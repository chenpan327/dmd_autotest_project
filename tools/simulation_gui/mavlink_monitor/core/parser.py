"""独立 MAVLink 消息解析器 — 不依赖 parse_mavlink.py

EAGER 阶段：parse_header() — 格式检测、头部解析、CRC 校验
LAZY  阶段：parse_fields() — struct 解包、数组合并、枚举解析
"""

from __future__ import annotations

import json
import socket
import struct
from pathlib import Path

from mavlink_monitor.core.model import FieldDetail, MessageRecord


# ── struct format char → C type name ─────────────────────────────
_STRUCT_TYPE_MAP: dict[str, str] = {
    "b": "int8_t",
    "B": "uint8_t",
    "h": "int16_t",
    "H": "uint16_t",
    "i": "int32_t",
    "I": "uint32_t",
    "q": "int64_t",
    "Q": "uint64_t",
    "f": "float",
    "d": "double",
    "c": "char",
    "s": "char",
    "p": "char",
    "?": "bool",
}

# struct 格式符中属于"聚合类型"的字符（Nc/Ns/Np 不展开为 N 个独立元素）
_AGGREGATE_FMT_CHARS: set[str] = {"s", "p", "c"}


def _extract_base_fmt(fmt_char: str) -> str:
    """从可能带数字前缀的格式符中提取基础类型字符。

    Example:
        "128s" → "s"
        "B"    → "B"
        "8f"   → "f"   （8f 已在 _expand_format 中展开，此处仅为防御）
    """
    # 去掉前导数字
    i = len(fmt_char) - 1
    while i >= 0 and "0" <= fmt_char[i] <= "9":
        i -= 1
    # i 现在指向字节序字符或基础类型字符
    if i >= 0 and fmt_char[i] in "<>!@=":
        return fmt_char[i + 1:] if i + 1 < len(fmt_char) else fmt_char
    return fmt_char[i] if i >= 0 else fmt_char

# ── 常见 MAVLink 变量名 → 枚举类别映射 ───────────────────────────
_VARIABLE_ENUM_MAP: dict[str, str] = {
    "type": "MAV_TYPE",
    "autopilot": "MAV_AUTOPILOT",
    "base_mode": "MAV_MODE_FLAG",
    "system_status": "MAV_STATE",
    "severity": "MAV_SEVERITY",
    "custom_mode": None,  # custom_mode 通常是位掩码，不映射枚举
    "mavlink_version": None,
}


