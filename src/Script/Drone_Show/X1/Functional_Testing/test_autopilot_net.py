# coding: utf-8

"""
AUTOPILOT NET 网络配置管理自动化 — EULER_NETWORK(49) WiFi 配置读/写/校验

来源（Common_Testing 通用功能点脚本库第二成员）：
    - 需求：C:\\git_dmd\\l5_test\\通用无人机测试需求\\AUTOPILOT-REQ-NET-0001~0005.md
    - 用例：C:\\git_dmd\\l5_test\\通用无人机测试用例库\\AUTOPILOT-TC-NET-0001~0018.md
    - 目标：把 NET 模块 18 条用例中可纯软件自动化的部分落地（allure story
      直接挂 TC 编号，可追溯）

EULER_NETWORK(49) v44 布局（<IB16B32B，crc_extra=194）：
    id    uint32  IP 地址（大端打包，复用 wifi.ip_to_uint32）
    cmd   uint8   位域（NET-0001 §3）：
                  bit0=写 IP   bit1=写 SSID   bit2=写密码
                  bit4=读配置  bit5=应答帧标志（飞机→地面站方向）
    ssid  char[16] SSID（补零）
    psk   char[32] WiFi 密码（补零）
    ⚠️ 仅 v44 有完整布局；v41 等旧 dialect 只有 id+ssid[8]（无 cmd/psk），
    本文件带 dialect 守卫自动 skip（L5/V3/V41 等机型）

18 条用例覆盖矩阵：
    ┌──────────┬───────────────┬──────────────────────────────┐
    │ TC       │ 分类           │ 落地方式                      │
    ├──────────┼───────────────┼──────────────────────────────┤
    │ NET-0001 │ 危险门控(同值写)│ test_net0001_writeback_same_values │
    │          │               │ test_net0001_combo_bit_semantics │
    │ NET-0002 │ 安全           │ test_net0002_reject_error_codes │
    │ NET-0003 │ 阻塞           │ skip 桩：213/214 无 dialect   │
    │ NET-0004 │ 半自动         │ 物理重连验证人工；ACK 即完成   │
    │          │               │ 的口径由写类用例天然覆盖       │
    │ NET-0005 │ 安全           │ test_net0005_read_current_config │
    │ NET-0006 │ 毁灭门控       │ test_net0006_legal_boundary_values │
    │ NET-0007 │ 排除           │ 地面站前端拦截（GCS 软件）     │
    │ NET-0008 │ 排除           │ 同上                         │
    │ NET-0009 │ 安全           │ test_net0009_fc_format_reject │
    │ NET-0010 │ 安全           │ test_net0010_dialect_alignment │
    │ NET-0011 │ 阻塞+排除      │ 串口 codec 缺口 + GCS 弹窗    │
    │ NET-0012 │ 排除           │ GCS UI                       │
    │ NET-0013 │ 阻塞           │ skip 桩：串口 codec 缺口      │
    │ NET-0014 │ 排除           │ GCS UI                       │
    │ NET-0015 │ 排除           │ GCS UI（密码历史下拉）        │
    │ NET-0016 │ 排除           │ 物理 USB + GCS UI            │
    │ NET-0017 │ 危险门控(同值写)│ test_net0017_no_sender_permission_check │
    │ NET-0018 │ 排除           │ 地面站侧权限（GCS 软件）      │
    └──────────┴───────────────┴──────────────────────────────┘
    合计：7 条 TC 自动化（8 个 test）+ 2 个阻塞 skip 桩 + 1 半自动 + 8 排除

用例级口径：
    - NET-0005：cmd=bit4 读请求 → 飞机应答帧（bit5 置位）携带 IP/SSID/
      密码。真机首跑为探测：应答帧存在即通过，字段语义记录存档
    - NET-0010：codec 层 msg49 构造→打包→重解析字段一致；真机层应答帧
      在同 dialect 下字段对齐可解析；dialect 定义版本与 git hash 存档
    - NET-0009：绕过地面站前端直发 MAVLink 非法值：7 字符/32 字符密码、
      含空格/中文/制表符/换行密码、9 字节 SSID（超需求 1~8 上限）→ 期望
      ACK 非 ACCEPTED；随后读校验配置未变。SSID 1~8 为需求口径，codec
      ssid[16]，差异记录为发现
    - NET-0002：可注入失败路径：写位置位但载荷为空（SSID/密码空串）、
      无任何写位的 cmd=0；存储满/忙不可经 MAVLink 注入，记录为不可自动
      化；地面站 UI 展示属 GCS 软件（NET-0007/0008/0012/0014 口径）
    - NET-0001 同值写回：合并位 bit0|1|2 写回备份值（配置不变、链路不
      掉）→ ACK result=0 → 读校验一致，覆盖写请求接收→解析→写入→应答
      全链路；物理重连验证（新密码连接）属半自动人工证据
    - NET-0001 位域组合（TC-0001 步骤 1/3/5）：仅 bit2（只改密码）；
      bit0|1|2（三项合并）；bit0|1 不带 bit2（向后兼容——密码必须保持
      不变）。全部使用备份同值，验证位域语义而非改值
    - NET-0006：合法边界 8 字符（下界）/31 字符（上界）/纯符号/混合 →
      每档写入→ACK→读校验，最后还原备份。⚠️ 真改密码可能短暂影响 WiFi
      连接（当前链路为有线 UDP 时无影响），人在场执行
    - NET-0017：REQ-NET-0005 飞控侧无权限校验——用第二个地面站套接字
      （sys_id=42，独立本地端口）发同值合法写 → 应与主站同样 ACCEPTED；
      发非法格式 → 仅因格式被拒（证明拒绝源于格式而非身份）
    - NET-0003/0013（skip 桩）：GET_WIFI_PASSWORD(213)/WIFI_PASSWORD_
      INFO(214) 在所有 mavlink_config_v*.json 与串口协议层均无定义；
      解除阻塞需开发提供报文定义 → 补 dialect JSON → 串口层封装

安全门控（默认全关）：
    AUTOPILOT_NET_ENABLE_DANGEROUS=1     同值写回（走写路径但不改值，
                                        链路不掉）
    AUTOPILOT_NET_ENABLE_DESTRUCTIVE=1   真改配置值（NET-0006 边界密码），
                                        可能断 WiFi 链路，需人在场
    写类用例一律挂 net_config_guard：先读备份 → 测试 → 还原 → 读校验，
    还原失败硬失败并附恢复指引（出厂默认密码 szdamoda）

已知规格-代码差异（记录为发现，不臆造）：
    - SSID 长度：需求 NET-0009 说 1~8 字节，v44 codec ssid[16]
    - IP 字段：无独立 IP 字段，复用 id(uint32)
    - 串口 WiFi 密码报文 GET_WIFI_PASSWORD(213)/WIFI_PASSWORD_INFO(214)
      在所有 mavlink_config_v*.json 中均无定义 → 串口类用例阻塞
"""

