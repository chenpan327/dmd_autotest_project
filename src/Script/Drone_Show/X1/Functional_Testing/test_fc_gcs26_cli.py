# coding: utf-8

r"""
GCS-26 调试终端（p0×5 + p1×10）— CLI P0 五项 + P1 抽样

业务背景：
    p0×5：终端交互(ls)、任务状态(ps)、CPU 占用(ps)、堆栈占用(ps)、模块
    初始化(istate)——ps 一条命令的输出同时覆盖任务/CPU/堆栈 3 个功能点；
    p1 抽样：传感器健康(sheal)、电池(bat)、通信链路(mav 0)、系统日志
    (dmsg)、飞行日志启停(log start/stop)、参数查改存(pp/sp/svp)。
    完整 51 项 CLI 命令见 test_mavlink_cli.py（断言口径同源）；
    电机顺序检查 mtcheck 涉及电机转动，永不自动执行。

命令协议速查（预期回显要点 = 断言依据）：
    ┌ ls        目录条目 "数字 名称" 行，正则 \d+\s+(\S+) 可解出条目
    ├ ps        ⚠️ 循环刷新命令（收集后必须 q 退出，2026-09-11 漏发 q
    │           导致刷屏污染后续 5 个用例）；输出含 "Heap" 字段 +
    │           核心任务行（CLI/IDLE）
    ├ istate    关键模块字段 module/sdcard/param/log/mission/assist 至少 1
    ├ sheal     关键传感器 imu/baro/compass/gps/battery/tele 至少 1
    ├ bat       "sum_voltage : x" / "current : x" 可正则解析；值域
    │           0<sv<30、-60<cur<60（台架限流电源 sv≈0.02V 亦通过）
    ├ mav 0     循环刷新的交互命令——收集后必须发 q 退出（q 无 ACK）
    ├ dmsg      非空回显
    ├ log start 确认文案 "ok: starting a log" 或 "log will write into"
    │           （真机实锤两种都出现过）
    ├ log stop  确认文案 "ok: stopping a log"
    └ pp/sp/svp 参数查改存：单参 pp <名> 秒回（⚠️ 无参 pp 全量 dump 8s
                截断坑见 GCS-14）；sp 语法 = "sp 名: 值"（⚠️ 冒号分隔，
                空格分隔固件不认，2026-09-11 实测），成功回 "found param"；
                svp 也要带名 = "svp <名>"（裸 svp 只回命令回声），成功回
                "Save '<名>' OK"

    用例（一命令一用例）：
    - test_gcs26_terminal_ls / task_ps / module_istate     P0 三用例
    - test_gcs26_sensor_health / battery / comm_mav /
      system_dmsg / flight_log / param_pp_svp              P1 六用例
"""

import re
import time

import pytest
import allure

from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    FCBasicBase, log_manager, _cli_failed, CONSOLE_PROMPT, SETTLE_SHORT)

# 参数查改存被测参数（固定，GCS-14 同款先例：调试开关改值无飞行影响；
# ⚠️ 无参 pp dump 取参会选中注册表首个 VEL_CHECK_TEMP 且截断，勿回退）
GCS26_PARAM_NAME = 'INDOOR_DEBUG'


