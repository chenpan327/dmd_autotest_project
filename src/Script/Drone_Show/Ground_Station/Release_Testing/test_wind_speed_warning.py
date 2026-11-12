#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""风速超限预警自动化测试用例。

测试地面站对 MAVLink 风速信息 (id=5 中 wind_speed_x / wind_speed_y) 的响应：
  - 风速计算与显示
  - 告警等级阈值触发
  - 告警弹窗升降级逻辑
  - 告警信息内容（中/英文）
  - 弹窗交互行为
  - 多飞机风速取最大值

风速字段单位: cm/s (int16), 即 4.9 m/s → raw value 490。
"""

import pytest
import allure
import time
import os
import re

from src.Protocol.mavlink.fake_airplane import FakeAirplane,_WindSpeedSender,_send_wind_speed_async
from src.Protocol.mavlink.parse_mavlink import MAVLink_message

# 风速阈值 (m/s → cm/s)
WIND_4_9 = 490   # 4.9 m/s
WIND_4_9_r = -490   # -4.9 m/s
WIND_5_0 = 500   # 5.0 m/s  (一级告警阈值)
WIND_7_9 = 790   # 7.9 m/s
WIND_8_0 = 800   # 8.0 m/s  (二级告警阈值)
WIND_11_9 = 1190 # 11.9 m/s
WIND_12_0 = 1200 # 12.0 m/s (三级告警阈值)


def _format_msg_detail(msg):
    import io
    import sys
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    msg.print()
    output = sys.stdout.getvalue()
    sys.stdout = old_stdout
    return output


def _calc_expected_wind_speed(wind_speed_x, wind_speed_y):
    """计算预期风速（矢量和解算），单位cm/s转m/s"""
    wx_ms = wind_speed_x / 100.0
    wy_ms = wind_speed_y / 100.0
    return (wx_ms ** 2 + wy_ms ** 2) ** 0.5


def _calc_expected_wind_direction(wind_speed_x, wind_speed_y):
    """计算预期风向（度），基于矢量和解算

    Args:
        wind_speed_x: x方向风速原始值(cm/s)
        wind_speed_y: y方向风速原始值(cm/s)

    Returns:
        风向角度(度)
    """
    import math
    wx_ms = wind_speed_x / 100.0
    wy_ms = wind_speed_y / 100.0
    # 使用 atan2 计算弧度，再转换为度
    direction_rad = math.atan2(wy_ms, wx_ms)
    direction_deg = math.degrees(direction_rad)
    return direction_deg


def _calc_max_wind_speed(speeds):
    """计算多架飞机风速的最大值

    Args:
        speeds: list of (wind_speed_x, wind_speed_y) tuples in cm/s

    Returns:
        max wind speed in m/s
    """
    max_speed = 0.0
    for wx, wy in speeds:
        speed = _calc_expected_wind_speed(wx, wy)
        if speed > max_speed:
            max_speed = speed
    return max_speed


def _assert_wind_speed_warning(dgcs_app, log_manager, expected_level, expected_text="", label=""):
    """通用风速告警弹窗断言

    Args:
        dgcs_app: DGCS应用实例
        log_manager: 日志管理器
        expected_level: 预期告警等级 (1/2/3 或 False)
        label: 用例标签，用于日志
    """
    warning_window = dgcs_app.check_windspeed_warning_window()
    if warning_window:
        warning_level, warning_text = dgcs_app.get_windspeed_warning_info()
    else:
        warning_level, warning_text = False, None

    # 1. 告警弹窗存在性断言
    if expected_level:
        assert warning_window, f"{label} 预期存在告警弹窗，实际不存在"
    else:
        assert not warning_window, f"{label} 预期不存在告警弹窗，实际存在"

    # 2. 告警等级断言
    # print(f"[TEST] {label} 预期告警等级={expected_level}, 实际={warning_level}")
    assert warning_level == expected_level, f"{label} 告警等级不符: 预期{expected_level}, 实际{warning_level}"
    allure.attach(f"[TEST] {label} 预期等级={expected_level}, 实际={warning_level}", "告警等级")
    log_manager.logger.info(f"[TEST] 风速告警弹窗等级断言 预期等级={expected_level}, 实际={warning_level}")

    # 3. 告警文本附件（若存在弹窗且有文本）
    if warning_window and warning_text:
        # 仅提取汉字、英文、数字进行对比
        filtered_actual = re.sub(r'[^一-龥a-zA-Z0-9]', '', warning_text)
        filtered_expected = re.sub(r'[^一-龥a-zA-Z0-9]', '', expected_text) if expected_text else ""
        if expected_text != "":
            assert filtered_actual == filtered_expected, f"告警信息与预期不符: 实际={warning_text}, 预期={expected_text}"
            allure.attach(f"告警文本: {warning_text}", "告警信息")
            log_manager.logger.info(f"[TEST] 风速告警弹窗文本断言 预期文本={filtered_expected}, 实际={filtered_actual}")
        else:
            allure.attach(f"告警文本: {warning_text}", "告警信息")


def _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, wind_speed_x, wind_speed_y, label=""):
    """通用风速信息断言：风速大小和颜色

    Args:
        dgcs_app: DGCS应用实例
        log_manager: 日志管理器
        expected_speed: 预期风速值(m/s)
        wind_speed_x: x方向风速原始值(cm/s)
        wind_speed_y: y方向风速原始值(cm/s)
        label: 用例标签，用于日志
    """
    direction, speed, color = dgcs_app.get_othermenu_windspeed_info_text()

    # 1. 风速大小断言：offset<=0.1m/s,飞机未上线则默认风速为0.0且不进行风向判断
    try:
        actual_speed = float(speed)
        direction_flag = True
    except:
        actual_speed = 0.0
        direction_flag = False
    offset = abs(actual_speed - expected_speed)
    # print(f"[TEST] {label} 预期风速={expected_speed:.1f}m/s, 实际={actual_speed:.1f}m/s, offset={offset:.1f}m/s")
    assert offset <= 0.1, f"{label} 风速偏差超过0.1m/s: 预期{expected_speed:.1f}m/s, 实际{actual_speed:.1f}m/s"
    allure.attach(f"[TEST] {label} 预期风速={expected_speed:.1f}m/s, 实际={actual_speed:.1f}m/s, offset={offset:.1f}m/s", "风速大小")
    log_manager.logger.info(f"[TEST] 风速大小断言 预期风速={expected_speed:.1f}m/s, 实际={actual_speed:.1f}m/s, offset={offset:.1f}m/s")

    # 2. 风向断言
    if direction_flag:
        expected_direction = _calc_expected_wind_direction(wind_speed_x, wind_speed_y)
        # 允许 ±2° 的误差范围
        direction_offset = abs(direction - expected_direction) if direction is not None else None
        # print(f"[TEST] {label} 预期风向={expected_direction:.1f}°, 实际风向={direction}°, 偏差={direction_offset:.1f}°")
        if direction is not None:
            assert direction_offset <= 2, f"{label} 风向偏差超过2°: 预期{expected_direction:.1f}°, 实际{direction}°"
        allure.attach(f"[TEST] {label} 预期风向={expected_direction:.1f}°, 实际风向={direction}°, 偏差={direction_offset:.1f}°", "风向")
        log_manager.logger.info(f"[TEST] 风向断言 预期风向={expected_direction:.1f}°, 实际风向={direction}°, 偏差={direction_offset:.1f}°")

    # 3. 风速字体颜色断言
    expected_color = "Red" if expected_speed >= 5.0 else "White"
    # print(f"[TEST] {label} 预期颜色={expected_color}, 实际颜色={color}")
    assert color == expected_color, f"{label} 颜色不符: 预期{expected_color}, 实际{color}"
    allure.attach(f"[TEST] {label} 预期颜色={expected_color}, 实际颜色={color}", "风速字体颜色")
    log_manager.logger.info(f"[TEST] 风速字体颜色断言 预期颜色={expected_color}, 实际颜色={color}")


def _assert_click_windspeed_warning_iknow(dgcs_app, log_manager, label=""):
    """点击风速告警弹窗的「我知道了」按钮并验证关闭

    Args:
        dgcs_app: DGCS应用实例
        log_manager: 日志管理器
        label: 用例标签，用于日志
    """
    # 点击前：检查弹窗有效性
    warning_window_before = dgcs_app.check_windspeed_warning_window()
    click_success = False
    window_closed = False

    if warning_window_before:
        click_success = dgcs_app.click_windspeed_warning_iknow_window()
        # 等待弹窗关闭
        time.sleep(0.5)
        window_closed = not dgcs_app.check_windspeed_warning_window()

    allure.attach(
        f"{label} 点击「我知道了」按钮\n"
        f"点击前弹窗存在: {warning_window_before}\n"
        f"点击是否成功: {click_success}\n"
        f"点击后弹窗是否关闭: {window_closed}",
        "操作结果"
    )
    log_manager.logger.info(f"[TEST] 点击风速告警弹窗的「我知道了」按钮断言 点击前弹窗存在: {warning_window_before}  点击是否成功: {click_success}  点击后弹窗是否关闭: {window_closed}")

    assert warning_window_before, f"{label} 点击前弹窗不存在，无法点击"
    assert click_success, f"{label} 点击「我知道了」按钮失败"
    assert window_closed, f"{label} 点击后弹窗未关闭"


def _assert_click_windspeed_warning_close(dgcs_app, log_manager, label=""):
    """点击风速告警弹窗的关闭按钮并验证关闭

    Args:
        dgcs_app: DGCS应用实例
        log_manager: 日志管理器
        label: 用例标签，用于日志
    """
    # 点击前：检查弹窗有效性
    warning_window_before = dgcs_app.check_windspeed_warning_window()
    click_success = False
    window_closed = False

    if warning_window_before:
        click_success = dgcs_app.click_windspeed_warning_close_window()
        # 等待弹窗关闭
        time.sleep(0.5)
        window_closed = not dgcs_app.check_windspeed_warning_window()

    allure.attach(
        f"{label} 点击关闭按钮\n"
        f"点击前弹窗存在: {warning_window_before}\n"
        f"点击是否成功: {click_success}\n"
        f"点击后弹窗是否关闭: {window_closed}",
        "操作结果"
    )
    log_manager.logger.info(f"[TEST] 点击风速告警弹窗的「关闭」按钮断言 点击前弹窗存在: {warning_window_before}  点击是否成功: {click_success}  点击后弹窗是否关闭: {window_closed}")

    assert warning_window_before, f"{label} 点击前弹窗不存在，无法点击"
    assert click_success, f"{label} 点击关闭按钮失败"
    assert window_closed, f"{label} 点击后弹窗未关闭"

@pytest.mark.functional
class TestWindSpeedExceedanceWarning:
    """风速超限预警功能测试 - 与真实地面站交互."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, dgcs_app, log_manager, request: pytest.FixtureRequest, mavlink_version):
        self.mavlink_version = mavlink_version

        if dgcs_app.start_app():
            log_manager.logger.info("[TEST] ====== 启动 DGCS 应用 ======")
            dgcs_app.click_login()
            success = dgcs_app.check_login_success(wait_time=10)
            if not success:
                log_manager.logger.info("[TEST] ====== DGCS 登录失败，跳过登录后测试 ======")
                pytest.skip("DGCS 登录失败，跳过登录后测试")
            else:
                log_manager.logger.info("[TEST] ====== DGCS 登录成功 ======")
            # 登录后可能需要等待主窗口就绪并处理常见弹窗
            dgcs_app.check_main_window_waiting(wait_time=3)
            dgcs_app.check_battery_warming(wait_time=3)
        else:
            if not dgcs_app.check_login_window():
                log_manager.logger.info("[TEST] ====== 无法启动 DGCS 应用 ======")
                pytest.skip(f"无法启动 DGCS 应用")
            else:
                if dgcs_app.check_main_window():
                    log_manager.logger.info("[TEST] ====== 已启动 DGCS 应用 ======")

        log_manager.logger.info("[TEST] ====== 初始化假飞机 ======")
        with allure.step("初始化假飞机"):
            self.fake_plane = FakeAirplane(mavlink_version=self.mavlink_version)
            log_manager.logger.info(f"[TEST] 假飞机: {self.fake_plane.local_ip}:{self.fake_plane.local_port}")
            log_manager.logger.info(f"[TEST] 地面站: {self.fake_plane.ground_station_ip}:{self.fake_plane.ground_station_port}")
            allure.attach(
                f"假飞机: {self.fake_plane.local_ip}:{self.fake_plane.local_port}\n"
                f"地面站: {self.fake_plane.ground_station_ip}:{self.fake_plane.ground_station_port}",
                "连接信息"
            )
            with allure.step("自动响应地面站发送 id=1 extend=1 请求"):
                self.wind_sender = _WindSpeedSender(log_manager, self.fake_plane, addr=(self.fake_plane.ground_station_ip, self.fake_plane.ground_station_port))
            log_manager.logger.info(f"[TEST] 假飞机: {self.fake_plane.local_ip}:{self.fake_plane.local_port}")
            log_manager.logger.info(f"[TEST] 地面站: {self.fake_plane.ground_station_ip}:{self.fake_plane.ground_station_port}")
        yield
        with allure.step("清理测试资源"):
            if dgcs_app.check_windspeed_warning_window():
                dgcs_app.click_windspeed_warning_close_window()
            log_manager.logger.info("[TEST] ====== 清理资源 ======")
            self.wind_sender.stop()
            self.fake_plane.close()
            allure.attach("资源已清理", "清理信息")
            # teardown：关闭应用
            try:
                dgcs_app.close_app()
                log_manager.logger.info("[TEST] ====== 关闭应用 ======")
            except Exception as exc:
                # 终止进程作为兜底
                try:
                    dgcs_app.ui.terminate_process()
                    log_manager.logger.info("[TEST] ====== 终止进程 ======")
                except Exception:
                    pass
            
    # ------------------------------------------------------------------
    # 协议握手
    # ------------------------------------------------------------------
    def _do_handshake(self, log_manager):
        """执行 MAVLink 握手：心跳 → 收 id=3 → 发 id=2 → 收 id=1(extend=1) → 返回 addr."""
        gcs_ip = self.fake_plane.ground_station_ip
        gcs_port = self.fake_plane.ground_station_port

        with allure.step("发送心跳 (id=0)"):
            time.sleep(10)

            log_manager.logger.info("[TEST] 步骤1: 发送心跳")
            msg = MAVLink_message(msg_id=0, sys_id=1, comp_id=1, seq=0,
                                  version=self.mavlink_version, fields={'mavlink_version': 37})
            self.fake_plane.send(msg, addr=(gcs_ip, gcs_port))

        with allure.step("等待地面站发送 id=3 请求"):
            log_manager.logger.info("[TEST] 步骤2: 等待 id=3 (timeout=30s)")
            start = time.time()
            received = None
            while time.time() - start < 30.0:
                received, addr = self.fake_plane.receive()
                if received is not None:
                    log_manager.logger.info(f"[TEST] 收到 msg_id={received.msg_id} from={addr}")
                    if received.msg_id == 3:
                        allure.attach(_format_msg_detail(received), f"收到 id=3 请求 ({gcs_ip})")
                        break
                    elif received.msg_id == 0:
                        continue
                time.sleep(0.1)
            assert received is not None, "未接收到地面站的 id=3 请求"
            assert received.msg_id == 3, f"期望 msg_id=3, 实际={received.msg_id}"

        with allure.step("发送 id=2 身份信息"):
            log_manager.logger.info("[TEST] 步骤3: 发送 id=2")
            msg = MAVLink_message(msg_id=2, seq=28, sys_id=0,
                                  fields={'serial': "123", 'code': "123"})
            self.fake_plane.send(msg, addr=(gcs_ip, gcs_port))
            time.sleep(0.3)

        with allure.step("等待地面站发送 id=1 (extend=1) 请求"):
            log_manager.logger.info("[TEST] 步骤4: 等待 id=1 extend=1 (timeout=30s)")
            start = time.time()
            received = None
            ground_addr = None
            while time.time() - start < 30.0:
                received, ground_addr = self.fake_plane.receive()
                if received is not None:
                    log_manager.logger.info(f"[TEST] 收到 msg_id={received.msg_id} from={ground_addr}")
                    if received.msg_id == 1:
                        allure.attach(_format_msg_detail(received),
                                      f"收到 id=1 请求 ({ground_addr})")
                        break
                    elif received.msg_id == 0:
                        continue
                time.sleep(0.1)
            assert received is not None, "未接收到地面站的 id=1 请求"
            assert received.msg_id == 1, f"期望 msg_id=1, 实际={received.msg_id}"

        with allure.step("开启心跳报文监控线程"):
            self.wind_sender.start()

        return True

    # ==================================================================
    # 分类一：风速计算关系 (001 ~ 005)
    # ==================================================================

    @allure.feature("风速超限预警")
    @allure.story("风速计算关系")
    @allure.title("001: wind_speed_x=0, wind_speed_y=4.9 → 地面站显示 90° 4.9m/s")
    def test_001_wind_speed_y_only(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 001: wx=0, wy=4.9m/s =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"
        
        with allure.step("发送风速 wx=0, wy=4.9"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_4_9), "更新风速信息失败"

        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_4_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_4_9, label="001")
            _assert_wind_speed_warning(dgcs_app, log_manager, False, label="001")

        log_manager.logger.info("[TEST] ====== 001 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("风速计算关系")
    @allure.title("002: wind_speed_x=0, wind_speed_y=-4.9 → 地面站显示 -90° 4.9m/s")
    def test_002_wind_speed_y_only_r(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 002: wx=0, wy=-4.9m/s =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送风速 wx=0, wy=-4.9"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_4_9_r), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_4_9_r)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_4_9_r, label="002")
            _assert_wind_speed_warning(dgcs_app, log_manager, False, label="002")
        log_manager.logger.info("[TEST] ====== 002 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("风速计算关系")
    @allure.title("003: wind_speed_x=4.9, wind_speed_y=0 → 地面站显示 0° 4.9m/s")
    def test_003_wind_speed_x_only(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 003: wx=4.9m/s, wy=0 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送风速 wx=4.9, wy=0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, WIND_4_9, 0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(WIND_4_9, 0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, WIND_4_9, 0, label="003")
            _assert_wind_speed_warning(dgcs_app, log_manager, False, label="003")
        log_manager.logger.info("[TEST] ====== 003 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("风速计算关系")
    @allure.title("004: wind_speed_x=-4.9, wind_speed_y=0 → 地面站显示 180° 4.9m/s")
    def test_004_wind_speed_x_only_r(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 004: wx=-4.9m/s, wy=0 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送风速 wx=-4.9, wy=0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, WIND_4_9_r, 0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(WIND_4_9_r, 0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, WIND_4_9_r, 0, label="004")
            _assert_wind_speed_warning(dgcs_app, log_manager, False, label="004")
        log_manager.logger.info("[TEST] ====== 004 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("风速计算关系")
    @allure.title("005: wind_speed_x=4.9, wind_speed_y=4.9 → 地面站显示 45° 6.93m/s")
    def test_005_both_components(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 005: wx=4.9m/s, wy=4.9m/s =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送风速 wx=4.9, wy=4.9"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, WIND_4_9, WIND_4_9), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(WIND_4_9, WIND_4_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, WIND_4_9, WIND_4_9, label="005")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="005")
        log_manager.logger.info("[TEST] ====== 005 完成 ======")

    # ==================================================================
    # 分类二：告警检测频率 (006 ~ 007)
    # ==================================================================

    @allure.feature("风速超限预警")
    @allure.story("告警检测频率")
    @allure.title("006: 0.5秒内风速从5.0变为8.0 → 地面站每秒出现告警弹窗")
    def test_006_frequency_05s(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 006: 0.5s 内 5.0→8.0m/s =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=5.0，0.5秒后发送 wy=8.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="006-发送5.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="006-发送5.0后")
            time.sleep(0.5)
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_8_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_8_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="006-发送8.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="006-发送8.0后")

        with allure.step("验证"):
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="006-最终验证")
            allure.attach("预期: 触发二级告警弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 006 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("告警检测频率")
    @allure.title("007: 1秒后风速从5.0变为8.0 → 地面站每秒出现告警弹窗")
    def test_007_frequency_1s(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 007: 1s 后 5.0→8.0m/s =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=5.0，1秒后发送 wy=8.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="007-发送5.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="007-发送5.0后")
            time.sleep(1.0)
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_8_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_8_0)
            time.sleep(0.5)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="007-发送8.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="007-发送8.0后")

        with allure.step("验证"):
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="007-最终验证")
            allure.attach("预期: 触发二级告警弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 007 完成 ======")

    # ==================================================================
    # 分类三：告警等级阈值 (008 ~ 013)
    # ==================================================================

    @allure.feature("风速超限预警")
    @allure.story("告警等级阈值")
    @allure.title("008: wy=4.9m/s (<5m/s) → 不触发一级告警")
    def test_008_below_level1(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 008: wy=4.9m/s, 不触发告警 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=4.9"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_4_9), "更新风速信息失败"

        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_4_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_4_9, label="008")
            _assert_wind_speed_warning(dgcs_app, log_manager, False, label="008")
            allure.attach("预期: 风速=4.9m/s, 白色, 无告警弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 008 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("告警等级阈值")
    @allure.title("009: wy=5.0m/s (≥5m/s) → 触发一级告警")
    def test_009_level1(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 009: wy=5.0m/s, 一级告警 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=5.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="009")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="009")
            allure.attach("预期: 风速=5.0m/s, 红色, 一级告警弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 009 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("告警等级阈值")
    @allure.title("010: wy=7.9m/s (<8m/s) → 触发一级告警(非二级)")
    def test_010_below_level2(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 010: wy=7.9m/s, 一级告警 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=7.9"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_7_9), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_7_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_7_9, label="010")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="010")
            allure.attach("预期: 风速=7.9m/s, 红色, 一级告警弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 010 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("告警等级阈值")
    @allure.title("011: wy=8.0m/s (≥8m/s) → 触发二级告警")
    def test_011_level2(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 011: wy=8.0m/s, 二级告警 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=8.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_8_0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_8_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="011")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="011")
            allure.attach("预期: 风速=8.0m/s, 红色, 二级告警弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 011 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("告警等级阈值")
    @allure.title("012: wy=11.9m/s (<12m/s) → 触发二级告警(非三级)")
    def test_012_below_level3(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 012: wy=11.9m/s, 二级告警 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=11.9"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_11_9), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_11_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_11_9, label="012")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="012")
            allure.attach("预期: 风速=11.9m/s, 红色, 二级告警弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 012 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("告警等级阈值")
    @allure.title("013: wy=12.0m/s (≥12m/s) → 触发三级告警")
    def test_013_level3(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 013: wy=12.0m/s, 三级告警 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=12.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_12_0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_12_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_12_0, label="013")
            _assert_wind_speed_warning(dgcs_app, log_manager, 3, label="013")
            allure.attach("预期: 风速=12.0m/s, 红色, 三级告警弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 013 完成 ======")

    # ==================================================================
    # 分类四：风速信息显示颜色 (014 ~ 017)
    # ==================================================================

    @allure.feature("风速超限预警")
    @allure.story("风速信息显示")
    @allure.title("014: wy=4.9m/s (不超限) → 右上角白字显示 4.9m/s")
    def test_014_display_white(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 014: 不超限, 白字显示 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=4.9"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_4_9), "更新风速信息失败"

        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_4_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_4_9, label="014")
            _assert_wind_speed_warning(dgcs_app, log_manager, False, label="014")
            allure.attach("预期: 风速=4.9m/s, 白色, 无告警弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 014 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("风速信息显示")
    @allure.title("015: wy=5.0m/s (一级超限) → 右上角红字显示 5.0m/s")
    def test_015_display_red_level1(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 015: 一级超限, 红字显示 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=5.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="015")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="015")
            allure.attach("预期: 风速=5.0m/s, 红色, 一级告警弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 015 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("风速信息显示")
    @allure.title("016: wy=8.0m/s (二级超限) → 右上角红字显示 8.0m/s")
    def test_016_display_red_level2(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 016: 二级超限, 红字显示 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=8.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_8_0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_8_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="016")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="016")
            allure.attach("预期: 风速=8.0m/s, 红色, 二级告警弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 016 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("风速信息显示")
    @allure.title("017: wy=12.0m/s (三级超限) → 右上角红字显示 12.0m/s")
    def test_017_display_red_level3(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 017: 三级超限, 红字显示 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=12.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_12_0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_12_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_12_0, label="017")
            _assert_wind_speed_warning(dgcs_app, log_manager, 3, label="017")
            allure.attach("预期: 风速=12.0m/s, 红色, 三级告警弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 017 完成 ======")

    # ==================================================================
    # 分类五：告警弹窗升降级逻辑 (018 ~ 022)
    # ==================================================================

    @allure.feature("风速超限预警")
    @allure.story("告警升降级逻辑")
    @allure.title("018: 一级→关闭→二级(升级) → 弹窗显示二级告警")
    def test_018_upgrade_level(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 018: L1→关闭弹窗→L2 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("1.发送 wy=5.0 (一级告警)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="018-发送5.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="018-发送5.0后")
            allure.attach("手动操作: 查看弹窗 → 关闭弹窗", "步骤1")
            _assert_click_windspeed_warning_close(dgcs_app, log_manager, label="018-点击'关闭'按钮关闭一级告警弹窗")

        with allure.step("2.发送 wy=8.0 (二级告警 → 升级)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_8_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_8_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="018-发送8.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="018-发送8.0后")

        with allure.step("验证"):
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="018-最终验证")
            allure.attach("预期: 触发二级告警弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 018 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("告警升降级逻辑")
    @allure.title("019: 二级→关闭→等2分钟→一级(降级, <3min) → 不弹窗")
    def test_019_downgrade_within_3min(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 019: L2→关闭→2min→L1 (降级<3min) =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("1.发送 wy=8.0 (二级告警)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_8_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_8_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="019-发送8.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="019-发送8.0后")
            allure.attach("手动操作: 查看弹窗 → 关闭弹窗", "步骤1")
            _assert_click_windspeed_warning_close(dgcs_app, log_manager, label="019-点击'关闭'按钮关闭二级告警弹窗")
            time.sleep(120)

        with allure.step("2.发送 wy=5.0 (一级 → 降级, <3min)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="019-发送5.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, False, label="019-发送5.0后")

        with allure.step("验证"):
            _assert_wind_speed_warning(dgcs_app, log_manager, False, label="019-最终验证")
            allure.attach("预期: 风速=5.0m/s, 红色, 无告警弹窗(降级且距上次<3分钟)", "期望结果")
        log_manager.logger.info("[TEST] ====== 019 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("告警升降级逻辑")
    @allure.title("020: 一级→关闭→等2分钟→一级(同级, <3min) → 不弹窗")
    def test_020_same_level_within_3min(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 020: L1→关闭→2min→L1 (同级<3min) =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("1.发送 wy=5.0 (一级告警)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="020-发送5.0后(step1)")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="020-发送5.0后(step1)")
            _assert_click_windspeed_warning_close(dgcs_app, log_manager, label="020-点击'关闭'按钮关闭一级告警弹窗")
            allure.attach("自动操作: 查看弹窗 → 关闭弹窗", "关闭告警弹窗后等待 2 分钟...")
            time.sleep(120)

        with allure.step("2.发送 wy=5.0 (一级 → 同级, <3min)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="020-发送5.0后(step2)")
            _assert_wind_speed_warning(dgcs_app, log_manager, False, label="020-发送5.0后(step2)")

        with allure.step("验证"):
            _assert_wind_speed_warning(dgcs_app, log_manager, False, label="020-最终验证")
            allure.attach("预期: 风速=5.0m/s, 红色, 无告警弹窗(同级且距上次<3分钟)", "期望结果")
        log_manager.logger.info("[TEST] ====== 020 完成 ======")


    @allure.feature("风速超限预警")
    @allure.story("告警升降级逻辑")
    @allure.title("021: 二级→关闭→等3分钟→一级(降级, >3min) → 弹窗显示一级")
    def test_021_downgrade_over_3min(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 021: L2→关闭→3min→L1 (降级>3min) =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("1.发送 wy=8.0 (二级告警)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_8_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_8_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="021-发送8.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="021-发送8.0后")
            _assert_click_windspeed_warning_close(dgcs_app, log_manager, label="021-点击'关闭'按钮关闭二级告警弹窗")

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_4_9), "更新风速信息失败"

            allure.attach("自动操作: 查看弹窗 → 关闭弹窗", "关闭告警弹窗后等待 3 分钟...")
            time.sleep(180)

        with allure.step("2.发送 wy=5.0 (一级 → 降级, >3min)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="021-发送5.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="021-发送5.0后")

        with allure.step("验证"):
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="021-最终验证")
            allure.attach("预期: 风速=5.0m/s, 红色, 一级告警弹窗(距上次>3分钟)", "期望结果")
        log_manager.logger.info("[TEST] ====== 021 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("告警升降级逻辑")
    @allure.title("022: 一级→关闭→等3分钟→一级(同级, >3min) → 弹窗显示一级")
    def test_022_same_level_over_3min(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 022: L1→关闭→3min→L1 (同级>3min) =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("1.发送 wy=5.0 (一级告警)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="022-发送5.0后(step1)")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="022-发送5.0后(step1)")
            _assert_click_windspeed_warning_close(dgcs_app, log_manager, label="022-点击'关闭'按钮关闭一级告警弹窗")
            allure.attach("自动操作: 查看弹窗 → 关闭弹窗", "关闭告警弹窗后等待 3 分钟...")
            time.sleep(180)

        with allure.step("2.发送 wy=5.0 (一级 → 同级, >3min)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="022-发送5.0后(step2)")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="022-发送5.0后(step2)")

        with allure.step("验证"):
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="022-最终验证")
            allure.attach("预期: 风速=5.0m/s, 红色, 一级告警弹窗(距上次>3分钟)", "期望结果")
        log_manager.logger.info("[TEST] ====== 022 完成 ======")

    # ==================================================================
    # 分类六：弹窗为非模态窗口 (023)
    # ==================================================================

    @allure.feature("风速超限预警")
    @allure.story("弹窗非模态")
    @allure.title("023: 告警弹窗为非模态 → 允许操作剧本映射等其他功能")
    def test_023_non_modal_dialog(self, dgcs_app, log_manager, dgcs_drama_file):
        log_manager.logger.info("[TEST] ====== 023: 弹窗非模态 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("1.发送 wy=5.0 (触发一级告警)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="023")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="023")

        with allure.step("2.验证"):
            # ====== 加载剧本文件 ======
            assert dgcs_drama_file, "未提供 --dgcs-drama-file"
            assert os.path.exists(dgcs_drama_file), f"剧本文件不存在: {dgcs_drama_file}"
            assert dgcs_app.load_drama(filename=dgcs_drama_file, wait_time=5), \
                f"剧本加载失败: {dgcs_drama_file}"
        log_manager.logger.info("[TEST] ====== 023 完成 ======")

    # ==================================================================
    # 分类七：最多显示一个弹窗 (024)
    # ==================================================================

    @allure.feature("风速超限预警")
    @allure.story("弹窗唯一性")
    @allure.title("024: 新告警弹窗覆盖旧弹窗")
    def test_024_single_popup(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 024: 弹窗覆盖 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("1.发送 wy=5.0 (一级告警)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="024-发送5.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="024-发送5.0后")

        with allure.step("2.发送 wy=8.0 (二级告警 → 覆盖)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_8_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_8_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="024-发送8.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="024-发送8.0后")

        with allure.step("验证"):
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="024-最终验证")
            allure.attach("预期: 仅一个二级告警弹窗", "期望结果")
            _assert_click_windspeed_warning_close(dgcs_app, log_manager, label="024-点击'关闭'按钮关闭二级告警弹窗")
            _assert_wind_speed_warning(dgcs_app, log_manager, False, label="024-最终再次验证")
            allure.attach("预期: 关闭二级告警弹窗后无弹窗", "期望结果")
        log_manager.logger.info("[TEST] ====== 024 完成 ======")

    # ==================================================================
    # 分类八：中文告警信息 (025 ~ 027)
    # ==================================================================

    @allure.feature("风速超限预警")
    @allure.story("中文告警信息")
    @allure.title("025: 一级告警中文信息")
    def test_025_chinese_message_level1(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 025: 中文告警-一级 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=5.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            expected_text = f"当前风速{expected_speed} m/s，超过了1级告警风速5.0m/s，请注意大风影响"
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="025")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, expected_text=expected_text, label="025")

        log_manager.logger.info("[TEST] ====== 025 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("中文告警信息")
    @allure.title("026: 二级告警中文信息")
    def test_026_chinese_message_level2(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 026: 中文告警-二级 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=8.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_8_0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_8_0)
            expected_text = f"当前风速{expected_speed} m/s，超过了2级告警风速8.0 m/s，请注意大风影响"
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="026")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, expected_text=expected_text, label="026")

        log_manager.logger.info("[TEST] ====== 026 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("中文告警信息")
    @allure.title("027: 三级告警中文信息")
    def test_027_chinese_message_level3(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 027: 中文告警-三级 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送 wy=12.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_12_0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_12_0)
            expected_text = f"当前风速{expected_speed} m/s，超过了3级告警风速12.0 m/s，请注意大风影响"
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_12_0, label="027")
            _assert_wind_speed_warning(dgcs_app, log_manager, 3, expected_text=expected_text, label="027")

        log_manager.logger.info("[TEST] ====== 027 完成 ======")

    # ==================================================================
    # 分类九：英文告警信息 (028 ~ 030)
    # ==================================================================

    @allure.feature("风速超限预警")
    @allure.story("英文告警信息")
    @allure.title("028: 一级告警英文信息")
    def test_028_english_message_level1(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 028: 英文告警-一级 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("切换语言为英文"):
            assert dgcs_app.click_othermenu_language_switch_button("English"), "语言未切换成功"

        with allure.step("发送 wy=5.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            expected_text = f"Wind speed is {expected_speed} m/s, which exceeds the level 1 windspeed risk threshold of 5.0 m/s. Be aware of changing wind conditions."
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="028")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, expected_text=expected_text, label="028")

        with allure.step("切换语言为中文"):
            assert dgcs_app.click_othermenu_language_switch_button("Chinese"), "语言未切换成功"

        log_manager.logger.info("[TEST] ====== 028 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("英文告警信息")
    @allure.title("029: 二级告警英文信息")
    def test_029_english_message_level2(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 029: 英文告警-二级 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("切换语言为英文"):
            assert dgcs_app.click_othermenu_language_switch_button("English"), "语言未切换成功"

        with allure.step("发送 wy=8.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_8_0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_8_0)
            expected_text = f"Wind speed is {expected_speed} m/s, which exceeds the level 2 windspeed risk threshold of 8.0 m/s. Be aware of changing wind conditions."
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="029")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, expected_text=expected_text, label="029")

        with allure.step("切换语言为中文"):
            assert dgcs_app.click_othermenu_language_switch_button("Chinese"), "语言未切换成功"

        log_manager.logger.info("[TEST] ====== 029 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("英文告警信息")
    @allure.title("030: 三级告警英文信息")
    def test_030_english_message_level3(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 030: 英文告警-三级 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("切换语言为英文"):
            assert dgcs_app.click_othermenu_language_switch_button("English"), "语言未切换成功"

        with allure.step("发送 wy=12.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_12_0), "更新风速信息失败"
            
        with allure.step("验证"):
            expected_speed = _calc_expected_wind_speed(0, WIND_12_0)
            expected_text = f"Wind speed is {expected_speed} m/s, which exceeds the level 3 windspeed risk threshold of 12.0 m/s. Be aware of changing wind conditions."
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_12_0, label="030")
            _assert_wind_speed_warning(dgcs_app, log_manager, 3, expected_text=expected_text, label="030")

        with allure.step("切换语言为中文"):
            assert dgcs_app.click_othermenu_language_switch_button("Chinese"), "语言未切换成功"

        log_manager.logger.info("[TEST] ====== 030 完成 ======")

    # ==================================================================
    # 分类十：弹窗消失/持续 (031 ~ 033)
    # ==================================================================

    @allure.feature("风速超限预警")
    @allure.story("弹窗交互")
    @allure.title("031: 点击「我知道了」按钮 → 弹窗关闭")
    def test_031_dismiss_by_button(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 031: 点击「我知道了」关闭弹窗 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("1.发送 wy=5.0 (触发一级告警)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="031")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="031-按下'我知道了'按钮前一级告警弹窗状态")

        with allure.step("2.点击「我知道了」按钮"):
            _assert_click_windspeed_warning_iknow(dgcs_app, log_manager, label="031-点击'我知道了'按钮关闭一级告警弹窗")
            _assert_wind_speed_warning(dgcs_app, log_manager, False, label="031-按下'我知道了'按钮后一级告警弹窗状态")
        log_manager.logger.info("[TEST] ====== 031 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("弹窗交互")
    @allure.title("032: 点击「关闭」按钮 → 弹窗关闭")
    def test_032_dismiss_by_close(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 032: 点击「关闭」按钮 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("1.发送 wy=5.0 (触发一级告警)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="032")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="032-按下'关闭'按钮前一级告警弹窗状态")

        with allure.step("2.点击「关闭」按钮"):
            _assert_click_windspeed_warning_close(dgcs_app, log_manager, label="032-点击'关闭'按钮关闭一级告警弹窗")
            _assert_wind_speed_warning(dgcs_app, log_manager, False, label="032-按下'关闭'按钮后一级告警弹窗状态")
        log_manager.logger.info("[TEST] ====== 032 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("弹窗交互")
    @allure.title("033: 不点击按钮 → 弹窗持续存在(10分钟)")
    def test_033_popup_persists(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 033: 弹窗持续存在 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("1.发送 wy=5.0 (触发一级告警)"):
            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="033")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="033-等待10min前一级告警弹窗状态")
            time.sleep(600)

        with allure.step("2.验证"):
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="033-等待10min后一级告警弹窗状态")
        log_manager.logger.info("[TEST] ====== 033 完成 ======")


# ======================================================================
# 分类十一：多飞机风速取最大值 (034 ~ 037)
# 需要两个 FakeAirplane 实例，使用独立的 fixture
# ======================================================================

@pytest.mark.functional
class TestWindSpeedMultiAircraft:
    """多飞机风速超限预警测试 - 验证多台无人机时取最大风速."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, dgcs_app, log_manager, mavlink_version):
        self.mavlink_version = mavlink_version

        if dgcs_app.start_app():
            log_manager.logger.info("[TEST] ====== 启动 DGCS 应用 ======")
            dgcs_app.click_login()
            success = dgcs_app.check_login_success(wait_time=10)
            if not success:
                log_manager.logger.info("[TEST] ====== DGCS 登录失败，跳过登录后测试 ======")
                pytest.skip("DGCS 登录失败，跳过登录后测试")
            else:
                log_manager.logger.info("[TEST] ====== DGCS 登录成功 ======")
            # 登录后可能需要等待主窗口就绪并处理常见弹窗
            dgcs_app.check_main_window_waiting(wait_time=3)
            dgcs_app.check_battery_warming(wait_time=3)
        else:
            if not dgcs_app.check_login_window():
                log_manager.logger.info("[TEST] ====== 无法启动 DGCS 应用 ======")
                pytest.skip(f"无法启动 DGCS 应用")
            else:
                if dgcs_app.check_main_window():
                    log_manager.logger.info("[TEST] ====== 已启动 DGCS 应用 ======")

        log_manager.logger.info("[TEST] ====== 初始化两架假飞机 ======")
        with allure.step("初始化假飞机 1"):
            self.fake_plane_1 = FakeAirplane(mavlink_version=self.mavlink_version)
            log_manager.logger.info(f"[TEST] 假飞机1: {self.fake_plane_1.local_ip}:{self.fake_plane_1.local_port}")
            allure.attach(
                f"假飞机1: {self.fake_plane_1.local_ip}:{self.fake_plane_1.local_port}",
                "假飞机1"
            )
            with allure.step("假飞机 1自动响应地面站发送 id=1 extend=1 请求"):
                self.wind_sender_1 = _WindSpeedSender(log_manager, self.fake_plane_1, addr=(self.fake_plane_1.ground_station_ip, self.fake_plane_1.ground_station_port))
        with allure.step("初始化假飞机 2"):
            # 第二架飞机使用不同的端口
            self.fake_plane_2 = FakeAirplane(mavlink_version=self.mavlink_version, ip_addr="172.16.3.182", interface="WLAN 8", local_port=14551)
            log_manager.logger.info(f"[TEST] 假飞机2: {self.fake_plane_2.local_ip}:{self.fake_plane_2.local_port}")
            allure.attach(
                f"假飞机2: {self.fake_plane_2.local_ip}:{self.fake_plane_2.local_port}",
                "假飞机2"
            )
            with allure.step("假飞机 2自动响应地面站发送 id=1 extend=1 请求"):
                self.wind_sender_2 = _WindSpeedSender(log_manager, self.fake_plane_2, addr=(self.fake_plane_2.ground_station_ip, self.fake_plane_2.ground_station_port))
        yield
        with allure.step("清理测试资源"):
            if dgcs_app.check_windspeed_warning_window():
                dgcs_app.click_windspeed_warning_close_window()
            log_manager.logger.info("[TEST] ====== 清理资源 ======")
            self.wind_sender_1.stop()
            self.wind_sender_2.stop()
            self.fake_plane_1.close()
            self.fake_plane_2.close()
            allure.attach("资源已清理", "清理信息")
            # teardown：关闭应用
            try:
                dgcs_app.close_app()
                log_manager.logger.info("[TEST] ====== 关闭应用 ======")
            except Exception as exc:
                # 终止进程作为兜底
                try:
                    dgcs_app.ui.terminate_process()
                    log_manager.logger.info("[TEST] ====== 终止进程 ======")
                except Exception:
                    pass

    def _do_handshake(self, fake_planes, log_manager):
        """执行 MAVLink 握手：心跳 → 收 id=3 → 发 id=2 → 收 id=1(extend=1) → 返回 addr."""
        gcs_ip = fake_planes[0].ground_station_ip
        gcs_port = fake_planes[0].ground_station_port

        with allure.step("发送心跳 (id=0)"):
            # 不可注释，保证飞机一定处于下线状态
            log_manager.logger.info("不可注释，保证飞机一定处于下线状态")
            time.sleep(10)

            log_manager.logger.info("[TEST] 步骤1: 发送心跳")
            msg = MAVLink_message(msg_id=0, sys_id=1, comp_id=1, seq=0,
                                  version=self.mavlink_version, fields={'mavlink_version': 37})
            for fake_plane in fake_planes:
                fake_plane.send(msg, addr=(gcs_ip, gcs_port))

        with allure.step("等待地面站发送 id=3 请求"):
            log_manager.logger.info("[TEST] 步骤2: 等待 id=3 (timeout=30s)")
            start = time.time()
            received = None
            for fake_plane in fake_planes:
                while time.time() - start < 30.0:
                    received, addr = fake_plane.receive()
                    if received is not None:
                        log_manager.logger.info(f"[TEST] 收到 msg_id={received.msg_id} from={addr}")
                        if received.msg_id == 3:
                            allure.attach(_format_msg_detail(received), f"收到 id=3 请求 ({gcs_ip})")
                            break
                        elif received.msg_id == 0:
                            continue
                    time.sleep(0.05)
                assert received is not None, "未接收到地面站的 id=3 请求"
                assert received.msg_id == 3, f"期望 msg_id=3, 实际={received.msg_id}"

        with allure.step("发送 id=2 身份信息"):
            log_manager.logger.info("[TEST] 步骤3: 发送 id=2")
            msg = MAVLink_message(msg_id=2, seq=28, sys_id=0,
                                  fields={'serial': "123", 'code': "123"})
            for fake_plane in fake_planes:
                fake_plane.send(msg, addr=(gcs_ip, gcs_port))
            time.sleep(0.05)

        with allure.step("等待地面站发送 id=1 (extend=1) 请求"):
            log_manager.logger.info("[TEST] 步骤4: 等待 id=1 extend=1 (timeout=30s)")
            start = time.time()
            received = None
            ground_addr = None
            for fake_plane in fake_planes:
                while time.time() - start < 30.0:
                        received, ground_addr = fake_plane.receive()
                        if received is not None:
                            log_manager.logger.info(f"[TEST] 收到 msg_id={received.msg_id} from={ground_addr}")
                            if received.msg_id == 1:
                                allure.attach(_format_msg_detail(received),
                                            f"收到 id=1 请求 ({ground_addr})")
                                break
                            elif received.msg_id == 0:
                                continue
                        time.sleep(0.05)
                assert received is not None, f"{fake_plane.target_ip}未接收到地面站的 id=1 请求"
                assert received.msg_id == 1, f"期望 msg_id=1, 实际={received.msg_id}"

        with allure.step("开启心跳报文监控线程"):
            self.wind_sender_1.start()
            self.wind_sender_2.start()

        return True

    # ------------------------------------------------------------------
    @allure.feature("风速超限预警")
    @allure.story("多飞机风速")
    @allure.title("034: 飞机1=5.0m/s, 飞机2=8.0m/s → 显示 8.0m/s (取最大)")
    def test_034_two_aircraft_max_8(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 034: 双飞机, max=8.0 =====")
        assert self._do_handshake([self.fake_plane_1, self.fake_plane_2], log_manager), "假飞机1/2与地面站握手失败"
        # 展示无人机列表视图
        dgcs_app.open_uav_view_meau_list()

        with allure.step("飞机1: wy=5.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender_1, 0, WIND_5_0), "更新风速信息失败"
            assert _send_wind_speed_async(log_manager, self.wind_sender_2, 0, 0), "更新风速信息失败"
            expected_speed = _calc_max_wind_speed([(0, WIND_5_0)])
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="034-飞机1发送5.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 1, label="034-飞机1发送5.0后")

        with allure.step("等待 2 分钟"):
            time.sleep(120)

        with allure.step("飞机2: wy=8.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender_1, 0, WIND_5_0), "更新风速信息失败"
            assert _send_wind_speed_async(log_manager, self.wind_sender_2, 0, WIND_8_0), "更新风速信息失败"
            expected_speed = _calc_max_wind_speed([(0, WIND_5_0), (0, WIND_8_0)])
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="034-飞机2发送8.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="034-飞机2发送8.0后")

        with allure.step("验证"):
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="034-最终验证")
        log_manager.logger.info("[TEST] ====== 034 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("多飞机风速")
    @allure.title("035: 飞机1=8.0m/s, 飞机2=12.0m/s → 显示 12.0m/s")
    def test_035_two_aircraft_max_12(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 035: 双飞机, max=12.0 =====")
        assert self._do_handshake([self.fake_plane_1, self.fake_plane_2], log_manager), "假飞机1/2与地面站握手失败"
        # 展示无人机列表视图
        dgcs_app.open_uav_view_meau_list()

        with allure.step("飞机1: wy=8.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender_1, 0, WIND_8_0), "更新风速信息失败"
            assert _send_wind_speed_async(log_manager, self.wind_sender_2, 0, 0), "更新风速信息失败"
            expected_speed = _calc_max_wind_speed([(0, WIND_8_0)])
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="035-飞机1发送8.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="035-飞机1发送8.0后")

        with allure.step("等待 2 分钟"):
            time.sleep(120)

        with allure.step("飞机2: wy=12.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender_1, 0, WIND_8_0), "更新风速信息失败"
            assert _send_wind_speed_async(log_manager, self.wind_sender_2, 0, WIND_12_0), "更新风速信息失败"
            expected_speed = _calc_max_wind_speed([(0, WIND_8_0), (0, WIND_12_0)])
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_12_0, label="035-飞机2发送12.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 3, label="035-飞机2发送12.0后")

        with allure.step("验证"):
            _assert_wind_speed_warning(dgcs_app, log_manager, 3, label="035-最终验证")
        log_manager.logger.info("[TEST] ====== 035 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("多飞机风速")
    @allure.title("036: 飞机1=12.0m/s, 飞机2=8.0m/s → 显示 12.0m/s (取最大)")
    def test_036_two_aircraft_max_12_reverse(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 036: 双飞机(反向), max=12.0 =====")
        assert self._do_handshake([self.fake_plane_1, self.fake_plane_2], log_manager), "假飞机1/2与地面站握手失败"
        # 展示无人机列表视图
        dgcs_app.open_uav_view_meau_list()

        with allure.step("飞机1: wy=12.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender_1, 0, WIND_12_0), "更新风速信息失败"
            assert _send_wind_speed_async(log_manager, self.wind_sender_2, 0, 0), "更新风速信息失败"
            expected_speed = _calc_max_wind_speed([(0, WIND_12_0)])
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_12_0, label="036-飞机1发送12.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 3, label="036-飞机1发送12.0后")

        with allure.step("等待 2 分钟"):
            time.sleep(120)

        with allure.step("飞机2: wy=8.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender_1, 0, WIND_12_0), "更新风速信息失败"
            assert _send_wind_speed_async(log_manager, self.wind_sender_2, 0, WIND_8_0), "更新风速信息失败"
            expected_speed = _calc_max_wind_speed([(0, WIND_12_0), (0, WIND_8_0)])
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_12_0, label="036-飞机2发送8.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 3, label="036-飞机2发送8.0后")

        with allure.step("验证"):
            _assert_wind_speed_warning(dgcs_app, log_manager, 3, label="036-最终验证")
        log_manager.logger.info("[TEST] ====== 036 完成 ======")

    @allure.feature("风速超限预警")
    @allure.story("多飞机风速")
    @allure.title("037: 飞机1=8.0m/s, 飞机2=5.0m/s → 显示 8.0m/s (取最大)")
    def test_037_two_aircraft_max_8_reverse(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== 037: 双飞机(反向), max=8.0 =====")
        assert self._do_handshake([self.fake_plane_1, self.fake_plane_2], log_manager), "假飞机1/2与地面站握手失败"
        # 展示无人机列表视图
        dgcs_app.open_uav_view_meau_list()

        with allure.step("飞机1: wy=8.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender_1, 0, WIND_8_0), "更新风速信息失败"
            assert _send_wind_speed_async(log_manager, self.wind_sender_2, 0, 0), "更新风速信息失败"
            expected_speed = _calc_max_wind_speed([(0, WIND_8_0)])
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="037-飞机1发送8.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="037-飞机1发送8.0后")

        with allure.step("等待 2 分钟"):
            time.sleep(120)

        with allure.step("飞机2: wy=5.0"):
            assert _send_wind_speed_async(log_manager, self.wind_sender_1, 0, WIND_8_0), "更新风速信息失败"
            assert _send_wind_speed_async(log_manager, self.wind_sender_2, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_max_wind_speed([(0, WIND_8_0), (0, WIND_5_0)])
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="037-飞机2发送5.0后")
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="037-飞机2发送5.0后")

        with allure.step("验证"):
            _assert_wind_speed_warning(dgcs_app, log_manager, 2, label="037-最终验证")
        log_manager.logger.info("[TEST] ====== 037 完成 ======")

@pytest.mark.functional
class TestWindSpeedFixedBug:
    """风速超限预警功能测试 - 与真实地面站交互."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, dgcs_app, log_manager, request: pytest.FixtureRequest, mavlink_version):
        self.mavlink_version = mavlink_version

        if dgcs_app.start_app():
            log_manager.logger.info("[TEST] ====== 启动 DGCS 应用 ======")
            dgcs_app.click_login()
            success = dgcs_app.check_login_success(wait_time=10)
            if not success:
                log_manager.logger.info("[TEST] ====== DGCS 登录失败，跳过登录后测试 ======")
                pytest.skip("DGCS 登录失败，跳过登录后测试")
            else:
                log_manager.logger.info("[TEST] ====== DGCS 登录成功 ======")
            # 登录后可能需要等待主窗口就绪并处理常见弹窗
            dgcs_app.check_main_window_waiting(wait_time=3)
            dgcs_app.check_battery_warming(wait_time=3)
        else:
            if not dgcs_app.check_login_window():
                log_manager.logger.info("[TEST] ====== 无法启动 DGCS 应用 ======")
                pytest.skip(f"无法启动 DGCS 应用")
            else:
                if dgcs_app.check_main_window():
                    log_manager.logger.info("[TEST] ====== 已启动 DGCS 应用 ======")

        log_manager.logger.info("[TEST] ====== 初始化假飞机 ======")
        with allure.step("初始化假飞机"):
            self.fake_plane = FakeAirplane(mavlink_version=self.mavlink_version)
            log_manager.logger.info(f"[TEST] 假飞机: {self.fake_plane.local_ip}:{self.fake_plane.local_port}")
            log_manager.logger.info(f"[TEST] 地面站: {self.fake_plane.ground_station_ip}:{self.fake_plane.ground_station_port}")
            allure.attach(
                f"假飞机: {self.fake_plane.local_ip}:{self.fake_plane.local_port}\n"
                f"地面站: {self.fake_plane.ground_station_ip}:{self.fake_plane.ground_station_port}",
                "连接信息"
            )
            with allure.step("自动响应地面站发送 id=1 extend=1 请求"):
                self.wind_sender = _WindSpeedSender(log_manager, self.fake_plane, addr=(self.fake_plane.ground_station_ip, self.fake_plane.ground_station_port))
            log_manager.logger.info(f"[TEST] 假飞机: {self.fake_plane.local_ip}:{self.fake_plane.local_port}")
            log_manager.logger.info(f"[TEST] 地面站: {self.fake_plane.ground_station_ip}:{self.fake_plane.ground_station_port}")
        yield
        with allure.step("清理测试资源"):
            if dgcs_app.check_windspeed_warning_window():
                dgcs_app.click_windspeed_warning_close_window()
            log_manager.logger.info("[TEST] ====== 清理资源 ======")
            self.wind_sender.stop()
            self.fake_plane.close()
            allure.attach("资源已清理", "清理信息")
            # teardown：关闭应用
            try:
                dgcs_app.close_app()
                log_manager.logger.info("[TEST] ====== 关闭应用 ======")
            except Exception as exc:
                # 终止进程作为兜底
                try:
                    dgcs_app.ui.terminate_process()
                    log_manager.logger.info("[TEST] ====== 终止进程 ======")
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # 协议握手
    # ------------------------------------------------------------------
    def _do_handshake(self, log_manager):
        """执行 MAVLink 握手：心跳 → 收 id=3 → 发 id=2 → 收 id=1(extend=1) → 返回 addr."""
        gcs_ip = self.fake_plane.ground_station_ip
        gcs_port = self.fake_plane.ground_station_port

        with allure.step("发送心跳 (id=0)"):
            time.sleep(10)

            log_manager.logger.info("[TEST] 步骤1: 发送心跳")
            msg = MAVLink_message(msg_id=0, sys_id=1, comp_id=1, seq=0,
                                  version=self.mavlink_version, fields={'mavlink_version': 37})
            self.fake_plane.send(msg, addr=(gcs_ip, gcs_port))

        with allure.step("等待地面站发送 id=3 请求"):
            log_manager.logger.info("[TEST] 步骤2: 等待 id=3 (timeout=30s)")
            start = time.time()
            received = None
            while time.time() - start < 30.0:
                received, addr = self.fake_plane.receive()
                if received is not None:
                    log_manager.logger.info(f"[TEST] 收到 msg_id={received.msg_id} from={addr}")
                    if received.msg_id == 3:
                        allure.attach(_format_msg_detail(received), f"收到 id=3 请求 ({gcs_ip})")
                        break
                    elif received.msg_id == 0:
                        continue
                time.sleep(0.1)
            assert received is not None, "未接收到地面站的 id=3 请求"
            assert received.msg_id == 3, f"期望 msg_id=3, 实际={received.msg_id}"

        with allure.step("发送 id=2 身份信息"):
            log_manager.logger.info("[TEST] 步骤3: 发送 id=2")
            msg = MAVLink_message(msg_id=2, seq=28, sys_id=0,
                                  fields={'serial': "123", 'code': "123"})
            self.fake_plane.send(msg, addr=(gcs_ip, gcs_port))
            time.sleep(0.3)

        with allure.step("等待地面站发送 id=1 (extend=1) 请求"):
            log_manager.logger.info("[TEST] 步骤4: 等待 id=1 extend=1 (timeout=30s)")
            start = time.time()
            received = None
            ground_addr = None
            while time.time() - start < 30.0:
                received, ground_addr = self.fake_plane.receive()
                if received is not None:
                    log_manager.logger.info(f"[TEST] 收到 msg_id={received.msg_id} from={ground_addr}")
                    if received.msg_id == 1:
                        allure.attach(_format_msg_detail(received),
                                      f"收到 id=1 请求 ({ground_addr})")
                        break
                    elif received.msg_id == 0:
                        continue
                time.sleep(0.1)
            assert received is not None, "未接收到地面站的 id=1 请求"
            assert received.msg_id == 1, f"期望 msg_id=1, 实际={received.msg_id}"

        with allure.step("开启心跳报文监控线程"):
            self.wind_sender.start()

        return True

    # ==================================================================
    # 分类十二：缺陷回归测试 (bug001)
    # ==================================================================

    @allure.feature("风速超限预警")
    @allure.story("缺陷回归测试")
    @allure.title("bug001: 风速字体颜色变化与恢复")
    def test_bug001_color_change(self, dgcs_app, log_manager):
        log_manager.logger.info("[TEST] ====== bug001: 风速字体颜色变化与恢复 =====")
        assert self._do_handshake(log_manager), "假飞机与地面站握手失败"

        with allure.step("发送风速 wx=0, wy=5.0，风速一级告警后恢复"):

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, 0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, 0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, 0, label="bug001-飞机1发送0.0后")

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_4_9), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_4_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_4_9, label="bug001-飞机1发送4.9后")

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="bug001-飞机1发送5.0后")

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_4_9), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_4_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_4_9, label="bug001-飞机1再次发送4.9后")

        with allure.step("发送风速 wx=0, wy=8.0，风速二级告警后恢复"):

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_7_9), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_7_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_7_9, label="bug001-飞机1发送7.9后")

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_8_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_8_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_8_0, label="bug001-飞机1发送8.0后")

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_7_9), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_7_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_7_9, label="bug001-飞机1再次发送7.9后")

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="bug001-飞机1发送5.0后")

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_4_9), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_4_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_4_9, label="bug001-飞机1再次发送4.9后")

        with allure.step("发送风速 wx=0, wy=12.0，风速三级告警后恢复"):

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_11_9), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_11_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_11_9, label="bug001-飞机1发送11.9后")

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_12_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_12_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_12_0, label="bug001-飞机1发送12.0后")

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_11_9), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_11_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_11_9, label="bug001-飞机1再次发送11.9后")

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_5_0), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_5_0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_5_0, label="bug001-飞机1发送5.0后")

            assert _send_wind_speed_async(log_manager, self.wind_sender, 0, WIND_4_9), "更新风速信息失败"
            expected_speed = _calc_expected_wind_speed(0, WIND_4_9)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, WIND_4_9, label="bug001-飞机1再次发送4.9后")

        with allure.step("验证"):
            self.fake_plane.close()
            self.wind_sender.stop()
            time.sleep(5)
            expected_speed = _calc_expected_wind_speed(0, 0)
            _assert_wind_speed_info(dgcs_app, log_manager, expected_speed, 0, 0, label="bug001-飞机1掉线后")

        log_manager.logger.info("[TEST] ====== bug001 完成 ======")
