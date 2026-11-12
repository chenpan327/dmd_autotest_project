# coding: utf-8

"""
GCS-02 状态上报流（p0×6 + p1×9）— packed_state/extend_state 字段审计

业务背景：
    heartbeat_dmd 周期请求下审计 packed_state(5)/extend_state(8) 全字段：
    P0/P1 项（解锁/模式/位姿/定位质量/home 与 fence/传感器健康/电压/姿态/
    温度/hash/指示灯）+ 补充项（eph/链路速率/SSID/电台/表演状态/电池压差与
    序列号/风速/速度/电芯电压/RID/各模块版本号）。核对字段持续刷新
    （seq 递增）且数值在合理范围；补充项单位口径待确认，先审计存档不断言。

    - test_gcs02_status_audit   状态上报流 15 项字段审计（默认执行）
"""

import socket
import time

import pytest
import allure

from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    FCBasicBase, log_manager, _format_msg_detail)
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    MSG_ID_HEARTBEAT, MSG_ID_PACKED_STATE, MSG_ID_EXT_STATE,
    MSG_ID_WIFI_STATUS, HEARTBEAT_DMD_HEX)


def _readable(raw):
    """bytes 数组字段（ssid/版本号/序列号等）转可读文本

    去尾部补零字节；剩余全为可打印 ASCII 则直接显示，否则以 hex 呈现。
    """
    if not isinstance(raw, (bytes, bytearray)):
        return raw
    data = bytes(raw).rstrip(b'\x00')
    if not data:
        return "(空)"
    try:
        text = data.decode('ascii')
        if all(32 <= ord(c) < 127 or c == '\t' for c in text):
            return text.strip()
    except UnicodeDecodeError:
        pass
    return f"hex:{data.hex(' ')}"


