"""
假 R2 电台模拟器（FakeR2RadioStation）。

基于 DGCS v4 DAV 协议（DavLink2）实现，模拟 R2 双频 / R2G 单频电台的完整生命周期：
  INIT → ENROLLING → ONLINE → （心跳保持 + 响应地面站命令）

协议参考：D:\Work\dgcs4\Python假电台模拟器技术方案.md
架构参考：fake_airplane.py / fake_nest.py

Usage:
    python -m src.Protocol.mavlink.fake_radio

    或在代码中:
    from src.Protocol.mavlink.fake_radio import FakeR2RadioStation

    radio = FakeR2RadioStation(device_id=1, sub_device_type=5)
    radio.start()
    ...
    radio.stop()
"""

import ctypes
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from typing import Optional, Tuple

from utils.logger import LogManager, logger

# ==========================================================================
# 配置常量
# ==========================================================================

FAKE_RADIO_IP = "172.16.200.100"
DGCS_IP = "172.16.200.1"
DAV_PORT = 14555
NETCARD_INTERFACE = "WLAN 6"

# R2 地址范围: 0xFFFFFFFFFF100 ~ 0xFFFFFFFFFF1FF (device_id=0~255)
RADIO_BASE_ADDR = 0xFFFFFFFFFF100
GROUND_ADDR = 0xFFFFFFFFFFFF0  # 52-bit 地面站地址（12个F）

# ==========================================================================
# CRC8 查表 — 多项式 x^8 + x^5 + x^4 + 1 (0x31)
# 来源: CRC8.cs:7-23（与技术方案文档 §4.1 一致）
# ==========================================================================

CRC8_TABLE = (
    0x00, 0x5E, 0xBC, 0xE2, 0x61, 0x3F, 0xDD, 0x83, 0xC2, 0x9C, 0x7E, 0x20, 0xA3, 0xFD, 0x1F, 0x41,
    0x9D, 0xC3, 0x21, 0x7F, 0xFC, 0xA2, 0x40, 0x1E, 0x5F, 0x01, 0xE3, 0xBD, 0x3E, 0x60, 0x82, 0xDC,
    0x23, 0x7D, 0x9F, 0xC1, 0x42, 0x1C, 0xFE, 0xA0, 0xE1, 0xBF, 0x5D, 0x03, 0x80, 0xDE, 0x3C, 0x62,
    0xBE, 0xE0, 0x02, 0x5C, 0xDF, 0x81, 0x63, 0x3D, 0x7C, 0x22, 0xC0, 0x9E, 0x1D, 0x43, 0xA1, 0xFF,
    0x46, 0x18, 0xFA, 0xA4, 0x27, 0x79, 0x9B, 0xC5, 0x84, 0xDA, 0x38, 0x66, 0xE5, 0xBB, 0x59, 0x07,
    0xDB, 0x85, 0x67, 0x39, 0xBA, 0xE4, 0x06, 0x58, 0x19, 0x47, 0xA5, 0xFB, 0x78, 0x26, 0xC4, 0x9A,
    0x65, 0x3B, 0xD9, 0x87, 0x04, 0x5A, 0xB8, 0xE6, 0xA7, 0xF9, 0x1B, 0x45, 0xC6, 0x98, 0x7A, 0x24,
    0xF8, 0xA6, 0x44, 0x1A, 0x99, 0xC7, 0x25, 0x7B, 0x3A, 0x64, 0x86, 0xD8, 0x5B, 0x05, 0xE7, 0xB9,
    0x8C, 0xD2, 0x30, 0x6E, 0xED, 0xB3, 0x51, 0x0F, 0x4E, 0x10, 0xF2, 0xAC, 0x2F, 0x71, 0x93, 0xCD,
    0x11, 0x4F, 0xAD, 0xF3, 0x70, 0x2E, 0xCC, 0x92, 0xD3, 0x8D, 0x6F, 0x31, 0xB2, 0xEC, 0x0E, 0x50,
    0xAF, 0xF1, 0x13, 0x4D, 0xCE, 0x90, 0x72, 0x2C, 0x6D, 0x33, 0xD1, 0x8F, 0x0C, 0x52, 0xB0, 0xEE,
    0x32, 0x6C, 0x8E, 0xD0, 0x53, 0x0D, 0xEF, 0xB1, 0xF0, 0xAE, 0x4C, 0x12, 0x91, 0xCF, 0x2D, 0x73,
    0xCA, 0x94, 0x76, 0x28, 0xAB, 0xF5, 0x17, 0x49, 0x08, 0x56, 0xB4, 0xEA, 0x69, 0x37, 0xD5, 0x8B,
    0x57, 0x09, 0xEB, 0xB5, 0x36, 0x68, 0x8A, 0xD4, 0x95, 0xCB, 0x29, 0x77, 0xF4, 0xAA, 0x48, 0x16,
    0xE9, 0xB7, 0x55, 0x0B, 0x88, 0xD6, 0x34, 0x6A, 0x2B, 0x75, 0x97, 0xC9, 0x4A, 0x14, 0xF6, 0xA8,
    0x74, 0x2A, 0xC8, 0x96, 0x15, 0x4B, 0xA9, 0xF7, 0xB6, 0xE8, 0x0A, 0x54, 0xD7, 0x89, 0x6B, 0x35,
)


def crc8(data: bytes, offset: int = 0, length: int = None) -> int:
    """CRC8 帧头校验。初始值 0xFF，覆盖 byte 0~20（共 21 字节）。"""
    if length is None:
        length = len(data) - offset
    crc = 0xFF
    for i in range(offset, offset + length):
        crc = CRC8_TABLE[crc ^ data[i]]
    return crc & 0xFF


# ==========================================================================
# CRC16 查表 — 多项式 x^16 + x^12 + x^5 + 1 (0x8005)
# 来源: CRC16.cs:7-28（与技术方案文档 §4.2 一致）
# ==========================================================================

CRC16_TABLE = (
    0x0000, 0x1189, 0x2312, 0x329B, 0x4624, 0x57AD, 0x6536, 0x74BF, 0x8C48, 0x9DC1, 0xAF5A, 0xBED3,
    0xCA6C, 0xDBE5, 0xE97E, 0xF8F7, 0x1081, 0x0108, 0x3393, 0x221A, 0x56A5, 0x472C, 0x75B7, 0x643E,
    0x9CC9, 0x8D40, 0xBFDB, 0xAE52, 0xDAED, 0xCB64, 0xF9FF, 0xE876, 0x2102, 0x308B, 0x0210, 0x1399,
    0x6726, 0x76AF, 0x4434, 0x55BD, 0xAD4A, 0xBCC3, 0x8E58, 0x9FD1, 0xEB6E, 0xFAE7, 0xC87C, 0xD9F5,
    0x3183, 0x200A, 0x1291, 0x0318, 0x77A7, 0x662E, 0x54B5, 0x453C, 0xBDCB, 0xAC42, 0x9ED9, 0x8F50,
    0xFBEF, 0xEA66, 0xD8FD, 0xC974, 0x4204, 0x538D, 0x6116, 0x709F, 0x0420, 0x15A9, 0x2732, 0x36BB,
    0xCE4C, 0xDFC5, 0xED5E, 0xFCD7, 0x8868, 0x99E1, 0xAB7A, 0xBAF3, 0x5285, 0x430C, 0x7197, 0x601E,
    0x14A1, 0x0528, 0x37B3, 0x263A, 0xDECD, 0xCF44, 0xFDDF, 0xEC56, 0x98E9, 0x8960, 0xBBFB, 0xAA72,
    0x6306, 0x728F, 0x4014, 0x519D, 0x2522, 0x34AB, 0x0630, 0x17B9, 0xEF4E, 0xFEC7, 0xCC5C, 0xDDD5,
    0xA96A, 0xB8E3, 0x8A78, 0x9BF1, 0x7387, 0x620E, 0x5095, 0x411C, 0x35A3, 0x242A, 0x16B1, 0x0738,
    0xFFCF, 0xEE46, 0xDCDD, 0xCD54, 0xB9EB, 0xA862, 0x9AF9, 0x8B70, 0x8408, 0x9581, 0xA71A, 0xB693,
    0xC22C, 0xD3A5, 0xE13E, 0xF0B7, 0x0840, 0x19C9, 0x2B52, 0x3ADB, 0x4E64, 0x5FED, 0x6D76, 0x7CFF,
    0x9489, 0x8500, 0xB79B, 0xA612, 0xD2AD, 0xC324, 0xF1BF, 0xE036, 0x18C1, 0x0948, 0x3BD3, 0x2A5A,
    0x5EE5, 0x4F6C, 0x7DF7, 0x6C7E, 0xA50A, 0xB483, 0x8618, 0x9791, 0xE32E, 0xF2A7, 0xC03C, 0xD1B5,
    0x2942, 0x38CB, 0x0A50, 0x1BD9, 0x6F66, 0x7EEF, 0x4C74, 0x5DFD, 0xB58B, 0xA402, 0x9699, 0x8710,
    0xF3AF, 0xE226, 0xD0BD, 0xC134, 0x39C3, 0x284A, 0x1AD1, 0x0B58, 0x7FE7, 0x6E6E, 0x5CF5, 0x4D7C,
    0xC60C, 0xD785, 0xE51E, 0xF497, 0x8028, 0x91A1, 0xA33A, 0xB2B3, 0x4A44, 0x5BCD, 0x6956, 0x78DF,
    0x0C60, 0x1DE9, 0x2F72, 0x3EFB, 0xD68D, 0xC704, 0xF59F, 0xE416, 0x90A9, 0x8120, 0xB3BB, 0xA232,
    0x5AC5, 0x4B4C, 0x79D7, 0x685E, 0x1CE1, 0x0D68, 0x3FF3, 0x2E7A, 0xE70E, 0xF687, 0xC41C, 0xD595,
    0xA12A, 0xB0A3, 0x8238, 0x93B1, 0x6B46, 0x7ACF, 0x4854, 0x59DD, 0x2D62, 0x3CEB, 0x0E70, 0x1FF9,
    0xF78F, 0xE606, 0xD49D, 0xC514, 0xB1AB, 0xA022, 0x92B9, 0x8330, 0x7BC7, 0x6A4E, 0x58D5, 0x495C,
    0x3DE3, 0x2C6A, 0x1EF1, 0x0F78,
)


def crc16(data: bytes, offset: int = 0, length: int = None) -> int:
    """CRC16 整帧校验。初始值 0xFFFF，覆盖 byte 0~End-3。"""
    if length is None:
        length = len(data) - offset
    crc = 0xFFFF
    for i in range(offset, offset + length):
        crc = (crc >> 8) ^ CRC16_TABLE[(crc ^ data[i]) & 0x00FF]
    return crc & 0xFFFF


# ==========================================================================
# Protobuf 手动编码 — 不依赖 .proto 编译，使用 wire format 直接构造
# 消息定义来源：DavMessage.proto（技术方案 §5）
# ==========================================================================

