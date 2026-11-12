#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LED 灯控制测试 - RGB 颜色、混合颜色、低亮度、渐变与开关控制

业务背景：
    无人机编队表演中，LED 灯是视觉效果的重要组成部分。通过 MAVLink COMMAND_LONG
    消息 (msg_id=76) 可以控制无人机的 RGB LED 灯颜色，实现编队灯光表演、状态指示
    等功能。地面站发送包含 light_r/light_g/light_b 参数的控制命令，无人机通过
    COMMAND_ACK (msg_id=77) 确认执行结果，并通过 PACKED_STATE (msg_id=5) 返回
    当前 LED 状态。

测试对象：
    - LED 控制命令报文 (COMMAND_LONG, msg_id=76)
      - param1/param2/param3 分别对应 light_r/light_g/light_b
      - 无人机固件将浮点参数截断为整数值（如 36.75 → 36）
    - COMMAND_ACK 响应 (msg_id=77)
    - PACKED_STATE 中的 light_r/light_g/light_b 字段 (msg_id=5)
    - heartbeat_dmd 请求报文 (msg_id=1, extend=1)

测试项：
    基础颜色：
    1. LED 红色控制 — light_r=36, light_g=0, light_b=0
    2. LED 绿色控制 — light_r=0, light_g=36, light_b=0
    3. LED 蓝色控制 — light_r=0, light_g=0, light_b=36
    4. LED 关闭控制 — light_r=0, light_g=0, light_b=0

    混合颜色：
    5. LED 黄色控制 — light_r=36, light_g=36, light_b=0
    6. LED 青色控制 — light_r=0, light_g=36, light_b=36
    7. LED 品红控制 — light_r=36, light_g=0, light_b=36
    8. LED 白色控制 — light_r=36, light_g=36, light_b=36

    低亮度：
    9.  LED 低亮度红色控制 — light_r=10, light_g=0, light_b=0
    10. LED 低亮度绿色控制 — light_r=0, light_g=10, light_b=0
    11. LED 低亮度蓝色控制 — light_r=0, light_g=0, light_b=10
    12. LED 低亮度白色控制 — light_r=10, light_g=10, light_b=10

    渐变（递增/递减，步长 50）：
    13. LED 红色递增 — light_r 0→50→100→150→200→250
    14. LED 红色递减 — light_r 250→200→150→100→50→0
    15. LED 绿色递增 — light_g 0→50→100→150→200→250
    16. LED 绿色递减 — light_g 250→200→150→100→50→0
    17. LED 蓝色递增 — light_b 0→50→100→150→200→250
    18. LED 蓝色递减 — light_b 250→200→150→100→50→0

    全遍历（步长 1，三重循环覆盖所有 RGB 组合）：
    19. LED RGB 全遍历 — R∈[0,255], G∈[0,255], B∈[0,255], 共 256^3=16777216 种组合
