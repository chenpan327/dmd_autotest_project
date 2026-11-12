# coding: utf-8
"""
===============================================================================
                            h743 UART 异常处理测试脚本
===============================================================================
脚本编号: DMD_TEST_H743_UART_ERROR_001
脚本版本: v1.1
创建日期: 2026-09-14
修改日期: 2026-09-17
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: hope_stm32h743vit6 公共开发板 (MCU 底软 UART 驱动)
测试类型: 底软功能验证测试
测试环境: Python 3.10, pytest, allure, 双串口 (Shell 口 + 数据口)

测试目的:
验证 h743 板 MCU 底软 UART 驱动对线路异常与帧错误的容错与恢复能力
(飞书行75-80, 共 6 个测试点)。硬件断开以 250ms Break(持续低电平)注入为
可自动化代理(物理拔插留人工); 奇偶/停止位/溢出错误经帧格式错配注入与
溢出探测验证"计数增长 + 丢失污染数据 + 恢复正常"三段式行为。

前置条件:
1. 测试环境准备:
   - h743 开发板已运行 ll_drivers_tester 测试固件, Shell 口已接测试主机
     (串口号/波特率见 config.json hope_stm32h743vit6 段 port1/baud1)
   - 被测 UART TX/RX 与主机数据口交叉直连 (串口号见 config 段 port2)
   - conftest 板段配置 fail-fast 校验通过, shellp / uart_args fixture 已就绪
2. 判定语义: 判定字典 rep 中任一值为 False 即该测试点失败, "记录:" 前缀键
   仅作记录, 逐点判定明细挂 Allure 附件
3. 并行约束: 单一 Shell 串口物理独占, 严禁 pytest-xdist / 多进程并行
原理详见: mcu_ll_drivers_tester/ll_drivers_tester_host/doc/uart_test_principle.md 第 11 章

测试步骤:
1. [飞书行75 test_err_disconnect_rx] 接收恢复(break 模拟): MCU 阻塞接收中主机
   在线打 250ms Break → 重发 recv 拉起接收再送数据, 3 次重试
2. [飞书行76 test_err_disconnect_tx] 发送恢复(break 模拟): 主机打 250ms Break →
   MCU 发送 8 字节 → 主机接收全量比对, 3 次重试
3. [飞书行77 test_err_parity_inject] 注入错误奇偶校验位: 8E1/8O1 错配注入
   64 字节 (每字节必 PE) 三段式: 注入 → 恢复 → 清理
4. [飞书行78 test_err_noise_inject] 半位噪声注入 (占位): 无法自动化
5. [飞书行79 test_err_frame_inject] 注入停止位错误:
   (1) 位长错配注入 (MCU 7N1 vs 主机 8N1, 每字节必 FE) 三段式
   (2) 附加场景: 2 停止位/1 停止位错配满载 2048B 容错 (接收器只查首个停止位)
6. [飞书行80 test_err_overrun_inject] 注入硬件溢出: MCU 停读 + 主机满速灌 8KB,
   记录 ORE 增量, 验证恢复能力

预期结果（与测试步骤一一对应）:
1. [行75] 3 次重试内接收恢复正常 (break 起始帧错误中止在途 recv 属实测行为,
   中止形态仅记录)
2. [行76] 3 次重试内发送恢复且数据一致 (错误状态不残留)
3. [行77] PE 计数增长 + 污染数据未被全量接收 + 恢复后正常收发且 PE 计数稳定
4. [行78] skip (pyserial 只能发完整帧, 需信号发生器/干扰电路)
5. [行79] FE 计数增长 + 污染数据丢弃 + 恢复后正常收发且 FE 计数稳定;
   附加场景满载数据完整 (FE 仅记录)
6. [行80] 溢出后双向收发恢复且后续新数据正常 (确定性硬件 ORE 需 RDR 滞留
   条件, 计数增长仅记录, 以恢复判定)

===============================================================================
测试结论:
异常处理 6 个测试点全部实现自动化 (占位点显式 skip 并注明原因), 判定结果
与逐点明细见 Allure 报告各用例的「判定明细」「串口收发流水」附件。
===============================================================================
"""
import allure
import pytest

