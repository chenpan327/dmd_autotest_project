#!/usr/bin/env python3
"""
DAV Protocol Frame Parser - CLI tool for decoding DAV protocol hex frames.

Usage:
    python dav_frame_parser.py <hex_string>
    echo "<hex>" | python dav_frame_parser.py
    python dav_frame_parser.py --file <file_with_hex_lines>
"""
import struct
import sys
import argparse


# =============================================================================
# Enum value maps
# =============================================================================

UINT32_VALUE = {
    0: "DAV_NO_ERROR",
    1: "DAV_COMMAND_ACK_BOOTLOADER_VERSION",
    2: "DAV_COMMAND_ACK_APP_VERSION",
    3: "DAV_COMMAND_RETURN_TO_BOOTLOADER",
    4: "DAV_COMMAND_MESSAGE_DISABLE_BROADCAST",
    5: "DAV_COMMAND_MESSAGE_ENABLE_BROADCAST",
    6: "DAV_COMMAND_BOOT_ERASE_FLASH_ADDRESS",
    7: "DAV_COMMAND_ASK_DAV_ADDRESS",
    8: "DAV_COMMAND_ENABLE_REMOTE_CONTROL_FREQ_MATCH",
    9: "DAV_COMMAND_DISABLE_REMOTE_CONTROL_FREQ_MATCH",
    10: "DAV_COMMAND_ASK_CHIP_UID",
    11: "DAV_COMMAND_ASK_PRODUCT_SERIAL_NUMBER",
    12: "DAV_COMMAND_SET_850M_V3_RECEIVE_MODE",
    13: "DAV_COMMAND_SET_850M_R2_RECEIVE_MODE",
    14: "DAV_COMMAND_SET_24G_REMOTE_CONTROL_MODE",
    15: "DAV_COMMAND_SET_24G_RTCM_MODE",
    16: "DAV_COMMAND_ASK_BOOTLOADER_SHA256",
    17: "DAV_COMMAND_ASK_APP_SHA256",
    18: "DAV_COMMAND_ASK_PROTOCOL_SHA256",
    19: "DAV_COMMAND_ASK_PROTO_VERSION_INT",
    20: "DAV_COMMAND_ASK_REMOTE_CONTROL_MATCHING_CODE",
    21: "DAV_COMMAND_ASK_RADIO_R2_850M_MATCHING_CODE",
    22: "DAV_COMMAND_ASK_RADIO_R2_24G_MATCHING_CODE",
    23: "DAV_COMMAND_ACK_HEARTBEAT",
    24: "DAV_COMMAND_SET_850M_V3_LOW_RATE_RECEIVE_MODE",
    25: "DAV_COMMAND_SET_850M_SCAN_RECEIVE_MODE",
    26: "DAV_COMMAND_SET_24G_SCAN_RECEIVE_MODE",
    27: "DAV_COMMAND_ASK_DEVICE_LAN_CONFIG",
    28: "DAV_COMMAND_ASK_LORA_RADIO_WORK_MODE",
    30: "DAV_COMMAND_ACK_RECEIVER_DMD_AUTO_TEST_STATUS",
    31: "DAV_COMMAND_ACK_ELRS_DMD_AUTO_TEST_STATUS",
    32: "DAV_COMMAND_ACK_HARDFAULT_INFO",
    33: "DAV_COMMAND_SEARCH_SUB_RADIO_STATION",
    34: "DAV_COMMAND_CALIBRATE_GIMBAL",
    35: "DAV_COMMAND_STORAGE_GIMBAL",
    36: "DAV_COMMAND_WORK_GIMBAL",
    37: "DAV_COMMAND_LD_PROC_GIMBAL",
    38: "DAV_COMMAND_DEBUG_GIMBAL",
    39: "DAV_COMMAND_GIMBAL_CHANNEL",
    40: "DAV_COMMAND_ASK_RADIO_ENCRYPT_KEY",
    500: "DAV_ERROR_PROTOBUF_DESERIALIZE_FAIL",
    501: "DAV_ERROR_MEMORY_NO_ENOUGH",
    502: "DAV_ERROR_INTERFACE_NOT_FOUND",
    503: "DAV_ERROR_ROUTE_ADDRESS_NOT_FOUND",
    504: "DAV_ERROR_INTERFACE_INDEX_SET_BEYOND",
    505: "DAV_ERROR_INTERFACE_INDEX_SET_REPEAT",
    506: "DAV_ERROR_PRODUCT_SERIAL_NUM_FORMAT_WRONG",
    507: "DAV_ERROR_PRODUCT_SERIAL_NUM_SET_REPEAT",
    1000: "DAV_STATUS_REMOTE_CONTROL_RECEIVER_NO_EXIST",
    1001: "DAV_STATUS_REMOTE_CONTROL_RECEIVER_INIT_FAIL",
    1002: "DAV_STATUS_REMOTE_CONTROL_RECEIVER_FREQ_MATCHING_TIMEOUT",
    1003: "DAV_STATUS_REMOTE_CONTROL_RECEIVER_FOREVER_LOST_SIGNAL",
    1004: "DAV_STATUS_REMOTE_CONTROL_RECEIVER_TEMPORARILY_LOST_SIGNAL",
    1010: "DAV_STATUS_RADIO_850M_RECEIVER_NO_EXIST",
    1011: "DAV_STATUS_RADIO_850M_RECEIVER_INIT_FAIL",
    1012: "DAV_STATUS_RADIO_850M_FOREVER_LOST_SIGNAL",
    1013: "DAV_STATUS_RADIO_850M_TEMPORARILY_LOST_SIGNAL",
    1020: "DAV_STATUS_RADIO_2400M_RECEIVER_NO_EXIST",
    1021: "DAV_STATUS_RADIO_2400M_RECEIVER_INIT_FAIL",
    1022: "DAV_STATUS_LPPC_CONTROL_RECEIVER_NO_EXIST",
    1023: "DAV_STATUS_LPPC_CONTROL_RECEIVER_INIT_FAIL",
    1024: "DAV_STATUS_RADIO_2400M_FOREVER_LOST_SIGNAL",
    1025: "DAV_STATUS_RADIO_2400M_TEMPORARILY_LOST_SIGNAL",
    1026: "DAV_LPPC_MODIFY_REGISTER_FAILED",
    2000: "DAV_REPORT_REMOTE_CONTROL_FREQ_MATCH_SUCCESS",
    2001: "DAV_REPORT_REMOTE_CONTROL_FREQ_MATCH_TIMEOUT",
}

