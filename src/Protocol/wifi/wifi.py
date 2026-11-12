# coding: utf-8
"""
WiFi 模块协议层(单一文件整合)

分层定位:
    物理层:Serial_Protocol_Lite.py(串口)、fake_ground_control_station.py(UDP)
    协议层:本文件 — WiFi 专有命令封装、MAVLink 消息构造、iperf 客户端、升级流程
    脚本层:src/Script/Drone_Show/Wifi_Module/Release_Testing/ 下的 pytest 用例

内容分节:
    1. 常量             - MAVLink 命令 ID、msg_id、ACK 枚举、超时、固件路径、阈值
    2. 数据类           - 各流程的结果类型(IperfResult / UpgradeResult / Sample / Report)
    3. MAVLink 命令封装 - GCS 下行命令发送 + COMMAND_ACK 等待
    4. iperf 客户端     - TCP/UDP 吞吐测试
    5. 固件升级         - GPS / companion / 电池升级完整流程
    6. 自动重连监控     - _check 任务行为采样与稳定性监控

源码依据:
    - mt793x onion_companion.c / onion_upgrade.h / onion_upgrade.c
    - mt793x dmd_cicd.c / dmd_factory.c(CLI 命令)
    - middleware/MTK/iperf(iperf 协议)
    - dmd_uav_32.py(MAVLink msg_id)

修改本文件前请先核对固件源码,保持与设备行为一致。
"""
import os
import re
import time
import zlib
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

from utils.logger import log_manager
from src.Protocol.mavlink.parse_mavlink import MAVLink_message


# ==========================================================================
# 1. 常量
# ==========================================================================

# ---------- MAVLink 命令 ID(DMD 自定义,40045+)----------
# 源码:onion_companion.c:220-261
MAV_CMD_UPDATE_COMPANION = 40045
#   param1: 0=companion(整包)、1=battery、2=GPS、3=receiver、4=lppc
MAV_CMD_STANDBY = 40046
#   param1: 0=UAV 上电、1=UAV 下电、其他=仅记日志不动电源
MAV_CMD_STANDBY_READY = 40047
#   飞控 standby ready 指示(本模块仅透传到 UAV)
MAV_CMD_SWITCH_DHCP = 40049
#   源码:onion_companion.c:262-263,WiFi 模块当前 continue 直接丢弃
MAV_CMD_DELETE_MAC = 40050
#   源码:onion_companion.c:264-265,WiFi 模块当前 continue 直接丢弃
MAV_CMD_HOLD_PWR = 40054
#   控制 UAV 锁定电源(onion_upgrade.c:206 升级流程中向 UAV 下发)

# ---------- MAVLink 命令 ID(通用,与 wifi mac 查询相关)----------
# 源码:onion_companion.c:128-157
MAV_CMD_WIFI_MAC_ADDR = 1005
#   param1=0:WiFi 回 STA MAC(填入 param2-7 回 UAV)
#   param1=1:WiFi 回 STA IP(填入 param2-5 回 UAV)

# ---------- MAVLink msg_id ----------
# 源码:dmd_uav_32.py + onion_companion.c
MSG_ID_HEARTBEAT = 0                # 标准 HEARTBEAT
MSG_ID_HEARTBEAT_DMD = 1            # DMD 自定义心跳
MSG_ID_IDENTIFY_INFO = 2            # 身份信息
MSG_ID_GET_IDENTIFY_INFO = 3        # 身份请求
MSG_ID_PACKED_STATE = 5             # 打包状态
MSG_ID_EXTEND_STATE = 8             # 扩展状态
MSG_ID_EULER_NETWORK = 49           # 远程改 IP/SSID(8 字节 SSID)
MSG_ID_COMMAND_LONG = 76            # GCS→UAV 命令
MSG_ID_COMMAND_ACK = 77             # UAV→GCS 命令应答

# COMMAND_ACK.result 枚举(标准 MAVLink)
ACK_RESULT_ACCEPTED = 0
ACK_RESULT_TEMPORARILY_REJECTED = 1
ACK_RESULT_DENIED = 2
ACK_RESULT_UNSUPPORTED = 3
ACK_RESULT_FAILED = 4

# ---------- EULER_NETWORK 字段约束 ----------
# 源码:dmd_uav_32.py:1895 array_lengths=[8]
EULER_NETWORK_SSID_LEN = 8  # SSID 字段固定 8 字节,不足补 \x00

# ---------- 默认 ACK 超时(秒)----------
DEFAULT_ACK_TIMEOUT = 10.0

# ---------- WiFi 串口默认参数 ----------
# config.json 的 Wifi_Module.serial_baudrate 必须为 921600(与固件 CLI 一致)
# 此常量用于脚本层 reboot 后重连、conftest fallback 等场景,避免硬编码
WIFI_DEFAULT_BAUDRATE = 921600
# reboot 后设备重启 + 串口就绪的典型等待(秒)
WIFI_REBOOT_READY_SECONDS = 2
# change_ssid 后固件热加载(set_ssid_chg_flag)所需等待(秒)
WIFI_SSID_HOTSWAP_SECONDS = 8

# ---------- 固件升级相关(源码 onion_upgrade.h)----------
GPS_BLOCK_DATA_LEN = 250            # GPS 升级单块大小
UAV_BLOCK_RETRY_TM = 3              # 飞控 blink 升级重试次数

# 固件 FTP 路径(源码 onion_upgrade.h:10-18)
FTP_ROOT_DIR = "/root"
FTP_CMPN_DIR = "/cmpn"
FTP_GPS_FIRMWARE = "/root/gps.bin"
FTP_BATTERY_FIRMWARE = "/root/battery.bin"
FTP_UPDATE_ZIP = "/root/update.zip"
FTP_CMPN_FIRMWARE = "/cmpn/dmd_companion/fota_793x.bin"

