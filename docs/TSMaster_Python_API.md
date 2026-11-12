# TSMaster Python API 中文说明

> 适用范围：同星（TOSUN）TSMaster 自带 Python 3.11.8 运行时中的 `TSMaster` 包。
> 本文档基于 `{TSMaster}\Data\Python\3.11.8\x64\Lib\site-packages\TSMaster\__init__.pyi`（类型存根，30628 行）整理，用于在**不打开 TSMaster 上位机界面**的情况下，通过 Python API 控制总线设备。

---

## 1. 概述

`TSMaster` 是 TOSUN（同星）的汽车总线（CAN / CAN FD / LIN / FlexRay / Ethernet）开发测试工具。它内置了一套 Python 运行时，并暴露一个 `TSMaster` Python 包，用于以编程方式控制硬件。

**关键结论：** 这套 API **不是纯独立的设备驱动 SDK**，而是 TSMaster 运行时（`TSMaster.pyd` + `libTSMaster.dll` + 设备驱动）的 Python 绑定。因此可以不开 GUI，但**目标机器上必须装有 TSMaster（或其运行时 + pyd + 驱动）**。

### 1.1 加载机制

`import TSMaster` 时，包内的 `__init__.py` 执行以下步骤：

1. 检查 Python 版本（支持 3.6 ~ 3.12，不支持则抛 `PyVerNotSupported`）；
2. 读取注册表 `HKCU\Software\TOSUN\TSMaster` 的 `bin64` 值，定位 TSMaster 安装目录；
3. 从该目录加载 `bin64/TSMaster.pyd`（真正的二进制扩展，所有 API 实现在这里）；
4. 若注册表读取失败，则回退为按包路径向上推算安装位置。

### 1.2 运行模式

由 `app.is_tsmaster_host()` 区分：

| 模式 | 说明 |
|---|---|
| 宿主模式 | Python 代码作为 TSMaster 的「小程序（Mini Program）」运行在 `TSMaster.exe` 进程内，`is_tsmaster_host()` 返回 `True` |
| 外部 / 无头模式 | 独立 Python 进程，通过 `app.connect()` 启动 / 连接运行时；安装目录中的 `TSMasterServer.exe`、`TSMasterMCPServer.exe`、`TSMasterRPCTool.pyd` 即为无头 / 服务化运行提供支撑 |

### 1.3 返回值约定

- 绝大多数 API 返回值遵循 `Result` 约定：**0 = 成功，非 0 = 错误码**。
- 用 `app.check(errcode)` 判断是否成功，用 `app.get_error_description(code)` 获取错误描述。
- 带 `[Out]` 参数的方法，其返回值是**元组**：第一个元素是 `Result`，后续元素是输出参数（见各方法签名中的注释）。

### 1.4 常用常量

官方示例中出现的 TSMaster 预定义常量：

**日志等级（`TLevel` / `ALevel`）：**

| 常量 | 值 | 含义 |
|---|---|---|
| `lvlError` | 1 | 错误 |
| `lvlWarning` | 2 | 警告 |
| `lvlOK` | 3 | 成功 |
| `lvlHint` | 4 | 提示 |
| `lvlInfo` | 5 | 信息 |
| `lvlVerbose` | 6 | 详细 |

**通道与应用通道类型：**

| 常量 | 说明 |
|---|---|
| `CH1` / `CH2` / … | 通道索引常量，`CH1 = 0`，`CH2 = 1`，从 0 开始 |
| `APP_CAN` / `APP_LIN` | 应用通道类型（CAN / LIN） |

**硬件设备类型（`set_mapping` 的 `AHWType` 参数）：**

| 常量 | 说明 |
|---|---|
| `TS_USB_DEVICE` | TOSUN USB 设备 |
| `XL_USB_DEVICE` | Vector XL USB 设备 |
| `TS_TCP_DEVICE` | TOSUN TCP 设备 |

**错误码：**

| 常量 | 说明 |
|---|---|
| `IDX_ERR_OK` | 无错误 |
| `IDX_ERR_SW_API_WAIT_TIMEOUT` | 等待超时 |
| `IDX_ERR_TEST_CHECK_LOWER` / `IDX_ERR_TEST_CHECK_UPPER` | 判定的值低于 / 高于范围 |

**其他：**

| 常量 | 说明 |
|---|---|
| `CAN_STAT_BUS_LOAD` | 总线统计项：总线负载 |
| `TSystemVarType_svtInt32` 等 | 系统变量类型（见 `TSMaster.h`） |
| `TOnlineReplayTimingMode_ortImmediately(0)` / `ortAsLog(1)` / `ortDelayed(2)` | 在线回放启动定时模式 |
| `STIM_STOPPED` | 刺激信号状态 |

---

## 2. 功能类总览

`__init__.pyi` 前约 29000 行是 Delphi VCL 界面控件绑定（`Button`、`Form`、`Memo`、`Panel` 等），仅用于「在 TSMaster 里画自定义面板」，**控制设备不需要它们**。真正用于设备控制的是以下类：

