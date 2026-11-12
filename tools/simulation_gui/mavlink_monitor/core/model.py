"""监控数据模型 — 环形缓冲 + MessageRecord

线程安全设计：所有写操作由 MonitorEngine 的工作线程执行（单生产者），
GUI 主线程只读（单消费者），使用 collections.deque + Lock 保护。
"""

from __future__ import annotations

import time
import threading
from collections import deque
from dataclasses import dataclass, field
from itertools import islice


# ═══════════════════════════════════════════════════════════════
# FieldDetail — 单个字段的解析结果
# ═══════════════════════════════════════════════════════════════
@dataclass
class FieldDetail:
    """MAVLink 消息中单个字段的解析详情。"""
    name: str               # 字段名（如 "type", "ssid"）
    value_raw: object       # 原始解析值（int / float / bytes）
    value_display: str      # 可读显示值（含枚举映射）
    raw_hex: str            # 原始十六进制表示
    type_name: str          # 类型名（如 "uint8_t", "char[8]"）
    is_array: bool = False  # 是否为数组/字符数组
    business_hint: str = ""  # 业务功能提示（如 command=183 映射）


# ═══════════════════════════════════════════════════════════════
# MessageRecord — 单条 MAVLink 消息的完整记录
# ═══════════════════════════════════════════════════════════════
@dataclass
class MessageRecord:
    """单条 MAVLink 消息的完整解析记录。

    Phase 1（header 解析）填充除 fields 外的所有字段。
    Phase 2（lazy parse）由用户触发后填充 fields。
    """

    # ── 元数据 ──
    seq: int = 0                          # 全局自增序号
    timestamp_abs: float = 0.0            # 绝对时间戳（time.time()）
    timestamp_rel: float = 0.0            # 相对首条消息的时间
    direction: str = "Rx"                 # "Rx" | "Tx"

    # ── 网络地址 ──
    src_ip: str = ""
    src_port: int = 0
    dst_ip: str = ""
    dst_port: int = 0

    # ── 格式信息 ──
    format_type: str = "standard"         # "standard" | "ip_prefixed"
    relay_ip: str = ""                    # 特殊格式：4 字节 IP 前缀，普通格式为空

    # ── MAVLink 头部 ──
    msg_id: int = 0
    msg_name: str = ""                    # 如 "MAVLink_heartbeat_message"
    sys_id: int = 0
    comp_id: int = 0
    seq_mav: int = 0                      # MAVLink 帧内 seq
    payload_len: int = 0
    start_byte: int = 0xFE

    # ── Payload ──
    payload_bytes: bytes = b""            # 原始 payload 字节（lazy parse 用）
    _payload_hex: str = field(default="", init=False, repr=False)     # Payload 完整十六进制（延迟计算缓存）
    _payload_display: str = field(default="", init=False, repr=False) # Payload
    _payload_set: bool = field(default=False, init=False, repr=False)  # 截断显示（延迟计算缓存）

    # ── CRC ──
    crc_ok: bool = True
    crc_expected: int = 0
    crc_actual: int = 0

    # ── 字段（lazy）──
    fields: list[FieldDetail] = field(default_factory=list)
    fields_parsed: bool = False            # 是否已完成 Phase 2 解析

    # ── 来源 ──
    node_id: str = ""                      # 来源监控节点 ID (如 "nic_WLAN", "udp_0.0.0.0:14550")
    source_type: str = "nic"               # 来源类型: "nic" | "udp"
    version: str = "default"               # MAVLink 配置版本

    # ── 电台 DAV Ack 帧（msg_type=1）──
    dav_report: int | None = None          # DAV Ack 帧的 report 字段（0=DAV_NO_ERROR，非 0=失败码）；Msg 帧为 None

    @property
    def crc_display(self) -> str:
        """CRC 显示字符串。"""
        if self.crc_actual == 0 and self.crc_expected == 0:
            return "—"  # CRC 未计算
        if self.crc_ok:
            return f"OK 0x{self.crc_actual:04X}"
        return f"FAIL 0x{self.crc_actual:04X}"

    @property
    def msg_id_hex(self) -> str:
        return f"0x{self.msg_id:02X}"

    # ── payload_hex / payload_display 延迟计算（首次访问从 payload_bytes 生成）──
    _PAYLOAD_HEX_MAX_DISPLAY: int = 16

    @property
    def payload_hex(self) -> str:
        if not self._payload_set and self.payload_bytes:
            self._payload_hex = self.payload_bytes.hex()
        return self._payload_hex

    @payload_hex.setter
    def payload_hex(self, value: str) -> None:
        self._payload_hex = value
        self._payload_set = True

    @property
    def payload_display(self) -> str:
        if not self._payload_set and self.payload_bytes:
            data = self.payload_bytes
            if len(data) <= self._PAYLOAD_HEX_MAX_DISPLAY:
                self._payload_display = data.hex()
            else:
                self._payload_display = data[:self._PAYLOAD_HEX_MAX_DISPLAY].hex() + "…"
        return self._payload_display

    @payload_display.setter
    def payload_display(self, value: str) -> None:
        self._payload_display = value

    @property
    def has_relay_ip(self) -> bool:
        return self.format_type == "ip_prefixed" and bool(self.relay_ip)

    def format_complete(self) -> str:
        """格式化完整 MAVLink 消息用于复制。

        包含帧头(start_byte)、sys、comp、len、msgid、crc 等全部字段。
        """
        from datetime import datetime

        lines = []
        lines.append("══ MAVLink Message ══")
        lines.append(f"Seq:       #{self.seq}")
        lines.append(f"Time:      {datetime.fromtimestamp(self.timestamp_abs).strftime('%Y-%m-%d %H:%M:%S.%f')}")
        lines.append(f"Direction: {self.direction}")
        lines.append(f"Source:    {self.src_ip}:{self.src_port}")
        lines.append(f"Target:    {self.dst_ip}:{self.dst_port}")
        if self.has_relay_ip:
            lines.append(f"Relay IP:  {self.relay_ip}")

        lines.append("Frame Header:")
        lines.append(f"  Start:   0x{self.start_byte:02X}")
        lines.append(f"  Len:     {self.payload_len}")
        lines.append(f"  Seq:     {self.seq_mav}")
        lines.append(f"  Sys:     {self.sys_id}")
        lines.append(f"  Comp:    {self.comp_id}")
        lines.append(f"  MsgID:   {self.msg_id_hex} ({self.msg_name or 'UNKNOWN'})")

        payload = self.payload_hex.replace(" ", "")
        if len(payload) > 128:
            payload = payload[:128] + "…"
        lines.append(f"Payload:  {payload}")

        crc_status = "OK" if self.crc_ok else "FAIL"
        lines.append(f"CRC:      0x{self.crc_actual:04X} ({crc_status})")

        if self.format_type == "ip_prefixed":
            lines.append(f"Format:   ip_prefixed")
        if self.node_id:
            lines.append(f"Node:     {self.node_id}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# MonitorModel — 线程安全环形缓冲
# ═══════════════════════════════════════════════════════════════
class MonitorModel:
    """线程安全环形缓冲，存储 MessageRecord。

    特性：
        - 基于 deque(maxlen=capacity) 的环形缓冲
        - 单生产者（Engine 线程 append）单消费者（GUI 线程 read）
        - 自增 seq 计数器
        - 首条消息时间戳用于计算相对时间
    """

    def __init__(self, capacity: int = 4096000):
        self._capacity = capacity
        self._records: deque[MessageRecord] = deque(maxlen=capacity)  # 环形缓冲，自动淘汰旧记录
        self._lock = threading.Lock()
        self._seq_counter: int = 0
        self._first_timestamp: float | None = None
        self._error_count: int = 0
        self._total_count: int = 0
        self._crc_fail_count: int = 0

    # ── 写入 ──
    def append(self, record: MessageRecord, *,
               is_error: bool = False,
               is_crc_fail: bool = False) -> None:
        """添加一条记录（线程安全），可选一并更新错误/CRC计数。

        优化：将 mark_error/mark_crc_fail 合并到一次锁内完成，
        避免引擎热路径中每条消息 2-3 次锁获取。
        """
        record.timestamp_abs = time.time()
        if self._first_timestamp is None:
            self._first_timestamp = record.timestamp_abs
        record.timestamp_rel = record.timestamp_abs - self._first_timestamp

        with self._lock:
            self._seq_counter += 1
            record.seq = self._seq_counter
            self._records.append(record)
            self._total_count += 1
            if is_error:
                self._error_count += 1
            if is_crc_fail:
                self._crc_fail_count += 1

    # ── 批量写入（高性能路径：一次锁写入 N 条，减少锁竞争）──
    def append_batch(self, records: list[MessageRecord]) -> None:
        """批量添加记录（线程安全），一次锁完成全部写入。

        使用场景：5000 msg/s 下，单条 append 产生 5000 次锁获取；
        批量写入（如每 64 条刷一次）可将锁获取降至 ~78 次/s。
        """
        if not records:
            return
        now = time.time()
        if self._first_timestamp is None:
            self._first_timestamp = now
        with self._lock:
            for record in records:
                record.timestamp_abs = now
                record.timestamp_rel = now - self._first_timestamp
                self._seq_counter += 1
                record.seq = self._seq_counter
                self._records.append(record)
            self._total_count += len(records)

    def mark_error(self) -> None:
        with self._lock:
            self._error_count += 1

    def mark_crc_fail(self) -> None:
        with self._lock:
            self._crc_fail_count += 1

    # ── 读取 ──
    def get_all(self) -> list[MessageRecord]:
        """获取所有记录的快照。"""
        with self._lock:
            return list(self._records)

    def get_latest(self, n: int = 200) -> list[MessageRecord]:
        """获取最近 n 条记录。

        优化：使用反向迭代器从尾部取元素，O(n) 而非 O(total)。
        deque 正向 islice(total-n, total) 需遍历 total 个元素；
        reversed + islice 仅遍历 n 个元素。
        """
        with self._lock:
            total = len(self._records)
            if total <= n:
                return list(self._records)
            # 从 deque 尾部反向迭代 n 个元素，再反转回正序
            return list(islice(reversed(self._records), n))[::-1]

    def get_since(self, seq: int) -> list[MessageRecord]:
        """获取 seq > 指定值的所有新记录。

        优化：新记录总是在尾部追加，从尾部倒序遍历，
        遇到 seq <= 目标值即停止，避免 O(n) 全量扫描。
        """
        with self._lock:
            result: list[MessageRecord] = []
            for r in reversed(self._records):
                if r.seq <= seq:
                    break
                result.append(r)
            result.reverse()
            return result

    def get_by_seq(self, seq: int) -> MessageRecord | None:
        """按 seq 获取单条记录。"""
        with self._lock:
            for r in self._records:
                if r.seq == seq:
                    return r
        return None

    # ── 统计 ──
    @property
    def count(self) -> int:
        return len(self._records)

    @property
    def total(self) -> int:
        return self._total_count

    @property
    def errors(self) -> int:
        return self._error_count

    @property
    def crc_failures(self) -> int:
        return self._crc_fail_count

    @property
    def latest_seq(self) -> int:
        return self._seq_counter

    @property
    def buffer_usage(self) -> tuple[int, int]:
        """返回 (used, capacity)。"""
        return (len(self._records), self._capacity)

    def clear(self) -> None:
        """清空缓冲（保留计数器）。"""
        with self._lock:
            self._records.clear()

    def reset(self) -> None:
        """完全重置（含计数器）。"""
        with self._lock:
            self._records.clear()
            self._seq_counter = 0
            self._first_timestamp = None
            self._error_count = 0
            self._total_count = 0
            self._crc_fail_count = 0

    def reset_stats(self) -> None:
        """仅重置统计计数器，不清空缓冲。"""
        with self._lock:
            self._error_count = 0
            self._total_count = 0
            self._crc_fail_count = 0
