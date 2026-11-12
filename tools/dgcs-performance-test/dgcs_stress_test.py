#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DGCS 地面站压力测试工具
========================
在本机网卡上添加多个 IP 别名，每架无人机 = 独立 IP + 端口 14551，
向地面站发送 MAVLink 心跳包并接收回复，验证地面站的大规模连接处理能力。

协议信息提取自 dmd_autotest_project:
  - 地面站默认: 172.16.200.1:14550  (config.json → Ground_Station)
  - 无人机端口: 14551              (config.json → V4.port)
  - Heartbeat (msg_id=0): <IBBBBB, crc_extra=50    (mavlink_config_v41.json)
  - Heartbeat_dmd (msg_id=1): <HB8BB, crc_extra=68  (地面站 → 无人机请求)
  - Identify_info (msg_id=2): <20B5B, crc_extra=0   (无人机 → 地面站应答)
  - MAVLink 帧: 0xFE + len + seq + sys_id + comp_id + msg_id + payload + CRC16_X25

交互流程（参考 fake_airplane.py）:
  1. 无人机 → heartbeat(msg_id=0) → 地面站
  2. 地面站发现后 → heartbeat_dmd(msg_id=1) → 该无人机 IP:14551
  3. 工具收到 msg_id=1 → 自动回复 identify_info(msg_id=2) 确认连接
  4. 地面站界面显示该飞机上线

IP 别名管理（同 fake_airplane.py 的 netsh 方式）:
  - 测试前: netsh interface ip add address ... 逐条添加 IP
  - 测试后: netsh interface ip delete address ... 逐条删除
  - 管理员权限必需

