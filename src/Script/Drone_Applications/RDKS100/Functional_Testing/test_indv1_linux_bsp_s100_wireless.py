# coding: utf-8
"""
===============================================================================
                    S100 底软 BSP 无线子系统测试脚本
===============================================================================
脚本编号: DMD_TEST_RDKS100_BSP_WLAN_001
脚本版本: v1.0
创建日期: 2026-09-18
修改日期: 2026-09-18
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: RDKS100 (INDV1, S100 双 SoC: Acore Linux + MCU 小核)
测试类型: 底软功能验证测试 (Functional_Testing)
测试环境: Python 3.10, pytest, allure, SSH (paramiko)

测试目的:
验证 INDV1 (S100) 无线子系统 (TC-S100-WLAN-01 ~ 03): hobot-wifi deb 提供
wifi_init/wifi_connect (hostapd/wpa_supplicant + NetworkManager) 与
hobot-wifi/hobot-bluetooth 服务, sysinfo 侧 WIFI 查询走 nl80211 genetlink。
覆盖: 服务与网口在位 → WiFi 入网连通 → 蓝牙在位。测试点从源码反推
(待与《底软Linux BSP 测试点分解》核对)。

前置条件:
1. 测试环境准备:
   - DUT 已启动且镜像含 hobot-wifi deb, 主机经 SSH 访问板端
     (config.json INDV1 段; 注意无线用例走 SSH 而非 WiFi 通道, 防断连)
   - ssh_session / board_info / bsp_params fixture 已就绪 (conftest 提供)
2. 环境依赖与 skip 条款:
   - WLAN-01/03: 镜像未含 hobot-wifi/hobot-bluetooth 服务单原则 skip;
     无线模块未上电 (无 wlan*/hci* 接口) 则 skip
   - WLAN-02 入网连通: 需可入网 AP, config INDV1.wifi_test_enabled=true
     且配置 wifi_ssid/wifi_psk 后才跑
3. 判定语义: pytest 原生断言, 板端命令输出挂 Allure 附件

测试步骤:
1. [WLAN-01 test_wifi_service_and_iface] 服务与网口在位: hobot-wifi.service
   单元存在 → 扫描 wlan*/mlan* 无线接口
2. [WLAN-02 test_wifi_connect_ping] WiFi 入网连通 (需显式开启): nmcli 连接
   wifi_ssid/wifi_psk → 断言激活成功 → ping 网关 (或 wifi_ping_target)
3. [WLAN-03 test_bluetooth_present] 蓝牙在位: hobot-bluetooth.service 单元
   存在 → hci* 适配器在位

预期结果（与测试步骤一一对应）:
1. [WLAN-01] 服务单元存在且无线接口已注册
2. [WLAN-02] 入网激活成功且网关可达
3. [WLAN-03] 蓝牙服务单元与适配器在位

===============================================================================
测试结论:
无线子系统 3 个测试点全部实现自动化, 硬件依赖场景显式 skip 并经 config
显式开关管控, 断言结果与板端输出见 Allure 报告各用例及其附件。
===============================================================================
"""
import re

import allure
import pytest

from utils.logger import log_manager


