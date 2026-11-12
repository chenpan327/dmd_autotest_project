# coding: utf-8
"""
===============================================================================
                    S100 底软 BSP 时间同步测试脚本
===============================================================================
脚本编号: DMD_TEST_RDKS100_BSP_TSYNC_001
脚本版本: v1.0
创建日期: 2026-09-18
修改日期: 2026-09-18
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: RDKS100 (INDV1, S100 双 SoC: Acore Linux + MCU 小核)
测试类型: 底软功能验证测试 (Functional_Testing)
测试环境: Python 3.10, pytest, allure, SSH (paramiko)

测试目的:
验证 INDV1 (S100) 底软时间同步子系统 (TC-S100-TSYNC-01 ~ 04): dmd-bsp
modules/timesync 封装 hobot timesync HAL (多时钟源 + PPS 快照), 是飞控/图传
多源数据时间对齐的基础。覆盖: 系统时钟源与单调性 → 时间同步样例 → PTP 硬件
时间戳能力在位 → PPS 秒脉冲输入。测试点从源码反推 (待与《底软Linux BSP
测试点分解》核对)。

前置条件:
1. 测试环境准备:
   - DUT 已启动且 dmd-bsp deb 已安装 (sample 程序在 ipc_bin_dir, 默认
     /usr/hobot/bin), 主机经 SSH 访问板端 (config.json INDV1 段)
   - ssh_session / board_info / bsp_params fixture 已就绪 (conftest 提供)
2. 环境依赖与 skip 条款:
   - TSYNC-02 时间同步样例: 依赖 sp-samples deb (默认 /app/timesync_demo/),
     不在位则 skip
   - TSYNC-03 PTP: 依赖 SoC 以太网控制器 PTP 硬件能力暴露的 /dev/ptp*,
     设备不在位则 skip (板级/内核配置差异)
   - TSYNC-04 PPS: 需真实 PPS 源接入, config INDV1.pps_test_enabled=true 才跑
3. 判定语义: pytest 原生断言, 板端命令输出挂 Allure 附件

测试步骤:
1. [TSYNC-01 test_clock_source_and_monotonic] 系统时钟源: current_clocksource
   非空 → date +%s 可读且接近测试机时间 (±1h, NTP 未同步也不该差出时区级) →
   /proc/uptime 连续两次读数单调递增
2. [TSYNC-02 test_timesync_sample] 时间同步样例: bsp_params.timesync_sample_bin
   可执行 → 运行 (timeout 兜底) → 退出码 0
3. [TSYNC-03 test_ptp_device_present] PTP 能力在位: /sys/class/ptp/ 下存在
   ptp 设备且 /dev/ptp* 节点存在
4. [TSYNC-04 test_pps_source] PPS 秒脉冲 (需显式开启): 运行 pps_probe_cmd
   (默认 ppstest /dev/pps0) → 输出含 assert 事件序列

预期结果（与测试步骤一一对应）:
1. [TSYNC-01] 时钟源在位、系统时间合理、uptime 单调递增
2. [TSYNC-02] 时间同步样例正常退出 (输出挂附件, 断言口径首跑后校准)
3. [TSYNC-03] PTP 字符设备在位 (多源时间戳能力可用)
4. [TSYNC-04] PPS 事件持续上报 (秒脉冲输入链路通)

===============================================================================
测试结论:
时间同步 4 个测试点全部实现自动化, 硬件依赖场景显式 skip 并经 config
显式开关管控, 断言结果与板端输出见 Allure 报告各用例及其附件。
===============================================================================
"""
import re
import time

import allure
import pytest

from utils.logger import log_manager


