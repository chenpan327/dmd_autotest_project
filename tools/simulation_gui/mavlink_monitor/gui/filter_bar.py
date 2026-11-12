"""过滤栏 — QWidget 过滤器"""

from __future__ import annotations
from typing import Callable
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QCheckBox, QSpinBox,
)

from mavlink_monitor.gui.widgets import _MultiSelectButton


# ═══════════════════════════════════════════════════════
# FilterBar — 顶部过滤栏
# ═══════════════════════════════════════════════════════
class FilterBar(QWidget):
    """顶部过滤栏。

    布局: [MsgID ▼] [SrcIP ▼] [DstIP ▼] [RelayIP ▼] [心跳] [识别] [☑ 启用过滤] [清除]  ····  [显示上限]
    """

    on_filter_change = Signal(dict)

    def __init__(self, on_filter_change: Callable | None = None):
        super().__init__()
        if on_filter_change:
            self.on_filter_change.connect(on_filter_change)
        self._setup()

    def _setup(self) -> None:
        ly = QHBoxLayout(self)
        ly.setContentsMargins(4, 2, 4, 2)
        ly.setSpacing(4)

        # ── 过滤标签（可由外部隐藏，统一使用 2×2 网格标签）──
        self._tag_label = QLabel("过滤")
        self._tag_label.setStyleSheet("color: #888; font-weight: bold; padding-right: 2px;")
        ly.addWidget(self._tag_label)

        # ── MsgID 多选 ──
        self._msgid_select = _MultiSelectButton("MsgID ▾")
        self._msgid_select.setFixedWidth(120)
        self._msgid_select.selection_changed.connect(self._notify)
        ly.addWidget(self._msgid_select)

        # ── SrcIP 多选 ──
        self._srcip_select = _MultiSelectButton("SrcIP ▾")
        self._srcip_select.setFixedWidth(110)
        self._srcip_select.selection_changed.connect(self._notify)
        ly.addWidget(self._srcip_select)

        # ── DstIP 多选 ──
        self._dstip_select = _MultiSelectButton("DstIP ▾")
        self._dstip_select.setFixedWidth(110)
        self._dstip_select.selection_changed.connect(self._notify)
        ly.addWidget(self._dstip_select)

        # ── RelayIP 多选 ──
        self._relayip_select = _MultiSelectButton("RelayIP ▾")
        self._relayip_select.setFixedWidth(110)
        self._relayip_select.selection_changed.connect(self._notify)
        ly.addWidget(self._relayip_select)

        # ── 快速识别 ──
        hb = QPushButton("心跳"); hb.setFixedWidth(44)
        hb.clicked.connect(lambda: self._preset("heartbeat"))
        ly.addWidget(hb)
        ib = QPushButton("识别"); ib.setFixedWidth(44)
        ib.clicked.connect(lambda: self._preset("identify"))
        ly.addWidget(ib)

        # ── 清除 + 启用过滤（默认关闭，紧挨在一起）──
        cl = QPushButton("清除"); cl.setFixedWidth(44)
        cl.clicked.connect(self._clear)
        ly.addWidget(cl)
        self._enabled = QCheckBox("启用过滤")
        self._enabled.toggled.connect(self._notify)
        ly.addWidget(self._enabled)

        # 注：显示上限已移至视图组，由 MainWindow 统一管理

    # ── 公开方法：更新可选列表 ──
    def set_msgid_options(self, options: dict[int, str]) -> None:
        """设置可选 MsgID 列表。options: {msg_id: msg_name}"""
        opts = {str(k): f"(ID{k:03d}) {v}" for k, v in options.items()}
        self._msgid_select.set_options(opts)

    def set_ip_options(self, ips: set[str]) -> None:
        """设置可选 IP 列表（同时更新 SrcIP 和 DstIP 下拉）。"""
        opts = {ip: ip for ip in sorted(ips)}
        self._srcip_select.set_options(opts)
        self._dstip_select.set_options(opts)

    def set_relayip_options(self, ips: set[str]) -> None:
        """设置可选真实目标 IP 列表（更新 RelayIP 下拉）。"""
        opts = {ip: ip for ip in sorted(ips) if ip}
        self._relayip_select.set_options(opts)

    # ── 信号 ──
    def _notify(self) -> None:
        self.on_filter_change.emit({
            "msgids":    self._msgid_select.selected_keys(),
            "src_ips":   self._srcip_select.selected_keys(),
            "dst_ips":   self._dstip_select.selected_keys(),
            "relay_ips": self._relayip_select.selected_keys(),
            "enabled":   self._enabled.isChecked(),
        })

    # ── 预置 / 清除 ──
    def _preset(self, p: str) -> None:
        self._msgid_select.clear_selection()
        self._srcip_select.clear_selection()
        self._dstip_select.clear_selection()
        self._relayip_select.clear_selection()
        opts = self._msgid_select._options
        if p == "heartbeat":
            if "0" in opts:
                self._msgid_select.set_selected_keys({"0"})
        elif p == "identify":
            keys = {"2", "3"} & set(opts.keys())
            self._msgid_select.set_selected_keys(keys)
        self._notify()

    def _clear(self) -> None:
        self._msgid_select.clear_selection()
        self._srcip_select.clear_selection()
        self._dstip_select.clear_selection()
        self._relayip_select.clear_selection()
        self._notify()
