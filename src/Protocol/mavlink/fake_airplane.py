import ctypes
import hashlib
import subprocess
import re
import socket
import struct
import time
import os
import sys
import threading

from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from src.Protocol.mavlink.param_dict import UavParamDict, serial_to_model, MODEL_TO_CSV

from utils.logger import LogManager,logger


fake_airplane_ip = "172.16.3.168"
NETCARD_INTERFACE = "WLAN 6"

# ==================================================================
# MAVLink System ID / Component ID 常量（对齐协议文档 §4.4.1/§4.2）
# 仅保留本模块实际使用的常量；机巢/广播等常量见 fake_nest.py
# ==================================================================
SYS_ID_UAV   = 1    # 无人机（消息 sys_id）
COMP_ID_GCS  = 39   # 地面站（消息 comp_id）

# 参数校验 CSV 根目录（对齐 dgcs4 ComponentService: RootDir/DirName = AppContext.BaseDirectory/Components）
_PARAM_CSV_BASE = r"C:\Program Files\DGCS\4.0\Components\ParamList"

# 机型 → start_serial 序列号前缀配置表（__main__ 与 MultiSimulationGUI 下拉框共用）
AIRPLANE_MODEL_SERIALS = {
    "V4": "WV40F0K00",
    "V32": "WV32F0K00",
    "L3": "WL30F0K00",
    "Y2": "YY20F0K00",
    "X1": "WX10F0K00",
    "L31": "WL31F0K00",
    "V41": "WV41F0K00",
    "L5": "WL50F0K00",
}

class FakeAirplane:
    def __init__(self, ip_addr=fake_airplane_ip,
                 ground_station_ip="172.16.200.1",
                 ground_station_port=14550,
                 local_port=14551,
                 interface=NETCARD_INTERFACE,
                 mask="255.240.0.0",
                 recv_timeout=1.0,
                 mavlink_version='39'):
        self.target_interface = interface
        self.target_ip = ip_addr
        self.target_mask = mask
        self.ground_station_ip = ground_station_ip
        self.ground_station_port = ground_station_port
        self.local_port = local_port
        self.recv_timeout = recv_timeout
        self.mavlink_version = mavlink_version

        self.local_ip = None
        self.sock = None
        self.udp_connected = False

        self._setup_network()
        self._udp_setup()
        time.sleep(0.5)  # 等待网络完全就绪

    # ------------------------------------------------------------------
    # 网卡 IP 设置 此处为对一个网卡设置多个辅助IP
    # ------------------------------------------------------------------
    def _setup_network(self):

        """Windows 上无 dummy 设备，使用 PowerShell 在活动接口上添加辅助 IP 作为等价逻辑"""
        if self._ip_exists_locally(self.target_ip):
            logger.info(f"IP {self.target_ip} 已存在于本机接口，跳过添加")
            self.local_ip = self.target_ip
            return True

        if not self.target_interface:
            logger.error("未找到活动的物理网络接口，无法添加辅助IP")
            return False

        ps_cmd = (
            f'powershell -NoProfile -Command '
            f'"New-NetIPAddress -InterfaceAlias \'{self.target_interface}\' '
            f'-IPAddress \'{self.target_ip}\' -PrefixLength 24"'
        )
        
        logger.info(f"在 {self.target_interface} 上添加辅助IP: {self.target_ip}")
        ret = os.system(ps_cmd)
        if ret != 0:
            logger.error(f"New-NetIPAddress 执行失败，返回码: {ret}")
            return False
        self.local_ip = self.target_ip
    
    # ------------------------------------------------------------------
    # 网卡 IP 设置
    # ------------------------------------------------------------------
    def _setup_network_old(self):
        """检查并按需把目标网卡的 IP 配置为 self.target_ip"""
        self.local_ip = self._get_local_ip()
        if self.local_ip is None:
            logger.warning(f"未找到 {self.target_interface} 的 IP 地址，请检查网络连接。")
            return

        if self.local_ip != self.target_ip:
            self._set_ip_address()
            self.local_ip = self._get_local_ip()
            if self.local_ip == self.target_ip:
                logger.info(f"{self.target_interface} 的 IP 地址已成功设置为: {self.local_ip}")
        else:
            logger.info(f"{self.target_interface} 的 IP 地址已正确设置为: {self.local_ip}")

    def _get_local_ip(self):
        """查询目标网卡的 IPv4 地址。

        优先用 PowerShell Get-NetIPAddress(结构化、不依赖 locale / 控制台代码页),
        失败回退到 ipconfig /all + 正则解析(用 cp936 显式解码,避免默认 locale 错配)。

        为什么不用 text=True 默认解码:
            ipconfig /all 在中文 Windows 上输出 cp936 字节,若 Python 进程 locale
            与系统不一致(Jenkins 节点常见),默认解码会乱码,IPv4 行匹配失败 →
            "未找到 WLAN 6 的 IP 地址"误报(实际网卡已配置 IP)。#459
        """
        ip = self._get_local_ip_via_powershell()
        if ip:
            return ip
        return self._get_local_ip_via_ipconfig()

    def _get_local_ip_via_powershell(self):
        """PowerShell Get-NetIPAddress — 结构化、locale 无关。"""
        try:
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 f'(Get-NetIPAddress -InterfaceAlias "{self.target_interface}" '
                 f'-AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress'],
                capture_output=True, text=True, encoding='utf-8', timeout=5
            )
        except Exception as e:
            logger.warning(f"[FakeAirplane] PowerShell Get-NetIPAddress 调用失败: {e}")
            return None

        ip = (result.stdout or '').strip()
        # 一个接口可能有多个 IPv4(主 IP + link-local fallback),取第一个有效的
        for candidate in re.findall(r'\d{1,3}(?:\.\d{1,3}){3}', ip):
            if not candidate.startswith('169.254.'):  # 跳过 APIPA link-local
                logger.info(
                    f"[FakeAirplane] PowerShell 检测到 {self.target_interface} IPv4 = {candidate}"
                )
                return candidate
        # 接口不存在 / 未配置 IP — PowerShell 返回空,或全是 link-local
        logger.warning(
            f"[FakeAirplane] PowerShell 未查到 {self.target_interface} 的有效 IPv4 "
            f"(rc={result.returncode}, stdout={ip!r}, stderr={result.stderr.strip()[:120]})"
        )
        return None

    def _get_local_ip_via_ipconfig(self):
        """ipconfig /all + cp936 显式解码,作为 PowerShell 不可用时的兜底。"""
        try:
            result = subprocess.run(['ipconfig', '/all'],
                                    capture_output=True, timeout=5)
            text = result.stdout.decode('cp936', errors='replace')
        except Exception as e:
            logger.error(f"[FakeAirplane] ipconfig 调用失败: {e}")
            return None

        in_target_section = False
        for line in text.split('\n'):
            line = line.strip()
            if self.target_interface in line:
                in_target_section = True
                continue
            if in_target_section:
                match = re.search(r'IPv4[^\n]*?[:\s]+(\d{1,3}(?:\.\d{1,3}){3})', line)
                if match:
                    logger.info(
                        f"[FakeAirplane] ipconfig 解析到 {self.target_interface} IPv4 = {match.group(1)}"
                    )
                    return match.group(1)
                # 进入新 adapter section → 退出当前 section
                if "适配器" in line or "adapter" in line.lower():
                    in_target_section = False
        logger.warning(f"[FakeAirplane] ipconfig 解析未找到 {self.target_interface} 的 IPv4")
        return None

    def _set_ip_address(self):
        """通过 netsh 静态配置网卡 IP（需要管理员权限）"""
        try:
            if ctypes.windll.shell32.IsUserAnAdmin():
                logger.info("管理员权限已确认.")
            else:
                logger.warning("请以管理员身份运行此脚本.")
                return False
        except Exception:
            return False

        try:
            cmd = [
                'netsh', 'interface', 'ip', 'set', 'address',
                f'name={self.target_interface}',
                'source=static',
                f'addr={self.target_ip}',
                f'mask={self.target_mask}',
                'store=persistent'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"{self.target_interface} 的 IP 已成功设置为: {self.target_ip} / {self.target_mask}")
                return True
            logger.error(f"设置失败: {result.stderr}")
            return False
        except Exception as e:
            logger.error(f"发生错误: {e}")
            return False

    # ------------------------------------------------------------------
    # 检查 IP 是否已绑定到本机任意接口
    # ------------------------------------------------------------------   
    def _ip_exists_locally(self, ip: str) -> bool:
        """检查 IP 是否已绑定到本机任意接口"""
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind((ip, 0))
            return True
        except OSError:
            return False
        finally:
            if s:
                s.close()

    # ------------------------------------------------------------------
    # UDP 通讯
    # ------------------------------------------------------------------
    def _udp_setup(self):
        """创建并绑定 UDP 套接字"""
        if self.local_ip is None:
            logger.warning("本地 IP 未配置，跳过 UDP 套接字创建。")
            return

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        self.sock.settimeout(self.recv_timeout)
        self.udp_connected = True

        max_retries = 10
        for attempt in range(1, max_retries + 1):
            try:
                self.sock.bind((self.local_ip, self.local_port))
                logger.info(f"UDP 套接字已绑定到 {self.local_ip}:{self.local_port}")
                logger.info(f"目标地面站: {self.ground_station_ip}:{self.ground_station_port}")
                break
            except OSError as e:
                if e.winerror == 10049 and attempt < max_retries:
                    logger.info(f"IP 未生效，1s 后重试 ({attempt + 1}/{max_retries})")
                    time.sleep(1)
                else:
                    logger.warning(f"IP 重试{max_retries}次后仍未生效")
                    raise

    def close(self):
        """关闭 UDP 通讯"""
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.udp_connected = False
        logger.info("FakeAirplane UDP 通讯已关闭。")
    # ------------------------------------------------------------------
    # MAVLink 收发
    # ------------------------------------------------------------------
    def send(self, message: MAVLink_message, addr=None) -> bool:
        """向地面站发送一条 MAVLink 消息

        Args:
            message: 待发送的 MAVLink_message 实例
            addr: 目标 (ip, port)，省略则发送给默认地面站

        Returns:
            发送成功返回 True，否则 False
        """
        if not self.udp_connected or self.sock is None:
            logger.warning("UDP 未连接，无法发送数据。")
            return False

        if addr is None:
            addr = (self.ground_station_ip, self.ground_station_port)

        try:
            data = message.pack()
            self.sock.sendto(data, addr)
            return True
        except Exception as e:
            logger.error(f"发送数据失败: {e}")
            return False

    def receive(self, bufsize: int = 1024):
        """接收并解析一条标准 MAVLink 消息。

        Returns:
            (MAVLink_message, addr) 元组；超时返回 (None, None)
        """
        if not self.udp_connected or self.sock is None:
            return None, None

        try:
            data, _ = self.sock.recvfrom(bufsize)
            addr = (self.ground_station_ip, self.ground_station_port)
        except socket.timeout:
            return None, None
        except Exception as e:
            logger.error(f"接收数据失败: {e}")
            return None, None

        # ---- DEBUG: 打印所有收到的 UDP 报文（暂时注释）----
        # hex_full = data.hex()
        # hex_spaced = ' '.join(f'{b:02x}' for b in data)
        # ascii_repr = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data)
        # print(f"\n[AIRPLANE-RECV] local={self.local_ip}:{self.local_port} ← {addr} | len={len(data)}")
        # print(f"  hex_full=  {hex_full}")
        # print(f"  hex_spaced={hex_spaced}")
        # print(f"  ascii=     {ascii_repr}")

        try:
            message = MAVLink_message(hex_data=data.hex())
            # fields_str = ', '.join(f'{k}={v}' for k, v in message.fields.items())
            # print(f"  parsed=    msg_id={message.msg_id} sys_id={message.sys_id} "
            #       f"comp_id={message.comp_id} "
            #       f"fields=[{fields_str}]")
            return message, addr
        except Exception as e:
            # print(f"  parse_failed | error={e}")
            logger.error(f"解析 MAVLink 消息失败: {e}")
            return None, addr


