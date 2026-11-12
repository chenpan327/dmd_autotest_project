# coding: utf-8
"""
dmdtest_uart 被测串口会话管理 (搬运自 mcu_ll_drivers_tester uart_tester.py, 接口适配本框架)

每个测试点自包含"打开→测试→关闭"全流程:
    open_target(shellp, args, baud)  → dmdtest_uart open + config baud=... + 主机数据口同波特率打开
                                       返回 (uartp, maxsize), maxsize 来自 open 应答第4字段
    close_target(shellp, uartp)      → 停数据口 + dmdtest_uart close
    switch_host_port(args, uartp, b) → 换波特率: 关闭旧数据口对象并按新波特率重建
                                       (pyserial 波特率热切换不可靠, 直接重建对象)
"""
import time

from src.Physical.Serial.SerialPortController import UartPortController
from src.Protocol.dmdtest_uart.protocol import normal_cmd_ack, ack_is_ok
from utils.logger import logger


def open_target(shellp, args, baud=115200):
    """打开被测串口公共流程: dmdtest_uart open → config baud=... → 主机数据口同波特率打开

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        args: 配置命名空间(SimpleNamespace), 本函数使用 uartx(被测 UART 编号)
              与 port2(主机数据口 COM 号)
        baud: 目标波特率, 同步作用于 MCU 侧 config 与主机数据口, 默认 115200

    Returns:
        tuple: (uartp, maxsize) —— uartp 为已连接的 UartPortController
               (target_uart/target_maxsize 已回填); maxsize 为被测端 DMA 单块
               上限(open 应答第 4 字段); 打开失败返回 (None, 0)
    """
    acks = normal_cmd_ack(shellp, f"dmdtest_uart open {args.uartx}")
    if not ack_is_ok(acks):
        logger.error(f"dmdtest_uart open {args.uartx} 失败: {acks}")
        return None, 0
    if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart config baud={baud}")):
        logger.error(f"dmdtest_uart config baud={baud} 失败")
        normal_cmd_ack(shellp, "dmdtest_uart close")
        return None, 0
    uartp = UartPortController(port=args.port2, baudrate=baud, target_uart=args.uartx)
    uartp.target_maxsize = int(acks.split()[3])   # 应答第4字段 = DMA单块上限
    uartp.connect()
    time.sleep(0.1)
    uartp.recv_data(timeout=0)   # 清刚打开时的残留
    return uartp, uartp.target_maxsize


def close_target(shellp, uartp):
    """关闭被测串口会话: 停主机数据口 + dmdtest_uart close

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 待关闭的主机数据口(UartPortController 实例), None 时仅下发 close 命令

    Returns:
        无
    """
    if uartp:
        uartp.disconnect()
    normal_cmd_ack(shellp, "dmdtest_uart close")


def switch_host_port(args, uartp, baud):
    """主机数据口换波特率: 关闭旧串口对象并按新波特率重建(pyserial 热切换不可靠)

    Args:
        args: 配置命名空间(SimpleNamespace), 本函数使用 port2(主机数据口 COM 号)
        uartp: 当前数据口对象, 其 target_uart/target_maxsize 被新对象继承,
               旧对象在本函数内被关闭(不可再使用)
        baud: 新波特率(bps)

    Returns:
        UartPortController: 按新波特率重建且已连接的数据口对象
    """
    uartp.disconnect()
    newp = UartPortController(port=args.port2, baudrate=baud, target_uart=uartp.target_uart)
    newp.target_maxsize = uartp.target_maxsize
    newp.connect()
    time.sleep(0.1)
    return newp
