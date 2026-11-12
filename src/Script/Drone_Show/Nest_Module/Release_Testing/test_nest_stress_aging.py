# coding: utf-8
"""
机巢测试 - 老化与压力 (TC-NEST-7-01/02/03)

业务背景:
    模块七长时老化场景, 覆盖:
    - MAVLink + Ping 连续 N 轮稳定性 (无内存/句柄泄漏)
    - 充电上下电循环 N 次 (无累积故障)
    - 磁盘 / 任务 / 内存长期监控 (userdata 不爆, 进程不重启)

设计要点:
    - aging_loop_count 来自 config.json (默认 30 轮, 客户现场调高)
    - 单轮失败立即 FAIL, 不掩埋 (避免老化表面通过但底层已挂)
    - 内存采样取 VmRSS, 老化前后对比 drop_max_percent 控制泄漏阈值
    - 老化用例运行时间长, 标 severity=CRITICAL 但 mark 着老化, 单独跑
"""
import re
import time

import pytest
import allure

from utils.logger import log_manager


try:
    from src.Protocol.nest.nest_mavlink import NestMavlinkHelper, FakeGcs, FakeUav  # type: ignore
    _NEST_MAVLINK_AVAILABLE = True
except ImportError:
    _NEST_MAVLINK_AVAILABLE = False


