# -*- coding: utf-8 -*-
"""
屏幕录制工具 - 支持录屏并保存为 GIF

依赖库：
    - mss: 跨平台屏幕捕获库，负责获取屏幕截图
    - Pillow: 图像处理库，用于处理和保存 GIF

核心流程：
    1. start() 启动后台捕获线程，按指定 FPS 持续截取屏幕
    2. _capture_loop() 在独立线程中循环采集帧，存入 _frames 列表
    3. stop() 停止捕获线程，对帧列表进行压缩优化后保存为 GIF
    4. attach_gif_to_allure() 将 GIF 作为附件嵌入 Allure 测试报告

GIF 体积优化策略（防止过大导致报告加载缓慢）：
    - 分辨率限制：最大 1600x1200，超出按比例缩小
    - 帧数限制：最多 1500 帧，超出则均匀采样
    - 颜色压缩：调色板降为 64 色，减少存储空间
"""

import os
import time
import threading
from datetime import datetime
from typing import Optional, Tuple

import allure

# mss: 跨平台屏幕捕获，支持多显示器
try:
    import mss
except ImportError:
    mss = None

# Pillow: 图像处理，用于 GIF 编码
try:
    from PIL import Image
except ImportError:
    Image = None


# ============================================================================
# 全局共享截屏资源：所有 ScreenRecorder 实例共用一个 mss 实例 + 锁
# 避免多实例并发调用 mss.grab() 导致的 GDI 竞争
# ============================================================================
_screenshot_lock = threading.Lock()
_shared_sct = None
_shared_sct_monitor = None


def _get_shared_sct(monitor):
    """获取全局共享的 mss 实例，所有截屏操作串行化"""
    global _shared_sct, _shared_sct_monitor
    with _screenshot_lock:
        if _shared_sct is None:
            _shared_sct = mss.mss()
        _shared_sct_monitor = monitor
        return _shared_sct


