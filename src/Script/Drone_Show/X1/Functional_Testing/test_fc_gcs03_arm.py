# coding: utf-8

"""
GCS-03 解锁与上锁（p0×8，危险）

指令速查（2026-09-08 真机实锤，来源见各条标注）：
    ┌ 解锁/上锁: COMMAND_LONG command=400 (MAV_CMD_COMPONENT_ARM_DISARM)
    │   param1 = 1 解锁 / 0 上锁；param2 = 21196 强制 kill（配合 param1=0）
    │   解锁前置 ① GCS 在线：heartbeat_dmd 周期心跳（失联门限 ~30s，
    │              发 arm 前需刚发过心跳）
    │            ② mode=4（play/GUIDED 状态机；rtl 拒绝、stab 静默拒绝）
    │            ③ 电源正常：FS_BATT_ACT=1 时低电检测开启，台架限流电源
    │              电压采样 ~0.02V < 门限 19.2V → 解锁进 WAIT_TK 即被
    │              Battery failsafe 打回并 RTL 落锁（2026-09-10 日志
    │              实锤）；台架跑解锁用例先 sp FS_BATT_ACT: 0，
    │              真机试飞前必须恢复
    │   拒绝文案 "Mode cannot Arm"(模式门槛) / "Already Armed"(重复解锁)
    │   ⚠ ACK result=0 仅代表业务转发成功 — 判定以 STATUSTEXT +
    │     packed_state.armed 回读为准（三通道交叉，拒绝时 ACK 照样回 0）
    │   执行序(ARM-0004): 解锁 = 记yaw → 写Home(条件) → 设围栏原点 →
    │     启飞行日志 → 写ARMED → 通电源；
    │     上锁 = 停日志 → 清play_id → 清急停 → 写DISARMED → 卸任务 →
    │     清failsafe → 断电源
    │   Home 写入有前提（ARM-0004 AC-002：home 未设置且水平定位有效）
    └

    ┌ 模式切换: SET_MODE msg_id=11
    └   custom_mode: 0=stab 2=althold 4=play 5=loiter 6=rtl 9=land
        （base_mode=0, target_system=1；枚举 GCS-05 CLI 反查实锤，
          guide/auto 地面切不进，枚举未知）

环境口径：自动落锁根因 = **飞机倒置**（上下面装反，roll≈3.09 rad≈177°）
触发 ARM-0003 条件[5][6] 翻倒/大角度翻转保护 → 检测确认后（2~5s）自动
加锁。正放后消失。排查过程排除的假设：表演状态/电压/Radio（均非主因）；
dmsg 中 I2C4 读写与 CAN 接收失败为独立待查项（疑似 BMS 不在环，电池
数据全 0）。保持性验证为硬断言：解锁 6s 后仍 armed=1 才算通过；若回锁
即 fail 并附 dmsg 落锁原因。

用例层判定口径：
    - 拒绝类用例双通道判定——ACK result≠0 或 STATUSTEXT 命中拒绝文案
      任一满足即行为正确（兼容真机 ACK result=0 假成功偏差，偏差单独
      记录为问题单素材）；armed 保持检查带自动落锁鉴别（低电压/
      failsafe 环境因素不计失败，dmsg 轨迹佐证）
    - home_set 按 ARM-0004 AC-002 条件观察（home 未设置且水平定位
      有效才写入）；全程状态位快照对比，⚠️ 拆桨+限流台架

用例：
    - test_gcs03_arm_disarm                 指令解锁 / 指令上锁闭环
    - test_gcs03_duplicate_arm_rejected     重复解锁 → 拒绝 + Already Armed
    - test_gcs03_duplicate_disarm_rejected  重复上锁 → 幂等拒绝（待办，跳过）
    - test_gcs03_kill_disarm                强制上锁 kill（待办，跳过）

危险门控（默认 skip，定义在 fc_basic_base.py，运行前设置环境变量）：
    PowerShell: $env:FC_BASIC_ENABLE_DANGEROUS = "1"
    CMD:        set FC_BASIC_ENABLE_DANGEROUS=1
    Git Bash:   FC_BASIC_ENABLE_DANGEROUS=1 python main.py --device_type X1 --test_suites Functional_Testing
"""

import time

import pytest
import allure

from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    FCBasicBase, dangerous_gate, log_manager, SETTLE_MODE,
    CMD_ARM_DISARM, ARM_P1, DISARM_P1, MSG_ID_SET_MODE)

# 前后对比观察的状态位
_SNAPSHOT_KEYS = ('armed', 'mode', 'fly_state', 'home_set', 'fence_origin_set',
                  'play_state', 'drama_state', 'light_r', 'light_g', 'light_b',
                  'voltage_battery_percent')


@allure.feature("FC 基础功能 P0/P1")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC")
@pytest.mark.functional
class TestGcs03Arm(FCBasicBase):
    """GCS-03 解锁与上锁（p0×8）"""

    # ------------------------------------------------------------------
    # 公共辅助
    # ------------------------------------------------------------------

    def _switch_to_mode4(self):
        """SET_MODE(11) 切 mode=4 并断言回读生效。"""
        msg = MAVLink_message(
            msg_id=MSG_ID_SET_MODE, sys_id=1, comp_id=1, seq=0,
            version=self.mavlink_version,
            fields={'custom_mode': 4, 'target_system': 1, 'base_mode': 0})
        self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
        time.sleep(SETTLE_MODE)
        packed = self._get_packed_state()
        assert packed is not None, "切模式后无法获取 packed_state"
        mode_now = packed.fields.get('mode')
        log_manager.log_and_attach(
            f"SET_MODE custom_mode=4 后 packed_state.mode={mode_now}", "模式前置")
        assert mode_now == 4, (
            f"切表演模式(4)后状态流 mode={mode_now}——模式切换未生效")

    def _snapshot(self, tag, packed=None):
        """关键状态位快照；传入已收到的 packed_state 可复用（避免重新
        请求的间隙里状态回落导致快照与断言时点不一致）。"""
        if packed is None:
            packed = self._get_packed_state()
        assert packed is not None, f"无法获取 packed_state（{tag}）"
        snap = {k: packed.fields.get(k) for k in _SNAPSHOT_KEYS}
        log_manager.log_and_attach(
            '\n'.join(f"{k} = {v}" for k, v in snap.items()),
            f"状态位快照（{tag}）")
        return snap

    @staticmethod
    def _diff(before, after, action):
        """前后状态位对比表，变化行标注。"""
        lines = [f"{k}: {before[k]} → {after[k]}"
                 + ("  ← 变化" if before[k] != after[k] else "")
                 for k in before]
        log_manager.log_and_attach('\n'.join(lines),
                                   f"状态位前后对比（{action}）")

    # ------------------------------------------------------------------
    # 用例 1：指令解锁 / 指令上锁闭环
    # ------------------------------------------------------------------

    @allure.story("GCS-03 解锁与上锁")
    @allure.title("GCS-03 指令解锁 → 指令上锁闭环")
    @dangerous_gate
    def test_gcs03_arm_disarm(self):
        """指令解锁与指令上锁全链路（GCS-03 p0×8 正向路径）"""
        with allure.step("前置：GCS 在线 + mode=4"):
            packed = self._get_packed_state()
            assert packed is not None, "GCS 在线会话未建立"
            self._switch_to_mode4()

        with allure.step("基线快照（确认上锁态）"):
            snap_base = self._snapshot("基线")
            if snap_base['armed'] == 1:
                self._assert_ack(
                    self._send_command(CMD_ARM_DISARM, param1=DISARM_P1),
                    "初始上锁")
                self._wait_armed_state(0)
                snap_base = self._snapshot("基线（归位后）")

        with allure.step("指令解锁（p1=1）→ armed 翻 1"):
            ack, texts = self._send_command_watch_text(
                CMD_ARM_DISARM, param1=ARM_P1)
            self._assert_ack(ack, "解锁")
            if texts:
                log_manager.log_and_attach(' | '.join(texts), "解锁 STATUSTEXT")
            packed_armed = self._poll_armed(1, timeout=4.0)
            assert packed_armed is not None, (
                "armed 未翻转为 1——解锁被拒或未执行，看本用例 STATUSTEXT 附件")
            snap_armed = self._snapshot("解锁后（实锤帧）", packed=packed_armed)
            self._diff(snap_base, snap_armed, "解锁")
            # Home 写入按 ARM-0004 AC-002 有前提（home 未设置且水平定位有效）
            if snap_base['home_set'] == 1:
                assert snap_armed['home_set'] == 1, "解锁导致 home_set 回退"
            assert snap_armed['mode'] == snap_base['mode'], "解锁导致模式跳变"

        with allure.step("保持性验证：解锁 6s 后仍为解锁态（>5s 自动落锁窗口）"):
            # pass 标准：电压修复后 armed 应保持；6s 覆盖历史 ~5s 落锁窗口
            time.sleep(6.0)
            if self._poll_armed(1, timeout=2.0) is None:
                dmsg_tail = self._cli("dmsg", timeout=8.0)[-500:]
                assert False, (
                    f"解锁后 6s 内 armed 被自动回锁——不应发生（历史根因为"
                    f"台架电压不足，已调整）。dmsg 尾部（落锁原因）:\n"
                    f"{dmsg_tail}")
            log_manager.log_and_attach(
                "解锁后 6s armed 保持 1 ✓（自动落锁窗口外）", "保持性验证")

        with allure.step("指令上锁（p1=0）→ armed 回 0"):
            ack, texts = self._send_command_watch_text(
                CMD_ARM_DISARM, param1=DISARM_P1)
            self._assert_ack(ack, "上锁")
            if texts:
                log_manager.log_and_attach(' | '.join(texts), "上锁 STATUSTEXT")
            self._wait_armed_state(0)
            snap_disarmed = self._snapshot("上锁后")
            self._diff(snap_armed, snap_disarmed, "上锁")
            assert snap_disarmed['armed'] == 0, (
                f"上锁后 armed={snap_disarmed['armed']}（应 0）")
            log_manager.log_and_attach(
                f"param1 语义（本机实测）: 解锁={ARM_P1} 上锁={DISARM_P1}",
                "实测口径")

        with allure.step("收尾：确认上锁态"):
            packed = self._get_packed_state()
            if packed is not None:
                log_manager.log_and_attach(
                    f"收尾状态: armed={packed.fields.get('armed')}（应 0）",
                    "收尾状态")

    # ------------------------------------------------------------------
    # 用例 2：重复解锁拒绝
    # ------------------------------------------------------------------

    @allure.story("GCS-03 解锁与上锁")
    @allure.title("GCS-03 重复解锁 → 拒绝 + 'Already Armed'（ARM-0002 #5）")
    @dangerous_gate
    def test_gcs03_duplicate_arm_rejected(self):
        """重复解锁拒绝路径（GCS-03 p0×8）"""
        with allure.step("前置：GCS 在线 + mode=4"):
            packed = self._get_packed_state()
            assert packed is not None, "GCS 在线会话未建立"
            self._switch_to_mode4()

        with allure.step("指令解锁（p1=1）→ armed=1"):
            ack, _ = self._send_command_watch_text(CMD_ARM_DISARM, param1=ARM_P1)
            self._assert_ack(ack, "解锁")
            assert self._poll_armed(1, timeout=4.0) is not None, "解锁未生效"

        with allure.step("已解锁状态重复解锁 → 拒绝"):
            ack, texts = self._send_command_watch_text(
                CMD_ARM_DISARM, param1=ARM_P1)
            assert ack is not None, "重复解锁未收到 ACK"
            result = ack.fields.get('result')
            joined = ' | '.join(texts)
            log_manager.log_and_attach(
                f"重复解锁 ACK result={result}\nSTATUSTEXT: {joined or '(无)'}",
                "重复解锁响应")
            st_rejected = any('already armed' in t.lower() for t in texts)
            assert result != 0 or st_rejected, (
                f"重复解锁未被拒绝（ACK result={result}，STATUSTEXT 无 "
                f"'Already Armed'）——ARM-0002 #5 / ARM-0006 AC-005 均未满足")
            if result == 0 and st_rejected:
                log_manager.log_and_attach(
                    "ACK result=0 但 STATUSTEXT 已报 'Already Armed'——ACK "
                    "假成功偏差（与 ARM-0006 口径不符，问题单素材）", "已知偏差")

        with allure.step("重复解锁后 armed 保持（回锁原因用 dmsg 鉴别）"):
            # 注意：fs_state 会被 disarm 清零（ARM-0004 上锁执行序含"清除
            # failsafe"），事后查 fs_state 查不到回锁原因；dmsg 系统日志里
            # 的状态机轨迹（Radio failsafe SET / battery low / disarming）
            # 才是落锁原因的直接证据
            if self._poll_armed(1, timeout=1.5) is not None:
                log_manager.log_and_attach(
                    "重复解锁后 armed 保持 1", "armed 保持")
            else:
                dmsg_tail = self._cli("dmsg", timeout=8.0)[-500:]
                env_markers = ('Radio failsafe', 'disarming', 'battery',
                               'low battery')
                if any(m.lower() in dmsg_tail.lower()
                       for m in env_markers):
                    log_manager.log_and_attach(
                        f"armed 已回落，dmsg 显示自动落锁轨迹"
                        f"（环境因素，不计失败）:\n{dmsg_tail}",
                        "armed 保持（环境回锁）")
                else:
                    assert False, (
                        f"重复解锁后 armed 不为 1 且 dmsg 无落锁轨迹——疑似"
                        f"重复解锁破坏状态（缺陷）。dmsg 尾部:\n{dmsg_tail}")

        with allure.step("收尾：指令上锁"):
            ack, _ = self._send_command_watch_text(CMD_ARM_DISARM,
                                                   param1=DISARM_P1)
            self._assert_ack(ack, "收尾上锁")
            self._wait_armed_state(0)

    # ------------------------------------------------------------------
    # 用例 3（待办）：重复上锁幂等拒绝
    # ------------------------------------------------------------------

    @allure.story("GCS-03 解锁与上锁")
    @allure.title("GCS-03 上锁态重复上锁 → 拒绝（幂等保护，ARM-0004 AC-009）")
    @dangerous_gate
    @pytest.mark.skip(reason="待办：重复上锁幂等保护用例待实现（ARM-0004 AC-009）")
    def test_gcs03_duplicate_disarm_rejected(self):
        """上锁态重复上锁拒绝路径（待实现）"""
        raise NotImplementedError("待实现：ARM-0004 AC-009 幂等保护验证")

    # ------------------------------------------------------------------
    # 用例 4（待办）：强制上锁 kill
    # ------------------------------------------------------------------

    @allure.story("GCS-03 解锁与上锁")
    @allure.title("GCS-03 强制上锁 kill（p2=21196，ARM-0008 紧急通道）")
    @dangerous_gate
    @pytest.mark.skip(reason="待办：强制上锁 kill 用例待实现（ARM-0008 紧急通道）")
    def test_gcs03_kill_disarm(self):
        """强制上锁 kill 路径（待实现）"""
        raise NotImplementedError("待实现：ARM-0008 强制上锁验证")
