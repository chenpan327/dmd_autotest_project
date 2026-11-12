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
传感器校准 (Calibration) 测试 - 飞前传感器校准与偏移设置

业务背景：
    无人机在每次飞行表演前需要对加速度计、陀螺仪、磁力计等传感器进行校准，
    以确保飞行控制系统的姿态感知准确。传感器偏移设置用于修正安装误差或环境干扰
    导致的测量偏差。本测试模块验证通过 MAVLink 命令执行飞前校准、设置传感器偏移、
    以及传感器校准的完整流程。

测试对象：
    - 飞前校准命令 (MAV_CMD_PREFLIGHT_CALIBRATION, command=241)
    - 传感器偏移设置命令 (MAV_CMD_PREFLIGHT_SET_SENSOR_OFFSETS, command=242)
    - 传感器校准命令 (MAV_CMD_CALIB_SENSOR, command=40040)
    - 加速度计、陀螺仪、磁力计的校准参数

测试项：
    1. 无人机上线检测 — 通过 version 命令验证无人机在线，等待心跳 (id=0)
    2. 飞前校准 — 分别发送加速度计/陀螺仪/磁力计校准命令 (command=241)，通过 param 指定校准对象
    3. 传感器偏移设置 — 通过 command=242 设置加速度计/陀螺仪/磁力计的 X/Y/Z 轴偏移
    4. 传感器校准 — 通过 command=40040 启动加速度计/磁力计校准，等待校准完成后获取校准值
"""


# 注意：此测试需要重写以适配新 GCS API
pytestmark = pytest.mark.skip(reason="需重写以适配新 GCS API（fake_ground_control_station）。旧 Dmd_Uav_Udp.GroundControlStation 已删除，新 GCS 仅提供 send/receive，不再提供 send_heartbeat_dmd、send_command_long、parse_mavlink_data、drone_connected 等方法。参考 test_mavlink_fake_airplane.py 或 test_mavlink_identify_info.py 的写法重写。")


@pytest.mark.functional
class TestMavlinkCalibration:
    """MAVLink 校准测试"""

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

    @allure.feature("校准测试")
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

    @allure.feature("校准测试")
    @allure.story("飞前校准")
    @allure.title("测试飞前校准命令")
    @allure.description("验证能够通过 MAV_CMD_PREFLIGHT_CALIBRATION 命令执行飞前校准")
    def test_preflight_calibration(self):
        with allure.step("发送飞前校准命令 (加速度计)"):
            self.gcs.send_command_long(
                command=241,
                param1=0,  # 陀螺仪：不校准
                param2=0,  # 磁力计：不校准
                param3=0,  # 地面压力：不校准
                param4=0,  # 无线电：不校准
                param5=1,  # 加速度计：校准
                param6=0,  # 罗盘/电机干扰：不校准
                param7=0
            )
            time.sleep(1.0)
            log_manager.logger.info("加速度计校准命令已发送")

        with allure.step("发送飞前校准命令 (陀螺仪)"):
            self.gcs.send_command_long(
                command=241,
                param1=1,  # 陀螺仪：校准
                param2=0,
                param3=0,
                param4=0,
                param5=0,
                param6=0,
                param7=0
            )
            time.sleep(1.0)
            log_manager.logger.info("陀螺仪校准命令已发送")

        with allure.step("发送飞前校准命令 (磁力计)"):
            self.gcs.send_command_long(
                command=241,
                param1=0,
                param2=1,  # 磁力计：校准
                param3=0,
                param4=0,
                param5=0,
                param6=0,
                param7=0
            )
            time.sleep(1.0)
            log_manager.logger.info("磁力计校准命令已发送")

    @allure.feature("校准测试")
    @allure.story("传感器偏移设置")
    @allure.title("测试传感器偏移设置")
    @allure.description("验证能够通过 MAV_CMD_PREFLIGHT_SET_SENSOR_OFFSETS 命令设置传感器偏移")
    def test_set_sensor_offsets(self):
        with allure.step("发送加速度计偏移设置命令"):
            self.gcs.send_command_long(
                command=242,
                param1=1,  # 加速度计
                param2=0,  # X 轴偏移
                param3=0,  # Y 轴偏移
                param4=0,  # Z 轴偏移
                param5=0,
                param6=0,
                param7=0
            )
            time.sleep(1.0)
            log_manager.logger.info("加速度计偏移设置已发送")

        with allure.step("发送陀螺仪偏移设置命令"):
            self.gcs.send_command_long(
                command=242,
                param1=0,  # 陀螺仪
                param2=0,
                param3=0,
                param4=0,
                param5=0,
                param6=0,
                param7=0
            )
            time.sleep(1.0)
            log_manager.logger.info("陀螺仪偏移设置已发送")

        with allure.step("发送磁力计偏移设置命令"):
            self.gcs.send_command_long(
                command=242,
                param1=2,  # 磁力计
                param2=0,
                param3=0,
                param4=0,
                param5=0,
                param6=0,
                param7=0
            )
            time.sleep(1.0)
            log_manager.logger.info("磁力计偏移设置已发送")

    @allure.feature("校准测试")
    @allure.story("传感器校准")
    @allure.title("测试传感器校准命令")
    @allure.description("验证能够通过 MAV_CMD_CALIB_SENSOR 命令校准传感器")
    def test_calibrate_sensor(self):
        with allure.step("发送加速度计校准命令"):
            self.gcs.send_command_long(
                command=40040,
                param1=1,  # 加速度计
                param2=1,  # 开始校准
                param3=0,
                param4=0,
                param5=0,
                param6=0,
                param7=0
            )
            time.sleep(2.0)
            log_manager.logger.info("加速度计校准开始")

        with allure.step("等待校准完成"):
            time.sleep(5.0)

        with allure.step("发送磁力计校准命令"):
            self.gcs.send_command_long(
                command=40040,
                param1=2,  # 磁力计
                param2=1,  # 开始校准
                param3=0,
                param4=0,
                param5=0,
                param6=0,
                param7=0
            )
            time.sleep(2.0)
            log_manager.logger.info("磁力计校准开始")

        with allure.step("等待校准完成"):
            time.sleep(5.0)

        with allure.step("获取校准值"):
            self.gcs.send_command_long(
                command=40040,
                param1=1,  # 加速度计
                param2=3,  # 获取校准值
                param3=0,
                param4=0,
                param5=0,
                param6=0,
                param7=0
            )
            time.sleep(1.0)
            log_manager.logger.info("获取校准值命令已发送")
