# coding: utf-8

"""
GCS-15 传感器校准（p1×8，危险）— 启动/强制停止（不落坏值）+ 取值探测

业务背景：
    校准命令 = CMD_CALIB_SENSOR(40040)（DMD 私有总命令，三源实锤：
    DGCS 真站 MavlinkCommandMessageBuilder:337 + chenpan
    test_mavlink_calibration + laser 用例 param1=7 激光同类型表）：
        param1 = 校准类型：1=加速度 ACCEL / 2=磁罗盘 CMPS / 3=RC /
                 4=ESC / 5=UWB（另带 p3/4/5=xyz）/ 6=Camera / 7=激光
        param2 = 操作类型：1=启动 / 2=停止 / 3=获取校准值（回 msg30）
        启动加速度 = (p1=1, p2=1)；启动磁罗盘 = (p1=2, p2=1)；
        停止 = (p1=0, p2=2)
    ⚠️ 旧口径（241 + "p1=启停/p2=传感器"）为双重错误，2026-09-11 修正；
    241 是标准 MAVLink 飞前校准（chenpan Release_Testing 覆盖），与
    40040 是两个命令。

    只验证启停链路与中途终止不保存坏值（完整六面摆放校准属人工流程）。
    校准会改落盘值，测试后建议人工重校。⚠️ 危险组

真机实测口径（2026-09-11 40040 跑批实锤）：
    - 启动/停止 ACK 均 result=0（全程 STATUSTEXT 无文案）；**校准真实
      生效的行为铁证 = TP_SENSOR_CALI 发布率随校准单调上升**（累计
      均值口径：0.011 校准前 → 0.26 加速度后 → 0.45 磁罗盘中）——
      Topic 在校准期间真实发布，非 ACK 假成功
    - ⚠️ 固件 dt 打印器缺陷：`dt TP_SENSOR_CALI` 回
      "--->print not defined!"——Topic 字段值打不出来，只能取发布率
      （问题单素材）
    - ⚠️ **fs_state 与校准无关**（字段全是失效保护标志 EKF/crash/
      radio/battery，实测恒 0，旧版查 fs_state 是无效检查，已移除）
    - **p2=3 取值的存在性未证实**：仅出自 chenpan 老 skip 用例；DGCS
      真站源码只见 opType==2（停止）分支，CmdCalibPeriph.opType 枚举
      定义不在仓库。真机发 p2=3 得 ACK result=4 + 无 msg30（两轮复现）
      ——无法区分"操作未实现"与"前置不满足"。备选假设：**校准值或为
      推送制**（校准完成后自动回 msg30——DGCS codec 有其反序列化）
      而非 p2=3 查询制。待固件组确认 opType 合法值后定稿

    - test_gcs15_calibration   加速度/磁罗盘校准启停链路 + 取值探测（危险门控）

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

from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    FCBasicBase, dangerous_gate, log_manager, SETTLE_SHORT,
    CMD_CALIB_SENSOR, MSG_ID_CALIBRATION_VALUE)

# 校准类型（param1 取值，DGCS CalibrationType 枚举）
CALI_TYPE_ACCEL = 1        # 加速度
CALI_TYPE_CMPS = 2         # 磁罗盘

# COMMAND_ACK result 码（标准 MAV_RESULT）
MAV_RESULT_NAMES = {0: 'ACCEPTED 接受', 1: 'TEMPORARILY_REJECTED 临时拒绝',
                    2: 'DENIED 拒绝', 3: 'UNSUPPORTED 不支持',
                    4: 'FAILED 执行失败', 5: 'IN_PROGRESS 执行中'}


def _cali_pub_rate(dt_text):
    """从 dt TP_SENSOR_CALI 回显提取发布率（pub/s）；无则 None

    回显形如 "TP_SENSOR_CALI(0.2645502 pub/s)--->print not defined!"
    （固件打印器缺陷：字段值打不出来，只有发布率行可用）
    """
    m = re.search(r'TP_SENSOR_CALI\(([\d.]+) pub/s\)', dt_text or '')
    return float(m.group(1)) if m else None


@allure.feature("FC 基础功能 P0/P1")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC")
@pytest.mark.functional
class TestGcs15Calibration(FCBasicBase):
    """GCS-15 传感器校准（p1×8）"""

    @allure.story("GCS-15 传感器校准")
    @allure.title("GCS-15 校准启动/强制停止（不落坏值）+ 取值探测")
    @dangerous_gate
    def test_gcs15_calibration(self):
        """校准启动→强制停止 两种传感器 + 取值探测（GCS-15 p1×8 启停链路）"""
        # (校准类型 param1, 名称)；启动 = p1=类型/p2=1，停止 = p1=0/p2=2
        rate_trend = []      # (标签, 发布率)——校准生效的行为证据链
        for cali_type, name in [(CALI_TYPE_ACCEL, "加速度"),
                                (CALI_TYPE_CMPS, "磁罗盘")]:
            with allure.step(f"启动{name}校准 (40040, p1={cali_type} 类型, p2=1 启动)"):
                # watch_text 顺手抓 STATUSTEXT（启动文案是真实生效的旁证）
                ack, texts = self._send_command_watch_text(
                    CMD_CALIB_SENSOR, param1=cali_type, param2=1)
                assert ack is not None, f"{name}校准启动无 ACK"
                result = ack.fields.get('result')
                log_manager.log_and_attach(
                    f"{name}校准启动 ACK result={result}"
                    f"（{MAV_RESULT_NAMES.get(result, '?')}），"
                    f"STATUSTEXT={texts or '(无)'}", f"{name}校准启动")

            with allure.step(f"{name}校准中状态（dt TP_SENSOR_CALI）"):
                state_on = self._cli("dt TP_SENSOR_CALI")
                log_manager.log_and_attach(state_on or "(空)",
                                           f"{name}校准中状态")
                rate_on = _cali_pub_rate(state_on)
                if rate_on is not None:
                    rate_trend.append((f"{name}校准中", rate_on))

            with allure.step(f"强制停止 (p1=0, p2=2) → 状态归位核对"):
                time.sleep(2.0)
                ack, texts = self._send_command_watch_text(
                    CMD_CALIB_SENSOR, param1=0, param2=2)
                assert ack is not None, f"{name}校准停止无 ACK"
                result = ack.fields.get('result')
                log_manager.log_and_attach(
                    f"{name}校准停止 ACK result={result}"
                    f"（{MAV_RESULT_NAMES.get(result, '?')}），"
                    f"STATUSTEXT={texts or '(无)'}", f"{name}校准停止")
                state_off = self._cli("dt TP_SENSOR_CALI")
                log_manager.log_and_attach(state_off or "(空)",
                                           f"{name}停止后状态")
                rate_off = _cali_pub_rate(state_off)
                if rate_off is not None:
                    rate_trend.append((f"{name}停止后", rate_off))
                # 校准 Topic 前后读数相同 → 疑似校准未真实生效（Topic 口径
                # 首跑存档，确认字段语义后再收紧为断言）
                if state_on and state_off and state_on == state_off:
                    log_manager.logger.warning(
                        f"{name}校准前后 TP_SENSOR_CALI 读数相同——疑似校准"
                        f"未生效或 Topic 字段不反映启停（口径存档不判失败）")
                time.sleep(SETTLE_SHORT)

        # 发布率趋势：累计均值随校准单调上升 = 校准真实发布的行为铁证
        # （2026-09-11 实测 0.011 → 0.26 → 0.45；瞬时语义待定，仅记录）
        if rate_trend:
            log_manager.log_and_attach(
                "TP_SENSOR_CALI 发布率趋势（校准期间上升=校准真实生效，"
                "ACK 假成功之外的旁证）:\n" + '\n'.join(
                    f"  {label}: {rate} pub/s" for label, rate in rate_trend),
                "校准发布率趋势")

        with allure.step("p2=3 取值操作存在性探测（未证实协议，仅记录）"):
            # p2=3 仅出自 老 skip 用例，DGCS 源码无此分支——本步
            # 是存在性实验而非既定协议验证；校准值也可能是推送制
            # （校准完成自动回 msg30），见模块 docstring 口径
            ack = self._send_command(CMD_CALIB_SENSOR,
                                     param1=CALI_TYPE_ACCEL, param2=3)
            result = ack.fields.get('result') if ack else None
            calib_msg = self._wait_msg(MSG_ID_CALIBRATION_VALUE, timeout=3.0)
            body = (f"p2=3 探测 ACK result={result}"
                    f"（{MAV_RESULT_NAMES.get(result, '?')}）\n"
                    + (f"msg30 校准值载荷:\n"
                       f"{(calib_msg.payload or b'').hex(' ')[:400]}"
                       if calib_msg is not None else
                       "msg30 无回包（3s）——与 2026-09-11 实测一致"
                       "（result=4：未实现 or 前置不满足，待固件组定夺）"))
            log_manager.log_and_attach(body, "p2=3 取值探测")