@allure.epic("S100 底软测试")
@allure.feature("时间同步")
class TestIndv1BspTimesync:
    """底软 Linux BSP 时间同步测试点 (时钟源/样例/PTP/PPS)"""


    @allure.story("时钟源")
    @allure.title("TC-S100-TSYNC-01 系统时钟源在位且 uptime 单调递增")
    @allure.description(
        "[板端命令] current_clocksource 非空 (Acore 预期 arch_sys_counter 系); "
        "date +%s 与测试机时间偏差 <1h (NTP 未同步也不该差出时区/年代级); "
        "/proc/uptime 连续两次读数单调递增 (单调时钟基准正常)。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "时间同步", "时钟源")
    def test_clock_source_and_monotonic(self, ssh_session):
        with allure.step("current_clocksource 非空"):
            code, out = ssh_session.exec_cmd_quiet(
                "cat /sys/devices/system/clocksource/clocksource0/current_clocksource"
            )
            assert code == 0 and out.strip(), (
                f"current_clocksource 不可读或为空: {out!r}"
            )
            clocksource = out.strip()
            log_manager.logger.info(f"[TSYNC] 时钟源: {clocksource}")
        with allure.step("系统时间与测试机偏差 <1h"):
            code, out = ssh_session.exec_cmd_quiet("date +%s")
            assert code == 0 and out.strip().isdigit(), f"date +%s 异常: {out!r}"
            drift = abs(int(out.strip()) - int(time.time()))
            assert drift < 3600, (
                f"板端系统时间与测试机偏差 {drift}s (≥1h) — RTC/NTP 全部失效时"
                f"飞控-图传-云平台时间对齐无从谈起"
            )
        with allure.step("/proc/uptime 单调递增"):
            ups = []
            for _ in range(2):
                code, out = ssh_session.exec_cmd_quiet("cat /proc/uptime")
                assert code == 0, f"/proc/uptime 不可读: {out!r}"
                ups.append(float(out.split()[0]))
                time.sleep(0.3)
            assert ups[1] > ups[0], f"uptime 未单调递增: {ups}"
        log_manager.logger.info(f"[TSYNC] 时钟源 OK: source={clocksource}, uptime={ups}")

    @allure.story("时间同步样例")
    @allure.title("TC-S100-TSYNC-02 时间同步样例 sample_timesync 正常退出")
    @allure.description(
        "[板端命令] 运行 bsp_params.timesync_sample_bin (默认 "
        "/app/timesync_demo/sample_timesync, hobot-sp-samples 时间同步验证样例): "
        "退出码 0 视为通过。样例输出格式以板上实际为准, 首跑后细化断言口径。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "时间同步", "样例")
    def test_timesync_sample(self, ssh_session, bsp_params):
        binary = bsp_params["timesync_sample_bin"]
        code, out = ssh_session.exec_cmd_quiet(f"test -x {binary}")
        if code != 0:
            pytest.skip(f"{binary} 不存在 — sp-samples deb 未安装或路径不同")
        timeout_s = int(bsp_params["timesync_sample_timeout_s"])
        with allure.step(f"运行 {binary} (timeout {timeout_s}s 兜底)"):
            code, out = ssh_session.exec_cmd_quiet(
                f"timeout -s INT {timeout_s} {binary} < /dev/null",
                timeout=timeout_s + 60,
            )
            allure.attach(out, name="timesync_sample_output", attachment_type=allure.attachment_type.TEXT)
            if "Usage" in out or "usage" in out:
                pytest.fail(
                    f"时间同步样例打印 usage 退出 (code={code}) — CLI 参数与预期不符, "
                    f"请按 -h 用法核对 bsp_params.timesync_sample_bin 调用方式:\n{out[-600:]}"
                )
            assert code == 0, (
                f"时间同步样例异常退出 (code={code}):\n{out[-800:]}"
            )
        log_manager.logger.info(f"[TSYNC] 时间同步样例 PASS, 输出尾部: {out[-200:]!r}")

    @allure.story("PTP能力")
    @allure.title("TC-S100-TSYNC-03 PTP 硬件时间戳能力在位 (/dev/ptp*)")
    @allure.description(
        "[板端命令] /sys/class/ptp/ 下存在 ptp 设备 (SoC 网络控制器 PTP 硬件时钟, "
        "多源时间戳/时间同步 HAL 的硬件基座) 且对应 /dev/ptp* 字符节点存在。"
        "板级/内核配置差异导致不在位时 skip。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "时间同步", "PTP")
    def test_ptp_device_present(self, ssh_session):
        with allure.step("扫描 /sys/class/ptp/"):
            code, out = ssh_session.exec_cmd_quiet("ls /sys/class/ptp/ 2>/dev/null")
            if code != 0 or not out.strip():
                pytest.skip(
                    "/sys/class/ptp/ 无 ptp 设备 — 本板级/内核配置未暴露 PTP 硬件时钟"
                )
            ptp_names = out.split()
        with allure.step("确认 /dev/ptp* 节点"):
            code, out = ssh_session.exec_cmd_quiet(
                "ls /dev/ptp* 2>/dev/null"
            )
            assert code == 0 and out.strip(), (
                f"sysfs 有 {ptp_names} 但 /dev/ptp* 节点缺失 — udev/驱动注册异常"
            )
        log_manager.logger.info(f"[TSYNC] PTP 在位: {out.split()}")

    @allure.story("PPS输入")
    @allure.title("TC-S100-TSYNC-04 PPS 秒脉冲事件上报 (需显式开启)")
    @allure.description(
        "[板端命令] 运行 bsp_params.pps_probe_cmd (默认 ppstest /dev/pps0, pps-tools): "
        "输出应持续出现 assert 事件 (秒脉冲输入链路通)。⚠ 需真实 PPS 源接入 — "
        "config INDV1.pps_test_enabled=true 才运行, 默认 skip。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "时间同步", "PPS")
    def test_pps_source(self, ssh_session, bsp_params):
        if not bsp_params.get("pps_test_enabled"):
            pytest.skip(
                "需真实 PPS 源接入 — 接好后置 config INDV1.pps_test_enabled=true"
            )
        cmd = bsp_params["pps_probe_cmd"]
        with allure.step(f"运行 PPS 探针: {cmd}"):
            code, out = ssh_session.exec_cmd_quiet(
                f"timeout -s INT 15 {cmd}", timeout=30
            )
            allure.attach(out, name="pps_probe_output", attachment_type=allure.attachment_type.TEXT)
        with allure.step("断言 assert 事件上报"):
            events = re.findall(r"assert\s+\d+\.\d+\s+seq\s+\d+", out)
            assert events, (
                f"PPS 无 assert 事件上报 (探针输出 {out[-300:]!r}) — "
                f"PPS 源未接 / 极性不符 / 设备号不符 (核对 pps_probe_cmd)"
            )
        log_manager.logger.info(f"[TSYNC] PPS OK: 事件样例 {events[:2]}")
