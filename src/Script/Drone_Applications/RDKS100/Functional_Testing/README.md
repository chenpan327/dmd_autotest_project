# RDKS100 (S100) Linux 底软功能测试

> 被测对象:INDV1 机型主控 **DMD RDK S100E**(Acore, Ubuntu 22.04 / kernel 6.1.158-rt)上的
> **dmd-bsp 底软包**(libdmd_bsp.so + 内核模块 + 开机服务)。
> 本 README 供测试执行者与底软开发快速对齐:板上有什么、底软做了什么、测试怎么跑、
> 失败了去哪看。规格依据:《行业无人机Linux底软规格书》。

---

## 1. 板卡架构(双 SoC + MCU,一块 PCB)

```
                    外部
        WiFi(DmdCom)│      网线(地面站网 172.16.200.x)
                    ▼            ▼
┌──────────────────────────────────────────────────────────────┐
│  【CV186AH】6×A53, Linux 5.10       【S100E / Acore】6×A78AE │
│  · WiFi 模组 FCE863R(对外入口)     · Ubuntu 22.04           │
│  · 测试链路跳板(本目录测试   ←──→  · 跑 dmd-bsp(被测主体)  │
│    的必经第二跳)  板内 RTL8364 switch(eth0 172.16.0.1↔.2)   │
│                                      │ remoteproc 加载/监控   │
│                              【MCU1】STM32/GD32(dmd_firmware)│
│                               └ IPC 总线提供 pwm/gpio/i2c/can│
│  板载外设: 8×camera(FPGA Crosslink 聚合)· ads6401 ToF ·    │
│  emc2301 风扇 · TCA9548 I2C 扩展 · 4G(EG950A)· PPS(FC 输入) │
└──────────────────────────────────────────────────────────────┘
```

- **Acore(S100E)**:被测主体。跑 dmd-bsp,负责传感器/协处理器管理
- **CV186(Sophon)**:辅助 SoC(算能,视频生态)。对测试而言承担 **WiFi 跳板**
  (FCE863R 模组在 CV186 侧;**Acore 无 WiFi 硬件**,板上实测 nmcli 仅 eth0)
- **MCU1**:固件源码在 `dmd_firmware` 仓库;被 Acore 经 remoteproc 加载,
  通过 IPC 总线(ins0/ins4 通道)向 Acore 提供 pwm/gpio/i2c/can 外设代理
- **FC 飞控**(外部):经 fc-uart 与 Acore 通讯,PPS 信号驱动相机/ToF 的 20Hz 曝光触发

## 2. dmd-bsp 底软职责(源码 `rdk/source/dmd-bsp/modules/`)

| 模块 | 职责 | 对应测试 |
|---|---|---|
| init / board | 开机自举、内核模块加载(dmd-loadko)、板卡信息 | flow-01 / board_info fixture |
| log | 日志系统(优先级/容量管控) | (容量管控用例待建) |
| camera (+codec) | 8 路 camera 监控、ISP 出图、编码 | flow-04(视频 e2e) / media-02(多轮稳定性) |
| rtsp | 视频对外 RTSP 输出 | flow-04 / media-02 |
| tof | ToF 点云/直方图业务 | flow-05 |
| timesync | 时间同步(FC PPS → 曝光触发,≤50us) | tsync 全组(时钟源/样例/PTP/PPS; 50us 精度待建) |
| adsb | 空域感知 + OTA 升级(全量/差分/校验) | flow-06(业务) / ota-05(OTA 样例在位) |
| ipcfhal + mcu-ipc | 跨核 IPC:MCU 外设代理(pwm/gpio/i2c/can) | ipc 全组 |
| system_info / storage | 8 类系统查询(负载/内存/存储/温度/风扇/板状态) | sysinfo 全组 |
| (打包链) AB 分区 + dm-verity + ota_tool | 双 slot OTA 升级 | ota 全组 |
| SDR | 图传统一接口(fishlink HTTP+AT) | sdr 全组 |
| (dts) thermal + emc2301 | SCMI 温度区 + 风扇调速 | cpu-07(降频) / sysinfo-02(温度面) / sysinfo-03(风扇) |

