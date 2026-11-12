# coding: utf-8

"""
GCS-23 远程终端（p1×4）— MAVLink 远程执行 CLI 并回传

业务背景：
    CONSOLE(48) 通道远程执行 CLI，验证输入写入→执行→输出回传全链路
    （不接触飞机的 CLI 通道，也是本套件所有 CLI 命令的载体）。
    正向用真命令（ls/version：ACK + 内容 + 提示符）；负向用未知命令
    验证差错处理路径。

真机实测口径（2026-09-11 实锤）：
    - **固件无 help 命令**（NAK + "Unknow cmd: 'help'"）——CLI 没有
      自助命令清单，命令全集/语法只能向固件组索取（议题已记）。
      旧版用例拿 help 当正向命令是"空洞通过"（NAK 回显也带提示符），
      已改造为负向用例
    - 未知命令回显 = NAK + "Unknow cmd: '<名>'" + 提示符

    - test_gcs23_remote_terminal   正向 ls/version + 负向 help（默认执行）
"""

import pytest
import allure

from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    FCBasicBase, log_manager, CONSOLE_PROMPT)


@allure.feature("FC 基础功能 P0/P1")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC")
@pytest.mark.functional
class TestGcs23Terminal(FCBasicBase):
    """GCS-23 远程终端（p1×4）"""

    @allure.story("GCS-23 远程终端")
    @allure.title("GCS-23 MAVLink 远程执行 CLI 并回传（正向 + 负向）")
    def test_gcs23_remote_terminal(self):
        """远程终端执行与回传：正向 ls/version + 负向未知命令（GCS-23 p1×4）"""
        # 正向：真实命令 → ACK + 内容 + 提示符完整回显
        for cmd in ("ls", "version"):
            with allure.step(f"远程执行 `{cmd}` 并核对完整回显"):
                resp = self._cli(cmd, timeout=8.0)
                assert resp and CONSOLE_PROMPT in resp, (
                    f"`{cmd}` 无完整回显（未收到提示符）: {resp[:200]}")
                assert "ack" in resp.lower(), (
                    f"`{cmd}` 未收到 ACK: {resp[:200]}")
                log_manager.log_and_attach(
                    resp[:300], f"远程终端 `{cmd}`")

        # 负向：未知命令 → NAK + Unknow cmd + 提示符（差错处理路径）
        with allure.step("负向：未知命令 `help` → NAK + Unknow cmd"):
            resp = self._cli("help", timeout=8.0)
            assert resp and CONSOLE_PROMPT in resp, (
                f"未知命令无完整回显: {resp[:200]}")
            low = resp.lower()
            assert "nak" in low or "unknow" in low, (
                f"未知命令应回 NAK/Unknow（固件无 help，2026-09-11 实测）: "
                f"{resp[:200]}")
            log_manager.log_and_attach(resp[:200], "负向 `help` 回显")