import io
import json
import os
import socket
import sys
import time

import pytest
import allure

from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from src.Protocol.wifi.wifi import ip_to_uint32
from utils.logger import log_manager


# ============================================================================
# 安全门控
# ============================================================================

ENABLE_DANGEROUS = os.environ.get("AUTOPILOT_NET_ENABLE_DANGEROUS", "0") == "1"
ENABLE_DESTRUCTIVE = os.environ.get("AUTOPILOT_NET_ENABLE_DESTRUCTIVE", "0") == "1"

dangerous_gate = pytest.mark.skipif(
    not ENABLE_DANGEROUS,
    reason="同值写回用例：需设置环境变量 AUTOPILOT_NET_ENABLE_DANGEROUS=1 "
           "（写路径生效但不改变配置值，链路保持）")

destructive_gate = pytest.mark.skipif(
    not ENABLE_DESTRUCTIVE,
    reason="真改配置用例：需设置环境变量 AUTOPILOT_NET_ENABLE_DESTRUCTIVE=1 "
           "并确认人在场（可能断 WiFi 链路，还原失败时用默认密码 szdamoda "
           "恢复）")

# ============================================================================
# 报文/位域常量（NET-0001 §3，真机语义未验证——首跑按探测处理）
# ============================================================================

MSG_ID_HEARTBEAT = 0
MSG_ID_EULER_NETWORK = 49
MSG_ID_COMMAND_ACK = 77
MSG_ID_STATUSTEXT = 253

NET_CMD_SET_IP = 0x01      # bit0：写 IP
NET_CMD_SET_SSID = 0x02    # bit1：写 SSID
NET_CMD_SET_PSK = 0x04     # bit2：写密码
NET_CMD_READ = 0x10        # bit4：读当前配置
NET_CMD_ANSWER = 0x20      # bit5：应答帧（飞机→地面站）

SSID_FIELD_LEN = 16
PSK_FIELD_LEN = 32

