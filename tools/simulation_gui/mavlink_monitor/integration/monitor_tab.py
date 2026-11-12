"""MAVLink Monitor — PySide6 QWidget 集成模块（NIC 嗅探模式）

可作为 QTabWidget 的一个 Tab 嵌入 MultiSimulationGUI 或其他 PySide6 应用。

用法:
    from mavlink_monitor.integration.monitor_tab import MonitorTab
    tab = MonitorTab()
    tab_widget.addTab(tab, "MAVLink Monitor")

    # 加载配置
    tab.load_config("/path/to/mavlink_config_v41.json",
                    "/path/to/mavlink_enums_v41.json")
    # 选择网卡并启动
    tab.set_interface("WLAN")
    tab.start()
"""

from __future__ import annotations

import time
import os

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGroupBox, QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QTreeWidget, QTreeWidgetItem, QFileDialog, QMessageBox,
)

# Core
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from mavlink_monitor.core.controller import MonitorController
from mavlink_monitor.core.filter import FilterRule


# ═══════════════════════════════════════════════════════════════
# Trace 表头
# ═══════════════════════════════════════════════════════════════
_COLUMNS = [
    ("#", 48), ("Time (Rel)", 110), ("Time (Abs)", 140),
    ("Dir", 36), ("Src IP:Port", 155), ("Dst IP:Port", 155),
    ("Msg Name", 130), ("MsgID", 58), ("Sys", 36), ("Comp", 42),
    ("Len", 36), ("Payload", 160), ("CRC", 80),
]


