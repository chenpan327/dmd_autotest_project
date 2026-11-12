# fake_airplane.py — 代码方案

> **文件**: `D:\Work\dmd_autotest_project_ycl\src\Protocol\mavlink\fake_airplane.py`
> **版本**: v1.3
> **行数**: ~2895
> **最后同步**: 2026-09-17
> **注意**: `_parse_waypoints_from_bin` / `visualize_drama_3d` / `visualize_drama_compare` 已从本文件剥离至 `mavlink_monitor/gui/drama_processing.py` 作为模块级独立函数
> **用途**: 假飞机模拟模块，提供 UDP 传输层 + MAVLink 协议响应器 + 批量管理器的完整仿真栈
>
> **关联方案**:
> - [CODE_PLAN.md](./CODE_PLAN.md) — integrated_gui.py 主面板方案（`SimulationPanel` 的 AST 反射目标）
> - [CODE_PLAN_FAKE_NEST.md](./CODE_PLAN_FAKE_NEST.md) — 假机巢模块方案
> - [CODE_PLAN_FAKE_RADIO.md](./CODE_PLAN_FAKE_RADIO.md) — 假电台模块方案

---

## 目录

1. [文件速览](#1-文件速览)
2. [代码分段索引](#2-代码分段索引)
3. [类层次结构](#3-类层次结构)
4. [核心类详解](#4-核心类详解)
5. [update_xxx 方法清单](#5-update_xxx-方法清单)
6. [数据流](#6-数据流)
7. [与 integrated_gui.py 的交互](#7-与-integrated_guipy-的交互)
8. [修改指南](#8-修改指南)

---

## 1. 文件速览

```
fake_airplane.py  (2255 行)
│
├── L1-16     导入（ctypes, subprocess, socket, threading, MAVLink_message, UavParamDict, LogManager）
├── L17-40    模块级常量（IP, 网卡, SYS/COMP ID, CSV 路径, 机型序列号表）
│
├── L42-293   FakeAirplane —— 传输层（UDP socket + Windows NIC IP 管理）
│   ├── L43-66    __init__（IP/端口/超时/mavlink_version）
│   ├── L71-94    _setup_network() —— PowerShell New-NetIPAddress 添加辅助 IP
│   ├── L174-185  _ip_exists_locally() —— 检查 IP 是否已绑定本机
│   ├── L190-215  _udp_setup() —— 创建并绑定 UDP 套接字
│   ├── L217-226  close() —— 关闭 UDP
│   ├── L230-253  send() —— 发送 MAVLink_message
│   └── L255-292  receive() —— 接收并解析 MAVLink_message（DEBUG 打印已注释）
│
├── L295-384  _WindSpeedSender —— 遗留风速监听器（独立线程）
│   └── L387-414  _send_wind_speed_async() —— 模块级异步风速更新函数
│
├── L423-2170 _FakeAirplaneMessageSender —— 单架假飞机协议响应器（主类，~1747 行）
│   ├── L451-647   类级常量（协议 ID / 状态机枚举 / 响应规则表 / ACK 失败配置）
│   ├── L649-805   __init__（160+ 行属性初始化 + CSV 参数加载，含电压字段）
│   ├── L810-833   _cleanup() —— 资源清理
│   ├── L838-866   start() / stop() —— 生命周期管理
│   ├── L868-1146  update_xxx 方法（风速/激光/高亮/烟花/折叠灯/喇叭/降落伞/ACK/param_hash/版本/传感器/位置/电池/drama_state）
│   ├── L1148-1183 self.success 衰减状态机
│   ├── L1188-1230 握手 + 等待消息
│   ├── L1235-1349 主循环 _run() + _dispatch_request() + _build_responses()
│   ├── L1380-1885 有状态协议处理器（对时/参数/剧本/校验/切模式/开始表演/命令 + 飞行状态机）
│   └── L1890-2169 消息构建器（_build_id_000/002/005/008/022/024/042/047/059/060/063_ack/077_cmd/204）
│
├── L2172-2275 _FakeAirplaneMessageSenders —— 批量管理器（创建多架飞机 + 自动定位）
│   ├── L2199-2207  定位常量（纬度/经度基准 + 步进）
│   ├── L2209-2269  __init__（循环创建 FakeAirplane + _FakeAirplaneMessageSender, 每架间隔 2s）
│   └── L2271-2275  stop() —— 批量停止
│
└── L2278-2322 __main__ 入口
```

---

## 2. 代码分段索引

> 使用方法：在 IDE 中 `Ctrl+G` 跳转到对应行号即可定位功能区域。

### 2.1 模块级常量与导入 (L1-40)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L1-14 | stdlib 导入 | `ctypes`, `hashlib`, `subprocess`, `socket`, `struct`, `threading` |
| L11-13 | 项目内导入 | `MAVLink_message`, `UavParamDict`, `LogManager` |
| L17 | 默认飞机 IP | `fake_airplane_ip = "172.16.3.168"` |
| L18 | 网卡接口名 | `NETCARD_INTERFACE = "WLAN 6"` |
| L24 | MAVLink 系统 ID | `SYS_ID_UAV = 1` |
| L25 | 地面站组件 ID | `COMP_ID_GCS = 39` |
| L28 | CSV 参数根目录 | `_PARAM_CSV_BASE` |
| L31-40 | 机型序列号映射表 | `AIRPLANE_MODEL_SERIALS`（8 种机型） |

### 2.2 FakeAirplane — 传输层 (L42-293)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L43-66 | `__init__` — IP/端口/网卡/mask/超时/mavlink_version | `local_ip`, `sock`, `udp_connected` |
| L71-94 | `_setup_network()` — PowerShell 添加辅助 IP | `New-NetIPAddress` |
| L99-138 | `_setup_network_old()` / `_get_local_ip()` — 遗留备用方案（ipconfig 解析） | — |
| L141-169 | `_set_ip_address()` — netsh 静态配置 IP（需管理员权限） | — |
| L174-185 | `_ip_exists_locally()` — 通过 bind 检测 IP 是否已存在 | — |
| L190-215 | `_udp_setup()` — socket 创建 + bind + 10 次重试机制 | — |
| L217-226 | `close()` — 关闭 UDP 套接字 | — |
| L230-253 | `send()` — `message.pack()` → `sendto()` | — |
| L255-292 | `receive()` — `recvfrom()` → `MAVLink_message(hex_data=...)` → 解析 + DEBUG 打印 | — |

### 2.3 _WindSpeedSender — 遗留风速发送器 (L295-414)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L298-308 | `__init__` — 风速x/y, running, thread, lock, success | — |
| L310-315 | `start()` — 启动后台 daemon 线程 | — |
| L317-322 | `stop()` — 停线程 join(2s) | — |
| L324-342 | `_build_wind_speed_msg()` — 构建 msg_id=5 风速消息 | — |
| L344-353 | `update_send_success()` / `update_wind_speed()` — 线程安全更新 | — |
| L355-384 | `_run()` — 收 id=1 → 发风速消息 → sleep(0.5) | — |
| L387-414 | `_send_wind_speed_async()` — 模块级函数，阻塞等待 success=True（1.5s 超时） | — |

### 2.4 _FakeAirplaneMessageSender — 协议常量与枚举 (L451-647)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L452-454 | 默认值 | `_DEFAULT_SEQ`, `_DEFAULT_CODE`, `_DEFAULT_SERIAL` |
| L456-463 | 时序常量 | `_HANDSHAKE_TIMEOUT = 30.0`, `_HEARTBEAT_SEND_INTERVAL = 0.5`, `_SUCCESS_HOLD_SECONDS = 0.5` |
| L466-481 | 入站消息 ID | HEARTBEAT(0), HEARTBEAT_DMD(1), GET_IDENTIFY_INFO(3), COMMAND_LONG(76), SWARM_FLIGHT_START(50), COMMAND_ACK(77), SET_MODE(11), PARAM_REQUEST_READ(20), PARAM_REQUEST_LIST(21), PARAM_SET(23), MISSION_REQUEST_VERIFY(41), CALIB_TIME(46), LIGHT_DATA(55), NET_FILE_COMMAND(63) |
| L484-488 | 出站消息 ID | TIME_ORIGIN(47), PARAM_VALUE(22), PARAM_REQUEST_LIST_ACK(24), MISSION_REQUEST_ACK(42), REMAINING_CAPACITY_STATE(59) |
| L494-497 | UavMode 取值 | G(4), R(6), LD(9) |
| L499-505 | FlyState — 内部飞行状态机 | DISARM(0), LANDED(1), GUIDE_IDLE(2), GUIDE_TAKEOFF(3), GUIDE_PLAY(4), LAND(5), RETURN(6) |
| L508-515 | PlayState — 对外表演进度 | IDLE(0) → DISARMED(1) → WAIT_TK(2) → TAKEOFF(3) → FLYING(4) → PLAYING(5) → LANDING(6) → LANDED(7) |
| L518-522 | MAV_CMD 枚举 | COMPONENT_ARM_DISARM(400), CAN_ARM(401), FLIGHT_STOP(40003), CHANGE_MISSION(40005), RETURN_TYPE(40048) |
| L525-531 | NET_FILE 子命令 | OPEN(0), WRITE(1), READ(2), CLOSE(3), ACK(4), VERIFY(5) |
| L533-544 | 默认参数表 | `_DEFAULT_PARAM_TABLE` — 10 个预设参数 (param_id, value, type) |
| L570-576 | sensor_health 位表 | 16 bits: IMU/Baro/Compass/GPS/Battery/BnoReset/Acc/Compass/Color/Magnetic/Scram/ESC/Parachute/Tele/BMS/Module |
| L631-636 | **`_FAILSAFE_BITS`** — failsafe(0x06) 位表 | `f_ekf_vert`=bit0 ... `f_crash`=bit15（C# AlarmCode 倒序，参数名=枚举名小写化） |
| L582-602 | 挂载点灯映射 | `_PAYLOAD_LIGHT_MAP`: param7 → (payload_type, config_attr, label)；新增 `_PAYLOAD_LANTERN_QUERY_MAP`: param1 → 灯类查询（param7=14 共用） |
| L594-629 | **`_RESPONSE_RULES`** — 无状态响应调度表 | HEARTBEAT → id=0; GET_IDENTIFY_INFO → id=2; HEARTBEAT_DMD → id=5/8/204 |
| L636-647 | **`_STATE_RULES`** — 有状态交互调度表 | SET_MODE/CALIB_TIME/PARAM_*/NET_FILE/MISSION_VERIFY/SWARM/LIGHT_DATA/COMMAND_LONG |

### 2.5 _FakeAirplaneMessageSender — 构造与生命周期 (L649-866)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L649-813 | **`__init__`** — 160+ 行属性初始化 | `serial`, `code`, `seq`, 16 sensor 标志, 激光/nova/烟花/折叠灯/蟠桃灯/鱼灯/旧孔明灯/喇叭/降落伞/撒花器 config+state, 10 个版本字段, 18 个电压字段, 位置 cur/tar, 飞行状态机字段（含 `_flight_base_lat`/`_flight_base_lon` 表演基准位置）, param_dict (UavParamDict from CSV), **ACK 失败/静默/特定command覆写配置**, 参数队列 |
| L792-805 | __init__ 尾部 — 启动后台线程 | `self.start()` |
| L810-833 | `_cleanup()` — 取消定时器 + 停线程 + 关 socket | — |
| L838-866 | `start()` / `stop()` — daemon 线程创建/join + socket 关闭 | — |

### 2.6 _FakeAirplaneMessageSender — update_xxx 方法 (L868-1146)

| 行号 | 方法 | 说明 |
|------|------|------|
| L868-878 | `update_wind_speed(wind_speed_x, wind_speed_y)` | 风速（cm/s，两分量 int） |
| L880-888 | `update_laser(laser_config, laser_state)` | 激光（config=[4], state=int） |
| L890-898 | `update_nova(nova_config, nova_state)` | 高亮灯（config=int, state=int） |
| L900-909 | `update_firework(firework_config)` | 烟花（config=int, bit0~7=8 通道） |
| L948-967 | `update_lantern(lantern_config, lantern_state, peach_lantern_config=0, fish_lantern_config=0, kongming_lantern_config=0)` | 折叠灯/蟠桃灯/鱼灯/旧孔明灯配置 |
| L996-1002 | `update_confetti(confetti_config)` | 撒花器配置（对应查询指令 param1=1/param7=16） |
| L710-720 | `update_trumpet(trumpet_config, trumpet_state, trumpet)` | 喇叭（同折叠灯） |
| L722-733 | `update_parachute(parachute_config, parachute_state, parachute)` | 降落伞（同折叠灯） |
| L950-963 | `update_ack(fail_count=0, silence_count=0, cmd_result_enable=False, cmd_result_commands=None, cmd_result_values=None)` | ACK 响应配置（三种模式: 沉默→特定command覆写→失败注入，优先级从高到低）；per-command 独立计数 + 10s 自动重置；cmd_result 支持单值广播/一一对应 |
| L968-988 | `update_param_hash(value=None, source=0)` | param_hash 手动(source=1, 设置 `_param_hash_source=1` 阻止 PARAM_SET 覆盖)/自动(source=0) |
| L991-1027 | `update_version(**kwargs)` | 10 个版本字段批量更新 |
| L1029-1064 | `update_sensor_health(**kwargs)` | 16 个传感器状态（按名称） |
| L1081-1103 | `update_position(cur_lat, cur_lon, tar_lat, tar_lon, cur_alt=0, tar_alt=0, fix_type=6)` | 当前位置 + 目标 + GPS 定位类型 |
| L1104-1151 | `update_bat(**kwargs)` | 28 个字段批量更新：19 个电池/电压字段（voltage_battery, voltage_battery_percent, battery_time, temp_batt, battery_capability, battery_used_times, voltage_battery_cell1~6, voltage_rid_bat 等）+ **9 个 0x3B REMAINING_CAPACITY(59) 字段（v1.12：safe_fly_radius/remain_fly_time/go_home_need_time/land_need_time/go_home_need_capacity/land_need_capacity/battery_total_capaticy/battery_remain_capaticy/battry_capacity_percentage，协议原文拼写 capaticy/battry）** |
| L1282-1294 | `update_drama_state(drama_state, mission_request_ack_result=-1)` | 剧本状态（MAVLink msg_id=5 drama_state 字段）+ **0x2A MISSION_REQUEST_ACK result 覆写**（-1=AUTO 按 loaded_missions 自动计算 0/1；>=0 强制覆写，2026-09-17 新增）|
| L1166-1172 | `update_waypoint_parse(enable: bool)` | **新增** — 航点解析开关（True=bin 保存后自动生成 3D 航点图） |
| L1175-1184 | `update_waypoint_compare(enable: bool)` | **新增** — 航点对比开关（已弃用内部自动联动，仅由外部 GUI 触发） |
| L1191-1203 | `update_bin_save(enable: bool, save_dir: str\|None)` | **新增** — bin 文件保存开关+路径（默认关闭，路径默认 `drama/`），暴露给 GUI |
| L1210-1222 | `update_hover_fence(manual_enable, safe_distance=3.0)` | **新增** — 悬停测试电子围栏 SET/RESET（manual_enable=True 时用配置半径替换地面站 PARAM_SET 值） |
| L1224-1238 | `update_hover_test(manual_enable, takeoff_height=10.0, hover_duration=60)` | **新增** — 悬停测试参数配置（manual_enable=True 时使用配置值回复） |
| L1427-1480 | `update_failsafe(enable=False, f_crash=False, ..., f_ekf_vert=False)` | **新增** — failsafe(0x06) 故障位配置（17 参数=enable+16 位；未配置的故障位一律置 0，全量覆盖语义；enable=True 时随 5s 状态周期外发，默认不外发） |

### 2.7 _FakeAirplaneMessageSender — success 状态机 (L1084-1119)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L1087-1095 | `_reset_success_locked()` — success=False + 取消衰减定时器 | 持锁调用 |
| L1097-1113 | `_mark_success_locked()` — success=True + 启动 0.5s Timer | 持锁调用 |
| L1115-1119 | `_on_success_expire()` — Timer 回调：0.5s 到期后 success=False | — |

### 2.8 _FakeAirplaneMessageSender — 握手与主循环 (L1124-1311)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L1124-1145 | `_do_handshake()` — 发 id=0 → 收 id=3 → 发 id=2 → 收 id=1 | 目前被注释掉（L776） |
| L1150-1166 | `_wait_for_msg_id()` — 超时等待指定 msg_id | timeout=30s |
| L1171-1211 | **`_run()`** — 主循环: 接收 → `_dispatch_request()`; 空闲 5s 发心跳; 识别后 5s 发续航 + 状态; `enable_failsafe=True` 时同周期加发 0x06（L1595-1603 锁内构建） | — |
| L1213-1243 | `_build_responses()` — 查 `_RESPONSE_RULES` 构建响应列表（身份门闩） | — |
| L1245-1285 | **`_dispatch_request()`** — 调度入口: 1) `_STATE_RULES` 有状态处理; 2) `_RESPONSE_RULES` 无状态回显 | — |
| L1287-1311 | `_dispatch_send()` / `_judge_send_success()` — 发送 + 更新 success 状态机 | — |

### 2.9 _FakeAirplaneMessageSender — 有状态协议处理器 (L1316-1821)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L1316-1320 | `_now_ms()` — 当前 UTC 毫秒（可注入测试时钟） | `_now_ms_override` |
| L1322-1332 | `_handle_set_mode()` — 写 mode + 回 ACK(77) | — |
| L1334-1344 | `_on_mode_changed()` — 飞行中切 LD/R → 触发降落/返航 | — |
| L1346-1354 | `_handle_calib_time()` — 记录 epoch_now_ms + 回 TIME_ORIGIN(47) | — |
| L1356-1402 | `_handle_param_request_list()` — 全量参数入队 → 分批(≤8个)回 PARAM_VALUE(22) → ACK(24) | 丢队首 5 个模拟丢包 |
| L1407-1421 | `_get_param_value()` — 参数取值（MustBe → MustNotBe → _params_set 缓存 → 0） | — |
| L1423-1455 | `_handle_param_request_read()` — 遍历 16B 槽位逐个查 ParamTypes → 回 PARAM_VALUE(22) | — |
| L1457-1574 | `_handle_param_set()` — struct 解包 8×float + 128B param_id → 写入 + 回显；refresh_param_hash 前加 `_param_hash_source != 1` 守卫 | — |
| L1507-1510 | `_handle_light_data()` — 回 ACK(77) | — |
| L1513-1520 | `_parse_mission_id()` — 从文件名解析 mission_id | 静态方法 |
| L1522-1537 | `_handle_net_file_command()` — 按 OPEN/WRITE/CLOSE/VERIFY 分发 | — |
| L1539-1612 | `_net_file_open()` — 分配 fid + bytearray 缓冲区（并发多文件支持） | — |
| L1614-1632 | `_net_file_write()` — payload 拷贝到缓冲区指定位置（并发分片安全） | — |
| L1634-1662 | `_net_file_close()` — 保存 .bin + 移入 `_file_data_cache` 供 VERIFY + 登记 loaded_missions | — |
| L1664-1688 | `_net_file_verify()` — 从 `_file_data_cache` 取数据 → MD5 校验比对 GCS | **新增** |
| L1690-1714 | `DRAMA_SAVE_ROOT` — 类常量，固定保存路径 `mavlink_monitor/drama/` | **新增** |
| L1945-1987 | `_save_drama_bin(transfer)` — 保存到 bin_save_dir，保存后记录 `_last_saved_bin_path`；若 `enable_waypoint_parse` 则调模块级 `visualize_drama_3d()` | **已修改** |
| — | `_parse_waypoints_from_bin` | **[已移除]** — 剥离至 `drama_processing.py` 模块级函数 |
| — | `visualize_drama_3d` | **[已移除]** — 剥离至 `drama_processing.py` 模块级函数 |
| — | `visualize_drama_compare` | **[已移除]** — 剥离至 `drama_processing.py` 模块级函数 |
| L2147-2169 | `_handle_mission_request_verify()` — result 取值: `mission_request_ack_result>=0` 强制覆写 / -1(AUTO) 按 loaded_missions 自动计算 → ACK(42) + result==0 时清理 _file_data_cache | 覆写值由 `update_drama_state` 修改 |
| L1920-1936 | **`_handle_command_long()`** — 状态副作用 + 挂载点灯 + 兜底 ACK | 核心命令入口 |
| L1938-1963 | `_build_mount_payload_responses()` — param7=14 走灯类查询（按 param1 区分），其余 param7 走通用映射（param1==1.0） | 新增 _PAYLOAD_LANTERN_QUERY_MAP 查询分支 |
| L1622-1648 | `_apply_command_long_effects()` — ARM/DISARM/急停/切剧本/返航降落 | — |
| L1650-1679 | `_arm()` / `_disarm()` / `_flight_stop()` / `_stop_flight()` | 飞行状态原子操作 |
| L2160-2205 | **`_handle_swarm_flight_start()`** — 保存基准位置(`_flight_base_lat`/`_flight_base_lon`) + 记录时刻 + 启动飞行线程 + 回 ACK(77)；收到 0x32 后调 `_rename_last_bin_to_ip_time(play)` 将最近接收 bin 改名 | 开始表演入口 |
| L1989-1996 | `_format_play_time(play_ms)` — 静态：play(ms) → UTC 时间串 `YYYYMMDD_HHMMSS.SSS` | **新增** |
| L1998-2027 | `_rename_last_bin_to_ip_time(play_ms)` — 将最近接收 bin 重命名为 `{飞机IP}_{UTC时间}.bin`；已是该格式 / 目标已存在 / 无最近文件 则跳过 | **新增** |
| L1731-1743 | `_start_flight()` — 创建飞行 daemon 线程（防重入） | — |
| L1745-1756 | `_flight_loop()` — 周期 ~490ms 调 `_advance_flight()` | — |
| L1758-1760 | `_clamp01()` — 值裁剪到 [0,1] | 静态方法 |
| L1762-1821 | **`_advance_flight()`** — 飞行状态机单步: Idle→Takeoff→Play→Land/Return→Landed→Disarm；PLAY 中位置漂移以 `_flight_base_lat` 为基准（非 `tar_lat`），漂移后自动同步 `tar_lat=cur_lat, tar_lon=cur_lon` | 核心算法 |

### 2.10 _FakeAirplaneMessageSender — 消息构建器 (L1826-2102)

| 行号 | 方法 | 构建 msg_id | 说明 |
|------|------|-------------|------|
| L1826-1833 | `_build_id_000()` | 0 (HEARTBEAT) | autopilot + mavlink_version |
| L1835-1841 | `_build_id_002(serial, code)` | 2 (IDENTIFY) | serial + code |
| L1843-1852 | `_build_id_047(time_ms)` | 47 (TIME_ORIGIN) | UTC 毫秒 |
| L2460-2464 | `_build_id_042(result)` | 42 (MISSION_REQUEST_ACK) | result=0 ACCEPTED；result 由 `_handle_mission_request_verify` 传入（可被 `mission_request_ack_result` 覆写） |
| L1860-1874 | `_build_id_059()` | 59 (REMAINING_CAPACITY) | 续航/电池状态（1Hz 主动上报） |
| L2475-2487 | `_build_id_006()` | 6 (FAILSAFE) | **新增** — 故障保护位掩码（uint16，`failsafe_flags` 按 `_FAILSAFE_BITS` 组装；`enable_failsafe=True` 时随 5s 周期上报） |
| L1876-1905 | `_build_id_022(chunk, start_index, total)` | 22 (PARAM_VALUE) | 批量参数，每帧 ≤8 个 |
| L1907-1911 | `_build_id_024(result)` | 24 (PARAM_REQUEST_LIST_ACK) | — |
| L1913-1921 | `_build_id_063_ack(ack_data)` | 63 (NET_FILE_COMMAND) | 文件传输 ACK |
| L1923-1983 | `_build_id_005(wind_speed_x, wind_speed_y, ...)` | 5 (PACKED_STATE) | **最复杂消息**: 含位置/传感器/飞行状态/灯光/电池/风速等 40+ 字段（drama_state 字段读取 `self.drama_state`，由 `update_drama_state` 覆写）|
| L1985-2026 | `_build_id_008(nova_light_version, gimbal_version)` | 8 (EXTENDED_HEARTBEAT) | 版本信息 + param_hash + 电池电芯 |
| L2344-2360 | `_build_id_060(payload_type, payload_channel)` | 60 (MOUNT_PAYLOAD) | 挂载负载状态 (list→位掩码)；type 1-firework 2-laser 3-nova 4-FoldLantern 5-FoldLante 6-Trumpet 7-KongMingLantern 8-PeachLantern 9-FishLantern 10-Confetti |
| L2363-2398 | `_build_id_077_cmd(command, result)` | 77 (COMMAND_ACK) | **含三种 ACK 配置**（优先级: 静默 → cmd_result覆写 → 失败注入）；返回 None 表示静默 |
| L2431-2461 | `_build_id_204(laser_state, nova_state, lantern_state, trumpet_state, parachute_state)` | 204 (LOAD_ALARM) | 负载告警状态（5 字段：激光/高亮灯/折叠灯/喇叭/降落伞） |

### 2.11 _FakeAirplaneMessageSenders — 批量管理器 (L2105-2208)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L2133 | 全局计数器 | `_global_airplane_counter` |
| L2136-2140 | 定位常量 | `_POS_BASE_LAT`, `_POS_BASE_LON`, `_POS_STEP`, `_POS_LAT_OFFSET` |
| L2142-2202 | **`__init__`** — 循环创建 FakeAirplane（先全部创建 UDP）→ 循环创建 Sender（间隔 2s）→ 自动分配唯一 lat/lon | — |
| L2204-2208 | `stop()` — 批量 `sender.stop()` + `fake_plane.close()` | — |

### 2.12 `__main__` 入口 (L2211-2254)

| 行号 | 功能 |
|------|------|
| L2211-2254 | 创建 2 架飞机 → 分别更新激光/nova/版本 → 阻塞等 Ctrl+C → stop |

---

## 3. 类层次结构

```
fake_airplane.py  (2255 行)
│
├── FakeAirplane                               (L42-293)
│     └── 传输层：UDP socket + Windows NIC IP 管理
│           ├── .sock: socket
│           ├── .local_ip: str
│           ├── .ground_station_ip / .ground_station_port
│           └── send() / receive() / close()
│
├── _WindSpeedSender                           (L295-384)  [遗留]
│     └── 风速消息发送器：独立线程收 id=1 → 发 id=5
│
├── _FakeAirplaneMessageSender                 (L423-2103)  ← 主类
│     ├── 类级常量 (L451-647)
│     │     ├── _RESPONSE_RULES: dict[int, response_rule]   无状态响应表
│     │     └── _STATE_RULES: dict[int, handler_name]       有状态交互表
│     ├── 实例属性 (L649-787, ~60+ 个)
│     │     ├── 核心标识: serial, code, seq
│     │     ├── 负载状态: laser/nova/firework/lantern/peach_lantern/fish_lantern/kongming_lantern/trumpet/parachute/confetti (config+state, 仅 config 字段，state 由 _build_id_* 统一使用)
│     │     ├── 传感器: 16 个 _sensor_xxx (0=正常, 1=异常)
│     │     ├── 版本信息: 10 个 version 字段
│     │     ├── 位置: cur_lat/lon, tar_lat/lon, cur_alt, tar_alt, _flight_base_lat/lon（表演基准）
│     │     ├── 飞行状态机: mode, armed, fly_state, play_state, mission_id
│     │     ├── 参数系统: param_dict (UavParamDict), _param_queue, _params_set
│     │     ├── ACK 配置: _ack_fail/silence_count, _ack_cmd_result_enabled/map + 各独立计数器
│     │     └── 线程: thread, _flight_thread
│     ├── 公共 API: 19 个 update_xxx() 方法 (L850-1315)
│     ├── 协议处理: 10 个 _handle_xxx() 方法 (L1322-1729)
│     └── 消息构建: 13 个 _build_id_xxx() 方法 (L1826-2102)
│
├── _FakeAirplaneMessageSenders                (L2105-2208)  ← 批量管理器
│     ├── .fake_airplane_senders: list[_FakeAirplaneMessageSender]
│     ├── .fake_airplanes: list[FakeAirplane]
│     └── _global_airplane_counter (class-level)
│
└── 模块级函数
      └── _send_wind_speed_async()                (L387-414)

外部依赖（来自同一项目）:
  src.Protocol.mavlink.parse_mavlink.MAVLink_message  ← 消息构造/解析
  src.Protocol.mavlink.param_dict.UavParamDict         ← 参数 CSV 管理
  utils.logger.LogManager / logger                      ← 日志
```

---

## 4. 核心类详解

### 4.1 FakeAirplane (L42-293)

**职责**: 传输层，管理 Windows 网卡辅助 IP 和 UDP 套接字。不包含任何 MAVLink 协议逻辑。

**初始化流程**:
1. 保存参数到实例属性 (`target_ip`, `ground_station_ip`, `local_port`, `recv_timeout`, `mavlink_version`)
2. `_setup_network()` — PowerShell `New-NetIPAddress` 添加辅助 IP
3. `_udp_setup()` — `socket(AF_INET, SOCK_DGRAM)` → `setsockopt(SO_BROADCAST)` → `bind()`（最多重试 10 次）
4. `time.sleep(0.5)` — 等待网络就绪

**IP 管理** (`_setup_network`, L71-94):
- 先 `_ip_exists_locally()` 检测目标 IP 是否已存在
- 不存在则执行 `powershell New-NetIPAddress -InterfaceAlias 'WLAN 6' -IPAddress '...' -PrefixLength 24`
- 返回码非 0 记录错误日志

**关键属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `target_ip` / `local_ip` | `str` | 目标/本地 IP |
| `ground_station_ip` / `ground_station_port` | `str` / `int` | 地面站地址 |
| `local_port` | `int` | 本地 UDP 端口 |
| `sock` | `socket \| None` | UDP 套接字 |
| `udp_connected` | `bool` | UDP 是否已就绪 |
| `mavlink_version` | `str` | `'39'` 或 `'44'` |
| `recv_timeout` | `float` | recvfrom 超时秒数 |

**线程模型**: 无自己的线程。send/receive 同步调用。

---

### 4.2 _FakeAirplaneMessageSender (L423-2103)

**职责**: 单架假飞机的完整 MAVLink 协议仿真器。一个实例对应一架 FakeAirplane + 一个后台线程（主循环）+ 一个飞行推进线程（可选）。

**初始化 (L649-787, ~140 行)**:

```python
def __init__(self, log_manager, fake_plane, addr,
             serial=_DEFAULT_SERIAL, code=_DEFAULT_CODE,
             nova_light_version=b"1234", gimbal_version=b"",
             seq=_DEFAULT_SEQ):
```

核心步骤:
1. 保存核心参数 → 初始化所有负载/传感器/版本/位置属性为默认值
2. 初始化 ACK 配置（`_ack_fail_count/silence_count` + `_ack_cmd_result_enabled/map` + 各独立计数器/时间戳字典）
3. 初始化飞行状态机字段（`mode=G`, `armed=0`, `fly_state=DISARM`, 等）
4. **参数系统**: `serial_to_model(serial)` 反查机型 → `UavParamDict(model)` → `load_csv(csv_path)`；失败则回退到 `_DEFAULT_PARAM_TABLE`
5. 末尾调用 `self.start()` 启动后台线程

**网络连接** (`send`, `receive` — 通过 `self.fake_plane`):
- `send(message, addr)`: 调用下层 `FakeAirplane.send()` (UDP `sendto`)
- `receive(bufsize)`: 调用下层 `FakeAirplane.receive()` (UDP `recvfrom` → `MAVLink_message` 解析)

**线程模型**:
```
self.thread (daemon)                  _flight_thread (daemon, 可选)
    │                                      │
    ├── _run()  主循环                     ├── _flight_loop()  490ms 周期
    │   ├── receive() 阻塞                 │   └── _advance_flight()
    │   ├── _dispatch_request() 调度        │       逐帧更新 cur_alt/cur_lat/play_state
    │   └── 空闲心跳 / 5s 主动上报         │
    └── running=False 退出                 └── _flight_running=False 退出
```

**主循环 `_run()`** (L1246-1286):
```
1. 启动后立即发送首次心跳 id=0
2. while self.running:
   a. receive() → 收到消息则 _dispatch_request(received)
   b. 身份识别未完成 → 每 5s 主动发送心跳 id=0
   c. 身份识别已完成 → 每 5s 主动上报:
      - id=59 (剩余续航)
      - id=5  (packed_state 表演进度)
```

**消息调度 `_dispatch_request()`** (L1320-1360):
```
收到消息 msg_id=
  ├── _STATE_RULES 命中 → handler(received) → [(msg, label), ...] → _dispatch_send()
  │     SET_MODE(11)        → _handle_set_mode
  │     CALIB_TIME(46)      → _handle_calib_time
  │     PARAM_REQUEST_LIST  → _handle_param_request_list
  │     PARAM_REQUEST_READ  → _handle_param_request_read
  │     PARAM_SET           → _handle_param_set
  │     NET_FILE_COMMAND    → _handle_net_file_command
  │     MISSION_VERIFY      → _handle_mission_request_verify
  │     SWARM_FLIGHT_START  → _handle_swarm_flight_start
  │     LIGHT_DATA          → _handle_light_data
  │     COMMAND_LONG        → _handle_command_long
  │
  └── _RESPONSE_RULES 命中 → _build_responses() → [rules_id, ...]
        HEARTBEAT(0)        → build_id_000
        GET_IDENTIFY_INFO   → build_id_002
        HEARTBEAT_DMD(1)    → build_id_005 + (extend==1 → build_id_008) + build_id_204
```

**飞行状态机 `_advance_flight()`** (L1762-1821):

```
                    SWARM_FLIGHT_START
                          │
  FLY_DISARM ──────→ FLY_LANDED ──────→ FLY_GUIDE_IDLE
                          │                  │
                          │             now >= takeoff_time_ms
                          │                  │
                          ▼                  ▼
                    FLY_LANDED         FLY_GUIDE_TAKEOFF     ← PLAY_TAKEOFF
  (落地后2s自动上锁)    │                  │
      │                 │             now >= play_time_ms
      ▼                 │                  │
  FLY_DISARM            │                  ▼
  PLAY_DISARMED         │            FLY_GUIDE_PLAY          ← PLAY_PLAYING
                          │             │
                          │         play_duration_ms > 0 到期
                          │         或 地面站切 LD/R 模式
                          │             │
                          │             ▼
                          │    FLY_LAND / FLY_RETURN         ← PLAY_LANDING
                          │             │
                          │        land_duration_ms 后
                          │             │
                          └─────────────┘
```

---

### 4.3 _FakeAirplaneMessageSenders (L2105-2208)

**职责**: 批量创建并管理多架假飞机。`SimulationPanel` 的 `_on_add_clicked()` 通过这个类"一次添加多架飞机"。

**初始化流程** (L2142-2202):
```
1. 校验: count ≥ 1, IP 末段 + count ≤ 255
2. 循环 1 (L2157-2160): 先创建所有 FakeAirplane (UDP socket)
3. 循环 2 (L2162-2174): 逐一创建 _FakeAirplaneMessageSender
   - serial = start_serial + "{code:03d}"
   - addr = (ground_station_ip, ground_station_port)
   - 每架间隔 2s (time.sleep(2))
4. 循环 3 (L2177-2185): 自动分配经纬度
   - lat = _POS_BASE_LAT + _POS_LAT_OFFSET  (226868764)
   - lon = _POS_BASE_LON + global_idx * _POS_STEP  (递增 0.00001°)
5. 异常处理: 部分失败时清理已创建的 sender + FakeAirplane
```

**关键属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `fake_airplane_senders` | `list[_FakeAirplaneMessageSender]` | 暴露给 `SimulationPanel._senders` |
| `fake_airplanes` | `list[FakeAirplane]` | 暴露给 `SimulationPanel._transports` |
| `_global_airplane_counter` | `int` (class) | 跨多次"添加"递增，保证经度不重复 |
| `_POS_BASE_LAT` | `int` (class) | 226868664 |
| `_POS_BASE_LON` | `int` (class) | 1140224548 |
| `_POS_STEP` | `int` (class) | 100 (= 0.00001°) |

---

### 4.4 _WindSpeedSender (L295-384) [遗留]

**职责**: 遗留的独立风速消息发送器。使用独立的 UDP 接收循环（不从 `_FakeAirplaneMessageSender` 线程共享 socket），收 id=1 → 发 id=5。

**当前状态**: 实际上 `_FakeAirplaneMessageSender` 在 `_build_id_005()` 中已内置风速字段，且主循环中 `HEARTBEAT_DMD(1)` 的 `_RESPONSE_RULES` 也会触发 id=5 构建。`_WindSpeedSender` 是遗留代码，目前未被 `_FakeAirplaneMessageSenders` 批量管理器使用。

---

## 5. update_xxx 方法清单

> 所有方法均位于 `_FakeAirplaneMessageSender` 类（L423-2103），通过 `with self._lock` 保证线程安全，调用后重置 `self.success = False`（`_reset_success_locked()`）。

| # | 方法签名 | 行号 | 参数类型 | 说明 |
|---|----------|------|----------|------|
| 1 | `update_wind_speed(wind_speed_x, wind_speed_y)` | L850 | `int, int` | 风速 x/y 分量 (cm/s) |
| 2 | `update_laser(laser_config, laser_state)` | L862 | `list[int], int` | 激光配置 (4 通道) + 状态 |
| 3 | `update_nova(nova_config, nova_state)` | L872 | `int, int` | 高亮灯配置 + 状态 |
| 4 | `update_firework(firework_config)` | L882 | `int` | 烟花 8 通道位掩码 (bit0~7) |
| 5 | `update_lantern(lantern_config, lantern_state, peach_lantern_config=0, fish_lantern_config=0, kongming_lantern_config=0)` | L948 | `int, int, int, int, int` | 折叠灯/蟠桃灯/鱼灯/旧孔明灯配置 |
| 5b | `update_confetti(confetti_config)` | L996 | `int` | 撒花器配置（对应查询指令 param1=1/param7=16） |
| 6 | `update_trumpet(trumpet_config, trumpet_state, trumpet)` | L710 | `int, int, int` | 喇叭配置/状态/负载标志 |
| 7 | `update_parachute(parachute_config, parachute_state, parachute)` | L722 | `int, int, int` | 降落伞配置/状态/负载标志 |
| 9 | `update_ack(fail_count=0, silence_count=0, cmd_result_enable=False, cmd_result_commands=None, cmd_result_values=None)` | L1065 | `int, int, bool, list[int], list[int]` | **ACK 响应配置三模式**（优先级从高到低）:<br>① silence_count: 前 N 次静默不回复<br>② cmd_result_*: 特定 command 强制覆写 result（单值广播/一一对应）<br>③ fail_count: 前 N 次返回 result=4 (FAILED)<br>各 command 独立计数，10s 未收到自动重置 |
| 10 | `update_param_hash(value=None, source=0)` | L1041 | `int, int` | param_hash 手动(source=1)/自动(source=0)；value 通过 integrated_gui.py known_param_types 强制为 int |
| 11 | `update_version(**kwargs)` | L1064 | `**kwargs` | 10 个版本字段批量更新 |
| 12 | `update_sensor_health(**kwargs)` | L1102 | `**kwargs` | 16 个传感器按名称更新 |
| 13 | `update_position(cur_lat, cur_lon, tar_lat, tar_lon, cur_alt=0, tar_alt=0, fix_type=6)` | L1174 | `uint32, uint32, uint32, uint32, uint32, uint32, uint8` | 当前位置 + 目标 + GPS 定位类型（MAVLink msg_id=5） |
| 14 | `update_bat(**kwargs)` | L1195 | `**kwargs` | 19 个电池/电压字段批量更新 |
| 15 | `update_waypoint_parse(enable: bool)` | L1257 | `bool` | **新增** — 航点解析开关 |
| 16 | `update_waypoint_compare(enable: bool)` | L1266 | `bool` | **新增** — 航点对比开关 |
| 17 | `update_bin_save(enable: bool, save_dir: str\|None)` | L1282 | `bool, str` | **新增** — bin 保存开关+路径 |
| 18 | `update_hover_fence(manual_enable, safe_distance=3.0)` | L1301 | `bool, float` | **新增** — 悬停测试电子围栏 SET/RESET；manual_enable=True 时在 `_handle_param_set` / `_handle_param_request_read` 中替换 FS_FENCE_RDS 回显值 |
| 19 | `update_hover_test(manual_enable, takeoff_height=10.0, hover_duration=60)` | L1315 | `bool, float, int` | **新增** — 悬停测试参数配置 |
| 20 | `update_drama_state(drama_state, mission_request_ack_result=-1)` | L1282 | `int, int` | 剧本状态（写入 0x05 消息的 `drama_state` 字段；替换原硬编码 0）+ **0x2A ACK result 覆写**（-1=AUTO 自动计算 0/1，>=0 强制覆写；`mission_request_ack_result` 经 `_config.py` known_param_types 注册为 int → GUI QSpinBox，2026-09-17 新增）|
| 21 | `update_failsafe(enable=False, f_crash=False, f_radio=False, f_battery=False, f_fence_alt=False, f_fence_circle=False, f_waypoint=False, f_too_far=False, f_static_dist=False, f_vibrate=False, f_drama_fail=False, f_parachute=False, f_sensor_fail=False, f_fence_2=False, f_ekf_stab=False, f_ekf_horz=False, f_ekf_vert=False)` | L1427 | `bool × 17` | **新增** — failsafe(0x06) 故障位配置（F_EKF_VERT=bit0 ... F_CRASH=bit15，对齐 C# AlarmCode Failsafe 掩码）；未配置的故障位一律置 0（全量覆盖语义）；enable=True 时 `_run` 5s 周期加发 0x06，默认不外发 |

### update_bat 支持的 28 个关键字 (L1104-1146)

| 关键字 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `voltage_battery` | `int` | 电池电压 (mV) | `34000` |
| `voltage_battery_percent` | `int` | 电池电量百分比 | `95` |
| `voltage_battery_diff` | `int` | 电池电压差 (mV) | `0` |
| `voltage_battery_history_diff` | `int` | 历史电池电压差 (mV) | `0` |
| `bat_serial_prefix` | `bytes` | 电池序列号前缀 | `b'V3F230324-'` |
| `bat_serial_suffix` | `bytes` | 电池序列号后缀 | `b'3355'` |
| `bat_serial_need_reset` | `int` | 电池序列号需重置标志 | `0` |
| `charge_state` | `int` | 充电状态 | `0` |
| `battery_time` | `int` | 电池使用时间 | `78` |
| `temp_batt` | `int` | 电池温度 | `0` |
| `battery_capability` | `int` | 电池容量 | `20` |
| `battery_used_times` | `int` | 电池使用次数 | `12` |
| `voltage_battery_cell1` | `int` | 电芯1电压 (mV) | `3500` |
| `voltage_battery_cell2` | `int` | 电芯2电压 (mV) | `3500` |
| `voltage_battery_cell3` | `int` | 电芯3电压 (mV) | `3500` |
| `voltage_battery_cell4` | `int` | 电芯4电压 (mV) | `3500` |
| `voltage_battery_cell5` | `int` | 电芯5电压 (mV) | `3500` |
| `voltage_battery_cell6` | `int` | 电芯6电压 (mV) | `3500` |
| `voltage_rid_bat` | `int` | RID 电池电压 (mV) | `0` |
| `safe_fly_radius` | `float` | 0x3B 安全飞行半径 (m) | `500.0` |
| `remain_fly_time` | `int` | 0x3B 剩余飞行时间 (s) | `1200` |
| `go_home_need_time` | `int` | 0x3B 返航所需时间 (s) | `60` |
| `land_need_time` | `int` | 0x3B 降落所需时间 (s) | `30` |
| `go_home_need_capacity` | `int` | 0x3B 返航所需电量 (mAh) | `500` |
| `land_need_capacity` | `int` | 0x3B 降落所需电量 (mAh) | `300` |
| `battery_total_capaticy` | `int` | 0x3B 电池总容量 (mAh，协议原文拼写) | `22000` |
| `battery_remain_capaticy` | `int` | 0x3B 电池剩余容量 (mAh，协议原文拼写) | `20000` |
| `battry_capacity_percentage` | `int` | 0x3B 电池容量百分比 (协议原文拼写) | `90` |

### update_version 支持的 10 个关键字 (L1000-1004)

| 关键字 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `flight_controller_version` | `bytes` (8B) | 飞控版本 | `b'n3.j.196'` |
| `companion_version` | `bytes` (8B) | 伴侣计算机版本 | `b'V3.631'` |
| `battery_version` | `bytes` (8B) | 电池版本 | `b''` |
| `gps_version` | `bytes` (8B) | GPS 版本 | `b'UM16982'` |
| `servo_ver` | `int` | 舵机版本 | `0` |
| `tele_version` | `bytes` (4B) | 遥测模块版本 | `b'E013'` |
| `bms_version` | `bytes` (4B) | BMS 版本 | `b''` |
| `rid_version` | `bytes` (8B) | RID 版本 | `b''` |
| `gimbal_version` | `bytes` (4B) | 云台版本 | `b''` |
| `nova_light_version` | `bytes` (4B) | 高亮灯版本 | 来自构造参数 |

### update_sensor_health 支持的 16 个关键字 (L570-576)

| 关键字 | Bit | 说明 | 取值逻辑 |
|--------|-----|------|----------|
| `imu` | 0 | IMU | 0=正常, 1=异常 |
| `baro` | 1 | 气压计 | 0=正常, 1=异常 |
| `compass` | 2 | 罗盘/BNO | 0=正常, 1=异常 |
| `gps` | 3 | GPS/UWB | 0=正常, 1=异常 |
| `battery` | 4 | 电池 | 0=正常, 1=异常 |
| `bno_reset` | 5 | BNO 复位 | 0=正常, 1=异常 |
| `acc_calibrated` | 6 | 加速度计校准 | 0=正常, 1=异常 |
| `compass_calibrated` | 7 | 罗盘校准 | 0=正常, 1=异常 |
| `color_calibrated` | 8 | 颜色校准 | 0=正常, 1=异常 |
| `magnetic_calibrated` | 9 | 磁力计校准 | 0=正常, 1=异常 |
| `scram` | 10 | SCRAM | 0=正常, 1=异常 |
| `esc` | 11 | ESC | 0=正常, 1=异常 |
| `parachute` | 12 | 降落伞 | **取反**: 1=正常, 0=异常 |
| `tele` | 13 | 遥测 | **取反**: 1=正常, 0=异常 |
| `bms` | 14 | BMS | **取反**: 1=正常, 0=异常 |
| `module` | 15 | 模块 | **取反**: 1=正常, 0=异常 |

---

## 6. 数据流

### 6.1 消息接收 → 响应发送全链路

```
地面站 (172.16.200.1:14550)
  │
  │  UDP sendto → 172.16.3.168:14551
  ▼
FakeAirplane.sock.recvfrom()
  │
  ├── DEBUG: 打印 hex_full / hex_spaced / ascii
  │
  └── MAVLink_message(hex_data=data.hex())
        │
        ▼
_FakeAirplaneMessageSender._run()
  │
  ├── _dispatch_request(received)
  │     │
  │     ├── _STATE_RULES[msg_id] → handler(received) → [(msg, label), ...]
  │     │     如 _handle_set_mode → _build_id_077_cmd → send()
  │     │
  │     └── _build_responses(received) → [(msg, label), ...]
  │           查 _RESPONSE_RULES[msg_id].rules[]
  │           对每个 rule: build(**state_attrs) → 叠加 self 当前状态
  │           send()
  │
  └── 空闲/周期性主动发送:
        - 识别前: 5s 发 id=0 (心跳)
        - 识别后: 5s 发 id=59 (续航) + id=5 (状态)
        - _flight_loop: 490ms 推进飞行状态机 (更新位置/高度)
```

### 6.2 身份识别门闩

```
飞机启动
  │
  ├── self._identified = False
  │
  ├── _run() 发送首次 id=0 (心跳)
  │
  ├── 收到 GET_IDENTIFY_INFO(3)
  │     → _build_responses() 检测到 msg_id==3
  │     → 构建 id=2 (serial + code)
  │     → self._identified = True  ← 门闩打开
  │
  └── 门闩关闭期间:
        - 仅放行 HEARTBEAT(0) + GET_IDENTIFY_INFO(3)
        - 其余消息静默屏蔽 (L1225-1228)
```

### 6.3 开始表演全链路

```
地面站下发 开始表演
  │
  ├── (可选) NET_FILE_COMMAND(63) OPEN→WRITE(并发分片)→CLOSE(保存.bin)→VERIFY(MD5校验)
  │     → loaded_missions.add(missionId) + received_dramas/*.bin
  ├── (可选) CALIB_TIME(46) → epoch_now_ms 基准
  ├── (可选) MISSION_REQUEST_VERIFY(41) → result: mission_request_ack_result>=0 覆写
  │     / -1(AUTO) 按 loaded_missions 自动计算(0/1) → ACK(42)
  │
  └── SWARM_FLIGHT_START(50)
        │
        ├── 校验: fly_state ∈ {DISARM, LANDED, GUIDE_IDLE}
        │   ├── OK → result=0, 登记 takeoff/play/mission_id/ascend/descend,
        │   │        保存基准位置 _flight_base_lat/lon = cur_lat/lon
        │   └── 拒绝 → result=4 (MAV_RESULT_FAILED)
        │
        ├── _start_flight() → 创建 _flight_thread
        │     │
        │     └── _flight_loop() 周期 ~490ms:
        │           │
        │           ├── GUIDE_IDLE: now >= takeoff_time_ms → TAKEOFF
        │           ├── TAKEOFF:   线性爬升 cur_alt = height * frac
        │           │              now >= play_time_ms → PLAY
        │           ├── PLAY:      位置微动 (cur_lat = _flight_base_lat + 1000 * frac)
        │           │              自动同步 tar_lat=cur_lat, tar_lon=cur_lon
        │           │              play_duration_ms>0 到期 → LAND/RETURN
        │           └── LAND/RETURN: 线性下降 cur_alt = height * (1-frac)
        │                           落地 → LANDED → +2s → DISARM
        │
        └── 回 ACK(77, command=50, result=0)
```

### 6.4 self.success 衰减状态机

```
update_xxx() 调用
  → _reset_success_locked()
    → success = False
    → 取消 success_timer

    发送消息 → _judge_send_success()
      ├── 失败 → _reset_success_locked()         (success 立即 False)
      └── 成功 → _mark_success_locked()
                  → success = True
                  → 启动 Timer(_SUCCESS_HOLD_SECONDS=0.5s)
                  → 到期 → _on_success_expire()
                          → success = False
                          → success_timer = None
```

**设计意图**: `success=True` 表示"当前状态确实被外发过一次"，维持 0.5s 供 GUI 轮询检测。若 0.5s 内又调用 `update_xxx`，旧 Timer 被取消并重启新 Timer。

---

## 7. 与 integrated_gui.py 的交互

> 本节说明 `integrated_gui.py` (CODE_PLAN.md) 如何通过 AST 反射操作本模块。

### 7.1 AST 静态解析

`integrated_gui.py` 的 `SimulationPanel.__init__()` (CODE_PLAN.md L1224-1273) 调用以下方法解析本文件:

```python
# CODE_PLAN.md L1251-1254
self._src_info = _parse_source(config.source_file, ...)   # AST 解析 → SourceInfo
self._update_methods = _discover_update_methods(config.sender_cls, ...)  # inspect 扫描 update_xxx
self._add_params = _discover_add_params(config.mgr_cls)   # inspect.signature 扫描 __init__ 参数
```

**`_parse_source()` 对本文件的提取**:

| 提取目标 | 本文件对应位置 | 提取内容 |
|----------|---------------|----------|
| `module_constants` | L17-40 | `fake_airplane_ip="172.16.3.168"`, `NETCARD_INTERFACE="WLAN 6"`, `SYS_ID_UAV=1`, `COMP_ID_GCS=39` |
| `init_attrs` (sender_cls) | L649-787 | `serial: str`, `code: str`, `seq: int`, `nova_light_version: bytes`, `gimbal_version: bytes` |
| `init_defaults` (mgr_cls) | L2142 | `mavlink_version`, `count`, `start_ip`, `start_serial`, `start_code`, `nova_light_version`, `log_manager`, `gimbal_version` |

**`_discover_update_methods()` 对本文件的提取**:

从 `_FakeAirplaneMessageSender` 类上发现 12 个 `update_xxx` 方法（见 §5），通过 `inspect.signature` 解析参数签名，通过 `docstring` 解析参数描述（CODE_PLAN.md L510-554）。

**`_discover_add_params()` 对本文件的提取**:

从 `_FakeAirplaneMessageSenders.__init__` (L2142) 解析参数签名:
- `mavlink_version: str`
- `count: int`
- `start_ip: str`
- `start_serial: str`
- `start_code: str/int`
- `nova_light_version: bytes`
- `gimbal_version: bytes`

### 7.2 SimConfig 映射

`_build_sim_configs()` (CODE_PLAN.md L1040-1188) 中 `"airplane"` 配置:

| SimConfig 字段 | 映射值 | 来源 |
|---------------|--------|------|
| `key` | `"airplane"` | — |
| `label` | `"假飞机"` | — |
| `source_file` | 本文件路径 | — |
| `sender_cls` | `_FakeAirplaneMessageSender` | L423 |
| `mgr_cls` | `_FakeAirplaneMessageSenders` | L2105 |
| `transport_cls` | `FakeAirplane` | L42 |
| `mgr_senders_attr` | `"fake_airplane_senders"` | L2145 |
| `mgr_transports_attr` | `"fake_airplanes"` | L2146 |
| `aid_prefix` | `"FA_"` | — |
| `param_choices` | `AIRPLANE_MODEL_SERIALS` | L31-40 (8 种机型) |
| `known_param_types` | 提供类型提示 | 如 `nova_light_version: bytes` |

### 7.3 GUI 操作 → 本模块调用链

```
SimulationPanel._on_add_clicked()          (CODE_PLAN.md L1668)
  → _FakeAirplaneMessageSenders(mavlink_version, count, start_ip,
                                start_serial, start_code,
                                nova_light_version, log_manager)
       ├── 循环创建 FakeAirplane (UDP socket)
       ├── 循环创建 _FakeAirplaneMessageSender (协议线程)
       └── 自动分配经纬度

SimulationPanel._on_apply_clicked()        (CODE_PLAN.md L1811)
  → target_sender.update_xxx(**kwargs)     ← 调用本模块 update 方法

SimulationPanel._on_remove_clicked()       (CODE_PLAN.md L1705)
  → sender.stop()                          ← 停线程 + 关 socket
  → transport.close()

SimulationPanel._on_basic_apply_clicked()  (CODE_PLAN.md L1649)
  → importlib.import_module("fake_airplane")
  → setattr(module, "fake_airplane_ip", new_value)
```

### 7.4 Socket 拦截与消息注入

`SimulationPanel.set_message_injector()` 创建的 `_SocketInterceptor` (CODE_PLAN.md L1194) 包装 `FakeAirplane.sock`，在 `recvfrom` 时回调闭包 → `FullUdpMonitorPanel.inject_raw_message()`，将假飞机收到的地面站消息注入到 UDP 监控引擎。详见 [CODE_PLAN.md §5.1](./CODE_PLAN.md#51-消息注入链路假节点--udp-监控)。

---

## 8. 修改指南

> **核心原则**: 修改代码后，在本文档对应 section 更新行号和描述。

### 场景 1: 新增一个 MAVLink 消息的响应

1. 在 `_FakeAirplaneMessageSender` 中新增 `_build_id_NNN()` 构建方法（参考 L1826-2102 现有构建器）
2. 如果消息是"无状态回显"，在 `_RESPONSE_RULES` (L594-629) 新增规则条目: `{msg_id: {'delay': None, 'rules': [{'build': '_build_id_NNN', 'label': '...', 'state': {...}}]}}`
3. 如果消息是"有状态交互"，在 `_STATE_RULES` (L636-647) 新增条目 → 新增 `_handle_xxx()` 处理器
4. 更新 §2.8/§2.9/§2.10 行号

### 场景 2: 新增一个 update 方法（如 update_camera / update_drama_state）

1. 在 `_FakeAirplaneMessageSender.__init__` (L649-887) 中新增实例属性并初始化默认值
2. 在 `_FakeAirplaneMessageSender` 中新增方法，遵循现有模式 (`with self._lock` + `_reset_success_locked()`)
3. 添加 docstring（包含参数类型描述），`_discover_update_methods()` 会自动发现
4. 如果该字段对应某个 `_build_id_NNN` 中的硬编码值，把硬编码替换为 `self.<field>`
5. 在 `_config.py` (L50-161) 的 `known_param_types` 中注册参数类型（如 `"drama_state": "int"`、`"mission_request_ack_result": "int"`）
6. 更新 §2.6（分段索引）、§4.2（实例属性表）、§5（update_xxx 方法清单）

### 场景 3: 添加新机型

1. 在 `AIRPLANE_MODEL_SERIALS` (L31-40) 添加机型→序列号映射
2. 确保 `_PARAM_CSV_BASE` 下有对应的 `{Model}_ParamList.csv` 文件
3. 确保 `serial_to_model()` 和 `MODEL_TO_CSV` (来自 `param_dict` 模块) 能正确映射新机型
4. 更新 §2.1

### 场景 4: 修改飞行状态机

1. 定位 `_advance_flight()` (L1762-1821) — 状态转移核心
2. `FlyState` 枚举在 (L499-505)，`PlayState` 枚举在 (L508-515)
3. 飞行中切模式逻辑在 `_on_mode_changed()` (L1334-1344)
4. 如果有 影响 `_build_id_005()` 的字段（如 `play_state`, `fly_state`, `mode`），需同步修改 (L1923-1983)
5. 更新 §4.2 飞行状态机图和 §6.3

### 场景 5: 修改参数系统行为

1. CSV 加载: `__init__` L756-769（`UavParamDict.load_csv()`）
2. PARAM_REQUEST_LIST 分批回传: `_handle_param_request_list()` (L1356-1402)，丢包逻辑在 L1372
3. PARAM_SET 写参数: `_handle_param_set()` (L1526-1574)，对齐 C# struct 格式；**手动 hash 守卫**：`_param_hash_source==1` 时跳过 `refresh_param_hash()`
4. 参数取值逻辑: `_get_param_value()` (L1407-1421)
5. 更新 §2.9

### 场景 6: 排查假飞机消息未出现在监控中的问题

1. 检查 `FakeAirplane._udp_setup()` 是否成功 bind (L190-215)：IP 可能未生效
2. 检查 `_FakeAirplaneMessageSender._run()` 线程是否运行：`self.running` 标志
3. 检查地面站消息是否到达：`receive()` 中的 DEBUG 打印 (L277-280) 会输出 hex/ascii
4. 检查协议规则是否匹配：`_dispatch_request()` 中 `_STATE_RULES` / `_RESPONSE_RULES` 是否包含对应 msg_id
5. 检查身份识别门闩：`_identified` 为 False 时会屏蔽非心跳/身份消息 (L1225-1228)
6. 参考 §6.1 完整消息链路

### 场景 7: 集成到 integrated_gui.py 时新增 SimConfig 字段

1. 如需 GUI 感知新的配置项，在 `_build_sim_configs()` (CODE_PLAN.md L1040-1188) 的 `"airplane"` 配置中新增 `known_param_types` / `param_choices` / `param_defaults` 条目
2. 如需 GUI 新增"可编辑模块常量"，确保该常量在本文件模块级定义（如 L17-40），`_parse_source()` 会自动扫描
3. 更新本文档 §7.1/§7.2

---

> **更新记录**:
> - 2026-09-10: **新增 failsafe(0x06) 消息支持**：①类常量 `_FAILSAFE_BITS`（L631，f_ekf_vert=bit0 ... f_crash=bit15，C# AlarmCode 倒序，参数名=枚举名小写化避免与 battery/parachute 等现有 int 参数冲突）；②`__init__` 新增 `enable_failsafe=False` + `failsafe_flags`（16 位全 0，**默认不外发**）；③新增 `update_failsafe(enable, f_crash, ..., f_ekf_vert)`（L1427，17 参数全量覆盖语义——未配置的故障位一律置 0，持锁 + `_reset_success_locked`）；④新增 `_build_id_006()`（L2475，uint16 位掩码组装）；⑤`_run` 5s 周期块加门控发送（L1595-1603，`enable_failsafe=True` 时随 id=59/5 一起外发）。GUI：`_config.py` airplane `known_param_types` 注册 enable+16 个 `f_*` 为 bool（True/False 下拉），反射零 GUI 逻辑改动。新增测试 `test_failsafe_0x06.py` 6 用例 + 验证脚本 `_gui_verify_failsafe_0x06.py` 21 断言（GUI 实操/真实线程端到端 mask=0x2000/enable=False 恢复/truthy 边界），全套 421 测试通过
> - 2026-09-08: v1.12 — **update_bat 扩展 0x3B REMAINING_CAPACITY(59) 全部 9 个字段**：`_build_id_059` 原 9 个硬编码值（safe_fly_radius=500.0/remain_fly_time=1200/go_home_need_time=60/land_need_time=30/go_home_need_capacity=500/land_need_capacity=300/battery_total_capaticy=22000/battery_remain_capaticy=20000/battry_capacity_percentage=90）改为 `__init__` 实例属性（默认值不变，字段名保持协议原文拼写 capaticy/battry）并从实例取值构建；`update_bat` docstring「支持的关键字」+`_VALID_BAT_KEYS` 白名单由 19 扩至 28 字段；GUI `_config.py` airplane `known_param_types` 注册 9 个新字段类型（safe_fly_radius=float→QDoubleSpinBox，其余 8 个 int→QSpinBox，反射零 GUI 逻辑改动）。范围仅独立假飞机（巢内 `_NestAirplane._build_id_059` 仍硬编码，未在本需求范围）。新增测试 `test_airplane_bat_059.py` 6 用例（9 字段更新/消息反映/__init__ 默认值源码比对/白名单防御/known_param_types/docstring 反射发现）+ GUI 验证脚本 `_gui_verify_bat_059.py` 10 断言（真实控件生成与类型/真实点击应用 28 参数全量提交/零值与极大值边界/新旧字段共存/0x3B 立即反映），全套 415 测试通过
> - 2026-08-26: **新增 update_drama_state(drama_state)**：`_FakeAirplaneMessageSender.__init__` 新增 `self.drama_state = 0`；新增方法（遵循 `with self._lock` + `_reset_success_locked()` 模式，参考 `update_position`）；`_build_id_005` 的 `'drama_state': 0` 替换为 `'drama_state': self.drama_state`（实现 0x05 中 drama_state 字段动态可写）；`_config.py` airplane `known_param_types` 注册 `"drama_state": "int"`；新增 `test_drama_state_update.py`（5 个 TC：写入、success 重置、默认值、_build_id_005 字段生效、线程安全）
> - 2026-08-24: **0x32 后自动重命名 bin**：`_save_drama_bin` 保存后记录 `_last_saved_bin_path`（接收时仍用原命名 `drama_merge_{id}_{timestamp}.bin`）；收到 SWARM_FLIGHT_START(0x32) 时 `_handle_swarm_flight_start` 调新增 `_rename_last_bin_to_ip_time(play)`，将最近一次接收的 bin 重命名为 `{飞机IP}_YYYYMMDD_HHMMSS.SSS.bin`（时间来自 play 字段，UTC ms，静态方法 `_format_play_time` 换算）；仅处理最近一次接收的文件（不搜索旧文件），已是该格式 / 目标已存在 / 无最近文件 则跳过；新增 `test_fake_airplane_rename.py`（5 个测试用例）
> - 2026-08-11: **修复表演后 lat 变为 0**：`_handle_swarm_flight_start` 新增保存 `_flight_base_lat`/`_flight_base_lon`（表演开始时的基准位置）；`_advance_flight` PLAY 状态位置漂移改用 `_flight_base_lat` 为基准（原用 `tar_lat`，会被 GUI 误设为 0 导致 lat 跳到 0）；`__init__` 新增对应属性初始化；新增 `test_flight_base_lat_fix.py`（5 个测试用例）
> - 2026-08-11: **优化 1+2**：`_advance_flight` PLAY 中自动同步 `tar_lat=cur_lat, tar_lon=cur_lon`（表演期间目标跟随当前位置；GUI `update_position` 显式设值优先级更高）；新增 `latlon`（度→1e7）/ `alt_m`（米→mm）类型，`_make_input_widget` 使用 QDoubleSpinBox 适配小数输入；`_config.py` airplane `known_param_types` 注册 lat/lon/alt 新类型；新增 `test_optimize_latlon_tar.py`（6 个测试用例）
> - 2026-08-04: **`update_ack` 签名扩展**：新增 `silence_count`（ACK 静默，前 N 次不回复）和 `cmd_result_enable/cmd_result_commands/cmd_result_values`（特定 command result 覆写，支持单值广播/一一对应）三种 ACK 响应模式（优先级: 静默 > cmd_result > fail_count）；`__init__` 新增 `_ack_silence_count/counters/last_time`、`_ack_cmd_result_enabled/map` 属性；`_build_id_077_cmd` 重构为三阶段检查；`_parse_list` 新增单值解析（支持 `"4"` → `[4]`）；GUI `_config.py` known_param_types 新增 ACK 相关参数类型声明
> - 2026-08-03: `update_lantern` 签名修正：`lantern_config`→`fold_lantern_config`，删除 `lantern` 参数，新增 `peach_lantern_config/fish_lantern_config/kongming_lantern_config` 可选参数；新增 `update_confetti(confetti_config)` 方法（对应 param1=1/param7=16）；`known_param_types` 新增对应参数类型，删除 `kongming_lantern`（裸）；`_build_id_204` 保持 5 字段不变（不包含 peach/fish/kongming/confetti _state 字段，因 MAVLink 协议 JSON 未定义）
> - 2026-07-29: 新增 `update_hover_fence(manual_enable, safe_distance)` / `update_hover_test(manual_enable, takeoff_height, hover_duration)` 方法；新增 `fence_manual_enable` / `safe_distance` / `hover_manual_enable` / `takeoff_height` / `hover_duration` 状态属性；`_handle_param_set` / `_handle_param_request_read` 中增加 fence_manual_enable 检查，manual_enable=True 时用 `safe_distance/2+1.0` 替换 FS_FENCE_RDS 回显值
> - 2026-07-28: 新增 `update_bin_save(enable, save_dir)` 方法；`_save_drama_bin` 受 `enable_bin_save` 守卫控制，保存路径改用实例属性 `bin_save_dir`；默认关闭 bin 保存
> - 2026-07-28: 新增 `update_waypoint_parse(bool)` / `update_waypoint_compare(bool)` 方法；`_save_drama_bin` 改为条件解析（由 `enable_waypoint_parse` 控制）；移除偶数次自动对比逻辑
> - 2026-07-27: 新增 `update_bat(**kwargs)` 方法（18 个电池/电压字段）；`FakeAirplane.receive()` 中 DEBUG 打印暂时注释
> - 2026-07-23: 初始版本，基于 `fake_airplane.py` (2255 行) 创建