# MessageID 枚举（技术方案 §5.1）
class MessageID:
    ENROLL_REQUEST = 0x000C
    ENROLL_REPLY = 0x000D
    ASK_HEARTBEAT = 0x000E
    RADIO_SEND_RTCM = 0x0100
    SET_RADIO_ENCRYPT_KEY = 0x0102
    ASK_RADIO_ENCRYPT_KEY = 0x0103
    SEND_RADIO_ENCRYPT_KEY = 0x0104
    SET_RADIO_RECEIVER_MODE = 0x0111
    REMOTE_CONTROL_FREQ_MATCHING = 0x0112
    SET_RECEIVER_RC_AND_RADIO_PARAM = 0x0119
    ASK_RADIO_REGULATORY_DOMAIN = 0x0201
    SEND_RADIO_REGULATORY_DOMAIN = 0x0202
    SET_RADIO_REGULATORY_DOMAIN = 0x0203
    SEND_RADIO_R2_HEARTBEAT = 0x0204
    SET_RADIO_BUTTON_PARAM = 0x0205
    SEND_RADIO_RF_PARAM_ECHO = 0x0207


# onlineDeviceType
ONLINE_DEVICE_TYPE_RADIO_STATION = 2

# subDeviceType
SUB_DEVICE_R2_850M_930M_V1 = 2
SUB_DEVICE_R2_2G4_V1 = 3
SUB_DEVICE_R2_STATION = 5  # 双频

# firmwareRunningStatus
FIRMWARE_NORMAL = 0

# radioRegulatoryDomain
COUNTRY_CODE_MUTE = 0
COUNTRY_CODE_R2_ISM2G4 = 5
COUNTRY_CODE_R2_850M_930M = 6

# enrollResult
ENROLL_ACCEPTED = 0


def _proto_varint(value: int) -> bytes:
    """编码 protobuf varint。"""
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def _proto_field_varint(field_number: int, value: int) -> bytes:
    """编码 varint 字段: tag + value。"""
    tag = (field_number << 3) | 0  # wire_type = 0 (varint)
    return _proto_varint(tag) + _proto_varint(value)


def _proto_field_length_delimited(field_number: int, data: bytes) -> bytes:
    """编码 length-delimited 字段: tag + length + data。"""
    tag = (field_number << 3) | 2  # wire_type = 2
    return _proto_varint(tag) + _proto_varint(len(data)) + data


def _proto_field_fixed32(field_number: int, value: int) -> bytes:
    """编码 fixed32 字段: tag + 4 bytes LE。"""
    tag = (field_number << 3) | 5  # wire_type = 5
    return _proto_varint(tag) + struct.pack('<I', value)


def _proto_field_fixed64(field_number: int, value: float) -> bytes:
    """编码 fixed64 字段: tag + 8 bytes LE（double 的 IEEE 754 双精度位）。

    proto 中 ``double`` 字段使用 wire_type=1（fixed64）。
    用于 rtkStationPosition 的 latitude/longitude/altitude。
    """
    tag = (field_number << 3) | 1  # wire_type = 1
    return _proto_varint(tag) + struct.pack('<d', value)


def _proto_packed_varint(field_number: int, values: list) -> bytes:
    """编码 packed repeated varint 字段。"""
    tag = (field_number << 3) | 2  # wire_type = 2 (length-delimited)
    inner = b''.join(_proto_varint(v) for v in values)
    return _proto_varint(tag) + _proto_varint(len(inner)) + inner


def build_enroll_request(serial_number: str, product_name: str) -> bytes:
    """构建 EnrollRequest protobuf（技术方案 §5.2）。

    message EnrollRequest {
        onlineDeviceType device_type = 1;  // RADIO_STATION = 2
        string product_name = 2;
        string serial_number = 3;
        uint32 check = 4;                  // 0
    }
    """
    result = bytearray()
    result += _proto_field_varint(1, ONLINE_DEVICE_TYPE_RADIO_STATION)
    result += _proto_field_length_delimited(2, product_name.encode('utf-8'))
    result += _proto_field_length_delimited(3, serial_number.encode('utf-8'))
    result += _proto_field_varint(4, 0)  # check = 0
    return bytes(result)


def build_send_encrypt_key(encrypt_type: int = 0, encrypt_key: bytes = b"",
                           encrypt_iv: bytes = b"") -> bytes:
    """构建 SEND_RADIO_ENCRYPT_KEY (0x0104) 响应 protobuf（技术方案 §5.5.2）。

    message RadioEncryptKey {
        EncryptKey radio_key = 1;  // EncryptKey{encrypt_type=1, encrypt_key=2, encrypt_iv=3}
        EncryptKey rc_key = 2;
    }
    作为 ASK_RADIO_ENCRYPT_KEY (0x0103) 的应答，携带当前加密状态。
    """
    ek = bytearray()
    ek += _proto_field_varint(1, encrypt_type)
    ek += _proto_field_length_delimited(2, encrypt_key)
    ek += _proto_field_length_delimited(3, encrypt_iv)
    return _proto_field_length_delimited(1, bytes(ek))  # radio_key


def build_send_regulatory_domain(device_id: int, rf_params: dict) -> bytes:
    """构建 SEND_RADIO_REGULATORY_DOMAIN (0x0202) 响应 protobuf（技术方案 §5.5.1）。

    message RadioStationRegulatoryDomain {
        uint32 set_device_id = 1;
        repeated RFparameters set_rf_param = 2;  // [0]=800M, [1]=2.4G
    }
    作为 ASK_RADIO_REGULATORY_DOMAIN (0x0201) 的应答，携带当前射频参数。
    rf_params: {'band_800m': {...}, 'band_2400m': {...}}
    """
    band_keys = ['band_800m', 'band_2400m'] if 'band_800m' in rf_params else ['band_2400m']
    result = bytearray()
    result += _proto_field_varint(1, device_id)
    for band_key in band_keys:
        band = rf_params.get(band_key, {})
        rf = bytearray()
        rf += _proto_field_varint(1, band.get('mode', 0))               # rf_work_mode
        rf += _proto_packed_varint(2, band.get('powers', []))           # rf_tx_power_dbm
        rf += _proto_field_varint(3, band.get('temperature', 0))        # rf_temperature
        rf += _proto_packed_varint(4, band.get('max_freqs', []))        # rf_max_fre
        rf += _proto_packed_varint(5, band.get('min_freqs', []))        # rf_min_fre
        result += _proto_field_length_delimited(2, bytes(rf))
    return bytes(result)


def build_heartbeat(
    sub_device_type: int = SUB_DEVICE_R2_STATION,
    firmware_version_alias: str = "R2.1.0.0",
    firmware_version: int = 0x01000000,
    protobuf_version: int = 619934,
    device_id: int = 0,
    error_report: int = 0,
    ethernet_ip: str = "172.16.200.100",
    battery_percentage: int = 85,
    poe_voltage_mv: int = 12000,
    charge_temperature: int = 30,
    encrypt_type: int = 0,
    translate_data_left_bytes: int = 1024,
    gps_latitude: float = 22.0,
    gps_longitude: float = 113.0,
    gps_altitude: float = 100.0,
    rf_800m_mode: int = COUNTRY_CODE_R2_850M_930M,
    rf_800m_powers: list = None,
    rf_800m_max_freqs: list = None,
    rf_800m_min_freqs: list = None,
    rf_800m_temperature: int = 35,
    rf_2400m_mode: int = COUNTRY_CODE_R2_ISM2G4,
    rf_2400m_powers: list = None,
    rf_2400m_max_freqs: list = None,
    rf_2400m_min_freqs: list = None,
    rf_2400m_temperature: int = 32,
    button_long_click_modes: list = None,
    button_long_click_times: list = None,
    button_short_click_modes: list = None,
) -> bytes:
    """构建 RadioStationR2Heart protobuf（技术方案 §5.4）。

    message RadioStationR2Heart {
        subDeviceType device_type = 1;
        firmwareRunningStatus firmware_running_status = 2;
        string firmware_version_alias = 3;
        fixed32 firmware_version = 4;
        uint32 protobuf_version = 5;
        fixed32 local_ms_time = 6;
        RadioStationR2HeartBeatExtend radio_station_r2 = 7;
    }
    """
    if rf_800m_powers is None:
        rf_800m_powers = [30, 30]
    if rf_800m_max_freqs is None:
        rf_800m_max_freqs = [930000000, 930000000]
    if rf_800m_min_freqs is None:
        rf_800m_min_freqs = [850000000, 850000000]
    if rf_2400m_powers is None:
        rf_2400m_powers = [20, 20]
    if rf_2400m_max_freqs is None:
        rf_2400m_max_freqs = [2483500000, 2483500000]
    if rf_2400m_min_freqs is None:
        rf_2400m_min_freqs = [2400123000, 2400123000]
    if button_long_click_modes is None:
        button_long_click_modes = [4, 4]  # pause
    if button_long_click_times is None:
        button_long_click_times = [1000, 1000]  # 长按阈值 ms
    if button_short_click_modes is None:
        button_short_click_modes = [0, 0]

    local_ms_time = int(time.time() * 1000) & 0xFFFFFFFF

    # 构建扩展消息 RadioStationR2HeartBeatExtend
    ext = bytearray()
    ext += _proto_field_varint(1, device_id)                    # device_id
    ext += _proto_field_varint(2, error_report)                 # error_report
    ext += _proto_field_length_delimited(3, ethernet_ip.encode('utf-8'))  # ethernet_ip
    ext += _proto_field_varint(4, battery_percentage)           # battery_percentage
    ext += _proto_field_varint(5, poe_voltage_mv)               # poe_voltage_mv
    ext += _proto_field_varint(6, charge_temperature)           # charge_temperature
    ext += _proto_field_varint(7, 0)                             # gps_utc_time

    # radioGroupPosition (repeated RtkStationPosition)
    # proto 中 latitude/longitude/altitude 为 double（wire_type=1 fixed64），
    # 直接编码 IEEE 754 双精度位（不乘 1e7）
    pos = bytearray()
    pos += _proto_field_varint(1, device_id)
    pos += _proto_field_fixed64(2, gps_latitude)
    pos += _proto_field_fixed64(3, gps_longitude)
    pos += _proto_field_fixed64(4, gps_altitude)
    ext += _proto_field_length_delimited(8, bytes(pos))

    # radio_rf_param[0] — 800M 频段
    rf0 = bytearray()
    rf0 += _proto_field_varint(1, rf_800m_mode)
    rf0 += _proto_packed_varint(2, rf_800m_powers)
    rf0 += _proto_field_varint(3, rf_800m_temperature)
    rf0 += _proto_packed_varint(4, rf_800m_max_freqs)
    rf0 += _proto_packed_varint(5, rf_800m_min_freqs)
    ext += _proto_field_length_delimited(9, bytes(rf0))

    # radio_rf_param[1] — 2.4G 频段
    rf1 = bytearray()
    rf1 += _proto_field_varint(1, rf_2400m_mode)
    rf1 += _proto_packed_varint(2, rf_2400m_powers)
    rf1 += _proto_field_varint(3, rf_2400m_temperature)
    rf1 += _proto_packed_varint(4, rf_2400m_max_freqs)
    rf1 += _proto_packed_varint(5, rf_2400m_min_freqs)
    ext += _proto_field_length_delimited(9, bytes(rf1))

    # button_param (RadioButtonParam: long_click_time=1, long_click_button_mode=2, short_click_button_mode=3)
    btn = bytearray()
    btn += _proto_packed_varint(1, button_long_click_times)      # long_click_time
    btn += _proto_packed_varint(2, button_long_click_modes)      # long_click_button_mode
    btn += _proto_packed_varint(3, button_short_click_modes)     # short_click_button_mode
    ext += _proto_field_length_delimited(10, bytes(btn))

    # encrypt_type
    ext += _proto_field_varint(11, encrypt_type)
    # translate_data_left_bytes
    ext += _proto_field_varint(12, translate_data_left_bytes)

    # 构建 RadioStationR2Heart
    result = bytearray()
    result += _proto_field_varint(1, sub_device_type)                    # device_type
    result += _proto_field_varint(2, FIRMWARE_NORMAL)                    # firmware_running_status
    result += _proto_field_length_delimited(3, firmware_version_alias.encode('utf-8'))
    result += _proto_field_fixed32(4, firmware_version)
    result += _proto_field_varint(5, protobuf_version)
    result += _proto_field_fixed32(6, local_ms_time)
    result += _proto_field_length_delimited(7, bytes(ext))               # radio_station_r2

    return bytes(result)


