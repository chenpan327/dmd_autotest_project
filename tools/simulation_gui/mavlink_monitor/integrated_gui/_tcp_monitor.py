"""TcpMonitorPanel — 云平台 TCP 消息监控子 Tab（GCS ↔ 云平台 TCP/TLS）。

从 integrated_gui 包新增的独立模块（v3.9，对应第 4 轮需求）：
把「地面站应用」TCP 监控从 UDP 消息监控 Tab 迁出到云平台拦截 Tab 的
专属子 Tab，独立 MonitorEngine + MonitorModel（与 UDP 监控完全解耦）。

布局:
    QSplitter(Horizontal)
    ├── 左栏 (fixed ~250px)
    │   ├── 网卡嗅探: 网卡 QComboBox + ⟳ + ▶开始嗅探/⏹停止嗅探 + 状态
    │   ├── 监控配置: 端口 QSpinBox(443) + [应用]
    │   └── 统计: TCP 包 / 记录 / 错误 / Buffer / Uptime
    └── 右区 (QVBoxLayout)
        ├── 捕获组: [|| 暂停] [清空]
        ├── 过滤组: SrcIP | SrcIP:Port | DstIP | DstIP:Port | [清除] [✓启用过滤]
        └── QSplitter(Vertical) 5:1 = TraceTable + DetailTree

依赖: mavlink_monitor.core.engine / gui.trace_table / gui.detail_tree
"""
from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from mavlink_monitor.core.engine import MonitorEngine
from mavlink_monitor.core.model import MonitorModel
from mavlink_monitor.gui.detail_tree import DetailTree
from mavlink_monitor.gui.left_panel import _get_interfaces
from mavlink_monitor.gui.trace_table import TraceTable

_POLL_MS = 50            # 与 UDP 监控 _on_tick 同节奏
_DEFAULT_PORT = 443
_MAX_COMBO_ITEMS = 50    # 过滤候选下拉上限
_DISPLAY_LIMIT = 100000


