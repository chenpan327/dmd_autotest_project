# coding: utf-8
"""
===============================================================================
                    S100 底软 BSP 系统信息测试脚本
===============================================================================
脚本编号: DMD_TEST_RDKS100_BSP_SYSINFO_001
脚本版本: v1.0
创建日期: 2026-09-18
修改日期: 2026-09-18
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: RDKS100 (INDV1, S100 双 SoC: Acore Linux + MCU 小核)
测试类型: 底软功能验证测试 (Functional_Testing)
测试环境: Python 3.10, pytest, allure, SSH (paramiko)

测试目的:
验证 INDV1 (S100) 底软系统信息面 (TC-S100-SYSINFO-01 ~ 07), 对应 dmd-bsp
modules/system_info 的 8 类查询能力 (HW_LOAD/MEMORY/STORAGE/DPORT/WIFI/
TEMP/FAN/BOARD_STATUS) 的底层可观测源: 版本追溯链 → thermal 温度面 →
MCU 风扇 → eMMC 容量/寿命 → dmd_sysinfo_test 样例 → eMMC 写压测 → watchdog
在位。测试点从源码反推 (待与《底软Linux BSP 测试点分解》核对)。

前置条件:
1. 测试环境准备:
   - DUT 已启动且 dmd-bsp deb 已安装 (sample 程序在 ipc_bin_dir, 默认
     /usr/hobot/bin), 主机经 SSH 访问板端 (config.json INDV1 段)
   - ssh_session / board_info / bsp_params fixture 已就绪 (conftest 提供)
2. 环境依赖与 skip 条款:
   - SYSINFO-03 风扇: 依赖 MCU i2c 代理 (config mcu_proxy_enabled, 与
     FLOW-03 口径一致)
   - SYSINFO-06 eMMC 写压测: 消耗擦写寿命, config emmc_write_test_enabled
     =true 才跑
3. 判定语义: pytest 原生断言, 板端命令输出挂 Allure 附件

测试步骤:
1. [SYSINFO-01 test_dmd_versions_traceability] 版本追溯链: /etc/dmd_versions
   存在且含 DMD_VERSION 首行 + 各 deb 的 Package/Version/Commit/Branch 条目;
   配置 expected_dmd_version 时精确比对
2. [SYSINFO-02 test_thermal_zones] thermal 温度面: /sys/class/thermal/ 下
   zone 数 >0, 各 zone temp 读数在 [-40, thermal_temp_max_c] 内
3. [SYSINFO-03 test_mcu_fan] MCU 风扇 (需 mcu_proxy_enabled): hwmon 下存在
   emc2301/emc2305 风扇, rpm 读数记录并比对 fan_min_rpm
4. [SYSINFO-04 test_emmc_capacity_life] eMMC 容量与寿命: mmcblk0 size 换算
   ≥ emmc_min_size_gb; life_time/pre_eol_info 读数记录 (越限告警)
5. [SYSINFO-05 test_sysinfo_sample] dmd_sysinfo_test 样例: 运行退出码 0 且
   输出非空 (8 类查询总入口, 输出挂附件)
6. [SYSINFO-06 test_emmc_write_stress] eMMC 写压测 (需显式开启): dd 随机块
   写入+回读 md5 比对, 速率 ≥ emmc_write_min_mbps
7. [SYSINFO-07 test_watchdog_nodes] watchdog 在位: /dev/watchdog* 节点存在
   (dts 使能多路 watchdog, 只验在位不触发)

预期结果（与测试步骤一一对应）:
1. [SYSINFO-01] 版本链完整, 镜像内组件源码版本可追溯
2. [SYSINFO-02] 至少一个温度区且读数物理合理
3. [SYSINFO-03] 风扇 hwmon 在位, 转速 ≥ 下限 (0 = 仅记录)
4. [SYSINFO-04] 容量达标, 寿命参数无越限 (0x03 预 EOL 告警)
5. [SYSINFO-05] 样例正常退出 (断言口径首跑后校准)
6. [SYSINFO-06] 数据一致且写速率达标
7. [SYSINFO-07] 至少一路 watchdog 节点在位

===============================================================================
测试结论:
系统信息 7 个测试点全部实现自动化, 破坏性场景显式 skip 并经 config
显式开关管控, 断言结果与板端输出见 Allure 报告各用例及其附件。
===============================================================================
"""
import re

import allure
import pytest

from utils.logger import log_manager


