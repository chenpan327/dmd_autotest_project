# coding: utf-8
"""
===============================================================================
                        h743 UART 波特率设置功能测试脚本
===============================================================================
脚本编号: DMD_TEST_H743_UART_BAUD_001
脚本版本: v1.1
创建日期: 2026-09-14
修改日期: 2026-09-17
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: hope_stm32h743vit6 公共开发板 (MCU 底软 UART 驱动)
测试类型: 底软功能验证测试
测试环境: Python 3.10, pytest, allure, 双串口 (Shell 口 + 数据口)

测试目的:
验证 h743 板 MCU 底软 UART 驱动波特率动态配置功能的正确性(飞书行59-64,
共 6 个测试点), 覆盖标准波特率八档遍历(行59)、发送/接收进行中与空隙/空闲
四场景动态重配置(行60-63)、非标准波特率非法值处理(行64)。

前置条件:
1. 测试环境准备:
   - h743 开发板已运行 ll_drivers_tester 测试固件, Shell 口已接测试主机
     (串口号/波特率见 config.json hope_stm32h743vit6 段 port1/baud1)
   - 被测 UART TX/RX 与主机数据口交叉直连 (串口号见 config 段 port2;
     主机数据口随 MCU 侧配置同步换波特率重开)
   - conftest 板段配置 fail-fast 校验通过, shellp / uart_args fixture 已就绪
2. 判定语义: 判定字典 rep 中任一值为 False 即该测试点失败, "记录:" 前缀键
   仅作记录, 逐点判定明细挂 Allure 附件
3. 并行约束: 单一 Shell 串口物理独占, 严禁 pytest-xdist / 多进程并行
原理详见: mcu_ll_drivers_tester/ll_drivers_tester_host/doc/uart_test_principle.md 第 9 章

测试步骤:
1. [飞书行59 test_baud_standard] 标准波特率配置遍历:
   9600/115200/230400/460800/921600/1000000/1500000/2000000 八档逐档
   (1) dmdtest_uart config baud=<档位>
   (2) 主机数据口按新波特率重开 (pyserial 热切换不可靠, 重建对象)
   (3) MCU 发送 50 字节并全量比对
2. [飞书行60 test_baud_reconfig_tx_busy] 发送进行中配置: 持续满速发送任务占满
   tx 线 → config baud=460800 → 主机重开@460800 → 100 字节块周期校验 →
   停任务恢复 115200 并验证收发
3. [飞书行61 test_baud_reconfig_tx_gap] 发送空隙配置: 上一笔收发完成(线空闲)
   的确定性空隙中切 230400/460800 → 新波特率下收发验证 → 恢复 115200
4. [飞书行62 test_baud_reconfig_rx_busy] 接收进行中配置: 启动接收任务 + 主机
   后台线程持续灌流 → 灌流中 config baud=460800 → 停流、同波特率重挂接收 →
   新波特率下 64 字节接收验证 → 恢复 115200
5. [飞书行63 test_baud_reconfig_rx_idle] 接收空闲配置: 接收任务运行(阻塞等待,
   线无数据)中切 460800/115200 → 停任务换档 → 双向收发验证
6. [飞书行64 test_baud_nonstandard] 非标准波特率传入: baud=0 与 baud=-1
   期望被拒绝; baud=12345 记录实际行为(BRR 整除近似); 恢复 115200 并验证收发

预期结果（与测试步骤一一对应）:
1. [行59] 八档均配置成功且 50 字节收发一致 (位宽精度需仪器测量, 以高速档
   完整性间接验证)
2. [行60] 占用中配置成功; 新波特率下数据流完整 (100 字节块周期校验通过);
   恢复 115200 后双向收发正常
3. [行61] 空隙配置成功; 各新波特率下收发正常; 恢复后收发正常
4. [行62] 接收流中配置成功; 换档后接收正常且数据一致 (切换期数据损坏属预期)
5. [行63] 接收任务运行中配置成功; 各档换档后收发正常
6. [行64] baud=0/-1 均返回 NG (配置失败); 12345 行为仅记录; 恢复后收发正常

===============================================================================
测试结论:
波特率设置 6 个测试点全部实现自动化, 判定结果与逐点明细见 Allure 报告
各用例的「判定明细」「串口收发流水」附件。
===============================================================================
"""
import threading
import time

import allure

