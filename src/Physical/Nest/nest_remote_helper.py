# coding: utf-8
"""
机巢远程命令执行工具

功能:
    - 通过 ssh / 调试串口 / adb 三种通道在机巢 Linux 控制台执行命令
    - 三通道语义等价 (需求文档 一、串口配置功能)

设计原则:
    本工具类不内置任何环境默认值 (IP/端口/账号/密码), 全部由调用方传入。
    conftest.py 的 *_session fixture 从 config.json 读取后注入,
    保证 config.json 是环境参数的唯一真相源。

    本工具不依赖 paramiko (requirements.txt 未列), 改用 subprocess + 系统原生
    ssh / adb 客户端, Windows 10+ 自带 OpenSSH, adb 由平台工具提供。
"""
import shlex
import subprocess
from typing import Optional, Tuple

from utils.logger import log_manager


class NestRemoteHelper:
    """
    机巢远程命令执行助手

    通过 ssh / adb / 调试串口 三种通道执行命令。
    构造参数全部必填, 由 conftest 从 config.json 注入。
    """

    SSH_TIMEOUT_DEFAULT = 15

    def __init__(
        self,
        channel: str,
        nest_ip: Optional[str] = None,
        ssh_port: int = 22,
        ssh_user: Optional[str] = None,
        ssh_passwd: Optional[str] = None,
        adb_serial: Optional[str] = None,
        console_session: Optional[object] = None,
    ):
        """
        Args:
            channel: 通道类型, "ssh" / "adb" / "console" 三选一
            nest_ip: 机巢 IP (ssh 通道必填)
            ssh_port: ssh 端口 (默认 22)
            ssh_user: ssh 用户 (ssh 通道必填)
            ssh_passwd: ssh 密码 (ssh 通道必填; 当前实现不交互输入, 走系统 ssh-agent 或 key)
            adb_serial: adb 设备序列号 (adb 通道必填)
            console_session: 已连接的调试串口对象 (console 通道必填, 需提供 write/readline 接口)
        """
        if channel not in ("ssh", "adb", "console"):
            raise ValueError(f"channel 必须为 ssh/adb/console, 实际 {channel!r}")
        self.channel = channel
        self.nest_ip = nest_ip
        self.ssh_port = ssh_port
        self.ssh_user = ssh_user
        self.ssh_passwd = ssh_passwd
        self.adb_serial = adb_serial
        self.console_session = console_session

        if channel == "ssh" and not (nest_ip and ssh_user):
            raise ValueError("ssh 通道需提供 nest_ip + ssh_user")
        if channel == "adb" and not adb_serial:
            raise ValueError("adb 通道需提供 adb_serial")
        if channel == "console" and console_session is None:
            raise ValueError("console 通道需提供 console_session")

    def exec_cmd(self, cmd: str, timeout: Optional[int] = None) -> str:
        """
        在机巢执行 shell 命令, 返回 stdout 字符串

        Args:
            cmd: 要执行的 shell 命令 (如 "uname -a")
            timeout: 超时秒数 (None 用默认)
        Returns:
            stdout 字符串 (尾空白被 strip)
        Raises:
            subprocess.CalledProcessError: 退出码非 0
            subprocess.TimeoutExpired: 超时
        """
        if self.channel == "ssh":
            return self._exec_ssh(cmd, timeout)
        if self.channel == "adb":
            return self._exec_adb(cmd, timeout)
        return self._exec_console(cmd, timeout)

    def exec_cmd_quiet(self, cmd: str, timeout: Optional[int] = None) -> Tuple[int, str]:
        """exec_cmd 的非抛错版本: 返回 (returncode, stdout) 元组, 不抛 CalledProcessError"""
        try:
            out = self.exec_cmd(cmd, timeout)
            return 0, out
        except subprocess.CalledProcessError as e:
            return e.returncode, (e.stdout or "")
        except subprocess.TimeoutExpired:
            return 124, ""

    def _exec_ssh(self, cmd: str, timeout: Optional[int]) -> str:
        to = timeout or self.SSH_TIMEOUT_DEFAULT
        # 用 BatchMode=yes 避免交互密码挂死; 真机应预配 key, 密码场景由调用方自行处理
        argv = [
            "ssh",
            "-p", str(self.ssh_port),
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{self.ssh_user}@{self.nest_ip}",
            cmd,
        ]
        log_manager.logger.info(f"[Nest-SSH] {self.nest_ip}:{self.ssh_port} $ {cmd}")
        proc = subprocess.run(
            argv,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
            timeout=to,
            check=True,
        )
        out = (proc.stdout or "").strip()
        log_manager.logger.debug(f"[Nest-SSH] stdout: {out[:200]}")
        return out

    def _exec_adb(self, cmd: str, timeout: Optional[int]) -> str:
        to = timeout or self.SSH_TIMEOUT_DEFAULT
        argv = ["adb", "-s", self.adb_serial, "shell", cmd]
        log_manager.logger.info(f"[Nest-ADB] {self.adb_serial} $ {cmd}")
        proc = subprocess.run(
            argv,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
            timeout=to,
            check=True,
        )
        out = (proc.stdout or "").strip()
        log_manager.logger.debug(f"[Nest-ADB] stdout: {out[:200]}")
        return out

    def _exec_console(self, cmd: str, timeout: Optional[int]) -> str:
        """调试串口通道: 通过 console_session.write/readline 收集输出

        console_session 须提供 write(line: str) / readline() / read_until(marker, timeout) 接口。
        """
        if not hasattr(self.console_session, "write"):
            raise NotImplementedError(
                "console_session 未实现 write/readline — 请用 SerialPortController 包装"
            )
        log_manager.logger.info(f"[Nest-Console] $ {cmd}")
        self.console_session.write((cmd + "\n").encode())
        marker = "# "  # Buildroot root prompt
        if hasattr(self.console_session, "read_until"):
            raw = self.console_session.read_until(marker.encode(), timeout=timeout or 5)
        else:
            raw = b""
            for _ in range(50):
                line = self.console_session.readline()
                if not line:
                    break
                raw += line
                if marker.encode() in line:
                    break
        try:
            text = raw.decode("utf-8", errors="replace")
        except AttributeError:
            text = str(raw)
        # 去掉回显命令本身 + 末尾 prompt
        lines = [ln for ln in text.splitlines() if ln.strip() and ln.strip() != cmd.strip() and not ln.strip().endswith("#")]
        return "\n".join(lines).strip()