ONLINE_DEVICE_TYPE = {0: "UAV", 1: "PORTABLE_POWER_SOURCE", 2: "RADIO_STATION"}

ENROLL_RESULT = {0: "accepted", 1: "repeated", 2: "out_capacity", 3: "check_fail", 4: "sn_error"}

SUB_DEVICE_TYPE = {
    0: "UAV_V4", 1: "PORTABLE_POWER_SOURCE_V1", 2: "RADIO_R2_STATION_850M_930M_V1",
    3: "RADIO_R2_STATION_2G4_V1", 4: "PAYLOAD_GIMBAL", 5: "RADIO_R2_STATION", 6: "PAYLOAD_HLT",
}

FIRMWARE_RUNNING_STATUS = {0: "normal", 1: "updating", 2: "standby", 3: "power_off", 4: "calibrating", 5: "emergency"}

RADIO_REGULATORY_DOMAIN = {
    0: "COUNTRY_CODE_MUTE", 2: "COUNTRY_CODE_V3_MODE", 3: "COUNTRY_CODE_V3_NEW_MODE",
    4: "COUNTRY_CODE_EU869", 5: "COUNTRY_CODE_R2_ISM2G4", 6: "COUNTRY_CODE_R2_850M_930M",
    7: "COUNTRY_CODE_RC_ISM2G4", 8: "COUNTRY_CODE_R2_ISM2G4_SHORT_INTERVAL",
    100: "COUNTRY_CODE_SCAN", 101: "COUNTRY_CODE_FACTORY_TEST", 102: "COUNTRY_CODE_CW",
    103: "COUNTRY_CODE_CALI_FRE_OFFSET_SNED", 104: "COUNTRY_CODE_CALI_FRE_OFFSET_RECEIVER",
    105: "COUNTRY_CODE_RC_BINDING",
}

RADIO_R2_ERROR_VALUE = {
    0: "R2_OK", 1: "R2_ERROR_MEMORY", 2: "R2_ERROR_RADIO_CHIP",
    3: "R2_ERROR_ETHERNET", 4: "R2_ERROR_OVERHEAT",
}

ENUM_MAPS = {
    "Uint32Value": UINT32_VALUE,
    "onlineDeviceType": ONLINE_DEVICE_TYPE,
    "enrollResult": ENROLL_RESULT,
    "subDeviceType": SUB_DEVICE_TYPE,
    "firmwareRunningStatus": FIRMWARE_RUNNING_STATUS,
    "radioRegulatoryDomain": RADIO_REGULATORY_DOMAIN,
    "RadioR2ErrorValue": RADIO_R2_ERROR_VALUE,
}


# =============================================================================
# Message field schemas:  field_num -> (name, wire_type, proto_type, repeated, enum_map)
# =============================================================================

def _f(name, proto_type, enum_map=None):
    """Shorthand for a non-repeated field."""
    return (name, proto_type, False, enum_map)

def _rf(name, proto_type, enum_map=None):
    """Shorthand for a repeated field."""
    return (name, proto_type, True, enum_map)

# Type codes: V=varint, F4=fixed32, F8=fixed64, S=string/bytes, M=sub-message, FL=float
V = "varint"; F4 = "fixed32"; F8 = "fixed64"; S = "bytes"; FL = "float"

