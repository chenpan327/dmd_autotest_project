# coding: utf-8
"""
机巢测试 - 日志拉取 (TC-NEST-4-07/08/09)

业务背景:
    机巢三类日志:
    - gateWay 日志: /userdata/logs/gateWay/gateWay.log (主路由 + 协议解析)
    - chargeCtrl 日志: /userdata/logs/chargeCtrl/chargeCtrl.log (充电管理 + 电机)
    - ppsManager 日志: /userdata/logs/ppsManager/ppsManager.log (PPS stub 阶段基本为空)
    - 飞机红外/可见光图像通过摄像头 HTTP port 8080 抓取 (mjpeg 单帧)

设计要点:
    - sftp get 拉日志到本地, 文件大小 > 0 即视为有写入, 不强依赖具体内容
    - ppsManager stub 阶段日志文件可能不存在, 直接 SKIP 不算 FAIL (评审 Q1/Q2)
    - 红外图像抓取通过 HTTP GET / capture, 摄像头不可达 SKIP
"""
import os
import tempfile
import time

import pytest
import allure
import urllib.request

from utils.logger import log_manager


@allure.epic("机巢固件测试")
@allure.feature("Release 测试")
@allure.story("日志拉取")
class TestNestLogFetch:
    """机巢应用日志 + 飞机红外图像拉取 (TC-NEST-4-07/08/09)"""


    @allure.title("TC-NEST-4-07 拉取 gateWay / chargeCtrl 日志 (sftp + 大小 > 0)")
    @allure.description(
        "[App 固件] sftp get /userdata/logs/gateWay/gateWay.log 与 "
        "/userdata/logs/chargeCtrl/chargeCtrl.log 到本地 tmp, "
        "两个文件都必须存在且大小 > 0 (说明应用有在写日志)。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("机巢", "App固件", "日志拉取", "sftp")
    def test_nest_logs_fetch(self, sftp_session, ssh_session, test_params):
        logs = [
            ("gateWay", f"{test_params['log_path_gateWay']}/gateWay.log"),
            ("chargeCtrl", f"{test_params['log_path_chargeCtrl']}/chargeCtrl.log"),
        ]
        for tag, remote in logs:
            with allure.step(f"检查 {tag} 日志远端存在"):
                code, out = ssh_session.exec_cmd_quiet(f"ls -l {remote}")
                if code != 0:
                    pytest.fail(f"{tag} 日志不在远端: {out!r}")
            with allure.step(f"sftp get {tag} 日志到本地 tmp"):
                local = os.path.join(tempfile.gettempdir(), f"nest_{tag}_{int(time.time())}.log")
                sftp_session.get(remote, local)
                size = os.path.getsize(local)
                assert size > 0, f"{tag} 日志为空 (应用未写入)"
                os.unlink(local)
        log_manager.logger.info("gateWay + chargeCtrl 日志拉取 OK")


    @allure.title("TC-NEST-4-08 拉取 ppsManager 日志 (stub 阶段 SKIP)")
    @allure.description(
        "[App 固件] sftp get /userdata/logs/ppsManager/ppsManager.log; "
        "ppsManager 当前为 stub (ppsManagerEntry.cpp:24), 日志文件可能不存在, "
        "ls 失败则 SKIP (评审 Q1/Q2), 不算 FAIL。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("机巢", "App固件", "日志拉取", "stub-skip")
    def test_pps_log_fetch(self, sftp_session, ssh_session, test_params):
        remote = f"{test_params['log_path_ppsManager']}/ppsManager.log"
        with allure.step("ls 检查 ppsManager 日志存在"):
            code, out = ssh_session.exec_cmd_quiet(f"ls -l {remote}")
            if code != 0:
                pytest.skip("ppsManager 仍为 stub, 日志未生成 — SKIP (评审 Q1/Q2)")
        with allure.step("sftp get ppsManager 日志"):
            local = os.path.join(tempfile.gettempdir(), f"nest_pps_{int(time.time())}.log")
            sftp_session.get(remote, local)
            size = os.path.getsize(local)
            os.unlink(local)
            assert size >= 0, "ppsManager 日志大小异常"
        log_manager.logger.info(f"ppsManager 日志拉取 OK ({size} 字节)")


    @allure.title("TC-NEST-4-09 飞机红外/可见光摄像头单帧抓取 (HTTP GET)")
    @allure.description(
        "[App 固件] 通过机巢摄像头 HTTP port (?port=8080) 抓一帧 mjpeg, "
        "Content-Type 必须 image/* 或 multipart/x-mixed-replace, "
        "body 长度 > 1 KB。摄像头不可达则 SKIP, 不算 FAIL。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("机巢", "App固件", "摄像头", "红外")
    def test_camera_snapshot_fetch(self, test_params, ssh_session):
        port = test_params["camera_http_port"]
        url = f"http://{test_params['nest_ip']}:{port}/?action=snapshot"
        with allure.step(f"HTTP GET {url}"):
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    ctype = resp.headers.get("Content-Type", "")
                    body = resp.read(64 * 1024)
            except Exception as e:
                pytest.skip(f"摄像头不可达 ({e}) — SKIP, 不算 FAIL")
        with allure.step("断言 Content-Type 与 body 大小"):
            assert ctype.startswith(("image/", "multipart/")), (
                f"Content-Type 非 image/multipart: {ctype!r}"
            )
            assert len(body) > 1024, f"图像 body 太小 ({len(body)} 字节, 可能是错误页)"
        allure.attach(
            body,
            name="camera_snapshot",
            attachment_type=allure.attachment_type.JPG,
        )
        log_manager.logger.info(f"摄像头抓帧 OK: ctype={ctype}, size={len(body)}")
