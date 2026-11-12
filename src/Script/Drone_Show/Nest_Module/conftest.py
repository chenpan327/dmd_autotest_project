# coding: utf-8
"""
机巢固件测试全局 Fixture

从 config.json 读取 Nest_Module 配置, 提供:
    - ssh / 调试串口 / adb 三通道远程执行 fixture
    - sftp 文件传输 fixture
    - 测试参数 fixture (fail-fast: 缺任一 key 立即抛 KeyError)

注意: --device_type / --test_suites / --mavlink_version 已在项目根目录 conftest.py 注册,
      此处无需重复注册。

源码对齐: dmdnest 应用层三进程 (gateWay/ppsManager/chargeCtrl) 的 UDP 端口分别为
          14651/14652/14653 (见 nestConfig.hpp), 已在 config.json 暴露。
"""
import json
import time
import pytest
from pathlib import Path

from utils.logger import log_manager
from utils.common import get_project_root
from src.Physical.Nest.nest_remote_helper import NestRemoteHelper
from src.Physical.Nest.nest_sftp_helper import NestSftpHelper


def load_nest_config() -> dict:
    """从 config.json 加载 Nest_Module 配置 (fail-fast: 缺节立即抛 KeyError)"""
    project_root = Path(get_project_root())
    config_path = project_root / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    nest_config = config.get("Nest_Module")
    if not nest_config:
        raise KeyError("config.json 中未找到 Nest_Module 配置项")
    return nest_config


def print_test_banner(device_type: str, test_suites: str, nest_config: dict):
    """测试会话开始时打印环境信息, 便于日志排查"""
    banner = f"""

============================================================
  机巢 (Dmd_Nest) 测试环境信息
============================================================
  设备类型:      {device_type}
  测试套件:      {test_suites}
------------------------------------------------------------
  机巢 IP:       {nest_config.get('nest_ip', '未配置')}
  SSH 端口:      {nest_config.get('ssh_port', '未配置')}
  调试串口:      {nest_config.get('debug_serial_port', '未配置')}
  ADB 序列号:    {nest_config.get('adb_serial', '未配置 (默认禁用)')}
  GCS 地址:      {nest_config.get('gcs_local_ip', '未配置')}
  MAVLink 端口:  {nest_config.get('nest_mavlink_port', '未配置')}
  固件进程:      {nest_config.get('nest_processes', '未配置')}
============================================================
"""
    log_manager.logger.info(banner)


@pytest.fixture(scope="session", autouse=True)
def print_startup_info(nest_config, pytestconfig):
    device_type = pytestconfig.getoption("device_type", default="Nest_Module")
    test_suites = pytestconfig.getoption("test_suites", default="Unknown")
    print_test_banner(device_type, test_suites, nest_config)


@pytest.fixture(scope="session")
def nest_config():
    """会话级 Nest_Module 配置字典"""
    return load_nest_config()


@pytest.fixture(scope="session")
def test_params(nest_config):
    """
    会话级测试参数 fixture (fail-fast)

    所有 key 必须存在于 config.json 的 Nest_Module 节, 缺任一 key 立即抛 KeyError。
    脚本里直接用 test_params["key"] 下标访问, 不要 test_params.get(key, default)。
    """
    required_keys = (
        "nest_ip", "ssh_port", "ssh_user", "ssh_passwd",
        "debug_serial_port", "debug_serial_baudrate", "nest_adb_enabled",
        "sftp_user", "sftp_passwd",
        "eth_iface", "eth_netmask",
        "gcs_local_ip", "gcs_local_port",
        "nest_mavlink_port", "pps_udp_port", "charge_udp_port",
        "uart_devs", "nest_processes",
        "baseline_ip", "alternate_ip",
        "userdata_path", "play_path", "update_img_path",
        "log_path_gateWay", "log_path_chargeCtrl", "log_path_ppsManager",
        "config_path", "camera_http_port",
        "df_userdata_min_mb", "df_sdcard_min_gb",
        "cpu_max_percent", "disk_usage_warn_percent",
        "aging_loop_count", "aging_mem_drop_max_percent",
    )
    missing = [k for k in required_keys if k not in nest_config]
    if missing:
        raise KeyError(
            f"config.json 的 Nest_Module 节缺少必需 key: {missing}。"
            f"请在 config.json 中补齐后再运行测试。"
        )
    return {k: nest_config[k] for k in required_keys}


