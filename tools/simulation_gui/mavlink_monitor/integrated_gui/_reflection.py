"""AST 动态反射 — 直接从源文件读取模块常量、__init__ 中 self.X 的类型。

从 integrated_gui.py 拆分出来的独立模块。
"""
from __future__ import annotations

import ast
import inspect
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# ═══════════════════════════════════════════════════════════════
# AST 动态反射 —— 直接从源文件读取模块常量、__init__ 中 self.X 的类型
# ═══════════════════════════════════════════════════════════════
@dataclass
class SourceInfo:
    """源文件的反射信息。"""
    module_constants: dict[str, tuple[Any, str]]    # name -> (value, kind)
    init_attrs: dict[str, str]                        # self_attr_name -> kind
    init_defaults: dict[str, Any] = field(default_factory=dict)


@dataclass
class NestedDeviceMeta:
    """嵌套设备元数据（AST 解析结果）。"""
    cls_name: str
    label: str
    sender_update_method: str
    sender_instances_attr: str
    instance_mode: str          # "dict" 或 "single"
    fields: dict = field(default_factory=dict)  # {field_name: (default, kind)}


def _constant_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, bytes):
        return "bytes"
    return "str"


def _literal_kind(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant):
        return _constant_kind(node.value)
    if isinstance(node, ast.List):
        return "list"
    if isinstance(node, ast.Tuple):
        return "list"
    if isinstance(node, ast.Dict):
        return "dict"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        if isinstance(node.left, (ast.List, ast.Tuple)) or \
           isinstance(node.right, (ast.List, ast.Tuple)):
            return "list"
        return "int"
    return None


def _resolve_literal_value(
    node: ast.AST,
    module_constants: dict[str, tuple[Any, str]],
) -> Any:
    """把 AST 节点解析为可用的 Python 值（用于 init_defaults）。"""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        try:
            return [_resolve_literal_value(e, module_constants) for e in node.elts]
        except Exception:
            return None
    if isinstance(node, ast.Tuple):
        try:
            return tuple(_resolve_literal_value(e, module_constants)
                         for e in node.elts)
        except Exception:
            return None
    if isinstance(node, ast.Name):
        const = module_constants.get(node.id)
        if const is not None:
            return const[0]
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left = _resolve_literal_value(node.left, module_constants)
        right = _resolve_literal_value(node.right, module_constants)
        if left is not None and right is not None:
            try:
                return left * right
            except Exception:
                return None
    return None


def _resolve_self_assign_value(
    sub: ast.Assign,
    args: ast.arguments,
    module_constants: dict[str, tuple[Any, str]],
) -> Any:
    """解析 self.X = ... 的右侧值。"""
    node = sub.value
    if isinstance(node, ast.Name):
        param_name = node.id
        num_args = len(args.args)
        for i, arg in enumerate(args.args):
            if arg.arg != param_name:
                continue
            default_idx = i - (num_args - len(args.defaults))
            if 0 <= default_idx < len(args.defaults):
                return _resolve_literal_value(
                    args.defaults[default_idx], module_constants
                )
            return None
        return None
    return _resolve_literal_value(node, module_constants)


