# mavlink_monitor 迁移指南

> **目标**: 将 `mavlink_monitor` 工具从当前位置迁移到 `D:\Work\dmd_autotest_project_ycl\tools\`

---

## 目录

1. [目录结构变化](#1-目录结构变化)
2. [必须改（不改会报错）](#2-必须改不改会报错)
3. [建议改（不改也能工作，但有隐患）](#3-建议改不改也能工作但有隐患)
4. [不需要改（自引用路径）](#4-不需要改自引用路径)
5. [迁移步骤](#5-迁移步骤)
6. [迁移后验证清单](#6-迁移后验证清单)

---

## 1. 目录结构变化

### 当前结构

```
D:\Work\
  My_Project_Local\
    mavlink_monitor/              ← 工具当前位置（独立项目）
      mavlink_monitor/            ← Python 包
      tests/
      resources/
      docs/
      integrated_gui.py           ← 兼容入口
      run_monitor.bat
  dmd_autotest_project_ycl/       ← 假设备项目（外部依赖）
    src\Protocol\mavlink\
      fake_airplane.py
      fake_nest.py
      fake_radio.py
    file\mavlink_version\
      mavlink_config_v*.json
      mavlink_enums_v*.json
    utils\logger.py
```

### 迁移后结构

```
D:\Work\
  dmd_autotest_project_ycl\
    tools\
      mavlink_monitor/            ← 工具新位置
        mavlink_monitor/          ← Python 包
        tests/
        resources/
        docs/
        integrated_gui.py
        run_monitor.bat
    src\Protocol\mavlink\         ← 假设备（不动）
    file\mavlink_version\         ← 配置（不动）
    utils\logger.py               ← 工具（不动）
