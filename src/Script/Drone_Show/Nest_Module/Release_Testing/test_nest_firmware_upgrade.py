# coding: utf-8
"""
机巢测试 - 固件升级 (TC-NEST-4-02/03/04/05)

业务背景:
    机巢 RK3506 Buildroot 镜像升级路径:
    - 整机镜像 update.img → /userdata/update.img, 调 ota_local_update 重启刷写
    - oem 分区升级 → /userdata/oem.img 同流程
    - 飞机分发固件 → /userdata/play/dmd_uav.bin, 由 gateWay 触发
    - PPS 固件 → ppsManager UDP 14652 (ppsManager 当前是 stub, 见评审 Q2)

    全部依赖 sftp 链路 (TC-NEST-4-01) 与磁盘空间 (TC-NEST-2-05) 作为前置。

设计要点:
    - 完整升级会真实刷写 + reboot, 在 CI 中破坏性大, 默认 SKIP 干跑 (dry-run)
    - 仅验证文件 put 上去 + ls 存在 + 触发命令能下发, 不真 reboot
    - 想做真升级跑回归: --nest-destructive-upgrade=y 开启 (评审 Q3)
    - PPS stub 阶段: 探测 UDP 14652 无响应则 SKIP, 同 TC-NEST-3-06 策略
"""
import os
import tempfile

import pytest
import allure

from utils.logger import log_manager


try:
    from src.Protocol.nest.nest_mavlink import NestMavlinkHelper, FakeGcs, FakeUdpSniffer  # type: ignore
    _NEST_MAVLINK_AVAILABLE = True
except ImportError:
    _NEST_MAVLINK_AVAILABLE = False


DESTRUCTIVE_FLAG = "--nest-destructive-upgrade"


def pytest_addoption(parser):
    parser.addoption(
        DESTRUCTIVE_FLAG,
        action="store_true",
        default=False,
        help="开启真升级 + reboot 流程 (默认 dry-run, 仅 put + 触发命令)",
    )


@pytest.fixture(scope="module")
def destructive_upgrade(request):
    return bool(request.config.getoption(DESTRUCTIVE_FLAG))


