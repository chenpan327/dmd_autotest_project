# fake_nest.py — 代码方案

> **文件**: `D:\Work\dmd_autotest_project_ycl\src\Protocol\mavlink\fake_nest.py`
> **版本**: v1.8
> **行数**: 5783
> **最后同步**: 2026-09-10
> **用途**: 假机巢模拟器，模拟一台或多台机巢按 Nest 协议（v45）响应地面站，包含内部轻型假飞机、PPS、PPSCharger、LPPC 子设备模拟，以及摄像头 MJPEG 视频流
>
> **关联子方案**:
> - [CODE_PLAN.md](./CODE_PLAN.md) — integrated_gui.py 面板方案（SimulationPanel + NestedDevicePanel）
> - [PROJECT_PLAN.md](./PROJECT_PLAN.md) — mavlink_monitor 核心引擎方案
> - [CODE_PLAN_FAKE_AIRPLANE.md](./CODE_PLAN_FAKE_AIRPLANE.md) — 假飞机模块方案
> - [CODE_PLAN_FAKE_RADIO.md](./CODE_PLAN_FAKE_RADIO.md) — 假电台模块方案

---

## 目录

1. [文件速览](#1-文件速览)
2. [代码分段索引](#2-代码分段索引)
3. [类层次结构](#3-类层次结构)
4. [核心类详解](#4-核心类详解)
5. [_NestedDeviceBase 子类详解](#5-_nesteddevicebase-子类详解)
6. [线程模型](#6-线程模型)
7. [update_xxx 方法清单](#7-update_xxx-方法清单)
8. [消息路由](#8-消息路由)
9. [与 integrated_gui.py 的交互](#9-与-integrated_guipy-的交互)
10. [修改指南](#10-修改指南)

---

## 1. 文件速览

```
fake_nest.py  (4929 行) — 最大的假设备模块

├── L1-47     文档字符串（模块总说明 + 飞机消息路由策略 + 握手协议）
├── L49-70    导入（ctypes, socket, struct, subprocess, threading, dataclass;
│             parse_mavlink, param_dict, logger, LogManager）
├── L71-91    模块级常量（MAVLINK_VERSION='45', NETCARD_INTERFACE, SYS_ID_*, COMP_ID_*）
├── L97-110   **`_parse_mavlink_message(data)`** — fake_nest 专用解析函数（按 MAVLINK_VERSION=45 解析）
│
├── L111-153  嵌套设备自适应注册表（NestedDeviceMeta dataclass + NESTED_DEVICE_REGISTRY + _NestedDeviceBase.__init_subclass__）
│
├── L155-452  Class 1: FakeNest — 传输层（UDP 套接字 + Windows NIC IP 管理）
│   ├── L156-190  __init__（IP 地址、端口、网卡绑定参数）
│   ├── L192-213  _setup_network()（netsh 添加/检查辅助 IP）
│   ├── L215-267  _udp_setup()（创建 UDP socket 绑定）
│   ├── L269-314  close() / is_alive（资源释放）
│   ├── L319-371  send(message, addr, prepend_ip, prepend_ip_addr, raw_prefix)
│   └── L383-451  receive(bufsize) → (msg, addr, source_ip) — 自适应 IP 前缀检测（v45 解析）
│
├── L460-2368  Class 2: _NestAirplane — 轻型假飞机（~1908 行）
│   ├── L442-447  类文档（自包含、无网卡/线程、消息由机巢转发）
│   ├── L449-529  _UPDATABLE_FIELDS（67 个可更新字段，含电池/电压字段）
│   ├── L514-626  时序/协议/状态机常量（心跳间隔、握手状态、RESPONSE_RULES、STATE_RULES 等）
│   ├── L627-674  STATE_RULES / RESPONSE_RULES 规则表 + 处理函数名映射
│   ├── L677-872  __init__（~190 行属性初始化 + 参数 CSV 加载 + 电池电压字段，socket 延迟到外部模式创建）
│   ├── L852-1050 消息处理（process_message → _dispatch_request / _dispatch_airplane_response）
│   ├── L1052-1270 规则调度 + 各 msg_id 处理方法（_handle_heartbeat_dmd / _handle_calib_time / _handle_set_mode 等）
│   ├── L1272-1500 COMMAND_LONG 处理（挂载点灯控制、飞行命令等）
│   ├── L1502-1700 消息构建（build_heartbeat / build_packed_state / build_remaining_capacity 等）
│   ├── L1702-1880 握手状态机（IDLE→WAIT_ID_3→WAIT_ID_1→COMPLETED/FAILED）
│   ├── L1882-2000 飞行状态机（DISARM→LANDED→GUIDE_IDLE→GUIDE_TAKEOFF→GUIDE_PLAY→LAND/RETURN）
│   ├── L2002-2180 update_state / update_version / update_position / update_ack 等
│   ├── L2182-2240 参数访问（get_param / set_param / param_request_list 等）
│   ├── L2215-2230 external mode（set_external_mode / set_internal_mode（非 COMPLETED 握手重置）/ send_external）
│   ├── L2282-2335 resource cleanup（release / 关闭自有 socket）
│   ├── L2346-2395 **_external_receive_loop()** — 外模式接收线程（v1.2 新增。v1.3: + `_msg_injector`；v1.4: 使用 `MAVLink_message.parse(data)` 解析）
│
├── L2537-2638  Class 3: _NestedPPS — 储能电池 PPS（~102 行）
│   ├── L2542-2568  _UPDATABLE_FIELDS（15 个字段）+ _REPORT_INTERVAL
│   ├── L2572-2591  __init__（15 个状态字段 + _last_report_time）
│   ├── L2593-2614  build_state_message() → msg_id=83
│   ├── L2616-2620  needs_report / mark_report_sent
│   ├── L2625-2629  process_message（无响应规则，预留扩展）
│   └── L2631-2637  update_state（字段批量更新）
│
├── L2639-2727  Class 4: _NestedPPSCharger — PPS 充电器（~88 行）
│   ├── L2644-2664  _UPDATABLE_FIELDS（10 个字段）
│   ├── L2666-2683  __init__（10 个状态字段）
│   ├── L2685-2704  build_state_message() → msg_id=84
│   ├── L2706-2710  needs_report / mark_report_sent
│   ├── L2715-2719  process_message
│   └── L2721-2726  update_state
│
├── L2728-2833  Class 5: _NestedLPPC — LPPC 低功耗处理器（~106 行）
│   ├── L2733-2757  _UPDATABLE_FIELDS（16 个字段）
│   ├── L2763-2784  __init__（16 个状态字段）
│   ├── L2786-2811  build_state_message() → msg_id=100（lppc_heartbeat，v45）
│   ├── L2813-2817  needs_report / mark_report_sent
│   ├── L2822-2826  process_message
│   └── L2828-2833  update_state
│
├── L2835-4684  Class 6: _FakeNestSender — 单机巢响应器（~1850 行）
│   ├── L2640-2669  类文档（2 线程模型 + 飞机管理 + 协议响应规则结构）
│   ├── L2671-2748  类级注册表 + 默认值 + 时序常量 + MAV_CMD 枚举
│   ├── L2752-2784  _RESPONSE_RULES（id=1→id=87, id=3→id=2）+ _STATE_RULES（76→_handle_command_long, 74→_handle_get_lowfreq_info, 28→_handle_set_code_number）
│   ├── L2789-2829  握手方法（_do_handshake / _wait_for_msg_id）
│   ├── L2831-2933  __init__（~100 行属性 + 嵌套设备字典 + TCP/ACK 配置 + 线程启动。v1.3: + `_msg_injector`）
│   ├── L2935-3014  start / stop / _cleanup 生命周期管理
│   ├── L3056-3068  **`set_msg_injector(callback)`** — 消息注入回调（v1.3 新增）
│   ├── L3216-3225  update_nest_ip(nestIp)
│   ├── L3241-3289  update_nest_state(**fields) — 20 字段（含 viCount/viState/viJudge）+ uavIp 变更同步飞机 + pps_online/ppsCharger_online 同步子设备
│   ├── L3291-3306  **`update_vision_state(viCount, viState, viJudge)`** — 视觉检测信号（v1.6 新增，uint8 钳制 0-255）
│   ├── L3307-3342  update_nest_plane_layout(layout) — 飞机排布同步
│   ├── L3116-3358  _normalize_uav_ip / _make_airplane_serial_code / _sync_airplanes_locked / _register_external_airplane
│   ├── L3361-3377  update_nest_extend(**fields) → msg_id=87 字段
│   ├── L3379-3389  update_identify(serial, code) → msg_id=2 字段
│   ├── L3391-3408  update_ack(fail_count, silence_count) — 机巢自身 ACK 配置
│   ├── L3410-3430  update_airplane_ack(ip_str, fail_count, silence_count) — 飞机 ACK 配置
│   ├── L3432-3450  update_airplane_offline(ip_str, offline) — 飞机消息外发开关
│   ├── L3452-3482  update_airplane_state(ip_str, **fields) — 飞机状态字段
│   ├── L3484-3547  update_airplane_mode(ip_str, mode, target_nest_index, target_slot) — 内外模式 + 跨巢入巢
│   ├── L3549-3574  update_airplane_version(**kwargs) — 飞机版本信息
│   ├── L3576-3591  update_pps_state(**fields)
│   ├── L3593-3607  update_pps_charger_state(**fields)
│   ├── L3609-3626  update_lppc_state(ip_str, **fields)
│   ├── L3628-3663  self.success 衰减状态机（_reset_success_locked / _mark_success_locked / 0.5s Timer）
│   ├── L3668-3769  _run() — 接收线程（50ms 轮询 + 双路由策略）
│   ├── L4004-4127  _periodic_send_loop() — 周期线程（1s 发送 id=86 + 飞机心跳/状态 + PPS/PPSCharger + LPPC(100) 及新消息 80/81/82/101/102）
│   ├── L3899-3962  _dispatch_request(received, remote_addr) — 机巢消息规则调度
│   ├── L3964-4003  _wrap_and_send(msg, label, ...) — 统一外发入口（IP 前缀 + 日志 + success 标记）
│   ├── L4005-4049  _dispatch_airplane_response / _dispatch_pps_response / _dispatch_pps_charger_response / _dispatch_lppc_response
│   ├── L4295-4403  消息构建器（id=0/2/86/87/88）— **id=86 含 viCount/viState/viJudge**（v45）
│   ├── L4407-4436  _build_id_088 — NEST_UAV_HEARTBEAT（仅定义，暂不外发；v45 结构补齐 ip/mac/ssid/nestLayer）
│   ├── L4441-4496  _handle_get_lowfreq_info → 返回 id=75（MAC/IP/SSID）
│   ├── L4501-4620  _handle_command_long — 13 种命令支持（LED/PPS/UAV/Charger/LPPC/固件更新）
│   ├── L4823-4858  **`_handle_set_code_number`** — SET_CODE_NUMBER(0x1C,28) 处理：回 COMMAND_ACK(77) 并更新机巢 nestId + code（v1.8 新增，ACK 逻辑对齐 _handle_command_long，受 update_ack 控制）
│   └── L4622-4684  _build_id_077 — COMMAND_ACK 构建（含 ACK 静默/失败配置）
│
├── L4686-4876  Class 7: _FakeNestSenders — 批量机巢管理器（~190 行）
│   ├── L4689-4720  类文档（批量创建 + IP/code/nestId 自动递增规则）
│   ├── L4722-4729  类级全局计数 + 定位常量（_POS_BASE_LAT/LON/STEP）
│   ├── L4731-4823  __init__（count 循环创建 FakeNest → _FakeNestSender + 自动定位）
│   ├── L4825-4830  stop() — 停止所有线程 + 关闭所有 FakeNest
│   └── L4835-4875  _build_serial / _build_code / _build_id_bytes / _build_nest_sn 辅助方法
│
└── L4878-4929  __main__ 测试入口（创建 1 台机巢 + 长时间运行）
```

---

## 2. 代码分段索引

> 使用方法：在 IDE 中 `Ctrl+G` 跳转到对应行号即可定位功能区域。

### 2.1 模块常量与注册表 (L1-153)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L1-47 | 文件文档字符串（模块总说明 + 路由策略 + 握手协议） | — |
| L49-70 | 导入（ctypes, socket, struct, subprocess, threading, dataclass, parse_mavlink, param_dict, logger, LogManager） | — |
| L71-72 | MAVLINK 版本 + 网卡接口名 | `MAVLINK_VERSION = '45'`, `NETCARD_INTERFACE = "WLAN 6"` |
| L77-91 | System ID / Component ID 常量 | `SYS_ID_GCS=39`, `SYS_ID_UAV=1`, `SYS_ID_NEST=40`, `COMP_ID_NEST_PPS=36`, `COMP_ID_LPPC=37`, `COMP_ID_NEST_PPSCHARGER=38`, `COMP_ID_GCS=39`, `COMP_ID_NEST=40`, `COMP_ID_NEST_CHARGER=41` |
| L97-106 | `NestedDeviceMeta` dataclass | `cls`, `label`, `sender_update_method`, `sender_instances_attr`, `instance_mode`, `fields` |
| L108 | `NESTED_DEVICE_REGISTRY: dict[str, NestedDeviceMeta]` | 全局注册表 |
| L111-134 | `_NestedDeviceBase` 基类 + `__init_subclass__` 自动注册 | — |

### 2.2 Class 1: FakeNest 传输层 (L155-452)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L138-172 | `__init__`（IP 地址、GCS 地址/端口、网卡、超时） | `ip_addr`, `ground_station_ip`, `ground_station_port`, `local_port`, `interface`, `mask`, `recv_timeout` |
| L174-195 | `_setup_network()` — netsh 添加/检测辅助 IP | `subprocess.run("netsh ...")` |
| L197-249 | `_udp_setup()` — socket 创建 + SO_REUSEADDR + bind | `self.sock` |
| L251-296 | `close()` / `is_alive` — 资源释放（socket 关闭 + IP 移除） | — |
| L301-353 | `send(message, addr, prepend_ip, prepend_ip_addr, raw_prefix)` — 发送（可选 IP 前缀） | — |
| L355-434 | `receive(bufsize)` → `(msg, addr, source_ip)` — 自适应 IP 前缀检测与解析 | `MAVLink_message.parse()` |

### 2.3 Class 2: _NestAirplane 轻型假飞机 (L460-2368)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L442-447 | 类文档（无网卡/线程、消息由机巢转发） | — |
| L449-529 | `_UPDATABLE_FIELDS`（67 字段：风速、序列号、负载配参、负载状态、版本、GPS 位置、飞行状态机、灯光、autopilot、电池/电压） | — |
| L514-518 | 时序常量 | `_HEARTBEAT_INTERVAL=5.0`, `_STATUS_REPORT_INTERVAL=5.0`, `_HEARTBEAT_SEND_INTERVAL=0.5`, `_HANDSHAKE_TIMEOUT=30.0` |
| L520-538 | 协议常量（消息 ID 枚举：0,1,3,76,50,77,11,20,21,23,41,46,55,63 入站 + 47,22,24,42,59 出站） | `_MSG_ID_HEARTBEAT`, `_MSG_ID_COMMAND_LONG` 等 |
| L550-569 | 飞行状态机枚举 | `_UAV_MODE_G=4`, `_UAV_MODE_R=6`, `_UAV_MODE_LD=9`, `_FLY_DISARM` ~ `_FLY_RETURN`, `_PLAY_IDLE` ~ `_PLAY_LANDED` |
| L586-591 | 握手状态机 | `_HS_IDLE=0`, `_HS_WAIT_ID_3=1`, `_HS_WAIT_ID_1=2`, `_HS_COMPLETED=3`, `_HS_FAILED=4` |
| L593-600 | `_SENSOR_HEALTH_BITS` + `_SENSOR_HEALTH_INVERTED_BITS` | 16 位传感器健康位图 |
| L788-793 | **`_FAILSAFE_BITS`** — failsafe(0x06) 位表 | `f_ekf_vert`=bit0 ... `f_crash`=bit15（C# AlarmCode 倒序，参数名=枚举名小写化） |
| L603-610 | `_PAYLOAD_LIGHT_MAP` — COMMAND_LONG 挂载点灯映射 | param7 → (index, config_field, name) |
| L612-624 | `_DEFAULT_PARAM_TABLE` — 10 项默认 MAVLink 参数 | `SR0_PARAM`, `SYSID_THISMAV`, `FENCE_ENABLE` 等 |
| L627-661 | `_RESPONSE_RULES`（3 个入站 ID: 0/3/1） + `_STATE_RULES`（12 个入站 ID: 11/46/21/20/23/63/41/50/55/76） | — |
| L663-674 | 状态处理方法名映射表 | `_state_handlers` dict |
| L677-844 | `__init__`（~160 行属性 init + 可选参数 CSV 加载。**v1.1: socket 不再在 __init__ 中创建，延迟到 set_external_mode() 按需创建**） | `ip_str`, `mavlink_version`, `serial`, `code`, `_parent_sender`, `_slot_index` |
| L852-1050 | `process_message(received)` — 主消息处理入口 | — |
| L1052-1270 | 规则调度引擎 + 各 msg_id 处理方法 | `_handle_heartbeat_dmd`, `_handle_calib_time`, `_handle_set_mode`, `_handle_param_request_read`, `_handle_param_request_list`, `_handle_param_set`, `_handle_mission_request_verify`, `_handle_swarm_flight_start`, `_handle_light_data`, `_handle_command_long` |
| L1272-1500 | `_handle_command_long` — MAV_CMD 命令处理（ARM/DISARM / CAN_ARM / FLIGHT_STOP / CHANGE_MISSION / RETURN_TYPE / 挂载点灯等）+ `_should_silence_ack(command)` — ACK 静默检查（显式调用，`_build_id_077_cmd` 不再隐式返回 None） | — |
| L1103-1141 | **`_build_id_077_cmd(self, command, result)`** — 构建 COMMAND_ACK(77)，**永不返回 None**（对齐独立假飞机）。ACK 失败配置：`_ack_fail_count > 0` 时前N次返回 result=4(FAILED) | — |
| L1148-1160 | **`_build_id_006(self)`** — 构建 FAILSAFE(6)（uint16 位掩码，`failsafe_flags` 按 `_FAILSAFE_BITS` 组装；`enable_failsafe=True` 时随 5s 状态周期外发） | **新增** |
| L1143-1173 | **`_should_silence_ack(self, command)`** → bool — ACK 静默检查（新增，从 `_build_id_077_cmd` 中分离）。各 command 独立计数 + 10s 超时重置。调用方在构建 ACK 前先调用本方法，返回 True 时跳过构建 | — |
| L1502-1700 | 消息构建器 | `build_heartbeat()`, `build_packed_state()`, `build_remaining_capacity()`, `build_identify_info()`, `build_param_value()`, `build_version()` |
| L1664-1836 | **剧本文件传输 NET_FILE_COMMAND(63) + bin 落盘 + VERIFY 完成回复（v1.9/v1.10）** | `_parse_mission_id`(L1664, staticmethod), `_handle_net_file_command`(L1673, OPEN/WRITE/CLOSE/VERIFY 分发), `_net_file_open`(L1693, 分配 buffer), `_net_file_write`(L1710, 分片拷贝), `_net_file_close`(L1733, 缓存→`_file_data_cache` + 锁外落盘), `_net_file_verify`(L1763, MD5 比对→verify_return=0 完成回复), `DRAMA_SAVE_ROOT`(L1789), `_save_drama_bin`(L1791), `update_bin_save`(L1825) |
| L1841-1882 | **0x32 bin 改名（v1.11）** | `_format_play_time`(L1841, UTC YYYYMMDD_HHMMSS.mmm), `_rename_last_bin_to_ip_time`(L1850, 最近 bin → `{飞机IP}_{时间}.bin`，已是该格式/目标存在/未接收过则跳过) |
| L2003-2155 | **开始表演 SWARM_FLIGHT_START(50) + 飞行状态机（v1.11 修复）** | `_handle_swarm_flight_start`(L2003, 改名+状态接管+`_flight_base_lat/lon` 捕获+ACK 0/4), `_advance_flight`(L2059, PLAY 分支改用 `_flight_base_lat`+tar 跟随), `_start_flight`(L2124, is_alive 判重入), `_flight_loop`(L2140, ~490ms 周期推进；巢内飞机无 running 属性仅 `_flight_running`) |
| L1702-1880 | 握手状态机 drive | `start_handshake()`, `check_handshake_timeout()` |
| L1882-2000 | 飞行状态机 drive + 飞行模拟 | `_advance_fly_state()`, `_advance_play_state()` |
| L2002-2180 | `update_state(**fields)` / `update_version(**kwargs)` / `update_position(...)` / `update_ack(fail_count, silence_count)` | — |
| L2182-2240 | 参数读写 (`get_param` / `set_param` / `param_request_list` 等) | `UavParamDict`, CSV 加载 |
| L2116-2395 | external mode（v1.3: + `_msg_injector` 消息注入） | `set_external_mode(gs_ip, gs_port)` — 切换并启动外模式接收线程（v1.2）；`set_internal_mode()` — 切回并停止接收线程 + **非 COMPLETED 握手重置为 IDLE（v1.8，修复离巢后入巢不再发状态消息）**；`send_external(msg)` — 直发；**`_external_receive_loop()`** — 外模式接收线程（v1.2 新增，v1.3: + 消息注入回调） |
| L2329-2352 | `close()` — 停止外模式接收线程 + 关闭自有 socket + 停止飞行线程 | — |

### 2.4 Class 3-5: 嵌套子设备 (L2337-2634)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L2337-2438 | `_NestedPPS` — 储能电池 PPS | `_DEVICE_LABEL="储能电池 PPS"`, 15 fields, `_REPORT_INTERVAL=5.0`, `build_state_message()` → msg_id=83 |
| L2439-2526 | `_NestedPPSCharger` — PPS 充电器 | `_DEVICE_LABEL="储能电池充电器"`, 10 fields, `_REPORT_INTERVAL=5.0`, `build_state_message()` → msg_id=84 |
| L2531-2634 | `_NestedLPPC` — LPPC 低功耗处理器 | `_DEVICE_LABEL="LPPC 低功耗处理器"`, 16 fields, `_REPORT_INTERVAL=5.0`, `build_state_message()` → msg_id=100 |

### 2.5 Class 6: _FakeNestSender 主响应器 (L2835-4684)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L2640-2669 | 类文档（2 线程 + 飞机管理 + 协议响应规则结构说明） | — |
| L2671-2690 | 类级注册表 + 默认值（20 字节 sn 等） | `_airplane_registry`, `_instances`, `_DEFAULT_NEST_SN`, `_DEFAULT_BOX_SN` 等 |
| L2692-2748 | 时序常量 + 消息 ID + MAV_CMD/MAV_RESULT 枚举 | `_LOOP_POLL_INTERVAL=0.05`, `_NEST_STATE_SEND_INTERVAL=1.0`, 13 个 MAV_CMD 命令 |
| L2752-2784 | `_RESPONSE_RULES` (id=1→87, id=3→2) + `_STATE_RULES` (76→handle_command_long, 74→handle_get_lowfreq_info, 28→handle_set_code_number) | — |
| L2789-2829 | `_do_handshake()` / `_wait_for_msg_id()` — 同步握手（阻塞式） | — |
| L2831-2933 | `__init__`（~100 行属性 + 嵌套设备字典 + ACK 配置 + 线程启动） | `log_manager`, `fake_nest`, `addr`, `serial`, `code`, `nestId`, `BoxId`, `nestSn`, `nest_plane_layout` |
| L2935-3014 | `start()` / `stop()` / `_cleanup()` 生命周期 | `self.running`, `self.periodic_running`, 线程 join |
| L3056-3068 | **`set_msg_injector(callback)`** — 消息注入回调（v1.3 新增），传播到所有 external mode 飞机 | — |
| L3216-3225 | `update_nest_ip(nestIp)` | — |
| L3241-3289 | **`update_nest_state(**fields)`** — 20 个 msg_id=86 字段（含 viCount/viState/viJudge）+ uavIp/pps_online/ppsCharger_online 连锁同步 | — |
| L3291-3306 | **`update_vision_state(viCount, viState, viJudge)`** — 视觉检测信号（v1.6 新增，uint8 钳制 0-255） | — |
| L3307-3342 | `update_nest_plane_layout(layout)` — 飞机排布 + _sync_airplanes_locked | — |
| L3346-3588 | 飞机同步辅助（`_normalize_uav_ip` / `_make_airplane_serial_code` / `_sync_airplanes_locked` / `_register_external_airplane`） | — |
| L3594-3610 | `update_nest_extend(**fields)` → msg_id=87 字段 | **v1.8 新增 nestIp** → nestIp_87（0x57 专用）;`nestId`, `BoxId`, `nestSn`, `nestHardVer`, `nestVersion`, `BoxSn` |
| L3612-3622 | `update_identify(serial, code)` → msg_id=2 | — |
| L3624-3641 | `update_ack(fail_count, silence_count)` — 机巢 ACK 配置 | 各 command 独立计数、10s 超时重置 |
| L3643-3663 | `update_airplane_ack(ip_str, fail_count, silence_count)` — 飞机 ACK | — |
| L3665-3683 | `update_airplane_offline(ip_str, offline)` — 消息转发开关 | — |
| L3685-3715 | `update_airplane_state(ip_str, **fields)` — 48 个飞机字段 | — |
| L3717-3780 | `update_airplane_mode(ip_str, mode, target_nest_index, target_slot)` — 内外模式 + 跨巢入巢 | — |
| L3782-3807 | `update_airplane_version(**kwargs)` — 飞机版本信息 | — |
| L3809-3824 | `update_pps_state(**fields)` — PPS 15 字段 | — |
| L3826-3840 | `update_pps_charger_state(**fields)` — PPSCharger 10 字段 | — |
| L3842-3859 | `update_lppc_state(ip_str, **fields)` — LPPC 16 字段 | — |
| L3861-3896 | `self.success` 衰减状态机（0.5s Timer） | — |
| L3901-4002 | **`_run()`** — 接收线程主循环（0.05s 轮询、双路由策略 A+B） | — |
| L4004-4127 | **`_periodic_send_loop()`** — 周期发送线程（1s 一次：id=86 + 飞机心跳 + PPS/PPSCharger；LPPC 上报 v1.7 启用；**外/内模式飞机状态块各含 `airplane.enable_failsafe` 门控的 0x06 外发，L4817/L4882**） | 身份识别门闩：未识别前仅发心跳 |
| L4135-4198 | **`_dispatch_request()`** — 机巢消息规则调度（STATE_RULES → RESPONSE_RULES） | 身份识别门闩 + ACK 配置 |
| L4200-4239 | **`_wrap_and_send()`** — 统一外发（IP 前缀 + 日志 + success 标记） | — |
| L4241-4290 | 各组件 dispatch 方法（airplane/pps/pps_charger/lppc） | — |
| L4295-4403 | 消息构建器（id=0/2/86/87/88）— **id=86 含 viCount/viState/viJudge** | `_build_id_000`, `_build_id_002`, `_build_id_086`, `_build_id_087`, `_build_id_088` |
| L4407-4436 | `_build_id_088` — 仅定义暂不外发（v45 补齐 ip/mac/ssid/nestLayer） | — |
| L4441-4496 | `_handle_get_lowfreq_info` → 返回 id=75（MAC/IP/SSID） | — |
| L4501-4620 | **`_handle_command_long`** — 13 种命令处理 | LED(183)/PPS/UAV/Charger/LPPC/固件更新 |
| L4823-4858 | **`_handle_set_code_number`** — SET_CODE_NUMBER(0x1C,28)：回 COMMAND_ACK(77) + 更新机巢 nestId + code（v1.8 新增） | ACK 逻辑对齐 _handle_command_long，受 update_ack 控制 |
| L4622-4684 | **`_build_id_077`** → COMMAND_ACK（含静默/失败计数、各 command 独立 10s 重置） | ack_sys_id 对齐接收 comp_id |

### 2.6 Class 7: _FakeNestSenders 批量管理器 (L4686-4876)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L4438-4469 | 类文档（IP/code/nestId 自动递增规则） | — |
| L4471-4478 | 类级全局计数 + 定位常量 | `_global_nest_counter`, `_POS_BASE_LAT=226868664`, `_POS_BASE_LON=1140224548`, `_POS_STEP=100`, `_POS_ALT_STEP=150` |
| L4480-4572 | **`__init__`** — count 循环创建 FakeNest → _FakeNestSender + 自动定位 | start_ip/start_serial/start_code/start_nestId/start_uav_ip 逐次递增 |
| L4574-4579 | `stop()` — 停止所有线程 + 关闭所有 FakeNest | — |
| L4584-4624 | 静态辅助方法 | `_build_serial`, `_build_code`, `_build_id_bytes`, `_build_nest_sn` |

### 2.7 __main__ 测试入口 (L4878-4929)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L4627-4682 | `if __name__ == "__main__":` — 创建 LogManager + _FakeNestSenders(count=1) + 长时间运行 | 简单测试框架 |

---

## 3. 类层次结构

```
_NestedDeviceBase                        (L111)  ← __init_subclass__ 自动注册子类
│
├── _NestAirplane  (_NestedDeviceBase)   (L442)  ← "轻型假飞机"  (instance_mode="dict")
├── _NestedPPS     (_NestedDeviceBase)   (L2342) ← "储能电池 PPS"  (instance_mode="single")
├── _NestedPPSCharger (_NestedDeviceBase) (L2444) ← "储能电池充电器" (instance_mode="single")
└── _NestedLPPC    (_NestedDeviceBase)   (L2533) ← "LPPC 低功耗处理器" (instance_mode="dict")

FakeNest                                (L137)  ← 传输层：UDP socket + NIC IP 管理
                                              (无继承、无线程)

_FakeNestSender                         (L2640) ← 单机巢响应器：2 线程 + 嵌套设备管理
  ├── owns FakeNest
  ├── owns _NestAirplane[] via _airplanes: dict[str, _NestAirplane]
  ├── owns _NestedPPS × 1 via _pps
  ├── owns _NestedPPSCharger × 1 via _pps_charger
  └── owns _NestedLPPC[] via _lppc_dict: dict[str, _NestedLPPC]

_FakeNestSenders                        (L4438) ← 批量管理器
  ├── owns _FakeNestSender[] via nest_senders: list
  └── owns FakeNest[] via fake_nests: list (1:1 对应)

辅助 dataclass:
  NestedDeviceMeta                       (L97)   ← 嵌套设备类型元数据（label/fields/instance_mode/...）

辅助注册表:
  NESTED_DEVICE_REGISTRY: dict[str, NestedDeviceMeta]  (L108) ← __init_subclass__ 自动填充
```

### 实例化关系

```
_FakeNestSenders(count=2, ...)
  ├── FakeNest(ip_addr="172.17.0.1")  ← UDP 传输层 #0
  │     └── _FakeNestSender(..., fake_nest=fn0)
  │           ├── _airplanes["172.17.1.1"] = _NestAirplane(ip="172.17.1.1", slot=0)
  │           ├── _airplanes["172.17.1.2"] = _NestAirplane(ip="172.17.1.2", slot=1)
  │           ├── ...（共 5 架，由 nest_plane_layout 控制）
  │           ├── _pps = _NestedPPS()           （由 pps_online 控制创建/销毁）
  │           ├── _pps_charger = _NestedPPSCharger() （由 ppsCharger_online 控制）
  │           └── _lppc_dict["172.17.1.1"] = _NestedLPPC() （每个飞机一个）
  │
  ├── FakeNest(ip_addr="172.17.0.2")  ← UDP 传输层 #1
  │     └── _FakeNestSender(..., fake_nest=fn1)
  │           ├── _airplanes["172.17.1.6"] = ...
  │           └── ...
  └── ...
```

---

## 4. 核心类详解

### 4.1 FakeNest (L155-452) — 传输层

**职责**: UDP socket + Windows NIC 辅助 IP 管理。无线程，只提供 `send()` / `receive()` 接口。

**`__init__` 参数**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `ip_addr` | `"172.16.3.180"` | 机巢辅助 IP（添加到网卡上） |
| `ground_station_ip` | `"172.16.200.1"` | 地面站 IP |
| `ground_station_port` | `14650` | 地面站端口 |
| `local_port` | `14651` | 本机绑定端口 |
| `interface` | `"WLAN 6"` | Windows 网卡接口名 |
| `mask` | `"255.240.0.0"` | 子网掩码 |
| `recv_timeout` | `1.0` | socket 接收超时（秒） |

**关键方法**:

| 方法 | 行号 | 说明 |
|------|------|------|
| `_setup_network()` | L174 | 使用 `netsh interface ip add address` 添加辅助 IP；如已存在则跳过 |
| `_udp_setup()` | L197 | 创建 UDP socket，设置 SO_REUSEADDR，绑定 (ip_addr, local_port) |
| `send(message, addr, prepend_ip, prepend_ip_addr, raw_prefix)` | L301 | 发送 MAVLink 消息：支持三种格式（标准 / IP 前缀 / 自定义前缀） |
| `receive(bufsize)` → `(msg, addr, source_ip)` | L355 | 接收并解析：自适应检测 4 字节 IP 前缀 vs 标准 MAVLink 魔数 |
| `close()` | L251 | 关闭 socket + 移除辅助 IP |
| `is_alive` | L290 | 属性：socket 是否存活 |

**数据方向**:

```
send(): 上层 → FakeNest.sock → 网卡 → GCS
receive(): 网卡 → FakeNest.sock → 上层
```

### 4.2 _NestAirplane (L442-2335) — 轻型假飞机

**职责**: 完全自包含的轻型飞机模拟器。不创建网卡节点、无独立线程。消息接收由机巢 receive 线程驱动，外发由机巢 `_wrap_and_send` 完成。

**与 FakeAirplane 的差异**:

| 维度 | FakeAirplane | _NestAirplane |
|------|-------------|---------------|
| 网卡/端口 | 独立网卡 IP + UDP socket | 无，走机巢 UDP 套接字转发 |
| 线程 | 自有 receive/send 线程 | 无，由机巢线程驱动 |
| 消息外发 | 直发（标准 MAVLink） | 通过机巢包装（IP 前缀格式，策略 A） |
| 握手 | 自身线程内阻塞握手 | 非阻塞状态机（IDLE→WAIT_ID_3→WAIT_ID_1→COMPLETED/FAILED，30s 超时） |
| 内外模式 | 仅 external mode | 支持 internal（机巢内）/ external（机巢外，直连 GCS） |

**`__init__` 参数**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `ip_str` | （必填） | 飞机 IP 字符串 |
| `mavlink_version` | `'43'` | MAVLink 协议版本 |
| `serial` | `b'KWL50F0K'` | 序列号 |
| `code` | `b'00000'` | 识别码 |
| `_parent_sender` | `None` | 所属 _FakeNestSender 实例 |
| `_slot_index` | `None` | 在巢内 uavIp 数组中的槽位索引 (0-4) |

**协议响应规则**:

| 规则表 | 行号 | 入站 ID 数量 | 说明 |
|--------|------|-------------|------|
| `_RESPONSE_RULES` | L627 | 3 个 (0, 3, 1) | 无状态回显（心跳→ACK / 获取身份→回复身份 / HEARTBEAT_DMD→回复状态） |
| `_STATE_RULES` | L636 | 12 个 (11,46,21,20,23,63,41,50,55,76,77,59) | 有状态交互（set_mode/calib_time/param_read/param_list/param_set/mission_verify/net_file_command/swarm_flight_start/light_data/command_long/command_ack/remaining_capacity） |

**关键内部方法**:

| 方法 | 说明 |
|------|------|
| `process_message(received)` → `[(msg, label)]` | 消息处理入口，委托 `_dispatch_request` |
| `start_handshake()` | 触发握手状态机（飞机发第一条心跳时调用） |
| `check_handshake_timeout()` | 检查握手是否超时（30s/步） |
| `update_state(**fields)` | 批量更新 48 个状态字段 |
| `update_version(**kwargs)` | 更新版本信息字段 |
| `update_position(cur_lat, cur_lon, tar_lat, tar_lon, ...)` | 更新 GPS 位置 + 高度 |
| `update_ack(fail_count, silence_count)` | 配置 ACK 失败/静默响应 |
| `update_msg_forwarding(enabled)` | 控制消息外发开关 |
| `set_external_mode(gs_ip, gs_port)` | 切换到机巢外模式（自有 socket 直发）。**v1.3: 从 `_parent_sender._msg_injector` 继承消息注入回调** |
| `set_internal_mode()` | 切换回机巢内模式（走机巢转发）。**v1.4: 归巢后保留握手状态（COMPLETED）避免 GCS 不重新识别导致死锁；v1.8: 非 COMPLETED 状态(IDLE/WAIT/FAILED)重置为 IDLE + identified=False，由周期线程重新发起握手，恢复 needs_status_report 门闩下的 0x59/0x05 状态上报（修复离巢后入巢不再发状态消息）** |
| `send_external(msg)` | 外部模式直发消息 |
| `_external_receive_loop()` | 外模式接收线程。**v1.3: + 消息注入回调；v1.4: 使用 `_parse_mavlink_message(data)` 解析（fake_nest 本地函数）** |
| `update(mode, gs_ip, gs_port, target_sender, target_slot)` | 统一的模式切换入口 |
| `release()` | 清理资源（关闭 socket、从注册表移除） |

### 4.3 _FakeNestSender (L2640-4433) — 主响应器

**职责**: 单台机巢的协议响应引擎。持有 2 个 daemon 后台线程（接收 + 周期发送），管理所有嵌套设备实例。

**`__init__` 参数**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `log_manager` | （必填） | LogManager 实例 |
| `fake_nest` | （必填） | FakeNest 传输层实例 |
| `addr` | （必填） | GCS 地址元组 (ip, port) |
| `serial` | `_DEFAULT_SERIAL` | 20 字节序列号 |
| `code` | `_DEFAULT_CODE` | 5 字节识别码 |
| `nestId` | `_DEFAULT_NEST_ID` | 5 字节 nestId |
| `BoxId` | `_DEFAULT_BOX_ID` | 5 字节 BoxId |
| `nestSn` | `_DEFAULT_NEST_SN` | 20 字节 nestSn |
| `nestHardVer` | `1` | nestHardVer |
| `nestVersion` | `_DEFAULT_NEST_VERSION` | 8 字节 nestVersion |
| `BoxSn` | `_DEFAULT_BOX_SN` | 20 字节 BoxSn |
| `nest_plane_layout` | `None`（→[1,1,1,1,1]） | 5 元素列表，1=有飞机 0=无飞机 |

**关键属性**:

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `nestIp` | `str` | fake_nest.local_ip | msg_id=86 上报的巢 IP |
| `uavIp` | `list[str]` | `["0.0.0.0"]*5` | 5 架飞机的 IP 地址 |
| `chargeVolt` | `list[int]` | `[0]*5` | 5 槽位充电电压 |
| `lock_state` | `int` | `0` | 锁定状态 |
| `inpos` | `list[int]` | `[2]*5` | 5 槽位入位状态 |
| `nest_plane_layout` | `list[int]` | `[1]*5` | 飞机排布掩码 |
| `chargePower` | `list[int]` | `[0]*5` | 充电功率 |
| `chargeTmp` | `list[int]` | `[0]*5` | 充电温度 |
| `motorState` | `list[int]` | `[0]*4` | 电机状态 |
| `motorChipState` | `list[int]` | `[0]*2` | 电机芯片状态 |
| `pps_online` | `int` | `0` | PPS 在线标志 |
| `ppsCharger_online` | `int` | `0` | PPS 充电器在线标志 |
| `viCount` | `int` | `0` | 视觉检测计数（uint8，随 id=86 上报）。**初始化时自动=巢内飞机数**，之后由 update_vision_state 手动接管 |
| `viState` | `int` | `0` | 视觉检测状态（uint8，随 id=86 上报，v45 新增） |
| `viJudge` | `int` | `0` | 视觉检测判定（uint8，随 id=86 上报，v45 新增） |
| `_vi_initialized` | `bool` | `False` | 视觉字段是否已初始化（首次自动同步或 update_vision_state 手动设置后置 True，此后 _sync_airplanes_locked 不再覆写 viCount） |
| `nestState` | `int` | `0` | 机巢状态 |
| `nestStateInfo` | `list[int]` | `[0]*16` | 机巢状态信息 |
| `_airplanes` | `dict[str,_NestAirplane]` | `{}` | 飞机实例字典 |
| `_pps` | `_NestedPPS` or `None` | `None` | PPS 实例 |
| `_pps_charger` | `_NestedPPSCharger` or `None` | `None` | PPSCharger 实例 |
| `_lppc_dict` | `dict[str,_NestedLPPC]` | `{}` | LPPC 实例字典 |
| `_camera_stream` | `_CameraMjpegStream` or `None` | `None` | 摄像头 MJPEG 视频流（update_camera_stream 懒创建，v1.7） |

**类级属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `_airplane_registry` | `dict` | 跨巢飞机查找（IP → _NestAirplane） |
| `_instances` | `list` | 所有 _FakeNestSender 实例（按创建顺序） |

**关键方法（非 update_xxx）**:

| 方法 | 行号 | 说明 |
|------|------|------|
| `set_msg_injector(callback)` | L3056 | **v1.3 新增** — 设置消息注入回调，自动传播到所有 external mode 飞机 |
| `start()` | L2935 | 启动两个后台 daemon 线程 |
| `stop()` | L2950 | 设置 running=False + join 线程 |
| `_sync_airplanes_locked()` | L3149 | 根据 uavIp + nest_plane_layout 同步 _airplanes 字典（创建/移除飞机）。**v1.1: 移除飞机时调用 `airplane.close()` 释放 socket** |
| `_register_external_airplane(airplane, slot_index)` | L3320 | 注册外部模式飞机到当前巢 |
| `_wrap_and_send(msg, label, ...)` | L3964 | 统一外发入口：IP 前缀包装 + 发送 + 日志 + success 状态机 |
| `_dispatch_request(received)` | L3899 | 机巢消息按 STATE_RULES → RESPONSE_RULES 调度 |
| `_handle_command_long(received)` | L4247 | 13 种 MAV_CMD 处理（LED/PPS/UAV/Charger/LPPC/固件更新） |
| `_handle_set_code_number(received)` | L4823 | **v1.8 新增** — SET_CODE_NUMBER(0x1C,28)：回 COMMAND_ACK(77, command=28, result=0) 并更新机巢 nestId + code（0x57/0x02 上报同步）；ACK 静默/失败受 update_ack 配置控制 |
| `_handle_get_lowfreq_info(received)` | L4187 | 返回低频信息 id=75（MAC/IP/SSID） |

### 4.4 _FakeNestSenders (L4438-4625) — 批量管理器

**职责**: 一次性创建 count 台机巢及对应响应线程，管理生命周期。

**`__init__` 参数**:

| 参数 | 说明 | 递增规则 |
|------|------|----------|
| `count` | 机巢数量（>=1） | — |
| `start_ip` | 起始 IP | 末段逐个 +1，不超过 .255 |
| `start_serial` | 起始序列号前缀 | 逐巢拼接递增 code（4 位补零） |
| `start_code` | 起始 code (int) | 逐个 +1 |
| `start_nestId` | 起始 nestId (int) | 逐个 +1 |
| `start_uav_ip` | 起始飞机 IP | 每巢 5 架，IP 依次递增 |
| `log_manager` | 日志管理器 | — |
| `start_nest_plane_layout` | 起始飞机排布 | 默认 [1,1,1,1,1] |

**自动定位规则**:

每个机巢的参考经度 = `_POS_BASE_LON + global_nest_idx * _POS_STEP`；
每架飞机在巢内按槽位索引增加经纬偏移（`slot`）和高度（`slot * _POS_ALT_STEP` mm）。

---

## 5. _NestedDeviceBase 子类详解

### 5.1 注册机制 (L111-134)

`_NestedDeviceBase.__init_subclass__` 在子类定义时自动将元数据写入 `NESTED_DEVICE_REGISTRY`。子类必须声明 5 个类属性：

```python
_DEVICE_LABEL: str           # GUI 子 Tab 显示名
_SENDER_UPDATE_METHOD: str   # _FakeNestSender 上的委托方法名
_SENDER_INSTANCES_ATTR: str  # _FakeNestSender 上存放实例的属性名
_INSTANCE_MODE: str          # "dict"（多实例字典） 或 "single"（单例）
_UPDATABLE_FIELDS: dict      # {field_name: (default, kind)}
```

### 5.2 _NestAirplane (L442-2335) — instance_mode="dict"

| 元数据 | 值 |
|--------|-----|
| `_DEVICE_LABEL` | `"轻型假飞机"` |
| `_SENDER_UPDATE_METHOD` | `"update_airplane_state"` |
| `_SENDER_INSTANCES_ATTR` | `"_airplanes"` |
| `_INSTANCE_MODE` | `"dict"` |

**_UPDATABLE_FIELDS (67 个)**:

| 分类 | 字段 | 类型 | 默认值 |
|------|------|------|--------|
| 风速 | `wind_speed_x`, `wind_speed_y` | `int16` | 0, 0 |
| 序列号 | `seq` | `int32` | 604054808 |
| 负载配置 | `laser_config` | `list_int` | [0,0,0,0] |
| | `nova_config`, `firework_config`, `lantern_config`, `trumpet_config`, `parachute_config` | `int` | 0 |
| 负载状态 | `laser_state`, `nova_state`, `lantern_state`, `trumpet_state`, `parachute_state` | `int` | 0 |
| 负载标志 | `lantern`, `trumpet`, `parachute` | `int` | 0 |
| 版本 | `nova_light_version` | `bytes` | b'1234' |
| | `gimbal_version` | `bytes` | b'' |
| | `flight_controller_version` | `bytes` | b'n3.j.196' |
| | `companion_version` | `bytes` | b'V3.631' |
| | `battery_version` | `bytes` | b'' |
| | `gps_version` | `bytes` | b'UM16982' |
| | `servo_ver` | `int` | 0 |
| | `tele_version` | `bytes` | b'E013' |
| | `bms_version` | `bytes` | b'' |
| | `rid_version` | `bytes` | b'' |
| GPS | `cur_lat`, `cur_lon` | `latlon` | 226868664, 1140224548（GUI 度→1e7）|
| | `tar_lat`, `tar_lon` | `latlon` | 同上 |
| | `cur_alt`, `tar_alt` | `alt_m` | 0, 0（GUI 米→mm）|
| GPS 类型 | `fix_type` | `uint8` | 6 (RTK fixed) |
| 飞行状态 | `mode` | `int` | 4 (G 模式) |
| | `armed` | `int` | 0 |
| | `final_mode` | `int` | 6 (R 模式) |
| | `play_duration_ms` | `int` | 0 |
| | `land_duration_ms` | `int` | 4000 |
| | `takeoff_height_mm` | `int` | 5000 |
| | `land_height_mm` | `int` | 3000 |
| 灯光 | `light_r`, `light_g`, `light_b` | `int` | 0 |
| 飞控 | `autopilot` | `int` | 21 (DMD_COM) |
| 电池/电压 | `voltage_battery` | `uint16` | 34000 |
| | `voltage_battery_percent` | `uint16` | 95 |
| | `voltage_battery_diff` | `uint16` | 0 |
| | `voltage_battery_history_diff` | `uint16` | 0 |
| | `bat_serial_prefix` | `bytes` | b'V3F230324-' |
| | `bat_serial_suffix` | `bytes` | b'3355' |
| | `bat_serial_need_reset` | `uint8` | 0 |
| | `charge_state` | `uint8` | 0 |
| | `battery_time` | `int` | 78 |
| | `temp_batt` | `int` | 0 |
| | `battery_capability` | `int` | 20 |
| | `battery_used_times` | `int` | 12 |
| | `voltage_battery_cell1` ~ `cell6` | `int` | 3500 (×6) |
| | `voltage_rid_bat` | `int` | 0 |

**bin 保存运行时属性（v1.9/v1.10，不在 `_UPDATABLE_FIELDS` 中——经 `update_bin_save` 更新）**:

| 属性 | 默认值 | 说明 |
|------|--------|------|
| `enable_bin_save` | `True` | 接收剧本后自动落盘（默认开启） |
| `bin_save_dir` | `DRAMA_SAVE_ROOT` | 保存目录（`D:\Work\dmd_autotest_project_ycl\tools\simulation_gui\output\drama`，不存在自动创建，GUI 可改） |
| `_file_data_cache` | `{}` | CLOSE→VERIFY 中间缓存 `{fname: bytes}`；VERIFY(5) MD5 比对数据源，MISSION_REQUEST_VERIFY(41) 成功时按 mission_id 最终清理（v1.10） |
| `_last_saved_bin_path` | `None` | 最近一次保存的 bin 路径（预留 0x32 改名，暂未使用） |

### 5.3 _NestedPPS (L2342-2438) — instance_mode="single"

| 元数据 | 值 |
|--------|-----|
| `_DEVICE_LABEL` | `"储能电池 PPS"` |
| `_SENDER_UPDATE_METHOD` | `"update_pps_state"` |
| `_SENDER_INSTANCES_ATTR` | `"_pps"` |
| `_INSTANCE_MODE` | `"single"` |

**_UPDATABLE_FIELDS (15 个)**:

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `power_voltage_v` | `float` | 0.0 | 电池电压 |
| `power_current_a` | `float` | 0.0 | 电池电流 |
| `power_remaining_cap_mah` | `float` | 0.0 | 剩余容量 |
| `power_full_cap_mah` | `float` | 0.0 | 满充容量 |
| `power_alarm_flags` | `int` | 0 | 告警标志 |
| `cell_temp_c` | `float` | 0.0 | 电芯温度 |
| `fet_temp_c` | `float` | 0.0 | FET 温度 |
| `cell_voltage_diff_v` | `float` | 0.0 | 电芯压差 |
| `cells_voltage` | `list` | `[0.0]*6` | 6 节电芯电压 |
| `power_soc` | `int` | 0 | SoC 百分比 |
| `nest_sn` | `list_int` | `[0]*12` | 巢序列号 |
| `power_sn` | `list_int` | `[0]*12` | 电源序列号 |
| `firmware_version` | `list_int` | `[0]*8` | 固件版本 |
| `fan_status` | `int` | 0 | 风扇状态 |
| `heater_status` | `int` | 0 | 加热器状态 |

**周期上报**: msg_id=83, sys_id=COMP_ID_NEST_PPS(36), 每 5 秒。
**生命周期**: 由 `update_nest_state(pps_online=1/0)` 控制创建/销毁。

### 5.4 _NestedPPSCharger (L2444-2526) — instance_mode="single"

| 元数据 | 值 |
|--------|-----|
| `_DEVICE_LABEL` | `"储能电池充电器"` |
| `_SENDER_UPDATE_METHOD` | `"update_pps_charger_state"` |
| `_SENDER_INSTANCES_ATTR` | `"_pps_charger"` |
| `_INSTANCE_MODE` | `"single"` |

**_UPDATABLE_FIELDS (10 个)**:

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `input_voltage_v` | `float` | 0.0 | 输入电压 |
| `input_current_a` | `float` | 0.0 | 输入电流 |
| `output_voltage_v` | `float` | 0.0 | 输出电压 |
| `output_current_a` | `float` | 0.0 | 输出电流 |
| `output_power_w` | `float` | 0.0 | 输出功率 |
| `charger_alarm_flags` | `int` | 0 | 告警标志 |
| `charger_fw_ver` | `list_int` | `[0]*8` | 充电器固件版本 |
| `charger_status` | `int` | 0 | 充电器状态 |
| `fan_status` | `int` | 0 | 风扇状态 |
| `charger_temp_c` | `int` | 0 | 充电器温度 |

**周期上报**: msg_id=84, sys_id=COMP_ID_NEST_PPSCHARGER(38), 每 5 秒。
**生命周期**: 由 `update_nest_state(ppsCharger_online=1/0)` 控制创建/销毁。

### 5.5 _NestedLPPC (L2858-...) — instance_mode="dict"

| 元数据 | 值 |
|--------|-----|
| `_DEVICE_LABEL` | `"LPPC 低功耗处理器"` |
| `_SENDER_UPDATE_METHOD` | `"update_lppc_state"` |
| `_SENDER_INSTANCES_ATTR` | `"_lppc_dict"` |
| `_INSTANCE_MODE` | `"dict"` |

**_UPDATABLE_FIELDS (26 个)**:

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `voltage` | `int` | 0 | 电压 |
| `current` | `int` | 0 | 电流 |
| `remaining_capacity` | `int` | 0 | 剩余容量 |
| `full_charge_capacity` | `int` | 0 | 满充容量 |
| `cycle_count` | `int` | 0 | 循环次数 |
| `health` | `int` | 0 | 健康度 |
| `cell_delta` | `int` | 0 | 电芯压差 |
| `temperature` | `int` | 0 | 温度 |
| `fet_temperature` | `int` | 0 | FET 温度 |
| `cell_voltages` | `list` | `[0]*3` | 3 节电芯电压 |
| `sn_prefix` | `list_int` | `[0]*8` | SN 前缀 |
| `sn_suffix` | `list_int` | `[0]*4` | SN 后缀 |
| `soc` | `int` | 0 | SoC 百分比 |
| `parachute_healthy` | `int` | 0 | 降落伞健康 |
| `bms_healthy` | `int` | 0 | BMS 健康 |
| `piezo_healthy` | `int` | 0 | 蜂鸣器健康 |
| `cell_voltage_delta` | `float` | 0.0 | **v1.7** id=80 电芯压差 (V) |
| `soh` | `int` | 0 | **v1.7** id=80 健康度 |
| `battery_temp` | `int` | 0 | **v1.7** id=80 电池温度 |
| `fet_temp` | `int` | 0 | **v1.7** id=80 FET 温度 |
| `fault_flags` | `int` | 0 | **v1.7** id=81 故障标志 (uint32) |
| `failsafe_flags` | `int` | 0 | **v1.7** id=101 故障安全标志 (uint32) |
| `lifetime_counts` | `list_int` | `[0]*12` | **v1.7** id=82 12 类故障次数 |
| `lifetime_lasts` | `list_int` | `[0]*12` | **v1.7** id=82 12 类故障最后循环 |
| `history_counts` | `list_int` | `[0]*12` | **v1.7** id=102 12 类历史次数 |
| `history_lasts` | `list_int` | `[0]*12` | **v1.7** id=102 12 类历史最后循环 |

**周期上报**（v1.7 启用，此前已注释屏蔽）:
- `LPPC_HEARTBEAT`(100) @~1Hz，sys_id=COMP_ID_LPPC(37)，前缀首字节=槽位层索引（协议文档 §4.4.7，`raw_prefix=bytes([layer,0,0,0])`）
- 新 LPPC 消息 @5s：`LPPC_BATTERY_STATE`(80)、`LPPC_FAULT_STATUS`(81)、`LPPC_LIFETIME_INFO`(82)、`LPPC_FAILSAFE`(101)、`LPPC_BATTERY_HISTORY`(102)
- `process_message` 支持 COMMAND_LONG LPPC 命令（50001-50008）回 ACK(sys_id=37)

**生命周期**: 每个巢内飞机自动创建一个 LPPC 实例（`_sync_airplanes_locked` 自动创建）。

---

## 6. 线程模型

`_FakeNestSender` 持有 2 个 daemon 后台线程。

```
_FakeNestSender
├── Thread 1: _run()                     ← 接收线程 (L3668)
│   ├── 轮询间隔: 0.05s (_LOOP_POLL_INTERVAL)
│   ├── 调用: fake_nest.receive()
│   ├── 过滤: 忽略心跳 (msg_id=0)
│   └── 路由: 策略 A (IP 前缀) → 策略 B (comp_id 广播)
│       ├── _dispatch_request(received, addr)         → 机巢自身响应
│       ├── _dispatch_airplane_response(airplane, msg) → 飞机响应
│       ├── _dispatch_pps_response(msg)               → PPS 响应
│       └── _dispatch_pps_charger_response(msg)       → PPSCharger 响应
│
└── Thread 2: _periodic_send_loop()       ← 周期发送线程 (L3771)
    ├── 间隔: 1.0s (_NEST_STATE_SEND_INTERVAL)
    ├── 始终发送: 机巢心跳 id=0
    ├── 外部模式飞机心跳 + 状态 (5s 间隔，绕过身份门闩)
    ├── 身份识别完成后:
    │   ├── 机巢打包状态 id=86 (0x56)
    │   ├── 内部模式飞机心跳 id=0 (IP 前缀，5s 间隔)
    │   ├── 内部模式飞机状态 id=5 + id=59 (5s 间隔)
    │   ├── failsafe(0x06)：enable_failsafe=True 的飞机随状态周期外发（外模式 send_external / 内模式 _wrap_and_send，两侧门控）
    │   ├── PPS 状态 id=83 (5s 间隔)
    │   └── PPSCharger 状态 id=84 (5s 间隔)
    └── LPPC 状态 id=100 + 新消息 80/81/82/101/102（v1.7 启用）
```

**线程生命周期**:
- `start()` (L2935): 设置 running/periodic_running = True → 创建并启动两个 daemon 线程
- `stop()` (L2950): 设置 running/periodic_running = False → join(timeout=2) 等待线程退出
- `_cleanup()` (L2988): 清空嵌套设备 + stop + close FakeNest

**线程安全**:
- `self._lock = threading.Lock()` (L2885) — 保护所有 update_xxx 写入 + 嵌套设备同步
- 子设备各自持有 `self._lock`（_NestAirplane / _NestedPPS / _NestedPPSCharger / _NestedLPPC）
- `self.success` 访问需持锁（`_reset_success_locked` / `_mark_success_locked`）

**身份识别门闩** (L3771-3894):
- 周期发送: 未识别前仅发心跳 id=0（内部飞机状态不发送）
- 接收调度: 未识别前仅放行 msg_id=0 和 msg_id=3（`_ALLOW_BEFORE_IDENTIFY`），其余屏蔽
- 收到 id=3 并回复 id=2 后，`_identified = True` 解锁所有消息

---

## 7. update_xxx 方法清单

所有 update_xxx 方法均在 `_FakeNestSender` 上定义，供 integrated_gui.py 的 SimulationPanel 通过反射发现和调用。

| 方法签名 | 行号 | 更新目标 | 字段数 | 说明 |
|----------|------|----------|--------|------|
| `update_nest_ip(nestIp)` | L3518 | 机巢自身 | 1 | 更新 nestIp，重置 success（兼容旧 API；**v1.8 改为只更新公共 nestIp 旧引用,优先用 update_nest_state(nestIp=...)/update_nest_extend(nestIp=...) 拆分更新 86/87**） |
| `update_nest_state(**fields)` | L3647 | 机巢 msg_id=86 | 16 | **v1.8 字段表新增 nestIp** → 写入 nestIp_86（0x56 专用, 与 87 的 nestIp_87 与 FakeNest 本机 IP 解耦）;uavIp(**v1.8 全空防御**: 规整后全 "0.0.0.0"/空时忽略该字段,保护巢内飞机不被 GUI 表单默认值误清)/chargeVolt/lock_state/inpos/chargePower/chargeTmp/motorState/motorChipState/pps_online/ppsCharger_online/viCount/viState/viJudge/nestState/nestStateInfo;自动同步嵌套设备 |
| `update_vision_state(viCount, viState, viJudge)` | L3559 | 机巢 msg_id=86 视觉字段 | 3 | **v1.6 新增** — 视觉检测信号（vi=vision），uint8 自动钳制 0-255，重置 success；调用后 `_vi_initialized=True` 接管，同步不再覆写 viCount |
| `update_camera_stream(enabled)` | L3576 | 机巢摄像头视频流 | 1 | **v1.7 新增** — 开关 HTTP MJPEG 流（:8080/stream），开启后推送循环数字 1~10 的 JPEG 帧 |
| `update_nest_plane_layout(layout)` | L3307 | 机巢飞机排布 | 1 | list[int] 或字符串 "1,0,1,0,1"，调用 _sync_airplanes_locked |
| `update_nest_extend(**fields)` | L3594 | 机巢 msg_id=87 | 6 | nestId/BoxId/nestSn/nestHardVer/nestVersion/BoxSn |
| `update_identify(serial, code)` | L3612 | 机巢 msg_id=2 | 2 | serial + code，无 **kwargs |
| `update_nest_extend(**fields)` | L3929 | 机巢 msg_id=87 | 7 | **v1.8 字段表新增 nestIp** → 写入 nestIp_87（0x57 专用, 与 86 的 nestIp_86 与 FakeNest 本机 IP 解耦）;nestId/BoxId/nestSn/nestHardVer/nestVersion/BoxSn |
| `update_ack(fail_count, silence_count)` | L3624 | 机巢 ACK 配置 | 2 | 各 command 独立计数 + 10s 超时重置 |
| `update_airplane_ack(ip_str, fail_count, silence_count)` | L3643 | 指定飞机 ACK | 3 | 委托 airplane.update_ack() |
| `update_airplane_offline(ip_str, offline)` | L3665 | 指定飞机离线状态 | 2 | 控制 _msg_forwarding_enabled |
| `update_airplane_state(ip_str, **fields)` | L3685 | 指定飞机状态 | 48 | 委托 airplane.update_state() |
| `update_airplane_mode(ip_str, mode, target_nest_index, target_slot)` | L3717 | 指定飞机模式 | 4 | internal/external 模式切换 + 跨巢入巢 |
| `update_airplane_version(**kwargs)` | L3782 | 指定飞机版本 | 10+ | 委托 airplane.update_version()，ip_str 必填 |
| `update_pps_state(**fields)` | L3809 | PPS 状态 | 15 | 委托 _pps.update_state() |
| `update_pps_charger_state(**fields)` | L3826 | PPSCharger 状态 | 10 | 委托 _pps_charger.update_state() |
| `update_lppc_state(ip_str, **fields)` | L3842 | LPPC 状态 | 16 | 委托 _lppc_dict[ip_str].update_state() |

| `update_bat(**kwargs)` | L2132 (飞机) | 指定飞机电池 | 19 | 委托 airplane.update_bat()，18 个电池/电压字段 |

**_NestAirplane 自身 update 方法**（由 NestedDevicePanel 直接发现）:

| 方法签名 | 行号 | 字段数 | 说明 |
|----------|------|--------|------|
| `update_state(**fields)` | L1903 | 67 | 通用字段更新，按名称 setattr |
| `update_wind_speed(wind_speed_x, wind_speed_y)` | L1913 | 2 | 风速参数 |
| `update_laser(laser_config, laser_state)` | L1919 | 2 | 激光参数 |
| `update_nova(nova_config, nova_state)` | L1925 | 2 | 高亮灯参数 |
| `update_firework(firework_config)` | L1931 | 1 | 烟花参数 |
| `update_lantern(lantern_config, lantern_state, lantern)` | L1936 | 3 | 折叠灯参数 |
| `update_trumpet(trumpet_config, trumpet_state, trumpet)` | L1943 | 3 | 喇叭参数 |
| `update_parachute(parachute_config, parachute_state, parachute)` | L1950 | 3 | 降落伞参数 |
| `update_ack(fail_count, silence_count)` | L1957 | 2 | ACK 配置 |
| `update_failsafe(enable=False, f_crash=False, ..., f_ekf_vert=False)` | L2375 | 17 | **新增** — failsafe(0x06) 故障位配置（F_EKF_VERT=bit0 ... F_CRASH=bit15，对齐 C# AlarmCode）；未配置的故障位一律置 0（全量覆盖语义）；enable=True 时机巢周期线程随 5s 状态外发 0x06，默认不外发。**自身版本优先于合并的 `_FakeAirplaneMessageSender.update_failsafe`（两侧签名一致，GUI 点击均生效）** |
| `update_msg_forwarding(enabled)` | L1976 | 1 | 消息外发开关 |
| `update_version(**kwargs)` | L1985 | 10 | 版本字段 |
| `update_state_extend(**fields)` | L2175 | 33 | **v1.8 新增** — 消息 8(id=8 拓展心跳) 全字段更新：姿态(roll/pitch/yaw)/温度(temp_imu/temp_baro/temp_batt)/anchor_hash/电池(cell1-6/capability/used_times/rid_bat/battery_time)/版本(10 个)/uas_code/laser_temperature + 机巢定位 4 字段(is_inside_nest/loc_nest_layer/loc_nest_id/loc_nest_sn,手工值持续生效,**仅出入巢动作覆盖**,机巢改号不覆盖);白名单校验 |
| `update_sensor_health(**kwargs)` | L2020 | 16 | 传感器状态 |
| `update_param_hash(value, source)` | L2054 | 2 | param_hash 设置 |
| `update_position(cur_lat, cur_lon, tar_lat, tar_lon, cur_alt, tar_alt, fix_type)` | L2070 | 7 | 位置字段（GUI: latlon×4+alt_m×2, getter 自动 ×1e7/×1000） |
| `update_bat(**kwargs)` | L2132 | 19 | 电池/电压字段 |
| `update_bin_save(enable=True, save_dir=None)` | L1825 | 2 | **v1.9 新增** — bin 文件保存开关/路径（默认开启，对齐独立假飞机 API；接收剧本后自动保存 `Nest_{机巢id}_{飞机id}_{时间戳}.bin`，0x32 改名暂不实现） |

**方法总数**: 16 个（`_FakeNestSender`）+ 18 个（`_NestAirplane` 自身）

---

## 8. 消息路由

### 8.1 两种互补路由策略（`_run` 主循环，L3668-3769）

**策略 A — IP 前缀精确路由**（优先级最高）:

当 `receive()` 解析到 `source_ip` 非空（消息带有 4 字节 IP 前缀）时：

```
source_ip 命中 → 仅对应组件回复
├── source_ip in _airplanes → _dispatch_airplane_response(airplane, received)
└── source_ip == local_ip   → _dispatch_request(received)         (机巢自身)
                              + _dispatch_pps_response(received)
                              + _dispatch_pps_charger_response(received)
```

如未匹配到已知组件，回退到策略 B。

**策略 B — comp_id 广播路由**:

当消息为纯 MAVLink（无前缀）时，按 `received.comp_id` 分发：

| comp_id | 常量 | 路由目标 |
|---------|------|----------|
| `0` | `COMP_ID_ALL` | 机巢 + 所有飞机 + PPS + PPSCharger |
| `1` | `COMP_ID_AUTOPILOT1` | 所有飞机（批量握手） |
| `35` | `COMP_ID_NEST` | 机巢自身 |
| `36` | `COMP_ID_NEST_PPS` | PPS |
| `37` | `COMP_ID_LPPC` | LPPC（v1.7 启用） |
| `38` | `COMP_ID_NEST_PPSCHARGER` | PPSCharger |
| `41` | `COMP_ID_NEST_CHARGER` | 机巢（充电器路径） |
| `255` | `SYS_ID_BROADCAST` | 全部组件（同 comp_id=0） |

### 8.2 消息响应规则总览

**机巢 `_RESPONSE_RULES` (L2752-2775)**:

| 入站 msg_id | 说明 | 出站 msg_id | 构建器 | 条件 |
|-------------|------|-------------|--------|------|
| 1 | HEARTBEAT_DMD | 87 | `_build_id_087` | `extend == 1` |
| 3 | GET_IDENTIFY_INFO | 2 | `_build_id_002` | — |

**机巢 `_STATE_RULES` (L2781-2784)**:

| 入站 msg_id | 说明 | 处理方法 |
|-------------|------|----------|
| 76 | COMMAND_LONG | `_handle_command_long` （13 种 MAV_CMD 支持） |
| 74 | GET_LOWFREQ_INFO | `_handle_get_lowfreq_info` （MAC/IP/SSID） |
| 28 | SET_CODE_NUMBER (0x1C) | `_handle_set_code_number` （回 ACK + 更新 nestId/code，v1.8 新增） |

**飞机 `_RESPONSE_RULES` (L627-635)**:

| 入站 msg_id | 说明 | 出站 msg_id | 条件 |
|-------------|------|-------------|------|
| 0 | HEARTBEAT | 0 | 握手完成后回复 |
| 3 | GET_IDENTIFY_INFO | 2 | 握手状态机驱动 |
| 1 | HEARTBEAT_DMD | 5 (packed_state) | `extend == 1` |

**飞机 `_STATE_RULES` (L636-661)**:

| 入站 msg_id | 说明 | 处理 |
|-------------|------|------|
| 11 | SET_MODE | 模式切换 |
| 46 | CALIB_TIME | 时间校准 |
| 21 | PARAM_REQUEST_LIST | 参数列表请求 |
| 20 | PARAM_REQUEST_READ | 参数读取 |
| 23 | PARAM_SET | 参数设置 |
| 63 | NET_FILE_COMMAND | 文件传输 |
| 41 | MISSION_REQUEST_VERIFY | 任务验证 |
| 50 | SWARM_FLIGHT_START | 蜂群飞行启动 |
| 55 | LIGHT_DATA | 灯光数据 |
| 76 | COMMAND_LONG | 13 种飞行命令 |

---

## 9. 与 integrated_gui.py 的交互

### 9.1 SimConfig 配置

`_build_sim_configs()` (integrated_gui.py L1040-1188) 中的 `SimConfig("nest")` 配置:

```python
SimConfig(
    key="nest",
    label="假机巢",
    source_file=Path("fake_nest.py"),
    transport_cls=FakeNest,
    sender_cls=_FakeNestSender,
    mgr_cls=_FakeNestSenders,
    known_param_types={
        "count": "int", "start_ip": "str", "start_serial": "str",
        "start_code": "int", "start_nestId": "int", "start_uav_ip": "str",
        "nestIp": "str", "serial": "bytes", "code": "bytes",
    },
    param_defaults={
        "count": 2, "start_ip": "172.17.0.1", "start_serial": "NESTF0K",
        "start_code": 1, "start_nestId": 1, "start_uav_ip": "172.17.1.1",
    },
    aid_prefix="FN_",
    has_nested_devices=True,  ← 触发嵌套设备解析
)
```

### 9.2 AST 动态反射链路

```
_build_sim_configs() → SimConfig("nest")
  ↓
SimulationPanel.__init__()
  ├── _parse_source(fake_nest.py)              ← 提取模块常量 + init_attrs
  ├── _discover_update_methods(_FakeNestSender) ← 扫描 14 个 update_xxx 方法
  ├── _discover_add_params(_FakeNestSenders)    ← 提取 __init__ 参数
  └── _parse_nested_devices_from_source(fake_nest.py)  ← 发现 4 个 _NestedDeviceBase 子类
        ↓
      NESTED_DEVICE_REGISTRY 镜像 → dict[str, NestedDeviceMeta]
        ↓
      NestedDevicePanel × 4（轻型假飞机 / 储能电池 PPS / 储能电池充电器 / LPPC）
```

### 9.3 NestedDevicePanel 子 Tab 创建

每个 `_NestedDeviceBase` 子类生成一个 `NestedDevicePanel` 子 Tab，嵌入在假机巢 Tab 内：

```
[Tab 2] SimulationPanel("nest")
  ├── [子 Tab 0] NestedDevicePanel(_NestAirplane)
  │     └── target: 所有 sender 的 _airplanes 字典键 (IP 字符串)
  │     └── update: _FakeNestSender.update_airplane_state(ip_str=..., **fields)
  │
  ├── [子 Tab 1] NestedDevicePanel(_NestedPPS)
  │     └── target: 所有 sender 的 _pps 单例
  │     └── update: _FakeNestSender.update_pps_state(**fields)
  │
  ├── [子 Tab 2] NestedDevicePanel(_NestedPPSCharger)
  │     └── target: 所有 sender 的 _pps_charger 单例
  │     └── update: _FakeNestSender.update_pps_charger_state(**fields)
  │
  └── [子 Tab 3] NestedDevicePanel(_NestedLPPC)
        └── target: 所有 sender 的 _lppc_dict 字典键 (IP 字符串)
        └── update: _FakeNestSender.update_lppc_state(ip_str=..., **fields)
```

### 9.4 消息注入链路（v1.3 新增，v1.3.2 修正为 GCS IP）

飞机离巢后消息注入 UDP 监控的完整链路。
**src_ip/src_port 使用地面站 IP:port（`self._gs_ip`/`self._gs_port`，对齐机巢 `_SocketInterceptor` 使用 `transport.ground_station_ip`）**，
dst_ip/dst_port 使用飞机自身，确保监控中显示为「GCS → 飞机」：

```
IntegratedMainWindow
  → panel.set_message_injector(lambda d, sip, sp, dip, dp:
        self._udp_panel.inject_raw_message(d, sip, sp, dip, dp))

SimulationPanel.set_message_injector()
  ├── _patch_transport_socket(transport)  ← 巢内模式：FakeNest.sock → _SocketInterceptor
  └── sender.set_msg_injector(callback)   ← 外模式：_FakeNestSender → _NestAirplane

_FakeNestSender.set_msg_injector(callback)
  → self._msg_injector = callback
  → 传播到所有已 external 飞机的 airplane._msg_injector

_NestAirplane._external_receive_loop()
  → self._sock.recvfrom() → data, addr
  → src_ip = self._gs_ip    ← 地面站 IP（对齐机巢 transport.ground_station_ip）
  → src_port = self._gs_port
  → dst_ip = self.ip         ← 飞机 IP
  → dst_port = self._local_port
  → self._msg_injector(data, src_ip, src_port, dst_ip, dst_port)
  → FullUdpMonitorPanel.inject_raw_message()
```

### 9.5 关键差异（与 fake_airplane 对比）

| 维度 | fake_airplane | fake_nest |
|------|--------------|-----------|
| 嵌套设备 | 无 | 4 个 _NestedDeviceBase 子类 |
| 参数扫描 | init_attrs 直接来自 sender_cls | sender_cls + 嵌套子类 _UPDATABLE_FIELDS |
| 跨巢操作 | 无 | `update_airplane_mode` 支持 target_nest_index |
| ACK 配置 | sender 级别 | 机巢级别 + 飞机级别两层 |
| 周期发送间隔 | 1s (飞机心跳) | 1s (巢状态) + 5s (子设备) |
| 身份识别 | handshake_completed 标志 | `_identified` 门闩 |

---

## 10. 修改指南

> **核心原则**: 修改代码后，在本文档对应 section 更新行号和描述。

### 场景 1: 新增一个嵌套设备类型（如 _NestedFan）

1. 创建 `_NestedFan(_NestedDeviceBase)` 类（参照 `_NestedPPS` 模式）:
   ```python
   class _NestedFan(_NestedDeviceBase):
       _DEVICE_LABEL = "散热风扇"
       _SENDER_UPDATE_METHOD = "update_fan_state"
       _SENDER_INSTANCES_ATTR = "_fan"
       _INSTANCE_MODE = "single"
       _UPDATABLE_FIELDS = {
           'fan_speed_rpm': (0, 'int'),
           'fan_temp_c': (0.0, 'float'),
       }
       _REPORT_INTERVAL = 5.0
       def __init__(self): ...
       def build_state_message(self): ...  # msg_id=新ID
       def update_state(self, **fields): ...
   ```
2. 在 `_FakeNestSender.__init__` 中新增 `self._fan = None`
3. 在 `_FakeNestSender` 上新增 `update_fan_state(**fields)`
4. 在 `_periodic_send_loop` 中新增风扇状态上报逻辑
5. 在 `_run` 中新增 comp_id 路由分支（如需要）
6. `_NestedDeviceBase.__init_subclass__` 会自动注册到 `NESTED_DEVICE_REGISTRY`，integrated_gui.py 的 `_parse_nested_devices_from_source` 会自动发现
7. 更新本文档 §3/§5/§7 对应内容

### 场景 2: 为机巢新增 update_xxx 方法

1. 在 `_FakeNestSender` 上新增方法（参照 `update_nest_extend` 模式）
2. `integrated_gui.py` 的 `_discover_update_methods` 会自动通过 `inspect.getmembers` 发现新方法
3. 如需参数类型提示，在 `SimConfig.known_param_types` 中添加条目
4. 更新本文档 §7

### 场景 3: 修改消息周期上报内容

1. 定位 `_FakeNestSender._periodic_send_loop()` (L3771-3894)
2. 修改对应消息的构建逻辑（`_build_id_086` / `_build_id_087` / `_build_id_083` / `_build_id_084` 等）
3. 如需新增周期消息，复制现有的 PPS 上报模式
4. 注意身份识别门闩：未识别前仅发心跳
5. 更新本文档 §2.5/§6

### 场景 4: 新增 MAV_CMD 命令处理

1. 在 `_FakeNestSender._handle_command_long()` (L4247) 中新增 `elif command == YOUR_CMD:` 分支
2. 如需新增 MAV_CMD 常量，在 _FakeNestSender 类级属性区域 (L2721-2743) 添加
3. 更新本文档 §4.3

### 场景 5: 修改飞机握手流程

1. 定位 `_NestAirplane` 类的握手状态机方法:
   - `start_handshake()` (L1702 附近) — 触发握手
   - `check_handshake_timeout()` (L1720 附近) — 超时检查
   - `_advance_handshake(received)` (L1740 附近) — 状态推进
2. 修改 `_HS_IDLE` ~ `_HS_FAILED` 状态常量 (L586-591)
3. 注意与 period_send_loop 的耦合（飞机首次发心跳时触发握手）

### 场景 6: 排查飞机消息未收到回复

1. 检查飞机 IP 是否在 `uavIp` 列表中（且非 "0.0.0.0"）
2. 检查 `nest_plane_layout[i]` 是否 = 1（对应槽位未被屏蔽）
3. 检查飞机 `_msg_forwarding_enabled` 是否为 True（未被 `update_airplane_offline` 设为离线）
4. 检查握手状态是否完成（消息处理入口有 `_ALLOW_BEFORE_IDENTIFY` 门闩）
5. 检查飞机 `_ack_silence_count` 是否导致 ACK 静默
6. 检查 `_periodic_send_loop` 中身份识别 `_identified` 是否完成

### 场景 7: 新增一个 update_xxx 方法的字段

1. 修改对应 `_UPDATABLE_FIELDS` 字典（子类级），新增 `'field_name': (default, kind)` 条目
2. 在子类 `__init__` 中新增 `self.field_name = default` 属性初始化
3. 在子类 `build_state_message()` 的 `fields` 字典中新增对应字段
4. `integrated_gui.py` 的 NestedDevicePanel 会通过 `_parse_nested_devices_from_source` 自动发现新字段
5. 更新本文档 §5 对应子类的 _UPDATABLE_FIELDS 表格

### 场景 8: 异常构造清理

`_FakeNestSenders.__init__` (L4558-4572) 有部分构造失败的清理逻辑。添加循环内逻辑时，注意：
- 已创建的 sender 列表 → `nest_senders`
- 已创建的 FakeNest 列表 → `fake_nests`
- 清理时先 stop sender 线程，再 close FakeNest socket
- 注释中提到：网卡辅助 IP 在 close 时暂未撤销（FakeNest.close 不调用 Remove-NetIPAddress）

---

> **更新记录**:
> - 2026-09-10: v1.12 — **`_NestAirplane` 新增 failsafe(0x06) 消息支持（对齐独立假飞机）**：①类常量 `_FAILSAFE_BITS`（L788，f_ekf_vert=bit0 ... f_crash=bit15，C# AlarmCode 倒序）；②`__init__` 新增 `enable_failsafe=False` + `failsafe_flags`（16 位全 0，**默认不外发**）；③新增 `update_failsafe(enable, f_crash, ..., f_ekf_vert)`（L2375，17 参数全量覆盖语义——未配置的故障位一律置 0；与 `_FakeAirplaneMessageSender.update_failsafe` 签名一致，自身版本优先，规避 v1.9 单侧实现点击 AttributeError 的坑）；④新增 `_build_id_006()`（L1148，uint16 位掩码组装）；⑤`_FakeNestSender._periodic_send_loop` 外模式（L4817 `send_external`）/内模式（L4882 `_wrap_and_send` 带 IP 前缀）两处 `airplane.enable_failsafe` 门控外发，随 5s 状态周期。GUI：NestedDevicePanel 反射自动发现（类型经默认值 False 推断为 bool True/False 下拉），零 GUI 代码改动。新增测试 `test_failsafe_0x06.py` TC5（巢内飞机位掩码/覆盖语义/周期两处门控）+ GUI 实操 `_gui_verify_failsafe_0x06.py` V2（真实面板点击应用 → 真实 _NestAirplane mask=0x0080），全套 421 测试通过
> - 2026-09-08: v1.11 — **修复「巢内飞机不响应 0x32（开始表演）」并补全 0x32 bin 改名**。①根因：`_handle_swarm_flight_start` 调用 `self._start_flight()`，但 `_start_flight`/`_flight_loop`/`_flight_thread` 未从独立假飞机移植 → 收到 0x32 即 AttributeError（被机巢 `_run` 外层 try 吞掉）→ 0x77 ACK 永远不回、`_advance_flight` 无调用方状态机不动。修复：`__init__` 补 `_flight_thread`/`_flight_base_lat`/`_flight_base_lon`；新增 `_start_flight`（is_alive 判重入）+ `_flight_loop`（~490ms 周期调 `_advance_flight`，巢内飞机无 `running` 属性仅判 `_flight_running`）；`_handle_swarm_flight_start` 对齐假飞机补 `_rename_last_bin_to_ip_time(play)` 调用与基准坐标捕获；`_advance_flight` PLAY 分支位置微动改用 `_flight_base_lat` 并同步 tar_lat/tar_lon 跟随；`close()` join 飞行线程。②新增 `_format_play_time`(L1841) + `_rename_last_bin_to_ip_time`(L1850)：0x32 触发最近一次接收的 bin 改名 `{飞机IP}_{YYYYMMDD_HHMMSS.mmm}.bin`（时间取 play 字段 UTC；已是该格式/目标已存在/未接收过则跳过，巢内飞机 IP 直接用 `self.ip`）。③产品缺陷顺带修复：`_FakeNestSender.stop()`/`_cleanup()` 清空 `_airplanes` 前遍历 `airplane.close()`（原直接 clear 导致飞行/外模式线程泄漏）。新增测试 `test_fake_nest_swarm_start.py` 10 用例（ACK/状态接管/线程启动/时间注入全流程 TAKEOFF→PLAYING→RETURN→LANDED→DISARM/飞行中拒绝 result=4/close 清理与重启/改名三例）+ e2e `_e2e_verify_swarm_start.py` 13 断言（真实机巢回环：机巢握手→飞机 WAIT_ID_3 就绪后握手 COMPLETED→0x32→GCS 实收 0x77 result=0→0x05 周期上报 play_state 序列 WAIT_TK→TAKEOFF→PLAYING、cur_alt 0→3120→5000 爬升→飞行中 result=4→stop 后线程退出）；e2e 揭示握手时序要点：**须先与机巢自身握手（sender._identified 门闩控制周期线程）再等飞机 WAIT_ID_3**，否则 id=3 走 `_RESPONSE_RULES` 兜底（identified=True 但 _hs_state 停 IDLE → 0x05 周期上报被 needs_status_report 拒绝）。全套 409 测试通过
> - 2026-09-07: v1.10 — **①修复「巢内接收剧本最后没有回复完成给地面站」**：`_handle_net_file_command` 原只分发 OPEN/WRITE/CLOSE，地面站传输完成后的 `NET_FILE_VERIFY(5)`（`net_file_verify_file`，MD5 校验）掉进空分支无回复 → 地面站重试 3 次报失败。对齐独立假飞机补全：`_NET_FILE_VERIFY=5` 类常量；`__init__` 新增 `_file_data_cache={}`；`_net_file_close` 缓冲数据移入 `_file_data_cache[fname]`（原直接丢弃）；新增 `_net_file_verify`（`<16s64s` 解包 FMd5+文件名 → cache 取数据 `hashlib.md5` 比对 → ACK `<hi16s64s`（ack_cmd=5 + verify_return（0 匹配/1 不匹配/-1 文件不存在）+ 飞机侧 MD5 + 文件名 64B 补零），ACK 形式与 OPEN/WRITE/CLOSE 一致（id=63、net_file_cmd=4、经 `_build_id_063_ack`→机巢 `_wrap_and_send` 回地面站）；`_handle_mission_request_verify`(41) result=0 时按 mission_id 清理关联缓存（对齐 C# HandleMissionRequestVerify2 最终清理）。②`DRAMA_SAVE_ROOT` 默认路径改为 `D:\Work\dmd_autotest_project_ycl\tools\simulation_gui\output\drama`（不存在自动 makedirs）。新增测试 `test_fake_nest_bin_save.py` +5 用例（VERIFY 匹配 0/不匹配 1 回带实际 MD5/文件不存在 -1 MD5 全零/41 清理 cache/默认路径）共 16 用例；e2e `_e2e_verify_bin_save.py` 增 S5 真实回程（GCS socket 发全流程 → 机巢转发 → GCS 收 VERIFY ACK verify_return=0，注意 v45 id=63 `data` 字段 `<h253s` 定长，回包解析需截取实际结构长度），18/18 断言通过，全套 384 测试通过
> - 2026-09-07: v1.9 — **`_NestAirplane`（巢内/离巢假飞机）实现「接收并保存剧本 bin」**，策略对齐独立假飞机 `_FakeAirplaneMessageSender`：①修复 `_parse_mission_id` 缺 `@staticmethod` 导致收到 id=63 OPEN 必抛 TypeError 的 bug（上版本引入）；②`_net_file_open` 分配 `bytearray(f_length)` 缓冲、`_net_file_write` 按 `wr_pos` 分片拷贝 payload（变长 ≤240，fid 不匹配回 -1、越界部分写入回 actual，GCS 端 `net_file_write_file` 依赖 `write_return>=0` + fid 匹配推进/重试）；③`_net_file_close` 登记 mission_id 后**锁外**调用新增 `_save_drama_bin`：受 `enable_bin_save`（**默认 True**）控制，保存到 `bin_save_dir`（默认 `DRAMA_SAVE_ROOT=D:\Work\My_Project_Local\mavlink_monitor\drama`），文件名 `Nest_{机巢id}_{飞机id}_{YYYYMMDD_HHMMSS}.bin`（nestId 取 `_parent_sender.nestId` 5 字节 bytes，缺失回退 `00000` 对齐 `_sync_nest_locating_from_sender`；时间戳后缀避免覆盖历史文件；记录 `_last_saved_bin_path`；**0x32 起飞指令改名功能暂不实现**）；④新增 `update_bin_save(enable=True, save_dir=None)`（对齐假飞机 API，NestedDevicePanel 反射自动发现，自身版本优先于合并的 `_FakeAirplaneMessageSender.update_bin_save`——原控件点击会 AttributeError，现已修复生效；GUI 零代码改动，`enable`→True/False 下拉、`save_dir`→文本框启发式推断）。新增测试 `test_fake_nest_bin_save.py`（11 用例：默认开启/关闭不落盘/落盘命名与内容/重复接收不覆盖/_parse_mission_id 回归/GUI 发现与类型推断/fid 错误/越界部分写入/nestId 缺失回退）+ e2e 验证脚本 `_e2e_verify_bin_save.py`（15 断言：GUI 实操/真实握手+id=63 链路落盘/异常恢复/多飞机不串），全套 379 测试通过
> - 2026-09-01: v1.8 — ①SET_CODE_NUMBER(0x1C,28)：`_FakeNestSender._handle_set_code_number` 回 COMMAND_ACK(77) 并更新机巢 nestId(0x57 上报)+ code(0x02 上报),ACK 受 `update_ack`(silence/fail) 控制、仅 result=0 生效；`_STATE_RULES` 注册 28；`_config.py` nest `known_param_types` 补 fail_count/silence_count。②修复「飞机离巢后入巢不再发状态消息」：`set_internal_mode` 归巢时,非 COMPLETED 握手状态(IDLE/WAIT_3/WAIT_1/FAILED)重置为 IDLE + identified=False,由机巢周期线程重新发起握手,恢复 `needs_status_report` 门闩下的 0x59/0x05 状态上报；COMPLETED 保留(避免地面站不重新识别导致死锁)。③0x56/0x57 消息 nestIp 字段拆分：`__init__` 新增 `nestIp_86`/`nestIp_87`（默认继承 fake_nest.local_ip,与 FakeNest 绑定的本机 IP 解耦）；`update_nest_state(nestIp=...)` 写入 nestIp_86、`update_nest_extend(nestIp=...)` 写入 nestIp_87；周期线程与 _RESPONSE_RULES 各自取独立属性,一个函数只管对应 id 消息的 nestIp,互不影响；`update_nest_ip` 保留为兼容旧 API。新增测试 `test_fake_nest_set_code_number.py`(9 用例)+ `test_fake_nest_reenter.py`(8 用例)+ `test_fake_nest_nestip_split.py`(9 用例)。④新增 `_NestAirplane.update_state_extend(**fields)`（消息 8 全字段更新,33 字段白名单:姿态/温度/hash/电池/版本/uas_code/laser_temperature/机巢定位 4 字段);`_build_id_008` 原硬编码字段(roll/pitch/yaw/temp_imu/temp_baro/anchor_hash/uas_code/laser_temperature)参数化为实例属性(__init__ 默认值不变);修复 `_build_id_008` nova_light_version 默认参数 b"1234" 真值覆盖实例值的 bug(默认参数改 None,update_version/update_state_extend 的 nova_light_version 现已生效);`_UPDATABLE_FIELDS` 补 8 字段声明(float/uint32/bytes);GUI 轻型假飞机 NestedDevicePanel 反射自动发现,零 GUI 代码改动。新增测试 `test_fake_nest_state_extend.py`(8 用例)。⑤修复「update_state_extend 更新不了机巢定位字段」：`_build_id_008` 原 v45 机巢定位字段(is_inside_nest/loc_nest_layer/loc_nest_id/loc_nest_sn)每次构建动态计算(巢内继承 parent_sender/离巢置零),手工值被逐条覆盖;改为实例属性存储 + 动作联动——新增 `_NestAirplane._apply_nest_locating(sender, slot)`(入巢/创建联动,getattr 防御测试桩缺属性)与 `_clear_nest_locating()`(出巢置零),`update()` 出/入巢分支、`_sync_airplanes_locked` 创建飞机、`update_nest_extend(nestId/nestSn=...)` 与 `_handle_set_code_number` 改号(经新增 `_FakeNestSender._refresh_airplanes_nest_locating`)联动覆盖;手工值在巢内/离巢均持续生效;`_UPDATABLE_FIELDS` 补 4 个机巢定位字段声明(uint8/bytes,GUI 控件类型正确)。新增 3 用例(出巢置零/入巢联动/改号传播),共 11 用例。⑥修复「update_state_extend 机巢定位字段对巢内飞机不起作用」：GUI 应用 `update_nest_extend` / `SET_CODE_NUMBER(0x1c)` 时全字段提交(nestId/nestSn 常为未修改默认值),原联动判断 `if 'nestId' in fields` 恒真 → 任何一次机巢 Tab 应用都用机巢当前值覆盖飞机手工 loc 值；改为**值实际变化才联动**（`update_nest_extend` 逐字段比对 `getattr(self,k)!=v`、`_handle_set_code_number` 比对 `self.nestId!=new_id`）,同值重复提交不再覆盖手工 loc 值。新增 TC5b 用例,共 12 用例。⑦**最终定位并修复「update_state_extend 机巢定位字段对巢内飞机不起作用」**：真实拉起 GUI 复现（SimulationPanel+NestedDevicePanel+真实按钮点击）证明 GUI 核心链路正常（修改→应用→属性+0x08 立即生效），真因是 ⑤ 中自行加的「机巢改号→飞机 loc 联动刷新」超出需求定义——真实测试流程中地面站发 SET_CODE_NUMBER(0x1c) 改号时手工 loc 值被联动冲掉；**移除改号联动**（删 `_refresh_airplanes_nest_locating` 及 update_nest_extend/_handle_set_code_number 两处调用），字段优先级严格定为：手工值持续生效，**仅出入巢动作**（update external/internal）覆盖；机巢改号只影响 0x57(nestId)/0x02(code)。TC5/TC5b 合并为「改号不覆盖手工值」，共 11 用例。⑧**最终根因（GUI 端到端实测）**：「update_state_extend 机巢定位字段对巢内飞机不起作用」的真因是 **机巢主 Tab 的 update_nest_state 表单 uavIp 控件默认值为 `__init__` 初始值 "0.0.0.0,..."×5**（GUI 全字段提交时随其它字段一并提交）→ uavIp 被覆盖成全 0 → `_sync_airplanes_locked` 判定所有飞机不在 target_ips → **巢内飞机全部删除**（之后重建则 loc 字段重新继承机巢值）→ 手工设置丢失。update_state_extend 本身经真实 GUI 按钮+真实线程+真实 UDP 回环验证完全正常（应用即生效、12s 周期不覆盖、端到端 0x08 携带手工值）。修复：`update_nest_state` 对 uavIp 增加防御——规整后**全空**（全 "0.0.0.0"/空列表/空值）时忽略该字段（不覆盖 uavIp/_uavIp_configured、不触发 _sync_airplanes_locked、打 warning），清空飞机仍走 update_nest_plane_layout([0,0,0,0,0])；真实 uavIp（含任一有效 IP）行为不变。新增 `tests/test_fake_nest_uavip_guard.py` 7 用例（全 0 忽略/空列表忽略/混合空值忽略/真实 IP 同步不变/显式移除不变/layout 清空不变/GUI 全字段提交复现转绿），全套 368 测试通过
> - 2026-08-27: v1.7 — ①LPPC 系列：启用 `LPPC_HEARTBEAT`(100) 周期推送（@1Hz，前缀首字节=槽位层索引 `[layer,0,0,0]`，协议文档 §4.4.7）；启用 compid=37(LPPC) 路由与 LPPC 首字节(<10) 层路由；新增 5 个新 LPPC 消息 `LPPC_BATTERY_STATE`(80)/`FAULT_STATUS`(81)/`LIFETIME_INFO`(82)/`FAILSAFE`(101)/`BATTERY_HISTORY`(102) 构建与周期上报（@5s）；`process_message` 支持 LPPC 命令回 ACK(sys_id=37)。②MAV_CMD 电源控制：`_handle_command_long` 新增 `MAV_CMD_STANDBY`(40046)+PowerOPType、`POWER_ON/OFF/REST/WAKE_UP`(40057-40060)。③摄像头视频流：新增 `update_camera_stream(enabled)` 开关 + `_CameraMjpegStream`（HTTP `:8080/stream` MJPEG，PIL 生成数字 1~10 循环 JPEG 帧，协议文档 §7.9.2）。新增测试 `test_fake_nest_v45_lppc_power_camera.py`（21 用例）
> - 2026-08-27: v1.6.1 — vi* 初始化策略：`_sync_airplanes_locked` 首次有飞机时自动设 `viCount=巢内飞机数`（`_vi_initialized` 标志），`viState/viJudge` 保持 0；`update_vision_state` 调用后 `_vi_initialized=True` 手动接管，后续 uavIp/layout 同步不再覆写 viCount。新增 `TestFakeNestViInit` 3 用例
> - 2026-08-27: v1.6 — v45 全量对齐。①解析路径（`_parse_mavlink_message` / `FakeNest.receive`）改用 `MAVLINK_VERSION`(45)；②`_NestAirplane`/`_NestedPPS`/`_NestedPPSCharger`/`_NestedLPPC` 默认 `mavlink_version='43'→'45'`；③`nest_packed_state`(86) 接线视觉字段 `viCount/viState/viJudge`（__init__/update_nest_state/_build_id_086/周期发送），新增 **`update_vision_state(viCount, viState, viJudge)`**（uint8 钳制 0-255）；④`_build_id_008` 补 `mavVer=int(MAVLINK_VERSION)`；⑤`_build_id_088` 按 v45 结构补齐 `ip/mac/ssid/nestLayer`；模块 docstring v42→v45。新增测试 `test_fake_nest_v45_vision.py`（10 用例）
> - 2026-08-11: `_NestAirplane._UPDATABLE_FIELDS` GPS 位置字段类型 `uint32→latlon`（度→1e7）、`uint32→alt_m`（米→mm），GUI 支持小数输入自动缩放；`_nested.py` `update_position` 表单 lon/lat 顺序交换（lon 在前）
> - 2026-07-27: v1.5 — 新增 `_NestAirplane.update_bat(**kwargs)` 方法（19 个电池/电压字段）；`_UPDATABLE_FIELDS` 从 48 增至 67 字段；`_build_id_005/_build_id_008` 电压字段改用实例属性
> - 2026-07-24: v1.4 — 新增 `_parse_mavlink_message(data)` 模块级函数（fake_nest 专用，不修改 parse_mavlink）；`set_internal_mode()` 归巢后保留握手状态，修复归巢后不发送非心跳消息的 bug
> - 2026-07-24: v1.3.2 — 修正 src_ip/src_port 为地面站 IP（`self._gs_ip`/`self._gs_port`）
> - 2026-07-24: v1.3 — 新增消息注入链路
> - 2026-07-24: v1.2 — 修复巢内飞机 ACK 响应缺失 + 新增外模式接收线程
> - 2026-07-23: 初始版本
