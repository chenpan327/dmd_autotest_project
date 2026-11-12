#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MAVLink 网络文件传输测试

测试范围:
    - UDP 模式: push / pull / verify / delete
    - 串口模式: push / pull
    - 异常情况: 文件不存在、超时重试

运行方式:
    pytest scripts/test_protocol/test_mavlink_net_file.py -v --tb=short

    # 指定无人机 IP
    pytest scripts/test_protocol/test_mavlink_net_file.py -v \
        --drone-ip 172.17.1.87 --drone-port 14551

    # 指定串口
    pytest scripts/test_protocol/test_mavlink_net_file.py -v \
        --serial-port COM10
"""

import os
import sys
import json
import time
import hashlib

import pytest
import allure


# ============================================================
# 路径配置
# ============================================================

# 项目根目录下的测试文件存放路径
# __file__ -> Release_Testing -> V4 -> Drone_Show -> Script -> src -> project_root
_project_root = os.path.abspath(__file__)
for _ in range(6):
    _project_root = os.path.dirname(_project_root)
_TEST_DATA_DIR = os.path.join(_project_root, "file", "dat_files")


# ============================================================
# 工具函数
# ============================================================

def _md5_hex(filepath):
    h = hashlib.md5()
    with open(filepath, 'rb') as f:
        h.update(f.read())
    return h.hexdigest()


def _make_test_file(size=1024, content=None):
    """在 file/dat_files 下创建测试文件，返回 (路径, 内容, MD5)。"""
    os.makedirs(_TEST_DATA_DIR, exist_ok=True)
    name = f"test_{int(time.time() * 1000000)}.dat"
    filepath = os.path.join(_TEST_DATA_DIR, name)
    if content is not None:
        data = content if isinstance(content, bytes) else content.encode('utf-8')
    else:
        data = os.urandom(size)
    with open(filepath, 'wb') as f:
        f.write(data)
    return filepath, data, hashlib.md5(data).hexdigest()


# Fixtures: drone_ip / drone_port 由 conftest.py 提供（从 config.json 读取）


@pytest.fixture(scope="function")
def serial_port(request):
    config_path = os.path.join(_project_root, "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    # 机型一律以 --device_type 命令行选项为准（main.py 自动携带），
    # config.json 顶层 DeviceType 遗留键已移除
    device = request.config.getoption("--device_type", default="")
    if not device:
        raise KeyError("未指定机型：请通过 --device_type 显式传入（如 --device_type=X1）")
    serial_port_name = config.get(device, {}).get("serial_port")
    if not serial_port_name:
        raise KeyError(f"config.json 的 {device} 节未配置 serial_port")
    return serial_port_name


@pytest.fixture(scope="function")
def remote_dir():
    return "//data/MISSION"


# ============================================================
# UDP 模式测试
# ============================================================

@pytest.mark.functional
@allure.feature("MAVLink 文件传输")
class TestNetFileTransferUdp:
    """UDP 通道文件传输测试"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, drone_ip, drone_port, remote_dir):
        with allure.step("导入依赖模块"):
            from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
            from src.Protocol.airplane.mav_net_file import (
                MAVLink_message, MAVLINK_MSG_ID_NET_FILE_COMMAND,
                NET_FILE_OPEN, NET_FILE_WRITE, NET_FILE_READ,
                NET_FILE_CLOSE, NET_FILE_ACK, NET_FILE_VERIFY, NET_FILE_DELETE,
                NET_FILE_OP_MODE_READ, NET_FILE_OP_MODE_WRITE,
                GCSSimMAVLinkLink,
                net_file_write_file, net_file_read_file,
                net_file_verify_file, net_file_delete_file,
            )
            self.MAVLink_message = MAVLink_message
            self.GroundControlStation = GroundControlStation
            self.GCSSimMAVLinkLink = GCSSimMAVLinkLink
            self.net_file_write_file = net_file_write_file
            self.net_file_read_file = net_file_read_file
            self.net_file_verify_file = net_file_verify_file
            self.net_file_delete_file = net_file_delete_file
            self.NET_FILE_OPEN = NET_FILE_OPEN
            self.NET_FILE_READ = NET_FILE_READ
            self.NET_FILE_ACK = NET_FILE_ACK
            self.MAVLINK_MSG_ID_NET_FILE_COMMAND = MAVLINK_MSG_ID_NET_FILE_COMMAND
            self.NET_FILE_OP_MODE_READ = NET_FILE_OP_MODE_READ

        self.drone_ip = drone_ip
        self.drone_port = drone_port
        self.remote_dir = remote_dir
        self._test_files = []

        with allure.step("初始化 GCS UDP 连接"):
            self.gcs = self.GroundControlStation(drone_ip=drone_ip, drone_port=drone_port)
            self.m_link = self.GCSSimMAVLinkLink(self.gcs)
            self.m_link.SYS_ID = 1
            self.m_link.COMP_ID = 1
            allure.attach(
                f"UDP 绑定 {self.gcs.local_ip}:{self.gcs.local_port} → {drone_ip}:{drone_port}",
                "连接信息"
            )

        yield

        with allure.step("清理测试资源"):
            for f in self._test_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass
            self.gcs.close()

    # ----------------------------------------------------------
    # 辅助方法
    # ----------------------------------------------------------

    def _remote_path(self, name):
        return f"//data/MISSION/{name}"

    def _add_cleanup(self, *paths):
        for p in paths:
            self._test_files.append(p)

    # ----------------------------------------------------------
    # 用例 1: push + pull 完整流程
    # ----------------------------------------------------------

    @allure.story("文件推拉")
    @allure.title("UDP push 后 pull 验证数据一致性")
    @allure.description("推送一个随机文件到无人机，再拉取回来，对比 MD5 确保数据完整")
    def test_push_then_pull(self):
        test_name = f"tnet_{int(time.time()) % 100000}.dat"
        remote_name = self._remote_path(test_name)

        # ---- Step 1: 创建测试文件 ----
        with allure.step("创建随机测试文件 (4KB)"):
            local_src, src_data, src_md5 = _make_test_file(4096)
            self._add_cleanup(local_src)
            allure.attach(f"size={len(src_data)} md5={src_md5}", "源文件信息")

        # ---- Step 2: Push ----
        with allure.step("推送文件到无人机"):
            result = self.net_file_write_file(
                self.m_link, self.m_link, local_src, remote_name
            )
            assert result is True, "push 失败"
            allure.attach(f"push {local_src} → {remote_name} OK", "推送结果")

        # ---- Step 3: Pull ----
        local_dst = os.path.join(_TEST_DATA_DIR, f"pull_{test_name}")
        self._add_cleanup(local_dst)

        with allure.step("从无人机拉取文件"):
            result = self.net_file_read_file(
                self.m_link, self.m_link, local_dst, remote_name
            )
            assert result is True, "pull 失败"
            assert os.path.exists(local_dst), f"拉取文件不存在: {local_dst}"
            dst_size = os.path.getsize(local_dst)
            allure.attach(f"pull {remote_name} → {local_dst} ({dst_size} bytes)", "拉取结果")

        # ---- Step 4: 验证 MD5 ----
        with allure.step("对比源文件和拉取文件的 MD5"):
            dst_md5 = _md5_hex(local_dst)
            assert src_md5 == dst_md5, f"MD5 不匹配: src={src_md5} dst={dst_md5}"
            allure.attach(f"MD5 一致: {src_md5}", "校验结果")

        # ---- Step 5: Validate via verify command ----
        with allure.step("使用 verify 命令校验远端文件"):
            result = self.net_file_verify_file(
                self.m_link, self.m_link, local_src, remote_name, ""
            )
            assert result is True, "verify 失败"
            allure.attach("远端 MD5 校验通过", "校验结果")

        # ---- Step 6: Cleanup remote ----
        with allure.step("删除远端测试文件"):
            result = self.net_file_delete_file(self.m_link, self.m_link, remote_name)
            assert result is True, "delete 失败"
            allure.attach(f"已删除远端文件 {remote_name}", "清理结果")

    # ----------------------------------------------------------
    # 用例 2: pull 不存在的文件
    # ----------------------------------------------------------

    @allure.story("异常处理")
    @allure.title("pull 不存在的文件应返回 False")
    @allure.description("请求一个不存在的远端文件，验证返回 False 而非异常")
    def test_pull_nonexistent_file(self):
        fake_remote = self._remote_path(f"nonexist_{int(time.time()) % 100000}.dat")
        local_dst = os.path.join(_TEST_DATA_DIR, "pull_nonexist.dat")
        self._add_cleanup(local_dst)

        with allure.step("尝试 pull 不存在的远端文件"):
            result = self.net_file_read_file(
                self.m_link, self.m_link, local_dst, fake_remote
            )
            assert result is False, "不存在的文件应返回 False"
            allure.attach(f"正确返回 False: {fake_remote}", "预期结果")

    # ----------------------------------------------------------
    # 用例 3: push 空文件
    # ----------------------------------------------------------

    @allure.story("边界条件")
    @allure.title("push 空文件")
    @allure.description("推送 0 字节文件，验证能正常 push/pull")
    def test_push_empty_file(self):
        test_name = f"tempty_{int(time.time()) % 100000}.dat"
        remote_name = self._remote_path(test_name)

        with allure.step("创建空文件"):
            local_src, src_data, src_md5 = _make_test_file(content=b'')
            self._add_cleanup(local_src)
            assert len(src_data) == 0

        with allure.step("推送空文件"):
            result = self.net_file_write_file(
                self.m_link, self.m_link, local_src, remote_name
            )
            assert result is True, "push 空文件失败"

        local_dst = os.path.join(_TEST_DATA_DIR, f"pull_{test_name}")
        self._add_cleanup(local_dst)

        with allure.step("拉取空文件"):
            result = self.net_file_read_file(
                self.m_link, self.m_link, local_dst, remote_name
            )
            assert result is True, "pull 空文件失败"
            assert os.path.getsize(local_dst) == 0, "拉取的文件不是空文件"

        with allure.step("清理远端"):
            self.net_file_delete_file(self.m_link, self.m_link, remote_name)

    # ----------------------------------------------------------
    # 用例 4: push 大文件 (分块传输)
    # ----------------------------------------------------------

    @allure.story("分块传输")
    @allure.title("push 大文件验证分块写入")
    @allure.description("推送一个较大的文件（需要多次 NET_FILE_WRITE），验证分块传输正确性")
    def test_push_large_file(self):
        test_name = f"tbig_{int(time.time()) % 100000}.dat"
        remote_name = self._remote_path(test_name)

        # 5624 bytes 约需要 24 个 WRITE 块 (每块 240 字节)
        file_size = 5624
        with allure.step(f"创建 {file_size} 字节测试文件"):
            local_src, src_data, src_md5 = _make_test_file(file_size)
            self._add_cleanup(local_src)
            allure.attach(f"size={file_size} md5={src_md5}", "源文件信息")

        with allure.step("推送大文件"):
            result = self.net_file_write_file(
                self.m_link, self.m_link, local_src, remote_name
            )
            assert result is True, f"push {file_size} 字节文件失败"

        local_dst = os.path.join(_TEST_DATA_DIR, f"pull_{test_name}")
        self._add_cleanup(local_dst)

        with allure.step("拉取验证"):
            result = self.net_file_read_file(
                self.m_link, self.m_link, local_dst, remote_name
            )
            assert result is True, "pull 失败"
            dst_md5 = _md5_hex(local_dst)
            assert src_md5 == dst_md5, f"大文件 MD5 不匹配: {src_md5[:16]}... vs {dst_md5[:16]}..."

        with allure.step("清理远端"):
            self.net_file_delete_file(self.m_link, self.m_link, remote_name)

    # ----------------------------------------------------------
    # 用例 5: verify 命令
    # ----------------------------------------------------------

    @allure.story("文件校验")
    @allure.title("verify 校验已存在的文件")
    @allure.description("push 文件后使用 verify 命令对比 MD5，验证校验功能正常")
    def test_verify_file(self):
        test_name = f"tver_{int(time.time()) % 100000}.dat"
        remote_name = self._remote_path(test_name)

        with allure.step("推送测试文件"):
            local_src, src_data, src_md5 = _make_test_file(1024)
            self._add_cleanup(local_src)
            result = self.net_file_write_file(
                self.m_link, self.m_link, local_src, remote_name
            )
            assert result is True, "push 失败"

        with allure.step("verify 远端文件 (传入 MD5 字符串)"):
            result = self.net_file_verify_file(
                self.m_link, self.m_link, "", remote_name, src_md5
            )
            assert result is True, "verify 失败"

        with allure.step("cleanup"):
            self.net_file_delete_file(self.m_link, self.m_link, remote_name)


