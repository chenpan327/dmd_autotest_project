# coding: utf-8
"""
通信测试共享 conftest — 供 V3/V4/L3/X1 等机型目录自动继承。

Pytest 会沿目录树向上查找 conftest，因此 Drone_Show/ 下所有子目录
无需重复定义相同的 fixtures 和辅助函数。

配置说明:
- 串口通信：用于传统串口连接的飞控通信
- UDP 通信：用于网络连接的飞控通信
"""

import sys
import os
import time
import pytest
from typing import Optional

from utils.common import get_project_root, load_config
from utils.logger import log_manager

# ============================================================================
# 路径配置
# ============================================================================

project_root = get_project_root()
sys.path.insert(0, project_root)

# ============================================================================
# 导入模块 — pytest.ini pythonpath = . src 已让 src 成为顶层包,直接 import
# ============================================================================

from src.Protocol.airplane.Serial_Protocol_Lite import ProtocolHandler as SerialProtocolHandler
from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation


# ============================================================================
# 配置加载辅助函数
# ============================================================================

def _resolve_device_type(request, config):
    """获取机型：一律以 pytest --device_type 命令行选项为准（main.py 入口会自动携带）

    config.json 顶层 DeviceType 遗留键已移除，不再提供 config 回退 —
    未指定 --device_type 时直接报错，避免静默用错机型的配置。
    """
    opt = request.config.getoption("--device_type", default="")
    if opt:
        return opt
    raise KeyError(
        "未指定机型：请通过 --device_type 显式传入（如 --device_type=X1）；"
        "main.py 入口会自动携带该参数"
    )


def get_airplane_config(config, key, default=None, device_type=None):
    """
    获取当前机型的配置项

    Args:
        config: 配置字典
        key: 配置项名称（如 'serial_port', 'ip' 等）
        default: 默认值
        device_type: 机型名称（必填，用 _resolve_device_type(request, config) 先解析）

    Returns:
        配置项的值
    """
    if device_type is None:
        raise ValueError(
            "get_airplane_config 必须显式传入 device_type "
            "(先经 _resolve_device_type(request, config) 解析机型)"
        )
    if device_type in config:
        return config[device_type].get(key, default)
    return default


# ============================================================================
# 辅助函数 — 缓冲区 / 线程 / 连接管理
# ============================================================================

def clear_handler_buffer(handler, handler_type: str = "serial") -> None:
    """清空协议处理器缓冲区"""
    if handler is None:
        return
    try:
        if hasattr(handler, 'clear_buffer'):
            handler.clear_buffer()
            log_manager.logger.info(f"{handler_type}接收缓冲区已清空 (clear_buffer)")
            return
        if hasattr(handler, 'flush_buffer'):
            handler.flush_buffer()
            log_manager.logger.info(f"{handler_type}接收缓冲区已清空 (flush_buffer)")
            return
        if handler_type == "serial" and hasattr(handler, 'serial') and handler.serial.is_open:
            handler.serial.reset_input_buffer()
            handler.serial.reset_output_buffer()
            log_manager.logger.info(f"{handler_type}缓冲区已通过底层接口清空")
            return
        log_manager.logger.warning(f"未找到合适的{handler_type}缓冲区清理方法")
    except Exception as e:
        log_manager.logger.warning(f"清空{handler_type}缓冲区时发生异常：{str(e)}")


def stop_handler_recv_thread(handler) -> None:
    """停止协议处理器的接收线程"""
    if handler is None or not hasattr(handler, 'recv_thread'):
        return
    recv_thread = handler.recv_thread
    if not recv_thread.is_alive():
        return
    log_manager.logger.info("正在停止接收线程...")
    try:
        if hasattr(handler, 'stop_receive_thread'):
            handler.stop_receive_thread()
        elif hasattr(recv_thread, 'stop'):
            recv_thread.stop()
        elif hasattr(handler, 'running'):
            handler.running = False
        recv_thread.join(timeout=3)
        if recv_thread.is_alive():
            log_manager.logger.warning("接收线程没有正常结束，强制停止")
    except Exception as e:
        log_manager.logger.error(f"停止接收线程时发生异常：{str(e)}")