# GPS 升级单块耗时估算(秒)
# 源码:onion_upgrade.c:118-190,实测受 GPS 芯片 Flash 写入抖动影响,按 0.2s/块保留余量
GPS_PER_BLOCK_SECONDS = 0.2

# FCS 功率重置时间(秒)
# 源码:onion_upgrade.c:179-182:F9P=5s+2s,UM=30s+2s
FCS_RESET_DELAY_F9P = 5
FCS_RESET_DELAY_UM = 30
FCS_POWER_OFF_DELAY = 2
FCS_RESET_EXTRA_MARGIN = 3  # 重启余量

# companion 整包升级总耗时(秒)
# 源码:onion_upgrade.c:410-471:vTaskDelay(5s)+ 解压 + fcs_upgrade + vTaskDelay(10s) + mt793x_upgrade reboot
COMPANION_UPGRADE_WAIT = 120

# ---------- WiFi 自动重连阈值(源码 onion_companion.c:28-30)----------
# rewifi_cnt 每秒 +1,到达顺序为 15 → 30,所以两档都会触发:
#   - 15s:_check 进入 else-if 分支,set_wifi_ssid(当前 ssid) 重新初始化 wifi
#   - 30s:_check 进入 if 分支,切换到另一档 SSID 并清零 rewifi_cnt
REWIFI_TMOUT_MAX = 15               # 15s 未连:重新初始化 wifi(else-if 分支)
SWITCH_SSID_TMOUT_MAX = 30          # 30s 未连:切换备用 SSID(if 分支,清零 rewifi_cnt)
CHG_UNLINK_TMOUT_MAX = 90           # 切 SSID 后 90s 未连 reboot(仅硬版本 0)

# 自动切换日志关键字(源码 onion_companion.c:378)
SWITCH_SSID_LOG_KEYWORD = "switch another ssid"

# ---------- iperf 协议(middleware/MTK/iperf)----------
IPERF_DEFAULT_PORT = 5001
IPERF_SERVER_RECEIVE_TIMEOUT = 20   # 固件服务端无数据 20s 自动退出

# iperf 性能阈值(Mbits/sec)
TCP_BANDWIDTH_MIN_MBPS = 10
UDP_BANDWIDTH_MIN_MBPS = 5
UDP_LOSS_MAX_PERCENT = 30


# ==========================================================================
# 2. 数据类
# ==========================================================================

@dataclass
class IperfResult:
    """iperf 测试结果"""
    success: bool = False
    bandwidth_mbps: Optional[float] = None
    jitter_ms: Optional[float] = None       # UDP only
    loss_percent: Optional[int] = None      # UDP only
    raw_output: str = ""                    # 原始输出(截断后)
    error: Optional[str] = None


@dataclass
class UpgradeResult:
    """升级流程结果"""
    success: bool = False
    ack_result: Optional[int] = None      # COMMAND_ACK result(0=ACCEPTED)
    firmware_len: int = 0
    firmware_crc32: int = 0
    total_blocks: int = 0
    wait_seconds: int = 0
    error: Optional[str] = None


@dataclass
class ConnectionSample:
    """单次连接状态采样"""
    elapsed: int                    # 距开始秒数
    is_linked: Optional[bool]       # 是否已连接
    rssi: Optional[int]             # RSSI(dBm)
    ssid: Optional[str]             # 当前 SSID
    connect_status: Optional[str]   # 连接状态字符串


@dataclass
class StabilityReport:
    """连接稳定性报告"""
    samples: List[ConnectionSample] = field(default_factory=list)
    total_samples: int = 0
    linked_samples: int = 0
    linked_ratio: float = 0.0       # 连接率 0-1
    ssid_changed: bool = False      # 是否发生过 SSID 变化
    ssid_seen: List[str] = field(default_factory=list)

    @property
    def is_stable(self) -> bool:
        """连接率 >= 90% 视为稳定"""
        return self.linked_ratio >= 0.9


@dataclass
class AutoSwitchReport:
    """SSID 自动切换监控报告"""
    detected: bool = False          # 是否检测到 SSID 自动切换
    original_ssid: Optional[str] = None
    switched_to: Optional[str] = None
    switch_time_seconds: Optional[int] = None  # 切换发生时刻


# ==========================================================================
# 3. MAVLink 命令封装(GCS 下行)
#
# 源码依据(onion_companion.c):
#   - MAV_CMD_STANDBY (40046):UAV 上下电
#   - EULER_NETWORK (msg_id=49):远程改 IP/SSID
#   - MAV_CMD_UPDATE_COMPANION (40045):触发固件升级
# ==========================================================================

def resolve_module_ip(serial_session, fallback_ip: str) -> str:
    """解析 WiFi 模块当前实际 IP,失败回退到 config 的 mavlink_target_ip。

    用于 GCS fixture 等"class/session 级"场景 — conftest.module_current_ip 是
    函数级 fixture,无法被 class 级 fixture 直接依赖。这里直接调串口查询。

    为什么需要:#459 GCS 测试 7 个失败根因 — WiFi 模块当前 IP 是 .101,
    但 config mavlink_target_ip 是 .200,GCS 死磕 .200 导致命令永远到不了。
    """
    try:
        current = serial_session.get_ip_address()
        if current:
            if current != fallback_ip:
                log_manager.logger.info(
                    f"[WiFi-IP] 模块当前 IP={current} 与 config fallback={fallback_ip} "
                    f"不同,使用当前 IP"
                )
            return current
    except Exception as e:
        log_manager.logger.warning(
            f"[WiFi-IP] 获取当前 IP 失败,使用 config fallback={fallback_ip}: {e}"
        )
    return fallback_ip


def ip_to_uint32(ip_str: str) -> int:
    """将 IPv4 字符串转为 uint32(大端/网络字节序)

    用途:EULER_NETWORK.id 字段编码
    固件 onion_companion.c:287 用 sprintf("%d.%d.%d.%d") 拆回 IP,
    字节顺序与 MAVLink 序列化一致,大端(第一段为最高字节)。
    """
    parts = ip_str.split(".")
    if len(parts) != 4:
        raise ValueError(f"无效 IPv4: {ip_str}")
    return (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3])


