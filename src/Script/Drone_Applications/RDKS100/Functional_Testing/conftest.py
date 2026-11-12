# coding: utf-8
"""
INDV1 底软测试全局 Fixture

被测对象: INDV1 机型主控 (DMD RDK S100, Acore Linux) 上的底软
         (dmd-bsp deb: libdmd_bsp.so + 内核模块 + 开机服务)

从 config.json 读取 INDV1 配置, 提供:
    - ssh 远程执行 fixture (复用 src/Physical/Nest/NestRemoteHelper, 通用 Linux 远程执行工具)
    - 板卡信息 fixture (boardid / 硬件版本, 决定各用例的板级适用性)
    - 测试参数 fixture (fail-fast: 缺任一 key 立即抛 KeyError)

注意:
    - --device_type / --test_suites / --mavlink_version 已在项目根目录 conftest.py 注册
    - NestRemoteHelper 走系统 ssh + BatchMode, 不支持密码交互 —
      测试机需预先配好到板卡的 ssh 公钥 (ssh-copy-id), 否则连接探针失败整批 skip
    - conftest 放在 Functional_Testing/ 内, 不影响同级 Release_Testing 的 MCU UART 测试
    - 用例断言失败时, pytest_runtest_makereport 钩子立刻通过 adb 导出板端日志到
      <项目根>/logs/adb/<脚本名>_<时间戳>/: dmesg / journalctl / /log/fc 飞控日志 /
      /sys/fs/pstore 内核panic日志 (板端 adbd 由镜像 hobot-adbd.service 提供)
"""
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest

from utils.logger import log_manager
from utils.common import get_project_root
from src.Physical.Nest.nest_remote_helper import NestRemoteHelper


def load_indv1_config() -> dict:
    """从 config.json 加载 INDV1 配置 (fail-fast: 缺节立即抛 KeyError)"""
    project_root = Path(get_project_root())
    config_path = project_root / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    indv1_config = config.get("INDV1")
    if not indv1_config:
        raise KeyError("config.json 中未找到 INDV1 配置项")
    return indv1_config


@pytest.fixture(scope="session")
def indv1_config():
    """会话级 INDV1 配置字典 (含可选 key)"""
    return load_indv1_config()


@pytest.fixture(scope="session")
def test_params(indv1_config):
    """
    会话级测试参数 fixture (fail-fast)

    所有 key 必须存在于 config.json 的 INDV1 节。
    脚本里直接用 test_params["key"] 下标访问, 不要 test_params.get(key, default)。
    """
    required_keys = (
        "acore_ip", "port", "ssh_user",
        "expected_i2c8_claimed", "expected_i2c8_present",
        "fc_uart_dev", "board_test_bin",
    )
    missing = [k for k in required_keys if k not in indv1_config]
    if missing:
        raise KeyError(
            f"config.json 的 INDV1 节缺少必需 key: {missing}。"
            f"请在 config.json 中补齐后再运行测试。"
        )
    return {k: indv1_config[k] for k in required_keys}


@pytest.fixture(scope="session", autouse=True)
def print_startup_info(indv1_config, pytestconfig):
    """测试会话开始时打印环境信息, 便于日志排查"""
    device_type = pytestconfig.getoption("device_type", default="INDV1")
    test_suites = pytestconfig.getoption("test_suites", default="Unknown")
    banner = f"""

============================================================
  INDV1 底软测试环境信息
============================================================
  设备类型:      {device_type}
  测试套件:      {test_suites}
------------------------------------------------------------
  板卡 IP:       {indv1_config.get('acore_ip', '未配置')}
  SSH 端口:      {indv1_config.get('port', '未配置')}
  SSH 用户:      {indv1_config.get('ssh_user', '未配置')}
  跳板(Sophon):  {indv1_config.get('sophon_jump', '未配置')}
  期望板级:      {indv1_config.get('expected_boardid') or '不限'}
  i2c-8 应答设备: {indv1_config.get('expected_i2c8_present', '未配置')}
  i2c-8 被占用:   {indv1_config.get('expected_i2c8_claimed', '未配置')}
  FC 串口:       {indv1_config.get('fc_uart_dev', '未配置')}
  自检程序:      {indv1_config.get('board_test_bin', '未配置')}
============================================================
"""
    log_manager.logger.info(banner)


