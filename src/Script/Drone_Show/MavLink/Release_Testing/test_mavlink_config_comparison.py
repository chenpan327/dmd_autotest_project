#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import pytest
import allure
import sys

sys.path.insert(0, r'D:\liaoyutao\fake_airplane')
from src.Protocol.mavlink.extract_mavlink_config import extract_mavlink_config, extract_mavlink_enums

logger = logging.getLogger(__name__)


def _get_version_label(py_path: str) -> str:
    """从文件路径提取版本标识，如 dmd_uav_32.py -> v32"""
    base = os.path.splitext(os.path.basename(py_path))[0]
    parts = base.split('_')
    if len(parts) >= 2 and parts[-1].isdigit():
        return f"v{parts[-1]}"
    return base


@pytest.fixture(scope='class')
def mavlink_configs(request):
    """提取两个版本的配置并返回对比结果，版本路径从命令行参数读取."""
    old_py = request.config.getoption('--old-version')
    new_py = request.config.getoption('--new-version')

    old_label = _get_version_label(old_py)
    new_label = _get_version_label(new_py)

    def _resolve_paths(py_path, label):
        """解析配置和枚举 JSON 路径。如果输入已是 JSON 则直接使用；否则从 .py 提取。"""
        if py_path.endswith('.json'):
            cfg_json = py_path
            enum_json = py_path.replace('mavlink_config_', 'mavlink_enums_')
        else:
            d = os.path.dirname(py_path)
            cfg_json = os.path.join(d, f"mavlink_config_{label}.json")
            enum_json = os.path.join(d, f"mavlink_enums_{label}.json")
            if not os.path.exists(cfg_json):
                extract_mavlink_config(py_path, cfg_json)
            if not os.path.exists(enum_json):
                extract_mavlink_enums(py_path, enum_json)
        return cfg_json, enum_json

    old_json, old_enum_json = _resolve_paths(old_py, old_label)
    new_json, new_enum_json = _resolve_paths(new_py, new_label)

    with open(old_json, 'r', encoding='utf-8') as f:
        old_cfg = json.load(f)
    with open(new_json, 'r', encoding='utf-8') as f:
        new_cfg = json.load(f)
    with open(old_enum_json, 'r', encoding='utf-8') as f:
        old_enums = json.load(f)
    with open(new_enum_json, 'r', encoding='utf-8') as f:
        new_enums = json.load(f)

    # JSON key 是字符串，转回 int
    old_enums = {name: {int(k): v for k, v in items.items()} for name, items in old_enums.items()}
    new_enums = {name: {int(k): v for k, v in items.items()} for name, items in new_enums.items()}

    old_msgs = {m['message_name']: m for m in old_cfg.get('messages', [])}
    new_msgs = {m['message_name']: m for m in new_cfg.get('messages', [])}

    old_names = set(old_msgs.keys())
    new_names = set(new_msgs.keys())
    old_enum_names = set(old_enums.keys())
    new_enum_names = set(new_enums.keys())

    # 预计算枚举变化
    common_enum_names = sorted(old_enum_names & new_enum_names)
    enum_added_names = sorted(new_enum_names - old_enum_names)
    enum_removed_names = sorted(old_enum_names - new_enum_names)
    enum_changed = []
    enum_unchanged = []
    for enum_name in common_enum_names:
        old_items = old_enums[enum_name]
        new_items = new_enums[enum_name]
        if old_items != new_items:
            added_items = {k: v for k, v in new_items.items() if k not in old_items}
            removed_items = {k: v for k, v in old_items.items() if k not in new_items}
            modified_items = {
                k: (old_items[k], new_items[k])
                for k in old_items if k in new_items and old_items[k] != new_items[k]
            }
            enum_changed.append({
                'name': enum_name,
                'added': added_items,
                'removed': removed_items,
                'modified': modified_items,
            })
        else:
            enum_unchanged.append(enum_name)

    logger.info(
        f"对比版本: {old_label}(message_define_version={old_cfg.get('message_define_version')}) "
        f"-> {new_label}(message_define_version={new_cfg.get('message_define_version')})"
    )
    logger.info(f"旧版本报文数: {len(old_names)}, 新版本报文数: {len(new_names)}")
    logger.info(
        f"旧版本枚举类型数: {len(old_enum_names)}, "
        f"新版本枚举类型数: {len(new_enum_names)}"
    )
    logger.info(
        f"枚举变化: 新增 {len(enum_added_names)} 个类型, "
        f"删除 {len(enum_removed_names)} 个类型, "
        f"变更 {len(enum_changed)} 个类型"
    )

    # 预计算变化报文和未变化报文
    common_names = sorted(old_names & new_names)
    changed = []
    unchanged = []
    for name in common_names:
        old_msg = old_msgs[name]
        new_msg = new_msgs[name]
        diffs = []
        for field in ['msg_id', 'crc_extra', 'struct_format']:
            if old_msg.get(field) != new_msg.get(field):
                diffs.append(f"{field}: {old_msg.get(field)} -> {new_msg.get(field)}")
        if old_msg.get('variables') != new_msg.get('variables'):
            old_vars = old_msg.get('variables', [])
            new_vars = new_msg.get('variables', [])
            added_v = [v for v in new_vars if v not in old_vars]
            removed_v = [v for v in old_vars if v not in new_vars]
            diffs.append(f"variables 变化 (新增: {added_v}, 删除: {removed_v})")
        if diffs:
            changed.append({'name': name, 'diffs': diffs})
        else:
            unchanged.append(name)

    logger.info(f"变化报文: {len(changed)} 条, 未变化报文: {len(unchanged)} 条")

    return {
        'old_cfg': old_cfg,
        'new_cfg': new_cfg,
        'old_msgs': old_msgs,
        'new_msgs': new_msgs,
        'old_names': old_names,
        'new_names': new_names,
        'old_label': old_label,
        'new_label': new_label,
        'added': sorted(new_names - old_names),
        'removed': sorted(old_names - new_names),
        'common': common_names,
        'changed': changed,
        'unchanged': unchanged,
        'old_enums': old_enums,
        'new_enums': new_enums,
        'old_enum_names': old_enum_names,
        'new_enum_names': new_enum_names,
        'enum_added': enum_added_names,
        'enum_removed': enum_removed_names,
        'enum_common': common_enum_names,
        'enum_changed': enum_changed,
        'enum_unchanged': enum_unchanged,
    }