def ssid_to_bytes(ssid_str: str, length: int = EULER_NETWORK_SSID_LEN) -> bytes:
    """将 SSID 字符串转为定长 bytes(不足补 \\x00,超长截断)

    用途:EULER_NETWORK.ssid 字段编码(固定 8 字节)
    """
    encoded = ssid_str.encode("utf-8")[:length]
    return encoded.ljust(length, b"\x00")


def wait_for_command_ack(gcs, expected_cmd: int,
                         timeout: float = DEFAULT_ACK_TIMEOUT) -> Tuple[Optional[int], Optional[object]]:
    """等待 COMMAND_ACK 中匹配 expected_cmd 的响应

    Args:
        gcs: GroundControlStation 实例(必须有 receive 方法)
        expected_cmd: 期望的 command 字段值(如 MAV_CMD_STANDBY)
        timeout: 超时秒数

    Returns:
        (result_value, msg):result 是 ACK 中的 result 字段(0=ACCEPTED);
        超时返回 (None, None)
    """
    start = time.time()
    while time.time() - start < timeout:
        msg, _ = gcs.receive()
        if msg is not None and msg.msg_id == MSG_ID_COMMAND_ACK:
            cmd = msg.fields.get("command", 0)
            result = msg.fields.get("result", -1)
            log_manager.logger.info(
                f"[WiFi-Mavlink] COMMAND_ACK: command={cmd}, result={result}"
            )
            if cmd == expected_cmd:
                return result, msg
        time.sleep(0.1)
    return None, None


def _build_command_long(command_id: int, param1: float, mavlink_version) -> MAVLink_message:
    """构造 COMMAND_LONG 消息(其他 param 默认 0)"""
    return MAVLink_message(
        msg_id=MSG_ID_COMMAND_LONG, sys_id=1, comp_id=1, seq=0,
        version=mavlink_version,
        fields={
            'command': command_id,
            'param1': param1,
            'param2': 0, 'param3': 0, 'param4': 0,
            'param5': 0, 'param6': 0, 'param7': 0,
            'target_system': 0, 'target_component': 0, 'confirmation': 0,
        }
    )


def send_standby(gcs, mavlink_version, power_on: bool,
                 timeout: float = DEFAULT_ACK_TIMEOUT) -> Optional[int]:
    """发送 MAV_CMD_STANDBY 控制 UAV 电源

    Args:
        gcs: GroundControlStation 实例
        mavlink_version: MAVLink 版本
        power_on: True=上电(param1=0),False=下电(param1=1)
        timeout: ACK 超时

    Returns:
        ACK result 值(0=ACCEPTED),超时返回 None

    源码:onion_companion.c:246-261
        param1=0 → fcs_pwr_control(true)  开电源(GPIO16 高)
        param1=1 → fcs_pwr_control(false) 关电源(GPIO16 低)
        其他值 → 仅记日志,不动电源
        ACK 无条件 ACCEPTED(先 ACK 后执行)
    """
    param1 = 0 if power_on else 1
    action = "上电" if power_on else "下电"
    log_manager.logger.info(f"[WiFi-Mavlink] 发送 STANDBY {action}(param1={param1})")

    gcs.send(_build_command_long(MAV_CMD_STANDBY, param1, mavlink_version))
    result, _ = wait_for_command_ack(gcs, MAV_CMD_STANDBY, timeout)
    return result


def send_euler_network(gcs, mavlink_version,
                       ip: Optional[str] = None,
                       ssid: Optional[str] = None,
                       timeout: float = DEFAULT_ACK_TIMEOUT) -> Optional[int]:
    """发送 EULER_NETWORK 远程修改 WiFi 的 IP/SSID

    Args:
        gcs: GroundControlStation 实例
        mavlink_version: MAVLink 版本
        ip: 新 IP 字符串;None 或空字符串表示不改(固件判断 id != 0)
        ssid: 新 SSID;None 或空表示不改;超过 8 字节会截断
        timeout: ACK 超时

    Returns:
        ACK result 值(0=ACCEPTED),超时返回 None

    源码:onion_companion.c:267-302(GCS→UAV 方向)
        先回 ACK(无条件 ACCEPTED) → vTaskDelay(1s) → 解码改 IP/SSID
        改 IP 条件:id != 0 且 != 当前 IP
        改 SSID 条件:非空、不等于 DMD_DFT_SSID、不等于旧值
        不 reboot,通过 set_ssid_chg_flag 触发热加载
    """
    id_uint32 = ip_to_uint32(ip) if ip else 0
    ssid_bytes = ssid_to_bytes(ssid) if ssid else b"\x00" * EULER_NETWORK_SSID_LEN

    log_manager.logger.info(
        f"[WiFi-Mavlink] 发送 EULER_NETWORK: ip={ip or '(不改)'}, ssid={ssid or '(不改)'}"
    )

    msg = MAVLink_message(
        msg_id=MSG_ID_EULER_NETWORK, sys_id=1, comp_id=1, seq=0,
        version=mavlink_version,
        fields={'id': id_uint32, 'ssid': ssid_bytes}
    )
    gcs.send(msg)
    result, _ = wait_for_command_ack(gcs, MSG_ID_EULER_NETWORK, timeout)
    return result


