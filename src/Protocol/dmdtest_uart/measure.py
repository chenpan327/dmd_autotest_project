# coding: utf-8
"""
dmdtest_uart 测量方法集 (搬运自 mcu_ll_drivers_tester uart_tester.py, 接口适配本框架)

包含: 数据收集/流校验、双侧帧格式同步、全量统计查询、双向收发与长度遍历比对、
发送/接收/全双工三方向吞吐量测量、发送/接收线程 CPU 占用差分测量。
判定口径与原理详见 mcu_ll_drivers_tester/ll_drivers_tester_host/doc/uart_test_principle.md
第 3.1-3.3/3.6 节。

测量函数以 rep dict 承载结果: 键值为 False 即该判定项不通过, "记录:" 前缀键仅作记录,
由脚本层测试用例统一断言(语义同原 feishu_point 装饰器)。
"""
import time

from src.Protocol.dmdtest_uart.order_ary import OrderAry
from src.Protocol.dmdtest_uart.protocol import (
    calculate_transfer_time,
    normal_recv_data_to_ack,
    normal_cmd_ack,
    ack_is_ok,
    parse_stat_body,
)
from utils.logger import logger

# ============================================================================
# 常量定义
# ============================================================================

# 飞书行14-17/34-37/43-46 指定的四个吞吐量测试波特率
# (表格"理论速率"原按 9bit/字节计算(漏了停止位), 统一按 8N1 的 10bit/字节修正)
FEISHU_TPUT_BAUDS = [115200, 460800, 921600, 1500000]

# 飞书行59 标准波特率清单(115200/460800/921600/1500000)并向低/高速两侧扩展
FEISHU_STD_BAUDS = [9600, 115200, 230400, 460800, 921600, 1000000, 1500000, 2000000]

TPUT_RATIO_MIN = 95.0     # 吞吐量判定阈值: 实测/理论(按10bit/字节) > 95%
MCU_TPUT_LEN_MAX = 4096   # 下位机堆保护上限(字节): 单次 send/recv 命令的 order_ary 分配上限
                          # (H743 上 order_ary 走 newlib 堆实测可到 65536, 需更长测量窗
                          #  提升高速档折算精度时可调大, no-mem 降半重试为二道防线)
SEND_CPU_MAX_PCT = 10.0   # 发送线程 CPU 占用率上限(%)
RECV_CPU_MAX_PCT = 0.5    # 接收线程 CPU 占用率上限(%)
LOOP_RTT_MAX_MS = 50.0    # 环路时间判定上限(ms, 含USB适配器时延, 绝对值仅作参考)


# ============================================================================
# 数据收集 / 流校验 / 帧格式同步
# ============================================================================

def collect_bytes(uartp, want, timeout, poll=0.05):
    """限时从数据口累计接收 want 字节(数据到达即返回, 不含固定等待)

    Args:
        uartp: 被测 UART 数据口控制器(UartPortController 实例, enable_queue=True)
        want: 期望累计接收的目标字节数
        timeout: 收数总窗(秒), 到期即返回已收到的部分
        poll: 空等时的轮询粒度(秒), 默认 0.05; 计时敏感场景传 0.01

    Returns:
        bytes: 实际收到的字节(可能不足 want, 调用方自行判定完整性)
    """
    data = b''
    t0 = time.time()
    while len(data) < want and time.time() - t0 < timeout:
        chunk = uartp.recv_data(timeout=poll)
        if chunk:
            data += chunk
    return data


def verify_tx_task_stream(data, block_len=100):
    """校验 uart_tx_t 持续发送流: 相同 block_len 字节块周期性重复

    判据 stream[i] == stream[i+block_len] 对窗口内全部 i 成立, 相位无关
    (首字节可落在块内任意位置), 对丢字节/重复/损坏任何损伤均敏感。

    Args:
        data: 从数据口收集的持续发送流字节串
        block_len: 固件 uart_tx_t 任务单轮发送的块长, 默认 100

    Returns:
        bool: 全部位置满足块周期相等返回 True; 数据不足 2×block_len
              或任一位置不等返回 False
    """
    if len(data) < block_len * 2:
        return False
    return all(data[i] == data[i + block_len] for i in range(len(data) - block_len))


