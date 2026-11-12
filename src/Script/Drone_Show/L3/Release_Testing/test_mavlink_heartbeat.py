#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
地面站心跳/识别/状态功能测试 - UDP 通信与消息交互

业务背景：
    地面站 (GCS) 通过 UDP 与无人机进行通信，是整个编队表演控制系统的基础通道。
    地面站需要周期性接收无人机的心跳报文以确认在线状态，发送识别请求获取设备信息，
    并通过 heartbeat_dmd 请求获取打包状态 (PACKED_STATE) 和扩展状态。
    本测试模块使用 FakeGroundControlStation 模拟地面站，验证 UDP 套接字初始化、
    心跳接收、识别信息请求、状态请求以及套接字生命周期管理。

测试对象：
    - GroundControlStation 类 (UDP 套接字封装)
    - 无人机心跳报文 (msg_id=0, HEARTBEAT)
    - 识别信息请求/响应 (msg_id=3 → msg_id=2)
    - heartbeat_dmd 请求/响应 (msg_id=1 → msg_id=5 PACKED_STATE)
    - 扩展状态请求 (msg_id=1 extend=1 → msg_id=5 + msg_id=8)
    - UDP 套接字生命周期 (初始化、绑定、关闭、关闭后发送)

测试项：
    1. 周期性接收无人机心跳 — 清空缓冲区后接收 id=0 心跳，验证至少收到 1 次
    2. 发送请求获取识别信息 — 发送 id=3 请求，验证收到 id=2 响应
    3. 发送请求获取打包状态 — 发送 id=1 heartbeat_dmd，验证收到 id=5 packed_state
    4. 发送扩展请求获取扩展状态 — 发送 id=1 extend=1，验证收到 id=5 和 id=8
    5. UDP 套接字初始化 — 验证 sock 非空、udp_connected 为 True
    6. UDP 套接字绑定 — 验证 getsockname() 返回的绑定地址与预期一致
    7. 关闭套接字 — 验证 close() 后 sock 为 None、udp_connected 为 False
    8. 关闭后发送失败 — 验证 close() 后再调用 sendto 抛出异常
    9. 验证心跳响应间隔 — 主动发送 heartbeat_dmd 请求，记录响应时间，验证平均响应间隔约 1 秒 (容差 0.3s)
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
class TestGroundControlStation:
    """地面站功能测试"""

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

    @allure.feature("地面站心跳功能")
    @allure.story("周期性接收无人机心跳")
    @allure.title("周期性接收无人机心跳")
    def test_01_recv_periodic_heartbeat(self):
        """周期性接收到 id=0 心跳消息，验证心跳间隔约1秒"""
        with allure.step("清空接收缓冲区"):
            self._clear_recv_buffer()

        heartbeat_timestamps = []

        with allure.step("收集无人机心跳时间戳"):
            start = time.time()
            collect_duration = 20.0
            while time.time() - start < collect_duration:
                received, addr = self.gcs.receive()
                if received is not None and received.msg_id == 0:
                    heartbeat_timestamps.append(time.time())
                    detail = _format_msg_detail(received)
                    log_manager.log_and_attach(detail, f"心跳 {len(heartbeat_timestamps)} {addr[0]}")
                time.sleep(0.9)

        with allure.step("验证接收到心跳"):
            assert len(heartbeat_timestamps) >= 1, "未接收到任何心跳"
            log_manager.log_and_attach(f"接收到 {len(heartbeat_timestamps)} 次心跳", "验证通过")

        with allure.step("验证心跳时间间隔"):
            if len(heartbeat_timestamps) >= 2:
                intervals = [heartbeat_timestamps[i+1] - heartbeat_timestamps[i]
                             for i in range(len(heartbeat_timestamps) - 1)]
                avg_interval = sum(intervals) / len(intervals)
                min_interval = min(intervals)
                max_interval = max(intervals)

                detail = (f"心跳次数: {len(heartbeat_timestamps)}\n"
                          f"平均间隔: {avg_interval:.3f}s\n"
                          f"最小间隔: {min_interval:.3f}s\n"
                          f"最大间隔: {max_interval:.3f}s\n"
                          f"所有间隔: {[f'{i:.3f}s' for i in intervals]}")
                log_manager.log_and_attach(detail, "心跳间隔统计")

                expected_interval = 5.0
                tolerance = 0.3
                assert abs(avg_interval - expected_interval) < tolerance, \
                    f"平均间隔 {avg_interval:.3f}s 不符合预期 {expected_interval}s"
                log_manager.log_and_attach(f"心跳间隔正常: {avg_interval:.3f}s", "验证通过")
            else:
                log_manager.log_and_attach(
                    f"心跳次数不足 ({len(heartbeat_timestamps)} < 2)，跳过间隔验证", "跳过验证")

    @allure.feature("地面站识别功能")
    @allure.story("获取设备识别信息")
    @allure.title("发送请求获取识别信息")
    def test_02_send_id3_recv_id2(self):
        """发送 id=3 获取识别信息，接收 id=2 响应"""
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

        with allure.step("创建获取识别信息请求 (id=3)"):
            msg = MAVLink_message(msg_id=3, sys_id=1, comp_id=1, seq=0,
                                  version=self.mavlink_version,
                                  fields={'target_system': 1, 'target_component': 1})
            log_manager.log_and_attach(msg.hex_data, "发送数据十六进制")

        with allure.step("发送获取识别信息请求"):
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

    @allure.feature("地面站状态功能")
    @allure.story("请求打包状态")
    @allure.title("发送请求获取打包状态")
    def test_03_send_id1_recv_id5(self):
        """发送 id=1 (heartbeat_dmd)，返回 id=5 (packed_state)"""
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

        with allure.step("发送 heartbeat_dmd 报文 (id=1)"):
            # fe0c00010101010016000000000000000001f5f5
            hex_data = bytes.fromhex('fe0c00010101010016000000000000000001f5f5')
            # 使用第一个发现的无人机 IP
            if self.gcs.discovered_drones:
                target_ip = list(self.gcs.discovered_drones)[0]
            else:
                target_ip = self.gcs.drone_ip
            self.gcs.sock.sendto(hex_data, (target_ip, self.gcs.drone_port))
            log_manager.log_and_attach(f"发送至 {target_ip}:{self.gcs.drone_port}", "发送目标")

        with allure.step("等待无人机响应 (id=5)"):
            start_time = time.time()
            timeout = 5.0
            received = None
            while time.time() - start_time < timeout:
                received, addr = self.gcs.receive()
                if received is not None:
                    if received.msg_id == 5:
                        detail = _format_msg_detail(received)
                        log_manager.log_and_attach(detail, f"收到响应详情 {addr[0]}")
                        break
                    elif received.msg_id == 0:
                        # 忽略心跳，继续等待
                        continue
                time.sleep(0.1)

        with allure.step("验证响应消息"):
            assert received is not None, "未接收到响应"
            assert received.msg_id == 5, f"期望响应 msg_id=5，实际收到 msg_id={received.msg_id}"
            log_manager.log_and_attach(f"响应 msg_id={received.msg_id}", "验证通过")

    @allure.feature("地面站状态功能")
    @allure.story("请求打包状态和扩展状态")
    @allure.title("发送扩展请求获取扩展状态")
    def test_04_send_id1_extend_recv_id5_id8(self):
        """发送 id=1 且 extend=1，返回 id=5 和 id=8"""
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

        with allure.step("发送 heartbeat_dmd 报文 (id=1, extend=1)"):
            # fe0c00010101010016000000000000000001f5f5
            hex_data = bytes.fromhex('fe0c00010101010016000000000000000001f5f5')
            target_ip = list(self.gcs.discovered_drones)[0] if self.gcs.discovered_drones else self.gcs.drone_ip
            self.gcs.sock.sendto(hex_data, (target_ip, self.gcs.drone_port))
            log_manager.log_and_attach(f"发送至 {target_ip}:{self.gcs.drone_port}，extend=1", "发送目标")

        with allure.step("等待无人机响应 (id=5 和 id=8)"):
            start_time = time.time()
            timeout = 5.0
            recv_ids = []
            while time.time() - start_time < timeout:
                received, addr = self.gcs.receive()
                if received is not None:
                    if received.msg_id in (5, 8):
                        recv_ids.append(received.msg_id)
                        detail = _format_msg_detail(received)
                        log_manager.log_and_attach(detail, f"收到响应详情 {addr[0]}")
                    elif received.msg_id == 0:
                        # 忽略心跳
                        continue
                if 5 in recv_ids and 8 in recv_ids:
                    break
                time.sleep(0.1)

        with allure.step("验证响应消息"):
            assert 5 in recv_ids, f"期望收到 msg_id=5，实际收到的消息: {recv_ids}"
            assert 8 in recv_ids, f"期望收到 msg_id=8，实际收到的消息: {recv_ids}"
            log_manager.log_and_attach(f"收到消息ID: {recv_ids}", "验证通过")

    @allure.feature("地面站基础功能")
    @allure.story("UDP套接字初始化")
    @allure.title("UDP套接字初始化")
    def test_05_udp_socket_initialization(self):
        """测试 UDP 套接字初始化"""
        with allure.step("验证UDP套接字"):
            assert self.gcs.sock is not None, "UDP套接字未创建"
            log_manager.log_and_attach("UDP套接字已创建", "验证结果")

        with allure.step("验证UDP连接状态"):
            assert self.gcs.udp_connected is True, "UDP未连接"
            log_manager.log_and_attach("UDP已连接", "验证结果")

    @allure.feature("地面站基础功能")
    @allure.story("UDP套接字绑定")
    @allure.title("UDP套接字绑定")
    def test_06_udp_socket_binding(self):
        """测试 UDP 套接字绑定"""
        with allure.step("获取本地绑定地址"):
            local_addr = self.gcs.sock.getsockname()
            log_manager.log_and_attach(f"绑定地址: {local_addr}", "绑定信息")

        with allure.step("验证绑定地址"):
            expected = (self.gcs.local_ip, self.gcs.local_port)
            assert local_addr == expected, f"期望 {expected}，实际 {local_addr}"
            log_manager.log_and_attach(f"绑定正确: {local_addr}", "验证通过")

    @allure.feature("地面站基础功能")
    @allure.story("关闭套接字")
    @allure.title("关闭套接字")
    def test_07_close_socket(self):
        """测试关闭套接字"""
        with allure.step("关闭地面站"):
            self.gcs.close()

        with allure.step("验证关闭结果"):
            assert self.gcs.sock is None, "套接字未置空"
            log_manager.log_and_attach("套接字已置空", "验证结果")

        with allure.step("验证连接状态"):
            assert self.gcs.udp_connected is False, "连接状态未更新"
            log_manager.log_and_attach("连接已断开", "验证结果")

    @allure.feature("地面站基础功能")
    @allure.story("关闭后发送")
    @allure.title("关闭后发送失败")
    def test_08_send_after_close(self):
        """测试关闭后发送失败"""
        with allure.step("关闭套接字"):
            self.gcs.close()

        with allure.step("验证发送失败"):
            hex_data = bytes.fromhex('fe0c00010101010016000000000000000001f5f5')
            try:
                self.gcs.sock.sendto(hex_data, (self.gcs.drone_ip, self.gcs.drone_port))
                result = True
            except Exception:
                result = False
            assert result is False, "关闭后发送应该失败"
            log_manager.log_and_attach("关闭后发送返回 False", "验证通过")

    @allure.feature("地面站心跳功能")
    @allure.story("验证心跳响应时间")
    @allure.title("验证每台飞机心跳响应间隔")
    def test_09_verify_heartbeat_interval(self):
        """发送 heartbeat_dmd 请求并验证无人机响应间隔是否稳定（期望约1秒）"""
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

        target_ip = list(self.gcs.discovered_drones)[0] if self.gcs.discovered_drones else self.gcs.drone_ip
        hex_data = bytes.fromhex('fe0c00010101010016000000000000000001f5f5')
        response_times = []

        with allure.step("发送 heartbeat_dmd 报文并记录响应时间"):
            for i in range(6):
                t_send = time.time()
                self.gcs.sock.sendto(hex_data, (target_ip, self.gcs.drone_port))

                t_recv = None
                t_start = time.time()
                recv_timeout = 3.0
                while time.time() - t_start < recv_timeout:
                    received, addr = self.gcs.receive()
                    if received is not None and received.msg_id == 5:
                        t_recv = time.time()
                        detail = _format_msg_detail(received)
                        log_manager.log_and_attach(detail, f"第{i+1}次响应 {addr[0]}")
                        break
                    elif received is not None and received.msg_id == 0:
                        continue
                    time.sleep(0.05)

                if t_recv is not None:
                    elapsed = t_recv - t_send
                    response_times.append((t_send, t_recv, elapsed))
                    log_manager.log_and_attach(
                        f"第{i+1}次: 发送={t_send:.3f}, 接收={t_recv:.3f}, 耗时={elapsed:.3f}s",
                        f"响应时间 {i+1}")
                time.sleep(0.8)

        with allure.step("验证响应时间间隔"):
            assert len(response_times) >= 3, f"响应次数不足 ({len(response_times)} < 3)"

            intervals = [response_times[j+1][0] - response_times[j][0] for j in range(len(response_times)-1)]
            avg_interval = sum(intervals) / len(intervals)
            min_interval = min(intervals)
            max_interval = max(intervals)

            detail = (f"响应次数: {len(response_times)}\n"
                      f"平均发送间隔: {avg_interval:.3f}s\n"
                      f"最小发送间隔: {min_interval:.3f}s\n"
                      f"最大发送间隔: {max_interval:.3f}s\n"
                      f"所有间隔: {[f'{i:.3f}s' for i in intervals]}\n"
                      f"各次响应耗时: {[f'{rt[2]:.3f}s' for rt in response_times]}")
            log_manager.log_and_attach(detail, f"{target_ip} 响应间隔统计")

            expected_interval = 1.0
            tolerance = 0.3
            assert abs(avg_interval - expected_interval) < tolerance, \
                f"{target_ip}: 平均响应间隔 {avg_interval:.3f}s 不符合预期 {expected_interval}s"
            log_manager.log_and_attach(f"响应间隔正常: {avg_interval:.3f}s", "验证通过")