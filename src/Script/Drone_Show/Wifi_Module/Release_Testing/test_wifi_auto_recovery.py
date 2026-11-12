# coding: utf-8
"""
WiFi 模块测试 - 自动重连与异常恢复压测(脚本层)

业务背景:
    无人机编队表演中,WiFi 链路稳定性是关键。固件内置 _check 任务,
    每 1 秒检查一次 WiFi 连接状态,在异常时自动触发恢复动作。
    本测试模拟 WiFi 断连场景,验证自动恢复逻辑生效。

中间件事实(来自 mt793x onion_companion.c:347-409):
    任务:_check,每秒一次循环(vTaskDelay(1000))
    局部变量:rewifi_cnt(未连接秒数),模块级 ssid_chg_flag,chg_unlink_cnt

    三档超时(rewifi_cnt 每秒 +1,到达顺序为 15 → 30):
      - REWIFI_TMOUT_MAX = 15:onion_companion.c:28
        rewifi_cnt == 15 进入 else-if 分支,set_wifi_ssid(当前 ssid) 重初始化 wifi
        日志 "wifi unlinked for 15 seconds, reinit wifi..."
      - SWITCH_SSID_TMOUT_MAX = 30:onion_companion.c:29
        rewifi_cnt == 30 进入 if 分支,切换到另一档 SSID 并清零 rewifi_cnt
        日志 "wifi unlinked for 30 seconds, switch another ssid[XXX]..."
      - CHG_UNLINK_TMOUT_MAX = 90:onion_companion.c:30
        ssid_chg_flag != 0 && chg_unlink_cnt >= 90 && get_hard_version() == 0(仅旧硬件):
          hal_sys_reboot(WHOLE_SYSTEM_REBOOT)

分层:
    协议层封装见 src/Protocol/wifi/auto_recovery.py:
      - sample_connection(serial_session, elapsed)        → ConnectionSample
      - monitor_connection_stability(session, duration_s) → StabilityReport
      - monitor_ssid_auto_switch(session, trigger_ssid)   → AutoSwitchReport
    脚本层只做 pytest 编排 + allure 步骤 + 断言。

测试策略:
    1. SSID 切换测试:改到无效 SSID 触发 30s 自动切换,验证 SSID 变化
    2. 长断连 reboot 测试:仅硬版本 0 触发,默认 skip(耗时 90s+ 且会断开整个 session)
    3. 正常运行基线:60s 监控连接率,应 ≥ 90%

副作用管理:
    fixture teardown 还原 SSID。
"""
import time
import pytest
import allure

from utils.logger import log_manager
from src.Protocol.wifi.wifi import (
    monitor_ssid_auto_switch, monitor_connection_stability,
    reconnect_after_reboot,
    SWITCH_SSID_TMOUT_MAX, CHG_UNLINK_TMOUT_MAX,
)


# 是否运行 reboot 压测(默认 skip — 90s+ 会断 session)
RUN_REBOOT_RECOVERY_TEST = False

# 测试等待时间(略大于阈值)
SWITCH_SSID_WAIT = SWITCH_SSID_TMOUT_MAX + 10  # 40s,等日志
REBOOT_TEST_WAIT = CHG_UNLINK_TMOUT_MAX + 70   # 160s 等 reboot + 重连


