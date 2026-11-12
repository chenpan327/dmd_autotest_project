# coding: utf-8
"""
===============================================================================
                            h743 UART 接收功能测试脚本
===============================================================================
脚本编号: DMD_TEST_H743_UART_RECV_001
脚本版本: v1.1
创建日期: 2026-09-14
修改日期: 2026-09-17
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: hope_stm32h743vit6 公共开发板 (MCU 底软 UART 驱动)
测试类型: 底软功能验证测试
测试环境: Python 3.10, pytest, allure, 双串口 (Shell 口 + 数据口)

测试目的:
验证 h743 板 MCU 底软 UART 驱动接收功能的完整性与正确性, 覆盖通路/边界/
特殊数据(飞书行23-27)、超时语义(行28-33)、性能-吞吐量与线程CPU(行34-39)、
并发/overrun(行40-41), 共 19 个测试点。与发送侧镜像, 方向相反:
命令先发 → MCU 阻塞接收 → 主机后送数据 → 固件内 memcmp → 上位机看应答 ret==len。

前置条件:
1. 测试环境准备:
   - h743 开发板已运行 ll_drivers_tester 测试固件, Shell 口已接测试主机
     (串口号/波特率见 config.json hope_stm32h743vit6 段 port1/baud1)
   - 被测 UART RX 与主机数据口 TX 相连 (数据口串口号见 config 段 port2)
   - conftest 板段配置 fail-fast 校验通过, shellp / uart_args fixture 已就绪
2. 判定语义: 判定字典 rep 中任一值为 False 即该测试点失败, "记录:" 前缀键
   仅作记录, 逐点判定明细挂 Allure 附件
3. 并行约束: 单一 Shell 串口物理独占, 严禁 pytest-xdist / 多进程并行
原理详见: mcu_ll_drivers_tester/ll_drivers_tester_host/doc/uart_test_principle.md 第 5 章

测试步骤:
1. [飞书行23 test_recv_data_range] 接收数据 1~buf 遍历:
   (1) dmdtest_uart open 打开被测串口会话 (maxsize=DMA 单块上限)
   (2) 遍历长度 1~maxsize: 下发 recv 命令 → 主机送数据 → 校验应答 ret==len
2. [飞书行24 test_recv_one_byte] 1 字节数据: MCU 阻塞接收 1 字节, 主机发送并校验
3. [飞书行25 test_recv_buf_len] buf 长度数据: MCU 阻塞接收 maxsize 字节并校验
4. [飞书行26 test_recv_long_8x] 长数据(8倍buf): MCU 阻塞接收 8×maxsize 字节,
   固件内整包 memcmp
5. [飞书行27 test_recv_same_bytes] 相同字节遍历: 0x00~0xFF 每值接收 maxsize 个
   相同字节并固件内比对
6. [飞书行28 test_recv_to0_hasdata] timeout=0 缓冲区有数据: 主机先发 8 字节沉入
   驱动缓冲, 再下发 timeout=0 接收命令
7. [飞书行29 test_recv_to0_nodata] timeout=0 缓冲区无数据: 清缓冲后 timeout=0 接收
8. [飞书行30 test_recv_toneg_late_data] timeout<0 数据 5s 后到达: MCU 进入
   timeout=-1 接收, 静默 5.5s 后补发 8 字节
9. [飞书行31 test_recv_toneg_hasdata] timeout<0 缓冲区已有数据: 数据先沉缓冲,
   再 timeout=-1 接收
10. [飞书行32 test_recv_topos_nodata] timeout>0 窗口内无数据: timeout=200 接收,
    线上保持无数据
11. [飞书行33 test_recv_topos_hasdata] timeout>0 窗口内有数据: timeout=1000 接收,
    主机 0.1s 后送达 8 字节
12. [飞书行34-37 test_recv_tput_*] 吞吐量四波特率: 115200/460800/921600/1500000
    逐档 MCU 阻塞接收约 0.5s 传输量, 取应答接口耗时(扣除 50ms 命令启动时延)
    折算吞吐率
13. [飞书行38 test_recv_thread_cpu] 接收线程 CPU: copytest 差分+3 次取中位数,
    长度点 [1, m/4, m/2, 3m/4, m] 覆盖四个波特率
14. [飞书行39 test_recv_isr_cpu] 接收中断 CPU (占位): 无法自动化
15. [飞书行40 test_recv_isr_dma_preempt] 中断打断接收/DMA (占位): 无法自动化
16. [飞书行41 test_recv_overrun] 接收过载行为探测: MCU 停读 + 主机满速灌 8KB,
    记录错误计数增量与 recv 返回形态, 再验证恢复能力与后续新数据接收

预期结果（与测试步骤一一对应）:
1. [行23] 各长度应答 ret==len (固件内 memcmp 一致, 数据无丢失)
2. [行24] 应答 OK 且 ret==1
3. [行25] 应答 OK 且 ret==maxsize
4. [行26] 应答 OK 且 ret==8×buf (跨 DMA 块流式接收无丢失)
5. [行27] 全部 256 个字节值接收成功且一致 (8bit 透明通道)
6. [行28] 立即命中缓冲返回接收成功 (ret==8)
7. [行29] 返回接收失败 (NG 且 ret==0)
8. [行30] 数据到达后返回成功 (ret==8) 且耗时 >5000ms (证明 -1 不中途超时)
9. [行31] 立即命中返回接收成功 (ret==8)
10. [行32] 按期超时返回失败 (NG ret==0) 且耗时 ∈[190,600]ms (tick 粒度容差)
11. [行33] 窗口内收满返回成功 (ret==8) 且耗时 <1000ms
12. [行34-37] 各档折算速率比 >95% (10bit/字节修正理论值)
13. [行38] 各长度点接收净 CPU 占用率 ≤0.5%
14. [行39] skip (固件无中断级耗时统计命令)
15. [行40] skip (中断级打断/DMA 抢占无法注入)
16. [行41] 溢出后双向收发恢复且后续新数据接收正常 (ORE/FE/PE 增量与
    rx_bytes 增量仅记录)

===============================================================================
测试结论:
接收功能 19 个测试点全部实现自动化 (中断类占位点显式 skip 并注明原因),
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
    normal_recv_data_to_ack,
    open_target,
    close_target,
    recv_len_series,
    measure_recv_tput,
    measure_recv_cpu_at_baud,
    overflow_probe,
)
from utils.assert_helper import assert_feishu_rep


def _run_recv_tput(shellp, uart_args, baud):
    """接收吞吐量公共流程: 以指定波特率打开会话并测量

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uart_args: 配置命名空间(uartx=被测 UART 编号, port2=主机数据口 COM 号)
        baud: 目标波特率(bps)

    Returns:
        dict: measure_recv_tput 测量/判定字典; 会话打开失败返回 None
    """
    uartp, _ = open_target(shellp, uart_args, baud)
    if uartp is None:
        return None
    try:
        return measure_recv_tput(shellp, uartp, ord('q'))
    finally:
        close_target(shellp, uartp)


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartRecvPath:
    """接收功能 — 通路/边界/特殊数据 (飞书行23-27)"""

    @allure.feature("接收功能")
    @allure.story("通路")
    @allure.title("飞书行23 接收数据(1~buf遍历)")
    @allure.description("期望: 数据和发送端数据一致。"
                        "遍历 1~DMA单块上限 每个长度值, MCU 固件内 memcmp 比对, 上位机看 ret==len")
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("UART", "接收功能")
    def test_recv_data_range(self, shellp, uart_args):
        """飞书行23 | 接收功能/通路 | 接收数据"""
        rep = {}
        uartp, maxsize = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                rep.update(recv_len_series(shellp, uartp, list(range(1, maxsize + 1))))
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行23 接收数据(1~buf遍历)")

    @allure.feature("接收功能")
    @allure.story("边界")
    @allure.title("飞书行24 1字节数据")
    @allure.description("期望: 正常接收, 并且和发送端一致")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "接收功能")
    def test_recv_one_byte(self, shellp, uart_args):
        """飞书行24 | 接收功能/边界 | 1字节数据"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('h')

                # 步骤1: MCU 进入接收, 主机发 1 字节
                uartp.recv_data(timeout=0)
                cmd = f"dmdtest_uart recv len=1 from={seedfrom} to={seedfrom+8} timeout=1000"
                shellp.send_text(cmd + '\r\n')
                time.sleep(0.05)
                uartp.send_data(OrderAry(1, seedfrom, seedfrom + 8).to_bytes())
                time.sleep(0.15)

                # 步骤2: 固件内比对结果
                acks = normal_recv_data_to_ack(shellp, cmd, 1.0)
                rep['1字节接收成功且一致'] = ack_is_ok(acks) and len(acks.split()) > 2 \
                    and int(acks.split()[2]) == 1
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行24 1字节数据")

    @allure.feature("接收功能")
    @allure.story("边界")
    @allure.title("飞书行25 buf长度数据")
    @allure.description("期望: 正常接收, 并且和发送端一致")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "接收功能")
    def test_recv_buf_len(self, shellp, uart_args):
        """飞书行25 | 接收功能/边界 | buf长度数据"""
        rep = {}
        uartp, maxsize = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('i')

                # 步骤1: MCU 阻塞接收 maxsize 字节, 主机发送同长度数据
                uartp.recv_data(timeout=0)
                cmd = f"dmdtest_uart recv len={maxsize} from={seedfrom} to={seedfrom+8} timeout=1000"
                shellp.send_text(cmd + '\r\n')
                time.sleep(0.05)
                uartp.send_data(OrderAry(maxsize, seedfrom, seedfrom + 8).to_bytes())
                time.sleep(0.1 + maxsize * 10 / uartp.baudrate)

                # 步骤2: 校验
                acks = normal_recv_data_to_ack(shellp, cmd, 2.0)
                rep['buf长度接收成功且一致'] = ack_is_ok(acks) and len(acks.split()) > 2 \
                    and int(acks.split()[2]) == maxsize
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行25 buf长度数据")

    @allure.feature("接收功能")
    @allure.story("边界")
    @allure.title("飞书行26 长数据(8倍buf)")
    @allure.description("期望: 数据无丢失。单次接收 8×maxsize 字节整包比对(跨多个 DMA 块的流式接收)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "接收功能")
    def test_recv_long_8x(self, shellp, uart_args):
        """飞书行26 | 接收功能/边界 | 长数据(8倍buf)"""
        rep = {}
        uartp, maxsize = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                n = maxsize * 8
                seedfrom = ord('j')

                # 步骤1: MCU 阻塞接收 8×buf 字节(超时3s)
                uartp.recv_data(timeout=0)
                cmd = f"dmdtest_uart recv len={n} from={seedfrom} to={seedfrom+8} timeout=3000"
                shellp.send_text(cmd + '\r\n')
                time.sleep(0.05)
                uartp.send_data(OrderAry(n, seedfrom, seedfrom + 8).to_bytes())
                time.sleep(0.2 + n * 10 / uartp.baudrate)

                # 步骤2: 固件内整包 memcmp
                acks = normal_recv_data_to_ack(shellp, cmd, 3.0)
                rep['长数据接收成功且一致(跨DMA块)'] = ack_is_ok(acks) and len(acks.split()) > 2 \
                    and int(acks.split()[2]) == n
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行26 长数据(8倍buf)")

    @allure.feature("接收功能")
    @allure.story("特殊数据")
    @allure.title("飞书行27 相同字节遍历0-0xFF")
    @allure.description("期望: 遍历 0x00~0xFF 全部字节值, 每值接收 maxsize 个相同字节并固件内比对, "
                        "数据无丢失且一致")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "接收功能")
    def test_recv_same_bytes(self, shellp, uart_args):
        """飞书行27 | 接收功能/特殊数据 | 相同字节遍历0-0xFF"""
        rep = {}
        uartp, maxsize = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                for v in range(0, 256):
                    rep[f'相同字节0x{v:02X}×{maxsize}接收一致'] = False

                    # 步骤1: MCU 接收 maxsize 个相同字节 v
                    uartp.recv_data(timeout=0)
                    cmd = f"dmdtest_uart recv len={maxsize} from={v} to={v} timeout=1000"
                    shellp.send_text(cmd + '\r\n')
                    time.sleep(0.03)

                    # 步骤2: 主机发送 maxsize 个字节 v
                    uartp.send_data(bytes([v]) * maxsize)
                    time.sleep(0.1 + maxsize * 10 / uartp.baudrate)

                    # 步骤3: 校验
                    acks = normal_recv_data_to_ack(shellp, cmd, 2.0)
                    if ack_is_ok(acks):
                        rep[f'相同字节0x{v:02X}×{maxsize}接收一致'] = True
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行27 相同字节遍历0-0xFF")


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartRecvTimeout:
    """接收功能 — 超时语义 (飞书行28-33)

    无需后台任务竞争即可覆盖全部六种语义分支:
    数据先沉缓冲/缓冲空/晚到数据三类时序 × timeout 0/-1/>0。
    """

    @allure.feature("接收功能")
    @allure.story("超时")
    @allure.title("飞书行28 timeout=0 缓冲区有数据")
    @allure.description("期望: 返回接收成功(立即从缓冲命中)。主机先发数据沉入驱动缓冲, 再下发 timeout=0 接收命令")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "接收功能", "超时")
    def test_recv_to0_hasdata(self, shellp, uart_args):
        """飞书行28 | 接收功能/超时 | timeout=0缓冲区有数据"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('k')

                # 步骤1: 数据先到 —— 发 8 字节沉入驱动缓冲
                uartp.recv_data(timeout=0)
                uartp.send_data(OrderAry(8, seedfrom, seedfrom + 8).to_bytes())
                time.sleep(0.05)

                # 步骤2: timeout=0 接收, 应立即命中缓冲返回成功
                acks = normal_cmd_ack(shellp, f"dmdtest_uart recv len=8 from={seedfrom} to={seedfrom+8} timeout=0", 0.3)
                rep['缓冲有数据timeout=0接收成功'] = ack_is_ok(acks) and len(acks.split()) > 2 \
                    and int(acks.split()[2]) == 8
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行28 timeout=0缓冲区有数据")

    @allure.feature("接收功能")
    @allure.story("超时")
    @allure.title("飞书行29 timeout=0 缓冲区无数据")
    @allure.description("期望: 返回接收失败(立即超时 NG, ret==0)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "接收功能", "超时")
    def test_recv_to0_nodata(self, shellp, uart_args):
        """飞书行29 | 接收功能/超时 | timeout=0缓冲区无数据"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('l')

                # 步骤1: 确保缓冲无数据
                uartp.recv_data(timeout=0)

                # 步骤2: timeout=0 接收, 期望 NG ret==0
                acks = normal_cmd_ack(shellp, f"dmdtest_uart recv len=8 from={seedfrom} to={seedfrom+8} timeout=0", 0.3)
                rep['缓冲无数据timeout=0接收失败'] = (not ack_is_ok(acks))
                if not ack_is_ok(acks) and len(acks.split()) > 2:
                    rep['返回ret==0'] = int(acks.split()[2]) == 0
                else:
                    rep['返回ret==0'] = False
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行29 timeout=0缓冲区无数据")

    @allure.feature("接收功能")
    @allure.story("超时")
    @allure.title("飞书行30 timeout<0 数据5s后到达")
    @allure.description("期望: 持续等待, 5s 后数据到达返回接收成功(ret==8 且耗时>5s, 证明 -1 不中途超时)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "接收功能", "超时")
    def test_recv_toneg_late_data(self, shellp, uart_args):
        """飞书行30 | 接收功能/超时 | timeout<0数据5s后到达"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('m')

                # 步骤1: MCU 进入 timeout=-1 永久等待接收
                uartp.recv_data(timeout=0)
                cmd = f"dmdtest_uart recv len=8 from={seedfrom} to={seedfrom+8} timeout=-1"
                shellp.send_text(cmd + '\r\n')

                # 步骤2: 静默 5.5s(期间无数据, 验证不中途超时)
                time.sleep(5.5)

                # 步骤3: 补发 8 字节正常数据, recv 应立即收满返回
                uartp.send_data(OrderAry(8, seedfrom, seedfrom + 8).to_bytes())
                time.sleep(0.3)

                # 步骤4: 校验 ret==8 且耗时>5s
                acks = normal_recv_data_to_ack(shellp, cmd, 2.0)
                rep['5s后数据接收成功'] = False
                rep['持续等待耗时>5000ms'] = False
                if ack_is_ok(acks):
                    ary = acks.split()
                    if len(ary) > 4:
                        rep['5s后数据接收成功'] = (int(ary[2]) == 8)
                        rep['持续等待耗时>5000ms'] = (int(ary[2]) == 8 and float(ary[3][:-2]) > 5000)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行30 timeout<0数据5s后到达")

    @allure.feature("接收功能")
    @allure.story("超时")
    @allure.title("飞书行31 timeout<0 缓冲区已有数据")
    @allure.description("期望: 返回接收成功(数据已在缓冲, 立即命中)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "接收功能", "超时")
    def test_recv_toneg_hasdata(self, shellp, uart_args):
        """飞书行31 | 接收功能/超时 | timeout<0缓冲区已有数据"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('n')

                # 步骤1: 数据先到沉入缓冲
                uartp.recv_data(timeout=0)
                uartp.send_data(OrderAry(8, seedfrom, seedfrom + 8).to_bytes())
                time.sleep(0.05)

                # 步骤2: timeout=-1 接收应立即成功
                acks = normal_cmd_ack(shellp, f"dmdtest_uart recv len=8 from={seedfrom} to={seedfrom+8} timeout=-1", 0.3)
                rep['缓冲有数据timeout=-1接收成功'] = ack_is_ok(acks) and len(acks.split()) > 2 \
                    and int(acks.split()[2]) == 8
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行31 timeout<0缓冲区已有数据")

    @allure.feature("接收功能")
    @allure.story("超时")
    @allure.title("飞书行32 timeout>0 窗口内无数据")
    @allure.description("期望: 持续等待 timeout 后返回接收失败(NG ret==0, 耗时∈[190,600]ms tick 粒度容差)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "接收功能", "超时")
    def test_recv_topos_nodata(self, shellp, uart_args):
        """飞书行32 | 接收功能/超时 | timeout>0窗口内无数据"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('o')

                # 步骤1: 缓冲无数据, timeout=200 接收
                uartp.recv_data(timeout=0)
                acks = normal_cmd_ack(shellp, f"dmdtest_uart recv len=8 from={seedfrom} to={seedfrom+8} timeout=200", 0.6)

                # 步骤2: 期望 NG ret==0, 耗时落在 [190, 600]ms(tick粒度容差)
                rep['窗口内无数据按期超时'] = False
                rep['超时耗时∈[190,600]ms'] = False
                if not ack_is_ok(acks):
                    ary = acks.split()
                    if len(ary) > 4:
                        ms = float(ary[3][:-2])
                        rep['窗口内无数据按期超时'] = (int(ary[2]) == 0)
                        rep['超时耗时∈[190,600]ms'] = (int(ary[2]) == 0 and 190 < ms < 600)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行32 timeout>0窗口内无数据")

    @allure.feature("接收功能")
    @allure.story("超时")
    @allure.title("飞书行33 timeout>0 窗口内有数据")
    @allure.description("期望: 返回接收成功(窗口内收满, ret==8 且耗时<1000ms)。"
                        "timeout=1000 接收, 主机 0.1s 后发数据")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "接收功能", "超时")
    def test_recv_topos_hasdata(self, shellp, uart_args):
        """飞书行33 | 接收功能/超时 | timeout>0窗口内有数据"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('p')

                # 步骤1: MCU 进入 timeout=1000 接收
                uartp.recv_data(timeout=0)
                cmd = f"dmdtest_uart recv len=8 from={seedfrom} to={seedfrom+8} timeout=1000"
                shellp.send_text(cmd + '\r\n')

                # 步骤2: 窗口内(0.1s)送达数据
                time.sleep(0.1)
                uartp.send_data(OrderAry(8, seedfrom, seedfrom + 8).to_bytes())
                time.sleep(0.2)

                # 步骤3: 校验成功且耗时<1000ms
                acks = normal_recv_data_to_ack(shellp, cmd, 2.0)
                rep['窗口内数据接收成功'] = False
                rep['窗口内完成(耗时<1000ms)'] = False
                if ack_is_ok(acks):
                    ary = acks.split()
                    if len(ary) > 4:
                        rep['窗口内数据接收成功'] = (int(ary[2]) == 8)
                        rep['窗口内完成(耗时<1000ms)'] = (int(ary[2]) == 8 and float(ary[3][:-2]) < 1000)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行33 timeout>0窗口内有数据")


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartRecvPerf:
    """接收功能 — 性能: 吞吐量与线程 CPU (飞书行34-39)"""

    @allure.feature("接收功能")
    @allure.story("性能")
    @allure.title("飞书行34 吞吐量-115200")
    @allure.description("期望: >95% 理论速率(修正理论 11520 B/s)。"
                        "MCU 阻塞接收约 0.5s 传输量, 取应答接口耗时(扣除 50ms 命令时延)折算")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "接收功能", "性能")
    def test_recv_tput_115200(self, shellp, uart_args):
        """飞书行34 | 接收功能/性能 | 吞吐量-115200"""
        rep = {}
        m = _run_recv_tput(shellp, uart_args, 115200)
        if m is None:
            rep['打开串口失败'] = False
        else:
            rep.update(m)
            rep['吞吐率>95%理论'] = m.get('记录:速率比%', 0) > TPUT_RATIO_MIN
        assert_feishu_rep(rep, "飞书行34 吞吐量-115200")

    @allure.feature("接收功能")
    @allure.story("性能")
    @allure.title("飞书行35 吞吐量-460800")
    @allure.description("期望: >95% 理论速率(修正理论 46080 B/s)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "接收功能", "性能")
    def test_recv_tput_460800(self, shellp, uart_args):
        """飞书行35 | 接收功能/性能 | 吞吐量-460800"""
        rep = {}
        m = _run_recv_tput(shellp, uart_args, 460800)
        if m is None:
            rep['打开串口失败'] = False
        else:
            rep.update(m)
            rep['吞吐率>95%理论'] = m.get('记录:速率比%', 0) > TPUT_RATIO_MIN
        assert_feishu_rep(rep, "飞书行35 吞吐量-460800")

    @allure.feature("接收功能")
    @allure.story("性能")
    @allure.title("飞书行36 吞吐量-921600")
    @allure.description("期望: >95% 理论速率(标准档, 理论 92160 B/s; BRR 取整实际 923077(+0.16%), "
                        "偏差超限时数据比对/应答失败, 综合判定)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "接收功能", "性能")
    def test_recv_tput_921600(self, shellp, uart_args):
        """飞书行36 | 接收功能/性能 | 吞吐量-921600"""
        rep = {}
        m = _run_recv_tput(shellp, uart_args, 921600)
        if m is None:
            rep['打开串口失败'] = False
        else:
            rep.update(m)
            rep['吞吐率>95%理论'] = m.get('记录:速率比%', 0) > TPUT_RATIO_MIN
        assert_feishu_rep(rep, "飞书行36 吞吐量-921600")

    @allure.feature("接收功能")
    @allure.story("性能")
    @allure.title("飞书行37 吞吐量-1500000")
    @allure.description("期望: >95% 理论速率(高性能档, 修正理论 150000 B/s)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "接收功能", "性能")
    def test_recv_tput_1500000(self, shellp, uart_args):
        """飞书行37 | 接收功能/性能 | 吞吐量-1500000"""
        rep = {}
        m = _run_recv_tput(shellp, uart_args, 1500000)
        if m is None:
            rep['打开串口失败'] = False
        else:
            rep.update(m)
            rep['吞吐率>95%理论'] = m.get('记录:速率比%', 0) > TPUT_RATIO_MIN
        assert_feishu_rep(rep, "飞书行37 吞吐量-1500000")

    @allure.feature("接收功能")
    @allure.story("性能")
    @allure.title("飞书行38 接收线程CPU耗时(4波特率)")
    @allure.description("期望: 各长度点接收净 CPU 占用率 ≤0.5%。"
                        "差分+3次取中位数(strip 噪声), 长度点 [1, m/4, m/2, 3m/4, m], "
                        "覆盖四个波特率")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "接收功能", "性能")
    def test_recv_thread_cpu(self, shellp, uart_args):
        """飞书行38 | 接收功能/性能 | 接收线程CPU耗时"""
        rep = {}
        for baud in FEISHU_TPUT_BAUDS:
            rep[f'波特率{baud}'] = {}
            uartp, _ = open_target(shellp, uart_args, baud)
            try:
                if uartp is None:
                    rep[f'波特率{baud}']['打开串口失败'] = False
                    continue
                measure_recv_cpu_at_baud(shellp, uartp, rep[f'波特率{baud}'])
            finally:
                close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行38 接收线程CPU耗时")

    @allure.feature("接收功能")
    @allure.story("性能")
    @allure.title("飞书行39 接收中断CPU耗时(占位)")
    @allure.description("占位: 同发送侧行19 —— FreeRTOS 运行时统计仅覆盖任务上下文, "
                        "DMA/ISR 级耗时无统计命令, 无法自动化")
    @allure.severity(allure.severity_level.MINOR)
    @allure.tag("UART", "接收功能", "占位")
    def test_recv_isr_cpu(self):
        """飞书行39 | 接收功能/性能 | 接收中断CPU耗时(占位, 无法自动化)"""
        pytest.skip('无中断级CPU耗时测量手段(需固件新增ISR统计命令)')


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartRecvConcurrency:
    """接收功能 — 并发/overrun (飞书行40-41)"""

    @allure.feature("接收功能")
    @allure.story("并发")
    @allure.title("飞书行40 中断打断接收/DMA(占位)")
    @allure.description("期望: 接收数据无丢失, 覆盖四个波特率。"
                        "占位: 中断级打断/DMA 抢占无法从上位机注入(需可编程高频中断源)")
    @allure.severity(allure.severity_level.MINOR)
    @allure.tag("UART", "接收功能", "占位")
    def test_recv_isr_dma_preempt(self):
        """飞书行40 | 接收功能/并发 | 中断打断接收/DMA(占位, 无法自动化)"""
        pytest.skip('中断级打断/DMA抢占无法注入, 无高频中断源控制手段')

    @allure.feature("接收功能")
    @allure.story("overrun")
    @allure.title("飞书行41 接收过载行为探测")
    @allure.description("期望: rx速率>线程接收速率时保留缓冲数据、丢失新数据。"
                        "探测: MCU 停读 + 主机满速连灌 8KB, 记录错误计数增量与 recv 返回形态, "
                        "以恢复能力+后续新数据正常为主要判定(缓冲策略语义无法从主机断言)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "接收功能", "overrun")
    def test_recv_overrun(self, shellp, uart_args):
        """飞书行41 | 接收功能/overrun | 接收过载行为探测"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                rep.update(overflow_probe(shellp, uartp, ord('r')))
                rep['说明'] = '缓冲保留/覆盖策略语义无法从主机断言, 已记录计数增量与recv形态, 以恢复判定'
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行41 接收过载行为探测")