底软源码树:`C:\workspace\code\rdk`(repo manifest 多仓;
dts 关键文件 `source/hobot-drivers/kernel-dts/dmd-s100-v1p0.dtsi`、
`drobot-s100-thermal.dtsi`);MCU 固件源码:`C:\workspace\code\dmd_firmware`。

## 3. 网络拓扑(四张网,互不相通)

| 网络 | 成员 | 用途 |
|---|---|---|
| DmdCom WiFi(10.10.12.0/23, DHCP=10.10.12.1) | 台架 WLAN + CV186 WiFi(10.10.12.136) | 测试入口(第一跳) |
| 板内网(172.16.0.0/24) | CV186 eth0(.1) ↔ Acore eth0(.2) | 测试第二跳(SSH 落点) |
| 地面站网(172.16.200.x) | 台架"以太网 2" → DGCS | 地面站测试专用,与底软无关 |
| 外网(10.10.4.x) | 台架有线(10.10.4.176) | Jenkins 通讯 |

⚠️ CV186 的 WiFi 地址为 DHCP 动态分配,漂移会导致整条链路中断
——已申请 MAC 绑定(`bc:2a:33:2a:ae:15` → `10.10.12.136`)。
若构建报"SSH 未恢复",先在台架验证两条命令定位断在哪一跳:

```powershell
ssh root@10.10.12.136 "uname -a"                    # 第一跳: CV186
ssh -o BatchMode=yes root@172.16.0.2 "uname -a"     # 第二跳: 经跳板到 Acore
```

CV186 侧 WiFi 掉线后的恢复(运维动作,不改配置):
COM6 串口(115200, root/root)登录执行 `dhclient wlp1s0`。

## 4. 测试内容(53 用例,10 个脚本)

### 4.0 用例总览与判据口径

| 脚本 | 用例 | 覆盖 |
|---|---|---|
| test_indv1_linux_bsp_s100_flow.py | 6 | 自举(模块/自检)、FC 链路、MCU 外设代理、视频 RTSP e2e、TOF 业务、ADS-B |
| test_indv1_linux_bsp_s100_cpu.py | 9 | 启动链顺序、6 核 SMP、启动时间、硬/软重启、1.5GHz 频率、过温降频、Dhrystone、cyclictest |
| test_indv1_linux_bsp_s100_ddr.py | 5 | 容量(12GB LPDDR5)、memtester 压测、温度监控、负载温升、带宽 |
| test_indv1_linux_bsp_s100_ipc.py | 7 | MCU 握手、ipcfhal 配置、通道回环、PWM/CAN 闭环、I2C 双总线、gpiochip |
| test_indv1_linux_bsp_s100_timesync.py | 4 | 时钟源单调性、时间同步样例、PTP 在位、PPS 秒脉冲 |
| test_indv1_linux_bsp_s100_sysinfo.py | 7 | dmd_versions 版本追溯、thermal 温度面、MCU 风扇、eMMC 容量寿命、sysinfo 样例、eMMC 写压测、watchdog |
| test_indv1_linux_bsp_s100_ota.py | 5 | AB 双 slot 分区、活动槽查询、dm-verity、升级演练、ADS-B OTA 样例 |
| test_indv1_linux_bsp_s100_sdr.py | 4 | SDR 样例在位、参数面查询、对码、配置导出导入 |
| test_indv1_linux_bsp_s100_media.py | 3 | 多媒体工具链盘点、RTSP 多轮稳定性、NPU 运行时导入 |
| test_indv1_linux_bsp_s100_wireless.py | 3 | WiFi 服务/网口在位、入网连通、蓝牙在位 |

**判据通用口径**(各表"通过判据"均在此基础上叠加):

- ✅ **通过**:该用例列出的断言全部成立(pytest 原生 assert,任一失败即用例失败)
- ⏭ **skip**:环境依赖不满足(外设不在位 / 开关未开 / 工具未部署),**不判失败**,
  skip 原因写入日志与 Allure;skip≠通过,报告里单独统计
- ❌ **不过**:任一断言不成立;失败瞬间经 adb 自动取证(第 5 节),别急着复跑,先看
  `logs/adb/<脚本名>_<时间戳>/` 里的 dmesg/journalctl/飞控日志/pstore

