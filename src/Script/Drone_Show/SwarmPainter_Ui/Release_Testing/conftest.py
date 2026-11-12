import json
import logging
import subprocess
import sys
from utils.web_cloud import load_config

import pytest
from airtest.core.api import *

APP_PATH = load_config().get("SwarmPainter_Ui", {}).get("app_path")


@pytest.fixture(scope="session", autouse=True)
def start_app():
    """会话级 fixture：启动 Windows App + 初始化 Airtest"""
    print("\n=== 启动 Windows 应用 ===")

    # 启动应用
    proc = subprocess.Popen(APP_PATH)

    # 初始化 Airtest：使用 Windows 桌面
    auto_setup(__file__, devices=["Windows:///"])

    # 等待窗口加载
    time.sleep(2)

    yield proc  # 这里产出进程对象，测试中需要也可以用

    print("\n=== 关闭 Windows 应用 ===")
    # 关闭
    proc.terminate()
    time.sleep(1)


def pytest_configure():
    logging.getLogger("airtest").setLevel(logging.WARNING)
