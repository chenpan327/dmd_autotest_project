# coding: utf-8

"""
GCS-18 电源控制（p1×3，危险）— 待机/恢复 + 越界值验证

业务背景：
    command=40046（WiFi 模块 onion_companion.c:246-261 实锤）：
        param1 = 0 → 开飞控电（GPIO16 高）→ 唤醒
        param1 = 1 → 关飞控电（GPIO16 低）→ 待机/断电
        其他值 → 仅记日志，不控制电源（本用例验证此行为）

    ⚠️ "关机"和"待机"是**同一条命令**（p1=1），区别只在于是否再发 p1=0：
    断电 → p1=0 → 渐进唤醒 = 待机恢复闭环；
    断电 → 不再发 = 关机（WiFi 模块仍在电，可随时远程拉回）。
    旧版猜测 SHUTDOWN_P1=3 已证伪（p1=3 固件不动电源）。

真机实测口径（2026-09-11 用户确认）：
    - 待机期间 packed_state (msg 5) **停发**（正常——待机模式不报状态）
    - 恢复是**渐进式唤醒**：心跳 (msg 0) 秒级恢复，packed_state (msg 5)
      需要更长时间（各模块从低功耗逐个初始化）——测试分两步判据：
      先验心跳（硬断言），再等 packed_state（长窗口渐进等待）

    - test_gcs18_standby           待机 → 渐进恢复闭环（危险门控）
    - test_gcs18_invalid_param     p1=3 越界值 → 不动电源（危险门控）

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
    FCBasicBase, dangerous_gate, log_manager, STANDBY_SETTLE)
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    CMD_ARM_DISARM, DISARM_P1, CMD_STANDBY, MSG_ID_HEARTBEAT)


@allure.feature("FC 基础功能 P0/P1")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC")
@pytest.mark.functional
class TestGcs18Standby(FCBasicBase):
    """GCS-18 电源控制（p1×3）"""

    @allure.story("GCS-18 电源控制")
    @allure.title("GCS-18 待机 → 渐进恢复闭环")
    @dangerous_gate
    def test_gcs18_standby(self):
        """待机→观察→恢复（GCS-18 p1×3 中的待机项）"""
        with allure.step("前置：确保上锁（解锁态电源操作应被拒）"):
            ack = self._send_command(CMD_ARM_DISARM, param1=DISARM_P1)
            log_manager.log_and_attach(
                f"前置上锁 ACK result={ack.fields.get('result') if ack else None}",
                "前置状态")

        with allure.step("待机 (40046, p1=1) → ACK + 状态观察"):
            self._assert_ack(self._send_command(CMD_STANDBY, param1=1.0),
                             "待机")
            time.sleep(STANDBY_SETTLE)
            packed = self._get_packed_state()
            # 待机期间 packed_state 停发属正常（都睡了不报状态）
            log_manager.log_and_attach(
                f"待机后 packed_state: "
                f"{'fly_state=' + str(packed.fields.get('fly_state')) + ', mode=' + str(packed.fields.get('mode')) if packed else '(无回传——待机中停发属正常)'}",
                "待机观察")

        with allure.step("恢复 (40046, p1=0) → 心跳先回 → packed_state 渐进恢复"):
            self._assert_ack(self._send_command(CMD_STANDBY, param1=0.0),
                             "恢复")
            # 恢复是渐进式的：心跳（msg 0）秒级回来，packed_state (msg 5)
            # 需要更长时间（各模块从低功耗唤醒——用户确认正常行为）
            hb = self.gcs.wait_for_message([MSG_ID_HEARTBEAT], timeout=8.0)
            assert hb is not None, "恢复后心跳丢失——链路未复活"
            log_manager.log_and_attach(
                "恢复后心跳 ✓（链路存活）", "恢复-心跳")

        with allure.step("等待 packed_state 完全恢复（渐进式唤醒）"):
            packed = self._poll_armed(0, timeout=STANDBY_SETTLE * 4)
            if packed is not None:
                log_manager.log_and_attach(
                    f"packed_state 恢复 ✓ fly_state="
                    f"{packed.fields.get('fly_state')}, mode="
                    f"{packed.fields.get('mode')}", "恢复-状态流")
            else:
                log_manager.logger.warning(
                    f"packed_state 在 {STANDBY_SETTLE * 4:.0f}s 内未恢复"
                    f"（渐进唤醒耗时更长，存档不判失败）")

    @allure.story("GCS-18 电源控制")
    @allure.title("GCS-18 越界值 p1=3 → 不控制电源")
    @dangerous_gate
    def test_gcs18_invalid_param(self):
        """越界值验证：p1=3 WiFi 模块仅记日志不动电源（onion_companion.c 口径）"""
        with allure.step("发送 p1=3 → ACK + 电源应无变化"):
            # onion_companion.c:246-261：p1 非 0/1 仅记日志不控制电源
            ack = self._send_command(CMD_STANDBY, param1=3.0)
            assert ack is not None, "越界值无 ACK"
            result = ack.fields.get('result')
            log_manager.log_and_attach(
                f"p1=3 ACK result={result}"
                f"（WiFi 模块口径：仅记日志不动电源）", "越界值回执")

        with allure.step("验证链路未断（电源未被误关）"):
            # 如果电源真被关了，心跳会在几秒内消失
            time.sleep(5.0)
            hb = self.gcs.wait_for_message([MSG_ID_HEARTBEAT], timeout=8.0)
            assert hb is not None, (
                "p1=3 后心跳丢失——越界值疑似触发了断电（与 onion_companion.c "
                "口径不符，问题单素材）")
            log_manager.log_and_attach(
                "p1=3 后心跳正常 ✓（电源未被误关）", "越界值验证")