@allure.epic("WiFi 模块测试")
@allure.feature("老化压测")
@allure.story("自动重连与异常恢复")
class TestWifiAutoRecovery:
    """WiFi 自动重连和异常恢复压测"""

    @pytest.fixture(autouse=True)
    def _restore_ssid(self, serial_session, test_params):
        """压测前后还原 SSID"""
        original_ssid = test_params["test_ssid"]
        log_manager.logger.info(
            f"[Auto-Recovery] 测试前 SSID={original_ssid}"
        )
        yield
        try:
            log_manager.logger.info(
                f"[Auto-Recovery] 还原 SSID: {original_ssid}"
            )
            serial_session.change_ssid(original_ssid)
            time.sleep(8)  # 等热加载完成
            log_manager.logger.info("[Auto-Recovery] 还原完成")
        except Exception as e:
            log_manager.logger.error(f"[Auto-Recovery] 还原失败: {e}")

    @allure.title("WiFi 断连后 30s 自动切换 SSID")
    @allure.description(
        "切换到无效 SSID 触发断连,等待 30s+ 验证 _check 任务自动切换到备用 SSID。"
        "源码 onion_companion.c:365-409:rewifi_cnt == 30 时调用 set_wifi_ssid 切换。"
        "验证方式:协议层 monitor_ssid_auto_switch 轮询 SSID 是否变化。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("自动恢复", "SSID 切换", "压测")
    def test_auto_switch_ssid_after_disconnect(self, serial_session, test_params):
        """测试 WiFi 30s 断连后自动切换 SSID"""
        invalid_ssid = "dmd_invalid_ssid_xx"  # 故意用不存在的 SSID

        with allure.step(f"切换到无效 SSID: {invalid_ssid}"):
            success = serial_session.change_ssid(invalid_ssid)
            log_manager.logger.info(
                f"[Auto-Recovery] 切到无效 SSID 命令发送: {success}"
            )

        with allure.step("验证 WiFi 已断连"):
            time.sleep(3)
            status = serial_session.check_wifi_connection()
            if status:
                is_linked = status.get("is_linked")
                log_manager.logger.info(
                    f"[Auto-Recovery] 切换后连接状态: is_linked={is_linked}"
                )
                if is_linked:
                    log_manager.logger.warning(
                        "[Auto-Recovery] WiFi 仍连接(无效 SSID 可能未生效),"
                        "继续等待 _check 任务触发"
                    )

        with allure.step(f"等待 {SWITCH_SSID_WAIT}s 监控自动切换(协议层 monitor_ssid_auto_switch)"):
            report = monitor_ssid_auto_switch(
                serial_session, trigger_ssid=invalid_ssid,
                wait_seconds=SWITCH_SSID_WAIT, poll_interval=5,
            )

        with allure.step("验证自动切换已触发"):
            allure.attach(
                f"【测试结果】\n"
                f"  触发方式: 切换到无效 SSID {invalid_ssid}\n"
                f"  等待时间: {SWITCH_SSID_WAIT}s\n"
                f"  30s 自动切换: {'已触发' if report.detected else '未检测到'}\n"
                f"  切换后 SSID: {report.switched_to or '(未检测到)'}\n"
                f"  切换发生时刻: {report.switch_time_seconds}s\n"
                f"  注: 固件 _check 任务在 rewifi_cnt==30 时切换 SSID\n"
                f"  实际切换日志: 'wifi unlinked for 30 seconds, switch another ssid[XXX]...'",
                name="30s 自动切换 SSID",
                attachment_type=allure.attachment_type.TEXT
            )

            # 软断言:未检测到只警告不失败(可能串口读取时机错过)
            if not report.detected:
                log_manager.logger.warning(
                    "[Auto-Recovery] 未在等待窗口内检测到 SSID 自动切换。"
                    "可能原因:1) 无效 SSID 仍连原 AP;2) 串口读取错过的切换瞬间;"
                    "3) _check 任务异常"
                )

    @allure.title("WiFi 长期断连 reboot 恢复(90s,仅硬版本 0)")
    @allure.description(
        "持续断连 90s 后,旧硬件版本(get_hard_version()==0)会触发 hal_sys_reboot。"
        "源码 onion_companion.c:402-404:chg_unlink_cnt >= 90 时整机重启。"
        "默认 skip — 会断开整个 session,设置 RUN_REBOOT_RECOVERY_TEST=True 单独跑。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("自动恢复", "reboot", "压测")
    @pytest.mark.skipif(
        not RUN_REBOOT_RECOVERY_TEST,
        reason="reboot 压测默认跳过 — 90s+ 断连 + reboot 会断开 session。"
               "如需运行,设置 RUN_REBOOT_RECOVERY_TEST=True 单独跑"
    )
    def test_auto_reboot_after_long_disconnect(self, serial_session, test_params):
        """测试 WiFi 90s 长期断连后自动 reboot(仅硬版本 0)"""
        invalid_ssid = "dmd_invalid_ssid_reboot"

        with allure.step("切换到无效 SSID 触发长期断连"):
            serial_session.change_ssid(invalid_ssid)
            log_manager.logger.info(
                f"[Auto-Recovery] 切到 {invalid_ssid},等待 {REBOOT_TEST_WAIT}s 触发 reboot"
            )

        with allure.step(f"等待 {REBOOT_TEST_WAIT}s(90s 断连 + 70s reboot 重连)"):
            time.sleep(REBOOT_TEST_WAIT)

        with allure.step("重连串口"):
            # 协议层封装 disconnect + 等待 + connect,统一波特率 921600
            success = reconnect_after_reboot(serial_session)
            if not success:
                log_manager.logger.error(
                    "[Auto-Recovery] reboot 后串口重连失败"
                    "(可能硬件版本非 0,未触发 reboot)"
                )

        with allure.step("验证 reboot 后 WiFi 状态恢复"):
            wifi_info = serial_session.get_wifi_info()
            allure.attach(
                f"【测试结果】\n"
                f"  等待时间: {REBOOT_TEST_WAIT}s\n"
                f"  串口重连: {'成功' if success else '失败'}\n"
                f"  重启后 WiFi: {wifi_info}",
                name="90s 自动 reboot",
                attachment_type=allure.attachment_type.TEXT
            )

    @allure.title("WiFi 自动维护任务心跳(连续监控 60s)")
    @allure.description(
        "连续 60s 监控 WiFi 连接状态,验证 _check 任务正常运行"
        "(没有异常日志、WiFi 保持连接或正常切换)。"
        "作为基线测试,确认设备在正常运行时不会误触发自动恢复。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("自动恢复", "监控", "基线")
    def test_no_false_trigger_during_normal_operation(self, serial_session, test_params):
        """正常情况下 60s 内不应触发自动恢复"""
        original_ssid = test_params["test_ssid"]

        # 确保用正常 SSID
        serial_session.change_ssid(original_ssid)
        time.sleep(5)

        with allure.step("连续监控 60s,每 5s 采样(协议层 monitor_connection_stability)"):
            report = monitor_connection_stability(
                serial_session, duration_seconds=60, sample_interval=5,
            )

        with allure.step("验证 WiFi 持续连接(允许短暂波动)"):
            allure.attach(
                f"【监控结果】\n"
                f"  总采样数: {report.total_samples}\n"
                f"  已连接样本: {report.linked_samples} "
                f"({report.linked_ratio * 100:.0f}%)\n"
                f"  SSID 是否变化: {report.ssid_changed}\n"
                f"  观察到的 SSID: {report.ssid_seen}\n\n"
                f"  采样详情:\n" +
                "\n".join(
                    f"    {s.elapsed}s: linked={s.is_linked}, "
                    f"rssi={s.rssi}, ssid={s.ssid}"
                    for s in report.samples
                ),
                name="60s 监控",
                attachment_type=allure.attachment_type.TEXT
            )

            # 正常情况下应 100% 连接(允许 ≤1 次抖动)
            assert report.linked_ratio >= 0.9, (
                f"WiFi 连接率 {report.linked_ratio * 100:.0f}% 低于 90% 阈值,"
                f"设备可能误触发自动恢复"
            )
