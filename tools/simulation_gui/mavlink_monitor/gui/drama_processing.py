"""
剧本处理面板
============

提供两个子 Tab：

    Tab 0 —— 航点解析对比：选择 bin 文件，手动触发航点解析 / 航点对比
    Tab 1 —— 航点篡改：    修改 .drm 剧本中两架飞机某帧的航点间距

依赖
----
    - DramaReader（来自外部项目）解析 .drm 文件
    - DatReader（来自外部项目）用于 bin 文件的备用解析
    - 假飞机的 visualize_drama_3d / visualize_drama_compare 方法

运行
----
    本模块由 integrated_gui.py 的 IntegratedMainWindow 创建并注入 sender 引用。
"""
from __future__ import annotations

import json as _json
import logging
import math
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QSize, QThread, Signal, Slot
from PySide6.QtGui import QCloseEvent, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mavlink_monitor.gui.widgets import _LimitedCombo

# ═══════════════════════════════════════════════════════════════
# 外部依赖路径（假设备项目）
# ═══════════════════════════════════════════════════════════════
from mavlink_monitor.core.paths import get_fake_project_path, has_fake_project

_FAKE_PROJECT = get_fake_project_path()
_HAS_FAKE = has_fake_project()
if _HAS_FAKE and _FAKE_PROJECT not in sys.path:
    sys.path.insert(0, _FAKE_PROJECT)

# ═══════════════════════════════════════════════════════════════
# 注入本地 Drama3_pb2 模块（protobuf 7.x UTF-8 修复）
# ═══════════════════════════════════════════════════════════════
# protobuf 7.x 对 string 字段严格校验 UTF-8，而 .drm 文件中的
# dramaId/sceneName/description/authorName/map.name/segmInfos.description
# 可能含非 UTF-8 字节。本地 Drama3_pb2.py 将这些字段改为 bytes 类型，
# 绕开 protobuf 的 UTF-8 校验。为确保外部项目中的 drama_reader.py
# 也使用本地版本，需在首次导入前将本地模块注册到 sys.modules。
_LOCAL_PB2 = os.path.join(os.path.dirname(__file__), "Drama3_pb2.py")
if os.path.exists(_LOCAL_PB2):
    import importlib.util as _importlib_util
    _spec = _importlib_util.spec_from_file_location(
        "src.Protocol.drama.drone_show.Drama3_pb2", _LOCAL_PB2
    )
    if _spec and _spec.loader:
        _local_module = _importlib_util.module_from_spec(_spec)
        sys.modules["src.Protocol.drama.drone_show.Drama3_pb2"] = _local_module
        _spec.loader.exec_module(_local_module)

# 日志：优先使用外部项目的 logger，不可用时回退到标准 logging
try:
    from utils.logger import logger  # type: ignore[import-untyped]
except ImportError:
    logger = logging.getLogger("drama_processing")


def _try_import_drama_reader():
    """尝试导入 DramaReader；不可用时返回 None。"""
    try:
        from src.Protocol.drama.drone_show.drama_reader import DramaReader
        return DramaReader
    except ImportError:
        return None


def _try_import_dat_reader():
    """尝试导入 DatReader；不可用时返回 None。"""
    try:
        from src.Protocol.drama.drone_show.dat_reader import DatReader
        return DatReader
    except ImportError:
        return None


# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════
_SELF_DIR = Path(__file__).resolve().parent.parent  # → mavlink_monitor/
_PROJECT_ROOT = _SELF_DIR.parent  # → mavlink_monitor/ (project root)
DEFAULT_DRAMA_DIR = str(_PROJECT_ROOT / "output" / "drama")
DRAMA_MODIFIED_DIR = str(_PROJECT_ROOT / "output" / "drama_modified")

# 剧本时间对齐对比：距离容差（m），小于该值且灯光一致视为航点匹配
_DIST_TOL = 0.005
# 剧本文件名时间戳 yyyymmdd_hhmmss[.xxx]（xxx 毫秒）
_TS_RE = re.compile(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?:\.(\d{1,3}))?")


# ═══════════════════════════════════════════════════════════════
# 独立航点解析/可视化函数
# ═══════════════════════════════════════════════════════════════
def parse_timestamp_from_name(name: str) -> datetime | None:
    """从剧本文件名解析起飞绝对时间（``yyyymmdd_hhmmss[.xxx]``，xxx 毫秒）。

    - ``drama_merge_1_20260727_200616.bin`` → 2026-07-27 20:06:16
    - ``172.16.3.170_20260824_124942.585.bin`` → 2026-08-24 12:49:42.585

    Args:
        name: bin 文件完整路径或文件名

    Returns:
        ``datetime`` 对象；解析失败返回 None
    """
    m = _TS_RE.search(os.path.basename(name))
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    h, mi, s = int(m.group(4)), int(m.group(5)), int(m.group(6))
    ms = int(m.group(7).ljust(3, "0")) if m.group(7) else 0
    return datetime(y, mo, d, h, mi, s, ms * 1000)


def _sample_pos(frames: list[dict], j: float) -> tuple[float, float, float] | None:
    """在剧本帧序列上按帧号 ``j``（可为小数）线性插值第一架飞机位置。

    越界或无位置数据时返回 None。
    """
    if j < 0:
        return None
    i0 = int(math.floor(j))
    i1 = int(math.ceil(j))
    if i0 >= len(frames) or not frames[i0]["positions"]:
        return None
    p0 = frames[i0]["positions"][0]
    if i1 >= len(frames) or i0 == i1:
        return (p0["x"], p0["y"], p0["z"])
    p1 = frames[i1]["positions"][0]
    t = j - i0
    return (p0["x"] + (p1["x"] - p0["x"]) * t,
            p0["y"] + (p1["y"] - p0["y"]) * t,
            p0["z"] + (p1["z"] - p0["z"]) * t)


def _sample_light(frames: list[dict], j: float) -> tuple[int, int, int] | None:
    """灯光是持续值：取 ``floor(j)`` 帧第一架飞机的灯光（前向保持），不插值。"""
    i = int(math.floor(j))
    if i < 0 or i >= len(frames) or not frames[i]["lights"]:
        return None
    l = frames[i]["lights"][0]
    return (l["r"], l["g"], l["b"])


def compare_drama_timelines(early_frames: list[dict], late_frames: list[dict],
                            early_t0: datetime, late_t0: datetime,
                            payload_fps: int, point_fps: int | None = None) -> list[dict]:
    """按绝对时间对齐对比两个不同起飞时间的剧本。

    规则：
    - 以**早起飞剧本**的帧为时间基准（帧号恒整数），**晚起飞剧本**插值到该网格
    - 对比起点 = 晚起飞时刻（对应 early 帧号 ``ceil(offset)``），终点 = 公共重叠区间
    - frames 数组的帧号是 **payload 帧索引**（时间 = 帧号 / payload_fps），
      因此偏移 ``offset = 起飞时间差 × payload_fps``（单位 payload 帧）
    - **每个 payload 帧一个对比点**（疏密与原剧本「航点解析」一致，即 Tab0
      ``parse_waypoints_from_bin`` 的航点粒度）；晚起飞剧本帧号 ``j = k - offset``
      为小数时对相邻帧线性插值（灯光取 floor 帧，不插值）
    - 每个时间点计算两机实际距离 + 灯光 RGB 一致性

    Args:
        early_frames: 早起飞剧本 frames（``parse_waypoints_lights_from_bin`` 的 "frames"）
        late_frames: 晚起飞剧本 frames
        early_t0: 早起飞剧本起飞绝对时间
        late_t0: 晚起飞剧本起飞绝对时间
        payload_fps: 负载帧率（frames 数组帧号的实际帧率）
        point_fps: 保留参数（兼容调用），对比点疏密以原剧本 payload 帧为基准

    Returns:
        ``[{'frame', 'rel_time', 'dist', 'light_ok', 'ok',
           'early_pos', 'late_pos', 'early_light', 'late_light'}, ...]``
    """
    dt_payload = 1.0 / payload_fps if payload_fps else 1.0
    offset = (late_t0 - early_t0).total_seconds() / dt_payload
    step = 1  # 每 payload 帧一个对比点，疏密与原剧本航点解析一致
    k_start = int(math.ceil(offset))
    k_end = min(len(early_frames) - 1, k_start + len(late_frames) - 1)
    results = []
    for k in range(k_start, k_end + 1, step):
        j = k - offset  # 晚起飞剧本帧号（可为小数）
        ep = _sample_pos(early_frames, k)
        lp = _sample_pos(late_frames, j)
        if ep is None or lp is None:
            continue
        d = math.sqrt((ep[0] - lp[0]) ** 2 + (ep[1] - lp[1]) ** 2 + (ep[2] - lp[2]) ** 2)
        el = _sample_light(early_frames, k)
        ll = _sample_light(late_frames, j)
        light_ok = el is not None and ll is not None and el == ll
        results.append({
            "frame": k,
            "rel_time": j * dt_payload,  # 相对晚起飞时刻的秒数
            "dist": d,
            "light_ok": light_ok,
            "ok": d < _DIST_TOL and light_ok,
            "early_pos": ep,
            "late_pos": lp,
            "early_light": el,
            "late_light": ll,
        })
    return results


def parse_waypoints_from_bin(bin_path: str) -> dict | None:
    """解析 bin 文件，提取航点与元数据（共用解析管线）。

    Args:
        bin_path: .bin 文件完整路径

    Returns:
        {'waypoints': [...], 'header': ..., 'data': ..., 'dot_index': int} 或 None
    """
    try:
        from src.Protocol.drama.drone_show.dat_reader import DatReader
    except ImportError:
        return None

    reader = DatReader()
    try:
        header, config, trailer, _rc0, _rc1, _rc2 = reader.process_file(bin_path)
    except Exception:
        return None

    valid_frames = [f for f in trailer['frames'] if 'unknown' not in f]
    try:
        reader.save_one_drone_data(config, valid_frames, bin_path, interpolate=True)
    except Exception:
        return None

    dot_index = bin_path.rfind('.')
    json_path = f"{bin_path[:dot_index]}.json"
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = _json.load(f)
    except Exception:
        return None

    waypoints = []
    META_KEYS = {"pointFps", "payloadFps", "totalPointFrameCount", "totalPayloadFrameCount"}
    for key in sorted(data.keys(), key=lambda k: (
        0 if k in META_KEYS else 1, int(k) if k.isdigit() else 999999
    )):
        if key in META_KEYS:
            continue
        for item in data[key]:
            if "x" in item and "y" in item and "z" in item:
                waypoints.append({
                    "frame": int(key),
                    "x": item["x"],
                    "y": item["y"],
                    "z": item["z"],
                })
    if not waypoints:
        return None
    return {"waypoints": waypoints, "header": header, "data": data, "dot_index": dot_index}


def visualize_drama_3d(bin_path: str) -> str | None:
    """解析剧本 bin 文件并生成交互式 3D 航点可视化 HTML。

    Args:
        bin_path: .bin 文件完整路径

    Returns:
        生成的 HTML 文件路径，失败时返回 None
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        logger.warning("[TEST] 3D 可视化依赖缺失: plotly")
        return None

    parsed = parse_waypoints_from_bin(bin_path)
    if parsed is None:
        logger.warning(f"[TEST] 航点解析失败: {bin_path}")
        return None

    waypoints = parsed["waypoints"]
    header = parsed["header"]
    data = parsed["data"]
    dot_index = parsed["dot_index"]

    xs = [w["x"] for w in waypoints]
    ys = [w["y"] for w in waypoints]
    zs = [w["z"] for w in waypoints]
    frames_nums = [w["frame"] for w in waypoints]
    point_fps = data.get("pointFps", "?")
    mission_id = int.from_bytes(header['id'], 'little')

    # 构建 3D 图
    fig = go.Figure()

    # 轨迹线
    fig.add_trace(go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode='lines',
        line=dict(width=4, color='rgba(100, 149, 237, 0.7)'),
        name='飞行轨迹',
        hovertemplate="Frame: %{text}<br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
        text=frames_nums,
    ))

    # 航点标记
    fig.add_trace(go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode='markers',
        marker=dict(
            size=2,
            color=frames_nums,
            colorscale='Viridis',
            colorbar=dict(title="Frame", thickness=15, len=0.5),
            opacity=0.8,
        ),
        name='航点',
        hovertemplate="Frame: %{text}<br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
        text=frames_nums,
    ))

    # 起点
    start_wp = waypoints[0]
    fig.add_trace(go.Scatter3d(
        x=[start_wp["x"]], y=[start_wp["y"]], z=[start_wp["z"]],
        mode='markers+text',
        marker=dict(size=10, color='limegreen', symbol='diamond', line=dict(width=2, color='darkgreen')),
        text=[f"起点 (F{start_wp['frame']})"],
        textposition="top center",
        textfont=dict(size=12, color='limegreen'),
        name=f'起点 (Frame {start_wp["frame"]})',
        hovertemplate="<b>起点</b><br>Frame: %{text}<br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))

    # 终点
    end_wp = waypoints[-1]
    fig.add_trace(go.Scatter3d(
        x=[end_wp["x"]], y=[end_wp["y"]], z=[end_wp["z"]],
        mode='markers+text',
        marker=dict(size=10, color='red', symbol='x', line=dict(width=2, color='darkred')),
        text=[f"终点 (F{end_wp['frame']})"],
        textposition="top center",
        textfont=dict(size=12, color='red'),
        name=f'终点 (Frame {end_wp["frame"]})',
        hovertemplate="<b>终点</b><br>Frame: %{text}<br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))

    # 原点
    fig.add_trace(go.Scatter3d(
        x=[0], y=[0], z=[0],
        mode='markers',
        marker=dict(size=8, color='orange', symbol='circle-open', line=dict(width=2, color='orange')),
        name='原点 (0,0,0)',
        hovertemplate="<b>原点</b><br>X: 0<br>Y: 0<br>Z: 0<extra></extra>",
    ))

    # 计算轴范围：各轴独立，航点包围盒 +5% 边距 → 数据占 ~90%
    def _axis_range(values):
        lo, hi = min(values), max(values)
        pad = (hi - lo) * 0.05 if hi != lo else max(abs(lo) * 0.05, 0.5)
        return [lo - pad, hi + pad]

    fig.update_layout(
        title=dict(
            text=f"<b>3D 航点可视化 — Mission {mission_id}</b><br>"
                 f"<sup>{len(waypoints)} 个航点 · 位置帧率: {point_fps}fps · "
                 f"帧范围: {min(frames_nums)}–{max(frames_nums)}</sup>",
            x=0.5,
        ),
        scene=dict(
            xaxis_title="X (m) [东向]",
            yaxis_title="Y (m) [北向]",
            zaxis_title="Z (m) [高度]",
            aspectmode='cube',
            camera=dict(
                eye=dict(x=1.3, y=1.3, z=0.8),
                up=dict(x=0, y=0, z=1),
            ),
            xaxis=dict(range=_axis_range(xs)),
            yaxis=dict(range=_axis_range(ys)),
            zaxis=dict(range=_axis_range(zs)),
        ),
        legend=dict(
            yanchor="top", y=0.99,
            xanchor="left", x=0.01,
            font=dict(size=10),
        ),
        margin=dict(l=0, r=0, t=60, b=0),
        hovermode='closest',
    )

    # 输出 HTML
    html_path = f"{bin_path[:dot_index]}_3d.html"
    try:
        fig.write_html(html_path)
        logger.info(
            f"[TEST] 3D 航点可视化已生成: {html_path} "
            f"(mission={mission_id}, waypoints={len(waypoints)})"
        )
    except Exception as e:
        logger.warning(f"[TEST] 保存 HTML 失败 {html_path}: {e}")
        return None

    return html_path


def visualize_drama_compare(current_bin: str, previous_bin: str) -> str | None:
    """对比两次剧本航点，生成差异可视化 HTML。

    规则：
    - 相同坐标 (x,y,z 差值 < 1cm) → 灰色小点（缩小 80%）
    - 不同坐标 → 当前红色 / 上次蓝色（正常大小）

    Args:
        current_bin: 当前 bin 路径
        previous_bin: 上一次 bin 路径

    Returns:
        生成的 HTML 路径，失败返回 None
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    cur = parse_waypoints_from_bin(current_bin)
    prev = parse_waypoints_from_bin(previous_bin)
    if cur is None or prev is None:
        logger.warning("[TEST] compare 解析失败")
        return None

    cur_wps = cur["waypoints"]  # list of {frame, x, y, z}
    prev_wps = prev["waypoints"]

    EPS = 0.01  # 1cm tolerance

    # 将上次航点坐标放入可匹配池（坐标仅用一次，避免重复匹配）
    prev_pool = [(w["x"], w["y"], w["z"]) for w in prev_wps]
    prev_matched = [False] * len(prev_pool)

    match_x, match_y, match_z, match_t = [], [], [], []
    cur_x, cur_y, cur_z, cur_t = [], [], [], []
    prev_x, prev_y, prev_z, prev_t = [], [], [], []

    for cw in cur_wps:
        cx, cy, cz = cw["x"], cw["y"], cw["z"]
        found = False
        for i, (px, py, pz) in enumerate(prev_pool):
            if prev_matched[i]:
                continue
            if abs(cx - px) < EPS and abs(cy - py) < EPS and abs(cz - pz) < EPS:
                match_x.append(cx); match_y.append(cy); match_z.append(cz)
                match_t.append(f"({cx:.1f}, {cy:.1f}, {cz:.1f})")
                prev_matched[i] = True
                found = True
                break
        if not found:
            cur_x.append(cx); cur_y.append(cy); cur_z.append(cz)
            cur_t.append(f"F{cw['frame']} ({cx:.1f}, {cy:.1f}, {cz:.1f})")

    # 上次未匹配的
    for i, (px, py, pz) in enumerate(prev_pool):
        if not prev_matched[i]:
            prev_x.append(px); prev_y.append(py); prev_z.append(pz)
            prev_t.append(f"F{prev_wps[i]['frame']} ({px:.1f}, {py:.1f}, {pz:.1f})")

    mission_id = int.from_bytes(cur["header"]['id'], 'little')
    match_cnt = len(match_x)
    diff_cnt = len(cur_x) + len(prev_x)

    fig = go.Figure()

    # 匹配点：缩小 80%（size=0.8），灰色
    if match_x:
        fig.add_trace(go.Scatter3d(
            x=match_x, y=match_y, z=match_z,
            mode='markers',
            marker=dict(size=0.8, color='gray', opacity=0.6),
            name=f'匹配 ({match_cnt})',
            hovertemplate="%{text}<br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
            text=match_t,
        ))

    # 当前差异：红色
    if cur_x:
        fig.add_trace(go.Scatter3d(
            x=cur_x, y=cur_y, z=cur_z,
            mode='markers',
            marker=dict(size=2, color='red', opacity=0.9),
            name=f'当前差异 ({len(cur_x)})',
            hovertemplate="%{text}<br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
            text=cur_t,
        ))

    # 上次差异：蓝色
    if prev_x:
        fig.add_trace(go.Scatter3d(
            x=prev_x, y=prev_y, z=prev_z,
            mode='markers',
            marker=dict(size=2, color='blue', opacity=0.9),
            name=f'上次差异 ({len(prev_x)})',
            hovertemplate="%{text}<br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
            text=prev_t,
        ))

    # 轴范围：合并所有点
    all_x = match_x + cur_x + prev_x
    all_y = match_y + cur_y + prev_y
    all_z = match_z + cur_z + prev_z
    def _ar(vals):
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.05 if hi != lo else max(abs(lo) * 0.05, 0.5)
        return [lo - pad, hi + pad]

    fig.update_layout(
        title=dict(
            text=f"<b>航点对比 — Mission {mission_id}</b><br>"
                 f"<sup>{match_cnt} 匹配 · {diff_cnt} 差异 | "
                 f"当前: {os.path.basename(current_bin)} vs 上次: {os.path.basename(previous_bin)}</sup>",
            x=0.5,
        ),
        scene=dict(
            xaxis_title="X (m) [东向]",
            yaxis_title="Y (m) [北向]",
            zaxis_title="Z (m) [高度]",
            aspectmode='cube',
            camera=dict(eye=dict(x=1.3, y=1.3, z=0.8), up=dict(x=0, y=0, z=1)),
            xaxis=dict(range=_ar(all_x)),
            yaxis=dict(range=_ar(all_y)),
            zaxis=dict(range=_ar(all_z)),
        ),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, font=dict(size=10)),
        margin=dict(l=0, r=0, t=60, b=0),
        hovermode='closest',
    )

    dot = current_bin.rfind('.')
    html_path = f"{current_bin[:dot]}_compare_{mission_id}.html"
    try:
        fig.write_html(html_path)
        logger.info(
            f"[TEST] 对比图已生成: {html_path} "
            f"(mission={mission_id}, match={match_cnt}, diff={diff_cnt})"
        )
    except Exception as e:
        logger.warning(f"[TEST] 保存对比 HTML 失败: {e}")
        return None
    return html_path


