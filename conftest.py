import logging
import os
import subprocess
import time
from typing import Dict, Any
from src.Protocol.Communication_Protocol import ProtocolHandler  # 确保导入路径正确
import pytest


# --------------------------
# 1. 全局日志增强配置（保持不变，确保日志正常输出）
# --------------------------
@pytest.fixture(scope="session", autouse=True)
def setup_global_logging():
    """全局日志初始化（会话级，仅执行一次）"""
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)

    file_handler = logging.FileHandler(
        os.path.join(log_dir, "pytest_global.log"),
        encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))

    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)

    yield
    root_logger.removeHandler(file_handler)


# --------------------------
# 2. 全局配置参数（跨模块共享）
# --------------------------
@pytest.fixture(scope="session")
def global_config() -> Dict[str, Any]:
    return {
        "device_model": "Airplane-X1",
        "max_retry": 3,
        "common_timeout": 5,
        "serial_baudrate": 115200
    }


# --------------------------
# 3. 跨模块通用工具函数
# --------------------------
@pytest.fixture(scope="session")
def common_utils():
    class Utils:
        @staticmethod
        def hex_to_str(hex_data: bytes) -> str:
            return hex_data.hex(" ").upper()

        @staticmethod
        def str_to_hex(text: str) -> bytes:
            return bytes.fromhex(text.replace(" ", ""))

        @staticmethod
        def retry(func, max_retry: int = 3, delay: float = 1.0):
            def wrapper(*args, **kwargs):
                for i in range(max_retry):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        if i == max_retry - 1:
                            raise e
                        logging.warning(f"⚠️  第{i + 1}次重试：{str(e)}")  # 增加警告图标
                        time.sleep(delay)
            return wrapper
    return Utils()


# --------------------------
# 4. pytest 钩子函数（全局行为定制）
# --------------------------
def pytest_addoption(parser):
    parser.addoption(
        "--serial-port",
        action="store",
        default=None,
        help="指定串口端口（如 COM3 或 /dev/ttyUSB0）"
    )
    parser.addoption(
        "--device-model",
        action="store",
        default="Airplane-X1",
        help="指定设备型号（覆盖默认配置）"
    )


@pytest.fixture(scope="session")
def cli_options(request):
    return {
        "serial_port": request.config.getoption("--serial-port"),
        "device_model": request.config.getoption("--device-model")
    }


# --------------------------
# 5. 全局前置/清理（重点优化日志格式）
# --------------------------
@pytest.fixture(scope="session", autouse=True)
def session_setup_teardown():
    """会话级前置/清理（所有测试开始前和结束后执行）"""
    # 全局会话开始：用边框和图标突出显示
    logging.info("\n" + "="*60)
    logging.info("📝  === 全局测试会话开始 ===")
    logging.info(f"📅  启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info("="*60 + "\n")

    # 检查环境依赖
    allure_dir = os.path.join(os.path.dirname(__file__), "allure-results")
    os.makedirs(allure_dir, exist_ok=True)
    logging.info(f"✅  已确保 Allure 结果目录存在：{allure_dir}")

    yield

    # 全局会话结束：同样用边框突出
    logging.info("\n" + "="*60)
    logging.info("📝  === 全局测试会话结束 ===")
    logging.info(f"📅  结束时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info("="*60 + "\n")


# --------------------------
# 共享的fixtures（优化串口连接日志）
# --------------------------
@pytest.fixture(scope="module")
def protocol_handler():
    """模块级串口协议处理器 fixture"""
    # 初始化提示
    logging.info("\n" + "-"*50)
    logging.info("🔌  初始化串口协议处理器...")
    handler = ProtocolHandler(
        port=None,
        baudrate=115200,
        timeout=0.1
    )

    # 连接串口
    logging.info("🔗  尝试建立串口连接...")
    connected = handler.connect()
    if not connected:
        logging.error("❌  串口连接失败！")
        pytest.fail("串口连接失败，无法执行测试")
    logging.info("✅  串口连接成功！")
    logging.info("-"*50 + "\n")

    yield handler

    # 断开连接
    logging.info("\n" + "-"*50)
    logging.info("🔌  开始断开串口连接...")
    handler.disconnect()
    logging.info("✅  串口连接已断开")
    logging.info("-"*50 + "\n")


# --------------------------
# 断言失败时导出ADB日志的钩子函数（优化错误提示）
# --------------------------
def pytest_exception_interact(node, call, report):
    if isinstance(call.excinfo.value, AssertionError):
        test_script = os.path.basename(node.fspath)
        test_function = node.name
        error_msg = str(call.excinfo.value)

        # 错误信息用红色边框和错误图标突出
        logging.error("\n" + "*"*60)
        logging.error("❌  === 断言错误发生 ===")
        logging.error(f"📂  脚本路径: {node.fspath}")
        logging.error(f"🔍  测试函数: {test_function}")
        logging.error(f"💬  错误信息: {error_msg}")
        logging.error("*"*60 + "\n")

        # 日志目录准备
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        log_root = os.path.join(os.path.dirname(__file__), "logs")
        log_dir = os.path.join(log_root, f"{timestamp}_{test_script.replace('.py', '')}")
        os.makedirs(log_dir, exist_ok=True)
        logging.info(f"📁  准备导出日志至: {log_dir}")

        # ADB路径配置
        adb_path = os.path.join(
            os.path.dirname(__file__),
            "tools", "platform-tools-adb", "adb.exe"
        )
        if not os.path.exists(adb_path):
            logging.error(f"❌  ADB工具不存在: {adb_path}")
            return

        # 导出日志
        try:
            logcat_path = os.path.join(log_dir, "adb_logcat.log")
            with open(logcat_path, "w", encoding="utf-8", errors="ignore") as f:
                subprocess.run(
                    [adb_path, "logcat", "-d"],
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    check=True,
                    shell=True,
                    encoding="utf-8",
                    errors="ignore"
                )
            logging.info(f"✅  ADB logcat 已导出至: {logcat_path}")

            device_info_path = os.path.join(log_dir, "device_info.log")
            with open(device_info_path, "w", encoding="utf-8", errors="ignore") as f:
                subprocess.run([adb_path, "devices", "-l"], stdout=f, stderr=subprocess.STDOUT, shell=True, encoding="utf-8", errors="ignore")
                subprocess.run([adb_path, "shell", "getprop", "ro.build.version.release"], stdout=f, stderr=subprocess.STDOUT, shell=True, encoding="utf-8", errors="ignore")
            logging.info(f"✅  设备信息已导出至: {device_info_path}")

        except subprocess.CalledProcessError as e:
            logging.warning(f"⚠️  ADB命令执行失败: {str(e)}")
        except Exception as e:
            logging.warning(f"⚠️  日志导出失败: {str(e)}")