def _parse_source(
    path: Path,
    sender_cls_name: str,
    mgr_cls_name: str,
) -> SourceInfo:
    """解析源文件，提取模块常量、__init__ 中 self.X 的类型。"""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    module_constants: dict[str, tuple[Any, str]] = {}
    init_attrs: dict[str, str] = {}
    init_defaults: dict[str, Any] = {}

    for node in tree.body:
        # 模块级赋值（int/float/str/bytes/bool）
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and isinstance(node.value, ast.Constant):
                kind = _constant_kind(node.value.value)
                if kind in ("int", "float", "str", "bytes", "bool"):
                    module_constants[tgt.id] = (node.value.value, kind)

        # 类定义
        if isinstance(node, ast.ClassDef):
            # 类体内的「类级常量」
            for item in node.body:
                if (isinstance(item, ast.Assign) and len(item.targets) == 1):
                    tgt = item.targets[0]
                    if (isinstance(tgt, ast.Name) and
                            isinstance(item.value, ast.Constant)):
                        kind = _constant_kind(item.value.value)
                        if kind in ("int", "float", "str", "bytes", "bool"):
                            module_constants.setdefault(tgt.id,
                                                        (item.value.value, kind))

            if node.name not in (sender_cls_name, mgr_cls_name):
                continue
            for item in node.body:
                if not isinstance(item, ast.FunctionDef) or item.name != "__init__":
                    continue

                # 第一遍：建立 __init__ 形参 -> kind 的映射
                init_params: dict[str, str] = {}
                args = item.args
                num_args = len(args.args)
                defaults = args.defaults
                for i, default in enumerate(defaults):
                    arg_idx = num_args - len(defaults) + i
                    if arg_idx < 1:  # 跳过 self
                        continue
                    arg_name = args.args[arg_idx].arg
                    kind = _literal_kind(default)
                    if kind is None and isinstance(default, ast.Name):
                        const = module_constants.get(default.id)
                        if const is not None:
                            kind = const[1]
                    if kind is not None:
                        init_params[arg_name] = kind

                # 第二遍：扫描 self.X = ... 赋值
                for sub in ast.walk(item):
                    if not isinstance(sub, ast.Assign):
                        continue
                    kind = _literal_kind(sub.value)
                    if kind is None and isinstance(sub.value, ast.Name):
                        kind = init_params.get(sub.value.id)
                    if kind is None:
                        continue
                    value = _resolve_self_assign_value(
                        sub, args, module_constants
                    )
                    for t in sub.targets:
                        if (isinstance(t, ast.Attribute) and
                                isinstance(t.value, ast.Name) and
                                t.value.id == "self" and
                                isinstance(t.attr, str)):
                            init_attrs[t.attr] = kind
                            if value is not None:
                                init_defaults[t.attr] = value

    return SourceInfo(
        module_constants=module_constants,
        init_attrs=init_attrs,
        init_defaults=init_defaults,
    )


# ═══════════════════════════════════════════════════════════════
# AST 动态解析：嵌套设备类
# ═══════════════════════════════════════════════════════════════
def _inherits_from(cls_node: ast.ClassDef, base_name: str) -> bool:
    for base in cls_node.bases:
        if isinstance(base, ast.Name) and base.id == base_name:
            return True
        if isinstance(base, ast.Attribute) and base.attr == base_name:
            return True
    return False


def _extract_string_attr(cls_node: ast.ClassDef, attr_name: str) -> str | None:
    for item in cls_node.body:
        if not isinstance(item, ast.Assign) or len(item.targets) != 1:
            continue
        tgt = item.targets[0]
        if isinstance(tgt, ast.Name) and tgt.id == attr_name:
            if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                return item.value.value
    return None


def _infer_list_element_kind(node: ast.AST) -> str:
    elements: list[ast.AST] = []
    if isinstance(node, ast.List):
        elements = node.elts
    elif isinstance(node, ast.Tuple):
        elements = node.elts
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left_list = None
        if isinstance(node.left, (ast.List, ast.Tuple)):
            left_list = node.left
        elif isinstance(node.right, (ast.List, ast.Tuple)):
            left_list = node.right
        if left_list is not None:
            elements = left_list.elts
    if not elements:
        return "list"
    if all(
        isinstance(e, ast.Constant)
        and isinstance(e.value, int)
        and not isinstance(e.value, bool)
        for e in elements
    ):
        return "list_int"
    return "list"