所有用例的板端命令输出都挂 Allure 附件,判据争议时以附件原文为准。
指标依据规格书:CPU 6×A78AE @1.5GHz、DDR 12GB LPDDR5、eMMC 64GB、
相机 20Hz/延迟≤50ms、ToF 20Hz/延迟≤30ms、Timesync ≤50us、
IPC/DDR/eMMC 带宽 ≥60~70% 理论值。

### 4.1 flow — 业务主流程冒烟(6)

| 用例 | 测什么 | 板端指令(核心) | 通过判据 | skip 条件 |
|---|---|---|---|---|
| FLOW-01 自举 | MCU 被加载、IPC 就绪、模块齐、自检过 | `cat .../remoteproc_mcu0/state`、`devmem 0xcddee00`、`systemctl show dmd-loadko`、`journalctl -k`、`lsmod`、`dmd_board_test` | state=running;魔数=0x49504346('IPCF');ExecMainStatus=0;日志含 dmd_load_ko_begin/end 且无 check timeout;lsmod=板级期望集;自检有 PASS: 无 FAIL: | 未知 boardid 直接 fail(防漏测,不 skip) |
| FLOW-02 飞控链路 | fc-uart 透传落盘业务在跑 | `readlink -f /dev/fc-uart`、`systemctl is-active fc-logger`、`ls -lL /log/fc/` | 链接指向 ttyCH943X*;服务 active;/log/fc 有非空文件 | 非 v2p0(boardid≠0x8)板级 skip;飞控未上电时 fail(数据侧无法验证) |
| FLOW-03 MCU 代理 | 温度/风扇/gpio 经 IPC 代理可用 | `i2cdetect -y 8`、hwmon temp 读数、gpiochip ngpios | 0x48/0x49=UU(dmd_temp 占用)、0x2f 在位;温度∈[-40,125]℃;存在 106 线 gpiochip | 未开 mcu_proxy_enabled / 非 MCU 板级 skip |
| FLOW-04 视频 e2e | 采集→H.265 编码→RTSP 推流全链 | `dmd_rtsp_test -n 150` | cam0 up / RTSP up / encoder up 三标记;[stats] sent≥100、fail≤3、rtsp feeds>0 | camera 不在位(输出 not found + dmd_camera_init)skip |
| FLOW-05 TOF 业务 | 深度帧真实产出 | `timeout -s INT 20 dmd_tof_manual_test` | 无 dmd_bspinit failed;≥1 路 `get_frame success`;失败帧≤成功路数×3 | 全部 TOF 初始化失败(sensor 不在位)skip |
| FLOW-06 ADS-B | 空域感知接收链路 | `test -e /dev/ttyS1`;开 adsb_enabled 后 `timeout -s INT 15 dmd_adsb_manual_test` | ttyS1 在位;运行时无 `FAIL: dmd_adsb_init/start/get_version` | 无接收机(开关关)只验串口在位后 skip |

### 4.2 cpu — CPU 测试点(9)

| 用例 | 测什么 | 板端指令(核心) | 通过判据 | skip 条件 |
|---|---|---|---|---|
| CPU-01 启动链 | SPL→BL31→OP-TEE→U-Boot→Linux 顺序 | 自动触发 reboot,调试串口抓完整启动日志(boot_capture fixture) | Linux 标记存在;(U-Boot 或 BL31)存在;实际出现顺序=定义顺序 | 未接调试串口 skip;SPL/OP-TEE 控制台静默只告警不判失败 |
| CPU-02 SMP | 6 核全部在线 | `nproc`、`grep -c ^processor /proc/cpuinfo`、`cat .../cpu/online` | 三处核心数均=6(expected_cpu_count) | — |
| CPU-03 启动时间 | rootfs 挂载耗时 | 同串口日志,取 `VFS: Mounted root`/`Run /sbin/init` 内核时间戳 | ≤ boot_time_max_s(默认 30s) | 未接串口 skip |
| CPU-04 硬重启 | 断电后恢复 | (人工断电) | 自动化占位 | 恒 skip(需人工/继电器) |
| CPU-05 软重启 | reboot 自恢复 | `reboot` → 轮询 SSH → `uptime` | reboot_timeout_s(300s)内 SSH 恢复且 uptime 归零重涨 | **不恢复=fail 非 skip**(阻断后续用例级联失败) |
| CPU-06 频率 | 额定 1.5GHz | `cat .../cpuinfo_max_freq` | =1500000 kHz | SCMI 真机不可见,现状见第 6 节已知问题 1 |
| CPU-07 降频机制 | 过温降频在位 | thermal trip point + 压载采样 | trip point 存在且 cooling 映射在位 | 同上(SCMI 缺陷),已反馈底软 |
| CPU-08 Dhrystone | 单核算力 | `dhrystone`(dhrystone_iterations 轮) | DMIPS ≥ dhrystone_min_dmips(默认 2000,首跑校准) | 板上无 dhrystone skip |
| CPU-09 实时性 | 调度时延 | `cyclictest` 空载/压载(stress-ng 或 dd)/中断压力三场景 | Max latency ≤ cyclictest_max_latency_us(默认 1000μs) | 板上无 cyclictest skip |

