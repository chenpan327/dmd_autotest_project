# coding: utf-8
"""
dmdtest_uart 错误注入 / 溢出探测 (搬运自 mcu_ll_drivers_tester uart_tester.py, 接口适配本框架)

三种帧错配注入方式 (MCU 侧保持配置, 主机侧单侧改格式) 与三段式流程:
    注入 (计数增长 + 污染数据未被全量接收) → 恢复 (收发正常 + 计数稳定) → 清理 (双侧 8N1)
Break 注入: 250ms 持续低电平模拟对端复位/拔插/干扰 (物理拔插的可自动化代理)。
溢出探测: MCU 停读 + 主机满速灌入, 以"计数增量记录 + recv 形态记录 + 恢复能力判定"代替
缓冲策略语义断言。
原理详见 mcu_ll_drivers_tester/ll_drivers_tester_host/doc/uart_test_principle.md 第 3.4/3.5 节。

注入函数以 rep dict 承载结果 (键值 False 即判定失败, "记录:" 前缀仅记录),
由脚本层测试用例统一断言; Break/溢出函数返回元组或 rep, 语义见各 docstring。
"""
import time

from src.Protocol.dmdtest_uart.order_ary import OrderAry
from src.Protocol.dmdtest_uart.protocol import (
    normal_recv_data_to_ack,
    normal_cmd_ack,
    ack_is_ok,
)
from src.Protocol.dmdtest_uart.measure import apply_format_both, query_stat, host_roundtrip
from utils import serial_trace


def inject_parity_mismatch(shellp, uartp, testlen, seedfrom):
    """奇偶校验错配注入(飞书行53/70/77 共用)

    MCU=8E1, 主机单侧=8O1 —— 偶/奇校验位互补, 每字节必然 PE。
    三段式: 注入(PE 计数增长 + 污染数据未被全量接收) → 恢复(收发正常 +
    计数稳定) → 清理(双侧恢复 8N1)。注意: MCU 侧 format 重初始化会清空
    错误计数, 恰好提供干净基线; 自愈驱动会把短超时 recv 等满,
    主机须等 0.5s 再读应答。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例)
        testlen: 注入数据长度(字节), 同时用作恢复验证长度
        seedfrom: OrderAry 起始字符码点(0~255), 注入与恢复各用 seedfrom/seedfrom+1

    Returns:
        dict: 判定/记录字典 —— 判定键 'PE计数增长'/'污染数据未被全量接收'/
              '错配恢复后收发正常'/'恢复后PE计数稳定' 及配置失败键(bool);
              记录键 '记录:注入后PE增量'(键值 False 即该测试点失败)
    """
    rep = {}
    # 阶段1: 双侧配置 8E1(计数清零, 建立基线)
    if not apply_format_both(shellp, uartp, 8, 'E', 1):
        rep['配置8E1失败'] = False
        return rep
    stat0 = query_stat(shellp)
    if stat0 is None:
        rep['stat查询失败'] = False
        return rep
    # 阶段2: 仅主机侧改 8O1 后发数据 → MCU 逐字节 PE
    if not uartp.set_format(8, 'O', 1):
        rep['主机侧设置8O1失败'] = False
    else:
        cmd = f"dmdtest_uart recv len={testlen} from={seedfrom} to={seedfrom+8} timeout=200"   # 短超时接收
        shellp.send_text(cmd + '\r\n')
        time.sleep(0.05)
        uartp.send_data(OrderAry(testlen, seedfrom, seedfrom + 8).to_bytes())
        time.sleep(0.5)                                             # 等自愈驱动等满超时
        acks = normal_recv_data_to_ack(shellp, cmd, timeout=1.0)
        stat1 = query_stat(shellp)
        pe_delta = (stat1['parity'] - stat0['parity']) if stat1 else -1
        rep['PE计数增长'] = pe_delta > 0
        rep['记录:注入后PE增量'] = pe_delta
        full_accept = False
        if ack_is_ok(acks):
            ary = acks.split()
            full_accept = len(ary) > 2 and int(ary[2]) == testlen
        rep['污染数据未被全量接收'] = not full_accept
    # 阶段3: 主机改回 8E1 → 双向收发恢复且 PE 计数不再增长
    if uartp.set_format(8, 'E', 1):
        statA = query_stat(shellp)
        ok = host_roundtrip(shellp, uartp, testlen, seedfrom + 1)
        statB = query_stat(shellp)
        rep['错配恢复后收发正常'] = ok
        rep['恢复后PE计数稳定'] = (statA is not None and statB is not None
                               and statB['parity'] == statA['parity'])
    else:
        rep['主机侧恢复8E1失败'] = False
    # 现场清理: 双侧恢复默认 8N1
    apply_format_both(shellp, uartp, 8, 'N', 1)
    return rep


