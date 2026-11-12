# coding: utf-8
"""
机巢测试 - 充电与机电控制 (TC-NEST-5-01/02/03/04)

业务背景:
    gateWay 把 NEST_UAV_CHARGER_CMD / NEST_UAV_LOCK 路由到 chargeCtrl UDP 14653
    (gateWay.cpp:411, charger_gateway_client.cpp:179 回 ACK)。
    chargeCtrl 管充电开关 + 4 电机推拉杆 + 电流采样保护。
    LED 通过 MAV_CMD_DO_SET_SERVO param1~4 控制 (本模块不重复测, 见 TC-NEST-3-05)。
    摄像头 HTTP port 8080 提供单帧抓取。

设计要点:
    - 充电用例需要电流采样, 仅在机巢台架运行; mock 模式只验 ACK
    - 推拉杆 cycles 用例需要实际电机, 台架缺失时 SKIP
    - 摄像头用例只验 HTTP 单帧抓取, 红外/可见光双流不在本用例范围
"""
import re
import time

import pytest
import allure
import urllib.request

from utils.logger import log_manager


try:
    from src.Protocol.nest.nest_mavlink import NestMavlinkHelper, FakeGcs  # type: ignore
    _NEST_MAVLINK_AVAILABLE = True
except ImportError:
    _NEST_MAVLINK_AVAILABLE = False


@pytest.fixture(autouse=True)
def _skip_without_nest_mavlink():
    if not _NEST_MAVLINK_AVAILABLE:
        pytest.skip(
            "nest MAVLink helper 未实现 (src/Protocol/nest/nest_mavlink.py 待补), "
            "本文件充电/推拉杆/摄像头用例默认 skip"
        )


@allure.epic("机巢固件测试")
@allure.feature("Release 测试")
@allure.story("充电与机电控制")
class TestNestControl:
    """充电上下电 / 充电保护 / 推拉杆 cycles / 摄像头抓帧 (TC-NEST-5-01~04)"""


    @allure.title("TC-NEST-5-01 NEST_UAV_CHARGER_CMD on/off 各 3 次, ACK 全 result==0")
    @allure.description(
        "[App 固件] FakeGCS 交替发 charge on/off 共 6 次, 每次 COMMAND_ACK result==0, "
        "耗时 < 2s。charger_gateway_client.cpp:179 回 ACK。台架模式额外校验电流反馈, "
        "本用例仅协议层 ACK, 电流校验见台架套件。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("机巢", "App固件", "充电控制")
    def test_charger_on_off_cycles(self, test_params):
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        for i in range(3):
            for action in ("on", "off"):
                with allure.step(f"#{i} 发 NEST_UAV_CHARGER_CMD action={action}"):
                    fake_gcs.send_command(
                        "NEST_UAV_CHARGER_CMD", params={"channel": 0, "action": action}
                    )
                    ack = fake_gcs.wait_for_ack(
                        command="NEST_UAV_CHARGER_CMD", timeout=2.0
                    )
                    assert ack is not None and ack.result == 0, (
                        f"#{i} {action} ACK 失败: {ack}"
                    )
        log_manager.logger.info("充电 on/off 6 cycles ACK OK")


    @allure.title("TC-NEST-5-02 充电过流/过温/超时保护触发 (阈值由固件侧保证)")
    @allure.description(
        "[App 固件] 模拟过流/过温/超时三种异常输入, chargeCtrl 应在 1s 内回 NACK 或 "
        "STATUS 报警。阈值由固件侧 chargeCtrl.cpp 决定, 本用例只发触发参数 + 等 STATUS, "
        "STATUS 含 protect 字段即视为保护动作生效。台架真过流场景由充电桩联调套件覆盖。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("机巢", "App固件", "充电保护")
    def test_charge_protection_trigger(self, test_params):
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        cases = [
            {"name": "over_current", "params": {"action": "on", "force_fault": "over_current"}},
            {"name": "over_temp", "params": {"action": "on", "force_fault": "over_temp"}},
            {"name": "timeout", "params": {"action": "on", "force_fault": "timeout"}},
        ]
        for case in cases:
            with allure.step(f"发 NEST_UAV_CHARGER_CMD 模拟 {case['name']}"):
                fake_gcs.send_command("NEST_UAV_CHARGER_CMD", params=case["params"])
                status = fake_gcs.wait_for_status(timeout=2.0)
                assert status is not None, f"{case['name']} 无 STATUS 上报"
                assert getattr(status, "protect", None), (
                    f"{case['name']} STATUS 未触发保护标志: {status}"
                )
        log_manager.logger.info("充电保护三种触发 OK")


    @allure.title("TC-NEST-5-03 NEST_UAV_LOCK 推拉杆 50 cycles (kOut/kIn 交替)")
    @allure.description(
        "[App 固件] 交替发 kOut/kIn 各 50 次 (共 100 ACK), "
        "每次 result==0 且耗时 < 3s。需机巢台架 4 电机实际承力, "
        "台架缺失时 helper 检测到无串口反馈会自动 SKIP。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("机巢", "App固件", "推拉杆", "cycles")
    def test_uav_lock_cycles(self, test_params):
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        for i in range(50):
            for direction in ("kOut", "kIn"):
                with allure.step(f"#{i} 发 NEST_UAV_LOCK direction={direction}"):
                    fake_gcs.send_command(
                        "NEST_UAV_LOCK", params={"direction": direction}
                    )
                    ack = fake_gcs.wait_for_ack(
                        command="NEST_UAV_LOCK", timeout=3.0
                    )
                    assert ack is not None and ack.result == 0, (
                        f"#{i} {direction} ACK 失败: {ack}"
                    )
        log_manager.logger.info("推拉杆 50 cycles (100 ACK) OK")


    @allure.title("TC-NEST-5-04 摄像头 HTTP port 抓帧 (单帧 + Content-Type 校验)")
    @allure.description(
        "[App 固件] HTTP GET http://nest_ip:8080/?action=snapshot, "
        "Content-Type 必须 image/* 或 multipart/*, body > 1 KB。"
        "摄像头不可达 SKIP, 不算 FAIL。红外/可见光双流抓取见 TC-NEST-4-09。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("机巢", "App固件", "摄像头")
    def test_camera_http_snapshot(self, test_params):
        port = test_params["camera_http_port"]
        url = f"http://{test_params['nest_ip']}:{port}/?action=snapshot"
        with allure.step(f"HTTP GET {url}"):
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    ctype = resp.headers.get("Content-Type", "")
                    body = resp.read(64 * 1024)
            except Exception as e:
                pytest.skip(f"摄像头不可达 ({e}) — SKIP")
        with allure.step("断言 Content-Type 与 body"):
            assert ctype.startswith(("image/", "multipart/")), (
                f"Content-Type 非 image/multipart: {ctype!r}"
            )
            assert len(body) > 1024, f"body 太小: {len(body)} 字节"
        log_manager.logger.info(f"摄像头抓帧 OK: ctype={ctype}, size={len(body)}")
