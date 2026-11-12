"""CloudProxyPanel — 云平台拦截 Tab（SimulationPanel 控制 + 消息监视复合面板）。

从 integrated_gui 包新增的独立模块（对应 fake_cloud 子方案）。
依赖: ._config, ._panels, fake_cloud.json_diff
"""
from __future__ import annotations

import html
import time
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QTextBrowser,
    QVBoxLayout, QWidget,
)

from fake_cloud.json_diff import highlight_html, syntax_highlight

from ._config import SimConfig
from ._panels import SimulationPanel
from ._tcp_monitor import TcpMonitorPanel

# ═══════════════════════════════════════════════════════════════
# 事件类型展示映射（tampered_response 预留篡改阶段）
# ═══════════════════════════════════════════════════════════════
_KIND_LABELS = {
    "gcs_request": "地面站→云",
    "cloud_response": "云→地面站",
    "tampered_response": "GUI篡改(预留)",
    "proxy_error": "代理错误",
}
_KIND_COLORS = {
    "gcs_request": QColor("#1677ff"),
    "cloud_response": QColor("#52c41a"),
    "tampered_response": QColor("#fa8c16"),
    "proxy_error": QColor("#ff4d4f"),
}
_MAX_VIEW_ROWS = 5000          # 表格行数上限（超出丢弃最旧）
_POLL_INTERVAL_MS = 50         # 与 UDP 监控 _on_tick 同节奏