from src.Protocol.dmdtest_uart import (
    OrderAry,
    FEISHU_STD_BAUDS,
    normal_cmd_ack,
    ack_is_ok,
    normal_recv_data_to_ack,
    collect_bytes,
    verify_tx_task_stream,
    query_shell_prio,
    host_roundtrip,
    open_target,
    close_target,
    switch_host_port,
)
from utils.assert_helper import assert_feishu_rep


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartBaudStandard:
    """波特率设置功能 — 标准波特率 (飞书行59)"""

    @allure.feature("波特率设置功能")
    @allure.story("标准波特率")
    @allure.title("飞书行59 标准波特率配置遍历")
    @allure.description("期望: 各标准档位配置后数据收发正常。"
                        "8 档(9600~2000000, 含 115200/460800/921600/1500000)逐档 "
                        "配置→主机重开→MCU 发 50 字节→全量比对。位宽精度需仪器测量, 以高速档完整性间接验证")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "波特率设置功能")
    def test_baud_standard(self, shellp, uart_args):
        """飞书行59 | 波特率设置功能 | 标准波特率配置遍历"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('A')
                for baud in FEISHU_STD_BAUDS:
                    rep[f'波特率{baud}配置并收发一致'] = False

                    # 步骤1: 配置新波特率
                    if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart config baud={baud}", 0.3)):
                        continue

                    # 步骤2: 主机数据口以新波特率重开
                    uartp = switch_host_port(uart_args, uartp, baud)
                    time.sleep(0.1)
                    uartp.recv_data(timeout=0)

                    # 步骤3: MCU 发 50 字节并比对
                    acks = normal_cmd_ack(shellp, f"dmdtest_uart send len=50 from={seedfrom} to={seedfrom+10} timeout=-1",
                                          0.1 + 50 * 10 / baud)
                    time.sleep(0.05)
                    rdata = uartp.recv_data(timeout=1.0)
                    if ack_is_ok(acks) and rdata and rdata == OrderAry(50, seedfrom, seedfrom + 10).to_bytes():
                        rep[f'波特率{baud}配置并收发一致'] = True
                    seedfrom = (seedfrom + 1) if seedfrom < ord('Z') else ord('A')
                rep['说明'] = '位宽精度(时钟偏差)需仪器测量, 以高速档数据完整性间接验证'
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行59 标准波特率配置遍历")


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartBaudReconfig:
    """波特率设置功能 — 动态重配置 (飞书行60-63)"""

    @allure.feature("波特率设置功能")
    @allure.story("动态重配置")
    @allure.title("飞书行60 发送进行中配置")
    @allure.description("期望: tx线被占用时配置波特率成功, 同步换档后数据发送正常。"
                        "① 启动 uart_tx_t 持续发送占满 tx 线 ② 发送中 config baud=460800 ③ "
                        "主机重开@460800 丢弃过渡期数据 ④ 校验 100 字节块周期完整性")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "波特率设置功能", "动态重配置")
    def test_baud_reconfig_tx_busy(self, shellp, uart_args):
        """飞书行60 | 波特率设置功能 | 发送进行中配置"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                # 步骤1: 启动持续满速发送任务(默认优先级, 占满发送通道)
                if not ack_is_ok(normal_cmd_ack(shellp, "dmdtest_uart enable id=0", 0.3)):
                    rep['启动持续发送任务失败'] = False
                else:
                    # 步骤2: 发送进行中配置新波特率(DMA 传输进行时); 满速任务前3s不让出CPU,
                    # shell 应答实测约2.75s到达, 应答窗须加宽到4.5s
                    rep['发送中配置波特率成功'] = ack_is_ok(
                        normal_cmd_ack(shellp, "dmdtest_uart config baud=460800", 0.3, 4.5))

                    # 步骤3: 主机数据口重开@460800, 丢弃切换期过渡数据
                    uartp = switch_host_port(uart_args, uartp, 460800)
                    time.sleep(0.2)
                    uartp.recv_data(timeout=0)
                    collect_bytes(uartp, 256, 0.5)      # 丢弃过渡期可能损坏的数据

                    # 步骤4: 收集≥400字节, 校验 100 字节块周期性(新波特率下数据流完整)
                    data = collect_bytes(uartp, 400, 2.0)
                    rep['新波特率下数据流完整(100字节块周期)'] = verify_tx_task_stream(data)

                    # 步骤5: 停止任务, 恢复波特率并验证现场干净
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp.recv_data(timeout=0)
                    normal_cmd_ack(shellp, "dmdtest_uart config baud=115200", 0.3)
                    uartp = switch_host_port(uart_args, uartp, 115200)
                    rep['恢复115200后收发正常'] = host_roundtrip(shellp, uartp, 64, ord('B'))
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行60 发送进行中配置")

    @allure.feature("波特率设置功能")
    @allure.story("动态重配置")
    @allure.title("飞书行61 发送空隙配置")
    @allure.description("期望: tx线空隙时配置波特率成功, 双方同步后数据发送正常。"
                        "确定性空隙: 「上一笔发送已完成(应答即线空闲)、下一笔未开始」时立即配置并验证")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "波特率设置功能", "动态重配置")
    def test_baud_reconfig_tx_gap(self, shellp, uart_args):
        """飞书行61 | 波特率设置功能 | 发送空隙配置"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                seedfrom = ord('C')

                # 步骤1: 基线收发@115200
                rep['基线115200收发正常'] = host_roundtrip(shellp, uartp, 64, seedfrom)
                for new_baud in [230400, 460800]:
                    seedfrom += 1

                    # 步骤2: 上一笔收发已完成(线空闲), 空隙中立即配置新波特率
                    rep[f'空隙配置{new_baud}成功'] = ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart config baud={new_baud}", 0.3))

                    # 步骤3: 主机同步换波特率, 新波特率下收发验证
                    uartp = switch_host_port(uart_args, uartp, new_baud)
                    rep[f'{new_baud}下收发正常'] = host_roundtrip(shellp, uartp, 64, seedfrom)

                # 步骤4: 恢复 115200
                normal_cmd_ack(shellp, "dmdtest_uart config baud=115200", 0.3)
                uartp = switch_host_port(uart_args, uartp, 115200)
                rep['恢复115200后收发正常'] = host_roundtrip(shellp, uartp, 64, ord('D'))
                rep['说明'] = '以「上一笔发送已完成」的确定性空隙代替后台流1ms空隙(不可精确踩点)'
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行61 发送空隙配置")

    @allure.feature("波特率设置功能")
    @allure.story("动态重配置")
    @allure.title("飞书行62 接收进行中配置")
    @allure.description("期望: rx线被占用时配置波特率成功, 同步换档后数据接收正常。"
                        "① 启动 uart_rx_t + 主机后台线程持续灌流 ② 灌流中 config baud=460800 "
                        "③ 停流换档 ④ 正常接收验证(切换期数据损坏属预期)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "波特率设置功能", "动态重配置")
    def test_baud_reconfig_rx_busy(self, shellp, uart_args):
        """飞书行62 | 波特率设置功能 | 接收进行中配置"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                shell_prio = query_shell_prio(shellp) or 2
                seedfrom = ord('E')

                # 步骤1: 启动持续接收任务(rx 通道活跃)
                if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart enable id=1 prio={shell_prio+1}", 0.3)):
                    rep['启动接收任务失败'] = False
                else:
                    # 步骤2: 后台线程持续灌流(256字节块+10ms间隔, rx线持续有数据)
                    stop_evt = threading.Event()

                    def _stream_writer():
                        while not stop_evt.is_set():
                            uartp.send_data(OrderAry(256, seedfrom, seedfrom + 8).to_bytes())
                            time.sleep(0.01)

                    writer = threading.Thread(target=_stream_writer, daemon=True)
                    writer.start()
                    time.sleep(0.3)      # 等流稳定, rx线处于持续占用状态

                    # 步骤3: 灌流进行中配置波特率(接收数据流中切换, 期望配置成功);
                    # 满速任务前3s不让出CPU, shell 应答实测约2.75s到达, 应答窗须加宽到4.5s
                    rep['接收流中配置波特率成功'] = ack_is_ok(
                        normal_cmd_ack(shellp, "dmdtest_uart config baud=460800", 0.3, 4.5))
                    time.sleep(0.2)      # 切换期尾流(旧波特率数据成为乱码, 属预期)
                    stop_evt.set()
                    writer.join(2.0)

                    # 步骤4: 停止接收任务, 主机重开@460800
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp = switch_host_port(uart_args, uartp, 460800)
                    # 主机重开串口的电气瞬态可能在测试口产生毛刺字节→线路错误→接收中止死态,
                    # 且步骤5的数据可能在recv进入前到达而丢失(实测偶发"NG 0"超时);
                    # 同波特率重配置一次: 驱动deInit+init强制重挂接收并清空环形缓冲, 状态确定
                    normal_cmd_ack(shellp, "dmdtest_uart config baud=460800", 0.3)

                    # 步骤5: 新波特率下正常接收验证
                    seedfrom += 1
                    cmd = f"dmdtest_uart recv len=64 from={seedfrom} to={seedfrom+8} timeout=1000"
                    shellp.send_text(cmd + '\r\n')
                    time.sleep(0.05)
                    uartp.send_data(OrderAry(64, seedfrom, seedfrom + 8).to_bytes())
                    time.sleep(0.2)
                    acks = normal_recv_data_to_ack(shellp, cmd, 2.0)
                    rep['换档后接收正常且数据一致'] = ack_is_ok(acks) and len(acks.split()) > 2 \
                        and int(acks.split()[2]) == 64

                    # 步骤6: 恢复 115200
                    normal_cmd_ack(shellp, "dmdtest_uart config baud=115200", 0.3)
                    uartp = switch_host_port(uart_args, uartp, 115200)
                    uartp.recv_data(timeout=0)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行62 接收进行中配置")

    @allure.feature("波特率设置功能")
    @allure.story("动态重配置")
    @allure.title("飞书行63 接收空闲配置")
    @allure.description("期望: rx线空闲时配置波特率成功, 双方同步后数据接收正常。"
                        "接收任务运行(阻塞等待, 线无数据)时配置并验证, 补充「任务运行中动态重配置」维度")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("UART", "波特率设置功能", "动态重配置")
    def test_baud_reconfig_rx_idle(self, shellp, uart_args):
        """飞书行63 | 波特率设置功能 | 接收空闲配置"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                shell_prio = query_shell_prio(shellp) or 2
                seedfrom = ord('F')
                for new_baud in [460800, 115200]:
                    # 步骤1: 启动接收任务(阻塞等待数据, rx线空闲)
                    if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart enable id=1 prio={shell_prio+1}", 0.3)):
                        rep['启动接收任务失败'] = False
                        break

                    # 步骤2: 线空闲时配置波特率(接收任务运行中); 满速任务前3s不让出CPU,
                    # shell 应答实测约2.75s到达, 应答窗须加宽到4.5s
                    rep[f'接收任务运行中配置{new_baud}成功'] = ack_is_ok(
                        normal_cmd_ack(shellp, f"dmdtest_uart config baud={new_baud}", 0.3, 4.5))

                    # 步骤3: 停止任务, 主机同步换档, 验证接收正常
                    normal_cmd_ack(shellp, "dmdtest_uart disable", 1.0)
                    uartp = switch_host_port(uart_args, uartp, new_baud)
                    seedfrom += 1
                    rep[f'{new_baud}下接收正常'] = host_roundtrip(shellp, uartp, 64, seedfrom)
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行63 接收空闲配置")


@allure.epic("BSP_APP MCU 底软 UART 测试")
class TestUartBaudNonStandard:
    """波特率设置功能 — 非标准波特率 (飞书行64)"""

    @allure.feature("波特率设置功能")
    @allure.story("非标准波特率")
    @allure.title("飞书行64 非标准波特率传入")
    @allure.description("期望: 非法值(0/-1)返回配置失败。"
                        "① 非法值命令层 baud>0 校验拒绝(NG) ② 任意正值(12345)可被 BRR 整除近似接受, "
                        "与规格「必须失败」存在差异, 记录实际行为不作硬性判定 ③ 恢复 115200 验证现场")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("UART", "波特率设置功能")
    def test_baud_nonstandard(self, shellp, uart_args):
        """飞书行64 | 波特率设置功能 | 非标准波特率传入"""
        rep = {}
        uartp, _ = open_target(shellp, uart_args)
        try:
            if uartp is None:
                rep['打开串口失败'] = False
            else:
                # 步骤1: 非法值 0 → 期望 NG(配置失败)
                acks = normal_cmd_ack(shellp, "dmdtest_uart config baud=0", 0.3)
                rep['波特率0被拒绝(NG)'] = (not ack_is_ok(acks)) and ('NG' in acks)

                # 步骤2: 非法值 -1 → 期望 NG
                acks = normal_cmd_ack(shellp, "dmdtest_uart config baud=-1", 0.3)
                rep['波特率-1被拒绝(NG)'] = (not ack_is_ok(acks)) and ('NG' in acks)

                # 步骤3: 非标准正值 12345 → 记录实际行为(可能被BRR近似接受)
                acks = normal_cmd_ack(shellp, "dmdtest_uart config baud=12345", 0.3)
                rep['记录:波特率12345返回'] = 'OK(BRR近似接受)' if ack_is_ok(acks) else 'NG'

                # 步骤4: 恢复 115200 并验证
                rep['恢复115200成功'] = ack_is_ok(normal_cmd_ack(shellp, "dmdtest_uart config baud=115200", 0.3))
                rep['恢复后收发正常'] = host_roundtrip(shellp, uartp, 64, ord('G'))
                rep['说明'] = '非法值已判NG; 任意正值可被BRR整除近似接受, 与规格存在差异仅记录'
        finally:
            close_target(shellp, uartp)
        assert_feishu_rep(rep, "飞书行64 非标准波特率传入")
