# Dmd_Autotest_Project

## 无人机自动化测试框架

基于 Pytest + Allure 的多机型、多协议无人机自动化测试框架，覆盖飞控串口/网络通信、Web 云平台、桌面地面站、WiFi 模块、编队算法、**S100 底软 BSP（INDV1）**等测试场景。

### 核心特性

- **多设备支持**：V3 / V4 / V41 / L3 / X1 / INDV1 / Swarm_Painter / Wifi_Module / Radio 等机型，以及 Cloud_Platform_Api / Cloud_Platform_Ui / Ground_Station / MavLink 等非机型测试
- **底软 BSP 测试**（INDV1/S100）：业务主流程冒烟 + CPU/DDR/IPC 测试点，SSH 跳板免密控制，断言失败自动经 adb 导出板端日志
- **三层架构**：物理层 (Physical) → 协议层 (Protocol) → 脚本层 (Script)，职责分离
- **五类测试套件**：Release_Testing / Change_Testing / Functional_Testing / Performance_Testing / Unit_Module_Testing
- **Allure 报告**：可视化报告、历史趋势、日志附件
- **配置驱动**：通过 `config.json` 统一管理设备参数和测试计划
- **CI/CD 集成**：支持 Jenkins，命令行参数驱动
- **失败重试**：pytest-rerunfailures 自动重试

---

## 环境搭建

- **Python 版本**：Python 3.10.11
- **推荐 IDE**：PyCharm / VSCode
- **操作系统**：Windows / Linux / macOS

### 安装步骤

```bash
# 1. 克隆项目
git clone <repository-url>
cd dmd_autotest_project

# 2. 创建并激活虚拟环境
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/Mac

# 3. 安装依赖
pip install -r requirements.txt
```

### TSMaster 前置依赖（CAN/CAN FD 测试仪器，可选）

`TSMaster`（同星 TOSUN）作为 CAN/CAN FD **测试仪器**，通过 `src/Physical/TSMaster/`（`TSMasterController`）+ `src/Protocol/tsmaster/`（`CanProtocol`）调用，用于测试 V4 / X1 / L3 / V41 等机型的总线通信。属机器级一次性前置依赖：

1. **在运行测试的机器上正式安装 TSMaster**（官方安装包），安装器会装好 `bin64` 运行时、CAN 硬件驱动、注册表与授权。TSMaster 运行时约 700MB + 商业授权，**无法内嵌进 git 仓库**。
2. Python 侧**无需 TSMaster 自带的 Python 3.11.8**：`src/Physical/TSMaster/tsmaster_loader.py` 从 `bin64_path` 参数或注册表定位 `TSMaster.pyd`，用工程统一 `.venv`（Python 3.10.11，已验证可加载）加载运行时。
3. 通道映射通过 `TSMasterController.set_mapping(...)` 配置，或在 TSMaster 上位机预配后保存。

> 用法示例见 `TSMasterController` / `CanProtocol` 的 docstring，及 `docs/TSMaster_Python_API.md` 的 API 参考。

---

## 项目结构

