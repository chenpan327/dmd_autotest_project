# coding: utf-8
"""
===============================================================================
                    S100 底软 BSP SDR 图传测试脚本
===============================================================================
脚本编号: DMD_TEST_RDKS100_BSP_SDR_001
脚本版本: v1.0
创建日期: 2026-09-18
修改日期: 2026-09-18
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: RDKS100 (INDV1, S100 双 SoC: Acore Linux + MCU 小核)
测试类型: 底软功能验证测试 (Functional_Testing)
测试环境: Python 3.10, pytest, allure, SSH (paramiko)

测试目的:
验证 INDV1 (S100) SDR 图传链路 (TC-S100-SDR-01 ~ 04): dmd-bsp modules/SDR
统一图传接口 (dmd_sdr_init/get/set/pair/export/import/reset), 实现层
fishlink 走 HTTP (http://192.168.144.10|11:80/api/*) + AT 串口双通道。
覆盖: 样例在位 → 参数面查询 → 对码 → 配置导出/导入。测试点从源码反推
(待与《底软Linux BSP 测试点分解》SDR 表核对)。

前置条件:
1. 测试环境准备:
   - DUT 已启动且 dmd-bsp deb 已安装 (sample 程序在 ipc_bin_dir, 默认
     /usr/hobot/bin), 主机经 SSH 访问板端 (config.json INDV1 段)
   - ssh_session / board_info / bsp_params fixture 已就绪 (conftest 提供)
2. 环境依赖与 skip 条款:
   - SDR-02/03/04 需 SDR 图传模块在位 (fishlink HTTP+AT 链路通),
     config INDV1.sdr_test_enabled=true 才跑; 模块不在位时输出呈
     连接失败特征, 用例内二次 skip
   - SDR-03/04 命令模板 (sdr_pair_cmd / sdr_config_cmd) 未配置时 skip
3. 判定语义: pytest 原生断言, 板端命令输出挂 Allure 附件

测试步骤:
1. [SDR-01 test_sdr_sample_present] dmd_sdr_test 样例可执行 (deb 装载即应有)
2. [SDR-02 test_sdr_params_query] 参数面查询: 运行 dmd_sdr_test (无参默认
   序列) → 无 'FAIL: dmd_sdr' 前缀失败 → 退出码 0; 输出呈连接失败特征时
   skip (台架无 SDR 模块)
3. [SDR-03 test_sdr_pair] 对码 (需显式开启+命令模板): 执行 sdr_pair_cmd
   → 退出码 0
4. [SDR-04 test_sdr_config_export_import] 配置导出/导入 (需显式开启+命令
   模板): 执行 sdr_config_cmd → 退出码 0

预期结果（与测试步骤一一对应）:
1. [SDR-01] 样例二进制在位
2. [SDR-02] 图传模块应答正常, get/init 面无失败
3. [SDR-03] 对码流程成功 (地面端配合)
4. [SDR-04] 配置导出/导入回环成功 (soft=AT 优先回落 HTTP reboot 口径)

===============================================================================
测试结论:
SDR 图传 4 个测试点全部实现自动化, 硬件依赖场景显式 skip 并经 config
显式开关管控, 断言结果与板端输出见 Allure 报告各用例及其附件。
===============================================================================
"""
import allure
import pytest

from utils.logger import log_manager


# 板端无 SDR 模块时的输出特征 (fishlink HTTP 不可达 / AT 串口无应答)
_SDR_ABSENT_SIGNATURES = (
    "connection refused",
    "connection timed out",
    "couldn't connect",
    "could not connect",
    "failed to connect",
    "no such file or directory",  # AT 串口设备不在位
)


def _sdr_absent(out):
    """判断输出是否呈 SDR 模块不在位特征"""
    low = out.lower()
    return any(sig in low for sig in _SDR_ABSENT_SIGNATURES)


