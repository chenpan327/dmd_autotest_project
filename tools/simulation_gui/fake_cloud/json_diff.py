"""fake_cloud.json_diff — JSON 递归 diff 与 HTML 高亮（纯函数）。

当前「监听阶段」代理不改写内容；本模块作为工具就位，供：

  * ``tampered_response`` 事件出现后（后续篡改阶段）由 GUI 详情视图调用
    ``highlight_html(original, tampered)`` 渲染字段级高亮对比；
  * 测试（TC3）直接验证 diff 语义。

设计约定：
  * diff 路径语法：``$.data[0].title``（对象 key 直接拼接，数组用 ``[i]``）；
  * 高亮样式：改=黄底、增=绿底、删=红底删除线；改动值悬停 title 提示原值。
"""
from __future__ import annotations

import html
from typing import Any

# 预留篡改阶段的高亮样式（与 GUI CloudMessageView 颜色体系一致）
CHANGED_STYLE = "background:#ffe58f;border-radius:3px;"
ADDED_STYLE = "background:#b7eb8f;border-radius:3px;"
REMOVED_STYLE = "background:#ffa39e;border-radius:3px;text-decoration:line-through;opacity:0.75;"

_KIND_STYLE = {
    "changed": CHANGED_STYLE,
    "added": ADDED_STYLE,
    "removed": REMOVED_STYLE,
}

# 语法高亮配色（详情区 JSON 渲染）
_C_KEY = "#0033b3"
_C_STR = "#067d17"
_C_NUM = "#1750eb"
_C_BOOL = "#871094"

_MISSING = object()  # diff 哨兵：一侧不存在该节点


# ═══════════════════════════════════════════════════════════════
# diff
# ═══════════════════════════════════════════════════════════════
def diff_json(original: Any, tampered: Any, path: str = "$") -> list[dict]:
    """递归对比两份 JSON，返回差异条目列表。

    每条: ``{"path": "$.data[0].title", "kind": "changed|added|removed",
             "old": <原值或 None>, "new": <新值或 None>}``
    """
    entries: list[dict] = []
    if original is _MISSING and tampered is _MISSING:
        return entries
    if original is _MISSING:
        entries.append({"path": path, "kind": "added", "old": None, "new": tampered})
        return entries
    if tampered is _MISSING:
        entries.append({"path": path, "kind": "removed", "old": original, "new": None})
        return entries

    if isinstance(original, dict) and isinstance(tampered, dict):
        for k in original:
            child = f"{path}.{k}"
            if k not in tampered:
                entries.append({"path": child, "kind": "removed", "old": original[k], "new": None})
            else:
                entries.extend(diff_json(original[k], tampered[k], child))
        for k in tampered:
            if k not in original:
                entries.append({"path": f"{path}.{k}", "kind": "added", "old": None, "new": tampered[k]})
        return entries

    if isinstance(original, list) and isinstance(tampered, list):
        for i in range(max(len(original), len(tampered))):
            o = original[i] if i < len(original) else _MISSING
            t = tampered[i] if i < len(tampered) else _MISSING
            entries.extend(diff_json(o, t, f"{path}[{i}]"))
        return entries

    if original != tampered:
        entries.append({"path": path, "kind": "changed", "old": original, "new": tampered})
    return entries


# ═══════════════════════════════════════════════════════════════
# HTML 渲染
# ═══════════════════════════════════════════════════════════════
def _fmt_scalar(value: Any) -> str:
    if isinstance(value, str):
        return f'<span style="color:{_C_STR}">&quot;{html.escape(value)}&quot;</span>'
    if isinstance(value, bool):
        return f'<span style="color:{_C_BOOL}">{value}</span>'
    if value is None:
        return f'<span style="color:{_C_BOOL}">null</span>'
    if isinstance(value, (int, float)):
        return f'<span style="color:{_C_NUM}">{value}</span>'
    return html.escape(str(value))


def _wrap_mark(inner: str, kind: str, old: Any = None) -> str:
    style = _KIND_STYLE.get(kind, "")
    title = ""
    if kind == "changed" and old is not None:
        title = f' title="原值: {html.escape(repr(old))}"'
    mark = "⚠" if kind == "changed" else ("＋" if kind == "added" else "－")
    return (f'<span style="{style}"{title}>'
            f'<span style="color:#d46b08">{mark}</span>{inner}</span>')


