# coding: utf-8
"""
===============================================================================
                        S100 底软 BSP DDR 测试脚本
===============================================================================
脚本编号: DMD_TEST_RDKS100_BSP_DDR_001
脚本版本: v1.1
创建日期: 2026-09-14
修改日期: 2026-09-17
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: RDKS100 (INDV1, S100 双 SoC: Acore Linux + MCU 小核)
测试类型: 底软功能验证测试 (Functional_Testing)
测试环境: Python 3.10, pytest, allure, SSH (paramiko)

测试目的:
验证 INDV1 (S100) 底软 BSP 的 DDR 功能与可靠性 (TC-S100-DDR-01 ~ 05):
容量识别/数据正确性压测/温度监控/负载温升/带宽。测试点从源码反推
(待与《底软Linux BSP 测试点分解》DDR 表核对)。

前置条件:
1. 测试环境准备:
   - DUT 已启动, 主机经 SSH 访问板端 (config.json INDV1 段)
   - ssh_session / bsp_params fixture 已就绪 (conftest 提供)
2. 板上依赖 (均为可选, 缺失时 skip 或降级):
   - memtester (全模式位校验) / stress-ng (--vm 降级方案) — apt 可装
   - mbw (带宽, 仅记录) — apt 或源码编译
   - DDR 温度 sensor 为 TMP112 (dmd_temp 驱动, i2c-8 上 0x48/0x49, hwmon
     name=dmdtemp), 依赖 MCU i2c 代理对端 (config mcu_proxy_enabled)
3. 判定语义: pytest 原生断言, 压测/采样输出挂 Allure 附件

测试步骤:
1. [DDR-01 test_ddr_capacity] 容量识别: 读 /proc/meminfo MemTotal, 断言 ≥
   ddr_min_total_mb (默认 4096MB); 内核 Memory: 行仅记录 (S100 为 BPU/VDSP/
   CMA 预留, MemTotal < 物理焊装容量属正常, 故用下限而非精确匹配)
2. [DDR-02 test_ddr_stress] 数据正确性: 优先 memtester 压 ddr_memtester_mb
   1 轮; 缺失时降级 stress-ng --vm 60s; 两者都无则 skip
3. [DDR-03 test_ddr_temperature_monitor] 温度监控: hwmon dmdtemp 读数在
   [-40,125]°C; thermal zone 中 DDR 相关 zone 的 trip point 合法
   (dts: alert 75°C / crit 95°C)
4. [DDR-04 test_ddr_temp_under_load] 负载温升: stress-ng --vm 压载
   ddr_load_duration_s (默认 60s), 每 5s 采样温度, 全程 ≤ ddr_temp_max_c
   (默认 85°C)
5. [DDR-05 test_ddr_bandwidth] 带宽: mbw 压 100MB 记录拷贝带宽 (无 mbw 则
   skip), 断言仅防明显异常

预期结果（与测试步骤一一对应）:
1. [DDR-01] MemTotal ≥ 下限 (实测值与内核报告记录入日志)
2. [DDR-02] 压测退出码 0 且输出无 FAILURE (无内存位错误)
3. [DDR-03] 温度读数物理合理, DDR thermal zone trip point 配置合法
4. [DDR-04] 压载全程温度 ≤ 阈值, 采样序列挂 Allure 附件
5. [DDR-05] mbw 运行成功且解析到带宽 >0 (绝对值与 SoC/编译选项强相关, 记录为主)

===============================================================================
测试结论:
DDR 5 个测试点全部实现自动化 (可选工具缺失场景显式 skip 或降级并注明),
断言结果与压测输出见 Allure 报告各用例及其附件。
===============================================================================
"""
import re
import time

import allure
import pytest

from utils.logger import log_manager


