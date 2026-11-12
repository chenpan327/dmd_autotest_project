import os
import sys
import time

import pytest
from selenium.webdriver.chrome.options import Options
import allure

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.split(os.path.split(os.path.split(BASE_DIR)[0])[0])[0]

sys.path.append(BASE_DIR)
from selenium import webdriver
from src.Physical.WebBase.UIBase import UIBase, GifRecorder, root_path, log_manager


@pytest.fixture(scope="session", autouse=True)
def browser():
    """整个测试会话只启动一次浏览器"""
    print("\n=== 启动浏览器 ===")
    options = Options()

    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--force-device-scale-factor=1")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)

    driver.set_window_size(1920, 1080)

    yield driver
    print("\n=== 关闭浏览器 ===")
    driver.quit()


@pytest.fixture
def recorder(browser, request):
    gif_name = f"{request.node.name}.gif"
    gif_path = os.path.join(
        root_path,
        "file",
        "gif",
        gif_name
    )
    recorder = GifRecorder(
        browser,
        output=gif_path,
        fps=8
    )
    return recorder


@pytest.fixture(scope="session", autouse=True)
def login(browser):
    """整个测试会话只登录一次"""
    print("\n=== 登录系统 ===")
    runner = UIBase(browser)
    runner = runner.login()
    return runner


@pytest.fixture(autouse=True)
def auto_attach(request):
    """
    每个用例执行完自动截图 + 控制台日志
    """
    yield
    # 只处理类实例测试
    instance = getattr(request.node, "instance", None)
    if not instance:
        return

    uav = getattr(instance, "uav", None)
    if not uav:
        return

    safe_name = f"{uav.node_name.lower()}.png"
    uav.refresh()
    allure.attach.file(
        root_path + f"/file/picture/{safe_name}",
        name="执行结果",
        attachment_type=allure.attachment_type.PNG
    )


@pytest.fixture(autouse=True)
def test_setup_teardown(request: pytest.FixtureRequest, recorder):
    log_manager.logger.info(f"\n>>> 测试开始：{request.node.name}")
    recorder.start()

    yield
    recorder.stop()
    if os.path.exists(recorder.output):
        allure.attach.file(
            recorder.output,
            name="执行录像",
            attachment_type=allure.attachment_type.GIF
        )

    log_manager.logger.info(f">>> 测试结束：{request.node.name}")
    log_manager.attach_log_to_allure()
    time.sleep(0.5)
