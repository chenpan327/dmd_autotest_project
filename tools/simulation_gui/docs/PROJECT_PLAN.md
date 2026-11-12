# MAVLink UDP 实时监控工具 — 项目计划

> **版本**: v3.2
> **日期**: 2026-08-04
> **状态**: Phase 0-4 全部完成；Phase 5（优化完善）进行中 — 建议 2 完成；v3.2 性能优化：目标 5000 msg/s 不卡顿

---

## 目录

1. [需求概述](#1-需求概述)
2. [需求确认汇总](#2-需求确认汇总)
3. [技术选型](#3-技术选型)
4. [项目结构](#4-项目结构)
5. [架构设计](#5-架构设计)
6. [核心模块设计](#6-核心模块设计)
7. [GUI 布局设计](#7-gui-布局设计)
8. [独立解析器设计](#8-独立解析器设计)
9. [双模式监控架构](#9-双模式监控架构)
10. [配置导入机制](#10-配置导入机制)
11. [数据流与线程模型](#11-数据流与线程模型)
12. [实施计划与完成状态](#12-实施计划与完成状态)
13. [测试覆盖](#13-测试覆盖)
14. [决策记录](#14-决策记录)
15. [Phase 5 — 优化完善计划](#15-phase-5--优化完善计划)
16. [风险与注意事项](#16-风险与注意事项)

---

## 1. 需求概述

基于 MAVLink 协议规范（JSON 配置文件），开发一个**网络监控诊断工具**，类似 Wireshark + CANoe Trace 的结合体，用于实时捕获、解析和展示 MAVLink UDP 流量。

**核心功能：**

- **双模式监控**：网卡嗅探模式（混杂模式抓包）+ 端口绑定模式（socket 监听）
- **独立解析器**：不依赖 `parse_mavlink.py`，仅基于 `mavlink_config_v*.json` + `mavlink_enums_v*.json`
- 实时展示每条消息的**源/目的 IP:Port**、**MAVLink 头部**、**Payload 字段值**
- 参考 CANoe Trace Window：消息列表（默认折叠）→ 展开显示字段
- Payload 列统一截断 + hover tooltip 逐字段展示
- 数组字段（`char[N]` 等）自动显示 ASCII 可读行
- **隐藏列「真实目标IP」**：仅特殊格式（4 字节 IP 前缀）有值，按钮展开
- 双列时间戳（相对 / 绝对，可切换）
- 枚举值同时显示原始数值 + 枚举名称
- **CRC 失败消息仍解析字段**，仅 CRC 列红色标记 `✗`
- 全方位过滤：**方向(Tx/Rx)、MsgID+消息名、特殊格式、IP:Port、SysID/CompID、关键字、正则、高亮**
- Lazy parse：收到消息仅解析 header，展开时解析 payload 字段
- CRC 预计算查表（10× 提速）
- 可选日志记录（格式兼容现有 `test_log_*.log`）
- 环形缓冲 + 虚拟列表，适配 100-1000 msg/s
- 独立工具 + PySide6 Tab 集成两种形态

---

## 2. 需求确认汇总

| # | 问题 | 结论 |
|---|------|------|
| Q1 | 监控范围 | **A — 仅监控本机绑定的 UDP 端口（被动接收）** + 网卡嗅探模式（可选） |
| Q2 | 节点数量 | **同时监控多个节点，每个端口独立 socket 线程** |
| Q3 | GUI 框架 | **PySide6**（原计划 dearpygui，后因集成需求切换，见 D13） |
| Q4 | 工具形态 | **C — 独立工具 + MultiSimulationGUI Tab** |
| Q5 | 性能预期 | **B — 中等速率（100-1000 msg/s），环形缓冲 + 虚拟列表** |
| Q6 | 时间戳 | **C — 双列显示，可切换** |
| Q7 | 持久化 | **B — 可选日志（test_log_YYYYMMDD_HHMMSS.log）** |
| Q8 | 枚举解析 | **B — 同时显示原始数值和枚举名称** |
| Q9 | 过滤搜索 | **全部支持：Dir/MsgID+MsgName/特殊格式/IP:Port/SysID/CompID/关键字/正则/高亮** |
| Q10 | 非MAVLink包 | **A — 静默丢弃** |
| Q11 | 解析器策略 | **独立解析器，不调用 parse_mavlink.py** |
| Q12 | 配置导入 | **版本号后缀 OR 手动浏览两个 JSON 文件** |
| Q13 | 搜索路径 | **B — resources/config_default.json 存储可编辑搜索路径** |
| Q14 | CRC 优化 | **B — 预计算 256 条目查表** |
| Q15 | 解析策略 | **B — Lazy parse（header 立即解析，字段展开时解析）** |
| Q16 | CRC 失败处理 | **A — 仍显示并解析字段，CRC 列红色 ✗ 标记** |
| Q17 | 特殊格式 | **混合出现，逐包 auto-detect；隐藏列「真实目标IP」按钮展开** |
| Q18 | 日志 | **沿用 test_log_YYYYMMDD_HHMMSS.log 命名** |
| Q19 | 双模式 | **端口绑定（默认）+ 网卡嗅探（可选，需 Npcap）** |
| Q20 | 过滤扩展 | **Tx/Rx/MsgID(含消息名)/特殊格式 均做过滤** |

---

## 3. 技术选型

| 层面 | 选型 | 理由 |
|------|------|------|
| **语言** | Python 3.10+ | 与现有项目一致 |
| **GUI（独立 + 集成）** | `PySide6` ≥ 6.5 | 统一框架，独立窗口 + Tab 嵌入均用 PySide6；与 MultiSimulationGUI 同框架无缝集成 |
| **UDP 捕获（端口模式）** | Python `socket`（标准库） | 无额外依赖 |
| **UDP 捕获（网卡模式）** | `scapy` + Npcap 驱动 | 混杂模式抓包，需管理员权限 |
| **MAVLink 解析** | **独立实现**（`core/parser.py`） | 仅依赖 JSON 配置，不 import 外部 Python 模块 |
| **CRC 计算** | 自实现 x25crc（256 预计算查表） | 10× 提速，脱离上游耦合 |
| **配置加载** | JSON → dict（`json.load` + 类级缓存） | 与 `mavlink_config_v*.json` 一致 |
| **枚举映射** | 加载 `mavlink_enums_v*.json` | 已有完整数据 |
| **日志** | 自实现（格式兼容 `utils.logger`） | 避免跨项目依赖 |

---

## 4. 项目结构

```
mavlink_monitor/
├── PROJECT_PLAN.md                 ← 本文件
├── README.md
├── requirements.txt                ← PySide6>=6.5, scapy>=2.5, pytest>=8.0
├── integrated_gui.py                ← 唯一启动入口 (PySide6)
├── run_monitor.bat                 ← Windows 双击启动（实际调用 integrated_gui.py）
│
├── mavlink_monitor/
│   ├── __init__.py
│   │
│   ├── core/                       ← 核心引擎（框架无关，零外部依赖）
│   │   ├── __init__.py
│   │   ├── controller.py           ← MonitorController：引擎↔GUI 桥接层 ★新增
│   │   ├── paths.py                ← 统一路径解析：假项目/MAVLink版本目录/电台协议XML（`get_radio_message_xml()`）；电台消息配置源为 `simulation_gui/resources/DavMessage.proto`
│   │   ├── engine.py               ← MonitorEngine：端口绑定 + 网卡嗅探
│   │   ├── model.py                ← MonitorModel：环形缓冲 + MessageRecord
│   │   ├── parser.py               ← MavlinkParser：独立解析器（x25crc 查表）
│   │   ├── filter.py               ← MessageFilter：过滤器链 + 预置工厂方法
│   │   └── exporter.py             ← LogExporter：日志 + CSV/JSON 导出
│   │
│   ├── gui/                        ← PySide6 GUI（独立窗口）
│   │   ├── __init__.py
│   │   ├── main_window.py          ← QMainWindow：菜单 + 状态栏 + 布局 + 定时器
│   │   ├── left_panel.py           ← 左侧面板：配置 + 节点 + 统计（三合一）
│   │   ├── filter_bar.py           ← 过滤栏：MsgID/MsgName/特殊格式/字段/搜索/预设
│   │   ├── trace_table.py          ← Trace 表格：14列 + tooltip + 时间切换 + 复制
│   │   ├── detail_tree.py          ← 字段详情树：QTreeWidget + ASCII 行
│   │   ├── widgets.py              ← 共享控件：_MultiSelectButton / _LimitedCombo / _CollapseToggle
│   │   └── utils.py                ← 共享工具：fmt_rel / fmt_abs
│   │
│   └── integration/                ← PySide6 集成
│       ├── __init__.py
│       └── monitor_tab.py          ← QWidget 封装，可嵌入 QTabWidget
│
├── tests/
│   ├── __init__.py
│   ├── test_parser.py              ← 10 个测试类：CRC/格式检测/Header/字段/枚举/数组/配置/RelayIP/FieldDetail/CRCDisplay
│   ├── test_engine.py              ← 4 个测试类：PortNode/节点管理/生命周期/消息捕获
│   ├── test_filter.py              ← 6 个测试类：FilterRule/过滤应用/高亮/预置/规则管理/边界
│   ├── test_exporter.py            ← 格式化函数 + LogExporter 集成 + CSV/JSON 导出
│   └── test_integration.py         ← 端到端：Controller→Engine→Parser→Filter→Exporter
│
├── resources/
│   └── config_default.json         ← 搜索路径 + buffer 容量 + GUI 偏好
│
└── logs/
    └── (test_integration_*.log)    ← 集成测试生成的日志文件
```

### 与 v2.0 计划的关键差异

| 计划 (v2.0) | 实际 (v3.0) | 原因 |
|-------------|-------------|------|
| `gui/app.py` | `gui/main_window.py` | 命名更规范（QMainWindow 子类） |
| `gui/theme.py` | 无（颜色内联在各组件中） | 简化；颜色常量和 QColor 直接定义在 trace_table.py 等文件中 |
| `gui/node_panel.py` | 合并到 `gui/left_panel.py` | 配置 + 节点 + 统计紧密耦合，合并减少文件数 |
| `gui/config_section.py` | 合并到 `gui/left_panel.py` | 同上 |
| `gui/stats_panel.py` | 合并到 `gui/left_panel.py` | 同上 |
| `gui/trace_view.py` | `gui/trace_table.py` | 更准确描述组件类型（QTableWidget） |
| `gui/detail_panel.py` | `gui/detail_tree.py` | 更准确描述组件类型（QTreeWidget） |
| `core/controller.py` | **新增** | 引擎↔GUI 桥接，统一管理 parser/model/engine/filter/exporter 生命周期 |
| `resources/filter_presets.json` | 无（预置硬编码在 filter.py 静态工厂方法中） | 简化；5 个预设（heartbeat/identify/crc_fail/direction/special）足够用 |
| dearpygui GUI | PySide6 GUI | 集成需求：需与 MultiSimulationGUI（PySide6）同框架 |

---

## 5. 架构设计

### 5.1 分层架构

```
┌──────────────────────────────────────────────────────────┐
│                      表现层 (GUI)                         │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  PySide6 MainWindow / MonitorTab (统一框架)          │ │
│  │  ├── LeftPanel   (配置 + 节点 + 统计)                │ │
│  │  ├── FilterBar   (过滤控件)                          │ │
│  │  ├── TraceTable  (消息列表)                          │ │
│  │  └── DetailTree  (字段详情)                          │ │
│  └──────────┬───────────────────────────────────────────┘ │
│             │         轮询 / 回调（QTimer 50ms）          │
├─────────────┼────────────────────────────────────────────┤
│             │      控制器层 (Controller)                   │
│  ┌──────────┴────────────────────────────────────────────┐ │
│  │              MonitorController                         │ │
│  │  - 统一管理 parser / model / engine / filter /        │ │
│  │    exporter 的生命周期                                 │ │
│  │  - start/stop  |  add_port  |  set_interface          │ │
│  │  - get_new_records()  |  get_visible_records()        │ │
│  │  - parse_fields() (lazy)  |  get_stats()              │ │
│  │  - load_config / load_enums  |  set_filter_rules      │ │
│  │  - start_logging / log_record / stop_logging          │ │
│  └──────────┬────────────────────────────────────────────┘ │
│             │                                              │
├─────────────┼──────────────────────────────────────────────┤
│             │          核心层 (Core)                        │
│  ┌──────────┴──────┐ ┌──────────┐ ┌──────────────────┐    │
│  │  MonitorEngine  │ │  Model   │ │  MessageFilter   │    │
│  │  - 端口绑定线程 │ │(环形缓冲)│ │  (过滤链)        │    │
│  │  - 网卡嗅探线程 │ │          │ │  + 预置工厂方法  │    │
│  └──────────┬──────┘ └────┬─────┘ └────────┬─────────┘    │
│             │             │               │               │
│  ┌──────────┴─────────────┴───────────────┴──────────────┐ │
│  │        MavlinkParser（独立自实现）                      │ │
│  │  x25crc 查表 + struct.unpack + 版本识别 + 枚举        │ │
│  │  lazy parse: header first, fields on demand            │ │
│  └──────────┬────────────────────────────────────────────┘ │
│             │                                              │
│  ┌──────────┴──────────────┐                               │
│  │  LogExporter            │                               │
│  │  日志 + CSV/JSON 导出   │                               │
│  └─────────────────────────┘                               │
│             │                                              │
├─────────────┼──────────────────────────────────────────────┤
│             │          数据层（静态资源）                    │
│  ┌──────────┴────────────────────────────────────────────┐ │
│  │  mavlink_config_v*.json  │  mavlink_enums_v*.json     │ │
│  │  resources/config_default.json                         │ │
│  └───────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

---

## 6. 核心模块设计

### 6.1 MonitorController（桥接层）★ 实际新增

```
MonitorController
├── parser: MavlinkParser       ← 配置加载 + lazy parse
├── model: MonitorModel         ← 环形缓冲（线程安全）
├── engine: MonitorEngine       ← 端口绑定 + 网卡嗅探
├── filter: MessageFilter       ← 过滤链
├── exporter: LogExporter       ← 日志持久化
│
├── load_config(path, version)  → bool
├── load_enums(path, version)   → bool
├── add_port(ip, port, label, version) → node_id
├── start() / stop() / pause() / resume()
├── get_new_records()           → list[MessageRecord]  (增量拉取 + 过滤)
├── get_visible_records(n)      → list[MessageRecord]  (最近 n 条 + 过滤)
├── parse_fields(record)        → list[FieldDetail]    (lazy parse)
├── set_filter_rules(rules) / clear_filter()
├── get_stats()                 → dict
├── start_logging() / log_record() / stop_logging()
├── set_interface(name) / start_nic_mode() / stop_nic_mode()
├── set_udp_listener(...) / start_udp() / stop_udp()
├── set_radio_listener(...) / load_radio_config(...) / start_radio() / stop_radio()  ← 配置源 .proto/.xml/.json 按扩展名分流
├── inject_radio_packet(data, src_ip, src_port, dst_ip, dst_port) → bool  ← 假电台 DAV 帧注入
├── parse_fields(record)  ← 电台 DAV 按 msg_type 区分解析：Ack 帧(dav_report)直接解析 report；Msg 帧 protobuf wire 解析
└── reset_stats() / clear_buffer()
```

### 6.2 MonitorEngine — 双模式

```
┌─ MonitorEngine ─────────────────────────────────────┐
│                                                     │
│  mode: "port" | "interface" | "both"                │
│                                                     │
│  # 端口绑定模式                                      │
│  port_nodes: Dict[str, PortNode]                    │
│    ├─ node_id, local_ip, local_port, label          │
│    ├─ sock: socket.socket                           │
│    └─ thread: threading.Thread                      │
│                                                     │
│  # 网卡嗅探模式                                      │
│  interface_node: InterfaceNode | None               │
│    ├─ interface_name: str (e.g. "WLAN 6")           │
│    ├─ sniffer: scapy.AsyncSniffer                   │
│    └─ running: bool                                 │
│                                                     │
│  Methods:                                           │
│    add_port(ip, port, label) → node_id              │
│    remove_port(node_id)                             │
│    set_interface(name)                              │
│    start() / stop() / pause() / resume()            │
│    start_sniffing() / stop_sniffing()               │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 6.3 MavlinkParser — Lazy Parse

```
解析分两阶段:

Phase 1（收到包立即执行）:
  - 格式检测（魔数 / 4字节IP前缀）
  - 解析 header（start, len, seq, sys_id, comp_id, msg_id）
  - CRC 校验（可选，默认关闭以提升吞吐）
  - 构建 MessageRecord（payload 以 bytes 保留，fields 为空）
  → 入环形缓冲

Phase 2（用户展开/点击时执行）:
  - struct.unpack(config.fmt, payload_bytes)
  - 变量名合并（ssid[0]..ssid[7] → ssid: bytes）
  - 枚举映射（type=2 → "MAV_TYPE_QUADROTOR"）
  - 构建 fields 列表
  → 缓存到 MessageRecord.fields，后续不再重复解析
```

### 6.4 MessageFilter

```
过滤器链，每个 FilterRule 可独立启停:
  - DirRule:    dir == "Rx" / dir == "Tx"
  - MsgIdRule:  msg_id in [0, 2, 3, ...]
  - MsgNameRule: msg_name matches pattern
  - SpecialRule: format == "ip_prefixed"
  - FieldRule:  任意字段 eq/neq/contains/regex
  - SearchRule: 全文搜索（含正则）+ 高亮

预置模板（静态工厂方法）:
  preset_heartbeat()    → msg_id=0
  preset_identify()     → msg_id in {2,3}
  preset_crc_fail()     → 高亮 CRC 失败
  preset_direction(dir) → Rx 或 Tx
  preset_special_format() → ip_prefixed 格式
```

### 6.5 LogExporter

```
日志命名: test_log_YYYYMMDD_HHMMSS.log
格式:
  [2026-07-02 15:30:45.123456] MAVLINK Rx
    Src:  172.17.3.176:14551
    Dst:  172.16.200.1:14550
    Msg:  HEARTBEAT (id=0)
    CRC:  OK (0x7BDB)    或  ✗ FAIL (calc=0x7BDB, frame=0xA1C3)
    Format: standard  (或 ip_prefixed (Relay: 172.17.3.200))
    Fields:
      type = 2 (MAV_TYPE_QUADROTOR)
      ssid = 44 4D 44 5F 55 41 56 00 (ASCII: 'DMD_UAV\0')

批量导出:
  export_csv(records, filepath)
  export_json(records, filepath)
```

---

## 7. GUI 布局设计

### 7.1 实际布局（PySide6 实现）

```
┌─ MAVLink UDP Monitor ─────────────────────────────────────┐
│ File  View                                                  │
├──────────────┬────────────────────────────────────────────┤
│┌─ Mavlink配置┐│ ┌─ Filter ──────────────────────────────┐ │
││ 目录: [...] ││ │MsgID:[___] Msg:[___] [特殊格式]       │ │
││ [扫描] v41▾ ││ │[全部▾][=▾][___] [快速搜索...]        │ │
││ [OK] 就绪   ││ │[正则][高亮] [心跳][识别][CRC失败][清除]│ │
│├─ 监控节点 ──┤│ └────────────────────────────────────────┘ │
││ ○ 端口绑定  ││ ┌─ Trace ────────────────────────────────┐ │
││ ○ 网卡嗅探  ││ │[时间: 相对][真实目标IP][||暂停][清空] │ │
││ IP:[___]    ││ │        [复制选中]                       │ │
││ Port:[14550]││ │ # │Time(Rel)│Src│Dst│Msg│ID│...│CRC   │ │
││ [+]         ││ │─────────────────────────────────────── │ │
││ ☑ 节点列表  ││ │ 1 +0.00 172… HEARTBEAT 0x00 … ✓      │ │
│├─ 统计 ─────┤│ │ 2 +0.12 172… HEARTBEAT_DMD … ✓        │ │
││ Total: 0   ││ │ ...                                      │ │
││ Rate: 0/s  ││ └──────────────────────────────────────────┘ │
││ Errors: 0  ││ ┌─ Detail (QTreeWidget) ──────────────────┐ │
││ Buffer:0   ││ │ 字段名   解析值          原始Hex   类型  │ │
││ Uptime:... ││ │ id       1               01        uint8 │ │
│└────────────┘│ │   -> ASCII DMD_UAV\0                     │ │
│              │ └──────────────────────────────────────────┘ │
├──────────────┴────────────────────────────────────────────┤
│ Ready │ Nodes: 0 │ Buffer: 0/10000 │ FPS: --               │
└──────────────────────────────────────────────────────────┘
```

### 7.2 配色（内联在 trace_table.py 中）

| 元素 | 颜色 | Hex |
|------|------|-----|
| 背景 | 深灰 | Fusion 默认 |
| Rx / 源 IP / 方向 Rx | 青绿 | `#4EC9B0` |
| Tx / 目的 IP / 方向 Tx | 橙棕 | `#CE9178` |
| HEARTBEAT 消息名 | 蓝 | `#569CD6` |
| IDENTIFY 消息名 | 紫 | `#C586C0` |
| COMMAND/SET_ 消息名 | 黄 | `#DCDCAA` |
| CRC OK | 绿 | `#6A9955` |
| CRC Fail / 错误 | 红 | `#F44747` |
| ASCII 可读行 | 绿 | `#6A9955` |
| 隐藏列「真实目标IP」 | 黄 | `#DCDCAA` |
| 次要文字 | 灰 | `#969696` |

### 7.3 Trace 列定义（13 列）

| # | 列名 | 宽度 | 默认隐藏 | 说明 |
|---|------|------|----------|------|
| 1 | # | 48 | | 全局递增序号 |
| 2 | Time (Rel) | 160 | | 相对时间 |
| 3 | Time (Abs) | 160 | ✓ | 绝对时间（默认隐藏） |
| 4 | Src IP:Port | 165 | | 源地址 |
| 5 | Dst IP:Port | 165 | | 目的地址 |
| 6 | 真实目标IP | 130 | ✓ | 特殊格式 relay IP，普通格式 `—` |
| 7 | Msg Name | 140 | | 消息名，按类型着色 |
| 8 | MsgID | 60 | | `0x00` 格式 |
| 9 | Sys | 40 | | sys_id |
| 10 | Comp | 44 | | comp_id |
| 11 | Len | 40 | | payload 长度 |
| 12 | Payload | 170 | | 截断 hex + hover tooltip（含 ASCII 行) |
| 13 | CRC | 80 | | `OK 0x7BDB`（绿）/ `FAIL 0xA1C3`（红） |

### 7.4 时间模式切换

时间按钮循环切换三种模式：
- **时间: 绝对** — 仅显示 Abs 列
- **时间: 相对** — 仅显示 Rel 列（默认）
- **时间: 双列** — 同时显示 Rel + Abs

---

## 8. 独立解析器设计

### 8.1 设计原则

- **零外部 Python 依赖**：不 import `parse_mavlink.py` / `mavcrc.py` 等
- **仅依赖 JSON 数据**：`mavlink_config_v*.json` + `mavlink_enums_v*.json`
- **Lazy parse**：header 立即解析，字段按需展开
- **CRC 查表**：256 条目预计算，O(1)/byte
- **CRC 默认关闭**：`crc_enabled=False`，仅测试时开启以提升吞吐

### 8.2 核心解析流程

```
data (bytes), src_addr, dst_addr, timestamp
         │
         ▼
  ┌─ _detect_format ─────────────────────┐
  │  data[0] ∈ {0xFE, 0xFD}?             │
  │    YES → "standard", data, None       │
  │    NO  → data[4] ∈ {0xFE, 0xFD}?     │
  │           YES → "ip_prefixed",        │
  │                 data[4:], inet_ntoa() │
  │           NO  → 魔数失败 → None       │
  └──────────────┬────────────────────────┘
                 ▼
  ┌─ _parse_header (EAGER) ─────────────┐
  │  struct.unpack('BBBBBB', data[0:6]) │
  │    → start, len, seq, sys, comp, mid│
  │  CRC: x25crc(data[1:6+len])          │
  │       + crc_extra → crc_ok/bad       │
  │  payload_bytes = data[6:6+len]       │
  └──────────────┬────────────────────────┘
                 ▼
           MessageRecord
           (fields=[] 空，payload_bytes 保留)
                 │
                 ▼  用户展开时触发
  ┌─ _parse_fields (LAZY) ──────────────┐
  │  struct.unpack(config.fmt, payload)  │
  │  → raw_values → 变量名合并          │
  │  → 枚举映射（查 enums JSON）         │
  │  → FieldDetail 列表                  │
  │  → 回填并缓存到 record.fields        │
  └──────────────────────────────────────┘
```

### 8.3 CRC 预计算查表

```python
class x25crc:
    # 预计算 256 条目查找表（多项式 0x1021）
    _TABLE = [0] * 256
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
        _TABLE[i] = crc & 0xFFFF

    def accumulate(self, buf):
        accum = self.crc
        for b in buf:
            accum = ((accum << 8) ^ self._TABLE[((accum >> 8) ^ b) & 0xFF]) & 0xFFFF
        self.crc = accum
# 实测 ~10× 提速（25μs → 2.5μs / 50 bytes）
```

### 8.4 枚举映射策略

```
_VARIABLE_ENUM_MAP:
  "type"          → "MAV_TYPE"
  "autopilot"     → "MAV_AUTOPILOT"
  "base_mode"     → "MAV_MODE_FLAG"
  "system_status" → "MAV_STATE"
  "severity"      → "MAV_SEVERITY"
  "custom_mode"   → None      (位掩码，不映射)
  "mavlink_version" → None

显示格式: "MAV_TYPE_QUADROTOR (2)"
未知枚举值仅显示数字: "255"
```

### 8.5 数组变量合并

```
输入:  [ssid[0]=0x44, ssid[1]=0x4D, ssid[2]=0x44, ...]
       → 正则检测 /^(.+)\[\d+\]$/
       → 按 base name 分组 + 按索引排序
       → 合并为 ssid: bytes([0x44, 0x4D, 0x44, ...])
       → type_name: "char[8]"

单元素数组（如 ssid[0] 单独出现）→ 不合并，保留原名
```

---

## 9. 双模式监控架构

### 9.1 模式对比

| | 端口绑定（默认） | 网卡嗅探（可选） |
|--|-----------------|-----------------|
| **原理** | `socket.bind((ip, port))` | scapy/AsyncSniffer 混杂模式 |
| **需要依赖** | 无（Python stdlib） | `scapy` + Npcap 驱动 |
| **需要权限** | 无需 | **管理员权限** |
| **配置** | 指定 (IP, Port) | 选择网卡即可 |
| **抓包范围** | 仅发往该端口的 UDP | 经过该网卡的所有 UDP |
| **过滤** | 操作系统层面 | 应用层按魔数过滤 |
| **适用场景** | 已知端口、自动化测试 | 未知端口、现场诊断 |

### 9.2 GUI 切换

```
┌─ 监控节点 ────────────────────┐
│ ○ 端口绑定                    │
│ ○ 网卡嗅探                    │
│   网卡: [WLAN 6 ▼]  [开始嗅探]│
│                                │
│ IP: [172.16.200.1]            │
│ Port: [14550]           [+]   │
│ ☑ 172.16.200.1:14550          │
└────────────────────────────────┘
```

两种模式通过 RadioButton 切换 UI，引擎层面通过 `start()` vs `start_nic_mode()` 区分。

---

## 10. 配置导入机制

### 10.1 两种方式

**方式 A — 版本号后缀**：
```
用户选择版本 → 从 resources/config_default.json 的 search_paths 中查找
  → mavlink_config_v{version}.json
  → mavlink_enums_v{version}.json
  → [OK] 就绪 / [--] 仅 Config / [OFF] 未加载
```

`resources/config_default.json`：
```json
{
  "search_paths": [
    "../../file/mavlink_version",
    "D:/Work/dmd_autotest_project_ycl/file/mavlink_version"
  ],
  "buffer_capacity": 10000,
  "payload_max_chars": 26,
  "log_dir": "./logs"
}
```

**方式 B — 手动浏览**：
```
点击 [...] 按钮 → 系统文件对话框 → 选择目录 → 自动扫描目录下所有版本
```

### 10.2 状态指示

| 文字 | 含义 |
|------|------|
| `[OK] Config + Enums 就绪` | Config + Enums 均已加载 |
| `[--] 仅 Config 就绪` | 仅 Config 加载（枚举映射不可用） |
| `[OFF] 未加载` | 未加载 |

---

## 11. 数据流与线程模型

```
┌─ Main Thread (GUI)  ~20 FPS (QTimer 50ms) ─────────────┐
│  - _on_tick(): controller.get_new_records()             │
│    → trace_table.add_record() → trim_rows(500)          │
│  - 用户交互: 点击行 → lazy parse → detail_tree          │
│  - 过滤变更 → controller.set_filter_rules()             │
│  - 统计刷新 → left_panel.update_stats()                 │
└──────────────────────┬─────────────────────────────────┘
                       │ 轮询 (MonitorController)
┌──────────────────────┼─────────────────────────────────┐
│      MonitorModel (Thread-Safe Deque, 无上限)           │
│      实际: 简单 deque + threading.Lock，未设 maxlen     │
└──────────────────────┬─────────────────────────────────┘
                       │ append()
        ┌──────────────┼──────────────┐
        │              │              │
┌───────┴──────┐ ┌────┴─────┐ ┌─────┴────────┐
│ Port Thread 1│ │Port Thr 2│ │ Sniffer Thr  │
│ recvfrom →   │ │          │ │ sniff →      │
│ parse_header │ │          │ │ filter UDP   │
│ → append     │ │          │ │ → parse      │
└──────────────┘ └──────────┘ │ → append     │
                              └──────────────┘
```

---

## 12. 实施计划与完成状态

### Phase 0 — GUI 框架 ✅ 已完成（实际用 PySide6 而非 dearpygui）

| # | 文件 | 功能 | 状态 |
|---|------|------|------|
| 0.1 | `gui/main_window.py` | QMainWindow + 菜单 + 状态栏 + QTimer 轮询 | ✅ |
| 0.2 | `gui/left_panel.py` | 左侧面板（配置 + 节点管理 + 统计，三合一） | ✅ |
| 0.3 | `gui/filter_bar.py` | 过滤栏（MsgID/MsgName/特殊格式/字段/搜索/预设） | ✅ |
| 0.4 | `gui/trace_table.py` | Trace 表格（13列 + tooltip + 时间切换 + 复制选中） | ✅ |
| 0.5 | `gui/detail_tree.py` | 字段详情树（QTreeWidget + ASCII 行） | ✅ |
| 0.6 | `integrated_gui.py` | 启动入口（PySide6） | ✅ |
| 0.7 | `run_monitor.bat` | Windows 双击启动（调用 integrated_gui.py） | ✅ |

### Phase 1 — 核心引擎 ✅ 已完成

| # | 文件 | 功能 | 状态 |
|---|------|------|------|
| 1.1 | `core/parser.py` | 独立解析器（x25crc 查表 + struct + lazy parse + 枚举） | ✅ |
| 1.2 | `core/model.py` | MonitorModel + MessageRecord + FieldDetail（线程安全） | ✅ |
| 1.3 | `core/engine.py` | 端口绑定（多端口多线程）+ 网卡嗅探（scapy AsyncSniffer） | ✅ |
| 1.4 | `core/filter.py` | 过滤器链（Dir/MsgID/特殊格式/字段/搜索/正则）+ 预置工厂方法 | ✅ |
| 1.5 | `core/exporter.py` | 日志（test_log_*.log 格式）+ CSV/JSON 批量导出 | ✅ |
| 1.6 | `core/controller.py` | **MonitorController 桥接层**（引擎↔GUI 统一接口） | ✅ |

### Phase 2 — Engine ↔ GUI 对接 ✅ 已完成

| # | 任务 | 状态 |
|---|------|------|
| 2.1 | Controller 统一管理 parser/model/engine/filter/exporter 生命周期 | ✅ |
| 2.2 | QTimer 50ms 轮询 → `get_new_records()` → 增量更新 Trace 表格 | ✅ |
| 2.3 | `trim_rows(500)` 自动裁剪旧行 | ✅ |
| 2.4 | 统计面板实时数据（left_panel.update_stats） | ✅ |
| 2.5 | 过滤栏 ↔ `controller.set_filter_rules()` 对接 | ✅ |
| 2.6 | 点击行 → `controller.parse_fields()` → lazy parse → DetailTree | ✅ |
| 2.7 | 配置变更 → 版本切换 → `controller.load_config/enums` | ✅ |
| 2.8 | 日志开关 `start_logging()` / `log_record()` / `stop_logging()` | ✅ |

### Phase 3 — 网卡嗅探模式 ✅ 已完成

| # | 任务 | 状态 |
|---|------|------|
| 3.1 | `engine.py` — scapy AsyncSniffer 集成 + `_sniff_callback` | ✅ |
| 3.2 | GUI RadioButton 切换（端口绑定 / 网卡嗅探） | ✅ |
| 3.3 | powershell Get-NetAdapter 获取网卡列表 | ✅ |
| 3.4 | `controller.start_nic_mode()` / `stop_nic_mode()` | ✅ |
| 3.5 | 网卡嗅探 → UDP filter → 魔数过滤 → parse_header → 入缓冲 | ✅ |

### Phase 4 — PySide6 集成 + 最终完善 ✅ 已完成

| # | 任务 | 状态 |
|---|------|------|
| 4.1 | `integration/monitor_tab.py` — QWidget 封装，可嵌入 QTabWidget | ✅ |
| 4.2 | CSV/JSON 导出（File 菜单） | ✅ |
| 4.3 | 时间戳切换（相对/绝对/双列） | ✅ |
| 4.4 | 隐藏列「真实目标IP」按钮展开 | ✅ |
| 4.5 | 暂停滚动 / 复制选中行 | ✅ |
| 4.6 | `run_monitor.bat` + README 文档（指向 integrated_gui.py） | ✅ |
| 4.7 | 单元测试 + 集成测试全覆盖 | ✅ |

---

## 13. 测试覆盖

### 13.1 测试文件总览

| 文件 | 测试类数 | 覆盖范围 |
|------|----------|----------|
| `tests/test_parser.py` | 10 | CRC计算、格式检测、Header解析、字段解包、枚举映射、数组合并、配置加载、RelayIP、FieldDetail属性、CRC显示 |
| `tests/test_engine.py` | 4 | PortNode、节点管理CRUD、引擎生命周期启停暂停、消息捕获（标准/IP前缀/非MAVLink丢弃/批量/暂停） |
| `tests/test_filter.py` | 6 | FilterRule、过滤应用（dir/msgid/msgname/special/srcip/dstip/sysid/compid/search/crc/组合AND）、高亮模式、预置工厂方法、规则管理、边界条件 |
| `tests/test_exporter.py` | 7+ | hex_to_ascii、时间戳格式化、CRC格式化、字段格式化、LogExporter集成（写入/多记录/CRC失败/raw payload）、CSV导出、JSON导出 |
| `tests/test_integration.py` | 3 | 端到端流水线（配置→引擎→捕获→解析→过滤→导出）、暂停恢复、统计接口 |

### 13.2 运行测试

```bash
cd D:/Work/My_Project_Local/mavlink_monitor
pytest tests/ -v
# 需要: mavlink_config_v41.json 和 mavlink_enums_v41.json 在已知路径
```

### 13.3 测试依赖的外部文件

测试硬编码引用以下路径（需要存在才能通过）：
```
D:\Work\dmd_autotest_project_ycl\file\mavlink_version\mavlink_config_v41.json
D:\Work\dmd_autotest_project_ycl\file\mavlink_version\mavlink_enums_v41.json
```

---

## 14. 决策记录

| ID | 日期 | 问题 | 决策 |
|----|------|------|------|
| D01 | 0702 | GUI 框架 | ~~dearpygui ≥ 2.3.1~~ → 变更为 PySide6（D13） |
| D02 | 0702 | 解析器依赖 | 独立实现，不调用 parse_mavlink.py |
| D03 | 0702 | CRC 算法 | 自实现 x25crc + 256 预计算查表 |
| D04 | 0702 | 解析策略 | Lazy parse（header eager，fields on demand） |
| D05 | 0702 | 配置搜索路径 | `resources/config_default.json` 可配置 |
| D06 | 0702 | CRC 失败处理 | 显示 + 红色标记 + 仍解析字段 |
| D07 | 0702 | 特殊格式 | 逐包 auto-detect + 隐藏列「真实目标IP」 |
| D08 | 0702 | 过滤维度 | Dir/MsgID+MsgName/特殊格式/IP:Port/SysID/CompID/全文/正则 |
| D09 | 0702 | 监控模式 | 双模式：端口绑定（默认）+ 网卡嗅探（可选） |
| D10 | 0702 | 日志命名 | test_log_YYYYMMDD_HHMMSS.log |
| D11 | 0702 | 非 MAVLink 包 | 静默丢弃 |
| D12 | 0702 | 工具形态 | 独立工具（PySide6 窗口）+ MultiSimGUI Tab（PySide6） |
| **D13** | **0703** | **GUI 框架切换** | **从 dearpygui 切换到 PySide6**。原因：(1) 与 MultiSimulationGUI 统一框架，Tab 嵌入零成本；(2) 无需维护两套 GUI 代码；(3) PySide6 QTableWidget/QTreeWidget 生态成熟稳定 |
| D14 | 0703 | Controller 层 | 新增 MonitorController 作为引擎→GUI 桥接层，统一管理生命周期，GUI 代码零散直接操作 core 模块 |
| D15 | 0703 | GUI 文件结构 | 合并 node_panel + config_section + stats_panel → left_panel.py，减少碎片文件 |
| D16 | 0703 | 过滤预置 | 预置模板用静态工厂方法硬编码在 filter.py，不创建 resources/filter_presets.json |
| D17 | 0703 | CRC 默认策略 | 生产环境 `crc_enabled=False`（吞吐优先），测试环境按需开启 |

---

## 15. Phase 5 — 优化完善计划

> **目标**: 修复已知缺陷、补齐功能缺口、提升工程质量
> **预计工期**: 3-5 天

### 15.1 Bug 修复（P0 — 必须修复）

> **v3.2 性能优化**: B2 已修复。新增以下优化以支持 5000 msg/s 吞吐：
> - `MonitorModel.append_batch()` — 批量写入，锁获取从 5000次/s → ~78次/s（63× 减少）
> - `MonitorEngine._batch_buffer` — 引擎端批量缓冲，每 64 条或 1s 刷新
> - `MessageRecord.payload_hex/payload_display` — 延迟计算（@property），热路径不再预计算 hex
> - `TraceTableModel(QAbstractTableModel)` — 虚拟列表替换 QTableWidget，只渲染可见行
> - `FullUdpMonitorPanel` — 自适应刷新率（50-200ms），display_limit 10000→100000
> - `MonitorController` — capacity 从 40960000 → 4096000

| # | 问题 | 影响范围 | 修复方案 |
|---|------|----------|----------|
| **B1** | 过滤栏 CRC 过滤字段名不一致 | `filter_bar.py:117` `_preset("crc_fail")` 设置 `field="CRC"`，但 `filter.py:141` `_match_one()` 中的分支是 `field == "crc"`（小写），永远不命中 | 统一为 `"crc"`（小写） |
| **B2** | ~~环形缓冲无上限 — 潜在内存泄漏~~ ✅ 已修复 (v3.2) | `model.py:116` deque 已设 maxlen=capacity（默认 4096000），自动淘汰旧记录；新增 `append_batch()` 批量写入减少锁竞争 63× | — |
| **B3** | 网卡列表扫描不全，缺少以太网 | `left_panel.py:15-31` `_get_interfaces()` 使用 `Get-NetAdapter \| Select-Object -ExpandProperty Name`，部分网卡（特别是物理以太网卡）未被列出 | 改用更全面的获取方式：`Get-NetAdapter \| Select-Object Name, InterfaceDescription \| Format-List`，或 fallback 到 `scapy.all.get_if_list()` |
| **B4** | 网卡名称显示乱码 | `left_panel.py:22` subprocess 的 `encoding=sys.getdefaultencoding()` 在某些 Windows 中文系统下为 `gbk`，但 powershell 返回 UTF-8，导致中文网卡名乱码 | 固定 `encoding="utf-8"` + `errors="replace"`，或改用 `chcp 65001` 后执行 powershell |

### 15.2 功能补全（P1 — 影响可用性）

| # | 项目 | 说明 |
|---|------|------|
| **F1** | CRC 可见控制 | 当前 `crc_enabled=False` 硬编码，无 GUI 开关；在配置面板增加 CRC 校验开关，默认关闭 |
| **F2** | Direction 自动判定 | `parse_header()` 硬编码 `direction="Rx"`；通过比较 `src_addr`/`dst_addr` 与本机 IP 自动判断 Rx/Tx，或提供手动标记 |
| **F3** | MonitorTab 功能对齐 MainWindow | `integration/monitor_tab.py` 缺少版本扫描、网卡列表、过滤栏预设等；补齐，使 Tab 嵌入模式与独立窗口体验一致 |
| **F4** | 日志自动记录 | 当前需手动调用 `start_logging()` / `log_record()`；增加"自动记录所有消息到日志"开关 |
| **F5** | Payload tooltip 字段过多时截断 | `trace_table.py:218-240` `eventFilter()` 中 hover 时对所有已解析字段逐行展示；当字段数 >20 时 tooltip 过长撑出屏幕。改为：(1) 默认只展示前 N 个字段（如 15 个），(2) 末行显示 `… 共 M 个字段，点击行在详情面板查看全部` |

### 15.3 测试增强（P2 — 可测试性与可移植性）

| # | 项目 | 说明 |
|---|------|------|
| **T1** | 测试路径去硬编码 | `test_parser.py`/`test_engine.py`/`test_integration.py` 硬编码 `D:\Work\dmd_autotest_project_ycl\file\mavlink_version\`；改为 `pytest.fixture` 读取环境变量或 `resources/config_default.json` 中的路径，让其他开发者能跑测试 |
| **T2** | 网卡嗅探单元测试 | 当前 sniffing 模式无测试覆盖；用 mock scapy 或 loopback 接口补充 |
| **T3** | GUI 自动化测试 | 基于 `pytest-qt` 增加核心交互路径的回归测试（启动→加载配置→添加端口→收发消息→过滤→导出） |

### 15.4 工程化（P3 — 长期可维护性）

| # | 项目 | 说明 |
|---|------|------|
| **E1** | `pyproject.toml` | 替换 `requirements.txt`，定义 build system + 依赖 + pytest 配置 |
| **E2** | 测试配置集中化 | 将 `CONFIG_PATH`/`ENUMS_PATH` 集中在 `tests/conftest.py` 的 fixtures 中 |
| **E3** | 类型检查 | 配置 mypy/pyright，修复类型错误 |
| **E4** | 代码覆盖率 | 配置 `pytest-cov`，设最低覆盖率阈值（如 80%） |
| **E5** | 日志文件清理 | `logs/` 目录已积累 17 个集成测试日志（~50KB），增加 `.gitignore` 或测试后自动清理 |

### 15.5 实施顺序建议

```
Day 1: B1, B2, B3, B4    ← Bug 修复（CRC过滤/内存泄漏/网卡扫描不全/乱码）
Day 2: F1, F2, F5         ← 功能补全（CRC开关/Direction判定/Payload tooltip截断）
Day 3: F3, F4, T1, T2     ← MonitorTab对齐 + 日志自动记录 + 测试可移植
Day 4: E1, E2, E3, E4     ← 工程化基础（pyproject.toml/conftest/类型检查/覆盖率）
Day 5: T3, E5, 全量回归   ← GUI测试 + 日志清理 + 全链路回归验证
```

---

## 16. Phase 6 — 分组消息视图 (CANoe 风格)

> **目标**: 新增按 `(src_ip, dst_ip, msg_id)` 分组的消息视图，类似 CANoe Trace 的 CAN ID 分组模式
> **日期**: 2026-07-15
> **状态**: 待实施

### 16.1 需求确认

| # | 问题 | 结论 |
|---|------|------|
| Q1 | 分组键 IP | **Src IP + Dst IP + MsgID** — 按完整通信对 + 消息类型分组 |
| Q2 | 模式切换 | **同一区域 QStackedWidget 切换**（按钮"分组视图"↔"时间序视图"） |
| Q3 | 旧数据清理 | **按总消息数** — 所有分组总消息 ≤ display_limit，移除最旧消息 |
| Q4 | 分组摘要列 | **完整摘要** — Src IP \| Dst IP \| Msg Name (MsgID) \| Count \| Last Time \| Direction |

### 16.2 设计方案

#### 分组视图布局

```
┌─ Grouped View ───────────────────────────────────────────────────┐
│ [时间: 相对]  [|| 暂停]  [清空]                                    │
├──────────────────────────────────────────────────────────────────┤
│ Src IP       │ Dst IP       │ Msg Name (ID)  │ Count│Time │Dir   │
├──────────────┼──────────────┼────────────────┼──────┼─────┼──────┤
│▶ 172.17.3.176│172.16.200.1  │HEARTBEAT(0x00) │  342 │...  │Rx    │
│  ├ +0.000    │14551→14550   │HEARTBEAT 0x00 1 1 10 A1B2… OK     │
│  ├ +1.002    │14551→14550   │HEARTBEAT 0x00 1 1 10 C3D4… OK     │
│▶ 172.16.200.1│172.17.3.176  │COMMAND(0x4C)   │   12 │...  │Tx    │
│▶ 172.17.3.176│172.16.200.1  │PARAM_SET(0x17) │    5 │...  │Rx    │
│  ├ +2.500    │14551→14550   │PARAM_SET 0x17 1 1 164 A1B2… OK    │
```

#### 核心数据结构

```python
@dataclass
class _GroupInfo:
    tree_item: QTreeWidgetItem   # 顶层分组节点
    records: deque                # MessageRecord 双端队列，按时间排序
    count: int                    # 子消息数
    last_timestamp_abs: float     # 最新消息时间
    directions: set[str]          # {"Rx"} / {"Tx"} / {"Rx","Tx"}

# O(1) 分组查找
_groups: dict[tuple, _GroupInfo]  # key = (src_ip, dst_ip, msg_id)
```

#### 分组节点列（3 列，列 0-2，始终可见）

| # | 列名 | 宽度 | 数据 |
|---|------|------|------|
| 0 | Src IP | 140 | `record.src_ip` |
| 1 | Dst IP | 140 | `record.dst_ip` |
| 2 | Message | 180 | `f"{msg_name} (0x{msg_id:02X})"` |

#### 子消息列（共 12 列，相对/绝对时间二选一，无双列模式）

| # | 列名 | 宽度 | 默认 | 数据 |
|---|------|------|------|------|
| 2 | Message | 180 | 可见 | `msg_name`（复用分组 Message 列） |
| 3 | Time(Rel) | 160 | **可见** | `_fmt_rel(timestamp_rel)` — HH:MM:SS.ffffff |
| 4 | Time(Abs) | 160 | 隐藏 | `_fmt_abs(timestamp_abs)` — datetime.fromtimestamp → HH:MM:SS.ffffff（不展示年月日，但原始数据保留完整时间戳） |
| 5 | Ports | 115 | 可见 | `f"{src_port}->{dst_port}"` |
| 6 | MsgID | 55 | 可见 | `0xXX` |
| 7 | Sys | 40 | 可见 | `sys_id` |
| 8 | Comp | 44 | 可见 | `comp_id` |
| 9 | Len | 40 | 可见 | `payload_len` |
| 10 | Payload | 170 | 可见 | 截断 hex |
| 11 | CRC | 80 | 可见 | `f"0x{record.crc_actual:04X}"` — 帧原始 CRC，不校验 |

#### 视图切换行为（Q16.5 — 2026-07-15 修订）

| # | 问题 | 结论 |
|---|------|------|
| Q16.5.1 | 切换时重建范围 | **所有消息** — 从 model 全量重建，忽略过滤条件 |
| Q16.5.2 | 实时更新策略 | **双视图同步更新** — `_on_tick` 同时向两个视图 add + trim，无论哪个处于活跃状态 |
| Q16.5.3 | 暂停时切换 | 切换后从 model 全量重建目标视图 |

**实现要点**：
- `_on_tick` 移除 `currentIndex()` 路由判断，始终向两个视图同时推送记录
- `_on_toggle_view_mode` 切换到分组 → `_rebuild_grouped_view()`；切换到时间序 → `_rebuild_trace_table()`
- 新增 `_rebuild_trace_table()`：清空 → 遍历 `model.get_all()` 或 `get_visible_records(max_count=display_limit)` → 逐条 add
- 过滤变更时不重建视图（过滤仅影响后续新消息），除非用户手动要求

#### 关键算法

**add_record**: O(1) dict 查找/创建分组 → 追加子节点 → 更新摘要 → 超限触发 trim
**trim_messages**: 扫描所有分组找最旧首条消息 → 移除（O(num_groups)，分组数 < 500）
**clear**: 清空 dict + tree
**_rebuild**: 过滤变更时从 `get_visible_records()` 全量重建

### 16.3 实施步骤

| # | 文件 | 操作 | 说明 |
|---|------|------|------|
| 1 | `gui/grouped_trace_view.py` | **新建** | ~450 行 QWidget，含 QTreeWidget + 工具栏 + _GroupInfo |
| 2 | `gui/trace_table.py` | 修改 | 新增 `on_record_clicked` 信号（保留旧 `on_row_clicked`） |
| 3 | `gui/main_window.py` | 修改 | QStackedWidget + 模式切换按钮 + `_on_tick` 路由 + `_on_record_clicked` 统一处理 |

### 16.4 验证方案

1. 启动 `integrated_gui.py`，默认时间序视图功能不变
2. 点击"分组视图"切换到 Mode 2
3. 验证消息按 `(src_ip, dst_ip, msg_id)` 分组、新消息自动归组、分组摘要正确
4. 验证展开分组后消息按时间排序、点击子消息 DetailTree 正确显示字段
5. 验证暂停/清空/过滤/显示上限在分组模式下均正常
6. 运行 `python -m pytest tests/ -v` 确保无回归

---

## 17. 风险与注意事项

| 风险 | 影响 | 缓解 |
|------|------|------|
| ~~dearpgui 2.x API 差异~~ | ~~已解决~~ | **已切换到 PySide6，此风险消除** |
| 独立解析器与 JSON 耦合 | 中 | JSON 格式由 extract 脚本生成，约定稳定 |
| 多线程 UDP 绑定冲突 | 低 | SO_REUSEADDR + 不同 (IP, Port) |
| 高消息速率 GUI 卡顿 | 中 | QTimer 50ms 轮询 + `trim_rows(500)` + CRC 默认关闭 |
| 特殊 IP 前缀格式误判 | 低 | 魔数双重校验 |
| ~~dearpygui 与 PySide6 同进程~~ | ~~高~~ | **已切换到纯 PySide6，此风险消除** |
| Npcap 未安装 | 中（网卡模式） | 端口模式不受影响；网卡模式需手动安装 Npcap |
| 管理员权限缺失 | 中（网卡模式） | 端口模式不受影响 |
| 测试路径硬编码 | 高 | 其他开发者路径不同则测试全部失败；应改为相对路径或环境变量 |
| 环形缓冲内存泄漏 | 中 | 当前 deque 无上限；长时间运行可能 OOM；需设置 maxlen |
