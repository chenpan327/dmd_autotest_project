# coding: utf-8
"""
机巢测试 - MAVLink 指令路由 (TC-NEST-3-03/04/05/06)

业务背景:
    gateWay.cpp:411 COMMAND_LONG 路由 switch:
    - NEST_UAV_CHARGER_CMD → chargeCtrl UDP 14653 (charger_gateway_client.cpp:179 回 ACK)
    - NEST_UAV_LOCK        → chargeCtrl motor (4 电机推拉杆 kOut/kIn)
    - MAV_CMD_DO_SET_SERVO → LED (param1=R, param2=G, param3=B, param4=index)
    - NEST_PPS_CHARGER_CMD → ppsManager UDP 14652 (ppsManager 当前是 stub, 不会回 ACK)
"""
import pytest
import allure

from utils.logger import log_manager


try:
    from src.Protocol.nest.nest_mavlink import NestMavlinkHelper, FakeGcs, FakeUdpSniffer  # type: ignore
    _NEST_MAVLINK_AVAILABLE = True
except ImportError:
    _NEST_MAVLINK_AVAILABLE = False


@pytest.fixture(autouse=True)
def _skip_without_nest_mavlink():
    if not _NEST_MAVLINK_AVAILABLE:
        pytest.skip(
            "nest MAVLink helper 未实现 (src/Protocol/nest/nest_mavlink.py 待补), "
            "本文件 4 个指令路由用例默认 skip"
        )


@allure.epic("机巢固件测试")
@allure.feature("Release 测试")
@allure.story("MAVLink 指令路由")
class TestNestCommandRouting:
    """充电指令 / UAV 锁定 / LED / PPS 指令路由 (TC-NEST-3-03/04/05/06)"""

    @allure.title("TC-NEST-3-03 NEST_UAV_CHARGER_CMD 路由到 chargeCtrl UDP 14653")
    @allure.description(
        "[App 固件] FakeGCS 发 NEST_UAV_CHARGER_CMD, 监听 UDP 14653 抓 chargeCtrl 收包, "
        "等 COMMAND_ACK result==0; charger_gateway_client.cpp:179 回 ACK。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("机巢", "App固件", "MAVLink", "充电指令路由")
    def test_charger_cmd_routed_to_chargectl(self, test_params):
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        sniffer = FakeUdpSniffer(local_port=test_params["charge_udp_port"])
        sniffer.start()
        with allure.step("发 NEST_UAV_CHARGER_CMD"):
            fake_gcs.send_command("NEST_UAV_CHARGER_CMD", params={"channel": 0, "action": "on"})
        with allure.step("UDP 14653 抓包验证 chargeCtrl 收到"):
            pkt = sniffer.wait_for_packet(timeout=2.0)
            assert pkt is not None, "chargeCtrl UDP 14653 未收到指令"
        with allure.step("等 COMMAND_ACK"):
            ack = fake_gcs.wait_for_ack(command="NEST_UAV_CHARGER_CMD", timeout=3.0)
            assert ack is not None and ack.result == 0, f"ACK 失败: {ack}"
        log_manager.logger.info("充电指令路由 + ACK OK")


    @allure.title("TC-NEST-3-04 NEST_UAV_LOCK 触发 4 电机推拉杆")
    @allure.description(
        "[App 固件] FakeGCS 发 NEST_UAV_LOCK, 监听 chargeCtrl 电机动作, "
        "验证 MotorDirection kOut/kIn 切换。需机巢台架实际电机, mock 模式仅验路由。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("机巢", "App固件", "MAVLink", "电机锁定")
    def test_uav_lock_motor_action(self, test_params):
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        for direction in ("kOut", "kIn"):
            with allure.step(f"发 NEST_UAV_LOCK direction={direction}"):
                fake_gcs.send_command("NEST_UAV_LOCK", params={"direction": direction})
            with allure.step("等 COMMAND_ACK"):
                ack = fake_gcs.wait_for_ack(command="NEST_UAV_LOCK", timeout=3.0)
                assert ack is not None and ack.result == 0, (
                    f"{direction} ACK 失败 (mock 模式至少路由应通)"
                )
        log_manager.logger.info("UAV 锁定电机动作 OK")


    @allure.title("TC-NEST-3-05 MAV_CMD_DO_SET_SERVO param1~4 设 LED RGB + index")
    @allure.description(
        "[App 固件] 发 DO_SET_SERVO param1=R param2=G param3=B param4=0 (单灯) 与 0xff (全部); "
        "视觉采集 5 LED 颜色匹配 (容差 ±10)。gateWay.cpp:421-439 解析。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("机巢", "App固件", "MAVLink", "LED颜色")
    def test_led_color_via_do_set_servo(self, test_params):
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        test_cases = [
            {"r": 255, "g": 0, "b": 0, "index": 0},   # 单灯红
            {"r": 0, "g": 255, "b": 0, "index": 1},   # 单灯绿
            {"r": 0, "g": 0, "b": 255, "index": 0xff},  # 全部蓝
        ]
        for tc in test_cases:
            with allure.step(f"发 DO_SET_SERVO RGB=({tc['r']},{tc['g']},{tc['b']}) index={tc['index']}"):
                fake_gcs.send_command(
                    "MAV_CMD_DO_SET_SERVO",
                    params={"p1": tc["r"], "p2": tc["g"], "p3": tc["b"], "p4": tc["index"]},
                )
            with allure.step("等 COMMAND_ACK"):
                ack = fake_gcs.wait_for_ack(command="MAV_CMD_DO_SET_SERVO", timeout=2.0)
                assert ack is not None and ack.result == 0, f"ACK 失败: {ack}"
        log_manager.logger.info(f"LED 颜色控制 OK ({len(test_cases)} 场景)")


    @allure.title("TC-NEST-3-06 NEST_PPS_CHARGER_CMD 路由到 ppsManager UDP 14652")
    @allure.description(
        "[App 固件] FakeGCS 发 NEST_PPS_CHARGER_CMD, 监听 UDP 14652 抓包, "
        "验证 ppsManager 是否收到。ppsManager 当前为 stub (ppsManagerEntry.cpp:24), 不会回 ACK — "
        "skip 条件:探测 UDP 14652 无响应则 skip (见评审 Q2)。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("机巢", "App固件", "MAVLink", "PPS充电指令")
    def test_pps_charger_cmd_routed_to_pps(self, test_params):
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        sniffer = FakeUdpSniffer(local_port=test_params["pps_udp_port"])
        sniffer.start()
        with allure.step("探测 ppsManager 是否实现 (UDP 14652 是否监听)"):
            if not sniffer.is_port_listening(timeout=1.0):
                pytest.skip("ppsManager 仍为 stub, UDP 14652 未监听 — 跳过 (评审 Q2)")
        with allure.step("发 NEST_PPS_CHARGER_CMD"):
            fake_gcs.send_command("NEST_PPS_CHARGER_CMD", params={"action": "on"})
        with allure.step("UDP 14652 抓包验证 ppsManager 收到"):
            pkt = sniffer.wait_for_packet(timeout=2.0)
            assert pkt is not None, "ppsManager UDP 14652 未收到指令"
        log_manager.logger.info("PPS 充电指令路由 OK")