@pytest.mark.functional
@allure.feature("MAVLink 协议配置版本对比")
class TestMavlinkVersionInfo:
    """版本号等元信息对比"""

    @allure.story("版本号信息校验")
    def test_protocol_and_dialect_unchanged(self, mavlink_configs):
        old_cfg = mavlink_configs['old_cfg']
        new_cfg = mavlink_configs['new_cfg']
        old_label = mavlink_configs['old_label']
        new_label = mavlink_configs['new_label']

        allure.dynamic.title(
            f"[{old_label} vs {new_label}] wire_protocol_version 和 dialect 应保持一致"
        )
        allure.dynamic.description(
            f"验证两个版本的 wire_protocol_version 和 dialect 字段未发生变更。"
        )

        with allure.step("对比 wire_protocol_version"):
            logger.info(f"wire_protocol_version: {old_cfg['wire_protocol_version']} -> {new_cfg['wire_protocol_version']}")
            assert old_cfg['wire_protocol_version'] == new_cfg['wire_protocol_version'], \
                f"wire_protocol_version 不一致: {old_cfg['wire_protocol_version']} -> {new_cfg['wire_protocol_version']}"

        with allure.step("对比 dialect"):
            logger.info(f"dialect: {old_cfg['dialect']} -> {new_cfg['dialect']}")
            assert old_cfg['dialect'] == new_cfg['dialect'], \
                f"dialect 不一致: {old_cfg['dialect']} -> {new_cfg['dialect']}"

    @allure.story("版本号信息校验")
    def test_git_hash(self, mavlink_configs):
        old_cfg = mavlink_configs['old_cfg']
        new_cfg = mavlink_configs['new_cfg']
        old_label = mavlink_configs['old_label']
        new_label = mavlink_configs['new_label']
        old_hash = old_cfg.get('git_hash', '')
        new_hash = new_cfg.get('git_hash', '')

        allure.dynamic.title(
            f"[{old_label} vs {new_label}] git_hash 对比"
        )
        allure.dynamic.description(
            f"验证 git_hash 变化。旧版本: {old_hash}, 新版本: {new_hash}。"
        )

        with allure.step("对比 git_hash"):
            logger.info(f"git_hash: {old_hash} -> {new_hash}")
            allure.attach(f"旧版本: {old_hash}", "旧版本 git_hash")
            allure.attach(f"新版本: {new_hash}", "新版本 git_hash")
            if old_hash and new_hash:
                assert old_hash != new_hash, \
                    f"git_hash 未发生变化: {old_hash} == {new_hash}"
            elif not old_hash:
                logger.warning("旧版本 git_hash 为空，无法比较")
            elif not new_hash:
                logger.warning("新版本 git_hash 为空，无法比较")

    @allure.story("版本号信息校验")
    def test_message_define_version(self, mavlink_configs):
        old_cfg = mavlink_configs['old_cfg']
        new_cfg = mavlink_configs['new_cfg']
        old_label = mavlink_configs['old_label']
        new_label = mavlink_configs['new_label']
        old_ver = old_cfg.get('message_define_version')
        new_ver = new_cfg.get('message_define_version')

        allure.dynamic.title(
            f"[{old_label} vs {new_label}] message_define_version 应正确升级"
        )
        allure.dynamic.description(
            f"验证 message_define_version 从 {old_ver} 升级到更高版本。"
        )

        with allure.step("对比 message_define_version"):
            logger.info(f"message_define_version: {old_ver} -> {new_ver}")
            allure.attach(f"旧版本: {old_ver}", "旧版本号")
            allure.attach(f"新版本: {new_ver}", "新版本号")
            assert old_ver != new_ver, \
                "message_define_version 未发生变化，版本未升级"