| 类 | 行号（pyi） | 职责 |
|---|---|---|
| `app` | 29153 | 应用生命周期、硬件 / 通道配置、DBC 加载、系统变量、日志 |
| `com` | 29760 | 总线帧收发、周期发送、信号编解码、RBS、J1939、BLF 日志、TCP/UDP |
| `test` | 30117 | 测试自动化（判定、信号检查引擎、结果记录） |
| `rtl` | 29140 | 运行时工具（少量 UI 相关） |
| 数据结构类 | 30255 起 | `RawCAN`、`RawLIN`、`RawFlexRay`、`GenericFrame`、信号类、DBC 属性类 |
| Mini Program 类 | 30255 起 | `MpInstance`、`MpVar*`、`MpTimer` |

所有功能类的方法均为 `@classmethod`，**无需实例化**，直接 `TSMaster.app.xxx()` / `TSMaster.com.xxx()` 调用。

---

## 3. app 类 —— 应用生命周期与硬件配置

### 3.1 连接管理

| 方法 | 说明 |
|---|---|
| `connect() -> int` | 通过与每个映射通道建立连接来连接到指定应用程序（用已保存的配置连接） |
| `disconnect() -> int` | 关闭每个映射通道的连接，断开指定应用程序 |
| `is_connected() -> bool` | 检查应用是否已连接 |
| `add_application(name) -> int` | 按名称新增应用，可添加或编辑通道映射 |
| `del_application(name) -> int` | 按名称删除应用，删除后该应用的所有映射消失 |
| `get_application_list() -> Strings` | 获取本机现有应用名称列表，以「;」分隔 |
| `get_current_application() -> str` | 获取当前应用名 |
| `set_current_application(name) -> int` | 设置当前应用名（不同应用拥有不同资源映射） |
| `terminate_application(instance) -> int` | 终止当前小程序的执行 |
| `is_tsmaster_host() -> bool` | 是否运行在 TSMaster.exe 宿主内 |

### 3.2 通道数量

| 方法 | 说明 |
|---|---|
| `set_can_channel_count(count)` / `get_can_channel_count() -> int` | 设置 / 获取 CAN 通道数 |
| `set_lin_channel_count(count)` / `get_lin_channel_count() -> int` | 设置 / 获取 LIN 通道数 |
| `set_flexray_channel_count(count)` / `get_flexray_channel_count() -> int` | 设置 / 获取 FlexRay 通道数 |

### 3.3 硬件配置

| 方法 | 说明 |
|---|---|
| `configure_can_baudrate(idx_chn, baudrate_kbps, listen_only, install_term_resistor_120ohm) -> int` | 配置 CAN 波特率、只听模式、是否内置 120Ω 终端电阻 |
| `configure_canfd_baudrate(idx_chn, baud_arb_kbps, baud_data_kbps, controller_type, controller_mode, install_term_resistor_120ohm) -> int` | 配置 CAN FD 仲裁段 / 数据段波特率 |
| `configure_lin_baudrate(idx_chn, baudrate_kbps, protocol) -> int` | 配置 LIN 波特率与协议 |

### 3.4 通道映射

| 方法 | 说明 |
|---|---|
| `set_mapping(app_name, app_chn_type, app_chn_index, hw_name, hw_type, hw_sub_type, hw_index, hw_chn_index, enabled) -> int` | 建立应用通道 → 硬件通道映射 |
| `del_mapping(app_name, app_chn_type, app_chn_index) -> int` | 删除指定应用通道的映射 |
| `get_mapping(app_name, app_chn_type, app_chn_index) -> Tuple[int, str, int, int, int, int, bool]` | 查询映射属性（含硬件名 / 类型 / 通道 / 使能） |

### 3.5 设备枚举

| 方法 | 说明 |
|---|---|
| `enumerate_hw_devices() -> int` | 枚举设备 |
| `get_hw_info_by_index(index) -> List[int, int, str, str, str]` | 返回：kind、厂商名、设备名、序列号 |

### 3.6 DBC / LDF / FlexRay 数据库

三类总线分别提供对称的加载 / 卸载 / 查询接口，此处以 CAN 为例（`tsdb_` 前缀）：

