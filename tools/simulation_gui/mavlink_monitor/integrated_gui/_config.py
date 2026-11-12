"""SimConfig 模拟器元配置 + _SocketInterceptor。

从 integrated_gui.py 拆分出来的独立模块。
依赖: ._types, ._reflection
"""
from __future__ import annotations

import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._env import (
    _FAKE_SRC, HAS_FAKE_CLOUD, HAS_FAKE_MODULES,
    AIRPLANE_MODEL_SERIALS, FakeAirplane,
    _FakeAirplaneMessageSender, _FakeAirplaneMessageSenders,
    FakeNest, _FakeNestSender, _FakeNestSenders,
    FAKE_RADIO_IP, DGCS_IP, RADIO_NETCARD_INTERFACE,
    SUB_DEVICE_R2_STATION, FakeR2RadioStation,
    _FakeRadioSender, _FakeRadioSenders,
    DEFAULT_LISTEN_HOST, DEFAULT_LISTEN_PORT, DEFAULT_UPSTREAM_ORIGIN,
    FakeCloudGateway, _FakeCloudSender, _FakeCloudSenders,
)

# fake_cloud 源目录（本仓库 simulation_gui/fake_cloud/，区别于假项目 _FAKE_SRC）
_CLOUD_SRC = Path(__file__).resolve().parents[2] / "fake_cloud"

# SimConfig —— 模拟器元配置
# ═══════════════════════════════════════════════════════════════
@dataclass
class SimConfig:
    """单个模拟器 Tab 的全部配置。"""
    key: str
    label: str
    source_file: Path
    sender_cls_name: str
    mgr_cls_name: str
    transport_cls: type
    sender_cls: type
    mgr_cls: type
    mgr_senders_attr: str
    mgr_transports_attr: str
    aid_prefix: str
    known_param_types: dict[str, str]
    method_param_types: dict[str, dict[str, str]] = field(default_factory=dict)
    has_nested_devices: bool = False
    param_choices: dict[str, dict[str, str]] = field(default_factory=dict)
    param_defaults: dict[str, Any] = field(default_factory=dict)
    # 「应用基础参数」的 importlib 模块名；空 = source_file.stem（顶层模块）。
    # 包内模块（如 fake_cloud.ad_proxy）必须显式指定 dotted 路径，
    # 否则 import_module(stem) 报 ModuleNotFoundError。
    module_name: str = ""