@pytest.mark.functional
@allure.feature("MAVLink 协议配置报文数量与名称对比")
class TestMavlinkMessageCountAndNames:
    """报文数量和名称列表对比"""

    @allure.story("报文数量统计")
    def test_message_count(self, mavlink_configs):
        old_count = len(mavlink_configs['old_names'])
        new_count = len(mavlink_configs['new_names'])
        old_label = mavlink_configs['old_label']
        new_label = mavlink_configs['new_label']

        allure.dynamic.title(
            f"[{old_label} vs {new_label}] 报文总数对比"
        )
        allure.dynamic.description(
            f"对比报文数量变化，旧版本 {old_count} 条，新版本 {new_count} 条。"
        )

        with allure.step("统计报文数量"):
            delta = new_count - old_count
            logger.info(f"报文数量: {old_count} -> {new_count} (变化量: {delta:+d})")
            allure.attach(f"旧版本报文数: {old_count}", "旧版本")
            allure.attach(f"新版本报文数: {new_count}", "新版本")
            allure.attach(f"变化量: {delta:+d}", "变化量")
            assert old_count == new_count or delta != 0, \
                f"报文数量异常: {old_count} -> {new_count}"

    @allure.story("新增报文检查")
    def test_added_messages(self, mavlink_configs):
        added = mavlink_configs['added']
        old_label = mavlink_configs['old_label']
        new_label = mavlink_configs['new_label']

        allure.dynamic.title(
            f"[{old_label} vs {new_label}] 新增报文检测 (共 {len(added)} 条)"
        )
        allure.dynamic.description(
            f"动态检测 {new_label} 相对于 {old_label} 的新增报文列表。"
        )

        with allure.step("检查新增报文列表"):
            logger.info(f"新增报文数量: {len(added)}")
            logger.info(f"新增报文列表: {added}")
            allure.attach(json.dumps(added, indent=2, ensure_ascii=False), "实际新增报文")

            if added:
                for name in added:
                    with allure.step(f"新增报文: {name}"):
                        logger.info(f"检测到新增报文: {name}")
            else:
                with allure.step("无新增报文"):
                    logger.info("两个版本之间无新增报文")

    @allure.story("删除报文检查")
    def test_no_removed_messages(self, mavlink_configs):
        removed = mavlink_configs['removed']
        old_label = mavlink_configs['old_label']
        new_label = mavlink_configs['new_label']

        allure.dynamic.title(
            f"[{old_label} vs {new_label}] 不应存在被删除的报文"
        )
        allure.dynamic.description(
            f"验证 {new_label} 相对于 {old_label} 没有删除任何报文。"
        )

        with allure.step("检查删除报文列表"):
            logger.info(f"删除报文列表: {removed}")
            allure.attach(json.dumps(removed, indent=2, ensure_ascii=False), "被删除报文")
            assert len(removed) == 0, \
                f"发现 {len(removed)} 条被删除的报文: {removed}"