@pytest.fixture(scope="session")
def ssh_session(indv1_config, test_params):
    """
    会话级 SSH 通道 fixture

    复用 NestRemoteHelper (subprocess + 系统 ssh) 在 INDV1 板卡执行命令。
    ip 为空视为未配置环境, skip 整批; 连通探针失败同样 skip, 避免每用例各自超时。
    """
    if not test_params["acore_ip"]:
        pytest.skip("config.json INDV1.acore_ip 未配置 — 填写板卡 IP 后重跑")
    helper = NestRemoteHelper(
        channel="ssh",
        nest_ip=test_params["acore_ip"],
        ssh_port=test_params["port"],
        ssh_user=test_params["ssh_user"],
        ssh_passwd=indv1_config.get("ssh_passwd", ""),
    )
    # 连通性探针: 失败立即 skip (BatchMode 不支持密码, 常见原因是公钥未配)
    code, _ = helper.exec_cmd_quiet("uname -a", timeout=10)
    if code != 0:
        pytest.skip(
            f"INDV1 SSH 连接失败 ({test_params['acore_ip']}:{test_params['port']})"
            f" — 检查网络 / sshd / ssh 公钥(测试机需 ssh-copy-id); returncode={code}"
        )
    log_manager.logger.info(f"[INDV1-SSH] 连接成功: {test_params['acore_ip']}")
    yield helper


@pytest.fixture(scope="session")
def board_info(ssh_session):
    """
    会话级板卡信息 fixture

    读 /sys/class/boardinfo (dmd-bsp modules/board 落的 sysfs, boardid 为 16 进制):
    返回 {boardid: "0x8", boardid_raw: 原始串, hw_name, hw_version, known: 是否在已知板级表}
    内核模块 / i2c / fc-uart 等用例据此判定板级适用性。
    """
    prefix = "/sys/class/boardinfo"

    def _cat(name):
        code, out = ssh_session.exec_cmd_quiet(f"cat {prefix}/{name}")
        return out.strip() if code == 0 else ""

    boardid_raw = _cat("dmd_boardid")
    info = {
        "boardid_raw": boardid_raw,
        "hw_name": _cat("hw_name"),
        "hw_version": _cat("hw_version"),
    }
    # dmd_board.c 按 16 进制解析 boardid (兼容带/不带 0x 前缀), 归一化成 "0x%x"
    m = re.fullmatch(r"(?:0[xX])?([0-9a-fA-F]+)", boardid_raw)
    if m:
        info["boardid"] = f"0x{int(m.group(1), 16):x}"
    else:
        info["boardid"] = boardid_raw
    # dmd-loadko.sh 已知板级: 0x0=v1p0, 0x1=v1p1, 0x8=v2p0
    info["known"] = info["boardid"] in ("0x0", "0x1", "0x8")
    log_manager.logger.info(
        f"[INDV1] boardid={info['boardid']!r} hw_name={info['hw_name']!r} "
        f"hw_version={info['hw_version']!r} known={info['known']}"
    )
    return info


# ============================================================================
# BSP 专项测试 (CPU/DDR/IPC...) 公共 fixture
# ============================================================================

