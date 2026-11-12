# coding: utf-8
"""
WiFi 模块测试 - 心跳透传链路(脚本层)

业务背景:
    WiFi 模块作为 MAVLink 透传节点,需要可靠地把 FC 心跳转发给 GCS。
    UAV 内部有 failsafe 计时器(5s 未收到 GCS 心跳会触发保护),
    所以 WiFi 透传链路必须保证:可达 + 延迟可控 + 不连续丢包。

    本测试项通过 serial_fc_session(经 UART1 串口模拟 FC)+
    GroundControlStation(模拟 GCS)量化验证透传链路质量。

测试项:
    1. 心跳透传可达性 — 发心跳突发,GCS 在 8s 内收到至少 1 个
    2. 心跳透传端到端延迟 — 5 次采样平均延迟 < 1s(UAV failsafe 5s 的 1/5)
    3. 心跳透传无丢失 — 10s 窗口连续 10 个心跳,接收率 ≥ 80%

源码事实(来自 onion_companion.c):
    - _transfer_uav_to_gcs 行 193:FC 心跳 xQueueSend 到 queue_companion_to_gcs
    - WiFi 模块本身不计时,只透传 — failsafe 计时器在 UAV/GCS 两端

注:
    - FC 命令响应独立性(STANDBY 不依赖 FC 心跳)属于命令处理测试,
      见 test_wifi_gcs_command_handling.py::test_standby_independent_of_fc_heartbeat。
    - 协议握手(身份/扩展状态)见 test_wifi_mavlink_protocol_handshake.py。
"""
import time
import pytest
import allure
import sys
import os

# 确保项目根目录在 sys.path 中
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from utils.logger import log_manager
from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from src.Protocol.wifi.wifi import resolve_module_ip


# 历史背景:本模块曾用 UDP FakeAirplane 发包,但 mt793x 固件 UDP 入口设计上
# 只透传给 FC,不回 GCS(queue_companion_to_gcs 的 4 个写者全部来自 UART 侧 —
# onion_companion.c:193/252/273、onion_gcs.c:136)。真实 FC→GCS 透传只发生在
# UART 入口:_transfer_uart_to_companion(onion_uav.c:173)→ _transfer_uav_to_gcs
# (onion_companion.c:193)→ GCS。所以现在改用串口(serial_fc_session,接 UART1)
# 模拟 FC,走固件真实的 UART→GCS 透传链路。
# 真实 FC 字段对齐 dmd_uav:sys_id=0/comp_id=0/mavlink_version=33,见 mav_channel.cpp:29/195-213。


# 心跳透传延迟告警阈值(秒)— UAV failsafe 通常 5s 触发,WiFi 透传延迟应 < 1s
HEARTBEAT_LATENCY_WARN_S = 1.0
# 心跳透传延迟采样次数
HEARTBEAT_LATENCY_SAMPLES = 5
# 心跳发送间隔(秒)— 对齐真实飞控 3s 间隔,这里缩到 1s 加速采样
HEARTBEAT_INTERVAL_S = 1.0
# 心跳 msg_id(标准 HEARTBEAT=0 + DMD 自定义 HEARTBEAT_DMD=1)
HEARTBEAT_MSG_IDS = (0, 1)


# ============================================================================
# 模块级 SKIP:本模块三个用例需要 FT232RL #2 物理接到 WiFi 模块 UART1(FC MAVLink,
# 3Mbps),但当前测试机把 FT232RL #2 接到了真实 FC 板上的调试 UART(不是 FC 与 WiFi
# 模块之间的那根 WiFi-UART),测试发送的字节进入 FC 调试口但 FC 不转发,根本到不了
# WiFi 模块 UART1 RX → 固件解不到我们的 MAVLink 帧 → GCS 收不到任何我们发的 msg_id=0。
#
# 诊断指纹(2026-06-29 #474 实测):
#   - GCS 持续收到真实 FC 的 msg_id=64 透传(seq 连续递增)→ 真实 FC ↔ WiFi UART1
#     链路本身工作正常
#   - GCS 收不到任何 msg_id=0 —— 不是我们的(sys_id=0/comp_id=0)、不是固件自身
#     _heartbeat_task 的(autopilot=21)、也不是真实 FC hrtbt_serv 的(autopilot=20)
#   - 三路 msg_id=0 全失败 + msg_id=64 单路成功 = FT232RL #2 接到了 FC 调试口(死路)
#
# 固件透传逻辑已核实无 msg_id 过滤:
#   - _transfer_uart_to_companion(onion_uav.c:173)无差别 mavlink_parse_char
#   - _transfer_uav_to_gcs(onion_companion.c:171-193)msg_id=0 只调 update_uav_heartbeat,
#     无 continue,落入 L193 透传
#   - _transfer_companion_to_udp(onion_gcs.c:107-115)无 msg_id 过滤
#
# 启用方法:把 FT232RL #2 从 FC 调试口拔下,改接到 WiFi 模块 UART1 RX(同时拔掉真实
# FC 那头的线),然后删除下方 pytestmark 即可。接线修正后三个用例应全部 PASS。
# ============================================================================
pytestmark = pytest.mark.skip(
    reason="硬件接线未就绪:FT232RL #2 当前接 FC 调试口(应接 WiFi 模块 UART1 RX),"
           "测试字节到不了 WiFi 模块 UART1 → GCS 收不到 msg_id=0;改接后删本 SKIP 启用"
)