# 出厂默认 WiFi 密码（NET-0004：恢复指引用）
DEFAULT_WIFI_PSK = "szdamoda"

NET_READ_TIMEOUT = 5.0
NET_WRITE_ACK_TIMEOUT = 8.0
NET_RESTORE_RETRIES = 3


def _pad_field(text, length):
    """字符串补零到定长字段（字节列表）"""
    raw = (text or "").encode('utf-8')[:length]
    return list(raw) + [0] * (length - len(raw))


def _strip_field(value):
    """从定长字段提取字符串（兼容 bytes/list）"""
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    elif isinstance(value, (list, tuple)):
        raw = bytes(value)
    else:
        return str(value) if value else ""
    return raw.rstrip(b'\x00').decode('utf-8', errors='replace')


def _uint32_to_ip(value):
    """uint32 → IP 字符串（与 ip_to_uint32 互逆，大端）"""
    value = int(value) & 0xFFFFFFFF
    return f"{(value >> 24) & 0xFF}.{(value >> 16) & 0xFF}.{(value >> 8) & 0xFF}.{value & 0xFF}"


def _format_msg_detail(msg):
    """格式化消息详情（利用 MAVLink_message.print() 的输出）"""
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        msg.print()
        return sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout


def _make_euler_network(cmd_bits, version, ip=None, ssid=None, psk=None,
                        sys_id=1):
    """构造 EULER_NETWORK(49) 消息（v44 完整布局）

    Args:
        cmd_bits: cmd 位域（NET_CMD_* 组合）
        ip: IP 字符串（None 则 id=0，固件视为不改 IP）
        ssid/psk: 字符串（None 则字段全零）
    """
    return MAVLink_message(
        msg_id=MSG_ID_EULER_NETWORK, sys_id=sys_id, comp_id=1, seq=0,
        version=version,
        fields={'id': ip_to_uint32(ip) if ip else 0,
                'cmd': cmd_bits,
                'ssid': _pad_field(ssid, SSID_FIELD_LEN),
                'psk': _pad_field(psk, PSK_FIELD_LEN)})


def _dialect_supports_euler_network(version):
    """检查 active dialect 的 msg 49 是否含 cmd/psk 字段（v44 完整布局）"""
    try:
        config = MAVLink_message._load_config(str(version))
        m49 = config.get(MSG_ID_EULER_NETWORK)
        if not m49:
            return False
        variables = m49.get('variables', [])
        return 'cmd' in variables and 'psk[0]' in variables
    except Exception:
        return False


# ============================================================================
# 测试类
# ============================================================================