MESSAGE_SCHEMAS = {
    "UniversalCommand": {
        1: _f("command", V, UINT32_VALUE),
    },
    "DavAddress": {
        1: _f("address", F8),
    },
    "SingleBytes": {
        1: _f("msg", S),
    },
    "ProductSerialNumber": {
        1: _f("serial_number", S),
        2: _f("year", V),
        3: _f("month", V),
        4: _f("day", V),
        5: _f("hour", V),
        6: _f("minute", V),
    },
    "EnrollRequest": {
        1: _f("device_type", V, ONLINE_DEVICE_TYPE),
        2: _f("product_name", S),
        3: _f("serial_number", S),
        4: _f("check", V),
    },
    "EnrollReply": {
        1: _f("accept_status", V, ENROLL_RESULT),
        2: _f("heartbeat_interval_ms", V),
    },
    "PpsHeartBeat": {
        1: _f("device_type", V, SUB_DEVICE_TYPE),
        2: _f("firmware_running_status", V, FIRMWARE_RUNNING_STATUS),
        3: _f("firmware_version_alias", S),
        4: _f("firmware_version", F4),
        5: _f("protobuf_version", V),
        6: _f("local_ms_time", F4),
        7: _f("portable_charger", "PortableChargerHeartbeat"),
    },
    "SubModuleLogSave": {
        1: _f("msg_id", V),
        2: _f("log_data", S),
    },
    "DeviceLocalAreaNetworkConfig": {
        1: _f("device_ipv4", S),
        2: _f("ipv4_gateway", S),
        3: _f("ipv4_subnet_mask", S),
        4: _rf("dest_ip_port", "NetDestIpPort"),
    },
    "NetDestIpPort": {
        1: _f("dest_ipv4", S),
        2: _f("dest_port", V),
        3: _f("local_port", V),
    },
    "RtcmLinkInfo": {
        1: _f("radio_850m_chan", V),
        2: _f("gps_utc_time", V),
    },
    "EncryptKey": {
        1: _f("encrypt_type", V),
        2: _f("encrypt_key", S),
        3: _f("encrypt_iv", S),
    },
    "RadioEncryptKey": {
        1: _f("radio_key", "EncryptKey"),
        2: _f("rc_key", "EncryptKey"),
    },
    "RemoteControlChannel": {
        1: _rf("channel_value", V),
    },
    "RadioReceiverMode": {
        1: _f("radio_850m_mode", V),
        2: _f("radio_2g4_mode", V),
        3: _f("radio_850m_binding_code", V),
        4: _f("radio_2g4_binding_code", V),
    },
    "RadioReceiveRSSI": {
        1: _f("radio_850m_status", V),
        2: _f("radio_850m_1074_num_per_secode", V),
        3: _f("radio_2400M_status", V),
        4: _f("radio_2g4_1074_num_per_secode", V),
    },
    "RemoteControlRSSI": {
        1: _f("remote_control_status", V),
        2: _f("remote_control_pkg_per", V),
    },
    "RFparameters": {
        1: _f("rf_work_mode", V, RADIO_REGULATORY_DOMAIN),
        2: _rf("rf_tx_power_dbm", V),
        3: _f("rf_temperature", V),
        4: _rf("rf_max_fre", V),
        5: _rf("rf_min_fre", V),
    },
    "RadioReceiverRFparameters": {
        1: _f("rc_binding_code", V),
        2: _rf("radio_binding_code", V),
        3: _rf("receiver_radio_param", "RFparameters"),
        4: _rf("radio_id_enable_bit", V),
    },
    "ReceiverDmdAutoTestStatus": {
        1: _rf("channel_value", V),
        2: _f("remote_control_fre", V),
        3: _f("radio_2g4_chip_status", V),
        4: _f("radio_2g4_rssi", V),
        5: _f("radio_850m_chip_status", V),
        6: _f("radio_850m_rssi", V),
        7: _f("radio_2g4_match_code", V),
        8: _f("radio_850m_match_code", V),
    },
    "ElrsDmdAutoTestStatus": {
        1: _rf("channel_value", V),
        2: _f("remote_control_fre", V),
        3: _f("radio_chip_status", V),
        4: _f("radio_temperature", FL),
        5: _f("match_code", V),
    },
    "LoraRadioFactoryTest": {
        1: _f("cmd", V),
        2: _rf("param", V),
    },
    "RadioStationRegulatoryDomain": {
        1: _f("set_device_id", V),
        2: _rf("set_rf_param", "RFparameters"),
    },
    "rtkStationPosition": {
        1: _f("device_id", V),
        2: _f("latitude", F8),
        3: _f("longitude", F8),
        4: _f("altitude", F8),
    },
    "RadioButtonParam": {
        1: _rf("long_click_time", V),
        2: _rf("long_click_button_mode", V),
        3: _rf("short_click_button_mode", V),
    },
    "radioStationR2HeartBeatExtend": {
        1: _f("device_id", V),
        2: _f("error_report", V, RADIO_R2_ERROR_VALUE),
        3: _f("ethernet_ip", S),
        4: _f("battery_percentage", V),
        5: _f("poe_voltage_mv", V),
        6: _f("charge_temperature", V),
        7: _f("gps_utc_time", V),
        8: _rf("radioGroupPosition", "rtkStationPosition"),
        9: _rf("radio_rf_param", "RFparameters"),
        10: _f("button_param", "RadioButtonParam"),
        11: _f("encrypt_type", V),
        12: _f("translate_data_left_bytes", V),
    },
    "radioStationR2Heart": {
        1: _f("device_type", V, SUB_DEVICE_TYPE),
        2: _f("firmware_running_status", V, FIRMWARE_RUNNING_STATUS),
        3: _f("firmware_version_alias", S),
        4: _f("firmware_version", F4),
        5: _f("protobuf_version", V),
        6: _f("local_ms_time", F4),
        7: _f("radio_station_r2", "radioStationR2HeartBeatExtend"),
    },
    "RadioRFParamEcho": {
        1: _f("upper_frequency", F4),
        2: _f("lower_frequency", F4),
        3: _f("bandwide", F4),
        4: _f("frequency_channel_num", V),
        5: _f("average_tx_power", FL),
        6: _f("send_duty_cycle", V),
    },
    "RadioRFParamsEcho": {
        1: _rf("rf_echo", "RadioRFParamEcho"),
    },
    "laserGimbalHeartExtend": {
        1: _f("temperature", FL),
        2: _f("lr_st", V),
        3: _f("lg_st", V),
        4: _f("lb_st", V),
        5: _f("cur_roll", FL),
        6: _f("cur_pitch", FL),
    },
    "laserGimbalHeart": {
        1: _f("device_type", V, SUB_DEVICE_TYPE),
        2: _f("running_status", V, FIRMWARE_RUNNING_STATUS),
        3: _f("firmware_version", F4),
        4: _f("protobuf_version", V),
        5: _f("local_ms_time", F4),
        6: _f("gimbal_extend_status", "laserGimbalHeartExtend"),
    },
    "AttitudeInfo": {
        1: _f("stamp", F8),
        2: _f("roll", FL),
        3: _f("pitch", FL),
        4: _f("yaw", FL),
        5: _f("gx", FL),
        6: _f("gy", FL),
        7: _f("gz", FL),
    },
    "GpsInfo": {
        1: _f("stamp", F8),
        2: _rf("pos", FL),
        3: _rf("vel", FL),
        4: _rf("pos_noise", FL),
        5: _rf("vel_noise", FL),
    },
    "TargetAngleInfo": {
        1: _f("stamp", F8),
        2: _f("enable", V),
        3: _f("mode", V),
        4: _f("x", FL),
        5: _f("y", FL),
        6: _f("z", FL),
    },
    "novaLightHeart": {
        1: _f("device_type", V, SUB_DEVICE_TYPE),
        2: _f("running_status", V, FIRMWARE_RUNNING_STATUS),
        3: _f("firmware_version", F4),
        4: _f("protobuf_version", V),
        5: _f("local_ms_time", F4),
        6: _f("state", V),
    },
    "FirmwareInfo": {
        1: _f("split_len", V),
        2: _f("split_sum", V),
        3: _f("firmware_version", F4),
        4: _f("firmware_len", F4),
        5: _f("hardware_code", F4),
        6: _f("firmware_address", F4),
        7: _f("firmware_param_address", F4),
        8: _f("firmware_write_address", F4),
        9: _f("firmware_type", V),
        10: _f("security_info", V),
        11: _f("firmware_sha256", S),
    },
    "FirmwarePackage": {
        1: _f("package_seq", V),
        2: _f("firmware_data", S),
    },
    "DgcsControlPPS": {
        1: _f("chg_disch_open", V),
        2: _f("fan_open", V),
        3: _f("heat_open", V),
        4: _f("bazz_open", V),
        5: _f("ds_open", V),
    },
}


