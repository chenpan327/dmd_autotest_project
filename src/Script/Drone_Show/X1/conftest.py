# coding: utf-8

"""
X1 机型共享 conftest — MAVLink 构包/解析辅助 + 激光云台测试基类

Pytest 沿目录树向上查找 conftest，本文件对 X1 下所有测试目录生效
（Release_Testing / Common_Testing / Functional_Testing 等）。

内容分四部分，脚本按包路径导入使用（同 Cloud_Platform_Api / Swarm_Painter
的 `from ...conftest import ...` 先例）：
    1. 协议常量（多处引用的消息号/命令号）
    2. 解析/格式化等通用辅助函数（原先在多个测试脚本中重复实现，此处收拢）
    3. _UavSessionBase 收发方法库（MAVLink 收发，与负载无关）
    4. _GimbalLaserBase 负载方法库（云台模式/角度、激光颜色等常用控制，
       继承收发方法库；激光/云台类脚本继承即用）

前置/后置 fixture 不放这里——不同用例的清理策略可能有差别，由各测试
脚本自己的 setup_teardown 负责（需初始化会话属性 gcs / drone_ip /
drone_port / mavlink_version，参考现有激光脚本）。


构包说明：不设构包工厂层——MAVLink_message 自带字段补全
（_validate_and_fill_fields 给缺失标量补 0，pack_payload 对 bytes/list
数组超出实际长度的下标补 0），各发送方法直接构造 MAVLink_message，
仅显式给出抓包口径要求的字段，已验证与显式补零逐字节等价。
"""

import io
import os
import re
import socket
import sys
import time

from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from utils.common import get_project_root
from utils.logger import log_manager

# ============================================================================
# 1. 协议常量（多处引用的消息号/命令号；单处使用的消息号写在调用点注释）
# ============================================================================

MSG_ID_CONSOLE = 48          # CONSOLE（CLI 终端通道，构包 + 两处接收过滤共用）

CMD_DO_SET_SERVO = 183       # MAV_CMD_DO_SET_SERVO（云台角度/激光颜色控制共用）

# 终端路由开关参数名（2026-09-04 UDP 助手抓包逆向确认：置 20 打开 CLI→CONSOLE(48)
# 路由并回 "Set 'SR0_CONSOLE' OK"，置 0 关闭；缺这步 CLI 无回显，曾被误判为
# CLI 挂死）
CONSOLE_ROUTE_PARAM = "SR0_CONSOLE"

# 云台模式（CLI `gimbal <mode>`，GMBL-0001；单向切换 Init→Debug→LD Prot→Init，
# Debug 不能直接切回 Init，须经 LD Protection 中转）
GIMBAL_MODE_INIT = 0
GIMBAL_MODE_DEBUG = 1
GIMBAL_MODE_LD_PROT = 2

# 云台模式回显名（成功回显 "set gimbal to <名> mode"，三种均真机实测）：
# 用于 _gimbal_mode 的正向回显断言
GIMBAL_MODE_NAME = {GIMBAL_MODE_INIT: 'init', GIMBAL_MODE_DEBUG: 'debug',
                    GIMBAL_MODE_LD_PROT: 'ld protection'}

# 云台通道号 param4（1~4：上视 1/3、下视 2/4；真机当前使用通道 3）
GIMBAL_CHANNEL = 3

# 激光广播通道 param4=128（GMBL-0004 §3.3：任意激光均接收；亦可对
# 具体通道 1~4 下发）
LASER_BROADCAST_CHANNEL = 128


# ============================================================================
# 2. 解析 / 格式化辅助
# ============================================================================

def extract_console_text(msg):
    """从已解析的 CONSOLE 消息中提取文本"""
    data = msg.fields.get('data', b'')
    text_len = msg.fields.get('length', 0)
    if isinstance(data, bytes):
        return data[:text_len].rstrip(b'\x00').decode('latin-1', errors='replace')
    return ""


def format_msg_detail(msg):
    """格式化消息详情（捕获 MAVLink_message.print() 的输出）"""
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        msg.print()
        return sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout


# ============================================================================
# 3. 收发方法库 — MAVLink 收发（与负载无关；不含 fixture）
# ============================================================================

