# coding: utf-8
"""
hope_stm32h743vit6 (h743 公共开发板) UART 底软测试 Fixture

被测对象: h743 板 MCU 底软的 UART 驱动 (Shell 口下发 dmdtest_uart 命令集)
测试逻辑: src/Protocol/dmdtest_uart 协议层 + 本目录 8 个分组测试文件
         (79 个飞书测试点, 判定语义 rep 任一值为 False 即失败)

Jenkins 入口: DeviceType=BSP_APP + BoardType=hope_stm32h743vit6 + TestSuites=UART
          -> main.py --device_type hope_stm32h743vit6 --test_suites UART
config.json: hope_stm32h743vit6 段 (script_dir 指向本板目录, port1/baud1/port2/uartx 必填)

本文件提供: 收集期板段 fail-fast / Shell 串口生命周期 / uart_args 命名空间 /
result_report_ 等价物(逐点判定明细直接挂 Allure 附件, 不再落独立报告树)。
"""
import json
from pathlib import Path

import allure
import pytest

from src.Physical.Serial.SerialPortController import SerialPortController
from utils import serial_trace
from utils.logger import log_manager
from utils.common import get_project_root

# 板段必填 key (缺任一 = 收集期硬失败, 见 pytest_configure)
REQUIRED_KEYS = ("port1", "baud1", "port2", "uartx")
INT_KEYS = ("baud1", "uartx")
# 可选 key: 默认值 + config 同名 key 覆盖
OPTIONAL_DEFAULTS = {
    "seed": 20260909,     # 随机测试复现种子 (飞书行65-74, 各随机点以 seed+行号 派生)
    "soak_seconds": 60,   # 浸泡时长(s), 行65 内存泄漏检测; 72h 长稳 = 259200
}


def _load_board_section(device_type):
    """按 device_type 读 config.json 设备段; 段不存在返回 None"""
    config_path = Path(get_project_root()) / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get(device_type)


def pytest_configure(config):
    """pytest 钩子 (早于收集期 test 模块 import): 本板板段配置 fail-fast 校验

    配置错误时 79 个用例应以 UsageError 硬失败 (退出码 4),
    而不是全部变形失败污染报告; --device_type 非本板时直接跳过。
    """
    device_type = config.getoption("--device_type", default="")
    if device_type != "hope_stm32h743vit6":
        return
    board = _load_board_section(device_type)
    if not board:
        raise pytest.UsageError(
            f"config.json 缺少板段 [{device_type}] "
            f"(必须与 Jenkins BoardType 下拉值完全一致)")
    missing = [k for k in REQUIRED_KEYS if k not in board]
    if missing:
        raise pytest.UsageError(
            f"config.json[{device_type}] 缺少 UART 测试必填 key: {missing}")
    for key in INT_KEYS:
        if not isinstance(board[key], int) or isinstance(board[key], bool):
            raise pytest.UsageError(
                f"config.json[{device_type}].{key} 必须是整数, 实际: {board[key]!r}")
    config._bsp_app_board = {"device_type": device_type, **board}


@pytest.fixture(scope="session")
def board_cfg(pytestconfig):
    """会话级板段配置 (pytest_configure 已 fail-fast 校验, 这里只取回)"""
    return pytestconfig._bsp_app_board


@pytest.fixture(scope="session", autouse=True)
def print_startup_info(board_cfg):
    """会话开始打环境横幅, 便于日志排查"""
    banner = f"""

============================================================
  h743 (hope_stm32h743vit6) UART 底软测试环境信息
============================================================
  板名(BoardType):  {board_cfg['device_type']}
  测试套件:         UART
------------------------------------------------------------
  Shell 口 (下发 dmdtest_uart 测试命令):  {board_cfg.get('port1', '未配置')} @ {board_cfg.get('baud1', '未配置')}
  数据口 (与被测 UART 收发比对数据):      {board_cfg.get('port2', '未配置')}
  被测 UART:        uart{board_cfg.get('uartx', '?')}
  随机测试种子 (数值固定则随机类用例每次跑出相同序列, 便于复现问题):
    {board_cfg.get('seed', 20260909)}
  浸泡测试时长 ("内存泄漏检测"用例持续随机收发的时长, 秒; config.json 可改):
    {board_cfg.get('soak_seconds', 60)}
============================================================
"""
    log_manager.logger.info(banner)


@pytest.fixture(scope="session")
def uart_args(board_cfg):
    """
    会话级配置命名空间 (协议层测试函数的 args 入参)

    字段与 dmdtest_uart 协议层函数签名约定一致:
    port1/baud1/port2/uartx + seed/soak_seconds。
    """
    from types import SimpleNamespace
    ns = SimpleNamespace(
        port1=str(board_cfg["port1"]),
        baud1=int(board_cfg["baud1"]),
        port2=str(board_cfg["port2"]),
        uartx=int(board_cfg["uartx"]),
    )
    for key, default in OPTIONAL_DEFAULTS.items():
        setattr(ns, key, int(board_cfg.get(key, default)))
    return ns


@pytest.fixture(scope="session")
def shellp(uart_args):
    """
    会话级 MCU Shell 串口 (79 个测试点共用同一实例)

    串行约束: 单一 Shell 串口物理独占; 测试点用例内部自包含 open/close 会话、
    互不依赖但共享串口状态 — 严禁 pytest-xdist / 多进程 / 多线程并行
    (本仓库未安装 xdist, 也不得引入)。
    连接失败 skip 整批; teardown 统一关闭。
    """
    ctrl = SerialPortController(port=uart_args.port1, baudrate=uart_args.baud1,
                                enable_queue=True, trace_enabled=True)
    if not ctrl.connect():
        pytest.skip(
            f"Shell 串口连接失败: {uart_args.port1} @ {uart_args.baud1} "
            f"— 检查 COM 口号/波特率/是否被串口调试终端占用")
    log_manager.logger.info(
        f"[h743-UART] Shell 串口已连接: {uart_args.port1} @ {uart_args.baud1}, "
        f"被测 uart{uart_args.uartx}")
    yield ctrl
    try:
        ctrl.disconnect()
    except Exception:  # noqa: BLE001 — teardown 不掩盖测试结果
        log_manager.logger.warning("[h743-UART] Shell 串口关闭异常 (已忽略)")


@pytest.fixture(autouse=True)
def uart_trace_attach(request, shellp):
    """逐用例串口收发流水切片, 挂 Allure 附件 (Shell 口/数据口全量 TX/RX)

    流水为接收线程物理层簿记, 含被 clear_buffer 丢弃的残留与 Break 线路事件;
    控制台 INFO 只呈现消费到的数据, 被丢弃/污染的残留以本附件为准。
    附件名形如 "test_xxx_串口收发流水", 在 Allure 用例页 Teardown 阶段可见。
    """
    start = serial_trace.snapshot()
    yield
    entries = serial_trace.entries_since(start)
    if entries:
        allure.attach(
            "\n".join(entries),
            name=f"{request.node.name}_串口收发流水",
            attachment_type=allure.attachment_type.TEXT,
        )