# =============================================================================
# CMD map: cmd_id -> (enum_name, description, message_type)
# =============================================================================

CMD_MAP = {
    0x0000: ("GET_FIRMWARE_VERSION", "发送端向接收端询问版本", "UniversalCommand"),
    0x0001: ("ASK_DAV_ADDRESS", "发送端向接收端询问地址", "UniversalCommand"),
    0x0002: ("SEND_DAV_ADDRESS", "接收端向发送端发送自身地址", "DavAddress"),
    0x0003: ("CHANGE_DAV_ADDRESS", "发送端向接收端修改其地址", "DavAddress"),
    0x0004: ("ASK_CHIP_UID", "发送端向接收端询问UID", "UniversalCommand"),
    0x0005: ("SEND_CHIP_UID", "接收端向发送端发送自身UID", "SingleBytes"),
    0x0006: ("SET_PRODUCT_SERIAL_NUMBER", "设置SN码", "ProductSerialNumber"),
    0x0007: ("ASK_PRODUCT_SERIAL_NUMBER", "询问SN码", "UniversalCommand"),
    0x0008: ("SEND_PRODUCT_SERIAL_NUMBER", "发送SN码", "ProductSerialNumber"),
    0x0009: ("ASK_VERSION_SHA", "询问固件的SHA256哈希值", "UniversalCommand"),
    0x000A: ("SEND_VERSION_SHA", "发送SHA256哈希值", "SingleBytes"),
    0x000B: ("ASK_DAV_PROTO_VERSION_INT", "询问proto文件版本", "UniversalCommand"),
    0x000C: ("ENROLL_REQUEST", "向地面站请求注册", "EnrollRequest"),
    0x000D: ("ENROLL_REPLY", "地面站向设备端下发注册结果", "EnrollReply"),
    0x000E: ("ASK_HEARTBEAT", "地面站向设备端询问心跳包", "UniversalCommand"),
    0x000F: ("PPS_HEARTBEAT", "PPS的心跳包", "PpsHeartBeat"),
    0x0010: ("SUBMODULE_TRANS_SAVE_LOG", "子模块发送给飞控log", "SubModuleLogSave"),
    0x0011: ("ASK_DEVICE_LAN_CONFIG", "询问设备局域网配置", "UniversalCommand"),
    0x0012: ("SEND_DEVICE_LAN_CONFIG", "发送设备局域网配置", "DeviceLocalAreaNetworkConfig"),
    0x0013: ("SET_DEVICE_LAN_CONFIG", "设置设备局域网配置", "DeviceLocalAreaNetworkConfig"),
    0x0014: ("ASK_HARDFAULT_INFO", "查询设备的hardfault信息", "UniversalCommand"),
    0x0015: ("SEND_HARDFAULT_INFO", "发送设备的hardfault信息", "SingleBytes"),
    0x0100: ("RADIO_SEND_RTCM", "由接收机发向飞控的RTCM信息", "SingleBytes"),
    0x0101: ("RADIO_RTCM_LINK_INFO", "飞控向接收机发送电台配置", "RtcmLinkInfo"),
    0x0102: ("SET_RADIO_ENCRYPT_KEY", "设置遥控器加密秘钥", "RadioEncryptKey"),
    0x0103: ("ASK_RADIO_ENCRYPT_KEY", "查询加密秘钥", "UniversalCommand"),
    0x0104: ("SEND_RADIO_ENCRYPT_KEY", "返回加密秘钥", "RadioEncryptKey"),
    0x0110: ("REMOTE_CONTROL_SEND_CHANNEL", "接收机向飞控发送遥控器通道值", "RemoteControlChannel"),
    0x0111: ("SET_RADIO_RECEIVER_MODE", "设置接收机工作模式和对频码", "RadioReceiverMode"),
    0x0112: ("REMOTE_CONTROL_FREQ_MATCHING", "使能遥控器对频模式", "UniversalCommand"),
    0x0113: ("REMOTE_CONTROL_FREQ_MATCHING_RESULT", "对频结果", "UniversalCommand"),
    0x0114: ("RADIO_RECEIVER_RSSI", "接收机接收电台信号的状态", "RadioReceiveRSSI"),
    0x0115: ("REMOTE_CONTROL_RECEIVER_RSSI", "接收机接收遥控器的状态", "RemoteControlRSSI"),
    0x0117: ("GET_RECEIVER_RC_AND_RADIO_PARAM", "获取接收机遥控器和电台参数", "UniversalCommand"),
    0x0118: ("SEND_RECEIVER_RC_AND_RADIO_PARAM", "发送接收机遥控器和电台参数", "RadioReceiverRFparameters"),
    0x0119: ("SET_RECEIVER_RC_AND_RADIO_PARAM", "设置接收机遥控器和电台参数", "RadioReceiverRFparameters"),
    0x0120: ("ASK_DMD_AUTO_TEST_STATUS", "询问自动测试状态", "UniversalCommand"),
    0x0121: ("RECEIVER_DMD_AUTO_TEST_STATUS", "回复接收机的自动测试状态", "ReceiverDmdAutoTestStatus"),
    0x0122: ("ELRS_DMD_AUTO_TEST_STATUS", "回复ELRS的自动测试状态", "ElrsDmdAutoTestStatus"),
    0x0200: ("LORA_RADIO_FACTORY_TEST", "LoRa电台工厂测试", "LoraRadioFactoryTest"),
    0x0201: ("ASK_RADIO_REGULATORY_DOMAIN", "查询电台的射频国家码", "UniversalCommand"),
    0x0202: ("SEND_RADIO_REGULATORY_DOMAIN", "发送电台的射频国家码", "RadioStationRegulatoryDomain"),
    0x0203: ("SET_RADIO_REGULATORY_DOMAIN", "设置电台的射频国家码", "RadioStationRegulatoryDomain"),
    0x0204: ("SEND_RADIO_R2_HEARTBEAT", "发送电台的心跳包", "radioStationR2Heart"),
    0x0205: ("SET_RADIO_BUUTON_PARAM", "设置电台按钮参数", "RadioButtonParam"),
    0x0207: ("SEND_RADIO_RF_PARAM_ECHO", "回显电台射频信息", "RadioRFParamsEcho"),
    0x0280: ("SEND_LASER_GIMBAL_HEARTBEAT", "发送云台的心跳包", "laserGimbalHeart"),
    0x0281: ("SEND_CUR_ATTITUDE", "发送飞控姿态给云台", "AttitudeInfo"),
    0x0282: ("SEND_CUR_GPS", "发送飞控gps信息给云台", "GpsInfo"),
    0x0283: ("SET_PAYLOAD_GIMBAL_ANGLE", "控制云台目标roll/pitch", "TargetAngleInfo"),
    0x0284: ("SET_PAYLOAD_LASER_CHANNEL", "控制激光", "SingleBytes"),
    0x0285: ("SET_PAYLOAD_NOTIFY_LED", "控制指示灯", "UniversalCommand"),
    0x0286: ("SET_GIMBAL_PARAM", "设置云台参数", "GimbalParam"),
    0x0287: ("SET_GIMBAL_CMD", "向云台发送命令", "UniversalCommand"),
    0x0288: ("SEND_GIMBAL_CHANNEL", "云台接收自己当前的通道值", "UniversalCommand"),
    0x0295: ("SEND_NOVA_LIGHT_HEARTBEAT", "发送高亮灯的心跳包", "novaLightHeart"),
    0x0296: ("SET_NOVA_LIGHT", "发送高亮灯亮灯命令", "PayloadHlt"),
    0x0422: ("READY_TO_BOOTLOADER", "让设备返回boot状态", "UniversalCommand"),
    0x0425: ("SEND_FIRMWARE_HEADER", "向设备发送固件信息", "FirmwareInfo"),
    0x0426: ("CONTROL_MESSAGE_IN_BOOT", "控制待升级设备的广播通信接口", "UniversalCommand"),
    0x0427: ("ERASE_FLASH_ADDRESS", "控制待升级设备擦除待写入区域", "UniversalCommand"),
    0x0428: ("SEND_FIRMWARE_PACKET", "发送固件的分包数据", "FirmwarePackage"),
    0x042B: ("SEND_FIRMWARE_UPDATE_DONE", "待升级设备对外发送升级成功", "UniversalCommand"),
    0x042C: ("READY_TO_JUMP_APP", "控制设备跳入新固件", "UniversalCommand"),
    0x0600: ("LPPC_CONTROL_MESSAGE", "LPPC控制信息", "LppcControlMessage"),
    0x0601: ("LPPC_BATTERY_MESSAGE", "LPPC的电池信息", "LppcBatteryMessage"),
    0x0602: ("ICT_ONBOARD_MESSAGE", "工装发送信息", "IctOnboardMessage"),
    0x0603: ("LPPC_REGISTER_MODIFY_MESSAGE", "LPPC寄存器修改信息", "LppcRegisterModifyMessage"),
    0x0700: ("DGCS_CONTROL_PPS_MESSAGE", "地面站控制PPS", "DgcsControlPPS"),
    0xFFFD: ("DISABLE_READ_PROTECT", "发送命令关闭读保护", "UniversalCommand"),
    0x10001: ("DRONE_HEADER", "解析剧本文件头", "DroneDramaHeader"),
    0x10002: ("DRONE_FRAME", "解析剧本", "DroneFrame"),
}


