# MAVLink UDP Monitor

实时 MAVLink UDP 消息监控与诊断工具，参考 Vector CANoe Trace Window 交互范式。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 GUI（向后兼容，UDP 监控始终可用，假设备 Tab 条件启用）
python integrated_gui.py

# 新方式（v2.0 包拆分后推荐）
python -m mavlink_monitor.integrated_gui
python -m mavlink_monitor.integrated_gui --list-screens
python -m mavlink_monitor.integrated_gui --screen 1
```

## 功能

- **多节点监听** — 同时绑定多个 UDP 端口，被动接收 MAVLink 流量
- **实时解析** — 自动识别 MAVLink 版本（v1）、CRC 校验、Payload 字段展开
- **双格式支持** — 标准 MAVLink 格式 + 4字节 IP 前缀特殊格式
- **枚举映射** — 字段值自动映射为可读枚举名称
- **灵活过滤** — 按 MsgID/IP/Port/SysID/CompID/关键字/正则 过滤或高亮
- **双时间戳** — 相对时间 + 绝对时间可切换
- **双视图** — 时间序平铺表格 + CANoe 风格分组消息树
- **假设备集成** — 假飞机/假机巢/假电台控制面板 + 消息注入监控
- **剧本处理** — 航点解析对比（3D 可视化）+ 航点篡改
- **日志记录** — 可选持久化，格式与现有项目 log 一致

## 两种使用方式

| 方式 | 启动命令 | GUI |
|------|----------|-----|
| 独立工具 | `python integrated_gui.py` | PySide6 窗口（仅 UDP 监控 Tab） |
| 集成模式 | `python integrated_gui.py` | PySide6 窗口（UDP + 假设备 + 剧本 Tab，需假设备项目） |

## 项目结构

```
mavlink_monitor/
├── integrated_gui.py              ← 兼容入口（重定向到 v2.0 包）
├── mavlink_monitor/
│   ├── core/                      # 核心引擎（框架无关）
│   │   ├── model.py               # MonitorModel — 环形缓冲 + MessageRecord
│   │   ├── parser.py              # MavlinkParser — v1 帧解析 + CRC
│   │   ├── engine.py              # MonitorEngine — 端口监听 + 嗅探
│   │   ├── controller.py          # MonitorController — 桥接层
│   │   ├── filter.py              # MessageFilter — 规则链
│   │   ├── exporter.py            # CSV/JSON 导出
│   │   ├── radio_parser.py        # RadioDavParser — DAV 协议
│   │   └── paths.py               # 统一路径解析（环境变量优先）
│   ├── gui/                       # PySide6 GUI 组件
│   │   ├── main_window.py         # 独立监控窗口
│   │   ├── left_panel.py          # 配置 + 网卡 + 统计
│   │   ├── trace_table.py         # 时间序 Trace 表格（14列）
│   │   ├── grouped_trace_view.py  # CANoe 风格分组消息树（12列）
│   │   ├── detail_tree.py         # 字段详情树
│   │   ├── filter_bar.py          # 过滤栏
│   │   ├── drama_processing.py    # 剧本处理（航点解析对比 + 篡改）
│   │   ├── widgets.py             # 共享控件（_LimitedCombo, _MultiSelectButton, ...）
│   │   └── utils.py               # 共享工具（fmt_rel, fmt_abs）
│   ├── integration/               # PySide6 Tab 集成
│   ├── integrated_gui/            # v2.0 集成面板包（8 模块，从单体文件拆分）
│   │   ├── __init__.py            # 重新导出 + main() 入口
│   │   ├── _env.py                # 共享环境（路径 + 假模块导入）
│   │   ├── _reflection.py         # AST 动态反射
│   │   ├── _types.py              # 类型检测 + 值转换 + 控件工厂
│   │   ├── _config.py             # SimConfig + _build_sim_configs + _SocketInterceptor
│   │   ├── _panels.py             # SimulationPanel
│   │   ├── _nested.py             # NestedDevicePanel
│   │   ├── _monitor.py            # FullUdpMonitorPanel
│   │   └── _window.py             # 多屏辅助 + IntegratedMainWindow
│   └── resources/                 # JSON 配置文件
├── tests/                         # 156 个测试用例
├── docs/                          # 方案文档（7 份 CODE_PLAN + 审查报告 + 优化计划）
└── output/                        # 输出目录（drama, drama_modified）
```

## 优化状态

| 类别 | 进度 |
|------|------|
| HIGH 严重问题（原 15 项） | **14/15** 完成 |
| 新增项目（H16-H20） | **5/5** 完成 |
| 架构重构（H10 包拆分） | ✅ v2.0 |
| 仅剩 | H2（controller.py 硬编码容量需业务决策） |