def send_update_companion(gcs, mavlink_version, target: int,
                          timeout: float = DEFAULT_ACK_TIMEOUT) -> Optional[int]:
    """发送 MAV_CMD_UPDATE_COMPANION 触发固件升级

    Args:
        gcs: GroundControlStation 实例
        mavlink_version: MAVLink 版本
        target: 升级目标(0=companion 整包、1=battery、2=GPS、3=receiver、4=lppc)
        timeout: ACK 超时

    Returns:
        ACK result 值(0=ACCEPTED);
        注意:固件在对应固件文件不存在时会改 param1=255 通知 UAV 拒绝,
        此时 ACK 的 result 仍可能为 0(透传后由 UAV 决定)。

    源码:onion_companion.c:220-245
        param1=0 → companion 整包(需 /root/update.zip)
        param1=1 → battery(需 /root/battery.bin)
        param1=2 → GPS(需 /root/gps.bin,自动区分 UM/F9P)
        文件不存在:param1 改为 255 后透传给 UAV
    """
    log_manager.logger.info(
        f"[WiFi-Mavlink] 发送 UPDATE_COMPANION target={target}"
    )
    gcs.send(_build_command_long(MAV_CMD_UPDATE_COMPANION, target, mavlink_version))
    result, _ = wait_for_command_ack(gcs, MAV_CMD_UPDATE_COMPANION, timeout)
    return result


def send_command_long(gcs, mavlink_version, command_id: int, param1: float = 0,
                      timeout: float = DEFAULT_ACK_TIMEOUT) -> Optional[int]:
    """通用 COMMAND_LONG 发送 + COMMAND_ACK 等待

    用于没有专门封装的命令(如 MAV_CMD_HOLD_PWR、SWITCH_DHCP、DELETE_MAC)。
    ACK 的 command 字段等于 command_id 即视为匹配(部分命令 WiFi 模块只透传不回 ACK,
    此时本函数返回 None,脚本层据此判 SKIP 或验证透传链路)。

    Args:
        gcs: GroundControlStation 实例
        mavlink_version: MAVLink 版本
        command_id: MAV_CMD_* 常量
        param1: 命令参数(其他 param 默认 0)
        timeout: ACK 超时

    Returns:
        ACK result 值(0=ACCEPTED);超时返回 None
    """
    log_manager.logger.info(
        f"[WiFi-Mavlink] 发送 COMMAND_LONG command={command_id} param1={param1}"
    )
    gcs.send(_build_command_long(command_id, param1, mavlink_version))
    result, _ = wait_for_command_ack(gcs, command_id, timeout)
    return result


def query_wifi_mac_addr(gcs, mavlink_version, want_ip: bool = False,
                        timeout: float = DEFAULT_ACK_TIMEOUT):
    """通过 MAV_CMD_WIFI_MAC_ADDR 查询 WiFi 模块 MAC 或 IP

    WiFi 模块收到 param1=0 把 STA MAC 填入 param2-7 后透传回 UAV;
    收到 param1=1 把 STA IP 填入 param2-5 后透传回 UAV。
    ACK 经 companion → uav → companion → gcs 路径不一定回 GCS,因此本函数
    返回 (ack_result, ack_msg),脚本层据此判断。

    源码:onion_companion.c:128-157

    Args:
        gcs: GroundControlStation 实例
        mavlink_version: MAVLink 版本
        want_ip: True 查 IP(param1=1),False 查 MAC(param1=0)
        timeout: ACK 超时

    Returns:
        (ack_result, ack_msg):ack_result 为 COMMAND_ACK result 字段,
        ack_msg 为 MAVLink_message;超时返回 (None, None)
    """
    param1 = 1 if want_ip else 0
    log_manager.logger.info(
        f"[WiFi-Mavlink] 查询 WIFI_MAC_ADDR want_ip={want_ip}(param1={param1})"
    )
    gcs.send(_build_command_long(MAV_CMD_WIFI_MAC_ADDR, param1, mavlink_version))
    return wait_for_command_ack(gcs, MAV_CMD_WIFI_MAC_ADDR, timeout)


# ==========================================================================
# 4. iperf 客户端封装
#
# 职责:
#     - 查找 iperf2 可执行文件(项目内置 / 系统 PATH)
#     - 调用 iperf2 客户端打流(TCP/UDP)
#     - 解析输出(带宽、抖动、丢包)
#
# 依赖:项目内置 tools/iperf2.0.14/iperf-2.0.14a-win.exe(随仓库分发)或系统 PATH
#
# 为什么是 iperf2 不是 iperf3:
#     MT793x middleware 的固件服务端用 NLANR 老版本 iperf2 血统(注册命令 `iperf`),
#     与 ESnet iperf3 不互通(协议头/状态机完全不同)。客户端必须也用 iperf2 才能
#     正常握手测速。#460
# ==========================================================================

def probe_tcp_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """探测 TCP 端口是否可连(iperf 服务端启动验证用)

    Args:
        host: 目标主机
        port: 目标端口
        timeout: connect 超时(秒)

    Returns:
        True 表示端口可连(服务端已就绪)
    """
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def find_iperf_binary() -> Optional[str]:
    """查找 iperf2 可执行文件(必须用 iperf2,与固件服务端协议匹配)

    优先级:
        1. 项目内置 tools/iperf2.0.14/iperf-2.0.14a-win.exe(随仓库分发,版本固定)
        2. 系统 PATH 中的 iperf2 / iperf(iperf3 与固件 iperf2 服务端不兼容,会跳过)

    Returns:
        可执行文件绝对路径;未找到返回 None
    """
    # 1. 项目内置(本文件位于 src/Protocol/wifi/,项目根向上 3 层)
    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    builtin_rel = "tools/iperf2.0.14/iperf-2.0.14a-win.exe"
    builtin_abs = os.path.join(project_root, "tools", "iperf2.0.14", "iperf-2.0.14a-win.exe")
    if os.path.exists(builtin_abs):
        log_manager.logger.info(f"[iperf] 使用项目内置: {builtin_rel}")
        return builtin_abs

    # 2. 系统 PATH(iperf3 与固件 iperf2 服务端协议不兼容,故不在候选中)
    for cmd in ("iperf2", "iperf"):
        path = shutil.which(cmd)
        if path:
            log_manager.logger.info(f"[iperf] 使用系统 PATH: {path}")
            return path

    return None


