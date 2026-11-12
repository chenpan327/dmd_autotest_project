"""多显示器辅助 + IntegratedMainWindow。

从 integrated_gui.py 拆分出来的独立模块。
依赖: ._config, ._panels, ._nested, ._monitor
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QScreen
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QStatusBar, QTabWidget,
    QVBoxLayout, QWidget,
)

from mavlink_monitor.gui.drama_processing import DramaProcessingPanel

from ._cloud_panel import CloudProxyPanel
from ._config import SimConfig, _build_sim_configs
from ._env import HAS_FAKE_CLOUD, HAS_FAKE_MODULES, LogManager
from ._monitor import FullUdpMonitorPanel
from ._panels import SimulationPanel

SIM_CONFIGS = _build_sim_configs() if (HAS_FAKE_MODULES or HAS_FAKE_CLOUD) else {}


# ═══════════════════════════════════════════════════════════════
# 多显示器辅助
# ═══════════════════════════════════════════════════════════════
def _parse_gui_launch_args(
    argv: list[str],
) -> tuple[int | None, tuple[int, int] | None, bool]:
    parser = argparse.ArgumentParser(
        prog="IntegratedGUI",
        description="集成仿真与监控控制台",
        add_help=True,
    )
    parser.add_argument("--screen", type=str, default=None,
                        help="0-based 屏幕索引")
    parser.add_argument("--pos", type=str, default=None,
                        help="窗口左上角 'X,Y'")
    parser.add_argument("--list-screens", action="store_true",
                        help="列出全部可用屏幕后退出")
    ns = parser.parse_known_args(argv)[0]

    screen_index: int | None = None
    for src in (ns.screen, os.environ.get("DMD_GUI_SCREEN", "").strip()):
        if not src:
            continue
        if src.lstrip("-").isdigit():
            screen_index = int(src)
            break
        print(f"[GUI] 忽略无法解析的 screen 索引 {src!r}")

    position: tuple[int, int] | None = None
    pos_src = ns.pos or os.environ.get("DMD_GUI_POS")
    if pos_src:
        try:
            x_str, y_str = pos_src.split(",", 1)
            position = (int(x_str.strip()), int(y_str.strip()))
        except ValueError:
            print(f"[GUI] 忽略无法解析的 --pos/DMD_GUI_POS={pos_src!r}")

    return screen_index, position, ns.list_screens


def _pick_screen(index: int | None) -> QScreen | None:
    screens = QApplication.screens()
    if not screens:
        return None
    if index is None or not (0 <= index < len(screens)):
        return QApplication.primaryScreen()
    return screens[index]


def _format_screens() -> str:
    screens = QApplication.screens()
    lines = [f"Available screens ({len(screens)}):"]
    primary = QApplication.primaryScreen()
    for i, s in enumerate(screens):
        geo = s.geometry()
        avail = s.availableGeometry()
        dpi = s.logicalDotsPerInch()
        role = "primary" if s is primary else "secondary"
        lines.append(
            f"  [{i}] {role:<9} name={s.name()!r:<24} "
            f"geometry={geo.x():>5},{geo.y():>5} {geo.width():>4}x{geo.height():<4} "
            f"available={avail.x():>5},{avail.y():>5} {avail.width():>4}x{avail.height():<4} "
            f"dpi={dpi:.1f}"
        )
    return "\n".join(lines)


def _ensure_on_screen(win: QWidget) -> bool:
    screens = QApplication.screens()
    if not screens:
        return False
    frame = win.frameGeometry()
    if any(s.geometry().intersects(frame) for s in screens):
        return False
    primary = QApplication.primaryScreen() or screens[0]
    avail = primary.availableGeometry()
    w = min(max(win.width(), 640), avail.width())
    h = min(max(win.height(), 480), avail.height())
    x = avail.x() + max(0, (avail.width() - w) // 2)
    y = avail.y() + max(0, (avail.height() - h) // 2)
    win.setGeometry(x, y, w, h)
    return True


# ═══════════════════════════════════════════════════════════════
# IntegratedMainWindow
# ═══════════════════════════════════════════════════════════════
class IntegratedMainWindow(QMainWindow):
    """集成仿真与 UDP 监控的统一控制面板。

    Tab 0 —— UDP 消息监控（始终存在）
    Tab 1-3 —— 假飞机 / 假机巢 / 假电台（仅当假模块可用时）
    """

    def __init__(
        self,
        screen_index: int | None = None,
        position: tuple[int, int] | None = None,
    ) -> None:
        super().__init__()
        self._has_fake = HAS_FAKE_MODULES
        title = "Integrated Simulation & Monitor Control Panel" if self._has_fake \
                else "MAVLink UDP Monitor (Standalone)"
        self.setWindowTitle(title)
        self.resize(1200, 900)
        self.setObjectName("INTEGRATED_MAIN_WINDOW")

        # ── LogManager ──
        if self._has_fake:
            self._log_manager = LogManager(log_dir="logs\\")
        else:
            self._log_manager = None

        # ── SIM_CONFIGS ──
        self._sim_configs: dict[str, SimConfig] = {}
        if self._has_fake or HAS_FAKE_CLOUD:
            self._sim_configs = _build_sim_configs()

        # ── 中心布局 ──
        central = QWidget()
        central.setObjectName("INTEGRATED_CENTRAL")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("INTEGRATED_TABS")
        root.addWidget(self._tabs)

        # ── 状态栏 ──
        sb = QStatusBar()
        sb.setObjectName("INTEGRATED_STATUS_BAR")
        self.setStatusBar(sb)

        # ── Tab 0: UDP 监控（始终存在） ──
        self._udp_panel = FullUdpMonitorPanel()
        self._udp_panel.setObjectName("INTEGRATED_TAB_UDP")
        self._tabs.addTab(self._udp_panel, "UDP 消息监控")

        # ── Tab 1-3: 假飞机 / 假机巢 / 假电台（仅在 HAS_FAKE_MODULES 时） ──
        self._panels: dict[str, SimulationPanel] = {}
        if self._has_fake:
            for key, cfg in self._sim_configs.items():
                if key == "cloud":
                    continue   # cloud 由 CloudProxyPanel 单独创建（见下）
                panel = SimulationPanel(
                    cfg, self._log_manager,
                    status_setter=sb.showMessage,
                )
                panel.setObjectName(f"INTEGRATED_TAB_{key.upper()}")
                # 将假节点收到的消息直接注入 UDP 监控
                panel.set_message_injector(
                    lambda d, sip, sp, dip, dp, p=panel:
                    self._udp_panel.inject_raw_message(d, sip, sp, dip, dp)
                )
                self._tabs.addTab(panel, cfg.label)
                self._panels[key] = panel

        # ── Tab 4: 云平台拦截（本仓库 fake_cloud，不依赖假项目可用） ──
        self._cloud_panel: CloudProxyPanel | None = None
        if HAS_FAKE_CLOUD and "cloud" in self._sim_configs:
            cloud_cfg = self._sim_configs["cloud"]
            self._cloud_panel = CloudProxyPanel(
                cloud_cfg, self._log_manager,
                status_setter=sb.showMessage,
            )
            self._cloud_panel.setObjectName("INTEGRATED_TAB_CLOUD")
            # UDP raw 注入对 HTTP 代理为兼容占位（消息走结构化事件视图）
            self._cloud_panel.set_message_injector(
                lambda d, sip, sp, dip, dp:
                self._udp_panel.inject_raw_message(d, sip, sp, dip, dp)
            )
            self._tabs.addTab(self._cloud_panel, cloud_cfg.label)
            self._panels["cloud"] = self._cloud_panel  # type: ignore[assignment]

            # ── Tab 4: 剧本处理（仅在假模块可用时） ──
            self._drama_panel = DramaProcessingPanel()
            self._drama_panel.setObjectName("INTEGRATED_TAB_DRAMA")
            self._tabs.addTab(self._drama_panel, "剧本处理")
        else:
            self._drama_panel = None

        # ── 定时收集假节点 IP ──
        if self._has_fake:
            self._fake_ip_timer = QTimer(self)
            self._fake_ip_timer.setInterval(2000)
            self._fake_ip_timer.timeout.connect(self._collect_and_push_fake_ips)
            self._fake_ip_timer.start()

        # ── 连接信号：刷新假节点 IP 按钮 ──
        self._udp_panel._btn_refresh_fake.clicked.connect(self._collect_and_push_fake_ips)

        # ── 多显示器 ──
        self._screen_index = screen_index
        self._requested_position = position
        self._apply_launch_geometry()

        sb.showMessage("就绪" if self._has_fake
                       else "独立模式 — 假设备项目不可用")

    def _apply_launch_geometry(self) -> None:
        target = _pick_screen(self._screen_index)
        if target is None:
            return
        self.setScreen(target)
        avail = target.availableGeometry()
        max_w = max(640, avail.width() - 24)
        max_h = max(480, avail.height() - 24)
        cur_w, cur_h = self.width(), self.height()
        if cur_w > max_w or cur_h > max_h:
            self.resize(min(cur_w, max_w), min(cur_h, max_h))
        if self._requested_position is not None:
            x, y = self._requested_position
            x = max(avail.x(), min(x, avail.x() + avail.width() - self.width()))
            y = max(avail.y(), min(y, avail.y() + avail.height() - self.height()))
            self.move(x, y)
        else:
            self.move(
                avail.x() + (avail.width() - self.width()) // 2,
                avail.y() + (avail.height() - self.height()) // 2,
            )

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, lambda: _ensure_on_screen(self))

    def _collect_and_push_fake_ips(self) -> None:
        """从所有 SimulationPanel 收集假节点 IP，推送到 UDP 监控面板。"""
        all_ips: list[str] = []
        for panel in self._panels.values():
            all_ips.extend(panel.get_fake_node_ips())
        self._udp_panel.set_fake_node_ips(all_ips)

    def closeEvent(self, event: QCloseEvent) -> None:
        # 关闭假设备面板
        for panel in self._panels.values():
            try:
                panel.shutdown()
            except Exception as e:
                print(f"[GUI] 关闭 Panel 异常: {e}")
        # 关闭 UDP 监控
        try:
            self._udp_panel.shutdown()
        except Exception as e:
            print(f"[GUI] 关闭 UDP 监控异常: {e}")
        super().closeEvent(event)