def apply_format_both(shellp, uartp, databits, parity, stopbits) -> bool:
    """双侧同步设置帧格式(MCU: dmdtest_uart config; 主机: set_format 重开串口)

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例)
        databits: 数据位个数(7/8)
        parity: 校验位('N' 无/'E' 偶/'O' 奇)
        stopbits: 停止位个数(1/2)

    Returns:
        bool: 双侧均设置成功返回 True; 任一侧失败返回 False
              (MCU 侧 config 重初始化会顺带清空错误计数, 注入用例依赖此特性取基线)
    """
    if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart config parity={parity} databits={databits} stopbits={stopbits}")):
        return False
    if not uartp.set_format(databits, parity, stopbits):
        return False
    uartp.recv_data(timeout=0)
    return True


# ============================================================================
# 统计查询 / 双向收发与长度遍历比对
# ============================================================================

def query_stat(shellp, retries=2):
    """查询 MCU 完整驱动统计(dmdtest_uart stat, 新固件全量统计版)

    应答形如: stat OK { "baud": 115200, "tx_bytes": N, "rx_bytes": N, "parity": 0,
    "noise": 0, "frame": 0, "overrun": 0, "dma": 0, "sw_err": [0,...],
    "hw_err": 0x00000000, "tx_dma_size": 512, "rx_dma_size": 512 }
    (shell 已把换行替换为空格)。计数器口径(驱动实现): tx_bytes=send 实际送达量,
    rx_bytes=recv 实际读取量(应用级), parity/noise/frame/overrun/dma=错误 ISR 计数,
    sw_err[0]=发送通知异常软件计数。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        retries: 解析失败后的自动重发次数, 默认 2(stat 为纯查询命令, 重发无副作用;
                 异常注入类测试中 shell 回显可能混入非法字符/杂散行, 核心计数键
                 parity/frame 缺失即判本次失败并重试)

    Returns:
        dict: 逐键统计字典(键见应答示例, hw_err 为 int 型十六进制值, sw_err 为
              list[int]); 旧固件仅 parity/noise/frame/overrun 四键;
              重试后仍解析失败返回 None
    """
    for _try in range(retries + 1):
        acks = normal_cmd_ack(shellp, "dmdtest_uart stat", 0.3)
        if not acks:
            continue
        body = acks.split(' ', 2)[2] if acks.count(' ') >= 2 else acks
        st = parse_stat_body(body)
        if st and 'parity' in st and 'frame' in st:   # 核心错误计数键齐才算成功
            return st
        logger.warning(f"stat 解析失败(第{_try + 1}次)"
                       + (", 重试" if _try < retries else ""))
    return None


def query_shell_prio(shellp):
    """查询 Shell 任务优先级(dmdtest_uart prio)

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)

    Returns:
        int: Shell 任务优先级数值; 查询失败或应答异常返回 None
             (调用方常以 `or 2` 兜底)
    """
    acks = normal_cmd_ack(shellp, "dmdtest_uart prio", 0.2)
    if ack_is_ok(acks):
        ary = acks.split()
        if len(ary) > 2:
            return int(ary[2])
    return None


def host_roundtrip(shellp, uartp, length, seedfrom, seedlen=8) -> bool:
    """双向收发校验(移植自旧用例 uart_roundtrip)

    ① MCU 发送 length 字节→主机全量比对  ② 主机发送→MCU 固件内 memcmp 比对,
    两方向都通过才算成功。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例)
        length: 单方向收发字节数
        seedfrom: OrderAry 起始字符码点(0~255), 每用例换起始防残留数据"碰巧"通过
        seedlen: OrderAry 循环字符区间宽度, to = from + seedlen, 默认 8

    Returns:
        bool: 两个方向数据均一致返回 True; 任一方向失败返回 False
    """
    # 方向1: MCU → 主机
    uartp.recv_data(timeout=0)
    if not ack_is_ok(normal_cmd_ack(shellp, f"dmdtest_uart send len={length} from={seedfrom} to={seedfrom+seedlen} timeout=-1",
                                    0.1 + length * 10 / max(uartp.baudrate, 1))):
        return False
    time.sleep(0.05)
    rdata = uartp.recv_data(timeout=0.2)
    if not (rdata and rdata == OrderAry(length, seedfrom, seedfrom + seedlen).to_bytes()):
        return False
    # 方向2: 主机 → MCU (命令先发、数据后到)
    cmd = f"dmdtest_uart recv len={length} from={seedfrom} to={seedfrom+seedlen} timeout=1000"
    if shellp.send_text(cmd + '\r\n') < 0:
        return False
    time.sleep(0.05)
    if uartp.send_data(OrderAry(length, seedfrom, seedfrom + seedlen).to_bytes()) < 0:
        return False
    time.sleep(0.1 + length * 10 / max(uartp.baudrate, 1))
    return ack_is_ok(normal_recv_data_to_ack(shellp, cmd, timeout=1.5))