# 仅在假模块可用时构建 SIM_CONFIGS
def _build_sim_configs() -> dict[str, SimConfig]:
    """构建模拟器配置字典。

    cloud（云平台透明反向代理）在本仓库内，恒可用；
    airplane / nest / radio 仅在 HAS_FAKE_MODULES 时可用。
    """
    configs: dict[str, SimConfig] = {}
    if HAS_FAKE_CLOUD:
        configs["cloud"] = SimConfig(
            key="cloud",
            label="云平台拦截 (FakeCloud)",
            source_file=_CLOUD_SRC / "ad_proxy.py",
            sender_cls_name="_FakeCloudSender",
            mgr_cls_name="_FakeCloudSenders",
            transport_cls=FakeCloudGateway,
            sender_cls=_FakeCloudSender,
            mgr_cls=_FakeCloudSenders,
            mgr_senders_attr="cloud_senders",
            mgr_transports_attr="cloud_gateways",
            aid_prefix="FC_",
            module_name="fake_cloud.ad_proxy",
            known_param_types={
                "count": "int",
                "listen_host": "str",
                "listen_port": "int",
                "upstream_origin": "str",
                "parse_promotion": "bool",
                "max_events": "int",
                "upstream": "str",
                "enable": "bool",
            },
            param_defaults={
                "count": 1,
                "listen_host": DEFAULT_LISTEN_HOST,
                "listen_port": DEFAULT_LISTEN_PORT,
                "upstream_origin": DEFAULT_UPSTREAM_ORIGIN,
                "parse_promotion": True,
            },
        )
    if not HAS_FAKE_MODULES:
        return configs
    configs.update({
        "airplane": SimConfig(
            key="airplane",
            label="假飞机 (FakeAirplane)",
            source_file=_FAKE_SRC / "fake_airplane.py",
            sender_cls_name="_FakeAirplaneMessageSender",
            mgr_cls_name="_FakeAirplaneMessageSenders",
            transport_cls=FakeAirplane,
            sender_cls=_FakeAirplaneMessageSender,
            mgr_cls=_FakeAirplaneMessageSenders,
            mgr_senders_attr="fake_airplane_senders",
            mgr_transports_attr="fake_airplanes",
            aid_prefix="FA_",
            known_param_types={
                "count": "int",
                "mavlink_version": "str",
                "start_ip": "str",
                "start_serial": "str",
                "start_code": "int",
                "value": "int",  # update_param_hash 的 hash 值
                "nova_light_version": "bytes",
                "gimbal_version": "bytes",
                "wind_speed_x": "int16",
                "wind_speed_y": "int16",
                "laser_config": "list_int",
                "laser_state": "int",
                "nova_config": "int",
                "nova_state": "int",
                "firework_config": "list_int",
                "lantern_config": "int",
                "lantern_state": "int",
                "trumpet_config": "int",
                "trumpet_state": "int",
                "trumpet": "int",
                "parachute_config": "int",
                "parachute_state": "int",
                "parachute": "int",
                # -- 蟠桃灯 / 鱼灯 / 旧孔明灯 / 撒花器 --
                "peach_lantern_config": "int",
                "fish_lantern_config": "int",
                "kongming_lantern_config": "int",
                "confetti_config": "int",
                # -- update_position: GPS 位置（MAVLink msg_id=5, GUI 输入度/米，自动 ×1e7 / ×1000）--
                "cur_lat": "latlon",
                "cur_lon": "latlon",
                "tar_lat": "latlon",
                "tar_lon": "latlon",
                "cur_alt": "alt_m",
                "tar_alt": "alt_m",
                "fix_type": "uint8",
                "rtk_radio_850m": "uint8",
                "rtk_radio_2g4": "uint8",
                # -- update_drama_state: 剧本状态（MAVLink msg_id=5）+ 0x2A ACK result 覆写--
                "drama_state": "int",
                "mission_request_ack_result": "int",
                "imu": "int",
                "baro": "int",
                "compass": "int",
                "gps": "int",
                "battery": "int",
                "bno_reset": "int",
                "acc_calibrated": "int",
                "compass_calibrated": "int",
                "color_calibrated": "int",
                "magnetic_calibrated": "int",
                "scram": "int",
                "esc": "int",
                "tele": "int",
                "bms": "int",
                "module": "int",
                # -- 电池/电压相关字段（MAVLink msg_id=5, H=uint16_t, B=uint8_t）--
                "voltage_battery": "uint16",
                "voltage_battery_percent": "uint16",
                "voltage_battery_diff": "uint16",
                "voltage_battery_history_diff": "uint16",
                "bat_serial_prefix": "bytes",
                "bat_serial_suffix": "bytes",
                "bat_serial_need_reset": "uint8",
                "charge_state": "uint8",
                "battery_time": "int",
                "temp_batt": "int",
                "battery_capability": "int",
                "battery_used_times": "int",
                "voltage_battery_cell1": "int",
                "voltage_battery_cell2": "int",
                "voltage_battery_cell3": "int",
                "voltage_battery_cell4": "int",
                "voltage_battery_cell5": "int",
                "voltage_battery_cell6": "int",
                "voltage_rid_bat": "int",
                # -- 0x3B REMAINING_CAPACITY(59) 字段（update_bat，协议原文拼写）--
                "safe_fly_radius": "float",
                "remain_fly_time": "int",
                "go_home_need_time": "int",
                "land_need_time": "int",
                "go_home_need_capacity": "int",
                "land_need_capacity": "int",
                "battery_total_capaticy": "int",
                "battery_remain_capaticy": "int",
                "battry_capacity_percentage": "int",
                # -- 悬停测试 + 电子围栏 --
                "manual_enable": "bool",
                "safe_distance": "float",
                "takeoff_height": "float",
                "hover_duration": "int",
                # -- ACK 配置（update_ack）--
                "fail_count": "int",
                "silence_count": "int",
                "cmd_result_enable": "bool",
                "cmd_result_commands": "list_int",
                "cmd_result_values": "list_int",
                # -- failsafe(0x06) 故障位配置（update_failsafe）--
                "enable": "bool",
                "f_crash": "bool",
                "f_radio": "bool",
                "f_battery": "bool",
                "f_fence_alt": "bool",
                "f_fence_circle": "bool",
                "f_waypoint": "bool",
                "f_too_far": "bool",
                "f_static_dist": "bool",
                "f_vibrate": "bool",
                "f_drama_fail": "bool",
                "f_parachute": "bool",
                "f_sensor_fail": "bool",
                "f_fence_2": "bool",
                "f_ekf_stab": "bool",
                "f_ekf_horz": "bool",
                "f_ekf_vert": "bool",
            },
            param_choices={
                "start_serial": AIRPLANE_MODEL_SERIALS,
            },
            param_defaults={
                "mavlink_version": "44",
                "count": 5,
                "start_ip": "172.16.3.168",
                "start_serial": AIRPLANE_MODEL_SERIALS["X1"],
                "start_code": 101,
                "nova_light_version": b"1003",
                "gimbal_version": b"1007",
            },
        ),
        "nest": SimConfig(
            key="nest",
            label="假机巢 (FakeNest)",
            source_file=_FAKE_SRC / "fake_nest.py",
            sender_cls_name="_FakeNestSender",
            mgr_cls_name="_FakeNestSenders",
            transport_cls=FakeNest,
            sender_cls=_FakeNestSender,
            mgr_cls=_FakeNestSenders,
            mgr_senders_attr="nest_senders",
            mgr_transports_attr="fake_nests",
            aid_prefix="FN_",
            known_param_types={
                "count": "int",
                "start_ip": "str",
                "start_serial": "str",
                "start_code": "int",
                "start_nestId": "int",
                "start_uav_ip": "str",
                "nestIp": "str",
                "serial": "bytes",
                "code": "bytes",
                # -- ACK 配置（update_ack）--
                "fail_count": "int",
                "silence_count": "int",
            },
            param_defaults={
                "count": 2,
                "start_ip": "172.17.0.1",
                "start_serial": "NESTF0K",
                "start_code": 1,
                "start_nestId": 1,
                "start_uav_ip": "172.17.1.1",
            },
            has_nested_devices=True,
        ),
        "radio": SimConfig(
            key="radio",
            label="假电台 (FakeRadio)",
            source_file=_FAKE_SRC / "fake_radio.py",
            sender_cls_name="_FakeRadioSender",
            mgr_cls_name="_FakeRadioSenders",
            transport_cls=FakeR2RadioStation,
            sender_cls=_FakeRadioSender,
            mgr_cls=_FakeRadioSenders,
            mgr_senders_attr="radio_senders",
            mgr_transports_attr="radios",
            aid_prefix="FR_",
            known_param_types={
                "count": "int",
                "start_device_id": "int",
                "start_ip": "str",
                "sub_device_type": "int",
                "dgcs_ip": "str",
                "interface": "str",
                "percentage": "int",
                "voltage_mv": "int",
                "temperature": "int",
                "latitude": "float",
                "longitude": "float",
                "altitude": "float",
                "encrypt_type": "int",
                "band_key": "str",
                "mode": "int",
                "powers": "list_int",
                "min_freqs": "list_int",
                "max_freqs": "list_int",
                # -- ACK 配置（update_ack）--
                "fail_count": "int",
                "silence_count": "int",
                "cmd_result_enable": "bool",
                "cmd_result_commands": "list_int",
                "cmd_result_values": "list_int",
            },
            param_defaults={
                "count": 1,
                "start_device_id": 1,
                "start_ip": FAKE_RADIO_IP,
                "sub_device_type": SUB_DEVICE_R2_STATION,
                "dgcs_ip": DGCS_IP,
                "interface": RADIO_NETCARD_INTERFACE,
            },
        ),
    })
    return configs


# ═══════════════════════════════════════════════════════════════
# _SocketInterceptor —— 包装 socket 拦截 recvfrom 数据
# ═══════════════════════════════════════════════════════════════
class _SocketInterceptor:
    """包装 socket.socket，拦截 recvfrom / sendto 以捕获假节点收发的原始数据。"""

    def __init__(self, real_sock, on_recv: Callable | None = None,
                 on_send: Callable | None = None):
        self._sock = real_sock
        self._on_recv = on_recv
        self._on_send = on_send

    def recvfrom(self, *args, **kwargs):
        data, addr = self._sock.recvfrom(*args, **kwargs)
        if self._on_recv:
            try:
                self._on_recv(data, addr)
            except Exception:
                pass  # 回调异常绝对不能影响主业务
        return data, addr

    def sendto(self, data, *args, **kwargs):
        result = self._sock.sendto(data, *args, **kwargs)
        if self._on_send:
            try:
                addr = args[0] if args else kwargs.get("address")
                self._on_send(data, addr)
            except Exception:
                pass  # 回调异常绝对不能影响主业务
        return result

    def __getattr__(self, name):
        return getattr(self._sock, name)


