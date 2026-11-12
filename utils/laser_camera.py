#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
激光光斑相机检测 — USB 相机取图 + 绿/蓝激光光斑识别

供 X1 激光测试（test_mavlink_laser_blink.py）做点亮/熄灭的客观视觉断言；
配套手动调参预览工具 debug_camera_laser.py（不入库）。

检测原理（激光打在墙面/幕布上，光斑 = 小而亮的饱和色块）：
    BGR→HSV → 按颜色 inRange 掩码 → 形态学开运算去噪 → 最大轮廓
    → moments 质心；found = 轮廓面积 ≥ MIN_SPOT_AREA_PX

色相标度注意：OpenCV 的 H∈[0,179]（绿≈60，蓝≈115）；calibration_scan
测试里 iCAT 的 120/240 是分析仪自己的标度，两者勿混用。
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


# ============================================================================
# 检测参数（阈值调参入口，配合 debug_camera_laser.py 实测校准）
# ============================================================================

# HSV 掩码上下界 (H, S, V)，H 用 OpenCV 0-179 标度
HSV_RANGES = {
    "green": ((45, 80, 200), (75, 255, 255)),
    "blue": ((100, 80, 200), (130, 255, 255)),
}

MIN_SPOT_AREA_PX = 6        # 光斑最小轮廓面积（px²），低于视为噪点
FLUSH_FRAMES = 5            # 取图前连读帧数（冲掉缓冲区里的旧画面）
MORPH_KERNEL_SIZE = 3       # 开运算核大小

SPOT_COLOR_BGR = {"green": (0, 255, 0), "blue": (255, 0, 0)}    # 标注用 BGR


@dataclass
class SpotResult:
    """单个颜色的激光光斑检测结果"""
    color: str                                   # "green" / "blue"
    found: bool                                  # 是否检出有效光斑（面积达阈值）
    centroid: Optional[Tuple[float, float]]      # 光斑质心 (x, y)，未检出为 None
    area_px: float                               # 最大轮廓面积（px²），无轮廓为 0
    pixel_count: int                             # 掩码命中像素总数（含未成轮廓的噪声）


def find_camera_index(name_substring):
    """按设备名（不区分大小写子串）解析 DirectShow 相机 index

    设备枚举顺序会随插拔/驱动变化漂移（2026-09-17 实锤：FF-Camera 从
    index 1 漂到 index 0，硬编码 index 开到了 Integrated Camera），需要
    指定相机时必须按名字解析。依赖 pygrabber（DirectShow 设备名枚举）。
    未唯一命中抛 ValueError（消息带当前设备清单，便于对照改名）。
    """
    try:
        from pygrabber.dshow_graph import FilterGraph
    except ImportError as e:
        raise ImportError(
            "按名打开相机需要 pygrabber（pip install pygrabber）") from e
    devices = FilterGraph().get_input_devices()
    hits = [i for i, name in enumerate(devices)
            if name_substring.lower() in name.lower()]
    listing = "; ".join(f"index {i}: {name}" for i, name in enumerate(devices))
    if len(hits) != 1:
        raise ValueError(
            f"相机名 '{name_substring}' 未唯一命中（{len(hits)} 个）。"
            f"当前 DirectShow 设备: {listing}")
    return hits[0]


