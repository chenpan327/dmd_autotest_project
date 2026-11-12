"""
Radio configuration library — 基于 ``RadioSerialProtocol`` / ``RadioUdpProtocol`` 的同步 API。

Usage (serial)::

    with RadioConfig() as rc:
        rc.connect("COM3", 460800)
        print(rc.get_firmware_version())       # → "1.0.1.0"
        print(rc.get_radio_encrypt_key())      # → {"encrypt_type": 0}
        rc.set_radio_encrypt_key(encrypt_type=1, encrypt_key=b'...', encrypt_iv=b'...')

Usage (UDP)::

    with RadioConfigUdp() as rc:
        rc.connect("172.20.0.76", 14555, local_port=14555)
        print(rc.get_firmware_version())
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .radio_serial_protocol import (
    RadioSerialProtocol,
    ConnectionError,
    TimeoutError,
    list_serial_ports,
)
from .radio_udp_protocol import RadioUdpProtocol


# ---------------------------------------------------------------------------
# Standalone heartbeat formatter (no RadioConfig instance needed)
# ---------------------------------------------------------------------------


def format_heartbeat(hb: Dict[str, Any]) -> str:
    """将 ``radioStationR2Heart`` 心跳包 dict 格式化为可读字符串。

    可以直接传入 :meth:`RadioConfig.get_heartbeat` 的返回值，
    也可以用于离线分析保存的心跳数据。

    Example::

        rc = RadioConfig()
        rc.connect("COM3")
        hb = rc.get_heartbeat()
        print(format_heartbeat(hb))
    """
    r2 = hb.get("radio_station_r2", {})
    rf_list = r2.get("radio_rf_param", [])
    btn = r2.get("button_param", {})

    BAND_LABEL = {0: "850M", 1: "2.4G"}
    STATUS_MAP = {"normal": "正常", "standby": "待机",
                  "updating": "升级中", "power_off": "关机",
                  "calibrating": "校准中", "emergency": "紧急"}
    ERROR_MAP = {"RADIO_R2_NO_ERROR": "无错误",
                 "RTK_ERROR_VALUE": "RTK 输入异常(RS232 未接)",
                 "POWER_BUTTON_NOT_PRESSED_VALUE": "电源键未按下",
                 "LOW_POWER_VALUE": "低电报警",
                 "BATTERY_ERROR_VALUE": "电池异常",
                 "CHARGE_HIGH_TEMPERATURE_VALUE": "充电温度过高",
                 "RADIO_850M_930M_HIGH_TEMPERATURE_VALUE": "850M 射频过温",
                 "RADIO_2G4_TEMPERATURE_VALUE": "2.4G 射频过温",
                 "RADIO_850M_930M_SELF_TEST_ERROR_VALUE": "850M 自检错误",
                 "RADIO_2G4_SELF_TEST_ERROR_VALUE": "2.4G 自检错误",
                 "RADIO_850M_930M_ID_CONFLICT_ERROR_VALUE": "850M ID 冲突",
                 "RADIO_2G4_ID_CONFLICT_ERROR_VALUE": "2.4G ID 冲突"}

    lines = []
    lines.append("═" * 50)
    lines.append(f"  设备类型:      {hb.get('device_type', '?')}")
    lines.append(f"  运行状态:      {STATUS_MAP.get(hb.get('firmware_running_status', ''), hb.get('firmware_running_status', '?'))}")
    lines.append(f"  固件版本:      {hb.get('firmware_version_alias', '?')}")
    lines.append(f"  本地时间:      {hb.get('local_ms_time', 0)} ms")
    lines.append("─" * 50)
    lines.append(f"  错误状态:      {ERROR_MAP.get(r2.get('error_report', ''), r2.get('error_report', '?'))}")
    lines.append(f"  以太网 IP:     {r2.get('ethernet_ip', '?')}")
    lines.append(f"  电量:          {r2.get('battery_percentage', '?')}%")
    if r2.get('gps_utc_time'):
        lines.append(f"  GPS UTC 时间:  {r2.get('gps_utc_time')} ms")
    if r2.get('device_id'):
        lines.append(f"  电台 ID:       {r2.get('device_id')}")

    MODE_DEFAULT = {0: "850M", 1: "2.4G"}
    for i, rf in enumerate(rf_list):
        label = BAND_LABEL.get(i, f"射频[{i}]")
        mode = rf.get('rf_work_mode') or MODE_DEFAULT.get(i, "默认")
        temp = rf.get('rf_temperature', '?')
        powers = rf.get('rf_tx_power_dbm', [])
        hi = rf.get('rf_max_fre', [0])[0] if rf.get('rf_max_fre') else 0
        lo = rf.get('rf_min_fre', [0])[0] if rf.get('rf_min_fre') else 0
        lines.append("─" * 50)
        lines.append(f"  [{label}] 模式: {mode}  温度: {temp}°C")
        lines.append(f"         功率: {powers}")
        if lo or hi:
            lines.append(f"         频率: {lo/1e6:.3f} ~ {hi/1e6:.3f} MHz")

    positions = r2.get("radioGroupPosition", [])
    for i, pos in enumerate(positions):
        if pos.get("device_id") or pos.get("latitude"):
            lines.append("─" * 50)
            lines.append(f"  基站[{i}]: ID={pos.get('device_id')} "
                         f"lat={pos.get('latitude',0):.6f} "
                         f"lon={pos.get('longitude',0):.6f} "
                         f"alt={pos.get('altitude',0):.1f}m")

    if btn:
        lines.append("─" * 50)
        lines.append(f"  按键长按模式:  {btn.get('long_click_button_mode', [])}")
        lines.append(f"  按键短按模式:  {btn.get('short_click_button_mode', [])}")

    lines.append("═" * 50)
    return "\n".join(lines)


class RadioConfig:
    """电台参数配置工具（同步 API）。

    对 ``RadioSerialProtocol`` 的薄封装，提供上下文管理器和向后兼容的方法名。
    """

    def __init__(
        self,
        xml_path: Optional[str] = None,
        pb2_path: Optional[str] = None,
    ) -> None:
        self._rtp = RadioSerialProtocol(xml_path=xml_path, pb2_path=pb2_path)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self, port: str, baud: int = 460800, timeout: float = 5.0) -> None:
        """打开串口并发现设备。"""
        self._rtp.connect(port, baud, timeout)

    def disconnect(self) -> None:
        self._rtp.disconnect()

    def close(self) -> None:
        self.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._rtp.is_connected

    # ------------------------------------------------------------------
    # Port enumeration
    # ------------------------------------------------------------------

    @staticmethod
    def list_ports() -> List[Tuple[str, str]]:
        return list_serial_ports()

    # ------------------------------------------------------------------
    # Firmware version
    # ------------------------------------------------------------------

    def get_firmware_version(self, timeout: float = 3.0) -> str:
        """查询固件版本。"""
        return self._rtp.query_firmware_version(timeout)

    # ------------------------------------------------------------------
    # Encrypt key
    # ------------------------------------------------------------------

    def get_radio_encrypt_key(self, timeout: float = 3.0) -> Dict[str, Any]:
        """查询电台加密密钥。"""
        return self._rtp.get_encrypt_key(timeout)

    def set_radio_encrypt_key(
        self,
        encrypt_type: int,
        encrypt_key: bytes = b"",
        encrypt_iv: bytes = b"",
        timeout: float = 3.0,
    ) -> None:
        """设置设备加密密钥。"""
        self._rtp.set_encrypt_key(encrypt_type, encrypt_key, encrypt_iv, timeout)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def get_heartbeat(self, timeout: float = 3.0) -> Dict[str, Any]:
        """查询设备心跳包（R2 电台）。返回原始 dict。"""
        return self._rtp.query_heartbeat(timeout)

    def format_heartbeat(self, timeout: float = 3.0) -> str:
        """查询心跳包并格式化输出。等价于 ``format_heartbeat(self.get_heartbeat(timeout))``。"""
        return format_heartbeat(self._rtp.query_heartbeat(timeout))

    # ------------------------------------------------------------------
    # Button param
    # ------------------------------------------------------------------

    def set_button_param(
        self,
        long_click_time: Optional[List[int]] = None,
        long_click_mode: Optional[List[int]] = None,
        short_click_mode: Optional[List[int]] = None,
        timeout: float = 3.0,
    ) -> None:
        """设置电台自定义按键功能。

        Args:
            long_click_time: 长按时间阈值 (ms)。
            long_click_mode: 长按功能。0=保留, 1=返航, 2=降落, 3=急停, 4=自定义。
            short_click_mode: 短按功能。
        """
        self._rtp.set_button_param(
            long_click_time=long_click_time,
            long_click_mode=long_click_mode,
            short_click_mode=short_click_mode,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "RadioConfig":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.disconnect()
        return False

    def __del__(self) -> None:
        try:
            self.disconnect()
        except Exception:
            pass


class RadioConfigUdp:
    """电台参数配置工具（UDP 网口同步 API）。

    对 ``RadioUdpProtocol`` 的薄封装，提供与 ``RadioConfig`` 相同的上层 API，
    但通过网口（UDP）而非串口通信。

    与串口可以直接查询不同，UDP 需要先等待 Radio 发送 ``ENROLL_REQUEST``
    上线请求，PC 自动回复 ``ENROLL_REPLY`` 后设备上线，之后才能正常查询。

    Usage::

        with RadioConfigUdp() as rc:
            rc.connect("172.20.0.76", 14555, local_port=14555)
            print(rc.get_firmware_version())
            print(rc.get_heartbeat())
    """

    def __init__(
        self,
        xml_path: Optional[str] = None,
        pb2_path: Optional[str] = None,
    ) -> None:
        self._rtp = RadioUdpProtocol(xml_path=xml_path, pb2_path=pb2_path)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(
        self,
        host: str,
        port: int,
        local_port: int = 0,
        timeout: float = 5.0,
    ) -> None:
        """创建 UDP socket 并等待 Radio 上线。

        Radio 发送 ``ENROLL_REQUEST`` → PC 自动回复 ``ENROLL_REPLY`` → 上线完成。

        Args:
            host: 远端设备 IP 地址。
            port: 远端设备端口号。
            local_port: 本地绑定端口（0=自动分配）。
            timeout: 等待上线的超时秒数。
        """
        self._rtp.connect(host, port, local_port, timeout)

    def disconnect(self) -> None:
        self._rtp.disconnect()

    def close(self) -> None:
        self.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._rtp.is_connected

    @property
    def is_enrolled(self) -> bool:
        """设备是否已上线（已完成 ENROLL 握手）。"""
        return self._rtp.is_enrolled

    @property
    def remote_addr(self) -> Tuple[str, int]:
        """返回当前连接的远端地址 (host, port)。"""
        return self._rtp.remote_addr

    @property
    def local_port(self) -> int:
        """返回本地绑定的端口号。"""
        return self._rtp.local_port

    # ------------------------------------------------------------------
    # Firmware version
    # ------------------------------------------------------------------

    def get_firmware_version(self, timeout: float = 3.0) -> str:
        """查询固件版本。"""
        return self._rtp.query_firmware_version(timeout)

    # ------------------------------------------------------------------
    # Encrypt key
    # ------------------------------------------------------------------

    def get_radio_encrypt_key(self, timeout: float = 3.0) -> Dict[str, Any]:
        """查询电台加密密钥。"""
        return self._rtp.get_encrypt_key(timeout)

    def set_radio_encrypt_key(
        self,
        encrypt_type: int,
        encrypt_key: bytes = b"",
        encrypt_iv: bytes = b"",
        timeout: float = 3.0,
    ) -> None:
        """设置设备加密密钥。"""
        self._rtp.set_encrypt_key(encrypt_type, encrypt_key, encrypt_iv, timeout)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def get_heartbeat(self, timeout: float = 3.0) -> Dict[str, Any]:
        """查询设备心跳包（R2 电台）。返回原始 dict。"""
        return self._rtp.query_heartbeat(timeout)

    def format_heartbeat(self, timeout: float = 3.0) -> str:
        """查询心跳包并格式化输出。"""
        return format_heartbeat(self._rtp.query_heartbeat(timeout))

    # ------------------------------------------------------------------
    # Button param
    # ------------------------------------------------------------------

    def set_button_param(
        self,
        long_click_time: Optional[List[int]] = None,
        long_click_mode: Optional[List[int]] = None,
        short_click_mode: Optional[List[int]] = None,
        timeout: float = 3.0,
    ) -> None:
        """设置电台自定义按键功能。"""
        self._rtp.set_button_param(
            long_click_time=long_click_time,
            long_click_mode=long_click_mode,
            short_click_mode=short_click_mode,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "RadioConfigUdp":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.disconnect()
        return False

    def __del__(self) -> None:
        try:
            self.disconnect()
        except Exception:
            pass
