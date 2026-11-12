# coding: utf-8

"""
GCS-01 连接与在线判断（p0×4）— 心跳接收/在线探测 + 地面站失联注入

业务背景：
    飞机标准心跳（msg 0）真机实测约 5s/条（口径同 liaoyutao
    test_mavlink_heartbeat.py test_01：5.0±0.3s）；heartbeat_dmd(msg 1)
    发送后飞控回 packed_state(5)，确认业务层在线判断链路
    （解析→更新连接状态→回传）。失联注入 = 先 1Hz 心跳确认在线，
    停发 30s 观察 msg6/fs_state 失效上报，恢复心跳后失联标志应清除。

    - test_gcs01_heartbeat_online   双向心跳与在线探测（默认执行）
    - test_gcs01_gcs_lost_inject    停发心跳触发地面站失联（危险门控）

危险用例默认 skip。开启 = 运行前设置环境变量（门控定义在 fc_basic_base.py，
import 时求值，改代码无效）：
    PowerShell: $env:FC_BASIC_ENABLE_DANGEROUS = "1"
    CMD:        set FC_BASIC_ENABLE_DANGEROUS=1
    Git Bash:   FC_BASIC_ENABLE_DANGEROUS=1 python main.py --device_type X1 --test_suites Functional_Testing
"""

import time

import pytest
import allure

from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    FCBasicBase, dangerous_gate, log_manager)
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    MSG_ID_HEARTBEAT, MSG_ID_FAILSAFE)


@allure.feature("FC 基础功能 P0/P1")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC")
@pytest.mark.functional
class TestGcs01Heartbeat(FCBasicBase):
    """GCS-01 心跳与在线判断（p0×4）"""

    @allure.story("GCS-01 心跳与在线判断")
    @allure.title("GCS-01 双向心跳与在线探测")
    def test_gcs01_heartbeat_online(self):
        """心跳接收周期统计 + heartbeat_dmd 在线探测（GCS-01 p0×4）"""
        with allure.step("接收飞机心跳 30s，统计周期（预期约 5s/条）"):
            beats = []
            start = time.time()
            while time.time() - start < 30.0:
                received, addr = self.gcs.receive()
                if (received is not None
                        and received.msg_id == MSG_ID_HEARTBEAT
                        and addr and addr[0] == self.drone_ip):
                    beats.append(time.time())
                time.sleep(0.01)
            assert len(beats) >= 3, (
                f"30s 仅收到 {len(beats)} 条心跳（5s 周期预期约 6 条），链路异常")
            intervals = [b - a for a, b in zip(beats, beats[1:])]
            avg = sum(intervals) / len(intervals)
            log_manager.log_and_attach(
                f"心跳 {len(beats)} 条，平均周期 {avg:.3f}s，"
                f"最小 {min(intervals):.3f}s，最大 {max(intervals):.3f}s，"
                f"全部间隔: {[f'{i:.3f}s' for i in intervals]}",
                "心跳周期统计")
            expected_interval, tolerance = 5.0, 0.3
            assert abs(avg - expected_interval) < tolerance, (
                f"心跳平均周期 {avg:.3f}s 不符合预期 {expected_interval}s"
                f"（±{tolerance}s，口径同 test_mavlink_heartbeat.py）")

        with allure.step("heartbeat_dmd 请求 → packed_state 回传（在线判定）"):
            packed = self._get_packed_state()
            assert packed is not None, (
                "heartbeat_dmd 后未收到 packed_state——业务层未回传状态，"
                "在线判断链路（GCS-01/GCS-02 交界）异常")

    @allure.story("GCS-01 心跳与在线判断")
    @allure.title("GCS-01 停发心跳触发地面站失联")
    @dangerous_gate
    def test_gcs01_gcs_lost_inject(self):
        """停发心跳注入地面站失联 → 恢复（GCS-01 p0 失联检测）"""
        with allure.step("保持 1Hz 心跳 10s（在线基线）"):
            packed = self._get_packed_state()
            assert packed is not None, "在线基线建立失败：无 packed_state"

        with allure.step("停发心跳 30s，观察失效上报"):
            self._clear_recv_buffer()
            fs_reports = []
            start = time.time()
            while time.time() - start < 30.0:
                received, addr = self.gcs.receive()
                if (received is not None and received.msg_id == MSG_ID_FAILSAFE
                        and addr and addr[0] == self.drone_ip):
                    fs_reports.append(received)
                    log_manager.log_and_attach(
                        f"failsafe={received.fields.get('failsafe')}",
                        f"失效上报 #{len(fs_reports)}")
                time.sleep(0.05)
            fs_state = self._cli("fs_state")
            log_manager.log_and_attach(
                f"静默 30s：失效报文 {len(fs_reports)} 条；fs_state:\n{fs_state}",
                "失联观察结果")

        with allure.step("恢复心跳，链路应复活"):
            packed = self._get_packed_state(retries=4)
            assert packed is not None, "恢复心跳后仍无 packed_state，链路未恢复"
            fs_state_after = self._cli("fs_state")
            log_manager.log_and_attach(
                f"恢复后 fs_state（与失联期间对比核对清除逻辑，"
                f"fs_state 输出口径以人工判读为准）:\n{fs_state_after}",
                "恢复观察")