def inject_databits_mismatch(shellp, uartp, testlen, seedfrom):
    """位长错配注入(MCU=7N1, 主机=8N1, 飞书行55/70/79 共用)

    MCU 在第9位采样停止位, 而 ASCII 字符最高位恒为 0, 每字节必然帧错误(FE),
    即"注入停止位错误"。恢复阶段由从机(MCU)改回 8N1 —— config 重初始化
    复位接收通路并重发 recv 重新拉起接收(阶段2 的 recv 已因错配出错退出
    接收状态), 再验证双向收发与 FE 计数稳定; 结束时双侧恢复 8N1。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例)
        testlen: 注入数据长度(字节), 同时用作恢复验证长度
        seedfrom: OrderAry 起始字符码点(0~255), 注入与恢复各用 seedfrom/seedfrom+1

    Returns:
        dict: 判定/记录字典 —— 判定键 'FE计数增长'/'污染数据未被全量接收'/
              '重发recv接收恢复正常'/'恢复后发送数据一致'/'恢复后FE计数稳定'
              及配置失败键(bool); 记录键 '记录:注入后FE增量'
              (键值 False 即该测试点失败)
    """
    rep = {}
    # 阶段1: MCU 7N1(format 重初始化清零计数), 主机暂同步 7N1
    if not apply_format_both(shellp, uartp, 7, 'N', 1):
        rep['配置7N1失败'] = False
        return rep
    stat0 = query_stat(shellp)
    if stat0 is None:
        rep['stat查询失败'] = False
        return rep
    # 阶段2: 仅主机侧改 8N1 发数据 → 停止位采样落在 D7(恒0) → 每字节 FE
    if not uartp.set_format(8, 'N', 1):
        rep['主机侧设置8N1失败'] = False
    else:
        cmd = f"dmdtest_uart recv len={testlen} from={seedfrom} to={seedfrom+8} timeout=200"
        shellp.send_text(cmd + '\r\n')
        time.sleep(0.05)
        uartp.send_data(OrderAry(testlen, seedfrom, seedfrom + 8).to_bytes())
        time.sleep(0.5)
        acks = normal_recv_data_to_ack(shellp, cmd, timeout=1.0)
        stat1 = query_stat(shellp)
        fe_delta = (stat1['frame'] - stat0['frame']) if stat1 else -1
        rep['FE计数增长'] = fe_delta > 0
        rep['记录:注入后FE增量'] = fe_delta
        full_accept = False
        if ack_is_ok(acks):
            ary = acks.split()
            full_accept = len(ary) > 2 and int(ary[2]) == testlen
        rep['污染数据未被全量接收'] = not full_accept
    # 阶段3: 从机改回 8N1 → 重发 recv 恢复且 FE 计数稳定
    # 阶段2 的 recv 已因错配出错退出接收状态, 从机 config 改回 8N1 重初始化
    # 接收通路(错误计数随之清零, statA 于重配后采样即恢复期基线),
    # 须重发 dmdtest_uart recv 重新拉起接收(命令先发、数据后到);
    # 再由 MCU 发送一笔数据, 双向均恢复且 FE 计数不再增长
    if not ack_is_ok(normal_cmd_ack(shellp, "dmdtest_uart config parity=N databits=8 stopbits=1")):
        rep['从机侧恢复8N1失败'] = False
    else:
        statA = query_stat(shellp)
        # 重发 recv(接收方向): 校验重新进入接收状态且数据一致
        rcmd = f"dmdtest_uart recv len={testlen} from={seedfrom+1} to={seedfrom+9} timeout=1000"
        recv_ok = False
        if shellp.send_text(rcmd + '\r\n') >= 0:
            time.sleep(0.05)
            if uartp.send_data(OrderAry(testlen, seedfrom + 1, seedfrom + 9).to_bytes()) >= 0:
                time.sleep(0.1 + testlen * 10 / max(uartp.baudrate, 1))
                acks = normal_recv_data_to_ack(shellp, rcmd, timeout=1.5)
                recv_ok = ack_is_ok(acks) and len(acks.split()) > 2 and int(acks.split()[2]) == testlen
        # 发送方向: MCU 发同长度数据由主机全量比对
        uartp.recv_data(timeout=0)
        acks = normal_cmd_ack(shellp, f"dmdtest_uart send len={testlen} from={seedfrom+1} to={seedfrom+9} timeout=-1",
                              0.1 + testlen * 10 / max(uartp.baudrate, 1))
        time.sleep(0.05)
        rdata = uartp.recv_data(timeout=0.2)
        rep['重发recv接收恢复正常'] = recv_ok
        rep['恢复后发送数据一致'] = (ack_is_ok(acks) and bool(rdata)
                               and rdata == OrderAry(testlen, seedfrom + 1, seedfrom + 9).to_bytes())
        statB = query_stat(shellp)
        rep['恢复后FE计数稳定'] = (statA is not None and statB is not None
                               and statB['frame'] == statA['frame'])
    apply_format_both(shellp, uartp, 8, 'N', 1)
    return rep