@allure.feature("FC 基础功能 P0/P1")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC")
@pytest.mark.functional
class TestGcs26Cli(FCBasicBase):
    """GCS-26 调试终端（p0×5 + p1×10）"""

    # ==================================================================
    # 公共辅助
    # ==================================================================

    def _cli_interactive(self, cmd, collect_time=3.0):
        """发循环刷新型交互命令，收集后发 q 退出（q 无 ACK，尽力而为）"""
        resp = self._cli(cmd, timeout=collect_time)
        self._cli("q", timeout=2.0)
        return resp

    # ==================================================================
    # P0 三用例（覆盖 5 个功能点：ps 输出兼任务状态/CPU/堆栈）
    # ==================================================================

    @allure.story("GCS-26 调试终端 P0")
    @allure.title("GCS-26 终端交互：ls 目录浏览")
    def test_gcs26_terminal_ls(self):
        """验证 ls 命令：目录条目可解析（GCS-26 p0 终端交互）"""
        with allure.step("发送 ls 并核对目录条目"):
            resp = self._cli("ls", timeout=8.0)
            assert resp and CONSOLE_PROMPT in resp, (
                f"ls 无完整回显: {resp[:200]}")
            items = re.findall(r"\d+\s+(\S+)", resp)
            log_manager.log_and_attach(
                f"ls 条目 {len(items)} 项: {items[:20]}", "目录条目")
            assert items, f"ls 返回的文件列表为空: {resp[:200]}"

    @allure.story("GCS-26 调试终端 P0")
    @allure.title("GCS-26 任务状态/CPU/堆栈：ps")
    def test_gcs26_task_ps(self):
        """验证 ps 命令：Heap 字段 + 核心任务（GCS-26 p0 任务/CPU/堆栈）"""
        with allure.step("发送 ps 收集并核对（循环刷新命令，q 退出）"):
            resp = self._cli_interactive("ps", collect_time=4.0)
            assert resp, "ps 无输出"
            log_manager.log_and_attach(resp[:800], "ps 输出（已 q 退出）")
            assert "Heap" in resp, f"ps 缺少 Heap 字段: {resp[:200]}"
            assert "CLI" in resp or "IDLE" in resp or "cli" in resp, (
                f"ps 未找到核心任务（CLI/IDLE）: {resp[:200]}")

    @allure.story("GCS-26 调试终端 P0")
    @allure.title("GCS-26 模块初始化状态：istate")
    def test_gcs26_module_istate(self):
        """验证 istate 命令：关键模块字段（GCS-26 p0 模块初始化）"""
        with allure.step("发送 istate 并核对关键模块"):
            resp = self._cli("istate", timeout=8.0)
            assert resp and CONSOLE_PROMPT in resp, (
                f"istate 无完整回显: {resp[:200]}")
            log_manager.log_and_attach(resp[:600], "istate 输出")
            low = resp.lower()
            found = [m for m in ("module", "sdcard", "param", "log",
                                 "mission", "assist") if m in low]
            assert found, f"istate 未返回任何关键模块状态: {resp[:200]}"

    # ==================================================================
    # P1 六用例（抽样）
    # ==================================================================

    @allure.story("GCS-26 调试终端 P1")
    @allure.title("GCS-26 传感器健康：sheal")
    def test_gcs26_sensor_health(self):
        """验证 sheal 命令：关键传感器字段命中（GCS-26 p1 抽样）"""
        with allure.step("发送 sheal 并核对关键传感器"):
            resp = self._cli("sheal", timeout=8.0)
            assert resp and CONSOLE_PROMPT in resp, (
                f"sheal 无完整回显: {resp[:200]}")
            log_manager.log_and_attach(resp[:600], "sheal 输出")
            low = resp.lower()
            found = [s for s in ("imu", "baro", "compass", "gps",
                                 "battery", "tele") if s in low]
            assert found, f"sheal 未返回任何关键传感器状态: {resp[:200]}"

    @allure.story("GCS-26 调试终端 P1")
    @allure.title("GCS-26 电池信息：bat")
    def test_gcs26_battery(self):
        """验证 bat 命令：电压/电流可解析且在值域（GCS-26 p1 抽样）"""
        with allure.step("发送 bat 并解析电压/电流"):
            resp = self._cli("bat", timeout=8.0)
            assert resp and CONSOLE_PROMPT in resp, (
                f"bat 无完整回显: {resp[:200]}")
            log_manager.log_and_attach(resp[:600], "bat 输出")
            sv = re.search(r'sum_voltage\s*:\s*([-+]?\d+\.?\d*)', resp)
            cur = re.search(r'current\s*:\s*([-+]?\d+\.?\d*)', resp)
            assert sv, f"bat 缺少 sum_voltage 字段: {resp[:200]}"
            assert cur, f"bat 缺少 current 字段: {resp[:200]}"
            sum_voltage, current = float(sv.group(1)), float(cur.group(1))
            # 值域与 liaoyutao 用例同源；台架限流电源 sv≈0.02V 亦在域内
            assert 0.0 < sum_voltage < 30.0, f"电池总电压异常: {sum_voltage}V"
            assert -60.0 < current < 60.0, f"电池电流异常: {current}A"

    @allure.story("GCS-26 调试终端 P1")
    @allure.title("GCS-26 通信链路质量：mav 0（交互命令）")
    def test_gcs26_comm_mav(self):
        """验证 mav 命令：循环输出可收集，q 可退出（GCS-26 p1 抽样）"""
        with allure.step("发送 mav 0 收集链路质量"):
            resp = self._cli_interactive("mav 0", collect_time=3.0)
            assert resp, "mav 0 无输出"
            log_manager.log_and_attach(resp[:600], "mav 输出（已 q 退出）")

    @allure.story("GCS-26 调试终端 P1")
    @allure.title("GCS-26 系统日志查看：dmsg")
    def test_gcs26_system_dmsg(self):
        """验证 dmsg 命令：非空回显（GCS-26 p1 抽样）"""
        with allure.step("发送 dmsg 并核对非空"):
            resp = self._cli("dmsg", timeout=8.0)
            assert resp, "dmsg 无回显"
            log_manager.log_and_attach(resp[:600], "dmsg 输出")

    @allure.story("GCS-26 调试终端 P1")
    @allure.title("GCS-26 飞行日志启停：log start → log stop")
    def test_gcs26_flight_log(self):
        """验证 log start/stop 命令：确认文案（GCS-26 p1 抽样）"""
        with allure.step("log start → 核对启动确认文案"):
            resp_start = self._cli("log start", timeout=8.0)
            low = resp_start.lower()
            log_manager.log_and_attach(resp_start[:300], "log start 回显")
            assert ("ok: starting a log" in low
                    or "log will write into" in low), (
                f"log start 未确认: {resp_start[:200]}")
        with allure.step("log stop → 核对停止确认文案"):
            time.sleep(SETTLE_SHORT)
            resp_stop = self._cli("log stop", timeout=8.0)
            low = resp_stop.lower()
            log_manager.log_and_attach(resp_stop[:300], "log stop 回显")
            assert "ok: stopping a log" in low, (
                f"log stop 未确认: {resp_stop[:200]}")

    @allure.story("GCS-26 调试终端 P1")
    @allure.title("GCS-26 参数查改存：pp → sp → svp（CLI 通道）")
    def test_gcs26_param_pp_svp(self):
        """验证 pp/sp/svp CLI 链路：改值 0 → 恢复 → 落盘（GCS-26 p1 抽样）

        与 GCS-14（MAVLink 参数协议）为同一参数系统的两条通道；
        被测参数固定 INDOOR_DEBUG（调试开关，改值无飞行影响）。
        """
        name = GCS26_PARAM_NAME
        with allure.step(f"pp {name} 读原值"):
            pp_out = self._cli(f"pp {name}", timeout=8.0)
            assert not _cli_failed(pp_out), (
                f"pp {name} 查询失败: {pp_out[:200]}")
            m = re.search(rf'{name}\s*[:=]\s*(-?[\d.]+)', pp_out)
            assert m, f"pp 单参查询未见 {name}: {pp_out[:200]}"
            origin = float(m.group(1))
            log_manager.log_and_attach(
                f"原值: {name} = {origin}\n{pp_out[:200]}", "pp 读原值")

        with allure.step(f"sp {name}: 0 → 回读核对"):
            # sp 语法带冒号（"sp 名: 值"，liaoyutao 同款；空格分隔不认）
            sp_out = self._cli(f"sp {name}: 0", timeout=8.0)
            low = sp_out.lower()
            log_manager.log_and_attach(sp_out[:300], "sp 改值回显")
            assert "found param" in low and "can't find param" not in low, (
                f"sp 未命中参数: {sp_out[:200]}")
            pp2 = self._cli(f"pp {name}", timeout=8.0)
            m2 = re.search(rf'{name}\s*[:=]\s*(-?[\d.]+)', pp2)
            assert m2 and float(m2.group(1)) == 0.0, (
                f"改值未生效: {pp2[:200]}")

        with allure.step(f"恢复 sp {name}: {origin:g} → svp 落盘"):
            sp_out = self._cli(f"sp {name}: {origin:g}", timeout=8.0)
            assert "found param" in sp_out.lower(), (
                f"恢复写入失败: {sp_out[:200]}")
            # svp 也要带参数名（裸 svp 只回命令回声，2026-09-11 实测），
            # 成功文案 "Save '<名>' OK"（真机 fixture 握手回显同款格式）
            svp_out = self._cli(f"svp {name}", timeout=8.0)
            low = svp_out.lower()
            log_manager.log_and_attach(
                f"恢复 sp 回显:\n{sp_out[:200]}\nsvp 回显:\n{svp_out[:200]}",
                "恢复与落盘")
            assert "save" in low and "ok" in low, (
                f"svp 未确认保存: {svp_out[:200]}")
