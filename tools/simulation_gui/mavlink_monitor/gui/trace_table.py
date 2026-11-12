"""Trace 消息表格 — QTableView + QAbstractTableModel（虚拟列表）+ payload tooltip

v2.0: 从 QTableWidget 重构为 QAbstractTableModel，关键优化：
  - 只渲染屏幕可见行（~30-50 行），不再创建 100000 个 QTableWidgetItem
  - add_records_batch() 批量插入：一次 beginInsertRows/endInsertRows
  - 自动淘汰旧行（deque maxlen），无需 trim_rows
"""

from __future__ import annotations
from collections import deque
from PySide6.QtCore import Qt, QThread, Signal, QEvent, QAbstractTableModel, QModelIndex
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableView, QHeaderView, QMenu, QApplication,
)
from PySide6.QtGui import QColor, QFont, QAction

# ═══════════════════════════════════════════════════════
# 列定义 (suffix, label, width, default_hidden)
# ═══════════════════════════════════════════════════════
_COLUMNS = [
    ("seq",      "#",            48,   False),
    ("time_rel", "Time (Rel)",   160,  False),
    ("time_abs", "Time (Abs)",   160,  True),
    ("src",      "Src IP:Port",  165,  False),
    ("dst",      "Dst IP:Port",  165,  False),
    ("relay_ip", "真实目标IP",    130,  True),
    ("msg",      "Msg Name",     140,  False),
    ("msgid",    "MsgID",        60,   False),
    ("sys",      "Sys",          40,   False),
    ("comp",     "Comp",         44,   False),
    ("len",      "Len",          40,   False),
    ("payload",  "Payload",      170,  False),
    ("crc",      "CRC",          80,   False),
    ("source",   "Source",       140,  True),
]

_PAYLOAD_MAX = 26
_ROLE_RECORD = Qt.ItemDataRole.UserRole
_ROLE_TOOLTIP = Qt.ItemDataRole.UserRole + 1

# 颜色
C_DIR_RX  = QColor(50,  210, 170); C_DIR_TX  = QColor(230, 130, 90)
C_HEART   = QColor(60,  150, 235); C_IDENT   = QColor(210, 120, 200)
C_CMD     = QColor(210, 180, 40);  C_DEFAULT = QColor(0, 0, 0)
C_RADIO   = QColor(0,   180, 180);  # 电台 DAV 消息：青蓝色
C_SEC     = QColor(105, 105, 105); C_DIM     = QColor(75,  75,  75)
C_CRC_OK  = QColor(80,  175, 60);  C_CRC_FAIL= QColor(244, 71,  71)
C_WARN    = QColor(210, 180, 40)

_TIME_LABELS = ["时间: 绝对", "时间: 相对"]


from mavlink_monitor.gui.utils import fmt_rel as _fmt_rel, fmt_abs as _fmt_abs


def _hex_to_ascii(hex_str: str) -> str:
    h = hex_str.replace(" ", "")
    chars = []
    for i in range(0, len(h), 2):
        try: b = int(h[i:i+2], 16)
        except (ValueError, IndexError): continue
        if b == 0: chars.append("\\0")
        elif 32 <= b <= 126: chars.append(chr(b))
        else: chars.append(".")
    return "'" + "".join(chars) + "'"