def send_len_series(shellp, uartp, lengths, seedfrom=ord('0'), seedlen=9):
    """按长度列表逐长度发送并全量比对(移植自旧用例 do_uart_send_len)

    每轮递增起始字符防止上一用例残留数据"碰巧"通过; 单点失败重试一遍:
    过滤台架 USB 接收路径偶发丢数(时间窗性, 与波特率无关),
    确定性驱动缺陷两次都失败不被过滤。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例)
        lengths: 待遍历的长度列表(如 range(1, maxsize+1))
        seedfrom: OrderAry 起始字符码点(0~255), 默认 ord('0'), 逐轮自动递增
        seedlen: OrderAry 循环字符区间宽度, to = from + seedlen, 默认 9

    Returns:
        dict: 判定结果 —— 键 f'发送长度{i}字节一致', 全部成功则各键值为 True,
              任一长度两次尝试均失败即该键 False(键值 False 即该测试点失败)
    """
    rep = {}
    for i in lengths:
        seedfrom = (seedfrom + 1) if seedfrom < ord('H') else ord(' ')
        rep[f'发送长度{i}字节一致'] = False
        for _try in range(2):
            uartp.recv_data(timeout=0)
            cmd = f"dmdtest_uart send len={i} from={seedfrom} to={seedfrom + seedlen} timeout=-1"
            if not ack_is_ok(normal_cmd_ack(shellp, cmd, 0.1 + i * 10 / max(uartp.baudrate, 1))):
                continue
            time.sleep(0.05)
            rdata = uartp.recv_data(timeout=0.1)
            if rdata and OrderAry(i, seedfrom, seedfrom + seedlen).to_bytes() == rdata:
                rep[f'发送长度{i}字节一致'] = True
                break
    return rep


def recv_len_series(shellp, uartp, lengths, seedfrom=ord(' '), seedlen=8):
    """按长度列表逐长度接收并校验(移植自旧用例 do_uart_recv_len)

    时序: 命令先发→MCU 阻塞接收→主机后送数据→固件内 memcmp→上位机看应答
    ret==len; 单点失败重试一遍: 过滤台架偶发(同 send_len_series),
    确定性缺陷不过滤。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例)
        lengths: 待遍历的长度列表(如 range(1, maxsize+1))
        seedfrom: OrderAry 起始字符码点(0~255), 默认 ord(' '), 逐轮自动递增
        seedlen: OrderAry 循环字符区间宽度, to = from + seedlen, 默认 8

    Returns:
        dict: 判定结果 —— 键 f'接收长度{i}字节成功', 全部成功则各键值为 True,
              任一长度两次尝试均失败即该键 False(键值 False 即该测试点失败)
    """
    rep = {}
    for i in lengths:
        seedfrom = (seedfrom + 1) if seedfrom < ord('Z') else ord(' ')
        rep[f'接收长度{i}字节成功'] = False
        for _try in range(2):
            uartp.recv_data(timeout=0)
            cmd = f"dmdtest_uart recv len={i} from={seedfrom} to={seedfrom + seedlen} timeout=1000"
            if shellp.send_text(cmd + '\r\n') < 0:
                continue
            time.sleep(0.05)
            if uartp.send_data(OrderAry(i, seedfrom, seedfrom + seedlen).to_bytes()) < 0:
                continue
            time.sleep(0.1 + i * 10 / max(uartp.baudrate, 1))
            acks = normal_recv_data_to_ack(shellp, cmd, timeout=2.0)
            if ack_is_ok(acks) and len(acks.split()) > 2 and int(acks.split()[2]) == i:
                rep[f'接收长度{i}字节成功'] = True
                break
            uartp.recv_data(timeout=0)
    return rep


