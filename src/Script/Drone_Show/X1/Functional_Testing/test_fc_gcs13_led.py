# coding: utf-8

"""
GCS-13 指示灯（信号灯）控制（p1×2）— CLI notify 使能开关

业务背景：
    指示灯 = 信号灯，CLI `notify on/off` 控制使能，以 CLI 回显核验执行。

    ⚠️ 183 RGB 控制块已于 2026-09-10 实测后移除：COMMAND_LONG 183 不带
    param7 点不亮 LED（点亮保持 10s 肉眼确认无光），ACK result=0 假成功，
    packed_state.light_r/g/b 回读恒 0（死字段——既不反映指令也不反映真实）。
    183 为复用命令按 param7 分路（激光颜色控制实锤 param7=4），LED RGB 的
    子功能码待固件组确认后另立用例恢复。

    - test_gcs13_notify_switch   信号灯使能/失能（notify off/on）
"""

import pytest
import allure

from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    FCBasicBase, log_manager, _cli_failed)


@allure.feature("FC 基础功能 P0/P1")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC")
@pytest.mark.functional
class TestGcs13Led(FCBasicBase):
    """GCS-13 指示灯（信号灯）控制（p1×2）"""

    @allure.story("GCS-13 指示灯")
    @allure.title("GCS-13 信号灯使能/失能（notify off/on）")
    def test_gcs13_notify_switch(self):
        """验证 notify off/on 命令：CLI 回显核验（GCS-13 p1×2）"""
        with allure.step("指示灯失能 notify off → 恢复 notify on"):
            resp_off = self._cli("notify off")
            resp_on = self._cli("notify on")
            log_manager.log_and_attach(
                f"notify off 回显:\n{resp_off[:100]}\n"
                f"notify on 回显:\n{resp_on[:100]}", "指示灯使能开关")
            assert not _cli_failed(resp_off), (
                f"notify off 执行失败: {resp_off[:200]}")
            assert not _cli_failed(resp_on), (
                f"notify on 执行失败: {resp_on[:200]}")
