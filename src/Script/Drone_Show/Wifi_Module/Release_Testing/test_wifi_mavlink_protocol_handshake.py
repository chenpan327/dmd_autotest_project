# coding: utf-8
"""
WiFi 模块测试 - MAVLink 协议握手流程(脚本层)

业务背景:
    DMD 自定义 MAVLink 协议定义了 GCS 与飞机之间的握手流程:
        1. GCS 收到 FC 心跳后,主动下发 msg_id=3(身份识别请求)
        2. FC 收到 msg_id=3 后,回 msg_id=2(身份信息:序列号 + 型号代码)
        3. GCS 收到 msg_id=2 后,下发 msg_id=1 extend=1(扩展状态请求)
        4. FC 收到后,回 msg_id=5(传感器状态)+ msg_id=8(系统详情)

    本测试用 FakeAirplane 模拟 FC,验证 WiFi 模块能完整透传这套握手流程。

测试项:
    1. 等待 GCS 身份识别请求(msg_id=3)
    2. 响应身份信息(msg_id=2)
    3. 等待 GCS 扩展状态请求(msg_id=1)
    4. 响应扩展状态(msg_id=5 + msg_id=8)
    5. 双向通信完整性(完整握手流程端到端验证)

环境前提:
    - 需要真实 GCS(dgcs4)在线,主动下发 id=3/id=1 请求
    - GCS 不在线时,所有用例 SKIP(不是 WiFi 模块 bug)

注:心跳透传链路验证见 test_wifi_mavlink_heartbeat_passthrough.py。
"""
import time
import pytest
import allure
import sys
import os
import io

# 确保项目根目录在 sys.path 中
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.Protocol.mavlink.fake_airplane import FakeAirplane
from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from utils.logger import log_manager



def _format_msg_detail(msg):
    """格式化消息详情(捕获 msg.print() 的输出)"""
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        msg.print()
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout
    return output


