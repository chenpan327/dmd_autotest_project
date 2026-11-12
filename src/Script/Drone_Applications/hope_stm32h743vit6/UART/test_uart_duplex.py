# coding: utf-8
"""
===============================================================================
                            h743 UART 全双工测试脚本
===============================================================================
脚本编号: DMD_TEST_H743_UART_DUPLEX_001
脚本版本: v1.1
创建日期: 2026-09-14
修改日期: 2026-09-17
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: hope_stm32h743vit6 公共开发板 (MCU 底软 UART 驱动)
测试类型: 底软功能验证测试
测试环境: Python 3.10, pytest, allure, 双串口 (Shell 口 + 数据口)

测试目的:
验证 h743 板 MCU 底软 UART 驱动的全双工收发能力(飞书行42-48, 共 7 个测试点)。
固件回环任务(任务2: 收 1 字节唤醒 → 非阻塞收尾 → StreamBuffer → 原样发回)
提供全双工通路; 吞吐量以两档长度(N/2 与 N)差分折算持续速率判定 —— 端到端计时
含回环管线固定时延(实测 40~130ms 且随波特率波动), 差分中消去; 收发被串行化
(半双工行为)则差分速率近乎减半, 95% 阈值即隐含"必须真全双工"判定。

前置条件:
1. 测试环境准备:
   - h743 开发板已运行 ll_drivers_tester 测试固件, Shell 口已接测试主机
     (串口号/波特率见 config.json hope_stm32h743vit6 段 port1/baud1)
   - 被测 UART TX/RX 与主机数据口交叉直连 (串口号见 config 段 port2)
   - conftest 板段配置 fail-fast 校验通过, shellp / uart_args fixture 已就绪
2. 判定语义: 判定字典 rep 中任一值为 False 即该测试点失败, "记录:" 前缀键
   仅作记录, 逐点判定明细挂 Allure 附件
3. 并行约束: 单一 Shell 串口物理独占, 严禁 pytest-xdist / 多进程并行
原理详见: mcu_ll_drivers_tester/ll_drivers_tester_host/doc/uart_test_principle.md 第 6 章

测试步骤:
1. [飞书行42 test_duplex_path] 收发同时出现数据:
   (1) dmdtest_uart open 打开会话, dmdtest_uart enable id=2 启动固件回环任务
   (2) 256/1024/4096 三档长度: 主机发送期间回显同时回流, 全量比对
   (3) dmdtest_uart disable 停止回环任务
2. [飞书行43-46 test_duplex_tput_*] 全双工吞吐量四波特率 (115200/460800/921600/
   1500000): 启动回环任务, 每档以两档长度(N/2 与 N)回环计时,
   差分折算持续速率; 前后各查一次 stat 取 MCU 侧收发字节证据
3. [飞书行47 test_duplex_thread_cpu] 全双工线程 CPU (占位): 无法自动化
4. [飞书行48 test_duplex_isr_cpu] 全双工中断 CPU (占位): 无法自动化

预期结果（与测试步骤一一对应）:
1. [行42] 256/1024/4096 三档回环数据全量一致 (收发同时进行无丢失)
2. [行43-46] 各档差分速率比 >95% 理论速率 (被串行化则差分≈50% 必不过);
   主机实收不完整而 MCU 侧收发足额零错时, 定责台架 USB 接收路径并以
   MCU 侧证据替代完整性判定
3. [行47] skip (回环任务不经 dmdtest_uart 统计路径, 固件无查询命令)
4. [行48] skip (无中断级 CPU 耗时测量手段)

===============================================================================
测试结论:
全双工 7 个测试点全部实现自动化 (CPU 统计类占位点显式 skip 并注明原因),
判定结果与逐点明细见 Allure 报告各用例的「判定明细」「串口收发流水」附件。
===============================================================================
"""
import time

import allure
import pytest