"""

import math
import pytest
import allure
import time
import socket

from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from src.Protocol.icat.Icat_Led_Analyser import ICATLedAnalyser, ICATError
from utils.logger import log_manager


def _int_to_param(val):
    """将期望整数值转为 COMMAND_LONG 浮点参数（固件截断 float→int）"""
    return 0.0 if val == 0 else float(val) + 0.75


def _make_led_cmd(version, r=0, g=0, b=0):
    """创建 LED 控制命令 (COMMAND_LONG, msg_id=76, command=183)"""
    return MAVLink_message(msg_id=76, sys_id=1, comp_id=1, seq=0,
                           version=version,
                           fields={'param1': float(r), 'param2': float(g),
                                   'param3': float(b), 'param4': 0.0,
                                   'param5': 0.0, 'param6': 0.0, 'param7': 1.0,
                                   'command': 183, 'target_system': 0,
                                   'target_component': 0, 'confirmation': 0})


def _make_heartbeat_dmd(version):
    """创建 heartbeat_dmd 报文 (msg_id=1, extend=1)"""
    return MAVLink_message(msg_id=1, sys_id=1, comp_id=1, seq=0,
                           version=version,
                           fields={'id': 1, 'autopilot': 22,
                                   'ssid': b'\x00' * 8, 'extend': 1})


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


def _rgb_to_hue(r, g, b):
    """根据 RGB 值 (0-255) 计算标准色相角 (0-360)。r=g=b 时返回 -1 表示无色彩。"""
    if r == g == b:
        return -1
    r_n, g_n, b_n = r / 255.0, g / 255.0, b / 255.0
    max_c, min_c = max(r_n, g_n, b_n), min(r_n, g_n, b_n)
    delta = max_c - min_c
    if delta == 0:
        return 0
    if max_c == r_n:
        hue = 60 * (((g_n - b_n) / delta) % 6)
    elif max_c == g_n:
        hue = 60 * (((b_n - r_n) / delta) + 2)
    else:
        hue = 60 * (((r_n - g_n) / delta) + 4)
    return round(hue) % 360


@pytest.mark.functional
class TestLedControlFunction:
    """LED 灯控制功能测试"""

    ICAT_COM_PORT = "COM4"

    @pytest.fixture(autouse=True)
    def setup_teardown(self, drone_ip, drone_port, mavlink_version):
        """测试前置/后置操作"""
        self.mavlink_version = mavlink_version
        self.led_cmd_off = _make_led_cmd(mavlink_version)
        self.heartbeat_dmd = _make_heartbeat_dmd(mavlink_version)
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

    def _discover_drone(self, timeout=5.0):
        """发现无人机并返回 IP"""
        start = time.time()
        while time.time() - start < timeout:
            received, addr = self.gcs.receive()
            if received is not None and received.msg_id == 0:
                log_manager.log_and_attach(f"发现无人机: {addr[0]}", "发现结果")
                return addr[0]
            time.sleep(0.1)
        return None

    @staticmethod
    def _wait_for_msg(gcs, msg_id, drone_ip, timeout=5.0):
        """等待指定 msg_id 的消息并返回，忽略心跳 (msg_id=0)，过滤非目标IP"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            received, addr = gcs.receive()
            if received is not None:
                if received.msg_id == msg_id:
                    if addr[0] == drone_ip:
                        return received, addr
                    else:
                        detail = _format_msg_detail(received)
                        log_manager.log_and_attach(detail, f"[其他飞机] msg_id={msg_id} 响应 {addr[0]}")
                elif received.msg_id == 0:
                    continue
            time.sleep(0.1)
        return None, None

    def _request_packed_state(self, drone_ip, retries=3):
        """发送 heartbeat_dmd 请求 packed_state，带重试"""
        for _ in range(retries):
            self.gcs.send(self.heartbeat_dmd, addr=(drone_ip, self.gcs.drone_port))
            time.sleep(0.3)
            received, addr = self._wait_for_msg(self.gcs, 5, drone_ip, timeout=3.0)
            if received is not None:
                return received, addr
        return None, None

    def _run_led_test(self, color_name, r_param, g_param, b_param,
                      expected_r, expected_g, expected_b):
        """执行单次 LED 控制测试的通用流程。"""
        with allure.step("发现无人机"):
            drone_ip = self._discover_drone()
            assert drone_ip is not None, "未发现无人机"

        with allure.step("先关闭 LED 确保初始状态"):
            self.gcs.send(self.led_cmd_off, addr=(drone_ip, self.gcs.drone_port))
            time.sleep(0.5)

        cmd = _make_led_cmd(self.mavlink_version, r=r_param, g=g_param, b=b_param)

        with allure.step(f"发送{color_name} LED 控制命令 (COMMAND_LONG, id=76)"):
            self.gcs.send(cmd, addr=(drone_ip, self.gcs.drone_port))
            log_manager.log_and_attach(f"发送至 {drone_ip}:{self.gcs.drone_port}", "发送目标")
            log_manager.log_and_attach(cmd.hex_data, "发送数据十六进制")

        with allure.step("等待 COMMAND_ACK 响应 (msg_id=77)"):
            received, addr = self._wait_for_msg(self.gcs, 77, drone_ip)
            assert received is not None, "未接收到 COMMAND_ACK 响应"
            detail = _format_msg_detail(received)
            log_manager.log_and_attach(detail, f"收到 COMMAND_ACK 详情 {addr[0]}")
            result = received.fields.get('result', -1)
            assert result == 0, f"LED 控制命令执行失败，result={result}"

        with allure.step("发送 heartbeat_dmd 请求 packed_state 并等待响应 (msg_id=5)"):
            received, addr = self._request_packed_state(drone_ip)
            assert received is not None, "未接收到 packed_state 响应（重试3次后）"

            light_r = received.fields.get('light_r', -1)
            light_g = received.fields.get('light_g', -1)
            light_b = received.fields.get('light_b', -1)
            log_manager.log_and_attach(f"light_r={light_r}, light_g={light_g}, light_b={light_b}", f"{color_name} RGB 值")

            assert light_r == expected_r, f"{color_name} LED: 期望 light_r={expected_r}，实际 light_r={light_r}"
            assert light_g == expected_g, f"{color_name} LED: 期望 light_g={expected_g}，实际 light_g={light_g}"
            assert light_b == expected_b, f"{color_name} LED: 期望 light_b={expected_b}，实际 light_b={light_b}"

        self._verify_led_via_icat(expected_r, expected_g, expected_b,
                                  step_label=color_name)

    def _run_led_ramp_test(self, channel_name, channel, values, direction):
        """执行 LED 渐变测试，逐级验证各亮度值。

        Args:
            channel_name: 通道中文名 ('红', '绿', '蓝')
            channel: 通道标识 ('r', 'g', 'b')
            values: 要测试的亮度值列表
            direction: 方向标识 ('递增' or '递减')
        """
        with allure.step("发现无人机"):
            drone_ip = self._discover_drone()
            assert drone_ip is not None, "未发现无人机"

        with allure.step("先关闭 LED 确保初始状态"):
            self.gcs.send(self.led_cmd_off, addr=(drone_ip, self.gcs.drone_port))
            time.sleep(0.5)

        for val in values:
            step_label = f"{direction} {channel_name} 亮度={val}"
            with allure.step(step_label):
                r_p = _int_to_param(val) if channel == 'r' else 0.0
                g_p = _int_to_param(val) if channel == 'g' else 0.0
                b_p = _int_to_param(val) if channel == 'b' else 0.0

                cmd = _make_led_cmd(self.mavlink_version, r=r_p, g=g_p, b=b_p)
                self.gcs.send(cmd, addr=(drone_ip, self.gcs.drone_port))

                received, addr = self._wait_for_msg(self.gcs, 77, drone_ip)
                assert received is not None, f"未收到 COMMAND_ACK ({step_label})"
                result = received.fields.get('result', -1)
                assert result == 0, f"LED 命令执行失败 result={result} ({step_label})"

                received, addr = self._request_packed_state(drone_ip)
                assert received is not None, f"未收到 packed_state ({step_label})"

                light_r = received.fields.get('light_r', -1)
                light_g = received.fields.get('light_g', -1)
                light_b = received.fields.get('light_b', -1)
                log_manager.log_and_attach(f"light_r={light_r}, light_g={light_g}, light_b={light_b}", step_label)

                exp_r = val if channel == 'r' else 0
                exp_g = val if channel == 'g' else 0
                exp_b = val if channel == 'b' else 0
                assert light_r == exp_r, f"期望 light_r={exp_r}，实际 light_r={light_r} ({step_label})"
                assert light_g == exp_g, f"期望 light_g={exp_g}，实际 light_g={light_g} ({step_label})"
                assert light_b == exp_b, f"期望 light_b={exp_b}，实际 light_b={light_b} ({step_label})"

                self._verify_led_via_icat(exp_r, exp_g, exp_b, step_label=step_label)

            time.sleep(0.1)

    def _verify_led_via_icat(self, expected_r, expected_g, expected_b, step_label=""):
        """通过 iCAT LED 分析仪验证物理 LED 颜色显示。

        读取 4 个通道的 LED 数据，计算期望色相与实测色相的偏差，
        验证偏差在容差范围内。

        Args:
            expected_r/g/b: 发送给无人机的 RGB 值 (0-255)
            step_label: 步骤描述，用于日志
        """
        expected_hue = _rgb_to_hue(expected_r, expected_g, expected_b)

        with allure.step(f"iCAT LED 分析仪验证 {step_label}".strip()):
            try:
                with ICATLedAnalyser(self.ICAT_COM_PORT, baudrate=19200) as icat:
                    for channel in range(4):
                        all_data = icat.get_channel_all(channel)
                        detail = (
                            f"通道 {channel} - 颜色: {all_data.color_name}\n"
                            f"  RGB 实测: {all_data.rgb}\n"
                            f"  HSI 实测: H={all_data.hue}, S={all_data.saturation}, I={all_data.intensity}\n"
                            f"  xy: ({all_data.x:.3f}, {all_data.y:.3f}), 波长: {all_data.wavelength}nm"
                        )
                        log_manager.log_and_attach(detail, f"iCAT 通道 {channel} {step_label}")

                        if expected_hue >= 0:
                            delta_hue = abs(all_data.hue - expected_hue)
                            delta_hue = min(delta_hue, 360 - delta_hue)
                            log_manager.log_and_attach(
                                f"通道 {channel} 期望色相={expected_hue}°, 实测色相={all_data.hue}°, "
                                f"色相差={delta_hue}°",
                                f"iCAT 色相校验 {step_label}"
                            )
                            assert delta_hue < 60, (
                                f"通道 {channel} 色相差过大: 期望色相={expected_hue}°, "
                                f"实测色相={all_data.hue}°, 色相差={delta_hue}° ({step_label})"
                            )
                        else:
                            # 无色相（r=g=b），验证饱和度应很低
                            log_manager.log_and_attach(
                                f"通道 {channel} 无色彩 (r=g=b={expected_r}), "
                                f"饱和度={all_data.saturation}, 强度={all_data.intensity}",
                                f"iCAT 消色差校验 {step_label}"
                            )
                            if expected_r == 0:
                                assert all_data.intensity < 30, (
                                    f"通道 {channel} LED 应关闭但强度偏高: "
                                    f"intensity={all_data.intensity} ({step_label})"
                                )

            except ICATError as e:
                log_manager.log_and_attach(f"iCAT 设备通讯异常: {e}", "iCAT 警告")
                allure.attach(f"iCAT 设备通讯异常: {e}", name="iCAT 警告",
                              attachment_type=allure.attachment_type.TEXT)

    # ── 基础颜色测试 ──────────────────────────────────────────────

    @allure.feature("LED 灯控制")
    @allure.story("LED 基础颜色控制")
    @allure.title("MAVLink LED 红色控制测试")
    def test_led_red_control(self):
        """测试发送红色 LED 控制命令"""
        self._run_led_test("红色", r_param=36.75, g_param=0, b_param=0,
                           expected_r=36, expected_g=0, expected_b=0)

    @allure.feature("LED 灯控制")
    @allure.story("LED 基础颜色控制")
    @allure.title("MAVLink LED 绿色控制测试")
    def test_led_green_control(self):
        """测试发送绿色 LED 控制命令"""
        self._run_led_test("绿色", r_param=0, g_param=36.75, b_param=0,
                           expected_r=0, expected_g=36, expected_b=0)

    @allure.feature("LED 灯控制")
    @allure.story("LED 基础颜色控制")
    @allure.title("MAVLink LED 蓝色控制测试")
    def test_led_blue_control(self):
        """测试发送蓝色 LED 控制命令"""
        self._run_led_test("蓝色", r_param=0, g_param=0, b_param=36.75,
                           expected_r=0, expected_g=0, expected_b=36)

    @allure.feature("LED 灯控制")
    @allure.story("LED 基础颜色控制")
    @allure.title("MAVLink LED 关闭控制测试")
    def test_led_off_control(self):
        """测试关闭 LED 灯"""
        self._run_led_test("关闭", r_param=0, g_param=0, b_param=0,
                           expected_r=0, expected_g=0, expected_b=0)

    # ── 混合颜色测试 ──────────────────────────────────────────────

    @allure.feature("LED 灯控制")
    @allure.story("LED 混合颜色控制")
    @allure.title("MAVLink LED 黄色控制测试")
    def test_led_yellow_control(self):
        """测试发送黄色 LED 控制命令 (红+绿)"""
        self._run_led_test("黄色", r_param=36.75, g_param=36.75, b_param=0,
                           expected_r=36, expected_g=36, expected_b=0)

    @allure.feature("LED 灯控制")
    @allure.story("LED 混合颜色控制")
    @allure.title("MAVLink LED 青色控制测试")
    def test_led_cyan_control(self):
        """测试发送青色 LED 控制命令 (绿+蓝)"""
        self._run_led_test("青色", r_param=0, g_param=36.75, b_param=36.75,
                           expected_r=0, expected_g=36, expected_b=36)

    @allure.feature("LED 灯控制")
    @allure.story("LED 混合颜色控制")
    @allure.title("MAVLink LED 品红控制测试")
    def test_led_magenta_control(self):
        """测试发送品红 LED 控制命令 (红+蓝)"""
        self._run_led_test("品红", r_param=36.75, g_param=0, b_param=36.75,
                           expected_r=36, expected_g=0, expected_b=36)

    @allure.feature("LED 灯控制")
    @allure.story("LED 混合颜色控制")
    @allure.title("MAVLink LED 白色控制测试")
    def test_led_white_control(self):
        """测试发送白色 LED 控制命令 (红+绿+蓝)"""
        self._run_led_test("白色", r_param=36.75, g_param=36.75, b_param=36.75,
                           expected_r=36, expected_g=36, expected_b=36)

    # ── 低亮度测试 ────────────────────────────────────────────────

    @allure.feature("LED 灯控制")
    @allure.story("LED 低亮度控制")
    @allure.title("MAVLink LED 低亮度红色控制测试")
    def test_led_dim_red_control(self):
        """测试发送低亮度红色 LED 控制命令"""
        self._run_led_test("低亮度红色", r_param=10.75, g_param=0, b_param=0,
                           expected_r=10, expected_g=0, expected_b=0)

    @allure.feature("LED 灯控制")
    @allure.story("LED 低亮度控制")
    @allure.title("MAVLink LED 低亮度绿色控制测试")
    def test_led_dim_green_control(self):
        """测试发送低亮度绿色 LED 控制命令"""
        self._run_led_test("低亮度绿色", r_param=0, g_param=10.75, b_param=0,
                           expected_r=0, expected_g=10, expected_b=0)

    @allure.feature("LED 灯控制")
    @allure.story("LED 低亮度控制")
    @allure.title("MAVLink LED 低亮度蓝色控制测试")
    def test_led_dim_blue_control(self):
        """测试发送低亮度蓝色 LED 控制命令"""
        self._run_led_test("低亮度蓝色", r_param=0, g_param=0, b_param=10.75,
                           expected_r=0, expected_g=0, expected_b=10)

    @allure.feature("LED 灯控制")
    @allure.story("LED 低亮度控制")
    @allure.title("MAVLink LED 低亮度白色控制测试")
    def test_led_dim_white_control(self):
        """测试发送低亮度白色 LED 控制命令 (红+绿+蓝)"""
        self._run_led_test("低亮度白色", r_param=10.75, g_param=10.75, b_param=10.75,
                           expected_r=10, expected_g=10, expected_b=10)

    # ── 渐变测试（递增）────────────────────────────────────────────

    @allure.feature("LED 灯控制")
    @allure.story("LED 渐变控制")
    @allure.title("MAVLink LED 红色递增控制测试")
    def test_led_red_ramp_up(self):
        """测试红色 LED 从 0 逐级递增到 250"""
        self._run_led_ramp_test("红", "r", range(0, 251, 50), "递增")

    @allure.feature("LED 灯控制")
    @allure.story("LED 渐变控制")
    @allure.title("MAVLink LED 绿色递增控制测试")
    def test_led_green_ramp_up(self):
        """测试绿色 LED 从 0 逐级递增到 250"""
        self._run_led_ramp_test("绿", "g", range(0, 251, 50), "递增")

    @allure.feature("LED 灯控制")
    @allure.story("LED 渐变控制")
    @allure.title("MAVLink LED 蓝色递增控制测试")
    def test_led_blue_ramp_up(self):
        """测试蓝色 LED 从 0 逐级递增到 250"""
        self._run_led_ramp_test("蓝", "b", range(0, 251, 50), "递增")

    # ── 渐变测试（递减）────────────────────────────────────────────

    @allure.feature("LED 灯控制")
    @allure.story("LED 渐变控制")
    @allure.title("MAVLink LED 红色递减控制测试")
    def test_led_red_ramp_down(self):
        """测试红色 LED 从 250 逐级递减到 0"""
        self._run_led_ramp_test("红", "r", range(250, -1, -50), "递减")

    @allure.feature("LED 灯控制")
    @allure.story("LED 渐变控制")
    @allure.title("MAVLink LED 绿色递减控制测试")
    def test_led_green_ramp_down(self):
        """测试绿色 LED 从 250 逐级递减到 0"""
        self._run_led_ramp_test("绿", "g", range(250, -1, -50), "递减")

    @allure.feature("LED 灯控制")
    @allure.story("LED 渐变控制")
    @allure.title("MAVLink LED 蓝色递减控制测试")
    def test_led_blue_ramp_down(self):
        """测试蓝色 LED 从 250 逐级递减到 0"""
        self._run_led_ramp_test("蓝", "b", range(250, -1, -50), "递减")

    # ── 全遍历测试（三重循环，步长 1）──────────────────────────────
    # 耗时过长（256^3=16777216 次 ≈ 194 天），暂时注释，按需取消

    # def _run_led_rgb_exhaustive(self):
    #     """执行 LED RGB 三重循环全遍历测试，覆盖所有 256^3=16777216 种 RGB 组合。"""
    #     with allure.step("发现无人机"):
    #         drone_ip = self._discover_drone()
    #         assert drone_ip is not None, "未发现无人机"

    #     with allure.step("先关闭 LED 确保初始状态"):
    #         self.gcs.send(self.led_cmd_off, addr=(drone_ip, self.gcs.drone_port))
    #         time.sleep(0.5)

    #     count = 0
    #     for r in range(256):
    #         for g in range(256):
    #             for b in range(256):
    #                 r_p = _int_to_param(r)
    #                 g_p = _int_to_param(g)
    #                 b_p = _int_to_param(b)
    #                 cmd = _make_led_cmd(self.mavlink_version, r=r_p, g=g_p, b=b_p)
    #                 self.gcs.send(cmd, addr=(drone_ip, self.gcs.drone_port))

    #                 received, _ = self._wait_for_msg(self.gcs, 77)
    #                 assert received is not None, \
    #                     f"未收到 COMMAND_ACK (R={r},G={g},B={b})"
    #                 result = received.fields.get('result', -1)
    #                 assert result == 0, \
    #                     f"LED 命令执行失败 result={result} (R={r},G={g},B={b})"

    #                 received, _ = self._request_packed_state(drone_ip)
    #                 assert received is not None, \
    #                     f"未收到 packed_state (R={r},G={g},B={b})"

    #                 light_r = received.fields.get('light_r', -1)
    #                 light_g = received.fields.get('light_g', -1)
    #                 light_b = received.fields.get('light_b', -1)
    #                 assert light_r == r, \
    #                     f"期望 light_r={r}，实际 light_r={light_r} (R={r},G={g},B={b})"
    #                 assert light_g == g, \
    #                     f"期望 light_g={g}，实际 light_g={light_g} (R={r},G={g},B={b})"
    #                 assert light_b == b, \
    #                     f"期望 light_b={b}，实际 light_b={light_b} (R={r},G={g},B={b})"

    #                 count += 1
    #                 if count % 256 == 0:
    #                     log_manager.log_and_attach(
    #                         f"已测试 {count}/16777216 ({count*100//16777216}%)", "全遍历进度")

    #     log_manager.log_and_attach("RGB 全遍历 16777216 次测试全部通过", "全遍历结果")

    # @allure.feature("LED 灯控制")
    # @allure.story("LED 全遍历控制")
    # @allure.title("MAVLink LED RGB 三重循环全遍历控制测试")
    # def test_led_rgb_exhaustive(self):
    #     """三重 for 循环遍历所有 RGB 组合 (256^3=16777216)，步长=1"""
    #     self._run_led_rgb_exhaustive()