class _WindSpeedSender:
    """风速消息发送器 - 后台线程持续监听并响应 id=1 请求"""

    def __init__(self, log_manager, fake_plane, addr, seq=604054808):
        self.log_manager = log_manager
        self.fake_plane = fake_plane
        self.addr = addr
        self.seq = seq
        self.wind_speed_x = 0
        self.wind_speed_y = 0
        self.running = False
        self.thread = None
        self._lock = __import__('threading').Lock()
        self.success = False

    def start(self):
        """启动后台发送线程"""
        self.running = True
        self.thread = __import__('threading').Thread(target=self._run, daemon=True)
        self.thread.start()
        print("[TEST] 风速发送线程已启动")

    def stop(self):
        """停止后台发送线程"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        print("[TEST] 风速发送线程已停止")

    def _build_wind_speed_msg(self, wind_speed_x, wind_speed_y, version, seq=604054808):
        """构建包含风速信息的 id=5 消息."""
        return MAVLink_message(msg_id=5, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                            version=version,
                            fields={
                                'seq': seq,
                                'sensor_health': 3583,
                                'voltage_battery': 16277,
                                'wifi_up': 74,
                                'ssid': b'dmd',
                                'voltage_battery_diff': 71,
                                'voltage_battery_history_diff': 71,
                                'bat_serial_prefix': b'V4S24101',
                                'wind_speed_x': wind_speed_x,
                                'wind_speed_y': wind_speed_y,
                                'bat_serial_suffix': b'',
                                'time_need_reset': 1,
                                'uav_speed_horz': 3,
                            })

    def update_send_success(self, send_success):
        """更新风速参数，后续发送使用新参数"""
        with self._lock:
            self.success = send_success

    def update_wind_speed(self, wind_speed_x, wind_speed_y):
        """更新风速参数，后续发送使用新参数"""
        with self._lock:
            self.wind_speed_x = wind_speed_x
            self.wind_speed_y = wind_speed_y
            
    def _run(self):
        """后台线程运行逻辑：收到id=1后发送一帧"""
        while self.running:
            received, _ = self.fake_plane.receive()
            if received is None:
                time.sleep(0.05)
                continue
            if received.msg_id == 0:
                continue

            if received.msg_id == 1:
                
                with self._lock:
                    wx = self.wind_speed_x
                    wy = self.wind_speed_y
                wx_ms = wx / 100.0
                wy_ms = wy / 100.0
                magnitude = (wx_ms ** 2 + wy_ms ** 2) ** 0.5
                print(f"[TEST] 飞机{self.fake_plane.local_ip}:{self.fake_plane.local_port}后台线程收到 id=1 → 发送风速消息: wx={wx_ms}m/s, wy={wy_ms}m/s, magnitude={magnitude:.2f}m/s")
                msg = self._build_wind_speed_msg(wx, wy, self.fake_plane.mavlink_version, self.seq)
                ok = self.fake_plane.send(msg, addr=self.addr)
                if not ok:
                    self.update_send_success(False)
                    self.log_manager.logger.info(f"[TEST] 飞机{self.fake_plane.local_ip}:{self.fake_plane.local_port}风速模拟失败")
                else:
                    self.update_send_success(True)
                    self.log_manager.logger.info(f"[TEST] 飞机{self.fake_plane.local_ip}:{self.fake_plane.local_port}风速模拟成功 x方向：{self.wind_speed_x}，y方向：{self.wind_speed_y}")
                time.sleep(0.5)
            else:
                pass


def _send_wind_speed_async(log_manager, wind_sender, wind_speed_x, wind_speed_y):
    """更新风速发送器的参数（不阻塞等待响应）

    Args:
        log_manager: 日志管理器
        wind_sender: _WindSpeedSender 实例
        wind_speed_x: x方向风速原始值(cm/s)
        wind_speed_y: y方向风速原始值(cm/s)

    Returns:
        True - 参数更新成功
    """
    timestart = time.time()

    wind_sender.update_wind_speed(wind_speed_x, wind_speed_y)

    while not wind_sender.success:
        time.sleep(0.05)
        if time.time() - timestart > 1.5:
            # 发送失败状态持续1帧时间以上
            print(f"[TEST] 更新风速参数失败")
            log_manager.logger.info(f"[TEST] 飞机{wind_sender.fake_plane.local_ip}:{wind_sender.fake_plane.local_port}风速参数更新失败")
            return False
    
    time.sleep(0.1)
    log_manager.logger.info(f"[TEST] 飞机{wind_sender.fake_plane.local_ip}:{wind_sender.fake_plane.local_port}风速参数更新 x方向：{wind_speed_x}，y方向：{wind_speed_y}")
    wind_sender.update_send_success(False)
    return True


# ==================================================================
# _FakeAirplaneMessageSender：单架假飞机的响应线程
# ------------------------------------------------------------------
# 由 _FakeAirplaneMessageSenders 批量创建并管理生命周期
# ==================================================================

class _FakeAirplaneMessageSender:
    """单架假飞机的消息响应器：一个实例 = 一架 FakeAirplane + 一个后台线程。

    工作流程：
        1. start() 启动线程，先做 MAVLink 握手，再进入主循环。
        2. 主循环持续从 self.fake_plane 接收地面站消息，
           按类级配置表 _RESPONSE_RULES 调度响应：
             构建（叠加 self 当前状态）→ 发送 → 日志 → 按 delay 节流。
        3. update_laser/update_nova/update_firework/update_lantern/
              update_trumpet/update_parachute() 可在运行期改写各负载状态。
        4. stop() 通知线程退出并 join。

    协议响应规则（_RESPONSE_RULES）结构：

        _RESPONSE_RULES[入站 msg_id] = {
            'delay': <节流间隔秒> | None,
            'rules': [
                {
                    'build': <本类 @staticmethod 名称（字符串）>,
                    'label': <日志标签>,
                    'state': {<builder 形参>: <self 属性名>}  # 叠加当前状态；空 dict 表示不依赖状态
                    'when' : <可选 callable(received) -> bool>  # True 才发送
                },
                ...
            ],
        }
    """

    # 协议常量
    _DEFAULT_SEQ = 604054808
    _DEFAULT_CODE = 1
    _DEFAULT_SERIAL = "WX10F0K00"

    # 时序常量（秒）
    _HANDSHAKE_INITIAL_DELAY = 1
    _HANDSHAKE_TIMEOUT = 30.0
    _POST_IDENTITY_DELAY = 0.3
    _LOOP_POLL_INTERVAL = 0.05
    _HEARTBEAT_SEND_INTERVAL = 0.5
    # 一次成功发送后，self.success 保持 True 的时长；之后自动回落为 False
    _SUCCESS_HOLD_SECONDS = 0.5

    # 地面站消息 ID
    _MSG_ID_HEARTBEAT = 0
    _MSG_ID_HEARTBEAT_DMD = 1
    _MSG_ID_GET_IDENTIFY_INFO = 3
    _MSG_ID_COMMAND_LONG = 76
    _MSG_ID_SWARM_FLIGHT_START = 50
    _MSG_ID_COMMAND_ACK = 77
    # 修正：v44 协议 set_mode 的 msg_id 为 11（旧代码误写为 75，导致规则永不命中）
    _MSG_ID_SET_MODE = 11
    # 开始表演全流程新增入站消息 ID
    _MSG_ID_PARAM_REQUEST_READ = 20
    _MSG_ID_PARAM_REQUEST_LIST = 21
    _MSG_ID_PARAM_SET = 23
    _MSG_ID_MISSION_REQUEST_VERIFY = 41
    _MSG_ID_CALIB_TIME = 46
    _MSG_ID_LIGHT_DATA = 55
    _MSG_ID_NET_FILE_COMMAND = 63

    # 出站消息 ID
    _MSG_ID_TIME_ORIGIN = 47
    _MSG_ID_PARAM_VALUE = 22
    _MSG_ID_PARAM_REQUEST_LIST_ACK = 24
    _MSG_ID_MISSION_REQUEST_ACK = 42
    _MSG_ID_REMAINING_CAPACITY_STATE = 59

    # 识别完成前放行的入站消息（其余一律屏蔽）
    _ALLOW_BEFORE_IDENTIFY = (_MSG_ID_HEARTBEAT, _MSG_ID_GET_IDENTIFY_INFO)

    # UavMode 取值（对齐 dgcs4 CommonType/Utils/Types.cs）
    _UAV_MODE_G = 4          # G 模式（编队/剧本）
    _UAV_MODE_R = 6          # 返航 RTL
    _UAV_MODE_LD = 9         # 降落 Land

    # FlyState（内部飞行状态机）
    _FLY_DISARM = 0
    _FLY_LANDED = 1
    _FLY_GUIDE_IDLE = 2
    _FLY_GUIDE_TAKEOFF = 3
    _FLY_GUIDE_PLAY = 4
    _FLY_LAND = 5
    _FLY_RETURN = 6

    # PlayState（对外表演进度）
    _PLAY_IDLE = 0
    _PLAY_DISARMED = 1
    _PLAY_WAIT_TK = 2
    _PLAY_TAKEOFF = 3
    _PLAY_FLYING = 4
    _PLAY_PLAYING = 5
    _PLAY_LANDING = 6
    _PLAY_LANDED = 7

    # MAV_CMD（COMMAND_LONG.command，对齐 dgcs4 dmd_uav.generated.cs）
    _MAV_CMD_COMPONENT_ARM_DISARM = 400
    _MAV_CMD_CAN_ARM = 401          # 起飞前预检"能否解锁"
    _MAV_CMD_FLIGHT_STOP = 40003    # 急停
    _MAV_CMD_CHANGE_MISSION = 40005 # 切换剧本
    _MAV_CMD_RETURN_TYPE = 40048    # 返航/降落类型

    # NET_FILE_COMMAND(63) 子命令（对齐 src/Protocol/airplane/mav_net_file.py）
    _NET_FILE_OPEN = 0
    _NET_FILE_WRITE = 1
    _NET_FILE_READ = 2
    _NET_FILE_CLOSE = 3
    _NET_FILE_ACK = 4
    _NET_FILE_VERIFY = 5

    # 模拟参数表（(param_id, value, param_type)）——分批经 PARAM_VALUE(22) 回传。
    # 简化桩：只需让地面站"参数就绪"校验通过，无需真机全量参数。
    _DEFAULT_PARAM_TABLE = [
        ('SR0_PARAM', 4.0, 9),
        ('SYSID_THISMAV', 1.0, 9),
        ('FENCE_ENABLE', 1.0, 9),
        ('FENCE_ALT_MAX', 120.0, 9),
        ('WPNAV_SPEED', 500.0, 9),
        ('ANGLE_MAX', 3000.0, 9),
        ('BATT_CAPACITY', 22000.0, 9),
        ('RTL_ALT', 1500.0, 9),
        ('TKOFF_ALT', 500.0, 9),
        ('LAND_SPEED', 50.0, 9),
    ]

    # ------------------------------------------------------------------
    # sensor_health 位表（16 bits，对应 packed_state 消息的 sensor_health 字段）
    #
    #   ┌─────┬─────────────────────┬──────────────────────┐
    #   │ Bit │        含义         │       取值逻辑       │
    #   ├─────┼─────────────────────┼──────────────────────┤
    #   │ 0   │ IMU                 │ 0=正常，1=异常       │
    #   │ 1   │ Baro（气压计）      │ 0=正常，1=异常       │
    #   │ 2   │ Compass / BNO       │ 0=正常，1=异常       │
    #   │ 3   │ GPS / UWB           │ 0=正常，1=异常       │
    #   │ 4   │ Battery             │ 0=正常，1=异常       │
    #   │ 5   │ BnoReset            │ 0=正常，1=异常       │
    #   │ 6   │ Acc calibrated      │ 0=正常，1=异常       │
    #   │ 7   │ Compass calibrated  │ 0=正常，1=异常       │
    #   │ 8   │ Color calibrated    │ 0=正常，1=异常       │
    #   │ 9   │ Magnetic calibrated │ 0=正常，1=异常       │
    #   │ 10  │ Scram               │ 0=正常，1=异常       │
    #   │ 11  │ ESC                 │ 0=正常，1=异常       │
    #   │ 12  │ Parachute           │ 取反：1=正常，0=异常 │
    #   │ 13  │ Tele                │ 取反：1=正常，0=异常 │
    #   │ 14  │ BMS                 │ 取反：1=正常，0=异常 │
    #   │ 15  │ Module              │ 取反：1=正常，0=异常 │
    #   └─────┴─────────────────────┴──────────────────────┘
    # ------------------------------------------------------------------
    _SENSOR_HEALTH_BITS = {
        'imu': 0, 'baro': 1, 'compass': 2, 'gps': 3,
        'battery': 4, 'bno_reset': 5, 'acc_calibrated': 6,
        'compass_calibrated': 7, 'color_calibrated': 8,
        'magnetic_calibrated': 9, 'scram': 10, 'esc': 11,
        'parachute': 12, 'tele': 13, 'bms': 14, 'module': 15,
    }
    # bit 12-15 取反逻辑：内部存储 0=正常/1=异常，写入寄存器时翻转
    _SENSOR_HEALTH_INVERTED_BITS = {12, 13, 14, 15}

    # ---- failsafe(0x06) 位表：故障名 → bit（对齐 C# AlarmCode Failsafe 掩码）----
    # C# 列表为 bit15→bit0 倒序（F_EKF_VERT=bit0 ... F_CRASH=bit15），
    # 参数名 = 枚举名小写化（f_ 前缀，避免与 battery/parachute 等现有参数冲突）。
    _FAILSAFE_BITS = {
        'f_crash': 15, 'f_radio': 14, 'f_battery': 13, 'f_fence_alt': 12,
        'f_fence_circle': 11, 'f_waypoint': 10, 'f_too_far': 9, 'f_static_dist': 8,
        'f_vibrate': 7, 'f_drama_fail': 6, 'f_parachute': 5, 'f_sensor_fail': 4,
        'f_fence_2': 3, 'f_ekf_stab': 2, 'f_ekf_horz': 1, 'f_ekf_vert': 0,
    }

    # COMMAND_LONG(76) 挂载点灯映射：param7 → (payload_type, config 属性名, 标签)
    # param1==1.0 表示"点亮/动作"，param7 选择负载类型。
    _PAYLOAD_LIGHT_MAP = {
        3.0:  (1, 'firework_config', 'firework'),
        9.0:  (2, 'laser_config', 'laser'),
        12.0: (3, 'nova_config', 'nova'),
        15.0: (5, 'parachute_config', 'parachute'),
        16.0: (10, 'confetti_config', 'confetti'),  # 撒花器
    }

    # 灯类负载查询映射（param7=14 共用）：param1 → (payload_type, config 属性名, 标签)
    # config_attr 为 None 表示查询后默认回复空（旧孔明灯 param1=2）。
    _PAYLOAD_LANTERN_QUERY_MAP = {
        1.0: (4, 'lantern_config', 'lantern'),                     # 折叠灯 FoldLantern
        2.0: (7, 'kongming_lantern_config', 'kongming_lantern'),   # 旧孔明灯 KongMingLantern
        3.0: (8, 'peach_lantern_config', 'peach_lantern'),         # 蟠桃灯 PeachLantern
        4.0: (9, 'fish_lantern_config', 'fish_lantern'),           # 鱼灯 FishLantern
    }

    # ------------------------------------------------------------------
    # 协议响应规则表 — 无状态回显（只读构建，一规则一消息）
    # 仅保留心跳/心跳DMD/身份三类纯回显；命令类交互统一走 _STATE_RULES。
    # ------------------------------------------------------------------
    _RESPONSE_RULES = {
        _MSG_ID_HEARTBEAT: {
            'delay': None,
            'rules': [
                {'build': '_build_id_000', 'label': 'id=0(0x00)',
                 'state': {}},
            ],
        },
        _MSG_ID_GET_IDENTIFY_INFO: {
            'delay': None,
            'rules': [
                {'build': '_build_id_002', 'label': 'id=2(0x02)',
                 'state': {'serial': 'serial',
                           'code': 'code'}},
            ],
        },
        _MSG_ID_HEARTBEAT_DMD: {
            'delay': _HEARTBEAT_SEND_INTERVAL,
            'rules': [
                {'build': '_build_id_005', 'label': 'id=5(0x05)',
                 'state': {'wind_speed_x': 'wind_speed_x',
                           'wind_speed_y': 'wind_speed_y',
                           'seq': 'seq'}},
                {'build': '_build_id_008', 'label': 'id=8(0x08)',
                 'state': {'nova_light_version': 'nova_light_version',
                           'gimbal_version': 'gimbal_version'},
                 'when': lambda recv: recv.fields.get('extend') == 1},
                {'build': '_build_id_204', 'label': 'id=204(0xCC)',
                 'state': {'laser_state': 'laser_state',
                           'nova_state': 'nova_state',
                           'lantern_state': 'lantern_state',
                           'trumpet_state': 'trumpet_state',
                           'parachute_state': 'parachute_state'}},
            ],
        },
    }

    # ------------------------------------------------------------------
    # 有状态协议交互调度表 —— msg_id → 处理方法名
    # 这些交互需读写内部状态或依赖请求内容（对时/参数/剧本/校验/切模式/开始表演/
    # 命令），不适合塞进无副作用的 _RESPONSE_RULES 查表，走 _dispatch_request 分支。
    # ------------------------------------------------------------------
    _STATE_RULES = {
        _MSG_ID_SET_MODE: '_handle_set_mode',
        _MSG_ID_CALIB_TIME: '_handle_calib_time',
        _MSG_ID_PARAM_REQUEST_LIST: '_handle_param_request_list',
        _MSG_ID_PARAM_REQUEST_READ: '_handle_param_request_read',
        _MSG_ID_PARAM_SET: '_handle_param_set',
        _MSG_ID_NET_FILE_COMMAND: '_handle_net_file_command',
        _MSG_ID_MISSION_REQUEST_VERIFY: '_handle_mission_request_verify',
        _MSG_ID_SWARM_FLIGHT_START: '_handle_swarm_flight_start',
        _MSG_ID_LIGHT_DATA: '_handle_light_data',
        _MSG_ID_COMMAND_LONG: '_handle_command_long',
    }

    def __init__(self, log_manager, fake_plane, addr, serial=_DEFAULT_SERIAL, code=_DEFAULT_CODE, nova_light_version=b"1234", gimbal_version=b"", seq=_DEFAULT_SEQ):
        self.log_manager = log_manager
        self.fake_plane = fake_plane
        self.addr = addr
        self.seq = seq
        self.serial = serial
        self.code = code
        self.wind_speed_x = 0
        self.wind_speed_y = 0
        self.laser_config = [0, 0, 0, 0]
        self.nova_config = 0
        self.lantern_config = 0
        self.trumpet_config = 0
        self.parachute_config = 0
        self.laser_state = 0
        self.nova_state = 0
        self.lantern_state = 0
        self.trumpet_state = 0
        self.parachute_state = 0
        self.firework_config = 0
        self.trumpet = 0
        self.parachute = 0
        # 蟠桃灯 / 鱼灯 / 旧孔明灯 / 撒花器
        self.peach_lantern_config = 0
        self.fish_lantern_config = 0
        self.kongming_lantern_config = 0
        self.confetti_config = 0
        self.rtk_radio_850m = 72   # 850MHz RTK 电台状态 (uint8)
        self.rtk_radio_2g4 = 69    # 2.4GHz RTK 电台状态 (uint8)
        # ---- sensor_health 各传感器状态（0=正常, 1=异常）----
        self._sensor_imu = 1
        self._sensor_baro = 1
        self._sensor_compass = 1
        self._sensor_gps = 1
        self._sensor_battery = 1
        self._sensor_bno_reset = 1
        self._sensor_acc_calibrated = 1
        self._sensor_compass_calibrated = 1
        self._sensor_color_calibrated = 1
        self._sensor_magnetic_calibrated = 1
        self._sensor_scram = 1
        self._sensor_esc = 1
        self._sensor_parachute = 1
        self._sensor_tele = 1
        self._sensor_bms = 1
        self._sensor_module = 1
        # ---- failsafe(0x06) 故障状态（enable=False 默认不外发；未配置的故障位一律为 0）----
        self.enable_failsafe = False
        self.failsafe_flags = {name: 0 for name in self._FAILSAFE_BITS}
        self.nova_light_version = nova_light_version
        self.gimbal_version = gimbal_version
        # ---- autopilot 枚举值（独立假飞机=20 DMD_FC，机巢管理的假飞机=21 DMD_COM）----
        self.autopilot = 20  # 默认 DMD_FC
        # ---- 版本信息字段（可在运行时通过 update_version 更新）----
        self.flight_controller_version = b'n3.j.196'  # FC_Version / 飞控版本
        self.companion_version = b'V3.631'            # 伴侣计算机版本
        self.battery_version = b''                    # 电池版本
        self.gps_version = b'UM16982'                 # GPS 版本
        self.servo_ver = 0                            # 舵机版本
        self.tele_version = b'E013'                   # 遥测模块版本
        self.bms_version = b''                        # BMS 版本
        self.rid_version = b''                        # RID 版本
        # ---- 电池/电压相关字段（可通过 update_bat 更新）----
        self.voltage_battery = 34000                # 电池电压 (mV)
        self.voltage_battery_percent = 95           # 电池电量百分比
        self.voltage_battery_diff = 0               # 电池电压差 (mV)
        self.voltage_battery_history_diff = 0       # 历史电池电压差 (mV)
        self.bat_serial_prefix = b'V3F230324-'      # 电池序列号前缀
        self.bat_serial_suffix = b'3355'            # 电池序列号后缀
        self.bat_serial_need_reset = 0              # 电池序列号需重置标志
        self.charge_state = 0                       # 充电状态
        self.battery_time = 78                      # 电池使用时间
        self.temp_batt = 0                          # 电池温度
        self.battery_capability = 20                # 电池容量
        self.battery_used_times = 12                # 电池使用次数
        self.voltage_battery_cell1 = 3500           # 电芯1电压 (mV)
        self.voltage_battery_cell2 = 3500           # 电芯2电压 (mV)
        self.voltage_battery_cell3 = 3500           # 电芯3电压 (mV)
        self.voltage_battery_cell4 = 3500           # 电芯4电压 (mV)
        self.voltage_battery_cell5 = 3500           # 电芯5电压 (mV)
        self.voltage_battery_cell6 = 3500           # 电芯6电压 (mV)
        self.voltage_rid_bat = 0                    # RID 电池电压 (mV)

        # ---- 0x3B REMAINING_CAPACITY(59) 字段（可通过 update_bat 更新）----
        self.safe_fly_radius = 500.0            # 安全飞行半径 (m)
        self.remain_fly_time = 1200             # 剩余飞行时间 (s)
        self.go_home_need_time = 60             # 返航所需时间 (s)
        self.land_need_time = 30                # 降落所需时间 (s)
        self.go_home_need_capacity = 500        # 返航所需电量 (mAh)
        self.land_need_capacity = 300           # 降落所需电量 (mAh)
        self.battery_total_capaticy = 22000     # 电池总容量 (mAh，协议原文拼写)
        self.battery_remain_capaticy = 20000    # 电池剩余容量 (mAh，协议原文拼写)
        self.battry_capacity_percentage = 90    # 电池容量百分比 (协议原文拼写)
        # ---- param_hash 来源标记（1=手动设置, 0=自动计算）----
        self._param_hash_source = 0
        self.cur_lat = 226868664
        self.cur_lon = 1140224548
        self.tar_lat = 226868664
        self.tar_lon = 1140224548
        self.cur_alt = 0
        self.tar_alt = 0
        self.fix_type = 6  # GPS 定位类型 (0-6, MAVLink msg_id=5 B=uint8_t)
        self.running = False
        self.thread = None
        self._lock = threading.Lock()
        self.success = False
        self._identified = False
        self._success_timer = None  # type: threading.Timer | None

        # ---- ACK 失败响应配置 ----
        # _ack_fail_count: 对所有 command 统一返回 result=4 的次数（0=禁用）
        self._ack_fail_count: int = 0
        # _ack_fail_counters: {command_id: current_count} — 各 command 已返回 result=4 的次数
        self._ack_fail_counters: dict[int, int] = {}
        # _ack_fail_last_time: {command_id: timestamp} — 各 command 上次收到的时间
        self._ack_fail_last_time: dict[int, float] = {}

        # ---- ACK 静默响应配置 ----
        # _ack_silence_count: 对所有 command 统一不回复的次数（0=禁用）
        self._ack_silence_count: int = 0
        # _ack_silence_counters: {command_id: current_count} — 各 command 已静默的次数
        self._ack_silence_counters: dict[int, int] = {}
        # _ack_silence_last_time: {command_id: timestamp} — 各 command 上次收到的时间
        self._ack_silence_last_time: dict[int, float] = {}

        # ---- ACK 特定 command result 覆写配置 ----
        # _ack_cmd_result_enabled: 是否启用按 command 覆写 result
        self._ack_cmd_result_enabled: bool = False
        # _ack_cmd_result_map: {command_id: result} — 特定 command 的 ACK result 覆写值
        self._ack_cmd_result_map: dict[int, int] = {}

        # ---- 开始表演全流程：状态机字段 ----
        # mode 默认 G(4)：地面站起飞前 CheckCanArm 要求 packed_state.mode==G，
        # 且"开始表演"流程不下发 SET_MODE，故飞机须始终以 G 模式上报。
        self.mode = self._UAV_MODE_G  # 当前模式：4=G, 6=R, 9=LD
        self.armed = 0                # 是否解锁 0/1
        self.fly_state = self._FLY_DISARM   # 内部飞行状态机（FlyState）
        self.play_state = self._PLAY_IDLE   # 对外表演进度（PlayState 0~7）
        self.mission_id = 0           # 当前剧本 id
        self.loaded_missions = set()  # 已下发并"就绪"的剧本 id 集合
        self.epoch_now_ms = 0         # 最近一次对时基准（相对 1970 UTC 毫秒）
        self.takeoff_time_ms = 0      # 起飞绝对时刻（相对 1970 UTC 毫秒）
        self.play_time_ms = 0         # 进入播放绝对时刻
        # play_duration_ms=0 表示仅带位置微动 Hover，不自动降落；
        # >0 则到达时长后自动切 Land/Return（测试用，自测需要走完 起飞→播→落→上锁）。
        self.play_duration_ms = 0
        self.land_duration_ms = 4000  # 起飞/降落各阶段时长
        self.takeoff_height_mm = 5000  # 起飞高度(mm)，来自 ascend
        self.land_height_mm = 3000     # 降落高度(mm)，来自 descend
        self._phase_start_ms = 0       # 当前飞行阶段起始时刻
        self._flight_base_lat = 0     # 表演开始时的基准纬度（1e7 度）
        self._flight_base_lon = 0     # 表演开始时的基准经度（1e7 度）
        self.final_mode = self._UAV_MODE_R  # 结束模式（R/LD）
        self.light_r = 0
        self.light_g = 0
        self.light_b = 0
        self.drama_state = 0          # 剧本状态 (MAVLink msg_id=5 drama_state，可由 update_drama_state 覆写)
        self.mission_request_ack_result = -1  # 0x2A MISSION_REQUEST_ACK result 覆写值
        # (-1=AUTO 按 loaded_missions 自动计算 0/1；>=0 强制覆写，可由 update_drama_state 修改)
        self._flight_thread = None    # 飞行推进线程
        self._flight_running = False
        self._now_ms_override = None  # 测试用：注入时钟（None 时取真实时间）
        self._net_files = {}          # 并发文件传输: {fid: {name, length, mission_id, buffer}}
        self._next_fid = 1            # 自增文件句柄
        self._file_data_cache = {}    # CLOSE→VERIFY 中间缓存: {fname: bytes}，MISSION_REQUEST_VERIFY 时清理
        self._landed_at_ms = 0        # 落地时刻（用于落地后自动上锁）
        self._params_set = {}         # PARAM_SET 写入的参数缓存

        # ---- bin 文件保存开关/路径（默认关闭，路径保持现有）----
        self.enable_bin_save = False
        self.bin_save_dir = self.DRAMA_SAVE_ROOT
        self._last_saved_bin_path = None   # 最近一次接收并保存的 bin 路径（0x32 时用于改名）

        # ---- 航点解析/对比开关（默认关闭，由外部 GUI 触发）----
        self.enable_waypoint_parse = False
        self.enable_waypoint_compare = False

        # ---- 悬停测试 + 电子围栏状态 ----
        self.fence_manual_enable = False   # True=使用配置半径回复; False=回显地面站值
        self.safe_distance = 3.0           # 安全距离 (m)
        self.hover_manual_enable = False   # True=使用配置参数回复; False=回显地面站值
        self.takeoff_height = 10.0         # 起飞高度 (m)
        self.hover_duration = 60           # 悬停时长 (s)

        # ---- 参数系统：从 CSV 加载 UavParamDict ----
        self._model = serial_to_model(self.serial)  # 从序列号反查机型名
        self.param_dict = UavParamDict(self._model)
        csv_filename = MODEL_TO_CSV.get(self._model, "X1_ParamList.csv")
        csv_path = os.path.join(_PARAM_CSV_BASE, csv_filename)
        if not self.param_dict.load_csv(csv_path):
            logger.warning(
                f"[TEST] 飞机{self.fake_plane.local_ip}:{self.fake_plane.local_port} "
                f"参数 CSV 加载失败: {csv_path}，回退到内置 _DEFAULT_PARAM_TABLE"
            )
        else:
            logger.info(
                f"[TEST] 飞机{self.fake_plane.local_ip}:{self.fake_plane.local_port} "
                f"机型={self._model} 参数表已加载 ({len(self.param_dict.ParamTypes)} 参数)"
            )
        # 参数队列（PARAM_REQUEST_LIST 分批回传用）
        self._param_queue: list[str] = []
        self._param_queue_interval_s = 0.1  # 每批间隔（秒），默认 100ms

        try:
            # TODO: 暂时屏蔽握手逻辑
            # if not self._do_handshake():
            #     raise RuntimeError(
            #         f"[TEST] 飞机{self.fake_plane.local_ip}:{self.fake_plane.local_port}握手失败"
            #     )
            if not self.start():
                raise RuntimeError(
                    f"[TEST] 飞机{self.fake_plane.local_ip}:{self.fake_plane.local_port}后台线程启动失败"
                )
        except Exception:
            # 握手或启动线程失败：清理已分配的 socket / 线程 / 定时器，再向上抛
            self._cleanup()
            raise

    # ------------------------------------------------------------------
    # 资源清理（构造失败 / 正常 stop 共用）
    # ------------------------------------------------------------------
    def _cleanup(self):
        """清理本实例占用的资源：停线程、关 socket、取消 success 衰减定时器。

        可被外部在 __init__ 失败路径调用，也可在 stop() 中复用。
        """
        # 取消 success 衰减定时器
        with self._lock:
            if self._success_timer is not None:
                self._success_timer.cancel()
                self._success_timer = None
        # 停后台线程（仅当其曾被启动且仍存活）
        if self.thread is not None and self.thread.is_alive():
            self.running = False
            self.thread.join(timeout=2)
        # 停飞行推进线程
        self._flight_running = False
        if self._flight_thread is not None and self._flight_thread.is_alive():
            self._flight_thread.join(timeout=2)
        # 关闭底层 socket
        if self.fake_plane is not None:
            try:
                self.fake_plane.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 生命周期 / 参数更新
    # ------------------------------------------------------------------
    def start(self):
        try:
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            print("[TEST] 消息发送线程已启动")
            return True
        except Exception as e:
            logger.error(f"启动消息发送线程失败: {e}")
            return False

    def stop(self):
        """正常停止：通知线程退出并 join；取消 success 衰减定时器；关闭 socket。"""
        self.running = False
        self._flight_running = False
        with self._lock:
            if self._success_timer is not None:
                self._success_timer.cancel()
                self._success_timer = None
        if self.thread is not None:
            self.thread.join(timeout=2)
        if self._flight_thread is not None and self._flight_thread.is_alive():
            self._flight_thread.join(timeout=2)
        try:
            if self.fake_plane is not None:
                self.fake_plane.close()
        except Exception:
            pass
        print("[TEST] 消息发送线程已停止")

    def update_wind_speed(self, wind_speed_x, wind_speed_y):
        """更新风速参数，后续发送使用新参数。

        副作用：将 self.success 清为 False（之前缓存的"已外发"已不再代表当前状态）。
        待新状态被成功外发后，self.success 会被 _judge_send_success 重新置 True
        并保持 _SUCCESS_HOLD_SECONDS 秒。
        """
        with self._lock:
            self.wind_speed_x = wind_speed_x
            self.wind_speed_y = wind_speed_y
            self._reset_success_locked()

    def update_laser(self, laser_config, laser_state):
        """更新激光参数，后续发送使用新参数。

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.laser_config = laser_config
            self.laser_state = laser_state
            self._reset_success_locked()

    def update_nova(self, nova_config, nova_state):
        """更新高亮灯参数，后续发送使用新参数。

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.nova_config = nova_config
            self.nova_state = nova_state
            self._reset_success_locked()

    def update_firework(self, firework_config):
        """更新烟花参数，后续发送使用新参数。

        firework_config: 烟花通道配置，bit0~7 = 8 firework channels (uint16_t)

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.firework_config = firework_config
            self._reset_success_locked()

    def update_lantern(self, lantern_config, lantern_state,
                       peach_lantern_config=0,
                       fish_lantern_config=0,
                       kongming_lantern_config=0):
        """更新折叠灯/蟠桃灯/鱼灯/旧孔明灯参数，后续发送使用新参数。

        lantern_config:      折叠灯配置（对应查询指令 param1=1/param7=14）
        lantern_state:       折叠灯状态，沿用激光状态逻辑 (uint16_t)
        peach_lantern_config:  蟠桃灯配置（默认 0）
        fish_lantern_config:   鱼灯配置（默认 0）
        kongming_lantern_config: 旧孔明灯配置（默认 0）

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.lantern_config = lantern_config
            self.lantern_state = lantern_state
            self.peach_lantern_config = peach_lantern_config
            self.fish_lantern_config = fish_lantern_config
            self.kongming_lantern_config = kongming_lantern_config
            self._reset_success_locked()

    def update_trumpet(self, trumpet_config, trumpet_state, trumpet):
        """更新喇叭参数，后续发送使用新参数。

        trumpet: 1 = 有负载, 其他 = 无负载 (uint8_t)

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.trumpet_config = trumpet_config
            self.trumpet_state = trumpet_state
            self.trumpet = trumpet
            self._reset_success_locked()

    def update_parachute(self, parachute_config, parachute_state, parachute):
        """更新降落伞参数，后续发送使用新参数。

        parachute: 1 = 有负载, 其他 = 无负载 (uint8_t)

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.parachute_config = parachute_config
            self.parachute_state = parachute_state
            self.parachute = parachute
            self._reset_success_locked()

    def update_confetti(self, confetti_config):
        """更新撒花器参数，后续发送使用新参数。

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.confetti_config = confetti_config
            self._reset_success_locked()

    def update_ack(self, fail_count=0, silence_count=0,
                   cmd_result_enable=False, cmd_result_commands=None,
                   cmd_result_values=None):
        """配置所有 command 的 ACK 响应行为。

        支持三种模式（按优先级从高到低）：
        1. 静默（silence_count）：前 N 次不回复，之后回复 result=0。
        2. 特定 command result 覆写（cmd_result_*）：对指定 command 强制返回指定 result。
        3. 失败注入（fail_count）：前 N 次返回 result=4 (FAILED)，之后返回 result=0。

        各 command 独立计数，10s 未收到该 command 则其计数器自动重置为 0。

        Args:
            fail_count: 失败次数（>=0），设为 0 则禁用（始终返回 result=0）
            silence_count: 静默次数（>=0），设为 0 则禁用（始终立即回复）
            cmd_result_enable: 是否启用特定 command 的 result 覆写
            cmd_result_commands: 需要覆写 result 的 command 列表
            cmd_result_values: 对应的 result 值列表。
                - 单元素列表：所有 cmd_result_commands 中的 command 都用此 result
                - 多元素列表：与 cmd_result_commands 一一对应（长度必须相等）
        """
        with self._lock:
            self._ack_fail_count = fail_count
            self._ack_fail_counters.clear()
            self._ack_fail_last_time.clear()
            self._ack_silence_count = silence_count
            self._ack_silence_counters.clear()
            self._ack_silence_last_time.clear()
            self._ack_cmd_result_enabled = cmd_result_enable
            self._ack_cmd_result_map.clear()
            if cmd_result_enable and cmd_result_commands:
                if cmd_result_values and len(cmd_result_values) == 1:
                    # 单值广播：所有 command 用同一个 result
                    value = cmd_result_values[0]
                    for cmd in cmd_result_commands:
                        self._ack_cmd_result_map[int(cmd)] = int(value)
                elif cmd_result_values:
                    # 一一对应
                    for cmd, val in zip(cmd_result_commands, cmd_result_values):
                        self._ack_cmd_result_map[int(cmd)] = int(val)

    # ------------------------------------------------------------------
    # param_hash 更新（source: 1=手动设置, 0=自动计算）
    # ------------------------------------------------------------------
    def update_param_hash(self, value=None, source=0):
        """更新 param_hash。

        Args:
            value: 手动设置时的 hash 值（source=1 时必须提供）
            source: 1=手动设置（直接覆盖 param_dict.ParamHash），
                    0=自动计算（从 param_dict 重新 refresh）
        """
        with self._lock:
            self._param_hash_source = source
            if source == 1:
                # 手动设置：直接覆盖
                if self.param_dict is not None and value is not None:
                    self.param_dict.ParamHash = int(value)
            elif source == 0:
                # 自动计算：从 param_dict 刷新
                if self.param_dict is not None:
                    self.param_dict.refresh_param_hash()
            self._reset_success_locked()

    # ------------------------------------------------------------------
    # 版本信息统一更新（替代分散的 update_xxx_version）
    # ------------------------------------------------------------------
    def update_version(self, **kwargs):
        """统一更新版本信息，后续发送 id=8 消息时使用新值。

        支持的关键字：flight_controller_version / companion_version /
        battery_version / gps_version / servo_ver / tele_version /
        bms_version / rid_version / gimbal_version / nova_light_version

        flight_controller_version (FC_Version) : bytes (8B)
        companion_version                     : bytes (8B)
        battery_version                       : bytes (8B)
        gps_version                           : bytes (8B)
        servo_ver                             : int
        tele_version                          : bytes (4B)
        bms_version                           : bytes (4B)
        rid_version                           : bytes (8B)
        gimbal_version                        : bytes (4B)
        nova_light_version                    : bytes (4B)

        示例:
            sender.update_version(
                nova_light_version=b"1000",
                flight_controller_version=b"n3.k.200",
                servo_ver=1,
            )

        副作用：将 self.success 清为 False。
        """
        _VALID_VERSION_KEYS = {
            'flight_controller_version', 'companion_version', 'battery_version',
            'gps_version', 'servo_ver', 'tele_version', 'bms_version',
            'rid_version', 'gimbal_version', 'nova_light_version',
        }
        with self._lock:
            for key, value in kwargs.items():
                if key in _VALID_VERSION_KEYS:
                    setattr(self, key, value)
            self._reset_success_locked()

    def update_sensor_health(self, **kwargs):
        """更新 sensor_health 各传感器状态，后续发送使用新参数。

        支持的关键字：imu / baro / compass / gps / battery / bno_reset /
        acc_calibrated / compass_calibrated / color_calibrated /
        magnetic_calibrated / scram / esc / parachute / tele / bms / module

        ┌─────┬─────────────────────┬──────────────────────┐
        │ Bit │        含义         │       取值逻辑       │
        ├─────┼─────────────────────┼──────────────────────┤
        │ 0   │ IMU                 │ 0=正常，1=异常       │
        │ 1   │ Baro（气压计）      │ 0=正常，1=异常       │
        │ 2   │ Compass / BNO       │ 0=正常，1=异常       │
        │ 3   │ GPS / UWB           │ 0=正常，1=异常       │
        │ 4   │ Battery             │ 0=正常，1=异常       │
        │ 5   │ BnoReset            │ 0=正常，1=异常       │
        │ 6   │ Acc calibrated      │ 0=正常，1=异常       │
        │ 7   │ Compass calibrated  │ 0=正常，1=异常       │
        │ 8   │ Color calibrated    │ 0=正常，1=异常       │
        │ 9   │ Magnetic calibrated │ 0=正常，1=异常       │
        │ 10  │ Scram               │ 0=正常，1=异常       │
        │ 11  │ ESC                 │ 0=正常，1=异常       │
        │ 12  │ Parachute           │ 取反：1=正常，0=异常 │
        │ 13  │ Tele                │ 取反：1=正常，0=异常 │
        │ 14  │ BMS                 │ 取反：1=正常，0=异常 │
        │ 15  │ Module              │ 取反：1=正常，0=异常 │
        └─────┴─────────────────────┴──────────────────────┘

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            for name, state in kwargs.items():
                attr = f'_sensor_{name}'
                if hasattr(self, attr):
                    setattr(self, attr, int(state))
            self._reset_success_locked()

    def _build_sensor_health(self):
        """根据各传感器状态构建 sensor_health 位掩码（16 bits）。

        bits 0-11: 0=正常, 1=异常（直通）
        bits 12-15: 取反：1=正常, 0=异常（内部存储 0=正常 → 寄存器写 1）
        """
        value = 0
        for sensor_name, bit in self._SENSOR_HEALTH_BITS.items():
            state = getattr(self, f'_sensor_{sensor_name}', 0)
            if bit in self._SENSOR_HEALTH_INVERTED_BITS:
                state = 1 - state  # 取反
            if state:
                value |= (1 << bit)
        return value

    def update_position(self, cur_lat, cur_lon, tar_lat, tar_lon,
                       cur_alt=0, tar_alt=0, fix_type=6,
                       rtk_radio_850m=0, rtk_radio_2g4=0):
        """更新当前位置、目标位置和 GPS 定位类型，后续发送使用新参数。

        cur_lat: 当前纬度 (MAVLink I=uint32_t, 1e7 度)
        cur_lon: 当前经度 (MAVLink I=uint32_t, 1e7 度)
        tar_lat: 目标纬度 (MAVLink I=uint32_t, 1e7 度)
        tar_lon: 目标经度 (MAVLink I=uint32_t, 1e7 度)
        cur_alt: 当前高度 (MAVLink I=uint32_t, mm)
        tar_alt: 目标高度 (MAVLink I=uint32_t, mm)
        fix_type: GPS 定位类型 (MAVLink B=uint8_t, 0-1: no fix, 2: 2D, 3: 3D,
                  4: DGPS, 5: RTK float, 6: RTK fixed)
        rtk_radio_850m: 850MHz RTK 电台状态 (MAVLink B=uint8_t)
        rtk_radio_2g4: 2.4GHz RTK 电台状态 (MAVLink B=uint8_t)

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.cur_lat = cur_lat
            self.cur_lon = cur_lon
            self.tar_lat = tar_lat
            self.tar_lon = tar_lon
            self.cur_alt = cur_alt
            self.tar_alt = tar_alt
            self.fix_type = fix_type
            self.rtk_radio_850m = rtk_radio_850m
            self.rtk_radio_2g4 = rtk_radio_2g4
            self._reset_success_locked()

    def update_drama_state(self, drama_state, mission_request_ack_result=-1):
        """更新剧本状态 (drama_state)，后续发送 id=5 消息时使用新值。

        drama_state: 剧本状态 (MAVLink I=int32_t, 取值范围由上层业务定义)
        mission_request_ack_result: 0x2A MISSION_REQUEST_ACK result 覆写值
                  (-1=AUTO 按 loaded_missions 自动计算 0/1；>=0 强制覆写)

        副作用：将 self.success 清为 False（同 update_position）。
        """
        with self._lock:
            self.drama_state = drama_state
            self.mission_request_ack_result = mission_request_ack_result
            self._reset_success_locked()

    def update_bat(self, **kwargs):
        """统一更新电池/电压相关字段，后续发送 id=5/id=8 消息时使用新值。

        支持的关键字：voltage_battery / voltage_battery_percent /
        voltage_battery_diff / voltage_battery_history_diff /
        bat_serial_prefix / bat_serial_suffix / bat_serial_need_reset /
        charge_state / battery_time / temp_batt / battery_capability /
        battery_used_times / voltage_battery_cell1 / voltage_battery_cell2 /
        voltage_battery_cell3 / voltage_battery_cell4 / voltage_battery_cell5 /
        voltage_battery_cell6 / voltage_rid_bat /
        safe_fly_radius / remain_fly_time / go_home_need_time /
        land_need_time / go_home_need_capacity / land_need_capacity /
        battery_total_capaticy / battery_remain_capaticy /
        battry_capacity_percentage

        voltage_battery              : int   — 电池电压 (mV)，默认 34000
        voltage_battery_percent      : int   — 电池电量百分比，默认 95
        voltage_battery_diff         : int   — 电池电压差 (mV)，默认 0
        voltage_battery_history_diff : int   — 历史电池电压差 (mV)，默认 0
        bat_serial_prefix            : bytes — 电池序列号前缀，默认 b'V3F230324-'
        bat_serial_suffix            : bytes — 电池序列号后缀，默认 b'3355'
        bat_serial_need_reset        : int   — 电池序列号需重置标志，默认 0
        charge_state                 : int   — 充电状态，默认 0
        battery_time                 : int   — 电池使用时间，默认 78
        temp_batt                    : int   — 电池温度，默认 0
        battery_capability           : int   — 电池容量，默认 20
        battery_used_times           : int   — 电池使用次数，默认 12
        voltage_battery_cell1~6      : int   — 电芯1~6电压 (mV)，默认 3500
        voltage_rid_bat              : int   — RID 电池电压 (mV)，默认 0
        safe_fly_radius              : float — 0x3B 安全飞行半径 (m)，默认 500.0
        remain_fly_time              : int   — 0x3B 剩余飞行时间 (s)，默认 1200
        go_home_need_time            : int   — 0x3B 返航所需时间 (s)，默认 60
        land_need_time               : int   — 0x3B 降落所需时间 (s)，默认 30
        go_home_need_capacity        : int   — 0x3B 返航所需电量 (mAh)，默认 500
        land_need_capacity           : int   — 0x3B 降落所需电量 (mAh)，默认 300
        battery_total_capaticy       : int   — 0x3B 电池总容量 (mAh，协议原文拼写)，默认 22000
        battery_remain_capaticy      : int   — 0x3B 电池剩余容量 (mAh，协议原文拼写)，默认 20000
        battry_capacity_percentage   : int   — 0x3B 电池容量百分比 (协议原文拼写)，默认 90

        副作用：将 self.success 清为 False（同 update_wind_speed）。

        示例:
            sender.update_bat(voltage_battery=35000, voltage_battery_percent=80,
                              battery_time=100)
        """
        _VALID_BAT_KEYS = {
            'voltage_battery', 'voltage_battery_percent',
            'voltage_battery_diff', 'voltage_battery_history_diff',
            'bat_serial_prefix', 'bat_serial_suffix', 'bat_serial_need_reset',
            'charge_state', 'battery_time', 'temp_batt', 'battery_capability',
            'battery_used_times',
            'voltage_battery_cell1', 'voltage_battery_cell2',
            'voltage_battery_cell3', 'voltage_battery_cell4',
            'voltage_battery_cell5', 'voltage_battery_cell6',
            'voltage_rid_bat',
            # -- 0x3B REMAINING_CAPACITY(59) 字段 --
            'safe_fly_radius', 'remain_fly_time', 'go_home_need_time',
            'land_need_time', 'go_home_need_capacity', 'land_need_capacity',
            'battery_total_capaticy', 'battery_remain_capaticy',
            'battry_capacity_percentage',
        }
        with self._lock:
            for key, value in kwargs.items():
                if key in _VALID_BAT_KEYS:
                    setattr(self, key, value)
            self._reset_success_locked()

    def update_waypoint_parse(self, enable: bool):
        """设置航点解析开关（True=bin 保存后自动生成 3D 航点图）。

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.enable_waypoint_parse = bool(enable)
            self._reset_success_locked()

    def update_waypoint_compare(self, enable: bool):
        """设置航点对比开关（True=接收 bin 后自动与上次航点对比）。

        注意：当前版本中此开关仅由外部 GUI 直接调用 visualize_drama_compare 触发，
        不再作为 _save_drama_bin 内的自动联动行为保留。

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.enable_waypoint_compare = bool(enable)
            self._reset_success_locked()

    def update_bin_save(self, enable: bool, save_dir: str | None = None):
        """设置 bin 文件保存开关及保存路径。

        Args:
            enable: True=自动保存 bin 文件到磁盘
            save_dir: 保存目录路径，为 None 时保持现有路径不变

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.enable_bin_save = bool(enable)
            if save_dir is not None:
                self.bin_save_dir = str(save_dir)
            self._reset_success_locked()

    def update_hover_fence(self, manual_enable, safe_distance=3.0):
        """设置悬停测试电子围栏参数。

        manual_enable=True:  使用配置的 fence_radius 回复地面站 PARAM_SET
                             (radius = safe_distance/2 + 1.0)
        manual_enable=False: 回显地面站发送的原值（默认行为）

        safe_distance: 安全距离 (m)，默认 3.0m

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.fence_manual_enable = manual_enable
            self.safe_distance = safe_distance
            self._reset_success_locked()

    def update_hover_test(self, manual_enable, takeoff_height=10.0, hover_duration=60):
        """设置悬停测试参数。

        manual_enable=True:  使用配置的 takeoff_height/hover_duration 回复
        manual_enable=False: 回显地面站发送的原值（默认行为）

        takeoff_height: 起飞高度 (m)，默认 10.0m
        hover_duration: 悬停时长 (s)，默认 60s

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.hover_manual_enable = manual_enable
            self.takeoff_height = takeoff_height
            self.hover_duration = hover_duration
            self._reset_success_locked()

    def update_failsafe(self, enable=False, f_crash=False, f_radio=False,
                        f_battery=False, f_fence_alt=False, f_fence_circle=False,
                        f_waypoint=False, f_too_far=False, f_static_dist=False,
                        f_vibrate=False, f_drama_fail=False, f_parachute=False,
                        f_sensor_fail=False, f_fence_2=False, f_ekf_stab=False,
                        f_ekf_horz=False, f_ekf_vert=False):
        """配置 failsafe(0x06) 故障位掩码并控制其随 5s 状态周期外发。

        enable: True=随 5s 状态周期外发 0x06；False=不外发（默认）

        16 个故障位参数（1/True=置位；未配置的故障位一律置 0，全量覆盖语义）：

        f_crash        : bit15 — 坠机 (F_CRASH)
        f_radio        : bit14 — 电台失联 (F_RADIO)
        f_battery      : bit13 — 低电 (F_BATTERY)
        f_fence_alt    : bit12 — 高度围栏 (F_FENCE_ALT)
        f_fence_circle : bit11 — 水平围栏 (F_FENCE_CIRCLE)
        f_waypoint     : bit10 — 航点失败 (F_WAYPOINT)
        f_too_far      : bit9  — 距离过远 (F_TOO_FAR)
        f_static_dist  : bit8  — 静态距离 (F_STATIC_DIST)
        f_vibrate      : bit7  — 震动 (F_VIBRATE)
        f_drama_fail   : bit6  — 剧本失败 (F_DRAMA_FAIL)
        f_parachute    : bit5  — 降落伞 (F_PARACHUTE)
        f_sensor_fail  : bit4  — 传感器故障 (F_SENSOR_FAIL)
        f_fence_2      : bit3  — 二级围栏 (F_FENCE_2)
        f_ekf_stab     : bit2  — EKF 定高 (F_EKF_STAB)
        f_ekf_horz     : bit1  — EKF 水平 (F_EKF_HORZ)
        f_ekf_vert     : bit0  — EKF 垂直 (F_EKF_VERT)

        副作用：将 self.success 清为 False（同 update_wind_speed）。
        """
        with self._lock:
            self.enable_failsafe = bool(enable)
            values = {
                'f_crash': f_crash, 'f_radio': f_radio, 'f_battery': f_battery,
                'f_fence_alt': f_fence_alt, 'f_fence_circle': f_fence_circle,
                'f_waypoint': f_waypoint, 'f_too_far': f_too_far,
                'f_static_dist': f_static_dist, 'f_vibrate': f_vibrate,
                'f_drama_fail': f_drama_fail, 'f_parachute': f_parachute,
                'f_sensor_fail': f_sensor_fail, 'f_fence_2': f_fence_2,
                'f_ekf_stab': f_ekf_stab, 'f_ekf_horz': f_ekf_horz,
                'f_ekf_vert': f_ekf_vert,
            }
            self.failsafe_flags = {name: 1 if values[name] else 0
                                   for name in self._FAILSAFE_BITS}
            self._reset_success_locked()

    # ------------------------------------------------------------------
    # self.success 衰减状态机（持锁 / 持锁的 Timer 回调）
    # ------------------------------------------------------------------
    def _reset_success_locked(self):
        """持锁调用：将 self.success 清为 False，并取消挂起的 0.5s 衰减定时器。

        在 update_*() 状态被改写、或者一次发送失败时调用。
        """
        self.success = False
        if self._success_timer is not None:
            self._success_timer.cancel()
            self._success_timer = None

    def _mark_success_locked(self):
        """持锁调用：标记一次发送成功。

        行为：
            - self.success 立即置 True
            - 启动一个 _SUCCESS_HOLD_SECONDS 秒的 Timer，到期后自动清回 False
            - 若在窗口内又收到新的成功标记，会取消旧 Timer 并启动新 Timer
              （始终以"最后一次成功外发"为基准，0.5s 内无新成功则回落）
        """
        self.success = True
        if self._success_timer is not None:
            self._success_timer.cancel()
        self._success_timer = threading.Timer(
            self._SUCCESS_HOLD_SECONDS, self._on_success_expire
        )
        self._success_timer.daemon = True
        self._success_timer.start()

    def _on_success_expire(self):
        """Timer 回调：0.5s 衰减到期后清 success。"""
        with self._lock:
            self.success = False
            self._success_timer = None

    # ------------------------------------------------------------------
    # 协议握手
    # ------------------------------------------------------------------
    def _do_handshake(self):
        """执行 MAVLink 握手：心跳 → 收 id=3 → 发 id=2 → 收 id=1。"""

        time.sleep(self._HANDSHAKE_INITIAL_DELAY)
        msg = self._build_id_000()
        self._dispatch_send(msg, "000")

        received, _ = self._wait_for_msg_id(3, label="id=3")
        if received is None:
            logger.error("[TEST] 握手失败: 未收到地面站 id=3")
            return False

        msg = self._build_id_002(serial=self.serial,code=self.code)
        self._dispatch_send(msg, "002")
        time.sleep(self._POST_IDENTITY_DELAY)

        received, _ = self._wait_for_msg_id(1, label="id=1 extend=1")
        if received is None:
            logger.error("[TEST] 握手失败: 未收到地面站 id=1")
            return False

        return True

    # ------------------------------------------------------------------
    # 特定ID接收消息等待
    # ------------------------------------------------------------------
    def _wait_for_msg_id(self, expected_id, label, timeout=None):
        """在 timeout 内等待指定 msg_id。返回 (msg, addr)，超时返回 (None, None)。"""
        if timeout is None:
            timeout = self._HANDSHAKE_TIMEOUT
        print(f"[TEST] 等待 {label} (timeout={timeout}s)")
        start = time.time()
        received = None
        while time.time() - start < timeout:
            received, addr = self.fake_plane.receive()
            if received is not None:
                print(f"[TEST] 收到 msg_id={received.msg_id} from={addr}")
                if received.msg_id == expected_id:
                    return received, addr
                if received.msg_id == self._MSG_ID_HEARTBEAT:
                    continue
            # time.sleep(0.00)
        return None, None

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def _run(self):
        """主循环：接收 → 查 _RESPONSE_RULES 调度响应；空闲时主动发送心跳。

        识别完成后额外以 1Hz 主动上报剩余续航(59) 与表演进度(packed_state 5)。
        """
        print(f"[TEST] _run() 主循环已启动 (code={self.code})")
        # 启动后立即发送首次心跳
        msg = self._build_id_000()
        self._dispatch_send(msg, "000(initial)")
        last_heartbeat = time.time()
        last_report = time.time()
        while self.running:
            received, _ = self.fake_plane.receive()
            if received is not None:
                self._dispatch_request(received)
            elif not self._identified:
                # 身份识别未完成，超时无消息时按 1s 间隔主动发送心跳
                now = time.time()
                if now - last_heartbeat >= 5.0:
                    msg = self._build_id_000()
                    self._dispatch_send(msg, "000(periodic)")
                    last_heartbeat = now

            # 识别完成后 5s 周期主动上报剩余续航 / 表演进度
            # NOTE: 消息构建必须持锁，避免与 _advance_flight() 产生数据竞态；
            #       但 _dispatch_send → _judge_send_success 内部也会获取
            #       self._lock（不可重入），故先构建后发送，不在锁内调用发送。
            if self._identified:
                now = time.time()
                if now - last_report >= 5.0:
                    with self._lock:
                        msg_059 = self._build_id_059()
                        msg_005 = self._build_id_005(
                            wind_speed_x=self.wind_speed_x,
                            wind_speed_y=self.wind_speed_y,
                            seq=self.seq)
                        # failsafe(0x06)：enable_failsafe=True 时随状态周期外发
                        msg_006 = self._build_id_006() if self.enable_failsafe else None
                    self._dispatch_send(msg_059,
                                        "id=59(0x3B) REMAINING_CAPACITY")
                    self._dispatch_send(msg_005,
                                        "id=5(0x05) PACKED_STATE(periodic)")
                    if msg_006 is not None:
                        self._dispatch_send(msg_006,
                                            "id=6(0x06) FAILSAFE(periodic)")
                    last_report = now

    def _build_responses(self, received):
        """构建响应消息列表（不发送），供 _dispatch_request 和外部复用。

        Returns:
            list of (MAVLink_message, label) — 可能为空列表
        """
        batch = self._RESPONSE_RULES.get(received.msg_id)
        if batch is None:
            return []
        pending = []
        with self._lock:
            # 身份识别未完成前，仅允许心跳(msg=0)和身份(msg=3)，屏蔽其余所有响应
            if (received.msg_id != self._MSG_ID_HEARTBEAT
                    and received.msg_id != self._MSG_ID_GET_IDENTIFY_INFO
                    and not self._identified):
                return []
            for rule in batch['rules']:
                if rule.get('when') and not rule['when'](received):
                    continue
                try:
                    kwargs = {kw: getattr(self, attr) if isinstance(attr, str) else attr
                              for kw, attr in rule.get('state', {}).items()}
                    msg = getattr(self, rule['build'])(**kwargs)
                except Exception as e:
                    logger.error(f"[TEST] {rule['label']} 构建失败: {e}")
                    continue
                pending.append((msg, rule['label']))
            # msg 003 身份识别完成后，解锁后续响应
            if received.msg_id == self._MSG_ID_GET_IDENTIFY_INFO:
                self._identified = True
        return pending

    def _dispatch_request(self, received):
        """处理一个收到的请求。

        调度顺序：
          1. 有状态 / 依赖请求内容的交互（_STATE_RULES）：对时/参数/剧本/校验/
             切模式/开始表演/命令(COMMAND_LONG)。
          2. 无状态查表回显（_RESPONSE_RULES）：心跳/心跳DMD/身份。
        """
        mid = received.msg_id
        # 身份识别门闩：未识别前仅放行心跳/身份
        gated = (not self._identified and mid not in self._ALLOW_BEFORE_IDENTIFY)

        # 1) 有状态协议交互
        handler_name = self._STATE_RULES.get(mid)
        if handler_name is not None and not gated:
            self.log_manager.logger.info(
                f"[TEST] 飞机{self.fake_plane.local_ip}:{self.fake_plane.local_port} "
                f"收到 msg_id={mid} 消息(有状态)"
            )
            pending = getattr(self, handler_name)(received) or []
            for msg, label in pending:
                self._dispatch_send(msg, label)
            return

        # 2) 无状态查表回显
        batch = self._RESPONSE_RULES.get(mid)
        if batch is None:
            return
        self.log_manager.logger.info(
            f"[TEST] 飞机{self.fake_plane.local_ip}:{self.fake_plane.local_port} "
            f"收到 msg_id={mid} 消息"
        )

        pending = self._build_responses(received)

        for msg, label in pending:
            self._dispatch_send(msg, label)

        delay = batch.get('delay')
        if delay is not None:
            time.sleep(delay)

    def _dispatch_send(self, msg, label):
        """统一的发送 + 结果判断入口。msg 为 None 时跳过。"""
        if msg is None:
            return False
        ok = self.fake_plane.send(msg, addr=self.addr)
        self._judge_send_success(ok, label)
        return ok

    def _judge_send_success(self, send_result, msg_id):
        """观察一次发送结果，更新 self.success 状态机：
            - 成功：self.success = True，并在 _SUCCESS_HOLD_SECONDS 后自动回落为 False
            - 失败：self.success 立即清为 False（按"当前状态确实被外发过"的语义）
        """
        if not send_result:
            with self._lock:
                self._reset_success_locked()
            self.log_manager.logger.info(
                f"[TEST] 飞机{self.fake_plane.local_ip}:{self.fake_plane.local_port} {msg_id}消息模拟失败"
            )
        else:
            with self._lock:
                self._mark_success_locked()
            self.log_manager.logger.info(
                f"[TEST] 飞机{self.fake_plane.local_ip}:{self.fake_plane.local_port} {msg_id}消息模拟成功"
            )

    # ------------------------------------------------------------------
    # 开始表演流程：时钟 / 有状态交互处理器
    # ------------------------------------------------------------------
    def _now_ms(self):
        """当前时刻（相对 1970 UTC 毫秒）。测试可通过 _now_ms_override 注入。"""
        if self._now_ms_override is not None:
            return self._now_ms_override
        return int(time.time() * 1000)

    def _handle_set_mode(self, received):
        """SET_MODE(11)：写入 self.mode 并回 COMMAND_ACK(command=11)。

        飞行中切 LD/R 触发降落/返航的逻辑在 Phase 3 的 _on_mode_changed 内补充。
        """
        custom = received.fields.get('custom_mode', 0)
        with self._lock:
            self.mode = custom
        self._on_mode_changed(custom)
        return [(self._build_id_077_cmd(command=self._MSG_ID_SET_MODE),
                 'id=77(0x4D) SET_MODE_ACK')]

    def _on_mode_changed(self, custom_mode):
        """模式变化钩子：飞行中切 LD/R → 触发降落/返航。"""
        if custom_mode not in (self._UAV_MODE_LD, self._UAV_MODE_R):
            return
        with self._lock:
            if self.fly_state in (self._FLY_GUIDE_TAKEOFF, self._FLY_GUIDE_PLAY):
                self.final_mode = custom_mode
                self.fly_state = (self._FLY_RETURN if custom_mode == self._UAV_MODE_R
                                  else self._FLY_LAND)
                self.play_state = self._PLAY_LANDING
                self._phase_start_ms = self._now_ms()

    def _handle_calib_time(self, received):
        """CALIB_TIME(46)：记录对时基准 epoch_now_ms，回 TIME_ORIGIN(47)。

        time = 当前 UTC 相对 1970-01-01 的毫秒数，是后续 takeoff/play 绝对时刻的基准。
        """
        now_ms = self._now_ms()
        with self._lock:
            self.epoch_now_ms = now_ms
        return [(self._build_id_047(now_ms), 'id=47 TIME_ORIGIN')]

    def _handle_param_request_list(self, received):
        """PARAM_REQUEST_LIST(21)：对齐 C# HandleParam_Request_List（receive.cs:486-502）。

        1. 防重入：paramQueue 非空则忽略
        2. 全部 ParamTypes.Keys 入队，故意丢弃队首 5 个（模拟丢包）
        3. 分批（每批 ≤8）回 PARAM_VALUE(22)，末尾补 ACK(24)
        4. param_total = ParamTypes.Count（全表规模）
        """
        if self._param_queue:
            return []  # 防重入

        if self.param_dict is not None and self.param_dict.ParamTypes:
            # 使用 CSV 参数表
            keys = list(self.param_dict.ParamTypes.keys())
            total = len(keys)
            # 模拟丢包：丢弃队首 5 个参数
            keys = keys[5:]
            # 计算回传间隔：1000 / SR0_PARAM（秒）
            sr0 = self.param_dict.ParamsMustBe.get("SR0_PARAM", 10)
            self._param_queue_interval_s = max(0.05, 1.0 / max(1, int(sr0)))
        else:
            # 回退到内置参数表
            params = self._DEFAULT_PARAM_TABLE
            total = len(params)
            keys = [p[0] for p in params]
            self._param_queue_interval_s = 0.1

        # 全量入队（不含已丢弃的 5 个）
        self._param_queue = list(keys)

        out = []
        start = 0
        while self._param_queue:
            batch_names = []
            for _ in range(min(8, len(self._param_queue))):
                batch_names.append(self._param_queue.pop(0))
            batch = []
            for i, name in enumerate(batch_names):
                val = self._get_param_value(name)
                batch.append((name, val, 9))  # type=9 (MAV_PARAM_TYPE_INT32)
            out.append((self._build_id_022(batch, start, total),
                        f'id=22(0x16) PARAM_VALUE[{start}:{start + len(batch)}]'))
            start += len(batch)

        # 收尾 ACK
        out.append((self._build_id_024(0), 'id=24(0x18) PARAM_REQUEST_LIST_ACK'))
        return out

    # ------------------------------------------------------------------
    # 参数取值（对齐 C# GetParamValue，FakeUavParser.cs:214-227）
    # ------------------------------------------------------------------
    def _get_param_value(self, name: str) -> float:
        """返回某个参数的上报值。

        MustBe → 预期值；MustNotBe → 禁止值+0.1；其他 → 先查 _params_set 缓存，否则 0。
        """
        if self.param_dict is not None:
            return self.param_dict.get_param_value(name)
        # 回退：查内置 _DEFAULT_PARAM_TABLE
        for n, v, _ in self._DEFAULT_PARAM_TABLE:
            if n == name:
                return v
        # 查 SET_PARAM 写入过的参数
        if name in self._params_set:
            return self._params_set[name]
        return 0.0

    def _handle_param_request_read(self, received):
        """PARAM_REQUEST_READ(20)：对齐 C# HandleGetParam（receive.cs:437-456）。

        遍历 param_count 个 16B 槽位，每个在 ParamTypes 中存在的参数加入应答；
        未知参数静默跳过。param_total = 请求的 param_count。
        """
        param_id_b = received.fields.get('param_id', b'') or b''
        if isinstance(param_id_b, str):
            param_id_b = param_id_b.encode('latin-1')
        param_count = received.fields.get('param_count', 1)

        batch = []
        for i in range(param_count):
            slot_start = i * 16
            if len(param_id_b) < slot_start + 16:
                break
            slot = param_id_b[slot_start:slot_start + 16]
            name = slot.split(b'\x00', 1)[0].decode('utf-8', 'ignore')
            if not name:
                continue
            # 对齐 C#：仅当 name 在 ParamTypes 中存在时才加入应答
            if self.param_dict is not None and name in self.param_dict.ParamTypes:
                val = self._get_param_value(name)
                if self.fence_manual_enable and name == "FS_FENCE_RDS":
                    val = float(self.safe_distance / 2.0 + 1.0)
                batch.append((name, val, 0))  # param_type=0 对齐 C# CreateEmptyParam
            elif name in dict(self._DEFAULT_PARAM_TABLE):
                val = self._get_param_value(name)
                if self.fence_manual_enable and name == "FS_FENCE_RDS":
                    val = float(self.safe_distance / 2.0 + 1.0)
                batch.append((name, val, 0))

        if not batch:
            return []

        return [(self._build_id_022(batch, 0, param_count),
                 f'id=22(0x16) PARAM_VALUE(get) {[n for n,_,_ in batch]}')]

    def _handle_param_set(self, received):
        """PARAM_SET(23)：对齐 C# HandleSetParam（receive.cs:458-484）。

        1. 遍历 param_count 个 16B 槽位，逐个写入 + 回显
        2. 写入 ParamsMustBe / ParamsMustNotBe（两者都不在则仅回显不写）
        3. RefreshParamHash
        4. 回显走 GetParamValue（对齐 C#：写后取值，MustNotBe 会 +0.1）
        5. param_total 不赋值（对齐 C# CreateEmptyParam 默认 0）
        """
        fmt = '<8fHBB128s'
        size = struct.calcsize(fmt)
        payload = received.payload or b''
        if len(payload) < size:
            return []

        vals = struct.unpack(fmt, payload[:size])
        raw_values = vals[0:8]     # float[8]
        param_count = vals[8]       # UInt16
        param_id_b = vals[11]       # byte[128]

        changed = False
        batch = []
        for i in range(min(param_count, 8)):
            slot_start = i * 16
            if len(param_id_b) < slot_start + 16:
                break
            slot = param_id_b[slot_start:slot_start + 16]
            name = slot.split(b'\x00', 1)[0].decode('utf-8', 'ignore')
            if not name:
                continue

            with self._lock:
                self._params_set[name] = raw_values[i]
                if self.param_dict is not None:
                    if self.param_dict.set_param(name, raw_values[i]):
                        changed = True

            # 对齐 C#：回显走 GetParamValue（MustNotBe 会 +0.1）
            echo_val = self._get_param_value(name)
            # 悬停测试围栏：若 manual_enable=True 且参数为 FS_FENCE_RDS，使用配置半径
            if self.fence_manual_enable and name == "FS_FENCE_RDS":
                echo_val = float(self.safe_distance / 2.0 + 1.0)
            batch.append((name, echo_val, 0))  # param_type=0 对齐 C# CreateEmptyParam

        if changed and self.param_dict is not None and self._param_hash_source != 1:
            self.param_dict.refresh_param_hash()

        if not batch:
            return []

        return [(self._build_id_022(batch, 0, 0),  # param_total=0 对齐 C#
                 f'id=22(0x16) PARAM_VALUE(set) {[(n,v) for n,v,_ in batch]}')]

    def _handle_light_data(self, received):
        """LIGHT_DATA(55)：起降灯光剧本，回 COMMAND_ACK(77, result=0)。"""
        return [(self._build_id_077_cmd(command=self._MSG_ID_LIGHT_DATA, result=0),
                 'id=77(0x4D) LIGHT_DATA ACK')]

    # ---- 剧本文件传输 NET_FILE_COMMAND(63) ---------------------------
    @staticmethod
    def _parse_mission_id(name):
        """从剧本文件名解析 mission_id：drama_{id}.dat / drama_merge_{id}.dat。

        drama_tk_* / drama_ld_*（起降灯光）不含 mission_id，返回 None。
        """
        m = re.search(r'drama_(?:merge_)?(\d+)', name)
        return int(m.group(1)) if m else None

    def _handle_net_file_command(self, received):
        """NET_FILE_COMMAND(63)：按 OPEN/WRITE/CLOSE 分片回 ACK，CLOSE 时登记 mission_id。

        与地面站推送端 net_file_write_file() 的 ACK 结构严格对齐。
        """
        cmd = received.fields.get('net_file_cmd', -1)
        data = received.fields.get('data', b'') or b''
        if isinstance(data, str):
            data = data.encode('latin-1')
        if cmd == self._NET_FILE_OPEN:
            return self._net_file_open(data)
        if cmd == self._NET_FILE_WRITE:
            return self._net_file_write(data)
        if cmd == self._NET_FILE_CLOSE:
            return self._net_file_close(data)
        if cmd == self._NET_FILE_VERIFY:
            return self._net_file_verify(data)
        return []

    def _net_file_open(self, data):
        """OPEN：解析文件名/大小，分配 bytearray 缓冲区，返回 fid。

        支持并发多文件传输：每个文件分配独立 fid 和缓冲区。
        """
        # OPEN 请求数据: <hI64s = op_mode(2) + file_length(4) + filename(64)
        fmt = '<hI64s'
        op_mode, f_length, fname_b = struct.unpack(fmt, data[:struct.calcsize(fmt)])
        fname = fname_b.split(b'\x00', 1)[0].decode('utf-8', 'ignore')
        mission_id = self._parse_mission_id(fname)
        with self._lock:
            fid = self._next_fid
            self._next_fid += 1
            self._net_files[fid] = {
                'fid': fid,
                'name': fname,
                'length': f_length,
                'mission_id': mission_id,
                'buffer': bytearray(f_length) if f_length > 0 else bytearray(),
            }
        # OPEN ACK: <hiIh64s = ack_cmd + fid(>=0) + file_length + op_mode + filename
        ack = struct.pack('<hiIh64s', self._NET_FILE_OPEN, fid, f_length,
                          op_mode, fname_b[:64])
        return [(self._build_id_063_ack(ack),
                 f'id=63 NET_FILE ACK OPEN fid={fid} {fname} len={f_length}')]

    def _net_file_write(self, data):
        """WRITE：将 payload 拷贝到对应 fid 的缓冲区指定位置。

        支持并发分片写入：每个分片携带独立的 wr_pos，写入 bytearray 对应偏移量。
        """
        # WRITE 请求数据: <HiI240s = send_len(2) + fid(4) + wr_pos(4) + payload(240)
        fmt = '<HiI240s'
        send_len, fid, wr_pos, payload = struct.unpack(fmt, data[:struct.calcsize(fmt)])
        write_return = send_len  # 默认成功
        with self._lock:
            transfer = self._net_files.get(fid)
            if transfer is None:
                write_return = -1  # fid 不存在
            else:
                buf = transfer['buffer']
                actual = min(send_len, len(payload), len(buf) - wr_pos)
                if actual > 0:
                    buf[wr_pos:wr_pos + actual] = payload[:actual]
                if actual != send_len:
                    write_return = actual  # 部分写入（超出缓冲区边界）
        # WRITE ACK: <hiiI = ack_cmd + write_return + fid + wr_pos
        ack = struct.pack('<hiiI', self._NET_FILE_WRITE, write_return, fid, wr_pos)
        return [(self._build_id_063_ack(ack),
                 f'id=63 NET_FILE ACK WRITE fid={fid} pos={wr_pos} len={send_len}')]

    def _net_file_close(self, data):
        """CLOSE：缓冲数据保存 .bin + 移入 _file_data_cache 供 VERIFY 使用。

        对齐 C# OnClose：不删除缓冲区，而是缓存到 _fileDataCache[fileName]，
        等待后续 VERIFY 校验 MD5，MISSION_REQUEST_VERIFY 时最终清理。
        """
        # CLOSE 请求数据: <Hi = 保留(2) + fid(4)
        fmt = '<Hi'
        _, fid = struct.unpack(fmt, data[:struct.calcsize(fmt)])
        mission_id = None
        close_return = 0
        transfer = None
        with self._lock:
            transfer = self._net_files.pop(fid, None)
            if transfer is None:
                close_return = -1  # fid 不存在
            else:
                mission_id = transfer.get('mission_id')
                fname = transfer.get('name', '')
                # 移入 _file_data_cache，保留给后续 VERIFY / MISSION_REQUEST_VERIFY
                self._file_data_cache[fname] = bytes(transfer['buffer'])
                if mission_id is not None:
                    self.loaded_missions.add(mission_id)
        # 保存 .bin 文件（在锁外执行，避免 IO 阻塞）
        if transfer is not None and len(transfer['buffer']) > 0:
            self._save_drama_bin(transfer)
        # CLOSE ACK: <hii = ack_cmd + close_return + fid
        ack = struct.pack('<hii', self._NET_FILE_CLOSE, close_return, fid)
        return [(self._build_id_063_ack(ack),
                 f'id=63 NET_FILE ACK CLOSE fid={fid} mission={mission_id}')]

    def _net_file_verify(self, data):
        """VERIFY：从 _file_data_cache 取文件数据，计算 MD5 与 GCS 比对。

        VERIFY 发生在 CLOSE 之后，数据已在 _file_data_cache 中。
        VERIFY 请求数据: <16s64s = FMd5(16) + SzName(64)
        VERIFY ACK: <hi16s64s = ack_cmd(2) + VerifyReturn(4) + FMd5(16) + SzName(64)
        VerifyReturn: 0=匹配, 1=不匹配, -1=文件不存在
        """
        fmt = '<16s64s'
        gcs_md5, sz_name = struct.unpack(fmt, data[:struct.calcsize(fmt)])
        fname = sz_name.rstrip(b'\x00').decode('utf-8', 'ignore')
        verify_return = -1  # 默认：文件不存在
        actual_md5 = b'\x00' * 16
        with self._lock:
            buf = self._file_data_cache.get(fname)
            if buf is not None:
                actual_md5 = hashlib.md5(buf).digest()
                verify_return = 0 if actual_md5 == gcs_md5 else 1
        ack = struct.pack('<hi16s64s', self._NET_FILE_VERIFY, verify_return,
                          actual_md5, sz_name[:64])
        return [(self._build_id_063_ack(ack),
                 f'id=63 NET_FILE ACK VERIFY result={verify_return}')]

    # 剧本 bin 文件保存根目录（固定路径，不随 cwd 变化）
    DRAMA_SAVE_ROOT = r"D:\Work\My_Project_Local\mavlink_monitor\drama"

    def _save_drama_bin(self, transfer: dict) -> str:
        """将接收完整的剧本数据保存为 .bin 文件。

        每次保存追加时间戳后缀（_YYYYMMDD_HHMMSS），避免覆盖历史文件。
        受 enable_bin_save 开关控制，保存路径由 bin_save_dir 指定。

        Args:
            transfer: {'name', 'length', 'mission_id', 'buffer', ...}

        Returns:
            保存的文件路径；若 enable_bin_save 为 False 则返回空字符串
        """
        if not self.enable_bin_save:
            return ""
        save_dir = self.bin_save_dir
        os.makedirs(save_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        # 文件名: drama_merge_{missionId}_{timestamp}.bin，若无法解析 mission_id 则用原始名
        mission_id = transfer.get('mission_id')
        if mission_id is not None:
            safe_name = f'drama_merge_{mission_id}_{timestamp}.bin'
        else:
            raw_name = transfer.get('name', 'unknown')
            safe_name = raw_name.replace('/', '_').replace('\\', '_') + f'_{timestamp}.bin'
        filepath = os.path.join(save_dir, safe_name)
        with open(filepath, 'wb') as f:
            f.write(bytes(transfer['buffer']))
        self._last_saved_bin_path = filepath   # 记录最近接收的 bin（供 0x32 改名）
        logger.info(
            f"[TEST] 剧本文件已保存: {filepath} "
            f"(mission={mission_id}, size={len(transfer['buffer'])} bytes)"
        )
        # 保存成功后，若开关 enable_waypoint_parse 为 True 则解析并生成 3D 航点可视化 HTML
        # 调用 drama_processing 中的独立函数（已从本类剥离）
        if self.enable_waypoint_parse:
            try:
                from mavlink_monitor.gui.drama_processing import visualize_drama_3d
                visualize_drama_3d(filepath)
            except Exception as e:
                logger.warning(f"[TEST] 3D 可视化生成失败: {e}")

        return filepath

    @staticmethod
    def _format_play_time(play_ms: int) -> str:
        """将 0x32 play 字段（Unix 毫秒时间戳）格式化为 UTC 时间串 YYYYMMDD_HHMMSS.mmm。

        例：0x1A033AE6DB7 = 1787573464503 ms → 20260824_121104.503（UTC）。
        """
        millis = play_ms % 1000
        base = time.strftime('%Y%m%d_%H%M%S', time.gmtime(play_ms // 1000))
        return f"{base}.{millis:03d}"

    def _rename_last_bin_to_ip_time(self, play_ms: int) -> str:
        """收到 SWARM_FLIGHT_START(0x32) 后，将最近一次接收的 bin 重命名为【飞机IP_时间】。

        命名格式: ``{飞机IP}_YYYYMMDD_HHMMSS.SSS.bin``（时间来自 play 字段，UTC）。
        仅处理最近一次接收的 bin（不搜索旧文件）；若文件名已是该格式、
        或目标文件已存在、或未接收过 bin，则跳过，不覆盖已有文件。

        Args:
            play_ms: 0x32 消息 play 字段（Unix 毫秒时间戳）

        Returns:
            重命名后的新路径；跳过或失败返回空字符串
        """
        path = self._last_saved_bin_path
        if not path or not os.path.exists(path):
            return ""
        _fp = getattr(self, 'fake_plane', None)
        ip = (_fp.local_ip if _fp and getattr(_fp, 'local_ip', None)
              else "unknown")
        target_name = f"{ip}_{self._format_play_time(play_ms)}.bin"
        if os.path.basename(path) == target_name:
            return ""  # 文件名已是【飞机IP_时间】
        target_path = os.path.join(os.path.dirname(path), target_name)
        if os.path.exists(target_path):
            logger.info(f"[TEST] 重命名跳过（目标已存在）: {target_path}")
            return ""
        try:
            os.rename(path, target_path)
            self._last_saved_bin_path = target_path
            logger.info(f"[TEST] 已重命名 {os.path.basename(path)} → {target_name}")
            return target_path
        except Exception as e:
            logger.warning(f"[TEST] 重命名失败: {e}")
            return ""

    # 航点解析 / 3D 可视化 / 对比功能已剥离至 mavlink_monitor.gui.drama_processing
    # 作为独立模块级函数：parse_waypoints_from_bin / visualize_drama_3d / visualize_drama_compare

    def _handle_mission_request_verify(self, received):
        """MISSION_REQUEST_VERIFY(41)：查剧本是否已加载，回 MISSION_REQUEST_ACK(42)。

        对齐 C# HandleMissionRequestVerify2：
          - 检查 loaded_missions 中是否包含该 missionId
          - 清理 _file_data_cache 中对应文件名的缓存
        result=0 表示 ACCEPTED，非 0 表示 FAILED。
        """
        mid = received.fields.get('id', 0)
        # mission_request_ack_result >=0 时强制覆写（update_drama_state 可修改）；
        # -1(AUTO) 时保持原自动计算：已加载 0(ACCEPTED)，未加载 1(FAILED)。
        if self.mission_request_ack_result >= 0:
            result = self.mission_request_ack_result
        else:
            result = 0 if mid in self.loaded_missions else 1
        if result == 0:
            with self._lock:
                # 清理与该 mission_id 关联的 _file_data_cache 条目
                to_remove = []
                for fname, _ in self._file_data_cache.items():
                    if self._parse_mission_id(fname) == mid:
                        to_remove.append(fname)
                for fname in to_remove:
                    del self._file_data_cache[fname]
        return [(self._build_id_042(result),
                 f'id=42(0x2A) MISSION_REQUEST_ACK id={mid} result={result}')]

    def _handle_command_long(self, received):
        """COMMAND_LONG(76) 统一处理：

          1. 状态副作用：ARM / DISARM / 急停（_apply_command_long_effects）。
          2. 挂载点灯：命中 param7 映射则回 MOUNT_PAYLOAD_STATE(id=60)。
          3. 未命中任何挂载规则时，兜底回 COMMAND_ACK(id=77, result=0)。
        """
        # 1) 状态副作用
        self._apply_command_long_effects(received)
        # 2) 挂载点灯
        pending = self._build_mount_payload_responses(received)
        # 3) 兜底 ACK
        if not pending:
            command = received.fields.get('command', 0)
            pending.append((self._build_id_077_cmd(command=command),
                            f'id=77(0x4D) cmd={command}'))
        return pending

    def _build_mount_payload_responses(self, received):
        """按 param7 命中映射表时，构建 id=60 挂载状态。

        param7=14 灯类查询：通过 param1 区分折叠灯(1)/旧孔明灯(2)/蟠桃灯(3)/鱼灯(4)。
        其余 param7 走 _PAYLOAD_LIGHT_MAP（要求 param1==1.0）。
        """
        param7 = received.fields.get('param7')
        # —— 灯类负载查询（param7=14 共用） ——
        if param7 == 14.0:
            entry = self._PAYLOAD_LANTERN_QUERY_MAP.get(received.fields.get('param1'))
            if entry is None:
                return []
            payload_type, config_attr, name = entry
            channel = getattr(self, config_attr)
            return [(self._build_id_060(payload_type, channel),
                     f'id=60(0x3c) {name}')]
        # —— 通用负载查询（param1 必须为 1.0） ——
        if received.fields.get('param1') != 1.0:
            return []
        entry = self._PAYLOAD_LIGHT_MAP.get(param7)
        if entry is None:
            return []
        payload_type, config_attr, name = entry
        channel = getattr(self, config_attr)
        return [(self._build_id_060(payload_type, channel),
                 f'id=60(0x3c) {name}')]

    def _apply_command_long_effects(self, received):
        """COMMAND_LONG(76) 的状态副作用：ARM/DISARM、急停、切剧本、飞行中返航/降落。

        CAN_ARM(401) 无需状态改动，仅由兜底逻辑回 ACK(result=0) 表示"可解锁"；
        其余 ACK 均由 _handle_command_long 的兜底逻辑统一回传（command_ack, result=0）。
        """
        command = received.fields.get('command', 0)
        param1 = received.fields.get('param1', 0.0)
        if command == self._MAV_CMD_COMPONENT_ARM_DISARM:
            if param1 == 1.0:
                self._arm()
            elif param1 == 0.0:
                self._disarm()
        elif command == self._MAV_CMD_FLIGHT_STOP:
            # 起飞前(FlyGuideIdle/Landed) 急停：上锁复位
            if param1 == 0.0:
                self._flight_stop()
        elif command == self._MAV_CMD_CHANGE_MISSION:
            # 切换剧本：param1 为目标 mission_id（须已加载）
            mid = int(param1)
            with self._lock:
                if mid in self.loaded_missions:
                    self.mission_id = mid
        elif command == self._MAV_CMD_RETURN_TYPE:
            # 飞行中返航/降落：param1==0 → 返航(R)，否则降落(LD)
            self._on_mode_changed(self._UAV_MODE_R if param1 == 0.0
                                  else self._UAV_MODE_LD)

    def _arm(self):
        """解锁：仅当已切 G 模式且当前上锁未飞时生效（对齐 C# 前置条件）。"""
        with self._lock:
            if self.fly_state == self._FLY_DISARM and self.mode == self._UAV_MODE_G:
                self.armed = 1
                self.fly_state = self._FLY_LANDED
                self.play_state = self._PLAY_WAIT_TK
                self._landed_at_ms = self._now_ms()

    def _disarm(self):
        """上锁：仅当已解锁未起飞(Landed)时生效。"""
        with self._lock:
            if self.fly_state == self._FLY_LANDED:
                self.armed = 0
                self.fly_state = self._FLY_DISARM
                self.play_state = self._PLAY_DISARMED

    def _flight_stop(self):
        """急停：起飞前(Idle/Landed) 复位为上锁。"""
        with self._lock:
            if self.fly_state in (self._FLY_GUIDE_IDLE, self._FLY_LANDED):
                self.armed = 0
                self.fly_state = self._FLY_DISARM
                self.play_state = self._PLAY_DISARMED
        self._stop_flight()

    def _stop_flight(self):
        """停止飞行推进线程。"""
        self._flight_running = False

    # ---- 开始表演 SWARM_FLIGHT_START(50) + 飞行状态机 ----------------
    def _handle_swarm_flight_start(self, received):
        """SWARM_FLIGHT_START(50)：记录时刻并启动推进线程，回 COMMAND_ACK(50)。

        实测：真实地面站点击"开始表演"时**直接下发 SWARM_FLIGHT_START**，
        并不在同一会话重传剧本(NET_FILE)/对时(CALIB_TIME)——真机自持剧本。
        故桩不再硬性要求 `mission_id ∈ loaded_missions`，也不用 takeoff>now 拦截：
        只要当前处于地面待命态就接受(result=0) 并自主起飞；已在飞行中才拒绝。
        """
        takeoff = received.fields.get('takeoff', 0)
        play = received.fields.get('play', 0)
        ascend = received.fields.get('ascend', 0)
        descend = received.fields.get('descend', 0)
        final_mode = received.fields.get('final_mode', self._UAV_MODE_R)
        mission_id = received.fields.get('mission_id', 0)

        now = self._now_ms()
        # 收到 0x32 后，将最近一次接收的 bin 重命名为【飞机IP_时间】
        # （仅当原文件名非该格式时改名，不搜索旧文件；已是该格式则跳过）
        self._rename_last_bin_to_ip_time(play)
        # 仅当处于地面待命态才接受；已在飞行推进中(TAKEOFF/PLAY/LAND/RETURN)则拒绝
        ok = self.fly_state in (self._FLY_DISARM, self._FLY_LANDED,
                                self._FLY_GUIDE_IDLE)

        if ok:
            if mission_id not in self.loaded_missions:
                # 桩未经 NET_FILE 收到该剧本（真机自持），自动登记以放行后续校验
                logger.info(f"[TEST] SWARM: mission {mission_id} 未经下发，桩自动登记")
                self.loaded_missions.add(mission_id)
            with self._lock:
                self.mode = self._UAV_MODE_G
                self.armed = 1
                self.takeoff_time_ms = takeoff
                self.play_time_ms = play
                self.mission_id = mission_id
                self.final_mode = (final_mode if final_mode in
                                   (self._UAV_MODE_LD, self._UAV_MODE_R)
                                   else self._UAV_MODE_R)
                if ascend:
                    self.takeoff_height_mm = ascend
                if descend:
                    self.land_height_mm = descend
                self._flight_base_lat = self.cur_lat
                self._flight_base_lon = self.cur_lon
                self.fly_state = self._FLY_GUIDE_IDLE
                self.play_state = self._PLAY_WAIT_TK
                self._phase_start_ms = now
            self._start_flight()
            result = 0
        else:
            result = 4   # MAV_RESULT_FAILED（已在飞行中）

        return [(self._build_id_077_cmd(command=self._MSG_ID_SWARM_FLIGHT_START,
                                        result=result),
                 f'id=77(0x4D) SWARM_FLIGHT_START ACK result={result}')]

    def _start_flight(self):
        """启动飞行推进线程（周期 ~490ms 调用 _advance_flight）。

        用"线程存活"而非仅"标志位"判重入：GUI 下线会置 self.running=False 使
        _flight_loop 退出，但若仅靠 _flight_running 标志，重新上线后再来 SWARM
        会误判为"仍在推进"而不重启线程。故这里以 is_alive() 为准。
        """
        if (self._flight_running and self._flight_thread is not None
                and self._flight_thread.is_alive()):
            return
        self._flight_running = True
        self._flight_thread = threading.Thread(target=self._flight_loop, daemon=True)
        self._flight_thread.start()

    def _flight_loop(self):
        # self.running 由 GUI 上/下线切换；退出时必须清 _flight_running，
        # 否则下次 _start_flight 会因标志残留 True 而拒绝重启。
        try:
            while self._flight_running and self.running:
                try:
                    self._advance_flight()
                except Exception as e:
                    logger.error(f"飞行推进异常: {e}")
                time.sleep(0.49)
        finally:
            self._flight_running = False

    @staticmethod
    def _clamp01(x):
        return 0.0 if x < 0 else (1.0 if x > 1 else x)

    def _advance_flight(self):
        """飞行状态机单步推进（对应 C# ProcessFlyingCheck）。

        FlyGuideIdle → (到 takeoff) Takeoff → (到 play) Playing
                     → (播放结束) Landing → (落地) Landed → (+2s) Disarm。
        逐帧更新 cur_alt/cur_lat，play_state 对外反馈进度。
        """
        now = self._now_ms()
        stop_after = False
        with self._lock:
            st = self.fly_state
            if st == self._FLY_GUIDE_IDLE:
                if now >= self.takeoff_time_ms:
                    self.fly_state = self._FLY_GUIDE_TAKEOFF
                    self.play_state = self._PLAY_TAKEOFF
                    self._phase_start_ms = now
            elif st == self._FLY_GUIDE_TAKEOFF:
                frac = self._clamp01((now - self._phase_start_ms) /
                                     max(1, self.land_duration_ms))
                self.cur_alt = int(self.takeoff_height_mm * frac)
                if now >= self.play_time_ms:
                    self.fly_state = self._FLY_GUIDE_PLAY
                    self.play_state = self._PLAY_PLAYING
                    self.cur_alt = self.takeoff_height_mm
                    self._phase_start_ms = now
            elif st == self._FLY_GUIDE_PLAY:
                elapsed = now - self._phase_start_ms
                # 位置微动：有明确剧本时长则按进度推算，否则以 8s 为基做视觉效果
                dur_ref = self.play_duration_ms if self.play_duration_ms > 0 else 8000
                self.cur_lat = self._flight_base_lat + int(1000 * self._clamp01(elapsed / dur_ref))
                # 表演期间目标位置跟随当前位置（GUI 显式调用 update_position 优先级更高，
                # 因为 update_position 持锁设值后才释放，下一个 tick 才会进入此处覆盖）
                self.tar_lat = self.cur_lat
                self.tar_lon = self.cur_lon
                # 仅当 play_duration_ms > 0 才自动进入降落（测试用）；
                # 默认 hang 在 Playing 直到地面站下达降落/返航指令（真机自持剧本）。
                if self.play_duration_ms > 0 and elapsed >= self.play_duration_ms:
                    self.mode = self.final_mode
                    self.fly_state = (self._FLY_RETURN
                                      if self.final_mode == self._UAV_MODE_R
                                      else self._FLY_LAND)
                    self.play_state = self._PLAY_LANDING
                    self._phase_start_ms = now
            elif st in (self._FLY_LAND, self._FLY_RETURN):
                frac = self._clamp01((now - self._phase_start_ms) /
                                     max(1, self.land_duration_ms))
                self.cur_alt = int(self.takeoff_height_mm * (1 - frac))
                if now - self._phase_start_ms >= self.land_duration_ms:
                    self.cur_alt = 0
                    self.fly_state = self._FLY_LANDED
                    self.play_state = self._PLAY_LANDED
                    self._landed_at_ms = now
            elif st == self._FLY_LANDED:
                # 落地后 2s 自动上锁
                if (self.mode in (self._UAV_MODE_LD, self._UAV_MODE_R)
                        and now - self._landed_at_ms >= 2000):
                    self.fly_state = self._FLY_DISARM
                    self.armed = 0
                    self.play_state = self._PLAY_DISARMED
                    # 复位为 G 模式，使地面站 CheckCanArm 通过、可再次开始表演
                    self.mode = self._UAV_MODE_G
                    stop_after = True
        if stop_after:
            self._flight_running = False

    # ------------------------------------------------------------------
    # 消息构建（@staticmethod，原模块级 _build_xxx_msg 已迁移至此）
    # ------------------------------------------------------------------
    def _build_id_000(self):
        """构建心跳的 id=0 消息。
        autopilot 字段：独立假飞机=20(DMD_FC)，机巢管理=21(DMD_COM)。
        """
        return MAVLink_message(msg_id=0, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS, seq=0,
                              version=self.fake_plane.mavlink_version,
                              fields={'autopilot': self.autopilot,
                                      'mavlink_version': int(self.fake_plane.mavlink_version)})

    def _build_id_002(self, serial="WX10F0K00002", code="1"):
        """构建身份信息的 id=2 消息。
        """
        return MAVLink_message(msg_id=2, seq=28, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                              version=self.fake_plane.mavlink_version,
                              fields={'serial': serial,
                                      'code': code})

    def _build_id_047(self, time_ms=None):
        """构建对时应答的 id=47 (TIME_ORIGIN) 消息。

        time: uint64，UTC 相对 1970-01-01 的毫秒数。
        """
        if time_ms is None:
            time_ms = self._now_ms()
        return MAVLink_message(msg_id=self._MSG_ID_TIME_ORIGIN, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.fake_plane.mavlink_version,
                               fields={'time': int(time_ms)})

    def _build_id_042(self, result=0):
        """构建 MISSION_REQUEST_ACK(42) 消息（result=0 表示 ACCEPTED）。"""
        return MAVLink_message(msg_id=self._MSG_ID_MISSION_REQUEST_ACK, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.fake_plane.mavlink_version,
                               fields={'result': result})

    def _build_id_059(self):
        """构建剩余续航状态 REMAINING_CAPACITY_STATE(59) 消息（1Hz 主动上报）。

        全部字段经 update_bat 可更新（默认值见 __init__）。
        """
        return MAVLink_message(msg_id=self._MSG_ID_REMAINING_CAPACITY_STATE, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.fake_plane.mavlink_version,
                               fields={
                                   'safe_fly_radius': self.safe_fly_radius,
                                   'remain_fly_time': self.remain_fly_time,
                                   'go_home_need_time': self.go_home_need_time,
                                   'land_need_time': self.land_need_time,
                                   'go_home_need_capacity': self.go_home_need_capacity,
                                   'land_need_capacity': self.land_need_capacity,
                                   'battery_total_capaticy': self.battery_total_capaticy,
                                   'battery_remain_capaticy': self.battery_remain_capaticy,
                                   'battry_capacity_percentage': self.battry_capacity_percentage,
                               })

    def _build_id_006(self):
        """构建故障保护状态 FAILSAFE(6) 消息（enable_failsafe=True 时随 5s 周期上报）。

        failsafe: uint16 位掩码，每位对应一个故障（1=故障，见 _FAILSAFE_BITS）。
        """
        mask = 0
        for name, bit in self._FAILSAFE_BITS.items():
            if self.failsafe_flags.get(name):
                mask |= (1 << bit)
        return MAVLink_message(msg_id=6, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.fake_plane.mavlink_version,
                               fields={'failsafe': mask})

    def _build_id_022(self, chunk, start_index, total):
        """构建 PARAM_VALUE(22) 批量消息（一帧最多 8 个参数）。

        chunk: list[(name, value, ptype)]，长度 1~8。
        start_index: 本批首个参数的全局序号（仅用于日志，不填入消息）。
        total: 参数总数。

        对齐 C# CreateEmptyParam（FakeUavParser.cs:201）：
          param_type[8]  = 全 0（未填充）
          param_index[8] = 全 0（未填充）
        """
        values = [0.0] * 8
        indices = [0] * 8      # 恒 0，对齐 C# CreateEmptyParam
        types = bytearray(8)   # 恒 0，对齐 C# CreateEmptyParam
        names = bytearray(128)
        for i, (name, val, _ptype) in enumerate(chunk):
            values[i] = float(val)
            # indices[i] / types[i] 保持 0，不设置
            nb = name.encode('utf-8')[:16]
            names[i * 16:i * 16 + len(nb)] = nb
        return MAVLink_message(msg_id=self._MSG_ID_PARAM_VALUE, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.fake_plane.mavlink_version,
                               fields={
                                   'param_value': values,
                                   'param_index': indices,
                                   'param_count': len(chunk),
                                   'param_total': total,
                                   'param_id': bytes(names),
                                   'param_type': bytes(types),
                               })

    def _build_id_024(self, result=0):
        """构建 PARAM_REQUEST_LIST_ACK(24) 消息。"""
        return MAVLink_message(msg_id=self._MSG_ID_PARAM_REQUEST_LIST_ACK, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.fake_plane.mavlink_version,
                               fields={'result': result})

    def _build_id_063_ack(self, ack_data):
        """构建 NET_FILE_COMMAND(63) 的 ACK 消息（net_file_cmd=NET_FILE_ACK）。

        ack_data: 已按各操作 ACK 结构打包好的字节串（填入 data 字段）。
        """
        return MAVLink_message(msg_id=self._MSG_ID_NET_FILE_COMMAND, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.fake_plane.mavlink_version,
                               fields={'net_file_cmd': self._NET_FILE_ACK,
                                       'data': ack_data})

    def _build_id_005(self, wind_speed_x=0, wind_speed_y=0, sensor_health_extend=0,
                      seq=_DEFAULT_SEQ):
        """构建心跳消息的 id=5 消息。

        sensor_health_extend - bit0: rid   0x0-不存在 0x1-存在
                               bit1: gimbal 0x0-不存在 0x1-存在
                               bit2: nova  0x0-不存在 0x1-存在
        """
        return MAVLink_message(msg_id=5, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.fake_plane.mavlink_version,
                               fields={
                                    'seq': seq,
                                    "cur_lat": self.cur_lat,
                                    "cur_lon": self.cur_lon,
                                    "cur_alt": self.cur_alt,
                                    "tar_lat": self.tar_lat,
                                    "tar_lon": self.tar_lon,
                                    "tar_alt": self.tar_alt,
                                    'sensor_health': self._build_sensor_health(),
                                    'voltage_battery': self.voltage_battery,
                                    'voltage_battery_percent': self.voltage_battery_percent,
                                    'eph': 16,
                                    'wifi_up': 92,
                                    'mav_up_rate': 36,
                                    'ssid': b'd50',
                                    'fix_type': self.fix_type,
                                    'satellites_visible': 15,
                                    'rtk_quality': 65,
                                    'armed': self.armed,
                                    'mode': self.mode,
                                    'auth_constraint': 1,
                                    'fence_origin_set': 1,
                                    'home_set': 1,
                                    'fly_state': ((self.mission_id & 0x0f) << 4),
                                    'rtk_radio_850m': self.rtk_radio_850m,
                                    'rc_radio': 99,
                                    'light_r': self.light_r,
                                    'light_g': self.light_g,
                                    'light_b': self.light_b,
                                    'play_state': self.play_state,
                                    'drama_state': self.drama_state,
                                    'voltage_battery_diff': self.voltage_battery_diff,
                                    'voltage_battery_history_diff': self.voltage_battery_history_diff,
                                    'restart_flag': 0,
                                    'bat_serial_prefix': self.bat_serial_prefix,
                                    'wind_speed_x': wind_speed_x,
                                    'wind_speed_y': wind_speed_y,
                                    'uwb_group': 0,
                                    'bat_serial_suffix': self.bat_serial_suffix,
                                    'bat_serial_need_reset': self.bat_serial_need_reset,
                                    'time_need_reset': 0,
                                    'elevation': 0,
                                    'boot_need_update': 0,
                                    'charge_state': self.charge_state,
                                    'lightpanel_state': 0,
                                    'sensor_health_middle': 0,
                                    'rc_matching_code': 0,
                                    'uav_speed_horz': 0,
                                    'sensor_health_extend': sensor_health_extend,
                                    'rtk_radio_2g4': self.rtk_radio_2g4,
                               })

    def _build_id_008(self, nova_light_version=b"1234", gimbal_version=b""):
        """构建拓展心跳消息的 id=8 消息（对齐 C# HandleHeartbeatDmd，receive.cs:109-143）。

        param_hash 使用 paramDict.ParamHash，让地面站可快速校验参数一致性。
        版本字段优先使用实例变量（可通过 update_version 更新），未设置时回退到默认值。
        """
        param_hash = (self.param_dict.ParamHash
                      if self.param_dict is not None else 0)
        return MAVLink_message(msg_id=8, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.fake_plane.mavlink_version,
                               fields={
                                    "roll": 0,
                                    "pitch": 0,
                                    "yaw": 0,
                                    "battery_time": self.battery_time,
                                    "temp_imu": 0,
                                    "temp_baro": 0,
                                    "temp_batt": self.temp_batt,
                                    "param_hash": param_hash,
                                    "anchor_hash": 0,
                                    "battery_capability": self.battery_capability,
                                    "battery_used_times": self.battery_used_times,
                                    "voltage_battery_cell1": self.voltage_battery_cell1,
                                    "voltage_battery_cell2": self.voltage_battery_cell2,
                                    "voltage_battery_cell3": self.voltage_battery_cell3,
                                    "voltage_battery_cell4": self.voltage_battery_cell4,
                                    "voltage_battery_cell5": self.voltage_battery_cell5,
                                    "voltage_battery_cell6": self.voltage_battery_cell6,
                                    "flight_controller_version": self.flight_controller_version,
                                    "companion_version": self.companion_version,
                                    "battery_version": self.battery_version,
                                    "gps_version": self.gps_version,
                                    "servo_ver": self.servo_ver,
                                    "tele_version": self.tele_version,
                                    "bms_version": self.bms_version,
                                    "rid_version": self.rid_version,
                                    "gimbal_version": gimbal_version or self.gimbal_version,
                                    "voltage_rid_bat": self.voltage_rid_bat,
                                    "uas_code": b'',
                                    "laser_temperature": 25,
                                    "nova_light_version": nova_light_version or self.nova_light_version,
                               })

    def _build_id_060(self, payload_type, payload_channel):
        """构建挂载负载状态的 id=60 消息 (MAVLink_mount_payload_state_message)。

        payload_type:    负载类型 (uint8)
                         1-firework  2-laser  3-nova  4-FoldLantern(折叠灯)
                         5-FoldLante(降落伞)  6-Trumpet(喇叭)
                         7-KongMingLantern(孔明灯)  8-PeachLantern(蟠桃灯)
                         9-FishLantern(鱼灯)  10-Confetti(撒花器)
        payload_channel: 负载通道配置，支持 int 或 list（自动转为位掩码 uint32）
        """
        # list → uint32 位掩码转换（如 laser_config [1,0,1,0] → 0x5）
        if isinstance(payload_channel, list):
            payload_channel = sum((int(b) & 1) << i for i, b in enumerate(payload_channel))
        return MAVLink_message(msg_id=60, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.fake_plane.mavlink_version,
                               fields={
                                   'payload_type': payload_type,
                                   'payload_channel': payload_channel,
                               })

    def _build_id_077_cmd(self, command, result=0):
        """构建 command_ack 的 id=77 消息（动态 command / result）。

        支持三种 ACK 响应配置（按优先级从高到低）：
        1. 静默（_ack_silence_count > 0）：返回 None，完全不回复。
        2. 特定 command result 覆写（_ack_cmd_result_enabled）：对指定 command 强制返回指定 result。
        3. 失败注入（_ack_fail_count > 0）：对所有 command 前 N 次响应 result=4 (FAILED)，
           达到次数后响应 result=0 (ACCEPTED)。
        各 command 独立计数，10s 未收到该 command 则计数器自动重置。

        Args:
            command: MAVLink command ID (uint16)
            result: MAV_RESULT（0=ACCEPTED，4=FAILED）
        """
        # 1) 检查 ACK 静默响应配置（各 command 独立计数和计时）
        if self._ack_silence_count > 0:
            now = time.time()
            counter = self._ack_silence_counters.get(command, 0)
            last_time = self._ack_silence_last_time.get(command, 0)

            # 该 command 10s 未出现 → 重置计数器
            if now - last_time > 10.0:
                counter = 0

            if counter < self._ack_silence_count:
                counter += 1
                self._ack_silence_counters[command] = counter
                self._ack_silence_last_time[command] = now
                return None  # 静默，不回复

            self._ack_silence_counters[command] = counter
            self._ack_silence_last_time[command] = now

        # 2) 检查 ACK 特定 command result 覆写配置
        if self._ack_cmd_result_enabled and command in self._ack_cmd_result_map:
            result = self._ack_cmd_result_map[command]

        # 3) 检查 ACK 失败响应配置（未被 cmd_result 覆写时才生效）
        elif self._ack_fail_count > 0:
            now = time.time()
            counter = self._ack_fail_counters.get(command, 0)
            last_time = self._ack_fail_last_time.get(command, 0)

            # 该 command 10s 未出现 → 重置计数器
            if now - last_time > 10.0:
                counter = 0

            if counter < self._ack_fail_count:
                result = 4  # MAV_RESULT_FAILED
                counter += 1
            else:
                result = 0  # MAV_RESULT_ACCEPTED

            self._ack_fail_counters[command] = counter
            self._ack_fail_last_time[command] = now

        return MAVLink_message(msg_id=77, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.fake_plane.mavlink_version,
                               fields={
                                   'command': command,
                                   'result': result,
                               })

    def _build_id_204(self, laser_state=0, nova_state=0,
                       lantern_state=0, trumpet_state=0, parachute_state=0):
        """构建负载告警状态的 id=204 消息。

        laser_state  低 4 位绿色，高 4 位蓝色：
            bit 0-3 / 4-7  1:低温(<-5℃,关闭)  2:低温告警  3:高温(降功率)  4:高温(关闭)
        nova_state   bit 0: 0x0-不存在 0x1-存在
                     bit 1: 0x0-温度正常 0x1-温度告警
        lantern_state: 折叠灯状态，沿用激光状态逻辑 (uint16_t)
        trumpet_state: 喇叭状态，沿用激光状态逻辑 (uint16_t)
        parachute_state: 降落伞状态，沿用激光状态逻辑 (uint16_t)
        """
        return MAVLink_message(msg_id=204, sys_id=SYS_ID_UAV, comp_id=COMP_ID_GCS,
                               version=self.fake_plane.mavlink_version,
                               fields={
                                    "laser_state": laser_state,
                                    "nova_state": nova_state,
                                    "lantern_state": lantern_state,
                                    "trumpet_state": trumpet_state,
                                    "parachute_state": parachute_state,
                               })


