import re
import json
import os


def extract_mavlink_config(source_py_path: str, output_json_path: str = None) -> dict:
    """
    从 MAVLink Python 源文件中提取协议版本信息和消息类的 struct.pack 配置，输出为 JSON。

    Args:
        source_py_path: dmd_uav.py 等 MAVLink 源文件路径
        output_json_path: 可选，输出 JSON 文件路径。为 None 时不写入文件

    Returns:
        dict: 包含以下字段:
            - wire_protocol_version: 协议版本号
            - dialect: 方言名称
            - message_define_version: 消息定义版本号
            - messages: 消息配置列表，每项包含:
                - message_name: 类名
                - struct_format: struct.pack 格式字符串
                - variables: 对应变量名列表 (已去掉 self. 前缀)
    """
    with open(source_py_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 提取全局版本/协议信息
    def _extract_const(name: str) -> str | None:
        m = re.search(rf'^\s*{name}\s*=\s*["\'](.+?)["\']\s*$', content, re.MULTILINE)
        return m.group(1) if m else None

    protocol_version = _extract_const('WIRE_PROTOCOL_VERSION')
    dialect = _extract_const('DIALECT')
    msg_define_version = _extract_const('MESSAGE_DEFINE_VERSION')

    # 提取所有 MAVLINK_MSG_ID_ 常量定义
    msg_id_map = {}
    for m in re.finditer(r'^\s*(MAVLINK_MSG_ID_\w+)\s*=\s*(-?\d+)\s*$', content, re.MULTILINE):
        msg_id_map[m.group(1)] = int(m.group(2))

    # 匹配所有 MAVLink_message 子类
    classes = re.findall(r'class (MAVLink_\w+_message)\(MAVLink_message\):', content)

    messages = []
    for class_name in classes:
        class_start = content.find(f'class {class_name}(MAVLink_message):')
        if class_start == -1:
            continue

        # 截取到下一个类定义之前的范围
        next_class = content.find('class MAVLink_', class_start + len(class_name) + 30)
        class_section = content[class_start:] if next_class == -1 else content[class_start:next_class]

        # 提取 MAVLink_message.pack 中的 crc_extra 和 struct.pack 信息
        pack_match = re.search(
            r"MAVLink_message\.pack\(self,\s*mav,\s*(\d+),\s*struct\.pack\('([^']+)'\s*,\s*([^)]+)\)\)",
            class_section
        )
        if not pack_match:
            continue

        crc_extra = int(pack_match.group(1))
        fmt_str = pack_match.group(2)
        vars_str = pack_match.group(3)

        # 从类名推导 MAVLINK_MSG_ID_ 常量名来查真正的 msg_id
        # MAVLink_heartbeat_message -> MAVLINK_MSG_ID_HEARTBEAT
        name_core = class_name[len('MAVLink_'):-len('_message')].upper()
        msg_id_const = f'MAVLINK_MSG_ID_{name_core}'
        msg_id = msg_id_map.get(msg_id_const)

        # 拆分变量并去掉 self. 前缀
        clean_vars = [v.strip().replace('self.', '') for v in vars_str.split(',')]

        entry = {
            'message_name': class_name,
            'struct_format': fmt_str,
            'variables': clean_vars,
            'crc_extra': crc_extra,
        }
        if msg_id is not None:
            entry['msg_id'] = msg_id

        messages.append(entry)

    result = {
        'wire_protocol_version': protocol_version,
        'dialect': dialect,
        'message_define_version': msg_define_version,
        'messages': messages
    }

    # 可选：写入 JSON 文件
    if output_json_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_json_path)) or '.', exist_ok=True)
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    return result


def extract_mavlink_enums(source_py_path: str, output_json_path: str = None,
                          skip_enum_end: bool = True) -> dict:
    """
    从 MAVLink Python 源文件中提取所有 enums[...] 枚举定义，按枚举名分组。

    源文件中的枚举形如:
        enums['MAV_CMD'][22] = EnumEntry('MAV_CMD_NAV_TAKEOFF', '''...''')

    Args:
        source_py_path: dmd_uav_41.py 等 MAVLink 源文件路径
        output_json_path: 可选，输出 JSON 文件路径。为 None 时不写入文件
        skip_enum_end: 是否跳过形如 XXX_ENUM_END 的哨兵条目，默认 True

    Returns:
        dict: 枚举名 -> { 数值(int): 条目名(str) }
              例如 {"MAV_CMD": {22: "MAV_CMD_NAV_TAKEOFF", ...}, ...}
    """
    with open(source_py_path, 'r', encoding='utf-8') as f:
        content = f.read()

    enums: dict[str, dict[int, str]] = {}

    pattern = re.compile(
        r"^enums\['(\w+)'\]\[(-?\d+)\]\s*=\s*EnumEntry\(\s*['\"]([^'\"]+)['\"]",
        re.MULTILINE,
    )
    for m in pattern.finditer(content):
        enum_name = m.group(1)
        value = int(m.group(2))
        entry_name = m.group(3)

        if skip_enum_end and entry_name.endswith('_ENUM_END'):
            continue

        enums.setdefault(enum_name, {})[value] = entry_name

    # 按枚举值排序，便于阅读
    enums = {name: dict(sorted(items.items())) for name, items in enums.items()}

    if output_json_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_json_path)) or '.', exist_ok=True)
        # JSON 的 key 必须是字符串
        serializable = {name: {str(k): v for k, v in items.items()} for name, items in enums.items()}
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)

    return enums


if __name__ == '__main__':
    # 使用示例
    # source = r'D:\liaoyutao\fake_airplane\dmd_uav.py'
    # output = r'D:\liaoyutao\fake_airplane\mavlink_config.json'

    # config = extract_mavlink_config(source, output)
    # print(f"协议版本: {config['wire_protocol_version']}, 方言: {config['dialect']}")
    # print(f"共提取 {len(config['messages'])} 条消息配置，已保存至 {output}")

    # 提取枚举定义
    enum_source = r'D:\liaoyutao\fake_airplane\mavlink_version\dmd_uav_32.py'
    enum_output = r'D:\liaoyutao\fake_airplane\mavlink_enums_32.json'
    enums = extract_mavlink_enums(enum_source, enum_output)
    total = sum(len(v) for v in enums.values())
    print(f"共提取 {len(enums)} 个枚举类型，{total} 个枚举值，已保存至 {enum_output}")