# =============================================================================
# Protobuf decoder
# =============================================================================

def read_varint(buf, pos):
    result = 0; shift = 0
    while pos < len(buf):
        b = buf[pos]; result |= (b & 0x7F) << shift; pos += 1
        if (b & 0x80) == 0: break
        shift += 7
    return result, pos


def decode_field(buf, pos, indent, schema):
    """Decode one protobuf field. Returns (consumed_bytes,). Prints output."""
    start = pos
    tag, pos = read_varint(buf, pos)
    fn = tag >> 3
    wt = tag & 0x07
    prefix = "  " * indent

    field_info = schema.get(fn) if schema else None
    if field_info:
        fname, ftype, is_repeated, enum_map = field_info
    else:
        fname, ftype, is_repeated, enum_map = None, None, False, None

    label = f"[{fn}]" if fname is None else f"[{fn}] {fname}"

    if wt == 0:  # Varint
        val, pos = read_varint(buf, pos)
        if enum_map:
            enum_name = enum_map.get(val, "")
            print(f"{prefix}{label} = {val} ({enum_name})" if enum_name else f"{prefix}{label} = {val}")
        elif ftype == V and val > 1000 and val < 10000000:
            # Could be frequency in Hz
            print(f"{prefix}{label} = {val} ({val/1e6:.3f} MHz)")
        else:
            print(f"{prefix}{label} = {val}")
        return pos - start

    elif wt == 1:  # 64-bit (fixed64 or double)
        raw = buf[pos:pos+8]
        u64 = struct.unpack("<Q", raw)[0]
        f64 = struct.unpack("<d", raw)[0]
        if ftype == F8:
            print(f"{prefix}{label} = {u64} (0x{u64:016X})")
        else:
            print(f"{prefix}{label} = {f64:.6f} (raw=0x{u64:016X})")
        pos += 8
        return pos - start

    elif wt == 2:  # Length-delimited
        length, pos = read_varint(buf, pos)
        sub = buf[pos:pos+length]
        pos += length

        if ftype and issubmessage(ftype):
            print(f"{prefix}{label} ({length}B):")
            if is_repeated and ftype:
                # Repeated packed sub-message
                decode_message(sub, indent + 1, ftype)
            else:
                decode_message(sub, indent + 1, ftype)
            return pos - start

        if is_repeated:
            # Packed repeated scalar
            items = unpack_packed(sub, ftype or V)
            if ftype == V and enum_map:
                named = [f"{v}({enum_map.get(v,'')})" if v in enum_map else str(v) for v in items]
                print(f"{prefix}{label} = [{', '.join(named)}]")
            elif ftype == V:
                if items and all(0 < v < 10000 for v in items):
                    print(f"{prefix}{label} = {items}")
                else:
                    print(f"{prefix}{label} = {items}")
            elif ftype == F4:
                parts = [f"{v} ({v/1e6:.3f} MHz)" if v > 100000 else str(v) for v in items]
                print(f"{prefix}{label} = {items}  [{', '.join(parts)}]")
            elif ftype == FL:
                parts = [f"{v:.3f}" for v in items]
                print(f"{prefix}{label} = [{', '.join(parts)}]")
            else:
                print(f"{prefix}{label} = {items}")
            return pos - start

        # String or bytes
        try:
            s = sub.decode('ascii')
            if all(c >= ' ' and c <= '~' for c in s):
                print(f"{prefix}{label} = \"{s}\"")
                return pos - start
        except:
            pass

        # Raw bytes — try to interpret as nested protobuf if we can
        if length <= 200:
            print(f"{prefix}{label} ({length}B): {sub.hex(' ')}")
        else:
            print(f"{prefix}{label} ({length}B): {sub[:32].hex(' ')}...")
        return pos - start

    elif wt == 5:  # 32-bit (fixed32 or float)
        raw = buf[pos:pos+4]
        u32 = struct.unpack("<I", raw)[0]
        f32 = struct.unpack("<f", raw)[0]
        if ftype == FL:
            print(f"{prefix}{label} = {f32:.3f}")
        elif ftype == F4:
            if 100000 < u32 < 10000000000:
                print(f"{prefix}{label} = {u32} ({u32/1e6:.3f} MHz)")
            else:
                print(f"{prefix}{label} = {u32} (0x{u32:08X})")
        else:
            # Show both
            if abs(f32) > 0.001 and abs(f32) < 1e9:
                print(f"{prefix}{label} = u32={u32}, float={f32:.3f}")
            else:
                print(f"{prefix}{label} = {u32} (0x{u32:08X})")
        pos += 4
        return pos - start

    else:
        print(f"{prefix}[{fn}] wire_type={wt} (unknown)")
        return pos - start


