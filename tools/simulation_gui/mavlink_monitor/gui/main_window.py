"""MAVLink UDP Monitor — PySide6 主窗口"""

from __future__ import annotations
import os
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QMenuBar, QStatusBar, QSplitter, QWidget, QVBoxLayout,
    QFileDialog, QMessageBox, QLabel, QStackedWidget, QPushButton, QHBoxLayout,
    QSpinBox,
)
from PySide6.QtGui import QAction

from ..core.controller import MonitorController
from ..core.filter import FilterRule
from .left_panel import LeftPanel
from .filter_bar import FilterBar
from .trace_table import TraceTable
from .grouped_trace_view import GroupedTraceView
from .detail_tree import DetailTree


class MainWindow(QMainWindow):
    """MAVLink UDP 监控主窗口。"""

    def __init__(self):
        super().__init__()
        self._ctrl = MonitorController()
        self._scroll_paused = False
        self._display_limit = 10000  # 表格显示行数上限
        self._first_show = True  # 首次显示标志，用于多屏居中
        self._seen_ips: set[str] = set()  # 已见 IP 缓存，避免重复更新过滤栏
        self._seen_relay_ips: set[str] = set()

        self.setWindowTitle("MAVLink UDP Monitor")
        self.resize(1500, 850)
        self.setMinimumSize(1024, 600)

        self._setup_menu()
        self._setup_statusbar()
        self._setup_central()
        self._setup_timer()

        # 加载 command=183 业务功能映射配置
        self._load_command_183_config()
        # 加载电台 DAV 消息配置
        self._load_radio_config()

    def showEvent(self, event) -> None:
        """首次显示时居中到主屏幕（解决多屏窗口消失问题）。"""
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            self._center_on_screen()

    # ── 菜单 ──
    def _setup_menu(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("File")
        file_menu.addAction("导出 CSV...", self._export_csv)
        file_menu.addAction("导出 JSON...", self._export_json)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)

        view_menu = mb.addMenu("View")
        view_menu.addAction("重置统计", self._on_reset_stats)
        view_menu.addAction("清空缓冲", self._on_clear_buffer)

    # ── 状态栏 ──
    def _setup_statusbar(self) -> None:
        self._status_label = QLabel("Ready")
        self._status_iface = QLabel("网卡: --")
        self._status_udp = QLabel("电台: --")  # 原 UDP 状态栏，现用于电台
        self._status_buf = QLabel("Buffer: 0 / 40960000")

        sb = self.statusBar()
        sb.addWidget(self._status_label, 1)
        sb.addPermanentWidget(self._status_iface)
        sb.addPermanentWidget(self._status_udp)
        sb.addPermanentWidget(self._status_buf)

    # ── 中央布局 ──
    def _setup_central(self) -> None:
        h_split = QSplitter(Qt.Orientation.Horizontal)

        # ── 左面板：配置 + 网卡 + 统计 ──
        self.left_panel = LeftPanel()
        self.left_panel.setFixedWidth(290)
        self.left_panel.on_start_nic.connect(self._on_start_nic)
        self.left_panel.on_stop_nic.connect(self._on_stop_nic)
        self.left_panel.on_config_changed.connect(self._on_config_changed)
        h_split.addWidget(self.left_panel)

        # ── 右区域：过滤栏 | 表格 | 详情 ──
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(2)

        self.filter_bar = FilterBar(on_filter_change=self._on_filter_change)
        # 注：FilterBar 内部的 "过滤" 标签将被隐藏，统一使用 2×2 网格的标签

        # 信号连接 + FilterBar 创建就绪后，触发初始配置加载（填充 MsgID 列表）
        self.left_panel.load_initial_config()

        # 确保过滤初始状态：关闭，无规则（默认显示所有消息）
        self._ctrl.filter_enabled = False
        self._ctrl.clear_filter()

        # ── 2×2 功能组布局 ──
        # 顺序：视图 / 数据源
        #       捕获 / 过滤
        # 标签宽度统一对齐，控件左对齐
        from PySide6.QtWidgets import QGridLayout

        TAG_WIDTH = 42  # 标签统一宽度（像素）

        def _tag(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFixedWidth(TAG_WIDTH)
            lbl.setStyleSheet("color: #666; font-weight: bold; font-size: 11px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return lbl

        def _cell(tag_text: str, *widgets: QWidget) -> QWidget:
            """创建功能组容器：tag + 控件左对齐。"""
            ctn = QWidget()
            ly = QHBoxLayout(ctn)
            ly.setContentsMargins(4, 2, 4, 2)
            ly.setSpacing(4)
            ly.addWidget(_tag(tag_text))
            for w in widgets:
                ly.addWidget(w)
            ly.addStretch(1)  # 控件左对齐
            return ctn

        # ── Row 0, Col 0：视图组 ──
        self._time_btn = QPushButton("时间: 相对")
        self._time_btn.setFixedWidth(70)
        self._time_btn.clicked.connect(self._on_toggle_time)
        self._mode_btn = QPushButton("分组视图")
        self._mode_btn.setCheckable(True)
        self._mode_btn.setFixedWidth(64)
        self._mode_btn.clicked.connect(self._on_toggle_view_mode)
        self._relay_btn = QPushButton("真实目标IP")
        self._relay_btn.setCheckable(True)
        self._relay_btn.setFixedWidth(72)
        self._relay_btn.clicked.connect(self._on_toggle_relay)
        self._source_btn = QPushButton("来源")
        self._source_btn.setCheckable(True)
        self._source_btn.setFixedWidth(44)
        self._source_btn.clicked.connect(self._on_toggle_source)
        limit_lbl = QLabel("显示上限:")
        self._display_limit_spin = QSpinBox()
        self._display_limit_spin.setRange(1, 1000000)
        self._display_limit_spin.setValue(10000)
        self._display_limit_spin.setFixedWidth(80)
        self._display_limit_spin.valueChanged.connect(self._on_display_limit_change)
        view_ctn = _cell("视图", self._time_btn, self._mode_btn, self._relay_btn,
                          self._source_btn, limit_lbl, self._display_limit_spin)

        # ── Row 0, Col 1：数据源组 ──
        self._nest_btn = QPushButton("机巢")
        self._nest_btn.setCheckable(True)
        self._nest_btn.setChecked(True)
        self._nest_btn.setFixedWidth(44)
        self._nest_btn.setToolTip("开关 ip_prefixed(机巢) 格式消息的接收与解析")
        self._nest_btn.clicked.connect(self._on_nest_toggle)
        self._radio_btn = QPushButton("电台")
        self._radio_btn.setCheckable(True)
        self._radio_btn.setFixedWidth(44)
        self._radio_btn.setToolTip("开关 R2 电台 DAV 协议监听 (UDP 14555)")
        self._radio_btn.clicked.connect(self._on_radio_toggle)
        src_ctn = _cell("数据源", self._nest_btn, self._radio_btn)

        # ── Row 1, Col 0：捕获组 ──
        self._pause_btn = QPushButton("|| 暂停")
        self._pause_btn.setFixedWidth(52)
        self._pause_btn.clicked.connect(self._on_pause_clicked)
        self._clear_btn_ctrl = QPushButton("清空")
        self._clear_btn_ctrl.setFixedWidth(40)
        self._clear_btn_ctrl.clicked.connect(self._on_clear_buffer)
        cap_ctn = _cell("捕获", self._pause_btn, self._clear_btn_ctrl)

        # ── Row 1, Col 1：过滤组（嵌入 FilterBar，隐藏其内部标签）──
        self.filter_bar._tag_label.setVisible(False)  # 隐藏内部 "过滤" 标签
        filter_ctn = QWidget()
        fl = QHBoxLayout(filter_ctn)
        fl.setContentsMargins(4, 2, 4, 2)
        fl.setSpacing(4)
        fl.addWidget(_tag("过滤"))
        fl.addWidget(self.filter_bar, 1)  # FilterBar 占据过滤组剩余空间

        # ── QGridLayout 组装 ──
        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.addWidget(view_ctn,   0, 0)
        grid.addWidget(src_ctn,    0, 1)
        grid.addWidget(cap_ctn,    1, 0)
        grid.addWidget(filter_ctn, 1, 1)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)  # 过滤组列可伸展
        rl.addLayout(grid)

        # ── QStackedWidget 容纳两种视图 ──
        self._view_stack = QStackedWidget()

        # Index 0: 时间序平铺表格（隐藏内部工具栏，由主窗口统一控制）
        self._trace_table = TraceTable()
        self._trace_table.toolbar_visible = False
        self._trace_table.on_record_clicked.connect(self._on_record_clicked)
        self._trace_table.on_pause.connect(self._on_pause)
        self._view_stack.addWidget(self._trace_table)

        # Index 1: 分组树视图（隐藏内部工具栏，由主窗口统一控制）
        self._grouped_view = GroupedTraceView(display_limit=self._display_limit)
        self._grouped_view.toolbar_visible = False
        self._grouped_view.on_record_clicked.connect(self._on_record_clicked)
        self._grouped_view.on_pause.connect(self._on_pause)
        self._view_stack.addWidget(self._grouped_view)

        v_split = QSplitter(Qt.Orientation.Vertical)
        v_split.addWidget(self._view_stack)

        self.detail_tree = DetailTree()
        v_split.addWidget(self.detail_tree)
        v_split.setSizes([650, 150])

        rl.addWidget(v_split, 1)
        h_split.addWidget(right)

        self.setCentralWidget(h_split)

    # ── 定时器 ──
    def _setup_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(50)  # ~20 FPS

    # ═══════════════════════════════════════════════════
    # 定时刷新
    # ═══════════════════════════════════════════════════
    def _on_tick(self) -> None:
        if not self._ctrl.is_running:
            return

        if not self._scroll_paused:
            records = self._ctrl.get_new_records()

            # 优化：仅更新当前活跃视图
            active_index = self._view_stack.currentIndex()
            active_view = self._trace_table if active_index == 0 else self._grouped_view

            # 在添加记录前记住是否在底部（用户手动上滚则不强制拉回）
            was_at_bottom = active_view.is_at_bottom()

            for rec in records:
                active_view.add_record(rec)

            if active_index == 0:
                self._trace_table.trim_rows(self._display_limit)
            else:
                self._grouped_view.trim_messages(self._display_limit)

            # 如果之前就在底部，添加新记录后自动滚到底部
            if was_at_bottom and records:
                active_view.scroll_to_bottom()

            # 收集新 IP，更新过滤栏可选列表
            new_ips: set[str] = set()
            new_relay_ips: set[str] = set()
            for rec in records:
                if rec.src_ip and rec.src_ip not in self._seen_ips:
                    new_ips.add(rec.src_ip)
                if rec.dst_ip and rec.dst_ip not in self._seen_ips:
                    new_ips.add(rec.dst_ip)
                if rec.has_relay_ip and rec.relay_ip not in self._seen_relay_ips:
                    new_relay_ips.add(rec.relay_ip)
            if new_ips:
                self._seen_ips |= new_ips
                self.filter_bar.set_ip_options(self._seen_ips)
            if new_relay_ips:
                self._seen_relay_ips |= new_relay_ips
                self.filter_bar.set_relayip_options(self._seen_relay_ips)

        # 统计
        s = self._ctrl.get_stats()
        self.left_panel.update_stats(
            s["total"], s["rate"], s["errors"], s["crc_fail"],
            s["nic_packets"], s["nic_mavlink"],
            s["buffer_used"], s["buffer_max"], s["uptime"],
            s.get("radio_packets", 0), s.get("radio_mavlink", 0),
        )

        self._status_iface.setText(f"网卡: {s['interface']}")
        radio_info = f"电台: {s.get('radio_host', '')}:{s.get('radio_port', 0)}" if s.get("radio_running") else "电台: --"
        self._status_udp.setText(radio_info)
        self._status_buf.setText(f"Buffer: {s['buffer_used']}/{s['buffer_max']}")

    # ═══════════════════════════════════════════════════
    # 网卡嗅探回调
    # ═══════════════════════════════════════════════════
    def _on_start_nic(self, iface: str) -> None:
        if not self._ctrl.is_config_ready:
            self._set_status("请先在左侧加载 Mavlink 配置")
            self.left_panel.set_sniffing_stopped()
            return
        try:
            self._ctrl.set_interface(iface)
            self._ctrl.start()
            self._set_status(f"嗅探中 — {iface}")
        except Exception as e:
            self._set_status(f"启动失败: {e}")
            self.left_panel.set_sniffing_stopped()

    def _on_stop_nic(self) -> None:
        self._ctrl.stop()
        self._set_status("已停止嗅探")

    # ═══════════════════════════════════════════════════
    # 配置回调
    # ═══════════════════════════════════════════════════
    def _on_config_changed(self, config_path: str, enums_path: str,
                           version: str) -> None:
        ok = True
        if config_path and os.path.isfile(config_path):
            ok &= self._ctrl.load_config(config_path, version)
        if enums_path and os.path.isfile(enums_path):
            ok &= self._ctrl.load_enums(enums_path, version)
        self._set_status("配置就绪" if ok else "配置加载失败")
        # 更新过滤栏的 MsgID 可选列表
        if ok:
            msgids = self._ctrl.get_available_msgids()
            if msgids:
                self.filter_bar.set_msgid_options(msgids)
            self._seen_ips.clear()
            self.filter_bar.set_ip_options(set())
            self._seen_relay_ips.clear()
            self.filter_bar.set_relayip_options(set())

    # ═══════════════════════════════════════════════════
    # command=183 业务功能配置加载
    # ═══════════════════════════════════════════════════
    def _load_command_183_config(self) -> None:
        """加载 command=183 业务功能映射配置文件。"""
        import os as _os
        path = _os.path.join(
            _os.path.dirname(__file__), "..", "..", "resources",
            "command_183_functions.json",
        )
        path = _os.path.abspath(path)
        if _os.path.isfile(path):
            ok = self._ctrl.load_command_183_config(path)
            if ok:
                self._set_status("command=183 业务功能配置已加载")
            else:
                self._set_status("command=183 配置加载失败")
        else:
            print(f"[MainWindow] command_183 config not found: {path}")

    # ═══════════════════════════════════════════════════
    # 电台 DAV 监听控制
    # ═══════════════════════════════════════════════════
    def _load_radio_config(self) -> None:
        """加载电台 DAV 消息配置 JSON。"""
        import os as _os
        path = _os.path.join(
            _os.path.dirname(__file__), "..", "..", "resources",
            "radio_message_config.json",
        )
        path = _os.path.abspath(path)
        if _os.path.isfile(path):
            ok = self._ctrl.load_radio_config(path)
            if ok:
                print("[MainWindow] 电台 DAV 消息配置已加载")
            else:
                print("[MainWindow] 电台 DAV 消息配置加载失败")
        else:
            print(f"[MainWindow] radio_message_config not found: {path}")

    def _on_nest_toggle(self, checked: bool) -> None:
        """机巢按钮切换：开关 ip_prefixed 格式消息的接收与解析。"""
        self._ctrl.nest_enabled = checked
        self._nest_btn.setText("机巢 ●" if checked else "机巢")
        self._set_status("机巢(ip_prefixed)解析已开启" if checked else "机巢(ip_prefixed)解析已关闭")

    def _on_radio_toggle(self, checked: bool) -> None:
        """电台按钮切换：启动/停止 R2 电台 DAV 协议监听。"""
        if checked:
            try:
                # 确保配置已加载
                if not self._ctrl.load_radio_config(
                    self._get_radio_config_path()
                ):
                    self._set_status("电台配置加载失败，无法启动")
                    self._radio_btn.setChecked(False)
                    return

                # 使用默认电台端口 14555
                self._ctrl.set_radio_listener("0.0.0.0", 14555)
                self._ctrl.start_radio()
                self._radio_btn.setText("电台 ●")
                self._set_status("电台 DAV 监听中 — 0.0.0.0:14555")
            except Exception as e:
                self._set_status(f"电台启动失败: {e}")
                self._radio_btn.setChecked(False)
        else:
            self._ctrl.stop_radio()
            self._radio_btn.setText("电台")
            self._set_status("电台 DAV 监听已停止")

    @staticmethod
    def _get_radio_config_path() -> str:
        import os as _os
        path = _os.path.join(
            _os.path.dirname(__file__), "..", "..", "resources",
            "radio_message_config.json",
        )
        return _os.path.abspath(path)

    # ═══════════════════════════════════════════════════
    # 过滤回调
    # ═══════════════════════════════════════════════════
    def _on_filter_change(self, state: dict) -> None:
        rules = []
        if state.get("msgids"):
            rules.append(FilterRule("msgid", "in", ",".join(sorted(state["msgids"]))))
        if state.get("src_ips"):
            rules.append(FilterRule("srcip", "in", ",".join(sorted(state["src_ips"]))))
        if state.get("dst_ips"):
            rules.append(FilterRule("dstip", "in", ",".join(sorted(state["dst_ips"]))))
        if state.get("relay_ips"):
            rules.append(FilterRule("relayip", "in", ",".join(sorted(state["relay_ips"]))))
        self._ctrl.set_filter_rules(rules)
        self._ctrl.filter_enabled = state.get("enabled", True)
        # 过滤变更 → 两个视图都用过滤后数据重建
        self._rebuild_trace_table(filtered=True)
        self._rebuild_grouped_view(filtered=True)

    # ═══════════════════════════════════════════════════
    # 行点击 → lazy parse（两种视图共用）
    # ═══════════════════════════════════════════════════
    def _on_record_clicked(self, record) -> None:
        """统一的行点击处理：从平铺表格或分组树中点击消息。"""
        if record is None:
            return
        fields = self._ctrl.parse_fields(record)
        # 电台消息显示 DAV 协议信息
        if record.source_type == "radio":
            info = (f"{record.msg_name}  "
                    f"DAV(src=0x{record.sys_id:02X}, seq={record.seq_mav})  "
                    f"#{record.seq}")
        else:
            info = f"{record.msg_name or f'MSG_{record.msg_id}'} #{record.seq}"
        self.detail_tree.show_fields(info, fields, payload_hex=record.payload_hex, record=record)

    # ═══════════════════════════════════════════════════
    # 菜单操作
    # ═══════════════════════════════════════════════════
    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", "export.csv",
                                               "CSV (*.csv)")
        if path:
            self._ctrl.exporter.export_csv(self._ctrl.model.get_all(), path)
            self._set_status(f"已导出: {path}")

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出 JSON", "export.json",
                                               "JSON (*.json)")
        if path:
            self._ctrl.exporter.export_json(self._ctrl.model.get_all(), path)
            self._set_status(f"已导出: {path}")

    def _on_reset_stats(self) -> None:
        self._ctrl.reset_stats()
        self._set_status("统计已重置")

    def _on_clear_buffer(self) -> None:
        self._ctrl.clear_buffer()
        self._trace_table.clear()
        self._grouped_view.clear()
        self._set_status("缓冲已清空")

    def _on_pause_clicked(self) -> None:
        """统一工具栏暂停按钮。"""
        self._scroll_paused = not self._scroll_paused
        self._pause_btn.setText("▶ 恢复" if self._scroll_paused else "|| 暂停")
        # 同步两个视图（使用公共属性，避免直接访问私有属性）
        self._trace_table.scroll_paused = self._scroll_paused
        self._grouped_view.scroll_paused = self._scroll_paused
        self._set_status("滚动已暂停" if self._scroll_paused else "滚动已恢复")

    def _on_pause(self, paused: bool) -> None:
        """视图内部暂停回调（保持按钮同步）。"""
        self._scroll_paused = paused
        self._pause_btn.setText("▶ 恢复" if paused else "|| 暂停")
        self._trace_table.scroll_paused = paused
        self._grouped_view.scroll_paused = paused
        self._set_status("滚动已暂停" if paused else "滚动已恢复")

    def _on_toggle_time(self) -> None:
        """切换绝对/相对时间显示。"""
        cur = self._trace_table.time_mode
        new_mode = 1 - cur
        self._trace_table.time_mode = new_mode
        self._grouped_view.time_mode = new_mode  # setter 内更新列可见性（修复 H12）
        self._time_btn.setText("时间: 绝对" if new_mode == 0 else "时间: 相对")

    def _on_toggle_relay(self) -> None:
        """切换真实目标IP列可见性。"""
        visible = self._relay_btn.isChecked()
        self._trace_table._relay_visible = visible
        self._trace_table._view.setColumnHidden(5, not visible)
        self._relay_btn.setText("真实目标IP ✓" if visible else "真实目标IP")

    def _on_toggle_source(self) -> None:
        """切换来源列可见性。"""
        visible = self._source_btn.isChecked()
        self._trace_table._source_visible = visible
        self._trace_table._view.setColumnHidden(13, not visible)
        self._source_btn.setText("来源 ✓" if visible else "来源")

    def _on_display_limit_change(self, limit: int) -> None:
        self._display_limit = limit
        self._grouped_view.set_display_limit(limit)

    def _set_status(self, text: str) -> None:
        self._status_label.setText(text)

    # ═══════════════════════════════════════════════════
    # 视图模式切换
    # ═══════════════════════════════════════════════════
    def _on_toggle_view_mode(self, checked: bool) -> None:
        """切换平铺表格 ↔ 分组树视图。从 model 全量重建目标视图。"""
        if checked:
            self._view_stack.setCurrentIndex(1)
            self._mode_btn.setText("时间序视图")
            self._rebuild_grouped_view()
        else:
            self._view_stack.setCurrentIndex(0)
            self._mode_btn.setText("分组视图")
            self._rebuild_trace_table()

    def _rebuild_grouped_view(self, filtered: bool = False) -> None:
        """重建分组视图。"""
        self._grouped_view.clear()
        if filtered:
            records = self._ctrl.get_visible_records(max_count=self._display_limit)
        else:
            records = self._ctrl.model.get_latest(self._display_limit)
        for rec in records:
            self._grouped_view.add_record(rec)
        self._grouped_view.trim_messages(self._display_limit)
        self._grouped_view.scroll_to_bottom()

    def _rebuild_trace_table(self, filtered: bool = False) -> None:
        """重建平铺表格。"""
        self._trace_table.clear()
        if filtered:
            records = self._ctrl.get_visible_records(max_count=self._display_limit)
        else:
            records = self._ctrl.model.get_latest(self._display_limit)
        for rec in records:
            self._trace_table.add_record(rec)
        self._trace_table.trim_rows(self._display_limit)
        self._trace_table.scroll_to_bottom()

    def _center_on_screen(self) -> None:
        """将窗口居中到主屏幕可见区域。

        解决多屏环境下窗口可能显示在已断开屏幕外的问题。
        """
        from PySide6.QtGui import QScreen
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return

        # 优先使用主屏幕，确保窗口在有效显示区域内
        primary_screen = app.primaryScreen()
        if primary_screen is None:
            return

        available = primary_screen.availableGeometry()
        window_geo = self.frameGeometry()

        # 如果窗口尺寸大于可用区域，限制为可用区域的 90%
        if window_geo.width() > available.width():
            self.resize(int(available.width() * 0.9), self.height())
            window_geo = self.frameGeometry()
        if window_geo.height() > available.height():
            self.resize(self.width(), int(available.height() * 0.9))
            window_geo = self.frameGeometry()

        # 居中
        x = available.x() + (available.width() - window_geo.width()) // 2
        y = available.y() + (available.height() - window_geo.height()) // 2
        self.move(max(0, x), max(0, y))

    def closeEvent(self, event) -> None:
        self._ctrl.stop()
        super().closeEvent(event)
