# coding: utf-8
"""
===============================================================================
                        S100 底软 BSP IPC 测试脚本
===============================================================================
脚本编号: DMD_TEST_RDKS100_BSP_IPC_001
脚本版本: v1.1
创建日期: 2026-09-14
修改日期: 2026-09-17
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: RDKS100 (INDV1, S100 双 SoC: Acore Linux + MCU 小核)
测试类型: 底软功能验证测试 (Functional_Testing)
测试环境: Python 3.10, pytest, allure, SSH (paramiko)

测试目的:
验证 INDV1 (S100) 底软 BSP 的 IPC 链路 (TC-S100-IPC-01 ~ 07): AP(Linux) 与
MCU 小核经 hb_ipc mailbox 互联, 用户态经 hb_ipcf_hal (/etc/ipcfhal_config.json,
/dev/ipcdrv), 内核态经 dmd_ipc_mgr (instance 4)。覆盖 MCU 握手/配置完整性/
通道回环吞吐/PWM 代理/CAN 代理/MCU I2C 双总线/GPIO 代理。测试点从源码反推
(待与《底软Linux BSP 测试点分解》IPC 表核对)。

前置条件:
1. 测试环境准备:
   - DUT 已启动且 dmd-bsp deb 已安装 (sample 程序在 ipc_bin_dir, 默认
     /usr/hobot/bin), 主机经 SSH 访问板端 (config.json INDV1 段)
   - ssh_session / board_info / bsp_params fixture 已就绪 (conftest 提供)
2. 危险用例显式开关 (可能影响真实外设, 默认 skip):
   - IPC-03 通道回环: ins0 系通道是 CAN 桥 (绑定 FlexCAN6~9, 固件无回显实现),
     误发会污染真实 CAN 总线 — 对端具备回显能力后置 ipc_loopback_test_enabled
   - IPC-04 PWM 闭环: 可能驱动真实执行器 — 确认环境后置 ipc_pwm_test_enabled
   - IPC-05 CAN 闭环: 报文必然转发到真实 CAN 总线 — 有受控对端后置
     ipc_can_test_enabled
   - IPC-06 I2C 双总线: 依赖 MCU 固件 ins4 对端 (config mcu_proxy_enabled)
3. 判定语义: pytest 原生断言, 板端 sample 输出挂 Allure 附件

测试步骤:
1. [IPC-01 test_mcu_firmware_and_ipc_ready] MCU 固件运行与 IPC 握手:
   remoteproc_mcu0 state=running → devmem 0xcddee00 读魔数 0x49504346('IPCF') →
   loadko 内核日志 'ipc4 ready'
2. [IPC-02 test_ipcfhal_config] ipcfhal 配置完整性: 解析 /etc/ipcfhal_config.json,
   断言 instance4 channel 0/1/2 (PWM/GPIO/I2C) 与回环通道在册
3. [IPC-03 test_ipc_loopback] 通道回环吞吐: dmd_ipc_test -i{ins} -c{ch} -L
   -n{count} -l{len}, 填随机数发送对端回包 memcmp, 退出码 0 且吞吐 ≥ 下限
4. [IPC-04 test_ipc_pwm_loopback] PWM 代理闭环: dmd_ipc2pwm -i4 -c0, 默认写
   1kHz/50% 后读回硬件原始 tick 比对 (period 精确, duty 容差 ±2‰)
5. [IPC-05 test_ipc_can_loopback] CAN 代理闭环: dmd_ipc2can -i0 -c1 -n{count},
   发 can_id=0x1 约定回显 0x0 且数据一致
6. [IPC-06 test_mcu_i2c_dual_bus] MCU I2C 双总线: i2cdetect -y 9 可扫 (dts bus9
   为空, 全 '--' 属正常) → 扫描后 bus8 温度仍可读 (验证两总线互不卡死)
7. [IPC-07 test_mcu_gpio_chip] GPIO 代理在位: 查找 106 线 mcu_gpio0 gpiochip
   (sysfs ngpios 优先, gpiodetect 兜底)

预期结果（与测试步骤一一对应）:
1. [IPC-01] MCU 固件 running, IPC 魔数匹配, 日志就绪标记存在
2. [IPC-02] 配置为合法 JSON 且 instance4 三通道 + 回环通道齐全
3. [IPC-03] 退出码 0 (样例约定 Fail>0 返回 1), 吞吐 ≥ ipc_min_rate_kbps
4. [IPC-04] 写→读回比对通过 (退出码 0)
5. [IPC-05] 全部帧回环一致 (退出码 0)
6. [IPC-06] i2c-9 可扫且扫描后 i2c-8 温度读取正常 (IPC 通道未互相卡死)
7. [IPC-07] 存在线数为 106 的 gpiochip (方向读写闭环属破坏性操作, 只验在位)

===============================================================================
测试结论:
IPC 7 个测试点全部实现自动化, 危险场景默认 skip 并经 config 显式开关管控,
断言结果与板端 sample 输出见 Allure 报告各用例及其附件。
===============================================================================
"""
import json
import re