```
dmd_autotest_project/
├── main.py                      # 程序入口，解析 CLI 参数并执行 pytest
├── conftest.py                  # 全局 pytest 命令行参数注册
├── config.json                  # 全局配置文件
├── pytest.ini                   # Pytest 配置
├── requirements.txt             # Python 依赖
├── jenkins_build_script.bat     # Jenkins 构建脚本
│
├── src/
│   ├── Physical/                # 物理层 — 硬件通信接口
│   │   ├── Serial/              #   串口通信 (SerialPortController: 帧格式可配 7/8N1E/O/1/2; UartPortController: 被测数据口)
│   │   ├── Udp/                 #   UDP 网络通信
│   │   ├── App/                 #   DLL/Swarm Painter 算法接口
│   │   ├── WebBase/             #   Web API/UI 基类 (APIBase, UIBase)
│   │   ├── Dgcs/                #   地面站 UI 自动化
│   │   ├── Nest/                #   机巢 SSH/SFTP/ADB/Serial 控制器
│   │   ├── Telnet/              #   Telnet 远程控制
│   │   ├── SwarmPainter/        #   Swarm Painter 应用控制
│   │   └── TSMaster/            #   同星 CAN/CAN FD 总线 (TSMasterController)
│   │
│   ├── Protocol/                # 协议层 — 通信协议封装（按业务域划分）
│   │   ├── airplane/                  # 飞机嵌入式协议
│   │   │   └── Serial_Protocol_Lite.py     # 串口协议处理器（核心）
│   │   ├── dmdtest_uart/              # MCU 底软 UART 测试协议 (dmdtest_uart 命令集)
│   │   │   ├── order_ary.py                # OrderAry 伪随机数据模型 (比对基准)
│   │   │   ├── protocol.py                 # 命令-应答三行同步协议 / stat 解析
│   │   │   ├── session.py                  # 被测串口会话管理 (open/close/switch)
│   │   │   ├── measure.py                  # 吞吐量/CPU 差分/统计查询/长度遍历
│   │   │   └── inject.py                   # 错误注入与溢出探测
│   │   ├── icat/                      # iCAT LED 分析仪
│   │   │   └── Icat_Led_Analyser.py        # LED 灯效分析
│   │   ├── mavlink/                   # MAVLink 协议栈（解析/模拟飞机/GCS）
│   │   ├── rtcm/                      # RTCM/RTK 协议
│   │   ├── radio/                     # DAV Radio 协议栈
│   │   ├── wifi/                      # WiFi 模块协议 (wifi.py 1110 行)
│   │   ├── web/                       # Web 云端协议
│   │   │   ├── Web_API.py                  # Web API 协议
│   │   │   └── Web_UI.py                   # Web UI 协议
│   │   ├── dgcs/                      # 地面站协议
│   │   │   ├── Dgcs_Ui.py                  # DGCS UI 自动化
│   │   │   └── dgcs_business.py            # DGCS 业务逻辑
│   │   ├── drama/                     # 剧本编辑器 SP/Maya 协议
│   │   │   ├── DLL.py                      # 算法 DLL 封装
│   │   │   ├── SwarmPainter.py             # Swarm Painter 应用控制
│   │   │   ├── common/                     # 公共工具（com_class/com_func/com_math/...）
│   │   │   └── drone_show/                 # 剧本数据读写（drama/dat/drm）
│   │   ├── tsmaster/                  # 同星 CAN/CAN FD 协议 (CanProtocol)
│   │   ├── google/                    # Protobuf 运行时
│   │   └── image/                     # 图像资源
│   │
│   └── Script/                   # 脚本层 — 测试用例
│       ├── Drone_Show/
│       │   ├── conftest.py            # ★ 共享 fixtures（串口/UDP/MavLink）
│       │   ├── V4/                    # V4 机型 (5 套件)
│       │   ├── V41/                   # V41 机型 (V4 升级版,目录结构与用例和 V4 保持一致)
│       │   ├── V3/                    # V3 机型 (占位,未实现)
│       │   ├── L3/                    # L3 机型
│       │   ├── X1/                    # X1 机型 (占位,未实现)
│       │   ├── Swarm_Painter/         # 编队算法测试 (DLL)
│       │   ├── SwarmPainter_Ui/       # Swarm Painter 桌面 UI 测试
│       │   ├── Wifi_Module/           # WiFi 模块测试
│       │   ├── Nest_Module/           # 机巢测试 (10 用例,自带 conftest)
│       │   ├── Cloud_Platform_Api/    # 云平台 API 测试
│       │   ├── Cloud_Platform_Ui/     # 云平台 UI 测试
│       │   ├── Ground_Station/        # 地面站 DGCS 测试
│       │   ├── MavLink/               # MAVLink 版本对比
│       │   └── Radio/                 # Radio 模块测试
│       └── Drone_Applications/
│           ├── RDKS100/               # S100 开发板 (Linux 底软) — Jenkins: BSP_APP + BoardType=RDKS100
│           │   └── Functional_Testing/                 #   标准五套件口径
│           │       ├── conftest.py                     #   ssh/board_info/bsp_params/adb日志 fixtures
│           │       └── test_indv1_linux_bsp_s100_*.py  #   flow/CPU/DDR/IPC (27 用例)
│           └── hope_stm32h743vit6/    # h743 公共开发板 (MCU 底软) — Jenkins: BSP_APP + BoardType + UART
│               └── UART/                              #   总线套件口径
│                   ├── conftest.py                    #   Shell 串口生命周期/板段 fail-fast/uart_args
│                   ├── test_uart_send.py              #   发送功能 21 点 (飞书行2-22)
│                   ├── test_uart_recv.py              #   接收功能 19 点 (行23-41)
│                   ├── test_uart_duplex.py            #   全双工 7 点 (行42-48)
│                   ├── test_uart_loop.py              #   环路测试 2 点 (行49-50)
│                   ├── test_uart_stat.py              #   统计功能 8 点 (行51-58)
│                   ├── test_uart_baud.py              #   波特率设置 6 点 (行59-64)
│                   ├── test_uart_random.py            #   随机测试 10 点 (行65-74)
│                   └── test_uart_error.py             #   异常处理 6 点 (行75-80)
│
├── utils/                        # 工具库
│   ├── common.py                 #   共享函数 (get_project_root, load_config)
│   ├── logger.py                 #   日志管理 (LogManager + Allure 附件)
│   ├── airtest_report.py         #   Airtest+Allure 报告集成 (copy_dir/rmdir/copy_result_html/...)
│   ├── web_cloud.py              #   云平台辅助 (验证码, 测试数据)
│   ├── assert_helper.py          #   断言辅助
│   ├── screen_recorder.py        #   录屏工具
│   └── text_color.py             #   截图辅助 (capture_control_screenshot)
│
├── tools/                        # 外部二进制工具与独立脚本
│   ├── serial_console/          #   板端调试串口工具 (probe 探针 / login 登录执行 / listen 监听存档)
│   ├── x1_params/               #   X1 参数默认值批量写入 (set_test_params.py, 独立小工具)
│   ├── simulation_gui/          #   假飞机/机巢/电台仿真 GUI (自带 README)
│   ├── dgcs-performance-test/   #   ⚠ 独立子项目 — DGCS 压测工具 (源码 + EXE + build.bat)
│   ├── iperf2.0.14/ platform-tools-adb/ java-agent/ ...   # 二进制工具与安装包目录
├── docs/                         # 项目文档 (TSMaster_Python_API.md 等)
├── file/                         # 测试数据 (Excel, drama, DAT 等)
├── firmware/                     # 固件文件
├── logs/                         # 运行日志
├── allure-results/               # Allure 结果 (临时)
├── allure-report/                # Allure 报告
└── allure-2.35.1/                # Allure 命令行工具
```