| 方法 | 说明 |
|---|---|
| `tsdb_load_can_db(fr_file, supported_channels) -> Tuple[int, int]` | 加载 CAN 数据库，返回 db id |
| `tsdb_unload_can_db(id)` / `tsdb_unload_can_dbs()` | 卸载单个 / 全部 CAN 数据库 |
| `tsdb_get_can_db_count() -> Tuple[int, int]` | 获取数据库数量 |
| `tsdb_get_can_db_properties_by_address(addr) -> DBProperties` | 按地址（如 `0/Powertrain`）取数据库属性 |
| `tsdb_get_can_db_properties_by_index(db_index) -> DBProperties` | 按下标取数据库属性 |
| `tsdb_get_can_ecu_properties_by_address(addr) -> ECUProperties` | 按地址取 ECU 属性 |
| `tsdb_get_can_ecu_properties_by_index(db_index, ecu_index) -> ECUProperties` | 按下标取 ECU 属性 |
| `tsdb_get_can_frame_properties_by_address(addr) -> CANFrameProperties` | 按地址取报文属性 |
| `tsdb_get_can_frame_properties_by_index(db_index, ecu_index, frame_index, is_tx) -> CANFrameProperties` | 按下标取报文属性 |
| `tsdb_get_can_signal_properties_by_address(addr) -> CANSignalProperties` | 按地址取信号属性 |
| `tsdb_get_can_signal_properties_by_index(db_index, ecu_index, frame_index, signal_index, is_tx) -> CANSignalProperties` | 按下标取信号属性 |

> LIN 使用 `tsdb_load_lin_db` / `tsdb_get_lin_*`；FlexRay 使用 `tsdb_load_flexray_db` / `tsdb_get_flexray_*`，接口形态一致。

### 3.7 系统变量

`app` 类提供了约 40 个系统变量读写接口，分同步 / 异步两种模式，覆盖 double、int32、uint32、int64、uint64、string 及各类数组。

| 方法（节选） | 说明 |
|---|---|
| `create_system_var(complete_name, type, default_value, comment)` / `delete_system_var(name)` | 创建 / 删除系统变量 |
| `get_system_var_value(name) -> Tuple[int, Any]` | 读系统变量值 |
| `get_system_var_generic(name) -> Tuple[int, str]` / `set_system_var_generic(name, value)` | 以字符串形式读写 |
| `set_system_var_double(name, value)` / `set_system_var_int32(name, value)` 等 | 同步写各类型 |
| `set_system_var_double_async(name, value)` / `set_system_var_int32_async(name, value)` 等 | 异步写各类型 |
| `wait_system_var(name, value, timeout_ms)` | 等待变量达到指定值（超时返回） |
| `wait_system_var_existance(name, timeout)` / `wait_system_var_disappear(name, timeout)` | 等待变量创建 / 删除 |

> 异步写（`*_async`）不触发 `OnChange` 事件，适用于对性能要求较高的自动化场景。

### 3.8 日志、文件与其他

| 方法 | 说明 |
|---|---|
| `start_log(instance)` / `end_log(instance)` | 开始 / 结束记录总线事件 |
| `get_timestamp_us() -> int` | 获取当前测量的 PC 时间戳（微秒） |
| `log_text(str, level)` / `log(str, level)`（模块级） | 在系统消息窗口输出日志 |
| `set_turbo_mode(enable)` / `get_turbo_mode() -> bool` | 启用 / 查询 turbo 模式（延迟最小化、功耗增加） |
| `get_tsmaster_version() -> List[int]` | 返回 [年, 月, 日, 构建号] |
| `set_default_output_dir(path)` | 设置默认日志输出目录 |
| `get_configuration_file_name() / get_configuration_file_path()` | 获取配置文件路径 |
| `execute_python_script(file, args, is_sync, is_x64) -> Tuple[int, str]` | 用外部 Python 实例执行脚本 |
| `execute_app(app_path, work_dir, param, wait_ms)` | 执行外部进程并等待 |
| `get_hardware_id_string() / get_hardware_id_array()` | 获取本机硬件 ID |
| `excel_load / excel_get_* / excel_set_* / excel_unload` | Excel 文件读写 |
| `ini_create / ini_write_* / ini_read_* / ini_close` | INI 文件读写 |
| `write_text_file_start / write_text_file_line / write_text_file_end` | 文本 / CSV 写 |
| `read_text_file_start / read_text_file_line / read_text_file_end` | 文本读 |
| `write_mat_file_* / read_mat_file_*` | MATLAB .mat 文件读写 |

### 3.9 小程序（Mini Program）管理

| 方法 | 说明 |
|---|---|
| `tsmp_load(file, import_module, run_after_load)` / `tsmp_unload(file)` / `tsmp_unload_all()` | 加载 / 卸载小程序 |
| `tsmp_run(file)` / `tsmp_stop(file)` / `tsmp_is_running(file) -> bool` | 运行 / 停止 / 查询小程序 |
| `tsmp_run_all()` / `tsmp_stop_all()` | 运行 / 停止全部小程序 |
| `tsmp_reload_settings()` | 重载小程序设置 |

---

## 4. com 类 —— 总线通信

### 4.1 帧收发