class ScreenRecorder:
    """
    屏幕录制器，支持全屏或指定区域录制，输出 GIF 文件。

    核心属性：
        fps: 目标帧率（每秒采集帧数），影响 GIF 播放速度和文件大小
        output_dir: GIF 文件输出目录
        _frames: 采集的原始帧列表（每项为 PIL Image 对象）
        _recording: 标记当前是否处于录制状态
        _thread: 后台捕获线程句柄
        _interval: 两帧之间的采集间隔（秒），等于 1.0 / fps
        _monitor: mss 使用的屏幕区域定义字典

    使用示例：
        recorder = ScreenRecorder(fps=10, output_dir="logs/recordings")
        recorder.start()                      # 开始录制（全屏）
        # ... 执行测试操作 ...
        gif_path = recorder.stop("test.gif")  # 停止并保存
        recorder.attach_gif_to_allure(gif_path)  # 附加到 Allure 报告
    """

    def __init__(self, fps: int = 10, output_dir: str = "logs/recordings"):
        """
        初始化屏幕录制器。

        Args:
            fps: 每秒帧数，默认 10fps。值越高画面越流畅，但 GIF 体积越大。
            output_dir: GIF 文件保存目录，默认 "logs/recordings"。
                        目录不存在时会自动创建。
        """
        # 运行时检查依赖是否安装，避免录制到一半才报错
        if mss is None:
            raise ImportError("需要安装 mss 库: pip install mss")
        if Image is None:
            raise ImportError("需要安装 Pillow 库: pip install Pillow")

        self.fps = fps
        self.output_dir = output_dir
        self._frames: list[Image.Image] = []   # 采集的帧列表
        self._recording = False               # 是否正在录制
        self._thread: Optional[threading.Thread] = None   # 后台捕获线程
        self._interval = 1.0 / fps             # 帧采集间隔（秒）
        self._monitor: Optional[dict] = None   # mss 屏幕区域定义

        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)

    def _set_monitor(self, region: Optional[Tuple[int, int, int, int]] = None):
        """
        根据传入的区域参数设置 mss 监控区域。

        Args:
            region: 录制区域元组 (left, top, right, bottom)，单位为像素。
                    - 若为 None：录制主显示器（monitors[1]）
                    - 若指定：(left, top) 为左上角坐标，(right, bottom) 为右下角坐标

        Note:
            mss 的 monitor 字典格式为 {"left", "top", "width", "height")，
            因此需要将 (left, top, right, bottom) 转换为宽度和高度。
        """
        with mss.mss() as sct:
            if region:
                # 用户指定了区域，按指定坐标设置
                self._monitor = {
                    "left": region[0],
                    "top": region[1],
                    "width": region[2] - region[0],   # right - left
                    "height": region[3] - region[1]    # bottom - top
                }
            else:
                # 未指定区域则使用主显示器（monitors[1]，index 0 是全部显示器的复合区域）
                self._monitor = sct.monitors[1]

    def _capture_loop(self):
        """
        后台屏幕捕获循环（在独立线程中运行）。

        工作原理：
            - 所有 ScreenRecorder 实例共享同一个 mss.mss() 实例
            - 通过全局锁 _screenshot_lock 串行化所有截屏操作，避免 GDI 竞争
            - 将 BGRA 原始字节转换为 RGB PIL Image
            - 按 _interval 指定的间隔持续采集，直到 _recording 被置为 False

        GDI 异常处理：
            - mss 在 Windows 上可能因 GDI 资源竞争导致 GetDIBits() 失败
            - grab 失败时跳过本帧（sleep 补齐帧间隔），不重试不卡死
            - 跳过帧不影响 GIF 连续性（GIF 每帧独立，按帧间隔播放）
        """
        import sys
        sct = _get_shared_sct(self._monitor)
        while self._recording:
            start_time = time.time()

            # 截取指定区域的屏幕，返回 BGRA 格式的原始字节
            # grab 操作被全局锁保护，串行化所有 ScreenRecorder 的截屏请求
            screenshot = None
            try:
                with _screenshot_lock:
                    screenshot = sct.grab(self._monitor)
            except Exception as e:
                # grab 失败：跳过本帧，用 sleep 补齐帧间隔，保持帧率节奏
                print(f"[ScreenRecorder] grab 失败: {e}", file=sys.stderr)
                elapsed = time.time() - start_time
                sleep_time = self._interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
                continue

            # mss 返回的格式是 BGRA（字节顺序：蓝、绿、红、Alpha）
            # Image.frombytes 需要指定 raw 模式 "BGRX"（X 为占位符，忽略 Alpha）
            try:
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            except Exception as e:
                print(f"[ScreenRecorder] frombytes 失败: {e}", file=sys.stderr)
                elapsed = time.time() - start_time
                sleep_time = self._interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
                continue

            # 保存到帧列表，后续用于生成 GIF
            try:
                self._frames.append(img)
            except Exception as e:
                print(f"[ScreenRecorder] append 失败: {e}", file=sys.stderr)
                elapsed = time.time() - start_time
                sleep_time = self._interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
                continue

            # 控制实际采集帧率：每帧消耗的时间后，等待剩余时间
            # print(f"--------------------------------------{time.time()}")
            elapsed = time.time() - start_time
            sleep_time = self._interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)   # 精确控制采集间隔

        print("[ScreenRecorder] _capture_loop 正常退出（_recording=False）")

    def start(self, region: Optional[Tuple[int, int, int, int]] = None):
        """
        开始屏幕录制。

        行为：
            1. 设置录制区域（默认为全屏）
            2. 清空历史帧列表
            3. 启动后台捕获线程，开始循环采集屏幕

        Args:
            region: 可选，录制区域 (left, top, right, bottom)。
                    None 表示全屏录制。
                    示例：(100, 100, 800, 600) 录制左上角 (100,100) 到右下角 (800,600) 的区域

        Note:
            调用时如果已经在录制中（_recording=True），直接返回，不会重启。
        """
        if self._recording:
            return

        self._set_monitor(region)          # 配置监控区域
        self._frames = []                  # 清空旧帧
        self._recording = True             # 标记为录制状态
        self._thread = threading.Thread(
            target=self._capture_loop,    # 线程执行目标函数
            daemon=True                   # daemon 线程：主进程退出时自动终止
        )
        self._thread.start()

    def stop(self, filename: Optional[str] = None) -> str:
        """
        停止录制并保存为 GIF 文件。

        行为：
            1. 将 _recording 置为 False，通知捕获线程退出
            2. 等待捕获线程安全终止（最多 2 秒超时）
            3. 如果没有采集到任何帧，直接返回空字符串
            4. 对帧进行体积优化（分辨率、帧数、颜色压缩）
            5. 将帧列表保存为 GIF 文件

        Args:
            filename: 输出文件名。None 时自动使用时间戳生成文件名。

        Returns:
            生成的 GIF 文件完整路径，录制失败时返回空字符串。

        GIF 优化策略详解：
            1. 分辨率压缩：最大 1600x1200，超出按等比缩放
            2. 帧数采样：超过 1500 帧时均匀抽样到 1500 帧
            3. 颜色量化：Pillow ADAPTIVE 调色板降至 64 色
            4. 播放时长：每帧停留 duration=int(_interval * 1000) 毫秒
        """
        if not self._recording:
            return ""

        # 通知线程停止录制
        self._recording = False
        if self._thread:
            self._thread.join(timeout=2)   # 最多等待 2 秒让线程安全退出

        if not self._frames:
            return ""

        # 自动生成文件名（无指定时）
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"recording_{timestamp}.gif"

        filepath = os.path.join(self.output_dir, filename)
        os.makedirs(self.output_dir, exist_ok=True)

        # 仅在有≥2帧时生成 GIF（单帧无法生成动画）
        if len(self._frames) > 1:
            frame = self._frames[0]

            # ========== 体积优化 ==========
            # 限制参数：分辨率、帧数、颜色数
            max_width = 1600
            max_height = 1200
            max_frames = 2000
            max_colors = 128

            # 1. 分辨率限制：超出最大尺寸时按等比缩放
            if frame.width > max_width or frame.height > max_height:
                ratio = min(max_width / frame.width, max_height / frame.height)
                if ratio < 1:
                    new_size = (int(frame.width * ratio), int(frame.height * ratio))
                    self._frames = [f.resize(new_size, Image.LANCZOS) for f in self._frames]

            # 2. 帧数限制：超过上限时均匀采样
            #    step = 总帧数 / 最大帧数，每隔 step 帧取一帧
            if len(self._frames) > max_frames:
                
                step = len(self._frames) / max_frames
                self._frames = [self._frames[int(i * step)] for i in range(max_frames)]
            # print(f"总共截图数量{len(self._frames)}")
            # 3. 颜色压缩：转换为调色板模式，降低颜色深度
            #    ADAPTIVE 策略会自动选取最具代表性的 64 种颜色
            self._frames = [
                f.convert("P", palette=Image.ADAPTIVE, colors=max_colors)
                for f in self._frames
            ]

            # ========== 保存 GIF ==========
            # save_all=True: 保存为多帧动画
            # append_images: 要附加的帧（除第一帧外的所有帧）
            # duration: 每帧停留毫秒数
            # loop=0: 无限循环播放
            self._frames[0].save(
                filepath,
                save_all=True,
                append_images=self._frames[1:],
                duration=int(self._interval * 1000),
                loop=0,
                optimize=False
            )

        # 清空帧列表，释放内存
        self._frames = []
        return filepath

    def is_recording(self) -> bool:
        """
        查询当前是否正在录制。

        Returns:
            True 表示正在录制（start() 已调用且 stop() 未调用或仍在采集中）
            False 表示已停止或未开始
        """
        return self._recording

    def attach_gif_to_allure(self, filepath: str, name: str = "录屏"):
        """
        将 GIF 文件作为附件添加到 Allure 测试报告。

        用于在测试报告中直观展示测试执行过程。

        Args:
            filepath: GIF 文件的完整路径
            name: Allure 报告中显示的附件名称

        行为：
            - 文件存在：将 GIF 二进制数据作为 attachment_type.GIF 附加
            - 文件不存在：附加一段说明文本（而不是图片），避免报告报错
        """
        if os.path.exists(filepath):
            with open(filepath, "rb") as f:
                gif_data = f.read()
            allure.attach(
                gif_data,
                name=name,
                attachment_type=allure.attachment_type.GIF
            )
        else:
            # 文件不存在时附加文本说明，避免 Allure 报告因缺失附件而异常
            allure.attach(
                f"录屏文件不存在：{filepath}",
                name=f"{name}（不存在）",
                attachment_type=allure.attachment_type.TEXT
            )

    @property
    def frame_count(self) -> int:
        """
        获取当前已采集的帧数量。

        Returns:
            _frames 列表中的帧数量，即已采集但尚未保存的帧数
        """
        return len(self._frames)


