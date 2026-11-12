# coding: utf-8
"""
===============================================================================
                    S100 底软 BSP 多媒体扩展测试脚本
===============================================================================
脚本编号: DMD_TEST_RDKS100_BSP_MEDIA_001
脚本版本: v1.0
创建日期: 2026-09-18
修改日期: 2026-09-18
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: RDKS100 (INDV1, S100 双 SoC: Acore Linux + MCU 小核)
测试类型: 底软功能验证测试 (Functional_Testing)
测试环境: Python 3.10, pytest, allure, SSH (paramiko)

测试目的:
验证 INDV1 (S100) 多媒体/算力扩展面 (TC-S100-MEDIA-01 ~ 03)。注意分工:
业务主流程 RTSP 端到端已由 test_indv1_linux_bsp_s100_flow.py (FLOW-04)
覆盖, 本脚本只做流程外的扩展面: 多媒体工具链盘点 → RTSP 连续多轮稳定性 →
NPU 推理运行时可导入。测试点从源码反推 (待与《底软Linux BSP 测试点分解》
核对)。

前置条件:
1. 测试环境准备:
   - DUT 已启动且 dmd-bsp deb 已安装 (sample 程序在 ipc_bin_dir, 默认
     /usr/hobot/bin), 主机经 SSH 访问板端 (config.json INDV1 段)
   - ssh_session / board_info / bsp_params fixture 已就绪 (conftest 提供)
2. 环境依赖与 skip 条款:
   - MEDIA-02 连续多轮 RTSP: 会独占 camera/FPGA (与 FLOW-04 同约束),
     config media_rtsp_repeat_test_enabled=true 才跑; camera 不在位时 skip
   - dmd 打包链路 (build_params/ubuntu-22.04_dmd_rdk-s100_release.conf) 的
     RDK_DPKG_DEB_PKG_LIST 不含 sp-samples/multimedia-samples, 相关二进制
     不在位只记录不判失败
3. 判定语义: pytest 原生断言, 板端命令输出挂 Allure 附件

测试步骤:
1. [MEDIA-01 test_media_toolchain_inventory] 工具链盘点: dmd-bsp 侧
   dmd_encode_manual_test/dmd_rtsp_test/dmd_foxglove_test 必须在位;
   VPU 样例 (media_codec_bin) 等平台侧二进制记录在位性
2. [MEDIA-02 test_rtsp_repeat_stability] RTSP 连续多轮稳定性 (需显式开启):
   连续 media_rtsp_repeat_runs 轮 dmd_rtsp_test -n {frames}, 各轮
   sent≥期望 2/3 且 fail≤3 且 feeds>0, 末轮出帧不低于首轮 50%
3. [MEDIA-03 test_npu_runtime_import] NPU 推理运行时可导入: 板端 python3
   执行 npu_import_probe (默认 import hbm_runtime) 退出码 0

预期结果（与测试步骤一一对应）:
1. [MEDIA-01] dmd-bsp 多媒体样例齐全, 平台侧样例在位性留档
2. [MEDIA-02] 多轮运行帧率稳定不衰减 (编码/推流链路无累积性劣化)
3. [MEDIA-03] hbm_runtime (hobot-dnn pybind11 绑定) 可导入

===============================================================================
测试结论:
多媒体扩展 3 个测试点全部实现自动化, 独占资源场景显式 skip 并经 config
显式开关管控, 断言结果与板端输出见 Allure 报告各用例及其附件。
===============================================================================
"""
import re

import allure
import pytest

from utils.logger import log_manager


# 与 FLOW-04 同款 [stats] 行解析口径
_STATS_RE = re.compile(
    r"\[stats\] sent=(\d+) fail=(\d+) \| rtsp feeds=(\d+) bytes=(\d+)"
    r" dropped=(\d+) fifo_overwrite=(\d+) clients=(\d+)"
)


