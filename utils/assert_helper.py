# -*- coding: utf-8 -*-
"""
assert_helper.py
提供断言辅助函数，用于记录断言信息到日志和 Allure 报告。
"""

import json

import allure
from utils.logger import log_manager


def log_assert_info(assert_name, **kwargs):
    """
    记录断言信息到日志和 Allure 报告。

    :param assert_name: 断言名称/描述
    :param kwargs: 键值对形式的断言信息
    """
    log_manager.logger.info(f"[断言检查] {assert_name}")
    for key, value in kwargs.items():
        log_manager.logger.info(f"  {key}: {value}")

    # 生成 Allure 附件
    attach_content = f"断言: {assert_name}\n"
    for key, value in kwargs.items():
        attach_content += f"{key}: {value}\n"

    allure.attach(
        attach_content,
        name=assert_name,
        attachment_type=allure.attachment_type.TEXT
    )


def _collect_false_keys(node, prefix=""):
    """递归收集 dict 中值为 False 的键路径 (嵌套 dict 深入展开)"""
    failed = []
    for key, value in node.items():
        path = f"{prefix}/{key}" if prefix else str(key)
        if value is False:
            failed.append(path)
        elif isinstance(value, dict):
            failed.extend(_collect_false_keys(value, path))
    return failed


def assert_feishu_rep(rep, point_label):
    """
    dmdtest_uart 测试点判定断言 (feishu_point 判定语义的 pytest 版)

    判定规则与原上位机 feishu_point 装饰器一致:
        rep 中任一值为 False 即该测试点失败 ("记录:" 前缀键为字符串/数值仅作记录);
        嵌套 dict (如四波特率 CPU 测量的 rep['波特率xxx']) 递归深入判定。
    完整判定明细以 JSON 附件挂到 Allure, 失败消息只携带失败项列表
    (控制台/Jenkins 日志保持精简, 关键数据看 Allure 附件)。

    :param rep: 测试点函数体写入的判定/记录字典
    :param point_label: 测试点标识 (如 "飞书行02 发送数据(1~buf遍历)")
    """
    allure.attach(
        json.dumps(rep, ensure_ascii=False, indent=2, default=str),
        name=f"{point_label}_判定明细",
        attachment_type=allure.attachment_type.JSON,
    )
    failed = _collect_false_keys(rep)
    assert not failed, (
        f"{point_label} 判定失败项: {failed}; "
        f"判定明细见 Allure 附件「{point_label}_判定明细」"
    )
