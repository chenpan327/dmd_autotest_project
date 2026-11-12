# coding: utf-8

"""
X1 FC 基础功能公共基座 — 《FC功能规格书(L5).xlsx》P0+P1 全部 114 项功能点

来源与口径：
    - 功能点清单：C:\\Users\\dmd\\Desktop\\work\\FC功能点练习手册_P0P1.md
      （=《FC功能规格书(L5).xlsx》功能点 sheet 的 P0×26 + P1×88，L5/X1 通用）
    - 测试对象：X1 真机（拆桨 + 限流电源台架），UDP MAVLink v44
    - 三层链路（地面站→业务→飞控）从地面站侧发指令，通过
      COMMAND_ACK + packed_state(5)/extend_state(8) 状态回读 + CLI(CONSOLE)
      三通道交叉断言，覆盖"发送/转发/执行"三行

功能组 → 脚本拆分对照（按功能点一文件，扩充哪个功能点只动哪个文件）：
    ┌──────────┬──────────────────────────────┬─────────────────┬──────────┐
    │ 功能组    │ 脚本                          │ P0/P1 项数       │ 门控      │
    ├──────────┼──────────────────────────────┼─────────────────┼──────────┤
    │ GCS-01   │ test_fc_gcs01_heartbeat.py   │ p0×4            │ 失联危险  │
    │ GCS-02   │ test_fc_gcs02_status.py      │ p0×6 + p1×9     │ —        │
    │ GCS-03   │ test_fc_gcs03_arm.py         │ p0×8            │ 危险      │
    │ GCS-04   │ test_fc_gcs04_failsafe.py    │ p1×6            │ 危险      │
    │ GCS-05   │ test_fc_gcs05_mode.py        │ p0×3 + p1×10    │ 危险      │
    │ GCS-13   │ test_fc_gcs13_led.py         │ p1×2            │ —        │
    │ GCS-14   │ test_fc_gcs14_param.py       │ p1×12           │ —        │
    │ GCS-15   │ test_fc_gcs15_calibration.py │ p1×8            │ 危险      │
    │ GCS-16   │ test_fc_gcs16_log.py         │ p1×14           │ 清除毁灭  │
    │ GCS-18   │ test_fc_gcs18_standby.py     │ p1×3            │ 危险/毁灭 │
    │ GCS-19   │ test_fc_gcs19_rtcm.py        │ p1×3            │ —        │
    │ GCS-23   │ test_fc_gcs23_terminal.py    │ p1×4            │ —        │
    │ GCS-26   │ test_fc_gcs26_cli.py         │ p0×5 + p1×10    │ 电机除外  │
    │ GCS-20   │ (已迁 test_autopilot_net.py) │ p1×7            │ 毁灭      │
    └──────────┴──────────────────────────────┴─────────────────┴──────────┘

安全门控（两级环境变量，默认全关）：
    FC_BASIC_ENABLE_DANGEROUS=1    危险组：解锁/上锁、模式切换、起飞降落、
                                   失效注入、传感器校准、待机休眠（拆桨前提）
    FC_BASIC_ENABLE_DESTRUCTIVE=1  毁灭组：日志清除(LOG_ERASE)、关机(断电需
                                   重新上电)、网络配置修改(可能失联)
    永不自动执行：电机顺序检查 mtcheck（人工执行）

DMD 实测协议口径（与标准 MAVLink 的差异，来源见各常量注释）：
    - 解锁/上锁 command=400，param1 语义未定（手册 p1=1=解锁 vs release
      用例 p1=0=解锁，两轮真机实测仍未闭环）——以 GCS-03 用例的 param1
      自动定界实测结果为准；拒绝时 ACK 可能仍 result=0（仅转发成功），
      判定以 STATUSTEXT + packed_state.armed 回读为准
    - 待机 command=40046 param1=1（play 测试抓包 hex 0x9c6e，注释里的
      "cmd=183" 是笔误）；恢复 param1=0；休眠/关机参数 ⚠️待确认
    - 起飞 MAV_CMD_NAV_TAKEOFF=22 是否为 DMD 实现口径 ⚠️待确认
      （手册附录 B-#7），用例按标准号发，ACK result 记录口径
    - 模式切换 msg_id=11：custom_mode 枚举仅知 4=表演、9=降落/结束表演、
      6=RTL；其余用 CLI `mode <name>` + packed_state.mode 反查（用例产出
      枚举表存档）

⚠️ 待确认项（手册附录 B）：失联判定门限、校准停止参数、休眠/关机 param、
    指示灯使能命令（CLI 已有 notify on/off 可用）
    （EULER_NETWORK cmd 语义已由 AUTOPILOT-REQ-NET-0001/0003 确认，
      对应用例在本套件 test_autopilot_net.py）
"""

