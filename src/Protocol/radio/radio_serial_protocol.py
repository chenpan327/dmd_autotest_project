"""
Radio Test Protocol — DAV 电台/接收机通信基类。

提供 ``BaseRadioProtocol``（传输无关的 DAV 协议逻辑）和
``RadioSerialProtocol``（串口实现），供 ``radio_config.py``（脚本 API）和
``radio_config_tool.py``（GUI）共用。

Usage::

    from src.Protocol.radio.radio_serial_protocol import RadioSerialProtocol

    rtp = RadioSerialProtocol()
    rtp.connect("COM3", 460800)

    ver = rtp.query_firmware_version()           # → "1.0.1.0"
    key = rtp.get_encrypt_key()                  # → {"encrypt_type": 0}
    rtp.set_encrypt_key(1, key_bytes, iv_bytes)

    rtp.disconnect()
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import serial
import serial.tools.list_ports

from .dav_protocol import DavProtocol, AddressRole, MessageType, EncryptType
from .dav_payload import DavPayload

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

_RADIO_ROOT = os.path.dirname(os.path.abspath(__file__))

_DEFAULT_XML_PATH = os.path.join(_RADIO_ROOT, "MessageDefineUAV.xml")
_DEFAULT_PB2_PATH = os.path.join(_RADIO_ROOT, "MessageDefineUAVC_pb2.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _version_int_to_str(ver: int) -> str:
    return f"{(ver >> 24) & 0xFF}.{(ver >> 16) & 0xFF}.{(ver >> 8) & 0xFF}.{ver & 0xFF}"


def list_serial_ports() -> List[Tuple[str, str]]:
    """列出可用串口。返回 [(device, description), ...]."""
    return [(p.device, p.description) for p in serial.tools.list_ports.comports()]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RadioProtoError(Exception):
    pass


class ConnectionError(RadioProtoError):
    pass


class TimeoutError(RadioProtoError):
    pass


# ===================================================================
# BaseRadioProtocol  —  transport-agnostic DAV protocol logic
# ===================================================================


class BaseRadioProtocol:
    """DAV 电台设备通信协议基类（传输无关）。

    子类需实现：
        - ``is_connected`` (property)
        - ``_ensure_ready()``
        - ``_recv_loop()``
        - ``connect(...)`` / ``disconnect()``

    并通过 ``send_callback`` 参数将传输层的发送函数注入 ``DavProtocol``。
    """

    DEFAULT_SELF_ADDRESS: int = 4503599627370494  # 0xFFF_FFFF_FFFF_FE

    # 请求参数
    REQ_RETRIES: int = 3
    RETRY_INTERVAL: float = 0.3
    DEFAULT_TIMEOUT: float = 3.0
    DISCOVER_RETRIES: int = 3

    def __init__(
        self,
        xml_path: Optional[str] = None,
        pb2_path: Optional[str] = None,
        on_dispatch: Optional[Callable[[Dict[str, Any], bytes], None]] = None,
        on_device_ready: Optional[Callable[[int], None]] = None,
        send_callback: Optional[Callable[[bytes], None]] = None,
    ) -> None:
        self._xml_path = xml_path or _DEFAULT_XML_PATH
        self._pb2_path = pb2_path or _DEFAULT_PB2_PATH

        # 协议层
        self._dav = DavProtocol(
            local_address=self.DEFAULT_SELF_ADDRESS,
            send_callback=send_callback,
        )
        self._dp = DavPayload(xml_path=self._xml_path, pb2_path=self._pb2_path)

        # 命令查找表
        self._CMD = self._build_cmd_lookup()

        # 设备地址
        self._device_address: int = 0
        self._address_resolved: bool = False

        # 回调
        self._on_dispatch = on_dispatch
        self._on_device_ready = on_device_ready

        # 线程
        self._thread_exit: bool = False
        self._recv_thread: Optional[threading.Thread] = None

        # 请求-响应同步
        self._response_event = threading.Event()
        self._response_data: Optional[bytes] = None
        self._response_cmd: int = 0
        self._ack_event = threading.Event()
        self._ack_value: int = 0

    # ------------------------------------------------------------------
    # Command ID lookup
    # ------------------------------------------------------------------

    def _build_cmd_lookup(self) -> Dict[str, int]:
        names = [
            "GET_FIRMWARE_VERSION",
            "ASK_DAV_ADDRESS",
            "SEND_DAV_ADDRESS",
            "ASK_RADIO_ENCRYPT_KEY",
            "SEND_RADIO_ENCRYPT_KEY",
            "SET_RADIO_ENCRYPT_KEY",
            "ASK_HEARTBEAT",
            "SEND_RADIO_R2_HEARTBEAT",
            "SET_RADIO_BUTTON_PARAM",
        ]
        lookup: Dict[str, int] = {}
        for name in names:
            cid = self._dp.name_to_cmd_id(name)
            if cid is not None:
                lookup[name] = cid
        return lookup

    def cmd_id(self, name: str) -> int:
        """返回命令名称对应的 cmdID。"""
        return self._CMD[name]

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def device_address(self) -> int:
        return self._device_address

    @property
    def address_resolved(self) -> bool:
        return self._address_resolved

    @property
    def dav(self) -> DavProtocol:
        """暴露 DavProtocol 实例（供高级用法）。"""
        return self._dav

    @property
    def payload(self) -> DavPayload:
        """暴露 DavPayload 实例（供高级用法）。"""
        return self._dp

    # ------------------------------------------------------------------
    # Thread management (shared)
    # ------------------------------------------------------------------

    def _start_recv_thread(self) -> None:
        self._thread_exit = False
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def _join_recv_thread(self, timeout: float = 2.0) -> None:
        if self._recv_thread and self._recv_thread.is_alive():
            self._recv_thread.join(timeout=timeout)
        self._recv_thread = None

    # ------------------------------------------------------------------
    # High-level queries
    # ------------------------------------------------------------------

    def query_firmware_version(self, timeout: float = DEFAULT_TIMEOUT) -> str:
        """查询固件版本。返回 ``"1.0.1.0"`` 格式字符串。"""
        self._ensure_ready()

        payload = self._dp.encode(
            cmd_id=self._CMD["GET_FIRMWARE_VERSION"],
            command=2,  # DAV_COMMAND_ACK_APP_VERSION
        )
        ack = self._request_with_ack(
            cmd=self._CMD["GET_FIRMWARE_VERSION"],
            payload=payload,
            timeout=timeout,
        )
        return _version_int_to_str(ack)

    def get_encrypt_key(self, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """查询电台加密密钥。

        Returns:
            dict: ``{"encrypt_type": 0}`` 或 ``{"encrypt_type": 1, "encrypt_key": "ABCD...", "encrypt_iv": "EF01..."}``.
        """
        self._ensure_ready()

        payload = self._dp.encode(
            cmd_id=self._CMD["ASK_RADIO_ENCRYPT_KEY"],
            command=38,  # DAV_COMMAND_ASK_RADIO_ENCRYPT_KEY
        )
        data = self._request_with_response(
            ask_cmd=self._CMD["ASK_RADIO_ENCRYPT_KEY"],
            ask_payload=payload,
            response_cmd=self._CMD["SEND_RADIO_ENCRYPT_KEY"],
            timeout=timeout,
        )
        msg = self._dp.decode(cmd_id=self._CMD["SEND_RADIO_ENCRYPT_KEY"], data=data)
        d = self._dp.to_dict(msg)

        radio_key = d.get("radio_key", {})
        etype = radio_key.get("encrypt_type", 0)
        result: Dict[str, Any] = {"encrypt_type": etype}
        if etype != 0:
            result["encrypt_key"] = (
                bytes(radio_key.get("encrypt_key", b"")).hex().upper()
            )
            result["encrypt_iv"] = (
                bytes(radio_key.get("encrypt_iv", b"")).hex().upper()
            )
        return result

    def set_encrypt_key(
        self,
        encrypt_type: int,
        encrypt_key: bytes = b"",
        encrypt_iv: bytes = b"",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """设置设备加密密钥。

        Args:
            encrypt_type: 0=无加密, 1=AES128, 2=AES256.
            encrypt_key: 密钥。
            encrypt_iv: 初始化向量。
        """
        self._ensure_ready()

        payload = self._dp.encode(
            cmd_id=self._CMD["SET_RADIO_ENCRYPT_KEY"],
            radio_key={
                "encrypt_type": encrypt_type,
                "encrypt_key": encrypt_key if encrypt_type != 0 else b"",
                "encrypt_iv": encrypt_iv if encrypt_type != 0 else b"",
            },
        )
        self._request_with_ack(
            cmd=self._CMD["SET_RADIO_ENCRYPT_KEY"],
            payload=payload,
            timeout=timeout,
        )

    def query_heartbeat(self, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """查询设备心跳包（R2 电台）。

        发送 ``ASK_HEARTBEAT`` (0x000E)，设备回复 ``SEND_RADIO_R2_HEARTBEAT`` (0x0204)。
        返回 ``radioStationR2Heart`` 结构体的 dict。

        Returns:
            dict: 包含 device_type, firmware_running_status, firmware_version_alias,
            firmware_version, protobuf_version, local_ms_time, radio_station_r2 (子结构体)。
            radio_station_r2 包含 device_id, error_report, ethernet_ip, battery_percentage,
            poe_voltage_mv, charge_temperature, gps_utc_time, radioGroupPosition,
            radio_rf_param, button_param, encrypt_type, translate_data_left_bytes 等字段。
        """
        self._ensure_ready()

        payload = self._dp.encode(
            cmd_id=self._CMD["ASK_HEARTBEAT"],
            command=23,  # DAV_COMMAND_ACK_HEARTBEAT
        )
        data = self._request_with_response(
            ask_cmd=self._CMD["ASK_HEARTBEAT"],
            ask_payload=payload,
            response_cmd=self._CMD["SEND_RADIO_R2_HEARTBEAT"],
            timeout=timeout,
        )
        msg = self._dp.decode(
            cmd_id=self._CMD["SEND_RADIO_R2_HEARTBEAT"], data=data
        )
        return self._dp.to_dict(msg)

    def set_button_param(
        self,
        long_click_time: Optional[List[int]] = None,
        long_click_mode: Optional[List[int]] = None,
        short_click_mode: Optional[List[int]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """设置电台自定义按键功能。

        Args:
            long_click_time: 长按时间阈值列表 (ms)。大于该时间为长按，小于为短按。
            long_click_mode: 长按功能列表。0=保留, 1=返航, 2=降落, 3=急停, 4=自定义。
            short_click_mode: 短按功能列表。
            timeout: 超时秒数。
        """
        self._ensure_ready()

        fields: Dict[str, Any] = {}
        if long_click_time is not None:
            fields["long_click_time"] = long_click_time
        if long_click_mode is not None:
            fields["long_click_button_mode"] = long_click_mode
        if short_click_mode is not None:
            fields["short_click_button_mode"] = short_click_mode

        payload = self._dp.encode(
            cmd_id=self._CMD["SET_RADIO_BUTTON_PARAM"], **fields
        )
        self._request_with_ack(
            cmd=self._CMD["SET_RADIO_BUTTON_PARAM"],
            payload=payload,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Async send (for GUI use — no blocking wait)
    # ------------------------------------------------------------------

    def send_async(
        self,
        cmd: int,
        payload: bytes,
        *,
        ack_count: int = 0,
        broadcast_type: int = 0,
    ) -> None:
        """发送一帧（不等待响应）。响应通过 ``on_dispatch`` 回调处理。

        Args:
            cmd: 命令 ID。
            payload: protobuf 编码后的数据。
            ack_count: ACK 序号（0=不需要 ACK）。
            broadcast_type: 广播类型掩码。
        """
        receiver = 0 if broadcast_type else self._device_address
        self._dav.send(
            receiver=receiver,
            cmd=cmd,
            data=payload,
            ack_count=ack_count,
            broadcast_type=broadcast_type,
        )

    def send_async_by_name(
        self,
        msg_name: str,
        payload: bytes,
        *,
        ack_count: int = 0,
        broadcast_type: int = 0,
    ) -> None:
        """按消息名称发送一帧。"""
        self.send_async(
            cmd=self._CMD[msg_name],
            payload=payload,
            ack_count=ack_count,
            broadcast_type=broadcast_type,
        )

    # ------------------------------------------------------------------
    # Low-level request-response (public, for extending)
    # ------------------------------------------------------------------

    def request_with_ack(
        self, cmd: int, payload: bytes, timeout: float = DEFAULT_TIMEOUT
    ) -> int:
        """发送带 ACK 的请求，阻塞等待 ACK，返回 report 值。"""
        self._ensure_ready()
        return self._request_with_ack(cmd, payload, timeout)

    def request_with_response(
        self,
        ask_cmd: int,
        ask_payload: bytes,
        response_cmd: int,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> bytes:
        """发送请求，阻塞等待匹配的响应帧，返回 payload 字节。"""
        self._ensure_ready()
        return self._request_with_response(ask_cmd, ask_payload, response_cmd, timeout)

    # ------------------------------------------------------------------
    # Device discovery (public, can be re-triggered)
    # ------------------------------------------------------------------

    def discover_device(self, timeout: float = 5.0) -> bool:
        """主动发起设备发现。返回 True 表示成功。"""
        return self._discover_device(timeout)

    # ------------------------------------------------------------------
    # Feed raw bytes (public, for external receive loops)
    # ------------------------------------------------------------------

    def feed(self, raw_bytes: bytes) -> List[Tuple[Dict[str, Any], bytes]]:
        """喂入原始字节，返回解码后的 (header, payload) 列表。"""
        return list(self._dav.feed(raw_bytes))

    # ------------------------------------------------------------------
    # Internals — ensure ready
    # ------------------------------------------------------------------

    def _ensure_ready(self) -> None:
        raise NotImplementedError("subclass must implement _ensure_ready")

    # ------------------------------------------------------------------
    # Internals — receive loop (subclass must implement)
    # ------------------------------------------------------------------

    def _recv_loop(self) -> None:
        raise NotImplementedError("subclass must implement _recv_loop")

    # ------------------------------------------------------------------
    # Internals — request-response
    # ------------------------------------------------------------------

    def _request_with_ack(
        self, cmd: int, payload: bytes, timeout: float
    ) -> int:
        last_error: Optional[Exception] = None
        for attempt in range(self.REQ_RETRIES):
            self._ack_event.clear()
            self._ack_value = 0

            self._dav.send(
                receiver=self._device_address,
                cmd=cmd,
                data=payload,
                ack_count=(attempt + 1) & 0x3F or 1,
            )
            if self._ack_event.wait(timeout):
                return self._ack_value

            last_error = TimeoutError(
                f"ACK 超时 (cmd=0x{cmd:04X}, attempt={attempt + 1})"
            )
            time.sleep(self.RETRY_INTERVAL)

        raise last_error  # type: ignore[misc]

    def _request_with_response(
        self,
        ask_cmd: int,
        ask_payload: bytes,
        response_cmd: int,
        timeout: float,
    ) -> bytes:
        self._response_event.clear()
        self._response_data = None
        self._response_cmd = response_cmd

        for _ in range(self.REQ_RETRIES):
            self._dav.send(
                receiver=self._device_address,
                cmd=ask_cmd,
                data=ask_payload,
            )
            if self._response_event.wait(timeout):
                assert self._response_data is not None
                return self._response_data
            time.sleep(self.RETRY_INTERVAL)

        raise TimeoutError(
            f"响应超时 (ask=0x{ask_cmd:04X}, expect=0x{response_cmd:04X})"
        )

    # ------------------------------------------------------------------
    # Internals — device discovery
    # ------------------------------------------------------------------

    def _discover_device(self, timeout: float) -> bool:
        payload = self._dp.encode(
            cmd_id=self._CMD["GET_FIRMWARE_VERSION"],
            command=2,
        )

        deadline = time.monotonic() + timeout
        for _ in range(self.DISCOVER_RETRIES):
            if time.monotonic() > deadline:
                break

            self._ack_event.clear()
            self._dav.send(
                receiver=0,
                cmd=self._CMD["GET_FIRMWARE_VERSION"],
                data=payload,
                broadcast_type=0x2FFFF,
                ack_count=1,
            )

            if self._ack_event.wait(
                timeout=min(2.0, max(0.1, deadline - time.monotonic()))
            ):
                if self._address_resolved:
                    return True
            time.sleep(self.RETRY_INTERVAL)

        self.disconnect()
        raise ConnectionError("设备发现超时 — 无设备响应")

    # ------------------------------------------------------------------
    # Internals — dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, header: Dict[str, Any], payload: bytes) -> None:
        msg_type = header.get("message_type", 0)
        if msg_type == MessageType.ACK:
            self._handle_ack(header, payload)
        elif msg_type == MessageType.CMD:
            self._handle_cmd(header, payload)

        # 外部回调
        if self._on_dispatch:
            try:
                self._on_dispatch(header, payload)
            except Exception:
                pass

    def _handle_ack(self, header: Dict[str, Any], payload: bytes) -> None:
        sender = header.get("sender_address", 0) & DavProtocol.ADDRESS_MASK

        # 设备发现
        if not self._address_resolved and sender != 0:
            if sender & (0xF << 48):
                self._device_address = sender
            else:
                self._device_address = sender | (AddressRole.RADIO_RC_RECEIVER << 48)
            self._address_resolved = True
            if self._on_device_ready:
                try:
                    self._on_device_ready(self._device_address)
                except Exception:
                    pass

        ack_value = 0
        if len(payload) >= 4:
            ack_value = int.from_bytes(payload[:4], "little")

        self._ack_value = ack_value
        self._ack_event.set()

    def _handle_cmd(self, header: Dict[str, Any], payload: bytes) -> None:
        cmd = header.get("cmd", 0)

        # SEND_DAV_ADDRESS 也可用于设备发现
        cmd_send_addr = self._CMD.get("SEND_DAV_ADDRESS")
        if cmd_send_addr is not None and cmd == cmd_send_addr and not self._address_resolved:
            sender = header.get("sender_address", 0) & DavProtocol.ADDRESS_MASK
            if sender != 0:
                if sender & (0xF << 48):
                    self._device_address = sender
                else:
                    self._device_address = sender | (AddressRole.RADIO_RC_RECEIVER << 48)
                self._address_resolved = True
                if self._on_device_ready:
                    try:
                        self._on_device_ready(self._device_address)
                    except Exception:
                        pass

        # 匹配等待中的响应
        if cmd == self._response_cmd and self._response_cmd != 0:
            self._response_data = payload
            self._response_event.set()


# ===================================================================
# RadioSerialProtocol  —  serial transport
# ===================================================================


class RadioSerialProtocol(BaseRadioProtocol):
    """DAV 电台设备通信协议（串口实现）。

    封装串口连接、设备发现、请求-响应模式、固件版本/加密密钥查询。

    Parameters
    ----------
    xml_path : str or None
        ``MessageDefineUAV.xml`` 路径。
    pb2_path : str or None
        ``_pb2.py`` 模块路径。
    on_dispatch : callable or None
        可选的外部帧分发回调 ``on_dispatch(header: dict, payload: bytes)``。
        收到每一帧（ACK 或 CMD）时调用，在接收线程中执行。
    on_device_ready : callable or None
        设备地址解析完成时的回调 ``on_device_ready(address: int)``。
    on_port_list_change : callable or None
        串口列表变化时的回调 ``on_port_list_change(ports: [(device, desc), ...])``。
    """

    def __init__(
        self,
        xml_path: Optional[str] = None,
        pb2_path: Optional[str] = None,
        on_dispatch: Optional[Callable[[Dict[str, Any], bytes], None]] = None,
        on_device_ready: Optional[Callable[[int], None]] = None,
        on_port_list_change: Optional[Callable[[List[Tuple[str, str]]], None]] = None,
    ) -> None:
        super().__init__(
            xml_path=xml_path,
            pb2_path=pb2_path,
            on_dispatch=on_dispatch,
            on_device_ready=on_device_ready,
            send_callback=self._serial_write,
        )

        # 串口
        self._serial: Optional[serial.Serial] = None
        self._com_state: int = 0  # 0=closed, 1=open

        # 串口列表回调
        self._on_port_list_change = on_port_list_change
        self._port_list_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._com_state == 1

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self, port: str, baud: int = 460800, timeout: float = 5.0) -> None:
        """打开串口，启动接收线程，发现设备。

        Args:
            port: 串口名或数字索引。
            baud: 波特率。
            timeout: 设备发现超时秒数。

        Raises:
            ConnectionError: 串口打开失败或设备发现超时。
        """
        if self._com_state == 1:
            return

        device = self._resolve_port(port)
        try:
            self._serial = serial.Serial(port=device, baudrate=baud, timeout=0.001)
        except serial.SerialException as e:
            raise ConnectionError(f"无法打开串口 {port}: {e}") from e

        self._com_state = 1
        self._device_address = 0
        self._address_resolved = False

        # 启动线程
        self._start_recv_thread()
        self._thread_exit = False
        self._port_list_thread = threading.Thread(
            target=self._port_list_loop, daemon=True
        )
        self._port_list_thread.start()

        # 发现设备
        self._discover_device(timeout)

    def disconnect(self) -> None:
        """关闭串口，停止所有线程。"""
        self._thread_exit = True

        for thr in [self._recv_thread, self._port_list_thread]:
            if thr and thr.is_alive():
                thr.join(timeout=2.0)

        self._recv_thread = None
        self._port_list_thread = None

        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

        self._com_state = 0
        self._device_address = 0
        self._address_resolved = False

    # ------------------------------------------------------------------
    # Internals — ensure ready
    # ------------------------------------------------------------------

    def _ensure_ready(self) -> None:
        if self._com_state != 1:
            raise ConnectionError("串口未打开")
        if not self._address_resolved:
            raise ConnectionError("设备地址未解析")

    # ------------------------------------------------------------------
    # Internals — serial
    # ------------------------------------------------------------------

    def _serial_write(self, data: bytes) -> None:
        if self._serial and self._serial.is_open:
            try:
                self._serial.write(data)
            except serial.SerialException:
                pass

    @staticmethod
    def _resolve_port(port: str) -> str:
        try:
            idx = int(port)
            ports = list(serial.tools.list_ports.comports())
            if 0 <= idx < len(ports):
                return ports[idx].device
        except ValueError:
            pass

        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            if p.device.upper() == port.upper():
                return p.device
        for p in ports:
            if port.upper() in p.device.upper():
                return p.device
        for p in ports:
            if port.upper() in (p.description or "").upper():
                return p.device

        available = [(p.device, p.description) for p in ports]
        raise ConnectionError(f"找不到串口 '{port}'。可用: {available}")

    # ------------------------------------------------------------------
    # Internals — receive loop
    # ------------------------------------------------------------------

    def _recv_loop(self) -> None:
        while not self._thread_exit:
            if self._serial and self._serial.is_open:
                try:
                    chunk = self._serial.read(4096)
                    if chunk:
                        for header, payload in self._dav.feed(chunk):
                            self._dispatch(header, payload)
                except serial.SerialException:
                    pass
            time.sleep(0.001)

    # ------------------------------------------------------------------
    # Internals — port list polling
    # ------------------------------------------------------------------

    def _port_list_loop(self) -> None:
        last_ports: List[Tuple[str, str]] = []
        while not self._thread_exit:
            try:
                current = list_serial_ports()
                current_sorted = sorted(current, key=lambda x: x[0])
                if current_sorted != last_ports:
                    last_ports = current_sorted
                    if self._on_port_list_change:
                        try:
                            self._on_port_list_change(current_sorted)
                        except Exception:
                            pass
            except Exception:
                pass
            time.sleep(1.0)
