# coding: utf-8
"""
统一的串口通信控制器

功能特性:
    - 自动/手动选择串口端口
    - 后台线程异步接收数据
    - 线程安全的缓冲区管理
    - 支持 HEX 和字符串两种数据格式
    - 支持上下文管理器 (with 语句)
    - 可选的收发计数统计
    - 可选的接收队列管理
    - 支持命令 - 响应模式

属性:
    port (str): 串口端口号，如 'COM1' 或 '/dev/ttyUSB0'
    baudrate (int): 波特率，默认 115200
    timeout (float): 读取超时时间 (秒)
    is_connected (bool): 连接状态标志
    receive_buffer (bytearray): 接收数据缓冲区
    buffer_lock (Lock): 缓冲区访问锁，保证线程安全
    receive_thread (Thread): 后台接收数据线程
    running (bool): 线程运行状态标志
    enable_count (bool): 是否启用收发计数
    enable_queue (bool): 是否启用接收队列
    rx_count (int): 接收字节计数
    tx_count (int): 发送字节计数
    recv_queue (Queue): 接收数据队列
"""
import threading
import time
import queue
from threading import Lock
import serial
import serial.tools.list_ports
from utils import serial_trace
from utils.logger import logger


class SerialPortController:
    """
    统一串口通信控制器类

    功能特性:
        - 自动/手动选择串口端口
        - 后台线程异步接收数据
        - 线程安全的缓冲区管理
        - 支持 HEX 和字符串两种数据格式
        - 支持上下文管理器 (with 语句)
        - 可选的收发计数统计
        - 可选的接收队列管理
    """

    # 类常量：线程休眠时间 (秒)
    _RECEIVE_IDLE_SLEEP = 0.01      # 接收线程空闲时休眠时间
    _DISCONNECT_WAIT = 0.1          # 断开连接后等待时间
    _BUFFER_READ_SLEEP = 0.01       # 读取数据时轮询间隔

    # 帧格式映射 (实例属性存人读字符, 连接时映射为 pyserial 常量)
    _DATABITS_MAP = {7: serial.SEVENBITS, 8: serial.EIGHTBITS}
    _PARITY_MAP = {'N': serial.PARITY_NONE, 'E': serial.PARITY_EVEN, 'O': serial.PARITY_ODD}
    _STOPBITS_MAP = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}

    def __init__(self, port=None, baudrate=115200, timeout=0.5,
                 enable_count=False, enable_queue=False,
                 databits=8, parity='N', stopbits=1, trace_enabled=False):
        """
        初始化串口通信对象

        Args:
            port (str, optional): 串口端口号。None 表示自动选择
            baudrate (int, optional): 波特率，默认 115200
            timeout (float, optional): 串口读取超时时间 (秒)，默认 0.5
            enable_count (bool, optional): 是否启用收发计数，默认 False
            enable_queue (bool, optional): 是否启用接收队列，默认 False
            databits (int, optional): 数据位 7/8，默认 8
            parity (str, optional): 校验位 'N'/'E'/'O'，默认 'N'
            stopbits (int, optional): 停止位 1/2，默认 1
            trace_enabled (bool, optional): 是否启用收发流水追踪 (每笔 TX/RX 记入
                utils.serial_trace 全局流水簿供逐用例挂 Allure, TX 同步打控制台
                INFO), 默认 False — 仅 h743 UART 底软测试启用
        """
        self.ser = None                     # 串口对象
        self.port = port                    # 端口号
        self.baudrate = baudrate            # 波特率
        self.timeout = timeout              # 超时时间

        # 帧格式 (默认 8N1; set_format 可在连接后重开串口切换)
        self.databits = databits            # 数据位
        self.parity = parity                # 校验位字符
        self.stopbits = stopbits            # 停止位

        self.is_connected = False           # 连接状态
        self.receive_buffer = bytearray()   # 接收数据缓冲区
        self.buffer_lock = Lock()           # 缓冲区锁，保护多线程访问
        self.receive_thread = None          # 接收线程
        self.running = False                # 线程运行标志
        self._stop_event = threading.Event()  # 线程停止事件，用于优雅退出

        # 可选功能：计数统计
        self.enable_count = enable_count
        self.rx_count = 0                   # 接收计数
        self.tx_count = 0                   # 发送计数
        self.count_lock = Lock()            # 计数器锁

        # 可选功能：接收队列
        self.enable_queue = enable_queue
        self.recv_queue = queue.Queue()     # 接收数据队列

        # 可选功能：收发流水追踪 (utils.serial_trace 簿记, 语义见 __init__ docstring)
        self.trace_enabled = trace_enabled

    def find_available_ports(self):
        """
        查找系统中所有可用的串口端口

        Returns:
            list[str]: 可用端口号列表，如 ['COM1', 'COM3']
        """
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]

    def connect(self, port=None, baudrate=None, timeout=None):
        """
        连接串口

        Args:
            port (str, optional): 指定端口号，None 则使用初始化时的值或自动选择
            baudrate (int, optional): 指定波特率，None 则使用初始化时的值
            timeout (float, optional): 指定超时时间，None 则使用初始化时的值

        Returns:
            bool: 连接成功返回 True，失败返回 False
        """
        try:
            # 更新配置参数
            if port is not None:
                self.port = port
            if baudrate is not None:
                self.baudrate = baudrate
            if timeout is not None:
                self.timeout = timeout

            # 如果线程正在运行，先断开连接
            if self.running:
                self.disconnect()
                time.sleep(self._DISCONNECT_WAIT)

            # 自动选择端口或手动指定
            if self.port:
                logger.info(f"使用串口：{self.port}, 波特率：{self.baudrate}")
            else:
                available_ports = self.find_available_ports()
                if not available_ports:
                    raise Exception("No available serial ports found")
                self.port = available_ports[0]
                logger.info(f"自动选择串口：{self.port}")

            # 创建并打开串口连接 (帧格式按实例属性, 默认 8N1)
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                parity=self._PARITY_MAP[self.parity],
                stopbits=self._STOPBITS_MAP[self.stopbits],
                bytesize=self._DATABITS_MAP[self.databits],
            )

            # 串口打开成功，启动接收线程
            if self.ser.is_open:
                self.is_connected = True
                self.running = True
                self._stop_event.clear()  # 清除停止事件
                self.clear_buffer()       # 清空缓冲区

                # 创建并启动后台接收线程
                self.receive_thread = threading.Thread(
                    target=self._receive_data,
                    daemon=True,  # 守护线程，主程序退出时自动结束
                    name=f"SerialReceiver-{self.port}"
                )
                self.receive_thread.start()

                logger.info(f"串口连接成功")
                return True
            return False

        except serial.SerialException as e:
            logger.error(f"串口连接失败：{str(e)}")
            self.is_connected = False
            return False
        except Exception as e:
            logger.error(f"串口连接失败：{str(e)}")
            self.is_connected = False
            return False

    def _receive_data(self):
        """
        后台接收数据线程函数

        持续从串口读取数据并存入缓冲区，使用锁保证线程安全。
        当 running 为 False 或 _stop_event 被设置时退出循环。
        """
        while self.running and self.is_connected and not self._stop_event.is_set():
            try:
                if self.ser.in_waiting:
                    data = self.ser.read(self.ser.in_waiting)
                    if data:
                        # 记入收发流水（如果启用; 只做内存追加, 不做控制台 I/O）
                        if self.trace_enabled:
                            serial_trace.record(self.port, 'RX', data)

                        # 更新计数（如果启用）
                        if self.enable_count:
                            with self.count_lock:
                                self.rx_count += len(data)

                        # 加入队列（如果启用）
                        if self.enable_queue:
                            self.recv_queue.put(data)

                        # 同时加入缓冲区（兼容原有逻辑）
                        with self.buffer_lock:
                            self.receive_buffer.extend(data)
                else:
                    # 无数据时短暂休眠，避免 CPU 空转
                    time.sleep(self._RECEIVE_IDLE_SLEEP)
            except Exception as e:
                logger.warning(f"接收数据出错：{str(e)}")
                time.sleep(0.1)  # 出错后延长休眠时间

    def set_format(self, databits=8, parity='N', stopbits=1) -> bool:
        """
        设置帧格式 (数据位/校验位/停止位), 已连接状态下重开串口生效

        Args:
            databits (int): 数据位 7/8
            parity (str): 校验位 'N'/'E'/'O'
            stopbits (int): 停止位 1/2

        Returns:
            bool: 设置后串口可用返回 True，不支持格式或重开失败返回 False
        """
        if databits not in self._DATABITS_MAP or parity not in self._PARITY_MAP \
                or stopbits not in self._STOPBITS_MAP:
            logger.warning(f"{self.port} 不支持的帧格式: {databits}{parity}{stopbits}")
            return False
        self.databits = databits
        self.parity = parity
        self.stopbits = stopbits
        if self.ser and self.ser.is_open:
            self.disconnect()
            time.sleep(self._DISCONNECT_WAIT)
            if not self.connect():
                return False
            time.sleep(self._DISCONNECT_WAIT)
            self.clear_buffer()
        return self.is_connected

    def send_data(self, data, is_hex=False):
        """
        发送数据到串口

        Args:
            data (str | bytes | bytearray): 要发送的数据
                - str: 字符串或 HEX 字符串 (如 "48 65 6C 6C 6F")
                - bytes/bytearray: 二进制数据
            is_hex (bool, optional): 是否为 HEX 格式，默认 False

        Returns:
            bool: 发送成功返回 True，失败返回 False
        """
        if not self.is_connected:
            logger.warning("串口未连接")
            return False

        try:
            # 数据格式转换
            if is_hex:
                # HEX 模式：将 HEX 字符串转换为 bytes
                if isinstance(data, str):
                    # 移除空格和换行符
                    data = data.replace(' ', '').replace('\n', '').replace('\r', '')
                    data = bytes.fromhex(data)
                elif isinstance(data, (bytes, bytearray)):
                    # bytes/bytearray 在 is_hex=True 时直接使用原始数据
                    logger.warning("is_hex=True 时传入 bytes/bytearray，将直接使用原始数据")
                    data = bytes(data)
            elif isinstance(data, str):
                # 字符串模式：UTF-8 编码
                data = data.encode('utf-8')
            elif isinstance(data, (bytearray, memoryview)):
                # 转换为 bytes
                data = bytes(data)

            # 数据类型校验
            if not isinstance(data, bytes):
                logger.error(f"无效数据类型：{type(data)}")
                return False

            # 更新计数（如果启用）
            if self.enable_count:
                with self.count_lock:
                    self.tx_count += len(data)

            # 发送数据
            self.ser.write(data)
            self.ser.flush()  # 确保数据完全发送

            # 记入收发流水并打控制台 INFO（如果启用）
            if self.trace_enabled:
                serial_trace.record(self.port, 'TX', data)
                logger.info(f"[{self.port} TX] {len(data)}B {serial_trace.preview(data)}")
            return True

        except ValueError as e:
            logger.error(f"HEX 数据格式错误：{str(e)}")
            return False
        except Exception as e:
            logger.error(f"发送数据失败：{str(e)}")
            return False

    def send_text(self, text: str) -> int:
        """
        发送文本数据

        Args:
            text (str): 要发送的文本

        Returns:
            int: 发送的字节数，失败返回 -1
        """
        if not self.is_connected:
            logger.warning("串口未连接，无法发送数据")
            return -1

        if isinstance(text, str):
            text = text.encode('utf-8')

        result = self.send_data(text)
        return len(text) if result else -1

    def read_data(self, length=None, timeout=1.0):
        """
        从缓冲区读取数据

        Args:
            length (int, optional): 要读取的字节数，None 表示读取所有可用数据
            timeout (float, optional): 超时时间 (秒)，默认 1.0

        Returns:
            bytes: 读取的数据，超时或达到指定长度时返回

        Note:
            该方法会从共享缓冲区取出数据，多次调用不会返回重复数据
        """
        if not self.is_connected:
            return b""

        start_time = time.time()
        collected_data = bytearray()

        while True:
            # 加锁访问共享缓冲区
            with self.buffer_lock:
                if len(self.receive_buffer) > 0:
                    # 取出缓冲区所有数据
                    collected_data.extend(self.receive_buffer)
                    self.receive_buffer.clear()  # 清空缓冲区

                # 检查是否达到指定长度
                if length is not None and len(collected_data) >= length:
                    return bytes(collected_data[:length])

            # 检查是否超时
            if timeout is not None and time.time() - start_time >= timeout:
                break

            time.sleep(self._BUFFER_READ_SLEEP)

        return bytes(collected_data)

    def read_line(self, end=b'\n', timeout=1.0):
        """
        从缓冲区读取一行数据 (以指定结束符为界)

        Args:
            end (bytes, optional): 行结束符，默认 b'\\n'
            timeout (float, optional): 超时时间 (秒)，默认 1.0

        Returns:
            bytes: 读取的一行数据（不包含结束符，行尾 \\r 已被剥离），超时返回空字节串
        """
        if not self.is_connected:
            return b""

        start_time = time.time()

        while True:
            # 加锁访问共享缓冲区
            with self.buffer_lock:
                # 查找结束符位置
                end_idx = self.receive_buffer.find(end)
                if end_idx != -1:
                    # 提取一行数据 (不含结束符)，并去除行尾可能残留的 \r
                    line = bytes(self.receive_buffer[:end_idx]).rstrip(b'\r')
                    # 更新缓冲区，移除已读取部分
                    self.receive_buffer = self.receive_buffer[end_idx + len(end):]
                    return line

            # 检查是否超时
            if timeout is not None and time.time() - start_time >= timeout:
                return b""

            time.sleep(self._BUFFER_READ_SLEEP)

    def recv_data(self, timeout: float = 0.1) -> bytes:
        """
        从队列接收数据（会合并所有可用数据）

        Args:
            timeout (float, optional): 超时时间 (秒)，默认 0.1

        Returns:
            bytes: 接收到的数据，超时或无数据返回 None

        Note:
            需要 enable_queue=True 才能使用此方法
        """
        if not self.enable_queue:
            logger.warning("未启用接收队列功能，请使用 read_data() 方法")
            return None

        data = None
        try:
            data = self.recv_queue.get(block=(timeout > 0), timeout=timeout)
            if data:
                # 继续收集队列中所有可用数据
                while self.running:
                    try:
                        data1 = self.recv_queue.get(block=False)
                        if data1:
                            data += data1
                        else:
                            break
                    except queue.Empty:
                        break
        except queue.Empty:
            pass
        return data

    def clear_buffer(self):
        """
        清空接收和发送缓冲区

        包括:
            - 清空内部 receive_buffer
            - 清空串口驱动的内部缓冲区
            - 清空接收队列（如果启用）
        """
        with self.buffer_lock:
            # 被丢弃的残留数据记入流水（如果启用; 回显污染排查依赖此记录）
            if self.trace_enabled and self.receive_buffer:
                serial_trace.record(self.port, 'RX丢弃', bytes(self.receive_buffer))
            self.receive_buffer.clear()

        if self.enable_queue:
            self.clear_rx_queue()

        if self.ser and self.ser.is_open:
            try:
                self.ser.reset_input_buffer()   # 清空输入缓冲区
                self.ser.reset_output_buffer()  # 清空输出缓冲区
            except:
                pass

    def clear_rx_queue(self):
        """
        清空接收队列

        Note:
            需要 enable_queue=True 才能使用此方法
        """
        if not self.enable_queue:
            return

        try:
            while not self.recv_queue.empty():
                self.recv_queue.get(block=False)
                self.recv_queue.task_done()
        except queue.Empty:
            pass

    def get_counts(self) -> dict:
        """
        获取收发计数

        Returns:
            dict: {'rx': 接收计数，'tx': 发送计数}

        Note:
            需要 enable_count=True 才能获取有效计数
        """
        if not self.enable_count:
            logger.warning("未启用计数功能")
            return {'rx': 0, 'tx': 0}

        with self.count_lock:
            return {'rx': self.rx_count, 'tx': self.tx_count}

    def reset_counts(self):
        """
        重置收发计数

        Note:
            需要 enable_count=True 才能使用此方法
        """
        if not self.enable_count:
            logger.warning("未启用计数功能")
            return

        with self.count_lock:
            self.rx_count = 0
            self.tx_count = 0

    def disconnect(self):
        """
        断开串口连接

        步骤:
            1. 设置停止标志
            2. 等待接收线程退出
            3. 关闭串口
        """
        self.running = False
        self._stop_event.set()  # 通知接收线程退出

        # 等待接收线程结束
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)

        # 关闭串口
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception as e:
                logger.error(f"关闭串口失败：{str(e)}")

        self.is_connected = False
        self.receive_thread = None
        logger.info("串口已断开")

    def stop(self):
        """
        停止串口控制器
        """
        self.disconnect()
        logger.info(f"串口控制器已停止：{self.port}")

    def __enter__(self):
        """
        上下文管理器入口，支持 with 语句

        Returns:
            SerialPortController: 当前实例

        Raises:
            ConnectionError: 连接失败时抛出
        """
        if not self.connect():
            raise ConnectionError(f"无法连接到串口：{self.port}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        上下文管理器出口，自动断开连接

        Args:
            exc_type, exc_val, exc_tb: 异常信息 (如有)
        """
        self.disconnect()

    def __del__(self):
        """
        析构函数，对象销毁时确保资源释放
        """
        try:
            if self.is_connected or (self.ser and self.ser.is_open):
                self.disconnect()
        except:
            pass


# ============================================================================
# 兼容性别名（保持向后兼容）
# ============================================================================

class SerialPortLite(SerialPortController):
    """
    兼容性类：SerialPortLite
    等同于 SerialPortController(enable_count=False, enable_queue=False)
    """
    def __init__(self, port=None, baudrate=115200, timeout=0.5):
        super().__init__(port=port, baudrate=baudrate, timeout=timeout,
                         enable_count=False, enable_queue=False)


class MCUSerialController(SerialPortController):
    """
    兼容性类：MCUSerialController
    等同于 SerialPortController(enable_count=True, enable_queue=True)
    """
    def __init__(self, port=None, baudrate=115200, timeout=0.5):
        super().__init__(port=port, baudrate=baudrate, timeout=timeout,
                         enable_count=True, enable_queue=True)


class UartPortController(SerialPortController):
    """
    dmdtest_uart 被测 UART 数据口控制器 (BSP_APP UART 底软测试专用)

    在通用串口控制器之上:
        - 默认启用接收队列与收发计数 (吞吐量测量/数据比对依赖)
        - send_data 返回实际发送字节数 (int, 失败 -1), 与通用控制器的 bool 语义不同
        - 记录被测端信息: target_uart (被测 UART 编号) / target_maxsize (DMA 单块上限,
          由协议层 open_target 应答解析后回填)
    """

    def __init__(self, port=None, baudrate=115200, timeout=0.5, target_uart=0):
        super().__init__(port=port, baudrate=baudrate, timeout=timeout,
                         enable_count=True, enable_queue=True, trace_enabled=True)
        self.target_uart = target_uart      # 被测端 UART 编号 (dmdtest_uart open N)
        self.target_maxsize = 0             # 被测端 DMA 单块上限 (字节)

    def recv_data(self, timeout: float = 0.1) -> bytes:
        """从队列接收数据, 消费到的每笔数据同步打控制台 INFO

        控制台只呈现测试代码消费到的数据 (长度 + 前导预览); 线路上的完整物理
        流水 (含被 clear_buffer 丢弃的残留) 以 serial_trace 簿记挂 Allure 为准。

        Args:
            timeout (float, optional): 超时时间 (秒)，默认 0.1

        Returns:
            bytes: 接收到的数据，超时或无数据返回 None
        """
        data = super().recv_data(timeout=timeout)
        if data:
            logger.info(f"[{self.port} RX] {len(data)}B {serial_trace.preview(data)}")
        return data

    def send_data(self, data, is_hex=False) -> int:
        """
        发送原始字节

        Returns:
            int: 实际发送的字节数, 失败返回 -1
        """
        payload = bytes(data) if not isinstance(data, str) else data
        if not super().send_data(payload, is_hex=is_hex):
            return -1
        return len(payload if isinstance(payload, bytes) else payload.encode('utf-8'))