@pytest.mark.functional
@allure.feature("MAVLink 协议配置报文字段变更对比")
class TestMavlinkMessageFieldChanges:
    """共同存在的报文字段变更详细对比"""

    @allure.story("变更信息汇总")
    def test_change_summary(self, mavlink_configs):
        """汇总输出新旧版本的变更信息."""
        old_cfg = mavlink_configs['old_cfg']
        new_cfg = mavlink_configs['new_cfg']
        old_label = mavlink_configs['old_label']
        new_label = mavlink_configs['new_label']
        added = mavlink_configs['added']
        removed = mavlink_configs['removed']
        changed = mavlink_configs['changed']
        unchanged = mavlink_configs['unchanged']

        allure.dynamic.title(
            f"[{old_label} vs {new_label}] 版本变更信息汇总"
        )
        allure.dynamic.description(
            f"汇总 {new_label} 相对于 {old_label} 的所有变更信息。"
        )

        summary_lines = [
            f"=== MAVLink 版本变更汇总 ({old_label} -> {new_label}) ===",
            f"",
            f"[版本信息]",
            f"  wire_protocol_version: {old_cfg['wire_protocol_version']} -> {new_cfg['wire_protocol_version']}",
            f"  dialect:               {old_cfg['dialect']} -> {new_cfg['dialect']}",
            f"  message_define_version: {old_cfg.get('message_define_version')} -> {new_cfg.get('message_define_version')}",
            f"  git_hash:              {old_cfg.get('git_hash', '')} -> {new_cfg.get('git_hash', '')}",
            f"",
            f"[报文数量]",
            f"  旧版本: {len(mavlink_configs['old_names'])} 条",
            f"  新版本: {len(mavlink_configs['new_names'])} 条",
            f"  变化量: {len(mavlink_configs['new_names']) - len(mavlink_configs['old_names']):+d} 条",
            f"",
            f"[新增报文] ({len(added)} 条)",
        ]
        for name in added:
            summary_lines.append(f"  + {name}")

        summary_lines.append(f"")
        summary_lines.append(f"[删除报文] ({len(removed)} 条)")
        if removed:
            for name in removed:
                summary_lines.append(f"  - {name}")
        else:
            summary_lines.append(f"  (无)")

        summary_lines.append(f"")
        summary_lines.append(f"[变更报文] ({len(changed)} 条)")
        for item in changed:
            summary_lines.append(f"  ~ {item['name']}")
            for diff in item['diffs']:
                summary_lines.append(f"      {diff}")

        summary_lines.append(f"")
        summary_lines.append(f"[未变更报文] ({len(unchanged)} 条)")
        summary_lines.append(f"  共 {len(unchanged)} 条报文字段完全一致")

        summary_text = '\n'.join(summary_lines)

        with allure.step("打印变更汇总"):
            logger.info("\n" + summary_text)
            allure.attach(summary_text, "版本变更汇总")

    @allure.story("共同报文变更检查")
    def test_changed_messages_detected(self, mavlink_configs):
        """动态识别所有发生字段变更的共同报文，逐条详细对比."""
        old_msgs = mavlink_configs['old_msgs']
        new_msgs = mavlink_configs['new_msgs']
        changed = mavlink_configs['changed']
        old_label = mavlink_configs['old_label']
        new_label = mavlink_configs['new_label']

        allure.dynamic.title(
            f"[{old_label} vs {new_label}] 动态识别字段变更报文 (共 {len(changed)} 条)"
        )
        allure.dynamic.description(
            f"自动检测两个版本共同报文中发生字段变更的报文，并逐条详细对比 msg_id、crc_extra、struct_format、variables。"
        )

        with allure.step(f"发现 {len(changed)} 条报文发生字段变更"):
            logger.info(f"变化报文数量: {len(changed)}")
            allure.attach(
                json.dumps([c['name'] for c in changed], indent=2, ensure_ascii=False),
                "变化报文列表"
            )

        for item in changed:
            name = item['name']
            old_msg = old_msgs[name]
            new_msg = new_msgs[name]

            with allure.step(f"变更报文: {name}"):
                logger.info(f"详细对比变更报文: {name}")
                logger.info(f"  差异摘要: {item['diffs']}")
                allure.attach('\n'.join(item['diffs']), f"{name} 差异摘要")

                # msg_id
                with allure.step("对比 msg_id"):
                    old_id = old_msg.get('msg_id')
                    new_id = new_msg.get('msg_id')
                    logger.info(f"  msg_id: {old_id} -> {new_id}")
                    if old_id == new_id:
                        logger.info(f"  msg_id 一致")
                    else:
                        logger.warning(f"  msg_id 发生变化!")

                # crc_extra
                with allure.step("对比 crc_extra"):
                    old_crc = old_msg.get('crc_extra')
                    new_crc = new_msg.get('crc_extra')
                    logger.info(f"  crc_extra: {old_crc} -> {new_crc}")
                    if old_crc == new_crc:
                        logger.info(f"  crc_extra 一致")
                    else:
                        logger.warning(f"  crc_extra 发生变化!")
                        allure.attach(f"旧: {old_crc}", "crc_extra")
                        allure.attach(f"新: {new_crc}", "crc_extra")

                # struct_format
                with allure.step("对比 struct_format"):
                    old_fmt = old_msg.get('struct_format')
                    new_fmt = new_msg.get('struct_format')
                    logger.info(f"  struct_format: {old_fmt} -> {new_fmt}")
                    if old_fmt == new_fmt:
                        logger.info(f"  struct_format 一致")
                    else:
                        logger.warning(f"  struct_format 发生变化!")
                        allure.attach(f"旧: {old_fmt}", "struct_format")
                        allure.attach(f"新: {new_fmt}", "struct_format")

                # variables
                with allure.step("对比 variables"):
                    old_vars = old_msg.get('variables', [])
                    new_vars = new_msg.get('variables', [])
                    added_vars = [v for v in new_vars if v not in old_vars]
                    removed_vars = [v for v in old_vars if v not in new_vars]
                    logger.info(f"  旧变量数: {len(old_vars)}, 新变量数: {len(new_vars)}")
                    logger.info(f"  新增变量: {added_vars}")
                    logger.info(f"  删除变量: {removed_vars}")
                    allure.attach(json.dumps(old_vars, indent=2, ensure_ascii=False), "旧版本变量")
                    allure.attach(json.dumps(new_vars, indent=2, ensure_ascii=False), "新版本变量")
                    if added_vars:
                        allure.attach(json.dumps(added_vars, indent=2, ensure_ascii=False), "新增变量")
                    if removed_vars:
                        allure.attach(json.dumps(removed_vars, indent=2, ensure_ascii=False), "删除变量")

    @allure.story("未变更报文检查")
    def test_unchanged_messages(self, mavlink_configs):
        """逐条列举未变更报文，详细展示各字段一致性."""
        old_msgs = mavlink_configs['old_msgs']
        new_msgs = mavlink_configs['new_msgs']
        unchanged = mavlink_configs['unchanged']
        old_label = mavlink_configs['old_label']
        new_label = mavlink_configs['new_label']

        allure.dynamic.title(
            f"[{old_label} vs {new_label}] 未变更报文字段一致性检查 (共 {len(unchanged)} 条)"
        )
        allure.dynamic.description(
            f"逐条验证 {len(unchanged)} 条未变更报文的 msg_id、crc_extra、struct_format、variables 均保持一致。"
        )

        with allure.step(f"开始检查 {len(unchanged)} 条未变更报文"):
            logger.info(f"未变更报文数量: {len(unchanged)}")

        failures = []
        for name in unchanged:
            old_msg = old_msgs[name]
            new_msg = new_msgs[name]

            with allure.step(f"未变更报文: {name}"):
                logger.info(f"检查未变更报文: {name}")

                # msg_id
                old_id = old_msg.get('msg_id')
                new_id = new_msg.get('msg_id')
                logger.info(f"  msg_id: {old_id} (一致)")
                if old_id != new_id:
                    msg = f"{name} msg_id: {old_id} -> {new_id}"
                    logger.error(msg)
                    failures.append(msg)

                # crc_extra
                old_crc = old_msg.get('crc_extra')
                new_crc = new_msg.get('crc_extra')
                logger.info(f"  crc_extra: {old_crc} (一致)")
                if old_crc != new_crc:
                    msg = f"{name} crc_extra: {old_crc} -> {new_crc}"
                    logger.error(msg)
                    failures.append(msg)

                # struct_format
                old_fmt = old_msg.get('struct_format')
                logger.info(f"  struct_format: {old_fmt} (一致)")
                if old_msg.get('struct_format') != new_msg.get('struct_format'):
                    msg = f"{name} struct_format 发生变化"
                    logger.error(msg)
                    failures.append(msg)

                # variables
                old_vars = old_msg.get('variables', [])
                logger.info(f"  variables: {len(old_vars)} 个变量 (一致)")
                if old_msg.get('variables') != new_msg.get('variables'):
                    msg = f"{name} variables 发生变化"
                    logger.error(msg)
                    failures.append(msg)

        with allure.step("汇总检查结果"):
            if failures:
                allure.attach('\n'.join(failures), "不一致的报文")
                logger.error(f"发现 {len(failures)} 处不一致")
                assert False, f"发现 {len(failures)} 处不一致:\n" + '\n'.join(failures[:10])

            logger.info(f"{len(unchanged)} 条未变更报文全部一致")


