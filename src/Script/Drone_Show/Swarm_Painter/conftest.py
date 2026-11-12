# coding: utf-8
"""
Swarm_Painter 共享 conftest.py

提供 DLL fixture 和路径解析，避免在每个测试文件中重复定义。
"""
import os
import sys
from pathlib import Path

import pytest

from utils.logger import log_manager

# ===================== 路径解析 =====================
def _resolve_dll_path() -> Path:
    """根据 conftest 位置向上回溯，解析 DLL 所在目录。"""
    current_file = Path(__file__).resolve()
    # conftest.py 位于 src/Script/Drone_Show/Swarm_Painter/
    # 需要向上 4 层到达项目根目录
    project_root = current_file
    while not (project_root / "config.json").exists():
        project_root = project_root.parent
        if project_root == project_root.parent:  # 到达根
            break
    return project_root / "Physical" / "App"


DLL_PATH = _resolve_dll_path()
log_manager.logger.info(f"[Swarm_Painter] DLL 路径: {DLL_PATH}")

# 注意：不在模块加载阶段检查 DLL 目录是否存在。
# 如果 Physical/App 未部署（如 Jenkins 台机），让依赖 DLL 的测试
# 在 dll fixture 中自然失败，而不依赖 DLL 的测试（如 drama_reader）可以正常执行。

# ===================== 模块导入 =====================
try:
    from src.Protocol.drama import DLL as dll_module
except ImportError as _import_err:
    log_manager.logger.warning(f"[Swarm_Painter] 相对导入失败，尝试直接导入: {_import_err}")
    _protocol_dir = Path(__file__).parents[2]
    sys.path.append(str(_protocol_dir))
    import DLL as dll_module

# ===================== 测试常量 =====================
DRONE_INFO_STR = """[
    {
        "name": "V3",
        "value": 21,
        "droneParams": [
            {"name": "horizonMaxSpeed", "value": "8", "state": "0"},
            {"name": "verticalUpMaxSpeed", "value": "5", "state": "0"},
            {"name": "safeDis", "value": "1.9", "state": "0"}
        ]
    }
]"""


# ===================== Pytest Fixtures =====================
@pytest.fixture(scope="module")
def dll():
    """
    模块级 DLL fixture

    自动初始化 DLL 实例并完成授权，所有测试文件共享。
    如果 Physical/App 目录或 dmd_algorithm.dll 不存在，直接报错。
    """
    if not DLL_PATH.exists():
        raise FileNotFoundError(
            f"DLL 目录不存在: {DLL_PATH}\n"
            f"请将 dmd_algorithm.dll 及其依赖放入 Physical/App 目录。"
        )
    if not (DLL_PATH / "dmd_algorithm.dll").exists():
        raise FileNotFoundError(
            f"dmd_algorithm.dll 未找到: {DLL_PATH / 'dmd_algorithm.dll'}\n"
            f"请将 DLL 文件放入 Physical/App 目录。"
        )
    instance = dll_module.DLL(str(DLL_PATH))
    instance.set_user_drones_info(DRONE_INFO_STR)
    instance.set_user_authorize(True)
    yield instance
    instance.close()
