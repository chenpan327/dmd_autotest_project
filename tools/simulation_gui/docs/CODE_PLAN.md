# integrated_gui — 代码方案

> **包**: `mavlink_monitor/integrated_gui/`（10 模块，原 `integrated_gui.py` 拆分）
> **兼容入口**: `integrated_gui.py`（10 行重定向层）
> **版本**: v3.10
> **行数**: ~3480（总计 11 文件）
> **最后同步**: 2026-09-14
> **用途**: 集成仿真与监控的统一 Qt 控制面板，基于 QTabWidget 管理 UDP 监控 + 假飞机/假机巢/假电台 + 云平台拦截代理 + 剧本处理 + 悬停测试电子围栏
>
> **关联子方案**:
> - [PROJECT_PLAN.md](./PROJECT_PLAN.md) — mavlink_monitor 核心引擎方案
> - [CODE_PLAN_FAKE_AIRPLANE.md](./CODE_PLAN_FAKE_AIRPLANE.md) — 假飞机模块方案
> - [CODE_PLAN_FAKE_NEST.md](./CODE_PLAN_FAKE_NEST.md) — 假机巢模块方案
> - [CODE_PLAN_FAKE_RADIO.md](./CODE_PLAN_FAKE_RADIO.md) — 假电台模块方案
> - [CODE_PLAN_FAKE_CLOUD.md](./CODE_PLAN_FAKE_CLOUD.md) — 云平台拦截代理模块方案

---

## 目录