def disconnect_handler(handler, handler_type: str = "serial") -> None:
    """断开协议处理器连接"""
    if handler is None:
        return
    log_manager.logger.info(f"开始断开{handler_type}连接...")
    try:
        if handler_type == "serial":
            stop_handler_recv_thread(handler)
            time.sleep(0.5)
            clear_handler_buffer(handler, handler_type)
        if hasattr(handler, 'disconnect'):
            handler.disconnect()
        elif hasattr(handler, 'sock') and handler.sock:
            handler.sock.close()
        elif hasattr(handler, 'serial') and handler.serial.is_open:
            handler.serial.close()
        log_manager.logger.info(f"{handler_type}连接已断开")
    except Exception as e:
        log_manager.logger.error(f"断开{handler_type}连接时发生异常：{str(e)}")
        try:
            if hasattr(handler, 'serial') and handler.serial.is_open:
                handler.serial.reset_input_buffer()
                handler.serial.reset_output_buffer()
                handler.serial.close()
                log_manager.logger.info(f"已强制关闭{handler_type}并清空缓冲区")
        except Exception as ee:
            log_manager.logger.error(f"强制关闭{handler_type}失败：{str(ee)}")


# ============================================================================
# Fixture — 串口协议处理器
# ============================================================================

@pytest.fixture(scope="module")
def serial_protocol_handler(request) -> Optional[SerialProtocolHandler]:
    """模块级串口协议处理器 fixture"""
    log_manager.logger.info("开始初始化串口协议处理器...")
    current_config = load_config()
    device_type = _resolve_device_type(request, current_config)
    log_manager.logger.info(f"当前机型 (DeviceType): {device_type}")

    handler = None
    try:
        port = get_airplane_config(current_config, 'serial_port', device_type=device_type)
        baudrate = get_airplane_config(current_config, 'serial_baudrate', 115200, device_type=device_type)
        timeout_config = get_airplane_config(current_config, 'serial_timeout', device_type=device_type)

        if timeout_config:
            timeout = float(timeout_config)
        else:
            timeout = 8.0

        log_manager.logger.info("从配置文件读取串口设置:")
        log_manager.logger.info(f"  串口：{port}")
        log_manager.logger.info(f"  波特率：{baudrate}")

        if not port:
            raise ValueError(f"机型 '{device_type}' 的 serial_port 配置为空，请在 config.json 中配置")

        handler = SerialProtocolHandler(port=port, baudrate=baudrate, timeout=timeout)
        handler.connect()

        if handler:
            log_manager.logger.info("串口连接成功！")
            clear_handler_buffer(handler, "串口")

            # 获取设备版本信息并写入 Allure 环境信息
            try:
                version_info = handler.get_device_version()
                if version_info and version_info.get("version"):
                    allure_results = os.path.join(project_root, "allure-results")
                    os.makedirs(allure_results, exist_ok=True)
                    env_path = os.path.join(allure_results, "environment.properties")
                    with open(env_path, "a", encoding="utf-8") as f:
                        # 只取版本号本身的纯文本（如 n3.g.199），去除可能附加的 ~dmd_uav~@ 等
                        ver = version_info['version'].split()[0] if version_info.get('version') else ""
                        if ver:
                            f.write(f"Firmware={ver}\n")
                        sn = (version_info.get('sn') or "").split()[0]
                        if sn:
                            f.write(f"SN={sn}\n")
                    log_manager.logger.info(f"已将设备版本信息写入 {env_path}")
            except Exception as e:
                log_manager.logger.warning(f"获取/写入设备版本信息失败：{e}")

    except Exception as e:
        log_manager.logger.error(f"初始化串口协议处理器失败：{e}")
        pytest.skip(f"串口初始化失败：{e}")

    yield handler

    # 安全关闭：确保电机停止、DShot 关闭，防止脚本结束后电机继续转动
    if handler:
        for cmd_name, cmd_fn in [
            ("停止电机测试", lambda: handler.motor_test_stop()),
            ("停止老化测试", lambda: handler.aging_test_stop()),
            ("停止 DShot", lambda: handler.set_dshot_stop()),
            ("锁定电机", lambda: handler.disarm_motors()),
        ]:
            try:
                cmd_fn()
                log_manager.logger.info(f"已执行安全关闭: {cmd_name}")
            except Exception:
                pass

    disconnect_handler(handler, "串口")
    log_manager.logger.info("串口协议处理器清理完成")


# ============================================================================
# Fixture — UDP 协议处理器（地面站）
# ============================================================================

