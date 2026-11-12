"""
地面站 MAVLink 消息映射工具 V1.0

功能说明：
    解析 DGCS（地面控制站）生成的 MavlinkCommandMessageBuilder.cs 文件，
    结合 MAVLink 协议的 JSON 配置（消息定义与枚举定义），
    构建出 "命令 ID -> MAVLink 消息名 / 消息 ID / MAV_CMD 命令值" 的映射表，
    并输出为 JSON 文件，便于后续协议对接与调试使用。
"""

import re
import json
import os
from pathlib import Path
from typing import Optional


def parse_mavlink_version(filepath: str) -> Optional[str]:
    """从代码中提取 MessageDefineVersion 的值。

    参数:
        filepath (str): 含 MessageDefineVersion 常量定义的 C# 源文件路径
    返回:
        Optional[str]: 提取到的版本号字符串；未匹配到时返回 None
    """

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    pattern = r'public\s+const\s+string\s+MessageDefineVersion\s*=\s*"([^"]+)"'
    match = re.search(pattern, content)

    return match.group(1) if match else None


def parse_mavlink_msg_id(filepath: str) -> dict[str, int]:
    """解析 MavlinkMsgId.cs 文件，获取 "消息名 -> 消息 ID" 的映射。

    参数:
        filepath (str): MavlinkMsgId.cs 文件路径
    返回:
        dict[str, int]: 形如 {消息名: 消息ID} 的字典
    """
    msg_id_map = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 匹配枚举条目，形如：NAME = value,
    pattern = re.compile(r'^\s+(\w+)\s*=\s*(\d+),?', re.MULTILINE)
    for match in pattern.finditer(content):
        name = match.group(1)
        value = int(match.group(2))
        msg_id_map[name] = value

    return msg_id_map


def parse_msg_classes(filepath: str) -> dict[str, str]:
    """解析 dmd_uav.generated.cs 文件，获取 "Msg_xxx 类 -> Serialize_NAME 方法" 的映射。

    参数:
        filepath (str): dmd_uav.generated.cs 文件路径
    返回:
        dict[str, str]: 形如 {Msg_xxx类名: Serialize_NAME方法名} 的字典
    """
    msg_to_serialize = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 查找每一个 Msg_xxx 类及其对应的 Serialize_YYYY 方法
    class_pattern = re.compile(
        r'public class (Msg_\w+)\s*:\s*MavlinkMessage\s*\{[^}]+?'
        r'return MavLinkSerializer\.Serialize_(\w+)\(this',
        re.DOTALL
    )
    for match in class_pattern.finditer(content):
        class_name = match.group(1)
        serialize_name = match.group(2)
        msg_to_serialize[class_name] = serialize_name

    return msg_to_serialize


def parse_builder_cases(
    filepath: str,
    msg_id_map: dict[str, tuple[str, int]],
    cmd_id_map: dict[str, str],
) -> list[dict]:
    """解析 MavlinkCommandMessageBuilder.cs 中的 switch-case 分支，
    提取每个 case 中 new Msg_xxx() 的相关信息。

    参数:
        filepath (str):                          MavlinkCommandMessageBuilder.cs 文件路径
        msg_id_map (dict[str, tuple[str, int]]): 消息名后缀 -> (消息名, 消息ID) 的映射
        cmd_id_map (dict[str, str]):             MAV_CMD 枚举名 -> 数值 的映射
    返回:
        list[dict]: 每个 case 对应的字典列表，包含消息类名、命令 ID、命令枚举等信息
    """
    cases = []
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 提取整个 switch (cmd.Id) {...} 代码块
    switch_match = re.search(
        r'switch \(cmd\.Id\)\s*\{(.*)\}\s*\n\s*return retMsg;',
        content,
        re.DOTALL
    )
    if not switch_match:
        return cases

    switch_body = switch_match.group(1)

    # 按 case 拆分代码块：
    # 一个 case 块以 'case MesgId.Xxx:' 开始，到下一个 'case' 或 'default' 之前结束
    case_pattern = re.compile(
        r'case\s+(MesgId\.\w+)\s*:\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}',
        re.DOTALL
    )

    for match in case_pattern.finditer(switch_body):
        case_name = match.group(1)
        case_body = match.group(2)

        # 在 case 块中查找 new Msg_xxx()，定位实际构造的消息类型
        msg_match = re.search(r'new\s+(Msg_\w+)\s*\(\)', case_body)
        if not msg_match:
            continue

        msg_class = msg_match.group(1)

        # 若 case 中出现 MAV_CMD.XXX，则提取对应的命令枚举名
        mav_cmd_match = re.search(r'MAV_CMD\.(MAV_CMD_\w+)', case_body)
        mav_cmd_enum = mav_cmd_match.group(1) if mav_cmd_match else None

        cases.append({
            'case_name': case_name,
            'msg_class': msg_class,
            'mav_cmd_enum': mav_cmd_enum,
            'case_body': case_body.strip()
        })

    # 依次补全消息 ID 映射和命令 ID 映射
    cases = build_msg_class_to_cmd_id_map(
        build_msg_class_to_msg_id_map(cases, msg_id_map),
        cmd_id_map,
    )

    return cases


