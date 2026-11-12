# coding: utf-8
"""
全局 conftest.py - 注册项目级 pytest 命令行参数

使所有测试目录都能识别 --device_type 和 --test_suites 参数
"""


def pytest_addoption(parser):
    """
    注册全局命令行选项
    """
    parser.addoption(
        "--device_type",
        action="store",
        default="",
        help="设备类型 (如: V4, Wifi_Module, Swarm_Painter, Cloud_Platform_Api 等)"
    )
    parser.addoption(
        "--test_suites",
        action="store",
        default="",
        help="测试套件 (如: Release_Testing, Functional_Testing 等)"
    )
    parser.addoption(
        "--mavlink_version",
        action="store",
        default="41",
        help="MAVLink 协议版本号 (如: 32, 37, 39, 41)"
    )