def _run_iperf_client(binary: str, args: List[str], timeout: int) -> str:
    """执行 iperf 客户端命令,返回 stdout+stderr 合并输出"""
    cmd = [binary] + args
    log_manager.logger.info(f"[iperf] 执行: {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        # 超时时拼接已采集的输出
        out = ""
        if isinstance(e.stdout, bytes):
            out += e.stdout.decode("utf-8", errors="replace")
        elif isinstance(e.stdout, str):
            out += e.stdout
        if isinstance(e.stderr, bytes):
            out += e.stderr.decode("utf-8", errors="replace")
        elif isinstance(e.stderr, str):
            out += e.stderr
        # 打印 partial output,帮助定位是「服务端无响应」还是「连接被拒」
        # (#459 之前超时只说"部分输出已采集",看不到 iperf2 的真实错误)
        preview = out.strip().splitlines()[:8]
        preview_str = "\n".join(f"  | {line}" for line in preview)
        log_manager.logger.warning(
            f"[iperf] 客户端超时(无完整结果)。已采集输出前 8 行:\n{preview_str}"
        )
        return out
    except Exception as e:
        log_manager.logger.error(f"[iperf] 客户端执行失败: {e}")
        raise


def run_tcp_uplink(binary: str, server_ip: str, duration: int = 10,
                   port: int = IPERF_DEFAULT_PORT) -> IperfResult:
    """以 TCP 客户端模式打流到 server_ip

    Args:
        binary: iperf2 可执行文件路径
        server_ip: WiFi 模块 IP(需先在模块上启动 iperf -s)
        duration: 测试时长(秒)
        port: 服务端口(默认 5001)

    Returns:
        IperfResult,bandwidth_mbps 字段为 TCP 带宽
    """
    args = ["-c", server_ip, "-p", str(port), "-t", str(duration), "-i", "1"]
    output = _run_iperf_client(binary, args, timeout=duration + 10)

    bandwidth = _parse_tcp_bandwidth(output)
    result = IperfResult(
        success=bandwidth is not None,
        bandwidth_mbps=bandwidth,
        raw_output=output[-2000:],
        error=None if bandwidth else "未能解析 TCP 带宽",
    )
    return result


def run_udp_uplink(binary: str, server_ip: str, duration: int = 10,
                   bandwidth_target: str = "20M",
                   port: int = IPERF_DEFAULT_PORT) -> IperfResult:
    """以 UDP 客户端模式打流到 server_ip

    Args:
        binary: iperf2 可执行文件路径
        server_ip: WiFi 模块 IP
        duration: 测试时长(秒)
        bandwidth_target: UDP 目标带宽(如 "20M"、"50M")
        port: 服务端口

    Returns:
        IperfResult,包含 bandwidth_mbps / jitter_ms / loss_percent
    """
    args = [
        "-c", server_ip, "-u", "-b", bandwidth_target,
        "-p", str(port), "-t", str(duration), "-i", "1",
    ]
    output = _run_iperf_client(binary, args, timeout=duration + 10)

    bw, jitter, loss = _parse_udp_summary(output)
    result = IperfResult(
        success=bw is not None,
        bandwidth_mbps=bw,
        jitter_ms=jitter,
        loss_percent=loss,
        raw_output=output[-2000:],
        error=None if bw else "未能解析 UDP 带宽",
    )
    return result


# iperf2 输出正则
_TCP_BANDWIDTH_RE = re.compile(r"([\d.]+)\s*(Mbits|Gbits|Kbits|bits)/sec", re.IGNORECASE)
_UDP_SUMMARY_RE = re.compile(
    r"([\d.]+)\s*ms\s+([\d]+)/([\d]+)\s*\(([\d.]+)%\)"
)


def _to_mbps(value: float, unit: str) -> float:
    """把带宽数值按单位统一为 Mbps"""
    unit_lower = unit.lower()
    if "gbits" in unit_lower:
        return value * 1000
    if "mbits" in unit_lower:
        return value
    if "kbits" in unit_lower:
        return value / 1000
    return value / 1_000_000  # bits/sec


def _parse_tcp_bandwidth(output: str) -> Optional[float]:
    """解析 TCP 带宽(取最后一行匹配,即总结行)"""
    matches = _TCP_BANDWIDTH_RE.findall(output)
    if not matches:
        return None
    value_str, unit = matches[-1]
    return _to_mbps(float(value_str), unit)


def _parse_udp_summary(output: str):
    """解析 UDP 总结行:带宽、抖动、丢包率

    iperf2 UDP 服务端总结行格式(示例):
        [  5]   0.00-10.00  sec  23.8 MBytes  20.0 Mbits/sec  0.046 ms  12/17007 (0.071%)

    注:iperf2 客户端会回显 "Server Report" 段,包含 jitter / loss,与 iperf3 的
    客户端只有本地段不同。本正则取最后一行匹配,正好命中 Server Report。
    """
    bandwidth_mbps = None
    jitter_ms = None
    loss_percent = None

    # 找最后一行带丢包率的总结(包含 ms + N/M (X%))
    matches = list(_UDP_SUMMARY_RE.finditer(output))
    if matches:
        m = matches[-1]
        jitter_ms = float(m.group(1))
        loss_percent = int(float(m.group(4)))

    # 带宽:同行的 Mbits/sec
    bw_matches = _TCP_BANDWIDTH_RE.findall(output)
    if bw_matches:
        value_str, unit = bw_matches[-1]
        bandwidth_mbps = _to_mbps(float(value_str), unit)

    return bandwidth_mbps, jitter_ms, loss_percent


# ==========================================================================
# 5. 固件升级流程封装
#
# 封装三种固件升级的完整流程,屏蔽 FTP 上传 + MAVLink 触发 + 等待 的细节:
#     upgrade_gps()           - GPS 升级(MAV_CMD_UPDATE_COMPANION param1=2,WiFi 内部完成)
#     upgrade_companion()     - companion 整包升级(param1=0,含飞控 blink 协议)
#     trigger_battery_upgrade() - 电池升级触发(param1=1,固件 stub,仅验证链路)
#
# 源码依据:
#     - onion_companion.c:220-245(触发逻辑)
#     - onion_upgrade.c:118-190(GPS 刷写)、:311-395(飞控 blink)、:410-471(upgrade_task)
#     - onion_upgrade.h:10-18(文件路径)
# ==========================================================================

def _read_firmware_info(firmware_path: str):
    """读取固件文件大小和 CRC32"""
    if not os.path.exists(firmware_path):
        return None, None
    firmware_len = os.path.getsize(firmware_path)
    crc = 0
    with open(firmware_path, "rb") as f:
        while True:
            chunk = f.read(4096)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc) & 0xFFFFFFFF
    return firmware_len, crc


