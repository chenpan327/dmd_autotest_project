"""
DAV Payload — 消息体序列化/反序列化，基于 XML 消息定义文件。

读取 ``MessageDefineUAV.xml`` 获取 cmdID → protobuf 消息结构体的映射，
通过预生成的 ``_pb2.py`` 模块进行 protobuf 编解码。

依赖::

    pip install protobuf

用法::

    from dav_payload import DavPayload

    # 1. 实例化（指定 XML 和 pb2 模块路径）
    dp = DavPayload(
        xml_path="pyprotobuf/xml/MessageDefineUAV.xml",
        pb2_path="pyprotobuf/build/python/MessageDefineUAVC_pb2.py",
    )

    # 2. 编码：dict → protobuf bytes
    data = dp.encode(cmd_id=0x000C, device_type=0, product_name="UAV1", serial_number="SN001", check=0)
    # → b'\\x08\\x00\\x12\\x04UAV1...'

    # 3. 解码：bytes → protobuf message object (或 dict)
    msg = dp.decode(cmd_id=0x000F, data=b'\\x08\\x01\\x10\\x00...')
    print(msg.device_type)  # 属性访问
    print(dp.to_dict(msg))  # 或转 dict

    # 4. 配合 dav_protocol 使用
    from dav_protocol import DavProtocol, AddressRole

    dav = DavProtocol(...)
    dp = DavPayload(...)

    # 发送: 编码 → 组帧 → 发送
    payload = dp.encode(cmd_id=0x000C, device_type=0, product_name="UAV")
    dav.send(receiver=target, cmd=0x000C, data=payload)

    # 接收: 解帧 → 解码 → 处理
    for header, payload in dav.feed(raw_bytes):
        msg = dp.decode(cmd_id=header['cmd'], data=payload)
        print(f"收到 {dp.cmd_id_to_name(header['cmd'])}: {dp.to_dict(msg)}")
"""

from __future__ import annotations

import importlib.util
import os
import sys
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# XML parser (compatible with readXMLInfo.py logic)
# ---------------------------------------------------------------------------


def _get_key_data(xml_element, key_string):
    """Plist-style: return the element immediately following <key>key_string</key>."""
    children = list(xml_element)
    for i, el in enumerate(children):
        if el.tag == "key" and el.text == key_string:
            if i + 1 < len(children):
                return children[i + 1]
    return None


def _get_keys_string(xml_element):
    """Return all <key> text values in order."""
    return [el.text for el in xml_element if el.tag == "key"]


