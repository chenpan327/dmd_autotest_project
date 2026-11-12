# coding: utf-8
"""
===============================================================================
                            h743 UART 随机测试脚本
===============================================================================
脚本编号: DMD_TEST_H743_UART_RANDOM_001
脚本版本: v1.1
创建日期: 2026-09-14
修改日期: 2026-09-17
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: hope_stm32h743vit6 公共开发板 (MCU 底软 UART 驱动)
测试类型: 底软功能验证测试
测试环境: Python 3.10, pytest, allure, 双串口 (Shell 口 + 数据口)

测试目的:
以随机化操作序列验证 h743 板 MCU 底软 UART 驱动的稳定性与容错恢复能力
(飞书行65-74, 共 10 个测试点): 随机操作浸泡(内存泄漏)/任务数量/收发带宽/
错误注入/任务相对优先级/波特率切换。各测试点使用 random.Random(seed) 独立
实例按 (seed + 飞书行号) 派生, 种子经 config.json h743 板段 seed 键配置,
相同种子可完整复现随机序列。

前置条件:
1. 测试环境准备:
   - h743 开发板已运行 ll_drivers_tester 测试固件, Shell 口已接测试主机
     (串口号/波特率见 config.json hope_stm32h743vit6 段 port1/baud1)
   - 被测 UART TX/RX 与主机数据口交叉直连 (串口号见 config 段 port2)
   - conftest 板段配置 fail-fast 校验通过, shellp / uart_args fixture 已就绪
2. 判定语义: 判定字典 rep 中任一值为 False 即该测试点失败, "记录:" 前缀键
   仅作记录, 逐点判定明细挂 Allure 附件
3. 并行约束: 单一 Shell 串口物理独占, 严禁 pytest-xdist / 多进程并行
原理详见: mcu_ll_drivers_tester/ll_drivers_tester_host/doc/uart_test_principle.md 第 10 章

测试步骤:
1. [飞书行65 test_random_memleak] 内存泄漏检测(随机浸泡): 浸泡时长内随机执行
   {双向收发×6 权重/压力任务启停/stat 查询/格式切换/波特率切换/串口重开},
   每步校验应答与数据完整性; 结束后最终收发校验
   (浸泡时长 config soak_seconds, 默认 60s; 72h 长稳 = 259200)
2. [飞书行66 test_random_tx_task_num] 发送任务数量随机: 3 组随机数量(1~12)
   CPU 压力任务, 每组等 3s 过满转期后发送代表长度并比对
3. [飞书行67 test_random_tx_bandwidth] 发送带宽随机: 30 轮随机长度(1~buf)×
   随机间隔(0~200ms)发送序列, 逐笔比对
4. [飞书行68 test_random_rx_bandwidth] 接收带宽随机: 30 轮随机长度×随机到达
   延迟(50~500ms)接收序列, 逐笔校验
5. [飞书行69 test_random_isr_freq] 中断频率随机 (占位): 无法自动化
6. [飞书行70 test_random_error_inject] 随机注入错误/异常: 从错误池
   {break/奇偶错配/位长错配/停止位错配}随机选型 4 轮, 随机间隔注入,
   每轮验证通信恢复
7. [飞书行71 test_random_task_prio] 任务相对优先级随机: 3 组随机组合
   (压力任务优先级 shell 同级/+1/+2 × 数量 2~12), 每组发送+接收校验
8. [飞书行72 test_random_temp] 温度随机波动 (占位): 无法自动化
9. [飞书行73 test_random_voltage] 电压随机波动 (占位): 无法自动化
10. [飞书行74 test_random_baud_switch] 随机切换波特率: 随机抽取 4 档波特率序列,
    逐档切换并双向收发校验, 结束恢复 115200

预期结果（与测试步骤一一对应）:
1. [行65] 全程无 no-mem 应答与异常应答, 浸泡结束后收发正常
   (固件无堆余量查询命令, 以此作泄漏间接判据)
2. [行66] 3 组不同任务数量下发送数据均无丢失
3. [行67] 30 轮随机长度发送全部一致
4. [行68] 30 轮随机延迟接收全部成功
5. [行69] skip (无中断注入手段, 需可编程中断源)
6. [行70] 每轮随机注入后通信均恢复正常
7. [行71] 各优先级×数量组合下收发均一致 (CPU 占用随机波动未模拟)
8. [行72] skip (需温箱等环境试验设备)
9. [行73] skip (需可编程电源)
10. [行74] 随机序列各档收发一致且恢复 115200 后正常

===============================================================================
测试结论:
随机测试 10 个测试点全部实现自动化 (占位点显式 skip 并注明原因), 随机序列
可经 config seed 复现, 判定结果与逐点明细见 Allure 报告各用例的
「判定明细」「串口收发流水」附件。
===============================================================================
"""
import random
import time