class LaserSpotCamera:
    """USB 相机封装：取图 + 激光光斑检测

    Windows 下用 DirectShow 后端打开（比 MSMF 开得快、曝光属性可用）；
    分辨率设置失败时静默回退相机默认分辨率。
    camera_name 优先于 camera_index：给出名字时在 open() 当刻按名解析
    index（顺序会漂，构造时解析不可靠），解析失败抛 ValueError/IOError。
    """

    def __init__(self, camera_index=0, width=1920, height=1080, exposure=None,
                 camera_name=None):
        self.camera_index = camera_index
        self.camera_name = camera_name
        self.width = width
        self.height = height
        self.exposure = exposure      # DirectShow 曝光值（负值，如 -5），None=自动
        self.cap = None

    # ── 相机开关 ──────────────────────────────────────────────────

    def open(self):
        """打开相机并应用分辨率/曝光设置，失败抛 IOError"""
        if self.camera_name is not None:
            self.camera_index = find_camera_index(self.camera_name)
        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            raise IOError(f"相机 index={self.camera_index} 打开失败（DirectShow 后端）")
        self.cap = cap    # 先落位，分辨率/曝光设置都依赖 self.cap
        if self.width and self.height:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if self.exposure is not None:
            self.set_exposure(self.exposure)
        return self

    def close(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def __enter__(self):
        if self.cap is None:
            self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    # ── 曝光（属性语义随后端而异，以画面实际变化为准） ────────────

    def set_exposure(self, value):
        """切手动曝光并设曝光值（DirectShow 负值标度）"""
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)      # 1=手动（DSHOW 语义）
        self.cap.set(cv2.CAP_PROP_EXPOSURE, float(value))
        self.exposure = value

    def set_auto_exposure(self):
        """恢复自动曝光"""
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0)      # 0=自动（DSHOW 语义）
        self.exposure = None

    # ── 取图与检测 ────────────────────────────────────────────────

    def capture(self):
        """取一帧最新画面（连读 FLUSH_FRAMES 帧冲掉缓冲区旧画面）

        相机缓冲区可能残留激光熄灭前的旧帧，直接 read 会拿到过期画面
        造成 ON/OFF 误判，必须连读取最新。
        """
        if self.cap is None:
            raise RuntimeError("相机未打开，请先调用 open()")
        frame = None
        for _ in range(FLUSH_FRAMES):
            ok, frame = self.cap.read()
            if not ok:
                raise IOError(f"相机 index={self.camera_index} 取图失败")
        return frame

    def detect_spot(self, frame, color):
        """在帧中检测指定颜色的激光光斑

        参数:
            frame: BGR 图像（numpy array）
            color: "green" / "blue"

        返回:
            SpotResult
        """
        if color not in HSV_RANGES:
            raise ValueError(f"未知激光颜色: {color}（支持: {list(HSV_RANGES)}）")
        lower, upper = (np.array(bound) for bound in HSV_RANGES[color])

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, lower, upper)
        pixel_count = int(cv2.countNonZero(mask))

        kernel = np.ones((MORPH_KERNEL_SIZE, MORPH_KERNEL_SIZE), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return SpotResult(color, False, None, 0.0, pixel_count)

        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        if area < MIN_SPOT_AREA_PX:
            return SpotResult(color, False, None, area, pixel_count)

        m = cv2.moments(largest)
        centroid = (m['m10'] / m['m00'], m['m01'] / m['m00'])
        return SpotResult(color, True, centroid, area, pixel_count)

    def annotate(self, frame, result, text_y=30):
        """在帧副本上标注检测结果（十字准星 + 圆圈 + 状态文本），返回标注帧

        注意 cv2.putText 不支持中文，标注文本用英文。
        text_y 用于多颜色叠加时错开文本行。
        """
        out = frame.copy()
        bgr = SPOT_COLOR_BGR.get(result.color, (0, 255, 255))
        if result.found:
            x, y = (int(round(v)) for v in result.centroid)
            cv2.drawMarker(out, (x, y), bgr, cv2.MARKER_CROSS, 40, 2)
            cv2.circle(out, (x, y), 24, bgr, 2)
            text = f"{result.color.upper()} spot ({x},{y}) area={result.area_px:.0f}px2"
        else:
            text = (f"{result.color.upper()} spot NOT FOUND "
                    f"(max_area={result.area_px:.0f}px2 px={result.pixel_count})")
        cv2.putText(out, text, (10, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, bgr, 2)
        return out


def encode_jpg(frame):
    """帧编码为 JPG 字节流（allure 二进制附件用，参照 test_nest_log_fetch 模式）"""
    ok, buf = cv2.imencode('.jpg', frame)
    if not ok:
        raise IOError("JPG 编码失败")
    return buf.tobytes()