### 独立子项目 (不参与 pytest 收集)

- **`tools/dgcs-performance-test/`** — DGCS 地面站压力测试工具。完整自带 `requirements.txt` / `build.bat` / PyInstaller 打包 EXE，仅依赖 `config.json` 的 `Ground_Station` 配置段，与 `src/` 完全解耦。详细说明见该目录的源码注释。

---

## 快速开始

```bash
python main.py --device_type <设备类型> --test_suites <测试套件> [--mavlink_version <版本>]
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--device_type` | 是 | 设备类型，如 `V4`、`L3`、`Cloud_Platform_Api` |
| `--test_suites` | 是 | 测试套件，如 `Release_Testing`、`Functional_Testing` |
| `--mavlink_version` | 否 | MAVLink 版本号，默认从 config.json 读取 (41) |

**示例**：

```bash
# 机型测试
python main.py --device_type V4 --test_suites Release_Testing
python main.py --device_type V41 --test_suites Release_Testing
python main.py --device_type L3 --test_suites Functional_Testing

# 非机型测试
python main.py --device_type Cloud_Platform_Api --test_suites Release_Testing
python main.py --device_type Ground_Station --test_suites Release_Testing
python main.py --device_type Wifi_Module --test_suites Release_Testing

# Swarm Painter
python main.py --device_type Swarm_Painter --test_suites Release_Testing

# 底软 BSP (Linux) / MCU 底软 UART — 见下方 BSP_APP 章节
python main.py --device_type INDV1 --test_suites Functional_Testing
python main.py --device_type hope_stm32h743vit6 --test_suites UART

# 指定 MAVLink 版本
python main.py --device_type V4 --test_suites Release_Testing --mavlink_version 39
```

### 查看报告

```bash
# 生成并查看 Allure 报告
allure generate ./allure-results -o ./allure-report --clean
allure open ./allure-report

# 或直接启动服务
allure serve ./allure-results
```

---

## 架构设计

