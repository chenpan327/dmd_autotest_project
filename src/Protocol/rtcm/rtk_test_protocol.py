"""
RTK Test Protocol — unified RTCM3 message parser, builder, and serial sender.

Parse:
    from rtk_test_protocol import parse_rtcm_frame, parse_rtcm_file
    msg = parse_rtcm_frame(raw_bytes)
    msgs = parse_rtcm_file("38400_rtk.json")

Build:
    from rtk_test_protocol import MsmBuilder, Message1006
    raw = MsmBuilder.gps(1074, num_sats=8, epoch_ms='now').to_bytes()
    raw = Message1006.build(station_id=0, x=-2396842.83, y=-5976984.07, z=11628934.22).to_bytes()

Send:
    from rtk_test_protocol import RtkSender
    with RtkSender(log_callback=print) as s:
        s.connect("COM4", 115200)
        s.load_templates_from_json("38400_rtk.json")
        s.start_auto_send(1.0)
        time.sleep(10)

CLI:
    python rtk_test_protocol.py send COM4 --mode template --json 38400_rtk.json -d 10
    python rtk_test_protocol.py parse 38400_rtk.json
    python rtk_test_protocol.py build -t 1074 -n 8
    python rtk_test_protocol.py check d30015...
    python rtk_test_protocol.py ports
"""

import json
import struct
import threading
import time
from datetime import datetime

# ============================================================================
# Constants
# ============================================================================

PREAMBLE = 0xD3

RTCM_TYPE_NAMES = {
    1006: "Station coordinates XYZ + antenna height",
    1033: "Receiver and antenna descriptor",
    1074: "GPS MSM4 (full PR + CP + CNR)",
    1075: "GPS MSM5", 1076: "GPS MSM6", 1077: "GPS MSM7",
    1084: "GLONASS MSM4", 1085: "GLONASS MSM5", 1086: "GLONASS MSM6", 1087: "GLONASS MSM7",
    1094: "Galileo MSM4", 1095: "Galileo MSM5", 1096: "Galileo MSM6", 1097: "Galileo MSM7",
    1104: "QZSS MSM4", 1114: "QZSS MSM5",
    1124: "BeiDou MSM4", 1125: "BeiDou MSM5", 1126: "BeiDou MSM6", 1127: "BeiDou MSM7",
    1230: "GLONASS code-phase biases",
    4006: "Custom: real-time light (single color)",
    4007: "Custom: real-time light (RGB)",
}

GNSS_NAMES = {0: "GPS", 1: "GLONASS", 2: "Galileo", 4: "QZSS", 5: "BeiDou"}
RTCM_MSM_TYPES = {1074, 1084, 1094, 1114, 1124}

# ============================================================================
# CRC24Q
# ============================================================================

CRC24Q_TABLE = [
    0x000000, 0x864CFB, 0x8AD50D, 0x0C99F6, 0x93E6E1, 0x15AA1A, 0x1933EC, 0x9F7F17,
    0xA18139, 0x27CDC2, 0x2B5434, 0xAD18CF, 0x3267D8, 0xB42B23, 0xB8B2D5, 0x3EFE2E,
    0xC54E89, 0x430272, 0x4F9B84, 0xC9D77F, 0x56A868, 0xD0E493, 0xDC7D65, 0x5A319E,
    0x64CFB0, 0xE2834B, 0xEE1ABD, 0x685646, 0xF72951, 0x7165AA, 0x7DFC5C, 0xFBB0A7,
    0x0CD1E9, 0x8A9D12, 0x8604E4, 0x00481F, 0x9F3708, 0x197BF3, 0x15E205, 0x93AEFE,
    0xAD50D0, 0x2B1C2B, 0x2785DD, 0xA1C926, 0x3EB631, 0xB8FACA, 0xB4633C, 0x322FC7,
    0xC99F60, 0x4FD39B, 0x434A6D, 0xC50696, 0x5A7981, 0xDC357A, 0xD0AC8C, 0x56E077,
    0x681E59, 0xEE52A2, 0xE2CB54, 0x6487AF, 0xFBF8B8, 0x7DB443, 0x712DB5, 0xF7614E,
    0x19A3D2, 0x9FEF29, 0x9376DF, 0x153A24, 0x8A4533, 0x0C09C8, 0x00903E, 0x86DCC5,
    0xB822EB, 0x3E6E10, 0x32F7E6, 0xB4BB1D, 0x2BC40A, 0xAD88F1, 0xA11107, 0x275DFC,
    0xDCED5B, 0x5AA1A0, 0x563856, 0xD074AD, 0x4F0BBA, 0xC94741, 0xC5DEB7, 0x43924C,
    0x7D6C62, 0xFB2099, 0xF7B96F, 0x71F594, 0xEE8A83, 0x68C678, 0x645F8E, 0xE21375,
    0x15723B, 0x933EC0, 0x9FA736, 0x19EBCD, 0x8694DA, 0x00D821, 0x0C41D7, 0x8A0D2C,
    0xB4F302, 0x32BFF9, 0x3E260F, 0xB86AF4, 0x2715E3, 0xA15918, 0xADC0EE, 0x2B8C15,
    0xD03CB2, 0x567049, 0x5AE9BF, 0xDCA544, 0x43DA53, 0xC596A8, 0xC90F5E, 0x4F43A5,
    0x71BD8B, 0xF7F170, 0xFB6886, 0x7D247D, 0xE25B6A, 0x641791, 0x688E67, 0xEEC29C,
    0x3347A4, 0xB50B5F, 0xB992A9, 0x3FDE52, 0xA0A145, 0x26EDBE, 0x2A7448, 0xAC38B3,
    0x92C69D, 0x148A66, 0x181390, 0x9E5F6B, 0x01207C, 0x876C87, 0x8BF571, 0x0DB98A,
    0xF6092D, 0x7045D6, 0x7CDC20, 0xFA90DB, 0x65EFCC, 0xE3A337, 0xEF3AC1, 0x69763A,
    0x578814, 0xD1C4EF, 0xDD5D19, 0x5B11E2, 0xC46EF5, 0x42220E, 0x4EBBF8, 0xC8F703,
    0x3F964D, 0xB9DAB6, 0xB54340, 0x330FBB, 0xAC70AC, 0x2A3C57, 0x26A5A1, 0xA0E95A,
    0x9E1774, 0x185B8F, 0x14C279, 0x928E82, 0x0DF195, 0x8BBD6E, 0x872498, 0x016863,
    0xFAD8C4, 0x7C943F, 0x700DC9, 0xF64132, 0x693E25, 0xEF72DE, 0xE3EB28, 0x65A7D3,
    0x5B59FD, 0xDD1506, 0xD18CF0, 0x57C00B, 0xC8BF1C, 0x4EF3E7, 0x426A11, 0xC426EA,
    0x2AE476, 0xACA88D, 0xA0317B, 0x267D80, 0xB90297, 0x3F4E6C, 0x33D79A, 0xB59B61,
    0x8B654F, 0x0D29B4, 0x01B042, 0x87FCB9, 0x1883AE, 0x9ECF55, 0x9256A3, 0x141A58,
    0xEFAAFF, 0x69E604, 0x657FF2, 0xE33309, 0x7C4C1E, 0xFA00E5, 0xF69913, 0x70D5E8,
    0x4E2BC6, 0xC8673D, 0xC4FECB, 0x42B230, 0xDDCD27, 0x5B81DC, 0x57182A, 0xD154D1,
    0x26359F, 0xA07964, 0xACE092, 0x2AAC69, 0xB5D37E, 0x339F85, 0x3F0673, 0xB94A88,
    0x87B4A6, 0x01F85D, 0x0D61AB, 0x8B2D50, 0x145247, 0x921EBC, 0x9E874A, 0x18CBB1,
    0xE37B16, 0x6537ED, 0x69AE1B, 0xEFE2E0, 0x709DF7, 0xF6D10C, 0xFA48FA, 0x7C0401,
    0x42FA2F, 0xC4B6D4, 0xC82F22, 0x4E63D9, 0xD11CCE, 0x575035, 0x5BC9C3, 0xDD8538,
]