import allure
import pytest

from src.Protocol.dmdtest_uart import (
    normal_cmd_ack,
    ack_is_ok,
    normal_recv_data_to_ack,
    OrderAry,
    apply_format_both,
    query_stat,
    query_shell_prio,
    host_roundtrip,
    open_target,
    close_target,
    switch_host_port,
    send_len_series,
    recv_len_series,
    inject_parity_mismatch,
    inject_databits_mismatch,
    inject_stopbits_mismatch,
    inject_break_and_recv_recover,
)
from utils.assert_helper import assert_feishu_rep


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartRandom:
    """随机测试 (飞书行65-74)"""

    @allure.feature("随机测试")
    @allure.story("内存泄漏浸泡")
    @allure.title("飞书行65 内存泄漏检测")
    @allure.description("期望: 内存无泄露。随机操作浸泡: 时长内随机执行{双向收发×6权重/压力任务启停/"
                        "stat查询/格式切换/波特率切换/串口重开}, 每步校验应答与数据完整性。"
                        "72h 长稳: config soak_seconds=259200。"
                        "间接判据: 固件无堆余量查询命令, 以「无 no-mem 应答+功能始终正常」代替")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "随机测试")
    def test_random_memleak(self, shellp, uart_args):
        """飞书行65 | 随机测试 | 内存泄漏检测"""
        rep = {}
        rng = random.Random(uart_args.seed)
        deadline = time.time() + uart_args.soak_seconds
        uartp = None
        rounds = 0
        anomalies = []
        ops = ['roundtrip'] * 6 + ['task', 'stat', 'format', 'baud', 'reopen']
        try:
            uartp, _ = open_target(shellp, uart_args)
            if uartp is None:
                rep['打开串口失败'] = False
                assert_feishu_rep(rep, "飞书行65 内存泄漏检测")
                return
            shell_prio = query_shell_prio(shellp) or 2
            while time.time() < deadline:
                rounds += 1
                op = rng.choice(ops)

                # 操作1: 随机长度双向收发校验
                if op == 'roundtrip':
                    if not host_roundtrip(shellp, uartp, rng.randint(1, uartp.target_maxsize),
                                          rng.randint(33, 100)):
                        anomalies.append(f'第{rounds}轮收发校验失败')

                # 操作2: 压力任务启停(反复创建销毁, 考验堆分配回收; 与Shell同级避免饿死)
                elif op == 'task':
                    num = rng.randint(1, 6)
                    acks = normal_cmd_ack(shellp, f"dmdtest_uart enable id=9 prio={shell_prio} num={num}", 1.5)
                    if 'no-mem' in acks:
                        anomalies.append(f'第{rounds}轮压力任务no-mem')
                    time.sleep(0.5)
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)

                # 操作3: 错误计数查询
                elif op == 'stat':
                    if query_stat(shellp) is None:
                        anomalies.append(f'第{rounds}轮stat查询失败')

                # 操作4: 随机格式切换并恢复(驱动重初始化路径)
                elif op == 'format':
                    parity = rng.choice('NEO')
                    if apply_format_both(shellp, uartp, 8, parity, 1):
                        if not host_roundtrip(shellp, uartp, 32, rng.randint(33, 100)):
                            anomalies.append(f'第{rounds}轮格式切换后收发失败')
                    else:
                        anomalies.append(f'第{rounds}轮格式切换失败')
                    apply_format_both(shellp, uartp, 8, 'N', 1)

                # 操作5: 随机波特率切换并恢复(驱动重初始化路径)
                elif op == 'baud':
                    b = rng.choice([9600, 230400, 460800, 921600])
                    if ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart config baud={b}", 0.3)):
                        uartp = switch_host_port(uart_args, uartp, b)
                        if not host_roundtrip(shellp, uartp, 32, rng.randint(33, 100)):
                            anomalies.append(f'第{rounds}轮波特率切换后收发失败')
                        normal_cmd_ack(shellp, "dmdtest_uart config baud=115200", 0.3)
                        uartp = switch_host_port(uart_args, uartp, 115200)
                    else:
                        anomalies.append(f'第{rounds}轮波特率切换失败')

                # 操作6: 串口关闭重开(Device::open/close 反复执行)
                elif op == 'reopen':
                    close_target(shellp, uartp)
                    uartp, _ = open_target(shellp, uart_args)
                    if uartp is None:
                        anomalies.append(f'第{rounds}轮重开串口失败')
                        time.sleep(0.5)
                time.sleep(rng.uniform(0.01, 0.1))

            # 结束前最终校验
            rep['记录:浸泡时长(s)'] = uart_args.soak_seconds
            rep['记录:随机操作轮数'] = rounds
            rep['无no-mem与异常应答'] = (len(anomalies) == 0)
            if anomalies:
                rep['记录:异常清单(前10条)'] = ';'.join(anomalies[:10])
            rep['浸泡后收发正常'] = uartp is not None and host_roundtrip(shellp, uartp, 64, ord('H'))
            rep['说明'] = '无堆余量查询命令, 以无no-mem应答+功能正常作泄漏间接判据'
        finally:
            if uartp:
                close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行65 内存泄漏检测")

    @allure.feature("随机测试")
    @allure.story("发送任务数量随机")
    @allure.title("飞书行66 发送任务数量随机")
    @allure.description("期望: 数据不丢失。"
                        "近似: 固件后台任务单实例限制, 以随机数量(1~12) CPU 压力任务 + Shell 发送校验, "
                        "3 组, 每组等 3s 过满转期")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "随机测试")
    def test_random_tx_task_num(self, shellp, uart_args):
        """飞书行66 | 随机测试 | 发送任务数量随机"""
        rep = {}
        rng = random.Random(uart_args.seed + 66)
        uartp, maxsize = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                shell_prio = query_shell_prio(shellp) or 2
                lengths = [1, maxsize // 2, maxsize]
                for grp in range(3):
                    num = rng.randint(1, 12)

                    # 步骤1: 启动随机数量的高优先级压力任务
                    if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart enable id=9 prio={shell_prio+1} num={num}", 1.5)):
                        rep[f'第{grp+1}组({num}个任务)启动失败'] = False
                        continue

                    # 步骤2: 等3s过满转期(压力任务3s后周期让出)
                    time.sleep(3.0)
                    uartp.recv_data(timeout=0)

                    # 步骤3: 该组合下发送代表长度并比对
                    sub = send_len_series(shellp, uartp, lengths)
                    rep[f'第{grp+1}组({num}个压力任务)发送一致'] = all(sub.values())

                    # 步骤4: 停止压力任务
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp.recv_data(timeout=0)
                rep['说明'] = '固件单后台任务限制, 以随机数量CPU压力任务近似多发送任务场景'
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行66 发送任务数量随机")

    @allure.feature("随机测试")
    @allure.story("发送带宽随机")
    @allure.title("飞书行67 发送带宽随机")
    @allure.description("期望: 数据不丢失。30 轮随机长度(1~buf)×随机间隔(0~200ms)的发送序列, 逐笔比对")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "随机测试")
    def test_random_tx_bandwidth(self, shellp, uart_args):
        """飞书行67 | 随机测试 | 发送带宽随机"""
        rep = {}
        rng = random.Random(uart_args.seed + 67)
        uartp, maxsize = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                for i in range(30):
                    n = rng.randint(1, maxsize)
                    seedfrom = rng.randint(33, 100)
                    rep[f'第{i+1}轮(长度{n})一致'] = False

                    # 步骤1: 随机长度发送
                    uartp.recv_data(timeout=0)
                    acks = normal_cmd_ack(shellp, f"dmdtest_uart send len={n} from={seedfrom} to={seedfrom+8} timeout=-1",
                                          0.1 + n * 10 / uartp.baudrate)

                    # 步骤2: 比对
                    time.sleep(0.05)
                    rdata = uartp.recv_data(timeout=0.2)
                    if ack_is_ok(acks) and rdata and rdata == OrderAry(n, seedfrom, seedfrom + 8).to_bytes():
                        rep[f'第{i+1}轮(长度{n})一致'] = True

                    # 步骤3: 随机间隔(模拟随机发送带宽)
                    time.sleep(rng.uniform(0, 0.2))
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行67 发送带宽随机")

    @allure.feature("随机测试")
    @allure.story("接收带宽随机")
    @allure.title("飞书行68 接收带宽随机")
    @allure.description("期望: 数据不丢失。30 轮随机长度×随机到达延迟(50~500ms)的接收序列, 逐笔校验")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "随机测试")
    def test_random_rx_bandwidth(self, shellp, uart_args):
        """飞书行68 | 随机测试 | 接收带宽随机"""
        rep = {}
        rng = random.Random(uart_args.seed + 68)
        uartp, maxsize = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                for i in range(30):
                    n = rng.randint(1, maxsize)
                    seedfrom = rng.randint(33, 100)
                    rep[f'第{i+1}轮(长度{n})接收成功'] = False

                    # 步骤1: 下发接收命令(1000ms 窗口)
                    uartp.recv_data(timeout=0)
                    cmd = f"dmdtest_uart recv len={n} from={seedfrom} to={seedfrom+8} timeout=1000"
                    shellp.send_text(cmd + '\r\n')

                    # 步骤2: 随机延迟后送达数据(模拟随机接收带宽)
                    time.sleep(rng.uniform(0.05, 0.5))
                    uartp.send_data(OrderAry(n, seedfrom, seedfrom + 8).to_bytes())

                    # 步骤3: 校验
                    time.sleep(0.1 + n * 10 / uartp.baudrate)
                    acks = normal_recv_data_to_ack(shellp, cmd, 2.0)
                    if ack_is_ok(acks) and len(acks.split()) > 2 and int(acks.split()[2]) == n:
                        rep[f'第{i+1}轮(长度{n})接收成功'] = True
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行68 接收带宽随机")

    @allure.feature("随机测试")
    @allure.story("中断频率随机")
    @allure.title("飞书行69 中断频率随机(占位)")
    @allure.description("期望: 数据不丢失。"
                        "占位: 无中断注入手段, 任务级 CPU 压力不能模拟真实高频中断抢占, "
                        "需可编程中断源(如定时器中断风暴)后补全")
    @allure.severity(allure.severity_level.MINOR)
    @allure.tag("UART", "随机测试", "占位")
    def test_random_isr_freq(self):
        """飞书行69 | 随机测试 | 中断频率随机(占位, 无法自动化)"""
        pytest.skip('无中断注入手段, 需可编程中断源(如定时器中断风暴)')

    @allure.feature("随机测试")
    @allure.story("随机注入错误/异常")
    @allure.title("飞书行70 随机注入错误/异常")
    @allure.description("期望: 不影响下一帧的收发。"
                        "从错误池{break/奇偶错配/位长错配/停止位错配}随机选型, 随机间隔(0.1~0.5s)注入, "
                        "每轮注入后验证通信恢复正常")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "随机测试")
    def test_random_error_inject(self, shellp, uart_args):
        """飞书行70 | 随机测试 | 随机注入错误/异常"""
        rep = {}
        rng = random.Random(uart_args.seed + 70)
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                injectors = {
                    'break':    lambda: {'break后接收恢复': inject_break_and_recv_recover(shellp, uartp, ord('I'))[0]},
                    '奇偶错配': lambda: inject_parity_mismatch(shellp, uartp, 64, ord('J')),
                    '位长错配': lambda: inject_databits_mismatch(shellp, uartp, 64, ord('K')),
                    '停止位错配': lambda: inject_stopbits_mismatch(shellp, uartp, 2048, ord('L')),
                }
                for rnd_i in range(4):
                    name = rng.choice(list(injectors.keys()))

                    # 步骤1: 随机间隔(注入频率不需要太高)
                    time.sleep(rng.uniform(0.1, 0.5))

                    # 步骤2: 随机选型注入
                    sub = injectors[name]()
                    ok = not any(v is False for v in sub.values())
                    rep[f'第{rnd_i+1}轮({name})注入后恢复正常'] = ok
                    rep[f'记录:第{rnd_i+1}轮({name})明细'] = dict(sub)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行70 随机注入错误/异常")

    @allure.feature("随机测试")
    @allure.story("任务相对优先级随机")
    @allure.title("飞书行71 任务相对优先级随机")
    @allure.description("期望: 随机出现比收发任务优先级相等/更高的任务时数据不丢失。"
                        "3 组随机组合: 压力任务优先级(shell同级/+1/+2)×数量(2~12), "
                        "每组下发送+接收代表长度校验(CPU 占用随机波动未模拟)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "随机测试")
    def test_random_task_prio(self, shellp, uart_args):
        """飞书行71 | 随机测试 | 任务相对优先级随机"""
        rep = {}
        rng = random.Random(uart_args.seed + 71)
        uartp, maxsize = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                shell_prio = query_shell_prio(shellp) or 2
                lengths = [1, maxsize // 2, maxsize]
                for grp in range(3):
                    prio = shell_prio + rng.choice([0, 1, 2])
                    num = rng.randint(2, 12)

                    # 步骤1: 启动随机优先级×随机数量的压力任务
                    if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart enable id=9 prio={prio} num={num}", 1.5)):
                        rep[f'第{grp+1}组(P{prio},M{num})启动失败'] = False
                        continue

                    # 步骤2: 等3s过满转期
                    time.sleep(3.0)
                    uartp.recv_data(timeout=0)

                    # 步骤3: 该组合下发送+接收校验
                    sub_s = send_len_series(shellp, uartp, lengths)
                    sub_r = recv_len_series(shellp, uartp, lengths)
                    rep[f'第{grp+1}组(P{prio},M{num})收发一致'] = all(sub_s.values()) and all(sub_r.values())

                    # 步骤4: 停止
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp.recv_data(timeout=0)
                rep['说明'] = '优先级×数量随机组合已覆盖; CPU占用随机波动未模拟(压力任务恒定耗CPU)'
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行71 任务相对优先级随机")

    @allure.feature("随机测试")
    @allure.story("温度随机波动")
    @allure.title("飞书行72 温度随机波动(占位)")
    @allure.description("期望: 数据不丢失。占位: 需温箱等环境试验设备, 软件测试框架无法实现")
    @allure.severity(allure.severity_level.MINOR)
    @allure.tag("UART", "随机测试", "占位")
    def test_random_temp(self):
        """飞书行72 | 随机测试 | 温度随机波动(占位, 无法自动化)"""
        pytest.skip('需温箱等环境试验设备, 软件测试框架无法实现')

    @allure.feature("随机测试")
    @allure.story("电压随机波动")
    @allure.title("飞书行73 电压随机波动(占位)")
    @allure.description("期望: 数据不丢失。占位: 需可编程电源, 软件测试框架无法实现")
    @allure.severity(allure.severity_level.MINOR)
    @allure.tag("UART", "随机测试", "占位")
    def test_random_voltage(self):
        """飞书行73 | 随机测试 | 电压随机波动(占位, 无法自动化)"""
        pytest.skip('需可编程电源, 软件测试框架无法实现')

    @allure.feature("随机测试")
    @allure.story("随机切换波特率")
    @allure.title("飞书行74 随机切换波特率")
    @allure.description("期望: 数据不丢失。"
                        "随机抽取波特率序列(rng.sample), 逐档切换+双向收发校验; "
                        "「数据流不断的随机切换」由行60-62 动态重配置组专项覆盖")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "随机测试")
    def test_random_baud_switch(self, shellp, uart_args):
        """飞书行74 | 随机测试 | 随机切换波特率"""
        rep = {}
        rng = random.Random(uart_args.seed + 74)
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seq = rng.sample([9600, 115200, 230400, 460800, 921600], 4)
                rep['记录:随机波特率序列'] = '→'.join(str(b) for b in seq)
                seedfrom = ord('M')

                # 步骤1: 逐档切换并校验
                for baud in seq:
                    seedfrom += 1
                    if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart config baud={baud}", 0.3)):
                        rep[f'波特率{baud}切换失败'] = False
                        continue
                    uartp = switch_host_port(uart_args, uartp, baud)
                    rep[f'波特率{baud}下收发一致'] = host_roundtrip(shellp, uartp, 64, seedfrom)

                # 步骤2: 恢复 115200
                normal_cmd_ack(shellp, "dmdtest_uart config baud=115200", 0.3)
                uartp = switch_host_port(uart_args, uartp, 115200)
                rep['恢复115200后收发正常'] = host_roundtrip(shellp, uartp, 64, ord('N'))
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行74 随机切换波特率")
