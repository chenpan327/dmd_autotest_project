# coding: utf-8
"""
WiFi 模块测试全局 Fixture

从 config.json 读取 Wifi_Module 配置，提供：
    - 串口连接 fixture
    - FTP 连接 fixture
    - 配置参数 fixture（SSID、网关、MavLink IP 等）

注意：--device_type、--test_suites、--mavlink_version 已在项目根目录 conftest.py 中注册，
      此处无需重复注册。
"""
import json
import os
import time
import pytest
from pathlib import Path
from utils.logger import log_manager
from utils.common import get_project_root
from src.Protocol.airplane.Serial_Protocol_Lite import ProtocolHandler
from src.Protocol.wifi.wifi_ftp_helper import WifiFtpHelper


def load_wifi_config() -> dict:
    """
    从 config.json 加载 Wifi_Module 配置

    Returns:
        Wifi_Module 配置字典
    """
    project_root = Path(get_project_root())
    config_path = project_root / "config.json"

    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    wifi_config = config.get("Wifi_Module", {})
    if not wifi_config:
        raise KeyError("config.json 中未找到 Wifi_Module 配置项")

    return wifi_config


def print_test_banner(device_type: str, test_suites: str, wifi_config: dict):
    """
    在测试执行前打印测试环境信息，便于日志排查问题

    Args:
        device_type: 设备类型（如 Wifi_Module）
        test_suites: 测试套件名称（如 Functional_Testing）
        wifi_config: Wifi_Module 配置字典
    """
    banner = f"""

============================================================
  WiFi Module 测试环境信息
============================================================
  设备类型：    {device_type}
  测试套件：    {test_suites}
------------------------------------------------------------
  串口端口：    {wifi_config.get('serial_port', '未配置')}
  串口波特率：  {wifi_config.get('serial_baudrate', '未配置')}
  FTP 主机：    {wifi_config.get('ftp_host', '未配置')}
  MavLink IP：  {wifi_config.get('mavlink_target_ip', '未配置')}
  MavLink 端口：{wifi_config.get('mavlink_target_port', '未配置')}
  测试 SSID：   {wifi_config.get('test_ssid', '未配置')}
  测试网关：    {wifi_config.get('test_gateway', '未配置')}
============================================================
"""
    log_manager.logger.info(banner)


@pytest.fixture(scope="session", autouse=True)
def print_startup_info(wifi_config, pytestconfig):
    """
    会话级自动执行 fixture
    在测试会话开始时打印一次测试环境信息
    """
    device_type = pytestconfig.getoption("device_type", default="Wifi_Module")
    test_suites = pytestconfig.getoption("test_suites", default="Unknown")
    print_test_banner(device_type, test_suites, wifi_config)


@pytest.fixture(scope="session", autouse=True)
def _reset_wifi_module_ip(serial_session, test_params):
    """会话级自动执行:把 WiFi 模块 IP 重置到 config mavlink_target_ip。

    为什么需要:#459 7 个 GCS 用例失败,根因是上次测试改了 IP 没还原,
    WiFi 模块启动后停在 .101,但 config mavlink_target_ip 是 .200。
    本 fixture 在会话开始时无条件重置,保证后续用例从已知状态出发。
    """
    target_ip = test_params["mavlink_target_ip"]
    try:
        current = serial_session.get_ip_address()
        if not current:
            log_manager.logger.warning(
                "[Session-Reset] 无法读取 WiFi 模块当前 IP,跳过重置"
            )
            return
        if current == target_ip:
            log_manager.logger.info(
                f"[Session-Reset] WiFi 模块 IP 已是 {target_ip},无需重置"
            )
            return
        log_manager.logger.warning(
            f"[Session-Reset] WiFi 模块当前 IP={current},"
            f"与 config mavlink_target_ip={target_ip} 不一致,执行重置"
        )
        serial_session.change_ip_config(target_ip)
        time.sleep(3)
        new_ip = serial_session.get_ip_address()
        if new_ip == target_ip:
            log_manager.logger.info(f"[Session-Reset] 重置成功: {current} -> {new_ip}")
        else:
            log_manager.logger.error(
                f"[Session-Reset] 重置后 IP={new_ip},期望 {target_ip} — "
                "后续用例可能仍受 IP 漂移影响"
            )
    except Exception as e:
        log_manager.logger.warning(f"[Session-Reset] IP 重置异常: {e}")


