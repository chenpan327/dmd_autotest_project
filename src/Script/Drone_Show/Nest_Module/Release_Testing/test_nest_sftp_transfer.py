# coding: utf-8
"""
机巢测试 - sftp 文件传输与剧本下发 (TC-NEST-4-01/06)

业务背景:
    机巢应用通过 sftp 接收 GCS 推送的剧本与素材, 落到 /userdata/play/ 后由 gateWay 解析。
    本模块覆盖 sftp 链路基础连通性 (md5 roundtrip) 与小批量剧本下发 (5 个文件)。

设计要点:
    - TC-NEST-4-01 用 NestSftpHelper.verify_roundtrip 做 put→get→md5 三段比对, 一致才算 OK
    - TC-NEST-4-06 模拟 5 个剧本文件 (1 KB 随机), 全部 put 到 play_path, ls 验证存在, teardown 清理
    - 全程 sftp_session + ssh_session 由 conftest 注入, 本文件不藏任何 IP/账号默认值
"""
import os
import tempfile

import pytest
import allure

from utils.logger import log_manager


@allure.epic("机巢固件测试")
@allure.feature("Release 测试")
@allure.story("sftp 文件传输与剧本下发")
class TestNestSftpTransfer:
    """sftp 链路连通性 (TC-NEST-4-01) 与剧本下发 (TC-NEST-4-06)"""


    @allure.title("TC-NEST-4-01 sftp 上传/下载/MD5 roundtrip 一致")
    @allure.description(
        "[BSP 镜像] sftp put 1 MB 随机文件到 /userdata/sftp_roundtrip.bin, "
        "再 get 回本地, md5_local == md5_remote == md5_back 三段一致。"
        "teardown 删除远端残留, 失败也清。NestSftpHelper.verify_roundtrip 已封装。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("机巢", "BSP镜像", "sftp", "MD5")
    def test_sftp_md5_roundtrip(self, sftp_session, ssh_session, test_params):
        remote = f"{test_params['userdata_path']}/sftp_roundtrip.bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
            local = tmp.name
            tmp.write(os.urandom(1024 * 1024))
        try:
            with allure.step(f"verify_roundtrip: {local} -> {remote}"):
                ok = sftp_session.verify_roundtrip(local, remote, ssh_session)
                assert ok, "sftp roundtrip md5 不一致 (链路或磁盘异常)"
        finally:
            os.unlink(local)
            sftp_session.remove(remote)
        log_manager.logger.info("sftp roundtrip OK (1 MB, md5 三段一致)")


    @allure.title("TC-NEST-4-06 剧本批量下发 (5 个文件 sftp put + ls 验证)")
    @allure.description(
        "[App 固件] 模拟 GCS 推送 5 个剧本文件 (play_001.bin ~ play_005.bin, 每个 4 KB 随机), "
        "全部 sftp put 到 /userdata/play/, 远端 ls 必须含全部 5 个文件名。"
        "teardown 逐个 rm 清理 play 目录, 避免污染下一轮测试。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("机巢", "App固件", "sftp", "剧本下发")
    def test_drama_files_push_to_play(self, sftp_session, test_params):
        play_path = test_params["play_path"]
        names = [f"play_{i:03d}.bin" for i in range(1, 6)]
        locals_to_cleanup = []
        remotes_to_cleanup = []
        try:
            with allure.step(f"sftp put 5 个剧本文件到 {play_path}"):
                for name in names:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
                        tmp.write(os.urandom(4096))
                        local = tmp.name
                    locals_to_cleanup.append(local)
                    remote = f"{play_path}/{name}"
                    remotes_to_cleanup.append(remote)
                    sftp_session.put(local, remote)
            with allure.step("远端 ls 验证 5 个剧本全部存在"):
                files = set(sftp_session.list_dir(play_path))
                missing = [n for n in names if n not in files]
                assert not missing, f"剧本下发遗漏: {missing} 不在 {play_path}"
        finally:
            for r in remotes_to_cleanup:
                try:
                    sftp_session.remove(r)
                except Exception as e:
                    log_manager.logger.warning(f"清理 {r} 失败: {e}")
            for p in locals_to_cleanup:
                try:
                    os.unlink(p)
                except OSError:
                    pass
        log_manager.logger.info(f"剧本下发 OK: 5 个文件全部就位 {play_path}")
