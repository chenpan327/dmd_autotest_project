# coding: utf-8
"""
===============================================================================
                    S100 底软 BSP 业务主流程测试脚本
===============================================================================
脚本编号: DMD_TEST_RDKS100_BSP_FLOW_001
脚本版本: v1.1
创建日期: 2026-09-14
修改日期: 2026-09-17
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: RDKS100 (INDV1, S100 双 SoC: Acore Linux + MCU 小核)
测试类型: 底软功能验证测试 (Functional_Testing)
测试环境: Python 3.10, pytest, allure, SSH (paramiko)

测试目的:
按业务主流程端到端冒烟 (自举 → 飞控链路 → MCU 外设代理 → 视频业务 →
TOF 业务 → 空域感知, TC-S100-FLOW-01 ~ 06), 验证"整机能跑业务"。
业务流程依据 dmd-bsp 源码的真实启动与运行顺序编排; CPU / DDR / IPC 等
测试点类验证见同目录 test_indv1_linux_bsp_s100_*.py。

前置条件:
1. 测试环境准备:
   - DUT 已启动且 dmd-bsp deb 已安装 (sample 程序在 ipc_bin_dir, 默认
     /usr/hobot/bin), 主机经 SSH 访问板端 (config.json INDV1 段)
   - ssh_session / board_info / bsp_params fixture 已就绪 (conftest 提供)
2. 阶段依赖与 skip 条款:
   - 用例按定义顺序执行, 前序阶段失败会让后续阶段大概率失败 (业务流串行依赖)
   - FLOW-02 仅 v2p0 (boardid 0x8) 具备 ch943x/fc-uart 链路, 其余板级 skip
   - FLOW-03 依赖 MCU 固件 ins4 pwm/gpio/i2c 对端 (config mcu_proxy_enabled)
   - FLOW-04 会独占 camera/FPGA, 须在无产品业务进程的干净环境执行;
     摄像头不在位时 skip
   - FLOW-05 需 TOF sensor 在位, 全部初始化失败时 skip
   - FLOW-06 需真实 ADS-B 接收机 (config adsb_enabled=true), 默认仅验设备在位
3. 判定语义: pytest 原生断言, 板端命令输出挂 Allure 附件 (rtsp/tof/adsb)

测试步骤:
1. [FLOW-01 test_01_boot_and_bsp_ready] 上电自举全链:
   remoteproc_mcu0 state=running → devmem 0xcddee00 读 IPC 魔数 'IPCF' →
   dmd-loadko.service 成功且内核日志含 dmd_load_ko_begin/end 无 check timeout →
   lsmod 与 boardid (0x0/0x1/0x8) 期望模块集比对 → dmd_board_test 自检全 PASS
2. [FLOW-02 test_02_fc_uart_link] 飞控链路业务: /dev/fc-uart (udev→ttyCH943X1)
   在位 → fc-logger.service active → /log/fc 下存在非空文件 (2Mbaud 透传落盘)
3. [FLOW-03 test_03_mcu_peripheral_proxy] MCU 域外设代理业务: i2c-8 扫描确认
   tmp112(0x48/0x49) 被驱动占用(UU) + 风扇 emc2301(0x2f) 在位 → hwmon 温度读数
   在 [-40,125]°C → 存在 106 线 MCU gpiochip
4. [FLOW-04 test_04_video_business_e2e] 视频业务端到端 (核心): dmd_rtsp_test
   -n 150 定帧运行 → 断言 cam0 up / RTSP up / encoder up 三阶段标记 →
   解析 [stats]: sent≥100 且编码失败帧≤3 且 rtsp feeds>0
5. [FLOW-05 test_05_tof_business] TOF 深度业务: timeout -s INT 优雅终止
   dmd_tof_manual_test → 无 dmd_bspinit failed → 至少一路 get_frame success
   且失败帧数不过多
6. [FLOW-06 test_06_adsb_business] 空域感知业务: /dev/ttyS1 在位 → (config
   开启时) 运行 dmd_adsb_manual_test 15s → 断言无 FAIL: dmd_adsb_init/start/
   get_version

预期结果（与测试步骤一一对应）:
1. [FLOW-01] 自举五步全部通过, 产出 boardid 供后续阶段判断板级能力
2. [FLOW-02] fc-uart 在位、服务 active、落盘文件非空 (透传业务真实在跑)
3. [FLOW-03] 温度/风扇器件在位且温度物理合理, 106 线 gpiochip 存在
   (代理业务在服务)
4. [FLOW-04] camera/RTSP/编码器三阶段启动, 出帧≥期望 2/3、失败≤3 帧、
   码流确实推入 FIFO
5. [FLOW-05] TOF 管线初始化成功且至少一路持续产出深度帧
6. [FLOW-06] ADS-B 业务初始化成功 (未接接收机时仅验串口在位后 skip)

===============================================================================
测试结论:
业务主流程 6 个阶段全部实现自动化, 环境外设不在位场景显式 skip 并注明原因,
断言结果与板端输出见 Allure 报告各用例及其附件。
===============================================================================
"""
import re