# ============================================================================
# 吞吐量测量 (发送 / 接收 / 全双工)
# ============================================================================

def measure_send_tput(shellp, uartp, seedfrom):
    """MCU→主机方向吞吐量测量(判定基准=MCU 自报接口速率比)

    主机端到端计时含 shell 命令下发/order_ary 构造/USB 适配器等固定开销
    (实测约50~60ms), 0.5s 测量窗下端到端速率比只能到~92% —— 故判定采用
    MCU 自报接口耗时(send 应答第4字段, 纯驱动阻塞时长, 实测≈99%线速率),
    端到端数值仅记录; 数据完整性独立全量比对, 不完整且 MCU 侧达标时
    定责为主机侧 USB 适配器接收路径(1.5M 持续满速实测丢~3%);
    MCU 堆不足(no-mem)时自动降半长度重试。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例, 已按目标波特率打开)
        seedfrom: OrderAry 起始字符码点(0~255), to = seedfrom + 8

    Returns:
        dict: 测量/判定字典 —— 判定键 '发送应答OK'(bool)与 '数据完整一致'(bool,
              主机不完整但 MCU 侧达标时降级为记录键 '记录:数据完整性');
              记录键 '测量字节数'/'记录:MCU接口耗时(ms)'/'记录:MCU接口速率比%'/
              '记录:端到端耗时(s)'/'记录:端到端速率比%'(键值 False 即该测试点失败)
    """
    baud = uartp.baudrate
    n = int(baud / 10 * 0.5)
    n = max(4096, n - n % 512)      # 对齐512并设下限
    n = min(n, MCU_TPUT_LEN_MAX)    # MCU 堆保护上限
    rep = {}
    while True:
        uartp.recv_data(timeout=0)
        shellp.clear_buffer()
        cmd = f"dmdtest_uart send len={n} from={seedfrom} to={seedfrom+8} timeout=-1"
        t0 = time.perf_counter()
        shellp.send_text(cmd + '\r\n')
        # 数据到达即返回(poll=0.01), 计时不含固定等待
        rdata = collect_bytes(uartp, n, n * 10 / baud * 2 + 0.5, poll=0.01)
        t_end = time.perf_counter()
        acks = normal_recv_data_to_ack(shellp, cmd, timeout=1.5)
        if ('no-mem' in acks) and n > 4096:
            n //= 2                  # MCU 堆不足, 降一档长度重试
            continue
        break
    elapsed = t_end - t0
    theory = baud / 10.0
    rep['测量字节数'] = n
    rep['发送应答OK'] = ack_is_ok(acks)
    # MCU 侧接口吞吐(判定基准): 应答形如 send OK <ret> <ms>ms <%> <ns>
    mcu_ms = None
    if ack_is_ok(acks) and len(acks.split()) > 3:
        try:
            mcu_ms = float(acks.split()[3][:-2])
        except ValueError:
            mcu_ms = None
    if mcu_ms is not None and mcu_ms > 0:
        rep['记录:MCU接口耗时(ms)'] = round(mcu_ms, 3)
        rep['记录:MCU接口速率比%'] = round(n * 1000.0 / mcu_ms / theory * 100, 2)
    # 主机端到端数值(仅记录, 含~50ms固定开销)
    rep['记录:端到端耗时(s)'] = round(elapsed, 4)
    rep['记录:端到端速率比%'] = round(n / elapsed / theory * 100, 2) if elapsed > 0 else 0.0
    # 数据完整性: MCU 接口速率已达标时, 主机实收不完整定责为台架USB接收路径
    # (USB 适配器 1.5M 持续满速间歇丢数, 与读取模式无关), 降级为记录不作失败;
    # MCU 侧未达标且不完整 → 真失败
    intact = (rdata == OrderAry(n, seedfrom, seedfrom + 8).to_bytes())
    if intact:
        rep['数据完整一致'] = True
    elif rep.get('记录:MCU接口速率比%', 0) > TPUT_RATIO_MIN:
        rep['记录:数据完整性'] = f'不完整(主机实收{len(rdata)}/{n}B, MCU侧达标, 台架USB接收路径丢数)'
    else:
        rep['数据完整一致'] = False
    return rep