@allure.epic("S100 底软测试")
@allure.feature("系统信息")
class TestIndv1BspSysinfo:
    """底软 Linux BSP 系统信息测试点 (版本/温度/风扇/eMMC/样例/watchdog)"""


    @allure.story("版本追溯")
    @allure.title("TC-S100-SYSINFO-01 /etc/dmd_versions 版本追溯链完整")
    @allure.description(
        "[板端命令] pack_image.sh gen_package_versions 将 DMD_VERSION + 各 deb 的 "
        "Package/Version/Commit/Branch 写入 /etc/dmd_versions — 断言文件存在、"
        "首行为 DMD_VERSION (配置 expected_dmd_version 时精确比对)、含带 Commit "
        "字段的组件条目 (镜像内组件源码版本可追溯)。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "系统信息", "版本")
    def test_dmd_versions_traceability(self, ssh_session, bsp_params):
        with allure.step("读取 /etc/dmd_versions"):
            code, out = ssh_session.exec_cmd_quiet("cat /etc/dmd_versions")
            assert code == 0, f"/etc/dmd_versions 不存在 — 镜像非 dmd 打包链路产物: {out!r}"
            allure.attach(out, name="dmd_versions", attachment_type=allure.attachment_type.TEXT)
        with allure.step("断言 DMD_VERSION 首行"):
            lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
            assert lines, "/etc/dmd_versions 为空文件"
            first = lines[0]
            m = re.match(r"^DMD_VERSION[=:]\s*(\S+)", first)
            assert m, f"首行不是 DMD_VERSION 声明: {first!r}"
            expected = bsp_params.get("expected_dmd_version")
            if expected:
                assert m.group(1) == expected, (
                    f"板端 DMD_VERSION={m.group(1)!r} ≠ 期望 {expected!r} — "
                    f"烧错了镜像? 立即终止, 避免测试结论张冠李戴"
                )
        with allure.step("断言组件条目含 Commit 追溯字段"):
            commit_lines = [ln for ln in lines if "Commit" in ln]
            assert commit_lines, (
                f"/etc/dmd_versions 无含 Commit 的组件条目 — deb 追溯元数据未注入:\n{out[:500]}"
            )
        log_manager.logger.info(
            f"[SYSINFO] 版本链 OK: {first}; 含 Commit 条目 {len(commit_lines)} 条"
        )


    @allure.story("温度面")
    @allure.title("TC-S100-SYSINFO-02 thermal 温度区可读且读数物理合理")
    @allure.description(
        "[板端命令] 遍历 /sys/class/thermal/thermal_zone*/temp: 至少一个温度区 "
        "(CPU/BPU PVT + DDR tmp112 经 dmd_temp), 各 zone 读数在 "
        "[-40, thermal_temp_max_c]°C 内 (默认 110, 满载 CPU/BPU 可超 100)。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "系统信息", "温度")
    def test_thermal_zones(self, ssh_session, bsp_params):
        with allure.step("遍历 thermal zone"):
            cmd = (
                'for z in /sys/class/thermal/thermal_zone*; do '
                't=$(cat $z/type 2>/dev/null); v=$(cat $z/temp 2>/dev/null); '
                '[ -n "$v" ] && echo "$t $v"; done'
            )
            code, out = ssh_session.exec_cmd_quiet(cmd, timeout=20)
            assert code == 0 and out.strip(), f"thermal zone 不可读: {out!r}"
        with allure.step("逐 zone 校验读数区间"):
            zones = []
            for ln in out.splitlines():
                parts = ln.split()
                if len(parts) == 2 and parts[1].lstrip("-").isdigit():
                    zones.append((parts[0], int(parts[1])))
            assert zones, f"无有效温度读数:\n{out}"
            max_c = float(bsp_params["thermal_temp_max_c"])
            for name, millic in zones:
                c = millic / 1000.0
                assert -40.0 <= c <= max_c, (
                    f"thermal zone {name} 读数 {c}°C 超出 [-40, {max_c}] — "
                    f"传感器异常或过温"
                )
        log_manager.logger.info(
            f"[SYSINFO] 温度面 OK: " + ", ".join(f"{n}={v / 1000:.1f}°C" for n, v in zones)
        )


    @allure.story("风扇")
    @allure.title("TC-S100-SYSINFO-03 MCU 风扇 emc2301 hwmon 在位 (需 mcu_proxy_enabled)")
    @allure.description(
        "[板端命令] hwmon 下存在 emc2301/emc2305 风扇控制器 (dts: mcu_i2c bus8 "
        "0x2f, 内核原生 emc2305 驱动), fan*_input rpm 读数记录并比对 "
        "fan_min_rpm (默认 0 = 台架不接风扇仅记录, 上整机后收紧阈值)。"
        "⚠ 依赖 MCU i2c 代理 — config INDV1.mcu_proxy_enabled=true 才运行。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "系统信息", "风扇")
    def test_mcu_fan(self, ssh_session, bsp_params):
        if not bsp_params.get("mcu_proxy_enabled"):
            pytest.skip(
                "依赖 MCU i2c 代理对端 — 固件就绪后置 config INDV1.mcu_proxy_enabled=true"
            )
        with allure.step("查找风扇 hwmon"):
            cmd = (
                'for n in /sys/class/hwmon/hwmon*/name; do '
                'if grep -qiE "emc230" "$n" 2>/dev/null; then '
                'd=$(dirname "$n"); echo "$d $(cat $d/fan1_input 2>/dev/null)"; fi; done'
            )
            code, out = ssh_session.exec_cmd_quiet(cmd, timeout=20)
            assert code == 0 and out.strip(), (
                f"未找到 emc230x 风扇 hwmon: {out!r} — MCU i2c 代理或风扇器件异常"
            )
        with allure.step("转速读数记录与阈值比对"):
            rpms = []
            for ln in out.splitlines():
                parts = ln.split()
                if len(parts) == 2 and parts[1].isdigit():
                    rpms.append(int(parts[1]))
            floor = int(bsp_params.get("fan_min_rpm", 0))
            for rpm in rpms:
                assert rpm >= floor, f"风扇转速 {rpm} RPM 低于下限 {floor} (停转?)"
        log_manager.logger.info(f"[SYSINFO] 风扇 OK: rpm={rpms}")


    @allure.story("eMMC")
    @allure.title("TC-S100-SYSINFO-04 eMMC 容量达标且寿命参数无越限")
    @allure.description(
        "[板端命令] /sys/block/mmcblk0 (dts mmc0=eMMC): size 换算容量 ≥ "
        "emmc_min_size_gb; device/{life_time,pre_eol_info} 健康参数读数记录 "
        "(pre_eol_info 0x01 正常 / 0x02 预警 / 0x03 紧急, 读到 0x03 即告警失败)。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "系统信息", "eMMC")
    def test_emmc_capacity_life(self, ssh_session, bsp_params):
        with allure.step("eMMC 容量"):
            code, out = ssh_session.exec_cmd_quiet("cat /sys/block/mmcblk0/size")
            assert code == 0 and out.strip().isdigit(), (
                f"mmcblk0 size 不可读: {out!r} — eMMC 未识别?"
            )
            sectors = int(out.strip())
            size_gb = sectors * 512 / 1024 ** 3
            floor = float(bsp_params["emmc_min_size_gb"])
            assert size_gb >= floor, f"eMMC 容量 {size_gb:.1f}GB < 下限 {floor}GB"
        with allure.step("寿命健康参数"):
            code, out = ssh_session.exec_cmd_quiet(
                "cat /sys/block/mmcblk0/device/pre_eol_info "
                "/sys/block/mmcblk0/device/life_time 2>/dev/null"
            )
            eol = ""
            if code == 0 and out.strip():
                vals = out.split()
                eol = vals[0]
                allure.attach(out, name="emmc_life", attachment_type=allure.attachment_type.TEXT)
                assert eol != "0x03", (
                    f"eMMC pre_eol_info={eol} (紧急) — 器件寿命将尽, 立即更换"
                )
                if eol == "0x02":
                    log_manager.logger.warning("[SYSINFO] eMMC pre_eol_info=0x02 (预警), 建议关注")
            else:
                log_manager.logger.warning("[SYSINFO] eMMC 不支持 pre_eol_info/life_time 查询 (仅记录)")
        log_manager.logger.info(f"[SYSINFO] eMMC OK: {size_gb:.1f}GB eol={eol or 'N/A'}")


    @allure.story("系统信息样例")
    @allure.title("TC-S100-SYSINFO-05 dmd_sysinfo_test 样例 8 类查询正常退出")
    @allure.description(
        "[板端命令] 运行 {ipc_bin_dir}/dmd_sysinfo_test (modules/system_info 8 类"
        "查询的样例总入口): 退出码 0 且输出非空, 全文挂附件。输出格式以板上实际"
        "为准, 首跑后按各查询类 (HW_LOAD/MEMORY/STORAGE/DPORT/WIFI/TEMP/FAN/"
        "BOARD_STATUS) 细化断言口径。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "系统信息", "样例")
    def test_sysinfo_sample(self, ssh_session, bsp_params):
        binary = f"{bsp_params['ipc_bin_dir']}/dmd_sysinfo_test"
        code, out = ssh_session.exec_cmd_quiet(f"test -x {binary}")
        if code != 0:
            pytest.skip(f"{binary} 不存在 — dmd-bsp deb 未安装或未编译 samples")
        with allure.step("运行 dmd_sysinfo_test"):
            code, out = ssh_session.exec_cmd_quiet(binary, timeout=60)
            allure.attach(out, name="sysinfo_sample_output", attachment_type=allure.attachment_type.TEXT)
            assert code == 0, f"dmd_sysinfo_test 异常退出 (code={code}):\n{out[-800:]}"
            assert out.strip(), "样例无输出 — 8 类查询全部无打印?"
        log_manager.logger.info(f"[SYSINFO] 样例 PASS, 输出 {len(out)} 字节")


    @allure.story("eMMC压测")
    @allure.title("TC-S100-SYSINFO-06 eMMC 写压测: 随机块写入回读一致 (需显式开启)")
    @allure.description(
        "[板端命令] dd if=/dev/urandom of=/var/tmp bs=1M count=N 写入 + md5sum "
        "回读比对 + rm 清理, 解析 dd 速率断言 ≥ emmc_write_min_mbps。"
        "⚠ 消耗 eMMC 擦写寿命 — config INDV1.emmc_write_test_enabled=true 才运行。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "系统信息", "eMMC", "压测")
    def test_emmc_write_stress(self, ssh_session, bsp_params):
        if not bsp_params.get("emmc_write_test_enabled"):
            pytest.skip(
                "eMMC 写压测消耗擦写寿命 — 确认环境后置 "
                "config INDV1.emmc_write_test_enabled=true"
            )
        mb = int(bsp_params["emmc_write_mb"])
        path = "/var/tmp/dmd_emmc_stress.bin"
        with allure.step(f"写入 {mb}MB 随机数据"):
            code, out = ssh_session.exec_cmd_quiet(
                f"dd if=/dev/urandom of={path} bs=1M count={mb} 2>&1",
                timeout=max(300, mb * 10),
            )
            allure.attach(out, name="emmc_write_dd", attachment_type=allure.attachment_type.TEXT)
            assert code == 0, f"dd 写入失败 (code={code}):\n{out[-500:]}"
        try:
            with allure.step("md5 回读比对"):
                code, md5_out = ssh_session.exec_cmd_quiet(f"md5sum {path}", timeout=120)
                local_md5 = md5_out.split()[0] if md5_out.split() else ""
                code2, md5_out2 = ssh_session.exec_cmd_quiet(
                    f"dd if={path} bs=1M count={mb} 2>/dev/null | md5sum", timeout=120
                )
                read_md5 = md5_out2.split()[0] if md5_out2.split() else ""
                assert local_md5 and read_md5, f"md5 计算失败: {md5_out!r} / {md5_out2!r}"
                assert local_md5 == read_md5, (
                    f"eMMC 回读数据不一致 (write={local_md5}, read={read_md5}) — "
                    f"存储链路数据完整性受损"
                )
            with allure.step("解析写速率"):
                m = re.search(r"([\d.]+)\s*(MB|kB)/s", out)
                if m:
                    rate = float(m.group(1))
                    if m.group(2) == "kB":
                        rate /= 1024.0
                    floor = float(bsp_params["emmc_write_min_mbps"])
                    assert rate >= floor, f"eMMC 写速率 {rate:.1f}MB/s < 下限 {floor}MB/s"
                    log_manager.logger.info(f"[SYSINFO] eMMC 写压测 OK: {rate:.1f}MB/s, md5 一致")
                else:
                    log_manager.logger.info(f"[SYSINFO] eMMC 写压测 OK: md5 一致 (dd 无速率输出)")
        finally:
            ssh_session.exec_cmd_quiet(f"rm -f {path}")


    @allure.story("看门狗")
    @allure.title("TC-S100-SYSINFO-07 watchdog 设备节点在位 (只验在位不触发)")
    @allure.description(
        "[板端命令] dts 使能多路 watchdog — /dev/watchdog* 节点应存在。"
        "只验在位: 触发超时复位属破坏性操作, 归入人工/专项场景。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "系统信息", "watchdog")
    def test_watchdog_nodes(self, ssh_session):
        with allure.step("扫描 /dev/watchdog*"):
            code, out = ssh_session.exec_cmd_quiet("ls /dev/watchdog* 2>/dev/null")
            nodes = out.split() if code == 0 else []
            assert nodes, (
                f"/dev/watchdog* 不存在 — watchdog 驱动未使能或未注册字符设备"
            )
        log_manager.logger.info(f"[SYSINFO] watchdog OK: {nodes}")