def inject_stopbits_mismatch(shellp, uartp, burst, seedfrom):
    """停止位错配满载容错场景(MCU=8N2, 主机=8N1, 飞书行79 附加场景)

    UART 接收器只检查第一个停止位采样点, 背靠背满载下预期仍能正常接收
    (既定决策: 不判失败, FE 计数仅记录); 结束时恢复 8N1 并验证收发正常。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例)
        burst: 满载注入长度(字节, 如 2048), 一次性连发制造背靠背满载
        seedfrom: OrderAry 起始字符码点(0~255), 注入与恢复各用 seedfrom/seedfrom+1

    Returns:
        dict: 判定/记录字典 —— 判定键 '停止位错配满载数据完整'/
              '恢复8N1后收发正常' 及配置失败键(bool);
              记录键 '记录:满载期间FE增量'(键值 False 即该测试点失败)
    """
    rep = {}
    if not apply_format_both(shellp, uartp, 8, 'N', 2):
        rep['配置8N2失败'] = False
        return rep
    stat0 = query_stat(shellp)
    if not uartp.set_format(8, 'N', 1):
        rep['主机侧设置8N1失败'] = False
        return rep
    # 一次性连发 burst 字节制造背靠背满载, MCU 整包接收比对
    cmd = f"dmdtest_uart recv len={burst} from={seedfrom} to={seedfrom+8} timeout=3000"
    shellp.send_text(cmd + '\r\n')
    time.sleep(0.05)
    uartp.send_data(OrderAry(burst, seedfrom, seedfrom + 8).to_bytes())
    time.sleep(0.2 + burst * 10 / uartp.baudrate)
    acks = normal_recv_data_to_ack(shellp, cmd, timeout=2.0)
    stat1 = query_stat(shellp)
    rep['停止位错配满载数据完整'] = ack_is_ok(acks)
    rep['记录:满载期间FE增量'] = (stat1['frame'] - stat0['frame']) if (stat0 and stat1) else -1
    # 恢复 8N1 后正常
    rep['恢复8N1后收发正常'] = apply_format_both(shellp, uartp, 8, 'N', 1) and \
        host_roundtrip(shellp, uartp, 64, seedfrom + 1)
    return rep


