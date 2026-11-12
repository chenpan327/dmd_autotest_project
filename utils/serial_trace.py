# coding: utf-8
"""
串口收发流水日志簿 (h743 UART 底软测试专用, 会话级全局)

SerialPortController 在 trace_enabled=True 时把每笔 TX/RX 物理收发追加进全局
流水 (时间戳/端口/方向/字节数/前导预览), 接收线程内仅做"加锁追加+短预览"纯内存
操作, 不做控制台/文件 I/O, 保证 1.5Mbps 满速灌数下接收线程不被拖慢。

流水消费方:
    - 脚本层 conftest 逐用例切片 (entries_since) 挂 Allure 附件, 完整还原该用例
      期间 Shell 口/数据口线路上发生的每一笔收发, 含被 clear_buffer 丢弃的残留;
    - 控制台可见性由控制器与协议层的 INFO 日志承担 (消费到的数据), 与本流水互补。
"""
import threading
import time

# 每笔流水预览的最大字节数 (文本按原文转义, 二进制按 hex)
PREVIEW_LEN = 48
# 流水条目防爆上限 (异常洪泛时丢弃后续条目并计数, 不拖垮会话)
MAX_ENTRIES = 50000

_lock = threading.Lock()
_entries = []       # 每条: "HH:MM:SS.mmm PORT DIR nB 预览"
_dropped = 0        # 超限被丢弃的条目数


def preview(data):
    """数据前导预览文本: 文本类字节按原文显示 (控制符转义), 否则按 hex

    文本类 = 全部字节为可打印 ASCII 或常见控制符 (\\r/\\n/\\t), Shell 命令/
    应答以此形态展示; 其余 (真二进制) 按 hex 空格分隔展示。

    Args:
        data: 原始字节内容 (bytes/bytearray)

    Returns:
        str: 形如 '"dmdtest_uart open 1\\r\\n…"' 或 '73 74 61 74 …' 的短预览
    """
    head = bytes(data[:PREVIEW_LEN])
    if not head:
        return ''
    if all(0x20 <= b < 0x7F or b in (0x0D, 0x0A, 0x09) for b in head):
        text = head.decode('ascii').replace('\\', '\\\\') \
            .replace('\r', '\\r').replace('\n', '\\n').replace('\t', '\\t')
        return f'"{text}"' + ('…' if len(data) > PREVIEW_LEN else '')
    return head.hex(' ') + ('…' if len(data) > PREVIEW_LEN else '')


def record(port, direction, data=b''):
    """追加一笔收发流水 (线程安全, 超限丢弃并计数)

    Args:
        port: 端口号 (如 "COM13"), 仅作展示
        direction: 方向标记 ("TX"/"RX"/"RX丢弃"/"TX-BREAK" 等)
        data: 该笔收发的字节内容; 线路事件 (如 Break) 传 b"" 且 direction
              必须为 'TX-BREAK' 才入簿, 其余方向空数据不入簿
    """
    global _dropped
    if not data and direction != 'TX-BREAK':
        return
    t = time.time()
    ts = time.strftime('%H:%M:%S', time.localtime(t)) + f'.{int(t * 1000) % 1000:03d}'
    with _lock:
        if len(_entries) >= MAX_ENTRIES:
            _dropped += 1
            return
        _entries.append(f'{ts} {port} {direction} {len(data)}B {preview(data)}')


def snapshot():
    """取当前流水总条数 (用例开始前调用, 作为切片起点)"""
    with _lock:
        return len(_entries)


def entries_since(start):
    """取 start 之后新增的流水条目 (用例结束后切片挂 Allure)

    Args:
        start: snapshot() 返回的切片起点条数

    Returns:
        list[str]: 流水文本行列表; 会话期间发生过超限丢弃时末尾附丢弃计数行
    """
    with _lock:
        out = list(_entries[start:])
        if _dropped:
            out.append(f'…另有 {_dropped} 笔超出 {MAX_ENTRIES} 条上限未记录')
        return out
