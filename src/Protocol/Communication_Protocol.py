from src.Physical.Serial.Communication_Interface import SerialPort  # 导入父类
import time


class ProtocolHandler(SerialPort):
    """继承SerialPort类，封装协议相关的发送和接收逻辑"""

    def __init__(self, port=None, baudrate=115200, timeout=0.1):
        # 调用父类初始化方法
        super().__init__(port=port, baudrate=baudrate, timeout=timeout)

    def send_command(self, cmd, add_newline=True, wait_response=True, timeout=2):
        """
        封装发送指令的函数，支持发送指令并返回设备响应

        参数:
            cmd: 要发送的指令字符串（如"version"）
            add_newline: 是否自动添加换行符（\r\n，匹配SSCOM格式），默认True
            wait_response: 是否等待并返回设备响应，默认True
            timeout: 等待响应的超时时间（秒），默认2秒

        返回:
            若wait_response=True，返回设备响应（字节类型）；否则返回None
        """
        if not self.is_connected:
            print("Error: Serial port not connected. Call connect() first.")
            return None

        try:
            # 处理指令格式：自动添加\r\n（匹配SSCOM的默认行为）
            if add_newline and not cmd.endswith(('\r', '\n', '\r\n')):
                cmd += "\r\n"  # 确保设备能正确识别指令

            # 发送指令
            success = self.send_data(cmd)
            if not success:
                print(f"Failed to send command: {cmd}")
                return None

            print(f"Sent command: {cmd.strip()}")

            # 若需要等待响应
            if wait_response:
                # 清空历史缓冲区，避免干扰
                self.clear_buffer()
                # 等待设备响应（根据设备速度调整延迟）
                time.sleep(0.1)
                # 读取响应
                response = self.read_data(timeout=timeout)
                return response
            return None

        except Exception as e:
            print(f"Error in send_command: {str(e)}")
            return None