# BSP 测试参数默认值 — config.json INDV1 节同名 key 可覆盖
BSP_PARAM_DEFAULTS = {
    "expected_cpu_count": 6,           # SMP 全核心数
    "expected_cpu_freq_khz": 1500000,  # CPU 额定频率 1.5GHz
    "boot_capture_timeout_s": 120,     # 串口抓启动日志的最长等待
    "boot_time_max_s": 30,             # 上电→rootfs 挂载上限 (内核时间戳口径)
    "reboot_timeout_s": 300,           # reboot 后 ssh 恢复上限
    "dhrystone_bin": "/usr/hobot/bin/dhrystone",
    "dhrystone_iterations": 10000000,
    "dhrystone_min_dmips": 2000,       # 单核 DMIPS 下限 (记录为主, 阈值可调)
    "cyclictest_max_latency_us": 1000, # 调度时延上限 (PREEMPT_RT 空载应远小于此)
    "cyclictest_duration_s": 10,       # 每场景 cyclictest 时长
    # ---- DDR ----
    "ddr_min_total_mb": 1024,          # MemTotal 下限 (dts 基线 memory=2GB, BPU/CMA 预留后更小; 按实际焊装调整)
    "ddr_memtester_mb": 256,           # memtester/stress-ng 压测内存量
    "ddr_temp_max_c": 85,              # DDR(tmp112) 温度上限 (dts crit=95)
    "ddr_load_duration_s": 60,         # 负载温升场景时长
    # ---- IPC ----
    "ipc_bin_dir": "/usr/hobot/bin",   # dmd-bsp sample 程序目录
    "ipc_loopback_instance": 0,        # 回环通道 (ipcfhal_config.json: cpu2mcu_ins0ch0)
    "ipc_loopback_channel": 0,
    "ipc_loopback_count": 1000,        # 回环测试报文数
    "ipc_loopback_len": 64,            # 回环测试报文长度
    "ipc_min_rate_kbps": 1,            # 回环吞吐下限 (防明显退化, 首跑后校准)
    "ipc_pwm_test_enabled": False,     # PWM 闭环可能驱动真实执行器, 显式开启才跑
    "ipc_pwm_instance": 4,             # dts: mcu_pwm0 = ins4 ch0
    "ipc_pwm_channel": 0,
    "ipc_can_test_enabled": False,     # CAN 闭环可能上真实总线, 显式开启才跑
    "ipc_can_instance": 0,             # CAN 借通用通道打 MCU 侧 CAN (ipcfhal: ins0ch1)
    "ipc_can_channel": 1,
    "ipc_can_count": 200,
    # ---- 业务主流程 (test_indv1_linux_bsp_s100_flow) ----
    "rtsp_test_frames": 150,           # 视频业务端到端跑帧数 (20fps 下约 7.5s)
    "tof_probe_timeout_s": 20,         # TOF 业务运行时长 (timeout -s INT 优雅终止)
    "adsb_enabled": False,             # ADS-B 需真实接收机, 接好后显式开启
    # ---- MCU 代理依赖 (fc_app/dmd_firmware s100_mcu 分支现状: Ipc_Cfg.c 的
    #      instance4 RxCallback 全部为空, 无 pwm/gpio/i2c 对端, 也无回显实现;
    #      MCU 固件实现对端后开启以下开关) ----
    "mcu_proxy_enabled": False,        # MCU i2c/gpio 代理相关用例 (温度/风扇/gpiochip)
    "ipc_loopback_test_enabled": False,# dmd_ipc_test -L: ins0 为 CAN 桥通道, 误发会污染真实 CAN 总线
    # ---- Timesync (test_indv1_linux_bsp_s100_timesync) ----
    "timesync_sample_bin": "/app/timesync_demo/sample_timesync",  # sp-samples 时间同步样例 (不在位则 skip)
    "timesync_sample_timeout_s": 60,   # 时间同步样例运行超时
    "pps_test_enabled": False,         # PPS 需真实 PPS 源接入, 显式开启才跑
    "pps_probe_cmd": "ppstest /dev/pps0",  # PPS 探针命令 (pps-tools; 换源时同步改)
    # ---- SystemInfo (test_indv1_linux_bsp_s100_sysinfo) ----
    "expected_dmd_version": "",        # 期望 DMD_VERSION (/etc/dmd_versions 首行), 空则只验格式
    "thermal_temp_max_c": 110,         # thermal zone 读数上限 (CPU/BPU 满载可超 100°C)
    "emmc_min_size_gb": 8,             # eMMC 容量下限 (按实际焊装调整)
    "fan_min_rpm": 0,                  # 风扇转速下限 (台架不接风扇置 0 仅记录)
    "emmc_write_test_enabled": False,  # eMMC 写压测消耗擦写寿命, 显式开启才跑
    "emmc_write_mb": 256,              # 写压测数据量
    "emmc_write_min_mbps": 10,         # 写速率下限 (防明显退化, 首跑后校准)
    # ---- OTA (test_indv1_linux_bsp_s100_ota) ----
    "ota_tool_bin": "ota_tool",        # 板端 OTA 工具 (PATH 名或绝对路径)
    "ota_dm_verify_expected": True,    # 镜像构建 RDK_DM_VERIFY_ENABLE=yes → cmdline 应含 dm-verity
    "ota_upgrade_enabled": False,      # 系统升级演练会切 slot + reboot, 显式开启才跑
    "ota_install_cmd": "",             # 升级命令模板 (板端执行, 如 ota_tool -i /data/xxx.zip)
    "ota_upgrade_timeout_s": 600,      # 升级命令超时
    # ---- SDR 图传 (test_indv1_linux_bsp_s100_sdr) ----
    "sdr_test_enabled": False,         # 需 SDR 图传模块在位 (fishlink HTTP+AT 链路), 显式开启才跑
    "sdr_runtime_timeout_s": 20,       # dmd_sdr_test 运行超时
    "sdr_pair_cmd": "",                # 对码命令模板 (板端执行, 首跑按 -h 用法填)
    "sdr_config_cmd": "",              # 配置导出/导入命令模板 (板端执行, 首跑按 -h 用法填)
    # ---- Media 扩展 (test_indv1_linux_bsp_s100_media) ----
    "media_rtsp_repeat_test_enabled": False,  # 连续多轮 RTSP 会独占 camera/FPGA, 显式开启才跑
    "media_rtsp_repeat_runs": 2,       # 连续运行轮数
    "media_rtsp_frames": 100,          # 每轮帧数
    "media_codec_bin": "/app/multimedia_samples/sample_codec",  # VPU 编解码样例 (sp-samples)
    "npu_import_probe": "python3 -c 'import hbm_runtime'",      # hobot-dnn pybind11 运行时导入探针
    # ---- WLAN (test_indv1_linux_bsp_s100_wireless) ----
    "wifi_test_enabled": False,        # 需可入网 AP, 显式开启才跑
    "wifi_ssid": "",                   # 入网 SSID (wifi_test_enabled=true 时必填)
    "wifi_psk": "",                    # 入网密码
    "wifi_ping_target": "",            # 连通目标 IP, 空 = ping 默认网关
}


