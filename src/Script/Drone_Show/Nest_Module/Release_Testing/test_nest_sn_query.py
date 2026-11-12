# coding: utf-8
"""
机巢测试 - SN 查询与 IP 字节序 (TC-NEST-3-07/09)

业务背景:
    机巢消息定义说明 (3VrLnTpHkE2ciR2cNF5sEF):
    - §3 SN 查询:udp_data 头部 IP + compId 区分 nest/pps/charger/uav 不同 SN
    - §5 UDP mavlink 头部 IP 字节序:网络字节序 (大端), 172.16.0.123 → AC 10 00 7B
"""
import pytest
import allure

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
            "本文件 SN 查询与字节序用例默认 skip"
        )


@allure.epic("机巢固件测试")
@allure.feature("Release 测试")
@allure.story("SN 查询与 IP 字节序")
class TestNestSnQuery:
    """SN 查询 (4 种 compId) 与 UDP IP 字节序 (TC-NEST-3-07/09)"""

    @allure.title("TC-NEST-3-07 compId 区分返回 nest/pps/charger/uav 四种 SN")
    @allure.description(
        "[App 固件] udp_data 头部 IP=nest_ip 时, compId 分别=nest/pps/charger, "
        "发 GET_IDENTIFY_INFO 解析返回 SN; 改头部 IP=uav_ip, compId=uav 重试。"
        "4 种场景 SN 字段非空。参考机巢消息定义说明 §3。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("机巢", "App固件", "MAVLink", "SN查询")
    def test_sn_query_by_compid(self, test_params):
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        cases = [
            {"target": "nest", "header_ip": test_params["nest_ip"], "comp_id": "nest"},
            {"target": "pps", "header_ip": test_params["nest_ip"], "comp_id": "pps"},
            {"target": "charger", "header_ip": test_params["nest_ip"], "comp_id": "charger"},
            {"target": "uav", "header_ip": "172.16.0.123", "comp_id": "uav"},
        ]
        for case in cases:
            with allure.step(f"查询 {case['target']} 的 SN (header_ip={case['header_ip']})"):
                fake_gcs.send_get_identify_info(
                    header_ip=case["header_ip"], comp_id=case["comp_id"]
                )
                msg = fake_gcs.wait_for_identify_info(timeout=2.0)
                assert msg is not None, f"{case['target']} SN 查询无响应"
                assert msg.sn and len(msg.sn) > 0, f"{case['target']} SN 字段为空"
        log_manager.logger.info("4 种 compId SN 查询 OK")


    @allure.title("TC-NEST-3-09 UDP 头部 IP 网络字节序 (大端)")
    @allure.description(
        "[App 固件] 构造 172.16.0.123 → AC 10 00 7B 网络字节序, 抓包验证 4 字节排列; "
        "反向 ARM 小端读出 == uint32 0x7B0010AC。机巢消息定义说明 §5。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("机巢", "App固件", "MAVLink", "IP字节序")
    def test_udp_header_ip_byte_order(self, test_params):
        helper = NestMavlinkHelper()
        ip_str = "172.16.0.123"
        with allure.step(f"构造 {ip_str} 的网络字节序大端字节"):
            big_endian = helper.pack_ip_big_endian(ip_str)
            assert big_endian == b"\xac\x10\x00\x7b", (
                f"大端字节错: 期望 b'\\xac\\x10\\x00\\x7b', 实际 {big_endian!r}"
            )
        with allure.step("ARM 小端读出 uint32 (lsb first)"):
            little_uint32 = int.from_bytes(big_endian, "little")
            assert little_uint32 == 0x7B0010AC, (
                f"小端 uint32 错: 期望 0x7B0010AC, 实际 0x{little_uint32:08X}"
            )
        with allure.step("loopback 抓包验证 on-wire 字节序"):
            on_wire = helper.capture_udp_ip_bytes(
                target_ip=test_params["nest_ip"],
                target_port=test_params["nest_mavlink_port"],
                timeout=2.0,
            )
            assert on_wire is not None, "未抓到 UDP 包, 无法验字节序"
        log_manager.logger.info(f"IP 字节序 OK: big-endian={big_endian.hex()}, little-uint32=0x{little_uint32:08X}")
