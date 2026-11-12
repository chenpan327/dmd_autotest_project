"""
UDP Radio Protocol — 基于 UDP 网口的 DAV 电台通信协议。

对 ``BaseRadioProtocol`` 的 UDP 传输实现，提供与 ``RadioSerialProtocol``
相同的上层 API，但通过网口（UDP socket）而非串口进行通信。

**与串口的区别：** 串口可以直接发送心跳查询，UDP 需要先完成上线（ENROLL）握手：
Radio 发送 ``ENROLL_REQUEST`` → PC 回复 ``ENROLL_REPLY`` → 设备上线。
掉线后 Radio 会重新发送 ``ENROLL_REQUEST``，PC 需要再次回复才能上线。

Usage::

    from src.Protocol.radio.radio_udp_protocol import RadioUdpProtocol

    udp = RadioUdpProtocol()
    udp.connect("172.20.0.76", 14555, local_port=14555)

    ver = udp.query_firmware_version()          # → "1.0.1.0"
    hb  = udp.query_heartbeat()                 # → {...}
    udp.disconnect()
"""

from __future__ import annotations

import socket
import time
from typing import Any, Callable, Dict, Optional, Tuple

from .dav_protocol import DavProtocol, AddressRole
from .radio_serial_protocol import (
    BaseRadioProtocol,
    ConnectionError,
)


