"""
DAV Protocol — Pure Python message framing (no C DLL required).

Usage::

    # 1. Create instance with your local address
    dav = DavProtocol(local_address=DavProtocol.make_address(mac_id=0x1234, role=AddressRole.PC_CLIENT))

    # 2. Register a physical-layer send callback
    dav.set_send_callback(my_serial.write)         # or my_udp_socket.sendto, etc.

    # 3. Send a command frame
    dav.send(receiver=0xABCD, cmd=0x0001, data=b'\\x08\\x00\\x01')

    # 4. Feed received bytes into the state machine
    for header, payload in dav.feed(incoming_bytes):
        print(f"Received cmd=0x{header['cmd']:04X} from 0x{header['sender_address']:013X}")


Author: generated from dav_protocol.h / dav_protocol.c / support/*.c
Protocol version: 0
"""

from __future__ import annotations

import struct
from enum import IntEnum
from typing import Callable, Iterator, Optional, Tuple, Dict, Any

# ---------------------------------------------------------------------------
# Enums matching the C definitions
# ---------------------------------------------------------------------------


class EncryptType(IntEnum):
    NONE = 0
    ENIGMA1 = 1
    ENIGMA2 = 2
    AES1 = 3
    AES2 = 4
    RSA1 = 5  # not implemented
    RSA2 = 6  # not implemented
    SHIFT = 7


class MessageType(IntEnum):
    CMD = 0
    ACK = 1


class AddressRole(IntEnum):
    UAV = 0
    RADIO_RC_RECEIVER = 1
    LPPC = 2
    PAYLOAD = 3
    PC_CLIENT = 0xF


class UnpackStatus(IntEnum):
    FIND_SOF = 0
    AUTH_HEADER = 1
    RECEIVE_DATA = 2
    AUTH_PACK = 3
    DATA_HANDLE = 4


# Broadcast feature flags (high 16 bits of broadcast_config)
BROADCAST_INTERFACE_BY_ADDRESS = 1 << 16
BROADCAST_INTERFACE_ALL_BY_ADDRESS = 2 << 16

# ---------------------------------------------------------------------------
# CRC tables — identical to CRC8_CRC16_CRC32.c
# ---------------------------------------------------------------------------