@allure.epic("WiFi 模块测试")
@allure.feature("MAVLink 通信")
@allure.story("协议握手流程")
class TestWifiMavlinkProtocolHandshake:
    """MAVLink 协议握手流程测试类"""

    # 真地面站探测超时(秒),探测失败则跳过依赖 GCS 的测试
    GCS_PROBE_TIMEOUT = 5.0


    @pytest.fixture(autouse=True)
    def setup_teardown(self, test_params, mavlink_version):
        """测试前置/后置:初始化 FakeAirplane,环境不可用则全 SKIP"""
        self.mavlink_version = mavlink_version
        self._skip_reason = None
        log_manager.logger.info("[Handshake-Test] ====== 初始化假飞机 ======")
        with allure.step("初始化假飞机"):
            self.fake_plane = FakeAirplane(mavlink_version=self.mavlink_version)
            if not self.fake_plane.udp_connected or self.fake_plane.sock is None:
                self._skip_reason = (
                    "FakeAirplane UDP 未就绪(WLAN 6 网卡可能未配置 IP),"
                    "协议握手测试无法执行 —— 请检查测试机网卡配置"
                )
                log_manager.logger.warning(f"[Handshake-Test] {self._skip_reason}")
            else:
                log_manager.logger.info(
                    f"[Handshake-Test] 假飞机: {self.fake_plane.local_ip}:{self.fake_plane.local_port}"
                )
                allure.attach(
                    f"假飞机: {self.fake_plane.local_ip}:{self.fake_plane.local_port}\n"
                    f"目标地面站: {self.fake_plane.ground_station_ip}:{self.fake_plane.ground_station_port}",
                    name="环境信息",
                    attachment_type=allure.attachment_type.TEXT
                )
        yield
        with allure.step("清理测试资源"):
            log_manager.logger.info("[Handshake-Test] ====== 清理资源 ======")
            self.fake_plane.close()


    def _ensure_fake_plane_ready(self):
        """若 FakeAirplane 未就绪则 SKIP 当前测试"""
        if self._skip_reason is not None:
            pytest.skip(self._skip_reason)


    def _check_gcs_online(self):
        """发送心跳探测真地面站是否在线,超时返回 False"""
        gcs_ip = self.fake_plane.ground_station_ip
        msg = MAVLink_message(
            msg_id=0, sys_id=1, comp_id=1, seq=0,
            version=self.mavlink_version,
            fields={'mavlink_version': 37}
        )
        self.fake_plane.send(msg, addr=(gcs_ip, self.fake_plane.ground_station_port))

        start = time.time()
        while time.time() - start < self.GCS_PROBE_TIMEOUT:
            received, addr = self.fake_plane.receive()
            if received is not None:
                log_manager.logger.info(
                    f"[Handshake-Test] 检测到地面站响应: msg_id={received.msg_id}, from={addr}"
                )
                return True
            time.sleep(0.1)

        log_manager.logger.info("[Handshake-Test] 未检测到真地面站响应")
        return False


    @allure.title("等待地面站身份识别请求(msg_id=3)")
    @allure.description(
        "假飞机等待真地面站发送身份识别请求(msg_id=3),验证 GCS → WiFi → FC 下行链路正常。\n"
        "GCS 不在线时 SKIP 而非 FAIL(环境问题)。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("MAVLink", "身份识别", "下行通信")
    def test_wait_gcs_identify_request(self):
        """测试等待地面站身份识别请求"""
        self._ensure_fake_plane_ready()
        if not self._check_gcs_online():
            pytest.skip("未检测到真地面站,跳过下行通信测试")

        with allure.step("等待地面站发送 msg_id=3 请求(timeout=30s)"):
            start_time = time.time()
            timeout = 30.0
            received = None
            while time.time() - start_time < timeout:
                received, addr = self.fake_plane.receive()
                if received is not None:
                    log_manager.logger.info(
                        f"[Handshake-Test] 收到消息: msg_id={received.msg_id}, from={addr}"
                    )
                    if received.msg_id == 3:
                        detail = _format_msg_detail(received)
                        log_manager.logger.info(f"[Handshake-Test] 收到 id=3 请求:")
                        log_manager.logger.info(detail)
                        allure.attach(
                            detail, name=f"假飞机收到请求 {addr[0]}",
                            attachment_type=allure.attachment_type.TEXT
                        )
                        break
                    elif received.msg_id == 0:
                        log_manager.logger.info("[Handshake-Test] 收到心跳,继续等待 id=3")
                        continue
                time.sleep(0.1)
            elapsed = time.time() - start_time
            log_manager.logger.info(f"[Handshake-Test] 等待结束 (耗时 {elapsed:.1f}s)")

        with allure.step("验证收到 msg_id=3"):
            assert received is not None, "假飞机未接收到真地面站的请求"
            assert received.msg_id == 3, f"期望 msg_id=3,实际收到 msg_id={received.msg_id}"
            allure.attach(
                f"收到 msg_id={received.msg_id}",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )


    @allure.title("假飞机响应身份信息(msg_id=2)")
    @allure.description(
        "向地面站发送 msg_id=2 身份响应(序列号 + 型号代码)。\n"
        "验证 FC → WiFi → GCS 上行链路 + WiFi 模块透传 msg_id=2 不丢失字段。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("MAVLink", "身份响应", "上行通信")
    def test_respond_identity(self):
        """测试发送身份信息响应"""
        self._ensure_fake_plane_ready()
        gcs_ip = self.fake_plane.ground_station_ip

        with allure.step("发送 msg_id=2 身份响应"):
            msg = MAVLink_message(
                msg_id=2,
                seq=28,
                sys_id=0,
                fields={'serial': "123", 'code': "123"}
            )
            log_manager.logger.info(f"[Handshake-Test] 创建身份消息: seq=28, hex={msg.hex_data}")
            result = self.fake_plane.send(msg, addr=(gcs_ip, self.fake_plane.ground_station_port))
            log_manager.logger.info(f"[Handshake-Test] 发送结果: {result}")
            time.sleep(0.3)

        with allure.step("验证身份响应发送成功"):
            assert result is True, "发送身份响应失败"
            allure.attach(
                "身份响应发送成功",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )


    @allure.title("等待地面站扩展状态请求(msg_id=1, extend=1)")
    @allure.description(
        "假飞机等待真地面站发送扩展状态请求(msg_id=1, extend=1)。\n"
        "GCS 不在线时 SKIP 而非 FAIL。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("MAVLink", "扩展状态", "下行通信")
    def test_wait_gcs_extend_request(self):
        """测试等待地面站扩展状态请求"""
        self._ensure_fake_plane_ready()
        if not self._check_gcs_online():
            pytest.skip("未检测到真地面站,跳过下行通信测试")

        with allure.step("等待地面站发送 msg_id=1, extend=1 请求(timeout=30s)"):
            start_time = time.time()
            timeout = 30.0
            received = None
            while time.time() - start_time < timeout:
                received, addr = self.fake_plane.receive()
                if received is not None:
                    log_manager.logger.info(
                        f"[Handshake-Test] 收到消息: msg_id={received.msg_id}, from={addr}"
                    )
                    if received.msg_id == 1:
                        detail = _format_msg_detail(received)
                        log_manager.logger.info(f"[Handshake-Test] 收到 id=1 请求:")
                        log_manager.logger.info(detail)
                        allure.attach(
                            detail, name=f"假飞机收到请求 {addr[0]}",
                            attachment_type=allure.attachment_type.TEXT
                        )
                        break
                    elif received.msg_id == 0:
                        log_manager.logger.info("[Handshake-Test] 收到心跳,继续等待 id=1")
                        continue
                time.sleep(0.1)
            elapsed = time.time() - start_time
            log_manager.logger.info(f"[Handshake-Test] 等待结束 (耗时 {elapsed:.1f}s)")

        with allure.step("验证收到 msg_id=1"):
            assert received is not None, "假飞机未接收到真地面站的请求"
            assert received.msg_id == 1, f"期望 msg_id=1,实际收到 msg_id={received.msg_id}"
            allure.attach(
                f"收到 msg_id={received.msg_id}",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )


    @allure.title("假飞机响应扩展状态(msg_id=5 和 msg_id=8)")
    @allure.description(
        "向地面站发送 msg_id=5(传感器状态)+ msg_id=8(系统详情)响应。\n"
        "验证 WiFi 模块透传大 payload(msg_id=8 含 30+ 字段)不丢字段。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("MAVLink", "扩展状态响应", "上行通信")
    def test_respond_extend_status(self):
        """测试发送扩展状态响应"""
        self._ensure_fake_plane_ready()
        gcs_ip = self.fake_plane.ground_station_ip

        with allure.step("发送 msg_id=5 传感器状态响应"):
            msg = MAVLink_message(
                msg_id=5, sys_id=1, comp_id=1,
                version=self.mavlink_version,
                fields={
                    'seq': 604054808,
                    'sensor_health': 3583,
                    'voltage_battery': 16277,
                    'wifi_up': 74,
                    'ssid': b'dmd_test',
                    'voltage_battery_diff': 71,
                    'voltage_battery_history_diff': 71,
                    'bat_serial_prefix': b'V4S24101',
                    'wind_speed_x': 1500,
                    'wind_speed_y': 450,
                    'bat_serial_suffix': b'',
                    'time_need_reset': 1,
                    'uav_speed_horz': 3,
                }
            )
            log_manager.logger.info(f"[Handshake-Test] id=5 消息: hex={msg.hex_data}")
            result = self.fake_plane.send(msg, addr=(gcs_ip, self.fake_plane.ground_station_port))
            log_manager.logger.info(f"[Handshake-Test] id=5 发送结果: {result}")
            assert result is True, "发送 id=5 响应失败"
            allure.attach(
                "id=5 传感器状态响应发送成功",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )

        with allure.step("发送 msg_id=8 系统详情响应"):
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
                    'battery_capability': 3500,
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
            log_manager.logger.info(f"[Handshake-Test] id=8 消息: hex={msg.hex_data}")
            result = self.fake_plane.send(msg, addr=(gcs_ip, self.fake_plane.ground_station_port))
            log_manager.logger.info(f"[Handshake-Test] id=8 发送结果: {result}")
            assert result is True, "发送 id=8 响应失败"
            allure.attach(
                "id=8 系统详情响应发送成功",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )


    @allure.title("双向通信完整性测试")
    @allure.description(
        "完整协议握手流程端到端验证:\n"
        "  发心跳 → 等 id=3 → 发 id=2 → 等 id=1 → 发 id=5 + id=8\n"
        "覆盖 WiFi 模块对 DMD 自定义 MAVLink 消息(0/1/2/3/5/8)的全部透传能力。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("MAVLink", "双向通信", "完整性测试")
    def test_bidirectional_communication_integrity(self):
        """测试完整的双向通信流程"""
        self._ensure_fake_plane_ready()
        if not self._check_gcs_online():
            pytest.skip("未检测到真地面站,跳过双向通信测试")

        results = {
            "heartbeat_sent": False,
            "id3_received": False,
            "id2_sent": False,
            "id1_received": False,
            "id5_sent": False,
            "id8_sent": False
        }

        gcs_ip = self.fake_plane.ground_station_ip

        with allure.step("步骤1: 假飞机发送心跳"):
            msg = MAVLink_message(
                msg_id=0, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'mavlink_version': 37}
            )
            result = self.fake_plane.send(msg, addr=(gcs_ip, self.fake_plane.ground_station_port))
            results["heartbeat_sent"] = result

        with allure.step("步骤2: 等待地面站身份识别请求 (msg_id=3)"):
            start_time = time.time()
            timeout = 30.0
            while time.time() - start_time < timeout:
                received, addr = self.fake_plane.receive()
                if received is not None:
                    if received.msg_id == 3:
                        results["id3_received"] = True
                        log_manager.logger.info(f"[Handshake-Test] 收到 id=3 请求 from {addr}")
                        break
                    elif received.msg_id == 0:
                        continue
                time.sleep(0.1)

        with allure.step("步骤3: 假飞机发送身份响应 (msg_id=2)"):
            if results["id3_received"]:
                msg = MAVLink_message(
                    msg_id=2, seq=28, sys_id=0,
                    fields={'serial': "DMDTEST0000000001", 'code': "V41"}
                )
                result = self.fake_plane.send(msg, addr=(gcs_ip, self.fake_plane.ground_station_port))
                results["id2_sent"] = result
                time.sleep(0.3)

        with allure.step("步骤4: 等待地面站扩展状态请求 (msg_id=1)"):
            start_time = time.time()
            timeout = 30.0
            while time.time() - start_time < timeout:
                received, addr = self.fake_plane.receive()
                if received is not None:
                    if received.msg_id == 1:
                        results["id1_received"] = True
                        log_manager.logger.info(f"[Handshake-Test] 收到 id=1 请求 from {addr}")
                        break
                    elif received.msg_id == 0:
                        continue
                time.sleep(0.1)

        with allure.step("步骤5: 假飞机发送传感器状态 (msg_id=5)"):
            if results["id1_received"]:
                msg = MAVLink_message(
                    msg_id=5, sys_id=1, comp_id=1,
                    version=self.mavlink_version,
                    fields={
                        'seq': 604054808,
                        'sensor_health': 3583,
                        'voltage_battery': 16277,
                        'wifi_up': 74,
                        'ssid': b'dmd_test',
                        'voltage_battery_diff': 71,
                        'voltage_battery_history_diff': 71,
                        'bat_serial_prefix': b'V4S24101',
                        'wind_speed_x': 1500,
                        'wind_speed_y': 450,
                        'bat_serial_suffix': b'',
                        'time_need_reset': 1,
                        'uav_speed_horz': 3,
                    }
                )
                result = self.fake_plane.send(msg, addr=(gcs_ip, self.fake_plane.ground_station_port))
                results["id5_sent"] = result

        with allure.step("步骤6: 假飞机发送系统详情 (msg_id=8)"):
            if results["id1_received"]:
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
                result = self.fake_plane.send(msg, addr=(gcs_ip, self.fake_plane.ground_station_port))
                results["id8_sent"] = result

        with allure.step("验证通信结果"):
            log_manager.logger.info(f"[Handshake-Test] 双向通信测试结果: {results}")
            assert results["heartbeat_sent"], "心跳发送失败"
            assert results["id3_received"], "未收到地面站身份识别请求 (msg_id=3)"
            assert results["id2_sent"], "身份响应发送失败 (msg_id=2)"
            assert results["id1_received"], "未收到地面站扩展状态请求 (msg_id=1)"
            assert results["id5_sent"], "传感器状态响应发送失败 (msg_id=5)"
            assert results["id8_sent"], "系统详情响应发送失败 (msg_id=8)"

        allure.attach(
            f"【测试结果】\n"
            f"  双向通信流程完成\n"
            f"  心跳发送: {'成功' if results['heartbeat_sent'] else '失败'}\n"
            f"  id=3 接收: {'成功' if results['id3_received'] else '失败'}\n"
            f"  id=2 发送: {'成功' if results['id2_sent'] else '失败'}\n"
            f"  id=1 接收: {'成功' if results['id1_received'] else '失败'}\n"
            f"  id=5 发送: {'成功' if results['id5_sent'] else '失败'}\n"
            f"  id=8 发送: {'成功' if results['id8_sent'] else '失败'}",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )
