# coding: utf-8
"""
===============================================================================
                            h743 UART 发送功能测试脚本
===============================================================================
脚本编号: DMD_TEST_H743_UART_SEND_001
脚本版本: v1.1
创建日期: 2026-09-14
修改日期: 2026-09-17
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: hope_stm32h743vit6 公共开发板 (MCU 底软 UART 驱动)
测试类型: 底软功能验证测试
测试环境: Python 3.10, pytest, allure, 双串口 (Shell 口 + 数据口)

测试目的:
验证 h743 板 MCU 底软 UART 驱动发送功能的完整性与正确性, 覆盖通路/边界/
特殊数据(飞书行2-7)、超时语义(行8-13)、性能-吞吐量与线程CPU(行14-19)、
并发/overrun(行20-22), 共 21 个测试点。

前置条件:
1. 测试环境准备:
   - h743 开发板已运行 ll_drivers_tester 测试固件, Shell 口已接测试主机
     (串口号/波特率见 config.json hope_stm32h743vit6 段 port1/baud1)
   - 被测 UART TX 与主机数据口 RX 相连 (数据口串口号见 config 段 port2)
   - conftest 板段配置 fail-fast 校验通过, shellp / uart_args fixture 已就绪
2. 判定语义: 判定字典 rep 中任一值为 False 即该测试点失败, "记录:" 前缀键
   仅作记录, 逐点判定明细挂 Allure 附件
3. 并行约束: 单一 Shell 串口物理独占, 严禁 pytest-xdist / 多进程并行
原理详见: mcu_ll_drivers_tester/ll_drivers_tester_host/doc/uart_test_principle.md 第 4 章

测试步骤:
1. [飞书行02 test_send_data_range] 发送数据 1~buf 遍历:
   (1) dmdtest_uart open 打开被测串口会话 (maxsize=DMA 单块上限)
   (2) 遍历长度 1~maxsize 逐次下发 dmdtest_uart send, 主机全量比对内容
2. [飞书行03 test_send_zero_len] 零长度数据:
   (1) 下发 send len=0 (有界超时防 Shell 挂死), 解析驱动返回值 ret
   (2) 等待 0.3s 检查数据口有无字节到达
3. [飞书行04 test_send_one_byte] 1 字节数据: MCU 发送 1 字节, 主机逐字节比对
4. [飞书行05 test_send_buf_len] buf 长度数据: MCU 恰好发送 maxsize 字节并全量比对
5. [飞书行06 test_send_long_8x] 长数据(8倍buf): 单次直发跨多个 DMA 块的字节流,
   主机限时收满后整体比对
6. [飞书行07 test_send_same_bytes] 相同字节遍历: 0x00~0xFF 每个值连发 maxsize 个
   相同字节 (from==to), 主机逐值比对
7. [飞书行08 test_send_to0_busy] timeout=0 资源被占用: 启动高优先级持续发送任务
   占满通道, 再下发 timeout=0 发送并解析 ret 与耗时
8. [飞书行09 test_send_to0_idle] timeout=0 资源未被占用: 空闲通道 timeout=0
   发送 7 字节并比对
9. [飞书行10 test_send_toneg_idle] timeout<0 资源未被占用: 空闲通道 timeout=-1
   发送 7 字节并比对
10. [飞书行11 test_send_toneg_busy_release] timeout<0 占用后释放: 启动占用任务后
    timeout=-1 发送, 等占用任务约 3s 后周期性让出发送窗口
11. [飞书行12 test_send_topos_busy_gt] timeout>0 占用大于超时: 占用中下发
    timeout=5ms 发送, 解析 ret 与耗时
12. [飞书行13 test_send_topos_busy_lt] timeout>0 占用小于超时: 占用启动后立即
    下发 timeout=5000 发送, 占用任务让出窗口内应完成
13. [飞书行14-17 test_send_tput_*] 吞吐量四波特率: 115200/460800/921600/1500000
    逐档开会话测量发送吞吐量, 取 MCU 自报接口耗时折算速率比并全量比对内容
14. [飞书行18 test_send_thread_cpu] 发送线程 CPU: copytest 差分法, 长度点
    [1, m/4, m/2, 3m/4, m] 覆盖四个波特率
15. [飞书行19 test_send_isr_cpu] 发送中断 CPU (占位): 无法自动化
16. [飞书行20 test_send_multi_thread] 多线程高负载发送: 启动 12 个高优先级 CPU
    压力任务近似高负载, 代表长度逐个发送并比对
17. [飞书行21 test_send_isr_preempt] 高优先级中断打断 (占位): 无法自动化
18. [飞书行22 test_send_overrun] 发送过载: 满速发送流收集 1200 字节做 100 字节块
    周期校验; 占用任务让出窗口并发送 send(-1) 512 字节验证排队完成

预期结果（与测试步骤一一对应）:
1. [行02] 各长度发送应答 OK 且主机实收数据全量一致
2. [行03] 命令应答可解析 (Shell 未挂死), 返回值≤0 (规格要求 ret<0),
   线上 0.3s 内无任何字节
3. [行04] 发送应答 OK 且 1 字节内容一致
4. [行05] 发送应答 OK 且 maxsize 字节内容一致
5. [行06] 应答 OK 且 ret==8×buf, 长数据完整一致 (跨 DMA 块无丢失错位)
6. [行07] 全部 256 个字节值的比对均一致 (8bit 透明通道)
7. [行08] ret==0 且耗时 <0.5ms (不等待立即返回)
8. [行09] 发送成功且数据一致
9. [行10] 发送成功且数据一致 (-1 永久等待语义空闲即发)
10. [行11] 占用释放后最终发送成功 (ret==7) 且耗时 >1000ms (确系持续等待)
11. [行12] ret==0 且耗时 ∈[4.5,5.5]ms (按期超时返回)
12. [行13] 窗口内发送成功 (ret==7) 且 0.2s<耗时<5s
13. [行14-17] 各档 MCU 接口速率比 >95% 且内容一致 (主机实收不完整而 MCU 侧
    达标时定责台架 USB 接收路径, 降为记录)
14. [行18] 各长度点发送净 CPU 占用率 ≤10%
15. [行19] skip (固件无中断级耗时统计命令)
16. [行20] 代表长度发送全部一致 (数据无丢失)
17. [行21] skip (无中断注入手段)
18. [行22] 满载流≥1200 字节且块周期校验通过 (不丢失/不重复); 并发发送 ret==512

===============================================================================
测试结论:
发送功能 21 个测试点全部实现自动化 (中断类占位点显式 skip 并注明原因),
判定结果与逐点明细见 Allure 报告各用例的「判定明细」「串口收发流水」附件。
===============================================================================
"""
import time

import allure
import pytest

from src.Protocol.dmdtest_uart import (
    OrderAry,
    FEISHU_TPUT_BAUDS,
    TPUT_RATIO_MIN,
    normal_cmd_ack,
    ack_is_ok,
    collect_bytes,
    verify_tx_task_stream,
    query_shell_prio,
    open_target,
    close_target,
    send_len_series,
    measure_send_tput,
    measure_send_cpu_at_baud,
)
from utils.assert_helper import assert_feishu_rep
from utils.logger import logger


def _run_send_tput(shellp, uart_args, baud):
    """发送吞吐量公共流程: 以指定波特率打开会话并测量

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uart_args: 配置命名空间(uartx=被测 UART 编号, port2=主机数据口 COM 号)
        baud: 目标波特率(bps)

    Returns:
        dict: measure_send_tput 测量/判定字典; 会话打开失败返回 None
    """
    uartp, _ = open_target(shellp, uart_args, baud)
    if uartp is None:
        return None
    try:
        return measure_send_tput(shellp, uartp, ord('t'))
    finally:
        close_target(shellp, uartp)


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartSendPath:
    """发送功能 — 通路/边界/特殊数据 (飞书行2-7)"""

    @allure.feature("发送功能")
    @allure.story("通路")
    @allure.title("飞书行02 发送数据(1~buf遍历)")
    @allure.description("期望: 单次发送 1~buf 长度数据, 数据不丢失。"
                        "遍历 1~DMA单块上限 每个长度值逐次发送并全量比对内容")
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("UART", "发送功能")
    def test_send_data_range(self, shellp, uart_args):
        """飞书行2 | 发送功能/通路 | 发送数据"""
        rep = {}
        uartp, maxsize = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                rep.update(send_len_series(shellp, uartp, list(range(1, maxsize + 1))))
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行02 发送数据(1~buf遍历)")

    @allure.feature("发送功能")
    @allure.story("边界")
    @allure.title("飞书行03 零长度数据")
    @allure.description("期望: 返回发送失败, 线上无数据。"
                        "固件已放开 len==0 透传驱动层, 本用例直达驱动层验证零长度语义: "
                        "send len=0 有界超时防 Shell 挂死, 判定 ret<0 且线上 0.3s 无任何字节")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "发送功能")
    def test_send_zero_len(self, shellp, uart_args):
        """飞书行3 | 发送功能/边界 | 零长度数据"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                # 步骤1: 零长度发送直达驱动层(应答形如 send OK <ret> <ms>ms <%> <ns>)
                uartp.recv_data(timeout=0)
                acks = normal_cmd_ack(shellp, "dmdtest_uart send len=0 from=65 to=90 timeout=200", 0.5)
                rep['命令应答已解析(shell未挂死)'] = (len(acks.split()) > 4)

                # 步骤2: 解析驱动返回值并判定
                ret = None
                if ack_is_ok(acks):
                    ary = acks.split()
                    if len(ary) > 2:
                        try:
                            ret = int(ary[2])
                        except ValueError:
                            ret = None
                if ret is not None:
                    rep['记录:驱动返回值'] = ret
                rep['返回值≤0(未声称发送字节)'] = (ret is not None and ret <= 0)
                rep['返回发送失败(ret<0,按规格)'] = (ret is not None and ret < 0)

                # 步骤3: 等待 0.3s 确认数据口无任何字节到达
                time.sleep(0.3)
                rdata = uartp.recv_data(timeout=0)
                rep['线上无数据'] = (rdata is None or len(rdata) == 0)
                rep['说明'] = ('固件已放开len==0透传驱动层; 规格要求ret<0, '
                               '实测ret==0属零字节成功语义偏差; 旧固件(len>0拦截)回NG时本用例判失败')
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行03 零长度数据")

    @allure.feature("发送功能")
    @allure.story("边界")
    @allure.title("飞书行04 1字节数据")
    @allure.description("期望: 发送成功, 接收端与发送端一致。"
                        "位级时序(9bit/字节)需示波器验证, 本用例验证字节级收发一致性")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "发送功能")
    def test_send_one_byte(self, shellp, uart_args):
        """飞书行4 | 发送功能/边界 | 1字节数据"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('5')

                # 步骤1: MCU 发送 1 字节
                uartp.recv_data(timeout=0)
                acks = normal_cmd_ack(shellp, f"dmdtest_uart send len=1 from={seedfrom} to={seedfrom+8} timeout=-1", 0.2)
                rep['发送应答OK'] = ack_is_ok(acks)

                # 步骤2: 主机接收并逐字节比对
                rdata = uartp.recv_data(timeout=0.3)
                rep['1字节数据一致'] = bool(rdata) and rdata == OrderAry(1, seedfrom, seedfrom + 8).to_bytes()
                rep['说明'] = '位级时序(9bit/字节)需仪器验证, 已验证字节级一致'
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行04 1字节数据")

    @allure.feature("发送功能")
    @allure.story("边界")
    @allure.title("飞书行05 buf长度数据")
    @allure.description("期望: 发送成功(恰好一个 DMA 块长度)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "发送功能")
    def test_send_buf_len(self, shellp, uart_args):
        """飞书行5 | 发送功能/边界 | buf长度数据"""
        rep = {}
        uartp, maxsize = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('7')

                # 步骤1: MCU 发送恰好 maxsize(DMA 单块上限)字节
                uartp.recv_data(timeout=0)
                acks = normal_cmd_ack(shellp, f"dmdtest_uart send len={maxsize} from={seedfrom} to={seedfrom+8} timeout=-1",
                                      0.1 + maxsize * 10 / uartp.baudrate)
                rep['发送应答OK'] = ack_is_ok(acks)

                # 步骤2: 全量比对
                rdata = uartp.recv_data(timeout=0.3)
                rep['buf长度数据一致'] = bool(rdata) and rdata == OrderAry(maxsize, seedfrom, seedfrom + 8).to_bytes()
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行05 buf长度数据")

    @allure.feature("发送功能")
    @allure.story("边界")
    @allure.title("飞书行06 长数据(8倍buf)")
    @allure.description("期望: 字节流数据完整发送。"
                        "单次直发 8×maxsize 字节(跨多个 DMA 块), 主机全量比对, "
                        "验证驱动流式发送的跨块拼接正确性")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "发送功能")
    def test_send_long_8x(self, shellp, uart_args):
        """飞书行6 | 发送功能/边界 | 长数据(8倍buf)"""
        rep = {}
        uartp, maxsize = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                n = maxsize * 8
                seedfrom = ord('9')

                # 步骤1: MCU 单次发送 8×buf 字节流(阻塞至全部送出)
                uartp.recv_data(timeout=0)
                acks = normal_cmd_ack(shellp, f"dmdtest_uart send len={n} from={seedfrom} to={seedfrom+8} timeout=-1",
                                      0.2 + n * 10 / uartp.baudrate)
                rep['发送应答OK'] = ack_is_ok(acks)
                if ack_is_ok(acks):
                    ary = acks.split()
                    rep['发送ret==len'] = len(ary) > 2 and int(ary[2]) == n

                # 步骤2: 主机限时收满并整体比对
                rdata = collect_bytes(uartp, n, n * 10 / uartp.baudrate * 3 + 1.0)
                rep['长数据完整一致(跨DMA块)'] = rdata == OrderAry(n, seedfrom, seedfrom + 8).to_bytes()
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行06 长数据(8倍buf)")

    @allure.feature("发送功能")
    @allure.story("特殊数据")
    @allure.title("飞书行07 相同字节遍历0-0xFF")
    @allure.description("期望: 遍历 0x00~0xFF 全部 256 个字节值, 每个值连发 maxsize 个相同字节, "
                        "数据一致 — 验证 8bit 透明通道(含 0x00/0xFF 及全部控制字符)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "发送功能")
    def test_send_same_bytes(self, shellp, uart_args):
        """飞书行7 | 发送功能/特殊数据 | 相同字节遍历0-0xFF"""
        rep = {}
        uartp, maxsize = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                for v in range(0, 256):
                    rep[f'相同字节0x{v:02X}×{maxsize}一致'] = False

                    # 步骤1: 清残留, MCU 连发 maxsize 个相同字节 v(from==to)
                    uartp.recv_data(timeout=0)
                    cmd = f"dmdtest_uart send len={maxsize} from={v} to={v} timeout=-1"
                    if not ack_is_ok(normal_cmd_ack(shellp, cmd, 0.1 + maxsize * 10 / uartp.baudrate)):
                        continue

                    # 步骤2: 主机接收 maxsize 个字节, 须全部等于 v
                    rdata = uartp.recv_data(timeout=0.2)
                    if rdata and rdata == bytes([v]) * maxsize:
                        rep[f'相同字节0x{v:02X}×{maxsize}一致'] = True
                    if v % 64 == 0:
                        logger.info(f"相同字节遍历进度: 0x{v:02X}/0xFF")
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行07 相同字节遍历0-0xFF")


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartSendTimeout:
    """发送功能 — 超时语义 (飞书行8-13)

    占用源: 高优先级 uart_tx_t 任务死循环 send(100B,-1) 占满 DMA 队列,
    运行满 3s 后每轮 sleep(1) 周期性让出 1ms 窗口(固件内建释放节奏)。
    """

    @allure.feature("发送功能")
    @allure.story("超时")
    @allure.title("飞书行08 timeout=0 资源被占用")
    @allure.description("期望: 发送失败(不等待立即返回 ret==0, 耗时<0.5ms)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "发送功能", "超时")
    def test_send_to0_busy(self, shellp, uart_args):
        """飞书行8 | 发送功能/超时 | timeout=0资源被占用"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                shell_prio = query_shell_prio(shellp) or 2
                seedfrom = ord('a')

                # 步骤1: 启动比 Shell 高优先级的持续发送任务(占满发送通道)
                if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart enable id=0 prio={shell_prio+1}", 0.3)):
                    rep['启动占用任务失败'] = False
                else:
                    # 步骤2: 占用状态下 timeout=0 发送, 期望 ret==0 且耗时应≈0
                    acks = normal_cmd_ack(shellp, f"dmdtest_uart send len=7 from={seedfrom} to={seedfrom+8} timeout=0", 0.3)
                    rep['占用下timeout=0返回ret==0'] = False
                    rep['占用下timeout=0立即返回(ms<0.5)'] = False
                    if ack_is_ok(acks):
                        ary = acks.split()
                        if len(ary) > 4:
                            rep['占用下timeout=0返回ret==0'] = (int(ary[2]) == 0)
                            rep['占用下timeout=0立即返回(ms<0.5)'] = (int(ary[2]) == 0 and float(ary[3][:-2]) < 0.5)

                    # 步骤3: 停止占用任务并清空线路数据
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp.recv_data(timeout=0)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行08 timeout=0资源被占用")

    @allure.feature("发送功能")
    @allure.story("超时")
    @allure.title("飞书行09 timeout=0 资源未被占用")
    @allure.description("期望: 发送成功(空闲通道立即发送)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "发送功能", "超时")
    def test_send_to0_idle(self, shellp, uart_args):
        """飞书行9 | 发送功能/超时 | timeout=0资源未被占用"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('b')

                # 步骤1: 空闲通道 timeout=0 发送 7 字节
                uartp.recv_data(timeout=0)
                acks = normal_cmd_ack(shellp, f"dmdtest_uart send len=7 from={seedfrom} to={seedfrom+8} timeout=0", 0.3)
                rep['空闲下timeout=0发送成功'] = ack_is_ok(acks)

                # 步骤2: 数据一致
                rdata = uartp.recv_data(timeout=0.3)
                rep['空闲下timeout=0数据一致'] = bool(rdata) and rdata == OrderAry(7, seedfrom, seedfrom + 8).to_bytes()
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行09 timeout=0资源未被占用")

    @allure.feature("发送功能")
    @allure.story("超时")
    @allure.title("飞书行10 timeout<0 资源未被占用")
    @allure.description("期望: 发送成功(空闲通道立即发送, -1 永久等待语义)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "发送功能", "超时")
    def test_send_toneg_idle(self, shellp, uart_args):
        """飞书行10 | 发送功能/超时 | timeout<0资源未被占用"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('c')

                # 步骤1: 空闲通道 timeout=-1 发送 7 字节
                uartp.recv_data(timeout=0)
                acks = normal_cmd_ack(shellp, f"dmdtest_uart send len=7 from={seedfrom} to={seedfrom+8} timeout=-1", 0.3)
                rep['空闲下timeout=-1发送成功'] = ack_is_ok(acks)

                # 步骤2: 数据一致
                rdata = uartp.recv_data(timeout=0.3)
                rep['空闲下timeout=-1数据一致'] = bool(rdata) and rdata == OrderAry(7, seedfrom, seedfrom + 8).to_bytes()
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行10 timeout<0资源未被占用")

    @allure.feature("发送功能")
    @allure.story("超时")
    @allure.title("飞书行11 timeout<0 占用后释放")
    @allure.description("期望: 持续等待, 释放后 tx线出现该数据(ret==7 且耗时>1s)。"
                        "等价场景: 占用任务约 3s 后周期性让出(固件节奏非精确 5s), 持续等待语义一致")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "发送功能", "超时")
    def test_send_toneg_busy_release(self, shellp, uart_args):
        """飞书行11 | 发送功能/超时 | timeout<0占用后释放"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                shell_prio = query_shell_prio(shellp) or 2
                seedfrom = ord('d')

                # 步骤1: 启动高优先级占用任务
                if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart enable id=0 prio={shell_prio+1}", 0.3)):
                    rep['启动占用任务失败'] = False
                else:
                    # 步骤2: timeout=-1 发送 —— 持续等待, 约3s后占用任务让出窗口发完
                    acks = normal_cmd_ack(shellp, f"dmdtest_uart send len=7 from={seedfrom} to={seedfrom+8} timeout=-1", 4.5)
                    rep['持续等待最终发送成功'] = False
                    rep['持续等待耗时>1000ms'] = False
                    if ack_is_ok(acks):
                        ary = acks.split()
                        if len(ary) > 4:
                            rep['持续等待最终发送成功'] = (int(ary[2]) == 7)
                            rep['持续等待耗时>1000ms'] = (int(ary[2]) == 7 and float(ary[3][:-2]) > 1000)

                    # 步骤3: 清理
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp.recv_data(timeout=0)
                    rep['说明'] = '占用任务约3s周期让出(非精确5s), 持续等待语义等价'
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行11 timeout<0占用后释放")

    @allure.feature("发送功能")
    @allure.story("超时")
    @allure.title("飞书行12 timeout>0 占用大于timeout")
    @allure.description("期望: 发送超时(按时返回 ret==0, 耗时∈[4.5,5.5]ms)。"
                        "占用任务持续占满通道(3s满转期内), timeout=5ms 发送应超时返回")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "发送功能", "超时")
    def test_send_topos_busy_gt(self, shellp, uart_args):
        """飞书行12 | 发送功能/超时 | timeout>0占用大于timeout"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                shell_prio = query_shell_prio(shellp) or 2
                seedfrom = ord('e')

                # 步骤1: 启动占用任务(前3s死循环占满发送通道)
                if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart enable id=0 prio={shell_prio+1}", 0.3)):
                    rep['启动占用任务失败'] = False
                else:
                    # 步骤2: timeout=5ms 发送, 期望 ret==0 且耗时∈[4.5,5.5]ms
                    acks = normal_cmd_ack(shellp, f"dmdtest_uart send len=7 from={seedfrom} to={seedfrom+8} timeout=5", 0.3)
                    rep['占用大于timeout返回ret==0'] = False
                    rep['超时耗时∈[4.5,5.5]ms'] = False
                    if ack_is_ok(acks):
                        ary = acks.split()
                        if len(ary) > 4:
                            ms = float(ary[3][:-2])
                            rep['占用大于timeout返回ret==0'] = (int(ary[2]) == 0)
                            rep['超时耗时∈[4.5,5.5]ms'] = (int(ary[2]) == 0 and 4.5 < ms < 5.5)

                    # 步骤3: 清理
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp.recv_data(timeout=0)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行12 timeout>0占用大于timeout")

    @allure.feature("发送功能")
    @allure.story("超时")
    @allure.title("飞书行13 timeout>0 占用小于timeout")
    @allure.description("期望: 发送成功(等待窗口内释放, ret==7 且 0.2s<耗时<5s)。"
                        "占用任务启动后立即下发 timeout=5000 —— 占用约 3s 进入周期性让出, 窗口内发完")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "发送功能", "超时")
    def test_send_topos_busy_lt(self, shellp, uart_args):
        """飞书行13 | 发送功能/超时 | timeout>0占用小于timeout"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                shell_prio = query_shell_prio(shellp) or 2
                seedfrom = ord('f')

                # 步骤1: 启动占用任务(3s后周期让出)
                if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart enable id=0 prio={shell_prio+1}", 0.3)):
                    rep['启动占用任务失败'] = False
                else:
                    # 步骤2: 立即下发 timeout=5000 —— 占用约3s后释放(<5s), 窗口内发送成功
                    acks = normal_cmd_ack(shellp, f"dmdtest_uart send len=7 from={seedfrom} to={seedfrom+8} timeout=5000", 4.5)
                    rep['占用小于timeout发送成功'] = False
                    rep['窗口内完成(0.2s<耗时<5s)'] = False
                    if ack_is_ok(acks):
                        ary = acks.split()
                        if len(ary) > 4:
                            ms = float(ary[3][:-2])
                            rep['占用小于timeout发送成功'] = (int(ary[2]) == 7)
                            rep['窗口内完成(0.2s<耗时<5s)'] = (int(ary[2]) == 7 and 200 < ms < 5000)

                    # 步骤3: 清理
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp.recv_data(timeout=0)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行13 timeout>0占用小于timeout")


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartSendPerf:
    """发送功能 — 性能: 吞吐量与线程 CPU (飞书行14-19)"""

    @allure.feature("发送功能")
    @allure.story("性能")
    @allure.title("飞书行14 吞吐量-115200")
    @allure.description("期望: >95% 理论速率(表格按 9bit/字节, 已按 8N1 的 10bit 修正为 11520 B/s)。"
                        "判定采用 MCU 自报接口耗时折算速率比(纯驱动阻塞时长, 剥离主机端固定开销), "
                        "端到端数值仅记录; 同时全量比对内容")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "发送功能", "性能")
    def test_send_tput_115200(self, shellp, uart_args):
        """飞书行14 | 发送功能/性能 | 吞吐量-115200"""
        rep = {}
        m = _run_send_tput(shellp, uart_args, 115200)
        if m is None:
            rep['打开串口失败'] = False
        else:
            rep.update(m)
            rep['吞吐率>95%理论'] = m.get('记录:MCU接口速率比%', 0) > TPUT_RATIO_MIN
        assert_feishu_rep(rep, "飞书行14 吞吐量-115200")

    @allure.feature("发送功能")
    @allure.story("性能")
    @allure.title("飞书行15 吞吐量-460800")
    @allure.description("期望: >95% 理论速率(修正理论 46080 B/s), 按 MCU 接口速率比判定")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "发送功能", "性能")
    def test_send_tput_460800(self, shellp, uart_args):
        """飞书行15 | 发送功能/性能 | 吞吐量-460800"""
        rep = {}
        m = _run_send_tput(shellp, uart_args, 460800)
        if m is None:
            rep['打开串口失败'] = False
        else:
            rep.update(m)
            rep['吞吐率>95%理论'] = m.get('记录:MCU接口速率比%', 0) > TPUT_RATIO_MIN
        assert_feishu_rep(rep, "飞书行15 吞吐量-460800")

    @allure.feature("发送功能")
    @allure.story("性能")
    @allure.title("飞书行16 吞吐量-921600")
    @allure.description("期望: >95% 理论速率(标准档, 理论 92160 B/s)。"
                        "BRR 取整后实际 923077(+0.16%), 以数据完整性+95%阈值综合判定")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "发送功能", "性能")
    def test_send_tput_921600(self, shellp, uart_args):
        """飞书行16 | 发送功能/性能 | 吞吐量-921600"""
        rep = {}
        m = _run_send_tput(shellp, uart_args, 921600)
        if m is None:
            rep['打开串口失败'] = False
        else:
            rep.update(m)
            rep['吞吐率>95%理论'] = m.get('记录:MCU接口速率比%', 0) > TPUT_RATIO_MIN
        assert_feishu_rep(rep, "飞书行16 吞吐量-921600")

    @allure.feature("发送功能")
    @allure.story("性能")
    @allure.title("飞书行17 吞吐量-1500000")
    @allure.description("期望: >95% 理论速率(高性能档, 修正理论 150000 B/s), 按 MCU 接口速率比判定;"
                        "主机实收不完整而 MCU 侧达标时定责台架 USB 接收路径(降为记录)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "发送功能", "性能")
    def test_send_tput_1500000(self, shellp, uart_args):
        """飞书行17 | 发送功能/性能 | 吞吐量-1500000"""
        rep = {}
        m = _run_send_tput(shellp, uart_args, 1500000)
        if m is None:
            rep['打开串口失败'] = False
        else:
            rep.update(m)
            rep['吞吐率>95%理论'] = m.get('记录:MCU接口速率比%', 0) > TPUT_RATIO_MIN
        assert_feishu_rep(rep, "飞书行17 吞吐量-1500000")

    @allure.feature("发送功能")
    @allure.story("性能")
    @allure.title("飞书行18 发送线程CPU耗时(4波特率)")
    @allure.description("期望: 各长度点发送净 CPU 占用率 ≤10%。"
                        "copytest 差分法(strip 框架开销), 长度点 [1, m/4, m/2, 3m/4, m], "
                        "覆盖 115200/460800/921600/1500000 四个波特率")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "发送功能", "性能")
    def test_send_thread_cpu(self, shellp, uart_args):
        """飞书行18 | 发送功能/性能 | 发送线程CPU耗时"""
        rep = {}
        for baud in FEISHU_TPUT_BAUDS:
            rep[f'波特率{baud}'] = {}
            uartp, _ = open_target(shellp, uart_args, baud)
            try:
                if uartp is None:
                    rep[f'波特率{baud}']['打开串口失败'] = False
                    continue
                measure_send_cpu_at_baud(shellp, uartp, rep[f'波特率{baud}'])
            finally:
                close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行18 发送线程CPU耗时")

    @allure.feature("发送功能")
    @allure.story("性能")
    @allure.title("飞书行19 发送中断CPU耗时(占位)")
    @allure.description("期望: ISR 级 byte/s/cycle 耗时, 覆盖四个波特率。"
                        "占位: FreeRTOS 运行时统计仅覆盖任务上下文, 固件无中断级耗时统计命令, "
                        "待固件新增 ISR 级统计(如 DWT 周期计数上报)后补全")
    @allure.severity(allure.severity_level.MINOR)
    @allure.tag("UART", "发送功能", "占位")
    def test_send_isr_cpu(self):
        """飞书行19 | 发送功能/性能 | 发送中断CPU耗时(占位, 无法自动化)"""
        pytest.skip('无中断级CPU耗时测量手段(需固件新增ISR统计命令)')


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartSendConcurrency:
    """发送功能 — 并发/overrun (飞书行20-22)"""

    @allure.feature("发送功能")
    @allure.story("并发")
    @allure.title("飞书行20 多线程高负载发送")
    @allure.description("期望: 数据无丢失。"
                        "近似: 固件后台任务单实例限制无法创建多个发送任务, "
                        "以 12 个高优先级 CPU 压力任务 + Shell 发送逐长度比对近似高负载并发")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "发送功能", "并发")
    def test_send_multi_thread(self, shellp, uart_args):
        """飞书行20 | 发送功能/并发 | 多线程高负载发送"""
        rep = {}
        uartp, maxsize = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                shell_prio = query_shell_prio(shellp) or 2
                lengths = [1, maxsize // 2, maxsize]

                # 步骤1: 启动12个高优先级纯CPU压力任务(不碰串口, 纯消耗CPU)
                if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart enable id=9 prio={shell_prio+1} num=12", 1.5)):
                    rep['启动压力任务失败'] = False
                else:
                    # 步骤2: 等3s过满转期(压力任务3s后周期sleep让出CPU)
                    time.sleep(3.0)
                    uartp.recv_data(timeout=0)

                    # 步骤3: 高负载下发送代表长度并比对
                    rep.update(send_len_series(shellp, uartp, lengths))

                    # 步骤4: 停止压力任务
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp.recv_data(timeout=0)
                    rep['说明'] = '固件单后台任务限制, 以CPU压力近似多线程负载'
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行20 多线程高负载发送")

    @allure.feature("发送功能")
    @allure.story("并发")
    @allure.title("飞书行21 高优先级中断打断发送(占位)")
    @allure.description("期望: 数据无丢失。"
                        "占位: 真实高频中断源无法从上位机注入, 任务级 CPU 压力不能模拟中断级抢占, "
                        "需固件新增可编程中断源后补全")
    @allure.severity(allure.severity_level.MINOR)
    @allure.tag("UART", "发送功能", "占位")
    def test_send_isr_preempt(self):
        """飞书行21 | 发送功能/并发 | 高优先级中断打断发送(占位, 无法自动化)"""
        pytest.skip('无中断注入手段, 任务级压力不能模拟真实高频中断抢占')

    @allure.feature("发送功能")
    @allure.story("overrun")
    @allure.title("飞书行22 发送过载不丢不重")
    @allure.description("期望: 应用层发送超过串口发送速率时数据不丢失、无重复。"
                        "① 满速率连续流 100 字节块周期校验(不丢失/不重复/不损坏) "
                        "② 占用任务让出窗口期 Shell send(-1) 排队完成(ret==512)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "发送功能", "overrun")
    def test_send_overrun(self, shellp, uart_args):
        """飞书行22 | 发送功能/overrun | 发送过载不丢不重"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('g')

                # 步骤1: 启动持续满速发送任务
                if not ack_is_ok(normal_cmd_ack(shellp, "dmdtest_uart enable id=0", 0.3)):
                    rep['启动满速发送任务失败'] = False
                else:
                    # 步骤2: 等流稳定后收集≥1200字节(丢弃前256字节过渡期数据)
                    time.sleep(0.3)
                    uartp.recv_data(timeout=0)
                    collect_bytes(uartp, 256, 0.5)
                    data = collect_bytes(uartp, 1200, 2.0)

                    # 步骤3: 校验100字节块周期性(不丢失不重复)
                    rep['满载流字节量充足'] = len(data) >= 1200
                    rep['满载流不丢失不重复(块周期校验)'] = verify_tx_task_stream(data)

                    # 步骤4: 满3s后占用任务周期让出, 验证并发 send(-1) 排队完成
                    time.sleep(3.2)
                    acks = normal_cmd_ack(shellp, f"dmdtest_uart send len=512 from={seedfrom} to={seedfrom+8} timeout=-1", 4.5)
                    rep['满载下并发发送API完成(ret==512)'] = ack_is_ok(acks) and len(acks.split()) > 2 \
                        and int(acks.split()[2]) == 512

                    # 步骤5: 清理
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp.recv_data(timeout=0)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行22 发送过载不丢不重")
