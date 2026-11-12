"""
假机巢（FakeNest）模拟器：模拟一台机巢按 Nest 协议（v45）响应地面站。

模块结构：
    FakeNest                    传输层：在本机网卡上添加一个辅助 IP，绑定 UDP 套接字。
                                - 支持自适应识别两种 MAVLink 格式：
                                  * 标准格式：MAVLink 魔数开头
                                  * 特殊格式：4 字节 IP 前缀 + MAVLink
    _NestAirplane             轻型假飞机：不创建网卡节点、不绑定端口。
                                - 通过机巢 UDP 套接字转发，消息自动带本飞机 IP 前缀。
                                - 通信策略与 _FakeAirplaneMessageSender 一致。
                                - 握手流程（非阻塞状态机）：
                                  IDLE → (首条心跳) → WAIT_ID_3 → (收 id=3) → 发 id=2
                                  → WAIT_ID_1 → (收 id=1 extend=1) → COMPLETED
                                  超时 30s → FAILED，不阻塞其他消息处理。
    _FakeNestSender             响应层：单台假机巢的后台线程集合。
                                - 接收线程：监听地面站消息，按 _RESPONSE_RULES 响应。
                                - 周期线程：每 1s 发送 msg_id=86（nest_packed_state）+ 飞机心跳。
                                - 根据 uavIp 自动创建/移除 _NestAirplane 实例。
                                - 驱动飞机的握手状态机（触发 + 超时检查）。
    _FakeNestSenders            管理层：批量创建多台假机巢及其响应线程。

飞机消息路由（两种互补策略）：
    策略 A — IP 前缀消息 + 命中某组件 IP → 仅该 IP 对应组件回复（精确路由）
    策略 B — 纯 MAVLink（无前缀）→ 按 comp_id 广播路由：
        comp_id=0  (ALL)           → 所有组件回复
        comp_id=1  (AUTOPILOT1)    → 所有假飞机回复（含握手+正常消息）
        comp_id=35 (NEST)          → 假机巢回复
        comp_id=36 (NEST_PPS)      → PPS 回复
        comp_id=38 (NEST_PPSCHARGER) → PPSCharger 回复

协议规则（v45 / _RESPONSE_RULES）：
    入站 msg_id=1 (HEARTBEAT_DMD)        -> 发送 msg_id=87 (NEST_EXTEND_STATE) 给地面站
    入站 msg_id=3 (GET_IDENTIFY_INFO)    -> 发送 msg_id=2  (IDENTIFY_INFO)     给地面站
    周期 1s                              -> 发送 msg_id=86 (NEST_PACKED_STATE)  给地面站

飞机握手协议（通过机巢转发，支持两种互补策略）：
    策略 A — 单机精确握手（IP 前缀格式）：
        飞机 → 地面站: 首条心跳 msg_id=0（由周期线程以飞机 IP 前缀发出）
        飞机 ← 地面站: msg_id=3 (GET_IDENTIFY_INFO)（地面站以飞机 IP 前缀发送，机巢路由到对应飞机）
        飞机 → 地面站: msg_id=2 (IDENTIFY_INFO)（飞机以自身 IP 前缀经机巢回复）
        飞机 ← 地面站: msg_id=1 (HEARTBEAT_DMD, extend=1)（握手确认）
    策略 B — 批量握手（纯 MAVLink，comp_id=1）：
        地面站以 comp_id=1 发送 msg_id=3 → 所有飞机同时回复 id=2
        地面站以 comp_id=1 发送 msg_id=1 extend=1 → 所有飞机同时完成握手
    超时 30s/步，失败不删除飞机，继续正常通信。
"""

import ctypes
import hashlib
import re
import socket
import struct
import subprocess
import sys
import os
import time
import threading
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_mavlink import MAVLink_message
from param_dict import UavParamDict, serial_to_model, MODEL_TO_CSV

# DGCS 安装目录下的参数 CSV 根目录（对齐 fake_airplane.py）
_PARAM_CSV_BASE = r"C:\Program Files\DGCS\4.0\Components\ParamList"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from utils.logger import logger
from utils.logger import LogManager

MAVLINK_VERSION = '45'
NETCARD_INTERFACE = "WLAN 6"

# ==================================================================
# MAVLink System ID / Component ID 常量（对齐协议文档 §4.4.1/§4.2）
# ==================================================================
# System ID（发送方系统身份）
SYS_ID_GCS     = 39   # 地面站 (MAV_COMP_ID_DMD_GCS)
SYS_ID_UAV     = 1    # 无人机 (MAV_COMP_ID_AUTOPILOT1)
SYS_ID_NEST    = 40   # 机巢主控 (MAV_COMP_ID_NEST)
SYS_ID_BROADCAST = 255  # 广播

# Component ID（子系统/目标组件）
COMP_ID_ALL           = 0    # 所有组件
COMP_ID_AUTOPILOT1    = 1    # 飞控自动驾驶仪
COMP_ID_NEST_PPS      = 36   # PPS 可编程电源
COMP_ID_LPPC          = 37   # LPPC 低功耗处理器
COMP_ID_NEST_PPSCHARGER = 38  # PPS 充电器
COMP_ID_GCS           = 39   # 地面站 (MAV_COMP_ID_DMD_GCS)
COMP_ID_NEST          = 40   # 机巢主控 (MAV_COMP_ID_NEST)
COMP_ID_NEST_CHARGER  = 41   # 机巢充电器


# ==================================================================
# fake_nest 专用：从原始 bytes 解析 MAVLink 消息
# ==================================================================
def _parse_mavlink_message(data: bytes):
    """从原始 MAVLink 帧字节解析为 MAVLink_message 实例。

    fake_nest 专用的便捷封装，按 ``MAVLINK_VERSION``(45) 加载协议配置解析，
    等价于 ``MAVLink_message(hex_data=data.hex(), version=MAVLINK_VERSION)``。
    放在本文件而非 parse_mavlink 中，避免修改外部通用库。

    Args:
        data: 原始 MAVLink 帧字节（header + payload + crc）
    Returns:
        MAVLink_message 实例
    """
    return MAVLink_message(hex_data=data.hex(), version=MAVLINK_VERSION)


# ==================================================================
# 机巢摄像头视频流（协议文档 §7.9.2）：HTTP :8080/stream MJPEG
# ==================================================================
def _make_camera_frame(value: int, size: tuple = (320, 240)) -> bytes:
    """生成一张显示数字 value 的 JPEG 帧（供 MJPEG 视频流推送）。

    参考地面站 DroneNestCameraClient 解析方式：按 JPEG SOI/EOI（FF D8 / FF D9）
    提取帧并显示。帧内容为深色背景 + 白色大号数字，用于循环显示 1~10。
    """
    import io
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new('RGB', size, (24, 26, 48))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype('arialbd.ttf', int(size[1] * 0.6))
    except Exception:
        font = ImageFont.load_default()
    text = str(value)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size[0] - tw) / 2 - bbox[0], (size[1] - th) / 2 - bbox[1]),
              text, font=font, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=85)
    return buf.getvalue()


class _CameraMjpegStream:
    """机巢摄像头 MJPEG HTTP 流（:8080/stream）。

    - 服务地址: http://{nestIp}:8080/stream（协议文档 §7.9.2）
    - 帧格式: multipart/x-mixed-replace，每帧为 JPEG（内容为循环数字 1~10）
    - 帧提取: 地面站按 JPEG SOI/EOI 标记（FF D8 / FF D9）组帧
    """

    def __init__(self):
        self._frames = {}          # {value: jpeg_bytes}
        self._server = None
        self._thread = None
        self._running = False
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._running

    def _ensure_frames(self):
        if not self._frames:
            for v in range(1, 11):
                self._frames[v] = _make_camera_frame(v)

    def start(self) -> bool:
        """启动 HTTP MJPEG 服务（8080 端口）。返回是否成功。"""
        import http.server
        with self._lock:
            if self._server is not None:
                return True
            self._ensure_frames()
            handler = self._make_handler()
            try:
                self._server = http.server.ThreadingHTTPServer(('', 8080), handler)
            except OSError as e:
                logger.warning(f"[TEST] 摄像头 HTTP 服务启动失败: {e}")
                self._server = None
                return False
            self._running = True
            self._server.frames = self._frames
            self._server.stream = self
            self._thread = threading.Thread(
                target=self._server.serve_forever, daemon=True,
                name='camera-mjpeg',
            )
            self._thread.start()
            logger.info("[TEST] 机巢摄像头 MJPEG 流已启动 http://:8080/stream")
            return True

    def stop(self):
        """停止 HTTP MJPEG 服务。"""
        with self._lock:
            self._running = False
            if self._server is not None:
                try:
                    self._server.shutdown()
                    self._server.server_close()
                except Exception:
                    pass
                self._server = None
            self._thread = None
            logger.info("[TEST] 机巢摄像头 MJPEG 流已停止")

    def _make_handler(self):
        import http.server

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.rstrip('/') != '/stream':
                    self.send_error(404)
                    return
                frames = self.server.frames
                stream = self.server.stream
                value = 0
                try:
                    self.send_response(200)
                    self.send_header('Content-Type',
                                     'multipart/x-mixed-replace; boundary=frame')
                    self.send_header('Cache-Control', 'no-cache')
                    self.end_headers()
                    while stream._running:
                        value = (value % 10) + 1
                        frame = frames[value]
                        self.wfile.write(
                            b'--frame\r\n'
                            b'Content-Type: image/jpeg\r\n'
                            b'Content-Length: %d\r\n\r\n' % len(frame)
                        )
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                        self.wfile.flush()
                        time.sleep(0.5)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                except Exception:
                    pass

            def log_message(self, *args):
                pass  # 静默访问日志

        return _Handler


# ==================================================================
# 嵌套设备自适应注册表（__init_subclass__ 自动发现）
# ==================================================================
@dataclass
class NestedDeviceMeta:
    """嵌套设备类型的元数据，由 _NestedDeviceBase.__init_subclass__ 自动填充。"""
    cls: type                    # 嵌套设备类
    label: str                   # 子 Tab 显示名
    sender_update_method: str    # _FakeNestSender 上对应的 update 方法名
    sender_instances_attr: str   # _FakeNestSender 上存放实例的属性名
    instance_mode: str           # "dict"（字典管理，如 _airplanes）或 "single"（单例，如 _pps）
    fields: dict                 # {field_name: (default, kind)}


NESTED_DEVICE_REGISTRY: dict[str, NestedDeviceMeta] = {}


