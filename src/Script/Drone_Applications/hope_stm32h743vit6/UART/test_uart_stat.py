# coding: utf-8
"""
===============================================================================
                            h743 UART 统计功能测试脚本
===============================================================================
脚本编号: DMD_TEST_H743_UART_STAT_001
脚本版本: v1.1
创建日期: 2026-09-14
修改日期: 2026-09-17
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: hope_stm32h743vit6 公共开发板 (MCU 底软 UART 驱动)
测试类型: 底软功能验证测试
测试环境: Python 3.10, pytest, allure, 双串口 (Shell 口 + 数据口)

测试目的:
验证 h743 板 MCU 底软 UART 驱动 dmdtest_uart stat 全量统计的正确性
(飞书行51-58, 共 8 个测试点)。统计字段: baud/tx_bytes/rx_bytes/五类错误计数
(parity/noise/frame/overrun/dma)/sw_err/hw_err。字节计数为应用级口径具确定性,
可 0 误差精确断言; 错误计数经帧格式错配注入验证"计数增长→恢复后稳定"。

前置条件:
1. 测试环境准备:
   - h743 开发板已运行 ll_drivers_tester 测试固件, Shell 口已接测试主机
     (串口号/波特率见 config.json hope_stm32h743vit6 段 port1/baud1)
   - 被测 UART TX/RX 与主机数据口交叉直连 (串口号见 config 段 port2)
   - conftest 板段配置 fail-fast 校验通过, shellp / uart_args fixture 已就绪
2. 判定语义: 判定字典 rep 中任一值为 False 即该测试点失败, "记录:" 前缀键
   仅作记录, 逐点判定明细挂 Allure 附件
3. 并行约束: 单一 Shell 串口物理独占, 严禁 pytest-xdist / 多进程并行
原理详见: mcu_ll_drivers_tester/ll_drivers_tester_host/doc/uart_test_principle.md 第 3.6/8 章

测试步骤:
1. [飞书行51 test_stat_rx_bytes] 总接收字节数:
   (1) dmdtest_uart stat 查询 rx_bytes 基线
   (2) MCU 阻塞接收 256 字节 (主机发送, 固件内比对消费)
   (3) 再查 stat, 计算增量并判定
2. [飞书行52 test_stat_tx_bytes] 总发送字节数:
   (1) 查询 tx_bytes 基线
   (2) MCU 发送 512 字节 (主机侧清收不影响计数)
   (3) 再查 stat 计算增量并判定
3. [飞书行53 test_stat_parity_err] 奇偶校验位错误: 8E1/8O1 错配注入 64 字节
   (偶/奇互补每字节必 PE) 三段式: 注入 → 恢复 → 清理, 全程查 stat
4. [飞书行54 test_stat_noise_err] 噪声错误 (占位): 无法自动化
5. [飞书行55 test_stat_frame_err] 帧错误: 7N1/8N1 位长错配注入 64 字节
   (停止位采样落在恒 0 的 D7, 每字节必 FE) 三段式
6. [飞书行56 test_stat_overrun_err] 溢出错误: MCU 停读 + 主机满速灌 8KB 制造
   接收溢出, 记录 ORE/FE/PE 增量与 recv 返回形态
7. [飞书行57 test_stat_app_unread] 应用层未接收字节数 (占位): 无法自动化
8. [飞书行58 test_stat_precision] 统计精度验证:
   (1) baud 字段一致性
   (2) 发送 512 字节后 tx_bytes 增量精确性
   (3) 接收 256 字节后 rx_bytes 增量精确性
   (4) 8E1/8O1 注入 32 字节记录 PE 增量界限
   (5) 双侧恢复 8N1 清理现场

预期结果（与测试步骤一一对应）:
1. [行51] 计数有增加 (>0) 且增量精确 ==256 (0 误差)
2. [行52] 计数有增加 (>0) 且增量精确 ==512 (0 误差)
3. [行53] PE 计数增长 + 污染数据未被全量接收 + 恢复后收发正常且 PE 计数稳定
4. [行54] skip (pyserial 只能发完整帧, 无法注入位级噪声)
5. [行55] FE 计数增长 + 污染数据未被全量接收 + 重发 recv 恢复正常且 FE 计数稳定
6. [行56] 溢出后双向收发恢复且后续新数据正常 (DMA 持续搬移 RDR 时硬件 ORE
   难以确定性触发, 计数增长仅记录)
7. [行57] skip (rx_bytes 为应用已读取口径, 无未读取积压统计字段)
8. [行58] baud==115200; tx_bytes 增量精确 ==512; rx_bytes 增量精确 ==256;
   PE 增量 ∈[1,32] (错误计数受自愈重挂丢弃影响仅界限判定)

===============================================================================
测试结论:
统计功能 8 个测试点全部实现自动化 (占位点显式 skip 并注明原因), 字节计数
0 误差断言 + 错误计数界限判定, 判定结果与逐点明细见 Allure 报告各用例的
「判定明细」「串口收发流水」附件。
===============================================================================
"""
import time

