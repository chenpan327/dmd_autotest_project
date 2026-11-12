"""左侧面板 — Mavlink配置 + 网卡选择 + 统计"""

from __future__ import annotations
import os, re, glob, subprocess
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QLineEdit, QComboBox, QFileDialog,
)


# ═══════════════════════════════════════════════════════════════
# 网卡扫描（借鉴 fake_airplane.py 的 ipconfig 方案）
# ═══════════════════════════════════════════════════════════════
def _get_interfaces() -> list[str]:
    """通过 ipconfig 获取所有可用网卡名称。"""
    names: set[str] = set()

    try:
        r = subprocess.run(
            ["ipconfig"],
            capture_output=True, text=True, timeout=8,
        )
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                line_s = line.strip()
                if not line_s.endswith(":"):
                    continue
                m = re.search(r'适配器\s+(.+):\s*$', line_s)
                if m:
                    name = m.group(1).strip()
                    if name and len(name) > 1:
                        names.add(name)
                    continue
                m = re.search(r'adapter\s+(.+):\s*$', line_s, re.IGNORECASE)
                if m:
                    name = m.group(1).strip()
                    if name and len(name) > 1:
                        names.add(name)
    except Exception:
        pass

    if not names:
        try:
            from scapy.all import get_if_list
            for name in get_if_list():
                name = name.strip()
                if name:
                    names.add(name)
        except ImportError:
            pass

    if not names:
        return ["(无可用网卡)"]
    return sorted(names)


# ═══════════════════════════════════════════════════════════════
# 版本扫描
# ═══════════════════════════════════════════════════════════════
from mavlink_monitor.core.paths import get_mavlink_version_dir

_KNOWN_DIRS = [
    get_mavlink_version_dir,
    lambda: os.path.join(os.path.dirname(__file__), "..", "..", "..",
                         "..", "file", "mavlink_version"),
]

def _find_dir() -> str:
    for fn in _KNOWN_DIRS:
        try:
            d = fn()
            if os.path.isdir(d): return d
        except Exception: pass
    return ""

def _scan_versions(d: str) -> list[str]:
    if not d or not os.path.isdir(d): return []
    vs = []
    for p in glob.glob(os.path.join(d, "mavlink_config_v*.json")):
        m = re.search(r'mavlink_config_v(\d+)\.json', os.path.basename(p))
        if m: vs.append(f"v{m.group(1)}")
    return sorted(vs, key=lambda v: int(v[1:]))

def _resolve_paths(d: str, v: str) -> tuple[str, str]:
    v = v.strip().lower()
    if not v.startswith("v"): v = f"v{v}"
    cfg = os.path.join(d, f"mavlink_config_{v}.json")
    enu = os.path.join(d, f"mavlink_enums_{v}.json")
    return (cfg if os.path.isfile(cfg) else "",
            enu if os.path.isfile(enu) else "")