| 方法 | 说明 |
|---|---|
| `transmit_can_async(can: RawCAN) -> int` | 异步发送一帧 CAN |
| `transmit_can_sync(can: RawCAN, timeout_ms) -> int` | 同步发送一帧 CAN |
| `transmit_lin_async(lin)` / `transmit_lin_sync(lin, timeout_ms)` | 异步 / 同步发送 LIN 帧 |
| `transmit_flexray_async(flexray)` / `transmit_flexray_sync(flexray, timeout_ms)` | 异步 / 同步发送 FlexRay 帧 |
| `transmit_*_async_wo_pretx(...)` | 上述三个协议的「不触发 preTx 事件」变体 |
| `wait_can_message(instance, tx_can, rx_can, timeout_ms)` | 在总线上等待指定 CAN 帧：先发 `tx_can`（若其 id = -1 则不发送），再等待 `rx_can`（需先配置好 id 与通道属性） |

### 4.2 周期发送

| 方法 | 说明 |
|---|---|
| `add_cyclic_message_can(can, period_ms)` | 将一帧加入周期发送引擎 |
| `del_cyclic_message_can(can)` | 从周期发送引擎删除指定帧 |
| `del_cyclic_messages()` | 清除所有周期帧 |

### 4.3 信号编解码

| 方法 | 说明 |
|---|---|
| `get_can_signal_value(signal: CANSignal, data) -> float` | 从帧数据缓冲取 CAN 信号物理值 |
| `set_can_signal_value(signal: CANSignal, data, value) -> List[int]` | 将 CAN 信号物理值写入帧数据缓冲 |
| `get_lin_signal_value(signal: LINSignal, data)` / `set_lin_signal_value(...)` | LIN 信号读写 |
| `get_flexray_signal_value(signal: FlexRaySignal, data)` / `set_flexray_signal_value(...)` | FlexRay 信号读写 |

### 4.4 RBS（剩余总线仿真）

RBS = Remaining Bus Simulation，用于按数据库仿真总线上其余节点。三类总线（CAN / LIN / FlexRay）均提供对称接口，以 CAN 为例：

| 方法 | 说明 |
|---|---|
| `can_rbs_start()` / `can_rbs_stop()` / `can_rbs_is_running()` | 启动 / 停止 / 查询运行状态 |
| `can_rbs_enable(bool)` | 临时启用 / 禁用 RBS 引擎（用于启动前配置，启动后设置信号再启用即发送） |
| `can_rbs_configure(auto_start, auto_send_on_modification, activate_node_simulation, init_value_options)` | 配置（init_value_options：0=用库，1=用上次，2=复位为 0） |
| `can_rbs_activate_all_networks(enable, include_children)` | 激活全部网络 |
| `can_rbs_activate_network_by_name(chn, enable, network, include_children)` | 按名激活网络 |
| `can_rbs_activate_node_by_name(chn, enable, network, node, include_children)` | 按名激活节点 |
| `can_rbs_activate_message_by_name(chn, enable, network, node, msg)` | 按名激活报文 |
| `can_rbs_set_message_cycle_by_name(chn, interval_ms, network, node, msg)` | 设置报文周期 |
| `can_rbs_get_signal_value_by_address(addr) -> Tuple[int, float]` | 按地址读信号 |
| `can_rbs_set_signal_value_by_address(addr, value)` | 按地址写信号 |
| `can_rbs_get_signal_value_by_element(chn, network, node, msg, signal) -> Tuple[int, float]` | 按元素名读信号 |
| `can_rbs_set_signal_value_by_element(chn, network, node, msg, signal, value)` | 按元素名写信号 |
| `can_rbs_batch_set_start()` / `can_rbs_batch_set_end()` / `can_rbs_batch_set_signal(addr, value)` | 批量写信号 |
| `can_rbs_fault_inject_clear()` | 清除故障注入项 |
| `can_rbs_fault_inject_message_lost(enable, chn, identifier)` | 故障注入：丢帧 |
| `can_rbs_fault_inject_signal_alter(enable, addr, alter_value)` | 故障注入：篡改信号 |
| `can_rbs_set_normal_signal(addr)` / `set_rc_signal(addr)` / `set_rc_signal_with_limit(addr, lo, hi)` / `set_crc_signal(addr, algo, byte_start, byte_count)` | 信号类型设置（普通 / 滚动计数 / 校验） |

### 4.5 J1939

| 方法 | 说明 |
|---|---|
| `j1939_make_id(pgn, source, destination, priority) -> int` | 由协议属性生成 J1939 报文 ID |
| `j1939_extract_id(identifier) -> List[int]` | 从 ID 解析出 [PGN, 源, 目的, 优先级] |
| `j1939_get_pgn(source...)` 等 8 个 `get_*` | 提取 PGN / source / destination / priority / R / DP / EDP |
| `j1939_set_pgn(...)` 等 8 个 `set_*` | 设置上述属性 |
| `j1939_transmit_pdu_async(chn, pgn, priority, source, destination, data)` | 异步发送 J1939 PDU |
| `j1939_transmit_pdu_sync(chn, pgn, priority, source, destination, data, timeout_ms)` | 同步发送 J1939 PDU |
| `j1939_transmit_pdu_as_string_async / sync(...)` | 数据以逗号分隔字符串形式发送 |
| `j1939_get_last_pdu(chn, identifier, is_tx) -> Tuple[int, List[int], int]` | 取最后一帧 PDU 数据及时间 |