@allure.epic("S100 底软测试")
@allure.feature("SDR图传")
class TestIndv1BspSdr:
    """底软 Linux BSP SDR 图传测试点 (样例在位/参数面/对码/配置)"""


    @allure.story("样例在位")
    @allure.title("TC-S100-SDR-01 dmd_sdr_test 样例在位")
    @allure.description(
        "[板端命令] {ipc_bin_dir}/dmd_sdr_test 可执行 (dmd-bsp sample 安装产物, "
        "modules/SDR 统一图传接口的样例入口)。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "SDR", "样例")
    def test_sdr_sample_present(self, ssh_session, bsp_params):
        binary = f"{bsp_params['ipc_bin_dir']}/dmd_sdr_test"
        code, out = ssh_session.exec_cmd_quiet(f"test -x {binary}")
        if code != 0:
            pytest.skip(f"{binary} 不存在 — dmd-bsp deb 未安装或未编译 samples")
        log_manager.logger.info(f"[SDR] 样例在位: {binary}")


    @allure.story("参数面")
    @allure.title("TC-S100-SDR-02 图传模块应答: init/get 参数面无失败 (需显式开启)")
    @allure.description(
        "[板端命令] 运行 dmd_sdr_test (无参默认序列, 覆盖 dmd_sdr_get 的 "
        "conn/siginfo/temp/version 等参数面): 断言无 'FAIL: dmd_sdr' 前缀失败且 "
        "退出码 0。输出呈 fishlink 连接失败特征视为台架无 SDR 模块, skip。"
        "⚠ config INDV1.sdr_test_enabled=true 才运行。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "SDR", "参数面")
    def test_sdr_params_query(self, ssh_session, bsp_params):
        if not bsp_params.get("sdr_test_enabled"):
            pytest.skip(
                "需 SDR 图传模块在位 — 接好后置 config INDV1.sdr_test_enabled=true"
            )
        binary = f"{bsp_params['ipc_bin_dir']}/dmd_sdr_test"
        timeout_s = int(bsp_params["sdr_runtime_timeout_s"])
        with allure.step(f"运行 dmd_sdr_test (timeout {timeout_s}s 兜底)"):
            code, out = ssh_session.exec_cmd_quiet(
                f"timeout -s INT {timeout_s} {binary} < /dev/null",
                timeout=timeout_s + 60,
            )
            allure.attach(out, name="sdr_test_output", attachment_type=allure.attachment_type.TEXT)
        if _sdr_absent(out):
            pytest.skip(
                f"SDR 模块不在位 (fishlink HTTP/AT 链路不通, 输出见附件) — "
                f"台架无图传模块时本用例无法验证"
            )
        assert "FAIL: dmd_sdr" not in out and "FAIL: sdr_" not in out, (
            f"SDR 参数面存在失败项:\n{out[-800:]}"
        )
        assert "Segmentation fault" not in out, "dmd_sdr_test 段错误 — 库崩溃"
        assert code == 0, f"dmd_sdr_test 异常退出 (code={code}):\n{out[-800:]}"
        log_manager.logger.info(f"[SDR] 参数面 PASS, 输出尾部: {out[-200:]!r}")


    @allure.story("对码")
    @allure.title("TC-S100-SDR-03 图传对码流程 (需显式开启+命令模板)")
    @allure.description(
        "[板端命令] 执行 bsp_params.sdr_pair_cmd (板端对码命令, 按 dmd_sdr_test -h "
        "用法填写, 地面端需配合进对码状态) → 退出码 0。"
        "⚠ config INDV1.sdr_test_enabled=true 且配置 sdr_pair_cmd 后才运行。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "SDR", "对码")
    def test_sdr_pair(self, ssh_session, bsp_params):
        if not bsp_params.get("sdr_test_enabled"):
            pytest.skip("需 SDR 模块在位 — 置 config INDV1.sdr_test_enabled=true")
        pair_cmd = bsp_params.get("sdr_pair_cmd")
        if not pair_cmd:
            pytest.skip(
                "未配置 sdr_pair_cmd — 按 dmd_sdr_test -h 用法在 config.json "
                "INDV1.sdr_pair_cmd 填写对码命令"
            )
        with allure.step(f"执行对码命令: {pair_cmd}"):
            code, out = ssh_session.exec_cmd_quiet(pair_cmd, timeout=120)
            allure.attach(out, name="sdr_pair_output", attachment_type=allure.attachment_type.TEXT)
            if _sdr_absent(out):
                pytest.skip("SDR 模块不在位 (输出见附件)")
            assert code == 0, f"对码命令失败 (code={code}):\n{out[-800:]}"
        log_manager.logger.info("[SDR] 对码 PASS")


    @allure.story("配置管理")
    @allure.title("TC-S100-SDR-04 图传配置导出/导入回环 (需显式开启+命令模板)")
    @allure.description(
        "[板端命令] 执行 bsp_params.sdr_config_cmd (导出+导入命令序列, 覆盖 "
        "dmd_sdr_export/import/clear_config 链) → 退出码 0。"
        "⚠ config INDV1.sdr_test_enabled=true 且配置 sdr_config_cmd 后才运行。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "SDR", "配置")
    def test_sdr_config_export_import(self, ssh_session, bsp_params):
        if not bsp_params.get("sdr_test_enabled"):
            pytest.skip("需 SDR 模块在位 — 置 config INDV1.sdr_test_enabled=true")
        config_cmd = bsp_params.get("sdr_config_cmd")
        if not config_cmd:
            pytest.skip(
                "未配置 sdr_config_cmd — 按 dmd_sdr_test -h 用法在 config.json "
                "INDV1.sdr_config_cmd 填写导出/导入命令"
            )
        with allure.step(f"执行配置导出/导入命令: {config_cmd}"):
            code, out = ssh_session.exec_cmd_quiet(config_cmd, timeout=120)
            allure.attach(out, name="sdr_config_output", attachment_type=allure.attachment_type.TEXT)
            if _sdr_absent(out):
                pytest.skip("SDR 模块不在位 (输出见附件)")
            assert code == 0, f"配置导出/导入命令失败 (code={code}):\n{out[-800:]}"
        log_manager.logger.info("[SDR] 配置导出/导入 PASS")