def _calc_total_blocks(firmware_len: int, block_size: int = GPS_BLOCK_DATA_LEN) -> int:
    """计算分块数"""
    return (firmware_len + block_size - 1) // block_size


def _upload_firmware(ftp_session, firmware_path: str, remote_path: str) -> bool:
    """通过 FTP 上传固件"""
    try:
        if not ftp_session.connect():
            log_manager.logger.error(f"[Upgrade] FTP 连接失败")
            return False
        if not ftp_session.upload_file(firmware_path, remote_path):
            log_manager.logger.error(f"[Upgrade] FTP 上传失败: {firmware_path} -> {remote_path}")
            return False
        log_manager.logger.info(f"[Upgrade] FTP 上传成功: {remote_path}")
        return True
    except Exception as e:
        log_manager.logger.error(f"[Upgrade] FTP 异常: {e}")
        return False


def upgrade_gps(gcs, ftp_session, mavlink_version, firmware_path: str,
                remote_path: str = FTP_GPS_FIRMWARE,
                ack_timeout: float = DEFAULT_ACK_TIMEOUT) -> UpgradeResult:
    """执行 GPS 固件升级(通过 WiFi 模块内部升级流程)

    流程:
        1. FTP 上传 gps.bin 到 /root/gps.bin
        2. 发送 MAV_CMD_UPDATE_COMPANION param1=2
        3. 等待 COMMAND_ACK
        4. 等待 WiFi 模块内部 UART 刷写完成(估算耗时)

    源码:onion_upgrade.c:118-190
        单块大小 250B,起始 ACK 20s,数据 ACK 5s,重试 3 次
        F9P 复位 5s+2s,UM 复位 30s+2s
    """
    result = UpgradeResult()

    firmware_len, crc = _read_firmware_info(firmware_path)
    if firmware_len is None:
        result.error = f"固件文件不存在: {firmware_path}"
        log_manager.logger.error(f"[GPS-Upgrade] {result.error}")
        return result

    result.firmware_len = firmware_len
    result.firmware_crc32 = crc
    result.total_blocks = _calc_total_blocks(firmware_len)
    log_manager.logger.info(
        f"[GPS-Upgrade] 固件: len={firmware_len}, crc32=0x{crc:08X}, "
        f"blocks={result.total_blocks}"
    )

    # 步骤 1: FTP 上传
    if not _upload_firmware(ftp_session, firmware_path, remote_path):
        result.error = "FTP 上传失败"
        return result

    # 步骤 2: 发送触发命令
    log_manager.logger.info("[GPS-Upgrade] 发送 MAV_CMD_UPDATE_COMPANION param1=2")
    ack_result = send_update_companion(gcs, mavlink_version, target=2, timeout=ack_timeout)
    result.ack_result = ack_result

    if ack_result is None:
        result.error = f"{ack_timeout}s 内未收到 COMMAND_ACK"
        return result
    if ack_result != ACK_RESULT_ACCEPTED:
        result.error = f"升级启动被拒绝: result={ack_result}"
        return result

    # 步骤 3: 等待内部刷写完成
    # 单块耗时:UART(921600bps) + ACK 5s(数据)/20s(起始),按 0.2s/块估算 + FCS 复位余量
    wait_seconds = max(
        int(ack_timeout),
        int(result.total_blocks * GPS_PER_BLOCK_SECONDS)
        + FCS_RESET_DELAY_UM + FCS_POWER_OFF_DELAY + FCS_RESET_EXTRA_MARGIN + 30
    )
    result.wait_seconds = wait_seconds
    log_manager.logger.info(
        f"[GPS-Upgrade] 等待内部升级 {wait_seconds}s({result.total_blocks} 块 + FCS 复位)"
    )
    time.sleep(wait_seconds)

    result.success = True
    log_manager.logger.info("[GPS-Upgrade] GPS 升级流程完成")
    return result


def upgrade_companion(gcs, ftp_session, mavlink_version, firmware_path: str,
                      remote_path: str = FTP_UPDATE_ZIP,
                      ack_timeout: float = DEFAULT_ACK_TIMEOUT) -> UpgradeResult:
    """执行 companion 整包升级(含飞控 blink 协议 + WiFi reboot)

    流程:
        1. FTP 上传 update.zip 到 /root/update.zip
        2. 发送 MAV_CMD_UPDATE_COMPANION param1=0
        3. 等待 COMMAND_ACK
        4. 等待 WiFi 内部完成:解压 → fcs_upgrade → mt793x_upgrade(reboot)

    源码:onion_upgrade.c:410-471(upgrade_task)
        vTaskDelay(5s) → uncompress_update_zip → fcs_upgrade → vTaskDelay(10s)
        → mt793x_upgrade 写 FOTA + hal_sys_reboot
    """
    result = UpgradeResult()

    firmware_len, crc = _read_firmware_info(firmware_path)
    if firmware_len is None:
        result.error = f"升级包不存在: {firmware_path}"
        return result

    result.firmware_len = firmware_len
    result.firmware_crc32 = crc
    log_manager.logger.info(
        f"[Companion-Upgrade] 升级包: len={firmware_len}, crc32=0x{crc:08X}"
    )

    # 步骤 1: FTP 上传
    if not _upload_firmware(ftp_session, firmware_path, remote_path):
        result.error = "FTP 上传失败"
        return result

    # 步骤 2: 发送触发命令
    log_manager.logger.info("[Companion-Upgrade] 发送 MAV_CMD_UPDATE_COMPANION param1=0")
    ack_result = send_update_companion(gcs, mavlink_version, target=0, timeout=ack_timeout)
    result.ack_result = ack_result

    if ack_result is None:
        result.error = f"{ack_timeout}s 内未收到 COMMAND_ACK"
        return result
    if ack_result != ACK_RESULT_ACCEPTED:
        result.error = f"升级启动被拒绝: result={ack_result}"
        return result

    # 步骤 3: 等待内部升级(解压 + fcs + reboot)
    result.wait_seconds = COMPANION_UPGRADE_WAIT
    log_manager.logger.info(
        f"[Companion-Upgrade] 等待内部升级 {COMPANION_UPGRADE_WAIT}s(含 reboot)"
    )
    time.sleep(COMPANION_UPGRADE_WAIT)

    result.success = True
    log_manager.logger.info("[Companion-Upgrade] companion 升级流程等待结束")
    return result