### 4.6 日志（BLF）与在线回放

| 方法 | 说明 |
|---|---|
| `tslog_blf_write_start(file) -> List[int]` | 创建 BLF 文件开始写，返回句柄 |
| `tslog_blf_write_can(handle, can)` / `write_lin(...)` / `write_flexray(...)` | 写入帧 |
| `tslog_blf_write_end(handle)` | 停止写 |
| `tslog_blf_read_start(file)` / `tslog_blf_read_object(handle) -> GenericFrame` / `tslog_blf_read_end(handle)` | 读 BLF |
| `tslog_blf_to_asc(blf, asc)` / `tslog_asc_to_blf(asc, blf)` | BLF ↔ ASC 转换 |
| `tslog_add_online_replay_config(file)` / `tslog_set_online_replay_config(...)` | 配置在线回放 |
| `tslog_start_online_replay(index)` / `tslog_stop_online_replay(index)` / `tslog_pause_online_replay(index)` | 控制在线回放 |

### 4.7 网络通信（TCP / UDP）

`ioip_*` 系列提供 TCP / UDP 客户端与服务器能力，常用于网关 / 以太网测试：

| 方法 | 说明 |
|---|---|
| `ioip_create(instance, port_tcp, port_udp) -> List[int]` | 创建 IP 对象（含 TCP 客户端 / 服务器、UDP 客户端 / 服务器） |
| `ioip_delete(instance, handle)` | 删除 IP 对象 |
| `ioip_enable_tcp_server(instance, handle, enable)` / `ioip_enable_udp_server(...)` | 启用服务器 |
| `ioip_connect_tcp_server(instance, handle, ip, port)` / `ioip_connect_udp_server(...)` | 连接外部服务器 |
| `ioip_send_buffer_tcp(instance, handle, buffer)` / `ioip_send_buffer_udp(...)` | 发送数据 |
| `ioip_receive_tcp_client_response(instance, handle, timeout_ms) -> Tuple[int, List[int]]` | 接收 TCP 响应 |
| `ioip_receive_udp_client_response(instance, handle, timeout_ms) -> Tuple[int, List[int]]` | 接收 UDP 响应 |
| `ioip_send_udp_broadcast(instance, handle, port, buffer)` | UDP 广播 |

### 4.8 统计与其他

| 方法 | 说明 |
|---|---|
| `enable_bus_statistics(enable)` / `clear_bus_statistics()` | 启停 / 清除总线统计 |
| `get_bus_statistics(bus_type, idx_chn, idx_stat) -> Tuple[int, float]` | 取统计结果值 |
| `get_fps_can(chn, identifier) -> List[int]` / `get_fps_canfd(...)` / `get_fps_lin(...)` | 取指定 ID 的每秒帧数（FPS，需先启用总线统计） |
| `inject_can_message(can)` / `inject_lin_message(lin)` / `inject_flexray_frame(fr)` | 注入虚拟帧到测量窗口，以 trace / 图形 / 面板形式显示 |

### 4.9 信号服务器（sgnsrv）

按报文 ID 或报文名注册信号，之后即可用返回的 client id 反复获取该信号的物理值（用于接收 / 采集信号）。

| 方法 | 说明 |
|---|---|
| `sgnsrv_register_can_signal_by_msg_identifier(chn, msg_id, sgn_name) -> List[int]` | 按报文 ID 注册 CAN 信号，返回 [Result, ClientId] |
| `sgnsrv_register_lin_signal_by_msg_identifier(chn, msg_id, sgn_name) -> List[int]` | 按报文 ID 注册 LIN 信号 |
| `sgnsrv_register_can_signal_by_msg_name(chn, network_name, msg_name, sgn_name) -> List[int]` | 按报文名注册 CAN 信号 |
| `sgnsrv_register_lin_signal_by_msg_name(chn, network_name, msg_name, sgn_name) -> List[int]` | 按报文名注册 LIN 信号 |
| `sgnsrv_register_flexray_signal_by_frame(chn, chn_mask, cycle_number, slot_id, sgn_name) -> List[int]` | 按帧头信息注册 FlexRay 信号 |
| `sgnsrv_register_flexray_signal_by_frame_name(chn, network_name, frame_name, sgn_name) -> List[int]` | 按帧名注册 FlexRay 信号 |
| `sgnsrv_get_can_signal_phy_value_latest(chn, client_id) -> Tuple[int, float, int]` | 取 CAN 信号最新物理值，返回 [Result, Value, TimestampUs] |
| `sgnsrv_get_lin_signal_phy_value_latest(chn, client_id) -> Tuple[int, float, int]` | 取 LIN 信号最新物理值 |
| `sgnsrv_get_flexray_signal_phy_value_latest(chn, client_id) -> Tuple[int, float, int]` | 取 FlexRay 信号最新物理值 |
| `sgnsrv_get_can_signal_phy_value_in_msg(chn, client_id, can) -> Tuple[int, float, int]` | 从指定帧中取 CAN 信号物理值 |
| `sgnsrv_get_lin_signal_phy_value_in_msg(chn, client_id, lin) -> Tuple[int, float, int]` | 从指定帧中取 LIN 信号物理值 |
| `sgnsrv_get_flexray_signal_phy_value_in_frame(chn, client_id, flexray) -> Tuple[int, float, int]` | 从指定帧中取 FlexRay 信号物理值 |

