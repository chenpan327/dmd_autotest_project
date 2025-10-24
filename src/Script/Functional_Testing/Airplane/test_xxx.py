# C:\workspace\code\dmd_autotest_project\src\Script\Functional_Testing\Airplane\test_xxx.py
import pytest
import logging

logger = logging.getLogger(__name__)


class TestAirplaneAT:
    """飞机AT指令测试类（稳定版）"""

    # 使用 fixture 实现前置操作（替代 setup_method）
    @pytest.fixture(autouse=True)
    def setup_before_test(self, protocol_handler):
        """每个测试方法执行前自动执行的前置操作"""
        logger.info(f"\n--- 准备执行测试（前置操作） ---")
        self.protocol_handler = protocol_handler  # 绑定到实例
        protocol_handler.clear_buffer()  # 清空缓冲区
        yield  # 分隔前置和清理
        # 这里可以放后置操作（替代 teardown_method）
        logger.info(f"--- 测试结束（清理操作） ---\n")
        protocol_handler.send_command("AT+READY", wait_response=False)

    def test_at_version(self):
        """测试版本指令（直接使用实例属性的 protocol_handler）"""
        response = self.protocol_handler.send_command("version", timeout=2)
        logger.info(response)
        assert response is not None, "版本指令无响应"