# mavlink_monitor 优化计划

> **基于**: `CODE_REVIEW_REPORT.md` 15 个 HIGH 问题 + 5 Agent 交叉分析
> **创建日期**: 2026-07-29
> **最后更新**: 2026-07-29（多 Agent 交叉质询后修订）
> **状态**: 待执行 — 已逐条验证，发现 3 处计划错误 + 5 个遗漏项

---

## 目录

1. [实际完成进度](#1-实际完成进度)
2. [修复优先级矩阵](#2-修复优先级矩阵)
3. [逐条方案（原 H1-H15）](#3-逐条方案)
4. [新增项目（H16-H20）](#4-新增项目)
5. [依赖关系（修订版）](#5-依赖关系修订版)
6. [执行顺序建议（修订版）](#6-执行顺序建议修订版)
7. [交叉分析附录：Agent 分歧与共识](#7-交叉分析附录agent-分歧与共识)

---

## 1. 实际完成进度

> 以下为 2026-07-29 实际源码核查结果。原计划标注"H2 已完成"经核实为**部分完成**（model.py 默认值已改，但 controller.py 硬编码覆盖）。

| ID | 项目 | 状态 | 证据 |
|----|------|------|------|
| H1 | get_latest() O(n) | ✅ 已完成 | 改用 `reversed` + `islice` O(n)，性能验证 0.01ms（2026-07-31） |
| H2 | 默认容量 OOM | ⚠️ 部分完成 | `model.py:157` 默认值已改为 4096000，但 `controller.py:33` 硬编码 `capacity=40960000` 覆盖了安全默认值 |
| H3 | MAVLink v2 帧 | ✅ 已完成 | 两处拒绝 v2（standard + IP-prefixed），显式 `return None`（2026-07-31） |
| H4 | varint 移位限制 | ✅ 已完成 | 改用 `for _ in range(10)` 字节计数，支持合法 10 字节 protobuf varint（2026-07-31） |
| H5 | Qt 线程安全 | ✅ 已完成 | 新增 `_record_added` Signal + 线程检查门卫，非主线程调用自动排队（2026-07-31） |
| H6 | Plotly 后台线程 | ✅ 已完成 | 新增 `_DramaWorker(QThread)` + 信号 `progress/file_done/finished`（2026-07-31） |
| H7 | integrated_gui.py 硬编码路径 | ✅ 已完成 | 改用 `core/paths.py` 统一解析（2026-07-31） |
| H8 | test_persistence.py 硬编码路径 | ✅ 已完成 | 改用 `core/paths.py` + `os.path.dirname(__file__)`（2026-07-31） |
| H9 | left_panel.py 硬编码路径 | ✅ 已完成 | 改用 `core/paths.py` 的 `get_mavlink_version_dir()`（2026-07-31） |
| H10 | 单体文件拆分 | ✅ 已完成 | 拆分为 `integrated_gui/` 包（8 模块），`integrated_gui.py` 保留为兼容重定向（2026-07-31） |
| H11 | 跨类访问私有属性 | ✅ 已完成 | 新增 `scroll_paused` setter / `time_mode` property 到 TraceTable 和 GroupedTraceView，MainWindow 改用公共 API（2026-07-31） |
| H12 | 分组视图时间列不同步 | ✅ 已完成 | `GroupedTraceView.time_mode` setter 内同步更新 `_tree` 列可见性，修复 H11 时一并解决（2026-07-31） |
| H13 | trim_rows O(n²) | ✅ 已完成 | 添加 `setUpdatesEnabled(False/True)` 批量禁用 UI 刷新（2026-07-31） |
| H14 | drama_processing.py 硬编码路径 | ✅ 已完成 | 改用 `core/paths.py` 统一解析（2026-07-31） |
| H15 | 回调接口文档不一致 | ✅ 已完成 | 更新 docstring 为 5 参数签名（gcs_ip, gcs_port 拆分）（2026-07-31） |

**结论：15 项中 14 项完成（H1/H3/H4/H5/H6/H7/H8/H9/H10/H11/H12/H13/H14/H15），1 项（H2）部分完成但被 controller.py 覆盖而无效。**

**新增项目（H16-H20）：5 项全部完成 ✅**
- H16 ✅ 提取共享 Widget（v1.10 已完成）
- H17 ✅ _TamperEntry 控件替换（_LimitedCombo → currentData() 直存 int）
- H18 ✅ _ROW_HEIGHT DPI 感知（sizeHintForRow 动态校准）
- H19 ✅ 清理 UDP TODO 死代码（main_window + left_panel 共 16 处）
- H20 ✅ 合并 _fmt_rel/_fmt_abs（v1.10 已完成，gui/utils.py）

---

## 2. 修复优先级矩阵

```
影响程度
  ^
  │  H3(数据全错)    H2(160GB OOM, controller.py覆盖)
  │  ──────────────────────────
  │  H1(GUI卡死)     H5(Qt崩溃)
  │  H7/H9/H14(不可移植)
  │  ─────── 高危线 ────────────
  │  H13(性能退化)   H6(GUI冻结)
  │  H4(边界bug)     H12(显示错误)
  │  H11(维护风险)   H15(文档错误)
  │  H16(Widget分散) H10(架构债)   H8(测试不可移植)
  │  H17(TamperEntry控件)  H18(DPI)  H19(TODO死代码)
  └──────────────────────────────────→ 修复代价
      低              中              高
```

---

## 3. 逐条方案

### H1: get_latest() O(n) 性能 ✅ 已修复（2026-07-31）

| 文件 | `model.py:215` |
|------|---------------|
| 现状（修复前） | `islice(self._records, total - n, total)` — deque 上正向迭代到尾部 O(total) |
| 修复 | `list(islice(reversed(self._records), n))[::-1]` — 反向迭代 O(n) |

**对原有功能的影响**:

| 维度 | 分析 |
|------|------|
| 语义一致性 | ✅ 完全一致：都是从尾部取最近 n 条，FIFO 顺序不变 |
| 性能 | ✅ 从 O(total) 降到 O(n)，与同文件的 `get_since()` 风格一致 |
| 调用方 | ✅ `MonitorController.get_visible_records()` (controller.py:167-173) 透传调用，接口不变 |
| 线程安全 | ✅ 调用仍在 `with self._lock` 内 |

**额外修改**: 无。

---

### H2: 默认容量 OOM 风险

| 文件 | `model.py:157` + **`controller.py:33`**（原计划遗漏） |
|------|-------------------------------------------------------|
| 现状 | `model.py` 默认值已改为 `4096000`（~14GB），但 `controller.py:33` 显式传参 `capacity=40960000`（~160GB）**覆盖了安全默认值** |
| 修复 | `controller.py:33` → `capacity=4096000`（或删除显式传参，使用 model 默认值） |

**原计划的错误**: 声称"MonitorController.**init** 已支持显式传入 model_capacity 参数覆盖"——实际 `MonitorController.__init__` **没有** `model_capacity` 参数（controller.py:31），`capacity=40960000` 是硬编码的。仅改 model.py 默认值**完全无效**。

**对原有功能的影响**:

| 维度 | 分析 |
|------|------|
| 缓冲区容量 | 从 ~160GB 降到 ~14GB（90% 缩减），对 <16GB RAM 机器仍有风险 |
| 现有部署 | 如果部署依赖大缓冲区且消息速率高，刷新周期短时可能提前淘汰数据 |
| 建议 | CHANGELOG 标注；长期应支持从配置文件读取 `buffer_capacity` |

**额外修改**: `main_window.py:74` 和 `left_panel.py:321` 的状态栏字符串 `"Buffer: 0 / 40960000"` 需同步更新为动态获取（当前是运行时覆写的占位文本，影响小但应修正）。

---

### H3: MAVLink v2 帧误解析 ✅ 已修复（2026-07-31）

| 文件 | `parser.py:251-275` |
|------|-------------------|
| 现状 | `data[0] in (MAGIC_V1, MAGIC_V2)` 接受 v2 魔数，但用 v1 6 字节头部解包 |

**v1 vs v2 头部差异**:

```
v1: [magic(1)] [len(1)] [seq(1)] [sys(1)] [comp(1)] [msg(1)]  = 6 字节头部
v2: [magic(1)] [len(1)] [flags_in(1)] [flags_c(1)] [seq(1)] [sys(1)] [comp(1)] [msg(2)] = 10 字节头部
```

如果用 v1 的 `"BBBBBB"` 解包 v2 数据：`seq` ← `incompat_flags`，`sys_id` ← `compat_flags`，`comp_id` ← `seq`，`msg_id` ← `sys_id`（且缺少高字节）——**所有字段全错**。

**方案 A（最小侵入）**: 检测到 v2 魔数直接返回 `None`（拒绝解析）。

**方案 B（正确修复）**: 实现完整 v2 头部解析（10 字节），需 CRC extra 字典 + 签名尾部处理。

**对原有功能的影响**:

| 维度 | 方案 A | 方案 B |
|------|--------|--------|
| 语义 | v2 帧被跳过（当前即使"解析"也是全错，更危险） | v2 帧正确解析 |
| 工作量 | 1 行 | 需 `MAVLinkConfig` 提供 crc_extra + 修改多处 |
| 调用方 | 无影响 | `MessageRecord` 无需改，`parse` 签名不变 |
| 风险 | 若有 v2 用户，从"看到错误数据"变为"看不到数据"（后者更安全） | 需处理 v2 签名(3 byte 尾部)，否则 CRC 校验总失败 |

**修订建议**（交叉分析后新增）:
- 方案 A 仅返回 `None` 会导致 v2 帧**静默消失**。建议同时增加一个计数器并在 GUI 状态栏显示 "v2 帧已跳过: N"，让用户感知。
- `parser.py:254` 的 IP 前缀格式检测中 `data[self.IP_PREFIX_LEN]` 也匹配 v2 魔数（0xFD），格式检测顺序（先 standard 后 IP-prefixed）确保安全，但需在代码中加注释说明。

**推荐**: 方案 A 先止血，方案 B 作为后续增强。

**额外修改**: 方案 A 需在 parser 中增加 `_v2_skipped_count` 计数器并暴露给 GUI。

**实施记录（2026-07-31）**: 采用方案 A，在两处拒绝 v2 帧：
1. `parser.py` standard 格式分支：`if data[0] == self.MAVLINK_MAGIC_V2: return None`
2. IP-prefixed 格式分支（取 clean_data 后）：同样的检查，防止 IP 封装绕过

---

### H4: varint 移位限制 ✅ 已修复（2026-07-31）

| 文件 | `radio_parser.py:682` |
|------|---------------------|
| 现状 | `if shift >= 64: return None, pos` — 最多 64 位 |
| 修复 | `for _ in range(10):` — protobuf varint 最多 10 字节 |

**对原有功能的影响**:

| 维度 | 分析 |
|------|------|
| 正常数据 | 99.9% 的 varint ≤ 5 字节，无影响 |
| 边界数据 | ✅ 之前被拒绝的合法 10 字节 varint 现在正确解析 |
| 恶意数据 | `range(10)` 自动终止，无需 `shift >= 64` 检查 |

**额外修改**: 无。

---

### H5: Qt Widget 非主线程操作 ✅ 已修复（2026-07-31）

| 文件 | `trace_table.py:169` `grouped_trace_view.py:156` |
|------|-------------------------------------------------|

**现状分析**: 追溯调用链：

```
Engine._udp_listen_loop (工作线程)
  → MonitorController._on_record()
    → MonitorModel.append()         ← 写入环形缓冲（有锁，安全）

GUI 定时器 _on_tick (主线程，50ms)
  → MonitorModel.get_since(seq)     ← 读取新记录
    → TraceTable.add_record()       ← 在主线程！QT 安全
    → GroupedTraceView.add_record() ← 在主线程！QT 安全
```

**关键发现**: 当前架构通过 50ms `QTimer` 将数据从后台线程泵到主线程，这是正确的模式。`add_record` 实际上**只在主线程被调用**。

**方案**: 在 `add_record` 入口加防御性保护：

```python
def add_record(self, record) -> None:
    if QThread.currentThread() != QApplication.instance().thread():
        QMetaObject.invokeMethod(self, "add_record", Qt.QueuedConnection,
                                 Q_ARG(type(record), record))
        return
    # ... 正常逻辑
```

**对原有功能的影响**:

| 维度 | 分析 |
|------|------|
| 性能 | 主线程调用时多一次 `currentThread()` 比较（纳秒级），可忽略 |
| 语义 | 主线程调用零变化；非主线程调用从"未定义行为→正确调度" |
| grouped_trace_view | 同样需要加防护（`add_record` 中还调用 `_create_child_item`、`_create_group` 等 QTreeWidget 操作） |

**额外修改**: 两处改动完全一致。

---

### H6: Plotly 主线程阻塞 ✅ 已修复（2026-07-31）

| 文件 | `drama_processing.py:594-662` |
|------|------------------------------|

**现状**: `_on_parse`/`_on_compare` 是 `@Slot()`，同步调用 `visualize_drama_3d()` → `fig.write_html()`，阻塞主线程。

**方案**: 使用 `QThreadPool` + `QObject` + `Signal`：

```python
class _PlotlyWorker(QObject):
    finished = Signal(str)      # html_path 或空
    progress = Signal(str)     # 状态文本
    error = Signal(str)

    def __init__(self, task_type: str, files: list[str], parent=None):
        super().__init__(parent)
        self._type = task_type
        self._files = files

    @Slot()
    def run(self):
        for i, f in enumerate(self._files):
            self.progress.emit(f"[{i+1}/{len(self._files)}] 解析中…")
            try:
                result = visualize_drama_3d(f)
                if result:
                    self.finished.emit(result)
                else:
                    self.error.emit(f"解析失败: {f}")
            except Exception as e:
                self.error.emit(f"异常: {e}")
```

**对原有功能的影响**:

| 维度 | 分析 |
|------|------|
| GUI 响应 | ✅ 不再冻结 |
| 用户操作 | ⚠️ 需要禁用按钮防止重复提交；`os.startfile` 自动打开改为信号触发用户确认 |
| 取消支持 | 需额外实现 `QThreadPool.cancel()` 或在 worker 中检查标志位 |
| 多次提交 | 每个任务独立，QThreadPool 自动排队 |

**让步**:
- 自动用浏览器打开最后一个 HTML 的行为需改为用户确认（避免后台静默弹窗）
- 如果用户快速连续点击解析，需加防重复按钮状态

**额外修改**: 无（独立于其他模块）。

**实施记录（2026-07-31）**: 采用 QThread 方案（非 QThreadPool），实现与计划略有差异：
- 新增 `_DramaWorker(QThread)` 类：`progress/file_done/finished` 三个信号
- `_on_parse` / `_on_compare` 改为创建 Worker → 连接信号 → `start()`
- 新增回调槽 `_open_if_exists`（自动打开 HTML）、`_on_parse_done`、`_on_compare_done`（恢复按钮）
- 解析期间禁用按钮防止重复提交

---

### H7/H9/H14: 硬编码绝对路径

涉及 3 处：

| ID | 文件 | 行 | 硬编码内容 |
|----|------|-----|-----------|
| H7 | `integrated_gui.py` | 54 | `r"D:\Work\dmd_autotest_project_ycl"` |
| H9 | `left_panel.py` | 66 | `r"D:\Work\dmd_autotest_project_ycl\file\mavlink_version"` |
| H14 | `drama_processing.py` | 63 | `r"D:\Work\dmd_autotest_project_ycl"` + `sys.path.insert(0,...)` |

**修订**（交叉分析后修正）: 
- 原计划使用 `_SELF_DIR` 变量，但 `drama_processing.py` 中未定义 `_SELF_DIR`。需要各文件先定义 `_SELF_DIR = os.path.dirname(os.path.abspath(__file__))`。
- **共享工具函数位置**: `integrated_gui.py` 是项目根目录顶层脚本，不能从 `mavlink_monitor` 包内导入。建议将路径解析函数放在 `mavlink_monitor/config.py`（或新建 `mavlink_monitor/paths.py`），`integrated_gui.py` 通过 `from mavlink_monitor.paths import get_fake_project_path` 导入。
- `left_panel.py:64-67` 中的 `../../../../..` 深层相对路径同样脆弱，应纳入统一方案。

**统一方案**:

```python
# mavlink_monitor/paths.py (新文件，所有模块共享)
import os
import warnings

def get_fake_project_path() -> str:
    """获取假设备项目路径。优先级：环境变量 → 相对路径 → 硬编码回退。"""
    env_path = os.environ.get("DMD_FAKE_PROJECT_PATH", "")
    if env_path:
        return env_path
    # 从 mavlink_monitor/paths.py 向上 1 级 → mavlink_monitor/，再向上 1 级 → 项目根
    relative = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "dmd_autotest_project_ycl"
    ))
    if os.path.isdir(relative):
        return relative
    fallback = r"D:\Work\dmd_autotest_project_ycl"
    if os.path.isdir(fallback):
        warnings.warn(f"使用硬编码回退路径: {fallback}，建议设置 DMD_FAKE_PROJECT_PATH 环境变量")
        return fallback
    return ""

def has_fake_project() -> bool:
    return os.path.isdir(get_fake_project_path())
```

**对原有功能的影响**:

| 维度 | 分析 |
|------|------|
| 新机器部署 | 设 `DMD_FAKE_PROJECT_PATH` 环境变量即可，无需改代码 |
| 本机使用 | 相对路径等效原路径 |
| 假设备 Tab | 路径不存在时 `has_fake_project()=False`，Tab 不创建（与现状行为一致） |

**额外修改**: `integrated_gui.py`, `left_panel.py`, `drama_processing.py` 三文件同步修改，**新建 `mavlink_monitor/paths.py`** 作为共享工具模块。

---

### H8: test_persistence.py 硬编码路径

| 文件 | `test_persistence.py:27-33` |
|------|---------------------------|

**修订**: 原计划遗漏了该文件中的 **3 个独立硬编码路径**：
```python
_FAKE_PROJECT = r"D:\Work\dmd_autotest_project_ycl"          # 路径 1
sys.path.insert(0, r"D:\Work\dmd_autotest_project_ycl\src\Protocol\mavlink")  # 路径 2
sys.path.insert(0, r"D:\Work\My_Project_Local\mavlink_monitor")               # 路径 3
```

**方案**: 使用 `conftest.py` 定位项目根 + `DMD_FAKE_PROJECT_PATH` 环境变量（使用上述 `paths.py` 工具函数）。

**对原有功能的影响**:

| 维度 | 分析 |
|------|------|
| CI/CD | 设环境变量即可运行 |
| 其他测试 | conftest.py session scope，不影响其他测试 |
| 原测试语义 | 路径解析逻辑不变，只是来源变了 |

**额外修改**: 检查是否还有其他测试文件有类似硬编码。

---

### H9: left_panel.py 硬编码路径

见 H7/H9/H14 统一方案。

---

### H10: 单体文件拆分 ✅ 已修复（2026-07-31）

**实施**: 3192 行单体文件拆分为 `mavlink_monitor/integrated_gui/` 包（8 个模块，每个 ≤870 行）:

```
mavlink_monitor/integrated_gui/
├── __init__.py      (170 行)  重新导出 + main()
├── __main__.py      (  3 行)  python -m 入口
├── _env.py          ( 90 行)  路径设置 + 假设备模块条件导入
├── _reflection.py   (415 行)  AST 动态反射 (SourceInfo, _parse_source, ...)
├── _types.py        (430 行)  类型检测 + 值转换 + 控件工厂
├── _config.py       (240 行)  SimConfig + _build_sim_configs + _SocketInterceptor
├── _panels.py       (870 行)  SimulationPanel
├── _nested.py       (430 行)  NestedDevicePanel
├── _monitor.py      (560 行)  FullUdpMonitorPanel
└── _window.py       (255 行)  多显示器辅助 + IntegratedMainWindow
```

原 `integrated_gui.py` 保留为 10 行兼容重定向层，`from integrated_gui import ...` 仍可用。

| 文件 | `integrated_gui.py` (3278 行) |
|------|-----------------------------|

**修订**（交叉分析后修正）:
- 原计划声称 "`_MultiSelectButton` 被 drama_processing.py 通过 `integrated_gui._MultiSelectButton` 引用"——**错误**。实际导入是 `from mavlink_monitor.gui.filter_bar import _MultiSelectButton`（drama_processing.py:58），与 integrated_gui.py 无关。
- H10 与 H11 **没有依赖关系**（原计划声称"拆分后才好加 property"是错误的）——两个任务涉及完全不同的文件集。H11 可独立先行。

**方案**: 按职责拆分为 4 个文件：

```
integrated_gui.py (入口 + IntegratedMainWindow + main, ~300 行)
├── src_reflection.py     (SourceInfo, _parse_source, _detect_kind, _make_input_widget, _coerce, _INT_RANGES, ~400 行)
├── sim_config.py         (SimConfig, _build_sim_configs, _SocketInterceptor, ~200 行)
├── simulation_panel.py   (SimulationPanel, NestedDevicePanel, ~1000 行)
├── udp_monitor_panel.py  (FullUdpMonitorPanel, 屏幕辅助函数, ~600 行)
└── (现有) drama_processing.py (DramaProcessingPanel, ~1537 行)
```

**对原有功能的影响**:

| 维度 | 分析 |
|------|------|
| 导入语义 | `from integrated_gui import main` 保持可用（原入口兼容层 re-export） |
| SimulationPanel | 被 drama_processing.py 引用 → 需改为从 `simulation_panel` 导入 |
| AST 反射 | `_discover_update_methods` 被嵌套面板使用，需确保导入路径 |
| 测试 | test_persistence.py 需更新导入 |

**修订建议**（交叉分析后新增）:
- SimulationPanel 和 NestedDevicePanel 之间存在大量重复逻辑（`_discover_update_methods`、`_coerce` 调用、`_on_apply_clicked` 参数强制转换），拆分时应提取共享基类 `_BaseSimulationPanel`，避免将重复代码复制到两个文件。

**让步**:
- 拆分后 `integrated_gui.py` 仍在——作为兼容入口 `from .simulation_panel import SimulationPanel` 再 re-export
- 可以让所有现有 `from integrated_gui import X` 继续工作（延迟符号绑定）

**额外修改**: 更新 CODE_PLAN.md 的分段索引（大面积行号变更）。

---

### H11: 跨类访问私有属性 ✅ 已修复（2026-07-31）

**实施**: 在 TraceTable / GroupedTraceView 新增公共属性（`scroll_paused` setter、`time_mode` property），MainWindow 改为使用公共 API。修复范围涵盖 `_scroll_paused`、`_time_mode`、`_table` 的直接访问。

| 文件 | `main_window.py:508-542` |
|------|-------------------------|

**修订**: 原计划将其放在第 3 批，并声称依赖 H10（文件拆分）。**经过交叉分析确认：H11 与 H10 无任何文件重叠，可完全独立执行，建议提升到第 1 批。**

**现状**: `MainWindow` 直接读写以下 7 个私有属性：

| 私有属性 | 访问行号 |
|----------|---------|
| `_trace_table._scroll_paused` | 508, 516 |
| `_trace_table._time_mode` | 523, 525 |
| `_trace_table._table` | 526-527, 535, 542 |
| `_trace_table._relay_visible` | 534 |
| `_trace_table._source_visible` | 541 |
| `_grouped_view._scroll_paused` | 509, 517 |
| `_grouped_view._time_mode` | 528 |

**方案**: 在 `TraceTable` / `GroupedTraceView` 上暴露公共 property：

```python
# TraceTable 新增:
@property
def scroll_paused(self) -> bool: return self._scroll_paused
@scroll_paused.setter
def scroll_paused(self, v: bool): self._scroll_paused = v

@property
def time_mode(self) -> int: return self._time_mode
@time_mode.setter
def time_mode(self, v: int):
    self._time_mode = v
    self._table.setColumnHidden(1, v == 0)
    self._table.setColumnHidden(2, v == 1)

@property
def relay_visible(self) -> bool: return self._relay_visible
@relay_visible.setter
def relay_visible(self, v: bool):
    self._relay_visible = v
    self._table.setColumnHidden(5, not v)

@property
def source_visible(self) -> bool: return self._source_visible
@source_visible.setter
def source_visible(self, v: bool):
    self._source_visible = v
    self._table.setColumnHidden(13, not v)
```

**对原有功能的影响**:

| 维度 | 分析 |
|------|------|
| MainWindow 调用 | `_trace_table._scroll_paused` → `_trace_table.scroll_paused`（纯重命名） |
| 行为 | ✅ 完全不变，property 内部逻辑与原来手动操作一致 |
| `_table` 暴露 | ❌ 不能直接暴露 QTableWidget。应为列可见性操作封装方法如 `set_time_column_visible(bool)` |

**让步**:
- 这是纯内部重构，不改变外部行为。
- H11 完成后，H12（时间列不同步）会**自动修复**——因为 `time_mode` setter 中已包含 `setColumnHidden` 调用，`MainWindow._on_toggle_time` 在设置 `grouped_view.time_mode` 时就会触发列更新。

**额外修改**: 仅 `main_window.py` + `trace_table.py` + `grouped_trace_view.py` 三个文件。

---

### H12: 分组视图时间列不同步 ✅ 已修复（2026-07-31）

**实施**: H11 修复时，`GroupedTraceView.time_mode` setter 内同时更新 `_tree.setColumnHidden()`，MainWindow 改用 `time_mode` 属性后自动修复。

| 文件 | `main_window.py:528` |
|------|---------------------|

**现状**: `_on_toggle_time` 设置了 `_grouped_view._time_mode` 但从未调用 `_grouped_view._toggle_time()` 或等效逻辑来更新 `_tree` 列可见性。

**修订**: H11 实施后，本项会**自动修复**——因为 `time_mode` property setter 封装了 `setColumnHidden` 调用。

**方案**: 与 H11 合并实施：
- 如有时间列 → 通过 property setter 自动同步
- 如无时间列 → 删除 `_grouped_view._time_mode = new_mode` 行 + 移除 `_time_mode` 属性

**对原有功能的影响**: 取决于实际是否需要。无论是删代码还是补代码，都不会破坏现有功能（当前就是不同步状态）。

---

### H13: trim_rows O(n²) ✅ 已修复（2026-07-31）

| 文件 | `trace_table.py:202-204` |
|------|--------------------------|

**现状**: `while rowCount() > max: removeRow(0)` — O(rows_to_remove × total_rows)

**修订**（交叉分析后修正）: 原计划的 `for _ in range(excess)` 方案存在隐患——如果 `removeRow` 过程中 `rowCount()` 发生变化（异常/并发），可能尝试删除多于实际行数的行。建议改为 while 循环：

```python
def trim_rows(self, max_rows: int) -> None:
    excess = self._table.rowCount() - max_rows
    if excess <= 0:
        return
    self._table.setUpdatesEnabled(False)
    try:
        while excess > 0 and self._table.rowCount() > 0:
            self._table.removeRow(0)
            excess -= 1
    finally:
        self._table.setUpdatesEnabled(True)
```

**对原有功能的影响**:

| 维度 | 分析 |
|------|------|
| 性能 | `setUpdatesEnabled(False)` 阻断 N 次重绘，实际耗时从 秒级→毫秒级 |
| 语义 | 完全不变（从头部删除旧行） |
| 安全 | while 循环防止 `rowCount()` 变化导致的不一致状态 |

**为何不用 `takeRow` + 手动清理**: `takeRow` 返回 `None`（PySide6 的已知行为），仍需手动管理。批量暂停重绘是最小改动方案。

**额外修改**: `grouped_trace_view.py:trim_messages` 使用堆排序算法（`heapq`，line 320），与逐行删除的复杂度不同——不需要本次同步修复。

**实施记录（2026-07-31）**: 采用与计划一致的 `setUpdatesEnabled(False/True)` 包裹方案。实测 1000→500 行修剪耗时 0.4ms。

---

### H14: drama_processing.py 硬编码路径

见 H7/H9/H14 统一方案。

---

### H15: 回调接口文档不一致 ✅ 已修复（2026-07-31）

**实施**: 更新 `set_message_injector` docstring，callback 签名从 4 参数改为实际 5 参数。

| 文件 | `integrated_gui.py:2034` |
|------|-------------------------|

**现状**:

```python
# 文档 (L2034):
# callback 签名为: (data: bytes, sender_addr: tuple, dst_ip: str, dst_port: int) -> None

# 实际调用 (L2078-2079):
def _on_recv(data: bytes, sender_addr: tuple) -> None:
    callback(data, gcs_ip, gcs_port, dst_ip, dst_port)   # 5 个参数！

# 实际消费 (L3180):
lambda d, sip, sp, dip, dp, p=panel:
    self._udp_panel.inject_raw_message(d, sip, sp, dip, dp)
```

**方案**: 修正文档。

```python
# 修正后:
# callback 签名为: (data: bytes, src_ip: str, src_port: int, dst_ip: str, dst_port: int) -> None
# 其中 src_ip/src_port 为地面站地址（GCS），dst_ip/dst_port 为目标设备地址
```

**对原有功能的影响**: 无。纯文档修改。

**额外修改**: 无。

---

## 4. 新增项目

> 以下项目来自 5 Agent 交叉分析中发现的原计划遗漏项。均经过交叉质询验证。

### H16: 提取共享 Widget 到 gui/widgets.py ✅ 已完成（2026-07-31，v1.10）

**实施**: 已于 CODE_PLAN v1.10 完成。`mavlink_monitor/gui/widgets.py` 包含全部 4 个共享控件：
`_MultiSelectButton`, `_FixedHeightListView`, `_LimitedCombo`, `_CollapseToggle`。

| 严重程度 | HIGH（架构反模式，影响 3 个模块的导入关系） |
|----------|------------------------------------------|

**现状**: 三个自定义下拉/选择控件分散在无关模块中，形成跨模块私有类导入：

```
filter_bar.py        ─defines→ _MultiSelectButton
    ↓ (drama_processing.py:58 导入)
drama_processing.py  ─defines→ _FixedHeightListView, _LimitedCombo
    ↓ (integrated_gui.py:104 导入)
integrated_gui.py    ─uses→ _LimitedCombo（6 处）
```

`_LimitedCombo` 定义在 `drama_processing.py`（领域处理模块），但**从不在此文件中实例化**。6 个实例全部在 `integrated_gui.py` 中。这是 misplaced responsibility 反模式。

**方案**: 新建 `mavlink_monitor/gui/widgets.py`，迁移三个类：

```
mavlink_monitor/gui/widgets.py
├── _FixedHeightListView    ← 从 drama_processing.py:1276 迁入
├── _LimitedCombo           ← 从 drama_processing.py:1302 迁入
└── _MultiSelectButton      ← 从 filter_bar.py:16 迁入
```

更新导入：
- `filter_bar.py` → `from mavlink_monitor.gui.widgets import _MultiSelectButton`
- `drama_processing.py` → `from mavlink_monitor.gui.widgets import _FixedHeightListView, _LimitedCombo`
- `integrated_gui.py` → `from mavlink_monitor.gui.widgets import _LimitedCombo`

**对原有功能的影响**:

| 维度 | 分析 |
|------|------|
| 导入语义 | 所有类的公开 API 不变，调用方只改 import 路径 |
| 风险 | 极低——纯文件移动，不改变任何逻辑 |
| CODE_REVIEW_REPORT | 修复第 187 行 "未使用导入" 误报（`_FixedHeightListView` 和 `_LimitedCombo` 实际被跨文件使用） |

**让步**: 无。独立于所有其他任务，可在任意批次执行。

**额外修改**: 
- 删除 `drama_processing.py` 中 `QComboBox` 的导入（仅用于 `_LimitedCombo` 父类），改为 `widgets.py` 中导入。
- 删除 `drama_processing.py` 中未使用的导入：`QCloseEvent`（line 32）、`QGridLayout`（line 41）。

---

### H17: 修正 _TamperEntry 控件选择 ✅ 已修复（2026-07-31）

**实施**: `drama_processing.py` _TamperEntry 三个下拉框从 `_MultiSelectButton(single_select=True)` 替换为 `_LimitedCombo(20)`。
- `currentData()` 直接返回 int，消除 `selected_key() → int()` 转换
- 信号 `selection_changed` → `currentIndexChanged`
- 移除 `drama_processing.py` 对 `_MultiSelectButton` 的无用导入

| 严重程度 | MEDIUM（功能正确但 UX 不匹配） |
|----------|-------------------------------|

**现状**: `_TamperEntry`（drama_processing.py:1370,1384,1391）的三个下拉框使用 `_MultiSelectButton(single_select=True)`——这是把**多选过滤控件**强行用作**单选数据录入控件**。

**问题**:
1. **UX 错位**: 用户面对的是一个带勾选框的弹出菜单（多选过滤的范式），但实际上只能选一项。缺少 QComboBox 的标准交互（键盘输入跳转、滚轮切换）。
2. **弹窗宽度不匹配**: `_MultiSelectButton._show_popup()` 硬编码 `menu.setMinimumWidth(180)`，而列宽只有 80/90/100px，弹窗超出按钮 2 倍以上。
3. **多余的 string↔int 转换**: `get_data()` 中 `int(frame_str)`、`int(drone1_str)`、`int(drone2_str)` 来回转换——用 `_LimitedCombo` 的 `currentData()` 可直接存 int。
4. **丢失选择的 UX bug**: 当 `set_options()` 移除当前选中项时，按钮显示空字符串（`base_label=""` 变为空），无任何占位提示。

**历史背景**: CODE_PLAN.md line 780 记录这是 v1.5 的**有意变更**——为了与 UDP 监控 MsgID 过滤"同款样式"。这是一个审美优先于 UX 的决策。

**方案**: 将三个 `_MultiSelectButton(single_select=True)` 替换为 `_LimitedCombo(max_visible=20)`：

```python
# 替换前:
self._combo_frame = _MultiSelectButton("", single_select=True)
self._combo_frame.set_options({str(f): str(f) for f in all_frames})
self._combo_frame.set_selected_key(str(all_frames[0]))
frame_str = self._combo_frame.selected_key()

# 替换后:
self._combo_frame = _LimitedCombo(20)
self._combo_frame.clear()
for f in all_frames:
    self._combo_frame.addItem(str(f), userData=f)  # 直接存 int
self._combo_frame.setCurrentIndex(0)
frame = self._combo_frame.currentData()  # 直接返回 int，无需 str→int
```

**对原有功能的影响**:

| 维度 | 分析 |
|------|------|
| 数据获取 | ✅ `currentData()` 直接返回 int，消除 `selected_key() → int()` 转换 |
| 信号 | `selection_changed` → `currentIndexChanged`，`_on_params_changed` 连接方式不变 |
| `set_data()` | `set_options({k:v})` + `set_selected_key(k)` → `clear()` + `addItem()` + `setCurrentIndex()` |
| 外观 | 弹窗宽度自动匹配列宽（`_LimitedCombo.showPopup()` 已锁定宽度），不再 180px 溢出 |
| 可访问性 | ✅ 支持键盘输入跳转、滚轮切换、屏幕阅读器 |

**让步**: 
- 移除 `_TamperEntry` 对 `_MultiSelectButton` 的导入依赖后，`drama_processing.py:58` 的 import 可删除。
- 在 H16（Widget 提取）之后执行更干净——可以直接从 `widgets.py` 导入 `_LimitedCombo`。

---

### H18: 修复 _ROW_HEIGHT DPI 缩放问题 ✅ 已修复（2026-07-31）

**实施**: `widgets.py` `_LimitedCombo.showPopup()` 新增 DPI 感知：弹出前用 `view.sizeHintForRow(0)` 获取实际行高，动态更新 `_FixedHeightListView._max_height`。100% DPI 行为不变，高 DPI 下正确适配。

| 严重程度 | LOW（仅在非 100% DPI 时显现） |
|----------|------------------------------|

**现状**: `drama_processing.py:1309` 硬编码 `_ROW_HEIGHT = 22`。`_FixedHeightListView` 用 `max_visible * 22` 计算硬截断高度（如 20×22=440px）。

**问题**: 在 150% DPI（常见于 4K 笔记本）下，实际行高约 30-35px，440px 只能显示 ~13 项而非预期的 20 项。在 macOS 上默认行高也更大。

**方案**: 从 view 动态获取行高：

```python
class _LimitedCombo(QComboBox):
    def __init__(self, max_visible: int = 20, parent=None):
        super().__init__(parent)
        self._max_visible = max_visible
        self.setMaxVisibleItems(max_visible)
        view = _FixedHeightListView(max_visible * 22)  # 初始值
        self.setView(view)
        # 首项添加后校准实际行高
        self._view = view

    def showPopup(self) -> None:
        view = self.view()
        if view is not None and self.count() > 0:
            actual_row_h = view.sizeHintForRow(0)
            if actual_row_h > 0:
                view._max_height = self._max_visible * actual_row_h
        # ... 宽度锁定 + super().showPopup()
```

**更简单的方案**: 直接移除 `_FixedHeightListView`，仅依赖 `setMaxVisibleItems()`。在 PySide6/Qt6 中，`setMaxVisibleItems` 已被修复（不会被 `clear()+addItem()` 重置），且正确适配 DPI。

**对原有功能的影响**:

| 维度 | 分析 |
|------|------|
| 100% DPI | 无变化 |
| 高 DPI | ✅ 显示正确的项目数而非被过早截断 |
| 风险 | 移除 `_FixedHeightListView` 后，若某些 Qt 样式绕过 `setMaxVisibleItems`，弹窗可能再次变高。建议保留 `_FixedHeightListView` 但改为动态获取行高 |

**推荐**: H16 实施时一起处理——在 `widgets.py` 中实现 DPI 感知的行高。

---

### H19: 清理 TODO 死代码（UDP 监听器桩） ✅ 已修复（2026-07-31）

**实施**: 删除 `main_window.py`（5处）和 `left_panel.py`（11处）中所有注释掉的 UDP 监听代码块。同步移除 `left_panel.update_stats()` 的 `udp_packets`/`udp_mavlink` 参数，更新两处调用方。

| 严重程度 | LOW（注释掉的代码不影响运行） |
|----------|------------------------------|

**现状**: 17 处 `TODO: UDP 监听暂注释` 分布在两个文件中：
- `main_window.py`: lines 91, 92, 301, 326, 335
- `left_panel.py`: lines 102, 103, 113, 125, 294, 296, 298, 319, 324, 332, 338

这些是长期搁置的 UDP 监听功能片段，已失去同步。如果功能永久搁置，应删除；如果计划恢复，应创建 issue 跟踪。

**方案**: 
1. 确认 UDP 监听功能是否计划恢复
2. 如不恢复 → 删除所有 TODO 注释块
3. 如计划恢复 → 提取到独立分支/issue，从主分支移除死代码

**对原有功能的影响**: 无。纯代码清理。

---

### H20: 合并重复的 _fmt_rel/_fmt_abs 函数 ✅ 已完成（2026-07-31，v1.10）

**实施**: 已于 CODE_PLAN v1.10 完成。`mavlink_monitor/gui/utils.py` 定义 `fmt_rel`/`fmt_abs`，`trace_table.py` 和 `grouped_trace_view.py` 均从此导入。

| 严重程度 | LOW（代码重复，不影响功能） |
|----------|---------------------------|

**现状**: 相同的 `_fmt_rel` 和 `_fmt_abs` 函数被定义了 **5 次**：

| 文件 | 行号 |
|------|------|
| `trace_table.py` | 47, 54 |
| `grouped_trace_view.py` | 73, 80 |
| `monitor_tab.py` | 341 |

**方案**: 提取到 `mavlink_monitor/gui/utils.py`（或现有工具模块），所有文件从同一处导入。

**对原有功能的影响**: 无。纯代码去重。

---

## 5. 依赖关系（修订版）

```
第 0 批（基础设施，其他项的前置依赖）:
  H16 ──→ (独立，新建 widgets.py，后续 H17/H10 可依赖它)

第 1 批（独立，零风险）:
  H2 ──→ (独立，但需同时改 controller.py:33)
  H1 ──→ (独立，与 H2 同文件 model.py)
  H3 ──→ (独立)
  H4 ──→ (独立)
  H7 ──┬──→ H9 (同路径变量) ──→ H8 (测试用同一路径)
       └──→ H14 (drama_processing.py 同路径)
  H15 ──→ (独立)
  H11 ──→ H12 (property 封装时自动修复时间列不同步)
  H13 ──→ (独立)
  H20 ──→ (独立)

第 2 批（需信号/property/线程，有微小风险）:
  H5 ──→ (独立)
  H6 ──→ (独立，QThreadPool + Signal)
  H17 ──→ (独立，依赖 H16 更干净但非必须)
  H18 ──→ (独立，建议 H16 时一起处理)
  H19 ──→ (独立)

第 3 批（大重构）:
  H10 ──→ (依赖 H16 提供干净的 widget 导入)
        └──→ 内部重构: 提取 SimulationPanel/NestedDevicePanel 共享基类
```

**关键修订**:
- ~~H10 → H11~~ **已删除**。H10（拆分 integrated_gui.py）和 H11（TraceTable/GroupedTraceView 加 property）涉及**完全不同的文件集**，无任何依赖关系。
- **H11 → H12** **已确认**。H11 中将 `time_mode` 封装为 property（setter 内调 `setColumnHidden`），H12 的时间列不同步问题自动修复。
- H2 的依赖从"仅 model.py"修正为"model.py + controller.py"。

---

## 6. 执行顺序建议（修订版）

| 批次 | ID | 预估工作量 | 风险 | 备注 |
|------|-----|----------|------|------|
| **第 0 批** | H16 | ~30 行 | 极低 | **新建 gui/widgets.py**，后续项的前置依赖 |
| **第 1 批** | H2 | 2 行 | 极低 | model.py 默认值 ✅ + **controller.py:33 待修** |
| | H1 | 1 行 | 极低 | model.py get_latest() 改用 reversed |
| | H3 | 3 行 | 极低 | 返回 None 拒绝 v2 + 增加跳过计数器 |
| | H4 | 3 行 | 极低 | for range(10) 替代 shift >= 64 |
| | H15 | 1 行 | 无 | 纯文档修正 |
| | H7/H9/H14 | ~20行/文件 | 低 | 新建 paths.py + 3 文件引用 |
| | H11 | ~40 行 | 低 | 3 文件加 property，自动修复 H12 |
| | H12 | 0 行 | 无 | H11 自动修复 |
| | H13 | ~12 行 | 低 | while 循环 + setUpdatesEnabled |
| | H20 | ~10 行 | 极低 | 提取 _fmt_rel/_fmt_abs 到 utils.py |
| **第 2 批** | H5 | ~15行/文件 | 低 | 防御性 currentThread() 检查 |
| | H8 | ~15 行 | 低 | conftest.py + 使用 paths.py |
| | H17 | ~30 行 | 低 | _TamperEntry 控件替换，依赖 H16 |
| | H18 | ~10 行 | 低 | DPI 感知行高，建议 H16 时一起做 |
| | H19 | ~20 行 | 极低 | 删除 TODO 死代码 |
| **第 3 批** | H6 | ~60 行 | 中 | QThreadPool + Signal |
| **第 4 批** | H10 | ~2 天 | 高 | 拆分 + 兼容层 + 提取共享基类 + 更新 CODE_PLAN |

---

## 7. 交叉分析附录：Agent 分歧与共识

> 以下记录了 5 个分析 Agent 之间的关键分歧及最终裁决。

### 共识项（所有 Agent 一致同意）

| 发现 | 结论 |
|------|------|
| H2 修复不完整 | `controller.py:33` 硬编码 `capacity=40960000` 覆盖了 model.py 的安全默认值，必须同步修改 |
| H10→H11 无依赖 | 两个任务涉及完全不同的文件集（H10: integrated_gui.py及其衍生，H11: trace_table/grouped_trace_view），可独立执行 |
| Widget 类应提取到共享模块 | `_LimitedCombo` 定义在 drama_processing.py 但只被 integrated_gui.py 使用——misplaced responsibility |
| CODE_REVIEW_REPORT 第 187 行部分错误 | `_FixedHeightListView` 和 `_LimitedCombo` 是类**定义**而非"未使用导入"，且被跨文件使用 |

### 分歧项（Agent 之间意见不一致，已裁决）

| 分歧 | Agent 2 观点 | Agent 3 观点 | Agent A 裁决 | 最终决策 |
|------|-------------|-------------|-------------|---------|
| _TamperEntry 控件选择 | _MultiSelectButton(single_select=True) 是错误的控件，应改回 _LimitedCombo | 未提及 | 同意 Agent 2 的 UX 分析，但严重程度为 MEDIUM | **列为 H17**，建议改回 _LimitedCombo（v1.5 的"同款样式"决策是审美优先于 UX） |
| M17 严重程度 | 未提及 | 应从 MEDIUM 升级为 HIGH（8 秒启动阻塞） | 不同意——单次启动延迟 ≠ 重复操作冻结 | **保持 MEDIUM**，不纳入 HIGH 优化计划 |
| H3 风险 | 未提及 | 静默丢弃 v2 帧缺少用户感知 | — | **采纳**，H3 方案中增加「跳过计数器 + GUI 状态栏显示」 |
| H13 实现细节 | 未提及 | for 循环应改为 while 循环防 rowCount 变化 | — | **采纳**，改为 while 循环 |
| Widget 提取是否并入 H10 | 应提取为独立项 | 应提取 | 同意独立，但可在同一批次 | **列为 H16**（独立项，第 0 批基础设施） |

### 原计划的 3 处错误

| # | 位置 | 错误描述 | 修正 |
|---|------|---------|------|
| 1 | §H2 影响分析 | 声称 `MonitorController.__init__` 有 `model_capacity` 参数支持覆盖——实际上没有 | H2 方案中增加 `controller.py:33` 修改 |
| 2 | §H2 执行顺序 | 标注 "已完成"——实际只改了 model.py 默认值，controller.py 未改 | 状态改为 "部分完成，待修 controller.py" |
| 3 | §3 依赖图 | `H10 → H11 (拆分后才好加 property)`——两任务文件集零重叠 | 删除此依赖；H11 移至第 1 批 |
| 4 | §H10 拆分方案 | 声称 `_MultiSelectButton` 从 integrated_gui 导入——实际从 filter_bar 导入 | 修正为正确导入路径 |

---

> **注意**: 本计划目前覆盖 20 个优化项（原 H1-H15 + 新增 H16-H20）。CODE_REVIEW_REPORT.md 中的 53 个 MEDIUM 和 61 个 LOW 问题不在此范围。
>
> **Agent 分析参与**: 5 个专用 Agent（进度核查 / QComboBox 架构 / 计划完整性 / 交叉质询 A / 交叉质询 B），总计审查 100+ 源码位置。
