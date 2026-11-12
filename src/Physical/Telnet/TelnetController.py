# coding: utf-8
"""
统一的 Telnet 通信控制器

功能特性:
    - 基于 TCP Socket 的网口通信
    - 后台线程异步接收数据
    - 线程安全的缓冲区管理
    - 支持 HEX 和字符串两种数据格式
    - 支持上下文管理器 (with 语句)
    - 可选的收发计数统计
    - 可选的接收队列管理
    - 支持命令 - 响应模式

属性:
    host (str): 目标主机 IP 地址
    port (int): 目标端口号，默认 23 (Telnet)
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
import socket
from threading import Lock
from utils.logger import logger


class TelnetController:
    """
    Telnet 通信控制器类

    功能特性:
        - 基于 TCP Socket 的网口通信
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
    _CONNECT_TIMEOUT = 5.0          # 连接超时时间 (秒)

    def __init__(self, host=None, port=23, timeout=0.5,
                 enable_count=False, enable_queue=False):
        """
        初始化 Telnet 通信对象

        Args:
            host (str, optional): 目标主机 IP 地址，如 '192.168.1.100'
            port (int, optional): 目标端口号，默认 23 (Telnet 标准端口)
            timeout (float, optional): 读取超时时间 (秒)，默认 0.5
            enable_count (bool, optional): 是否启用收发计数，默认 False
            enable_queue (bool, optional): 是否启用接收队列，默认 False
        """
        self.socket = None                  # Socket 对象
        self.host = host                    # 目标主机 IP
        self.port = port                    # 目标端口
        self.timeout = timeout              # 超时时间

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

    def connect(self, host=None, port=None, timeout=None):
        """
        连接到 Telnet 服务器

        Args:
            host (str, optional): 指定目标主机 IP，None 则使用初始化时的值
            port (int, optional): 指定目标端口，None 则使用初始化时的值
            timeout (float, optional): 指定超时时间，None 则使用初始化时的值

        Returns:
            bool: 连接成功返回 True，失败返回 False
        """
        try:
            # 更新配置参数
            if host is not None:
                self.host = host
            if port is not None:
                self.port = port
            if timeout is not None:
                self.timeout = timeout

            # 如果线程正在运行，先断开连接
            if self.running:
                self.disconnect()
                time.sleep(self._DISCONNECT_WAIT)

            # 参数校验
            if not self.host:
                raise Exception("未指定目标主机 IP 地址")

            logger.info(f"正在连接 Telnet 服务器：{self.host}:{self.port}")

            # 创建 Socket 连接
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self._CONNECT_TIMEOUT)
            self.socket.connect((self.host, self.port))
            self.socket.settimeout(self.timeout)

            # 连接成功，启动接收线程
            self.is_connected = True
            self.running = True
            self._stop_event.clear()  # 清除停止事件
            self.clear_buffer()       # 清空缓冲区

            # 创建并启动后台接收线程
            self.receive_thread = threading.Thread(
                target=self._receive_data,
                daemon=True,  # 守护线程，主程序退出时自动结束
                name=f"TelnetReceiver-{self.host}:{self.port}"
            )
            self.receive_thread.start()

            logger.info(f"Telnet 连接成功：{self.host}:{self.port}")
            return True

        except socket.timeout as e:
            logger.error(f"连接超时：{str(e)}")
            self.is_connected = False
            return False
        except socket.error as e:
            logger.error(f"Socket 错误：{str(e)}")
            self.is_connected = False
            return False
        except Exception as e:
            logger.error(f"Telnet 连接失败：{str(e)}")
            self.is_connected = False
            return False

    def _receive_data(self):
        """
        后台接收数据线程函数

        持续从 Socket 读取数据并存入缓冲区，使用锁保证线程安全。
        当 running 为 False 或 _stop_event 被设置时退出循环。
        """
        while self.running and self.is_connected and not self._stop_event.is_set():
            try:
                # 使用 select 或直接 recv 接收数据
                self.socket.setblocking(False)
                try:
                    data = self.socket.recv(4096)
                    if data:
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
                except socket.error:
                    # 非阻塞模式下无数据会抛出异常，短暂休眠后继续
                    time.sleep(self._RECEIVE_IDLE_SLEEP)
            except Exception as e:
                logger.warning(f"接收数据出错：{str(e)}")
                time.sleep(0.1)  # 出错后延长休眠时间

    def send_data(self, data, is_hex=False):
        """
        发送数据到 Telnet 服务器

        Args:
            data (str | bytes | bytearray): 要发送的数据
                - str: 字符串或 HEX 字符串 (如 "48 65 6C 6C 6F")
                - bytes/bytearray: 二进制数据
            is_hex (bool, optional): 是否为 HEX 格式，默认 False

        Returns:
            bool: 发送成功返回 True，失败返回 False
        """
        if not self.is_connected:
            logger.warning("Telnet 未连接")
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
            self.socket.sendall(data)
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
            logger.warning("Telnet 未连接，无法发送数据")
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
            bytes: 读取的一行数据 (不包含结束符)，超时返回空字节串
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
                    # 提取一行数据 (不含结束符)
                    line = bytes(self.receive_buffer[:end_idx])
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
            - 清空 Socket 的内部缓冲区
            - 清空接收队列（如果启用）
        """
        with self.buffer_lock:
            self.receive_buffer.clear()

        if self.enable_queue:
            self.clear_rx_queue()

        if self.socket:
            try:
                # 清空 Socket 缓冲区
                self.socket.setblocking(False)
                while True:
                    try:
                        self.socket.recv(4096)
                    except socket.error:
                        break
                self.socket.setblocking(True)
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
        断开 Telnet 连接

        步骤:
            1. 设置停止标志
            2. 等待接收线程退出
            3. 关闭 Socket
        """
        self.running = False
        self._stop_event.set()  # 通知接收线程退出

        # 等待接收线程结束
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)

        # 关闭 Socket
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                logger.error(f"关闭 Socket 失败：{str(e)}")

        self.is_connected = False
        self.receive_thread = None
        logger.info("Telnet 连接已断开")

    def stop(self):
        """
        停止 Telnet 控制器
        """
        self.disconnect()
        logger.info(f"Telnet 控制器已停止：{self.host}:{self.port}")

    def __enter__(self):
        """
        上下文管理器入口，支持 with 语句

        Returns:
            TelnetController: 当前实例

        Raises:
            ConnectionError: 连接失败时抛出
        """
        if not self.connect():
            raise ConnectionError(f"无法连接到 Telnet 服务器：{self.host}:{self.port}")
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
            if self.is_connected or self.socket:
                self.disconnect()
        except:
            pass