@pytest.fixture(scope="session")
def bsp_params(indv1_config):
    """BSP 专项测试参数: 默认值 + config.json INDV1 节同名 key 覆盖"""
    params = dict(BSP_PARAM_DEFAULTS)
    overridden = [k for k in BSP_PARAM_DEFAULTS if k in indv1_config]
    for k in overridden:
        params[k] = indv1_config[k]
    if overridden:
        log_manager.logger.info(f"[INDV1-BSP] 覆盖 BSP 参数: {overridden}")
    return params


def _acore_console(indv1_config):
    """从 console_com_map 取 Acore 调试串口配置, 返回 (port, baudrate)"""
    com_map = indv1_config.get("console_com_map") or {}
    return com_map.get("J6_Acore"), com_map.get("J6_Acore_baudrate", 115200)


@pytest.fixture(scope="session")
def serial_console(indv1_config):
    """
    会话级调试串口 fixture (Acore 控制台, 取 console_com_map 的 J6_Acore 通道)

    config.json INDV1.console_com_map 未配置 J6_Acore 视为未接串口,
    skip 串口类用例 (启动链/启动时间)。
    """
    port, baudrate = _acore_console(indv1_config)
    if not port:
        pytest.skip(
            "config.json INDV1.console_com_map 未配置 J6_Acore 串口 — 启动日志类用例跳过"
        )
    try:
        from src.Physical.Serial.SerialPortController import SerialPortController
    except ImportError as e:
        pytest.skip(f"未找到 SerialPortController: {e}")
    log_manager.logger.info(f"[INDV1-Serial] 连接调试串口: {port} @ {baudrate}")
    # enable_queue=True: boot_capture 依赖 recv_data() 读队列, 默认构造该队列为关闭状态
    ctrl = SerialPortController(enable_queue=True)
    if not ctrl.connect(port=port, baudrate=baudrate):
        pytest.skip(f"调试串口连接失败: {port} @ {baudrate}")
    yield ctrl
    try:
        ctrl.disconnect()
    except Exception:
        pass


@pytest.fixture(scope="session")
def boot_capture(serial_console, indv1_config, ssh_session, bsp_params):
    """
    会话级冷启动串口日志 (惰性触发一次, 启动链/启动时间用例共用)

    通过 ssh 触发 reboot, 同时从调试串口循环接收直到超时, 全文存档到
    <项目根>/log/boot_capture_<时间戳>.log, 返回解码后的日志文本。
    注意:
      - 首个引用本 fixture 的用例会触发板卡重启 (耗时约 boot_capture_timeout_s)
      - Acore 重启会复位板载 USB 串口桥 (gadget 重枚举): 句柄失效、数据流中断,
        抓取循环检测到 10s 无新数据且未见加载完成标记时自动重连串口
    """
    port, baud = _acore_console(indv1_config)
    serial_console.clear_buffer()
    log_manager.logger.info("[INDV1-Boot] 触发 reboot, 开始抓取启动串口日志 ...")
    ssh_session.exec_cmd_quiet("reboot")
    deadline = time.time() + bsp_params["boot_capture_timeout_s"]
    chunks = []
    last_data_at = time.time()
    while time.time() < deadline:
        try:
            data = serial_console.recv_data(timeout=0.2)
        except Exception:
            data = None
        now = time.time()
        if data:
            chunks.append(data)
            last_data_at = now
        # 10s 无新数据且尚未抓到加载完成标记 → 串口桥大概率随重启重枚举掉了, 重连
        if now - last_data_at > 10 and b"dmd_load_ko_end" not in b"".join(chunks)[-800:]:
            log_manager.logger.warning("[INDV1-Boot] 串口 10s 无数据(疑似板载桥重枚举), 重连串口")
            try:
                serial_console.disconnect()
            except Exception:
                pass
            time.sleep(2)
            try:
                serial_console.connect(port=port, baudrate=baud)
            except Exception:
                pass
            last_data_at = time.time()
            continue
        if b"dmd_load_ko_end" in b"".join(chunks)[-800:]:
            log_manager.logger.info("[INDV1-Boot] 已抓到 dmd_load_ko_end, 提前结束")
            break
        time.sleep(0.2)
    text = b"".join(chunks).decode("utf-8", errors="replace")
    out = Path(get_project_root()) / "logs" / f"boot_capture_{datetime.now():%Y%m%d_%H%M%S}.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    log_manager.logger.info(f"[INDV1-Boot] 启动日志抓取完成 ({len(text)} 字节), 存档: {out}")
    if "systemd-shutdown" in text:
        log_manager.logger.warning(
            "[INDV1-Boot] 抓取内容为 reboot 收尾的关机日志, 本次启动输出未被捕获 — "
            "串口桥重枚举丢失了启动窗口, 含启动链阶段的用例结果请人工复核")
    # reboot 会拖垮板载 USB 串口桥和 Sophon 网络(跳板) — 等待 SSH 链路恢复,
    # 避免后续用例全部打到失联的板子上 (经跳板的 ssh 恢复即代表全链路恢复)
    deadline = time.time() + bsp_params.get("reboot_timeout_s", 300)
    recovered = False
    while time.time() < deadline:
        code, _ = ssh_session.exec_cmd_quiet("true", timeout=10)
        if code == 0:
            recovered = True
            log_manager.logger.info("[INDV1-Boot] 板卡 SSH 链路已恢复")
            break
        time.sleep(5)
    if not recovered:
        pytest.fail(
            "板卡 reboot 后 SSH 链路未在 reboot_timeout_s 内恢复 — 依赖 boot_capture "
            "的用例提前终止, 避免后续用例在失联通道上级联失败。"
            "排查顺序: ① 跳板 Sophon 的 WiFi/IP 是否漂移(近三次构建均为跳板掉线, "
            "非板卡问题) ② Acore 的 sshd/网络是否起来(COM9 串口登录查 "
            "systemctl status ssh / ip addr)", banner=False,
        )
    return text


# ============================================================================
# 失败自动导出板端日志 (pytest_runtest_makereport + adb)
#
# 板端日志位置 (来源: rdk 源码):
#   - /log/fc/message*    fc-logger.service 飞控串口日志 (hrut_remoteproc_log, 20MB x 15 轮转)
#   - /sys/fs/pstore/     内核 ramoops (CONFIG_PSTORE_RAM/CONSOLE/PMSG=y), panic/上次启动日志
#   - dmesg / journalctl  内核环形缓冲 / systemd 服务日志 (dmd-loadko 等)
# adbd 由镜像 hobot-adbd.service 提供 (USB gadget 方式, 插 USB-C 即可)
# ============================================================================

_ADB_SUBDIR = Path("tools") / "platform-tools-adb" / "adb.exe"
_ADB_TIMEOUT_SHELL = 300      # dmesg / journalctl 单命令超时
_ADB_TIMEOUT_PULL = 600       # adb pull 超时 (fc 日志最坏 300MB)
_ADB_NO_DEVICE = "<no-adb-device>"


def _find_adb_exe() -> str:
    """优先用仓库自带 tools/platform-tools-adb/adb.exe, 否则回退 PATH 上的 adb"""
    candidate = Path(get_project_root()) / _ADB_SUBDIR
    if candidate.exists():
        return str(candidate)
    return "adb"