### 4.3 ddr — DDR 测试点(5)

| 用例 | 测什么 | 板端指令(核心) | 通过判据 | skip 条件 |
|---|---|---|---|---|
| DDR-01 容量 | MemTotal 达标 | `grep MemTotal /proc/meminfo` | ≥ ddr_min_total_mb(默认 1024MB,CMA/BPU 预留后) | — |
| DDR-02 压测 | 内存位无坏点 | `memtester 256M`(或 stress-ng --vm) | 退出码 0,无 failure | 板上无工具 skip |
| DDR-03 温度监控 | DDR 温度可读+trip | hwmon dmdtemp/temp1_input、thermal trip point | 读数∈[-40, ddr_temp_max_c=85]℃;trip 在位 | 未开 mcu_proxy_enabled skip |
| DDR-04 负载温升 | 压载下温度受控 | 压载 60s + 持续采样温度 | 全程 ≤85℃ 且收敛 | 同上 |
| DDR-05 带宽 | 内存带宽留档 | `mbw`(可选) | 输出解析留档(阈值首跑校准) | 板上无 mbw skip |

### 4.4 ipc — IPC/外设代理(7)

| 用例 | 测什么 | 板端指令(核心) | 通过判据 | skip 条件 |
|---|---|---|---|---|
| IPC-01 MCU 握手 | 固件在跑+共享内存就绪 | 同 FLOW-01 前三步 | state=running;魔数 0x49504346;日志含 ipc4 ready(格式核对中,暂只告警) | — |
| IPC-02 配置完整性 | 通道表在册 | `cat /etc/ipcfhal_config.json` | 合法 JSON;ins4 ch0/1/2(PWM/GPIO/I2C)+回环通道齐全 | — |
| IPC-03 通道回环 | IPC 数据面收发 | `dmd_ipc_test -i0 -c0 -L -n1000 -l64` | 退出码 0(样例 Fail>0 返回 1);吞吐≥ipc_min_rate_kbps | 未开 ipc_loopback_test_enabled(ins0 为 CAN 桥,误发上真总线) |
| IPC-04 PWM 闭环 | 写→读回硬件比对 | `dmd_ipc2pwm -i4 -c0` | 退出码 0(period 精确,duty 容差±2‰) | 未开 ipc_pwm_test_enabled(可能驱动真实执行器) |
| IPC-05 CAN 闭环 | 帧回环一致 | `dmd_ipc2can -i0 -c1 -n200` | 退出码 0(发 id=0x1 约定回显 0x0,数据一致) | 未开 ipc_can_test_enabled(报文必然上真实总线) |
| IPC-06 I2C 双总线 | 两条 MCU I2C 互不卡死 | `i2cdetect -y 9` → 复读 bus8 温度 | bus9 可扫(空总线全 -- 属正常);扫描后 bus8 温度仍可读 | 未开 mcu_proxy_enabled |
| IPC-07 gpiochip | GPIO 代理在位 | `lsmod`、gpiochip*/ngpios、gpiodetect 兜底 | 存在 106 线 gpiochip(只验在位,读写闭环属破坏性) | dmd_gpio 未加载(板级不含)skip |

### 4.5 timesync — 时间同步(4)