def crc24q(data):
    """Compute CRC24Q checksum for RTCM3.

    Uses the Qualcomm feedback formula: process one byte at a time,
    feeding the top 8 bits of the running CRC XOR'd with the byte into the LUT.
    """
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFFFF) ^ CRC24Q_TABLE[(crc >> 16) ^ b]
    return crc & 0xFFFFFF


def verify_crc24q(frame):
    """Verify CRC24Q of a complete RTCM3 frame."""
    if len(frame) < 6:
        return False
    expected = crc24q(frame[:-3])
    actual = (frame[-3] << 16) | (frame[-2] << 8) | frame[-1]
    return expected == actual


# ============================================================================
# Frame utilities (pure Python — no C DLL dependency)
# ============================================================================


def generate_rtcm_frame(rtcm_type, payload):
    """Build a complete RTCM3 frame from message type and payload bytes.

    Encodes 12-bit type as: byte[0] = type>>4, byte[1] = (type&0xF)<<4,
    then appends payload. Matches the C DLL encoding used by dav_protocol.
    """
    content_len = 2 + len(payload)
    content = bytearray(content_len)
    content[0] = (rtcm_type >> 4) & 0xFF
    content[1] = (rtcm_type << 4) & 0xFF
    content[2:] = payload

    header = bytes([PREAMBLE, (content_len >> 8) & 0x03, content_len & 0xFF])
    crc_val = crc24q(header + bytes(content))
    crc_bytes = bytes([(crc_val >> 16) & 0xFF, (crc_val >> 8) & 0xFF, crc_val & 0xFF])
    return header + bytes(content) + crc_bytes


def replace_msm_gps_time(frame, epoch_ms):
    """Replace 30-bit GPS epoch time (DF004) in an MSM RTCM frame.

    The epoch time field starts at bit 24 of the message content (byte offset 3
    into the frame = after the 3-byte preamble/length header). The field spans
    bytes 6–9 (0-indexed in the full frame), sharing byte 9 with the next field
    so its low 2 bits must be preserved.

    Args:
        frame: Complete RTCM3 frame bytes.
        epoch_ms: New GPS epoch time in milliseconds (0–604799999).

    Returns new bytes with updated time and valid CRC.
    """
    temp = bytearray(frame)
    # 30-bit epoch at frame bytes 6-9:
    # byte 6: epoch bits 29-22  (all 8 bits belong to epoch)
    # byte 7: epoch bits 21-14  (all 8 bits belong to epoch)
    # byte 8: epoch bits 13-6   (all 8 bits belong to epoch)
    # byte 9: epoch bits 5-0 → bits 7-2; bits 1-0 = multiframe_indicator + IODS
    temp[6] = (epoch_ms >> 22) & 0xFF
    temp[7] = (epoch_ms >> 14) & 0xFF
    temp[8] = (epoch_ms >> 6) & 0xFF
    temp[9] = (temp[9] & 0x03) | ((epoch_ms & 0x3F) << 2)

    # Recalculate CRC24Q over entire frame (excluding old CRC)
    crc_val = crc24q(bytes(temp)[:-3])
    temp[-3] = (crc_val >> 16) & 0xFF
    temp[-2] = (crc_val >> 8) & 0xFF
    temp[-1] = crc_val & 0xFF
    return bytes(temp)


def _gps_tow_now():
    """Return current UTC time as GPS TOW in milliseconds.

    GPS week starts on Sunday; Python weekday() returns Monday=0.
    So weekday() + 1 maps: Monday→1 ... Saturday→6, Sunday→0.
    """
    utc_now = datetime.utcnow()
    gps_day = (utc_now.weekday() + 1) % 7
    tow_ms = (gps_day * 86400 + utc_now.hour * 3600 +
              utc_now.minute * 60 + utc_now.second) * 1000
    return tow_ms + utc_now.microsecond // 1000


def _gps_tow_from_utc(utc_dt):
    """Convert UTC datetime to GPS TOW in milliseconds."""
    # Same weekday→GPS-day mapping as _gps_tow_now (Sunday=day 0)
    gps_day = (utc_dt.weekday() + 1) % 7
    tow_ms = (gps_day * 86400 + utc_dt.hour * 3600 +
              utc_dt.minute * 60 + utc_dt.second) * 1000
    return tow_ms + utc_dt.microsecond // 1000


# ============================================================================
# Bit I/O
# ============================================================================


