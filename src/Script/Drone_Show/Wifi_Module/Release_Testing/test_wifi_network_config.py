# coding: utf-8
"""
WiFi 模块测试 - 网络配置

业务背景:
    WiFi 模块需要支持动态网络配置以适应不同的部署环境。本测试通过串口命令修改
    IP/掩码/网关、切换 SSID、切换 AP/STA 模式、设置休眠模式。

中间件事实(来自 mt793x dmd_cicd.c:162-177):
    - chgIp 单参 (1 个参数):仅写 IP,掩码/网关**保留原值**(nvdm 和 st1 运行时都不动)
    - chgIp 三参 (IP + mask + gw):完整写入 nvdm 和 st1 运行时
    - chgIp 两参:落入 else 分支,打印 usage 并返回错误
    - chgOpMode:取值 ap/sta/rpt,调用 wifi_config_set_opmode + wifi_config_reload_setting 热加载,不重启
    - chgSsid:写 nvdm + 运行时 ssid + ssid_chg_flag,需等待重连

副作用管理:
    本测试修改的所有配置(IP/SSID/opmode)都会在 fixture teardown 中还原,
    即使测试中途失败也会还原,避免污染后续测试。
"""
import time
import pytest
import allure

from utils.logger import log_manager


@allure.epic("WiFi 模块测试")
@allure.feature("功能测试")
@allure.story("网络配置")
class TestWifiNetworkConfig:
    """WiFi 网络配置测试类"""

    # 配置变更后等待生效的时间(秒)
    IP_PROPAGATION_DELAY = 2.0
    SSID_RECONNECT_DELAY = 5.0
    OPMODE_SWITCH_DELAY = 3.0

    @pytest.fixture(autouse=True)
    def _preserve_network_state(self, serial_session, test_params):
        """每个测试前后保存/还原网络状态(IP/SSID/opmode)。

        autouse=True,所有测试用例都会自动应用。
        即使测试中途失败,yield 之后的还原逻辑也会执行。
        """
        original_ip = None
        original_ssid = test_params["test_ssid"]
        original_opmode = "sta"  # 测试期望默认是 STA 模式

        # 测试前:尽量读取当前 IP(可能因前面测试失败而读不到,不强制)
        try:
            original_ip = serial_session.get_ip_address()
            log_manager.logger.info(f"[WiFi-Preserve] 测试前 IP={original_ip}, SSID={original_ssid}, opMode={original_opmode}")
        except Exception as e:
            log_manager.logger.warning(f"[WiFi-Preserve] 读取初始 IP 失败(忽略): {e}")

        yield

        # 测试后:还原 IP / opMode / SSID
        log_manager.logger.info("[WiFi-Preserve] 还原网络状态...")
        try:
            # 1. 先还原 opMode 到 sta(AP 模式下后续命令可能不可达)
            serial_session.change_op_mode(original_opmode)
            time.sleep(self.OPMODE_SWITCH_DELAY)
            # 2. 还原 SSID
            serial_session.change_ssid(original_ssid)
            time.sleep(self.SSID_RECONNECT_DELAY)
            # 3. 还原 IP(只在原 IP 已知时)
            if original_ip:
                serial_session.change_ip_config(original_ip)
                time.sleep(self.IP_PROPAGATION_DELAY)
            log_manager.logger.info(f"[WiFi-Preserve] 还原完成 -> IP={original_ip}, SSID={original_ssid}")
        except Exception as e:
            log_manager.logger.error(f"[WiFi-Preserve] 还原失败(后续测试可能受影响): {e}")

    # ------------------------------------------------------------------
    @allure.title("仅修改 IP 地址(chgIp 单参)")
    @allure.description("发送 chgIp 单参命令仅写 IP,掩码和网关保留原值(源码 dmd_cicd.c:162-177)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("WiFi", "网络配置", "chgIp", "单参")
    def test_change_ip_only(self, serial_session, test_params):
        # 用 config 里 test_gateway 同段的 IP,避免跨子网后失联
        original_ip = serial_session.get_ip_address()
        test_ip = test_params["test_ip_alternate"]

        with allure.step(f"发送 chgIp 单参命令: IP={test_ip}"):
            result = serial_session.change_ip_config(test_ip)

        with allure.step("验证命令返回值"):
            assert result is not None, "change_ip_config 返回 None(命令无响应或解析失败)"
            assert isinstance(result, dict), f"返回值应为 dict,实际 {type(result).__name__}"
            assert result.get("changed_ip") == test_ip, \
                f"changed_ip 不匹配: 期望 {test_ip}, 实际 {result.get('changed_ip')}"

        with allure.step(f"等待 {self.IP_PROPAGATION_DELAY}s 后验证新 IP 生效"):
            time.sleep(self.IP_PROPAGATION_DELAY)
            new_ip = serial_session.get_ip_address()
            assert new_ip == test_ip, \
                f"新 IP 未生效: 期望 {test_ip}, 实际 {new_ip} (chgIp 可能未真正写入 nvdm)"

        # 记录原始 IP 给 teardown 用(虽然 fixture 已经处理)
        log_manager.logger.info(f"[WiFi-Test] IP 变更生效: {original_ip} -> {new_ip}")


    @allure.title("修改 IP + 掩码 + 网关(chgIp 三参)")
    @allure.description("发送 chgIp ip mask gw 命令完整修改网络参数")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("WiFi", "网络配置", "chgIp", "三参")
    def test_change_ip_full(self, serial_session, test_params):
        test_ip = test_params["test_ip_alternate_full"]
        test_mask = "255.240.0.0"
        test_gateway = test_params["test_gateway"]

        with allure.step(f"发送 chgIp 三参命令: {test_ip} {test_mask} {test_gateway}"):
            result = serial_session.change_ip_config(test_ip, test_mask, test_gateway)

        with allure.step("验证命令返回值"):
            assert result is not None, "change_ip_config 返回 None"
            assert result.get("changed_ip") == test_ip, \
                f"changed_ip 不匹配: 期望 {test_ip}, 实际 {result.get('changed_ip')}"

        with allure.step(f"等待 {self.IP_PROPAGATION_DELAY}s 后验证新 IP 生效"):
            time.sleep(self.IP_PROPAGATION_DELAY)
            new_ip = serial_session.get_ip_address()
            assert new_ip == test_ip, f"新 IP 未生效: 期望 {test_ip}, 实际 {new_ip}"


    @allure.title("切换 SSID(chgSsid)")
    @allure.description("切换到备用 SSID,等待重连后检查状态,再还原")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "网络配置", "chgSsid")
    def test_change_ssid(self, serial_session, test_params):
        test_ssid = test_params["test_ssid_alt"]
        original_ssid = test_params["test_ssid"]

        with allure.step(f"发送 chgSsid 命令: {test_ssid}"):
            success = serial_session.change_ssid(test_ssid)
            assert success is True, f"切换 SSID 到 {test_ssid} 失败"

        with allure.step(f"等待 {self.SSID_RECONNECT_DELAY}s 重连"):
            time.sleep(self.SSID_RECONNECT_DELAY)

        with allure.step("检查连接状态(允许切换失败,仅记录)"):
            status = serial_session.check_wifi_connection()
            if status:
                log_manager.logger.info(
                    f"[WiFi-Test] SSID={test_ssid} 连接状态: linked={status.get('is_linked')}, "
                    f"rssi={status.get('rssi')}"
                )
            else:
                log_manager.logger.warning(f"[WiFi-Test] 切换到 {test_ssid} 后无法获取连接状态")

        # SSID 还原由 fixture teardown 完成,这里不再重复


    @allure.title("设置不休眠模式(config write STA PSMode 0)")
    @allure.description(
        "发送 config write STA PSMode 0 命令禁用休眠,验证命令返回 success。"
        "注:无回读命令,仅依赖返回值。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "网络配置", "PSMode")
    def test_set_no_sleep_mode(self, serial_session):
        with allure.step("发送 config write STA PSMode 0"):
            success = serial_session.set_sta_ps_mode(0)
            assert success is True, "设置不休眠模式失败"

        with allure.step("验证设置生效(读回 PSMode)"):
            # 中间件未提供读 PSMode 的命令,这里只能依赖命令返回 success
            log_manager.logger.info("[WiFi-Test] PSMode=0 设置成功(无回读命令,依赖返回值)")


    @allure.title("切换 STA 模式(chgOpMode sta)")
    @allure.description(
        "发送 chgOpMode sta,等待热加载后验证串口仍可获取 IP(链路保持)。"
        "源码依据:dmd_cicd.c chgOpMode 调用 wifi_config_reload_setting 热加载,不重启。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "网络配置", "chgOpMode", "STA")
    def test_change_to_sta_mode(self, serial_session):
        with allure.step("发送 chgOpMode sta"):
            success = serial_session.change_op_mode("sta")
            assert success is True, "切换到 STA 模式失败"

        with allure.step(f"等待 {self.OPMODE_SWITCH_DELAY}s 热加载完成"):
            time.sleep(self.OPMODE_SWITCH_DELAY)

        with allure.step("验证 STA 模式下仍可通信"):
            # 热加载后 IP 链路应保持,串口命令可正常响应
            ip = serial_session.get_ip_address()
            assert ip is not None, "切换 STA 后无法获取 IP(链路可能未恢复)"


    @allure.title("切换 AP 模式(chgOpMode ap)")
    @allure.description(
        "发送 chgOpMode ap,等待热加载完成。"
        "AP 模式还原由 fixture teardown 完成(先切回 sta 再继续)。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "网络配置", "chgOpMode", "AP")
    def test_change_to_ap_mode(self, serial_session):
        with allure.step("发送 chgOpMode ap"):
            success = serial_session.change_op_mode("ap")
            assert success is True, "切换到 AP 模式失败"

        with allure.step(f"等待 {self.OPMODE_SWITCH_DELAY}s 热加载完成"):
            time.sleep(self.OPMODE_SWITCH_DELAY)

        # AP 模式还原由 fixture teardown 完成(它会先切回 sta 再继续)
        log_manager.logger.info("[WiFi-Test] AP 模式测试完成,fixture teardown 将自动切回 STA")
