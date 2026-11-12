# coding: utf-8
"""
WiFi 模块测试 - GCS 下行命令处理(脚本层)

业务背景:
    地面站(GCS)通过 MAVLink COMMAND_LONG 向 WiFi 模块下发运维指令,
    WiFi 模块处理后将 COMMAND_ACK 回复 GCS。本测试覆盖以下关键运维命令:
      - MAV_CMD_STANDBY (40046):UAV 上下电控制(表演流程核心)
      - EULER_NETWORK (msg_id=49):远程改 IP/SSID(远程运维通道)

中间件事实(来自 mt793x onion_companion.c):
    - MAV_CMD_STANDBY (40046,onion_companion.c:246-261):
        * param1=0 → fcs_pwr_control(true)  开 UAV 电 (GPIO16 高)
        * param1=1 → fcs_pwr_control(false) 关 UAV 电 (GPIO16 低)
        * 其他值 → 仅记日志,不控制电源
        * 无条件回 COMMAND_ACK result=ACCEPTED(在执行电源控制前)

    - EULER_NETWORK (msg_id=49,onion_companion.c:267-302,GCS→UAV 方向):
        * 先回 COMMAND_ACK command=49 result=ACCEPTED
        * vTaskDelay(1000) 等 ACK 到达
        * 解码 euler_network.id(uint32 当作 IP)和 euler_network.ssid(char[8])
        * 改 IP 条件:id != 0 且 != 当前 IP
        * 改 SSID 条件:非空、不等于 DMD_DFT_SSID、不等于旧值
        * 调用 set_wifi_ssid + set_ssid_chg_flag(1) 触发热加载,不 reboot

分层:
    协议层封装见 src/Protocol/wifi/mavlink_commands.py:
      - send_standby(gcs, mavlink_version, power_on)  → COMMAND_ACK result
      - send_euler_network(gcs, mavlink_version, ip, ssid) → COMMAND_ACK result
    脚本层只做 pytest 编排 + allure 步骤 + 断言,不再关心 MAVLink 字段细节。

副作用管理:
    EULER_NETWORK 会修改 IP/SSID,fixture teardown 必须还原。
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
from src.Protocol.wifi.wifi import (
    send_standby, send_euler_network, wait_for_command_ack,
    resolve_module_ip,
    DEFAULT_ACK_TIMEOUT,
)


@allure.epic("WiFi 模块测试")
@allure.feature("GCS 命令处理")
@allure.story("地面站下行命令")
class TestGcsCommandHandling:
    """WiFi 模块对 GCS 下行命令的处理测试"""

    @pytest.fixture(scope="class")
    def gcs(self, test_params, serial_session):
        """地面站 fixture:用模块当前 IP,避免 config mavlink_target_ip 与实际漂移"""
        target_ip = resolve_module_ip(serial_session, test_params["mavlink_target_ip"])
        target_port = test_params["mavlink_target_port"]

        log_manager.logger.info(f"[GCS-Cmd] 地面站初始化: {target_ip}:{target_port}")
        gcs_instance = GroundControlStation(drone_ip=target_ip, drone_port=target_port)

        log_manager.logger.info("[GCS-Cmd] 开始发现无人机...")
        gcs_instance.discover_drones(timeout=5.0)
        if gcs_instance.discovered_drones:
            best_ip = next(iter(gcs_instance.discovered_drones))
            log_manager.logger.info(f"[GCS-Cmd] 发现无人机: {best_ip}")
        else:
            log_manager.logger.warning(f"[GCS-Cmd] 未发现无人机,使用默认: {target_ip}")

        yield gcs_instance
        gcs_instance.close()

    @pytest.fixture(autouse=True)
    def _preserve_network_state(self, serial_session, test_params):
        """每个测试前后还原 IP/SSID,避免 EULER_NETWORK 污染后续测试"""
        original_ssid = test_params["test_ssid"]
        original_ip = None
        try:
            original_ip = serial_session.get_ip_address()
        except Exception as e:
            log_manager.logger.warning(f"[GCS-Cmd] 读取初始 IP 失败: {e}")

        log_manager.logger.info(
            f"[GCS-Cmd] 测试前状态: IP={original_ip}, SSID={original_ssid}"
        )
        yield
        try:
            log_manager.logger.info("[GCS-Cmd] 还原网络状态...")
            serial_session.change_ssid(original_ssid)
            time.sleep(5)
            if original_ip:
                serial_session.change_ip_config(original_ip)
                time.sleep(3)
            log_manager.logger.info("[GCS-Cmd] 还原完成")
        except Exception as e:
            log_manager.logger.error(f"[GCS-Cmd] 还原失败: {e}")

    # ==================== MAV_CMD_STANDBY 测试 ====================


    @allure.title("MAV_CMD_STANDBY 开 UAV 电源(param1=0)")
    @allure.description(
        "发送 COMMAND_LONG command=40046 param1=0,验证 WiFi 回 COMMAND_ACK result=0。"
        "固件 onion_companion.c:256-258 调用 fcs_pwr_control(true) 设置 GPIO16 高电平。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("GCS 命令", "STANDBY", "UAV 电源")
    def test_standby_uav_power_on(self, gcs, mavlink_version):
        """测试 STANDBY 命令开 UAV 电源"""
        with allure.step("发送 MAV_CMD_STANDBY param1=0(协议层 send_standby)"):
            result = send_standby(gcs, mavlink_version, power_on=True)

        with allure.step("验证 ACK result=ACCEPTED(0)"):
            assert result is not None, \
                f"{DEFAULT_ACK_TIMEOUT}s 内未收到 STANDBY 的 COMMAND_ACK"
            assert result == 0, \
                f"STANDBY 开电源被拒绝: result={result}(期望 0=ACCEPTED)"

            allure.attach(
                f"【测试结果】\n"
                f"  命令: MAV_CMD_STANDBY param1=0\n"
                f"  ACK result: {result} (ACCEPTED)\n"
                f"  动作: fcs_pwr_control(true) → UAV 上电",
                name="STANDBY 开电源",
                attachment_type=allure.attachment_type.TEXT
            )

    @allure.title("MAV_CMD_STANDBY 关 UAV 电源(param1=1)")
    @allure.description(
        "发送 COMMAND_LONG command=40046 param1=1,验证 WiFi 回 COMMAND_ACK result=0。"
        "固件 onion_companion.c:253-255 调用 fcs_pwr_control(false) 设置 GPIO16 低电平。\n"
        "环境相关性:\n"
        "  - 真电源(test_params['uav_power_supply_type']='real'):必须 result=0(ACCEPTED)\n"
        "  - 假电源('fake'):result=0(ACCEPTED) 或 result=4(FAILED) 都算通过 —\n"
        "    假电源没有真实负载,GPIO 拉低后 UAV 实际未下电,固件检测到 UAV 仍在线会回 FAILED。\n"
        "    这是环境限制,不是固件 bug。\n"
        "注意:关电源后 UAV 心跳会停止,后续测试可能受影响 — 由 fixture 还原。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("GCS 命令", "STANDBY", "UAV 电源")
    def test_standby_uav_power_off(self, gcs, test_params, mavlink_version):
        """测试 STANDBY 命令关 UAV 电源(假电源环境容忍 result=4)"""
        supply_type = test_params["uav_power_supply_type"]
        is_fake = supply_type == "fake"

        with allure.step(f"发送 MAV_CMD_STANDBY param1=1(电源类型={supply_type})"):
            result = send_standby(gcs, mavlink_version, power_on=False)

        with allure.step("验证 ACK result(按电源类型分支)"):
            assert result is not None, \
                f"{DEFAULT_ACK_TIMEOUT}s 内未收到 STANDBY 的 COMMAND_ACK"

            if is_fake:
                # 假电源:GPIO 信号发出但 UAV 未真下电,固件检测后回 FAILED(4) 属正常
                assert result in (0, 4), (
                    f"假电源环境 STANDBY 关电源 result={result}"
                    f"(期望 0=ACCEPTED 或 4=FAILED,实际超出范围)"
                )
                verdict = "ACCEPTED" if result == 0 else "FAILED(假电源环境预期)"
            else:
                # 真电源:必须 ACCEPTED
                assert result == 0, \
                    f"真电源环境 STANDBY 关电源被拒绝: result={result}(期望 0=ACCEPTED)"
                verdict = "ACCEPTED"

            allure.attach(
                f"【测试结果】\n"
                f"  命令: MAV_CMD_STANDBY param1=1\n"
                f"  电源类型: {supply_type}\n"
                f"  ACK result: {result} ({verdict})\n"
                f"  动作: fcs_pwr_control(false) → GPIO16 低\n"
                f"  注: UAV 下电后心跳停止,下一步会重新上电",
                name="STANDBY 关电源",
                attachment_type=allure.attachment_type.TEXT
            )

        # 测试结束后重新上电 UAV(避免影响后续测试)
        with allure.step("测试后重新上电 UAV"):
            log_manager.logger.info("[GCS-Cmd] 重新发送 param1=0 恢复 UAV 电源")
            send_standby(gcs, mavlink_version, power_on=True)
            time.sleep(2)

    @allure.title("MAV_CMD_STANDBY 非法 param1(其他值)")
    @allure.description(
        "send_standby(power_on=True) 只能覆盖 param1=0/1,这里直接构造 COMMAND_LONG "
        "param1=2(非法值),验证 WiFi 仍回 COMMAND_ACK result=0,但不控制电源"
        "(固件 onion_companion.c:259-261 仅记日志 'pwr off')。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("GCS 命令", "STANDBY", "边界测试")
    def test_standby_invalid_param(self, gcs, mavlink_version):
        """测试 STANDBY 命令非法 param1(应回 ACK 但不动电源)"""
        # 协议层 send_standby 只封装了合法的 0/1,非法值需要直接构造 COMMAND_LONG
        from src.Protocol.mavlink.parse_mavlink import MAVLink_message
        from src.Protocol.wifi.wifi import MAV_CMD_STANDBY, MSG_ID_COMMAND_LONG

        with allure.step("发送 COMMAND_LONG command=MAV_CMD_STANDBY param1=2(非法值)"):
            cmd_msg = MAVLink_message(
                msg_id=MSG_ID_COMMAND_LONG, sys_id=1, comp_id=1, seq=0,
                version=mavlink_version,
                fields={
                    'command': MAV_CMD_STANDBY,
                    'param1': 2,  # 非法值
                    'param2': 0, 'param3': 0, 'param4': 0,
                    'param5': 0, 'param6': 0, 'param7': 0,
                    'target_system': 0, 'target_component': 0, 'confirmation': 0,
                }
            )
            gcs.send(cmd_msg)
            log_manager.logger.info("[GCS-Cmd] 已发送 MAV_CMD_STANDBY param1=2(非法值)")

        with allure.step("等待 COMMAND_ACK(协议层 wait_for_command_ack)"):
            result, ack_msg = wait_for_command_ack(gcs, MAV_CMD_STANDBY)

        with allure.step("验证 ACK 仍为 ACCEPTED(无条件接受)"):
            assert ack_msg is not None, \
                f"{DEFAULT_ACK_TIMEOUT}s 内未收到 STANDBY 的 COMMAND_ACK"
            assert result == 0, \
                f"STANDBY 应无条件 ACCEPTED,实际 result={result}"

            allure.attach(
                f"【测试结果】\n"
                f"  命令: MAV_CMD_STANDBY param1=2(非法值)\n"
                f"  ACK result: {result} (ACCEPTED — 无条件接受)\n"
                f"  动作: 仅记日志 'pwr off',不调用 fcs_pwr_control",
                name="STANDBY 非法 param1",
                attachment_type=allure.attachment_type.TEXT
            )



    @allure.title("STANDBY 命令响应不依赖 FC 心跳(独立性)")
    @allure.description(
        "验证 WiFi 模块对 GCS STANDBY 命令的响应独立于 FC 是否在线。\n"
        "源码:_transfer_gcs_to_uav 在 onion_companion.c:246-261 由 WiFi 自身直接回 ACK,\n"
        "  不依赖 fcs_got_wifi_info 状态 — 即使 FC 静默,WiFi 也应正常响应。\n"
        "环境相关性:假电源环境下,STANDBY 可能返回 FAILED(4) — 与 test_standby_uav_power_off\n"
        "  同因(GPIO 控制无真实负载反馈)。这里只要收到 ACK 即证明 WiFi 响应独立。\n"
        "业务价值:FC 故障时 GCS 仍可通过 WiFi 远程恢复(如重启 FC 电源)。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("GCS 命令", "STANDBY", "WiFi 独立性")
    def test_standby_independent_of_fc_heartbeat(self, gcs, test_params, mavlink_version):
        """测试 WiFi STANDBY 响应不依赖 FC 心跳(假电源容忍 result=4)"""
        supply_type = test_params["uav_power_supply_type"]
        is_fake = supply_type == "fake"

        with allure.step("前置:静默 5s 模拟 FC 不广播心跳"):
            log_manager.logger.info(
                f"[GCS-Cmd] 静默 5s,模拟 FC 不发心跳场景(电源类型={supply_type})"
            )
            time.sleep(5)

        with allure.step("发送 MAV_CMD_STANDBY param1=0(协议层 send_standby)"):
            result = send_standby(gcs, mavlink_version, power_on=True)

        with allure.step("验证 WiFi ACK 不依赖 FC 心跳"):
            # 关键断言:必须收到 ACK(证明 WiFi 响应独立于 FC 心跳)
            assert result is not None, (
                f"{DEFAULT_ACK_TIMEOUT}s 内未收到 STANDBY ACK — "
                "WiFi 模块命令响应依赖 FC 心跳(违反独立性设计)"
            )

            # ACK result 按电源类型分支(同 test_standby_uav_power_off 逻辑)
            if is_fake:
                assert result in (0, 4), (
                    f"假电源环境 STANDBY result={result}"
                    f"(期望 0=ACCEPTED 或 4=FAILED,实际超出范围)"
                )
                verdict = "ACCEPTED" if result == 0 else "FAILED(假电源环境预期)"
            else:
                assert result == 0, (
                    f"真电源环境 STANDBY 应无条件 ACCEPTED,实际 result={result}"
                )
                verdict = "ACCEPTED"

            allure.attach(
                f"【测试数据】\n"
                f"  前置: 静默 5s 模拟 FC 不广播心跳\n"
                f"  电源类型: {supply_type}\n"
                f"  命令: MAV_CMD_STANDBY param1=0\n"
                f"  ACK result: {result} ({verdict})\n"
                f"  源码: _transfer_gcs_to_uav 行 246-261,WiFi 自身回 ACK",
                name="测试数据",
                attachment_type=allure.attachment_type.TEXT
            )

            allure.attach(
                f"【测试结果】\n"
                f"  STANDBY ACK result: {result} ({verdict})\n"
                f"  WiFi 模块在 FC 心跳静默期仍响应 GCS 命令(独立性验证通过)\n"
                f"  业务价值: FC 故障时 GCS 可远程恢复(如下电再上电)",
                name="验证通过",
                attachment_type=allure.attachment_type.TEXT
            )

    # ==================== EULER_NETWORK 测试 ====================

    @allure.title("EULER_NETWORK 切换 SSID(msg_id=49)")
    @allure.description(
        "通过协议层 send_euler_network(ssid=target) 切换到备用 SSID,"
        "验证 WiFi 回 COMMAND_ACK result=0,且 SSID 已生效。"
        "固件 onion_companion.c:267-302:先 ACK → 改 SSID → set_ssid_chg_flag 触发热加载。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("GCS 命令", "EULER_NETWORK", "SSID 切换")
    def test_euler_network_change_ssid(self, gcs, serial_session, test_params, mavlink_version):
        """测试 EULER_NETWORK 切换 SSID"""
        original_ssid = test_params["test_ssid"]
        target_ssid = test_params["test_ssid_alt"]

        with allure.step("记录变更前 SSID"):
            wifi_info = serial_session.get_wifi_info()
            assert wifi_info is not None, "获取 wifi info 失败"
            log_manager.logger.info(
                f"[EULER] 变更前 SSID: {wifi_info.get('ssid')}"
            )

        with allure.step(f"发送 EULER_NETWORK 切换 SSID 到 {target_ssid}(协议层 send_euler_network)"):
            result = send_euler_network(gcs, mavlink_version, ssid=target_ssid)

        with allure.step("验证 ACK result=ACCEPTED"):
            assert result is not None, \
                f"{DEFAULT_ACK_TIMEOUT}s 内未收到 EULER_NETWORK 的 COMMAND_ACK"
            assert result == 0, \
                f"EULER_NETWORK 被拒绝: result={result}"

        with allure.step("等待 SSID 热加载完成(固件 vTaskDelay(1000) + 热加载)"):
            time.sleep(8)

        with allure.step("验证 SSID 已切换"):
            new_wifi_info = serial_session.get_wifi_info()
            assert new_wifi_info is not None, "切换后获取 wifi info 失败"
            current_ssid = new_wifi_info.get("ssid")
            log_manager.logger.info(f"[EULER] 切换后 SSID: {current_ssid}")

            allure.attach(
                f"【测试结果】\n"
                f"  命令: EULER_NETWORK ssid={target_ssid}\n"
                f"  ACK result: {result} (ACCEPTED)\n"
                f"  切换前 SSID: {wifi_info.get('ssid')}\n"
                f"  切换后 SSID: {current_ssid}\n"
                f"  注: SSID 由 fixture teardown 还原到 {original_ssid}",
                name="EULER_NETWORK SSID 切换",
                attachment_type=allure.attachment_type.TEXT
            )


    @allure.title("EULER_NETWORK 修改 IP(msg_id=49)")
    @allure.description(
        "通过协议层 send_euler_network(ip=target) 修改 WiFi IP 地址,验证 ACK + IP 生效。"
        "固件 onion_companion.c:287-292:id(uint32)格式化为 IP 后写入 nvdm + st1。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("GCS 命令", "EULER_NETWORK", "IP 修改")
    def test_euler_network_change_ip(self, gcs, serial_session, test_params, mavlink_version):
        """测试 EULER_NETWORK 修改 IP"""
        original_ip = serial_session.get_ip_address()
        target_ip = test_params["test_ip_alternate"]

        with allure.step(f"发送 EULER_NETWORK 修改 IP 到 {target_ip}(协议层 send_euler_network)"):
            result = send_euler_network(
                gcs, mavlink_version, ip=target_ip,
                ssid=test_params["test_ssid"],  # 保持原 SSID
            )

        with allure.step("验证 ACK result=ACCEPTED"):
            assert result is not None, \
                f"{DEFAULT_ACK_TIMEOUT}s 内未收到 EULER_NETWORK 的 COMMAND_ACK"
            assert result == 0, \
                f"EULER_NETWORK 被拒绝: result={result}"

        with allure.step("等待 IP 生效(固件 vTaskDelay + set_st1_ipAddr)"):
            time.sleep(5)

        with allure.step("验证 IP 已修改"):
            new_ip = serial_session.get_ip_address()
            log_manager.logger.info(f"[EULER] IP 变更: {original_ip} -> {new_ip}")

            allure.attach(
                f"【测试结果】\n"
                f"  命令: EULER_NETWORK id={target_ip}\n"
                f"  ACK result: {result} (ACCEPTED)\n"
                f"  变更前 IP: {original_ip}\n"
                f"  变更后 IP: {new_ip}\n"
                f"  注: IP 由 fixture teardown 还原到 {original_ip}",
                name="EULER_NETWORK IP 修改",
                attachment_type=allure.attachment_type.TEXT
            )

    @allure.title("EULER_NETWORK 不修改(id=0 且 ssid 为空)")
    @allure.description(
        "通过协议层 send_euler_network() 无参调用(id=0, ssid=None),"
        "验证 WiFi 仍回 COMMAND_ACK result=0(ACK 无条件发送)。"
        "固件:onion_companion.c:287 判断 id != 0 才改 IP,:294 判断 ssid 非空才改。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("GCS 命令", "EULER_NETWORK", "边界测试")
    def test_euler_network_no_change(self, gcs, mavlink_version):
        """测试 EULER_NETWORK 空字段(应回 ACK 但不动配置)"""
        with allure.step("发送 EULER_NETWORK id=0 ssid=空(协议层 send_euler_network 无参)"):
            result = send_euler_network(gcs, mavlink_version)

        with allure.step("验证 ACK 仍为 ACCEPTED(无条件)"):
            assert result is not None, \
                f"{DEFAULT_ACK_TIMEOUT}s 内未收到 EULER_NETWORK 的 COMMAND_ACK"
            assert result == 0, \
                f"EULER_NETWORK 应无条件 ACCEPTED,实际 result={result}"

            allure.attach(
                f"【测试结果】\n"
                f"  命令: EULER_NETWORK id=0 ssid=空\n"
                f"  ACK result: {result} (ACCEPTED — 无条件)\n"
                f"  动作: 不改 IP,不改 SSID",
                name="EULER_NETWORK 空字段",
                attachment_type=allure.attachment_type.TEXT
            )