def inject_break_and_recv_recover(shellp, uartp, seedfrom):
    """Break 注入 + 接收恢复探测(飞书行70/75 共用)

    MCU 阻塞接收中, 主机在线上打 250ms Break(持续低电平, 模拟对端复位/
    线路异常)。实测驱动行为: Break 起始处的帧错误会立即中止在途 recv 并
    返回负错误码(如 ret=-5), 且 Break 结束到下一次 recv 拉起接收之间的
    线上数据不被缓存 —— 故恢复验证须在 Break 结束后重发 recv 重新拉起
    接收、再送数据; 在途中止形态(错误码)仅记录不作判定。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例)
        seedfrom: OrderAry 起始字符码点(0~255), 每轮/每步自动递增防残留

    Returns:
        tuple: (是否恢复, 实际重试次数, 在途中止形态) ——
               是否恢复(bool, 3 次重试内 recv ret==8 即 True);
               实际重试次数(int, 1~3);
               在途中止形态(str, 如 "recv(ret=-5)" 或 "无应答", 仅记录)
    """
    abort_form = '未采集'
    for i in range(3):
        seedfrom += 1
        # 步骤1: MCU 进入阻塞接收(1000ms)后线路打 Break(产生帧错误)
        cmd = f"dmdtest_uart recv len=8 from={seedfrom} to={seedfrom+8} timeout=1000"
        shellp.send_text(cmd + '\r\n')
        time.sleep(0.05)
        serial_trace.record(uartp.port, 'TX-BREAK', b'')   # 线路事件入流水簿
        uartp.ser.send_break(0.25)
        time.sleep(0.35)                    # 等 Break 结束与在途 recv 中止应答
        acks = normal_recv_data_to_ack(shellp, cmd, timeout=1.2)
        if i == 0:                          # 首轮记录在途 recv 中止形态(仅记录)
            ary = acks.split() if acks else []
            abort_form = f'{ary[1]}(ret={ary[2]})' if len(ary) > 2 else '无应答'
        # 步骤2: Break 已结束(模拟重连), 重发 recv 拉起接收后再送数据校验恢复
        seedfrom += 1
        cmd = f"dmdtest_uart recv len=8 from={seedfrom} to={seedfrom+8} timeout=1000"
        shellp.send_text(cmd + '\r\n')
        time.sleep(0.05)
        uartp.send_data(OrderAry(8, seedfrom, seedfrom + 8).to_bytes())
        time.sleep(0.3)
        acks = normal_recv_data_to_ack(shellp, cmd, timeout=1.0)
        if ack_is_ok(acks) and len(acks.split()) > 2 and int(acks.split()[2]) == 8:
            return True, i + 1, abort_form
    return False, 3, abort_form


def inject_break_and_send_recover(shellp, uartp, seedfrom):
    """Break 注入 + 发送恢复探测(飞书行76)

    主机打 250ms Break 后, MCU 发送 8 字节数据由主机接收全量比对,
    验证错误状态不残留、发送路径正常, 允许 3 次重试。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例)
        seedfrom: OrderAry 起始字符码点(0~255), 每轮自动递增防残留

    Returns:
        tuple: (是否恢复, 实际重试次数) —— 是否恢复(bool, 3 次重试内
               发送应答 OK 且数据一致即 True); 实际重试次数(int, 1~3)
    """
    for i in range(3):
        seedfrom += 1
        # 步骤1: 线路打 Break
        serial_trace.record(uartp.port, 'TX-BREAK', b'')   # 线路事件入流水簿
        uartp.ser.send_break(0.25)
        time.sleep(0.1)
        # 步骤2: MCU 发送 8 字节, 主机接收比对
        uartp.recv_data(timeout=0)
        acks = normal_cmd_ack(shellp, f"dmdtest_uart send len=8 from={seedfrom} to={seedfrom+8} timeout=-1", 0.2)
        rdata = uartp.recv_data(timeout=0.3)
        if ack_is_ok(acks) and rdata and rdata == OrderAry(8, seedfrom, seedfrom + 8).to_bytes():
            return True, i + 1
    return False, 3