class BitReader:
    """MSB-first bit reader for RTCM3."""

    def __init__(self, data, offset_bytes=0):
        self._data = data
        self._pos = offset_bytes * 8

    def read_bits(self, n):
        """Read n bits MSB-first. bit_idx=7 means the leftmost bit of a byte."""
        result = 0
        for _ in range(n):
            byte_idx = self._pos // 8
            bit_idx = 7 - (self._pos % 8)
            result = (result << 1) | ((self._data[byte_idx] >> bit_idx) & 1)
            self._pos += 1
        return result

    def read_bits_signed(self, n):
        val = self.read_bits(n)
        if val >> (n - 1):
            val -= (1 << n)
        return val

    def byte_pos(self):
        return self._pos // 8 + (1 if self._pos % 8 else 0)


class BitWriter:
    """MSB-first bit writer for RTCM3."""

    def __init__(self):
        self._bits = []

    def write_bits(self, value, n):
        for i in range(n - 1, -1, -1):
            self._bits.append((value >> i) & 1)

    def write_bits_signed(self, value, n):
        if value < 0:
            value += (1 << n)
        self.write_bits(value, n)

    def to_bytes(self):
        data = bytearray()
        for i in range(0, len(self._bits), 8):
            byte = 0
            for j in range(8):
                bit_idx = i + j
                if bit_idx < len(self._bits):
                    byte = (byte << 1) | self._bits[bit_idx]
                else:
                    byte = byte << 1
            data.append(byte)
        return bytes(data)

    def bit_count(self):
        return len(self._bits)


# ============================================================================
# Message base class
# ============================================================================