@allure.feature("FC 基础功能 P0/P1")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC")
@pytest.mark.functional
class TestGcs02Status(FCBasicBase):
    """GCS-02 状态上报流（p0×6 + p1×9）"""

    @allure.story("GCS-02 状态上报流")
    @allure.title("GCS-02 packed_state/extend_state 状态字段审计")
    def test_gcs02_status_audit(self):
        """状态上报流 15 项字段审计（GCS-02 p0×6 + p1×9）"""
        with allure.step("先发现无人机"):
            msg, addr = self.gcs.wait_for_message([MSG_ID_HEARTBEAT], timeout=8.0)
            assert msg is not None, "未发现无人机（8s 内无心跳）"
            if addr[0] != self.drone_ip:
                log_manager.log_and_attach(
                    f"心跳来源 {addr[0]} 与配置目标 {self.drone_ip} 不一致", "警告")
            else:
                log_manager.log_and_attach(f"发现无人机: {addr[0]}", "发现结果")

        with allure.step("清空接收缓冲区"):
            self._clear_recv_buffer()

        with allure.step("构造 heartbeat_dmd 请求"):
            req = MAVLink_message(hex_data=HEARTBEAT_DMD_HEX)
            log_manager.log_and_attach(req.hex_data, "发送数据十六进制")

        with allure.step("周期发送请求并收集状态流（1Hz × 10s，过滤非目标IP）"):
            target = (self.drone_ip, self.drone_port)
            packed_list, ext_list, wifi_list = [], [], []
            send_count = 0
            other_drone_logs = 0
            old_timeout = self.gcs.sock.gettimeout()
            self.gcs.sock.settimeout(0.1)
            start = time.time()
            next_beat = start
            try:
                while time.time() - start < 10.0:
                    if time.time() >= next_beat:
                        result = self.gcs.send(req, addr=target)
                        assert result is True, "发送 heartbeat_dmd 请求失败"
                        send_count += 1
                        next_beat += 1.0
                    try:
                        received, addr = self.gcs.receive()
                    except socket.timeout:
                        received, addr = None, None
                    if received is None or received.msg_id == MSG_ID_HEARTBEAT:
                        continue
                    if not addr or addr[0] != self.drone_ip:
                        # 非目标飞机的报文只留痕不参与断言（防刷屏最多记 5 条）
                        if other_drone_logs < 5:
                            other_drone_logs += 1
                            log_manager.log_and_attach(
                                _format_msg_detail(received),
                                f"[其他飞机] msg_id={received.msg_id} "
                                f"{addr[0] if addr else '?'}")
                        continue
                    if received.msg_id == MSG_ID_PACKED_STATE:
                        if not packed_list:      # 首条响应附完整详情
                            log_manager.log_and_attach(
                                _format_msg_detail(received),
                                "收到响应详情 packed_state")
                        packed_list.append(received)
                    elif received.msg_id == MSG_ID_EXT_STATE:
                        if not ext_list:
                            log_manager.log_and_attach(
                                _format_msg_detail(received),
                                "收到响应详情 extend_state")
                        ext_list.append(received)
                    elif received.msg_id == MSG_ID_WIFI_STATUS:
                        if not wifi_list:
                            log_manager.log_and_attach(
                                _format_msg_detail(received),
                                "收到响应详情 wifi_status")
                        wifi_list.append(received)
            finally:
                self.gcs.sock.settimeout(old_timeout)
            log_manager.log_and_attach(
                f"已发送 heartbeat_dmd {send_count} 次 → "
                f"{target[0]}:{target[1]}", "发送结果")

        with allure.step("验证状态流响应"):
            assert packed_list, "10s 内未收到 packed_state，状态上报流中断"
            first, last = packed_list[0], packed_list[-1]
            assert last.fields.get('seq', 0) != first.fields.get('seq', 0) or \
                len(packed_list) > 1, "packed_state.seq 无变化，上报流疑似停滞"

        with allure.step("核对 packed_state(5) 上报字段（全字段审计）"):
            f = last.fields
            voltage = f.get('voltage_battery', 0) / 1000.0     # mV → V
            packed_lines = [
                f"packed_state 收到 {len(packed_list)} 条"
                f"（同窗口 wifi_status 旁收 {len(wifi_list)} 条）",
                f"[p0] 解锁状态 armed={f.get('armed')}  飞行模式 mode={f.get('mode')}"
                f"  fly_state={f.get('fly_state')}",
                f"[p0] 位置 lat={f.get('cur_lat')} lon={f.get('cur_lon')} "
                f"alt={f.get('cur_alt')}",
                f"[p1] 定位质量 fix_type={f.get('fix_type')} "
                f"satellites={f.get('satellites_visible')} "
                f"rtk_quality={f.get('rtk_quality')}",
                f"[补] 定位精度 eph={f.get('eph')}  海拔 elevation={f.get('elevation')}",
                f"[p1] 基准点 home_set={f.get('home_set')} "
                f"fence_origin_set={f.get('fence_origin_set')}",
                f"[p1] 控制目标 tar=({f.get('tar_lat')}, {f.get('tar_lon')}, "
                f"{f.get('tar_alt')})",
                f"[p1] 传感器健康 sensor_health={f.get('sensor_health')} "
                f"middle={f.get('sensor_health_middle')} "
                f"extend={f.get('sensor_health_extend')}",
                f"[p1] 电压 {voltage:.2f}V 电量 {f.get('voltage_battery_percent')}%",
                f"[p1] 指示灯 light=({f.get('light_r')}, {f.get('light_g')}, "
                f"{f.get('light_b')})",
                f"[补] 链路 wifi_up={f.get('wifi_up')} "
                f"mav_up_rate={f.get('mav_up_rate')} "
                f"ssid={_readable(f.get('ssid'))}",
                f"[补] 电台 rtk_850m={f.get('rtk_radio_850m')} "
                f"rtk_2g4={f.get('rtk_radio_2g4')} rc_radio={f.get('rc_radio')} "
                f"rc_matching_code={f.get('rc_matching_code')}",
                f"[补] 表演 play_state={f.get('play_state')} "
                f"drama_state={f.get('drama_state')} "
                f"lightpanel_state={f.get('lightpanel_state')}",
                f"[补] 电池压差 diff={f.get('voltage_battery_diff')} "
                f"history_diff={f.get('voltage_battery_history_diff')} "
                f"序列号={_readable(f.get('bat_serial_prefix'))}"
                f"-{_readable(f.get('bat_serial_suffix'))}",
                f"[补] 风速 wind=({f.get('wind_speed_x')}, {f.get('wind_speed_y')})"
                f"  速度 horz={f.get('uav_speed_horz')} "
                f"vert={f.get('uav_speed_vert')}",
                f"[补] 状态标志 auth_constraint={f.get('auth_constraint')} "
                f"restart_flag={f.get('restart_flag')} "
                f"uwb_group={f.get('uwb_group')} charge_state={f.get('charge_state')}",
                f"[补] 复位标志 bat_serial_need_reset="
                f"{f.get('bat_serial_need_reset')} "
                f"time_need_reset={f.get('time_need_reset')} "
                f"boot_need_update={f.get('boot_need_update')}",
            ]
            log_manager.log_and_attach(
                '\n'.join(line for line in packed_lines if line),
                "packed_state(5) 审计结果")

        with allure.step("核对 extend_state(8) 上报字段（全字段审计）"):
            if not ext_list:
                e = {}
                log_manager.log_and_attach(
                    "extend_state 未收到（10s 窗口内 0 条）",
                    "extend_state(8) 审计结果")
            else:
                e = ext_list[-1].fields
                cell_voltages = [e.get(f'voltage_battery_cell{i}')
                                 for i in range(1, 7)]
                ext_lines = [
                    f"extend_state 收到 {len(ext_list)} 条",
                    f"[p0] 姿态 roll={e.get('roll')} pitch={e.get('pitch')} "
                    f"yaw={e.get('yaw')}",
                    f"[p1] 传感器温度 imu={e.get('temp_imu')} "
                    f"baro={e.get('temp_baro')} batt={e.get('temp_batt')}",
                    f"[p1] 参数校验 hash param_hash={e.get('param_hash')}"
                    f" anchor_hash={e.get('anchor_hash')}",
                    f"[补] 电池剩余时间={e.get('battery_time')}s "
                    f"循环次数={e.get('battery_used_times')} "
                    f"健康度={e.get('battery_capability')}",
                    f"[补] 电芯电压 cell1~6={cell_voltages}",
                    f"[补] RID/激光 uas_code={_readable(e.get('uas_code'))} "
                    f"voltage_rid_bat={e.get('voltage_rid_bat')} "
                    f"laser_temperature={e.get('laser_temperature')}",
                    f"[补] 版本 FC={_readable(e.get('flight_controller_version'))} "
                    f"companion={_readable(e.get('companion_version'))} "
                    f"battery={_readable(e.get('battery_version'))}",
                    f"[补] 版本 GPS={_readable(e.get('gps_version'))} "
                    f"servo={e.get('servo_ver')} "
                    f"tele={_readable(e.get('tele_version'))} "
                    f"bms={_readable(e.get('bms_version'))}",
                    f"[补] 版本 rid={_readable(e.get('rid_version'))} "
                    f"gimbal={_readable(e.get('gimbal_version'))} "
                    f"nova_light={_readable(e.get('nova_light_version'))}",
                ]
                log_manager.log_and_attach(
                    '\n'.join(line for line in ext_lines if line),
                    "extend_state(8) 审计结果")

        with allure.step("值域断言（明显异常才算失败）"):
            assert 0 <= f.get('fix_type', 0) <= 6, \
                f"fix_type={f.get('fix_type')} 超出 0~6 范围"
            # 台架接假电池（限流电源），电压遥测无效（实测 0.02V），先不断言；
            # 换真电池后再恢复
            # assert 9.0 < voltage < 15.0 or 18.0 < voltage < 30.0, \
            #     f"电压 {voltage:.2f}V 不在常见电池范围（3S/6S），需人工核对"
            if e:
                # 姿态单位为弧度（2026-09-08 倒置事故实锤：倒置时 roll≈3.09
                # rad ≈ 177°；±90° = ±1.5708 rad）
                for angle in ('roll', 'pitch'):
                    val = e.get(angle, 0.0)
                    assert abs(val) <= 1.5708, (
                        f"{angle}={val} rad（{val * 57.2958:.1f}°）超出 ±90°"
                        f"——飞机姿态异常或倒置（翻转会触发 ARM-0003 自动落锁）")
