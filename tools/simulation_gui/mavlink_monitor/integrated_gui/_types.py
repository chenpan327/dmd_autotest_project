"""类型检测、值转换、控件工厂。

从 integrated_gui.py 拆分出来的独立模块。
依赖: ._reflection (SourceInfo, NestedDeviceMeta 类型提示)
"""
from __future__ import annotations

import ast
import inspect
import json
import re
import textwrap
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QLineEdit, QSpinBox, QWidget,
)

from mavlink_monitor.gui.widgets import _CollapseToggle, _LimitedCombo

from ._reflection import _parse_sphinx_params_from_docstring, _parse_supported_keywords_from_docstring


# ═══════════════════════════════════════════════════════════════
# 类型检测
# ═══════════════════════════════════════════════════════════════
_INT_HINT_KEYWORDS = (
    "count", "num", "size", "len", "index", "port", "code",
    "speed", "state", "lat", "lon", "alt", "id", "version_int",
    "nestip",
)
_BOOL_HINT_KEYWORDS = ("success", "enable", "flag", "armed", "is_", "has_", "need_", "set_")
_BYTES_HINT_KEYWORDS = ("version", "serial", "prefix", "suffix", "sn")
_LIST_HINT_KEYWORDS = ("config", "channel", "array", "list", "matrix", "items", "info")


def _infer_kind_via_isinstance(cls: type, param_name: str) -> str | None:
    try:
        source = inspect.getsource(cls)
    except (TypeError, OSError):
        return None
    for m in re.finditer(r"isinstance\s*\(([^,()]+(?:\([^)]*\)[^,()]*)*)\s*,\s*(\w+)\s*\)", source):
        first_arg, type_name = m.group(1), m.group(2)
        if param_name not in first_arg:
            continue
        if type_name == "list":
            return "list"
        if type_name == "tuple":
            return "list"
        if type_name == "bytes":
            return "bytes"
        if type_name == "int":
            return "int"
        if type_name == "float":
            return "float"
        if type_name == "bool":
            return "bool"
    return None


def _find_param_kind_via_attr(
    sender_cls: type,
    method_name: str,
    param_name: str,
    init_attrs: dict[str, str],
) -> str | None:
    if not method_name or not param_name or not init_attrs:
        return None
    method = getattr(sender_cls, method_name, None)
    if method is None:
        return None
    try:
        source = inspect.getsource(method)
    except (TypeError, OSError):
        return None
    tree = ast.parse(textwrap.dedent(source))
    for stmt in ast.walk(tree):
        if not isinstance(stmt, ast.Assign):
            continue
        for tgt in stmt.targets:
            if (isinstance(tgt, ast.Attribute) and
                    isinstance(tgt.value, ast.Name) and
                    tgt.value.id == "self" and
                    isinstance(stmt.value, ast.Name) and
                    stmt.value.id == param_name):
                return init_attrs.get(tgt.attr)
    return None


def _detect_kind(
    default: Any,
    name: str = "",
    *,
    config: "SimConfig | None" = None,
    method_name: str | None = None,
    init_attrs: dict[str, str] | None = None,
) -> str:
    """综合判断参数类型。"""
    # 1) 注册表优先
    if config is not None and name in config.known_param_types:
        return config.known_param_types[name]

    # 2) init_attrs 直接查表
    if init_attrs and name in init_attrs:
        return init_attrs[name]

    # 3) self.X = param 路径追踪
    if config is not None and method_name and init_attrs:
        kind = _find_param_kind_via_attr(config.sender_cls, method_name, name, init_attrs)
        if kind:
            return kind

    # 4) 默认值类型
    if default is not None:
        if isinstance(default, bool):
            return "bool"
        if isinstance(default, int):
            return "int"
        if isinstance(default, float):
            return "float"
        if isinstance(default, bytes):
            return "bytes"
        if isinstance(default, (list, tuple)):
            return "list"

    # 5) AST isinstance 扫描
    if config is not None:
        for cls in (config.mgr_cls, config.sender_cls):
            kind = _infer_kind_via_isinstance(cls, name)
            if kind:
                return kind

    # 6) 名称启发式
    lowered = name.lower()
    if any(kw in lowered for kw in _LIST_HINT_KEYWORDS):
        return "list"
    if any(kw in lowered for kw in _BYTES_HINT_KEYWORDS):
        return "bytes"
    if any(kw in lowered for kw in _INT_HINT_KEYWORDS):
        return "int"
    if any(kw in lowered for kw in _BOOL_HINT_KEYWORDS):
        return "bool"
    return "str"


