"""NestedDevicePanel — 嵌套设备子 Tab。

从 integrated_gui.py 拆分出来的独立模块。
依赖: ._reflection, ._types
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QSpacerItem, QVBoxLayout,
    QWidget,
)

from mavlink_monitor.gui.widgets import _CollapseToggle, _LimitedCombo

from ._env import _FakeAirplaneMessageSender
from ._reflection import (
    NestedDeviceMeta,
    _parse_sphinx_params_from_docstring,
    _parse_supported_keywords_from_docstring,
)
from ._types import (
    _EST_FORM_ROW_HEIGHT, _coerce, _detect_kind, _make_input_widget,
)


# ═══════════════════════════════════════════════════════════════
# NestedDevicePanel —— 嵌套设备子 Tab
# ═══════════════════════════════════════════════════════════════
class NestedDevicePanel(QWidget):
    """单个嵌套设备类型的控制面板（子 Tab 内容）。

    扫描嵌套设备类的 update_xxx 方法，动态生成参数表单，
    支持 update 方法切换与目标设备切换时保存/恢复参数值。
    """

    def __init__(
        self,
        meta,
        senders_getter: Callable[[], list],
        set_status: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._meta = meta
        self._nested_cls = meta.cls          # 嵌套设备类（如 _NestAirplane）
        self._senders_getter = senders_getter
        self._set_status = set_status
        cls_name = self._nested_cls.__name__
        self._aid = f"FN_SUB_{cls_name.upper()}_"
        self._target_keys: list[tuple[int, Any]] = []
        self._update_param_widgets: dict[str, tuple[Any, Callable, Callable, str]] = {}

        # 持久化：{target_key: {method_name: {param_name: value}}}
        self._saved_update_params: dict[str, dict[str, dict[str, Any]]] = {}
        self._current_update_method: str = ""
        self._current_target: str = ""

        # 扫描嵌套设备类的 update_xxx 方法
        self._update_methods = self._discover_update_methods()

        self._build_ui()
        self.refresh_targets()  # 内部会触发首次 _refresh_update_params

    # ── 代码扫描 ──
    @staticmethod
    def _scan_update_methods_on_cls(
        cls: type, methods: dict[str, dict[str, Any]],
    ) -> None:
        """扫描一个类上的 update_xxx 方法，合并到 methods 字典。"""
        updatable_fields: dict = getattr(cls, '_UPDATABLE_FIELDS', {})

        for name in dir(cls):
            if not name.startswith("update_") or name == "update":
                continue
            if name in methods:          # 嵌套设备自身的方法优先
                continue
            attr = getattr(cls, name, None)
            if attr is None or not callable(attr):
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
            # 自适应入参：含 **kwargs 时，从 docstring / _UPDATABLE_FIELDS 提取字段并合并
            if has_var_keyword:
                # 1) 优先从 "支持的关键字: …" / "支持：" 格式提取
                keywords = _parse_supported_keywords_from_docstring(attr)
                if keywords:
                    for kw in keywords:
                        if kw not in params:
                            field_info = updatable_fields.get(kw)
                            params[kw] = field_info[0] if field_info else None
                # 2) 尝试从 Sphinx :param name: 格式提取（仅当无命名参数时）
                elif not params:
                    sphinx_params = _parse_sphinx_params_from_docstring(attr)
                    if sphinx_params:
                        for pname in sphinx_params:
                            field_info = updatable_fields.get(pname)
                            params[pname] = field_info[0] if field_info else None
                    # 3) 回退到 _UPDATABLE_FIELDS（update_state 等方法接受全部字段）
                    elif updatable_fields:
                        for fname, (default, _kind) in updatable_fields.items():
                            params[fname] = default
                # 4) 已有命名参数 + **kwargs 但无关键词列表：保留命名参数
            if params:
                methods[name] = params

    def _discover_update_methods(self) -> dict[str, dict[str, Any]]:
        """扫描嵌套设备类上所有 update_xxx 方法。

        轻型假飞机额外合并 _FakeAirplaneMessageSender 的独立 update_xxx 方法
        （如 update_nova_light_version / update_laser 等），使每个方法仅展示
        自身领域的参数，与单独假飞机 Tab 的体验保持一致。
        """
        methods: dict[str, dict[str, Any]] = {}
        self._scan_update_methods_on_cls(self._nested_cls, methods)

        # 轻型假飞机：额外暴露 _FakeAirplaneMessageSender 上的独立 update_xxx
        cls_name = self._nested_cls.__name__
        if cls_name in ('_NestedAirplane', '_NestAirplane'):
            try:
                self._scan_update_methods_on_cls(
                    _FakeAirplaneMessageSender, methods,
                )
            except NameError:
                pass

        return methods

    # ── UI 构建 ──
    def _build_ui(self) -> None:
        _NESTED_MAX_ROWS = 25
        self.setObjectName(f"{self._aid}PANEL")
        root = QVBoxLayout(self)

        # ── 顶栏：目标设备 + update 方法 ──
        sel = QHBoxLayout()
        sel.addWidget(QLabel("目标设备:"))
        self._combo_target = _LimitedCombo(20)
        self._combo_target.setObjectName(f"{self._aid}COMBO_TARGET")
        self._combo_target.setMinimumWidth(200)
        self._combo_target.currentTextChanged.connect(self._on_target_changed)
        sel.addWidget(self._combo_target)
        sel.addSpacing(24)
        sel.addWidget(QLabel("update 方法:"))
        self._combo_update = _LimitedCombo(20)
        self._combo_update.setObjectName(f"{self._aid}COMBO_UPDATE")
        for m in self._update_methods:
            self._combo_update.addItem(m)
        self._combo_update.currentTextChanged.connect(self._refresh_update_params)
        sel.addWidget(self._combo_update)
        root.addLayout(sel)

        # ── 参数区域（动态重建，始终包一层 QScrollArea 限制 25 行）──
        self._params_scroll = QScrollArea()
        self._params_scroll.setWidgetResizable(True)
        self._params_scroll.setObjectName(f"{self._aid}SCROLL_PARAMS")
        self._params_scroll.setMinimumHeight(_NESTED_MAX_ROWS * _EST_FORM_ROW_HEIGHT)
        self._params_container = QWidget()
        self._params_container.setObjectName(f"{self._aid}PARAMS_CONTAINER")
        self._params_form = QFormLayout(self._params_container)
        self._params_scroll.setWidget(self._params_container)
        root.addWidget(self._params_scroll, stretch=1)

        # ── 应用按钮 ──
        self._btn_apply = QPushButton("应用 update")
        self._btn_apply.setObjectName(f"{self._aid}BTN_APPLY")
        self._btn_apply.clicked.connect(self._on_apply_clicked)
        root.addWidget(self._btn_apply)

    # ── 持久化 ──
    def _save_current_form_values(self, method: str | None = None,
                                   target: str | None = None) -> None:
        if method is None:
            method = self._combo_update.currentText()
        if target is None:
            target = self._combo_target.currentData()
        if not method or not self._update_param_widgets or target is None:
            return
        values: dict[str, Any] = {}
        for pname, (_w, getter, _s, kind) in self._update_param_widgets.items():
            try:
                raw = getter()
                values[pname] = _coerce(raw, kind) if isinstance(raw, str) else raw
            except Exception:
                continue
        self._saved_update_params.setdefault(target, {})[method] = values

    def _load_saved_values(self, target_key: str, method_name: str) -> dict[str, Any] | None:
        return self._saved_update_params.get(target_key, {}).get(method_name)

    # ── 动态 choices ──
    def _get_dynamic_choices(
        self, pname: str, method: str,
    ) -> dict[str, str] | None:
        """返回嵌套设备参数的可选值 dict（label -> value），未匹配返回 None。"""
        if pname == "ip_str":
            return self._get_instance_key_choices()
        return None

    def _get_instance_key_choices(self) -> dict[str, str]:
        """收集当前 sender 的嵌套实例 key 列表（如飞机 IP）。"""
        choices: dict[str, str] = {}
        target = self._current_target
        if not target or target == "__ALL__":
            return choices
        senders = self._senders_getter()
        try:
            parts = target.split(":", 1)
            sender_idx = int(parts[0])
            sender = senders[sender_idx]
        except (ValueError, IndexError):
            return choices
        instances = getattr(sender, self._meta.sender_instances_attr, None)
        if isinstance(instances, dict):
            for key in instances:
                choices[key] = key
        return choices

    # ── 动态参数渲染 ──
    @Slot(str)
    def _refresh_update_params(self, _method: str | None = None) -> None:
        # 保存旧值（使用旧 method + 旧 target）
        if self._current_update_method and self._update_param_widgets:
            self._save_current_form_values(
                method=self._current_update_method,
                target=self._current_target,
            )
        # 清空表单
        while self._params_form.count():
            item = self._params_form.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._update_param_widgets = {}

        method = self._combo_update.currentText()
        self._current_update_method = method
        self._current_target = self._combo_target.currentData() or ""
        if not method or method not in self._update_methods:
            return

        target = self._current_target
        saved = self._load_saved_values(target, method) if target else None

        params = self._update_methods[method]

        # update_position: GUI 表单中 lon 在前 lat 在后
        if method == "update_position":
            _lon_lat_order = ["cur_lon", "cur_lat", "tar_lon", "tar_lat",
                              "cur_alt", "tar_alt", "fix_type"]
            params = {k: params[k] for k in _lon_lat_order if k in params}
        for pname, default in params.items():
            # 优先使用 _UPDATABLE_FIELDS 声明的精确类型，其次启发式推断
            field_info = self._meta.fields.get(pname)
            if field_info is not None:
                kind = field_info[1]
                if default is None:
                    default = field_info[0]
            else:
                kind = _detect_kind(default, pname)
            value = saved.get(pname) if (saved and pname in saved) else default
            # 动态 choices（ip_str 等）
            choices = self._get_dynamic_choices(pname, method)
            slot_id = f"PARAM_{method.upper()}_{pname.upper()}"
            widget, getter, setter = _make_input_widget(self._aid, slot_id, value, kind, choices=choices)
            kind_label = "choice" if choices else kind
            lbl = QLabel(f"{pname}  <{kind_label}>")
            lbl.setObjectName(f"{self._aid}LBL_{slot_id}")
            self._params_form.addRow(lbl, widget)
            self._update_param_widgets[pname] = (widget, getter, setter, kind)

    @Slot(str)
    def _on_target_changed(self, _text: str) -> None:
        self._refresh_update_params()

    # ── 目标列表刷新 ──
    def refresh_targets(self) -> None:
        self._combo_target.blockSignals(True)
        try:
            self._combo_target.clear()
            self._target_keys = []

            # ── 全选选项 ──
            self._combo_target.addItem("【全选】", userData="__ALL__")
            self._target_keys.append((-1, "__ALL__"))

            senders = self._senders_getter()

            for i, sender in enumerate(senders):
                instances = getattr(sender, self._meta.sender_instances_attr, None)
                if instances is None:
                    continue

                if self._meta.instance_mode == "dict":
                    for key in instances:
                        label = f"巢#{i} / {key}"
                        self._combo_target.addItem(label, userData=f"{i}:{key}")
                        self._target_keys.append((i, key))
                else:
                    if instances is not None:
                        label = f"巢#{i} (在线)"
                        self._combo_target.addItem(label, userData=str(i))
                        self._target_keys.append((i, None))

            if len(self._target_keys) <= 1:  # 只有全选，无实际实例
                self._combo_target.addItem("(无可用实例 — 请先在巢端启用)")
        finally:
            self._combo_target.blockSignals(False)
        # 加载当前选中 target 的已保存参数
        self._refresh_update_params()

    # ── 应用 ──
    @Slot()
    def _on_apply_clicked(self) -> None:
        method_name = self._combo_update.currentText()
        if not method_name or method_name not in self._update_methods:
            return

        idx = self._combo_target.currentIndex()
        if idx < 0 or idx >= len(self._target_keys):
            QMessageBox.warning(self, "错误", "请先选择一个有效的目标设备")
            return

        # 收集参数
        kwargs: dict[str, Any] = {}
        for pname, (_w, getter, _s, kind) in self._update_param_widgets.items():
            try:
                raw = getter()
                kwargs[pname] = _coerce(raw, kind) if isinstance(raw, str) else raw
            except Exception as e:
                QMessageBox.warning(self, "参数错误", f"{pname} 解析失败: {e}")
                return

        sender_idx, instance_key = self._target_keys[idx]
        target_key = self._combo_target.currentData() or ""

        # ── 全选：遍历所有 sender 的所有实例 ──
        if instance_key == "__ALL__":
            senders = self._senders_getter()
            total = 0
            failed = 0
            for si, sender in enumerate(senders):
                instances = getattr(sender, self._meta.sender_instances_attr, None)
                if instances is None:
                    continue
                if self._meta.instance_mode == "dict":
                    for key, inst in instances.items():
                        try:
                            getattr(inst, method_name)(**kwargs)
                            total += 1
                        except Exception as e:
                            failed += 1
                            print(f"[GUI] 巢#{si}/{key} {method_name} 失败: {e}")
                else:
                    try:
                        getattr(instances, method_name)(**kwargs)
                        total += 1
                    except Exception as e:
                        failed += 1
                        print(f"[GUI] 巢#{si} {method_name} 失败: {e}")

            # 持久化：覆盖所有个体的该 update 全部字段
            for si, sender in enumerate(senders):
                insts = getattr(sender, self._meta.sender_instances_attr, None)
                if insts is None:
                    continue
                if self._meta.instance_mode == "dict":
                    for key in insts:
                        k = f"{si}:{key}"
                        self._saved_update_params.setdefault(k, {})[method_name] = dict(kwargs)
                else:
                    k = str(si)
                    self._saved_update_params.setdefault(k, {})[method_name] = dict(kwargs)
            # 同时保存 __ALL__ 自身
            self._saved_update_params.setdefault("__ALL__", {})[method_name] = dict(kwargs)

            self._set_status(
                f"[{self._meta.label}] 全选: 已对 {total - failed}/{total} 个执行 {method_name}"
            )
            return

        # ── 单个目标 ──
        senders = self._senders_getter()
        try:
            sender = senders[sender_idx]
        except IndexError:
            QMessageBox.warning(self, "错误", f"巢 #{sender_idx} 不存在")
            return

        instances = getattr(sender, self._meta.sender_instances_attr, None)
        if instances is None:
            QMessageBox.warning(self, "错误", "未找到嵌套设备实例")
            return
        if self._meta.instance_mode == "dict":
            instance = instances.get(instance_key)
        else:
            instance = instances
        if instance is None:
            QMessageBox.warning(self, "错误", f"实例 {instance_key} 不存在")
            return

        # 持久化
        self._saved_update_params.setdefault(target_key, {})[method_name] = dict(kwargs)

        method = getattr(instance, method_name)
        try:
            method(**kwargs)
        except Exception as e:
            QMessageBox.critical(self, "更新失败", str(e))
            return

        self._set_status(
            f"[{self._meta.label}] 已更新巢#{sender_idx}"
            + (f" / {instance_key}" if instance_key is not None else "")
        )


