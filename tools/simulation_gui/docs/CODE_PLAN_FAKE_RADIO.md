# fake_radio.py — 代码方案

> **文件**: `D:\Work\dmd_autotest_project_ycl\src\Protocol\mavlink\fake_radio.py`
> **版本**: v1.8
> **行数**: 1866
> **最后同步**: 2026-09-08
> **用途**: 假 R2 电台模拟器，基于 DGCS v4 DAV 协议（DavLink2）实现，模拟 R2 双频 / R2G 单频电台的完整生命周期
>
> **关联子方案**:
> - [CODE_PLAN.md](./CODE_PLAN.md) — integrated_gui.py 主面板方案（SimulationPanel 驱动本模块）
> - [PROJECT_PLAN.md](./PROJECT_PLAN.md) — mavlink_monitor 核心引擎方案
> - [CODE_PLAN_FAKE_AIRPLANE.md](./CODE_PLAN_FAKE_AIRPLANE.md) — 假飞机模块方案
> - [CODE_PLAN_FAKE_NEST.md](./CODE_PLAN_FAKE_NEST.md) — 假机巢模块方案

---

## 目录

1. [文件速览](#1-文件速览)
2. [代码分段索引](#2-代码分段索引)
3. [类层次结构](#3-类层次结构)
4. [核心类详解](#4-核心类详解)
5. [DAV 协议帧格式](#5-dav-协议帧格式)
6. [状态机与生命周期](#6-状态机与生命周期)
7. [update_xxx 方法清单](#7-update_xxx-方法清单)
8. [与 integrated_gui.py 的交互](#8-与-integrated_guipy-的交互)
9. [修改指南](#9-修改指南)

---

## 1. 文件速览

```
fake_radio.py  (1316 行)
│
├── L1-20     模块文档字符串
├── L22-33    stdlib imports（ctypes, socket, struct, threading 等）
│
├── L35-46    配置常量 —— IP、端口、DAV 地址
├── L48-81    CRC8 查表 + crc8() 函数
├── L83-121   CRC16 查表 + crc16() 函数
│
├── L124-367  Protobuf 手动编码
│   ├── L130-139  MessageID 枚举类
│   ├── L142-159  设备/状态/国家码常量
│   ├── L162-194  Varint / field 编码辅助函数
│   ├── L197-212  build_enroll_request()
│   ├── L215-328  build_heartbeat() —— 15+ 参数
│   ├── L331-353  parse_enroll_reply()
│   └── L356-367  _read_varint()
│
├── L370-551  DavLink2Codec —— DAV 链路层编解码器
│   ├── L375-400  类文档 + __init__
│   ├── L406-445  encode_msg() —— 编码 Msg 帧
│   ├── L447-474  encode_ack() —— 编码 Ack 帧
│   ├── L476-502  _put_source_addr() / _put_dest_addr() —— 52-bit 地址写入
│   └── L508-551  decode() —— 解码任意 DAV 帧
│
├── L554-1086 FakeR2RadioStation —— 假电台主类
│   ├── L559-597   类文档 + 状态机常量 + 时序常量
│   ├── L599-647   __init__ —— 初始化所有属性
│   ├── L653-683   _build_default_rf() —— RF 参数默认值
│   ├── L689-722   _setup_network() —— PowerShell 辅助 IP + _ip_exists_locally()
│   ├── L728-772   UDP: _udp_setup() / _udp_send() / _udp_recv()
│   ├── L778-806   生命周期: start() / stop()
│   ├── L813-835   _run() —— 主循环（注册 + 心跳 + 消息处理）
│   ├── L841-876   _do_enroll() —— 注册流程
│   ├── L882-923   _send_heartbeat() —— 心跳构造与发送
│   ├── L929-962   _handle_incoming() —— 地面站消息分发
│   ├── L968-1020  _on_set_domain() / _on_set_encrypt() / _on_set_button()
│   ├── L1026-1035 _send_ack()
│   └── L1041-1085 公开 API: set_encrypt_type() / set_rf_band() / set_battery() / set_gps()
│
├── L1088-1146 FakeRadioStationManager —— 批量管理器
│   ├── L1103-1130 __init__ —— 创建多台 FakeR2RadioStation
│   ├── L1132-1140 start_all()
│   └── L1142-1145 stop_all()
│
├── L1148-1237 _FakeRadioSender —— GUI 适配层包装器
│   ├── L1159-1163 __init__
│   ├── L1167-1189 sender 接口属性（thread / running / code / serial）
│   ├── L1191-1200 _run() —— 确保网络/UDP 后委托给 _radio._run()
│   ├── L1202-1208 stop() / close()
│   └── L1212-1236 update_xxx 方法（4 个）
│
├── L1239-1285 _FakeRadioSenders —— GUI 批量管理器
│   ├── L1247-1277 __init__ —— _FakeRadioSender 列表创建
│   └── L1279-1284 stop()
│
└── L1287-1316 __main__ 入口
```

---

## 2. 代码分段索引

> 使用方法：在 IDE 中 `Ctrl+G` 跳转到对应行号即可定位功能区域。

### 2.1 导入与配置常量 (L1-46)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L1-20 | 模块文档字符串（架构说明 + 运行方式） | — |
| L22-33 | stdlib imports | `ctypes`, `socket`, `struct`, `subprocess`, `threading` |
| L39-42 | 网络配置常量 | `FAKE_RADIO_IP`, `DGCS_IP`, `DAV_PORT`, `NETCARD_INTERFACE` |
| L44-46 | DAV 地址常量（52-bit） | `RADIO_BASE_ADDR`, `GROUND_ADDR` |

### 2.2 CRC 校验 (L48-121)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L53-70 | CRC8 查表（256 项，多项式 0x31） | `CRC8_TABLE` |
| L73-80 | `crc8()` 函数 —— DAV 头部校验（bytes 0-20，初始值 0xFF） | `crc8()` |
| L88-111 | CRC16 查表（256 项，多项式 0x8005） | `CRC16_TABLE` |
| L114-121 | `crc16()` 函数 —— DAV 整帧校验（bytes 0..End-3，初始值 0xFFFF） | `crc16()` |

### 2.3 Protobuf 手动编码 (L130-535)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L130-148 | MessageID 枚举（16 个消息 ID，v1.4 新增 0x0103/0x0104/0x0201/0x0202 查询指令） | `ENROLL_REQUEST(0x000C)`, `SEND_RADIO_R2_HEARTBEAT(0x0204)`, `ASK_RADIO_ENCRYPT_KEY(0x0103)`, `SEND_RADIO_ENCRYPT_KEY(0x0104)`, `ASK_RADIO_REGULATORY_DOMAIN(0x0201)`, `SEND_RADIO_REGULATORY_DOMAIN(0x0202)` 等 |
| L143-159 | 设备类型 / 子型号 / 状态 / 国家码常量 | `ONLINE_DEVICE_TYPE_RADIO_STATION`, `SUB_DEVICE_R2_STATION`, `ENROLL_ACCEPTED` 等 |
| L162-169 | `_proto_varint()` —— varint 编码 | — |
| L172-194 | field 编码辅助函数 | `_proto_field_varint()`, `_proto_field_length_delimited()`, `_proto_field_fixed32()`, `_proto_packed_varint()` |
| L197-205 | **`_proto_field_fixed64()`**（v1.4 新增）—— 编码 double（wire_type 1, IEEE 754 双精度位） | 用于 rtkStationPosition 的 lat/lon/alt |
| L208-224 | `build_enroll_request()` —— 构造 EnrollRequest protobuf | 4 个字段: device_type, product_name, serial_number, check |
| L232-246 | **`build_send_encrypt_key()`**（v1.4 新增）—— 构造 SEND_RADIO_ENCRYPT_KEY(0x0104) | `RadioEncryptKey.radio_key{encrypt_type, encrypt_key, encrypt_iv}` |
| L249-271 | **`build_send_regulatory_domain()`**（v1.4 新增）—— 构造 SEND_RADIO_REGULATORY_DOMAIN(0x0202) | `set_device_id` + `set_rf_param[]`（800M/2.4G） |
| L274-410 | `build_heartbeat()` —— 构造 RadioStationR2Heart protobuf（v1.4: GPS 改为 double 编码） | 15+ 参数，含扩展消息 RadioStationR2HeartBeatExtend |
| L400-423 | `parse_enroll_reply()` —— 解析 EnrollReply | 返回 `{accept_status, heartbeat_interval_ms}` |
| L425-437 | `_read_varint()` —— varint 解码器 | 返回 `(value, new_pos)` |
| L439-493 | **`_parse_proto_fields()` / `_parse_packed_varints()`** —— 通用 protobuf wire 解析（v1.3 新增） | 用于 `_on_set_*` 命令解析 |
| L495-529 | **`_parse_rfparameters()`** —— 解析 RFparameters 子消息（v1.3 新增，支持 packed/unpacked） | mode/powers/temperature/max_fre/min_fre |

### 2.4 DavLink2Codec 编解码器 (L370-551)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L375-400 | 类文档 + `__init__` | `device_addr`, `_tx_seq`, `HEADER_MARKER=0xA5`, `HEADER_LEN=22` |
| L406-445 | `encode_msg()` —— 编码 Msg 类型帧 | 22B 头 + 2B msg_id + payload + 2B CRC16 |
| L447-474 | `encode_ack()` —— 编码 Ack 类型帧 | MsgType=1，data_len=4（uint32 report） |
| L476-488 | `_put_source_addr()` —— 写入 52-bit 源地址 | byte 7-12 + byte 13 低 nibble |
| L490-502 | `_put_dest_addr()` —— 写入 52-bit 目标地址 | byte 13 高 nibble + byte 14-19 |
| L508-551 | `decode()` —— 解码 DAV 帧 | 返回 dict 含 `msg_type, ack_count, msg_id, payload, report` 或 None |

### 2.5 FakeR2RadioStation 主类 (L669-1333)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L732-759 | 类文档 —— 生命周期四步骤 | — |
| L761-770 | 状态机常量 + 时序常量 | `STATE_INIT=0`, `STATE_ENROLLING=1`, `STATE_ONLINE=2`；`HEARTBEAT_INTERVAL=2.5`, `ENROLL_TIMEOUT=5.0` 等 |
| L768-835 | **`__init__`** —— 11 个参数 + 22 个内部属性（v1.4: 新增 `_encrypt_key`/`_encrypt_iv`） | `device_addr`, `codec`, `_rf_params`, `_battery_percentage`, `_gps_*`, `_button_param`, `_receiver_mode`, `_receiver_rc_radio`, `_encrypt_key`, `_encrypt_iv` 等 |
| L837-867 | `_build_default_rf()` —— 根据 sub_device_type 构建 RF 默认值 | `band_800m`（双频）或仅 `band_2400m`（单频） |
| L873-906 | 网络初始化 | `_ip_exists_locally()`, `_setup_network()`（PowerShell New-NetIPAddress） |
| L912-956 | UDP 通讯 | `_udp_setup()`（最多 10 次重试）, `_udp_send()`, `_udp_recv()` |
| L962-990 | 生命周期管理 | `start()`（网络→UDP→线程）、`stop()`（线程→socket） |
| L997-1019 | **`_run()`** 主循环 | Phase 1: `_do_enroll()` → Phase 2: 心跳 + 消息处理（每 0.1s 循环） |
| L1025-1060 | `_do_enroll()` 注册流程 | 发 EnrollRequest → 等待 5s 内 EnrollReply（accepted） |
| L1076-1113 | `_send_heartbeat()` | 组装 build_heartbeat(**kwargs)（v1.3: 传入 button_param 全字段；v1.4: GPS 走 double）→ encode → UDP 发送 |
| L1126-1182 | `_handle_incoming()` | 最多 5 条/循环，dispatch: SetDomain / SetEncrypt / SetButton / SetReceiverMode / SetReceiverRcRadio / SendRtcm / FreqMatching / AskEncryptKey / AskRegulatoryDomain / AskHeartbeat + 通用 fallback 肯定 ACK |
| L726-858 | **RTCM3 差分帧构建工具（v1.9，模块级）** | `_crc24q`(L731, CRC-24Q 0x1864CFB), `_rtcm_pack_bits`(位流打包), `_build_rtcm_frame`(0xD3+10bit长度+CRC), `build_rtcm1005`(L768, 基准站帧 DF022/23/24 信号指示位), `build_rtcm1124`(L795, BDS MSM4 链路模拟帧), `pack_single_bytes`/`unpack_single_bytes`(L815, SingleBytes 包装 §11.2.2), `rtcm_summarize`(L845, 帧消息号摘要) |
| L1196-1250 | **差分上报（v1.9，技术方案 §11 差分源）** | `set_diff_enable`(L1203), `set_diff_signal_state`(L1209), `_tick_diff`(L1221, 上线≥10s 后 1Hz 调度), `_send_diff`(L1235, RTCM(1005+1124)→SingleBytes→RadioSendRtcm ackCount=0) |
| L1185-1229 | `_on_set_domain()` —— 完整解析 `RadioStationRegulatoryDomain`（set_device_id + set_rf_param→RFparameters） | 更新 `_rf_params`，下次心跳 radio_rf_param 反映 |
| L1232-1263 | `_on_set_encrypt()` —— 完整解析 `RadioEncryptKey`（radio_key/rc_key 的 encrypt_type/key/iv） | 更新 `_encrypt_type`/`_encrypt_key`/`_encrypt_iv`，心跳 encrypt_type 反映 |
| L1266-1289 | `_on_set_button()` —— 完整解析 `RadioButtonParam`（time/mode/short_mode） | 更新 `_button_param`，心跳 button_param 反映 |
| L1292-1307 | **`_on_set_receiver_mode()`**（v1.3 新增）—— 解析 `RadioReceiverMode` | 更新 `_receiver_mode` |
| L1310-1339 | **`_on_set_receiver_rc_radio()`**（v1.3 新增）—— 解析 `RadioReceiverRFparameters` | 更新 `_receiver_rc_radio` |
| L1343-1354 | **`_on_ask_encrypt_key()`**（v1.4 新增）—— 处理 ASK_RADIO_ENCRYPT_KEY(0x0103) | 回复 SEND_RADIO_ENCRYPT_KEY(0x0104)，携带当前加密状态 |
| L1357-1368 | **`_on_ask_regulatory_domain()`**（v1.4 新增）—— 处理 ASK_RADIO_REGULATORY_DOMAIN(0x0201) | 回复 SEND_RADIO_REGULATORY_DOMAIN(0x0202)，携带当前射频参数 |
| L1389-1433 | **`_ack_policy(msg_id)`**（v1.7）—— 判定本次命令 ACK 响应策略并递增计数 | 返回 `(action, report)`：silence（不回复）/ fail（report=4）/ override（指定 report）/ normal |
| L1435-1449 | **`_handle_config_command(msg_id, ack_count, apply_fn=None)`**（v1.7）—— 按策略处理配置指令 | silence 不应用+不回复；fail/override 不应用+回复指定 report；normal 应用 `apply_fn`+回复 report=0 |
| L1451-1460 | `_send_ack(ack_count, report=0)` —— 直接发帧（report 由 `_ack_policy` 计算） | msgType=1, ackCount 原值回传 |
| L1386-1435 | 公开 API | `set_encrypt_type()`, `set_rf_band()`, `set_battery()`, `set_gps()` |

### 2.6 管理器与适配层 (L1437-1742)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L1437-1494 | `FakeRadioStationManager` —— 批量管理器 | `radios` 列表，`start_all()`，`stop_all()` |
| L1497-1533 | **`_RadioSocketInterceptor`**（v1.5 新增）—— 内部 socket 拦截器 | 包装 recvfrom/sendto，供 `_FakeRadioSender.set_msg_injector` 就地包装（处理 socket 延迟创建） |
| L1537-1664 | `_FakeRadioSender` —— GUI 适配包装器（v1.5: 新增 `set_msg_injector`/`_wrap_sock`） | sender 接口 + transport 接口 + 4 个 `update_xxx`；`_run` 中 socket 就绪后自动自包装 |
| L1594-1623 | **`set_msg_injector(callback)` / `_wrap_sock()`**（v1.5 新增）—— 消息注入回调 + sock 自包装 | gcs 取模块常量 `DGCS_IP`/`DAV_PORT`；接收 src=地面站、外发 dst=地面站 |
| L1668-1742 | `_FakeRadioSenders` —— GUI 批量适配器 | `radio_senders` / `radios` 双列表（相同对象） |

### 2.7 入口 (L1744-1777)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L1748-1774 | `if __name__ == "__main__"` —— 独立运行示例 | 创建单台 R2 双频电台，Ctrl+C 停止 |
| L1631-1657 | `if __name__ == "__main__"` —— 独立运行示例 | 创建单台 R2 双频电台，Ctrl+C 停止 |

---

## 3. 类层次结构

```
外部依赖:
  utils.logger
    └── LogManager, logger

本文件类层次:

  DavLink2Codec                                     (L375)
    │  帧编解码器，被 FakeR2RadioStation 组合使用
    │
    └── (组合) FakeR2RadioStation                   (L558)
          │  假电台核心：状态机、注册、心跳、命令响应
          │
          ├── (独立管理器) FakeRadioStationManager  (L1092)
          │     ├── .radios: list[FakeR2RadioStation]
          │     ├── start_all()
          │     └── stop_all()
          │
          ├── (GUI 适配) _FakeRadioSender           (L1152)
          │     ├── ._radio: FakeR2RadioStation       ← 委托
          │     ├── sender 接口: thread, running, code, serial, _run(), stop()
          │     ├── transport 接口: local_ip, local_port, close()
          │     └── update 方法: update_battery/gps/encrypt/rf_band
          │
          └── (GUI 批量) _FakeRadioSenders           (L1239)
                ├── .radio_senders: list[_FakeRadioSender]
                ├── .radios: list[_FakeRadioSender]    ← 同一批对象
                └── stop()

辅助类/函数:
  MessageID                                          (L130)  ← 枚举命名空间
  build_enroll_request()                             (L197)  ← Protobuf 构造
  build_heartbeat()                                  (L215)  ← Protobuf 构造
  parse_enroll_reply()                               (L331)  ← Protobuf 解析
  crc8() / crc16()                                   (L73 / L114)  ← CRC 校验
```

**关键设计模式**:

| 模式 | 位置 | 说明 |
|------|------|------|
| **适配器** | `_FakeRadioSender` (L1152) | 将 `FakeR2RadioStation` 适配为 `SimulationPanel` 期望的 sender/transport 双接口 |
| **委托** | `_FakeRadioSender._radio` | 所有 sender/update 方法最终委托给内部 `FakeR2RadioStation` 实例 |
| **批量管理** | `_FakeRadioSenders` (L1239) | `radio_senders` 和 `radios` 持有同一批对象（`SimConfig.mgr_senders_attr="radio_senders"`, `mgr_transports_attr="radios"`） |
| **状态机** | `FakeR2RadioStation` (L588-591) | `INIT(0) → ENROLLING(1) → ONLINE(2)` |
| **策略** | `_handle_incoming()` (L929) | 按 `msg_id` 分发到不同的 `_on_*` 处理器 |

---

## 4. 核心类详解

### 4.1 DavLink2Codec (L375-551)

**职责**: DAV 链路层帧编解码器，严格对应 C# DavLink2 (DavLink.cs:164-315)。

**帧格式**（详见 §5）:

```
[0] 0xA5 Sync
[1] TxSeq (0-255)
[2:3] DataLen (10bit) + Version (2bit)
[4] AckCount (6bit) + MsgType (2bit)
[5:6] ReceiveType
[7:12]+[13低4位] 源地址 (52-bit)
[13高4位]+[14:19] 目标地址 (52-bit)
[20] Reserved
[21] CRC8 (over bytes 0-20)
[22:23] MessageID (LE uint16) —— 仅 Msg 帧
[24:] Protobuf payload
[End-2:] CRC16 (over bytes 0..End-3)
```

**关键属性**:

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `HEADER_MARKER` | `int` | `0xA5` | 帧同步字 |
| `HEADER_LEN` | `int` | `22` | 帧头长度（不含 payload 和 CRC16） |
| `MSG_TYPE_MSG` | `int` | `0` | Msg 类型标识 |
| `MSG_TYPE_ACK` | `int` | `1` | Ack 类型标识 |
| `device_addr` | `int` | — | 本设备 52-bit 地址 |
| `_tx_seq` | `int` | `0` | 发送序号（0-255 自增） |

**关键方法**:

| 方法 | 行号 | 功能 |
|------|------|------|
| `__init__(device_addr)` | L398-400 | 保存 52-bit 地址，初始化 `_tx_seq=0` |
| `encode_msg(msg_id, payload, ack_count=0)` | L406-445 | 编码 Msg 类型帧（发送 protobuf 消息） |
| `encode_ack(ack_count, report=0)` | L447-474 | 编码 Ack 类型帧（响应地面站命令） |
| `_put_source_addr(buf, addr)` | L476-488 | 将 52-bit 源地址写入 byte 7-12 + byte 13 低 nibble |
| `_put_dest_addr(buf, addr)` | L490-502 | 将 52-bit 目标地址写入 byte 13 高 nibble + byte 14-19 |
| `decode(data)` | L508-551 | 解码 DAV 帧，返回 dict 或 None（校验失败） |

---

### 4.2 FakeR2RadioStation (L558-1086)

**职责**: 假 R2 电台核心类，实现完整的 DAV 协议生命周期。

**初始化参数** (L599-609):

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `device_id` | `int` | `1` | 设备 ID（0-255），DAV 地址 = `RADIO_BASE_ADDR + device_id` |
| `sub_device_type` | `int` | `5` (R2 双频) | 子型号: 5=双频, 3=R2G 2.4G 单频 |
| `local_ip` | `str` | `"172.16.200.100"` | 本机 IP |
| `dgcs_ip` | `str` | `"172.16.200.1"` | DGCS 地面站 IP |
| `port` | `int` | `14555` | UDP 端口 |
| `serial_number` | `str` | `"R2-SIM-{device_id:05d}"` | 序列号 |
| `product_name` | `str` | `"R2-SIMULATOR"` | 产品名 |
| `firmware_version` | `str` | `"R2.1.0.0"` | 固件版本字符串 |
| `interface` | `str` | `"WLAN 6"` | Windows 网卡接口名 |

**关键内部属性** (L611-647):

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `device_addr` | `int` | `0xFFFFFFFFFF100 + device_id` | 52-bit DAV 地址 |
| `codec` | `DavLink2Codec` | — | 帧编解码器 |
| `sock` | `Optional[socket.socket]` | `None` | UDP socket |
| `running` | `bool` | `False` | 运行标志（控制线程退出） |
| `_thread` | `Optional[Thread]` | `None` | 后台线程（daemon） |
| `state` | `int` | `STATE_INIT(0)` | 当前状态 |
| `_last_hb` | `float` | `0.0` | 上次心跳时间戳 |
| `online` | `bool` | `False` | 对外可见的在线状态 |
| `_encrypt_type` | `int` | `0` | 加密类型（0=none, 1=AES-128, 2=AES-256） |
| `_rf_params` | `dict` | 见 L653-683 | RF 频段参数（band_800m / band_2400m） |
| `_battery_percentage` | `int` | `85` | 电池百分比 |
| `_poe_voltage_mv` | `int` | `12000` | PoE 电压 (mV) |
| `_charge_temperature` | `int` | `30` | 充电温度 |
| `_rf_800m_temperature` | `int` | `35` | 800M 射频温度 |
| `_rf_2400m_temperature` | `int` | `32` | 2.4G 射频温度 |
| `_gps_latitude` | `float` | `22.0` | GPS 纬度 |
| `_gps_longitude` | `float` | `113.0` | GPS 经度 |
| `_gps_altitude` | `float` | `100.0` | GPS 高度 |

**时序常量** (L593-597):

| 常量 | 值 | 说明 |
|------|-----|------|
| `HEARTBEAT_INTERVAL` | `2.5` | 心跳间隔（秒） |
| `ENROLL_TIMEOUT` | `5.0` | 注册超时（秒） |
| `RECV_TIMEOUT` | `1.0` | socket 接收超时（秒） |
| `LOOP_INTERVAL` | `0.1` | 主循环轮询间隔（秒） |
| `DIFF_START_DELAY` | `10.0` | 上线后差分起始延迟（秒，§11.2.4 地面站转发定时器 10s 后才启动）（v1.9） |
| `DIFF_INTERVAL` | `1.0` | 差分上报周期（秒，1Hz；地面站判活要求 ≥1 帧/2s）（v1.9） |

**关键方法详表**:

| 方法 | 行号 | 访问 | 功能 |
|------|------|------|------|
| `_build_default_rf()` | L653 | private | 根据 `sub_device_type` 构建 `_rf_params` 默认值 |
| `_ip_exists_locally(ip)` | L689 | private | 检查 IP 是否已绑定到本机 |
| `_setup_network()` | L702 | private | PowerShell 添加辅助 IP（若不存在） |
| `_udp_setup()` | L728 | private | 创建 UDP socket（最多 10 次重试） |
| `_udp_send(data)` | L750 | private | 发送 UDP 到地面站 |
| `_udp_recv()` | L761 | private | 非阻塞接收（超时返回 None） |
| `start()` | L778 | public | 启动: 网络→UDP→线程 |
| `stop()` | L795 | public | 停止: 线程→socket→状态重置 |
| `_run()` | L813 | private | 主循环: `_do_enroll()` → 心跳 + 消息处理 |
| `_do_enroll()` | L841 | private | 注册流程: 发 EnrollRequest → 等 EnrollReply（5s 超时） |
| `_send_heartbeat()` | L882 | private | 组装 protobuf → 编码 → UDP 发送 |
| `_handle_incoming()` | L929 | private | 每次循环处理最多 5 条消息，按 msg_id 分发 |
| `_on_set_domain(payload)` | L968 | private | 处理 SetRadioRegulatoryDomain（简化实现） |
| `_on_set_encrypt(payload)` | L977 | private | 解析 protobuf 提取 encrypt_type 并更新 |
| `_on_set_button(payload)` | L1018 | private | 处理 SetRadioButtonParam（空实现） |
| `_send_ack(ack_count)` | L1026 | private | ack_count≠0 时回复 ACK 帧 |
| `set_encrypt_type(encrypt_type)` | L1041 | public | 修改加密类型 |
| `set_rf_band(band_key, mode, powers, ...)` | L1045 | public | 修改 RF 频段参数 |
| `set_battery(percentage, voltage_mv, temperature)` | L1067 | public | 修改电池/温度 |
| `set_gps(latitude, longitude, altitude)` | L1077 | public | 修改 GPS 位置 |

---

### 4.3 FakeRadioStationManager (L1092-1146)

**职责**: 批量假电台管理器，一次性创建并管理多台电台。

**初始化参数** (L1103-1111):

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `count` | `int` | `1` | 电台数量 |
| `start_device_id` | `int` | `1` | 起始 device_id（递增分配） |
| `start_ip` | `str` | `FAKE_RADIO_IP` | 起始 IP（末段递增分配） |
| `sub_device_type` | `int` | `SUB_DEVICE_R2_STATION` | 子型号 |
| `dgcs_ip` | `str` | `DGCS_IP` | 地面站 IP |
| `interface` | `str` | `NETCARD_INTERFACE` | 网卡接口 |

**关键属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `radios` | `list[FakeR2RadioStation]` | 所有创建的电台实例 |

**关键方法**:

| 方法 | 行号 | 功能 |
|------|------|------|
| `__init__` | L1103 | 验证 count/IP 范围 → 循环创建 FakeR2RadioStation |
| `start_all()` | L1132 | 依次启动（间隔 0.5s 错开注册） |
| `stop_all()` | L1142 | 依次停止 |

---

### 4.4 _FakeRadioSender (L1152-1237)

**职责**: GUI 适配层包装器。将 `FakeR2RadioStation` 适配为 `SimulationPanel` 期望的双接口：
- **sender 接口**: `thread`, `running`, `code`, `serial`, `_run()`, `stop()`
- **transport 接口**: `local_ip`, `local_port`, `close()`
- 同时兼任两个角色（同一对象出现在 `radio_senders` 和 `radios` 两个列表中）

**关键属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `_radio` | `FakeR2RadioStation` | 被包装的核心电台实例 |
| `local_ip` | `str` | 来自 `radio.local_ip`（transport 接口） |
| `local_port` | `int` | 来自 `radio.port`（transport 接口） |
| `thread` (property) | `Thread` | 读写 `_radio._thread`（sender 接口） |
| `running` (property) | `bool` | 读写 `_radio.running`（sender 接口） |
| `code` (property) | `int` | 返回 `_radio.device_id`（sender 接口） |
| `serial` (property) | `str` | 返回 `_radio.serial_number`（sender 接口） |

**关键方法**:

| 方法 | 行号 | 功能 |
|------|------|------|
| `_run()` | L1191 | 确保网络/UDP 已初始化后调用 `_radio._run()`（GUI 的 `_start_sender_thread` 直接调用 `_run`，跳过了 `start()` 的网络初始化） |
| `stop()` | L1202 | 委托 `_radio.stop()` |
| `close()` | L1207 | 委托 `_radio.stop()`（transport 接口） |
| `update_battery(...)` | L1212 | 委托 `_radio.set_battery()` |
| `update_gps(...)` | L1218 | 委托 `_radio.set_gps()` |
| `update_encrypt(...)` | L1224 | 委托 `_radio.set_encrypt_type()`（仅非 None 时） |
| `update_rf_band(...)` | L1229 | 委托 `_radio.set_rf_band()`（仅 band_key 非 None 时） |
| `update_diff(enable=True, gps_signal=1, glonass_signal=1, galileo_signal=1)` | L1991 | **v1.9 新增** — 委托 `_radio.set_diff_enable()` + `set_diff_signal_state()`；控制差分外发开关及 RTCM 1005 帧 DF022/DF023/DF024 卫星信号指示位（差分报文中的"信号状态"） |

---

### 4.5 _FakeRadioSenders (L1239-1285)

**职责**: 批量管理器的 GUI 适配层。对应 `_FakeAirplaneMessageSenders` / `_FakeNestSenders` 的模式。

**初始化参数** (L1247-1252):

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `count` | `int` | `1` | 电台数量 |
| `start_device_id` | `int` | `1` | 起始 device_id |
| `start_ip` | `str` | `FAKE_RADIO_IP` | 起始 IP |
| `sub_device_type` | `int` | `SUB_DEVICE_R2_STATION` | 子型号 |
| `dgcs_ip` | `str` | `DGCS_IP` | 地面站 IP |
| `interface` | `str` | `NETCARD_INTERFACE` | 网卡接口 |
| `log_manager` | — | `None` | 日志管理器（保留接口，实际未使用） |

**关键属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `radio_senders` | `list[_FakeRadioSender]` | sender 列表（`SimConfig.mgr_senders_attr` 指向此属性） |
| `radios` | `list[_FakeRadioSender]` | transport 列表（`SimConfig.mgr_transports_attr` 指向此属性） |

**关键行为**:
- 两个列表持有完全相同的 `_FakeRadioSender` 对象
- `stop()` 遍历 `radio_senders` 逐一停止，捕获异常防止中断

---

## 5. DAV 协议帧格式

### 5.1 帧结构总览

```
Byte 偏移   内容
─────────────────────────────────────────────────
 0          0xA5  Sync 同步字
 1          TxSeq  发送序号（0-255 自增）
 2-3        DataLen (10bit) + Version (2bit, =0)
 4          AckCount (6bit, bit7-2) + MsgType (2bit, bit1-0)
 5-6        ReceiveType (保留 =0)
 7-12       Source Addr [39:0]  (byte 7 是最低字节)
13[3:0]     Source Addr [51:40] (bit 48-51, 低 nibble)
13[7:4]     Dest Addr [3:0]     (bit 0-3, 高 nibble)
14-19       Dest Addr [47:4]    (byte 14 是 bit 4-11)
20          Reserved (=0)
21          CRC8  覆盖 bytes 0-20
─────────────────────────────────────────────────  ← 帧头结束 (22 bytes)
22-23       MessageID  (LE uint16)  仅 MsgType=0
24-( )      Payload  (protobuf 序列化数据)
─────────────────────────────────────────────────
(End-2)     CRC16  覆盖 bytes 0..(End-3)
(End-1)     CRC16 低字节
```

### 5.2 MsgType 区分

| MsgType (bit1-0) | 含义 | DataLen 内容 | 帧尾 |
|-------------------|------|-------------|------|
| `0` (MSG_TYPE_MSG) | 数据消息 | 2B msg_id + protobuf payload | 2B CRC16 |
| `1` (MSG_TYPE_ACK) | 应答消息 | 4B report (uint32 LE) | 2B CRC16 |

### 5.3 CRC 校验细节

| CRC 类型 | 多项式 | 初始值 | 覆盖范围 | 表格大小 |
|----------|--------|--------|----------|----------|
| CRC8 | `x^8 + x^5 + x^4 + 1` (0x31) | `0xFF` | bytes 0-20（帧头 21 字节） | 256 项 |
| CRC16 | `x^16 + x^12 + x^5 + 1` (0x8005) | `0xFFFF` | bytes 0..(End-3)（整帧除去 CRC16 自身） | 256 项 |

来源：分别对应 C# 源码 `CRC8.cs:7-23` 和 `CRC16.cs:7-28`。

### 5.4 地址编码（52-bit）

| 地址 | 常量 | 编码位置 |
|------|------|----------|
| 电台设备地址 | `RADIO_BASE_ADDR(0xFFFFFFFFFF100) + device_id` | byte 7-12 + byte 13 低 nibble |
| 地面站地址 | `GROUND_ADDR(0xFFFFFFFFFFFF0)` | byte 13 高 nibble + byte 14-19 |

地址范围：
- 电台: `0xFFFFFFFFFF100 ~ 0xFFFFFFFFFF1FF`（支持 device_id=0~255）
- 地面站: `0xFFFFFFFFFFFF0`（固定 52-bit 全 F）

### 5.5 DavLink2Codec 解码流程

```
decode(data)                                      (L508)
  │
  ├── 1. 长度检查 (< HEADER_LEN+2 → None)
  ├── 2. Sync 字检查 (data[0] != 0xA5 → None)
  ├── 3. 解析 data_len = data[2] + ((data[3] & 0x3F) << 8)
  ├── 4. 长度完整性检查
  ├── 5. CRC8 校验 (bytes 0-20)
  │     └── data[21] == crc8(data, 0, 21) ?
  ├── 6. CRC16 校验 (bytes 0..End-3)
  │     └── calc_crc == pkt_crc ?
  ├── 7. 解析 ack_count + msg_type (from byte 4)
  └── 8. 根据 msg_type 提取:
        ├── Msg: msg_id (bytes 22-23 LE) + payload (bytes 24+)
        └── Ack: report (bytes 22-25 LE uint32)
```

---

## 6. 状态机与生命周期

### 6.1 状态转换图

```
                  start()
                     │
     ┌───────────────▼───────────────┐
     │       STATE_INIT (0)          │
     │  网络初始化 + UDP 绑定        │
     └───────────────┬───────────────┘
                     │ _do_enroll()
                     ▼
     ┌───────────────┐
     │ STATE_ENROLLING│ 超时 5s ────────► 线程退出
     │   (1)         │
     │ 发 EnrollReq  │
     │ 等 EnrollReply│
     └───────┬───────┘
             │ accepted
             ▼
     ┌───────────────────────────────────────────────┐
     │              STATE_ONLINE (2)                  │
     │                                                │
     │  每 0.1s 循环:                                 │
     │    ├── _handle_incoming()  处理地面站消息       │
     │    │    ├── SET_RADIO_REGULATORY_DOMAIN (0x0203)│
     │    │    ├── SET_RADIO_ENCRYPT_KEY      (0x0102)│
     │    │    ├── SET_RADIO_BUTTON_PARAM     (0x0205)│
     │    │    ├── RADIO_SEND_RTCM            (0x0100)│
     │    │    └── ASK_HEARTBEAT              (0x000E)│
     │    │                                            │
     │    └── 每 2.5s: _send_heartbeat()              │
     │         └── RadioStationR2Heart (0x0204)        │
     │                                                  │
     │  退出条件: self.running == False                  │
     └──────────────────────────────────────────────────┘
```

### 6.2 注册流程详解

```
_do_enroll()                                       (L841)
  │
  ├── 1. state = STATE_ENROLLING
  ├── 2. 构建 EnrollRequest protobuf
  │      fields: device_type=2, product_name, serial_number, check=0
  ├── 3. codec.encode_msg(ENROLL_REQUEST=0x000C, payload)
  ├── 4. _udp_send(frame) → 地面站
  │
  └── 5. 阻塞等待 (ENROLL_TIMEOUT=5.0s):
        │
        └── 循环: _udp_recv() → decode() →
              过滤 msg_type=MSG + msg_id=ENROLL_REPLY
              │
              └── parse_enroll_reply(payload)
                   ├── accept_status=ENROLL_ACCEPTED(0) → state=ONLINE, return True
                   └── 其他 → return False
```

### 6.3 在线阶段消息处理

每个 `LOOP_INTERVAL(0.1s)` 周期内:

1. **处理地面站消息**（最多 5 条/周期）—— 配置指令统一「肯定 ACK」策略
   （`report=0` = DAV_NO_ERROR，`ack_count` 原值回传；`ack_count=0` 不回复）:

   **v1.7 拦截语义**：所有命令经 `_handle_config_command(msg_id, ack_count, apply_fn)` 处理——
   先由 `_ack_policy(msg_id)` 判定策略，**仅 normal 时执行 `apply_fn` 应用地面站设置的值**；
   silence（静默）不应用 + 不回复；fail/override（失败注入/命令 report 覆写）不应用 + 回复指定 report：
   - `SET_RADIO_REGULATORY_DOMAIN(0x0203)` → `apply_fn=_on_set_domain()` 更新 `_rf_params`
   - `SET_RADIO_ENCRYPT_KEY(0x0102)` → `apply_fn=_on_set_encrypt()` 更新 `_encrypt_type`/`_encrypt_key`/`_encrypt_iv`
   - `SET_RADIO_BUTTON_PARAM(0x0205)` → `apply_fn=_on_set_button()` 更新 `_button_param`
   - `SET_RADIO_RECEIVER_MODE(0x0111)` → `apply_fn=_on_set_receiver_mode()` 更新 `_receiver_mode`（v1.3）
   - `SET_RECEIVER_RC_AND_RADIO_PARAM(0x0119)` → `apply_fn=_on_set_receiver_rc_radio()` 更新 `_receiver_rc_radio`（v1.3）
   - `RADIO_SEND_RTCM(0x0100)` / `REMOTE_CONTROL_FREQ_MATCHING(0x0112)` → 无 apply_fn，仅回 ACK（v1.3）
   - `ASK_RADIO_ENCRYPT_KEY(0x0103)` → `_on_ask_encrypt_key()` 回复 `SEND_RADIO_ENCRYPT_KEY(0x0104)`；ACK 走策略（v1.4）
   - `ASK_RADIO_REGULATORY_DOMAIN(0x0201)` → `_on_ask_regulatory_domain()` 回复 `SEND_RADIO_REGULATORY_DOMAIN(0x0202)`；ACK 走策略（v1.4）
   - `ASK_HEARTBEAT(0x000E)` → 忽略（电台 2.5s 心跳已足够）
   - 其他未知命令 → 通用 fallback：带 `ack_count` 一律回复肯定 ACK（v1.3）

   > ⚠️ **update_ack 拦截时不应用状态**：`update_ack(silence_count/fail_count/cmd_result_*)` 命中时，
   > 电台**不执行 `_on_set_*` 状态赋值**（如不给 button_param 赋值），只按策略回复（或静默），
   > 心跳不回传地面站设置的新值——用于模拟电台无响应/处理失败的测试场景。

2. **定时心跳**:
   - 距上次心跳 >= 2.5s → `_send_heartbeat()`
   - 心跳内容: 设备信息 + 电池/温度 + GPS + 双频 RF 参数 + 加密类型 + 按键参数
     （v1.3: 按键参数编码 long_click_time / long_click_button_mode / short_click_button_mode 三字段；
      v1.4: GPS 位置编码为 double/fixed64，地面站可完整解析）

---

## 7. update_xxx 方法清单

> 以下方法属于 `_FakeRadioSender`（L1537），供 `SimulationPanel` 通过反射发现和调用。

| 方法名 | 行号 | 参数签名 | 委托到 | 说明 |
|--------|------|----------|--------|------|
| `update_ack` | L1722 | `fail_count=0, silence_count=0, cmd_result_enable=False, cmd_result_commands=None, cmd_result_values=None` | `FakeR2RadioStation._ack_policy`（v1.6 新增，对齐 fake_airplane.update_ack） | 配置所有 command 的 ACK 响应：静默（前 N 次不回复）/ 特定 command report 覆写 / 失败注入（前 N 次 report=4）；各 command 独立计数，10s 无消息自动重置。**v1.7：命中拦截（silence/fail/override）时不应用地面站设置值**（如 button_param/rf_params） |
| `update_battery` | L1743 | `percentage: int=None, voltage_mv: int=None, temperature: int=None` | `FakeR2RadioStation.set_battery()` | 更新电池百分比/PoE 电压/充电温度，下次心跳生效 |
| `update_gps` | L1749 | `latitude: float=None, longitude: float=None, altitude: float=None` | `FakeR2RadioStation.set_gps()` | 更新 GPS 位置，下次心跳生效 |
| `update_encrypt` | L1755 | `encrypt_type: int=None` | `FakeR2RadioStation.set_encrypt_type()` | 设置加密类型，仅非 None 时调用 |
| `update_rf_band` | L1760 | `band_key: str=None, mode: int=None, powers: list=None, min_freqs: list=None, max_freqs: list=None, temperature: int=None` | `FakeR2RadioStation.set_rf_band()` | 更新 RF 频段参数，仅 band_key 非 None 时调用 |
| `update_diff` | L1991 | `enable: bool=True, gps_signal: int=1, glonass_signal: int=1, galileo_signal: int=1` | `set_diff_enable()` + `set_diff_signal_state()` | **v1.9 新增** — 差分外发开关（上线后 1Hz 自动上报 RadioSendRtcm）+ RTCM 1005 帧卫星信号指示位 |

### 7.1 `update_rf_band` 的 band_key 取值

| band_key | 适用子型号 | RF 参数字典路径 |
|----------|-----------|-----------------|
| `"band_800m"` | R2 双频 (`SUB_DEVICE_R2_STATION=5`) | `_rf_params['band_800m']` |
| `"band_2400m"` | R2 双频 + R2G 单频 (`SUB_DEVICE_R2_2G4_V1=3`) | `_rf_params['band_2400m']` |

### 7.2 对应的底层 public setter

| FakeR2RadioStation 方法 | 行号 | 参数 | 修改属性 |
|--------------------------|------|------|----------|
| `set_encrypt_type()` | L1386 | `encrypt_type: int` | `_encrypt_type` |
| `set_rf_band()` | L1390 | `band_key, mode, powers, min_freqs, max_freqs, temperature` | `_rf_params[band_key]`, `_rf_800m_temperature`, `_rf_2400m_temperature` |
| `set_battery()` | L1412 | `percentage, voltage_mv, temperature` | `_battery_percentage`, `_poe_voltage_mv`, `_charge_temperature` |
| `set_gps()` | L1422 | `latitude, longitude, altitude` | `_gps_latitude`, `_gps_longitude`, `_gps_altitude` |

---

## 8. 与 integrated_gui.py 的交互

### 8.1 SimConfig 配置

在 `integrated_gui.py` 的 `_build_sim_configs()` (L1040-1188) 中，电台的 `SimConfig` 定义如下：

```python
SimConfig(
    key="radio",
    label="假电台",
    source_file=Path(".../fake_radio.py"),
    sender_cls=_FakeRadioSender,
    mgr_cls=_FakeRadioSenders,
    transport_cls=FakeR2RadioStation,
    mgr_senders_attr="radio_senders",    # → mgr.radio_senders
    mgr_transports_attr="radios",        # → mgr.radios
    aid_prefix="FR_",
    known_param_types={
        "count": "int", "start_device_id": "int", "start_ip": "str",
        "sub_device_type": "int", "dgcs_ip": "str", "interface": "str",
        "percentage": "int", "voltage_mv": "int", "temperature": "int",
        "latitude": "float", "longitude": "float", "altitude": "float",
        "encrypt_type": "int", "band_key": "str", "mode": "int",
        "powers": "list_int", "min_freqs": "list_int", "max_freqs": "list_int",
    },
    param_defaults={
        "count": 1, "start_device_id": 1, "start_ip": FAKE_RADIO_IP,
        "sub_device_type": SUB_DEVICE_R2_STATION, "dgcs_ip": DGCS_IP,
        "interface": NETCARD_INTERFACE,
    },
)
```

### 8.2 反射链路

```
SimulationPanel("radio").__init__()
  │
  ├── _parse_source(config.source_file)   ← AST 解析 fake_radio.py
  │     → 提取 module_constants:
  │         FAKE_RADIO_IP, DGCS_IP, DAV_PORT, NETCARD_INTERFACE,
  │         RADIO_BASE_ADDR, GROUND_ADDR, ONLINE_DEVICE_TYPE_RADIO_STATION,
  │         SUB_DEVICE_R2_STATION, 等
  │     → 提取 init_attrs: 来自 _FakeRadioSender / FakeR2RadioStation 的 __init__
  │
  ├── _discover_update_methods(_FakeRadioSender)
  │     → 发现 4 个方法:
  │         update_battery(percentage, voltage_mv, temperature)
  │         update_gps(latitude, longitude, altitude)
  │         update_encrypt(encrypt_type)
  │         update_rf_band(band_key, mode, powers, min_freqs, max_freqs, temperature)
  │
  └── _discover_add_params(_FakeRadioSenders)
        → 提取 __init__ 参数: count, start_device_id, start_ip,
          sub_device_type, dgcs_ip, interface, log_manager
```

### 8.3 运行时关键交互点

| 交互点 | integrated_gui.py 位置 | 本模块对应位置 | 说明 |
|--------|----------------------|---------------|------|
| **基础参数写入** | `SimulationPanel._on_basic_apply_clicked()` (L1649) | 模块级常量 (L35-46) | GUI 修改 `fake_radio.py` 模块常量（如 `FAKE_RADIO_IP`）并写回源文件 |
| **添加设备** | `SimulationPanel._on_add_clicked()` (L1668) | `_FakeRadioSenders.__init__()` (L1247) | 创建 `mgr = _FakeRadioSenders(**kwargs)` |
| **Socket 拦截** | `SimulationPanel._patch_transport_socket()` (L1971) | `FakeR2RadioStation.sock` (L625) | 替换 `transport.sock` 为 `_SocketInterceptor`，拦截 recvfrom 回调 |
| **上线/下线** | `SimulationPanel._start_sender_thread()` (L1776) | `_FakeRadioSender._run()` (L1191) | 确保网络/UDP 后调用 `_radio._run()` |
| **应用 update** | `SimulationPanel._on_apply_clicked()` (L1811) | `_FakeRadioSender.update_xxx()` (L1212-1236) | 调用对应 update 方法 |
| **停止** | `SimulationPanel.shutdown()` | `_FakeRadioSender.stop()` (L1202) → `FakeR2RadioStation.stop()` (L795) | 线程停止 + socket 关闭 |
| **批量停止** | `SimulationPanel._on_offline_all_clicked()` | `_FakeRadioSenders.stop()` (L1279) | 遍历所有 sender.stop() |

### 8.4 消息注入链路

> **v1.1 修复** (2026-07-31): `_patch_transport_socket` 原先无法检测电台的嵌套 socket
> (`transport._radio.sock`)，导致 `_SocketInterceptor` 从未安装到电台。修复后方法会
> fallback 到 `_radio.sock`，并将拦截器正确写入 `radio.sock`（而非 `transport.sock`）。
>
> **v1.2 修复** (2026-08-18): 补齐外发方向与 DAV 解析。
> (1) `_SocketInterceptor` 增加 `sendto` 拦截，电台心跳/注册/ACK 外发帧也进入监控；
> (2) `inject_raw_message` 对 0xA5 帧分流到 `MonitorController.inject_radio_packet()`，
>     走 `RadioDavParser`（source_type="radio"），不再被 MAVLink 魔数检查丢弃；
> (3) gcs 地址改从 `_radio.dgcs_ip`/`_radio.port` 读取（`_FakeRadioSender` 包装器无此属性）。
>
> **v1.3 修复** (2026-08-19): (1) gcs 地址**固定**为 `172.16.200.1:14555`（地面站标准地址，
> 不再随电台实例 `dgcs_ip`/`port` 配置变化，保证监控显示恒定）；(2) 电台消息配置改读
> `src/Protocol/radio/MessageDefineUAV.xml`（69 条权威消息表）；(3) 配置指令处理完善
> （见 §6.3 肯定 ACK 策略 + 外发字段更新）。
>
> **v1.5 修复** (2026-08-19): 电台消息注入改由 ``_FakeRadioSender.set_msg_injector``
> 自包装完成——假电台 socket 在 ``_run``→``_udp_setup`` 才创建（延迟创建），原先
> ``_patch_transport_socket`` 在添加设备时遇到 ``sock=None`` 直接 return，导致拦截器
> 装不上：接收消息不进监控（log 有但界面无）、外发消息只走 UDP 监听路径（dst=0.0.0.0）。
> 新增内部 ``_RadioSocketInterceptor``，``_FakeRadioSender`` 在 socket 就绪后自动自包装，
> 收发数据经回调注入监控；``_patch_transport_socket`` 对电台不再安装 ``_SocketInterceptor``。

```
接收方向（地面站 → 电台）:
  FakeR2RadioStation._udp_recv()
    ↓ 通过被拦截的 sock.recvfrom()
  _RadioSocketInterceptor.recvfrom()                  (fake_radio.py)
    ↓ _on_recv → self._msg_injector(data, gcs_ip, gcs_port, dst_ip, dst_port)

外发方向（电台 → 地面站）:
  FakeR2RadioStation._udp_send()
    ↓ 通过被拦截的 sock.sendto()
  _RadioSocketInterceptor.sendto()                    (fake_radio.py)
    ↓ _on_send → self._msg_injector(data, dst_ip, dst_port, gcs_ip, gcs_port)

  （统一由 _FakeRadioSender.set_msg_injector 在 sock 就绪后自包装，
    处理 socket 延迟创建；_patch_transport_socket 对电台不再拦截）

  SimulationPanel.set_message_injector / _on_add_clicked
    ↓ sender.set_msg_injector(callback)
  IntegratedMainWindow 闭包                           (_window.py)
    ↓ self._udp_panel.inject_raw_message(...)
  FullUdpMonitorPanel.inject_raw_message()            (_monitor.py)
    ├─ 0xA5 头 → _ctrl.inject_radio_packet() → RadioDavParser.to_message_record()
    └─ 其他   → _ctrl.engine._process_raw_packet(...)
  MonitorEngine / RadioDavParser → MonitorModel → 50ms QTimer → UI
```

### 8.5 关键注意事项

1. **radio_senders 和 radios 是同一批对象**: `SimConfig` 中 `mgr_senders_attr="radio_senders"` 和 `mgr_transports_attr="radios"` 指向两个列表，但两个列表包含完全相同的 `_FakeRadioSender` 对象。`SimulationPanel` 的 `_senders` 和 `_transports` 因此也指向同一批对象。
2. **_FakeRadioSender 兼任 sender+transport**: 与 airplane/nest 不同（它们有独立的 sender 和 transport 类），电台的 sender 和 transport 是同一个 `_FakeRadioSender` 实例。
3. **网络初始化延迟**: `_FakeRadioSender._run()` (L1191) 会先检查 `_radio.sock is None`，如果是则调用 `_setup_network()` 和 `_udp_setup()`。这是因为 GUI 的 `_start_sender_thread` 直接调用 `_run()` 而非 `start()`。
4. **无嵌套设备**: 与 nest 不同，radio 没有 `_NestedDeviceBase` 子类，因此 `SimulationPanel` 不会为其创建 `NestedDevicePanel`。
5. **Socket 拦截走 _radio.sock** (v1.1): `_FakeRadioSender` 自身没有 `sock` 属性，真实的 socket 在 `_radio.sock`（`FakeR2RadioStation`）。`_patch_transport_socket()` 已适配此嵌套路径，拦截器直接写入 `_radio.sock`。
6. **下线状态以线程存活为准** (v1.1): `SimulationPanel._is_sender_online()` 以线程 `is_alive()` 为准而非 `running` flag，避免关闭过程中状态误报。
7. **外发帧走 sendto 拦截** (v1.2): 电台的心跳/EnrollRequest/ACK 通过 `FakeR2RadioStation._udp_send → sock.sendto()` 发送，`_SocketInterceptor` 已新增 `sendto` 拦截（`on_send`），`_patch_transport_socket` 对电台安装 `on_send` 回调（src/dst 反转）。send 拦截仅对电台启用，假飞机/机巢不受影响。
8. **监控 gcs 地址固定** (v1.3): 电台消息在 UDP 监控中，地面站一侧地址恒为 `172.16.200.1:14555`（接收方向 src / 外发方向 dst），不随电台实例的 `dgcs_ip`/`port` 配置变化。

---

## 9. 修改指南

> **核心原则**: 修改代码后，在本文档对应 section 更新行号和描述。

### 场景 1: 新增一个 DAV 消息类型（如新的地面站命令）

1. 在 `MessageID` 类 (L130) 添加新的消息 ID 常量
2. 如需回复 protobuf，在 Protobuf 编码区 (L124-437) 添加对应的 `build_xxx()` 函数
3. 在 `FakeR2RadioStation._handle_incoming()` (L1066) 添加 `elif msg_id == MessageID.XXX:` 分支
4. 添加对应的 `_on_xxx()` 处理方法（参考 `_on_set_encrypt`/`_parse_proto_fields` 的解析模式）
5. 更新本文档 §2.3/§4.2/§6.3

### 场景 2: 新增一个 update_xxx 方法供 GUI 调用

1. 在 `FakeR2RadioStation` (L1285-1333) 添加 public setter 方法
2. 在 `_FakeRadioSender` (L1456-1480) 添加对应的 `update_xxx()` 方法（委托到 setter）
3. 在 `integrated_gui.py` 的 `SimConfig("radio").known_param_types` (L1040+) 添加新参数的类型声明
4. `SimulationPanel._discover_update_methods()` 会自动发现新的 `update_xxx` 方法
5. 更新本文档 §7

### 场景 3: 修改心跳内容（如增加新字段）

1. 在 `FakeR2RadioStation.__init__()` (L599) 添加新的内部属性
2. 在 `build_heartbeat()` (L215) 添加新字段的 protobuf 编码
   - 修改 `RadioStationR2HeartBeatExtend` 扩展消息（`ext` bytearray, L273-316）
   - 使用正确的 `_proto_field_xxx()` 编码
3. 在 `_send_heartbeat()` (L882) 的 `kwargs` 中添加新字段
4. 更新本文档 §2.3/§4.2

### 场景 4: 修改默认配置常量（如 IP、端口）

1. 直接修改模块级常量 (L39-46)
2. `SimulationPanel._on_basic_apply_clicked()` 也会通过 `setattr` 写回这些值
3. 更新本文档 §2.1

### 场景 5: 新增子型号支持（如新频段）

1. 在常量区 (L146-148) 添加新的 `SUB_DEVICE_XXX` 常量
2. 修改 `_build_default_rf()` (L653) 添加新子型号的 RF 参数默认值
3. 如需新频率范围，在 `build_heartbeat()` (L215) 中添加新频段的编码逻辑
4. 在 `SimConfig.param_defaults` 中更新 `sub_device_type` 的可选值
5. 更新本文档 §2.2/§2.3/§4.2

### 场景 6: 修改编解码器（如修改帧格式或 CRC）

1. 定位 `DavLink2Codec` 类 (L375-551)
2. 确认修改与 C# DavLink2 源码 (DavLink.cs:164-315) 保持一致
3. 特别注意:
   - `encode_msg()` (L406) / `encode_ack()` (L447) 的字节布局
   - `_put_source_addr()` (L476) / `_put_dest_addr()` (L490) 的 52-bit 地址编码
   - `decode()` (L508) 的 `data_len` 解析公式（`data[2] + ((data[3] & 0x3F) << 8)`）
4. 更新本文档 §5

### 场景 7: 排查电台无法上线的问题

1. 检查 `_setup_network()` (L702) 是否成功：IP 是否在本机接口上存在
2. 检查 `_udp_setup()` (L728) 是否成功：socket 是否正确绑定
3. 检查注册流程 `_do_enroll()` (L841)：EnrollRequest 是否发送、EnrollReply 是否在 5s 内收到
4. 检查 DAV 地址是否正确：`device_addr = RADIO_BASE_ADDR + device_id`
5. 使用 Wireshark 抓包 `UDP port 14555`，验证帧格式

### 场景 8: 排查 GUI 面板中电台状态不更新的问题

1. 检查 `SimulationPanel._refresh_device_list()` (L1865) 中 `_is_sender_online()` 是否正确读取 `running` 和 `thread` 状态
2. 检查 `_FakeRadioSender` 的属性委托是否正确（`running`, `thread` 等 property）
3. 检查 `SimulationPanel._patch_transport_socket()` 是否成功替换 `transport.sock`
4. 检查 `_SocketInterceptor.recvfrom()` 是否拦截到数据
5. 参考 §8.4 消息注入链路完整路径

---

> **更新记录**:
> - 2026-09-08: v1.9 — **实现差分源上报（技术方案 §11）+ update_diff + 监控解析 0x0100**。①`fake_radio.py` 新增模块级 RTCM3 工具：`_crc24q`（CRC-24Q 0x1864CFB）、`_rtcm_pack_bits`/`_build_rtcm_frame`（0xD3+10-bit 长度+payload+CRC）、`build_rtcm1005`（基准站 ARP 帧，位布局 DF002(12)+DF003(12)+DF021(6)+DF022/23/24 信号指示位(1×3)+DF001(1)+DF025(1)+DF141(2)+DF011/12/13 坐标(38×3)=151bit→19B，白名单帧）、`build_rtcm1124`（BDS MSM4 链路模拟帧，掩码全零→20B，白名单帧）、`pack_single_bytes`/`unpack_single_bytes`（SingleBytes 包装 0x0A+varint，§11.2.2）、`rtcm_summarize`（帧消息号摘要，提取算法对齐地面站 RTCM32.cs）。②`FakeR2RadioStation` 差分源：类常量 `DIFF_START_DELAY=10.0`（§11.2.4 地面站转发定时器 10s 后才启动）、`DIFF_INTERVAL=1.0`（1Hz，判活 ≥1 帧/2s）；`__init__` 新增 `_diff_enable=True`（上线自动外发）/_diff_signal_state=(1,1,1)/_last_diff/_online_since；`set_diff_enable`/`set_diff_signal_state`（1005 帧 DF022/23/24 卫星信号指示位）；`_run` 在线后记录 `_online_since` 并每拍调 `_tick_diff`（≥10s 起按 1Hz 调 `_send_diff`：RTCM(1005+1124)→SingleBytes→`encode_msg(RADIO_SEND_RTCM, ackCount=0)`→UDP，上行无需 ACK）。③`_FakeRadioSender.update_diff(enable, gps_signal, glonass_signal, galileo_signal)`（GUI AST 反射自动发现，enable→bool 下拉/信号位→QSpinBox，零 GUI 代码）。④监控侧 `radio_parser.py`：`_KNOWN_FIELDS` 补 0x0100→{1:"msg"}（删除后部旧 "rtcm_data" 重复定义）；MSG 帧方向改为按 DAV 源地址判断（源=电台地址→Tx，修正上下行共用 0x0100 的静态方向失真；心跳测试帧构造同步真实化为电台源地址）；0x0100 消息名附 RTCM 摘要（如 `RADIO_SEND_RTCM[RTCM 1005,1124]`）。新增 `tests/test_radio_diff.py` 15 用例 + e2e `tests/_e2e_verify_radio_diff.py` 16 断言（真实回环注册→上线→首拍 11.1s→1Hz 3 拍→监控解析→GUI 停发），全套 399 测试通过
> - 2026-08-21: v1.8 — 适配 0x00 消息两种解析方式（radio_parser/controller，监控侧）：Msg 帧 0x00 = GET_FIRMWARE_VERSION（protobuf，`UniversalCommand{command}`）；Ack 帧 = report 直接解析（UInt32 LE）。`MessageRecord` 新增 `dav_report`，`to_message_record` 存入 Ack report，`controller._parse_radio_fields` 按 msg_type 区分（Ack→`parse_ack_report` 显示 report；Msg→protobuf 显示 command）。新增 `tests/test_radio_dual_format.py` 7 个用例；全套 253 测试通过
> - 2026-08-20: v1.7 — 修复 update_ack 拦截时仍应用地面站设置值：原 `_handle_incoming` 先 `_on_set_xxx(payload)` 再 `_send_ack` 判定策略，导致静默/失败注入/命令覆写命中时地面站的值（如 button_param）仍被赋值并回传心跳。重构：(1) 新增 `_ack_policy(msg_id)`（§2.5）判定策略返回 (action, report)；(2) `_send_ack(ack_count, report)` 改为仅发帧；(3) 新增 `_handle_config_command(msg_id, ack_count, apply_fn)`，**仅 normal 时执行 `apply_fn` 应用地面站值**，silence 不应用+不回复、fail/override 不应用+回复指定 report（§6.3）；(4) 行号全量同步（1846 → 1866 行）。新增 `tests/test_radio_ack.py` 5 个拦截语义用例；全套 246 测试通过
> - 2026-08-20: v1.6 — (1) 修复 ACK 帧在 UDP 监控中误命名：`RadioDavParser.to_message_record` 对 ACK 帧（msg_type=1）优先命名 `Radio_ACK(ack=N)`、方向 Tx（原 msg_id=0 被 proto 配置映射为 GET_FIRMWARE_VERSION）；(2) **新增 `_FakeRadioSender.update_ack`**（§7，对齐 fake_airplane.update_ack）：静默（silence_count）/ 特定 command report 覆写（cmd_result_*）/ 失败注入（fail_count，前 N 次 report=4），`FakeR2RadioStation._send_ack` 增加 `msg_id` 参数按优先级应用（§2.5）；(3) 行号全量同步（1744 → 1846 行）
> - 2026-08-19: v1.5 — 修复假电台收发消息不进 UDP 监控（socket 延迟创建导致拦截器装不上）：(1) 新增 `_RadioSocketInterceptor`（§2.6）；(2) `_FakeRadioSender` 新增 `set_msg_injector`/`_wrap_sock`，`_run` 中 socket 就绪后自动自包装（§2.6/§8.4），接收消息进监控、外发消息 dst=地面站 172.16.200.1:14555；(3) 行号全量同步（1660 → 1744 行）
> - 2026-08-19: v1.4 — 依据技术方案 + `DavMessage.proto` 重构消息模块（不参考 DavMessage.cs）：(1) **修复 GPS 编码 bug**——`rtkStationPosition` 的 lat/lon/alt 在 proto 中为 `double`（wire_type 1/fixed64），原实现用 fixed32×1e7 导致地面站解析心跳 GPS 全为 0；新增 `_proto_field_fixed64`（§2.3），`build_heartbeat` 改编码 double 原始位（§2.3/§6.3）；(2) **查询指令交互**——MessageID 新增 0x0103/0x0104/0x0201/0x0202，新增 `build_send_encrypt_key`/`build_send_regulatory_domain`（§2.3）与 `_on_ask_encrypt_key`/`_on_ask_regulatory_domain`（§2.5），`ASK_RADIO_ENCRYPT_KEY`→`SEND_RADIO_ENCRYPT_KEY`、`ASK_RADIO_REGULATORY_DOMAIN`→`SEND_RADIO_REGULATORY_DOMAIN`（§6.3）；`_on_set_encrypt` 补记录 key/iv；(3) 行号全量同步（1559 → 1660 行）
> - 2026-08-19: v1.3 — (1) §8.4/§8.5 监控 gcs 地址固定 172.16.200.1:14555；(2) 配置指令肯定 ACK 策略 + 外发字段更新（§2.3 MessageID 扩展 0x0111/0x0112/0x0119、新增 `_parse_proto_fields`/`_parse_packed_varints`/`_parse_rfparameters`；§2.5 新增 `_on_set_receiver_mode`/`_on_set_receiver_rc_radio`，`_on_set_domain`/`_on_set_encrypt`/`_on_set_button` 完整解析；§6.3 通用 fallback 肯定 ACK；`build_heartbeat`/`_send_heartbeat` 支持 button_param 全字段）；(3) 行号全量同步（1316 → 1559 行）
> - 2026-08-18: v1.2 — 修复假电台收发消息未注入监控：(1) §8.4 新增外发 sendto 拦截与 DAV 分流（`inject_radio_packet`）；(2) §8.5 新增注意事项 #7；(3) gcs 地址改从 `_radio.dgcs_ip`/`_radio.port` 读取
> - 2026-07-31: v1.1 — 更新 §8.4 消息注入链路（修复电台嵌套 sock 检测），§8.5 新增注意事项 #5、#6
> - 2026-07-23: 初始版本，基于 `fake_radio.py` (1316 行) 创建
