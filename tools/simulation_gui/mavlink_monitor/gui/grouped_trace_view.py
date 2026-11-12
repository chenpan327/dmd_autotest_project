"""CANoe-style 分组消息树 — QTreeWidget 按 (src_ip, dst_ip, msg_id) 分组

列布局（12 列）:
  分组节点: Src IP | Dst IP | Message（列 0-2）
  子消息:   Time(Rel) | Time(Abs) | Ports | MsgID | Sys | Comp | Len | Payload | CRC（列 3-11）
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTreeWidget, QTreeWidgetItem, QMenu, QApplication,
)
from PySide6.QtGui import QColor, QFont, QAction

# ═══════════════════════════════════════════════════════
# 颜色常量
# ═══════════════════════════════════════════════════════
C_DIR_RX   = QColor(50,  210, 170)
C_DIR_TX   = QColor(230, 130, 90)
C_HEART    = QColor(60,  150, 235)
C_IDENT    = QColor(210, 120, 200)
C_CMD      = QColor(210, 180, 40)
C_RADIO    = QColor(0,   180, 180)   # 电台 DAV 消息：青蓝色
C_DEFAULT  = QColor(0, 0, 0)
C_SEC      = QColor(105, 105, 105)
C_GRP_BG   = QColor(235, 242, 250)
C_GRP_FG   = QColor(25,  35,  65)

_PAYLOAD_MAX = 26
_ROLE_RECORD   = Qt.ItemDataRole.UserRole
_ROLE_GROUP_KEY = Qt.ItemDataRole.UserRole + 1

_TIME_LABELS = ["时间: 绝对", "时间: 相对"]

# ── 列定义: (header, width) ──
_COLUMNS = [
    ("Src IP",       140),   # 0  分组
    ("Dst IP",       140),   # 1  分组
    ("Message",      180),   # 2  分组+子消息
    ("Time(Rel)",    160),   # 3  子消息 相对时间
    ("Time(Abs)",    160),   # 4  子消息 绝对时间（默认隐藏）
    ("Ports",        115),   # 5  子消息
    ("MsgID",         55),   # 6  子消息
    ("Sys",           40),   # 7  子消息
    ("Comp",          44),   # 8  子消息
    ("Len",           40),   # 9  子消息
    ("Payload",      170),   # 10 子消息
    ("CRC",           80),   # 11 子消息 (stretchLastSection)
]

COL_SRC_IP    = 0
COL_DST_IP    = 1
COL_MESSAGE   = 2
COL_TIME_REL  = 3
COL_TIME_ABS  = 4
COL_PORTS     = 5
COL_MSGID     = 6
COL_SYS       = 7
COL_COMP      = 8
COL_LEN       = 9
COL_PAYLOAD   = 10
COL_CRC       = 11
_GRP_COLS     = 3


from mavlink_monitor.gui.utils import fmt_rel as _fmt_rel, fmt_abs as _fmt_abs


@dataclass
class _GroupInfo:
    tree_item: QTreeWidgetItem
    records: deque = field(default_factory=deque)
    count: int = 0
    last_timestamp_abs: float = 0.0


class GroupedTraceView(QWidget):
    """CANoe 风格分组消息树视图。"""

    on_record_clicked = Signal(object)
    on_pause = Signal(bool)
    _record_added = Signal(object)       # 内部：线程安全调度

    def __init__(self, parent=None, display_limit: int = 10000, max_groups: int = 5000):
        super().__init__(parent)
        self._groups: dict[tuple, _GroupInfo] = {}
        self._total_msg_count = 0
        self._display_limit = display_limit
        self._max_groups = max_groups
        self._scroll_paused = False
        self._time_mode = 1       # 0=abs, 1=rel(default)
        # 最小堆：(first_msg_timestamp, group_key)，用于 O(log g) 淘汰最老 group
        self._group_heap: list[tuple[float, tuple]] = []

        ly = QVBoxLayout(self)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(2)

        # ── 工具栏（可由外部接管）──
        self._toolbar = QHBoxLayout()
        self._toolbar.setSpacing(4)

        self._pause_btn = QPushButton("|| 暂停")
        self._pause_btn.clicked.connect(self._toggle_pause)
        self._toolbar.addWidget(self._pause_btn)

        self._clear_btn = QPushButton("清空")
        self._clear_btn.clicked.connect(self.clear)
        self._toolbar.addWidget(self._clear_btn)

        self._time_btn = QPushButton(_TIME_LABELS[self._time_mode])
        self._time_btn.clicked.connect(self._toggle_time)
        self._toolbar.addWidget(self._time_btn)

        self._toolbar.addStretch()
        ly.addLayout(self._toolbar)

        # ── 树 ──
        self._tree = QTreeWidget()
        self._tree.setColumnCount(len(_COLUMNS))
        self._tree.setHeaderLabels([c[0] for c in _COLUMNS])
        for i, (_, w) in enumerate(_COLUMNS):
            self._tree.setColumnWidth(i, w)
        self._tree.setColumnHidden(COL_TIME_ABS, True)  # Abs 默认隐藏
        self._tree.setSelectionMode(self._tree.SelectionMode.SingleSelection)
        self._tree.setEditTriggers(self._tree.EditTrigger.NoEditTriggers)
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setAnimated(True)
        self._tree.header().setStretchLastSection(True)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

        ly.addWidget(self._tree, 1)

        # 线程安全：内部信号 → _add_record_impl
        self._record_added.connect(self._add_record_impl)

    # ═══════════════════════════════════════════════════
    # 核心操作
    # ═══════════════════════════════════════════════════
    def add_record(self, record) -> None:
        """线程安全的 add_record：非主线程调用自动排队到主线程。"""
        if QThread.currentThread() != QApplication.instance().thread():
            self._record_added.emit(record)  # 信号跨线程自动排队
            return
        self._add_record_impl(record)

    def _add_record_impl(self, record) -> None:
        if self._scroll_paused:
            return

        group_key = (record.src_ip, record.dst_ip, record.msg_id)
        info = self._groups.get(group_key)

        if info is None:
            if len(self._groups) >= self._max_groups:
                self._remove_oldest_group()
                if len(self._groups) >= self._max_groups:
                    return
            info = self._create_group(record, group_key)

        self._create_child_item(record, info.tree_item)
        info.records.append(record)
        info.count += 1
        info.last_timestamp_abs = record.timestamp_abs
        self._total_msg_count += 1
        self._update_group_summary(info, record)

        if self._total_msg_count > self._display_limit:
            self.trim_messages(self._display_limit)

    def trim_messages(self, max_total: int) -> None:
        while self._total_msg_count > max_total:
            oldest_key = self._find_oldest_group_key()
            if oldest_key is None:
                break
            self._pop_oldest_from_group(oldest_key)

    def clear(self) -> None:
        self._tree.clear()
        self._groups.clear()
        self._total_msg_count = 0
        self._group_heap.clear()

    def set_display_limit(self, limit: int) -> None:
        self._display_limit = limit

    def set_max_groups(self, max_groups: int) -> None:
        self._max_groups = max_groups

    # ── 自动滚动 ──
    def is_at_bottom(self, threshold: int = 5) -> bool:
        """判断滚动条是否在底部（容差 threshold px）。"""
        sb = self._tree.verticalScrollBar()
        return sb.value() >= sb.maximum() - threshold

    def scroll_to_bottom(self) -> None:
        """滚动到树视图最底部。"""
        self._tree.scrollToBottom()

    @property
    def scroll_paused(self) -> bool:
        return self._scroll_paused

    @scroll_paused.setter
    def scroll_paused(self, paused: bool) -> None:
        self._scroll_paused = paused
        self._pause_btn.setText("> 恢复" if self._scroll_paused else "|| 暂停")

    @property
    def time_mode(self) -> int:
        """0=绝对时间, 1=相对时间（默认）。"""
        return self._time_mode

    @time_mode.setter
    def time_mode(self, mode: int) -> None:
        """设置时间模式并同步更新树列可见性。"""
        self._time_mode = mode
        self._tree.setColumnHidden(COL_TIME_REL, mode == 0)
        self._tree.setColumnHidden(COL_TIME_ABS, mode == 1)
        self._time_btn.setText(_TIME_LABELS[mode])

    @property
    def toolbar_visible(self) -> bool:
        for i in range(self._toolbar.count()):
            w = self._toolbar.itemAt(i).widget()
            if w is not None and w.isVisible():
                return True
        return False

    @toolbar_visible.setter
    def toolbar_visible(self, v: bool) -> None:
        for i in range(self._toolbar.count()):
            w = self._toolbar.itemAt(i).widget()
            if w is not None:
                w.setVisible(v)

    @property
    def total_messages(self) -> int:
        return self._total_msg_count

    @property
    def total_groups(self) -> int:
        return len(self._groups)

    @property
    def display_limit(self) -> int:
        return self._display_limit

    # ═══════════════════════════════════════════════════
    # 内部 — 分组管理
    # ═══════════════════════════════════════════════════
    def _create_group(self, record, group_key: tuple) -> _GroupInfo:
        item = QTreeWidgetItem(self._tree)
        item.setData(0, _ROLE_GROUP_KEY, group_key)

        bold_font = QFont()
        bold_font.setBold(True)
        for c in range(_GRP_COLS):
            item.setBackground(c, C_GRP_BG)
            item.setFont(c, bold_font)
            item.setForeground(c, C_GRP_FG)

        info = _GroupInfo(tree_item=item)
        self._groups[group_key] = info
        self._update_group_summary(info, record)
        # 推入最小堆用于 O(log g) 淘汰
        heapq.heappush(self._group_heap, (record.timestamp_abs, group_key))
        return info

    def _create_child_item(self, record, parent: QTreeWidgetItem) -> None:
        child = QTreeWidgetItem(parent)
        dir_color = C_DIR_RX if record.direction == "Rx" else C_DIR_TX
        msg_name = record.msg_name or f"MSG_{record.msg_id}"
        msg_color = self._msg_color(record.msg_name)

        # 列 2: Message（复用分组 Message 列）
        child.setText(COL_MESSAGE, msg_name)
        child.setForeground(COL_MESSAGE, msg_color)
        child.setData(COL_MESSAGE, _ROLE_RECORD, record)

        # 列 3-11: 子消息专有列
        col_defs = [
            (COL_TIME_REL, _fmt_rel(record.timestamp_rel), C_DEFAULT),
            (COL_TIME_ABS, _fmt_abs(record.timestamp_abs), C_DEFAULT),
            (COL_PORTS,    f"{record.src_port}->{record.dst_port}", dir_color),
            (COL_MSGID,    record.msg_id_hex, C_SEC),
            (COL_SYS,      str(record.sys_id), C_SEC),
            (COL_COMP,     str(record.comp_id), C_SEC),
            (COL_LEN,      str(record.payload_len), C_SEC),
            (COL_PAYLOAD,  self._trunc(record.payload_hex.replace(" ", "")), C_DEFAULT),
            (COL_CRC,      f"0x{record.crc_actual:04X}", C_SEC),
        ]
        for col, text, color in col_defs:
            child.setText(col, text)
            child.setForeground(col, color)
            child.setData(col, _ROLE_RECORD, record)

    def _update_group_summary(self, info: _GroupInfo, record=None) -> None:
        if record is None and info.records:
            record = info.records[-1]
        if record is None:
            return

        msg_id_str = f"0x{record.msg_id:02X}"
        item = info.tree_item
        item.setText(COL_SRC_IP,  record.src_ip)
        item.setText(COL_DST_IP,  record.dst_ip)
        item.setText(COL_MESSAGE, f"{record.msg_name or f'MSG_{record.msg_id}'} ({msg_id_str})")

    def _remove_oldest_group(self) -> None:
        if not self._groups:
            return
        oldest_key = min(self._groups, key=lambda k: self._groups[k].last_timestamp_abs)
        self._remove_group(oldest_key)

    def _remove_group(self, group_key: tuple) -> None:
        info = self._groups.get(group_key)
        if info is None:
            return
        idx = self._tree.indexOfTopLevelItem(info.tree_item)
        if idx >= 0:
            self._tree.takeTopLevelItem(idx)
        self._total_msg_count -= info.count
        del self._groups[group_key]

    # ═══════════════════════════════════════════════════
    # 内部 — 裁剪
    # ═══════════════════════════════════════════════════
    def _find_oldest_group_key(self) -> tuple | None:
        """通过最小堆 O(log g) 查找最老分组（含惰性删除）。"""
        while self._group_heap:
            ts, key = self._group_heap[0]
            info = self._groups.get(key)
            if info is not None and info.records:
                first_ts = info.records[0].timestamp_abs
                if abs(first_ts - ts) < 0.001:  # 时间戳匹配（浮点容差）
                    return key
            # 惰性删除：堆顶 group 已空或时间戳不匹配
            heapq.heappop(self._group_heap)
        return None

    def _pop_oldest_from_group(self, group_key: tuple) -> None:
        info = self._groups.get(group_key)
        if info is None or not info.records:
            return
        info.records.popleft()
        info.count -= 1
        self._total_msg_count -= 1

        child = info.tree_item.child(0)
        if child is not None:
            info.tree_item.removeChild(child)

        if info.count == 0:
            self._remove_group(group_key)
        else:
            # 推入新的堆条目记录当前最老消息时间戳
            first_ts = info.records[0].timestamp_abs
            heapq.heappush(self._group_heap, (first_ts, group_key))
            self._update_group_summary(info)

    # ═══════════════════════════════════════════════════
    # 内部 — 点击
    # ═══════════════════════════════════════════════════
    def _on_item_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        if item.parent() is not None:
            record = item.data(COL_MESSAGE, _ROLE_RECORD)
            if record is not None:
                self.on_record_clicked.emit(record)

    def get_record_from_item(self, item: QTreeWidgetItem):
        if item.parent() is not None:
            return item.data(COL_MESSAGE, _ROLE_RECORD)
        return None

    # ── 右键菜单：复制完整 MAVLink 消息 ──
    def _on_context_menu(self, pos) -> None:
        """右键菜单：复制完整 MAVLink 消息到剪贴板。"""
        item = self._tree.itemAt(pos)
        if item is None:
            return
        record = self.get_record_from_item(item)
        if record is None:
            return

        menu = QMenu(self)
        copy_action = QAction("复制完整 MAVLink 消息", self)
        copy_action.triggered.connect(lambda r=record: self._copy_message(r))
        menu.addAction(copy_action)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _copy_message(self, record) -> None:
        """将完整 MAVLink 消息复制到剪贴板。"""
        text = record.format_complete()
        QApplication.clipboard().setText(text)

    # ═══════════════════════════════════════════════════
    # 工具栏
    # ═══════════════════════════════════════════════════
    def _toggle_pause(self) -> None:
        self._scroll_paused = not self._scroll_paused
        self._pause_btn.setText("> 恢复" if self._scroll_paused else "|| 暂停")
        self.on_pause.emit(self._scroll_paused)

    def _toggle_time(self) -> None:
        """相对 ↔ 绝对时间切换（仅单列，无双列模式）。"""
        self._time_mode = 1 - self._time_mode  # 0↔1
        self._tree.setColumnHidden(COL_TIME_REL, self._time_mode == 0)
        self._tree.setColumnHidden(COL_TIME_ABS, self._time_mode == 1)
        self._time_btn.setText(_TIME_LABELS[self._time_mode])

    # ═══════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════
    @staticmethod
    def _trunc(hex_str: str) -> str:
        if len(hex_str) <= _PAYLOAD_MAX:
            return hex_str
        return hex_str[:_PAYLOAD_MAX].rstrip() + "…"

    @staticmethod
    def _msg_color(name: str) -> QColor:
        if not name:
            return C_DEFAULT
        n = name.upper()
        if n.startswith("RADIO_"): return C_RADIO
        if "HEARTBEAT" in n:
            return C_HEART
        if "IDENTIFY" in n:
            return C_IDENT
        if "COMMAND" in n or "SET_" in n:
            return C_CMD
        return C_DEFAULT
