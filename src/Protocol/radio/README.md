# protocol.radio — DAV 电台/接收机协议工具包

基于 DAV 协议的电台通信库，支持串口和 UDP 两种传输方式。

## 架构

```
RadioConfig / RadioConfigUdp     ← 同步 API（上下文管理器）
├── RadioSerialProtocol          ← 串口传输
└── RadioUdpProtocol             ← UDP 网口传输
    └── BaseRadioProtocol        ← 传输无关基类（请求-响应、设备发现、帧分发）
        ├── DavProtocol          ← DAV 帧编解码（CRC、加密、状态机）
        └── DavPayload           ← protobuf 编解码（XML 元数据 + pb2 模块）
```

## 快速开始

**串口：**

```python
from protocol.radio import RadioConfig

with RadioConfig() as rc:
    rc.connect("COM3", 460800)
    print(rc.get_firmware_version())       # "1.0.1.0"
    print(rc.get_radio_encrypt_key())      # {"encrypt_type": 0}
    rc.set_radio_encrypt_key(encrypt_type=1, encrypt_key=b'...', encrypt_iv=b'...')
```

**UDP 网口：**

```python
from protocol.radio import RadioConfigUdp

with RadioConfigUdp() as rc:
    rc.connect("172.20.0.76", 14555, local_port=14555)
    print(rc.get_firmware_version())
    print(rc.format_heartbeat())
```

## 主要类

| 类 | 文件 | 说明 |
|---|---|---|
| `DavProtocol` | `dav_protocol.py` | DAV 协议帧编解码，CRC/Enigma/AES 加解密，接收状态机 |
| `DavPayload` | `dav_payload.py` | 基于 XML 消息定义和 pb2 模块的 protobuf 编解码 |
| `BaseRadioProtocol` | `radio_serial_protocol.py` | 传输无关基类，请求-响应同步、ACK 等待、设备发现、帧分发 |
| `RadioSerialProtocol` | `radio_serial_protocol.py` | 串口实现，提供 `connect(port, baud)` / `disconnect()` |
| `RadioUdpProtocol` | `radio_udp_protocol.py` | UDP 实现，ENROLL 上线握手，`connect(host, port)` |
| `RadioConfig` | `radio_config.py` | 串口同步 API，上下文管理器，常用方法封装 |
| `RadioConfigUdp` | `radio_config.py` | UDP 同步 API，与 `RadioConfig` 相同的方法签名 |

## 工具函数

```python
from protocol.radio.radio_serial_protocol import list_serial_ports
from protocol.radio import RadioConfig, format_heartbeat

# 列出可用串口
for dev, desc in list_serial_ports():
    print(dev, desc)

# 离线格式化心跳数据
hb_data = {"device_type": 1, "firmware_running_status": "normal", ...}
print(format_heartbeat(hb_data))
```

## 依赖

- `pyserial` — 串口通信
- `protobuf` — protobuf 编解码
- `pycryptodome`（可选）— AES 加密支持

## 目录结构

```
protocol/radio/
├── __init__.py               # 统一导出
├── dav_protocol.py           # DavProtocol, AddressRole, MessageType, EncryptType
├── dav_payload.py            # DavPayload — XML 解析 + protobuf 编解码
├── radio_serial_protocol.py  # BaseRadioProtocol + RadioSerialProtocol + 工具函数
├── radio_udp_protocol.py     # RadioUdpProtocol
├── radio_config.py           # RadioConfig + RadioConfigUdp + format_heartbeat()
├── dav_frame_parser.py       # DAV 帧解析 CLI 工具
├── MessageDefineUAV.xml      # 消息定义（自包含）
├── MessageDefineUAVC_pb2.py  # protobuf 编译产物（自包含）
└── README.md
```

整个目录自包含，复制到任意项目即可使用，无需外部依赖文件。
