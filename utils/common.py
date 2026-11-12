# coding: utf-8
"""项目级共享工具函数，避免在各 conftest 中重复定义。"""

import json
import os


def get_project_root():
    """获取项目根目录（向上查找 requirements.txt 或 config.json）"""
    current = os.path.abspath(__file__)
    while current != os.path.dirname(current):
        if os.path.exists(os.path.join(current, 'requirements.txt')) or \
           os.path.exists(os.path.join(current, 'config.json')):
            return current
        current = os.path.dirname(current)
    return current


def load_config(project_root=None):
    """从 config.json 加载配置，失败时返回 {}"""
    if project_root is None:
        project_root = get_project_root()
    config_path = os.path.join(project_root, 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}
