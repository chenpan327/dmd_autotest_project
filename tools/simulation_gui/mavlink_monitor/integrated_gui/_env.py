"""共享环境：路径设置 + 假设备模块条件导入。

从 integrated_gui.py 拆分出来，供所有子模块安全导入（无循环依赖）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# 路径设置
# ═══════════════════════════════════════════════════════════════
_SELF_DIR = Path(__file__).resolve().parent.parent  # integrated_gui/.. = mavlink_monitor/
if str(_SELF_DIR) not in sys.path:
    sys.path.insert(0, str(_SELF_DIR))

from mavlink_monitor.core.paths import get_fake_project_path, get_fake_mavlink_dir, has_fake_project

_FAKE_PROJECT = get_fake_project_path()
_HAS_FAKE_PROJECT = has_fake_project()
_FAKE_MAVLINK_DIR = get_fake_mavlink_dir()
if _HAS_FAKE_PROJECT:
    for _p in (_FAKE_PROJECT, _FAKE_MAVLINK_DIR):
        if _p and _p not in sys.path:
            sys.path.insert(0, _p)


# ═══════════════════════════════════════════════════════════════
# 尝试导入假设备模块（可能不可用）
# ═══════════════════════════════════════════════════════════════
HAS_FAKE_MODULES: bool = False
_FAKE_IMPORT_ERROR: str = ""

if _HAS_FAKE_PROJECT:
    try:
        from fake_airplane import (  # noqa: E402
            AIRPLANE_MODEL_SERIALS,
            FakeAirplane,
            _FakeAirplaneMessageSender,
            _FakeAirplaneMessageSenders,
        )
        from fake_nest import (  # noqa: E402
            FakeNest,
            NESTED_DEVICE_REGISTRY,
            _FakeNestSender,
            _FakeNestSenders,
        )
        from fake_radio import (  # noqa: E402
            FAKE_RADIO_IP,
            DGCS_IP,
            NETCARD_INTERFACE as RADIO_NETCARD_INTERFACE,
            SUB_DEVICE_R2_STATION,
            FakeR2RadioStation,
            _FakeRadioSender,
            _FakeRadioSenders,
        )
        from utils.logger import LogManager  # noqa: E402
        HAS_FAKE_MODULES = True
    except ImportError as e:
        _FAKE_IMPORT_ERROR = str(e)
        print(f"[integrated_gui] 假设备模块导入失败: {e}")
        print(f"[integrated_gui] 将以独立 UDP 监控模式运行")

# 当假模块不可用时提供 None 占位，避免 import 时报 NameError
if not HAS_FAKE_MODULES:
    AIRPLANE_MODEL_SERIALS: dict = {}          # type: ignore[no-redef]
    FakeAirplane: type | None = None           # type: ignore[no-redef]
    _FakeAirplaneMessageSender: type | None = None  # type: ignore[no-redef]
    _FakeAirplaneMessageSenders: type | None = None  # type: ignore[no-redef]
    FakeNest: type | None = None               # type: ignore[no-redef]
    NESTED_DEVICE_REGISTRY: dict = {}          # type: ignore[no-redef]
    _FakeNestSender: type | None = None        # type: ignore[no-redef]
    _FakeNestSenders: type | None = None       # type: ignore[no-redef]
    FAKE_RADIO_IP: str = "172.16.200.1"        # type: ignore[no-redef]
    DGCS_IP: str = "172.16.200.1"              # type: ignore[no-redef]
    RADIO_NETCARD_INTERFACE: str = ""           # type: ignore[no-redef]
    SUB_DEVICE_R2_STATION: type | None = None   # type: ignore[no-redef]
    FakeR2RadioStation: type | None = None      # type: ignore[no-redef]
    _FakeRadioSender: type | None = None        # type: ignore[no-redef]
    _FakeRadioSenders: type | None = None       # type: ignore[no-redef]
    LogManager: type | None = None              # type: ignore[no-redef]


# ═══════════════════════════════════════════════════════════════
# fake_cloud — 云平台透明反向代理（本仓库 simulation_gui/ 内，恒可用）
# ═══════════════════════════════════════════════════════════════
_SIM_GUI_DIR = Path(__file__).resolve().parents[2]   # simulation_gui/
if str(_SIM_GUI_DIR) not in sys.path:
    sys.path.insert(0, str(_SIM_GUI_DIR))

HAS_FAKE_CLOUD: bool = False
try:
    from fake_cloud import (  # noqa: E402
        DEFAULT_LISTEN_HOST,
        DEFAULT_LISTEN_PORT,
        DEFAULT_UPSTREAM_ORIGIN,
        FakeCloudGateway,
        _FakeCloudSender,
        _FakeCloudSenders,
    )
    HAS_FAKE_CLOUD = True
except ImportError as e:
    print(f"[integrated_gui] fake_cloud 模块导入失败: {e}")
    DEFAULT_LISTEN_HOST: str = "127.0.0.1"      # type: ignore[no-redef]
    DEFAULT_LISTEN_PORT: int = 8765              # type: ignore[no-redef]
    DEFAULT_UPSTREAM_ORIGIN: str = ""            # type: ignore[no-redef]
    FakeCloudGateway: type | None = None         # type: ignore[no-redef]
    _FakeCloudSender: type | None = None         # type: ignore[no-redef]
    _FakeCloudSenders: type | None = None        # type: ignore[no-redef]


# ═══════════════════════════════════════════════════════════════
# 假设备项目的路径引用
# ═══════════════════════════════════════════════════════════════
def _get_fake_source_dir() -> Path:
    """返回假设备源文件所在目录；不可用时返回当前目录。"""
    if _HAS_FAKE_PROJECT and _FAKE_MAVLINK_DIR:
        return Path(_FAKE_MAVLINK_DIR)
    return _SELF_DIR


_FAKE_SRC = _get_fake_source_dir()