# ═══════════════════════════════════════════════════════════════
# CloudMessageView — 消息监视视图
# ═══════════════════════════════════════════════════════════════
class CloudMessageView(QWidget):
    """云平台 HTTP 消息监视：事件表格 + 详情 HTML 高亮视图。

    数据来源：QTimer 轮询所有 _FakeCloudSender.drain_events()
    （与 FullUdpMonitorPanel._on_tick 的 get_new_records 模式一致）。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FC_MESSAGE_VIEW")
        self._paused = False
        self._promotion_only = False
        self._counts: dict[str, int] = {}
        self._pending: list[dict] = []   # 暂停期间积压

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        # ── 工具栏 ──
        bar = QHBoxLayout()
        self._btn_pause = QPushButton("暂停")
        self._btn_pause.setObjectName("FC_BTN_PAUSE")
        self._btn_pause.setCheckable(True)
        self._btn_pause.clicked.connect(self._on_pause_toggled)

        self._btn_clear = QPushButton("清空")
        self._btn_clear.setObjectName("FC_BTN_CLEAR")
        self._btn_clear.clicked.connect(self._on_clear)

        self._btn_filter = QPushButton("仅看广告接口")
        self._btn_filter.setObjectName("FC_BTN_FILTER")
        self._btn_filter.setCheckable(True)
        self._btn_filter.clicked.connect(self._on_filter_toggled)

        self._lbl_stats = QLabel("事件 0")
        self._lbl_stats.setObjectName("FC_LBL_STATS")

        bar.addWidget(self._btn_pause)
        bar.addWidget(self._btn_clear)
        bar.addWidget(self._btn_filter)
        bar.addStretch(1)
        bar.addWidget(self._lbl_stats)
        root.addLayout(bar)

        # ── 上下分割：表格 + 详情 ──
        splitter = QSplitter(Qt.Vertical)
        splitter.setObjectName("FC_SPLIT_VIEW")

        self._table = QTableWidget(0, 7)
        self._table.setObjectName("FC_TABLE_EVENTS")
        self._table.setHorizontalHeaderLabels(
            ["#", "时间", "类型", "方法", "路径", "状态", "摘要"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.Stretch)
        h.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(6, QHeaderView.Stretch)
        self._table.cellClicked.connect(self._on_row_clicked)
        splitter.addWidget(self._table)

        self._detail = QTextBrowser()
        self._detail.setObjectName("FC_DETAIL")
        self._detail.setOpenExternalLinks(False)
        self._detail.setHtml("<i>点击上方事件行查看详情（请求头 / 响应信封 / JSON 高亮；"
                             "篡改对比区预留）</i>")
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root.addWidget(splitter, stretch=1)

    # ── 事件流入 ──
    def add_event(self, event: dict) -> None:
        """追加一条事件（暂停时积压；恢复后批量入表）。"""
        kind = str(event.get("kind", "?"))
        self._counts[kind] = self._counts.get(kind, 0) + 1
        if self._paused:
            self._pending.append(event)
            self._update_stats()
            return
        self._append_row(event)

    def _append_row(self, event: dict) -> None:
        if self._promotion_only and "/promotion/" not in str(event.get("path", "")):
            return
        row = self._table.rowCount()
        self._table.insertRow(row)

        kind = str(event.get("kind", "?"))
        color = _KIND_COLORS.get(kind)

        def _item(text: str, align_center: bool = False) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            if align_center:
                it.setTextAlignment(Qt.AlignCenter)
            it.setData(Qt.UserRole, event)   # 行 → 完整事件（详情渲染用）
            if color is not None:
                it.setForeground(color)
            return it

        ts = time.strftime("%H:%M:%S", time.localtime(event.get("ts", 0)))
        ms = int(event.get("ts", 0) * 1000) % 1000
        self._table.setItem(row, 0, _item(str(event.get("seq", "")), True))
        self._table.setItem(row, 1, _item(f"{ts}.{ms:03d}", True))
        self._table.setItem(row, 2, _item(_KIND_LABELS.get(kind, kind), True))
        self._table.setItem(row, 3, _item(str(event.get("method", "-")), True))
        self._table.setItem(row, 4, _item(str(event.get("path", ""))))
        self._table.setItem(row, 5, _item(str(event.get("status") or "-"), True))
        self._table.setItem(row, 6, _item(str(event.get("summary", ""))))

        # 超限裁剪最旧行
        if self._table.rowCount() > _MAX_VIEW_ROWS:
            self._table.removeRow(0)

        # 自动滚动（列表本来就在底部时才跟随）
        sb = self._table.verticalScrollBar()
        if sb.value() >= sb.maximum() - 4:
            self._table.scrollToBottom()

    def drain_poll(self, senders: list[Any]) -> None:
        """QTimer 轮询入口：拉取所有 sender 的积压事件。"""
        for s in senders:
            drain = getattr(s, "drain_events", None)
            if drain is None:
                continue
            try:
                for ev in drain():
                    self.add_event(ev)
            except Exception:
                pass
        self._update_stats()

    # ── 工具栏回调 ──
    def _on_pause_toggled(self) -> None:
        self._paused = self._btn_pause.isChecked()
        self._btn_pause.setText("继续" if self._paused else "暂停")
        if not self._paused and self._pending:
            pending, self._pending = self._pending, []
            for ev in pending:
                self._append_row(ev)
            self._update_stats()

    def _on_clear(self) -> None:
        self._table.setRowCount(0)
        self._pending.clear()
        self._counts.clear()
        self._detail.setHtml("<i>已清空</i>")
        self._update_stats()

    def _on_filter_toggled(self) -> None:
        self._promotion_only = self._btn_filter.isChecked()
        self._btn_filter.setText("仅看广告接口 (开)" if self._promotion_only
                                 else "仅看广告接口")

    def _update_stats(self) -> None:
        parts = [f"{_KIND_LABELS.get(k, k)} {v}" for k, v in self._counts.items()]
        pending = f"  积压 {len(self._pending)}" if self._pending else ""
        self._lbl_stats.setText("事件 " + " | ".join(parts) + pending)

    # ── 详情渲染 ──
    def _on_row_clicked(self, row: int, _col: int) -> None:
        item = self._table.item(row, 0)
        if item is None:
            return
        event = item.data(Qt.UserRole)
        if isinstance(event, dict):
            self._detail.setHtml(self._render_detail(event))

    def _render_detail(self, ev: dict) -> str:
        kind = str(ev.get("kind", "?"))
        ts = time.strftime("%H:%M:%S", time.localtime(ev.get("ts", 0)))
        badge_color = _KIND_COLORS.get(kind, QColor("#333"))
        hexcolor = badge_color.name() if hasattr(badge_color, "name") else "#333"
        head = (
            f'<div style="margin-bottom:6px;">'
            f'<span style="color:{hexcolor};font-weight:bold;">'
            f'[ {_KIND_LABELS.get(kind, kind)} ]</span> '
            f'<b>{html.escape(str(ev.get("method", "-")))}</b> '
            f'{html.escape(str(ev.get("path", "")))} '
            f'<span style="color:#888;">req_id={ev.get("req_id")} {ts}</span>'
            f'</div>'
        )
        if kind == "gcs_request":
            return head + self._render_request(ev)
        if kind == "cloud_response":
            return head + self._render_response(ev)
        if kind == "proxy_error":
            return head + (
                f'<div style="background:#fff1f0;border:1px solid #ffa39e;'
                f'padding:6px;font-family:Consolas,monospace;">'
                f'{html.escape(str(ev.get("error", "")))}</div>'
            )
        if kind == "tampered_response":   # 预留篡改阶段
            return head + self._render_tampered(ev)
        return head

    @staticmethod
    def _kv_table(rows: list[tuple[str, str]]) -> str:
        trs = "".join(
            f'<tr><td style="color:#555;padding:2px 10px 2px 0;">{html.escape(k)}</td>'
            f'<td style="padding:2px 0;">{html.escape(v)}</td></tr>'
            for k, v in rows
        )
        return f'<table style="margin:4px 0;">{trs}</table>'

    def _render_request(self, ev: dict) -> str:
        parts = [self._kv_table([
            ("Authorization", "存在（值不展示）" if ev.get("auth") else "无"),
            ("X-DGCS-VERSION", str(ev.get("client_version") or "-")),
            ("Content-Type", str(ev.get("content_type") or "-")),
            ("Body 长度", f"{ev.get('body_len', 0)} B"),
        ])]
        if ev.get("json_body") is not None:
            parts.append('<div style="color:#555;">请求体 JSON：</div>')
            parts.append(syntax_highlight(ev["json_body"]))
        return "".join(parts)

    def _render_response(self, ev: dict) -> str:
        parts = [self._kv_table([
            ("状态码", str(ev.get("status", "-"))),
            ("Content-Type", str(ev.get("content_type") or "-")),
            ("Body 长度", f"{ev.get('body_len', 0)} B"),
        ])]
        parsed = ev.get("parsed")
        if parsed:
            rows = [("信封 code", str(parsed.get("envelope_code"))),
                    ("message", str(parsed.get("message"))),
                    ("data 条目数", str(parsed.get("item_count")))]
            for i, it in enumerate(parsed.get("items") or []):
                rows.append((f"条目[{i}] id={it.get('id')}",
                             f"title={it.get('title')!r} content_len="
                             f"{it.get('content_len')} url={it.get('url')!r}"))
            parts.append('<div style="color:#555;">promotion 深度解析：</div>')
            parts.append(self._kv_table(rows))
        if ev.get("json_body") is not None:
            parts.append('<div style="color:#555;">响应体 JSON：</div>')
            parts.append(syntax_highlight(ev["json_body"]))
        # 预留：篡改对比区（tampered 事件出现后由 _render_tampered 渲染）
        return "".join(parts)

    @staticmethod
    def _render_tampered(ev: dict) -> str:
        """预留篡改阶段：original → tampered 字段级高亮对比。"""
        original = ev.get("original")
        tampered = ev.get("tampered")
        if original is None or tampered is None:
            return "<i>事件缺少 original/tampered 数据（预留视图）</i>"
        return highlight_html(original, tampered)


# ═══════════════════════════════════════════════════════════════
# CloudProxyPanel — 复合面板（SimulationPanel API 兼容委托）
# ═══════════════════════════════════════════════════════════════
class CloudProxyPanel(QWidget):
    """云平台拦截 Tab（子 Tab 容器，v3.9）。

    ├── 子 Tab「云平台配置」 —— 原 CloudProxyPanel 页面
    │     （上=SimulationPanel(cloud) 控制，下=CloudMessageView 消息监视）
    └── 子 Tab「TCP 消息监控」 —— TcpMonitorPanel（GCS↔云平台 TCP/TLS，
          独立引擎，从 UDP 消息监控 Tab 迁出）

    对 IntegratedMainWindow 暴露 SimulationPanel 兼容 API（委托）：
      * get_senders / set_message_injector / shutdown → 转发控制面板；
      * get_fake_node_ips → 恒空（HTTP 代理非 UDP 假节点，不进 UDP 监控过滤）。
    """

    def __init__(self, config: SimConfig,
                 log_manager: Any,
                 status_setter: Callable[[str], None]) -> None:
        super().__init__()
        self.setObjectName("FC_CLOUD_PANEL")
        self._config = config

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # ── 子 Tab 容器 ──
        self._tabs = QTabWidget()
        self._tabs.setObjectName("FC_SUB_TABS")

        # 子 Tab 1: 云平台配置（原页面）
        config_page = QWidget()
        config_page.setObjectName("FC_CONFIG_PAGE")
        cp = QVBoxLayout(config_page)
        cp.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Vertical)
        splitter.setObjectName("FC_SPLIT_MAIN")
        self._sim_panel = SimulationPanel(config, log_manager, status_setter)
        self._sim_panel.setObjectName("FC_SIM_PANEL")
        splitter.addWidget(self._sim_panel)
        self._view = CloudMessageView()
        splitter.addWidget(self._view)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        cp.addWidget(splitter)
        self._tabs.addTab(config_page, "云平台配置")

        # 子 Tab 2: TCP 消息监控（gcs_app 数据源独立宿主）
        self._tcp_panel = TcpMonitorPanel()
        self._tabs.addTab(self._tcp_panel, "TCP 消息监控")

        root.addWidget(self._tabs)

        # 50ms 轮询事件（与 UDP 监控 _on_tick 同模式；仅配置页消息视图）
        self._poll_timer = QTimer(self)
        self._poll_timer.setObjectName("FC_TIMER_POLL")
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._on_poll)
        self._poll_timer.start()

    def _on_poll(self) -> None:
        try:
            self._view.drain_poll(self._sim_panel.get_senders())
        except Exception:
            pass

    # ── SimulationPanel 兼容委托 ──
    def get_fake_node_ips(self) -> list[str]:
        return []   # HTTP 代理非 UDP 假节点

    def get_senders(self) -> list[Any]:
        return self._sim_panel.get_senders()

    def set_message_injector(self, callback: Callable | None) -> None:
        # gateway 无 sock 属性 → _patch_transport_socket 自动跳过；
        # sender.set_msg_injector 为兼容占位（HTTP 走结构化事件）。
        self._sim_panel.set_message_injector(callback)

    def shutdown(self) -> None:
        self._poll_timer.stop()
        self._tcp_panel.shutdown()
        self._sim_panel.shutdown()
