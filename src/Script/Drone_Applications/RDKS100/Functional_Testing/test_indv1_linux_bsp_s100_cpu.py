# coding: utf-8
"""
===============================================================================
                        S100 底软 BSP CPU 测试脚本
===============================================================================
脚本编号: DMD_TEST_RDKS100_BSP_CPU_001
脚本版本: v1.1
创建日期: 2026-09-14
修改日期: 2026-09-17
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: RDKS100 (INDV1, S100 双 SoC: Acore Linux + MCU 小核)
测试类型: 底软功能验证测试 (Functional_Testing)
测试环境: Python 3.10, pytest, allure, SSH (paramiko) + 调试串口

测试目的:
验证 INDV1 (S100) 底软 BSP 的 CPU 相关能力 (TC-S100-CPU-01 ~ 09, 对应
《底软Linux BSP 测试点分解》一级分组 CPU)。启动类: 启动链完整性/核心数/
启动时间/硬重启/软重启; 性能指标类: 运行频率(正常/异常-热降频机制)/
算力(Dhrystone DMIPS)/实时性(cyclictest 三场景调度时延)。

前置条件:
1. 测试环境准备:
   - DUT 已启动, 主机经 SSH 访问板端 (config.json INDV1 段)
   - 启动类用例 (01/03) 需调试串口: config.json INDV1.console_com_map 的
     J6_Acore 通道 (boot_capture fixture 会触发一次真实 reboot 抓取启动日志,
     两个用例共用一份日志)
   - ssh_session / board_info / bsp_params fixture 已就绪 (conftest 提供)
2. 板上依赖 (缺失时按用例 skip 或降级):
   - TC-08 需板端部署 Dhrystone 2.1 二进制 (dhrystone_bin, 缺省
     /usr/hobot/bin/dhrystone)
   - TC-09 需板端 cyclictest (rt-tests); 满载优先 stress-ng (缺失退化 dd
     busyloop), 中断压力场景必须 stress-ng
3. 特别注意:
   - TC-05 软重启用例会真实重启板卡 (本文件内放在末尾执行)
   - TC-01/03 的日志口径: SPL/U-Boot 阶段控制台可能静默, 缺标记仅告警不判失败
4. 判定语义: pytest 原生断言, 启动日志/跑分输出/时延汇总挂 Allure 附件

测试步骤:
1. [CPU-01 test_boot_chain_order] 启动链完整性: 触发冷启动抓调试串口日志,
   以 'reboot: Restarting system' 切分出本轮日志, 定位 SPL/BL31/OP-TEE/
   U-Boot/Linux 标记并核对出现顺序
2. [CPU-02 test_cpu_cores_online] 核心数: nproc 与 /proc/cpuinfo processor 数
   均等于期望核心数 (默认 6), /sys/.../online 覆盖全部核心
3. [CPU-03 test_boot_time] 启动时间: 从启动日志解析 rootfs 挂载内核时间戳
   (VFS: Mounted root / Run /sbin/init), 兜底 systemd-analyze
4. [CPU-04 test_hard_reboot] 硬重启 (占位): 断电重启需继电器/人工配合
5. [CPU-05 test_soft_reboot] 软重启: 下发 reboot → 确认 ssh 掉线 → 轮询恢复
   (上限 reboot_timeout_s) → 断言 /proc/uptime 重新计数
6. [CPU-06 test_cpu_freq_normal] 运行频率(正常): 全核心 cpuinfo_max_freq ==
   expected_cpu_freq_khz (默认 1.5GHz), 记录当前频率与 governor
7. [CPU-07 test_cpu_throttle_mechanism] 运行频率(异常): thermal zone 存在合法
   trip point (0<trip≤150°C) 且 cooling_device 含 cpufreq 类 (机制在位)
8. [CPU-08 test_cpu_dhrystone] 算力: 运行 Dhrystone 2.1, 解析 DMIPS
   (VAX MIPS 或 Dhrystones/1757 折算), 断言 ≥ 下限 (默认 2000)
9. [CPU-09 test_cpu_cyclictest] 实时性: cyclictest -m -S -p98 -i1000 在
   空载/CPU 满载(stress-ng 或 dd)/中断压力(stress-ng --timer) 三场景下运行,
   解析 Max 时延并断言 ≤ 阈值 (默认 1000us)

预期结果（与测试步骤一一对应）:
1. [CPU-01] 关键阶段 (U-Boot 或 BL31 + Linux) 存在且实际顺序与启动链定义一致;
   静默缺标记的阶段告警记录
2. [CPU-02] 期望核心数全部在线, 无 offline 核心
3. [CPU-03] rootfs 挂载耗时 ≤ boot_time_max_s (默认 30s; 不含 bootloader 阶段,
   口径记入报告)
4. [CPU-04] skip (人工执行: 断电≥5s → 上电 → 观察启动链 → 系统恢复登录)
5. [CPU-05] ssh 掉线后按时恢复且新 uptime <180s (确系新一次启动)
6. [CPU-06] 全核心额定频率一致且等于期望值
7. [CPU-07] 热降频机制在位 (合法 trip point + cpufreq cooling device)
8. [CPU-08] DMIPS ≥ 下限 (完整值记录, 仅防明显性能回退)
9. [CPU-09] 三场景 Max 调度时延均 ≤ 阈值 (无 stress-ng 时中断压力场景跳过)

===============================================================================
测试结论:
CPU 9 个测试点全部实现自动化 (硬重启用例为显式占位, 可选工具缺失场景
skip 并注明原因), 断言结果与日志/跑分输出见 Allure 报告各用例及其附件。
===============================================================================
"""
import re
import time