> 注：官方示例中 `id = com.sgnsrv_register_can_signal_by_msg_identifier(CH1, 0x64, 'EngSpeed')` 直接把返回值当作 client id 使用，而 pyi 声明返回 `List[int]`（Result + ClientId），实际以运行时返回为准。

### 4.10 CAN FD PDU 容器（can_pdu_container）

| 方法 | 说明 |
|---|---|
| `can_pdu_container_set_cycle_count(chn, msg_id, count)` | 设置 CAN FD 报文中 PDU 容器的周期数 |
| `can_pdu_container_set_cycle_by_index(chn, msg_id, idx_cycle, signal_group_id_list)` | 设置某周期打包哪些 PDU |
| `can_pdu_container_get_cycle_count(chn, msg_id) -> List[int]` | 获取 PDU 容器周期总数 |
| `can_pdu_container_get_cycle_by_index(chn, msg_id, idx_cycle) -> Tuple[int, str]` | 获取某周期打包的 PDU |
| `can_pdu_container_refresh(chn, msg_id)` | 刷新所有周期使设置生效 |

---

## 5. test 类 —— 测试自动化

| 方法 | 说明 |
|---|---|
| `set_verdict_ok(verdict)` / `set_verdict_nok(verdict)` / `set_verdict_cok(verdict)` | 设置判定（OK / NOK / COK） |
| `check_verdict(instance, name, value, min, max)` | 值在范围内判 OK，否则 NOK |
| `log_info(instance, info, level)` | 记录信息 |
| `log_value(instance, msg, value, level)` / `log_string(instance, msg, value, level)` | 记录「名=值」对 |
| `write_result_string(instance, name, value, level)` / `write_result_value(instance, name, value, level)` | 写结果 |
| `write_result_image(instance, name, image_path)` | 写图片路径到结果 |
| `retrieve_current_result_folder(instance) -> Tuple[int, str]` | 获取当前用例日志目录 |
| `check_error_begin()` / `check_error_end() -> List[int]` | 区间内错误检查 |
| `check_test_terminate()` | 检查用户是否请求终止 |
| `classic_test_system_login(user, pwd)` / `classic_test_system_import(conf)` | 经典测试系统登录 / 导入 |
| `signal_checker_clear()` | 清除信号检查引擎全部检查项 |
| `signal_checker_add_check_with_time(...)` / `..._with_trigger(...)` | 增加范围 / 触发检查 |
| `signal_checker_add_rising_edge_with_time(...)` / `..._falling_edge...` | 上升沿 / 下降沿检查 |
| `signal_checker_add_monotony_rising_with_time(...)` / `..._falling...` | 单调性检查 |
| `signal_checker_add_follow_with_time(...)` / `..._with_trigger(...)` | 信号跟随检查 |
| `signal_checker_add_jump_with_time(...)` / `..._unchange...` | 跳变 / 不变检查 |
| `signal_checker_add_statistics_with_time(...)` / `..._with_trigger(...)` | 统计检查 |
| `signal_checker_get_result(instance, check_id) -> Tuple[int, bool, float, str]` | 取检查结果（含是否通过 / 值 / 描述） |
| `signal_checker_check_statistics(instance, check_id, min, max) -> Tuple[int, bool, float, str]` | 统计检查结果 |
| `signal_checker_enable(check_id, enable)` | 启用 / 禁用指定检查 |

---

## 6. rtl 类 —— 运行时工具

| 方法 | 说明 |
|---|---|
| `draw_frame_control(dc, left, top, width, height, type, state) -> bool` | 绘制指定类型 / 样式的框架控件 |
| `draw_text(dc, text, left, top, width, height, formats) -> bool` | 按格式绘制文本 |
| `get_component_by_index(parent, idx) -> Component` | 按下标取子组件 |
| `get_control_by_index(parent, idx) -> Control` | 按下标取子控件 |

---

## 7. 数据结构类

### 7.1 RawCAN —— CAN / CAN FD 帧

构造：`RawCAN(id=0, dlc=8, idx_chn=0, time_us=0, datas=[], flags=6)`

