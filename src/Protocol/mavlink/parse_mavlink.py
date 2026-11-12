import struct
import socket
import os
import json


class x25crc(object):
    '''x25 CRC - based on checksum.h from mavlink library'''
    def __init__(self, buf=None):
        self.crc = 0xffff
        if buf is not None:
            if isinstance(buf, str):
                self.accumulate_str(buf)
            else:
                self.accumulate(buf)

    def accumulate(self, buf):
        '''add in some more bytes'''
        accum = self.crc
        for b in buf:
            tmp = b ^ (accum & 0xff)
            tmp = (tmp ^ (tmp << 4)) & 0xFF
            accum = (accum >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)
        self.crc = accum

    def accumulate_str(self, buf):
        '''add in some more bytes (Python 3 compatible)'''
        # 使用 latin-1 编码保持原始字节（避免 Unicode 转换）
        self.accumulate(bytearray(buf, 'latin-1'))


class MAVLink_message:
    """MAVLink 消息类，支持双向解析（pack/unpack）

    通过 mavlink_version/mavlink_config_v41.json 读取各消息类型的
    struct_format、variables、crc_extra 等配置，实现 payload 的
    通用 pack/unpack。

    header 格式: start(1) + length(1) + seq(1) + sys_id(1) + comp_id(1) + msg_id(1) = 6 字节
    payload 格式: 由 msg_id 从 JSON 配置中查表决定
    crc 格式: uint16_t 小端序 = 2 字节
    """

    _CONFIG_CACHE = {}
    _CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               '..', '..', 'file', 'mavlink_version')
    DEFAULT_VERSION = 'v41'

    def __init__(self, start=254, length=0, seq=0, sys_id=0, comp_id=0,
                 msg_id=0, payload=None, crc=0, fields=None, hex_data=None,
                 version=None):
        """
        构建 MAVLink 消息。

        三种方式：
        1. 通过字段构建：MAVLink_message(msg_id=0, fields={...})
        2. 通过 payload 构建：MAVLink_message(msg_id=0, payload=b'...')
        3. 通过 hex_data 解析：MAVLink_message(hex_data='fe0900...')

        version: MAVLink 配置版本号，决定从 mavlink_version/ 加载哪个 JSON。
            支持格式：41 / '41' / 'v41' / 'V41'，均映射到 mavlink_config_v41.json。
            默认使用 DEFAULT_VERSION（'v41'）。
        """
        self.version = self._normalize_version(version if version is not None
                                               else self.DEFAULT_VERSION)
        self.msg_id = msg_id
        self.fields = fields if fields is not None else {}
        if hex_data is not None:
            self.unpack(hex_data)
        else:
            self.start = start
            self.length = length if length else (len(payload) if payload else 0)
            self.seq = seq
            self.sys_id = sys_id
            self.comp_id = comp_id
            self.payload = payload if payload is not None else b''
            self.crc = crc
            if self.fields:
                self._validate_and_fill_fields()

    @staticmethod
    def _normalize_version(version) -> str:
        """将版本号统一为 'v{NN}' 形式（接受 41 / '41' / 'v41' / 'V41'）"""
        v = str(version).strip().lower().lstrip('v')
        return f'v{v}'

    def _validate_and_fill_fields(self):
        """验证输入字段合法性，过滤非法字段，并为未提供的字段填充默认值 0"""
        config = self._get_config()
        if not config:
            return

        variables = config['variables']

        # 收集合法字段名及其数组长度
        valid_names = set()
        array_sizes = {}
        for var in variables:
            if '[' in var:
                base_name = var.split('[')[0]
                valid_names.add(base_name)
                array_sizes[base_name] = array_sizes.get(base_name, 0) + 1
            else:
                valid_names.add(var)

        # 过滤非法字段
        filtered = {}
        for key, value in self.fields.items():
            if key in valid_names:
                filtered[key] = value
            else:
                print(f"Warning: 字段 '{key}' 不是 msg_id={self.msg_id} 的有效字段，已忽略")

        # 为未提供的字段填充默认值
        for name in valid_names:
            if name not in filtered:
                filtered[name] = b'\x00' * array_sizes[name] if name in array_sizes else 0

        self.fields = filtered

    @classmethod
    def _get_config_path(cls, version) -> str:
        """根据版本号构建配置文件路径"""
        v = cls._normalize_version(version)
        return os.path.join(cls._CONFIG_DIR, f'mavlink_config_{v}.json')

    @classmethod
    def _load_config(cls, version):
        """加载指定版本的 JSON 配置（按版本类级缓存）"""
        v = cls._normalize_version(version)
        if v in cls._CONFIG_CACHE:
            return cls._CONFIG_CACHE[v]
        path = cls._get_config_path(v)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            cls._CONFIG_CACHE[v] = {m['msg_id']: m for m in data.get('messages', [])}
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Warning: 无法加载 MAVLink 配置 {path}: {e}")
            cls._CONFIG_CACHE[v] = {}
        return cls._CONFIG_CACHE[v]

    def _get_config(self):
        """获取当前 msg_id 对应的 JSON 配置（基于 self.version）"""
        config = self._load_config(self.version)
        return config.get(self.msg_id)

    @property
    def hex_data(self) -> str:
        """完整 MAVLink 帧的十六进制字符串"""
        return self.pack().hex()

    def pack(self, compute_crc=True) -> bytes:
        """将消息打包为字节序列（可选自动计算 CRC）"""
        if not self.payload and self.fields:
            self.pack_payload()

        self.length = len(self.payload)
        header = struct.pack('BBBBBB', self.start, self.length,
                             self.seq, self.sys_id, self.comp_id, self.msg_id)
        msgbuf = header + self.payload

        if compute_crc:
            config = self._get_config()
            crc_extra = config.get('crc_extra', 0) if config else 0
            crc = x25crc(msgbuf[1:])
            crc.accumulate_str(chr(crc_extra))
            self.crc = crc.crc

        crc_bytes = struct.pack('<H', self.crc)
        return msgbuf + crc_bytes

    def unpack(self, data) -> None:
        """从字节序列或十六进制字符串解析消息（自动尝试解析 payload）"""
        if isinstance(data, str):
            data = bytes.fromhex(data)

        if len(data) < 8:
            raise ValueError(
                f"数据长度不足，至少需要 8 字节（6 字节 header + payload + 2 字节 crc），"
                f"实际 {len(data)} 字节"
            )

        header = data[0:6]
        self.start, self.length, self.seq, self.sys_id, self.comp_id, self.msg_id = \
            struct.unpack('BBBBBB', header)
        self.payload = data[6:6 + self.length]
        crc_bytes = data[6 + self.length:6 + self.length + 2]
        self.crc = struct.unpack('<H', crc_bytes)[0] if len(crc_bytes) == 2 else 0

        # 尝试根据 JSON 配置自动解析 payload
        try:
            self.unpack_payload()
        except Exception:
            pass

    def pack_payload(self) -> bytes:
        """
        根据 JSON 配置将 self.fields 打包为 payload bytes。

        对于数组字段（如 ssid），fields 中应提供 bytes 或 str：
            fields = {'ssid': b'ABCD1234', ...}
        对于字符串字段（如 data），fields 中应提供 bytes 或 str：
            fields = {'data': b'...', ...}
        对于普通数值字段，fields 中应提供 int/float：
            fields = {'seq': 1, 'cur_lat': 123456789, ...}
        """
        config = self._get_config()
        if not config:
            return self.payload

        fmt = config['struct_format']
        variables = config['variables']

        values = []
        for var in variables:
            if '[' in var:
                base_name = var.split('[')[0]
                idx = int(var.split('[')[1].rstrip(']'))
                field_val = self.fields.get(base_name, b'')

                if isinstance(field_val, bytes):
                    values.append(field_val[idx] if idx < len(field_val) else 0)
                elif isinstance(field_val, str):
                    values.append(ord(field_val[idx]) if idx < len(field_val) else 0)
                elif isinstance(field_val, (list, tuple)):
                    values.append(field_val[idx] if idx < len(field_val) else 0)
                else:
                    values.append(0)
            else:
                val = self.fields.get(var, 0)
                if isinstance(val, str):
                    val = val.encode('utf-8')
                values.append(val)

        self.payload = struct.pack(fmt, *values)
        self.length = len(self.payload)
        return self.payload

    def unpack_payload(self) -> dict:
        """
        根据 JSON 配置将 self.payload 解析为 self.fields 字典。

        数组字段（如 ssid[0]...ssid[7]）会被合并为 bytes：
            fields['ssid'] = b'ABCD1234'
        字符串字段（如 data）保持为 bytes：
            fields['data'] = b'...'
        普通数值字段保持为 int/float：
            fields['seq'] = 1
        """
        config = self._get_config()
        if not config:
            return {}

        fmt = config['struct_format']
        variables = config['variables']
        expected_size = struct.calcsize(fmt)

        if len(self.payload) < expected_size:
            padded = self.payload.ljust(expected_size, b'\x00')
        else:
            padded = self.payload[:expected_size]

        values = struct.unpack(fmt, padded)
        self.fields = {}

        i = 0
        while i < len(variables):
            var = variables[i]
            if '[' in var:
                base_name = var.split('[')[0]
                arr = []
                j = i
                while j < len(variables) and variables[j].startswith(f"{base_name}["):
                    arr.append(values[j])
                    j += 1
                self.fields[base_name] = bytes(arr)
                i = j
            else:
                self.fields[var] = values[i]
                i += 1

        return self.fields

    def __repr__(self) -> str:
        return (
            f"MAVLink_message("
            f"start={self.start}, length={self.length}, seq={self.seq}, "
            f"sys_id={self.sys_id}, comp_id={self.comp_id}, msg_id={self.msg_id}, "
            f"payload_len={len(self.payload)}, crc=0x{self.crc:04X})"
        )

    def print(self) -> None:
        """打印 MAVLink 消息解析结果（参考 print_parse_result 格式）"""
        print(f"--- MAVLink 头部信息 ---")
        print(f"  - Start:        {self.start} (0x{self.start:02X}) [uint8_t]")
        print(f"  - Length:       {self.length} [uint8_t]")
        print(f"  - Seq:          {self.seq} [uint8_t]")
        print(f"  - SysID:        {self.sys_id} [uint8_t]")
        print(f"  - CompID:       {self.comp_id} [uint8_t]")
        print(f"  - MsgID:        {self.msg_id} [uint8_t]")

        if self.fields:
            config = self._get_config()
            msg_name = config['message_name'] if config else f"UNKNOWN_MSG_{self.msg_id}"
            print(f"--- {msg_name} 解析 ---")
            for key, value in self.fields.items():
                if isinstance(value, float):
                    print(f"  {key}: {value:.6f}")
                elif isinstance(value, bytes):
                    try:
                        text = value.rstrip(b'\x00').decode('utf-8')
                        if text and all(c.isprintable() or c.isspace() for c in text):
                            print(f"  {key}: {text!r} (hex: {value.hex()})")
                        else:
                            print(f"  {key}: {value.hex()}")
                    except UnicodeDecodeError:
                        print(f"  {key}: {value.hex()}")
                else:
                    print(f"  {key}: {value}")
        else:
            print(f"  Payload (Hex): {self.payload.hex()} (Len: {len(self.payload)})")

        print(f"CRC Value: 0x{self.crc:04X} [uint16_t]")

if __name__ == "__main__":
    # 示例：解析一条心跳消息的十六进制数据
    hex_data = "fe0caa010101000016000000000000000001f406"
    msg = MAVLink_message(hex_data=hex_data)
    msg.print()





        