@allure.epic("S100 底软测试")
@allure.feature("无线子系统")
class TestIndv1BspWireless:
    """底软 Linux BSP 无线子系统测试点 (WiFi 服务/入网/蓝牙)"""


    @allure.story("服务在位")
    @allure.title("TC-S100-WLAN-01 hobot-wifi 服务在位且无线接口已注册")
    @allure.description(
        "[板端命令] systemctl list-unit-files 存在 hobot-wifi.service (镜像含 "
        "hobot-wifi deb); ip -o link 扫描 wlan*/mlan* 无线接口 (驱动加载 + "
        "固件就绪的标志)。接口不在位 = 无线模块未上电/未接天线, skip。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "无线", "WiFi")
    def test_wifi_service_and_iface(self, ssh_session):
        with allure.step("hobot-wifi 服务单元存在"):
            code, out = ssh_session.exec_cmd_quiet(
                "systemctl list-unit-files hobot-wifi.service --no-legend"
            )
            if code != 0 or not out.strip():
                pytest.skip("镜像未含 hobot-wifi.service 单元 — 未装 hobot-wifi deb")
        with allure.step("扫描无线接口"):
            code, out = ssh_session.exec_cmd_quiet("ip -o link show")
            assert code == 0, f"ip link 不可读: {out!r}"
            ifaces = [
                m.group(1) for m in
                (re.match(r"\d+:\s+(\w+[^:@]*)", ln) for ln in out.splitlines())
                if m
            ]
            wlan_ifaces = [x for x in ifaces if x.startswith(("wlan", "mlan"))]
            if not wlan_ifaces:
                pytest.skip(
                    f"无 wlan*/mlan* 接口 (现有: {ifaces}) — 无线模块未上电或驱动未起"
                )
        log_manager.logger.info(f"[WLAN] 服务在位, 无线接口: {wlan_ifaces}")


    @allure.story("入网连通")
    @allure.title("TC-S100-WLAN-02 WiFi 入网且网关可达 (需显式开启)")
    @allure.description(
        "[板端命令] nmcli device wifi connect '<wifi_ssid>' password '<wifi_psk>' "
        "(root, NetworkManager) → 激活成功 → ping 连通目标 (wifi_ping_target, "
        "空则 ping 默认网关) 断言 ≥1 包应答。⚠ 需可入网 AP — config "
        "INDV1.wifi_test_enabled=true 且配置 wifi_ssid/wifi_psk 后才运行。"
        "注意: 测试通道走 SSH 有线/跳板, WiFi 断连不影响用例上报。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "无线", "WiFi", "连通")
    def test_wifi_connect_ping(self, ssh_session, bsp_params):
        if not bsp_params.get("wifi_test_enabled"):
            pytest.skip(
                "需可入网 AP — 置 config INDV1.wifi_test_enabled=true 并配置 "
                "wifi_ssid/wifi_psk"
            )
        ssid = bsp_params.get("wifi_ssid")
        psk = bsp_params.get("wifi_psk")
        if not ssid or not psk:
            pytest.fail(
                "已开启 wifi_test_enabled 但未配置 wifi_ssid/wifi_psk — "
                "请在 config.json INDV1 节补齐"
            )
        with allure.step(f"nmcli 连接 {ssid}"):
            code, out = ssh_session.exec_cmd_quiet(
                f'nmcli device wifi connect "{ssid}" password "{psk}"',
                timeout=90,
            )
            allure.attach(out, name="nmcli_connect", attachment_type=allure.attachment_type.TEXT)
            assert code == 0, f"WiFi 连接失败 (code={code}):\n{out[-600:]}"
        with allure.step("确定连通目标 (网关或 wifi_ping_target)"):
            target = bsp_params.get("wifi_ping_target")
            if not target:
                code, out = ssh_session.exec_cmd_quiet("ip route show default")
                m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", out)
                assert m, f"无默认路由, 且未配置 wifi_ping_target: {out!r}"
                target = m.group(1)
        with allure.step(f"ping {target}"):
            code, out = ssh_session.exec_cmd_quiet(
                f"ping -c 3 -W 2 {target}", timeout=30
            )
            allure.attach(out, name="wifi_ping", attachment_type=allure.attachment_type.TEXT)
            ok_pkts = len(re.findall(r"time=\d+", out))
            assert ok_pkts >= 1, (
                f"ping {target} 3 发 0 应答 — WiFi 已激活但无转发 "
                f"(AP 未放行 / 上联断开):\n{out[-300:]}"
            )
        log_manager.logger.info(f"[WLAN] 入网连通 OK: {ssid} -> {target} ({ok_pkts}/3 应答)")


    @allure.story("蓝牙在位")
    @allure.title("TC-S100-WLAN-03 蓝牙服务单元与适配器在位")
    @allure.description(
        "[板端命令] systemctl list-unit-files 存在 hobot-bluetooth.service; "
        "hciconfig/bluetoothctl 扫描 hci* 适配器。适配器不在位 = 蓝牙模块未上电, "
        "skip 而非 fail (与 WLAN-01 无线接口口径一致)。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("S100", "底软", "无线", "蓝牙")
    def test_bluetooth_present(self, ssh_session):
        with allure.step("hobot-bluetooth 服务单元存在"):
            code, out = ssh_session.exec_cmd_quiet(
                "systemctl list-unit-files hobot-bluetooth.service --no-legend"
            )
            if code != 0 or not out.strip():
                pytest.skip("镜像未含 hobot-bluetooth.service 单元 — 未装或镜像裁剪")
        with allure.step("扫描 hci 适配器"):
            code, out = ssh_session.exec_cmd_quiet(
                "hciconfig 2>/dev/null || bluetoothctl list 2>/dev/null"
            )
            hci_list = re.findall(r"hci\d+", out)
            if not hci_list:
                pytest.skip(
                    "无 hci* 适配器 — 蓝牙模块未上电 (startbt 未执行/器件不在位)"
                )
        log_manager.logger.info(f"[WLAN] 蓝牙在位: {hci_list}")