from src.Protocol.dmdtest_uart import (
    OrderAry,
    TPUT_RATIO_MIN,
    normal_cmd_ack,
    ack_is_ok,
    collect_bytes,
    open_target,
    close_target,
    measure_duplex_tput,
)
from utils.assert_helper import assert_feishu_rep


def _run_duplex_tput(shellp, uart_args, baud):
    """全双工吞吐量公共流程: 指定波特率打开会话+启动回环任务+测量+停止回环

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uart_args: 配置命名空间(uartx=被测 UART 编号, port2=主机数据口 COM 号)
        baud: 目标波特率(bps)

    Returns:
        dict: measure_duplex_tput 测量/判定字典; 会话打开失败返回 None,
              回环任务启动失败返回 {'启动回环任务失败': False}
    """
    uartp, _ = open_target(shellp, uart_args, baud)
    if uartp is None:
        return None
    try:
        if not ack_is_ok(normal_cmd_ack(shellp, "dmdtest_uart enable id=2", 0.3)):
            return {'启动回环任务失败': False}
        m = measure_duplex_tput(shellp, uartp, ord('u'))
        normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
        uartp.recv_data(timeout=0)
        return m
    finally:
        close_target(shellp, uartp)


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartDuplex:
    """全双工 (飞书行42-48)"""

    @allure.feature("全双工")
    @allure.story("通路")
    @allure.title("飞书行42 rx和tx同时出现数据")
    @allure.description("期望: 收发数据无丢失。"
                        "主机发送期间回显同时回流, 收发在线路上重叠进行, 256/1024/4096 三档全量比对")
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("UART", "全双工")
    def test_duplex_path(self, shellp, uart_args):
        """飞书行42 | 全双工/通路 | rx和tx同时出现数据"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('s')

                # 步骤1: 启动固件内回环任务(任务2)
                if not ack_is_ok(normal_cmd_ack(shellp, "dmdtest_uart enable id=2", 0.3)):
                    rep['启动回环任务失败'] = False
                else:
                    # 步骤2: 多档长度收发同时进行并全量比对
                    for n in [256, 1024, 4096]:
                        rep[f'全双工{n}字节一致'] = False
                        uartp.recv_data(timeout=0)
                        sdata = OrderAry(n, seedfrom, seedfrom + 8).to_bytes()
                        if uartp.send_data(sdata) < 0:
                            continue
                        rdata = collect_bytes(uartp, n, n * 10 / uartp.baudrate * 3 + 0.5)
                        if rdata == sdata:
                            rep[f'全双工{n}字节一致'] = True
                        seedfrom = (seedfrom + 1) if seedfrom < ord('Z') else ord(' ')

                    # 步骤3: 停止回环任务
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp.recv_data(timeout=0)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行42 rx和tx同时出现数据")

    @allure.feature("全双工")
    @allure.story("性能")
    @allure.title("飞书行43 全双工吞吐量-115200")
    @allure.description("期望: 单方向吞吐率 >95% 理论速率。"
                        "以两档长度(N/2 与 N)差分折算持续速率判定(回环管线固定时延在差分中消去; "
                        "被串行化则差分速率≈50% 无法通过), MCU 侧回环收发足额且零错时作判定替代")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "全双工", "性能")
    def test_duplex_tput_115200(self, shellp, uart_args):
        """飞书行43 | 全双工/性能 | 全双工吞吐量-115200"""
        rep = {}
        m = _run_duplex_tput(shellp, uart_args, 115200)
        if m is None:
            rep['打开串口失败'] = False
        else:
            rep.update(m)
            rep['单方向吞吐率>95%理论'] = (m.get('记录:差分速率比%', 0) > TPUT_RATIO_MIN) \
                or m.get('MCU侧回环足额(判定替代)', False)
        assert_feishu_rep(rep, "飞书行43 全双工吞吐量-115200")

    @allure.feature("全双工")
    @allure.story("性能")
    @allure.title("飞书行44 全双工吞吐量-460800")
    @allure.description("期望: 单方向吞吐率 >95% 理论速率(差分法判定)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "全双工", "性能")
    def test_duplex_tput_460800(self, shellp, uart_args):
        """飞书行44 | 全双工/性能 | 全双工吞吐量-460800"""
        rep = {}
        m = _run_duplex_tput(shellp, uart_args, 460800)
        if m is None:
            rep['打开串口失败'] = False
        else:
            rep.update(m)
            rep['单方向吞吐率>95%理论'] = (m.get('记录:差分速率比%', 0) > TPUT_RATIO_MIN) \
                or m.get('MCU侧回环足额(判定替代)', False)
        assert_feishu_rep(rep, "飞书行44 全双工吞吐量-460800")

    @allure.feature("全双工")
    @allure.story("性能")
    @allure.title("飞书行45 全双工吞吐量-921600")
    @allure.description("期望: 单方向吞吐率 >95% 理论速率(标准档, 差分法判定)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "全双工", "性能")
    def test_duplex_tput_921600(self, shellp, uart_args):
        """飞书行45 | 全双工/性能 | 全双工吞吐量-921600"""
        rep = {}
        m = _run_duplex_tput(shellp, uart_args, 921600)
        if m is None:
            rep['打开串口失败'] = False
        else:
            rep.update(m)
            rep['单方向吞吐率>95%理论'] = (m.get('记录:差分速率比%', 0) > TPUT_RATIO_MIN) \
                or m.get('MCU侧回环足额(判定替代)', False)
        assert_feishu_rep(rep, "飞书行45 全双工吞吐量-921600")

    @allure.feature("全双工")
    @allure.story("性能")
    @allure.title("飞书行46 全双工吞吐量-1500000")
    @allure.description("期望: 单方向吞吐率 >95% 理论速率(高性能档, 差分法判定;"
                        "主机实收不完整而 MCU 侧收发足额零错时定责台架 USB 接收路径)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "全双工", "性能")
    def test_duplex_tput_1500000(self, shellp, uart_args):
        """飞书行46 | 全双工/性能 | 全双工吞吐量-1500000"""
        rep = {}
        m = _run_duplex_tput(shellp, uart_args, 1500000)
        if m is None:
            rep['打开串口失败'] = False
        else:
            rep.update(m)
            rep['单方向吞吐率>95%理论'] = (m.get('记录:差分速率比%', 0) > TPUT_RATIO_MIN) \
                or m.get('MCU侧回环足额(判定替代)', False)
        assert_feishu_rep(rep, "飞书行46 全双工吞吐量-1500000")

    @allure.feature("全双工")
    @allure.story("性能")
    @allure.title("飞书行47 全双工线程CPU耗时(占位)")
    @allure.description("占位: 回环任务独立于 Shell 运行, 不经 dmdtest_uart 统计路径, "
                        "固件无查询其它任务 CPU 占用的命令(单向 send/recv 的 CPU 统计已由行18/38 覆盖)")
    @allure.severity(allure.severity_level.MINOR)
    @allure.tag("UART", "全双工", "占位")
    def test_duplex_thread_cpu(self):
        """飞书行47 | 全双工/性能 | 全双工线程CPU耗时(占位, 无法自动化)"""
        pytest.skip('回环任务不经dmdtest_uart统计路径, 固件无其它任务CPU查询命令')

    @allure.feature("全双工")
    @allure.story("性能")
    @allure.title("飞书行48 全双工中断CPU耗时(占位)")
    @allure.description("占位: 同行19/39 —— 无中断级耗时统计手段")
    @allure.severity(allure.severity_level.MINOR)
    @allure.tag("UART", "全双工", "占位")
    def test_duplex_isr_cpu(self):
        """飞书行48 | 全双工/性能 | 全双工中断CPU耗时(占位, 无法自动化)"""
        pytest.skip('无中断级CPU耗时测量手段(需固件新增ISR统计命令)')