import allure
import pytest

from src.Protocol.dmdtest_uart import (
    OrderAry,
    normal_cmd_ack,
    ack_is_ok,
    normal_recv_data_to_ack,
    apply_format_both,
    query_stat,
    open_target,
    close_target,
    inject_parity_mismatch,
    inject_databits_mismatch,
    overflow_probe,
)
from utils.assert_helper import assert_feishu_rep


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartStat:
    """统计功能 (飞书行51-58)"""

    @allure.feature("统计功能")
    @allure.story("数据接收统计")
    @allure.title("飞书行51 总接收字节数")
    @allure.description("期望: 计数有增加。"
                        "rx_bytes 为应用级口径(recv 实际读取量累加): 基线 → 主机发 256 字节+MCU recv 读取 → "
                        "判定计数有增加(>0) 且增量精确==N(0 误差)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "统计功能")
    def test_stat_rx_bytes(self, shellp, uart_args):
        """飞书行51 | 统计功能 | 总接收字节数"""
        rep = {}
        N = 256
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('z')

                # 步骤1: 记录 rx_bytes 基线
                st0 = query_stat(shellp)
                rep['stat查询可用'] = st0 is not None and 'rx_bytes' in st0
                if not rep['stat查询可用']:
                    assert_feishu_rep(rep, "飞书行51 总接收字节数")
                    return

                # 步骤2: MCU 进入接收, 主机发 N 字节(固件内比对消费)
                uartp.recv_data(timeout=0)
                cmd = f"dmdtest_uart recv len={N} from={seedfrom} to={seedfrom+8} timeout=1000"
                shellp.send_text(cmd + '\r\n')
                time.sleep(0.05)
                uartp.send_data(OrderAry(N, seedfrom, seedfrom + 8).to_bytes())
                time.sleep(0.1 + N * 10 / uartp.baudrate)
                acks = normal_recv_data_to_ack(shellp, cmd, 2.0)
                rep['接收N字节成功'] = ack_is_ok(acks) and len(acks.split()) > 2 \
                    and int(acks.split()[2]) == N

                # 步骤3: 查询 rx_bytes 增量并判定
                st1 = query_stat(shellp)
                if st1 is None or 'rx_bytes' not in st1:
                    rep['计数有增加(规格)'] = False
                else:
                    delta = st1['rx_bytes'] - st0['rx_bytes']
                    rep['记录:rx_bytes增量'] = delta
                    rep['计数有增加(规格)'] = delta > 0
                    rep['增量精确==N(0误差)'] = delta == N
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行51 总接收字节数")

    @allure.feature("统计功能")
    @allure.story("数据发送统计")
    @allure.title("飞书行52 总发送字节数")
    @allure.description("期望: 计数有增加。"
                        "tx_bytes 为 send 实际送达 DMA 量累加: 基线 → MCU 发送 512 字节 → "
                        "判定计数有增加(>0) 且增量精确==N(0 误差)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "统计功能")
    def test_stat_tx_bytes(self, shellp, uart_args):
        """飞书行52 | 统计功能 | 总发送字节数"""
        rep = {}
        N = 512
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('y')

                # 步骤1: 记录 tx_bytes 基线
                st0 = query_stat(shellp)
                rep['stat查询可用'] = st0 is not None and 'tx_bytes' in st0
                if not rep['stat查询可用']:
                    assert_feishu_rep(rep, "飞书行52 总发送字节数")
                    return

                # 步骤2: MCU 发送 N 字节(主机侧清收不影响计数)
                uartp.recv_data(timeout=0)
                acks = normal_cmd_ack(shellp, f"dmdtest_uart send len={N} from={seedfrom} to={seedfrom+8} timeout=-1",
                                      0.1 + N * 10 / uartp.baudrate)
                rep['发送N字节成功'] = ack_is_ok(acks) and len(acks.split()) > 2 \
                    and int(acks.split()[2]) == N
                uartp.recv_data(timeout=0.2)

                # 步骤3: 查询 tx_bytes 增量并判定
                st1 = query_stat(shellp)
                if st1 is None or 'tx_bytes' not in st1:
                    rep['计数有增加(规格)'] = False
                else:
                    delta = st1['tx_bytes'] - st0['tx_bytes']
                    rep['记录:tx_bytes增量'] = delta
                    rep['计数有增加(规格)'] = delta > 0
                    rep['增量精确==N(0误差)'] = delta == N
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行52 总发送字节数")

    @allure.feature("统计功能")
    @allure.story("异常统计")
    @allure.title("飞书行53 奇偶校验位错误")
    @allure.description("期望: 计数有增加。"
                        "8E/8O 错配注入(偶/奇互补, 每字节必 PE): PE 计数增长 + 污染数据未被全量接收 + 恢复后计数稳定")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "统计功能")
    def test_stat_parity_err(self, shellp, uart_args):
        """飞书行53 | 统计功能 | 奇偶校验位错误"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                rep.update(inject_parity_mismatch(shellp, uartp, 64, ord('w')))
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行53 奇偶校验位错误")

    @allure.feature("统计功能")
    @allure.story("异常统计")
    @allure.title("飞书行54 噪声错误(占位)")
    @allure.description("期望: 计数有增加。"
                        "占位: NE 计数查询能力已具备, 但 pyserial 只能发送完整帧, "
                        "无法在指定位注入噪声使采样判决出错, 需信号发生器/硬件干扰电路后补全")
    @allure.severity(allure.severity_level.MINOR)
    @allure.tag("UART", "统计功能", "占位")
    def test_stat_noise_err(self):
        """飞书行54 | 统计功能 | 噪声错误(占位, 无法自动化)"""
        pytest.skip('位级噪声无法经pyserial注入(需硬件干扰源), NE计数仅可查询')

    @allure.feature("统计功能")
    @allure.story("异常统计")
    @allure.title("飞书行55 帧错误")
    @allure.description("期望: 计数有增加。"
                        "位长错配注入(MCU 7N1 vs 主机 8N1, 停止位采样点落在恒为 0 的 D7): "
                        "FE 计数增长 + 污染数据未被全量接收 + 恢复后计数稳定")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "统计功能")
    def test_stat_frame_err(self, shellp, uart_args):
        """飞书行55 | 统计功能 | 帧错误"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                rep.update(inject_databits_mismatch(shellp, uartp, 64, ord('x')))
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行55 帧错误")

    @allure.feature("统计功能")
    @allure.story("异常统计")
    @allure.title("飞书行56 溢出错误")
    @allure.description("期望: 计数有增加。"
                        "探测: MCU 停读 + 主机满速灌 8KB 制造接收溢出。"
                        "DMA 持续搬移 RDR 时硬件 ORE 难以确定性触发, 计数增长仅记录, 以恢复能力判定")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "统计功能")
    def test_stat_overrun_err(self, shellp, uart_args):
        """飞书行56 | 统计功能 | 溢出错误"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                rep.update(overflow_probe(shellp, uartp, ord('y')))
                rep['说明'] = 'DMA持续搬移RDR时硬件ORE难以触发, 计数增长仅记录, 以恢复能力判定'
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行56 溢出错误")

    @allure.feature("统计功能")
    @allure.story("异常统计")
    @allure.title("飞书行57 应用层未接收字节数(占位)")
    @allure.description("期望: 计数有增加。"
                        "占位: rx_bytes 为应用已读取口径, DMA 缓冲未读取积压字节数无对应统计字段, 无法查询")
    @allure.severity(allure.severity_level.MINOR)
    @allure.tag("UART", "统计功能", "占位")
    def test_stat_app_unread(self):
        """飞书行57 | 统计功能 | 应用层未接收字节数(占位, 无法自动化)"""
        pytest.skip('rx_bytes为应用已读取口径, DMA缓冲未读取积压字节数无对应统计字段')

    @allure.feature("统计功能")
    @allure.story("异常统计")
    @allure.title("飞书行58 统计精度验证")
    @allure.description("期望: 统计计数 0 误差。四组判定: "
                        "① baud 字段==115200 ② tx_bytes 增量精确==512 ③ rx_bytes 增量精确==256 "
                        "④ 8E/8O 注入 32 字节 PE 增量记录(自愈重挂丢弃影响, 以 [1,32] 界限判定)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "统计功能")
    def test_stat_precision(self, shellp, uart_args):
        """飞书行58 | 统计功能 | 统计精度验证"""
        rep = {}
        N = 512   # 发送精度测量长度
        M = 256   # 接收精度测量长度
        P = 32    # 错误注入字节数
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('x')

                # 步骤1: 波特率字段一致性
                st = query_stat(shellp)
                rep['stat查询可用'] = st is not None
                if st is None:
                    assert_feishu_rep(rep, "飞书行58 统计精度验证")
                    return
                if 'baud' in st:
                    rep['波特率字段==115200'] = (st['baud'] == 115200)

                # 步骤2: 发送字节计数0误差
                st0 = query_stat(shellp)
                uartp.recv_data(timeout=0)
                acks = normal_cmd_ack(shellp, f"dmdtest_uart send len={N} from={seedfrom} to={seedfrom+8} timeout=-1",
                                      0.1 + N * 10 / uartp.baudrate)
                rep['发送N字节成功'] = ack_is_ok(acks) and len(acks.split()) > 2 \
                    and int(acks.split()[2]) == N
                uartp.recv_data(timeout=0.2)
                st1 = query_stat(shellp)
                if st0 and st1 and 'tx_bytes' in st0 and 'tx_bytes' in st1:
                    tx_delta = st1['tx_bytes'] - st0['tx_bytes']
                    rep[f'记录:发送{N}字节tx_bytes增量={tx_delta}'] = True
                    rep['tx_bytes增量精确==N(0误差)'] = (tx_delta == N)
                else:
                    rep['tx_bytes增量精确==N(0误差)'] = False

                # 步骤3: 接收字节计数0误差
                st0 = query_stat(shellp)
                uartp.recv_data(timeout=0)
                cmd = f"dmdtest_uart recv len={M} from={seedfrom+1} to={seedfrom+9} timeout=1000"
                shellp.send_text(cmd + '\r\n')
                time.sleep(0.05)
                uartp.send_data(OrderAry(M, seedfrom + 1, seedfrom + 9).to_bytes())
                time.sleep(0.1 + M * 10 / uartp.baudrate)
                acks = normal_recv_data_to_ack(shellp, cmd, 2.0)
                rep['接收M字节成功'] = ack_is_ok(acks)
                st1 = query_stat(shellp)
                if st0 and st1 and 'rx_bytes' in st0 and 'rx_bytes' in st1:
                    rx_delta = st1['rx_bytes'] - st0['rx_bytes']
                    rep[f'记录:接收{M}字节rx_bytes增量={rx_delta}'] = True
                    rep['rx_bytes增量精确==M(0误差)'] = (rx_delta == M)
                else:
                    rep['rx_bytes增量精确==M(0误差)'] = False

                # 步骤4: 错误计数精度(8E/8O 错配注入 P 字节全错校验)
                if not apply_format_both(shellp, uartp, 8, 'E', 1):
                    rep['配置8E1失败'] = False
                else:
                    st0 = query_stat(shellp)
                    if st0 is None or 'parity' not in st0:
                        rep['错误计数精度查询失败'] = False
                    elif uartp.set_format(8, 'O', 1):
                        cmd = f"dmdtest_uart recv len={P} from={seedfrom+2} to={seedfrom+10} timeout=200"
                        shellp.send_text(cmd + '\r\n')
                        time.sleep(0.05)
                        uartp.send_data(OrderAry(P, seedfrom + 2, seedfrom + 10).to_bytes())
                        time.sleep(0.5)
                        normal_recv_data_to_ack(shellp, cmd, timeout=1.0)
                        st1 = query_stat(shellp)
                        pe_delta = (st1['parity'] - st0['parity']) if st1 else -1
                        rep[f'记录:注入{P}字节PE增量={pe_delta}'] = True
                        rep['PE增量≥1且≤注入字节数'] = (1 <= pe_delta <= P)
                    else:
                        rep['主机侧设置8O1失败'] = False
                rep['说明'] = ('字节计数器(tx/rx_bytes)可0误差精确断言; '
                               'PE错误计数受自愈重挂丢弃影响仅界限判定')

                # 步骤5: 现场清理
                apply_format_both(shellp, uartp, 8, 'N', 1)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行58 统计精度验证")