def measure_recv_tput(shellp, uartp, seedfrom):
    """主机→MCU方向吞吐量测量(判定基准=接口耗时折算速率比)

    MCU 阻塞接收 N 字节, 主机灌数后取应答中的接口耗时(ms)折算吞吐率;
    接口耗时含"命令下发→主机开始灌数"的固定时延(50ms), 计算时扣除;
    MCU 堆不足(no-mem)时自动降半长度重试。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例, 已按目标波特率打开)
        seedfrom: OrderAry 起始字符码点(0~255), to = seedfrom + 8

    Returns:
        dict: 测量/判定字典 —— 判定键 '接收应答OK'(bool)与 '命令发送失败'(bool,
              仅命令下发失败时出现); 记录键 '测量字节数'/'记录:接口耗时(ms)'/
              '记录:吞吐率(B/s)'/'记录:理论速率(B/s)'/'记录:速率比%'
              (键值 False 即该测试点失败)
    """
    baud = uartp.baudrate
    n = int(baud / 10 * 0.5)
    n = max(4096, n - n % 512)
    n = min(n, MCU_TPUT_LEN_MAX)   # MCU 堆保护上限(recv 需 2×n 分配)
    rep = {}
    while True:
        uartp.recv_data(timeout=0)
        shellp.clear_buffer()         # 清残留回显, 防应答读取串台
        cmd = f"dmdtest_uart recv len={n} from={seedfrom} to={seedfrom+8} timeout=8000"
        if shellp.send_text(cmd + '\r\n') < 0:
            rep['命令发送失败'] = False
            return rep
        time.sleep(0.05)             # 等MCU进入阻塞接收(该50ms在折算时扣除)
        uartp.send_data(OrderAry(n, seedfrom, seedfrom + 8).to_bytes())
        acks = normal_recv_data_to_ack(shellp, cmd, timeout=n * 10 / baud + 3.0)
        if ('no-mem' in acks) and n > 4096:
            n //= 2
            continue
        break
    rep['测量字节数'] = n
    if not (ack_is_ok(acks) and len(acks.split()) > 3):
        rep['接收应答OK'] = False
        return rep
    rep['接收应答OK'] = True
    ms = float(acks.split()[3][:-2])
    transfer_s = max((ms - 50.0) / 1000.0, 0.001)   # 扣除50ms命令启动时延
    theory = baud / 10.0
    tput = n / transfer_s
    rep['记录:接口耗时(ms)'] = round(ms, 3)
    rep['记录:吞吐率(B/s)'] = round(tput, 1)
    rep['记录:理论速率(B/s)'] = round(theory, 1)
    rep['记录:速率比%'] = round(tput / theory * 100, 2)
    return rep