@allure.epic("机巢固件测试")
@allure.feature("Release 测试")
@allure.story("老化与压力")
class TestNestStressAging:
    """MAVLink+Ping / 充电 / 磁盘任务 老化 (TC-NEST-7-01~03)"""


    @allure.title("TC-NEST-7-01 MAVLink 心跳 + Ping 连续 N 轮稳定性")
    @allure.description(
        "[App 固件] 连续 aging_loop_count 轮, 每轮: FakeUAV 发 10 个心跳透传到 FakeGCS, "
        "ssh ping GCS -c 5. 三项门槛: (a) 心跳 100% 收到 (b) ping 丢包 0% (c) gateWay VmRSS "
        "老化前后涨幅 < aging_mem_drop_max_percent。helper 未实现时 SKIP。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("机巢", "App固件", "老化", "MAVLink")
    def test_mavlink_ping_aging(self, test_params, ssh_session):
        if not _NEST_MAVLINK_AVAILABLE:
            pytest.skip("nest MAVLink helper 未实现, 本老化用例 SKIP")
        loops = test_params["aging_loop_count"]
        mem_drop_max = test_params["aging_mem_drop_max_percent"]
        fake_uav = FakeUav(serial_dev=test_params["uart_devs"][0])
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        fake_gcs.start_listening()
        rss_start = self._rss_kb(ssh_session, "gateWay")
        with allure.step(f"老化 {loops} 轮: 10 心跳 + ping -c 5"):
            for i in range(loops):
                seqs = fake_uav.send_heartbeats(count=10, interval=0.1)
                received = fake_gcs.wait_for_messages(timeout=3.0, expected_count=10)
                assert len(received) == 10, f"#{i} 心跳只收到 {len(received)}/10"
                code, ping_out = ssh_session.exec_cmd_quiet(
                    f"ping -c 5 -W 2 {test_params['gcs_local_ip']}"
                )
                m = re.search(r"(\d+)% packet loss", ping_out or "")
                assert m and int(m.group(1)) == 0, f"#{i} ping 丢包: {ping_out!r}"
        rss_end = self._rss_kb(ssh_session, "gateWay")
        with allure.step(f"内存涨幅校验 (start={rss_start}KB end={rss_end}KB)"):
            if rss_start > 0:
                growth = (rss_end - rss_start) * 100.0 / rss_start
                assert growth < mem_drop_max, (
                    f"gateWay VmRSS 涨幅 {growth:.1f}% >= 门槛 {mem_drop_max}% (内存泄漏)"
                )
        log_manager.logger.info(
            f"MAVLink+Ping 老化 OK: {loops} 轮, VmRSS {rss_start}->{rss_end} KB"
        )


    @allure.title("TC-NEST-7-02 充电 on/off 循环 aging_loop_count 次")
    @allure.description(
        "[App 固件] 连续 aging_loop_count 次 on→off→on 循环, 每次 ACK result==0, "
        "老化后查询 chargeCtrl STATUS 无累积 fault 标志。台架缺失时 helper SKIP。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("机巢", "App固件", "老化", "充电")
    def test_charge_cycle_aging(self, test_params):
        if not _NEST_MAVLINK_AVAILABLE:
            pytest.skip("nest MAVLink helper 未实现")
        loops = test_params["aging_loop_count"]
        fake_gcs = FakeGcs(local_port=test_params["gcs_local_port"])
        with allure.step(f"老化 {loops} 轮 on/off"):
            for i in range(loops):
                for action in ("on", "off"):
                    fake_gcs.send_command(
                        "NEST_UAV_CHARGER_CMD", params={"channel": 0, "action": action}
                    )
                    ack = fake_gcs.wait_for_ack(
                        command="NEST_UAV_CHARGER_CMD", timeout=2.0
                    )
                    assert ack is not None and ack.result == 0, (
                        f"#{i} {action} ACK 失败: {ack}"
                    )
        with allure.step("查老化后 STATUS 无累积 fault"):
            status = fake_gcs.wait_for_status(timeout=3.0)
            assert status is not None, "老化后无 STATUS 上报"
            assert not getattr(status, "fault_accumulated", False), (
                f"chargeCtrl 累积 fault 标志: {status}"
            )
        log_manager.logger.info(f"充电循环老化 OK: {loops} 轮, 无累积故障")


    @allure.title("TC-NEST-7-03 长时磁盘/任务/内存监控 (无进程重启 + userdata 不爆)")
    @allure.description(
        "[BSP 镜像] 持续 60s, 每 5s 采样: ps 抓三进程 PID 不变 (无重启), "
        "df userdata 使用率涨幅 < 1% (日志不爆写), free 内存涨幅 < 10%。"
        "本用例是轻量监控, 真正长时 (>1h) 由 CI 单独跑, 此处只验监控链路。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("机巢", "BSP镜像", "老化", "监控")
    def test_disk_task_mem_monitor(self, ssh_session, test_params):
        procs = test_params["nest_processes"]
        pid_start = {}
        ud_start = None
        mem_start = None
        with allure.step("采样初始基线"):
            for p in procs:
                code, out = ssh_session.exec_cmd_quiet(f"pgrep -f {p} | head -1")
                assert code == 0 and out, f"进程 {p} 未找到"
                pid_start[p] = out.strip()
            ud_start = self._userdata_use_percent(ssh_session, test_params)
            mem_start = self._mem_free_kb(ssh_session)
        with allure.step("60s 监控窗口, 每 5s 采样一次"):
            deadline = time.time() + 60
            while time.time() < deadline:
                for p in procs:
                    code, out = ssh_session.exec_cmd_quiet(f"pgrep -f {p} | head -1")
                    assert code == 0 and out.strip() == pid_start[p], (
                        f"进程 {p} 重启了 (start={pid_start[p]} now={out.strip()!r})"
                    )
                time.sleep(5)
        with allure.step("窗口结束再采样并对比"):
            ud_end = self._userdata_use_percent(ssh_session, test_params)
            mem_end = self._mem_free_kb(ssh_session)
            assert (ud_end - ud_start) < 1.0, (
                f"userdata 使用率涨幅 {ud_end - ud_start:.2f}% >= 1% (日志爆写)"
            )
            if mem_start and mem_end:
                drop = (mem_start - mem_end) * 100.0 / mem_start
                assert drop < 10.0, f"free 内存跌 {drop:.1f}% >= 10%"
        log_manager.logger.info(
            f"监控 OK: PID 无变, userdata {ud_start}->{ud_end}%, free {mem_start}->{mem_end} KB"
        )


    @staticmethod
    def _rss_kb(ssh_session, proc: str) -> int:
        code, out = ssh_session.exec_cmd_quiet(
            f"cat /proc/$(pgrep -f {proc} | head -1)/status 2>/dev/null | grep VmRSS"
        )
        m = re.search(r"VmRSS:\s*(\d+)\s*kB", out or "")
        return int(m.group(1)) if m else 0


    @staticmethod
    def _userdata_use_percent(ssh_session, test_params) -> float:
        path = test_params["userdata_path"]
        code, out = ssh_session.exec_cmd_quiet(f"df -h {path}")
        for ln in (out or "").splitlines():
            cols = ln.split()
            for col in cols:
                if col.endswith("%"):
                    try:
                        return float(col[:-1])
                    except ValueError:
                        continue
        return 0.0


    @staticmethod
    def _mem_free_kb(ssh_session) -> int:
        code, out = ssh_session.exec_cmd_quiet("cat /proc/meminfo | grep MemFree")
        m = re.search(r"MemFree:\s*(\d+)\s*kB", out or "")
        return int(m.group(1)) if m else 0
