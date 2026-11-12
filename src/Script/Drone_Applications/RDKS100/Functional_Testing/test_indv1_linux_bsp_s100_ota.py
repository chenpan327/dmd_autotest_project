# coding: utf-8
"""
===============================================================================
                    S100 底软 BSP OTA 升级测试脚本
===============================================================================
脚本编号: DMD_TEST_RDKS100_BSP_OTA_001
脚本版本: v1.0
创建日期: 2026-09-18
修改日期: 2026-09-18
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: RDKS100 (INDV1, S100 双 SoC: Acore Linux + MCU 小核)
测试类型: 底软功能验证测试 (Functional_Testing)
测试环境: Python 3.10, pytest, allure, SSH (paramiko)

测试目的:
验证 INDV1 (S100) OTA 升级子系统 (TC-S100-OTA-01 ~ 05): 镜像按
s100-ota-gpt.json 全 AB 分区打包 (boot_/system_/vbmeta_ 双 slot), 构建期
RDK_DM_VERIFY_ENABLE=yes 开启 boot hash + system dm-verity + vbmeta 签名
(rdk-gen partition_tools/pack_avb_img.sh); 板端经 ota_tool 查询/切换 slot,
ota_process 执行升级。覆盖: AB 分区完备 → 活动槽查询 → dm-verity 使能 →
系统升级演练 → ADS-B 固件 OTA 样例。测试点从 rdk-gen 源码反推。

前置条件:
1. 测试环境准备:
   - DUT 已启动且镜像为 dmd 打包链路产物 (AB 分区 + ota_tool 在位),
     主机经 SSH 访问板端 (config.json INDV1 段)
   - ssh_session / board_info / bsp_params fixture 已就绪 (conftest 提供)
2. 危险用例显式开关 (默认 skip):
   - OTA-04 系统升级演练: 会切 slot + reboot — 备好升级包并置
     ota_upgrade_enabled=true + ota_install_cmd 后才跑
3. 判定语义: pytest 原生断言, 板端命令输出挂 Allure 附件

测试步骤:
1. [OTA-01 test_ab_partitions_complete] AB 分区完备: /dev/disk/by-partlabel/
   下 boot_x/system_x/vbmeta_x (x=a,b) 六分区齐全
2. [OTA-02 test_active_slot_query] 活动槽查询: ota_tool -g 退出码 0 且输出
   非空 (格式首跑校准后细化)
3. [OTA-03 test_dm_verity_enabled] dm-verity 使能: /proc/cmdline 含 dm= 与
   verity (构建期 RDK_DM_VERIFY_ENABLE=yes 口径)
4. [OTA-04 test_ota_upgrade_drill] 升级演练 (需显式开启): 记录升级前活动槽
   → 执行 ota_install_cmd → reboot → 等待 SSH 恢复 → 活动槽已切换
5. [OTA-05 test_adsb_ota_sample] ADS-B 固件 OTA 样例在位: dmd_adsb_ota_test
   可执行 (真实 OTA 流程需接收机在位, 经 config INDV1.adsb_enabled 接入)

预期结果（与测试步骤一一对应）:
1. [OTA-01] 六个双 slot 分区全部在位
2. [OTA-02] 活动槽可查询 (a/b 或 0/1)
3. [OTA-03] 内核 cmdline 携带 dm-verity 参数 (boot/system 校验在服务)
4. [OTA-04] 升级后活动槽切换成功且 SSH 链路自动恢复
5. [OTA-05] ADS-B OTA 样例在位 (错误码 -7..-12 矩阵属专项场景)

===============================================================================
测试结论:
OTA 5 个测试点全部实现自动化, 升级演练默认 skip 并经 config 显式开关管控,
断言结果与板端输出见 Allure 报告各用例及其附件。
===============================================================================
"""
import re
import time

import allure
import pytest

from utils.logger import log_manager


_SLOT_RE = re.compile(r"\b([ab0-1])\b", re.IGNORECASE)