def overflow_probe(shellp, uartp, seedfrom, burst=8192):
    """接收溢出探测公共流程(飞书行41/56/80 共用)

    ① stat 基线  ② MCU 不发接收命令, 主机满速连灌 burst 字节(超出驱动缓冲)
    ③ stat 增量(ore/fe/pe/rx_bytes 记录)  ④ 溢出后 recv 返回形态(仅记录)
    ⑤ 恢复: 双向收发  ⑥ 后续新数据正常接收;
    缓冲策略语义(保留旧数据 vs 覆盖)无法从主机断言, 以计数增量记录 +
    恢复能力判定代替。

    Args:
        shellp: Shell 口串口控制器(SerialPortController 实例, enable_queue=True)
        uartp: 被测 UART 数据口控制器(UartPortController 实例)
        seedfrom: OrderAry 起始字符码点(0~255), 各步骤以 seedfrom+1/+2/+3 错开
        burst: 满速灌入长度(字节), 默认 8192(超出驱动缓冲)

    Returns:
        dict: 判定/记录字典 —— 判定键 '溢出后双向收发恢复'/'后续新数据接收正常'
              (bool); 记录键 '记录:ORE增量'/'记录:FE增量'/'记录:PE增量'/
              '记录:未读取期间rx_bytes增量'/'记录:溢出后recv返回'
              (键值 False 即该测试点失败)
    """
    rep = {}
    stat0 = query_stat(shellp)
    # 步骤1-2: 主机满速灌入, MCU 侧无人读取 → 驱动缓冲溢出
    uartp.recv_data(timeout=0)
    uartp.send_data(OrderAry(burst, seedfrom, seedfrom + 8).to_bytes())
    time.sleep(0.3 + burst * 10 / uartp.baudrate)
    # 步骤3: 错误计数与字节计数增量(记录)
    #   rx_bytes 为应用级口径(recv实际读取量): MCU 未读取期间应不增长,
    #   增量若为0即证明灌入字节滞留在驱动缓冲(未读取字节未被计入)
    stat1 = query_stat(shellp)
    if stat0 and stat1:
        rep['记录:ORE增量'] = stat1['overrun'] - stat0['overrun']
        rep['记录:FE增量'] = stat1['frame'] - stat0['frame']
        rep['记录:PE增量'] = stat1['parity'] - stat0['parity']
        if 'rx_bytes' in stat0 and 'rx_bytes' in stat1:
            rep['记录:未读取期间rx_bytes增量'] = stat1['rx_bytes'] - stat0['rx_bytes']
    # 步骤4: 溢出后缓冲残留数据可读性(记录返回形态, 不作内容断言)
    acks = normal_cmd_ack(shellp, f"dmdtest_uart recv len=8 from={seedfrom+1} to={seedfrom+9} timeout=300", 0.6)
    if ack_is_ok(acks):
        rep['记录:溢出后recv返回'] = 'OK(ret=%s)' % acks.split()[2]
    elif acks:
        ary = acks.split()
        rep['记录:溢出后recv返回'] = ('NG(ret=%s)' % ary[2]) if len(ary) > 2 else 'NG'
    else:
        rep['记录:溢出后recv返回'] = '无应答'
    # 步骤5: 恢复能力: 正常双向收发
    rep['溢出后双向收发恢复'] = host_roundtrip(shellp, uartp, 64, seedfrom + 2)
    # 步骤6: 后续新数据正常接收
    cmd = f"dmdtest_uart recv len=32 from={seedfrom+3} to={seedfrom+11} timeout=1000"
    ok = False
    if shellp.send_text(cmd + '\r\n') >= 0:
        time.sleep(0.05)
        uartp.send_data(OrderAry(32, seedfrom + 3, seedfrom + 11).to_bytes())
        time.sleep(0.15)
        ok = ack_is_ok(normal_recv_data_to_ack(shellp, cmd, 1.0))
    rep['后续新数据接收正常'] = ok
    uartp.recv_data(timeout=0)
    return rep