import io
import os
import socket
import sys
import time

import pytest
import allure

from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from utils.logger import log_manager


# ============================================================================
# 安全门控
# ============================================================================

# 危险组开关：解锁/上锁、模式切换、起飞降落、失效注入、校准、待机休眠
# （修正：原 == "0" 写反，未设变量时危险用例会默认执行、设了 =1 反而 skip）
ENABLE_DANGEROUS = os.environ.get("FC_BASIC_ENABLE_DANGEROUS", "0") == "1"
# 毁灭组开关：日志清除、关机、网络配置修改
ENABLE_DESTRUCTIVE = os.environ.get("FC_BASIC_ENABLE_DESTRUCTIVE", "0") == "1"

dangerous_gate = pytest.mark.skipif(
    not ENABLE_DANGEROUS,
    reason="危险用例：需拆桨+限流电源台架，且设置环境变量 "
           "FC_BASIC_ENABLE_DANGEROUS=1 后执行")

destructive_gate = pytest.mark.skipif(
    not ENABLE_DESTRUCTIVE,
    reason="毁灭性用例（断电/不可逆/可能失联）：需设置环境变量 "
           "FC_BASIC_ENABLE_DESTRUCTIVE=1 并确认在测试机上执行")

# ============================================================================
# MAVLink 消息号（v44 dialect，file/mavlink_version/mavlink_config_v44.json）
# ============================================================================

MSG_ID_HEARTBEAT = 0            # 标准心跳
MSG_ID_HEARTBEAT_DMD = 1        # 定制心跳（GCS 周期请求 → packed_state 回传）
MSG_ID_FAILSAFE = 6             # 失效上报（GCS-04 观察通道）
MSG_ID_PACKED_STATE = 5         # 打包状态（GCS-02 主观察通道）
MSG_ID_EXT_STATE = 8            # 扩展状态（姿态/温度/param_hash）
MSG_ID_SET_MODE = 11            # 模式切换（GCS-05）
MSG_ID_PARAM_REQUEST_READ = 20  # 参数协议（GCS-14）
MSG_ID_PARAM_REQUEST_LIST = 21
MSG_ID_PARAM_VALUE = 22
MSG_ID_PARAM_SET = 23
MSG_ID_PARAM_LIST_ACK = 24
MSG_ID_CONSOLE = 48             # CLI 远程终端通道（GCS-23/26）
MSG_ID_COMMAND_LONG = 76        # COMMAND_LONG / ACK
MSG_ID_COMMAND_ACK = 77
MSG_ID_LOG_REQUEST_LIST = 117   # 日志协议（GCS-16）
MSG_ID_LOG_ENTRY = 118
MSG_ID_LOG_REQUEST_DATA = 119
MSG_ID_LOG_DATA = 120
MSG_ID_LOG_ERASE = 121
MSG_ID_LOG_REQUEST_END = 122
MSG_ID_WIFI_STATUS = 212        # WIFI_STATUS 周期上报（GCS-20/GCS-02）
MSG_ID_RTCM_32 = 228            # RTCM 差分注入（GCS-19）
MSG_ID_RTCM_128 = 229
MSG_ID_RTCM_240 = 230
MSG_ID_STATUSTEXT = 253         # 状态文本（拒绝原因上报，ARM-0002/0006 规范）
MSG_ID_CALIBRATION_VALUE = 30   # 校准值上报（40040 p2=3 取值的应答通道，
                                # DGCS codec 有反序列化，载荷 69B）