# ═══════════════════════════════════════════════════════════════
# LeftPanel
# ═══════════════════════════════════════════════════════════════
class LeftPanel(QWidget):
    """左侧面板：配置 + 网卡选择 + 统计。"""

    on_start_nic = Signal(str)
    on_stop_nic = Signal()
    on_config_changed = Signal(str, str, str)  # config_path, enums_path, version

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config_dir = _find_dir()
        self._version = ""
        self._config_ok = False
        self._enums_ok = False
        self._sniffing = False
        self._setup()
        # 注意：不在此处调用 _on_scan()，由外部 load_initial_config() 触发，
        # 确保信号连接就绪后再加载配置。

    def _setup(self) -> None:
        ly = QVBoxLayout(self)
        ly.setContentsMargins(4, 4, 4, 4)
        ly.setSpacing(4)

        self._build_config(ly)
        self._build_nic(ly)
        self._build_stats(ly)

    # ── 配置组（紧凑版）─────────────────────────────────────────
    def _build_config(self, parent: QVBoxLayout) -> None:
        g = QGroupBox("Mavlink配置")
        l = QVBoxLayout(g)
        l.setSpacing(3)

        # 单行：版本 + 扫描 + 浏览
        h = QHBoxLayout(); h.setSpacing(3)
        h.addWidget(QLabel("版本:"))
        self._ver_combo = QComboBox()
        self._ver_combo.setMinimumWidth(60)
        self._ver_combo.addItem("(扫描)")
        self._ver_combo.currentTextChanged.connect(self._on_version_changed)
        h.addWidget(self._ver_combo, 1)
        scan_btn = QPushButton("扫描")
        scan_btn.setFixedWidth(40); scan_btn.clicked.connect(self._on_scan)
        h.addWidget(scan_btn)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(24); browse_btn.setToolTip("选择配置目录")
        browse_btn.clicked.connect(self._browse_dir)
        h.addWidget(browse_btn)
        l.addLayout(h)

        # 状态
        self._cfg_status = QLabel("[OFF] 未加载")
        l.addWidget(self._cfg_status)

        parent.addWidget(g)

    def load_initial_config(self) -> None:
        """在信号连接就绪后调用，触发初始配置扫描。"""
        if self._config_dir:
            self._on_scan()

    def _on_scan(self) -> None:
        d = self._config_dir
        if not d or not os.path.isdir(d):
            d = _find_dir()
        if d:
            self._config_dir = d
        vs = _scan_versions(self._config_dir) if self._config_dir else []
        self._ver_combo.blockSignals(True)
        self._ver_combo.clear()
        if vs:
            self._ver_combo.addItems(vs)
            self._ver_combo.setCurrentIndex(len(vs) - 1)
        else:
            self._ver_combo.addItem("(未发现版本)")
        self._ver_combo.blockSignals(False)
        # 手动触发版本变更
        cur = self._ver_combo.currentText()
        if cur and "未发现" not in cur:
            self._on_version_changed(cur)

    def _on_version_changed(self, v: str) -> None:
        if not v or "未发现" in v or "扫描" in v:
            return
        self._version = v
        cfg, enu = _resolve_paths(self._config_dir, v)
        self._config_ok = bool(cfg)
        self._enums_ok = bool(enu)
        if self._config_ok and self._enums_ok:
            self._cfg_status.setText("[OK] Config + Enums 就绪")
        elif self._config_ok:
            self._cfg_status.setText("[--] 仅 Config 就绪")
        else:
            self._cfg_status.setText("[OFF] 未加载")
        self.on_config_changed.emit(cfg, enu, v)

    def _browse_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择 Config 目录")
        if d:
            self._config_dir = d
            self._on_scan()

    # ── 网卡嗅探组 ────────────────────────────────────────────
    def _build_nic(self, parent: QVBoxLayout) -> None:
        g = QGroupBox("网卡嗅探")
        l = QVBoxLayout(g)
        l.setSpacing(4)

        h = QHBoxLayout(); h.setSpacing(4)
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
        l.addLayout(h)

        h = QHBoxLayout(); h.setSpacing(4)
        self._nic_btn = QPushButton("▶ 开始嗅探")
        self._nic_btn.setMinimumHeight(30)
        self._nic_btn.clicked.connect(self._toggle_sniffing)
        h.addWidget(self._nic_btn)
        l.addLayout(h)

        self._nic_status = QLabel("● 未启动")
        l.addWidget(self._nic_status)

        parent.addWidget(g)

    def _refresh_nic_list(self) -> None:
        current = self._nic_combo.currentText()
        self._nic_combo.clear()
        ifaces = _get_interfaces()
        self._nic_combo.addItems(ifaces)
        if current and current in ifaces:
            self._nic_combo.setCurrentText(current)

    def _toggle_sniffing(self) -> None:
        if self._sniffing:
            self._sniffing = False
            self._nic_btn.setText("▶ 开始嗅探")
            self._nic_status.setText("● 已停止")
            self._nic_combo.setEnabled(True)
            self.on_stop_nic.emit()
        else:
            iface = self._nic_combo.currentText().strip()
            if not iface or "(无可用网卡)" in iface:
                return
            self._sniffing = True
            self._nic_btn.setText("⏹ 停止嗅探")
            self._nic_status.setText("● 嗅探中...")
            self._nic_combo.setEnabled(False)
            self.on_start_nic.emit(iface)

    def set_sniffing_stopped(self) -> None:
        self._sniffing = False
        self._nic_btn.setText("▶ 开始嗅探")
        self._nic_status.setText("● 已停止")
        self._nic_combo.setEnabled(True)

    # ── 统计组 ────────────────────────────────────────────────
    def _build_stats(self, parent: QVBoxLayout) -> None:
        g = QGroupBox("统计")
        l = QVBoxLayout(g)
        self._stat_total    = QLabel("MAVLink: 0")
        self._stat_rate     = QLabel("Rate: 0 msg/s")
        self._stat_err      = QLabel("Errors: 0  CRC Fail: 0")
        self._stat_nic      = QLabel("网卡捕获: 0 UDP 包")
        self._stat_radio    = QLabel("电台DAV: 0 消息")
        self._stat_buf      = QLabel("Buffer: 0 / 40960000")
        self._stat_uptime   = QLabel("Uptime: 00:00:00")
        for w in [self._stat_total, self._stat_rate, self._stat_err,
                   self._stat_nic,
                   self._stat_radio,
                   self._stat_buf, self._stat_uptime]:
            l.addWidget(w)
        parent.addWidget(g)

    def update_stats(self, total, rate, errors, crc_fail,
                     nic_packets, nic_mavlink, buf_used, buf_max, uptime,
                     radio_packets=0, radio_mavlink=0) -> None:
        self._stat_total.setText(f"MAVLink: {total}")
        self._stat_rate.setText(f"Rate: {rate:.0f} msg/s")
        self._stat_err.setText(f"Errors: {errors}  CRC Fail: {crc_fail}")
        self._stat_nic.setText(f"网卡捕获: {nic_packets} UDP 包  (MAVLink: {nic_mavlink})")
        self._stat_radio.setText(f"电台DAV: {radio_packets} 包  (消息: {radio_mavlink})")
        self._stat_buf.setText(f"Buffer: {buf_used} / {buf_max}")
        self._stat_uptime.setText(f"Uptime: {uptime}")

    def get_version(self) -> str:
        return self._version