class _FakeAirplaneMessageSenders:
    """批量假飞机管理器：一次性创建多架假飞机及其响应线程。

    使用方式：
        mgr = _FakeAirplaneMessageSenders(count, start_ip, start_serial, start_code, log_manager)
        for sender in mgr.senders:
            sender.start()    # 构造时不自动启动；需逐个调用 start()
        ...
        mgr.stop()           # 停止所有线程并关闭底层 FakeAirplane

    构造时按规则为每架飞机分配：
        - IP：start_ip 末段逐个 +1（不超过 .255）
        - serial：start_serial 拼接当前 code_base（3 位补零），code 继续 +1
        - code  ：逐个 +1（传给 sender 作为初始 str code）

    Attributes:
        senders: list[_FakeAirplaneMessageSender]，与 fake_airplanes 一一对应
        fake_airplanes: list[FakeAirplane]，底层 UDP 套接字实例

    Args:
        count: 飞机数量（>= 1）
        start_ip: 起始 IP，如 "172.16.3.180"
        start_serial: 起始序列号前缀，如 "WX10F0K00"
        start_code: 起始 code（int 或 str），逐个 +1
        log_manager: 日志管理器
    """

    # —— 全局独立飞机计数器（跨多次"添加"调用递增，保证经度不重复）——
    _global_airplane_counter: int = 0

    # —— 定位常量（1e7 度 / mm）——
    _POS_BASE_LAT: int = 226868664   # 基础纬度
    _POS_BASE_LON: int = 1140224548  # 基础经度
    _POS_STEP: int = 100             # 0.00001° = 100
    # 独立飞机列与机巢列纬度差 0.00001°
    _POS_LAT_OFFSET: int = 100       # 独立飞机纬度 = BASE_LAT + 100

    def __init__(self, mavlink_version, count, start_ip, start_serial, start_code, nova_light_version, log_manager, gimbal_version=b""):

        code_base = int(start_code)
        self.fake_airplane_senders = []
        self.fake_airplanes = []

        if count < 1:
            raise ValueError("count 必须 >= 1")
        base = tuple(int(p) for p in start_ip.split('.'))
        if base[3] + count - 1 > 255:
            raise ValueError(
                f"起始 IP {start_ip} 末段={base[3]} 数量={count} 超出 .255 边界"
            )

        try:
            for i in range(count):
                ip = f"{base[0]}.{base[1]}.{base[2]}.{base[3] + i}"
                fake_plane = FakeAirplane(ip_addr=ip, mavlink_version=mavlink_version, interface=NETCARD_INTERFACE)
                self.fake_airplanes.append(fake_plane)

            for idx, fake_plane in enumerate(self.fake_airplanes):
                code_val = code_base + idx
                serial_base = f"{start_serial}{code_val:03d}"
                sender = _FakeAirplaneMessageSender(
                    log_manager, fake_plane,
                    serial=serial_base,
                    code=str(code_val),
                    nova_light_version=nova_light_version,
                    gimbal_version=gimbal_version,
                    addr=(fake_plane.ground_station_ip, fake_plane.ground_station_port),
                )
                time.sleep(2)
                self.fake_airplane_senders.append(sender)

            # —— 自动定位：每架独立飞机的经度递增 0.00001°，纬度偏移 0.00001° ——
            for idx, sender in enumerate(self.fake_airplane_senders):
                global_idx = _FakeAirplaneMessageSenders._global_airplane_counter + idx
                lat = _FakeAirplaneMessageSenders._POS_BASE_LAT + _FakeAirplaneMessageSenders._POS_LAT_OFFSET
                lon = _FakeAirplaneMessageSenders._POS_BASE_LON + global_idx * _FakeAirplaneMessageSenders._POS_STEP
                sender.update_position(lat, lon, lat, lon, cur_alt=0, tar_alt=0)
                logger.info(
                    f"[POS] 独立飞机 #{global_idx} ip={sender.fake_plane.local_ip} "
                    f"lat={lat} lon={lon} alt=0"
                )
            _FakeAirplaneMessageSenders._global_airplane_counter += count

        except Exception:
            # 部分构造失败：清理已创建的 sender + FakeAirplane，再向上抛
            # 备注：网卡上的辅助 IP 暂未撤销（FakeAirplane.close() 不会调用 Remove-NetIPAddress），
            # 若想完整清理，需要 FakeAirplane 记录"本实例添加的 IP"并在 close 时撤销。
            for sender in self.fake_airplane_senders:
                try:
                    sender._cleanup()
                except Exception as e:
                    logger.error(f"sender 清理失败: {e}")
            for fake_plane in self.fake_airplanes:
                try:
                    fake_plane.close()
                except Exception as e:
                    logger.error(f"FakeAirplane 关闭失败: {e}")
            raise
    
    def stop(self):
        for fake_airplane_sender in self.fake_airplane_senders:
            fake_airplane_sender.stop()
        for fake_airplane in self.fake_airplanes:
            fake_airplane.close()


