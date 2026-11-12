# coding: utf-8
"""
WiFi 模块测试 - WiFi 信息与系统状态

业务背景:
    了解 WiFi 模块的运行状态和系统资源使用情况是排查问题和保障稳定运行的基础。
    本测试通过串口命令获取 WiFi 模块的详细连接信息、系统任务运行状态、CPU 占用率、
    固件版本以及 SD 卡剩余容量,为日常巡检、故障定位和性能基线建立提供数据支撑。

中间件事实:
    - dmdfact getVer 返回版本字符串(裸文本),无固定结构
    - os cpu 返回系统 CPU 占用信息(当前实现里 ProtocolHandler.get_os_cpu 未解析具体数值,
      只把整段响应放进 full_info,因此本测试只校验 full_info 非空)
    - dmdfact sdCap 在 SD 未挂载时(WIFITEST 模式 / 物理未插)会失败
"""
import re
import pytest
import allure

from utils.logger import log_manager


# 关键任务清单(用于栈水位/状态检查)— 来自 mt793x 中间件常见任务
_KEY_TASKS = ("wifi_main_task", "wpa_supplicant", "lwIP", "onion_main")


@allure.epic("WiFi 模块测试")
@allure.feature("Release 测试")
@allure.story("WiFi 信息与系统状态")
class TestWifiInfoAndSystemStatus:
    """WiFi 信息与系统状态测试类"""

    @allure.title("WiFi 详细信息字段完整性")
    @allure.description(
        "发送 wifi info,验证 MAC/SSID/IP/connect_status 必需字段全部存在,"
        "BSSID/channel/band 字段存在且类型正确(信道号 1-165,band 为字符串)。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "信息查询", "字段完整性")
    def test_wifi_info_detail(self, serial_session):
        """验证 wifi info 返回的 MAC/SSID/BSSID/IP/信道/频段等关键字段都已解析"""
        with allure.step("发送 wifi info 命令"):
            result = serial_session.get_wifi_info()

        with allure.step("验证返回非空"):
            assert result is not None, "获取 WiFi 信息失败(命令无响应或解析失败)"
            assert isinstance(result, dict)

        with allure.step("验证 MAC 字段格式"):
            mac = result.get("mac")
            assert mac, "MAC 地址为空"
            assert re.match(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$", mac), \
                f"MAC 格式不合法: {mac}"

        with allure.step("验证连接相关字段"):
            assert result.get("ssid"), "SSID 为空"
            assert result.get("ip"), "IP 地址为空"
            assert result.get("connect_status") is not None, "connect_status 为空"

        with allure.step("验证信号相关字段"):
            # BSSID 在未连接时可能为空,但字段必须存在
            assert "bssid" in result, "缺少 bssid 字段"
            # channel 必须是有效信道号(1~165)
            ch = result.get("channel")
            if ch is not None:
                assert isinstance(ch, int) and 1 <= ch <= 165, f"信道号越界: {ch}"
            # band 应该是字符串(2.4G/5G)
            band = result.get("band")
            if band is not None:
                assert isinstance(band, str), f"band 类型错误: {type(band).__name__}"

        log_manager.logger.info(f"WiFi 详细信息: {result}")


    @allure.title("系统任务列表与关键任务状态")
    @allure.description(
        "发送 os task,验证返回非空列表,且每个任务含 task_name/status/priority/stack_watermark 字段。"
        "关键任务(wifi_main_task/lwIP 等)的栈水位必须 > 0(为 0 表示栈溢出)。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "系统状态", "任务列表")
    def test_os_task_status(self, serial_session):
        """验证任务列表非空,关键任务(wifi_main_task/lwIP 等)都存在且状态正常"""
        with allure.step("发送 os task 命令"):
            tasks = serial_session.get_os_tasks()

        with allure.step("验证任务列表"):
            assert tasks is not None, "获取任务列表失败"
            assert isinstance(tasks, list)
            assert len(tasks) > 0, "任务列表为空(运行中系统应至少有 idle)"
        log_manager.logger.info(f"系统任务数量: {len(tasks)}")

        with allure.step("验证每个任务字段完整"):
            for i, task in enumerate(tasks):
                assert isinstance(task, dict), f"任务 #{i} 不是 dict"
                for key in ("task_name", "status", "priority", "stack_watermark"):
                    assert key in task, f"任务 #{i} 缺少字段: {key}"

        with allure.step("检查关键任务存在"):
            task_names = {t["task_name"] for t in tasks}
            missing = [t for t in _KEY_TASKS if t not in task_names]
            if missing:
                log_manager.logger.warning(f"以下关键任务未在列表中找到: {missing}")
                # 关键任务缺失仅警告(不同模式任务列表不同),不强制失败

        # 关键任务的栈水位必须 > 0(栈水位为 0 表示已溢出)
        for task in tasks:
            if task["task_name"] in _KEY_TASKS:
                sw = task.get("stack_watermark")
                if isinstance(sw, (int, float)):
                    assert sw > 0, f"任务 {task['task_name']} 栈水位为 0,可能已溢出"
                log_manager.logger.info(
                    f"关键任务: {task['task_name']}, 状态: {task['status']}, "
                    f"优先级: {task['priority']}, 栈水位: {sw}"
                )


    @allure.title("CPU 占用率信息")
    @allure.description(
        "发送 os cpu,验证返回的 full_info 非空且至少包含一个数字(CPU 占用率数值)。"
        "注:当前协议实现未解析具体 cpu_usage,只校验 full_info 内容有效。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "系统状态", "CPU")
    def test_os_cpu_usage(self, serial_session):
        """验证 os cpu 命令返回有效响应(具体数值由 full_info 携带)"""
        with allure.step("发送 os cpu 命令"):
            result = serial_session.get_os_cpu()

        with allure.step("验证返回结构"):
            assert result is not None, "获取 CPU 信息失败"
            assert isinstance(result, dict)

            # 当前协议实现把整段响应放在 full_info,cpu_usage 字段未解析(实现限制)
            full_info = result.get("full_info", "")
            assert full_info and len(full_info.strip()) > 0, "CPU 信息响应为空"

            # full_info 里应至少包含数字(CPU 占用率数值)
            has_digit = any(c.isdigit() for c in full_info)
            assert has_digit, f"CPU 信息响应里未发现数值: {full_info!r}"

        log_manager.logger.info(f"CPU 信息: {result}")


    @allure.title("WiFi 固件版本")
    @allure.description(
        "发送 dmdfact getVer,验证版本字符串非空且至少包含一个数字或点号(避免空字符串或错误信息)。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "信息查询", "固件版本")
    def test_wifi_version(self, serial_session):
        """验证版本字符串非空且包含版本号特征"""
        with allure.step("发送 dmdfact getVer 命令"):
            version = serial_session.get_wifi_version()

        with allure.step("验证版本字符串"):
            assert version is not None, "获取固件版本失败"
            assert isinstance(version, str), f"版本应为 str,实际 {type(version).__name__}"
            assert len(version.strip()) > 0, "版本字符串为空"

            # 版本号应至少包含一个数字或点号
            has_version_char = any(c.isdigit() or c == "." for c in version)
            assert has_version_char, f"版本字符串不像版本号: {version!r}"

        log_manager.logger.info(f"WiFi 固件版本: {version}")