@pytest.fixture(scope="session")
def ssh_session(nest_config, test_params):
    """
    会话级 SSH 通道 fixture

    通过 NestRemoteHelper 在机巢 Linux 控制台执行命令。
    缺 nest_ip 或 ssh_user 视为未配置, skip 所有依赖本 fixture 的用例。
    """
    helper = NestRemoteHelper(
        channel="ssh",
        nest_ip=test_params["nest_ip"],
        ssh_port=test_params["ssh_port"],
        ssh_user=test_params["ssh_user"],
        ssh_passwd=test_params["ssh_passwd"],
    )
    # 连通性探针: 失败立即 skip, 避免每个用例各自超时
    code, _ = helper.exec_cmd_quiet("uname -a", timeout=10)
    if code != 0:
        pytest.skip(
            f"机巢 SSH 连接失败 ({test_params['nest_ip']}:{test_params['ssh_port']})"
            f" — 检查网络与 sshd; returncode={code}"
        )
    log_manager.logger.info(f"[Nest-SSH] 连接成功: {test_params['nest_ip']}")
    yield helper


@pytest.fixture(scope="session")
def adb_session(nest_config, test_params):
    """
    会话级 ADB 通道 fixture

    缺 adb_serial 或 nest_adb_enabled=False 视为该批次不支持 ADB, skip。
    """
    if not test_params["nest_adb_enabled"]:
        pytest.skip("config.json Nest_Module.nest_adb_enabled=false, ADB 通道跳过")
    adb_serial = nest_config.get("adb_serial")
    if not adb_serial:
        pytest.skip("config.json 未配置 Nest_Module.adb_serial")
    helper = NestRemoteHelper(channel="adb", adb_serial=adb_serial)
    code, _ = helper.exec_cmd_quiet("uname -a", timeout=10)
    if code != 0:
        pytest.skip(f"机巢 ADB 连接失败 (serial={adb_serial})")
    yield helper


@pytest.fixture(scope="session")
def console_session(nest_config, test_params):
    """
    会话级调试串口通道 fixture

    通过 SerialPortController (src/Physical/Serial) 连接调试串口。
    缺 debug_serial_port 视为未接调试串口, skip。
    """
    port = test_params["debug_serial_port"]
    if not port:
        pytest.skip("config.json 未配置 Nest_Module.debug_serial_port")
    try:
        from src.Physical.Serial.SerialPortController import SerialPortController
    except ImportError as e:
        pytest.skip(f"未找到 SerialPortController: {e}")
    baudrate = test_params["debug_serial_baudrate"]
    log_manager.logger.info(f"[Nest-Console] 正在连接调试串口: {port} @ {baudrate}")
    ctrl = SerialPortController()
    if not ctrl.connect(port=port, baudrate=baudrate):
        pytest.skip(f"调试串口连接失败: {port} @ {baudrate}")
    helper = NestRemoteHelper(channel="console", console_session=ctrl)
    yield helper
    try:
        ctrl.disconnect()
    except Exception:
        pass


@pytest.fixture(scope="session")
def sftp_session(nest_config, test_params):
    """
    会话级 sftp fixture

    fail-fast: 账号密码必须在 config.json 里, 不允许静默使用默认值。
    """
    helper = NestSftpHelper(
        host=test_params["nest_ip"],
        user=test_params["sftp_user"],
        passwd=test_params["sftp_passwd"],
        port=test_params["ssh_port"],
    )
    log_manager.logger.info(f"[Nest-SFTP] 会话建立: {test_params['nest_ip']}")
    yield helper
    helper.disconnect()


@pytest.fixture
def backup_baseline_ip(test_params, ssh_session):
    """破坏性用例 (TC-NEST-2-02 setIp) 用: 备份基线 IP, 用例结束后还原。

    Why: setIp + 重启会断 ssh, 不还原会导致后续用例全 fail。
    用 fixture 兜底, 即使断言失败也能在 teardown 还原。
    """
    baseline = test_params["baseline_ip"]
    log_manager.logger.info(f"[Nest-Backup] 记录基线 IP={baseline}")
    yield baseline
    code, current = ssh_session.exec_cmd_quiet(
        f"ifconfig {test_params['eth_iface']} | grep inet"
    )
    if baseline not in (current or ""):
        log_manager.logger.warning(
            f"[Nest-Backup] teardown 检测到 IP 漂移, 当前={current!r}, 尝试还原 {baseline}"
        )
        ssh_session.exec_cmd_quiet(
            f"/etc/setIp.sh {baseline}", timeout=10
        )
        time.sleep(3)