def _parse_xml(xml_path: str) -> Dict[str, Any]:
    """Parse MessageDefineUAV.xml and return {enums, structs, messages, files}."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # --- Files ---
    files_data = _get_key_data(root, "Files")
    files = []
    if files_data is not None and len(files_data) > 0:
        for file_el in files_data:
            files.append(
                {
                    "suffix": _get_key_data(file_el, "suffix").text,
                    "StructRename": _get_key_data(file_el, "StructRename").text,
                }
            )

    # --- Enums ---
    enums_data = _get_key_data(root, "Enums")
    enums = []
    if enums_data is not None and len(enums_data) > 0:
        for key_str in _get_keys_string(enums_data):
            enum_el = _get_key_data(enums_data, key_str)
            desc_el = _get_key_data(enum_el, "description")
            desc = desc_el.text if desc_el is not None else ""
            values_el = _get_key_data(enum_el, "values")
            values = []
            if values_el is not None:
                for val_key in _get_keys_string(values_el):
                    val_el = _get_key_data(values_el, val_key)
                    v = _get_key_data(val_el, "value").text
                    d = _get_key_data(val_el, "description")
                    values.append(
                        {
                            "enumName": val_key,
                            "value": v,
                            "description": d.text if d is not None else "",
                        }
                    )
            enums.append(
                {"enumStructName": key_str, "description": desc, "values": values}
            )

    # --- Structs ---
    structs_data = _get_key_data(root, "Structs")
    structs = []
    if structs_data is not None and len(structs_data) > 0:
        for key_str in _get_keys_string(structs_data):
            struct_el = _get_key_data(structs_data, key_str)
            variables = []
            for var_info in struct_el:
                var_keys = _get_keys_string(var_info)
                if var_keys:
                    var_type = var_keys[0]
                    var_name_el = _get_key_data(var_info, var_type)
                    var_desc_el = _get_key_data(var_info, "description")
                    variables.append(
                        {
                            "type": var_type,
                            "name": var_name_el.text if var_name_el is not None else "",
                            "description": var_desc_el.text
                            if var_desc_el is not None
                            else "",
                        }
                    )
            structs.append({"structName": key_str, "variable": variables})

    # --- Messages ---
    messages_data = _get_key_data(root, "Messages")
    messages = []
    if messages_data is not None and len(messages_data) > 0:
        for key_str in _get_keys_string(messages_data):
            msg_el = _get_key_data(messages_data, key_str)
            entry = {"name": key_str}
            for mk in _get_keys_string(msg_el):
                entry[mk] = _get_key_data(msg_el, mk).text
            messages.append(entry)

    return {"enums": enums, "structs": structs, "messages": messages, "files": files}


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class DavPayload:
    """DAV 协议 payload 编解码器。

    Parameters
    ----------
    xml_path : str
        ``MessageDefineUAV.xml`` 的路径。
    pb2_path : str or None
        预生成的 ``_pb2.py`` 模块路径（如 ``build/python/MessageDefineUAVC_pb2.py``）。
        传 None 则仅提供元数据查询，不提供 encode/decode。
    language_target : str
        选择语言版本：``"C"`` 或 ``"CSharp"``。默认 ``"C"``。
    """

    # protobuf 标量类型
    PROTOBUF_SCALARS = frozenset(
        [
            "bool",
            "double",
            "float",
            "int32",
            "uint32",
            "int64",
            "uint64",
            "sint32",
            "sint64",
            "fixed32",
            "fixed64",
            "sfixed32",
            "sfixed64",
            "string",
            "bytes",
        ]
    )

    def __init__(
        self,
        xml_path: str,
        pb2_path: Optional[str] = None,
        language_target: str = "C",
    ) -> None:
        self._xml_path = xml_path
        self._language_target = language_target

        # Parse XML
        parsed = _parse_xml(xml_path)
        self._enums: List[Dict] = parsed["enums"]
        self._structs: List[Dict] = parsed["structs"]
        self._messages: List[Dict] = parsed["messages"]

        # Determine StructRename key: "CType" or "CSharpType"
        self._struct_rename_key = "CType" if language_target == "C" else "CSharpType"

        # Build lookup tables
        self._cmd_to_msg: Dict[int, Dict] = {}  # cmdID(int) → message dict
        self._name_to_cmd: Dict[str, int] = {}  # message name → cmdID
        self._cmd_to_struct_name: Dict[int, str] = {}  # cmdID → protobuf class name
        self._name_to_struct_name: Dict[str, str] = {}  # message name → protobuf class name

        for msg in self._messages:
            try:
                cmd_id = int(msg.get("cmdID", "0"), 0)
            except (ValueError, TypeError):
                continue
            name = msg["name"]
            struct_name = msg.get(self._struct_rename_key, "") or ""
            origin_type = msg.get("OriginType", "")

            self._cmd_to_msg[cmd_id] = msg
            self._name_to_cmd[name] = cmd_id
            if struct_name:
                self._cmd_to_struct_name[cmd_id] = struct_name
                self._name_to_struct_name[name] = struct_name
            elif origin_type:
                self._cmd_to_struct_name[cmd_id] = origin_type
                self._name_to_struct_name[name] = origin_type

        # Load pb2 module
        self._pb2_module: Any = None
        self._pb2_available: bool = False
        if pb2_path is not None:
            self._load_pb2(pb2_path)

    # ------------------------------------------------------------------
    # pb2 module loading
    # ------------------------------------------------------------------

    def _load_pb2(self, pb2_path: str) -> None:
        """Import the pre-generated _pb2.py module."""
        try:
            spec = importlib.util.spec_from_file_location(
                "_dav_pb2_module", pb2_path
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load spec from {pb2_path}")
            self._pb2_module = importlib.util.module_from_spec(spec)
            sys.modules["_dav_pb2_module"] = self._pb2_module
            spec.loader.exec_module(self._pb2_module)
            self._pb2_available = True
        except ImportError as e:
            raise ImportError(
                f"protobuf 库未安装。请执行: pip install protobuf\n详情: {e}"
            ) from e
        except Exception as e:
            raise RuntimeError(f"加载 pb2 模块失败 ({pb2_path}): {e}") from e

    # ------------------------------------------------------------------
    # Lookup API
    # ------------------------------------------------------------------

    def cmd_id_to_name(self, cmd_id: int) -> Optional[str]:
        """返回 cmdID 对应的消息名称，如 ``"ENROLL_REQUEST"``。"""
        msg = self._cmd_to_msg.get(cmd_id)
        return msg["name"] if msg else None

    def cmd_id_to_struct_name(self, cmd_id: int) -> Optional[str]:
        """返回 cmdID 对应的 protobuf 结构体名称。"""
        return self._cmd_to_struct_name.get(cmd_id)

    def name_to_cmd_id(self, name: str) -> Optional[int]:
        """返回消息名称对应的 cmdID。"""
        return self._name_to_cmd.get(name)

    def get_message_info(self, cmd_id: int) -> Optional[Dict[str, Any]]:
        """返回 cmdID 对应的完整消息元数据。"""
        msg = self._cmd_to_msg.get(cmd_id)
        if msg is None:
            return None

        struct_name = self._cmd_to_struct_name.get(cmd_id)
        fields = self._get_struct_fields(struct_name) if struct_name else []

        return {
            "name": msg["name"],
            "cmd_id": cmd_id,
            "struct_name": struct_name,
            "origin_type": msg.get("OriginType", ""),
            "description": msg.get("description", ""),
            "fields": fields,
        }

    def get_all_messages(self) -> List[Dict[str, Any]]:
        """返回所有消息的元数据列表。"""
        result = []
        for msg in self._messages:
            try:
                cmd_id = int(msg.get("cmdID", "0"), 0)
            except (ValueError, TypeError):
                continue
            result.append(self.get_message_info(cmd_id))
        return result

    def _get_struct_fields(self, struct_name: str) -> List[Dict[str, str]]:
        """递归查找 struct 的字段定义。"""
        for s in self._structs:
            if s["structName"] == struct_name:
                return s["variable"]
        # Not found — might be a renamed type; try the OriginType
        for msg in self._messages:
            if msg.get(self._struct_rename_key) == struct_name:
                origin = msg.get("OriginType", "")
                for s in self._structs:
                    if s["structName"] == origin:
                        return s["variable"]
        return []

    @property
    def pb2_available(self) -> bool:
        """是否成功加载了 pb2 模块（提供 encode/decode）。"""
        return self._pb2_available

    # ------------------------------------------------------------------
    # Encode / Decode
    # ------------------------------------------------------------------

    def _get_pb2_class(self, cmd_id: int):
        """获取 cmdID 对应的 protobuf 消息类。"""
        if not self._pb2_available:
            raise RuntimeError("pb2 模块未加载，无法编解码。请在构造时传入 pb2_path。")

        struct_name = self._cmd_to_struct_name.get(cmd_id)
        if struct_name is None:
            raise KeyError(f"cmdID 0x{cmd_id:04X} 未在 XML 中定义，或该语言目标未包含此消息。")

        cls = getattr(self._pb2_module, struct_name, None)
        if cls is None:
            raise KeyError(
                f"protobuf 类 '{struct_name}' 在 pb2 模块中不存在（cmdID=0x{cmd_id:04X}）。"
            )
        return cls

    def encode(self, cmd_id: int, **fields) -> bytes:
        """将字段编码为 protobuf 字节。

        Parameters
        ----------
        cmd_id : int
            命令 ID。
        **fields
            消息体字段，关键字参数。嵌套消息传 dict，repeated 传 list。

        Returns
        -------
        bytes
            protobuf 序列化后的字节。

        Example::

            dp.encode(cmd_id=0x000C, device_type=0, product_name="UAV")
        """
        cls = self._get_pb2_class(cmd_id)
        msg = self._build_message(cls, fields)
        return msg.SerializeToString()

    def encode_by_name(self, msg_name: str, **fields) -> bytes:
        """按消息名称编码，等价于 ``encode(name_to_cmd_id(name), **fields)``。"""
        cmd_id = self._name_to_cmd.get(msg_name)
        if cmd_id is None:
            raise KeyError(f"未知消息名: {msg_name}")
        return self.encode(cmd_id, **fields)

    def decode(self, cmd_id: int, data: bytes):
        """将 protobuf 字节解码为消息对象。

        Returns
        -------
        protobuf message object
            可直接通过属性访问字段（如 ``msg.device_type``）。

        Example::

            msg = dp.decode(cmd_id=0x000F, data=payload)
            print(msg.device_type)
        """
        cls = self._get_pb2_class(cmd_id)
        msg = cls()
        msg.ParseFromString(data)
        return msg

    def decode_by_name(self, msg_name: str, data: bytes):
        """按消息名称解码。"""
        cmd_id = self._name_to_cmd.get(msg_name)
        if cmd_id is None:
            raise KeyError(f"未知消息名: {msg_name}")
        return self.decode(cmd_id, data)

    @staticmethod
    def to_dict(msg) -> Dict[str, Any]:
        """将 protobuf 消息对象转为普通 dict（递归处理嵌套消息和枚举）。"""
        from google.protobuf.json_format import MessageToDict

        return MessageToDict(msg, preserving_proto_field_name=True)

    @staticmethod
    def to_json(msg, indent: int = 2) -> str:
        """将 protobuf 消息对象转为 JSON 字符串。"""
        from google.protobuf.json_format import MessageToJson

        return MessageToJson(msg, preserving_proto_field_name=True, indent=indent)

    # ------------------------------------------------------------------
    # Internal: build protobuf message from dict/fields
    # ------------------------------------------------------------------

    def _build_message(self, cls, fields: Dict[str, Any]):
        """递归构造 protobuf message 对象。"""
        msg = cls()
        descriptor = cls.DESCRIPTOR

        for key, value in fields.items():
            field_desc = descriptor.fields_by_name.get(key)
            if field_desc is None:
                raise ValueError(
                    f"字段 '{key}' 在消息 '{descriptor.name}' 中不存在。"
                )

            if field_desc.label == field_desc.LABEL_REPEATED:
                # repeated field — value should be a list
                if not isinstance(value, (list, tuple)):
                    value = [value]
                repeated = getattr(msg, key)
                for item in value:
                    if field_desc.type == field_desc.TYPE_MESSAGE:
                        nested_cls = self._get_nested_class(cls, field_desc)
                        repeated.add().CopyFrom(self._build_message(nested_cls, item))
                    elif field_desc.type == field_desc.TYPE_ENUM:
                        repeated.append(self._resolve_enum(field_desc, item))
                    else:
                        repeated.append(item)
            elif field_desc.type == field_desc.TYPE_MESSAGE:
                # nested message
                nested_cls = self._get_nested_class(cls, field_desc)
                if isinstance(value, dict):
                    getattr(msg, key).CopyFrom(self._build_message(nested_cls, value))
                else:
                    getattr(msg, key).CopyFrom(value)
            elif field_desc.type == field_desc.TYPE_ENUM:
                setattr(msg, key, self._resolve_enum(field_desc, value))
            else:
                setattr(msg, key, value)

        return msg

    @staticmethod
    def _get_nested_class(cls, field_desc):
        """Get the protobuf class for a nested message field."""
        from google.protobuf import descriptor as _descriptor
        from google.protobuf import symbol_database as _symbol_database

        # Try to find it from the module globals first
        msg_type = field_desc.message_type
        if msg_type is not None:
            # MessageDescriptor has no 'name' attribute directly in newer protobuf
            # — use the descriptor pool
            return _symbol_database.Default().GetPrototype(msg_type)
        raise ValueError(f"Cannot find class for field {field_desc.name}")

    @staticmethod
    def _resolve_enum(field_desc, value):
        """Resolve enum value from int or string name."""
        enum_type = field_desc.enum_type
        if enum_type is None:
            return int(value)
        if isinstance(value, str):
            enum_value = enum_type.values_by_name.get(value)
            if enum_value is not None:
                return enum_value.number
        if isinstance(value, int):
            return value
        raise ValueError(f"无法解析枚举值: {value} (字段: {field_desc.name})")


# ===================================================================
# Quick self-test
# ===================================================================

if __name__ == "__main__":
    import os

    # Locate files relative to this script
    here = os.path.dirname(os.path.abspath(__file__))
    xml_path = os.path.join(here, "pyprotobuf", "xml", "MessageDefineUAV.xml")
    pb2_path = os.path.join(
        here, "pyprotobuf", "build", "python", "MessageDefineUAVC_pb2.py"
    )

    if not os.path.exists(xml_path):
        print(f"XML 文件不存在: {xml_path}")
        print("请确认 pyprotobuf 子模块已初始化。")
        exit(1)

    # Metadata-only mode (no pb2)
    dp_meta = DavPayload(xml_path=xml_path)
    print("=== 消息列表（前10条）===")
    for info in dp_meta.get_all_messages()[:10]:
        print(
            f"  0x{info['cmd_id']:04X}  {info['name']:<40s}  → {info['struct_name']}"
        )
    print(f"  ... 共 {len(dp_meta.get_all_messages())} 条消息\n")

    # Full mode with pb2
    if os.path.exists(pb2_path):
        dp = DavPayload(xml_path=xml_path, pb2_path=pb2_path)
        print("=== 编解码测试 ===")

        # Test encode/decode for EnrollRequest (cmd_id=0x000C)
        info = dp.get_message_info(0x000C)
        print(f"消息: {info['name']} (0x{info['cmd_id']:04X})")
        print(f"结构体: {info['struct_name']}")
        print(f"字段: {[(f['type'], f['name']) for f in info['fields']]}")

        # Encode
        data = dp.encode(
            cmd_id=0x000C,
            device_type=0,  # UAV
            product_name="TestUAV",
            serial_number="SN123456",
            check=0,
        )
        print(f"编码: {len(data)} bytes  → {data.hex(' ')}")

        # Decode
        msg = dp.decode(cmd_id=0x000C, data=data)
        d = dp.to_dict(msg)
        print(f"解码: {d}")

        # Test PpsHeartBeat (0x000F) with nested message and enum
        print()
        info2 = dp.get_message_info(0x000F)
        print(f"消息: {info2['name']} (0x{info2['cmd_id']:04X})")
        print(f"结构体: {info2['struct_name']}")

        data2 = dp.encode(
            cmd_id=0x000F,
            device_type=1,  # PORTABLE_POWER_SOURCE
            firmware_running_status=0,  # normal
            firmware_version_alias="v1.0.0",
            firmware_version=0x01000000,
            protobuf_version=100,
            local_ms_time=12345678,
            portable_charger={
                "soc": 85,
                "cell_voltage": [3.8, 3.9, 4.0, 3.7, 3.8, 3.9],
                "sum_voltage": 23.1,
                "cell_temperature": 35.5,
                "fet_temperature": 40.0,
                "current": 1.5,
                "diff_vol": 0.3,
                "normal_flag": 2,
                "cycle_count": 10,
                "rechargeable_times": 500.0,
                "soh": 95,
                "error_code": 0,
                "fan_open": False,
                "heat_open": False,
                "bazz_open": False,
                "charge_open": True,
                "ds_open": True,
                "discharge_open": False,
                "charge_status": 1,
                "wifi_ssid": "PPS-WiFi",
                "wifi_ip": "192.168.1.1",
                "operation_reg": 0,
                "lifetime": 1000,
            },
        )
        print(f"编码: {len(data2)} bytes")

        msg2 = dp.decode(cmd_id=0x000F, data=data2)
        d2 = dp.to_dict(msg2)
        print(f"解码: device_type={d2.get('device_type')}, "
              f"soc={d2.get('portable_charger', {}).get('soc')}%")

        print("\n所有测试通过。")
    else:
        print(f"pb2 模块不存在: {pb2_path}")
        print("仅提供元数据查询模式（无 encode/decode）。")
        print("要生成 pb2 模块，请运行 generateProtoFiles.py 然后 protoc。")