if __name__ == "__main__":

    
    log_manager = LogManager(log_dir=f"logs\\")
    senders = _FakeAirplaneMessageSenders(mavlink_version="44", count=2, start_ip="172.16.3.168", start_serial=AIRPLANE_MODEL_SERIALS["X1"], start_code="3", nova_light_version=b"1234", gimbal_version=b"", log_manager=log_manager)

    fake_airplane_senders = senders.fake_airplane_senders

    # for fake_airplane_sender in fake_airplane_senders:
    #     fake_airplane_sender.update_laser([1,0,1,0], 0)
    #     fake_airplane_sender.update_nova(1, 0)
    #     fake_airplane_sender.update_version(nova_light_version=b"1000")

    fake_airplane_senders[0].update_laser([0,0,0,0], 0)
    fake_airplane_senders[0].update_nova(1, 0)
    fake_airplane_senders[0].update_version(nova_light_version=b"1000")

    fake_airplane_senders[1].update_laser([1,0,1,0], 0)
    fake_airplane_senders[1].update_nova(1, 0)
    fake_airplane_senders[1].update_version(nova_light_version=b"1001")

    # fake_airplane_senders[2].update_laser([1,0,1,0], 0)
    # fake_airplane_senders[2].update_nova(0, 0)
    # fake_airplane_senders[2].update_version(nova_light_version=b"")

    # fake_airplane_senders[3].update_laser([1,0,1,0], 0)
    # fake_airplane_senders[3].update_nova(0, 0)
    # fake_airplane_senders[3].update_version(nova_light_version=b"1001")

    try:
        while True:
            # test_data = bytes.fromhex('fe7b8e0000081fcfc13a2063a3bccac441be0000000033335d42250651423333c5414a6f9a6e00000000a5a50100f90ef60e070f1e0f6e332e612e31393956332e36310035000000000000000000554d31363938320001313031310000000056332e3631003500000000000000556e696e697400a5a5a5a5a5a5a5a5a5a5a5a5a568bf')
            # message = MAVLink_message(hex_data=test_data.hex())
            # fake_plane.send(message)
            time.sleep(0.1)
            # msg, addr = fake_plane.receive()
            # if fake_airplane_sender is None:
            #     continue
            # logger.info(f"接收到来自 {addr} 的消息: {msg}")
    except KeyboardInterrupt:
        logger.info("正在停止 FakeAirplane...")
        senders.stop()
        logger.info("FakeAirplane 已完全停止。")

