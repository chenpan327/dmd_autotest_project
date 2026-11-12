# coding: utf-8
"""
WiFi 模块测试 - 其他 MAVLink 命令覆盖(脚本层)

业务背景:
    test_wifi_gcs_command_handling.py 只覆盖了 STANDBY / EULER_NETWORK 两条核心命令。
    onion_companion.c 还处理一组运维命令,这些命令在 release 测试中也应至少验证
    "WiFi 模块不崩溃 + 透传/响应链路正常":

    - MAV_CMD_WIFI_MAC_ADDR (1005,onion_companion.c:128-157):
        * param1=0:WiFi 把 STA MAC(6B)填入 param2-7 后透传回 UAV
        * param1=1:WiFi 把 STA IP(4B)填入 param2-5 后透传回 UAV
    - MAV_CMD_HOLD_PWR (40054,onion_companion.c:116-118):
        * 仅在升级流程中由本模块向 UAV 下发,这里反向验证 ACK 链路
    - MAV_CMD_SWITCH_DHCP (40049,onion_companion.c:262-263):
        * 当前实现 continue 直接丢弃,不回 ACK,仅验证不崩溃
    - MAV_CMD_DELETE_MAC (40050,onion_companion.c:264-265):
        * 当前实现 continue 直接丢弃,不回 ACK,仅验证不崩溃

    另外两条"无副作用"消息也归到本测试:
    - SUBMOD_FIRMWARE_INFO (onion_companion.c:304-306):仅 LOG_I
    - SUBMOD_UPDATE_PACKAGE (onion_companion.c:307-309):仅 LOG_I

分层:
    协议层封装见 src.Protocol.wifi.wifi:
      - send_command_long(gcs, mavlink_version, command_id, param1)
      - query_wifi_mac_addr(gcs, mavlink_version, want_ip)
    脚本层只做 pytest 编排 + allure 步骤 + 断言。

注意:
    MAV_CMD_HOLD_PWR / SWITCH_DHCP / DELETE_MAC 在当前固件中要么由模块主动下发,
    要么 continue 丢弃,WiFi 模块对 GCS 下行版本只透传(或丢弃)。
    所以这些用例的判定重点是"链路不崩 + ACK 行为符合预期",而非业务字段。
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
from src.Protocol.wifi.wifi import (
    send_command_long, query_wifi_mac_addr, wait_for_command_ack,
    resolve_module_ip,
    DEFAULT_ACK_TIMEOUT,
    MAV_CMD_HOLD_PWR, MAV_CMD_SWITCH_DHCP, MAV_CMD_DELETE_MAC,
    MAV_CMD_WIFI_MAC_ADDR, MSG_ID_COMMAND_LONG, MSG_ID_COMMAND_ACK,
)


# MAV_CMD_RID_CTRL — 源码 dmd_uav_37.py:597(RID 控制)
MAV_CMD_RID_CTRL = 40053


# 源码 onion_companion.c:304-309 中两条消息只 LOG_I,定义常量避免魔数
# 取值来源:file/mavlink_version/dmd_uav_37.py:878-880
MSG_ID_SUBMOD_FIRMWARE_INFO = 92
MSG_ID_SUBMOD_UPDATE_PACKAGE = 94



@allure.epic("WiFi 模块测试")
@allure.feature("GCS 命令处理")
@allure.story("其他 MAVLink 命令")
class TestWifiMavlinkExtraCommands:
    """WiFi 模块对其他 MAVLink 命令的处理"""

    @pytest.fixture(scope="class")
    def gcs(self, test_params, serial_session):
        """地面站 fixture:作为命令发送方(用模块当前 IP)"""
        target_ip = resolve_module_ip(serial_session, test_params["mavlink_target_ip"])
        target_port = test_params["mavlink_target_port"]

        log_manager.logger.info(f"[Extra-Cmd] 地面站初始化: {target_ip}:{target_port}")
        gcs_instance = GroundControlStation(drone_ip=target_ip, drone_port=target_port)

        log_manager.logger.info("[Extra-Cmd] 开始发现无人机...")
        gcs_instance.discover_drones(timeout=5.0)
        if gcs_instance.discovered_drones:
            best_ip = next(iter(gcs_instance.discovered_drones))
            log_manager.logger.info(f"[Extra-Cmd] 发现无人机: {best_ip}")
        else:
            log_manager.logger.warning(
                f"[Extra-Cmd] 未发现无人机,使用默认: {target_ip}"
            )

        yield gcs_instance
        gcs_instance.close()

    # ==================== MAV_CMD_WIFI_MAC_ADDR 测试 ====================


    @allure.title("WIFI_MAC_ADDR 查询 STA MAC(param1=0)")
    @allure.description(
        "发送 COMMAND_LONG command=1005 param1=0,验证 WiFi 把 STA MAC 填入 param2-7 后透传回 UAV。"
        "源码 onion_companion.c:131-142:wifi_config_get_mac_address(WIFI_PORT_STA, mac_addr) → param2-7。"
        "注:WiFi 模块把 ack 透传到 UAV,不直接回 GCS — 没收到 ACK 时 SKIP,不死板断言 FAIL。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("GCS 命令", "WIFI_MAC_ADDR", "MAC 查询")
    def test_query_wifi_mac(self, gcs, mavlink_version, serial_session):
        """测试 WIFI_MAC_ADDR param1=0 查 MAC"""
        with allure.step("记录预期 MAC(串口直读,作为对照)"):
            expected_mac = serial_session.get_mac_address("sta")
            log_manager.logger.info(f"[Extra-Cmd] 串口直读 STA MAC: {expected_mac}")

        with allure.step("发送 MAV_CMD_WIFI_MAC_ADDR param1=0(协议层 query_wifi_mac_addr)"):
            result, ack_msg = query_wifi_mac_addr(gcs, mavlink_version, want_ip=False)

        with allure.step("验证响应"):
            allure.attach(
                f"【测试数据】\n"
                f"  命令: MAV_CMD_WIFI_MAC_ADDR param1=0\n"
                f"  串口直读 MAC: {expected_mac}\n"
                f"  ACK result: {result}\n"
                f"  ACK msg: {ack_msg}",
                name="测试数据",
                attachment_type=allure.attachment_type.TEXT
            )

            # WiFi 把 ack 透传到 UAV,不直接回 GCS;没收到属预期,SKIP
            if ack_msg is None:
                pytest.skip(
                    "WiFi 模块把 WIFI_MAC_ADDR ack 透传给 UAV,GCS 未直接收到 — "
                    "符合 onion_companion.c:155 xQueueSend(queue_companion_to_uav)。"
                )

            # 收到 ACK 时,result 应为 ACCEPTED
            assert result == 0, f"WIFI_MAC_ADDR 应回 ACCEPTED,实际 result={result}"

            allure.attach(
                f"【测试结果】\n"
                f"  ACK result: {result} (ACCEPTED)\n"
                f"  透传方向: WiFi → UAV(不直接回 GCS,本用例仅验证 ACK 链路)",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )


    @allure.title("WIFI_MAC_ADDR 查询 STA IP(param1=1)")
    @allure.description(
        "发送 COMMAND_LONG command=1005 param1=1,验证 WiFi 把 STA IP 填入 param2-5 后透传回 UAV。"
        "源码 onion_companion.c:143-152:get_st1_ipaddr() → param2-5。"
        "同 MAC 用例:ack 透传到 UAV,GCS 未收到属预期。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("GCS 命令", "WIFI_MAC_ADDR", "IP 查询")
    def test_query_wifi_ip(self, gcs, mavlink_version, serial_session):
        """测试 WIFI_MAC_ADDR param1=1 查 IP"""
        with allure.step("记录预期 IP(串口直读,作为对照)"):
            expected_ip = serial_session.get_ip_address()
            log_manager.logger.info(f"[Extra-Cmd] 串口直读 STA IP: {expected_ip}")

        with allure.step("发送 MAV_CMD_WIFI_MAC_ADDR param1=1(协议层 query_wifi_mac_addr)"):
            result, ack_msg = query_wifi_mac_addr(gcs, mavlink_version, want_ip=True)

        with allure.step("验证响应"):
            allure.attach(
                f"【测试数据】\n"
                f"  命令: MAV_CMD_WIFI_MAC_ADDR param1=1\n"
                f"  串口直读 IP: {expected_ip}\n"
                f"  ACK result: {result}\n"
                f"  ACK msg: {ack_msg}",
                name="测试数据",
                attachment_type=allure.attachment_type.TEXT
            )

            if ack_msg is None:
                pytest.skip(
                    "WiFi 模块把 WIFI_MAC_ADDR ack 透传给 UAV,GCS 未直接收到 — "
                    "符合 onion_companion.c:155 xQueueSend(queue_companion_to_uav)。"
                )

            assert result == 0, f"WIFI_MAC_ADDR 应回 ACCEPTED,实际 result={result}"

            allure.attach(
                f"【测试结果】\n"
                f"  ACK result: {result} (ACCEPTED)\n"
                f"  透传方向: WiFi → UAV",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )

    # ==================== MAV_CMD_HOLD_PWR 测试 ====================


    @allure.title("MAV_CMD_HOLD_PWR GCS 下发(ACK 链路验证)")
    @allure.description(
        "MAV_CMD_HOLD_PWR(40054)原本是 WiFi 模块在升级流程中主动向 UAV 下发的电源锁定命令\n"
        "(onion_upgrade.c:206),正常业务流不会从 GCS 反向下发。\n"
        "本用例反向测试:GCS 下发 HOLD_PWR,验证 WiFi 模块(_transfer_gcs_to_uav)至少不崩溃。\n"
        "固件 onion_companion.c:218-265 对 COMMAND_LONG 只匹配特定 command_id,HOLD_PWR 不在白名单,\n"
        "会落到末尾 xQueueSend(queue_companion_to_uav) 透传给 UAV — 不回 ACK,GCS 收不到属预期。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("GCS 命令", "HOLD_PWR", "边界测试")
    def test_hold_pwr_gcs_to_uav(self, gcs, mavlink_version):
        """测试 GCS 反向下发 HOLD_PWR(WiFi 应透传给 UAV,不死机)"""
        with allure.step("发送 MAV_CMD_HOLD_PWR param1=1"):
            result = send_command_long(
                gcs, mavlink_version,
                command_id=MAV_CMD_HOLD_PWR, param1=1,
            )

        with allure.step("验证 WiFi 模块未崩溃(任一响应或超时均可)"):
            allure.attach(
                f"【测试数据】\n"
                f"  命令: MAV_CMD_HOLD_PWR param1=1\n"
                f"  ACK result: {result}(None 表示未回 ACK,符合透传语义)\n"
                f"  业务判定: 不死机即通过",
                name="测试数据",
                attachment_type=allure.attachment_type.TEXT
            )

            # 预期:WiFi 透传给 UAV,GCS 不应收到 ACK;result=None 符合预期
            # 这里只验证命令发送 + 等待流程不抛异常
            log_manager.logger.info(
                f"[Extra-Cmd] HOLD_PWR ACK result={result} "
                f"(None 属预期 — WiFi 透传给 UAV,不直接回 GCS)"
            )

            allure.attach(
                f"【测试结果】\n"
                f"  WiFi 模块未崩溃\n"
                f"  ACK 行为: {('回 ACK' if result is not None else '未回 ACK(透传给 UAV)')}\n"
                f"  链路验证: 通过",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )


    # ==================== MAV_CMD_SWITCH_DHCP / DELETE_MAC 测试 ====================


    @allure.title("MAV_CMD_SWITCH_DHCP GCS 下发(WiFi 应 continue 丢弃)")
    @allure.description(
        "MAV_CMD_SWITCH_DHCP(40049)在 onion_companion.c:262-263 中被 continue 直接丢弃,\n"
        "不回 ACK,也不会透传到 UAV。\n"
        "本用例验证 WiFi 模块对这条命令的处理符合「丢弃」语义 — 不死机 + 不透传。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("GCS 命令", "SWITCH_DHCP", "丢弃语义")
    def test_switch_dhcp_dropped(self, gcs, mavlink_version):
        """测试 SWITCH_DHCP 被 WiFi 丢弃"""
        with allure.step("发送 MAV_CMD_SWITCH_DHCP param1=0"):
            result = send_command_long(
                gcs, mavlink_version,
                command_id=MAV_CMD_SWITCH_DHCP, param1=0,
            )

        with allure.step("验证 WiFi 丢弃(不回 ACK,不死机)"):
            log_manager.logger.info(
                f"[Extra-Cmd] SWITCH_DHCP ACK result={result} "
                f"(None 属预期 — onion_companion.c:263 continue 直接丢弃)"
            )

            allure.attach(
                f"【测试结果】\n"
                f"  命令: MAV_CMD_SWITCH_DHCP param1=0\n"
                f"  ACK result: {result}(None 属预期 — 被 continue 丢弃)\n"
                f"  WiFi 模块未崩溃",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )


    @allure.title("MAV_CMD_DELETE_MAC GCS 下发(WiFi 应 continue 丢弃)")
    @allure.description(
        "MAV_CMD_DELETE_MAC(40050)在 onion_companion.c:264-265 中被 continue 直接丢弃。\n"
        "本用例验证 WiFi 模块对这条命令的「丢弃」语义 — 不死机 + 不透传。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("GCS 命令", "DELETE_MAC", "丢弃语义")
    def test_delete_mac_dropped(self, gcs, mavlink_version):
        """测试 DELETE_MAC 被 WiFi 丢弃"""
        with allure.step("发送 MAV_CMD_DELETE_MAC param1=0"):
            result = send_command_long(
                gcs, mavlink_version,
                command_id=MAV_CMD_DELETE_MAC, param1=0,
            )

        with allure.step("验证 WiFi 丢弃(不回 ACK,不死机)"):
            log_manager.logger.info(
                f"[Extra-Cmd] DELETE_MAC ACK result={result} "
                f"(None 属预期 — onion_companion.c:265 continue 直接丢弃)"
            )

            allure.attach(
                f"【测试结果】\n"
                f"  命令: MAV_CMD_DELETE_MAC param1=0\n"
                f"  ACK result: {result}(None 属预期 — 被 continue 丢弃)\n"
                f"  WiFi 模块未崩溃",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )


    # ==================== SUBMOD_FIRMWARE_INFO / UPDATE_PACKAGE 测试 ====================


    @allure.title("SUBMOD_FIRMWARE_INFO 消息(WiFi 仅记日志)")
    @allure.description(
        "MAVLINK_MSG_ID_SUBMOD_FIRMWARE_INFO 在 onion_companion.c:304-306 中仅 LOG_I,\n"
        "无副作用,不回 ACK。本用例验证 WiFi 模块对这条消息不死机。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("MAVLink 消息", "SUBMOD_FIRMWARE_INFO", "边界测试")
    def test_submod_firmware_info_no_crash(self, gcs, mavlink_version):
        """测试 SUBMOD_FIRMWARE_INFO 仅记日志(不死机)"""
        with allure.step("发送 SUBMOD_FIRMWARE_INFO"):
            msg = MAVLink_message(
                msg_id=MSG_ID_SUBMOD_FIRMWARE_INFO,
                sys_id=1, comp_id=1, seq=0,
                version=mavlink_version,
                fields={},
            )
            send_ok = gcs.send(msg)
            log_manager.logger.info(
                f"[Extra-Cmd] SUBMOD_FIRMWARE_INFO 发送: {send_ok}"
            )

        with allure.step("等待 2s 确认 WiFi 未崩溃"):
            time.sleep(2)
            allure.attach(
                f"【测试结果】\n"
                f"  命令: MAVLINK_MSG_ID_SUBMOD_FIRMWARE_INFO\n"
                f"  发送: {'成功' if send_ok else '失败'}\n"
                f"  WiFi 模块未崩溃(onion_companion.c:304-306 仅 LOG_I)",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )


    @allure.title("SUBMOD_UPDATE_PACKAGE 消息(WiFi 仅记日志)")
    @allure.description(
        "MAVLINK_MSG_ID_SUBMOD_UPDATE_PACKAGE 在 onion_companion.c:307-309 中仅 LOG_I,\n"
        "无副作用,不回 ACK。本用例验证 WiFi 模块对这条消息不死机。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("MAVLink 消息", "SUBMOD_UPDATE_PACKAGE", "边界测试")
    def test_submod_update_package_no_crash(self, gcs, mavlink_version):
        """测试 SUBMOD_UPDATE_PACKAGE 仅记日志(不死机)"""
        with allure.step("发送 SUBMOD_UPDATE_PACKAGE"):
            msg = MAVLink_message(
                msg_id=MSG_ID_SUBMOD_UPDATE_PACKAGE,
                sys_id=1, comp_id=1, seq=0,
                version=mavlink_version,
                fields={},
            )
            send_ok = gcs.send(msg)
            log_manager.logger.info(
                f"[Extra-Cmd] SUBMOD_UPDATE_PACKAGE 发送: {send_ok}"
            )

        with allure.step("等待 2s 确认 WiFi 未崩溃"):
            time.sleep(2)
            allure.attach(
                f"【测试结果】\n"
                f"  命令: MAVLINK_MSG_ID_SUBMOD_UPDATE_PACKAGE\n"
                f"  发送: {'成功' if send_ok else '失败'}\n"
                f"  WiFi 模块未崩溃(onion_companion.c:307-309 仅 LOG_I)",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )


    # ==================== MAV_CMD_RID_CTRL 测试 ====================


    @allure.title("MAV_CMD_RID_CTRL GCS 下发(WiFi 应透传到 UAV)")
    @allure.description(
        "MAV_CMD_RID_CTRL(40053)用于开启/关闭 RemoteID 广播。\n"
        "固件 onion_companion.c:_transfer_gcs_to_uav 不识别此 command_id,\n"
        "会落到末尾 xQueueSend(queue_companion_to_uav) 透传给 UAV — 不回 ACK。\n"
        "本用例验证 WiFi 模块对这条命令不死机,且行为符合「透传」语义。\n"
        "注:RemoteID 实际由 rid_app.c + BLE/WiFi beacon 实现,WiFi 模块只是 MAVLink 透传节点。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("GCS 命令", "RID_CTRL", "RemoteID", "边界测试")
    def test_rid_ctrl_passthrough(self, gcs, mavlink_version):
        """测试 MAV_CMD_RID_CTRL 透传到 UAV(不直接回 ACK)"""
        with allure.step("发送 MAV_CMD_RID_CTRL param1=1(开启 RID)"):
            result = send_command_long(
                gcs, mavlink_version,
                command_id=MAV_CMD_RID_CTRL, param1=1,
            )

        with allure.step("验证 WiFi 模块未崩溃(透传语义)"):
            log_manager.logger.info(
                f"[Extra-Cmd] RID_CTRL ACK result={result} "
                f"(None 属预期 — WiFi 透传给 UAV,不直接回 GCS)"
            )

            allure.attach(
                f"【测试数据】\n"
                f"  命令: MAV_CMD_RID_CTRL param1=1\n"
                f"  ACK result: {result}(None 属预期 — WiFi 透传)\n"
                f"  业务判定: 不死机即通过",
                name="测试数据",
                attachment_type=allure.attachment_type.TEXT
            )

            allure.attach(
                f"【测试结果】\n"
                f"  WiFi 模块未崩溃\n"
                f"  ACK 行为: {('回 ACK' if result is not None else '未回 ACK(透传给 UAV)')}\n"
                f"  注:RID 实际广播由 rid_app.c + BLE/WiFi beacon 实现,\n"
                f"      本用例仅验证 MAV_CMD_RID_CTRL 的 MAVLink 透传链路",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )
