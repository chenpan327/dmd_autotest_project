# -*- coding: utf-8 -*-
"""
MAVLink CLI 协议实现

基于 MAVLink_console_message（消息 ID 48）封装双向 CLI 命令传输协议。
用于通过 MAVLink 通道向无人机发送 CLI 命令并接收响应。

协议说明：
    MAVLink_console_message 格式:
        - length: uint8_t  — data 中的有效字节数
        - data:   uint8_t[250] — 控制台文本数据（命令或响应）

架构参考：
    driver/tools/CLI_COMMANDS_REFERENCE.md — 75 个 CLI 命令的完整参考手册
    driver/dgcs/mav_net_file.py             — MAVLink 文件传输协议（参考实现模式）

作者：jin tao
创建时间：2025-10-15 15:33:42
"""

import sys
import os
import time as time_module

# ---------------------------------------------------------------------------
# 路径初始化
# ---------------------------------------------------------------------------
_current_dir = os.path.dirname(os.path.abspath(__file__))
_driver_dir = os.path.dirname(_current_dir)

for _p in (_current_dir, _driver_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from parse_mavlink import MAVLink_message

# ============================================================================
# MAVLink CONSOLE 消息 ID 常量
# ============================================================================
MAVLINK_MSG_ID_CONSOLE = 48
CONSOLE_DATA_MAX_LEN = 250            # data 数组最大长度

# ============================================================================
# 循环刷新模式命令（需要 q 退出，否则会持续占用 CLI）
# ============================================================================
# 这些命令进入循环刷新模式后，任何非 'q' 字符都会触发刷新，
# 必须发送 'q\\r' 才能退出循环，否则后续命令的每个字符都被当作刷新触发。
LOOP_MODE_COMMANDS = {'ps', 'mav', 'flight_time'}

# ============================================================================
# 默认超时与重试参数
# ============================================================================
DEFAULT_CMD_TIMEOUT = 5.0              # 默认命令超时（秒）
DEFAULT_RECV_BLOCKING_TIMEOUT = 0.5    # recv_match 阻塞超时（秒）
DEFAULT_MAX_RETRIES = 3                # 默认最大重试次数


#####################################################################################
# 抽象接口层：统一串口和 UDP 的 MAVLink CLI 通讯接口
#####################################################################################

class CLILink:
    """MAVLink CLI 通讯接口基类

    统一串口模式和 UDP 模式的接口，使得 CLI 命令操作函数可以通用。
    设计模式参考 mav_net_file.MAVLinkLink。
    """

    # MAVLink 消息头信息（子类可覆盖）
    SYS_ID = 0
    COMP_ID = 0
    SEQ = 0
    VERSION = None  # MAVLink 版本号（如 'v44'），None 则使用 MAVLink_message 默认版本

    def recv_match(self, blocking=False, timeout=DEFAULT_RECV_BLOCKING_TIMEOUT):
        """接收并返回一条 MAVLink 消息

        Args:
            blocking: 是否阻塞等待
            timeout: 阻塞超时时间（秒）

        Returns:
            MAVLink_message 或 None（超时返回 None）
        """
        raise NotImplementedError

    def send(self, message):
        """发送 MAVLink 消息

        Args:
            message: MAVLink_message 实例或 bytes

        Returns:
            发送成功返回 True，否则 False
        """
        raise NotImplementedError

    def console_send(self, text):
        """构造并发送 CONSOLE 消息（msg_id=48），委托 MAVLink_message.pack_payload() 打包。

        Args:
            text: 要发送的文本内容（str 或 bytes），最大 250 字节，超出自动截断。
                  自动追加 \\r（回车）作为命令终止符（模拟终端 Enter 键）。

        Returns:
            发送的 MAVLink_message 对象
        """
        if isinstance(text, str):
            data_bytes = text.encode('utf-8')
        else:
            data_bytes = text

        # 自动追加 \\r 命令终止符（CLI 需要回车触发命令处理）
        if not data_bytes.endswith(b'\r'):
            data_bytes = data_bytes + b'\r'

        actual_len = min(len(data_bytes), CONSOLE_DATA_MAX_LEN)
        data_bytes = data_bytes[:actual_len]

        # 使用 fields 委托 MAVLink_message.pack_payload() 自动打包
        # data 数组需 250 个元素（msg_id=48 struct_format: <B250B）
        data_list = list(data_bytes) + [0] * (CONSOLE_DATA_MAX_LEN - actual_len)
        fields = {'length': actual_len, 'data': data_list}

        msg = MAVLink_message(
            msg_id=MAVLINK_MSG_ID_CONSOLE,
            fields=fields,
            sys_id=self.SYS_ID,
            comp_id=self.COMP_ID,
            seq=self.SEQ,
            version=self.VERSION,
        )
        self.SEQ = (self.SEQ + 1) & 0xFF
        self.send(msg)
        return msg

    def exit_loop_mode(self):
        """发送 'q\\r' 退出 CLI 循环刷新模式（ps / mav / flight_time）

        某些命令（ps, mav, flight_time）进入交互刷新循环后，
        任何非 'q' 字符都会触发刷新，必须发送 'q\\r' 退出。
        在发送任何新命令之前调用此方法可确保 CLI 处于就绪状态。
        """
        self.console_send('q')

    def drain_recv(self, duration=0.5):
        """清空接收缓冲区中的残留消息

        Args:
            duration: 清空持续时间（秒）
        """
        start = time_module.time()
        while time_module.time() - start < duration:
            msg = self.recv_match(blocking=True, timeout=0.1)
            if msg is None:
                break

    def close(self):
        """关闭连接（子类可重写）"""
        pass


class GCSCLILink(CLILink):
    """基于 GroundControlStation 的 MAVLink CLI 通讯接口适配器

    复用 GroundControlStation 的 UDP 收发能力，与 mav_net_file.GCSSimMAVLinkLink 模式一致。
    """

    def __init__(self, gcs, sys_id=0, comp_id=0, version=None):
        """
        Args:
            gcs:     GroundControlStation 实例
            sys_id:  MAVLink 系统 ID
            comp_id: MAVLink 组件 ID
            version: MAVLink 版本号（如 'v44'），用于消息打包/解析
        """
        self._gcs = gcs
        self.SYS_ID = sys_id
        self.COMP_ID = comp_id
        self.VERSION = version

    def recv_match(self, blocking=False, timeout=DEFAULT_RECV_BLOCKING_TIMEOUT):
        start = time_module.time()
        while True:
            msg, _ = self._gcs.receive()
            if msg is None:
                if not blocking:
                    return None
                if time_module.time() - start >= timeout:
                    return None
                time_module.sleep(0.01)
            else:
                return msg

    def send(self, message):
        return self._gcs.send(message)

    def close(self):
        self._gcs.close()


#####################################################################################
# 工具函数：CONSOLE 消息的文本提取
#####################################################################################

def console_message_get_text(msg):
    """从 MAVLink_console_message 中提取文本

    依赖 MAVLink_message.unpack_payload() 将 payload 解析为 fields 字典，
    然后从中提取 length 和 data 字段。

    Args:
        msg: MAVLink_message 对象（msg_id 应为 48，已通过 unpack_payload 解析）

    Returns:
        str: 提取的文本内容（自动去除尾部零填充和 \\r）
    """
    data_field = msg.fields.get('data', b'')
    if isinstance(data_field, bytes):
        length = msg.fields.get('length', len(data_field))
        effective = data_field[:length].rstrip(b'\x00').rstrip(b'\r')
        try:
            return effective.decode('utf-8')
        except UnicodeDecodeError:
            return effective.hex()
    return ""


#####################################################################################
# 核心 CLI 命令执行
#####################################################################################

def cli_send_command(link_in, link_out, command, timeout=DEFAULT_CMD_TIMEOUT,
                     expect_ack=True):
    """向无人机发送一条 CLI 命令并等待响应

    工作流程:
        1. 构造 CONSOLE 消息（msg_id=48），携带 CLI 命令文本（自动追加 \\r）
        2. 发送到无人机
        3. 等待无人机通过 CONSOLE 消息返回响应
        4. 检测到 CLI 提示符（~dmd_uav~@:）或超时后结束收集

    Args:
        link_in:  MAVLink 输入连接对象（用于接收响应）
        link_out: MAVLink 输出连接对象（用于发送命令）
        command:  CLI 命令字符串（如 "version", "ls", "mode stab"）
        timeout:  命令超时时间（秒）
        expect_ack: 是否等待 ACK/NAK 响应头

    Returns:
        CLICmdResult: 包含 success、response_text、raw_messages 的结果对象
    """
    raw_messages = []
    response_parts = []

    # 发送命令
    link_out.console_send(command)

    # 等待响应
    start_time = time_module.time()
    prompt_seen = False

    while time_module.time() - start_time < timeout:
        msg = link_in.recv_match(blocking=True, timeout=DEFAULT_RECV_BLOCKING_TIMEOUT)
        if msg is None:
            # 如果已经看到提示符，提前结束等待
            if prompt_seen:
                break
            continue

        raw_messages.append(msg)

        # 只处理 CONSOLE 消息的响应
        if msg.msg_id == MAVLINK_MSG_ID_CONSOLE:
            text = console_message_get_text(msg)
            if text:
                response_parts.append(text)
                # 检测 CLI 提示符（~dmd_uav~@:）表示响应结束
                if CLICmdResult.CLI_PROMPT in text:
                    prompt_seen = True

        # 检测到提示符后，短暂等待确认没有后续消息
        if prompt_seen:
            follow_up = link_in.recv_match(blocking=True, timeout=0.3)
            if follow_up is None:
                break
            else:
                raw_messages.append(follow_up)
                if follow_up.msg_id == MAVLINK_MSG_ID_CONSOLE:
                    text = console_message_get_text(follow_up)
                    if text:
                        response_parts.append(text)

    full_response = ''.join(response_parts)

    # 检查 ACK/NAK
    success = True
    if expect_ack:
        if 'NAK' in full_response:
            success = False
        elif 'ACK' not in full_response and not full_response:
            success = False

    return CLICmdResult(
        success=success,
        response_text=full_response,
        raw_messages=raw_messages,
        command=command
    )


def cli_send_command_simple(link, command, timeout=DEFAULT_CMD_TIMEOUT,
                            expect_ack=True):
    """cli_send_command 的简化版本，使用单一 link 进行收发

    自动处理循环刷新模式命令（ps / mav / flight_time）：
    收到第一轮响应后自动发送 'q\\r' 退出循环。

    Args:
        link:    CLILink 对象（同时用于发送和接收）
        command: CLI 命令字符串（不含 \\r，自动追加）
        timeout: 命令超时时间（秒）
        expect_ack: 是否等待 ACK/NAK 响应头

    Returns:
        CLICmdResult
    """
    # 提取命令名（第一个空格之前的词）
    cmd_name = command.split(' ')[0].strip()

    result = cli_send_command(link, link, command, timeout=timeout,
                              expect_ack=expect_ack)

    # 循环刷新模式命令：收到响应后发送 'q\r' 退出
    if cmd_name in LOOP_MODE_COMMANDS and result.response_text:
        link.exit_loop_mode()
        link.drain_recv(0.3)

    return result


#####################################################################################
# 命令结果封装
#####################################################################################

class CLICmdResult:
    """CLI 命令执行结果

    CLI 响应格式（参考嵌入式 SYS_CLI_SERV 模块）::

        命令回显\\r\\n
        ACK\\r\\n              (或 NAK\\r\\n)
        <命令输出>\\r\\n
        ~dmd_uav~@:          (CLI 提示符)
    """

    # CLI 提示符模式（用于检测响应结束）
    CLI_PROMPT = '~dmd_uav~@:'

    def __init__(self, success=True, response_text="", raw_messages=None,
                 command=""):
        self.success = success
        # 规范化换行符: \\r\\n → \\n
        self.response_text = response_text.replace('\r\n', '\n').replace('\r', '\n')
        self.raw_messages = raw_messages if raw_messages is not None else []
        self.command = command

    @property
    def lines(self):
        """返回按行分割的响应文本列表（去除空行）"""
        return [l for l in self.response_text.split('\n') if l]

    @property
    def is_ack(self):
        """响应是否包含 ACK（检查前几行，跳过命令回显行）"""
        for line in self.lines[:3]:
            s = line.strip()
            if s.startswith('ACK'):
                return True
        return False

    @property
    def is_nak(self):
        """响应是否包含 NAK（检查前几行，跳过命令回显行）"""
        for line in self.lines[:3]:
            s = line.strip()
            if s.startswith('NAK'):
                return True
        return False

    @property
    def body(self):
        """获取 ACK/NAK 之后、提示符之前的纯业务内容

        自动去除:
          - 首行命令回显（与 self.command 匹配的行）
          - ACK/NAK 协议头行
          - 末尾 CLI 提示符行 (~dmd_uav~@:)
        """
        lines = self.lines

        # 去掉首行命令回显
        if lines and self.command and lines[0].strip() == self.command.strip():
            lines = lines[1:]

        # 去掉 ACK/NAK 行
        if lines and (lines[0].startswith('ACK') or lines[0].startswith('NAK')):
            lines = lines[1:]

        # 去掉末尾提示符
        if lines and self.CLI_PROMPT in lines[-1]:
            lines = lines[:-1]

        return '\n'.join(lines)

    @property
    def prompt(self):
        """返回响应末尾的 CLI 提示符（如 ~dmd_uav~@:），无则返回空字符串"""
        for line in reversed(self.lines):
            if self.CLI_PROMPT in line:
                return line
        return ""

    def __bool__(self):
        return self.success

    def __repr__(self):
        status = "OK" if self.success else "FAIL"
        preview = self.response_text[:200].replace('\n', '\\n')
        return f"CLICmdResult({status}, cmd='{self.command}', text='{preview}')"

    def print(self):
        """打印命令结果"""
        print(f"--- CLI 命令: {self.command} ---")
        print(f"状态: {'成功' if self.success else '失败'}")
        print(f"响应:")
        print(self.response_text)
        print(f"--- 共收到 {len(self.raw_messages)} 条原始消息 ---")


#####################################################################################
# 批量命令与交互会话
#####################################################################################

def cli_execute_batch(link, commands, timeout=DEFAULT_CMD_TIMEOUT,
                      stop_on_error=False):
    """批量执行多条 CLI 命令

    Args:
        link:         CLILink 对象
        commands:     命令字符串列表
        timeout:      每条命令的超时时间（秒）
        stop_on_error: 遇到 NAK 时是否停止

    Returns:
        list[CLICmdResult]: 每条命令的执行结果
    """
    results = []
    for cmd in commands:
        result = cli_send_command_simple(link, cmd, timeout=timeout)
        results.append(result)
        if stop_on_error and not result.success:
            break
    return results


class CLISession:
    """CLI 交互会话

    维护一个持续的命令执行上下文，支持序列号自动递增和状态跟踪。

    用法示例:
        session = CLISession(link)
        result = session.cmd("version")
        result.print()
        session.cmd("mode stab")
        print(session.summary())
    """

    def __init__(self, link, sys_id=0, comp_id=0, version=None):
        """
        Args:
            link:    CLILink 对象
            sys_id:  MAVLink 系统 ID
            comp_id: MAVLink 组件 ID
            version: MAVLink 版本号（如 'v44'）
        """
        self.link = link
        self.sys_id = sys_id
        self.comp_id = comp_id
        self._seq = 0
        self._history = []  # list[CLICmdResult]
        self._cmd_count = 0

        # 同步 link 的 ID 和版本
        if hasattr(link, 'SYS_ID'):
            link.SYS_ID = sys_id
        if hasattr(link, 'COMP_ID'):
            link.COMP_ID = comp_id
        if version is not None and hasattr(link, 'VERSION'):
            link.VERSION = version

    @property
    def seq(self):
        """获取并递增序列号"""
        s = self._seq
        self._seq = (self._seq + 1) & 0xFF
        return s

    def cmd(self, command, timeout=DEFAULT_CMD_TIMEOUT):
        """执行一条 CLI 命令

        Args:
            command: CLI 命令字符串
            timeout: 超时时间（秒）

        Returns:
            CLICmdResult
        """
        self.link.SEQ = self.seq
        result = cli_send_command_simple(self.link, command, timeout=timeout)
        self._history.append(result)
        self._cmd_count += 1
        return result

    def cmd_batch(self, commands, timeout=DEFAULT_CMD_TIMEOUT,
                  stop_on_error=False):
        """批量执行命令"""
        results = []
        for cmd in commands:
            r = self.cmd(cmd, timeout=timeout)
            results.append(r)
            if stop_on_error and not r.success:
                break
        return results

    @property
    def history(self):
        """返回命令历史"""
        return list(self._history)

    @property
    def last_result(self):
        """返回最后一条命令的结果"""
        return self._history[-1] if self._history else None

    def summary(self):
        """返回会话摘要"""
        total = len(self._history)
        ok = sum(1 for r in self._history if r.success)
        fail = total - ok
        return (f"CLISession: {total} 条命令, "
                f"{ok} 成功, {fail} 失败")

    def print_history(self):
        """打印命令历史摘要"""
        print(f"=== CLI 会话历史 ({self.summary()}) ===")
        for i, r in enumerate(self._history):
            status = "✓" if r.success else "✗"
            print(f"  [{i}] {status} {r.command}")
            if r.response_text:
                # 缩进显示响应第一行
                first_line = r.response_text.split('\n')[0]
                print(f"      → {first_line}")


#####################################################################################
# 高层 CLI 命令封装
# 按照 CLI_COMMANDS_REFERENCE.md 分类，提供 Pythonic 的命令接口
#####################################################################################

class CLIClient:
    """高层 CLI 客户端

    将 CLI_COMMANDS_REFERENCE.md 中记录的 75 个命令封装为 Python 方法。
    内部使用 CLISession 管理 MAVLink 通讯。

    用法示例:
        link = UDPCLILink("172.16.3.180")
        client = CLIClient(link)

        # 通用命令
        client.ls()
        client.version()
        client.ps()

        # 控制命令
        client.mode("stab")
        client.arm()
        client.takeoff(10.0)
        client.land()
        client.disarm()

        # 参数命令
        client.pp("MT0_MAP")
        client.sp("MT0_MAP:1")
    """

    def __init__(self, link, sys_id=0, comp_id=0, version=None):
        """
        Args:
            link:    CLILink 对象
            sys_id:  MAVLink 系统 ID
            comp_id: MAVLink 组件 ID
            version: MAVLink 版本号（如 'v44'）
        """
        self._session = CLISession(link, sys_id=sys_id, comp_id=comp_id,
                                   version=version)

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def link(self):
        return self._session.link

    @property
    def history(self):
        return self._session.history

    @property
    def last_result(self):
        return self._session.last_result

    # ------------------------------------------------------------------
    # 原始命令执行
    # ------------------------------------------------------------------

    def raw(self, command, timeout=DEFAULT_CMD_TIMEOUT):
        """执行任意原始 CLI 命令字符串"""
        return self._session.cmd(command, timeout=timeout)

    # ==================================================================
    # 一、通用命令 (Common Commands)
    # ==================================================================

    # --- 1. ls ---
    def ls(self):
        """列出当前目录内容"""
        return self._session.cmd("ls")

    # --- 2. cd ---
    def cd(self, dir_name):
        """切换工作目录

        Args:
            dir_name: 目录名，".." 返回上级
        """
        return self._session.cmd(f"cd {dir_name}")

    # --- 3. cat ---
    def cat(self, file_path):
        """读取文件内容（十六进制）

        Args:
            file_path: 文件路径
        """
        return self._session.cmd(f"cat {file_path}")

    # --- 4. ps ---
    def ps(self):
        """查看任务状态（进程列表），按 q 退出刷新模式"""
        return self._session.cmd("ps")

    # --- 5. pp ---
    def pp(self, param_name=None):
        """打印参数值

        Args:
            param_name: 参数名，省略则递归打印所有参数
        """
        if param_name:
            return self._session.cmd(f"pp {param_name}")
        return self._session.cmd("pp")

    # --- 6. pm ---
    def pm(self):
        """打印模块信息"""
        return self._session.cmd("pm")

    # --- 7. sp ---
    def sp(self, param_name, value):
        """设置参数值（仅内存，不持久化）

        Args:
            param_name: 参数名
            value:      参数值
        """
        return self._session.cmd(f"sp {param_name}:{value}")

    # --- 8. svp ---
    def svp(self, param_name):
        """保存参数到 Flash

        Args:
            param_name: 参数名
        """
        return self._session.cmd(f"svp {param_name}")

    # --- 9. log ---
    def log_start(self):
        """启动飞行日志记录"""
        return self._session.cmd("log start")

    def log_stop(self):
        """停止飞行日志记录"""
        return self._session.cmd("log stop")

    # --- 10. dt ---
    def dt(self, topic_name):
        """显示 UORB 主题数据

        Args:
            topic_name: UORB 主题名（不含 /uorb/ 前缀）
        """
        return self._session.cmd(f"dt {topic_name}")

    # --- 11. smsg ---
    def smsg(self, clear=False):
        """显示/清除系统日志

        Args:
            clear: True=清除，False=显示
        """
        if clear:
            return self._session.cmd("smsg c")
        return self._session.cmd("smsg")

    # --- 12. dmsg ---
    def dmsg(self, clear=False):
        """显示/清除调试日志

        Args:
            clear: True=清除，False=显示
        """
        if clear:
            return self._session.cmd("dmsg c")
        return self._session.cmd("dmsg")

    # --- 13. rm ---
    def rm(self, file_path):
        """删除文件

        Args:
            file_path: 文件路径
        """
        return self._session.cmd(f"rm {file_path}")

    # --- 14. istate ---
    def istate(self):
        """查看初始化状态"""
        return self._session.cmd("istate")

    # --- 15. sheal ---
    def sheal(self):
        """查看传感器健康状态"""
        return self._session.cmd("sheal")

    # --- 16. mav ---
    def mav(self, channel):
        """查看 MAVLink 通道状态（按 q 退出）

        Args:
            channel: 通道索引（0-based）
        """
        return self._session.cmd(f"mav {channel}")

    # --- 17. now ---
    def now(self):
        """查看系统时间和飞行时间"""
        return self._session.cmd("now")

    # --- 18. wifi ---
    def wifi(self, nw_id=None, ssid=None, reset=False):
        """WiFi 模块配置

        Args:
            nw_id: 网络 ID（1-999），与 ssid 同时使用
            ssid:  SSID（1-8 字符），与 nw_id 同时使用
            reset: True=复位 WiFi 模块
        """
        if reset:
            return self._session.cmd("wifi reset")
        if nw_id is not None and ssid is not None:
            return self._session.cmd(f"wifi {nw_id}:{ssid}")
        return self._session.cmd("wifi")

    # --- 19. 080 ---
    def reset_bno080(self):
        """复位 BNO080 传感器"""
        return self._session.cmd("080")

    # --- 20. uwb ---
    def uwb_debug(self):
        """进入 UWB 调试模式"""
        return self._session.cmd("uwb")

    # --- 21. com ---
    def com(self):
        """与伴飞计算机通信（进入交互模式）"""
        return self._session.cmd("com")

    # --- 22. version ---
    def version(self):
        """查看固件版本和序列号"""
        return self._session.cmd("version")

    # --- 23. fs_state ---
    def fs_state(self):
        """查看故障保护状态"""
        return self._session.cmd("fs_state")

    # --- 24. bat ---
    def bat(self):
        """查看电池详细状态"""
        return self._session.cmd("bat")

    # --- 25. sd_format ---
    def sd_format(self):
        """格式化 SD 卡（危险操作！）"""
        return self._session.cmd("sd_format")

    # ==================================================================
    # 二、无人机控制命令 (UAV Control)
    # ==================================================================

    # --- 26. mode ---
    def mode(self, mode_name=None):
        """设置/查看飞行模式

        Args:
            mode_name: 模式名（stab/althold/loiter/guided/auto/land/rtl）
                       省略则查看当前模式，"?" 列出可用模式
        """
        if mode_name:
            return self._session.cmd(f"mode {mode_name}")
        return self._session.cmd("mode")

    def mode_list(self):
        """列出可用飞行模式"""
        return self._session.cmd("mode ?")

    # --- 27. takeoff ---
    def takeoff(self, height, lat_offset=0, lon_offset=0, extra=0):
        """起飞命令

        Args:
            height:     起飞高度（取负值，向上为正）
            lat_offset: 纬度偏移（可选）
            lon_offset: 经度偏移（可选）
            extra:      备用参数（可选）
        """
        if lat_offset or lon_offset or extra:
            return self._session.cmd(
                f"takeoff {height},{lat_offset},{lon_offset},{extra}")
        return self._session.cmd(f"takeoff {height}")

    # --- 28. flyto ---
    def flyto(self, x, y, z):
        """飞行到指定位置

        Args:
            x: 目标 X 坐标
            y: 目标 Y 坐标
            z: 目标 Z 坐标（负值向上）
        """
        return self._session.cmd(f"flyto {x},{y},{z}")

    # --- 29. arm ---
    def arm(self):
        """解锁（ARM）电机"""
        return self._session.cmd("arm")

    # --- 30. disarm ---
    def disarm(self):
        """锁定（DISARM）电机"""
        return self._session.cmd("disarm")

    # --- 31. servo ---
    def servo(self, ch0, ch1, ch2):
        """设置舵机值

        Args:
            ch0: 通道 0 值（0-255）
            ch1: 通道 1 值（0-255）
            ch2: 通道 2 值（0-255）
        """
        return self._session.cmd(f"servo {ch0},{ch1},{ch2}")

    # --- 32. fstart ---
    def fstart(self):
        """开始飞行任务"""
        return self._session.cmd("fstart")

    # --- 33. notify ---
    def notify_on(self):
        """开启通知/指示灯"""
        return self._session.cmd("notify on")

    def notify_off(self):
        """关闭通知/指示灯"""
        return self._session.cmd("notify off")

    # --- 34. home ---
    def set_home(self, lat, lon):
        """设置 Home 点位置

        Args:
            lat: 纬度
            lon: 经度
        """
        return self._session.cmd(f"home {lat},{lon}")

    # --- 35. fence ---
    def set_fence(self, radius, height, center_x=None, center_y=None):
        """设置电子围栏

        Args:
            radius:   围栏半径
            height:   围栏高度
            center_x: 中心 X 坐标（可选，省略则以当前位置为中心）
            center_y: 中心 Y 坐标（可选，省略则以当前位置为中心）
        """
        if center_x is not None and center_y is not None:
            return self._session.cmd(f"fence {center_x},{center_y},{radius},{height}")
        return self._session.cmd(f"fence {radius},{height}")

    # --- 36. relay ---
    def relay(self, relay_id, value):
        """继电器/点火器控制

        Args:
            relay_id: 继电器编号
            value:    0=关闭, 1=开启
        """
        return self._session.cmd(f"relay {relay_id},{value}")

    # --- 37. radio_pair ---
    def radio_pair(self, option=4):
        """遥控器对频

        Args:
            option: 4=自动对频，其他值=按遥控器编码对频
        """
        return self._session.cmd(f"radio_pair {option}")

    # ==================================================================
    # 三、测试命令 (Testing Commands)
    # ==================================================================

    # --- 38. ct ---
    def clock_test(self, event_type, delay_sec):
        """时钟事件测试

        Args:
            event_type: CLOCK_EVENT_TYPE 枚举值
            delay_sec:  触发延时（秒）
        """
        return self._session.cmd(f"ct {event_type},{delay_sec}")

    # --- 39. vt ---
    def vibrate_test_start(self, p1, p2, p3, p4):
        """启动振动测试"""
        return self._session.cmd(f"vt 1,{p1},{p2},{p3},{p4}")

    def vibrate_test_stop(self):
        """停止振动测试"""
        return self._session.cmd("vt 0")

    # --- 40. rattest ---
    def rate_test(self, wave, axis_x, axis_y, axis_z, period_ms,
                  phase_ms, pos_gain, neg_gain, extra=0):
        """角速率响应测试"""
        return self._session.cmd(
            f"rattest {wave},{axis_x},{axis_y},{axis_z},"
            f"{period_ms},{phase_ms},{pos_gain},{neg_gain},{extra}")

    # --- 41. atttest ---
    def atti_test(self, wave, axis_x, axis_y, axis_z,
                  gain, period_ms, test_time_ms, wait_time_ms):
        """姿态响应测试"""
        return self._session.cmd(
            f"atttest {wave},{axis_x},{axis_y},{axis_z},"
            f"{gain},{period_ms},{test_time_ms},{wait_time_ms}")

    # --- 42. postest ---
    def pos_test(self, wave, direction, gain, time_val, period):
        """位置注入测试"""
        return self._session.cmd(
            f"postest {wave},{direction},{gain},{time_val},{period}")

    # --- 43. ffs ---
    def fake_fail_clear(self):
        """清除所有模拟故障"""
        return self._session.cmd("ffs 0")

    def fake_fail_battery(self):
        """模拟低电量故障"""
        return self._session.cmd("ffs 1")

    def fake_fail_waypoint(self):
        """模拟航点错误故障"""
        return self._session.cmd("ffs 2")

    def fake_fail_fence(self):
        """模拟围栏越界故障"""
        return self._session.cmd("ffs 3")

    def fake_fail_ekf(self, horiz_invalid=0, vert_invalid=0, atti_invalid=0):
        """模拟 EKF 故障"""
        return self._session.cmd(
            f"ffs 4,{horiz_invalid},{vert_invalid},{atti_invalid}")

    # --- 44. sdtest ---
    def sd_test(self, cycles=100, delete_first=False):
        """SD 卡读写测试

        Args:
            cycles:       测试循环次数
            delete_first: 测试前先删除测试文件
        """
        cmd = f"sdtest {cycles}"
        if delete_first:
            cmd += " -d"
        return self._session.cmd(cmd)

    # --- 45. temp_test ---
    def temp_test(self, target_temp=2200):
        """温度漂移测试

        Args:
            target_temp: 目标温度值
        """
        return self._session.cmd(f"temp_test {target_temp}")

    # --- 46. mtcheck ---
    def motor_check_stop(self):
        """停止电机检测"""
        return self._session.cmd("mtcheck -1")

    def motor_check_simple(self, mode, thro):
        """简单电机检测"""
        return self._session.cmd(f"mtcheck {mode},{thro}")

    def motor_check_stepped(self, mt_index, start_thro, target_thro,
                            step, interval):
        """步进油门电机检测"""
        return self._session.cmd(
            f"mtcheck 2,{mt_index},{start_thro},{target_thro},{step},{interval}")

    def motor_check_manual(self, mt0, mt1, mt2, mt3, interval):
        """多电机手动油门"""
        return self._session.cmd(
            f"mtcheck 3,{mt0},{mt1},{mt2},{mt3},{interval}")

    def motor_check_cycle(self, mt0, mt1, mt2, mt3,
                          work_t, relax_t, interval):
        """多电机周期测试"""
        return self._session.cmd(
            f"mtcheck 4,{mt0},{mt1},{mt2},{mt3},{work_t},{relax_t},{interval}")

    # --- 47. tracealyzer ---
    def tracealyzer(self, filter_group):
        """Tracealyzer 滤波器设置

        Args:
            filter_group: FilterGroup 编号（0-6）
        """
        return self._session.cmd(f"tracealyzer {filter_group}")

    # --- 48. esc ---
    def esc_cal(self):
        """ESC 校准模式（需重启）"""
        return self._session.cmd("esc cal")

    def esc_work(self):
        """ESC 正常工作模式"""
        return self._session.cmd("esc work")

    def esc_manual(self):
        """ESC 手动校准模式"""
        return self._session.cmd("esc manual")

    # --- 49. aging_test ---
    def aging_test_stop(self):
        """停止老化测试"""
        return self._session.cmd("aging_test 0")

    def aging_test_simple(self, time_val, throttle_duration):
        """简单老化测试"""
        return self._session.cmd(f"aging_test 1,{time_val},{throttle_duration}")

    def aging_test_advanced(self, stride, low_pct, mid_pct, high_pct, top_pct,
                            time_val, throttle_dur, extra1, extra2, extra3):
        """高级老化测试（多级油门）"""
        return self._session.cmd(
            f"aging_test 2,{low_pct},{mid_pct},{high_pct},{top_pct},"
            f"{stride},{time_val},{throttle_dur},{extra1},{extra2},{extra3}")

    # --- 50. cam_cali ---
    def cam_cali(self):
        """触发相机校准"""
        return self._session.cmd("cam_cali")

    # --- 51. dshot ---
    def dshot_start(self):
        """启动 DShot 输出"""
        return self._session.cmd("dshot start")

    def dshot_stop(self):
        """停止 DShot 输出"""
        return self._session.cmd("dshot stop")

    def dshot_telemetry(self, enable):
        """DShot 遥测开关

        Args:
            enable: True=开启, False=关闭
        """
        return self._session.cmd(f"dshot tel {1 if enable else 0}")

    def dshot_test(self):
        """DShot 测试模式"""
        return self._session.cmd("dshot t")

    def dshot_rpm(self):
        """读取电机 RPM"""
        return self._session.cmd("dshot rpm")

    def dshot_info(self, n):
        """请求电调信息

        Args:
            n: 电调编号
        """
        return self._session.cmd(f"dshot info {n}")

    def dshot_led(self, enable):
        """DShot LED 控制"""
        return self._session.cmd(f"dshot led {1 if enable else 0}")

    def dshot_dir(self, direction):
        """DShot 电机方向

        Args:
            direction: 0 或 1
        """
        return self._session.cmd(f"dshot dir {direction}")

    def dshot_3d(self, enable):
        """DShot 3D 模式开关"""
        return self._session.cmd(f"dshot 3d {1 if enable else 0}")

    # --- 52. cam_param ---
    def cam_param(self, reg, value):
        """相机寄存器参数读写

        Args:
            reg:   寄存器地址（如 0x30）
            value: 寄存器值（如 0x01）
        """
        return self._session.cmd(f"cam_param 0x{reg:02X},0x{value:02X}")

    # --- 53. mt_test ---
    def mt_test_stop(self):
        """停止电机测试"""
        return self._session.cmd("mt_test 0")

    def mt_test_simple(self, cycles):
        """电机基础测试"""
        return self._session.cmd(f"mt_test {cycles}")

    def mt_test_delay(self, motor, amplitude, duty, cycles):
        """电机延迟测试"""
        return self._session.cmd(
            f"mt_test {motor},{amplitude},{duty},{cycles}")

    def mt_test_cnc(self, motor, amplitude):
        """CNC 电源模式测试"""
        return self._session.cmd(f"mt_test {motor},{amplitude}")

    def mt_test_log(self, motor, interval, min_thro, max_thro, time_val):
        """电机日志记录"""
        return self._session.cmd(
            f"mt_test {motor},{interval},{min_thro},{max_thro},{time_val}")

    # --- 54. fake_gps ---
    def fake_gps_start(self, lon, lat, alt):
        """启用模拟 GPS

        Args:
            lon: 模拟经度
            lat: 模拟纬度
            alt: 模拟高度
        """
        return self._session.cmd(f"fake_gps 1,{lon},{lat},{alt}")

    def fake_gps_stop(self):
        """禁用模拟 GPS"""
        return self._session.cmd("fake_gps -1,0,0,0")

    # ==================================================================
    # 四、调试命令 (Debug Commands)
    # ==================================================================

    # --- 55. flash ---
    def flash_read(self, flash_type):
        """读取调试 Flash

        Args:
            flash_type: 1=Trace, 2=Watchdog, 3=PVD
        """
        return self._session.cmd(f"flash {flash_type}")

    # --- 56. erase_flash ---
    def erase_flash(self):
        """擦除调试 Flash（需重启）"""
        return self._session.cmd("erase_flash")

    # --- 57. rebuild_param ---
    def rebuild_param(self):
        """重建参数文件"""
        return self._session.cmd("rebuild_param")

    # --- 58. notify_flash ---
    def notify_flash(self, value):
        """设置通知 Flash LED

        Args:
            value: LED 数值
        """
        return self._session.cmd(f"notify_flash {value}")

    # --- 59. log_del ---
    def log_delete(self, log_id=0):
        """删除飞行日志

        Args:
            log_id: 日志 ID（0=删除全部）
        """
        return self._session.cmd(f"log_del {log_id}")

    # --- 60. protect ---
    def flash_protect_enable(self):
        """开启 Flash 读保护"""
        return self._session.cmd("protect 1")

    def flash_protect_disable(self):
        """关闭 Flash 读保护（会擦除 Flash）"""
        return self._session.cmd("protect 2")

    # --- 61. task_switch ---
    def task_switch(self):
        """显示任务切换追踪"""
        return self._session.cmd("task_switch")

    # --- 62. bms_reset ---
    def bms_reset(self):
        """BMS（电池管理系统）复位"""
        return self._session.cmd("bms_reset")

    # --- 63. sd_getinfo ---
    def sd_getinfo(self):
        """查看 SD 卡详细信息"""
        return self._session.cmd("sd_getinfo")

    # --- 64. gimbal ---
    def gimbal_init(self):
        """云台初始化模式"""
        return self._session.cmd("gimbal 0")

    def gimbal_debug(self):
        """云台调试模式"""
        return self._session.cmd("gimbal 1")

    # --- 65. flight_time ---
    def flight_time(self):
        """实时显示飞行时间/续航信息"""
        return self._session.cmd("flight_time")

    # --- 66. shell_echo_config ---
    def shell_echo(self, state=None):
        """控制 CLI 回显

        Args:
            state: 'on'/'off'/'?'，省略则查看当前状态
        """
        if state:
            return self._session.cmd(f"shell_echo_config {state}")
        return self._session.cmd("shell_echo_config")

    # ==================================================================
    # 五、DAV 数传命令 (DAV Radio Commands)
    # ==================================================================

    # --- 67. ask_receiver_encrypt_key ---
    def ask_receiver_encrypt_key(self):
        """请求接收器加密密钥"""
        return self._session.cmd("ask_receiver_encrypt_key")

    # --- 68. radio_test_config ---
    def radio_test_config(self, mode=None):
        """数传工厂测试模式

        Args:
            mode: 0-9=设置模式，省略=查询当前模式
        """
        if mode is not None:
            return self._session.cmd(f"radio_test_config {mode}")
        return self._session.cmd("radio_test_config")

    # --- 69. radio_850m_mode ---
    def radio_850m_mode(self, mode=None):
        """850M LLCC68 运行模式"""
        if mode is not None:
            return self._session.cmd(f"radio_850m_mode {mode}")
        return self._session.cmd("radio_850m_mode")

    # --- 70. radio_850m_freq ---
    def radio_850m_freq(self, freq=None):
        """850M 频率设置/查询（范围 850000-930000 Hz）"""
        if freq is not None:
            return self._session.cmd(f"radio_850m_freq {freq}")
        return self._session.cmd("radio_850m_freq")

    # --- 71. radio_850m_config ---
    def radio_850m_config(self, *params):
        """850M 数据包配置

        Args:
            *params: 9 个整数参数，省略则查询
        """
        if params:
            return self._session.cmd(
                f"radio_850m_config {','.join(str(p) for p in params)}")
        return self._session.cmd("radio_850m_config")

    # --- 72. radio_2g4_mode ---
    def radio_2g4_mode(self, mode=None):
        """2.4G SX1280 运行模式"""
        if mode is not None:
            return self._session.cmd(f"radio_2g4_mode {mode}")
        return self._session.cmd("radio_2g4_mode")

    # --- 73. radio_2g4_freq ---
    def radio_2g4_freq(self, freq=None):
        """2.4G 频率设置/查询（范围 2400000-2500000 Hz）"""
        if freq is not None:
            return self._session.cmd(f"radio_2g4_freq {freq}")
        return self._session.cmd("radio_2g4_freq")

    # --- 74. radio_2g4_config ---
    def radio_2g4_config(self, *params):
        """2.4G 数据包配置

        Args:
            *params: 7 个整数参数，省略则查询
        """
        if params:
            return self._session.cmd(
                f"radio_2g4_config {','.join(str(p) for p in params)}")
        return self._session.cmd("radio_2g4_config")

    # --- 75. dav_up ---
    def dav_upgrade(self, upgrade_type=0):
        """DAV 应用升级

        Args:
            upgrade_type: 0=退出升级, 1=Radio 升级, 2=LPPC 升级
        """
        return self._session.cmd(f"dav_up {upgrade_type}")

    # ==================================================================
    # 便利组合方法
    # ==================================================================

    def takeoff_and_loiter(self, height):
        """起飞后切换到悬停模式（组合命令）

        Args:
            height: 起飞高度
        """
        result = self.takeoff(height)
        if not result:
            return result
        return self.mode("loiter")

    def land_and_disarm(self):
        """降落并锁定"""
        r1 = self.mode("land")
        # 注意：实际使用中可能需要等待降落完成
        r2 = self.disarm()
        return r2

    def safe_reboot(self):
        """安全重启流程：锁定 → 确认后发送重启

        注意：实际 reboot 命令需要通过其他机制实现，此处仅作示例。
        """
        return self.disarm()

    def get_basic_info(self):
        """获取基本信息：版本、电池、传感器健康

        Returns:
            dict: 包含 version, bat, sheal, now 的结果
        """
        return {
            'version': self.version(),
            'bat': self.bat(),
            'sheal': self.sheal(),
            'now': self.now(),
        }

    def get_system_overview(self):
        """获取系统概览：版本、模块、任务、内存

        Returns:
            dict: 包含 version, pm, ps, fs_state 的结果
        """
        return {
            'version': self.version(),
            'pm': self.pm(),
            'ps': self.ps(),
            'fs_state': self.fs_state(),
        }

    def summary(self):
        """返回会话摘要"""
        return self._session.summary()

    def print_history(self):
        """打印命令历史"""
        self._session.print_history()

    def close(self):
        """关闭连接"""
        if hasattr(self.link, 'close'):
            self.link.close()


#####################################################################################
# 模块入口（调试用）
#####################################################################################

if __name__ == '__main__':
    import argparse

    # 导入 GroundControlStation
    _driver_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _sim_path = os.path.join(_driver_dir, 'simulation')
    if _sim_path not in sys.path:
        sys.path.insert(0, _sim_path)
    from fake_ground_control_station import GroundControlStation

    parser = argparse.ArgumentParser(
        description="MAVLink CLI 协议工具 - 通过 CONSOLE 消息（msg_id=48）与无人机 CLI 交互")
    parser.add_argument("command", nargs="?", help="要执行的 CLI 命令（如 ls, version, mode stab）")
    parser.add_argument("-drone", required=False,
                        help="无人机 IP（默认 172.17.1.87）", type=str,
                        default="172.17.1.87")
    parser.add_argument("-drone_port", required=False,
                        help="无人机端口（默认 14551）", type=int, default=14551)
    parser.add_argument("-gcs_ip", required=False,
                        help="地面站 IP（默认 172.16.200.1）", type=str,
                        default="172.16.200.1")
    parser.add_argument("-gcs_port", required=False,
                        help="地面站端口（默认 14550）", type=int, default=14550)
    parser.add_argument("-sysid", required=False,
                        help="MAVLink 源系统 ID（默认 0）", type=int, default=0)
    parser.add_argument("-compid", required=False,
                        help="MAVLink 源组件 ID（默认 0）", type=int, default=0)
    parser.add_argument("-timeout", required=False,
                        help="命令超时时间（秒，默认 5）", type=float, default=5.0)

    args = parser.parse_args()

    # 建立连接
    gcs = GroundControlStation(
        local_ip=args.gcs_ip, local_port=args.gcs_port,
        drone_ip=args.drone, drone_port=args.drone_port)
    link = GCSCLILink(gcs, sys_id=args.sysid, comp_id=args.compid)
    print(f"CLI 已连接 -> 无人机 {args.drone}:{args.drone_port}")

    try:
        client = CLIClient(link, sys_id=args.sysid, comp_id=args.compid)

        if args.command:
            # 单次命令模式
            result = client.raw(args.command, timeout=args.timeout)
            result.print()
        else:
            # 交互模式
            print("MAVLink CLI 交互模式（输入 'exit' 退出, 'help' 查看命令列表）")
            while True:
                try:
                    cmd = input("CLI> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n退出。")
                    break

                if not cmd:
                    continue
                if cmd.lower() in ('exit', 'quit'):
                    print("退出 CLI。")
                    break
                if cmd.lower() == 'help':
                    print("可用命令: ls, cd, ps, pp, pm, version, mode, arm, "
                          "disarm, takeoff, flyto, bat, sheal, fs_state, "
                          "now, istate, smsg, dmsg, wifi, ...")
                    print("输入完整 CLI 命令直接执行。")
                    continue

                result = client.raw(cmd, timeout=args.timeout)
                result.print()
    finally:
        link.close()
