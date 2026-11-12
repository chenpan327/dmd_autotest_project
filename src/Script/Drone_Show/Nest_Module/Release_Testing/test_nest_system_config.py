# coding: utf-8
"""
机巢测试 - 串口与系统配置 (TC-NEST-2-01 ~ 06)

业务背景:
    机巢运行 RK3506 Buildroot Linux, 运维同时提供 ssh / 调试串口 / adb 三种等价连接通道,
    本模块覆盖三通道等价性、静态 IP 配置、网络配置读取、进程状态、磁盘剩余、CPU 占用。
    所有用例标 [BSP 镜像], 需完整 OS 镜像运行。

    需求-源码差距: 需求文档列 4 进程 (gateWay/ppsManager/chargeController/vision),
    源码实际只有 3 个 (gateWay/ppsManager/chargeCtrl) — 见评审文档 Q1。
"""
import re
import pytest
import allure

from utils.logger import log_manager


@allure.epic("机巢固件测试")
@allure.feature("Release 测试")
@allure.story("串口与系统配置")
class TestNestSystemConfig:
    """机巢串口与系统配置测试 (TC-NEST-2-01 ~ 06)"""

    @allure.title("TC-NEST-2-01 三通道 (ssh/调试串口/adb) 执行同一命令输出一致")
    @allure.description(
        "[BSP 镜像] ssh / 调试串口 / adb 三通道执行同一命令 (uname -a + os-release), "
        "diff 三路 stdout 必须完全一致; 调试串口要求 115200 8N1, 不回显密码。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("机巢", "BSP镜像", "通道等价")
    def test_three_channel_equivalence(self, ssh_session, console_session, adb_session):
        with allure.step("ssh 通道执行查询命令"):
            ssh_out = ssh_session.exec_cmd("uname -a; cat /etc/os-release 2>/dev/null | head -5")

        with allure.step("调试串口通道执行同一查询"):
            console_out = console_session.exec_cmd("uname -a; cat /etc/os-release 2>/dev/null | head -5")

        with allure.step("adb 通道执行同一查询"):
            adb_out = adb_session.exec_cmd("uname -a; cat /etc/os-release 2>/dev/null | head -5")

        with allure.step("diff 三路输出"):
            assert ssh_out, "ssh 通道无输出"
            assert console_out, "调试串口通道无输出"
            assert adb_out, "adb 通道无输出"
            assert ssh_out.strip() == console_out.strip() == adb_out.strip(), (
                f"三通道输出不一致:\nssh={ssh_out!r}\nconsole={console_out!r}\nadb={adb_out!r}"
            )
        log_manager.logger.info("三通道等价性 OK")


    @allure.title("TC-NEST-2-02 配置静态 IP + 重启后持久化")
    @allure.description(
        "[BSP 镜像] /etc/setIp.sh 设新 IP + 重启后新 IP ssh 可连 + ifconfig eth0 inet == 新 IP; "
        "teardown 由 fixture 兜底还原基线 IP。机巢仅支持静态 IP, 不验证 dhcp 反向。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("机巢", "BSP镜像", "静态IP", "破坏性")
    def test_static_ip_persistent(self, ssh_session, test_params, backup_baseline_ip):
        alternate = test_params["alternate_ip"]
        baseline = backup_baseline_ip
        iface = test_params["eth_iface"]

        with allure.step(f"记录基线 IP={baseline}, 切换到 alternate={alternate}"):
            ssh_session.exec_cmd(f"/etc/setIp.sh {alternate}")
        with allure.step("重启机巢"):
            ssh_session.exec_cmd_quiet("reboot", timeout=5)
        with allure.step("等待机巢重新可达 (轮询新 IP)"):
            new_ssh = self._wait_reachable(alternate, test_params)
        with allure.step("验证新 IP ifconfig"):
            out = new_ssh.exec_cmd(f"ifconfig {iface} | grep 'inet addr' || ifconfig {iface} | grep inet")
            assert alternate in out, f"ifconfig 未出现新 IP {alternate}: {out!r}"
        log_manager.logger.info(f"静态 IP 切换 OK: {baseline} -> {alternate}")


    @allure.title("TC-NEST-2-03 ifconfig 同时出现 eth0 与 lo, 掩码 255.240.0.0, ping GCS 丢包 0%")
    @allure.description(
        "[BSP 镜像] ifconfig 含 eth0 + lo 两块网卡, eth0 掩码 255.240.0.0; "
        "ping -c 3 GCS 丢包率必须 0%。掩码适配表演线, 不通用。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("机巢", "BSP镜像", "网卡", "ping")
    def test_network_interface_and_ping(self, ssh_session, test_params):
        with allure.step("ifconfig 检查 eth0 + lo"):
            out = ssh_session.exec_cmd("ifconfig")
            assert test_params["eth_iface"] in out, f"未找到 {test_params['eth_iface']} 网卡"
            assert "lo" in out, "未找到 lo 网卡"
        with allure.step(f"验证 eth0 掩码 == {test_params['eth_netmask']}"):
            assert test_params["eth_netmask"] in out, (
                f"eth0 掩码非预期 {test_params['eth_netmask']}"
            )
        with allure.step(f"ping GCS {test_params['gcs_local_ip']}"):
            ping_out = ssh_session.exec_cmd(
                f"ping -c 3 -W 2 {test_params['gcs_local_ip']}"
            )
            m = re.search(r"(\d+)% packet loss", ping_out)
            assert m, f"ping 输出无丢包率字段: {ping_out!r}"
            loss = int(m.group(1))
            assert loss == 0, f"GCS ping 丢包 {loss}% > 0%"
        log_manager.logger.info(f"网卡与 ping OK (loss={loss}%)")


    @allure.title("TC-NEST-2-04 三进程 (gateWay/ppsManager/chargeCtrl) 均存活")
    @allure.description(
        "[BSP 镜像] ps 检查机巢应用进程; 源码实际名为 gateWay/ppsManager/chargeCtrl "
        "(需求文档里的 chargeController/vision 在源码中不存在, 见评审 Q1)。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("机巢", "BSP镜像", "进程状态")
    def test_process_status(self, ssh_session, test_params):
        expected = test_params["nest_processes"]
        with allure.step("ps 抓所有机巢应用进程"):
            out = ssh_session.exec_cmd(
                "ps | grep -E '" + "|".join(expected) + "' | grep -v grep"
            )
        with allure.step("逐进程断言存在"):
            for proc in expected:
                assert proc in out, f"进程 {proc} 未在 ps 输出: {out!r}"
        log_manager.logger.info(f"三进程存活 OK: {expected}")


    @allure.title("TC-NEST-2-05 df -h userdata 与 sdcard 可用空间充足")
    @allure.description(
        "[BSP 镜像] /userdata 可用 > 50MB, /mnt/sdcard 可用 > 1GB; "
        "userdata 使用率 > 80% 仅 warning, 不作硬门槛。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("机巢", "BSP镜像", "磁盘")
    def test_disk_free(self, ssh_session, test_params):
        with allure.step("df -h 抓 userdata + sdcard"):
            out = ssh_session.exec_cmd("df -h")
            assert test_params["userdata_path"] in out, f"df 未含 {test_params['userdata_path']}"
            assert "/mnt/sdcard" in out, "df 未含 /mnt/sdcard"
        with allure.step("解析 userdata 可用 MB"):
            ud_avail = self._parse_df_avail_mb(out, test_params["userdata_path"])
            assert ud_avail is not None, f"userdata 行解析失败: {out!r}"
            assert ud_avail >= test_params["df_userdata_min_mb"], (
                f"userdata 可用 {ud_avail}MB < 门槛 {test_params['df_userdata_min_mb']}MB"
            )
        with allure.step("解析 sdcard 可用 GB"):
            sd_avail = self._parse_df_avail_gb(out, "/mnt/sdcard")
            assert sd_avail is not None, f"sdcard 行解析失败: {out!r}"
            assert sd_avail >= test_params["df_sdcard_min_gb"], (
                f"sdcard 可用 {sd_avail}GB < 门槛 {test_params['df_sdcard_min_gb']}GB"
            )
        with allure.step("userdata 使用率 warning 检查"):
            ud_use = self._parse_df_use_percent(out, test_params["userdata_path"])
            if ud_use is not None and ud_use > test_params["disk_usage_warn_percent"]:
                log_manager.logger.warning(
                    f"userdata 使用率 {ud_use}% > {test_params['disk_usage_warn_percent']}% (仅警告)"
                )
        log_manager.logger.info(f"磁盘 OK: userdata={ud_avail}MB sdcard={sd_avail}GB")


    @allure.title("TC-NEST-2-06 top 取三进程 CPU 占用均值 < 80%")
    @allure.description(
        "[BSP 镜像] top -bn1 取 gateWay/ppsManager/chargeCtrl 三进程 %CPU, "
        "各采样 3 次取均值, 任意进程 >= 80% (单核) FAIL。仅取单次快照, 压抗场景见模块七。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("机巢", "BSP镜像", "CPU")
    def test_cpu_usage(self, ssh_session, test_params):
        threshold = test_params["cpu_max_percent"]
        expected = test_params["nest_processes"]
        results = {}
        with allure.step("三进程各采样 3 次 top -bn1"):
            for proc in expected:
                samples = []
                for _ in range(3):
                    out = ssh_session.exec_cmd(
                        f"top -bn1 | grep {proc} | grep -v grep | head -1"
                    )
                    cpu = self._parse_top_cpu_percent(out)
                    if cpu is not None:
                        samples.append(cpu)
                assert samples, f"进程 {proc} top 无可用样本: {out!r}"
                avg = sum(samples) / len(samples)
                results[proc] = avg
        with allure.step("逐进程均值断言"):
            for proc, avg in results.items():
                assert avg < threshold, (
                    f"进程 {proc} CPU 均值 {avg:.1f}% >= 门槛 {threshold}%"
                )
        log_manager.logger.info(f"CPU 占用 OK: {results}")


    @staticmethod
    def _parse_df_avail_mb(df_output: str, path_marker: str):
        for ln in df_output.splitlines():
            if path_marker in ln:
                cols = ln.split()
                for col in cols[3:5]:
                    if col.endswith("M"):
                        try:
                            return float(col[:-1])
                        except ValueError:
                            continue
        return None

    @staticmethod
    def _parse_df_avail_gb(df_output: str, path_marker: str):
        for ln in df_output.splitlines():
            if path_marker in ln:
                cols = ln.split()
                for col in cols[3:5]:
                    if col.endswith(("G", "T")):
                        try:
                            return float(col[:-1])
                        except ValueError:
                            continue
        return None

    @staticmethod
    def _parse_df_use_percent(df_output: str, path_marker: str):
        for ln in df_output.splitlines():
            if path_marker in ln:
                cols = ln.split()
                for col in cols[3:5]:
                    if col.endswith("%"):
                        try:
                            return float(col[:-1])
                        except ValueError:
                            continue
        return None

    @staticmethod
    def _parse_top_cpu_percent(top_line: str):
        if not top_line:
            return None
        cols = top_line.split()
        for col in cols:
            if re.match(r"^\d+(\.\d+)?$", col):
                return float(col)
        return None

    @staticmethod
    def _wait_reachable(ip: str, test_params):
        """轮询新 IP ssh 可达, 最多 120s"""
        import time as _t
        from src.Physical.Nest.nest_remote_helper import NestRemoteHelper
        deadline = _t.time() + 120
        while _t.time() < deadline:
            helper = NestRemoteHelper(
                channel="ssh",
                nest_ip=ip,
                ssh_port=test_params["ssh_port"],
                ssh_user=test_params["ssh_user"],
                ssh_passwd=test_params["ssh_passwd"],
            )
            code, _ = helper.exec_cmd_quiet("uname -a", timeout=5)
            if code == 0:
                return helper
            _t.sleep(3)
        pytest.fail(f"切换 IP 后 120s 内 ssh 仍不可达: {ip}")
