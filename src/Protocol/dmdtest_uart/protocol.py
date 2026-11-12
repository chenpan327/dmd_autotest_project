# coding: utf-8
"""
dmdtest_uart 命令-应答协议 (搬运自 mcu_ll_drivers_tester uart_tester.py, 接口适配本框架)

被测 MCU 固件运行 ll_drivers_tester 测试固件, 经 Shell 口下发 `dmdtest_uart` 命令集
(open/close/config/stat/send/recv/copytest/enable/disable/prio, key=value 参数格式)。

命令-应答协议: 应答定位"以命令动词开头且带 OK/NG、其后出现 '>>' 提示符"的行,
循环累积接收直至应答到齐或超时 (容错回显污染/应答延迟到达, 不依赖严格三行结构);
命令等待延时 = 0.1 + 数据量×10/波特率 (自适应)。

shellp 为 Shell 口串口控制器 (src.Physical.Serial.SerialPortController 实例, enable_queue=True)。
原理详见 mcu_ll_drivers_tester/ll_drivers_tester_host/doc/uart_test_principle.md 第 2.1/2.3 节。
"""
import re
import time

from utils.logger import logger


def calculate_transfer_time(data_size, baudrate, data_bits=8, parity_bits=0, stop_bits=1):
    """计算按当前帧格式传输 data_size 字节所需的理论时间(8N1 时每字节 10bit)

    Args:
        data_size: 数据字节数
        baudrate: 波特率(bps)
        data_bits: 数据位个数, 默认 8
        parity_bits: 校验位个数(无校验为 0), 默认 0
        stop_bits: 停止位个数, 默认 1

    Returns:
        dict: bits_per_byte=每字节总位数(1起始位+数据+校验+停止)/
              total_bits=总位数/transfer_time=理论传输耗时(秒)/
              bytes_per_second=理论字节速率(B/s)
    """
    bits_per_byte = 1 + data_bits + parity_bits + stop_bits  # 1 起始位
    total_bits = data_size * bits_per_byte
    return {
        'bits_per_byte': bits_per_byte,
        'total_bits': total_bits,
        'transfer_time': total_bits / baudrate,
        'bytes_per_second': baudrate / bits_per_byte
    }


def normal_recv_data_to_ack(shellp, cmd: str, timeout=2.0) -> str:
    """读取命令应答: 定位以命令动词开头且带 OK/NG 的应答行, 取其后出现提示符的行

    应答行形如 "send OK 8 450.0ms 0.1% 120000" / "recv NG 0 ..."; 应答在回显之后
    延迟到达(长传输/阻塞命令), 循环累积接收直至"应答行+其后'>>'提示符"到齐或超时,
    避免只读到回显的前段帧; 异常注入类测试中 shell 回显可能混入非法字符/杂散行、
    命令回显行本身可能被污染, 同样不依赖严格三行结构。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        cmd: 已下发的完整命令文本(如 "dmdtest_uart send len=8 ... timeout=0"),
             以其第 2 个空格分段作为应答行定位动词
        timeout: 应答读取总窗(秒); 到期未获"应答行+提示符"即放弃

    Returns:
        str: 有效应答行文本; 未取到返回 ""
    """
    verb = cmd.split()[1] if len(cmd.split()) > 1 else ''
    if not verb:
        return ""
    text = ''
    t0 = time.time()
    while time.time() - t0 < timeout:
        data = shellp.recv_data(timeout=0.2)
        if data:
            text += data.decode('utf-8', errors='ignore')
            lines = [ln.strip() for ln in text.splitlines()]
            for i in range(len(lines) - 1, -1, -1):   # 从后往前: 多条命中取最新
                s = lines[i]
                if s.startswith(verb + ' ') and (' OK' in s or ' NG' in s):
                    if any('>>' in x for x in lines[i + 1:]):
                        if text.strip():
                            logger.info(f"[{shellp.port} RX] {' '.join(text.split())}")
                        return s
    if text.strip():
        logger.info(f"[{shellp.port} RX(未获完整应答)] {' '.join(text.split())}")
    return ""


def normal_cmd_ack(shellp, cmd: str, delay=0.3, ack_timeout=2.0) -> str:
    """发送命令并获取应答: 清残留→发命令→自适应延时→循环读应答

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        cmd: 待下发命令文本(不含换行, 函数自动补 "\r\n")
        delay: 命令发出后的固定等待(秒); 长传输/阻塞命令按
               "0.1 + 数据量×10/波特率" 自适应给值
        ack_timeout: 应答读取总窗(秒); 命令被高优先级任务压制时 shell 需等其
                     让出(满速后台任务前 3s 不让出, 实测应答约 2.75s 到达),
                     此场景须给 ≥4.5

    Returns:
        str: 有效应答行(语义同 normal_recv_data_to_ack);
             命令发送失败或超时未获应答返回 ""
    """
    shellp.clear_buffer()
    if (shellp.send_text(cmd + "\r\n") > 0):
        time.sleep(delay)
        return normal_recv_data_to_ack(shellp, cmd, timeout=ack_timeout)
    return ""


def ack_is_ok(ack: str) -> bool:
    """判断应答行是否为 OK 应答

    Args:
        ack: normal_cmd_ack / normal_recv_data_to_ack 返回的应答行

    Returns:
        bool: 应答行含 " OK " 返回 True; NG 应答、空串、无应答返回 False
    """
    return ack.find(" OK ") >= 0


def parse_stat_body(body: str):
    """解析 dmdtest_uart stat 应答体为字典 (query_stat 的正则内核, 独立导出便于单测)

    新格式: JSON 风格统计文本逐键正则抽取(hw_err 为 0x 十六进制字面量,
    严格 JSON 不支持该写法); 旧固件: "stat OK <pe> <ne> <fe> <ore>" 4 计数兼容映射。

    Args:
        body: stat 应答的有效载荷(去掉 "stat OK " 前缀后的部分);
              新固件为单行 JSON 风格统计文本, 旧固件为 4 个十进制计数

    Returns:
        dict: 逐键统计字典 —— 新固件含 baud/tx_bytes/rx_bytes/parity/noise/
              frame/overrun/dma/hw_err/tx_dma_size/rx_dma_size(int)与
              sw_err(list[int]); 旧固件仅 parity/noise/frame/overrun 四键;
              无法解析返回 None
    """
    st = {}
    # 新格式: JSON 风格文本逐键正则抽取 (hw_err 为 0x 十六进制字面量, 严格 JSON 不支持该写法)
    for key in ('baud', 'tx_bytes', 'rx_bytes', 'parity', 'noise', 'frame',
                'overrun', 'dma', 'hw_err', 'tx_dma_size', 'rx_dma_size'):
        m = re.search(r'"%s"\s*:\s*(0[xX][0-9A-Fa-f]+|\d+)' % key, body)
        if m:
            v = m.group(1)
            st[key] = int(v, 16) if v[:2].lower() == '0x' else int(v)
    m = re.search(r'"sw_err"\s*:\s*\[([^\]]*)\]', body)
    if m:
        try:
            st['sw_err'] = [int(x) for x in m.group(1).replace(' ', '').split(',') if x]
        except ValueError:
            pass
    if st:
        return st
    # 旧固件兼容: stat OK <pe> <ne> <fe> <ore>
    try:
        vals = [int(x) for x in body.split()]
        if len(vals) >= 4:
            return {'parity': vals[0], 'noise': vals[1], 'frame': vals[2], 'overrun': vals[3]}
    except ValueError:
        pass
    return None