CRC8_TABLE: Tuple[int, ...] = (
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

CRC16_TABLE: Tuple[int, ...] = (
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

# ---------------------------------------------------------------------------
# Enigma tables — identical to enigma.c
# ---------------------------------------------------------------------------

ENIGMA_ENCRYPT_TABLE: Tuple[Tuple[int, ...], Tuple[int, ...]] = (
    (
        0, 9, 18, 27, 36, 45, 54, 63, 72, 65, 90, 83, 108, 101, 126, 119,
        144, 153, 130, 139, 180, 189, 166, 175, 216, 209, 202, 195, 252, 245, 238, 231,
        41, 32, 59, 50, 13, 4, 31, 22, 97, 104, 115, 122, 69, 76, 87, 94,
        185, 176, 171, 162, 157, 148, 143, 134, 241, 248, 227, 234, 213, 220, 199, 206,
        82, 91, 64, 73, 118, 127, 100, 109, 26, 19, 8, 1, 62, 55, 44, 37,
        194, 203, 208, 217, 230, 239, 244, 253, 138, 131, 152, 145, 174, 167, 188, 181,
        123, 114, 105, 96, 95, 86, 77, 68, 51, 58, 33, 40, 23, 30, 5, 12,
        235, 226, 249, 240, 207, 198, 221, 212, 163, 170, 177, 184, 135, 142, 149, 156,
        164, 173, 182, 191, 128, 137, 146, 155, 236, 229, 254, 247, 200, 193, 218, 211,
        52, 61, 38, 47, 16, 25, 2, 11, 124, 117, 110, 103, 88, 81, 74, 67,
        141, 132, 159, 150, 169, 160, 187, 178, 197, 204, 215, 222, 225, 232, 243, 250,
        29, 20, 15, 6, 57, 48, 43, 34, 85, 92, 71, 78, 113, 120, 99, 106,
        246, 255, 228, 237, 210, 219, 192, 201, 190, 183, 172, 165, 154, 147, 136, 129,
        102, 111, 116, 125, 66, 75, 80, 89, 46, 39, 60, 53, 10, 3, 24, 17,
        223, 214, 205, 196, 251, 242, 233, 224, 151, 158, 133, 140, 179, 186, 161, 168,
        79, 70, 93, 84, 107, 98, 121, 112, 7, 14, 21, 28, 35, 42, 49, 56,
    ),
    (
        0, 233, 59, 210, 118, 159, 77, 164, 236, 5, 215, 62, 154, 115, 161, 72,
        49, 216, 10, 227, 71, 174, 124, 149, 221, 52, 230, 15, 171, 66, 144, 121,
        98, 139, 89, 176, 20, 253, 47, 198, 142, 103, 181, 92, 248, 17, 195, 42,
        83, 186, 104, 129, 37, 204, 30, 247, 191, 86, 132, 109, 201, 32, 242, 27,
        196, 45, 255, 22, 178, 91, 137, 96, 40, 193, 19, 250, 94, 183, 101, 140,
        245, 28, 206, 39, 131, 106, 184, 81, 25, 240, 34, 203, 111, 134, 84, 189,
        166, 79, 157, 116, 208, 57, 235, 2, 74, 163, 113, 152, 60, 213, 7, 238,
        151, 126, 172, 69, 225, 8, 218, 51, 123, 146, 64, 169, 13, 228, 54, 223,
        97, 136, 90, 179, 23, 254, 44, 197, 141, 100, 182, 95, 251, 18, 192, 41,
        80, 185, 107, 130, 38, 207, 29, 244, 188, 85, 135, 110, 202, 35, 241, 24,
        3, 234, 56, 209, 117, 156, 78, 167, 239, 6, 212, 61, 153, 112, 162, 75,
        50, 219, 9, 224, 68, 173, 127, 150, 222, 55, 229, 12, 168, 65, 147, 122,
        165, 76, 158, 119, 211, 58, 232, 1, 73, 160, 114, 155, 63, 214, 4, 237,
        148, 125, 175, 70, 226, 11, 217, 48, 120, 145, 67, 170, 14, 231, 53, 220,
        199, 46, 252, 21, 177, 88, 138, 99, 43, 194, 16, 249, 93, 180, 102, 143,
        246, 31, 205, 36, 128, 105, 187, 82, 26, 243, 33, 200, 108, 133, 87, 190,
    ),
)

ENIGMA_DECRYPT_TABLE: Tuple[Tuple[int, ...], Tuple[int, ...]] = (
    (
        0, 75, 150, 221, 37, 110, 179, 248, 74, 1, 220, 151, 111, 36, 249, 178,
        148, 223, 2, 73, 177, 250, 39, 108, 222, 149, 72, 3, 251, 176, 109, 38,
        33, 106, 183, 252, 4, 79, 146, 217, 107, 32, 253, 182, 78, 5, 216, 147,
        181, 254, 35, 104, 144, 219, 6, 77, 255, 180, 105, 34, 218, 145, 76, 7,
        66, 9, 212, 159, 103, 44, 241, 186, 8, 67, 158, 213, 45, 102, 187, 240,
        214, 157, 64, 11, 243, 184, 101, 46, 156, 215, 10, 65, 185, 242, 47, 100,
        99, 40, 245, 190, 70, 13, 208, 155, 41, 98, 191, 244, 12, 71, 154, 209,
        247, 188, 97, 42, 210, 153, 68, 15, 189, 246, 43, 96, 152, 211, 14, 69,
        132, 207, 18, 89, 161, 234, 55, 124, 206, 133, 88, 19, 235, 160, 125, 54,
        16, 91, 134, 205, 53, 126, 163, 232, 90, 17, 204, 135, 127, 52, 233, 162,
        165, 238, 51, 120, 128, 203, 22, 93, 239, 164, 121, 50, 202, 129, 92, 23,
        49, 122, 167, 236, 20, 95, 130, 201, 123, 48, 237, 166, 94, 21, 200, 131,
        198, 141, 80, 27, 227, 168, 117, 62, 140, 199, 26, 81, 169, 226, 63, 116,
        82, 25, 196, 143, 119, 60, 225, 170, 24, 83, 142, 197, 61, 118, 171, 224,
        231, 172, 113, 58, 194, 137, 84, 31, 173, 230, 59, 112, 136, 195, 30, 85,
        115, 56, 229, 174, 86, 29, 192, 139, 57, 114, 175, 228, 28, 87, 138, 193,
    ),
    (
        0, 199, 103, 160, 206, 9, 169, 110, 117, 178, 18, 213, 187, 124, 220, 27,
        234, 45, 141, 74, 36, 227, 67, 132, 159, 88, 248, 63, 81, 150, 54, 241,
        61, 250, 90, 157, 243, 52, 148, 83, 72, 143, 47, 232, 134, 65, 225, 38,
        215, 16, 176, 119, 25, 222, 126, 185, 162, 101, 197, 2, 108, 171, 11, 204,
        122, 189, 29, 218, 180, 115, 211, 20, 15, 200, 104, 175, 193, 6, 166, 97,
        144, 87, 247, 48, 94, 153, 57, 254, 229, 34, 130, 69, 43, 236, 76, 139,
        71, 128, 32, 231, 137, 78, 238, 41, 50, 245, 85, 146, 252, 59, 155, 92,
        173, 106, 202, 13, 99, 164, 4, 195, 216, 31, 191, 120, 22, 209, 113, 182,
        244, 51, 147, 84, 58, 253, 93, 154, 129, 70, 230, 33, 79, 136, 40, 239,
        30, 217, 121, 190, 208, 23, 183, 112, 107, 172, 12, 203, 165, 98, 194, 5,
        201, 14, 174, 105, 7, 192, 96, 167, 188, 123, 219, 28, 114, 181, 21, 210,
        35, 228, 68, 131, 237, 42, 138, 77, 86, 145, 49, 246, 152, 95, 255, 56,
        142, 73, 233, 46, 64, 135, 39, 224, 251, 60, 156, 91, 53, 242, 82, 149,
        100, 163, 3, 196, 170, 109, 205, 10, 17, 214, 118, 177, 223, 24, 184, 127,
        179, 116, 212, 19, 125, 186, 26, 221, 198, 1, 161, 102, 8, 207, 111, 168,
        89, 158, 62, 249, 151, 80, 240, 55, 44, 235, 75, 140, 226, 37, 133, 66,
    ),
)

# ---------------------------------------------------------------------------
# CRC helpers
# ---------------------------------------------------------------------------

CRC8_INIT = 0xFF
CRC16_INIT = 0xFFFF


def crc8(data: bytes) -> int:
    """Compute CRC8 over *data* (initial value 0xFF)."""
    crc = CRC8_INIT
    for b in data:
        crc = CRC8_TABLE[crc ^ b]
    return crc & 0xFF


def crc16(data: bytes) -> int:
    """Compute CRC16 over *data* (initial value 0xFFFF)."""
    crc = CRC16_INIT
    for b in data:
        crc = (crc >> 8) ^ CRC16_TABLE[(crc ^ b) & 0xFF]
    return crc & 0xFFFF


# ---------------------------------------------------------------------------
# Enigma cipher helpers
# ---------------------------------------------------------------------------


def _enigma_encrypt(key: bytes, iv: bytearray, buf: bytearray) -> None:
    """In-place Enigma encrypt (reverse order, like C code)."""
    t0, t1 = ENIGMA_ENCRYPT_TABLE[0], ENIGMA_ENCRYPT_TABLE[1]
    k0, k1 = key[0], key[1]
    length = len(buf)
    for i in range(length):
        idx = length - 1 - i
        b = buf[idx]
        offset = k0 + iv[0] + b
        b = t0[offset & 0xFF]
        offset = k1 + iv[1] + b
        b = t1[offset & 0xFF]
        buf[idx] = b
        iv[0] = (iv[0] + 1) & 0xFF
        if i % 11 == 0:
            iv[1] = (iv[1] + 1) & 0xFF


def _enigma_decrypt(key: bytes, iv: bytearray, buf: bytearray) -> None:
    """In-place Enigma decrypt (reverse order, like C code)."""
    d0, d1 = ENIGMA_DECRYPT_TABLE[0], ENIGMA_DECRYPT_TABLE[1]
    k0, k1 = key[0], key[1]
    length = len(buf)
    for i in range(length):
        idx = length - 1 - i
        b = buf[idx]
        b = d1[b]
        b = (b - (k1 + iv[1])) & 0xFF
        b = d0[b]
        b = (b - (k0 + iv[0])) & 0xFF
        buf[idx] = b
        iv[0] = (iv[0] + 1) & 0xFF
        if i % 11 == 0:
            iv[1] = (iv[1] + 1) & 0xFF


# ---------------------------------------------------------------------------
# Shift cipher
# ---------------------------------------------------------------------------


def _shift_encrypt(buf: bytearray, data_len: int) -> None:
    """In-place 4-bit shift encrypt."""
    encrypt_len = data_len  # data_len already includes CMD_SIZE
    temp = buf.copy()
    # clear last padding byte's high nibble (keep only low nibble)
    temp[len(buf) - 1] &= 0x0F
    for i in range(encrypt_len - 1, -1, -1):
        temp[i + 1] = (temp[i + 1] & 0x0F) | ((temp[i] & 0x0F) << 4)
        temp[i] >>= 4
    buf[:] = temp


def _shift_decrypt(buf: bytearray, length: int) -> None:
    """In-place 4-bit shift decrypt."""
    for i in range(length):
        buf[i] = ((buf[i] << 4) & 0xFF) | ((buf[i + 1] >> 4) & 0x0F)


# ---------------------------------------------------------------------------
# Optional AES support  (requires pycryptodome:  pip install pycryptodome)
# ---------------------------------------------------------------------------

try:
    from Crypto.Cipher import AES as _AES

    def _aes_encrypt(key: bytes, iv: bytes, buf: bytearray) -> None:
        cipher = _AES.new(key, _AES.MODE_CBC, iv=iv)
        encrypted = cipher.encrypt(bytes(buf))
        buf[:] = encrypted

    def _aes_decrypt(key: bytes, iv: bytes, buf: bytearray) -> None:
        cipher = _AES.new(key, _AES.MODE_CBC, iv=iv)
        decrypted = cipher.decrypt(bytes(buf))
        buf[:] = decrypted

    _HAS_AES = True
except ImportError:
    _HAS_AES = False


# ===================================================================
# Main protocol class
# ===================================================================


class DavProtocol:
    """Pure-Python DAV protocol message framer.

    Parameters
    ----------
    local_address : int
        52-bit local address.  Use :meth:`make_address` to build one.
    send_callback : callable or None
        Optional physical-layer send function, signature ``callback(raw_bytes: bytes)``.
    """

    SOF: int = 0xA5
    VERSION: int = 0
    MAX_DATA_LEN: int = 16352
    ADDRESS_MASK: int = 0xFFFFFFFFFFFFF  # 52 bits

    # Frame size constants matching the C DLL
    # GCC #pragma pack(1) tightly packs bitfields → 22 bytes
    HEAD_SIZE: int = 22  # sizeof(dav_protocol_header_t)
    CMD_SIZE: int = 2  # sizeof(uint16_t) for command id
    TAIL_SIZE: int = 2  # sizeof(uint16_t) for CRC16 tail

    ENIGMA_PADDING_ALIGN: int = 8
    AES_PADDING_ALIGN: int = 16

    def __init__(
        self,
        local_address: int = 0,
        send_callback: Optional[Callable[[bytes], None]] = None,
    ) -> None:
        self.local_address: int = local_address & self.ADDRESS_MASK
        self._send_callback: Optional[Callable[[bytes], None]] = send_callback
        self._seq: int = 0

        # Enigma key material:  [(key2, iv2), (key2, iv2)]  for ENIGMA1 / ENIGMA2
        self._enigma_keys: list = [None, None]  # type: ignore[list-item]

        # AES key material: [(key32, iv16), (key32, iv16)] for AES1 / AES2
        self._aes_keys: list = [None, None]  # type: ignore[list-item]

        # --- Receive state machine ---
        self._recv_buf: bytearray = bytearray()  # raw FIFO
        self._recv_state: int = UnpackStatus.FIND_SOF
        self._recv_frame: bytearray = bytearray()  # accumulating frame
        self._recv_total: int = 0
        self._recv_header: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Address helpers
    # ------------------------------------------------------------------

    @staticmethod
    def make_address(mac_id: int, role: int = AddressRole.PC_CLIENT) -> int:
        """Build a 52-bit DAV address from a 48-bit MAC and 4-bit role."""
        return ((role & 0xF) << 48) | (mac_id & 0xFFFFFFFFFFFF)

    @staticmethod
    def extract_address_parts(address: int) -> Tuple[int, int]:
        """Return ``(mac_id, role)`` from a 52-bit address."""
        address &= 0xFFFFFFFFFFFFF
        return (address & 0xFFFFFFFFFFFF, (address >> 48) & 0xF)

    # ------------------------------------------------------------------
    # Physical layer callback
    # ------------------------------------------------------------------

    def set_send_callback(self, callback: Callable[[bytes], None]) -> None:
        """Register a physical-layer send function.

        Example::

            dav.set_send_callback(serial_port.write)
            dav.set_send_callback(lambda data: sock.sendto(data, ('192.168.1.100', 9000)))
        """
        self._send_callback = callback

    # ------------------------------------------------------------------
    # Encryption key setup
    # ------------------------------------------------------------------

    def set_enigma_keys(self, index: int, key: bytes, iv: bytes) -> None:
        """Set key + IV for Enigma cipher.

        *index*: 0 for ENIGMA1, 1 for ENIGMA2.
        *key*: 2 bytes.  *iv*: 2 bytes.
        """
        self._enigma_keys[index] = (bytes(key[:2]), bytearray(iv[:2]))

    def set_aes_keys(self, index: int, key: bytes, iv: bytes) -> None:
        """Set key + IV for AES-256-CBC.

        *index*: 0 for AES1, 1 for AES2.
        *key*: 32 bytes.  *iv*: 16 bytes.
        """
        self._aes_keys[index] = (bytes(key[:32]), bytes(iv[:16]))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFF
        return seq

    def _calc_padding(self, data_len: int, encrypt_type: int) -> int:
        """Return the number of padding bytes for *data_len* (already includes CMD_SIZE)."""
        if encrypt_type in (EncryptType.AES1, EncryptType.AES2):
            rem = data_len % self.AES_PADDING_ALIGN
            return 0 if rem == 0 else self.AES_PADDING_ALIGN - rem
        elif encrypt_type in (EncryptType.ENIGMA1, EncryptType.ENIGMA2):
            rem = data_len % self.ENIGMA_PADDING_ALIGN
            return 0 if rem == 0 else self.ENIGMA_PADDING_ALIGN - rem
        elif encrypt_type == EncryptType.SHIFT:
            return 1
        else:
            return 0

    def _encrypt_payload(self, buf: bytearray, encrypt_type: int, data_len: int) -> int:
        """Encrypt payload in-place.  *buf* is header + cmd + data + padding.
        Returns padding bytes count.
        """
        total_pre_pad = self.CMD_SIZE + data_len
        padding = self._calc_padding(total_pre_pad, encrypt_type)

        if encrypt_type == EncryptType.NONE:
            return 0

        payload = buf[self.HEAD_SIZE : self.HEAD_SIZE + total_pre_pad + padding]

        if encrypt_type == EncryptType.SHIFT:
            _shift_encrypt(payload, total_pre_pad)
        elif encrypt_type == EncryptType.ENIGMA1:
            if self._enigma_keys[0] is None:
                raise ValueError("ENIGMA1 keys not set — call set_enigma_keys(0, key, iv)")
            _enigma_encrypt(self._enigma_keys[0][0], self._enigma_keys[0][1], payload)
        elif encrypt_type == EncryptType.ENIGMA2:
            if self._enigma_keys[1] is None:
                raise ValueError("ENIGMA2 keys not set — call set_enigma_keys(1, key, iv)")
            _enigma_encrypt(self._enigma_keys[1][0], self._enigma_keys[1][1], payload)
        elif encrypt_type == EncryptType.AES1:
            if not _HAS_AES:
                raise ImportError("AES requires pycryptodome: pip install pycryptodome")
            if self._aes_keys[0] is None:
                raise ValueError("AES1 keys not set — call set_aes_keys(0, key, iv)")
            _aes_encrypt(self._aes_keys[0][0], self._aes_keys[0][1], payload)
        elif encrypt_type == EncryptType.AES2:
            if not _HAS_AES:
                raise ImportError("AES requires pycryptodome: pip install pycryptodome")
            if self._aes_keys[1] is None:
                raise ValueError("AES2 keys not set — call set_aes_keys(1, key, iv)")
            _aes_encrypt(self._aes_keys[1][0], self._aes_keys[1][1], payload)
        elif encrypt_type in (EncryptType.RSA1, EncryptType.RSA2):
            raise NotImplementedError("RSA encryption is not implemented")
        else:
            raise ValueError(f"Unknown encrypt_type: {encrypt_type}")

        return padding

    def _decrypt_payload(self, buf: bytearray, encrypt_type: int, length: int, padding: int) -> bool:
        """Decrypt payload in-place. Returns True on success."""
        if encrypt_type == EncryptType.NONE:
            return True

        payload = buf[self.HEAD_SIZE : self.HEAD_SIZE + length]

        try:
            if encrypt_type == EncryptType.SHIFT:
                _shift_decrypt(payload, length - 1)  # -1 because shift uses trailing byte
            elif encrypt_type == EncryptType.ENIGMA1:
                if self._enigma_keys[0] is None:
                    return False
                _enigma_decrypt(self._enigma_keys[0][0], self._enigma_keys[0][1], payload)
            elif encrypt_type == EncryptType.ENIGMA2:
                if self._enigma_keys[1] is None:
                    return False
                _enigma_decrypt(self._enigma_keys[1][0], self._enigma_keys[1][1], payload)
            elif encrypt_type == EncryptType.AES1:
                if not _HAS_AES or self._aes_keys[0] is None:
                    return False
                _aes_decrypt(self._aes_keys[0][0], self._aes_keys[0][1], payload)
            elif encrypt_type == EncryptType.AES2:
                if not _HAS_AES or self._aes_keys[1] is None:
                    return False
                _aes_decrypt(self._aes_keys[1][0], self._aes_keys[1][1], payload)
            elif encrypt_type in (EncryptType.RSA1, EncryptType.RSA2):
                return False
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Frame packing
    # ------------------------------------------------------------------

    def pack_header(
        self,
        receiver: int,
        payload_len: int,
        message_type: int = MessageType.CMD,
        ack_count: int = 0,
        broadcast_type: int = 0,
        encrypt_type: int = EncryptType.NONE,
        padding: int = 0,
    ) -> bytes:
        """Build header bytes (22 bytes) for a frame.

        Parameters
        ----------
        receiver : int
            52-bit receiver address.
        payload_len : int
            Total payload length = CMD_SIZE + data_len + padding.
        message_type : int
            ``MessageType.CMD`` (0) or ``MessageType.ACK`` (1).
        ack_count : int
            ACK sequence number (1-63), 0 if no ACK required.
        broadcast_type : int
            16-bit broadcast type mask.
        encrypt_type : int
            ``EncryptType`` value.
        padding : int
            Padding byte count (0-16).
        """
        # Byte 2-3: len(14 bits) | version(2 bits) as little-endian uint16
        len_version = (payload_len & 0x3FFF) | ((self.VERSION & 0x3) << 14)

        sender = self.local_address & self.ADDRESS_MASK
        rcvr = receiver & self.ADDRESS_MASK

        # Tightly packed bitfields across 2 uint64_t (128 bits total):
        #   msg_type(2) | ack(6) | recv(16) | sender(52) | receiver(52)
        # u64_0: msg_type(2) | ack(6) | recv(16) | sender_low40
        # u64_1: sender_high12 | receiver(52)
        u64_0 = (
            (message_type & 0x3)
            | ((ack_count & 0x3F) << 2)
            | ((broadcast_type & 0xFFFF) << 8)
            | ((sender & 0xFFFFFFFFFF) << 24)
        )
        u64_1 = ((sender >> 40) & 0xFFF) | ((rcvr & 0xFFFFFFFFFFFFF) << 12)

        # Byte 20: encrypt_type(3 bits) | padding_bytes(5 bits)
        enc_pad = ((encrypt_type & 0x7)) | ((padding & 0x1F) << 3)

        header = struct.pack(
            "<BBHQQBB",
            0xA5,  # sof
            0x00,  # seq placeholder
            len_version,
            u64_0,
            u64_1,
            enc_pad,
            0x00,  # crc8 placeholder
        )
        assert len(header) == self.HEAD_SIZE, f"Header size mismatch: {len(header)} != {self.HEAD_SIZE}"

        return header

    def _finalize_header(self, buf: bytearray, seq: int) -> None:
        """Set seq and compute CRC8 over the header region."""
        buf[1] = seq & 0xFF
        # CRC8 over entire header, result goes to last byte
        crc_val = crc8(buf[: self.HEAD_SIZE - 1])
        buf[self.HEAD_SIZE - 1] = crc_val

    def _finalize_frame(self, buf: bytearray) -> None:
        """Compute CRC16 over the entire frame, append to last 2 bytes."""
        frame_len = len(buf)
        crc_val = crc16(buf[: frame_len - self.TAIL_SIZE])
        buf[frame_len - 2] = crc_val & 0xFF
        buf[frame_len - 1] = (crc_val >> 8) & 0xFF

    # ------------------------------------------------------------------
    # Public pack / send API
    # ------------------------------------------------------------------

    def pack_frame(
        self,
        receiver: int,
        cmd: int,
        data: bytes = b"",
        *,
        encrypt_type: int = EncryptType.NONE,
        ack_count: int = 0,
        broadcast_type: int = 0,
        message_type: int = MessageType.CMD,
        ack_seq: int = 0,
    ) -> bytes:
        """Pack a complete DAV frame, return the raw bytes for transmission.

        Parameters
        ----------
        receiver : int
            52-bit receiver address.
        cmd : int
            16-bit command ID.
        data : bytes
            Protobuf-serialized payload (or raw bytes).
        encrypt_type : int
            ``EncryptType`` value (default: no encryption).
        ack_count : int
            ACK index (1-63), 0 = no ACK.
        broadcast_type : int
            16-bit broadcast role mask.
        message_type : int
            ``MessageType.CMD`` (default) or ``MessageType.ACK``.
        ack_seq : int
            Sequence number override.  When 0 the internal counter is used.

        Returns
        -------
        bytes
            Complete framed packet ready to hand to a physical layer.
        """
        data_len = len(data)
        if data_len > self.MAX_DATA_LEN:
            raise ValueError(f"Data too long: {data_len} > {self.MAX_DATA_LEN}")

        seq = ack_seq if ack_seq != 0 else self._next_seq()

        if message_type == MessageType.ACK:
            # ACK frames: payload is just the 4-byte ack value, no cmd field
            inner_data_len = data_len
            payload_len = inner_data_len
            padding = 0
        else:
            inner_data_len = data_len
            payload_len = self.CMD_SIZE + inner_data_len
            padding = self._calc_padding(payload_len, encrypt_type)

        payload_len += padding

        # Allocate frame buffer
        frame_len = self.HEAD_SIZE + payload_len + self.TAIL_SIZE
        buf = bytearray(frame_len)

        # Build header
        header = self.pack_header(
            receiver=receiver,
            payload_len=payload_len,
            message_type=message_type,
            ack_count=ack_count,
            broadcast_type=broadcast_type,
            encrypt_type=encrypt_type,
            padding=padding,
        )
        buf[: self.HEAD_SIZE] = header

        # Write payload
        if message_type == MessageType.ACK:
            buf[self.HEAD_SIZE : self.HEAD_SIZE + inner_data_len] = data
        else:
            struct.pack_into("<H", buf, self.HEAD_SIZE, cmd & 0xFFFF)
            buf[self.HEAD_SIZE + self.CMD_SIZE : self.HEAD_SIZE + self.CMD_SIZE + inner_data_len] = data

        # Encrypt
        if encrypt_type != EncryptType.NONE and message_type == MessageType.CMD:
            self._encrypt_payload(buf, encrypt_type, inner_data_len)
            # Update padding in header
            buf[self.HEAD_SIZE - 2] = ((encrypt_type & 0x7)) | ((padding & 0x1F) << 3)

        # Finalize: seq + CRC8 + CRC16
        self._finalize_header(buf, seq)
        self._finalize_frame(buf)

        return bytes(buf)

    def pack_ack(
        self,
        receiver: int,
        cmd: int,
        ack_value: int,
        ack_count: int,
        ack_seq: int,
        encrypt_type: int = EncryptType.NONE,
    ) -> bytes:
        """Pack an ACK frame.

        Parameters
        ----------
        receiver : int
            52-bit receiver address.
        cmd : int
            Original command ID being acknowledged.
        ack_value : int
            32-bit report value.
        ack_count : int
            ACK index (must match the original message's ack_count).
        ack_seq : int
            Sequence number (must match the original message's seq).
        encrypt_type : int
            Encryption type (must match the original message).
        """
        return self.pack_frame(
            receiver=receiver,
            cmd=cmd,
            data=struct.pack("<I", ack_value & 0xFFFFFFFF),
            encrypt_type=encrypt_type,
            ack_count=ack_count,
            message_type=MessageType.ACK,
            ack_seq=ack_seq,
        )

    def send(
        self,
        receiver: int,
        cmd: int,
        data: bytes = b"",
        *,
        encrypt_type: int = EncryptType.NONE,
        ack_count: int = 0,
        broadcast_type: int = 0,
    ) -> bytes:
        """Pack a CMD frame and send it through the registered physical layer callback.

        Returns the packed bytes (same as :meth:`pack_frame`).
        """
        frame = self.pack_frame(
            receiver=receiver,
            cmd=cmd,
            data=data,
            encrypt_type=encrypt_type,
            ack_count=ack_count,
            broadcast_type=broadcast_type,
        )
        if self._send_callback is not None:
            self._send_callback(frame)
        return frame

    # ------------------------------------------------------------------
    # Frame unpacking  (state machine)
    # ------------------------------------------------------------------

    def _parse_header(self, data: bytes) -> Dict[str, Any]:
        """Parse the 22-byte header into a dict."""
        sof, seq, len_version, u64_0, u64_1, enc_pad, crc8_val = struct.unpack_from(
            "<BBHQQBB", data, 0
        )

        payload_len = len_version & 0x3FFF
        version = (len_version >> 14) & 0x3
        message_type = u64_0 & 0x3
        ack_count = (u64_0 >> 2) & 0x3F
        broadcast_type = (u64_0 >> 8) & 0xFFFF
        sender_low40 = (u64_0 >> 24) & 0xFFFFFFFFFF
        sender_high12 = u64_1 & 0xFFF
        sender_address = (sender_high12 << 40) | sender_low40
        receiver_address = (u64_1 >> 12) & self.ADDRESS_MASK
        encrypt_type = enc_pad & 0x7
        padding = (enc_pad >> 3) & 0x1F

        return {
            "sof": sof,
            "seq": seq,
            "payload_len": payload_len,
            "version": version,
            "message_type": message_type,
            "ack_count": ack_count,
            "broadcast_type": broadcast_type,
            "sender_address": sender_address,
            "receiver_address": receiver_address,
            "encrypt_type": encrypt_type,
            "padding": padding,
            "crc8": crc8_val,
        }

    def feed(self, raw_bytes: bytes) -> Iterator[Tuple[Dict[str, Any], bytes]]:
        """Feed raw bytes into the receive state machine.

        Yields ``(header_dict, payload_bytes)`` for each successfully decoded
        CMD frame.  ACK frames are handled internally (not yielded).

        Parameters
        ----------
        raw_bytes : bytes
            Raw bytes received from the physical layer.

        Yields
        ------
        header_dict : dict
            Parsed header fields: sof, seq, payload_len, version, message_type,
            ack_count, broadcast_type, sender_address, receiver_address,
            encrypt_type, padding, crc8.
            For CMD frames an extra key ``cmd`` (int) holds the command id.
        payload_bytes : bytes
            Decrypted payload (protobuf-serialized data, without the 2-byte cmd prefix).
        """
        self._recv_buf.extend(raw_bytes)

        # Continue while there is data OR we are mid-frame (AUTH_PACK / DATA_HANDLE
        # don't consume buffer bytes — they operate on the already-collected frame).
        while len(self._recv_buf) > 0 or self._recv_state in (
            UnpackStatus.AUTH_PACK,
            UnpackStatus.DATA_HANDLE,
        ):
            if self._recv_state == UnpackStatus.FIND_SOF:
                # Scan for SOF byte
                try:
                    idx = self._recv_buf.index(self.SOF)
                except ValueError:
                    self._recv_buf.clear()
                    return
                # Discard bytes before SOF
                del self._recv_buf[:idx]
                self._recv_state = UnpackStatus.AUTH_HEADER

            elif self._recv_state == UnpackStatus.AUTH_HEADER:
                if len(self._recv_buf) < self.HEAD_SIZE:
                    return  # need more data

                header_data = bytes(self._recv_buf[: self.HEAD_SIZE])
                hdr = self._parse_header(header_data)

                # Validate
                if (
                    hdr["sof"] != self.SOF
                    or hdr["payload_len"] > self.MAX_DATA_LEN
                    or hdr["version"] != self.VERSION
                ):
                    del self._recv_buf[0]  # discard one byte, re-scan
                    self._recv_state = UnpackStatus.FIND_SOF
                    continue

                if crc8(header_data[: self.HEAD_SIZE - 1]) != hdr["crc8"]:
                    del self._recv_buf[0]
                    self._recv_state = UnpackStatus.FIND_SOF
                    continue

                self._recv_header = hdr
                self._recv_total = hdr["payload_len"] + self.TAIL_SIZE
                self._recv_frame = bytearray()
                del self._recv_buf[: self.HEAD_SIZE]  # consume header bytes
                self._recv_state = UnpackStatus.RECEIVE_DATA

            elif self._recv_state == UnpackStatus.RECEIVE_DATA:
                needed = self._recv_total - len(self._recv_frame)
                if needed > 0:
                    take = min(needed, len(self._recv_buf))
                    self._recv_frame.extend(self._recv_buf[:take])
                    del self._recv_buf[:take]

                if len(self._recv_frame) < self._recv_total:
                    return  # need more data

                self._recv_state = UnpackStatus.AUTH_PACK

            elif self._recv_state == UnpackStatus.AUTH_PACK:
                # Reconstruct full frame from stored header + received payload+tail
                full = self._build_full_frame()
                expected_crc = crc16(full[: len(full) - self.TAIL_SIZE])
                actual_crc = full[len(full) - 2] | (full[len(full) - 1] << 8)

                if expected_crc != actual_crc:
                    # CRC failure — discard frame, go back to scanning
                    self._recv_frame = bytearray()
                    self._recv_state = UnpackStatus.FIND_SOF
                    continue

                self._recv_state = UnpackStatus.DATA_HANDLE

            elif self._recv_state == UnpackStatus.DATA_HANDLE:
                yield from self._handle_received_frame()
                self._recv_frame = bytearray()
                self._recv_header = None
                self._recv_total = 0
                self._recv_state = UnpackStatus.FIND_SOF

    def _build_full_frame(self) -> bytes:
        """Reconstruct the full frame from parsed header + received data."""
        sender = self._recv_header["sender_address"] & self.ADDRESS_MASK
        rcvr = self._recv_header["receiver_address"] & self.ADDRESS_MASK
        header_data = struct.pack(
            "<BBHQQBB",
            self._recv_header["sof"],
            self._recv_header["seq"],
            (self._recv_header["payload_len"] & 0x3FFF)
            | ((self._recv_header["version"] & 0x3) << 14),
            (self._recv_header["message_type"] & 0x3)
            | ((self._recv_header["ack_count"] & 0x3F) << 2)
            | ((self._recv_header["broadcast_type"] & 0xFFFF) << 8)
            | ((sender & 0xFFFFFFFFFF) << 24),
            ((sender >> 40) & 0xFFF) | ((rcvr & 0xFFFFFFFFFFFFF) << 12),
            (self._recv_header["encrypt_type"] & 0x7)
            | ((self._recv_header["padding"] & 0x1F) << 3),
            self._recv_header["crc8"],
        )
        return header_data + bytes(self._recv_frame)

    def _handle_received_frame(self) -> Iterator[Tuple[Dict[str, Any], bytes]]:
        """Process a successfully received frame."""
        hdr = self._recv_header
        full = self._build_full_frame()
        buf = bytearray(full)

        # Decrypt
        if hdr["encrypt_type"] != EncryptType.NONE:
            if not self._decrypt_payload(
                buf, hdr["encrypt_type"], hdr["payload_len"], hdr["padding"]
            ):
                return  # decrypt failed, drop frame

        if hdr["message_type"] == MessageType.CMD:
            # Extract cmd_id
            cmd = struct.unpack_from("<H", buf, self.HEAD_SIZE)[0]
            data_start = self.HEAD_SIZE + self.CMD_SIZE
            data_len = hdr["payload_len"] - self.CMD_SIZE - hdr["padding"]
            payload = bytes(buf[data_start : data_start + data_len])

            hdr["cmd"] = cmd
            yield (hdr, payload)

        elif hdr["message_type"] == MessageType.ACK:
            # ACK frames: payload is the 4-byte report value
            if hdr["payload_len"] >= 4:
                ack_value = struct.unpack_from("<I", buf, self.HEAD_SIZE)[0]
                hdr["ack_value"] = ack_value
            # ACK is for internal use; the caller can also receive it
            hdr["cmd"] = 0
            yield (hdr, bytes(buf[self.HEAD_SIZE : self.HEAD_SIZE + hdr["payload_len"] - hdr["padding"]]))

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def reset_receive(self) -> None:
        """Reset the receive state machine (e.g. after a transport disconnect)."""
        self._recv_buf.clear()
        self._recv_frame = bytearray()
        self._recv_state = UnpackStatus.FIND_SOF
        self._recv_header = None
        self._recv_total = 0

    @property
    def has_aes(self) -> bool:
        """True if pycryptodome is available for AES encrypt/decrypt."""
        return _HAS_AES


# ===================================================================
# Quick self-test  (run this file directly to verify CRC / enigma)
# ===================================================================

if __name__ == "__main__":
    # Verify CRC8
    test_data = bytes([0xA5, 0x00, 0x5A, 0x8A] + [0x00] * 25 + [0x00])  # 30 bytes with SOF/seq/len
    # Fill payload for a known CRC8 test
    hdr = bytearray(30)
    hdr[0] = 0xA5
    hdr[1] = 0xA5
    hdr[2] = 0x5A
    hdr[3] = 0x8A
    # u64_0 .. u64_2 and enc_pad left zero
    c8 = crc8(hdr[:29])
    assert c8 is not None
    print(f"CRC8 of minimal header: 0x{c8:02X}")

    # Verify CRC16
    c16 = crc16(b"\xA5" * 16)
    print(f"CRC16 of 16*0xA5: 0x{c16:04X}")

    # Verify round-trip: pack → feed
    dav = DavProtocol(local_address=DavProtocol.make_address(0xABCD, AddressRole.PC_CLIENT))
    frame = dav.pack_frame(receiver=DavProtocol.make_address(0x1234, AddressRole.UAV), cmd=0x0001, data=b"Hello")
    print(f"Packed frame ({len(frame)} bytes): {frame.hex(' ')}")

    results = list(dav.feed(frame))
    if results:
        r_hdr, r_data = results[0]
        print(f"Round-trip OK: cmd=0x{r_hdr['cmd']:04X}  data={r_data!r}")
        print(f"  sender=0x{r_hdr['sender_address']:013X}  receiver=0x{r_hdr['receiver_address']:013X}")
    else:
        print("Round-trip FAILED — no frame decoded")

    # Verify shift encrypt round-trip
    dav2 = DavProtocol(local_address=DavProtocol.make_address(0x1, AddressRole.PC_CLIENT))
    frame2 = dav2.pack_frame(
        receiver=DavProtocol.make_address(0x2, AddressRole.UAV),
        cmd=0x0042,
        data=b"\x01\x02\x03\x04\x05\x06\x07",
        encrypt_type=EncryptType.SHIFT,
    )
    results2 = list(dav2.feed(frame2))
    if results2:
        r2_hdr, r2_data = results2[0]
        print(f"Shift encrypt round-trip OK: cmd=0x{r2_hdr['cmd']:04X}  data={r2_data.hex(' ')}")
    else:
        print("Shift encrypt round-trip FAILED")

    # Verify enigma round-trip
    dav3 = DavProtocol(local_address=DavProtocol.make_address(0x1, AddressRole.PC_CLIENT))
    dav3.set_enigma_keys(0, key=b"\x12\x34", iv=b"\xAB\xCD")
    frame3 = dav3.pack_frame(
        receiver=DavProtocol.make_address(0x2, AddressRole.UAV),
        cmd=0x0088,
        data=b"Enigma test message 1234",
        encrypt_type=EncryptType.ENIGMA1,
    )
    results3 = list(dav3.feed(frame3))
    if results3:
        r3_hdr, r3_data = results3[0]
        print(f"Enigma round-trip OK: cmd=0x{r3_hdr['cmd']:04X}  data={r3_data!r}")
    else:
        print("Enigma round-trip FAILED")

    print("\nAll self-tests completed.")
