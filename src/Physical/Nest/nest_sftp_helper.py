# coding: utf-8 -*-
"""
机巢 sftp 文件传输工具

功能:
    - 通过 sftp 协议在机巢上传/下载文件
    - 文件完整性校验 (MD5)
    - 列出远端目录

设计原则:
    本工具类不内置任何环境默认值, 全部由调用方传入。
    conftest.py 的 sftp_session fixture 从 config.json 读取后注入。
    依赖系统 sftp 客户端 (Windows 10+ 自带), 不引入第三方库。
"""
import hashlib
import os
import subprocess
import tempfile
from typing import List, Optional

from utils.logger import log_manager


class NestSftpHelper:
    """
    机巢 sftp 文件传输助手

    构造参数 host/user/passwd 必填, 由 conftest 从 config.json 注入。
    """

    def __init__(self, host: str, user: str, passwd: str, port: int = 22, timeout: int = 30):
        if not host or not user or not passwd:
            raise ValueError(
                "NestSftpHelper 必须显式传入 host/user/passwd,"
                "请通过 conftest.py 的 sftp_session fixture 从 config.json 读取后注入"
            )
        self.host = host
        self.user = user
        self.passwd = passwd
        self.port = port
        self.timeout = timeout

    def _base_argv(self) -> List[str]:
        return [
            "sftp",
            "-P", str(self.port),
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{self.user}@{self.host}",
        ]

    def _run_batch(self, batch_cmds: List[str]) -> str:
        """执行一组 sftp 交互命令 (put/get/ls/rm), 返回 stdout 合并"""
        script = "\n".join(batch_cmds) + "\nbye\n"
        argv = self._base_argv()
        log_manager.logger.info(f"[Nest-SFTP] {self.host}:{self.port} batch: {batch_cmds}")
        proc = subprocess.run(
            argv,
            input=script,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=True,
        )
        return proc.stdout or ""

    def put(self, local: str, remote: str) -> bool:
        """上传本地文件到远端"""
        if not os.path.isfile(local):
            raise FileNotFoundError(f"本地文件不存在: {local}")
        self._run_batch([f"put {local} {remote}"])
        log_manager.logger.info(f"[Nest-SFTP] put {local} -> {remote} OK")
        return True

    def get(self, remote: str, local: str) -> bool:
        """下载远端文件到本地"""
        self._run_batch([f"get {remote} {local}"])
        if not os.path.isfile(local):
            raise RuntimeError(f"sftp get 后本地文件不存在: {local}")
        log_manager.logger.info(f"[Nest-SFTP] get {remote} -> {local} OK")
        return True

    def list_dir(self, remote_dir: str) -> List[str]:
        """列远端目录, 返回文件名列表 (不含 . 与 ..)"""
        out = self._run_batch([f"ls {remote_dir}"])
        names = []
        for ln in out.splitlines():
            ln = ln.strip()
            if not ln or ln.endswith(f"{remote_dir}"):
                continue
            # sftp ls 默认输出远端完整路径, 取末段文件名
            names.append(os.path.basename(ln))
        return [n for n in names if n]

    def remove(self, remote: str) -> bool:
        """删远端文件 (teardown 用)"""
        self._run_batch([f"rm {remote}"])
        log_manager.logger.info(f"[Nest-SFTP] rm {remote} OK")
        return True

    def md5_remote(self, remote: str, ssh_helper) -> Optional[str]:
        """通过 ssh_helper 在远端算 md5 (机巢 Buildroot 默认有 md5sum)"""
        code, out = ssh_helper.exec_cmd_quiet(f"md5sum {remote}")
        if code != 0 or not out:
            return None
        return out.split()[0]

    @staticmethod
    def md5_local(local: str) -> str:
        h = hashlib.md5()
        with open(local, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def verify_roundtrip(self, local: str, remote: str, ssh_helper) -> bool:
        """上传 + 回下 + md5 比对 + 清理"""
        self.put(local, remote)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
        tmp.close()
        try:
            self.get(remote, tmp.name)
            md5_local = self.md5_local(local)
            md5_remote = self.md5_remote(remote, ssh_helper)
            md5_back = self.md5_local(tmp.name)
            ok = (md5_local == md5_remote == md5_back)
            log_manager.logger.info(
                f"[Nest-SFTP] md5 local={md5_local} remote={md5_remote} back={md5_back} -> {'OK' if ok else 'FAIL'}"
            )
            return ok
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def disconnect(self):
        """sftp 无连接池, 这里仅记日志保持 fixture API 对称"""
        log_manager.logger.info(f"[Nest-SFTP] disconnect {self.host}")
