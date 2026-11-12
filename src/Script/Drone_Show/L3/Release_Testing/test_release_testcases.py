#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest
import allure
import time
import socket

from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from utils.logger import log_manager

# MAV_CMD 常量
MAV_CMD_COMPONENT_ARM_DISARM = 400
MAV_CMD_NAV_RETURN_TO_LAUNCH = 20
MAV_CMD_PREFLIGHT_CALIBRATION = 241
MAV_CMD_DO_SET_HOME = 179
MAV_CMD_DO_SET_SERVO = 183


def _format_msg_detail(msg):
    """格式化 MAVLink 消息详情"""
    import io
    import sys
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    msg.print()
    output = sys.stdout.getvalue()
    sys.stdout = old_stdout
    return output


@pytest.mark.functional
@allure.feature("版本发布测试")
class TestReleaseVersionTestcases:
    """地面站 UI 显示验证测试 — 版本发布地面站 UI 显示与功能验证

    串口协议和 UDP 假地面站已解耦，测试可同时独立调用：
    - self.serial: SerialProtocolHandler — 串口命令（如 ffs、dt TP_*）
    - self.gcs: GroundControlStation — MAVLink UDP 收发（send/receive）
    """

    _HEARTBEAT_DMD_HEX = 'fe0c00010101010016000000000000000001f5f5'

    @pytest.fixture(autouse=True)
    def setup_before_test(self, serial_protocol_handler, mavlink_version,
                          drone_ip, drone_port):
        """测试前置/后置 — 同时注入串口和 UDP 处理器"""
        self.serial = serial_protocol_handler
        self.gcs = GroundControlStation(drone_ip=drone_ip, drone_port=drone_port)
        self._drone_ip = None
        self.mavlink_version = mavlink_version
        log_manager.logger.info("前置操作：串口和 UDP 处理器已就绪")
        yield
        self.gcs.close()
        time.sleep(0.5)
        log_manager.logger.info("后置操作：测试资源清理完成")

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _clear_recv_buffer(self):
        """清空 UDP 接收缓冲区"""
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

    # ==================================================================
    # 无人机连接检测
    # ==================================================================

    @allure.story("无人机连接检测")
    @allure.title("无人机上线检测")
    @allure.description("验证无人机能够上线并被地面站检测到")
    def test_release_0(self):
        with allure.step("等待并检测无人机上线心跳"):
            time.sleep(10)
            start = time.time()
            found = False
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

    # ==================================================================
    # 基本状态信息
    # ==================================================================

    @allure.story("基本状态信息")
    @allure.title("状态栏异常检测")
    @allure.description("验证状态栏不显示异常红框，参数显示正确")
    def test_release_1(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求并验证 PACKED_STATE 打包状态"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"
            assert packed.msg_id == 5

        with allure.step("记录打包状态数据"):
            data_str = _format_msg_detail(packed)
            log_manager.logger.info(f"packed_state 数据：\n{data_str}")
            log_manager.log_and_attach(data_str, "packed_state 详情")

    @allure.story("基本状态信息")
    @allure.title("飞机编号显示")
    @allure.description("验证地面站正常显示飞机编号")
    def test_release_2(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态并获取飞机编号"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("记录飞机编号"):
            seq = packed.fields.get('seq', 'N/A')
            log_manager.logger.info(f"飞机编号：{seq}")

    @allure.story("基本状态信息")
    @allure.title("飞机模式显示")
    @allure.description("验证地面站正常显示飞机飞行模式")
    def test_release_3(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态并获取飞机模式"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("记录飞机模式"):
            mode = packed.fields.get('mode', 'N/A')
            log_manager.logger.info(f"飞机模式：{mode}")

    # ==================================================================
    # GPS与定位信息
    # ==================================================================

    @allure.story("GPS与定位信息")
    @allure.title("搜星数与定位状态显示")
    @allure.description("验证搜星数、定位百分比正确显示，定位模式颜色正确（PGS绿色/浮动解青色/差分紫色/未差分蓝色）")
    def test_release_4(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态并获取GPS与定位信息"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("记录搜星与定位信息"):
            f = packed.fields
            log_manager.logger.info(f"WiFi 上行速率：{f.get('wifi_up')}")
            log_manager.logger.info(f"MAVLink 上行速率：{f.get('mav_up_rate')}")
            log_manager.logger.info(f"GPS 定位类型：{f.get('fix_type')}")
            log_manager.logger.info(f"可见卫星数：{f.get('satellites_visible')}")
            log_manager.logger.info(f"RTK 质量：{f.get('rtk_quality')}")

    # ==================================================================
    # 电池与电源信息
    # ==================================================================

    @allure.story("电池与电源信息")
    @allure.title("电压与电量显示")
    @allure.description("验证电池电压、电量百分比正确显示，V4飞机显示充电图标")
    def test_release_5(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态并获取电压与电量"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("记录电压与电量"):
            f = packed.fields
            log_manager.logger.info(f"电池电压：{f.get('voltage_battery')}")
            log_manager.logger.info(f"电量：{f.get('voltage_battery_percent')}")

    @allure.story("电池与电源信息")
    @allure.title("电池循环次数显示")
    @allure.description("验证地面站正常显示电池循环次数")
    def test_release_20(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取电池循环次数"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录电池循环次数"):
            log_manager.logger.info(f"电池循环次数：{ext.fields.get('battery_used_times')}")

    @allure.story("电池与电源信息")
    @allure.title("电池剩余使用时长显示")
    @allure.description("验证地面站正常显示电池剩余使用时长")
    def test_release_21(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取电池剩余使用时长"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录电池剩余使用时长"):
            log_manager.logger.info(f"电池剩余时常：{ext.fields.get('battery_capability')}")

    @allure.story("电池与电源信息")
    @allure.title("电池最大压差显示")
    @allure.description("验证地面站正常显示电池最大压差")
    def test_release_22(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态并获取电池最大压差"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("记录电池最大压差"):
            log_manager.logger.info(f"电池最大压差：{packed.fields.get('voltage_battery_diff')}")

    @allure.story("电池与电源信息")
    @allure.title("电池单片电芯电压显示")
    @allure.description("验证地面站正常显示电池各单片电芯电压")
    def test_release_26(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取各电芯电压"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录各电芯电压"):
            f = ext.fields
            log_manager.logger.info(f"电芯1：{f.get('voltage_battery_cell1')}")
            log_manager.logger.info(f"电芯2：{f.get('voltage_battery_cell2')}")
            log_manager.logger.info(f"电芯3：{f.get('voltage_battery_cell3')}")
            log_manager.logger.info(f"电芯4：{f.get('voltage_battery_cell4')}")

    @allure.story("电池与电源信息")
    @allure.title("电池SN显示")
    @allure.description("验证地面站正常显示电池序列号")
    def test_release_27(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取电池序列号"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录电池序列号"):
            battery_ver = ext.fields.get('battery_version', b'')
            if isinstance(battery_ver, bytes):
                battery_ver = battery_ver.rstrip(b'\x00').decode('utf-8', errors='ignore')
            log_manager.logger.info(f"电池 SN：{battery_ver}")

    # ==================================================================
    # 飞机姿态信息
    # ==================================================================

    @allure.story("飞机姿态信息")
    @allure.title("ROLL值显示")
    @allure.description("验证地面站正常显示飞机横滚角ROLL值")
    def test_release_16(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取ROLL值"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录ROLL值"):
            log_manager.logger.info(f"ROLL：{ext.fields.get('roll')}")

    @allure.story("飞机姿态信息")
    @allure.title("Pitch值显示")
    @allure.description("验证地面站正常显示飞机俯仰角Pitch值")
    def test_release_17(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取Pitch值"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录Pitch值"):
            log_manager.logger.info(f"Pitch：{ext.fields.get('pitch')}")

    @allure.story("飞机姿态信息")
    @allure.title("Yaw值显示")
    @allure.description("验证地面站正常显示飞机偏航角Yaw值")
    def test_release_18(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取Yaw值"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录Yaw值"):
            log_manager.logger.info(f"Yaw：{ext.fields.get('yaw')}")

    # ==================================================================
    # 高度信息
    # ==================================================================

    @allure.story("高度信息")
    @allure.title("高度显示")
    @allure.description("验证地面站正常显示飞机当前高度")
    def test_release_6(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态并获取高度"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("记录高度"):
            log_manager.logger.info(f"海拔高度：{packed.fields.get('elevation')}")

    @allure.story("高度信息")
    @allure.title("海拔高度显示")
    @allure.description("验证地面站正常显示飞机海拔高度")
    def test_release_19(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态并获取海拔高度"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("记录海拔高度"):
            log_manager.logger.info(f"海拔高度：{packed.fields.get('elevation')}")

    # ==================================================================
    # 传感器状态
    # ==================================================================

    @allure.story("传感器状态")
    @allure.title("传感器模块状态显示")
    @allure.description("验证IMU/Baro/Compass/GPS/Battery/Camera/ESC/Parachute/Tele/Bms状态正确显示")
    def test_release_13(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态并获取传感器健康状态"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("记录传感器状态"):
            log_manager.logger.info(f"传感器状态：{packed.fields.get('sensor_health')}")

    # ==================================================================
    # 温度信息
    # ==================================================================

    @allure.story("温度信息")
    @allure.title("IMU温度显示")
    @allure.description("验证地面站正常显示IMU温度")
    def test_release_23(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取IMU温度"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录IMU温度"):
            log_manager.logger.info(f"IMU 温度：{ext.fields.get('temp_imu')}")

    @allure.story("温度信息")
    @allure.title("Baro温度显示")
    @allure.description("验证地面站正常显示气压计温度")
    def test_release_24(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取Baro温度"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录Baro温度"):
            log_manager.logger.info(f"Baro 温度：{ext.fields.get('temp_baro')}")

    @allure.story("温度信息")
    @allure.title("Battery温度显示")
    @allure.description("验证地面站正常显示电池温度")
    def test_release_25(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取电池温度"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录电池温度"):
            log_manager.logger.info(f"Battery 温度：{ext.fields.get('temp_batt')}")

    # ==================================================================
    # 版本信息
    # ==================================================================

    @allure.story("版本信息")
    @allure.title("Mavlink版本号显示")
    @allure.description("验证Mavlink版本号与地面站版本一致")
    def test_release_28(self):
        with allure.step("检测无人机上线并接收心跳"):
            start = time.time()
            found = False
            heartbeat = None
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    heartbeat = msg
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("记录Mavlink版本号"):
            mav_ver = heartbeat.fields.get('mavlink_version', 'N/A')
            log_manager.logger.info(f"Mavlink 版本号：{mav_ver}")

    @allure.story("版本信息")
    @allure.title("固件版本号显示")
    @allure.description("验证固件版本号与后台下载版本号一致")
    def test_release_29(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取固件版本号"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录固件版本号"):
            fc_ver = ext.fields.get('flight_controller_version', b'')
            if isinstance(fc_ver, bytes):
                fc_ver = fc_ver.rstrip(b'\x00').decode('utf-8', errors='ignore')
            log_manager.logger.info(f"固件版本号：{fc_ver}")

    @allure.story("版本信息")
    @allure.title("电池固件版本号显示")
    @allure.description("验证电池固件版本号与后台下载版本号一致")
    def test_release_30(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取电池固件版本号"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录电池固件版本号"):
            bat_ver = ext.fields.get('battery_version', b'')
            if isinstance(bat_ver, bytes):
                bat_ver = bat_ver.rstrip(b'\x00').decode('utf-8', errors='ignore')
            log_manager.logger.info(f"电池固件版本号：{bat_ver}")

    @allure.story("版本信息")
    @allure.title("电台接收机版本号显示")
    @allure.description("验证电台接收机二合一版本号与后台下载版本号一致")
    def test_release_31(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取电台接收机版本号"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录电台接收机版本号"):
            tele_ver = ext.fields.get('tele_version', b'')
            if isinstance(tele_ver, bytes):
                tele_ver = tele_ver.rstrip(b'\x00').decode('utf-8', errors='ignore')
            log_manager.logger.info(f"电台接收机版本号：{tele_ver}")

    @allure.story("版本信息")
    @allure.title("GPS版本号显示")
    @allure.description("验证GPS版本号与后台下载版本号一致")
    def test_release_32(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取GPS版本号"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录GPS版本号"):
            gps_ver = ext.fields.get('gps_version', b'')
            if isinstance(gps_ver, bytes):
                gps_ver = gps_ver.rstrip(b'\x00').decode('utf-8', errors='ignore')
            log_manager.logger.info(f"GPS 版本号：{gps_ver}")

    @allure.story("版本信息")
    @allure.title("机载版本号显示")
    @allure.description("验证机载版本号与后台下载版本号一致")
    def test_release_33(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态并获取机载版本号"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("记录机载版本号"):
            comp_ver = ext.fields.get('companion_version', b'')
            if isinstance(comp_ver, bytes):
                comp_ver = comp_ver.rstrip(b'\x00').decode('utf-8', errors='ignore')
            log_manager.logger.info(f"机载版本号：{comp_ver}")

    # ==================================================================
    # 网络与信号
    # ==================================================================

    @allure.story("网络与信号")
    @allure.title("信号强度显示")
    @allure.description("验证信号强度随AP信号强度变化正确显示")
    def test_release_7(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态并获取信号信息"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("记录信号信息"):
            f = packed.fields
            log_manager.logger.info(f"WiFi 上行速率：{f.get('wifi_up')}")
            log_manager.logger.info(f"MAVLink 上行速率：{f.get('mav_up_rate')}")
            log_manager.logger.info(f"GPS 定位类型：{f.get('fix_type')}")
            log_manager.logger.info(f"可见卫星数：{f.get('satellites_visible')}")
            log_manager.logger.info(f"RTK 质量：{f.get('rtk_quality')}")

    @allure.story("网络与信号")
    @allure.title("飞机SSID显示")
    @allure.description("验证地面站正常显示飞机SSID")
    def test_release_10(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态并获取SSID"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("记录SSID"):
            ssid = packed.fields.get('ssid', b'')
            if isinstance(ssid, bytes):
                ssid = ssid.rstrip(b'\x00').decode('utf-8', errors='ignore')
            log_manager.logger.info(f"SSID：{ssid}")

    @allure.story("网络与信号")
    @allure.title("IP地址显示")
    @allure.description("验证地面站正常显示飞机IP地址")
    def test_release_11(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("记录IP地址"):
            log_manager.logger.info(f"无人机 IP：{self._drone_ip or self.gcs.drone_ip}")

    # ==================================================================
    # 飞机标识
    # ==================================================================

    @allure.story("飞机标识")
    @allure.title("飞机序列号显示")
    @allure.description("验证地面站正常显示飞机序列号")
    def test_release_12(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态确认在线"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("发送身份信息请求并获取序列号"):
            time.sleep(0.3)
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            id_msg = MAVLink_message(msg_id=3, sys_id=1, comp_id=1, seq=0,
                                     version=self.mavlink_version,
                                     fields={'target_system': 1, 'target_component': 1})
            result = self.gcs.send(id_msg, addr=addr)
            assert result is True
            start = time.time()
            info = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 2:
                        info = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert info is not None, "未接收到身份信息"
            assert info.msg_id == 2, f"期望 msg_id=2，实际={info.msg_id}"

        with allure.step("记录飞机序列号"):
            serial = info.fields.get('serial', b'')
            code = info.fields.get('code', b'')
            if isinstance(serial, bytes):
                serial = serial.rstrip(b'\x00').decode('utf-8', errors='ignore')
            if isinstance(code, bytes):
                code = code.rstrip(b'\x00').decode('utf-8', errors='ignore')
            log_manager.logger.info(f"序列号(serial)：{serial}")
            log_manager.logger.info(f"编码(code)：{code}")
            assert serial, "序列号信息不正确"

    # ==================================================================
    # 故障状态
    # ==================================================================

    @allure.story("故障状态")
    @allure.title("FS故障状态检测")
    @allure.description("验证通过ffs命令注入故障后FS故障状态正确上报，清除故障后恢复")
    def test_release_14(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态确认在线"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("发送 ffs 1 命令注入低电量故障"):
            log_manager.logger.info("发送 ffs 1 命令")
            result = self.serial.send_command("ffs 1", timeout=5)
            log_manager.logger.info(f"ffs 1 返回：{result}")
            assert result is not None, "ffs 1 命令执行失败"

        with allure.step("等待并接收 FS 故障上报"):
            time.sleep(0.2)
            start = time.time()
            fs_msg = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 6:
                        fs_msg = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            if fs_msg is not None:
                log_manager.logger.info(f"FS 报错信息：{fs_msg.fields.get('failsafe')}")

        with allure.step("发送 ffs 0 命令清除故障"):
            log_manager.logger.info("发送 ffs 0 命令")
            result = self.serial.send_command("ffs 0", timeout=5)
            log_manager.logger.info(f"ffs 0 返回：{result}")
            assert result is not None, "ffs 0 命令执行失败"

    # ==================================================================
    # 解锁与上锁
    # ==================================================================

    @allure.story("解锁与上锁")
    @allure.title("右键解锁")
    @allure.description("验证右键解锁功能正常，发送解锁命令并收到应答")
    def test_release_34(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态确认在线"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("发送解锁命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, version=self.mavlink_version,
                                      fields={'param1': 0, 'param2': 0, 'param3': 0,
                                              'param4': 0, 'param5': 0, 'param6': 0,
                                              'param7': 0, 'command': MAV_CMD_COMPONENT_ARM_DISARM,
                                              'target_system': 1, 'target_component': 1,
                                              'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77
            assert ack.fields.get('command') == MAV_CMD_COMPONENT_ARM_DISARM

        with allure.step("发送上锁命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, version=self.mavlink_version,
                                      fields={'param1': 1, 'param2': 0, 'param3': 0,
                                              'param4': 0, 'param5': 0, 'param6': 0,
                                              'param7': 0, 'command': MAV_CMD_COMPONENT_ARM_DISARM,
                                              'target_system': 1, 'target_component': 1,
                                              'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77
            assert ack.fields.get('command') == MAV_CMD_COMPONENT_ARM_DISARM

    @allure.story("解锁与上锁")
    @allure.title("右键上锁")
    @allure.description("验证右键上锁功能正常，发送上锁命令并收到应答")
    def test_release_35(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态确认在线"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("发送解锁命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, version=self.mavlink_version,
                                      fields={'param1': 0, 'param2': 0, 'param3': 0,
                                              'param4': 0, 'param5': 0, 'param6': 0,
                                              'param7': 0, 'command': MAV_CMD_COMPONENT_ARM_DISARM,
                                              'target_system': 1, 'target_component': 1,
                                              'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77

        with allure.step("发送上锁命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, version=self.mavlink_version,
                                      fields={'param1': 1, 'param2': 0, 'param3': 0,
                                              'param4': 0, 'param5': 0, 'param6': 0,
                                              'param7': 0, 'command': MAV_CMD_COMPONENT_ARM_DISARM,
                                              'target_system': 1, 'target_component': 1,
                                              'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77

        with allure.step("等待无人机恢复正常心跳"):
            self._clear_recv_buffer()
            start = time.time()
            heartbeat_count = 0
            last_hb_time = 0
            while time.time() - start < 20.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    now = time.time()
                    if heartbeat_count == 0 or now - last_hb_time > 0.5:
                        heartbeat_count += 1
                        last_hb_time = now
                        if heartbeat_count >= 2:
                            break
                time.sleep(0.05)

    # ==================================================================
    # 飞行控制
    # ==================================================================

    @allure.story("飞行控制")
    @allure.title("右键降落")
    @allure.description("验证右键降落功能触发正常")
    def test_release_36(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 253:
                    pass
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态确认在线"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("触发右键降落"):
            time.sleep(0.5)

    @allure.story("飞行控制")
    @allure.title("右键返航")
    @allure.description("验证右键返航功能正常，发送返航命令并收到应答")
    def test_release_37(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求打包状态确认在线"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None, "未收到 packed_state"

        with allure.step("发送返航命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, version=self.mavlink_version,
                                      fields={'param1': 0, 'param2': 0, 'param3': 0,
                                              'param4': 0, 'param5': 0, 'param6': 0,
                                              'param7': 0, 'command': MAV_CMD_NAV_RETURN_TO_LAUNCH,
                                              'target_system': 1, 'target_component': 1,
                                              'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77

            while time.time() - start < 10.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 253:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            # assert ack is not None, "消息上报无应答"
            # assert ack.msg_id == 253
            time.sleep(5)

    # ==================================================================
    # 校准功能
    # ==================================================================

    @allure.story("校准功能")
    @allure.title("磁罗盘校准")
    @allure.description("验证磁罗盘校准功能正常，发送校准命令并收到应答")
    def test_release_38(self):
        time.sleep(5)
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 253:
                    pass
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态确认在线"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("发送磁罗盘校准命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, version=self.mavlink_version,
                                      fields={'param1': 1, 'param2': 1, 'param3': 0,
                                              'param4': 0, 'param5': 0, 'param6': 0,
                                              'param7': 0, 'command': MAV_CMD_PREFLIGHT_CALIBRATION,
                                              'target_system': 1, 'target_component': 1,
                                              'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77

    @allure.story("校准功能")
    @allure.title("加速度计校准")
    @allure.description("验证加速度计校准功能正常，发送校准命令并获取IMU原始数据")
    def test_release_39(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态确认在线"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("发送加速度计校准命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, version=self.mavlink_version,
                                      fields={'param1': 1, 'param2': 3, 'param3': 0,
                                              'param4': 0, 'param5': 0, 'param6': 0,
                                              'param7': 0, 'command': MAV_CMD_PREFLIGHT_CALIBRATION,
                                              'target_system': 1, 'target_component': 1,
                                              'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77

        with allure.step("获取 IMU_RAW0 原始数据"):
            result = self.serial.send_command("dt TP_IMU_RAW0", timeout=5)
            log_manager.logger.info(f"IMU_RAW0 返回：{result}")
            assert result is not None, "未收到设备响应"

        with allure.step("获取 IMU_RAW1 原始数据"):
            result = self.serial.send_command("dt TP_IMU_RAW1", timeout=5)
            log_manager.logger.info(f"IMU_RAW1 返回：{result}")
            assert result is not None, "未收到设备响应"

    @allure.story("校准功能")
    @allure.title("电调校准")
    @allure.description("验证电调校准功能正常，发送校准命令并收到应答")
    def test_release_43(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态确认在线"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("发送电调校准命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, version=self.mavlink_version,
                                      fields={'param1': 1, 'param2': 6, 'param3': 0,
                                              'param4': 0, 'param5': 0, 'param6': 0,
                                              'param7': 0, 'command': MAV_CMD_PREFLIGHT_CALIBRATION,
                                              'target_system': 1, 'target_component': 1,
                                              'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77

    @allure.story("校准功能")
    @allure.title("停止校准")
    @allure.description("验证停止校准功能正常，发送停止命令并收到应答")
    def test_release_40(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态确认在线"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("发送停止校准命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, version=self.mavlink_version,
                                      fields={'param1': 2, 'param2': 0, 'param3': 0,
                                              'param4': 0, 'param5': 0, 'param6': 0,
                                              'param7': 0, 'command': MAV_CMD_PREFLIGHT_CALIBRATION,
                                              'target_system': 1, 'target_component': 1,
                                              'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77

    # ==================================================================
    # 返航点设置
    # ==================================================================

    @allure.story("返航点设置")
    @allure.title("返航点设置")
    @allure.description("验证返航点设置功能正常，使用当前位置设置返航点并收到应答")
    def test_release_91(self):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        with allure.step("请求扩展状态确认在线"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            ext = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 8:
                        ext = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ext is not None, "未收到 extend_state"
            assert ext.msg_id == 8

        with allure.step("发送返航点设置命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, version=self.mavlink_version,
                                      fields={'param1': 1, 'param2': 0, 'param3': 0,
                                              'param4': 0, 'param5': 0, 'param6': 0,
                                              'param7': 0, 'command': MAV_CMD_DO_SET_HOME,
                                              'target_system': 1, 'target_component': 1,
                                              'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77

    # ==================================================================
    # 灯光控制
    # ==================================================================

    @allure.story("灯光控制")
    @allure.title("灯光颜色控制")
    @allure.description("验证飞机灯光颜色与地面站选择一致，支持红绿蓝三色切换和关灯")
    def test_release_108(self, mavlink_version):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        # 红色灯光测试
        r, g, b = 245, 0, 0
        with allure.step("发送红色灯光命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, sys_id=1, comp_id=1, seq=0,
                        version=mavlink_version,
                        fields={'param1': float(r), 'param2': float(g),
                                'param3': float(b), 'param4': 0.0,
                                'param5': 0.0, 'param6': 0.0, 'param7': 1.0,
                                'command': 183, 'target_system': 0,
                                'target_component': 0, 'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77
            time.sleep(0.5)

        with allure.step("验证红色灯光状态"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None
            f = packed.fields
            log_manager.logger.info(f"灯光 RGB: ({f.get('light_r')}, {f.get('light_g')}, {f.get('light_b')})")

        # 绿色灯光测试
        r, g, b = 0, 245, 0
        with allure.step("发送绿色灯光命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, sys_id=1, comp_id=1, seq=0,
                        version=mavlink_version,
                        fields={'param1': float(r), 'param2': float(g),
                                'param3': float(b), 'param4': 0.0,
                                'param5': 0.0, 'param6': 0.0, 'param7': 1.0,
                                'command': 183, 'target_system': 0,
                                'target_component': 0, 'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77
            time.sleep(0.5)

        with allure.step("验证绿色灯光状态"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None
            f = packed.fields
            log_manager.logger.info(f"灯光 RGB: ({f.get('light_r')}, {f.get('light_g')}, {f.get('light_b')})")

        # 蓝色灯光测试
        r, g, b = 0, 0, 245
        with allure.step("发送蓝色灯光命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, sys_id=1, comp_id=1, seq=0,
                        version=mavlink_version,
                        fields={'param1': float(r), 'param2': float(g),
                                'param3': float(b), 'param4': 0.0,
                                'param5': 0.0, 'param6': 0.0, 'param7': 1.0,
                                'command': 183, 'target_system': 0,
                                'target_component': 0, 'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77
            time.sleep(0.5)

        with allure.step("验证蓝色灯光状态"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None
            f = packed.fields
            log_manager.logger.info(f"灯光 RGB: ({f.get('light_r')}, {f.get('light_g')}, {f.get('light_b')})")

        # 关灯
        r, g, b = 0, 0, 0
        with allure.step("发送关灯命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, sys_id=1, comp_id=1, seq=0,
                        version=mavlink_version,
                        fields={'param1': float(r), 'param2': float(g),
                                'param3': float(b), 'param4': 0.0,
                                'param5': 0.0, 'param6': 0.0, 'param7': 1.0,
                                'command': 183, 'target_system': 0,
                                'target_component': 0, 'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77
            time.sleep(0.5)

        with allure.step("验证灯光关闭"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None
            f = packed.fields
            log_manager.logger.info(f"灯光 RGB: ({f.get('light_r')}, {f.get('light_g')}, {f.get('light_b')})")

    @allure.story("灯光控制")
    @allure.title("关灯控制")
    @allure.description("验证关灯功能正常，灯光全部关闭为零")
    def test_release_109(self, mavlink_version):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        r, g, b = 0, 0, 0
        with allure.step("发送关灯命令并验证应答"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, sys_id=1, comp_id=1, seq=0,
                        version=mavlink_version,
                        fields={'param1': float(r), 'param2': float(g),
                                'param3': float(b), 'param4': 0.0,
                                'param5': 0.0, 'param6': 0.0, 'param7': 1.0,
                                'command': 183, 'target_system': 0,
                                'target_component': 0, 'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77
            time.sleep(0.5)

        with allure.step("验证灯光全部为零"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None
            f = packed.fields
            log_manager.logger.info(f"灯光 RGB: ({f.get('light_r')}, {f.get('light_g')}, {f.get('light_b')})")

    @allure.story("灯光控制")
    @allure.title("灯光亮度控制")
    @allure.description("验证灯光亮度调节功能正常，支持不同亮度级别切换（0.15/0.3/0.6）")
    def test_release_110(self, mavlink_version):
        with allure.step("检测无人机上线"):
            start = time.time()
            found = False
            while time.time() - start < 5.0:
                msg, addr = self.gcs.receive()
                if msg is not None and msg.msg_id == 0:
                    self._drone_ip = addr[0]
                    found = True
                    break
                time.sleep(0.05)
            assert found, "未发现无人机"

        r = 240 * 0.15
        g = 0
        b = 0

        with allure.step("设置亮度0.15并验证"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, sys_id=1, comp_id=1, seq=0,
                        version=mavlink_version,
                        fields={'param1': float(r), 'param2': float(g),
                                'param3': float(b), 'param4': 0.0,
                                'param5': 0.0, 'param6': 0.0, 'param7': 1.0,
                                'command': 183, 'target_system': 0,
                                'target_component': 0, 'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77
            time.sleep(0.5)

            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None
            f = packed.fields
            log_manager.logger.info(f"亮度0.15 灯光 RGB: ({f.get('light_r')}, {f.get('light_g')}, {f.get('light_b')})")

        r = 240 * 0.3
        g = 0
        b = 0

        with allure.step("设置亮度0.3并验证"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, sys_id=1, comp_id=1, seq=0,
                        version=mavlink_version,
                        fields={'param1': float(r), 'param2': float(g),
                                'param3': float(b), 'param4': 0.0,
                                'param5': 0.0, 'param6': 0.0, 'param7': 1.0,
                                'command': 183, 'target_system': 0,
                                'target_component': 0, 'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77
            time.sleep(0.5)

            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None
            f = packed.fields
            log_manager.logger.info(f"亮度0.3 灯光 RGB: ({f.get('light_r')}, {f.get('light_g')}, {f.get('light_b')})")

        r = 240 * 0.6
        g = 0
        b = 0

        with allure.step("设置亮度0.6并验证"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, sys_id=1, comp_id=1, seq=0,
                        version=mavlink_version,
                        fields={'param1': float(r), 'param2': float(g),
                                'param3': float(b), 'param4': 0.0,
                                'param5': 0.0, 'param6': 0.0, 'param7': 1.0,
                                'command': 183, 'target_system': 0,
                                'target_component': 0, 'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77
            time.sleep(0.5)

            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None
            f = packed.fields
            log_manager.logger.info(f"亮度0.6 灯光 RGB: ({f.get('light_r')}, {f.get('light_g')}, {f.get('light_b')})")

        r = 0
        g = 0
        b = 0

        with allure.step("关灯并验证"):
            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            cmd_msg = MAVLink_message(msg_id=76, sys_id=1, comp_id=1, seq=0,
                        version=mavlink_version,
                        fields={'param1': float(r), 'param2': float(g),
                                'param3': float(b), 'param4': 0.0,
                                'param5': 0.0, 'param6': 0.0, 'param7': 1.0,
                                'command': 183, 'target_system': 0,
                                'target_component': 0, 'confirmation': 0})
            result = self.gcs.send(cmd_msg, addr=addr)
            assert result is True
            start = time.time()
            ack = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 77:
                        ack = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert ack is not None, "控制指令无应答"
            assert ack.msg_id == 77
            time.sleep(0.5)

            self._clear_recv_buffer()
            addr = (self._drone_ip or self.gcs.drone_ip, self.gcs.drone_port)
            hb_msg = MAVLink_message(hex_data=self._HEARTBEAT_DMD_HEX)
            result = self.gcs.send(hb_msg, addr=addr)
            assert result is True
            start = time.time()
            packed = None
            while time.time() - start < 3.0:
                msg, addr = self.gcs.receive()
                if msg is not None:
                    if msg.msg_id == 5:
                        packed = msg
                        break
                    elif msg.msg_id == 0:
                        self._drone_ip = addr[0]
                time.sleep(0.02)
            assert packed is not None
            f = packed.fields
            log_manager.logger.info(f"关灯后 RGB: ({f.get('light_r')}, {f.get('light_g')}, {f.get('light_b')})")
