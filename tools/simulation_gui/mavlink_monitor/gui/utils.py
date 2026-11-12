"""共享 GUI 工具函数 — 时间格式化等。

所有可复用的纯函数集中于此模块，消除跨文件重复定义。
"""

from __future__ import annotations

from datetime import datetime


def fmt_rel(sec: float) -> str:
    """相对时间 → HH:MM:SS.ffffff"""
    h = int(sec) // 3600
    m = (int(sec) % 3600) // 60
    s = int(sec) % 60
    us = int((sec - int(sec)) * 1_000_000)
    return f"{h:02d}:{m:02d}:{s:02d}.{us:06d}"


def fmt_abs(ts: float) -> str:
    """绝对时间 → datetime.fromtimestamp → HH:MM:SS.ffffff"""
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S.%f")
