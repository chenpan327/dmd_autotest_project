"""共享 GUI 控件 — _MultiSelectButton / _FixedHeightListView / _LimitedCombo / _CollapseToggle

所有自定义控件集中于此模块，避免跨模块的私有类导入。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QSize, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QWidget,
    QWidgetAction,
)


# ═══════════════════════════════════════════════════════════════
# _MultiSelectButton — 多选/单选下拉按钮
# ═══════════════════════════════════════════════════════════════
class _MultiSelectButton(QPushButton):
    """带多选/单选弹出菜单的按钮。

    single_select=True 时：单选模式（隐藏全选/清除按钮，勾选新项自动取消其他项，
    按钮文字显示选中项文本）。默认 False（多选模式，兼容现有 MsgID/SrcIP 等过滤）。
    """

    selection_changed = Signal()

    def __init__(self, label: str, parent: QWidget | None = None,
                 single_select: bool = False) -> None:
        super().__init__(label, parent)
        self._options: dict[str, str] = {}       # key → display_text
        self._selected: set[str] = set()
        self._base_label = label
        self._single_select = single_select
        self.clicked.connect(self._show_popup)
        self._update_text()

    # ── 公开 API ──
    def set_options(self, options: dict[str, str]) -> None:
        """设置可选列表。options: {key: display_text}"""
        self._options = dict(options)
        self._selected = self._selected & set(options.keys())
        self._update_text()

    def selected_keys(self) -> set[str]:
        return set(self._selected)

    def set_selected_keys(self, keys: set[str]) -> None:
        self._selected = set(keys) & set(self._options.keys())
        self._update_text()

    def clear_selection(self) -> None:
        self._selected.clear()
        self._update_text()

    # ── 单选模式便捷 API ──
    def selected_key(self) -> str | None:
        """单选模式下返回唯一选中 key，无选中时返回 None。"""
        if self._selected:
            return next(iter(self._selected))
        return None

    def set_selected_key(self, key: str) -> None:
        """单选模式下设置唯一选中项。"""
        if key in self._options:
            self._selected = {key}
        else:
            self._selected.clear()
        self._update_text()

    # ── 内部 ──
    def _update_text(self) -> None:
        if self._single_select:
            # 单选模式：仅显示选中项的文本，未选中时显示 base_label
            if self._selected:
                key = next(iter(self._selected))
                display = self._options.get(key, key)
                self.setText(display)
            else:
                self.setText(self._base_label)
        else:
            # 多选模式：显示选中数量
            if not self._selected or len(self._selected) == len(self._options):
                self.setText(self._base_label)
            else:
                self.setText(f"{self._base_label} ({len(self._selected)})")

    def _show_popup(self) -> None:
        menu = QMenu(self)
        menu.setMinimumWidth(180)

        # ── 快捷按钮行（仅多选模式显示）──
        if not self._single_select:
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(6, 4, 6, 2)
            btn_layout.setSpacing(4)

            all_btn = QPushButton("全选")
            all_btn.setFixedHeight(22)
            all_btn.clicked.connect(lambda: self._do_select_all(menu))
            btn_layout.addWidget(all_btn)

            none_btn = QPushButton("清除")
            none_btn.setFixedHeight(22)
            none_btn.clicked.connect(lambda: self._do_clear(menu))
            btn_layout.addWidget(none_btn)

            btn_action = QWidgetAction(menu)
            btn_action.setDefaultWidget(btn_widget)
            menu.addAction(btn_action)

            menu.addSeparator()

        # ── 列表 ──
        list_widget = QListWidget()
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        list_widget.setMaximumHeight(260)

        # 先在信号阻断下填充初始状态，避免初始化时触发 itemChanged
        list_widget.blockSignals(True)
        for key, text in self._options.items():
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if key in self._selected
                else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, key)
            list_widget.addItem(item)
        list_widget.blockSignals(False)

        list_widget.itemChanged.connect(self._on_item_changed)
        list_action = QWidgetAction(menu)
        list_action.setDefaultWidget(list_widget)
        menu.addAction(list_action)

        # 弹出位置：按钮正下方
        pos = self.mapToGlobal(QPoint(0, self.height()))
        menu.popup(pos)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self._selected.add(key)
            # 单选模式：取消其他项的选中
            if self._single_select:
                self._selected = {key}
                # 找到 sender list_widget 并同步其他项的勾选状态
                list_widget = item.listWidget()
                if list_widget:
                    list_widget.blockSignals(True)
                    for i in range(list_widget.count()):
                        other = list_widget.item(i)
                        if other is not item and other.checkState() == Qt.CheckState.Checked:
                            other.setCheckState(Qt.CheckState.Unchecked)
                    list_widget.blockSignals(False)
        else:
            self._selected.discard(key)
        self._update_text()
        self.selection_changed.emit()

    def _do_select_all(self, menu: QMenu) -> None:
        self._selected = set(self._options.keys())
        menu.close()
        self._update_text()
        self.selection_changed.emit()

    def _do_clear(self, menu: QMenu) -> None:
        self._selected.clear()
        menu.close()
        self._update_text()
        self.selection_changed.emit()


# ═══════════════════════════════════════════════════════════════
# _FixedHeightListView / _LimitedCombo — 下拉弹窗行数 + 宽度受限
# ═══════════════════════════════════════════════════════════════
class _FixedHeightListView(QListView):
    """QListView 子类：sizeHint() 高度硬截断为 max_height。

    Qt 内部通过 view.sizeHint() 决定弹窗高度，在此处截断是最底层的控制，
    不依赖 setMaxVisibleItems（可能被 clear+addItem 重置）或 stylesheet（宽度 bug）。
    """

    def __init__(self, max_height: int = 440, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_height = max_height
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        if hint.height() > self._max_height:
            hint.setHeight(self._max_height)
        return hint

    def minimumSizeHint(self) -> QSize:
        """双保险：minimumSizeHint 也受 max_height 约束，防止 Qt 在某些布局下绕过 sizeHint。"""
        hint = super().minimumSizeHint()
        if hint.height() > self._max_height:
            hint.setHeight(self._max_height)
        return hint


class _LimitedCombo(QComboBox):
    """QComboBox 子类：使用 _FixedHeightListView 替代默认 view，硬限制弹窗高度。

    宽度：showPopup() 时锁定 view.setMinimumWidth / setMaximumWidth = self.width()，
    防止因内容长度导致弹窗宽度撑满屏幕（Qt 已知问题）。
    """

    _ROW_HEIGHT = 22  # 100% DPI 默认值，showPopup 时动态校准

    def __init__(self, max_visible: int = 20, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_visible = max_visible
        # Qt 内置限高：maxVisibleItems 不会被 clear()+addItem() 重置
        self.setMaxVisibleItems(max_visible)
        # 自定义 view 双保险：sizeHint() + minimumSizeHint() 硬截断高度
        self.setView(_FixedHeightListView(max_visible * self._ROW_HEIGHT))

    def showPopup(self) -> None:
        view = self.view()
        if view is not None:
            combo_w = self.width()
            view.setMinimumWidth(combo_w)
            view.setMaximumWidth(combo_w)
            # DPI 感知行高：根据首项实际渲染高度动态校准 max_height
            if self.count() > 0:
                actual_row_h = view.sizeHintForRow(0)
                if actual_row_h > 0 and actual_row_h != self._ROW_HEIGHT:
                    view._max_height = self._max_visible * actual_row_h
        super().showPopup()


# ═══════════════════════════════════════════════════════════════
# _CollapseToggle — 参数折叠/展开通用组件
# ═══════════════════════════════════════════════════════════════
_MAX_VISIBLE_ITEMS = 5


class _CollapseToggle:
    """管理一组 (标签, 输入控件) 的折叠/展开。

    默认显示前 ``_MAX_VISIBLE_ITEMS`` 个，其余隐藏；
    点击按钮切换全部显示 / 只显示前 N 个。
    """

    def __init__(self, max_visible: int = _MAX_VISIBLE_ITEMS,
                 container: QWidget | None = None) -> None:
        self._max = max_visible
        self._pairs: list[tuple[QWidget, QWidget]] = []
        self._btn: QPushButton | None = None
        self._expanded = False
        self._container = container  # 需要刷新布局的容器 widget

    def add_pair(self, label: QWidget, input_widget: QWidget) -> None:
        self._pairs.append((label, input_widget))

    def finalize(self, parent_layout, object_name: str) -> None:
        """如果条目数超过上限，隐藏多余条目并在 *parent_layout* 中插入切换按钮。

        按钮会插入在 layout 最后一个元素之前（即 apply / add 按钮之前）。
        支持重复调用——会先移除旧按钮再重建。
        """
        # 先移除旧按钮
        if self._btn is not None:
            parent_layout.removeWidget(self._btn)
            self._btn.deleteLater()
            self._btn = None
            self._expanded = False

        if len(self._pairs) <= self._max:
            return
        self._hide_excess()
        remaining = len(self._pairs) - self._max
        self._btn = QPushButton(f"▼ 展开更多 ({remaining} 个参数)")
        self._btn.setObjectName(object_name)
        self._btn.clicked.connect(self._toggle)
        # 插入到最后一个元素之前（即 apply / add 按钮之前）
        insert_pos = max(0, parent_layout.count() - 1)
        parent_layout.insertWidget(insert_pos, self._btn)

    def _hide_excess(self) -> None:
        for lbl, w in self._pairs[self._max:]:
            lbl.hide()
            w.hide()

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        for lbl, w in self._pairs[self._max:]:
            lbl.setVisible(self._expanded)
            w.setVisible(self._expanded)
        remaining = len(self._pairs) - self._max
        if self._btn is not None:
            self._btn.setText(
                "▲ 收起参数" if self._expanded
                else f"▼ 展开更多 ({remaining} 个参数)"
            )
        # 强制刷新容器布局（否则展开后可能不显示）
        if self._container is not None:
            self._container.updateGeometry()
            lay = self._container.layout()
            if lay is not None:
                lay.invalidate()
                lay.activate()
            # 如果容器在 QScrollArea 中，强制刷新滚动区域
            p = self._container.parent()
            if isinstance(p, QScrollArea):
                p.updateGeometry()

    def reset(self) -> None:
        """清空已记录的控件对（用于动态重建参数的场景）。

        注意：不清理 _btn —— finalize() 负责移除旧按钮。
        """
        self._pairs.clear()
        self._expanded = False