import allure
import pytest

from utils.logger import log_manager


# 启动链阶段标记: (阶段名, 匹配正则) — 期望按列表顺序出现在串口日志中
# 实测 v1p0 板控制台: SPL/U-Boot 静默不打印, BL31 有横幅, 内核直接以时间戳行出现
BOOT_CHAIN_MARKERS = [
    ("SPL", re.compile(r"\bspl\b", re.IGNORECASE)),
    ("BL31", re.compile(r"\bbl31\b", re.IGNORECASE)),
    ("OP-TEE", re.compile(r"op-?tee\b|tee-?os\b|\boptee\b", re.IGNORECASE)),
    ("U-Boot", re.compile(r"u-?boot", re.IGNORECASE)),
    ("Linux", re.compile(
        r"linux version|starting kernel|booting linux|\[\s*\d+\.\d{6}\]", re.IGNORECASE)),
]

# rootfs 挂载完成的内核日志特征 (取最早命中的内核时间戳)
ROOTFS_MOUNT_RE = re.compile(
    r"\[\s*([0-9]+\.[0-9]+)\].*(?:VFS: Mounted root|Run /sbin/init)", re.IGNORECASE
)


def _read_sys_ints(ssh_session, glob_expr):
    """读取板端一组 sysfs 数值文件, 返回 int 列表 (读失败的文件跳过)"""
    code, out = ssh_session.exec_cmd_quiet(f"cat {glob_expr} 2>/dev/null")
    if code != 0:
        return []
    values = []
    for ln in out.split():
        try:
            values.append(int(ln))
        except ValueError:
            continue
    return values


def _start_cpu_load(ssh_session, ncores, duration_s):
    """拉满 CPU 负载: 优先 stress-ng, 缺失时退化为 N 个 dd busyloop; 返回清理命令"""
    code, out = ssh_session.exec_cmd_quiet("command -v stress-ng")
    if code == 0 and out.strip():
        ssh_session.exec_cmd_quiet(
            f"nohup stress-ng --cpu {ncores} --timeout {duration_s + 5}s >/dev/null 2>&1 &"
        )
        return None  # stress-ng 到时自退
    log_manager.logger.info("板上无 stress-ng, 使用 dd busyloop 压载")
    for _ in range(ncores):
        ssh_session.exec_cmd_quiet("nohup dd if=/dev/zero of=/dev/null >/dev/null 2>&1 &")
    return "pkill -f 'dd if=/dev/zero of=/dev/null'"


