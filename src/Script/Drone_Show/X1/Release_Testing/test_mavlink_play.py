#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
表演报文 Release 验证测试 — UDP 通信与消息交互

业务背景：
    地面站 (GCS) 通过 UDP 向无人机发送表演控制报文 (msg_id=50)，
    控制无人机执行预设的表演动作。Release 验证覆盖端到端完整链路，
    与 Functional 测试共享相同的测试流程，侧重 Release 环境下的
    基础通过性验证。

测试对象：
    - 表演控制报文 (msg_id=50, MAVLink 1 格式, 66 字节 payload)
    - time_origin 响应 (msg_id=47) — 校准时间，用于计算 takeoff/play 时刻
    - 无人机对表演报文的响应

测试流程：
    1. 模式切换与解锁 — 发送切换模式 (msg_id=11) 和解锁 (msg_id=76) 命令
    2. 时间校准 — 发送校验时间请求，等待 time_origin 响应，计算 takeoff/play
    3. 发送表演报文 — 多次发送表演控制报文 (msg_id=50)，仅首次获得有效响应
       (result==0)，后续响应的 result 字段为非 0，视为未响应
    4. 响应验证 — 断言恰好 1 次有效响应，多次响应视为错误
    5. 收尾流程 — 结束表演 → 待机 → 恢复