class RadioUdpProtocol(BaseRadioProtocol):
    """DAV 电台设备通信协议（UDP 网口实现）。

    封装 UDP socket 连接、上线（ENROLL）握手、请求-响应模式、
    固件版本/加密密钥/心跳查询。

    Parameters
    ----------
    xml_path : str or None
        ``MessageDefineUAV.xml`` 路径。
    pb2_path : str or None
        ``_pb2.py`` 模块路径。
    on_dispatch : callable or None
        可选的外部帧分发回调 ``on_dispatch(header: dict, payload: bytes)``。
    on_device_ready : callable or None
        设备上线时的回调 ``on_device_ready(address: int)``。
    on_enroll_request : callable or None
        收到 ENROLL_REQUEST 时的回调 ``on_enroll_request(header: dict, payload: bytes)``，
        可用于日志/调试。在 ENROLL_REPLY 发送前调用。
    """

    def __init__(
        self,
        xml_path: Optional[str] = None,
        pb2_path: Optional[str] = None,
        on_dispatch: Optional[Callable[[Dict[str, Any], bytes], None]] = None,
        on_device_ready: Optional[Callable[[int], None]] = None,
        on_enroll_request: Optional[Callable[[Dict[str, Any], bytes], None]] = None,
    ) -> None:
        super().__init__(
            xml_path=xml_path,
            pb2_path=pb2_path,
            on_dispatch=on_dispatch,
            on_device_ready=on_device_ready,
            send_callback=self._udp_send,
        )

        # UDP socket
        self._sock: Optional[socket.socket] = None
        self._remote_addr: Tuple[str, int] = ("", 0)
        self._local_port: int = 0
        self._socket_bound: bool = False

        # 上线（ENROLL）状态
        self._enrolled: bool = False
        self._on_enroll_request = on_enroll_request

        # 添加 UDP 特有的命令
        enroll_req_id = self._dp.name_to_cmd_id("ENROLL_REQUEST")
        enroll_reply_id = self._dp.name_to_cmd_id("ENROLL_REPLY")
        if enroll_req_id is not None:
            self._CMD["ENROLL_REQUEST"] = enroll_req_id
        if enroll_reply_id is not None:
            self._CMD["ENROLL_REPLY"] = enroll_reply_id

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._socket_bound

    @property
    def is_enrolled(self) -> bool:
        """设备是否已上线（已完成 ENROLL 握手）。"""
        return self._enrolled

    @property
    def remote_addr(self) -> Tuple[str, int]:
        """返回当前连接的远端地址 (host, port)。"""
        return self._remote_addr

    @property
    def local_port(self) -> int:
        """返回本地绑定的端口号。"""
        if self._sock:
            try:
                return self._sock.getsockname()[1]
            except OSError:
                pass
        return self._local_port

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(
        self,
        remote_host: str,
        remote_port: int,
        local_port: int = 0,
        timeout: float = 5.0,
    ) -> None:
        """创建 UDP socket，启动接收线程，等待 Radio 上线。

        与串口不同，UDP 连接时不会主动发送广播查询，而是等待 Radio
        发送 ``ENROLL_REQUEST`` (0x000C)，PC 自动回复 ``ENROLL_REPLY``
        (0x000D) 后完成上线。

        Args:
            remote_host: 远端设备 IP 地址。
            remote_port: 远端设备端口号。
            local_port: 本地绑定端口（0=自动分配）。
            timeout: 等待上线的超时秒数。

        Raises:
            ConnectionError: socket 创建失败或上线超时。
        """
        if self._socket_bound:
            return

        self._remote_addr = (remote_host, remote_port)
        self._local_port = local_port

        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(0.001)
            self._sock.bind(("0.0.0.0", local_port))
        except OSError as e:
            self._sock = None
            raise ConnectionError(f"无法创建 UDP socket: {e}") from e

        self._socket_bound = True
        self._device_address = 0
        self._address_resolved = False
        self._enrolled = False

        self._dav.set_send_callback(self._udp_send)
        self._start_recv_thread()

        self._discover_device(timeout)

    def disconnect(self) -> None:
        """关闭 UDP socket，停止接收线程。"""
        self._thread_exit = True

        self._join_recv_thread()

        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

        self._socket_bound = False
        self._enrolled = False
        self._device_address = 0
        self._address_resolved = False

    # ------------------------------------------------------------------
    # Internals — ensure ready
    # ------------------------------------------------------------------

    def _ensure_ready(self) -> None:
        if not self._socket_bound or self._sock is None:
            raise ConnectionError("UDP socket 未打开")
        if not self._enrolled:
            raise ConnectionError("设备未上线（未收到 ENROLL_REQUEST）")

    # ------------------------------------------------------------------
    # Internals — UDP send
    # ------------------------------------------------------------------

    def _udp_send(self, data: bytes) -> None:
        if self._sock and self._socket_bound:
            try:
                self._sock.sendto(data, self._remote_addr)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Internals — receive loop
    # ------------------------------------------------------------------

    def _recv_loop(self) -> None:
        while not self._thread_exit:
            if self._sock:
                try:
                    data, _addr = self._sock.recvfrom(4096)
                    if data:
                        for header, payload in self._dav.feed(data):
                            self._dispatch(header, payload)
                except socket.timeout:
                    pass
                except OSError:
                    pass
            time.sleep(0.001)

    # ------------------------------------------------------------------
    # Internals — enrollment handling
    # ------------------------------------------------------------------

    def _handle_cmd(self, header: Dict[str, Any], payload: bytes) -> None:
        """拦截 ENROLL_REQUEST 以完成上线握手。"""
        cmd = header.get("cmd", 0)
        if cmd == self._CMD.get("ENROLL_REQUEST"):
            self._handle_enroll_request(header, payload)
        super()._handle_cmd(header, payload)

    def _handle_enroll_request(
        self, header: Dict[str, Any], payload: bytes
    ) -> None:
        """处理 Radio 的上线请求，回复 ENROLL_REPLY。"""
        sender = header.get("sender_address", 0) & DavProtocol.ADDRESS_MASK

        # 解析/更新设备地址
        if sender != 0:
            was_resolved = self._address_resolved
            if sender & (0xF << 48):
                self._device_address = sender
            else:
                self._device_address = sender | (AddressRole.RADIO_RC_RECEIVER << 48)
            self._address_resolved = True
            if not was_resolved and self._on_device_ready:
                try:
                    self._on_device_ready(self._device_address)
                except Exception:
                    pass

        # 外部回调（日志/调试）
        if self._on_enroll_request:
            try:
                self._on_enroll_request(header, payload)
            except Exception:
                pass

        # 下发注册结果 (accept_status: 0=accepted 允许上线)
        enroll_reply = self._dp.encode(
            cmd_id=self._CMD["ENROLL_REPLY"],
            accept_status=0,
            heartbeat_interval_ms=1000,
        )
        self._dav.send(
            receiver=self._device_address,
            cmd=self._CMD["ENROLL_REPLY"],
            data=enroll_reply,
        )
        self._enrolled = True

    # ------------------------------------------------------------------
    # Internals — device discovery (wait for enrollment)
    # ------------------------------------------------------------------

    def _discover_device(self, timeout: float) -> bool:
        """等待 Radio 发送 ENROLL_REQUEST 完成上线。

        与串口不同，UDP 不主动广播查询，而是被动等待 Radio 的上线请求。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._enrolled and self._address_resolved:
                return True
            time.sleep(0.1)

        self.disconnect()
        raise ConnectionError(
            f"设备上线超时（{timeout:.0f}s）— 未收到 ENROLL_REQUEST"
        )