def visualize_drama_compare_timeline(bin_a: str, bin_b: str,
                                     out_dir: str | None = None) -> str | None:
    """对比两个不同起飞时间的剧本，生成时间对齐的 3D 航迹 + 双折线 HTML。

    布局：页面左侧竖排两个折线图（两机距离 / 灯光一致性，横轴=相对秒），
    右侧 3D 场景（早起飞剧本灰航线/灰航点，晚起飞剧本绿/红航点 + 分段着色航线）。

    规则：
    - 早起飞剧本为时间基准（整数帧），晚起飞剧本线性插值到其时间网格
    - 晚起飞剧本航点/航线绿色条件：两机距离 < 0.005m 且灯光 RGB 一致；否则红色
    - 灯光取 ``floor`` 帧持续值，不插值

    Args:
        bin_a: 剧本 bin 路径 A
        bin_b: 剧本 bin 路径 B
        out_dir: 输出目录；默认与早起飞剧本同目录

    Returns:
        生成的 HTML 路径，失败返回 None
    """
    try:
        import plotly.graph_objects as go
        from plotly.offline import get_plotlyjs
    except ImportError:
        logger.warning("[TEST] 3D 可视化依赖缺失: plotly")
        return None

    pa = parse_waypoints_lights_from_bin(bin_a)
    pb = parse_waypoints_lights_from_bin(bin_b)
    if pa is None or pb is None:
        logger.warning("[TEST] 对比解析失败")
        return None
    ta = parse_timestamp_from_name(bin_a)
    tb = parse_timestamp_from_name(bin_b)
    if ta is None or tb is None:
        logger.warning("[TEST] 无法从文件名解析开始时间: %s / %s", bin_a, bin_b)
        return None

    if ta <= tb:
        early_bin, late_bin = bin_a, bin_b
        early_t0, late_t0 = ta, tb
        early_parsed, late_parsed = pa, pb
    else:
        early_bin, late_bin = bin_b, bin_a
        early_t0, late_t0 = tb, ta
        early_parsed, late_parsed = pb, pa

    payload_fps = early_parsed["payload_fps"] or late_parsed["payload_fps"] or 1
    point_fps = early_parsed["point_fps"] or late_parsed["point_fps"] or 1
    results = compare_drama_timelines(
        early_parsed["frames"], late_parsed["frames"],
        early_t0, late_t0, payload_fps, point_fps,
    )
    if not results:
        logger.warning("[TEST] 无有效对比点")
        return None

    mission_id = int.from_bytes(early_parsed["header"]['id'], 'little')

    # 后起飞时刻对应早起飞剧本的帧号（payload 帧）；帧 < 该值为「后起飞前」
    offset = (late_t0 - early_t0).total_seconds() * payload_fps
    split_frame = int(math.ceil(offset))
    pos_step = max(1, round(payload_fps / point_fps)) if payload_fps and point_fps else 1

    # ── 原剧本（早起飞）完整轨迹/航点：后起飞前淡灰 + 对比段正常灰 ──
    # 显示全部 payload 帧（与 Tab0「航点解析」parse_waypoints_from_bin 疏密一致）
    pre_x, pre_y, pre_z, pre_fr = [], [], [], []
    post_x, post_y, post_z, post_fr = [], [], [], []
    ef = early_parsed["frames"]
    for f in ef:
        if not f["positions"]:
            continue
        p = f["positions"][0]
        if f["frame"] < split_frame:
            pre_x.append(p["x"]); pre_y.append(p["y"]); pre_z.append(p["z"])
            pre_fr.append(f["frame"])
        else:
            post_x.append(p["x"]); post_y.append(p["y"]); post_z.append(p["z"])
            post_fr.append(f["frame"])

    # ── 晚起飞剧本（对比区间） ──
    l_x = [r["late_pos"][0] for r in results]
    l_y = [r["late_pos"][1] for r in results]
    l_z = [r["late_pos"][2] for r in results]
    l_colors = ['green' if r["ok"] else 'red' for r in results]
    # 航点标记：position 帧（frame % pos_step == 0）用大菱形，普通 payload 帧用小圆点
    l_sizes = [8 if (r["frame"] % pos_step == 0) else 2 for r in results]
    l_symbols = ['diamond' if (r["frame"] % pos_step == 0) else 'circle' for r in results]
    pre_sizes = [8 if (f % pos_step == 0) else 2 for f in pre_fr]
    pre_symbols = ['diamond' if (f % pos_step == 0) else 'circle' for f in pre_fr]
    post_sizes = [8 if (f % pos_step == 0) else 2 for f in post_fr]
    post_symbols = ['diamond' if (f % pos_step == 0) else 'circle' for f in post_fr]

    # 晚起飞航线分段着色：段颜色 = 两端点都 ok → 绿，否则红（None 分隔）
    seg_x, seg_y, seg_z, seg_colors = [], [], [], []
    for i, r in enumerate(results):
        if i < len(results) - 1:
            seg = 'green' if (r["ok"] and results[i + 1]["ok"]) else 'red'
        else:
            seg = l_colors[i]
        seg_x.append(l_x[i]); seg_y.append(l_y[i]); seg_z.append(l_z[i])
        seg_colors.append(seg)
        if i < len(results) - 1:
            seg_x.append(l_x[i + 1]); seg_y.append(l_y[i + 1]); seg_z.append(l_z[i + 1])
            seg_colors.append(seg)
            seg_x.append(None); seg_y.append(None); seg_z.append(None)
            seg_colors.append(seg)

    def _axis_range(vals):
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.05 if hi != lo else max(abs(lo) * 0.05, 0.5)
        return [lo - pad, hi + pad]

    fig3d = go.Figure()
    # 原剧本航线（后起飞前淡灰 / 对比段正常灰）——无条件添加，空数据用空数组
    fig3d.add_trace(go.Scatter3d(
        x=pre_x, y=pre_y, z=pre_z, mode='lines',
        line=dict(width=3, color='rgba(150,150,150,0.25)'),
        name='原剧本航线（后起飞前）',
        hovertemplate="X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))
    fig3d.add_trace(go.Scatter3d(
        x=post_x, y=post_y, z=post_z, mode='lines',
        line=dict(width=3, color='rgba(128,128,128,0.7)'),
        name='原剧本航线（对比段）',
        hovertemplate="X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))
    # 原剧本航点（后起飞前淡灰 / 对比段正常灰）——大菱形=航点，小圆点=payload 帧
    fig3d.add_trace(go.Scatter3d(
        x=pre_x, y=pre_y, z=pre_z, mode='markers',
        marker=dict(size=pre_sizes, color='rgba(150,150,150,0.35)', symbol=pre_symbols,
                    opacity=0.6),
        name='原剧本航点（后起飞前）',
        hovertemplate="X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))
    fig3d.add_trace(go.Scatter3d(
        x=post_x, y=post_y, z=post_z, mode='markers',
        marker=dict(size=post_sizes, color='gray', symbol=post_symbols, opacity=0.7),
        name='原剧本航点（对比段）',
        hovertemplate="X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))
    # 晚起飞航线（分段着色）
    fig3d.add_trace(go.Scatter3d(
        x=seg_x, y=seg_y, z=seg_z, mode='lines',
        line=dict(width=4, color=seg_colors),
        name=f'后起飞航线 ({os.path.basename(late_bin)})',
        hovertemplate="X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))
    # 晚起飞航点（绿/红）——大菱形=航点，小圆点=payload 帧
    fig3d.add_trace(go.Scatter3d(
        x=l_x, y=l_y, z=l_z, mode='markers',
        marker=dict(size=l_sizes, color=l_colors, symbol=l_symbols,
                    line=dict(width=0.5, color='black'), opacity=0.95),
        name='后起飞航点 (绿=匹配, 红=差异)',
        text=[f"t={r['rel_time']:.2f}s dist={r['dist']:.3f}m" for r in results],
        hovertemplate="%{text}<br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))

    # 起点 / 终点 / 原点（与 visualize_drama_playback 视觉一致）——无条件添加
    first_p = ef[0]["positions"][0] if ef and ef[0]["positions"] else None
    last_p = ef[-1]["positions"][0] if ef and ef[-1]["positions"] else None
    sx = [first_p["x"]] if first_p else []
    sy = [first_p["y"]] if first_p else []
    sz = [first_p["z"]] if first_p else []
    fig3d.add_trace(go.Scatter3d(
        x=sx, y=sy, z=sz, mode='markers+text',
        marker=dict(size=2.5, color='limegreen', symbol='diamond',
                    line=dict(width=1, color='darkgreen')),
        text=["起点"] if first_p else [], textposition="top center",
        textfont=dict(size=12, color='limegreen'),
        name='起点',
        hovertemplate="<b>起点</b><br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))
    ex = [last_p["x"]] if last_p else []
    ey = [last_p["y"]] if last_p else []
    ez = [last_p["z"]] if last_p else []
    fig3d.add_trace(go.Scatter3d(
        x=ex, y=ey, z=ez, mode='markers+text',
        marker=dict(size=2.5, color='red', symbol='x',
                    line=dict(width=1, color='darkred')),
        text=["终点"] if last_p else [], textposition="top center",
        textfont=dict(size=12, color='red'),
        name='终点',
        hovertemplate="<b>终点</b><br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))
    fig3d.add_trace(go.Scatter3d(
        x=[0], y=[0], z=[0],
        mode='markers',
        marker=dict(size=8, color='orange', symbol='circle-open',
                    line=dict(width=2, color='orange')),
        name='原点 (0,0,0)',
        hovertemplate="<b>原点</b><br>X: 0<br>Y: 0<br>Z: 0<extra></extra>",
    ))

    # 当前帧 markers（trace 9/10/11，播放时 JS 用 Plotly.restyle 更新）
    _f0 = results[0]
    fig3d.add_trace(go.Scatter3d(
        x=[_f0["early_pos"][0]], y=[_f0["early_pos"][1]], z=[_f0["early_pos"][2]],
        mode='markers',
        marker=dict(size=8, color='blue', symbol='circle', line=dict(width=1, color='darkblue')),
        name='当前帧-原剧本',
        hovertemplate="<b>当前帧原剧本</b><br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))
    fig3d.add_trace(go.Scatter3d(
        x=[_f0["late_pos"][0]], y=[_f0["late_pos"][1]], z=[_f0["late_pos"][2]],
        mode='markers',
        marker=dict(size=8, color='purple', symbol='circle', line=dict(width=1, color='darkmagenta')),
        name='当前帧-后起飞',
        hovertemplate="<b>当前帧后起飞</b><br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))
    fig3d.add_trace(go.Scatter3d(
        x=[_f0["early_pos"][0], _f0["late_pos"][0], None],
        y=[_f0["early_pos"][1], _f0["late_pos"][1], None],
        z=[_f0["early_pos"][2], _f0["late_pos"][2], None],
        mode='lines',
        line=dict(width=3, color='rgba(0,0,255,0.6)', dash='dash'),
        name='当前帧两机距离',
        hovertemplate="<b>当前帧两机距离</b><extra></extra>",
    ))

    # 轴范围：原剧本全部帧 + 晚起飞对比点 + 原点
    all_x = pre_x + post_x + l_x
    all_y = pre_y + post_y + l_y
    all_z = pre_z + post_z + l_z
    fig3d.update_layout(
        title=dict(
            text=(f"<b>剧本时间对齐对比 — Mission {mission_id}</b><br>"
                  f"<sup>{os.path.basename(early_bin)} (起飞 {early_t0.strftime('%H:%M:%S.%f')[:-3]}) vs "
                  f"{os.path.basename(late_bin)} (起飞 {late_t0.strftime('%H:%M:%S.%f')[:-3]}) · "
                  f"payloadFps {payload_fps} · pointFps {point_fps} · 共 {len(results)} 个时间点 · "
                  f"点距<{_DIST_TOL}m 且灯光一致→绿</sup>"),
            x=0.5,
        ),
        scene=dict(
            xaxis_title="X (m) [东向]",
            yaxis_title="Y (m) [北向]",
            zaxis_title="Z (m) [高度]",
            aspectmode='cube',
            camera=dict(eye=dict(x=1.3, y=1.3, z=0.8), up=dict(x=0, y=0, z=1)),
            xaxis=dict(range=_axis_range(all_x)),
            yaxis=dict(range=_axis_range(all_y)),
            zaxis=dict(range=_axis_range(all_z)),
        ),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, font=dict(size=10)),
        margin=dict(l=0, r=0, t=70, b=0),
        hovermode='closest',
    )

    # ── 两个折线图（左侧，横轴=相对秒） ──
    rel_times = [r["rel_time"] for r in results]
    dists = [r["dist"] for r in results]
    light_vals = [1 if r["light_ok"] else 0 for r in results]

    fig_dist = go.Figure()
    fig_dist.add_trace(go.Scatter(
        x=rel_times, y=dists, mode='lines',
        line=dict(width=2, color='#1f77b4'),
        name='两机距离',
        hovertemplate="t=%{x:.2f}s<br>dist=%{y:.3f}m<extra></extra>",
    ))
    fig_dist.update_layout(
        title=dict(text="两机实际距离", x=0.5, font=dict(size=14)),
        xaxis_title="相对时间 (s)",
        yaxis_title="距离 (m)",
        margin=dict(l=55, r=15, t=40, b=40),
        height=280,
    )

    fig_light = go.Figure()
    fig_light.add_trace(go.Scatter(
        x=rel_times, y=light_vals, mode='lines',
        line=dict(width=2, color='#ff7f0e', shape='hv'),
        name='灯光一致性',
        hovertemplate="t=%{x:.2f}s<br>一致=%{y}<extra></extra>",
    ))
    fig_light.update_layout(
        title=dict(text="灯光颜色一致性 (1=一致, 0=不一致)", x=0.5, font=dict(size=14)),
        xaxis_title="相对时间 (s)",
        yaxis=dict(title="一致性", tickmode='array', tickvals=[0, 1], range=[-0.1, 1.1]),
        margin=dict(l=55, r=15, t=40, b=40),
        height=280,
    )

    # ── HTML 组装：3D 全航迹 + 播放控制 + 数据内嵌 ──
    points_data = [
        {"t": round(r["rel_time"], 3), "dist": round(r["dist"], 4), "ok": bool(r["ok"]),
         "ex": r["early_pos"][0], "ey": r["early_pos"][1], "ez": r["early_pos"][2],
         "lx": r["late_pos"][0], "ly": r["late_pos"][1], "lz": r["late_pos"][2]}
        for r in results
    ]
    data_js = _json.dumps({"points": points_data, "count": len(results), "fps": payload_fps},
                          separators=(',', ':'))
    max_idx = len(results) - 1

    app_js = f"""
(function() {{
  var DATA = {data_js};
  var gd = document.getElementById('plotly_3d');
  var slider = document.getElementById('frame-slider');
  var btn = document.getElementById('play-btn');
  var speedSel = document.getElementById('speed-select');
  var label = document.getElementById('frame-label');
  var maxIdx = DATA.count - 1;
  var playing = false, timer = null;

  function update(i) {{
    if (i < 0) i = 0;
    if (i > maxIdx) i = maxIdx;
    var p = DATA.points[i];
    Plotly.restyle(gd, {{x: [[p.ex]], y: [[p.ey]], z: [[p.ez]]}}, [9]);
    Plotly.restyle(gd, {{x: [[p.lx]], y: [[p.ly]], z: [[p.lz]]}}, [10]);
    Plotly.restyle(gd, {{x: [[p.ex, p.lx, null]], y: [[p.ey, p.ly, null]], z: [[p.ez, p.lz, null]]}}, [11]);
    slider.value = i;
    label.textContent = 't=' + p.t.toFixed(2) + 's · 距离=' + p.dist.toFixed(3) + 'm · ' + (p.ok ? '匹配(绿)' : '差异(红)');
  }}

  function baseInterval() {{
    var speed = Number(speedSel.value) || 1;
    return 1000 / (DATA.fps * speed);
  }}

  function startTimer() {{
    timer = setInterval(function() {{
      var i = Number(slider.value) + 1;
      if (i > maxIdx) {{ pause(); return; }}
      update(i);
    }}, baseInterval());
  }}

  function play() {{
    if (playing) {{ pause(); return; }}
    playing = true; btn.textContent = 'II 暂停';
    startTimer();
  }}

  function pause() {{
    playing = false; btn.textContent = '▶ 播放';
    clearInterval(timer);
  }}

  btn.onclick = play;
  slider.oninput = function() {{ update(Number(slider.value)); }};
  speedSel.onchange = function() {{
    if (playing) {{ clearInterval(timer); startTimer(); }}
  }};
  update(0);
}})();
"""

    div_3d = fig3d.to_html(full_html=False, include_plotlyjs=False, div_id="plotly_3d",
                           config={"responsive": True})
    div_dist = fig_dist.to_html(full_html=False, include_plotlyjs=False, div_id="plotly_dist",
                                config={"responsive": True})
    div_light = fig_light.to_html(full_html=False, include_plotlyjs=False, div_id="plotly_light",
                                  config={"responsive": True})
    plotly_js = get_plotlyjs()

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>剧本时间对齐对比 — Mission {mission_id}</title>
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; overflow: hidden;
    font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif; background: #fff; }}
  #layout {{ display: flex; height: 100vh; }}
  #charts {{ width: 540px; min-width: 540px; display: flex; flex-direction: column;
    border-right: 1px solid #ddd; box-sizing: border-box; overflow-y: auto; }}
  #plotly_wrap {{ flex: 1; display: flex; flex-direction: column; overflow: hidden; }}
  #plotly_3d {{ flex: none; height: calc(100vh - 56px) !important; }}
  #controls {{ display: flex; align-items: center; gap: 12px;
    background: rgba(255, 255, 255, 0.96); border-top: 1px solid #ddd;
    padding: 10px 16px; box-shadow: 0 -2px 6px rgba(0,0,0,0.06); }}
  #controls button {{ min-width: 72px; padding: 6px 12px; font-size: 14px;
    border: 1px solid #999; border-radius: 4px; background: #f5f5f5; cursor: pointer; }}
  #controls select {{ padding: 6px 8px; font-size: 14px; border-radius: 4px; }}
  #frame-slider {{ flex: 1; cursor: pointer; }}
  #frame-label {{ font-size: 13px; color: #444; white-space: nowrap; }}
</style>
<script>{plotly_js}</script>
</head>
<body>
<div id="layout">
  <div id="charts">
    {div_dist}
    {div_light}
  </div>
  <div id="plotly_wrap">
    {div_3d}
    <div id="controls">
      <button id="play-btn">▶ 播放</button>
      <select id="speed-select" title="播放速率">
        <option value="1">1x</option>
        <option value="2">2x</option>
        <option value="3">3x</option>
        <option value="4">4x</option>
        <option value="5">5x</option>
      </select>
      <label for="frame-slider">进度</label>
      <input type="range" id="frame-slider" min="0" max="{max_idx}" value="0" step="1">
      <span id="frame-label">t=0s</span>
    </div>
  </div>
</div>
<script>{app_js}</script>
</body>
</html>"""

    early_dot = early_bin.rfind('.')
    late_dot = late_bin.rfind('.')
    early_base = os.path.basename(early_bin[:early_dot])
    late_base = os.path.basename(late_bin[:late_dot])
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        html_path = os.path.join(out_dir, f"{early_base}_vs_{late_base}_timeline.html")
    else:
        html_path = f"{early_bin[:early_dot]}_vs_{late_base}_timeline.html"
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(
            f"[TEST] 时间对齐对比已生成: {html_path} "
            f"(points={len(results)}, green={sum(1 for r in results if r['ok'])})"
        )
    except Exception as e:
        logger.warning(f"[TEST] 保存时间对齐对比 HTML 失败 {html_path}: {e}")
        return None
    return html_path


def parse_waypoints_lights_from_bin(bin_path: str) -> dict | None:
    """解析 bin 文件，提取每帧航点位置与灯光状态（含 fps 元数据）。

    复用 ``parse_waypoints_from_bin`` 的 DatReader 解析管线，
    额外从 JSON 中分离每帧的位置 item 与灯光 item (r/g/b)。

    Args:
        bin_path: .bin 文件完整路径

    Returns:
        {'frames': [{'frame', 'positions', 'lights'}...],
         'point_fps': int, 'payload_fps': int,
         'header': ..., 'dot_index': int} 或 None
    """
    parsed = parse_waypoints_from_bin(bin_path)
    if parsed is None:
        return None

    data = parsed["data"]
    frames = []
    for key in sorted(data.keys(), key=lambda k: (
        0 if str(k) in {"pointFps", "payloadFps",
                        "totalPointFrameCount", "totalPayloadFrameCount"}
        else 1,
        int(k) if str(k).isdigit() else 999999,
    )):
        if not str(key).isdigit():
            continue
        positions = []
        lights = []
        for item in data[key]:
            if "x" in item and "y" in item and "z" in item:
                positions.append({"x": item["x"], "y": item["y"], "z": item["z"]})
            elif "r" in item and "g" in item and "b" in item:
                lights.append({"r": item["r"], "g": item["g"], "b": item["b"]})
        frames.append({"frame": int(key), "positions": positions, "lights": lights})

    return {
        "frames": frames,
        "point_fps": data.get("pointFps", 0),
        "payload_fps": data.get("payloadFps", 0),
        "header": parsed["header"],
        "dot_index": parsed["dot_index"],
    }


def visualize_drama_playback(bin_path: str, out_dir: str | None = None) -> str | None:
    """解析剧本 bin 文件并生成带帧播放进度条的交互式 3D 航点+灯光 HTML。

    视觉风格与 ``visualize_drama_3d`` 保持一致（轨迹线 / 起点 / 终点 / 原点 /
    轴范围），但增强为：

    - 航点 marker 颜色 = 该帧该航点的灯光 RGB（体现灯光状态）
    - 已途径航线淡色 / 未途径航线亮色，随当前帧动态分段
    - 底部原生进度条（range slider）：可拖动或跳跃至任意帧
    - 播放 / 暂停 + 1x~5x 播放速率调节

    v2（2026-08-24）实现机制：不再使用 plotly frames/slider 全量嵌入动画帧
    （8331 帧会导致 HTML 过大、拖动卡顿），改为：

    - plotly 生成静态 base 场景（未途径线 / 已途径线 / 当前帧 markers / 起终点 / 原点）
    - 位置帧（1667）与灯光帧（8331）数据以紧凑 JSON 数组完整内嵌
      （``posLen`` / ``lightLen`` 自描述，保证位置帧完全保留）
    - 原生 HTML range slider + select 速率 + JS ``Plotly.restyle`` 运行时更新
    - 已途径 / 未途径分段线由 JS 按当前帧实时构建（O(N) 内存，非 O(N²)）

    Args:
        bin_path: .bin 文件完整路径
        out_dir: 输出目录；默认与 bin 同目录

    Returns:
        生成的 HTML 文件路径，失败时返回 None
    """
    try:
        import plotly.graph_objects as go
        from plotly.offline import get_plotlyjs
    except ImportError:
        logger.warning("[TEST] 3D 可视化依赖缺失: plotly")
        return None

    parsed = parse_waypoints_lights_from_bin(bin_path)
    if parsed is None:
        logger.warning(f"[TEST] 航点+灯光解析失败: {bin_path}")
        return None

    frames_data = parsed["frames"]
    point_fps = parsed["point_fps"]
    payload_fps = parsed["payload_fps"]
    header = parsed["header"]
    mission_id = int.from_bytes(header['id'], 'little')
    dot_index = parsed["dot_index"]

    if not frames_data:
        logger.warning(f"[TEST] 无帧数据: {bin_path}")
        return None

    # ── 位置帧（完全保留） / 灯光帧（完全保留） ──
    frame_step = max(1, round(payload_fps / point_fps)) if point_fps else 1
    pos_by_pf: list[list[tuple[float, float, float]]] = []
    for fd in frames_data:
        if fd["frame"] % frame_step == 0:
            pos_by_pf.append([(p["x"], p["y"], p["z"]) for p in fd["positions"]])
    if not pos_by_pf:
        logger.warning(f"[TEST] 无航点数据: {bin_path}")
        return None

    lights_by_f: list[list[tuple[int, int, int]]] = [
        [(l["r"], l["g"], l["b"]) for l in fd["lights"]]
        for fd in frames_data
    ]
    max_drones = max((len(f["positions"]) for f in frames_data), default=1)

    # 轴范围
    xs_all = [p[0] for pf in pos_by_pf for p in pf]
    ys_all = [p[1] for pf in pos_by_pf for p in pf]
    zs_all = [p[2] for pf in pos_by_pf for p in pf]

    def _axis_range(values):
        lo, hi = min(values), max(values)
        pad = (hi - lo) * 0.05 if hi != lo else max(abs(lo) * 0.05, 0.5)
        return [lo - pad, hi + pad]

    # ── 静态 base 场景（JS 用 restyle 更新 trace 0/1/2） ──
    def _trajectory_xyz(frame_slice):
        if max_drones == 1:
            return ([p[0][0] for p in frame_slice],
                    [p[0][1] for p in frame_slice],
                    [p[0][2] for p in frame_slice])
        xs, ys, zs = [], [], []
        for pf in frame_slice:
            for di in range(max_drones):
                p = pf[di] if di < len(pf) else (None, None, None)
                xs.append(p[0]); ys.append(p[1]); zs.append(p[2])
                xs.append(None); ys.append(None); zs.append(None)
        return xs, ys, zs

    fig = go.Figure()

    # trace 0: 未途径线（亮蓝，初始 = 全部位置帧）
    fx, fy, fz = _trajectory_xyz(pos_by_pf)
    fig.add_trace(go.Scatter3d(
        x=fx, y=fy, z=fz, mode='lines',
        line=dict(width=4, color='rgba(100, 149, 237, 0.9)'),
        name='未途径航线',
        hovertemplate="X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))

    # trace 1: 已途径线（淡灰，初始 = 空）
    fig.add_trace(go.Scatter3d(
        x=[], y=[], z=[], mode='lines',
        line=dict(width=4, color='rgba(150, 150, 150, 0.45)'),
        name='已途径航线',
        hovertemplate="X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
    ))

    # trace 2: 当前帧航点 markers（初始 = 位置帧 0）
    def _marker_xyz(pf_idx: int, f_idx: int):
        pf = pos_by_pf[pf_idx]
        lf = lights_by_f[f_idx] if f_idx < len(lights_by_f) else []
        mx, my, mz, mcol, mtext = [], [], [], [], []
        for di in range(max_drones):
            p = pf[di] if di < len(pf) else None
            l = lf[di] if di < len(lf) else None
            if p is None:
                continue
            mx.append(p[0]); my.append(p[1]); mz.append(p[2])
            if l is not None:
                mcol.append(f"rgb({l[0]},{l[1]},{l[2]})")
                mtext.append(f"F{pf_idx * frame_step} 航点{di + 1} (RGB {l[0]},{l[1]},{l[2]})")
            else:
                mcol.append("rgb(128,128,128)")
                mtext.append(f"F{pf_idx * frame_step} 航点{di + 1}")
        return mx, my, mz, mcol, mtext

    mx, my, mz, mcol, mtext = _marker_xyz(0, 0)
    fig.add_trace(go.Scatter3d(
        x=mx, y=my, z=mz, mode='markers',
        marker=dict(size=4, color=mcol, line=dict(width=0.5, color='black'), opacity=0.95),
        text=mtext,
        hovertemplate="%{text}<br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
        name='当前帧航点',
    ))

    # ── 起点 / 终点 / 原点（与 visualize_drama_3d 一致） ──
    first_pf = pos_by_pf[0][0] if pos_by_pf[0] else None
    last_pf = pos_by_pf[-1][0] if pos_by_pf[-1] else None
    if first_pf is not None:
        fig.add_trace(go.Scatter3d(
            x=[first_pf[0]], y=[first_pf[1]], z=[first_pf[2]],
            mode='markers+text',
            marker=dict(size=2.5, color='limegreen', symbol='diamond',
                        line=dict(width=1, color='darkgreen')),
            text=["起点"],
            textposition="top center",
            textfont=dict(size=12, color='limegreen'),
            name='起点',
            hovertemplate="<b>起点</b><br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
        ))
    if last_pf is not None:
        fig.add_trace(go.Scatter3d(
            x=[last_pf[0]], y=[last_pf[1]], z=[last_pf[2]],
            mode='markers+text',
            marker=dict(size=2.5, color='red', symbol='x',
                        line=dict(width=1, color='darkred')),
            text=["终点"],
            textposition="top center",
            textfont=dict(size=12, color='red'),
            name='终点',
            hovertemplate="<b>终点</b><br>X: %{x:.2f}m<br>Y: %{y:.2f}m<br>Z: %{z:.2f}m<extra></extra>",
        ))
    fig.add_trace(go.Scatter3d(
        x=[0], y=[0], z=[0],
        mode='markers',
        marker=dict(size=8, color='orange', symbol='circle-open',
                    line=dict(width=2, color='orange')),
        name='原点 (0,0,0)',
        hovertemplate="<b>原点</b><br>X: 0<br>Y: 0<br>Z: 0<extra></extra>",
    ))

    fig.update_layout(
        title=dict(
            text=(
                f"<b>3D 航点播放 — Mission {mission_id}</b><br>"
                f"<sup>{len(pos_by_pf)} 个位置帧 · {len(lights_by_f)} 个灯光帧 · "
                f"位置帧率: {point_fps}fps · 灯光帧率: {payload_fps}fps · "
                f"marker 颜色 = 灯光 RGB · 淡色 = 已途径航线</sup>"
            ),
            x=0.5,
        ),
        scene=dict(
            xaxis_title="X (m) [东向]",
            yaxis_title="Y (m) [北向]",
            zaxis_title="Z (m) [高度]",
            aspectmode='cube',
            camera=dict(eye=dict(x=1.3, y=1.3, z=0.8), up=dict(x=0, y=0, z=1)),
            xaxis=dict(range=_axis_range(xs_all)),
            yaxis=dict(range=_axis_range(ys_all)),
            zaxis=dict(range=_axis_range(zs_all)),
        ),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, font=dict(size=10)),
        margin=dict(l=0, r=0, t=70, b=120),  # 底部留出原生控件空间
        hovermode='closest',
    )

    # ── HTML 外壳（plotly.js 内嵌 + 原生控件 + 数据 + 应用 JS） ──
    plotly_div = fig.to_html(full_html=False, include_plotlyjs=False, div_id="plotly_playback",
                             config={"responsive": True})
    plotly_js = get_plotlyjs()

    data_payload = {
        "pos": [[list(p) for p in pf] for pf in pos_by_pf],
        "lights": [[list(l) for l in lf] for lf in lights_by_f],
        "frameStep": frame_step,
        "pointFps": point_fps,
        "payloadFps": payload_fps,
        "missionId": mission_id,
        "droneCount": max_drones,
        "posLen": len(pos_by_pf),
        "lightLen": len(lights_by_f),
    }
    data_js = _json.dumps(data_payload, separators=(',', ':'))

    max_frame = len(lights_by_f) - 1
    app_js = f"""
(function() {{
  var DATA = {data_js};
  var gd = document.getElementById('plotly_playback');
  var slider = document.getElementById('frame-slider');
  var btn = document.getElementById('play-btn');
  var speedSel = document.getElementById('speed-select');
  var label = document.getElementById('frame-label');
  var maxFrame = DATA.lightLen - 1;
  var posLen = DATA.posLen;
  var playing = false, timer = null;

  function pfIndex(f) {{
    var p = Math.floor(f / DATA.frameStep);
    return p > posLen - 1 ? posLen - 1 : p;
  }}

  function buildLine(frameSlice) {{
    var x = [], y = [], z = [];
    if (DATA.droneCount === 1) {{
      for (var i = 0; i < frameSlice.length; i++) {{
        var p = frameSlice[i][0];
        x.push(p[0]); y.push(p[1]); z.push(p[2]);
      }}
    }} else {{
      for (var i = 0; i < frameSlice.length; i++) {{
        for (var di = 0; di < DATA.droneCount; di++) {{
          var p = frameSlice[i][di] || [null, null, null];
          x.push(p[0]); y.push(p[1]); z.push(p[2]);
          x.push(null); y.push(null); z.push(null);
        }}
      }}
    }}
    return [x, y, z];
  }}

  function update(f) {{
    if (f < 0) f = 0;
    if (f > maxFrame) f = maxFrame;
    var pf = pfIndex(f);
    var pfPos = DATA.pos[pf];
    var lfLight = DATA.lights[f] || [];
    var mx = [], my = [], mz = [], mcol = [], mtext = [];
    for (var di = 0; di < DATA.droneCount; di++) {{
      var p = pfPos[di];
      var l = lfLight[di];
      if (!p) continue;
      mx.push(p[0]); my.push(p[1]); mz.push(p[2]);
      if (l) {{
        mcol.push('rgb(' + l[0] + ',' + l[1] + ',' + l[2] + ')');
        mtext.push('F' + pf * DATA.frameStep + ' 航点' + (di + 1) + ' (RGB ' + l[0] + ',' + l[1] + ',' + l[2] + ')');
      }} else {{
        mcol.push('rgb(128,128,128)');
        mtext.push('F' + pf * DATA.frameStep + ' 航点' + (di + 1));
      }}
    }}
    Plotly.restyle(gd, {{x: [mx], y: [my], z: [mz], 'marker.color': [mcol], text: [mtext]}}, [2]);
    var fut = buildLine(DATA.pos.slice(pf));
    Plotly.restyle(gd, {{x: [fut[0]], y: [fut[1]], z: [fut[2]]}}, [0]);
    var past = buildLine(DATA.pos.slice(0, pf + 1));
    Plotly.restyle(gd, {{x: [past[0]], y: [past[1]], z: [past[2]]}}, [1]);
    slider.value = f;
    label.textContent = '帧: ' + f + ' / ' + maxFrame + ' · 位置帧 ' + pf;
  }}

  function baseInterval() {{
    var speed = Number(speedSel.value) || 1;
    return 1000 / (DATA.payloadFps * speed);
  }}

  function startTimer() {{
    timer = setInterval(function() {{
      var f = Number(slider.value) + 1;
      if (f > maxFrame) {{ pause(); return; }}
      update(f);
    }}, baseInterval());
  }}

  function play() {{
    if (playing) {{ pause(); return; }}
    playing = true; btn.textContent = 'II 暂停';
    startTimer();
  }}

  function pause() {{
    playing = false; btn.textContent = '▶ 播放';
    clearInterval(timer);
  }}

  btn.onclick = play;
  slider.oninput = function() {{ update(Number(slider.value)); }};
  speedSel.onchange = function() {{
    if (playing) {{ clearInterval(timer); startTimer(); }}
  }};
  label.textContent = '帧: 0 / ' + maxFrame + ' · 位置帧 0';
}})();
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>3D 航点播放 — Mission {mission_id}</title>
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; overflow: hidden;
    font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif; background: #fff; }}
  #plotly_playback {{ width: 100% !important; height: calc(100vh - 56px) !important; }}
  #controls {{
    position: fixed; bottom: 0; left: 0; right: 0; z-index: 10;
    display: flex; align-items: center; gap: 12px;
    background: rgba(255, 255, 255, 0.96); border-top: 1px solid #ddd;
    padding: 10px 16px; box-shadow: 0 -2px 6px rgba(0,0,0,0.06);
  }}
  #controls button {{
    min-width: 72px; padding: 6px 12px; font-size: 14px;
    border: 1px solid #999; border-radius: 4px; background: #f5f5f5; cursor: pointer;
  }}
  #controls select {{ padding: 6px 8px; font-size: 14px; border-radius: 4px; }}
  #frame-slider {{ flex: 1; cursor: pointer; }}
  #frame-label {{ font-size: 13px; color: #444; white-space: nowrap; }}
</style>
<script>{plotly_js}</script>
</head>
<body>
{plotly_div}
<div id="controls">
  <button id="play-btn">▶ 播放</button>
  <select id="speed-select" title="播放速率">
    <option value="1">1x</option>
    <option value="2">2x</option>
    <option value="3">3x</option>
    <option value="4">4x</option>
    <option value="5">5x</option>
  </select>
  <label for="frame-slider">进度</label>
  <input type="range" id="frame-slider" min="0" max="{max_frame}" value="0" step="1">
  <span id="frame-label">帧: 0 / {max_frame} · 位置帧 0</span>
</div>
<script>{app_js}</script>
</body>
</html>"""

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        base_name = os.path.basename(bin_path[:dot_index])
        html_path = os.path.join(out_dir, f"{base_name}_playback.html")
    else:
        html_path = f"{bin_path[:dot_index]}_playback.html"
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(
            f"[TEST] 3D 航点播放已生成: {html_path} "
            f"(mission={mission_id}, pos_frames={len(pos_by_pf)}, light_frames={len(lights_by_f)})"
        )
    except Exception as e:
        logger.warning(f"[TEST] 保存播放 HTML 失败 {html_path}: {e}")
        return None
    return html_path


# ═══════════════════════════════════════════════════════════════
# DramaFrameInspectorPanel —— DRAMA 文件帧数据检查器
# ═══════════════════════════════════════════════════════════════
class DramaFrameInspectorPanel(QWidget):
    """DRAMA 文件帧数据检查器。

    加载 .drm 剧本文件，解析后以树状形式列出所有 protobuf 字段，
    合并同类项（如多架飞机的同名字段合并为一条路径），
    显示字段路径、类型、出现次数、取值范围。

    同时根据 C# DramaProto.cs 的完整 schema 检查缺失字段，
    在 ``Drama3_Not_Exist`` 根节点下列出 count=0 的字段。
    """

    # ── protobuf 类型 → 显示名称 ──
    _TYPE_NAMES: dict[int, str] = {
        1: "double", 2: "float", 3: "int64", 4: "uint64",
        5: "int32", 6: "fixed64", 7: "fixed32", 8: "bool",
        9: "string", 10: "group", 11: "message", 12: "bytes",
        13: "uint32", 14: "enum", 15: "sfixed32", 16: "sfixed64",
        17: "sint32", 18: "sint64",
    }

    # ── 阈值 ──
    _MAX_SCALAR_VALUES = 100

    # ═══════════════════════════════════════════════════════════
    # 完整 Schema（基于 D:\Work\dgcs4\Dgcs.Core\Domains\Dramas\DramaProto.cs）
    # 格式: {msg_name: {field_number: (field_name, type_or_msg, is_repeated?)}}
    # ═══════════════════════════════════════════════════════════

    # ── 标量类型（非 message，叶子节点）──
    _S = True  # scalar sentinel

    _FULL_SCHEMA: dict = {
        # ── PositionKeyFrame ──
        "PositionKeyFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("x",             "float"),
            3: ("y",             "float"),
            4: ("z",             "float"),
        },
        # ── PoseKeyFrame ──
        "PoseKeyFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("pitch",         "float"),
            3: ("roll",          "float"),
            4: ("yaw",           "float"),
        },
        # ── PayloadLight ──
        "PayloadLight": {
            1: ("r",             "uint32"),
            2: ("g",             "uint32"),
            3: ("b",             "uint32"),
        },
        # ── PayloadLightFrame ──
        "PayloadLightFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("lights",        "PayloadLight"),
        },
        # ── PayloadNova ──
        "PayloadNova": {
            1: ("power",         "uint32"),
        },
        # ── PayloadNovaFrame ──
        "PayloadNovaFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("novas",         "PayloadNova"),
        },
        # ── PayloadLazer ──
        "PayloadLazer": {
            1: ("r",             "uint32"),
            2: ("g",             "uint32"),
            3: ("b",             "uint32"),
            4: ("channel",       "int32"),
        },
        # ── PayloadLazerFrame ──
        "PayloadLazerFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("legacyLazers",  "PayloadLazer"),
            3: ("lazers",        "PayloadLazer", True),
        },
        # ── PayloadFireworkAngle ──
        "PayloadFireworkAngle": {
            1: ("channel",       "uint32"),
            2: ("angle",         "uint32"),
            3: ("type",          "uint32"),
        },
        # ── PayloadFireworks ──
        "PayloadFireworks": {
            1: ("firedPort",     "uint32"),
            2: ("angles",        "PayloadFireworkAngle", True),
        },
        # ── PayloadFireworksFrame ──
        "PayloadFireworksFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("fireworks",     "PayloadFireworks"),
        },
        # ── PayloadLantern ──
        "PayloadLantern": {
            1: ("isOn",          "bool"),
        },
        # ── PayloadLanternFrame ──
        "PayloadLanternFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("lanterns",      "PayloadLantern"),
        },
        # ── PayloadGimbal ──
        "PayloadGimbal": {
            1: ("pitch",         "float"),
            2: ("roll",          "float"),
            3: ("yaw",           "float"),
        },
        # ── PayloadGimbalVector ──
        "PayloadGimbalVector": {
            1: ("x",             "float"),
            2: ("y",             "float"),
            3: ("z",             "float"),
            4: ("channel",       "int32"),
        },
        # ── PayloadGimbalFrame ──
        "PayloadGimbalFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("gimbals",       "PayloadGimbal"),
            3: ("gimbalVectors", "PayloadGimbalVector", True),
        },
        # ── PayloadParachute ──
        "PayloadParachute": {
            1: ("channel",       "uint32"),
        },
        # ── PayloadParachuteFrame ──
        "PayloadParachuteFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("parachutes",    "PayloadParachute", True),
        },
        # ── PayloadFoldLantern ──
        "PayloadFoldLantern": {
            1: ("isOn",          "bool"),
            2: ("lanternStyle",  "uint32"),
            3: ("power",         "uint32"),
        },
        # ── PayloadFoldLanternFrame ──
        "PayloadFoldLanternFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("foldLantern",   "PayloadFoldLantern"),
        },
        # ── PayloadKongMingLantern ──
        "PayloadKongMingLantern": {
            1: ("isOn",          "bool"),
        },
        # ── PayloadKongMingLanternFrame ──
        "PayloadKongMingLanternFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("kongMingLantern", "PayloadKongMingLantern"),
        },
        # ── PayloadPeachLantern ──
        "PayloadPeachLantern": {
            1: ("isOn",          "bool"),
        },
        # ── PayloadPeachLanternFrame ──
        "PayloadPeachLanternFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("peachLantern",  "PayloadPeachLantern"),
        },
        # ── PayloadFishLantern ──
        "PayloadFishLantern": {
            1: ("isOn",          "bool"),
        },
        # ── PayloadFishLanternFrame ──
        "PayloadFishLanternFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("fishLantern",   "PayloadFishLantern"),
        },
        # ── PayloadConfetti ──
        "PayloadConfetti": {
            1: ("isOn",          "bool"),
        },
        # ── PayloadConfettiFrame ──
        "PayloadConfettiFrame": {
            1: ("frameIndex",    "uint32"),
            2: ("confetti",      "PayloadConfetti"),
        },
        # ── Vector3Proto ──
        "Vector3Proto": {
            1: ("x",             "float"),
            2: ("y",             "float"),
            3: ("z",             "float"),
        },
        # ── LaserAreaProto ──
        "LaserAreaProto": {
            1: ("points",        "Vector3Proto", True),
        },
        # ── DramaRangeInfo ──
        "DramaRangeInfo": {
            1: ("groundLazerArea", "LaserAreaProto"),
            2: ("skyLazerArea",    "LaserAreaProto"),
        },
        # ── DramaMapInfoProto ──
        "DramaMapInfoProto": {
            1: ("rotate",        "float"),
            2: ("name",          "string"),
            3: ("widthScale",    "float"),
            4: ("heightScale",   "float"),
            5: ("radius",        "float"),
            6: ("x",             "float"),
            7: ("y",             "float"),
            8: ("z",             "float"),
            9: ("lon",           "double"),
            10: ("lat",          "double"),
        },
        # ── DramaSegmentProto ──
        "DramaSegmentProto": {
            1: ("startFrameIndex", "uint32"),
            2: ("endFrameIndex",   "uint32"),
            3: ("segmentType",     "uint32"),
            4: ("description",     "string"),
        },
        # ── DramaDroneProto ──
        "DramaDroneProto": {
            1:  ("id",                      "uint32"),
            2:  ("droneType",               "uint32"),
            3:  ("returnType",              "uint32"),
            4:  ("playTimeOffset",          "uint32"),
            5:  ("positionKeyFrames",       "PositionKeyFrame",       True),
            6:  ("lightKeyFrames",          "PayloadLightFrame",      True),
            7:  ("novaKeyFrames",           "PayloadNovaFrame",       True),
            8:  ("fireworksKeyFrames",      "PayloadFireworksFrame",  True),
            9:  ("lanternKeyFrames",        "PayloadLanternFrame",    True),
            10: ("gimbalKeyFrames",         "PayloadGimbalFrame",     True),
            11: ("lazerKeyFrames",          "PayloadLazerFrame",      True),
            12: ("poseKeyFrames",           "PoseKeyFrame",           True),
            13: ("totalPointFrameCount",    "uint32"),
            14: ("totalPayloadFrameCount",  "uint32"),
            15: ("extendNovaKeyFrames",     "PayloadNovaFrame",       True),
            16: ("parachuteKeyFrames",      "PayloadParachuteFrame",  True),
            17: ("payloadFoldKeyFrames",    "PayloadFoldLanternFrame",True),
            18: ("kongMingLanternKeyFrames","PayloadKongMingLanternFrame", True),
            19: ("peachLanternKeyFrames",   "PayloadPeachLanternFrame",True),
            20: ("fishLanternKeyFrames",    "PayloadFishLanternFrame", True),
            21: ("confettiKeyFrames",       "PayloadConfettiFrame",    True),
        },
        # ── Drama3Proto ──
        "Drama3": {
            1:  ("dramaMissionId",  "string"),
            2:  ("droneCount",      "uint32"),
            3:  ("sceneName",       "string"),
            4:  ("description",     "string"),
            5:  ("payloadFps",      "uint32"),
            6:  ("pointFps",        "uint32"),
            7:  ("dramaVersion",    "uint32"),
            8:  ("drones",          "DramaDroneProto",       True),
            9:  ("map",             "DramaMapInfoProto"),
            10: ("segment",         "DramaSegmentProto",     True),
            11: ("authorName",      "string"),
            12: ("rangeInfo",       "DramaRangeInfo"),
        },
    }

    # ── 旧 pb2 消息名 → schema 名 (ListFields() DESCRIPTOR 名 → C# 名) ──
    _PB2_TO_SCHEMA: dict[str, str] = {
        "Drama3":          "Drama3",
        "Drone":           "DramaDroneProto",
        "MapInfo":         "DramaMapInfoProto",
        "SegmentInfo":     "DramaSegmentProto",
        "PositionKeyFrame":"PositionKeyFrame",
        "PoseKeyFrame":    "PoseKeyFrame",
        "PayloadLight":    "PayloadLight",
        "PayloadLightFrame":"PayloadLightFrame",
        "PayloadNova":     "PayloadNova",
        "PayloadNovaFrame": "PayloadNovaFrame",
        "PayloadLazer":    "PayloadLazer",
        "PayloadLazerFrame":"PayloadLazerFrame",
        "PayloadFireworks":"PayloadFireworks",
        "PayloadFireworksFrame":"PayloadFireworksFrame",
        "PayloadFireworkAngle":"PayloadFireworkAngle",
        "PayloadLantern":  "PayloadLantern",
        "PayloadLanternFrame":"PayloadLanternFrame",
        "PayloadGimbal":   "PayloadGimbal",
        "PayloadGimbalFrame":"PayloadGimbalFrame",
    }

    # ── 旧 pb2 字段号 → C# 字段名（当 schema 名与 pb2 不同时用 field_number 查）──
    # 此映射用于在 existing 树上匹配缺失字段时，按 field_number 查找
    _PB2_FIELD_TO_SCHEMA: dict[str, dict[int, str]] = {
        "Drama3": {
            # pb2 field 名称 → (field_number, schema_msg)
            # 用 field_number 做桥接
        },
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drm_path: str = ""
        self._build_ui()

    # ── UI 构建 ──
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── 文件选择行 ──
        grp_file = QGroupBox("剧本文件（.drm）")
        file_row = QHBoxLayout(grp_file)

        self._edit_drm_path = QLineEdit()
        self._edit_drm_path.setPlaceholderText("选择 .drm 剧本文件…")
        self._edit_drm_path.setReadOnly(True)
        file_row.addWidget(self._edit_drm_path, 1)

        self._btn_browse = QPushButton("选择文件…")
        self._btn_browse.clicked.connect(self._on_browse)
        file_row.addWidget(self._btn_browse)

        self._btn_load = QPushButton("加载解析")
        self._btn_load.setToolTip("解析 .drm 文件并汇总帧数据")
        self._btn_load.clicked.connect(self._on_load)
        self._btn_load.setMinimumHeight(30)
        file_row.addWidget(self._btn_load)

        root.addWidget(grp_file)

        # ── 摘要区 ──
        grp_summary = QGroupBox("数据摘要")
        summary_layout = QFormLayout(grp_summary)
        self._lbl_file = QLabel("—")
        summary_layout.addRow("文件:", self._lbl_file)
        self._lbl_drone_count = QLabel("—")
        summary_layout.addRow("飞机数量:", self._lbl_drone_count)
        self._lbl_frame_range = QLabel("—")
        summary_layout.addRow("帧范围:", self._lbl_frame_range)
        self._lbl_field_count = QLabel("—")
        summary_layout.addRow("字段路径数:", self._lbl_field_count)
        root.addWidget(grp_summary)

        # ── 树状字段浏览器（双 Tab） ──
        grp_tree = QGroupBox("字段结构")
        tree_layout = QVBoxLayout(grp_tree)

        self._tree_tabs = QTabWidget()
        self._tree_tabs.setObjectName("DRAMA_FIELD_TABS")

        # Tab 0: 按帧类型分类（合并同类项 + Not_Exist）
        self._tree_merged = QTreeWidget()
        self._tree_merged.setHeaderLabels(["字段路径", "类型", "出现次数", "取值范围 / 值"])
        self._tree_merged.setAlternatingRowColors(True)
        self._tree_merged.setRootIsDecorated(True)
        self._tree_merged.header().setStretchLastSection(True)
        self._tree_merged.setColumnWidth(0, 360)
        self._tree_merged.setColumnWidth(1, 70)
        self._tree_merged.setColumnWidth(2, 90)
        self._tree_merged.setColumnWidth(3, 280)
        self._tree_tabs.addTab(self._tree_merged, "按帧类型分类")

        # Tab 1: 按飞机分类（逐飞机展开，无 Not_Exist）
        self._tree_per_drone = QTreeWidget()
        self._tree_per_drone.setHeaderLabels(["字段路径", "类型", "出现次数", "取值范围 / 值"])
        self._tree_per_drone.setAlternatingRowColors(True)
        self._tree_per_drone.setRootIsDecorated(True)
        self._tree_per_drone.header().setStretchLastSection(True)
        self._tree_per_drone.setColumnWidth(0, 360)
        self._tree_per_drone.setColumnWidth(1, 70)
        self._tree_per_drone.setColumnWidth(2, 90)
        self._tree_per_drone.setColumnWidth(3, 280)
        self._tree_tabs.addTab(self._tree_per_drone, "按飞机分类")

        tree_layout.addWidget(self._tree_tabs)
        root.addWidget(grp_tree, 1)

        # ── 状态行 ──
        self._lbl_status = QLabel("就绪 — 请选择 .drm 文件")
        self._lbl_status.setWordWrap(True)
        root.addWidget(self._lbl_status)

    # ── 槽函数 ──
    @Slot()
    def _on_browse(self) -> None:
        start_dir = os.path.dirname(self._drm_path) if self._drm_path else os.path.expanduser("~")
        f, _ = QFileDialog.getOpenFileName(
            self, "选择剧本文件", start_dir,
            "剧本文件 (*.drm *.tmp);;所有文件 (*)",
        )
        if f:
            self._drm_path = f
            self._edit_drm_path.setText(f)

    @Slot()
    def _on_load(self) -> None:
        if not self._drm_path:
            QMessageBox.warning(self, "提示", "请先选择 .drm 文件。")
            return
        if not os.path.exists(self._drm_path):
            QMessageBox.warning(self, "文件不存在", f"文件不存在: {self._drm_path}")
            return

        self._btn_load.setEnabled(False)
        self._lbl_status.setText("解析中…")
        QApplication.processEvents()

        try:
            raw_bytes = self._decrypt_and_extract(self._drm_path)
            if raw_bytes is None:
                self._lbl_status.setText("解析失败: 无法解密/解压文件")
                self._btn_load.setEnabled(True)
                return

            from src.Protocol.drama.drone_show.Drama3_pb2 import Drama3
            drama3 = Drama3()
            drama3.ParseFromString(raw_bytes)

            self._populate_trees(drama3)
            self._lbl_status.setText(f"解析完成: {os.path.basename(self._drm_path)}")
        except Exception as e:
            self._lbl_status.setText(f"解析失败: {e}")
            logger.warning(f"FrameInspector 解析失败: {e}", exc_info=True)
        finally:
            self._btn_load.setEnabled(True)

    # ── 解密 + 解压（复用 drama_reader 逻辑） ──
    @staticmethod
    def _decrypt_and_extract(drm_path: str) -> bytes | None:
        """AES-CBC 解密 → ZIP 解压 → 返回 dramafile 的原始字节。"""
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import unpad
            import zipfile, io
            from src.Protocol.drama.drone_show.drama_reader import secret_key, secret_iv
        except ImportError:
            return None

        try:
            with open(drm_path, 'rb') as f:
                encrypted = f.read()

            cipher = AES.new(secret_key, AES.MODE_CBC, secret_iv)
            try:
                decrypted = unpad(cipher.decrypt(encrypted), AES.block_size)
            except ValueError:
                decrypted = cipher.decrypt(encrypted).rstrip(b'\x00')

            zip_buf = io.BytesIO(decrypted)
            with zipfile.ZipFile(zip_buf) as zf:
                if 'dramafile' not in zf.namelist():
                    return None
                return zf.read('dramafile')
        except Exception:
            return None

    # ── 树填充（双 Tab） ──
    def _populate_trees(self, drama3: Any) -> None:
        """填充两个 Tab：按帧类型分类 + 按飞机分类。"""
        # ── 公共：收集已有字段统计 ──
        stats = self._collect_message_stats(drama3, "Drama3")
        drone_count = 0
        for child in stats.children.values():
            if child.field_name == "drones":
                drone_count = child.count
                break

        # ── Tab 0: 按帧类型分类（合并同类项 + Not_Exist） ──
        self._populate_tab_merged(stats)

        # ── Tab 1: 按飞机分类（逐 drone + 公用字段，无 Not_Exist） ──
        self._populate_tab_per_drone(drama3, stats)

        # ── 更新摘要 ──
        frame_range = self._estimate_frame_range(stats, drone_count)
        self._lbl_file.setText(os.path.basename(self._drm_path))
        self._lbl_drone_count.setText(str(drone_count))
        self._lbl_frame_range.setText(frame_range)
        exist_leaves = self._count_leaf_paths(stats)
        not_exist_stats = self._build_not_exist_tree(stats, "Drama3")
        ne_leaves = self._count_leaf_paths(not_exist_stats)
        self._lbl_field_count.setText(f"{exist_leaves} (+{ne_leaves} 缺失)")

    # ── Tab 0: 按帧类型分类 ──
    def _populate_tab_merged(self, stats: _FieldStats) -> None:
        """Tab 0 — 合并同类项 + Drama3_Not_Exist。"""
        tree = self._tree_merged
        tree.clear()

        # Drama3 已有字段
        root_exist = QTreeWidgetItem(tree, ["Drama3", "message", "", ""])
        root_exist.setExpanded(True)
        for child in stats.children.values():
            self._build_tree_node(root_exist, child)

        # Drama3_Not_Exist
        not_exist_stats = self._build_not_exist_tree(stats, "Drama3")
        if not_exist_stats.children:
            root_ne = QTreeWidgetItem(tree, [
                "Drama3_Not_Exist", "message", "",
                "（schema 中定义但数据中未出现的字段）"
            ])
            font = root_ne.font(0)
            font.setItalic(True)
            for col in range(4):
                root_ne.setFont(col, font)
            root_ne.setForeground(0, Qt.gray)
            root_ne.setForeground(3, Qt.gray)
            root_ne.setExpanded(True)
            for child in not_exist_stats.children.values():
                self._build_tree_node(root_ne, child)

    # ── Tab 1: 按飞机分类 ──
    def _populate_tab_per_drone(self, drama3: Any,
                                  merged_stats: _FieldStats) -> None:
        """Tab 1 — 每个 drone 独立分支 + 公用字段，无 Not_Exist。"""
        tree = self._tree_per_drone
        tree.clear()

        root = QTreeWidgetItem(tree, ["Drama3", "message", "", ""])
        root.setExpanded(True)

        # ── 非 drone 字段（从 merged_stats 取，与 Tab 0 相同） ──
        for child in merged_stats.children.values():
            if child.field_name == "drones":
                continue
            self._build_tree_node(root, child)

        # ── 逐 drone 展开 ──
        drones_field = merged_stats.children.get("drones")
        if drones_field is None or drones_field.count == 0:
            return

        # 创建 drone 父节点（文件夹）
        drones_parent = QTreeWidgetItem(root, [
            "drones", "message", str(drones_field.count),
            f"({drones_field.count} airplanes)"
        ])
        drones_parent.setExpanded(True)

        for drone in drama3.drones:
            drone_id = drone.id
            drone_label = f"drone_{drone_id} (id={drone_id})"
            drone_stats = self._collect_message_stats(drone, f"drone_{drone_id}")
            drone_stats.field_name = drone_label
            drone_stats.count = 1
            drone_item = self._build_tree_node(drones_parent, drone_stats)
            # 首层展开关键帧类型便于浏览
            for i in range(drone_item.childCount()):
                child = drone_item.child(i)
                if child.text(0) in (
                    "positionKeyFrames", "lightKeyFrame",
                    "poseKeyFrames", "novaKeyFrame", "fireworksKeyFrame",
                    "lanternKeyFrame", "gimbalKeyFrame", "lazerKeyFrame",
                ):
                    child.setExpanded(True)

    def _count_leaf_paths(self, stats: "_FieldStats") -> int:
        if not stats.children:
            return 1
        return sum(self._count_leaf_paths(c) for c in stats.children.values())

    def _estimate_frame_range(self, root_stats: "_FieldStats", drone_count: int) -> str:
        try:
            drones_stats = root_stats.children.get("drones")
            if drones_stats and drones_stats.children:
                for key in ("totalPointFrameCount", "totalPayloadFrameCount"):
                    tpf = drones_stats.children.get(key)
                    if tpf and tpf.scalar_values:
                        max_val = max(tpf.scalar_values)
                        return f"0 ~ {max_val - 1}" if max_val > 0 else "—"
        except Exception:
            pass
        return "—"

    # ═══════════════════════════════════════════════════════════
    # 递归采集 protobuf 消息字段统计
    # ═══════════════════════════════════════════════════════════
    class _FieldStats:
        """字段统计节点。"""
        __slots__ = ("path", "field_name", "proto_type", "count",
                     "scalar_values", "children", "present_field_numbers")
        def __init__(self, path: str, field_name: str, proto_type: str) -> None:
            self.path = path
            self.field_name = field_name
            self.proto_type = proto_type
            self.count = 0
            self.scalar_values: list = []
            self.children: dict = {}
            self.present_field_numbers: set[int] = set()

    def _collect_message_stats(self, msg: Any, path_prefix: str) -> _FieldStats:
        """递归收集一条 protobuf 消息的所有字段统计。

        对 repeated message 字段，遍历全部元素并合并统计。
        同时记录已出现的 field_number 用于后续 schema 差异对比。
        """
        name = path_prefix.rsplit(".", 1)[-1] if "." in path_prefix else path_prefix
        root = self._FieldStats(path_prefix, name, "message")
        root.count = 1

        # 遍历已知字段（ListFields 只返回有值的字段）
        for fd, value in msg.ListFields():
            fd_number = fd.number
            fd_name = fd.name
            fd_type = fd.type
            fd_repeated = (fd.is_repeated if hasattr(fd, 'is_repeated')
                           else (fd.label == fd.LABEL_REPEATED))

            root.present_field_numbers.add(fd_number)
            type_name = self._TYPE_NAMES.get(fd_type, f"type_{fd_type}")

            if type_name == "message":
                suffix = f"{fd_name}[]" if fd_repeated else fd_name
                child_path = f"{path_prefix}.{suffix}"
                child_stats = root.children.get(fd_name)
                if child_stats is None:
                    child_stats = self._FieldStats(child_path, fd_name, "message")
                    root.children[fd_name] = child_stats

                items = list(value) if fd_repeated else [value]
                child_stats.count += len(items)
                for item in items:
                    sub = self._collect_message_stats(item, child_path)
                    # 修复 Bug#3：补齐 ListFields 未返回的 proto3 默认值字段
                    # 例如 OFF 帧的 lazer (r=0, g=0, b=0, channel=3) 中 r/g/b 是默认值，
                    # ListFields() 不返回这些字段，但统计时仍应视为存在
                    self._fill_proto3_default_values(item, sub, child_path)
                    # 合并子消息的 present_field_numbers（并集）
                    child_stats.present_field_numbers |= sub.present_field_numbers
                    # 合并子消息的子字段
                    for sub_child in sub.children.values():
                        existing = child_stats.children.get(sub_child.field_name)
                        if existing is None:
                            child_stats.children[sub_child.field_name] = sub_child
                        else:
                            existing.count += sub_child.count
                            existing.present_field_numbers |= sub_child.present_field_numbers
                            existing.scalar_values.extend(sub_child.scalar_values)
                            if len(existing.scalar_values) > self._MAX_SCALAR_VALUES:
                                existing.scalar_values = existing.scalar_values[:self._MAX_SCALAR_VALUES]
                            for sc2 in sub_child.children.values():
                                ec = existing.children.get(sc2.field_name)
                                if ec is None:
                                    existing.children[sc2.field_name] = sc2
                                else:
                                    ec.count += sc2.count
                                    ec.present_field_numbers |= sc2.present_field_numbers
                                    ec.scalar_values.extend(sc2.scalar_values)
                                    # 修复 Bug#3 后续：合并第 3 层（如 lazers.b）
                                    for sc3 in sc2.children.values():
                                        eb = ec.children.get(sc3.field_name)
                                        if eb is None:
                                            ec.children[sc3.field_name] = sc3
                                        else:
                                            eb.count += sc3.count
                                            eb.present_field_numbers |= sc3.present_field_numbers
                                            eb.scalar_values.extend(sc3.scalar_values)
                                            if len(eb.scalar_values) > self._MAX_SCALAR_VALUES:
                                                eb.scalar_values = eb.scalar_values[:self._MAX_SCALAR_VALUES]
            else:
                suffix = f"{fd_name}[]" if fd_repeated else fd_name
                child_path = f"{path_prefix}.{suffix}"
                child_stats = root.children.get(fd_name)
                if child_stats is None:
                    child_stats = self._FieldStats(child_path, fd_name, type_name)
                    root.children[fd_name] = child_stats

                items = list(value) if fd_repeated else [value]
                child_stats.count += len(items)
                for v in items:
                    if len(child_stats.scalar_values) < self._MAX_SCALAR_VALUES:
                        child_stats.scalar_values.append(v)

        # 尝试未知字段
        try:
            unknown = msg.UnknownFields()
            self._collect_unknown_fields(unknown, path_prefix, root)
        except (NotImplementedError, AttributeError, TypeError):
            pass

        return root

    def _collect_unknown_fields(self, unknown: Any, path_prefix: str,
                                 root: _FieldStats) -> None:
        return  # protobuf 7.x upb 不支持迭代未知字段

    # ═══════════════════════════════════════════════════════════
    # 补齐 proto3 默认值字段
    # ═══════════════════════════════════════════════════════════
    # proto3 默认值（如 r=0/g=0/b=0）不会被 ListFields() 返回。
    # 但统计时这些字段仍应视为「存在」，
    # 否则像 OFF 帧的 lazer (r=0,g=0,b=0,channel=3) 会被完全忽略，
    # 导致 b 节点只能体现 ON 帧的 b=25，丢失 0 值。
    def _fill_proto3_default_values(self, msg: Any, sub_stats: _FieldStats,
                                      path_prefix: str) -> None:
        """为 msg 中 ListFields() 未返回的标量字段补齐默认值。

        Args:
            msg: 当前处理的 protobuf 消息实例（repeated message 的一项）
            sub_stats: msg 对应的 _FieldStats 节点
            path_prefix: msg 的字段路径（用于 _FieldStats.path）
        """
        if not hasattr(msg, 'DESCRIPTOR'):
            return

        # 找出当前 msg 中 ListFields() 实际返回的字段名
        try:
            set_field_names = {fd.name for fd, _ in msg.ListFields()}
        except Exception:
            return

        # 遍历 schema 中所有标量字段，对未在 set_field_names 中的补齐默认值
        for fd in msg.DESCRIPTOR.fields:
            # 跳过 message 类型和 repeated 字段
            if fd.type == 11:  # TYPE_MESSAGE
                continue
            if fd.is_repeated:  # LABEL_REPEATED (新 protobuf 用 is_repeated)
                continue
            fd_name = fd.name
            if fd_name in sub_stats.children:
                continue  # 已被 ListFields 返回，跳过
            type_name = self._TYPE_NAMES.get(fd.type)
            if type_name is None:
                continue
            # 跳过 string/bytes/enum（这些类型不适合用 0 作为默认值）
            if type_name in ("string", "bytes", "enum"):
                continue
            # 取默认值
            if type_name in ("uint32", "uint64", "int32", "int64",
                              "fixed32", "fixed64", "sfixed32", "sfixed64",
                              "sint32", "sint64"):
                default_val: Any = 0
            elif type_name in ("float", "double"):
                default_val = 0.0
            elif type_name == "bool":
                default_val = False
            else:
                continue
            # 补齐到 sub_stats.children
            default_stats = self._FieldStats(
                f"{path_prefix}.{fd_name}", fd_name, type_name)
            default_stats.count = 1  # 当前 msg 贡献 1
            default_stats.scalar_values.append(default_val)
            default_stats.present_field_numbers.add(fd.number)
            sub_stats.children[fd_name] = default_stats

    # ═══════════════════════════════════════════════════════════
    # 缺失字段树构建
    # ═══════════════════════════════════════════════════════════
    def _build_not_exist_tree(self, existing: _FieldStats,
                                schema_msg: str,
                                _is_top: bool = True) -> _FieldStats:
        """对比 schema 和已有数据，构建缺失字段统计树。

        Args:
            existing: 从实际数据收集的已有字段统计
            schema_msg: schema 中的消息类型名
            _is_top: 是否是顶层调用（顶层报缺失标量，递归层不报）

        检测逻辑：
        - 顶层 (Drama3)：显示所有缺失字段（含标量和消息）
        - 递归层 (子消息)：仅显示缺失的 message 字段。
          标量字段在 proto3 中默认值(=0/空)无法区分「未设置」与「设置为默认值」，
          因此递归层不将缺失标量视为「字段缺失」，避免误报。
        """
        root = self._FieldStats("Drama3_Not_Exist", "Drama3_Not_Exist", "message")
        root.count = 0

        schema_fields = self._FULL_SCHEMA.get(schema_msg)
        if schema_fields is None:
            return root

        pb2_names = self._get_pb2_field_names(schema_msg)

        _SCALAR_TYPES = frozenset({
            "uint32", "uint64", "int32", "int64", "float", "double",
            "string", "bytes", "bool", "fixed32", "fixed64",
            "sfixed32", "sfixed64", "sint32", "sint64", "enum",
        })

        for fd_num, fd_def in schema_fields.items():
            fd_name = fd_def[0]
            type_or_msg = fd_def[1]
            is_repeated = len(fd_def) > 2 and fd_def[2]
            is_scalar = type_or_msg in _SCALAR_TYPES

            # 用 C# 名或 pb2 名在 existing.children 中查找
            exist_child = existing.children.get(fd_name)
            if exist_child is None and fd_num in pb2_names:
                exist_child = existing.children.get(pb2_names[fd_num])

            if exist_child is not None:
                # 字段存在 → 递归检查子消息中是否还有缺失
                if not is_scalar:
                    sub_ne = self._build_not_exist_tree(
                        exist_child, type_or_msg, _is_top=False)
                    if sub_ne.children:
                        child_stats = self._FieldStats(
                            f"Drama3_Not_Exist.{fd_name}", fd_name, "message")
                        child_stats.count = 0
                        for sub_c in sub_ne.children.values():
                            child_stats.children[sub_c.field_name] = sub_c
                        root.children[fd_name] = child_stats
            else:
                # 字段不存在
                # 递归层：跳过标量（proto3 默认值歧义），仅报告 message 字段缺失
                if not _is_top and is_scalar:
                    continue
                suffix = "[]" if is_repeated else ""
                child_path = f"Drama3_Not_Exist.{fd_name}{suffix}"

                if type_or_msg in ("uint32", "uint64", "int32", "int64",
                    "float", "double", "string", "bytes", "bool",
                    "fixed32", "fixed64", "sfixed32", "sfixed64",
                    "sint32", "sint64", "enum"):
                    # 标量 — 叶子节点
                    child_stats = self._FieldStats(child_path, fd_name, type_or_msg)
                    child_stats.count = 0
                    root.children[fd_name] = child_stats
                else:
                    # message — 递归展开其完整子字段树
                    child_stats = self._FieldStats(child_path, fd_name, "message")
                    child_stats.count = 0
                    # 展开此 message 的完整 schema 子字段（全部 count=0）
                    self._expand_full_schema(child_stats, type_or_msg,
                                             child_path)
                    root.children[fd_name] = child_stats

        return root

    def _expand_full_schema(self, parent_stats: _FieldStats,
                              schema_msg: str, path_prefix: str) -> None:
        """递归展开一个消息类型的完整 schema，全部 count=0。"""
        schema_fields = self._FULL_SCHEMA.get(schema_msg)
        if schema_fields is None:
            return

        for fd_num, fd_def in schema_fields.items():
            fd_name = fd_def[0]
            type_or_msg = fd_def[1]
            is_repeated = len(fd_def) > 2 and fd_def[2]

            suffix = "[]" if is_repeated else ""
            child_path = f"{path_prefix}.{fd_name}{suffix}"

            if type_or_msg in ("uint32", "uint64", "int32", "int64",
                "float", "double", "string", "bytes", "bool",
                "fixed32", "fixed64", "sfixed32", "sfixed64",
                "sint32", "sint64", "enum"):
                child = self._FieldStats(child_path, fd_name, type_or_msg)
                child.count = 0
                parent_stats.children[fd_name] = child
            else:
                child = self._FieldStats(child_path, fd_name, "message")
                child.count = 0
                self._expand_full_schema(child, type_or_msg, child_path)
                parent_stats.children[fd_name] = child

    # ── pb2 字段名映射（旧 pb2 DESCRIPTOR → C# schema 名） ──
    _pb2_field_name_cache: dict[str, dict[int, str]] = {}

    def _get_pb2_field_names(self, schema_msg: str) -> dict[int, str]:
        """获取 schema 消息类型在旧 pb2 中的 field_number → pb2_field_name 映射。

        用于在 existing.children 中同时尝试 C# 字段名和 pb2 字段名查找。
        结果会被缓存。
        """
        if schema_msg in self._pb2_field_name_cache:
            return self._pb2_field_name_cache[schema_msg]

        # 反向映射：schema_msg → pb2 DESCRIPTOR 名
        pb2_name = schema_msg  # 多数名称一致
        for k, v in self._PB2_TO_SCHEMA.items():
            if v == schema_msg:
                pb2_name = k
                break

        mapping: dict[int, str] = {}
        try:
            from src.Protocol.drama.drone_show import Drama3_pb2 as _pb2
            cls = getattr(_pb2, pb2_name, None)
            if cls is not None:
                for fd in cls.DESCRIPTOR.fields:
                    mapping[fd.number] = fd.name
        except Exception:
            pass

        self._pb2_field_name_cache[schema_msg] = mapping
        return mapping

    # ═══════════════════════════════════════════════════════════
    # 构建 QTreeWidget 节点
    # ═══════════════════════════════════════════════════════════
    def _build_tree_node(self, parent_item: QTreeWidgetItem,
                         stats: _FieldStats) -> "QTreeWidgetItem":
        """递归构建树节点。count=0 的节点使用灰色斜体。返回创建的 item。"""
        if stats.proto_type == "message":
            count_str = str(stats.count) if stats.count else "0"
            value_str = f"({stats.count} items)" if stats.count else "(0 items)"
        else:
            count_str = str(stats.count) if stats.count else "0"
            value_str = "—" if stats.count == 0 else self._format_scalar_range(stats)

        item = QTreeWidgetItem(parent_item, [
            stats.field_name,
            stats.proto_type,
            count_str,
            value_str,
        ])

        # 缺失字段 (count=0) 灰色斜体
        if stats.count == 0 and stats.proto_type != "message":
            font = item.font(0)
            font.setItalic(True)
            for col in range(4):
                item.setFont(col, font)
                item.setForeground(col, Qt.gray)
        elif stats.count == 0:
            font = item.font(0)
            font.setItalic(True)
            for col in range(4):
                item.setFont(col, font)
            item.setForeground(0, Qt.gray)
            item.setForeground(2, Qt.gray)

        if stats.proto_type == "message" and stats.children:
            # 缺失节点默认折叠，已有节点默认展开
            is_missing = stats.count == 0
            item.setExpanded(not is_missing)
            sorted_children = sorted(stats.children.values(),
                                     key=lambda c: c.field_name)
            for child in sorted_children:
                self._build_tree_node(item, child)

        return item

    def _format_scalar_range(self, stats: _FieldStats) -> str:
        """根据收集的标量值生成范围/值描述。

        显示策略：
        - 无值: "—"
        - 单 unique 值: "value" 或 "value (count)" (当 count > 1 时)
        - 2-5 unique 值: "v1 (n1), v2 (n2), ..." 显示各值出现次数
        - >5 unique 值: "lo ~ hi" 退回到范围显示
        """
        vals = stats.scalar_values
        if not vals:
            return "—"

        unique = set(vals)

        if stats.proto_type == "bool":
            if len(unique) == 1:
                v = list(unique)[0]
                return f"{v} ({stats.count})" if stats.count > 1 else str(v)
            return f"True ({vals.count(True)}) / False ({vals.count(False)})"

        if stats.proto_type in ("string", "bytes"):
            if len(unique) == 1:
                s = str(list(unique)[0])
                return s[:60] + ("…" if len(s) > 60 else "")
            strs = [str(v) for v in list(unique)[:6]]
            if len(unique) > 6:
                strs.append(f"…等 {len(unique)} 种")
            return " | ".join(s[:30] for s in strs)

        numeric_vals = [v for v in vals if isinstance(v, (int, float))]
        if not numeric_vals:
            return str(vals[0]) if len(vals) == 1 else f"({len(vals)} values)"

        # ── 单 unique 值：显示数值 + 出现次数 ──
        if len(unique) == 1:
            v = list(unique)[0]
            return f"{v} ({stats.count})" if stats.count > 1 else str(v)

        # ── 2-5 个 unique 值：显示每个值的出现次数 ──
        if len(unique) <= 5:
            # 按首次出现顺序展示
            seen: list = []
            counts: list = []
            for v in numeric_vals:
                if v not in seen:
                    seen.append(v)
                    counts.append(1)
                else:
                    idx = seen.index(v)
                    counts[idx] += 1
            parts = [f"{v} ({cnt})" for v, cnt in zip(seen, counts)]
            return ", ".join(parts)

        # ── >5 unique 值：退回到范围显示 ──
        lo = min(numeric_vals)
        hi = max(numeric_vals)
        if lo == hi:
            return str(lo)

        if stats.proto_type in ("uint32", "uint64", "int32", "int64",
                                 "fixed32", "fixed64", "sfixed32", "sfixed64",
                                 "sint32", "sint64", "enum"):
            return f"{lo} ~ {hi}"
        else:
            return f"{lo:.3f} ~ {hi:.3f}"


# ═══════════════════════════════════════════════════════════════
# DramaProcessingPanel —— 剧本处理主面板
# ═══════════════════════════════════════════════════════════════
class DramaProcessingPanel(QWidget):
    """剧本处理 Tab —— 含航点解析对比 / 航点篡改 / 帧数据检查 / 航迹对比四个子 Tab。

    航点解析/对比功能已完全独立为本模块的模块级函数，不再依赖假飞机 sender。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # ── 子 Tab ──
        self._sub_tabs = QTabWidget(self)
        self._sub_tabs.setObjectName("DRAMA_SUB_TABS")

        self._wp_compare_panel = WaypointParseComparePanel()
        self._wp_compare_panel.setObjectName("DRAMA_WP_COMPARE")
        self._sub_tabs.addTab(self._wp_compare_panel, "航点解析对比")

        self._wp_tamper_panel = WaypointTamperPanel()
        self._wp_tamper_panel.setObjectName("DRAMA_WP_TAMPER")
        self._sub_tabs.addTab(self._wp_tamper_panel, "航点篡改")

        self._frame_inspector = DramaFrameInspectorPanel()
        self._frame_inspector.setObjectName("DRAMA_FRAME_INSPECTOR")
        self._sub_tabs.addTab(self._frame_inspector, "帧数据检查")

        self._track_compare_panel = WaypointTrackComparePanel()
        self._track_compare_panel.setObjectName("DRAMA_TRACK_COMPARE")
        self._sub_tabs.addTab(self._track_compare_panel, "航迹对比")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._sub_tabs)


# ═══════════════════════════════════════════════════════════════
# _DramaWorker — 后台线程执行 Plotly HTML 生成
# ═══════════════════════════════════════════════════════════════
class _DramaWorker(QThread):
    """在后台线程执行 visualize_drama_3d / visualize_drama_compare /
    visualize_drama_playback，避免同步生成 Plotly HTML 时冻结 GUI。
    """

    progress = Signal(str)           # 状态栏文本
    file_done = Signal(str)          # 单个文件完成 → 自动打开 HTML（仅 parse）
    file_done_batch = Signal(str, int)  # 单个文件完成（带批次号）→ 航迹对比 HTML 列表
    finished = Signal(bool, str)     # 全部完成 → (成功?, 汇总文本)

    def __init__(self, task_type: str, files: list[str],
                 batch_no: int = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._task_type = task_type   # "parse" | "compare" | "playback"
        self._files = files
        self._batch_no = batch_no

    def run(self) -> None:
        if self._task_type == "parse":
            self._run_parse()
        elif self._task_type == "playback":
            self._run_playback()
        elif self._task_type == "compare_timeline":
            self._run_compare_timeline()
        else:
            self._run_compare()

    def _run_parse(self) -> None:
        ok = 0
        last_html = ""
        total = len(self._files)
        for i, f in enumerate(self._files, 1):
            if self.isInterruptionRequested():
                return
            if not os.path.exists(f):
                self.progress.emit(f"[{i}/{total}] 文件不存在: {f}")
                continue
            self.progress.emit(f"[{i}/{total}] 解析中: {os.path.basename(f)} …")
            try:
                html_path = visualize_drama_3d(f)  # ← CPU 密集调用在工作线程
                if html_path:
                    ok += 1
                    last_html = html_path
                    self.progress.emit(
                        f"[{i}/{total}] 解析成功: {os.path.basename(html_path)}"
                    )
                    self.file_done.emit(html_path)
                else:
                    self.progress.emit(
                        f"[{i}/{total}] 解析失败（返回空）: {os.path.basename(f)}"
                    )
            except Exception as e:
                self.progress.emit(
                    f"[{i}/{total}] 解析异常: {os.path.basename(f)} - {e}"
                )
        self.finished.emit(True, f"解析完成: {ok}/{total} 成功")

    def _run_playback(self) -> None:
        ok = 0
        total = len(self._files)
        for i, f in enumerate(self._files, 1):
            if self.isInterruptionRequested():
                return
            if not os.path.exists(f):
                self.progress.emit(f"[{i}/{total}] 文件不存在: {f}")
                continue
            self.progress.emit(f"[{i}/{total}] 解析播放中: {os.path.basename(f)} …")
            try:
                html_path = visualize_drama_playback(f)  # ← CPU 密集调用在工作线程
                if html_path:
                    ok += 1
                    self.progress.emit(
                        f"[{i}/{total}] 已生成: {os.path.basename(html_path)}"
                    )
                    self.file_done_batch.emit(html_path, self._batch_no)
                else:
                    self.progress.emit(
                        f"[{i}/{total}] 解析失败（返回空）: {os.path.basename(f)}"
                    )
            except Exception as e:
                self.progress.emit(
                    f"[{i}/{total}] 解析异常: {os.path.basename(f)} - {e}"
                )
        self.finished.emit(True, f"剧本解析完成: {ok}/{total} 成功")

    def _run_compare(self) -> None:
        f1, f2 = self._files[0], self._files[1]
        self.progress.emit(f"对比中: {os.path.basename(f1)} vs {os.path.basename(f2)} …")
        try:
            html_path = visualize_drama_compare(f1, f2)  # ← CPU 密集调用在工作线程
            if html_path:
                self.progress.emit(f"对比完成: {os.path.basename(html_path)}")
                self.file_done.emit(html_path)
                self.finished.emit(True, f"对比完成: {os.path.basename(html_path)}")
            else:
                self.finished.emit(False, "对比失败（返回空）")
        except Exception as e:
            self.finished.emit(False, f"对比异常: {e}")

    def _run_compare_timeline(self) -> None:
        f1, f2 = self._files[0], self._files[1]
        self.progress.emit(
            f"时间对齐对比中: {os.path.basename(f1)} vs {os.path.basename(f2)} …"
        )
        try:
            html_path = visualize_drama_compare_timeline(f1, f2)  # ← CPU 密集调用在工作线程
            if html_path:
                self.progress.emit(f"对比完成: {os.path.basename(html_path)}")
                self.file_done_batch.emit(html_path, self._batch_no)
                self.finished.emit(True, f"剧本对比完成: {os.path.basename(html_path)}")
            else:
                self.finished.emit(False, "剧本对比失败（返回空，请确认两个 bin 存在且文件名含 yyyymmdd_hhmmss 时间戳）")
        except Exception as e:
            self.finished.emit(False, f"剧本对比异常: {e}")


# ═══════════════════════════════════════════════════════════════
# WaypointParseComparePanel —— 航点解析对比子 Tab
# ═══════════════════════════════════════════════════════════════
class WaypointParseComparePanel(QWidget):
    """航点解析对比面板。

    功能：
    - 选择 bin 文件（自动定位到 drama/ 目录）
    - 「航点解析」按钮：对每个选中文件调用模块级 visualize_drama_3d → 自动打开 HTML
    - 「航点对比」按钮：对恰好 2 个选中文件调用模块级 visualize_drama_compare → 自动打开 HTML

    航点解析/对比函数为本模块的独立函数，不依赖假飞机 sender。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selected_files: list[str] = []

        self._build_ui()
        self._ensure_drama_dir()

    # ── UI 构建 ──
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── 文件选择 ──
        grp_file = QGroupBox("Bin 文件选择")
        file_layout = QVBoxLayout(grp_file)

        # 文件列表
        self._file_list = QListWidget()
        self._file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._file_list.setMinimumHeight(120)
        file_layout.addWidget(self._file_list)

        # 按钮行
        btn_row = QHBoxLayout()
        self._btn_select = QPushButton("选择文件…")
        self._btn_select.setToolTip("打开文件选择对话框，自动定位到 drama/ 目录")
        self._btn_select.clicked.connect(self._on_select_files)
        btn_row.addWidget(self._btn_select)

        self._btn_clear = QPushButton("清空列表")
        self._btn_clear.clicked.connect(self._on_clear_files)
        btn_row.addWidget(self._btn_clear)
        btn_row.addStretch()
        file_layout.addLayout(btn_row)

        root.addWidget(grp_file)

        # ── 操作按钮 ──
        grp_action = QGroupBox("操作")
        action_layout = QHBoxLayout(grp_action)

        self._btn_parse = QPushButton("航点解析")
        self._btn_parse.setToolTip("对列表中每个 bin 文件逐次执行航点解析（3D 可视化）")
        self._btn_parse.setMinimumHeight(36)
        self._btn_parse.clicked.connect(self._on_parse)
        action_layout.addWidget(self._btn_parse)

        self._btn_compare = QPushButton("航点对比")
        self._btn_compare.setToolTip("对恰好 2 个 bin 文件执行航点对比（差异可视化）")
        self._btn_compare.setMinimumHeight(36)
        self._btn_compare.clicked.connect(self._on_compare)
        action_layout.addWidget(self._btn_compare)

        root.addWidget(grp_action)

        # ── 状态 ──
        self._lbl_status = QLabel("就绪 — 请选择 bin 文件")
        self._lbl_status.setWordWrap(True)
        root.addWidget(self._lbl_status)
        root.addStretch()

    def _ensure_drama_dir(self) -> None:
        os.makedirs(DEFAULT_DRAMA_DIR, exist_ok=True)

    # ── 槽函数 ──
    @Slot()
    def _on_select_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择 Bin 文件", DEFAULT_DRAMA_DIR,
            "Bin 文件 (*.bin);;所有文件 (*)",
        )
        if files:
            for f in files:
                if f not in self._selected_files:
                    self._selected_files.append(f)
                    self._file_list.addItem(f)
            self._lbl_status.setText(f"已选择 {len(self._selected_files)} 个文件")

    @Slot()
    def _on_clear_files(self) -> None:
        self._selected_files.clear()
        self._file_list.clear()
        self._lbl_status.setText("就绪 — 请选择 bin 文件")

    @Slot()
    def _on_parse(self) -> None:
        """在后台线程逐次对每个文件调用 visualize_drama_3d。"""
        if not self._selected_files:
            QMessageBox.warning(self, "提示", "请先选择 bin 文件。")
            return

        self._btn_parse.setEnabled(False)
        self._btn_compare.setEnabled(False)

        self._worker = _DramaWorker("parse", list(self._selected_files), self)
        self._worker.progress.connect(self._lbl_status.setText)
        self._worker.file_done.connect(self._open_if_exists)
        self._worker.finished.connect(self._on_parse_done)
        self._worker.start()

    @Slot()
    def _on_compare(self) -> None:
        """在后台线程对恰好 2 个文件调用 visualize_drama_compare。"""
        if len(self._selected_files) != 2:
            QMessageBox.warning(
                self, "文件数量错误",
                f"航点对比需要恰好 2 个文件，当前选择了 {len(self._selected_files)} 个。\n"
                f"请在列表中保留恰好 2 个文件后重试。",
            )
            return

        f1, f2 = self._selected_files[0], self._selected_files[1]
        if not os.path.exists(f1):
            QMessageBox.warning(self, "文件不存在", f"文件不存在: {f1}")
            return
        if not os.path.exists(f2):
            QMessageBox.warning(self, "文件不存在", f"文件不存在: {f2}")
            return

        self._btn_parse.setEnabled(False)
        self._btn_compare.setEnabled(False)

        self._worker = _DramaWorker("compare", [f1, f2], self)
        self._worker.progress.connect(self._lbl_status.setText)
        self._worker.file_done.connect(self._open_if_exists)
        self._worker.finished.connect(self._on_compare_done)
        self._worker.start()

    # ── Worker 回调 ──
    @Slot(str)
    def _open_if_exists(self, html_path: str) -> None:
        """工作线程完成单个文件后自动打开 HTML（主线程安全）。"""
        if html_path and os.path.exists(html_path):
            os.startfile(html_path)

    @Slot(bool, str)
    def _on_parse_done(self, success: bool, summary: str) -> None:
        self._lbl_status.setText(summary)
        self._btn_parse.setEnabled(True)
        self._btn_compare.setEnabled(True)

    @Slot(bool, str)
    def _on_compare_done(self, success: bool, summary: str) -> None:
        self._lbl_status.setText(summary)
        self._btn_parse.setEnabled(True)
        self._btn_compare.setEnabled(True)


# ═══════════════════════════════════════════════════════════════
# WaypointTrackComparePanel —— 航迹对比子 Tab
# ═══════════════════════════════════════════════════════════════
class WaypointTrackComparePanel(QWidget):
    """航迹对比面板（剧本处理第 4 个子 Tab）。

    两个控件盒：
    - Box1 「Bin 文件选择」：最多 2 个 bin，展示区固定高度容纳 2 行，
      标题文本右侧 4 个按钮（选择文件 / 清空列表 / 剧本解析 / 剧本对比）
    - Box2 「解析结果 HTML 列表」：文件链接（点击打开）/ 生成时间 / 批次，
      同一批次（同时解析多个 bin）的行使用相同背景色

    - 「剧本解析」：对每个选中 bin 调用 ``visualize_drama_playback``
      生成带帧播放进度条的 3D 航点+灯光 HTML
    - 「剧本对比」：预留（补点剧本 vs 原剧本，需额外输入开始绝对时间）
    """

    # 同一批次行的背景色轮换
    _BATCH_COLORS = [
        QColor("#d5e8d4"),  # 淡绿
        QColor("#dae8fc"),  # 淡蓝
        QColor("#ffe6cc"),  # 淡橙
        QColor("#e1d5e7"),  # 淡紫
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selected_files: list[str] = []
        self._norm_paths: set[str] = set()
        self._batch_no = 0
        self._worker: _DramaWorker | None = None
        self._build_ui()

    # ── UI 构建 ──
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── Box1: Bin 文件选择 ──
        grp_file = QGroupBox()
        file_layout = QVBoxLayout(grp_file)
        file_layout.setSpacing(6)

        # 标题文本 + 4 按钮
        title_row = QHBoxLayout()
        lbl_title = QLabel("Bin 文件选择")
        _font = lbl_title.font()
        _font.setBold(True)
        lbl_title.setFont(_font)
        title_row.addWidget(lbl_title)
        title_row.addStretch()

        self._btn_select = QPushButton("选择文件")
        self._btn_select.setToolTip("打开文件选择对话框（最多 2 个）")
        self._btn_select.clicked.connect(self._on_select_files)
        title_row.addWidget(self._btn_select)

        self._btn_clear = QPushButton("清空列表")
        self._btn_clear.clicked.connect(self._on_clear_files)
        title_row.addWidget(self._btn_clear)

        self._btn_parse = QPushButton("剧本解析")
        self._btn_parse.setToolTip("对每个选中 bin 生成带帧播放进度条的 3D 航点+灯光 HTML")
        self._btn_parse.clicked.connect(self._on_parse)
        title_row.addWidget(self._btn_parse)

        self._btn_compare = QPushButton("剧本对比")
        self._btn_compare.setToolTip("预留：补点剧本 vs 原剧本对比")
        self._btn_compare.clicked.connect(self._on_compare)
        title_row.addWidget(self._btn_compare)
        file_layout.addLayout(title_row)

        # 文件列表：固定高度容纳 2 行
        self._file_list = QListWidget()
        self._file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        row_h = self._file_list.fontMetrics().height() + 6
        self._file_list.setFixedHeight(2 * row_h + 2 * self._file_list.frameWidth())
        file_layout.addWidget(self._file_list)
        root.addWidget(grp_file)

        # ── Box2: 解析结果 HTML 列表 ──
        grp_result = QGroupBox("解析结果 HTML 列表")
        result_layout = QVBoxLayout(grp_result)
        self._result_table = QTableWidget(0, 3)
        self._result_table.setHorizontalHeaderLabels(["文件链接", "生成时间", "批次"])
        self._result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._result_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._result_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._result_table.cellClicked.connect(self._on_cell_clicked)
        result_layout.addWidget(self._result_table)
        root.addWidget(grp_result, 1)

        # ── 状态 ──
        self._lbl_status = QLabel("就绪 — 请选择 bin 文件（最多 2 个）")
        self._lbl_status.setWordWrap(True)
        root.addWidget(self._lbl_status)

    # ── 槽函数 ──
    @Slot()
    def _on_select_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择 Bin 文件", DEFAULT_DRAMA_DIR,
            "Bin 文件 (*.bin);;所有文件 (*)",
        )
        if not files:
            return
        self._append_selected(files)

    def _append_selected(self, files: list[str]) -> None:
        """追加选择文件（上限 2 个，绝不删除已选项）。抽离为独立方法便于测试。

        使用规范化路径（大小写不敏感 + 绝对路径）去重，避免同一文件
        以不同写法重复加入列表。
        """
        for f in files:
            norm = os.path.normcase(os.path.abspath(f))
            if len(self._selected_files) >= 2:
                QMessageBox.information(self, "提示", "最多选择 2 个 bin 文件。")
                break
            if norm in self._norm_paths:
                continue
            self._selected_files.append(f)
            self._norm_paths.add(norm)
            self._file_list.addItem(f)
        self._lbl_status.setText(f"已选择 {len(self._selected_files)} 个文件")

    @Slot()
    def _on_clear_files(self) -> None:
        self._selected_files.clear()
        self._norm_paths.clear()
        self._file_list.clear()
        self._lbl_status.setText("就绪 — 请选择 bin 文件（最多 2 个）")

    @Slot()
    def _on_parse(self) -> None:
        if not self._selected_files:
            QMessageBox.warning(self, "提示", "请先选择 bin 文件。")
            return

        self._batch_no += 1
        self._btn_parse.setEnabled(False)
        self._btn_compare.setEnabled(False)

        self._worker = _DramaWorker(
            "playback", list(self._selected_files), self._batch_no, self,
        )
        self._worker.progress.connect(self._lbl_status.setText)
        self._worker.file_done_batch.connect(self._add_result_row)
        self._worker.finished.connect(self._on_parse_done)
        self._worker.start()

    @Slot()
    def _on_compare(self) -> None:
        """剧本对比：两个 bin 文件名各含 ``yyyymmdd_hhmmss[.mmm]`` 时间戳，
        按绝对时间对齐（早起飞剧本为基准，晚起飞剧本插值）生成对比 HTML。"""
        if len(self._selected_files) != 2:
            QMessageBox.warning(
                self, "文件数量错误",
                f"剧本对比需要恰好 2 个文件，当前选择了 {len(self._selected_files)} 个。\n"
                f"请在列表中保留恰好 2 个文件后重试。",
            )
            return

        f1, f2 = self._selected_files[0], self._selected_files[1]
        for f in (f1, f2):
            if not os.path.exists(f):
                QMessageBox.warning(self, "文件不存在", f"文件不存在: {f}")
                return
        if parse_timestamp_from_name(f1) is None or parse_timestamp_from_name(f2) is None:
            QMessageBox.warning(
                self, "无法解析开始时间",
                "剧本对比需要从文件名解析两个剧本的开始绝对时间\n"
                "（格式 yyyymmdd_hhmmss 或 yyyymmdd_hhmmss.mmm）。\n\n"
                f"当前文件:\n{os.path.basename(f1)}\n{os.path.basename(f2)}",
            )
            return

        self._batch_no += 1
        self._btn_parse.setEnabled(False)
        self._btn_compare.setEnabled(False)

        self._worker = _DramaWorker(
            "compare_timeline", [f1, f2], self._batch_no, self,
        )
        self._worker.progress.connect(self._lbl_status.setText)
        self._worker.file_done_batch.connect(self._add_result_row)
        self._worker.finished.connect(self._on_parse_done)
        self._worker.start()

    # ── Worker 回调 ──
    @Slot(str, int)
    def _add_result_row(self, html_path: str, batch_no: int) -> None:
        """工作线程完成后将生成结果加入 HTML 列表（主线程安全）。"""
        if not os.path.exists(html_path):
            return
        row = self._result_table.rowCount()
        self._result_table.insertRow(row)

        name_item = QTableWidgetItem(os.path.basename(html_path))
        name_item.setToolTip(html_path)
        name_item.setForeground(QColor("#1a56db"))
        self._result_table.setItem(row, 0, name_item)

        mtime = os.path.getmtime(html_path)
        time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
        self._result_table.setItem(row, 1, QTableWidgetItem(time_str))

        self._result_table.setItem(row, 2, QTableWidgetItem(f"批次 {batch_no}"))

        # 同一批次 → 相同背景色
        color = self._BATCH_COLORS[(batch_no - 1) % len(self._BATCH_COLORS)]
        for col in range(3):
            self._result_table.item(row, col).setBackground(color)
        self._result_table.resizeRowToContents(row)

    @Slot(int, int)
    def _on_cell_clicked(self, row: int, _column: int) -> None:
        item = self._result_table.item(row, 0)
        if item is not None and item.toolTip():
            os.startfile(item.toolTip())

    @Slot(bool, str)
    def _on_parse_done(self, _success: bool, summary: str) -> None:
        self._lbl_status.setText(summary)
        self._btn_parse.setEnabled(True)
        self._btn_compare.setEnabled(True)


# ═══════════════════════════════════════════════════════════════
# WaypointTamperPanel —— 航点篡改子 Tab
# ═══════════════════════════════════════════════════════════════
class WaypointTamperPanel(QWidget):
    """航点篡改面板。

    功能：
    - 加载 .drm 剧本文件，解析所有飞机及其航点
    - 用户通过 +/- 添加/删除修改条目
    - 每条目：帧号、飞机1 ID、飞机2 ID、原本距离(m)、目标距离(m)、
      修改后飞机2 与其他飞机的最小距离(m)
    - 点击「确定修改」→ 修改飞机2 对应帧的航点 → 输出新 .drm 到 drama_modified/
    """

    # 信号：日志输出（可选，供外部连接）
    log_message = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # 解析后的剧本数据
        self._drama_data: dict | None = None   # DramaReader.read() 的返回值
        self._drm_path: str = ""
        self._drones: list[dict] = []           # [{"id": ..., "positionKeyFrames": [...], ...}]
        self._all_frames: list[int] = []        # 所有飞机的帧号并集，排序
        self._zero_frame_mode: bool = False     # 全零帧兼容模式（帧号=索引）

        # 修改条目列表
        self._entries: list[_TamperEntry] = []

        self._build_ui()

    # ── UI 构建 ──
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── 剧本文件加载 ──
        grp_load = QGroupBox("剧本文件（.drm）")
        load_layout = QHBoxLayout(grp_load)

        self._edit_drm_path = QLineEdit()
        self._edit_drm_path.setPlaceholderText("选择 .drm 剧本文件…")
        self._edit_drm_path.setReadOnly(True)
        load_layout.addWidget(self._edit_drm_path, 1)

        self._btn_browse = QPushButton("选择文件…")
        self._btn_browse.clicked.connect(self._on_browse_drm)
        load_layout.addWidget(self._btn_browse)

        self._btn_load = QPushButton("加载解析")
        self._btn_load.setToolTip("解析 .drm 文件，提取所有飞机及航点")
        self._btn_load.clicked.connect(self._on_load_drm)
        load_layout.addWidget(self._btn_load)

        root.addWidget(grp_load)

        # ── 解析信息 ──
        grp_info = QGroupBox("剧本信息")
        self._info_layout = QFormLayout(grp_info)
        self._lbl_drone_count = QLabel("—")
        self._info_layout.addRow("飞机数量:", self._lbl_drone_count)
        self._lbl_drone_detail = QLabel("—")
        self._lbl_drone_detail.setWordWrap(True)
        self._info_layout.addRow("各飞机航点数:", self._lbl_drone_detail)
        root.addWidget(grp_info)

        # ── 修改条目滚动区 ──
        grp_entries = QGroupBox("修改条目")
        entries_outer = QVBoxLayout(grp_entries)

        # 表头行（全选 + 列标题，与 _TamperEntry 列宽对齐）
        header = QWidget()
        header.setStyleSheet(
            "QWidget { background: palette(window); border-bottom: 2px solid palette(mid); }"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 2, 4, 2)
        header_layout.setSpacing(0)

        self._check_all = QCheckBox()
        self._check_all.setToolTip("全选 / 取消全选所有修改条目")
        self._check_all.stateChanged.connect(self._on_select_all)
        header_layout.addWidget(self._check_all, 0)
        header_layout.addSpacing(8)  # 条目 → 帧: 1x

        _GAP_1X = 8
        _GAP_2X = 16
        _COLUMNS = [
            ("帧", 80), ("飞机高度", 100), ("基准飞机", 90),
            ("被修改飞机", 100), ("原本距离", 90), ("目标距离(m)", 100),
            ("与其他飞机最小距离", 130),
        ]
        # 间距模式：帧→高度 1x，高度/基准飞机/被修改飞机/原本距离之间 2x，其余 1x
        _GAP_PATTERN = [_GAP_1X, _GAP_2X, _GAP_2X, _GAP_2X, _GAP_1X, _GAP_1X]
        for i, (title, width) in enumerate(_COLUMNS):
            lbl = QLabel(title)
            lbl.setStyleSheet(
                "font-weight: bold; border: none;"
                " padding-top: 2px; padding-bottom: 2px;"
                " padding-left: 4px; padding-right: 2px;"
            )
            lbl.setFixedWidth(width)
            header_layout.addWidget(lbl, 0)
            if i < len(_GAP_PATTERN):
                header_layout.addSpacing(_GAP_PATTERN[i])
        header_layout.addStretch()
        entries_outer.addWidget(header)

        # 条目列表
        self._entries_scroll = QScrollArea()
        self._entries_scroll.setWidgetResizable(True)
        self._entries_container = QWidget()
        self._entries_layout = QVBoxLayout(self._entries_container)
        self._entries_layout.setContentsMargins(0, 0, 0, 0)
        self._entries_layout.setSpacing(1)  # 条目间分隔
        self._entries_layout.addStretch()
        self._entries_scroll.setWidget(self._entries_container)
        entries_outer.addWidget(self._entries_scroll, 1)

        # +/- 按钮
        btn_row = QHBoxLayout()
        self._btn_add = QPushButton("＋ 添加一处修改")
        self._btn_add.clicked.connect(self._on_add_entry)
        btn_row.addWidget(self._btn_add)

        self._btn_remove = QPushButton("删除修改")
        self._btn_remove.setToolTip("删除所有已勾选的修改条目")
        self._btn_remove.clicked.connect(self._on_remove_entry)
        btn_row.addWidget(self._btn_remove)

        btn_row.addStretch()
        entries_outer.addLayout(btn_row)
        root.addWidget(grp_entries)

        # ── 确定按钮 ──
        btn_bottom = QHBoxLayout()
        btn_bottom.addStretch()

        self._btn_confirm = QPushButton("确定修改并输出")
        self._btn_confirm.setMinimumHeight(40)
        self._btn_confirm.setMinimumWidth(200)
        self._btn_confirm.setStyleSheet("QPushButton { font-weight: bold; }")
        self._btn_confirm.clicked.connect(self._on_confirm)
        btn_bottom.addWidget(self._btn_confirm)
        btn_bottom.addStretch()
        root.addLayout(btn_bottom)

        # ── 状态 ──
        self._lbl_status = QLabel("就绪 — 请加载 .drm 剧本文件")
        self._lbl_status.setWordWrap(True)
        root.addWidget(self._lbl_status)

    # ── 内部辅助 ──
    def _get_position(self, drone: dict, frame: int) -> tuple[float, float, float] | None:
        """获取某飞机在指定帧的位置 (x, y, z)。使用最近帧插值。"""
        kfs = drone.get("positionKeyFrames", [])
        if not kfs:
            return None

        # 已按 frame 排序（DramaReader 保证）
        # 精确匹配
        for kf in kfs:
            if kf["frame"] == frame:
                return (kf["x"], kf["y"], kf["z"])

        # 前后插值
        before = None
        after = None
        for kf in kfs:
            if kf["frame"] < frame:
                before = kf
            elif kf["frame"] > frame and after is None:
                after = kf
                break

        if before is None and after is None:
            return None
        if before is None:
            return (after["x"], after["y"], after["z"])
        if after is None:
            return (before["x"], before["y"], before["z"])

        # 线性插值
        ratio = (frame - before["frame"]) / (after["frame"] - before["frame"])
        x = before["x"] + (after["x"] - before["x"]) * ratio
        y = before["y"] + (after["y"] - before["y"]) * ratio
        z = before["z"] + (after["z"] - before["z"]) * ratio
        return (x, y, z)

    def _find_drone_by_id(self, drone_id: int) -> dict | None:
        for d in self._drones:
            if d["id"] == drone_id:
                return d
        return None

    def _calc_distance(self, p1: tuple, p2: tuple) -> float:
        return math.sqrt(
            (p1[0] - p2[0]) ** 2 +
            (p1[1] - p2[1]) ** 2 +
            (p1[2] - p2[2]) ** 2
        )

    def _recalc_min_distance_to_others(
        self, drone2_id: int, frame: int, new_pos: tuple,
        drone1_id: int | None = None,
    ) -> float:
        """计算修改后飞机2 与其他所有飞机在 frame 帧的最小距离。

        排除被修改飞机自身（drone2_id）和基准飞机（drone1_id）。
        """
        exclude_ids = {drone2_id}
        if drone1_id is not None:
            exclude_ids.add(drone1_id)
        min_dist = float('inf')
        for d in self._drones:
            if d["id"] in exclude_ids:
                continue
            pos = self._get_position(d, frame)
            if pos is None:
                continue
            dist = self._calc_distance(new_pos, pos)
            if dist < min_dist:
                min_dist = dist
        return min_dist if min_dist != float('inf') else 0.0

    # ── 槽函数 ──
    @Slot()
    def _on_browse_drm(self) -> None:
        start_dir = os.path.dirname(self._drm_path) if self._drm_path else ""
        if not start_dir:
            start_dir = os.path.expanduser("~")
        f, _ = QFileDialog.getOpenFileName(
            self, "选择剧本文件", start_dir,
            "剧本文件 (*.drm *.bin);;所有文件 (*)",
        )
        if f:
            self._drm_path = f
            self._edit_drm_path.setText(f)

    @Slot()
    def _on_load_drm(self) -> None:
        if not self._drm_path:
            QMessageBox.warning(self, "提示", "请先选择 .drm 文件。")
            return

        if not os.path.exists(self._drm_path):
            QMessageBox.warning(self, "文件不存在", f"文件不存在: {self._drm_path}")
            return

        self._lbl_status.setText("解析剧本文件中…")

        # 尝试 DramaReader
        DramaReader = _try_import_drama_reader()
        if DramaReader is not None:
            try:
                reader = DramaReader()
                self._drama_data = reader.read(self._drm_path)
                self._drones = self._drama_data.get("drama3", {}).get("drones", [])
                self._lbl_status.setText(
                    f"解析成功（DramaReader）: {len(self._drones)} 架飞机"
                )
            except Exception as e:
                self._drama_data = None
                self._drones = []
                self._lbl_status.setText(f"DramaReader 解析失败: {e}")
        else:
            # 回退：尝试 DatReader 处理单飞机 bin 文件
            DatReader = _try_import_dat_reader()
            if DatReader is not None:
                try:
                    reader = DatReader()
                    header, config, trailer, _rc0, _rc1, _rc2 = reader.process_file(self._drm_path)
                    reader.save_one_drone_data(config, trailer['frames'], self._drm_path, interpolate=True)
                    # 构建单飞机结构
                    dot_index = self._drm_path.rfind('.')
                    import json as _json
                    json_path = f"{self._drm_path[:dot_index]}.json"
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = _json.load(f)
                    waypoints = []
                    META_KEYS = {"pointFps", "payloadFps", "totalPointFrameCount", "totalPayloadFrameCount"}
                    for key in sorted(data.keys(), key=lambda k: (
                        0 if k in META_KEYS else 1, int(k) if k.isdigit() else 999999
                    )):
                        if key in META_KEYS:
                            continue
                        for item in data[key]:
                            if "x" in item and "y" in item and "z" in item:
                                waypoints.append({"frame": int(key), "x": item["x"], "y": item["y"], "z": item["z"]})
                    self._drones = [{
                        "id": int.from_bytes(header['id'], 'little'),
                        "droneType": 0,
                        "positionKeyFrames": waypoints,
                        "totalPointFrameCount": data.get("totalPointFrameCount", 0),
                        "totalPayloadFrameCount": data.get("totalPayloadFrameCount", 0),
                    }]
                    self._drama_data = {"drama3": {"drones": self._drones, "pointFps": data.get("pointFps", 0), "payloadFps": data.get("payloadFps", 0)}}
                    self._lbl_status.setText(f"解析成功（DatReader）: 1 架飞机")
                except Exception as e:
                    self._drones = []
                    self._drama_data = None
                    self._lbl_status.setText(f"DatReader 解析失败: {e}")
            else:
                self._lbl_status.setText("解析失败: 无法导入 DramaReader 或 DatReader")
                return

        if not self._drones:
            QMessageBox.warning(self, "解析结果", "未解析到任何飞机数据。")
            return

        # 收集所有帧号
        frame_set = set()
        for d in self._drones:
            for kf in d.get("positionKeyFrames", []):
                frame_set.add(kf["frame"])
        self._all_frames = sorted(frame_set)

        # 兼容处理：如果所有帧号都为 0（数据未正确写入帧号），
        # 则按关键帧索引生成顺序帧号（0, 1, 2, ..., max_kfs-1），
        # 同时修正关键帧数据中的 frame 字段
        self._zero_frame_mode = False
        if self._all_frames == [0]:
            max_kfs = max(
                (len(d.get("positionKeyFrames", [])) for d in self._drones),
                default=0,
            )
            if max_kfs > 1:
                self._all_frames = list(range(max_kfs))
                for d in self._drones:
                    for i, kf in enumerate(d.get("positionKeyFrames", [])):
                        kf["frame"] = i
                self._zero_frame_mode = True

        # 更新信息显示
        self._lbl_drone_count.setText(str(len(self._drones)))
        detail_parts = []
        max_show = 10
        for d in self._drones[:max_show]:
            wp_count = len(d.get("positionKeyFrames", []))
            detail_parts.append(f"飞机 {d['id']}: {wp_count} 个航点")
        if len(self._drones) > max_show:
            detail_parts.append(f"…等 {len(self._drones)} 架飞机")
        self._lbl_drone_detail.setText(" | ".join(detail_parts))

        # 清除旧条目
        self._clear_all_entries()

        self._lbl_status.setText(
            f"加载完成: {len(self._drones)} 架飞机, "
            f"{len(self._all_frames)} 个不同帧号 (帧范围 {self._all_frames[0]}–{self._all_frames[-1]})"
        )

    @Slot()
    def _on_add_entry(self) -> None:
        if not self._drones:
            QMessageBox.warning(self, "提示", "请先加载剧本文件。")
            return
        entry = _TamperEntry(self)
        entry.set_data(self._drones, self._all_frames, self)
        # 插入到 stretch 之前
        idx = self._entries_layout.count() - 1  # stretch 在最后
        self._entries_layout.insertWidget(idx, entry)
        self._entries.append(entry)

    @Slot(int)
    def _on_select_all(self, state: int) -> None:
        """全选/取消全选所有修改条目。"""
        checked = state == Qt.CheckState.Checked.value
        for entry in self._entries:
            entry.set_checked(checked)

    @Slot()
    def _on_remove_entry(self) -> None:
        """删除所有已勾选的修改条目。"""
        to_remove = [e for e in self._entries if e.is_checked()]
        if not to_remove:
            QMessageBox.information(self, "提示", "未选中任何修改条目。")
            return
        for entry in to_remove:
            self._entries_layout.removeWidget(entry)
            entry.deleteLater()
            self._entries.remove(entry)

    def _clear_all_entries(self) -> None:
        for entry in self._entries:
            self._entries_layout.removeWidget(entry)
            entry.deleteLater()
        self._entries.clear()

    @Slot()
    def _on_confirm(self) -> None:
        """执行修改并输出新 .drm 文件。"""
        if not self._drones:
            QMessageBox.warning(self, "提示", "请先加载剧本文件。")
            return
        if not self._entries:
            QMessageBox.warning(self, "提示", "没有待修改的条目，请先添加修改条目。")
            return

        # 收集勾选的条目（未勾选的条目不参与修改）
        checked_entries = [e for e in self._entries if e.is_checked()]
        if not checked_entries:
            QMessageBox.warning(self, "提示", "没有勾选的修改条目，请先勾选需要修改的条目。")
            return

        # 收集并验证所有勾选条目
        mods: list[dict] = []
        for entry in checked_entries:
            data = entry.get_data()
            if data is None:
                QMessageBox.warning(self, "参数不完整", "某个勾选的修改条目参数不完整。")
                return
            mods.append(data)

        # 应用修改到数据副本
        modified_wp = {}  # {(drone_id, frame): (new_x, new_y, new_z)}
        for mod in mods:
            frame = mod["frame"]
            drone1_id = mod["drone1_id"]
            drone2_id = mod["drone2_id"]
            target_dist = mod["target_dist"]

            drone1 = self._find_drone_by_id(drone1_id)
            drone2 = self._find_drone_by_id(drone2_id)

            # 顺序依赖：优先使用已修改的位置（modified_wp 作为工作状态），
            # 未修改时才回退到原始位置
            pos1 = modified_wp.get((drone1_id, frame)) or self._get_position(drone1, frame)
            pos2 = modified_wp.get((drone2_id, frame)) or self._get_position(drone2, frame)
            if pos1 is None or pos2 is None:
                QMessageBox.warning(self, "位置缺失",
                    f"飞机 {drone1_id} 或 {drone2_id} 在帧 {frame} 没有位置数据。")
                return

            cur_dist = self._calc_distance(pos1, pos2)
            if cur_dist < 1e-6:
                QMessageBox.warning(self, "距离为零",
                    f"飞机 {drone1_id} 和 {drone2_id} 在帧 {frame} 距离为 0，无法确定方向。")
                return

            # 沿直线方向修改飞机2 的位置
            dx = (pos2[0] - pos1[0]) / cur_dist  # 单位方向分量
            dy = (pos2[1] - pos1[1]) / cur_dist
            dz = (pos2[2] - pos1[2]) / cur_dist
            new_x = pos1[0] + dx * target_dist
            new_y = pos1[1] + dy * target_dist
            new_z = pos1[2] + dz * target_dist

            modified_wp[(drone2_id, frame)] = (new_x, new_y, new_z)
            mod["_cur_dist"] = cur_dist
            mod["_new_pos"] = (new_x, new_y, new_z)

        # 在数据副本中应用所有修改
        for (drone_id, frame), (nx, ny, nz) in modified_wp.items():
            drone = self._find_drone_by_id(drone_id)
            if drone is None:
                continue
            kfs = drone.get("positionKeyFrames", [])
            for kf in kfs:
                if kf["frame"] == frame:
                    kf["x"] = nx
                    kf["y"] = ny
                    kf["z"] = nz
                    break

        # 输出新 .drm 文件
        try:
            output_path = self._write_modified_drm(mods, modified_wp)
            if output_path:
                self._lbl_status.setText(f"输出成功: {output_path}")
                # 刷新勾选条目的"修改后最小距离"
                for entry, mod in zip(checked_entries, mods):
                    new_pos = mod.get("_new_pos", (0, 0, 0))
                    min_d = self._recalc_min_distance_to_others(
                        mod["drone2_id"], mod["frame"], new_pos,
                        drone1_id=mod["drone1_id"],
                    )
                    entry.set_min_distance(min_d)
                QMessageBox.information(self, "完成", f"已输出修改后的剧本:\n{output_path}")
            else:
                self._lbl_status.setText("输出失败")
        except Exception as e:
            self._lbl_status.setText(f"输出异常: {e}")
            QMessageBox.critical(self, "错误", f"输出失败: {e}")

    def _write_modified_drm(self, mods: list[dict],
                           modified_wp: dict | None = None) -> str | None:
        """将修改后的数据写入新的 .drm 文件。

        优先直接修改原始 protobuf（保全所有字段）；不可用时回退到 JSON。
        """
        os.makedirs(DRAMA_MODIFIED_DIR, exist_ok=True)

        # 生成文件名: 原文件名-uav_X-uav_Y-xx.xm.drm
        drone1_ids = sorted(set(str(m["drone1_id"]) for m in mods))
        drone2_ids = sorted(set(str(m["drone2_id"]) for m in mods))
        target_dists = [f"{m['target_dist']:.1f}" for m in mods]

        uav_x = "_".join(drone1_ids) if drone1_ids else "x"
        uav_y = "_".join(drone2_ids) if drone2_ids else "y"
        dist_str = "_".join(target_dists) if target_dists else "0.0"
        orig_name = (
            os.path.splitext(os.path.basename(self._drm_path))[0]
            if self._drm_path else "Drama"
        )
        base_name = f"{orig_name}-uav_{uav_x}-uav_{uav_y}-{dist_str}m"

        # 尝试直接修改原始 protobuf（保全所有字段）
        success = self._try_write_drm_protobuf(base_name, modified_wp or {})
        if success:
            return success

        # 回退：保存为 JSON
        return self._try_write_json(base_name)

    def _try_write_drm_protobuf(self, base_name: str,
                                modified_wp: dict) -> str | None:
        """直接解析原始 .drm protobuf，修改 positionKeyFrames 后写回。

        不复建 protobuf，直接在原始对象上修改航点坐标，
        从而保全原始文件中的所有字段（包括未知字段/扩展字段）。
        """
        try:
            from src.Protocol.drama.drone_show.Drama3_pb2 import Drama3
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import pad, unpad
            import zipfile
            import io
        except ImportError:
            return None

        if not self._drm_path or not os.path.exists(self._drm_path):
            return None

        try:
            # ── 1. 解密 + 解压原始 .drm → protobuf ──
            with open(self._drm_path, 'rb') as f:
                encrypted_data = f.read()

            from src.Protocol.drama.drone_show.drama_reader import secret_key, secret_iv
            cipher_dec = AES.new(secret_key, AES.MODE_CBC, secret_iv)
            try:
                decrypted = unpad(cipher_dec.decrypt(encrypted_data), AES.block_size)
            except ValueError:
                # 如果未正确填充，尝试去除末尾零字节
                decrypted = cipher_dec.decrypt(encrypted_data).rstrip(b'\x00')

            zip_buf = io.BytesIO(decrypted)
            with zipfile.ZipFile(zip_buf) as zf:
                file_list = zf.namelist()
                if 'dramafile' not in file_list:
                    logger.warning("ZIP 中没有 'dramafile'，找到: %s", file_list)
                    return None
                raw_data = zf.read('dramafile')

            drama3 = Drama3()
            drama3.ParseFromString(raw_data)

            # ── 2. 直接在 protobuf 上修改 positionKeyFrames ──
            for (drone_id, frame), (nx, ny, nz) in modified_wp.items():
                for drone in drama3.drones:
                    if drone.id == drone_id:
                        if self._zero_frame_mode:
                            # 全零帧模式：frame 值 = 关键帧列表索引
                            if 0 <= frame < len(drone.positionKeyFrames):
                                kf = drone.positionKeyFrames[frame]
                                kf.x = nx
                                kf.y = ny
                                kf.z = nz
                        else:
                            for kf in drone.positionKeyFrames:
                                if kf.frame == frame:
                                    kf.x = nx
                                    kf.y = ny
                                    kf.z = nz
                                    break
                        break

            # ── 3. 序列化 + 压缩 + 加密 → .drm ──
            serialized = drama3.SerializeToString()

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('dramafile', serialized)
            zip_data = zip_buffer.getvalue()

            cipher = AES.new(secret_key, AES.MODE_CBC, secret_iv)
            encrypted = cipher.encrypt(pad(zip_data, AES.block_size))

            output_path = os.path.join(DRAMA_MODIFIED_DIR, f"{base_name}.drm")
            with open(output_path, 'wb') as f:
                f.write(encrypted)

            return output_path

        except Exception as e:
            logger.warning("protobuf 直接修改失败 (%s)，回退到 JSON", e)
            return None

    def _try_write_json(self, base_name: str) -> str | None:
        """回退方案：保存为 JSON 格式（含所有飞机数据）。"""
        import json as _json
        output_path = os.path.join(DRAMA_MODIFIED_DIR, f"{base_name}.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            _json.dump(self._drama_data, f, indent=4, ensure_ascii=False)
        return output_path


# ═══════════════════════════════════════════════════════════════
# _TamperEntry —— 单条修改条目控件
# ═══════════════════════════════════════════════════════════════
class _TamperEntry(QFrame):
    """单条航点修改条目（表格式布局，含勾选框）。

    列：
        [☑] [帧: _LimitedCombo] [飞机高度: QLabel] [基准飞机: _LimitedCombo]
        [被修改飞机: _LimitedCombo] [原本距离: QLabel] [目标距离: QDoubleSpinBox]
        [与其他飞机最小距离: QLabel]

    表头由 WaypointTamperPanel 提供，本控件只显示数据列。

    v2.0: 三个下拉框从 _MultiSelectButton(single_select=True) 替换为
    _LimitedCombo，提供标准 QComboBox 交互（键盘跳转、滚轮、currentData() 直存 int）。
    """

    # 列宽（与表头对齐）
    COL_WIDTHS = [30, 80, 100, 90, 100, 90, 100, 130]
    # 间距：帧/基准飞机/被修改飞机/原本距离之间 2x，其余 1x
    _GAP_1X = 8
    _GAP_2X = 16

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drones: list[dict] = []
        self._all_frames: list[int] = []
        self._panel: WaypointTamperPanel | None = None

        # 表格线效果
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Plain)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)

        # 列 0: 勾选框
        self._check = QCheckBox()
        self._check.setFixedWidth(self.COL_WIDTHS[0])
        layout.addWidget(self._check, 0)
        layout.addSpacing(self._GAP_1X)  # 条目 → 帧: 1x

        # 列 1: 帧（使用 _LimitedCombo，currentData() 直接存 int）
        self._combo_frame = _LimitedCombo(20)
        self._combo_frame.setFixedWidth(self.COL_WIDTHS[1])
        self._combo_frame.currentIndexChanged.connect(self._on_params_changed)
        layout.addWidget(self._combo_frame, 0)
        layout.addSpacing(self._GAP_1X)  # 帧 → 飞机高度: 1x

        # 列 2: 飞机高度（x.xm|x.xm）
        self._lbl_altitude = QLabel("— m")
        self._lbl_altitude.setFixedWidth(self.COL_WIDTHS[2])
        self._lbl_altitude.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._lbl_altitude, 0)
        layout.addSpacing(self._GAP_2X)  # 飞机高度 → 基准飞机: 2x

        # 列 3: 基准飞机（使用 _LimitedCombo）
        self._combo_drone1 = _LimitedCombo(20)
        self._combo_drone1.setFixedWidth(self.COL_WIDTHS[3])
        self._combo_drone1.currentIndexChanged.connect(self._on_params_changed)
        layout.addWidget(self._combo_drone1, 0)
        layout.addSpacing(self._GAP_2X)  # 基准飞机 → 被修改飞机: 2x

        # 列 4: 被修改飞机（使用 _LimitedCombo）
        self._combo_drone2 = _LimitedCombo(20)
        self._combo_drone2.setFixedWidth(self.COL_WIDTHS[4])
        self._combo_drone2.currentIndexChanged.connect(self._on_params_changed)
        layout.addWidget(self._combo_drone2, 0)
        layout.addSpacing(self._GAP_2X)  # 被修改飞机 → 原本距离: 2x

        # 列 5: 原本距离
        self._lbl_cur_dist = QLabel("— m")
        self._lbl_cur_dist.setFixedWidth(self.COL_WIDTHS[5])
        self._lbl_cur_dist.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._lbl_cur_dist, 0)
        layout.addSpacing(self._GAP_1X)  # 原本距离 → 目标距离: 1x

        # 列 6: 目标距离
        self._spin_target = QDoubleSpinBox()
        self._spin_target.setFixedWidth(self.COL_WIDTHS[6])
        self._spin_target.setRange(0.01, 999999.0)
        self._spin_target.setDecimals(2)
        self._spin_target.setSuffix(" m")
        self._spin_target.setValue(10.0)
        layout.addWidget(self._spin_target, 0)
        layout.addSpacing(self._GAP_1X)  # 目标距离 → 最小距离: 1x

        # 列 7: 与其他飞机最小距离
        self._lbl_min_dist = QLabel("— m")
        self._lbl_min_dist.setFixedWidth(self.COL_WIDTHS[7])
        self._lbl_min_dist.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._lbl_min_dist, 0)

        layout.addStretch()

    # ── 勾选框 ──
    def is_checked(self) -> bool:
        return self._check.isChecked()

    def set_checked(self, checked: bool) -> None:
        self._check.setChecked(checked)

    def set_data(
        self, drones: list[dict], all_frames: list[int],
        panel: "WaypointTamperPanel",
    ) -> None:
        """设置可选数据并刷新下拉框。"""
        self._drones = drones
        self._all_frames = all_frames
        self._panel = panel

        # 填充帧下拉（userData 直接存 int，避免 str↔int 转换）
        self._combo_frame.clear()
        for f in all_frames:
            self._combo_frame.addItem(str(f), userData=f)
        if all_frames:
            self._combo_frame.setCurrentIndex(0)

        # 填充飞机下拉
        drone_ids = [d["id"] for d in drones]
        self._combo_drone1.clear()
        for did in drone_ids:
            self._combo_drone1.addItem(f"飞机 {did}", userData=did)
        if drone_ids:
            self._combo_drone1.setCurrentIndex(0)

        self._combo_drone2.clear()
        for did in drone_ids:
            self._combo_drone2.addItem(f"飞机 {did}", userData=did)
        # 默认选不同的两个
        if len(drone_ids) >= 2:
            self._combo_drone2.setCurrentIndex(1)
        elif drone_ids:
            self._combo_drone2.setCurrentIndex(0)

        self._update_distances()

    def set_min_distance(self, min_d: float) -> None:
        self._lbl_min_dist.setText(f"{min_d:.2f} m")

    def get_data(self) -> dict | None:
        """返回修改条目数据字典，参数不完整时返回 None。"""
        frame = self._combo_frame.currentData()
        drone1_id = self._combo_drone1.currentData()
        drone2_id = self._combo_drone2.currentData()
        if frame is None or drone1_id is None or drone2_id is None:
            return None
        if drone1_id == drone2_id:
            return None
        return {
            "frame": frame,
            "drone1_id": drone1_id,
            "drone2_id": drone2_id,
            "target_dist": self._spin_target.value(),
        }

    @Slot()
    def _on_params_changed(self) -> None:
        self._update_distances()

    def _update_distances(self) -> None:
        """根据当前选择更新飞机高度、原本距离和最小距离。"""
        frame = self._combo_frame.currentData()
        drone1_id = self._combo_drone1.currentData()
        drone2_id = self._combo_drone2.currentData()

        if frame is None or drone1_id is None or drone2_id is None or self._panel is None:
            self._lbl_cur_dist.setText("— m")
            self._lbl_min_dist.setText("— m")
            self._lbl_altitude.setText("— m")
            return

        if drone1_id == drone2_id:
            self._lbl_cur_dist.setText("同飞机")
            self._lbl_min_dist.setText("— m")
            self._lbl_altitude.setText("— m")
            return

        pos1 = self._panel._get_position(
            self._panel._find_drone_by_id(drone1_id) or {}, frame
        )
        pos2 = self._panel._get_position(
            self._panel._find_drone_by_id(drone2_id) or {}, frame
        )

        if pos1 is None or pos2 is None:
            self._lbl_cur_dist.setText("无位置")
            self._lbl_min_dist.setText("— m")
            self._lbl_altitude.setText("— m")
            return

        cur_dist = self._panel._calc_distance(pos1, pos2)
        self._lbl_cur_dist.setText(f"{cur_dist:.2f} m")

        # 飞机高度（z 坐标）
        self._lbl_altitude.setText(f"{pos1[2]:.1f}m|{pos2[2]:.1f}m")

        # 根据目标距离估算修改后的最小距离
        target_dist = self._spin_target.value()
        if cur_dist > 1e-6:
            dx = (pos2[0] - pos1[0]) / cur_dist
            dy = (pos2[1] - pos1[1]) / cur_dist
            dz = (pos2[2] - pos1[2]) / cur_dist
            new_x = pos1[0] + dx * target_dist
            new_y = pos1[1] + dy * target_dist
            new_z = pos1[2] + dz * target_dist
            min_d = self._panel._recalc_min_distance_to_others(
                drone2_id, frame, (new_x, new_y, new_z), drone1_id=drone1_id
            )
            self._lbl_min_dist.setText(f"{min_d:.2f} m")
        else:
            self._lbl_min_dist.setText("∞")
