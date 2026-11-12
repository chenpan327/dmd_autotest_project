"""消息过滤器 — 过滤链与规则引擎

基于 MessageRecord 字段的灵活过滤系统，支持过滤模式（隐藏不匹配的行）
和高亮模式（标记匹配的行）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import MessageRecord


# ═══════════════════════════════════════════════════════════════
# FilterRule — 单条过滤/高亮规则
# ═══════════════════════════════════════════════════════════════
@dataclass
class FilterRule:
    """单条过滤规则。

    Attributes:
        field: 匹配字段，支持 "dir" | "ip" | "msgid" | "msgname" | "special" |
               "srcip" | "dstip" | "sysid" | "compid" | "search" | "crc"
        op: 比较操作符 — "eq" | "neq" | "contains" | "regex" | "in"
        value: 比较值（字符串形式）
        enabled: 是否启用
        is_highlight: True=高亮匹配行, False=隐藏不匹配行
        color: 高亮颜色 (R, G, B, A)
    """
    field: str
    op: str
    value: str
    enabled: bool = True
    is_highlight: bool = False
    color: tuple = (38, 79, 120, 255)


# ═══════════════════════════════════════════════════════════════
# FilterResult — 过滤结果
# ═══════════════════════════════════════════════════════════════
@dataclass
class FilterResult:
    """过滤操作的结果。

    Attributes:
        visible: 通过所有非高亮过滤规则的记录
        highlights: seq → 高亮颜色 的映射
    """
    visible: list[MessageRecord] = field(default_factory=list)
    highlights: dict[int, tuple] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# MessageFilter — 过滤器主类
# ═══════════════════════════════════════════════════════════════
class MessageFilter:
    """MAVLink 消息过滤链。

    规则按添加顺序依次执行：
    - 过滤规则 (is_highlight=False)：从可见集中移除不匹配的记录
    - 高亮规则 (is_highlight=True)：将匹配的记录加入高亮映射
    """

    def __init__(self):
        self._rules: list[FilterRule] = []

    # ── 规则管理 ──

    def add_rule(self, rule: FilterRule) -> None:
        """添加一条过滤规则到链尾。"""
        self._rules.append(rule)

    def remove_rule(self, index: int) -> None:
        """按索引删除一条规则。"""
        if 0 <= index < len(self._rules):
            self._rules.pop(index)

    def clear(self) -> None:
        """清空所有规则。"""
        self._rules.clear()

    # ── 过滤执行 ──

    def apply(self, records: list[MessageRecord]) -> FilterResult:
        """对所有记录执行完整过滤链。

        优化：单次遍历同时评估所有规则，避免 N 条规则产生 N-1 个中间列表。

        Args:
            records: 待过滤的消息记录列表

        Returns:
            FilterResult 包含可见记录和高亮映射
        """
        # 预分类规则：分离过滤规则和高亮规则
        filter_rules: list[FilterRule] = []
        highlight_rules: list[FilterRule] = []
        for rule in self._rules:
            if not rule.enabled:
                continue
            if rule.is_highlight:
                highlight_rules.append(rule)
            else:
                filter_rules.append(rule)

        # 无任何启用规则时快速返回
        if not filter_rules and not highlight_rules:
            return FilterResult(visible=list(records), highlights={})

        visible: list[MessageRecord] = []
        highlights: dict[int, tuple] = {}

        for r in records:
            # 评估所有过滤规则
            passed = True
            for rule in filter_rules:
                if not self._match_one(r, rule):
                    passed = False
                    break
            if passed:
                visible.append(r)
                # 仅对通过过滤的记录评估高亮规则
                for rule in highlight_rules:
                    if self._match_one(r, rule):
                        highlights[r.seq] = rule.color

        return FilterResult(visible=visible, highlights=highlights)

    # ── 单条匹配 ──

    def _match_one(self, record: MessageRecord, rule: FilterRule) -> bool:
        """判断单条记录是否匹配规则。

        根据 rule.field 分发到对应的匹配逻辑。
        """
        field = rule.field
        op = rule.op
        value = rule.value

        if field == "dir":
            return self._match_dir(record, op, value)
        elif field == "ip":
            return self._match_ip(record, op, value)
        elif field == "source":
            return self._match_source(record, op, value)
        elif field == "msgid":
            return self._match_msgid(record, op, value)
        elif field == "msgname":
            return self._match_msgname(record, op, value)
        elif field == "special":
            return self._match_special(record, value)
        elif field == "srcip":
            return self._match_srcip(record, op, value)
        elif field == "dstip":
            return self._match_dstip(record, op, value)
        elif field == "relayip":
            return self._match_relayip(record, op, value)
        elif field == "sysid":
            return self._match_sysid(record, op, value)
        elif field == "compid":
            return self._match_compid(record, op, value)
        elif field == "search":
            return self._match_search(record, op, value)
        elif field == "crc":
            return self._match_crc(record, value)
        else:
            return False

    # ── 各字段匹配逻辑 ──

    @staticmethod
    def _match_dir(record: MessageRecord, op: str, value: str) -> bool:
        """匹配方向字段。"""
        if op == "eq":
            return record.direction == value
        elif op == "neq":
            return record.direction != value
        return False

    @staticmethod
    def _match_ip(record: MessageRecord, op: str, value: str) -> bool:
        """匹配 IP（同时检查 src_ip 和 dst_ip）。"""
        if op == "in":
            ips = {x.strip() for x in value.split(",") if x.strip()}
            return record.src_ip in ips or record.dst_ip in ips
        elif op == "contains":
            return value in record.src_ip or value in record.dst_ip
        return False

    @staticmethod
    def _match_source(record: MessageRecord, op: str, value: str) -> bool:
        """匹配来源类型字段 (nic / udp)。"""
        if op == "eq":
            return record.source_type == value
        elif op == "neq":
            return record.source_type != value
        return False

    @staticmethod
    def _match_msgid(record: MessageRecord, op: str, value: str) -> bool:
        """匹配消息 ID 字段。"""
        if op == "eq":
            try:
                return record.msg_id == int(value)
            except ValueError:
                return False
        elif op == "in":
            try:
                ids = {int(x.strip()) for x in value.split(",") if x.strip()}
                return record.msg_id in ids
            except ValueError:
                return False
        return False

    @staticmethod
    def _match_msgname(record: MessageRecord, op: str, value: str) -> bool:
        """匹配消息名称字段。"""
        if op == "contains":
            return value.lower() in record.msg_name.lower()
        elif op == "regex":
            try:
                return bool(re.search(value, record.msg_name, re.IGNORECASE))
            except re.error:
                return False
        return False

    @staticmethod
    def _match_special(record: MessageRecord, value: str) -> bool:
        """匹配特殊格式 (ip_prefixed) 字段。

        value 为 "1"/"true"/"yes" 时只匹配 ip_prefixed 格式，
        为空/"0"/"false"/"no" 时只匹配 standard 格式。
        """
        want_special = value.lower() in ("1", "true", "yes")
        is_special = record.format_type == "ip_prefixed"
        return is_special if want_special else not is_special

    @staticmethod
    def _match_srcip(record: MessageRecord, op: str, value: str) -> bool:
        """匹配源 IP 字段。"""
        if op == "in":
            ips = {x.strip() for x in value.split(",") if x.strip()}
            return record.src_ip in ips
        elif op == "contains":
            return value in record.src_ip
        elif op == "regex":
            try:
                return bool(re.search(value, record.src_ip))
            except re.error:
                return False
        return False

    @staticmethod
    def _match_dstip(record: MessageRecord, op: str, value: str) -> bool:
        """匹配目标 IP 字段。"""
        if op == "in":
            ips = {x.strip() for x in value.split(",") if x.strip()}
            return record.dst_ip in ips
        elif op == "contains":
            return value in record.dst_ip
        elif op == "regex":
            try:
                return bool(re.search(value, record.dst_ip))
            except re.error:
                return False
        return False

    @staticmethod
    def _match_relayip(record: MessageRecord, op: str, value: str) -> bool:
        """匹配真实目标 IP（relay_ip）字段。"""
        if op == "in":
            ips = {x.strip() for x in value.split(",") if x.strip()}
            return record.relay_ip in ips
        elif op == "contains":
            return value in record.relay_ip
        elif op == "regex":
            try:
                return bool(re.search(value, record.relay_ip))
            except re.error:
                return False
        return False

    @staticmethod
    def _match_sysid(record: MessageRecord, op: str, value: str) -> bool:
        """匹配系统 ID 字段。"""
        if op == "eq":
            try:
                return record.sys_id == int(value)
            except ValueError:
                return False
        return False

    @staticmethod
    def _match_compid(record: MessageRecord, op: str, value: str) -> bool:
        """匹配组件 ID 字段。"""
        if op == "eq":
            try:
                return record.comp_id == int(value)
            except ValueError:
                return False
        return False

    @staticmethod
    def _match_search(record: MessageRecord, op: str, value: str) -> bool:
        """全文搜索匹配 — 在所有字符串字段中搜索。"""
        text = MessageFilter._get_searchable_text(record)
        if op == "contains":
            return value.lower() in text.lower()
        elif op == "regex":
            try:
                return bool(re.search(value, text, re.IGNORECASE))
            except re.error:
                return False
        return False

    @staticmethod
    def _match_crc(record: MessageRecord, value: str) -> bool:
        """匹配 CRC 状态。

        value 为 "fail"/"false"/"0" 时匹配 CRC 失败记录，
        为 "ok"/"true"/"1"/"pass" 时匹配 CRC 成功记录。
        """
        want_fail = value.lower() in ("fail", "false", "0")
        return (not record.crc_ok) if want_fail else record.crc_ok

    @staticmethod
    def _get_searchable_text(record: MessageRecord) -> str:
        """生成记录的可搜索文本（拼接所有可读字段）。"""
        parts = [
            record.direction,
            record.src_ip,
            record.dst_ip,
            record.format_type,
            record.msg_name,
            record.source_type,
            record.node_id,
            record.relay_ip,
            str(record.msg_id),
            f"0x{record.msg_id:02X}",
            str(record.sys_id),
            str(record.comp_id),
            str(record.seq),
            record.payload_hex,
            record.payload_display,
        ]
        if record.payload_bytes:
            parts.append(record.payload_bytes.hex())
        return "\n".join(parts)

    # ═══════════════════════════════════════════════════════════
    # 预置工厂方法
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def preset_heartbeat() -> "MessageFilter":
        """仅显示心跳消息 (msg_id=0)。"""
        f = MessageFilter()
        f.add_rule(FilterRule(field="msgid", op="eq", value="0"))
        return f

    @staticmethod
    def preset_identify() -> "MessageFilter":
        """仅显示识别消息 (msg_id=2,3)。"""
        f = MessageFilter()
        f.add_rule(FilterRule(field="msgid", op="in", value="2,3"))
        return f

    @staticmethod
    def preset_crc_fail() -> "MessageFilter":
        """高亮 CRC 校验失败的消息。"""
        f = MessageFilter()
        f.add_rule(FilterRule(
            field="crc", op="eq", value="fail",
            is_highlight=True, color=(255, 80, 80, 255),
        ))
        return f

    @staticmethod
    def preset_direction(dir: str) -> "MessageFilter":
        """仅显示指定方向 (Rx 或 Tx) 的消息。"""
        f = MessageFilter()
        f.add_rule(FilterRule(field="dir", op="eq", value=dir))
        return f

    @staticmethod
    def preset_special_format() -> "MessageFilter":
        """仅显示 ip_prefixed 特殊格式消息。"""
        f = MessageFilter()
        f.add_rule(FilterRule(field="special", op="eq", value="1"))
        return f
