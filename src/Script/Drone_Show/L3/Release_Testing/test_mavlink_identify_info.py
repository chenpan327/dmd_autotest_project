#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
身份信息 (Identify Info) 测试 - 设备识别信息获取

业务背景：
    在无人机编队表演中，地面站需要获取每架无人机的身份识别信息（如序列号、
    硬件版本、固件版本等），以便进行设备管理和编队配置。身份信息通过 UDP 请求-响应
    机制获取：地面站发送获取身份信息请求 (msg_id=3)，无人机返回身份信息响应 (msg_id=2)。
    本测试模块验证地面站能够正确发送请求并解析无人机返回的身份信息。

测试对象：
    - 身份信息请求报文 (msg_id=3, IDENTIFY_INFO_REQUEST)
    - 身份信息响应报文 (msg_id=2, IDENTIFY_INFO_RESPONSE)
    - GroundControlStation UDP 通信机制
    - 无人机发现机制 (通过心跳 msg_id=0 发现设备 IP)

测试项：
    1. 发送获取身份信息请求 — 通过 UDP 发送 msg_id=3 请求，验证收到 msg_id=2 响应，确认响应消息 ID 正确
"""

import pytest
import allure
import time
import socket

from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from utils.logger import log_manager




def _format_msg_detail(msg):
    """格式化消息详情"""
    import io
    import sys
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    msg.print()
    output = sys.stdout.getvalue()
    sys.stdout = old_stdout
    return output


@pytest.mark.functional
class TestIdentifyInfoFunction:
    """身份信息功能测试"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, drone_ip, drone_port, mavlink_version):
        """测试前置/后置操作"""
        self.mavlink_version = mavlink_version
        with allure.step("初始化地面站"):
            self.gcs = GroundControlStation(drone_ip=drone_ip, drone_port=drone_port)
            log_manager.log_and_attach(f"地面站初始化完成，本地地址: {self.gcs.local_ip}:{self.gcs.local_port}", "初始化信息")
        yield
        with allure.step("清理测试资源"):
            self.gcs.close()
            log_manager.log_and_attach("地面站已关闭", "清理信息")

    def _clear_recv_buffer(self):
        """清空接收缓冲区"""
        self.gcs.sock.settimeout(0.1)
        try:
            while True:
                data, addr = self.gcs.sock.recvfrom(4096)
                if not data:
                    break
        except socket.timeout:
            pass
        finally:
            self.gcs.sock.settimeout(self.gcs.recv_timeout)

    @allure.feature("身份信息")
    @allure.story("获取无人机身份信息")
    @allure.title("发送获取身份信息请求并验证返回")
    @allure.description("通过 UDP 发送获取身份信息请求，验证无人机返回的身份信息")
    def test_send_get_identify_info(self):
        """测试发送获取身份信息请求"""
        with allure.step("先发现无人机"):
            start = time.time()
            timeout = 5.0
            while time.time() - start < timeout:
                received, addr = self.gcs.receive()
                if received is not None and received.msg_id == 0:
                    log_manager.log_and_attach(f"发现无人机: {addr[0]}", "发现结果")
                    break
                time.sleep(0.1)

        with allure.step("清空接收缓冲区"):
            self._clear_recv_buffer()

        with allure.step("创建获取身份信息请求 (id=3)"):
            msg = MAVLink_message(msg_id=3, sys_id=1, comp_id=1, seq=0,
                                  version=self.mavlink_version,
                                  fields={'target_system': 1, 'target_component': 1})
            log_manager.log_and_attach(msg.hex_data, "发送数据十六进制")

        with allure.step("发送获取身份信息请求"):
            target_ip = list(self.gcs.discovered_drones)[0] if self.gcs.discovered_drones else self.gcs.drone_ip
            result = self.gcs.send(msg, addr=(target_ip, self.gcs.drone_port))
            assert result is True, "发送请求失败"
            log_manager.log_and_attach(f"发送至 {target_ip}:{self.gcs.drone_port}", "发送结果")

        with allure.step("等待无人机响应 (id=2)"):
            start_time = time.time()
            timeout = 5.0
            received = None
            while time.time() - start_time < timeout:
                received, addr = self.gcs.receive()
                if received is not None:
                    if received.msg_id == 2:
                        detail = _format_msg_detail(received)
                        log_manager.log_and_attach(detail, f"收到响应详情 {addr[0]}")
                        break
                    elif received.msg_id == 0:
                        # 忽略心跳，继续等待
                        continue
                time.sleep(0.1)

        with allure.step("验证响应消息"):
            assert received is not None, "未接收到响应"
            assert received.msg_id == 2, f"期望响应 msg_id=2，实际收到 msg_id={received.msg_id}"
            log_manager.log_and_attach(f"响应 msg_id={received.msg_id}", "验证通过")
