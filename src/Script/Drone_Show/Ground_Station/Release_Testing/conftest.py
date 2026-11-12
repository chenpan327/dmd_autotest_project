# -*- coding: utf-8 -*-
"""
conftest.py

pytest 共享配置与 fixture：
- 路径与配置加载
- 注册自定义命令行参数（应用路径、登录凭据、测试数据等）
- 提供 session/class 级别 fixture 管理 DGCS 应用生命周期
- 提供 module/function 级别 fixture 供业务测试复用
"""

import sys
import os
import time
from datetime import datetime
from functools import lru_cache
from src.Protocol.mavlink.extract_mavlink_config_DGCS import extract_mavlink_config_DGCS
from utils.screen_recorder import ScreenRecorder

import pytest

from utils.logger import LogManager
from utils.common import get_project_root, load_config


project_root = get_project_root()
sys.path.insert(0, project_root)
    

# ============================================================================
# DGCS Mavlink版本配置加载
# ============================================================================
def check_DGCS_Mavlink_Version():
    """从 config.json 加载DGCS与Mavlink配置"""
    config_path = os.path.join(project_root, 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            dgcs_mavlink_version = config.get("Ground_Station", {}).get("version", "")
            mavlink_version = config.get("MavLink", {}).get("new-version", "")
            return extract_mavlink_config_DGCS(dgcs_mavlink_version, mavlink_version)
    except Exception as e:
        # log_manager.logger.error(f"加载配置文件失败：{e}")
        return False,None,None


# 加载全局配置
global_config = load_config(project_root)
timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
# dgcs_version_check, dgcs_mavlink_version, mavlink_version = check_DGCS_Mavlink_Version()
_GROUND_STATION = global_config.get("Ground_Station", {})


# ============================================================================
# pytest 命令行选项
# ============================================================================
def pytest_addoption(parser):
    parser.addoption(
        "--dgcs-app-path",
        action="store",
        default=_GROUND_STATION.get("app_path", ""),
        help="DGCS 应用可执行文件路径",
    )
    parser.addoption(
        "--dgcs-username",
        action="store",
        default=_GROUND_STATION.get("user_name", ""),
        help="DGCS 登录用户名",
    )
    parser.addoption(
        "--dgcs-password",
        action="store",
        default=_GROUND_STATION.get("login_passwd", ""),
        help="DGCS 登录密码",
    )
    parser.addoption(
        "--dgcs-drone-id",
        action="store",
        default="1952",
        help="测试用无人机 ID",
    )
    parser.addoption(
        "--dgcs-drama-file",
        action="store",
        default=_GROUND_STATION.get("drama3_file_path", ""),
        help="测试用剧本文件完整路径",
    )
    parser.addoption(
        "--dgcs-drama-id",
        action="store",
        default="1",
        help="测试用剧本 ID（用于映射）",
    )
    parser.addoption(
        "--skip-gui",
        action="store_true",
        default=False,
        help="跳过所有需要真实 GUI 的测试",
    )


# ============================================================================
# pytest 标记和钩子
# ============================================================================
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "gui: 标记需要启动真实 DGCS 应用并操作 UI 的测试"
    )
    config.addinivalue_line(
        "markers", "login: 标记需要先完成登录的测试"
    )
    config.addinivalue_line(
        "markers", "e2e: 标记端到端完整流程测试"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--skip-gui"):
        skip_gui = pytest.mark.skip(reason="--skip-gui 指定跳过 GUI 测试")
        for item in items:
            if "gui" in item.keywords:
                item.add_marker(skip_gui)


# ============================================================================
# 核心共享夹具 Fixture - 无人机数据
# ============================================================================
@pytest.fixture(scope="module")
def drama3_file_path():
    return global_config.get("Ground_Station", {}).get("drama3_file_path", "")


@pytest.fixture(scope="module")
def dat_file_path():
    return global_config.get("Ground_Station", {}).get("dat_file_path", "")


# ============================================================================
# DGCS 命令行参数 Fixture
# ============================================================================
@pytest.fixture(scope="session")
def dgcs_app_path(request):
    return request.config.getoption("--dgcs-app-path")


@pytest.fixture(scope="session")
def dgcs_username(request):
    return request.config.getoption("--dgcs-username")


@pytest.fixture(scope="session")
def dgcs_password(request):
    return request.config.getoption("--dgcs-password")


@pytest.fixture(scope="session")
def dgcs_drone_id(request):
    return request.config.getoption("--dgcs-drone-id")


@pytest.fixture(scope="session")
def dgcs_drama_file(request):
    path = request.config.getoption("--dgcs-drama-file")
    if path and not os.path.isabs(path):
        path = os.path.join(project_root, path)
    return path


@pytest.fixture(scope="session")
def dgcs_drama_id(request):
    return request.config.getoption("--dgcs-drama-id")

# ============================================================================
# DGCS 应用生命周期 Fixture
# ============================================================================
@pytest.fixture(scope="function")
def log_manager():
    # 测试前准备
    log_manager = LogManager(log_dir=f"logs\\TEST_LOG_{timestamp}")

    yield log_manager

    pass
    

# ============================================================================
# DGCS 应用生命周期 Fixture
# ============================================================================
@pytest.fixture(scope="class")
def dgcs_app(request, dgcs_app_path):
    """
    Class 级别 fixture：启动 DGCS 应用并返回 DgcsBusiness 实例。
    测试类结束后自动关闭应用。
    """
    pytest.importorskip("uiautomation", reason="需要安装 uiautomation 库")
    pytest.importorskip("psutil", reason="需要安装 psutil 库")

    from src.Protocol.dgcs.dgcs_business import DgcsBusiness

    business = DgcsBusiness(app_path=dgcs_app_path)
    started = business.start_app()
    if not started:
        pytest.skip(f"无法启动 DGCS 应用: {dgcs_app_path}")
    
    yield business

    # teardown：关闭应用
    try:
        business.close_app()
    except Exception as exc:
        # 终止进程作为兜底
        try:
            business.ui.terminate_process()
        except Exception:
            pass


@pytest.fixture(scope="class")
def dgcs_login(dgcs_app, dgcs_username, dgcs_password):
    """
    Class 级别 fixture：在已启动应用的基础上完成登录。
    同一测试类内的所有方法共享同一登录态，避免重复登录引发的状态错乱。
    若未提供用户名/密码，则跳过测试。
    """
    if not dgcs_username:
        pytest.skip("未提供 --dgcs-username，跳过登录相关测试")

    business = dgcs_app
    business.input_username(dgcs_username)
    if dgcs_password:
        business.input_password(dgcs_password)
    business.click_login()
    success = business.check_login_success(wait_time=10)
    if not success:
        pytest.skip("DGCS 登录失败，跳过登录后测试")

    # 登录后可能需要等待主窗口就绪并处理常见弹窗
    business.check_main_window_waiting(wait_time=3)
    business.check_battery_warming(wait_time=3)
    business.check_and_close_adjacent_project_warning(wait_time=3)

    yield business


# ============================================================================
# Fixture - 测试准备和清理
# ============================================================================
@pytest.fixture(autouse=True)
def test_setup_teardown(dgcs_app, log_manager, request: pytest.FixtureRequest):
    """
    自动执行的测试准备和清理 fixture

    作用域：function (每个测试函数执行前后都会调用)

    功能:
    1. 记录测试开始/结束日志
    2. 测试间添加短暂延迟，避免干扰

    Args:
        request: pytest 请求对象，用于获取测试节点信息
    """
    # 匹配多屏测试环境，获取地面站录制区域
    # dgcs_app_rect = dgcs_app.get_main_window().BoundingRectangle
    # dgcs_app_region = int(dgcs_app_rect.left), int(dgcs_app_rect.top), int(dgcs_app_rect.right), int(dgcs_app_rect.bottom)
    # 测试前开始录屏
    recorder = ScreenRecorder(fps=6, output_dir=f'logs\\DGCS_Screen_Recordings_{timestamp}')
    recorder.start()
    # recorder.start(region=dgcs_app_region)
    # 测试前准备
    log_manager.logger.info(f">>> 测试开始：{request.node.name}")
    # 短暂延迟，避免未录到屏
    time.sleep(0.2)

    yield

    # 测试后添加录屏附件
    recorder.stop(f"{request.node.name}.gif")
    gif_path = f"logs\\DGCS_Screen_Recordings_{timestamp}\\{request.node.name}.gif"
    recorder.attach_gif_to_allure(gif_path)
    # 测试后清理
    log_manager.logger.info(f">>> 测试结束：{request.node.name}")
    log_manager.attach_log_to_allure()

    # 短暂延迟，避免测试间干扰
    time.sleep(0.2)