def parse_enroll_reply(payload: bytes) -> dict:
    """解析 EnrollReply protobuf（技术方案 §5.3）。

    返回 {'accept_status': int, 'heartbeat_interval_ms': int}
    """
    result = {'accept_status': 0, 'heartbeat_interval_ms': 10000}
    pos = 0
    while pos < len(payload):
        tag, pos = _read_varint(payload, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7
        if wire_type == 0:  # varint
            value, pos = _read_varint(payload, pos)
            if field_number == 1:
                result['accept_status'] = value
            elif field_number == 2:
                result['heartbeat_interval_ms'] = value
        elif wire_type == 2:  # length-delimited
            length, pos = _read_varint(payload, pos)
            pos += length
        else:
            break
    return result


def _read_varint(data: bytes, pos: int) -> Tuple[int, int]:
    """读取一个 protobuf varint，返回 (value, new_pos)。"""
    value = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return value, pos


def _parse_proto_fields(data: bytes) -> list:
    """将 protobuf payload 解析为 [(field_number, wire_type, value), ...]。

    value 类型：wire_type 0 → int；wire_type 2 → bytes（子消息/字符串/packed）；
    wire_type 1/5 → int（fixed64/fixed32）。
    """
    fields = []
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        if tag is None:
            break
        field_number = tag >> 3
        wire_type = tag & 0x7
        if wire_type == 0:  # varint
            value, pos = _read_varint(data, pos)
            if value is None:
                break
            fields.append((field_number, wire_type, value))
        elif wire_type == 2:  # length-delimited
            length, pos = _read_varint(data, pos)
            if length is None:
                break
            if pos + length > len(data):
                break
            fields.append((field_number, wire_type, data[pos:pos + length]))
            pos += length
        elif wire_type == 5:  # fixed32
            if pos + 4 > len(data):
                break
            value = struct.unpack_from('<I', data, pos)[0]
            pos += 4
            fields.append((field_number, wire_type, value))
        elif wire_type == 1:  # fixed64
            if pos + 8 > len(data):
                break
            value = struct.unpack_from('<Q', data, pos)[0]
            pos += 8
            fields.append((field_number, wire_type, value))
        else:
            break
    return fields


def _parse_packed_varints(data: bytes) -> list:
    """解析 packed repeated varint 字段（wire_type=2 的字节块）。"""
    values = []
    pos = 0
    while pos < len(data):
        val, pos = _read_varint(data, pos)
        if val is None:
            break
        values.append(val)
    return values


def _parse_rfparameters(data: bytes) -> dict:
    """解析 RFparameters 子消息。

    message RFparameters {
        radioRegulatoryDomain rf_work_mode = 1;
        repeated uint32 rf_tx_power_dbm = 2;   // packed 或 unpacked
        uint32 rf_temperature = 3;
        repeated uint32 rf_max_fre = 4;        // packed 或 unpacked
        repeated uint32 rf_min_fre = 5;        // packed 或 unpacked
    }
    """
    rf = {}
    powers = []
    max_freqs = []
    min_freqs = []
    for field_number, wire_type, value in _parse_proto_fields(data):
        if field_number == 1 and wire_type == 0:
            rf['mode'] = value
        elif field_number == 2:
            if wire_type == 2:
                powers.extend(_parse_packed_varints(value))
            elif wire_type == 0:
                powers.append(value)
        elif field_number == 3 and wire_type == 0:
            rf['temperature'] = value
        elif field_number == 4:
            if wire_type == 2:
                max_freqs.extend(_parse_packed_varints(value))
            elif wire_type == 0:
                max_freqs.append(value)
        elif field_number == 5:
            if wire_type == 2:
                min_freqs.extend(_parse_packed_varints(value))
            elif wire_type == 0:
                min_freqs.append(value)
    if powers:
        rf['powers'] = powers
    if max_freqs:
        rf['max_freqs'] = max_freqs
    if min_freqs:
        rf['min_freqs'] = min_freqs
    return rf


# ==========================================================================
# DAV 链路层编解码器（DavLink2）
# 严格对应 C# DavLink2 (DavLink.cs:164-315)，技术方案 §3
# ==========================================================================

class DavLink2Codec:
    """DAV 链路层帧编解码器。

    帧格式（22 字节头 + payload + 2 字节 CRC16）：
      [0]=0xA5 Sync
      [1]=TxSeq
      [2:3]=DataLen(10bit) + Version(2bit)
      [4]=AckCount[7:2] + MsgType[1:0]
      [5:6]=ReceiveType
      [7:12]+[13低4位]=源地址(52bit)
      [13高4位]+[14:19]=目标地址(52bit)
      [20]=Reserved
      [21]=CRC8(header[0:21])
      [22:23]=MessageID(LE uint16) — 仅 Msg 类型
      [24:]=Payload — protobuf
      [End-2:]=CRC16(整帧除去 CRC16 自身)
    """

    HEADER_MARKER = 0xA5
    HEADER_LEN = 22
    MSG_TYPE_MSG = 0
    MSG_TYPE_ACK = 1

    def __init__(self, device_addr: int):
        self.device_addr = device_addr & 0xFFFFFFFFFFFFF  # 52-bit
        self._tx_seq = 0

    # ------------------------------------------------------------------
    # 编码
    # ------------------------------------------------------------------

    def encode_msg(self, msg_id: int, payload: bytes, ack_count: int = 0) -> bytes:
        """编码 Msg 类型帧（发送 protobuf 消息给地面站）。

        Args:
            msg_id: MessageID 枚举值
            payload: protobuf 序列化字节
            ack_count: ACK 序号（0 表示不需要 ACK）
        """
        data_len = 2 + len(payload)  # 2 字节 msg_id + protobuf 数据
        total = self.HEADER_LEN + data_len + 2  # +2 for CRC16
        buf = bytearray(total)

        # [0] Sync
        buf[0] = self.HEADER_MARKER
        # [1] TxSeq
        buf[1] = self._tx_seq
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        # [2:3] DataLen (10 bits) + Version (2 bits, =0)
        buf[2] = data_len & 0xFF
        buf[3] = ((data_len >> 8) & 0x3F)  # Version=0 in bits 6-7
        # [4] AckCount(6bit in bits 7-2) + MsgType(2bit in bits 1-0)
        buf[4] = ((ack_count << 2) & 0xFC)  # MsgType=0
        # [5:6] ReceiveType = 0
        # (already zero from bytearray)
        # [7:13] Source address (52-bit)
        self._put_source_addr(buf, self.device_addr)
        # [13:19] Destination address (52-bit, overlapping byte 13)
        self._put_dest_addr(buf, GROUND_ADDR)
        # [20] Reserved = 0
        # [21] CRC8 over bytes 0-20
        buf[21] = crc8(bytes(buf), 0, 21)
        # [22:23] MessageID (LE uint16)
        struct.pack_into('<H', buf, 22, msg_id)
        # [24:] Protobuf payload
        buf[24:24 + len(payload)] = payload
        # [End-2:] CRC16 over bytes 0..End-3
        c = crc16(bytes(buf), 0, self.HEADER_LEN + data_len)
        struct.pack_into('<H', buf, self.HEADER_LEN + data_len, c)

        return bytes(buf)

    def encode_ack(self, ack_count: int, report: int = 0) -> bytes:
        """编码 Ack 类型帧（响应地面站命令）。

        Args:
            ack_count: 收到的 Msg 的 ack_count（原值回传）
            report: 错误码（0 = DAV_NO_ERROR）
        """
        data_len = 4  # uint32 report
        total = self.HEADER_LEN + data_len + 2
        buf = bytearray(total)

        buf[0] = self.HEADER_MARKER
        buf[1] = self._tx_seq
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        buf[2] = data_len & 0xFF
        buf[3] = ((data_len >> 8) & 0x3F)
        buf[4] = ((ack_count << 2) & 0xFC) | 0x01  # MsgType=1 (Ack)

        self._put_source_addr(buf, self.device_addr)
        self._put_dest_addr(buf, GROUND_ADDR)

        buf[21] = crc8(bytes(buf), 0, 21)
        struct.pack_into('<I', buf, 22, report)  # report LE uint32

        c = crc16(bytes(buf), 0, self.HEADER_LEN + data_len)
        struct.pack_into('<H', buf, self.HEADER_LEN + data_len, c)

        return bytes(buf)

    def _put_source_addr(self, buf: bytearray, addr: int):
        """写入源地址（52-bit）到 byte 7-12 + byte 13 低 nibble。

        对应 DavLink2.cs:127-133
        """
        buf[7] = addr & 0xFF
        buf[8] = (addr >> 8) & 0xFF
        buf[9] = (addr >> 16) & 0xFF
        buf[10] = (addr >> 24) & 0xFF
        buf[11] = (addr >> 32) & 0xFF
        buf[12] = (addr >> 40) & 0xFF
        # byte 13 low nibble = source bits 48-51
        buf[13] = (addr >> 48) & 0x0F

    def _put_dest_addr(self, buf: bytearray, addr: int):
        """写入目标地址（52-bit）到 byte 13 高 nibble + byte 14-19。

        对应 DavLink2.cs:133-139
        """
        # byte 13 high nibble = dest bits 0-3
        buf[13] |= ((addr & 0x0F) << 4) & 0xF0
        buf[14] = (addr >> 4) & 0xFF
        buf[15] = (addr >> 12) & 0xFF
        buf[16] = (addr >> 20) & 0xFF
        buf[17] = (addr >> 28) & 0xFF
        buf[18] = (addr >> 36) & 0xFF
        buf[19] = (addr >> 44) & 0xFF

    # ------------------------------------------------------------------
    # 解码
    # ------------------------------------------------------------------

    def decode(self, data: bytes) -> Optional[dict]:
        """解析 DAV 帧。

        Returns:
            dict with keys: msg_type, ack_count, msg_id, payload, report
            或 None（校验失败）
        """
        if len(data) < self.HEADER_LEN + 2:
            return None
        if data[0] != self.HEADER_MARKER:
            return None

        # 解析 dataLen: byte[2] + ((byte[3] & 0x3F) << 8)
        # 技术方案 §3.2: dataLen = bytes[2] + ((bytes[3] & 0x3f) << 6)
        # 注：文档有疑，这里采用 << 8（与编码 >> 8 匹配，max=0xFF+0x300=1023）
        data_len = data[2] + ((data[3] & 0x3F) << 8)

        if len(data) < self.HEADER_LEN + data_len + 2:
            return None

        # CRC8 校验
        if data[21] != crc8(data, 0, 21):
            return None

        # CRC16 校验
        calc_crc = crc16(data, 0, self.HEADER_LEN + data_len)
        pkt_crc = struct.unpack_from('<H', data, self.HEADER_LEN + data_len)[0]
        if calc_crc != pkt_crc:
            return None

        ack_count = (data[4] >> 2) & 0x3F
        msg_type = data[4] & 0x03

        result = {'msg_type': msg_type, 'ack_count': ack_count}

        if msg_type == self.MSG_TYPE_MSG:
            result['msg_id'] = struct.unpack_from('<H', data, self.HEADER_LEN)[0]
            payload_start = self.HEADER_LEN + 2
            payload_len = data_len - 2
            result['payload'] = data[payload_start:payload_start + payload_len] if payload_len > 0 else b''
        else:  # Ack
            result['report'] = struct.unpack_from('<I', data, self.HEADER_LEN)[0]

        return result


# ==========================================================================
# 假 R2 电台主类
# ==========================================================================

# ═════════════════════════════════════════════════════════════════════
# RTCM3 差分帧构建（技术方案 §11：R2 电台作为差分数据源上行）
# ═════════════════════════════════════════════════════════════════════

def _crc24q(data: bytes) -> int:
    """CRC-24Q（RTCM3 标准校验：多项式 0x1864CFB，初始值 0，无反转）。"""
    crc = 0
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


def _rtcm_pack_bits(bits) -> bytes:
    """将 (值, 位数) 序列按大端位流打包，尾部补零到整字节。"""
    total = 0
    width = 0
    for value, nbits in bits:
        total = (total << nbits) | (value & ((1 << nbits) - 1))
        width += nbits
    pad = (-width) % 8
    total <<= pad
    return total.to_bytes((width + pad) // 8, 'big')


def _build_rtcm_frame(msg_number: int, payload: bytes) -> bytes:
    """组装 RTCM3 帧: 0xD3 + 10-bit 长度(=len(payload)) + payload + CRC-24Q。

    帧总长 = Length + 6；Length ≤ 1023（RTCM3 上限 1029 字节帧）。
    """
    if len(payload) > 1023:
        raise ValueError(f"RTCM payload 超长: {len(payload)} > 1023")
    head = bytes([0xD3, (len(payload) >> 8) & 0x03, len(payload) & 0xFF])
    body = head + payload
    crc = _crc24q(body)
    return body + bytes([(crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF])


def build_rtcm1005(station_id=1, gps_signal=1, glonass_signal=1,
                   galileo_signal=1, x_mm=0, y_mm=0, z_mm=0) -> bytes:
    """构建 RTCM3 1005 基准站 ARP 坐标帧（白名单帧，技术方案 §11.5.2）。

    DF022/DF023/DF024 为 GPS/GLONASS/Galileo 信号指示位（差分报文中的
    "信号状态"，可由 update_diff 运行时改写）；DF011/DF012/DF013 为基准站
    ARP 坐标（38 位补码毫米值）。位布局: DF002(12)+DF003(12)+DF021(6)+
    DF022(1)+DF023(1)+DF024(1)+DF001(1)+DF025(1)+DF141(2)+DF011(38)+
    DF012(38)+DF013(38) = 151 bit → 补零至 19 字节。
    """
    payload = _rtcm_pack_bits([
        (1005, 12),                              # DF002 消息号
        (station_id & 0xFFF, 12),                # DF003 基准站 ID
        (1, 6),                                  # DF021 ITRF 实现年份
        (1 if gps_signal else 0, 1),             # DF022 GPS 信号指示
        (1 if glonass_signal else 0, 1),         # DF023 GLONASS 信号指示
        (1 if galileo_signal else 0, 1),         # DF024 Galileo 信号指示
        (0, 1),                                  # DF001 保留
        (0, 1),                                  # DF025 天线高指示
        (0, 2),                                  # DF141 四分之一周期
        (int(x_mm) & ((1 << 38) - 1), 38),       # DF011 ARP X (mm, 38 位补码)
        (int(y_mm) & ((1 << 38) - 1), 38),       # DF012 ARP Y (mm)
        (int(z_mm) & ((1 << 38) - 1), 38),       # DF013 ARP Z (mm)
    ])
    return _build_rtcm_frame(1005, payload)


def build_rtcm1124(station_id=1) -> bytes:
    """构建 RTCM3 1124（BDS MSM4 观测值）链路模拟帧（白名单帧）。

    地面站准入只校验 CRC-24Q + 消息号白名单（§11.5.2），MSM4 观测语义由
    飞机端解析——掩码全零（无观测单元），本帧用于打通差分转发链路。
    位布局: DF002(12)+DF003(12)+DF004(30)+DF005(1)+DF006(3)+
    DF248 卫星掩码(64)+DF249 信号掩码(32) = 154 bit → 补零至 20 字节。
    """
    payload = _rtcm_pack_bits([
        (1124, 12),                              # DF002 消息号
        (station_id & 0xFFF, 12),                # DF003 基准站 ID
        (0, 30),                                 # DF004 BDS 星历时 (TOW)
        (0, 1),                                  # DF005 多消息标志
        (0, 3),                                  # DF006 IOD(SSR)
        (0, 64),                                 # DF248 BDS 卫星掩码
        (0, 32),                                 # DF249 BDS 信号掩码
    ])
    return _build_rtcm_frame(1124, payload)


def pack_single_bytes(msg: bytes) -> bytes:
    """SingleBytes protobuf 包装（§11.2.2）: field1(msg) = 0x0A + varint(len) + msg。"""
    n = len(msg)
    varint = b""
    while True:
        b7 = n & 0x7F
        n >>= 7
        varint += bytes([b7 | (0x80 if n else 0)])
        if not n:
            break
    return b"\x0a" + varint + msg


def unpack_single_bytes(payload: bytes) -> bytes:
    """解 SingleBytes 包装，返回 msg 字段（RTCM 原始字节）；格式不符原样返回。"""
    if len(payload) >= 2 and payload[0] == 0x0A:
        n = 0
        shift = 0
        pos = 1
        while pos < len(payload):
            b = payload[pos]
            n |= (b & 0x7F) << shift
            shift += 7
            pos += 1
            if not (b & 0x80):
                break
        return payload[pos:pos + n]
    return payload


def rtcm_summarize(data: bytes) -> str:
    """解析 RTCM3 字节流，返回摘要如 'RTCM 1005,1124 (2帧 57B)'；无有效帧返回 None。

    消息号提取对齐地面站 RTCM32.cs: msgId=(src[3]<<4)+(src[4]>>4)（src 含帧头）。
    """
    nums = []
    pos = 0
    while pos + 5 <= len(data) and data[pos] == 0xD3:
        length = data[pos + 2] + ((data[pos + 1] & 0x03) << 8)  # 不含 6 字节头尾
        total = length + 6
        if pos + total > len(data):
            break
        nums.append((data[pos + 3] << 4) + (data[pos + 4] >> 4))
        pos += total
    if not nums:
        return None
    return f"RTCM {','.join(str(n) for n in nums)} ({len(nums)}帧 {len(data)}B)"


class FakeR2RadioStation:
    """R2 假电台模拟器。

    完整生命周期（技术方案 §7.1）：
      1. 初始化网卡 IP + UDP socket
      2. 发送 EnrollRequest → 等待 EnrollReply
      3. 上线后每 2.5s 发送 RadioStationR2Heart 保持在线
      4. 响应地面站命令：SetRegulatoryDomain / SetEncryptKey /
         SetButtonParam / RadioSendRtcm（均需 3s 内回复 ACK）

    Parameters
    ----------
    device_id : int
        电台设备 ID（0-255），决定 DAV 地址 = 0xFFFFFFFFFF100 + device_id
    sub_device_type : int
        子型号：5=R2 双频, 3=R2G 单频 2.4G
    local_ip : str
        本机 IP（需在 DGCS 子网内）
    dgcs_ip : str
        DGCS 地面站 IP
    serial_number : str
        序列号
    product_name : str
        产品名
    firmware_version : str
        固件版本字符串
    interface : str
        Windows 网卡接口名（用于添加辅助 IP）
    """

    # 状态机
    STATE_INIT = 0
    STATE_ENROLLING = 1
    STATE_ONLINE = 2

    # 时序常量
    HEARTBEAT_INTERVAL = 2.5    # 心跳间隔（秒）
    ENROLL_TIMEOUT = 5.0        # 注册超时（秒）
    RECV_TIMEOUT = 1.0          # socket 接收超时（秒）
    LOOP_INTERVAL = 0.1         # 主循环轮询间隔（秒）
    DIFF_START_DELAY = 10.0     # 上线后差分起始延迟（秒，§11.2.4 地面站转发定时器 10s 后才启动）
    DIFF_INTERVAL = 1.0         # 差分上报周期（秒，§11.2.3 建议 1Hz；判活要求 ≥1 帧/2s）

    def __init__(
        self,
        device_id: int = 1,
        sub_device_type: int = SUB_DEVICE_R2_STATION,
        local_ip: str = FAKE_RADIO_IP,
        dgcs_ip: str = DGCS_IP,
        port: int = DAV_PORT,
        serial_number: str = None,
        product_name: str = "R2-SIMULATOR",
        firmware_version: str = "R2.1.0.0",
        interface: str = NETCARD_INTERFACE,
    ):
        self.device_id = device_id
        self.device_addr = RADIO_BASE_ADDR + device_id
        self.sub_device_type = sub_device_type
        self.local_ip = local_ip
        self.dgcs_ip = dgcs_ip
        self.port = port
        self.serial_number = serial_number or f"R2-SIM-{device_id:05d}"
        self.product_name = product_name
        self.firmware_version = firmware_version
        self.target_interface = interface

        # 内部状态
        self.state = self.STATE_INIT
        self.codec = DavLink2Codec(self.device_addr)
        self.sock: Optional[socket.socket] = None
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._last_hb = 0.0

        # 可被地面站命令修改的状态
        self._encrypt_type = 0
        self._encrypt_key = b""
        self._encrypt_iv = b""
        self._rf_params = self._build_default_rf()

        # 按键参数（SET_RADIO_BUTTON_PARAM 可修改，心跳 button_param 上报）
        self._button_param = {
            'long_click_time': [1000, 1000],
            'long_click_button_mode': [4, 4],  # 默认自定义(pause)
            'short_click_button_mode': [0, 0],
        }

        # 接收机模式（SET_RADIO_RECEIVER_MODE 可修改）
        self._receiver_mode = {
            'radio_850m_mode': 0,
            'radio_2g4_mode': 0,
            'radio_850m_binding_code': 0,
            'radio_2g4_binding_code': 0,
        }

        # 接收机 RC/电台参数（SET_RECEIVER_RC_AND_RADIO_PARAM 可修改）
        self._receiver_rc_radio = {
            'rc_binding_code': 0,
            'radio_binding_code': [],
            'receiver_radio_param': [],  # list[dict]，RFparameters
            'radio_id_enable_bit': [],
        }

        # ---- ACK 响应配置（对齐 fake_airplane.update_ack 语义）----
        # _ack_fail_count: 对所有 command 统一返回 report=4 的次数（0=禁用）
        self._ack_fail_count: int = 0
        # _ack_fail_counters: {command: current_count} — 各 command 已返回 report=4 的次数
        self._ack_fail_counters: dict = {}
        # _ack_fail_last_time: {command: timestamp} — 各 command 上次收到的时间
        self._ack_fail_last_time: dict = {}
        # _ack_silence_count: 对所有 command 统一不回复的次数（0=禁用）
        self._ack_silence_count: int = 0
        # _ack_silence_counters: {command: current_count} — 各 command 已静默的次数
        self._ack_silence_counters: dict = {}
        # _ack_silence_last_time: {command: timestamp} — 各 command 上次收到的时间
        self._ack_silence_last_time: dict = {}
        # _ack_cmd_result_enabled: 是否启用按 command 覆写 report
        self._ack_cmd_result_enabled: bool = False
        # _ack_cmd_result_map: {command: report} — 特定 command 的 ACK report 覆写值
        self._ack_cmd_result_map: dict = {}

        # 电池/温度（可运行时通过 set_battery 修改）
        self._battery_percentage = 85
        self._poe_voltage_mv = 12000
        self._charge_temperature = 30
        self._rf_800m_temperature = 35
        self._rf_2400m_temperature = 32

        # GPS 位置
        self._gps_latitude = 22.0
        self._gps_longitude = 113.0
        self._gps_altitude = 100.0

        # ---- 差分上报（技术方案 §11：R2 作为差分数据源，上行 RadioSendRtcm）----
        self._diff_enable = True             # 上线后自动外发差分（update_diff 可改）
        self._diff_signal_state = (1, 1, 1)  # RTCM 1005 帧 DF022/23/24：GPS/GLONASS/Galileo 信号指示位
        self._last_diff = 0.0                # 上次差分发送时刻
        self._online_since = None            # 上线时刻（差分 10s 起始延迟基准）

        # 在线状态（对外可读）
        self.online = False

    # ------------------------------------------------------------------
    # 默认 RF 参数
    # ------------------------------------------------------------------

    def _build_default_rf(self) -> dict:
        """构建默认 RF 参数（与心跳中 radio_rf_param 对应）。"""
        if self.sub_device_type == SUB_DEVICE_R2_STATION:
            # R2 双频：800M + 2.4G
            return {
                'band_800m': {
                    'mode': COUNTRY_CODE_R2_850M_930M,
                    'powers': [30, 30],
                    'max_freqs': [930000000, 930000000],
                    'min_freqs': [850000000, 850000000],
                    'temperature': 35,
                },
                'band_2400m': {
                    'mode': COUNTRY_CODE_R2_ISM2G4,
                    'powers': [20, 20],
                    'max_freqs': [2483500000, 2483500000],
                    'min_freqs': [2400123000, 2400123000],
                    'temperature': 32,
                },
            }
        else:
            # R2G 单频 2.4G（只有 band_2400m）
            return {
                'band_2400m': {
                    'mode': COUNTRY_CODE_R2_ISM2G4,
                    'powers': [20],
                    'max_freqs': [2483500000],
                    'min_freqs': [2400123000],
                    'temperature': 32,
                },
            }

    # ------------------------------------------------------------------
    # 网卡 IP 设置
    # ------------------------------------------------------------------

    def _ip_exists_locally(self, ip: str) -> bool:
        """检查 IP 是否已绑定到本机任意接口。"""
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

    def _setup_network(self) -> bool:
        """在指定网卡上添加辅助 IP（若尚不存在）。"""
        if self._ip_exists_locally(self.local_ip):
            logger.info(f"[RADIO] IP {self.local_ip} 已存在于本机接口，跳过添加")
            return True

        if not self.target_interface:
            logger.error("[RADIO] 未找到目标网络接口，无法添加辅助 IP")
            return False

        ps_cmd = (
            f'powershell -NoProfile -Command '
            f'"New-NetIPAddress -InterfaceAlias \'{self.target_interface}\' '
            f'-IPAddress \'{self.local_ip}\' -PrefixLength 24"'
        )
        logger.info(f"[RADIO] 在 {self.target_interface} 上添加辅助 IP: {self.local_ip}")
        ret = os.system(ps_cmd)
        if ret != 0:
            logger.error(f"[RADIO] New-NetIPAddress 执行失败，返回码: {ret}")
            return False
        return True

    # ------------------------------------------------------------------
    # UDP 通讯
    # ------------------------------------------------------------------

    def _udp_setup(self) -> bool:
        """创建并绑定 UDP socket。"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.settimeout(self.RECV_TIMEOUT)

        max_retries = 10
        for attempt in range(1, max_retries + 1):
            try:
                self.sock.bind((self.local_ip, self.port))
                logger.info(f"[RADIO] UDP socket 已绑定到 {self.local_ip}:{self.port}")
                logger.info(f"[RADIO] 目标地面站: {self.dgcs_ip}:{self.port}")
                return True
            except OSError as e:
                if hasattr(e, 'winerror') and e.winerror == 10049 and attempt < max_retries:
                    logger.info(f"[RADIO] IP 未生效，1s 后重试 ({attempt + 1}/{max_retries})")
                    time.sleep(1)
                else:
                    logger.error(f"[RADIO] 绑定 UDP socket 失败: {e}")
                    return False
        return False

    def _udp_send(self, data: bytes) -> bool:
        """发送 UDP 数据到地面站。"""
        if self.sock is None:
            return False
        try:
            self.sock.sendto(data, (self.dgcs_ip, self.port))
            return True
        except Exception as e:
            logger.error(f"[RADIO] UDP 发送失败: {e}")
            return False

    def _udp_recv(self) -> Optional[bytes]:
        """接收 UDP 数据（非阻塞，超时返回 None）。"""
        if self.sock is None:
            return None
        try:
            data, addr = self.sock.recvfrom(65535)
            return data
        except socket.timeout:
            return None
        except Exception as e:
            logger.error(f"[RADIO] UDP 接收失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """启动假电台：初始化网络 → UDP → 后台线程。"""
        if not self._setup_network():
            logger.error("[RADIO] 网络初始化失败")
            return False
        time.sleep(0.5)
        if not self._udp_setup():
            logger.error("[RADIO] UDP 初始化失败")
            return False

        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="FakeR2Radio")
        self._thread.start()
        logger.info(f"[RADIO] 假 R2 电台已启动 device_id={self.device_id} "
                     f"addr=0x{self.device_addr:013X} ip={self.local_ip}")
        return True

    def stop(self):
        """停止假电台：通知线程退出 → 关闭 socket。"""
        self.running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3)
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.online = False
        logger.info("[RADIO] 假 R2 电台已停止")

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def _run(self):
        """后台主循环：注册 → 心跳 + 处理地面站消息。"""
        # Phase 1: 注册
        if not self._do_enroll():
            logger.error("[RADIO] 注册失败，线程退出")
            return

        # Phase 2: 在线保持
        self.online = True
        self._last_hb = 0  # 立即发送首次心跳
        self._online_since = time.time()   # 差分起始延迟基准（§11.2.4：≥10s 再开始发）
        self._last_diff = 0.0
        logger.info("[RADIO] 已上线，进入心跳保持循环")

        while self.running:
            # 处理地面站下行消息
            self._handle_incoming()

            # 定时发送心跳
            now = time.time()
            if now - self._last_hb >= self.HEARTBEAT_INTERVAL:
                self._send_heartbeat()
                self._last_hb = now

            # 定时上报差分（上线 10s 后 1Hz，技术方案 §11）
            self._tick_diff(now)

            time.sleep(self.LOOP_INTERVAL)

    # ------------------------------------------------------------------
    # 差分上报（技术方案 §11：R2 作为差分数据源，上行 RadioSendRtcm）
    # ------------------------------------------------------------------

    def set_diff_enable(self, enable: bool):
        """设置差分外发开关（True=上线后自动 1Hz 上报差分）。"""
        self._diff_enable = bool(enable)
        if self._diff_enable:
            self._last_diff = 0.0   # 重新开启后立即恢复上报
        logger.info(f"[RADIO] 差分外发已{'开启' if self._diff_enable else '关闭'}")

    def set_diff_signal_state(self, gps_signal=1, glonass_signal=1, galileo_signal=1):
        """设置差分报文（RTCM 1005 帧）中的卫星信号指示位 DF022/DF023/DF024。"""
        self._diff_signal_state = (
            1 if gps_signal else 0,
            1 if glonass_signal else 0,
            1 if galileo_signal else 0,
        )
        logger.info(f"[RADIO] 差分信号状态已更新: GPS={self._diff_signal_state[0]} "
                    f"GLONASS={self._diff_signal_state[1]} "
                    f"Galileo={self._diff_signal_state[2]}")

    def _tick_diff(self, now):
        """差分上报调度：上线 ≥10s 后按 1Hz 上报（§11.2.3/§11.2.4）。"""
        if not self._diff_enable or not self.online or self._online_since is None:
            return
        if now - self._online_since < self.DIFF_START_DELAY:
            return
        if now - self._last_diff < self.DIFF_INTERVAL:
            return
        first = self._last_diff == 0.0
        self._send_diff()
        self._last_diff = now
        if first:
            logger.info(f"[RADIO] 差分上报已开始（上线 {self.DIFF_START_DELAY:.0f}s 后，1Hz）")

    def _send_diff(self):
        """上报一拍差分：RTCM(1005+1124) → SingleBytes 包装 → RadioSendRtcm(0x0100)。

        上行差分无需地面站 ACK（ackCount=0，§11.2.1）；每拍含白名单定位帧
        （§11.5.2），满足地面站来源判活条件（≥1 帧/2 秒，§11.4）。
        """
        gps_s, glo_s, gal_s = self._diff_signal_state
        rtcm = (build_rtcm1005(gps_signal=gps_s, glonass_signal=glo_s,
                               galileo_signal=gal_s)
                + build_rtcm1124())
        payload = pack_single_bytes(rtcm)
        frame = self.codec.encode_msg(MessageID.RADIO_SEND_RTCM, payload, ack_count=0)
        if self._udp_send(frame):
            logger.debug(f"[RADIO] 差分已上报 {len(rtcm)}B "
                         f"(信号状态 GPS={gps_s}/GLO={glo_s}/GAL={gal_s})")

    # ------------------------------------------------------------------
    # 注册流程（技术方案 §7.1 第 2-3 步）
    # ------------------------------------------------------------------

    def _do_enroll(self) -> bool:
        """发送 EnrollRequest，等待 EnrollReply。"""
        self.state = self.STATE_ENROLLING
        logger.info("[RADIO] 开始注册流程（EnrollRequest）")

        payload = build_enroll_request(self.serial_number, self.product_name)
        frame = self.codec.encode_msg(MessageID.ENROLL_REQUEST, payload)
        if not self._udp_send(frame):
            logger.error("[RADIO] 发送 EnrollRequest 失败")
            return False

        deadline = time.time() + self.ENROLL_TIMEOUT
        while time.time() < deadline and self.running:
            data = self._udp_recv()
            if data is None:
                continue

            decoded = self.codec.decode(data)
            if decoded is None:
                continue
            if decoded['msg_type'] != DavLink2Codec.MSG_TYPE_MSG:
                continue
            if decoded['msg_id'] != MessageID.ENROLL_REPLY:
                continue

            reply = parse_enroll_reply(decoded['payload'])
            if reply['accept_status'] == ENROLL_ACCEPTED:
                self.state = self.STATE_ONLINE
                logger.info(f"[RADIO] 注册成功 (accepted, heartbeat_interval={reply['heartbeat_interval_ms']}ms)")
                return True
            else:
                logger.error(f"[RADIO] 注册被拒绝: accept_status={reply['accept_status']}")
                return False

        logger.error(f"[RADIO] 注册超时（{self.ENROLL_TIMEOUT}s 未收到 EnrollReply）")
        return False

    # ------------------------------------------------------------------
    # 心跳
    # ------------------------------------------------------------------

    def _send_heartbeat(self):
        """发送 RadioStationR2Heart（MessageID=0x0204）。"""
        rf = self._rf_params
        band_800 = rf.get('band_800m', {})
        band_2400 = rf.get('band_2400m', {})

        kwargs = {
            'sub_device_type': self.sub_device_type,
            'firmware_version_alias': self.firmware_version,
            'device_id': self.device_id,
            'ethernet_ip': self.local_ip,
            'encrypt_type': self._encrypt_type,
            'battery_percentage': self._battery_percentage,
            'poe_voltage_mv': self._poe_voltage_mv,
            'charge_temperature': self._charge_temperature,
            'gps_latitude': self._gps_latitude,
            'gps_longitude': self._gps_longitude,
            'gps_altitude': self._gps_altitude,
            'button_long_click_times': self._button_param.get('long_click_time', [1000, 1000]),
            'button_long_click_modes': self._button_param.get('long_click_button_mode', [4, 4]),
            'button_short_click_modes': self._button_param.get('short_click_button_mode', [0, 0]),
        }

        if band_800:
            kwargs.update({
                'rf_800m_mode': band_800.get('mode', COUNTRY_CODE_R2_850M_930M),
                'rf_800m_powers': band_800.get('powers', [30, 30]),
                'rf_800m_max_freqs': band_800.get('max_freqs', [930000000, 930000000]),
                'rf_800m_min_freqs': band_800.get('min_freqs', [850000000, 850000000]),
                'rf_800m_temperature': self._rf_800m_temperature,
            })

        if band_2400:
            kwargs.update({
                'rf_2400m_mode': band_2400.get('mode', COUNTRY_CODE_R2_ISM2G4),
                'rf_2400m_powers': band_2400.get('powers', [20, 20]),
                'rf_2400m_max_freqs': band_2400.get('max_freqs', [2483500000, 2483500000]),
                'rf_2400m_min_freqs': band_2400.get('min_freqs', [2400123000, 2400123000]),
                'rf_2400m_temperature': self._rf_2400m_temperature,
            })

        payload = build_heartbeat(**kwargs)
        frame = self.codec.encode_msg(MessageID.SEND_RADIO_R2_HEARTBEAT, payload)
        self._udp_send(frame)
        logger.debug(f"[RADIO] 心跳已发送 device_id={self.device_id}")

    # ------------------------------------------------------------------
    # 地面站消息处理
    # ------------------------------------------------------------------

    def _handle_incoming(self):
        """非阻塞地处理地面站下行消息。"""
        # 一次主循环只处理少量消息，避免饥饿
        for _ in range(5):
            data = self._udp_recv()
            if data is None:
                break

            decoded = self.codec.decode(data)
            if decoded is None:
                continue
            if decoded['msg_type'] != DavLink2Codec.MSG_TYPE_MSG:
                # ACK 帧：地面站回复的 ACK，假电台当前不需要处理
                continue

            msg_id = decoded['msg_id']
            ack_count = decoded['ack_count']
            payload = decoded.get('payload', b'')

            if msg_id == MessageID.SET_RADIO_REGULATORY_DOMAIN:
                self._handle_config_command(msg_id, ack_count,
                                            lambda: self._on_set_domain(payload))
            elif msg_id == MessageID.SET_RADIO_ENCRYPT_KEY:
                self._handle_config_command(msg_id, ack_count,
                                            lambda: self._on_set_encrypt(payload))
            elif msg_id == MessageID.SET_RADIO_BUTTON_PARAM:
                self._handle_config_command(msg_id, ack_count,
                                            lambda: self._on_set_button(payload))
            elif msg_id == MessageID.SET_RADIO_RECEIVER_MODE:
                self._handle_config_command(msg_id, ack_count,
                                            lambda: self._on_set_receiver_mode(payload))
            elif msg_id == MessageID.SET_RECEIVER_RC_AND_RADIO_PARAM:
                self._handle_config_command(msg_id, ack_count,
                                            lambda: self._on_set_receiver_rc_radio(payload))
            elif msg_id == MessageID.RADIO_SEND_RTCM:
                self._handle_config_command(msg_id, ack_count)
            elif msg_id == MessageID.REMOTE_CONTROL_FREQ_MATCHING:
                self._handle_config_command(msg_id, ack_count)
            elif msg_id == MessageID.ASK_RADIO_ENCRYPT_KEY:
                # 查询加密密钥 → 回复 SEND_RADIO_ENCRYPT_KEY（携带当前状态）；ACK 走策略
                self._on_ask_encrypt_key()
                self._handle_config_command(msg_id, ack_count)
            elif msg_id == MessageID.ASK_RADIO_REGULATORY_DOMAIN:
                # 查询射频国家码/参数 → 回复 SEND_RADIO_REGULATORY_DOMAIN；ACK 走策略
                self._on_ask_regulatory_domain()
                self._handle_config_command(msg_id, ack_count)
            elif msg_id == MessageID.ASK_HEARTBEAT:
                # 地面站 1Hz AskHeartbeat，ackCount=0，无需回复
                # 我们的 2.5s 心跳已足够保持在线
                pass
            else:
                # 通用肯定 ACK 策略：其他带 ack_count 的配置指令一律回复
                # 肯定 ACK（report=0，DAV_NO_ERROR），ack_count 原值回传
                self._handle_config_command(msg_id, ack_count)

    # ------------------------------------------------------------------
    # 命令处理
    # ------------------------------------------------------------------

    def _on_set_domain(self, payload: bytes):
        """处理 SetRadioRegulatoryDomain（0x0203）。

        message RadioStationRegulatoryDomain {
            uint32 set_device_id = 1;
            repeated RFparameters set_rf_param = 2;   // [0]=800M, [1]=2.4G
        }
        message RFparameters {
            radioRegulatoryDomain rf_work_mode = 1;
            repeated uint32 rf_tx_power_dbm = 2;
            uint32 rf_temperature = 3;
            repeated uint32 rf_max_fre = 4;
            repeated uint32 rf_min_fre = 5;
        }
        解析后更新 _rf_params，下次心跳（SEND_RADIO_R2_HEARTBEAT）反映新值。
        """
        logger.info(f"[RADIO] 收到 SetRadioRegulatoryDomain (device_id={self.device_id})")
        rf_list = []
        for field_number, wire_type, value in _parse_proto_fields(payload):
            if field_number == 1 and wire_type == 0:
                logger.info(f"[RADIO] set_device_id = {value}")
            elif field_number == 2 and wire_type == 2:
                rf_list.append(_parse_rfparameters(value))

        if rf_list:
            band_keys = list(self._rf_params.keys())
            for idx, rf in enumerate(rf_list):
                if idx >= len(band_keys):
                    break
                band_key = band_keys[idx]
                band = self._rf_params[band_key]
                if 'mode' in rf:
                    band['mode'] = rf['mode']
                if 'powers' in rf:
                    band['powers'] = rf['powers']
                if 'max_freqs' in rf:
                    band['max_freqs'] = rf['max_freqs']
                if 'min_freqs' in rf:
                    band['min_freqs'] = rf['min_freqs']
                if 'temperature' in rf:
                    band['temperature'] = rf['temperature']
                    if band_key == 'band_800m':
                        self._rf_800m_temperature = rf['temperature']
                    elif band_key == 'band_2400m':
                        self._rf_2400m_temperature = rf['temperature']
            logger.info(f"[RADIO] RF 参数已更新: {self._rf_params}")

    def _on_set_encrypt(self, payload: bytes):
        """处理 SetRadioEncryptKey（0x0102）。

        message RadioEncryptKey {
            EncryptKey radio_key = 1;
            EncryptKey rc_key = 2;
        }
        message EncryptKey {
            uint32 encrypt_type = 1;
            bytes encrypt_key = 2;
            bytes encrypt_iv = 3;
        }
        解析 radio_key 的 encrypt_type/key/iv，更新心跳的 encrypt_type 字段。
        """
        logger.info(f"[RADIO] 收到 SetRadioEncryptKey (device_id={self.device_id})")
        for field_number, wire_type, value in _parse_proto_fields(payload):
            if field_number in (1, 2) and wire_type == 2:  # radio_key / rc_key
                ek = {}
                for fn, wt, v in _parse_proto_fields(value):
                    if fn == 1 and wt == 0:
                        ek['encrypt_type'] = v
                    elif fn == 2 and wt == 2:
                        ek['encrypt_key'] = v
                    elif fn == 3 and wt == 2:
                        ek['encrypt_iv'] = v
                if field_number == 1:  # radio_key → 本电台
                    if 'encrypt_type' in ek:
                        self._encrypt_type = ek['encrypt_type']
                    if 'encrypt_key' in ek:
                        self._encrypt_key = ek['encrypt_key']
                    if 'encrypt_iv' in ek:
                        self._encrypt_iv = ek['encrypt_iv']
                    logger.info(f"[RADIO] 加密参数已更新: type={self._encrypt_type}")

    def _on_set_button(self, payload: bytes):
        """处理 SetRadioButtonParam（0x0205）。

        message RadioButtonParam {
            repeated uint32 long_click_time = 1;          // 长按阈值 ms
            repeated uint32 long_click_button_mode = 2;   // 长按功能
            repeated uint32 short_click_button_mode = 3;  // 短按功能
        }
        解析后更新 _button_param，下次心跳的 button_param 反映新值。
        """
        logger.info(f"[RADIO] 收到 SetRadioButtonParam (device_id={self.device_id})")
        for field_number, wire_type, value in _parse_proto_fields(payload):
            if field_number == 1:
                self._button_param['long_click_time'] = (
                    _parse_packed_varints(value) if wire_type == 2 else [value]
                )
            elif field_number == 2:
                self._button_param['long_click_button_mode'] = (
                    _parse_packed_varints(value) if wire_type == 2 else [value]
                )
            elif field_number == 3:
                self._button_param['short_click_button_mode'] = (
                    _parse_packed_varints(value) if wire_type == 2 else [value]
                )
        logger.info(f"[RADIO] 按键参数已更新: {self._button_param}")

    def _on_set_receiver_mode(self, payload: bytes):
        """处理 SetRadioReceiverMode（0x0111）。

        message RadioReceiverMode {
            uint32 radio_850m_mode = 1;
            uint32 radio_2g4_mode = 2;
            uint32 radio_850m_binding_code = 3;
            uint32 radio_2g4_binding_code = 4;
        }
        """
        logger.info(f"[RADIO] 收到 SetRadioReceiverMode (device_id={self.device_id})")
        key_map = {1: 'radio_850m_mode', 2: 'radio_2g4_mode',
                   3: 'radio_850m_binding_code', 4: 'radio_2g4_binding_code'}
        for field_number, wire_type, value in _parse_proto_fields(payload):
            if wire_type == 0 and field_number in key_map:
                self._receiver_mode[key_map[field_number]] = value
        logger.info(f"[RADIO] 接收机模式已更新: {self._receiver_mode}")

    def _on_set_receiver_rc_radio(self, payload: bytes):
        """处理 SetReceiverRcAndRadioParam（0x0119）。

        message RadioReceiverRFparameters {
            uint32 rc_binding_code = 1;
            repeated uint32 radio_binding_code = 2;
            repeated RFparameters receiver_radio_param = 3;
            repeated uint32 radio_id_enable_bit = 4;
        }
        """
        logger.info(f"[RADIO] 收到 SetReceiverRcAndRadioParam (device_id={self.device_id})")
        params = self._receiver_rc_radio
        for field_number, wire_type, value in _parse_proto_fields(payload):
            if field_number == 1 and wire_type == 0:
                params['rc_binding_code'] = value
            elif field_number == 2:
                if wire_type == 2:
                    params['radio_binding_code'] = _parse_packed_varints(value)
                elif wire_type == 0:
                    params['radio_binding_code'].append(value)
            elif field_number == 3 and wire_type == 2:
                params['receiver_radio_param'].append(_parse_rfparameters(value))
            elif field_number == 4:
                if wire_type == 2:
                    params['radio_id_enable_bit'] = _parse_packed_varints(value)
                elif wire_type == 0:
                    params['radio_id_enable_bit'].append(value)
        logger.info(f"[RADIO] 接收机 RC/电台参数已更新: {params}")

    # ------------------------------------------------------------------
    # 查询指令响应
    # ------------------------------------------------------------------

    def _on_ask_encrypt_key(self):
        """处理 ASK_RADIO_ENCRYPT_KEY（0x0103），回复 SEND_RADIO_ENCRYPT_KEY（0x0104）。

        携带当前加密状态（encrypt_type / encrypt_key / encrypt_iv）。
        """
        logger.info(f"[RADIO] 收到 ASK_RADIO_ENCRYPT_KEY (device_id={self.device_id})")
        payload = build_send_encrypt_key(
            encrypt_type=self._encrypt_type,
            encrypt_key=self._encrypt_key,
            encrypt_iv=self._encrypt_iv,
        )
        frame = self.codec.encode_msg(MessageID.SEND_RADIO_ENCRYPT_KEY, payload)
        self._udp_send(frame)

    def _on_ask_regulatory_domain(self):
        """处理 ASK_RADIO_REGULATORY_DOMAIN（0x0201），回复 SEND_RADIO_REGULATORY_DOMAIN（0x0202）。

        携带当前射频参数（set_rf_param 两组：800M + 2.4G）。
        """
        logger.info(f"[RADIO] 收到 ASK_RADIO_REGULATORY_DOMAIN (device_id={self.device_id})")
        payload = build_send_regulatory_domain(self.device_id, self._rf_params)
        frame = self.codec.encode_msg(MessageID.SEND_RADIO_REGULATORY_DOMAIN, payload)
        self._udp_send(frame)

    # ------------------------------------------------------------------
    # ACK
    # ------------------------------------------------------------------

    def _ack_policy(self, msg_id: int):
        """判定本次命令的 ACK 响应策略，返回 (action, report)。

        action: 'silence'（静默不回复）/ 'fail'（失败注入）/ 'override'（命令 report 覆写）/ 'normal'（正常）
        report: 需要回复的 report 值（fail=4，override=指定值，normal=0；silence 忽略）

        各 command 独立计数，10s 未收到该 command 则计数器自动重置。
        """
        # 1) 检查 ACK 静默响应配置（各 command 独立计数和计时）
        if self._ack_silence_count > 0:
            now = time.time()
            counter = self._ack_silence_counters.get(msg_id, 0)
            last_time = self._ack_silence_last_time.get(msg_id, 0)
            # 该 command 10s 未出现 → 重置计数器
            if now - last_time > 10.0:
                counter = 0
            if counter < self._ack_silence_count:
                counter += 1
                self._ack_silence_counters[msg_id] = counter
                self._ack_silence_last_time[msg_id] = now
                return "silence", 0
            self._ack_silence_counters[msg_id] = counter
            self._ack_silence_last_time[msg_id] = now

        # 2) 检查 ACK 特定 command report 覆写配置
        if self._ack_cmd_result_enabled and msg_id in self._ack_cmd_result_map:
            return "override", self._ack_cmd_result_map[msg_id]

        # 3) 检查 ACK 失败响应配置（未被 cmd_result 覆写时才生效）
        if self._ack_fail_count > 0:
            now = time.time()
            counter = self._ack_fail_counters.get(msg_id, 0)
            last_time = self._ack_fail_last_time.get(msg_id, 0)
            # 该 command 10s 未出现 → 重置计数器
            if now - last_time > 10.0:
                counter = 0
            if counter < self._ack_fail_count:
                counter += 1
                self._ack_fail_counters[msg_id] = counter
                self._ack_fail_last_time[msg_id] = now
                return "fail", 4
            self._ack_fail_counters[msg_id] = counter
            self._ack_fail_last_time[msg_id] = now

        return "normal", 0

    def _handle_config_command(self, msg_id: int, ack_count: int, apply_fn=None):
        """处理带 ACK 的配置指令，按 update_ack 策略决定是否应用地面站的值 + 回复。

        - silence：不应用地面站的值 + 不回复（模拟电台无响应）
        - fail / override：不应用地面站的值 + 回复指定 report（模拟失败/结果覆写）
        - normal：应用地面站的值 + 回复 report=0

        apply_fn: 无参回调，仅 normal 时执行以应用地面站设置的值（如更新 _button_param）。
        """
        action, report = self._ack_policy(msg_id)
        if action == "silence":
            return  # 静默：不应用 + 不回复
        if action == "normal" and apply_fn is not None:
            apply_fn()  # 仅 normal 才应用地面站设置的值
        self._send_ack(ack_count, report)

    def _send_ack(self, ack_count: int, report: int = 0):
        """回复 ACK（技术方案 §3.7）。

        必须满足：msgType=1, ackCount 原值回传, report（默认 0 = DAV_NO_ERROR）。
        report 由调用方按 ``_ack_policy`` 策略计算（fail=4 / override=指定值 / normal=0）。
        """
        if ack_count == 0:
            return  # 不需要 ACK
        frame = self.codec.encode_ack(ack_count, report=report)
        self._udp_send(frame)
        logger.debug(f"[RADIO] ACK 已发送 ack_count={ack_count} report={report}")

    # ------------------------------------------------------------------
    # 公共接口：运行时修改参数
    # ------------------------------------------------------------------

    def set_encrypt_type(self, encrypt_type: int):
        """设置加密类型（0=none, 1=AES-128, 2=AES-256）。"""
        self._encrypt_type = encrypt_type

    def set_rf_band(self, band_key: str, mode: int = None,
                    powers: list = None, min_freqs: list = None,
                    max_freqs: list = None, temperature: int = None):
        """更新 RF 频段参数（band_key: 'band_800m' 或 'band_2400m'）。"""
        if band_key not in self._rf_params:
            return
        band = self._rf_params[band_key]
        if mode is not None:
            band['mode'] = mode
        if powers is not None:
            band['powers'] = list(powers)
        if min_freqs is not None:
            band['min_freqs'] = list(min_freqs)
        if max_freqs is not None:
            band['max_freqs'] = list(max_freqs)
        if temperature is not None:
            band['temperature'] = temperature
            if band_key == 'band_800m':
                self._rf_800m_temperature = temperature
            elif band_key == 'band_2400m':
                self._rf_2400m_temperature = temperature

    def set_battery(self, percentage: int = None, voltage_mv: int = None,
                    temperature: int = None):
        """更新电池/温度状态（下次心跳生效）。"""
        if percentage is not None:
            self._battery_percentage = percentage
        if voltage_mv is not None:
            self._poe_voltage_mv = voltage_mv
        if temperature is not None:
            self._charge_temperature = temperature

    def set_gps(self, latitude: float = None, longitude: float = None,
                altitude: float = None):
        """更新 GPS 位置（下次心跳生效）。"""
        if latitude is not None:
            self._gps_latitude = latitude
        if longitude is not None:
            self._gps_longitude = longitude
        if altitude is not None:
            self._gps_altitude = altitude


# ==========================================================================
# 批量假电台管理器
# ==========================================================================

class FakeRadioStationManager:
    """批量假电台管理器：一次性创建多台假电台。

    Usage::

        mgr = FakeRadioStationManager(count=2, start_device_id=1)
        mgr.start_all()
        ...
        mgr.stop_all()
    """

    def __init__(
        self,
        count: int = 1,
        start_device_id: int = 1,
        start_ip: str = FAKE_RADIO_IP,
        sub_device_type: int = SUB_DEVICE_R2_STATION,
        dgcs_ip: str = DGCS_IP,
        interface: str = NETCARD_INTERFACE,
    ):
        if count < 1:
            raise ValueError("count 必须 >= 1")

        base = tuple(int(p) for p in start_ip.split('.'))
        if base[3] + count - 1 > 255:
            raise ValueError(f"起始 IP {start_ip} 末段={base[3]} 数量={count} 超出 .255 边界")

        self.radios: list[FakeR2RadioStation] = []
        for i in range(count):
            ip = f"{base[0]}.{base[1]}.{base[2]}.{base[3] + i}"
            device_id = start_device_id + i
            radio = FakeR2RadioStation(
                device_id=device_id,
                sub_device_type=sub_device_type,
                local_ip=ip,
                dgcs_ip=dgcs_ip,
                interface=interface,
            )
            self.radios.append(radio)

    def start_all(self) -> bool:
        """启动所有假电台。"""
        ok = True
        for radio in self.radios:
            if not radio.start():
                logger.error(f"[RADIO-MGR] 电台 device_id={radio.device_id} 启动失败")
                ok = False
            time.sleep(0.5)  # 错开注册
        return ok

    def stop_all(self):
        """停止所有假电台。"""
        for radio in self.radios:
            radio.stop()


# ==========================================================================
# 内部 Socket 拦截器：包装假电台 socket，捕获收发数据传给 GUI 监控
# ==========================================================================

class _RadioSocketInterceptor:
    """包装 socket.socket，拦截 recvfrom / sendto 以捕获假电台收发数据。

    与 integrated_gui._config._SocketInterceptor 功能一致，但定义在本模块内，
    供 ``_FakeRadioSender.set_msg_injector`` 在 socket 延迟创建后就地包装
    （避免假电台 socket 创建时机晚于 ``_patch_transport_socket`` 而漏拦截）。
    """

    def __init__(self, real_sock, on_recv=None, on_send=None):
        self._sock = real_sock
        self._on_recv = on_recv
        self._on_send = on_send

    def recvfrom(self, *args, **kwargs):
        data, addr = self._sock.recvfrom(*args, **kwargs)
        if self._on_recv:
            try:
                self._on_recv(data, addr)
            except Exception:
                pass  # 回调异常绝不能影响主业务
        return data, addr

    def sendto(self, data, *args, **kwargs):
        result = self._sock.sendto(data, *args, **kwargs)
        if self._on_send:
            try:
                addr = args[0] if args else kwargs.get("address")
                self._on_send(data, addr)
            except Exception:
                pass  # 回调异常绝不能影响主业务
        return result

    def __getattr__(self, name):
        return getattr(self._sock, name)


# ==========================================================================
# GUI 适配层：将 FakeR2RadioStation 包装为 SimulationPanel 期望的接口
# ==========================================================================

class _FakeRadioSender:
    """GUI 适配包装器：将单个 FakeR2RadioStation 适配为 SimulationPanel
    所需的 sender 接口（thread / running / code / serial / _run / stop）。

    同时兼任 transport 角色（暴露 local_ip / local_port / close）。
    """

    def __init__(self, radio: FakeR2RadioStation):
        self._radio = radio
        # 暴露 transport 接口
        self.local_ip = radio.local_ip
        self.local_port = radio.port
        # 消息注入回调（UDP 监控）；sock 就绪后自动包装拦截器
        self._msg_injector = None  # Callable[[bytes,str,int,str,int],None] | None
        # 地面站地址（技术方案 §2.3：DGCS_IP=172.16.200.1, DAV_PORT=14555）
        self._gcs_ip = DGCS_IP
        self._gcs_port = DAV_PORT

    # -- sender 接口 -------------------------------------------------------

    @property
    def thread(self):
        return self._radio._thread

    @thread.setter
    def thread(self, value):
        self._radio._thread = value

    @property
    def running(self):
        return self._radio.running

    @running.setter
    def running(self, value):
        self._radio.running = value

    @property
    def code(self):
        return self._radio.device_id

    @property
    def serial(self):
        return self._radio.serial_number

    def _run(self):
        # 确保网络和 UDP 已初始化（GUI 的 _start_sender_thread 直接调用 _run，
        # 跳过了 start() 中的网络初始化步骤）
        if self._radio.sock is None:
            if not self._radio._setup_network():
                return
            time.sleep(0.5)
            if not self._radio._udp_setup():
                return
        # sock 已就绪：若有消息注入回调，自动包装拦截器（处理 sock 延迟创建）
        self._wrap_sock()
        self._radio._run()

    def set_msg_injector(self, callback):
        """设置消息注入回调，将假电台收发的原始数据转发到 UDP 监控。

        callback 签名: (data: bytes, src_ip: str, src_port: int,
                        dst_ip: str, dst_port: int) -> None

        若 socket 已就绪则立即包装拦截器；若尚未创建（延迟创建），
        将在 _run 中 socket 就绪后自动包装。
        """
        self._msg_injector = callback
        if callback is not None:
            self._wrap_sock()

    def _wrap_sock(self):
        """用 _RadioSocketInterceptor 包装 _radio.sock，收发数据经回调上报。"""
        real = self._radio.sock
        if real is None:
            return
        gcs_ip, gcs_port = self._gcs_ip, self._gcs_port
        dst_ip, dst_port = self.local_ip, self.local_port

        def _on_recv(data: bytes, sender_addr: tuple) -> None:
            # 接收方向：地面站 → 电台，src=地面站
            if self._msg_injector:
                self._msg_injector(data, gcs_ip, gcs_port, dst_ip, dst_port)

        def _on_send(data: bytes, target_addr: tuple) -> None:
            # 外发方向：电台 → 地面站，src/dst 反转
            if self._msg_injector:
                self._msg_injector(data, dst_ip, dst_port, gcs_ip, gcs_port)

        if isinstance(real, _RadioSocketInterceptor):
            real._on_recv = _on_recv
            real._on_send = _on_send
            return
        self._radio.sock = _RadioSocketInterceptor(real, _on_recv, _on_send)

    def stop(self):
        self._radio.stop()

    # -- transport 接口 ----------------------------------------------------

    def close(self):
        self._radio.stop()

    # -- update_xxx 方法（供 GUI 调参下拉框）--------------------------------

    def update_ack(self, fail_count=0, silence_count=0,
                   cmd_result_enable=False, cmd_result_commands=None,
                   cmd_result_values=None):
        """配置所有 command 的 ACK 响应行为（对齐 fake_airplane.update_ack）。

        支持三种模式（按优先级从高到低）：
        1. 静默（silence_count）：前 N 次不回复，之后回复 report=0。
        2. 特定 command report 覆写（cmd_result_*）：对指定 command 强制返回指定 report。
        3. 失败注入（fail_count）：前 N 次返回 report=4 (FAILED)，之后返回 report=0。

        各 command 独立计数，10s 未收到该 command 则其计数器自动重置为 0。

        Args:
            fail_count: 失败次数（>=0），设为 0 则禁用（始终返回 report=0）
            silence_count: 静默次数（>=0），设为 0 则禁用（始终立即回复）
            cmd_result_enable: 是否启用特定 command 的 report 覆写
            cmd_result_commands: 需要覆写 report 的 command（msg_id）列表
            cmd_result_values: 对应的 report 值列表。
                - 单元素列表：所有 command 都用此 report
                - 多元素列表：与 cmd_result_commands 一一对应（长度必须相等）
        """
        r = self._radio
        r._ack_fail_count = fail_count
        r._ack_fail_counters.clear()
        r._ack_fail_last_time.clear()
        r._ack_silence_count = silence_count
        r._ack_silence_counters.clear()
        r._ack_silence_last_time.clear()
        r._ack_cmd_result_enabled = cmd_result_enable
        r._ack_cmd_result_map.clear()
        if cmd_result_enable and cmd_result_commands:
            if cmd_result_values and len(cmd_result_values) == 1:
                # 单值广播：所有 command 用同一个 report
                value = cmd_result_values[0]
                for cmd in cmd_result_commands:
                    r._ack_cmd_result_map[int(cmd)] = int(value)
            elif cmd_result_values:
                # 一一对应
                for cmd, val in zip(cmd_result_commands, cmd_result_values):
                    r._ack_cmd_result_map[int(cmd)] = int(val)

    def update_battery(self, percentage: int = None, voltage_mv: int = None,
                       temperature: int = None):
        """更新电池/温度状态（下次心跳生效）。"""
        self._radio.set_battery(percentage=percentage, voltage_mv=voltage_mv,
                                temperature=temperature)

    def update_gps(self, latitude: float = None, longitude: float = None,
                   altitude: float = None):
        """更新 GPS 位置（下次心跳生效）。"""
        self._radio.set_gps(latitude=latitude, longitude=longitude,
                            altitude=altitude)

    def update_encrypt(self, encrypt_type: int = None):
        """设置加密类型（0=none, 1=AES-128, 2=AES-256）。"""
        if encrypt_type is not None:
            self._radio.set_encrypt_type(encrypt_type)

    def update_rf_band(self, band_key: str = None, mode: int = None,
                       powers: list = None, min_freqs: list = None,
                       max_freqs: list = None, temperature: int = None):
        """更新 RF 频段参数。band_key: 'band_800m' 或 'band_2400m'。"""
        if band_key is not None:
            self._radio.set_rf_band(band_key, mode=mode, powers=powers,
                                    min_freqs=min_freqs, max_freqs=max_freqs,
                                    temperature=temperature)

    def update_diff(self, enable: bool = True, gps_signal: int = 1,
                    glonass_signal: int = 1, galileo_signal: int = 1):
        """设置差分上报开关及差分报文中的卫星信号状态。

        假电台上线（Enrollment 成功）后自动向地面站 1Hz 上报差分
        （RadioSendRtcm 0x0100，上线 10s 后开始，技术方案 §11）。

        Args:
            enable: True=外发差分；False=停止外发（再次开启后立即恢复）
            gps_signal: RTCM 1005 帧 DF022 GPS 信号指示位（1=可用，0=不可用）
            glonass_signal: RTCM 1005 帧 DF023 GLONASS 信号指示位
            galileo_signal: RTCM 1005 帧 DF024 Galileo 信号指示位
        """
        self._radio.set_diff_enable(enable)
        self._radio.set_diff_signal_state(gps_signal, glonass_signal,
                                          galileo_signal)


class _FakeRadioSenders:
    """批量假电台管理器（GUI 适配层）。

    对应 _FakeAirplaneMessageSenders / _FakeNestSenders 的模式：
    - ``radio_senders``: list[_FakeRadioSender]
    - ``radios``: list[FakeR2RadioStation]（作为 transport 列表）
    """

    def __init__(self, count: int = 1, start_device_id: int = 1,
                 start_ip: str = FAKE_RADIO_IP,
                 sub_device_type: int = SUB_DEVICE_R2_STATION,
                 dgcs_ip: str = DGCS_IP,
                 interface: str = NETCARD_INTERFACE,
                 log_manager=None):
        if count < 1:
            raise ValueError("count 必须 >= 1")

        base = tuple(int(p) for p in start_ip.split('.'))
        if base[3] + count - 1 > 255:
            raise ValueError(
                f"起始 IP {start_ip} 末段={base[3]} 数量={count} 超出 .255 边界"
            )

        self.radio_senders: list[_FakeRadioSender] = []
        self.radios: list[_FakeRadioSender] = []

        for i in range(count):
            ip = f"{base[0]}.{base[1]}.{base[2]}.{base[3] + i}"
            device_id = start_device_id + i
            radio = FakeR2RadioStation(
                device_id=device_id,
                sub_device_type=sub_device_type,
                local_ip=ip,
                dgcs_ip=dgcs_ip,
                interface=interface,
            )
            sender = _FakeRadioSender(radio)
            self.radios.append(sender)
            self.radio_senders.append(sender)

    def stop(self):
        for sender in self.radio_senders:
            try:
                sender.stop()
            except Exception:
                pass


# ==========================================================================
# 主入口
# ==========================================================================

if __name__ == "__main__":
    log_manager = LogManager(log_dir="logs\\")

    # 创建单台 R2 双频假电台
    radio = FakeR2RadioStation(
        device_id=1,
        sub_device_type=SUB_DEVICE_R2_STATION,  # 5 = R2 双频
        local_ip=FAKE_RADIO_IP,
    )

    if not radio.start():
        logger.error("[RADIO] 启动失败，退出")
        sys.exit(1)

    logger.info(f"[RADIO] 假 R2 电台运行中 device_id={radio.device_id} "
                f"addr=0x{radio.device_addr:013X} ip={radio.local_ip}")
    logger.info("[RADIO] 按 Ctrl+C 停止...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("[RADIO] 正在停止...")
        radio.stop()
        logger.info("[RADIO] 已完全停止")