@allure.epic("通用无人机 AUTOPILOT")
@allure.feature("NET 网络配置管理")
@allure.tag("AUTOPILOT_COMMON", "NET")
@pytest.mark.functional
class TestAutopilotNet:
    """NET 模块自动化 — EULER_NETWORK 读/写/校验（7 TC → 8 用例 + 2 桩）"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, drone_ip, drone_port, mavlink_version):
        """前置：dialect 守卫 + 地面站发现飞机；后置：关闭地面站"""
        if not _dialect_supports_euler_network(mavlink_version):
            pytest.skip(
                f"当前 dialect v{mavlink_version} 的 EULER_NETWORK(49) 为旧布局"
                f"（无 cmd/psk 字段），NET 套件要求 v44+（X1/L3/V4）")

        self.drone_ip = drone_ip
        self.drone_port = drone_port
        self.mavlink_version = mavlink_version
        self._wrote_config = False        # net_config_guard 用

        with allure.step("初始化地面站并发现飞机（等心跳）"):
            self.gcs = GroundControlStation(drone_ip=drone_ip, drone_port=drone_port)
            log_manager.log_and_attach(
                f"地面站初始化完成，本地地址: {self.gcs.local_ip}:{self.gcs.local_port}",
                "初始化信息")
            hb, addr = self.gcs.wait_for_message([MSG_ID_HEARTBEAT], timeout=15.0)
            assert hb is not None, "15s 内未收到飞机心跳，飞机不在线"
            if addr and addr[0] != drone_ip:
                log_manager.log_and_attach(
                    f"心跳来源 {addr[0]} 与配置 IP {drone_ip} 不一致", "警告")
            self._clear_recv_buffer()

        yield

        with allure.step("清理测试资源"):
            self.gcs.close()
            log_manager.log_and_attach("地面站已关闭", "清理信息")

    @pytest.fixture
    def net_config_guard(self):
        """写类用例的配置备份/还原守卫

        setup：读当前配置存档；teardown：若发生过写入，还原原值并读校验，
        校验失败硬失败（附恢复指引：默认密码 szdamoda / 串口恢复）。
        """
        backup = self._read_net_config(retries=3)
        assert backup is not None, "无法读取当前网络配置，放弃执行写类用例"
        log_manager.log_and_attach(
            f"配置备份: ip={backup['ip']}, ssid={backup['ssid']!r}, "
            f"psk={'<保密不回显>' if backup['psk'] else '(空)'}", "配置备份")
        self._backup = backup
        self._wrote_config = False
        yield backup
        if self._wrote_config:
            self._restore_net_config(backup)

    # ==================================================================
    # 底层收发
    # ==================================================================

    def _clear_recv_buffer(self):
        """清空 UDP 接收缓冲区残留报文"""
        self.gcs.sock.settimeout(0.1)
        try:
            while True:
                data, _ = self.gcs.sock.recvfrom(4096)
                if not data:
                    break
        except socket.timeout:
            pass
        finally:
            self.gcs.sock.settimeout(self.gcs.recv_timeout)

    def _read_net_config(self, retries=1):
        """发 EULER_NETWORK 读请求（cmd=bit4）并等应答帧（bit5）

        Returns: {'ip','ssid','psk'} dict；失败返回 None。
        真机首跑按探测处理：应答帧语义（bit4→bit5、是否回 ACK）先记录后
        收紧断言。
        """
        for _ in range(retries):
            self._clear_recv_buffer()
            msg = _make_euler_network(NET_CMD_READ, self.mavlink_version)
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            log_manager.log_and_attach(
                "发送 EULER_NETWORK 读请求 (cmd=bit4)", "NET 读请求")
            answer = self._wait_net_answer(NET_READ_TIMEOUT)
            if answer is not None:
                return self._parse_net_config(answer)
            time.sleep(0.5)
        log_manager.log_and_attach(
            f"读配置无应答（{retries} 次重试后）", "警告")
        return None

    def _wait_net_answer(self, timeout):
        """等待飞机的 EULER_NETWORK 应答帧（cmd bit5 置位）"""
        start = time.time()
        while time.time() - start < timeout:
            received, addr = self.gcs.receive()
            if (received is not None
                    and received.msg_id == MSG_ID_EULER_NETWORK
                    and addr and addr[0] == self.drone_ip):
                cmd = received.fields.get('cmd', 0)
                if cmd & NET_CMD_ANSWER:
                    log_manager.log_and_attach(
                        _format_msg_detail(received), "NET 应答帧详情")
                    return received
                log_manager.log_and_attach(
                    f"收到 msg49 但 bit5 未置位 (cmd=0x{cmd:02x})", "警告")
            time.sleep(0.02)
        return None

    def _parse_net_config(self, msg):
        """解析应答帧 → {'ip','ssid','psk'}"""
        fields = msg.fields
        config = {
            'ip': _uint32_to_ip(fields.get('id', 0)),
            'ssid': _strip_field(fields.get('ssid', b'')),
            'psk': _strip_field(fields.get('psk', b'')),
        }
        # 密码是敏感信息：报告只记录长度，不回显内容
        log_manager.log_and_attach(
            f"当前配置: ip={config['ip']}, ssid={config['ssid']!r}, "
            f"psk_len={len(config['psk'])}", "NET 配置读取")
        return config

    def _send_net_write(self, cmd_bits, ip=None, ssid=None, psk=None,
                        sys_id=1):
        """发送 EULER_NETWORK 写请求，等 COMMAND_ACK(command=49) + STATUSTEXT

        Returns: (ack_msg_or_None, [statustext, ...])
        """
        msg = _make_euler_network(cmd_bits, self.mavlink_version,
                                  ip=ip, ssid=ssid, psk=psk, sys_id=sys_id)
        self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
        log_manager.log_and_attach(
            f"cmd=0x{cmd_bits:02x}, ip={ip or '(不改)'}, "
            f"ssid={ssid or '(不改)'}, psk={'***' if psk else '(不改)'}",
            "NET 写请求")
        self._wrote_config = True

        ack, texts = None, []
        ack_at = None
        start = time.time()
        while True:
            now = time.time()
            if ack is not None and now - ack_at >= 1.0:
                break
            if ack is None and now - start >= NET_WRITE_ACK_TIMEOUT:
                break
            received, addr = self.gcs.receive()
            if received is None or not addr or addr[0] != self.drone_ip:
                continue
            if (received.msg_id == MSG_ID_COMMAND_ACK
                    and received.fields.get('command') == MSG_ID_EULER_NETWORK
                    and ack is None):
                ack = received
                ack_at = now
                log_manager.log_and_attach(
                    _format_msg_detail(ack), "COMMAND_ACK (command=49)")
            elif received.msg_id == MSG_ID_STATUSTEXT:
                text = _strip_field(received.fields.get('text', b''))
                if text:
                    texts.append(text)
        if ack is None:
            log_manager.log_and_attach(
                f"等待 COMMAND_ACK(command=49) 超时 ({NET_WRITE_ACK_TIMEOUT}s)",
                "警告")
        if texts:
            log_manager.log_and_attach(' | '.join(texts), "STATUSTEXT")
        return ack, texts

    def _restore_net_config(self, backup):
        """还原网络配置（单次合并写 bit0|1|2，避免中间态）并读校验"""
        with allure.step("还原网络配置（写回备份值）"):
            last_error = None
            for attempt in range(1, NET_RESTORE_RETRIES + 1):
                try:
                    ack, _ = self._send_net_write(
                        NET_CMD_SET_IP | NET_CMD_SET_SSID | NET_CMD_SET_PSK,
                        ip=backup['ip'] if backup['ip'] != '0.0.0.0' else None,
                        ssid=backup['ssid'] or None,
                        psk=backup['psk'] or None)
                    if ack is not None and ack.fields.get('result') == 0:
                        time.sleep(2.0)      # 等配置热加载
                        break
                    last_error = f"还原 ACK 异常: {ack.fields if ack else '超时'}"
                except Exception as e:
                    last_error = str(e)
                log_manager.log_and_attach(
                    f"还原第 {attempt} 次失败: {last_error}", "还原重试")
            current = self._read_net_config(retries=3)
            restored = (current is not None
                        and current['ssid'] == backup['ssid']
                        and current['psk'] == backup['psk']
                        and (not backup['ip'] or backup['ip'] == '0.0.0.0'
                             or current['ip'] == backup['ip']))
            assert restored, (
                f"网络配置还原失败！备份: ssid={backup['ssid']!r} ip={backup['ip']}，"
                f"当前: ssid={(current['ssid'] if current else None)!r} "
                f"ip={current['ip'] if current else None}。"
                f"恢复手段：① 用当前/默认密码 {DEFAULT_WIFI_PSK!r} 重连后改回；"
                f"② 串口恢复（NET-0004）；last_error={last_error}")

    # ==================================================================
    # NET-0005 读取当前配置（安全，读使能器）
    # ==================================================================

    @allure.story("AUTOPILOT-TC-NET-0005")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.title("NET-0005 EULER_NETWORK 读取当前 WiFi 配置")
    def test_net0005_read_current_config(self):
        """读当前配置（NET-0005 正常流程，安全只读）"""
        with allure.step("发送读请求并等待应答帧"):
            config = self._read_net_config(retries=2)
            assert config is not None, (
                "EULER_NETWORK 读请求无应答帧（bit5）——读链路未实现或语义"
                "与 NET-0001 §3 不符（真机首跑探测结论，需对照固件确认）")
        with allure.step("应答字段合理性记录（IP 格式 / SSID 非空）"):
            assert config['ip'] == '0.0.0.0' or config['ip'].count('.') == 3, (
                f"应答 IP 字段格式异常: {config['ip']!r}")
            log_manager.log_and_attach(
                f"IP={'(未上报)' if config['ip'] == '0.0.0.0' else config['ip']}, "
                f"SSID={'(未上报)' if not config['ssid'] else config['ssid']}, "
                f"密码长度={len(config['psk'])}", "读取结果")

    # ==================================================================
    # NET-0010 MAVLink 协议版本一致性（安全）
    # ==================================================================

    @allure.story("AUTOPILOT-TC-NET-0010")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.title("NET-0010 EULER_NETWORK dialect 一致性")
    def test_net0010_dialect_alignment(self):
        """协议版本一致性（NET-0010，无硬件部分 + 真机应答对齐）"""
        with allure.step("codec 往返自检（构造 → hex → 重解析）"):
            probe = _make_euler_network(
                NET_CMD_SET_IP | NET_CMD_SET_PSK,
                self.mavlink_version,
                ip="172.19.210.29", ssid="probe_ssid", psk="12345678")
            hex_data = probe.hex_data
            reparsed = MAVLink_message(version=self.mavlink_version)
            reparsed.unpack(hex_data)      # hex 串解析，自动展开 payload 字段
            assert reparsed.fields.get('cmd') == NET_CMD_SET_IP | NET_CMD_SET_PSK
            assert _strip_field(reparsed.fields.get('ssid', b'')) == "probe_ssid"
            assert _strip_field(reparsed.fields.get('psk', b'')) == "12345678"
            assert _uint32_to_ip(reparsed.fields.get('id', 0)) == "172.19.210.29"
            log_manager.log_and_attach(hex_data, "msg49 编解码自检 hex")

        with allure.step("dialect 环境证据存档"):
            config = MAVLink_message._load_config(str(self.mavlink_version))
            log_manager.log_and_attach(
                f"msg49 定义: {json.dumps(config.get(49), ensure_ascii=False)[:300]}",
                "dialect 定义")
            config = self._read_net_config(retries=1)
            log_manager.log_and_attach(
                "真机应答帧可解析 ✓" if config is not None
                else "真机无应答帧（见 NET-0005 探测结论）",
                "真机对齐结论")

    # ==================================================================
    # NET-0009 飞控侧格式二次校验（安全，非法格式矩阵）
    # ==================================================================

    @allure.story("AUTOPILOT-TC-NET-0009")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.title("NET-0009 飞控侧密码/SSID 格式二次校验")
    def test_net0009_fc_format_reject(self):
        """非法格式矩阵 → 拒绝且配置不变（NET-0009 异常路径，只读安全）"""
        config_before = self._read_net_config(retries=2)
        assert config_before is not None, "前置读配置失败，无法比对"

        illegal_cases = [
            ("密码 7 字符（<8）", NET_CMD_SET_PSK, None, None, "1234567"),
            ("密码 32 字符（>31）", NET_CMD_SET_PSK, None, None, "a" * 32),
            ("密码含空格", NET_CMD_SET_PSK, None, None, "12345 78"),
            ("密码含中文", NET_CMD_SET_PSK, None, None, "密码12345"),
            ("密码含制表符", NET_CMD_SET_PSK, None, None, "1234\t5678"),
            ("密码含换行", NET_CMD_SET_PSK, None, None, "1234\n5678"),
            ("SSID 9 字符（超需求上限）", NET_CMD_SET_SSID, None, "123456789", None),
        ]
        for desc, cmd_bits, ip, ssid, psk in illegal_cases:
            with allure.step(f"非法用例: {desc} → 期望拒绝"):
                ack, texts = self._send_net_write(cmd_bits, ip=ip, ssid=ssid,
                                                  psk=psk)
                assert ack is not None, f"{desc}：无 COMMAND_ACK(command=49)"
                result = ack.fields.get('result')
                log_manager.log_and_attach(
                    f"{desc} → ACK result={result}, STATUSTEXT={texts}",
                    "格式校验结论")
                assert result != 0, (
                    f"{desc} 被接受（result=0）——飞控侧二次校验失效"
                    f"（NET-0002/0009 格式规则）")

        with allure.step("读校验：配置应未被非法值污染"):
            self._wrote_config = False     # 非法值不应生效，无需还原
            config_after = self._read_net_config(retries=2)
            assert config_after is not None, "事后读配置失败"
            assert config_after['ssid'] == config_before['ssid'] and \
                config_after['psk'] == config_before['psk'], (
                f"配置被非法值污染: {config_before} → {config_after}")

    # ==================================================================
    # NET-0002 失败路径与错误码（安全部分）
    # ==================================================================

    @allure.story("AUTOPILOT-TC-NET-0002")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.title("NET-0002 EULER_NETWORK 失败路径（可注入部分）")
    def test_net0002_reject_error_codes(self):
        """空载荷等失败路径 → 错误码口径记录（NET-0002，安全）"""
        config_before = self._read_net_config(retries=2)
        assert config_before is not None, "前置读配置失败"

        failure_cases = [
            ("写 SSID 位但载荷为空", NET_CMD_SET_SSID, None, "", None),
            ("写密码位但载荷为空", NET_CMD_SET_PSK, None, None, ""),
            ("无任何写位的 cmd=0", 0x00, None, None, None),
        ]
        for desc, cmd_bits, ip, ssid, psk in failure_cases:
            with allure.step(f"失败路径: {desc}"):
                ack, texts = self._send_net_write(cmd_bits, ip=ip, ssid=ssid,
                                                  psk=psk)
                result = ack.fields.get('result') if ack else None
                log_manager.log_and_attach(
                    f"{desc} → ACK result={result}, STATUSTEXT={texts}",
                    "错误码口径")
                assert ack is not None, f"{desc}：无 ACK"

        with allure.step("读校验：配置未变（空载荷不应清空配置）"):
            self._wrote_config = False
            config_after = self._read_net_config(retries=2)
            assert config_after is not None and \
                config_after['ssid'] == config_before['ssid'], (
                f"空载荷写导致配置变化: {config_before} → {config_after}")

    # ==================================================================
    # NET-0001 写路径（危险门控：同值写回）
    # ==================================================================

    @allure.story("AUTOPILOT-TC-NET-0001")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("NET-0001 EULER_NETWORK 同值写回（写路径贯通）")
    @dangerous_gate
    def test_net0001_writeback_same_values(self, net_config_guard):
        """同值写回（NET-0001 正常流程，危险门控）"""
        backup = net_config_guard
        with allure.step("写回备份值 (bit0|1|2 合并写，避免中间态)"):
            ack, texts = self._send_net_write(
                NET_CMD_SET_IP | NET_CMD_SET_SSID | NET_CMD_SET_PSK,
                ip=backup['ip'] if backup['ip'] != '0.0.0.0' else None,
                ssid=backup['ssid'] or None,
                psk=backup['psk'] or None)
            assert ack is not None, "写请求无 COMMAND_ACK(command=49)"
            assert ack.fields.get('result') == 0, (
                f"同值写回被拒 result={ack.fields.get('result')}, "
                f"STATUSTEXT={texts}")
        with allure.step("读校验：配置应与备份一致"):
            time.sleep(2.0)      # 等热加载
            current = self._read_net_config(retries=2)
            assert current is not None, "写后读配置失败"
            assert current['ssid'] == backup['ssid'] and \
                current['psk'] == backup['psk'], (
                f"同值写回后配置漂移: {backup} → {current}")

    @allure.story("AUTOPILOT-TC-NET-0001")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("NET-0001 cmd 位域组合语义（同值写）")
    @dangerous_gate
    def test_net0001_combo_bit_semantics(self, net_config_guard):
        """cmd 位域组合语义（NET-0001，危险门控同值写）"""
        backup = net_config_guard
        combos = [
            ("仅 bit2（密码位）", NET_CMD_SET_PSK),
            ("bit0|1|2（三项合并）",
             NET_CMD_SET_IP | NET_CMD_SET_SSID | NET_CMD_SET_PSK),
            ("bit0|1（不带 bit2，向后兼容）", NET_CMD_SET_IP | NET_CMD_SET_SSID),
        ]
        for desc, cmd_bits in combos:
            with allure.step(f"{desc} 同值写 → ACK + 读校验"):
                ack, texts = self._send_net_write(
                    cmd_bits,
                    ip=backup['ip'] if backup['ip'] != '0.0.0.0' else None,
                    ssid=backup['ssid'] or None,
                    psk=backup['psk'] or None)
                assert ack is not None, f"{desc}：无 ACK"
                assert ack.fields.get('result') == 0, (
                    f"{desc} 被拒 result={ack.fields.get('result')}, "
                    f"STATUSTEXT={texts}")
                time.sleep(2.0)
                current = self._read_net_config(retries=2)
                assert current is not None, f"{desc}：写后读失败"
                assert current['ssid'] == backup['ssid'] and \
                    current['psk'] == backup['psk'], (
                    f"{desc} 后配置漂移: {backup} → {current}")

    # ==================================================================
    # NET-0006 合法边界密码（毁灭门控：真改值）
    # ==================================================================

    @allure.story("AUTOPILOT-TC-NET-0006")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("NET-0006 合法密码边界值（真改值 + 还原）")
    @destructive_gate
    def test_net0006_legal_boundary_values(self, net_config_guard):
        """合法密码边界值矩阵（NET-0006，毁灭门控）"""
        backup = net_config_guard
        cases = [
            ("下界 8 字符", "12345678"),
            ("上界 31 字符", "a" * 31),
            ("纯符号", "!@#$%^&*"),
            ("混合", "Ab3$de9f"),
        ]
        for desc, psk in cases:
            with allure.step(f"写入合法密码: {desc} → ACK → 读校验"):
                ack, texts = self._send_net_write(NET_CMD_SET_PSK, psk=psk)
                assert ack is not None, f"{desc}：无 ACK"
                assert ack.fields.get('result') == 0, (
                    f"{desc} 被拒 result={ack.fields.get('result')}, "
                    f"STATUSTEXT={texts}")
                time.sleep(2.0)
                current = self._read_net_config(retries=2)
                assert current is not None and current['psk'] == psk, (
                    f"{desc} 读校验失败: 期望 psk_len={len(psk)}, "
                    f"实际 {current['psk'] if current else None!r}")
        # net_config_guard teardown 负责还原备份密码

    # ==================================================================
    # NET-0017 飞控侧无权限校验（危险门控：第二发送源同值写）
    # ==================================================================

    @allure.story("AUTOPILOT-TC-NET-0017")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.title("NET-0017 飞控侧不校验发送方权限")
    @dangerous_gate
    def test_net0017_no_sender_permission_check(self, net_config_guard):
        """双发送源同值写对比（NET-0017，危险门控）"""
        backup = net_config_guard
        with allure.step("建立第二地面站源 (sys_id=42, 独立端口)"):
            second_gcs = GroundControlStation(
                local_ip="0.0.0.0", local_port=14552,
                drone_ip=self.drone_ip, drone_port=self.drone_port)
            try:
                with allure.step("第二源发同值合法写 → 应与主站一致 ACCEPTED"):
                    msg = _make_euler_network(
                        NET_CMD_SET_IP | NET_CMD_SET_SSID | NET_CMD_SET_PSK,
                        self.mavlink_version,
                        ip=backup['ip'] if backup['ip'] != '0.0.0.0' else None,
                        ssid=backup['ssid'] or None,
                        psk=backup['psk'] or None,
                        sys_id=42)
                    second_gcs.send(msg, addr=(self.drone_ip, self.drone_port))
                    ack = self._wait_ack_49(NET_WRITE_ACK_TIMEOUT)
                    assert ack is not None, "第二源写请求无 ACK"
                    assert ack.fields.get('result') == 0, (
                        f"第二源(sys_id=42)同值写被拒 result="
                        f"{ack.fields.get('result')}——若非格式原因，说明飞控"
                        f"做了发送方权限校验，与 REQ-NET-0005 口径不符")
                with allure.step("第二源发非法格式 → 仅因格式被拒"):
                    bad = _make_euler_network(
                        NET_CMD_SET_PSK, self.mavlink_version,
                        psk="1234567", sys_id=42)      # 7 字符非法
                    second_gcs.send(bad, addr=(self.drone_ip, self.drone_port))
                    ack = self._wait_ack_49(NET_WRITE_ACK_TIMEOUT)
                    assert ack is not None, "非法格式写无 ACK"
                    assert ack.fields.get('result') != 0, (
                        "第二源非法格式被接受——格式校验失效（与身份无关的"
                        "格式拒绝才证明 0007 断言成立）")
            finally:
                second_gcs.close()

    def _wait_ack_49(self, timeout):
        """等待 COMMAND_ACK(command=49)"""
        start = time.time()
        while time.time() - start < timeout:
            received, addr = self.gcs.receive()
            if (received is not None
                    and received.msg_id == MSG_ID_COMMAND_ACK
                    and received.fields.get('command') == MSG_ID_EULER_NETWORK
                    and addr and addr[0] == self.drone_ip):
                log_manager.log_and_attach(
                    _format_msg_detail(received), "COMMAND_ACK (command=49)")
                return received
            time.sleep(0.02)
        return None

    # ==================================================================
    # 串口类用例（BLOCKED skip 桩）
    # ==================================================================

    @allure.story("AUTOPILOT-TC-NET-0003")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("NET-0003 串口 WiFi 密码读写（阻塞：缺报文定义）")
    @pytest.mark.skip(reason="串口 WiFi 密码报文 213/214 无 dialect 定义，"
                             "codec 阻塞（NET-0003/0011/0013 共因）")
    def test_net0003_serial_wifi_password(self):
        """串口密码读写（NET-0003，阻塞桩）"""

    @allure.story("AUTOPILOT-TC-NET-0013")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("NET-0013 串口修改 WiFi 密码与重连（阻塞：缺报文定义）")
    @pytest.mark.skip(reason="串口 WiFi 密码报文 213/214 无 dialect 定义，"
                             "codec 阻塞；飞控侧写路径验收已由网络通道用例"
                             "（NET-0001/0006）覆盖")
    def test_net0013_serial_modify_and_reconnect(self):
        """串口修改+重连（NET-0013，阻塞桩）"""
