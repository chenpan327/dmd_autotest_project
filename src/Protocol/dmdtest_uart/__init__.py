# coding: utf-8
"""
dmdtest_uart 协议包 — MCU 底软 UART 驱动测试的上位机协议实现

被测 MCU 固件运行 ll_drivers_tester 测试固件 (Shell 口下发 `dmdtest_uart` 命令集,
主机数据口与被测 UART TX/RX 交叉直连), 本包实现命令-应答协议、会话管理、
测量方法与错误注入, 供 BSP_APP UART 测试脚本层调用。

来源: 搬写自 mcu_ll_drivers_tester 仓库 ll_drivers_tester_host/python/uart_tester.py
(公共基础设施部分), 接口适配本框架三层架构; 测试点原理详见该仓库
ll_drivers_tester_host/doc/uart_test_principle.md。

模块划分:
    order_ary  — OrderAry 伪随机数据模型 (错位/丢字节/乱序敏感的比对基准)
    protocol   — 命令-应答协议 (normal_cmd_ack / ack_is_ok / stat 解析)
    session    — 被测串口会话管理 (open_target / close_target / switch_host_port)
    measure    — 测量方法 (吞吐量/CPU占用差分/统计查询/长度遍历/流校验)
    inject     — 错误注入与溢出探测 (奇偶/位长/停止位错配 / Break / ORE)

公共入参约定 (各函数 docstring 的 Args/Returns 均遵循此语义):
    shellp — Shell 口串口控制器 (SerialPortController 实例, enable_queue=True)
    uartp  — 被测 UART 数据口控制器 (UartPortController 实例, enable_queue=True)
    args   — 配置命名空间 (SimpleNamespace: port1/baud1/port2/uartx/seed/soak_seconds)
    rep    — 判定结果承载字典: 键值为 False 即该判定项失败, "记录:" 前缀键
             仅作记录, 由脚本层 assert_feishu_rep 统一断言
"""
from src.Protocol.dmdtest_uart.order_ary import OrderAry
from src.Protocol.dmdtest_uart.protocol import (
    calculate_transfer_time,
    normal_recv_data_to_ack,
    normal_cmd_ack,
    ack_is_ok,
    parse_stat_body,
)
from src.Protocol.dmdtest_uart.session import open_target, close_target, switch_host_port
from src.Protocol.dmdtest_uart.measure import (
    FEISHU_TPUT_BAUDS,
    FEISHU_STD_BAUDS,
    TPUT_RATIO_MIN,
    SEND_CPU_MAX_PCT,
    RECV_CPU_MAX_PCT,
    LOOP_RTT_MAX_MS,
    collect_bytes,
    verify_tx_task_stream,
    apply_format_both,
    query_stat,
    query_shell_prio,
    host_roundtrip,
    send_len_series,
    recv_len_series,
    measure_send_tput,
    measure_recv_tput,
    measure_duplex_tput,
    measure_send_cpu_at_baud,
    measure_recv_cpu_at_baud,
)
from src.Protocol.dmdtest_uart.inject import (
    inject_parity_mismatch,
    inject_databits_mismatch,
    inject_stopbits_mismatch,
    inject_break_and_recv_recover,
    inject_break_and_send_recover,
    overflow_probe,
)

__all__ = [
    'OrderAry',
    'calculate_transfer_time', 'normal_recv_data_to_ack', 'normal_cmd_ack',
    'ack_is_ok', 'parse_stat_body',
    'open_target', 'close_target', 'switch_host_port',
    'FEISHU_TPUT_BAUDS', 'FEISHU_STD_BAUDS', 'TPUT_RATIO_MIN',
    'SEND_CPU_MAX_PCT', 'RECV_CPU_MAX_PCT', 'LOOP_RTT_MAX_MS',
    'collect_bytes', 'verify_tx_task_stream', 'apply_format_both',
    'query_stat', 'query_shell_prio', 'host_roundtrip',
    'send_len_series', 'recv_len_series',
    'measure_send_tput', 'measure_recv_tput', 'measure_duplex_tput',
    'measure_send_cpu_at_baud', 'measure_recv_cpu_at_baud',
    'inject_parity_mismatch', 'inject_databits_mismatch', 'inject_stopbits_mismatch',
    'inject_break_and_recv_recover', 'inject_break_and_send_recover', 'overflow_probe',
]