| 用例 | 测什么 | 板端指令(核心) | 通过判据 | skip 条件 |
|---|---|---|---|---|
| TSYNC-01 时钟源 | 时钟基准正常 | `cat .../current_clocksource`、`date +%s`、两次 `cat /proc/uptime` | clocksource 非空;与测试机时差<1h;uptime 单调递增 | — |
| TSYNC-02 样例 | timesync 样例可运行 | `sample_timesync`(/app/timesync_demo/) | 退出码 0 | 二进制不在位(sp-samples 未装)skip;打印 Usage=fail(CLI 口径变了) |
| TSYNC-03 PTP | 硬件时间戳基座 | `ls /sys/class/ptp/`、`ls /dev/ptp*` | sysfs 与字符节点同时在位 | 板级/内核未暴露 PTP skip |
| TSYNC-04 PPS | 秒脉冲输入链路 | `ppstest /dev/pps0`(pps_probe_cmd) | 输出含 assert 事件序列 | 未开 pps_test_enabled(需真实 PPS 源) |

### 4.6 sysinfo — 系统信息(7)

| 用例 | 测什么 | 板端指令(核心) | 通过判据 | skip 条件 |
|---|---|---|---|---|
| SYSINFO-01 版本追溯 | 板上跑的版本可追溯 | `cat /etc/dmd_versions` | 首行 DMD_VERSION 声明(配置 expected_dmd_version 时精确比对,**不匹配=fail 防测错镜像**);含 Commit 条目 | 文件不存在=fail(非 dmd 打包链路产物) |
| SYSINFO-02 温度面 | thermal 全域可读 | 遍历 thermal_zone*/{type,temp} | zone≥1;读数∈[-40, 110]℃ | — |
| SYSINFO-03 风扇 | emc2301 在位/转速 | hwmon 搜 emc230* → fan1_input | hwmon 在位;rpm≥fan_min_rpm(默认 0=仅记录) | 未开 mcu_proxy_enabled |
| SYSINFO-04 eMMC | 容量与寿命 | `cat /sys/block/mmcblk0/size`、device/{pre_eol_info,life_time} | ≥8GB;pre_eol_info≠0x03(紧急=fail);0x02 预警只告警 | — |
| SYSINFO-05 样例 | 8 类查询总入口 | `dmd_sysinfo_test` | 退出码 0 且有输出(格式首跑校准) | 二进制不在位 skip |
| SYSINFO-06 eMMC 写压测 | 写入数据完整性 | dd 256M 随机块 + 双程 md5 比对 | md5 一致;速率≥emmc_write_min_mbps(10MB/s) | 未开 emmc_write_test_enabled(耗擦写寿命) |
| SYSINFO-07 watchdog | 看门狗节点在位 | `ls /dev/watchdog*` | ≥1 个节点(只验在位,触发属专项) | — |

### 4.7 ota — OTA 升级(5)

| 用例 | 测什么 | 板端指令(核心) | 通过判据 | skip 条件 |
|---|---|---|---|---|
| OTA-01 AB 分区 | 双 slot 表完备 | `ls /dev/disk/by-partlabel/` | boot/system/vbmeta × a/b 六分区齐全 | 分区缺失=fail(非 AB 打包,OTA 链路不可用) |
| OTA-02 活动槽 | slot 可查询 | `ota_tool -g` | 退出码 0 且有输出(a/b/0/1 解析兜底) | — |
| OTA-03 dm-verity | 只读校验在服务 | `cat /proc/cmdline` | 含 dm= 与 verity(ota_dm_verify_expected=false 的调试镜像则只记录) | — |
| OTA-04 升级演练 | 升级→切槽→回切 | 记录 `ota_tool -g` → `ota_install_cmd`(自配) → reboot → 轮询 SSH → 再查槽 | 升级命令码 0;SSH 于 reboot_timeout_s 内恢复;活动槽翻转 | 未开 ota_upgrade_enabled / 未配 ota_install_cmd(**开关开了没配命令=fail**) |
| OTA-05 ADS-B OTA 样例 | 升级工具在位 | `test -x dmd_adsb_ota_test` | 二进制在位(真实升级需接收机,错误码矩阵属专项) | 不在位 skip |

### 4.8 sdr — SDR 图传(4)

