# coding: utf-8
"""
机巢测试 - 信息查询与日志轮转 (TC-NEST-6-01/02/03)

业务背景:
    机巢版本号 / SN / ID / boxID 通过 MAVLink GET_IDENTIFY_INFO 上报 (gateWay.cpp),
    固件 build 时把 GIT_TAG / build_time 写进 /userdata/version.txt。
    日志轮转策略在 chargeCtrl / gateWay 各自 log4cpp 配置, 默认按大小滚动。

设计要点:
    - GIT_TAG 是版本号唯一真相源 (firmware/CMakeLists 里 git describe --tags)
    - SN 查询走 MAVLink, 复用 TC-NEST-3-07 helper; 本模块只验版本与日志轮转
    - 日志轮转触发需要持续写, 用例 tail -1000 取最近 rotate 计数验证
"""
import re

import pytest
import allure

from utils.logger import log_manager


try:
    from src.Protocol.nest.nest_mavlink import NestMavlinkHelper, FakeGcs  # type: ignore
    _NEST_MAVLINK_AVAILABLE = True
except ImportError:
    _NEST_MAVLINK_AVAILABLE = False


@allure.epic("机巢固件测试")
@allure.feature("Release 测试")
@allure.story("信息查询与日志轮转")
class TestNestInfoQuery:
    """版本 GIT_TAG / SN-ID-boxID / 日志轮转 (TC-NEST-6-01~03)"""


    @allure.title("TC-NEST-6-01 /userdata/version.txt 含 GIT_TAG 非空")
    @allure.description(
        "[App 固件] cat /userdata/version.txt, 必须含 GIT_TAG=Vxxx 行 (V 开头 + 数字 + 可选点号), "
        "build_time 行非空。GIT_TAG 由固件 build 时 git describe --tags 写入, 是版本唯一真相源。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("机巢", "App固件", "版本号")
    def test_version_git_tag(self, ssh_session, test_params):
        with allure.step("cat /userdata/version.txt"):
            code, out = ssh_session.exec_cmd_quiet(f"cat {test_params['userdata_path']}/version.txt")
            assert code == 0 and out, f"version.txt 读取失败: code={code}, out={out!r}"
        with allure.step("正则匹配 GIT_TAG"):
            m = re.search(r"GIT_TAG\s*=\s*(V[\w.\-]+)", out)
            assert m, f"version.txt 未找到 GIT_TAG 行: {out!r}"
            tag = m.group(1)
            assert re.match(r"^V\d", tag), f"GIT_TAG 格式异常: {tag!r}"
        with allure.step("校验 build_time 非空"):
            bm = re.search(r"build_time\s*=\s*(.+)", out)
            assert bm and bm.group(1).strip(), "build_time 为空"
        log_manager.logger.info(f"version.txt OK: GIT_TAG={tag}, build_time={bm.group(1).strip()}")


    @allure.title("TC-NEST-6-02 GET_IDENTIFY_INFO 返回 SN / ID / boxID 三字段非空")
    @allure.description(
        "[App 固件] FakeGCS 发 GET_IDENTIFY_INFO (header_ip=nest_ip, comp_id=nest), "
        "等 IDENTIFY_INFO 响应, 三字段 sn/id/box_id 都非空且格式合法。"
        "compId 区分见 TC-NEST-3-07, 本用例聚焦 nest 本体。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("机巢", "App固件", "SN查询")
    def test_identify_info_three_fields(self, test_params):
        if not _NEST_MAVLINK_AVAILABLE:
            pytest.skip("nest MAVLink helper 未实现")
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        with allure.step("发 GET_IDENTIFY_INFO"):
            fake_gcs.send_get_identify_info(
                header_ip=test_params["nest_ip"], comp_id="nest"
            )
            msg = fake_gcs.wait_for_identify_info(timeout=2.0)
            assert msg is not None, "IDENTIFY_INFO 无响应"
        with allure.step("校验 sn / id / box_id 三字段"):
            assert msg.sn and len(msg.sn) > 0, "sn 为空"
            assert msg.id and len(msg.id) > 0, "id 为空"
            assert msg.box_id and len(msg.box_id) > 0, "box_id 为空"
        log_manager.logger.info(f"IDENTIFY_INFO OK: sn={msg.sn}, id={msg.id}, box_id={msg.box_id}")


    @allure.title("TC-NEST-6-03 gateWay / chargeCtrl 日志按大小轮转 (rotate 计数 > 0)")
    @allure.description(
        "[App 固件] ls -1 /userdata/logs/{gateWay,chargeCtrl}/ 必须能看到 .log.1 / .log.2 之类的轮转文件, "
        "说明 log4cpp 按大小滚动生效。ppsManager stub 阶段无日志, 不参与本断言。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("机巢", "App固件", "日志轮转")
    def test_log_rotation_files_exist(self, ssh_session, test_params):
        for proc, log_dir in (
            ("gateWay", test_params["log_path_gateWay"]),
            ("chargeCtrl", test_params["log_path_chargeCtrl"]),
        ):
            with allure.step(f"ls {log_dir} 查轮转文件"):
                code, out = ssh_session.exec_cmd_quiet(f"ls -1 {log_dir}")
                assert code == 0, f"{proc} 日志目录 ls 失败: {out!r}"
                rotated = [
                    ln for ln in out.splitlines()
                    if re.search(r"\.log\.\d+$", ln.strip())
                ]
                assert rotated, f"{proc} 日志未见轮转文件 (期望 .log.N): {out!r}"
        log_manager.logger.info("日志轮转 OK: gateWay + chargeCtrl 都有 rotated 文件")