def build_msg_class_to_msg_id_map(
    cases: list[dict],
    msg_id_map: dict[str, tuple[str, int]],
) -> list[dict]:
    """为每个 case 补充 MAVLink 消息名（mavMsgName）和消息 ID（mavMsgID）。

    实现方式：取 Msg_ 前缀后的后缀名，到 msg_id_map 中查表。

    参数:
        cases (list[dict]):                      由 parse_builder_cases 生成的 case 字典列表
        msg_id_map (dict[str, tuple[str, int]]): 消息名后缀 -> (消息名, 消息ID) 的映射
    返回:
        list[dict]: 已补充 mavMsgName / mavMsgID 字段的 case 字典列表
    """
    for case in cases:
        if case['msg_class'].startswith('Msg_'):
            # 截掉 "Msg_" 前缀，得到与配置对应的后缀名
            suffix = case['msg_class'].split('Msg_')[1]
            if suffix in msg_id_map:
                message_name, config_msg_id = msg_id_map[suffix]
                case['mavMsgName'] = message_name
                case['mavMsgID'] = config_msg_id
    return cases


def build_msg_class_to_cmd_id_map(
    cases: list[dict],
    cmd_id_map: dict[str, str],
) -> list[dict]:
    """为 COMMAND_LONG（msg_id == 76）类型的 case 补充 MAV_CMD 的详细信息。

    其他消息类型的 commandValue / commandEnum 默认置为 None。

    参数:
        cases (list[dict]):          已包含 mavMsgID 字段的 case 字典列表
        cmd_id_map (dict[str, str]): MAV_CMD 枚举名 -> 数值 的映射
    返回:
        list[dict]: 已补充 commandValue / commandEnum 字段的 case 字典列表
    """
    # 仅当消息 ID 为 76（COMMAND_LONG）时，才需要附加 MAV_CMD 的具体命令值
    for case in cases:
        if case.get('mavMsgID') == 76 and case.get('mav_cmd_enum'):
            cmd_value = cmd_id_map.get(case.get('mav_cmd_enum'))
            case['commandValue'] = cmd_value
            case['commandEnum'] = case.get('mav_cmd_enum')
        else:
            case['commandValue'] = None
            case['commandEnum'] = None
    return cases


