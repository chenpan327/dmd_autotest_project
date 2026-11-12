"""FullUdpMonitorPanel — UDP 监控 Tab（包装 MonitorTab + 假节点消息）。

从 integrated_gui.py 拆分出来的独立模块。
依赖: mavlink_monitor.core, mavlink_monitor.gui（无内部 integrated_gui 依赖）
"""
from __future__ import annotations

import json
import os
import socket
import time
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QSpinBox, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

from mavlink_monitor.core.controller import MonitorController
from mavlink_monitor.core.filter import FilterRule
from mavlink_monitor.core.paths import get_radio_message_xml

from mavlink_monitor.gui.detail_tree import DetailTree
from mavlink_monitor.gui.filter_bar import FilterBar
from mavlink_monitor.gui.grouped_trace_view import GroupedTraceView
from mavlink_monitor.gui.left_panel import LeftPanel
from mavlink_monitor.gui.trace_table import TraceTable
from mavlink_monitor.gui.widgets import _CollapseToggle, _LimitedCombo

# 资源目录：_monitor.py 位于 mavlink_monitor/integrated_gui/ 下，
# 需上溯 3 级（integrated_gui → mavlink_monitor → simulation_gui）到 simulation_gui/resources
_RESOURCES_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "resources",
))

# ═══════════════════════════════════════════════════════════════
# UdpMonitorPanel —— UDP 监控 Tab（包装 MonitorTab + 假节点消息）
# ═══════════════════════════════════════════════════════════════
class FullUdpMonitorPanel(QWidget):
    """UDP 消息监控面板 — 照搬 MainWindow 的完整布局 + 假节点消息感知。

    包含:
    - 左面板: 配置加载 + 网卡嗅探 + 统计
    - 2×2 功能组网格: 视图 / 数据源 / 捕获 / 过滤
    - 双视图: 时间序平铺表格 + CANoe 风格分组树
    - 字段详情树
    - 底部假节点消息状态栏
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ctrl = MonitorController()
        self._scroll_paused = False
        self._display_limit = 100000
        self._seen_ips: set[str] = set()
        self._seen_relay_ips: set[str] = set()

        # 假节点状态
        self._fake_ips: set[str] = set()
        self._show_fake_only: bool = False

        self._setup_central()
        self._setup_timer()
        self._load_command_183_config()
        self._load_radio_config()

    # ═══════════════════════════════════════════════════════════
    # 中央布局（照搬 MainWindow._setup_central）
    # ═══════════════════════════════════════════════════════════
    def _setup_central(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        h_split = QSplitter(Qt.Orientation.Horizontal)

        # ── 左面板 ──
        self._left_panel = LeftPanel()
        self._left_panel.setFixedWidth(290)
        self._left_panel.on_start_nic.connect(self._on_start_nic)
        self._left_panel.on_stop_nic.connect(self._on_stop_nic)
        self._left_panel.on_config_changed.connect(self._on_config_changed)
        h_split.addWidget(self._left_panel)

        # ── 右区域 ──
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(2)

        self._filter_bar = FilterBar(on_filter_change=self._on_filter_change)
        self._left_panel.load_initial_config()
        self._ctrl.filter_enabled = False
        self._ctrl.clear_filter()

        # ── 2×2 功能组 ──
        TAG_WIDTH = 42

        def _tag(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFixedWidth(TAG_WIDTH)
            lbl.setStyleSheet("color: #666; font-weight: bold; font-size: 11px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return lbl

        def _cell(tag_text: str, *widgets: QWidget) -> QWidget:
            ctn = QWidget()
            ly = QHBoxLayout(ctn)
            ly.setContentsMargins(4, 2, 4, 2)
            ly.setSpacing(4)
            ly.addWidget(_tag(tag_text))
            for w in widgets:
                ly.addWidget(w)
            ly.addStretch(1)
            return ctn

        # Row 0, Col 0: 视图组
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
        self._display_limit_spin.setValue(100000)
        self._display_limit_spin.setFixedWidth(80)
        self._display_limit_spin.valueChanged.connect(self._on_display_limit_change)
        view_ctn = _cell("视图", self._time_btn, self._mode_btn, self._relay_btn,
                          self._source_btn, limit_lbl, self._display_limit_spin)

        # Row 0, Col 1: 数据源组
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
        # 「地面站应用」TCP 监控已迁至云平台拦截 Tab 的「TCP 消息监控」子 Tab
        # （v3.9），不再作为 UDP 监控数据源。
        src_ctn = _cell("数据源", self._nest_btn, self._radio_btn)

        # Row 1, Col 0: 捕获组
        self._pause_btn = QPushButton("|| 暂停")
        self._pause_btn.setFixedWidth(52)
        self._pause_btn.clicked.connect(self._on_pause_clicked)
        self._clear_btn_ctrl = QPushButton("清空")
        self._clear_btn_ctrl.setFixedWidth(40)
        self._clear_btn_ctrl.clicked.connect(self._on_clear_buffer)
        cap_ctn = _cell("捕获", self._pause_btn, self._clear_btn_ctrl)

        # Row 1, Col 1: 过滤组
        self._filter_bar._tag_label.setVisible(False)
        filter_ctn = QWidget()
        fl = QHBoxLayout(filter_ctn)
        fl.setContentsMargins(4, 2, 4, 2)
        fl.setSpacing(4)
        fl.addWidget(_tag("过滤"))
        fl.addWidget(self._filter_bar, 1)

        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.addWidget(view_ctn,   0, 0)
        grid.addWidget(src_ctn,    0, 1)
        grid.addWidget(cap_ctn,    1, 0)
        grid.addWidget(filter_ctn, 1, 1)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        rl.addLayout(grid)

        # ── QStackedWidget 双视图 ──
        self._view_stack = QStackedWidget()

        self._trace_table = TraceTable()
        self._trace_table.toolbar_visible = False
        self._trace_table.on_record_clicked.connect(self._on_record_clicked)
        self._trace_table.on_pause.connect(self._on_pause)
        self._view_stack.addWidget(self._trace_table)

        self._grouped_view = GroupedTraceView(display_limit=self._display_limit)
        self._grouped_view.toolbar_visible = False
        self._grouped_view.on_record_clicked.connect(self._on_record_clicked)
        self._grouped_view.on_pause.connect(self._on_pause)
        self._view_stack.addWidget(self._grouped_view)

        v_split = QSplitter(Qt.Orientation.Vertical)
        v_split.addWidget(self._view_stack)

        self._detail_tree = DetailTree()
        v_split.addWidget(self._detail_tree)
        v_split.setSizes([650, 150])

        rl.addWidget(v_split, 1)
        h_split.addWidget(right)

        root.addWidget(h_split, stretch=1)

        # ── 底部：假节点消息状态栏 ──
        fake_bar = QWidget()
        fake_bar.setObjectName("UDP_FAKE_BAR")
        fake_bar.setFixedHeight(32)
        fake_layout = QHBoxLayout(fake_bar)
        fake_layout.setContentsMargins(8, 2, 8, 2)

        self._fake_info_label = QLabel("假节点: (无)")
        self._fake_info_label.setObjectName("UDP_LBL_FAKE_INFO")
        fake_layout.addWidget(self._fake_info_label)
        fake_layout.addSpacing(16)

        self._fake_rx_label = QLabel("收到: 0")
        self._fake_rx_label.setObjectName("UDP_LBL_FAKE_RX")
        fake_layout.addWidget(self._fake_rx_label)
        fake_layout.addSpacing(16)

        self._chk_fake_only = QCheckBox("仅显示假节点收到的消息")
        self._chk_fake_only.setObjectName("UDP_CHK_FAKE_ONLY")
        self._chk_fake_only.stateChanged.connect(self._on_fake_only_changed)
        fake_layout.addWidget(self._chk_fake_only)
        fake_layout.addStretch()

        self._btn_refresh_fake = QPushButton("刷新假节点IP")
        self._btn_refresh_fake.setObjectName("UDP_BTN_REFRESH_FAKE")
        fake_layout.addWidget(self._btn_refresh_fake)

        root.addWidget(fake_bar)

    # ═══════════════════════════════════════════════════════════
    # 定时器
    # ═══════════════════════════════════════════════════════════
    def _setup_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer_interval = 50        # 当前刷新间隔 ms（自适应调整）
        self._timer_min_interval = 50    # 最小间隔（最高刷新率）
        self._timer_max_interval = 200   # 最大间隔（最低刷新率，避免视觉停滞）
        self._timer.start(self._timer_interval)

    # ═══════════════════════════════════════════════════════════
    # 定时刷新（照搬 MainWindow._on_tick）
    # ═══════════════════════════════════════════════════════════
    def _on_tick(self) -> None:
        if not self._ctrl.is_running:
            return

        if not self._scroll_paused:
            records = self._ctrl.get_new_records()

            # ── 自适应刷新率 ──
            # 单 tick 消息量 > 200 时降低刷新率（减少 GUI 渲染压力）
            # 单 tick 消息量 < 50 时恢复高刷新率
            count = len(records)
            if count > 200 and self._timer_interval < self._timer_max_interval:
                self._timer_interval = min(self._timer_interval + 10, self._timer_max_interval)
                self._timer.setInterval(self._timer_interval)
            elif count < 50 and self._timer_interval > self._timer_min_interval:
                self._timer_interval = max(self._timer_interval - 10, self._timer_min_interval)
                self._timer.setInterval(self._timer_interval)

            # 优化：仅更新当前活跃视图
            active_index = self._view_stack.currentIndex()
            active_view = self._trace_table if active_index == 0 else self._grouped_view

            # 在添加记录前记住是否在底部（用户手动上滚则不强制拉回）
            was_at_bottom = active_view.is_at_bottom()

            if active_index == 0:
                # TraceTable: 批量添加（QAbstractTableModel 虚拟列表）
                self._trace_table.add_records(records)
            else:
                # GroupedTraceView: 逐条添加
                for rec in records:
                    active_view.add_record(rec)

            if active_index == 0:
                self._trace_table.trim_rows(self._display_limit)
            else:
                self._grouped_view.trim_messages(self._display_limit)

            # 如果之前就在底部，添加新记录后自动滚到底部
            if was_at_bottom and records:
                active_view.scroll_to_bottom()

            # 收集新 IP
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
                self._filter_bar.set_ip_options(self._seen_ips)
            if new_relay_ips:
                self._seen_relay_ips |= new_relay_ips
                self._filter_bar.set_relayip_options(self._seen_relay_ips)

        # 统计
        s = self._ctrl.get_stats()
        self._left_panel.update_stats(
            s["total"], s["rate"], s["errors"], s["crc_fail"],
            s["nic_packets"], s["nic_mavlink"],
            s["buffer_used"], s["buffer_max"], s["uptime"],
            s.get("radio_packets", 0), s.get("radio_mavlink", 0),
        )

        # 假节点消息统计
        self._update_fake_stats()

    # ═══════════════════════════════════════════════════════════
    # 网卡嗅探
    # ═══════════════════════════════════════════════════════════
    def _on_start_nic(self, iface: str) -> None:
        if not self._ctrl.is_config_ready:
            self._left_panel.set_sniffing_stopped()
            return
        try:
            self._ctrl.set_interface(iface)
            self._ctrl.start()
        except Exception as e:
            print(f"[UDP] 启动嗅探失败: {e}")
            self._left_panel.set_sniffing_stopped()

    def _on_stop_nic(self) -> None:
        self._ctrl.stop()

    # ═══════════════════════════════════════════════════════════
    # 配置
    # ═══════════════════════════════════════════════════════════
    def _on_config_changed(self, config_path: str, enums_path: str,
                           version: str) -> None:
        ok = True
        if config_path and os.path.isfile(config_path):
            ok &= self._ctrl.load_config(config_path, version)
        if enums_path and os.path.isfile(enums_path):
            ok &= self._ctrl.load_enums(enums_path, version)
        if ok:
            msgids = self._ctrl.get_available_msgids()
            if msgids:
                self._filter_bar.set_msgid_options(msgids)
            self._seen_ips.clear()
            self._filter_bar.set_ip_options(set())
            self._seen_relay_ips.clear()
            self._filter_bar.set_relayip_options(set())

    # ═══════════════════════════════════════════════════════════
    # command=183 / 电台配置
    # ═══════════════════════════════════════════════════════════
    def _load_command_183_config(self) -> None:
        path = os.path.join(_RESOURCES_DIR, "command_183_functions.json")
        if os.path.isfile(path):
            self._ctrl.load_command_183_config(path)

    def _load_radio_config(self) -> None:
        path = self._get_radio_config_path()
        if os.path.isfile(path):
            self._ctrl.load_radio_config(path)

    def _get_radio_config_path(self) -> str:
        """返回电台消息配置路径：优先权威 DavMessage.proto，回退协议 XML。"""
        proto = os.path.join(_RESOURCES_DIR, "DavMessage.proto")
        if os.path.isfile(proto):
            return proto
        xml = get_radio_message_xml()
        if xml:
            return xml
        return ""

    # ═══════════════════════════════════════════════════════════
    # 按钮回调
    # ═══════════════════════════════════════════════════════════
    def _on_toggle_time(self) -> None:
        cur = self._trace_table._time_mode
        new_mode = 1 - cur
        self._trace_table._time_mode = new_mode
        self._trace_table._view.setColumnHidden(1, new_mode == 0)
        self._trace_table._view.setColumnHidden(2, new_mode == 1)
        self._grouped_view._time_mode = new_mode
        self._time_btn.setText("时间: 绝对" if new_mode == 0 else "时间: 相对")

    def _on_toggle_view_mode(self, checked: bool) -> None:
        if checked:
            self._view_stack.setCurrentIndex(1)
            self._mode_btn.setText("时间序视图")
            self._rebuild_grouped_view()
        else:
            self._view_stack.setCurrentIndex(0)
            self._mode_btn.setText("分组视图")
            self._rebuild_trace_table()

    def _on_toggle_relay(self) -> None:
        visible = self._relay_btn.isChecked()
        self._trace_table._relay_visible = visible
        self._trace_table._view.setColumnHidden(5, not visible)
        self._relay_btn.setText("真实目标IP ✓" if visible else "真实目标IP")

    def _on_toggle_source(self) -> None:
        visible = self._source_btn.isChecked()
        self._trace_table._source_visible = visible
        self._trace_table._view.setColumnHidden(13, not visible)
        self._source_btn.setText("来源 ✓" if visible else "来源")

    def _on_display_limit_change(self, limit: int) -> None:
        self._display_limit = limit
        self._grouped_view.set_display_limit(limit)

    def _on_pause_clicked(self) -> None:
        self._scroll_paused = not self._scroll_paused
        self._pause_btn.setText("▶ 恢复" if self._scroll_paused else "|| 暂停")
        self._trace_table._scroll_paused = self._scroll_paused
        self._grouped_view._scroll_paused = self._scroll_paused

    def _on_pause(self, paused: bool) -> None:
        self._scroll_paused = paused
        self._pause_btn.setText("▶ 恢复" if paused else "|| 暂停")
        self._trace_table._scroll_paused = paused
        self._grouped_view._scroll_paused = paused

    def _on_clear_buffer(self) -> None:
        self._ctrl.clear_buffer()
        self._trace_table.clear()
        self._grouped_view.clear()

    def _on_nest_toggle(self, checked: bool) -> None:
        self._ctrl.nest_enabled = checked
        self._nest_btn.setText("机巢 ●" if checked else "机巢")

    def _on_radio_toggle(self, checked: bool) -> None:
        if checked:
            try:
                self._ctrl.load_radio_config(self._get_radio_config_path())
                self._ctrl.set_radio_listener("0.0.0.0", 14555)
                self._ctrl.start_radio()
                self._radio_btn.setText("电台 ●")
            except Exception as e:
                print(f"[UDP] 电台启动失败: {e}")
                self._radio_btn.setChecked(False)
        else:
            self._ctrl.stop_radio()
            self._radio_btn.setText("电台")

    # ═══════════════════════════════════════════════════════════
    # 过滤
    # ═══════════════════════════════════════════════════════════
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
        self._rebuild_trace_table(filtered=True)
        self._rebuild_grouped_view(filtered=True)

    def _on_record_clicked(self, record) -> None:
        if record is None:
            return
        fields = self._ctrl.parse_fields(record)
        if record.source_type == "radio":
            info = (f"{record.msg_name}  "
                    f"DAV(src=0x{record.sys_id:02X}, seq={record.seq_mav})  "
                    f"#{record.seq}")
        else:
            info = f"{record.msg_name or f'MSG_{record.msg_id}'} #{record.seq}"
        self._detail_tree.show_fields(info, fields,
                                       payload_hex=record.payload_hex,
                                       record=record)

    def _rebuild_grouped_view(self, filtered: bool = False) -> None:
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
        self._trace_table.clear()
        if filtered:
            records = self._ctrl.get_visible_records(max_count=self._display_limit)
        else:
            records = self._ctrl.model.get_latest(self._display_limit)
        if records:
            self._trace_table.add_records(records)
        self._trace_table.trim_rows(self._display_limit)
        self._trace_table.scroll_to_bottom()

    # ═══════════════════════════════════════════════════════════
    # 假节点消息功能
    # ═══════════════════════════════════════════════════════════
    def inject_raw_message(self, data: bytes, src_ip: str, src_port: int,
                           dst_ip: str, dst_port: int) -> None:
        """将假节点收发的原始消息直接注入监控引擎。

        由 SimulationPanel 在假节点 recvfrom/sendto 时调用，
        绕过网卡嗅探，直接将消息写入 MonitorModel。

        电台 DAV 帧（0xA5 同步字）走 radio parser（source_type="radio"），
        其余走 MAVLink parser（source_type="fake"）。
        """
        if not data:
            return
        # 电台 DAV 帧分流：DAV 帧首字节 0xA5，不受 MAVLink 配置门禁限制
        if data[0] == 0xA5:
            self._ctrl.inject_radio_packet(data, src_ip, src_port, dst_ip, dst_port)
            return
        if not self._ctrl.is_config_ready:
            return
        self._ctrl.engine._process_raw_packet(
            data, src_ip, src_port, dst_ip, dst_port,
            node_id=f"fake_{dst_ip}", source_type="fake",
        )

    def set_fake_node_ips(self, ips: list[str]) -> None:
        """设置当前活跃假节点 IP 列表（由 IntegratedMainWindow 定时调用）。"""
        self._fake_ips = set(ips)
        self._update_fake_info_label()

    def _update_fake_info_label(self) -> None:
        if self._fake_ips:
            ip_list = ", ".join(sorted(self._fake_ips))
            self._fake_info_label.setText(f"假节点: {ip_list}")
            self._fake_info_label.setStyleSheet("color: #1f9d55; font-weight: bold;")
        else:
            self._fake_info_label.setText("假节点: (无)")
            self._fake_info_label.setStyleSheet("color: #9aa0a6;")

    def _update_fake_stats(self) -> None:
        """定时更新假节点消息统计（仅 dst_ip 匹配假节点 IP 的消息）。"""
        if not self._fake_ips:
            return
        try:
            records = self._ctrl.model.get_latest(1000)
        except Exception:
            return
        rx_count = sum(1 for r in records if r.dst_ip in self._fake_ips)
        self._fake_rx_label.setText(f"收到(最近1000条): {rx_count}")

    def _on_fake_only_changed(self, state: int) -> None:
        self._show_fake_only = (state == Qt.CheckState.Checked.value)
        if self._show_fake_only and self._fake_ips:
            rule = FilterRule(
                field="dstip",
                operator="in",
                value=",".join(sorted(self._fake_ips)),
                is_highlight=True,
            )
            self._ctrl.filter.clear()
            self._ctrl.filter.add_rule(rule)
            self._ctrl.filter_enabled = True
            self._rebuild_trace_table(filtered=True)
            self._rebuild_grouped_view(filtered=True)
        else:
            self._ctrl.filter.clear()
            self._ctrl.filter_enabled = False
            self._rebuild_trace_table(filtered=False)
            self._rebuild_grouped_view(filtered=False)

    # ═══════════════════════════════════════════════════════════
    # 清理
    # ═══════════════════════════════════════════════════════════
    def shutdown(self) -> None:
        """停止所有后台任务。"""
        self._ctrl.stop_radio()
        self._ctrl.stop_udp()
        self._ctrl.stop()

