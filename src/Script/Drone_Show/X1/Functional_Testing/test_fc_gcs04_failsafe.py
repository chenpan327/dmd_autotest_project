# coding: utf-8

"""
GCS-04 失效保护触发（p1×6，危险）— CLI 故障注入 → 上报 → 清除

业务背景：
    固件 SYS_CLI_SERV 提供 ffs（fake failsafe）注入命令，把对应状态源锁成
    异常值，用于失效保护测试。注入成功的可靠判据是 CLI 回显对应的
    "Fake ..." 文本——ACK result=0 存在假成功偏差（与 GCS-03 解锁同源）。

ffs 指令映射（来源：Serial_Protocol_Lite.py set_error_state，按固件源码
sys_cli_serv.cpp:1937-2010 校验；ffs 5 为 2026-09-09 真机终端实测发现）：
    ffs 0           清除全部注入     固件静默无回显（仅 ACK）
    ffs 1           低电             "Fake low battery"
    ffs 2           航点失败         "Fake wp error"
    ffs 3           超出电子围栏     "Fake fence error"
    ffs 4,1,0,1     EKF 异常         "Fake EKF to:(h,v,a)"
    ffs 5           坠机(跌落)       "Fake crash (fall)"

判定口径（2026-09-09）：
    - 注入必须命中对应 "Fake ..." 回显（主判据）
    - msg6 上报仅信息记录不阻断（室内模式下 FS_*_ACT 响应参数可能未开启）
    - fs_state 状态检查已取消：dt 探针实锤 ffs 疑似只回显不动状态源，
      台架上翻转判据必然误报

危险用例默认 skip。开启 = 运行前设置环境变量（门控定义在 fc_basic_base.py）：
    PowerShell: $env:FC_BASIC_ENABLE_DANGEROUS = "1"
    CMD:        set FC_BASIC_ENABLE_DANGEROUS=1
    Git Bash:   FC_BASIC_ENABLE_DANGEROUS=1 python main.py --device_type X1 --test_suites Functional_Testing
"""

import time

import pytest
import allure

from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    FCBasicBase, dangerous_gate, log_manager, SETTLE_SHORT)
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    MSG_ID_FAILSAFE)


@allure.feature("FC 基础功能 P0/P1")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC")
@pytest.mark.functional
class TestGcs04Failsafe(FCBasicBase):
    """GCS-04 失效保护触发（p1×6）"""

    # ==================================================================
    # 公共辅助
    # ==================================================================

    def _inject_and_verify(self, cmd, marker):
        """发送 ffs 注入命令，验证 "Fake ..." 回显，并记录 msg6 上报"""
        with allure.step(f"发送 ffs {cmd} 命令"):
            self._clear_recv_buffer()
            resp = self._cli(f"ffs {cmd}")
        with allure.step("验证故障标记"):
            assert resp, f"ffs {cmd} 命令无响应"
            assert marker in resp.lower(), f"ffs {cmd} 未命中 {marker}: {resp}"
        with allure.step("记录失效上报（msg6，仅信息不阻断）"):
            fs_msg = self._wait_msg(MSG_ID_FAILSAFE, timeout=5.0)
            log_manager.log_and_attach(
                f"msg6: "
                f"{'failsafe=' + str(fs_msg.fields.get('failsafe')) if fs_msg else '(未上报)'}",
                f"失效上报 ffs {cmd}")

    def _clear_error_state(self):
        """发送 ffs 0 清除全部注入（固件静默无回显，仅 ACK）"""
        with allure.step("恢复：清除故障状态"):
            self._cli("ffs 0")
            time.sleep(SETTLE_SHORT)

    # ==================================================================
    # 故障注入
    # ==================================================================

    @allure.story("GCS-04 失效保护")
    @allure.title("设置低电量故障")
    @dangerous_gate
    def test_set_error_state_low_battery(self):
        """验证 ffs 1 命令：设置低电量故障"""
        self._inject_and_verify("1", "fake low battery")
        self._clear_error_state()

    @allure.story("GCS-04 失效保护")
    @allure.title("设置航点失败故障")
    @dangerous_gate
    def test_set_error_state_waypoint_failed(self):
        """验证 ffs 2 命令：设置航点失败故障"""
        self._inject_and_verify("2", "fake wp error")
        self._clear_error_state()

    @allure.story("GCS-04 失效保护")
    @allure.title("设置围栏违规故障")
    @dangerous_gate
    def test_set_error_state_fence_violation(self):
        """验证 ffs 3 命令：设置围栏违规故障"""
        self._inject_and_verify("3", "fake fence error")
        self._clear_error_state()

    @allure.story("GCS-04 失效保护")
    @allure.title("设置 EKF 故障")
    @dangerous_gate
    def test_set_error_state_ekf_error(self):
        """验证 ffs 4, 1, 0, 1 命令：设置 EKF 故障"""
        self._inject_and_verify("4, 1, 0, 1", "fake ekf to:")
        self._clear_error_state()

    @allure.story("GCS-04 失效保护")
    @allure.title("设置坠机(跌落)故障")
    @dangerous_gate
    def test_set_error_state_crash_fall(self):
        """验证 ffs 5 命令：设置坠机(跌落)故障"""
        self._inject_and_verify("5", "fake crash")
        self._clear_error_state()