# ═══════════════════════════════════════════════════════════════════
# MavlinkParser
# ═══════════════════════════════════════════════════════════════════
class MavlinkParser:
    """独立 MAVLink 消息解析器。

    特性：
        - 不依赖 parse_mavlink.py 等外部实现
        - 基于 JSON 配置文件（mavlink_config + mavlink_enums）
        - EAGER header 解析 + LAZY field 解析
        - 预计算 X.25 CRC 查找表
    """

    MAVLINK_MAGIC_V1 = 0xFE
    MAVLINK_MAGIC_V2 = 0xFD
    IP_PREFIX_LEN = 4

    # ─────────────────────────────────────────────────────────────
    # 初始化
    # ─────────────────────────────────────────────────────────────
    def __init__(self) -> None:
        self._config_cache: dict[str, dict[int, dict]] = {}
        self._enums_cache: dict[str, dict[str, dict[int, str]]] = {}
        self._cmd183_functions: list[dict] = []  # command=183 业务功能映射
        self._x25crc_table: list[int] = self._build_crc_table()
        self.crc_enabled: bool = False  # 默认不计算 CRC，提升吞吐
        self._active_version: str = "default"  # 当前已加载的配置版本

    # ─────────────────────────────────────────────────────────────
    # CRC 查找表
    # ─────────────────────────────────────────────────────────────
    @staticmethod
    def _build_crc_table() -> list[int]:
        """构建 X.25 CRC-16-CCITT 256 项查找表（多项式 0x1021）。"""
        table: list[int] = []
        for i in range(256):
            crc: int = i << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
            table.append(crc)
        return table

    def _x25crc(self, data: bytes) -> int:
        """对 data 计算 X.25 CRC-16（初始值 0xFFFF）。"""
        crc: int = 0xFFFF
        for byte in data:
            crc = ((crc << 8) ^ self._x25crc_table[((crc >> 8) ^ byte) & 0xFF]) & 0xFFFF
        return crc

    @staticmethod
    def _x25crc_static(data: bytes, table: list[int]) -> int:
        """静态版本：对 data 计算 X.25 CRC-16（初始值 0xFFFF）。"""
        crc: int = 0xFFFF
        for byte in data:
            crc = ((crc << 8) ^ table[((crc >> 8) ^ byte) & 0xFF]) & 0xFFFF
        return crc

    # ─────────────────────────────────────────────────────────────
    # 配置加载
    # ─────────────────────────────────────────────────────────────
    def load_config(self, config_path: str, version: str = "default") -> None:
        """加载 MAVLink 消息配置 JSON 文件。

        JSON 格式：
        {"messages": [{"msg_id": 0, "message_name": "...",
                       "struct_format": "<IBBBBB", "variables": [...],
                       "crc_extra": 50}, ...]}
        """
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cache: dict[int, dict] = {}
        for msg in data.get("messages", []):
            msg_id = msg["msg_id"]
            cache[msg_id] = {
                "message_name": msg["message_name"],
                "struct_format": msg["struct_format"],
                "variables": list(msg["variables"]),
                "crc_extra": msg["crc_extra"],
            }
        self._config_cache[version] = cache
        self._active_version = version  # 记录当前活跃版本

    def get_available_msgids(self) -> dict[int, str]:
        """返回已加载配置中所有消息的 {msg_id: message_name} 映射。"""
        cache = self._config_cache.get(self._active_version, {})
        return {msg_id: info["message_name"] for msg_id, info in cache.items()}

    def load_enums(self, enums_path: str, version: str = "default") -> None:
        """加载 MAVLink 枚举 JSON 文件。

        JSON 格式：
        {"MAV_AUTOPILOT": {"0": "MAV_AUTOPILOT_GENERIC", ...}, ...}
        """
        with open(enums_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        cache: dict[str, dict[int, str]] = {}
        for category, mapping in raw.items():
            parsed: dict[int, str] = {}
            for k, v in mapping.items():
                parsed[int(k)] = v
            cache[category] = parsed
        self._enums_cache[version] = cache

    def load_command_183_config(self, config_path: str) -> None:
        """加载 command=183 业务功能映射配置文件。

        JSON 格式：
        {"command": 183, "functions": [
            {"name": "点灯", "match": {"param7": 1}, "note": "..."},
            ...
        ]}
        """
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._cmd183_functions = data.get("functions", [])

    def match_command_183_business(self, fields: list[FieldDetail]) -> str:
        """根据解析后的字段列表匹配 command=183 业务功能名称。

        按配置文件中的顺序匹配，首个满足全部 match 条件的条目生效。
        param 值为 float，匹配时转为 int 比较。

        Returns:
            业务功能名称，未匹配返回空字符串。
        """
        if not self._cmd183_functions:
            return ""

        # 构建 param 名称 → FieldDetail 的映射
        field_map: dict[str, FieldDetail] = {}
        for f in fields:
            field_map[f.name] = f

        for entry in self._cmd183_functions:
            match = entry.get("match", {})
            if self._match_params(match, field_map):
                return entry.get("name", "")
        return ""

    @staticmethod
    def _match_params(match: dict, field_map: dict[str, FieldDetail]) -> bool:
        """检查所有 match 条件是否满足。"""
        for param_key, expected_val in match.items():
            field = field_map.get(param_key)
            if field is None:
                return False
            actual = field.value_raw
            if isinstance(actual, float):
                actual = int(actual)
            if actual != int(expected_val):
                return False
        return True

    # ─────────────────────────────────────────────────────────────
    # EAGER: parse_header
    # ─────────────────────────────────────────────────────────────
    def parse_header(
        self, data: bytes, src_addr: tuple[str, int], dst_addr: tuple[str, int],
        version: str | None = None, direction: str = "Rx",
    ) -> MessageRecord | None:
        """EAGER 阶段：格式检测 + 头部解析 + CRC 校验。

        Args:
            direction: "Rx" 或 "Tx"，由调用方根据网络上下文判定。

        Returns:
            MessageRecord（fields 为空）或 None（非 MAVLink 数据）。
        """
        if version is None:
            version = self._active_version
        # ── Step 1: 格式检测 ──
        format_type: str
        relay_ip: str = ""
        clean_data: bytes

        if not data:
            return None

        # MAVLink v2 帧（魔数 0xFD）暂不支持，直接拒绝避免误解析
        # v2 头部为 10 字节，与 v1 6 字节不兼容
        if data[0] == self.MAVLINK_MAGIC_V2:
            return None

        if data[0] == self.MAVLINK_MAGIC_V1:
            format_type = "standard"
            clean_data = data
        elif len(data) > self.IP_PREFIX_LEN and data[self.IP_PREFIX_LEN] in (
            self.MAVLINK_MAGIC_V1,
            self.MAVLINK_MAGIC_V2,
        ):
            format_type = "ip_prefixed"
            try:
                relay_ip = socket.inet_ntoa(data[0:4])
            except (OSError, struct.error):
                relay_ip = "?.?.?.?"
            clean_data = data[4:]
        else:
            return None

        # v2 魔数（0xFD）在 IP-prefixed 分支也需拒绝
        if clean_data[0] == self.MAVLINK_MAGIC_V2:
            return None

        # ── Step 2: 最小长度检查 ──
        if len(clean_data) < 8:
            return None

        # ── Step 3: 头部解析 ──
        start, length, seq_mav, sys_id, comp_id, msg_id = struct.unpack(
            "BBBBBB", clean_data[0:6]
        )

        payload_start = 6
        payload_end = payload_start + length
        crc_end = payload_end + 2

        if len(clean_data) < crc_end:
            return None  # 数据不足

        payload_bytes = clean_data[payload_start:payload_end]
        frame_crc = struct.unpack("<H", clean_data[payload_end:crc_end])[0]

        # ── Step 4: CRC 校验（可选，默认关闭）──
        config = self._config_cache.get(version, {}).get(msg_id)
        if self.crc_enabled and config is not None:
            crc_extra = config["crc_extra"]
            crc_data = clean_data[1:payload_end] + bytes([crc_extra])
            crc_computed = self._x25crc(crc_data)
            crc_ok = crc_computed == frame_crc
        else:
            crc_computed = 0
            crc_ok = True
            # frame_crc 保留数据包中的原始值（不校验但展示数值）

        # ── Step 5: 构建 MessageRecord ──
        msg_name = ""
        if config is not None:
            msg_name = config.get("message_name", "")

        record = MessageRecord(
            direction=direction,
            src_ip=src_addr[0],
            src_port=src_addr[1],
            dst_ip=dst_addr[0],
            dst_port=dst_addr[1],
            format_type=format_type,
            relay_ip=relay_ip,
            msg_id=msg_id,
            msg_name=msg_name,
            sys_id=sys_id,
            comp_id=comp_id,
            seq_mav=seq_mav,
            payload_len=length,
            start_byte=start,
            payload_bytes=payload_bytes,
            # payload_hex/payload_display 延迟计算 — 首次访问时从 payload_bytes 生成
            crc_ok=crc_ok,
            crc_expected=crc_computed,
            crc_actual=frame_crc,
            version=version,
        )
        return record

    @staticmethod
    def _truncate_hex(data: bytes, max_display: int = 16) -> str:
        """截断 hex 显示字符串。"""
        if len(data) <= max_display:
            return data.hex()
        return data[:max_display].hex() + "…"

    # ─────────────────────────────────────────────────────────────
    # LAZY: parse_fields
    # ─────────────────────────────────────────────────────────────
    def parse_fields(
        self, record: MessageRecord, version: str | None = None,
    ) -> list[FieldDetail]:
        """LAZY 阶段：struct 解包 + 数组合并 + 枚举解析。

        Returns:
            FieldDetail 列表。
        """
        if version is None:
            version = record.version
        config = self._config_cache.get(version, {}).get(record.msg_id)
        # 若 record.version 不匹配当前活跃版本，回退到活跃版本
        if config is None and version != self._active_version:
            config = self._config_cache.get(self._active_version, {}).get(record.msg_id)
            if config is not None:
                version = self._active_version
        if config is None:
            record.fields_parsed = True
            return []

        struct_format: str = config["struct_format"]
        variables: list[str] = config["variables"]
        enums = self._enums_cache.get(version, {})

        # ── Step 1: struct.unpack ──
        try:
            values = struct.unpack(struct_format, record.payload_bytes)
        except struct.error:
            record.fields_parsed = True
            return []

        # ── Step 2: 展开 struct_format 为独立格式符 ──
        individual_formats = self._expand_format(struct_format)

        # 值数量与展开格式符数量应一致（或至少不超出）
        if len(values) < len(individual_formats) or len(values) < len(variables):
            record.fields_parsed = True
            return []

        # ── Step 3: 分配到中间条目列表 ──
        raw_entries: list[dict] = []
        for i, var_name in enumerate(variables):
            fmt_char = individual_formats[i] if i < len(individual_formats) else "B"
            raw_val = values[i]
            # 解析 fmt_char 的基础类型（处理 "128s" 等多字符格式符）
            base_fmt_char = _extract_base_fmt(fmt_char)
            # 字符数组成员：将 unsigned char 显示为 "char"
            if "[" in var_name and base_fmt_char in ("B", "b"):
                type_name = "char"
            else:
                type_name = _STRUCT_TYPE_MAP.get(fmt_char, _STRUCT_TYPE_MAP.get(base_fmt_char, "unknown"))
            raw_entries.append({
                "var_name": var_name,
                "value": raw_val,
                "type_name": type_name,
                "fmt_char": fmt_char,
            })

        # ── Step 4: 合并数组变量（如 ssid[0]..ssid[7] → ssid） ──
        merged = self._merge_array_variables(raw_entries)

        # ── Step 5: 构建 FieldDetail + 枚举解析 ──
        fields: list[FieldDetail] = []
        for entry in merged:
            name = entry["var_name"]
            value = entry["value"]
            type_name = entry["type_name"]
            is_array = entry["is_array"]

            # 枚举解析
            value_display: str
            if is_array:
                value_display = value.hex() if isinstance(value, (bytes, bytearray)) else str(value)
            else:
                value_display = self._resolve_enum(name, value, enums)

            # 原始 hex（bytes 用空格分隔）
            if isinstance(value, (bytes, bytearray)):
                raw_hex = " ".join(f"{b:02X}" for b in value)
            elif isinstance(value, int):
                raw_hex = f"0x{value:X}"
            elif isinstance(value, float):
                raw_hex = f"{value:.6f}"
            else:
                raw_hex = str(value)

            fields.append(FieldDetail(
                name=name,
                value_raw=value,
                value_display=value_display,
                raw_hex=raw_hex,
                type_name=type_name,
                is_array=is_array,
            ))

        # 回填 record
        record.fields = fields
        record.fields_parsed = True
        return fields

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _expand_format(fmt: str) -> list[str]:
        """将复合 struct 格式展开为独立基本格式符列表。

        Example:
            "<IBBBBB" → ["I", "B", "B", "B", "B", "B"]
            "<HB8BB"  → ["H", "B", "B","B","B","B","B","B","B","B", "B"]
            "<2B3H"   → ["B","B", "H","H","H"]
            "<8fHBB128s" → ["f","f","f","f","f","f","f","f","H","B","B","128s"]

        注意：s/p/c 为聚合类型，不展开 Ns/Np/Nc → N 个独立元素。
        """
        result: list[str] = []
        i = 0
        n = len(fmt)
        while i < n:
            c = fmt[i]
            # 跳过字节序/对齐字符
            if c in "<>!@=":
                i += 1
                continue
            # 数字前缀 → 重复次数
            if "0" <= c <= "9":
                j = i
                while j < n and "0" <= fmt[j] <= "9":
                    j += 1
                count = int(fmt[i:j])
                i = j
                if i < n:
                    base = fmt[i]
                    # 聚合类型 (s/p/c) 不展开，保留完整格式符如 "128s"
                    if base in _AGGREGATE_FMT_CHARS:
                        result.append(f"{count}{base}")
                    else:
                        for _ in range(count):
                            result.append(base)
                    i += 1
            else:
                result.append(c)
                i += 1
        return result

    @staticmethod
    def _merge_array_variables(entries: list[dict]) -> list[dict]:
        """合并相邻同名数组变量。

        将 "ssid[0]", "ssid[1]", ... "ssid[7]" 合并为单个 "ssid": bytes 条目。
        仅合并字节大小的成员（uint8_t/char），float/int 等类型保留为独立条目。
        """
        import re

        # 判断 fmt_char 是否为字节大小的类型
        def _is_byte_type(fc: str) -> bool:
            base = _extract_base_fmt(fc)
            return base in ("B", "b", "c")

        merged: list[dict] = []
        # 第一遍：分组
        groups: dict[str, list[dict]] = {}
        group_order: list[str] = []

        for entry in entries:
            name = entry["var_name"]
            m = re.match(r"^(.+)\[\d+\]$", name)
            if m:
                base = m.group(1)
                if base not in groups:
                    groups[base] = []
                    group_order.append(base)
                groups[base].append(entry)
            else:
                merged.append(dict(entry, is_array=False))

        # 第二遍：合并数组组
        for base in group_order:
            group = groups[base]
            # 按索引排序
            indexed: list[tuple[int, dict]] = []
            for entry in group:
                m = re.match(r"^.+\[(\d+)\]$", entry["var_name"])
                idx = int(m.group(1)) if m else 0
                indexed.append((idx, entry))

            fmt_char = indexed[0][1]["fmt_char"]

            # 非字节类型不合并为 bytes，保留为独立条目
            if not _is_byte_type(fmt_char):
                for _, entry in indexed:
                    merged.append(dict(entry, is_array=False))
                continue

            # 基础类型名：优先使用条目已有的 type_name（如 "char"），否则映射
            count = len(indexed)
            first_type_name = indexed[0][1].get("type_name", "")
            if "char" in first_type_name.lower():
                base_type = "char"
            else:
                base_type = _STRUCT_TYPE_MAP.get(fmt_char, "unknown")
            type_name = f"{base_type}[{count}]"

            # 如果组只有 1 个元素，不合并为数组
            if count == 1:
                entry = dict(indexed[0][1])
                entry["is_array"] = False
                merged.append(entry)
                continue

            # 按索引构建 bytes
            indexed.sort(key=lambda x: x[0])
            int_values: list[int] = []
            for _, entry in indexed:
                val = entry["value"]
                if isinstance(val, int):
                    int_values.append(val & 0xFF)
                else:
                    int_values.append(0)

            merged.append({
                "var_name": base,
                "value": bytes(int_values),
                "type_name": type_name,
                "fmt_char": fmt_char,
                "is_array": True,
            })

        return merged

    @staticmethod
    def _resolve_enum(
        var_name: str, value: object, enums: dict[str, dict[int, str]],
    ) -> str:
        """将变量值解析为枚举名称显示字符串。

        Returns:
            "MAV_TYPE_QUADROTOR (2)" 或 "2" 这样的显示字符串。
        """
        if not isinstance(value, int):
            return str(value)

        enum_category = _VARIABLE_ENUM_MAP.get(var_name)
        if enum_category is None:
            return str(value)

        enum_dict = enums.get(enum_category)
        if enum_dict is None:
            return str(value)

        name = enum_dict.get(value)
        if name is not None:
            return f"{name} ({value})"
        return str(value)