@pytest.fixture(scope="session")
def wifi_config():
    """
    会话级 WiFi 配置 fixture

    提供 config.json 中的 Wifi_Module 配置
    """
    return load_wifi_config()


@pytest.fixture(scope="session")
def serial_session(wifi_config):
    """
    会话级串口连接 fixture

    从 config.json 读取 serial_port 和 serial_baudrate
    整个测试会话只连接一次
    """
    port = wifi_config.get("serial_port")
    baudrate = wifi_config.get("serial_baudrate", 921600)

    log_manager.logger.info(f"[WiFi-Serial] 正在连接串口: {port} @ {baudrate}")

    if not port:
        log_manager.logger.error("[WiFi-Serial] config.json 中未配置 serial_port，跳过测试")
        pytest.skip("config.json 中未配置 Wifi_Module.serial_port，跳过测试")

    handler = ProtocolHandler()
    success = handler.connect(port=port, baudrate=baudrate)
    if not success:
        log_manager.logger.error(f"[WiFi-Serial] 串口连接失败: {port} @ {baudrate}，跳过所有测试")
        pytest.skip(f"串口连接失败 ({port}, {baudrate})，跳过所有测试")

    log_manager.logger.info(f"[WiFi-Serial] 串口连接成功: {port} @ {baudrate}")
    yield handler
    log_manager.logger.info(f"[WiFi-Serial] 正在断开串口: {port}")
    handler.disconnect()


@pytest.fixture(scope="session")
def serial_fc_session(wifi_config):
    """FC MAVLink 串口(session 级)— 接 WiFi 模块 UART1,用于心跳透传测试。

    与 serial_session 同类(ProtocolHandler)不同实例:serial_session 接 UART0(CLI),
    本 fixture 接 UART1(FC MAVLink),实例隔离可并存。
    缺 serial_fc_port 视为未接 UART1 硬件,SKIP 心跳透传用例。
    """
    port = wifi_config.get("serial_fc_port")
    baudrate = wifi_config.get("serial_fc_baudrate", 115200)

    log_manager.logger.info(f"[WiFi-Serial-FC] 正在连接 UART1: {port} @ {baudrate}")

    if not port:
        pytest.skip("config.json 未配置 Wifi_Module.serial_fc_port — 心跳透传测试跳过")

    handler = ProtocolHandler()
    success = handler.connect(port=port, baudrate=baudrate)
    if not success:
        pytest.skip(f"UART1 串口连接失败: {port} @ {baudrate}")

    log_manager.logger.info(f"[WiFi-Serial-FC] UART1 连接成功: {port} @ {baudrate}")
    yield handler
    log_manager.logger.info(f"[WiFi-Serial-FC] 正在断开 UART1: {port}")
    handler.disconnect()