class MonitorTab(QWidget):
    """MAVLink 监控 PySide6 Tab（NIC 嗅探模式）。"""

    config_loaded = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ctrl = MonitorController()
        self._scroll_paused = False
        self._max_rows = 500

        self._setup_ui()
        self._setup_timer()

    # ═══════════════════════════════════════════════════════════
    # UI 构建
    # ═══════════════════════════════════════════════════════════
    def _setup_ui(self) -> None:
        main_layout = QHBoxLayout(self)

        # ── 左面板 ──
        left = QWidget()
        left.setFixedWidth(280)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)

        # 配置组
        cfg_group = QGroupBox("消息配置")
        cfg_layout = QVBoxLayout(cfg_group)
        h = QHBoxLayout()
        h.addWidget(QLabel("版本:"))
        self._version_combo = QComboBox()
        self._version_combo.addItems(["auto", "v32", "v37", "v39", "v41", "v42"])
        h.addWidget(self._version_combo)
        cfg_layout.addLayout(h)
        self._cfg_status = QLabel("[OFF] 未加载")
        cfg_layout.addWidget(self._cfg_status)
        btn_layout = QHBoxLayout()
        self._btn_load_cfg = QPushButton("加载 Config...")
        self._btn_load_cfg.clicked.connect(self._on_load_config)
        btn_layout.addWidget(self._btn_load_cfg)
        self._btn_load_enums = QPushButton("加载 Enums...")
        self._btn_load_enums.clicked.connect(self._on_load_enums)
        btn_layout.addWidget(self._btn_load_enums)
        cfg_layout.addLayout(btn_layout)
        left_layout.addWidget(cfg_group)

        # 网卡嗅探组
        nic_group = QGroupBox("网卡嗅探")
        nic_layout = QVBoxLayout(nic_group)
        h = QHBoxLayout()
        h.addWidget(QLabel("网卡:"))
        self._nic_combo = QComboBox()
        self._nic_combo.setEditable(True)
        self._nic_combo.setMinimumWidth(130)
        h.addWidget(self._nic_combo)
        nic_layout.addLayout(h)
        btn_row = QHBoxLayout()
        self._btn_start = QPushButton("开始嗅探")
        self._btn_start.clicked.connect(self._on_start)
        btn_row.addWidget(self._btn_start)
        self._btn_stop = QPushButton("停止嗅探")
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_stop.setEnabled(False)
        btn_row.addWidget(self._btn_stop)
        nic_layout.addLayout(btn_row)
        self._nic_info = QLabel("未启动")
        nic_layout.addWidget(self._nic_info)
        left_layout.addWidget(nic_group)

        # UDP监听组
        udp_group = QGroupBox("UDP监听 (内部)")
        udp_layout = QVBoxLayout(udp_group)
        h = QHBoxLayout()
        h.addWidget(QLabel("Host:"))
        self._udp_host = QLineEdit("0.0.0.0")
        self._udp_host.setMinimumWidth(100)
        h.addWidget(self._udp_host)
        udp_layout.addLayout(h)
        h = QHBoxLayout()
        h.addWidget(QLabel("Port:"))
        self._udp_port = QLineEdit("14550")
        self._udp_port.setFixedWidth(80)
        h.addWidget(self._udp_port)
        h.addStretch()
        udp_layout.addLayout(h)
        btn_row = QHBoxLayout()
        self._btn_start_udp = QPushButton("开始监听")
        self._btn_start_udp.clicked.connect(self._on_start_udp)
        btn_row.addWidget(self._btn_start_udp)
        self._btn_stop_udp = QPushButton("停止监听")
        self._btn_stop_udp.clicked.connect(self._on_stop_udp)
        self._btn_stop_udp.setEnabled(False)
        btn_row.addWidget(self._btn_stop_udp)
        udp_layout.addLayout(btn_row)
        self._udp_info = QLabel("未启动")
        udp_layout.addWidget(self._udp_info)
        left_layout.addWidget(udp_group)

        # 统计
        stat_group = QGroupBox("统计")
        stat_layout = QVBoxLayout(stat_group)
        self._stat_label = QLabel("Total: 0  Rate: 0 msg/s\nErrors: 0  CRC Fail: 0")
        stat_layout.addWidget(self._stat_label)
        left_layout.addWidget(stat_group)

        left_layout.addStretch()
        main_layout.addWidget(left)

        # ── 右面板：Trace + 字段详情 ──
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # Trace 表格
        self._trace_table = QTableWidget()
        self._trace_table.setColumnCount(len(_COLUMNS))
        self._trace_table.setHorizontalHeaderLabels([c[0] for c in _COLUMNS])
        for i, (_, w) in enumerate(_COLUMNS):
            self._trace_table.setColumnWidth(i, w)
        self._trace_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._trace_table.setAlternatingRowColors(True)
        self._trace_table.cellClicked.connect(self._on_row_clicked)
        right_splitter.addWidget(self._trace_table)

        # 字段详情
        self._field_tree = QTreeWidget()
        self._field_tree.setHeaderLabels(["字段名", "解析值", "原始值 (Hex)", "类型"])
        self._field_tree.setColumnWidth(0, 120)
        self._field_tree.setColumnWidth(1, 200)
        self._field_tree.setColumnWidth(2, 150)
        self._field_tree.setColumnWidth(3, 80)
        right_splitter.addWidget(self._field_tree)

        main_layout.addWidget(right_splitter, 1)

    def _setup_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(50)

    # ═══════════════════════════════════════════════════════════
    # 公开 API
    # ═══════════════════════════════════════════════════════════
    def load_config(self, config_path: str, enums_path: str | None = None,
                    version: str = "default") -> bool:
        ok = self._ctrl.load_config(config_path, version)
        if enums_path:
            ok &= self._ctrl.load_enums(enums_path, version)
        self._cfg_status.setText("[OK] 就绪" if ok else "[OFF] 加载失败")
        return ok

    def set_interface(self, name: str) -> None:
        self._ctrl.set_interface(name)

    def start(self) -> None:
        self._ctrl.start()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)

    def stop(self) -> None:
        self._ctrl.stop()
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)

    def closeEvent(self, event) -> None:
        self._ctrl.stop_udp()
        self._ctrl.stop()
        super().closeEvent(event)

    # ═══════════════════════════════════════════════════════════
    # 定时刷新
    # ═══════════════════════════════════════════════════════════
    def _on_tick(self) -> None:
        if not self._ctrl.is_running:
            return

        records = self._ctrl.get_new_records()
        if records and not self._scroll_paused:
            for rec in records:
                self._add_trace_row(rec)

            while self._trace_table.rowCount() > self._max_rows:
                self._trace_table.removeRow(0)

        stats = self._ctrl.get_stats()
        self._stat_label.setText(
            f"Total: {stats['total']}  Rate: {stats['rate']:.0f} msg/s\n"
            f"Errors: {stats['errors']}  CRC Fail: {stats['crc_fail']}\n"
            f"网卡包: {stats['nic_packets']}  MAVLink: {stats['nic_mavlink']}\n"
            f"UDP包: {stats.get('udp_packets', 0)}  MAVLink: {stats.get('udp_mavlink', 0)}"
        )

    def _add_trace_row(self, record) -> None:
        row = self._trace_table.rowCount()
        self._trace_table.insertRow(row)

        items = [
            QTableWidgetItem(str(record.seq)),
            QTableWidgetItem(f"+{record.timestamp_rel:.6f}"),
            QTableWidgetItem(_fmt_abs(record.timestamp_abs)),
            QTableWidgetItem(record.direction),
            QTableWidgetItem(f"{record.src_ip}:{record.src_port}"),
            QTableWidgetItem(f"{record.dst_ip}:{record.dst_port}"),
            QTableWidgetItem(record.msg_name or f"MSG_{record.msg_id}"),
            QTableWidgetItem(record.msg_id_hex),
            QTableWidgetItem(str(record.sys_id)),
            QTableWidgetItem(str(record.comp_id)),
            QTableWidgetItem(str(record.payload_len)),
            QTableWidgetItem(record.payload_display),
            QTableWidgetItem(record.crc_display),
        ]

        for col, item in enumerate(items):
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._trace_table.setItem(row, col, item)

        items[0].setData(Qt.ItemDataRole.UserRole, record)

    # ═══════════════════════════════════════════════════════════
    # 回调
    # ═══════════════════════════════════════════════════════════
    def _on_load_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Config JSON", "", "JSON (*.json)")
        if path:
            version = self._version_combo.currentText()
            self.load_config(path, version=version)

    def _on_load_enums(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Enums JSON", "", "JSON (*.json)")
        if path:
            self._ctrl.load_enums(path, self._version_combo.currentText())

    def _on_start(self) -> None:
        if not self._ctrl.is_config_ready:
            QMessageBox.warning(self, "未配置", "请先加载消息配置文件。")
            return
        iface = self._nic_combo.currentText().strip()
        if not iface:
            QMessageBox.warning(self, "未选择网卡", "请输入或选择网卡名称。")
            return
        self._ctrl.set_interface(iface)
        self._nic_info.setText(f"嗅探中: {iface}")
        self.start()

    def _on_stop(self) -> None:
        self.stop()
        self._nic_info.setText("已停止")

    def _on_start_udp(self) -> None:
        host = self._udp_host.text().strip() or "0.0.0.0"
        try:
            port = int(self._udp_port.text().strip())
        except ValueError:
            port = 14550
        try:
            self._ctrl.set_udp_listener(host, port)
            self._ctrl.start_udp()
            self._udp_info.setText(f"监听中: {host}:{port}")
            self._btn_start_udp.setEnabled(False)
            self._btn_stop_udp.setEnabled(True)
        except Exception as e:
            QMessageBox.warning(self, "UDP错误", f"启动失败: {e}")

    def _on_stop_udp(self) -> None:
        self._ctrl.stop_udp()
        self._udp_info.setText("已停止")
        self._btn_start_udp.setEnabled(True)
        self._btn_stop_udp.setEnabled(False)

    def _on_row_clicked(self, row: int, col: int) -> None:
        item = self._trace_table.item(row, 0)
        if item is None:
            return
        record = item.data(Qt.ItemDataRole.UserRole)
        if record is None:
            return

        fields = self._ctrl.parse_fields(record)
        self._field_tree.clear()
        for f in fields:
            tree_item = QTreeWidgetItem([
                f.name, f.value_display, f.raw_hex, f.type_name,
            ])
            self._field_tree.addTopLevelItem(tree_item)
            if f.is_array:
                ascii_item = QTreeWidgetItem([
                    "  ASCII", _fmt_ascii(f.raw_hex), "", "",
                ])
                self._field_tree.addTopLevelItem(ascii_item)


from mavlink_monitor.gui.utils import fmt_abs as _fmt_abs


def _fmt_ascii(hex_str: str) -> str:
    chars = []
    for p in hex_str.split():
        try:
            b = int(p, 16)
        except ValueError:
            continue
        if b == 0:       chars.append("\\0")
        elif 32 <= b <= 126: chars.append(chr(b))
        else:            chars.append(".")
    return "'" + "".join(chars) + "'"