| 用例 | 测什么 | 板端指令(核心) | 通过判据 | skip 条件 |
|---|---|---|---|---|
| SDR-01 样例在位 | dmd_sdr_test 装载 | `test -x {ipc_bin_dir}/dmd_sdr_test` | 二进制在位 | 不在位 skip |
| SDR-02 参数面 | init/get 全参数无失败 | `dmd_sdr_test`(无参默认序列) | 无 `FAIL: dmd_sdr`;码 0;无段错误 | 未开 sdr_test_enabled;输出呈连接失败特征(模块不在位)skip |
| SDR-03 对码 | pair 流程 | `sdr_pair_cmd`(自配,按 -h 用法) | 退出码 0 | 未开开关/未配命令模板 skip |
| SDR-04 配置导出导入 | export/import 链 | `sdr_config_cmd`(自配) | 退出码 0 | 同上 |

### 4.9 media — 多媒体扩展(3)

| 用例 | 测什么 | 板端指令(核心) | 通过判据 | skip 条件 |
|---|---|---|---|---|
| MEDIA-01 工具链盘点 | dmd-bsp 多媒体样例装载 | `test -x` dmd_encode_manual_test/dmd_rtsp_test/dmd_foxglove_test | 三个全在位;sample_codec(VPU)等平台样例仅记录不判 | dmd 侧缺件=fail(deb 未装/未编 samples) |
| MEDIA-02 RTSP 多轮稳定性 | 编码推流无累积劣化 | 连续 2 轮 `dmd_rtsp_test -n 100` | 每轮 sent≥67/fail≤3/feeds>0;末轮 sent≥首轮 50% | 未开 media_rtsp_repeat_test_enabled;camera 不在位 skip |
| MEDIA-03 NPU 运行时 | 推理基座可导入 | `python3 -c 'import hbm_runtime'` | 退出码 0 | 板端无 python3 skip;ModuleNotFoundError=**fail**(镜像缺 hobot-dnn) |

### 4.10 wireless — 无线子系统(3)

| 用例 | 测什么 | 板端指令(核心) | 通过判据 | skip 条件 |
|---|---|---|---|---|
| WLAN-01 服务/网口 | WiFi 服务+接口注册 | `systemctl list-unit-files hobot-wifi`、`ip -o link` | 单元存在;有 wlan*/mlan* 接口 | 无单元(镜像未装)skip;无接口(模块未上电)skip |
| WLAN-02 入网连通 | 真实入网+转发 | `nmcli device wifi connect <ssid> password <psk>` → `ping 网关` | nmcli 码 0;ping 3 发≥1 应答 | 未开 wifi_test_enabled/未配 ssid(开了没配=**fail**);注意测试通道走 SSH 有线,WiFi 断连不影响上报 |
| WLAN-03 蓝牙 | 服务+适配器 | `systemctl list-unit-files hobot-bluetooth`、`hciconfig` | 单元存在;hci* 适配器在位 | 无单元 skip;无适配器(未上电)skip |

## 5. 运行方式与环境

```bash
# Jenkins: DeviceType=BSP_APP + BoardType=RDKS100 + TestSuites=Functional_Testing
# 等价本地:
python main.py --device_type RDKS100 --test_suites Functional_Testing
```

环境链路(SSH 免密, BatchMode, 不支持密码交互):

```
台架 ──ssh──> Sophon/CV186(10.10.12.136, root) ──内网──> Acore(172.16.0.2, root)
      └──USB 串口── Acore 调试口(console_com_map.J6_Acore, 启动链/启动时间抓取)
```

