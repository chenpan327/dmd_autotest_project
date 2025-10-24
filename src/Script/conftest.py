import pytest
from src.Protocol.Communication_Protocol import ProtocolHandler


@pytest.fixture(scope="module")  # 模块级别的 fixture，整个模块只初始化一次
def serial_protocol():
    """创建并返回一个已连接的 ProtocolHandler 实例，自动管理连接生命周期"""
    # 初始化协议处理器（可根据需要指定 port，默认自动选择）
    protocol = ProtocolHandler(baudrate=115200)
    # 连接串口
    connected = protocol.connect()
    if not connected:
        pytest.fail("串口连接失败，无法执行测试")  # 连接失败则标记测试失败
    yield protocol  # 提供实例给测试用例
    # 测试结束后自动断开连接（fixture 的 teardown 逻辑）
    protocol.disconnect()