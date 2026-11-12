"""
Radio 测试配置 — 从项目根目录 config.json 读取 Radio 设备参数。
"""

import pytest

from utils.common import get_project_root, load_config


# ============================================================================
# 路径 & 配置加载
# ============================================================================

_PROJECT_ROOT = get_project_root()


def _resolve_device_type(request) -> str:
    """机型一律以 --device_type 命令行选项为准（main.py 自动携带）；
    config.json 顶层 DeviceType 遗留键已移除，不做静默回退"""
    opt = request.config.getoption("--device_type", default="")
    if opt:
        return opt
    raise KeyError(
        "未指定机型：请通过 --device_type 显式传入（如 --device_type=Radio）；"
        "main.py 入口会自动携带该参数"
    )


# ============================================================================
# Session-scoped Radio 配置 fixture
# ============================================================================


@pytest.fixture(scope="session")
def radio_cfg(request) -> dict:
    """返回 config.json 中 ``Radio`` 段的全部配置，供所有测试用例使用。

    示例::

        def test_xxx(radio_cfg):
            port = radio_cfg["radio_serial_port"]
    """
    config = load_config(_PROJECT_ROOT)
    device_type = _resolve_device_type(request)
    section = config.get(device_type, {})
    if not section:
        pytest.fail(f"config.json 中未找到设备类型 '{device_type}' 的配置")
    return section