def record_screen_context(recorder: ScreenRecorder, filename: Optional[str] = None):
    """
    创建录屏上下文管理器（用于 with 语句）。

    上下文管理器会在进入时自动启动录制，退出时自动停止并保存。
    适合用于录制某个特定代码块的执行过程。

    用法示例：
        recorder = ScreenRecorder()
        with record_screen_context(recorder, "login.gif"):
            login_button.click()
            password_input.set_text("password123")
            submit_button.click()

    Args:
        recorder: 已创建的 ScreenRecorder 实例
        filename: GIF 文件名，None 时使用默认命名

    Returns:
        _RecordContext 上下文管理器实例
    """
    return _RecordContext(recorder, filename)


class _RecordContext:
    """
    录屏上下文管理器的内部实现类。

    实现了 __enter__ 和 __exit__ 魔术方法，使其支持 with 语句。
    用户不应直接实例化此类，应通过 record_screen_context() 工厂函数创建。
    """

    def __init__(self, recorder: ScreenRecorder, filename: Optional[str] = None):
        self.recorder = recorder
        self.filename = filename

    def __enter__(self):
        """进入 with 块时：启动屏幕录制"""
        self.recorder.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        退出 with 块时：停止录制并保存 GIF。

        Args:
            exc_type: 异常类型（若有），None 表示正常退出
            exc_val: 异常值（若有），None 表示正常退出
            exc_tb: 异常回溯（若有），None 表示正常退出

        Returns:
            False：不会屏蔽异常，异常会继续向外传播

        Note:
            无论测试成功还是失败（含异常），都会保存录屏。
            通过返回 False 保证异常能够正常传播。
        """
        filepath = self.recorder.stop(self.filename)
        if filepath:
            print(f"录屏已保存: {filepath}")
        return False