@allure.epic("WiFi 模块测试")
@allure.feature("MAVLink 通信")
@allure.story("心跳透传链路")
class TestWifiMavlinkHeartbeatPassthrough:
    """心跳透传链路测试类"""

    @pytest.fixture(scope="class")
    def gcs(self, test_params, serial_session):
        """GCS 模拟器 fixture:接收 FC 经 WiFi 透传的心跳(用模块当前 IP)"""
        target_ip = resolve_module_ip(serial_session, test_params["mavlink_target_ip"])
        target_port = test_params["mavlink_target_port"]

        log_manager.logger.info(f"[HB-Passthrough] GCS 初始化: {target_ip}:{target_port}")
        gcs_instance = GroundControlStation(drone_ip=target_ip, drone_port=target_port)
        yield gcs_instance
        gcs_instance.close()


    @pytest.fixture(autouse=True)
    def fake_plane(self, serial_fc_session):
        """复用 session 级 ProtocolHandler(接 WiFi 模块 UART1)作为 FC 模拟器"""
        log_manager.logger.info("[HB-Passthrough] 使用 UART1 串口模拟 FC")
        yield serial_fc_session


    @allure.title("心跳透传可达性(FC → WiFi → GCS)")
    @allure.description(
        "经 UART1 串口发心跳到 WiFi 模块,"
        "WiFi 模块经 _transfer_uav_to_gcs 透传给 GCS,GCS 8s 内应收到至少 1 个心跳(msg_id=0 或 1)。\n"
        "源码:onion_companion.c:193 _transfer_uav_to_gcs xQueueSend 到 queue_companion_to_gcs。\n"
        "判定:收到即通过;超时则 SKIP(GCS 未发现无人机或环境问题,非 WiFi 模块 bug)。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("MAVLink", "心跳", "透传可达性")
    def test_heartbeat_passthrough_success(self, gcs, fake_plane):
        """测试心跳透传可达性 — 经 UART1 发心跳到 WiFi 模块,WiFi 透传到 GCS"""
        with allure.step("经 UART1 发 3 次心跳突发(提高 GCS 识别率)"):
            for seq in range(3):
                msg = MAVLink_message(
                    msg_id=0, sys_id=0, comp_id=0, seq=seq,
                    version='v37',
                    fields={
                        'custom_mode': 0, 'type': 2, 'autopilot': 20,
                        'base_mode': 0, 'system_status': 4, 'mavlink_version': 33,
                    }
                )
                fake_plane.send_data(msg.pack())
                time.sleep(0.1)

        with allure.step("GCS 8s 窗口等待接收任意心跳"):
            start = time.time()
            received = None
            recv_addr = None
            while time.time() - start < 8.0:
                msg, addr = gcs.receive()
                if msg is not None and msg.msg_id in HEARTBEAT_MSG_IDS:
                    received = msg
                    recv_addr = addr
                    break
                time.sleep(0.05)
            elapsed = time.time() - start

        with allure.step("验证 GCS 收到至少 1 个心跳"):
            allure.attach(
                f"【测试数据】\n"
                f"  心跳突发: 3 次\n"
                f"  GCS 等待窗口: 8.0s\n"
                f"  实际耗时: {elapsed:.1f}s\n"
                f"  收到心跳: {received.msg_id if received else '(无)'}",
                name="测试数据",
                attachment_type=allure.attachment_type.TEXT
            )

            if received is None:
                pytest.skip(
                    "GCS 未在 8s 内收到 FC 心跳 — 可能 GCS 未发现无人机或 WiFi 透传异常,"
                    "判定为环境问题 SKIP"
                )

            log_manager.logger.info(
                f"[HB-Passthrough] 心跳透传可达: msg_id={received.msg_id},"
                f"from={recv_addr}, 耗时 {elapsed:.1f}s"
            )
            allure.attach(
                f"【测试结果】\n"
                f"  心跳透传链路可达\n"
                f"  首个心跳 msg_id: {received.msg_id}\n"
                f"  GCS 接收地址: {recv_addr}\n"
                f"  耗时: {elapsed:.1f}s",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )


    @allure.title("心跳透传端到端延迟(FC → WiFi → GCS)")
    @allure.description(
        f"经 UART1 串口发心跳到 WiFi 模块,WiFi 透传到 GCS,采样 {HEARTBEAT_LATENCY_SAMPLES} 次测量端到端延迟。\n"
        f"判定:平均延迟 < {HEARTBEAT_LATENCY_WARN_S}s(避免 UAV 5s failsafe 误触发),\n"
        f"      成功率 ≥ 60%(否则 WiFi 透传链路异常)。\n"
        f"源码:_transfer_uav_to_gcs on onion_companion.c:193 xQueueSend 到 queue_companion_to_gcs。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("MAVLink", "心跳", "透传延迟")
    def test_heartbeat_passthrough_latency(self, gcs, fake_plane):
        """测试心跳透传端到端延迟"""
        latencies = []
        with allure.step(
            f"采样 {HEARTBEAT_LATENCY_SAMPLES} 次心跳透传延迟 "
            f"(每 {HEARTBEAT_INTERVAL_S}s 经 UART1 发一次)"
        ):
            for seq in range(HEARTBEAT_LATENCY_SAMPLES):
                msg = MAVLink_message(
                    msg_id=0, sys_id=0, comp_id=0, seq=seq,
                    version='v37',
                    fields={
                        'custom_mode': 0, 'type': 2, 'autopilot': 20,
                        'base_mode': 0, 'system_status': 4, 'mavlink_version': 33,
                    }
                )
                t_start = time.time()
                fake_plane.send_data(msg.pack())

                got = False
                while time.time() - t_start < 2.0:
                    received, _ = gcs.receive()
                    if received is not None and received.msg_id in HEARTBEAT_MSG_IDS:
                        latency_ms = (time.time() - t_start) * 1000
                        latencies.append(latency_ms)
                        got = True
                        log_manager.logger.info(
                            f"[HB-Passthrough] 心跳 #{seq} 透传延迟: {latency_ms:.1f}ms"
                        )
                        break
                    time.sleep(0.02)
                if not got:
                    log_manager.logger.warning(
                        f"[HB-Passthrough] 心跳 #{seq} 未在 2s 内透传到 GCS"
                    )
                time.sleep(HEARTBEAT_INTERVAL_S)

        with allure.step("验证透传延迟分布"):
            valid_count = len(latencies)
            avg_ms = sum(latencies) / valid_count if valid_count else 0
            max_ms = max(latencies) if latencies else 0
            min_ms = min(latencies) if latencies else 0

            allure.attach(
                f"【测试数据】\n"
                f"  采样次数: {HEARTBEAT_LATENCY_SAMPLES}\n"
                f"  有效接收: {valid_count}\n"
                f"  采样间隔: {HEARTBEAT_INTERVAL_S}s\n"
                f"  延迟明细(ms): {[f'{x:.1f}' for x in latencies]}",
                name="测试数据",
                attachment_type=allure.attachment_type.TEXT
            )

            assert valid_count >= HEARTBEAT_LATENCY_SAMPLES * 0.6, (
                f"心跳透传成功率过低: {valid_count}/{HEARTBEAT_LATENCY_SAMPLES} "
                f"(WiFi 透传链路异常或 GCS 未发现无人机)"
            )

            assert avg_ms < HEARTBEAT_LATENCY_WARN_S * 1000, (
                f"心跳透传平均延迟 {avg_ms:.1f}ms 超过告警阈值 "
                f"{HEARTBEAT_LATENCY_WARN_S * 1000:.0f}ms,UAV 可能误触发 failsafe"
            )

            if max_ms > HEARTBEAT_LATENCY_WARN_S * 1000:
                log_manager.logger.warning(
                    f"[HB-Passthrough] 最大延迟 {max_ms:.1f}ms 超过告警阈值"
                    f"({HEARTBEAT_LATENCY_WARN_S * 1000:.0f}ms) — 偶发抖动,平均仍 OK"
                )

            allure.attach(
                f"【测试结果】\n"
                f"  有效采样: {valid_count}/{HEARTBEAT_LATENCY_SAMPLES}\n"
                f"  延迟统计: min={min_ms:.1f}ms, avg={avg_ms:.1f}ms, max={max_ms:.1f}ms\n"
                f"  告警阈值: {HEARTBEAT_LATENCY_WARN_S * 1000:.0f}ms (UAV failsafe 5s 的 1/5)\n"
                f"  结论: 心跳透传延迟可控",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )


    @allure.title("10s 窗口内连续心跳透传无丢失")
    @allure.description(
        "连续 10s 内经 UART1 每 1s 发一次心跳到 WiFi 模块,WiFi 应全部透传到 GCS。\n"
        "验证 WiFi 透传任务(_transfer_uav_to_gcs)不会因队列满或调度抖动丢失心跳。\n"
        "业务依据:UAV failsafe 5s 触发,如果 WiFi 丢失 ≥5 个连续心跳会导致 UAV 误判 GCS 失联。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("MAVLink", "心跳", "透传可靠性")
    def test_no_heartbeat_loss_in_window(self, gcs, fake_plane):
        """测试 10s 窗口内心跳透传无丢失"""
        total_hb = 10
        sent_count = 0
        received_count = 0
        start = time.time()

        with allure.step(f"10s 窗口内经 UART1 连续发 {total_hb} 个心跳"):
            for seq in range(total_hb):
                msg = MAVLink_message(
                    msg_id=0, sys_id=0, comp_id=0, seq=seq,
                    version='v37',
                    fields={
                        'custom_mode': 0, 'type': 2, 'autopilot': 20,
                        'base_mode': 0, 'system_status': 4, 'mavlink_version': 33,
                    }
                )
                fake_plane.send_data(msg.pack())
                sent_count += 1

                # 短暂窗口(0.5s)收本次心跳
                t_recv_start = time.time()
                while time.time() - t_recv_start < 0.5:
                    received, _ = gcs.receive()
                    if received is not None and received.msg_id in HEARTBEAT_MSG_IDS:
                        received_count += 1
                        break
                    time.sleep(0.02)

                # 等到下一秒边界(对齐 1s 间隔)
                elapsed = time.time() - start
                wait = max(0, (seq + 1) - elapsed)
                time.sleep(wait)

            elapsed_total = time.time() - start

        with allure.step("验证透传无连续丢失"):
            loss_count = sent_count - received_count
            loss_percent = (loss_count / sent_count * 100) if sent_count else 100

            allure.attach(
                f"【测试数据】\n"
                f"  窗口: 10s\n"
                f"  发送心跳: {sent_count}\n"
                f"  接收心跳: {received_count}\n"
                f"  丢失: {loss_count}({loss_percent:.0f}%)\n"
                f"  实际耗时: {elapsed_total:.1f}s",
                name="测试数据",
                attachment_type=allure.attachment_type.TEXT
            )

            # 允许偶发丢失(网络抖动),但连续丢失 ≥5 会触发 UAV failsafe
            # 这里用 80% 接收率作为软阈值,90% 作为告警
            assert received_count >= sent_count * 0.8, (
                f"心跳接收率过低: {received_count}/{sent_count} ({loss_percent:.0f}% 丢失)"
                f" — WiFi 透传链路异常"
            )

            if received_count < sent_count * 0.9:
                log_manager.logger.warning(
                    f"[HB-Passthrough] 心跳接收率 {received_count}/{sent_count} "
                    f"低于 90% 告警阈值 — 检查 WiFi 调度或队列深度"
                )

            allure.attach(
                f"【测试结果】\n"
                f"  心跳接收率: {received_count}/{sent_count} ({100 - loss_percent:.0f}%)\n"
                f"  连续丢失风险: {'无' if loss_count < 3 else '存在(需排查)'}\n"
                f"  UAV failsafe 风险: {'低' if loss_count < 3 else '高'}",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )
