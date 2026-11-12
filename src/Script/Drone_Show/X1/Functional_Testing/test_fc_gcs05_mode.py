# coding: utf-8

"""
GCS-05 模式切换与一键起飞（p0×3 + p1×10，危险）

业务背景：
    模式枚举无文档，用 CLI `mode <name>` 切换 + packed_state.mode 回读
    反查 custom_mode。回执三要素（2026-09-10 真机终端实锤口径）：
        ACK                          ← 每步必验
        switch to mode: MODE_<NAME>  ← 切换确认行
        packed_state.mode 回读       ← 枚举仲裁，已实锤模式硬断言
    ⚠️ **同态重切是 no-op**：当前状态切当前状态只回 ACK、不打切换行
    （2026-09-10 实测）——因此用例组织为固定顺序闭环：land 归位（容忍
    同态）→ 五飞行模式依次切换 → rtl → auto → land 终态。闭环顺序保证
    除归位步外均为真实切换，切换回显校验有效；终步 land 前接 rtl（auto
    为 no-op 不改前态），回显必现。
    ⚠️ **auto 仅验证通信链路**：廖工 2026-09-10 确认 auto 跑不起来
    （未实现），CLI 发送仅回 ACK、无 "switch to mode: " 回显——闭环中
    auto 步只硬断言 ACK（通信先测通），切换回显/模式功能不作断言，
    回显若出现则存档。
    再用 msg_id=11 MAVLink 通道切 stab 核对状态回读，完成发送→转发→
    执行→上报闭环。

模式名对照（2026-09-10 手册缩写 + 真机终端实锤）：
    手册缩写 S=姿态 stab(0)、AH=定高 althold(2)、L=定点 loiter(5)、
    R=返航 rtl(6)、LD=land(9)、G=群控。群控 = guided = play(表演)，
    同一模式三名（手册"群控"/CLI guided/飞控 play），custom_mode=4。
    ⚠️ CLI 名为全称 guided（非 guide——09-08 反查失败疑似名字拼错）；
    auto 无切换回显、回读维持原值，**廖工 2026-09-10 确认跑不起来
    （未实现）**——用例仅验通信链路（ACK 硬断言）+ 回读存档不判失败。

    一键起飞 = MAV_CMD_NAV_TAKEOFF(22, p7=目标高度 2m)：上锁态请求应
    被拒——双通道判定（ACK result≠0 或行为仲裁 armed 保持 0；result=0
    假成功偏差记录素材，与 command=400 同源）；解锁后请求 ACK
    result=0（⚠️ DMD 是否用 22 实现待确认，若拒绝需查实际命令号）；
    mode 9 降落 → 上锁收尾。
    ⚠️ 拆桨台架执行，电机仅怠速。

用例：
    - test_gcs05_mode_switch_loop    CLI 模式闭环（land 归位→S/AH/L/G/R→auto→land 校验）
    - test_gcs05_mode_switch_mavlink msg11 通道切换闭环（stab）
    - test_gcs05_takeoff_reject_disarmed  上锁态一键起飞 → 拒绝（双通道判定）
    - test_gcs05_takeoff_normal           解锁 → 一键起飞 → 降落 → 上锁
    （起飞降落原单用例已按正常/异常路径拆分；室内台架无高度变化，
      起飞后 5s 观察窗口已删除，仅保留短暂执行窗口后直接降落）

危险用例默认 skip。开启 = 运行前设置环境变量（门控定义在 fc_basic_base.py，
import 时求值，改代码无效）：
    PowerShell: $env:FC_BASIC_ENABLE_DANGEROUS = "1"
    CMD:        set FC_BASIC_ENABLE_DANGEROUS=1
    Git Bash:   FC_BASIC_ENABLE_DANGEROUS=1 python main.py --device_type X1 --test_suites Functional_Testing
"""

import re
import time

import pytest
import allure

from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    FCBasicBase, dangerous_gate, log_manager, SETTLE_MODE, SETTLE_SHORT,
    CMD_ARM_DISARM, ARM_P1, DISARM_P1, CMD_NAV_TAKEOFF)
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    MSG_ID_SET_MODE)

# CLI 名 → 手册缩写/中文名（2026-09-10 手册口径）
MANUAL_MODE_ABBR = {
    "stab": "S/姿态", "althold": "AH/定高", "loiter": "L/定点",
    "guided": "G/群控", "rtl": "R/返航", "land": "LD/降落",
    "auto": "?/未知",
}

# CLI 名 → 已实锤 custom_mode（回读断言用；auto 未知不预设）
EXPECTED_MODE_ENUM = {"stab": 0, "althold": 2, "guided": 4,
                      "loiter": 5, "rtl": 6, "land": 9}

# 模式切换闭环序列：(CLI 名, 手册缩写, 是否校验切换回显)。
# 顺序保证除归位步外前态必不同 → 真实切换 → 回显必现，校验有效
MODE_SWITCH_LOOP = [
    ("land", "LD/降落", False),    # 归位步：起始可能已是 land（同态 no-op 无回显）
    ("stab", "S/姿态", True),
    ("althold", "AH/定高", True),
    ("loiter", "L/定点", True),
    ("guided", "G/群控", True),
    ("rtl", "R/返航", True),
    # auto 仅验证通信链路（2026-09-10 确认跑不起来）：
    # 只硬断言 ACK，无 "switch to mode: " 回显属预期；no-op 不改前态，
    # 不影响终步 land 回显校验
    ("auto", "?/未知·仅通信", False),
    ("land", "LD/降落", True),     # 终态：前接 rtl（auto 为 no-op），必为真实切换
]


@allure.feature("FC 基础功能 P0/P1")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC")
@pytest.mark.functional
class TestGcs05Mode(FCBasicBase):
    """GCS-05 模式切换与一键起飞（p0×3 + p1×10）"""

    # ==================================================================
    # 公共辅助
    # ==================================================================

    def _switch_cli_mode(self, name, verify_echo=True):
        """CLI `mode <name>` 切换一步：ACK 必验，回显按参校验，回读仲裁

        verify_echo=True 硬断言 "switch to mode: MODE_<NAME>" 切换行——
        仅限闭环顺序保证前态不同时使用（同态重切是 no-op，只回 ACK 不打
        切换行）；False 用于归位步与 auto——auto 仅验证通信链路（廖工
        确认未实现、跑不起来），只硬断言 ACK。packed_state.mode 回读：
        已实锤枚举硬断言，未知存档。
        """
        with allure.step(f"发送 mode {name} 并核验回执（ACK）"):
            self._clear_recv_buffer()
            resp = self._cli(f"mode {name}")
            assert resp, f"mode {name} 命令无响应"
            assert "ack" in resp.lower(), f"mode {name} 未收到 ACK: {resp[:200]}"
            switched = re.search(r"switch to mode:\s*(MODE_\w+)", resp)
            if switched:
                log_manager.log_and_attach(
                    f"回显切换行: {switched.group(1)}", f"切换回显 {name}")
            elif verify_echo:
                assert False, (
                    f"mode {name} 未命中切换回显 'switch to mode:'"
                    f"（闭环前态应不同，此处应有真实切换——疑似异常或漏收）:"
                    f"{resp[:200]}")
            else:
                if name == "auto":
                    note = ("auto 模式仅验证通信链路（可能未实现、还跑不起来）：只校验 ACK，无 'switch to "
                            "mode: ' 回显属预期")
                else:
                    note = "归位步可能同态重切，不判定"
                log_manager.log_and_attach(
                    f"{note}:\n{resp[:200]}", f"切换回显缺失 {name}")
                log_manager.logger.warning(f"mode {name}: {note}")
        with allure.step(f"回读 packed_state.mode（{MANUAL_MODE_ABBR[name]}）"):
            time.sleep(SETTLE_MODE)
            packed = self._get_packed_state()
            mode_val = packed.fields.get('mode') if packed else None
            log_manager.log_and_attach(
                f"mode {name} → packed_state.mode={mode_val}",
                f"枚举回读 {name}")
            expected = EXPECTED_MODE_ENUM.get(name)
            if expected is not None:
                assert mode_val == expected, (
                    f"mode {name} 回读 mode={mode_val}，与实锤枚举 "
                    f"{expected} 不符——模式切换未生效或枚举漂移")
            elif switched is None:
                log_manager.logger.warning(
                    f"mode {name} 无切换回显且回读维持 {mode_val}"
                    f"（枚举未知，口径存档不判失败）")

    # ==================================================================
    # CLI 模式切换闭环
    # ==================================================================

    @allure.story("GCS-05 模式切换")
    @allure.title("GCS-05 CLI 模式切换闭环（land 归位 → S/AH/L/G/R → auto → land）")
    @dangerous_gate
    @pytest.mark.skip(reason="临时跳过：调试起飞降落用例（调试完删除此行）")
    def test_gcs05_mode_switch_loop(self):
        """模式闭环：land 归位（容忍同态）→ stab/althold/loiter/guided/rtl
        依次切换（回显+回读双校验）→ auto（仅验通信 ACK，未实现·廖工确认）
        → land 终态（回显硬校验）"""
        for name, abbr, verify_echo in MODE_SWITCH_LOOP:
            if name == "auto":
                tag = "［仅验通信·ACK，auto 未实现］"
            elif verify_echo:
                tag = "［回显校验］"
            else:
                tag = "［归位步·容忍同态］"
            with allure.step(f"切 {name}（{abbr}）{tag}"):
                self._switch_cli_mode(name, verify_echo=verify_echo)
        log_manager.log_and_attach(
            "闭环完成: " + " → ".join(n for n, _, _ in MODE_SWITCH_LOOP),
            "模式切换闭环")

    # ==================================================================
    # MAVLink 通道切换闭环
    # ==================================================================

    @allure.story("GCS-05 模式切换")
    @allure.title("GCS-05 MAVLink msg11 切换闭环（stab）")
    @dangerous_gate
    @pytest.mark.skip(reason="临时跳过：调试起飞降落用例（调试完删除此行）")
    def test_gcs05_mode_switch_mavlink(self):
        """msg11 通道切 stab：发送 → 状态回读核对（发送→转发→执行→上报闭环）"""
        with allure.step("发送 SET_MODE (msg11) custom_mode=0 (stab)"):
            msg = MAVLink_message(
                msg_id=MSG_ID_SET_MODE, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'custom_mode': 0, 'target_system': 1,
                        'base_mode': 1})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            log_manager.log_and_attach(
                "SET_MODE custom_mode=0 (stab)", "模式切换发送")
        with allure.step("回读核对 packed_state.mode"):
            time.sleep(SETTLE_MODE)
            packed = self._get_packed_state()
            assert packed is not None, "切换后无法获取 packed_state"
            actual = packed.fields.get('mode')
            log_manager.log_and_attach(
                f"切换 stab(0) 后 packed_state.mode={actual}", "模式切换回读")
            assert actual == 0, (
                f"msg11 切 stab(0) 后状态流 mode={actual}，"
                f"不一致——转发/执行/上报三层中有一层异常")
    
    # ==================================================================
    # 一键起飞与降落（按正常/异常路径拆分）
    # ==================================================================

    @allure.story("GCS-05 一键起飞与降落")
    @allure.title("GCS-05 上锁态一键起飞 → 拒绝（双通道判定）")
    @dangerous_gate
    def test_gcs05_takeoff_reject_disarmed(self):
        """上锁态请求一键起飞 → 应被拒（GCS-05 p1 起飞项异常路径）"""
        with allure.step("前置：确保上锁 → armed=0"):
            self._assert_ack(
                self._send_command(CMD_ARM_DISARM, param1=DISARM_P1),
                "确保上锁")
            # 回读确认上锁态（ACK result=0 仅代表转发成功，不作数）
            if self._poll_armed(0, timeout=3.0) is None:
                # 解锁/飞行态下 disarm 被固件拒绝（飞行中不允许上锁，
                # ACK 假成功回 0 而 armed 不落——2026-09-10 实测）：
                # 先切 mode 9 降落（落地自动落锁）再兜底上锁
                log_manager.log_and_attach(
                    "direct disarm 未生效（疑似入场为解锁/飞行态），"
                    "先降落再上锁", "前置兜底")
                msg = MAVLink_message(
                    msg_id=MSG_ID_SET_MODE, sys_id=1, comp_id=1, seq=0,
                    version=self.mavlink_version,
                    fields={'custom_mode': 9, 'target_system': 1,
                            'base_mode': 1})
                self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
                time.sleep(SETTLE_MODE)
                self._assert_ack(
                    self._send_command(CMD_ARM_DISARM, param1=DISARM_P1),
                    "降落后兜底上锁")
                self._wait_armed_state(0)
        with allure.step("上锁态请求起飞 → 拒绝判定（双通道）"):
            # ACK result=0 假成功有前科（command=400 同源），拒绝判定走
            # 双通道：ACK result≠0，或行为仲裁——armed 保持 0（未自动
            # 解锁进起飞流程）即固件行为上已拒绝
            ack, texts = self._send_command_watch_text(
                CMD_NAV_TAKEOFF, param7=2.0)
            assert ack is not None, "起飞指令无 ACK"
            result = ack.fields.get('result')
            if texts:
                log_manager.log_and_attach(' | '.join(texts), "起飞 STATUSTEXT")
            log_manager.log_and_attach(
                f"上锁态起飞 ACK result={result}, STATUSTEXT={texts or '(无)'}",
                "拒绝路径口径")
            if result == 0:
                # ACK 通道无拒绝证据 → 行为仲裁：等可能的自动解锁窗口
                time.sleep(SETTLE_SHORT)
                if self._poll_armed(1, timeout=2.0) is not None:
                    assert False, (
                        f"上锁态起飞被执行（armed 翻 1）——解锁前检查缺失"
                        f"（GCS-03 交界缺陷）。STATUSTEXT: {texts}")
                log_manager.log_and_attach(
                    "ACK result=0 假成功（与 command=400 同源偏差，问题单"
                    "素材）；行为仲裁：armed 保持 0，固件正确未执行起飞",
                    "已知偏差")

    @allure.story("GCS-05 一键起飞与降落")
    @allure.title("GCS-05 一键起飞正常路径 → 降落 → 上锁")
    @dangerous_gate
    def test_gcs05_takeoff_normal(self):
        """解锁 → 一键起飞 → 降落 → 上锁收尾（GCS-05 p1 起飞项正常路径）"""
        with allure.step("前置：切 guided/群控（mode=4，解锁前置——GCS-03 口径）"):
            # 解锁前置②：mode=4（2026-09-10 实测复现：非 guided 态 arm 被
            # 模式门槛拒绝，ACK 假成功回 0 而 armed 不翻）
            msg = MAVLink_message(
                msg_id=MSG_ID_SET_MODE, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'custom_mode': 4, 'target_system': 1, 'base_mode': 1})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            time.sleep(SETTLE_MODE)
            packed = self._get_packed_state()
            assert packed is not None, "切模式后无法获取 packed_state"
            mode_now = packed.fields.get('mode')
            log_manager.log_and_attach(
                f"SET_MODE custom_mode=4 后 packed_state.mode={mode_now}",
                "模式前置")
            assert mode_now == 4, (
                f"切群控模式(4)后状态流 mode={mode_now}——模式切换未生效，"
                f"解锁前置不满足（GCS-03 口径：解锁需 mode=4）")
        with allure.step("前置：解锁（p1=1）→ armed=1"):
            self._assert_ack(self._send_command(CMD_ARM_DISARM, param1=ARM_P1),
                             "解锁")
            # 回读确认解锁（mode=4 无表演任务时约 5s 后自动加锁，需抓紧起飞）
            self._wait_armed_state(1)
        with allure.step("一键起飞 2m（command=22, p7=2.0）→ ACK result=0"):
            ack = self._send_command(CMD_NAV_TAKEOFF, param7=2.0)
            assert ack is not None, "起飞指令无 ACK"
            result = ack.fields.get('result')
            log_manager.log_and_attach(
                f"解锁态起飞 ACK result={result}", "正常路径")
            assert result == 0, (
                f"解锁态一键起飞被拒 result={result}——若 DMD 未用 "
                f"MAV_CMD_NAV_TAKEOFF(22) 实现一键起飞（手册附录 B ⚠️待确认），"
                f"请查实际命令号后更新 CMD_NAV_TAKEOFF")
            # 室内台架无高度变化（观察窗口已删）：仅留短暂执行窗口，
            # 避免起飞指令未处理就被降落覆盖
            time.sleep(SETTLE_SHORT)
        with allure.step("降落（mode 9）→ 上锁收尾"):
            msg = MAVLink_message(
                msg_id=MSG_ID_SET_MODE, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'custom_mode': 9, 'target_system': 1, 'base_mode': 1})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            time.sleep(SETTLE_MODE)
            self._assert_ack(self._send_command(CMD_ARM_DISARM, param1=DISARM_P1),
                             "降落收尾上锁")
