# 用于共享日志配置和全局fixtures
import logging
import pytest
from src.Protocol.Communication_Protocol import ProtocolHandler  # 导入协议处理类


# --------------------------
# 全局日志配置（所有测试共享）
# --------------------------
def setup_logging():
    """初始化日志配置"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    return logging.getLogger(__name__)


# 初始化日志（在conftest加载时执行）
logger = setup_logging()


# 可选：添加更多全局fixtures（如通用工具函数、配置参数等）
@pytest.fixture(scope="session")
def common_config():
    """共享的配置参数（如超时时间、指令前缀等）"""
    return {
        "default_timeout": 2,
        "at_prefix": "AT+",
        "success_flag": b"OK"
    }