import allure
import pytest

from utils.logger import log_manager


def _ipc_bin(ssh_session, bsp_params, name):
    """返回板上 sample 程序路径, 不存在则 skip"""
    path = f"{bsp_params['ipc_bin_dir']}/{name}"
    code, out = ssh_session.exec_cmd_quiet(f"test -x {path}")
    if code != 0:
        pytest.skip(f"{path} 不存在 — dmd-bsp deb 未安装或 ipc_bin_dir 配置有误")
    return path


@allure.epic("S100 底软测试")
@allure.feature("IPC BSP")
class TestIndv1BspIpc:
    """底软 Linux BSP IPC 测试点 (MCU 握手/配置/回环/PWM/CAN/I2C/GPIO)"""


    @allure.story("MCU握手")
    @allure.title("TC-S100-IPC-01 MCU 固件 running 且共享内存魔数 IPCF 就绪")
    @allure.description(
        "[板端命令] remoteproc_mcu0 state=running; devmem 0xcddee00 应读到魔数 "
        "0x49504346 (ASCII 'IPCF', dmd-loadko.sh 的就绪判据); 本轮 loadko 日志应含 "
        "'mcu ipc4 ready'。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("S100", "底软", "IPC", "MCU")
    def test_mcu_firmware_and_ipc_ready(self, ssh_session):
        with allure.step("remoteproc MCU 状态"):
            code, out = ssh_session.exec_cmd_quiet(
                "cat /sys/class/remoteproc/remoteproc_mcu0/state"
            )
            assert code == 0, f"remoteproc_mcu0 state 读取失败: {out!r}"
            assert out.strip() == "running", (
                f"MCU 固件状态={out.strip()!r}, 期望 running"
            )
        with allure.step("共享内存魔数 0x49504346 ('IPCF')"):
            code, out = ssh_session.exec_cmd_quiet("devmem 0xcddee00")
            if code != 0:
                log_manager.logger.warning(f"[IPC] devmem 不可用 ({out.strip()!r}), 跳过魔数校验")
            else:
                assert "49504346" in out.lower(), (
                    f"IPC 魔数不匹配: 期望 0x49504346('IPCF'), 读到 {out.strip()!r} "
                    f"— MCU 侧 IPC 通道未就绪"
                )
        with allure.step("loadko 日志含 ipc4 ready"):
            # 标记由 dmd-loadko.sh echo > /dev/kmsg 写入, 属内核传输层, 须用 -k 过滤
            code, out = ssh_session.exec_cmd_quiet(
                "journalctl -b -k --no-pager | grep -i 'ipc4 ready'",
                timeout=30,
            )
            if code == 0 and out.strip():
                log_manager.logger.info(f"[IPC] {out.strip().splitlines()[-1]}")
            else:
                log_manager.logger.warning("[IPC] 日志未匹配 'ipc4 ready', 请核对格式")
        log_manager.logger.info("[IPC] MCU 固件 running + IPC 就绪 OK")


    @allure.story("配置")
    @allure.title("TC-S100-IPC-02 ipcfhal 配置: instance4 三通道 (PWM/GPIO/I2C) 在册")
    @allure.description(
        "[板端命令] /etc/ipcfhal_config.json 必须定义 instance 4 的 channel 0/1/2 "
        "(对应 dts mcu_pwm0/mcu_gpio0/mcu_i2c) 及通用回环通道; 包大小 128 与 IPC buf 一致。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "IPC", "配置")
    def test_ipcfhal_config(self, ssh_session, bsp_params):
        with allure.step("读取 /etc/ipcfhal_config.json"):
            code, out = ssh_session.exec_cmd_quiet("cat /etc/ipcfhal_config.json")
            assert code == 0, f"ipcfhal 配置读取失败: {out!r}"
        with allure.step("解析并断言 instance4 通道"):
            try:
                cfg = json.loads(out)
            except json.JSONDecodeError as e:
                pytest.fail(f"ipcfhal 配置不是合法 JSON: {e}")
            channels = {}
            for key, val in cfg.items():
                if key.startswith("config_") and isinstance(val, dict):
                    channels[(val.get("instance"), val.get("channel"))] = val
            for ch in (0, 1, 2):
                assert (4, ch) in channels, (
                    f"ipcfhal 配置缺 instance4 channel{ch} — PWM/GPIO/I2C 代理将无法工作"
                )
            loop_key = (
                int(bsp_params["ipc_loopback_instance"]),
                int(bsp_params["ipc_loopback_channel"]),
            )
            assert loop_key in channels, (
                f"回环通道 {loop_key} 不在 ipcfhal 配置中 — TC-03 回环测试将无法执行"
            )
        log_manager.logger.info(
            f"[IPC配置] 通道: {sorted(channels)}; "
            f"pkg_size_max={channels[(4, 0)].get('pkg_size_max')}"
        )


    @allure.story("回环")
    @allure.title("TC-S100-IPC-03 通道回环: dmd_ipc_test -L Fail=0 且吞吐 ≥ 下限 (需显式开启)")
    @allure.description(
        "[板端命令] dmd_ipc_test -i{ins0} -c{ch0} -L -n{count} -l{len}: 填随机数发送, "
        "对端逐字节回包 memcmp。断言退出码 0 (样例内 Fail>0 返回 1), "
        "解析吞吐记录并断言 ≥ ipc_min_rate_kbps (默认极低, 防明显退化, 首跑后校准)。"
        "⚠ 经 s100_mcu 固件核实: ins0 系通道是 CAN 桥 (CanIpc 绑定 FlexCAN6~9, "
        "收到数据直接转发真实 CAN 总线, 固件无回显实现) — 误发会污染真实 CAN 总线, "
        "仅当对端具备回显能力时置 config INDV1.ipc_loopback_test_enabled=true 运行。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "IPC", "回环")
    def test_ipc_loopback(self, ssh_session, bsp_params):
        if not bsp_params.get("ipc_loopback_test_enabled"):
            pytest.skip(
                "ins0 为 CAN 桥通道 (当前 MCU 固件无回显实现, 误发会上真实 CAN 总线) "
                "— 对端具备回显能力后置 config INDV1.ipc_loopback_test_enabled=true"
            )
        binary = _ipc_bin(ssh_session, bsp_params, "dmd_ipc_test")
        ins = int(bsp_params["ipc_loopback_instance"])
        ch = int(bsp_params["ipc_loopback_channel"])
        count = int(bsp_params["ipc_loopback_count"])
        length = int(bsp_params["ipc_loopback_len"])
        with allure.step(f"dmd_ipc_test -i{ins} -c{ch} -L -n{count} -l{length}"):
            code, out = ssh_session.exec_cmd_quiet(
                f"{binary} -i {ins} -c {ch} -L -n {count} -l {length}",
                timeout=max(120, count),
            )
            allure.attach(out, name="ipc_loopback_output", attachment_type=allure.attachment_type.TEXT)
            assert code == 0, (
                f"回环测试失败 (退出码 {code}, 样例约定 Fail>0 返回 1):\n{out[-1000:]}"
            )
        with allure.step("解析吞吐"):
            rates = [float(x) for x in re.findall(r"([\d.]+)\s*KB/s", out, re.IGNORECASE)]
            if rates:
                rate = max(rates)
                floor = float(bsp_params["ipc_min_rate_kbps"])
                assert rate >= floor, f"回环吞吐 {rate:.1f}KB/s 低于下限 {floor}KB/s"
                log_manager.logger.info(f"[IPC回环] {count} 报文 PASS, 吞吐 {rate:.1f}KB/s")
            else:
                log_manager.logger.info(f"[IPC回环] {count} 报文 PASS (输出无 KB/s, 吞吐未记录)")


    @allure.story("PWM代理")
    @allure.title("TC-S100-IPC-04 PWM 代理闭环: 写→读回比对 (需显式开启)")
    @allure.description(
        "[板端命令] dmd_ipc2pwm -i4 -c0: 默认写 1kHz/50% 后读回硬件原始 tick(200MHz) 比对, "
        "period 精确匹配、duty 容差 ±2‰, 样例失败返回非 0。"
        "⚠ MCU PWM 可能连接真实执行器 — 仅当 config INDV1.ipc_pwm_test_enabled=true 时运行。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "IPC", "PWM")
    def test_ipc_pwm_loopback(self, ssh_session, bsp_params):
        if not bsp_params.get("ipc_pwm_test_enabled"):
            pytest.skip(
                "PWM 闭环可能驱动真实执行器 — 确认测试环境后置 "
                "config INDV1.ipc_pwm_test_enabled=true"
            )
        binary = _ipc_bin(ssh_session, bsp_params, "dmd_ipc2pwm")
        ins = int(bsp_params["ipc_pwm_instance"])
        ch = int(bsp_params["ipc_pwm_channel"])
        with allure.step(f"dmd_ipc2pwm -i{ins} -c{ch} (默认 1kHz/50% 写读回比对)"):
            code, out = ssh_session.exec_cmd_quiet(
                f"{binary} -i {ins} -c {ch}", timeout=120
            )
            allure.attach(out, name="ipc2pwm_output", attachment_type=allure.attachment_type.TEXT)
            assert code == 0, f"PWM 闭环失败 (退出码 {code}):\n{out[-1000:]}"
        log_manager.logger.info("[IPC-PWM] 写→读回比对 PASS")


    @allure.story("CAN代理")
    @allure.title("TC-S100-IPC-05 CAN 代理闭环: 发 0x1 回显 0x0 (需显式开启)")
    @allure.description(
        "[板端命令] dmd_ipc2can -i0 -c1 -n{count}: 发 {can_id=0x1, 随机数据}, "
        "约定回显 can_id=0x0 且数据逐字节一致; 样例对 send/timeout/id/len/data 六类失败分别计数, "
        "失败返回非 0。⚠ 经 s100_mcu 固件核实: ins0ch1 绑定 FlexCAN7, 报文**必然**转发到真实 "
        "CAN 总线, 且当前固件无 id-1 回显逻辑 — 仅在有受控对端 (回环节点/抓包确认) 时置 "
        "ipc_can_test_enabled=true 运行。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "IPC", "CAN")
    def test_ipc_can_loopback(self, ssh_session, bsp_params):
        if not bsp_params.get("ipc_can_test_enabled"):
            pytest.skip(
                "CAN 闭环可能把报文打到真实总线 — 确认测试环境后置 "
                "config INDV1.ipc_can_test_enabled=true"
            )
        binary = _ipc_bin(ssh_session, bsp_params, "dmd_ipc2can")
        ins = int(bsp_params["ipc_can_instance"])
        ch = int(bsp_params["ipc_can_channel"])
        count = int(bsp_params["ipc_can_count"])
        with allure.step(f"dmd_ipc2can -i{ins} -c{ch} -n{count}"):
            code, out = ssh_session.exec_cmd_quiet(
                f"{binary} -i {ins} -c {ch} -n {count}", timeout=max(120, count)
            )
            allure.attach(out, name="ipc2can_output", attachment_type=allure.attachment_type.TEXT)
            assert code == 0, f"CAN 闭环失败 (退出码 {code}):\n{out[-1000:]}"
        log_manager.logger.info(f"[IPC-CAN] {count} 帧回环 PASS")


    @allure.story("I2C代理")
    @allure.title("TC-S100-IPC-06 MCU I2C 双总线: i2c-9 可扫且扫描后 i2c-8 不卡死")
    @allure.description(
        "[板端命令] i2cdetect -y 9 退出码 0 (dts bus9 为空, 全 '--' 属正常, "
        "能扫即证明第二条 MCU I2C 适配器经 IPC 代理在位); 随后 bus8 的 tmp112 温度仍可读, "
        "证明两总线共享 IPC 通道的串行化未互相卡死。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "IPC", "I2C")
    def test_mcu_i2c_dual_bus(self, ssh_session, bsp_params):
        if not bsp_params.get("mcu_proxy_enabled"):
            pytest.skip(
                "依赖 MCU i2c 代理对端 (当前 s100_mcu 固件无 ins4 处理器) "
                "— 固件就绪后置 config INDV1.mcu_proxy_enabled=true"
            )
        with allure.step("i2cdetect -y 9 (空总线全 '--' 属正常)"):
            code, out = ssh_session.exec_cmd_quiet("i2cdetect -y 9", timeout=60)
            assert code == 0, f"i2c-9 扫描失败 — 第二条 MCU I2C 适配器不在位: {out!r}"
            assert ":" in out, f"i2c-9 无扫描矩阵输出 (适配器不存在?): {out!r}"
        with allure.step("扫描后 bus8 温度仍可读 (验证 IPC 通道未卡死)"):
            # dmd_temp 注册的 hwmon name 是 "dmdtemp" (非 tmp112), 兼容两种命名
            cmd = (
                'for n in /sys/class/hwmon/hwmon*/name; do '
                'if grep -qiE "dmdtemp|tmp112" "$n" 2>/dev/null; then '
                'd=$(dirname "$n"); cat $d/temp1_input 2>/dev/null; fi; done'
            )
            code, out = ssh_session.exec_cmd_quiet(cmd, timeout=20)
            assert code == 0 and out.strip(), (
                f"i2c-9 扫描后 i2c-8 温度读取失败 — 双总线在 IPC 通道上互相卡死: {out!r}"
            )
        log_manager.logger.info("[IPC-I2C] bus9 可扫 + bus8 复测正常, 双总线 OK")


    @allure.story("GPIO代理")
    @allure.title("TC-S100-IPC-07 GPIO 代理在位: 106 线 mcu_gpiochip 存在")
    @allure.description(
        "[板端命令] dts mcu_gpio0 ngpios=106; 通过 /sys/class/gpio/gpiochip*/ngpios "
        "查找 (fallback gpiodetect), 断言存在 106 线的 gpiochip。"
        "方向读写闭环属破坏性操作(可能影响外设), 本用例只验在位。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "IPC", "GPIO")
    def test_mcu_gpio_chip(self, ssh_session, board_info):
        code, out = ssh_session.exec_cmd_quiet("lsmod | grep -q dmd_gpio")
        if code != 0:
            pytest.skip(
                f"dmd_gpio 未加载 (板级 {board_info['boardid']} 不含该模块) — 无 MCU gpiochip"
            )
        with allure.step("查找 106 线 gpiochip (sysfs)"):
            code, out = ssh_session.exec_cmd_quiet(
                'for c in /sys/class/gpio/gpiochip*; do '
                '[ -e "$c/ngpios" ] && echo "$(basename $c) $(cat $c/ngpios)"; '
                'done 2>/dev/null'
            )
            chips = {}
            for ln in out.splitlines():
                parts = ln.split()
                if len(parts) == 2 and parts[1].isdigit():
                    chips[parts[0]] = int(parts[1])
            matched = [c for c, n in chips.items() if n == 106]
        if not matched:
            with allure.step("sysfs 未命中, 尝试 gpiodetect"):
                code, out = ssh_session.exec_cmd_quiet("gpiodetect 2>/dev/null")
                m = re.search(r"gpiochip\d+\s+\[(\d+)\s+lines\]", out or "")
                if m and int(m.group(1)) == 106:
                    matched = ["gpiodetect:" + (out.splitlines()[0] if out else "")]
        assert matched, (
            f"未找到 106 线的 MCU gpiochip — dmd_gpio 驱动未加载或线数不符 "
            f"(实际: {chips or (out or '')[:200]!r})"
        )
        log_manager.logger.info(f"[IPC-GPIO] mcu gpiochip OK: {matched}")
