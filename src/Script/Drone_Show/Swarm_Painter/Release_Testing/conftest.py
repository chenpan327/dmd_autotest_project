# conftest.py
import sys

import pytest
from src.Protocol.drama.drone_show.drama_reader import DramaReader
import os
from functools import lru_cache
import time
from utils.logger import log_manager
from utils.common import get_project_root, load_config


project_root = get_project_root()
sys.path.insert(0, project_root)

# 加载全局配置
global_config = load_config(project_root)
data_file_path = global_config.get("Swarm_Painter", {}).get("file_name", "")

@lru_cache(maxsize=1)
def load_drama_data():
    """
    使用缓存加载数据，避免重复读取文件和实例化对象。
    返回解析后的数据字典或 None。
    """
    try:
        if not data_file_path:
            return None

        dr = DramaReader()
        parsed_data = dr.read(data_file_path)
        
        # 确保数据结构存在
        if "drama3" in parsed_data:
            return parsed_data
        return None
        
    except (json.JSONDecodeError, KeyError, IOError):
        return None

# ============================================================================
# 核心共享夹具 Fixture - 无人机数据
# ============================================================================
@pytest.fixture(scope="module")
def drama3():
    """提供 drama3 数据"""
    drama_data = load_drama_data()
    if drama_data is None:
        pytest.skip("无法加载 drama3 数据，跳过相关测试")
    return drama_data.get("drama3", {})

@pytest.fixture(scope="module")
def drones(drama3):
    """提供 drones 数据"""
    return drama3.get("drones", [])

# 将 drone_index_list 改为普通变量，便于在 parametrize 中使用
_drama_data = load_drama_data()
_drama3_data = _drama_data.get("drama3", {}) if _drama_data else {}
drone_index_list = list(range(len(_drama3_data.get("drones", [])))) if _drama3_data else []

# ============================================================================
# Fixture - 测试准备和清理
# ============================================================================

@pytest.fixture(autouse=True)
def test_setup_teardown(request: pytest.FixtureRequest):
    """
    自动执行的测试准备和清理 fixture

    作用域：function (每个测试函数执行前后都会调用)

    功能:
    1. 记录测试开始/结束日志
    2. 测试间添加短暂延迟，避免干扰

    Args:
        request: pytest 请求对象，用于获取测试节点信息
    """
    # 测试前准备
    log_manager.logger.info(f"\n>>> 测试开始：{request.node.name}")

    yield

    # 测试后清理
    log_manager.logger.info(f">>> 测试结束：{request.node.name}")

    # 短暂延迟，避免测试间干扰
    time.sleep(0.2)