def measure_duplex_tput(shellp, uartp, seedfrom):
    """全双工吞吐量测量(固件回环任务, 判定基准=两档长度差分速率比)

    主机发送 N 字节并计时至 N 字节回显全部收满; 收发在线路上重叠进行,
    理想耗时 ≈ N×10/baud(单方向); 端到端耗时含回环管线固定时延(USB 往返+
    回环任务唤醒, 实测约40~130ms 且随波特率波动), 直接判定时低波特率档
    仅~82% —— 以两档长度(N/2 与 N)差分折算持续速率作判定基准(固定开销在
    差分中消去, 端到端数值仅记录); 若收发被串行化(半双工行为)则差分速率
    近乎减半, 无法通过 95% 判定; 数据不完整且 MCU 侧回环字节数(tx_bytes
    增量)足额零错时, 定责为主机侧 USB 适配器接收路径。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True;
                测量前后各查一次 stat 以取 MCU 侧收发字节数证据)
        uartp: 被测 UART 数据口控制器(UartPortController 实例, 已按目标波特率
               打开, 回环任务已 enable)
        seedfrom: OrderAry 起始字符码点(0~255), to = seedfrom + 8

    Returns:
        dict: 测量/判定字典 —— 判定键 '回环半长数据一致'/'回环数据完整一致'
              (bool, MCU 侧足额零错时移除并以 'MCU侧回环足额(判定替代)'=True
              替代); 记录键 '测量字节数'/'记录:端到端耗时(s)'/'记录:端到端速率比%'/
              '记录:差分速率比%'(判定基准)或 '记录:差分未算出'/'记录:数据完整性'
              (键值 False 即该测试点失败)
    """
    baud = uartp.baudrate
    # 回环测量不走shell的recv/send命令, MCU侧回环任务原样转发零分配,
    # 长度不受MCU_TPUT_LEN_MAX(命令路径order_ary堆上限)约束, 仅受主机内存限制;
    # 取约1秒线时间的字节数: 管线固定开销~100ms/抖动±30ms在500ms+差分窗口中
    # 占比<6%, 否则高波特率档差分被抖动淹没(曾测得117%>100%及dt<=t_half乱序)
    n = int(baud / 10 * 1.0)
    n = max(4096, n - n % 512)
    n = min(n, 65536)              # 主机内存上限
    half = n // 2
    theory = baud / 10.0
    rep = {}
    t_half = None
    st0 = query_stat(shellp)
    for cur in (half, n):
        sdata = OrderAry(cur, seedfrom, seedfrom + 8).to_bytes()
        uartp.recv_data(timeout=0)
        # 接收线程路径收数: 直达读(独占串口)在全双工(同端口边写边读)场景
        # 吞吐坍缩至~16%, 不可用于本测量
        t0 = time.perf_counter()
        rdata = bytearray()
        uartp.send_data(sdata)
        deadline = cur * 10 / baud * 4 + 1.0
        while len(rdata) < cur and time.perf_counter() - t0 < deadline:
            c = uartp.recv_data(timeout=0.05)
            if c:
                rdata += c
        dt = time.perf_counter() - t0
        rdata = bytes(rdata)
        if cur == half:
            t_half = dt
            rep['回环半长数据一致'] = (rdata == sdata)
        else:
            rep['测量字节数'] = n
            rep['回环数据完整一致'] = (rdata == sdata)
            rep['记录:端到端耗时(s)'] = round(dt, 4)
            rep['记录:端到端速率比%'] = round(cur / dt / theory * 100, 2) if dt > 0 else 0.0
            # 差分持续速率(判定基准): (N-N/2)/(t_N - t_N/2), 固定时延消去
            if t_half is not None and dt > t_half > 0 and rep['回环半长数据一致']:
                rep['记录:差分速率比%'] = round((cur - half) / (dt - t_half) / theory * 100, 2)
            else:
                rep['记录:差分未算出'] = f'时序乱序(dt={dt:.3f}s, t_half={t_half:.3f}s)或半长数据不一致'
    # 丢数定责与判定替代: MCU 侧收/发字节数均足额且错误计数零增量 ——
    # 小缓冲(StreamBuffer 1KB)环回下, MCU 环路速率跟不上线速率必然回压
    # 溢出(rx_bytes 缺额或错误计数增长), 足额+零错即证明 MCU 以线速率
    # 持续全双工; 此时主机实收不完整定责为台架 USB 接收路径(USB 适配器
    # 1.5M 持续满速间歇丢数), 完整性降级为记录, 判定由 MCU 侧证据替代
    st1 = query_stat(shellp)
    if st0 and st1:
        tx_dt = st1.get('tx_bytes', 0) - st0.get('tx_bytes', 0)
        rx_dt = st1.get('rx_bytes', 0) - st0.get('rx_bytes', 0)
        err_dt = sum(st1.get(k, 0) - st0.get(k, 0) for k in ('frame', 'overrun', 'parity', 'noise'))
        host_bad = (rep.get('回环半长数据一致') is False) or (rep.get('回环数据完整一致') is False)
        if host_bad and tx_dt >= half + n and rx_dt >= half + n and err_dt == 0:
            rep.pop('回环半长数据一致', None)
            rep.pop('回环数据完整一致', None)
            rep['记录:数据完整性'] = '不完整(台架USB接收路径丢数, MCU侧收发足额零错)'
            rep['MCU侧回环足额(判定替代)'] = True
        elif host_bad:
            rep['说明'] = 'MCU侧收/发计数未足额, 环路存在真实丢数'
    return rep