# ═══════════════════════════════════════════════════════════════
# 控件值与字符串互转
# ═══════════════════════════════════════════════════════════════
_KIND_HINT: dict[str, str] = {
    "int": "整数, 如 10",
    "uint32": "uint32, 无符号32位 0~4294967295",
    "int32": "int32, 有符号32位 -2147483648~2147483647",
    "uint16": "uint16, 无符号16位 0~65535",
    "int16": "int16, 有符号16位 -32768~32767",
    "uint8": "uint8, 无符号8位 0~255",
    "float": "小数, 如 1.5",
    "bool": "True / False",
    "bytes": "字节串 (utf-8 编码), 如 1234",
    "str": "字符串",
    "list": "列表, 多种格式: [0,1,0,1] 或 0,1,0,1 或 0101",
    "list_int": "整数列表, 多种格式: [0,1,0,1] 或 0,1,0,1 或 0101",
    "latlon": "经纬度 (度), 如 22.6868764",
    "alt_m": "高度 (米), 如 100.5",
}

_MIN_VISIBLE_FORM_ROWS = 5
_EST_FORM_ROW_HEIGHT = 32


def _resolve_hint(kind: str) -> str:
    return _KIND_HINT.get(kind, "")


def _default_to_text(default: Any) -> str:
    if isinstance(default, bytes):
        try:
            return default.decode("utf-8")
        except Exception:
            return default.hex()
    if isinstance(default, (list, tuple)):
        return ",".join(str(x) for x in default)
    if default is None:
        return ""
    return str(default)


def _coerce(raw: Any, kind: str) -> Any:
    """把控件原始值转换成方法期望的类型。"""
    if raw is None:
        raw = ""
    if not isinstance(raw, str):
        return raw
    s = raw.strip()

    if kind == "bool":
        if s.lower() in ("1", "true", "yes", "y", "on", "t"):
            return True
        if s.lower() in ("0", "false", "no", "n", "off", "f", ""):
            return False
        raise ValueError(f"无法解析 bool: {raw!r}")

    _INT_KINDS = {"int", "uint32", "int32", "uint16", "int16", "uint8"}
    if kind in _INT_KINDS:
        if not s:
            return 0
        if s.lower().startswith("0x"):
            return int(s, 16)
        return int(s)

    if kind == "float":
        return float(s) if s else 0.0

    if kind == "bytes":
        return s.encode("utf-8")

    if kind in ("list", "list_int"):
        return _parse_list(s, element_kind="int" if kind == "list_int" else "auto")

    return raw


def _parse_list(s: str, element_kind: str = "auto") -> list:
    """多种格式解析为列表。"""

    def _auto_coerce(x):
        if not isinstance(x, str):
            return x
        stripped = x.strip()
        try:
            return int(stripped)
        except ValueError:
            return stripped

    if not s:
        return []
    # 1) JSON
    try:
        v = json.loads(s)
        if isinstance(v, list):
            return [_auto_coerce(x) if element_kind == "auto" else _coerce(x, element_kind)
                    for x in v]
    except (ValueError, json.JSONDecodeError):
        pass
    # 2) Python literal
    try:
        v = ast.literal_eval(s)
        if isinstance(v, (list, tuple)):
            return [_auto_coerce(x) if element_kind == "auto" else _coerce(x, element_kind)
                    for x in v]
    except (ValueError, SyntaxError):
        pass
    # 3) CSV
    if "," in s:
        try:
            return [
                _auto_coerce(p.strip()) if element_kind == "auto" else _coerce(p.strip(), element_kind)
                for p in s.split(",")
                if p.strip()
            ]
        except ValueError:
            pass
    # 4) 空格分隔
    if " " in s:
        try:
            return [
                _auto_coerce(p.strip()) if element_kind == "auto" else _coerce(p.strip(), element_kind)
                for p in s.split()
                if p.strip()
            ]
        except ValueError:
            pass
    # 5) 纯 0/1 比特串
    if all(c in "01" for c in s):
        return [int(c) for c in s]
    # 6) 单值：解析为单元素列表（如 "4" → [4]，"hello" → ["hello"]）
    try:
        return [_auto_coerce(s.strip()) if element_kind == "auto" else _coerce(s.strip(), element_kind)]
    except ValueError:
        pass
    raise ValueError(f"无法解析为列表: {s!r}")