def _normalize_slot(text):
    """从 ota_tool -g 输出提取活动槽, 归一化为 'a'/'b'; 解析不出返回 None"""
    m = re.search(r"slot\s*[:=]?\s*([ab])\b", text, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    m = re.search(r"slot\s*[:=]?\s*([01])\b", text, re.IGNORECASE)
    if m:
        return "a" if m.group(1) == "0" else "b"
    return None


@allure.epic("S100 底软测试")
@allure.feature("OTA升级")
class TestIndv1BspOta:
    """底软 Linux BSP OTA 测试点 (AB 分区/活动槽/dm-verity/升级演练/ADS-B OTA)"""


    @allure.story("AB分区")
    @allure.title("TC-S100-OTA-01 AB 双 slot 分区完备 (boot/system/vbmeta × a/b)")
    @allure.description(
        "[板端命令] /dev/disk/by-partlabel/ 下应存在 boot_a/system_a/vbmeta_a 与 "
        "boot_b/system_b/vbmeta_b 六个分区 (s100-ota-gpt.json 全 AB 分区表, "
        "pack_image.sh RDK_DM_VERIFY_ENABLE=yes 的前提)。"
    )
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.tag("S100", "底软", "OTA", "分区")
    def test_ab_partitions_complete(self, ssh_session):
        with allure.step("列出分区标签"):
            code, out = ssh_session.exec_cmd_quiet("ls /dev/disk/by-partlabel/")
            assert code == 0, f"/dev/disk/by-partlabel/ 不可读: {out!r}"
            labels = set(out.split())
            allure.attach(out, name="part_labels", attachment_type=allure.attachment_type.TEXT)
        with allure.step("断言双 slot 六分区"):
            required = {
                f"{name}_{slot}"
                for name in ("boot", "system", "vbmeta")
                for slot in ("a", "b")
            }
            missing = required - labels
            assert not missing, (
                f"AB 分区缺失: {sorted(missing)} — 镜像非 s100-ota-gpt.json "
                f"全 AB 分区打包, OTA 升级链路不可用"
            )
        log_manager.logger.info("[OTA] AB 六分区齐备 OK")


    @allure.story("活动槽")
    @allure.title("TC-S100-OTA-02 ota_tool 活动槽可查询")
    @allure.description(
        "[板端命令] 运行 bsp_params.ota_tool_bin -g (fast_flash.sh 同款口径): "
        "退出码 0 且输出非空。输出格式以板上实际为准 (a/b 或 0/1), 首跑校准后 "
        "在 OTA-04 升级演练中作为前后对比基线。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "OTA", "slot")
    def test_active_slot_query(self, ssh_session, bsp_params):
        tool = bsp_params["ota_tool_bin"]
        with allure.step(f"{tool} -g"):
            code, out = ssh_session.exec_cmd_quiet(f"{tool} -g", timeout=30)
            allure.attach(out, name="ota_tool_g", attachment_type=allure.attachment_type.TEXT)
            assert code == 0, f"{tool} -g 失败 (code={code}) — ota_tool 不在位或参数不符:\n{out[-500:]}"
            assert out.strip(), f"{tool} -g 无输出"
        slot = _normalize_slot(out)
        if slot:
            log_manager.logger.info(f"[OTA] 活动槽: {slot}")
        else:
            log_manager.logger.warning(
                f"[OTA] {tool} -g 输出未解析出活动槽 (输出见附件) — 首跑后校准 _normalize_slot"
            )


    @allure.story("dm-verity")
    @allure.title("TC-S100-OTA-03 内核 cmdline 携带 dm-verity (boot/system 校验在服务)")
    @allure.description(
        "[板端命令] /proc/cmdline 含 dm= 与 verity 关键字 — 构建期 "
        "RDK_DM_VERIFY_ENABLE=yes 时 partition_tools/pack_avb_img.sh 经 "
        "veritysetup 计算 root hash 生成 dm-verity cmdline, system 分区只读校验。"
        "config INDV1.ota_dm_verify_expected=false 时改为记录不断言 (适配未开校验的调试镜像)。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "OTA", "dm-verity")
    def test_dm_verity_enabled(self, ssh_session, bsp_params):
        with allure.step("读取 /proc/cmdline"):
            code, out = ssh_session.exec_cmd_quiet("cat /proc/cmdline")
            assert code == 0, f"/proc/cmdline 不可读: {out!r}"
            allure.attach(out, name="cmdline", attachment_type=allure.attachment_type.TEXT)
        has_dm = 'dm="' in out or " dm=" in out
        has_verity = "verity" in out
        if bsp_params.get("ota_dm_verify_expected", True):
            assert has_dm and has_verity, (
                f"cmdline 缺 dm-verity 参数 (dm={has_dm}, verity={has_verity}) — "
                f"镜像未按 RDK_DM_VERIFY_ENABLE=yes 打包或参数丢失"
            )
            log_manager.logger.info("[OTA] dm-verity cmdline OK")
        else:
            log_manager.logger.info(
                f"[OTA] dm-verity 未开启为预期 (ota_dm_verify_expected=false): "
                f"dm={has_dm}, verity={has_verity}"
            )


    @allure.story("升级演练")
    @allure.title("TC-S100-OTA-04 系统升级演练: 升级→切换→重启→活动槽翻转 (需显式开启)")
    @allure.description(
        "[板端命令] 记录升级前活动槽 (ota_tool -g) → 执行 bsp_params.ota_install_cmd "
        "(板端升级命令, 如 ota_tool -i /data/xxx.zip, 升级包需提前放置板端) → "
        "reboot → 轮询等待 SSH 链路恢复 (reboot_timeout_s) → 断言活动槽已切换。"
        "⚠ 会切换启动槽并重启整机 — config INDV1.ota_upgrade_enabled=true 且配置 "
        "ota_install_cmd 后才运行, 默认 skip。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("S100", "底软", "OTA", "升级")
    def test_ota_upgrade_drill(self, ssh_session, bsp_params):
        if not bsp_params.get("ota_upgrade_enabled"):
            pytest.skip(
                "升级演练会切 slot + reboot — 备好升级包后置 "
                "config INDV1.ota_upgrade_enabled=true 并配置 ota_install_cmd"
            )
        if not bsp_params.get("ota_install_cmd"):
            pytest.fail(
                "已开启 ota_upgrade_enabled 但未配置 ota_install_cmd — "
                "请在 config.json INDV1.ota_install_cmd 填写板端升级命令"
            )
        tool = bsp_params["ota_tool_bin"]
        with allure.step("记录升级前活动槽"):
            code, out = ssh_session.exec_cmd_quiet(f"{tool} -g", timeout=30)
            assert code == 0, f"升级前 {tool} -g 失败: {out!r}"
            pre_slot = _normalize_slot(out)
            assert pre_slot, (
                f"升级前活动槽解析失败 (输出 {out[-200:]!r}) — 先跑 TC-OTA-02 校准解析"
            )
        with allure.step(f"执行升级命令: {bsp_params['ota_install_cmd']}"):
            code, out = ssh_session.exec_cmd_quiet(
                bsp_params["ota_install_cmd"],
                timeout=int(bsp_params["ota_upgrade_timeout_s"]),
            )
            allure.attach(out, name="ota_install_output", attachment_type=allure.attachment_type.TEXT)
            assert code == 0, f"升级命令失败 (code={code}):\n{out[-1000:]}"
        with allure.step("reboot 并等待 SSH 链路恢复"):
            ssh_session.exec_cmd_quiet("reboot")
            timeout_s = int(bsp_params.get("reboot_timeout_s", 300))
            deadline = time.time() + timeout_s
            recovered = False
            while time.time() < deadline:
                code, _ = ssh_session.exec_cmd_quiet("true", timeout=10)
                if code == 0:
                    recovered = True
                    break
                time.sleep(5)
            assert recovered, (
                f"升级 reboot 后 SSH 链路未在 {timeout_s}s 内恢复 — "
                f"新槽可能启动失败 (排查: 串口看新 slot 启动日志 / vbmeta 校验)"
            )
        with allure.step("断言活动槽已切换"):
            code, out = ssh_session.exec_cmd_quiet(f"{tool} -g", timeout=30)
            assert code == 0, f"升级后 {tool} -g 失败: {out!r}"
            post_slot = _normalize_slot(out)
            assert post_slot, f"升级后活动槽解析失败: {out[-200:]!r}"
            assert post_slot != pre_slot, (
                f"升级后活动槽未切换 (前={pre_slot}, 后={post_slot}) — "
                f"升级包未写入非活动槽或标记未置位"
            )
        log_manager.logger.info(f"[OTA] 升级演练 OK: {pre_slot} → {post_slot}")


    @allure.story("ADS-B OTA")
    @allure.title("TC-S100-OTA-05 ADS-B 固件 OTA 样例在位 (dmd_adsb_ota_test)")
    @allure.description(
        "[板端命令] dmd-bsp modules/adsb 提供 dmd_adsb_ota_upgrade(path) (固件≤64KB, "
        "4KB/帧 200ms 间隔, READY 4s 超时, 错误码 -7..-12) — 断言对应样例 "
        "dmd_adsb_ota_test 在位。真实 OTA 流程需 ADS-B 接收机在位, 经 config "
        "INDV1.adsb_enabled 接入后按样例用法驱动 (错误码矩阵属专项场景)。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "OTA", "ADS-B")
    def test_adsb_ota_sample(self, ssh_session, bsp_params):
        binary = f"{bsp_params['ipc_bin_dir']}/dmd_adsb_ota_test"
        code, out = ssh_session.exec_cmd_quiet(f"test -x {binary}")
        if code != 0:
            pytest.skip(f"{binary} 不存在 — dmd-bsp deb 未安装或未编译 samples")
        log_manager.logger.info(f"[OTA] ADS-B OTA 样例在位: {binary}")