class _UavSessionBase:
    """MAVLink 收发方法库（不含 fixture，与负载无关）

    方法  _clear_recv_buffer / _send_console_cmd / _send_command_long
          / _set_console_route
    依赖脚本 fixture 初始化的会话属性：self.gcs / self.drone_ip /
    self.drone_port / self.mavlink_version（前置/后置由各测试脚本自己的
    setup_teardown 负责，不同用例清理策略可自行定制）。
    """

    # ==================================================================
    # 传输方法
    # ==================================================================

    def _clear_recv_buffer(self):
        """清空 UDP 接收缓冲区中的残留报文"""
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

    def _send_console_cmd(self, text, timeout=5.0):
        """发送 CONSOLE CLI 命令并收集回显文本（以提示符结束）

        构包（msg_id=48，struct_format '<B250B'）：text 以 \\r 结尾（UDP
        助手抓包确认的可行格式，不带 \\n）；data 直接传 bytes，pack_payload
        对超出实际长度的下标自动补 0。
        """
        data_bytes = text.encode('utf-8') + b'\r'
        self.gcs.send(
            MAVLink_message(msg_id=MSG_ID_CONSOLE, sys_id=1, comp_id=1, seq=0,
                            version=self.mavlink_version,
                            fields={'length': min(len(data_bytes), 250),
                                    'data': data_bytes}),
            addr=(self.drone_ip, self.drone_port))
        log_manager.log_and_attach(f"发送: {text}", "CLI 发送")

        response_parts = []
        start = time.time()
        while time.time() - start < timeout:
            received, addr = self.gcs.receive()
            if received is not None and received.msg_id == MSG_ID_CONSOLE:
                if addr[0] == self.drone_ip:
                    txt = extract_console_text(received)
                    response_parts.append(txt)
                    if '~dmd_uav~@:' in txt:    # CLI 提示符，命中表示回显结束
                        break
            time.sleep(0.05)

        full = ''.join(response_parts)
        log_manager.log_and_attach(full if full else "(空)", f"CLI 响应: {text}")
        return full

    def _send_command_long(self, command, timeout=5.0, quiet=False,
                           expect_result=0, **params):
        """构造并发送 COMMAND_LONG，等待 COMMAND_ACK 且 result=0，否则直接断言

        返回收到的 COMMAND_ACK 消息（需在用例里显式断言判据时使用）。
        构包（msg_id=76）：只传有效参数，未传的 param 位与 target_system 等
        标量由 MAVLink_message 自动补 0（与显式补零逐字节等价）。
        quiet=True 时仅写运行日志、不生成 allure 附件（极限角轮转全程近
        600 次移动，逐次附件会撑爆报告，改为按段出摘要）。
        expect_result：期望的 ACK result（默认 0）。传 None 表示接受任意
        result、仅记录日志——负向用例用（GMBL-0003/0004：旧版指令"被拒/
        被忽略"均属不可用、错通道路由丢弃无回执差异，result 不构成判据）。
        """
        cmd = MAVLink_message(
            msg_id=76, sys_id=1, comp_id=1, seq=0,    # COMMAND_LONG
            version=self.mavlink_version,
            fields={'command': command,
                    **{key: float(value) for key, value in params.items()}})
        self.gcs.send(cmd, addr=(self.drone_ip, self.drone_port))
        if not quiet:
            log_manager.log_and_attach(
                f"command={command}, params={params}", "COMMAND_LONG 发送")
            log_manager.log_and_attach(cmd.hex_data, "发送数据十六进制")

        ack = None
        start = time.time()
        while time.time() - start < timeout:
            received, addr = self.gcs.receive()
            # 须同时匹配 command 字段——否则前一条命令的迟到 ACK 会被误配
            if (received is not None and received.msg_id == 77    # COMMAND_ACK
                    and addr[0] == self.drone_ip
                    and received.fields.get('command') == command):
                ack = received
                break
            time.sleep(0.05)

        assert ack is not None, (
            f"command={command}, params={params} 未收到 COMMAND_ACK ({timeout}s)")
        result = ack.fields.get('result', -1)
        if expect_result is None:
            log_manager.logger.info(
                f"command={command}, params={params} ACK result={result}（不判据）")
        else:
            assert result == expect_result, (
                f"command={command}, params={params} 执行失败, ACK result={result}")
        if not quiet:
            log_manager.log_and_attach(
                format_msg_detail(ack), f"COMMAND_ACK (command={command})")
        return ack

    def _wait_drone_online(self, timeout=8.0):
        """等待无人机心跳（msg_id=0，实测约 5s 一条），收到即返回 True

        收到后登记进 gcs.discovered_drones，消除 send() 的"未被发现"
        误告警；超时仅告警返回 False（离线时随后的终端握手会失败报错）。
        """
        start = time.time()
        self.gcs.sock.settimeout(0.2)
        try:
            while time.time() - start < timeout:
                try:
                    data, addr = self.gcs.sock.recvfrom(4096)
                except socket.timeout:
                    continue
                if data and len(data) > 6:
                    msg = MAVLink_message(hex_data=data.hex())
                    if msg.msg_id == 0 and addr[0] == self.drone_ip:
                        self.gcs.discovered_drones.add(addr[0])
                        log_manager.log_and_attach(
                            f"收到无人机心跳，链路在线: {addr}", "链路检查")
                        return True
        finally:
            self.gcs.sock.settimeout(self.gcs.recv_timeout)
        log_manager.logger.warning(
            f"{timeout}s 内未收到 {self.drone_ip} 心跳，链路疑似离线")
        return False

    def _record_device_env(self):
        """CLI 查询固件版本/SN，写入 allure 环境信息（environment.properties）

        Drone_Show 的 conftest 只在串口 fixture 里写环境信息，UDP 流程
        缺失——此处对齐其归档口径（追加写 Firmware=/SN=），让报告能追溯
        "哪个固件跑绿的"。版本解析正则同 test_mavlink_cli.py 的 version
        用例（sn:/version:）；解析失败仅告警不阻塞。
        """
        resp = self._send_console_cmd("version")
        sn_m = re.search(r'sn[:=]\s*([^,\n]+)', resp, re.IGNORECASE)
        ver_m = re.search(r'version[:=]\s*([^\n]+)', resp, re.IGNORECASE)
        sn = sn_m.group(1).strip() if sn_m else ""
        ver = ver_m.group(1).strip() if ver_m else ""
        # 只取首个空白前的纯文本，去除可能粘连的提示符等（口径同串口 fixture）
        sn = sn.split()[0] if sn else ""
        ver = ver.split()[0] if ver else ""
        if not (sn or ver):
            log_manager.logger.warning(
                f"version 命令未解析到 sn/version: {resp[:200]}")
            return
        try:
            allure_results = os.path.join(get_project_root(), "allure-results")
            os.makedirs(allure_results, exist_ok=True)
            env_path = os.path.join(allure_results, "environment.properties")
            with open(env_path, "a", encoding="utf-8") as f:
                if ver:
                    f.write(f"Firmware={ver}\n")
                if sn:
                    f.write(f"SN={sn}\n")
            log_manager.logger.info(f"已将设备版本信息写入 {env_path}")
        except Exception as e:
            log_manager.logger.warning(f"写入环境信息失败: {e}")

    def _set_console_route(self, value):
        """发送 PARAM_SET（msg_id=23）设置 SR0_CONSOLE，开关 CLI→CONSOLE(48) 路由

        打开（value=20.0）：先发 0 复位再置 20——固件只在值变化时回显
        "Set/Save 'SR0_CONSOLE' OK"（2026-09-14 真机实测），复位保证值必然
        变化、回显必然出现；以该回显判定打开成功。
        首轮未命中会整体重试一轮（再走一遍复位+置 20）：无人机重启后的
        首次开路由，固件会先把控制台缓冲区积压的开机日志整段冲刷到
        CONSOLE 通道，握手回显被挤出 5s 接收窗（2026-09-20 实锤：8×251B
        开机日志 → 首跑"打开终端失败"，21s 后重跑即成功）；重试轮缓冲区
        已冲净，复位又保证值再次变化、回显必然出现。两轮皆未命中才判
        打开失败。
        关闭（value=0.0）：只发送不等回执（路由关后无 CONSOLE 回显）。
        字段取值与真机 UDP 抓包逐字节一致（2026-09-04 验证）：param_value[0]
        =value 其余位自动补 0，param_count=1，target_system=0，
        target_component=1（抓包口径，必须显式给），param_id=struct '128s'
        自动补零。
        """
        def _send_param(v):
            self.gcs.send(
                MAVLink_message(msg_id=23, sys_id=1, comp_id=1,    # PARAM_SET
                                seq=0, version=self.mavlink_version,
                                fields={'param_value': [float(v)],
                                        'param_count': 1,
                                        'target_system': 0, 'target_component': 1,
                                        'param_id': CONSOLE_ROUTE_PARAM.encode()}),
                addr=(self.drone_ip, self.drone_port))

        if value == 0.0:      # 关路由：无回显可等，只发送
            _send_param(0.0)
            log_manager.log_and_attach(
                f"PARAM_SET {CONSOLE_ROUTE_PARAM}=0.0（关路由）", "打开/关闭终端路由")
            return

        marker = f"'{CONSOLE_ROUTE_PARAM}' OK"   # 命中即握手成功
        full = ""
        for attempt in (1, 2):   # 首轮 + 开机日志冲刷场景重试一轮
            # 打开：先复位再置 20（复位若造成 20→0 变化，其回显会被下面
            # 的等待循环顺带收到，无碍）；间隔 0.2s 留给固件处理复位
            _send_param(0.0)
            time.sleep(0.2)
            _send_param(value)
            log_manager.log_and_attach(
                f"PARAM_SET {CONSOLE_ROUTE_PARAM}=0→{value}（复位后打开）",
                "打开/关闭终端路由")

            full = ""
            start = time.time()
            while time.time() - start < 5.0:
                received, addr = self.gcs.receive()
                if (received is not None and received.msg_id == MSG_ID_CONSOLE
                        and addr[0] == self.drone_ip):
                    full += extract_console_text(received)
                    # 命中判据用累计文本：回显可能跨帧拆开，逐帧判会漏；
                    # 也不用裸 'OK' 判——冲刷的历史文本若恰含 'OK' 会提前
                    # 退出，漏收后面的真回显（开机日志淹没握手即此场景）
                    if marker in full:
                        break
                time.sleep(0.05)
            suffix = "" if attempt == 1 else "（重试轮）"
            log_manager.log_and_attach(full if full else "(空)",
                                       f"{CONSOLE_ROUTE_PARAM}={value} 回显{suffix}")
            if marker in full:
                return
            if attempt == 1:
                log_manager.logger.warning(
                    f"首轮未收到 '{CONSOLE_ROUTE_PARAM}' OK 回显——疑似重启"
                    f"后首次开路由冲刷的开机日志占用接收窗，清空缓冲后重试")
                self._clear_recv_buffer()   # 丢掉冲刷尾巴，重试轮从干净窗口起收

        assert marker in full, (
            f"打开终端失败：重试一轮后仍未收到 '{CONSOLE_ROUTE_PARAM}' OK "
            f"回显（首轮若为开机日志冲刷，原文已进日志附件）: {full[:200]}")