打包为 EXE:
  1. 环境要求: Windows + Python 3.10 + Npcap (IP/MAC 伪造依赖, https://npcap.com/#download)
  2. 在本目录下双击或命令行执行 build.bat
     - 自动 pip install pyinstaller + -r requirements.txt
     - 调用 PyInstaller --onefile --windowed 打包 dgcs_stress_test.py
     - --collect-all scapy  收集 scapy 全部子模块(运行期动态导入,否则打包后丢层)
     - 输出: 当前目录下的 DGCS_StressTest.exe (单文件, 约 57 MB)
     - 中间产物 build_temp/ 由脚本自行清理
  3. 运行 DGCS_StressTest.exe 需以管理员身份启动(管理网卡 IP 别名)
"""

import struct
import random
import time
import threading
import socket
import subprocess
import sys
import os
import math
import json
from collections import deque
from datetime import datetime, timedelta

# subprocess 默认用 locale 编码 (中文 Windows = GBK),但 powershell/netsh 输出可能含
# 非 GBK 字节 (Unicode 表情/UTF-8 BOM 等),导致 UnicodeDecodeError 抛到线程里;
# 而且 PowerShell 默认按 cp936 编码字节输出,Python 用 UTF-8 解码 → 网卡名 "以太网"
# 这种中文会乱码。这里 monkey-patch subprocess.run,统一:
#   1) text=True 时强制 encoding='utf-8' + errors='replace' (不抛异常)
#   2) powershell -Command "..." 调用,自动在命令最前面注入
#      [Console]::OutputEncoding=[Text.Encoding]::UTF8;
#      让 PowerShell 用 UTF-8 编码字节输出,与 Python 的 UTF-8 解码对齐,彻底解决中文乱码。
_orig_subprocess_run = subprocess.run
_PS_UTF8_PREFIX = '[Console]::OutputEncoding=[Text.Encoding]::UTF8; '

def _safe_subprocess_run(*args, **kwargs):
    if kwargs.get('text') or kwargs.get('universal_newlines'):
        kwargs.setdefault('encoding', 'utf-8')
        kwargs.setdefault('errors', 'replace')
    if args and isinstance(args[0], (list, tuple)):
        cmd_list = list(args[0])
        if cmd_list and str(cmd_list[0]).lower().rstrip('.exe') == 'powershell':
            if '-Command' in cmd_list:
                idx = cmd_list.index('-Command')
                if idx + 1 < len(cmd_list) and isinstance(cmd_list[idx + 1], str) \
                        and not cmd_list[idx + 1].startswith(_PS_UTF8_PREFIX):
                    cmd_list[idx + 1] = _PS_UTF8_PREFIX + cmd_list[idx + 1]
                    args = (cmd_list,) + tuple(args[1:])
    return _orig_subprocess_run(*args, **kwargs)
subprocess.run = _safe_subprocess_run

# =====================================================================
# 工具版本号 (UI 显示 + 排查用)
# =====================================================================
TOOL_VERSION = "2.1.1"

# 地面站 Online 超时 — 对齐 dgcs4 DebugConfig.UdpTimeout 默认值 6000ms
# 地面站每 1Hz tick 检查: 若 (now - LastOnlineTime) > udpTimeout 则置 DISCONNECTED
# 工具据此在 6s 内未收到 GCS 心跳/业务消息时清零对应标志, 让显示跟随地面站抖动
GCS_ONLINE_TIMEOUT_S = 6.0

# 集群通信端口 (master 监听, slave 连接) — TCP + 行分隔 JSON
CLUSTER_PORT = 19999

# =====================================================================
# MAVLink CRC (X.25) — 提取自 parse_mavlink.py
# =====================================================================
def mavlink_crc(data: bytes, crc_extra: int) -> int:
    crc = 0xffff
    for b in data:
        tmp = b ^ (crc & 0xff)
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        crc = (crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)
    tmp = crc_extra ^ (crc & 0xff)
    tmp = (tmp ^ (tmp << 4)) & 0xFF
    crc = (crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)
    return crc & 0xffff


# =====================================================================
# MAVLink 消息构建 — 提取自 mavlink_config_v41.json + DGCS4 dmd_uav_codec.generated.cs
# =====================================================================
HB_CRC = 50            # msg_id=0: <IBBBBB, 9 bytes
HB_DMD_CRC = 68        # msg_id=1: <HB8BB, 12 bytes
ID_CRC = 0             # msg_id=2: <20B5B, 25 bytes
GET_ID_CRC = 79        # msg_id=3: <BB, 2 bytes
PS_CRC = 90            # msg_id=5: packed_state, 106 bytes
FS_CRC = 72            # msg_id=6: failsafe, 2 bytes (dmd_uav_codec.generated.cs:59)
ES_CRC = 155           # msg_id=8: extend_state
RAW_IMU_CRC = 144      # msg_id=27: raw_imu, 26 bytes (dmd_uav_codec.generated.cs:73)
PRLA_CRC = 165         # msg_id=24: param_request_list_ack, 1 byte
RCS_CRC = 51           # msg_id=59: remaining_capacity_state, 19 bytes

# MAV_AUTOPILOT enum (from DGCS4 CommonType/Utils/Types.cs)
MAV_AUTOPILOT_DMD_FC = 20   # flight controller — shows as FC_WORKING (fully online)
MAV_AUTOPILOT_DMD_COM = 21  # companion module — shows as WORKING only
MAV_AUTOPILOT_DMD_GCS = 22  # ground station

# 飞控心跳参数（对齐 dmd_uav mav_channel.cpp:195-215）
HB_COMPID = 1              # 飞控默认 comp_id=1（200 是 MT793 companion 用，不适用于飞机本体）
HB_TYPE_QUADROTOR = 2      # MAV_TYPE_QUADROTOR
HB_BASE_MODE_DISARM = 0    # 解锁前
HB_BASE_MODE_ARMED = 89    # custom+armed（bit0=custom, bit3=armed, bit4+bit6=HIL+manual）
HB_SYS_STATUS_ACTIVE = 4   # MAV_STATE_ACTIVE (mav_channel.cpp:210)
MAV_VERSION_1 = 3          # MAVLINK_VERSION (mav_channel.cpp:212)

def build_heartbeat(sys_id: int, seq: int,
                    autopilot: int = MAV_AUTOPILOT_DMD_FC,
                    type_: int = HB_TYPE_QUADROTOR, base_mode: int = HB_BASE_MODE_DISARM,
                    custom_mode: int = 0, system_status: int = HB_SYS_STATUS_ACTIVE,
                    mavlink_version: int = MAV_VERSION_1,
                    comp_id: int = HB_COMPID) -> bytes:
    """构建 heartbeat (msg_id=0), 9 字节 payload

    默认值对齐 dmd_uav mav_channel.cpp:195-215:
      type=QUADROTOR(2), autopilot=DMD_FC(20), base_mode=0,
      system_status=ACTIVE(4), mavlink_version=3
    """
    payload = struct.pack('<IBBBBB',
                          custom_mode & 0xFFFFFFFF, type_ & 0xFF,
                          autopilot & 0xFF, base_mode & 0xFF,
                          system_status & 0xFF, mavlink_version & 0xFF)
    header = struct.pack('BBBBBB', 0xFE, 9, seq & 0xFF, sys_id & 0xFF, comp_id & 0xFF, 0)
    crc = mavlink_crc(header[1:] + payload, HB_CRC)
    return header + payload + struct.pack('<H', crc)


def build_identify_info(sys_id: int, seq: int, serial: bytes = None, code: bytes = None) -> bytes:
    """构建 identify_info (msg_id=2), 25 字节 payload (serial=20B + code=5B)

    DGCS4 Deserialize_IDENTIFY_INFO 严格按 offset+0..20 读 serial、offset+20..25 读 code。
    若 payload 不是正好 25 字节,GCS 读 code[20:25] 会读到 CRC 字节,SN/Code 字段错乱。
    serial/code 可传 bytes 覆盖默认值 (会被截断/补零到 20/5 字节)。
    """
    if serial is None:
        serial = (f'DMDTEST{sys_id:013d}').encode()   # 7+13=20 字节
    if code is None:
        # 默认 code 用 4 位数字 (DGCS4 把 code 当作 DisplayId 显示在 UI 的 ID 字段)
        code = f'{sys_id:04d}'.encode()                # 4 字节
    serial = serial[:20].ljust(20, b'\x00')
    code = code[:5].ljust(5, b'\x00')
    payload = serial + code
    assert len(payload) == 25, f'identify_info payload 必须 25 字节,实际 {len(payload)}'
    header = struct.pack('BBBBBB', 0xFE, len(payload), seq & 0xFF, sys_id & 0xFF, 1, 2)
    crc = mavlink_crc(header[1:] + payload, ID_CRC)
    return header + payload + struct.pack('<H', crc)


def build_packed_state(sys_id: int, seq: int,
                       lat: int = 0, lon: int = 0, alt: int = 0,
                       tar_lat: int = None, tar_lon: int = None, tar_alt: int = None,
                       ssid: bytes = b'dmd\x00\x00\x00\x00\x00',
                       voltage: int = 16277, batt_pct: int = 85,
                       fix_type: int = 3, satellites: int = 15,
                       armed: int = 0, mode: int = 0,
                       fly_state: int = 0, wifi_up: int = -40,
                       bat_serial: bytes = b'V4S24101\x00\x00\x00',
                       sensor_health: int = 3583,
                       sensor_health_middle: int = 0,
                       sensor_health_extend: int = 0,
                       rc_matching_code: int = 0,
                       uav_speed_horz: int = 0, uav_speed_vert: int = 0,
                       elevation: int = 0,
                       light_r: int = 0, light_g: int = 0, light_b: int = 0,
                       play_state: int = 0,
                       eph: int = 90, mav_up_rate: int = 3,
                       rtk_quality: int = 2,
                       rtk_radio_850m: int = 72,
                       rtk_radio_2g4: int = 72,
                       rc_radio: int = 90,
                       wind_speed_x: int = 0, wind_speed_y: int = 0,
                       fence_origin_set: int = 1, home_set: int = 1,
                       auth_constraint: int = 1) -> bytes:
    """构建 packed_state (msg_id=5), 106 字节 payload

    字段布局来自 DGCS4 dmd_uav_codec.generated.cs Serialize_PACKED_STATE():
      offset  size  field
      0       4     seq (U32 LE)
      4       4     cur_lat (U32 LE, lat * 1e7)
      8       4     cur_lon (U32 LE, lon * 1e7)
      12      4     cur_alt (U32 LE, alt_mm)
      16      4     tar_lat
      20      4     tar_lon
      24      4     tar_alt
      28      2     sensor_health (U16 LE)
      30      2     voltage_battery (U16 LE, mV)
      32      2     voltage_battery_percent (U16 LE)
      34      2     eph (U16 LE, hdop * 100)
      36      1     wifi_up (s8, dBm)
      37      1     mav_up_rate (u8)
      38      8     ssid (u8[8])
      46      1     fix_type
      47      1     satellites_visible
      48      1     rtk_quality
      49      1     armed
      50      1     mode
      51      1     auth_constraint
      52      1     fence_origin_set
      53      1     home_set
      54      1     fly_state
      55      1     rtk_radio_850m
      56      1     rc_radio
      57      1     light_r
      58      1     light_g
      59      1     light_b
      60      1     play_state
      61      1     drama_state
      62      2     voltage_battery_diff (U16 LE)
      64      2     voltage_battery_history_diff (U16 LE)
      66      1     restart_flag
      67     10     bat_serial_prefix (u8[10])
      77      2     wind_speed_x (s16 LE, cm/s)
      79      2     wind_speed_y (s16 LE, cm/s)
      81      1     uwb_group (s8)
      82      4     bat_serial_suffix (u8[4])
      86      1     bat_serial_need_reset
      87      1     time_need_reset
      88      4     elevation (s32 LE, mm)
      92      1     boot_need_update
      93      1     charge_state
      94      1     lightpanel_state
      95      2     sensor_health_middle (U16 LE)
      97      2     rc_matching_code (U16 LE)
      99      2     uav_speed_horz (s16 LE, cm/s)
      101     2     uav_speed_vert (s16 LE, cm/s)
      103     2     sensor_health_extend (U16 LE)
      105     1     rtk_radio_2g4
    Total: 106 bytes
    """
    buf = bytearray(106)

    def pu32(off, val): struct.pack_into('<I', buf, off, int(val) & 0xFFFFFFFF)
    def pu16(off, val): struct.pack_into('<H', buf, off, int(val) & 0xFFFF)
    def ps16(off, val): struct.pack_into('<h', buf, off, int(val))
    def ps32(off, val): struct.pack_into('<i', buf, off, int(val))
    def pu8(off, val):  buf[off] = int(val) & 0xFF
    def ps8(off, val):  buf[off] = int(val) & 0xFF
    def pbytes(off, data): buf[off:off + len(data)] = data[:len(data)]

    pu32(0, seq)
    pu32(4, lat)         # cur_lat
    pu32(8, lon)         # cur_lon
    pu32(12, alt)        # cur_alt (mm)
    pu32(16, tar_lat if tar_lat is not None else lat)        # tar_lat
    pu32(20, tar_lon if tar_lon is not None else lon)        # tar_lon
    pu32(24, tar_alt if tar_alt is not None else alt)        # tar_alt
    pu16(28, sensor_health)
    pu16(30, voltage)    # voltage_battery (mV)
    pu16(32, batt_pct)   # voltage_battery_percent
    pu16(34, eph)        # eph (hdop * 100)
    ps8(36, wifi_up)     # wifi_up (dBm, signed)
    pu8(37, mav_up_rate)
    pbytes(38, ssid)
    pu8(46, fix_type)
    pu8(47, satellites)
    pu8(48, rtk_quality)
    pu8(49, armed)
    pu8(50, mode)
    pu8(51, auth_constraint)
    pu8(52, fence_origin_set)
    pu8(53, home_set)
    pu8(54, fly_state)
    pu8(55, rtk_radio_850m)
    pu8(56, rc_radio)
    pu8(57, light_r)     # light_r
    pu8(58, light_g)     # light_g
    pu8(59, light_b)     # light_b
    pu8(60, play_state)  # play_state
    pu8(61, 0)           # drama_state
    pu16(62, 0)          # voltage_battery_diff
    pu16(64, 0)          # voltage_battery_history_diff
    pu8(66, 0)           # restart_flag
    pbytes(67, bat_serial)
    ps16(77, wind_speed_x)   # wind_speed_x (cm/s)
    ps16(79, wind_speed_y)   # wind_speed_y (cm/s)
    ps8(81, 0)           # uwb_group
    pbytes(82, b'\x00\x00\x00\x00')  # bat_serial_suffix
    pu8(86, 0)           # bat_serial_need_reset
    pu8(87, 0)           # time_need_reset
    ps32(88, elevation)  # elevation (mm)
    pu8(92, 0)           # boot_need_update
    pu8(93, 0)           # charge_state
    pu8(94, 0)           # lightpanel_state
    pu16(95, sensor_health_middle)   # sensor_health_middle
    pu16(97, rc_matching_code)       # rc_matching_code
    ps16(99, uav_speed_horz)         # uav_speed_horz
    ps16(101, uav_speed_vert)        # uav_speed_vert
    pu16(103, sensor_health_extend)  # sensor_health_extend
    pu8(105, rtk_radio_2g4)

    header = struct.pack('BBBBBB', 0xFE, 106, seq & 0xFF, sys_id & 0xFF, 1, 5)
    crc = mavlink_crc(header[1:] + bytes(buf), PS_CRC)
    return header + bytes(buf) + struct.pack('<H', crc)


def build_extend_state(sys_id: int, seq: int,
                       roll: float = 0.0, pitch: float = 0.0, yaw: float = 0.0,
                       battery_time: int = 80,
                       temp_imu: float = 28.5, temp_baro: float = 26.0,
                       temp_batt: float = 32.0,
                       param_hash: int = 0, anchor_hash: int = 0,
                       battery_capability: int = 3500,
                       battery_used_times: int = 12,
                       cell1: int = 4070, cell2: int = 4065,
                       cell3: int = 4078, cell4: int = 4062,
                       fc_ver: bytes = b'4.1.0\x00\x00\x00',
                       companion_ver: bytes = b'4.2.0\x00\x00\x00',
                       battery_ver: bytes = b'3.0\x00\x00\x00\x00\x00',
                       gps_ver: bytes = b'2.1\x00\x00\x00\x00\x00',
                       tele_ver: bytes = b'1.5\x00',
                       bms_ver: bytes = b'1.2\x00',
                       rid_ver: bytes = b'1.0\x00\x00\x00\x00\x00',
                       gimbal_ver: bytes = b'1.0\x00',
                       servo_ver: int = 0,
                       voltage_rid_bat: int = 3700,
                       uas_code: bytes = b'') -> bytes:
    """构建 extend_state (msg_id=8), 用于回复 heartbeat_dmd.extend==1

    字段布局来自 DGCS4 dmd_uav_codec.generated.cs Serialize_EXTEND_STATE():
      offset  size  field
      0       4     roll (f32 LE, rad)
      4       4     pitch (f32 LE, rad)
      8       4     yaw (f32 LE, rad)
      12      4     battery_time (U32 LE, s)
      16      4     temp_imu (f32 LE, °C)
      20      4     temp_baro (f32 LE, °C)
      24      4     temp_batt (f32 LE, °C)
      28      4     param_hash (U32 LE)
      32      4     anchor_hash (U32 LE)
      36      2     battery_capability (U16 LE, mAh)
      38      2     battery_used_times (U16 LE)
      40      2     voltage_battery_cell1 (U16 LE, mV)
      42      2     voltage_battery_cell2 (U16 LE, mV)
      44      2     voltage_battery_cell3 (U16 LE, mV)
      46      2     voltage_battery_cell4 (U16 LE, mV)
      48      8     flight_controller_version (u8[8])
      56      8     companion_version (u8[8])
      64      8     battery_version (u8[8])
      72      8     gps_version (u8[8])
      80      1     servo_ver (u8)
      81      4     tele_version (u8[4])
      85      4     bms_version (u8[4])
      89      8     rid_version (u8[8])
      97      4     gimbal_version (u8[4])
      101     2     voltage_rid_bat (U16 LE, mV)
      103     20    uas_code (u8[20])
    Total: 123 bytes
    """
    buf = bytearray(123)
    struct.pack_into('<fff', buf, 0, roll, pitch, yaw)
    struct.pack_into('<I', buf, 12, battery_time & 0xFFFFFFFF)
    struct.pack_into('<fff', buf, 16, temp_imu, temp_baro, temp_batt)
    struct.pack_into('<II', buf, 28, param_hash & 0xFFFFFFFF, anchor_hash & 0xFFFFFFFF)
    struct.pack_into('<HH', buf, 36, battery_capability & 0xFFFF, battery_used_times & 0xFFFF)
    struct.pack_into('<HHHH', buf, 40, cell1 & 0xFFFF, cell2 & 0xFFFF,
                     cell3 & 0xFFFF, cell4 & 0xFFFF)
    buf[48:56] = (fc_ver or b'')[:8].ljust(8, b'\x00')
    buf[56:64] = (companion_ver or b'')[:8].ljust(8, b'\x00')
    buf[64:72] = (battery_ver or b'')[:8].ljust(8, b'\x00')
    buf[72:80] = (gps_ver or b'')[:8].ljust(8, b'\x00')
    buf[80] = servo_ver & 0xFF
    buf[81:85] = (tele_ver or b'')[:4].ljust(4, b'\x00')
    buf[85:89] = (bms_ver or b'')[:4].ljust(4, b'\x00')
    buf[89:97] = (rid_ver or b'')[:8].ljust(8, b'\x00')
    buf[97:101] = (gimbal_ver or b'')[:4].ljust(4, b'\x00')
    struct.pack_into('<H', buf, 101, voltage_rid_bat & 0xFFFF)
    buf[103:123] = (uas_code or b'')[:20].ljust(20, b'\x00')

    header = struct.pack('BBBBBB', 0xFE, 123, seq & 0xFF, sys_id & 0xFF, 1, 8)
    crc = mavlink_crc(header[1:] + bytes(buf), ES_CRC)
    return header + bytes(buf) + struct.pack('<H', crc)


def build_param_request_list_ack(sys_id: int, seq: int, result: int = 0) -> bytes:
    """构建 param_request_list_ack (msg_id=24), 1 字节 payload
    参考 DGCS4 Msg_param_request_list_ack: result (byte)
    """
    payload = struct.pack('B', result & 0xFF)
    header = struct.pack('BBBBBB', 0xFE, 1, seq & 0xFF, sys_id & 0xFF, 1, 24)
    crc = mavlink_crc(header[1:] + payload, PRLA_CRC)
    return header + payload + struct.pack('<H', crc)


def build_remaining_capacity_state(sys_id: int, seq: int,
                                    remain_fly_time: int = 1500,
                                    battery_total: int = 3700,
                                    battery_remain: int = 2800,
                                    battery_pct: int = 85) -> bytes:
    """构建 remaining_capacity_state (msg_id=59), 19 字节 payload
    参考 DGCS4 Deserialize_REMAINING_CAPACITY_STATE / FakeUavParser.SendBatteryExtendInfo
    格式: <fHHHHHHHB = 4+2+2+2+2+2+2+2+1 = 19 bytes
    """
    payload = struct.pack('<fHHHHHHHB',
                          50.0,          # safe_fly_radius (f32)
                          remain_fly_time & 0xFFFF,  # remain_fly_time (u16) — 秒
                          0,             # go_home_need_time (u16)
                          0,             # land_need_time (u16)
                          0,             # go_home_need_capacity (u16)
                          0,             # land_need_capacity (u16)
                          battery_total & 0xFFFF,    # battery_total_capaticy (u16) — mAh
                          battery_remain & 0xFFFF,   # battery_remain_capaticy (u16) — mAh
                          battery_pct & 0xFF)        # battry_capacity_percentage (u8)
    header = struct.pack('BBBBBB', 0xFE, 19, seq & 0xFF, sys_id & 0xFF, 1, 59)
    crc = mavlink_crc(header[1:] + payload, RCS_CRC)
    return header + payload + struct.pack('<H', crc)


def build_failsafe(sys_id: int, seq: int, failsafe: int = 0,
                   comp_id: int = HB_COMPID) -> bytes:
    """构建 failsafe (msg_id=6), 2 字节 payload

    位掩码 (dmd_uav mav_channel.cpp:3917-3927):
      bit0=EkfStab | bit1=EkfHorz | bit2=EkfVert | bit3=Crash | bit4=Radio
      bit5=Battery | bit6=FenceAlt | bit7=FenceCircle | bit8=Waypoint
      bit9=TooFar | bit10=StaticDist | bit12=DramaFail/TkFail
      bit13=Igniter | bit14=SensorFail/FenceCircle2 | bit15=ImuRisk

    飞控/FakeUav 都 1Hz 主动上报（failsafe != 0 时）。
    """
    payload = struct.pack('<H', failsafe & 0xFFFF)
    header = struct.pack('BBBBBB', 0xFE, 2, seq & 0xFF, sys_id & 0xFF, comp_id & 0xFF, 6)
    crc = mavlink_crc(header[1:] + payload, FS_CRC)
    return header + payload + struct.pack('<H', crc)


def build_raw_imu(sys_id: int, seq: int,
                  time_usec: int = 0,
                  xacc: int = 0, yacc: int = 0, zacc: int = 0,
                  xgyro: int = 0, ygyro: int = 0, zgyro: int = 0,
                  xmag: int = 0, ymag: int = 0, zmag: int = 0,
                  comp_id: int = HB_COMPID) -> bytes:
    """构建 raw_imu (msg_id=27), 26 字节 payload <Q9h

    用途：地面站 IMU 调试图表。FakeUav 按 SR0_SNSR_RAW 参数倍数多发。
    """
    payload = struct.pack('<Q9h',
                          time_usec & 0xFFFFFFFFFFFFFFFF,
                          xacc, yacc, zacc,
                          xgyro, ygyro, zgyro,
                          xmag, ymag, zmag)
    header = struct.pack('BBBBBB', 0xFE, 26, seq & 0xFF, sys_id & 0xFF, comp_id & 0xFF, 27)
    crc = mavlink_crc(header[1:] + payload, RAW_IMU_CRC)
    return header + payload + struct.pack('<H', crc)


# =====================================================================
# 启动自检 — 校验所有消息生成器输出与 DGCS4 codec 期望逐字节一致
# =====================================================================
# (msg_name, expected_payload_size, expected_msg_id, builder)
_SELFTEST_CASES = [
    ('heartbeat',                  9, 0,  lambda: build_heartbeat(1, 1)),
    ('packed_state',             106, 5,  lambda: build_packed_state(1, 1)),
    ('extend_state',             123, 8,  lambda: build_extend_state(1, 1)),
    ('identify_info',             25, 2,  lambda: build_identify_info(1, 1)),
    ('failsafe',                   2, 6,  lambda: build_failsafe(1, 1)),
    ('remaining_capacity_state',  19, 59, lambda: build_remaining_capacity_state(1, 1)),
    ('raw_imu',                   26, 27, lambda: build_raw_imu(1, 1)),
    ('param_request_list_ack',    1, 24, lambda: build_param_request_list_ack(1, 1)),
]


def run_selftest() -> dict:
    """启动自检: 构造每种 MAVLink 消息, 校验
       - 总长度 = 6 + payload + 2
       - 起始字节 0xFE
       - payload 长度字段 == GCS codec 期望
       - msg_id 字段正确
       - CRC 与 GCS X.25 + crc_extra 算法一致
    返回 {ok: bool, failures: [...], summary: str}
    """
    failures = []
    ok_count = 0
    for name, exp_pl, exp_msg, builder in _SELFTEST_CASES:
        try:
            data = builder()
            total = len(data)
            start = data[0]
            pl = data[1]
            msg = data[5]
            wire_crc = struct.unpack('<H', data[-2:])[0]
            re_crc = mavlink_crc(data[1:6+pl], data[6+pl+0])  # dummy, just for size check
            issues = []
            if start != 0xFE:
                issues.append(f'start=0x{start:02x}!=0xfe')
            if pl != exp_pl:
                issues.append(f'payload={pl}/expect={exp_pl}')
            if msg != exp_msg:
                issues.append(f'msg_id={msg}/expect={exp_msg}')
            if total != 6 + exp_pl + 2:
                issues.append(f'total={total}/expect={6+exp_pl+2}')
            if issues:
                failures.append(f'{name}: {", ".join(issues)}')
            else:
                ok_count += 1
        except Exception as e:
            failures.append(f'{name}: exception {e}')

    ok = not failures
    return {
        'ok': ok,
        'ok_count': ok_count,
        'total': len(_SELFTEST_CASES),
        'failures': failures,
        'summary': f"自检: {ok_count}/{len(_SELFTEST_CASES)} 消息通过" +
                   (f" | 失败: {'; '.join(failures)}" if failures else ""),
    }


def parse_maVLink_header(data: bytes) -> dict:
    """快速解析 MAVLink 帧头"""
    if len(data) < 8:
        return None
    start, length, seq, sys_id, comp_id, msg_id = struct.unpack('BBBBBB', data[:6])
    if start != 0xFE:
        return None
    payload = data[6:6 + length] if len(data) >= 6 + length else b''
    return {'msg_id': msg_id, 'sys_id': sys_id, 'seq': seq,
            'comp_id': comp_id, 'payload': payload, 'length': length}


# =====================================================================
# IP 地址工具
# =====================================================================
def ip_to_int(ip: str) -> int:
    a, b, c, d = ip.split('.')
    return (int(a) << 24) | (int(b) << 16) | (int(c) << 8) | int(d)


def int_to_ip(val: int) -> str:
    return f"{(val >> 24) & 0xFF}.{(val >> 16) & 0xFF}.{(val >> 8) & 0xFF}.{val & 0xFF}"


def get_active_interface():
    """探测本机活跃网卡（连接地面站所在网络的接口）"""
    # 优先通过路由表获取
    try:
        out = subprocess.run(
            ['powershell', '-Command',
             "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
             "Where-Object {$_.NextHop -ne '0.0.0.0'} | "
             "Select-Object -First 1).InterfaceAlias"],
            capture_output=True, text=True, timeout=5)
        name = out.stdout.strip()
        if name:
            return name
    except Exception:
        pass

    # 备用：检测第一个有 IP 的以太网接口
    try:
        out = subprocess.run(
            ['powershell', '-Command',
             "(Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | "
             "Select-Object -First 1).Name"],
            capture_output=True, text=True, timeout=5)
        name = out.stdout.strip()
        if name:
            return name
    except Exception:
        pass

    return "Ethernet"


def list_all_interfaces() -> list:
    """枚举本机所有可用网卡 (含状态/IP/描述)，供 GUI 下拉框使用

    返回 list[dict]，每项字段：
      - name:        PowerShell InterfaceAlias（用户在 GUI 看到的名字，如 "以太网 2"）
      - ip:          首个 IPv4 地址（无则空串）
      - description: 驱动描述 (如 "Intel(R) Wi-Fi 6E AX211 160MHz")
      - status:      Up/Disabled/Disconnected
      - mac:         MAC 地址（含分隔符）
      - is_default:  是否默认路由所在网卡
    排除：loopback (127.x)、link-local (169.254.x)、虚拟桥接/隧道 (除非有真实 IP)
    """
    default_iface = ''
    try:
        out = subprocess.run(
            ['powershell', '-Command',
             "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
             "Where-Object {$_.NextHop -ne '0.0.0.0'} | "
             "Select-Object -First 1).InterfaceAlias"],
            capture_output=True, text=True, timeout=5)
        default_iface = out.stdout.strip()
    except Exception:
        pass

    cmd = (
        "Get-NetAdapter | ForEach-Object {"
        "  $ip = (Get-NetIPAddress -InterfaceAlias $_.Name -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
        "         Where-Object { $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1).IPAddress;"
        "  [PSCustomObject]@{ Name=$_.Name; Desc=$_.InterfaceDescription; Status=$_.Status; Mac=$_.MacAddress; Ip=$ip }"
        "} | ConvertTo-Json -Compress"
    )
    items = []
    try:
        out = subprocess.run(
            ['powershell', '-Command', cmd],
            capture_output=True, text=True, timeout=10)
        text = out.stdout.strip()
        if text:
            import json as _json
            data = _json.loads(text)
            if isinstance(data, dict):
                data = [data]
            for row in data:
                name = (row.get('Name') or '').strip()
                if not name:
                    continue
                ip = (row.get('Ip') or '').strip()
                desc = (row.get('Desc') or '').strip()
                status = (row.get('Status') or '').strip()
                mac = ((row.get('Mac') or '').strip()).replace('-', ':').lower()
                items.append({
                    'name': name,
                    'ip': ip,
                    'description': desc,
                    'status': status,
                    'mac': mac,
                    'is_default': (name == default_iface),
                })
    except Exception:
        pass

    # 排序：默认路由优先，然后 Up 状态，然后有 IP，最后按名称
    items.sort(key=lambda x: (
        not x['is_default'],
        x['status'] != 'Up',
        not x['ip'],
        x['name'],
    ))
    return items


def format_iface_label(item: dict) -> str:
    """下拉框显示文本: '以太网 2 (10.10.4.176) [Up] · Intel I210'"""
    name = item.get('name', '?')
    ip = item.get('ip', '')
    status = item.get('status', '')
    desc = item.get('description', '')
    parts = [name]
    if ip:
        parts.append(f"({ip})")
    if status and status != 'Up':
        parts.append(f"[{status}]")
    if desc:
        # 截断过长的驱动描述
        short = desc if len(desc) <= 40 else desc[:37] + '...'
        parts.append(f"· {short}")
    return ' '.join(parts)


def get_interface_ip(interface: str) -> str:
    """获取指定网卡的当前 IP 地址"""
    try:
        out = subprocess.run(
            ['powershell', '-Command',
             f"(Get-NetIPAddress -InterfaceAlias '{interface}' "
             "-AddressFamily IPv4 | Select-Object -First 1).IPAddress"],
            capture_output=True, text=True, timeout=5)
        ip = out.stdout.strip()
        if ip:
            return ip
    except Exception:
        pass

    # 备用: 用 socket 探测
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def get_interface_netmask(interface: str) -> str:
    """获取指定网卡的子网掩码"""
    try:
        out = subprocess.run(
            ['powershell', '-Command',
             f"(Get-NetIPAddress -InterfaceAlias '{interface}' "
             "-AddressFamily IPv4 | Select-Object -First 1).PrefixLength"],
            capture_output=True, text=True, timeout=5)
        prefix = out.stdout.strip()
        if prefix:
            pl = int(prefix)
            # 转换 prefix length → netmask
            mask = (0xFFFFFFFF << (32 - pl)) & 0xFFFFFFFF
            return int_to_ip(mask)
    except Exception:
        pass
    return "255.255.0.0"


def get_gateway_ip(interface: str) -> str:
    try:
        out = subprocess.run(
            ['powershell', '-Command',
             f"(Get-NetRoute -InterfaceAlias '{interface}' "
             "-DestinationPrefix 0.0.0.0/0 | Select-Object -First 1).NextHop"],
            capture_output=True, text=True, timeout=5)
        gw = out.stdout.strip()
        if gw and gw != '0.0.0.0':
            return gw
    except Exception:
        pass
    return ''


def same_subnet(ip1: str, ip2: str, mask: str = '255.255.255.0') -> bool:
    i1 = ip_to_int(ip1)
    i2 = ip_to_int(ip2)
    m = ip_to_int(mask)
    return (i1 & m) == (i2 & m)


def resolve_mac(ip: str, iface: str, timeout: float = 2.0) -> str:
    try:
        from scapy.all import Ether, ARP, srp1
        resolved = resolve_scapy_iface(iface)
        ans = srp1(Ether(dst='ff:ff:ff:ff:ff:ff') / ARP(pdst=ip),
                   iface=resolved, timeout=timeout, verbose=False)
        if ans and ans.haslayer('Ether'):
            return ans['Ether'].src
    except Exception:
        pass
    return ''


def suggest_start_ip(interface: str, ap_ip: str = None, gcs_ip: str = None) -> str:
    """根据 地面站 IP + AP/网关 IP + 本机 IP 推荐一个安全的 drone 起始 IP

    优先级: 地面站 GCS IP (无人机必须和 GCS 同子网, GCS 才能收到 UDP 包)
            > AP/网关 IP (路由权威, 通常与 GCS 同子网)
            > 本机 IP (本机也接在同一个 AP 下时)
            > 兜底 172.16.200.200

    规则:
      - 取参考 IP 前 3 段做 /24 子网 (压测场景通常 /24, 与 same_subnet 默认一致)
      - 起点偏移到 .200 (避开 .1=网关/AP, .100~.199=DHCP 常用池)
      - 避让 ap/gcs/本机 IP 末段, 撞了递增 +1, 直到 .250
    """
    my_ip = get_interface_ip(interface)

    def _parts(ip):
        try:
            ps = (ip or '').split('.')
            if len(ps) == 4 and all(0 <= int(p) <= 255 for p in ps):
                return ps
        except (ValueError, AttributeError):
            pass
        return None

    # 选参考 IP — GCS 优先 (无人机首要目标是被 GCS 看到), 其次 AP, 最后本机
    ref_ps = _parts(gcs_ip) or _parts(ap_ip) or _parts(my_ip)
    if not ref_ps:
        return "172.16.200.200"

    base3 = '.'.join(ref_ps[:3])

    # 收集需要避让的末段 (ap/gcs/本机若在同子网)
    avoid_last = set()
    for ip in (ap_ip, gcs_ip, my_ip):
        ps = _parts(ip)
        if ps and '.'.join(ps[:3]) == base3:
            avoid_last.add(int(ps[3]))

    cand = 200
    while cand in avoid_last and cand < 250:
        cand += 1
    return f"{base3}.{cand}"


# =====================================================================
# IP 别名管理 (netsh) — 同 fake_airplane.py _set_ip_address 方式
# =====================================================================
class IPAliasManager:
    """通过 netsh 在网卡上添加/删除 IP 别名"""

    def __init__(self, interface: str, log_fn=None):
        self.interface = interface
        self.log = log_fn or (lambda m: None)
        self._ips = []      # 已成功添加的 IP
        self._mask = "255.255.0.0"  # 默认 /16，与工程内一致

    def set_mask(self, mask: str):
        self._mask = mask

    def add_range(self, start_ip: str, count: int) -> int:
        """添加 count 个 IP，返回成功添加数量"""
        base = ip_to_int(start_ip)
        added = 0
        self.log(f"正在添加 {count} 个 IP 别名到 {self.interface}...")
        for i in range(count):
            ip = int_to_ip(base + i)
            if not self._add_one(ip):
                self.log(f"  添加失败: {ip}")
                break
            # netsh 返回成功不代表 IP 立即可用，等待一小段时间
            time.sleep(0.05)
            if not self._verify_ip(ip, retries=10):
                self.log(f"  验证失败: {ip} (IP 未能绑定，跳过)")
                self._remove_one(ip)
                continue
            self._ips.append(ip)
            added += 1
            if (added) % 50 == 0:
                self.log(f"  已添加 {added}/{count}...")
        self.log(f"IP 别名添加完成: {added}/{count}")
        return added

    def _add_one(self, ip: str) -> bool:
        cmd = ['netsh', 'interface', 'ip', 'add', 'address',
               f'name={self.interface}', f'addr={ip}', f'mask={self._mask}']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                self.log(f"  netsh 添加 {ip} 失败: {result.stderr.strip()}")
            return result.returncode == 0
        except Exception as e:
            self.log(f"  netsh 添加 {ip} 异常: {e}")
            return False

    def _verify_ip(self, ip: str, retries: int = 10) -> bool:
        """验证 IP 是否可用于 bind（netsh 返回成功后可能需要等待）"""
        last_err = ""
        for attempt in range(retries):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.bind((ip, VirtualDrone.DRONE_PORT))
                s.close()
                return True
            except OSError as e:
                last_err = str(e)
                time.sleep(0.1)
        self.log(f"    验证 {ip}:{VirtualDrone.DRONE_PORT} 失败 ({last_err})")
        return False

    def remove_all(self):
        if not self._ips:
            return
        self.log(f"正在删除 {len(self._ips)} 个 IP 别名...")
        for ip in self._ips:
            self._remove_one(ip)
        self.log(f"IP 别名删除完成: {len(self._ips)}")
        self._ips.clear()

    def _remove_one(self, ip: str) -> bool:
        cmd = ['netsh', 'interface', 'ip', 'delete', 'address',
               f'name={self.interface}', f'addr={ip}']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    def __len__(self):
        return len(self._ips)


# =====================================================================
# 飞行状态机
# =====================================================================
class FlightState:
    """飞行状态枚举（对齐 FakeUavParser.cs FlyState）"""
    IDLE = 0       # 地面/解锁前
    TAKEOFF = 1    # 起飞爬升
    CRUISE = 2     # 巡航
    RETURN = 3     # 返航
    LANDING = 4    # 降落


# =====================================================================
# DroneBehavior — 单架飞机的状态机 + 字段抖动 + 消息构建
# 纯函数无 IO，被 VirtualDrone / ScapyVirtualDrone / FloodRunner 共享
# =====================================================================
class DroneBehavior:
    """一架虚拟无人机的行为模型

    每秒 tick 一次推进状态机；按需 build 出各 MAVLink 消息帧。
    """

    # 默认调度间隔（秒）— 对齐真实飞控
    HEARTBEAT_PERIOD = 3.0          # mav_channel.cpp:195 (3s)
    FAILSAFE_PERIOD = 1.0           # FakeUav 1Hz 主动
    RCS_PERIOD = 1.0                # FakeUav SendBatteryExtendInfo 1Hz
    # 应答节流 — 对齐固件 mav_channel.cpp:853-856
    # GCS 高频轮询 heartbeat_dmd 时,飞机不应每次都回 packed_state/extend_state,500ms 一帧
    MIN_SEND_STATE_INTERVAL_S = 0.5      # mav_channel.hpp:29 (500ms)
    MIN_SEND_IDENTIFY_INTERVAL_S = 2.0   # GET_IDENTIFY_INFO 应答节流,GCS 重发请求时不重复回
    # 应答 drain 上限因子 — 每轮 _send_loop 最多 drain (count * 此因子) 个应答
    # 心跳是 keep-online 必发, 应答是 best-effort, 必须保证心跳节奏不被应答积压拖慢
    # 1000 架 × 500ms 节流 → 入队 ~2000/s, 单轮 3s 累 6000; 若全 drain 则构包+sendp 耗时 >6s
    # → 心跳间隔超过 GCS UdpTimeout → 全部 DISCONNECTED. cap 到 count 后最坏 2N 包/轮, 可控
    MAX_RESP_PER_ROUND_FACTOR = 1.0

    def __init__(self, index: int, sys_id: int, config: dict = None):
        self.index = index
        self.sys_id = sys_id
        self.seq = random.randint(0, 255)

        cfg = config or {}
        self._jitter_enabled = bool(cfg.get('jitter', True))
        self._field_pct = float(cfg.get('field_pct', 20.0))
        self._state_machine_enabled = bool(cfg.get('state_machine', True))
        self._target_alt = int(float(cfg.get('target_alt_m', 50)) * 1000)   # mm
        self._phase_offset = float(cfg.get('phase_offset_s', 5.0))
        self._cruise_duration = float(cfg.get('cruise_duration_s', 30.0))
        self._raw_imu_rate = float(cfg.get('raw_imu_rate_hz', 0))           # 0=禁用
        self._initial_failsafe = int(cfg.get('failsafe_mask', 0))
        # SSID (8 字节 ASCII) — 真实业务是 WiFi 网络名,整个机队连同一个 AP 时共享
        # 对齐固件 mav_channel.cpp:866-886 (从 WiFi 模块读 SSID 填入 packed_state.ssid)
        # 默认 'DMD',固件出厂默认也是 'dmd' (mt793x/dmd_app.h:28 DMD_DFT_SSID)
        ssid_str = str(cfg.get('ssid', 'DMD'))
        self._ssid = ssid_str.encode('ascii', errors='replace')[:8].ljust(8, b'\x00')

        # 初始位置（深圳附近）+ per-drone 微抖动避免完全重合
        base_lat = float(cfg.get('base_lat', 22.5))
        base_lon = float(cfg.get('base_lon', 113.9))
        self._home_lat = int((base_lat + random.uniform(-0.005, 0.005)) * 1e7)
        self._home_lon = int((base_lon + random.uniform(-0.005, 0.005)) * 1e7)
        self._lat = self._home_lat
        self._lon = self._home_lon
        self._alt = 0
        self._heading = random.uniform(0, 2 * math.pi)

        # 状态机
        self._state = FlightState.IDLE
        self._state_enter_time = 0.0
        self._startup_delay = self.index * self._phase_offset
        self._flight_time = 0.0

        # 电池
        self._voltage = 16277
        self._batt_pct = 95
        self._batt_total_cap = 3700
        self._batt_remain_cap = 3500
        self._remain_fly_time = int(self._cruise_duration + 120)
        # 4 cell voltages —— 跟随主电压整体下降，cell 间略有差异
        self._cell_base = 4070      # 4.07V/cell → ~16.28V total ≈ voltage/4
        self._rid_voltage = 3700    # RID 模块电池 ~3.7V
        self._battery_used_times = random.randint(5, 30)

        # 温度（飞行中会缓慢上升，对齐真实飞控 IMU/Baro/Batt 温升）
        self._temp_imu = random.uniform(24.0, 28.0)
        self._temp_baro = random.uniform(22.0, 26.0)
        self._temp_batt = random.uniform(26.0, 30.0)

        # 失效保护（默认 0=正常；可由 GUI 注入）
        self.failsafe_mask = self._initial_failsafe

        # 静态字段（含抖动用的"身份"信息）
        self._sensor_health = 3583
        self._sensor_health_middle = 0x0001   # bit0=imu_vib_ok
        self._sensor_health_extend = 0x0001   # bit0=rid_ok
        # _ssid 已在 __init__ 顶部从 cfg['ssid'] 读取 (机队共享)
        # 用 index 而非 sys_id 生成身份字段:
        # sys_id 受 MAVLink 单字节限制在 1~254 循环 (count>254 必撞),
        # 而 serial(20B)/code(5B)/uas_code(20B) 空间充足, 用 index 可保证全集群唯一
        self._serial = (f'DMDTEST{self.index:012d}').encode()[:20]
        # 模块版本（对齐 FakeUavParser.receive.cs:111-117）
        self._fc_version = b'4.1.0\x00\x00\x00'
        self._companion_version = b'4.2.0\x00\x00\x00'
        self._battery_version = b'3.0\x00\x00\x00\x00\x00'
        self._gps_version = b'2.1\x00\x00\x00\x00\x00'
        self._tele_version = b'1.5\x00'
        self._bms_version = b'1.2\x00'
        self._rid_version = b'1.0\x00\x00\x00\x00\x00'
        self._gimbal_version = b'1.0\x00'
        self._param_hash = 0xDEADBEEF
        self._anchor_hash = 0xCAFEBABE
        # UAS_CODE 20 字节 ASCII（RID 远程识别用）,跟随 index 保证唯一
        uas_str = f"UAS_TEST_{self.index:04d}".encode('ascii')
        self._uas_code = uas_str[:20].ljust(20, b'\x00')
        # identify_info.code (5B) — 地面站 UI 的 "ID" 字段 读的就是这个
        # 5 字节最大塞 5 位数字, 支持 index 0..99999 全集群唯一
        self._identify_code = f'{self.index + 1:05d}'.encode()[:5]
        self._rc_matching_code = 0x1234

        # 灯色（由状态机更新）
        self._light_r = 0
        self._light_g = 0
        self._light_b = 0

        # 统计/状态
        self.sent = 0
        self.recv = 0
        self.discovered = False              # GCS 心跳轮询中 (收到 heartbeat_dmd, 仅代表 GCS 在向我发心跳)
        self.discovered_time = 0.0           # 最近一次收到 GCS 心跳的时间戳 (6s 内未收到则清零 discovered)
        self.discovered_by_ap = False        # ARP 应答 (IP 进入 AP/GCS ARP 表, 不代表 GCS 知道我)
        self.gcs_online = False              # 地面站在线飞机数 (GCS 状态机走到 WORKING+, 即收到 GCS 非心跳 MAVLink)
        self.gcs_online_time = 0.0           # 最近一次收到 GCS 业务消息的时间戳 (6s 内未收到则清零 gcs_online)
        self.last_recv_time = 0.0
        self.last_recv_msg_id = None
        # 应答节流时间戳 — 对齐固件 mav_channel.cpp:853-856 (500ms 节流)
        self.last_send_state_time = 0.0      # packed_state/extend_state 上次回复时间
        self.last_send_identify_time = 0.0   # identify_info 上次回复时间

    # ---- helpers ----
    def _rj(self, lo: int, hi: int) -> int:
        return random.randint(lo, hi - 1)

    def _rf(self, lo: float, hi: float) -> float:
        return random.uniform(lo, hi)

    # ---- 状态查询 ----
    def _get_armed(self) -> int:
        return 0 if self._state == FlightState.IDLE else 1

    def _get_base_mode(self) -> int:
        return HB_BASE_MODE_DISARM if self._state == FlightState.IDLE else HB_BASE_MODE_ARMED

    def _get_mode(self) -> int:
        return {
            FlightState.IDLE: 0,
            FlightState.TAKEOFF: 4,
            FlightState.CRUISE: 4,
            FlightState.RETURN: 6,
            FlightState.LANDING: 9,
        }.get(self._state, 0)

    def _get_fly_state(self) -> int:
        return {
            FlightState.IDLE: 0,
            FlightState.TAKEOFF: 0x10,
            FlightState.CRUISE: 0x20,
            FlightState.RETURN: 0x40,
            FlightState.LANDING: 0x80,
        }.get(self._state, 0)

    def _get_motion(self):
        """返回 (v_horz_cm_s, v_vert_cm_s)"""
        return {
            FlightState.IDLE: (0, 0),
            FlightState.TAKEOFF: (0, 300),
            FlightState.CRUISE: (800, 0),
            FlightState.RETURN: (1000, 0),
            FlightState.LANDING: (0, -200),
        }.get(self._state, (0, 0))

    def _get_light(self):
        return {
            FlightState.IDLE: (0, 0, 0),
            FlightState.TAKEOFF: (255, 0, 0),
            FlightState.CRUISE: (0, 255, 0),
            FlightState.RETURN: (0, 0, 255),
            FlightState.LANDING: (255, 255, 0),
        }.get(self._state, (0, 0, 0))

    # ---- 状态机推进 ----
    def tick(self, dt: float):
        """每秒推进一次状态机 + GPS 运动 + 电池衰减"""
        self._flight_time += dt

        if not self._state_machine_enabled:
            # 仅 GPS 原地抖动
            if self._jitter_enabled:
                drift = int(self._field_pct * 100)
                self._lat += self._rj(-drift, drift + 1)
                self._lon += self._rj(-drift, drift + 1)
            self._drain_battery(dt)
            return

        # 状态转移
        if self._state == FlightState.IDLE:
            if self._flight_time >= self._startup_delay:
                self._enter_state(FlightState.TAKEOFF)
        elif self._state == FlightState.TAKEOFF:
            if self._alt >= self._target_alt:
                self._enter_state(FlightState.CRUISE)
        elif self._state == FlightState.CRUISE:
            if self._flight_time - self._state_enter_time >= self._cruise_duration:
                self._enter_state(FlightState.RETURN)
        elif self._state == FlightState.RETURN:
            if self._haversine_m(self._lat, self._lon, self._home_lat, self._home_lon) <= 5.0:
                self._enter_state(FlightState.LANDING)
        elif self._state == FlightState.LANDING:
            if self._alt <= 0 and (self._flight_time - self._state_enter_time) >= 2.0:
                self._alt = 0
                # 循环：回到 IDLE 并重置 battery / startup_delay
                self._enter_state(FlightState.IDLE)
                self._startup_delay = self._flight_time + 3.0   # 3 秒后重新起飞
                self._voltage = 16277
                self._batt_pct = 95
                self._batt_remain_cap = 3500
                self._remain_fly_time = int(self._cruise_duration + 120)
                self._cell_base = 4070
                self._rid_voltage = 3700
                self._battery_used_times += 1

        # 状态内运动
        v_horz, v_vert = self._get_motion()
        if v_vert > 0:
            self._alt = int(self._alt + v_vert * 10 * dt)     # cm/s → mm/s
        elif v_vert < 0:
            self._alt = max(0, int(self._alt + v_vert * 10 * dt))
        if v_horz > 0:
            self._move_horizontal(v_horz, dt)

        # 灯色
        self._light_r, self._light_g, self._light_b = self._get_light()

        # GPS 噪声（无论是否运动，叠加 ±0.3m 抖动）
        if self._jitter_enabled:
            self._lat += self._rj(-30, 31)
            self._lon += self._rj(-30, 31)

        # 电池衰减
        self._drain_battery(dt)

    def _enter_state(self, new_state: int):
        self._state = new_state
        self._state_enter_time = self._flight_time

    def _drain_battery(self, dt: float):
        if self._state != FlightState.IDLE:
            self._batt_pct = max(20, self._batt_pct - 0.05 * dt)
            self._voltage = max(14800, int(self._voltage - 2 * dt))
            self._batt_remain_cap = int(self._batt_total_cap * self._batt_pct / 100)
            self._remain_fly_time = max(0, self._remain_fly_time - int(dt))
            # 4 cell 电压跟随主电压 (mV/4 ≈ cell mV)，加微抖动
            cell_avg = int(self._voltage // 4)
            self._cell_base = max(3600, cell_avg + random.randint(-15, 15))
            # RID 电池轻微下降
            self._rid_voltage = max(3300, self._rid_voltage - int(0.5 * dt))
            # 温度上升（飞行中功耗大）
            self._temp_imu = min(60.0, self._temp_imu + 0.05 * dt)
            self._temp_baro = min(55.0, self._temp_baro + 0.04 * dt)
            self._temp_batt = min(55.0, self._temp_batt + 0.08 * dt)
        else:
            # 地面静置：温度向环境温回归，RID 缓慢自恢复
            self._temp_imu += (25.0 - self._temp_imu) * 0.01 * dt
            self._temp_baro += (23.0 - self._temp_baro) * 0.01 * dt
            self._temp_batt += (25.0 - self._temp_batt) * 0.01 * dt
            self._rid_voltage = min(4200, int(self._rid_voltage + 0.2 * dt))

    def _move_horizontal(self, speed_cm_s: float, dt: float):
        if self._state == FlightState.RETURN:
            self._heading = self._bearing_to(self._lat, self._lon,
                                             self._home_lat, self._home_lon)
        step_m = speed_cm_s * dt / 100.0
        cos_lat = math.cos(math.radians(self._lat / 1e7))
        d_lat_1e7 = step_m * math.cos(self._heading) / 111000 * 1e7
        d_lon_1e7 = (step_m * math.sin(self._heading) / (111000 * cos_lat) * 1e7
                     if cos_lat > 0.01 else 0)
        self._lat = int(self._lat + d_lat_1e7)
        self._lon = int(self._lon + d_lon_1e7)
        # 边界限制
        self._lat = max(-900000000, min(900000000, self._lat))
        self._lon = max(-1800000000, min(1800000000, self._lon))

    def _bearing_to(self, lat1, lon1, lat2, lon2) -> float:
        return math.atan2(lon2 - lon1, lat2 - lat1)

    def _haversine_m(self, lat1, lon1, lat2, lon2) -> float:
        d_lat = (lat2 - lat1) / 1e7
        d_lon = (lon2 - lon1) / 1e7
        return math.sqrt(d_lat * d_lat + d_lon * d_lon) * 111000

    # ---- 消息构建（统一入口）----
    def build(self, msg_name: str) -> bytes:
        """构建一条 MAVLink 帧（自动递增 seq）"""
        self.seq = (self.seq + 1) & 0xFF
        if msg_name == 'heartbeat':
            return self._build_heartbeat()
        if msg_name == 'packed_state':
            return self._build_packed_state()
        if msg_name == 'extend_state':
            return self._build_extend_state()
        if msg_name == 'failsafe':
            return build_failsafe(self.sys_id, self.seq, self.failsafe_mask)
        if msg_name == 'remaining_capacity':
            return build_remaining_capacity_state(
                self.sys_id, self.seq,
                remain_fly_time=self._remain_fly_time,
                battery_total=self._batt_total_cap,
                battery_remain=self._batt_remain_cap,
                battery_pct=int(self._batt_pct))
        if msg_name == 'raw_imu':
            return self._build_raw_imu()
        if msg_name == 'identify_info':
            return build_identify_info(self.sys_id, self.seq,
                                       serial=self._serial,
                                       code=self._identify_code)
        if msg_name == 'param_request_list_ack':
            return build_param_request_list_ack(self.sys_id, self.seq)
        raise ValueError(f"unknown msg_name: {msg_name}")

    def _build_heartbeat(self) -> bytes:
        return build_heartbeat(
            self.sys_id, self.seq,
            system_status=HB_SYS_STATUS_ACTIVE,
            base_mode=self._get_base_mode(),
            autopilot=MAV_AUTOPILOT_DMD_FC)

    def _build_packed_state(self) -> bytes:
        # 目标航点
        if self._state == FlightState.RETURN:
            tar_lat, tar_lon, tar_alt = self._home_lat, self._home_lon, self._target_alt
        elif self._state == FlightState.LANDING:
            tar_lat, tar_lon, tar_alt = self._home_lat, self._home_lon, 0
        elif self._state_machine_enabled:
            cos_lat = math.cos(math.radians(self._lat / 1e7))
            tar_lat = int(self._lat + 50 * math.cos(self._heading) / 111000 * 1e7)
            tar_lon = (int(self._lon + 50 * math.sin(self._heading) /
                           (111000 * cos_lat) * 1e7) if cos_lat > 0.01 else self._lon)
            tar_alt = self._target_alt
        else:
            tar_lat, tar_lon, tar_alt = self._lat, self._lon, self._alt

        v_horz, v_vert = self._get_motion()
        jit = self._jitter_enabled
        eph = self._rj(5, 51) if jit else 90
        satellites = self._rj(8, 21) if jit else 15
        fix_type = 6 if (jit and self._rj(0, 10) > 2) else 3
        wifi_up = self._rj(-70, -30) if jit else -40
        mav_up_rate = self._rj(1, 6) if jit else 3
        rtk_quality = self._rj(0, 101) if jit else 2
        rtk_850m = self._rj(60, 81) if jit else 72
        rtk_2g4 = self._rj(60, 81) if jit else 72
        rc_radio = self._rj(80, 101) if jit else 90
        voltage = self._voltage + (self._rj(-50, 51) if jit else 0)
        wind_x = self._rj(-300, 301) if jit else 0
        wind_y = self._rj(-300, 301) if jit else 0
        v_horz_jit = v_horz + (self._rj(-50, 51) if (jit and v_horz) else 0)
        v_vert_jit = v_vert + (self._rj(-30, 31) if (jit and v_vert) else 0)

        play_state = 1 if self._state == FlightState.CRUISE else 0

        return build_packed_state(
            self.sys_id, self.seq,
            lat=self._lat, lon=self._lon, alt=self._alt,
            tar_lat=tar_lat, tar_lon=tar_lon, tar_alt=tar_alt,
            ssid=self._ssid,
            voltage=voltage, batt_pct=int(self._batt_pct),
            fix_type=fix_type, satellites=satellites,
            armed=self._get_armed(), mode=self._get_mode(),
            fly_state=self._get_fly_state(),
            wifi_up=wifi_up, mav_up_rate=mav_up_rate,
            bat_serial=b'DMD000001\x00',
            sensor_health=self._sensor_health,
            sensor_health_middle=self._sensor_health_middle,
            sensor_health_extend=self._sensor_health_extend,
            rc_matching_code=self._rc_matching_code,
            uav_speed_horz=v_horz_jit, uav_speed_vert=v_vert_jit,
            elevation=self._alt + (self._rj(-500, 501) if jit else 0),
            light_r=self._light_r, light_g=self._light_g, light_b=self._light_b,
            play_state=play_state,
            eph=eph, rtk_quality=rtk_quality,
            rtk_radio_850m=rtk_850m, rtk_radio_2g4=rtk_2g4,
            rc_radio=rc_radio,
            wind_speed_x=wind_x, wind_speed_y=wind_y)

    def _build_extend_state(self) -> bytes:
        jit = self._jitter_enabled
        # 姿态（弧度）— 状态相关
        if jit:
            # 飞行中有摇摆，地面静止几乎为 0
            if self._state == FlightState.IDLE:
                roll = self._rf(-0.02, 0.02)
                pitch = self._rf(-0.02, 0.02)
            else:
                roll = self._rf(-0.15, 0.15)
                pitch = self._rf(-0.15, 0.15)
            yaw = self._heading
            # 温度抖动（基于已积累的温度状态）
            temp_imu = self._temp_imu + self._rf(-0.3, 0.3)
            temp_baro = self._temp_baro + self._rf(-0.2, 0.2)
            temp_batt = self._temp_batt + self._rf(-0.2, 0.2)
            # cell 电压基于 _cell_base 抖动
            c1 = self._cell_base + self._rj(-10, 11)
            c2 = self._cell_base + self._rj(-10, 11)
            c3 = self._cell_base + self._rj(-10, 11)
            c4 = self._cell_base + self._rj(-10, 11)
            rid_v = self._rid_voltage + self._rj(-20, 21)
        else:
            roll = pitch = 0.0
            yaw = self._heading
            temp_imu, temp_baro, temp_batt = 28.5, 26.0, 32.0
            c1, c2, c3, c4 = 4070, 4065, 4078, 4062
            rid_v = 3700

        return build_extend_state(
            self.sys_id, self.seq,
            roll=roll, pitch=pitch, yaw=yaw,
            battery_time=self._remain_fly_time,
            temp_imu=temp_imu, temp_baro=temp_baro, temp_batt=temp_batt,
            battery_capability=self._batt_total_cap,
            battery_used_times=self._battery_used_times,
            cell1=c1, cell2=c2, cell3=c3, cell4=c4,
            fc_ver=self._fc_version,
            companion_ver=self._companion_version,
            battery_ver=self._battery_version,
            gps_ver=self._gps_version,
            tele_ver=self._tele_version,
            bms_ver=self._bms_version,
            rid_ver=self._rid_version,
            gimbal_ver=self._gimbal_version,
            voltage_rid_bat=rid_v,
            uas_code=self._uas_code,
            param_hash=self._param_hash, anchor_hash=self._anchor_hash)

    def _build_raw_imu(self) -> bytes:
        jit = self._jitter_enabled
        if jit:
            xacc = self._rj(-50, 51)
            yacc = self._rj(-50, 51)
            zacc = 1000 + self._rj(-50, 51)
            xgyro = self._rj(-20, 21)
            ygyro = self._rj(-20, 21)
            zgyro = self._rj(-20, 21)
            xmag = self._rj(-300, 301)
            ymag = self._rj(-300, 301)
            zmag = 400 + self._rj(-100, 101)
        else:
            xacc = yacc = 0
            zacc = 1000
            xgyro = ygyro = zgyro = 0
            xmag = ymag = 0
            zmag = 400
        t_usec = int(time.time() * 1e6) & 0xFFFFFFFFFFFFFFFF
        return build_raw_imu(
            self.sys_id, self.seq, time_usec=t_usec,
            xacc=xacc, yacc=yacc, zacc=zacc,
            xgyro=xgyro, ygyro=ygyro, zgyro=zgyro,
            xmag=xmag, ymag=ymag, zmag=zmag)


# =====================================================================
# 虚拟无人机
# =====================================================================
class VirtualDrone:
    """一架虚拟无人机：独立 IP:14551 + UDP socket

    行为（状态机/抖动/消息构建）全部委托给 DroneBehavior；本类只负责 socket IO。
    """

    DRONE_PORT = 14551   # 无人机统一端口 — config.json V4.port / Ground_Station 发现端口

    def __init__(self, index: int, local_ip: str, jitter_enabled: bool,
                 field_jitter_pct: float, config: dict = None):
        self.index = index
        self.ip = local_ip
        self.port = self.DRONE_PORT
        self.sys_id = (index % 254) + 1

        cfg = dict(config or {})
        cfg.setdefault('jitter', jitter_enabled)
        cfg.setdefault('field_pct', field_jitter_pct)
        self.behavior = DroneBehavior(index, self.sys_id, cfg)
        # 兼容外部对 seq/_jitter/_field_pct 的引用
        self.seq = self.behavior.seq

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            self.sock.bind((local_ip, self.DRONE_PORT))
        except OSError as e:
            raise RuntimeError(f"无法绑定 {local_ip}:{self.DRONE_PORT}: {e}")
        self.sock.setblocking(False)

    # ---- 行为委托 ----
    @property
    def sent(self): return self.behavior.sent
    @sent.setter
    def sent(self, v): self.behavior.sent = v

    @property
    def recv(self): return self.behavior.recv
    @recv.setter
    def recv(self, v): self.behavior.recv = v

    @property
    def discovered(self): return self.behavior.discovered
    @discovered.setter
    def discovered(self, v): self.behavior.discovered = v

    @property
    def discovered_time(self): return self.behavior.discovered_time
    @discovered_time.setter
    def discovered_time(self, v): self.behavior.discovered_time = v

    @property
    def discovered_by_ap(self): return self.behavior.discovered_by_ap
    @discovered_by_ap.setter
    def discovered_by_ap(self, v): self.behavior.discovered_by_ap = v

    @property
    def gcs_online(self): return self.behavior.gcs_online
    @gcs_online.setter
    def gcs_online(self, v): self.behavior.gcs_online = v

    @property
    def last_recv_time(self): return self.behavior.last_recv_time
    @last_recv_time.setter
    def last_recv_time(self, v): self.behavior.last_recv_time = v

    @property
    def last_recv_msg_id(self): return self.behavior.last_recv_msg_id
    @last_recv_msg_id.setter
    def last_recv_msg_id(self, v): self.behavior.last_recv_msg_id = v

    def tick(self, dt: float):
        self.behavior.tick(dt)
        self.seq = self.behavior.seq

    # ---- 统一发包接口 ----
    def send_msg(self, msg_name: str, dst_ip: str, dst_port: int) -> bool:
        try:
            data = self.behavior.build(msg_name)
            self.sock.sendto(data, (dst_ip, dst_port))
            self.behavior.sent += 1
            self.seq = self.behavior.seq
            return True
        except Exception:
            return False

    # ---- 兼容旧接口 ----
    def send_heartbeat(self, dst_ip: str, dst_port: int) -> bool:
        return self.send_msg('heartbeat', dst_ip, dst_port)

    def send_packed_state(self, dst_ip: str, dst_port: int) -> bool:
        return self.send_msg('packed_state', dst_ip, dst_port)

    def send_identify_info(self, dst_ip: str, dst_port: int) -> bool:
        return self.send_msg('identify_info', dst_ip, dst_port)

    def send_extend_state(self, dst_ip: str, dst_port: int) -> bool:
        return self.send_msg('extend_state', dst_ip, dst_port)

    def send_failsafe(self, dst_ip: str, dst_port: int) -> bool:
        return self.send_msg('failsafe', dst_ip, dst_port)

    def send_remaining_capacity(self, dst_ip: str, dst_port: int) -> bool:
        return self.send_msg('remaining_capacity', dst_ip, dst_port)

    def send_raw_imu(self, dst_ip: str, dst_port: int) -> bool:
        return self.send_msg('raw_imu', dst_ip, dst_port)

    def send_param_request_list_ack(self, dst_ip: str, dst_port: int) -> bool:
        return self.send_msg('param_request_list_ack', dst_ip, dst_port)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


# =====================================================================
# 无人机集群
# =====================================================================
class DroneSwarm:
    """管理 N 架虚拟无人机（N 个独立 IP + 端口 14551）"""

    def __init__(self, count: int, start_ip: str, alias_mgr: IPAliasManager,
                 jitter: bool = True, field_jitter_pct: float = 20.0,
                 config: dict = None, log_fn=None):
        self.count = count
        self._log = log_fn or (lambda m: None)
        self._drones = []

        # 添加 IP 别名
        actual = alias_mgr.add_range(start_ip, count)
        if actual == 0:
            raise RuntimeError("无法添加 IP 别名，请以管理员运行并检查网络配置")
        if actual < count:
            self._log(f"警告: 仅成功添加 {actual}/{count} 个 IP，实际模拟 {actual} 架")

        # 创建无人机
        base = ip_to_int(start_ip)
        for i in range(actual):
            ip = int_to_ip(base + i)
            try:
                drone = VirtualDrone(i, ip, jitter, field_jitter_pct, config=config)
                self._drones.append(drone)
            except RuntimeError as e:
                self._log(f"  创建无人机 {i} ({ip}) 失败: {e}")

        self._log(f"创建完成: {len(self._drones)} 架无人机 ({len(self._drones)} 个 IP × 端口 {VirtualDrone.DRONE_PORT})")

    def __len__(self):
        return len(self._drones)

    def __iter__(self):
        return iter(self._drones)

    def active_sockets(self) -> int:
        return len(self._drones)

    def summary(self) -> dict:
        total_sent = sum(d.sent for d in self._drones)
        total_recv = sum(d.recv for d in self._drones)
        discovered = sum(1 for d in self._drones if d.discovered)
        discovered_by_ap = sum(1 for d in self._drones if d.discovered_by_ap)
        gcs_online = sum(1 for d in self._drones if d.gcs_online)
        return {'total_sent': total_sent, 'total_recv': total_recv,
                'discovered': discovered,
                'discovered_by_ap': discovered_by_ap,
                'gcs_online': gcs_online,
                'total': len(self._drones)}

    def close_all(self):
        for d in self._drones:
            d.close()


# =====================================================================
# 洪水发包器 (scapy L2) — 用于超大数量纯压力
# =====================================================================
class FloodSender:
    def __init__(self, dst_ip: str, dst_port: int, dst_mac: str, iface=None):
        self.dst_ip = dst_ip
        self.dst_port = dst_port
        self.dst_mac = dst_mac
        self.iface = iface
        self._ok = False
        try:
            from scapy.all import Ether, IP, UDP, sendp
            self._Ether = Ether; self._IP = IP; self._UDP = UDP; self._sendp = sendp
            self._ok = True
        except ImportError:
            pass
        self.stats = {'packets': 0, 'errors': 0, 'start_time': 0.0}

    @property
    def available(self): return self._ok

    def start(self): self.stats = {'packets': 0, 'errors': 0, 'start_time': time.time()}

    def send(self, src_ip: str, src_mac: str, data: bytes) -> bool:
        try:
            pkt = (self._Ether(src=src_mac, dst=self.dst_mac) /
                   self._IP(src=src_ip, dst=self.dst_ip) /
                   self._UDP(sport=14551, dport=self.dst_port) / data)
            self._sendp(pkt, iface=self.iface, verbose=False)
            self.stats['packets'] += 1
            return True
        except Exception:
            self.stats['errors'] += 1
            return False

    def snapshot(self) -> dict:
        s = dict(self.stats)
        if s['start_time'] > 0:
            s['elapsed'] = time.time() - s['start_time']
            s['rate'] = s['packets'] / s['elapsed'] if s['elapsed'] > 0 else 0
        return s


# =====================================================================
# 测试执行器 — 双向模式
# =====================================================================
class BidirectionalRunner:
    """独立收包线程 + 发包线程"""

    def __init__(self, swarm: DroneSwarm, gcs_ip: str, gcs_port: int,
                 interval: float = 3.0, duration: float = 0.0,
                 batch_size: int = 50, respond: bool = True,
                 raw_imu_rate: float = 0.0,
                 packed_state_rate: float = 5.0,
                 extend_state_rate: float = 2.0,
                 on_log=None, on_tick=None):
        self.swarm = swarm
        self.gcs_ip = gcs_ip
        self.gcs_port = gcs_port
        self.interval = interval
        self.duration = duration
        self.batch_size = batch_size
        self.respond = respond
        self.raw_imu_rate = raw_imu_rate
        self.packed_state_rate = packed_state_rate
        self.extend_state_rate = extend_state_rate
        self.on_log = on_log or (lambda m: None)
        self.on_tick = on_tick
        self._stop = threading.Event()
        self._send_thread = None
        self._recv_thread = None
        self._aux_thread = None
        self._round = 0
        self._t0 = 0.0
        self._recv_lock = threading.Lock()
        self._recv_total = 0
        # 浮点频率累加器（支持 0.5Hz 等小数）
        self._ps_acc = 0.0
        self._es_acc = 0.0
        # 应答发送计数（诊断用）
        self._ps_sent = 0
        self._es_sent = 0
        self._rcs_sent = 0
        self._id_sent = 0
        self._hb_sent = 0
        self._fs_sent = 0
        self._raw_sent = 0
        self._send_errors = 0
        # 状态转换日志节流: 1000+ 架时, "✓ 飞机 #X 被发现/在线" 会刷屏阻塞 GUI Text widget
        # 只记前 N 条单架消息, 之后的转换靠每轮 summary (②心跳 X/N, ③在线 X/N) 体现
        self._disc_log_count = 0
        self._online_log_count = 0
        self._TRANSITION_LOG_PER_TYPE = 20   # 前 20 架单条记录, 之后静默
        self._last_diag_time = time.time()

    def start(self):
        self._stop.clear()
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()
        self._aux_thread = threading.Thread(target=self._aux_loop, daemon=True)
        self._aux_thread.start()
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._send_thread.start()

    def stop(self):
        self._stop.set()

    def running(self) -> bool:
        return (self._send_thread and self._send_thread.is_alive()) or \
               (self._recv_thread and self._recv_thread.is_alive()) or \
               (self._aux_thread and self._aux_thread.is_alive())

    # ------------------------------------------------------------------
    def _recv_loop(self):
        """独立收包线程 — 持续轮询所有 socket"""
        drones = list(self.swarm)
        self.on_log(f"收包线程启动: 监听 {len(drones)} 个端口")

        while not self._stop.is_set():
            got_any = False
            for drone in drones:
                if self._stop.is_set():
                    break
                try:
                    data, addr = drone.sock.recvfrom(4096)
                    info = parse_maVLink_header(data)
                    if info is None:
                        continue
                    got_any = True
                    drone.recv += 1
                    drone.last_recv_time = time.time()
                    drone.last_recv_msg_id = info['msg_id']

                    # 收到任何非 heartbeat_dmd (msg_id != 1) 的 MAVLink → GCS 已把我当在线在交互
                    # 对齐地面站 UavParser.receive.cs:25-30 状态机: 收到任意 MAVLink → WORKING → Online
                    # 6s 内未再收到 GCS 业务消息 → _refresh_online_counters 清零 (对齐 udpTimeout=6000ms)
                    if info['msg_id'] != 1:
                        now_t = time.time()
                        if not drone.gcs_online:
                            drone.gcs_online = True
                            self.on_log(
                                f"  ✓ 飞机 #{drone.index} (IP={drone.ip}, "
                                f"sys_id={drone.sys_id}) 被地面站标记为在线!")
                        drone.behavior.gcs_online_time = now_t

                    # msg_id=1: heartbeat_dmd — GCS 对心跳的确认
                    # 对齐固件 mav_channel.cpp:849-1438,500ms 节流 (mav_channel.hpp:29)
                    if info['msg_id'] == 1:
                        now_t = time.time()
                        if not drone.discovered:
                            drone.discovered = True
                            self.on_log(
                                f"  ✓ 飞机 #{drone.index} (IP={drone.ip}, "
                                f"sys_id={drone.sys_id}) 被地面站发现!")
                        drone.behavior.discovered_time = now_t
                        # 已被 GCS 标 Online 的飞机, 收到 GCS 心跳也维持 gcs_online_time
                        # 对齐地面站: GCS 在 ConnectState != DISCONNECTED 时持续发心跳 (UavParser.cs:95)
                        #           → 工具持续收到心跳 = GCS 视角下我仍在线
                        #           → GCS 标 DISCONNECTED 后停止发心跳 → 6s 后工具 ③ 清零 (同步抖动)
                        if drone.gcs_online:
                            drone.behavior.gcs_online_time = now_t
                        if self.respond:
                            now_s = now_t
                            # 500ms 节流:GCS 高频轮询时不每次都回,对齐固件
                            if now_s - drone.behavior.last_send_state_time >= \
                                    DroneBehavior.MIN_SEND_STATE_INTERVAL_S:
                                drone.behavior.last_send_state_time = now_s
                                # 必须回复 packed_state (msg_id=5) 地面站才会显示上线
                                if drone.send_packed_state(self.gcs_ip, self.gcs_port):
                                    self._ps_sent += 1
                                # extend==1 时紧跟 packed_state 发 extend_state
                                if len(info['payload']) >= 12 and info['payload'][11] == 1:
                                    if drone.send_extend_state(self.gcs_ip, self.gcs_port):
                                        self._es_sent += 1

                    # msg_id=3: get_identify_info — GCS 请求身份信息
                    # 对齐固件 mav_channel.cpp:1901-1911,加节流防 GCS 重发请求时打爆
                    elif info['msg_id'] == 3:
                        if self.respond:
                            now_s = time.time()
                            if now_s - drone.behavior.last_send_identify_time >= \
                                    DroneBehavior.MIN_SEND_IDENTIFY_INTERVAL_S:
                                drone.behavior.last_send_identify_time = now_s
                                if drone.send_identify_info(self.gcs_ip, self.gcs_port):
                                    self._id_sent += 1

                    # msg_id=21: param_request_list → 回复 ACK
                    elif info['msg_id'] == 21:
                        if self.respond:
                            if drone.send_param_request_list_ack(self.gcs_ip, self.gcs_port):
                                self._rcs_sent += 1

                    with self._recv_lock:
                        self._recv_total += 1
                except (BlockingIOError, socket.error):
                    continue
                except Exception:
                    continue

            if not got_any:
                time.sleep(0.02)  # 无数据时休眠 20ms

    # ------------------------------------------------------------------
    def _aux_loop(self):
        """1Hz 辅助线程 — 仅推进状态机 + 周期性 FAILSAFE/RAW_IMU 主动上报。

        对齐真实固件 dmd_uav/task/modules/mav/mav_channel.cpp:
          - HEARTBEAT (msg_id=0): 0.33Hz,在 _send_loop 里发,不在这里
          - PACKED_STATE / EXTEND_STATE / IDENTIFY_INFO / RCS:
            **从不主动发**,只在 _recv_loop 收到 GCS heartbeat_dmd (msg_id=1)
            或 GET_IDENTIFY_INFO (msg_id=3) 时被动应答 (含 500ms 节流)。
          - FAILSAFE: 由 sr[]_FAILSAFE 参数控制,默认 1Hz 主动 (stream_serv)
          - RAW_IMU: 由 sr[]_SNSR_RAW 参数控制,默认 0 (不发),可配置
        """
        drones = list(self.swarm)
        active_log = ["1Hz 推进状态机"]
        if self.raw_imu_rate > 0:
            active_log.append(f"+ RAW_IMU×{int(self.raw_imu_rate)}")
        if any(d.behavior.failsafe_mask for d in drones):
            active_log.append("+ FAILSAFE 1Hz")
        active_log.append("| PS/ES/identify 仅 GCS 触发应答(500ms 节流,对齐固件)")
        self.on_log(f"辅助线程启动: {' '.join(active_log)}")
        last_tick = time.time()
        while not self._stop.is_set():
            now = time.time()
            dt = now - last_tick
            if dt >= 1.0:
                last_tick = now
                for drone in drones:
                    drone.tick(dt)
                    # FAILSAFE 1Hz 主动上报 (对齐固件 sr[]_FAILSAFE_DEF=1.0)
                    if drone.behavior.failsafe_mask != 0:
                        if drone.send_failsafe(self.gcs_ip, self.gcs_port):
                            self._fs_sent += 1
                    # RAW_IMU 按配置频率主动上报 (对齐固件 sr[]_SNSR_RAW)
                    if self.raw_imu_rate > 0:
                        for _ in range(int(self.raw_imu_rate)):
                            if drone.send_raw_imu(self.gcs_ip, self.gcs_port):
                                self._raw_sent += 1

                # 每 5 秒输出一次诊断 — 显示 GCS 触发的应答计数
                now = time.time()
                if now - self._last_diag_time >= 5.0:
                    self._last_diag_time = now
                    n = len(drones)
                    parts = [f"GCS触发应答: PS×{self._ps_sent:,} ES×{self._es_sent:,} identify×{self._id_sent:,} RCS×{self._rcs_sent:,}"]
                    if self._fs_sent:
                        parts.append(f"FS×{self._fs_sent:,}")
                    if self._raw_sent:
                        parts.append(f"RAW×{self._raw_sent:,}")
                    if self._send_errors:
                        parts.append(f"⚠错误×{self._send_errors}")
                    parts.append(f"| {n}架")
                    self.on_log(" ".join(parts))
            self._stop.wait(0.1)

    # ------------------------------------------------------------------
    def _send_loop(self):
        """发包线程 — 定时向所有飞机发心跳"""
        drones = list(self.swarm)
        count = len(drones)
        bs = min(self.batch_size, count)
        self._t0 = time.time()

        self.on_log(f"发包线程启动: {count} 架无人机")
        self.on_log(f"目标: {self.gcs_ip}:{self.gcs_port}")
        self.on_log(f"心跳间隔: {self.interval}s, 回复GCS: {'是' if self.respond else '否'}")

        while not self._stop.is_set():
            r0 = time.time()

            for offset in range(0, count, bs):
                if self._stop.is_set():
                    break
                end = min(offset + bs, count)
                for i in range(offset, end):
                    if drones[i].send_heartbeat(self.gcs_ip, self.gcs_port):
                        self._hb_sent += 1

            self._round += 1
            s = self.swarm.summary()
            elp = time.time() - r0
            elp_total = time.time() - self._t0
            rate = s['total_sent'] / elp_total if elp_total > 0 else 0

            self.on_log(
                f"第 {self._round} 轮: 发 {s['total_sent']:,} | "
                f"收 {s['total_recv']:,} | "
                f"①ARP {s.get('discovered_by_ap', 0)}/{s['total']} | "
                f"②心跳 {s['discovered']}/{s['total']} | "
                f"③在线 {s.get('gcs_online', 0)}/{s['total']} | "
                f"{rate:.0f} pps | {elp:.1f}s"
            )

            if self.on_tick:
                self.on_tick(s, rate, elp_total)

            # 第 3 轮后仍未收到任何回复 → 诊断提示
            if self._round == 3 and s['total_recv'] == 0:
                self.on_log("⚠ 已发送 3 轮心跳但未收到任何回复，可能原因:")
                self.on_log("  1. 地面站未运行或不在同一网络 (目标: "
                           f"{self.gcs_ip}:{self.gcs_port})")
                self.on_log("  2. 本机 IP 与地面站不在同一子网 (检查网卡和子网掩码)")
                self.on_log("  3. 防火墙阻止了 UDP 通信 (检查 Windows Defender)")
                self.on_log(f"  4. 地面站未监听端口 {self.gcs_port}")
                self.on_log("  提示: 请确认本机能 ping 通地面站 IP，"
                           "且地面站界面已启动")

            if self.duration > 0 and elp_total >= self.duration:
                break

            remain = self.interval - elp
            if remain > 0 and not self._stop.is_set():
                self._stop.wait(remain)

        s = self.swarm.summary()
        self.on_log(f"发包线程结束: 总发 {s['total_sent']:,}, "
                    f"总收 {s['total_recv']:,}, "
                    f"①ARP {s.get('discovered_by_ap', 0)}/{s['total']}, "
                    f"②心跳 {s['discovered']}/{s['total']}, "
                    f"③在线 {s.get('gcs_online', 0)}/{s['total']}")


# =====================================================================
# 洪水测试执行器 (scapy, 只发不收)
# =====================================================================
class FloodRunner:
    def __init__(self, sender: FloodSender, count: int,
                 start_ip: str, start_mac: str,
                 interval: float, duration: float, batch: int, jitter: bool,
                 on_log=None, on_tick=None):
        self.s = sender; self.count = count
        self._ip_base = ip_to_int(start_ip)
        self._mac_base = int(start_mac.replace(':', '').replace('-', ''), 16)
        self.interval = interval; self.duration = duration
        self.batch = batch; self.jitter = jitter
        self.on_log = on_log or (lambda m: None)
        self.on_tick = on_tick
        self._stop = threading.Event()
        self._thread = None
        self._seq = [random.randint(0, 255) for _ in range(count)]

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self): self._stop.set()

    def running(self): return self._thread and self._thread.is_alive()

    def _run(self):
        c = self.count
        bs = min(self.batch, c)
        self.s.start(); t0 = time.time()
        self.on_log(f"洪水模式: {c} 架, {self.s.dst_ip}:{self.s.dst_port}")
        rnd = 0
        while not self._stop.is_set():
            r0 = time.time()
            for o in range(0, c, bs):
                if self._stop.is_set(): break
                for i in range(o, min(o + bs, c)):
                    self._seq[i] = (self._seq[i] + 1) & 0xFF
                    ss, bm = HB_SYS_STATUS_ACTIVE, HB_BASE_MODE_DISARM
                    if self.jitter and random.random() < 0.2:
                        bm = random.choice([HB_BASE_MODE_DISARM, HB_BASE_MODE_ARMED])
                    # 用 build_heartbeat 默认参数（对齐飞控: type=QUAD, autopilot=DMD_FC,
                    # system_status=ACTIVE, mavlink_version=3, comp_id=1）
                    hb = build_heartbeat((i % 254) + 1, self._seq[i],
                                         system_status=ss, base_mode=bm)
                    sip = int_to_ip(self._ip_base + i)
                    mac = f"{(self._mac_base + i) >> 40 & 0xFF:02X}:" \
                          f"{(self._mac_base + i) >> 32 & 0xFF:02X}:" \
                          f"{(self._mac_base + i) >> 24 & 0xFF:02X}:" \
                          f"{(self._mac_base + i) >> 16 & 0xFF:02X}:" \
                          f"{(self._mac_base + i) >> 8 & 0xFF:02X}:" \
                          f"{(self._mac_base + i) & 0xFF:02X}"
                    self.s.send(sip, mac, hb)
            rnd += 1
            st = self.s.snapshot()
            self.on_log(f"第 {rnd} 轮: {st['packets']:,} 包, "
                        f"{st['rate']:.0f} pps, {time.time() - r0:.1f}s")
            if self.on_tick: self.on_tick(st, st['rate'], time.time() - t0)
            if self.duration > 0 and (time.time() - t0) >= self.duration: break
            remain = self.interval - (time.time() - r0)
            if remain > 0 and not self._stop.is_set():
                self._stop.wait(remain)
        st = self.s.snapshot()
        self.on_log(f"结束: {st['packets']:,} 包, 错误 {st['errors']}, "
                    f"{time.time() - t0:.1f}s")


# =====================================================================
# Scapy 双向模式 (L2 收发) — 无需 IP 别名，无需管理员权限，跨机器通用
# =====================================================================
def get_scapy_iface_list() -> list:
    """获取 Npcap/Scapy 接口列表，兼容 scapy 2.5 / 2.6 / 2.7+

    scapy 2.7+ 将 get_windows_if_list 从 scapy.interfaces 移除，
    必须改用 scapy.arch.windows 或 scapy.interfaces.get_working_ifaces。
    返回统一的 dict 列表 (name / friendly_name / description / ips / mac)。
    """
    # 策略 1: scapy.arch.windows (跨版本最稳定)
    try:
        from scapy.arch.windows import get_windows_if_list
        result = get_windows_if_list()
        if result:
            return result
    except Exception:
        pass

    # 策略 2: scapy.interfaces.get_windows_if_list (scapy 2.5/2.6)
    try:
        from scapy.interfaces import get_windows_if_list as _gwl
        result = _gwl()
        if result:
            return result
    except Exception:
        pass

    # 策略 3: scapy.interfaces.get_working_ifaces (scapy 2.7+)
    try:
        from scapy.interfaces import get_working_ifaces
        ifaces = get_working_ifaces()
        out = []
        for i in ifaces:
            ips_raw = getattr(i, 'ips', {}) or {}
            ips = []
            try:
                for group in ips_raw.values():
                    for ip in group:
                        ips.append(str(ip))
            except Exception:
                pass
            out.append({
                'name': getattr(i, 'network_name', '') or getattr(i, 'name', ''),
                'friendly_name': getattr(i, 'description', '') or getattr(i, 'name', ''),
                'description': getattr(i, 'description', ''),
                'ips': ips,
                'mac': getattr(i, 'mac', '') or '',
            })
        if out:
            return out
    except Exception:
        pass

    # 策略 4: scapy.conf.iface 列表 (兜底)
    try:
        from scapy.config import conf
        if getattr(conf, 'iface', None):
            i = conf.iface
            return [{
                'name': getattr(i, 'network_name', '') or getattr(i, 'name', ''),
                'friendly_name': getattr(i, 'description', '') or getattr(i, 'name', ''),
                'description': getattr(i, 'description', ''),
                'ips': [],
                'mac': getattr(i, 'mac', '') or '',
            }]
    except Exception:
        pass

    return []


def resolve_scapy_iface(windows_iface: str) -> str:
    """将 Windows 网卡名称映射为 Npcap/Scapy 可识别的接口名

    Windows 网卡别名 (如 "以太网 2") 和 Npcap 的 friendly_name
    可能不同，直接传给 scapy 会导致 sniff/sendp 使用错误的接口。

    匹配策略（从严到松）：
      1) 精确匹配 name / friendly_name / description
      2) 单向子串：windows_iface 必须是 val 的子串
         （避免 "以太网 2" 错误命中 "以太网" — 不能让短的 val 反向匹配长的输入）
      3) 多个候选时，取长度最接近 windows_iface 的（最具体）
      4) 通过本机 IP 匹配
      5) 全部失败，返回原值
    """
    if_list = get_scapy_iface_list()
    if not if_list:
        return windows_iface

    def _get(item, key):
        if isinstance(item, dict):
            return item.get(key) or ''
        return getattr(item, key, '') or ''

    # 1) 精确匹配
    for item in if_list:
        for key in ('name', 'friendly_name', 'description'):
            val = _get(item, key)
            if val == windows_iface:
                return _get(item, 'name')

    # 2) 单向子串 + 长度最接近优先（避免歧义）
    candidates = []
    for item in if_list:
        for key in ('friendly_name', 'description', 'name'):
            val = _get(item, key)
            if not val:
                continue
            # 关键：只允许 windows_iface ⊂ val，禁止反向
            # 这样 "以太网 2" 不会误匹配 "以太网"
            if windows_iface in val:
                candidates.append((abs(len(val) - len(windows_iface)), _get(item, 'name')))
                break  # 同一接口找到一个字段匹配即可
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    # 3) 通过 IP 匹配 (本机 IP 所在的接口)
    try:
        my_ip = get_interface_ip(windows_iface)
        if my_ip:
            for item in if_list:
                ips = _get(item, 'ips')
                if not ips:
                    continue
                try:
                    if any(my_ip in str(ip) for ip in ips):
                        return _get(item, 'name')
                except Exception:
                    pass
    except Exception:
        pass

    return windows_iface


def is_local_ip(target_ip: str) -> bool:
    """检测 target_ip 是否是本机某个网卡的 IP（自环场景检测）

    用于判断 GCS 是否运行在本机 — 若是，scapy L2 抓不到该方向的包，
    必须改用 netsh 模式或换机部署。
    """
    if not target_ip:
        return False
    # 快速路径：直接 PowerShell 查所有本机 IP
    try:
        out = subprocess.run(
            ['powershell', '-Command',
             "(Get-NetIPAddress -AddressFamily IPv4).IPAddress"],
            capture_output=True, text=True, timeout=5)
        for line in out.stdout.splitlines():
            line = line.strip()
            if line == target_ip:
                return True
    except Exception:
        pass
    # 慢路径：通过 scapy 接口列表
    try:
        for item in get_scapy_iface_list():
            ips = (item.get('ips', []) if isinstance(item, dict)
                   else getattr(item, 'ips', []) or [])
            for ip in ips:
                if str(ip) == target_ip:
                    return True
    except Exception:
        pass
    return False


def get_real_mac(iface: str) -> str:
    """获取本机网卡的真实 MAC 地址"""
    try:
        import ctypes
        from ctypes import wintypes
        # 用 GetAdaptersInfo 获取第一个匹配网卡的 MAC（纯 socket 方式）
        out = subprocess.run(
            ['powershell', '-Command',
             f"(Get-NetAdapter -Name '{iface}' -ErrorAction SilentlyContinue | "
             "Select-Object -First 1).MacAddress"],
            capture_output=True, text=True, timeout=5)
        mac = out.stdout.strip().replace('-', ':').lower()
        if mac and mac != '00:00:00:00:00:00':
            return mac
    except Exception:
        pass
    return '02:00:00:00:00:01'


def _mac_to_bytes(mac: str) -> str:
    """aa:bb:cc:dd:ee:ff -> '\\xaa\\xbb\\xcc\\xdd\\xee\\xff' (for scapy)"""
    return mac.replace(':', '')


def _mac_add(mac: str, delta: int) -> str:
    """MAC 地址 + delta"""
    val = int(mac.replace(':', '').replace('-', ''), 16) + delta
    return ':'.join(f"{(val >> (5 - i) * 8) & 0xFF:02X}" for i in range(6)).lower()


class ScapyVirtualDrone:
    """虚拟无人机 — scapy L2 模式

    行为（状态机/抖动/消息构建）全部委托给 DroneBehavior；本类只负责 L2 元数据（IP/MAC）。
    与 netsh 的 VirtualDrone 共享同一个 DroneBehavior，行为完全一致。
    """

    def __init__(self, index: int, local_ip: str, local_mac: str,
                 jitter_enabled: bool, field_jitter_pct: float,
                 config: dict = None):
        self.index = index
        self.ip = local_ip
        self.mac = local_mac
        self.port = 14551
        self.sys_id = (index % 254) + 1

        cfg = dict(config or {})
        cfg.setdefault('jitter', jitter_enabled)
        cfg.setdefault('field_pct', field_jitter_pct)
        self.behavior = DroneBehavior(index, self.sys_id, cfg)
        self.seq = self.behavior.seq
        self._ps_count = 0

    # ---- 行为委托 ----
    @property
    def sent(self): return self.behavior.sent
    @sent.setter
    def sent(self, v): self.behavior.sent = v

    @property
    def recv(self): return self.behavior.recv
    @recv.setter
    def recv(self, v): self.behavior.recv = v

    @property
    def discovered(self): return self.behavior.discovered
    @discovered.setter
    def discovered(self, v): self.behavior.discovered = v

    @property
    def discovered_time(self): return self.behavior.discovered_time
    @discovered_time.setter
    def discovered_time(self, v): self.behavior.discovered_time = v

    @property
    def discovered_by_ap(self): return self.behavior.discovered_by_ap
    @discovered_by_ap.setter
    def discovered_by_ap(self, v): self.behavior.discovered_by_ap = v

    @property
    def gcs_online(self): return self.behavior.gcs_online
    @gcs_online.setter
    def gcs_online(self, v): self.behavior.gcs_online = v

    @property
    def last_recv_time(self): return self.behavior.last_recv_time
    @last_recv_time.setter
    def last_recv_time(self, v): self.behavior.last_recv_time = v

    @property
    def last_recv_msg_id(self): return self.behavior.last_recv_msg_id
    @last_recv_msg_id.setter
    def last_recv_msg_id(self, v): self.behavior.last_recv_msg_id = v

    def tick(self, dt: float):
        self.behavior.tick(dt)
        self.seq = self.behavior.seq

    # ---- 统一构建接口（保持与旧版兼容的方法名）----
    def build(self, msg_name: str) -> bytes:
        data = self.behavior.build(msg_name)
        self.seq = self.behavior.seq
        return data

    def build_heartbeat(self) -> bytes:
        return self.build('heartbeat')

    def build_packed_state_jittered(self) -> bytes:
        return self.build('packed_state')

    def build_extend_state_jittered(self) -> bytes:
        return self.build('extend_state')

    def build_failsafe(self) -> bytes:
        return self.build('failsafe')

    def build_remaining_capacity(self) -> bytes:
        return self.build('remaining_capacity')

    def build_raw_imu(self) -> bytes:
        return self.build('raw_imu')

    def build_identify_info(self) -> bytes:
        return self.build('identify_info')

    def build_param_request_list_ack(self) -> bytes:
        return self.build('param_request_list_ack')


class ScapyDroneSwarm:
    """管理 N 架 scapy 虚拟无人机（无需 IP 别名，直接通过 L2 发帧）"""

    def __init__(self, count: int, start_ip: str, start_mac: str,
                 jitter: bool = True, field_jitter_pct: float = 20.0,
                 config: dict = None, log_fn=None):
        self._log = log_fn or (lambda m: None)
        self._drones = []
        self._by_ip = {}  # IP → drone 快速查找

        base_ip = ip_to_int(start_ip)
        for i in range(count):
            ip = int_to_ip(base_ip + i)
            mac = _mac_add(start_mac, i)
            drone = ScapyVirtualDrone(i, ip, mac, jitter, field_jitter_pct,
                                      config=config)
            self._drones.append(drone)
            self._by_ip[ip] = drone

        self._log(f"创建完成: {len(self._drones)} 架虚拟无人机 "
                  f"(scapy L2, IP {start_ip} ~ {int_to_ip(base_ip + count - 1)}, "
                  f"无需 netsh)")

    def __len__(self): return len(self._drones)
    def __iter__(self): return iter(self._drones)
    def get_by_ip(self, ip: str): return self._by_ip.get(ip)

    def summary(self) -> dict:
        total_sent = sum(d.sent for d in self._drones)
        total_recv = sum(d.recv for d in self._drones)
        discovered = sum(1 for d in self._drones if d.discovered)
        discovered_by_ap = sum(1 for d in self._drones if d.discovered_by_ap)
        gcs_online = sum(1 for d in self._drones if d.gcs_online)
        return {'total_sent': total_sent, 'total_recv': total_recv,
                'discovered': discovered,
                'discovered_by_ap': discovered_by_ap,
                'gcs_online': gcs_online,
                'total': len(self._drones)}


class ScapyBidirectionalRunner:
    """Scapy L2 双向模式：伪造 IP/MAC 发包 + sniff 收包，无需 netsh/IP 别名

    要求: Npcap 已安装 (scapy 依赖)
    """

    def __init__(self, swarm: ScapyDroneSwarm, gcs_ip: str, gcs_port: int,
                 real_mac: str, gcs_mac: str, iface: str,
                 interval: float = 3.0, duration: float = 0.0,
                 batch_size: int = 50, respond: bool = True,
                 raw_imu_rate: float = 0.0,
                 packed_state_rate: float = 5.0,
                 extend_state_rate: float = 2.0,
                 on_log=None, on_tick=None):
        self.swarm = swarm
        self.gcs_ip = gcs_ip
        self.gcs_port = gcs_port
        self.real_mac = real_mac
        self.gcs_mac = gcs_mac or 'ff:ff:ff:ff:ff:ff'
        self.iface = iface
        self.interval = interval
        self.duration = duration
        self.batch_size = batch_size
        self.respond = respond
        self.raw_imu_rate = raw_imu_rate
        self.packed_state_rate = packed_state_rate
        self.extend_state_rate = extend_state_rate
        self.on_log = on_log or (lambda m: None)
        self.on_tick = on_tick
        self._stop = threading.Event()
        self._send_thread = None
        self._aux_thread = None
        self._sniffer = None          # P1: 单合并 sniffer (业务+诊断+raw+ARP), BPF 内核过滤
        self._diag_total = 0
        self._diag_gcs_pkts = 0
        self._raw_total = 0           # 与 _diag_total 等价 (合并后只有一条路径), 保留向后兼容日志
        self._raw_samples = []
        self._arp_seen = 0
        self._arp_answered = 0
        self._drone_ips = {d.ip for d in swarm}
        self._round = 0
        self._t0 = 0.0
        self._recv_lock = threading.Lock()
        self._recv_total = 0
        self._scapy_ok = False
        # 浮点频率累加器（支持 0.5Hz 等小数）
        self._ps_acc = 0.0
        self._es_acc = 0.0
        # 应答发送计数（诊断用 — 显示 GCS 触发的应答次数）
        self._ps_sent = 0
        self._es_sent = 0
        self._rcs_sent = 0
        self._id_sent = 0
        self._hb_sent = 0
        self._fs_sent = 0
        self._raw_sent = 0
        self._send_errors = 0
        # 状态转换日志节流: 1000+ 架时, "✓ 飞机 #X 被发现/在线" 会刷屏阻塞 GUI Text widget
        # 只记前 N 条单架消息, 之后的转换靠每轮 summary (②心跳 X/N, ③在线 X/N) 体现
        self._disc_log_count = 0
        self._online_log_count = 0
        self._TRANSITION_LOG_PER_TYPE = 20   # 前 20 架单条记录, 之后静默
        self._last_diag_time = time.time()
        # P0 性能优化: 应答入队 + 批量 sendp
        # _resp_q 单生产 (_on_packet) 单消费 (_send_loop),deque 原子操作无需锁
        # maxlen=count*2: 每架最多排队 packed_state + extend_state 各 1 条
        self._resp_q = deque(maxlen=max(len(swarm) * 2, 100))
        self._resp_dropped = 0
        self._resp_queued = 0
        self._send_total_us = 0.0
        self._send_rounds = 0

        try:
            from scapy.all import Ether, IP, UDP, sendp
            from scapy.all import AsyncSniffer
            self._Ether = Ether
            self._IP = IP
            self._UDP = UDP
            self._sendp = sendp
            self._AsyncSniffer = AsyncSniffer
            self._scapy_ok = True
        except ImportError:
            self.on_log("错误: scapy 未安装，请执行 pip install scapy")

    @property
    def available(self) -> bool:
        return self._scapy_ok

    def start(self):
        if not self._scapy_ok:
            return
        self._stop.clear()

        # 将 Windows 网卡名映射为 Npcap/Scapy 可识别的接口名
        resolved = resolve_scapy_iface(self.iface)
        if resolved != self.iface:
            self.on_log(f"网卡映射: '{self.iface}' → '{resolved}' (Npcap)")
            self.iface = resolved

        # 诊断: 输出 Npcap 接口列表
        try:
            if_list = get_scapy_iface_list()
            self.on_log(f"Npcap 接口数: {len(if_list)}")
            for item in if_list:
                if isinstance(item, dict):
                    name = item.get('name', '?')
                    friendly = item.get('friendly_name', '?')
                    desc = item.get('description', '?')
                    ips = item.get('ips', '?')
                    mac = item.get('mac', '?')
                else:
                    name = getattr(item, 'network_name', '?')
                    friendly = getattr(item, 'description', '?') or getattr(item, 'name', '?')
                    desc = getattr(item, 'description', '?')
                    ips = getattr(item, 'ips', '?')
                    mac = getattr(item, 'mac', '?')
                self.on_log(f"  name={name}")
                self.on_log(f"    friendly={friendly}")
                self.on_log(f"    desc={desc}")
                self.on_log(f"    ips={ips} mac={mac}")
            self.on_log(f"当前使用: {self.iface}")
        except Exception as e:
            self.on_log(f"Npcap 接口列表获取失败: {e}")

        # 自环检测: GCS IP 若为本机某网卡 IP，scapy L2 抓不到该方向包
        if is_local_ip(self.gcs_ip):
            self.on_log(f"⚠ GCS IP {self.gcs_ip} 是本机网卡 IP — 自环场景")
            self.on_log("  scapy L2 无法捕获本机→本机的 UDP 回包")
            self.on_log("  建议: 1) 换机器部署 GCS  2) 切换到 netsh 模式 (需管理员)")

        self._start_sniffer()        # P1: 合并后的单 sniffer, 内含 BPF + 分流 (业务/诊断/raw/ARP)
        self._send_gratuitous_arp()
        self._aux_thread = threading.Thread(target=self._aux_loop, daemon=True)
        self._aux_thread.start()
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._send_thread.start()

    def stop(self):
        self._stop.set()
        if self._sniffer:
            try:
                self._sniffer.stop()
            except Exception:
                pass
            self._sniffer = None
        # P1: 原 _arp_sniffer / _diag_sniffer / _raw_sniffer 已合并进 _sniffer, 不再单独 stop

    def running(self) -> bool:
        return (self._send_thread and self._send_thread.is_alive()) or \
               (self._aux_thread and self._aux_thread.is_alive())

    # ------------------------------------------------------------------
    def _aux_loop(self):
        """1Hz 辅助线程 — 仅推进状态机 + 周期性 FAILSAFE/RAW_IMU 主动上报。

        对齐真实固件 dmd_uav/task/modules/mav/mav_channel.cpp:
          - HEARTBEAT (msg_id=0): 0.33Hz,在 _send_loop 里发,不在这里
          - PACKED_STATE / EXTEND_STATE / IDENTIFY_INFO / RCS:
            **从不主动发**,只在 _on_packet 收到 GCS heartbeat_dmd (msg_id=1)
            或 GET_IDENTIFY_INFO (msg_id=3) 时被动应答 (含 500ms 节流)。
          - FAILSAFE: 由 sr[]_FAILSAFE 参数控制,默认 1Hz 主动 (stream_serv)
          - RAW_IMU: 由 sr[]_SNSR_RAW 参数控制,默认 0 (不发),可配置
        """
        drones = list(self.swarm)
        active_log = ["1Hz 推进状态机"]
        if self.raw_imu_rate > 0:
            active_log.append(f"+ RAW_IMU×{int(self.raw_imu_rate)}")
        if any(d.behavior.failsafe_mask for d in drones):
            active_log.append("+ FAILSAFE 1Hz")
        active_log.append("| PS/ES/identify 仅 GCS 触发应答(500ms 节流,对齐固件)")
        active_log.append("+ 每 60s 重发免费 ARP (防 AP ARP 表过期)")
        self.on_log(f"辅助线程启动: {' '.join(active_log)}")
        last_tick = time.time()
        last_arp_refresh = time.time()
        while not self._stop.is_set():
            now = time.time()
            dt = now - last_tick
            if dt >= 1.0:
                last_tick = now
                # 每 60s 重发免费 ARP (防 AP/交换机 ARP 表过期,OpenWrt 默认 20min,但企业 AP 可能更短)
                if now - last_arp_refresh >= 60.0:
                    last_arp_refresh = now
                    self._send_gratuitous_arp()
                for drone in drones:
                    drone.tick(dt)
                    # FAILSAFE 1Hz 主动上报 (对齐固件 sr[]_FAILSAFE_DEF=1.0)
                    if drone.behavior.failsafe_mask != 0:
                        self._send_to_gcs(drone, drone.build_failsafe())
                        self._fs_sent += 1
                    # RAW_IMU 按配置频率主动上报 (对齐固件 sr[]_SNSR_RAW)
                    if self.raw_imu_rate > 0:
                        for _ in range(int(self.raw_imu_rate)):
                            self._send_to_gcs(drone, drone.build_raw_imu())
                            self._raw_sent += 1

                # 每 5 秒输出一次诊断 — 显示 GCS 触发的应答计数
                now = time.time()
                if now - self._last_diag_time >= 5.0:
                    self._last_diag_time = now
                    n = len(drones)
                    discovered = sum(1 for d in drones if d.discovered)
                    disc_by_ap = sum(1 for d in drones if d.discovered_by_ap)
                    gcs_online = sum(1 for d in drones if d.gcs_online)
                    parts = [f"GCS触发应答: PS×{self._ps_sent:,} ES×{self._es_sent:,} identify×{self._id_sent:,} RCS×{self._rcs_sent:,}"]
                    if self._fs_sent:
                        parts.append(f"FS×{self._fs_sent:,}")
                    if self._raw_sent:
                        parts.append(f"RAW×{self._raw_sent:,}")
                    if self._send_errors:
                        parts.append(f"⚠错误×{self._send_errors}")
                    parts.append(f"| {n}架 | ①ARP {disc_by_ap}/{n} | ②心跳 {discovered}/{n} | ③在线 {gcs_online}/{n}")
                    if gcs_online == 0 and self._hb_sent > n:
                        if discovered > 0:
                            parts.append("⚠心跳到但无在线 - GCS未发非心跳MAVLink, 检查packed_state内容/sys_id/源IP/源MAC")
                        elif disc_by_ap > 0:
                            parts.append("⚠ARP到但无心跳 - 检查GCS心跳/IP/端口")
                        else:
                            parts.append("⚠AP/GCS未识别任何飞机 - 检查网卡/防火墙/自环/IP/MAC")
                    self.on_log(" ".join(parts))
            self._stop.wait(0.1)

    # ------------------------------------------------------------------
    def _start_sniffer(self):
        """P1 优化: 单 AsyncSniffer + BPF 内核过滤 + 回调分流, 替代原 4 个 sniffer.

        BPF filter 让 Npcap 在内核态只把需要的包传到 Python:
          - ARP (虚拟 IP 的 ARP 请求)
          - UDP 来自 GCS IP 且目标端口 14551 (GCS→drone 业务包)
        原 4 个 sniffer 抓同一网卡 4 遍, Python 层重复解析, 大规模时 CPU 浪费 3/4.
        合并后 _diag_total 语义变为"通过 BPF 的包数" (不含被内核过滤掉的广播/TCP/ICMP).
        """
        try:
            from scapy.all import AsyncSniffer, ARP, IP, UDP, Ether, IPv6
            _gcs_ip = self.gcs_ip
            _on_packet = self._on_packet
            _on_arp = self._on_arp
            _self = self
            _samples = []

            def _dispatch(pkt):
                # 诊断统计: 通过 BPF 的所有包 (业务 UDP + ARP)
                _self._diag_total += 1
                # raw 样本 (前 10 包, 与原 _raw_sniffer 行为一致)
                if len(_samples) < 10:
                    try:
                        etype = pkt[Ether].type if Ether in pkt else None
                        src = dst = proto = ""
                        if IP in pkt:
                            src = pkt[IP].src; dst = pkt[IP].dst
                            proto = {6: 'TCP', 17: 'UDP', 1: 'ICMP'}.get(pkt[IP].proto, f"IP({pkt[IP].proto})")
                        elif ARP in pkt:
                            src = pkt[ARP].psrc; dst = pkt[ARP].pdst; proto = 'ARP'
                        elif IPv6 in pkt:
                            src = pkt[IPv6].src; dst = pkt[IPv6].dst; proto = 'IPv6'
                        _samples.append(f"  [{len(_samples)}] EtherType={etype:#06x} {proto} {src} -> {dst}")
                    except Exception:
                        _samples.append(f"  [{len(_samples)}] (parse error)")
                    _self._raw_samples = _samples

                # 分流: ARP 优先 (无 IP 头)
                if ARP in pkt:
                    _on_arp(pkt)
                    return
                if IP in pkt and UDP in pkt:
                    if pkt[IP].src == _gcs_ip:
                        _self._diag_gcs_pkts += 1
                        _on_packet(pkt)
                    return

            # BPF filter: arp 或 来自 GCS IP 的 UDP 目标端口 14551
            # Npcap 在 Windows 上 BPF 内核过滤可靠
            bpf = f"(arp) or (udp and src host {_gcs_ip} and dst port 14551)"

            self._sniffer = AsyncSniffer(
                iface=self.iface,
                filter=bpf,
                prn=_dispatch,
                store=False,
            )
            self._sniffer.start()
            self.on_log(f"合并嗅探器启动 (BPF 内核过滤: {bpf})")
        except Exception as e:
            self.on_log(f"启动嗅探器失败: {e}")
            # BPF 失败时退化为无过滤 + Python 分流 (兜底, 不让工具不可用)
            try:
                from scapy.all import AsyncSniffer, ARP, IP, UDP
                _gcs_ip = self.gcs_ip
                _on_packet = self._on_packet
                _on_arp = self._on_arp
                _self = self
                def _dispatch_no_bpf(pkt):
                    _self._diag_total += 1
                    if ARP in pkt:
                        _on_arp(pkt); return
                    if IP in pkt and UDP in pkt and pkt[IP].src == _gcs_ip:
                        _self._diag_gcs_pkts += 1
                        _on_packet(pkt)
                self._sniffer = AsyncSniffer(iface=self.iface, filter="",
                                             prn=_dispatch_no_bpf, store=False)
                self._sniffer.start()
                self.on_log("⚠ BPF 启动失败, 退化为 Python 过滤 (性能较低)")
            except Exception as e2:
                self.on_log(f"嗅探器兜底启动也失败: {e2}")

    def _on_arp(self, pkt):
        """ARP 请求回调 — GCS/AP 询问某飞机 IP 的 MAC 时,回复该飞机自己的 MAC

        对齐真实固件:每架飞机的 WiFi 模块独立响应 ARP,每架一个 MAC。
        hwsrc 必须用 drone.mac,不能用 real_mac,否则 AP/GCS ARP 表里
        所有飞机 IP 指向同一个 MAC (压测 AP 失真)。
        """
        try:
            from scapy.all import ARP, Ether
            if ARP not in pkt:
                return
            arp = pkt[ARP]
            if arp.op != 1:  # 1 = who-has (request)
                return
            self._arp_seen += 1
            target_ip = arp.pdst
            drone = self.swarm.get_by_ip(target_ip)
            if drone is None:
                return
            self._arp_answered += 1
            # 标记 AP/GCS 已识别该飞机 (ARP 查询 = 该 IP 已在 AP/GCS 视野中)
            if not drone.behavior.discovered_by_ap:
                drone.behavior.discovered_by_ap = True
                self.on_log(
                    f"  ◆ 飞机 #{drone.index} (IP={drone.ip}) 进入 AP ARP 表")
            reply = (Ether(src=drone.mac, dst=arp.hwsrc) /
                     ARP(op=2, hwsrc=drone.mac, psrc=target_ip,
                         hwdst=arp.hwsrc, pdst=arp.psrc))
            self._sendp(reply, iface=self.iface, verbose=False)
        except Exception:
            pass

    def _send_gratuitous_arp(self):
        """发送免费 ARP,预填 AP/交换机/GCS 的 ARP 表

        对齐真实固件 lwip 自动发 gratuitous ARP 的行为
        (mt793x/lwip/src/core/netif.c:898-901 etharp_gratuitous)。
        飞机静态配 IP 后,lwip 立即广播 ARP Request,源/目标 IP 都是自己。

        ⚠ hwsrc 必须用 drone.mac,不能用 real_mac。
        否则 AP 的 ARP 表里所有飞机 IP 会指向同一个 MAC (工具机器的 MAC),
        真实场景每架飞机一个独立 MAC,且压测 AP 时要让 AP 看到真实的 MAC 数量。
        """
        try:
            from scapy.all import ARP, Ether
            count = 0
            for drone in self.swarm:
                # ARP op=1 是 request,op=2 是 reply。
                # lwip 的 gratuitous 用 request (etharp_request 给自己 IP)
                # 但很多设备对 ARP reply 接受度更高,这里发 request 兼容性最好
                garp = (Ether(src=drone.mac, dst='ff:ff:ff:ff:ff:ff') /
                        ARP(op=1, hwsrc=drone.mac, psrc=drone.ip,
                            hwdst='00:00:00:00:00:00', pdst=drone.ip))
                self._sendp(garp, iface=self.iface, verbose=False)
                count += 1
            self.on_log(f"已发送 {count} 个免费 ARP (每架飞机独立 MAC,预填 AP/GCS ARP 表)")
        except Exception as e:
            self.on_log(f"发送免费 ARP 失败: {e}")

    def _on_packet(self, pkt):
        """scapy 嗅探回调 — 收到 GCS → Drone 的包"""
        try:
            from scapy.all import IP, UDP, Raw
            if IP not in pkt or UDP not in pkt:
                return
            dst_ip = pkt[IP].dst
            drone = self.swarm.get_by_ip(dst_ip)
            if drone is None:
                return

            raw_data = bytes(pkt[Raw].load) if Raw in pkt else bytes(pkt[UDP].payload)
            info = parse_maVLink_header(raw_data)
            if info is None:
                return

            drone.recv += 1
            drone.last_recv_time = time.time()
            drone.last_recv_msg_id = info['msg_id']

            # 收到任何非 heartbeat_dmd (msg_id != 1) 的 MAVLink → GCS 已把我当在线在交互
            # 对齐地面站 UavParser.receive.cs:25-30 状态机: 收到任意 MAVLink → WORKING → Online
            # 6s 内未再收到 GCS 业务消息 → _refresh_online_counters 清零 (对齐 udpTimeout=6000ms)
            if info['msg_id'] != 1:
                now_t = time.time()
                if not drone.gcs_online:
                    drone.gcs_online = True
                    # 日志节流: 前 N 架单条记录, 之后静默 (1000+ 架刷屏会阻塞 Tk Text)
                    if self._online_log_count < self._TRANSITION_LOG_PER_TYPE:
                        self._online_log_count += 1
                        self.on_log(
                            f"  ✓ 飞机 #{drone.index} (IP={drone.ip}, "
                            f"sys_id={drone.sys_id}) 被地面站标记为在线!")
                drone.behavior.gcs_online_time = now_t

            # msg_id=1: heartbeat_dmd → 回复 packed_state + (extend==1 时) extend_state
            # 对齐固件 mav_channel.cpp:849-1438,500ms 节流 (mav_channel.hpp:29)
            if info['msg_id'] == 1:
                now_t = time.time()
                if not drone.discovered:
                    drone.discovered = True
                    if self._disc_log_count < self._TRANSITION_LOG_PER_TYPE:
                        self._disc_log_count += 1
                        self.on_log(
                            f"  ✓ 飞机 #{drone.index} (IP={drone.ip}, "
                            f"sys_id={drone.sys_id}) 被地面站发现!")
                drone.behavior.discovered_time = now_t
                # 已被 GCS 标 Online 的飞机, 收到 GCS 心跳也维持 gcs_online_time
                # 对齐地面站: GCS 在 ConnectState != DISCONNECTED 时持续发心跳 (UavParser.cs:95)
                #           → 工具持续收到心跳 = GCS 视角下我仍在线
                #           → GCS 标 DISCONNECTED 后停止发心跳 → 6s 后工具 ③ 清零 (同步抖动)
                if drone.gcs_online:
                    drone.behavior.gcs_online_time = now_t
                if self.respond:
                    now_s = now_t
                    # 500ms 节流:GCS 高频轮询时不每次都回,对齐固件
                    if now_s - drone.behavior.last_send_state_time >= \
                            DroneBehavior.MIN_SEND_STATE_INTERVAL_S:
                        drone.behavior.last_send_state_time = now_s
                        # P0 优化: 改入队由 _send_loop 批量发, 不再阻塞 sniffer 回调
                        self._enqueue_resp(
                            drone, drone.build_packed_state_jittered())
                        self._ps_sent += 1
                        # extend==1 时紧跟 packed_state 发,对齐 mav_channel.cpp:1289-1435
                        if len(info['payload']) >= 12 and info['payload'][11] == 1:
                            self._enqueue_resp(
                                drone, drone.build_extend_state_jittered())
                            self._es_sent += 1

            # msg_id=3: get_identify_info → 回复 identify_info
            # 对齐固件 mav_channel.cpp:1901-1911,加节流防 GCS 重发请求时打爆
            elif info['msg_id'] == 3:
                if self.respond:
                    now_s = time.time()
                    if now_s - drone.behavior.last_send_identify_time >= \
                            DroneBehavior.MIN_SEND_IDENTIFY_INTERVAL_S:
                        drone.behavior.last_send_identify_time = now_s
                        self._send_to_gcs(drone, drone.build_identify_info())
                        self._id_sent += 1

            # msg_id=21: param_request_list → 回复 ACK
            elif info['msg_id'] == 21:
                if self.respond:
                    self._send_to_gcs(drone, drone.build_param_request_list_ack())
                    self._rcs_sent += 1

            with self._recv_lock:
                self._recv_total += 1
        except Exception:
            pass

    def _build_packet(self, drone: ScapyVirtualDrone, data: bytes):
        """构造一帧 scapy Packet (Ether/IP/UDP/data), 不发送.
        由 _send_loop 批量收集后单次 sendp([pkts]) 发出, 减少 N 次系统调用到 1 次."""
        return (self._Ether(src=self.real_mac, dst=self.gcs_mac) /
                self._IP(src=drone.ip, dst=self.gcs_ip) /
                self._UDP(sport=14551, dport=self.gcs_port) / data)

    def _enqueue_resp(self, drone: ScapyVirtualDrone, data: bytes):
        """应答包入队, 由 _send_loop drain 后与 heartbeat 合并批量发送.
        deque(maxlen=N) 满时自动丢弃最老应答 (新数据更重要)."""
        qlen_before = len(self._resp_q)
        self._resp_q.append((drone, data))
        self._resp_queued += 1
        if len(self._resp_q) <= qlen_before:
            # deque 已满, 老应答被丢弃
            self._resp_dropped += 1

    def _send_to_gcs(self, drone: ScapyVirtualDrone, data: bytes):
        """[兼容接口] 立即单帧发送 — 仅供 _aux_loop (FAILSAFE/RAW_IMU 主动推送) 等不在 _send_loop 批量路径的调用点使用.
        _on_packet 收到的 GCS 触发应答改走 _enqueue_resp 入队, 不再走这里."""
        try:
            pkt = self._build_packet(drone, data)
            self._sendp(pkt, iface=self.iface, verbose=False)
            drone.sent += 1
        except Exception as e:
            self._send_errors += 1
            if self._send_errors <= 5:
                self.on_log(f"⚠ 发送失败 #{self._send_errors}: {e}")
            elif self._send_errors == 6:
                self.on_log("⚠ 发送错误过多,后续将不再打印 (计数仍累加)")

    # ------------------------------------------------------------------
    def _send_loop(self):
        drones = list(self.swarm)
        count = len(drones)
        self._t0 = time.time()

        self.on_log(f"发包线程启动: {count} 架无人机 (scapy L2, 批量 sendp)")
        self.on_log(f"本机 MAC={self.real_mac}, GCS={self.gcs_ip}:{self.gcs_port}")
        self.on_log(f"心跳间隔: {self.interval}s")

        while not self._stop.is_set():
            r0 = time.time()

            # P0 优化: 每轮 collect heartbeat + drain 应答队列, 单次 sendp([pkts]) 批量发
            # scapy sendp(list) 内部复用 L2socket, 把 N 次系统调用压到 1 次 socket open/close
            pkts = []
            for i in range(count):
                if self._stop.is_set():
                    break
                d = drones[i]
                pkts.append(self._build_packet(d, d.build_heartbeat()))
                d.sent += 1
                self._hb_sent += 1
            # drain 应答队列 (sniffer 回调入队的 packed_state/extend_state)
            # P1.5 修复: cap 每轮 drain 上限为 count, 避免积压时构包耗时而拖慢心跳节奏
            # 心跳是 keep-online 必发 (msg_id=0, 3s 间隔), 应答是 best-effort — 心跳优先
            # 应答超 cap 时 deque(maxlen=count*2) 自动丢老应答 (sniffer 端 _enqueue_resp 计数)
            max_resp = int(count * DroneBehavior.MAX_RESP_PER_ROUND_FACTOR)
            drained = 0
            while drained < max_resp:
                try:
                    d, data = self._resp_q.popleft()
                except IndexError:
                    break
                pkts.append(self._build_packet(d, data))
                d.sent += 1
                drained += 1

            # 分批 sendp, 每批 ≤1000 帧避免内存峰值
            send_us = 0.0
            BATCH = 1000
            for i in range(0, len(pkts), BATCH):
                chunk = pkts[i:i + BATCH]
                if not chunk:
                    continue
                t_send0 = time.perf_counter()
                try:
                    self._sendp(chunk, iface=self.iface, verbose=False)
                except Exception as e:
                    self._send_errors += 1
                    if self._send_errors <= 5:
                        self.on_log(f"⚠ 批量发送失败 #{self._send_errors}: {e}")
                    elif self._send_errors == 6:
                        self.on_log("⚠ 发送错误过多,后续将不再打印 (计数仍累加)")
                send_us += (time.perf_counter() - t_send0) * 1e6
            self._send_total_us += send_us
            self._send_rounds += 1

            self._round += 1
            s = self.swarm.summary()
            elp = time.time() - r0
            elp_total = time.time() - self._t0
            rate = s['total_sent'] / elp_total if elp_total > 0 else 0
            avg_send_ms = (self._send_total_us / self._send_rounds / 1000.0) \
                if self._send_rounds > 0 else 0.0

            self.on_log(
                f"第 {self._round} 轮: 发 {s['total_sent']:,} | "
                f"收 {s['total_recv']:,} | "
                f"①ARP {s['discovered_by_ap']}/{s['total']} | "
                f"②心跳 {s['discovered']}/{s['total']} | "
                f"③在线 {s.get('gcs_online', 0)}/{s['total']} | "
                f"{rate:.0f} pps | {elp:.1f}s | "
                f"sendp={avg_send_ms:.0f}ms/轮 | "
                f"应答入队={self._resp_queued} 离队={self._resp_queued - len(self._resp_q)} 丢弃={self._resp_dropped}"
                f"{' | 诊断: raw=' + str(self._raw_total) + ' snif=' + str(self._diag_total) + ' gcs=' + str(self._diag_gcs_pkts) + ' arp=' + str(self._arp_seen) + '/' + str(self._arp_answered) if s['total_recv'] == 0 else ''}"
            )

            if self.on_tick:
                self.on_tick(s, rate, elp_total)

            # 诊断: 第1轮后输出 raw sniffer 样本包
            if self._round == 1 and self._raw_samples:
                self.on_log("raw 嗅探器前 10 包样本:")
                for line in self._raw_samples:
                    self.on_log(line)

            # 诊断提示
            if self._round == 3 and s['total_recv'] == 0:
                self.on_log("⚠ 已发送 3 轮心跳但未收到任何回复，可能原因:")
                self.on_log("  1. 地面站未运行或未监听端口")
                self.on_log("  2. GCS MAC 不正确 (尝试不用填，自动用广播)")
                self.on_log("  3. 防火墙拦截了 UDP 通信")
                self.on_log("  4. Npcap 未安装或网卡选择不正确")

            if self.duration > 0 and elp_total >= self.duration:
                break

            remain = self.interval - elp
            if remain > 0 and not self._stop.is_set():
                self._stop.wait(remain)

        s = self.swarm.summary()
        self.on_log(f"发包线程结束: 总发 {s['total_sent']:,}, "
                    f"总收 {s['total_recv']:,}, "
                    f"①ARP {s.get('discovered_by_ap', 0)}/{s['total']}, "
                    f"②心跳 {s['discovered']}/{s['total']}, "
                    f"③在线 {s.get('gcs_online', 0)}/{s['total']}")


# =====================================================================
# GUI
# =====================================================================
try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    from tkinter import font as tkfont
    HAS_TK = True
except ImportError:
    HAS_TK = False

GS_DEFAULT_IP = "172.16.200.1"
GS_DEFAULT_PORT = 14550
DRONE_PORT = 14551


class App:
    def __init__(self, root: tk.Tk, cluster_mode: bool = False):
        self.root = root
        self.cluster_mode = cluster_mode
        title_suffix = "集群 Master" if cluster_mode else "单机"
        self.root.title(f"DGCS 地面站压力测试工具 v{TOOL_VERSION} [{title_suffix}] — 测试开发部")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._alias_mgr = None
        self._runner = None
        self._swarm = None
        self._flood_sender = None
        self._poll_id = None

        # 集群 master 服务器 (仅 cluster_mode=True 时实例化)
        self._master_server = None
        self._cluster_poll_id = None  # 集群模式下 500ms 轮询 slave 列表

        self._setup_style()
        self._build()

        # 启动横幅：用途 / 使用方法 / 注意事项
        self._print_intro()

        if cluster_mode:
            self._start_master_server()

        # 枚举本机所有网卡 → 填充下拉框
        self._refresh_iface_combo()

        # 默认选默认路由网卡；若不存在则退回第一项
        iface = ''
        if self._iface_items:
            default_item = next((x for x in self._iface_items if x['is_default']), None)
            iface = default_item['name'] if default_item else self._iface_items[0]['name']
            # 同步下拉框显示
            for i, item in enumerate(self._iface_items):
                if item['name'] == iface:
                    self._cb_iface.current(i)
                    break
        if not iface:
            iface = get_active_interface()
            self._v_iface.set(iface)

        if cluster_mode:
            self._log(f"集群 Master 模式 — 监听 TCP {CLUSTER_PORT}, 等待 slave 连接")
            self._log(f"  启动 slave 示例: python dgcs_stress_test.py slave --master={get_interface_ip(iface)}:{CLUSTER_PORT} \\")
            self._log(f"                       --count=1000 --start-ip=192.168.1.10 --start-mac=00:00:00:00:00:01 \\")
            self._log(f"                       --iface=<scapy 网卡> --gcs-ip=<地面站 IP>")
            self._log(f"  所有 slave 连上后, 点 ▶开始测试 广播 start 指令")
        else:
            lip = get_interface_ip(iface)
            rmac = get_real_mac(iface)
            self._v_real_mac = rmac
            self._log(f"默认网卡: {iface}  |  本机 IP: {lip}  |  MAC: {rmac}")
            self._log('就绪 — 如地面站看不到飞机，请从下拉框切换到实际连 GCS 的网卡')

        # 首次自动填充 IP 起始 (按 AP/网关 IP + 本机 IP 算同子网地址)
        self._auto_suggest_start_ip()

        # 等所有控件都建好之后再按"内容自然高度"撑开窗口,避免打开时被裁剪
        self._fit_window_to_content()

        # 集群模式启动 slave 列表轮询
        if cluster_mode:
            self._cluster_poll()

    # ------------------------------------------------------------------
    def _fit_window_to_content(self):
        """按内容自然尺寸撑开窗口 — 打开即看到全貌,不被裁剪

        1. update_idletasks() 让 Tk 计算每个控件的 reqwidth/reqheight
        2. 取主容器的 reqsize 作为窗口目标 (含全部 LabelFrame + 日志)
        3. 不超过屏幕 - 边距;若超过则按屏幕高度截断 (用户可滚动/手动放大)
        4. 水平居中,垂直略偏上 (留出任务栏视觉舒适区)
        """
        self.root.update_idletasks()
        # 用主容器 reqsize,而非 root.reqsize (后者受当前 geometry 影响)
        req_w = max(self.root.winfo_reqwidth(), 820)
        req_h = max(self.root.winfo_reqheight(), 700)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # 屏幕边距: 横向 60px, 纵向 40px (尽量撑满,留出任务栏)
        w = min(req_w, sw - 60)
        h = min(req_h, sh - 40)
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2 - 20)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(820, 700)

    # ------------------------------------------------------------------
    def _setup_style(self):
        """配置 ttk 样式: LabelFrame 标题加粗加大,与内部文字形成明显视觉层次

        层次设计:
          LabelFrame 标题 (功能框名): 11pt 加粗, 深蓝色 — 一眼识别功能区
          内部 Label/RadioButton/CheckButton: 9pt 普通 — 内容文字
          灰色说明文字: 8pt — 提示性副标题
        """
        style = ttk.Style()
        # LabelFrame 标题: 加粗 + 深蓝色
        style.configure('TLabelframe.Label',
                        font=('Microsoft YaHei', 11, 'bold'),
                        foreground='#1a4d8c')
        # 内部普通文字: 9pt 正常粗细
        style.configure('TLabel',
                        font=('Microsoft YaHei', 9),
                        foreground='#222222')
        # 单选/复选按钮: 与普通文字对齐
        style.configure('TRadiobutton',
                        font=('Microsoft YaHei', 9))
        style.configure('TCheckbutton',
                        font=('Microsoft YaHei', 9))
        # 按钮: 稍大 + 加粗
        style.configure('TButton',
                        font=('Microsoft YaHei', 9, 'bold'))

    # ------------------------------------------------------------------
    def _build(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # ---- 顶部并排: 使用说明 (左) + 运行日志 (右) ----
        # 日志放顶部更显眼, 与使用说明并排节省垂直空间, 后续固定高度面板按序排在下面
        top_row = ttk.Frame(main)
        top_row.pack(fill=tk.BOTH, expand=True, pady=(0, 3))

        # 左: 使用说明
        intro = ttk.LabelFrame(top_row, text="使用说明 (真实业务链路 + 双重压测)", padding=8)
        intro.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4))
        intro_text = (
            "拓扑: N 架飞机 (伪 IP/MAC) ──→ AP 路由器 ──→ 地面站 GCS (172.16.200.1:14550)\n"
            "步骤:\n"
            "  1. 网卡 — 选实际接到 AP LAN 口的物理网卡 (默认路由网卡不一定是)\n"
            "  2. 目标 IP/端口 — 填地面站 IP (默认 172.16.200.1:14550)\n"
            "  3. 无人机数量 — 1~50000, 起始 IP 必须在本机子网\n"
            "  4. 发包模式 — Scapy L2 双向 (推荐) / netsh IP 别名 / 洪水模式\n"
            "  5. 飞行状态机 — 模拟真实起飞→巡航→返航→降落轨迹 (默认开)\n"
            "  6. 点 ▶ 开始测试 — 运行日志实时显示 发/收/①ARP/②心跳/③在线/pps\n"
            "观察:\n"
            "  · AP 侧 — Status→ARP Table 看 N 个 IP→MAC, Realtime Graphs 看 CPU/吞吐\n"
            "  · GCS 侧 — 飞机列表 + 详情面板字段刷新\n"
            "  · SSID — 整个机队共享 (模拟连同一个 AP), 默认 DMD\n"
            "⚠ Npcap 必装  ⚠ 飞机端已对齐固件 (HEARTBEAT 0.33Hz 主动, PS/ES/identify 仅 GCS 触发应答)\n"
            "⚠ 物理上限 — 单机 scapy ~3000 架稳定, >3000 需多机集群 (--cluster); 详见日志区说明"
        )
        ttk.Label(intro, text=intro_text, foreground="gray", justify=tk.LEFT,
                  font=("Microsoft YaHei", 9)).pack(anchor=tk.W)

        # 右: 运行日志 (从原底部迁移到顶部, 与使用说明并排)
        lf = ttk.LabelFrame(top_row, text="运行日志 (实时显示发/收/发现/pps + 主动推送统计)", padding=5)
        lf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bar = ttk.Frame(lf)
        bar.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        ttk.Button(bar, text="清空日志", width=10, command=self._clear_log).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(bar, text="保存日志", width=10, command=self._save_log).pack(side=tk.LEFT, padx=(0, 4))
        self._v_autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="自动滚动到最新", variable=self._v_autoscroll).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(bar, text="(查看 packed_state/extend_state 是否在持续发)", foreground="gray"
                  ).pack(side=tk.LEFT, padx=(10, 0))

        self._log_widget = tk.Text(lf, height=10, font=("Consolas", 9),
                                   bg="#1e1e1e", fg="#d4d4d4",
                                   insertbackground="white", relief=tk.FLAT,
                                   wrap=tk.WORD)
        self._log_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(lf, command=self._log_widget.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_widget.configure(yscrollcommand=sb.set)
        self._log_widget.configure(maxundo=0)

        # ---- 上线进度 (ARP / GCS 心跳 / 地面站在线, 500ms 独立刷新) ----
        # 三个数字测的层面不同, 对齐地面站 UavParser 状态机的真实"在线"判定:
        #   ① ARP 应答 (链路层): IP 进入 AP/GCS ARP 表, 不代表 GCS 知道我
        #   ② GCS 心跳轮询中 (轮询层): GCS 在向我发 heartbeat_dmd, 不代表 GCS 把我当在线
        #   ③ 地面站在线 (应用层): 收到 GCS 非心跳 MAVLink, 状态机走到 WORKING+
        op = ttk.LabelFrame(main, text="上线进度 (实时)", padding=10)
        op.pack(fill=tk.X, pady=(0, 3))
        op.columnconfigure(0, weight=1)
        op.columnconfigure(1, weight=1)
        op.columnconfigure(2, weight=1)
        big_font = tkfont.Font(size=20, weight='bold')
        sub_font = tkfont.Font(size=10)

        ap_box = ttk.Frame(op, borderwidth=2, relief='groove', padding=(8, 6))
        ap_box.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 4))
        ttk.Label(ap_box, text="① ARP 应答 (AP ARP 表)", font=sub_font,
                  foreground="#555").grid(row=0, column=0, sticky=tk.W)
        self._v_ap_count = tk.StringVar(value="0 / 0")
        ttk.Label(ap_box, textvariable=self._v_ap_count, font=big_font,
                  foreground="#0984e3").grid(row=1, column=0, sticky=tk.W, pady=(2, 0))
        self._ap_bar = ttk.Progressbar(ap_box, length=200, mode='determinate')
        self._ap_bar.grid(row=2, column=0, sticky=tk.EW, pady=(4, 0))

        gcs_box = ttk.Frame(op, borderwidth=2, relief='groove', padding=(8, 6))
        gcs_box.grid(row=0, column=1, sticky=tk.NSEW, padx=4)
        ttk.Label(gcs_box, text="② GCS 心跳轮询中", font=sub_font,
                  foreground="#555").grid(row=0, column=0, sticky=tk.W)
        self._v_gcs_count = tk.StringVar(value="0 / 0")
        ttk.Label(gcs_box, textvariable=self._v_gcs_count, font=big_font,
                  foreground="#fdcb6e").grid(row=1, column=0, sticky=tk.W, pady=(2, 0))
        self._gcs_bar = ttk.Progressbar(gcs_box, length=200, mode='determinate')
        self._gcs_bar.grid(row=2, column=0, sticky=tk.EW, pady=(4, 0))

        online_box = ttk.Frame(op, borderwidth=2, relief='groove', padding=(8, 6))
        online_box.grid(row=0, column=2, sticky=tk.NSEW, padx=(4, 0))
        ttk.Label(online_box, text="③ 地面站在线飞机数", font=sub_font,
                  foreground="#555").grid(row=0, column=0, sticky=tk.W)
        self._v_online_count = tk.StringVar(value="0 / 0")
        ttk.Label(online_box, textvariable=self._v_online_count, font=big_font,
                  foreground="#00b894").grid(row=1, column=0, sticky=tk.W, pady=(2, 0))
        self._online_bar = ttk.Progressbar(online_box, length=200, mode='determinate')
        self._online_bar.grid(row=2, column=0, sticky=tk.EW, pady=(4, 0))

        # ---- 集群节点列表 (仅 cluster_mode=True 显示) ----
        if self.cluster_mode:
            cl = ttk.LabelFrame(main, text="集群节点 (Slave 列表)", padding=8)
            cl.pack(fill=tk.X, pady=(0, 3))
            cols = ("slave_id", "addr", "state", "count", "start_ip",
                    "arp", "heartbeat", "online", "rate", "last_seen")
            self._slave_tree = ttk.Treeview(cl, columns=cols, show='headings', height=8)
            headers = {
                'slave_id':   ('Slave ID', 140),
                'addr':       ('地址', 110),
                'state':      ('状态', 70),
                'count':      ('架数', 60),
                'start_ip':   ('起始 IP', 110),
                'arp':        ('ARP 应答', 70),
                'heartbeat':  ('心跳轮询', 70),
                'online':     ('GCS 在线', 70),
                'rate':       ('pps', 60),
                'last_seen':  ('最近活动', 8),
            }
            for c in cols:
                self._slave_tree.heading(c, text=headers[c][0])
                self._slave_tree.column(c, width=headers[c][1], anchor=tk.W)
            self._slave_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            sb_cl = ttk.Scrollbar(cl, command=self._slave_tree.yview)
            sb_cl.pack(side=tk.RIGHT, fill=tk.Y)
            self._slave_tree.configure(yscrollcommand=sb_cl.set)
            # 默认无节点时的占位提示
            self._slave_tree.insert('', 'end', iid='_empty',
                                    values=('<等待 slave 连入>', '', '', '', '', '', '', '', '', ''))

        # ---- 目标 ----
        g = ttk.LabelFrame(main, text="目标 (地面站)", padding=8)
        g.pack(fill=tk.X, pady=(0, 3))

        ttk.Label(g, text="IP:").grid(row=0, column=0, sticky=tk.W)
        self._v_dst_ip = tk.StringVar(value=GS_DEFAULT_IP)
        ttk.Entry(g, textvariable=self._v_dst_ip, width=15).grid(row=0, column=1, sticky=tk.W, padx=5)
        # 地面站 IP 变化 → 自动重算 IP 起始 (GCS 子网是无人机子网的首要参考)
        self._v_dst_ip.trace_add('write', lambda *a: self._auto_suggest_start_ip())

        ttk.Label(g, text="端口:").grid(row=0, column=2, sticky=tk.W, padx=(15, 0))
        self._v_dst_port = tk.IntVar(value=GS_DEFAULT_PORT)
        ttk.Entry(g, textvariable=self._v_dst_port, width=7).grid(row=0, column=3, sticky=tk.W, padx=5)

        ttk.Label(g, text="网卡:").grid(row=0, column=4, sticky=tk.W, padx=(15, 0))
        self._v_iface = tk.StringVar(value="")
        self._iface_items = []  # list_all_interfaces() 结果缓存
        self._cb_iface = ttk.Combobox(
            g, textvariable=self._v_iface, width=42, state='readonly')
        self._cb_iface.grid(row=0, column=5, sticky=tk.W, padx=5)
        self._cb_iface.bind('<<ComboboxSelected>>', self._on_iface_change)

        # GCS MAC (可选)
        ttk.Label(g, text="GCS MAC:").grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        self._v_gcs_mac = tk.StringVar(value="")
        ttk.Entry(g, textvariable=self._v_gcs_mac, width=18).grid(row=1, column=1, sticky=tk.W, padx=5, pady=(4, 0))
        ttk.Label(g, text="(留空=广播, 跨网段建议广播)").grid(row=1, column=2, columnspan=4, sticky=tk.W, pady=(4, 0))

        # AP/网关 IP (可选, 对齐固件 dmd_app.h:20 DMD_DFT_GW_IP_ADDR)
        ttk.Label(g, text="AP/网关 IP:", foreground="blue",
                  font=("Microsoft YaHei", 9, "bold")).grid(row=2, column=0, sticky=tk.W, pady=(4, 0))
        self._v_ap_ip = tk.StringVar(value="172.16.201.1")
        ttk.Entry(g, textvariable=self._v_ap_ip, width=15).grid(row=2, column=1, sticky=tk.W, padx=5, pady=(4, 0))
        # AP/网关 IP 变化 → 自动重算 IP 起始 (用户没手动改过的前提下)
        self._v_ap_ip.trace_add('write', lambda *a: self._auto_suggest_start_ip())
        ttk.Label(g, text="(启动时 ping 验证可达;压测时打开 AP 管理页看转发/CPU/ARP 表)",
                  foreground="gray").grid(row=2, column=2, columnspan=4, sticky=tk.W, pady=(4, 0))

        # ---- 无人机 ----
        f = ttk.LabelFrame(main, text="无人机模拟 (伪造 IP × 端口 14551, scapy L2)", padding=8)
        f.pack(fill=tk.X, pady=(0, 3))

        ttk.Label(f, text="数量:").grid(row=0, column=0, sticky=tk.W)
        self._v_count = tk.IntVar(value=10)
        ttk.Spinbox(f, from_=1, to=50000, textvariable=self._v_count, width=7).grid(
            row=0, column=1, sticky=tk.W, padx=5)
        ttk.Label(f, text="(可任意数量，无需等待 IP 添加)").grid(
            row=0, column=2, columnspan=3, sticky=tk.W)

        ttk.Label(f, text="IP 起始:").grid(row=1, column=0, sticky=tk.W, pady=(5, 0))
        # 默认留空 — 启动后由 _auto_suggest_start_ip() 按 AP/网关 IP 自动填
        self._v_start_ip = tk.StringVar(value="")
        ttk.Entry(f, textvariable=self._v_start_ip, width=15).grid(row=1, column=1, sticky=tk.W, padx=5, pady=(5, 0))
        # 用户手动改过 IP 起始 → 不再被 AP/网卡联动覆盖
        self._start_ip_user_override = False
        self._start_ip_prog_set = False  # 程序自己 set 时置 True, 防 trace 误标
        self._v_start_ip.trace_add('write', self._on_start_ip_changed)

        ttk.Label(f, text="起始 MAC:").grid(row=1, column=2, sticky=tk.W, padx=(5, 0), pady=(5, 0))
        self._v_start_mac = tk.StringVar(value="02:00:00:00:00:01")
        ttk.Entry(f, textvariable=self._v_start_mac, width=18).grid(row=1, column=3, sticky=tk.W, padx=5, pady=(5, 0))

        ttk.Label(f, text="心跳间隔(s):").grid(row=1, column=4, sticky=tk.W, padx=(5, 0), pady=(5, 0))
        self._v_interval = tk.DoubleVar(value=3.0)
        ttk.Entry(f, textvariable=self._v_interval, width=6).grid(row=1, column=5, sticky=tk.W, padx=5, pady=(5, 0))

        # SSID (机队共享,对齐固件 packed_state.ssid = WiFi 网络名)
        ttk.Label(f, text="机队 SSID:", foreground="blue", font=("Microsoft YaHei", 9, "bold")
                  ).grid(row=2, column=0, sticky=tk.W, pady=(5, 0))
        self._v_ssid = tk.StringVar(value="DMD")
        ttk.Entry(f, textvariable=self._v_ssid, width=12).grid(row=2, column=1, sticky=tk.W, padx=5, pady=(5, 0))
        ttk.Label(f, text="(8 字节 ASCII, 写入 packed_state.ssid; 模拟所有飞机连同一个 AP)",
                  foreground="gray").grid(row=2, column=2, columnspan=4, sticky=tk.W, pady=(5, 0))

        # ---- 发包模式 (每个模式配通俗解释) ----
        s = ttk.LabelFrame(main, text="发包模式 (一台电脑模拟 N 架无人机的方式)", padding=8)
        s.pack(fill=tk.X, pady=(0, 3))

        self._v_mode = tk.StringVar(value="scapy")

        # Scapy 双向 (推荐)
        ttk.Radiobutton(s, text="Scapy 双向 (推荐)",
                        variable=self._v_mode, value="scapy",
                        command=self._on_mode_change).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(s, text="用 scapy 伪造 IP/MAC, 一台电脑模拟上千架不同身份的无人机, 能发也能收。日常压测就用这个",
                  foreground="gray", wraplength=620, justify=tk.LEFT
                  ).grid(row=1, column=0, columnspan=4, sticky=tk.W, padx=(20, 0))

        # IP别名 (备用)
        ttk.Radiobutton(s, text="IP别名 netsh (备用)",
                        variable=self._v_mode, value="netsh",
                        command=self._on_mode_change).grid(row=2, column=0, sticky=tk.W, pady=(4, 0))
        ttk.Label(s, text="用 netsh 给网卡真实绑定多个 IP, 每个 IP 跑独立 socket。仅当 GCS 跑在本机(scapy 抓不到本机→本机的包)时才用",
                  foreground="gray", wraplength=620, justify=tk.LEFT
                  ).grid(row=3, column=0, columnspan=4, sticky=tk.W, padx=(20, 0))

        # 洪水 (极限压测)
        ttk.Radiobutton(s, text="洪水 flood (极限压测)",
                        variable=self._v_mode, value="flood",
                        command=self._on_mode_change).grid(row=4, column=0, sticky=tk.W, pady=(4, 0))
        ttk.Label(s, text="scapy 疯狂发心跳只发不收, 不处理地面站回复。发送速度最快, 专门测地面站能扛多少包/秒",
                  foreground="gray", wraplength=620, justify=tk.LEFT
                  ).grid(row=5, column=0, columnspan=4, sticky=tk.W, padx=(20, 0))

        # netsh 专用选项 (隐藏/显示)
        self._netsh_opts = ttk.Frame(s)
        ttk.Label(self._netsh_opts, text="子网掩码:").grid(row=0, column=0, sticky=tk.W, padx=(20, 0))
        self._v_mask = tk.StringVar(value="255.255.0.0")
        ttk.Entry(self._netsh_opts, textvariable=self._v_mask, width=15).grid(row=0, column=1, padx=5)
        ttk.Label(self._netsh_opts, text="(IP别名模式专用)", foreground="gray").grid(row=0, column=2, sticky=tk.W)

        # flood 专用选项
        self._flood_opts = ttk.Frame(s)
        ttk.Label(self._flood_opts, text="目标 MAC:").grid(row=0, column=0, sticky=tk.W, padx=(20, 0))
        self._v_dst_mac = tk.StringVar(value="ff:ff:ff:ff:ff:ff")
        ttk.Entry(self._flood_opts, textvariable=self._v_dst_mac, width=18).grid(row=0, column=1, padx=5)
        ttk.Label(self._flood_opts, text="(洪水模式专用, 留空=广播)", foreground="gray").grid(row=0, column=2, sticky=tk.W)
        self._on_mode_change()

        # ---- 数据抖动 (字段值的小幅随机变化, 模拟传感器噪声) ----
        j = ttk.LabelFrame(main, text="数据抖动 (字段值的小幅随机变化, 模拟真实传感器噪声)", padding=8)
        j.pack(fill=tk.X, pady=(0, 3))
        self._v_jitter = tk.BooleanVar(value=True)
        ttk.Checkbutton(j, text="启用抖动",
                        variable=self._v_jitter).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(j, text="(每架飞机的 LAT/LON/电压/温度/姿态 等字段每帧都在小幅随机变化, 让地面站 UI 持续刷新)",
                  foreground="gray", wraplength=600, justify=tk.LEFT
                  ).grid(row=0, column=1, columnspan=4, sticky=tk.W)
        ttk.Label(j, text="幅度%:").grid(row=1, column=0, sticky=tk.W, padx=(20, 0))
        self._v_fj = tk.DoubleVar(value=20.0)
        ttk.Scale(j, from_=0, to=100, variable=self._v_fj, length=120).grid(row=1, column=1, padx=3)
        ttk.Label(j, textvariable=self._v_fj, width=4).grid(row=1, column=2)
        ttk.Label(j, text="(20 = 字段值在 ±20% 范围内浮动; 越大越夸张)", foreground="gray"
                  ).grid(row=1, column=3, sticky=tk.W)
        # 批次大小 (默认值,不展示在主界面,高级选项里露出)
        self._v_batch = tk.IntVar(value=50)

        # ---- 飞行模拟 & 遥测上报 (核心) ----
        sm = ttk.LabelFrame(main, text="飞行模拟 & 遥测上报", padding=8)
        sm.pack(fill=tk.X, pady=(0, 3))

        # Row 0: 核心开关 + 主动推送频率 (已对齐固件,默认 0=仅 GCS 触发)
        self._v_sm_enable = tk.BooleanVar(value=True)
        ttk.Checkbutton(sm, text="启用飞行状态机 (起飞→巡航→返航→降落 循环)",
                        variable=self._v_sm_enable).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(sm, text="PACKED_STATE(Hz):", foreground="blue", font=("Microsoft YaHei", 9, "bold")
                  ).grid(row=0, column=1, padx=(20, 0))
        self._v_ps_rate = tk.DoubleVar(value=0.0)
        ttk.Spinbox(sm, from_=0, to=20, increment=0.5, textvariable=self._v_ps_rate,
                    width=5, format="%.1f").grid(row=0, column=2, padx=3)
        ttk.Label(sm, text="EXTEND_STATE(Hz):", foreground="blue", font=("Microsoft YaHei", 9, "bold")
                  ).grid(row=0, column=3, padx=(15, 0))
        self._v_es_rate = tk.DoubleVar(value=0.0)
        ttk.Spinbox(sm, from_=0, to=20, increment=0.5, textvariable=self._v_es_rate,
                    width=5, format="%.1f").grid(row=0, column=4, padx=3)
        ttk.Label(sm, text="(默认0=仅GCS触发,对齐固件; ≥1=主动推送,会偏离真实场景)",
                  foreground="gray").grid(row=0, column=5, padx=(10, 0))

        # Row 1: 高级选项切换按钮
        self._v_advanced = tk.BooleanVar(value=False)
        self._btn_advanced = ttk.Checkbutton(sm, text="▶ 高级选项 (飞行参数 / 调试字段)",
                                             variable=self._v_advanced,
                                             command=self._toggle_advanced)
        self._btn_advanced.grid(row=1, column=0, columnspan=6, sticky=tk.W, pady=(4, 0))

        # 高级选项 frame (默认隐藏)
        self._adv_frame = ttk.Frame(sm, padding=(20, 4, 0, 0))
        # 飞行参数 (变量保留,控件在高级里)
        self._v_phase = tk.DoubleVar(value=5.0)
        self._v_tgt_alt = tk.DoubleVar(value=50.0)
        self._v_cruise = tk.DoubleVar(value=30.0)
        ttk.Label(self._adv_frame, text="[飞行参数]", foreground="darkgreen"
                  ).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(self._adv_frame, text="起飞错峰(s):").grid(row=0, column=1, padx=(10, 0))
        ttk.Entry(self._adv_frame, textvariable=self._v_phase, width=5).grid(row=0, column=2, padx=3)
        ttk.Label(self._adv_frame, text="目标高度(m):").grid(row=0, column=3, padx=(10, 0))
        ttk.Entry(self._adv_frame, textvariable=self._v_tgt_alt, width=5).grid(row=0, column=4, padx=3)
        ttk.Label(self._adv_frame, text="巡航时长(s):").grid(row=0, column=5, padx=(10, 0))
        ttk.Entry(self._adv_frame, textvariable=self._v_cruise, width=5).grid(row=0, column=6, padx=3)

        # 调试字段 (变量保留,控件在高级里)
        self._v_raw_imu = tk.DoubleVar(value=0.0)
        self._v_failsafe = tk.IntVar(value=0)
        ttk.Label(self._adv_frame, text="[调试字段]", foreground="darkgreen"
                  ).grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        ttk.Label(self._adv_frame, text="RAW_IMU(Hz,0=关):").grid(row=1, column=1, padx=(10, 0), pady=(4, 0))
        ttk.Spinbox(self._adv_frame, from_=0, to=20, increment=1, textvariable=self._v_raw_imu,
                    width=5).grid(row=1, column=2, padx=3, pady=(4, 0), sticky=tk.W)
        ttk.Label(self._adv_frame, text="FAILSAFE(0=正常):").grid(row=1, column=3, padx=(10, 0), pady=(4, 0))
        ttk.Entry(self._adv_frame, textvariable=self._v_failsafe, width=10).grid(
            row=1, column=4, columnspan=2, sticky=tk.W, padx=3, pady=(4, 0))
        ttk.Label(self._adv_frame, text="发包批次:").grid(row=1, column=5, padx=(10, 0), pady=(4, 0))
        ttk.Spinbox(self._adv_frame, from_=1, to=500, textvariable=self._v_batch, width=5
                    ).grid(row=1, column=6, padx=3, pady=(4, 0), sticky=tk.W)
        ttk.Label(self._adv_frame, text="RAW_IMU = 地面站 IMU 调试图表数据源, 默认 0 不发;  FAILSAFE 位 = 模拟故障(bit4=遥控器断 bit5=低电 bit6=围栏超高)",
                  foreground="gray", wraplength=720, justify=tk.LEFT
                  ).grid(row=2, column=0, columnspan=7, sticky=tk.W, pady=(2, 0))
        ttk.Label(self._adv_frame, text="发包批次 = 每轮发心跳时分多少批发, 100架+批次50=2批发完, 与数据抖动无关",
                  foreground="gray", wraplength=720, justify=tk.LEFT
                  ).grid(row=3, column=0, columnspan=7, sticky=tk.W, pady=(2, 0))
        # 默认隐藏高级 frame
        # (不 grid,即可隐藏; _toggle_advanced 控制)

        # ---- 控制 ----
        c = ttk.LabelFrame(main, text="测试控制", padding=8)
        c.pack(fill=tk.X, pady=(0, 3))
        # 大号醒目按钮字体 (开始=绿色, 停止=红色, 16号粗体)
        _btn_font = tkfont.Font(size=16, weight='bold')
        ttk.Label(c, text="时长 (s, 0=不限):").grid(row=0, column=0, sticky=tk.W)
        self._v_duration = tk.DoubleVar(value=0.0)   # 0=不限, 长稳压测默认
        ttk.Entry(c, textvariable=self._v_duration, width=8).grid(row=0, column=1, padx=5)
        self._v_respond = tk.BooleanVar(value=True)
        ttk.Checkbutton(c, text="收到请求时自动回复", variable=self._v_respond).grid(
            row=0, column=2, padx=(15, 0))
        # 开始/停止按钮: 放大字体 + 醒目配色 + 固定宽度
        # ttk.Button 不支持直接设背景色 (ttk 主题限制), 用 tk.Button 才能上色
        self._btn_start = tk.Button(
            c, text="▶  开始测试", command=self._start,
            font=_btn_font, fg="white", bg="#00b894",
            activebackground="#00cec9", activeforeground="white",
            relief=tk.RAISED, bd=3, height=2, width=14, cursor="hand2")
        self._btn_start.grid(row=0, column=3, padx=(30, 8), sticky=tk.E)
        self._btn_stop = tk.Button(
            c, text="■  停止测试", command=self._stop, state=tk.DISABLED,
            font=_btn_font, fg="white", bg="#d63031",
            activebackground="#ff7675", activeforeground="white",
            relief=tk.RAISED, bd=3, height=2, width=14, cursor="hand2")
        self._btn_stop.grid(row=0, column=4, sticky=tk.E)

        # ---- 状态 ----
        st = ttk.LabelFrame(main, text="实时状态", padding=8)
        st.pack(fill=tk.X, pady=(0, 3))
        self._v_status = tk.StringVar(value="就绪")
        ttk.Label(st, text="状态:").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(st, textvariable=self._v_status, foreground="blue").grid(row=0, column=1, padx=5)
        self._v_mode_disp = tk.StringVar()
        ttk.Label(st, textvariable=self._v_mode_disp, foreground="gray").grid(row=0, column=2, padx=(20, 0))
        self._v_stats = tk.StringVar(value="发: 0 | 收: 0 | 发现: 0 | 0 pps | 00:00")
        ttk.Label(st, textvariable=self._v_stats).grid(row=1, column=0, columnspan=5, sticky=tk.W, pady=(4, 0))
        self._progress = ttk.Progressbar(st, mode='indeterminate')
        self._progress.grid(row=2, column=0, columnspan=5, sticky=tk.EW, pady=(4, 0))

        # ---- 页脚: 版本号 ----
        ttk.Label(main, text=f"DGCS 地面站压力测试工具  v{TOOL_VERSION}  —  测试开发部",
                  foreground="gray", font=("Microsoft YaHei", 8)
                  ).pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))

    # ------------------------------------------------------------------
    def _on_mode_change(self):
        mode = self._v_mode.get()
        if mode == "flood":
            self._netsh_opts.grid_forget()
            self._flood_opts.grid(row=6, column=0, columnspan=4, sticky=tk.W, pady=(6, 0))
        elif mode == "netsh":
            self._flood_opts.grid_forget()
            self._netsh_opts.grid(row=6, column=0, columnspan=4, sticky=tk.W, pady=(6, 0))
        else:
            self._flood_opts.grid_forget()
            self._netsh_opts.grid_forget()

    def _toggle_advanced(self):
        """切换高级选项 frame 的显示/隐藏"""
        if self._v_advanced.get():
            self._adv_frame.grid(row=2, column=0, columnspan=6, sticky=tk.W, pady=(2, 0))
            self._btn_advanced.config(text="▼ 高级选项 (飞行参数 / 调试字段)")
        else:
            self._adv_frame.grid_forget()
            self._btn_advanced.config(text="▶ 高级选项 (飞行参数 / 调试字段)")

    def _build_behavior_config(self) -> dict:
        """从 GUI 变量构造 DroneBehavior config 字典"""
        # SSID 截断到 8 字节 ASCII (对齐 packed_state.ssid 字段长度)
        ssid_raw = self._v_ssid.get() if hasattr(self, '_v_ssid') else 'DMD'
        try:
            ssid_str = ssid_raw.encode('ascii', errors='replace').decode('ascii')[:8]
        except Exception:
            ssid_str = 'DMD'
        return {
            'ssid': ssid_str,
            'state_machine': self._v_sm_enable.get(),
            'phase_offset_s': self._v_phase.get(),
            'target_alt_m': self._v_tgt_alt.get(),
            'cruise_duration_s': self._v_cruise.get(),
            'raw_imu_rate_hz': self._v_raw_imu.get(),
            'failsafe_mask': int(self._v_failsafe.get() or 0),
        }

    def _apply_failsafe_to_swarm(self):
        """把 GUI 的 failsafe 位应用到所有 drone（运行中也可注入）"""
        mask = int(self._v_failsafe.get() or 0)
        if self._swarm:
            for d in self._swarm:
                if hasattr(d, 'behavior'):
                    d.behavior.failsafe_mask = mask

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        if hasattr(self, '_log_widget') and self._log_widget:
            self._log_widget.insert(tk.END, line + "\n")
            # 限制最多 5000 行,丢掉前面的旧行
            line_count = int(self._log_widget.index('end-1c').split('.')[0])
            if line_count > 5000:
                self._log_widget.delete(1.0, f"{line_count - 5000}.0")
            if getattr(self, '_v_autoscroll', None) and self._v_autoscroll.get():
                self._log_widget.see(tk.END)

    def _clear_log(self):
        if hasattr(self, '_log_widget') and self._log_widget:
            self._log_widget.delete(1.0, tk.END)

    def _save_log(self):
        from tkinter import filedialog
        if not (hasattr(self, '_log_widget') and self._log_widget):
            return
        content = self._log_widget.get(1.0, tk.END)
        if not content.strip():
            messagebox.showinfo("提示", "日志为空")
            return
        path = filedialog.asksaveasfilename(
            title="保存运行日志",
            defaultextension=".log",
            filetypes=[("日志文件", "*.log"), ("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile=f"dgcs_stress_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            messagebox.showinfo("已保存", f"日志已保存到:\n{path}")
        except OSError as e:
            messagebox.showerror("保存失败", str(e))

    def _print_intro(self):
        """启动时打印工具用途 / 使用方法 / 注意事项"""
        self._log("=" * 70)
        self._log("DGCS 地面站压力测试工具")
        self._log("=" * 70)
        self._log("【测试目的】")
        self._log("  伪造大量无人机 IP，通过同一端口 (14551) 向地面站发送心跳、")
        self._log("  扩展状态、FAILSAFE、RAW_IMU 等 MAVLink 报文，配合飞行状态机")
        self._log("  (起飞→巡航→返航→降落) 动态抖动上报，测试地面站的:")
        self._log("  · 并发连接数上限  · 协议解析吞吐  · UI 渲染压力  · 长时间稳定性")
        self._log("")
        self._log("【使用方法】")
        self._log("  1. 网卡下拉框: 选择本机实际连接地面站所在网段的网卡")
        self._log("     (默认会选默认路由网卡，但实际连 GCS 的可能是另一张)")
        self._log("  2. 目标 IP/端口: 填地面站 IP (默认 172.16.200.1:14550)")
        self._log("  3. 无人机数量: 1~50000 可选；起始 IP 必须在本机子网")
        self._log("     (跨子网时工具会自动用网关 MAC，但仍要求 ARP 可达)")
        self._log("  4. 发包模式:")
        self._log("     · Scapy L2 双向 (推荐): 伪造 IP/MAC，无需管理员，跨机器通用")
        self._log("     · netsh IP 别名: 真实 UDP socket，需管理员，无需 Npcap")
        self._log("     · 洪水模式: 只发心跳不收，最大压力 (用于极限压测)")
        self._log("  5. 启用飞行状态机: 模拟真实飞行轨迹与状态切换 (默认开)")
        self._log("  6. 点击 ▶ 开始测试 — 运行日志实时显示发/收/发现/pps")
        self._log("  7. 观察上线进度 (右上方三色大数字):")
        self._log("     ① ARP 应答 (蓝): AP 已学习到本机 MAC, 链路层 OK")
        self._log("     ② GCS 心跳轮询 (黄): GCS 在向我发 heartbeat_dmd, 轮询层 OK")
        self._log("     ③ 地面站在线 (绿): 收到 GCS 业务 MAVLink, 应用层 OK = 真正在线")
        self._log("  8. 验证标准: 30s 内 ③ 在线数 = 设置数量, 且能持续不掉")
        self._log("")
        self._log("【注意事项】")
        self._log("  ⚠ Npcap 必装 (Scapy/洪水模式) — https://npcap.com/#download")
        self._log("     安装时勾选 'Support raw 802. traffic' + 'WinPcap API-compatible'")
        self._log("  ⚠ 选错网卡 = 地面站收不到任何包: 启动后若 5s 内 '收 0'，")
        self._log("     立刻停止并切换网卡下拉框到另一张")
        self._log("  ⚠ GCS 自环: 若 GCS IP 命中本机网卡 (如本机就是 GCS)，")
        self._log("     scapy L2 抓不到本机→本机的包，需切到 netsh 模式或换机部署")
        self._log("  ⚠ 防火墙: Windows Defender 可能拦截 Npcap 的收包，")
        self._log("     首次运行若被拦截，请在防火墙允许 python.exe / Npcap")
        self._log("  ⚠ 跨网段: drone IP 会自动修正到本机子网，目标 MAC 会自动用网关")
        self._log("")
        self._log("【物理上限 — 为什么单机测不了 1 万架】")
        self._log("  单机 scapy Python 模拟器存在 4 个物理层瓶颈, 改代码改不动:")
        self._log("  P1. Python GIL 串行: 单线程解释器, sendp/构造包/解析全在一个核上排队")
        self._log("      → 加多核 CPU 不解决 (GIL 锁住), 必须多进程或多机")
        self._log("  P2. Npcap 系统调用延迟: 每次 sendp 进内核态切换 0.5-2ms,")
        self._log("      即便批量 sendp([list]) 复用 socket, 单次调用绝对延迟降不下来")
        self._log("  P3. scapy 构包开销: 每个包 = Ether/IP/UDP/Payload 三层对象 + struct.pack,")
        self._log("      Python 层 ~50μs/包, 1000 包/轮 = 50ms (不可压缩)")
        self._log("  P4. AP MAC 学习表上限: 消费级 AP ~32-128 station, 企业级 500-2000,")
        self._log("      伪造源 MAC 超量会被 AP 当未关联直接丢")
        self._log("  单机实测上限 (v2.1.x P0/P1 优化后):")
        self._log("    · ≤500 架: 稳定不掉  · 1000 架: 基本稳定 (前 30s 可能抖)")
        self._log("    · 2000 架: 临界, 偶尔抖   · 3000 架: 频繁抖, 不稳定")
        self._log("    · >3000 架: 不可能 (单机) — 必须 --cluster 多机分布式")
        self._log("  突破方案: python dgcs_stress_test.py --cluster  (master+slave, 多机各跑 N 架)")
        self._log("")
        self._log("【验证标准】 运行 30s 内应看到 '③ 在线 N/N'，地面站 UI 显示对应飞机数")
        self._log("")
        self._log("【地面站看不到飞机数据动态上报时排查】")
        self._log("  1. 状态栏 PS/ES 计数应在涨 → 工具确实在持续发 packed_state/extend_state")
        self._log("  2. 在地面站机器上抓包确认收得到:")
        self._log("     pktmon start --capture --filter --comp nics -p 0 -e")
        self._log("     pktmon filter add -p udp -t src.port=14551 dst.port=14550")
        self._log("     # 30s 后: pktmon stop && pktmon etl2pcap <file>.etl <file>.pcap")
        self._log("     # 用 Wireshark 打开 pcap,Filter: udp.port==14551,应看到 packed_state (msg_id=5)")
        self._log("  3. 地面站 UI 必须在飞机列表里选中某架,右侧详情面板才会刷新")
        self._log("     (未选中时面板DataContext=null,所有字段空白是正常现象)")
        self._log("  4. 详情面板 ID 字段来自 identify_info 的 code (DisplayId),")
        self._log("     SN 字段来自 identify_info 的 serial,SYS_CODE/Vers 来自 extend_state")
        self._log("=" * 70)

        # 启动自检 — 校验所有 MAVLink 消息生成器
        result = run_selftest()
        if result['ok']:
            self._log(f"✓ {result['summary']}")
        else:
            self._log(f"✗ {result['summary']}")
            self._log("  地面站可能因为 payload 长度/CRC 不匹配而丢弃这些消息!")
            for f in result['failures']:
                self._log(f"    - {f}")

    def _refresh_iface_combo(self):
        """刷新网卡下拉框 (启动时调用)"""
        items = list_all_interfaces()
        self._iface_items = items
        labels = [format_iface_label(it) for it in items]
        self._cb_iface['values'] = labels
        if items:
            self._log(f"检测到 {len(items)} 张网卡:")
            for it in items:
                flag = '★' if it['is_default'] else ' '
                ip = it['ip'] or '无IP'
                st = it['status'] or '?'
                self._log(f"  {flag} {it['name']:20s} {ip:16s} [{st}]")
        else:
            self._log("⚠ 未检测到任何网卡，请手输网卡名")

    def _on_iface_change(self, event=None):
        """下拉框切换网卡 — 更新 _v_iface 和本机 MAC"""
        idx = self._cb_iface.current()
        if idx < 0 or idx >= len(self._iface_items):
            return
        item = self._iface_items[idx]
        iface = item['name']
        self._v_iface.set(iface)
        # 优先用 PowerShell 拿到的 MAC；拿不到再走 get_real_mac
        mac = item.get('mac') or ''
        if mac and mac != '00:00:00:00:00:00':
            self._v_real_mac = mac
        else:
            self._v_real_mac = get_real_mac(iface)
        lip = item.get('ip') or get_interface_ip(iface)
        self._log(f"已切换网卡: {iface}  |  IP: {lip}  |  MAC: {self._v_real_mac}")
        # 网卡变了 → 本机 IP 变了 → 重算 IP 起始 (若用户没手动改过)
        self._auto_suggest_start_ip()



    def _on_start_ip_changed(self, *args):
        """trace 回调 — 用户在 IP 起始 输入框里手动键入时, 标记 override"""
        # 程序自己 set 时不算用户编辑
        if getattr(self, '_start_ip_prog_set', False):
            return
        self._start_ip_user_override = True

    def _auto_suggest_start_ip(self):
        """按 AP/网关 IP + 本机 IP 自动建议 IP 起始

        触发时机:
          - GUI 启动后首次填充 (App.__init__ 末尾)
          - 用户切换网卡 (_on_iface_change)
          - 用户改 AP/网关 IP (_v_ap_ip trace)

        用户手动改过 IP 起始输入框后, 不再自动覆盖 (尊重用户输入)。
        """
        # 控件还没建好 (App.__init__ 早期) 时跳过
        if not hasattr(self, '_v_start_ip') or not hasattr(self, '_v_ap_ip'):
            return
        if getattr(self, '_start_ip_user_override', False):
            return
        iface = self._v_iface.get().strip()
        ap_ip = self._v_ap_ip.get().strip()
        gcs_ip = self._v_dst_ip.get().strip() if hasattr(self, '_v_dst_ip') else ''
        try:
            new_ip = suggest_start_ip(iface, ap_ip=ap_ip, gcs_ip=gcs_ip)
        except Exception:
            return
        # 标记程序 set, 避免 trace 把自己识别为用户输入
        self._start_ip_prog_set = True
        try:
            self._v_start_ip.set(new_ip)
        finally:
            self._start_ip_prog_set = False

    @staticmethod
    def _ping_check(ip: str, timeout: float = 2.0) -> bool:
        """检查目标 IP 是否可达 (用 UDP 探测，避免 ICMP 被防火墙拦截)"""
        try:
            # 尝试 UDP 连接（不实际发包，只是检查路由）
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(timeout)
            s.connect((ip, 14550))
            s.close()
            return True
        except Exception:
            pass
        # 备用: 尝试 TCP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((ip, 14550))
            s.close()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    def _start(self):
        if self.cluster_mode:
            return self._start_cluster()

        if self._runner and self._runner.running():
            messagebox.showwarning("提示", "测试已在运行中")
            return

        count = self._v_count.get()
        dst_ip = self._v_dst_ip.get().strip()
        dst_port = self._v_dst_port.get()
        if not dst_ip:
            messagebox.showerror("错误", "请输入目标 IP")
            return

        # AP/网关可达性自检 — 验证工具机器和 AP 在同一 L2,流量能经过 AP 转发到 GCS
        ap_ip = self._v_ap_ip.get().strip()
        if ap_ip:
            self._log(f"▶ AP/网关可达性自检: ping {ap_ip} ...")
            if self._ping_check(ap_ip, timeout=2.0):
                self._log(f"  ✓ AP 可达 ({ap_ip} 响应 ICMP)")
                self._log(f"  ℹ 压测期间打开 AP 管理页 (http://{ap_ip}) 观察:")
                self._log(f"     · Status → Routes → ARP Table (应看到 N 架飞机 IP→MAC)")
                self._log(f"     · Status → Realtime Graphs (CPU/流量,AP 转发性能)")
                self._log(f"     · Network → Wireless → Associated Stations (不会有飞机,因为是 L2 伪造)")
            else:
                self._log(f"  ⚠ AP {ap_ip} 不可达!可能原因:网卡选错/不在同一子网/防火墙拦 ICMP")
                self._log(f"  ⚠ 压测可能失败,建议先解决 AP 可达性再开始")
        else:
            self._log("ℹ 未填 AP/网关 IP,跳过 AP 可达性自检")

        # GCS 可达性自检
        if self._ping_check(dst_ip, timeout=2.0):
            self._log(f"  ✓ GCS {dst_ip} 可达")
        else:
            self._log(f"  ⚠ GCS {dst_ip} 不可达 (ICMP)!若 GCS 拦截 ping 但开 UDP 14550 仍可工作")

        self._btn_start.configure(state=tk.DISABLED)
        self._btn_stop.configure(state=tk.NORMAL)
        self._v_status.set("运行中")
        self._progress.start(10)

        mode = self._v_mode.get()
        if mode == "flood":
            self._start_flood(count, dst_ip, dst_port)
        elif mode == "netsh":
            self._start_netsh(count, dst_ip, dst_port)
        else:
            self._start_scapy(count, dst_ip, dst_port)

    def _start_scapy(self, count, dst_ip, dst_port):
        """Scapy L2 双向模式 — 推荐默认模式"""
        self._v_mode_disp.set("模式: Scapy L2 双向")
        iface = self._v_iface.get().strip()

        # 将 Windows 网卡名映射为 Npcap 名
        sc_iface = resolve_scapy_iface(iface)
        if sc_iface != iface:
            self._log(f"网卡映射: '{iface}' → '{sc_iface}' (Npcap)")
        start_ip = self._v_start_ip.get().strip()
        start_mac = self._v_start_mac.get().strip()
        gcs_mac = self._v_gcs_mac.get().strip()

        try:
            ip_to_int(start_ip)
            int(start_mac.replace(':', '').replace('-', ''), 16)
        except Exception:
            messagebox.showerror("错误", "起始 IP 或 MAC 格式不正确")
            self._on_done()
            return

        real_mac = getattr(self, '_v_real_mac', '02:00:00:00:00:01')

        # ---- 智能修正：自动判断子网和下一跳 MAC ----
        my_ip = get_interface_ip(iface)
        my_mask = get_interface_netmask(iface)

        # 修正 1: drone IP 必须在本机子网，否则 GCS 的回复无法路由回来
        if not same_subnet(start_ip, my_ip, my_mask):
            old_sip = start_ip
            start_ip = suggest_start_ip(iface)
            self._log(f"⚠ 已自动修正 drone IP: {old_sip} → {start_ip} (本机子网)")
            self._log(f"  原因: 原 IP 在 GCS 子网，GCS ARP 请求无法跨网到达本机")
            # 同步回写 GUI 输入框，避免"显示 IP"与"实际发包源 IP"不一致
            self._v_start_ip.set(start_ip)

        # 修正 2: 跨子网时需要发到网关 MAC 而非 GCS MAC
        dst_mac = gcs_mac
        if not same_subnet(dst_ip, my_ip, my_mask):
            gw_ip = get_gateway_ip(iface)
            if gw_ip:
                self._log(f"  检测到跨子网: 本机={my_ip}, GCS={dst_ip}, 网关={gw_ip}")
                gw_mac = resolve_mac(gw_ip, iface)
                if gw_mac:
                    dst_mac = gw_mac
                    self._log(f"  下一跳: 网关 MAC={gw_mac} (帧将通过路由器转发到 GCS)")
                else:
                    self._log(f"  ⚠ 无法解析网关 MAC，使用广播 (可能不通)")
            else:
                self._log(f"  ⚠ 跨子网但无默认网关，使用广播 (可能不通)")

        self._log(f"Scapy L2 双向模式启动:")
        self._log(f"  本机 MAC={real_mac}, GCS={dst_ip}:{dst_port}")
        self._log(f"  起始 IP={start_ip}, MAC={start_mac}, 数量={count}")
        if dst_mac and dst_mac != 'ff:ff:ff:ff:ff:ff':
            self._log(f"  L2 目标 MAC={dst_mac}")

        self._swarm = ScapyDroneSwarm(
            count=count, start_ip=start_ip, start_mac=start_mac,
            jitter=self._v_jitter.get(),
            field_jitter_pct=self._v_fj.get(),
            config=self._build_behavior_config(),
            log_fn=self._log,
        )

        self._runner = ScapyBidirectionalRunner(
            self._swarm, dst_ip, dst_port,
            real_mac=real_mac, gcs_mac=dst_mac, iface=iface,
            interval=self._v_interval.get(),
            duration=self._v_duration.get(),
            batch_size=self._v_batch.get(),
            respond=self._v_respond.get(),
            raw_imu_rate=self._v_raw_imu.get(),
            packed_state_rate=self._v_ps_rate.get(),
            extend_state_rate=self._v_es_rate.get(),
            on_log=self._log,
            on_tick=self._on_bidir_tick,
        )
        if not self._runner.available:
            messagebox.showerror("错误", "scapy 未安装\n请确保已安装 Npcap + pip install scapy")
            self._on_done()
            return

        self._runner.start()
        self._poll()

    def _start_netsh(self, count, dst_ip, dst_port):
        """IP 别名双向模式 — 与 fake_airplane.py 相同的方案: netsh + UDP socket"""
        self._v_mode_disp.set("模式: netsh IP 别名")
        iface = self._v_iface.get().strip()
        start_ip = self._v_start_ip.get().strip()
        mask = self._v_mask.get().strip()

        try:
            ip_to_int(start_ip)
        except Exception:
            messagebox.showerror("错误", "IP 起始地址格式不正确")
            self._on_done()
            return

        # ---- 智能修正：与本机同子网 ----
        my_ip = get_interface_ip(iface)
        my_mask = get_interface_netmask(iface)

        if not same_subnet(start_ip, my_ip, my_mask):
            old_sip = start_ip
            start_ip = suggest_start_ip(iface)
            self._log(f"⚠ 已自动修正 drone IP: {old_sip} → {start_ip} (本机子网)")
            self._log(f"  原因: 原 IP 不在本机子网，UDP 收包无法路由回来")
            # 更新 GUI 变量
            self._v_start_ip.set(start_ip)

        self._log(f"网卡: {iface}  |  本机 IP: {my_ip}")
        self._log(f"子网掩码: {my_mask}  |  Drone IP 起始: {start_ip}")

        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            messagebox.showerror("错误", "netsh 模式需要管理员权限")
            self._on_done()
            return

        self._log(f"检查地面站 {dst_ip} 可达性...")
        if not self._ping_check(dst_ip):
            self._log(f"⚠ 无法 ping 通 {dst_ip}")
            if not messagebox.askyesno("警告",
                                       f"无法 ping 通地面站 {dst_ip}。\n是否仍然继续？"):
                self._on_done()
                return
        else:
            self._log(f"地面站 {dst_ip} 可达 ✓")

        self._log(f"准备添加 {count} 个 IP 别名...")
        self._alias_mgr = IPAliasManager(iface, log_fn=self._log)
        self._alias_mgr.set_mask(mask)

        try:
            self._swarm = DroneSwarm(
                count=count, start_ip=start_ip, alias_mgr=self._alias_mgr,
                jitter=self._v_jitter.get(),
                field_jitter_pct=self._v_fj.get(),
                config=self._build_behavior_config(),
                log_fn=self._log,
            )
        except RuntimeError as e:
            messagebox.showerror("错误", str(e))
            self._on_done()
            return

        self._runner = BidirectionalRunner(
            self._swarm, dst_ip, dst_port,
            interval=self._v_interval.get(),
            duration=self._v_duration.get(),
            batch_size=self._v_batch.get(),
            respond=self._v_respond.get(),
            raw_imu_rate=self._v_raw_imu.get(),
            packed_state_rate=self._v_ps_rate.get(),
            extend_state_rate=self._v_es_rate.get(),
            on_log=self._log,
            on_tick=self._on_bidir_tick,
        )
        self._runner.start()
        self._poll()

    def _start_flood(self, count, dst_ip, dst_port):
        self._v_mode_disp.set("模式: 洪水 (scapy)")
        dst_mac = self._v_dst_mac.get().strip()

        self._flood_sender = FloodSender(dst_ip, dst_port, dst_mac)
        if not self._flood_sender.available:
            messagebox.showerror("错误", "scapy 未安装，无法使用洪水模式\npip install scapy")
            self._on_done()
            return
        try:
            ip_to_int(self._v_start_ip.get().strip())
            int(self._v_start_mac.get().strip().replace(':', '').replace('-', ''), 16)
        except Exception:
            messagebox.showerror("错误", "起始 IP 或 MAC 格式不正确")
            self._on_done()
            return

        self._runner = FloodRunner(
            self._flood_sender, count,
            self._v_start_ip.get().strip(),
            self._v_start_mac.get().strip(),
            self._v_interval.get(), self._v_duration.get(),
            self._v_batch.get(), self._v_jitter.get(),
            on_log=self._log, on_tick=self._on_flood_tick,
        )
        self._runner.start()
        self._poll()

    def _stop(self):
        if self.cluster_mode:
            return self._stop_cluster()

        if self._runner:
            self._runner.stop()
        # 清理 netsh 模式的资源
        if self._swarm:
            if hasattr(self._swarm, 'close_all'):
                self._swarm.close_all()
            self._swarm = None
        if self._alias_mgr:
            self._alias_mgr.remove_all()
            self._alias_mgr = None
        if self._flood_sender:
            self._flood_sender = None
        self._on_done()

    def _on_done(self):
        self._btn_start.configure(state=tk.NORMAL)
        self._btn_stop.configure(state=tk.DISABLED)
        self._v_status.set("已停止")
        self._progress.stop()
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None

    def _on_bidir_tick(self, s, rate, elapsed):
        # 心跳 tick 只更新发包层瞬时数据 (rate/PS/ES/elapsed); AP/GCS/Online 计数
        # 由 _refresh_online_counters 每 500ms 用最新 summary 刷新, 避免两边显示不一致
        if not hasattr(self, '_hb_view'):
            self._hb_view = {}
        # P0 性能埋点: 批量 sendp 平均耗时 + 应答队列溢出计数
        avg_ms = 0.0
        dropped = 0
        if hasattr(self._runner, '_send_rounds') and self._runner._send_rounds > 0:
            avg_ms = self._runner._send_total_us / self._runner._send_rounds / 1000.0
        if hasattr(self._runner, '_resp_dropped'):
            dropped = self._runner._resp_dropped
        self._hb_view.update({
            'rate': rate,
            'et': str(timedelta(seconds=int(elapsed))),
            'ps': getattr(self._runner, '_ps_sent', 0),
            'es': getattr(self._runner, '_es_sent', 0),
            'avg_send_ms': avg_ms,
            'perf_str': (f" | sendp={avg_ms:.0f}ms/轮"
                         + (f" ⚠丢弃={dropped}" if dropped else "")),
            'err_str': f" | ⚠发送错误: {getattr(self._runner, '_send_errors', 0)}"
                       if getattr(self._runner, '_send_errors', 0) else "",
        })

    def _on_flood_tick(self, s, rate, elapsed):
        et = str(timedelta(seconds=int(elapsed)))
        self._v_stats.set(
            f"发: {s['packets']:,} | {s['rate']:.0f} pps | 错误: {s['errors']} | {et}"
        )

    def _poll(self):
        if self._runner and self._runner.running():
            self._refresh_online_counters()
            self._poll_id = self.root.after(500, self._poll)
        else:
            self._on_done()

    def _refresh_status_bar(self):
        """统一用最新 summary + 最近心跳 tick 数据刷新底部状态栏。
        与 _refresh_online_counters 共享同一份 summary 快照, 保证三个面板数字始终一致。
        """
        if not hasattr(self, '_v_last_summary') or not hasattr(self, '_hb_view'):
            return
        s = self._v_last_summary
        v = self._hb_view
        ap_n = s.get('discovered_by_ap', 0)
        gcs_n = s.get('discovered', 0)
        online_n = s.get('gcs_online', 0)
        total = s['total']
        self._v_stats.set(
            f"①ARP {ap_n}/{total} | ②心跳 {gcs_n}/{total} | ③在线 {online_n}/{total} | "
            f"发: {s['total_sent']:,} 收: {s['total_recv']:,} | {v['rate']:.0f} pps | "
            f"PS: {v['ps']:,} ES: {v['es']:,}{v.get('perf_str', '')}{v['err_str']} | {v['et']}"
        )

    def _refresh_online_counters(self):
        """500ms 独立刷新 ARP/GCS心跳/地面站在线 三个计数器 + 同步状态栏。

        三个数字测的层面不同 (链路层/轮询层/应用层), 通常 ① ≥ ② ≥ ③。
        每次刷新前先按 GCS_ONLINE_TIMEOUT_S (6s, 对齐地面站 UdpTimeout) 清算
        超时的 discovered / gcs_online 标志, 让显示跟随地面站抖动而不是恒定不变。

        集群模式 (cluster_mode=True) 改为从 MasterServer.aggregate_stats() 汇总,
        三个计数器代表所有 slave 的总和。
        """
        if self.cluster_mode:
            return self._refresh_cluster_counters()

        if not self._runner or not hasattr(self._runner, 'swarm'):
            return
        # 超时清算: 对齐地面站 UavParser.cs:152-172 的 udpTimeout 检查
        now = time.time()
        cutoff_heartbeat = now - GCS_ONLINE_TIMEOUT_S
        cutoff_online = now - GCS_ONLINE_TIMEOUT_S
        for d in self._runner.swarm:
            if d.discovered and d.behavior.discovered_time < cutoff_heartbeat:
                d.discovered = False
            if d.gcs_online and d.behavior.gcs_online_time < cutoff_online:
                d.gcs_online = False
        try:
            s = self._runner.swarm.summary()
        except Exception:
            return
        self._v_last_summary = s  # 缓存最新 summary 供 _refresh_status_bar 使用
        total = s.get('total', 0) or 1
        ap = s.get('discovered_by_ap', 0)
        gcs = s.get('discovered', 0)
        online = s.get('gcs_online', 0)
        if hasattr(self, '_v_ap_count'):
            self._v_ap_count.set(f"{ap} / {total}")
            self._ap_bar['maximum'] = total
            self._ap_bar['value'] = ap
        if hasattr(self, '_v_gcs_count'):
            self._v_gcs_count.set(f"{gcs} / {total}")
            self._gcs_bar['maximum'] = total
            self._gcs_bar['value'] = gcs
        if hasattr(self, '_v_online_count'):
            self._v_online_count.set(f"{online} / {total}")
            self._online_bar['maximum'] = total
            self._online_bar['value'] = online
        # 同步刷新状态栏, 保证大字面板和底部状态栏数字完全一致
        if hasattr(self, '_hb_view'):
            self._refresh_status_bar()

    # ------------------------------------------------------------------
    # 集群模式专用方法
    # ------------------------------------------------------------------
    def _start_master_server(self):
        """启动 master TCP 服务器 (后台线程), 监听 CLUSTER_PORT 等 slave 连入"""
        if self._master_server:
            return
        self._master_server = MasterServer(
            bind_host="0.0.0.0",
            bind_port=CLUSTER_PORT,
            on_event=lambda: self.root.after(0, self._refresh_slave_tree),
        )
        try:
            self._master_server.start()
            self._log(f"✓ Master 服务器已监听 0.0.0.0:{CLUSTER_PORT}")
        except Exception as e:
            self._log(f"✗ Master 服务器启动失败: {e}")
            self._log(f"  可能是端口 {CLUSTER_PORT} 被占用, 请检查防火墙/其他程序")
            self._master_server = None

    def _cluster_poll(self):
        """集群模式 500ms 轮询: 刷新 slave 列表 + 聚合计数器"""
        if not self.cluster_mode:
            return
        self._refresh_slave_tree()
        self._refresh_cluster_counters()
        self._cluster_poll_id = self.root.after(500, self._cluster_poll)

    def _refresh_slave_tree(self):
        """根据 MasterServer.get_slave_list() 更新右侧 Treeview"""
        if not self._master_server or not hasattr(self, '_slave_tree'):
            return
        slaves = self._master_server.get_slave_list()
        # 清空现有行 (含 _empty 占位)
        for iid in self._slave_tree.get_children(''):
            self._slave_tree.delete(iid)
        if not slaves:
            self._slave_tree.insert('', 'end', iid='_empty',
                                    values=('<等待 slave 连入>', '', '', '', '', '', '', '', '', ''))
            return
        now = time.time()
        for s in slaves:
            ago = f"{int(now - s['last_seen'])}s"
            self._slave_tree.insert('', 'end', iid=s['slave_id'], values=(
                s['slave_id'], s['addr'], s['state'], s['count'], s['start_ip'],
                s['arp'], s['heartbeat'], s['online'], f"{s['rate']:.0f}", ago,
            ))

    def _refresh_cluster_counters(self):
        """从 MasterServer.aggregate_stats() 汇总三个计数器 + 状态栏"""
        if not self._master_server:
            return
        agg = self._master_server.aggregate_stats()
        total = agg.get('total', 0) or 1
        ap = agg.get('discovered_by_ap', 0)
        gcs = agg.get('discovered', 0)
        online = agg.get('gcs_online', 0)
        if hasattr(self, '_v_ap_count'):
            self._v_ap_count.set(f"{ap} / {total}")
            self._ap_bar['maximum'] = total
            self._ap_bar['value'] = ap
        if hasattr(self, '_v_gcs_count'):
            self._v_gcs_count.set(f"{gcs} / {total}")
            self._gcs_bar['maximum'] = total
            self._gcs_bar['value'] = gcs
        if hasattr(self, '_v_online_count'):
            self._v_online_count.set(f"{online} / {total}")
            self._online_bar['maximum'] = total
            self._online_bar['value'] = online
        # 同步状态栏 (集群模式聚合版)
        if hasattr(self, '_v_stats'):
            self._v_stats.set(
                f"Slaves: {agg['slave_count']} (ready {agg['ready_count']} / "
                f"running {agg['running_count']}) | "
                f"①ARP {ap}/{total} | ②心跳 {gcs}/{total} | ③在线 {online}/{total} | "
                f"发: {agg['total_sent']:,} 收: {agg['total_recv']:,} | "
                f"{agg['rate']:.0f} pps"
            )

    def _start_cluster(self):
        """集群模式: 广播 start 指令到所有已连接 slave"""
        if not self._master_server:
            messagebox.showerror("错误", "Master 服务器未启动")
            return
        slaves = self._master_server.get_slave_list()
        if not slaves:
            messagebox.showwarning("提示", "尚未有 slave 连入\n请先在其它 PC 启动 slave 进程")
            return
        ready = [s for s in slaves if s['state'] in ('ready', 'running')]
        if not ready:
            messagebox.showwarning("提示", f"共 {len(slaves)} 个 slave, 但无 ready 状态\n请等待 slave 完成初始化")
            return
        self._log(f"▶ 广播 start 到 {len(ready)} 个 slave ...")
        self._master_server.broadcast({"cmd": "start"})
        self._master_server.set_slave_state("running")
        self._btn_start.configure(state=tk.DISABLED)
        self._btn_stop.configure(state=tk.NORMAL)
        self._v_status.set("运行中 (集群)")
        self._progress.start(10)
        self._refresh_slave_tree()

    def _stop_cluster(self):
        """集群模式: 广播 stop 指令到所有 slave"""
        if not self._master_server:
            return
        self._log("■ 广播 stop 到所有 slave ...")
        self._master_server.broadcast({"cmd": "stop"})
        self._master_server.set_slave_state("stopped")
        self._btn_start.configure(state=tk.NORMAL)
        self._btn_stop.configure(state=tk.DISABLED)
        self._v_status.set("已停止 (集群)")
        self._progress.stop()
        self._refresh_slave_tree()

    def _on_close(self):
        if self.cluster_mode:
            # 集群模式退出: 提示是否同时停止所有 slave
            slaves = self._master_server.get_slave_list() if self._master_server else []
            running = [s for s in slaves if s['state'] == 'running']
            if running:
                if messagebox.askyesno("确认",
                        f"{len(running)} 个 slave 仍在运行\n退出前广播 stop?\n(是=停 slave 后退出, 否=直接退出 slave 继续跑)"):
                    self._stop_cluster()
            if self._master_server:
                self._master_server.stop()
            self.root.destroy()
            return

        if self._runner and self._runner.running():
            if messagebox.askyesno("确认", "测试正在运行，确定退出吗？"):
                self._stop()
                self.root.destroy()
        else:
            if self._alias_mgr:
                self._alias_mgr.remove_all()
            self.root.destroy()


# =====================================================================
# 集群通信层 (Master/Slave TCP+JSON, 端口 CLUSTER_PORT)
# - slave 进程无头运行, 启动参数指定本机负责的飞机范围 (start_ip/start_mac/count)
# - master 进程带 GUI, 监听 CLUSTER_PORT, 广播启停, 聚合统计
# 协议: 行分隔 JSON, 每条消息一行 \n 结尾, socket.makefile 按行读取
# =====================================================================

def _send_json_line(sock: socket.socket, obj: dict):
    """通过 socket 发送一行 JSON (以 \\n 结尾). 失败静默 (对端关闭属正常)."""
    try:
        sock.sendall((json.dumps(obj, ensure_ascii=False) + '\n').encode('utf-8'))
        return True
    except Exception:
        return False


def _recv_json_lines(sock: socket.socket, on_msg):
    """阻塞循环: 按行读取 socket, 解析 JSON, 调 on_msg(obj).
    读到 EOF 或异常时退出. on_msg 抛 StopIteration 时主动退出."""
    try:
        f = sock.makefile('r', encoding='utf-8', newline='\n')
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                on_msg(obj)
            except json.JSONDecodeError:
                continue
    except StopIteration:
        pass
    except Exception:
        pass


class _SlaveConn:
    """Master 侧: 表示一个 slave 连接, 缓存最新 hello + stats"""
    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = f"{addr[0]}:{addr[1]}"
        self.slave_id = None
        self.hello = None       # {"count":N, "start_ip":..., ...}
        self.stats = None       # 最近一次 stats 消息 (含 summary/rate/elapsed)
        self.last_seen = time.time()
        self.state = "connected"   # connected → ready → running → stopped


class MasterServer:
    """Master 侧 TCP 服务器. 后台 accept_loop 接受 slave 连接,
    每连接一个 handler 线程读消息. broadcast() 给所有 slave 发指令;
    aggregate_stats() 汇总所有 slave 的 summary 6 字段求和.
    """

    def __init__(self, bind_host="0.0.0.0", bind_port=CLUSTER_PORT, on_event=None):
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.on_event = on_event or (lambda: None)  # slave 上线/下线/状态变更时调
        self._sock = None
        self._accept_thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._slaves = {}  # slave_id -> _SlaveConn

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.bind_host, self.bind_port))
        self._sock.listen(64)
        self._sock.settimeout(0.5)
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def stop(self):
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        with self._lock:
            for sid, sc in list(self._slaves.items()):
                _send_json_line(sc.conn, {"cmd": "stop"})
                try:
                    sc.conn.close()
                except Exception:
                    pass
            self._slaves.clear()

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            t = threading.Thread(target=self._handle_slave, args=(conn, addr), daemon=True)
            t.start()

    def _handle_slave(self, conn, addr):
        sc = _SlaveConn(conn, addr)

        def on_msg(obj):
            mtype = obj.get('type')
            sc.last_seen = time.time()
            if mtype == 'hello':
                sc.slave_id = obj.get('slave_id') or sc.addr
                sc.hello = obj
                sc.state = "ready"
                with self._lock:
                    self._slaves[sc.slave_id] = sc
                self.on_event()
            elif mtype == 'ready':
                sc.state = "ready"
                self.on_event()
            elif mtype == 'stats':
                sc.stats = obj
                if sc.state == "ready":
                    sc.state = "running"
                self.on_event()
            elif mtype == 'bye':
                raise StopIteration

        try:
            _recv_json_lines(conn, on_msg)
        except StopIteration:
            pass
        # slave 断开
        if sc.slave_id:
            with self._lock:
                self._slaves.pop(sc.slave_id, None)
            self.on_event()
        try:
            conn.close()
        except Exception:
            pass

    def broadcast(self, cmd_dict):
        """给所有在线 slave 发指令, 如 {"cmd":"start"} / {"cmd":"stop"}"""
        with self._lock:
            conns = [sc.conn for sc in self._slaves.values()]
        for c in conns:
            _send_json_line(c, cmd_dict)

    def set_slave_state(self, new_state):
        """广播 start/stop 后, 更新所有 slave 的预期状态 (UI 立即响应, 不等下次 stats)"""
        with self._lock:
            for sc in self._slaves.values():
                if new_state == "running" and sc.state == "ready":
                    sc.state = "running"
                elif new_state == "stopped" and sc.state == "running":
                    sc.state = "stopped"

    def aggregate_stats(self) -> dict:
        """汇总所有 slave 的 summary 6 字段求和 + slave 数 + 总架数"""
        agg = {
            'total_sent': 0, 'total_recv': 0,
            'discovered': 0, 'discovered_by_ap': 0, 'gcs_online': 0,
            'total': 0, 'rate': 0.0,
            'slave_count': 0, 'ready_count': 0, 'running_count': 0,
        }
        with self._lock:
            slaves = list(self._slaves.values())
        for sc in slaves:
            agg['slave_count'] += 1
            if sc.state == "ready":
                agg['ready_count'] += 1
            elif sc.state == "running":
                agg['running_count'] += 1
            if sc.hello:
                agg['total'] += int(sc.hello.get('count', 0))
            if sc.stats:
                s = sc.stats.get('summary', {})
                for k in ('total_sent', 'total_recv', 'discovered',
                          'discovered_by_ap', 'gcs_online'):
                    agg[k] += int(s.get(k, 0))
                agg['rate'] += float(sc.stats.get('rate', 0))
        return agg

    def get_slave_list(self) -> list:
        """返回 slave 列表 (供 UI Treeview 渲染). 每条含:
        slave_id/addr/state/count/start_ip/arp/heartbeat/online/rate/last_seen"""
        with self._lock:
            slaves = list(self._slaves.values())
        out = []
        for sc in slaves:
            s = (sc.stats.get('summary', {})) if sc.stats else {}
            out.append({
                'slave_id': sc.slave_id or sc.addr,
                'addr': sc.addr,
                'state': sc.state,
                'count': int(sc.hello.get('count', 0)) if sc.hello else 0,
                'start_ip': sc.hello.get('start_ip', '') if sc.hello else '',
                'arp': int(s.get('discovered_by_ap', 0)),
                'heartbeat': int(s.get('discovered', 0)),
                'online': int(s.get('gcs_online', 0)),
                'rate': float(sc.stats.get('rate', 0)) if sc.stats else 0.0,
                'last_seen': sc.last_seen,
            })
        return out


class SlaveClient:
    """Slave 侧: 连接 master, 拦截 runner.on_tick/on_log 转发, 响应 start/stop 指令.
    生命周期: start() 连接 master + 发 hello/ready + 启动 recv 线程
              收到 start → runner.start(); 收到 stop → runner.stop()
              主进程 stop() → 断开 master, 停止 runner
    """

    def __init__(self, master_host, master_port, slave_id, swarm, runner, hello_info):
        self.master_host = master_host
        self.master_port = master_port
        self.slave_id = slave_id
        self.swarm = swarm
        self.runner = runner
        self.hello_info = hello_info   # dict, 随 hello 消息发到 master
        self._sock = None
        self._stop = threading.Event()
        self._log_buf = []
        self._log_lock = threading.Lock()
        self._last_log_flush = 0.0

    def start(self):
        """连接 master (失败重试 30s), 发 hello + ready, 启动 recv 线程"""
        deadline = time.time() + 30
        while time.time() < deadline and not self._stop.is_set():
            try:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.settimeout(5)
                self._sock.connect((self.master_host, self.master_port))
                self._sock.settimeout(None)
                break
            except Exception as e:
                print(f"[slave {self.slave_id}] 连接 master 失败 ({e}), 2s 后重试")
                time.sleep(2)
        if not self._sock:
            raise RuntimeError(f"无法连接 master {self.master_host}:{self.master_port}")

        # 拦截 runner 的 on_tick/on_log 回调
        self.runner.on_tick = self._on_tick
        self.runner.on_log = self._on_log

        # 发 hello + ready
        hello = dict(self.hello_info)
        hello['type'] = 'hello'
        hello['slave_id'] = self.slave_id
        _send_json_line(self._sock, hello)
        _send_json_line(self._sock, {"type": "ready", "slave_id": self.slave_id})
        print(f"[slave {self.slave_id}] 已连接 master {self.master_host}:{self.master_port}, 等待 start 指令")

        t = threading.Thread(target=self._recv_loop, daemon=True)
        t.start()

    def _recv_loop(self):
        def on_msg(obj):
            cmd = obj.get('cmd')
            if cmd == 'start':
                if not self.runner.running():
                    print(f"[slave {self.slave_id}] 收到 start, 开始发包")
                    self.runner.start()
            elif cmd == 'stop':
                if self.runner.running():
                    print(f"[slave {self.slave_id}] 收到 stop, 停止发包")
                    self.runner.stop()
            elif cmd == 'status':
                try:
                    s = self.swarm.summary()
                    _send_json_line(self._sock, {
                        "type": "stats", "slave_id": self.slave_id,
                        "summary": s, "rate": 0, "elapsed": 0,
                    })
                except Exception:
                    pass
        try:
            _recv_json_lines(self._sock, on_msg)
        except Exception:
            pass
        # master 断开
        print(f"[slave {self.slave_id}] master 连接断开, 停止发包")
        if self.runner.running():
            self.runner.stop()
        self._stop.set()

    def _on_tick(self, summary, rate, elapsed):
        """runner.on_tick 回调: 上报 stats 到 master (频率 = runner 心跳轮节奏, 通常 3s/次)"""
        if self._stop.is_set() or not self._sock:
            return
        _send_json_line(self._sock, {
            "type": "stats", "slave_id": self.slave_id,
            "summary": summary, "rate": rate, "elapsed": elapsed,
        })

    def _on_log(self, msg):
        """runner.on_log 回调: 转发到 master (1Hz 滑窗合并, 避免大量小包刷屏)"""
        print(f"[slave {self.slave_id}] {msg}")
        now = time.time()
        with self._log_lock:
            self._log_buf.append(msg)
            if now - self._last_log_flush >= 1.0:
                msgs = self._log_buf[:]
                self._log_buf.clear()
                self._last_log_flush = now
            else:
                msgs = None
        if msgs and self._sock and not self._stop.is_set():
            combined = ' | '.join(msgs[-3:])  # 只取最近 3 条
            _send_json_line(self._sock, {
                "type": "log", "slave_id": self.slave_id,
                "msg": combined, "level": "info",
            })

    def stop(self):
        self._stop.set()
        if self.runner.running():
            self.runner.stop()
        if self._sock:
            _send_json_line(self._sock, {"type": "bye", "slave_id": self.slave_id})
            try:
                self._sock.close()
            except Exception:
                pass


def _gen_slave_id():
    """生成 slave 唯一 ID: hostname + PID"""
    try:
        host = socket.gethostname()
    except Exception:
        host = "unknown"
    return f"{host}-{os.getpid()}"


def slave_main(args):
    """Slave 进程入口: 构造 swarm+runner+SlaveClient, 等待 master start"""
    slave_id = args.slave_id or _gen_slave_id()
    print(f"[slave {slave_id}] 启动中: count={args.count} start_ip={args.start_ip} iface={args.iface}")

    swarm = ScapyDroneSwarm(
        count=args.count,
        start_ip=args.start_ip,
        start_mac=args.start_mac,
        config={'jitter': not args.no_jitter,
                'state_machine': not args.no_state_machine},
        log_fn=lambda m: print(f"[slave {slave_id}] {m}"),
    )

    # 解析 master host:port
    if ':' in args.master:
        master_host, master_port = args.master.rsplit(':', 1)
        master_port = int(master_port)
    else:
        master_host = args.master
        master_port = CLUSTER_PORT

    hello_info = {
        'count': args.count,
        'start_ip': args.start_ip,
        'start_mac': args.start_mac,
        'iface': args.iface,
        'gcs_ip': args.gcs_ip,
        'gcs_port': args.gcs_port,
        'interval': args.interval,
    }

    runner = ScapyBidirectionalRunner(
        swarm=swarm,
        gcs_ip=args.gcs_ip,
        gcs_port=args.gcs_port,
        real_mac=args.real_mac,
        gcs_mac=args.gcs_mac or None,
        iface=args.iface,
        interval=args.interval,
        duration=0,  # slave 模式 duration 由 master 控制
        batch_size=args.batch_size,
        respond=not args.no_respond,
        raw_imu_rate=args.raw_imu_rate,
        on_log=lambda m: None,   # 占位, SlaveClient.start() 会拦截
        on_tick=None,
    )

    if not runner.available:
        print(f"[slave {slave_id}] scapy 不可用, 退出")
        sys.exit(1)

    slave_client = SlaveClient(master_host, master_port, slave_id, swarm, runner, hello_info)

    # Ctrl-C 优雅退出
    import signal
    def _sig_handler(signum, frame):
        print(f"[slave {slave_id}] 收到信号 {signum}, 退出")
        slave_client.stop()
        sys.exit(0)
    signal.signal(signal.SIGINT, _sig_handler)
    try:
        signal.signal(signal.SIGTERM, _sig_handler)
    except (AttributeError, ValueError):
        pass  # Windows 无 SIGTERM

    slave_client.start()
    # 主线程阻塞直到 slave_client 断开
    while not slave_client._stop.is_set():
        time.sleep(0.5)
    print(f"[slave {slave_id}] 主循环退出")


def _build_argparser():
    import argparse
    p = argparse.ArgumentParser(
        prog="dgcs_stress_test",
        description=f"DGCS 地面站压力测试工具 v{TOOL_VERSION} (单机 / 集群 master / 集群 slave)",
    )
    p.add_argument("--cluster", action="store_true",
                   help="以集群 master 模式启动 (监听端口等 slave 连接, 默认单机模式)")
    sub = p.add_subparsers(dest="mode")
    sp = sub.add_parser("slave", help="以集群 slave 模式启动 (无头, 连接 master)")
    sp.add_argument("--master", required=True, metavar="HOST[:PORT]",
                    help=f"master 地址 (默认端口 {CLUSTER_PORT}, 例: 192.168.1.10 或 192.168.1.10:{CLUSTER_PORT})")
    sp.add_argument("--count", type=int, required=True, help="本 slave 模拟的飞机数量")
    sp.add_argument("--start-ip", required=True, help="起始飞机 IP")
    sp.add_argument("--start-mac", required=True, help="起始飞机 MAC")
    sp.add_argument("--iface", required=True, help="scapy 接口名 (Windows: \\\\Device\\\\NPF_{GUID})")
    sp.add_argument("--gcs-ip", required=True, help="地面站 IP")
    sp.add_argument("--gcs-port", type=int, default=14550, help="地面站端口 (默认 14550)")
    sp.add_argument("--gcs-mac", default="", help="地面站 MAC (留空用广播)")
    sp.add_argument("--real-mac", default="", help="本机真实 MAC (留空自动检测)")
    sp.add_argument("--interval", type=float, default=3.0, help="HEARTBEAT 间隔秒 (默认 3)")
    sp.add_argument("--batch-size", type=int, default=50, help="批量发送大小 (默认 50)")
    sp.add_argument("--raw-imu-rate", type=float, default=0.0, help="RAW_IMU 主动频率 Hz (默认 0=关)")
    sp.add_argument("--no-respond", action="store_true", help="不响应 GCS 心跳 (仅主动发 HEARTBEAT)")
    sp.add_argument("--no-jitter", action="store_true", help="关闭字段抖动")
    sp.add_argument("--no-state-machine", action="store_true", help="关闭飞机状态机")
    sp.add_argument("--slave-id", default="", help="slave 唯一 ID (留空自动生成 host-pid)")
    return p


# =====================================================================
def main():
    parser = _build_argparser()
    args = parser.parse_args()

    if args.mode == "slave":
        slave_main(args)
        return

    if not HAS_TK:
        print("错误: 需要 tkinter")
        sys.exit(1)
    root = tk.Tk()
    App(root, cluster_mode=args.cluster)
    root.mainloop()


if __name__ == "__main__":
    main()