# ============================================================================
# COMMAND_LONG 命令号
# ============================================================================

# 解锁/上锁（command=400；21196=强制 kill）
# param1 语义已实锤钉死（2026-09-08 GCS-03 定界真机实测）：
#   p1=1=解锁（packed_state armed 0→1 实锤帧）；
#   p1=0=上锁（反证：GCS-05 误用 p1=1"确保上锁"实际把飞机解锁，
#   起飞不再被拒）。release 用例的 p1=0 步骤标签是错的。
# ⚠️ 拒绝时 COMMAND_ACK 仍可能 result=0（仅代表转发成功），必须以
# STATUSTEXT 拒绝原因 + packed_state.armed 回读为准做判定。
CMD_ARM_DISARM = 400
ARM_P1 = 1        # 解锁（实锤）
DISARM_P1 = 0     # 上锁（实锤）
KILL_P2 = 21196   # 强制上锁 kill 魔数（MAVLink 生态通用，配合 DISARM_P1）

CMD_NAV_TAKEOFF = 22           # 一键起飞（⚠️ DMD 口径待确认，p7=目标高度）
CMD_NAV_RTL = 20               # 返航（MAVLink 标准 MAV_CMD_NAV_RETURN_TO_LAUNCH）
CMD_PREFLIGHT_CALIBRATION = 241    # 标准 MAVLink 飞前校准（标准参数语义 p1=陀螺仪等，
                                   # chenpan Release_Testing 覆盖；GCS-15 走 40040）
CMD_CALIB_SENSOR = 40040           # DMD 传感器校准总命令（DGCS 真站语义，
                                   # MavlinkCommandMessageBuilder:337 实锤）：
                                   # p1=校准类型 1加速度/2磁罗盘/3RC/4ESC/5UWB(带p3/4/5=xyz)/
                                   #    6Camera/7激光（laser 用例同源）
                                   # p2=操作 1启动/2停止（DGCS 源码实锤）；
                                   #    3取值未证实（仅 chenpan 老 skip 用例，2026-09-11
                                   #    真机 result=4 无 msg30，校准值或为推送制）
CMD_DO_SET_HOME = 179          # home 点设置（MAVLink 标准 MAV_CMD_DO_SET_HOME）
CMD_DO_SET_SERVO = 183         # 复用命令，按 param7 分路（MAVLink 标准 MAV_CMD_DO_SET_SERVO）：
                               #   param7=4 激光颜色控制（laser 用例实锤，param4=激光通道）；
                               #   LED RGB 子功能码未知——param7=0 实测点不亮 LED
                               #   （2026-09-10：ACK result=0 假成功 + light_r/g/b 回读恒 0）
CMD_STANDBY = 40046            # 电源控制（WiFi 模块 onion_companion.c:246-261 实锤）：
                               #   p1=0 开飞控电(GPIO16 高)=唤醒/恢复；
                               #   p1=1 关飞控电(GPIO16 低)=待机/关机（同一命令，
                               #        区别只在于是否再发 p1=0 拉回）；
                               #   其他值 仅记日志不动电源（2026-09-11 证伪旧猜测 p1=3）

# ============================================================================
# 飞行模式（msg_id=11 custom_mode 枚举，已知值；其余由用例反查补全）
# ============================================================================