def unpack_packed(buf, etype):
    """Unpack a packed repeated field into a list of values."""
    items = []
    if etype == V:
        pos = 0
        while pos < len(buf):
            v, pos = read_varint(buf, pos)
            items.append(v)
    elif etype == F4:
        for k in range(0, len(buf), 4):
            items.append(struct.unpack("<I", buf[k:k+4])[0])
    elif etype == F8:
        for k in range(0, len(buf), 8):
            items.append(struct.unpack("<Q", buf[k:k+8])[0])
    elif etype == FL:
        for k in range(0, len(buf), 4):
            items.append(round(struct.unpack("<f", buf[k:k+4])[0], 6))
    else:
        items.append(f"<{len(buf)} bytes>")
    return items


def issubmessage(ftype):
    return ftype in MESSAGE_SCHEMAS


def decode_message(buf, indent, schema_name):
    """Decode a protobuf message with known schema."""
    schema = MESSAGE_SCHEMAS.get(schema_name, {})
    pos = 0
    idx = 1
    while pos < len(buf):
        prefix = "  " * indent
        if schema_name == "UniversalCommand" and schema.get(1):
            # For UniversalCommand, we already print compactly
            pass
        consumed = decode_field(buf, pos, indent, schema)
        if consumed == 0:
            print(f"{prefix}[WARN] stuck at offset {pos}, remaining: {buf[pos:].hex(' ')}")
            break
        pos += consumed
        idx += 1