def trigger_battery_upgrade(gcs, ftp_session, mavlink_version, firmware_path: str,
                            remote_path: str = FTP_BATTERY_FIRMWARE,
                            ack_timeout: float = DEFAULT_ACK_TIMEOUT) -> UpgradeResult:
    """触发电池固件升级(param1=1)

    注意:upgrade_task 中电池分支当前为 stub(onion_upgrade.c:445 注释 "// update battery"),
    本函数仅验证触发链路(FTP 上传 + 命令接收 + ACK),不验证实际升级完成。

    源码:onion_companion.c:227-233
        检查 /root/battery.bin 是否存在,不存在则 param1 改为 255 通知 UAV 拒绝
    """
    result = UpgradeResult()

    firmware_len, crc = _read_firmware_info(firmware_path)
    if firmware_len is None:
        result.error = f"固件文件不存在: {firmware_path}"
        return result

    result.firmware_len = firmware_len
    result.firmware_crc32 = crc

    # 步骤 1: FTP 上传
    if not _upload_firmware(ftp_session, firmware_path, remote_path):
        result.error = "FTP 上传失败"
        return result

    # 步骤 2: 发送触发命令
    log_manager.logger.info("[Bat-Upgrade] 发送 MAV_CMD_UPDATE_COMPANION param1=1")
    ack_result = send_update_companion(gcs, mavlink_version, target=1, timeout=ack_timeout)
    result.ack_result = ack_result

    if ack_result is None:
        result.error = f"{ack_timeout}s 内未收到 COMMAND_ACK"
        return result
    if ack_result != ACK_RESULT_ACCEPTED:
        result.error = f"电池升级被拒绝: result={ack_result}"
        return result

    result.success = True
    log_manager.logger.info("[Bat-Upgrade] 电池升级触发链路验证通过(stub 阶段不验证实际升级)")
    return result


# ==========================================================================
# 6. 自动重连监控
#
# 封装对 WiFi 模块 _check 任务(onion_companion.c:347-409)的监控逻辑:
#     sample_connection()            - 单次采样连接状态
#     monitor_connection_stability() - 连续监控连接稳定性
#     monitor_ssid_auto_switch()     - 监控断连后 30s 自动切换 SSID
#
# 源码事实:
#     任务 _check 每秒一次,局部变量 rewifi_cnt 秒数计数。
#     rewifi_cnt == 15:_check 的 else-if 分支,set_wifi_ssid(当前 ssid) 重初始化 wifi。
#     rewifi_cnt == 30:_check 的 if 分支,切换到另一档 SSID,清零 rewifi_cnt。
#     ssid_chg_flag != 0 && chg_unlink_cnt >= 90 时整机 reboot(仅硬版本 0)。
# ==========================================================================

def sample_connection(serial_session, elapsed: int = 0) -> ConnectionSample:
    """采样当前连接状态(不抛异常,异常返回 None 字段)"""
    sample = ConnectionSample(
        elapsed=elapsed,
        is_linked=None, rssi=None, ssid=None, connect_status=None,
    )
    try:
        status = serial_session.check_wifi_connection()
        if status:
            sample.is_linked = status.get("is_linked")
            sample.rssi = status.get("rssi")
    except Exception as e:
        log_manager.logger.warning(f"[Auto-Recovery] 采样 check_wifi 异常: {e}")

    try:
        wifi_info = serial_session.get_wifi_info()
        if wifi_info:
            sample.ssid = wifi_info.get("ssid")
            sample.connect_status = wifi_info.get("connect_status")
    except Exception as e:
        log_manager.logger.warning(f"[Auto-Recovery] 采样 wifi_info 异常: {e}")

    return sample


def monitor_connection_stability(serial_session, duration_seconds: int,
                                 sample_interval: int = 5) -> StabilityReport:
    """连续监控连接状态

    Args:
        serial_session: 串口会话
        duration_seconds: 总监控时长(秒)
        sample_interval: 采样间隔(秒)

    Returns:
        StabilityReport,包含所有采样和连接率
    """
    report = StabilityReport()
    start = time.time()
    seen_ssids = set()

    while time.time() - start < duration_seconds:
        elapsed = int(time.time() - start)
        sample = sample_connection(serial_session, elapsed=elapsed)
        report.samples.append(sample)

        if sample.is_linked is True:
            report.linked_samples += 1
        if sample.ssid:
            seen_ssids.add(sample.ssid)

        log_manager.logger.info(
            f"[Auto-Recovery] {elapsed}s: linked={sample.is_linked}, "
            f"rssi={sample.rssi}, ssid={sample.ssid}"
        )
        time.sleep(sample_interval)

    report.total_samples = len(report.samples)
    report.linked_ratio = (
        report.linked_samples / report.total_samples if report.total_samples else 0
    )
    report.ssid_seen = list(seen_ssids)
    report.ssid_changed = len(seen_ssids) > 1

    log_manager.logger.info(
        f"[Auto-Recovery] 监控完成: 连接率={report.linked_ratio * 100:.0f}%"
        f"({report.linked_samples}/{report.total_samples}), SSID 变化={report.ssid_changed}"
    )
    return report