# ═══════════════════════════════════════════════════════════════
# 通用反射工具
# ═══════════════════════════════════════════════════════════════
def _discover_update_methods(
    sender_cls: type,
    config: "SimConfig | None" = None,
    init_defaults: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """扫描 ``sender_cls`` 上所有 ``update_xxx`` 方法。"""
    init_defaults = init_defaults or {}
    methods: dict[str, dict[str, Any]] = {}
    for name in dir(sender_cls):
        if not name.startswith("update_") or name == "update":
            continue
        attr = getattr(sender_cls, name)
        if not callable(attr):
            continue
        try:
            sig = inspect.signature(attr)
        except (TypeError, ValueError):
            continue
        params: dict[str, Any] = {}
        has_var_keyword = False
        for pname, p in sig.parameters.items():
            if pname == "self":
                continue
            if p.kind == inspect.Parameter.VAR_KEYWORD:
                has_var_keyword = True
                continue
            if p.kind == inspect.Parameter.VAR_POSITIONAL:
                continue
            params[pname] = (
                p.default if p.default is not inspect.Parameter.empty else None
            )
        # 自适应入参：含 **kwargs 时，从 docstring 提取字段并合并
        if has_var_keyword:
            keywords = _parse_supported_keywords_from_docstring(attr)
            if keywords:
                # 已有命名参数优先，docstring 提取的字段作为补充
                for kw in keywords:
                    if kw not in params:
                        params[kw] = init_defaults.get(kw)
            elif not params and config is not None:
                params = dict(config.method_param_types.get(name, {}))
        methods[name] = params
    return methods


def _discover_add_params(mgr_cls: type) -> dict[str, Any]:
    """读取 ``mgr_cls.__init__`` 的用户可见参数。"""
    sig = inspect.signature(mgr_cls.__init__)
    skip = {"self", "log_manager"}
    params: dict[str, Any] = {}
    for pname, p in sig.parameters.items():
        if pname in skip:
            continue
        if p.kind in (inspect.Parameter.VAR_POSITIONAL,
                      inspect.Parameter.VAR_KEYWORD):
            continue
        params[pname] = (
            p.default if p.default is not inspect.Parameter.empty else None
        )
    return params


# ═══════════════════════════════════════════════════════════════
# 通用控件工厂
# ═══════════════════════════════════════════════════════════════
_INT_RANGES: dict[str, tuple[int, int]] = {
    "uint32": (0, 0x7FFFFFFF),       # QSpinBox 上限为 int32 max
    "int32":  (-0x80000000, 0x7FFFFFFF),
    "uint16": (0, 0xFFFF),
    "int16":  (-0x8000, 0x7FFF),
    "uint8":  (0, 0xFF),
}


def _make_input_widget(
    aid: str, slot_id: str, default: Any, kind: str,
    choices: dict[str, str] | None = None,
) -> tuple[Any, Callable, Callable]:
    """根据 kind 构造对应输入控件，返回 (widget, getter, setter)。"""
    hint = _resolve_hint(kind)

    if choices:
        cb = _LimitedCombo(20)
        for label, value in choices.items():
            cb.addItem(f"{label} ({value})", userData=value)
        idx = cb.findData(default)
        if idx >= 0:
            cb.setCurrentIndex(idx)
        cb.setObjectName(f"{aid}{slot_id}")
        cb.setToolTip("从配置表选择对应机型")
        return (cb,
                lambda w=cb: w.currentData(),
                lambda v, w=cb: w.setCurrentIndex(max(w.findData(v), 0)))

    # ── MAVLink 精确整数类型 ──
    if kind in _INT_RANGES:
        lo, hi = _INT_RANGES[kind]
        val = int(default) if isinstance(default, int) else 0
        sb = QSpinBox()
        sb.setRange(lo, hi)
        sb.setValue(max(lo, min(hi, val)))
        sb.setObjectName(f"{aid}{slot_id}")
        sb.setToolTip(hint)
        return sb, sb.value, sb.setValue

    if kind == "int":
        val = int(default) if isinstance(default, int) else 0
        if val > 1_000_000 or val < -1_000_000:
            le = QLineEdit(hex(val) if val > 0xFFFF else str(val))
            le.setObjectName(f"{aid}{slot_id}")
            le.setPlaceholderText(hint)
            le.setToolTip(hint)
            return le, le.text, le.setText
        sb = QSpinBox()
        sb.setRange(-1_000_000, 1_000_000)
        sb.setValue(val)
        sb.setObjectName(f"{aid}{slot_id}")
        sb.setToolTip(hint)
        return sb, sb.value, sb.setValue

    if kind == "float":
        sb = QDoubleSpinBox()
        sb.setRange(-1_000_000.0, 1_000_000.0)
        sb.setDecimals(6)
        sb.setValue(float(default) if isinstance(default, (int, float)) else 0.0)
        sb.setObjectName(f"{aid}{slot_id}")
        sb.setToolTip(hint)
        return sb, sb.value, sb.setValue

    # ── 经纬度（度 → 1e7 整数，QLineEdit 支持粘贴）──
    if kind == "latlon":
        val = float(default) if isinstance(default, (int, float)) else 0.0
        if isinstance(default, int) and not isinstance(default, bool):
            val = default / 10_000_000.0
        le = QLineEdit(str(val))
        le.setObjectName(f"{aid}{slot_id}")
        le.setPlaceholderText("度, 如 22.6868764")
        le.setToolTip("经纬度 (度), 上限 ±200, 自动 ×10000000")
        return (le,
                lambda w=le: int(round(float(w.text() or "0") * 10_000_000)),
                lambda v, w=le: w.setText(
                    f"{(v / 10_000_000.0):.7f}" if isinstance(v, (int, float)) else str(v)
                ))

    # ── 高度（米 → 毫米整数，QLineEdit 支持粘贴）──
    if kind == "alt_m":
        val = float(default) if isinstance(default, (int, float)) else 0.0
        if isinstance(default, int) and not isinstance(default, bool):
            val = default / 1000.0
        le = QLineEdit(str(val))
        le.setObjectName(f"{aid}{slot_id}")
        le.setPlaceholderText("米, 如 100.5")
        le.setToolTip("高度 (米), 上限 ±10000, 自动 ×1000")
        return (le,
                lambda w=le: int(round(float(w.text() or "0") * 1000)),
                lambda v, w=le: w.setText(
                    f"{(v / 1000.0):.3f}" if isinstance(v, (int, float)) else str(v)
                ))

    if kind == "bool":
        cb = _LimitedCombo(20)
        cb.addItem("True", userData=True)
        cb.addItem("False", userData=False)
        cur = bool(default) if isinstance(default, bool) else False
        idx = 0 if cur else 1
        cb.setCurrentIndex(idx)
        cb.setObjectName(f"{aid}{slot_id}")
        cb.setToolTip(hint)
        return cb, lambda w=cb: w.currentData(), cb.setCurrentIndex

    le = QLineEdit(_default_to_text(default))
    le.setObjectName(f"{aid}{slot_id}")
    le.setPlaceholderText(hint)
    le.setToolTip(hint)
    return le, le.text, le.setText


# ═══════════════════════════════════════════════════════════════
# SimConfig —— 模拟器元配置
# ═══════════════════════════════════════════════════════════════
