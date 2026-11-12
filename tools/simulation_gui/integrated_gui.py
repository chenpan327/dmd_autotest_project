"""integrated_gui 兼容重定向层。

原单体文件已拆分为 ``mavlink_monitor.integrated_gui`` 包（8 个模块）。
此文件保留用于向后兼容 ``from integrated_gui import ...`` 和 ``python integrated_gui.py``。
"""
from mavlink_monitor.integrated_gui import *  # noqa: F403, E402
from mavlink_monitor.integrated_gui import main  # noqa: E402

if __name__ == "__main__":
    import sys
    sys.exit(main())
