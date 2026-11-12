import io
import logging
import os
import sys
from datetime import datetime

import allure

# 强制使用 UTF-8 编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


class LogManager:
    def __init__(self, log_dir="logs", log_filename=None, log_level=logging.INFO):
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)

        # 使用时间戳命名，避免覆盖历史日志
        if log_filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.log_filename = f"test_log_{timestamp}.log"
        else:
            self.log_filename = log_filename

        self.log_path = os.path.join(self.log_dir, self.log_filename)

        log_format = (
            "%(asctime)s - %(levelname)s - "
            "%(filename)s - [%(funcName)s] - "
            "%(message)s"
        )
        datefmt = "%Y-%m-%d %H:%M:%S"

        self.logger = logging.getLogger("CustomLogger")
        self.logger.setLevel(log_level)
        self.logger.propagate = False  

        # 关键修复点：防止重复绑定 handler
        # 文件输出 + 控制台输出（带时间戳，便于 Jenkins 构建日志查看）
        if not self.logger.handlers:
            # 文件输出（使用 'a' 模式追加，因为文件名已带时间戳）
            file_handler = logging.FileHandler(
                self.log_path,
                mode='a',
                encoding="utf-8"
            )
            file_handler.setLevel(log_level)
            file_handler.setFormatter(logging.Formatter(log_format, datefmt))
            self.logger.addHandler(file_handler)

            # 控制台输出（带时间戳，便于 Jenkins 构建日志查看）
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(log_level)
            console_handler.setFormatter(logging.Formatter(log_format, datefmt))
            self.logger.addHandler(console_handler)

    def get_logger(self):
        return self.logger

    def get_log_offset(self):
        """返回当前日志文件的末尾字节偏移量，用于增量读取"""
        if os.path.exists(self.log_path):
            return os.path.getsize(self.log_path)
        return 0

    def attach_log_to_allure(self, name="测试日志", start_offset=0):
        """将日志文件从 start_offset 开始的内容附加到 Allure 报告中"""
        if os.path.exists(self.log_path):
            with open(self.log_path, "r", encoding="utf-8") as f:
                if start_offset > 0:
                    f.seek(start_offset)
                log_content = f.read()
            allure.attach(log_content, name=name, attachment_type=allure.attachment_type.TEXT)
        else:
            allure.attach(f"日志文件不存在：{self.log_path}", name=name, attachment_type=allure.attachment_type.TEXT)

    def log_and_attach(self, body, name="", level=logging.INFO):
        """同时将信息打印到日志文件并附加到 Allure 报告"""
        if name:
            # 标题独占一行，正文换行起始（CLI 回显等长正文与标题混排不可读）
            self.logger.log(level, f"[{name}]\n{body}")
        else:
            self.logger.log(level, str(body))
        allure.attach(str(body), name=name, attachment_type=allure.attachment_type.TEXT)


log_manager = LogManager()
logger = log_manager.get_logger()


def log_and_attach(body, name="", level=logging.INFO):
    """模块级便捷函数：同时打印日志并附加到 Allure 报告"""
    log_manager.log_and_attach(body, name=name, level=level)