```
┌──────────────────────────────────────────┐
│          脚本层 (Script)                  │
│  测试用例 + conftest fixtures            │
│  调用协议层 API，断言结果                 │
└────────────────┬─────────────────────────┘
                 │
┌────────────────▼─────────────────────────┐
│          协议层 (Protocol)                │
│  airplane/ — 飞机嵌入式                   │
│    Serial_Protocol_Lite                  │
│  icat/    — iCAT LED 分析仪              │
│    Icat_Led_Analyser                     │
│  mavlink/ — MAVLink 协议栈                │
│  rtcm/    — RTCM/RTK 协议                │
│  radio/   — DAV Radio                   │
│  web/     — Web_API, Web_UI             │
│  dgcs/    — Dgcs_Ui, dgcs_business     │
│  drama/   — DLL, SwarmPainter,          │
│            common, drone_show           │
└────────────────┬─────────────────────────┘
                 │
┌────────────────▼─────────────────────────┐
│          物理层 (Physical)               │
│  SerialPortController   — 串口读写       │
│  APIBase / UIBase       — HTTP/浏览器    │
│  DgcsBusiness           — 桌面应用控制   │
│  App_Interface          — DLL 调用       │
└──────────────────────────────────────────┘
```

### Conftest 继承链

Pytest 沿目录树向上查找 conftest，子目录自动继承父级 fixtures。仅在有真正需要
共享的 fixture / 命令行参数时才新建 conftest.py — 空目录不需要 stub:

```
src/Script/Drone_Show/conftest.py              ← 共享 fixtures（串口/UDP/MavLink/IP/端口）
    ├── V4/ L3/ X1/ V3/                        ← 仅机型层目录,无 per-suite conftest
    ├── Swarm_Painter/Release_Testing/conftest.py    ← DLL/drama 数据 fixtures
    ├── Ground_Station/Release_Testing/conftest.py   ← DGCS 应用生命周期 fixtures
    ├── Cloud_Platform_Ui/Release_Testing/conftest.py ← browser/login session fixtures
    ├── Wifi_Module/conftest.py                ← 串口/FTP/test_params fixtures
    └── Radio/Release_Testing/conftest.py      ← radio_cfg fixture
```

---

## 配置说明

### 机型配置示例

```json
{
  "V4": {
    "ip": "172.17.3.176",
    "port": 14551,
    "serial_port": "COM5",
    "serial_baudrate": 115200,
    "testsuites": {
      "Release_Testing": {
        "script": ["test_release_testcases.py"]
      }
    }
  }
}
```

### 非机型配置示例

```json
{
  "Cloud_Platform_Api": {
    "domain": "https://cloud-gateway-uat.dmduav.com",
    "test_user": "<username>",
    "test_pwd": "<password>",
    "testsuites": {
      "Release_Testing": {
        "script": ["test_web_api.py"]
      },
      "Unit_Module_Testing": {
        "script": ["test_api_unit.py"]
      }
    }
  }
}
```

### 主要配置项

| 配置项 | 说明 |
|--------|------|
| `ip` / `port` | 无人机 UDP 通信地址 |
| `serial_port` | 串口名称 (COM3, /dev/ttyUSB0 等) |
| `serial_baudrate` | 串口波特率 |
| `serial_timeout` | 串口超时 (秒) |
| `domain` | Web API 域名 |
| `app_path` | 桌面应用可执行文件路径 |
| `testsuites.<suite>.script` | 该套件要运行的测试脚本列表 |
| `script_dir` | (可选) 覆盖脚本目录搜索; 相对 project_root。**注意: 使用此键后 script 列表相对它解析(不自动拼套件子目录), 列表项需自带 `Functional_Testing/` 前缀** |

### BSP_APP 板段示例 (MCU 底软 UART)

板名 = Jenkins `DeviceType=BSP_APP` 时 `BoardType` 下拉的值; BSP 板的 TestSuites
下拉为总线名 (UART/SPI/I2C/CAN/PWM), config 的 `testsuites` 键与之对应:

```json
{
  "hope_stm32h743vit6": {
    "port1": "COM10",
    "baud1": 115200,
    "port2": "COM5",
    "uartx": 1,
    "seed": 20260909,
    "soak_seconds": 60,
    "testsuites": {
      "UART": {
        "script": [
          "test_uart_send.py",
          "test_uart_recv.py",
          "test_uart_duplex.py",
          "test_uart_loop.py",
          "test_uart_stat.py",
          "test_uart_baud.py",
          "test_uart_random.py",
          "test_uart_error.py"
        ]
      },
      "SPI": { "script": [] },
      "I2C": { "script": [] },
      "CAN": { "script": [] },
      "PWM": { "script": [] }
    }
  }
}
```

| 配置项 | 说明 |
|--------|------|
| `port1` / `baud1` | Shell 口 (下发 `dmdtest_uart` 命令) |
| `port2` | 数据口 (与被测 UART TX/RX 交叉直连) |
| `uartx` | 被测 UART 编号 |
| `seed` / `soak_seconds` | (可选) 随机种子 / 浸泡时长 (72h 长稳 = 259200) |