class RtcmMessage:
    """Base class for parsed RTCM3 messages."""

    def __init__(self, msg_type, raw):
        self.msg_type = msg_type
        self.raw = raw
        self._payload = raw[3:-3]

    def summary(self):
        return f"RTCM {self.msg_type}: {len(self.raw)} bytes"

    def __repr__(self):
        return self.summary()

    def to_bytes(self):
        """Serialize back to raw RTCM3 frame with valid CRC24Q."""
        bw = self._encode()
        payload = bw.to_bytes()
        p_len = len(payload)
        header = bytes([PREAMBLE, (p_len >> 8) & 0x03, p_len & 0xFF])
        crc = crc24q(header + payload)
        return header + payload + bytes([(crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF])

    def _encode(self):
        return BitWriter()

    @staticmethod
    def _bytes_to_bitwriter(data):
        bw = BitWriter()
        for b in data:
            bw.write_bits(b, 8)
        return bw


# ============================================================================
# Message 1006: Station coordinates
# ============================================================================


class Message1006(RtcmMessage):
    """Station coordinates XYZ + antenna height."""

    def __init__(self, msg_type, raw):
        super().__init__(msg_type, raw)
        r = BitReader(raw, 3)
        self.station_id = r.read_bits(12)
        r.read_bits(6)
        self.gps_ind = r.read_bits(1)
        self.glo_ind = r.read_bits(1)
        self.gal_ind = r.read_bits(1)
        self.ref_sta_ind = r.read_bits(1)
        self.arp_x = r.read_bits_signed(38) * 0.0001
        r.read_bits(1); r.read_bits(3)
        self.arp_y = r.read_bits_signed(38) * 0.0001
        r.read_bits(2); r.read_bits(2)
        self.arp_z = r.read_bits_signed(38) * 0.0001
        self.antenna_height = r.read_bits(16) * 0.0001

    def summary(self):
        return (f"1006: Station {self.station_id}  "
                f"X={self.arp_x:.4f}m Y={self.arp_y:.4f}m Z={self.arp_z:.4f}m  "
                f"AntH={self.antenna_height:.4f}m")

    def _encode(self):
        bw = BitWriter()
        bw.write_bits(1006, 12)
        bw.write_bits(self.station_id, 12)
        bw.write_bits(0, 6)
        bw.write_bits(self.gps_ind, 1); bw.write_bits(self.glo_ind, 1)
        bw.write_bits(self.gal_ind, 1); bw.write_bits(self.ref_sta_ind, 1)
        bw.write_bits_signed(round(self.arp_x / 0.0001), 38)
        bw.write_bits(0, 1); bw.write_bits(0, 3)
        bw.write_bits_signed(round(self.arp_y / 0.0001), 38)
        bw.write_bits(0, 2); bw.write_bits(0, 2)
        bw.write_bits_signed(round(self.arp_z / 0.0001), 38)
        bw.write_bits(round(self.antenna_height / 0.0001), 16)
        return bw

    @classmethod
    def build(cls, station_id, x, y, z, antenna_height=0.0,
              gps_ind=1, glo_ind=1, gal_ind=0, ref_sta_ind=0):
        msg = cls.__new__(cls)
        msg.msg_type = 1006; msg.station_id = station_id
        msg.arp_x = x; msg.arp_y = y; msg.arp_z = z
        msg.antenna_height = antenna_height
        msg.gps_ind = gps_ind; msg.glo_ind = glo_ind
        msg.gal_ind = gal_ind; msg.ref_sta_ind = ref_sta_ind
        msg.raw = None
        return msg


# ============================================================================
# Message 1033: Receiver and antenna descriptor
# ============================================================================


class Message1033(RtcmMessage):
    """Receiver and antenna descriptor."""

    def __init__(self, msg_type, raw):
        super().__init__(msg_type, raw)
        r = BitReader(raw, 3)
        r.read_bits(12)  # confirmed type
        self.station_id = r.read_bits(12)
        desc_len = r.read_bits(8)
        self.descriptor = bytes(raw[r.byte_pos():r.byte_pos() + desc_len]).decode('ascii', errors='replace')
        pos = r.byte_pos() + desc_len
        self.antenna_setup_id = raw[pos]
        serial_len = raw[pos + 1]
        start = pos + 2
        self.serial_number = bytes(raw[start:start + serial_len]).decode('ascii', errors='replace')

    def summary(self):
        return (f"1033: Station {self.station_id}  "
                f"Desc='{self.descriptor}'  Setup={self.antenna_setup_id}  "
                f"SN='{self.serial_number}'")

    def _encode(self):
        desc_bytes = self.descriptor.encode('ascii', errors='replace')
        sn_bytes = self.serial_number.encode('ascii', errors='replace')
        payload = bytearray([len(desc_bytes)])
        payload.extend(desc_bytes)
        payload.append(self.antenna_setup_id)
        payload.append(len(sn_bytes))
        payload.extend(sn_bytes)
        bw = BitWriter()
        bw.write_bits(1033, 12); bw.write_bits(self.station_id, 12)
        return self._bytes_to_bitwriter(bw.to_bytes() + payload)

    @classmethod
    def build(cls, station_id, descriptor="", serial_number="Unknown",
              antenna_setup_id=0):
        msg = cls.__new__(cls)
        msg.msg_type = 1033; msg.station_id = station_id
        msg.descriptor = descriptor; msg.serial_number = serial_number
        msg.antenna_setup_id = antenna_setup_id
        msg.raw = None
        return msg


# ============================================================================
# MSM Message (GPS / GLONASS / Galileo / BeiDou)
# ============================================================================


def _gnss_from_type(msg_type):
    """Derive GNSS index from MSM message type (e.g. 1074→0=GPS, 1084→1=GLONASS)."""
    return (msg_type - 1071) // 10


def _level_from_type(msg_type):
    """Extract MSM level (4-7) from message type (e.g. 1077→7)."""
    return msg_type % 10


class MsmMessage(RtcmMessage):
    """MSM4/5/6/7 message."""

    def __init__(self, msg_type, raw):
        super().__init__(msg_type, raw)
        self.gnss = GNSS_NAMES.get(_gnss_from_type(msg_type), f"GNSS(?)")
        self.level = _level_from_type(msg_type)
        r = BitReader(raw, 3)

        self.station_id = r.read_bits(12)
        self.epoch_ms = r.read_bits(30)
        self.multiframe = r.read_bits(1)
        self.iods = r.read_bits(3)
        r.read_bits(7)
        self.clock_steering = r.read_bits(2)
        self.ext_clock = r.read_bits(2)
        self.div_free = r.read_bits(1)
        self.smooth_interval = r.read_bits(3)

        self.sat_mask = r.read_bits(64)
        self.num_sats = bin(self.sat_mask).count('1')
        self.sig_mask = r.read_bits(32)
        self.num_signals = bin(self.sig_mask).count('1')

        self.cell_mask = [r.read_bits(1) for _ in range(self.num_sats * self.num_signals)]

        self.satellite_data = []
        for i in range(self.num_sats):
            self.satellite_data.append({
                'sat_id': self._sat_index(i),
                'rough_range_ms': r.read_bits(8),
                'rough_pr': r.read_bits(10),
                'pr_m1': r.read_bits_signed(14),
                'phase_range': r.read_bits_signed(24),
            })

    def _sat_index(self, i):
        count = 0
        for pos in range(64):
            if (self.sat_mask >> (63 - pos)) & 1:
                if count == i:
                    return pos + 1
                count += 1
        return 0

    def summary(self):
        sats = ', '.join(str(s['sat_id']) for s in self.satellite_data)
        return (f"{self.msg_type}: {self.gnss} M{self.level}  "
                f"Station={self.station_id}  Epoch={self.epoch_ms}ms  "
                f"Sats={self.num_sats}({sats})  Signals={self.num_signals}")

    def _encode(self):
        bw = BitWriter()
        bw.write_bits(self.msg_type, 12); bw.write_bits(self.station_id, 12)
        bw.write_bits(self.epoch_ms, 30)
        bw.write_bits(self.multiframe, 1); bw.write_bits(self.iods, 3)
        bw.write_bits(0, 7)
        bw.write_bits(self.clock_steering, 2); bw.write_bits(self.ext_clock, 2)
        bw.write_bits(self.div_free, 1); bw.write_bits(self.smooth_interval, 3)
        bw.write_bits(self.sat_mask, 64); bw.write_bits(self.sig_mask, 32)
        for c in self.cell_mask:
            bw.write_bits(c, 1)
        for sat in self.satellite_data:
            bw.write_bits(sat['rough_range_ms'], 8)
            bw.write_bits(sat['rough_pr'], 10)
            bw.write_bits_signed(sat['pr_m1'], 14)
            bw.write_bits_signed(sat['phase_range'], 24)
        return bw


# ============================================================================
# MsmBuilder: construct MSM messages from simulated data
# ============================================================================


# Default signal masks: 32-bit bitmask where each set bit = one signal type tracked.
# Mask values follow RTCM Table 3.5-91 signal/RNSS mapping.
DEFAULT_SIGNALS = {
    "GPS":     0b00000000000000000000000000101010,  # L1C/A + L2P
    "GLONASS": 0b00000000000000000000000000001010,  # L1 + L2
    "Galileo": 0b00000000000000000000000100000010,  # E1 + E5a
    "BeiDou":  0b00000000000000000000001100000000,  # B1 + B2
}


class MsmBuilder:
    """Build MSM messages from simulated satellite data."""

    GPS_LEAP_SECONDS = 18  # UTC−GPS offset as of 2017 (leap seconds since Jan 1980)

    gps_tow_now = staticmethod(_gps_tow_now)
    gps_tow_from_utc = staticmethod(_gps_tow_from_utc)

    @staticmethod
    def _build(msg_type, station_id, num_sats, gnss, epoch_ms=0,
               pr_m1_range=(-1000, 1000), phase_range_val=(-50000, 50000), seed=0x1234):
        epoch_ms = _gps_tow_now() if epoch_ms == 'now' else epoch_ms
        msg = MsmMessage.__new__(MsmMessage)
        msg.msg_type = msg_type; msg.gnss = gnss; msg.level = 4
        msg.station_id = station_id; msg.epoch_ms = epoch_ms
        msg.multiframe = 0; msg.iods = 0
        msg.clock_steering = 0; msg.ext_clock = 0
        msg.div_free = 0; msg.smooth_interval = 0; msg.raw = None

        if num_sats > 64:
            num_sats = 64
        msg.sat_mask = ((1 << num_sats) - 1) << (64 - num_sats) if num_sats > 0 else 0
        msg.num_sats = num_sats

        sig_mask = DEFAULT_SIGNALS.get(gnss, 0)
        msg.sig_mask = sig_mask
        msg.num_signals = bin(sig_mask).count('1')

        msg.cell_mask = [1] * (num_sats * msg.num_signals)

        pr_min, pr_max = pr_m1_range
        ph_min, ph_max = phase_range_val
        msg.satellite_data = []
        for i in range(num_sats):
            msg.satellite_data.append({
                'sat_id': i + 1,
                'rough_range_ms': 70 + (i % 15),
                'rough_pr': (i * 37 + seed) % 1024,
                'pr_m1': _lcg(seed + i * 7, pr_min, pr_max),
                'phase_range': _lcg(seed + i * 13, ph_min, ph_max),
            })
        return msg

    @classmethod
    def gps(cls, msg_type=1074, station_id=0, num_sats=6, **kw):
        return cls._build(msg_type, station_id, num_sats, "GPS", **kw)

    @classmethod
    def glonass(cls, msg_type=1084, station_id=0, num_sats=3, **kw):
        return cls._build(msg_type, station_id, num_sats, "GLONASS", **kw)

    @classmethod
    def galileo(cls, msg_type=1094, station_id=0, num_sats=0, **kw):
        return cls._build(msg_type, station_id, num_sats, "Galileo", **kw)

    @classmethod
    def beidou(cls, msg_type=1124, station_id=0, num_sats=18, **kw):
        return cls._build(msg_type, station_id, num_sats, "BeiDou", **kw)


def _lcg(seed, lo, hi):
    """Trivial LCG for deterministic pseudo-range simulation."""
    val = (seed * 1103515245 + 12345) & 0x7FFFFFFF
    return lo + (val % (hi - lo + 1))


# ============================================================================
# Message 1230: GLONASS code-phase biases
# ============================================================================


class Message1230(RtcmMessage):
    """GLONASS code-phase biases."""

    def __init__(self, msg_type, raw):
        super().__init__(msg_type, raw)
        r = BitReader(raw, 3)
        r.read_bits(12)
        self.station_id = r.read_bits(12)
        r.read_bits(1); r.read_bits(3); r.read_bits(7)
        self.bias_indicator = r.read_bits(5)
        n_signals = 4 if self.bias_indicator & 0x10 else 3
        self.signals = []
        for _ in range(n_signals):
            self.signals.append({
                'signal_id': r.read_bits(5),
                'bias': r.read_bits_signed(14) * 0.02,
            })

    def summary(self):
        lines = [f"1230: Station {self.station_id}  GLONASS code-phase biases:"]
        for s in self.signals:
            lines.append(f"  Signal {s['signal_id']}: {s['bias']:.2f}m")
        return '\n'.join(lines)

    def _encode(self):
        bw = BitWriter()
        bw.write_bits(1230, 12); bw.write_bits(self.station_id, 12)
        bw.write_bits(0, 1); bw.write_bits(0, 3); bw.write_bits(0, 7)
        bw.write_bits(self.bias_indicator, 5)
        for s in self.signals:
            bw.write_bits(s['signal_id'], 5)
            bw.write_bits_signed(round(s['bias'] / 0.02), 14)
        return bw

    @classmethod
    def build(cls, station_id=0, biases=None):
        if biases is None:
            biases = [(0, 0.0), (0, 0.0), (0, 0.02)]
        msg = cls.__new__(cls)
        msg.msg_type = 1230; msg.station_id = station_id
        msg.bias_indicator = 0x03 | (0x10 if len(biases) >= 4 else 0)
        msg.signals = [{'signal_id': sid, 'bias': b} for sid, b in biases]
        msg.raw = None
        return msg


# ============================================================================
# Message factory
# ============================================================================

MSG_PARSERS = {
    1006: Message1006, 1033: Message1033,
    1074: MsmMessage, 1075: MsmMessage, 1076: MsmMessage, 1077: MsmMessage,
    1084: MsmMessage, 1085: MsmMessage, 1086: MsmMessage, 1087: MsmMessage,
    1094: MsmMessage, 1095: MsmMessage, 1096: MsmMessage, 1097: MsmMessage,
    1114: MsmMessage,
    1124: MsmMessage, 1125: MsmMessage, 1126: MsmMessage, 1127: MsmMessage,
    1230: Message1230,
}


def parse_rtcm_frame(raw_bytes):
    """Parse a single RTCM3 raw frame. Returns RtcmMessage subclass or None."""
    if not raw_bytes or raw_bytes[0] != PREAMBLE:
        return None
    if len(raw_bytes) < 6:
        return None
    msg_type = (raw_bytes[3] << 4) | (raw_bytes[4] >> 4)
    parser = MSG_PARSERS.get(msg_type, RtcmMessage)
    try:
        return parser(msg_type, raw_bytes)
    except (IndexError, struct.error):
        return RtcmMessage(msg_type, raw_bytes)


def parse_rtcm_file(json_path):
    """Parse all RTCM frames from a JSON file. Returns list of RtcmMessage objects."""
    with open(json_path, 'r') as f:
        j = json.load(f)
    results = []
    for type_str, info in j.get('frames', {}).items():
        raw = bytes.fromhex(info['hex'])
        msg = parse_rtcm_frame(raw)
        if msg:
            results.append(msg)
    results.sort(key=lambda m: m.msg_type)
    return results


# ============================================================================
# Errors
# ============================================================================


class RtkProtocolError(Exception):
    pass


class ConnectionError(RtkProtocolError):
    pass


# Backward-compat aliases
RtkSenderError = RtkProtocolError


# ============================================================================
# RtkSender — Serial RTK data sender
# ============================================================================


BUILDERS = {
    'GPS': MsmBuilder.gps, 'GLONASS': MsmBuilder.glonass,
    'Galileo': MsmBuilder.galileo, 'BeiDou': MsmBuilder.beidou,
}

DEFAULT_MSG_CONFIG = {
    1006: {'station_id': 0, 'x': -2396842.8368, 'y': -5976984.0662,
           'z': 11628934.2224, 'antenna_height': 0.0003},
    1033: {'station_id': 0, 'descriptor': '', 'serial_number': 'Unknown'},
    1074: {'gnss': 'GPS',     'num_sats': 8},
    1084: {'gnss': 'GLONASS', 'num_sats': 3},
    1094: {'gnss': 'Galileo', 'num_sats': 2},
    1124: {'gnss': 'BeiDou',  'num_sats': 18},
    1230: {'station_id': 0},
}


class RtkSender:
    """RTK correction data sender over serial port.

    Supports two modes:
      Template mode — load real data from JSON, refresh only MSM time.
      Builder mode — field-by-field construction with simulated data.
    """

    MAX_PARSE_SIZE = 5000

    def __init__(self, log_callback=None):
        self._log = log_callback or (lambda msg: None)
        self._serial = None
        self._send_thread = None
        self._is_sending = False
        self._rtk_data = {}
        self._templates = None
        self._msg_config = dict(DEFAULT_MSG_CONFIG)
        self._light_config = None

    # ---- connection ---------------------------------------------------

    def connect(self, port_name, baud=115200, timeout=5.0):
        """Open serial port. port_name can be 'COM3' or numeric index."""
        from .open_serial import dav_serial_driver_t

        if self._serial and self._serial.com_state == 1:
            return

        self._serial = dav_serial_driver_t()
        port_index = self._resolve_port_index(port_name, timeout)

        if not self._serial.open_serial(port_index, baud):
            self._serial.close_del_serial()
            self._serial = None
            raise ConnectionError(f"Failed to open serial port {port_name}")

        self._log(f"Connected to {port_name} at {baud} baud")

    def disconnect(self):
        """Close serial connection and stop sending."""
        self.stop_send()
        if self._serial:
            self._serial.close_del_serial()
            self._serial = None
        self._log("Disconnected")

    def close(self):
        self.disconnect()

    @property
    def is_connected(self):
        return bool(self._serial and self._serial.com_state == 1)

    @property
    def is_sending(self):
        return self._is_sending

    @staticmethod
    def list_ports():
        import serial.tools.list_ports
        return [(p.device, p.description) for p in serial.tools.list_ports.comports()]

    # ---- data loading ------------------------------------------------

    def load_rtk_data(self, filepath):
        """Parse RTCM3 messages from a .bin file. Returns count."""
        if self._is_sending:
            raise RtkProtocolError("Cannot load data while sending")
        with open(filepath, 'rb') as f:
            return self._parse_rtcm_data(f.read())

    def load_rtk_data_from_bytes(self, data):
        if self._is_sending:
            raise RtkProtocolError("Cannot load data while sending")
        return self._parse_rtcm_data(data)

    def load_rtk_data_from_json(self, filepath):
        """Load RTCM messages from JSON to the cyclic send pool."""
        if self._is_sending:
            raise RtkProtocolError("Cannot load data while sending")
        with open(filepath, 'r') as f:
            j = json.load(f)
        self._rtk_data.clear()
        for type_str, info in j.get('frames', {}).items():
            self._rtk_data[int(type_str)] = bytes.fromhex(info['hex'])
        self._log(f"Loaded {len(self._rtk_data)} RTCM messages from {filepath}")
        return len(self._rtk_data)

    def _parse_rtcm_data(self, data):
        """Scan binary buffer for RTCM3 frames by preamble.

        Length is encoded in bytes 1-2 (10-bit: bits 2-9 of byte1, bits 0-7 of byte2),
        giving just the content length. Total frame = 3B preamble/len + content + 3B CRC.
        For MSM types the epoch time field (bytes 6–9) is zeroed so the sender can
        overwrite it with live timestamps each cycle.
        """
        self._rtk_data.clear()
        i = 0
        limit = min(len(data), self.MAX_PARSE_SIZE)
        while i < limit:
            if data[i] != PREAMBLE:
                i += 1; continue
            # 10-bit content length from header
            rtcm_len = data[i + 2] | ((data[i + 1] & 0x3) << 8)
            rtcm_len += 6  # + 3B header + 3B CRC
            if i + rtcm_len > len(data):
                i += 1; continue
            frame = data[i:i + rtcm_len]
            if not verify_crc24q(frame):
                i += rtcm_len; continue
            rtcm_type = (frame[3] << 4) | (frame[4] >> 4)
            if rtcm_type in RTCM_MSM_TYPES:
                # Zero out the 30-bit GPS epoch time (DF004 at bit 24 of message)
                # so it can be replaced with live time each send cycle
                temp = bytearray(frame)
                temp[9] &= 0x3; temp[8] = 0; temp[7] = 0; temp[6] = 0
                self._rtk_data[rtcm_type] = bytes(temp)
            else:
                self._rtk_data[rtcm_type] = frame
            i += rtcm_len
        self._log(f"Parsed {len(self._rtk_data)} RTCM types: {sorted(self._rtk_data)}")
        return len(self._rtk_data)

    @property
    def rtk_types(self):
        return sorted(self._rtk_data.keys())

    def get_rtk_data(self, rtcm_type):
        return self._rtk_data.get(rtcm_type)

    def set_rtk_data(self, rtcm_type, data):
        """Directly set a raw RTCM frame to the cyclic send pool."""
        if self._is_sending:
            raise RtkProtocolError("Cannot modify data while sending")
        self._rtk_data[rtcm_type] = data

    def clear_rtk_data(self):
        if self._is_sending:
            raise RtkProtocolError("Cannot clear data while sending")
        self._rtk_data.clear()

    # ---- template mode -----------------------------------------------

    def load_templates_from_json(self, json_path):
        """Load RTCM frames from JSON as send templates.

        When sending via send_rtcm_cycle() or start_auto_send(),
        MSM messages have only the GPS time field refreshed each cycle.
        Non-MSM messages are sent unchanged.
        """
        if self._is_sending:
            raise RtkProtocolError("Cannot load templates while sending")
        with open(json_path, 'r') as f:
            j = json.load(f)
        self._templates = {}
        for type_str, info in j.get('frames', {}).items():
            self._templates[int(type_str)] = bytes.fromhex(info['hex'])
        self._log(f"Loaded {len(self._templates)} message templates from {json_path}")
        return len(self._templates)

    def get_template_types(self):
        return sorted(self._templates.keys()) if self._templates else []

    # ---- builder config ----------------------------------------------

    def set_msg_config(self, msg_type, **kwargs):
        """（Builder mode）Modify simulated message parameters."""
        if msg_type not in self._msg_config:
            raise RtkProtocolError(f"Unsupported message type: {msg_type}")
        self._msg_config[msg_type].update(kwargs)

    def disable_msg(self, msg_type):
        if self._templates:
            self._templates.pop(msg_type, None)
        else:
            self._msg_config[msg_type]['_disabled'] = True

    def enable_msg(self, msg_type):
        if self._templates:
            self._log("Use load_templates_from_json() to re-enable in template mode")
        else:
            self._msg_config[msg_type].pop('_disabled', None)

    # ---- send control ------------------------------------------------

    def send_rtcm(self, rtcm_type, payload):
        """Build and send a single RTCM frame (one-shot).

        Preamble + length + type + payload + CRC24Q are auto-generated.
        """
        if not self.is_connected:
            raise ConnectionError("Serial port not open")
        self._serial.serial_write_data(generate_rtcm_frame(rtcm_type, payload))

    def write_raw(self, data):
        """Write raw bytes directly to serial (no framing)."""
        if not self.is_connected:
            raise ConnectionError("Serial port not open")
        self._serial.serial_write_data(data)

    def send_rtcm_cycle(self):
        """Send one round of RTCM messages.

        Priority: templates > loaded data > builder config.
        Template mode — uses loaded templates, replaces MSM time only.
        Data mode — uses raw frames from bin/JSON, replaces MSM time only.
        Builder mode — constructs messages from DEFAULT_MSG_CONFIG with simulated data.
        """
        if not self.is_connected:
            raise ConnectionError("Serial port not open")

        if self._templates:
            self._send_cycle_from_templates()
        elif self._rtk_data:
            self._send_cycle_from_data()
        else:
            self._send_cycle_from_builders()

    def start_send(self, use_real_utc=False):
        """Start cyclic sending of loaded RTK data (from bin/JSON)."""
        if not self.is_connected:
            raise ConnectionError("Serial port not open")
        if not self._rtk_data and not self._templates:
            raise RtkProtocolError("No RTK data. Use load_rtk_data() or load_templates_from_json() first.")
        if self._is_sending:
            return
        self._use_real_utc = use_real_utc
        self._is_sending = True
        self._send_thread = threading.Thread(target=self._legacy_send_task, daemon=True)
        self._send_thread.start()
        self._log(f"Started sending RTK data (UTC={use_real_utc})")

    def start_auto_send(self, interval=1.0):
        """Start background thread that calls send_rtcm_cycle() at fixed interval."""
        if not self.is_connected:
            raise ConnectionError("Serial port not open")
        if self._is_sending:
            return
        self._auto_interval = interval
        self._is_sending = True
        self._send_thread = threading.Thread(target=self._auto_send_task, daemon=True)
        self._send_thread.start()
        self._log(f"Auto-send started (interval={interval}s)")

    def stop_send(self, timeout=2.0):
        """Stop any active sending."""
        if not self._is_sending:
            return
        self._is_sending = False
        if self._send_thread and self._send_thread.is_alive():
            self._send_thread.join(timeout=timeout)
            self._send_thread = None
        self._log("Stopped sending RTK data")

    stop_auto_send = stop_send

    # ---- real-time light control --------------------------------------

    def set_light_single_color(self, light_id, count, color):
        """RTCM 4006: single color per LED."""
        self._light_config = ('single', light_id, count, color)

    def set_light_rgb(self, light_id, count, fr, fg, fb, br, bg, bb, full_bright=True):
        """RTCM 4007: RGB foreground + background per LED."""
        bright = b'\xff' * count if full_bright else b'\x00' * count
        self._light_config = ('rgb', light_id, count, fr, fg, fb, br, bg, bb, bright)

    def clear_light(self):
        self._light_config = None

    # ---- context manager ----------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    def __del__(self):
        try:
            self.disconnect()
        except Exception:
            pass

    # ---- internals ----------------------------------------------------

    def _resolve_port_index(self, port_name, timeout):
        try:
            return int(port_name)
        except ValueError:
            pass
        deadline = time.time() + timeout
        while time.time() < deadline:
            for i, name in enumerate(self._serial.usb_com_name_list):
                if port_name.upper() in name.upper():
                    return i
            for i, port in enumerate(self._serial.usb_com_port_list):
                if port_name.upper() == port.upper():
                    return i
            time.sleep(0.1)
        raise ConnectionError(f"Port '{port_name}' not found. Available: {self._serial.usb_com_name_list}")

    def _ensure_connected(self):
        if not self.is_connected:
            raise ConnectionError("Serial port not open")

    # Template mode cycle
    def _send_cycle_from_templates(self):
        utc_now = datetime.utcnow()
        day_utc_ms = (utc_now.weekday() * 86400 + utc_now.hour * 3600 +
                       utc_now.minute * 60 + utc_now.second) * 1000

        for msg_type in sorted(self._templates):
            raw = self._templates[msg_type]
            if msg_type in RTCM_MSM_TYPES:
                raw = replace_msm_gps_time(raw, day_utc_ms)
            self._serial.serial_write_data(raw)

    # Builder mode cycle
    def _send_cycle_from_builders(self):
        for msg_type, cfg in sorted(self._msg_config.items()):
            if cfg.get('_disabled'):
                continue
            m = None
            if msg_type == 1006:
                m = Message1006.build(station_id=cfg['station_id'], x=cfg['x'],
                    y=cfg['y'], z=cfg['z'], antenna_height=cfg['antenna_height'])
            elif msg_type == 1033:
                m = Message1033.build(station_id=cfg['station_id'],
                    descriptor=cfg['descriptor'], serial_number=cfg['serial_number'])
            elif msg_type in (1074, 1084, 1094, 1124):
                bld = BUILDERS[cfg['gnss']]
                m = bld(msg_type, station_id=cfg.get('station_id', 0),
                        num_sats=cfg['num_sats'], epoch_ms='now')
            elif msg_type == 1230:
                m = Message1230.build(station_id=cfg['station_id'])
            else:
                continue
            self._serial.serial_write_data(m.to_bytes())

    # Cyclic data mode (loaded from bin/JSON)
    def _send_cycle_from_data(self):
        utc_now = datetime.utcnow()
        day_utc_ms = (utc_now.weekday() * 86400 + utc_now.hour * 3600 +
                       utc_now.minute * 60 + utc_now.second) * 1000
        for rtcm_type, raw in self._rtk_data.items():
            if rtcm_type in RTCM_MSM_TYPES:
                raw = replace_msm_gps_time(raw, day_utc_ms)
            self._serial.serial_write_data(raw)

    # Background tasks
    def _legacy_send_task(self):
        send_tick = 0
        last_second = -1
        while self._is_sending:
            utc_now = datetime.utcnow()
            if last_second == utc_now.second:
                self._send_light_frame()
                if not self._is_sending:
                    return
                time.sleep(0.1)
                continue
            last_second = utc_now.second
            send_tick += 1
            day_utc_ms = (utc_now.weekday() * 86400 + utc_now.hour * 3600 +
                           utc_now.minute * 60 + utc_now.second) * 1000
            for rtcm_type, raw in self._rtk_data.items():
                if not self._is_sending:
                    return
                if rtcm_type in RTCM_MSM_TYPES:
                    data = replace_msm_gps_time(raw, day_utc_ms)
                else:
                    data = raw
                self._serial.serial_write_data(data)
        return

    def _auto_send_task(self):
        while self._is_sending:
            tick = time.time()
            try:
                self.send_rtcm_cycle()
            except Exception as e:
                self._log(f"Auto-send error: {e}")
            if not self._is_sending:
                return
            elapsed = time.time() - tick
            time.sleep(max(0, self._auto_interval - elapsed))

    def _send_light_frame(self):
        if self._light_config is None:
            return
        config = self._light_config
        if config[0] == 'single':
            _, lid, cnt, col = config
            payload = struct.pack('<H', lid) + struct.pack('<B', col) * cnt
            self._serial.serial_write_data(generate_rtcm_frame(4006, payload))
        elif config[0] == 'rgb':
            _, lid, cnt, fr, fg, fb, br, bg, bb, bright = config
            payload = (struct.pack('<H', lid) +
                       struct.pack('<B', fr) + struct.pack('<B', fg) + struct.pack('<B', fb) +
                       struct.pack('<B', br) + struct.pack('<B', bg) + struct.pack('<B', bb) +
                       bright)
            self._serial.serial_write_data(generate_rtcm_frame(4007, payload))


# ============================================================================
# Unified CLI
# ============================================================================


def main():
    import argparse

    p = argparse.ArgumentParser(description='RTK Test Protocol — RTCM3 parse, build, send')
    sub = p.add_subparsers(dest='cmd')

    # ---- send ----
    s = sub.add_parser('send', help='Send RTCM over serial')
    s.add_argument('port', help='Serial port (e.g. COM4)')
    s.add_argument('-b', '--baud', type=int, default=115200)
    s.add_argument('-d', '--duration', type=float, default=0, help='Seconds (0=forever)')
    s.add_argument('--mode', choices=['template', 'builder'], default='template')
    s.add_argument('--json', help='JSON template file')
    s.add_argument('-n', '--sats', type=int, default=8, help='Sat count (builder mode)')

    # ---- parse ----
    pr = sub.add_parser('parse', help='Parse RTCM JSON export')
    pr.add_argument('json_file')

    # ---- build ----
    b = sub.add_parser('build', help='Build RTCM frame from simulated data')
    b.add_argument('-t', '--type', type=int, default=1074)
    b.add_argument('-s', '--station', type=int, default=0)
    b.add_argument('-n', '--sats', type=int, default=6)
    b.add_argument('-e', '--epoch', type=str, default='0', help='Epoch ms or "now"')
    b.add_argument('--hex', action='store_true', help='Output hex only')

    # ---- check ----
    c = sub.add_parser('check', help='Verify CRC24Q of hex frame')
    c.add_argument('hex_str')

    # ---- ports ----
    sub.add_parser('ports', help='List serial ports')

    args = p.parse_args()

    def tlog(msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    if args.cmd == 'send':
        sender = RtkSender(log_callback=tlog)
        try:
            sender.connect(args.port, args.baud)
            if args.mode == 'template' and args.json:
                sender.load_templates_from_json(args.json)
            sender.start_auto_send(1.0)
            if args.duration > 0:
                time.sleep(args.duration)
                sender.stop_send()
            else:
                print("Sending... Ctrl+C to stop.")
                while True:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nInterrupted.")
        except RtkProtocolError as e:
            print(f"Error: {e}")
        finally:
            sender.disconnect()

    elif args.cmd == 'parse':
        msgs = parse_rtcm_file(args.json_file)
        for msg in msgs:
            name = RTCM_TYPE_NAMES.get(msg.msg_type, '')
            if name:
                print(f"\n{'='*60}\n  {name}\n{'='*60}")
            print(f"  {msg.summary()}")
            raw = msg.raw
            for i in range(0, len(raw), 16):
                print(f"  {i:04X}: {' '.join(f'{b:02X}' for b in raw[i:i+16])}")
        print()

    elif args.cmd == 'build':
        from argparse import Namespace
        bl = {'GPS': MsmBuilder.gps, 'GLONASS': MsmBuilder.glonass,
              'Galileo': MsmBuilder.galileo, 'BeiDou': MsmBuilder.beidou}
        gnss_map = {1074: 'GPS', 1084: 'GLONASS', 1094: 'Galileo', 1124: 'BeiDou'}
        gnss = gnss_map.get(args.type, 'GPS')
        bld = bl[gnss]
        ep = 'now' if args.epoch == 'now' else int(args.epoch)
        msg = bld(msg_type=args.type, station_id=args.station, num_sats=args.sats, epoch_ms=ep)
        raw = msg.to_bytes()
        if args.hex:
            print(raw.hex())
        else:
            print(msg.summary())
            print(f"CRC valid: {verify_crc24q(raw)}  ({len(raw)} bytes)")
            for i in range(0, len(raw), 16):
                print(f"  {i:04X}: {' '.join(f'{b:02X}' for b in raw[i:i+16])}")

    elif args.cmd == 'check':
        raw = bytes.fromhex(args.hex_str)
        mt = (raw[3] << 4) | (raw[4] >> 4) if len(raw) >= 5 else 0
        print(f"Type: {mt} {RTCM_TYPE_NAMES.get(mt, '')}")
        print(f"Length: {len(raw)} bytes")
        print(f"CRC24Q valid: {verify_crc24q(raw)}")

    elif args.cmd == 'ports':
        ports = RtkSender.list_ports()
        if ports:
            for dev, desc in ports:
                print(f"  {dev} — {desc}")
        else:
            print("No serial ports found.")

    else:
        p.print_help()


if __name__ == '__main__':
    main()