- SSH 公钥需预置到 Sophon 与 Acore 两节点;SYSTEM 账户运行时密钥放
  `C:\Windows\System32\config\systemprofile\.ssh\`,ProxyJump 指向 CV186 地址
- 调试串口 COM 口在 `config.json INDV1.console_com_map` 登记;COM 口勿被串口终端占用

### 板级自适应

按 `boardid` 区分硬件版本(v1p0/v1p1/v2p0):v1p0 无 MCU 域外设与 fc-uart
(相关用例自动 skip)、内核模块加载集合按板级校验;未知 boardid 直接 fail。

### 联调开关(config.json INDV1 段,默认关,对应用例 skip)

| 开关 | 解锁用例 | 前提 |
|---|---|---|
| mcu_proxy_enabled | MCU 外设代理/I2C 双总线/DDR 温度/风扇 hwmon | MCU 固件实现 ins4 对端 |
| ipc_loopback_test_enabled | IPC 通道回环 | 对端回显(ins0 系为 CAN 桥) |
| ipc_can_test_enabled | IPC→CAN 闭环 | 有受控 CAN 对端 |
| ipc_pwm_test_enabled | IPC→PWM 闭环 | 确认不驱动真实执行器 |
| adsb_enabled | ADS-B 空域感知 | 接真实 ADS-B 接收机 |
| pps_test_enabled | PPS 秒脉冲(tsync-04) | 接真实 PPS 源(pps_probe_cmd 默认 ppstest /dev/pps0) |
| emmc_write_test_enabled | eMMC 写压测(sysinfo-06) | 消耗擦写寿命;emmc_write_mb 控制数据量 |
| ota_upgrade_enabled + ota_install_cmd | 系统升级演练(ota-04) | 升级包放板端,配板端升级命令;会切 slot+reboot |
| sdr_test_enabled (+sdr_pair_cmd/sdr_config_cmd) | SDR 参数面/对码/配置(sdr-02/03/04) | SDR 模块在位(fishlink HTTP+AT 通),命令模板按 dmd_sdr_test -h 填 |
| media_rtsp_repeat_test_enabled | RTSP 多轮稳定性(media-02) | 独占 camera/FPGA(与 flow-04 同约束) |
| wifi_test_enabled + wifi_ssid/wifi_psk | WiFi 入网连通(wlan-02) | 可入网 AP;wifi_ping_target 空=ping 网关 |

⚠ 通用规则:**开关开了但配套参数没配(ota_install_cmd/wifi_ssid 等)= fail 而非
skip** —— 防止"以为配了跳过了"的静默漏测。

### 失败自动取证

任一用例断言失败时,`pytest_runtest_makereport` 钩子立刻经 adb 导出板端日志到
`logs/adb/<脚本名>_<时间戳>/`(dmesg、journalctl、/log/fc 飞控日志、pstore)。
多台 adb 设备时在 `INDV1.adb_serial` 指定序列号。

## 6. 已知问题与注意事项(2026-09 真机联调)

1. **SCMI thermal/cpufreq 真机不可见**(疑似底软缺陷):
   dts 设计有 SCMI 温度区(`drobot-s100-thermal.dtsi`)与 emc2301 风扇 cooling,
   但真机 `/sys/class/thermal`、`cpuinfo_max_freq` 均为空 →
   `test_cpu_freq_normal` / `test_cpu_throttle_mechanism` 失败。
   已反馈底软确认(疑似 SCMI 传感器/性能域驱动未生效)。
2. **IPC 日志格式**:'ipc4 ready' 与真机日志不匹配(用例有告警,当前不判失败),
   需与底软开发核对格式后收紧断言。
3. **串口桥重枚举**:Acore reboot 会复位板载 USB 串口桥,启动日志窗口易丢失
   (历史构建仅抓到关机残留);conftest 带自动重连,持续抓不到时改独立 USB-TTL
   接调试排针,或在设备管理器固定 COM 号。
4. **CV186 WiFi 稳定性**:Acore reboot 的电源扰动可能导致 CV186 WiFi 模组瞬断
   → 跳板失联(IPv4 租约不自动恢复)。构建中遇"reboot 后 SSH 未恢复"的
   fail-fast,先按第 3 节两条命令定位断在哪一跳。
5. 板上 `dhrystone`/`cyclictest`/`memtester`/`mbw` 等工具未随镜像部署时,
   对应用例自动 skip(需底软侧补工具后生效)。

## 7. 相关文档

- 底软测试点需求:飞书《uart测试点分解》/《行业无人机Linux底软规格书》
- UART 驱动测试原理:`mcu_ll_drivers_tester/ll_drivers_tester_host/doc/uart_test_principle.md`
- 底软源码:`rdk` 仓库(repo manifest;构建脚本 `mk_dmd_bsp.sh` / `mk_kernel.sh`)
- MCU 固件源码:`dmd_firmware` 仓库
- 框架总览:仓库根目录 `README.md` 的 "BSP_APP (MCU 底软 UART) 测试" 章节