def _ddr_temps(ssh_session):
    """读取 DDR 温度 hwmon (毫摄氏度), 返回 [(来源, 毫度)]

    注意: dmd_temp 注册的 hwmon name 是 "dmdtemp" 而非 "tmp112"
    (drivers/temp/dmd_temp.c: devm_hwmon_device_register_with_groups(dev, "dmdtemp", ...)),
    兼容匹配两种命名。
    """
    cmd = (
        'for n in /sys/class/hwmon/hwmon*/name; do '
        'if grep -qiE "dmdtemp|tmp112" "$n" 2>/dev/null; then '
        'd=$(dirname "$n"); echo "$d $(cat $d/temp1_input 2>/dev/null)"; fi; done'
    )
    code, out = ssh_session.exec_cmd_quiet(cmd, timeout=20)
    if code != 0:
        return []
    readings = []
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) == 2 and parts[1].lstrip("-").isdigit():
            readings.append((parts[0], int(parts[1])))
    return readings


@allure.epic("S100 底软测试")
@allure.feature("DDR BSP")
class TestIndv1BspDdr:
    """底软 Linux BSP DDR 测试点 (容量/正确性/温度/温升/带宽)"""


    @allure.story("容量")
    @allure.title("TC-S100-DDR-01 容量识别: MemTotal ≥ 下限")
    @allure.description(
        "[板端命令] /proc/meminfo MemTotal 须 ≥ ddr_min_total_mb (默认 4096MB)。"
        "注意 S100 固件为 BPU/VDSP/CMA 预留内存, MemTotal < 物理焊装容量属正常, "
        "故用下限断言 + 实测值记录, 物理容量核对看启动日志 Memory: 行。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("S100", "底软", "DDR", "容量")
    def test_ddr_capacity(self, ssh_session, bsp_params):
        with allure.step("读取 /proc/meminfo MemTotal"):
            code, out = ssh_session.exec_cmd_quiet("grep MemTotal /proc/meminfo")
            assert code == 0, f"MemTotal 读取失败: {out!r}"
            m = re.search(r"MemTotal:\s+(\d+)\s*kB", out)
            assert m, f"MemTotal 解析失败: {out!r}"
            total_mb = int(m.group(1)) // 1024
        with allure.step("断言容量下限"):
            floor_mb = int(bsp_params["ddr_min_total_mb"])
            assert total_mb >= floor_mb, (
                f"MemTotal={total_mb}MB 低于下限 {floor_mb}MB — "
                f"检查设备树 memory 节点/固件预留是否异常"
            )
        # 启动日志里的物理容量信息 (记录用, 不判失败)
        code, meminfo_line = ssh_session.exec_cmd_quiet(
            "dmesg | grep -iE 'Memory:.*available' | tail -1"
        )
        log_manager.logger.info(
            f"[DDR容量] MemTotal={total_mb}MB (下限 {floor_mb}MB); "
            f"内核报告: {meminfo_line.strip()!r}"
        )


    @allure.story("数据正确性")
    @allure.title("TC-S100-DDR-02 压测无错误: memtester / stress-ng --vm")
    @allure.description(
        "[板端命令] 优先 memtester (全模式位校验) 压 ddr_memtester_mb 1 轮; "
        "缺失时降级 stress-ng --vm; 两者都无则 skip (镜像可用 apt install memtester)。"
        "断言退出码 0 且输出无 FAILURE。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "DDR", "压测")
    def test_ddr_stress(self, ssh_session, bsp_params):
        mb = int(bsp_params["ddr_memtester_mb"])
        code, out = ssh_session.exec_cmd_quiet("command -v memtester")
        if code == 0 and out.strip():
            with allure.step(f"memtester {mb}MB 1 轮"):
                code, out = ssh_session.exec_cmd_quiet(
                    f"memtester {mb}M 1", timeout=600
                )
                allure.attach(
                    out[-3000:], name="memtester_output",
                    attachment_type=allure.attachment_type.TEXT,
                )
                assert code == 0, f"memtester 退出码 {code} — 检查输出中的 FAILURE"
                assert "FAILURE" not in out, f"memtester 检出内存错误:\n{out[-2000:]}"
            log_manager.logger.info(f"[DDR压测] memtester {mb}MB 全模式 PASS")
            return
        code, out = ssh_session.exec_cmd_quiet("command -v stress-ng")
        if code == 0 and out.strip():
            with allure.step(f"stress-ng --vm 压 {mb}MB x 60s (memtester 缺失, 降级)"):
                code, out = ssh_session.exec_cmd_quiet(
                    f"stress-ng --vm 1 --vm-bytes {mb}M -t 60s --vm-hang 0", timeout=180
                )
                allure.attach(
                    out[-3000:], name="stressng_vm_output",
                    attachment_type=allure.attachment_type.TEXT,
                )
                assert code == 0, f"stress-ng --vm 退出码 {code} (stress-ng 压测失败返回非 0): {out[-500:]!r}"
            log_manager.logger.info(f"[DDR压测] stress-ng --vm {mb}MB PASS (memtester 缺失, 建议部署)")
            return
        pytest.skip("板上无 memtester 也无 stress-ng — apt install memtester 后重跑")


    @allure.story("温度")
    @allure.title("TC-S100-DDR-03 温度监控: dmdtemp(tmp112) 读数与 thermal trip point")
    @allure.description(
        "[板端命令] dmd_temp (TMP112@i2c-8 0x48/0x49, hwmon name=dmdtemp) 读数须在物理区间 "
        "[-40,125]°C; thermal zone 中应存在 DDR 相关 zone (dts: ddr0-thermal) 且 trip point 合法。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "DDR", "温度")
    def test_ddr_temperature_monitor(self, ssh_session):
        with allure.step("hwmon dmdtemp 读数在物理区间"):
            readings = _ddr_temps(ssh_session)
            if not readings:
                pytest.skip(
                    "未找到 dmdtemp hwmon — dmd_temp 依赖 MCU i2c 代理 "
                    "(当前 s100_mcu 固件无 ins4 对端, 见 config mcu_proxy_enabled)"
                )
            for hwmon, mc in readings:
                celsius = mc / 1000.0
                assert -40.0 <= celsius <= 125.0, (
                    f"{hwmon} DDR 温度超物理区间: {celsius}°C"
                )
        with allure.step("查找 DDR 相关 thermal zone 及 trip point"):
            code, out = ssh_session.exec_cmd_quiet(
                'for z in /sys/class/thermal/thermal_zone*; do '
                't=$(cat $z/type 2>/dev/null); echo "$z type=$t"; '
                'for tp in $z/trip_point_*_temp; do v=$(cat $tp 2>/dev/null); '
                '[ -n "$v" ] && echo "  $(basename $tp)=$v"; done; done'
            )
            assert code == 0, f"thermal zone 遍历失败: {out!r}"
            zones = {}
            cur = None
            for ln in out.splitlines():
                if "type=" in ln:
                    cur = ln.split()[0]
                    zones[cur] = {"type": ln.split("type=")[-1].strip(), "trips": []}
                elif cur and "=" in ln:
                    v = ln.rsplit("=", 1)[1]
                    if v.isdigit():
                        zones[cur]["trips"].append(int(v))
            ddr_zones = {
                z: info for z, info in zones.items()
                if re.search(r"ddr|tmp112|dmd", info["type"], re.IGNORECASE)
            }
            if not ddr_zones:
                log_manager.logger.warning(
                    f"[DDR温度] 未找到 type 含 ddr/tmp112/dmd 的 thermal zone, "
                    f"现有 zone: { {z: i['type'] for z, i in zones.items()} } — 请核对 dts 命名"
                )
            else:
                for z, info in ddr_zones.items():
                    valid = [t for t in info["trips"] if 0 < t <= 110000]
                    assert valid, f"{z}({info['type']}) trip point 异常: {info['trips']}"
        temps_str = ", ".join(f"{h}={m / 1000:.1f}°C" for h, m in readings)
        log_manager.logger.info(f"[DDR温度] {temps_str}; ddr zones: {list(ddr_zones) or '未识别(已告警)'}")


    @allure.story("温度")
    @allure.title("TC-S100-DDR-04 负载温升: 压载下温度持续受控")
    @allure.description(
        "[板端命令] stress-ng --vm 压载 ddr_load_duration_s (默认 60s), 每 5s 采样 TMP112 温度, "
        "全程 ≤ ddr_temp_max_c (默认 85°C, dts crit=95°C 留余量)。板上无 stress-ng 则 skip。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "DDR", "温升")
    def test_ddr_temp_under_load(self, ssh_session, bsp_params):
        mb = int(bsp_params["ddr_memtester_mb"])
        duration = int(bsp_params["ddr_load_duration_s"])
        temp_max = float(bsp_params["ddr_temp_max_c"])
        code, out = ssh_session.exec_cmd_quiet("command -v stress-ng")
        if not (code == 0 and out.strip()):
            pytest.skip("板上无 stress-ng — 温升场景需要 (apt install stress-ng)")
        readings = _ddr_temps(ssh_session)
        if not readings:
            pytest.skip(
                "tmp112/dmdtemp 不可读 — 依赖 MCU i2c 代理 "
                "(当前 s100_mcu 固件无 ins4 对端, 见 config mcu_proxy_enabled)"
            )
        with allure.step(f"stress-ng --vm {mb}MB 压载 {duration}s 并采样温度"):
            ssh_session.exec_cmd_quiet(
                f"nohup stress-ng --vm 1 --vm-bytes {mb}M --vm-hang 0 "
                f"-t {duration + 5}s >/dev/null 2>&1 &"
            )
            deadline = time.time() + duration
            samples = []
            while time.time() < deadline:
                for hwmon, mc in _ddr_temps(ssh_session):
                    celsius = mc / 1000.0
                    samples.append((hwmon, celsius))
                    assert celsius <= temp_max, (
                        f"压载中 {hwmon} DDR 温度 {celsius:.1f}°C 超过阈值 {temp_max}°C"
                    )
                time.sleep(5)
        peak = max(c for _, c in samples) if samples else float("nan")
        allure.attach(
            "\n".join(f"{h} {c:.1f}" for h, c in samples),
            name="ddr_temp_samples", attachment_type=allure.attachment_type.TEXT,
        )
        log_manager.logger.info(f"[DDR温升] 压载 {duration}s 峰值 {peak:.1f}°C (阈值 {temp_max}°C)")


    @allure.story("带宽")
    @allure.title("TC-S100-DDR-05 带宽测试: mbw (可选)")
    @allure.description(
        "[板端命令] mbw 压 100MB 记录拷贝带宽 (板上无 mbw 则 skip)。"
        "带宽绝对值与 SoC/编译选项强相关, 本用例以记录为主, 断言仅防明显异常(≤0)。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "DDR", "带宽")
    def test_ddr_bandwidth(self, ssh_session):
        code, out = ssh_session.exec_cmd_quiet("command -v mbw")
        if not (code == 0 and out.strip()):
            pytest.skip("板上无 mbw — 如需带宽数据请部署 (apt install mbw 或源码编译)")
        with allure.step("mbw 100MB 测带宽"):
            code, out = ssh_session.exec_cmd_quiet("mbw 100 -q", timeout=120)
            allure.attach(out, name="mbw_output", attachment_type=allure.attachment_type.TEXT)
            assert code == 0, f"mbw 运行失败 (code={code}): {out[-300:]!r}"
        rates = [float(x) for x in re.findall(r"([\d.]+)\s*M[iB]?B/[sS]", out)]
        assert rates and max(rates) > 0, f"mbw 输出未解析到带宽: {out[-500:]!r}"
        log_manager.logger.info(f"[DDR带宽] 峰值 {max(rates):.1f} MiB/s")