def load_mavlink_msg_config(config_path: str) -> dict[str, tuple[str, int]]:
    """加载 mavlink_config_vXX.json，构建 "Msg_ 后缀 -> (消息名, 消息 ID)" 的映射。

    例如：配置中的消息名 MAVLink_heartbeat_message
          经过提取核心名 -> "heartbeat"
          可与代码中的 Msg_heartbeat 进行匹配。

    参数:
        config_path (str): mavlink_config_vXX.json 文件路径
    返回:
        dict[str, tuple[str, int]]: 形如 {核心名: (消息名, 消息ID)} 的字典
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    msg_id_map = {}
    for msg in config.get('messages', []):
        message_name = msg.get('message_name', '')
        msg_id = msg.get('msg_id')
        # 从 message_name 中提取核心名：MAVLink_xxx_message -> xxx
        if message_name.startswith('MAVLink_') and message_name.endswith('_message'):
            core_name = message_name[len('MAVLink_'):-len('_message')]
            msg_id_map[core_name] = (message_name, msg_id)

    return msg_id_map


def load_mavlink_cmd_config(filepath: str) -> dict[str, str]:
    """加载 mavlink_enums_vXX.json，获取 "MAV_CMD 枚举名 -> 数值" 的映射。

    注意：原始配置中是 "数值 -> 枚举名" 的形式，这里需要做一次 key/value 翻转。

    参数:
        filepath (str): mavlink_enums_vXX.json 文件路径
    返回:
        dict[str, str]: 形如 {MAV_CMD 枚举名: 数值字符串} 的字典
    """
    cmd_id_map = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        config = json.load(f)

    mav_cmd_config = config.get('MAV_CMD')
    # 翻转字典：将 {数值: 枚举名} 转为 {枚举名: 数值}
    cmd_id_map = dict(zip(mav_cmd_config.values(), mav_cmd_config.keys()))

    return cmd_id_map


def extract_mavlink_config_DGCS(DGCS_version: str, mavlink_version: str) -> None:
    """主流程：
    1. 加载 MAVLink 消息配置与枚举配置；
    2. 解析 DGCS 的 MavlinkCommandMessageBuilder.cs；
    3. 构建命令列表并输出为 JSON 文件。

    参数:
        DGCS_version (str):   DGCS 版本号字符串，用于拼接输入/输出文件路径
        mavlink_version (str): MAVLink 版本号文件名（形如 dmd_uav_v41.py），
                               其中数字部分将被提取为版本号
    返回:
        None: 结果通过 JSON 文件输出到磁盘
    """

    # ===== 获取当前mavlink版本号 =====
    mavlink_version = mavlink_version.split('_')[-1].split('.')[0]

    # ===== 输入文件路径 =====
    if rename_mavlink_config_DGCS(DGCS_version):
        dgcs_builder_path,dgcs_mavlink_path = rename_mavlink_config_DGCS(DGCS_version)
        mavlink_enums_path = f'file\mavlink_version\mavlink_enums_v{mavlink_version}.json'
        mavlink_config_path = f'file\mavlink_version\mavlink_config_v{mavlink_version}.json'

        # ===== 输出文件路径 =====
        output_path = f'file\dgcs_version\DGCS_message_list_{DGCS_version}.json'

        # 解析 DGCS 的 mavlink 文件，获得当前地面站的Mavlink版本
        dgcs_mavlink_version = parse_mavlink_version(dgcs_mavlink_path)

        # 加载 MAVLink 协议的消息定义和枚举定义，用于后续 ID/名称 映射
        msg_id_map = load_mavlink_msg_config(mavlink_config_path)
        cmd_id_map = load_mavlink_cmd_config(mavlink_enums_path)

        # 解析 DGCS 的 builder 文件，得到每个命令对应的消息与命令信息
        cases = parse_builder_cases(dgcs_builder_path, msg_id_map, cmd_id_map)

        # 组装输出列表，仅保留对外需要的关键字段
        result = {}
        messages = []

        for case in cases:
            msg_name = case.get('mavMsgName')
            msg_id = case.get('mavMsgID')
            commandValue = case.get('commandValue')
            commandEnum = case.get('commandEnum')

            entry = {
                'msg_id': msg_id,
                'message_name': msg_name,
                'commandValue': commandValue,
                'commandEnum': commandEnum,
            }

            messages.append(entry)
        
        result = {
                'DGCS_version': DGCS_version,
                'DGCS_mavlink_version': dgcs_mavlink_version,
                'mavlink_version' : mavlink_version,
                'messages': messages
            }

        # 写入输出文件，保留中文字符（ensure_ascii=False）
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        if dgcs_mavlink_version == mavlink_version:
            return True, dgcs_mavlink_version, mavlink_version
        else:
            return False, dgcs_mavlink_version, mavlink_version
    else:

        return False, dgcs_mavlink_version, mavlink_version


def rename_mavlink_config_DGCS(DGCS_version: str) -> tuple[Path, Path] | bool:
    """重命名 DGCS 相关文件，追加版本号后缀。

    参数:
        DGCS_version (str): DGCS 版本号字符串，用于拼接目标文件名
    返回:
        tuple[Path, Path]: 重命名成功时返回新文件路径的元组
                          (dgcs_builder_path, dgcs_mavlink_path)
        bool: 重命名失败时返回 False
    """
    dgcs_builder_path = Path('file\dgcs_version\MavlinkCommandMessageBuilder.cs')
    dgcs_mavlink_path = Path('file\dgcs_version\dmd_uav_codec.generated.cs')
    new_dgcs_builder_path = Path(f'file\dgcs_version\MavlinkCommandMessageBuilder_{DGCS_version}.cs')
    new_dgcs_mavlink_path = Path(f'file\dgcs_version\dmd_uav_codec.generated_{DGCS_version}.cs')
    try:
        if not dgcs_builder_path.exists() and not dgcs_mavlink_path.exists():
            if new_dgcs_builder_path.exists() and new_dgcs_mavlink_path.exists():
                return new_dgcs_builder_path,new_dgcs_mavlink_path
                raise FileExistsError("目标文件名已存在")
            raise FileNotFoundError("原文件且目标文件名不存在")
            
        dgcs_builder_path.rename(new_dgcs_builder_path)
        dgcs_mavlink_path.rename(new_dgcs_mavlink_path)
        print(f"✅ 已将 {dgcs_builder_path} 重命名为 {new_dgcs_builder_path}")
        print(f"✅ 已将 {dgcs_mavlink_path} 重命名为 {new_dgcs_mavlink_path}")

        return new_dgcs_builder_path,new_dgcs_mavlink_path

    except (FileNotFoundError, FileExistsError, OSError) as e:
        print(f"❌ 重命名失败: {e}")

        return False
    

# if __name__ == '__main__':
    
#     extract_mavlink_config_DGCS('DGCS_3be819d9_4.0.9631.20963', 'file\\mavlink_version\\dmd_uav_41.py')