| 方法 / 属性 | 说明 |
|---|---|
| `init_w_std_id(id, dlc)` | 用标准帧 ID 初始化 |
| `init_w_ext_id(id, dlc)` | 用扩展帧 ID 初始化 |
| `set_data(idx_byte, data)` | 按字节索引写数据 |
| `id` | 报文标识符 |
| `dlc` | 数据长度 |
| `idx_chn` | 通道索引 |
| `time_us` | 时间戳（微秒） |
| `data` | 数据字节列表（**只能整体赋值**，单字节用 `set_data`） |
| `is_tx` | 是否发送帧 |
| `is_data` / `is_std` / `is_err` | 是否数据帧 / 标准帧 / 错误帧 |
| `is_edl` / `is_brs` / `is_esi` | CAN FD 标志（EDL / BRS / ESI） |

### 7.2 RawLIN —— LIN 帧

构造：`RawLIN(id=0, dlc=8, idx_chn=0, time_us=0, datas=[], flags=0)`

| 方法 / 属性 | 说明 |
|---|---|
| `init_w_id(id, dlc)` | 初始化 |
| `set_data(idx_byte, data)` | 按字节写 |
| `id` / `dlc` / `idx_chn` / `time_us` / `data` | 同 CAN 语义 |
| `checksum` | 校验和 |
| `err_status` / `status` | 错误状态 / 状态 |
| `is_tx` | 是否发送帧 |

### 7.3 RawFlexRay —— FlexRay 帧

构造：`RawFlexRay(slot_id=0, payload_length=8, idx_chn=0, channel_mask=1, dir=1, cycle_number=0, time_us=0, datas=[], frame_type=0, flags=2)`

| 方法 / 属性 | 说明 |
|---|---|
| `init_w_slot_id(slot_id, dlc)` | 初始化 |
| `frame_hash()` | 按头信息计算帧哈希 |
| `slot_id` / `cycle_number` / `channel_mask` / `dir` / `frame_type` | 槽 ID / 周期号 / 通道掩码 / 方向 / 帧类型 |
| `payload_length` / `actual_payload_length` | 载荷长度 / 实际载荷长度 |
| `header_crc_a` / `header_crc_b` / `frame_crc` / `frame_flags` / `frame_state_info` | CRC 与状态 |
| `time_us` / `data` | 时间戳 / 数据 |

### 7.4 GenericFrame —— 统一帧容器

| 属性 | 说明 |
|---|---|
| `FrameType` | 帧类型：0=CAN，1=LIN，2=CAN FD，3=实时注释，4=系统变量，5=FlexRay，6=Ethernet |
| `CAN` | `FrameType` 为 0 或 2 时有效 |
| `LIN` | `FrameType` 为 1 时有效 |
| `FlexRay` | `FrameType` 为 5 时有效 |
| `Comment` | `FrameType` 为 3 时有效 |
| `ToDisplayString()` | 转为显示字符串 |

### 7.5 信号定义类

**CANSignal** 构造：`CANSignal(can_sgn_type=0, is_intel=1, start_bit=0, length=1, factor=1.0, offset=0)`

| 属性 | 说明 |
|---|---|
| `CANSgnType` | 信号类型：0=无符号，1=有符号，2=float，3=double |
| `IsIntel` | **0=Motorola，1=Intel** |
| `StartBit` / `Length` | 起始位 / 位长 |
| `Factor` / `Offset` | 物理值换算因子 / 偏移 |

**LINSignal**：字段同 CANSignal，但 `IsIntel` 语义**相反**（0=Intel，1=Motorola）。

**FlexRaySignal**：额外包含 `CompuMethod`、`UpdateBit`、`ActualStartBit`、`ActualUpdateBit` 等字段。

### 7.6 数据库属性类

`DBProperties`、`ECUProperties`、`CANFrameProperties`、`LINFrameProperties`、`FlexRayFrameProperties`、`CANSignalProperties`、`LINSignalProperties`、`FlexRaySignalProperties` —— 均由 `tsdb_get_*` 系列返回，字段含 `IsValid`（是否有效）、`Name`、`Comment`、各索引与数量等，用于遍历 DBC / LDF 中的库、ECU、报文、信号元信息。

---

## 8. Mini Program 支持类

| 类 | 构造 | 说明 |
|---|---|---|
| `MpInstance(name)` | 按名创建小程序实例引用 | 方法：`MpBaseName()`、`MpFileName()` |
| `MpVarInteger(name, init, unit)` | 整数变量 | 属性 `Value` |
| `MpVarDouble(name, init, unit)` | 浮点变量 | 属性 `Value` |
| `MpVarString(name, init, unit)` | 字符串变量 | 属性 `Value` |
| `MpTimer(mp_name, timer_name, interval_ms)` | 定时器 | 属性 `IntervalMs`；方法 `Start()` / `Stop()` |

---

## 9. 模块级函数与 crc 模块

### 9.1 模块级常用函数

| 函数 | 说明 |
|---|---|
| `log(str, level)` | 在系统消息窗口输出带颜色日志（level 可省略） |
| `Abort()` | 中止 |
| `ShowMessage(...)` | 弹消息框 |

