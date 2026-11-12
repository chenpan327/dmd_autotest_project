# coding: utf-8
"""
机巢测试 - MAVLink 透传与广播 (TC-NEST-3-01/02/08/10)

业务背景:
    gateWay.cpp:341 handleUaverMsg:UAV → GCS 心跳透传; gateWay.cpp:349 default 透明转发。
    gateWay.cpp:363-366 fan-out:广播消息 fan-out 到 5 路串口。
    gateWay.cpp:440-446 LPPC_POWER_ON/OFF/SLEEP/WAKE 广播到 5 串口。

前置依赖:
    需 nest MAVLink helper (src/Protocol/nest 待补) + FakeUAV/FakeGCS 工具。
    缺失时本文件用例默认 skip, 等待 helper 落地。
"""
import pytest
import allure

from utils.logger import log_manager


try:
    from src.Protocol.nest.nest_mavlink import NestMavlinkHelper, FakeUav, FakeGcs  # type: ignore
    _NEST_MAVLINK_AVAILABLE = True
except ImportError:
    _NEST_MAVLINK_AVAILABLE = False


@pytest.fixture(autouse=True)
def _skip_without_nest_mavlink():
    if not _NEST_MAVLINK_AVAILABLE:
        pytest.skip(
            "nest MAVLink helper 未实现 (src/Protocol/nest/nest_mavlink.py 待补), "
            "本文件 4 个透传/广播用例默认 skip"
        )


@allure.epic("机巢固件测试")
@allure.feature("Release 测试")
@allure.story("MAVLink 透传与广播")
class TestNestMavlinkPassthrough:
    """MAVLink 心跳透传 / 广播 / LPPC 上下电 / 默认透明转发 (TC-NEST-3-01/02/08/10)"""

    @allure.title("TC-NEST-3-01 UAV→GCS 心跳透传 (gateWay.cpp:341)")
    @allure.description(
        "[App 固件] FakeUAV 经 serial 发 NEST_UAV_HEARTBEAT, FakeGCS UDP 14550 收包; "
        "时延 < 50ms, 连续 10 包不丢。gateWay 同时从心跳学习 UAV IP。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("机巢", "App固件", "MAVLink", "心跳透传")
    def test_uav_to_gcs_heartbeat_passthrough(self, test_params):
        fake_uav = FakeUav(serial_dev=test_params["uart_devs"][0])
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        fake_gcs.start_listening()

        with allure.step("FakeUAV 连发 10 个 NEST_UAV_HEARTBEAT"):
            seqs = fake_uav.send_heartbeats(count=10, interval=0.1)
        with allure.step("FakeGCS 收包并比对时延"):
            received = fake_gcs.wait_for_messages(timeout=3.0, expected_count=10)
            assert len(received) == 10, f"GCS 仅收到 {len(received)}/10 包"
            assert [m.seq for m in received] == seqs, "心跳序号不连续"
            for m in received:
                assert m.latency_ms < 50, f"心跳时延 {m.latency_ms}ms >= 50ms"
        log_manager.logger.info("UAV→GCS 心跳透传 OK (10/10, 均 <50ms)")


    @allure.title("TC-NEST-3-02 GCS→5UAV fan-out 广播 (gateWay.cpp:363)")
    @allure.description(
        "[App 固件] FakeGCS 发 HEARTBEAT_DMD, 5 路 FakeUAV 各自监听 serial, "
        "断言每路都收到 (fan-out 无遗漏)。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("机巢", "App固件", "MAVLink", "广播fan-out")
    def test_gcs_to_uavs_fanout_broadcast(self, test_params):
        fake_uavs = [FakeUav(serial_dev=d) for d in test_params["uart_devs"]]
        for u in fake_uavs:
            u.start_listening()
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        fake_gcs.send_heartbeat_dmd()
        with allure.step("5 路 FakeUAV 各自断言收到广播"):
            for idx, u in enumerate(fake_uavs):
                msg = u.wait_for_message(timeout=2.0)
                assert msg is not None, f"UAV#{idx} 未收到广播 (fan-out 遗漏)"
        log_manager.logger.info("5 路 fan-out 广播 OK")


    @allure.title("TC-NEST-3-08 LPPC_POWER_ON/OFF/SLEEP/WAKE 广播 5 串口")
    @allure.description(
        "[App 固件] FakeGCS 发 4 类 LPPC 命令, 5 路 FakeUAV 各自监听, "
        "断言每路都收到对应命令且无改写 (gateWay.cpp:440-446)。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("机巢", "App固件", "MAVLink", "LPPC上下电")
    def test_lppc_broadcast_to_all_serials(self, test_params):
        lppc_cmds = ["LPPC_POWER_ON", "LPPC_POWER_OFF", "LPPC_POWER_SLEEP", "LPPC_POWER_WAKE"]
        fake_uavs = [FakeUav(serial_dev=d) for d in test_params["uart_devs"]]
        for u in fake_uavs:
            u.start_listening()
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        for cmd in lppc_cmds:
            for u in fake_uavs:
                u.clear_buffer()
            fake_gcs.send_command(cmd)
            for idx, u in enumerate(fake_uavs):
                msg = u.wait_for_message(timeout=2.0)
                assert msg is not None, f"LPPC={cmd} UAV#{idx} 未收到"
                assert msg.command == cmd, f"LPPC 命令被改写: 期望 {cmd}, 收到 {msg.command}"
        log_manager.logger.info(f"LPPC 4 命令 5 串口广播 OK: {lppc_cmds}")


    @allure.title("TC-NEST-3-10 未知 msg_id default 路径透明转发 (gateWay.cpp:349)")
    @allure.description(
        "[App 固件] 双向透明转发:FakeUAV 发未识别 msg_id (如 SYS_STATUS), "
        "FakeGCS 原样收到; 反向 GCS 发未知 id, FakeUAV 原样收到。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("机巢", "App固件", "MAVLink", "透明转发")
    def test_unknown_msg_id_transparent_passthrough(self, test_params):
        fake_uav = FakeUav(serial_dev=test_params["uart_devs"][0])
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        fake_gcs.start_listening()
        fake_uav.start_listening()

        with allure.step("UAV→GCS 未知 msg_id 透明转发"):
            sent_payload = b"\x01\x02\x03\x04"
            fake_uav.send_unknown_msg(msg_id=10, payload=sent_payload)  # SYS_STATUS
            msg = fake_gcs.wait_for_message(timeout=2.0)
            assert msg is not None and msg.payload == sent_payload, "UAV→GCS 透明转发丢失或被改写"

        with allure.step("GCS→UAV 未知 msg_id 透明转发"):
            sent_payload2 = b"\xaa\xbb\xcc"
            fake_gcs.send_unknown_msg(msg_id=11, payload=sent_payload2)
            msg2 = fake_uav.wait_for_message(timeout=2.0)
            assert msg2 is not None and msg2.payload == sent_payload2, "GCS→UAV 透明转发丢失或被改写"
        log_manager.logger.info("未知 msg_id 双向透明转发 OK")
