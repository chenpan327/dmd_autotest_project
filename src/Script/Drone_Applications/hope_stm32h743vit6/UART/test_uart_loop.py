# coding: utf-8
"""
===============================================================================
                            h743 UART 环路测试脚本
===============================================================================
脚本编号: DMD_TEST_H743_UART_LOOP_001
脚本版本: v1.1
创建日期: 2026-09-14
修改日期: 2026-09-17
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: hope_stm32h743vit6 公共开发板 (MCU 底软 UART 驱动)
测试类型: 底软功能验证测试
测试环境: Python 3.10, pytest, allure, 双串口 (Shell 口 + 数据口)

测试目的:
验证 h743 板 MCU 底软 UART 驱动经固件回环任务的环路时延与数据完整性
(飞书行49-50, 共 2 个测试点)。环路时间: 回环任务运行中逐轮 1 字节往返计时,
判定均值 < 50ms (实测含 USB 串口适配器时延 1~10ms, 绝对值仅作参考);
数据完整性: 256~65536 九档长度回环全量比对, 覆盖单DMA块/块边界/
StreamBuffer容量/满载压力边界。

前置条件:
1. 测试环境准备:
   - h743 开发板已运行 ll_drivers_tester 测试固件, Shell 口已接测试主机
     (串口号/波特率见 config.json hope_stm32h743vit6 段 port1/baud1)
   - 被测 UART TX/RX 与主机数据口交叉直连 (串口号见 config 段 port2)
   - conftest 板段配置 fail-fast 校验通过, shellp / uart_args fixture 已就绪
2. 判定语义: 判定字典 rep 中任一值为 False 即该测试点失败, "记录:" 前缀键
   仅作记录, 逐点判定明细挂 Allure 附件
3. 并行约束: 单一 Shell 串口物理独占, 严禁 pytest-xdist / 多进程并行
原理详见: mcu_ll_drivers_tester/ll_drivers_tester_host/doc/uart_test_principle.md 第 7 章

测试步骤:
1. [飞书行49 test_loop_time] 环路时间:
   (1) dmdtest_uart open 打开会话, dmdtest_uart enable id=2 启动回环任务
   (2) 20 轮 1 字节往返计时 (发送 1 字节至收到回环字节)
   (3) 统计 min/avg/max 并判定, dmdtest_uart disable 停止回环任务
2. [飞书行50 test_loop_integrity] 数据完整性:
   (1) 启动回环任务
   (2) 256/512/1024/2048/4096/8192/16384/32768/65536 九档长度逐档发送并
       限时收满, 全量比对 (每档递增起始字符防残留数据"碰巧"通过)
   (3) 停止回环任务

预期结果（与测试步骤一一对应）:
1. [行49] 20 轮全部计时成功, 平均环路时间 <50ms (含 USB 适配器时延, 绝对值参考)
2. [行50] 九档长度回环数据全部一致 (回环通路无丢失/无重复/无错位)

===============================================================================
测试结论:
环路 2 个测试点全部实现自动化, 判定结果与逐点明细见 Allure 报告各用例的
「判定明细」「串口收发流水」附件。
===============================================================================
"""
import time

import allure

from src.Protocol.dmdtest_uart import (
    OrderAry,
    LOOP_RTT_MAX_MS,
    normal_cmd_ack,
    ack_is_ok,
    collect_bytes,
    open_target,
    close_target,
)
from utils.assert_helper import assert_feishu_rep


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartLoop:
    """环路测试 (飞书行49-50)"""

    @allure.feature("环路测试")
    @allure.story("环路时间")
    @allure.title("飞书行49 环路时间")
    @allure.description("期望: 环路往返时延达标(20 轮 1 字节往返计时, 均值 < 50ms)。"
                        "实测含 USB 串口适配器时延(典型 1~10ms), 绝对值仅作参考")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "环路测试")
    def test_loop_time(self, shellp, uart_args):
        """飞书行49 | 环路测试 | 环路时间"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                # 步骤1: 启动回环任务
                if not ack_is_ok(normal_cmd_ack(shellp, "dmdtest_uart enable id=2", 0.3)):
                    rep['启动回环任务失败'] = False
                else:
                    # 步骤2: 20轮 1 字节往返计时
                    lat = []
                    for i in range(20):
                        c = bytes([ord('A') + (i % 26)])
                        uartp.recv_data(timeout=0)
                        t0 = time.perf_counter()
                        uartp.send_data(c)
                        rdata = None
                        while time.perf_counter() - t0 < 0.5:
                            rdata = uartp.recv_data(timeout=0.05)
                            if rdata:
                                break
                        if rdata:
                            lat.append((time.perf_counter() - t0) * 1000)
                        time.sleep(0.02)

                    # 步骤3: 统计与判定
                    rep['计时成功轮数==20'] = (len(lat) == 20)
                    if lat:
                        rep['记录:环路时间min(ms)'] = round(min(lat), 3)
                        rep['记录:环路时间avg(ms)'] = round(sum(lat) / len(lat), 3)
                        rep['记录:环路时间max(ms)'] = round(max(lat), 3)
                        rep[f'平均环路时间<{LOOP_RTT_MAX_MS}ms'] = (sum(lat) / len(lat)) < LOOP_RTT_MAX_MS

                    # 步骤4: 停止回环任务
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp.recv_data(timeout=0)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行49 环路时间")

    @allure.feature("环路测试")
    @allure.story("数据完整性")
    @allure.title("飞书行50 数据完整性")
    @allure.description("期望: 回环数据无损。"
                        "256~65536 九档长度回环比对, 覆盖单DMA块/块边界/StreamBuffer容量/满载压力各边界")
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("UART", "环路测试")
    def test_loop_integrity(self, shellp, uart_args):
        """飞书行50 | 环路测试 | 数据完整性"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('v')

                # 步骤1: 启动回环任务
                if not ack_is_ok(normal_cmd_ack(shellp, "dmdtest_uart enable id=2", 0.3)):
                    rep['启动回环任务失败'] = False
                else:
                    # 步骤2: 九档长度全量比对
                    for n in [256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]:
                        rep[f'回环{n}字节一致'] = False
                        uartp.recv_data(timeout=0)
                        sdata = OrderAry(n, seedfrom, seedfrom + 8).to_bytes()
                        if uartp.send_data(sdata) < 0:
                            continue
                        rdata = collect_bytes(uartp, n, n * 10 / uartp.baudrate * 2 + 0.5)
                        if rdata == sdata:
                            rep[f'回环{n}字节一致'] = True
                        seedfrom = (seedfrom + 1) if seedfrom < ord('Z') else ord(' ')

                    # 步骤3: 停止回环任务
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp.recv_data(timeout=0)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行50 数据完整性")
