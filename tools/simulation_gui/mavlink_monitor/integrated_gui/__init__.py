"""
集成仿真与监控控制面板
========================

统一的 Qt 控制面板，基于 ``QTabWidget`` 同时管理：

    Tab 0 —— UDP 消息监控（始终可用）
    Tab 1 —— 假飞机 (FakeAirplane)
    Tab 2 —— 假机巢 (FakeNest)
    Tab 3 —— 假电台 (FakeRadio)
    Tab 4 —— 剧本处理 (DramaProcessingPanel)

Tab 1-4 仅在假设备项目存在且导入成功时显示；
否则仅作为独立的 MAVLink UDP 监控上位机运行。

依赖
----
    pip install PySide6

运行
----
    python -m mavlink_monitor.integrated_gui
    python -m mavlink_monitor.integrated_gui --screen 1
    python -m mavlink_monitor.integrated_gui --pos 1920,0
    python -m mavlink_monitor.integrated_gui --list-screens
    DMD_GUI_SCREEN=1 DMD_GUI_POS=1920,0 python -m mavlink_monitor.integrated_gui

包结构
------
本包从单体 ``integrated_gui.py`` (3192 行) 拆分为 8 个模块:

    __init__.py      — 重新导出 + 入口 main()
    _env.py          — 路径设置 + 假设备模块条件导入
    _reflection.py   — AST 动态反射 (SourceInfo, _parse_source, ...)
    _types.py        — 类型检测 + 值转换 + 控件工厂
    _config.py       — SimConfig + _build_sim_configs + _SocketInterceptor
    _panels.py       — SimulationPanel (~800 行)
    _nested.py       — NestedDevicePanel (~400 行)
    _cloud_panel.py  — CloudProxyPanel / CloudMessageView (云平台拦截 Tab)
    _monitor.py      — FullUdpMonitorPanel (~550 行)
    _window.py       — 多显示器辅助 + IntegratedMainWindow

向后兼容: ``from integrated_gui import main`` 仍可用（通过重新导出）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# 路径设置
# ═══════════════════════════════════════════════════════════════
_SELF_DIR = Path(__file__).resolve().parent.parent  # mavlink_monitor/ package
_PROJECT_ROOT = _SELF_DIR.parent                     # project root
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# _env 最先导入：处理假设备模块引导
from ._env import HAS_FAKE_CLOUD, HAS_FAKE_MODULES, _FAKE_IMPORT_ERROR

# ── _config ──
from ._config import (
    SimConfig,
    _build_sim_configs,
    _SocketInterceptor,
)

# ── _cloud_panel ──
from ._cloud_panel import CloudMessageView, CloudProxyPanel

# ── _tcp_monitor ──
from ._tcp_monitor import TcpMonitorPanel

# ── _reflection ──
from ._reflection import (
    NestedDeviceMeta,
    SourceInfo,
    _parse_nested_devices_from_source,
    _parse_source,
    _parse_sphinx_params_from_docstring,
    _parse_supported_keywords_from_docstring,
)

# ── _types ──
from ._types import (
    _coerce,
    _detect_kind,
    _discover_add_params,
    _discover_update_methods,
    _make_input_widget,
    _parse_list,
)

# ── _panels ──
from ._panels import SimulationPanel

# ── _nested ──
from ._nested import NestedDevicePanel

# ── _monitor ──
from ._monitor import FullUdpMonitorPanel

# ── _window ──
from ._window import (
    IntegratedMainWindow,
    _ensure_on_screen,
    _format_screens,
    _parse_gui_launch_args,
    _pick_screen,
)

# ═══════════════════════════════════════════════════════════════
# 公共 API
# ═══════════════════════════════════════════════════════════════
__all__ = [
    # 类
    "SimConfig",
    "SimulationPanel",
    "NestedDevicePanel",
    "CloudProxyPanel",
    "CloudMessageView",
    "TcpMonitorPanel",
    "FullUdpMonitorPanel",
    "IntegratedMainWindow",
    # dataclass
    "SourceInfo",
    "NestedDeviceMeta",
    # 函数
    "main",
    "_build_sim_configs",
    "_coerce",
    "_detect_kind",
    "_make_input_widget",
    "_parse_source",
    "_parse_nested_devices_from_source",
    "_parse_list",
    "_discover_update_methods",
    "_discover_add_params",
    "_parse_supported_keywords_from_docstring",
    "_parse_sphinx_params_from_docstring",
    "_SocketInterceptor",
    "_parse_gui_launch_args",
    "_pick_screen",
    "_format_screens",
    "_ensure_on_screen",
    # 常量
    "HAS_FAKE_MODULES",
    "HAS_FAKE_CLOUD",
]


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════
def main() -> int:
    """主入口函数。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    screen_index, position, list_only = _parse_gui_launch_args(sys.argv[1:])
    if list_only:
        print(_format_screens())
        return 0

    win = IntegratedMainWindow(screen_index=screen_index, position=position)
    win.show()
    print(f"Integrated GUI started. HAS_FAKE_MODULES={HAS_FAKE_MODULES}", flush=True)
    return app.exec()
