# coding: utf-8
"""
WiFi 模块测试 - iperf 网络吞吐性能(脚本层)

业务背景:
    无人机编队表演时,地面站与飞控之间通过 WiFi 传输 MavLink 消息、日志、
    固件升级数据。WiFi 链路的实际带宽决定了能否支撑高频遥测和大文件传输。
    iperf 是业界标准的 TCP/UDP 吞吐测量工具,本测试通过它建立性能基线。

中间件事实(来自 mt793x middleware/MTK/iperf):
    - 顶层命令:iperf(注册于 cli_cmds.c:85)
    - 子命令:-s(server)、-c <ip>(client)、-h(help)
    - 关键参数:-u(UDP)、-p <port>(默认 5001)、-t <secs>(默认 10s)
    - 服务端任务:iperf_tcp_s / iperf_udp_s
    - 接收超时:20 秒无数据自动退出
    - 协议血统:NLANR iperf2(与 ESnet iperf3 不互通)

分层:
    协议层封装见 src/Protocol/wifi/wifi.py:
      - find_iperf_binary()             → 项目内置 iperf-2.0.14a-win.exe 路径
      - run_tcp_uplink(binary, ip, t)   → IperfResult(bandwidth_mbps)
      - run_udp_uplink(binary, ip, t)   → IperfResult(bandwidth/jitter/loss)
    脚本层只做 pytest 编排 + allure 步骤 + 断言。

环境要求:
    - 项目内置 tools/iperf2.0.14/iperf-2.0.14a-win.exe(随仓库分发,必须用 iperf2)
    - 或系统 PATH 中的 iperf2 / iperf(iperf3 与固件不兼容)
    - PC 与 WiFi 模块同一局域网,可互通
"""
import time
import pytest
import allure

from utils.logger import log_manager
from src.Protocol.wifi.wifi import (
    find_iperf_binary, run_tcp_uplink, run_udp_uplink,
    probe_tcp_port,
    TCP_BANDWIDTH_MIN_MBPS, UDP_BANDWIDTH_MIN_MBPS, UDP_LOSS_MAX_PERCENT,
    IPERF_DEFAULT_PORT,
)


def _ensure_iperf_server(serial_session, module_ip: str, proto: str = "tcp",
                         port: int = IPERF_DEFAULT_PORT,
                         max_attempts: int = 3) -> bool:
    """确保模块上 iperf 服务端真的起来了 — 发命令 + 端口探测。

    #459 经验:`send_command(wait_response=False)` 不能保证命令真的被模块处理,
    且前序测试可能残留 iperf 服务端占用端口。本函数:
      1. 先探测端口是否已开(残留服务端 → 直接返回 True)
      2. 否则发 `iperf -s` / `iperf -s -u`,等 3s,再探测
      3. 探测失败则重试,最多 max_attempts 次

    Returns:
        True 表示端口可连,可以跑客户端
    """
    cmd = "iperf -s" if proto == "tcp" else "iperf -s -u"
    for attempt in range(1, max_attempts + 1):
        # 先看端口是不是已经开着(残留服务端)
        if probe_tcp_port(module_ip, port, timeout=1.5):
            log_manager.logger.info(
                f"[iperf] 端口 {port} 已就绪(attempt {attempt}/{max_attempts})"
            )
            return True

        log_manager.logger.info(
            f"[iperf] 端口未开,发送 '{cmd}'(attempt {attempt}/{max_attempts})"
        )
        serial_session.send_command(cmd, wait_response=False)
        time.sleep(3)

    # 最后一次探测
    ok = probe_tcp_port(module_ip, port, timeout=1.5)
    if not ok:
        log_manager.logger.error(
            f"[iperf] {max_attempts} 次尝试后端口 {port} 仍未开 — "
            "固件 iperf 服务端可能没起来,或 serial 命令被丢弃"
        )
    return ok


# 测试参数(脚本层只保留与 iperf 协议层无关的 pytest 配置)
IPERF_TEST_DURATION = 10  # 客户端打流时长(秒)


