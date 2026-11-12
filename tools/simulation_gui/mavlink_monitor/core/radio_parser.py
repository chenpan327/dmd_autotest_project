"""Radio DAV Protocol Parser — R2 电台 DAV 链路层帧解析器

基于 DGCS v4 DAV 协议（DavLink2）实现帧解码，将电台消息转换为
MessageRecord 供 GUI 表格展示。

协议参考：fake_radio.py / Python假电台模拟器技术方案.md §3
"""

from __future__ import annotations

import json
import re
import struct
import time
import xml.etree.ElementTree as ET
from typing import Optional

from .model import MessageRecord


# ═══════════════════════════════════════════════════════════════════
# CRC8 查表 — 多项式 x^8 + x^5 + x^4 + 1 (0x31)
# 来源: fake_radio.py:53-70 / CRC8.cs:7-23
# ═══════════════════════════════════════════════════════════════════

_CRC8_TABLE = (
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


def _crc8(data: bytes, offset: int = 0, length: int = None) -> int:
    """CRC8 帧头校验。初始值 0xFF，覆盖 byte 0~20（共 21 字节）。"""
    if length is None:
        length = len(data) - offset
    crc = 0xFF
    for i in range(offset, offset + length):
        crc = _CRC8_TABLE[crc ^ data[i]]
    return crc & 0xFF


# ═══════════════════════════════════════════════════════════════════
# CRC16 查表 — 多项式 x^16 + x^12 + x^5 + 1 (0x8005)
# 来源: fake_radio.py:88-111 / CRC16.cs:7-28
# ═══════════════════════════════════════════════════════════════════

_CRC16_TABLE = (
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


def _crc16(data: bytes, offset: int = 0, length: int = None) -> int:
    """CRC16 整帧校验。初始值 0xFFFF，覆盖 byte 0~End-3。"""
    if length is None:
        length = len(data) - offset
    crc = 0xFFFF
    for i in range(offset, offset + length):
        crc = (crc >> 8) ^ _CRC16_TABLE[(crc ^ data[i]) & 0x00FF]
    return crc & 0xFFFF


# ═══════════════════════════════════════════════════════════════════
# plist 风格 XML 解析（对应 src/Protocol/radio/MessageDefineUAV.xml）
# ═══════════════════════════════════════════════════════════════════

def _plist_get(el, key_string: str):
    """返回 plist 元素中 <key>key_string</key> 紧随其后的元素。"""
    children = list(el)
    for i, child in enumerate(children):
        if child.tag == "key" and child.text == key_string:
            if i + 1 < len(children):
                return children[i + 1]
    return None


def _plist_keys(el):
    """按顺序返回元素下所有 <key> 文本。"""
    return [child.text for child in el if child.tag == "key"]


_TX_MESSAGE_EXACT = {"ENROLL_REQUEST", "PPS_HEARTBEAT"}


def _infer_direction(name: str) -> str:
    """根据消息名推断方向（电台视角：Tx=电台发出，Rx=电台收到）。

    - ``SEND_*`` / ``ENROLL_REQUEST`` / ``PPS_HEARTBEAT`` / 状态上报类 → Tx
    - ``ASK_*`` / ``SET_*`` / ``GET_*`` / RTCM 等 → Rx
    """
    if name in _TX_MESSAGE_EXACT:
        return "Tx"
    if name.startswith("SEND_"):
        return "Tx"
    if name.startswith(("RECEIVER_DMD", "ELRS_DMD", "LPPC_BATTERY")):
        return "Tx"
    return "Rx"


# ═══════════════════════════════════════════════════════════════════
# RadioDavParser
# ═══════════════════════════════════════════════════════════════════

class RadioDavParser:
    """R2 电台 DAV 链路层帧解析器。

    将 DAV 帧（UDP 14555 端口）解析为 MessageRecord，
    以 Radio_XXX 命名显示在 Msg_Name 列。

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

    def __init__(self, config_path: str = None):
        self._msg_config: dict[int, dict] = {}  # msg_id → {message_name, direction, description}
        if config_path:
            self.load_config(config_path)

    # ─────────────────────────────────────────────────────────────
    # 配置加载
    # ─────────────────────────────────────────────────────────────

    def load_config(self, config_path: str) -> bool:
        """加载电台消息配置。

        ``.proto`` 路径 → 解析 ``DavMessage.proto`` 的 MessageID 枚举（权威协议定义）；
        ``.xml`` 路径 → 解析 ``MessageDefineUAV.xml``；
        其他路径 → 解析 JSON 格式（旧格式兼容）。
        """
        if config_path.lower().endswith(".proto"):
            return self.load_config_from_proto(config_path)
        if config_path.lower().endswith(".xml"):
            return self.load_config_from_xml(config_path)
        return self._load_config_json(config_path)

    def _load_config_json(self, config_path: str) -> bool:
        """从 JSON 文件加载消息配置（兼容旧格式）。"""
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._msg_config.clear()
            for msg in data.get("messages", []):
                self._msg_config[msg["msg_id"]] = {
                    "message_name": msg["message_name"],
                    "direction": msg.get("direction", "Rx"),
                    "description": msg.get("description", ""),
                }
            return True
        except Exception as e:
            print(f"[RadioParser] 加载配置失败: {e}")
            return False

    def load_config_from_xml(self, xml_path: str) -> bool:
        """从 ``MessageDefineUAV.xml``（plist 格式）加载全部消息定义。

        XML 位于 ``src/Protocol/radio/MessageDefineUAV.xml``，是 R2 电台 DAV
        协议的权威消息表（69 条）。每条提取 msg_id / 名称 / 描述，
        方向按消息名启发式推断。
        """
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except Exception as e:
            print(f"[RadioParser] XML 解析失败 ({xml_path}): {e}")
            return False

        messages_data = _plist_get(root, "Messages")
        if messages_data is None:
            print(f"[RadioParser] XML 中缺少 Messages 定义: {xml_path}")
            return False

        self._msg_config.clear()
        for key in _plist_keys(messages_data):
            msg_el = _plist_get(messages_data, key)
            if msg_el is None:
                continue
            fields = {}
            for mk in _plist_keys(msg_el):
                v_el = _plist_get(msg_el, mk)
                if v_el is not None and v_el.text is not None:
                    fields[mk] = v_el.text
            try:
                cmd_id = int(fields.get("cmdID", "0"), 0)
            except (ValueError, TypeError):
                continue
            self._msg_config[cmd_id] = {
                "message_name": key,
                "direction": _infer_direction(key),
                "description": fields.get("description", ""),
            }
        return len(self._msg_config) > 0

    def load_config_from_proto(self, proto_path: str) -> bool:
        """从 ``DavMessage.proto`` 的 ``MessageID`` 枚举加载全部消息定义。

        proto 位于 ``simulation_gui/resources/DavMessage.proto``，是 DAV 消息
        的权威协议定义。仅解析枚举成员（消息名 → cmdID），方向按消息名启发式推断。
        """
        try:
            with open(proto_path, "r", encoding="utf-8") as f:
                src = f.read()
        except OSError as e:
            print(f"[RadioParser] proto 读取失败 ({proto_path}): {e}")
            return False

        # 定位 enum MessageID { ... } 块
        m = re.search(r"\benum\s+MessageID\s*\{", src)
        if not m:
            print(f"[RadioParser] proto 中缺少 enum MessageID: {proto_path}")
            return False
        depth = 1
        i = m.end()
        while i < len(src) and depth > 0:
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
            i += 1
        if depth != 0:
            return False
        body = src[m.end():i - 1]

        self._msg_config.clear()
        for name, val in re.findall(r"(\w+)\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*;", body):
            try:
                cmd_id = int(val, 0)
            except (ValueError, TypeError):
                continue
            self._msg_config[cmd_id] = {
                "message_name": name,
                "direction": _infer_direction(name),
                "description": "",
            }
        return len(self._msg_config) > 0

    @property
    def is_configured(self) -> bool:
        return len(self._msg_config) > 0

    # ─────────────────────────────────────────────────────────────
    # 帧解码
    # ─────────────────────────────────────────────────────────────

    def decode_frame(self, data: bytes) -> dict | None:
        """解码 DAV 帧，返回帧信息字典或 None（校验失败）。

        Returns:
            dict with keys: msg_type, ack_count, msg_id, payload, report,
                            src_addr, dst_addr, tx_seq, crc8_ok, crc16_ok
        """
        if len(data) < self.HEADER_LEN + 2:
            return None
        if data[0] != self.HEADER_MARKER:
            return None

        # 解析 dataLen: byte[2] + ((byte[3] & 0x3F) << 8)
        data_len = data[2] + ((data[3] & 0x3F) << 8)

        if len(data) < self.HEADER_LEN + data_len + 2:
            return None

        # CRC8 校验 (覆盖 byte 0~20)
        crc8_ok = data[21] == _crc8(data, 0, 21)

        # CRC16 校验 (覆盖 byte 0~End-3)
        calc_crc = _crc16(data, 0, self.HEADER_LEN + data_len)
        pkt_crc = struct.unpack_from('<H', data, self.HEADER_LEN + data_len)[0]
        crc16_ok = calc_crc == pkt_crc

        # 解析头部字段
        tx_seq = data[1]
        version = (data[3] >> 6) & 0x03
        ack_count = (data[4] >> 2) & 0x3F
        msg_type = data[4] & 0x03

        # 源地址 (52-bit): byte 7-12 + byte 13 低 nibble
        src_addr = (
            data[7] |
            (data[8] << 8) |
            (data[9] << 16) |
            (data[10] << 24) |
            (data[11] << 32) |
            (data[12] << 40) |
            ((data[13] & 0x0F) << 48)
        )

        # 目标地址 (52-bit): byte 13 高 nibble + byte 14-19
        dst_addr = (
            ((data[13] >> 4) & 0x0F) |
            (data[14] << 4) |
            (data[15] << 12) |
            (data[16] << 20) |
            (data[17] << 28) |
            (data[18] << 36) |
            (data[19] << 44)
        )

        result = {
            'msg_type': msg_type,
            'ack_count': ack_count,
            'tx_seq': tx_seq,
            'version': version,
            'src_addr': src_addr,
            'dst_addr': dst_addr,
            'data_len': data_len,
            'crc8_ok': crc8_ok,
            'crc16_ok': crc16_ok,
        }

        if msg_type == self.MSG_TYPE_MSG:
            result['msg_id'] = struct.unpack_from('<H', data, self.HEADER_LEN)[0]
            payload_start = self.HEADER_LEN + 2
            payload_len = data_len - 2
            result['payload'] = data[payload_start:payload_start + payload_len] if payload_len > 0 else b''
        else:  # Ack
            result['report'] = struct.unpack_from('<I', data, self.HEADER_LEN)[0]

        return result

    # ─────────────────────────────────────────────────────────────
    # MessageRecord 构建
    # ─────────────────────────────────────────────────────────────

    def to_message_record(
        self, data: bytes, src_ip: str, src_port: int,
        dst_ip: str, dst_port: int, node_id: str = "radio",
    ) -> MessageRecord | None:
        """将原始 DAV 帧数据解析为 MessageRecord。

        Args:
            data: 原始 UDP payload（DAV 帧）
            src_ip: 源 IP
            src_port: 源端口
            dst_ip: 目标 IP
            dst_port: 目标端口
            node_id: 来源节点标识

        Returns:
            MessageRecord 或 None（非 DAV 帧/校验失败）。
        """
        frame = self.decode_frame(data)
        if frame is None:
            return None

        msg_id = frame.get('msg_id', 0)
        msg_type = frame['msg_type']
        crc_ok = frame['crc8_ok'] and frame['crc16_ok']

        # ACK 帧（msg_type=1）：固定命名为 Radio_ACK，方向 Tx（电台回复地面站）。
        # 不能查 _msg_config——ACK 帧无 msg_id（msg_id=0），proto 配置会把 0 映射到
        # GET_FIRMWARE_VERSION，导致 ACK 显示错误。
        if msg_type == self.MSG_TYPE_ACK:
            msg_name = f"Radio_ACK(ack={frame['ack_count']})"
            direction = "Tx"
        else:
            cfg = self._msg_config.get(msg_id, {})
            msg_name = cfg.get('message_name', f"Radio_MSG_0x{msg_id:04X}")
            # 方向以 DAV 源地址为准（电台视角）：源=电台地址 → Tx（电台发出）；
            # 源=地面站 → Rx。修正静态配置无法区分上下行共用 msg_id 的场景
            # （如 RADIO_SEND_RTCM 上行差分与下行下发共用 0x0100）
            direction = ("Tx" if self.is_radio_addr(frame.get('src_addr', 0))
                         else "Rx")

        # Payload 处理
        payload_bytes = frame.get('payload', b'')

        # RadioSendRtcm(0x0100)：附加 RTCM 摘要（帧消息号），便于监控面板判读
        if msg_id == 0x0100 and msg_type != self.MSG_TYPE_ACK:
            summary = self._rtcm_summary(payload_bytes)
            if summary:
                msg_name = f"{msg_name}{summary}"

        # CRC 显示
        crc_expected = 0
        crc_actual = 0
        if not crc_ok:
            crc_actual = 1  # 标记 CRC 失败

        record = MessageRecord(
            direction=direction,
            src_ip=src_ip,
            src_port=src_port,
            dst_ip=dst_ip,
            dst_port=dst_port,
            format_type="radio_dav",
            relay_ip="",
            msg_id=msg_id,
            msg_name=msg_name,
            sys_id=(frame['src_addr'] >> 48) & 0xFF if frame['src_addr'] else 0,
            comp_id=frame['tx_seq'],
            seq_mav=frame['tx_seq'],
            payload_len=len(payload_bytes),
            start_byte=self.HEADER_MARKER,
            payload_bytes=payload_bytes,
            # payload_hex/payload_display 延迟计算 — 首次访问时从 payload_bytes 生成
            crc_ok=crc_ok,
            crc_expected=crc_expected,
            crc_actual=crc_actual,
            node_id=node_id,
            source_type="radio",
            version="radio_dav",
        )

        # Ack 帧（msg_type=1）：report 直接解析（不经过 protobuf），标记到 record
        if msg_type == self.MSG_TYPE_ACK:
            record.dav_report = frame['report']

        return record

        return record

    @staticmethod
    def _truncate_hex(data: bytes, max_display: int = 26) -> str:
        """截断 hex 显示字符串。"""
        if not data:
            return "(empty)"
        h = data.hex()
        if len(h) <= max_display:
            return h
        return h[:max_display] + "…"

    @staticmethod
    def _rtcm_summary(payload: bytes) -> str | None:
        """对 RadioSendRtcm(0x0100) payload 提取 RTCM 摘要（帧消息号列表）。

        payload = SingleBytes 包装（0x0A + varint + RTCM3 字节流，技术方案 §11.2.2）。
        消息号提取对齐地面站 RTCM32.cs: msgId=(src[3]<<4)+(src[4]>>4)。
        无有效 RTCM 帧时返回 None。
        """
        if len(payload) < 2 or payload[0] != 0x0A:
            return None
        pos = 1
        shift = 0
        n = 0
        while pos < len(payload):
            b = payload[pos]
            n |= (b & 0x7F) << shift
            shift += 7
            pos += 1
            if not (b & 0x80):
                break
        rtcm = payload[pos:pos + n]
        nums = []
        p = 0
        while p + 5 <= len(rtcm) and rtcm[p] == 0xD3:
            length = rtcm[p + 2] + ((rtcm[p + 1] & 0x03) << 8)
            total = length + 6
            if p + total > len(rtcm):
                break
            nums.append((rtcm[p + 3] << 4) + (rtcm[p + 4] >> 4))
            p += total
        if not nums:
            return None
        return f"[RTCM {','.join(str(x) for x in nums)}]"

    # ─────────────────────────────────────────────────────────────
    # 地址辅助
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def format_dav_addr(addr: int) -> str:
        """格式化 52-bit DAV 地址为十六进制字符串。"""
        return f"0x{addr:013X}"

    @staticmethod
    def is_radio_addr(addr: int) -> bool:
        """判断地址是否在电台范围内 (0xFFFFFFFFFF100 ~ 0xFFFFFFFFFF1FF)。"""
        return 0xFFFFFFFFFF100 <= addr <= 0xFFFFFFFFFF1FF

    @staticmethod
    def is_ground_addr(addr: int) -> bool:
        """判断是否为地面站地址 (0xFFFFFFFFFFF0)。"""
        return addr == 0xFFFFFFFFFFF0

    # ─────────────────────────────────────────────────────────────
    # Protobuf Wire-Format 字段解析（用于详情面板）
    # ─────────────────────────────────────────────────────────────

    # 已知字段名映射: msg_id → {field_number: field_name}
    _KNOWN_FIELDS: dict[int, dict[int, str]] = {
        # UniversalCommand (0x0000 GET_FIRMWARE_VERSION，询问 boot/app 版本)
        # command: 1=DAV_COMMAND_ACK_BOOTLOADER_VERSION, 2=DAV_COMMAND_ACK_APP_VERSION
        0x0000: {
            1: "command",
        },
        # EnrollRequest (0x000C)
        0x000C: {
            1: "device_type", 2: "product_name", 3: "serial_number", 4: "check",
        },
        # EnrollReply (0x000D)
        0x000D: {
            1: "accept_status", 2: "heartbeat_interval_ms",
        },
        # RadioSendRtcm (0x0100) — SingleBytes{msg=RTCM3 字节流}（技术方案 §11.2.2，
        # 上行差分数据/下行切剧本·灯光秀下发共用此 msg_id）
        0x0100: {
            1: "msg",
        },
        # RadioStationR2Heart (0x0204)
        0x0204: {
            1: "sub_device_type", 2: "firmware_running_status",
            3: "firmware_version_alias", 4: "firmware_version",
            5: "protobuf_version", 6: "local_ms_time",
            7: "radio_station_r2",  # nested message
        },
        # RadioStationR2HeartBeatExtend (nested in field 7)
        # Fields: 1=device_id, 2=error_report, 3=ethernet_ip, 4=battery_pct,
        #         5=poe_voltage_mv, 6=charge_temp, 7=gps_utc_time,
        #         8=radioGroupPosition, 9=radio_rf_param, 10=button_param,
        #         11=encrypt_type, 12=translate_data_left_bytes
        # RadioStationRegulatoryDomain (0x0203)
        0x0203: {
            1: "set_device_id", 2: "set_rf_param",
        },
        # RadioEncryptKey (0x0102)
        0x0102: {
            1: "radio_key", 2: "rc_key",
        },
        # UniversalCommand (0x0103 ASK_RADIO_ENCRYPT_KEY / 0x0201 ASK_RADIO_REGULATORY_DOMAIN)
        0x0103: {
            1: "command",
        },
        0x0201: {
            1: "command",
        },
        # RadioEncryptKey (0x0104 SEND_RADIO_ENCRYPT_KEY)
        0x0104: {
            1: "radio_key", 2: "rc_key",
        },
        # RadioButtonParam (0x0205)
        0x0205: {
            1: "long_click_time", 2: "long_click_button_mode",
            3: "short_click_button_mode",
        },
        # SingleBytes / RadioSendRtcm (0x0100) — 见前部 _KNOWN_FIELDS 定义（msg）
        # RadioRTcmLinkInfo (0x0101)
        0x0101: {
            1: "radio_850m_chan", 2: "gps_utc_time",
        },
        # RadioReceiverMode (0x0111)
        0x0111: {
            1: "radio_850m_mode", 2: "radio_2g4_mode",
            3: "radio_850m_binding_code", 4: "radio_2g4_binding_code",
        },
        # RadioReceiverRFparameters (0x0118 SEND / 0x0119 SET)
        0x0118: {
            1: "rc_binding_code", 2: "radio_binding_code",
            3: "receiver_radio_param", 4: "radio_id_enable_bit",
        },
        0x0119: {
            1: "rc_binding_code", 2: "radio_binding_code",
            3: "receiver_radio_param", 4: "radio_id_enable_bit",
        },
        # RadioStationRegulatoryDomain (0x0202 SEND / 0x0203 SET)
        0x0202: {
            1: "set_device_id", 2: "set_rf_param",
        },
        # RadioRFParamsEcho (0x0207)
        0x0207: {
            1: "rf_param_echo",
        },
    }

    # 嵌套消息的字段名映射（用于 radio_station_r2 等）
    _NESTED_FIELDS: dict[str, dict[int, str]] = {
        "radio_station_r2": {
            1: "device_id", 2: "error_report", 3: "ethernet_ip",
            4: "battery_percentage", 5: "poe_voltage_mv",
            6: "charge_temperature", 7: "gps_utc_time",
            8: "radioGroupPosition", 9: "radio_rf_param",
            10: "button_param", 11: "encrypt_type",
            12: "translate_data_left_bytes",
        },
        "radio_rf_param": {
            1: "rf_work_mode", 2: "rf_tx_power_dbm", 3: "rf_temperature",
            4: "rf_max_fre", 5: "rf_min_fre",
        },
        "button_param": {
            1: "long_click_time", 2: "long_click_button_mode",
            3: "short_click_button_mode",
        },
        "radio_key": {
            1: "encrypt_type", 2: "encrypt_key", 3: "encrypt_iv",
        },
        "rc_key": {
            1: "encrypt_type", 2: "encrypt_key", 3: "encrypt_iv",
        },
        "set_rf_param": {
            1: "rf_work_mode", 2: "rf_tx_power_dbm", 3: "rf_temperature",
            4: "rf_max_fre", 5: "rf_min_fre",
        },
        "receiver_radio_param": {
            1: "rf_work_mode", 2: "rf_tx_power_dbm", 3: "rf_temperature",
            4: "rf_max_fre", 5: "rf_min_fre",
        },
        "radioGroupPosition": {
            1: "device_id", 2: "latitude", 3: "longitude", 4: "altitude",
        },
    }

    # wire_type 名称
    _WIRE_TYPE_NAMES: dict[int, str] = {
        0: "varint",
        1: "fixed64",
        2: "length-delimited",
        3: "start_group",
        4: "end_group",
        5: "fixed32",
    }

    def parse_protobuf_fields(
        self, msg_id: int, payload: bytes,
    ) -> list:
        """对 DAV 消息的 protobuf payload 进行 wire-format 字段解析。

        不依赖 .proto 编译，直接从 wire format 提取 tag/value，
        结合已知字段名映射，生成 FieldDetail 列表供详情面板展示。

        Args:
            msg_id: DAV MessageID
            payload: protobuf 序列化的 payload 字节

        Returns:
            FieldDetail 列表
        """
        from .model import FieldDetail

        fields: list[FieldDetail] = []
        if not payload:
            return fields

        known = self._KNOWN_FIELDS.get(msg_id, {})
        pos = 0
        field_index = 0

        while pos < len(payload):
            field_index += 1
            tag, pos = self._read_varint(payload, pos)
            if tag is None:
                break
            field_number = tag >> 3
            wire_type = tag & 0x7

            wt_name = self._WIRE_TYPE_NAMES.get(wire_type, f"wire_{wire_type}")

            # 获取已知字段名
            base_name = known.get(field_number, f"field_{field_number}")
            type_name = f"protobuf ({wt_name})"

            if wire_type == 0:  # varint
                value, pos = self._read_varint(payload, pos)
                if value is None:
                    break
                raw_hex = f"0x{value:X}" if value <= 0xFFFFFFFF else f"0x{value:X} (64bit)"
                value_display = str(value)
                fields.append(FieldDetail(
                    name=base_name, value_raw=value,
                    value_display=value_display, raw_hex=raw_hex,
                    type_name=type_name, is_array=False,
                ))

            elif wire_type == 2:  # length-delimited
                length, pos = self._read_varint(payload, pos)
                if length is None:
                    break
                if pos + length > len(payload):
                    break
                sub_data = payload[pos:pos + length]
                pos += length

                # 尝试解析嵌套消息或显示为 bytes/string
                nested_fields = self._try_parse_nested(base_name, sub_data)
                if nested_fields:
                    # 嵌套消息：展开子字段（缩进显示）
                    for nf in nested_fields:
                        nf.name = f"  {base_name}.{nf.name}"
                        fields.append(nf)
                else:
                    # 尝试 UTF-8 解码
                    try:
                        text = sub_data.decode("utf-8")
                        if text.isprintable() and len(text) > 0:
                            value_display = f'"{text}"'
                            is_str = True
                        else:
                            raise ValueError
                    except (ValueError, UnicodeDecodeError):
                        value_display = sub_data.hex()
                        is_str = False

                    raw_hex = sub_data.hex()
                    fields.append(FieldDetail(
                        name=base_name,
                        value_raw=sub_data,
                        value_display=value_display,
                        raw_hex=raw_hex,
                        type_name="string" if is_str else "bytes",
                        is_array=not is_str,
                    ))

            elif wire_type == 5:  # fixed32 (4 bytes LE)
                if pos + 4 > len(payload):
                    break
                value = struct.unpack_from('<I', payload, pos)[0]
                pos += 4
                fields.append(FieldDetail(
                    name=base_name, value_raw=value,
                    value_display=str(value), raw_hex=f"0x{value:08X}",
                    type_name=type_name, is_array=False,
                ))

            elif wire_type == 1:  # fixed64 (8 bytes LE)
                if pos + 8 > len(payload):
                    break
                value = struct.unpack_from('<Q', payload, pos)[0]
                pos += 8
                fields.append(FieldDetail(
                    name=base_name, value_raw=value,
                    value_display=str(value), raw_hex=f"0x{value:016X}",
                    type_name=type_name, is_array=False,
                ))

            else:
                # 未知 wire_type，跳过
                break

        return fields

    def parse_ack_report(self, report: int) -> list:
        """直接解析 DAV Ack 帧的 report 字段（msg_type=1，不走 protobuf）。

        Ack 帧 payload 是 4 字节 UInt32 report（0 = DAV_NO_ERROR，非 0 = 失败码），
        直接构造 FieldDetail 供详情面板展示。
        """
        from .model import FieldDetail

        return [FieldDetail(
            name="report",
            value_raw=report,
            value_display=str(report),
            raw_hex=f"0x{report:08X}",
            type_name="uint32",
            is_array=False,
        )]

    def _try_parse_nested(self, parent_name: str, data: bytes) -> list | None:
        """尝试将 length-delimited 数据解析为嵌套 protobuf 消息。

        仅对已知的嵌套消息类型（_NESTED_FIELDS 中有定义）进行解析。
        返回 FieldDetail 列表或 None（不可解析为嵌套消息）。
        """
        from .model import FieldDetail

        nested_known = self._NESTED_FIELDS.get(parent_name, {})
        if not nested_known:
            return None

        fields: list[FieldDetail] = []
        pos = 0
        while pos < len(data):
            tag, pos = self._read_varint(data, pos)
            if tag is None:
                break
            field_number = tag >> 3
            wire_type = tag & 0x7

            name = nested_known.get(field_number, f"f{field_number}")
            wt_name = self._WIRE_TYPE_NAMES.get(wire_type, f"wire_{wire_type}")

            if wire_type == 0:  # varint
                value, pos = self._read_varint(data, pos)
                if value is None:
                    break
                fields.append(FieldDetail(
                    name=name, value_raw=value,
                    value_display=str(value), raw_hex=f"0x{value:X}",
                    type_name=f"varint", is_array=False,
                ))

            elif wire_type == 2:  # length-delimited
                length, pos = self._read_varint(data, pos)
                if length is None:
                    break
                if pos + length > len(data):
                    break
                sub = data[pos:pos + length]
                pos += length

                # 递归解析已知嵌套类型
                sub_nested = self._NESTED_FIELDS.get(name)
                if sub_nested:
                    sub_fields = self._try_parse_nested(name, sub)
                    if sub_fields:
                        for sf in sub_fields:
                            sf.name = f"  {name}.{sf.name}"
                            fields.append(sf)
                        continue

                # packed repeated varint?
                if wire_type == 2 and name in nested_known.values():
                    packed = self._try_parse_packed_varint(sub)
                    if packed:
                        fields.append(FieldDetail(
                            name=name, value_raw=packed,
                            value_display=str(packed), raw_hex=sub.hex(),
                            type_name="packed varint[]", is_array=True,
                        ))
                        continue

                # 显示为 bytes
                try:
                    text = sub.decode("utf-8")
                    if text.isprintable() and len(text) > 0:
                        value_display = f'"{text}"'
                        is_array = False
                        type_name = "string"
                    else:
                        raise ValueError
                except (ValueError, UnicodeDecodeError):
                    value_display = sub.hex()
                    is_array = True
                    type_name = "bytes"

                fields.append(FieldDetail(
                    name=name, value_raw=sub,
                    value_display=value_display, raw_hex=sub.hex(),
                    type_name=type_name, is_array=is_array,
                ))

            elif wire_type == 5:  # fixed32
                if pos + 4 > len(data):
                    break
                value = struct.unpack_from('<I', data, pos)[0]
                pos += 4
                fields.append(FieldDetail(
                    name=name, value_raw=value,
                    value_display=str(value), raw_hex=f"0x{value:08X}",
                    type_name="fixed32", is_array=False,
                ))

            elif wire_type == 1:  # fixed64
                if pos + 8 > len(data):
                    break
                value = struct.unpack_from('<Q', data, pos)[0]
                pos += 8
                fields.append(FieldDetail(
                    name=name, value_raw=value,
                    value_display=str(value), raw_hex=f"0x{value:016X}",
                    type_name="fixed64", is_array=False,
                ))

            else:
                break

        return fields if fields else None

    @staticmethod
    def _try_parse_packed_varint(data: bytes) -> list[int] | None:
        """尝试将数据解析为 packed repeated varint。"""
        values: list[int] = []
        pos = 0
        while pos < len(data):
            val, pos = RadioDavParser._read_varint(data, pos)
            if val is None:
                return None
            values.append(val)
        return values if values else None

    @staticmethod
    def _read_varint(data: bytes, pos: int) -> tuple:
        """读取一个 protobuf varint，返回 (value, new_pos) 或 (None, pos)。

        protobuf varint 最多 10 字节（70 位），用字节计数器而非移位
        计数器限制循环，避免拒绝合法的超长 varint。
        """
        value = 0
        shift = 0
        for _ in range(10):  # 最多 10 字节（protobuf 规范上限）
            if pos >= len(data):
                return None, pos
            b = data[pos]
            pos += 1
            value |= (b & 0x7F) << shift
            if not (b & 0x80):
                return value, pos
            shift += 7
        return None, pos