# 2026-09-08 X1 真机 CLI 反查（GCS-05）：stab=0 / althold=2 / loiter=5 /
# rtl=6 / land=9（与 play 帧的 4=表演、9=结束一致）；auto 切换被拒，枚举未知
#
# 2026-09-10 手册缩写 + 真机终端实锤（口径定稿）：
#   手册缩写 S=姿态 stab(0) / AH=定高 althold(2) / L=定点 loiter(5) /
#   R=返航 rtl(6) / LD=land(9) / G=群控。群控 = guided = play(表演)，
#   同一模式三名（手册"群控"/CLI guided/飞控 play），custom_mode=4。
#   ⚠️ CLI 名为全称 guided（非 guide——09-08 反查失败疑似名字拼错）；
#   DISARMED 态 `mode guided` 可切实锤（"switch to mode: MODE_GUIDED"），
#   解锁态 `mode land` 可切且落地自动落锁；手册无第 7 种模式
#   auto：廖工 2026-09-10 确认未实现（跑不起来），CLI 发送仅回 ACK、
#   无切换回显——自动化只验通信链路（ACK 回执），模式功能不测
MODE_KNOWN_ENUM = {0: "stab(自稳)", 2: "althold(定高)", 4: "play(表演)",
                   5: "loiter(悬停)", 6: "rtl(返航)", 9: "land(降落/结束表演)"}
# CLI `mode <name>` 反查清单（手册练习 4：7 种模式枚举表；guided 为全称，
# 2026-09-10 终端实锤，旧值 "guide" 系拼错）
MODE_CLI_NAMES = ("stab", "althold", "loiter", "rtl", "land", "guided", "auto")

# ============================================================================
# CONSOLE 路由开关（CLI→CONSOLE 关键握手，与 laser 测试同源）
# ============================================================================

CONSOLE_ROUTE_PARAM = "SR0_CONSOLE"
CONSOLE_ROUTE_ON = 20.0        # 打开 CLI 终端（与 liaoyutao test_mavlink_cli.py 的 PARAM_CONSOLE_OPEN 同源）
CONSOLE_ROUTE_OFF = 0.0
CONSOLE_PROMPT = '~dmd_uav~@:'
CONSOLE_DATA_MAX = 250
CLI_FAIL_MARKERS = ("nak", "unknow", "error")

# heartbeat_dmd 帧（逐字节取自 test_release_testcases.py:43，真机验证可用；
# 发送后飞控回 packed_state(5)/extend_state(8)）
HEARTBEAT_DMD_HEX = 'fe0c00010101010016000000000000000001f5f5'

# 校准/日志/状态收集时长
PARAM_LIST_TIMEOUT = 30.0     # 全参数流式回传窗口：分包 8 参数/帧、param_total≈509 →
                              # ~64 帧 × ~5 帧/s ≈ 13s（2026-09-10 原始帧实锤），30s 留余量
LOG_LIST_TIMEOUT = 10.0
LOG_BLOCK_BYTES = 200          # 每次请求的日志数据块大小
SETTLE_SHORT = 1.0
SETTLE_MODE = 2.0              # 模式切换后的状态整定时间
STANDBY_SETTLE = 5.0           # 待机/恢复后的观察时间


def _cli_failed(resp):
    """判断 CLI 回显是否包含失败标记"""
    if not resp:
        return True
    low = resp.lower()
    return any(marker in low for marker in CLI_FAIL_MARKERS)


def _format_msg_detail(msg):
    """格式化消息详情（利用 MAVLink_message.print() 的输出）"""
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        msg.print()
        return sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout


def _make_console_msg(text, version=None):
    """构造 CONSOLE 消息（msg_id=48，行结尾 \\r，与 laser 测试同源）"""
    data_bytes = text.encode('utf-8') + b'\r'
    actual_len = min(len(data_bytes), CONSOLE_DATA_MAX)
    data_bytes = data_bytes[:actual_len]
    data_list = list(data_bytes) + [0] * (CONSOLE_DATA_MAX - actual_len)
    return MAVLink_message(
        msg_id=MSG_ID_CONSOLE, sys_id=1, comp_id=1, seq=0,
        fields={'length': actual_len, 'data': data_list},
        version=version)


def _extract_console_text(msg):
    """从 CONSOLE 消息中提取文本"""
    data = msg.fields.get('data', b'')
    text_len = msg.fields.get('length', 0)
    if isinstance(data, bytes):
        return data[:text_len].rstrip(b'\x00').decode('latin-1', errors='replace')
    return ""