# ============================================================================
# 4. 负载方法库 — 云台/激光常用控制（继承收发方法库；不含 fixture）
# ============================================================================

class _GimbalLaserBase(_UavSessionBase):
    """激光云台负载方法库 — 云台模式/角度控制与激光颜色控制（继承 _UavSessionBase）

    方法  _gimbal_mode（云台模式）/ _gimbal_lock_angle（云台角度）/
          _gimbal_vector（云台向量）/ _laser_color（激光颜色 g/b）/
          _gimbal_restore_init（恢复 Init 模式）
    子类按需覆盖 LASER_POWER_LIMIT（默认 3 护眼；相机检测需更高亮度时取 5）。
    测试后兜底清理（关激光、恢复 Init）由各脚本自己的 teardown 调用上述
    方法完成，调用顺序应在关路由/关地面站之前。
    """

    # 激光调试功率限幅：标准 10% 功率档=25（X1-REQ-LASER-0008），
    LASER_POWER_LIMIT = 25

    # 云台是否已处于 Init 模式（_gimbal_mode 维护；False 时 restore 会经
    # LD Protection 中转切回 Init）
    _gimbal_at_init = False

    # ==================================================================
    # 业务方法（gimbal / laser）
    # ==================================================================

    def _gimbal_mode(self, mode):
        """切换云台工作模式（CLI `gimbal <mode>`，GMBL-0001）

        判据双保险（固件对未知子命令也会回 ACK，仅看 ACK 会漏判）：
        正向——成功回显含 "set gimbal to <模式名> mode"（三种均真机实测）；
        反向——回显不得含 NAK / unknow 失败标记。
        模式为单向循环切换：Init → Debug → LD Protection → Init，
        Debug 不能直接切回 Init。
        """
        resp = self._send_console_cmd(f"gimbal {mode}")
        name = GIMBAL_MODE_NAME[mode]
        assert f"set gimbal to {name} mode" in resp.lower(), (
            f"gimbal mode={mode} 未命中正向回显 'set gimbal to {name} mode': "
            f"{resp[:200]}")
        low = resp.lower()
        assert not any(marker in low for marker in ("nak", "unknow")), \
            f"gimbal mode={mode} 执行失败: {resp[:200]}"
        self._gimbal_at_init = (mode == GIMBAL_MODE_INIT)
        return resp      # 回显文本，供用例步骤显式断言

    def _gimbal_restore_init(self):
        """恢复云台 Init 模式（遵循单向切换规则：Debug → LD Protection → Init）"""
        if self._gimbal_at_init:
            log_manager.logger.info("云台已处于 Init 模式，跳过切换")
            return
        self._gimbal_mode(GIMBAL_MODE_LD_PROT)
        time.sleep(0.5)   # 相邻两次模式切换的间隔（秒）
        self._gimbal_mode(GIMBAL_MODE_INIT)

    def _gimbal_lock_angle(self, x_deg, y_deg, channel, settle=1.0, quiet=False):
        """Lock 模式设置云台角度（COMMAND_LONG 183, param7=11，GMBL-0003）

        x_deg/y_deg → param1/param2；channel → param4（云台通道号 1~4，
        上视 1/3、下视 2/4）；settle 为角度整定等待时间（秒，默认 1s）；
        quiet=True 只写运行日志、不生成 allure 附件。
        返回 COMMAND_ACK，供用例步骤显式断言。
        """
        ack = self._send_command_long(
            CMD_DO_SET_SERVO,
            param1=x_deg, param2=y_deg,
            param4=channel,   # 云台通道号 1~4（上视 1/3、下视 2/4）
            param7=11,     # Lock 模式（角度形式，GMBL-0003）
            quiet=quiet)
        if quiet:
            log_manager.logger.info(f"云台步进移动 → X={x_deg}°, Y={y_deg}°")
        if settle > 0:
            time.sleep(settle)
        return ack

    def _gimbal_vector(self, x, y, z, channel, settle=1.0, quiet=False):
        """向量形式控制云台指向（COMMAND_LONG 183, param7=10）

        param1/2/3 = x/y/z 向量分量，channel → param4（云台通道号 1~4，
        上视 1/3、下视 2/4）。取值来源：
        tools/simulation_gui/resources/command_183_functions.json
        "云台角度-向量形式"（第二版云台激光需求）。settle/quiet 含义同
        _gimbal_lock_angle；返回 COMMAND_ACK 供用例显式断言。
        """
        ack = self._send_command_long(
            CMD_DO_SET_SERVO,
            param1=x, param2=y, param3=z,
            param4=channel,   # 云台通道号 1~4（上视 1/3、下视 2/4）
            param7=10,     # 云台角度-向量形式（command_183_functions.json）
            quiet=quiet)
        if quiet:
            log_manager.logger.info(f"云台向量移动 → X={x}, Y={y}, Z={z}")
        if settle > 0:
            time.sleep(settle)
        return ack

    def _laser_color(self, g, b, channel):
        """控制激光输出颜色（COMMAND_LONG 183, param7=4, param4=channel）

        X1 激光负载只有绿/蓝两色、无红光——param1(r) 恒 0，param2/3 = g/b；
        OFF=(0, 0)（LASER-0006，报文层面即 RGB 全 0）。channel → param4：
        128 为广播通道（GMBL-0004 §3.3，任意激光均接收），亦可传具体通道
        1~4（上视 1/3、下视 2/4）。功率限幅取类属性 LASER_POWER_LIMIT
        标准 10% 功率档=25（X1-REQ-LASER-0008）。
        """
        limit = self.LASER_POWER_LIMIT
        assert max(g, b) <= limit, (
            f"激光数值 (g={g}, b={b}) 超过限幅 {limit}（护眼），已拒绝发送")
        return self._send_command_long(
            CMD_DO_SET_SERVO,
            param2=g, param3=b,   # param1(r) 恒 0：X1 激光负载无红光
            param4=channel,   # 128=广播任意激光；或具体通道 1~4（上视 1/3、下视 2/4）
            param7=4)         # 激光颜色控制（真机确认）