import allure
import pytest

from utils.logger import log_manager


# dmd-loadko.sh 按 boardid (16 进制) 加载的内核模块集合 (lsmod 中的模块名)
# 注意: load_modules_mcu1() 在 v1p1/v2p0 都会加载 ads6401_aux (modprobe.d 的
# blacklist 只禁自动加载, 脚本里的显式 modprobe 仍然生效)
BOARDID_TO_MODULES = {
    "0x0": {"ads6401_aux"},  # v1p0: 仅 TOF sensor 驱动
    "0x1": {  # v1p1: MCU 域外设代理 + TOF 驱动
        "dmd_ipc_mgr", "dmd_pwm", "dmd_gpio", "dmd_mcu_i2c", "dmd_temp", "ads6401_aux",
    },
    "0x8": {  # v2p0: 上者 + CH9434D UART 扩展
        "dmd_ipc_mgr", "dmd_pwm", "dmd_gpio", "dmd_mcu_i2c", "dmd_temp",
        "ads6401_aux", "ch943x",
    },
}

_MCU_BOARDIDS = ("0x1", "0x8")  # 有 MCU 域外设代理业务的板级


@allure.epic("S100 底软测试")
@allure.feature("业务主流程")
class TestIndv1BspFlow:
    """S100 业务主流程端到端冒烟 — 按真实业务启动顺序逐阶段验证"""

    # 类级共享状态: 前序阶段产出 (boardid 等) 供后续阶段判断板级能力
    STATE = {}


    @allure.story("01 上电自举")
    @allure.title("TC-S100-FLOW-01 自举: MCU握手→按板级加载模块→底软自检PASS")
    @allure.description(
        "[业务阶段1] 上电自举全链: remoteproc_mcu0 running → devmem 0xcddee00 魔数 "
        "'IPCF' → dmd-loadko.service 成功退出 → journal 含 dmd_load_ko_begin/end "
        "且无 check timeout → lsmod 与板级 (boardid) 期望模块集一致 → "
        "dmd_board_test 自检全 PASS。产出 boardid 供后续阶段判断板级能力。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("S100", "业务流程", "自举")
    def test_01_boot_and_bsp_ready(self, ssh_session, board_info, test_params):
        with allure.step("MCU 固件 running + IPC 魔数"):
            code, out = ssh_session.exec_cmd_quiet(
                "cat /sys/class/remoteproc/remoteproc_mcu0/state"
            )
            assert code == 0 and out.strip() == "running", (
                f"MCU 固件未运行: state={out.strip()!r} — 自举第一步失败"
            )
            code, out = ssh_session.exec_cmd_quiet("devmem 0xcddee00")
            if code == 0:
                assert "49504346" in out.lower(), (
                    f"IPC 魔数异常: {out.strip()!r} (期望 0x49504346 'IPCF')"
                )
        with allure.step("dmd-loadko 成功 + 加载日志完整"):
            code, out = ssh_session.exec_cmd_quiet(
                "systemctl show dmd-loadko.service -p ExecMainStatus --value"
            )
            assert code == 0 and out.strip() == "0", (
                f"dmd-loadko.service 上次执行失败: ExecMainStatus={out!r}"
            )
            code, out = ssh_session.exec_cmd_quiet(
                # 标记由脚本 echo > /dev/kmsg 写入, 属内核传输层 — 不能用 -u 过滤
                # (kmsg 消息无 _SYSTEMD_UNIT 属性, -u 会过滤成空)。
                # journald 不可用/未持久化时回退 dmesg (运行过久环形缓冲可能滚动)
                "{ journalctl -b -k --no-pager 2>/dev/null || true; dmesg; }",
                timeout=30,
            )
            assert "dmd_load_ko_begin" in out and "dmd_load_ko_end" in out, (
                "内核日志缺 dmd_load_ko_begin/end 标记 — 加载流程未正常走完"
            )
            assert "check timeout" not in out, "MCU IPC 就绪轮询超时 (ipc4 check timeout)"
        with allure.step(f"内核模块与板级 {board_info['boardid']} 匹配"):
            expected = BOARDID_TO_MODULES.get(board_info["boardid"])
            assert expected is not None, (
                f"未知 boardid={board_info['boardid']!r} — loadko 不会加载任何模块, "
                f"整机的底软业务无从谈起"
            )
            code, out = ssh_session.exec_cmd_quiet("lsmod")
            loaded = {ln.split()[0] for ln in out.splitlines() if ln.strip()}
            missing = expected - loaded
            assert not missing, f"板级 {board_info['boardid']} 缺模块: {sorted(missing)}"
        with allure.step("底软自检程序全 PASS"):
            binary = test_params["board_test_bin"]
            code, out = ssh_session.exec_cmd_quiet(f"test -x {binary}")
            if code != 0:
                pytest.fail(f"{binary} 不存在 — dmd-bsp deb 未安装")
            code, out = ssh_session.exec_cmd_quiet(binary, timeout=60)
            assert "FAIL:" not in out, f"自检存在 FAIL 项:\n{out}"
            assert "PASS:" in out, f"自检输出无 PASS: 行:\n{out}"
        self.__class__.STATE["boardid"] = board_info["boardid"]
        log_manager.logger.info(
            f"[FLOW-01] 自举 OK: boardid={board_info['boardid']}, 模块 {sorted(expected)}, "
            f"自检 {out.count('PASS:')} 项 PASS"
        )


    @allure.story("02 飞控链路")
    @allure.title("TC-S100-FLOW-02 飞控链路: fc-uart 在位且串口数据持续落盘")
    @allure.description(
        "[业务阶段2] 飞控透传业务: /dev/fc-uart(udev→ttyCH943X1) 在位, fc-logger.service "
        "active, /log/fc/message* 存在且非空 — 文件持续有数据 = 2Mbaud 透传+落盘业务真实在跑。"
        "仅 v2p0 (0x8) 具备该链路, 其余板级 skip。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "业务流程", "飞控链路")
    def test_02_fc_uart_link(self, ssh_session, board_info, bsp_params):
        if board_info["boardid"] != "0x8":
            pytest.skip(f"板级 {board_info['boardid']!r} 无 ch943x/fc-uart 链路")
        with allure.step("fc-uart 设备在位"):
            dev = bsp_params["fc_uart_dev"]
            code, out = ssh_session.exec_cmd_quiet(f"readlink -f {dev}")
            assert code == 0 and "ttyCH943" in out, (
                f"{dev} 未指向 ttyCH943X: {out!r} — ch943x 未加载或 udev 规则未生效"
            )
        with allure.step("fc-logger 服务 active"):
            code, out = ssh_session.exec_cmd_quiet("systemctl is-active fc-logger.service")
            assert code == 0 and out.strip() == "active", f"fc-logger 非 active: {out!r}"
        with allure.step("飞控数据已落盘 (/log/fc 非空文件)"):
            code, out = ssh_session.exec_cmd_quiet(
                "ls -lL /log/fc/ 2>/dev/null | awk '$5 > 0 {print $NF, $5}'"
            )
            assert code == 0 and out.strip(), (
                "/log/fc 下无非空文件 — fc-logger 未收到飞控数据 "
                "(检查飞控是否上电/接线, 板端无飞控时本阶段数据侧无法验证)"
            )
        log_manager.logger.info(f"[FLOW-02] 飞控链路 OK: {dev} -> {out.splitlines()[-1]}")


    @allure.story("03 MCU外设代理")
    @allure.title("TC-S100-FLOW-03 MCU外设代理: 风扇/温度器件在位且温度可读")
    @allure.description(
        "[业务阶段3] MCU 域外设代理业务在服务: i2c-8 上 tmp112(0x48/0x49) 被驱动占用(UU)、"
        "风扇 emc2301(0x2f) 在位, 温度读数物理合理, 106 线 MCU gpiochip 存在。"
        "⚠ 依赖 MCU 固件实现 instance4 pwm/gpio/i2c 对端 — 当前 s100_mcu 分支 "
        "Ipc_Cfg.c 该实例回调全部为空, 固件就绪前本阶段 skip (config mcu_proxy_enabled)。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "业务流程", "MCU代理")
    def test_03_mcu_peripheral_proxy(self, ssh_session, board_info, bsp_params):
        if not bsp_params.get("mcu_proxy_enabled"):
            pytest.skip(
                "MCU 固件未实现 ins4 pwm/gpio/i2c 对端 (s100_mcu 分支 Ipc_Cfg.c 回调为空) "
                "— 固件就绪后置 config INDV1.mcu_proxy_enabled=true"
            )
        if board_info["boardid"] not in _MCU_BOARDIDS:
            pytest.skip(f"板级 {board_info['boardid']!r} 无 MCU 域外设")
        with allure.step("i2c-8 器件在位/被占用"):
            code, out = ssh_session.exec_cmd_quiet("i2cdetect -y 8", timeout=60)
            assert code == 0, f"i2c-8 扫描失败: {out!r}"
            cells = {}
            for ln in out.splitlines():
                m = re.match(r"^([0-9a-f]{2}):((?:\s+(?:[0-9a-f]{2}|UU|--))+)\s*$", ln)
                if m:
                    base = int(m.group(1), 16)
                    for off, st in enumerate(m.group(2).split()):
                        if st != "--":
                            cells[f"{base + off:02x}"] = st
            assert cells.get("48") == "UU" and cells.get("49") == "UU", (
                f"tmp112 (0x48/0x49) 未被 dmd_temp 占用: {cells} — 温度代理业务不可用"
            )
            assert "2f" in cells, f"风扇 emc2301(0x2f) 无应答且未被占用: {cells}"
        with allure.step("温度读数物理合理"):
            # dmd_temp 注册的 hwmon name 是 "dmdtemp" (非 tmp112), 兼容两种命名
            cmd = (
                'for n in /sys/class/hwmon/hwmon*/name; do '
                'if grep -qiE "dmdtemp|tmp112" "$n" 2>/dev/null; then '
                'd=$(dirname "$n"); cat $d/temp1_input 2>/dev/null; fi; done'
            )
            code, out = ssh_session.exec_cmd_quiet(cmd, timeout=20)
            temps = [int(x) for x in out.split() if x.lstrip("-").isdigit()]
            assert temps, f"温度不可读: {out!r}"
            for mc in temps:
                assert -40.0 <= mc / 1000.0 <= 125.0, f"温度超物理区间: {mc / 1000.0}°C"
        with allure.step("106 线 MCU gpiochip 存在"):
            code, out = ssh_session.exec_cmd_quiet(
                'for c in /sys/class/gpio/gpiochip*; do '
                '[ -e "$c/ngpios" ] && cat $c/ngpios; done 2>/dev/null'
            )
            assert any(x.strip() == "106" for x in out.split()), (
                f"未找到 106 线 mcu_gpiochip: {out!r} — dmd_gpio 代理不可用"
            )
        log_manager.logger.info(
            f"[FLOW-03] MCU 代理 OK: i2c 器件 {sorted(cells)}, "
            f"温度 {sorted(mc / 1000 for mc in temps)}°C"
        )


    @allure.story("04 视频业务")
    @allure.title("TC-S100-FLOW-04 视频端到端: camera→编码→RTSP 推流 150 帧")
    @allure.description(
        "[业务阶段4·核心] 运行官方 smoke dmd_rtsp_test -n 150: 建立 cam0 管线(含 AE) "
        "→ H.265 编码 → RTSP 推流, 定帧自动退出。断言: cam0 up / RTSP up / encoder up "
        "三阶段标记 + [stats] sent≥100 且编码失败帧≤3 + rtsp feeds>0 (码流确实推入 FIFO)。"
        "⚠ 会独占 camera/FPGA, 请在无产品业务进程的环境执行。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("S100", "业务流程", "视频")
    def test_04_video_business_e2e(self, ssh_session, bsp_params):
        binary = f"{bsp_params['ipc_bin_dir']}/dmd_rtsp_test"
        frames = int(bsp_params["rtsp_test_frames"])
        code, out = ssh_session.exec_cmd_quiet(f"test -x {binary}")
        assert code == 0, f"{binary} 不存在 — dmd-bsp deb 未安装"
        with allure.step(f"运行视频业务 {frames} 帧"):
            code, out = ssh_session.exec_cmd_quiet(
                f"{binary} -n {frames}", timeout=300
            )
            allure.attach(out, name="rtsp_business_output", attachment_type=allure.attachment_type.TEXT)
            if "not found" in out and "dmd_camera_init" in out:
                pytest.skip(
                    f"camera sensor 不在位 (台架未接摄像头, dmd_camera_init 探测 chip_id 失败) "
                    f"— 接入摄像头后重跑: {out.strip()[:200]}"
                )
        with allure.step("断言三阶段启动标记"):
            assert "cam0 up" in out, f"camera 管线未建立 (code={code}):\n{out[-800:]}"
            assert "RTSP up" in out, (
                f"RTSP 服务未起来 (code={code}):\n{out[-800:]}"
            )
            assert "encoder up" in out, f"编码器未启动:\n{out[-800:]}"
        with allure.step("断言帧统计"):
            stats = re.findall(
                r"\[stats\] sent=(\d+) fail=(\d+) \| rtsp feeds=(\d+) bytes=(\d+)"
                r" dropped=(\d+) fifo_overwrite=(\d+) clients=(\d+)", out
            )
            assert stats, f"无 [stats] 输出 — 业务循环未运行:\n{out[-800:]}"
            sent = int(stats[-1][0])
            fail = int(stats[-1][1])
            feeds = int(stats[-1][2])
            assert sent >= frames * 2 // 3, f"实际出帧 {sent} < 期望 {frames} 的 2/3"
            assert fail <= 3, f"编码发送失败帧 {fail} > 3"
            assert feeds > 0, "RTSP feeds=0 — 码流未进入推流 FIFO"
        log_manager.logger.info(
            f"[FLOW-04] 视频业务 OK: sent={sent} fail={fail} rtsp_feeds={feeds} "
            f"(feed_dropped={stats[-1][4]}, clients={stats[-1][6]})"
        )


    @allure.story("05 TOF业务")
    @allure.title("TC-S100-FLOW-05 TOF 深度业务: 管线初始化且逐路出深度帧")
    @allure.description(
        "[业务阶段5] dmd_tof_manual_test 全路初始化 + 运行 (timeout -s INT 优雅终止): "
        "断言无 'initialized failed' / 'get_frame failed' 风暴, 且至少一路打印 "
        "'get_frame success' (深度数据真实产出)。全部 TOF 初始化失败视为 sensor "
        "不在位 (台架环境), skip 而非 fail。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "业务流程", "TOF")
    def test_05_tof_business(self, ssh_session, bsp_params):
        binary = f"{bsp_params['ipc_bin_dir']}/dmd_tof_manual_test"
        code, out = ssh_session.exec_cmd_quiet(f"test -x {binary}")
        assert code == 0, f"{binary} 不存在 — dmd-bsp deb 未安装"
        timeout_s = int(bsp_params["tof_probe_timeout_s"])
        with allure.step(f"运行 TOF 业务 {timeout_s}s 后优雅终止"):
            code, out = ssh_session.exec_cmd_quiet(
                f"timeout -s INT {timeout_s} {binary} < /dev/null",
                timeout=timeout_s + 60,
            )
            allure.attach(out, name="tof_business_output", attachment_type=allure.attachment_type.TEXT)
        with allure.step("断言 TOF 业务产出深度帧"):
            assert "dmd_bspinit failed" not in out, f"底软初始化失败:\n{out[-600:]}"
            if "get_frame success" not in out:
                init_failed = re.findall(r"tof (\d+) initialized failed", out)
                pytest.skip(
                    f"TOF sensor 未在位或全部初始化失败 (failed pipes={init_failed}) "
                    f"— 台架无 TOF 模块时本阶段无法验证"
                )
            ok_pipes = sorted(set(re.findall(r"\[(\d+)\]dmd_tof_get_frame success", out)))
            err_frames = len(re.findall(r"dmd_tof_get_frame failed", out))
            assert err_frames <= len(ok_pipes) * 3, (
                f"get_frame 失败次数 {err_frames} 过多 (成功路数 {ok_pipes})"
            )
        log_manager.logger.info(f"[FLOW-05] TOF 业务 OK: 出帧路数 {ok_pipes}")


    @allure.story("06 空域感知")
    @allure.title("TC-S100-FLOW-06 ADS-B 空域感知: 接收机链路 (需显式开启)")
    @allure.description(
        "[业务阶段6] ADS-B 业务: ttyS1(921600) 收 '$...*XOR#' 帧 → 64 架态势表。"
        "需要真实 ADS-B 接收机, config INDV1.adsb_enabled=true 才运行 dmd_adsb_manual_test "
        "(默认 skip); 未开启时仅校验串口设备在位。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "业务流程", "ADS-B")
    def test_06_adsb_business(self, ssh_session, bsp_params):
        with allure.step("ADS-B 串口在位"):
            code, out = ssh_session.exec_cmd_quiet("test -e /dev/ttyS1")
            if code != 0:
                pytest.skip("/dev/ttyS1 不存在 — ADS-B 链路未配置或板级不支持")
        if not bsp_params.get("adsb_enabled"):
            pytest.skip(
                "未接 ADS-B 接收机 — 接好后置 config INDV1.adsb_enabled=true 重跑业务验证"
            )
        binary = f"{bsp_params['ipc_bin_dir']}/dmd_adsb_manual_test"
        code, out = ssh_session.exec_cmd_quiet(f"test -x {binary}")
        assert code == 0, f"{binary} 不存在 — dmd-bsp deb 未安装"
        with allure.step("运行 ADS-B 业务 15s"):
            code, out = ssh_session.exec_cmd_quiet(
                f"timeout -s INT 15 {binary} < /dev/null", timeout=90
            )
            allure.attach(out, name="adsb_business_output", attachment_type=allure.attachment_type.TEXT)
        with allure.step("断言业务初始化成功"):
            # 样例失败输出为 "FAIL: dmd_adsb_init/start/get_version returned N"
            assert (
                "FAIL: dmd_adsb_init" not in out
                and "FAIL: dmd_adsb_start" not in out
                and "FAIL: get_version" not in out
            ), f"ADS-B 初始化失败 (VS00 查版本无应答?):\n{out[-600:]}"
        log_manager.logger.info(f"[FLOW-06] ADS-B 业务链路 OK, 输出尾部: {out[-200:]!r}")
