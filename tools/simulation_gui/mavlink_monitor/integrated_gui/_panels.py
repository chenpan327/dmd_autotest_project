"""SimulationPanel — 通用模拟设备控制面板。

从 integrated_gui.py 拆分出来的独立模块。
依赖: ._config, ._nested, ._types, ._reflection
"""
from __future__ import annotations

import ast
import importlib
import inspect
import os
import re
import struct
import sys
import textwrap
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSpacerItem, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
    QWidget,
)

from mavlink_monitor.gui.widgets import _CollapseToggle, _LimitedCombo

from ._env import HAS_FAKE_MODULES, NESTED_DEVICE_REGISTRY, _FakeRadioSender

from ._config import SimConfig, _SocketInterceptor
from ._nested import NestedDevicePanel
from ._reflection import SourceInfo, _parse_source, _parse_nested_devices_from_source
from ._types import (
    _coerce, _detect_kind, _discover_add_params, _discover_update_methods,
    _make_input_widget, _MIN_VISIBLE_FORM_ROWS, _EST_FORM_ROW_HEIGHT,
)

# ═══════════════════════════════════════════════════════════════
# SimulationPanel —— 通用模拟设备控制面板
# ═══════════════════════════════════════════════════════════════
class SimulationPanel(QWidget):
    """通用模拟设备控制面板。

    通过 ``config`` 注入具体的类引用与源文件路径，
    内部所有反射 / 控件生成逻辑对 FakeAirplane / FakeNest / FakeRadio 都一致。
    """

    def __init__(
        self,
        config: SimConfig,
        log_manager: "LogManager",
        status_setter: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._config = config
        self._log_manager = log_manager
        self._set_status = status_setter
        self._aid = config.aid_prefix

        # 运行期状态
        self._senders: list[Any] = []
        self._transports: list[Any] = []
        self._lock = threading.RLock()
        self._add_param_widgets: dict[str, tuple[Any, Callable, Callable, str]] = {}
        self._update_param_widgets: dict[str, tuple[Any, Callable, Callable, str]] = {}
        self._basic_param_widgets: dict[str, tuple[Any, Callable, Callable, str, str, Any]] = {}

        # update 参数持久化：{target_key: {method_name: {param_name: value}}}
        # target_key 为 "__ALL__" 或 sender 索引字符串（如 "0", "1"）
        self._saved_update_params: dict[str, dict[str, dict[str, Any]]] = {}
        self._current_update_method: str = ""
        self._current_target: str = "__ALL__"

        # 反射信息
        self._src_info: SourceInfo = _parse_source(
            config.source_file, config.sender_cls_name, config.mgr_cls_name,
        )
        self._init_attrs = self._src_info.init_attrs
        self._module_constants = self._src_info.module_constants
        self._update_methods = _discover_update_methods(
            config.sender_cls,
            config=config,
            init_defaults=self._src_info.init_defaults,
        )
        self._add_params = _discover_add_params(config.mgr_cls)

        # 嵌套设备子面板（仅机巢 Tab）
        self._nested_panels: dict[str, "NestedDevicePanel"] = {}
        self._nested_tabs: QTabWidget | None = None
        self._nest_sub_tabs: QTabWidget | None = None

        # 基础参数折叠切换（保持为实例属性，避免被 GC 回收）
        self._basic_collapse: _CollapseToggle | None = None

        self._build_ui()
        self._refresh_update_params()
        self._refresh_device_list()

    # ── UI 构建 ──
    def _build_ui(self) -> None:
        self.setObjectName(f"{self._aid}PANEL")
        root = QVBoxLayout(self)

        if self._config.has_nested_devices:
            self._nest_sub_tabs = QTabWidget()
            self._nest_sub_tabs.setObjectName(f"{self._aid}SUB_TABS")

            main_view = QWidget()
            main_view.setObjectName(f"{self._aid}MAIN_VIEW")
            mv_layout = QVBoxLayout(main_view)
            mv_layout.setContentsMargins(0, 0, 0, 0)
            mv_layout.addWidget(self._build_basic_group())
            mv_layout.addWidget(self._build_add_group())
            mv_layout.addWidget(self._build_list_group(), stretch=1)
            mv_layout.addWidget(self._build_update_group())
            self._nest_sub_tabs.addTab(main_view, "机巢主视图")

            registry = NESTED_DEVICE_REGISTRY
            if registry:
                def _senders_getter():
                    with self._lock:
                        return list(self._senders)

                for dev_key, meta in registry.items():
                    panel = NestedDevicePanel(
                        meta=meta,
                        senders_getter=_senders_getter,
                        set_status=self._set_status,
                    )
                    panel.setObjectName(f"{self._aid}NESTED_{dev_key.upper()}")
                    self._nest_sub_tabs.addTab(panel, meta.label)
                    self._nested_panels[dev_key] = panel

            self._nested_tabs = self._nest_sub_tabs
            root.addWidget(self._nest_sub_tabs)
        else:
            root.addWidget(self._build_basic_group())
            root.addWidget(self._build_add_group())
            root.addWidget(self._build_list_group(), stretch=1)
            root.addWidget(self._build_update_group())

    def _build_basic_group(self) -> QGroupBox:
        grp = QGroupBox(
            f"基础参数 (模块级常量, AST 动态扫描自 "
            f"{self._config.source_file.name})"
        )
        grp.setObjectName(f"{self._aid}GRP_BASIC")
        outer = QVBoxLayout(grp)

        visible_items = [
            (cname, value, kind)
            for cname, (value, kind) in self._module_constants.items()
            if not cname.startswith("_")
        ]
        num_rows = len(visible_items)
        grid_rows = (num_rows + 1) // 2

        form_widget = QWidget()
        grid = QGridLayout(form_widget)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self._basic_param_widgets = {}
        self._basic_collapse = _CollapseToggle(container=form_widget)
        for idx, (cname, value, kind) in enumerate(visible_items):
            row = idx // 2
            col_offset = (idx % 2) * 2

            widget, getter, setter = self._make_input(
                f"BASIC_{cname.upper()}", value, kind
            )
            lbl = QLabel(f"{cname}  <{kind}>  =  module-level")
            lbl.setObjectName(f"{self._aid}LBL_BASIC_{cname.upper()}")
            grid.addWidget(lbl, row, col_offset)
            grid.addWidget(widget, row, col_offset + 1)
            self._basic_collapse.add_pair(lbl, widget)
            self._basic_param_widgets[cname] = (widget, getter, setter, kind, kind, value)

        if grid_rows > _MIN_VISIBLE_FORM_ROWS:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setObjectName(f"{self._aid}SCROLL_BASIC")
            scroll.setMinimumHeight(_MIN_VISIBLE_FORM_ROWS * _EST_FORM_ROW_HEIGHT)
            scroll.setWidget(form_widget)
            outer.addWidget(scroll, stretch=1)
        else:
            outer.addWidget(form_widget)

        self._basic_collapse.finalize(outer, f"{self._aid}BTN_COLLAPSE_BASIC")

        self._btn_basic_apply = QPushButton(
            f"应用基础参数 (写入 {self._config.source_file.stem} 模块)"
        )
        self._btn_basic_apply.setObjectName(f"{self._aid}BTN_BASIC_APPLY")
        self._btn_basic_apply.clicked.connect(self._on_basic_apply_clicked)
        outer.addWidget(self._btn_basic_apply)

        return grp

    def _build_add_group(self) -> QGroupBox:
        grp = QGroupBox(
            f"添加设备 (参数动态来自 {self._config.mgr_cls_name}.__init__)"
        )
        grp.setObjectName(f"{self._aid}GRP_ADD")
        outer = QVBoxLayout(grp)

        num_rows = len(self._add_params)
        grid_rows = (num_rows + 1) // 2

        form_widget = QWidget()
        grid = QGridLayout(form_widget)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self._add_param_widgets = {}
        for idx, (pname, default) in enumerate(self._add_params.items()):
            row = idx // 2
            col_offset = (idx % 2) * 2

            kind = _detect_kind(default, pname, config=self._config)
            default = self._config.param_defaults.get(pname, default)
            choices = self._config.param_choices.get(pname)
            widget, getter, setter = self._make_input(
                f"ADD_{pname.upper()}", default, kind, choices=choices
            )
            lbl = QLabel(f"{pname}  <{'choice' if choices else kind}>")
            lbl.setObjectName(f"{self._aid}LBL_ADD_{pname.upper()}")
            grid.addWidget(lbl, row, col_offset)
            grid.addWidget(widget, row, col_offset + 1)
            self._add_param_widgets[pname] = (widget, getter, setter, kind)

        if grid_rows > _MIN_VISIBLE_FORM_ROWS:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setObjectName(f"{self._aid}SCROLL_ADD")
            scroll.setMinimumHeight(_MIN_VISIBLE_FORM_ROWS * _EST_FORM_ROW_HEIGHT)
            scroll.setWidget(form_widget)
            outer.addWidget(scroll, stretch=1)
        else:
            outer.addWidget(form_widget)

        self._btn_add = QPushButton("添加")
        self._btn_add.setObjectName(f"{self._aid}BTN_ADD")
        self._btn_add.clicked.connect(self._on_add_clicked)
        outer.addWidget(self._btn_add)

        return grp

    def _build_list_group(self) -> QGroupBox:
        grp = QGroupBox(
            f"已添加设备 (点击『下线/上线』切换线程运行状态；行号对应下拉框索引)"
        )
        grp.setObjectName(f"{self._aid}GRP_LIST")
        layout = QHBoxLayout(grp)

        self._list_devices = QTableWidget(0, 5)
        self._list_devices.setObjectName(f"{self._aid}TABLE_DEVICES")
        self._list_devices.setHorizontalHeaderLabels(
            ["#", "IP:Port", "Code (Serial)", "状态", "操作"]
        )
        self._list_devices.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._list_devices.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list_devices.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._list_devices.verticalHeader().setVisible(False)
        h = self._list_devices.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self._list_devices, stretch=4)

        btn_col = QVBoxLayout()
        self._btn_remove = QPushButton("移除选中")
        self._btn_remove.setObjectName(f"{self._aid}BTN_REMOVE")
        self._btn_remove.clicked.connect(self._on_remove_clicked)

        self._btn_refresh = QPushButton("刷新列表")
        self._btn_refresh.setObjectName(f"{self._aid}BTN_REFRESH")
        self._btn_refresh.clicked.connect(self._refresh_device_list)

        self._btn_offline_all = QPushButton("全体下线")
        self._btn_offline_all.setObjectName(f"{self._aid}BTN_OFFLINE_ALL")
        self._btn_offline_all.clicked.connect(self._on_offline_all_clicked)

        self._btn_online_all = QPushButton("全体上线")
        self._btn_online_all.setObjectName(f"{self._aid}BTN_ONLINE_ALL")
        self._btn_online_all.clicked.connect(self._on_online_all_clicked)

        btn_col.addWidget(self._btn_remove)
        btn_col.addWidget(self._btn_refresh)
        btn_col.addWidget(self._btn_offline_all)
        btn_col.addWidget(self._btn_online_all)
        btn_col.addStretch()
        layout.addLayout(btn_col, stretch=1)

        self._status_timer = QTimer(self)
        self._status_timer.setObjectName(f"{self._aid}TIMER_STATUS")
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._refresh_status_only)
        self._status_timer.start()

        return grp

    def _build_update_group(self) -> QGroupBox:
        grp = QGroupBox(
            f"调整参数 (走 update_xxx 路径；动态来自 {self._config.sender_cls_name})"
        )
        grp.setObjectName(f"{self._aid}GRP_UPDATE")
        layout = QVBoxLayout(grp)

        sel = QHBoxLayout()
        sel.addWidget(QLabel("目标设备:"))
        self._combo_target = _LimitedCombo(20)
        self._combo_target.setObjectName(f"{self._aid}COMBO_TARGET")
        self._combo_target.addItem("【全体】", userData="__ALL__")
        sel.addWidget(self._combo_target)
        sel.addSpacing(24)
        sel.addWidget(QLabel("update 方法:"))
        self._combo_update = _LimitedCombo(20)
        self._combo_update.setObjectName(f"{self._aid}COMBO_UPDATE")
        for m in self._update_methods:
            self._combo_update.addItem(m)
        self._combo_update.currentTextChanged.connect(self._refresh_update_params)
        self._combo_target.currentTextChanged.connect(self._on_target_changed)
        sel.addWidget(self._combo_update)
        layout.addLayout(sel)

        self._params_scroll = QScrollArea()
        self._params_scroll.setWidgetResizable(True)
        self._params_scroll.setObjectName(f"{self._aid}SCROLL_PARAMS")
        self._params_scroll.setMinimumHeight(_MIN_VISIBLE_FORM_ROWS * _EST_FORM_ROW_HEIGHT)
        self._params_container = QWidget()
        self._params_container.setObjectName(f"{self._aid}PARAMS_CONTAINER")
        self._params_form = QFormLayout(self._params_container)
        self._params_scroll.setWidget(self._params_container)
        layout.addWidget(self._params_scroll, stretch=1)

        self._btn_apply = QPushButton("应用 update")
        self._btn_apply.setObjectName(f"{self._aid}BTN_APPLY")
        self._btn_apply.clicked.connect(self._on_apply_clicked)
        layout.addWidget(self._btn_apply)

        return grp

    def _make_input(
        self, slot_id: str, default: Any, kind: str,
        choices: dict[str, str] | None = None,
    ) -> tuple[Any, Callable, Callable]:
        return _make_input_widget(self._aid, slot_id, default, kind, choices)

    # ── 动态参数渲染 ──
    def _save_current_form_values(self, method: str | None = None, target: str | None = None) -> None:
        """把当前表单控件的值写入持久化字典。"""
        if method is None:
            method = self._combo_update.currentText()
        if target is None:
            target = self._combo_target.currentData()
        if not method or not self._update_param_widgets:
            return
        if target is None:
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
        """读取已保存的参数值；无保存记录时返回 None。"""
        return self._saved_update_params.get(target_key, {}).get(method_name)

    # ── 动态 choices（ip_str / mode 等下拉框选项）──
    def _get_dynamic_choices(
        self, pname: str, method: str,
    ) -> dict[str, str] | None:
        """返回某个参数的可选值 dict（label -> value），未匹配返回 None。"""
        if pname == "ip_str":
            return self._get_airplane_ip_choices()
        if pname == "mode" and method == "update_airplane_mode":
            return {"机巢内 (internal)": "internal", "机巢外 (external)": "external"}
        if pname == "target_nest_index" and method == "update_airplane_mode":
            return self._get_nest_index_choices()
        # 其他已知 choice 映射（静态）
        return self._config.param_choices.get(pname)

    def _get_airplane_ip_choices(self) -> dict[str, str]:
        """从当前选中的 sender 收集所有飞机 IP 作为下拉选项。"""
        choices: dict[str, str] = {}
        target = self._current_target
        with self._lock:
            if target == "__ALL__":
                for sender in self._senders:
                    airplanes = getattr(sender, "_airplanes", None)
                    if isinstance(airplanes, dict):
                        for ip in airplanes:
                            if ip not in choices:
                                choices[ip] = ip
            else:
                try:
                    idx = int(target)
                    sender = self._senders[idx]
                except (ValueError, IndexError):
                    return choices
                airplanes = getattr(sender, "_airplanes", None)
                if isinstance(airplanes, dict):
                    for ip in airplanes:
                        choices[ip] = ip
        return choices

    def _get_nest_index_choices(self) -> dict[str, str]:
        """返回可用机巢索引列表（用于跨巢入巢）。"""
        choices: dict[str, str] = {}
        with self._lock:
            for i, _ in enumerate(self._senders):
                label = f"巢#{i}"
                choices[label] = str(i)
        return choices

    @Slot(str)
    def _refresh_update_params(self, _method: str | None = None) -> None:
        # 保存当前表单值（使用旧 method + 旧 target，避免信号触发时串位）
        if self._current_update_method and self._update_param_widgets:
            self._save_current_form_values(
                method=self._current_update_method,
                target=self._current_target,
            )

        while self._params_form.count():
            item = self._params_form.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._update_param_widgets = {}

        method = self._combo_update.currentText()
        self._current_update_method = method
        self._current_target = self._combo_target.currentData() or "__ALL__"
        if not method or method not in self._update_methods:
            return

        target = self._current_target
        saved = self._load_saved_values(target, method) if target else None

        params = self._update_methods[method]

        # update_position: GUI 表单中 lon 在前 lat 在后（原始签名是 lat 在前）
        if method == "update_position":
            _lon_lat_order = ["cur_lon", "cur_lat", "tar_lon", "tar_lat",
                              "cur_alt", "tar_alt", "fix_type",
                              "rtk_radio_850m", "rtk_radio_2g4"]
            params = {k: params[k] for k in _lon_lat_order if k in params}
        for pname, default in params.items():
            kind = _detect_kind(
                default, pname,
                config=self._config,
                method_name=method,
                init_attrs=self._init_attrs,
            )
            # 优先使用已保存的值，其次用默认值
            value = saved.get(pname) if (saved and pname in saved) else default
            choices = self._get_dynamic_choices(pname, method)
            slot_id = f"PARAM_{method.upper()}_{pname.upper()}"
            widget, getter, setter = self._make_input(slot_id, value, kind, choices=choices)
            kind_label = "choice" if choices else kind
            label = QLabel(f"{pname}  <{kind_label}>")
            label.setObjectName(f"{self._aid}LBL_{slot_id}")
            self._params_form.addRow(label, widget)
            self._update_param_widgets[pname] = (widget, getter, setter, kind)

    @Slot(str)
    def _on_target_changed(self, _text: str) -> None:
        """目标设备切换时刷新参数面板（保存旧、加载新）。"""
        self._refresh_update_params()

    # ── 槽函数 ──
    @Slot()
    def _on_basic_apply_clicked(self) -> None:
        # 包内模块（fake_cloud.ad_proxy）用 SimConfig.module_name 的 dotted 路径；
        # 顶层模块（假项目目录下的 fake_airplane.py 等）回退 source_file.stem。
        mod_name = self._config.module_name or self._config.source_file.stem
        import importlib
        mod = importlib.import_module(mod_name)
        applied: list[str] = []
        for cname, (_w, getter, _s, kind, _orig_kind, orig_value) in self._basic_param_widgets.items():
            try:
                raw = getter()
                new_val = _coerce(raw, kind) if isinstance(raw, str) else raw
            except Exception as e:
                QMessageBox.warning(self, "参数错误", f"{cname} 解析失败: {e}")
                return
            setattr(mod, cname, new_val)
            applied.append(f"{cname}={new_val!r}")
        self._set_status(
            "已应用基础参数: " + ", ".join(applied) if applied else "未改动"
        )

    @Slot()
    def _on_add_clicked(self) -> None:
        kwargs: dict[str, Any] = {}
        for pname, (widget, getter, _setter, kind) in self._add_param_widgets.items():
            try:
                raw = getter()
                kwargs[pname] = _coerce(raw, kind) if isinstance(raw, str) else raw
            except Exception as e:
                QMessageBox.warning(self, "参数错误", f"参数 {pname} 解析失败: {e}")
                return
        kwargs["log_manager"] = self._log_manager

        try:
            with self._lock:
                mgr = self._config.mgr_cls(**kwargs)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "添加失败", str(e))
            return

        new_senders = getattr(mgr, self._config.mgr_senders_attr)
        new_transports = getattr(mgr, self._config.mgr_transports_attr)
        with self._lock:
            self._senders.extend(new_senders)
            self._transports.extend(new_transports)

        # 对新创建的 transport 打补丁，拦截 recvfrom → UDP 监控
        injector = getattr(self, "_message_injector", None)
        if injector:
            for t in new_transports:
                self._patch_transport_socket(t, injector)
            # 对新 sender 也传播注入回调（外模式飞机的独立 socket）
            for s in new_senders:
                _setter = getattr(s, 'set_msg_injector', None)
                if _setter is not None:
                    try:
                        _setter(injector)
                    except Exception:
                        pass

        self._refresh_device_list()
        self._set_status(
            f"已添加 {len(new_senders)} 个（本批），共 {len(self._senders)} 个"
        )

    @Slot()
    def _on_remove_clicked(self) -> None:
        row = self._list_devices.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在列表中选中要移除的设备")
            return
        with self._lock:
            try:
                sender = self._senders[row]
            except IndexError:
                return
            try:
                transport = self._transports[row]
            except IndexError:
                transport = None
        try:
            self._stop_sender_thread(sender)
        except Exception as e:
            print(f"[GUI] 停止设备异常: {e}")
        if transport is not None:
            try:
                transport.close()
            except Exception as e:
                print(f"[GUI] 关闭设备 UDP 异常: {e}")
        with self._lock:
            try:
                self._senders.pop(row)
                if transport is not None:
                    self._transports.pop(row)
            except IndexError:
                pass
        self._refresh_device_list()
        self._set_status(f"已移除 #{row}，剩余 {len(self._senders)} 个")

    @Slot()
    def _on_toggle_online_clicked(self, row: int) -> None:
        with self._lock:
            try:
                sender = self._senders[row]
            except IndexError:
                return
        online = self._is_sender_online(sender)
        if online:
            self._stop_sender_thread(sender)
            self._set_status(f"#{row} 已下线")
        else:
            self._start_sender_thread(sender)
            self._set_status(f"#{row} 已上线")
        self._refresh_row_status(row)

    @Slot()
    def _on_offline_all_clicked(self) -> None:
        with self._lock:
            targets = list(self._senders)
        for s in targets:
            if self._is_sender_online(s):
                self._stop_sender_thread(s)
        self._refresh_device_list()
        self._set_status(f"全体下线 ({len(targets)} 个)")

    @Slot()
    def _on_online_all_clicked(self) -> None:
        with self._lock:
            targets = list(self._senders)
        for s in targets:
            if not self._is_sender_online(s):
                self._start_sender_thread(s)
        self._refresh_device_list()
        self._set_status(f"全体上线 ({len(targets)} 个)")

    # ── 线程 / 在线状态工具 ──
    def _is_sender_online(self, sender) -> bool:
        """判断 sender 是否在线。

        以线程的实际存活状态为准（is_alive），而非 running flag。
        running flag 可被提前置为 False，但线程可能尚未退出，
        如果仅以 flag 判断会错误显示「离线」而实际仍在发送数据。
        """
        main_thr = getattr(sender, "thread", None)
        if main_thr is None:
            return False
        # 线程已死 → 离线（不论 running flag 的值）
        if not main_thr.is_alive():
            return False
        # 线程存活 → 在线（即使 running=False，线程还在跑）
        periodic_thr = getattr(sender, "periodic_thread", None)
        if periodic_thr is not None and not periodic_thr.is_alive():
            return False
        return True

    def _stop_sender_thread(self, sender) -> None:
        """停止 sender 的后台线程，确保线程完全退出后才返回。

        设置 running=False → 等待线程退出（join 超时 5s，
        足以覆盖 recvfrom 1s 超时 + enroll 5s 超时）。
        超时未退出则记录警告，但 daemon 线程不会阻塞进程退出。
        """
        sender.running = False
        if hasattr(sender, "periodic_running"):
            sender.periodic_running = False

        for thr_name in ("thread", "periodic_thread"):
            thr = getattr(sender, thr_name, None)
            if thr is None or not thr.is_alive():
                continue
            thr.join(timeout=5)
            if thr.is_alive():
                print(
                    f"[GUI] 警告: {thr_name} 线程在 5s 后仍未退出 "
                    f"(sender code={getattr(sender, 'code', '?')})"
                )

    def _start_sender_thread(self, sender) -> None:
        sender.running = True
        sender.thread = threading.Thread(target=sender._run, daemon=True)
        sender.thread.start()

        periodic_loop = getattr(sender, "_periodic_send_loop", None)
        if periodic_loop is not None and hasattr(sender, "periodic_running"):
            sender.periodic_running = True
            sender.periodic_thread = threading.Thread(
                target=periodic_loop, daemon=True
            )
            sender.periodic_thread.start()

    @Slot()
    def _on_apply_clicked(self) -> None:
        method = self._combo_update.currentText()
        if not method or method not in self._update_methods:
            return
        if not hasattr(self._config.sender_cls, method):
            return

        kwargs: dict[str, Any] = {}
        for pname, (_w, getter, _s, kind) in self._update_param_widgets.items():
            try:
                raw = getter()
                kwargs[pname] = _coerce(raw, kind) if isinstance(raw, str) else raw
            except Exception as e:
                QMessageBox.warning(
                    self, "参数错误", f"参数 {pname} 解析失败: {e}"
                )
                return

        target = self._combo_target.currentData()
        with self._lock:
            if target == "__ALL__":
                targets = list(self._senders)
                # 覆盖所有 sender 的该 update 全部字段
                for i in range(len(self._senders)):
                    idx_str = str(i)
                    self._saved_update_params.setdefault(idx_str, {})[method] = dict(kwargs)
            else:
                try:
                    idx = int(target)
                except (TypeError, ValueError):
                    QMessageBox.warning(self, "错误", "目标设备无效")
                    return
                if not (0 <= idx < len(self._senders)):
                    QMessageBox.warning(self, "错误", "目标设备索引越界")
                    return
                targets = [self._senders[idx]]

        # 持久化当前表单值到对应 target
        self._saved_update_params.setdefault(target, {})[method] = dict(kwargs)

        failed = 0
        for t in targets:
            try:
                getattr(t, method)(**kwargs)
            except Exception as e:
                failed += 1
                print(f"[GUI] 调用 {method} 失败: {e}")

        self._set_status(
            f"已对 {len(targets) - failed}/{len(targets)} 个执行 {method}"
        )

    # ── 列表刷新 ──
    def _refresh_device_list(self) -> None:
        self._list_devices.setRowCount(0)
        with self._lock:
            snap = list(zip(range(len(self._senders)), self._senders, self._transports))
        for i, sender, transport in snap:
            self._list_devices.insertRow(i)
            self._populate_row(i, sender, transport)
        self._refresh_target_combo()
        self._refresh_nested_panels()

    def _refresh_target_combo(self) -> None:
        self._combo_target.blockSignals(True)
        try:
            self._combo_target.clear()
            self._combo_target.addItem("【全体】", userData="__ALL__")
            for i, t in enumerate(self._transports):
                local_ip = getattr(t, "local_ip", "?")
                local_port = getattr(t, "local_port", "?")
                label = f"#{i}  {local_ip}:{local_port}"
                self._combo_target.addItem(label, userData=str(i))
        finally:
            self._combo_target.blockSignals(False)

    def _populate_row(self, row: int, sender, transport) -> None:
        item_idx = QTableWidgetItem(str(row))
        item_idx.setTextAlignment(Qt.AlignCenter)
        item_idx.setFlags(item_idx.flags() & ~Qt.ItemIsEditable)
        self._list_devices.setItem(row, 0, item_idx)

        local_ip = getattr(transport, "local_ip", "?")
        local_port = getattr(transport, "local_port", "?")
        item_addr = QTableWidgetItem(f"{local_ip}:{local_port}")
        item_addr.setFlags(item_addr.flags() & ~Qt.ItemIsEditable)
        self._list_devices.setItem(row, 1, item_addr)

        code = getattr(sender, "code", "?")
        serial = getattr(sender, "serial", "?")
        item_code = QTableWidgetItem(f"{code}  ({serial})")
        item_code.setToolTip(f"code={code}\nserial={serial}")
        item_code.setFlags(item_code.flags() & ~Qt.ItemIsEditable)
        self._list_devices.setItem(row, 2, item_code)

        self._refresh_row_status(row, sender=sender)
        self._set_action_button(row, sender)

    def _refresh_row_status(self, row: int, sender=None) -> None:
        with self._lock:
            try:
                s = sender if sender is not None else self._senders[row]
            except IndexError:
                return
        online = self._is_sender_online(s)
        text = "● 在线" if online else "○ 离线"
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        if online:
            item.setForeground(QColor("#1f9d55"))
        else:
            item.setForeground(QColor("#9aa0a6"))
        self._list_devices.setItem(row, 3, item)

        btn = self._list_devices.cellWidget(row, 4)
        if isinstance(btn, QPushButton):
            btn.setText("下线" if online else "上线")

    def _set_action_button(self, row: int, sender) -> None:
        online = self._is_sender_online(sender)
        btn = QPushButton("下线" if online else "上线")
        btn.setObjectName(f"{self._aid}BTN_TOGGLE_{row}")
        btn.clicked.connect(lambda _checked=False, r=row: self._on_toggle_online_clicked(r))
        self._list_devices.setCellWidget(row, 4, btn)

    def _refresh_status_only(self) -> None:
        with self._lock:
            count = len(self._senders)
        for row in range(count):
            self._refresh_row_status(row)

    def _refresh_nested_panels(self) -> None:
        for panel in self._nested_panels.values():
            panel.refresh_targets()

    # ── 公开 API：收集假节点 IP ──
    def get_fake_node_ips(self) -> list[str]:
        """返回当前所有 transport 的 local_ip 列表。"""
        ips: list[str] = []
        with self._lock:
            for t in self._transports:
                ip = getattr(t, "local_ip", None)
                if ip and ip != "?":
                    ips.append(str(ip))
        return ips

    def get_senders(self) -> list[Any]:
        """返回当前所有 sender 实例列表。"""
        with self._lock:
            return list(self._senders)

    def set_message_injector(self, callback: Callable | None) -> None:
        """设置消息注入回调，用于将假节点收到的原始数据转发到 UDP 监控。

        callback 签名为:
            (data: bytes, gcs_ip: str, gcs_port: int, dst_ip: str, dst_port: int) -> None

        其中 gcs_ip/gcs_port 取自 transport 的 ground_station_ip/port 或 dgcs_ip，
        dst_ip/dst_port 取自 transport 的 local_ip/port。
        """
        self._message_injector = callback
        # 对已有 transports 立即打补丁
        with self._lock:
            for t in self._transports:
                self._patch_transport_socket(t, callback)
        # 对外模式飞机的 sender 传播注入回调（飞机离巢后的独立 socket）
        for s in self._senders:
            _setter = getattr(s, 'set_msg_injector', None)
            if _setter is not None:
                try:
                    _setter(callback)
                except Exception:
                    pass

    def _patch_transport_socket(self, transport, callback: Callable | None) -> None:
        """替换 transport.sock 为 _SocketInterceptor，拦截 recvfrom。

        消息来源固定为 ground_station_ip:ground_station_port：
          - 假飞机:   172.16.200.1:14550
          - 假机巢:   172.16.200.1:14650
        目标为假节点自身的 local_ip:local_port。

        假电台**不在此处安装拦截器**：其消息注入统一由
        ``_FakeRadioSender.set_msg_injector`` 自包装完成（处理 socket 延迟创建，
        见 fake_radio.py），避免与 _SocketInterceptor 双重拦截。
        """
        # 电台（_FakeRadioSender 含 _radio）走 set_msg_injector 自包装
        if _FakeRadioSender is not None and isinstance(transport, _FakeRadioSender):
            return

        # 尝试获取真实的 socket 对象（假飞机/假机巢的 sock 直接挂在 transport 上）
        real_sock = getattr(transport, "sock", None)
        if real_sock is None:
            return

        # 来源 IP:Port —— 假飞机/机巢用 ground_station_ip:ground_station_port
        gcs_ip = getattr(transport, "ground_station_ip", None) or \
                 getattr(transport, "dgcs_ip", "172.16.200.1")
        gcs_port = getattr(transport, "ground_station_port", None) or \
                   getattr(transport, "port", 0)
        dst_ip = getattr(transport, "local_ip", "0.0.0.0")
        dst_port = getattr(transport, "local_port", None) or \
                   getattr(transport, "port", 0)

        def _on_recv(data: bytes, sender_addr: tuple) -> None:
            callback(data, gcs_ip, gcs_port, dst_ip, dst_port)

        # 避免重复包装
        if isinstance(real_sock, _SocketInterceptor):
            real_sock._on_recv = _on_recv if callback else None
            return

        interceptor = _SocketInterceptor(real_sock, on_recv=_on_recv if callback else None)
        transport.sock = interceptor

    # ── 退出清理 ──
    def shutdown(self) -> None:
        with self._lock:
            for s in self._senders:
                try:
                    s.stop()
                except Exception:
                    pass
            for t in self._transports:
                try:
                    t.close()
                except Exception:
                    pass

