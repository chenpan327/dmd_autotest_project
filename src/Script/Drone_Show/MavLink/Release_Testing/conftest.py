# coding: utf-8
"""
MAVLink 配置对比测试配置文件
从 config.json 读取旧版本和新版本 MAVLink Python 文件路径，作为测试参数
"""

import os
import sys
import pytest
from utils.common import get_project_root, load_config


# ============================================================================
# 路径配置
# ============================================================================

project_root = get_project_root()
sys.path.insert(0, project_root)


def get_mavlink_version_paths():
    """
    从 config.json 获取 MAVLink 版本文件路径

    Returns:
        tuple: (old_version_path, new_version_path)
    """
    config = load_config()
    mavlink_config = config.get('MavLink', {})

    old_version = mavlink_config.get('old-version', '')
    new_version = mavlink_config.get('new-version', '')

    # 转换为绝对路径
    if old_version and not os.path.isabs(old_version):
        old_version = os.path.join(project_root, old_version)
    if new_version and not os.path.isabs(new_version):
        new_version = os.path.join(project_root, new_version)

    # 统一路径分隔符
    if old_version:
        old_version = os.path.normpath(old_version)
    if new_version:
        new_version = os.path.normpath(new_version)

    return old_version, new_version


# ============================================================================
# Pytest 命令行选项注册
# ============================================================================

def pytest_addoption(parser):
    """
    注册命令行选项，默认值从 config.json 读取

    如果命令行未指定 --old-version 或 --new-version，
    将自动使用 config.json 中 MavLink 配置的值。
    """
    old_version, new_version = get_mavlink_version_paths()

    parser.addoption(
        '--old-version',
        action='store',
        default=old_version,
        help=f'MAVLink 旧版本 Python 文件路径 (默认: {old_version})'
    )
    parser.addoption(
        '--new-version',
        action='store',
        default=new_version,
        help=f'MAVLink 新版本 Python 文件路径 (默认: {new_version})'
    )