> 其余模块级函数（`CreateComponent`、`FreeConsole`、DPI 相关等）多为 Delphi 环境封装，设备控制一般不使用。

### 9.2 crc 模块（21 个 CRC 函数）

`TSMaster.crc.crc16_ccitt(data, datalen)`、`crc16_ccitt_false`、`crc16_dnp`、`crc16_ibm`、`crc16_maxim`、`crc16_modbus`、`crc16_usb`、`crc16_x25`、`crc16_xmodem`、`crc32`、`crc32_mpeg`、`crc4_itu`、`crc5_epc`、`crc5_itu`、`crc5_usb`、`crc6_itu`、`crc7_mmc`、`crc8`、`crc8_itu`、`crc8_maxim`、`crc8_rohc` —— 均返回 `int`。

### 9.3 controller 模块

`TSMaster.controller.control_rbs(enable: bool, info) -> int` —— 控制 RBS 引擎。

---

## 10. 设备控制典型流程

以「外部脚本控制 CAN 设备」为例：

```
1. app.connect()                          # 连接 / 启动运行时
2. app.set_can_channel_count(1)           # 设置 CAN 通道数
3. app.configure_can_baudrate(0, 500, False, False)   # CH0 配置 500kbps
4. app.set_mapping(...)                   # 应用通道 → 物理硬件通道映射
5. com.transmit_can_async(RawCAN(...))    # 发送单帧
6. com.add_cyclic_message_can(...)        # 或周期发送
7. （接收走回调 / 事件；记录走 app.start_log）
8. app.disconnect()                       # 收尾断开
```

---

## 11. 示例代码

### 11.1 最小发帧示例

```python
import TSMaster as ts

ts.app.connect()
ts.app.set_can_channel_count(1)
ts.app.configure_can_baudrate(0, 500.0, False, False)  # CH0, 500kbps

can = ts.RawCAN()
can.init_w_std_id(0x123, 8)              # 标准帧 ID=0x123, DLC=8
can.data = [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08]
ts.com.transmit_can_async(can)           # 异步发送

ts.app.disconnect()
```

### 11.2 周期发送

```python
import TSMaster as ts

ts.app.connect()
ts.app.set_can_channel_count(1)
ts.app.configure_can_baudrate(0, 500.0, False, False)

can = ts.RawCAN()
can.init_w_std_id(0x100, 8)
can.data = [0, 1, 2, 3, 4, 5, 6, 7]
ts.com.add_cyclic_message_can(can, 100.0)   # 每 100ms 发送一次
```

### 11.3 信号读写

```python
import TSMaster as ts

# 定义一个信号：起始位 8，16 位长，Intel 字节序，因子 0.1，偏移 0
sgn = ts.CANSignal(0, 1, 8, 16, 0.1, 0.0)

data = [0] * 8
data = ts.com.set_can_signal_value(sgn, data, 12.5)   # 写入物理值 12.5
value = ts.com.get_can_signal_value(sgn, data)        # 读回物理值
```

### 11.4 信号服务器接收（轮询最新值）

```python
import TSMaster as ts

# 按报文 ID 注册 CAN 信号，返回 client id
r, client_id = ts.com.sgnsrv_register_can_signal_by_msg_identifier(0, 0x64, 'EngSpeed')

# 轮询获取该信号最新物理值
r, value, timestamp_us = ts.com.sgnsrv_get_can_signal_phy_value_latest(0, client_id)
```

---

## 12. 注意事项

1. **接收方式**：实时接收有三种途径 —— ① `sgnsrv_*` 信号服务器（注册后轮询 `get_*_latest` 取最新物理值，见 §4.9）；② `wait_can_message`（发帧并等待指定回应帧）；③ `on_can_rx` 事件 / 回调（小程序宿主模式）。纯外部脚本做实时接收优先用信号服务器。

2. **字节序字段有坑**：`CANSignal.IsIntel` 为「0=Motorola，1=Intel」，而 `LINSignal.IsIntel` 相反（「0=Intel，1=Motorola」），使用时务必对照各自注释。

3. **`data` 字段整体赋值**：注释明确 `data` 不能按单值写，须整体赋值（`can.data = your_array`），单字节用 `set_data(idx, val)`。

4. **返回码约定**：所有 API 返回的 `Result`（及带 `Result` 元组的首元素）中 `0 = 成功`，非 0 = 错误码；用 `app.check(errcode)` 判断是否无错误，用 `app.get_error_description(code)` 取错误描述。

5. **中文 API 原型表**：完整函数原型（含中文说明）位于 `{TSMaster}\Configuration\TOSUN\TSMaster\MiniProgram\Conf\TSMasterMPAPIsPython_2052.ini`（2052 = 中文）与 `TSMasterFunctionPrototypesPython.ini`。

6. **版本对应**：本文档对应 `TSMaster/__version__.py` 声明的包版本 `1.0.0`；API 以安装目录内实际 `__init__.pyi` 为准。