"""

import pytest
import allure
import time
import socket

from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from utils.logger import log_manager


# 表演报文 (msg_id=50, MAVLink_swarm_flight_start_message) 的固定字段值
# takeoff / play / play_id 为动态计算字段，不在此定义
_PLAY_FIXED_FIELDS = {
    'takeoff_light': 0xFFFFFFFFFFFFFFFF,
    'land_light': 0xFFFFFFFFFFFFFFFF,
    'ascend': 6000,
    'descend': 6000,
    'elevation': 0,
    'return_lon': -1,
    'return_lat': -1,
    'return_elevation': -1,
    'final_mode': 6,
    'mission_id': 1,
}


def _build_play_hex(seq, takeoff, play):
    """构建表演控制报文 hex (msg_id=50, version=41)

    Args:
        seq: 报文序列号
        takeoff: 起飞时刻 (ms, 基于 time_origin 计算)
        play: 表演时刻 (ms, 基于 time_origin 计算)

    Returns:
        bytes: 编码后的 MAVLink 报文十六进制数据
    """
    import datetime

    # play_id 使用当前 UTC 毫秒时间戳，保证每次发送唯一
    play_id = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)

    fields = dict(_PLAY_FIXED_FIELDS, takeoff=takeoff, play=play, play_id=play_id)
    msg = MAVLink_message(msg_id=50, sys_id=1, comp_id=1, seq=seq,
                          fields=fields, version=41)
    return msg.pack()


def _format_msg_detail(msg):
    """解析并格式化 MAVLink 消息为可读字符串，用于日志上报"""
    import io
    import sys
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    msg.print()
    output = sys.stdout.getvalue()
    sys.stdout = old_stdout
    return output


@pytest.mark.functional
class TestMavlinkPlay:
    """MAVLink 表演报文 Release 验证测试

    多次发送表演报文，验证无人机仅首次有效响应 (result==0)，
    后续响应 result 非 0 视为未响应，断言恰好 1 次有效响应。
    流程：模式切换 → 解锁 → 时间校准 → 发送表演报文 → 等待响应 → 收尾。
    """

    @pytest.fixture(autouse=True)
    def setup_teardown(self, drone_ip, drone_port, mavlink_version):
        """测试前置：初始化地面站；后置：关闭地面站释放资源"""
        self.mavlink_version = mavlink_version
        self.drone_ip = drone_ip
        with allure.step("初始化地面站"):
            self.gcs = GroundControlStation(drone_ip=drone_ip, drone_port=drone_port)
            log_manager.log_and_attach(
                f"地面站初始化完成，本地地址: {self.gcs.local_ip}:{self.gcs.local_port}",
                "初始化信息")
        yield
        with allure.step("清理测试资源"):
            self.gcs.close()
            log_manager.log_and_attach("地面站已关闭，UDP 资源释放", "清理信息")

    def _clear_recv_buffer(self):
        """清空 UDP 接收缓冲区，避免历史消息干扰后续接收判断"""
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
        """通过心跳 (msg_id=0) 或 RID 广播 (msg_id=204) 发现局域网内无人机 IP

        Args:
            timeout: 扫描超时秒数，默认 5.0

        Returns:
            str | None: 无人机 IP 地址，未发现返回 None
        """
        old_timeout = self.gcs.recv_timeout
        self.gcs.sock.settimeout(0.1)
        start = time.time()
        try:
            while time.time() - start < timeout:
                received, addr = self.gcs.receive()
                if received is not None and received.msg_id in (0, 204):
                    log_manager.log_and_attach(f"发现无人机: {addr[0]}", "发现结果")
                    return addr[0]
                time.sleep(0.01)
            return None
        finally:
            self.gcs.recv_timeout = old_timeout
            self.gcs.sock.settimeout(old_timeout)

    @allure.feature("表演控制")
    @allure.story("表演报文发送验证")
    @allure.title("多次发送表演报文，验证仅首次有效响应")
    @allure.description(
        "Release 验证：多次发送表演控制报文 (msg_id=50)，验证无人机仅首次返回 "
        "result==0 的有效响应，后续响应 result≠0 视为未响应。"
        "流程：模式切换 → 解锁 → 时间校准 → 发送表演报文 → 等待响应 → 收尾恢复。"
        "断言恰好 1 次有效响应，多次响应视为错误。"
    )
    def test_01_repeat_send_play_message(self):
        """Release 验证：多次发送表演控制报文，断言恰好 1 次有效响应 (result==0)"""
        # ── 阶段 1: 确定目标无人机 ──
        with allure.step("目标无人机"):
            drone_ip = self.drone_ip
            log_manager.log_and_attach(f"目标无人机 IP: {drone_ip}", "目标信息")

        # ── 阶段 2: 飞行前准备 — 切换模式 + 解锁 ──
        with allure.step("发送切换模式报文 (msg_id=11, mode=4 表演模式)"):
            time.sleep(0.3)
            MODE_SWITCH_HEX = bytes.fromhex('fe060301010b040000000101df43')
            self.gcs.sock.sendto(MODE_SWITCH_HEX, (drone_ip, self.gcs.drone_port))
            log_manager.log_and_attach(
                f"切换模式报文 hex: {MODE_SWITCH_HEX.hex()} → {drone_ip}:{self.gcs.drone_port}",
                "切换模式")

        with allure.step("发送解锁报文 (msg_id=76, COMMAND_LONG cmd=183 解锁)"):
            time.sleep(0.3)
            UNLOCK_HEX = bytes.fromhex('fe21a601014c0000803f000000000000000000000000000000000000000000000000900100000087ed')
            self.gcs.sock.sendto(UNLOCK_HEX, (drone_ip, self.gcs.drone_port))
            log_manager.log_and_attach(
                f"解锁报文 hex: {UNLOCK_HEX.hex()} → {drone_ip}:{self.gcs.drone_port}",
                "解锁")

        # ── 阶段 3: 清空缓冲区，准备接收 ──
        with allure.step("清空 UDP 接收缓冲区，避免历史消息干扰"):
            self._clear_recv_buffer()

        repeat_count = 5
        send_interval = 30.0
        response_times = []

        with allure.step(f"多次发送表演报文 ({repeat_count} 次，间隔 {send_interval}s)，仅首次有效响应"):
            for i in range(repeat_count):
                # ── 步骤 1: 发送校验时间请求 (msg_id=46) ──
                time_check_hex = bytes.fromhex('fe014801012e00dff0')
                self.gcs.sock.sendto(time_check_hex, (drone_ip, self.gcs.drone_port))
                log_manager.log_and_attach(
                    f"校验时间报文 (msg_id=46) hex: {time_check_hex.hex()}",
                    f"校验时间请求 {i + 1}")

                # ── 步骤 2: 等待 time_origin 响应 (msg_id=47)，超时 2s ──
                time_value = None
                old_to = self.gcs.recv_timeout
                self.gcs.sock.settimeout(0.1)
                t_start = time.time()
                try:
                    while time.time() - t_start < 2.0:
                        received, addr = self.gcs.receive()
                        if received is not None and received.msg_id == 47:
                            if addr[0] == drone_ip:
                                time_value = received.fields.get('time', 0)
                                detail = _format_msg_detail(received)
                                log_manager.log_and_attach(
                                    detail,
                                    f"time_origin 响应: time={time_value}ms, 来自 {addr[0]}")
                                break
                            else:
                                detail = _format_msg_detail(received)
                                log_manager.log_and_attach(detail, f"[其他飞机] msg_id=47 {addr[0]}")
                        elif received is not None and received.msg_id in (0, 204):
                            continue
                        time.sleep(0.01)
                finally:
                    self.gcs.recv_timeout = old_to
                    self.gcs.sock.settimeout(old_to)
                assert time_value is not None, "未收到 time_origin 响应 (msg_id=47)"

                # ── 步骤 3: 基于 time_origin 计算 takeoff 和 play 时刻 ──
                # takeoff = time_origin + 10s, play = time_origin + 20s
                takeoff_ms = time_value + 10000
                play_ms = time_value + 20000
                log_manager.log_and_attach(
                    f"time_origin={time_value}ms → takeoff=time+10s={takeoff_ms}ms, "
                    f"play=time+20s={play_ms}ms",
                    f"时间计算 {i + 1}")

                # ── 步骤 4: 发送表演控制报文 (msg_id=50) ──
                t_send = time.time()
                play_hex = _build_play_hex(seq=i, takeoff=takeoff_ms, play=play_ms)
                self.gcs.sock.sendto(play_hex, (drone_ip, self.gcs.drone_port))
                log_manager.log_and_attach(
                    f"第{i + 1}次发送 msg_id=50 → {drone_ip}:{self.gcs.drone_port}\n"
                    f"hex: {play_hex.hex()}",
                    f"发送 {i + 1}/{repeat_count}")

                # ── 步骤 5: 等待表演响应，检查 result 字段 ──
                # result==0 为有效响应，result≠0 表示无人机不再响应表演报文
                t_recv = None
                old_to = self.gcs.recv_timeout
                self.gcs.sock.settimeout(0.1)
                t_start = time.time()
                recv_timeout = 3.0
                try:
                    while time.time() - t_start < recv_timeout:
                        received, addr = self.gcs.receive()
                        if received is not None and received.msg_id not in (0, 6, 47, 64, 204):
                            if addr[0] == drone_ip:
                                if received.msg_id == 77:
                                    result = received.fields.get('result', 0)
                                    detail = _format_msg_detail(received)
                                    if result != 0:
                                        log_manager.log_and_attach(
                                            f"{detail}\nresult={result} (非0，视为未响应)",
                                            f"第{i + 1}次响应 msg_id={received.msg_id}, 来自 {addr[0]}")
                                    else:
                                        t_recv = time.time()
                                        log_manager.log_and_attach(
                                            detail,
                                            f"第{i + 1}次响应 msg_id={received.msg_id}, 来自 {addr[0]}")
                                    break
                                else:
                                    detail = _format_msg_detail(received)
                                    log_manager.log_and_attach(detail, f"[其他响应] msg_id={received.msg_id} {addr[0]}")
                            else:
                                detail = _format_msg_detail(received)
                                log_manager.log_and_attach(detail, f"[其他飞机] msg_id={received.msg_id} {addr[0]}")
                        elif received is not None and received.msg_id in (0, 204):
                            continue
                        time.sleep(0.01)
                finally:
                    self.gcs.recv_timeout = old_to
                    self.gcs.sock.settimeout(old_to)

                if t_recv is not None:
                    elapsed = t_recv - t_send
                    response_times.append((t_send, t_recv, elapsed))
                    log_manager.log_and_attach(
                        f"第{i + 1}次: 发送={t_send:.3f}, 接收={t_recv:.3f}, "
                        f"耗时={elapsed:.3f}s",
                        f"响应时间 {i + 1}")
                else:
                    log_manager.log_and_attach(
                        f"第{i + 1}次未收到有效响应 (超时 {recv_timeout}s 或 result≠0)",
                        f"超时 {i + 1}")

                if i < repeat_count - 1:
                    time.sleep(send_interval)

        # ── 阶段 4: 验证响应结果 ──
        with allure.step("验证响应结果"):
            received_count = len(response_times)
            log_manager.log_and_attach(
                f"发送 {repeat_count} 次，收到有效响应 {received_count} 次",
                "响应统计")
            assert received_count == 1, (
                f"预期恰好 1 次有效响应，实际收到 {received_count} 次 "
                f"(发送{repeat_count}次)"
            )

        # ── 阶段 5: 收尾 — 结束表演 → 待机 → 恢复 ──
        with allure.step("等待表演完成并发送结束表演报文 (msg_id=11, mode=9 结束表演)"):
            time.sleep(30)  # 等待表演动作完成
            END_PLAY_HEX = bytes.fromhex('fe06f101010b090000000101630a')
            self.gcs.sock.sendto(END_PLAY_HEX, (drone_ip, self.gcs.drone_port))
            log_manager.log_and_attach(
                f"结束表演报文 hex: {END_PLAY_HEX.hex()} → {drone_ip}:{self.gcs.drone_port}",
                "结束表演")

        with allure.step("发送待机报文 (msg_id=76, cmd=183, 待机模式)"):
            time.sleep(0.3)
            STANDBY_HEX = bytes.fromhex('fe212101014c0000803f000000000000'
                                        '00000000000000000000000000000000'
                                        '6e9c0000008bc3')
            self.gcs.sock.sendto(STANDBY_HEX, (drone_ip, self.gcs.drone_port))
            log_manager.log_and_attach(
                f"待机报文 hex: {STANDBY_HEX.hex()} → {drone_ip}:{self.gcs.drone_port}",
                "待机")

        with allure.step("发送恢复报文 (msg_id=76, cmd=183, 恢复正常模式)"):
            time.sleep(0.3)
            RESTORE_HEX = bytes.fromhex('fe212301014c00000000000000000000'
                                        '00000000000000000000000000000000'
                                        '006e9c0000006cfa')
            self.gcs.sock.sendto(RESTORE_HEX, (drone_ip, self.gcs.drone_port))
            log_manager.log_and_attach(
                f"恢复报文 hex: {RESTORE_HEX.hex()} → {drone_ip}:{self.gcs.drone_port}",
                "恢复")