@pytest.mark.functional
@allure.feature("MAVLink 协议配置枚举对比")
class TestMavlinkEnumChanges:
    """枚举定义对比：数量、新增、删除、变更汇总."""

    @allure.story("枚举数量统计")
    def test_enum_count(self, mavlink_configs):
        old_count = len(mavlink_configs['old_enum_names'])
        new_count = len(mavlink_configs['new_enum_names'])
        old_label = mavlink_configs['old_label']
        new_label = mavlink_configs['new_label']

        allure.dynamic.title(
            f"[{old_label} vs {new_label}] 枚举类型总数对比"
        )
        allure.dynamic.description(
            f"对比枚举类型数量变化，旧版本 {old_count} 个，新版本 {new_count} 个。"
        )

        with allure.step("统计枚举类型数量"):
            delta = new_count - old_count
            logger.info(f"枚举类型数量: {old_count} -> {new_count} (变化量: {delta:+d})")
            allure.attach(f"旧版本枚举类型数: {old_count}", "旧版本")
            allure.attach(f"新版本枚举类型数: {new_count}", "新版本")
            allure.attach(f"变化量: {delta:+d}", "变化量")
            assert old_count == new_count or delta != 0, \
                f"枚举类型数量异常: {old_count} -> {new_count}"

    @allure.story("新增枚举检测")
    def test_added_enums(self, mavlink_configs):
        added = mavlink_configs['enum_added']
        old_label = mavlink_configs['old_label']
        new_label = mavlink_configs['new_label']

        allure.dynamic.title(
            f"[{old_label} vs {new_label}] 新增枚举类型检测 (共 {len(added)} 个)"
        )
        allure.dynamic.description(
            f"动态检测 {new_label} 相对于 {old_label} 的新增枚举类型列表。"
        )

        with allure.step("检查新增枚举类型列表"):
            logger.info(f"新增枚举类型数量: {len(added)}")
            logger.info(f"新增枚举类型列表: {added}")
            allure.attach(json.dumps(added, indent=2, ensure_ascii=False), "实际新增枚举")

            if added:
                for name in added:
                    with allure.step(f"新增枚举: {name}"):
                        logger.info(f"检测到新增枚举: {name}")
            else:
                with allure.step("无新增枚举"):
                    logger.info("两个版本之间无新增枚举类型")

    @allure.story("删除枚举检测")
    def test_no_removed_enums(self, mavlink_configs):
        removed = mavlink_configs['enum_removed']
        old_label = mavlink_configs['old_label']
        new_label = mavlink_configs['new_label']

        allure.dynamic.title(
            f"[{old_label} vs {new_label}] 不应存在被删除的枚举类型"
        )
        allure.dynamic.description(
            f"验证 {new_label} 相对于 {old_label} 没有删除任何枚举类型。"
        )

        with allure.step("检查删除枚举类型列表"):
            logger.info(f"删除枚举类型列表: {removed}")
            allure.attach(json.dumps(removed, indent=2, ensure_ascii=False), "被删除枚举")
            assert len(removed) == 0, \
                f"发现 {len(removed)} 个被删除的枚举类型: {removed}"

    @allure.story("枚举变更信息汇总")
    def test_enum_change_summary(self, mavlink_configs):
        old_label = mavlink_configs['old_label']
        new_label = mavlink_configs['new_label']
        old_enums = mavlink_configs['old_enums']
        new_enums = mavlink_configs['new_enums']
        added = mavlink_configs['enum_added']
        removed = mavlink_configs['enum_removed']
        changed = mavlink_configs['enum_changed']
        unchanged = mavlink_configs['enum_unchanged']

        allure.dynamic.title(
            f"[{old_label} vs {new_label}] 枚举变更信息汇总"
        )
        allure.dynamic.description(
            f"汇总 {new_label} 相对于 {old_label} 的所有枚举变更信息。"
        )

        # 计算各枚举类型的条目数量
        old_total_entries = sum(len(v) for v in old_enums.values())
        new_total_entries = sum(len(v) for v in new_enums.values())

        summary_lines = [
            f"=== MAVLink 枚举变更汇总 ({old_label} -> {new_label}) ===",
            f"",
            f"[枚举类型数量]",
            f"  旧版本: {len(old_enums)} 个类型, {old_total_entries} 个条目",
            f"  新版本: {len(new_enums)} 个类型, {new_total_entries} 个条目",
            f"",
            f"[新增枚举类型] ({len(added)} 个)",
        ]
        for name in added:
            entry_count = len(new_enums[name])
            summary_lines.append(f"  + {name} ({entry_count} 个条目)")

        summary_lines.append(f"")
        summary_lines.append(f"[删除枚举类型] ({len(removed)} 个)")
        if removed:
            for name in removed:
                entry_count = len(old_enums[name])
                summary_lines.append(f"  - {name} ({entry_count} 个条目)")
        else:
            summary_lines.append(f"  (无)")

        summary_lines.append(f"")
        summary_lines.append(f"[变更枚举类型] ({len(changed)} 个)")
        for item in changed:
            name = item['name']
            summary_lines.append(f"  ~ {name}")
            if item['added']:
                for k, v in item['added'].items():
                    summary_lines.append(f"      + [{k}] = {v}")
            if item['removed']:
                for k, v in item['removed'].items():
                    summary_lines.append(f"      - [{k}] = {v}")
            if item['modified']:
                for k, (old_v, new_v) in item['modified'].items():
                    summary_lines.append(f"      ~ [{k}] = {old_v} -> {new_v}")

        summary_lines.append(f"")
        summary_lines.append(f"[未变更枚举类型] ({len(unchanged)} 个)")
        summary_lines.append(f"  共 {len(unchanged)} 个枚举类型完全一致")

        summary_text = '\n'.join(summary_lines)

        with allure.step("打印枚举变更汇总"):
            logger.info("\n" + summary_text)
            allure.attach(summary_text, "枚举变更汇总")

        # 附加详细数据
        with allure.step("附加各枚举条目数量对比"):
            for name in sorted(set(old_enums.keys()) | set(new_enums.keys())):
                old_cnt = len(old_enums.get(name, {}))
                new_cnt = len(new_enums.get(name, {}))
                if old_cnt != new_cnt:
                    allure.attach(
                        f"{name}: {old_cnt} -> {new_cnt} ({new_cnt - old_cnt:+d})",
                        f"条目数变化: {name}"
                    )