class _NestedDeviceBase:
    """嵌套设备基类：子类定义时自动注册到 NESTED_DEVICE_REGISTRY。

    子类必须声明以下类属性：
        _DEVICE_LABEL: str           — GUI 显示名
        _SENDER_UPDATE_METHOD: str   — _FakeNestSender 上的 update 方法名
        _SENDER_INSTANCES_ATTR: str  — _FakeNestSender 上存放实例的属性名
        _INSTANCE_MODE: str          — "dict" 或 "single"
        _UPDATABLE_FIELDS: dict      — {field_name: (default, kind)}
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # 跳过基类自身（_NestedDeviceBase 不应注册）
        if cls.__name__ == "_NestedDeviceBase":
            return
        NESTED_DEVICE_REGISTRY[cls.__name__] = NestedDeviceMeta(
            cls=cls,
            label=getattr(cls, "_DEVICE_LABEL", cls.__name__),
            sender_update_method=cls._SENDER_UPDATE_METHOD,
            sender_instances_attr=cls._SENDER_INSTANCES_ATTR,
            instance_mode=cls._INSTANCE_MODE,
            fields=getattr(cls, "_UPDATABLE_FIELDS", {}),
        )


class FakeNest:
    def __init__(self, ip_addr="172.16.3.180",
                 ground_station_ip="172.16.200.1",
                 ground_station_port=14650,
                 local_port=14651,
                 interface=NETCARD_INTERFACE,
                 mask="255.240.0.0",
                 recv_timeout=1.0):
        self.target_interface = interface
        self.target_ip = ip_addr
        self.target_mask = mask
        self.ground_station_ip = ground_station_ip
        self.ground_station_port = ground_station_port
        self.local_port = local_port
        self.recv_timeout = recv_timeout

        self.local_ip = None
        self.sock = None
        self.udp_connected = False

        self._setup_network()
        self._udp_setup()
        time.sleep(0.5)  # 等待网络完全就绪

    # ------------------------------------------------------------------
    # 网卡 IP 设置 此处为对一个网卡设置多个辅助IP
    # ------------------------------------------------------------------
    def _setup_network(self):

        """Windows 上无 dummy 设备，使用 PowerShell 在活动接口上添加辅助 IP 作为等价逻辑"""
        if self._ip_exists_locally(self.target_ip):
            logger.info(f"IP {self.target_ip} 已存在于本机接口，跳过添加")
            self.local_ip = self.target_ip
            return True

        if not self.target_interface:
            logger.error("未找到活动的物理网络接口，无法添加辅助IP")
            return False

        ps_cmd = (
            f'powershell -NoProfile -Command '
            f'"New-NetIPAddress -InterfaceAlias \'{self.target_interface}\' '
            f'-IPAddress \'{self.target_ip}\' -PrefixLength 24"'
        )
        
        logger.info(f"在 {self.target_interface} 上添加辅助IP: {self.target_ip}")
        ret = os.system(ps_cmd)
        if ret != 0:
            logger.error(f"New-NetIPAddress 执行失败，返回码: {ret}")
            return False
        self.local_ip = self.target_ip
    
    # ------------------------------------------------------------------
    # 网卡 IP 设置
    # ------------------------------------------------------------------
    def _setup_network_old(self):
        """检查并按需把目标网卡的 IP 配置为 self.target_ip"""
        self.local_ip = self._get_local_ip()
        if self.local_ip is None:
            logger.warning(f"未找到 {self.target_interface} 的 IP 地址，请检查网络连接。")
            return

        if self.local_ip != self.target_ip:
            self._set_ip_address()
            self.local_ip = self._get_local_ip()
            if self.local_ip == self.target_ip:
                logger.info(f"{self.target_interface} 的 IP 地址已成功设置为: {self.local_ip}")
        else:
            logger.info(f"{self.target_interface} 的 IP 地址已正确设置为: {self.local_ip}")

    def _get_local_ip(self):
        """使用 ipconfig 解析目标网卡的 IPv4 地址"""
        result = subprocess.run(['ipconfig', '/all'],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True)
        lines = result.stdout.split('\n')
        in_target_section = False
        ip_address = None

        for line in lines:
            line = line.strip()

            if self.target_interface in line:
                in_target_section = True
                continue

            if in_target_section:
                match = re.search(r'IPv4.*?[:\s]+(\d+\.\d+\.\d+\.\d+)', line)
                if match:
                    ip_address = match.group(1)
                    break
                if "适配器" in line:
                    in_target_section = False

        return ip_address

    def _set_ip_address(self):
        """通过 netsh 静态配置网卡 IP（需要管理员权限）"""
        try:
            if ctypes.windll.shell32.IsUserAnAdmin():
                logger.info("管理员权限已确认.")
            else:
                logger.warning("请以管理员身份运行此脚本.")
                return False
        except Exception:
            return False

        try:
            cmd = [
                'netsh', 'interface', 'ip', 'set', 'address',
                f'name={self.target_interface}',
                'source=static',
                f'addr={self.target_ip}',
                f'mask={self.target_mask}',
                'store=persistent'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"{self.target_interface} 的 IP 已成功设置为: {self.target_ip} / {self.target_mask}")
                return True
            logger.error(f"设置失败: {result.stderr}")
            return False
        except Exception as e:
            logger.error(f"发生错误: {e}")
            return False

    # ------------------------------------------------------------------
    # 检查 IP 是否已绑定到本机任意接口
    # ------------------------------------------------------------------   
    def _ip_exists_locally(self, ip: str) -> bool:
        """检查 IP 是否已绑定到本机任意接口"""
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind((ip, 0))
            return True
        except OSError:
            return False
        finally:
            if s:
                s.close()

    # ------------------------------------------------------------------
    # UDP 通讯
    # ------------------------------------------------------------------
    def _udp_setup(self):
        """创建并绑定 UDP 套接字"""
        if self.local_ip is None:
            logger.warning("本地 IP 未配置，跳过 UDP 套接字创建。")
            return

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        self.sock.settimeout(self.recv_timeout)
        self.udp_connected = True

        max_retries = 10
        for attempt in range(1, max_retries + 1):
            try:
                self.sock.bind((self.local_ip, self.local_port))
                logger.info(f"UDP 套接字已绑定到 {self.local_ip}:{self.local_port}")
                logger.info(f"目标地面站: {self.ground_station_ip}:{self.ground_station_port}")
                break
            except OSError as e:
                if e.winerror == 10049 and attempt < max_retries:
                    logger.info(f"IP 未生效，1s 后重试 ({attempt + 1}/{max_retries})")
                    time.sleep(1)
                else:
                    logger.warning(f"IP 重试{max_retries}次后仍未生效")
                    raise


    def close(self):
        """关闭 UDP 通讯"""
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.udp_connected = False
        logger.info("FakeNest UDP 通讯已关闭。")

    # ------------------------------------------------------------------
    # MAVLink 收发
    # ------------------------------------------------------------------
    def send(self, message: MAVLink_message, addr=None,
             prepend_ip: bool = False, prepend_ip_addr: str = None,
             raw_prefix: bytes = None) -> bool:
        """向地面站发送一条 MAVLink 消息

        Args:
            message: 待发送的 MAVLink_message 实例
            addr: 目标 (ip, port)，省略则发送给默认地面站
            prepend_ip: 是否在 MAVLink 包前添加 4 字节 IP 前缀（特殊格式）
            prepend_ip_addr: 指定前缀 IP 地址（字符串）；省略则使用 self.local_ip。
            raw_prefix: 原始 4 字节前缀（优先于 prepend_ip_addr）。
                        用于 LPPC 心跳等需要非标准 IP 前缀的场景（§4.4.7）。

        Returns:
            发送成功返回 True，否则 False
        """
        if not self.udp_connected or self.sock is None:
            logger.warning("UDP 未连接，无法发送数据。")
            return False

        if addr is None:
            addr = (self.ground_station_ip, self.ground_station_port)

        try:
            data = message.pack()
            if prepend_ip:
                if raw_prefix is not None and len(raw_prefix) == 4:
                    ip_bytes = raw_prefix
                else:
                    ip_addr = prepend_ip_addr if prepend_ip_addr else self.local_ip
                    if ip_addr:
                        ip_bytes = socket.inet_aton(ip_addr)
                    else:
                        ip_bytes = b'\x00\x00\x00\x00'
                data = ip_bytes + data
            self.sock.sendto(data, addr)
            return True
        except Exception as e:
            logger.error(f"发送数据失败: {e}")
            return False

    def receive(self, bufsize: int = 1024):
        """接收并解析一条 MAVLink 消息，自动识别是否带 4 字节 IP 前缀。

        自适应检测逻辑：
            - 若首字节为 MAVLink 魔数（0xFE v1 / 0xFD v2）→ 标准格式
            - 若首字节非魔数，但偏移 4 字节后为魔数 → 特殊格式（4 字节 IP + MAVLink）
            - 其他情况 → 回退到标准解析

        Returns:
            (MAVLink_message, addr, source_ip) 元组；
            超时返回 (None, None, None)。
            source_ip: 特殊格式时返回前缀中的 IP 字符串，标准格式时为 None。
        """
        if not self.udp_connected or self.sock is None:
            return None, None, None

        try:
            data, _ = self.sock.recvfrom(bufsize)
            addr = (self.ground_station_ip, self.ground_station_port)
        except socket.timeout:
            return None, None, None
        except Exception as e:
            logger.error(f"接收数据失败: {e}")
            return None, None, None

        data_raw = data  # 保存原始报文用于调试打印（IP 前缀剥离前）

        # ------------------------------------------------------------------
        # 自适应检测：判断是否为"4 字节 IP + MAVLink"特殊格式
        # ------------------------------------------------------------------
        source_ip = None
        _MAVLINK_MAGIC = (0xFE, 0xFD)  # v1 / v2
        if len(data) > 5:
            first_byte = data[0]
            if first_byte not in _MAVLINK_MAGIC:
                # 首字节不是魔数，检查偏移 4 字节后是否为魔数
                if data[4] in _MAVLINK_MAGIC:
                    try:
                        source_ip = socket.inet_ntoa(data[0:4])
                        data = data[4:]  # 剥离 IP 前缀，后续按标准 MAVLink 解析
                    except (OSError, ValueError):
                        pass  # 不是合法 IPv4，保持原数据回退到标准解析

        # ---- 过滤自身外发的消息（UDP 回环）----
        # if source_ip is not None and source_ip == self.local_ip:
        #     print(f"[NEST-RECV] 跳过自身外发消息 source_ip={source_ip}")
        #     return None, None, None

        # ---- DEBUG: 打印所有收到的 UDP 报文（暂时注释）----
        # hex_full = data_raw.hex()
        # hex_spaced = ' '.join(f'{b:02x}' for b in data_raw)
        # ascii_repr = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data_raw)
        # print(f"\n[NEST-RECV] local={self.local_ip}:{self.local_port} ← {addr} | len={len(data_raw)}")
        # print(f"  hex_full=  {hex_full}")
        # print(f"  hex_spaced={hex_spaced}")
        # print(f"  ascii=     {ascii_repr}")

        try:
            message = MAVLink_message(hex_data=data.hex(), version=MAVLINK_VERSION)
            # fields_str = ', '.join(f'{k}={v}' for k, v in message.fields.items())
            # print(f"  parsed=    msg_id={message.msg_id} sys_id={message.sys_id} "
            #       f"comp_id={message.comp_id} source_ip={source_ip} "
            #       f"fields=[{fields_str}]")
            return message, addr, source_ip
        except Exception as e:
            print(f"  parse_failed | error={e}")
            logger.error(f"解析 MAVLink 消息失败: {e}")
            return None, addr, source_ip


# ==================================================================


# ==================================================================
# _NestAirplane：机巢内轻型假飞机（完全自包含，不依赖 fake_airplane.py）
# ==================================================================
class _NestAirplane(_NestedDeviceBase):
    """机巢内假飞机：完全自包含的消息处理与状态管理。

    不持有网卡/线程；消息接收由机巢 receive 线程驱动（process_message），
    外发由机巢 _wrap_and_send 完成。
    """

    # ================================================================
    # 嵌套设备自适应注册元数据
    # ================================================================
    _DEVICE_LABEL = "轻型假飞机"
    _SENDER_UPDATE_METHOD = 'update_airplane_state'
    _SENDER_INSTANCES_ATTR = "_airplanes"
    _INSTANCE_MODE = "dict"
    _UPDATABLE_FIELDS = {
        # -- 风速 & 序列号 --
        'wind_speed_x': (0, 'int16'),
        'wind_speed_y': (0, 'int16'),
        'seq': (604054808, 'int32'),
        # -- 负载配置（挂载点灯 / COMMAND_LONG param7 映射）--
        'laser_config': ([0, 0, 0, 0], 'list_int'),
        'nova_config': (0, 'int'),
        'firework_config': (0, 'int'),
        'lantern_config': (0, 'int'),
        'trumpet_config': (0, 'int'),
        'parachute_config': (0, 'int'),
        # -- 负载状态（id=204 上报）--
        'laser_state': (0, 'int'),
        'nova_state': (0, 'int'),
        'lantern_state': (0, 'int'),
        'trumpet_state': (0, 'int'),
        'parachute_state': (0, 'int'),
        # -- 负载存在标志 --
        'lantern': (0, 'int'),
        'trumpet': (0, 'int'),
        'parachute': (0, 'int'),
        # -- 版本信息（id=8 上报）--
        'roll': (0.0, 'float'),
        'pitch': (0.0, 'float'),
        'yaw': (0.0, 'float'),
        'temp_imu': (0.0, 'float'),
        'temp_baro': (0.0, 'float'),
        'anchor_hash': (0, 'uint32'),
        'uas_code': (b'', 'bytes'),
        'laser_temperature': (25.0, 'float'),
        'is_inside_nest': (0, 'uint8'),
        'loc_nest_layer': (0, 'uint8'),
        'loc_nest_id': (b'\x00' * 5, 'bytes'),
        'loc_nest_sn': (b'\x00' * 20, 'bytes'),
        'nova_light_version': (b'1234', 'bytes'),
        'gimbal_version': (b'', 'bytes'),
        'flight_controller_version': (b'n3.j.196', 'bytes'),
        'companion_version': (b'V3.631', 'bytes'),
        'battery_version': (b'', 'bytes'),
        'gps_version': (b'UM16982', 'bytes'),
        'servo_ver': (0, 'int'),
        'tele_version': (b'E013', 'bytes'),
        'bms_version': (b'', 'bytes'),
        'rid_version': (b'', 'bytes'),
        # -- GPS 位置（MAVLink msg_id=5, GUI 输入度/米，自动 ×1e7 / ×1000）--
        'cur_lat': (226868664, 'latlon'),
        'cur_lon': (1140224548, 'latlon'),
        'tar_lat': (226868664, 'latlon'),
        'tar_lon': (1140224548, 'latlon'),
        'cur_alt': (0, 'alt_m'),
        'tar_alt': (0, 'alt_m'),
        # -- GPS 定位类型（MAVLink msg_id=5, B=uint8_t）--
        'fix_type': (6, 'uint8'),
        # -- 飞行状态机 --
        'mode': (4, 'int'),               # 4=G, 6=R, 9=LD
        'armed': (0, 'int'),
        'final_mode': (6, 'int'),         # 结束模式
        'play_duration_ms': (0, 'int'),
        'land_duration_ms': (4000, 'int'),
        'takeoff_height_mm': (5000, 'int'),
        'land_height_mm': (3000, 'int'),
        # -- 灯光 --
        'light_r': (0, 'int'),
        'light_g': (0, 'int'),
        'light_b': (0, 'int'),
        # -- autopilot 枚举（20=DMD_FC, 21=DMD_COM）--
        'autopilot': (21, 'int'),
        # -- 电池/电压相关字段（MAVLink msg_id=5, H=uint16_t, B=uint8_t）--
        'voltage_battery': (34000, 'uint16'),
        'voltage_battery_percent': (95, 'uint16'),
        'voltage_battery_diff': (0, 'uint16'),
        'voltage_battery_history_diff': (0, 'uint16'),
        'bat_serial_prefix': (b'V3F230324-', 'bytes'),
        'bat_serial_suffix': (b'3355', 'bytes'),
        'bat_serial_need_reset': (0, 'uint8'),
        'charge_state': (0, 'uint8'),
        'battery_time': (78, 'int'),
        'temp_batt': (0, 'int'),
        'battery_capability': (20, 'int'),
        'battery_used_times': (12, 'int'),
        'voltage_battery_cell1': (3500, 'int'),
        'voltage_battery_cell2': (3500, 'int'),
        'voltage_battery_cell3': (3500, 'int'),
        'voltage_battery_cell4': (3500, 'int'),
        'voltage_battery_cell5': (3500, 'int'),
        'voltage_battery_cell6': (3500, 'int'),
        'voltage_rid_bat': (0, 'int'),
    }

    # ---- 时序常量 ----
    _HEARTBEAT_INTERVAL = 5.0
    _STATUS_REPORT_INTERVAL = 5.0
    _HEARTBEAT_SEND_INTERVAL = 0.5
    _HANDSHAKE_TIMEOUT = 30.0

    # ---- 协议常量 ----
    _DEFAULT_SEQ = 604054808
    _DEFAULT_CODE = 1
    _DEFAULT_SERIAL = "WX10F0K00"

    # ---- 入站消息 ID ----
    _MSG_ID_HEARTBEAT = 0
    _MSG_ID_HEARTBEAT_DMD = 1
    _MSG_ID_GET_IDENTIFY_INFO = 3
    _MSG_ID_COMMAND_LONG = 76
    _MSG_ID_SWARM_FLIGHT_START = 50
    _MSG_ID_COMMAND_ACK = 77
    _MSG_ID_SET_MODE = 11
    _MSG_ID_PARAM_REQUEST_READ = 20
    _MSG_ID_PARAM_REQUEST_LIST = 21
    _MSG_ID_PARAM_SET = 23
    _MSG_ID_MISSION_REQUEST_VERIFY = 41
    _MSG_ID_CALIB_TIME = 46
    _MSG_ID_LIGHT_DATA = 55
    _MSG_ID_NET_FILE_COMMAND = 63

    # ---- 出站消息 ID ----
    _MSG_ID_TIME_ORIGIN = 47
    _MSG_ID_PARAM_VALUE = 22
    _MSG_ID_PARAM_REQUEST_LIST_ACK = 24
    _MSG_ID_MISSION_REQUEST_ACK = 42
    _MSG_ID_REMAINING_CAPACITY_STATE = 59

    _ALLOW_BEFORE_IDENTIFY = (0, 3)

    # ---- UavMode / FlyState / PlayState ----
    _UAV_MODE_G = 4
    _UAV_MODE_R = 6
    _UAV_MODE_LD = 9

    _FLY_DISARM = 0
    _FLY_LANDED = 1
    _FLY_GUIDE_IDLE = 2
    _FLY_GUIDE_TAKEOFF = 3
    _FLY_GUIDE_PLAY = 4
    _FLY_LAND = 5
    _FLY_RETURN = 6

    _PLAY_IDLE = 0
    _PLAY_DISARMED = 1
    _PLAY_WAIT_TK = 2
    _PLAY_TAKEOFF = 3
    _PLAY_FLYING = 4
    _PLAY_PLAYING = 5
    _PLAY_LANDING = 6
    _PLAY_LANDED = 7

    # ---- MAV_CMD ----
    _MAV_CMD_COMPONENT_ARM_DISARM = 400
    _MAV_CMD_CAN_ARM = 401
    _MAV_CMD_FLIGHT_STOP = 40003
    _MAV_CMD_CHANGE_MISSION = 40005
    _MAV_CMD_RETURN_TYPE = 40048

    # ---- NET_FILE ----
    _NET_FILE_OPEN = 0
    _NET_FILE_WRITE = 1
    _NET_FILE_READ = 2
    _NET_FILE_CLOSE = 3
    _NET_FILE_ACK = 4
    _NET_FILE_VERIFY = 5

    # ---- 握手状态机 ----
    _HS_IDLE = 0
    _HS_WAIT_ID_3 = 1
    _HS_WAIT_ID_1 = 2
    _HS_COMPLETED = 3
    _HS_FAILED = 4

    # ---- sensor_health 位表（16 bits）----
    _SENSOR_HEALTH_BITS = {
        'imu': 0, 'baro': 1, 'compass': 2, 'gps': 3,
        'battery': 4, 'bno_reset': 5, 'acc_calibrated': 6,
        'compass_calibrated': 7, 'color_calibrated': 8,
        'magnetic_calibrated': 9, 'scram': 10, 'esc': 11,
        'parachute': 12, 'tele': 13, 'bms': 14, 'module': 15,
    }
    _SENSOR_HEALTH_INVERTED_BITS = {12, 13, 14, 15}

    # ---- failsafe(0x06) 位表：故障名 → bit（对齐 C# AlarmCode Failsafe 掩码）----
    # C# 列表为 bit15→bit0 倒序（F_EKF_VERT=bit0 ... F_CRASH=bit15），
    # 参数名 = 枚举名小写化（f_ 前缀，避免与 battery/parachute 等现有字段冲突）。
    _FAILSAFE_BITS = {
        'f_crash': 15, 'f_radio': 14, 'f_battery': 13, 'f_fence_alt': 12,
        'f_fence_circle': 11, 'f_waypoint': 10, 'f_too_far': 9, 'f_static_dist': 8,
        'f_vibrate': 7, 'f_drama_fail': 6, 'f_parachute': 5, 'f_sensor_fail': 4,
        'f_fence_2': 3, 'f_ekf_stab': 2, 'f_ekf_horz': 1, 'f_ekf_vert': 0,
    }

    # ---- COMMAND_LONG 挂载点灯映射 ----
    _PAYLOAD_LIGHT_MAP = {
        3.0:  (1, 'firework_config', 'firework'),
        9.0:  (2, 'laser_config', 'laser'),
        12.0: (3, 'nova_config', 'nova'),
        14.0: (4, 'lantern_config', 'lantern'),
        15.0: (5, 'parachute_config', 'parachute'),
    }

    # ---- 模拟参数表 ----
    _DEFAULT_PARAM_TABLE = [
        ('SR0_PARAM', 4.0, 9),
        ('SYSID_THISMAV', 1.0, 9),
        ('FENCE_ENABLE', 1.0, 9),
        ('FENCE_ALT_MAX', 120.0, 9),
        ('WPNAV_SPEED', 500.0, 9),
        ('ANGLE_MAX', 3000.0, 9),
        ('BATT_CAPACITY', 22000.0, 9),
        ('RTL_ALT', 1500.0, 9),
        ('TKOFF_ALT', 500.0, 9),
        ('LAND_SPEED', 50.0, 9),
    ]

    # ---- 协议响应规则表（无状态回显）----
    _RESPONSE_RULES = {
        0: {
            'delay': None,
            'rules': [
                {'build': '_build_id_000', 'label': 'id=0(0x00)', 'state': {}},
            ],
        },
        3: {
            'delay': None,
            'rules': [
                {'build': '_build_id_002', 'label': 'id=2(0x02)',
                 'state': {'serial': 'serial', 'code': 'code'}},
            ],
        },
        1: {
            'delay': _HEARTBEAT_SEND_INTERVAL,
            'rules': [
                {'build': '_build_id_005', 'label': 'id=5(0x05)',
                 'state': {'wind_speed_x': 'wind_speed_x',
                           'wind_speed_y': 'wind_speed_y',
                           'seq': 'seq'}},
                {'build': '_build_id_008', 'label': 'id=8(0x08)',
                 'state': {'nova_light_version': 'nova_light_version',
                           'gimbal_version': 'gimbal_version'},
                 'when': lambda recv: recv.fields.get('extend') == 1},
                {'build': '_build_id_204', 'label': 'id=204(0xCC)',
                 'state': {'laser_state': 'laser_state',
                           'nova_state': 'nova_state',
                           'lantern_state': 'lantern_state',
                           'trumpet_state': 'trumpet_state',
                           'parachute_state': 'parachute_state'}},
            ],
        },
    }

    # ---- 有状态协议交互调度表 ----
    _STATE_RULES = {
        11: '_handle_set_mode',
        46: '_handle_calib_time',
        21: '_handle_param_request_list',
        20: '_handle_param_request_read',
        23: '_handle_param_set',
        63: '_handle_net_file_command',
        41: '_handle_mission_request_verify',
        50: '_handle_swarm_flight_start',
        55: '_handle_light_data',
        76: '_handle_command_long',
    }

    # ================================================================
    # __init__
    # ================================================================
    def __init__(self, ip_str, mavlink_version='45', serial=b'KWL50F0K', code=b'00000',
                 _parent_sender=None, _slot_index=None):
        self.ip = ip_str
        self.mavlink_version = mavlink_version
        self.serial = serial
        self._parent_sender = _parent_sender  # _FakeNestSender 实例引用
        self._slot_index = _slot_index        # uavIp 列表中的槽位索引 (0-4)
        self.code = code
        self.autopilot = 21
        self._parse_ip_prefix = False
        self.log_manager = None
        self.seq = 604054808

        self.wind_speed_x = 0
        self.wind_speed_y = 0

        self.laser_config = [0, 0, 0, 0]
        self.nova_config = 0
        self.lantern_config = 0
        self.trumpet_config = 0
        self.parachute_config = 0
        self.firework_config = 0

        self.laser_state = 0
        self.nova_state = 0
        self.lantern_state = 0
        self.trumpet_state = 0
        self.parachute_state = 0
        self.lantern = 0
        self.trumpet = 0
        self.parachute = 0

        self._sensor_imu = 1
        self._sensor_baro = 1
        self._sensor_compass = 1
        self._sensor_gps = 1
        self._sensor_battery = 1
        self._sensor_bno_reset = 1
        self._sensor_acc_calibrated = 1
        self._sensor_compass_calibrated = 1
        self._sensor_color_calibrated = 1
        self._sensor_magnetic_calibrated = 1
        self._sensor_scram = 1
        self._sensor_esc = 1
        self._sensor_parachute = 1
        self._sensor_tele = 1
        self._sensor_bms = 1
        self._sensor_module = 1

        self.flight_controller_version = b'n3.j.196'
        self.companion_version = b'V3.631'
        self.battery_version = b''
        self.gps_version = b'UM16982'
        self.servo_ver = 0
        self.tele_version = b'E013'
        self.bms_version = b''
        self.rid_version = b''
        self.gimbal_version = b''
        self.nova_light_version = b'1234'

        # ---- 电池/电压相关字段（可通过 update_bat 更新）----
        self.voltage_battery = 34000
        self.voltage_battery_percent = 95
        self.voltage_battery_diff = 0
        self.voltage_battery_history_diff = 0
        self.bat_serial_prefix = b'V3F230324-'
        self.bat_serial_suffix = b'3355'
        self.bat_serial_need_reset = 0
        self.charge_state = 0
        self.battery_time = 78
        self.temp_batt = 0
        self.battery_capability = 20
        self.battery_used_times = 12
        self.voltage_battery_cell1 = 3500
        self.voltage_battery_cell2 = 3500
        self.voltage_battery_cell3 = 3500
        self.voltage_battery_cell4 = 3500
        self.voltage_battery_cell5 = 3500
        self.voltage_battery_cell6 = 3500
        self.voltage_rid_bat = 0

        self.cur_lat = 226868664
        self.cur_lon = 1140224548
        self.tar_lat = 226868664
        self.tar_lon = 1140224548
        self.cur_alt = 0
        self.tar_alt = 0
        self.fix_type = 6          # 0-1: no fix, 2: 2D, 3: 3D, 4: DGPS, 5: RTK float, 6: RTK fixed

        self.mode = self._UAV_MODE_G
        self.armed = 0
        self.fly_state = self._FLY_DISARM
        self.play_state = self._PLAY_IDLE
        self.mission_id = 0
        self.loaded_missions = set()
        self.epoch_now_ms = 0
        self.takeoff_time_ms = 0
        self.play_time_ms = 0
        self.play_duration_ms = 0
        self.land_duration_ms = 4000
        self.takeoff_height_mm = 5000
        self.land_height_mm = 3000
        self._phase_start_ms = 0
        self.final_mode = self._UAV_MODE_R
        self.light_r = 0
        self.light_g = 0
        self.light_b = 0
        # -- msg_id=8 拓展心跳字段（原硬编码于 _build_id_008，可通过 update_state_extend 更新）--
        self.roll = 0.0
        self.pitch = 0.0
        self.yaw = 0.0
        self.temp_imu = 0.0
        self.temp_baro = 0.0
        self.anchor_hash = 0
        self.uas_code = b''
        self.laser_temperature = 25.0
        # v45 机巢定位字段：默认离巢态全零；出入巢动作经 _apply_nest_locating/
        # _clear_nest_locating 联动覆盖，手工 update_state_extend 设置后持续生效。
        self.is_inside_nest = 0
        self.loc_nest_layer = 0
        self.loc_nest_id = b'\x00' * 5
        self.loc_nest_sn = b'\x00' * 20
        # ---- failsafe(0x06) 故障状态（enable=False 默认不外发；未配置的故障位一律为 0）----
        self.enable_failsafe = False
        self.failsafe_flags = {name: 0 for name in self._FAILSAFE_BITS}
        self._flight_running = False
        self._flight_thread = None    # 飞行推进线程（对齐独立假飞机）
        self._flight_base_lat = 0     # 表演开始时的基准纬度（1e7 度）
        self._flight_base_lon = 0     # 表演开始时的基准经度（1e7 度）
        self._now_ms_override = None
        self._net_file = {}
        self._file_data_cache = {}    # CLOSE→VERIFY 中间缓存: {fname: bytes}，MISSION_REQUEST_VERIFY(41) 时清理
        self._landed_at_ms = 0
        self._params_set = {}

        # ---- bin 文件保存开关/路径（对齐独立假飞机策略，默认开启）----
        self.enable_bin_save = True
        self.bin_save_dir = self.DRAMA_SAVE_ROOT
        self._last_saved_bin_path = None   # 最近一次接收并保存的 bin 路径

        self._model = None
        self.param_dict = None
        self._param_queue = []
        self._param_queue_interval_s = 0.1

        self._identified = False
        self._lock = threading.Lock()

        self._last_heartbeat_time = 0.0
        self._last_status_report_time = 0.0

        self._hs_state = self._HS_IDLE
        self._hs_start_time = 0.0

        # ---- ACK 失败响应配置 ----
        # _ack_fail_count: 对所有 command 统一返回 result=4 的次数（0=禁用）
        self._ack_fail_count: int = 0
        # _ack_fail_counters: {command_id: current_count} — 各 command 已返回 result=4 的次数
        self._ack_fail_counters: dict[int, int] = {}
        # _ack_fail_last_time: {command_id: timestamp} — 各 command 上次收到的时间
        self._ack_fail_last_time: dict[int, float] = {}

        # ---- ACK 静默响应配置 ----
        # _ack_silence_count: 对所有 command 统一不回复的次数（0=禁用）
        self._ack_silence_count: int = 0
        # _ack_silence_counters: {command_id: current_count} — 各 command 已静默的次数
        self._ack_silence_counters: dict[int, int] = {}
        # _ack_silence_last_time: {command_id: timestamp} — 各 command 上次收到的时间
        self._ack_silence_last_time: dict[int, float] = {}

        # ---- 消息外发开关（单架飞机离线/上线） ----
        self._msg_forwarding_enabled = True  # True=上线(正常外发), False=离线(停止外发)

        # ---- 机巢外模式：自有 socket 直连地面站 ----
        self._external_mode = False
        self._gs_ip = None       # 地面站 IP（外模式时设置）
        self._gs_port = None     # 地面站端口（外模式时设置）
        self._sock = None        # 自有 UDP socket（延迟到 set_external_mode() 时创建）
        self._local_port = 0     # OS 分配的实际端口
        # 机巢内模式不需要自有 socket，避免端口占用和资源泄漏。
        # socket 在 set_external_mode() 中按需创建，set_internal_mode() / close() 中释放。

        # ---- 外模式接收线程（对齐独立假飞机 _FakeAirplaneMessageSender._run） ----
        self._external_receive_running = False
        self._external_receive_thread = None

        # ---- 消息注入回调（外模式收包 → UDP 监控） ----
        self._msg_injector = None  # Callable[[bytes,str,int,str,int],None] | None

        try:
            self._model = serial_to_model(self.serial)
            self.param_dict = UavParamDict(self._model)
            csv_filename = MODEL_TO_CSV.get(self._model, "X1_ParamList.csv")
            csv_path = os.path.join(_PARAM_CSV_BASE, csv_filename)
            if not self.param_dict.load_csv(csv_path):
                logger.warning(
                    f"[TEST] 飞机{self.ip} 参数 CSV 加载失败: {csv_path}"
                )
            else:
                logger.info(
                    f"[TEST] 飞机{self.ip} 机型={self._model} 参数表已加载"
                )
        except Exception as e:
            logger.warning(f"[TEST] 飞机{self.ip} 参数系统初始化异常: {e}")



    def _build_sensor_health(self):
        """根据各传感器状态构建 sensor_health 位掩码（16 bits）。

        bits 0-11: 0=正常, 1=异常（直通）
        bits 12-15: 取反：1=正常, 0=异常（内部存储 0=正常 → 寄存器写 1）
        """
        value = 0
        for sensor_name, bit in self._SENSOR_HEALTH_BITS.items():
            state = getattr(self, f'_sensor_{sensor_name}', 0)
            if bit in self._SENSOR_HEALTH_INVERTED_BITS:
                state = 1 - state  # 取反
            if state:
                value |= (1 << bit)
        return value


    def _build_id_000(self):
        """构建心跳的 id=0 消息。
        autopilot 字段：独立假飞机=20(DMD_FC)，机巢管理=21(DMD_COM)。
        """
        return MAVLink_message(msg_id=0, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS, seq=0,
                              version=self.mavlink_version,
                              fields={'autopilot': self.autopilot,
                                      'mavlink_version': int(self.mavlink_version)})


    def _build_id_002(self, serial="WX10F0K00002", code="1"):
        """构建身份信息的 id=2 消息。
        """
        return MAVLink_message(msg_id=2, seq=28, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                              version=self.mavlink_version,
                              fields={'serial': serial,
                                      'code': code})


    def _build_id_047(self, time_ms=None):
        """构建对时应答的 id=47 (TIME_ORIGIN) 消息。

        time: uint64，UTC 相对 1970-01-01 的毫秒数。
        """
        if time_ms is None:
            time_ms = self._now_ms()
        return MAVLink_message(msg_id=self._MSG_ID_TIME_ORIGIN, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.mavlink_version,
                               fields={'time': int(time_ms)})


    def _build_id_042(self, result=0):
        """构建 MISSION_REQUEST_ACK(42) 消息（result=0 表示 ACCEPTED）。"""
        return MAVLink_message(msg_id=self._MSG_ID_MISSION_REQUEST_ACK, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.mavlink_version,
                               fields={'result': result})


    def _build_id_059(self):
        """构建剩余续航状态 REMAINING_CAPACITY_STATE(59) 消息（1Hz 主动上报）。"""
        return MAVLink_message(msg_id=self._MSG_ID_REMAINING_CAPACITY_STATE, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.mavlink_version,
                               fields={
                                   'safe_fly_radius': 500.0,
                                   'remain_fly_time': 1200,
                                   'go_home_need_time': 60,
                                   'land_need_time': 30,
                                   'go_home_need_capacity': 500,
                                   'land_need_capacity': 300,
                                   'battery_total_capaticy': 22000,
                                   'battery_remain_capaticy': 20000,
                                   'battry_capacity_percentage': 90,
                               })

    def _build_id_006(self):
        """构建故障保护状态 FAILSAFE(6) 消息（enable_failsafe=True 时随 5s 状态周期外发）。

        failsafe: uint16 位掩码，每位对应一个故障（1=故障，见 _FAILSAFE_BITS）。
        """
        mask = 0
        for name, bit in self._FAILSAFE_BITS.items():
            if self.failsafe_flags.get(name):
                mask |= (1 << bit)
        return MAVLink_message(msg_id=6, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.mavlink_version,
                               fields={'failsafe': mask})


    def _build_id_022(self, chunk, start_index, total):
        """构建 PARAM_VALUE(22) 批量消息（一帧最多 8 个参数）。

        chunk: list[(name, value, ptype)]，长度 1~8。
        start_index: 本批首个参数的全局序号（仅用于日志，不填入消息）。
        total: 参数总数。

        对齐 C# CreateEmptyParam（FakeUavParser.cs:201）：
          param_type[8]  = 全 0（未填充）
          param_index[8] = 全 0（未填充）
        """
        values = [0.0] * 8
        indices = [0] * 8      # 恒 0，对齐 C# CreateEmptyParam
        types = bytearray(8)   # 恒 0，对齐 C# CreateEmptyParam
        names = bytearray(128)
        for i, (name, val, _ptype) in enumerate(chunk):
            values[i] = float(val)
            # indices[i] / types[i] 保持 0，不设置
            nb = name.encode('utf-8')[:16]
            names[i * 16:i * 16 + len(nb)] = nb
        return MAVLink_message(msg_id=self._MSG_ID_PARAM_VALUE, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.mavlink_version,
                               fields={
                                   'param_value': values,
                                   'param_index': indices,
                                   'param_count': len(chunk),
                                   'param_total': total,
                                   'param_id': bytes(names),
                                   'param_type': bytes(types),
                               })


    def _build_id_024(self, result=0):
        """构建 PARAM_REQUEST_LIST_ACK(24) 消息。"""
        return MAVLink_message(msg_id=self._MSG_ID_PARAM_REQUEST_LIST_ACK, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.mavlink_version,
                               fields={'result': result})


    def _build_id_063_ack(self, ack_data):
        """构建 NET_FILE_COMMAND(63) 的 ACK 消息（net_file_cmd=NET_FILE_ACK）。

        ack_data: 已按各操作 ACK 结构打包好的字节串（填入 data 字段）。
        """
        return MAVLink_message(msg_id=self._MSG_ID_NET_FILE_COMMAND, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.mavlink_version,
                               fields={'net_file_cmd': self._NET_FILE_ACK,
                                       'data': ack_data})


    def _build_id_005(self, wind_speed_x=0, wind_speed_y=0, sensor_health_extend=0,
                      seq=_DEFAULT_SEQ):
        """构建心跳消息的 id=5 消息。

        sensor_health_extend - bit0: rid   0x0-不存在 0x1-存在
                               bit1: gimbal 0x0-不存在 0x1-存在
                               bit2: nova  0x0-不存在 0x1-存在
        """
        return MAVLink_message(msg_id=5, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.mavlink_version,
                               fields={
                                    'seq': seq,
                                    "cur_lat": self.cur_lat,
                                    "cur_lon": self.cur_lon,
                                    "cur_alt": self.cur_alt,
                                    "tar_lat": self.tar_lat,
                                    "tar_lon": self.tar_lon,
                                    "tar_alt": self.tar_alt,
                                    'sensor_health': self._build_sensor_health(),
                                    'voltage_battery': self.voltage_battery,
                                    'voltage_battery_percent': self.voltage_battery_percent,
                                    'eph': 16,
                                    'wifi_up': 92,
                                    'mav_up_rate': 36,
                                    'ssid': b'd50',
                                    'fix_type': self.fix_type,
                                    'satellites_visible': 15,
                                    'rtk_quality': 65,
                                    'armed': self.armed,
                                    'mode': self.mode,
                                    'auth_constraint': 1,
                                    'fence_origin_set': 1,
                                    'home_set': 1,
                                    'fly_state': ((self.mission_id & 0x0f) << 4),
                                    'rtk_radio_850m': 72,
                                    'rc_radio': 99,
                                    'light_r': self.light_r,
                                    'light_g': self.light_g,
                                    'light_b': self.light_b,
                                    'play_state': self.play_state,
                                    'drama_state': 0,
                                    'voltage_battery_diff': self.voltage_battery_diff,
                                    'voltage_battery_history_diff': self.voltage_battery_history_diff,
                                    'restart_flag': 0,
                                    'bat_serial_prefix': self.bat_serial_prefix,
                                    'wind_speed_x': wind_speed_x,
                                    'wind_speed_y': wind_speed_y,
                                    'uwb_group': 0,
                                    'bat_serial_suffix': self.bat_serial_suffix,
                                    'bat_serial_need_reset': self.bat_serial_need_reset,
                                    'time_need_reset': 0,
                                    'elevation': 0,
                                    'boot_need_update': 0,
                                    'charge_state': self.charge_state,
                                    'lightpanel_state': 0,
                                    'sensor_health_middle': 0,
                                    'rc_matching_code': 0,
                                    'uav_speed_horz': 0,
                                    'sensor_health_extend': sensor_health_extend,
                                    'rtk_radio_2g4': 69,
                               })


    def _build_id_008(self, nova_light_version=None, gimbal_version=None):
        """构建拓展心跳消息的 id=8 消息（对齐 C# HandleHeartbeatDmd，receive.cs:109-143）。

        param_hash 使用 paramDict.ParamHash，让地面站可快速校验参数一致性。
        版本字段优先使用实例变量（可通过 update_version 更新），未设置时回退到默认值。

        v45 新增机巢定位字段（协议文档 §16）：
            - 飞机在巢内时：继承所在机巢的 nestId、nestSn，layer = slot_index + 1，
              is_inside_nest = 1。
            - 飞机离巢时（外模式 / 无 parent_sender）：全部置零。
        """
        param_hash = (self.param_dict.ParamHash
                      if self.param_dict is not None else 0)

        # v45 机巢定位字段：直接读实例属性（_apply_nest_locating /
        # _clear_nest_locating 在出入巢动作时联动更新，
        # update_state_extend 手工设置后持续生效，不被逐条消息重算覆盖）

        return MAVLink_message(msg_id=8, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.mavlink_version,
                               fields={
                                    "roll": self.roll,
                                    "pitch": self.pitch,
                                    "yaw": self.yaw,
                                    "battery_time": self.battery_time,
                                    "temp_imu": self.temp_imu,
                                    "temp_baro": self.temp_baro,
                                    "temp_batt": self.temp_batt,
                                    "param_hash": param_hash,
                                    "anchor_hash": self.anchor_hash,
                                    "battery_capability": self.battery_capability,
                                    "battery_used_times": self.battery_used_times,
                                    "voltage_battery_cell1": self.voltage_battery_cell1,
                                    "voltage_battery_cell2": self.voltage_battery_cell2,
                                    "voltage_battery_cell3": self.voltage_battery_cell3,
                                    "voltage_battery_cell4": self.voltage_battery_cell4,
                                    "voltage_battery_cell5": self.voltage_battery_cell5,
                                    "voltage_battery_cell6": self.voltage_battery_cell6,
                                    "flight_controller_version": self.flight_controller_version,
                                    "companion_version": self.companion_version,
                                    "battery_version": self.battery_version,
                                    "gps_version": self.gps_version,
                                    "servo_ver": self.servo_ver,
                                    "tele_version": self.tele_version,
                                    "bms_version": self.bms_version,
                                    "rid_version": self.rid_version,
                                    "gimbal_version": gimbal_version or self.gimbal_version,
                                    "voltage_rid_bat": self.voltage_rid_bat,
                                    "uas_code": self.uas_code,
                                    "laser_temperature": self.laser_temperature,
                                    "nova_light_version": nova_light_version or self.nova_light_version,
                                    # ── v45 新增：机巢定位字段（协议文档 §16）──
                                    "is_inside_nest": self.is_inside_nest,
                                    "loc_nest_layer": self.loc_nest_layer,
                                    "loc_nest_id": self.loc_nest_id,
                                    "loc_nest_sn": self.loc_nest_sn,
                                    "mavVer": int(MAVLINK_VERSION),
                               })


    def _build_id_060(self, payload_type, payload_channel):
        """构建挂载负载状态的 id=60 消息 (MAVLink_mount_payload_state_message)。

        payload_type:    负载类型 (uint8)
                         1-firework  2-laser  3-nova  4-lantern  5-parachute
        payload_channel: 负载通道配置，支持 int 或 list（自动转为位掩码 uint32）
        """
        # list → uint32 位掩码转换（如 laser_config [1,0,1,0] → 0x5）
        if isinstance(payload_channel, list):
            payload_channel = sum((int(b) & 1) << i for i, b in enumerate(payload_channel))
        return MAVLink_message(msg_id=60, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.mavlink_version,
                               fields={
                                   'payload_type': payload_type,
                                   'payload_channel': payload_channel,
                               })


    def _build_id_077_cmd(self, command, result=0):
        """构建 command_ack 的 id=77 消息（动态 command / result）。

        对齐独立假飞机 _FakeAirplaneMessageSender._build_id_077_cmd：
        - 始终返回 MAVLink_message（永不静默返回 None），保证 ACK 一定发出。
        - 支持 ACK 失败响应配置（_ack_fail_count）：前 N 次返回 result=4（FAILED），
          达到次数后返回 result=0（ACCEPTED）。10s 未收到该 command 则计数器重置。
        - ACK 静默由 update_ack(silence_count=N) 配置，通过 _skip_ack_for_silence()
          在调用方显式跳过，而非在构建器中隐式返回 None。

        Args:
            command: MAVLink command ID (uint16)
            result: MAV_RESULT（0=ACCEPTED，4=FAILED）
        """
        # 检查 ACK 失败响应配置（各 command 独立计数和计时）
        if self._ack_fail_count > 0:
            now = time.time()
            counter = self._ack_fail_counters.get(command, 0)
            last_time = self._ack_fail_last_time.get(command, 0)

            # 该 command 10s 未出现 → 重置计数器
            if now - last_time > 10.0:
                counter = 0

            if counter < self._ack_fail_count:
                result = 4  # MAV_RESULT_FAILED
                counter += 1
            else:
                result = 0  # MAV_RESULT_ACCEPTED

            self._ack_fail_counters[command] = counter
            self._ack_fail_last_time[command] = now

        return MAVLink_message(msg_id=77, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.mavlink_version,
                               fields={
                                   'command': command,
                                   'result': result,
                               })

    def _should_silence_ack(self, command: int) -> bool:
        """检查 ACK 静默配置：前 N 次应静默（不回复），之后回复。

        各 command 独立计数，10s 未收到该 command 则计数器自动重置。
        调用方在构建 ACK 前先调用本方法，返回 True 时跳过 _build_id_077_cmd()。
        """
        if self._ack_silence_count <= 0:
            return False
        now = time.time()
        counter = self._ack_silence_counters.get(command, 0)
        last_time = self._ack_silence_last_time.get(command, 0)

        # 该 command 10s 未出现 → 重置计数器
        if now - last_time > 10.0:
            counter = 0

        if counter < self._ack_silence_count:
            counter += 1
            self._ack_silence_counters[command] = counter
            self._ack_silence_last_time[command] = now
            return True  # 静默

        self._ack_silence_counters[command] = counter
        self._ack_silence_last_time[command] = now
        return False

    def _build_id_204(self, laser_state=0, nova_state=0,
                       lantern_state=0, trumpet_state=0, parachute_state=0):
        """构建负载告警状态的 id=204 消息。

        laser_state  低 4 位绿色，高 4 位蓝色：
            bit 0-3 / 4-7  1:低温(<-5℃,关闭)  2:低温告警  3:高温(降功率)  4:高温(关闭)
        nova_state   bit 0: 0x0-不存在 0x1-存在
                     bit 1: 0x0-温度正常 0x1-温度告警
        lantern_state: 折叠灯状态，沿用激光状态逻辑 (uint16_t)
        trumpet_state: 喇叭状态，沿用激光状态逻辑 (uint16_t)
        parachute_state: 降落伞状态，沿用激光状态逻辑 (uint16_t)
        """
        return MAVLink_message(msg_id=204, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.mavlink_version,
                               fields={
                                    "laser_state": laser_state,
                                    "nova_state": nova_state,
                                    "lantern_state": lantern_state,
                                    "trumpet_state": trumpet_state,
                                    "parachute_state": parachute_state,
                               })


    def _build_responses(self, received):
        """构建响应消息列表（不发送），供 _dispatch_request 和外部复用。

        Returns:
            list of (MAVLink_message, label) — 可能为空列表
        """
        batch = self._RESPONSE_RULES.get(received.msg_id)
        if batch is None:
            return []
        pending = []
        with self._lock:
            # 身份识别未完成前，仅允许心跳(msg=0)和身份(msg=3)，屏蔽其余所有响应
            if (received.msg_id != self._MSG_ID_HEARTBEAT
                    and received.msg_id != self._MSG_ID_GET_IDENTIFY_INFO
                    and not self._identified):
                return []
            for rule in batch['rules']:
                if rule.get('when') and not rule['when'](received):
                    continue
                try:
                    kwargs = {kw: getattr(self, attr) if isinstance(attr, str) else attr
                              for kw, attr in rule.get('state', {}).items()}
                    msg = getattr(self, rule['build'])(**kwargs)
                except Exception as e:
                    logger.error(f"[TEST] {rule['label']} 构建失败: {e}")
                    continue
                pending.append((msg, rule['label']))
            # msg 003 身份识别完成后，解锁后续响应
            if received.msg_id == self._MSG_ID_GET_IDENTIFY_INFO:
                self._identified = True
        return pending


    def _now_ms(self):
        """当前时刻（相对 1970 UTC 毫秒）。测试可通过 _now_ms_override 注入。"""
        if self._now_ms_override is not None:
            return self._now_ms_override
        return int(time.time() * 1000)


    @staticmethod
    def _clamp01(x):
        return 0.0 if x < 0 else (1.0 if x > 1 else x)


    def _handle_set_mode(self, received):
        """SET_MODE(11)：写入 self.mode 并回 COMMAND_ACK(command=11)。

        飞行中切 LD/R 触发降落/返航的逻辑在 Phase 3 的 _on_mode_changed 内补充。
        """
        custom = received.fields.get('custom_mode', 0)
        with self._lock:
            self.mode = custom
        self._on_mode_changed(custom)
        if self._should_silence_ack(self._MSG_ID_SET_MODE):
            return []
        msg = self._build_id_077_cmd(command=self._MSG_ID_SET_MODE)
        return [(msg, 'id=77(0x4D) SET_MODE_ACK')]


    def _on_mode_changed(self, custom_mode):
        """模式变化钩子：飞行中切 LD/R → 触发降落/返航。"""
        if custom_mode not in (self._UAV_MODE_LD, self._UAV_MODE_R):
            return
        with self._lock:
            if self.fly_state in (self._FLY_GUIDE_TAKEOFF, self._FLY_GUIDE_PLAY):
                self.final_mode = custom_mode
                self.fly_state = (self._FLY_RETURN if custom_mode == self._UAV_MODE_R
                                  else self._FLY_LAND)
                self.play_state = self._PLAY_LANDING
                self._phase_start_ms = self._now_ms()


    def _handle_calib_time(self, received):
        """CALIB_TIME(46)：记录对时基准 epoch_now_ms，回 TIME_ORIGIN(47)。

        time = 当前 UTC 相对 1970-01-01 的毫秒数，是后续 takeoff/play 绝对时刻的基准。
        """
        now_ms = self._now_ms()
        with self._lock:
            self.epoch_now_ms = now_ms
        return [(self._build_id_047(now_ms), 'id=47 TIME_ORIGIN')]


    def _handle_param_request_list(self, received):
        """PARAM_REQUEST_LIST(21)：对齐 C# HandleParam_Request_List（receive.cs:486-502）。

        1. 防重入：paramQueue 非空则忽略
        2. 全部 ParamTypes.Keys 入队，故意丢弃队首 5 个（模拟丢包）
        3. 分批（每批 ≤8）回 PARAM_VALUE(22)，末尾补 ACK(24)
        4. param_total = ParamTypes.Count（全表规模）
        """
        if self._param_queue:
            return []  # 防重入

        if self.param_dict is not None and self.param_dict.ParamTypes:
            # 使用 CSV 参数表
            keys = list(self.param_dict.ParamTypes.keys())
            total = len(keys)
            # 模拟丢包：丢弃队首 5 个参数
            keys = keys[5:]
            # 计算回传间隔：1000 / SR0_PARAM（秒）
            sr0 = self.param_dict.ParamsMustBe.get("SR0_PARAM", 10)
            self._param_queue_interval_s = max(0.05, 1.0 / max(1, int(sr0)))
        else:
            # 回退到内置参数表
            params = self._DEFAULT_PARAM_TABLE
            total = len(params)
            keys = [p[0] for p in params]
            self._param_queue_interval_s = 0.1

        # 全量入队（不含已丢弃的 5 个）
        self._param_queue = list(keys)

        out = []
        start = 0
        while self._param_queue:
            batch_names = []
            for _ in range(min(8, len(self._param_queue))):
                batch_names.append(self._param_queue.pop(0))
            batch = []
            for i, name in enumerate(batch_names):
                val = self._get_param_value(name)
                batch.append((name, val, 9))  # type=9 (MAV_PARAM_TYPE_INT32)
            out.append((self._build_id_022(batch, start, total),
                        f'id=22(0x16) PARAM_VALUE[{start}:{start + len(batch)}]'))
            start += len(batch)

        # 收尾 ACK
        out.append((self._build_id_024(0), 'id=24(0x18) PARAM_REQUEST_LIST_ACK'))
        return out

    # ------------------------------------------------------------------
    # 参数取值（对齐 C# GetParamValue，FakeUavParser.cs:214-227）
    # ------------------------------------------------------------------


    def _get_param_value(self, name: str) -> float:
        """返回某个参数的上报值。

        MustBe → 预期值；MustNotBe → 禁止值+0.1；其他 → 先查 _params_set 缓存，否则 0。
        """
        if self.param_dict is not None:
            return self.param_dict.get_param_value(name)
        # 回退：查内置 _DEFAULT_PARAM_TABLE
        for n, v, _ in self._DEFAULT_PARAM_TABLE:
            if n == name:
                return v
        # 查 SET_PARAM 写入过的参数
        if name in self._params_set:
            return self._params_set[name]
        return 0.0


    def _handle_param_request_read(self, received):
        """PARAM_REQUEST_READ(20)：对齐 C# HandleGetParam（receive.cs:437-456）。

        遍历 param_count 个 16B 槽位，每个在 ParamTypes 中存在的参数加入应答；
        未知参数静默跳过。param_total = 请求的 param_count。
        """
        param_id_b = received.fields.get('param_id', b'') or b''
        if isinstance(param_id_b, str):
            param_id_b = param_id_b.encode('latin-1')
        param_count = received.fields.get('param_count', 1)

        batch = []
        for i in range(param_count):
            slot_start = i * 16
            if len(param_id_b) < slot_start + 16:
                break
            slot = param_id_b[slot_start:slot_start + 16]
            name = slot.split(b'\x00', 1)[0].decode('utf-8', 'ignore')
            if not name:
                continue
            # 对齐 C#：仅当 name 在 ParamTypes 中存在时才加入应答
            if self.param_dict is not None and name in self.param_dict.ParamTypes:
                val = self._get_param_value(name)
                batch.append((name, val, 0))  # param_type=0 对齐 C# CreateEmptyParam
            elif name in dict(self._DEFAULT_PARAM_TABLE):
                val = self._get_param_value(name)
                batch.append((name, val, 0))

        if not batch:
            return []

        return [(self._build_id_022(batch, 0, param_count),
                 f'id=22(0x16) PARAM_VALUE(get) {[n for n,_,_ in batch]}')]


    def _handle_param_set(self, received):
        """PARAM_SET(23)：对齐 C# HandleSetParam（receive.cs:458-484）。

        1. 遍历 param_count 个 16B 槽位，逐个写入 + 回显
        2. 写入 ParamsMustBe / ParamsMustNotBe（两者都不在则仅回显不写）
        3. RefreshParamHash
        4. 回显走 GetParamValue（对齐 C#：写后取值，MustNotBe 会 +0.1）
        5. param_total 不赋值（对齐 C# CreateEmptyParam 默认 0）
        """
        fmt = '<8fHBB128s'
        size = struct.calcsize(fmt)
        payload = received.payload or b''
        if len(payload) < size:
            return []

        vals = struct.unpack(fmt, payload[:size])
        raw_values = vals[0:8]     # float[8]
        param_count = vals[8]       # UInt16
        param_id_b = vals[11]       # byte[128]

        changed = False
        batch = []
        for i in range(min(param_count, 8)):
            slot_start = i * 16
            if len(param_id_b) < slot_start + 16:
                break
            slot = param_id_b[slot_start:slot_start + 16]
            name = slot.split(b'\x00', 1)[0].decode('utf-8', 'ignore')
            if not name:
                continue

            with self._lock:
                self._params_set[name] = raw_values[i]
                if self.param_dict is not None:
                    if self.param_dict.set_param(name, raw_values[i]):
                        changed = True

            # 对齐 C#：回显走 GetParamValue（MustNotBe 会 +0.1）
            echo_val = self._get_param_value(name)
            batch.append((name, echo_val, 0))  # param_type=0 对齐 C# CreateEmptyParam

        if changed and self.param_dict is not None:
            self.param_dict.refresh_param_hash()

        if not batch:
            return []

        return [(self._build_id_022(batch, 0, 0),  # param_total=0 对齐 C#
                 f'id=22(0x16) PARAM_VALUE(set) {[(n,v) for n,v,_ in batch]}')]


    def _handle_light_data(self, received):
        """LIGHT_DATA(55)：起降灯光剧本，回 COMMAND_ACK(77, result=0)。"""
        if self._should_silence_ack(self._MSG_ID_LIGHT_DATA):
            return []
        msg = self._build_id_077_cmd(command=self._MSG_ID_LIGHT_DATA, result=0)
        return [(msg, 'id=77(0x4D) LIGHT_DATA ACK')]

    # ---- 剧本文件传输 NET_FILE_COMMAND(63) ---------------------------


    @staticmethod
    def _parse_mission_id(name):
        """从剧本文件名解析 mission_id：drama_{id}.dat / drama_merge_{id}.dat。

        drama_tk_* / drama_ld_*（起降灯光）不含 mission_id，返回 None。
        """
        m = re.search(r'drama_(?:merge_)?(\d+)', name)
        return int(m.group(1)) if m else None


    def _handle_net_file_command(self, received):
        """NET_FILE_COMMAND(63)：按 OPEN/WRITE/CLOSE 分片回 ACK，CLOSE 时登记 mission_id。

        与地面站推送端 net_file_write_file() 的 ACK 结构严格对齐。
        """
        cmd = received.fields.get('net_file_cmd', -1)
        data = received.fields.get('data', b'') or b''
        if isinstance(data, str):
            data = data.encode('latin-1')
        if cmd == self._NET_FILE_OPEN:
            return self._net_file_open(data)
        if cmd == self._NET_FILE_WRITE:
            return self._net_file_write(data)
        if cmd == self._NET_FILE_CLOSE:
            return self._net_file_close(data)
        if cmd == self._NET_FILE_VERIFY:
            return self._net_file_verify(data)
        return []


    def _net_file_open(self, data):
        # OPEN 请求数据: <hI64s = op_mode(2) + file_length(4) + filename(64)
        fmt = '<hI64s'
        op_mode, f_length, fname_b = struct.unpack(fmt, data[:struct.calcsize(fmt)])
        fname = fname_b.split(b'\x00', 1)[0].decode('utf-8', 'ignore')
        fid = 1
        mission_id = self._parse_mission_id(fname)
        with self._lock:
            self._net_file = {'fid': fid, 'name': fname, 'length': f_length,
                              'mission_id': mission_id, 'received': 0,
                              'buffer': bytearray(f_length) if f_length > 0 else bytearray()}
        # OPEN ACK: <hiIh64s = ack_cmd + fid(>=0) + file_length + op_mode + filename
        ack = struct.pack('<hiIh64s', self._NET_FILE_OPEN, fid, f_length,
                          op_mode, fname_b[:64])
        return [(self._build_id_063_ack(ack), f'id=63 NET_FILE ACK OPEN {fname}')]


    def _net_file_write(self, data):
        # WRITE 请求数据: <HiI + payload = send_len(2) + fid(4) + wr_pos(4) + data(变长, ≤240)
        fmt = '<HiI'
        send_len, fid, wr_pos = struct.unpack(fmt, data[:struct.calcsize(fmt)])
        payload = data[struct.calcsize(fmt):]
        write_return = send_len  # 默认成功
        with self._lock:
            transfer = self._net_file or None
            if transfer is None or transfer.get('fid') != fid:
                write_return = -1  # fid 不存在
            else:
                buf = transfer['buffer']
                actual = max(0, min(send_len, len(payload), len(buf) - wr_pos))
                if actual > 0:
                    buf[wr_pos:wr_pos + actual] = payload[:actual]
                transfer['received'] = wr_pos + send_len
                if actual != send_len:
                    write_return = actual  # 部分写入（超出缓冲区边界）
        # WRITE ACK: <hiiI = ack_cmd + write_return + fid + wr_pos
        ack = struct.pack('<hiiI', self._NET_FILE_WRITE, write_return, fid, wr_pos)
        return [(self._build_id_063_ack(ack), 'id=63 NET_FILE ACK WRITE')]


    def _net_file_close(self, data):
        # CLOSE 请求数据: <Hi = 保留(2) + fid(4)
        fmt = '<Hi'
        _, fid = struct.unpack(fmt, data[:struct.calcsize(fmt)])
        mission_id = None
        close_return = 0
        transfer = None
        with self._lock:
            transfer = self._net_file or None
            if transfer is None or transfer.get('fid') != fid:
                close_return = -1  # fid 不存在
                transfer = None
            else:
                mission_id = transfer.get('mission_id')
                if mission_id is not None:
                    self.loaded_missions.add(mission_id)
                # 缓存数据供后续 VERIFY(5) MD5 校验（对齐独立假飞机）；
                # MISSION_REQUEST_VERIFY(41) 成功时按 mission_id 最终清理
                fname = transfer.get('name', '')
                if fname:
                    self._file_data_cache[fname] = bytes(transfer.get('buffer') or b'')
                self._net_file = {}
        # 保存 .bin 文件（在锁外执行，避免 IO 阻塞）
        if transfer is not None and len(transfer.get('buffer') or b'') > 0:
            self._save_drama_bin(transfer)
        # CLOSE ACK: <hii = ack_cmd + close_return(>=0) + fid
        ack = struct.pack('<hii', self._NET_FILE_CLOSE, close_return, fid)
        return [(self._build_id_063_ack(ack),
                 f'id=63 NET_FILE ACK CLOSE mission={mission_id}')]

    def _net_file_verify(self, data):
        """VERIFY：从 _file_data_cache 取文件数据，计算 MD5 与地面站比对。

        VERIFY 发生在 CLOSE 之后，数据已在 _file_data_cache 中；这是剧本接收
        的最后一步——回 verify_return=0 表示接收完成，地面站据此结束下发流程
        （net_file_verify_file 收不到本 ACK 会重试 3 次后报失败）。
        VERIFY 请求数据: <16s64s = FMd5(16) + SzName(64)
        VERIFY ACK: <hi16s64s = ack_cmd(2) + VerifyReturn(4) + FMd5(16) + SzName(64)
        VerifyReturn: 0=匹配, 1=不匹配, -1=文件不存在
        """
        fmt = '<16s64s'
        gcs_md5, sz_name = struct.unpack(fmt, data[:struct.calcsize(fmt)])
        fname = sz_name.rstrip(b'\x00').decode('utf-8', 'ignore')
        verify_return = -1  # 默认：文件不存在
        actual_md5 = b'\x00' * 16
        with self._lock:
            buf = self._file_data_cache.get(fname)
            if buf is not None:
                actual_md5 = hashlib.md5(buf).digest()
                verify_return = 0 if actual_md5 == gcs_md5 else 1
        ack = struct.pack('<hi16s64s', self._NET_FILE_VERIFY, verify_return,
                          actual_md5, sz_name[:64])
        return [(self._build_id_063_ack(ack),
                 f'id=63 NET_FILE ACK VERIFY result={verify_return}')]

    # 剧本 bin 文件保存根目录（固定路径，不随 cwd 变化）
    DRAMA_SAVE_ROOT = r"D:\Work\dmd_autotest_project_ycl\tools\simulation_gui\output\drama"

    def _save_drama_bin(self, transfer: dict) -> str:
        """将接收完整的剧本数据保存为 .bin 文件。

        策略与独立假飞机 _save_drama_bin 一致：每次保存追加时间戳后缀
        （_YYYYMMDD_HHMMSS），避免覆盖历史文件。初始命名
        Nest_{机巢id}_{飞机id}_{时间戳}.bin；起飞指令(0x32)改名暂不实现。

        Args:
            transfer: {'name', 'length', 'mission_id', 'buffer', ...}

        Returns:
            保存的文件路径；若 enable_bin_save 为 False 则返回空字符串
        """
        if not self.enable_bin_save:
            return ""
        save_dir = self.bin_save_dir
        os.makedirs(save_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        nest_id = getattr(self._parent_sender, 'nestId', None)
        if isinstance(nest_id, (bytes, bytearray)):
            nest_id = nest_id[:5].decode('utf-8', 'ignore') or '00000'
        else:
            nest_id = '00000'  # 对齐 _sync_nest_locating_from_sender 的缺失回退
        safe_name = f'Nest_{nest_id}_{self.ip}_{timestamp}.bin'
        filepath = os.path.join(save_dir, safe_name)
        with open(filepath, 'wb') as f:
            f.write(bytes(transfer['buffer']))
        self._last_saved_bin_path = filepath
        logger.info(
            f"[TEST] 剧本文件已保存: {filepath} "
            f"(mission={transfer.get('mission_id')}, size={len(transfer['buffer'])} bytes)"
        )
        return filepath

    def update_bin_save(self, enable: bool = True, save_dir: str | None = None):
        """设置 bin 文件保存开关及保存路径（对齐独立假飞机 API，默认开启）。

        Args:
            enable: True=接收剧本后自动保存 Nest_{机巢id}_{飞机id}_{时间戳}.bin 到磁盘
            save_dir: 保存目录路径，为 None 时保持现有路径不变
        """
        with self._lock:
            self.enable_bin_save = bool(enable)
            if save_dir is not None:
                self.bin_save_dir = str(save_dir)

    @staticmethod
    def _format_play_time(play_ms: int) -> str:
        """将 0x32 play 字段（Unix 毫秒时间戳）格式化为 UTC 时间串 YYYYMMDD_HHMMSS.mmm。

        例：0x1A033AE6DB7 = 1787573464503 ms → 20260824_121104.503（UTC）。
        """
        millis = play_ms % 1000
        base = time.strftime('%Y%m%d_%H%M%S', time.gmtime(play_ms // 1000))
        return f"{base}.{millis:03d}"

    def _rename_last_bin_to_ip_time(self, play_ms: int) -> str:
        """收到 SWARM_FLIGHT_START(0x32) 后，将最近一次接收的 bin 重命名为【飞机IP_时间】。

        命名格式: ``{飞机IP}_YYYYMMDD_HHMMSS.SSS.bin``（时间来自 play 字段，UTC）。
        仅处理最近一次接收的 bin（不搜索旧文件）；若文件名已是该格式、
        或目标文件已存在、或未接收过 bin，则跳过，不覆盖已有文件。

        Args:
            play_ms: 0x32 消息 play 字段（Unix 毫秒时间戳）

        Returns:
            重命名后的新路径；跳过或失败返回空字符串
        """
        path = self._last_saved_bin_path
        if not path or not os.path.exists(path):
            return ""
        target_name = f"{self.ip}_{self._format_play_time(play_ms)}.bin"
        if os.path.basename(path) == target_name:
            return ""  # 文件名已是【飞机IP_时间】
        target_path = os.path.join(os.path.dirname(path), target_name)
        if os.path.exists(target_path):
            logger.info(f"[TEST] 重命名跳过（目标已存在）: {target_path}")
            return ""
        try:
            os.rename(path, target_path)
            self._last_saved_bin_path = target_path
            logger.info(f"[TEST] 已重命名 {os.path.basename(path)} → {target_name}")
            return target_path
        except Exception as e:
            logger.warning(f"[TEST] 重命名失败: {e}")
            return ""


    def _handle_mission_request_verify(self, received):
        """MISSION_REQUEST_VERIFY(41)：查剧本是否已加载，回 MISSION_REQUEST_ACK(42)。

        对齐 C# HandleMissionRequestVerify2 / 独立假飞机：
          - 检查 loaded_missions 中是否包含该 missionId
          - result=0 时清理 _file_data_cache 中与该 mission 关联的缓存（最终清理）
        result=0 表示 ACCEPTED，非 0 表示 FAILED。
        """
        mid = received.fields.get('id', 0)
        result = 0 if mid in self.loaded_missions else 1
        if result == 0:
            with self._lock:
                # 清理与该 mission_id 关联的 _file_data_cache 条目
                to_remove = [fname for fname in self._file_data_cache
                             if self._parse_mission_id(fname) == mid]
                for fname in to_remove:
                    del self._file_data_cache[fname]
        return [(self._build_id_042(result),
                 f'id=42(0x2A) MISSION_REQUEST_ACK id={mid} result={result}')]


    def _handle_command_long(self, received):
        """COMMAND_LONG(76) 统一处理：

          1. 状态副作用：ARM / DISARM / 急停（_apply_command_long_effects）。
          2. 挂载点灯：命中 param7 映射则回 MOUNT_PAYLOAD_STATE(id=60)。
          3. 未命中任何挂载规则时，兜底回 COMMAND_ACK(id=77, result=0)。
        """
        # 1) 状态副作用
        self._apply_command_long_effects(received)
        # 2) 挂载点灯
        pending = self._build_mount_payload_responses(received)
        # 3) 兜底 ACK（对齐独立假飞机：_build_id_077_cmd 永不返回 None）
        if not pending:
            command = received.fields.get('command', 0)
            if self._should_silence_ack(command):
                return pending
            msg = self._build_id_077_cmd(command=command)
            pending.append((msg, f'id=77(0x4D) cmd={command}'))
        return pending


    def _build_mount_payload_responses(self, received):
        """按 param1==1.0 且 param7 命中 _PAYLOAD_LIGHT_MAP 时，构建 id=60 挂载状态。"""
        if received.fields.get('param1') != 1.0:
            return []
        entry = self._PAYLOAD_LIGHT_MAP.get(received.fields.get('param7'))
        if entry is None:
            return []
        payload_type, config_attr, name = entry
        channel = getattr(self, config_attr)
        return [(self._build_id_060(payload_type, channel),
                 f'id=60(0x3c) {name}')]


    def _apply_command_long_effects(self, received):
        """COMMAND_LONG(76) 的状态副作用：ARM/DISARM、急停、切剧本、飞行中返航/降落。

        CAN_ARM(401) 无需状态改动，仅由兜底逻辑回 ACK(result=0) 表示"可解锁"；
        其余 ACK 均由 _handle_command_long 的兜底逻辑统一回传（command_ack, result=0）。
        """
        command = received.fields.get('command', 0)
        param1 = received.fields.get('param1', 0.0)
        if command == self._MAV_CMD_COMPONENT_ARM_DISARM:
            if param1 == 1.0:
                self._arm()
            elif param1 == 0.0:
                self._disarm()
        elif command == self._MAV_CMD_FLIGHT_STOP:
            # 起飞前(FlyGuideIdle/Landed) 急停：上锁复位
            if param1 == 0.0:
                self._flight_stop()
        elif command == self._MAV_CMD_CHANGE_MISSION:
            # 切换剧本：param1 为目标 mission_id（须已加载）
            mid = int(param1)
            with self._lock:
                if mid in self.loaded_missions:
                    self.mission_id = mid
        elif command == self._MAV_CMD_RETURN_TYPE:
            # 飞行中返航/降落：param1==0 → 返航(R)，否则降落(LD)
            self._on_mode_changed(self._UAV_MODE_R if param1 == 0.0
                                  else self._UAV_MODE_LD)


    def _arm(self):
        """解锁：仅当已切 G 模式且当前上锁未飞时生效（对齐 C# 前置条件）。"""
        with self._lock:
            if self.fly_state == self._FLY_DISARM and self.mode == self._UAV_MODE_G:
                self.armed = 1
                self.fly_state = self._FLY_LANDED
                self.play_state = self._PLAY_WAIT_TK
                self._landed_at_ms = self._now_ms()


    def _disarm(self):
        """上锁：仅当已解锁未起飞(Landed)时生效。"""
        with self._lock:
            if self.fly_state == self._FLY_LANDED:
                self.armed = 0
                self.fly_state = self._FLY_DISARM
                self.play_state = self._PLAY_DISARMED


    def _flight_stop(self):
        """急停：起飞前(Idle/Landed) 复位为上锁。"""
        with self._lock:
            if self.fly_state in (self._FLY_GUIDE_IDLE, self._FLY_LANDED):
                self.armed = 0
                self.fly_state = self._FLY_DISARM
                self.play_state = self._PLAY_DISARMED
        self._stop_flight()


    def _stop_flight(self):
        """停止飞行推进线程。"""
        self._flight_running = False

    # ---- 开始表演 SWARM_FLIGHT_START(50) + 飞行状态机 ----------------


    def _handle_swarm_flight_start(self, received):
        """SWARM_FLIGHT_START(50)：记录时刻并启动推进线程，回 COMMAND_ACK(50)。

        实测：真实地面站点击"开始表演"时**直接下发 SWARM_FLIGHT_START**，
        并不在同一会话重传剧本(NET_FILE)/对时(CALIB_TIME)——真机自持剧本。
        故桩不再硬性要求 `mission_id ∈ loaded_missions`，也不用 takeoff>now 拦截：
        只要当前处于地面待命态就接受(result=0) 并自主起飞；已在飞行中才拒绝。
        """
        takeoff = received.fields.get('takeoff', 0)
        play = received.fields.get('play', 0)
        ascend = received.fields.get('ascend', 0)
        descend = received.fields.get('descend', 0)
        final_mode = received.fields.get('final_mode', self._UAV_MODE_R)
        mission_id = received.fields.get('mission_id', 0)

        now = self._now_ms()
        # 收到 0x32 后，将最近一次接收的 bin 重命名为【飞机IP_时间】
        # （仅当原文件名非该格式时改名，不搜索旧文件；已是该格式则跳过）
        self._rename_last_bin_to_ip_time(play)
        # 仅当处于地面待命态才接受；已在飞行推进中(TAKEOFF/PLAY/LAND/RETURN)则拒绝
        ok = self.fly_state in (self._FLY_DISARM, self._FLY_LANDED,
                                self._FLY_GUIDE_IDLE)

        if ok:
            if mission_id not in self.loaded_missions:
                # 桩未经 NET_FILE 收到该剧本（真机自持），自动登记以放行后续校验
                logger.info(f"[TEST] SWARM: mission {mission_id} 未经下发，桩自动登记")
                self.loaded_missions.add(mission_id)
            with self._lock:
                self.mode = self._UAV_MODE_G
                self.armed = 1
                self.takeoff_time_ms = takeoff
                self.play_time_ms = play
                self.mission_id = mission_id
                self.final_mode = (final_mode if final_mode in
                                   (self._UAV_MODE_LD, self._UAV_MODE_R)
                                   else self._UAV_MODE_R)
                if ascend:
                    self.takeoff_height_mm = ascend
                if descend:
                    self.land_height_mm = descend
                self._flight_base_lat = self.cur_lat
                self._flight_base_lon = self.cur_lon
                self.fly_state = self._FLY_GUIDE_IDLE
                self.play_state = self._PLAY_WAIT_TK
                self._phase_start_ms = now
            self._start_flight()
            result = 0
        else:
            result = 4   # MAV_RESULT_FAILED（已在飞行中）

        msg = self._build_id_077_cmd(command=self._MSG_ID_SWARM_FLIGHT_START,
                                     result=result)
        return [(msg, f'id=77(0x4D) SWARM_FLIGHT_START ACK result={result}')]


    def _advance_flight(self):
        """飞行状态机单步推进（对应 C# ProcessFlyingCheck）。

        FlyGuideIdle → (到 takeoff) Takeoff → (到 play) Playing
                     → (播放结束) Landing → (落地) Landed → (+2s) Disarm。
        逐帧更新 cur_alt/cur_lat，play_state 对外反馈进度。
        """
        now = self._now_ms()
        stop_after = False
        with self._lock:
            st = self.fly_state
            if st == self._FLY_GUIDE_IDLE:
                if now >= self.takeoff_time_ms:
                    self.fly_state = self._FLY_GUIDE_TAKEOFF
                    self.play_state = self._PLAY_TAKEOFF
                    self._phase_start_ms = now
            elif st == self._FLY_GUIDE_TAKEOFF:
                frac = self._clamp01((now - self._phase_start_ms) /
                                     max(1, self.land_duration_ms))
                self.cur_alt = int(self.takeoff_height_mm * frac)
                if now >= self.play_time_ms:
                    self.fly_state = self._FLY_GUIDE_PLAY
                    self.play_state = self._PLAY_PLAYING
                    self.cur_alt = self.takeoff_height_mm
                    self._phase_start_ms = now
            elif st == self._FLY_GUIDE_PLAY:
                elapsed = now - self._phase_start_ms
                # 位置微动：有明确剧本时长则按进度推算，否则以 8s 为基做视觉效果
                dur_ref = self.play_duration_ms if self.play_duration_ms > 0 else 8000
                self.cur_lat = self._flight_base_lat + int(1000 * self._clamp01(elapsed / dur_ref))
                # 表演期间目标位置跟随当前位置（GUI 显式 update_position 持锁设值后，
                # 下一个 tick 才会进入此处覆盖，故 GUI 显式值优先级更高）
                self.tar_lat = self.cur_lat
                self.tar_lon = self.cur_lon
                # 仅当 play_duration_ms > 0 才自动进入降落（测试用）；
                # 默认 hang 在 Playing 直到地面站下达降落/返航指令（真机自持剧本）。
                if self.play_duration_ms > 0 and elapsed >= self.play_duration_ms:
                    self.mode = self.final_mode
                    self.fly_state = (self._FLY_RETURN
                                      if self.final_mode == self._UAV_MODE_R
                                      else self._FLY_LAND)
                    self.play_state = self._PLAY_LANDING
                    self._phase_start_ms = now
            elif st in (self._FLY_LAND, self._FLY_RETURN):
                frac = self._clamp01((now - self._phase_start_ms) /
                                     max(1, self.land_duration_ms))
                self.cur_alt = int(self.takeoff_height_mm * (1 - frac))
                if now - self._phase_start_ms >= self.land_duration_ms:
                    self.cur_alt = 0
                    self.fly_state = self._FLY_LANDED
                    self.play_state = self._PLAY_LANDED
                    self._landed_at_ms = now
            elif st == self._FLY_LANDED:
                # 落地后 2s 自动上锁
                if (self.mode in (self._UAV_MODE_LD, self._UAV_MODE_R)
                        and now - self._landed_at_ms >= 2000):
                    self.fly_state = self._FLY_DISARM
                    self.armed = 0
                    self.play_state = self._PLAY_DISARMED
                    # 复位为 G 模式，使地面站 CheckCanArm 通过、可再次开始表演
                    self.mode = self._UAV_MODE_G
                    stop_after = True
        if stop_after:
            self._flight_running = False

    def _start_flight(self):
        """启动飞行推进线程（周期 ~490ms 调用 _advance_flight，对齐独立假飞机）。

        用"线程存活"而非仅"标志位"判重入：close() 会置 _flight_running=False
        使 _flight_loop 退出，但若仅靠标志位，重新添加飞机后再来 SWARM 会误判
        为"仍在推进"而不重启线程。故这里以 is_alive() 为准。
        """
        if (self._flight_running and self._flight_thread is not None
                and self._flight_thread.is_alive()):
            return
        self._flight_running = True
        self._flight_thread = threading.Thread(
            target=self._flight_loop, daemon=True,
            name=f"NestAirplaneFlight-{self.ip}")
        self._flight_thread.start()

    def _flight_loop(self):
        # 退出时必须清 _flight_running，否则下次 _start_flight 会因标志残留
        # True 而拒绝重启（巢内飞机无 self.running，由 close() 置位退出）。
        try:
            while self._flight_running:
                try:
                    self._advance_flight()
                except Exception as e:
                    logger.error(f"[TEST] 飞机{self.ip} 飞行推进异常: {e}")
                time.sleep(0.49)
        finally:
            self._flight_running = False

    # ------------------------------------------------------------------
    # 消息构建（@staticmethod，原模块级 _build_xxx_msg 已迁移至此）
    # ------------------------------------------------------------------

    # ================================================================
    # 消息处理（由机巢接收线程调用）
    # ================================================================
    def process_message(self, received):
        """处理收到的消息，返回 [(MAVLink_message, label), ...]。

        调度顺序（完全对齐独立假飞机 _dispatch_request）：
          1. 握手消息（id=3 / id=1 extend=1）—— 机巢管理特有
          2. 有状态交互（_STATE_RULES）：命中后 return，不再查 _RESPONSE_RULES
          3. 无状态查表回显（_RESPONSE_RULES）：
             心跳(0) / 心跳DMD(1→0x05/0x08/0xCC) / 身份(3→0x02)

        注意：机巢内收到的地面站消息为特殊格式（帧头带 4 字节 IP 前缀），
        由 FakeNest.receive() 剥离后按标准 MAVLink 路由到本方法。
        """
        responses = []

        # ── 握手阶段：等待 GET_IDENTIFY_INFO (msg_id=3) ──
        if self._hs_state == self._HS_WAIT_ID_3 \
                and received.msg_id == self._MSG_ID_GET_IDENTIFY_INFO:
            msg = self._build_identify_info()
            self._hs_state = self._HS_WAIT_ID_1
            self._hs_start_time = time.time()
            self._identified = True
            responses.append((msg, 'id=2(0x02)_handshake'))
            logger.info(
                f"[TEST] 飞机{self.ip} 握手: 收到 id=3, 回复 id=2, 进入 WAIT_ID_1"
            )

        # ── 握手阶段：等待 HEARTBEAT_DMD extend=1 (msg_id=1) ──
        elif self._hs_state == self._HS_WAIT_ID_1 \
                and received.msg_id == self._MSG_ID_HEARTBEAT_DMD:
            if received.fields.get('extend') == 1:
                self._hs_state = self._HS_COMPLETED
                self._identified = True
                logger.info(f"[TEST] 飞机{self.ip} 握手完成 (COMPLETED)")

        # ── 1) 有状态交互 ──
        mid = received.msg_id
        gated = (not self._identified
                 and mid not in self._ALLOW_BEFORE_IDENTIFY)
        handler_name = self._STATE_RULES.get(mid)
        if handler_name is not None and not gated:
            pending = getattr(self, handler_name)(received) or []
            for msg, label in pending:
                responses.append((msg, f'state:{label}'))
            return responses

        # ── 2) 无状态查表回显 ──
        normal_responses = self._build_responses(received)
        return responses + normal_responses

    # ================================================================
    # 心跳 / 状态上报（由机巢周期线程调用）
    # ================================================================
    def build_heartbeat(self):
        """构建心跳 msg_id=0。"""
        return self._build_id_000()

    def needs_heartbeat(self, now):
        return (now - self._last_heartbeat_time) >= self._HEARTBEAT_INTERVAL

    def mark_heartbeat_sent(self, now):
        self._last_heartbeat_time = now

    def needs_status_report(self, now):
        """仅握手完成后才上报（外部模式飞机绕过握手门闩）。"""
        if self._external_mode:
            return (now - self._last_status_report_time) >= self._STATUS_REPORT_INTERVAL
        if self._hs_state != self._HS_COMPLETED:
            return False
        return (now - self._last_status_report_time) >= self._STATUS_REPORT_INTERVAL

    def mark_status_report_sent(self, now):
        self._last_status_report_time = now

    def build_remaining_capacity(self):
        """构建 id=59 (REMAINING_CAPACITY) 消息。

        持锁构建，与 _advance_flight() / process_message() 互斥，
        避免读取半更新状态。
        """
        with self._lock:
            return self._build_id_059()

    def build_packed_state(self):
        """构建 id=5 (PACKED_STATE) 消息。

        持锁构建，与 _advance_flight() / process_message() 互斥，
        避免读取半更新状态（多个字段之间存在逻辑一致性约束）。
        """
        with self._lock:
            return self._build_id_005(
                wind_speed_x=self.wind_speed_x,
                wind_speed_y=self.wind_speed_y,
                seq=self.seq,
            )

    # ================================================================
    # 握手状态机
    # ================================================================
    def start_handshake(self):
        """由周期线程在首次心跳外发后调用，启动握手流程。"""
        if self._hs_state == self._HS_IDLE:
            self._hs_state = self._HS_WAIT_ID_3
            self._hs_start_time = time.time()

    def check_handshake_timeout(self):
        """检查握手是否超时。"""
        if self._hs_state in (self._HS_WAIT_ID_3, self._HS_WAIT_ID_1):
            if time.time() - self._hs_start_time > self._HANDSHAKE_TIMEOUT:
                self._hs_state = self._HS_FAILED
                logger.warning(f"[TEST] 飞机{self.ip} 握手超时")

    @property
    def is_handshaked(self):
        return self._hs_state == self._HS_COMPLETED

    @property
    def handshake_failed(self):
        return self._hs_state == self._HS_FAILED

    @property
    def handshake_state_name(self):
        _names = {0: 'IDLE', 1: 'WAIT_ID_3', 2: 'WAIT_ID_1', 3: 'COMPLETED', 4: 'FAILED'}
        return _names.get(self._hs_state, 'UNKNOWN')

    def _build_identify_info(self):
        """构建握手响应 msg_id=2 (IDENTIFY_INFO, UAV->GCS)。"""
        return MAVLink_message(
            msg_id=2, seq=28, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
            version=self.mavlink_version,
            fields={'serial': self.serial, 'code': self.code},
        )

    # ================================================================
    # 状态更新（由外部 update_nest_state 驱动）
    # ================================================================
    def update_state(self, **fields):
        """更新飞机状态字段。"""
        with self._lock:
            for k, v in fields.items():
                if hasattr(self, k):
                    setattr(self, k, v)

    # ================================================================
    # 专用 update 方法（对齐独立假飞机 _FakeAirplaneMessageSender API）
    # ================================================================
    def update_wind_speed(self, wind_speed_x, wind_speed_y):
        """更新风速参数。"""
        with self._lock:
            self.wind_speed_x = wind_speed_x
            self.wind_speed_y = wind_speed_y

    def update_laser(self, laser_config, laser_state):
        """更新激光参数。"""
        with self._lock:
            self.laser_config = laser_config
            self.laser_state = laser_state

    def update_nova(self, nova_config, nova_state):
        """更新高亮灯参数。"""
        with self._lock:
            self.nova_config = nova_config
            self.nova_state = nova_state

    def update_firework(self, firework_config):
        """更新烟花参数（bit0~7 = 8 通道）。"""
        with self._lock:
            self.firework_config = firework_config

    def update_lantern(self, lantern_config, lantern_state, lantern):
        """更新折叠灯参数。"""
        with self._lock:
            self.lantern_config = lantern_config
            self.lantern_state = lantern_state
            self.lantern = lantern

    def update_trumpet(self, trumpet_config, trumpet_state, trumpet):
        """更新喇叭参数。"""
        with self._lock:
            self.trumpet_config = trumpet_config
            self.trumpet_state = trumpet_state
            self.trumpet = trumpet

    def update_parachute(self, parachute_config, parachute_state, parachute):
        """更新降落伞参数。"""
        with self._lock:
            self.parachute_config = parachute_config
            self.parachute_state = parachute_state
            self.parachute = parachute

    def update_failsafe(self, enable=False, f_crash=False, f_radio=False,
                        f_battery=False, f_fence_alt=False, f_fence_circle=False,
                        f_waypoint=False, f_too_far=False, f_static_dist=False,
                        f_vibrate=False, f_drama_fail=False, f_parachute=False,
                        f_sensor_fail=False, f_fence_2=False, f_ekf_stab=False,
                        f_ekf_horz=False, f_ekf_vert=False):
        """配置 failsafe(0x06) 故障位掩码并控制其随 5s 状态周期外发。

        enable: True=外发 0x06；False=不外发（默认）

        16 个故障位参数（1/True=置位；未配置的故障位一律置 0，全量覆盖语义）：

        f_crash        : bit15 — 坠机 (F_CRASH)
        f_radio        : bit14 — 电台失联 (F_RADIO)
        f_battery      : bit13 — 低电 (F_BATTERY)
        f_fence_alt    : bit12 — 高度围栏 (F_FENCE_ALT)
        f_fence_circle : bit11 — 水平围栏 (F_FENCE_CIRCLE)
        f_waypoint     : bit10 — 航点失败 (F_WAYPOINT)
        f_too_far      : bit9  — 距离过远 (F_TOO_FAR)
        f_static_dist  : bit8  — 静态距离 (F_STATIC_DIST)
        f_vibrate      : bit7  — 震动 (F_VIBRATE)
        f_drama_fail   : bit6  — 剧本失败 (F_DRAMA_FAIL)
        f_parachute    : bit5  — 降落伞 (F_PARACHUTE)
        f_sensor_fail  : bit4  — 传感器故障 (F_SENSOR_FAIL)
        f_fence_2      : bit3  — 二级围栏 (F_FENCE_2)
        f_ekf_stab     : bit2  — EKF 定高 (F_EKF_STAB)
        f_ekf_horz     : bit1  — EKF 水平 (F_EKF_HORZ)
        f_ekf_vert     : bit0  — EKF 垂直 (F_EKF_VERT)
        """
        with self._lock:
            self.enable_failsafe = bool(enable)
            values = {
                'f_crash': f_crash, 'f_radio': f_radio, 'f_battery': f_battery,
                'f_fence_alt': f_fence_alt, 'f_fence_circle': f_fence_circle,
                'f_waypoint': f_waypoint, 'f_too_far': f_too_far,
                'f_static_dist': f_static_dist, 'f_vibrate': f_vibrate,
                'f_drama_fail': f_drama_fail, 'f_parachute': f_parachute,
                'f_sensor_fail': f_sensor_fail, 'f_fence_2': f_fence_2,
                'f_ekf_stab': f_ekf_stab, 'f_ekf_horz': f_ekf_horz,
                'f_ekf_vert': f_ekf_vert,
            }
            self.failsafe_flags = {name: 1 if values[name] else 0
                                   for name in self._FAILSAFE_BITS}

    def update_ack(self, fail_count=0, silence_count=0):
        """配置所有 command 的 ACK 响应失败/静默次数。

        fail_count: 前 N 次返回 result!=0，之后返回 result=0。
        silence_count: 前 N 次不回复（静默），之后返回 result=0。
        各 command 独立计数，10s 未收到该 command 则其计数器自动重置为 0。

        Args:
            fail_count: 失败次数（>=0），设为 0 则禁用（始终返回 result=0）
            silence_count: 静默次数（>=0），设为 0 则禁用（始终立即回复）
        """
        with self._lock:
            self._ack_fail_count = fail_count
            self._ack_fail_counters.clear()
            self._ack_fail_last_time.clear()
            self._ack_silence_count = silence_count
            self._ack_silence_counters.clear()
            self._ack_silence_last_time.clear()

    def update_msg_forwarding(self, enabled: bool = True):
        """设置飞机消息是否外发（上线/离线）。

        Args:
            enabled: True=上线(正常外发), False=离线(停止外发)
        """
        with self._lock:
            self._msg_forwarding_enabled = enabled

    def update_state_extend(self, **fields):
        """统一更新消息 8（id=8 拓展心跳）中的所有可配置字段。

        支持的关键字：roll / pitch / yaw / battery_time / temp_imu /
        temp_baro / temp_batt / anchor_hash / battery_capability /
        battery_used_times / voltage_battery_cell1 / voltage_battery_cell2 /
        voltage_battery_cell3 / voltage_battery_cell4 / voltage_battery_cell5 /
        voltage_battery_cell6 / voltage_rid_bat / uas_code /
        laser_temperature / flight_controller_version / companion_version /
        battery_version / gps_version / servo_ver / tele_version /
        bms_version / rid_version / gimbal_version / nova_light_version /
        is_inside_nest / loc_nest_layer / loc_nest_id / loc_nest_sn

        roll / pitch / yaw                       : float
        battery_time                             : int (秒)
        temp_imu / temp_baro / temp_batt         : float
        anchor_hash                              : int (uint32)
        battery_capability / battery_used_times  : int (uint16)
        voltage_battery_cell1~6                  : int (mV, uint16)
        voltage_rid_bat                          : int (uint16)
        uas_code                                 : bytes (20B)
        laser_temperature                        : float
        flight_controller_version (FC_Version)   : bytes (8B)
        companion_version                        : bytes (8B)
        battery_version                          : bytes (8B)
        gps_version                              : bytes (8B)
        servo_ver                                : int (uint8)
        tele_version                             : bytes (4B)
        bms_version                              : bytes (4B)
        rid_version                              : bytes (8B)
        gimbal_version                           : bytes (4B)
        nova_light_version                       : bytes (4B)
        is_inside_nest                           : int (uint8, 0/1)
        loc_nest_layer                           : int (uint8)
        loc_nest_id                              : bytes (5B)
        loc_nest_sn                              : bytes (20B)

        注意：is_inside_nest / loc_nest_* 为 v45 机巢定位字段，手工设置后
        持续生效；仅出巢（_clear_nest_locating）/入巢（_apply_nest_locating）
        动作联动覆盖。机巢改号（update_nest_extend / SET_CODE_NUMBER）不
        覆盖手工值。param_hash（参数字典）与 mavVer（协议版本）为协议动态
        字段，不在白名单。

        示例:
            airplane.update_state_extend(
                roll=1.5, laser_temperature=30.0,
                uas_code=b'ABCD', anchor_hash=99,
            )
        """
        _VALID_EXTEND_KEYS = {
            'roll', 'pitch', 'yaw', 'battery_time',
            'temp_imu', 'temp_baro', 'temp_batt', 'anchor_hash',
            'battery_capability', 'battery_used_times',
            'voltage_battery_cell1', 'voltage_battery_cell2',
            'voltage_battery_cell3', 'voltage_battery_cell4',
            'voltage_battery_cell5', 'voltage_battery_cell6',
            'voltage_rid_bat', 'uas_code', 'laser_temperature',
            'flight_controller_version', 'companion_version',
            'battery_version', 'gps_version', 'servo_ver', 'tele_version',
            'bms_version', 'rid_version', 'gimbal_version',
            'nova_light_version', 'is_inside_nest', 'loc_nest_layer',
            'loc_nest_id', 'loc_nest_sn',
        }
        with self._lock:
            for key, value in fields.items():
                if key in _VALID_EXTEND_KEYS:
                    setattr(self, key, value)

    def _apply_nest_locating(self, sender, slot_index):
        """按所在机巢与槽位联动更新消息 8 的机巢定位字段（入巢/创建飞机时调用）。

        覆盖 update_state_extend 的手工值；机巢 nestId/nestSn 变化时由
        _FakeNestSender._refresh_airplanes_nest_locating 再次调用保持联动。
        nestId/nestSn 缺失时（测试桩/早期初始化）回退零值与默认填充。
        """
        self.is_inside_nest = 1
        self.loc_nest_layer = int(slot_index) + 1            # 0-based → 1-based
        # nestId 为 5 字节 char[5]，直接使用或补齐
        nest_id = getattr(sender, 'nestId', None)
        if isinstance(nest_id, bytes):
            self.loc_nest_id = nest_id[:5].rjust(5, b'0')
        else:
            self.loc_nest_id = b'00000'
        nest_sn = getattr(sender, 'nestSn', b'')
        if isinstance(nest_sn, str):
            nest_sn = nest_sn.encode('utf-8')
        if not nest_sn:
            nest_sn = b'\x00' * 20
        self.loc_nest_sn = (nest_sn[:20] if len(nest_sn) >= 20
                            else nest_sn.ljust(20, b'\x00'))

    def _clear_nest_locating(self):
        """离巢：消息 8 的机巢定位字段全部置零（出巢动作时调用）。"""
        self.is_inside_nest = 0
        self.loc_nest_layer = 0
        self.loc_nest_id = b'\x00' * 5
        self.loc_nest_sn = b'\x00' * 20

    def update_version(self, **kwargs):
        """统一更新版本信息，后续发送 id=8 消息时使用新值。

        支持的关键字：flight_controller_version / companion_version /
        battery_version / gps_version / servo_ver / tele_version /
        bms_version / rid_version / gimbal_version / nova_light_version

        flight_controller_version (FC_Version) : bytes (8B)
        companion_version                     : bytes (8B)
        battery_version                       : bytes (8B)
        gps_version                           : bytes (8B)
        servo_ver                             : int
        tele_version                          : bytes (4B)
        bms_version                           : bytes (4B)
        rid_version                           : bytes (8B)
        gimbal_version                        : bytes (4B)
        nova_light_version                    : bytes (4B)

        示例:
            airplane.update_version(
                nova_light_version=b"1000",
                flight_controller_version=b"n3.k.200",
                servo_ver=1,
            )
        """
        _VALID_VERSION_KEYS = {
            'flight_controller_version', 'companion_version', 'battery_version',
            'gps_version', 'servo_ver', 'tele_version', 'bms_version',
            'rid_version', 'gimbal_version', 'nova_light_version',
        }
        with self._lock:
            for key, value in kwargs.items():
                if key in _VALID_VERSION_KEYS:
                    setattr(self, key, value)

    def update_sensor_health(self, **kwargs):
        """更新 sensor_health 各传感器状态，后续发送使用新参数。

        支持的关键字：imu / baro / compass / gps / battery / bno_reset /
        acc_calibrated / compass_calibrated / color_calibrated /
        magnetic_calibrated / scram / esc / parachute / tele / bms / module

        ┌─────┬─────────────────────┬──────────────────────┐
        │ Bit │        含义         │       取值逻辑       │
        ├─────┼─────────────────────┼──────────────────────┤
        │ 0   │ IMU                 │ 0=正常，1=异常       │
        │ 1   │ Baro（气压计）      │ 0=正常，1=异常       │
        │ 2   │ Compass / BNO       │ 0=正常，1=异常       │
        │ 3   │ GPS / UWB           │ 0=正常，1=异常       │
        │ 4   │ Battery             │ 0=正常，1=异常       │
        │ 5   │ BnoReset            │ 0=正常，1=异常       │
        │ 6   │ Acc calibrated      │ 0=正常，1=异常       │
        │ 7   │ Compass calibrated  │ 0=正常，1=异常       │
        │ 8   │ Color calibrated    │ 0=正常，1=异常       │
        │ 9   │ Magnetic calibrated │ 0=正常，1=异常       │
        │ 10  │ Scram               │ 0=正常，1=异常       │
        │ 11  │ ESC                 │ 0=正常，1=异常       │
        │ 12  │ Parachute           │ 取反：1=正常，0=异常 │
        │ 13  │ Tele                │ 取反：1=正常，0=异常 │
        │ 14  │ BMS                 │ 取反：1=正常，0=异常 │
        │ 15  │ Module              │ 取反：1=正常，0=异常 │
        └─────┴─────────────────────┴──────────────────────┘
        """
        with self._lock:
            for name, state in kwargs.items():
                attr = f'_sensor_{name}'
                if hasattr(self, attr):
                    setattr(self, attr, int(state))

    def update_param_hash(self, value=None, source=0):
        """更新 param_hash。

        Args:
            value: 手动设置时的 hash 值（source=1 时必须提供）
            source: 1=手动设置（直接覆盖 param_dict.ParamHash），
                    0=自动计算（从 param_dict 重新 refresh）
        """
        with self._lock:
            if source == 1:
                if self.param_dict is not None and value is not None:
                    self.param_dict.ParamHash = int(value)
            elif source == 0:
                if self.param_dict is not None:
                    self.param_dict.refresh_param_hash()

    def update_position(self, cur_lat, cur_lon, tar_lat, tar_lon,
                       cur_alt=0, tar_alt=0, fix_type=6):
        """更新当前位置、目标位置和 GPS 定位类型。

        cur_lat: 当前纬度 (MAVLink I=uint32_t, 1e7 度)
        cur_lon: 当前经度 (MAVLink I=uint32_t, 1e7 度)
        tar_lat: 目标纬度 (MAVLink I=uint32_t, 1e7 度)
        tar_lon: 目标经度 (MAVLink I=uint32_t, 1e7 度)
        cur_alt: 当前高度 (MAVLink I=uint32_t, mm)
        tar_alt: 目标高度 (MAVLink I=uint32_t, mm)
        fix_type: GPS 定位类型 (MAVLink B=uint8_t, 0-1: no fix, 2: 2D, 3: 3D,
                  4: DGPS, 5: RTK float, 6: RTK fixed)
        """
        with self._lock:
            self.cur_lat = cur_lat
            self.cur_lon = cur_lon
            self.tar_lat = tar_lat
            self.tar_lon = tar_lon
            self.cur_alt = cur_alt
            self.tar_alt = tar_alt
            self.fix_type = fix_type

    def update_bat(self, **kwargs):
        """统一更新电池/电压相关字段，后续发送 id=5/id=8 消息时使用新值。

        支持的关键字：voltage_battery / voltage_battery_percent /
        voltage_battery_diff / voltage_battery_history_diff /
        bat_serial_prefix / bat_serial_suffix / bat_serial_need_reset /
        charge_state / battery_time / temp_batt / battery_capability /
        battery_used_times / voltage_battery_cell1 / voltage_battery_cell2 /
        voltage_battery_cell3 / voltage_battery_cell4 / voltage_battery_cell5 /
        voltage_battery_cell6 / voltage_rid_bat

        voltage_battery              : int   — 电池电压 (mV)，默认 34000
        voltage_battery_percent      : int   — 电池电量百分比，默认 95
        voltage_battery_diff         : int   — 电池电压差 (mV)，默认 0
        voltage_battery_history_diff : int   — 历史电池电压差 (mV)，默认 0
        bat_serial_prefix            : bytes — 电池序列号前缀，默认 b'V3F230324-'
        bat_serial_suffix            : bytes — 电池序列号后缀，默认 b'3355'
        bat_serial_need_reset        : int   — 电池序列号需重置标志，默认 0
        charge_state                 : int   — 充电状态，默认 0
        battery_time                 : int   — 电池使用时间，默认 78
        temp_batt                    : int   — 电池温度，默认 0
        battery_capability           : int   — 电池容量，默认 20
        battery_used_times           : int   — 电池使用次数，默认 12
        voltage_battery_cell1~6      : int   — 电芯1~6电压 (mV)，默认 3500
        voltage_rid_bat              : int   — RID 电池电压 (mV)，默认 0

        示例:
            airplane.update_bat(voltage_battery=35000, voltage_battery_percent=80,
                                battery_time=100)
        """
        _VALID_BAT_KEYS = {
            'voltage_battery', 'voltage_battery_percent',
            'voltage_battery_diff', 'voltage_battery_history_diff',
            'bat_serial_prefix', 'bat_serial_suffix', 'bat_serial_need_reset',
            'charge_state', 'battery_time', 'temp_batt', 'battery_capability',
            'battery_used_times',
            'voltage_battery_cell1', 'voltage_battery_cell2',
            'voltage_battery_cell3', 'voltage_battery_cell4',
            'voltage_battery_cell5', 'voltage_battery_cell6',
            'voltage_rid_bat',
        }
        with self._lock:
            for key, value in kwargs.items():
                if key in _VALID_BAT_KEYS:
                    setattr(self, key, value)

    # ================================================================
    # IP 前缀解析控制
    # ================================================================
    def enable_ip_prefix_parsing(self):
        """启用 IP 前缀解析。"""
        self._parse_ip_prefix = True

    # ================================================================
    # 机巢外模式：飞机通过自有 socket 直接与地面站通信
    # ================================================================
    def _ensure_ip_on_interface(self):
        """确保飞机 IP 已添加到本机网卡（对齐 FakeNest._setup_network）。

        巢内模式下飞机 IP 由机巢 IP 前缀路由，无需真实绑定到本机；
        切换巢外时飞机需要用自己的 IP 直发消息，必须先将 IP 加到网卡。
        """
        # 快速路径：IP 已存在
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind((self.ip, 0))
            s.close()
            logger.info(f"[TEST] 飞机{self.ip} IP 已存在于本机接口，跳过添加")
            return True
        except OSError:
            pass

        # 通过 PowerShell 添加辅助 IP
        interface = NETCARD_INTERFACE
        if not interface:
            logger.error("[TEST] NETCARD_INTERFACE 未配置，无法添加辅助 IP")
            return False

        ps_cmd = (
            f'powershell -NoProfile -Command '
            f'"New-NetIPAddress -InterfaceAlias \'{interface}\' '
            f'-IPAddress \'{self.ip}\' -PrefixLength 24"'
        )
        logger.info(f"[TEST] 在 {interface} 上添加辅助IP: {self.ip}")
        ret = os.system(ps_cmd)
        if ret != 0:
            logger.error(f"[TEST] New-NetIPAddress 执行失败，返回码: {ret}")
            return False
        logger.info(f"[TEST] 飞机{self.ip} 辅助IP 添加成功")
        return True

    def set_external_mode(self, gs_ip: str, gs_port: int):
        """切换到机巢外模式：消息通过飞机自有 socket 直发地面站。

        外发时不再拼接 IP 前缀（源 IP 即为飞机 IP）；收到消息时由巢路由到
        process_message()，响应同样走 send_external()。

        关键步骤：
        1. 关闭 __init__ 中创建的旧 socket（可能已 fallback 到 0.0.0.0:随机端口）
        2. 将飞机 IP 添加到本机网卡（巢内时 IP 仅由机巢路由，未真实绑到本机）
        3. 创建新 socket 并 bind 到 (飞机IP, 14551)
        4. 带重试：IP 刚添加后可能尚未立即生效（winerror 10049）

        Args:
            gs_ip: 地面站 IP
            gs_port: 地面站端口
        """
        # 1) 关闭旧 socket
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        # 2) 确保飞机 IP 在本机网卡上
        if not self._ensure_ip_on_interface():
            logger.warning(
                f"[TEST] 飞机{self.ip} 无法将 IP 添加到网卡，"
                f"socket bind 将回退到 0.0.0.0"
            )

        # 3) 创建 socket 并 bind 到 (飞机IP, 14551)，带重试
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        max_retries = 10
        for attempt in range(1, max_retries + 1):
            try:
                self._sock.bind((self.ip, 14551))
                actual = self._sock.getsockname()
                self._local_port = actual[1]
                self._sock.settimeout(0.05)
                logger.info(
                    f"[TEST] 飞机 socket 绑定成功: {actual} "
                    f"(尝试 {attempt}/{max_retries})"
                )
                break
            except OSError as e:
                if hasattr(e, 'winerror') and e.winerror == 10049 and attempt < max_retries:
                    logger.info(
                        f"[TEST] 飞机{self.ip} IP 未生效，"
                        f"1s 后重试 ({attempt + 1}/{max_retries})"
                    )
                    time.sleep(1)
                else:
                    # 绑定失败，回退到 INADDR_ANY:14551
                    logger.warning(
                        f"[TEST] 飞机{self.ip} bind 失败: {e}，"
                        f"回退到 0.0.0.0:14551"
                    )
                    try:
                        self._sock.bind(('0.0.0.0', 14551))
                        actual = self._sock.getsockname()
                        self._local_port = actual[1]
                        self._sock.settimeout(0.05)
                        logger.info(
                            f"[TEST] 飞机 socket 回退绑定: {actual}"
                        )
                    except Exception as e2:
                        logger.error(
                            f"[TEST] 飞机{self.ip} socket 创建完全失败: {e2}"
                        )
                        self._sock.close()
                        self._sock = None
                    break

        self._external_mode = True
        self._gs_ip = gs_ip
        self._gs_port = gs_port
        self._parse_ip_prefix = True  # 外模式时自动启用 IP 前缀解析

        # 从父 sender 继承消息注入回调（外模式收包 → UDP 监控）
        if self._parent_sender is not None and \
           getattr(self._parent_sender, '_msg_injector', None) is not None:
            self._msg_injector = self._parent_sender._msg_injector

        # 4) 最终诊断：打印 socket 实际绑定地址
        if self._sock is not None:
            actual_addr = self._sock.getsockname()
            logger.info(
                f"[TEST] 飞机{self.ip} 已切换到机巢外模式 "
                f"socket={actual_addr} → {gs_ip}:{gs_port}"
            )
        else:
            logger.warning(
                f"[TEST] 飞机{self.ip} 外模式标志已设置但 socket 不可用"
            )

        # 5) 启动外模式接收线程（对齐独立假飞机 _FakeAirplaneMessageSender._run）
        self._external_receive_running = True
        self._external_receive_thread = threading.Thread(
            target=self._external_receive_loop, daemon=True
        )
        self._external_receive_thread.start()

        return True

    def set_internal_mode(self):
        """切回机巢内模式：消息由机巢包装外发。

        重置握手状态机，确保机巢周期线程重新发起握手流程。
        外部模式期间与地面站建立的会话状态在机巢内模式中无效——
        机巢内消息经 IP 前缀包装后，地面站将其视为新设备。
        """
        # 停止外模式接收线程
        self._external_receive_running = False
        self._external_mode = False
        if self._external_receive_thread is not None:
            if self._external_receive_thread.is_alive():
                self._external_receive_thread.join(timeout=2)
            self._external_receive_thread = None
        # 关闭外部模式创建的 socket，避免 fd 泄漏
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        # 归巢时握手状态处理：
        # - 已 COMPLETED：保留（地面站可能不重新握手，重置会死锁；状态消息照常外发）。
        # - 未 COMPLETED（IDLE/WAIT/FAILED）：重置为 IDLE + identified=False，
        #   让机巢周期线程重新发起握手，恢复 needs_status_report 门闩下的状态消息上报。
        #   否则离巢后保持非 COMPLETED，入巢后 0x59/0x05 状态消息永久不再外发。
        if self._hs_state != self._HS_COMPLETED:
            self._hs_state = self._HS_IDLE
            self._hs_start_time = 0.0
            self._identified = False
            logger.info(
                f"[TEST] 飞机{self.ip} 入巢重置握手状态 "
                f"(非 COMPLETED → IDLE, identified=False)"
            )
        else:
            logger.info(
                f"[TEST] 飞机{self.ip} 入巢保留握手状态 (COMPLETED)"
            )
        logger.info(
            f"[TEST] 飞机{self.ip} 已切回机巢内模式 "
            f"(hs_state={self._hs_state}, identified={self._identified})"
        )

    @property
    def is_external_mode(self) -> bool:
        return self._external_mode

    def update(self, mode, gs_ip, gs_port, target_sender=None, target_slot=None):
        """统一的机巢内/外模式切换入口。

        Args:
            mode: 'internal' 或 'external'
            gs_ip: 地面站 IP（external 模式必传）
            gs_port: 地面站端口（external 模式必传）
            target_sender: 入巢时目标机巢的 _FakeNestSender（跨巢移动时必传）
            target_slot: 入巢时目标槽位 0-4（跨巢移动时必传）

        切换为 external 时：通信链路切为飞机自有 socket 直发地面站，
        同时清除原机巢 uavIp/inpos 对应槽位，飞机对象保留不销毁。

        切换为 internal 时：切回机巢转发模式。
        - 若指定 target_sender（跨巢入巢）：从原巢移除，加入目标巢指定槽位
        - 否则：恢复原巢 uavIp/inpos 槽位
        """
        if mode == 'external':
            self.set_external_mode(gs_ip, gs_port)
            if self._parent_sender is not None and self._slot_index is not None:
                self._parent_sender._clear_airplane_slot(self._slot_index)
            # 出巢：机巢定位字段置零（覆盖 update_state_extend 手工值）
            self._clear_nest_locating()
            # 出巢：经纬不变，高度改为 1.5m（1500mm）
            self.update_position(self.cur_lat, self.cur_lon,
                                self.tar_lat, self.tar_lon,
                                cur_alt=1500, tar_alt=1500)
            logger.info(
                f"[POS] 飞机{self.ip} 出巢 → alt=1500mm "
                f"lat={self.cur_lat} lon={self.cur_lon}"
            )
        elif mode == 'internal':
            self.set_internal_mode()
            # 确定入巢目标 sender 和槽位
            if target_sender is not None and target_slot is not None:
                # 跨巢入巢：加入目标机巢
                target_sender._accept_airplane(self, target_slot)
                ref_sender = target_sender
                ref_slot = target_slot
            elif self._parent_sender is not None and self._slot_index is not None:
                # 回原巢
                self._parent_sender._restore_airplane_slot(self._slot_index, self.ip)
                ref_sender = self._parent_sender
                ref_slot = self._slot_index
            else:
                logger.warning(
                    f"[TEST] 飞机{self.ip} 入巢失败: "
                    f"无 _parent_sender 且未指定 target_sender"
                )
                return
            # 入巢：经纬 = 目标机巢参考经纬度+槽位，高度 = 槽位 × 150mm
            ref_lat = int(ref_sender._nest_ref_lat + ref_slot)
            ref_lon = int(ref_sender._nest_ref_lon + ref_slot)
            ref_slot = int(ref_slot)
            alt = ref_slot * 150  # mm per slot
            # 入巢：机巢定位字段按目标机巢联动（覆盖 update_state_extend 手工值）
            self._apply_nest_locating(ref_sender, ref_slot)
            self.update_position(ref_lat, ref_lon, ref_lat, ref_lon,
                                cur_alt=alt, tar_alt=alt)
            logger.info(
                f"[POS] 飞机{self.ip} 入巢 slot={ref_slot} "
                f"lat={ref_lat} lon={ref_lon} alt={alt}"
            )
        else:
            logger.error(f"[TEST] 飞机{self.ip} update 未知 mode={mode}")

    def send_external(self, msg) -> bool:
        """机巢外模式专用发送：通过飞机自有 socket 直发地面站，不含 IP 前缀。

        Returns:
            True 如果发送成功，False 如果发送失败或不在外模式。
        """
        if not self._external_mode:
            return False
        # 持锁复制 socket 引用，避免 set_external_mode 并发替换 self._sock
        # 导致 TOCTOU 竞态（检查通过后被另一线程关掉）
        with self._lock:
            sock = self._sock
            gs_ip = self._gs_ip
            gs_port = self._gs_port
        if sock is None:
            logger.warning(
                f"[TEST] 飞机{self.ip} 外模式发送失败: socket 未创建"
            )
            return False
        try:
            data = msg.pack()
            sock.sendto(data, (gs_ip, gs_port))
            actual_src = sock.getsockname()
            logger.info(
                f"[TEST] 飞机{self.ip} src={actual_src} "
                f"→ {gs_ip}:{gs_port} | msg_id={msg.msg_id}(0x{msg.msg_id:02X})"
            )
            return True
        except Exception as e:
            logger.error(f"[TEST] 飞机{self.ip} 外模式发送失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 外模式接收线程（对齐独立假飞机 _FakeAirplaneMessageSender._run）
    # ------------------------------------------------------------------
    def _external_receive_loop(self):
        """外模式接收线程：从自有 socket 读取 → 解析 MAVLink → process_message → send_external。

        对齐独立假飞机 _FakeAirplaneMessageSender._run() 的接收/调度循环。
        周期心跳/状态上报由机巢 _periodic_send_loop 统一驱动，不在此重复。
        """
        logger.info(
            f"[TEST] 飞机{self.ip} 外模式接收线程已启动 "
            f"socket={self._sock.getsockname() if self._sock else 'N/A'}"
        )
        while self._external_receive_running and self._external_mode:
            try:
                if self._sock is None:
                    time.sleep(0.05)
                    continue
                data, addr = self._sock.recvfrom(4096)
                if not data:
                    continue
                # 注入到 UDP 消息监控（对齐机巢 _SocketInterceptor 模式：
                # src_ip/src_port = 地面站 IP:port（transport.ground_station_ip），
                # dst_ip/dst_port = 飞机自身，确保监控中显示为 GCS→飞机）
                if self._msg_injector:
                    try:
                        src_ip = self._gs_ip or self.ip
                        src_port = self._gs_port or self._local_port
                        self._msg_injector(data, src_ip, src_port,
                                          self.ip, self._local_port)
                    except Exception:
                        pass  # 回调异常绝不能影响主业务
                # 解析标准 MAVLink（外模式直连 GCS，无 IP 前缀）
                received = _parse_mavlink_message(data)
                if received is None:
                    continue
                # 忽略心跳
                if received.msg_id == 0:
                    continue
                # 调度处理
                responses = self.process_message(received)
                for msg, label in responses:
                    self.send_external(msg)
            except socket.timeout:
                continue
            except OSError:
                # socket 已关闭（set_internal_mode / close），退出循环
                break
            except Exception as e:
                logger.error(
                    f"[TEST] 飞机{self.ip} 外模式接收异常: {e}", exc_info=True
                )
                time.sleep(0.05)
        logger.info(f"[TEST] 飞机{self.ip} 外模式接收线程已退出")

    def close(self):
        """清理资源：停止外模式接收线程 + 飞行推进线程 + 关闭自有 socket。"""
        self._flight_running = False
        self._external_receive_running = False
        if self._flight_thread is not None:
            if self._flight_thread.is_alive():
                self._flight_thread.join(timeout=2)
            self._flight_thread = None
        if self._external_receive_thread is not None:
            if self._external_receive_thread.is_alive():
                self._external_receive_thread.join(timeout=2)
            self._external_receive_thread = None
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        logger.info(f"[TEST] 飞机{self.ip} 资源已清理")


# ==================================================================
# _NestedPPS：轻型储能电池（周期上报 msg_id=83）
# ------------------------------------------------------------------
# 无独立线程、不创建网卡节点，由 _FakeNestSender 周期线程驱动
# ==================================================================
class _NestedPPS(_NestedDeviceBase):
    """轻型储能电池 PPS：周期上报 msg_id=83 (MAVLink_pps_state_message)。"""

    # ------------------------------------------------------------------
    # 嵌套设备自适应注册元数据
    # ------------------------------------------------------------------
    _DEVICE_LABEL = "储能电池 PPS"
    _SENDER_UPDATE_METHOD = "update_pps_state"
    _SENDER_INSTANCES_ATTR = "_pps"
    _INSTANCE_MODE = "single"
    _UPDATABLE_FIELDS = {
        'power_voltage_v': (0.0, 'float'),
        'power_current_a': (0.0, 'float'),
        'power_remaining_cap_mah': (0.0, 'float'),
        'power_full_cap_mah': (0.0, 'float'),
        'power_alarm_flags': (0, 'int'),
        'cell_temp_c': (0.0, 'float'),
        'fet_temp_c': (0.0, 'float'),
        'cell_voltage_diff_v': (0.0, 'float'),
        'cells_voltage': ([0.0] * 6, 'list'),
        'power_soc': (0, 'int'),
        'nest_sn': ([0] * 12, 'list_int'),
        'power_sn': ([0] * 12, 'list_int'),
        'firmware_version': ([0] * 8, 'list_int'),
        'fan_status': (0, 'int'),
        'heater_status': (0, 'int'),
    }

    _REPORT_INTERVAL = 5.0  # 上报间隔

    def __init__(self, mavlink_version='45'):
        self.mavlink_version = mavlink_version
        # 状态字段（对齐 mavlink_config_v43.json msg_id=83）
        self.power_voltage_v = 0.0         # float
        self.power_current_a = 0.0         # float
        self.power_remaining_cap_mah = 0.0 # float
        self.power_full_cap_mah = 0.0      # float
        self.power_alarm_flags = 0         # uint32
        self.cell_temp_c = 0.0             # float
        self.fet_temp_c = 0.0              # float
        self.cell_voltage_diff_v = 0.0     # float
        self.cells_voltage = [0.0] * 6     # float[6]
        self.power_soc = 0                 # uint8
        self.nest_sn = [0] * 12            # uint8[12]
        self.power_sn = [0] * 12           # uint8[12]
        self.firmware_version = [0] * 8    # uint8[8]
        self.fan_status = 0                # uint8
        self.heater_status = 0             # uint8
        self._last_report_time = 0.0
        self._lock = threading.Lock()

    def build_state_message(self):
        """构建 msg_id=83 周期状态消息。"""
        with self._lock:
            return MAVLink_message(msg_id=83, sys_id=COMP_ID_NEST_PPS, comp_id=COMP_ID_GCS,
                                   version=self.mavlink_version,
                                   fields={
                                       'power_voltage_v': self.power_voltage_v,
                                       'power_current_a': self.power_current_a,
                                       'power_remaining_cap_mah': self.power_remaining_cap_mah,
                                       'power_full_cap_mah': self.power_full_cap_mah,
                                       'power_alarm_flags': self.power_alarm_flags,
                                       'cell_temp_c': self.cell_temp_c,
                                       'fet_temp_c': self.fet_temp_c,
                                       'cell_voltage_diff_v': self.cell_voltage_diff_v,
                                       'cells_voltage': list(self.cells_voltage),
                                       'power_soc': self.power_soc,
                                       'nest_sn': list(self.nest_sn),
                                       'power_sn': list(self.power_sn),
                                       'firmware_version': list(self.firmware_version),
                                       'fan_status': self.fan_status,
                                       'heater_status': self.heater_status,
                                   })

    def needs_report(self, now: float) -> bool:
        return (now - self._last_report_time) >= self._REPORT_INTERVAL

    def mark_report_sent(self, now: float):
        self._last_report_time = now

    # ------------------------------------------------------------------
    # 消息处理（由机巢接收线程调用）
    # ------------------------------------------------------------------
    def process_message(self, received: MAVLink_message):
        """处理收到的消息，返回 [(MAVLink_message, label), ...]。
        当前 PPS 无响应规则，预留扩展。
        """
        return []

    def update_state(self, **fields):
        """更新 PPS 状态字段。"""
        with self._lock:
            for k, v in fields.items():
                if hasattr(self, k):
                    setattr(self, k, v)


# ==================================================================
# _NestedPPSCharger：轻型储能电池充电器（周期上报 msg_id=84）
# ------------------------------------------------------------------
# 无独立线程、不创建网卡节点，由 _FakeNestSender 周期线程驱动
# ==================================================================
class _NestedPPSCharger(_NestedDeviceBase):
    """轻型储能电池充电器 PPSCharger：周期上报 msg_id=84
       (MAVLink_pps_charger_state_message)。"""

    # ------------------------------------------------------------------
    # 嵌套设备自适应注册元数据
    # ------------------------------------------------------------------
    _DEVICE_LABEL = "储能电池充电器"
    _SENDER_UPDATE_METHOD = "update_pps_charger_state"
    _SENDER_INSTANCES_ATTR = "_pps_charger"
    _INSTANCE_MODE = "single"
    _UPDATABLE_FIELDS = {
        'input_voltage_v': (0.0, 'float'),
        'input_current_a': (0.0, 'float'),
        'output_voltage_v': (0.0, 'float'),
        'output_current_a': (0.0, 'float'),
        'output_power_w': (0.0, 'float'),
        'charger_alarm_flags': (0, 'int'),
        'charger_fw_ver': ([0] * 8, 'list_int'),
        'charger_status': (0, 'int'),
        'fan_status': (0, 'int'),
        'charger_temp_c': (0, 'int'),
    }

    _REPORT_INTERVAL = 5.0  # 上报间隔

    def __init__(self, mavlink_version='45'):
        self.mavlink_version = mavlink_version
        # 状态字段（对齐 mavlink_config_v43.json msg_id=84）
        self.input_voltage_v = 0.0     # float
        self.input_current_a = 0.0     # float
        self.output_voltage_v = 0.0    # float
        self.output_current_a = 0.0    # float
        self.output_power_w = 0.0      # float
        self.charger_alarm_flags = 0   # uint16
        self.charger_fw_ver = [0] * 8  # uint8[8]
        self.charger_status = 0        # uint8
        self.fan_status = 0            # uint8
        self.charger_temp_c = 0        # int8
        self._last_report_time = 0.0
        self._lock = threading.Lock()

    def build_state_message(self):
        """构建 msg_id=84 周期状态消息。"""
        with self._lock:
            return MAVLink_message(msg_id=84, sys_id=COMP_ID_NEST_PPSCHARGER, comp_id=COMP_ID_GCS,
                                   version=self.mavlink_version,
                                   fields={
                                       'input_voltage_v': self.input_voltage_v,
                                       'input_current_a': self.input_current_a,
                                       'output_voltage_v': self.output_voltage_v,
                                       'output_current_a': self.output_current_a,
                                       'output_power_w': self.output_power_w,
                                       'charger_alarm_flags': self.charger_alarm_flags,
                                       'charger_fw_ver': list(self.charger_fw_ver),
                                       'charger_status': self.charger_status,
                                       'fan_status': self.fan_status,
                                       'charger_temp_c': self.charger_temp_c,
                                   })

    def needs_report(self, now: float) -> bool:
        return (now - self._last_report_time) >= self._REPORT_INTERVAL

    def mark_report_sent(self, now: float):
        self._last_report_time = now

    # ------------------------------------------------------------------
    # 消息处理（由机巢接收线程调用）
    # ------------------------------------------------------------------
    def process_message(self, received: MAVLink_message):
        """处理收到的消息，返回 [(MAVLink_message, label), ...]。
        当前 PPSCharger 无响应规则，预留扩展。
        """
        return []

    def update_state(self, **fields):
        """更新 PPSCharger 状态字段。"""
        with self._lock:
            for k, v in fields.items():
                if hasattr(self, k):
                    setattr(self, k, v)


# ==================================================================
# _NestedLPPC：轻型 LPPC 低功耗处理器控制器（周期上报 msg_id=100）
# ------------------------------------------------------------------
# 每个槽位的飞机配有一个 LPPC 实例，由 _FakeNestSender 管理。
# 无独立线程、不创建网卡节点，由 _FakeNestSender 周期线程驱动。
# ==================================================================
class _NestedLPPC(_NestedDeviceBase):
    """轻型 LPPC 低功耗处理器控制器：周期上报 msg_id=100 (MAVLink_lppc_heartbeat_message)。

    管理关系：每个 _NestAirplane 配有一个 _NestedLPPC 实例。
    由 _FakeNestSender 周期线程驱动上报。
    """

    # ------------------------------------------------------------------
    # 嵌套设备自适应注册元数据
    # ------------------------------------------------------------------
    _DEVICE_LABEL = "LPPC 低功耗处理器"
    _SENDER_UPDATE_METHOD = "update_lppc_state"
    _SENDER_INSTANCES_ATTR = "_lppc_dict"
    _INSTANCE_MODE = "dict"
    _UPDATABLE_FIELDS = {
        'voltage': (0, 'int'),
        'current': (0, 'int'),
        'remaining_capacity': (0, 'int'),
        'full_charge_capacity': (0, 'int'),
        'cycle_count': (0, 'int'),
        'health': (0, 'int'),
        'cell_delta': (0, 'int'),
        'temperature': (0, 'int'),
        'fet_temperature': (0, 'int'),
        'cell_voltages': ([0] * 6, 'list'),
        'sn_prefix': ([0] * 8, 'list_int'),
        'sn_suffix': ([0] * 4, 'list_int'),
        'soc': (0, 'int'),
        'parachute_healthy': (0, 'int'),
        'bms_healthy': (0, 'int'),
        'piezo_healthy': (0, 'int'),
        # -- v45 新 LPPC 消息字段 --
        'cell_voltage_delta': (0.0, 'float'),   # id=80 电芯压差 (V)
        'soh': (0, 'int'),                       # id=80 健康度
        'battery_temp': (0, 'int'),              # id=80 电池温度
        'fet_temp': (0, 'int'),                  # id=80 FET 温度
        'fault_flags': (0, 'int'),               # id=81 故障标志 (uint32)
        'failsafe_flags': (0, 'int'),            # id=101 故障安全标志 (uint32)
        'lifetime_counts': ([0] * 12, 'list_int'),  # id=82 12 类故障次数
        'lifetime_lasts': ([0] * 12, 'list_int'),   # id=82 12 类故障最后循环
        'history_counts': ([0] * 12, 'list_int'),   # id=102 12 类历史次数
        'history_lasts': ([0] * 12, 'list_int'),    # id=102 12 类历史最后循环
    }

    _REPORT_INTERVAL = 1.0        # LPPC_HEARTBEAT(100) 上报间隔（文档 §10: ~0.5-1Hz）
    _EXTRA_REPORT_INTERVAL = 5.0  # 新 LPPC 消息（80/81/82/101/102）上报间隔

    def __init__(self, mavlink_version='45'):
        self.mavlink_version = mavlink_version
        # 状态字段（对齐 mavlink_config_v44.json msg_id=100, §7.5）
        self.voltage = 0              # uint16 电池电压 (mV)
        self.current = 0              # int16  电流 (mA)
        self.remaining_capacity = 0    # uint16 剩余容量 (mAh)
        self.full_charge_capacity = 0  # uint16 满充容量 (mAh)
        self.cycle_count = 0          # uint16 循环次数
        self.health = 0               # uint8  健康度百分比 (0-100)
        self.cell_delta = 0           # uint16 电芯压差 (mV)
        self.temperature = 0          # int16  温度（0.1°C）
        self.fet_temperature = 0      # int16  FET 管温度（0.1°C）
        self.cell_voltages = [0] * 6  # uint16[6] 各电芯电压 (mV)
        self.sn_prefix = [0] * 8      # uint8[8] 序列号前缀
        self.sn_suffix = [0] * 4      # uint8[4] 序列号后缀
        self.soc = 0                  # uint8  SOC 电量百分比
        self.parachute_healthy = 0    # uint8  降落伞健康标志
        self.bms_healthy = 0          # uint8  BMS 健康标志
        self.piezo_healthy = 0        # uint8  压电健康标志
        # -- v45 新 LPPC 消息字段 --
        self.cell_voltage_delta = 0.0  # float  id=80 电芯压差 (V)
        self.soh = 0                   # uint8  id=80 健康度
        self.battery_temp = 0          # int8   id=80 电池温度
        self.fet_temp = 0              # int8   id=80 FET 温度
        self.fault_flags = 0           # uint32 id=81 故障标志
        self.failsafe_flags = 0        # uint32 id=101 故障安全标志
        self.lifetime_counts = [0] * 12  # uint8[12] id=82 12 类故障次数
        self.lifetime_lasts = [0] * 12   # uint8[12] id=82 12 类故障最后循环
        self.history_counts = [0] * 12   # uint16[12] id=102 12 类历史次数
        self.history_lasts = [0] * 12    # uint16[12] id=102 12 类历史最后循环
        self._last_report_time = 0.0
        self._last_extra_report_time = 0.0
        self._lock = threading.Lock()

    def build_state_message(self):
        """构建 msg_id=100 周期 LPPC 心跳消息（LPPC→GCS）。"""
        with self._lock:
            return MAVLink_message(msg_id=100, sys_id=COMP_ID_LPPC, comp_id=COMP_ID_GCS,
                                   version=self.mavlink_version,
                                   fields={
                                       'voltage': self.voltage,
                                       'current': self.current,
                                       'remaining_capacity': self.remaining_capacity,
                                       'full_charge_capacity': self.full_charge_capacity,
                                       'cycle_count': self.cycle_count,
                                       'cell_delta': self.cell_delta,
                                       'temperature': self.temperature,
                                       'fet_temperature': self.fet_temperature,
                                       'cell_voltages': list(self.cell_voltages),
                                       'health': self.health,
                                       'sn_prefix': list(self.sn_prefix),
                                       'sn_suffix': list(self.sn_suffix),
                                       'soc': self.soc,
                                       'parachute_healthy': self.parachute_healthy,
                                       'bms_healthy': self.bms_healthy,
                                       'piezo_healthy': self.piezo_healthy,
                                   })

    # ------------------------------------------------------------------
    # v45 新 LPPC 消息构建
    # ------------------------------------------------------------------
    _LIFETIME_NAMES = ['COV', 'CUV', 'OCD1', 'OCD2', 'OCC1', 'OCC2',
                       'AOLD', 'ASCD', 'ASCC', 'OTC', 'OTD', 'OTF']
    _HISTORY_NAMES = ['ov', 'uv', 'ocd1', 'ocd2', 'occ1', 'occ2',
                      'aold', 'ascd', 'ascc', 'otc', 'otd', 'otf']

    def build_battery_state_message(self):
        """构建 msg_id=80 LPPC_BATTERY_STATE（电压/电流为浮点 V/A）。"""
        with self._lock:
            return MAVLink_message(msg_id=80, sys_id=COMP_ID_LPPC, comp_id=COMP_ID_GCS,
                                   version=self.mavlink_version,
                                   fields={
                                       'voltage': self.voltage / 1000.0,
                                       'current': self.current / 1000.0,
                                       'remaining_capacity': self.remaining_capacity,
                                       'full_charge_capacity': self.full_charge_capacity,
                                       'cell_voltage_delta': self.cell_voltage_delta,
                                       'cell_voltages': [v / 1000.0 for v in self.cell_voltages],
                                       'cycle_count': self.cycle_count,
                                       'soh': self.soh,
                                       'battery_temp': self.battery_temp,
                                       'fet_temp': self.fet_temp,
                                       'sn_prefix': list(self.sn_prefix),
                                       'sn_suffix': list(self.sn_suffix),
                                       'soc': self.soc,
                                       'parachute_healthy': self.parachute_healthy,
                                       'bms_healthy': self.bms_healthy,
                                       'piezo_healthy': self.piezo_healthy,
                                   })

    def build_fault_status_message(self):
        """构建 msg_id=81 LPPC_FAULT_STATUS（uint32 故障标志）。"""
        with self._lock:
            return MAVLink_message(msg_id=81, sys_id=COMP_ID_LPPC, comp_id=COMP_ID_GCS,
                                   version=self.mavlink_version,
                                   fields={'fault_flags': self.fault_flags})

    def build_lifetime_info_message(self):
        """构建 msg_id=82 LPPC_LIFETIME_INFO（12 类故障次数 + 最后循环，uint8）。"""
        with self._lock:
            fields = {}
            for i, name in enumerate(self._LIFETIME_NAMES):
                fields[f'NoOf{name}'] = self.lifetime_counts[i] if i < len(self.lifetime_counts) else 0
                fields[f'last{name}'] = self.lifetime_lasts[i] if i < len(self.lifetime_lasts) else 0
            return MAVLink_message(msg_id=82, sys_id=COMP_ID_LPPC, comp_id=COMP_ID_GCS,
                                   version=self.mavlink_version, fields=fields)

    def build_failsafe_message(self):
        """构建 msg_id=101 LPPC_FAILSAFE（uint32 故障安全标志）。"""
        with self._lock:
            return MAVLink_message(msg_id=101, sys_id=COMP_ID_LPPC, comp_id=COMP_ID_GCS,
                                   version=self.mavlink_version,
                                   fields={'flags': self.failsafe_flags})

    def build_battery_history_message(self):
        """构建 msg_id=102 LPPC_BATTERY_HISTORY（12 类历史次数 + 最后循环，uint16）。"""
        with self._lock:
            fields = {}
            for i, name in enumerate(self._HISTORY_NAMES):
                fields[f'{name}_count'] = self.history_counts[i] if i < len(self.history_counts) else 0
                fields[f'{name}_last_cycle'] = self.history_lasts[i] if i < len(self.history_lasts) else 0
            return MAVLink_message(msg_id=102, sys_id=COMP_ID_LPPC, comp_id=COMP_ID_GCS,
                                   version=self.mavlink_version, fields=fields)

    def build_extra_messages(self):
        """构建 v45 新 LPPC 消息列表：[(msg, label), ...]（80/81/82/101/102）。"""
        return [
            (self.build_battery_state_message(), 'id=80(0x50) LPPC_BATTERY_STATE'),
            (self.build_fault_status_message(), 'id=81(0x51) LPPC_FAULT_STATUS'),
            (self.build_lifetime_info_message(), 'id=82(0x52) LPPC_LIFETIME_INFO'),
            (self.build_failsafe_message(), 'id=101(0x65) LPPC_FAILSAFE'),
            (self.build_battery_history_message(), 'id=102(0x66) LPPC_BATTERY_HISTORY'),
        ]

    def needs_report(self, now: float) -> bool:
        return (now - self._last_report_time) >= self._REPORT_INTERVAL

    def mark_report_sent(self, now: float):
        self._last_report_time = now

    def needs_extra_report(self, now: float) -> bool:
        return (now - self._last_extra_report_time) >= self._EXTRA_REPORT_INTERVAL

    def mark_extra_report_sent(self, now: float):
        self._last_extra_report_time = now

    # ------------------------------------------------------------------
    # 消息处理（由机巢接收线程调用）
    # ------------------------------------------------------------------
    def process_message(self, received: MAVLink_message):
        """处理 LPPC 命令。支持 COMMAND_LONG(76) 的 LPPC 控制命令（50001-50008），回 ACK(77, sys_id=37)。"""
        if received.msg_id == 76:  # _MSG_ID_COMMAND_LONG
            command = received.fields.get('command', 0)
            if 50001 <= command <= 50008:
                ack = MAVLink_message(msg_id=77, sys_id=COMP_ID_LPPC,
                                      comp_id=COMP_ID_GCS, version=self.mavlink_version,
                                      fields={'command': command, 'result': 0})
                return [(ack, f'id=77(0x4D) LPPC cmd={command} result=0')]
        return []

    def update_state(self, **fields):
        """更新 LPPC 状态字段。"""
        with self._lock:
            for k, v in fields.items():
                if hasattr(self, k):
                    setattr(self, k, v)


# ==================================================================
# _FakeNestSender：单台假机巢的响应线程
# ------------------------------------------------------------------
# 由 _FakeNestSenders 批量创建并管理生命周期
# ==================================================================
class _FakeNestSender:
    """单台假机巢的消息响应器：一个实例 = 一台 FakeNest + 两个后台线程 + N 架轻型假飞机。

    线程构成：
        - _run()                接收线程：监听地面站消息，路由到机巢/飞机处理。
        - _periodic_send_loop() 周期线程：每 1s 发送 msg_id=86 + 全部飞机心跳。

    飞机管理：
        update_nest_state(uavIp=[...]) 时自动同步 _NestAirplane 实例。
        飞机不创建网卡节点，收发通过机巢 UDP 套接字转发。

    工作流程：
        1. 构造时即启动两个线程。
        2. update_*() 可在运行期改写 nestIp / nestSn / uavIp / 状态字段等。
        3. stop() 通知两个线程退出并 join。

    协议响应规则（_RESPONSE_RULES）结构：
        _RESPONSE_RULES[入站 msg_id] = {
            'delay': <节流间隔秒> | None,
            'rules': [
                {
                    'build': <本类 @staticmethod 名称（字符串）>,
                    'label': <日志标签>,
                    'state': {<builder 形参>: <self 属性名>}  # 叠加当前状态；空 dict 表示不依赖状态
                    'when' : <可选 callable(received) -> bool>  # True 才发送
                },
                ...
            ],
        }
    """

    # 类级飞机注册表：IP → _NestAirplane，用于跨巢飞机查找
    _airplane_registry: dict = {}

    # 类级实例注册表：所有 _FakeNestSender 实例，按创建顺序排列
    _instances: list = []

    # 协议默认值（bytes 字段长度需严格匹配 v45 配置）
    _DEFAULT_NEST_SN = b"NEST00000000000000000"             # 20 字节 nestSn
    _DEFAULT_BOX_SN = b"BOX0000000000000000000"             # 20 字节 BoxSn
    _DEFAULT_PPS_SN = b"PPS0000000000000000000"             # 20 字节 ppsSn
    _DEFAULT_PPS_CHARGER_SN = b"PCS000000000000000000"     # 20 字节 ppsChargerSn
    _DEFAULT_NEST_VERSION = b"NEST_V42"                     #  8 字节 nestVersion
    _DEFAULT_PPS_VERSION = b"PPS_V100"                      #  8 字节 ppsVersion
    _DEFAULT_PPS_CHARGER_VERSION = b"PCS_V100"              #  8 字节 ppsChargerVersion
    _DEFAULT_SERIAL = b"NESTSN00000000000000"               # 20 字节 serial（msg_id=2）
    _DEFAULT_CODE = b"00001"                                #  5 字节 code（msg_id=2）
    _DEFAULT_NEST_IP = "0.0.0.0"                            # nestIp（字符串，构建 MAVLink 时转为 uint32）
    _DEFAULT_NEST_HARD_VER = 1
    _DEFAULT_NEST_ID = b"00000"                             #  5 字节 nestId
    _DEFAULT_BOX_ID = b"00000"                              #  5 字节 BoxId

    # 时序常量（秒）
    _LOOP_POLL_INTERVAL = 0.05
    _NEST_STATE_SEND_INTERVAL = 1.0  # msg_id=86 周期 1s 发送（对齐协议文档 §5.1 ~1Hz）
    # 一次成功发送后，self.success 保持 True 的时长；之后自动回落为 False
    _SUCCESS_HOLD_SECONDS = 0.5

    # 时序常量（秒）
    _HANDSHAKE_INITIAL_DELAY = 1
    _HANDSHAKE_TIMEOUT = 30.0
    _POST_IDENTITY_DELAY = 0.3

    # 地面站消息 ID
    _MSG_ID_HEARTBEAT = 0
    _MSG_ID_HEARTBEAT_DMD = 1
    _MSG_ID_IDENTIFY_INFO = 2
    _MSG_ID_GET_IDENTIFY_INFO = 3

    # 识别完成前放行的入站消息（对齐 fake_airplane.py，其余一律屏蔽）
    _ALLOW_BEFORE_IDENTIFY = (_MSG_ID_HEARTBEAT, _MSG_ID_GET_IDENTIFY_INFO)

    # 机巢消息 ID
    _MSG_ID_NEST_PACKED_STATE = 86
    _MSG_ID_NEST_EXTEND_STATE = 87
    _MSG_ID_NEST_UAV_HEARTBEAT = 88
    _MSG_ID_COMMAND_LONG = 76
    _MSG_ID_COMMAND_ACK = 77
    _MSG_ID_SET_CODE_NUMBER = 28
    _MSG_ID_GET_LOWFREQ_INFO = 74
    _MSG_ID_LOWFREQ_INFO = 75

    # MAV_CMD 命令枚举（对齐 DGCS 文档 4.3 节）
    MAV_CMD_NEST_PPS_LOCK_CONTROL = 40061
    MAV_CMD_NEST_PPS_CHARGER_CMD = 40062
    MAV_CMD_NEST_UAV_LOCK = 40070
    MAV_CMD_NEST_UAV_CHARGER_CMD = 40071
    MAV_CMD_LPPC_CHG_EN_CMD = 40072    # LPPC 充电使能/禁用
    MAV_CMD_UPDATE_NEST = 40081         # 更新机巢固件
    MAV_CMD_UPDATE_NEST_BOX = 40082     # 更新机箱
    MAV_CMD_UPDATE_NEST_PPS = 40083     # 更新 PPS
    MAV_CMD_UPDATE_NEST_PPSCHG = 40084  # 更新 PPS 充电器
    MAV_CMD_UPDATE_NEST_IRDAMCU = 40085 # 更新红外 MCU
    MAV_CMD_UPDATE_NEST_UAV = 40086     # 更新机巢内无人机
    MAV_CMD_DO_SET_SERVO = 183          # LED 灯光控制

    # LPPC 控制命令（§4.3 LPPC 控制命令）
    MAV_CMD_LPPC_POWER_ON = 50001
    MAV_CMD_LPPC_POWER_OFF = 50002
    MAV_CMD_LPPC_SLEEP = 50003
    MAV_CMD_LPPC_WAKE = 50004
    MAV_CMD_LPPC_ARM = 50005
    MAV_CMD_LPPC_DISARM = 50006
    MAV_CMD_LPPC_PARACHUTE_OPEN = 50007
    MAV_CMD_LPPC_QUERY_BATTERY_HISTORY = 50008

    # 无人机电源控制命令（§4.3 经机巢转发；PowerOPType: 0=Resume 1=Standby 2=Shutdown 3=ForceShutdown 4=BatDormancy 5=PowerOn）
    MAV_CMD_STANDBY = 40046
    MAV_CMD_POWER_ON = 40057
    MAV_CMD_POWER_OFF = 40058
    MAV_CMD_REST = 40059
    MAV_CMD_WAKE_UP = 40060

    # MAV_RESULT 枚举
    MAV_RESULT_ACCEPTED = 0
    MAV_RESULT_UNSUPPORTED = 3

    # ------------------------------------------------------------------
    # 协议响应规则表 — 单一数据源（修改此表即可调整响应协议）
    # ------------------------------------------------------------------
    _RESPONSE_RULES = {
        _MSG_ID_HEARTBEAT_DMD: {
            'delay': None,
            'rules': [
                {'build': '_build_id_087', 'label': 'id=87(0x57)',
                 'state': {
                     'nestIp': 'nestIp_87',
                     'nestId': 'nestId',
                     'BoxId': 'BoxId',
                     'nestSn': 'nestSn',
                     'nestHardVer': 'nestHardVer',
                     'nestVersion': 'nestVersion',
                     'BoxSn': 'BoxSn',},
                 'when': lambda recv: recv.fields.get('extend') == 1},
            ],
        },
        _MSG_ID_GET_IDENTIFY_INFO: {
            'delay': None,
            'rules': [
                {'build': '_build_id_002', 'label': 'id=2(0x02)',
                 'state': {'serial': 'serial', 'code': 'code'}},
            ],
        },
    }

    # ------------------------------------------------------------------
    # 有状态协议交互调度表 —— msg_id → 处理方法名
    # 参考假飞机 _FakeAirplaneMessageSender._STATE_RULES 模式
    # ------------------------------------------------------------------
    _STATE_RULES = {
        _MSG_ID_COMMAND_LONG: '_handle_command_long',
        _MSG_ID_GET_LOWFREQ_INFO: '_handle_get_lowfreq_info',
        _MSG_ID_SET_CODE_NUMBER: '_handle_set_code_number',
    }

    # ------------------------------------------------------------------
    # 协议握手
    # ------------------------------------------------------------------
    def _do_handshake(self):
        """执行 MAVLink 握手：心跳 → 收 id=3 → 发 id=2 → 收 id=1。"""
        time.sleep(self._HANDSHAKE_INITIAL_DELAY)
        msg = self._build_id_000()
        self._wrap_and_send(msg, "000")

        received = self._wait_for_msg_id(3, label="id=3")
        if received is None:
            logger.error("[TEST] 握手失败: 未收到地面站 id=3")
            return False

        msg = self._build_id_002(serial=self.serial, code=self.code)
        self._wrap_and_send(msg, "002")
        time.sleep(self._POST_IDENTITY_DELAY)

        received = self._wait_for_msg_id(1, label="id=1 extend=1")
        if received is None:
            logger.error("[TEST] 握手失败: 未收到地面站 id=1")
            return False

        return True

    # ------------------------------------------------------------------
    # 特定ID接收消息等待
    # ------------------------------------------------------------------
    def _wait_for_msg_id(self, expected_id, label, timeout=None):
        """在 timeout 内等待指定 msg_id。返回 (msg, addr)，超时返回 (None, None)。"""
        if timeout is None:
            timeout = self._HANDSHAKE_TIMEOUT
        print(f"[TEST] 等待 {label} (timeout={timeout}s)")
        start = time.time()
        while time.time() - start < timeout:
            received, addr, _ = self.fake_nest.receive()
            if received is not None:
                # print(f"[TEST] 收到 msg_id={received.msg_id} from={addr}")
                if received.msg_id == expected_id:
                    return received, addr
                if received.msg_id == self._MSG_ID_HEARTBEAT:
                    continue
            time.sleep(0.1)
        return None, None

    def __init__(self, log_manager, fake_nest, addr,
                 serial=_DEFAULT_SERIAL, code=_DEFAULT_CODE,
                 nestId=_DEFAULT_NEST_ID, BoxId=_DEFAULT_BOX_ID,
                 nestSn=_DEFAULT_NEST_SN, nestHardVer=_DEFAULT_NEST_HARD_VER,
                 nestVersion=_DEFAULT_NEST_VERSION,
                 BoxSn=_DEFAULT_BOX_SN,
                 nest_plane_layout=None):
        self.log_manager = log_manager
        self.fake_nest = fake_nest
        self.addr = addr

        # msg_id=2 字段
        self.serial = serial
        self.code = code

        # msg_id=86 字段
        self.nestIp = fake_nest.local_ip  # 继承创建时的本机 IP
        # 0x56(id=86)/0x57(id=87) 消息的 nestIp 字段（与 FakeNest 绑定的本机 IP 解耦）
        # 默认继承 fake_nest.local_ip,可通过 update_nest_state / update_nest_extend 独立修改。
        self.nestIp_86 = fake_nest.local_ip  # 0x56 NEST_PACKED_STATE nestIp
        self.nestIp_87 = fake_nest.local_ip  # 0x57 NEST_EXTEND_STATE nestIp
        self.uavIp = ["0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0"]
        self._uavIp_configured = list(self.uavIp)  # 保存用户配置的 IP，layout 屏蔽时可恢复
        self.chargeVolt = [0, 0, 0, 0, 0]
        self.lock_state = 0
        self.inpos = [2, 2, 2, 2, 2]
        self._inpos_user_set = False  # 用户显式设置 inpos 后置 True，阻止自动覆写
        self.nest_plane_layout = (
            list(nest_plane_layout) if nest_plane_layout is not None
            else [1, 1, 1, 1, 1]
        )  # 机巢内飞机排布：1=有飞机 0=无飞机
        self.chargePower = [0, 0, 0, 0, 0]
        self.chargeTmp = [0, 0, 0, 0, 0]
        self.motorState = [0, 0, 0, 0]
        self.motorChipState = [0, 0]
        self.pps_online = 0
        self.ppsCharger_online = 0
        # 视觉检测字段（v45 nest_packed_state 新增，vi=vision，随 id=86 上报）
        self.viCount = 0     # 视觉检测计数（初始化时自动同步为巢内飞机数）
        self.viState = 0     # 视觉检测状态
        self.viJudge = 0     # 视觉检测判定
        # 视觉字段是否已初始化：首次自动同步或 update_vision_state 手动设置后置 True，
        # 此后 _sync_airplanes_locked 不再自动覆写 viCount
        self._vi_initialized = False
        self.nestState = 0
        self.nestStateInfo = [0] * 16

        # msg_id=87 字段
        self.nestId = nestId
        self.BoxId = BoxId
        self.ppsId = 0
        self.ppsChargerId = 0
        self.nestSn = nestSn
        self.nestHardVer = nestHardVer
        self.nestVersion = nestVersion
        self.BoxSn = BoxSn
        self.ppsSn = self._DEFAULT_PPS_SN
        self.ppsVersion = self._DEFAULT_PPS_VERSION
        self.ppsChargerSn = self._DEFAULT_PPS_CHARGER_SN
        self.ppsChargerVersion = self._DEFAULT_PPS_CHARGER_VERSION

        self.running = False
        self.periodic_running = False
        self.thread = None
        self.periodic_thread = None
        self._lock = threading.Lock()
        self._msg_injector = None  # 消息注入回调（传递到 external mode 飞机）
        self._camera_stream = None  # 摄像头 MJPEG 视频流（update_camera_stream 懒创建）
        self._instance_index = len(_FakeNestSender._instances)  # 本实例在注册表中的索引
        _FakeNestSender._instances.append(self)
        self.success = False
        self._success_timer = None  # type: threading.Timer | None

        # 身份识别门闩（对齐 fake_airplane.py）：识别完成前仅放行 0x0 / 0x3
        self._identified = False

        # ---- ACK 失败响应配置（机巢自身，各 command 独立计数和计时）----
        # _ack_fail_count: 对所有 command 统一返回 result=4 的次数（0=禁用）
        self._ack_fail_count: int = 0
        # _ack_fail_counters: {command_id: current_count} — 各 command 已返回 result=4 的次数
        self._ack_fail_counters: dict[int, int] = {}
        # _ack_fail_last_time: {command_id: timestamp} — 各 command 上次收到的时间
        self._ack_fail_last_time: dict[int, float] = {}

        # ---- ACK 静默响应配置 ----
        # _ack_silence_count: 对所有 command 统一不回复的次数（0=禁用）
        self._ack_silence_count: int = 0
        # _ack_silence_counters: {command_id: current_count} — 各 command 已静默的次数
        self._ack_silence_counters: dict[int, int] = {}
        # _ack_silence_last_time: {command_id: timestamp} — 各 command 上次收到的时间
        self._ack_silence_last_time: dict[int, float] = {}

        # 机巢参考经纬度（由 _FakeNestSenders 写入，入巢飞机共用此值）
        self._nest_ref_lat: int = 226868664
        self._nest_ref_lon: int = 1140224548

        # 机巢背后的轻型假飞机：{ip_str: _NestAirplane}
        self._airplanes = {}

        # 机巢附属设备（按在线状态创建/销毁）
        self._pps = None             # type: _NestedPPS | None
        self._pps_charger = None     # type: _NestedPPSCharger | None
        self._lppc_dict = {}         # {ip_str: _NestedLPPC} — 每个槽位飞机一个 LPPC

        try:
            # if not self._do_handshake():
            #     raise RuntimeError(
            #         f"[TEST] 机巢{self.fake_nest.local_ip}:{self.fake_nest.local_port}握手失败"
            #     )
            if not self.start():
                raise RuntimeError(
                    f"[TEST] 机巢{self.fake_nest.local_ip}:{self.fake_nest.local_port}后台线程启动失败"
                )
        except Exception:
            # 握手或启动线程失败：清理已分配的线程 / socket / 定时器，再向上抛
            self._cleanup()
            raise

    # ------------------------------------------------------------------
    # 资源清理（构造失败 / 正常 stop 共用）
    # ------------------------------------------------------------------
    def _cleanup(self):
        """清理本实例占用的资源：停线程、关 socket、取消 success 衰减定时器。"""
        # 取消 success 衰减定时器
        with self._lock:
            if self._success_timer is not None:
                self._success_timer.cancel()
                self._success_timer = None
        # 清空假飞机（先停各飞机的飞行推进/外模式线程与自有 socket，避免泄漏）
        for airplane in list(self._airplanes.values()):
            try:
                airplane.close()
            except Exception:
                pass
        self._airplanes.clear()
        # 清空附属设备
        self._pps = None
        self._pps_charger = None
        self._lppc_dict.clear()
        # 停止摄像头视频流
        if self._camera_stream is not None:
            try:
                self._camera_stream.stop()
            except Exception:
                pass
            self._camera_stream = None
        # 停两个后台线程
        self.running = False
        self.periodic_running = False
        for t in (self.thread, self.periodic_thread):
            if t is not None and t.is_alive():
                t.join(timeout=2)
        # 关闭底层 socket
        if self.fake_nest is not None:
            try:
                self.fake_nest.close()
            except Exception:
                pass
        # 从类级实例注册表移除
        try:
            _FakeNestSender._instances.remove(self)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # 生命周期 / 参数更新
    # ------------------------------------------------------------------
    def set_msg_injector(self, callback):
        """设置消息注入回调，将外模式飞机收到的原始数据转发到 UDP 监控。

        callback 签名为: (data: bytes, src_ip: str, src_port: int,
                          dst_ip: str, dst_port: int) -> None

        设置后会自动传播到所有已处于 external mode 的飞机。
        """
        self._msg_injector = callback
        with self._lock:
            for airplane in self._airplanes.values():
                if airplane.is_external_mode:
                    airplane._msg_injector = callback

    def start(self):
        """启动接收线程与 msg_id=86 周期发送线程。"""
        try:
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

            self.periodic_running = True
            self.periodic_thread = threading.Thread(target=self._periodic_send_loop, daemon=True)
            self.periodic_thread.start()

            print("[TEST] 假机巢消息发送线程已启动")
            return True
        except Exception as e:
            logger.error(f"启动假机巢消息发送线程失败: {e}")
            return False

    def stop(self):
        """正常停止：通知两个线程退出并 join；取消 success 衰减定时器；关闭 socket。"""
        self.running = False
        self.periodic_running = False
        with self._lock:
            if self._success_timer is not None:
                self._success_timer.cancel()
                self._success_timer = None
        # 清空假飞机（先停各飞机的飞行推进/外模式线程与自有 socket，避免泄漏）
        for airplane in list(self._airplanes.values()):
            try:
                airplane.close()
            except Exception:
                pass
        self._airplanes.clear()
        # 清空附属设备
        self._pps = None
        self._pps_charger = None
        self._lppc_dict.clear()
        # 停止摄像头视频流
        if self._camera_stream is not None:
            try:
                self._camera_stream.stop()
            except Exception:
                pass
            self._camera_stream = None
        # 停后台线程
        if self.thread is not None:
            self.thread.join(timeout=2)
        if self.periodic_thread is not None:
            self.periodic_thread.join(timeout=2)
        try:
            if self.fake_nest is not None:
                self.fake_nest.close()
        except Exception:
            pass
        print("[TEST] 假机巢消息发送线程已停止")

    def update_nest_ip(self, nestIp):
        """更新 msg_id=86/87 共用的 nestIp。

        副作用：将 self.success 清为 False（之前缓存的"已外发"已不再代表当前状态）。
        待新状态被成功外发后，self.success 会被 _wrap_and_send 重新置 True
        并保持 _SUCCESS_HOLD_SECONDS 秒。
        """
        with self._lock:
            self.nestIp = nestIp
            self._reset_success_locked()

    def update_nest_state(self, **fields):
        """更新 msg_id=86 周期性发送的状态字段。

        支持的关键字：nestIp / uavIp / chargeVolt / lock_state / inpos /
        chargePower / chargeTmp / motorState / motorChipState /
        pps_online / ppsCharger_online / viCount / viState / viJudge /
        nestState / nestStateInfo

        nestIp 仅修改 0x56 消息的 nestIp 字段（独立于 0x57 的 nestIp_87 与
        FakeNest 绑定的本机 IP fake_nest.local_ip），支持字符串 IP 或 uint32。

        uavIp 防御：传入的 uavIp 规整后全为空（全 "0.0.0.0"/空列表）时忽略该字段，
        不覆盖现有配置、不触发飞机同步——GUI 表单 uavIp 默认值（__init__ 初始值
        "0.0.0.0,..."）随全字段提交时曾误清全部巢内飞机。清空飞机请用
        update_nest_plane_layout([0,0,0,0,0])。

        副作用：将 self.success 清为 False（同 update_nest_ip）。
        uavIp 变更时自动同步 _NestAirplane 实例（不创建网卡节点）。
        """
        need_sync = False
        with self._lock:
            for k, v in fields.items():
                if k == 'nestIp':
                    # nestIp 仅作用于 0x56 消息, 写入独立的 nestIp_86
                    self.nestIp_86 = v
                elif k == 'uavIp':
                    # 防御：全空 uavIp（GUI 表单默认值）不覆盖、不同步
                    normalized = [self._normalize_uav_ip(ip)
                                  for ip in (v if v is not None else [])]
                    if any(ip is not None for ip in normalized):
                        setattr(self, k, v)
                        self._uavIp_configured = list(v)
                        need_sync = True
                    else:
                        logger.warning(
                            f"[TEST] 机巢 {self.fake_nest.local_ip} "
                            f"update_nest_state 忽略全空 uavIp={v!r}"
                            f"（保护现有 {len(self._airplanes)} 架巢内飞机, "
                            f"清空请用 update_nest_plane_layout）"
                        )
                elif hasattr(self, k):
                    setattr(self, k, v)
                    if k == 'inpos':
                        self._inpos_user_set = True
            self._reset_success_locked()
            # uavIp 变更 → 同步轻型假飞机
            if need_sync:
                self._sync_airplanes_locked()
            # pps_online 变更 → 同步 PPS 实例
            if 'pps_online' in fields:
                if self.pps_online and self._pps is None:
                    self._pps = _NestedPPS(MAVLINK_VERSION)
                    logger.info(
                        f"[TEST] 机巢 {self.fake_nest.local_ip} 创建 PPS"
                    )
                elif not self.pps_online and self._pps is not None:
                    logger.info(
                        f"[TEST] 机巢 {self.fake_nest.local_ip} 移除 PPS"
                    )
                    self._pps = None
            # ppsCharger_online 变更 → 同步 PPSCharger 实例
            if 'ppsCharger_online' in fields:
                if self.ppsCharger_online and self._pps_charger is None:
                    self._pps_charger = _NestedPPSCharger(MAVLINK_VERSION)
                    logger.info(
                        f"[TEST] 机巢 {self.fake_nest.local_ip} 创建 PPSCharger"
                    )
                elif not self.ppsCharger_online and self._pps_charger is not None:
                    logger.info(
                        f"[TEST] 机巢 {self.fake_nest.local_ip} 移除 PPSCharger"
                    )
                    self._pps_charger = None

    def update_vision_state(self, viCount=0, viState=0, viJudge=0):
        """更新视觉检测信号（v45 nest_packed_state 的 vi* 字段，随 id=86 上报）。

        视觉检测（vision）用于机巢对无人机入巢/归位状态的视觉判定。
        三个字段均为 uint8，取值自动钳制在 0-255 范围，避免 pack 溢出。

        支持的关键字：viCount / viState / viJudge

        副作用：将 self.success 清为 False（同 update_nest_state）。
        """
        with self._lock:
            self.viCount = max(0, min(255, int(viCount)))
            self.viState = max(0, min(255, int(viState)))
            self.viJudge = max(0, min(255, int(viJudge)))
            self._vi_initialized = True  # 手动接管，_sync_airplanes_locked 不再覆写 viCount
            self._reset_success_locked()

    def update_camera_stream(self, enabled=0):
        """控制机巢摄像头视频流开关（HTTP MJPEG :8080/stream，协议文档 §7.9.2）。

        开启后启动 :8080/stream 服务，推送循环数字 1~10 的 JPEG 帧流，
        供地面站 DroneNestCameraClient 按 JPEG SOI/EOI 标记解析显示。

        支持的关键字：enabled（0=关闭，1=开启）

        副作用：将 self.success 清为 False（同 update_nest_state）。
        """
        enabled = bool(int(enabled))
        with self._lock:
            if self._camera_stream is None:
                self._camera_stream = _CameraMjpegStream()
            if enabled:
                self._camera_stream.start()
            else:
                self._camera_stream.stop()
            self._reset_success_locked()

    def update_nest_plane_layout(self, layout):
        """更新机巢内飞机排布并自动同步飞机实例。

        Args:
            layout: 5 元素列表，1=有飞机 0=无飞机。
                    支持 [1,0,1,0,1] 或 "1,0,1,0,1" 或 "[1,0,1,0,1]"

        layout[i]==0 的槽位将移除对应飞机对象（外部模式飞机除外），
        layout[i]==1 的槽位将按 uavIp[i] 创建飞机。
        """
        # 类型强制：兼容 GUI 文本输入
        if isinstance(layout, str):
            try:
                layout = [int(x.strip()) for x in layout.strip('[]').split(',')]
            except (ValueError, AttributeError):
                logger.warning(
                    f"[TEST] 机巢 {self.fake_nest.local_ip} "
                    f"nest_plane_layout 解析失败: {layout!r}"
                )
                return
        if not isinstance(layout, list):
            logger.warning(
                f"[TEST] 机巢 {self.fake_nest.local_ip} "
                f"nest_plane_layout 格式错误: {layout!r}"
            )
            return
        # 自动补全长度（与 _sync_airplanes_locked 一致）：
        # 不足补齐 1（启用），超出截断
        if len(layout) < len(self.uavIp):
            layout = list(layout) + [1] * (len(self.uavIp) - len(layout))
        elif len(layout) > len(self.uavIp):
            layout = layout[:len(self.uavIp)]
        with self._lock:
            self.nest_plane_layout = list(layout)
            self._reset_success_locked()
            self._sync_airplanes_locked()

    # ------------------------------------------------------------------
    # 假飞机同步（持锁调用，不创建网卡节点）
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_uav_ip(ip):
        """将 uavIp 元素规整为 IP 字符串；空值/零值返回 None。"""
        if ip is None:
            return None
        if isinstance(ip, int):
            if ip == 0:
                return None
            return socket.inet_ntoa(struct.pack('!I', ip))
        if isinstance(ip, str):
            ip = ip.strip()
            if ip in ('', '0', '0.0.0.0'):
                return None
            return ip
        return None

    @staticmethod
    def _make_airplane_serial_code(ip_str: str):
        """根据飞机 IP 生成握手用的 (serial, code) bytes。

        serial: "KWL50F0K" + code（IP 末段 5 位补零），不定长
        code:   5 字节，IP 末段 5 位补零右对齐

        Examples:
            "172.16.3.181" → (b'WL50F0K00181', b'00181')
            "172.16.3.182" → (b'WL50F0K00182', b'00182')
        """
        parts = ip_str.split('.')
        last = int(parts[-1]) if len(parts) == 4 else 0
        code = str(last).encode('utf-8').rjust(5, b'0')[:5]
        serial = b'WL50F0K' + code
        return serial, code

    def _get_uav_layer_index(self, ip_str: str) -> int:
        """返回指定飞机 IP 在巢内的槽位索引（0=底层），供 LPPC 层前缀使用。

        优先取 _airplanes[ip_str]._slot_index；无匹配时回退 uavIp 顺序查找；仍无则 0。
        """
        airplane = self._airplanes.get(ip_str)
        if airplane is not None and airplane._slot_index is not None:
            return int(airplane._slot_index)
        try:
            return self.uavIp.index(ip_str)
        except ValueError:
            return 0

    def _sync_airplanes_locked(self):
        """持锁调用：根据 self.uavIp + self.nest_plane_layout 同步 _airplanes 字典。

        - nest_plane_layout[i]==0 的槽位不创建飞机（槽位掩码）
        - 外部模式飞机不会被销毁（uavIp 更新或 layout 变化时保留）
        - 创建飞机时传入 _parent_sender 和 _slot_index 以供 update() 回调
        """
        target_ips = set()
        layout = self.nest_plane_layout
        # 防御：兼容字符串 / 非 list 类型（GUI 文本输入可能绕过 update_nest_state）
        if isinstance(layout, str):
            try:
                layout = [int(x.strip()) for x in layout.strip('[]').split(',')]
            except (ValueError, AttributeError):
                layout = [1] * len(self.uavIp)
        elif not isinstance(layout, list):
            layout = [1] * len(self.uavIp)
        else:
            layout = list(layout)
        # 补全长度：短则末尾补 1
        if len(layout) < len(self.uavIp):
            layout.extend([1] * (len(self.uavIp) - len(layout)))

        # 按 layout 同步 uavIp / inpos（先于 target_ips 构建，确保飞机创建基于恢复后的 IP）
        for i in range(len(self.uavIp)):
            if i < len(layout) and layout[i] == 0:
                if self.uavIp[i] != "0.0.0.0":
                    self.uavIp[i] = "0.0.0.0"
                if not self._inpos_user_set and i < len(self.inpos) and self.inpos[i] != 0:
                    self.inpos[i] = 0
            else:
                configured_ip = self._uavIp_configured[i] if i < len(self._uavIp_configured) else "0.0.0.0"
                ip_str = self._normalize_uav_ip(configured_ip)
                if ip_str and ip_str in self._airplanes and not self._airplanes[ip_str].is_external_mode:
                    if self.uavIp[i] != ip_str:
                        self.uavIp[i] = ip_str
                    if not self._inpos_user_set and i < len(self.inpos) and self.inpos[i] != 2:
                        self.inpos[i] = 2
                elif ip_str and ip_str in self._airplanes and self._airplanes[ip_str].is_external_mode:
                    if self.uavIp[i] != "0.0.0.0":
                        self.uavIp[i] = "0.0.0.0"
                    if not self._inpos_user_set and i < len(self.inpos) and self.inpos[i] != 0:
                        self.inpos[i] = 0
                else:
                    if configured_ip not in ('0.0.0.0', '0', '') and self.uavIp[i] != configured_ip:
                        self.uavIp[i] = configured_ip
                    if not self._inpos_user_set and i < len(self.inpos) and self.inpos[i] != 2:
                        self.inpos[i] = 2

        for i, raw in enumerate(self.uavIp):
            # 槽位掩码：layout[i]==0 跳过
            if i < len(layout) and layout[i] == 0:
                continue
            ip_str = self._normalize_uav_ip(raw)
            if ip_str:
                target_ips.add(ip_str)

        # 移除不需要的飞机（跳过外部模式飞机）
        for ip_str in list(self._airplanes.keys()):
            if ip_str not in target_ips:
                airplane = self._airplanes[ip_str]
                if airplane.is_external_mode:
                    continue  # 外部模式飞机不销毁
                logger.info(
                    f"[TEST] 机巢 {self.fake_nest.local_ip} 移除飞机 {ip_str}"
                )
                # 关闭飞机自有 socket（__init__ 中不再创建，此处防御性清理）
                airplane.close()
                del self._airplanes[ip_str]
                _FakeNestSender._airplane_registry.pop(ip_str, None)
                # 同步移除对应 LPPC
                self._lppc_dict.pop(ip_str, None)

        # 同步已有飞机的槽位索引（处理 IP 换槽位的情况）
        for i, raw in enumerate(self.uavIp):
            if i < len(layout) and layout[i] == 0:
                continue
            ip_str = self._normalize_uav_ip(raw)
            if ip_str and ip_str in self._airplanes:
                airplane = self._airplanes[ip_str]
                if airplane._slot_index != i:
                    logger.info(
                        f"[TEST] 机巢 {self.fake_nest.local_ip} "
                        f"飞机 {ip_str} 槽位 {airplane._slot_index} → {i}"
                    )
                    airplane._slot_index = i

        # 创建新飞机（轻型，不创建网卡节点）
        for i, raw in enumerate(self.uavIp):
            # 槽位掩码：layout[i]==0 跳过
            if i < len(layout) and layout[i] == 0:
                continue
            ip_str = self._normalize_uav_ip(raw)
            if not ip_str:
                continue
            if ip_str not in self._airplanes:
                serial, code = self._make_airplane_serial_code(ip_str)
                logger.info(
                    f"[TEST] 机巢 {self.fake_nest.local_ip} 创建飞机 {ip_str} "
                    f"(serial={serial}, code={code}, slot={i})"
                )
                airplane = _NestAirplane(
                    ip_str, MAVLINK_VERSION, serial=serial, code=code,
                    _parent_sender=self, _slot_index=i,
                )
                # 经纬 = 机巢参考经纬度+槽位，高度 = 槽位 × 150mm
                ref_lat = int(self._nest_ref_lat + i)
                ref_lon = int(self._nest_ref_lon + i)
                alt = i * 150
                airplane.update_position(ref_lat, ref_lon, ref_lat, ref_lon,
                                        cur_alt=alt, tar_alt=alt)
                # 新建飞机即在巢内：机巢定位字段联动继承本机巢值
                airplane._apply_nest_locating(self, i)
                self._airplanes[ip_str] = airplane
                _FakeNestSender._airplane_registry[ip_str] = airplane
                # 同步创建 LPPC 实例
                self._lppc_dict[ip_str] = _NestedLPPC(MAVLINK_VERSION)

        # 视觉识别数量 viCount 初始化：首次有飞机时与巢内飞机数量一致。
        # 手动 update_vision_state 或首次自动初始化后 _vi_initialized=True，
        # 后续 uavIp/layout 变化触发同步不再覆写用户手动值。
        if not self._vi_initialized and self._airplanes:
            self.viCount = len(self._airplanes)
            self._vi_initialized = True

    # ------------------------------------------------------------------
    # 飞机槽位操作（供 _NestAirplane.update 回调，直接修改不触发 sync）
    # ------------------------------------------------------------------
    def _clear_airplane_slot(self, slot_index: int):
        """持锁清除指定槽位的 uavIp 和 inpos（飞机出巢时回调）。"""
        slot_index = int(slot_index)
        with self._lock:
            if 0 <= slot_index < len(self.uavIp):
                self.uavIp[slot_index] = "0.0.0.0"
            if 0 <= slot_index < len(self.inpos):
                self.inpos[slot_index] = 0
            self._inpos_user_set = False  # 物理出巢，恢复自动管理
            logger.info(
                f"[TEST] 机巢 {self.fake_nest.local_ip} "
                f"槽位{slot_index} 已清除 (飞机出巢)"
            )

    def _restore_airplane_slot(self, slot_index: int, ip: str):
        """持锁恢复指定槽位的 uavIp 和 inpos（飞机回巢时回调）。"""
        slot_index = int(slot_index)
        with self._lock:
            if 0 <= slot_index < len(self.uavIp):
                self.uavIp[slot_index] = ip
            if 0 <= slot_index < len(self.inpos):
                self.inpos[slot_index] = 2
            self._inpos_user_set = False  # 物理回巢，恢复自动管理
            logger.info(
                f"[TEST] 机巢 {self.fake_nest.local_ip} "
                f"槽位{slot_index} 已恢复 ip={ip} (飞机回巢)"
            )

    def _accept_airplane(self, airplane: '_NestAirplane', slot_index: int):
        """接收飞机进入本机巢指定槽位（跨巢入巢 / 同巢槽位变更）。

        从飞机原属机巢（或原槽位）移除，加入本机巢 _airplanes 字典，
        更新 uavIp/inpos 槽位以及 _uavIp_configured。

        注意：跨巢移动时先释放 self._lock 再获取 old_sender._lock，
        避免 A→B 与 B→A 同时发生时的死锁。
        """
        slot_index = int(slot_index)

        # ── 第一阶段：持 self._lock 读取原属信息（不获取 old_sender._lock）──
        with self._lock:
            old_sender = airplane._parent_sender
            old_slot = airplane._slot_index

        # ── 第二阶段：跨巢移动时，单独获取 old_sender._lock 做清理 ──
        if old_sender is not None and old_sender is not self:
            # 二次校验：在未持锁期间 _parent_sender 可能已被其他线程修改
            if airplane._parent_sender == old_sender:
                with old_sender._lock:
                    old_sender._airplanes.pop(airplane.ip, None)
                    old_sender._lppc_dict.pop(airplane.ip, None)
                    if old_slot is not None and 0 <= old_slot < len(old_sender.uavIp):
                        if old_sender.uavIp[old_slot] == airplane.ip:
                            old_sender.uavIp[old_slot] = "0.0.0.0"
                            if old_slot < len(old_sender.inpos):
                                old_sender.inpos[old_slot] = 0
                            old_sender._inpos_user_set = False  # 物理出巢，恢复自动管理
                logger.info(
                    f"[TEST] 飞机{airplane.ip} 从机巢 "
                    f"{old_sender.fake_nest.local_ip} 槽位{old_slot} 移除 (跨巢移动)"
                )

        # ── 第三阶段：持 self._lock 完成入巢 ──
        with self._lock:
            # 同巢槽位变更：清空旧槽位（仅当旧槽位仍指向本飞机时）
            if old_sender is self and old_slot is not None and old_slot != slot_index:
                if 0 <= old_slot < len(self.uavIp) and self.uavIp[old_slot] == airplane.ip:
                    self.uavIp[old_slot] = "0.0.0.0"
                    if old_slot < len(self.inpos):
                        self.inpos[old_slot] = 0
                    logger.info(
                        f"[TEST] 飞机{airplane.ip} 同巢槽位变更 "
                        f"{old_slot} → {slot_index}"
                    )
            # 加入本巢（或更新槽位）
            self._airplanes[airplane.ip] = airplane
            airplane._parent_sender = self
            airplane._slot_index = slot_index
            # 更新新槽位
            if 0 <= slot_index < len(self.uavIp):
                self.uavIp[slot_index] = airplane.ip
            if 0 <= slot_index < len(self.inpos):
                self.inpos[slot_index] = 2
            self._inpos_user_set = False  # 物理入巢，恢复自动管理
            # 同步 _uavIp_configured
            if 0 <= slot_index < len(self._uavIp_configured):
                self._uavIp_configured[slot_index] = airplane.ip
            # 同步创建 LPPC（如果还不存在）
            if airplane.ip not in self._lppc_dict:
                self._lppc_dict[airplane.ip] = _NestedLPPC(MAVLINK_VERSION)
            logger.info(
                f"[TEST] 机巢 {self.fake_nest.local_ip} "
                f"接收飞机 {airplane.ip} → 槽位{slot_index}"
            )

    def update_nest_extend(self, **fields):
        """更新 msg_id=87 响应时所使用的扩展字段。

        支持的关键字：nestIp / nestId / BoxId / nestSn / nestHardVer /
        nestVersion / BoxSn

        nestIp 仅修改 0x57 消息的 nestIp 字段（独立于 0x56 的 nestIp_86 与
        FakeNest 绑定的本机 IP fake_nest.local_ip），支持字符串 IP 或 uint32。
        nestId / BoxId 为 5 字节 char[5]（如 b"00001"），
        nestSn / BoxSn 为 20 字节，nestVersion 为 8 字节，
        nestHardVer 为 int。

        副作用：将 self.success 清为 False（同 update_nest_ip）。
        """
        with self._lock:
            for k, v in fields.items():
                if k == 'nestIp':
                    # nestIp 仅作用于 0x57 消息, 写入独立的 nestIp_87
                    self.nestIp_87 = v
                elif hasattr(self, k):
                    setattr(self, k, v)
            self._reset_success_locked()
            # 注意：机巢 nestId/nestSn 变化不联动飞机消息 8 的机巢定位字段——
            # 按 update_state_extend 的字段优先级定义，仅出入巢动作覆盖手工值

    def update_identify(self, serial=None, code=None):
        """更新 msg_id=2 响应时所使用的 serial / code。

        副作用：将 self.success 清为 False（同 update_nest_ip）。
        """
        with self._lock:
            if serial is not None:
                self.serial = serial
            if code is not None:
                self.code = code
            self._reset_success_locked()

    def update_ack(self, fail_count=0, silence_count=0):
        """配置机巢自身所有 command 的 ACK 响应失败/静默次数。

        fail_count: 前 N 次返回 result!=0，之后返回 result=0。
        silence_count: 前 N 次不回复（静默），之后返回 result=0。
        各 command 独立计数，10s 未收到该 command 则其计数器自动重置为 0。

        Args:
            fail_count: 失败次数（>=0），设为 0 则禁用（始终返回 result=0）
            silence_count: 静默次数（>=0），设为 0 则禁用（始终立即回复）
        """
        with self._lock:
            self._ack_fail_count = fail_count
            self._ack_fail_counters.clear()
            self._ack_fail_last_time.clear()
            self._ack_silence_count = silence_count
            self._ack_silence_counters.clear()
            self._ack_silence_last_time.clear()

    def update_airplane_ack(self, ip_str: str, fail_count=0, silence_count=0):
        """配置指定巢内飞机所有 command 的 ACK 响应失败/静默次数。

        fail_count: 前 N 次返回 result!=0，之后返回 result=0。
        silence_count: 前 N 次不回复（静默），之后返回 result=0。
        各 command 独立计数，10s 未收到该 command 则其计数器自动重置为 0。

        Args:
            ip_str: 飞机 IP 字符串，如 "172.16.3.180"
            fail_count: 失败次数（>=0），设为 0 则禁用（始终返回 result=0）
            silence_count: 静默次数（>=0），设为 0 则禁用（始终立即回复）
        """
        with self._lock:
            airplane = self._airplanes.get(ip_str)
            if airplane is None:
                logger.warning(
                    f"[TEST] 机巢{self.fake_nest.local_ip} "
                    f"飞机 {ip_str} 不存在，无法配置 ACK 响应"
                )
                return
            airplane.update_ack(fail_count=fail_count, silence_count=silence_count)

    def update_airplane_offline(self, ip_str: str, offline: bool = False):
        """设置指定巢内飞机的离线/上线状态（控制消息是否外发）。

        离线时飞机停止所有消息外发（心跳、状态、ACK 等均不发送），
        但飞机对象仍保留在机巢中，可通过该接口重新上线。

        Args:
            ip_str: 飞机 IP 字符串，如 "172.16.3.180"
            offline: True=离线(停止外发), False=上线(正常外发)
        """
        with self._lock:
            airplane = self._airplanes.get(ip_str)
            if airplane is None:
                logger.warning(
                    f"[TEST] 机巢{self.fake_nest.local_ip} "
                    f"飞机 {ip_str} 不存在，无法设置离线/上线状态"
                )
                return
            airplane.update_msg_forwarding(not offline)

    def update_airplane_state(self, ip_str: str, **fields):
        """更新指定 IP 飞机的状态字段。

        支持：wind_speed_x / wind_speed_y / seq
              laser_config / nova_config / firework_config / lantern_config /
                trumpet_config / parachute_config
              laser_state / nova_state / lantern_state / trumpet_state /
                parachute_state
              lantern / trumpet / parachute
              nova_light_version / gimbal_version / flight_controller_version /
                companion_version / battery_version / gps_version /
                servo_ver / tele_version / bms_version / rid_version
              cur_lat / cur_lon / tar_lat / tar_lon / cur_alt / tar_alt
              mode / armed / final_mode
              play_duration_ms / land_duration_ms / takeoff_height_mm /
                land_height_mm
              light_r / light_g / light_b / autopilot

        Args:
            ip_str: 飞机 IP 字符串，如 "172.16.3.180"
            **fields: 要更新的状态字段
        """
        with self._lock:
            airplane = self._airplanes.get(ip_str)
            if airplane is None:
                logger.warning(
                    f"[TEST] 机巢{self.fake_nest.local_ip} "
                    f"飞机 {ip_str} 不存在，无法更新状态"
                )
                return
            airplane.update_state(**fields)

    def update_airplane_mode(self, ip_str, mode, target_nest_index=None, target_slot=None):
        """切换指定 IP 飞机的机巢内/外通信模式。

        gs_ip/gs_port 自动确定：入巢 172.16.200.1:14650，出巢 172.16.200.1:14550。

        支持跨巢入巢：通过 target_nest_index 指定目标机巢（在 _instances 中的索引），
        未指定则默认为当前机巢（self）。

        Args:
            ip_str: 飞机 IP 字符串（GUI 下拉选择）
            mode: 'internal'（机巢内）或 'external'（机巢外）
            target_nest_index: 目标机巢索引（GUI 下拉选择，不传=当前巢）
            target_slot: 入巢目标槽位 0-4（仅 internal 模式生效，不传则自动分配）
        """
        if mode == 'internal':
            gs_ip, gs_port = '172.16.200.1', 14650
        elif mode == 'external':
            gs_ip, gs_port = '172.16.200.1', 14550
        else:
            logger.error(
                f"[TEST] 机巢{self.fake_nest.local_ip} "
                f"update_airplane_mode 未知 mode={mode}"
            )
            return

        # 确定目标机巢
        target_sender = self
        if target_nest_index is not None and 0 <= target_nest_index < len(_FakeNestSender._instances):
            target_sender = _FakeNestSender._instances[target_nest_index]

        with self._lock:
            airplane = self._airplanes.get(ip_str)
        if airplane is None:
            airplane = _FakeNestSender._airplane_registry.get(ip_str)
            if airplane is None:
                logger.warning(
                    f"[TEST] 机巢{self.fake_nest.local_ip} "
                    f"飞机 {ip_str} 不存在（本地及全局注册表均未找到）"
                )
                return

        if mode == 'internal':
            # 入巢（含跨巢/同巢）：规整 target_slot（GUI 可能传字符串或空值）
            if target_slot is not None:
                try:
                    target_slot = int(target_slot)
                except (ValueError, TypeError):
                    target_slot = None
            # 自动分配槽位（如未指定或无效）
            if target_slot is None:
                for i, ip in enumerate(target_sender.uavIp):
                    if ip in ('0.0.0.0', '0', ''):
                        target_slot = i
                        break
            if target_slot is None:
                logger.warning(
                    f"[TEST] 机巢{target_sender.fake_nest.local_ip} "
                    f"无空槽位，飞机 {ip_str} 无法入巢"
                )
                return
            airplane.update(mode, gs_ip, gs_port,
                          target_sender=target_sender, target_slot=target_slot)
        else:
            airplane.update(mode, gs_ip, gs_port)

    def update_airplane_version(self, **kwargs):
        """更新指定 IP 飞机的版本信息，后续发送 id=8 消息时使用新值。

        支持的关键字：ip_str / flight_controller_version /
        companion_version / battery_version / gps_version / servo_ver /
        tele_version / bms_version / rid_version / gimbal_version /
        nova_light_version

        ip_str 为必填项，其余字段仅白名单内的 key 生效。
        """
        ip_str = kwargs.pop('ip_str', None)
        if not ip_str:
            logger.warning(
                f"[TEST] 机巢{self.fake_nest.local_ip} "
                f"update_airplane_version 缺少 ip_str"
            )
            return
        with self._lock:
            airplane = self._airplanes.get(ip_str)
            if airplane is None:
                logger.warning(
                    f"[TEST] 机巢{self.fake_nest.local_ip} "
                    f"飞机 {ip_str} 不存在，无法更新版本"
                )
                return
            airplane.update_version(**kwargs)

    def update_pps_state(self, **fields):
        """更新 PPS（储能电池）的状态字段。

        支持的关键字对齐 msg_id=83 字段：power_voltage_v / power_current_a /
        power_remaining_cap_mah / power_full_cap_mah / power_alarm_flags /
        cell_temp_c / fet_temp_c / cell_voltage_diff_v / cells_voltage /
        power_soc / nest_sn / power_sn / firmware_version / fan_status /
        heater_status
        """
        with self._lock:
            if self._pps is None:
                logger.warning(
                    f"[TEST] 机巢{self.fake_nest.local_ip} PPS 不在线，无法更新"
                )
                return
            self._pps.update_state(**fields)

    def update_pps_charger_state(self, **fields):
        """更新 PPSCharger（储能电池充电器）的状态字段。

        支持的关键字对齐 msg_id=84 字段：input_voltage_v / input_current_a /
        output_voltage_v / output_current_a / output_power_w /
        charger_alarm_flags / charger_fw_ver / charger_status /
        fan_status / charger_temp_c
        """
        with self._lock:
            if self._pps_charger is None:
                logger.warning(
                    f"[TEST] 机巢{self.fake_nest.local_ip} PPSCharger 不在线，无法更新"
                )
                return
            self._pps_charger.update_state(**fields)

    def update_lppc_state(self, ip_str: str, **fields):
        """更新指定飞机 IP 对应的 LPPC 状态字段。

        支持的关键字对齐 msg_id=100 字段：voltage / current /
        remaining_capacity / full_charge_capacity / cycle_count / health /
        cell_delta / temperature / fet_temperature / cell_voltages /
        sn_prefix / sn_suffix / soc / parachute_healthy / bms_healthy /
        piezo_healthy
        """
        with self._lock:
            lppc = self._lppc_dict.get(ip_str)
            if lppc is None:
                logger.warning(
                    f"[TEST] 机巢{self.fake_nest.local_ip} "
                    f"飞机 {ip_str} 的 LPPC 不存在，无法更新"
                )
                return
            lppc.update_state(**fields)

    # ------------------------------------------------------------------
    # self.success 衰减状态机（持锁 / Timer 回调）
    # ------------------------------------------------------------------
    def _reset_success_locked(self):
        """持锁调用：将 self.success 清为 False，并取消挂起的 0.5s 衰减定时器。

        在 update_*() 状态被改写、或者一次发送失败时调用。
        """
        self.success = False
        if self._success_timer is not None:
            self._success_timer.cancel()
            self._success_timer = None

    def _mark_success_locked(self):
        """持锁调用：标记一次发送成功。

        行为：
            - self.success 立即置 True
            - 启动一个 _SUCCESS_HOLD_SECONDS 秒的 Timer，到期后自动清回 False
            - 若在窗口内又收到新的成功标记，会取消旧 Timer 并启动新 Timer
              （始终以"最后一次成功外发"为基准，0.5s 内无新成功则回落）
        """
        self.success = True
        if self._success_timer is not None:
            self._success_timer.cancel()
        self._success_timer = threading.Timer(
            self._SUCCESS_HOLD_SECONDS, self._on_success_expire
        )
        self._success_timer.daemon = True
        self._success_timer.start()

    def _on_success_expire(self):
        """Timer 回调：0.5s 衰减到期后清 success。"""
        with self._lock:
            self.success = False
            self._success_timer = None

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def _run(self):
        """接收线程：接收 → 路由 → 响应。

        路由规则（两种互补策略）：
            策略 A — IP 前缀消息 + 命中某组件 IP → 仅该 IP 对应组件回复（精确路由）
            策略 B — 纯 MAVLink（无前缀）→ 按 comp_id 广播路由：
                comp_id=0  (ALL)           → 所有组件回复
                comp_id=1  (AUTOPILOT1)    → 所有假飞机回复（含握手+正常消息）
                comp_id=35 (NEST)          → 假机巢回复
                comp_id=36 (NEST_PPS)      → PPS 回复
                comp_id=38 (NEST_PPSCHARGER) → PPSCharger 回复

        握手兼容说明：
            两种策略均可驱动飞机握手：
            - 策略 A：地面站以飞机 IP 前缀发送 id=3/id=1，机巢精确路由到对应飞机
            - 策略 B：地面站以 comp_id=1 发送 id=3/id=1，机巢广播到所有飞机
                      所有飞机同时推进握手状态（批量握手）
        """
        # MAV_COMPONENT 枚举（引用模块级常量，对齐协议文档 §4.2）
        _COMP_ID_ALL = COMP_ID_ALL
        _COMP_ID_AUTOPILOT1 = COMP_ID_AUTOPILOT1
        _COMP_ID_NEST_PPS = COMP_ID_NEST_PPS
        _COMP_ID_LPPC = COMP_ID_LPPC
        _COMP_ID_NEST_PPSCHARGER = COMP_ID_NEST_PPSCHARGER
        _COMP_ID_GCS = COMP_ID_GCS
        _COMP_ID_NEST = COMP_ID_NEST
        _COMP_ID_NEST_CHARGER = COMP_ID_NEST_CHARGER
        _COMP_ID_BROADCAST = SYS_ID_BROADCAST

        while self.running:
            try:
                received, addr, source_ip = self.fake_nest.receive()
                if received is None:
                    time.sleep(self._LOOP_POLL_INTERVAL)
                    continue
                # 仅处理目标 IP 为本组件 IP 的消息（socket 绑定已保证）
                if received.msg_id == self._MSG_ID_HEARTBEAT:
                    continue

                # 路由 1：IP 前缀 → 按 IP 匹配，仅对应组件回复
                if source_ip:
                    matched = False
                    # LPPC 层索引前缀（协议文档 §4.4.7）：首字节 < 10 → 飞机槽位层数
                    _first_octet = source_ip.split('.')[0]
                    if _first_octet.isdigit() and int(_first_octet) < 10:
                        layer = int(_first_octet)
                        if layer < len(self.uavIp):
                            target_ip = self._normalize_uav_ip(self.uavIp[layer])
                            lppc = self._lppc_dict.get(target_ip) if target_ip else None
                            if lppc is not None:
                                pending = lppc.process_message(received)
                                for msg, label in pending:
                                    self._wrap_and_send(
                                        msg, label, source_label=f"LPPC_{target_ip}",
                                        raw_prefix=bytes([layer, 0, 0, 0]),
                                    )
                        continue
                    if source_ip in self._airplanes:
                        self._dispatch_airplane_response(
                            self._airplanes[source_ip], received,
                        )
                        matched = True
                    if source_ip == self.fake_nest.local_ip:
                        self._dispatch_request(received, addr)
                        self._dispatch_pps_response(received)
                        self._dispatch_pps_charger_response(received)
                        self._dispatch_lppc_response(received)
                        matched = True
                    if matched:
                        continue
                    # 未匹配到已知组件（source_ip 非空但不在已知列表中），
                    # 回退到策略 B 按 comp_id 路由，确保所有消息都被解析处理

                # 路由 2：纯 MAVLink → 按 comp_id 路由
                comp_id = received.comp_id

                if comp_id == _COMP_ID_ALL:
                    # 所有组件回复
                    self._dispatch_request(received, addr)
                    for airplane in list(self._airplanes.values()):
                        self._dispatch_airplane_response(airplane, received)
                    self._dispatch_pps_response(received)
                    self._dispatch_pps_charger_response(received)
                    self._dispatch_lppc_response(received)
                elif comp_id == _COMP_ID_AUTOPILOT1:
                    # 仅假飞机回复
                    for airplane in list(self._airplanes.values()):
                        self._dispatch_airplane_response(airplane, received)
                elif comp_id == _COMP_ID_NEST:
                    # 仅假机巢回复
                    self._dispatch_request(received, addr)
                elif comp_id == _COMP_ID_NEST_CHARGER:
                    # 仅机巢充电器回复
                    self._dispatch_request(received, addr)
                elif comp_id == _COMP_ID_NEST_PPS:
                    # 仅 PPS 回复
                    self._dispatch_pps_response(received)
                elif comp_id == _COMP_ID_LPPC:
                    # 仅 LPPC 回复
                    self._dispatch_lppc_response(received)
                elif comp_id == _COMP_ID_NEST_PPSCHARGER:
                    # 仅 PPSCharger 回复
                    self._dispatch_pps_charger_response(received)
                elif comp_id == _COMP_ID_BROADCAST:
                    # 广播：所有组件回复（对齐协议文档 §4.4.1）
                    self._dispatch_request(received, addr)
                    for airplane in list(self._airplanes.values()):
                        self._dispatch_airplane_response(airplane, received)
                    self._dispatch_pps_response(received)
                    self._dispatch_pps_charger_response(received)
                    self._dispatch_lppc_response(received)
            except Exception as e:
                logger.error(
                    f"[TEST] 机巢{self.fake_nest.local_ip} "
                    f"接收线程异常: {e}", exc_info=True,
                )
                time.sleep(self._LOOP_POLL_INTERVAL)

    def _periodic_send_loop(self):
        """周期发送线程：每 5s 发送。

        外发策略（对齐 fake_airplane.py 握手门闩）：
          1. 始终周期外发 0x0（机巢心跳）
          2. 身份识别完成前（未收到 0x3 → 回复 0x2），不上报其他消息
          3. 识别完成后：周期外发 0x56 + 飞机心跳/状态 + PPS/PPSCharger
        """
        while self.periodic_running:
            try:
                now = time.time()
                # 机巢心跳 id=0：始终上报
                self._wrap_and_send(self._build_id_000(), "id=0(0x00)_nest")

                # 外部模式飞机心跳：始终上报（绕过身份识别门闩，直发地面站）
                for ip_str, airplane in list(self._airplanes.items()):
                    if not airplane.is_external_mode:
                        continue
                    if not airplane._msg_forwarding_enabled:
                        continue
                    if not airplane.ip or airplane.ip in ('0.0.0.0', '0', ''):
                        continue
                    if airplane.needs_heartbeat(now):
                        hb = airplane.build_heartbeat()
                        airplane.send_external(hb)
                        airplane.mark_heartbeat_sent(now)
                    if airplane.needs_status_report(now):
                        rpt_059 = airplane.build_remaining_capacity()
                        rpt_005 = airplane.build_packed_state()
                        airplane.send_external(rpt_059)
                        airplane.send_external(rpt_005)
                        # failsafe(0x06)：enable_failsafe=True 时随状态周期外发
                        if airplane.enable_failsafe:
                            airplane.send_external(airplane._build_id_006())
                        airplane.mark_status_report_sent(now)

                # 身份识别完成前，仅对外部飞机和机巢心跳，不发送巢状态/内部飞机
                if not self._identified:
                    time.sleep(self._NEST_STATE_SEND_INTERVAL)
                    continue

                with self._lock:
                    msg = self._build_id_086(
                        nestIp=self.nestIp_86,
                        uavIp=list(self.uavIp),
                        # msg_id=86 不含 latitude/longitude/altitude/fix_type/irda_inpos
                        chargeVolt=list(self.chargeVolt),
                        lock_state=self.lock_state,
                        inpos=list(self.inpos),
                        chargePower=list(self.chargePower),
                        chargeTmp=list(self.chargeTmp),
                        motorState=list(self.motorState),
                        motorChipState=list(self.motorChipState),
                        pps_online=self.pps_online,
                        ppsCharger_online=self.ppsCharger_online,
                        viCount=self.viCount,
                        viState=self.viState,
                        viJudge=self.viJudge,
                        nestState=self.nestState,
                        nestStateInfo=list(self.nestStateInfo),
                    )
                # 周期状态 id=86（0x56）
                self._wrap_and_send(msg, "id=86(0x56)")

                # 内部模式飞机心跳：识别完成后才上报
                for ip_str, airplane in list(self._airplanes.items()):
                    if airplane.is_external_mode:
                        continue  # 外部飞机已在上面处理
                    if not airplane._msg_forwarding_enabled:
                        continue
                    if not airplane.ip or airplane.ip in ('0.0.0.0', '0', ''):
                        continue
                    airplane.check_handshake_timeout()
                    if airplane.needs_heartbeat(now):
                        hb = airplane.build_heartbeat()
                        self._wrap_and_send(
                            hb, "id=0(0x00)",
                            source_label=f"飞机{airplane.ip}",
                            prepend_ip_addr=airplane.ip,
                        )
                        airplane.mark_heartbeat_sent(now)
                        airplane.start_handshake()

                    if airplane.needs_status_report(now):
                        rpt_059 = airplane.build_remaining_capacity()
                        rpt_005 = airplane.build_packed_state()
                        self._wrap_and_send(
                            rpt_059, "id=59(0x3B)",
                            source_label=f"飞机{airplane.ip}",
                            prepend_ip_addr=airplane.ip,
                        )
                        self._wrap_and_send(
                            rpt_005, "id=5(0x05)",
                            source_label=f"飞机{airplane.ip}",
                            prepend_ip_addr=airplane.ip,
                        )
                        # failsafe(0x06)：enable_failsafe=True 时随状态周期外发
                        if airplane.enable_failsafe:
                            self._wrap_and_send(
                                airplane._build_id_006(), "id=6(0x06) FAILSAFE",
                                source_label=f"飞机{airplane.ip}",
                                prepend_ip_addr=airplane.ip,
                            )
                        airplane.mark_status_report_sent(now)

                # PPS 状态上报：msg_id=83 每 5s（组件构建，机巢包装外发）
                if self._pps is not None and self._pps.needs_report(now):
                    pps_msg = self._pps.build_state_message()
                    self._wrap_and_send(pps_msg, "id=83(0x53)", source_label="PPS")
                    self._pps.mark_report_sent(now)

                # PPSCharger 状态上报：msg_id=84 每 5s（组件构建，机巢包装外发）
                if self._pps_charger is not None and self._pps_charger.needs_report(now):
                    chg_msg = self._pps_charger.build_state_message()
                    self._wrap_and_send(chg_msg, "id=84(0x54)", source_label="PPSCharger")
                    self._pps_charger.mark_report_sent(now)

                # LPPC 心跳上报：msg_id=100 ~1Hz（每个槽位飞机一个 LPPC）
                # 使用特殊 IP 前缀：首字节 = 无人机层索引 (0=底层)，触发 GCS 的
                # ParseLppcHeartbeat() 路径（协议文档 §4.4.7）
                for ip_str, lppc in list(self._lppc_dict.items()):
                    layer = self._get_uav_layer_index(ip_str)
                    lppc_prefix = bytes([layer, 0, 0, 0])  # 首字节=层索引
                    if lppc.needs_report(now):
                        lppc_msg = lppc.build_state_message()
                        self._wrap_and_send(lppc_msg, "id=100(0x64)",
                                            source_label=f"LPPC_{ip_str}",
                                            raw_prefix=lppc_prefix)
                        lppc.mark_report_sent(now)
                    # v45 新 LPPC 消息（80/81/82/101/102）@5s
                    if lppc.needs_extra_report(now):
                        for msg, label in lppc.build_extra_messages():
                            self._wrap_and_send(msg, label,
                                                source_label=f"LPPC_{ip_str}",
                                                raw_prefix=lppc_prefix)
                        lppc.mark_extra_report_sent(now)
            except Exception as e:
                logger.error(f"[TEST] 周期发送失败: {e}")
            time.sleep(self._NEST_STATE_SEND_INTERVAL)

    # ------------------------------------------------------------------
    # 规则调度（与 fake_airplanes 同构）
    # ------------------------------------------------------------------
    def _dispatch_request(self, received, remote_addr=None):
        """按 _STATE_RULES → _RESPONSE_RULES 顺序处理请求。

        调度顺序（参考假飞机 _FakeAirplaneMessageSender._dispatch_request）：
          1. 有状态交互（_STATE_RULES）：COMMAND_LONG 等需要读写内部状态
          2. 无状态查表回显（_RESPONSE_RULES）：心跳DMD/身份

        身份识别门闩：未识别前仅放行 0x0 / 0x3，其余屏蔽。
        """
        mid = received.msg_id

        # 身份识别门闩：未识别前仅放行心跳/身份
        if not self._identified and mid not in self._ALLOW_BEFORE_IDENTIFY:
            return

        # 1) 有状态协议交互
        handler_name = self._STATE_RULES.get(mid)
        if handler_name is not None:
            self.log_manager.logger.info(
                f"[TEST] 机巢{self.fake_nest.local_ip}:{self.fake_nest.local_port} "
                f"收到 msg_id={mid} 消息(有状态)"
            )
            pending = getattr(self, handler_name)(received) or []
            for msg, label in pending:
                self._wrap_and_send(msg, label)
            return

        # 2) 无状态查表回显
        batch = self._RESPONSE_RULES.get(mid)
        if batch is None:
            return
        hex_str = ' '.join(f'{b:02x}' for b in received.pack())
        addr_str = f" from={remote_addr}" if remote_addr else ""
        self.log_manager.logger.info(
            f"[TEST] 机巢{self.fake_nest.local_ip}:{self.fake_nest.local_port} "
            f"收到 msg_id={mid} 消息{addr_str} [{hex_str}]"
        )

        pending = []
        with self._lock:
            for rule in batch['rules']:
                if rule.get('when') and not rule['when'](received):
                    continue
                try:
                    kwargs = {kw: getattr(self, attr)
                              for kw, attr in rule.get('state', {}).items()}
                    msg = getattr(self, rule['build'])(**kwargs)
                except Exception as e:
                    logger.error(f"[TEST] {rule['label']} 构建失败: {e}")
                    continue
                pending.append((msg, rule['label']))
            # 收到 0x3 并回复 0x2 后，身份识别完成，解锁后续消息
            if mid == self._MSG_ID_GET_IDENTIFY_INFO:
                self._identified = True
                logger.info(
                    f"[TEST] 机巢{self.fake_nest.local_ip} 身份识别完成，解锁全部消息"
                )

        for msg, label in pending:
            self._wrap_and_send(msg, label)

        delay = batch.get('delay')
        if delay is not None:
            time.sleep(delay)

    def _wrap_and_send(self, msg, label, *, source_label=None,
                       prepend_ip_addr=None, raw_prefix=None):
        """统一外发入口：包装（IP 前缀）+ 发送 + 日志 + success 状态机。

        仅负责对组件已构建好的 MAVLink_message 进行再包装与外发，
        不参与消息内容构建。

        Args:
            msg: 组件构建好的 MAVLink_message
            label: 日志标签（如 "id=86(0x56)"）
            source_label: 来源组件名（如 "飞机172.16.3.180" / "PPS" / "机巢172.17.0.5"）
            prepend_ip_addr: IP 前缀地址（飞机用自身 IP，其他组件省略走 nest local_ip）
            raw_prefix: 原始 4 字节前缀，优先于 prepend_ip_addr。
                        用于 LPPC 心跳等场景（首字节 < 10 触发 GCS ParseLppcHeartbeat）。

        Returns:
            发送成功返回 True，否则 False
        """
        if msg is None:
            return False
        ok = self.fake_nest.send(
            msg, addr=self.addr,
            prepend_ip=True, prepend_ip_addr=prepend_ip_addr,
            raw_prefix=raw_prefix,
        )
        src = source_label or f"机巢{self.fake_nest.local_ip}:{self.fake_nest.local_port}"
        _log = self.log_manager.logger if self.log_manager else logger
        if not ok:
            with self._lock:
                self._reset_success_locked()
            _log.info(
                f"[TEST] {src} {label}消息模拟失败"
            )
        else:
            with self._lock:
                self._mark_success_locked()
            _log.info(
                f"[TEST] {src} {label}消息模拟成功"
            )
        return ok

    def _dispatch_airplane_response(self, airplane: _NestAirplane,
                                     received: MAVLink_message):
        """驱动一架轻型假飞机处理消息并外发。

        机巢内模式：机巢包装外发（prepend IP 前缀）。
        机巢外模式：飞机自有 socket 直发（无 IP 前缀，源 IP 即飞机 IP）。
        """
        if not airplane._msg_forwarding_enabled:
            return
        pending = airplane.process_message(received)
        for msg, label in pending:
            if airplane.is_external_mode:
                airplane.send_external(msg)
                logger.info(
                    f"[TEST] 飞机{airplane.ip}(外模式) {label}消息直发成功"
                )
            else:
                self._wrap_and_send(
                    msg, label,
                    source_label=f"飞机{airplane.ip}",
                    prepend_ip_addr=airplane.ip,
                )

    def _dispatch_pps_response(self, received: MAVLink_message):
        """驱动 PPS 处理消息，组件构建消息，机巢包装外发。"""
        if self._pps is None:
            return
        pending = self._pps.process_message(received)
        for msg, label in pending:
            self._wrap_and_send(msg, label, source_label="PPS")

    def _dispatch_pps_charger_response(self, received: MAVLink_message):
        """驱动 PPSCharger 处理消息，组件构建消息，机巢包装外发。"""
        if self._pps_charger is None:
            return
        pending = self._pps_charger.process_message(received)
        for msg, label in pending:
            self._wrap_and_send(msg, label, source_label="PPSCharger")

    def _dispatch_lppc_response(self, received: MAVLink_message):
        """驱动所有 LPPC 处理消息，组件构建消息，机巢包装外发。"""
        for ip_str, lppc in list(self._lppc_dict.items()):
            pending = lppc.process_message(received)
            for msg, label in pending:
                self._wrap_and_send(msg, label, source_label=f"LPPC_{ip_str}")

    # ------------------------------------------------------------------
    # 消息构建（@staticmethod）
    # ------------------------------------------------------------------
    @staticmethod
    def _ip_str_to_uint32(ip_str: str) -> int:
        """将 IP 字符串（如 "172.16.3.180"）转为 MAVLink 使用的 uint32（网络字节序）。"""
        return int.from_bytes(socket.inet_aton(ip_str), byteorder='little')

    @staticmethod
    def _build_id_000():
        """构建心跳的 id=0 消息（Nest→GCS，对齐协议文档 §4.4.2-④）。"""
        return MAVLink_message(msg_id=0, sys_id=SYS_ID_NEST, comp_id=COMP_ID_GCS, seq=0,
                               version=MAVLINK_VERSION,
                               fields={'custom_mode': 0,
                                       'type': 0,
                                       'autopilot': 20,
                                       'base_mode': 0,
                                       'system_status': 0,
                                       'mavlink_version': int(MAVLINK_VERSION)})

    @staticmethod
    def _build_id_002(serial=_DEFAULT_SERIAL, code=_DEFAULT_CODE):
        """构建身份信息的 id=2 消息（响应 get_identify_info, Nest→GCS）。"""
        return MAVLink_message(msg_id=2, seq=28, sys_id=SYS_ID_NEST, comp_id=COMP_ID_GCS,
                               version=MAVLINK_VERSION,
                               fields={'serial': serial,
                                       'code': code})

    @staticmethod
    def _build_id_086(nestIp=_DEFAULT_NEST_IP,
                      uavIp=None, chargeVolt=None,
                      lock_state=0, inpos=None,
                      chargePower=None, chargeTmp=None,
                      motorState=None, motorChipState=None,
                      pps_online=0, ppsCharger_online=0,
                      viCount=0, viState=0, viJudge=0,
                      nestState=0, nestStateInfo=None):
        """构建 msg_id=86 (MAVLink_nest_packed_state_message) 周期状态。

        nestIp 支持字符串 IP（如 "172.16.3.180"）或 uint32 整数，
        字符串会经由 _ip_str_to_uint32 转为网络字节序的 uint32。
        uavIp 元素同样支持字符串 IP 或 uint32 整数。

        默认全零——调用方应通过 update_nest_state() 注入真实状态。

        注意：v45 协议 msg_id=86 不含 latitude/longitude/altitude/fix_type/irda_inpos，
        这些字段在其他协议版本中存在，当前版本暂不填充。
        """
        # nestIp：字符串 → uint32 转换
        nestIp_uint32 = (_FakeNestSender._ip_str_to_uint32(nestIp)
                         if isinstance(nestIp, str) else nestIp)

        # uavIp：字符串 → uint32 转换
        if uavIp is None:
            uavIp_uint32 = [0, 0, 0, 0, 0]
        else:
            uavIp_uint32 = [
                _FakeNestSender._ip_str_to_uint32(ip)
                if isinstance(ip, str) else ip
                for ip in uavIp
            ]
        return MAVLink_message(msg_id=86, sys_id=SYS_ID_NEST, comp_id=COMP_ID_GCS,
                               version=MAVLINK_VERSION,
                               fields={
                                   'nestIp': nestIp_uint32,
                                   'uavIp': uavIp_uint32,
                                   'chargeVolt': list(chargeVolt) if chargeVolt is not None else [0, 0, 0, 0, 0],
                                   'lock_state': lock_state,
                                   'inpos': list(inpos) if inpos is not None else [0, 0, 0, 0, 0],
                                   'chargePower': list(chargePower) if chargePower is not None else [0, 0, 0, 0, 0],
                                   'chargeTmp': list(chargeTmp) if chargeTmp is not None else [0, 0, 0, 0, 0],
                                   'motorState': list(motorState) if motorState is not None else [0, 0, 0, 0],
                                   'motorChipState': list(motorChipState) if motorChipState is not None else [0, 0],
                                   'pps_online': pps_online,
                                   'ppsCharger_online': ppsCharger_online,
                                   'viCount': viCount,
                                   'viState': viState,
                                   'viJudge': viJudge,
                                   'nestState': nestState,
                                   'nestStateInfo': list(nestStateInfo) if nestStateInfo is not None else [0] * 16,
                               })

    @staticmethod
    def _build_id_087(nestIp=_DEFAULT_NEST_IP, nestId=_DEFAULT_NEST_ID, BoxId=_DEFAULT_BOX_ID,
                      nestSn=_DEFAULT_NEST_SN, nestHardVer=_DEFAULT_NEST_HARD_VER,
                      nestVersion=_DEFAULT_NEST_VERSION,
                      BoxSn=_DEFAULT_BOX_SN,
                      mavVer=int(MAVLINK_VERSION)):
        """构建 msg_id=87 (MAVLink_nest_extend_state_message) 扩展状态。

        响应 HEARTBEAT_DMD（msg_id=1）时发送。
        nestIp 支持字符串 IP（如 "172.16.3.180"）或 uint32 整数。
        nestId / BoxId 为 5 字节 char[5]（如 b"00001"）。
        新增 mavVer 字段（对齐协议文档 §5.2）。
        """
        nestIp_uint32 = (_FakeNestSender._ip_str_to_uint32(nestIp)
                         if isinstance(nestIp, str) else nestIp)
        return MAVLink_message(msg_id=87, sys_id=SYS_ID_NEST, comp_id=COMP_ID_GCS,
                               version=MAVLINK_VERSION,
                               fields={
                                   'nestIp': nestIp_uint32,
                                   'mavVer': mavVer,
                                   'nestId': nestId,
                                   'BoxId': BoxId,
                                   # 'ppsId': ppsId,                     # 非 msg_id=87 有效字段
                                   # 'ppsChargerId': ppsChargerId,       # 非 msg_id=87 有效字段
                                   'nestSn': nestSn,
                                   'nestHardVer': nestHardVer,
                                   'nestVersion': nestVersion,
                                   'BoxSn': BoxSn,
                                   # 'ppsSn': ppsSn,                     # 非 msg_id=87 有效字段
                                   # 'ppsVersion': ppsVersion,           # 非 msg_id=87 有效字段
                                   # 'ppsChargerSn': ppsChargerSn,       # 非 msg_id=87 有效字段
                                   # 'ppsChargerVersion': ppsChargerVersion,  # 非 msg_id=87 有效字段
                               })

    # ------------------------------------------------------------------
    # NEST_UAV_HEARTBEAT (msg_id=88) 消息定义（仅定义，暂不外发）
    # ------------------------------------------------------------------
    @staticmethod
    def _build_id_088_nest_to_uav():
        """构建 msg_id=88 NEST_UAV_HEARTBEAT（机巢→无人机方向，selfType=1）。
        协议文档 §7.8。当前仅定义暂不外发，字段按 v45 结构补齐默认值。
        """
        return MAVLink_message(msg_id=88, sys_id=SYS_ID_NEST, comp_id=COMP_ID_ALL,
                               version=MAVLINK_VERSION,
                               fields={'selfType': 1,
                                       'ip': 0,
                                       'mac': b'\x00' * 6,
                                       'ssid': b'\x00' * 8,
                                       'nestLayer': 0})

    @staticmethod
    def _build_id_088_uav_to_nest():
        """构建 msg_id=88 NEST_UAV_HEARTBEAT（无人机→机巢方向，selfType=0）。
        协议文档 §7.8。当前仅定义暂不外发，字段按 v45 结构补齐默认值。
        """
        return MAVLink_message(msg_id=88, sys_id=SYS_ID_UAV, comp_id=COMP_ID_NEST,
                               version=MAVLINK_VERSION,
                               fields={'selfType': 0,
                                       'ip': 0,
                                       'mac': b'\x00' * 6,
                                       'ssid': b'\x00' * 8,
                                       'nestLayer': 0})

    # ------------------------------------------------------------------
    # GET_LOWFREQ_INFO 处理（协议文档 §7.7）
    # ------------------------------------------------------------------
    def _handle_get_lowfreq_info(self, received):
        """处理 GET_LOWFREQ_INFO(74) 请求，回 LOWFREQ_INFO(75)。

        info_type 枚举（MAV_LOWFREQ_INFO_TYPE）：
            0=NEST_UAV_MACS  → 回巢内无人机 MAC 地址列表
            1=NEST_UAV_IPS   → 回巢内无人机 IP  地址列表
            2=NEST_UAV_SSIDS → 回巢内无人机 SSID 列表
        """
        info_type = received.fields.get('info_type', 0)
        info_value = self._build_lowfreq_info_value(info_type)
        msg = MAVLink_message(
            msg_id=self._MSG_ID_LOWFREQ_INFO, sys_id=SYS_ID_NEST,
            comp_id=COMP_ID_GCS, version=MAVLINK_VERSION,
            fields={'info_type': info_type, 'info_value': list(info_value)},
        )
        type_names = {0: 'MACS', 1: 'IPS', 2: 'SSIDS'}
        label = f'id=75(0x4B) LOWFREQ_INFO {type_names.get(info_type, "UNKNOWN")}'
        return [(msg, label)]

    def _build_lowfreq_info_value(self, info_type):
        """根据 info_type 构建 info_value (128 字节数组)。

        info_value 格式（协议文档 §7.7）：
            NEST_UAV_MACS (0): 5 × 6 字节 MAC 地址 = 30 字节，剩余填 0
            NEST_UAV_IPS  (1): 5 × 4 字节 IP 地址  = 20 字节，剩余填 0
            NEST_UAV_SSIDS(2): 5 个变长 SSID，以 \\0 分隔，最多填满 128 字节
        """
        buf = bytearray(128)
        airplanes = list(self._airplanes.keys())  # IP 字符串列表

        if info_type == 0:  # NEST_UAV_MACS
            # 根据 IP 生成伪 MAC（取 IP 末 4 字节 + 固定前缀 d0:27）
            for i in range(5):
                off = i * 6
                if i < len(airplanes):
                    parts = airplanes[i].split('.')
                    last = int(parts[-1]) if len(parts) == 4 else 0
                    buf[off:off + 6] = bytes([0xD0, 0x27, 0x88, 0x00, 0x00, min(last, 255)])
        elif info_type == 1:  # NEST_UAV_IPS
            for i in range(5):
                off = i * 4
                if i < len(airplanes):
                    ip_bytes = socket.inet_aton(airplanes[i])
                    buf[off:off + 4] = ip_bytes
        elif info_type == 2:  # NEST_UAV_SSIDS
            for i in range(5):
                if i < len(airplanes):
                    ssid = f"UAV_{airplanes[i]}"
                else:
                    ssid = f"UAV_{i}"
                ssid_bytes = ssid.encode('ascii', errors='replace')[:25]
                off = i * 26
                end = min(off + 26, 128)
                n = min(len(ssid_bytes), end - off - 1)
                buf[off:off + n] = ssid_bytes[:n]
        return bytes(buf)

    # ------------------------------------------------------------------
    # SET_CODE_NUMBER(28) 处理：回 COMMAND_ACK(77) 并更新机巢 nestId
    # ------------------------------------------------------------------
    def _handle_set_code_number(self, received):
        """SET_CODE_NUMBER(0x1C, 28) 处理：回 COMMAND_ACK(77) 并更新机巢编号。

        与 _handle_command_long 的 ACK 逻辑一致：
          - ack_sys_id = 收到消息的 comp_id（协议文档 §4.4.5），不可用时回退 SYS_ID_NEST。
          - 受 update_ack(fail_count/silence_count) 配置控制：
              silence_count: 前 N 次静默（_build_id_077 返回 None → 不回复、不更新）
              fail_count: 前 N 次 result!=0（不更新），之后 result=0（更新）
        仅当 ACK result==0 时把 self.nestId（0x57 上报）与 self.code（0x02 上报）
        同时更新为 code_number（5 字节规整）。

        Returns:
            list of (MAVLink_message, label) — 空列表表示静默不回复
        """
        code_number = received.fields.get('code_number')
        command = self._MSG_ID_SET_CODE_NUMBER
        ack_sys_id = received.comp_id if received.comp_id > 0 else SYS_ID_NEST

        msg = self._build_id_077(command=command, result=self.MAV_RESULT_ACCEPTED,
                                 ack_sys_id=ack_sys_id)
        if msg is None:
            return []  # 静默：不回复、不更新编号

        result = msg.fields.get('result', 0)
        if result == self.MAV_RESULT_ACCEPTED and code_number is not None:
            new_id = bytes(code_number)[:5].ljust(5, b'0')
            with self._lock:
                self.nestId = new_id
                self.code = new_id  # 0x02 身份消息的 code 字段同步更新
                # 注意：SET_CODE_NUMBER 改号不联动飞机消息 8 的机巢定位字段——
                # 按 update_state_extend 的字段优先级定义，仅出入巢动作覆盖手工值
            self.log_manager.logger.info(
                f"[TEST] 机巢{self.fake_nest.local_ip} SET_CODE_NUMBER(28) "
                f"result={result} nestId -> {self.nestId} code -> {self.code}"
            )
        return [(msg, f'id=77(0x4D) SET_CODE_NUMBER result={result} sys={ack_sys_id}')]

    # COMMAND_LONG 处理（对齐假飞机 _FakeAirplaneMessageSender._handle_command_long）
    # ------------------------------------------------------------------
    def _handle_command_long(self, received):
        """COMMAND_LONG(76) 处理：解析命令并回 COMMAND_ACK(77)。

        支持的命令：
          - MAV_CMD_DO_SET_SERVO (183) + param7=13 → LED 灯光控制（仅 ACK）
          - MAV_CMD_NEST_PPS_LOCK_CONTROL (40061) → PPS 锁定控制
          - MAV_CMD_NEST_PPS_CHARGER_CMD (40062) → PPS 充电器命令
          - MAV_CMD_NEST_UAV_LOCK (40070) → 无人机锁定
          - MAV_CMD_NEST_UAV_CHARGER_CMD (40071) → 无人机充电器命令
          - MAV_CMD_UPDATE_NEST (40081) → 更新机巢固件
          - MAV_CMD_UPDATE_NEST_BOX (40082) → 更新机箱
          - MAV_CMD_UPDATE_NEST_PPS (40083) → 更新 PPS
          - MAV_CMD_UPDATE_NEST_PPSCHG (40084) → 更新 PPS 充电器
          - MAV_CMD_UPDATE_NEST_IRDAMCU (40085) → 更新红外 MCU
          - MAV_CMD_UPDATE_NEST_UAV (40086) → 更新巢内无人机

        ACK sys_id 策略（对齐协议文档 §4.4.5）：
            GCS 在等待 ACK 时对比"接收帧的 sysid"与"请求时使用的 compid"。
            因此 ACK 的 sys_id 必须与 GCS 发送命令时的 comp_id 一致：
              - 发给机巢主控（compid=40）→ ACK sys_id=40
              - 发给充电器（compid=41）  → ACK sys_id=41
              - 发给 PPS（compid=36）     → ACK sys_id=36
              - 发给 LPPC（compid=37）    → ACK sys_id=37

        Returns:
            list of (MAVLink_message, label) — 至少包含 COMMAND_ACK
        """
        command = received.fields.get('command', 0)
        result = self.MAV_RESULT_ACCEPTED
        # ACK sys_id = 收到命令的 comp_id（协议文档 §4.4.5）
        ack_sys_id = received.comp_id if received.comp_id > 0 else SYS_ID_NEST

        # LED 灯光控制: MAV_CMD_DO_SET_SERVO(183), param7=13
        if command == self.MAV_CMD_DO_SET_SERVO:
            param7 = received.fields.get('param7', 0)
            if param7 == 13:
                # 灯光控制：param1=R, param2=G, param3=B, param4=Channel
                self.log_manager.logger.info(
                    f"[TEST] 机巢{self.fake_nest.local_ip} "
                    f"LED控制 R={received.fields.get('param1', 0)} "
                    f"G={received.fields.get('param2', 0)} "
                    f"B={received.fields.get('param3', 0)} "
                    f"Ch={received.fields.get('param4', 0)}"
                )
        # PPS 锁定控制
        elif command == self.MAV_CMD_NEST_PPS_LOCK_CONTROL:
            self.log_manager.logger.info(
                f"[TEST] 机巢{self.fake_nest.local_ip} "
                f"PPS锁定控制 param1={received.fields.get('param1', 0)}"
            )
        # PPS 充电器命令
        elif command == self.MAV_CMD_NEST_PPS_CHARGER_CMD:
            self.log_manager.logger.info(
                f"[TEST] 机巢{self.fake_nest.local_ip} "
                f"PPS充电器命令 param1={received.fields.get('param1', 0)}"
            )
        # 无人机锁定
        elif command == self.MAV_CMD_NEST_UAV_LOCK:
            self.log_manager.logger.info(
                f"[TEST] 机巢{self.fake_nest.local_ip} "
                f"无人机锁定 param1={received.fields.get('param1', 0)}"
            )
        # 无人机充电器命令
        elif command == self.MAV_CMD_NEST_UAV_CHARGER_CMD:
            self.log_manager.logger.info(
                f"[TEST] 机巢{self.fake_nest.local_ip} "
                f"无人机充电器命令 param1={received.fields.get('param1', 0)}"
            )
        # LPPC 充电使能/禁用
        elif command == self.MAV_CMD_LPPC_CHG_EN_CMD:
            self.log_manager.logger.info(
                f"[TEST] 机巢{self.fake_nest.local_ip} "
                f"LPPC充电使能 param1={received.fields.get('param1', 0)}"
            )
        # LPPC 控制命令（50001-50008）
        elif self.MAV_CMD_LPPC_POWER_ON <= command <= self.MAV_CMD_LPPC_QUERY_BATTERY_HISTORY:
            cmd_names = {
                self.MAV_CMD_LPPC_POWER_ON: 'POWER_ON',
                self.MAV_CMD_LPPC_POWER_OFF: 'POWER_OFF',
                self.MAV_CMD_LPPC_SLEEP: 'SLEEP',
                self.MAV_CMD_LPPC_WAKE: 'WAKE',
                self.MAV_CMD_LPPC_ARM: 'ARM',
                self.MAV_CMD_LPPC_DISARM: 'DISARM',
                self.MAV_CMD_LPPC_PARACHUTE_OPEN: 'PARACHUTE_OPEN',
                self.MAV_CMD_LPPC_QUERY_BATTERY_HISTORY: 'QUERY_BATTERY_HISTORY',
            }
            self.log_manager.logger.info(
                f"[TEST] 机巢{self.fake_nest.local_ip} "
                f"LPPC命令 {cmd_names.get(command, 'UNKNOWN')} "
                f"param1={received.fields.get('param1', 0)}"
            )
        # 无人机电源控制命令（§4.3 经机巢转发；STANDBY param1=PowerOPType）
        elif command in (self.MAV_CMD_POWER_ON, self.MAV_CMD_POWER_OFF,
                         self.MAV_CMD_REST, self.MAV_CMD_WAKE_UP,
                         self.MAV_CMD_STANDBY):
            pwr_names = {
                self.MAV_CMD_STANDBY: 'STANDBY',
                self.MAV_CMD_POWER_ON: 'POWER_ON',
                self.MAV_CMD_POWER_OFF: 'POWER_OFF',
                self.MAV_CMD_REST: 'REST',
                self.MAV_CMD_WAKE_UP: 'WAKE_UP',
            }
            extra = ""
            if command == self.MAV_CMD_STANDBY:
                op = int(received.fields.get('param1', 0))
                op_names = {0: 'Resume', 1: 'Standby', 2: 'Shutdown',
                            3: 'ForceShutdown', 4: 'BatDormancy', 5: 'PowerOn'}
                extra = f" PowerOPType={op_names.get(op, op)}"
            self.log_manager.logger.info(
                f"[TEST] 机巢{self.fake_nest.local_ip} "
                f"电源控制 {pwr_names.get(command, command)}{extra} "
                f"param1={received.fields.get('param1', 0)}"
            )
        # 固件更新命令（40081-40086）
        elif self.MAV_CMD_UPDATE_NEST <= command <= self.MAV_CMD_UPDATE_NEST_UAV:
            cmd_names = {
                self.MAV_CMD_UPDATE_NEST: 'UPDATE_NEST',
                self.MAV_CMD_UPDATE_NEST_BOX: 'UPDATE_NEST_BOX',
                self.MAV_CMD_UPDATE_NEST_PPS: 'UPDATE_NEST_PPS',
                self.MAV_CMD_UPDATE_NEST_PPSCHG: 'UPDATE_NEST_PPSCHG',
                self.MAV_CMD_UPDATE_NEST_IRDAMCU: 'UPDATE_NEST_IRDAMCU',
                self.MAV_CMD_UPDATE_NEST_UAV: 'UPDATE_NEST_UAV',
            }
            self.log_manager.logger.info(
                f"[TEST] 机巢{self.fake_nest.local_ip} "
                f"固件更新 {cmd_names.get(command, 'UNKNOWN')} "
                f"param1={received.fields.get('param1', 0)} "
                f"param2={received.fields.get('param2', 0)} "
                f"param3={received.fields.get('param3', 0)}"
            )
        else:
            result = self.MAV_RESULT_ACCEPTED
            self.log_manager.logger.warning(
                f"[TEST] 机巢{self.fake_nest.local_ip} "
                f"收到不支持的 COMMAND_LONG command={command}"
            )

        msg = self._build_id_077(command=command, result=result,
                                 ack_sys_id=ack_sys_id)
        if msg is None:
            return []
        return [(msg, f'id=77(0x4D) cmd={command} result={result} sys={ack_sys_id}')]

    def _build_id_077(self, command, result=0, ack_sys_id=None):
        """构建 command_ack 的 id=77 消息（对齐假飞机 _build_id_077_cmd）。

        支持 ACK 静默/失败响应配置：
        - silence_count: 前 N 次不回复（静默），之后回复 result=0
        - fail_count: 前 N 次回复 result!=0，之后回复 result=0
        各 command 独立计数，10s 未收到该 command 则计数器自动重置。
        返回 None 表示静默（不应发送任何内容）。

        ACK sys_id 必须与 GCS 发送时的 comp_id 匹配（协议文档 §4.4.5）：
          - GCS → 机巢主控 (compid=40) → ACK sys_id=40
          - GCS → 充电器   (compid=41) → ACK sys_id=41
          - GCS → PPS      (compid=36) → ACK sys_id=36

        Args:
            command: MAVLink command ID (uint16)
            result: MAV_RESULT（0=ACCEPTED, 3=UNSUPPORTED）
            ack_sys_id: ACK 的 sys_id，默认 SYS_ID_NEST(40)
        """
        # 检查 ACK 静默响应配置（各 command 独立计数和计时）
        if self._ack_silence_count > 0:
            now = time.time()
            counter = self._ack_silence_counters.get(command, 0)
            last_time = self._ack_silence_last_time.get(command, 0)

            # 该 command 10s 未出现 → 重置计数器
            if now - last_time > 10.0:
                counter = 0

            if counter < self._ack_silence_count:
                counter += 1
                self._ack_silence_counters[command] = counter
                self._ack_silence_last_time[command] = now
                return None  # 静默，不回复

            self._ack_silence_counters[command] = counter
            self._ack_silence_last_time[command] = now

        # 检查 ACK 失败响应配置（各 command 独立计数和计时）
        if self._ack_fail_count > 0:
            now = time.time()
            counter = self._ack_fail_counters.get(command, 0)
            last_time = self._ack_fail_last_time.get(command, 0)

            # 该 command 10s 未出现 → 重置计数器
            if now - last_time > 10.0:
                counter = 0

            if counter < self._ack_fail_count:
                result = 1  # Temp Rejected
                counter += 1
            else:
                result = 0  # MAV_RESULT_ACCEPTED

            self._ack_fail_counters[command] = counter
            self._ack_fail_last_time[command] = now

        if ack_sys_id is None:
            ack_sys_id = SYS_ID_NEST
        return MAVLink_message(msg_id=77, sys_id=ack_sys_id, comp_id=COMP_ID_GCS,
                               version=MAVLINK_VERSION,
                               fields={
                                   'command': command,
                                   'result': result,
                               })


# ==================================================================
# _FakeNestSenders：批量假机巢管理器
# ==================================================================
class _FakeNestSenders:
    """批量假机巢管理器：一次性创建多台假机巢及其响应线程。

    使用方式：
        mgr = _FakeNestSenders(count, start_ip, start_serial, start_code,
                               start_nestId, start_uav_ip, log_manager)
        # 构造时即已为每台机巢启动响应线程，并自动分配递增的飞机 IP
        ...
        mgr.stop()           # 停止所有线程并关闭底层 FakeNest

    构造时按规则为每台机巢分配：
        - IP：start_ip 末段逐个 +1（不超过 .255）
        - serial：start_serial 拼接当前 code_base（按 20 字节规整）
        - code  ：逐个 +1（int -> 5 字节 bytes）
        - nestId：由 start_nestId (int) 逐个 +1 后转为 5 字节 char[5]（右对齐补零）
        - nestSn：b"nestSn" + nestId 补零至 5 位（20 字节右对齐）
        - uavIp：每台机巢 5 架飞机，IP 从 start_uav_ip 起依次递增

    Attributes:
        nest_senders: list[_FakeNestSender]，与 fake_nests 一一对应
        fake_nests: list[FakeNest]，底层 UDP 套接字实例

    Args:
        count: 机巢数量（>= 1）
        start_ip: 起始 IP，如 "172.16.3.190"
        start_serial: 起始序列号前缀（str/bytes 均可；最终会被规整为 20 字节）
        start_code: 起始 code（int），逐个 +1
        start_nestId: 起始 nestId（int），逐个 +1
        start_uav_ip: 起始飞机 IP，如 "172.16.3.200"，每巢 5 架递增
        start_nest_plane_layout: 起始飞机排布 [1,0,1,0,1]，默认全 1（5 槽全启用）
        log_manager: 日志管理器
    """

    # —— 全局机巢计数器（跨多次"添加"调用递增，保证经度不重复）——
    _global_nest_counter: int = 0

    # —— 定位常量（1e7 度 / mm）——
    _POS_BASE_LAT: int = 226868664   # 基础纬度（机巢列）
    _POS_BASE_LON: int = 1140224548  # 基础经度
    _POS_STEP: int = 100             # 0.00001° = 100
    _POS_ALT_STEP: int = 150         # 槽位间高度差（mm）

    def __init__(self, count, start_ip, start_serial, start_code,
                 start_nestId, start_uav_ip, log_manager,
                 start_nest_plane_layout=None):
        if count < 1:
            raise ValueError("count 必须 >= 1")

        code_base = int(start_code)
        nestId_base = int(start_nestId)
        self.nest_senders = []
        self.fake_nests = []

        base = tuple(int(p) for p in start_ip.split('.'))
        uav_base = tuple(int(p) for p in start_uav_ip.split('.'))
        if base[3] + count - 1 > 255:
            raise ValueError(
                f"起始 IP {start_ip} 末段={base[3]} 数量={count} 超出 .255 边界"
            )

        # 先建好所有传输层（FakeNest）
        try:
            for i in range(count):
                ip = f"{base[0]}.{base[1]}.{base[2]}.{base[3] + i}"
                fake_nest = FakeNest(ip_addr=ip)
                self.fake_nests.append(fake_nest)

            # 再为每台传输层创建响应线程
            for i, fake_nest in enumerate(self.fake_nests):
                serial = self._build_serial(start_serial, code_base)
                code_bytes = self._build_code(code_base)
                nestId_bytes = self._build_id_bytes(nestId_base)
                nestSn = self._build_nest_sn(nestId_base)
                # 每台机巢 5 架飞机，IP 依次递增
                uav_offset = i * 5
                uavIp = [
                    f"{uav_base[0]}.{uav_base[1]}.{uav_base[2]}.{uav_base[3] + uav_offset + j}"
                    for j in range(5)
                ]
                sender = _FakeNestSender(
                    log_manager, fake_nest,
                    addr=(fake_nest.ground_station_ip, fake_nest.ground_station_port),
                    serial=serial,
                    code=code_bytes,
                    nestId=nestId_bytes,
                    nestSn=nestSn,
                    nest_plane_layout=start_nest_plane_layout,
                )
                # 自动分配递增的飞机 IP，触发 _NestAirplane 创建
                sender.update_nest_state(uavIp=uavIp)
                code_base += 1
                nestId_base += 1
                self.nest_senders.append(sender)

            # —— 自动定位：每台机巢的参考经纬度 + 巢内飞机海拔递增 ——
            for ni, sender in enumerate(self.nest_senders):
                global_nest_idx = _FakeNestSenders._global_nest_counter + ni
                ref_lat = _FakeNestSenders._POS_BASE_LAT
                ref_lon = _FakeNestSenders._POS_BASE_LON + global_nest_idx * _FakeNestSenders._POS_STEP
                sender._nest_ref_lat = ref_lat
                sender._nest_ref_lon = ref_lon
                logger.info(
                    f"[POS] 机巢 #{global_nest_idx} ip={sender.fake_nest.local_ip} "
                    f"ref_lat={ref_lat} ref_lon={ref_lon}"
                )
                for ip_str, airplane in sender._airplanes.items():
                    slot = airplane._slot_index if airplane._slot_index is not None else 0
                    # 经纬 = 机巢参考经纬度+槽位，高度 = 槽位 × 150mm
                    ref_lat_slot = int(ref_lat + slot)
                    ref_lon_slot = int(ref_lon + slot)
                    alt = slot * _FakeNestSenders._POS_ALT_STEP
                    airplane.update_position(ref_lat_slot, ref_lon_slot,
                                            ref_lat_slot, ref_lon_slot,
                                            cur_alt=alt, tar_alt=alt)
                    logger.info(
                        f"[POS] 巢飞机 ip={ip_str} slot={slot} "
                        f"lat={ref_lat_slot} lon={ref_lon_slot} alt={alt}"
                    )
            _FakeNestSenders._global_nest_counter += count

        except Exception:
            # 部分构造失败：清理已创建的 sender + FakeNest，再向上抛
            # 备注：网卡上的辅助 IP 暂未撤销（FakeNest.close() 不会调用 Remove-NetIPAddress），
            # 若想完整清理，需要 FakeNest 记录"本实例添加的 IP"并在 close 时撤销。
            for sender in self.nest_senders:
                try:
                    sender._cleanup()
                except Exception as e:
                    logger.error(f"sender 清理失败: {e}")
            for fake_nest in self.fake_nests:
                try:
                    fake_nest.close()
                except Exception as e:
                    logger.error(f"FakeNest 关闭失败: {e}")
            raise

    def stop(self):
        """停止所有响应线程并关闭底层 FakeNest。"""
        for nest_sender in self.nest_senders:
            nest_sender.stop()
        for fake_nest in self.fake_nests:
            fake_nest.close()

    # ------------------------------------------------------------------
    # 辅助：构造符合协议字段长度的 serial / code bytes
    # ------------------------------------------------------------------
    @staticmethod
    def _build_serial(prefix, code_base: int) -> bytes:
        """把 prefix 拼接 code（4 位补零），整体长度不补充。"""
        prefix_bytes = prefix.encode('utf-8') if isinstance(prefix, str) else bytes(prefix)
        suffix = f"{code_base:04d}".encode('utf-8')
        return prefix_bytes + suffix

    @staticmethod
    def _build_code(code_base: int) -> bytes:
        """把 int code 规整为 5 字节（右对齐补零）。"""
        s = str(code_base).encode('utf-8')
        if len(s) >= 5:
            return s[:5]
        return s.rjust(5, b'0')

    @staticmethod
    def _build_id_bytes(value: int) -> bytes:
        """把 int id 规整为 5 字节 char[5]（右对齐补零），用于 nestId / BoxId 等字段。"""
        s = str(value).encode('utf-8')
        if len(s) >= 5:
            return s[:5]
        return s.rjust(5, b'0')

    @staticmethod
    def _build_nest_sn(nestId) -> bytes:
        """根据 nestId 生成 nestSn（20 字节）。

        nestId 可为 int 或 5 字节 bytes（如 b"00001"）；int 时自动转为 5 位补零。
        规则：b"nestSn" + nestId 补零至 5 位，右对齐补零至 20 字节。
        Examples:
            nestId=1       → b'0000000nestSn00001'
            nestId=b"00001" → b'0000000nestSn00001'
            nestId=123     → b'0000000nestSn00123'
        """
        if isinstance(nestId, bytes):
            nestId = int(nestId.decode('utf-8'))
        suffix = f"{nestId:05d}".encode('utf-8')
        raw = b'nestSn' + suffix
        if len(raw) >= 20:
            return raw[:20]
        return raw.rjust(20, b'0')


if __name__ == "__main__":
    log_manager = LogManager(log_dir="logs\\")

    # ── 创建 1 台机巢（nestId=1, 飞机 IP 从 172.16.3.200 起）──
    senders = _FakeNestSenders(
        count=1,
        start_ip="172.16.3.191",
        start_serial="NESTF0K",
        start_code=1,
        start_nestId=1,
        start_uav_ip="172.16.3.200",
        log_manager=log_manager,
    )

    nest = senders.nest_senders[0]

    # ── 扩展状态（msg_id=87）──
    nest.update_nest_extend(
        nestVersion=b"NEST_V42",
        BoxSn=b"BOX000000000000000001",
    )

    # ── 周期状态（msg_id=86，按抓包 hex 填充真实值）──
    # 抓包解析: nestIp=172.17.0.3 uavIp=[0.0.0.0, 172.16.0.12, 172.16.0.13, 172.16.0.14, 172.16.0.15]
    # chargeVolt=[0, 3909, 4180, 3896, 4107] lock_state=2 inpos=[1,1,0,2,2]
    # chargePower=[0, 76, 12, 93, 52] chargeTmp=[0, 45, 10, 52, 53]
    # motorState=[0,0,0,0] motorChipState=[0,1] pps_online=1 ppsCharger_online=0
    # nestState=0 nestStateInfo="HEALTH"
    nest.update_nest_state(
        uavIp=["0.0.0.0", "172.16.0.12", "172.16.0.13", "172.16.0.14", "172.16.0.15"],
        chargeVolt=[0, 3909, 4180, 3896, 4107],
        lock_state=2,
        inpos=[1, 1, 0, 2, 2],
        chargePower=[0, 76, 12, 93, 52],
        chargeTmp=[0, 45, 10, 52, 53],
        motorState=[0, 0, 0, 0],
        motorChipState=[0, 1],
        pps_online=1,
        ppsCharger_online=0,
        nestState=0,
        nestStateInfo=[72, 69, 65, 76, 84, 72, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    )

    logger.info(
        f"[MAIN] 机巢 {nest.fake_nest.local_ip} 已启动, "
        f"下属飞机: {list(nest._airplanes.keys())}"
    )

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("正在停止 FakeNest...")
        senders.stop()
        logger.info("FakeNest 已完全停止。")