@allure.epic("机巢固件测试")
@allure.feature("Release 测试")
@allure.story("固件升级")
class TestNestFirmwareUpgrade:
    """整机镜像 / oem / 飞机分发 / PPS 升级 (TC-NEST-4-02~05)"""


    @allure.title("TC-NEST-4-02 整机镜像 update.img 上传 + 触发本地 OTA (dry-run)")
    @allure.description(
        "[BSP 镜像] sftp put update.img → /userdata/update.img; ls 确认大小匹配; "
        "dry-run 模式只验证 put + ota_local_update 命令存在; 真升级 (--nest-destructive-upgrade) "
        "会 reboot + 等 5 min 后用新镜像 ssh 重连验证 BOOT_DONE 标记。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("机巢", "BSP镜像", "整机升级", "破坏性")
    def test_full_image_upgrade_dry_run(self, sftp_session, ssh_session, test_params, destructive_upgrade):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".img") as tmp:
            tmp.write(os.urandom(64 * 1024))
            local_img = tmp.name
        remote_img = test_params["update_img_path"]
        try:
            with allure.step(f"sftp put 整机镜像 -> {remote_img}"):
                sftp_session.put(local_img, remote_img)
            with allure.step("ls -l 验证远端大小 == 本地"):
                code, out = ssh_session.exec_cmd_quiet(f"ls -l {remote_img}")
                assert code == 0, f"ls 失败: {out!r}"
                assert str(os.path.getsize(local_img)) in out, "镜像大小不匹配"
            with allure.step("检查 ota_local_update 工具存在"):
                code, out = ssh_session.exec_cmd_quiet("which ota_local_update || command -v ota_local_update")
                if code != 0:
                    pytest.skip("机巢无 ota_local_update 工具, 跳过 (评审 Q3)")
            if not destructive_upgrade:
                pytest.skip("dry-run 通过, 真升级需 --nest-destructive-upgrade 开启")
            with allure.step("真升级: 触发 ota_local_update + reboot"):
                ssh_session.exec_cmd_quiet("ota_local_update && reboot", timeout=10)
            with allure.step("等待新镜像启动 + ssh 重连验证"):
                new_ssh = self._wait_boot_done(test_params)
                code, tag = new_ssh.exec_cmd_quiet("cat /userdata/boot_done 2>/dev/null")
                assert code == 0 and tag.strip() == "1", "BOOT_DONE 标记缺失, 升级可能未完成"
        finally:
            try:
                os.unlink(local_img)
            except OSError:
                pass
            # 远端 update.img 必须删: dry-run 留下的随机数据若被 OTA daemon 监听会触发假升级;
            # destructive 模式下 OTA 工具通常会消费此文件, remove 失败也兜底 try/except 忽略。
            try:
                sftp_session.remove(remote_img)
            except Exception as e:
                log_manager.logger.warning(f"清理远端 {remote_img} 失败: {e}")
        log_manager.logger.info("整机镜像升级 OK")


    @allure.title("TC-NEST-4-03 oem 分区镜像升级 (dry-run)")
    @allure.description(
        "[BSP 镜像] sftp put oem.img → /userdata/oem.img, ls 验证; "
        "dry-run 只验 put + 工具存在, 真升级 (--nest-destructive-upgrade) 触发 ota 升 oem 分区。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("机巢", "BSP镜像", "oem升级", "破坏性")
    def test_oem_image_upgrade_dry_run(self, sftp_session, ssh_session, test_params, destructive_upgrade):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".img") as tmp:
            tmp.write(os.urandom(32 * 1024))
            local_oem = tmp.name
        remote_oem = f"{test_params['userdata_path']}/oem.img"
        try:
            with allure.step(f"sftp put oem 镜像 -> {remote_oem}"):
                sftp_session.put(local_oem, remote_oem)
            with allure.step("ls 验证文件存在"):
                code, out = ssh_session.exec_cmd_quiet(f"ls -l {remote_oem}")
                assert code == 0 and remote_oem in out, f"oem 镜像不在远端: {out!r}"
            if not destructive_upgrade:
                pytest.skip("dry-run 通过, 真升级需 --nest-destructive-upgrade")
        finally:
            try:
                os.unlink(local_oem)
            except OSError:
                pass
            try:
                sftp_session.remove(remote_oem)
            except Exception:
                pass
        log_manager.logger.info("oem 升级 dry-run OK")


    @allure.title("TC-NEST-4-04 飞机分发固件 dmd_uav.bin 上传到 play 目录")
    @allure.description(
        "[App 固件] sftp put dmd_uav.bin → /userdata/play/dmd_uav.bin; "
        "gateWay 扫到后通过串口刷到飞机 FC。本用例只验上传链路 + gateWay 扫描日志, "
        "实际 FC 升级由飞机端测试套件覆盖。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("机巢", "App固件", "飞机固件分发")
    def test_uav_firmware_distribute_to_play(self, sftp_session, ssh_session, test_params):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
            tmp.write(os.urandom(128 * 1024))
            local_fc = tmp.name
        remote_fc = f"{test_params['play_path']}/dmd_uav.bin"
        try:
            with allure.step(f"sftp put 飞机固件 -> {remote_fc}"):
                sftp_session.put(local_fc, remote_fc)
            with allure.step("ls 验证文件存在"):
                code, out = ssh_session.exec_cmd_quiet(f"ls -l {remote_fc}")
                assert code == 0, f"ls 失败: {out!r}"
            with allure.step("tail gateWay 日志确认扫描命中"):
                code, log_tail = ssh_session.exec_cmd_quiet(
                    f"tail -50 {test_params['log_path_gateWay']}/gateWay.log 2>/dev/null"
                )
                if code == 0:
                    assert "dmd_uav" in log_tail or "play" in log_tail, (
                        "gateWay 日志未出现扫描记录 (可能未轮询到)"
                    )
        finally:
            try:
                os.unlink(local_fc)
            except OSError:
                pass
            try:
                sftp_session.remove(remote_fc)
            except Exception:
                pass
        log_manager.logger.info("飞机固件分发链路 OK")


    @allure.title("TC-NEST-4-05 PPS 固件升级触发 (ppsManager stub 时 SKIP)")
    @allure.description(
        "[App 固件] ppsManager UDP 14652 探测监听后, 发 PPS_UPGRADE 触发升级; "
        "ppsManager 当前为 stub (ppsManagerEntry.cpp:24), 探测失败 SKIP (评审 Q2)。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("机巢", "App固件", "PPS升级", "stub-skip")
    def test_pps_firmware_upgrade_trigger(self, test_params):
        if not _NEST_MAVLINK_AVAILABLE:
            pytest.skip("nest MAVLink helper 未实现, 本用例 SKIP")
        sniffer = FakeUdpSniffer(local_port=test_params["pps_udp_port"])
        sniffer.start()
        with allure.step("探测 ppsManager 是否实现 (UDP 14652 监听)"):
            if not sniffer.is_port_listening(timeout=1.0):
                pytest.skip("ppsManager 仍为 stub, UDP 14652 未监听 — SKIP (评审 Q2)")
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        with allure.step("发 PPS_UPGRADE 并等 ACK"):
            fake_gcs.send_command("NEST_PPS_UPGRADE", params={"version": "latest"})
            ack = fake_gcs.wait_for_ack(command="NEST_PPS_UPGRADE", timeout=5.0)
            assert ack is not None and ack.result == 0, f"PPS 升级 ACK 失败: {ack}"
        log_manager.logger.info("PPS 升级触发 OK")


    @staticmethod
    def _wait_boot_done(test_params):
        """轮询 ssh 重连, BOOT_DONE 标记出现即返回"""
        import time as _t
        from src.Physical.Nest.nest_remote_helper import NestRemoteHelper
        deadline = _t.time() + 300
        while _t.time() < deadline:
            helper = NestRemoteHelper(
                channel="ssh",
                nest_ip=test_params["nest_ip"],
                ssh_port=test_params["ssh_port"],
                ssh_user=test_params["ssh_user"],
                ssh_passwd=test_params["ssh_passwd"],
            )
            code, _ = helper.exec_cmd_quiet("uname -a", timeout=5)
            if code == 0:
                return helper
            _t.sleep(5)
        pytest.fail(f"OTA 后 300s 内 ssh 仍不可达: {test_params['nest_ip']}")