def monitor_ssid_auto_switch(serial_session, trigger_ssid: str,
                             wait_seconds: int = SWITCH_SSID_TMOUT_MAX + 10,
                             poll_interval: int = 5) -> AutoSwitchReport:
    """监控 WiFi 断连后 _check 任务自动切换 SSID

    前提:WiFi 模块已通过 change_ssid(trigger_ssid) 切换到无效 SSID,
    本函数在 wait_seconds 内轮询 SSID,如果固件 _check 自动切回(SSID 不再等于
    trigger_ssid),则报告 detected=True。

    Args:
        serial_session: 串口会话
        trigger_ssid: 触发断连的 SSID(检测到当前 SSID 不再包含此值视为已切换)
        wait_seconds: 等待窗口(默认 SWITCH_SSID_TMOUT_MAX + 10s)
        poll_interval: 轮询间隔(秒)

    Returns:
        AutoSwitchReport
    """
    report = AutoSwitchReport(original_ssid=trigger_ssid)
    start = time.time()

    while time.time() - start < wait_seconds:
        elapsed = int(time.time() - start)
        sample = sample_connection(serial_session, elapsed=elapsed)

        current_ssid = sample.ssid or ""
        if current_ssid and trigger_ssid not in current_ssid:
            report.detected = True
            report.switched_to = current_ssid
            report.switch_time_seconds = elapsed
            log_manager.logger.info(
                f"[Auto-Recovery] {elapsed}s 检测到 SSID 自动切换: "
                f"{trigger_ssid} -> {current_ssid}"
            )
            break

        log_manager.logger.info(
            f"[Auto-Recovery] {elapsed}s: ssid={current_ssid or '(空)'}, "
            f"linked={sample.is_linked}"
        )
        time.sleep(poll_interval)

    if not report.detected:
        log_manager.logger.warning(
            f"[Auto-Recovery] {wait_seconds}s 内未检测到 SSID 自动切换"
            f"(预期固件 _check 任务在 {SWITCH_SSID_TMOUT_MAX}s 时切换)"
        )

    return report


# ---------------------------------------------------------------------------
# 物理层协作接口 — 封装与 ProtocolHandler(物理层)的典型交互
#
# 这些函数封装脚本层经常重复的"调物理层方法 + 等待"模式,集中管理
# 波特率/等待时间等 WiFi 专有常量,避免脚本层硬编码。
# ---------------------------------------------------------------------------

def change_ssid_and_wait(serial_session, ssid: str,
                         wait_seconds: float = WIFI_SSID_HOTSWAP_SECONDS) -> bool:
    """切换 SSID 并等待固件热加载完成

    封装 serial_session.change_ssid + 等待 set_ssid_chg_flag 触发热加载的典型模式。
    用于:EULER_NETWORK 改 SSID 后、测试间还原 SSID、stress_aging 循环切换等场景。

    Args:
        serial_session: ProtocolHandler 实例(物理层)
        ssid: 目标 SSID
        wait_seconds: 切换后等待热加载的时间(默认 8s)

    Returns:
        change_ssid 的返回值(成功 True / 失败 False)
    """
    success = serial_session.change_ssid(ssid)
    if success:
        log_manager.logger.info(
            f"[WiFi] SSID 已切换为 {ssid},等待 {wait_seconds}s 热加载"
        )
        time.sleep(wait_seconds)
    else:
        log_manager.logger.warning(f"[WiFi] SSID 切换失败: {ssid}")
    return success


def reconnect_after_reboot(serial_session, port: Optional[str] = None,
                           baudrate: int = WIFI_DEFAULT_BAUDRATE,
                           ready_wait: float = WIFI_REBOOT_READY_SECONDS,
                           retries: int = 3) -> bool:
    """reboot 后重连串口

    封装脚本层重复的 disconnect + sleep + connect 模式,统一使用 WiFi 默认波特率。
    用于:test_wifi_config_change.py 验证 reboot、test_wifi_auto_recovery.py 触发整机重启后。

    依赖物理层方法:
        serial_session.disconnect()  ← SerialPortController 基类
        serial_session.connect(port, baudrate)  ← SerialPortController 基类

    Args:
        serial_session: ProtocolHandler 实例(物理层)
        port: 串口号;None 表示使用 handler 当前绑定的 port(物理层默认行为)
        baudrate: 波特率(默认 921600,与 config.json Wifi_Module.serial_baudrate 一致)
        ready_wait: 断开后等待设备就绪的秒数
        retries: connect 失败时的重试次数

    Returns:
        True 表示重连成功;False 表示 retries 次后仍失败
    """
    try:
        serial_session.disconnect()
    except Exception as e:
        log_manager.logger.warning(f"[WiFi] disconnect 异常(可忽略): {e}")

    time.sleep(ready_wait)

    for attempt in range(1, retries + 1):
        try:
            success = serial_session.connect(port=port, baudrate=baudrate)
        except Exception as e:
            log_manager.logger.warning(
                f"[WiFi] 重连第 {attempt}/{retries} 次异常: {e}"
            )
            success = False

        if success:
            log_manager.logger.info(
                f"[WiFi] 重连成功(第 {attempt} 次): port={port or '(默认)'} @ {baudrate}"
            )
            return True

        if attempt < retries:
            time.sleep(ready_wait)

    log_manager.logger.error(
        f"[WiFi] 重连失败: {retries} 次尝试后仍无法连接 port={port} @ {baudrate}"
    )
    return False
