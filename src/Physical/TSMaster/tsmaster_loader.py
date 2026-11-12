# coding: utf-8
"""
TSMaster 运行时加载器

把 ``import TSMaster`` 变成显式的 pyd 加载：从 config.json（工程唯一真相源）解析
bin64 路径，注册表作 fallback。这样测试脚本能在工程统一虚拟环境 (.venv, Python 3.10.11)
下调用 TSMaster，无需依赖 TSMaster 自带的 Python 3.11.8。

TSMaster.pyd 使用稳定 ABI，已在 Python 3.10.11 下实测可加载（见根目录
TSMaster_Python_API.md 第 1 节）。加载逻辑对齐 TSMaster 官方包的 __init__.py。
"""
import importlib
import importlib.machinery
import importlib.util
import os
import sys

from utils.logger import logger
from utils.common import load_config


def get_tsmaster_config():
    """从 config.json 读取 TSMaster 仪器配置段（工程唯一真相源）。

    Returns:
        dict: TSMaster 配置，未配置时返回空 dict
    """
    try:
        return load_config().get("TSMaster", {})
    except Exception:
        return {}


def find_bin64_from_registry():
    """从注册表 HKCU\\Software\\TOSUN\\TSMaster 读取 bin64 路径（最后兜底）。

    Returns:
        str | None: bin64 目录路径，读取失败返回 None
    """
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\TOSUN\TSMaster")
        sdir, _ = winreg.QueryValueEx(key, "bin64")
        key.Close()
        return sdir
    except Exception as e:
        logger.warning(f"[TSMaster-Loader] 读取注册表 bin64 路径失败: {e}")
        return None


def load_tsmaster(bin64_path=None):
    """加载 TSMaster.pyd 并返回模块（幂等，缓存在 sys.modules["TSMaster"]）。

    bin64 路径解析优先级:
        1. bin64_path 显式参数
        2. config.json 的 TSMaster.bin64_path（单一真相源）
        3. 注册表（本机已安装 TSMaster）

    Args:
        bin64_path (str, optional): TSMaster 安装目录下的 bin64 目录。

    Returns:
        module: 加载后的 TSMaster 模块，暴露 app / com / test / RawCAN / CANSignal 等。

    Raises:
        FileNotFoundError: 未找到 TSMaster 运行时（未安装或路径未配置）
    """
    if "TSMaster" in sys.modules:
        return sys.modules["TSMaster"]

    if not bin64_path:
        bin64_path = get_tsmaster_config().get("bin64_path")

    if not bin64_path:
        bin64_path = find_bin64_from_registry()

    if not bin64_path:
        raise FileNotFoundError(
            "未找到 TSMaster 运行时：请在 config.json 的 TSMaster.bin64_path 配置，"
            "或在本机安装 TOSUN TSMaster"
        )

    pyd_path = os.path.join(bin64_path, "TSMaster.pyd")
    if not os.path.exists(pyd_path):
        raise FileNotFoundError(f"未找到 TSMaster.pyd: {pyd_path}")

    # 让 TSMaster.pyd 的依赖 DLL（TSMaster.dll / libTSMaster.dll 等）可被解析
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(bin64_path)
        except OSError as e:
            logger.warning(f"[TSMaster-Loader] 添加 DLL 搜索目录失败: {e}")

    loader = importlib.machinery.ExtensionFileLoader("TSMaster", pyd_path)
    spec = importlib.util.spec_from_file_location(
        "TSMaster", pyd_path, loader=loader, submodule_search_locations=None
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules["TSMaster"] = package
    spec.loader.exec_module(package)

    logger.info(f"[TSMaster-Loader] TSMaster.pyd 加载成功: {pyd_path}")
    return package