# ═══════════════════════════════════════════════════════════════
# TraceTableModel — QAbstractTableModel（虚拟列表）
# ═══════════════════════════════════════════════════════════════
class TraceTableModel(QAbstractTableModel):
    """MAVLink 消息虚拟表格模型。

    特性：
        - 基于 deque(maxlen) 的环形缓冲，自动淘汰旧记录
        - data() 按需格式化：只渲染屏幕可见行（~30-50 行）
        - 不再创建 QTableWidgetItem 对象 → 大幅降低内存和 CPU 开销
        - add_records() 批量插入：一次 beginInsertRows/endInsertRows
    """

    def __init__(self, max_rows: int = 100000):
        super().__init__()
        self._records: deque = deque(maxlen=max_rows)
        self._max_rows = max_rows

    # ── 批量写入（高性能路径）──
    def add_records(self, records: list) -> None:
        """批量添加记录：一次 beginInsertRows/endInsertRows。

        deque 的 maxlen 自动淘汰最旧记录，超出部分先发出
        beginRemoveRows 信号通知 View。
        """
        if not records:
            return
        old_count = len(self._records)
        overflow = old_count + len(records) - self._max_rows
        if overflow > 0:
            self.beginRemoveRows(QModelIndex(), 0, overflow - 1)
            # deque 自动丢弃最旧的 overflow 条
            self.endRemoveRows()

        insert_at = len(self._records)
        new_count = len(records)
        # 注意：如果 len(records) > self._max_rows，只有最后 max_rows 条会保留
        self.beginInsertRows(QModelIndex(), insert_at, insert_at + new_count - 1)
        self._records.extend(records)
        self.endInsertRows()

    def add_record(self, record) -> None:
        """添加单条记录（内部调用 add_records）。"""
        self.add_records([record])

    def get_record(self, row: int):
        """按行号获取 MessageRecord。"""
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    def clear(self) -> None:
        """清空所有记录。"""
        if not self._records:
            return
        self.beginResetModel()
        self._records.clear()
        self.endResetModel()

    @property
    def count(self) -> int:
        return len(self._records)

    @property
    def max_rows(self) -> int:
        return self._max_rows

    @max_rows.setter
    def max_rows(self, value: int) -> None:
        """更新最大行数并裁剪现有记录。"""
        if value <= 0:
            return
        self._max_rows = value
        excess = len(self._records) - value
        if excess > 0:
            self.beginRemoveRows(QModelIndex(), 0, excess - 1)
            while len(self._records) > value:
                self._records.popleft()
            self.endRemoveRows()

    # ── QAbstractTableModel interface ──
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._records):
            return None

        rec = self._records[row]

        if role == Qt.DisplayRole:
            return _format_cell(col, rec)
        if role == Qt.ForegroundRole:
            return _color_for_cell(col, rec)
        if role == _ROLE_RECORD:
            return rec
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(_COLUMNS):
                return _COLUMNS[section][1]
        return None


# ── TraceTableModel helpers ──
def _format_cell(col: int, rec) -> str:
    """格式化单元格显示文本（热路径，避免分支开销）。"""
    if col == 0:   return str(rec.seq)
    if col == 1:   return _fmt_rel(rec.timestamp_rel)
    if col == 2:   return _fmt_abs(rec.timestamp_abs)
    if col == 3:   return f"{rec.src_ip}:{rec.src_port}"
    if col == 4:   return f"{rec.dst_ip}:{rec.dst_port}"
    if col == 5:   return rec.relay_ip if rec.has_relay_ip else "—"
    if col == 6:   return rec.msg_name or f"MSG_{rec.msg_id}"
    if col == 7:   return rec.msg_id_hex
    if col == 8:   return str(rec.sys_id)
    if col == 9:   return str(rec.comp_id)
    if col == 10:  return str(rec.payload_len)
    if col == 11:  return _trunc_payload(rec.payload_hex.replace(" ", ""))
    if col == 12:  return rec.crc_display
    if col == 13:  return rec.node_id or "—"
    return ""


def _color_for_cell(col: int, rec) -> QColor:
    """返回单元格前景色。"""
    if col == 3:   return C_DIR_RX  # Src IP
    if col == 4:   return C_DIR_TX  # Dst IP
    if col == 5:   return C_WARN if rec.has_relay_ip else C_DIM
    if col == 6:   return _msg_color(rec.msg_name)
    if col == 7:   return C_SEC
    if col == 8:   return C_SEC
    if col == 9:   return C_SEC
    if col == 10:  return C_SEC
    if col == 12:  return C_CRC_OK if rec.crc_ok else C_CRC_FAIL
    if col == 13:  return C_DIM
    return C_DEFAULT


