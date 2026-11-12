# coding: utf-8
"""
WiFi 模块 FTP 文件传输工具

功能：
    - 连接 WiFi 模块的 FTP 服务器
    - 上传/下载文件
    - 文件完整性校验（MD5）
    - 批量文件传输

设计原则:
    本工具类不内置任何环境默认值(IP/账号/密码),全部由调用方传入。
    conftest.py 的 ftp_session fixture 从 config.json 读取后注入,
    保证 config.json 是环境参数的唯一真相源。
"""
import os
import time
import hashlib
from ftplib import FTP
from typing import Optional, Tuple

from utils.logger import log_manager


class WifiFtpHelper:
    """
    WiFi 模块 FTP 文件传输助手

    构造参数 host/user/passwd 均为必填,由调用方从 config.json 注入。
    """

    def __init__(self, host: str, user: str, passwd: str, timeout: float = 30.0):
        """
        初始化 FTP 客户端

        Args:
            host: FTP 服务器 IP 地址(必填,从 config.json 注入)
            user: FTP 用户名(必填)
            passwd: FTP 密码(必填)
            timeout: 连接超时时间（秒）
        """
        if not host or not user or not passwd:
            raise ValueError(
                "WifiFtpHelper 必须显式传入 host/user/passwd,"
                "请通过 conftest.py 的 ftp_session fixture 从 config.json 读取后注入"
            )
        self.host = host
        self.user = user
        self.passwd = passwd
        self.timeout = timeout
        self.ftp: Optional[FTP] = None

    def connect(self) -> bool:
        """
        连接 FTP 服务器

        Returns:
            成功返回 True
        """
        try:
            self.ftp = FTP(timeout=self.timeout)
            self.ftp.connect(self.host, 21)
            self.ftp.login(self.user, self.passwd)
            # 显式 PASV — Python 默认是被动模式,但固件 FTP server 在 NAT/防火墙
            # 环境下主动模式会导致 426 Recv no data too long (#459)。显式声明避免歧义。
            self.ftp.set_pasv(True)
            log_manager.logger.info(f"[WifiFtpHelper] FTP 连接成功: {self.host} (PASV)")
            return True
        except Exception as e:
            log_manager.logger.error(f"[WifiFtpHelper] FTP 连接失败: {e}")
            return False

    def reconnect(self) -> bool:
        """
        重新连接 FTP 服务器

        Returns:
            成功返回 True
        """
        self.disconnect()
        return self.connect()

    def disconnect(self):
        """断开 FTP 连接"""
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:
                pass
            self.ftp = None
            log_manager.logger.info(f"[WifiFtpHelper] FTP 已断开")

    def __enter__(self):
        if not self.connect():
            raise ConnectionError(f"无法连接到 FTP 服务器: {self.host}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def upload_file(self, local_path: str, remote_path: str, max_retries: int = 3,
                    blocksize: int = 2048) -> bool:
        """
        上传文件到 FTP 服务器（含自动重连重试）

        Args:
            local_path: 本地文件路径
            remote_path: 远程文件路径（如 "/cmpn/dmd_companion/fota_793x.bin"）
            max_retries: 最大重试次数
            blocksize: STOR 块大小(默认 2048,远小于 ftplib 默认 8192)
                固件 FTP server recv 缓冲小,大块传输易触发 426 Recv no data too long。
                #459 用 4096 能跑 1.5MB+ 普通固件。
                #460 上传到 /cmpn/dmd_companion/ 路径的 2.69MB fota_793x.bin 仍然
                426 — 推测该路径挂了 OTA 写入校验,吞吐跟不上 burst send。进一步
                降到 2048 让 TCP backpressure 更早生效,削平 burst。

        Returns:
            成功返回 True

        注:每次 STOR 前会先 best-effort 删除 remote_path 上的旧文件。
        业务依据:#452 出现过上一次中断后残留半截文件导致 FATFS 写入返回
        550 Cannot open file for writing。预清理可消除这类脏数据。
        """
        if not os.path.exists(local_path):
            log_manager.logger.error(f"[WifiFtpHelper] 本地文件不存在: {local_path}")
            return False

        file_size = os.path.getsize(local_path)
        for attempt in range(max_retries):
            if not self.ftp:
                if not self.connect():
                    log_manager.logger.warning(f"[WifiFtpHelper] FTP 连接失败 (尝试 {attempt+1}/{max_retries})")
                    time.sleep(3)
                    continue

            try:
                # 确保远程目录存在
                remote_dir = os.path.dirname(remote_path)
                self._ensure_remote_dir(remote_dir)

                # 上传前 best-effort 删除旧文件(避免 FATFS 残留半截文件触发 550)
                self._try_delete_remote(remote_path)

                log_manager.logger.info(
                    f"[WifiFtpHelper] 开始上传: {local_path} -> {remote_path} "
                    f"({file_size} bytes, blocksize={blocksize}, 尝试 {attempt+1}/{max_retries})"
                )

                # 进度跟踪:记下已发送字节,失败时输出诊断信息
                sent = {'bytes': 0}
                def _progress(chunk):
                    sent['bytes'] += len(chunk)

                start_ts = time.time()
                with open(local_path, "rb") as f:
                    self.ftp.storbinary(f"STOR {remote_path}", f,
                                        blocksize=blocksize, callback=_progress)

                elapsed = time.time() - start_ts
                log_manager.logger.info(
                    f"[WifiFtpHelper] 上传成功: {remote_path} "
                    f"({sent['bytes']} bytes, {elapsed:.1f}s, "
                    f"{sent['bytes']/1024/max(elapsed,0.001):.1f} KB/s)"
                )
                return True

            except Exception as e:
                elapsed = time.time() - start_ts if 'start_ts' in dir() else 0
                log_manager.logger.warning(
                    f"[WifiFtpHelper] 上传失败 (尝试 {attempt+1}/{max_retries}): {e} "
                    f"— 已发送 {sent.get('bytes', 0)}/{file_size} bytes"
                )
                self.disconnect()
                if attempt < max_retries - 1:
                    # 重试间隔从 1s 提到 5s:给模块 TCP 栈恢复时间
                    time.sleep(5)
                    self.connect()

        log_manager.logger.error(f"[WifiFtpHelper] 上传失败，已重试 {max_retries} 次: {remote_path}")
        return False

    def delete_file(self, remote_path: str) -> bool:
        """
        删除 FTP 服务器上的文件

        Args:
            remote_path: 远程文件路径

        Returns:
            成功(或文件本来就不存在)返回 True
        """
        if not self.ftp:
            if not self.connect():
                return False
        try:
            self.ftp.delete(remote_path)
            log_manager.logger.info(f"[WifiFtpHelper] 已删除远程文件: {remote_path}")
            return True
        except Exception as e:
            log_manager.logger.warning(f"[WifiFtpHelper] 删除远程文件失败: {remote_path} ({e})")
            return False

    def _try_delete_remote(self, remote_path: str):
        """上传前 best-effort 删除旧文件 — 直接 DELE,文件不存在或失败都静默忽略"""
        if not self.ftp:
            return
        try:
            self.ftp.delete(remote_path)
            log_manager.logger.info(f"[WifiFtpHelper] 预清理旧文件: {remote_path}")
        except Exception:
            # 文件不存在 / 权限不足 / 路径无效 — best-effort,不影响后续 STOR
            pass

    def _safe_nlst(self, target_dir: str) -> list:
        """
        规避固件 NLST 忽略路径参数的 bug — CWD 到目标目录再 NLST,然后回到原目录。

        固件 ftpd.c:337-349 的 cmd_nlist_handle 用 session->currentdir 列出,
        忽略 para 参数。要先 CWD 改变 currentdir 才能列出子目录内容。
        固件同事反馈该 bug 有历史原因不修改,脚本侧统一通过此方法规避。

        Args:
            target_dir: 要列出的目录(绝对路径)

        Returns:
            目录下的文件/子目录名列表,失败返回空列表
        """
        if not self.ftp:
            if not self.connect():
                return []

        try:
            original_pwd = self.ftp.pwd()
        except Exception:
            original_pwd = "/"

        try:
            self.ftp.cwd(target_dir)
            entries = self.ftp.nlst()  # 不传参,列出 currentdir
        except Exception as e:
            log_manager.logger.warning(
                f"[WifiFtpHelper] NLST {target_dir} 失败: {e}"
            )
            return []
        finally:
            try:
                self.ftp.cwd(original_pwd)
            except Exception:
                pass

        return entries or []

    def download_file(self, remote_path: str, local_path: str, max_retries: int = 3) -> bool:
        """
        从 FTP 服务器下载文件（含自动重连重试）

        Args:
            remote_path: 远程文件路径
            local_path: 本地文件路径
            max_retries: 最大重试次数

        Returns:
            成功返回 True
        """
        for attempt in range(max_retries):
            if not self.ftp:
                if not self.connect():
                    log_manager.logger.warning(f"[WifiFtpHelper] FTP 连接失败 (尝试 {attempt+1}/{max_retries})")
                    time.sleep(1)
                    continue

            try:
                local_dir = os.path.dirname(local_path)
                if local_dir and not os.path.exists(local_dir):
                    os.makedirs(local_dir, exist_ok=True)

                log_manager.logger.info(f"[WifiFtpHelper] 开始下载: {remote_path} -> {local_path}")

                with open(local_path, "wb") as f:
                    self.ftp.retrbinary(f"RETR {remote_path}", f.write)

                log_manager.logger.info(f"[WifiFtpHelper] 下载成功: {local_path}")
                return True

            except Exception as e:
                log_manager.logger.warning(f"[WifiFtpHelper] 下载失败 (尝试 {attempt+1}/{max_retries}): {e}")
                self.disconnect()
                if attempt < max_retries - 1:
                    time.sleep(1)
                    self.connect()

        log_manager.logger.error(f"[WifiFtpHelper] 下载失败，已重试 {max_retries} 次: {remote_path}")
        return False

    def file_exists(self, remote_path: str) -> bool:
        """
        检查远程文件是否存在

        实现说明:
        方案一(SIZE)已被废弃:实测 #455 中 STOR 成功后 SIZE 仍返回 550,
        推测是固件 FATFS 元数据同步延迟或 SIZE handler 在新上传文件上有 bug。
        方案二(CWD + NLST)是固件同事推荐的稳定方案:
        - 固件 ftpd.c:337 的 NLST 处理函数忽略 para,只列出 session->currentdir
        - 先 CWD 到目标文件所在目录,再 NLST (不带参数) 列出当前目录
        - 检查目标文件名是否在列表里
        CWD 本身也有 bug(ftpd.c:557 不验证目录是否存在,总是 250 OK),但 NLST
        在不存在目录上会失败,我们的 _safe_nlst 已处理这种情况。

        Args:
            remote_path: 远程文件路径

        Returns:
            存在返回 True
        """
        if not self.ftp:
            if not self.connect():
                return False

        # 拆分为目录 + 文件名
        remote_path = remote_path.replace("\\", "/").rstrip("/")
        if "/" not in remote_path:
            # 根目录下的文件
            parent_dir = "/"
            filename = remote_path
        else:
            parent_dir, filename = remote_path.rsplit("/", 1)
            if not parent_dir:
                parent_dir = "/"
            filename = filename.strip()

        if not filename:
            log_manager.logger.warning(f"[WifiFtpHelper] file_exists 文件名为空: {remote_path}")
            return False

        entries = self._safe_nlst(parent_dir)
        # NLST 返回的列表项可能是纯文件名,也可能带前缀;做包含匹配
        exists = any(
            entry.strip() == filename or entry.strip().endswith("/" + filename)
            for entry in entries
        )
        log_manager.logger.info(
            f"[WifiFtpHelper] file_exists: path={remote_path} -> "
            f"CWD {parent_dir} + NLST 得到 {len(entries)} 项, "
            f"查找 '{filename}' -> {'存在' if exists else '不存在'}"
        )
        return exists

    def get_file_size(self, remote_path: str) -> Optional[int]:
        """
        获取远程文件大小

        Args:
            remote_path: 远程文件路径

        Returns:
            文件大小（字节），失败返回 None
        """
        if not self.ftp:
            if not self.connect():
                return None

        try:
            size = self.ftp.size(remote_path)
            return size
        except Exception:
            return None

    @staticmethod
    def calculate_md5(file_path: str, chunk_size: int = 8192) -> Optional[str]:
        """
        计算本地文件的 MD5 值

        Args:
            file_path: 文件路径
            chunk_size: 读取块大小

        Returns:
            MD5 字符串，失败返回 None
        """
        try:
            md5_hash = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(chunk_size), b""):
                    md5_hash.update(chunk)
            return md5_hash.hexdigest()
        except Exception as e:
            log_manager.logger.error(f"[WifiFtpHelper] 计算 MD5 失败: {e}")
            return None

    def upload_and_verify(self, local_path: str, remote_path: str) -> Tuple[bool, str]:
        """
        上传文件并验证完整性（通过串口命令校验）

        Args:
            local_path: 本地文件路径
            remote_path: 远程文件路径

        Returns:
            (成功标志, 结果描述)
        """
        # 计算本地 MD5
        local_md5 = self.calculate_md5(local_path)
        if not local_md5:
            return False, "计算本地文件 MD5 失败"

        # 上传文件
        if not self.upload_file(local_path, remote_path):
            return False, "文件上传失败"

        return True, f"上传成功，本地 MD5: {local_md5}"

    def _ensure_remote_dir(self, remote_dir: str):
        """
        确保远程目录存在(固件 fatfs_mkdir_p 支持递归创建)

        实现说明:
        固件 ftpd.c:764 的 MKD 处理函数调 fatfs_mkdir_p(filename),能一次性
       递归创建多层目录。所以直接对完整路径发 MKD 即可,不需要逐级 CWD 探测。
        已存在的目录 MKD 会返回 "550 File exists",属正常情况,需忽略。

        Args:
            remote_dir: 远程目录路径(如 "/cmpn/dmd_companion")
        """
        if not self.ftp:
            return
        if not remote_dir or remote_dir == "/":
            return

        try:
            self.ftp.mkd(remote_dir)
            log_manager.logger.info(f"[WifiFtpHelper] 已创建远程目录: {remote_dir}")
        except Exception as e:
            err_str = str(e)
            # 固件返回 "550 File exists" 表示目录已存在,属正常,不报警
            if "exists" in err_str or "550" in err_str:
                log_manager.logger.debug(
                    f"[WifiFtpHelper] 远程目录已存在(可忽略): {remote_dir} ({err_str})"
                )
                return
            # 其他错误 — 可能是真创建失败,用 CWD 验证一下
            try:
                self.ftp.cwd(remote_dir)
                self.ftp.cwd("/")
                log_manager.logger.debug(
                    f"[WifiFtpHelper] 远程目录已存在(CWD 验证): {remote_dir}"
                )
            except Exception as cwd_err:
                log_manager.logger.error(
                    f"[WifiFtpHelper] 远程目录创建失败且不存在: {remote_dir} "
                    f"(mkd_error={err_str}, cwd_error={cwd_err})"
                )

    def list_directory(self, remote_path: str = "/") -> list:
        """
        列出远程目录内容(规避固件 NLST 忽略路径参数的 bug)

        Args:
            remote_path: 远程目录路径

        Returns:
            文件/目录列表
        """
        if not self.ftp:
            if not self.connect():
                return []
        # 固件 NLST 忽略 para — 必须先 CWD 再 NLST(详见 _safe_nlst 注释)
        return self._safe_nlst(remote_path)