def _make_param_set(param_name, value, version=None):
    """构造 PARAM_SET（msg_id=23，与 laser 测试抓包口径一致）

    字段语义（2026-09-11 真机验证，对齐 C# HandleSetParam）：
    param_count=名字槽个数（1）、target_system=0、param_id=名字放 16B
    槽 0 补零；SET 确认=回传 PARAM_VALUE(22) 带名 echo，不走 24。
    参数协议三指令完整速查见 test_fc_gcs14_param.py 模块 docstring。
    """
    return MAVLink_message(
        msg_id=MSG_ID_PARAM_SET, sys_id=1, comp_id=1, seq=0, version=version,
        fields={'param_value': [float(value), 0, 0, 0, 0, 0, 0, 0],
                'param_count': 1, 'target_system': 0, 'target_component': 1,
                'param_id': param_name.encode()})


# ============================================================================
# 表演报文（msg50）— 占住表演状态（GCS-03 解锁保持 / 后续起飞用例共用）
# 口径照抄 test_mavlink_play.py 真机验证实现（version=41 硬编码）
# ============================================================================

MSG_ID_TIME_CHECK = 46           # 校验时间请求
MSG_ID_TIME_ORIGIN = 47          # 校准时间应答（takeoff/play 时刻基准）
MSG_ID_SWARM_FLIGHT_START = 50   # 表演控制报文

# play 真机验证帧的校时请求（test_mavlink_play.py:192）
TIME_CHECK_HEX = 'fe014801012e00dff0'

_PLAY_FIXED_FIELDS = {
    'takeoff_light': 0xFFFFFFFFFFFFFFFF,
    'land_light': 0xFFFFFFFFFFFFFFFF,
    'ascend': 6000,
    'descend': 6000,
    'elevation': 0,
    'return_lon': -1,
    'return_lat': -1,
    'return_elevation': -1,
    'final_mode': 6,
    'mission_id': 1,
}


def build_play_hex(seq, takeoff, play):
    """构建表演控制报文（msg_id=50，version=41，play 脚本同源口径）

    Args:
        seq: 报文序列号
        takeoff: 起飞时刻（ms，基于 time_origin 计算）
        play: 表演时刻（ms）

    Returns:
        bytes: 编码后的 MAVLink 报文
    """
    import datetime
    # play_id 用当前 UTC 毫秒时间戳保证唯一
    play_id = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
    fields = dict(_PLAY_FIXED_FIELDS, takeoff=takeoff, play=play, play_id=play_id)
    msg = MAVLink_message(msg_id=MSG_ID_SWARM_FLIGHT_START, sys_id=1, comp_id=1,
                          seq=seq, fields=fields, version=41)
    return msg.pack()


# ============================================================================
# 测试基类 — 各功能组脚本继承（fixture 与底层收发，用例原样挂子类）
# ============================================================================