def _trunc_payload(hex_str: str) -> str:
    if len(hex_str) <= _PAYLOAD_MAX:
        return hex_str
    return hex_str[:_PAYLOAD_MAX].rstrip() + "…"


def _msg_color(name: str) -> QColor:
    if not name:
        return C_DEFAULT
    n = name.upper()
    if n.startswith("RADIO_"):
        return C_RADIO
    if "HEARTBEAT" in n:
        return C_HEART
    if "IDENTIFY" in n:
        return C_IDENT
    if "COMMAND" in n or "SET_" in n:
        return C_CMD
    return C_DEFAULT


# ═══════════════════════════════════════════════════════════════
# TraceTable — QTableView + TraceTableModel（虚拟列表）
# ═══════════════════════════════════════════════════════════════
class TraceTable(QWidget):
    """实时消息表格（虚拟列表 + 工具栏）。

    v2.0: 使用 QTableView + QAbstractTableModel 替代 QTableWidget，
    只渲染屏幕可见行，不再创建 QTableWidgetItem 对象。
    """

    on_row_clicked = Signal(int, int)
    on_record_clicked = Signal(object)   # emits MessageRecord
    on_pause = Signal(bool)

    def __init__(self, on_row_clicked=None, show_toolbar: bool = True):
        super().__init__()
        if on_row_clicked:
            self.on_row_clicked.connect(on_row_clicked)

        self._time_mode = 1        # 0=abs, 1=rel(default)
        self._relay_visible = False
        self._source_visible = False
        self._scroll_paused = False
        self._selected_seqs: set[int] = set()

        ly = QVBoxLayout(self)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(2)

        # ── 工具栏（show_toolbar=False 时不创建 —— 宿主面板自带
        #    捕获/暂停/清空时使用，如 TcpMonitorPanel） ──
        if show_toolbar:
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

            self._relay_btn = QPushButton("真实目标IP")
            self._relay_btn.setCheckable(True)
            self._relay_btn.clicked.connect(self._toggle_relay)
            self._toolbar.addWidget(self._relay_btn)

            self._source_btn = QPushButton("来源")
            self._source_btn.setCheckable(True)
            self._source_btn.clicked.connect(self._toggle_source)
            self._toolbar.addWidget(self._source_btn)

            self._toolbar.addStretch()
            ly.addLayout(self._toolbar)

        # ── QTableView + TraceTableModel ──
        self._model = TraceTableModel(max_rows=100000)
        self._view = QTableView()
        self._view.setModel(self._model)
        self._view.setSelectionBehavior(self._view.SelectionBehavior.SelectRows)
        self._view.setEditTriggers(self._view.EditTrigger.NoEditTriggers)
        self._view.setAlternatingRowColors(True)
        self._view.verticalHeader().setVisible(False)
        self._view.setShowGrid(False)
        self._view.horizontalHeader().setStretchLastSection(True)

        # 列宽
        for i, (_, _, w, hidden) in enumerate(_COLUMNS):
            self._view.setColumnWidth(i, w)
            self._view.setColumnHidden(i, hidden)

        self._view.clicked.connect(self._on_cell_clicked)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        # Tooltip on hover
        self._view.viewport().installEventFilter(self)
        self._view.setMouseTracking(True)

        ly.addWidget(self._view, 1)

    # ── 列控制 ──
    def _toggle_time(self) -> None:
        self._time_mode = 1 - self._time_mode
        self._view.setColumnHidden(1, self._time_mode == 0)  # rel
        self._view.setColumnHidden(2, self._time_mode == 1)  # abs
        self._time_btn.setText(_TIME_LABELS[self._time_mode])

    def _toggle_relay(self) -> None:
        self._relay_visible = self._relay_btn.isChecked()
        self._view.setColumnHidden(5, not self._relay_visible)

    def _toggle_source(self) -> None:
        self._source_visible = self._source_btn.isChecked()
        self._view.setColumnHidden(13, not self._source_visible)

    def _toggle_pause(self) -> None:
        self._scroll_paused = not self._scroll_paused
        self._pause_btn.setText("> 恢复" if self._scroll_paused else "|| 暂停")
        self.on_pause.emit(self._scroll_paused)

    # ── 行操作 ──
    def add_record(self, record) -> None:
        """添加单条记录。暂停时忽略。"""
        if self._scroll_paused:
            return
        self._model.add_record(record)

    def add_records(self, records: list) -> None:
        """批量添加记录（高性能路径）。暂停时忽略。"""
        if self._scroll_paused or not records:
            return
        self._model.add_records(records)

    def get_record(self, row: int):
        return self._model.get_record(row)

    def trim_rows(self, max_rows: int) -> None:
        """调整最大行数（deque maxlen 自动淘汰，此处仅更新阈值）。"""
        self._model.max_rows = max_rows

    def clear(self) -> None:
        self._model.clear()

    # ── 自动滚动 ──
    def is_at_bottom(self, threshold: int = 5) -> bool:
        sb = self._view.verticalScrollBar()
        return sb.value() >= sb.maximum() - threshold

    def scroll_to_bottom(self) -> None:
        self._view.scrollToBottom()

    @property
    def scroll_paused(self) -> bool:
        return self._scroll_paused

    @scroll_paused.setter
    def scroll_paused(self, paused: bool) -> None:
        self._scroll_paused = paused
        if getattr(self, "_pause_btn", None) is not None:
            self._pause_btn.setText("> 恢复" if self._scroll_paused else "|| 暂停")

    @property
    def time_mode(self) -> int:
        return self._time_mode

    @time_mode.setter
    def time_mode(self, mode: int) -> None:
        self._time_mode = mode
        self._view.setColumnHidden(1, mode == 0)
        self._view.setColumnHidden(2, mode == 1)
        self._time_btn.setText(_TIME_LABELS[mode])

    @property
    def relay_visible(self) -> bool:
        return self._relay_visible

    @property
    def source_visible(self) -> bool:
        return self._source_visible

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

    # ── Tooltip (hover on payload cell) ──
    def eventFilter(self, obj, event) -> bool:
        if obj == self._view.viewport() and event.type() == QEvent.Type.MouseMove:
            pos = event.pos()
            idx = self._view.indexAt(pos)
            if idx.isValid() and idx.column() == 11:  # Payload column
                rec = self._model.get_record(idx.row())
                if rec and rec.fields_parsed:
                    lines = [f"{rec.msg_name or f'MSG_{rec.msg_id}'} ({rec.msg_id_hex})"]
                    for f in rec.fields:
                        lines.append(f"  {f.name} = {f.value_display}  [{f.type_name}]")
                        if f.is_array:
                            try:
                                lines.append(f"    ASCII: {_hex_to_ascii(f.raw_hex)}")
                            except Exception:
                                pass
                    self._view.setToolTip("\n".join(lines))
                elif rec:
                    self._view.setToolTip(f"{rec.msg_name} ({rec.msg_id_hex})\n(选中行展开字段详情)")
                else:
                    self._view.setToolTip("")
            else:
                self._view.setToolTip("")
        return super().eventFilter(obj, event)

    # ── 交互 ──
    def _on_cell_clicked(self, index: QModelIndex) -> None:
        row, col = index.row(), index.column()
        self.on_row_clicked.emit(row, col)
        record = self._model.get_record(row)
        if record is not None:
            self.on_record_clicked.emit(record)

    # ── 右键菜单 ──
    def _on_context_menu(self, pos) -> None:
        idx = self._view.indexAt(pos)
        if not idx.isValid():
            return
        record = self._model.get_record(idx.row())
        if record is None:
            return

        menu = QMenu(self)
        copy_action = QAction("复制完整 MAVLink 消息", self)
        copy_action.triggered.connect(lambda: self._copy_message(record))
        menu.addAction(copy_action)
        menu.exec(self._view.viewport().mapToGlobal(pos))

    def _copy_message(self, record) -> None:
        text = record.format_complete()
        QApplication.clipboard().setText(text)