def _run_adb(adb_exe, adb_args, timeout):
    """执行 adb 命令, 返回 (returncode, 合并输出); 异常归一为负返回码, 不向上抛"""
    try:
        proc = subprocess.run(
            [adb_exe, *adb_args],
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return -124, f"adb timeout after {timeout}s: {' '.join(adb_args)}"
    except (OSError, ValueError) as e:
        return -1, f"adb exec failed: {e}"


def _find_adb_exe_and_prefix(cfg):
    """确定 adb 可执行文件与 -s 序列号前缀

    序列号: config.json INDV1.adb_serial 优先; 未配置且恰好一台设备在线时自动使用。
    返回 (adb_exe, ["-s", serial] 或 [], 错误信息或 None)
    """
    adb_exe = _find_adb_exe()
    code, out = _run_adb(adb_exe, ["devices"], 15)
    if code != 0:
        return adb_exe, [], f"adb devices 执行失败: {out.strip()}"
    serials = []
    for ln in out.splitlines()[1:]:
        parts = ln.split()
        if len(parts) == 2 and parts[1] == "device":
            serials.append(parts[0])
    serial_cfg = (cfg.get("adb_serial") or "").strip()
    if serial_cfg:
        if serial_cfg not in serials:
            return adb_exe, [], f"配置的 adb_serial={serial_cfg!r} 不在线 (在线: {serials})"
        return adb_exe, ["-s", serial_cfg], None
    if len(serials) == 1:
        return adb_exe, ["-s", serials[0]], None
    if not serials:
        return adb_exe, [], "未检测到在线 adb 设备 (检查 USB 连接与 hobot-adbd.service)"
    return adb_exe, [], f"检测到多台 adb 设备 {serials}, 请在 config.json INDV1.adb_serial 指定"


def _dump_device_logs(item):
    """断言失败时把板端日志导出到 <项目根>/logs/adb/<脚本名>_<时间戳>/

    任何一步失败只记 warning, 绝不影响测试结果上报。
    """
    try:
        cfg = load_indv1_config()
        adb_exe, serial_prefix, err = _find_adb_exe_and_prefix(cfg)
        if err:
            log_manager.logger.warning(f"[INDV1-LogDump] 跳过日志导出: {err}")
            return

        script_name = Path(item.fspath).stem
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_root = Path(get_project_root()) / "logs" / "adb"
        out_dir = log_root / f"{script_name}_{stamp}"
        idx = 1
        while out_dir.exists():  # 同一秒内多个失败用例, 追加序号避免覆盖
            out_dir = log_root / f"{script_name}_{stamp}_{idx}"
            idx += 1
        out_dir.mkdir(parents=True)

        def _shell_to_file(cmd, filename, timeout=_ADB_TIMEOUT_SHELL):
            code, out = _run_adb(adb_exe, [*serial_prefix, "shell", cmd], timeout)
            (out_dir / filename).write_text(out, encoding="utf-8", errors="replace")
            tag = "OK" if code == 0 else f"code={code}"
            log_manager.logger.info(f"[INDV1-LogDump] {filename}: {tag}")

        def _pull(remote, dirname):
            code, out = _run_adb(
                adb_exe,
                [*serial_prefix, "pull", remote, str(out_dir / dirname)],
                _ADB_TIMEOUT_PULL,
            )
            tag = "OK" if code == 0 else f"code={code}"
            log_manager.logger.info(f"[INDV1-LogDump] pull {remote}: {tag}")

        log_manager.logger.info(f"[INDV1-LogDump] 用例 {item.name} 断言失败, 导出日志到 {out_dir}")
        print(f"\n[INDV1-LogDump] 导出板端日志 -> {out_dir}", flush=True)

        _shell_to_file("dmesg", "dmesg.log")
        _shell_to_file("journalctl -b --no-pager", "journalctl.log")
        _pull("/log/fc", "log_fc")              # 飞控串口日志 (fc-logger 落盘)
        _pull("/sys/fs/pstore", "pstore")       # 内核 panic / 上次启动 ramoops
        _pull("/var/log/syslog", "syslog")      # Ubuntu syslog (可能不存在, 失败可忽略)
        log_manager.logger.info(f"[INDV1-LogDump] 完成: {out_dir}")
    except Exception as e:  # noqa: BLE001 — 日志导出绝不能影响测试执行
        log_manager.logger.warning(f"[INDV1-LogDump] 导出异常 (已忽略): {e}")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """用例断言失败 (call 阶段) 或 fixture 异常 (setup 阶段) 时, 立刻导出板端日志"""
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        _dump_device_logs(item)