from src.Protocol.dmdtest_uart import (
    open_target,
    close_target,
    inject_parity_mismatch,
    inject_databits_mismatch,
    inject_stopbits_mismatch,
    inject_break_and_recv_recover,
    inject_break_and_send_recover,
    overflow_probe,
)
from utils.assert_helper import assert_feishu_rep


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartError:
    """异常处理 (飞书行75-80)"""

    @allure.feature("异常处理")
    @allure.story("硬件断开与恢复")
    @allure.title("飞书行75 接收恢复(break模拟)")
    @allure.description("期望: 重连后能够正常接收数据。"
                        "物理拔插无法自动化, 以 250ms break(持续低电平, 常见于对端复位/拔插/干扰)模拟异常线路; "
                        "实测 break 起始帧错误会立即中止在途 recv(负错误码), 恢复验证为 break 结束后"
                        "重发 recv 拉起接收再收数据, 3 次重试内恢复正常")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "异常处理")
    def test_err_disconnect_rx(self, shellp, uart_args):
        """飞书行75 | 异常处理 | 接收恢复(break模拟)"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                # 步骤1: break 注入 + 接收恢复探测(3次重试内)
                ok, tries, abort_form = inject_break_and_recv_recover(shellp, uartp, ord('O'))
                rep['break后3次重试内接收恢复'] = ok
                rep['记录:实际重试次数'] = tries
                rep['记录:在途recv中止形态'] = abort_form
                rep['说明'] = ('物理拔线无法自动化(需人工/机械结构), 以250ms break模拟线路异常; '
                               '在途中止形态仅记录不作判定')
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行75 接收恢复(break模拟)")

    @allure.feature("异常处理")
    @allure.story("硬件断开与恢复")
    @allure.title("飞书行76 发送恢复(break模拟)")
    @allure.description("期望: 重连后能够正常发送数据。"
                        "break 注入后 MCU 发送数据由主机接收比对, 验证错误状态不残留、发送路径正常")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "异常处理")
    def test_err_disconnect_tx(self, shellp, uart_args):
        """飞书行76 | 异常处理 | 发送恢复(break模拟)"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                # 步骤1: break 注入 + 发送恢复探测
                ok, tries = inject_break_and_send_recover(shellp, uartp, ord('P'))
                rep['break后3次重试内发送恢复'] = ok
                rep['记录:实际重试次数'] = tries
                rep['说明'] = '物理拔线无法自动化, 以250ms break模拟线路异常'
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行76 发送恢复(break模拟)")

    @allure.feature("异常处理")
    @allure.story("奇偶校验位错误")
    @allure.title("飞书行77 注入错误奇偶校验位")
    @allure.description("期望: 奇偶校验位错误计数增加, 丢失该数据, 正常接收后续数据。"
                        "8E/8O 错配注入(每字节必 PE): PE 计数增长 + 污染数据丢失 + 恢复后正常收发")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "异常处理")
    def test_err_parity_inject(self, shellp, uart_args):
        """飞书行77 | 异常处理 | 注入错误奇偶校验位"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                rep.update(inject_parity_mismatch(shellp, uartp, 64, ord('Q')))
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行77 注入错误奇偶校验位")

    @allure.feature("异常处理")
    @allure.story("噪声错误")
    @allure.title("飞书行78 半位噪声注入(占位)")
    @allure.description("期望: 噪声错误计数增加, 丢失该数据, 正常接收后续数据。"
                        "占位: pyserial 只能发送完整帧, 无法在指定位注入半位噪声, 需信号发生器/干扰电路")
    @allure.severity(allure.severity_level.MINOR)
    @allure.tag("UART", "异常处理", "占位")
    def test_err_noise_inject(self):
        """飞书行78 | 异常处理 | 半位噪声注入(占位, 无法自动化)"""
        pytest.skip('无法在指定位注入半位噪声(需信号发生器/干扰电路), pyserial只能发完整帧')

    @allure.feature("异常处理")
    @allure.story("帧错误")
    @allure.title("飞书行79 注入停止位错误")
    @allure.description("期望: 停止位错误计数增加, 丢失该数据, 正常接收后续数据。"
                        "位长错配(MCU 7N1 vs 主机 8N1)使停止位采样落在恒 0 的 D7, 每字节必 FE; "
                        "附加场景: 2停止/1停止错配满载 2048B 容错(接收器只查首个停止位, 预期正常)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "异常处理")
    def test_err_frame_inject(self, shellp, uart_args):
        """飞书行79 | 异常处理 | 注入停止位错误"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                # 步骤1: 位长错配注入(主判定: FE计数增长+丢失污染数据+恢复正常)
                rep.update(inject_databits_mismatch(shellp, uartp, 64, ord('R')))

                # 步骤2: 附加场景: 停止位数量错配满载容错(数据应正常, FE仅记录)
                sub = inject_stopbits_mismatch(shellp, uartp, 2048, ord('S'))
                rep['附加:2停止/1停止满载数据完整'] = sub.get('停止位错配满载数据完整', False)
                if '记录:满载期间FE增量' in sub:
                    rep['记录:停止位错配满载FE增量'] = sub['记录:满载期间FE增量']
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行79 注入停止位错误")

    @allure.feature("异常处理")
    @allure.story("溢出错误")
    @allure.title("飞书行80 注入硬件溢出")
    @allure.description("期望: 溢出错误计数增加, 丢失该数据, 正常接收后续数据。"
                        "探测: MCU 停读 + 主机满速灌 8KB, 记录 ORE 增量, 以恢复判定"
                        "(确定性硬件 ORE 需 RDR 滞留条件, 无法从主机制造)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "异常处理")
    def test_err_overrun_inject(self, shellp, uart_args):
        """飞书行80 | 异常处理 | 注入硬件溢出"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                rep.update(overflow_probe(shellp, uartp, ord('T')))
                rep['说明'] = '确定性硬件ORE需RDR滞留条件无法从主机制造, 计数增长仅记录, 以恢复判定'
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行80 注入硬件溢出")