@pytest.fixture(scope="module")
def udp_protocol_handler(request) -> Optional[GroundControlStation]:
    """模块级 UDP 协议处理器 fixture"""
    log_manager.logger.info("开始初始化 UDP 协议处理器（地面站）...")
    current_config = load_config()
    device_type = _resolve_device_type(request, current_config)
    log_manager.logger.info(f"当前机型 (DeviceType): {device_type}")

    gcs = None
    try:
        ip = get_airplane_config(current_config, 'ip', device_type=device_type)
        port = get_airplane_config(current_config, 'port', device_type=device_type)
        log_manager.logger.info(f"UDP 配置：ip={ip}, port={port}")

        gcs = GroundControlStation(drone_ip=ip, drone_port=port)

        log_manager.logger.info("地面站实例创建成功")
        if hasattr(gcs, 'sock') and gcs.sock:
            log_manager.logger.info(f"  UDP IP: {gcs.sock.getsockname()[0]}")
        log_manager.logger.info(f"  UDP PORT: {getattr(gcs, 'port', 'N/A')}")

    except Exception as e:
        log_manager.logger.error(f"初始化 UDP 协议处理器失败：{e}")
        pytest.skip(f"UDP 初始化失败：{e}")

    yield gcs
    if gcs:
        try:
            gcs.close()
            log_manager.logger.info("UDP 套接字已关闭")
        except Exception as e:
            log_manager.logger.error(f"断开 UDP 连接时发生异常：{str(e)}")
    log_manager.logger.info("UDP 协议处理器清理完成")


# ============================================================================
# Fixture — 统一协议处理器（串口 + UDP）
# ============================================================================

@pytest.fixture(scope="module")
def protocol_handler(serial_protocol_handler, udp_protocol_handler):
    """统一的协议处理器 fixture，组合串口和 UDP"""
    log_manager.logger.info("协议处理器初始化完成")
    log_manager.logger.info(f"串口连接：{'已连接' if serial_protocol_handler else '未连接/禁用'}")
    log_manager.logger.info(f"UDP 连接：{'已连接' if udp_protocol_handler else '未连接/禁用'}")
    yield {
        'serial': serial_protocol_handler,
        'udp': udp_protocol_handler,
    }
    log_manager.logger.info("协议处理器清理完成")


# ============================================================================
# Fixture — MAVLink 版本号
# ============================================================================

@pytest.fixture(scope="session")
def mavlink_version(request) -> str:
    """读取 MAVLink 版本号：按 --device_type 定位的机型配置节获取"""
    config = load_config()
    device_type = _resolve_device_type(request, config)
    if device_type in config:
        version = config[device_type].get("mavlink_version", "")
        if version:
            log_manager.logger.info(f"MAVLink 版本号（{device_type}）：{version}")
            return str(version)
    version = config.get("mavlink_version", "")
    if version:
        log_manager.logger.info(f"MAVLink 版本号（全局）：{version}")
        return str(version)
    raise KeyError(
        f"config.json 的 {device_type} 节和顶层均未配置 mavlink_version，"
        f"请在 config.json 的 {device_type} 节中添加 \"mavlink_version\" 字段（例如 41）"
    )


# ============================================================================
# Fixture — 无人机 IP 和端口
# ============================================================================

@pytest.fixture(scope="session")
def drone_ip(request) -> str:
    """从 config.json 读取无人机 IP — 缺失即 fail-fast,不藏默认值"""
    config = load_config()
    device_type = _resolve_device_type(request, config)
    ip = get_airplane_config(config, 'ip', device_type=device_type)
    if not ip:
        raise KeyError(
            f"config.json 的 {device_type} 节未配置 ip,请在 config.json 中添加 \"ip\" 字段"
        )
    log_manager.logger.info(f"无人机 IP：{ip}")
    return str(ip)


@pytest.fixture(scope="session")
def drone_port(request) -> int:
    """从 config.json 读取无人机端口 — 缺失即 fail-fast,不藏默认值"""
    config = load_config()
    device_type = _resolve_device_type(request, config)
    port = get_airplane_config(config, 'port', device_type=device_type)
    if not port:
        raise KeyError(
            f"config.json 的 {device_type} 节未配置 port,请在 config.json 中添加 \"port\" 字段"
        )
    log_manager.logger.info(f"无人机端口：{port}")
    return int(port)


# ============================================================================
# Fixture — 测试准备和清理
# ============================================================================

@pytest.fixture(autouse=True)
def test_setup_teardown(request: pytest.FixtureRequest) -> None:
    """自动记录测试开始/结束日志，测试间短暂延迟"""
    log_manager.logger.info(f"\n>>> 测试开始：{request.node.name}")
    log_start_offset = log_manager.get_log_offset()

    yield

    log_manager.logger.info(f">>> 测试结束：{request.node.name}")
    log_manager.attach_log_to_allure(start_offset=log_start_offset)
    time.sleep(0.2)