@pytest.fixture(scope="session")
def ftp_session(wifi_config, serial_session):
    """
    会话级 FTP 连接 fixture

    从 config.json 强制读取 ftp_host、ftp_user、ftp_passwd(缺任一 key 立即报错),
    但 ftp_host 默认使用 WiFi 模块当前 IP(通过 dmdcicd getIp 获取),
    以确保在 IP 变更后仍能连接 FTP。
    """
    # fail-fast:账号密码必须在 config.json 里,不允许静默使用默认值
    config_host = wifi_config["ftp_host"]
    user = wifi_config["ftp_user"]
    passwd = wifi_config["ftp_passwd"]

    # 优先使用 WiFi 模块当前 IP(IP 变更后仍可连 FTP),获取失败回退到 config 的 ftp_host
    try:
        current_ip = serial_session.get_ip_address()
        if current_ip:
            log_manager.logger.info(f"[WiFi-FTP] WiFi 模块当前 IP: {current_ip}，使用该地址连接 FTP")
            host = current_ip
        else:
            host = config_host
    except Exception as e:
        log_manager.logger.warning(f"[WiFi-FTP] 获取 WiFi 模块当前 IP 失败，使用配置地址 {config_host}: {e}")
        host = config_host

    log_manager.logger.info(f"[WiFi-FTP] 正在连接 FTP: {host}")
    helper = WifiFtpHelper(host=host, user=user, passwd=passwd)
    yield helper
    log_manager.logger.info(f"[WiFi-FTP] 正在断开 FTP: {host}")
    helper.disconnect()


@pytest.fixture
def module_current_ip(serial_session, test_params):
    """
    函数级 fixture:每个测试用例运行时实时查询 WiFi 模块的当前 IP。

    为什么需要这个 fixture:
        test_wifi_network_config.py 用 chgIp 修改 IP 后,fixture teardown 还原的
        是 "测试开始前的 IP",不一定是 config.json 的 mavlink_target_ip。
        如果某测试硬编码 mavlink_target_ip 连模块,但模块当前 IP 是 chgIp 改过
        的另一个值(如 172.16.0.101),TCP/UDP 连接会超时(#452 iperf 失败根因)。

    Returns:
        模块当前 IP 字符串;查询失败回退到 config.json 的 mavlink_target_ip
    """
    config_ip = test_params["mavlink_target_ip"]
    try:
        current_ip = serial_session.get_ip_address()
        if current_ip:
            if current_ip != config_ip:
                log_manager.logger.info(
                    f"[module_current_ip] 模块当前 IP={current_ip} 与 config "
                    f"mavlink_target_ip={config_ip} 不同,使用当前 IP"
                )
            return current_ip
    except Exception as e:
        log_manager.logger.warning(
            f"[module_current_ip] 获取当前 IP 失败,使用 config 默认 {config_ip}: {e}"
        )
    return config_ip


@pytest.fixture(scope="session")
def mavlink_version():
    """读取 MAVLink 版本号：仅从 config.json 的 Wifi_Module.mavlink_version 获取"""
    wifi_config = load_wifi_config()
    version = wifi_config.get("mavlink_version", "")
    if not version:
        raise KeyError(
            "config.json 的 Wifi_Module 中未配置 mavlink_version，"
            "请在 config.json 的 Wifi_Module 节中添加 \"mavlink_version\" 字段（例如 \"41\"）"
        )
    log_manager.logger.info(f"MAVLink 版本号（Wifi_Module）：{version}")
    return str(version)


@pytest.fixture(scope="session")
def test_params(wifi_config):
    """
    会话级测试参数 fixture(fail-fast)

    所有 key 必须存在于 config.json 的 Wifi_Module 节中,缺任一 key 立即抛 KeyError,
    避免脚本层用错误的 fallback 值静默继续跑测试。
    脚本里直接用 test_params["key"](下标访问),不要再写 test_params.get(key, default)。
    """
    required_keys = (
        "test_ssid", "test_ssid_alt", "test_gateway",
        "mavlink_target_ip", "mavlink_target_port",
        "test_ip_alternate", "test_ip_alternate_full",
        "gcs_local_ip", "gcs_local_port",
        "uav_power_supply_type",
    )
    missing = [k for k in required_keys if k not in wifi_config]
    if missing:
        raise KeyError(
            f"config.json 的 Wifi_Module 节缺少必需 key: {missing}。"
            f"请在 config.json 中补齐后再运行测试。"
        )
    return {k: wifi_config[k] for k in required_keys}