# ============================================================
# 串口模式测试
# ============================================================

@pytest.mark.functional
@allure.feature("MAVLink 文件传输")
class TestNetFileTransferSerial:
    """串口通道文件传输测试"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, serial_port, remote_dir):
        if not serial_port:
            pytest.skip("未指定 --serial-port，跳过串口测试")

        with allure.step("检查 pyserial"):
            try:
                import serial  # noqa: F401
            except ImportError:
                pytest.skip("pyserial 未安装")

        with allure.step("导入依赖模块"):
            from src.Protocol.airplane.mav_net_file import (
                SerialMAVLinkLink,
                net_file_write_file, net_file_read_file,
                net_file_delete_file,
            )
            self.SerialMAVLinkLink = SerialMAVLinkLink
            self.net_file_write_file = net_file_write_file
            self.net_file_read_file = net_file_read_file
            self.net_file_delete_file = net_file_delete_file

        self.serial_port = serial_port
        self.remote_dir = remote_dir
        self._test_files = []

        with allure.step(f"初始化串口连接 {serial_port}"):
            self.m_link = self.SerialMAVLinkLink(
                port=serial_port,
                baudrate=115200,
                sys_id=0,
                comp_id=0,
            )
            allure.attach(f"串口 {serial_port} 115200bps", "连接信息")

        yield

        with allure.step("清理测试资源"):
            for f in self._test_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass
            self.m_link.close()

    def _remote_path(self, name):
        return f"//data/MISSION/{name}"

    def _add_cleanup(self, *paths):
        for p in paths:
            self._test_files.append(p)

    @pytest.mark.skip(reason="串口测试暂时跳过")
    @allure.story("文件推拉")
    @allure.title("串口 push 后 pull 验证数据一致性")
    @allure.description("通过串口推送文件到无人机，再拉取回来，对比 MD5")
    def test_serial_push_then_pull(self):
        test_name = f"tser_{int(time.time()) % 100000}.dat"
        remote_name = self._remote_path(test_name)

        with allure.step("创建测试文件 (2KB)"):
            local_src, src_data, src_md5 = _make_test_file(2048)
            self._add_cleanup(local_src)
            allure.attach(f"size={len(src_data)} md5={src_md5}", "源文件信息")

        with allure.step("串口推送文件"):
            result = self.net_file_write_file(
                self.m_link, self.m_link, local_src, remote_name
            )
            assert result is True, "串口 push 失败"

        local_dst = os.path.join(_TEST_DATA_DIR, f"spull_{test_name}")
        self._add_cleanup(local_dst)

        with allure.step("串口拉取文件"):
            result = self.net_file_read_file(
                self.m_link, self.m_link, local_dst, remote_name
            )
            assert result is True, "串口 pull 失败"
            dst_md5 = _md5_hex(local_dst)
            assert src_md5 == dst_md5, f"MD5 不匹配: {src_md5} vs {dst_md5}"

        with allure.step("清理远端"):
            self.net_file_delete_file(self.m_link, self.m_link, remote_name)
