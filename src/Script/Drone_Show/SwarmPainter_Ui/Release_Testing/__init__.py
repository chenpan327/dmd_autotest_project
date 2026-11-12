# coding: utf-8
"""
Backward-compat shim — 工具函数已迁到 utils.airtest_report。

测试代码(test_create_drame.py 等)用 `from ...SwarmPainter_Ui.Release_Testing import *`
星式导入,本 __init__.py 改为 re-export,保持原 API 不变,无需改动测试文件。
"""
from utils.airtest_report import *  # noqa: F401,F403  backward-compat
from utils.airtest_report import (  # noqa: F401  显式 re-export 给 IDE
    copy_dir,
    rmdir,
    truncateFile,
    copy_result_html,
    init_setup,
    init_reportdir,
    modify_file,
    post_action,
)