# ═══════════════════════════════════════════════════════════════
# TcpMonitorPanel
# ═══════════════════════════════════════════════════════════════
class TcpMonitorPanel(QWidget):
    """云平台 TCP 消息监控面板（独立引擎，gcs_app 数据源宿主）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FC_TCP_MONITOR")

        # 独立引擎：GCS 记录构造不走 parser（_process_raw_packet 才用），
        # parser=None 安全；与 UDP 监控的 engine/model 完全解耦。
        self._model = MonitorModel(capacity=4096000)
        self._engine = MonitorEngine(parser=None, model=self._model)

        self._last_seq = 0
        self._filter_enabled = False
        self._display_limit = _DISPLAY_LIMIT
        self._sniffing = False
        self._start_time = 0.0

        self._build_ui()

        self._poll_timer = QTimer(self)
        self._poll_timer.setObjectName("FC_TCP_TIMER_POLL")
        self._poll_timer.setInterval(_POLL_MS)
        self._poll_timer.timeout.connect(self._on_tick)
        self._poll_timer.start()

    # ═══════════════════════════════════════════════════════════
    # UI 构建
    # ═══════════════════════════════════════════════════════════
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("FC_TCP_SPLIT_MAIN")
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 900])
        root.addWidget(splitter)

    def _build_left_panel(self) -> QWidget:
        left = QWidget()
        left.setObjectName("FC_TCP_LEFT")
        ly = QVBoxLayout(left)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(4)

        # ── 网卡嗅探（复用 left_panel._get_interfaces 枚举） ──
        g_nic = QGroupBox("网卡嗅探")
        nl = QVBoxLayout(g_nic)
        nl.setSpacing(4)
        h = QHBoxLayout()
        h.addWidget(QLabel("网卡:"))
        self._nic_combo = QComboBox()
        self._nic_combo.setMinimumWidth(130)
        self._refresh_nic_list()
        h.addWidget(self._nic_combo, 1)
        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedWidth(28)
        refresh_btn.setToolTip("刷新网卡列表")
        refresh_btn.clicked.connect(self._refresh_nic_list)
        h.addWidget(refresh_btn)
        nl.addLayout(h)

        self._nic_btn = QPushButton("▶ 开始嗅探")
        self._nic_btn.setMinimumHeight(30)
        self._nic_btn.clicked.connect(self._on_toggle_sniff)
        nl.addWidget(self._nic_btn)
        self._nic_status = QLabel("● 未启动")
        nl.addWidget(self._nic_status)
        ly.addWidget(g_nic)

        # ── 监控配置 ──
        g_cfg = QGroupBox("监控配置")
        cl = QVBoxLayout(g_cfg)
        cl.setSpacing(4)
        h = QHBoxLayout()
        h.addWidget(QLabel("对端端口:"))
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(_DEFAULT_PORT)
        h.addWidget(self._port_spin, 1)
        apply_btn = QPushButton("应用")
        apply_btn.setFixedWidth(48)
        apply_btn.clicked.connect(self._on_port_apply)
        h.addWidget(apply_btn)
        cl.addLayout(h)
        self._port_status = QLabel(f"监控 tcp port {_DEFAULT_PORT}")
        cl.addWidget(self._port_status)
        ly.addWidget(g_cfg)

        # ── 统计 ──
        g_stat = QGroupBox("统计")
        sl = QVBoxLayout(g_stat)
        sl.setSpacing(2)
        self._stat_packets = QLabel("TCP 包: 0")
        self._stat_records = QLabel("记录: 0")
        self._stat_errors = QLabel("Errors: 0")
        self._stat_buf = QLabel(f"Buffer: 0 / 4096000")
        self._stat_uptime = QLabel("Uptime: 00:00:00")
        for w in (self._stat_packets, self._stat_records, self._stat_errors,
                  self._stat_buf, self._stat_uptime):
            sl.addWidget(w)
        ly.addWidget(g_stat)
        ly.addStretch(1)
        return left

    def _build_right_panel(self) -> QWidget:
        right = QWidget()
        right.setObjectName("FC_TCP_RIGHT")
        ly = QVBoxLayout(right)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(4)

        # ── 捕获 + 过滤 一行两组 ──
        bar = QHBoxLayout()
        bar.setSpacing(8)

        cap = QGroupBox("捕获")
        cl = QHBoxLayout(cap)
        cl.setSpacing(4)
        self._pause_btn = QPushButton("|| 暂停")
        self._pause_btn.setFixedWidth(52)
        self._pause_btn.clicked.connect(self._on_pause_clicked)
        cl.addWidget(self._pause_btn)
        self._clear_btn = QPushButton("清空")
        self._clear_btn.setFixedWidth(40)
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        cl.addWidget(self._clear_btn)
        bar.addWidget(cap)

        flt = QGroupBox("过滤")
        fl = QHBoxLayout(flt)
        fl.setSpacing(4)
        self._combo_srcip = self._make_filter_combo("SrcIP")
        self._combo_srcport = self._make_filter_combo("SrcIP:Port")
        self._combo_dstip = self._make_filter_combo("DstIP")
        self._combo_dstport = self._make_filter_combo("DstIP:Port")
        self._filter_clear_btn = QPushButton("清除")
        self._filter_clear_btn.setFixedWidth(40)
        self._filter_clear_btn.clicked.connect(self._on_clear_filter)
        self._filter_enable_chk = QCheckBox("启用过滤")
        self._filter_enable_chk.toggled.connect(self._on_filter_toggled)
        for lbl, combo in (("SrcIP", self._combo_srcip),
                           ("SrcIP:Port", self._combo_srcport),
                           ("DstIP", self._combo_dstip),
                           ("DstIP:Port", self._combo_dstport)):
            fl.addWidget(QLabel(lbl))
            fl.addWidget(combo, 1)
        fl.addWidget(self._filter_clear_btn)
        fl.addWidget(self._filter_enable_chk)
        bar.addWidget(flt, stretch=1)
        ly.addLayout(bar)

        # ── 时间序表格 + 详情（上下 5:1） ──
        splitter = QSplitter(Qt.Vertical)
        splitter.setObjectName("FC_TCP_SPLIT_VIEW")
        # show_toolbar=False：表格内建工具栏（暂停/清空/时间/真实目标IP/来源）
        # 不创建 —— 捕获与清空由外层捕获组提供（v3.10）
        self._trace_table = TraceTable(show_toolbar=False)
        self._trace_table.setObjectName("FC_TCP_TRACE_TABLE")
        self._trace_table.on_record_clicked.connect(self._on_record_clicked)
        self._trace_table.on_pause.connect(self._on_table_pause)
        splitter.addWidget(self._trace_table)
        self._detail_tree = DetailTree()
        self._detail_tree.setObjectName("FC_TCP_DETAIL")
        splitter.addWidget(self._detail_tree)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([500, 100])
        ly.addWidget(splitter, stretch=1)
        return right

    def _make_filter_combo(self, tooltip: str) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setToolTip(f"{tooltip} 过滤（可从下拉选择或手动输入，留空不过滤）")
        return combo

    # ═══════════════════════════════════════════════════════════
    # 网卡 / 端口
    # ═══════════════════════════════════════════════════════════
    def _refresh_nic_list(self) -> None:
        current = self._nic_combo.currentText()
        self._nic_combo.clear()
        ifaces = _get_interfaces()
        self._nic_combo.addItems(ifaces)
        if current and current in ifaces:
            self._nic_combo.setCurrentText(current)

    def _on_toggle_sniff(self) -> None:
        if self._sniffing:
            self._stop_sniffing()
            return
        iface = self._nic_combo.currentText().strip()
        if not iface or "(无可用网卡)" in iface:
            self._nic_status.setText("● 无可用网卡")
            return
        try:
            self._engine.set_interface(iface)
            self._engine.set_gcs_app_listener(self._port_spin.value())
            self._engine.start_gcs_app()
        except Exception as e:
            self._nic_status.setText(f"● 启动失败: {e}")
            return
        self._sniffing = True
        self._start_time = time.time()
        self._nic_btn.setText("⏹ 停止嗅探")
        self._nic_status.setText("● 嗅探中...")
        self._nic_combo.setEnabled(False)

    def _stop_sniffing(self) -> None:
        try:
            self._engine.stop_gcs_app()
        except Exception:
            pass
        self._sniffing = False
        self._nic_btn.setText("▶ 开始嗅探")
        self._nic_status.setText("● 已停止")
        self._nic_combo.setEnabled(True)

    def _on_port_apply(self) -> None:
        port = self._port_spin.value()
        was_running = self._sniffing
        if was_running:
            self._stop_sniffing()
        self._engine.set_gcs_app_listener(port)
        self._port_status.setText(f"监控 tcp port {port}")
        if was_running:
            self._on_toggle_sniff()

    # ═══════════════════════════════════════════════════════════
    # 轮询
    # ═══════════════════════════════════════════════════════════
    def _on_tick(self) -> None:
        if self._engine.is_running:
            new = self._model.get_since(self._last_seq)
            if new:
                self._last_seq = new[-1].seq
                self._collect_filter_candidates(new)
                if self._filter_enabled:
                    shown = [r for r in new if self._match_filter(r)]
                else:
                    shown = new
                if shown:
                    self._trace_table.add_records(shown)
                    self._trace_table.trim_rows(self._display_limit)
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        used, cap = self._model.buffer_usage
        self._stat_packets.setText(
            f"TCP 包: {self._engine.gcs_app_packet_count}")
        self._stat_records.setText(f"记录: {self._engine.gcs_app_record_count}")
        self._stat_errors.setText(f"Errors: {self._engine.gcs_app_error_count}")
        self._stat_buf.setText(f"Buffer: {used} / {cap}")
        if self._start_time > 0 and self._sniffing:
            up = int(time.time() - self._start_time)
            h, m, s = up // 3600, (up % 3600) // 60, up % 60
            self._stat_uptime.setText(f"Uptime: {h:02d}:{m:02d}:{s:02d}")

    # ═══════════════════════════════════════════════════════════
    # 过滤（自建四维：SrcIP / SrcIP:Port / DstIP / DstIP:Port，AND 语义）
    # ═══════════════════════════════════════════════════════════
    def _collect_filter_candidates(self, records: list) -> None:
        for combo, values in (
            (self._combo_srcip, {r.src_ip for r in records}),
            (self._combo_srcport, {f"{r.src_ip}:{r.src_port}" for r in records}),
            (self._combo_dstip, {r.dst_ip for r in records}),
            (self._combo_dstport, {f"{r.dst_ip}:{r.dst_port}" for r in records}),
        ):
            existing = {combo.itemText(i) for i in range(combo.count())}
            for v in sorted(values - existing):
                if combo.count() >= _MAX_COMBO_ITEMS:
                    break
                combo.addItem(v)

    def _match_filter(self, record) -> bool:
        """OR 语义（v3.10）：四个条件任一命中即显示（并集），全部留空显示全部。"""
        checks = []
        v = self._combo_srcip.currentText().strip()
        if v:
            checks.append(record.src_ip == v)
        v = self._combo_srcport.currentText().strip()
        if v:
            checks.append(f"{record.src_ip}:{record.src_port}" == v)
        v = self._combo_dstip.currentText().strip()
        if v:
            checks.append(record.dst_ip == v)
        v = self._combo_dstport.currentText().strip()
        if v:
            checks.append(f"{record.dst_ip}:{record.dst_port}" == v)
        if not checks:
            return True      # 无条件 → 全部显示
        return any(checks)

    def _on_filter_toggled(self, checked: bool) -> None:
        self._filter_enabled = checked
        self._rebuild_table()

    def _on_clear_filter(self) -> None:
        for combo in (self._combo_srcip, self._combo_srcport,
                      self._combo_dstip, self._combo_dstport):
            combo.setCurrentText("")
        self._rebuild_table()

    def _rebuild_table(self) -> None:
        """从 model 快照全量重建表格（过滤条件变化/清除时）。"""
        recs = self._model.get_latest(self._display_limit)
        if self._filter_enabled:
            recs = [r for r in recs if self._match_filter(r)]
        self._trace_table.clear()
        if recs:
            self._trace_table.add_records(recs)

    # ═══════════════════════════════════════════════════════════
    # 捕获控制 / 详情
    # ═══════════════════════════════════════════════════════════
    def _on_pause_clicked(self) -> None:
        paused = not self._trace_table.scroll_paused
        self._trace_table.scroll_paused = paused
        self._pause_btn.setText("▶ 恢复" if paused else "|| 暂停")

    def _on_table_pause(self, paused: bool) -> None:
        self._pause_btn.setText("▶ 恢复" if paused else "|| 暂停")

    def _on_clear_clicked(self) -> None:
        self._trace_table.clear()
        self._detail_tree.clear_fields()

    def _on_record_clicked(self, record) -> None:
        """点击记录 → DetailTree 渲染（gcs 记录 fields_parsed=True，无需 controller）。"""
        if record is None:
            return
        info = f"{record.msg_name or 'GCS_TCP'} #{record.seq}"
        self._detail_tree.show_fields(
            info, getattr(record, "fields", None) or [],
            payload_hex=record.payload_hex, record=record,
        )

    # ═══════════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════════
    def shutdown(self) -> None:
        self._poll_timer.stop()
        try:
            self._engine.stop_gcs_app()
        except Exception:
            pass
        try:
            self._engine.stop()
        except Exception:
            pass