@allure.epic("S100 底软测试")
@allure.feature("多媒体扩展")
class TestIndv1BspMedia:
    """底软 Linux BSP 多媒体扩展测试点 (工具链盘点/RTSP 稳定性/NPU)"""


    @allure.story("工具链盘点")
    @allure.title("TC-S100-MEDIA-01 多媒体工具链在位盘点")
    @allure.description(
        "[板端命令] dmd-bsp 侧 dmd_encode_manual_test / dmd_rtsp_test / "
        "dmd_foxglove_test 必须在位 (dmd-bsp deb 装载即应有); 平台侧 VPU 编解码"
        "样例 (media_codec_bin, 默认 /app/multimedia_samples/sample_codec) 属 "
        "sp-samples/multimedia-samples 包 — dmd 打包链路默认不含, 在位性只记录。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "多媒体", "盘点")
    def test_media_toolchain_inventory(self, ssh_session, bsp_params):
        with allure.step("dmd-bsp 多媒体样例在位 (必须)"):
            required = ("dmd_encode_manual_test", "dmd_rtsp_test", "dmd_foxglove_test")
            for name in required:
                path = f"{bsp_params['ipc_bin_dir']}/{name}"
                code, out = ssh_session.exec_cmd_quiet(f"test -x {path}")
                assert code == 0, (
                    f"{path} 不存在 — dmd-bsp deb 未安装或未编译 samples"
                )
        with allure.step("平台侧样例在位性记录"):
            optional = {
                "sample_codec (VPU 编解码)": bsp_params["media_codec_bin"],
            }
            for desc, path in optional.items():
                code, _ = ssh_session.exec_cmd_quiet(f"test -x {path}")
                if code == 0:
                    log_manager.logger.info(f"[MEDIA] 平台样例在位: {desc} -> {path}")
                else:
                    log_manager.logger.warning(
                        f"[MEDIA] 平台样例不在位 (仅记录): {desc} -> {path} — "
                        f"dmd 打包链路默认不含 sp-samples/multimedia-samples"
                    )
        log_manager.logger.info("[MEDIA] 工具链盘点 OK")


    @allure.story("RTSP稳定性")
    @allure.title("TC-S100-MEDIA-02 RTSP 连续多轮稳定性: 帧率不衰减 (需显式开启)")
    @allure.description(
        "[板端命令] 连续 media_rtsp_repeat_runs 轮 dmd_rtsp_test -n {frames}: "
        "各轮 [stats] sent≥期望帧数 2/3、fail≤3、rtsp feeds>0, 且末轮 sent 不低于 "
        "首轮 50% (编码/推流链路无累积性劣化)。⚠ 会独占 camera/FPGA (与 FLOW-04 "
        "同约束) — config INDV1.media_rtsp_repeat_test_enabled=true 才运行; "
        "camera 不在位时 skip。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "多媒体", "RTSP", "稳定性")
    def test_rtsp_repeat_stability(self, ssh_session, bsp_params):
        if not bsp_params.get("media_rtsp_repeat_test_enabled"):
            pytest.skip(
                "连续多轮 RTSP 会独占 camera/FPGA — 确认环境后置 "
                "config INDV1.media_rtsp_repeat_test_enabled=true"
            )
        binary = f"{bsp_params['ipc_bin_dir']}/dmd_rtsp_test"
        code, out = ssh_session.exec_cmd_quiet(f"test -x {binary}")
        assert code == 0, f"{binary} 不存在 — dmd-bsp deb 未安装"
        frames = int(bsp_params["media_rtsp_frames"])
        runs = int(bsp_params["media_rtsp_repeat_runs"])
        sent_per_run = []
        for run_idx in range(1, runs + 1):
            with allure.step(f"第 {run_idx}/{runs} 轮 dmd_rtsp_test -n {frames}"):
                code, out = ssh_session.exec_cmd_quiet(
                    f"{binary} -n {frames}", timeout=300
                )
                allure.attach(
                    out, name=f"rtsp_run{run_idx}_output",
                    attachment_type=allure.attachment_type.TEXT,
                )
                if "not found" in out and "dmd_camera_init" in out:
                    pytest.skip(
                        f"camera sensor 不在位 (dmd_camera_init 探测 chip_id 失败) — "
                        f"接入摄像头后重跑: {out.strip()[:200]}"
                    )
                assert "cam0 up" in out, f"第 {run_idx} 轮 camera 管线未建立:\n{out[-600:]}"
                assert "RTSP up" in out, f"第 {run_idx} 轮 RTSP 服务未起来:\n{out[-600:]}"
                stats = _STATS_RE.findall(out)
                assert stats, f"第 {run_idx} 轮无 [stats] 输出:\n{out[-600:]}"
                sent, fail, feeds = (int(x) for x in stats[-1][:3])
                assert sent >= frames * 2 // 3, (
                    f"第 {run_idx} 轮出帧 {sent} < 期望 {frames} 的 2/3"
                )
                assert fail <= 3, f"第 {run_idx} 轮编码失败帧 {fail} > 3"
                assert feeds > 0, f"第 {run_idx} 轮 RTSP feeds=0 — 码流未进入 FIFO"
                sent_per_run.append(sent)
                log_manager.logger.info(f"[MEDIA] 第 {run_idx} 轮 sent={sent} fail={fail}")
        with allure.step("轮间稳定性比对"):
            if runs >= 2:
                assert sent_per_run[-1] >= sent_per_run[0] * 0.5, (
                    f"多轮出帧衰减明显: {[s for s in sent_per_run]} — "
                    f"编码/推流链路存在累积性劣化 (泄漏/资源未释放?)"
                )
        log_manager.logger.info(f"[MEDIA] RTSP {runs} 轮稳定性 OK: sent={sent_per_run}")


    @allure.story("NPU运行时")
    @allure.title("TC-S100-MEDIA-03 NPU 推理运行时 hbm_runtime 可导入")
    @allure.description(
        "[板端命令] 板端 python3 执行 bsp_params.npu_import_probe (默认 "
        "'python3 -c \'import hbm_runtime\''): hobot-dnn deb 提供 pybind11 绑定 "
        "(HB_HBMRuntime), pydev_demo 系 AI 样例的运行时基座。镜像含 hobot-dnn "
        "(RDK_DPKG_DEB_PKG_LIST) 时应可导入; 模块名与镜像实际不符时按报错校准探针。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "多媒体", "NPU")
    def test_npu_runtime_import(self, ssh_session, bsp_params):
        probe = bsp_params["npu_import_probe"]
        with allure.step(f"执行导入探针: {probe}"):
            code, out = ssh_session.exec_cmd_quiet(probe, timeout=60)
            allure.attach(out, name="npu_import_output", attachment_type=allure.attachment_type.TEXT)
            if "python3: command not found" in out or "not found" in out.lower() and "python" in out.lower():
                pytest.skip("板端无 python3 — 本镜像未预装板端 Python 工具链")
            if "ModuleNotFoundError" in out:
                pytest.fail(
                    f"hbm_runtime 不可导入 — 镜像缺 hobot-dnn deb 或 python 绑定未装"
                    f"(核对 RDK_DPKG_DEB_PKG_LIST / 绑定安装路径), 报错:\n{out[-500:]}"
                )
            assert code == 0, f"NPU 运行时导入失败 (code={code}):\n{out[-500:]}"
        log_manager.logger.info("[MEDIA] hbm_runtime 导入 OK")