class FCBasicBase:
    """FC 基础功能公共基座 — 用例见 test_fc_gcsXX_*.py 各功能组脚本"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, drone_ip, drone_port, mavlink_version):
        """前置：地面站初始化 + 发现飞机；后置：关路由（如已开）+ 关闭地面站

        CONSOLE 路由不做前置——多数纯 MAVLink 用例用不到 CLI，握手放到了
        _cli() 首次调用时懒加载（见 _ensure_console），避免 CLI 异常连累
        全部用例。
        """
        self.drone_ip = drone_ip
        self.drone_port = drone_port
        self.mavlink_version = mavlink_version
        self._console_opened = False     # CONSOLE 路由懒加载状态
        with allure.step("初始化地面站并发现飞机（等心跳）"):
            self.gcs = GroundControlStation(drone_ip=drone_ip, drone_port=drone_port)
            log_manager.log_and_attach(
                f"地面站初始化完成，本地地址: {self.gcs.local_ip}:{self.gcs.local_port}",
                "初始化信息")
            hb, addr = self.gcs.wait_for_message([MSG_ID_HEARTBEAT], timeout=15.0)
            assert hb is not None, "15s 内未收到飞机心跳，飞机不在线"
            if addr and addr[0] != drone_ip:
                log_manager.log_and_attach(
                    f"心跳来源 {addr[0]} 与配置 IP {drone_ip} 不一致", "警告")
            self._clear_recv_buffer()

        yield

        with allure.step("清理测试资源"):
            if self._console_opened:
                try:
                    self._set_console_route(CONSOLE_ROUTE_OFF)
                except Exception as e:
                    log_manager.logger.warning(f"关闭 CONSOLE 路由失败: {e}")
            self.gcs.close()
            log_manager.log_and_attach("地面站已关闭，UDP 资源释放", "清理信息")

    # ==================================================================
    # 底层收发
    # ==================================================================

    def _clear_recv_buffer(self):
        """清空 UDP 接收缓冲区残留报文"""
        self.gcs.sock.settimeout(0.1)
        try:
            while True:
                data, _ = self.gcs.sock.recvfrom(4096)
                if not data:
                    break
        except socket.timeout:
            pass
        finally:
            self.gcs.sock.settimeout(self.gcs.recv_timeout)

    def _send_heartbeat_dmd(self):
        """发送 heartbeat_dmd（GCS 周期心跳，触发 packed_state 回传）"""
        msg = MAVLink_message(hex_data=HEARTBEAT_DMD_HEX)
        self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))

    def _wait_msg(self, msg_id, timeout=5.0, addr_filter=True):
        """等待指定 msg_id 报文（忽略心跳），超时返回 None"""
        start = time.time()
        while time.time() - start < timeout:
            received, addr = self.gcs.receive()
            if received is not None and received.msg_id == msg_id:
                if not addr_filter or (addr and addr[0] == self.drone_ip):
                    return received
            time.sleep(0.02)
        return None

    @staticmethod
    def _first_param_value(msg):
        """从 PARAM_VALUE 报文取第 1 个参数值（数组字段兼容解析）"""
        value = msg.fields.get('param_value')
        if isinstance(value, (list, tuple)):
            return float(value[0])
        if isinstance(value, (bytes, bytearray)) and len(value) >= 4:
            import struct
            return struct.unpack('<f', bytes(value[:4]))[0]
        return float(value)

    def _send_command(self, command, timeout=8.0, **params):
        """发送 COMMAND_LONG 并等待 COMMAND_ACK，超时返回 None（不收集文本）"""
        ack, _ = self._send_command_watch_text(command, timeout=timeout, **params)
        return ack

    def _send_command_watch_text(self, command, timeout=8.0, text_wait=1.0,
                                 **params):
        """发送 COMMAND_LONG，同时收集 ACK 与窗口内的 STATUSTEXT(253)

        拒绝类响应按 ARM-0002/0006 规范应同时回 ACK(失败) + STATUSTEXT(原因)，
        STATUSTEXT 可能在 ACK 前后到达，拿到 ACK 后再等 text_wait 秒收尾。

        Returns: (ack, [statustext 文本, ...])
        """
        fields = {'param1': 0.0, 'param2': 0.0, 'param3': 0.0, 'param4': 0.0,
                  'param5': 0.0, 'param6': 0.0, 'param7': 0.0, 'command': command,
                  'target_system': 1, 'target_component': 1, 'confirmation': 0}
        fields.update({k: float(v) for k, v in params.items()})
        cmd_msg = MAVLink_message(msg_id=MSG_ID_COMMAND_LONG, sys_id=1, comp_id=1,
                                  seq=0, version=self.mavlink_version, fields=fields)
        self.gcs.send(cmd_msg, addr=(self.drone_ip, self.drone_port))
        log_manager.log_and_attach(
            f"command={command}, params={params}", "COMMAND_LONG 发送")

        ack, texts = None, []
        ack_at = None
        start = time.time()
        while True:
            now = time.time()
            if ack is not None and now - ack_at >= text_wait:
                break
            if ack is None and now - start >= timeout:
                break
            received, addr = self.gcs.receive()
            if received is None or not addr or addr[0] != self.drone_ip:
                continue
            if received.msg_id == MSG_ID_COMMAND_ACK and ack is None:
                ack = received
                ack_at = now
                log_manager.log_and_attach(
                    _format_msg_detail(ack), f"COMMAND_ACK (command={command})")
            elif received.msg_id == MSG_ID_STATUSTEXT:
                text = self._extract_statustext(received)
                if text:
                    texts.append(text)
        if ack is None:
            log_manager.log_and_attach(
                f"等待 COMMAND_ACK 超时 ({timeout}s)", "警告")
        return ack, texts

    @staticmethod
    def _extract_statustext(msg):
        """从 STATUSTEXT(253) 提取文本（severity + 50B text，截断补零）"""
        text = msg.fields.get('text', b'')
        if isinstance(text, (bytes, bytearray)):
            return bytes(text).rstrip(b'\x00').decode('utf-8', errors='replace')
        return str(text) if text else ""

    def _assert_statustext(self, texts, keyword, action):
        """断言 STATUSTEXT 列表中包含关键字（ARM-0006：拒绝须上报具体原因）"""
        joined = ' | '.join(texts)
        log_manager.log_and_attach(joined if joined else "(无)",
                                   f"STATUSTEXT ({action})")
        assert any(keyword.lower() in t.lower() for t in texts), (
            f"{action} 的 STATUSTEXT 未包含 '{keyword}'（ARM-0002/0006 要求"
            f"拒绝时上报具体失败原因）；实际收到: {joined[:200] or '无'}——"
            f"若固件未实现 STATUSTEXT 拒绝原因上报，属需求实现差距")

    def _assert_ack(self, ack, action, expect_result=0):
        """断言 ACK 存在且 result 符合预期"""
        assert ack is not None, f"{action} 未收到 COMMAND_ACK"
        result = ack.fields.get('result', -1)
        assert result == expect_result, (
            f"{action} ACK result={result}（预期 {expect_result}），"
            f"command={ack.fields.get('command')}")
        return ack

    def _set_console_route(self, value, required=True):
        """PARAM_SET SR0_CONSOLE 开/关 CLI→CONSOLE 路由（关键握手）

        判据：收到任意 CONSOLE(48) 帧即认为路由已打开——2026-09-08 真机
        实测开路由后飞机倾倒 ~2KB CLI banner（8×251B），其中不含精确的
        "Set 'SR0_CONSOLE' OK" 字样，按精确字符串判会误判失败；CLI 的
        存活性由 _ensure_console 的 ls 预检把关。
        """
        msg = _make_param_set(CONSOLE_ROUTE_PARAM, value,
                              version=self.mavlink_version)
        self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
        log_manager.log_and_attach(
            f"PARAM_SET {CONSOLE_ROUTE_PARAM}={value}", "CONSOLE 路由")
        if value == CONSOLE_ROUTE_OFF:
            return
        parts = []
        got_console = False
        start = time.time()
        while time.time() - start < 5.0:
            received, addr = self.gcs.receive()
            if (received is not None and received.msg_id == MSG_ID_CONSOLE
                    and addr and addr[0] == self.drone_ip):
                parts.append(_extract_console_text(received))
                got_console = True
                if CONSOLE_PROMPT in parts[-1]:
                    break
            time.sleep(0.05)
        full = ''.join(parts)
        if required:
            assert got_console, (
                f"SR0_CONSOLE=20 后 5s 内未收到任何 CONSOLE 帧——路由未打开"
                f"（回显: {full[:200] or '无'}）")
        if full:
            log_manager.log_and_attach(full[:600], "CONSOLE 握手回显")

    def _ensure_console(self):
        """首次使用 CLI 时才打开 CONSOLE 路由（懒加载，幂等）

        SR0_CONSOLE=20 握手 + `ls` 存活预检只做一次；纯 MAVLink 用例
        （心跳/状态流/参数/日志/RTCM/待机等）不会触发，CLI 挂死也不影响它们。
        """
        if self._console_opened:
            return
        with allure.step("打开 CONSOLE 路由（SR0_CONSOLE=20 握手 + ls 预检）"):
            self._set_console_route(CONSOLE_ROUTE_ON)
            probe = self._cli_probe("ls", timeout=5.0)
            assert probe, (
                "CONSOLE 路由已打开但 CLI 无响应（ls 无回显）——疑似负载 CLI 挂死，"
                "需对机载负载单独重新上电后重跑")
        self._console_opened = True

    def _cli(self, text, timeout=5.0):
        """发送 CLI 命令并收集回显（GCS-23 远程终端通道，自动懒加载握手）"""
        self._ensure_console()
        return self._cli_probe(text, timeout=timeout)

    def _cli_probe(self, text, timeout=5.0):
        """发送 CLI 命令并收集回显（不做 CONSOLE 握手，供握手流程内部使用）"""
        msg = _make_console_msg(text, version=self.mavlink_version)
        self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
        parts = []
        start = time.time()
        old_timeout = self.gcs.sock.gettimeout()
        self.gcs.sock.settimeout(0.1)
        try:
            while time.time() - start < timeout:
                try:
                    received, addr = self.gcs.receive()
                except socket.timeout:
                    continue
                if (received is not None and received.msg_id == MSG_ID_CONSOLE
                        and addr and addr[0] == self.drone_ip):
                    parts.append(_extract_console_text(received))
                    if CONSOLE_PROMPT in parts[-1]:
                        break
                time.sleep(0.02)
        finally:
            self.gcs.sock.settimeout(old_timeout)
        full = ''.join(parts)
        log_manager.log_and_attach(full if full else "(空)", f"CLI: {text}")
        return full

    def _get_packed_state(self, timeout=4.0, retries=2):
        """发一次 heartbeat_dmd 并取 packed_state（GCS-02 请求-回传）"""
        for _ in range(retries):
            self._send_heartbeat_dmd()
            msg = self._wait_msg(MSG_ID_PACKED_STATE, timeout=timeout)
            if msg is not None:
                return msg
            time.sleep(0.5)
        return None

    def _poll_armed(self, expected, timeout=5.0):
        """轮询 packed_state 等待 armed 翻转；超时返回 None（不抛断言）

        供 param1 语义自动定界使用（先试一个方向，不翻再试另一个）。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            packed = self._get_packed_state(timeout=2.0, retries=1)
            if packed is not None and packed.fields.get('armed') == expected:
                return packed
            time.sleep(0.5)
        return None

    def _wait_armed_state(self, expected, timeout=5.0):
        """轮询 packed_state 等待 armed 翻转（容忍业务层状态传播延迟）

        ACK 成功 ≠ 执行成功（业务层可能只 ACK"已转发"），且状态上报存在
        传播延迟，故轮询一段时间再判定。失败信息带三路定界提示。

        Returns: 翻转后的 packed_state（供后续字段核对）
        """
        packed = self._poll_armed(expected, timeout=timeout)
        if packed is not None:
            return packed
        observed = None
        probe = self._get_packed_state(timeout=2.0, retries=1)
        if probe is not None:
            observed = probe.fields.get('armed')
        assert observed == expected, (
            f"ACK 成功但 packed_state.armed 未翻转为 {expected}"
            f"（轮询 {timeout}s 后仍为 {observed}，已排除状态传播延迟）。"
            f"定界三步：① param1 语义存疑——再发一次 cmd400 param1="
            f"{1 if expected == 0 else 0}，若 armed 翻转则 ARM_P1/DISARM_P1 "
            f"常量需互换（release 用例步骤标签 vs 手册标准语义矛盾）；"
            f"② CLI 发 `arm` 对比——CLI 成功 + MAVLink 不成功 = 业务转发层"
            f"问题；③ ACK 可能仅表示转发成功，飞控实际拒绝原因看本用例"
            f"STATUSTEXT 附件（ARM-0002 拒绝原因表，如 'Sensor not health'）")
        return probe
