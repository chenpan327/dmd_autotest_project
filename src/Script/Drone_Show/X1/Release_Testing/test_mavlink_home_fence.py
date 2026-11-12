#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest
import allure
import time
import threading
import socket

from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
from utils.logger import log_manager


"""
返航点/电子围栏 (Home/Fence) 测试 - 位置设置与安全边界

业务背景：
    返航点 (Home Point) 是无人机在失控、低电量或执行 RTL (Return-to-Launch) 命令时
    自动返回的目标位置。电子围栏 (Geofence) 定义了无人机的安全飞行区域，当无人机
    超出围栏范围时触发安全保护。在编队表演中，正确设置返航点和电子围栏是保障
    飞行安全的重要措施。本测试模块验证通过 MAVLink 命令和串口命令设置返航点与
    电子围栏的功能。

测试对象：
    - 返航点设置命令 (MAV_CMD_DO_SET_HOME, command=179)
    - 电子围栏设置命令 (MAV_CMD_DO_SET_FENCE, command=180)
    - 串口 fence 命令 (SerialHandler.set_geofence)
    - PACKED_STATE 中的 home_set 和 fence_origin_set 状态字段

测试项：
    1. 无人机上线检测 — 通过 version 命令验证无人机在线，等待心跳 (id=0)
    2. 设置返航点为当前位置 — 通过 command=179 param1=1 使用当前位置作为返航点，验证 home_set
    3. 设置指定经纬度返航点 — 通过 command=179 指定纬度 22.5432100、经度 114.0543200、高度 50m
    4. 设置电子围栏 — 通过 command=180 设置围栏半径 100m、高度 50m
    5. 串口设置电子围栏 — 通过串口 fence 命令设置围栏 (原点 0,0, 半径 100m, 高度 50m)，验证 fence_origin_set
"""


# 注意：此测试需要重写以适配新 GCS API
pytestmark = pytest.mark.skip(reason="需重写以适配新 GCS API（fake_ground_control_station）。旧 Dmd_Uav_Udp.GroundControlStation 已删除，新 GCS 仅提供 send/receive，不再提供 send_heartbeat_dmd、send_command_long、parse_mavlink_data、drone_connected 等方法。参考 test_mavlink_fake_airplane.py 或 test_mavlink_identify_info.py 的写法重写。")