# =============================================================================
# DAV Frame parser
# =============================================================================

def parse_dav_frame(data):
    """Parse and print a DAV protocol frame."""
    if len(data) < 24:
        print(f"ERROR: frame too short ({len(data)} bytes, minimum 24)")
        return

    # ---- Hex dump ----
    print("=" * 70)
    print("DAV Protocol Frame")
    print("=" * 70)
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_part = ' '.join(f"{b:02x}" for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f"  {i:04x}: {hex_part:<48s} {ascii_part}")

    # ---- Header ----
    sof = data[0]
    seq = data[1]
    len_version = struct.unpack("<H", data[2:4])[0]
    payload_len = len_version & 0x3FFF
    version = (len_version >> 14) & 0x03

    addr_ctrl = data[4:20]
    bits = int.from_bytes(addr_ctrl, 'little')
    msg_type = bits & 0x3
    ack_count = (bits >> 2) & 0x3F
    receive_type = (bits >> 8) & 0xFFFF
    sender_addr = (bits >> 24) & 0xFFFFFFFFFFFFF
    receiver_addr = (bits >> 76) & 0xFFFFFFFFFFFFF

    enc_byte = data[20]
    encrypt_type = enc_byte & 0x7
    padding_bytes = (enc_byte >> 3) & 0x1F
    crc8 = data[21]

    print(f"\n{'-' * 70}")
    print("Frame Header (22 bytes)")
    print(f"{'-' * 70}")
    print(f"  SOF            : 0x{sof:02X} {'(valid)' if sof == 0xA5 else '(INVALID!)'}")
    print(f"  seq            : {seq}")
    print(f"  len+version    : 0x{len_version:04X} → payload_len={payload_len}, version={version}")
    addr_ctrl_hex = addr_ctrl.hex(' ')
    print(f"  addr_ctrl      : {addr_ctrl_hex[:23]}...")
    print(f"  message_type   : {msg_type} ({'CMD' if msg_type == 0 else 'ACK'})")
    print(f"  ack_count      : {ack_count}")
    print(f"  receive_type   : 0x{receive_type:04X}")
    print(f"  sender_addr    : 0x{sender_addr:013X}")
    print(f"  receiver_addr  : 0x{receiver_addr:013X}")
    print(f"  encrypt_type   : {encrypt_type}")
    print(f"  padding_bytes  : {padding_bytes}")
    print(f"  crc8           : 0x{crc8:02X}")

    # ---- Payload ----
    payload_start = 22
    payload = data[payload_start:payload_start + payload_len]
    cmd = struct.unpack("<H", payload[0:2])[0]
    proto_data = payload[2:]

    tail_start = payload_start + payload_len
    crc16 = struct.unpack("<H", data[tail_start:tail_start+2])[0]

    cmd_info = CMD_MAP.get(cmd, ("UNKNOWN", "", ""))
    cmd_name, cmd_desc, msg_type_name = cmd_info

    print(f"\n{'-' * 70}")
    print("Payload")
    print(f"{'-' * 70}")
    print(f"  cmd            : 0x{cmd:04X} → {cmd_name}")
    print(f"  description    : {cmd_desc}")
    print(f"  message_type   : {msg_type_name}")
    print(f"  protobuf_data  : {len(proto_data)} bytes")
    if len(proto_data) > 0:
        print(f"    hex: {proto_data.hex(' ')}")
    print(f"  CRC16          : 0x{crc16:04X}")

    # ---- Protobuf decode ----
    if len(proto_data) == 0:
        print(f"\n  (no protobuf payload)")
        return

    print(f"\n{'-' * 70}")
    print(f"Protobuf Decode: {msg_type_name}")
    print(f"{'-' * 70}")

    if msg_type_name not in MESSAGE_SCHEMAS:
        print(f"  (schema not available — generic parse)")
        decode_message(proto_data, 1, None)
    else:
        decode_message(proto_data, 1, msg_type_name)

    # ---- Summary ----
    print(f"\n{'=' * 70}")
    print(f"Summary: seq={seq} {cmd_name} (0x{cmd:04X}) -- {cmd_desc}")
    print(f"{'=' * 70}")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="DAV Protocol Frame Parser — decode DAV hex frames",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python dav_frame_parser.py a5fa0400...
  echo "a5fa0400..." | python dav_frame_parser.py
  python dav_frame_parser.py --file frames.txt
        """)
    parser.add_argument("hex", nargs="?", help="Hex string to parse")
    parser.add_argument("--file", "-f", help="File containing hex strings (one per line)")
    args = parser.parse_args()

    hex_strings = []

    if args.file:
        with open(args.file) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    hex_strings.append(line)
    elif args.hex:
        hex_strings.append(args.hex)
    else:
        # Read from stdin
        if not sys.stdin.isatty():
            for line in sys.stdin:
                line = line.strip()
                if line:
                    hex_strings.append(line)
        else:
            parser.print_help()
            return

    for i, hs in enumerate(hex_strings):
        # Clean the hex string
        hs = hs.replace(" ", "").replace("\n", "").replace("\r", "")
        if not all(c in "0123456789abcdefABCDEF" for c in hs):
            print(f"ERROR: invalid hex string: {hs[:50]}...")
            continue

        try:
            data = bytes.fromhex(hs)
        except ValueError as e:
            print(f"ERROR: {e}")
            continue

        if i > 0:
            print("\n")
        parse_dav_frame(data)


if __name__ == "__main__":
    main()
