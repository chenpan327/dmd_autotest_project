"""统一路径解析 — 假设备项目 + MAVLink 版本配置路径。

消除跨模块硬编码绝对路径，优先级链：环境变量 → 相对路径推断 → 硬编码回退。

用法::

    from mavlink_monitor.core.paths import get_fake_project_path, has_fake_project
    if has_fake_project():
        sys.path.insert(0, get_fake_project_path())
"""

from __future__ import annotations

import os
import warnings


def get_fake_project_path() -> str:
    """获取假设备项目根目录路径。

    优先级：
    1. 环境变量 ``DMD_FAKE_PROJECT_PATH``
    2. 从本文件位置向上推断相对路径
    3. 硬编码回退路径（发出 FutureWarning）
    """
    # 1) 环境变量
    env_path = os.environ.get("DMD_FAKE_PROJECT_PATH", "").strip()
    if env_path and os.path.isdir(env_path):
        return os.path.normpath(env_path)

    # 2) 相对路径推断：paths.py → core → mavlink_monitor → simulation_gui → tools → dmd_autotest_project_ycl
    _here = os.path.dirname(os.path.abspath(__file__))       # .../simulation_gui/mavlink_monitor/core/
    _pkg_dir = os.path.dirname(_here)                         # .../simulation_gui/mavlink_monitor/
    _project_root = os.path.dirname(_pkg_dir)                  # .../simulation_gui/
    relative = os.path.normpath(os.path.join(
        _project_root, "..", ".."                              # 上 2 级到 dmd_autotest_project_ycl
    ))
    if os.path.isdir(relative):
        return relative

    # 3) 硬编码回退
    fallback = r"D:\Work\dmd_autotest_project_ycl"
    if os.path.isdir(fallback):
        warnings.warn(
            f"使用硬编码回退路径: {fallback}，建议设置 DMD_FAKE_PROJECT_PATH 环境变量",
            FutureWarning, stacklevel=2,
        )
        return fallback

    return ""


def has_fake_project() -> bool:
    """假设备项目是否可访问。"""
    p = get_fake_project_path()
    return bool(p) and os.path.isdir(p)


def get_fake_mavlink_dir() -> str:
    """假设备项目中的 mavlink 子目录路径。"""
    fp = get_fake_project_path()
    if not fp:
        return ""
    d = os.path.join(fp, "src", "Protocol", "mavlink")
    return d if os.path.isdir(d) else ""


def get_mavlink_version_dir() -> str:
    """MAVLink 版本配置目录（file/mavlink_version）。"""
    fp = get_fake_project_path()
    if not fp:
        return ""
    d = os.path.join(fp, "file", "mavlink_version")
    return d if os.path.isdir(d) else ""


def get_radio_message_xml() -> str:
    """电台协议消息定义 XML 路径（src/Protocol/radio/MessageDefineUAV.xml）。

    该文件是 R2 电台 DAV 消息的权威协议定义（69 条），
    作为假电台消息配置的主要输入源。
    """
    fp = get_fake_project_path()
    if not fp:
        return ""
    d = os.path.join(fp, "src", "Protocol", "radio", "MessageDefineUAV.xml")
    return d if os.path.isfile(d) else ""