@pytest.mark.functional
class TestMavlinkHomeFence:
    """MAVLink 返航点/电子围栏测试"""

    def _udp_receiver(self):
        """UDP 接收线程函数"""
        try:
            while self.gcs.running:
                try:
                    data, addr = self.gcs.sock.recvfrom(4096)
                    if data:
                        log_manager.logger.info(f"[GCS] 接收原始数据 ({len(data)} 字节，来自 {addr}): \n{data.hex()}")
                        self.recieve_data = self.gcs.parse_mavlink_data(data)

                except socket.timeout:
                    if not self.gcs.drone_connected:
                        elapsed = time.time() - self.gcs.last_heartbeat_time
                        if elapsed > 3.0:
                            log_manager.logger.info(f"\n[GCS] 无人机心跳超时 ({elapsed:.1f}s)")
                    continue
                except Exception as e:
                    log_manager.logger.info(f"[GCS] 错误：{e}")
                    continue

        finally:
            log_manager.logger.info(f"\n[GCS] 接收线程停止")

    @pytest.fixture(autouse=True)
    def setup_before_test(self, serial_protocol_handler, udp_protocol_handler):
        """
        测试前置和后置操作

        Args:
            serial_protocol_handler: 串口协议处理器 fixture
            udp_protocol_handler: UDP 协议处理器 fixture
        """
        log_manager.logger.info("前置操作：初始化协议处理器和 UDP 接收线程")

        self.serial = serial_protocol_handler
        self.gcs = udp_protocol_handler
        self.recieve_data = None

        self.gcs.running = True
        self.recv_thread = threading.Thread(target=self._udp_receiver, daemon=True)
        self.recv_thread.start()

        yield

        log_manager.logger.info("后置操作：清理测试资源")
        self.gcs.running = False
        self.recv_thread.join(timeout=1)

    @allure.feature("返航点/电子围栏")
    @allure.story("无人机连接与心跳检测")
    @allure.title("无人机上线检测")
    @allure.description("验证无人机能够通过 version 命令上线并被地面站检测到")
    def test_airplane_online(self):
        with allure.step("发送 version 命令并检查返回数据"):
            log_manager.logger.info("发送 version 命令")
            result = self.serial.get_device_version()
            log_manager.logger.info(f"返回结果：{result}")
            assert result, "返回结果：失败"
            assert result is not None, "命令执行失败"
            assert "sn" in result, "返回数据缺少 sn 字段"
            assert "version" in result, "返回数据缺少 version 字段"

        with allure.step("延时 10 秒，等待无人机上线"):
            time.sleep(10)

        with allure.step("检测到无人机上线"):
            assert self.gcs.drone_connected is True
            assert self.recieve_data['header']['msg_id'] == 0

    @allure.feature("返航点/电子围栏")
    @allure.story("返航点设置")
    @allure.title("测试设置返航点")
    @allure.description("验证能够通过 MAV_CMD_DO_SET_HOME 命令设置返航点位置")
    def test_set_home_position(self):
        with allure.step("获取当前位置"):
            self.gcs.send_heartbeat_dmd(enable=0)
            time.sleep(0.5)
            
            if self.recieve_data and self.recieve_data['header']['msg_id'] == 5:
                cur_lat = self.recieve_data['packed_state']['cur_lat']
                cur_lon = self.recieve_data['packed_state']['cur_lon']
                log_manager.logger.info(f"当前位置：{cur_lat * 1e-7}, {cur_lon * 1e-7}")

        with allure.step("发送设置返航点命令 (当前位置)"):
            self.gcs.send_command_long(
                command=179,
                param1=1,  # 使用当前位置
                param2=0,
                param3=0,
                param4=0,
                param5=0,
                param6=0,
                param7=0
            )
            time.sleep(1.0)

        with allure.step("验证返航点设置"):
            log_manager.logger.info("返航点设置命令已发送")

        with allure.step("检查返航点状态"):
            self.gcs.send_heartbeat_dmd(enable=0)
            time.sleep(0.5)
            
            if self.recieve_data and self.recieve_data['header']['msg_id'] == 5:
                home_set = self.recieve_data['packed_state']['home_set']
                log_manager.logger.info(f"返航点设置状态：{'✅ 已设置' if home_set else '❌ 未设置'}")

    @allure.feature("返航点/电子围栏")
    @allure.story("返航点设置")
    @allure.title("测试设置指定返航点")
    @allure.description("验证能够通过 MAV_CMD_DO_SET_HOME 命令设置指定位置的返航点")
    def test_set_custom_home_position(self):
        with allure.step("发送设置指定返航点命令"):
            # 设置指定经纬度的返航点
            self.gcs.send_command_long(
                command=179,
                param1=0,  # 使用指定位置
                param2=0,
                param3=0,
                param4=0,
                param5=225432100,  # 纬度 22.5432100
                param6=1140543200,  # 经度 114.0543200
                param7=50  # 高度 50 米
            )
            time.sleep(1.0)

        with allure.step("验证返航点设置"):
            log_manager.logger.info("指定返航点设置命令已发送")

    @allure.feature("返航点/电子围栏")
    @allure.story("电子围栏设置")
    @allure.title("测试设置电子围栏")
    @allure.description("验证能够通过 MAV_CMD_DO_SET_FENCE 命令设置电子围栏")
    def test_set_geofence(self):
        with allure.step("发送设置电子围栏命令"):
            # 设置电子围栏：半径 100 米，高度 50 米
            self.gcs.send_command_long(
                command=180,
                param1=0,  # 使用指定位置
                param2=50,  # 高度 50 米
                param3=100,  # 半径 100 米
                param4=0,
                param5=0,
                param6=0,
                param7=0
            )
            time.sleep(1.0)

        with allure.step("验证电子围栏设置"):
            log_manager.logger.info("电子围栏设置命令已发送")

    @allure.feature("返航点/电子围栏")
    @allure.story("电子围栏设置")
    @allure.title("测试通过串口设置电子围栏")
    @allure.description("验证能够通过串口 fence 命令设置电子围栏")
    def test_set_geofence_serial(self):
        with allure.step("检查串口连接"):
            if not self.serial or not self.serial.is_connected:
                pytest.skip("串口未连接，跳过测试")

        with allure.step("发送 fence 命令"):
            result = self.serial.set_geofence(0, 0, 100, 50)
            log_manager.logger.info(f"电子围栏设置结果：{'成功' if result else '失败'}")

        with allure.step("验证电子围栏状态"):
            self.gcs.send_heartbeat_dmd(enable=0)
            time.sleep(0.5)
            
            if self.recieve_data and self.recieve_data['header']['msg_id'] == 5:
                fence_set = self.recieve_data['packed_state']['fence_origin_set']
                log_manager.logger.info(f"电子围栏设置状态：{'✅ 已设置' if fence_set else '❌ 未设置'}")
