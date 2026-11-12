#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest
import allure
import time
import socket

from src.Protocol.mavlink.fake_airplane import FakeAirplane
from src.Protocol.mavlink.parse_mavlink import MAVLink_message


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
class TestFakeAirplane:
    """假飞机功能测试 - 验证假飞机与地面站的交互"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, mavlink_version):
        """测试前置/后置操作"""
        self.mavlink_version = mavlink_version
        print("\n[TEST] ====== 初始化假飞机 ======")
        with allure.step("初始化假飞机"):
            self.fake_plane = FakeAirplane(mavlink_version=mavlink_version)
            print(f"[TEST] 假飞机: {self.fake_plane.local_ip}:{self.fake_plane.local_port}")
            print(f"[TEST] 地面站: {self.fake_plane.ground_station_ip}:{self.fake_plane.ground_station_port}")
            allure.attach(f"假飞机: {self.fake_plane.local_ip}:{self.fake_plane.local_port}", "假飞机信息")
            allure.attach(f"目标地面站: {self.fake_plane.ground_station_ip}:{self.fake_plane.ground_station_port}", "地面站信息")
        yield
        with allure.step("清理测试资源"):
            print("[TEST] ====== 清理资源 ======")
            self.fake_plane.close()
            allure.attach("资源已清理", "清理信息")

    @allure.feature("假飞机扩展状态功能")
    @allure.story("响应扩展状态请求")
    @allure.title("收到id=1扩展请求返回id=5和id=8")
    def test_04_recv_id1_extend_send_id5_id8(self):
        """需要真地面站发送 id=1 且 extend=1 请求，假飞机才响应返回 id=5 和 id=8"""
        print("\n[TEST] ====== 测试开始 ======")

        with allure.step("假飞机发送心跳"):
            print("[TEST] 步骤1: 发送心跳")
            heartbeat_count = 0
            gcs_ip = self.fake_plane.ground_station_ip
            for i in range(1):
                msg = MAVLink_message(msg_id=0, sys_id=1, comp_id=1, seq=i,
                                      version=self.mavlink_version,
                                      fields={'mavlink_version': 41})
                print(f"[TEST] 创建心跳消息: seq={i}, hex={msg.hex_data}")
                result = self.fake_plane.send(msg, addr=(gcs_ip, self.fake_plane.ground_station_port))
                print(f"[TEST] 发送结果: {result}")
                if result:
                    heartbeat_count += 1
                    allure.attach(f"第{i+1}次心跳发送成功", f"发送结果")
                # time.sleep(0.3)

        with allure.step("验证发送成功"):
            print(f"[TEST] 步骤2: 验证心跳发送 (count={heartbeat_count})")
            assert heartbeat_count >= 1, f"期望至少发送1次心跳，实际发送 {heartbeat_count} 次"
            allure.attach(f"假飞机成功发送 {heartbeat_count} 次心跳", "验证通过")

        with allure.step("假飞机等待真地面站发送识别信息请求 (id=3)"):
            print("[TEST] 步骤3: 等待地面站发送 id=3 请求 (timeout=30s)")
            start_time = time.time()
            timeout = 30.0
            received = None
            while time.time() - start_time < timeout:
                received, addr = self.fake_plane.receive()
                if received is not None:
                    print(f"[TEST] 收到消息: msg_id={received.msg_id}, from={addr}")
                    if received.msg_id == 3:
                        detail = _format_msg_detail(received)
                        print(f"[TEST] 收到 id=3 请求:")
                        print(detail)
                        allure.attach(detail, f"假飞机收到请求 {addr[0]}")
                        break
                    elif received.msg_id == 0:
                        print("[TEST] 收到心跳，继续等待 id=3")
                        continue
                time.sleep(0.1)
            elapsed = time.time() - start_time
            print(f"[TEST] 等待结束 (耗时 {elapsed:.1f}s)")

        with allure.step("验证假飞机收到id=3请求"):
            print(f"[TEST] 步骤4: 验证收到 id=3")
            assert received is not None, "假飞机未接收到真地面站的请求"
            assert received.msg_id == 3, f"期望 msg_id=3，实际收到 msg_id={received.msg_id}"
            allure.attach(f"收到 msg_id={received.msg_id}", "验证通过")

        with allure.step("假飞机发送id=2响应"):
            msg = MAVLink_message(
                msg_id=2,
                seq=28,
                sys_id=0,
                fields={'serial': "123", 'code': "123"}
            )
            print(f"[TEST] 创建身份消息: seq=28, hex={msg.hex_data}")
            result = self.fake_plane.send(msg, addr=(gcs_ip, self.fake_plane.ground_station_port))
            print(f"[TEST] 发送结果: {result}")
            time.sleep(0.3)

        with allure.step("假飞机等待真地面站发送 heartbeat_dmd 报文 (id=1, extend=1)"):
            print("[TEST] 步骤5: 等待地面站发送 id=1, extend=1 请求 (timeout=30s)")
            start_time = time.time()
            timeout = 30.0
            received = None
            while time.time() - start_time < timeout:
                received, addr = self.fake_plane.receive()
                if received is not None:
                    print(f"[TEST] 收到消息: msg_id={received.msg_id}, from={addr}")
                    if received.msg_id == 1:
                        detail = _format_msg_detail(received)
                        print(f"[TEST] 收到 id=1 请求:")
                        print(detail)
                        allure.attach(detail, f"假飞机收到请求 {addr[0]}")
                        break
                    elif received.msg_id == 0:
                        print("[TEST] 收到心跳，继续等待 id=1")
                        continue
                time.sleep(0.1)
            elapsed = time.time() - start_time
            print(f"[TEST] 等待结束 (耗时 {elapsed:.1f}s)")

        with allure.step("验证假飞机收到id=1请求"):
            print(f"[TEST] 步骤6: 验证收到 id=1")
            assert received is not None, "假飞机未接收到真地面站的请求"
            assert received.msg_id == 1, f"期望 msg_id=1，实际收到 msg_id={received.msg_id}"
            allure.attach(f"收到 msg_id={received.msg_id}", "验证通过")

        with allure.step("假飞机发送id=5响应"):
            print("[TEST] 步骤7: 发送 id=5 响应")
            msg = MAVLink_message(msg_id=5, sys_id=1, comp_id=1,
                                  version=self.mavlink_version,
                                  fields={
                                      'seq': 604054808,
                                      'sensor_health': 3583,
                                      'voltage_battery': 16277,
                                      'wifi_up': 74,
                                      'ssid': b'dmd',
                                      'voltage_battery_diff': 71,
                                      'voltage_battery_history_diff': 71,
                                      'bat_serial_prefix': b'V4S24101',
                                      'wind_speed_x': 1500,
                                      'wind_speed_y': 450,
                                      'bat_serial_suffix': b'',
                                      'time_need_reset': 1,
                                      'uav_speed_horz': 3,
                                  })
            print(f"[TEST] id=5 消息: hex={msg.hex_data}")
            result = self.fake_plane.send(msg, addr=(gcs_ip, self.fake_plane.ground_station_port))
            print(f"[TEST] id=5 发送结果: {result}")
            assert result is True, "发送id=5响应失败"
            allure.attach("id=5响应发送成功", "发送结果")

        with allure.step("假飞机发送id=8响应"):
            print("[TEST] 步骤8: 发送 id=8 响应")
            msg = MAVLink_message(
                msg_id=8,
                version=self.mavlink_version,
                seq=26, sys_id=0, comp_id=0,
                fields={
                    'roll': 0.011320189572870731,
                    'pitch': -0.025642892345786095,
                    'yaw': 1.037914752960205,
                    'battery_time': 0,
                    'temp_imu': 68.4949951171875,
                    'temp_baro': 59.6400032043457,
                    'temp_batt': 26.75,
                    'param_hash': 769842611,
                    'anchor_hash': 0,
                    'battery_capability': 1,
                    'battery_used_times': 109,
                    'voltage_battery_cell1': 4044,
                    'voltage_battery_cell2': 4089,
                    'voltage_battery_cell3': 4037,
                    'voltage_battery_cell4': 4108,
                    'flight_controller_version': b'n3.g.193',
                    'companion_version': b'o3.0.020',
                    'battery_version': b'\x00\x00\x00\x00\x00\x00\x00\x00',
                    'gps_version': b'UM8310\x00\x00',
                    'servo_ver': 1,
                    'tele_version': b'1012',
                    'bms_version': b'1014',
                    'rid_version': b'\x00\x00\x00\x00\x00\x00\x00\x00',
                    'gimbal_version': b'\x00\x00\x00\x00',
                }
            )
            print(f"[TEST] id=8 消息: hex={msg.hex_data}")
            result = self.fake_plane.send(msg, addr=(gcs_ip, self.fake_plane.ground_station_port))
            print(f"[TEST] id=8 发送结果: {result}")
            assert result is True, "发送id=8响应失败"
            allure.attach("id=8响应发送成功", "发送结果")

        print("[TEST] ====== 测试完成 ======\n")