def render_json_html(obj: Any, marks: dict[str, dict] | None = None,
                     path: str = "$", indent: int = 0) -> str:
    """把 JSON 渲染为带语法高亮的 HTML 片段（缩进 2 空格风格）。

    ``marks``: ``{diff_path: {"kind": ..., "old": ...}}`` → 命中路径的节点
    附加篡改高亮（由 ``highlight_html`` 生成）。
    """
    marks = marks or {}
    pad = "&nbsp;" * (indent * 2)
    mark = marks.get(path)
    mk = mark["kind"] if mark else None
    old = mark.get("old") if mark else None

    if isinstance(obj, dict):
        if not obj:
            return _maybe_mark("{}", mk, old)
        rows = []
        for k, v in obj.items():
            child = f"{path}.{k}"
            key_html = f'<span style="color:{_C_KEY}">&quot;{html.escape(k)}&quot;</span>'
            rendered = render_json_html(v, marks, child, indent + 1)
            if rendered.startswith("<div"):
                rows.append(f"{pad}&nbsp;&nbsp;{key_html}: {rendered.lstrip()}")
            else:
                rows.append(f"{pad}&nbsp;&nbsp;{key_html}: {rendered}")
        body = ",<br>".join(rows)
        return _maybe_mark("{", mk, old, open_only=True) + f"<br>{body}<br>{pad}}}"

    if isinstance(obj, list):
        if not obj:
            return _maybe_mark("[]", mk, old)
        rows = []
        for i, v in enumerate(obj):
            child = f"{path}[{i}]"
            rendered = render_json_html(v, marks, child, indent + 1)
            rows.append(f"{pad}&nbsp;&nbsp;{rendered}")
        body = ",<br>".join(rows)
        return _maybe_mark("[", mk, old, open_only=True) + f"<br>{body}<br>{pad}]"

    # 标量：直接包裹（可能带高亮）
    if mk:
        return _wrap_mark(_fmt_scalar(obj), mk, old)
    return _fmt_scalar(obj)


def _maybe_mark(text: str, kind: str | None, old: Any = None,
                open_only: bool = False) -> str:
    """容器开括号的高亮处理（标量走 _wrap_mark）。"""
    if not kind:
        return text
    style = _KIND_STYLE.get(kind, "")
    mark = "⚠" if kind == "changed" else ("＋" if kind == "added" else "－")
    prefix = f'<span style="{style}"><span style="color:#d46b08">{mark}</span>{text}'
    if open_only:
        return prefix  # 闭括号不重复包 span，保持结构简单
    return prefix + "</span>"


def syntax_highlight(obj: Any) -> str:
    """纯语法高亮渲染（无 diff 标记），供 GUI 详情区展示任意 JSON。"""
    return f'<div style="font-family:Consolas,monospace;font-size:12px;">' \
           f'{render_json_html(obj)}</div>'


def highlight_html(original: Any, tampered: Any, title: str = "篡改对比") -> str:
    """渲染 original → tampered 的字段级高亮对比 HTML。

    改动字段黄底 ⚠（悬停显示原值）、新增绿底 ＋、删除红底 －。
    """
    diffs = diff_json(original, tampered)
    marks = {d["path"]: d for d in diffs}
    body = render_json_html(tampered, marks)
    changed = sum(1 for d in diffs if d["kind"] == "changed")
    added = sum(1 for d in diffs if d["kind"] == "added")
    removed = sum(1 for d in diffs if d["kind"] == "removed")
    legend = (
        f'<div style="margin-bottom:4px;color:#555;">'
        f'<b>{html.escape(title)}</b>&nbsp; '
        f'<span style="background:#ffe58f;">&nbsp;改 {changed}&nbsp;</span> '
        f'<span style="background:#b7eb8f;">&nbsp;增 {added}&nbsp;</span> '
        f'<span style="background:#ffa39e;">&nbsp;删 {removed}&nbsp;</span>'
        f'</div>'
    )
    return (
        f'<div style="font-family:Consolas,monospace;font-size:12px;">'
        f'{legend}{body}</div>'
    )
