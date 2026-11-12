"""MonitorEngine — 网卡嗅探引擎

基于 scapy AsyncSniffer 在指定网卡上捕获 UDP 流量，
自动识别 MAVLink 消息并解析，结果写入 MonitorModel。
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable

import logging

from .model import MonitorModel, MessageRecord, FieldDetail
from .parser import MavlinkParser
from .radio_parser import RadioDavParser

logger = logging.getLogger(__name__)

# ── 模块级 scapy 导入（避免在每包回调中重复 import）──
try:
    from scapy.all import AsyncSniffer, IP, TCP, UDP  # noqa: F811
except ImportError:
    AsyncSniffer = None  # type: ignore[assignment]
    IP = UDP = TCP = None


# ═══════════════════════════════════════════════════════════════
# InterfaceNode
# ═══════════════════════════════════════════════════════════════
@dataclass
class InterfaceNode:
    """网卡嗅探节点"""
    interface_name: str = ""
    sniffer = None  # scapy.AsyncSniffer
    running: bool = False
    packet_count: int = 0
    error_count: int = 0
    mavlink_count: int = 0


@dataclass
class UdpCaptureNode:
    """UDP socket 监听节点 — 捕获内部/loopback UDP 流量"""
    host: str = "0.0.0.0"
    port: int = 14550
    socket = None       # socket.socket
    thread = None       # threading.Thread
    running: bool = False
    packet_count: int = 0
    error_count: int = 0
    mavlink_count: int = 0


@dataclass
class RadioCaptureNode:
    """电台 DAV 协议 UDP 监听节点 — 捕获 R2 电台 DAV 流量"""
    host: str = "0.0.0.0"
    port: int = 14555
    socket = None           # socket.socket
    thread = None           # threading.Thread
    running: bool = False
    packet_count: int = 0
    error_count: int = 0
    radio_count: int = 0    # 成功解析的电台消息数
    parser: RadioDavParser = None  # 电台 DAV 解析器


@dataclass
class GcsAppCaptureNode:
    """地面站应用 TCP 监控节点 — 捕获地面站与云平台的 TCP/TLS 流量元数据。

    独立 scapy AsyncSniffer（filter="tcp port N"），复用当前选中网卡；
    不解析密文内容，仅记录五元组/方向/字节数/TCP 标志/载荷 hex。
    降噪：纯 ACK（无 payload 且无 SYN/FIN/RST）不生成记录。
    """
    iface: str = ""             # 嗅探网卡
    port: int = 443             # 监控的对端端口（云端 HTTPS）
    sniffer = None              # scapy.AsyncSniffer
    running: bool = False
    packet_count: int = 0       # 匹配 filter 的 TCP 包总数
    error_count: int = 0
    app_count: int = 0          # 生成记录数（降噪后）


# ═══════════════════════════════════════════════════════════════
# MonitorEngine
# ═══════════════════════════════════════════════════════════════
class MonitorEngine:
    """网卡嗅探监听引擎。

    特性：
        - scapy AsyncSniffer 混杂模式抓包
        - 自动识别标准格式 + 4 字节 IP 前缀特殊格式
        - 解析失败/非 MAVLink 包静默丢弃
        - CRC 失败消息仍然入缓冲（红色标记）
        - 线程安全写入 MonitorModel
    """

    BUFSIZE = 65535
    _BATCH_SIZE = 64      # 批量缓冲区：累积到此数量后批量写入 model
    _BATCH_MAX_AGE = 1.0  # 批量缓冲区：最大滞留时间（秒），超时强制刷新

    def __init__(self, parser: MavlinkParser, model: MonitorModel,
                 on_record: Callable[[MessageRecord], None] | None = None):
        """
        Args:
            parser: MAVLink 解析器实例（需已加载 config）
            model: 环形缓冲
            on_record: 每条新记录的回调（可选，用于 GUI 实时通知）
        """
        self.parser = parser
        self.model = model
        self._on_record = on_record
        self._interface_node: InterfaceNode | None = None
        self._udp_node: UdpCaptureNode | None = None
        self._radio_node: RadioCaptureNode | None = None
        self._gcs_app_node: GcsAppCaptureNode | None = None
        self._paused = False
        self._nest_enabled: bool = True  # 机巢(ip_prefixed)格式解析开关，默认开启
        self._local_ips: set[str] = set()  # 本机 IP 列表，用于方向判定
        # ── 批量缓冲区 ──
        self._batch_buffer: list[MessageRecord] = []
        self._batch_last_flush: float = 0.0

    # ═══════════════════════════════════════════════════════════
    # 启停控制
    # ═══════════════════════════════════════════════════════════
    def start(self) -> None:
        """启动网卡嗅探。"""
        if self._interface_node is None:
            raise RuntimeError("请先调用 set_interface() 配置网卡")

        if self._interface_node.running:
            return

        try:
            from scapy.all import AsyncSniffer
        except ImportError:
            raise RuntimeError(
                "scapy 未安装，请执行: pip install scapy\n"
                "网卡嗅探模式需要 scapy 库支持。"
            )

        # 缓存本机 IP 用于方向检测
        self._cache_local_ips()

        iface_node = self._interface_node
        iface_node.running = True
        iface_node.packet_count = 0
        iface_node.error_count = 0
        iface_node.mavlink_count = 0

        self._paused = False

        # 创建 AsyncSniffer，filter="udp" 在内核层面只捕获 UDP
        iface_node.sniffer = AsyncSniffer(
            iface=iface_node.interface_name,
            filter="udp",
            prn=self._sniff_callback,
            store=False,
        )
        iface_node.sniffer.start()
        logger.info(f"NIC sniffing started on interface: {iface_node.interface_name}")

    def stop(self) -> None:
        """停止网卡嗅探（同时停止 UDP 监听）。"""
        # 先刷新批量缓冲区中剩余的消息
        self._flush_batch()
        if self._interface_node is None:
            return

        iface_node = self._interface_node
        iface_node.running = False

        if iface_node.sniffer is not None:
            try:
                iface_node.sniffer.stop()
            except Exception:
                pass
            iface_node.sniffer = None

        # 同时停止 UDP 监听
        self.stop_udp()
        # 同时停止电台监听
        self.stop_radio()
        # 同时停止地面站应用监控
        self.stop_gcs_app()

        logger.info("NIC sniffing stopped")

    def pause(self) -> None:
        """暂停录入（底层继续抓包，但丢弃数据）。"""
        self._paused = True

    def resume(self) -> None:
        """恢复录入。"""
        self._paused = False

    @property
    def is_running(self) -> bool:
        nic_running = self._interface_node is not None and self._interface_node.running
        udp_running = self._udp_node is not None and self._udp_node.running
        radio_running = self._radio_node is not None and self._radio_node.running
        gcs_app_running = self._gcs_app_node is not None and self._gcs_app_node.running
        return nic_running or udp_running or radio_running or gcs_app_running

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def nest_enabled(self) -> bool:
        """机巢(ip_prefixed)格式解析是否启用。"""
        return self._nest_enabled

    @nest_enabled.setter
    def nest_enabled(self, value: bool) -> None:
        self._nest_enabled = value

    # ═══════════════════════════════════════════════════════════
    # 网卡配置
    # ═══════════════════════════════════════════════════════════
    @property
    def interface_node(self) -> InterfaceNode | None:
        return self._interface_node

    def set_interface(self, name: str) -> None:
        """配置要嗅探的网卡接口名称。"""
        if self._interface_node is None:
            self._interface_node = InterfaceNode(interface_name=name)
        else:
            self._interface_node.interface_name = name

    @property
    def active_interface_name(self) -> str:
        """当前活跃的网卡名称。"""
        if self._interface_node is not None:
            return self._interface_node.interface_name
        return ""

    # ═══════════════════════════════════════════════════════════
    # 统计
    # ═══════════════════════════════════════════════════════════
    @property
    def nic_packet_count(self) -> int:
        if self._interface_node is not None:
            return self._interface_node.packet_count
        return 0

    @property
    def nic_error_count(self) -> int:
        if self._interface_node is not None:
            return self._interface_node.error_count
        return 0

    @property
    def nic_mavlink_count(self) -> int:
        if self._interface_node is not None:
            return self._interface_node.mavlink_count
        return 0

    # ═══════════════════════════════════════════════════════════
    # UDP 监听器管理
    # ═══════════════════════════════════════════════════════════
    def set_udp_listener(self, host: str = "0.0.0.0", port: int = 14550) -> None:
        """配置 UDP 监听器 host 和 port。"""
        if self._udp_node is None:
            self._udp_node = UdpCaptureNode(host=host, port=port)
        else:
            self._udp_node.host = host
            self._udp_node.port = port

    def start_udp(self) -> None:
        """启动 UDP socket 监听器（后台线程）。"""
        if self._udp_node is None:
            raise RuntimeError("请先调用 set_udp_listener() 配置 UDP 监听")

        if self._udp_node.running:
            return

        self._cache_local_ips()
        node = self._udp_node
        node.running = True
        node.packet_count = 0
        node.error_count = 0
        node.mavlink_count = 0

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)  # 每秒检查 running 标志
        try:
            sock.bind((node.host, node.port))
        except OSError as e:
            node.running = False
            raise RuntimeError(
                f"UDP bind 失败 {node.host}:{node.port}: {e}"
            )

        # 如果 port=0，记录 OS 分配的实际端口
        actual_port = sock.getsockname()[1]
        if actual_port != node.port:
            node.port = actual_port

        node.socket = sock
        node.thread = threading.Thread(
            target=self._udp_listen_loop,
            daemon=True,
            name=f"udp-listener-{node.host}:{node.port}",
        )
        node.thread.start()
        logger.info(f"UDP listener started on {node.host}:{node.port}")

    def stop_udp(self) -> None:
        """停止 UDP 监听器线程并关闭 socket。"""
        if self._udp_node is None:
            return

        node = self._udp_node
        node.running = False

        if node.socket is not None:
            try:
                node.socket.close()
            except Exception:
                pass
            node.socket = None

        if node.thread is not None and node.thread.is_alive():
            node.thread.join(timeout=3.0)
            node.thread = None

        logger.info("UDP listener stopped")

    def _udp_listen_loop(self) -> None:
        """后台线程：recvfrom 循环接收 UDP 数据包。"""
        node = self._udp_node
        sock = node.socket
        bufsize = self.BUFSIZE

        # 缓存 sockname，避免热循环中每包调用 getsockname()（系统调用）
        try:
            _cached_dst_ip, _cached_dst_port = sock.getsockname()
        except Exception:
            _cached_dst_ip, _cached_dst_port = ("0.0.0.0", node.port)

        while node.running:
            try:
                data, addr = sock.recvfrom(bufsize)
            except socket.timeout:
                continue  # 检查 running 标志并重试
            except OSError:
                break      # socket 已关闭

            if self._paused:
                continue

            node.packet_count += 1
            src_ip, src_port = addr
            dst_ip = self._resolve_listen_dst_ip(_cached_dst_ip, self._local_ips)
            dst_port = _cached_dst_port

            node_id = f"udp_{node.host}:{node.port}"
            try:
                success = self._process_raw_packet(
                    data, src_ip, src_port, dst_ip, dst_port,
                    node_id, "udp",
                )
                if success:
                    node.mavlink_count += 1
                else:
                    node.error_count += 1
            except Exception:
                node.error_count += 1
                self.model.mark_error()

    # ── UDP 统计属性 ──
    @property
    def udp_packet_count(self) -> int:
        if self._udp_node is not None:
            return self._udp_node.packet_count
        return 0

    @property
    def udp_error_count(self) -> int:
        if self._udp_node is not None:
            return self._udp_node.error_count
        return 0

    @property
    def udp_mavlink_count(self) -> int:
        if self._udp_node is not None:
            return self._udp_node.mavlink_count
        return 0

    @property
    def is_udp_running(self) -> bool:
        return self._udp_node is not None and self._udp_node.running

    @property
    def udp_host(self) -> str:
        if self._udp_node is not None:
            return self._udp_node.host
        return ""

    @property
    def udp_port(self) -> int:
        if self._udp_node is not None:
            return self._udp_node.port
        return 0

    # ═══════════════════════════════════════════════════════════
    # 电台 DAV 监听器管理
    # ═══════════════════════════════════════════════════════════
    def set_radio_listener(self, host: str = "0.0.0.0", port: int = 14555) -> None:
        """配置电台 DAV 监听器 host 和 port。"""
        parser = RadioDavParser()
        if self._radio_node is None:
            self._radio_node = RadioCaptureNode(host=host, port=port, parser=parser)
        else:
            self._radio_node.host = host
            self._radio_node.port = port
            if self._radio_node.parser is None:
                self._radio_node.parser = parser

    def load_radio_config(self, config_path: str) -> bool:
        """加载电台消息配置 JSON 到解析器。"""
        if self._radio_node is None:
            self._radio_node = RadioCaptureNode()
        if self._radio_node.parser is None:
            self._radio_node.parser = RadioDavParser()
        return self._radio_node.parser.load_config(config_path)

    def start_radio(self) -> None:
        """启动电台 DAV UDP 监听器（后台线程）。"""
        if self._radio_node is None:
            self._radio_node = RadioCaptureNode()
            self._radio_node.parser = RadioDavParser()

        if self._radio_node.running:
            return

        self._cache_local_ips()
        node = self._radio_node
        node.running = True
        node.packet_count = 0
        node.error_count = 0
        node.radio_count = 0

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind((node.host, node.port))
        except OSError as e:
            node.running = False
            raise RuntimeError(
                f"电台 UDP bind 失败 {node.host}:{node.port}: {e}"
            )

        actual_port = sock.getsockname()[1]
        if actual_port != node.port:
            node.port = actual_port

        node.socket = sock
        node.thread = threading.Thread(
            target=self._radio_listen_loop,
            daemon=True,
            name=f"radio-listener-{node.host}:{node.port}",
        )
        node.thread.start()
        logger.info(f"Radio DAV listener started on {node.host}:{node.port}")

    def stop_radio(self) -> None:
        """停止电台 DAV UDP 监听器。"""
        if self._radio_node is None:
            return

        node = self._radio_node
        node.running = False

        if node.socket is not None:
            try:
                node.socket.close()
            except Exception:
                pass
            node.socket = None

        if node.thread is not None and node.thread.is_alive():
            node.thread.join(timeout=3.0)
            node.thread = None

        logger.info("Radio DAV listener stopped")

    def _radio_listen_loop(self) -> None:
        """后台线程：recvfrom 循环接收电台 DAV UDP 数据包。"""
        node = self._radio_node
        sock = node.socket
        bufsize = self.BUFSIZE
        parser = node.parser

        # 缓存 sockname，避免热循环中每包调用 getsockname()（系统调用）
        try:
            _cached_dst_ip, _cached_dst_port = sock.getsockname()
        except Exception:
            _cached_dst_ip, _cached_dst_port = ("0.0.0.0", node.port)

        while node.running:
            try:
                data, addr = sock.recvfrom(bufsize)
            except socket.timeout:
                continue
            except OSError:
                break

            if self._paused:
                continue

            node.packet_count += 1
            src_ip, src_port = addr
            dst_ip = self._resolve_listen_dst_ip(_cached_dst_ip, self._local_ips)
            dst_port = _cached_dst_port

            node_id = f"radio_{node.host}:{node.port}"
            try:
                if parser is not None and parser.is_configured:
                    record = parser.to_message_record(
                        data, src_ip, src_port, dst_ip, dst_port, node_id,
                    )
                else:
                    # 未配置解析器时，尝试裸帧解码（不生成 MessageRecord）
                    record = None

                if record is not None:
                    # 合并写入：一次锁完成 append + crc_fail 计数更新
                    self.model.append(record, is_crc_fail=(not record.crc_ok))
                    node.radio_count += 1
                    if self._on_record:
                        try:
                            self._on_record(record)
                        except Exception:
                            pass
                else:
                    # 非 DAV 帧或校验失败，不计为 radio_count
                    # 但如果 parser 解码返回了 None（非 DAV 数据），跳过
                    pass
            except Exception:
                node.error_count += 1
                self.model.mark_error()

    # ── 电台统计属性 ──
    @property
    def radio_packet_count(self) -> int:
        if self._radio_node is not None:
            return self._radio_node.packet_count
        return 0

    @property
    def radio_error_count(self) -> int:
        if self._radio_node is not None:
            return self._radio_node.error_count
        return 0

    @property
    def radio_count(self) -> int:
        if self._radio_node is not None:
            return self._radio_node.radio_count
        return 0

    @property
    def is_radio_running(self) -> bool:
        return self._radio_node is not None and self._radio_node.running

    @property
    def radio_host(self) -> str:
        if self._radio_node is not None:
            return self._radio_node.host
        return ""

    @property
    def radio_port(self) -> int:
        if self._radio_node is not None:
            return self._radio_node.port
        return 0

    # ═══════════════════════════════════════════════════════════
    # 地面站应用 TCP 监控（GCS ↔ 云平台 TCP/TLS 流量元数据）
    # ═══════════════════════════════════════════════════════════
    def set_gcs_app_listener(self, port: int = 443) -> None:
        """配置地面站应用监控的对端端口（云端 HTTPS，默认 443）。"""
        if self._gcs_app_node is None:
            self._gcs_app_node = GcsAppCaptureNode(port=port)
        else:
            self._gcs_app_node.port = int(port)

    def start_gcs_app(self) -> None:
        """启动地面站应用 TCP 监控（独立 sniffer，复用当前选中网卡）。"""
        if self._gcs_app_node is None:
            self._gcs_app_node = GcsAppCaptureNode()
        if self._gcs_app_node.running:
            return
        iface = self.active_interface_name
        if not iface:
            raise RuntimeError("请先在左侧选择网卡（地面站应用监控复用当前网卡）")
        try:
            from scapy.all import AsyncSniffer
        except ImportError:
            raise RuntimeError(
                "scapy 未安装，请执行: pip install scapy\n"
                "地面站应用 TCP 监控需要 scapy 库支持。"
            )
        self._cache_local_ips()
        node = self._gcs_app_node
        node.iface = iface
        node.running = True
        node.packet_count = 0
        node.error_count = 0
        node.app_count = 0
        node.sniffer = AsyncSniffer(
            iface=iface,
            filter=f"tcp port {node.port}",
            prn=self._gcs_sniff_callback,
            store=False,
        )
        node.sniffer.start()
        logger.info(f"GCS app TCP monitoring started on {iface} (port {node.port})")

    def stop_gcs_app(self) -> None:
        """停止地面站应用 TCP 监控。"""
        if self._gcs_app_node is None:
            return
        node = self._gcs_app_node
        node.running = False
        if node.sniffer is not None:
            try:
                node.sniffer.stop()
            except Exception:
                pass
            node.sniffer = None
        self._flush_batch()
        logger.info("GCS app TCP monitoring stopped")

    @property
    def is_gcs_app_running(self) -> bool:
        return self._gcs_app_node is not None and self._gcs_app_node.running

    @property
    def gcs_app_port(self) -> int:
        if self._gcs_app_node is not None:
            return self._gcs_app_node.port
        return 0

    @property
    def gcs_app_packet_count(self) -> int:
        if self._gcs_app_node is not None:
            return self._gcs_app_node.packet_count
        return 0

    @property
    def gcs_app_record_count(self) -> int:
        if self._gcs_app_node is not None:
            return self._gcs_app_node.app_count
        return 0

    @property
    def gcs_app_error_count(self) -> int:
        if self._gcs_app_node is not None:
            return self._gcs_app_node.error_count
        return 0

    # ── TCP 标志位 → 可读名称 ──
    _TCP_FLAG_NAMES = (
        (0x01, "FIN"), (0x02, "SYN"), (0x04, "RST"), (0x08, "PSH"),
        (0x10, "ACK"), (0x20, "URG"),
    )

    def _gcs_sniff_callback(self, packet) -> None:
        """scapy 每捕获一个匹配 TCP 包时调用（运行在 scapy 线程）。"""
        node = self._gcs_app_node
        if node is None or not node.running:
            return
        if self._paused:
            return
        node.packet_count += 1
        try:
            if not packet.haslayer("IP") or not packet.haslayer("TCP"):
                return
            ip_layer = packet[IP]
            tcp_layer = packet[TCP]
            payload = bytes(tcp_layer.payload)
            flags = int(tcp_layer.flags)

            # 降噪：纯 ACK（无载荷且无 SYN/FIN/RST）不记录
            if not payload and not (flags & 0x07):
                return

            record = self._build_gcs_record(
                ip_layer.src, tcp_layer.sport, ip_layer.dst, tcp_layer.dport,
                flags, payload, tcp_layer.seq, tcp_layer.window,
            )
            node.app_count += 1
            # 复用批量缓冲（与 NIC 路径一致，满/超时刷新）
            self._batch_buffer.append(record)
            if (len(self._batch_buffer) >= self._BATCH_SIZE
                    or time.time() - self._batch_last_flush > self._BATCH_MAX_AGE):
                self._flush_batch()
        except Exception:
            node.error_count += 1
            self.model.mark_error()

    def _build_gcs_record(self, src_ip: str, src_port: int, dst_ip: str,
                          dst_port: int, flags: int, payload: bytes,
                          tcp_seq: int, tcp_win: int) -> MessageRecord:
        """构造地面站应用 TCP 记录（密文不解，仅元数据 + 载荷 hex）。"""
        flag_names = ", ".join(name for bit, name in self._TCP_FLAG_NAMES
                               if flags & bit)
        # TLS record 判定：首字节 0x14-0x17（ChangeCipherSpec/Alert/Handshake/
        # ApplicationData）+ 版本高字节 0x03；或任一端为 443 视为 TLS
        is_tls = (len(payload) >= 2 and payload[0] in (0x14, 0x15, 0x16, 0x17)
                  and payload[1] == 0x03) or 443 in (src_port, dst_port)
        http_hint = ""
        if payload and not is_tls:
            head = payload[:32]
            for method in (b"GET ", b"POST ", b"PUT ", b"HEAD ",
                           b"DELETE", b"PATCH", b"OPTIO"):
                if head.startswith(method):
                    http_hint = payload.split(b"\r\n", 1)[0][:60].decode(
                        "latin-1", "replace")
                    break
            else:
                if b" HTTP/1." in head:
                    http_hint = payload.split(b"\r\n", 1)[0][:60].decode(
                        "latin-1", "replace")
        if is_tls:
            msg_name = "GCS_TLS"
        elif http_hint:
            msg_name = "GCS_HTTP"
        else:
            msg_name = "GCS_TCP"

        record = MessageRecord()
        record.src_ip = src_ip
        record.src_port = int(src_port)
        record.dst_ip = dst_ip
        record.dst_port = int(dst_port)
        record.direction = self._detect_direction(src_ip, dst_ip)
        record.msg_name = msg_name
        record.payload_len = len(payload)
        record.payload_bytes = payload[:4096]      # 密文截断保护
        record.node_id = "gcs_app"
        record.source_type = "gcs_app"
        record.fields_parsed = True                # 构造即完整，跳过 lazy parse
        record.fields = [
            FieldDetail(name="tcp_flags", value_raw=flags,
                        value_display=flag_names or "—",
                        raw_hex=f"0x{flags:02X}", type_name="uint8_t"),
            FieldDetail(name="payload_len", value_raw=len(payload),
                        value_display=f"{len(payload)} B",
                        raw_hex=f"{len(payload):X}", type_name="uint32_t"),
            FieldDetail(name="tcp_seq", value_raw=tcp_seq,
                        value_display=str(tcp_seq),
                        raw_hex=f"{tcp_seq:X}", type_name="uint32_t"),
            FieldDetail(name="tcp_win", value_raw=tcp_win,
                        value_display=str(tcp_win),
                        raw_hex=f"{tcp_win:X}", type_name="uint16_t"),
        ]
        if http_hint:
            record.fields.append(FieldDetail(
                name="http_first_line", value_raw=http_hint,
                value_display=http_hint, raw_hex="",
                type_name="char[]", is_array=True))
        return record

    # ═══════════════════════════════════════════════════════════
    # 方向检测
    # ═══════════════════════════════════════════════════════════
    def _cache_local_ips(self) -> None:
        """缓存本机所有 IP 地址，用于方向判定。"""
        ips: set[str] = set()
        try:
            hostname = socket.gethostname()
            _, _, addr_list = socket.gethostbyname_ex(hostname)
            for ip in addr_list:
                ips.add(ip)
        except Exception:
            pass
        # 始终包含 loopback
        ips.add("127.0.0.1")
        self._local_ips = ips

    @staticmethod
    def _resolve_listen_dst_ip(cached_dst_ip: str, local_ips: set[str]) -> str:
        """UDP 监听绑定 0.0.0.0/:: 时，用本机实际 IP 替代，避免记录 dst 恒为 0.0.0.0。

        仅对通配绑定地址做替换；若绑定具体 IP 则原样返回。
        """
        if cached_dst_ip not in ("0.0.0.0", "::"):
            return cached_dst_ip
        for ip in sorted(local_ips):
            if ip not in ("127.0.0.1", "0.0.0.0", "::1"):
                return ip
        return "127.0.0.1"

    def _detect_direction(self, src_ip: str, dst_ip: str) -> str:
        """根据 IP 判定消息方向。

        规则：
        - 如果 src_ip 是本机 IP → "Tx"（本机正在发送）
        - 如果 dst_ip 是本机 IP → "Rx"（本机正在接收）
        - 如果 src_ip 是广播/组播 → "Rx"
        - 默认 → "Rx"
        """
        if src_ip in self._local_ips:
            return "Tx"
        # dst_ip 匹配本机 → 外部发给本机
        if dst_ip in self._local_ips:
            return "Rx"
        # 广播/组播 → 视为接收
        if src_ip == "255.255.255.255" or src_ip.startswith("224."):
            return "Rx"
        return "Rx"

    # ═══════════════════════════════════════════════════════════
    # 嗅探回调（运行在 scapy 线程中）
    # ═══════════════════════════════════════════════════════════
    def _sniff_callback(self, packet) -> None:
        """scapy 每捕获一个 UDP 包时调用。"""
        if not self._interface_node or not self._interface_node.running:
            return
        if self._paused:
            return

        iface_node = self._interface_node
        iface_node.packet_count += 1

        try:
            if not packet.haslayer("IP") or not packet.haslayer("UDP"):
                return

            ip_layer = packet[IP]
            udp_layer = packet[UDP]
            raw_data = bytes(udp_layer.payload)

            node_id = f"nic_{iface_node.interface_name}"
            success = self._process_raw_packet(
                raw_data, ip_layer.src, udp_layer.sport,
                ip_layer.dst, udp_layer.dport,
                node_id, "nic",
            )
            if success:
                iface_node.mavlink_count += 1
            else:
                iface_node.error_count += 1
        except Exception:
            iface_node.error_count += 1
            self.model.mark_error()

    # ═══════════════════════════════════════════════════════════
    # 批量缓冲刷新
    # ═══════════════════════════════════════════════════════════
    def _flush_batch(self) -> None:
        """将批量缓冲区中的记录一次性写入 model（线程安全）。"""
        if not self._batch_buffer:
            return
        batch = self._batch_buffer
        self._batch_buffer = []
        self.model.append_batch(batch)
        self._batch_last_flush = time.time()

        # 回调通知（批量）
        if self._on_record:
            for record in batch:
                try:
                    self._on_record(record)
                except Exception:
                    pass

    # ═══════════════════════════════════════════════════════════
    # 共享数据包处理（NIC + UDP 共用）
    # ═══════════════════════════════════════════════════════════
    def _process_raw_packet(
        self, raw_data: bytes, src_ip: str, src_port: int,
        dst_ip: str, dst_port: int, node_id: str, source_type: str,
    ) -> bool:
        """共享的数据包处理逻辑：魔数检测 → 解析 → 写入 Model。

        优化：使用批量缓冲区，累积 _BATCH_SIZE 条后一次性写入 model，
        将锁获取从 5000次/s 降至 ~78次/s。

        Returns:
            True 表示成功解析并写入，False 表示非 MAVLink 数据或解析失败。
        """
        if not raw_data or len(raw_data) < 6:
            return False

        # ── 魔数检测：同时支持标准格式和 ip_prefixed 格式 ──
        if raw_data[0] not in (0xFE, 0xFD):
            if self._nest_enabled and len(raw_data) > 4 and raw_data[4] in (0xFE, 0xFD):
                pass  # ip_prefixed，继续解析
            else:
                return False  # 非 MAVLink，静默丢弃

        src_addr = (src_ip, src_port)
        dst_addr = (dst_ip, dst_port)
        direction = self._detect_direction(src_ip, dst_ip)

        record = self.parser.parse_header(raw_data, src_addr, dst_addr,
                                           direction=direction)
        if record is None:
            self.model.mark_error()
            return False

        record.node_id = node_id
        record.source_type = source_type

        # ── 批量缓冲写入 ──
        self._batch_buffer.append(record)
        if len(self._batch_buffer) >= self._BATCH_SIZE:
            self._flush_batch()
        elif (self._batch_last_flush > 0 and
              time.time() - self._batch_last_flush > self._BATCH_MAX_AGE):
            self._flush_batch()

        return True