def _parse_nested_device_class(
    cls_node: ast.ClassDef,
    module_constants: dict[str, tuple[Any, str]],
) -> NestedDeviceMeta | None:
    """解析单个 _NestedDeviceBase 子类的 AST → NestedDeviceMeta。"""
    label = _extract_string_attr(cls_node, "_DEVICE_LABEL")
    update_method = _extract_string_attr(cls_node, "_SENDER_UPDATE_METHOD")
    instances_attr = _extract_string_attr(cls_node, "_SENDER_INSTANCES_ATTR")
    instance_mode = _extract_string_attr(cls_node, "_INSTANCE_MODE")

    if not all([label, update_method, instances_attr, instance_mode]):
        return None

    mc_simple = {k: v[0] for k, v in module_constants.items()}
    fields: dict[str, tuple[Any, str]] = {}

    # 1) 优先读取 _UPDATABLE_FIELDS 显式声明
    for item in cls_node.body:
        if not isinstance(item, ast.Assign) or len(item.targets) != 1:
            continue
        tgt = item.targets[0]
        if not (isinstance(tgt, ast.Name) and tgt.id == "_UPDATABLE_FIELDS"):
            continue
        if not isinstance(item.value, ast.Dict):
            continue
        for key_node, val_node in zip(item.value.keys, item.value.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                continue
            fname = key_node.value
            if not isinstance(val_node, ast.Tuple) or len(val_node.elts) != 2:
                continue
            default_node, kind_node = val_node.elts
            if not isinstance(kind_node, ast.Constant) or not isinstance(kind_node.value, str):
                continue
            kind = kind_node.value
            default = _resolve_literal_value(default_node, mc_simple)
            fields[fname] = (default, kind)

    # 2) 自动推导：__init__ 中 self.X = value
    for item in cls_node.body:
        if not isinstance(item, ast.FunctionDef) or item.name != "__init__":
            continue
        for sub in ast.walk(item):
            if not isinstance(sub, ast.Assign):
                continue
            for t in sub.targets:
                if not (isinstance(t, ast.Attribute)
                        and isinstance(t.value, ast.Name)
                        and t.value.id == "self"
                        and isinstance(t.attr, str)):
                    continue
                fname = t.attr
                if fname.startswith("_"):
                    continue
                if fname in fields:
                    continue
                kind = _literal_kind(sub.value)
                if kind is None:
                    continue
                if kind == "list":
                    kind = _infer_list_element_kind(sub.value)
                default = _resolve_literal_value(sub.value, mc_simple)
                fields[fname] = (default, kind)

    return NestedDeviceMeta(
        cls_name=cls_node.name,
        label=label,
        sender_update_method=update_method,
        sender_instances_attr=instances_attr,
        instance_mode=instance_mode,
        fields=fields,
    )


def _parse_nested_devices_from_source(path: Path) -> dict[str, NestedDeviceMeta]:
    """解析源文件 AST，发现所有 _NestedDeviceBase 子类。"""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    module_constants: dict[str, tuple[Any, str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for sub in node.body:
                if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                        and isinstance(sub.targets[0], ast.Name)
                        and isinstance(sub.value, ast.Constant)):
                    kd = _constant_kind(sub.value.value)
                    if kd in ("int", "float", "str", "bytes", "bool"):
                        module_constants.setdefault(sub.targets[0].id, (sub.value.value, kd))
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and isinstance(node.value, ast.Constant):
                kd = _constant_kind(node.value.value)
                if kd in ("int", "float", "str", "bytes", "bool"):
                    module_constants[tgt.id] = (node.value.value, kd)

    result: dict[str, NestedDeviceMeta] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not _inherits_from(node, "_NestedDeviceBase"):
            continue
        if node.name == "_NestedDeviceBase":
            continue
        meta = _parse_nested_device_class(node, module_constants)
        if meta is not None:
            result[node.name] = meta

    return result


# ═══════════════════════════════════════════════════════════════
# docstring 动态解析：**kwargs 类方法
# ═══════════════════════════════════════════════════════════════
# 多种 docstring 格式：
#   "支持的关键字：a / b / c"
#   "支持的关键字对齐 msg_id=83 字段：a / b / c"
#   "支持：a / b / c"  或跨行列表形式
_KEYWORD_HINT_RE = re.compile(
    r"支持(?:的)?关键字(?:[^：:\n]*?)[：:]\s*(.+?)(?=\n\s*\n|。|\(|\（|$)",
    re.DOTALL,
)
# 回退：仅含 "支持：" 的格式（无 "关键字" 三字），捕获到 Args/Note 或段落结束
_SUPPORT_PLAIN_RE = re.compile(
    r"支持[：:]\s*\n?\s*(.+?)(?=\n\s*\n\s*(?:Args|Note|Raises|Return)|。\s*\n|$)",
    re.DOTALL,
)
_KW_SEP_RE = re.compile(r"[\s/、,，;；]+")
_SPHINX_PARAM_RE = re.compile(r":param\s+(\w+)\s*:", re.DOTALL)


def _parse_supported_keywords_from_docstring(method: Callable) -> list[str] | None:
    doc = inspect.getdoc(method)
    if not doc:
        return None
    # 优先匹配 "支持的关键字…：" 格式
    m = _KEYWORD_HINT_RE.search(doc)
    if not m:
        # 回退匹配 "支持：" 格式（无 "关键字" 三字）
        m = _SUPPORT_PLAIN_RE.search(doc)
    if not m:
        return None
    raw = m.group(1)
    # 去掉跨行列表中的前导空白，归一化为单行以便切分
    raw = " ".join(line.strip() for line in raw.splitlines() if line.strip())
    return [tok for tok in _KW_SEP_RE.split(raw) if tok]


def _parse_sphinx_params_from_docstring(method: Callable) -> list[str] | None:
    """从 Sphinx 风格的 ``:param name:`` 指令中提取参数名列表。"""
    doc = inspect.getdoc(method)
    if not doc:
        return None
    matches = _SPHINX_PARAM_RE.findall(doc)
    return matches if matches else None