1. [文件速览](#1-文件速览)
2. [代码分段索引](#2-代码分段索引)
3. [类层次结构](#3-类层次结构)
4. [核心类详解](#4-核心类详解)
5. [关键数据流](#5-关键数据流)
6. [关键算法](#6-关键算法)
7. [外部依赖与引用](#7-外部依赖与引用)
8. [配置与资源文件](#8-配置与资源文件)
9. [已知问题与优化点](#9-已知问题与优化点)
10. [修改指南](#10-修改指南)

---

## 1. 文件速览

> **v2.0**: 原单体 `integrated_gui.py` (3192 行) 拆分为以下包结构：

```
mavlink_monitor/integrated_gui/          (Python 包, ~3100 行总计)
│
├── __init__.py          (~170 行)  路径设置 + 重新导出 + main() 入口
├── __main__.py          (   3 行)  python -m mavlink_monitor.integrated_gui 入口
│
├── _env.py              (~ 90 行)  共享环境：路径设置 + 假设备模块条件导入
│   ├── HAS_FAKE_MODULES, _FAKE_SRC, LogManager, etc.
│   └── 假模块符号占位（None when unavailable）
│
├── _reflection.py       (~415 行)  AST 动态反射
│   ├── SourceInfo, NestedDeviceMeta dataclass
│   ├── _parse_source() — 核心 AST 解析
│   ├── _parse_nested_devices_from_source() — 嵌套设备发现
│   └── _parse_supported_keywords_from_docstring() — docstring 解析
│
├── _types.py            (~430 行)  类型检测 + 值转换 + 控件工厂
│   ├── _detect_kind() — 综合类型判断（6 级优先级链）
│   ├── _coerce(), _parse_list() — 值转换
│   ├── _make_input_widget() — 通用控件工厂
│   └── _discover_update_methods(), _discover_add_params()
│
├── _config.py           (~240 行)  模拟器配置
│   ├── SimConfig dataclass — 单个模拟器的全部元配置
│   ├── _build_sim_configs() — 构建 airplane/nest/radio 配置
│   └── _SocketInterceptor — socket recvfrom 拦截器
│
├── _panels.py           (~870 行)  SimulationPanel — 通用模拟设备控制面板
│   ├── __init__ + 反射信息初始化
│   ├── _build_ui / _build_basic_group / _build_add_group
│   ├── _build_list_group / _build_update_group
│   ├── 槽函数（add/remove/toggle/apply）
│   └── 公开 API（get_fake_node_ips / set_message_injector）
│
├── _nested.py           (~430 行)  NestedDevicePanel — 嵌套设备子 Tab
│   ├── __init__ + _discover_update_methods
│   ├── _build_ui + refresh_targets()
│   └── _on_apply_clicked（全选/单选路由）
│
├── _cloud_panel.py      (~430 行)  CloudProxyPanel — 云平台拦截 Tab（v3.7 新增，v3.9 子 Tab 化）
│   ├── CloudMessageView — HTTP 事件表格 + 详情 HTML 高亮（预留篡改对比区）
│   └── CloudProxyPanel — 子 Tab 容器：「云平台配置」(原页面) + 「TCP 消息监控」
│
├── _tcp_monitor.py      (~330 行)  TcpMonitorPanel — TCP 消息监控子 Tab（v3.9 新增）
│   ├── 独立 MonitorEngine + MonitorModel（与 UDP 监控解耦，gcs_app 宿主）
│   ├── 左栏: 网卡嗅探 / 监控端口(443 可改) / 统计
│   ├── 捕获组[暂停|清空] + 过滤组[SrcIP|SrcIP:Port|DstIP|DstIP:Port|清除|启用]
│   └── QSplitter 5:1 = TraceTable + DetailTree
│
├── _monitor.py          (~560 行)  FullUdpMonitorPanel — UDP 监控 Tab
│   ├── _setup_central（左面板 + 2×2 功能组 + QStackedWidget + 详情树）
│   ├── _on_tick（50ms 轮询，双视图同步更新）
│   ├── 按钮回调（时间切换/视图切换/暂停/清空/过滤）
│   └── inject_raw_message / set_fake_node_ips
│
├── _window.py           (~255 行)  多显示器辅助 + IntegratedMainWindow
│   ├── _parse_gui_launch_args / _pick_screen / _ensure_on_screen
│   ├── IntegratedMainWindow.__init__（Tab 创建 + 假节点 IP 推送）
│   └── closeEvent（关闭清理）
│
└── (兼容层) integrated_gui.py  (10 行)  项目根重定向 → from integrated_gui import ... 仍可用
```

**依赖图（无循环）**:
```
_env  _reflection  _types  _config  _monitor
  ↓       ↓          ↓        ↓         ↓
  └───────┴──────────┴────────┴─────────┴──→ _nested → _panels → _window → __init__
```

---

## 2. 代码分段索引

> **v2.0**: 使用 `Ctrl+G` 跳转到对应文件即可定位功能区域。各模块内部结构见 §1 文件速览。

### 2.1 条件导入与路径 (L1-150)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L1-26 | 文件文档字符串（模块说明 + 运行方式） | — |
| L27-42 | `from __future__` + stdlib imports | `dataclass`, `Path`, `ast`, `re` |
| L44-48 | `_SELF_DIR` 路径设置，加入 `sys.path` | `_SELF_DIR` |
| L52-53 | 硬编码假项目路径 `_FAKE_PROJECT` | `_FAKE_PROJECT`, `_HAS_FAKE_PROJECT` |
| L55-59 | 假项目 mavlink 目录加入 `sys.path` | `_FAKE_MAVLINK_DIR` |
| L61-104 | 导入 mavlink_monitor 模块 + drama_processing（始终可用） | `MonitorController`, `FilterRule`, `LeftPanel`, `FilterBar`, `TraceTable`, `GroupedTraceView`, `DetailTree`, `DramaProcessingPanel` |
| L106-137 | 尝试导入假设备模块（条件导入） | `HAS_FAKE_MODULES`, `FakeAirplane`, `FakeNest`, `FakeR2RadioStation`, `LogManager` |
| L140-150 | `_get_fake_source_dir()` — 返回假设备源文件目录 | `_FAKE_SRC` |

### 2.2 AST 动态反射 (L153-554)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L156-162 | `SourceInfo` dataclass | `module_constants`, `init_attrs`, `init_defaults` |
| L164-172 | `NestedDeviceMeta` dataclass | `cls_name`, `label`, `sender_update_method`, `fields` |
| L175-186 | `_constant_kind()` / `_literal_kind()` — 类型到字符串映射 | `"int"`, `"float"`, `"str"`, `"bytes"`, `"bool"` |
| L206-238 | `_resolve_literal_value()` — AST 节点→Python 值 | — |
| L240-261 | `_resolve_self_assign_value()` — 解析 self.X=param 默认值 | — |
| L263-347 | **`_parse_source()`** — 核心 AST 解析，提取模块常量 + `__init__` self.X 类型 | `SourceInfo` |
| L350-507 | **`_parse_nested_devices_from_source()`** — 发现所有 `_NestedDeviceBase` 子类 | `NestedDeviceMeta` |
| L510-554 | docstring 关键字解析 (`_KEYWORD_HINT_RE`, `_parse_supported_keywords_from_docstring`, `_parse_sphinx_params_from_docstring`) | — |

### 2.3 类型检测与值转换 (L556-883)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L559-566 | 启发式关键字列表 (`_INT_HINT_KEYWORDS`, `_BOOL_HINT_KEYWORDS`, 等) | — |
| L569-591 | `_infer_kind_via_isinstance()` — 源码 AST 扫描 isinstance 调用 | — |
| L593-619 | `_find_param_kind_via_attr()` — 通过 self.X=param 追踪类型 | — |
| L622-676 | **`_detect_kind()`** — 综合类型判断（注册表→init_attrs→路径追踪→默认值→isinstance扫描→名称启发式） | — |
| L678-689 | `_KIND_HINT` — 类型→占位提示文本映射 | — |
| L778-793 | `_resolve_hint()` / `_default_to_text()` | — |
| L795-826 | **`_coerce()`** — 控件值→Python 类型转换（bool/int/float/bytes/list） | — |
| L829-882 | **`_parse_list()`** — 多种列表格式解析（JSON / Python literal / CSV / 空格分隔 / 比特串） | — |

### 2.4 通用 UI 组件 (L699-1013)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L699-776 | **`_CollapseToggle`** — 参数折叠/展开组件（默认显示前5个，其余隐藏） | `add_pair()`, `finalize()`, `_toggle()` |
| L888-931 | `_discover_update_methods()` — 扫描 sender_cls 上所有 `update_xxx` 方法 | — |
| L933-948 | `_discover_add_params()` — 读取 mgr_cls `__init__` 参数 | — |
| L950-1013 | **`_make_input_widget()`** — 根据 kind 构造对应控件（QSpinBox/QDoubleSpinBox/_LimitedCombo(20)/QLineEdit） | — |

### 2.5 配置与数据类 (L1016-1212)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L1016-1037 | **`SimConfig`** dataclass — 单个模拟器的全部元配置 | `key`, `label`, `sender_cls`, `mgr_cls`, `known_param_types`, `param_defaults` |
| L1040-1188 | `_build_sim_configs()` — 构建 airplane/nest/radio 三组配置字典 | `SIM_CONFIGS` |
| L1191-1212 | **`_SocketInterceptor`** — 包装 socket 拦截 recvfrom/sendto 调用 | `recvfrom()`, `sendto()`, `__getattr__()` |

### 2.6 SimulationPanel — 通用模拟设备面板 (L1217-2016)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L1217-1222 | 类文档字符串 | — |
| L1224-1273 | **`__init__`** — 初始化反射信息、持久化字典、嵌套设备面板 | `_senders`, `_transports`, `_update_methods`, `_saved_update_params` |
| L1275-1316 | `_build_ui()` — 整体布局（基础参数 + 添加 + 列表 + update） | — |
| L1318-1374 | `_build_basic_group()` — 模块级常量编辑区（AST 扫描结果） | `_basic_param_widgets`, `_basic_collapse` |
| L1376-1422 | `_build_add_group()` — 添加设备参数区（动态来自 `__init__`） | `_add_param_widgets` |
| L1425-1479 | `_build_list_group()` — 已添加设备列表（IP:Port / Code / 状态 / 上线/下线） | `_list_devices`, 1s 定时刷新状态 |
| L1481-1520 | `_build_update_group()` — 调整参数区（目标选择 + update 方法选择 + 动态表单），下拉框使用 `_LimitedCombo(20)` 限制弹窗高度 | `_combo_target`, `_combo_update`, `_params_scroll` |
| L1522-1526 | `_make_input()` — 内部控件工厂包装 | — |
| L1529-1546 | `_save_current_form_values()` — 表单值写入持久化字典 | — |
| L1548-1550 | `_load_saved_values()` — 读取已保存参数值 | — |
| L1553-1588 | `_get_dynamic_choices()` / `_get_airplane_ip_choices()` / `_get_nest_index_choices()` | — |
| L1599-1641 | **`_refresh_update_params()`** — 切换 update 方法时重建参数表单（保存旧值→清空→加载新参数） | — |
| L1643-1646 | `_on_target_changed()` — 目标设备切换 | — |
| L1649-1666 | `_on_basic_apply_clicked()` — 基础参数写到源文件模块 | `importlib.import_module` + `setattr` |
| L1668-1703 | **`_on_add_clicked()`** — 创建 mgr_cls 实例，打补丁拦截 socket（v1.3: + sender.set_msg_injector 传播） | `_patch_transport_socket()` |
| L1705-1737 | `_on_remove_clicked()` — 停止线程 + 关闭 transport + 列表移除 | — |
| L1740-1753 | `_on_toggle_online_clicked()` — 上线/下线切换 | — |
| L1755-1773 | `_on_offline_all_clicked()` / `_on_online_all_clicked()` | — |
| L1776-1809 | `_is_sender_online()` / `_stop_sender_thread()` / `_start_sender_thread()`（v2.2: `_is_sender_online` 改为线程存活优先；`_stop_sender_thread` join 超时改为 5s） | — |
| L1811-1862 | **`_on_apply_clicked()`** — 调用目标 sender 的 update 方法（支持全体/单选） | — |
| L1865-1887 | `_refresh_device_list()` / `_refresh_target_combo()` | — |
| L1888-1936 | 列表行渲染（`_populate_row`, `_refresh_row_status`, `_set_action_button`） | — |
| L1938-1946 | `_refresh_status_only()` / `_refresh_nested_panels()` | — |
| L1949-2022 | **公开 API**: `get_fake_node_ips()` / `get_senders()` / `set_message_injector()` / `_patch_transport_socket()`（v1.3: `set_message_injector` 新增 sender.set_msg_injector 传播；v2.2: 支持电台 _radio.sock 嵌套检测；v2.4: 电台外发 sendto 拦截 + gcs 地址改从 _radio 读取） | — |

### 2.7 NestedDevicePanel — 嵌套设备面板 (L2021-2416)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L2021-2026 | 类文档字符串 | — |
| L2028-2053 | **`__init__`** — 扫描嵌套设备类 update_xxx 方法 | `_meta`, `_nested_cls`, `_target_keys` |
| L2057-2133 | `_scan_update_methods_on_cls()` / `_discover_update_methods()` | 轻型飞机额外合并 `_FakeAirplaneMessageSender` 方法 |
| L2136-2174 | `_build_ui()` — 目标下拉 + update 方法下拉 + 参数滚动区 + 应用按钮，下拉框使用 `_LimitedCombo(20)` 限制弹窗高度 | `_combo_target`, `_combo_update`, `_params_scroll` |
| L2176-2195 | `_save_current_form_values()` / `_load_saved_values()` | — |
| L2198-2223 | `_get_dynamic_choices()` / `_get_instance_key_choices()` | — |
| L2226-2270 | **`_refresh_update_params()`** — 重建参数表单（优先使用 `_UPDATABLE_FIELDS` 声明的类型） | — |
| L2277-2310 | `refresh_targets()` — 遍历所有 sender 发现嵌套实例 | `instance_mode: "dict"` vs `"single"` |
| L2312-2416 | **`_on_apply_clicked()`** — 全选（遍历所有 sender 的所有实例） vs 单选 | — |

### 2.8 FullUdpMonitorPanel — UDP 监控面板 (L2421-2949)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L2421-2430 | 类文档字符串 | — |
| L2432-2447 | **`__init__`** — 创建 MonitorController + 初始化假节点状态 | `_ctrl`, `_fake_ips`, `_show_fake_only` |
| L2450-2623 | **`_setup_central()`** — 完整布局（LeftPanel + 2×2功能组 + QStackedWidget双视图 + DetailTree + 假节点状态栏） | — |
| L2459-2465 | 左面板: `LeftPanel`（配置+网卡+统计） | `on_start_nic`, `on_stop_nic`, `on_config_changed` 信号 |
| L2473-2476 | 过滤栏: `FilterBar` | — |
| L2479-2564 | **2×2 功能组网格**（视图/数据源/捕获/过滤） | 各种按钮 + QGridLayout |
| L2568-2593 | QStackedWidget 双视图 + QSplitter(vertical) | `_trace_table` ↔ `_grouped_view` 切换 |
| L2595-2622 | 底部假节点状态栏 | `_fake_info_label`, `_chk_fake_only` |
| L2627-2630 | `_setup_timer()` — 50ms QTimer | — |
| L2635-2689 | **`_on_tick()`** — 核心轮询（增量拉取→自适应刷新率→批量/逐条推送→IP收集→统计刷新→假节点统计）v2.3: 自适应刷新率 + 批量 add_records | — |
| L2694-2706 | `_on_start_nic()` / `_on_stop_nic()` — 网卡嗅探控制 | — |
| L2711-2725 | `_on_config_changed()` — 配置变更→msgid选项更新 | — |
| L2730-2750 | `_load_command_183_config()` / `_load_radio_config()`（v3.0: 电台配置路径优先 `resources/DavMessage.proto`，回退协议 XML） | `_RESOURCES_DIR`, `get_radio_message_xml()` |
| L2755-2784 | 按钮回调: 时间切换 / 视图切换 / 真实目标IP / 来源列 | — |
| L2786-2800 | 显示上限 / 暂停 / 清空 | — |
| L2807-2823 | `_on_nest_toggle()` / `_on_radio_toggle()` — 数据源开关 | — |
| L2828-2841 | `_on_filter_change()` — 过滤规则构建（msgid/srcip/dstip/relayip） | — |
| L2843-2855 | `_on_record_clicked()` — 点击行→lazy parse→DetailTree | — |
| L2857-2877 | `_rebuild_grouped_view()` / `_rebuild_trace_table()` — 视图全量重建 | — |
| L2882-2894 | **`inject_raw_message()`** — 假节点原始消息注入引擎（v2.4: DAV 帧分流到 radio parser） | `_process_raw_packet()`, `inject_radio_packet()` |
| L2896-2908 | `set_fake_node_ips()` / `_update_fake_info_label()` | — |
| L2910-2919 | `_update_fake_stats()` — 最近1000条中匹配假节点IP的计数 | — |
| L2921-2939 | `_on_fake_only_changed()` — "仅显示假节点消息"开关 | — |
| L2944-2948 | `shutdown()` — 停止 radio / UDP / engine | — |

### 2.9 多显示器 + 主窗口 + 入口 (L2954-3192)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L2954-2988 | `_parse_gui_launch_args()` — 解析 `--screen` / `--pos` / `--list-screens` + 环境变量 | — |
| L2991-3015 | `_pick_screen()` / `_format_screens()` — 屏幕选择 | — |
| L3018-3032 | `_ensure_on_screen()` — 窗口不可见时回退到主屏居中 | — |
| L3038-3043 | `IntegratedMainWindow` 类文档 | — |
| L3045-3104 | **`__init__`** — 创建 LogManager → SIM_CONFIGS → Tabs → StatusBar | 核心入口 |
| L3085-3087 | Tab 0: `FullUdpMonitorPanel`（始终存在） | — |
| L3091-3104 | Tab 1-3: `SimulationPanel`（条件创建），注入 `set_message_injector` | — |
| L3107-3110 | Tab 4: `DramaProcessingPanel`（剧本处理，条件创建），航点函数已独立无需 sender | **新增** |
| L3112-3116 | 2s QTimer 定时收集假节点 IP → 推送 UDP 面板 | — |
| L3117-3122 | 多屏几何定位 + StatusBar 就绪消息 | — |
| L3124-3144 | `_apply_launch_geometry()` — 多屏窗口定位 | — |
| L3146-3148 | `showEvent()` — 首次显示后回调确保在可见屏内 | — |
| L3150-3154 | `_collect_and_push_fake_ips()` — 收集假节点IP→推送 | — |
| L3157-3169 | **`closeEvent()`** — 逐个 panel.shutdown() + UDP 面板 shutdown | — |
| L3172-3192 | `main()` — 入口: QApplication → IntegratedMainWindow → app.exec() | — |

---

## 3. 类层次结构

```
QMainWindow
  └── IntegratedMainWindow                          (L3038)
        ├── ._tabs: QTabWidget
        │     ├── [Tab 0] FullUdpMonitorPanel        (L2421)  ← 始终存在
        │     ├── [Tab 1] SimulationPanel("airplane") (L1217)  ← 条件
        │     ├── [Tab 2] SimulationPanel("nest")                 ← 条件
        │     │     └── nested: NestedDevicePanel[]   (L2021)  ← 子Tab
        │     └── [Tab 3] SimulationPanel("radio")                 ← 条件
        ├── ._log_manager: LogManager
        └── ._sim_configs: dict[str, SimConfig]

QWidget
  ├── SimulationPanel                               (L1268)
  │     ├── _config: SimConfig                      (L1018, dataclass)
  │     ├── _src_info: SourceInfo                   (L156, dataclass)
  │     ├── _senders: list[_FakeXxxSender]
  │     ├── _transports: list[FakeXxx]
  │     └── _nested_panels: dict[str, NestedDevicePanel]
  │
  ├── DramaProcessingPanel                         (mavlink_monitor/gui/drama_processing.py)
  │     ├── WaypointParseComparePanel               — 航点解析对比子Tab
  │     ├── WaypointTamperPanel                     — 航点篡改子Tab
  │     ├── DramaFrameInspectorPanel                — 帧数据检查子Tab（新增）
  │     ├── WaypointTrackComparePanel               — 航迹对比子Tab（v3.5 新增）
  │     └── [本地] Drama3_pb2.py                    — protobuf 7.x 兼容 (string→bytes)
  │
  ├── NestedDevicePanel                             (L2021)
  │     ├── _meta: NestedDeviceMeta                 (L164, dataclass)
  │     ├── _nested_cls: type
  │     └── _target_keys: list[(int, Any)]
  │
  ├── CloudProxyPanel                               (_cloud_panel.py, v3.7 新增)
  │     ├── ._sim_panel: SimulationPanel(cloud cfg)
  │     ├── ._view: CloudMessageView                — HTTP 事件表格 + 详情 HTML
  │     └── ._poll_timer: QTimer(50ms)
  │
  ├── FullUdpMonitorPanel                           (L2421)
  │     ├── _ctrl: MonitorController                (mavlink_monitor.core.controller)
  │     ├── _left_panel: LeftPanel
  │     ├── _filter_bar: FilterBar
  │     ├── _trace_table: TraceTable
  │     ├── _grouped_view: GroupedTraceView
  │     ├── _detail_tree: DetailTree
  │     └── _view_stack: QStackedWidget
  │
  └── _CollapseToggle                               (L699)  ← 通用折叠组件

辅助 dataclass:
  SimConfig                                         (L1018)
  SourceInfo                                        (L156)
  NestedDeviceMeta                                  (L164)

辅助类:
  _SocketInterceptor                                (L1194)  ← socket 包装器
```

---

## 4. 核心类详解

### 4.1 IntegratedMainWindow (L3038-3169)

**职责**: 顶层窗口，QTabWidget 管理 1-4 个 Tab。

**初始化流程**:
1. 检查 `HAS_FAKE_MODULES` → 决定窗口标题 + 是否创建 LogManager
2. 构建 `_sim_configs`（仅在假模块可用时）
3. 创建 `_tabs: QTabWidget`
4. Tab 0 = `FullUdpMonitorPanel()` — 始终创建
5. Tab 1-3 = `SimulationPanel(cfg, log_manager, status_setter)` — 条件创建
   - 每个 panel 调用 `set_message_injector()` 注入消息回调，将假节点收到的数据转发到 UDP 监控
6. 启动 2s QTimer → `_collect_and_push_fake_ips()`
7. 连接刷新假节点 IP 按钮

**关闭流程** (L3157-3169):
```python
def closeEvent(event):
    for panel in self._panels.values():
        panel.shutdown()       # 停止线程 + 关闭 transport
    self._udp_panel.shutdown() # 停止 radio/UDP/engine
```

**关键属性**:
| 属性 | 类型 | 说明 |
|------|------|------|
| `_has_fake` | `bool` | 假模块是否导入成功 |
| `_log_manager` | `LogManager \| None` | 日志管理器 |
| `_tabs` | `QTabWidget` | Tab 容器 |
| `_udp_panel` | `FullUdpMonitorPanel` | UDP 监控面板（Tab 0） |
| `_panels` | `dict[str, SimulationPanel]` | `{"airplane": ..., "nest": ..., "radio": ...}` |
| `_drama_panel` | `DramaProcessingPanel \| None` | 剧本处理面板（Tab 4），仅当 HAS_FAKE_MODULES |
| `_sim_configs` | `dict[str, SimConfig]` | 模拟器配置 |

### 4.1a DramaProcessingPanel (mavlink_monitor/gui/drama_processing.py)

**职责**: 剧本处理 Tab，含三个子 Tab。航点解析/对比函数已完全剥离为模块级独立函数，
不再依赖假飞机 sender（`parse_waypoints_from_bin` / `visualize_drama_3d` / `visualize_drama_compare`）。

**protobuf 7.x UTF-8 兼容层 + schema 扩展** (v1.3 → v2.7):

- ~~本地副本~~ 已重建为二进制 descriptor 文件 `Drama3.desc`（3526 bytes）
- `Drama3_pb2.py` 从 `.desc` 文件加载 descriptor → `AddSerializedFile()` 注册 → `GeneratedProtocolMessageType` 创建 Python 消息类
- **完整匹配 C# `DramaProto.cs`**：35 个消息类型，Drama3 12 字段，Drone 21 字段
- 新增 16 个消息类型：`DramaRangeInfo`/`LaserAreaProto`/`Vector3Proto`/`PayloadGimbalVector`/`PayloadParachute*`/`PayloadFoldLantern*`/`PayloadKongMingLantern*`/`PayloadPeachLantern*`/`PayloadFishLantern*`/`PayloadConfetti*`
- 所有 string 字段保持为 bytes 类型（protobuf 7.x UTF-8 兼容）
- `drama_reader.py` 中的 `_safe_str()` 工具函数继续负责 bytes→str 安全解码

**子 Tab 0 — 航点解析对比 (WaypointParseComparePanel)**:
- 选择 bin 文件 → 列表显示
- 「航点解析」按钮：逐次对每个选中文件调用模块级 `visualize_drama_3d()`，完成后自动打开最后一个 HTML
- 「航点对比」按钮：对恰好 2 个文件调用模块级 `visualize_drama_compare()`，完成后自动打开 HTML
- 无需假飞机 sender，可独立使用

**子 Tab 1 — 航点篡改 (WaypointTamperPanel)**:
- 加载 .drm 剧本文件（使用 DramaReader/DatReader 解析）
- 兼容全零帧 .drm（自动按索引生成 0, 1, 2, ... 顺序帧号）
- 显示飞机数量、每架飞机的航点数
- 表头行：全选勾选框 + 列标题（帧 / 飞机高度 / 基准飞机 / 被修改飞机 / 原本距离 / 目标距离(m) / 与其他飞机最小距离），表头文字通过 `padding-left:4px` 与下方控件左边缘对齐
- 列间距分两档（1x=8px / 2x=16px），帧→高度 1x，高度/基准飞机/被修改飞机/原本距离之间 2x，其余间隙 1x
- 「＋ 添加一处修改」按钮添加条目，「删除修改」按钮删除所有已勾选条目
- 每条目（_TamperEntry，QFrame 表格线效果）：勾选框 / 帧下拉按钮 / 飞机高度 / 基准飞机下拉按钮 / 被修改飞机下拉按钮 / 原本距离 / 目标距离 / 与其他飞机最小距离
- 帧/基准飞机/被修改飞机 使用 `_MultiSelectButton(single_select=True)`（与 UDP 监控 MsgID 过滤同款样式），点击弹出 QMenu + 勾选列表，单选模式下勾选新项自动取消其他项，按钮文字仅显示选中值（如 `"0"` / `"飞机 1"`），无多余前缀；其余下拉框（如 _make_input_widget 中的 bool/choices）仍使用 `_LimitedCombo(QComboBox)`
- 基准飞机为距离参照（不动），被修改飞机沿直线方向移动至目标距离
- 「与其他飞机最小距离」计算时排除被修改飞机自身和基准飞机
- 飞机航点数显示：最多展示前 10 架详情，超出显示「…等 N 架飞机」
- **输出机制 (v1.4)**：「确定修改并输出」→ `_try_write_drm_protobuf(modified_wp)` 直接解析原始 .drm protobuf，在对象上修改 positionKeyFrames 后序列化 → ZIP 压缩 → AES 加密 → 输出 .drm。此方式保全所有 protobuf 字段，避免 dict 重建导致的数据丢失；若 protobuf 不可用则回退到 JSON 输出

**子 Tab 2 — 帧数据检查 (DramaFrameInspectorPanel)** (v2.4 新增, v2.5 完善, v2.6 双Tab):
- 选择 .drm 文件 → 「加载解析」按钮
- AES-CBC 解密 → ZIP 解压 → 解析 protobuf `Drama3` 消息
- 数据摘要区：文件名、飞机数量、帧范围、字段路径总数（含缺失）
- **双 Tab 结构**：
  - **Tab "按帧类型分类"**：合并同类项视图 + `Drama3` / `Drama3_Not_Exist` 双根节点
  - **Tab "按飞机分类"**：每个 drone 独立分支（`drone_N (id=N)`），非 drone 字段与 Tab1 相同，**无 Not_Exist**
- QTreeWidget 四列：字段路径 | 类型 | 出现次数 | 取值范围/值
- **双根节点**（仅 Tab 按帧类型分类）：`Drama3`（已有字段）+ `Drama3_Not_Exist`（schema 中定义但数据中未出现的字段）
- **完整 C# schema**：内置 `DramaProto.cs` 全部 12 个顶层消息类型定义（~30 个 message 类型总计），覆盖所有字段
- **字段合并同类项**：多架飞机的同名字段合并为一条路径，显示总出现次数和取值范围
- **缺失字段**：与 schema 对比，未出现的字段放在 `Drama3_Not_Exist` 下以灰色斜体树状展示（count=0）
- **递归层跳过标量**：子消息递归检查时仅报告缺失的 message 字段（proto3 默认值=0 无法区分「未设置」与「默认值」）
- **pb2↔C# 名称映射**：旧 pb2 DESCRIPTOR 字段名自动翻译为 C# 字段名（如 pb2 `frame`→schema `frameIndex`, pb2 `dramaId`→schema `dramaMissionId`）
- 使用 protobuf 反射 API（`ListFields()` + `DESCRIPTOR`）泛型遍历，不依赖硬编码字段路径
- 标量值收集上限 100 个（防止 OOM）
- **数值范围格式化 (v2.7 改进)**：
  - 单值 → `value`（count=1）或 `value (count)`（count>1），明确显示出现次数
  - 2-5 unique 值 → `v1 (n1), v2 (n2), ...` 显示每个值的出现次数
  - >5 unique 值 → 退回到范围显示：整数 `lo ~ hi`；浮点 `lo.xxx ~ hi.xxx`
- **嵌套 repeated message 字段合并修复 (v2.7)**：`_collect_message_stats` 跨 message 合并标量子节点时，scalar_values 使用 `sc2.scalar_values`（不是 `sub_child.scalar_values`），修复 `lazerKeyFrame[].lazers[].b` 等深层嵌套字段 scalar_values 不累加的 BUG
- **proto3 默认值字段补齐 (v2.7.2)**：新增 `_fill_proto3_default_values`，对 ListFields() 未返回的标量字段（如 OFF 帧 lazer 的 `r=0,g=0,b=0`）补齐默认 0 值；否则这些字段会被遗漏，导致取值分布缺失一半
- **3 层嵌套合并 (v2.7.2)**：扩展递归合并到第 3 层（如 `lazerKeyFrame[].lazers[].b`），原 2 层合并仅首个 drone 的 b 字段被统计
- **示例**：`lazerKeyFrame-lazers-b` v2.7 修复后显示 `25 (1200)`；v2.7.2 进一步补齐 `0 (50)`，最终显示 `0 (50), 25 (50)`

**子 Tab 3 — 航迹对比 (WaypointTrackComparePanel)** (v3.5 新增):
- **Box1「Bin 文件选择」**：最多 2 个 bin 文件，展示区固定高度容纳 2 行；标题文本右侧 4 个按钮（选择文件 / 清空列表 / 剧本解析 / 剧本对比）；选择文件逻辑抽为 `_append_selected()`（上限 2 个，超限弹提示）
- **Box2「解析结果 HTML 列表」**：QTableWidget 三列（文件链接 / 生成时间 / 批次）；点击文件名用 `os.startfile` 打开 HTML；同一批次（同一次剧本解析的多个 bin）的行用相同背景色（`_BATCH_COLORS` 调色板按批次轮换）+「批次 N」标识
- **「剧本解析」**：对每个选中 bin 调用模块级 `visualize_drama_playback()`，通过 `_DramaWorker(task_type="playback")` 后台生成带帧播放进度条的 3D 航点+灯光 HTML，结果进入 Box2 列表
- **「剧本对比」**（v3.6 实现，v3.6.1 修正对齐帧率）：对恰好 2 个选中 bin 做**时间对齐对比**（不同起飞时间剧本）。从文件名解析两个剧本起飞绝对时间（`yyyymmdd_hhmmss` 或 `yyyymmdd_hhmmss.mmm`，无时间戳则弹提示），以**早起飞剧本帧为时间基准**（帧号恒整数）、**晚起飞剧本线性插值**到该网格（灯光取 floor 帧持续值不插值），逐时间点（步长 1/pointFps）计算两机实际距离 + 灯光 RGB 一致性；经 `_DramaWorker(task_type="compare_timeline")` 后台调用模块级 `visualize_drama_compare_timeline()`，结果进入 Box2 列表。`_append_selected` 用规范化路径（`normcase`+`abspath`）去重，追加绝不删除已选项
- **模块级新函数**：`parse_waypoints_lights_from_bin()` 复用 `parse_waypoints_from_bin` 解析管线，额外提取每帧灯光 (r/g/b) → `{frames, point_fps, payload_fps, ...}`；`visualize_drama_playback()` 基于 `visualize_drama_3d` 视觉风格（轨迹线/起点/终点/原点/轴范围），航点 marker 颜色=该帧灯光 RGB，标题含 pointFps/payloadFps
  - **时间对齐对比函数（v3.6 / v3.6.1 / v3.6.2 / v3.6.3）**：`parse_timestamp_from_name()` 解析文件名时间戳 → `datetime`（毫秒可选，正则 `_TS_RE`）；`compare_drama_timelines(early, late, early_t0, late_t0, payload_fps, point_fps)` 纯函数按绝对时间对齐——**frames 帧号是 payload 帧索引，偏移 `offset = 起飞时间差 × payload_fps`**（起点帧 `ceil(offset)`，终点=公共重叠区间，**对比点每个 payload 帧一个**，与 Tab0「航点解析」`parse_waypoints_from_bin` 疏密一致），晚起飞帧号 `j=k-offset` 小数时对相邻帧线性插值（灯光取 floor 帧持续值），返回每点 `{frame, rel_time, dist, light_ok, ok, early_pos, late_pos, early_light, late_light}`（`ok` = 距离<`_DIST_TOL`(0.005m) 且灯光一致）；`visualize_drama_compare_timeline()` 生成 HTML——左侧竖排两个折线图（两机距离 / 灯光一致性 1/0，横轴=相对秒），右侧 3D 场景（**原剧本完整轨迹/航点显示全部 payload 帧**：后起飞时刻前[帧<offset]淡灰、对比段正常灰，**position 帧航点用大菱形、普通 payload 帧用小圆点**区分；晚起飞剧本航点绿=匹配/红=差异，航线按航点状态分段着色，None 分隔 + line.color 数组；起点/终点/原点与 `visualize_drama_playback` 视觉一致，标题含 payloadFps/pointFps）并带**播放控制**——底部播放/暂停按钮 + 1x~5x 速率 + 时间 slider（3D 高度 `calc(100vh-56px)!important` 留出控制条），对比点数据紧凑 JSON 内嵌（`points` 数组），JS `Plotly.restyle` 仅更新「当前帧」两机高亮 markers 与连线（trace 9/10/11），未播放/暂停时整个航迹对比保持可见。新增 `tests/test_drama_compare_timeline.py` 14 用例（时间戳/整数偏移/非整数插值/payload_fps 偏移/每帧对比/灯光持续值/阈值边界/HTML 结构/播放控件/疏密一致/面板追加）
  - **v2 优化（2026-08-24）**：原实现用 plotly frames/slider 全量嵌入 8331 帧动画 → HTML 9.7MB、拖动卡顿。改为：plotly 生成静态 base 场景（未途径线亮蓝 / 已途径线淡灰 / 当前帧 markers / 起终点 / 原点）+ 位置帧（1667）与灯光帧（8331）数据以紧凑 JSON 数组完整内嵌（`posLen`/`lightLen` 自描述，位置帧完全保留）+ **原生 HTML range slider** + JS `Plotly.restyle` 运行时更新（拖动流畅，无 O(N²) 分段数据）+ **1x~5x 播放速率** select（`setInterval` 间隔 = `1000/(payloadFps×速率)`）+ **已途径/未途径航线**由 JS 按当前帧实时构建分段（淡灰/亮蓝），HTML 降至 ~5MB。新增 `tests/test_drama_track_compare.py` 的 4 个 playback 用例（posLen/lightLen 保留、速率选项、已途径 trace、体积）
  - **v3.5.2 视觉优化（2026-08-24）**：起点/终点航点图标缩小为当前的 25%（marker `size` 10→2.5，边框 width 2→1）；3D 坐标区填满页面——`config.responsive=True` + CSS `#plotly_playback{height:calc(100vh-56px)!important}`（底部控件高 56px），`html/body` 高度 100%
  - **v3.5.3 视觉优化（2026-08-24）**：当前帧航点 marker 再缩小为 50%（`size` 8→4），原点保持 8

### 4.2 FullUdpMonitorPanel (L2421-2949)

**职责**: 照搬 `MainWindow` 的完整监控布局。包含配置加载、网卡嗅探、双视图（时间序/分组）、字段详情、假节点消息感知。

**布局结构**:
```
QSplitter(Horizontal)
├── LeftPanel (fixed 290px)     ← 配置 + 网卡 + 统计
└── QWidget (right)
    ├── [2×2 功能组网格]
    │   ├── 视图: [时间切换] [分组视图] [真实目标IP] [来源] [显示上限]
    │   ├── 数据源: [机巢开关] [电台开关]（v3.9:「地面站应用」迁至云平台拦截
    │   │            Tab 的「TCP 消息监控」子 Tab）
    │   ├── 捕获: [暂停] [清空]
    │   └── 过滤: FilterBar
    ├── QSplitter(Vertical)
    │   ├── QStackedWidget
    │   │   ├── TraceTable           ← 时间序视图 (index 0)
    │   │   └── GroupedTraceView     ← 分组视图   (index 1)
    │   └── DetailTree
    └── 假节点状态栏: [IP列表] [收到计数] [仅显示假节点] [刷新]
```

**与 MainWindow 的差异**:
- 无 File 菜单（导出功能由外部提供）
- 增加数据源开关（机巢/电台）
- 增加假节点消息注入与"仅显示假节点"过滤
- 视图切换时全量重建（`_rebuild_*`）

**_on_tick 核心循环** (L2635-2689, v2.3 优化):
```
1. 检查 _ctrl.is_running
2. 如果未暂停:
   a. _ctrl.get_new_records() → 增量拉取
   b. 自适应刷新率：单 tick >200 条 → 降低刷新率(50→200ms)；<50 条 → 恢复(50ms)
   c. 向当前活跃视图添加：TraceTable 批量 add_records() / GroupedTraceView 逐条 add_record()
   d. trim_rows / trim_messages(display_limit)
   e. 检测 was_at_bottom → scroll_to_bottom()
   f. 收集新 IP → 更新 FilterBar 下拉选项
3. 统计刷新 → left_panel.update_stats(...)
4. 假节点统计 → _update_fake_stats()
```

**消息注入链路** (L2882-2894, v2.4: DAV 帧分流):
```python
def inject_raw_message(data, src_ip, src_port, dst_ip, dst_port):
    # 电台 DAV 帧（0xA5 同步字）走 radio parser，绕过 MAVLink 魔数检查
    if data and data[0] == 0xA5:
        self._ctrl.inject_radio_packet(data, src_ip, src_port, dst_ip, dst_port)
        return
    # 其余走 MAVLink parser，绕过网卡嗅探，直接写入 MonitorModel
    self._ctrl.engine._process_raw_packet(
        data, src_ip, src_port, dst_ip, dst_port,
        node_id=f"fake_{dst_ip}", source_type="fake",
    )
```

`MonitorController.inject_radio_packet()`（controller.py）复用 `engine._radio_node.parser.to_message_record()`，
以 `source_type="radio"` 直接写入 MonitorModel，与网卡/端口监听路径解耦。

### 4.3 SimulationPanel (L1217-2016)

**职责**: 通用模拟设备控制面板。通过 `SimConfig` 注入具体类引用，反射生成所有控件。FakeAirplane / FakeNest / FakeRadio 共用此面板。

**四区域布局**:
```
┌─ 基础参数 (模块级常量, AST 动态扫描) ────────────┐
│  [常量名] <类型> = module-level  [输入控件]        │
│  ...                                              │
│  [应用基础参数 (写入源文件模块)]                    │
├─ 添加设备 (参数动态来自 Mgr.__init__) ────────────┤
│  [参数名] <类型>  [输入控件]                       │
│  ...                                              │
│  [添加]                                            │
├─ 已添加设备 ─────────────────────────────────────┤
│  # | IP:Port | Code (Serial) | 状态 | 操作        │
│  [移除选中] [刷新列表] [全体下线] [全体上线]       │
├─ 调整参数 (走 update_xxx 路径) ──────────────────┤
│  目标设备: [全体 ▼]  update 方法: [update_xxx ▼]  │
│  [参数名] <类型>  [输入控件]                       │
│  ...                                              │
│  [应用 update]                                     │
└──────────────────────────────────────────────────┘
```

**初始化反射信息** (L1251-1260):
```python
self._src_info = _parse_source(config.source_file, ...)  # AST 解析
self._init_attrs = self._src_info.init_attrs
self._update_methods = _discover_update_methods(config.sender_cls, ...)
self._add_params = _discover_add_params(config.mgr_cls)
```

**参数持久化机制** (L1246, L1529-1550):
```python
# 数据结构: {target_key: {method_name: {param_name: value}}}
self._saved_update_params: dict[str, dict[str, dict[str, Any]]] = {}
```
- 切换 update 方法时：先 `_save_current_form_values()` → 清空表单 → 重建新方法参数 → 从 `_loaded_saved_values()` 恢复
- 切换目标设备时：同上
- 应用时：同时持久化到当前 target 的 `_saved_update_params`

**Socket 拦截** (L1971-2001, v2.2: 支持电台嵌套 sock; v2.4: 外发 sendto 拦截; v3.1: 电台改走 set_msg_injector):
```python
def _patch_transport_socket(transport, callback):
    # 假电台（_FakeRadioSender）：消息注入统一由 set_msg_injector 自包装完成
    #   （处理 socket 延迟创建），此处直接 return，不安装 _SocketInterceptor
    if _FakeRadioSender is not None and isinstance(transport, _FakeRadioSender):
        return
    # 假飞机/假机巢：替换 transport.sock 为 _SocketInterceptor，拦截 recvfrom
    #   recvfrom 时回调: callback(data, gcs_ip, gcs_port, dst_ip, dst_port)
    #   gcs 来自 ground_station_ip:ground_station_port（172.16.200.1:14550/14650）
```

### 4.3a CloudProxyPanel (mavlink_monitor/integrated_gui/_cloud_panel.py, v3.7 / v3.9 子 Tab 化)

**职责**: 云平台拦截 Tab —— **子 Tab 容器**（v3.9）：
```
CloudProxyPanel
└── QTabWidget「FC_SUB_TABS」
    ├── 子 Tab「云平台配置」—— 原页面 (QSplitter 3:2)
    │     ├── SimulationPanel(cloud)（基础参数 + 添加设备 + 列表 + update 参数）
    │     └── CloudMessageView（HTTP 事件表格 + 详情 HTML，预留篡改对比区）
    └── 子 Tab「TCP 消息监控」—— TcpMonitorPanel（_tcp_monitor.py）
```

**CloudMessageView**（配置页下半部）:
- 工具栏: [暂停/继续] [清空] [仅看广告接口] [事件计数]
- QTableWidget 7 列: # | 时间 | 类型 | 方法 | 路径 | 状态 | 摘要
  （类型: 地面站→云 / 云→地面站 / GUI篡改(预留) / 代理错误）
- QTextBrowser 详情：gcs_request 头摘要+body 高亮 / cloud_response 信封+
  promotion 条目 / tampered_response（预留）json_diff 字段级对比高亮

**SimulationPanel API 委托**: `get_senders` / `set_message_injector` /
`shutdown`（停轮询 + tcp/sim shutdown）；`get_fake_node_ips()` 恒空。

### 4.3b TcpMonitorPanel (mavlink_monitor/integrated_gui/_tcp_monitor.py, v3.9)

**职责**: 云平台 TCP 消息监控子 Tab —— 「地面站应用」TCP/TLS 监控的
独立宿主（从 UDP 消息监控 Tab 迁出，独立 `MonitorEngine + MonitorModel`
与 UDP 监控完全解耦；`parser=None` 安全——GCS 记录构造不走 parser）。

**布局**:
```
QSplitter(Horizontal)
├── 左栏: [网卡嗅探] 网卡下拉+⟳+▶开始嗅探/⏹停止 | [监控配置] 端口 QSpinBox(443)+应用
│         [统计] TCP包/记录/Errors/Buffer/Uptime
└── 右区: [捕获] || 暂停 | 清空     [过滤] SrcIP | SrcIP:Port | DstIP | DstIP:Port | 清除 | ✓启用过滤
    └── QSplitter(Vertical, 5:1) = TraceTable(时间序) + DetailTree(详情)
```

**数据链路**: `_on_toggle_sniff` → engine.set_interface + set_gcs_app_listener +
start_gcs_app（gcs sniffer，见 v3.8 条目）；`_poll_timer`(50ms) `_on_tick` →
`model.get_since(last_seq)` → 收集过滤候选 → 过滤（启用时）→
`trace_table.add_records`；点击行 → `on_record_clicked(record)` →
`detail_tree.show_fields`（gcs 记录 fields_parsed=True，不经 controller）。

**四维过滤**（自建，**OR 并集语义**（v3.10）：任一非空条件命中即显示，全空显示
全部；端口组合 FilterRule 不支持）: SrcIP / `SrcIP:Port`(`ip:port` 精确) /
DstIP / `DstIP:Port`；候选自动收集（每 combo 上限 50 项）；清除/启用切换时
`_rebuild_table()` 从 model 快照全量重建。**注意**：editable combo 程序化设值
须用 `setEditText()`（`setCurrentText` 对不在 items 中的文本可能不更新编辑框）。
运行中改端口 → 自动停止并以新端口重启嗅探。**表格内建工具栏不创建**
（`TraceTable(show_toolbar=False)`，v3.10）—— 暂停/清空由外层捕获组提供，
`scroll_paused` setter 对无按钮场景做了存在性保护（UDP 监控的 TraceTable
不受影响，默认 show_toolbar=True）。

### 4.4 NestedDevicePanel (L2021-2416)

**职责**: 单个嵌套设备类型（如 `_NestAirplane`, `_NestBox`）的控制面板，嵌入在机巢 Tab 的子 Tab 中。

**与 SimulationPanel 的区别**:
- 目标设备是嵌套的（如"巢#0 / 172.16.3.168"），而非 sender 层级
- 参数类型优先使用 `_UPDATABLE_FIELDS` 声明，其次启发式推断
- update 方法扫描自身类 + 必要时合并 `_FakeAirplaneMessageSender` 方法
- 全选时遍历所有 sender 的所有嵌套实例

### 4.5 辅助 dataclass

#### SimConfig (L1018-1037)
```python
@dataclass
class SimConfig:
    key: str                          # "airplane" | "nest" | "radio"
    label: str                        # Tab 标题
    source_file: Path                 # 源文件路径
    sender_cls: type                  # _FakeXxxMessageSender
    mgr_cls: type                     # _FakeXxxSenders
    transport_cls: type               # FakeXxx
    mgr_senders_attr: str             # "fake_airplane_senders" 等
    mgr_transports_attr: str          # "fake_airplanes" 等
    aid_prefix: str                   # "FA_" | "FN_" | "FR_"
    known_param_types: dict           # 已知参数→类型映射
    param_choices: dict               # 参数→下拉选项映射
    param_defaults: dict              # 参数→默认值
    has_nested_devices: bool          # 仅 nest 为 True
```

#### SourceInfo (L156-162)
```python
@dataclass
class SourceInfo:
    module_constants: dict[str, tuple[Any, str]]  # name -> (value, kind)
    init_attrs: dict[str, str]                     # self_attr -> kind
    init_defaults: dict[str, Any]
```

#### NestedDeviceMeta (L164-172)
```python
@dataclass
class NestedDeviceMeta:
    cls_name: str                     # 类名
    label: str                        # _DEVICE_LABEL
    sender_update_method: str         # _SENDER_UPDATE_METHOD
    sender_instances_attr: str        # _SENDER_INSTANCES_ATTR
    instance_mode: str                # "dict" | "single"
    fields: dict                      # {field_name: (default, kind)}
```

---

## 5. 关键数据流

### 5.1 消息注入链路（假节点 → UDP 监控）

**路径 A：巢内模式 / 独立假节点（SocketInterceptor 包装）**

```
SimulationPanel._on_add_clicked()
  → mgr_cls(**kwargs)             创建 sender + transport
  → set_message_injector(callback) → _patch_transport_socket()
       ↓
  transport.sock = _SocketInterceptor(real_sock, on_recv=_on_recv, on_send=_on_send)
       ↓                              （on_send 仅电台）
  假节点线程 recvfrom() → _SocketInterceptor.recvfrom()
  假电台 _udp_send()   → _SocketInterceptor.sendto()   ← v2.4 外发拦截
       ↓
  _on_recv(data, gcs_ip, gcs_port, dst_ip, dst_port)
  _on_send(data, dst_ip, dst_port, gcs_ip, gcs_port)   ← src/dst 反转
       ↓
  IntegratedMainWindow 闭包:
    self._udp_panel.inject_raw_message(data, sip, sp, dip, dp)
       ↓
  FullUdpMonitorPanel.inject_raw_message()
    ├─ 0xA5 头 → _ctrl.inject_radio_packet() → RadioDavParser.to_message_record()
    │            （source_type="radio"）                            ← v2.4 DAV 分流
    └─ 其他   → _ctrl.engine._process_raw_packet(..., source_type="fake")
       ↓
  MonitorEngine → MavlinkParser.parse_header() / RadioDavParser → MonitorModel.append()
       ↓
  QTimer 50ms → _on_tick() → get_new_records() → TraceTable/GroupedTraceView
```

**路径 B：飞机离巢后外模式（_msg_injector 回调链，v1.3 新增）**

```
SimulationPanel.set_message_injector(callback)
  → sender.set_msg_injector(callback)
       ↓
  _FakeNestSender.set_msg_injector(callback)
    → 传播到所有 external mode 飞机的 _msg_injector
       ↓
  _NestAirplane._external_receive_loop()
    → self._sock.recvfrom() → data, addr
    → src_ip = self._gs_ip     ← 地面站 IP（对齐 transport.ground_station_ip）
    → src_port = self._gs_port
    → self._msg_injector(data, src_ip, src_port, self.ip, self._local_port)
       ↓
  (同路径 A) FullUdpMonitorPanel.inject_raw_message() → MonitorEngine → UI
```

### 5.2 配置反射链路（源文件 → GUI 控件）

```
SimulationPanel.__init__()
  ├── _parse_source(config.source_file)      ← AST 解析源文件
  │     → SourceInfo (module_constants + init_attrs + init_defaults)
  │
  ├── _discover_update_methods(sender_cls)   ← inspect + docstring 解析
  │     → {method_name: {param: default}}
  │
  ├── _discover_add_params(mgr_cls)          ← inspect.signature
  │     → {param: default}
  │
  └── _build_ui()
        ├── _build_basic_group()   ← 遍历 module_constants
        ├── _build_add_group()     ← 遍历 add_params → _make_input_widget()
        └── _build_update_group()  ← 遍历 update_methods
              └── _refresh_update_params()
                    └── 每个参数: _detect_kind() → _make_input_widget()
```

### 5.3 参数持久化链路

```
用户填写表单 → 切换 update 方法 / 目标设备
  → _save_current_form_values()
       ↓
  _saved_update_params[target][method] = {param: value}
       ↓
  _refresh_update_params()
    → _load_saved_values(target, method)
    → 恢复控件值（用 setter）
       ↓
用户点击 [应用 update]
  → _on_apply_clicked()
    → 收集当前表单值
    → _saved_update_params[target][method] = kwargs  (持久化)
    → sender.method(**kwargs)                          (调用)
```

---

## 6. 关键算法

### 6.1 AST 动态反射 (`_parse_source`, L263-347)

**输入**: 源文件路径 + sender 类名 + mgr 类名
**输出**: `SourceInfo(module_constants, init_attrs, init_defaults)`

**算法步骤**:
1. `ast.parse(src)` 解析源文件
2. 遍历顶层节点:
   - 模块级 `x = Constant` → 记录到 `module_constants`（仅 int/float/str/bytes/bool）
   - 类定义内部的类级常量 → 同上
3. 定位目标类（`sender_cls_name` / `mgr_cls_name`）的 `__init__` 方法:
   - 第一遍: 建立 `__init__` 形参 → kind 的映射（从默认值推断）
   - 第二遍: AST walk 扫描 `self.X = value` 赋值，推断类型和默认值
4. 返回 `SourceInfo`

### 6.2 嵌套设备发现 (`_parse_nested_devices_from_source`, L473-507)

**输入**: 源文件路径
**输出**: `dict[str, NestedDeviceMeta]`

**算法步骤**:
1. `ast.parse(src)` → 收集模块级 + 类级常量
2. 遍历所有类定义:
   - 检查是否继承 `_NestedDeviceBase`（通过 `_inherits_from`）
   - 提取 `_DEVICE_LABEL`, `_SENDER_UPDATE_METHOD`, `_SENDER_INSTANCES_ATTR`, `_INSTANCE_MODE`
   - 提取 `_UPDATABLE_FIELDS` 字典（显式类型声明）
   - 自动推导: 扫描 `__init__` 中 `self.X = value`，推断类型和默认值

### 6.3 类型推断 (`_detect_kind`, L622-676)

优先级链（从高到低）:
1. `config.known_param_types` 注册表
2. `init_attrs` 直接查表（AST 解析的 self.X 类型）
3. `self.X = param` 路径追踪（`_find_param_kind_via_attr`）
4. 默认值运行时类型（`isinstance` 检测）
5. AST `isinstance()` 扫描（`_infer_kind_via_isinstance`）
6. 名称启发式（关键字匹配: `count/num/size` → int, `is_/has_/enable` → bool, `config/channel/list` → list, `version/serial/sn` → bytes）

### 6.4 控件工厂 (`_make_input_widget`, L950-1013)

| kind | 控件 | 特殊处理 |
|------|------|----------|
| `"int"` (≤1M) | `QSpinBox` | range ±1M |
| `"int"` (>1M) | `QLineEdit` | 大数用 hex 或文本 |
| `"float"` | `QDoubleSpinBox` | 6 位小数 |
| `"latlon"` | `QLineEdit` | 上限 ±200°, getter `float(text)×1e7`, 支持粘贴 |
| `"alt_m"` | `QLineEdit` | 上限 ±10000m, getter `float(text)×1000`, 支持粘贴 |
| `"bool"` | `_LimitedCombo(20)` | True / False |
| `"str"` / `"bytes"` | `QLineEdit` | 带 placeholder hint |
| `"list"` / `"list_int"` | `QLineEdit` | 多种格式提示 |
| 有 `choices` | `_LimitedCombo(20)` | 显示 `label (value)` |

### 6.5 参数折叠 (`_CollapseToggle`, L699-776)

**逻辑**:
- 默认显示前 `_MAX_VISIBLE_ITEMS`（5）个控件
- 超出部分隐藏 + 显示"▼ 展开更多 (N 个参数)"按钮
- 点击切换: 全部显示 / 隐藏超出部分
- 支持 `reset()` + `finalize()` 重复调用（动态重建参数场景）

---

## 7. 外部依赖与引用

### 7.1 mavlink_monitor 子包（始终可用）

| 导入 | 源文件 | 方案文档 |
|------|--------|----------|
| `MonitorController` | `mavlink_monitor/core/controller.py` | [PROJECT_PLAN.md §6.1](./PROJECT_PLAN.md#61-monitorcontroller桥接层--实际新增) |
| `FilterRule` | `mavlink_monitor/core/filter.py` | [PROJECT_PLAN.md §6.4](./PROJECT_PLAN.md#64-messagefilter) |
| `LeftPanel` | `mavlink_monitor/gui/left_panel.py` | [PROJECT_PLAN.md §7](./PROJECT_PLAN.md#7-gui-布局设计) |
| `FilterBar` | `mavlink_monitor/gui/filter_bar.py` | [PROJECT_PLAN.md §7](./PROJECT_PLAN.md#7-gui-布局设计) |
| `TraceTable` | `mavlink_monitor/gui/trace_table.py` | [PROJECT_PLAN.md §7.3](./PROJECT_PLAN.md#73-trace-列定义13-列) |
| `GroupedTraceView` | `mavlink_monitor/gui/grouped_trace_view.py` | [PROJECT_PLAN.md §16](./PROJECT_PLAN.md#16-phase-6--分组消息视图-canoe-风格) |
| `DetailTree` | `mavlink_monitor/gui/detail_tree.py` | [PROJECT_PLAN.md §7](./PROJECT_PLAN.md#7-gui-布局设计) |
| `_MultiSelectButton`, `_LimitedCombo`, `_CollapseToggle` | `mavlink_monitor/gui/widgets.py` | 本方案 §2.4 |
| `fmt_rel`, `fmt_abs` | `mavlink_monitor/gui/utils.py` | 本方案 §2.8 |

### 7.2 假设备模块（条件可用）

| 导入 | 源文件 | 方案文档 |
|------|--------|----------|
| `FakeAirplane`, `_FakeAirplaneMessageSender`, `_FakeAirplaneMessageSenders`, `AIRPLANE_MODEL_SERIALS` | `D:\...\fake_airplane.py` | [CODE_PLAN_FAKE_AIRPLANE.md](./CODE_PLAN_FAKE_AIRPLANE.md) |
| `FakeNest`, `_FakeNestSender`, `_FakeNestSenders`, `NESTED_DEVICE_REGISTRY` | `D:\...\fake_nest.py` | [CODE_PLAN_FAKE_NEST.md](./CODE_PLAN_FAKE_NEST.md) |
| `FakeR2RadioStation`, `_FakeRadioSender`, `_FakeRadioSenders`, `FAKE_RADIO_IP`, `DGCS_IP`, `NETCARD_INTERFACE`, `SUB_DEVICE_R2_STATION` | `D:\...\fake_radio.py` | [CODE_PLAN_FAKE_RADIO.md](./CODE_PLAN_FAKE_RADIO.md) |
| `get_fake_project_path`, `has_fake_project` | `mavlink_monitor/core/paths.py` | 本方案 §9 — 统一路径解析 |
| `LogManager` | `D:\...\utils\logger.py` | 无独立方案 |

### 7.3 fake_cloud — 云平台拦截代理（本仓库，恒可用，v3.7）

| 导入 | 源文件 | 方案文档 |
|------|--------|----------|
| `FakeCloudGateway`, `_FakeCloudSender`, `_FakeCloudSenders`, `DEFAULT_LISTEN_HOST/PORT`, `DEFAULT_UPSTREAM_ORIGIN`, `parse_promotion_response`, `diff_json`/`highlight_html`/`syntax_highlight` | `tools/simulation_gui/fake_cloud/`（3 模块，stdlib 零依赖） | [CODE_PLAN_FAKE_CLOUD.md](./CODE_PLAN_FAKE_CLOUD.md) |

---

## 8. 配置与资源文件

| 文件 | 路径 | 用途 | 加载位置 |
|------|------|------|----------|
| `config_default.json` | `mavlink_monitor/resources/config_default.json` | 搜索路径 + buffer 容量 + GUI 偏好 | `LeftPanel.load_initial_config()` |
| `command_183_functions.json` | `mavlink_monitor/resources/command_183_functions.json` | COMMAND_ACK(183) 的 result→功能名映射 | `FullUdpMonitorPanel._load_command_183_config()` (L2730) |
| `DavMessage.proto` | `simulation_gui/resources/DavMessage.proto` | 电台 DAV 协议权威消息定义（MessageID 枚举，69 条） | `FullUdpMonitorPanel._load_radio_config()` (L2738) |
| `mavlink_config_v*.json` | 外部项目 `file/mavlink_version/` | MAVLink 消息定义 | `MonitorController.load_config()` |
| `mavlink_enums_v*.json` | 外部项目 `file/mavlink_version/` | MAVLink 枚举映射 | `MonitorController.load_enums()` |
| `fake_airplane.py` | 外部项目 `src/Protocol/mavlink/` | 假飞机源文件（AST 反射源） | `_parse_source()` (L263) |
| `fake_nest.py` | 外部项目 `src/Protocol/mavlink/` | 假机巢源文件（AST 反射源） | `_parse_source()` + `_parse_nested_devices_from_source()` |
| `fake_radio.py` | 外部项目 `src/Protocol/mavlink/` | 假电台源文件（AST 反射源） | `_parse_source()` (L263) |
| `fake_cloud/ad_proxy.py` | 本仓库 `tools/simulation_gui/fake_cloud/` | 云平台透明反向代理（AST 反射源；v3.7） | `_parse_source()` + `SimConfig("cloud")` |
| `http_test_server.txt` | 地面站进程工作目录（用户手动创建） | 覆盖云端接口 origin 指向本代理（一行 `http://127.0.0.1:8765`；进程内只读一次，改动需重启地面站） | 不由本工具读写，见 CODE_PLAN_FAKE_CLOUD §1 |

---

## 9. 已知问题与优化点

> 以下问题引用自 [PROJECT_PLAN.md §15 Phase 5 — 优化完善计划](./PROJECT_PLAN.md#15-phase-5--优化完善计划)

### 本文件相关

| # | 问题 | 位置 | 状态 |
|---|------|------|------|
| **B3** | 网卡列表扫描不全 | `left_panel.py`（FullUdpMonitorPanel 通过 LeftPanel 间接使用） | 待修复 |
| **B4** | 网卡名称显示乱码 | `left_panel.py:22` encoding 问题 | 待修复 |
| **F3** | MonitorTab 功能对齐 MainWindow | `integration/monitor_tab.py` 缺版本扫描、网卡列表等 | 待修复 |
| **E5** | 日志文件清理 | `logs/` 目录积累集成测试日志 | 待修复 |

### 本文件特有

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| **I1** | ~~硬编码假项目路径~~ ✅ 已修复 | L52-61 | 改用 `mavlink_monitor.core.paths` 统一解析（环境变量 → 相对路径 → 硬编码回退） |
| **I2** | `FullUdpMonitorPanel` 与 `MainWindow` 代码重复 | L2421-2949 vs `gui/main_window.py` | 大量布局/回调逻辑重复，修改时需同步 |
| **I3** | 参数持久化仅在内存 | `_saved_update_params` 字典 | 重启 GUI 后丢失所有已保存参数 |
| **I4** | `_parse_source` 强依赖 AST 结构 | L263-347 | 假设备源文件结构变化（如类名改名、字段重排）会导致反射失败 |
| **I5** | `collect_and_push_fake_ips` 2s 轮询可能遗漏 | L3107-3110 | 假节点在轮询间隔内启停，IP 列表短暂不一致 |

---

## 10. 修改指南

> **v2.0**: 所有代码已从单体文件移至 `mavlink_monitor/integrated_gui/*.py`。修改后更新本文档对应模块描述。

### 场景 1: 新增一个假设备类型（如 FakeCamera）

1. 在 `_config.py` 的 `_build_sim_configs()` 新增 `SimConfig("camera", ...)`
2. 在 `_window.py` 的 `IntegratedMainWindow.__init__` 创建对应 `SimulationPanel`
3. 如果新设备有嵌套设备，在对应源文件中定义 `_NestedDeviceBase` 子类
4. 更新本文档 §1/§3/§4.5/§7.2
5. **特例 — 需要专属消息视图的设备**（参照 cloud，v3.7）：新建
   `_<xxx>_panel.py` 复合面板（SimulationPanel + 自定义视图），`_window.py`
   假设备循环 `skip` 该 key 后单独创建；设备源文件放本仓库时在 `_env.py`
   加独立导入段（`HAS_FAKE_XXX` 标志，不依赖 `HAS_FAKE_MODULES`）

### 场景 2: 在 SimulationPanel 中新增功能按钮

1. 修改 `_panels.py` 中对应 `_build_*_group()` 方法
2. 在 `SimulationPanel` 类中新建槽函数
3. 更新本文档 §1 对应描述

### 场景 3: 修改 AST 反射逻辑

1. 修改 `_reflection.py` 中的 `_parse_source()` / `_parse_nested_devices_from_source()`
2. 修改 `_types.py` 中的 `_detect_kind()` 优先级链
3. 更新本文档 §6.1-6.3

### 场景 4: 假设备源文件结构变更

1. 检查 `_reflection.py` 的解析逻辑是否兼容
2. 更新 `_config.py` 中 `SimConfig.known_param_types` / `param_defaults`
3. 更新对应 `CODE_PLAN_FAKE_*.md` 子方案

### 场景 5: 修改 FullUdpMonitorPanel 布局或行为

1. 修改 `_monitor.py` 中的 `_setup_central()` 或回调方法
2. 检查是否与 `gui/main_window.py` 存在差异需要同步
3. 更新本文档 §1

### 场景 6: 排查假节点消息未出现在监控中的问题

1. 检查 `_panels.py` 中 `SimulationPanel.set_message_injector()` 是否被调用
2. 检查 `_config.py` 中 `_SocketInterceptor.recvfrom()` 是否拦截到数据
3. 检查 `_monitor.py` 中 `FullUdpMonitorPanel.inject_raw_message()` 是否正确注入
4. 检查 `_monitor.py` 中 `_on_tick()` 是否运行 + 过滤条件
5. 参考 §5.1 消息注入链路完整路径

---

> **更新记录**:
> - 2026-09-15: v3.10 — TCP 消息监控两处调整：(1) `TraceTable` 新增 `show_toolbar` 参数（默认 True）——TCP 面板传 False，表格内建工具栏 5 按钮（||暂停/>恢复、清空、时间、真实目标IP、来源）不再创建（捕获/清空由外层捕获组提供）；`scroll_paused` setter 加 `_pause_btn` 存在性保护；UDP 监控不受影响；(2) `_tcp_monitor._match_filter` 四维过滤由 AND 改为 **OR 并集语义**（任一非空条件命中即显示，全空显示全部）。`test_tcp_monitor_panel.py` TC17 重写为 TC22（OR 断言）+ 新增 TC21（工具栏裁剪，含 UDP 回归）；`_gui_verify_gcs_app.py` 增 E17-E19；全套 441 passed、真机验证 28/28
> - 2026-09-15: v3.9 — 「地面站应用」TCP 监控从 UDP 消息监控 Tab 迁出：(1) 新模块 `_tcp_monitor.py` `TcpMonitorPanel`（独立 `MonitorEngine + MonitorModel`，`parser=None` 安全——GCS 路径不走 parser）：左栏网卡嗅探（复用 `_get_interfaces`）+ 监控端口(443 可改，运行中改自动重启) + 统计；捕获组[暂停|清空]；**四维过滤** SrcIP/SrcIP:Port/DstIP/DstIP:Port（自建 AND 语义 + 候选自动收集 + 清除 + 启用切换全量重建；editable combo 程序化设值须 `setEditText`）；`QSplitter 5:1` = TraceTable + DetailTree（gcs 记录 fields_parsed=True 不经 controller 直接 show_fields）；(2) `CloudProxyPanel` 子 Tab 化：「云平台配置」（原页面）+「TCP 消息监控」；(3) `_monitor.py` 移除「地面站应用」开关/`_on_gcs_app_toggle`/shutdown 联动（engine/controller 的 gcs 代码保留，宿主换成 TcpMonitorPanel 的独立引擎）。新增 `tests/test_tcp_monitor_panel.py` TC16-TC20（5 用例）；`test_gcs_app_monitor.py` TC15 改为断言 UDP 面板已无该开关；`_gui_verify_gcs_app.py` 重写为 E13-E16（真实流量 19/19：WLAN 网卡嗅探→baidu GCS_TLS 入表→四维过滤实操→5:1 详情树→停止冻结）；全套 440 passed
> - 2026-09-15: v3.8 — 监控区域（UDP 监控 Tab）新增「地面站应用」数据源（GCS↔云平台 TCP/TLS 元数据监控）：(1) 根因——`engine.py` 网卡嗅探 `filter="udp"` 在内核 BPF 层丢弃 TCP，地面站↔云平台 TLS 永远进不了监控；(2) `engine.py` 新增 `GcsAppCaptureNode` + `set_gcs_app_listener/start_gcs_app/stop_gcs_app`（独立 `AsyncSniffer(filter="tcp port 443")` 复用当前选中网卡）+ `_gcs_sniff_callback/_build_gcs_record`（构造 `MessageRecord`：msg_name=GCS_TLS/GCS_HTTP/GCS_TCP、五元组、方向、载荷 hex（密文截断 4096）、fields=tcp_flags/payload_len/tcp_seq/tcp_win[/http_first_line]、`source_type="gcs_app"`、构造即 `fields_parsed=True`；**降噪**：纯 ACK 不记录，数据包+SYN/FIN/RST 记录）；`is_running` 含 gcs 分支（驱动 GUI tick）；`stop()`/shutdown 联动；(3) `controller.py` 桥接 + `get_stats` 5 项；(4) `_monitor.py` 数据源组第三开关「地面站应用」+ `_on_gcs_app_toggle`（未选网卡回弹+提示）；(5) fake_cloud `DEFAULT_UPSTREAM_ORIGIN` 改回 UAT `https://cloud-gateway-uat.dmduav.com`（v1.2）。新增 `tests/test_gcs_app_monitor.py` TC11-TC15 + `_gui_verify_gcs_app.py` E10-E12（真实 HTTPS 流量端到端 15/15）；全套 435 passed
> - 2026-09-15: v3.7.1 — 云平台拦截 4 项修复：(1) `_panels.py _on_basic_apply_clicked` 对包内源文件（fake_cloud/ad_proxy.py）`import_module(stem)` 报 `No module named 'ad_proxy'` → `SimConfig` 新增 `module_name` 字段（cloud="fake_cloud.ad_proxy"），导入名 `module_name or source_file.stem`；(2)(3) fake_cloud 默认值按环境调整：监听 `10.10.12.149:14852`、上游 `https://10.20.2.34:443`；(4) 上位机看不到通信消息（wireshark 可见 TLS 帧）三层根因修复——上游 HTTPS 默认不校验证书（IP 直连/自签此前必 502）、非 HTTP 数据（TLS ClientHello）连入明文代理由静默丢弃改为 `_ProxyHandler.parse_request` 覆写发 proxy_error 事件（提示 http_test_server.txt 须 http:// 前缀）、监听地址与地面站访问地址对齐。`test_fake_cloud_proxy.py` TC6-TC9 + `_gui_verify_fake_cloud.py` E6-E9；全套 430 passed、扩展验证 35/35。详见 [CODE_PLAN_FAKE_CLOUD.md](./CODE_PLAN_FAKE_CLOUD.md) v1.1
> - 2026-09-14: v3.7 — 新增「云平台拦截 (FakeCloud)」Tab（监听阶段）：(1) 新建本仓库包 `tools/simulation_gui/fake_cloud/`（3 模块，stdlib 零依赖）——`ad_proxy.py` 透明反向代理（`FakeCloudGateway` transport / `_FakeCloudSender` sender+事件汇 / `_FakeCloudSenders` mgr，**对内容 100% 透传不做篡改**，双向捕获 gcs_request/cloud_response/proxy_error 结构化事件 + promotion 深度解析）+ `json_diff.py`（递归 diff + HTML 高亮：改⚠黄/增＋绿/删－红，预留篡改阶段）；(2) `_env.py` 新增 `HAS_FAKE_CLOUD` 导入段（不依赖假项目）；(3) `_config.py` `_build_sim_configs()` 无条件 cloud 分支；(4) `_window.py` cloud Tab（假设备循环 skip cloud）；(5) 新模块 `_cloud_panel.py`（`CloudProxyPanel` = SimulationPanel + `CloudMessageView` 事件表格+详情 HTML+预留篡改对比区，50ms 轮询 drain_events）。开发中修复：`close()` 对从未 start 的 server 调 `shutdown()` 永久阻塞；Windows `SO_REUSEADDR` 同端口静默共存 → connect 探测预检；`_reply` 补捕 `ConnectionAbortedError`。新增 `tests/test_fake_cloud_proxy.py` 5 用例 + `_gui_verify_fake_cloud.py` 25 断言（含 GUI 实操）；全套 426 测试通过。详见 [CODE_PLAN_FAKE_CLOUD.md](./CODE_PLAN_FAKE_CLOUD.md)
> - 2026-09-10: v3.6.5 — 假飞机/机巢内假飞机新增 failsafe(0x06) 消息支持：`fake_airplane.py` 与 `fake_nest.py`（`_NestAirplane`）各新增 `update_failsafe(enable, f_crash, ..., f_ekf_vert)`（17 参数，F_EKF_VERT=bit0 ... F_CRASH=bit15 对齐 C# AlarmCode；未配置的故障位一律置 0，全量覆盖语义；`enable_failsafe=False` 默认不外发，True 时随 5s 状态周期加发 0x06）+ `_build_id_006()`；`_config.py` airplane `known_param_types` 注册 enable+16 个 `f_*` 为 bool（GUI 反射自动生成 True/False 下拉，零 GUI 逻辑改动；机巢嵌套面板经默认值推断同样为 bool）。详见 [CODE_PLAN_FAKE_AIRPLANE.md](./CODE_PLAN_FAKE_AIRPLANE.md) / [CODE_PLAN_FAKE_NEST.md](./CODE_PLAN_FAKE_NEST.md) 2026-09-10 条目。新增 `tests/test_failsafe_0x06.py` 6 用例 + `_gui_verify_failsafe_0x06.py` 21 断言；全套 421 测试通过
> - 2026-08-31: v3.6.4 — 假机巢新增 SET_CODE_NUMBER(0x1C, 28) ack 回复(对齐 COMMAND_LONG/76 逻辑): `_FakeNestSender` 新增 `_handle_set_code_number`, `_STATE_RULES` 注册 28 → 回 COMMAND_ACK(77, command=28, ack_sys_id=接收 comp_id) 且受 `update_ack`(silence/fail) 配置控制; 仅当 ACK result=0 时把 `self.nestId`(0x57 上报)与 `self.code`(0x02 上报)同时更新为 code_number(5 字节规整)。nest `SimConfig.known_param_types` 补 fail_count/silence_count(与 airplane/radio 对齐, GUI 生成 update_ack 控件)。新增 `tests/test_fake_nest_set_code_number.py` 9 用例; 全套 333 测试通过
> - 2026-08-25: v3.6.3 — 剧本时间对齐对比调整：(1) **疏密以原剧本为基准**——对比点改为**每 payload 帧一个**（`compare_drama_timelines` step=1），原剧本航点显示全部 payload 帧，与 Tab0「航点解析」`parse_waypoints_from_bin` 疏密一致（168/170：原剧本 1606 航点[淡灰785+对比段821]、后起飞对比点 821，与 Tab0 1606/821 完全一致）。(2) **航点小标记**——3D 场景中 position 帧航点用**大菱形**、普通 payload 帧用**小圆点**区分（size/symbol 数组），同时对比位置与灯光（payload 帧）。删除 `_position_samples` 辅助函数。(3) **播放按钮可见**——`#plotly_3d` 改 `height: calc(100vh - 56px) !important` 留出底部控制条（原内联 `height:100%` 把 controls 挤出）。播放间隔改用 payloadFps。`test_drama_compare_timeline.py` 用例调整（删除 position 采样测试、新增每帧对比测试）15→14；全套 284 测试通过
> - 2026-08-25: v3.6.2 — 剧本时间对齐对比增强：(1) **原剧本航点疏密一致**——新增 `_position_samples(frames, pos_step)` 按 position 帧（`frame%pos_step==0`）采样，`visualize_drama_compare_timeline` 原剧本轨迹/航点改用此函数，与后起飞对比点疏密一致（168/170：原剧本对比段 165 航点 == 对比点 165）。(2) **播放控制**——对比 HTML 底部新增播放/暂停按钮 + 1x~5x 速率 + 时间 slider，对比点数据紧凑 JSON 内嵌（`points` 数组含 rel_time/dist/ok/两机坐标），JS `Plotly.restyle` 仅更新「当前帧」两机高亮 markers 与虚线连线（trace 9/10/11），未播放/暂停时整个航迹对比保持可见。`test_drama_compare_timeline.py` 新增 1 用例（position 帧采样）+ 更新集成断言（播放控件/疏密一致）14→15；全套 285 测试通过
> - 2026-08-25: v3.6.1 — 修正剧本时间对齐对比三处：(1) **对齐帧率**——frames 帧号是 payload 帧索引，`compare_drama_timelines` 改用 `payload_fps` 计算偏移（`offset=起飞时间差×payload_fps`，168/170 由 157→785），采样步长 `round(payload_fps/point_fps)` 满足「时间点长度 1/pointFps」；修后 168/170 后段重合（后段 avg 距离 304m→2.0m、绿点 0→29/55）。(2) **原剧本航点全保留**——`visualize_drama_compare_timeline` 显示早起飞剧本完整轨迹/航点，后起飞时刻前[帧<offset]用更淡灰（rgba 0.25/0.35）标识，对比段正常灰。(3) **3D 视觉对齐 playback**——新增起点/终点/原点 trace、标题含 payloadFps/pointFps、轴范围合并全部航点。`test_drama_compare_timeline.py` 新增 2 用例（payload_fps 偏移/采样步长）12→14；全套 284 测试通过
> - 2026-08-25: v3.6 — 「剧本对比」由预留实现为**时间对齐对比**（不同起飞时间剧本）：(1) 新增 `parse_timestamp_from_name()`（文件名 `yyyymmdd_hhmmss[.mmm]` → datetime）、`compare_drama_timelines()`（早起飞剧本为时间基准、晚起飞剧本按 `j=k-offset` 线性插值，灯光取 floor 帧持续值，距离 + 灯光一致性逐点输出，`_DIST_TOL=0.005m`）、`visualize_drama_compare_timeline()`（HTML 左侧竖排两折线图[距离/灯光一致性，横轴相对秒] + 右侧 3D：早起飞灰航线/灰航点，晚起飞绿[距离<0.005m 且灯光一致]/红航点，航线按航点状态 None 分隔分段着色）；(2) `_DramaWorker` 新增 task_type="compare_timeline"；(3) `WaypointTrackComparePanel._on_compare` 接入（文件名无时间戳弹提示）、`_append_selected` 用规范化路径去重且追加不删除；(4) 新增 `tests/test_drama_compare_timeline.py` 12 用例；全套 282 测试通过
> - 2026-08-24: v3.5.3 — `visualize_drama_playback` 当前帧航点 marker 缩小为 50%（size 8→4），原点保持 8。`test_drama_track_compare.py` 新增 1 用例（size 4/8 断言），用例 11→12；全套 270 测试通过
> - 2026-08-24: v3.5.2 — `visualize_drama_playback` 播放 HTML 视觉优化：(1) 起点/终点航点图标缩小为当前的 25%（marker size 10→2.5，边框 width 2→1）；(2) 3D 坐标区填满页面——`fig.to_html(config={"responsive": True})` + CSS `#plotly_playback{height:calc(100vh-56px)!important}`、`html/body{height:100%;overflow:hidden}`（底部控件高 56px）。`test_drama_track_compare.py` 新增 2 用例（图标 25%、responsive/CSS 填满），用例 9→11；全套 264 测试通过
> - 2026-08-24: v3.5.1 — `visualize_drama_playback` 播放 HTML 性能优化：(1) 原 plotly frames/slider 全量嵌入 8331 帧动画导致 HTML 9.7MB、拖动卡顿，改为 plotly 静态 base 场景（未途径线亮蓝 / 已途径线淡灰 / 当前帧 markers / 起终点 / 原点）+ 位置帧(1667)/灯光帧(8331) 紧凑 JSON 数组完整内嵌（`posLen`/`lightLen` 自描述，位置帧完全保留）+ 原生 HTML range slider + JS `Plotly.restyle` 运行时更新（拖动流畅，无 O(N²) 分段数据）；(2) 新增 1x~5x 播放速率下拉（`setInterval` 间隔 = 1000/(payloadFps×速率)，1x=真实灯光帧率）；(3) 已途径航线淡灰 / 未途径航线亮蓝，JS 按当前帧实时构建分段；(4) HTML 降至 ~5MB。`test_drama_track_compare.py` 更新 playback 断言 + 新增 4 用例（posLen/lightLen 保留、速率选项、已途径 trace、体积），用例 5→9；全套 262 测试通过
> - 2026-08-24: v3.5 — 剧本处理新增第 4 个子 Tab「航迹对比」：(1) 模块级新增 `parse_waypoints_lights_from_bin()`（复用 DatReader 管线，额外提取每帧灯光 r/g/b + pointFps/payloadFps）与 `visualize_drama_playback()`（基于 `visualize_drama_3d` 视觉风格，航点 marker 颜色=该帧灯光 RGB，底部 plotly slider 进度条可拖动/跳跃至任意帧，含播放/暂停按钮，标题含位置/灯光帧率）；(2) 新增 `WaypointTrackComparePanel`：Box1 文件选择（上限 2 个、列表固定 2 行高、标题右侧 4 按钮：选择文件/清空列表/剧本解析/剧本对比）+ Box2 解析结果 HTML 列表（文件链接/生成时间/批次，同批次相同背景色）；「剧本对比」预留（补点 vs 原剧本，需开始绝对时间）；(3) `_DramaWorker` 新增 task_type="playback" 与 `file_done_batch` 信号（带批次号）；(4) `src/Protocol/drama/drone_show/dat_reader.py` 的 `print_frame_type_counts` 精简为单行帧统计总览，减少解析日志量。新增 `tests/test_drama_track_compare.py` 5 个用例；全套 258 测试通过
> - 2026-08-21: v3.4 — 适配 0x00（msg_id=0）消息两种解析方式（依据技术方案 + C# 源码 DavDevice/DavMessageSender/DavLink 确认，由 msg_type 区分）：(1) **Msg 帧（msg_type=0）** = GET_FIRMWARE_VERSION，payload 为 `UniversalCommand{command}`（protobuf），`radio_parser._KNOWN_FIELDS` 补 `0x0000: {1: "command"}`，DetailTree 显示 command 字段；(2) **Ack 帧（msg_type=1）** = msg_id 缺省为 0，payload 为 `report`（UInt32 LE），`MessageRecord` 新增 `dav_report` 字段，`to_message_record` 存入 report，新增 `radio_parser.parse_ack_report(report)` 直接解析，`controller._parse_radio_fields` 按 `dav_report` 是否存在区分两种解析。新增 `tests/test_radio_dual_format.py` 7 个用例；全套 253 测试通过
> - 2026-08-20: v3.3 — 修复假电台 update_ack 拦截时仍应用地面站设置值：原 `_handle_incoming` 先 `_on_set_xxx` 再 `_send_ack` 判定策略，导致静默/失败注入/命令覆写命中时地面站的值（如 button_param）仍被赋值并回传心跳。重构 `_send_ack` 为 `_ack_policy(msg_id)`（判定返回 action/report）+ `_handle_config_command(msg_id, ack_count, apply_fn)`（**仅 normal 执行 apply_fn 应用地面站值**）+ `_send_ack(ack_count, report)` 纯发帧；`_handle_incoming` 各分支改用 helper。新增 `tests/test_radio_ack.py` 5 个拦截语义用例；全套 246 测试通过
> - 2026-08-20: v3.2 — (1) 修复 ACK 帧在 UDP 监控中误命名：`RadioDavParser.to_message_record` 对 ACK 帧（msg_type=1）固定命名 `Radio_ACK(ack=N)`、方向 Tx（原 msg_id=0 被 proto 配置映射为 GET_FIRMWARE_VERSION）；(2) 假电台新增 `update_ack`（对齐假飞机）：`_FakeRadioSender.update_ack`（静默/命令 report 覆写/失败注入），`FakeR2RadioStation._send_ack` 增加 `msg_id` 参数按优先级应用；radio `SimConfig.known_param_types` 补 5 个 ack 字段（fail_count/silence_count/cmd_result_enable/cmd_result_commands/cmd_result_values），GUI 自动生成控件。新增 `tests/test_radio_ack.py` 9 个用例；全套 241 测试通过
> - 2026-08-19: v3.1 — 修复假电台收发消息不进 UDP 监控：(1) 根因——假电台 socket 在 `_run`→`_udp_setup` 才创建（延迟创建），`_patch_transport_socket` 遇到 `sock=None` 直接 return，拦截器装不上（log 有 `_on_set_domain` 但监控无、外发消息 dst=0.0.0.0）；(2) 参考假机巢 `set_msg_injector` 模式——`fake_radio._FakeRadioSender` 新增 `set_msg_injector`/`_wrap_sock`，在 socket 就绪后自动用内部 `_RadioSocketInterceptor` 自包装，收发数据经回调注入监控（接收 src=地面站、外发 dst=172.16.200.1:14555）；`_patch_transport_socket` 对电台（`isinstance(_FakeRadioSender)`）直接 return，避免双重拦截；(3) `engine.py` 新增 `_resolve_listen_dst_ip`，UDP 监听绑定 0.0.0.0 时记录 dst 改用本机 IP。新增 `tests/test_radio_refactor.py` 的 set_msg_injector 路径用例；全套 232 测试通过
> - 2026-08-19: v3.1 — 修复假电台收发消息不进 UDP 监控：(1) 根因——假电台 socket 在 `_run`→`_udp_setup` 才创建（延迟创建），`_patch_transport_socket` 遇到 `sock=None` 直接 return，拦截器装不上（log 有 `_on_set_domain` 但监控无、外发消息 dst=0.0.0.0）；(2) 参考假机巢 `set_msg_injector` 模式——`fake_radio._FakeRadioSender` 新增 `set_msg_injector`/`_wrap_sock`，在 socket 就绪后自动用内部 `_RadioSocketInterceptor` 自包装，收发数据经回调注入监控（接收 src=地面站、外发 dst=172.16.200.1:14555）；`_patch_transport_socket` 对电台（`isinstance(_FakeRadioSender)`）直接 return，避免双重拦截；(3) `engine.py` 新增 `_resolve_listen_dst_ip`，UDP 监听绑定 0.0.0.0 时记录 dst 改用本机 IP。新增 `tests/test_radio_refactor.py` 的 set_msg_injector 路径用例；全套 232 测试通过
> - 2026-08-19: v3.0 — (1) **假电台消息配置改由 `resources/DavMessage.proto` 提供**（原 `radio_message_config.json` 已删除）：`RadioDavParser` 新增 `load_config_from_proto()`（解析 MessageID 枚举 + 方向启发式），`load_config` 按扩展名分流（.proto/.xml/.json），`_monitor.py` 配置路径优先 proto；(2) **fake_radio 消息模块重构**（依据技术方案 + proto，不参考 cs）：修复 GPS 编码 bug（`rtkStationPosition` lat/lon/alt 由 fixed32×1e7 改为 double/fixed64，地面站可完整解析心跳）；新增查询指令交互（0x0103→SEND 0x0104、0x0201→SEND 0x0202）；(3) 电台 gcs 地址从 `fake_radio.DGCS_IP`/`DAV_PORT` 读取（默认 172.16.200.1:14555）；(4) `radio_parser` 补充 `_KNOWN_FIELDS`（0x0103/0x0104/0x0201/0x0202/0x0118）。新增 `tests/test_radio_refactor.py` 5 个用例；全套 232 测试通过
> - 2026-08-19: v2.9 — (1) 电台 gcs 地址**固定显示** `172.16.200.1:14555`（`_patch_transport_socket` 电台分支不再读取实例配置）；(2) 电台消息配置改读权威协议文件 `src/Protocol/radio/MessageDefineUAV.xml`（69 条消息）：`paths.py` 新增 `get_radio_message_xml()`，`RadioDavParser` 新增 `load_config_from_xml()`（内联 plist 解析 + 方向启发式），`load_config` 按扩展名分流，`_monitor.py` 配置路径优先 XML；(3) `fake_radio.py` 配置指令处理完善：扩展 MessageID（0x0111/0x0112/0x0119）、`_on_set_domain`/`_on_set_encrypt`/`_on_set_button` 完整解析并更新状态、新增 `_on_set_receiver_mode`/`_on_set_receiver_rc_radio`、`_handle_incoming` 通用 fallback 肯定 ACK、`build_heartbeat`/`_send_heartbeat` 支持 button_param 全字段。新增 `tests/test_radio_features.py` 12 个用例；全套 227 测试通过
> - 2026-08-18: v2.8 — 修复假电台 UDP 消息未注入监控的问题（4 处缺陷）：(1) `_monitor.py` 资源路径少退一级（`mavlink_monitor/resources/` → `simulation_gui/resources/`），改为 `_RESOURCES_DIR` 常量，使 `radio_message_config.json`/`command_183_functions.json` 可正确加载；(2) `inject_raw_message` 增加 DAV 帧（0xA5 同步字）分流，新增 `MonitorController.inject_radio_packet()` 复用 `RadioDavParser.to_message_record()`（source_type="radio"），绕过 MAVLink 魔数检查；(3) `_SocketInterceptor` 增加 `sendto`/`on_send` 拦截，`_patch_transport_socket` 对电台安装 `on_send`（src/dst 反转）；(4) `_patch_transport_socket` 对电台从 `_radio` 读取 `dgcs_ip`/`port`（原从包装器读取恒为默认值/0）。新增 `tests/test_radio_injection.py` 11 个用例；全套 215 测试通过
> - 2026-08-14: v2.7.2 — 修复 proto3 默认值字段不显示统计的 BUG：(1) 新增 `_fill_proto3_default_values` 方法，在每次 `_collect_message_stats` 处理 message 子项时调用，补齐 ListFields() 未返回的标量字段（如 OFF 帧 lazer 的 `r=0,g=0,b=0`）；(2) 扩展嵌套合并到第 3 层（如 `lazerKeyFrame[].lazers[].b`），原 2 层合并导致跨 drone 的 b 计数只统计首个 drone；(3) 修复 `fd.label` 不存在导致 AttributeError（新 protobuf 用 `fd.is_repeated`）；(4) 用户场景 `激光test-v3-最小功率激光-短.drm` 的 `lazerKeyFrame-lazers-b` 现在正确显示 `0 (50), 25 (50)`；(5) 新增 TC#14（用户真实场景 50 drone × 2 lazer）和 TC#15（全默认 lazer）共 2 个测试用例，测试总数 13→15；全套 204 测试通过
> - 2026-08-14: v2.7.1 — 修复 `DramaFrameInspectorPanel` 字段统计 BUG：(1) `_collect_message_stats` 跨 message 合并时使用 `sc2.scalar_values` 而非 `sub_child.scalar_values`（修复嵌套 repeated message 字段 scalar_values 不累加问题）；(2) `_format_scalar_range` 在 unique 值 ≤5 时显示每个值的出现次数（`v1 (n1), v2 (n2), ...`），单 unique 值显示 `value (count)` 明确次数；(3) 新增 `tests/test_drama_field_stats.py` 13 个测试用例覆盖嵌套合并/取值显示/proto3 默认值等场景
> - 2026-08-12: v2.7 — 重建 `Drama3_pb2.py`：使用 `descriptor_pb2` 构建完整 FileDescriptorProto 二进制→`Drama3.desc` 文件；新增 16 个消息类型（DramaRangeInfo/LaserAreaProto/Vector3Proto/PayloadParachute*等）；Drama3 字段 11→12 (+rangeInfo)；Drone 字段 14→21 (+7 种新负载类型)；PayloadLazer +channel(4)；PayloadFireworkAngle +type(3)；PayloadGimbalFrame +gimbalVectors(3)；PayloadLazerFrame 拆分为 legacyLazers(2) + lazers(3,repeated)
> - 2026-08-12: v2.6 — `DramaFrameInspectorPanel` 新增双 Tab（按帧类型分类 / 按飞机分类）；Tab2 逐 drone 分支（`drone_N`），非 drone 字段共用，无 Not_Exist 节点
> - 2026-08-11: 新增 `latlon` / `alt_m` 控件类型；初始为 QDoubleSpinBox，后改为 QLineEdit 以支持粘贴、扩大上限（latlon ±200°、alt_m ±10000m）；getter 做 `float(text)×scale`；airplane `known_param_types` 注册 cur_lat/tar_lat/cur_lon/tar_lon→latlon, cur_alt/tar_alt→alt_m；嵌套飞机 `_UPDATABLE_FIELDS` 同步更新；`_nested.py` / `_panels.py` update_position 表单 lon/lat 顺序交换
> - 2026-08-04: v2.3 — 性能优化（目标 5000 msg/s）：display_limit 10000→100000；自适应刷新率（50-200ms）；TraceTable 改用 QAbstractTableModel 虚拟列表；批量 add_records()；_on_tick 优化批量推送
> - 2026-07-31: v2.2 — `_patch_transport_socket` 支持电台嵌套 sock 检测（`transport._radio.sock`）；`_is_sender_online` 改为线程存活优先（移除 running flag 优先判断）；`_stop_sender_thread` join 超时从 2s 提升到 5s；CODE_PLAN_FAKE_RADIO.md 同步更新 §8.4/§8.5
> - 2026-07-31: v2.1 — H17 `_TamperEntry` 三个下拉框 `_MultiSelectButton(single_select=True)` → `_LimitedCombo(20)`（`currentData()` 直存 int）；H18 `_LimitedCombo.showPopup()` DPI 感知（`sizeHintForRow(0)` 动态校准 `_max_height`）；H19 清理 `main_window.py` + `left_panel.py` 共 16 处 UDP TODO 死代码
> - 2026-07-31: v2.0 — H10 单体文件拆分：`integrated_gui.py` (3192 行) → `integrated_gui/` 包（8 模块，最大 870 行）；原文件保留为 10 行兼容重定向层；无循环依赖
> - 2026-07-31: v1.15 — `test_persistence.py` 从项目根移至 `tests/`，测试数量从 140 → 156
> - 2026-07-31: v1.14 — 文档归类到 `docs/`（7 份 MD），根目录仅保留 `README.md`
> - 2026-07-31: v1.13 — `DEFAULT_DRAMA_DIR` 从包内 `mavlink_monitor/drama/` 移至 `output/drama/`，28 个输出文件迁出
> - 2026-07-31: v1.12 — `DRAMA_MODIFIED_DIR` 从包内 `mavlink_monitor/drama_modified/` 移至项目根 `output/drama_modified/`，输出文件不再混入 Python 包
> - 2026-07-31: v1.11 — 新建 `core/paths.py` 统一路径解析（环境变量 `DMD_FAKE_PROJECT_PATH` → 相对路径 → 硬编码回退）；`integrated_gui.py`/`drama_processing.py`/`left_panel.py`/`test_persistence.py` 移除硬编码路径
> - 2026-07-31: v1.10 — 提取共享控件到 `gui/widgets.py`（`_MultiSelectButton`/`_FixedHeightListView`/`_LimitedCombo`/`_CollapseToggle`）；提取时间格式化函数到 `gui/utils.py`（`fmt_rel`/`fmt_abs`）；`integrated_gui.py` 移除 `_CollapseToggle` 类定义，改从 widgets 导入；`filter_bar.py`/`drama_processing.py`/`trace_table.py`/`grouped_trace_view.py`/`monitor_tab.py` 同步更新导入路径
> - 2026-07-29: v1.9 — ...（略）
> - 2026-07-29: v1.8 — 航点篡改界面 `_TamperEntry` 新增「飞机高度」列（帧→飞机高度→基准飞机之间），显示格式 `基准飞机z(m)|被修改飞机z(m)`（如 `10.5m|20.3m`）；表头 `_COLUMNS`、`_GAP_PATTERN`、`COL_WIDTHS` 同步更新
> - 2026-07-29: v1.7 — `_try_write_drm_protobuf()` 重写：不再从 dict 重建 protobuf，改为直接解析原始 .drm → 在 protobuf 对象上修改 positionKeyFrames → 序列化写回；修复航点篡改输出丢失剧本信息（灯光/云台/Nova 等非位置关键帧及全局字段）的 bug；方法签名增加 `modified_wp` 参数
> - 2026-07-29: v1.6 — `_build_sim_configs()` airplane `known_param_types` 新增悬停测试电子围栏字段（`manual_enable`/`safe_distance`/`takeoff_height`/`hover_duration`）；新增 `update_hover_fence` / `update_hover_test` update 方法，通过 `_discover_update_methods` 自动生成 GUI 控件
> - 2026-07-29: v1.5 — `_TamperEntry` 帧/基准飞机/被修改飞机 下拉框从 `_LimitedCombo` 替换为 `_MultiSelectButton(single_select=True)`（与 UDP 监控 MsgID 过滤同款样式）；`_MultiSelectButton` 新增 `single_select` 参数 + `selected_key()`/`set_selected_key()` 单选 API
> - 2026-07-28: v1.4 — _TamperEntry 重构为表格式布局（QFrame 边框 + 勾选框）；表头全选勾选框；删除按钮改为批量删除勾选条目；确定修改仅处理勾选条目；全零帧 .drm 兼容（按索引生成顺序帧号）；表头"修改后最小距离"→"与其他飞机最小距离"
> - 2026-07-28: v1.3 — protobuf 7.x UTF-8 兼容修复：本地 `Drama3_pb2.py` (string→bytes) + `sys.modules` 注入机制；`drama_reader.py` 新增 `_safe_str()` 解码函数；`_try_write_drm_protobuf()` 内嵌 `_b()` 编码函数
> - 2026-07-28: v1.2 — 航点解析/对比功能从 `fake_airplane.py` 完全剥离至 `drama_processing.py` 模块级独立函数；`DramaProcessingPanel`/`WaypointParseComparePanel` 移除 sender getter 依赖
> - 2026-07-28: v1.1 — 新增 `DramaProcessingPanel` Tab（航点解析对比 + 航点篡改）；SimulationPanel 新增 `get_senders()` 公开方法；集成 `drama_processing.py` 模块
> - 2026-07-27: `_build_sim_configs()` 中 airplane 的 `known_param_types` 新增 19 个电池/电压字段类型（支持 `update_bat` **kwargs 类型推断）
> - 2026-07-23: 初始版本，基于 `integrated_gui.py` (3192 行) 创建