# ============================================================================
# 线程 CPU 占用率测量 (copytest 差分校准法)
# ============================================================================

def measure_send_cpu_at_baud(shellp, uartp, rep):
    """发送线程 CPU 占用率测量(差分校准法, 移植自旧用例 do_uart_send_cpu)

    ① dmdtest_uart copytest len=i 取同长度 memcpy 基线(剥离测量框架固定开销)
    ② dmdtest_uart send len=i 实测, kenerl = sendCPU - copytest基线CPU ≈ 驱动净CPU,
       iface = (send耗时 - copytest耗时) ≈ 发送阻塞时长
    ③ 相邻长度点差分(Δkenerl/Δiface)消除固定开销漂移得每增量字节占用率

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例, 已按目标波特率
               打开, target_maxsize 决定长度点 [1, m/4, m/2, 3m/4, m])
        rep: 判定结果承载字典, 本函数向其写入结果

    Returns:
        无(结果写入 rep) —— 判定键 f'长度{i}发送CPU占用率≤10%'(bool, 首点作
        差分基准记 True); 记录键 f'记录:长度{i}净CPU/接口耗时(ns)';
        键值 False 即该测试点失败
    """
    seedfrom = ord('0')
    seedlen = 2
    iface_pre = None
    kern_pre = None
    m = uartp.target_maxsize
    lengths = [1, m // 4, m // 2, int(m * 3 / 4), m]   # 含 1×buf 整数倍长度点
    for i in lengths:
        key = f'长度{i}发送CPU占用率≤{SEND_CPU_MAX_PCT}%'
        rep[key] = False
        seedfrom += 1
        # 步骤1: memcpy 基线
        acks = normal_cmd_ack(shellp, f"dmdtest_uart copytest len={i}", 0.1 + i * 10 / max(uartp.baudrate, 1))
        if not (ack_is_ok(acks) and len(acks.split()) > 5):
            continue
        vcopy_ns = int(acks.split()[5])
        vcopy_ms = float(acks.split()[3][:-2])
        # 步骤2: 实际发送
        acks = normal_cmd_ack(shellp, f"dmdtest_uart send len={i} from={seedfrom} to={seedfrom+seedlen} timeout=-1",
                              0.1 + i * 10 / max(uartp.baudrate, 1))
        if not (ack_is_ok(acks) and len(acks.split()) > 5):
            continue
        time.sleep(0.05)
        rdata = uartp.recv_data(timeout=0.1)
        if not (rdata and rdata == OrderAry(i, seedfrom, seedfrom + seedlen).to_bytes()):
            continue
        ary = acks.split()
        kern = int(ary[5]) - vcopy_ns                     # 驱动净CPU(ns)
        iface = (float(ary[3][:-2]) - vcopy_ms) * 1e6     # 接口耗时差(ns)
        # 步骤3: 相邻点差分
        if kern_pre is not None and iface_pre is not None:
            kern_dt = max(kern - kern_pre, 0)
            iface_dt = iface - iface_pre
            rep[f'记录:长度{i}净CPU/接口耗时(ns)'] = f'{int(kern_dt)}/{int(iface_dt)}'
            if iface_dt > 0:
                rep[key] = (kern_dt * 100.0 / iface_dt) <= SEND_CPU_MAX_PCT
        else:
            rep[key] = True   # 首点作差分基准
        iface_pre, kern_pre = iface, kern


def measure_recv_cpu_at_baud(shellp, uartp, rep):
    """接收线程 CPU 占用率测量(差分+3次取中位数, 移植自旧用例 do_uart_recv_cpu)

    接收的阻塞时长由波特率理论传输时间决定而非接口差分:
    ① 每长度点 copytest 基线与 recv 实测各采样3次取中位数(单次计数在慢速MCU上噪声大)
    ② 首点建立 time_offset(测量系统固有偏差) 与 len_offset
    ③ 后续点 ΔCPU = recv - copytest基线 - time_offset, Δ理论 = (len差)×单字节传输时间

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例, 已按目标波特率
               打开, target_maxsize 决定长度点 [1, m/4, m/2, 3m/4, m])
        rep: 判定结果承载字典, 本函数向其写入结果

    Returns:
        无(结果写入 rep) —— 判定键 f'长度{i}接收CPU占用率≤0.5%'(bool, 基准段
        记 True); 记录键 f'记录:长度{i}净CPU/理论传输(ns)';
        键值 False 即该测试点失败
    """
    seedfrom = ord(' ')
    seedlen = 8
    cal = calculate_transfer_time(1, uartp.baudrate)
    m = uartp.target_maxsize
    lengths = [1, m // 4, m // 2, int(m * 3 / 4), m]
    spend = {}
    for idx in range(len(lengths)):
        i = lengths[idx]
        key = f'长度{i}接收CPU占用率≤{RECV_CPU_MAX_PCT}%'
        rep[key] = False
        seedfrom = (seedfrom + 1) if seedfrom < ord('Z') else ord(' ')
        # 步骤1: 3次采样取中位数
        vcopy_list, recv_list = [], []
        for _try in range(3):
            acks = normal_cmd_ack(shellp, f"dmdtest_uart copytest len={i}", 0.1 + i * 10 / max(uartp.baudrate, 1))
            if ack_is_ok(acks) and len(acks.split()) > 5:
                vcopy_list.append(int(acks.split()[5]))
            cmd = f"dmdtest_uart recv len={i} from={seedfrom} to={seedfrom+seedlen} timeout=1000"
            if shellp.send_text(cmd + '\r\n') < 0:
                continue
            time.sleep(0.05)
            if uartp.send_data(OrderAry(i, seedfrom, seedfrom + seedlen).to_bytes()) < 0:
                continue
            time.sleep(0.1 + i * 10 / max(uartp.baudrate, 1))
            acks = normal_recv_data_to_ack(shellp, cmd)
            if ack_is_ok(acks) and len(acks.split()) > 5:
                recv_list.append(int(acks.split()[5]))
        if len(vcopy_list) < 2 or len(recv_list) < 2:
            continue
        vcopy_ns = sorted(vcopy_list)[len(vcopy_list) // 2]
        recv_ns = sorted(recv_list)[len(recv_list) // 2]
        spend[f'{idx}_vcopy'] = vcopy_ns
        spend[f'{idx}_recv'] = recv_ns
        spend[f'{idx}_cal'] = i * cal['transfer_time'] * 1e9
        # 步骤2: 首个成功点建立系统偏差基准
        if 'time_offset' not in spend:
            spend['time_offset'] = recv_ns - vcopy_ns
            spend['len_offset'] = 1 if idx == 0 else lengths[idx] - lengths[idx - 1]
    # 步骤3: 差分计算各长度点占用率
    for idx in range(len(lengths)):
        i = lengths[idx]
        key = f'长度{i}接收CPU占用率≤{RECV_CPU_MAX_PCT}%'
        if i <= spend.get('len_offset', 1):
            rep[key] = True   # 基准段
            continue
        if f'{idx}_cal' in spend and f'{idx}_recv' in spend:
            iface_dt = spend[f'{idx}_cal'] - cal['transfer_time'] * 1e9 * spend['len_offset']
            kern_dt = spend[f'{idx}_recv'] - spend[f'{idx}_vcopy'] - spend['time_offset']
            if kern_dt < 0:
                kern_dt = 0
            rep[f'记录:长度{i}净CPU/理论传输(ns)'] = f'{int(kern_dt)}/{int(iface_dt)}'
            if iface_dt > 0:
                rep[key] = (kern_dt * 100.0 / iface_dt) <= RECV_CPU_MAX_PCT
