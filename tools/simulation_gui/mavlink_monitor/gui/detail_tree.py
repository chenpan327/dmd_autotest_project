"""字段详情树 — QTreeWidget 显示选中消息的字段"""

from __future__ import annotations
from typing import TYPE_CHECKING
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QHeaderView, QMenu, QApplication,
)
from PySide6.QtGui import QColor, QAction

if TYPE_CHECKING:
    from ..core.model import MessageRecord

_PAYLOAD_DISPLAY_MAX = 60  # 标题行 payload 截断长度


def _hex_to_ascii(hex_str: str) -> str:
    h = hex_str.replace(" ", "")
    chars = []
    for i in range(0, len(h), 2):
        try:
            b = int(h[i:i+2], 16)
        except (ValueError, IndexError):
            continue
        if b == 0:       chars.append("\\0")
        elif 32 <= b <= 126: chars.append(chr(b))
        else:            chars.append(".")
    return "'" + "".join(chars) + "'"


def _trunc_payload(hex_str: str, max_len: int = _PAYLOAD_DISPLAY_MAX) -> str:
    """截断 hex 字符串用于标题行显示。"""
    h = hex_str.replace(" ", "")
    if len(h) <= max_len:
        return h
    return h[:max_len] + "…"


class DetailTree(QTreeWidget):
    """底部字段详情树。"""

    def __init__(self):
        super().__init__()
        self.setHeaderLabels(["字段名", "解析值", "原始值 (Hex)", "类型"])
        self.setColumnWidth(0, 120)
        self.setColumnWidth(1, 200)
        self.setColumnWidth(2, 150)
        self.setColumnWidth(3, 80)
        self.setAlternatingRowColors(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        self._full_payload: str = ""
        self._record: "MessageRecord | None" = None

    def show_fields(self, msg_info: str, fields: list,
                    payload_hex: str = "",
                    record: "MessageRecord | None" = None) -> None:
        """显示字段列表。

        Args:
            msg_info: 标题文本（如 "HEARTBEAT #42"）
            fields: FieldDetail 列表
            payload_hex: 原始 payload 十六进制字符串
            record: MessageRecord 对象（用于右键复制完整消息）
        """
        self.clear()
        self._full_payload = payload_hex.replace(" ", "")
        self._record = record

        # 标题行：消息信息 | Payload(截断) | (空) | (空)
        payload_display = _trunc_payload(payload_hex) if payload_hex else ""
        title = QTreeWidgetItem([msg_info, payload_display, "", ""])
        title.setForeground(0, QColor(60, 150, 235))
        col1_color = QColor(180, 180, 180) if "…" in payload_display else QColor(120, 120, 120)
        title.setForeground(1, col1_color)
        self.addTopLevelItem(title)

        for f in fields:
            item = QTreeWidgetItem([f.name, f.value_display, f.raw_hex, f.type_name])
            item.setForeground(0, QColor(60, 150, 235))
            self.addTopLevelItem(item)

            if f.business_hint:
                hint_item = QTreeWidgetItem(
                    ["  └ 业务功能", f.business_hint, "", ""])
                hint_item.setForeground(0, QColor(75, 75, 75))
                hint_item.setForeground(1, QColor(50, 210, 170))
                self.addTopLevelItem(hint_item)

            if f.is_array:
                ascii_item = QTreeWidgetItem(
                    ["  -> ASCII", _hex_to_ascii(f.raw_hex), "", ""])
                ascii_item.setForeground(0, QColor(75, 75, 75))
                ascii_item.setForeground(1, QColor(80, 175, 60))
                self.addTopLevelItem(ascii_item)

        self.expandAll()

    def clear_fields(self) -> None:
        self._full_payload = ""
        self._record = None
        self.clear()

    # ── 右键菜单：复制完整 MAVLink 消息 ──
    def _on_context_menu(self, pos) -> None:
        if self._record is None:
            return

        menu = QMenu(self)
        copy_action = QAction("复制完整 MAVLink 消息", self)
        copy_action.triggered.connect(self._copy_full_message)
        menu.addAction(copy_action)
        menu.exec(self.viewport().mapToGlobal(pos))

    def _copy_full_message(self) -> None:
        """将完整 MAVLink 消息（含帧头、CRC 等）复制到剪贴板。"""
        if self._record is not None:
            QApplication.clipboard().setText(self._record.format_complete())