```

### 关键变化

| 维度 | 迁移前 | 迁移后 |
|------|--------|--------|
| 工具与假设备的关系 | **兄弟目录**（`My_Project_Local` 和 `dmd_autotest_project_ycl` 同级） | **子目录**（`tools/mavlink_monitor` 在 `dmd_autotest_project_ycl` 内部） |
| 从工具根到假设备根 | `..\dmd_autotest_project_ycl`（上 1 级 + 进入） | `..\..`（上 2 级） |
| 假设备项目绝对路径 | `D:\Work\dmd_autotest_project_ycl` | **不变** |

---

## 2. 必须改（不改会报错）

### 2.1 `core/paths.py` L36 — 相对路径推断 ⚠️ CRITICAL

**文件**: `mavlink_monitor\core\paths.py`

**当前代码** (L31-39):

```python
# 2) 相对路径推断：paths.py → core → mavlink_monitor → project_root → dmd_autotest_project_ycl
_here = os.path.dirname(os.path.abspath(__file__))       # .../mavlink_monitor/core/
_pkg_dir = os.path.dirname(_here)                         # .../mavlink_monitor/
_project_root = os.path.dirname(_pkg_dir)                  # .../mavlink_monitor (outer)
relative = os.path.normpath(os.path.join(
    _project_root, "..", "dmd_autotest_project_ycl"       # ← 从 My_Project_Local 上 1 级 + 进入
))
```

**问题**: `_project_root` 现在是 `tools\mavlink_monitor\`，`..\dmd_autotest_project_ycl` 变成 `tools\dmd_autotest_project_ycl`（不存在）。

**修改为**:

```python
# 2) 相对路径推断：paths.py → core → mavlink_monitor(pkg) → mavlink_monitor(root) → tools → dmd_autotest_project_ycl
_here = os.path.dirname(os.path.abspath(__file__))       # .../tools/mavlink_monitor/mavlink_monitor/core/
_pkg_dir = os.path.dirname(_here)                         # .../tools/mavlink_monitor/mavlink_monitor/
_project_root = os.path.dirname(_pkg_dir)                  # .../tools/mavlink_monitor/
relative = os.path.normpath(os.path.join(
    _project_root, "..", ".."                              # ← 上 2 级到 dmd_autotest_project_ycl
))
```

> **注意**: 如果设置了 `DMD_FAKE_PROJECT_PATH=D:\Work\dmd_autotest_project_ycl` 环境变量，
> 此路径不会被走到（环境变量优先级最高，见 `paths.py` L27-29）。推荐设置环境变量以彻底消除路径依赖。

---

### 2.2 `resources/config_default.json` L4 — 搜索路径

**文件**: `resources\config_default.json`

**当前内容**:

```json
"search_paths": [
    "../../file/mavlink_version",
    "D:/Work/dmd_autotest_project_ycl/file/mavlink_version"
]
```

**问题**: 相对路径 `../../file/mavlink_version` 从 `tools/mavlink_monitor/resources/` 上 2 级后
到达 `tools/mavlink_monitor/`，此目录下没有 `file/mavlink_version`。

**修改为**:

```json
"search_paths": [
    "../../../file/mavlink_version",
    "D:/Work/dmd_autotest_project_ycl/file/mavlink_version"
]
```

> 上 3 级：`resources/` → `mavlink_monitor/` → `tools/` → `dmd_autotest_project_ycl/` → `file/mavlink_version` ✓
>
> 绝对路径条目 `D:/Work/dmd_autotest_project_ycl/file/mavlink_version` 不受迁移影响，保持不动。

---

## 3. 建议改（不改也能工作，但有隐患）

### 3.1 `gui/left_panel.py` L67-68 — fallback 路径

**文件**: `mavlink_monitor\gui\left_panel.py`

**当前代码** (L65-68):

```python
_KNOWN_DIRS = [
    get_mavlink_version_dir,                                    # 优先级 1: paths.py
    lambda: os.path.join(os.path.dirname(__file__), "..", "..", "..",
                         "..", "..", "file", "mavlink_version"), # 优先级 2: fallback
]
```

**问题**: fallback 路径上 5 级从 `gui/left_panel.py` 出发：
- 迁移前: `gui` → `mavlink_monitor(pkg)` → `mavlink_monitor(root)` → `My_Project_Local` → `Work` → `file/mavlink_version` ❌（本来就不可达）
- 迁移后: `gui` → `mavlink_monitor(pkg)` → `mavlink_monitor(root)` → `tools` → `Work` → `file/mavlink_version` ❌（仍然不可达）

**建议**: 修正为 4 级相对路径，或直接删除此 fallback：

```python
_KNOWN_DIRS = [
    get_mavlink_version_dir,                                    # 优先级 1: paths.py
    lambda: os.path.join(os.path.dirname(__file__), "..", "..", "..",
                         "..", "file", "mavlink_version"),       # 上 4 级到 dmd_autotest_project_ycl
]
```

> 迁移后路径解析：
> `left_panel.py` → `gui/` → `mavlink_monitor(pkg)/` → `mavlink_monitor(root)/` → `tools/` → 然后 `file/mavlink_version` ❌
>
> 实际上这个 fallback 从迁移前就无法正确工作（需要上 4 级 + 进 `dmd_autotest_project_ycl`）。
> 由于 `get_mavlink_version_dir()` (优先级 1) 修复后会正常工作，此 fallback 不会被触发。
> **建议直接删除此 fallback，完全依赖 `paths.py`**。

### 3.2 `core/paths.py` L42 — 硬编码回退

**文件**: `mavlink_monitor\core\paths.py`

```python
fallback = r"D:\Work\dmd_autotest_project_ycl"
```

**结论**: **无需修改**。绝对路径，`dmd_autotest_project_ycl` 位置不变，仍正确。

---

## 4. 不需要改（自引用路径）

以下文件全部使用 `__file__` 或 `Path(__file__).resolve()` 进行包内自引用，
随项目目录整体移动后自动适配，**无需任何修改**：

| 文件 | 行号 | 路径计算 | 说明 |
|------|------|----------|------|
| `integrated_gui/__init__.py` | L52-55 | `Path(__file__).resolve().parent.parent` | `mavlink_monitor/` 包根 |
| `integrated_gui/_env.py` | L13-15 | `Path(__file__).resolve().parent.parent` | 同上 |
| `integrated_gui/_monitor.py` | L344,352,360 | `os.path.dirname(__file__), "..", "resources"` | 包内 `resources/` |
| `gui/main_window.py` | L350,370,418 | `os.path.dirname(__file__), "..", "..", "resources"` | 包内 `resources/` |
| `integration/monitor_tab.py` | L33 | 3 级上到项目根 | `sys.path` 注入 |
| `run_monitor.bat` | L2 | `"%~dp0"` | 脚本自身目录 |
| `tests/` 中所有绝对路径 | — | `D:\Work\dmd_autotest_project_ycl\...` | 假设备项目未移动 |

---

## 5. 迁移步骤

### Step 1: 复制项目

```batch
xcopy /E /I /H /Y "D:\Work\My_Project_Local\mavlink_monitor" "D:\Work\dmd_autotest_project_ycl\tools\mavlink_monitor"
```

### Step 2: 应用路径修改

按优先级：

| 优先级 | 文件 | 改动 |
|--------|------|------|
| **P0** | `tools\mavlink_monitor\mavlink_monitor\core\paths.py` L36 | `"..", "dmd_autotest_project_ycl"` → `"..", ".."` |
| **P1** | `tools\mavlink_monitor\resources\config_default.json` L4 | `../../file/` → `../../../file/` |
| P2 | `tools\mavlink_monitor\mavlink_monitor\gui\left_panel.py` L67-68 | 删除不可达的 fallback 或修正路径 |

### Step 3（推荐）: 设置环境变量

```batch
setx DMD_FAKE_PROJECT_PATH "D:\Work\dmd_autotest_project_ycl"
```

设置后 `paths.py` 直接使用环境变量，完全跳过相对路径推断和硬编码回退，
即使未来再次移动工具也无需修改代码。

---

## 6. 迁移后验证清单

| # | 验证项 | 命令 | 预期 |
|---|--------|------|------|
| 1 | 全量测试 | `cd tools\mavlink_monitor && python -m pytest tests/ -v -s` | 168 passed |
| 2 | 导入验证 | `python -c "from mavlink_monitor.core.paths import get_fake_project_path; print(get_fake_project_path())"` | 输出 `D:\Work\dmd_autotest_project_ycl` |
| 3 | GUI 启动 | `python -m mavlink_monitor.integrated_gui` | 窗口正常显示，无 import 报错 |
| 4 | Tab 检查 | 检查 GUI 窗口 | Tab 0-4 全部出现（假飞机/假机巢/假电台/剧本处理） |
| 5 | 假电台导入 | 观察启动日志 | 无 "假设备模块导入失败" 错误 |
| 6 | 配置加载 | 在 GUI 左面板选择版本 | `mavlink_config_v*.json` 列表正常显示 |
| 7 | 无 FutureWarning | 检查 stderr | 无 "使用硬编码回退路径" 警告（如果设了环境变量） |

---

> **最后更新**: 2026-07-31