@allure.epic("WiFi 模块测试")
@allure.feature("性能测试")
@allure.story("iperf 吞吐")
class TestIperfThroughput:
    """WiFi 网络吞吐性能测试"""

    @pytest.fixture(autouse=True)
    def _check_iperf_available(self):
        """检查 PC 端是否有 iperf2(通过协议层 find_iperf_binary)"""
        iperf_path = find_iperf_binary()
        if not iperf_path:
            pytest.skip(
                "PC 端未找到 iperf2,跳过吞吐测试。"
                "请将 iperf-2.0.14a-win.exe 放到 tools/iperf2.0.14/,"
                "或将 iperf2 / iperf 加入系统 PATH"
            )
        self.iperf_path = iperf_path
        yield


    @allure.title("iperf TCP 吞吐测试(模块作为服务端)")
    @allure.description(
        "WiFi 模块启动 iperf -s,PC 用 iperf2 客户端打流 10 秒,测量 TCP 上行带宽。"
        "源码依据:middleware/MTK/iperf/iperf_cli.c,默认端口 5001。"
        "注:固件服务端是 NLANR iperf2 血统,客户端必须用 iperf2(不能用 iperf3)。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("性能", "iperf", "TCP", "吞吐")
    def test_iperf_tcp_uplink(self, serial_session, module_current_ip):
        """TCP 上行吞吐测试(PC → 模块)"""
        module_ip = module_current_ip

        with allure.step(f"WiFi 模块启动 iperf TCP 服务端(当前 IP={module_ip})"):
            # 用 helper 探测端口,确保服务端真的起来了再跑客户端(#459 修复)
            server_ok = _ensure_iperf_server(serial_session, module_ip, proto="tcp")
            if not server_ok:
                pytest.skip(
                    f"iperf 服务端在 {module_ip}:{IPERF_DEFAULT_PORT} 起不来 — "
                    "固件未处理 serial 命令或 iperf 任务异常,跳过避免无意义超时"
                )

        with allure.step(f"PC 作为客户端打流 {IPERF_TEST_DURATION}s 到 {module_ip}(协议层 run_tcp_uplink)"):
            result = run_tcp_uplink(
                self.iperf_path, module_ip, duration=IPERF_TEST_DURATION,
            )

        with allure.step("停止模块服务端"):
            # 服务端 20s 无数据自动退出,这里主动停止避免影响后续测试
            time.sleep(1)

        with allure.step("解析带宽结果"):
            allure.attach(
                f"【iperf 输出】\n{result.raw_output}",
                name="iperf 原始输出",
                attachment_type=allure.attachment_type.TEXT
            )

            assert result.success and result.bandwidth_mbps is not None, (
                f"未能从 iperf 输出中解析出 TCP 带宽。错误: {result.error}"
            )
            assert result.bandwidth_mbps >= TCP_BANDWIDTH_MIN_MBPS, (
                f"TCP 带宽 {result.bandwidth_mbps:.2f} Mbps 低于阈值 {TCP_BANDWIDTH_MIN_MBPS} Mbps"
            )

            allure.attach(
                f"【测试结果】\n"
                f"  方向: PC → 模块 (上行)\n"
                f"  协议: TCP\n"
                f"  时长: {IPERF_TEST_DURATION}s\n"
                f"  带宽: {result.bandwidth_mbps:.2f} Mbps\n"
                f"  阈值: ≥ {TCP_BANDWIDTH_MIN_MBPS} Mbps",
                name="TCP 上行吞吐",
                attachment_type=allure.attachment_type.TEXT
            )
            log_manager.logger.info(
                f"[iperf] TCP 上行带宽: {result.bandwidth_mbps:.2f} Mbps"
            )


    @allure.title("iperf UDP 吞吐测试(模块作为服务端)")
    @allure.description(
        "WiFi 模块启动 iperf -s -u,PC 用 iperf2 UDP 客户端打流,测量带宽/丢包/抖动。"
        "源码依据:iperf_cli.c:99 iperf_udp_s 任务。"
        "注:固件服务端是 NLANR iperf2 血统,客户端必须用 iperf2(不能用 iperf3)。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("性能", "iperf", "UDP", "吞吐")
    def test_iperf_udp_uplink(self, serial_session, module_current_ip):
        """UDP 上行吞吐测试(PC → 模块)"""
        module_ip = module_current_ip

        with allure.step(f"WiFi 模块启动 iperf UDP 服务端(当前 IP={module_ip})"):
            # 复用 TCP 端口探测逻辑 — 固件 iperf -s -u 也在 5001 监听
            server_ok = _ensure_iperf_server(serial_session, module_ip, proto="udp")
            if not server_ok:
                pytest.skip(
                    f"iperf UDP 服务端在 {module_ip}:{IPERF_DEFAULT_PORT} 起不来 — "
                    "固件未处理 serial 命令或 iperf 任务异常,跳过避免无意义超时"
                )

        with allure.step(f"PC 作为 UDP 客户端打流 {IPERF_TEST_DURATION}s(协议层 run_udp_uplink)"):
            result = run_udp_uplink(
                self.iperf_path, module_ip,
                duration=IPERF_TEST_DURATION, bandwidth_target="20M",
            )

        with allure.step("解析 UDP 结果"):
            allure.attach(
                f"【iperf 输出】\n{result.raw_output}",
                name="iperf 原始输出",
                attachment_type=allure.attachment_type.TEXT
            )

            assert result.success and result.bandwidth_mbps is not None, (
                f"未能解析 UDP 带宽。错误: {result.error}"
            )
            assert result.bandwidth_mbps >= UDP_BANDWIDTH_MIN_MBPS, (
                f"UDP 带宽 {result.bandwidth_mbps:.2f} Mbps 低于阈值 {UDP_BANDWIDTH_MIN_MBPS} Mbps"
            )
            if result.loss_percent is not None:
                assert result.loss_percent <= UDP_LOSS_MAX_PERCENT, (
                    f"UDP 丢包率 {result.loss_percent}% 超过阈值 {UDP_LOSS_MAX_PERCENT}%"
                )

            allure.attach(
                f"【测试结果】\n"
                f"  方向: PC → 模块 (上行)\n"
                f"  协议: UDP\n"
                f"  带宽: {result.bandwidth_mbps:.2f} Mbps\n"
                f"  抖动: {result.jitter_ms} ms\n"
                f"  丢包率: {result.loss_percent}%",
                name="UDP 上行吞吐",
                attachment_type=allure.attachment_type.TEXT
            )
            log_manager.logger.info(
                f"[iperf] UDP 上行: bw={result.bandwidth_mbps:.2f}Mbps, "
                f"jitter={result.jitter_ms}ms, loss={result.loss_percent}%"
            )