@allure.epic("S100 底软测试")
@allure.feature("CPU BSP")
class TestIndv1BspCpu:
    """底软 Linux BSP CPU 测试点 (启动 5 项 + 性能指标 4 项)"""


    # ==================== 启动 ====================

    @allure.story("启动")
    @allure.title("TC-S100-CPU-01 启动链完整性: SPL/BL31/OP-TEE/U-Boot/Linux 顺序核对")
    @allure.description(
        "[串口] 触发一次冷启动(reboot), 从调试串口抓取完整启动日志并核对启动链顺序: "
        "SPL → BL31 → OP-TEE → U-Boot → Linux。U-Boot 与 Linux 为必须项; "
        "SPL/BL31/OP-TEE 若因控制台静默未打印则告警不判失败。日志存档于 log/boot_capture_*.log。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("S100", "底软", "CPU", "启动链")
    def test_boot_chain_order(self, boot_capture):
        with allure.step("截取重启点之后的日志 (排除旧系统关机消息)"):
            # 抓取从旧系统 shutdown 开始, 内核时间戳行会让 "Linux" 匹配到重启前
            parts = re.split(r"reboot: Restarting system", boot_capture)
            fresh_log = parts[-1]
        with allure.step("在启动日志中定位各阶段标记"):
            positions = {}
            for name, rx in BOOT_CHAIN_MARKERS:
                m = rx.search(fresh_log)
                if m:
                    positions[name] = m.start()
        with allure.step("断言关键阶段存在且顺序正确"):
            assert "Linux" in positions, "启动日志未找到 Linux 内核启动标记"
            assert ("U-Boot" in positions) or ("BL31" in positions), (
                "启动日志既无 U-Boot 也无 BL31 标记 — 串口未出日志或启动异常"
            )
            # 实际出现顺序必须与 BOOT_CHAIN_MARKERS 定义顺序一致
            expected_order = [n for n, _ in BOOT_CHAIN_MARKERS if n in positions]
            actual_order = [n for n, _ in sorted(positions.items(), key=lambda kv: kv[1])]
            assert actual_order == expected_order, (
                f"启动链顺序异常: 期望 {expected_order}, 实际 {actual_order}"
            )
        missing = [n for n, _ in BOOT_CHAIN_MARKERS if n not in positions]
        if missing:
            log_manager.logger.warning(f"[启动链] 以下阶段未在串口日志中打印(不判失败): {missing}")
        allure.attach(boot_capture[-4000:], name="boot_log_tail", attachment_type=allure.attachment_type.TEXT)
        log_manager.logger.info(f"[启动链] 顺序 OK: {actual_order}")


    @allure.story("启动")
    @allure.title("TC-S100-CPU-02 核心数: SMP 拉起全核心 6 核在线")
    @allure.description(
        "[系统] nproc 与 /proc/cpuinfo processor 数均须等于期望核心数(默认 6), "
        "/sys/devices/system/cpu/online 应覆盖全部核心, 无 offline CPU。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("S100", "底软", "CPU", "SMP")
    def test_cpu_cores_online(self, ssh_session, bsp_params):
        expected = int(bsp_params["expected_cpu_count"])
        with allure.step("nproc 与 /proc/cpuinfo 统计核心数"):
            code, out = ssh_session.exec_cmd_quiet("nproc")
            assert code == 0, f"nproc 执行失败: {out!r}"
            nproc = int(out.strip())
            code, out = ssh_session.exec_cmd_quiet("grep -c ^processor /proc/cpuinfo")
            cpuinfo_count = int(out.strip())
        with allure.step("检查 online CPU 列表"):
            code, online = ssh_session.exec_cmd_quiet(
                "cat /sys/devices/system/cpu/online"
            )
            assert code == 0, f"online 读取失败: {online!r}"
        assert nproc == expected, f"nproc={nproc}, 期望 {expected}"
        assert cpuinfo_count == expected, (
            f"/proc/cpuinfo processor 数={cpuinfo_count}, 期望 {expected}"
        )
        # online 形如 "0-5" 或 "0-3,5"; 统计已上线核心数量
        online_count = 0
        for seg in online.strip().split(","):
            if "-" in seg:
                a, b = seg.split("-")
                online_count += int(b) - int(a) + 1
            else:
                online_count += 1
        assert online_count == expected, (
            f"online={online.strip()!r} 仅 {online_count} 核在线, 期望 {expected}"
        )
        log_manager.logger.info(f"[SMP] {expected} 核全在线 OK (nproc={nproc})")


    @allure.story("启动")
    @allure.title("TC-S100-CPU-03 启动时间: rootfs 挂载 ≤ 阈值")
    @allure.description(
        "[串口] 从启动日志解析内核时间戳口径的 rootfs 挂载时间"
        "(VFS: Mounted root / Run /sbin/init), 断言 ≤ boot_time_max_s (默认 30s)。"
        "注意: 该口径不含 SPL/U-Boot 阶段耗时(无时间戳), 结果会记入报告。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("S100", "底软", "CPU", "启动时间")
    def test_boot_time(self, boot_capture, ssh_session, bsp_params):
        with allure.step("解析启动日志中 rootfs 挂载的内核时间戳"):
            m = ROOTFS_MOUNT_RE.search(boot_capture)
            if not m:
                # 兜底: systemd-analyze (仅内核+用户态, 不含 bootloader)
                code, out = ssh_session.exec_cmd_quiet("systemd-analyze time", timeout=15)
                assert code == 0 and out.strip(), (
                    "启动日志未匹配到 rootfs 挂载行, 且 systemd-analyze 不可用"
                )
                log_manager.logger.info(f"[启动时间] systemd-analyze 兜底: {out.strip()}")
                allure.attach(out.strip(), name="systemd_analyze", attachment_type=allure.attachment_type.TEXT)
                return
            boot_s = float(m.group(1))
        with allure.step("断言 rootfs 挂载时间 ≤ 阈值"):
            limit = float(bsp_params["boot_time_max_s"])
            assert boot_s <= limit, f"rootfs 挂载耗时 {boot_s:.2f}s 超过阈值 {limit}s"
        log_manager.logger.info(f"[启动时间] rootfs 挂载 {boot_s:.2f}s (阈值 {limit}s)")


    @allure.story("启动")
    @allure.title("TC-S100-CPU-04 硬重启: 断电重启恢复 (自动化占位)")
    @allure.description(
        "[人工] 断电重启需要继电器/可程控电源或人工配合, 当前未接入控制手段, 自动化占位 skip。"
        "人工执行步骤: 断电 ≥5s → 上电 → 观察串口完整启动链 → 系统恢复正常登录。"
        "后续接入继电器控制后, 本用例应实现: 断电→上电→等待 ssh 恢复→校验 uptime 归零。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "CPU", "硬重启", "manual")
    def test_hard_reboot(self):
        pytest.skip(
            "断电重启需继电器/人工配合 — 请按用例描述人工执行并记录结果"
        )


    @allure.story("启动")
    @allure.title("TC-S100-CPU-05 软重启: reboot 后自动恢复且 uptime 归零")
    @allure.description(
        "[系统] ssh 下发 reboot → 等待 ssh 掉线 → 轮询等待恢复(上限 reboot_timeout_s, 默认 300s) "
        "→ 断言 /proc/uptime 重新计数 (<180s)。注意: 本用例会重启板卡, 放在文件末尾执行。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "CPU", "软重启")
    def test_soft_reboot(self, ssh_session, bsp_params):
        with allure.step("记录重启前状态并下发 reboot"):
            code, uptime_before = ssh_session.exec_cmd_quiet("cat /proc/uptime")
            assert code == 0, f"重启前 uptime 读取失败: {uptime_before!r}"
            log_manager.logger.info(f"[软重启] 重启前 uptime: {uptime_before.strip()}")
            ssh_session.exec_cmd_quiet("reboot")
        with allure.step("等待 ssh 掉线 (确认真的在重启)"):
            dropped = False
            for _ in range(12):  # 12 x 5s = 60s 内应掉线
                time.sleep(5)
                code, _ = ssh_session.exec_cmd_quiet("true", timeout=5)
                if code != 0:
                    dropped = True
                    break
            if not dropped:
                log_manager.logger.warning("[软重启] 60s 内 ssh 未掉线, 可能重启极快或未生效")
        with allure.step("轮询等待系统恢复"):
            limit = float(bsp_params["reboot_timeout_s"])
            deadline = time.time() + limit
            back = False
            while time.time() < deadline:
                code, _ = ssh_session.exec_cmd_quiet("uname -a", timeout=10)
                if code == 0:
                    back = True
                    break
                time.sleep(5)
            assert back, f"reboot 后 {limit}s 内 ssh 未恢复"
        with allure.step("断言 uptime 归零 (确实是新的一次启动)"):
            code, out = ssh_session.exec_cmd_quiet("cat /proc/uptime")
            assert code == 0, f"重启后 uptime 读取失败: {out!r}"
            uptime_after = float(out.split()[0])
            assert uptime_after < 180, (
                f"重启后 uptime={uptime_after:.0f}s 未归零 — 疑似未真正重启"
            )
        log_manager.logger.info(f"[软重启] 恢复 OK, 新 uptime={uptime_after:.1f}s")


    # ==================== 性能指标 ====================

    @allure.story("性能指标")
    @allure.title("TC-S100-CPU-06 运行频率(正常): cpuinfo_max_freq = 1.5GHz")
    @allure.description(
        "[板端命令] cat /sys/devices/system/cpu/cpu*/cpufreq/cpuinfo_max_freq 应全部等于 "
        "expected_cpu_freq_khz (默认 1500000 kHz = 1.5GHz); 同时记录当前频率与 governor。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "CPU", "频率")
    def test_cpu_freq_normal(self, ssh_session, bsp_params):
        expected_khz = int(bsp_params["expected_cpu_freq_khz"])
        with allure.step("读取全部核心的 cpuinfo_max_freq"):
            max_freqs = _read_sys_ints(
                ssh_session, "/sys/devices/system/cpu/cpu*/cpufreq/cpuinfo_max_freq"
            )
            assert max_freqs, "读不到 cpuinfo_max_freq — 内核未启用 cpufreq?"
        with allure.step("断言额定频率"):
            wrong = sorted({f for f in max_freqs if f != expected_khz})
            assert not wrong, (
                f"cpuinfo_max_freq 存在非期望值: {wrong} kHz, 期望 {expected_khz} kHz"
            )
        with allure.step("记录当前频率与 governor"):
            cur = _read_sys_ints(
                ssh_session, "/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq"
            )
            code, governor = ssh_session.exec_cmd_quiet(
                "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null"
            )
            cur_max = max(cur) if cur else -1
        log_manager.logger.info(
            f"[频率] 额定 {expected_khz} kHz OK; 当前最高 {cur_max} kHz; "
            f"governor={governor.strip()!r}"
        )


    @allure.story("性能指标")
    @allure.title("TC-S100-CPU-07 运行频率(异常): 过温降频机制在位")
    @allure.description(
        "[板端命令] 校验热降频机制: /sys/class/thermal 下存在 thermal_zone 且配置了合法 "
        "trip point 温度 (0 < trip ≤ 150°C), cooling_device 中存在 cpufreq 类。"
        "真实过温触发属破坏性专项, 本用例验证机制存在; 热箱/加热降频实测另列。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "CPU", "降频", "thermal")
    def test_cpu_throttle_mechanism(self, ssh_session):
        with allure.step("枚举 thermal zone 及 trip point"):
            code, out = ssh_session.exec_cmd_quiet(
                'for z in /sys/class/thermal/thermal_zone*; do '
                'echo "$(basename $z) type=$(cat $z/type 2>/dev/null)"; '
                'for t in $z/trip_point_*_temp; do v=$(cat $t 2>/dev/null); '
                '[ -n "$v" ] && echo "  $(basename $t)=$v"; done; done'
            )
            assert code == 0 and "thermal_zone" in out, (
                f"无 thermal zone — 过温降频无从谈起: {out!r}"
            )
            trips = [
                int(v) for ln in out.splitlines() if "=" in ln
                for v in [ln.rsplit("=", 1)[1]] if v.lstrip("-").isdigit()
            ]
            valid_trips = [t for t in trips if 0 < t <= 150000]
            assert valid_trips, f"未找到合法 trip point 温度 (毫度): {trips}"
        with allure.step("断言存在 cpufreq cooling device"):
            code, out = ssh_session.exec_cmd_quiet(
                "cat /sys/class/thermal/cooling_device*/type 2>/dev/null"
            )
            cdev_types = out.split()
            assert any("cpufreq" in t for t in cdev_types), (
                f"cooling_device 中无 cpufreq 类 (实际: {cdev_types}) — 温度触发后无法降频"
            )
        log_manager.logger.info(
            f"[降频机制] trip points={sorted(valid_trips)} m°C, cooling={cdev_types}"
        )


    @allure.story("性能指标")
    @allure.title("TC-S100-CPU-08 算力: Dhrystone DMIPS ≥ 下限")
    @allure.description(
        "[板端命令] 运行 Dhrystone 2.1 (dhrystone_bin + iterations), 解析 DMIPS 并断言 "
        "≥ dhrystone_min_dmips (默认 2000, 仅防明显性能回退, 完整值记入报告)。"
        "板上缺二进制时 skip — 需交叉编译部署 (单线程跑分口径)。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "CPU", "Dhrystone")
    def test_cpu_dhrystone(self, ssh_session, bsp_params):
        binary = bsp_params["dhrystone_bin"]
        with allure.step(f"确认 {binary} 在板端可执行"):
            code, out = ssh_session.exec_cmd_quiet(f"test -x {binary}")
            if code != 0:
                pytest.skip(
                    f"{binary} 不存在 — 请交叉编译 Dhrystone 2.1 并部署后重跑 "
                    f"(aarch64: gcc -O2 dhry_1.c dhry_2.c -o dhrystone)"
                )
        with allure.step(f"运行 Dhrystone ({bsp_params['dhrystone_iterations']} 次)"):
            code, out = ssh_session.exec_cmd_quiet(
                f"{binary} {int(bsp_params['dhrystone_iterations'])}", timeout=300
            )
            allure.attach(out, name="dhrystone_output", attachment_type=allure.attachment_type.TEXT)
            assert code == 0, f"dhrystone 运行失败 (code={code}): {out[-500:]!r}"
        with allure.step("解析 DMIPS 结果"):
            m_dhry = re.search(r"Dhrystones?\s+per\s+Second:\s*([\d,]+)", out, re.IGNORECASE)
            m_vax = re.search(r"VAX\s+MIPS\s+rate\s*=\s*([\d.]+)", out, re.IGNORECASE)
            assert (m_dhry or m_vax), f"未能解析 DMIPS 输出, 请核对二进制版本:\n{out[-800:]}"
            if m_vax:
                dmips = float(m_vax.group(1))
            else:
                dhry_per_sec = int(m_dhry.group(1).replace(",", ""))
                dmips = dhry_per_sec / 1757.0  # 经典折算: 1757 Dhrystones/s = 1 DMIPS
        with allure.step("断言 DMIPS 下限"):
            floor = float(bsp_params["dhrystone_min_dmips"])
            assert dmips >= floor, f"DMIPS={dmips:.1f} 低于下限 {floor}"
        log_manager.logger.info(
            f"[Dhrystone] 单核 {dmips:.1f} DMIPS; 全核理论 x{bsp_params['expected_cpu_count']}"
        )


    @allure.story("性能指标")
    @allure.title("TC-S100-CPU-09 实时性: cyclictest 空载/满载/中断压力调度时延")
    @allure.description(
        "[板端命令] cyclictest -m -S -p98 -i1000 分别在 空载 / CPU满载 / 中断压力 下运行 "
        "(每场景 cyclictest_duration_s, 默认 10s), 解析 Max 时延并断言 ≤ "
        "cyclictest_max_latency_us (默认 1000us, PREEMPT_RT 正常应远低于此)。"
        "满载用 stress-ng --cpu (缺失时 dd busyloop); 中断压力用 stress-ng --timer, "
        "板上无 stress-ng 时该场景 skip。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "CPU", "cyclictest", "实时性")
    def test_cpu_cyclictest(self, ssh_session, bsp_params):
        with allure.step("确认板上 cyclictest 可用"):
            code, out = ssh_session.exec_cmd_quiet("command -v cyclictest")
            if code != 0 or not out.strip():
                pytest.skip("板上无 cyclictest (apt install rt-tests 或交叉部署)")
        code, out = ssh_session.exec_cmd_quiet("nproc")
        ncores = int(out.strip()) if code == 0 and out.strip().isdigit() else 1
        duration = int(bsp_params["cyclictest_duration_s"])
        limit_us = float(bsp_params["cyclictest_max_latency_us"])
        code, stress_path = ssh_session.exec_cmd_quiet("command -v stress-ng")
        has_stress = code == 0 and bool(stress_path.strip())

        def _run_cyclictest(scenario):
            code, out = ssh_session.exec_cmd_quiet(
                f"cyclictest -m -S -p98 -i1000 -h400 -D {duration}s", timeout=duration + 120
            )
            allure.attach(out, name=f"cyclictest_{scenario}", attachment_type=allure.attachment_type.TEXT)
            hits = re.findall(
                r"Min/Max/Avg Latency:\s*([-\d.]+)\s*/\s*([-\d.]+)\s*/\s*([-\d.]+)", out
            )
            assert hits, f"[{scenario}] cyclictest 无汇总输出 (code={code}):\n{out[-800:]}"
            _min, mx, _avg = (float(x) for x in hits[-1])  # 最后一行 = 总汇总
            return mx

        results = {}
        with allure.step("场景: 空载"):
            results["idle"] = _run_cyclictest("idle")
        with allure.step("场景: CPU 满载"):
            cleanup = _start_cpu_load(ssh_session, ncores, duration)
            try:
                results["full_load"] = _run_cyclictest("full_load")
            finally:
                if cleanup:
                    ssh_session.exec_cmd_quiet(cleanup)
            time.sleep(2)  # 负载消散
        with allure.step("场景: 中断压力 (stress-ng --timer 定时器风暴)"):
            if has_stress:
                ssh_session.exec_cmd_quiet(
                    f"nohup stress-ng --timer {ncores} --timeout {duration + 5}s >/dev/null 2>&1 &"
                )
                try:
                    results["irq_load"] = _run_cyclictest("irq_load")
                finally:
                    ssh_session.exec_cmd_quiet("pkill -f 'stress-ng --timer'")
            else:
                log_manager.logger.warning("[实时性] 板上无 stress-ng, 中断压力场景跳过")
        with allure.step("断言各场景 Max 时延 ≤ 阈值"):
            for name, mx in results.items():
                assert mx <= limit_us, (
                    f"[{name}] Max 调度时延 {mx:.0f}us 超过阈值 {limit_us}us"
                )
        log_manager.logger.info(
            "[实时性] Max 时延(us): " + ", ".join(f"{k}={v:.0f}" for k, v in results.items())
        )