---

## Pytest 配置

```ini
[pytest]
addopts = -v -s --alluredir=allure-results --reruns 0 --reruns-delay 1
disable_test_id_escaping_and_forfeit_all_rights_to_community_support = True
pythonpath = . src
python_files = test_*.py
python_classes = Test*
python_functions = test_*

# Allure 日志配置
log_cli = true
log_cli_level = INFO
log_cli_format = %(asctime)s - %(levelname)s - %(filename)s - [%(funcName)s] - %(message)s
log_cli_date_format = %Y-%m-%d %H:%M:%S
```

> **import 规则**: `pythonpath = . src` 让 `src` 成为顶层包,所有 import 必须用全路径 `from src.Protocol.<子包>.<模块> import ...`。扁平写法 `from src.Protocol.<模块>` 或 `from Protocol.<模块>` 都会爆 ModuleNotFoundError(参考 #483 同型 bug)。

### 自定义标记 (Markers)

| 标记 | 说明 |
|------|------|
| `functional` | 功能测试 |
| `algo` | 算法 DLL 测试 |
| `basic` | 基础接口测试 |
| `pathfinding` | 路径规划测试 |
| `safety` | 安全检查测试 |
| `matching` | 最佳匹配测试 |
| `collision` | 碰撞解决测试 |
| `takeoffland` | 起降分配测试 |
| `fileops` | 文件操作测试 |
| `ai` | AI 转换测试 |
| `wifi` / `wifi_functional` / `wifi_performance` / `wifi_release` / `wifi_stress` | WiFi 模块测试 |
| `gui` | DGCS GUI 测试 |
| `login` | 需登录的 DGCS 测试 |
| `e2e` | 端到端流程测试 |

```bash
# 按标记筛选运行
python -m pytest -m "functional"
python -m pytest -m "wifi and not wifi_stress"
```

---

## 依赖库（核心）

| 库 | 用途 |
|----|------|
| pytest | 测试框架 |
| allure-pytest | Allure 报告 |
| pytest-rerunfailures | 失败重试 |
| pyserial | 串口通信 |
| pymavlink | MAVLink 协议 |
| requests | HTTP 请求 |
| selenium | Web 浏览器自动化 |
| uiautomation / pywinauto / pyautogui | Windows GUI 自动化 |
| airtest | 跨平台 UI 自动化 |
| loguru | 日志管理 |
| numpy / opencv-contrib-python | 数据处理与视觉 |
| openpyxl | Excel 读写 |
| jsonschema | JSON Schema 校验 |
| psutil | 进程管理 |

完整列表见 `requirements.txt`。

---

## INDV1 (S100) 底软 BSP 测试

针对 INDV1 机型主控（地平线 RDK S100，Acore Linux 6.1.x-rt 实时内核）的底软自动化测试，
被测对象为 `dmd-bsp` deb（`libdmd_bsp.so` + 内核模块 + 开机服务）。

> 测试脚本位于 `src/Script/Drone_Applications/RDKS100/Functional_Testing/`,
> 由 Jenkins `DeviceType=BSP_APP + BoardType=RDKS100 + TestSuites=Functional_Testing` 入口运行
> (取代旧 `DeviceType=INDV1` 入口); config.json 的 INDV1 段仍保留本板连接配置
> (ssh/调试串口等, 供 conftest 读取)。原 Release_Testing 下的旧版 MCU UART 测试已删除,
> 由下方 BSP_APP MCU UART 测试取代。

### 脚本与用例（53 个）

| 脚本 | 定位 | 用例 |
|------|------|------|
| test_indv1_linux_bsp_s100_flow.py | **业务主流程冒烟** | 自举 → 飞控链路 → MCU 外设代理 → 视频RTSP端到端 → TOF → ADS-B |
| test_indv1_linux_bsp_s100_cpu.py | CPU 测试点 | 启动链顺序 / 6核SMP / 启动时间 / 硬重启 / 软重启 / 1.5GHz / 过温降频机制 / Dhrystone / cyclictest |
| test_indv1_linux_bsp_s100_ddr.py | DDR 测试点 | 容量 / memtester 压测 / 温度与 trip point / 负载温升 / 带宽 |
| test_indv1_linux_bsp_s100_ipc.py | IPC 测试点 | MCU 握手魔数 / ipcfhal 配置 / 通道回环 / PWM 闭环 / CAN 闭环 / I2C 双总线 / gpiochip |
| test_indv1_linux_bsp_s100_timesync.py | 时间同步测试点 | 时钟源单调性 / 时间同步样例 / PTP 在位 / PPS 秒脉冲 |
| test_indv1_linux_bsp_s100_sysinfo.py | 系统信息测试点 | /etc/dmd_versions 版本追溯 / thermal 温度面 / MCU 风扇 / eMMC 容量寿命 / dmd_sysinfo_test 样例 / eMMC 写压测 / watchdog 在位 |
| test_indv1_linux_bsp_s100_ota.py | OTA 升级测试点 | AB 双 slot 分区 / 活动槽查询 / dm-verity cmdline / 升级演练 (切槽+重启) / ADS-B OTA 样例 |
| test_indv1_linux_bsp_s100_sdr.py | SDR 图传测试点 | 样例在位 / 参数面查询 / 对码 / 配置导出导入 |
| test_indv1_linux_bsp_s100_media.py | 多媒体扩展测试点 | 多媒体工具链盘点 / RTSP 连续多轮稳定性 / NPU hbm_runtime 导入 |
| test_indv1_linux_bsp_s100_wireless.py | 无线子系统测试点 | hobot-wifi 服务与网口在位 / WiFi 入网连通 / 蓝牙在位 |

运行方式与其他机型一致：

```bash
python main.py --device_type INDV1 --test_suites Functional_Testing
```

### 环境链路

```
测试机 ──ssh──> Sophon/CV186 (sophon_jump, root) ──内网──> Acore (acore_ip, 测试目标)
        └──USB 串口── Acore 调试口 (console_com_map.J6_Acore, 供启动链/启动时间抓取)
```

- **SSH 免密**：测试机需配置 ed25519 密钥，公钥写入 Acore 与 Sophon 两节点的
  `authorized_keys`；`~/.ssh/config` 配置 `Host <acore_ip>` 的
  `ProxyJump <sophon_jump>`（框架走 BatchMode，不支持密码交互）
- **调试串口**：`config.json INDV1.console_com_map` 统一登记 COM 口与波特率
  （COM 口随 Acore 重启可能重枚举，可在设备管理器固定端口号；
  更稳的方案是独立 USB-TTL 线接调试排针）

### 联调开关（默认关闭，对应用例 skip，不影响构建通过）

| 开关 | 解锁的用例 | 解锁条件 |
|------|-----------|---------|
| `mcu_proxy_enabled` | MCU 外设代理 / I2C 双总线 / DDR 温度 / 风扇 hwmon | MCU 固件实现 ins4 pwm/gpio/i2c 对端 |
| `ipc_loopback_test_enabled` | IPC 通道回环 | 对端具备回显（ins0 系通道为 CAN 桥，误发会上真实 CAN 总线） |
| `ipc_can_test_enabled` | IPC→CAN 闭环 | 有受控 CAN 对端 |
| `ipc_pwm_test_enabled` | IPC→PWM 闭环 | 确认 PWM 不驱动真实执行器 |
| `adsb_enabled` | ADS-B 空域感知 | 接入真实 ADS-B 接收机 |
| `pps_test_enabled` | PPS 秒脉冲 (TSYNC-04) | 接入真实 PPS 源（`pps_probe_cmd` 默认 ppstest /dev/pps0） |
| `emmc_write_test_enabled` | eMMC 写压测 (SYSINFO-06) | 消耗擦写寿命，确认环境后开启（`emmc_write_mb` 控制数据量） |
| `ota_upgrade_enabled` + `ota_install_cmd` | 系统升级演练 (OTA-04) | 升级包放置板端，配置板端升级命令；会切 slot + reboot |
| `sdr_test_enabled` (+`sdr_pair_cmd`/`sdr_config_cmd`) | SDR 参数面/对码/配置 (SDR-02/03/04) | SDR 图传模块在位（fishlink HTTP+AT 链路通），命令模板按 dmd_sdr_test -h 填写 |
| `media_rtsp_repeat_test_enabled` | RTSP 连续多轮稳定性 (MEDIA-02) | 独占 camera/FPGA（与 FLOW-04 同约束），确认无产品业务进程后开启 |
| `wifi_test_enabled` + `wifi_ssid`/`wifi_psk` | WiFi 入网连通 (WLAN-02) | 可入网 AP；`wifi_ping_target` 空 = ping 默认网关 |

### 失败自动导出板端日志

任一用例断言失败时，`pytest_runtest_makereport` 钩子立刻经 adb 将板端日志导出到
`logs/adb/<脚本名>_<时间戳>/`（dmesg、journalctl、/log/fc 飞控日志、/sys/fs/pstore）。
存在多台 adb 设备时在 `INDV1.adb_serial` 指定序列号。

### 板级自适应

底软按 `boardid` 区分硬件版本（v1p0 / v1p1 / v2p0），用例自动适配：
v1p0 无 MCU 域外设与 fc-uart（相关用例自动 skip）、内核模块加载集合按板级校验、
TOF 按板级数量探测。未知 boardid 直接 fail（防静默漏测）。

### Jenkins

job 参数 `DeviceType=BSP_APP`、`BoardType=RDKS100`、`TestSuites=Functional_Testing`
(实际执行 `main.py --device_type RDKS100 --test_suites Functional_Testing`)。
注意：台架节点以 SYSTEM 运行时，SSH 密钥与 `~/.ssh/config`（ProxyJump 跳板规则）需放在
`C:\Windows\System32\config\systemprofile\.ssh\`；构建期间 COM 口勿被串口终端占用。

---

## BSP_APP (MCU 底软 UART) 测试

板卡 MCU 底软 UART 驱动的自动化测试，覆盖飞书《uart测试点分解》**8 大类 79 个测试点**
（发送/接收/全双工/环路/统计/波特率/随机/异常），一个测试点 = 一个 pytest 用例，
Allure 报告按飞书行号逐点可对照。测试逻辑已按本框架三层架构内嵌：

- **物理层** `src/Physical/Serial/SerialPortController.py`：帧格式可配（7/8 数据位 × N/E/O × 1/2 停止位，
  默认 8N1 不影响既有套件）；`UartPortController` 为被测数据口专用子类
- **协议层** `src/Protocol/dmdtest_uart/`：`dmdtest_uart` 命令-应答协议、会话管理、
  吞吐量/CPU 差分测量、错误注入与溢出探测（搬写自 mcu_ll_drivers_tester 的 uart_tester.py 公共设施）
- **脚本层** `BSP_APP/hope_stm32h743vit6/UART/`：8 个分组测试文件原生用例，
  判定语义与原上位机一致（rep 任一值为 False 即失败，"记录:" 前缀键仅记录）

测试点原理详见 mcu_ll_drivers_tester 仓库 `ll_drivers_tester_host/doc/uart_test_principle.md`。

### 目录组织与扩展规则

```
src/Script/Drone_Applications/<板名>/<套件名>/    # 板名 = Jenkins BoardType 下拉值,
                                                  # 套件名 = TestSuites 下拉值
```

遵循框架原生目录探测约定(main.py: `Drone_Show/<设备>` 优先, 其次 `Drone_Applications/<设备>`,
命中后拼 `/<套件>`), **script 列表一律裸文件名, 不使用 script_dir 覆盖**。

- Jenkins `DeviceType=BSP_APP` 是底软测试统一入口, `BoardType` 选具体板
  (RDKS100 / hope_stm32h743vit6 / host / hrw_stm32u073cbt6_eval / mobai_gd32l233kbg6_core /
  qsyx_stm32f030cct6_core / weact_stm32g431cbu6)
- **RDKS100 为 Linux 开发板**: TestSuites 给标准五套件 → `--device_type RDKS100` 原生定位
  `Drone_Applications/RDKS100/Functional_Testing/`(取代旧 `DeviceType=INDV1` 入口)
- **MCU 底软板**(hope_stm32h743vit6 等): TestSuites 给总线套件(UART/SPI/I2C/CAN/PWM) →
  原生定位 `Drone_Applications/<板名>/<总线>/`
- **接入一块新板的总线测试** = 3 步: ① 建 `Drone_Applications/<板名>/<总线>/` 目录放 conftest +
  测试文件 ② config.json 加板段(script 裸文件名) ③ (新板时) Jenkins BoardType 下拉加值
- 未接入的板/套件不建目录, 误选时 main.py 明确报错退出

### 运行方式

```bash
# BSP_APP 入口 (板名 = config.json 顶层键 = Jenkins BoardType 下拉值)
python main.py --device_type hope_stm32h743vit6 --test_suites UART

# 只跑某分组 (pytest -k, 类名即分组)
python -m pytest src/Script/Drone_Applications/BSP_APP/hope_stm32h743vit6/UART \
    --device_type=hope_stm32h743vit6 -k "TestUartLoop or TestUartStat"

# 72h 长稳浸泡: config.json hope_stm32h743vit6.soak_seconds 改为 259200 后跑随机测试分组
```

### 硬件拓扑与前置

```
测试机 ──COM port1──> MCU Shell 口 (下发 dmdtest_uart 命令)
       ──COM port2──> 被测 UARTx TX/RX 交叉直连 (数据口)
```

- 被测 MCU 需烧录含 `dmdtest_uart` 命令集的 ll_drivers_tester 固件
- 接线与测试原理见 `uart_test_principle.md`（port2 必须与被测 UART 交叉直连）

### 结果说明

- **79 点分布**：发送 21 / 接收 19 / 全双工 7 / 环路 2 / 统计 8 / 波特率 6 / 随机 10 / 异常 6
  （8 个文件 `test_uart_send/recv/duplex/loop/stat/baud/random/error.py` 与分组一一对应）
- **12 个占位 skip**（飞书行 19/21/39/40/47/48/54/57/69/72/73/78）：ISR 级 CPU 统计、
  中断注入、位级噪声、未读积压字节、温/电压波动等需固件增强或硬件注入手段，暂无法自动化
- **判定明细**：每个用例的完整判定/记录键值以 JSON 附件挂 Allure
  （`assert_feishu_rep`，与原上位机 feishu_point 语义一致，任一 False 即失败）
- **串行约束**：单一 Shell 串口独占，严禁并行执行（禁止引入 pytest-xdist）

### Jenkins

job 选 `DeviceType=BSP_APP` 后必须选 `BoardType`（板名下拉），TestSuites 联动显示
总线套件（UART/SPI/I2C/CAN/PWM），脚本分发为 `main.py --device_type <板名> --test_suites <总线>`。
job timeout 建议 ≥60 分钟（UART 79 点全量约 10-20 分钟）。

---

## 常见问题

### BSP_APP (MCU UART) 用例全部 skipped
- Shell 串口打不开：检查 `port1` COM 口号 / 波特率 / 是否被串口调试终端占用
  （COM 口同时只能被一个程序打开）；日志会打印 skip 原因

### BSP_APP 收集期 UsageError (退出码 4)
- `config.json` 板段缺失或缺必填 key（port1/baud1/port2/uartx），
  pytest 收集期直接硬失败，不会带病运行

### BSP_APP 用例大面积失败
- MCU 固件未烧 `dmdtest_uart` 命令集或版本不匹配（应答解析失败，失败明细的
  rep JSON 里有 ack 原文）
- port2 未与被测 UART TX/RX 交叉直连、共地缺失，环路/全双工类会整体失败

### INDV1 测试全部 skipped
- SSH 链路不通：手动执行 `ssh -o BatchMode=yes root@<acore_ip> uname -a` 验证
- BatchMode 不支持密码交互，必须预配公钥（追加到板端 authorized_keys）
- 跳板链路：Acore 无独立外网口时需经 Sophon 跳板，`~/.ssh/config` 配置 ProxyJump
- 板子未上电 / Sophon 节点离线（跳板失效会连带 Acore 不可达）

### INDV1 串口用例 skipped（启动链/启动时间）
- `console_com_map.J6_Acore` 未配置，或 COM 口被串口终端占用（COM 口同时只能被一个程序打开）
- Acore 重启会使板载 USB 串口桥重枚举，conftest 已带自动重连；
  若仍抓不到日志，改用独立 USB-TTL 线接调试排针

### 串口通信失败
- 检查 `config.json` 中 `serial_port` 是否正确
- 确认串口未被其他程序占用（如串口调试助手）
- 确认波特率与设备一致

### 测试用例未收集到
- 检查 `config.json` 中对应 `testsuites.<suite>.script` 是否配置了脚本名
- 确认脚本文件存在于对应目录
- 查看 pytest collection 输出的路径信息

### Allure 报告生成失败
- 确认 `allure-2.35.1` 目录存在
- 检查 Java 是否已安装（Allure 依赖 JRE）
- 手动执行 `allure generate` 查看错误详情

### 虚拟环境问题
- 删除 `.venv` 后重建：`python -m venv .venv`
- 确认 Python 版本为 3.10.x
- 重新安装：`pip install -r requirements.txt`

---

**最后更新**：2026年9月22日
