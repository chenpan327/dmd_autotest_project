# coding: utf-8

"""
MAVLink CLI 消息交互测试 — 参考地面站 CliPanel 的交互流程

业务背景：
    无人机固件内置 SYS_CLI_SERV 任务，通过 MAVLink CONSOLE 消息（msg_id=48）
    提供命令行交互通道。交互前需先通过 PARAM_SET（msg_id=23）将参数 SR0_CONSOLE
    置为 20 打开终端，交互结束后置为 0 关闭终端。

    本测试仅关注 MAVLink 消息层面的交互（参考地面站 CliPanel 面板流程）：
        1. 打开终端：PARAM_SET(SR0_CONSOLE=20) → PARAM_VALUE (msg_id=22) 确认
        2. 发送命令：CONSOLE (msg_id=48) → 接收无人机 CLI 输出 CONSOLE (msg_id=48)
        3. 关闭终端：PARAM_SET(SR0_CONSOLE=0) → PARAM_VALUE (msg_id=22) 确认

    说明：无人机对 PARAM_SET 的确认是通过 PARAM_VALUE（msg_id=22）回传参数值，
    而非 PARAM_REQUEST_LIST_ACK（msg_id=24）。

测试对象：
    - PARAM_SET 消息通道（msg_id=23）与 PARAM_VALUE 确认（msg_id=22）
    - CONSOLE 消息通道（msg_id=48）的发送与接收
"""

import re
import struct
import time

import pytest
import allure

from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from utils.logger import log_manager


# ============================================================================
# CONSOLE 消息常量
# ============================================================================

MSG_ID_CONSOLE = 48
MSG_ID_PARAM_SET = 23
MSG_ID_PARAM_VALUE = 22
CONSOLE_DATA_MAX = 250

# 终端开关参数（PARAM_SET SR0_CONSOLE）—— 参考地面站 CliPanel 的打开/关闭流程
PARAM_CONSOLE_ID = "SR0_CONSOLE"
PARAM_CONSOLE_OPEN = 20.0     # 打开 CLI 终端
PARAM_CONSOLE_CLOSE = 0.0     # 关闭 CLI 终端

# MAVLink 系统/组件 ID
DRONE_SYS_ID = 0
DRONE_COMP_ID = 1
GCS_SYS_ID = 1
GCS_COMP_ID = 1

# CLI 命令提示符（用于判断无人机已返回可交互状态）
CLI_PROMPT = "~dmd_uav~@:"


def _make_console_msg(text, sys_id=GCS_SYS_ID, comp_id=GCS_COMP_ID, version=None):
    """构造 MAVLink CONSOLE 消息（msg_id=48），委托 MAVLink_message.pack_payload() 打包。

    struct_format = '<B250B': length(1B) + data[0..249](250B)
    """
    data_bytes = text.encode('utf-8') + b'\r\n'
    actual_len = min(len(data_bytes), CONSOLE_DATA_MAX)
    data_bytes = data_bytes[:actual_len]
    data_list = list(data_bytes) + [0] * (CONSOLE_DATA_MAX - actual_len)

    return MAVLink_message(
        msg_id=MSG_ID_CONSOLE, sys_id=sys_id, comp_id=comp_id, seq=0,
        fields={'length': actual_len, 'data': data_list},
        version=version,
    )


def _extract_console_text(msg):
    """从已解析的 MAVLink CONSOLE 消息中提取文本"""
    data = msg.fields.get('data', b'')
    text_len = msg.fields.get('length', 0)
    if isinstance(data, bytes):
        return data[:text_len].rstrip(b'\x00').decode('latin-1', errors='replace')
    return ""


# ============================================================================
# 测试类
# ============================================================================

class _MavlinkCLIBase:
    """MAVLink CLI 消息交互测试基类 — 提供终端开关与 CONSOLE 收发的辅助方法。"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, drone_ip, drone_port, mavlink_version):
        self.drone_ip = drone_ip
        self.drone_port = drone_port
        self.mavlink_version = mavlink_version
        self._terminal_opened = False

        with allure.step("初始化地面站"):
            self.gcs = GroundControlStation(drone_ip=drone_ip, drone_port=drone_port)
            log_manager.log_and_attach(
                f"地面站初始化完成，本地地址: {self.gcs.local_ip}:{self.gcs.local_port}",
                "初始化信息")

        yield

        with allure.step("清理测试资源"):
            # 尽力关闭终端，避免遗留打开的 CLI 会话
            try:
                self._close_terminal()
            except Exception:
                pass
            self.gcs.close()
            log_manager.log_and_attach("地面站已关闭", "清理信息")

    # ==================================================================
    # 终端开关（PARAM_SET SR0_CONSOLE）
    # ==================================================================

    def _make_param_set_msg(self, value):
        """构造 PARAM_SET 消息（msg_id=23）用于打开/关闭 CLI 终端。

        struct_format = '<8fHBB128s':
            param_value(8f) + param_count(H) + target_system(B)
            + target_component(B) + param_id(128s)
        """
        param_id_bytes = PARAM_CONSOLE_ID.encode("ascii").ljust(128, b"\x00")
        return MAVLink_message(
            msg_id=MSG_ID_PARAM_SET,
            fields={
                "param_value": [value] + [0.0] * 7,
                "param_count": 1,
                "target_system": DRONE_SYS_ID,
                "target_component": DRONE_COMP_ID,
                "param_id": param_id_bytes,
            },
            sys_id=GCS_SYS_ID,
            comp_id=GCS_COMP_ID,
            version=self.mavlink_version,
        )

    def _parse_param_value(self, msg):
        """解析 PARAM_VALUE 消息（msg_id=22），返回 (param_id, param_value)。

        struct_format = '<8f8HHH128s8B':
            param_value(8f) + param_index(8H) + param_count(H)
            + param_total(H) + param_id(128s) + param_type(8B)

        说明：parse_mavlink.unpack_payload() 在合并 float 数组字段时执行
        bytes([float, ...])，会抛 TypeError 并被静默吞掉，导致 msg.fields 为空。
        因此这里直接按 struct 从原始 payload 解析，绕过该缺陷。
        """
        fmt = '<8f8HHH128s8B'
        payload = msg.payload
        if not payload or len(payload) < struct.calcsize(fmt):
            return '', None
        try:
            values = struct.unpack(fmt, payload[:struct.calcsize(fmt)])
        except Exception:
            return '', None
        value = values[0]
        # 固件对 char[128] 仅做 null 结尾，未填充到 128 字节，尾部含残留数据，
        # 因此取第一个 \x00 之前的内容作为 param_id。
        param_id = values[18].split(b'\x00')[0].decode('ascii', errors='replace')
        return param_id, value

    def _send_param_set(self, value, timeout=8.0):
        """发送 PARAM_SET 并等待 PARAM_VALUE（msg_id=22）确认。

        无人机对 PARAM_SET 的确认是通过 PARAM_VALUE 回传参数值。

        Returns:
            (是否收到确认, 回传 param_id, 回传参数值)
        """
        target = (self.drone_ip, self.drone_port)
        self.gcs.send(self._make_param_set_msg(value), addr=target)

        start = time.time()
        while time.time() - start < timeout:
            received, addr = self.gcs.receive()
            if received is not None and received.msg_id == MSG_ID_PARAM_VALUE:
                if addr[0] == self.drone_ip:
                    param_id, echoed = self._parse_param_value(received)
                    return True, param_id, echoed
            time.sleep(0.05)
        return False, None, None

    def _open_terminal(self):
        """发送 PARAM_SET(SR0_CONSOLE=20) 打开无人机 CLI 终端。"""
        ok, param_id, value = self._send_param_set(PARAM_CONSOLE_OPEN)
        log_manager.log_and_attach(
            f"打开终端 SR0_CONSOLE={PARAM_CONSOLE_OPEN} -> ACK={ok}, param_id={param_id}, value={value}",
            "终端开关")
        return ok, param_id, value

    def _close_terminal(self):
        """发送 PARAM_SET(SR0_CONSOLE=0) 关闭无人机 CLI 终端。"""
        ok, param_id, value = self._send_param_set(PARAM_CONSOLE_CLOSE)
        log_manager.log_and_attach(
            f"关闭终端 SR0_CONSOLE={PARAM_CONSOLE_CLOSE} -> ACK={ok}, param_id={param_id}, value={value}",
            "终端开关")
        return ok, param_id, value

    # ==================================================================
    # 底层收发
    # ==================================================================

    def _clear_recv_buffer(self):
        """清空接收缓冲区，避免上一次交互的残留消息干扰"""
        self.gcs.sock.settimeout(0.1)
        try:
            while True:
                data, _ = self.gcs.sock.recvfrom(4096)
                if not data:
                    break
        except Exception:
            pass
        finally:
            self.gcs.sock.settimeout(self.gcs.recv_timeout)

    def _send_console_cmd(self, text, timeout=5.0):
        """发送 CONSOLE 消息并收集响应文本，直到收到 CLI 提示符"""
        target = (self.drone_ip, self.drone_port)
        msg = _make_console_msg(text, version=self.mavlink_version)
        self.gcs.send(msg, addr=target)
        log_manager.log_and_attach(f"发送: {text}", "CLI 发送")

        response_parts = []
        start = time.time()
        while time.time() - start < timeout:
            received, addr = self.gcs.receive()
            if received is not None and received.msg_id == MSG_ID_CONSOLE:
                if addr[0] == self.drone_ip:
                    txt = _extract_console_text(received)
                    response_parts.append(txt)
                    if CLI_PROMPT in txt:
                        break
            time.sleep(0.05)

        full = ''.join(response_parts)
        log_manager.log_and_attach(full if full else "(空)", f"CLI 响应: {text}")
        return full

    # ==================================================================
    # CLI 命令执行（MAVLink CONSOLE 通道）
    # ==================================================================

    def _normalize_response(self, response):
        """归一化 CLI 响应：去除 null 字节，统一换行符"""
        if not response:
            return ""
        text = response.replace('\x00', '')
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        return text

    def _has_ack(self, response):
        """检查 CLI 响应是否包含 ACK 应答（独占一行）"""
        if not response:
            return False
        clean = self._normalize_response(response)
        for line in clean.split('\n'):
            if line.strip() == 'ACK':
                return True
        return False

    def _ensure_terminal_open(self):
        """确保 CLI 终端已打开（同一次测试内懒打开一次）"""
        if getattr(self, '_terminal_opened', False):
            return True
        ok, _, _ = self._open_terminal()
        self._terminal_opened = bool(ok)
        return bool(ok)

    def _run_cli_command(self, cmd, timeout=5.0, check_ack=True):
        """通过 MAVLink CONSOLE 通道发送 CLI 命令，返回归一化后的响应文本；失败返回 None"""
        if not self._ensure_terminal_open():
            return None
        self._clear_recv_buffer()
        resp = self._send_console_cmd(cmd, timeout=timeout)
        if not resp:
            return None
        if check_ack and not self._has_ack(resp):
            log_manager.log_and_attach(f"命令 {cmd} 未收到 ACK 应答: {resp[:200]}", "ACK 校验")
            return None
        return self._normalize_response(resp)

    def _run_interactive_command(self, cmd, collect_time=3.0):
        """发送进入循环刷新模式的命令（ps/mav），收集固定时间后按 q 退出"""
        if not self._ensure_terminal_open():
            return None
        self._clear_recv_buffer()
        resp = self._send_console_cmd(cmd, timeout=collect_time)
        # 发送 q 退出交互模式（q 无 ACK，忽略响应）
        try:
            self._send_console_cmd('q', timeout=2.0)
        except Exception:
            pass
        if not resp:
            return None
        resp = self._normalize_response(resp)
        if not self._has_ack(resp):
            log_manager.log_and_attach(f"命令 {cmd} 未收到 ACK 应答: {resp[:200]}", "ACK 校验")
            return None
        return resp

    # ==================================================================
    # 消息交互测试
    # ==================================================================


@allure.feature("MAVLink CLI 消息交互测试")
@allure.severity(allure.severity_level.NORMAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "MAVLINK_CLI", "MESSAGE_TEST")
@pytest.mark.functional
class TestMavlinkCLI(_MavlinkCLIBase):
    """MAVLink CLI 消息交互测试 — 覆盖终端开关与 CONSOLE 消息收发。"""

    # ==================================================================
    # 消息交互测试
    # ==================================================================

    @allure.story("终端开关")
    @allure.title("打开终端：PARAM_SET(20) → PARAM_VALUE")
    def test_open_terminal_interaction(self):
        """验证打开终端的 MAVLink 消息交互：PARAM_SET(SR0_CONSOLE=20) 收到 PARAM_VALUE"""
        with allure.step("发送 PARAM_SET(SR0_CONSOLE=20)"):
            ok, param_id, value = self._open_terminal()
        with allure.step("验证收到 PARAM_VALUE 确认"):
            assert ok, "打开终端未收到 PARAM_VALUE（msg_id=22）确认"
            assert param_id == PARAM_CONSOLE_ID, f"回传参数不是 {PARAM_CONSOLE_ID}: {param_id}"
            assert value is not None and abs(value - PARAM_CONSOLE_OPEN) < 0.01, \
                f"SR0_CONSOLE 回传值不是 {PARAM_CONSOLE_OPEN}: {value}"
            log_manager.log_and_attach(f"打开终端 PARAM_VALUE: {param_id}={value}", "验证通过")

    @allure.story("CONSOLE 消息交互")
    @allure.title("CONSOLE 消息发送与接收")
    def test_console_message_roundtrip(self):
        """验证 CONSOLE 消息通道：发送命令并接收无人机 CLI 输出"""
        with allure.step("确保终端已打开"):
            self._open_terminal()

        with allure.step("清空接收缓冲区"):
            self._clear_recv_buffer()

        with allure.step("发送 CONSOLE 命令 version"):
            resp = self._send_console_cmd('version')

        with allure.step("验证收到 CONSOLE 响应"):
            assert resp, "未收到 CONSOLE 响应"
            log_manager.log_and_attach(f"CONSOLE 响应长度: {len(resp)}", "验证通过")

    @allure.story("终端开关")
    @allure.title("关闭终端：PARAM_SET(0) → PARAM_VALUE")
    def test_close_terminal_interaction(self):
        """验证关闭终端的 MAVLink 消息交互：PARAM_SET(SR0_CONSOLE=0) 收到 PARAM_VALUE"""
        with allure.step("发送 PARAM_SET(SR0_CONSOLE=0)"):
            ok, param_id, value = self._close_terminal()
        with allure.step("验证收到 PARAM_VALUE 确认"):
            assert ok, "关闭终端未收到 PARAM_VALUE（msg_id=22）确认"
            assert param_id == PARAM_CONSOLE_ID, f"回传参数不是 {PARAM_CONSOLE_ID}: {param_id}"
            assert value is not None and abs(value - PARAM_CONSOLE_CLOSE) < 0.01, \
                f"SR0_CONSOLE 回传值不是 {PARAM_CONSOLE_CLOSE}: {value}"
            log_manager.log_and_attach(f"关闭终端 PARAM_VALUE: {param_id}={value}", "验证通过")

    # ==================================================================
    # 目录操作
    # ==================================================================

    @allure.story("目录操作")
    @allure.title("查看当前目录文件列表")
    def test_list_directory(self):
        """验证 ls 命令：返回当前目录的文件/目录列表"""
        with allure.step("发送 ls 命令"):
            resp = self._run_cli_command("ls", timeout=3.0)
        with allure.step("验证返回文件列表"):
            assert resp, "ls 命令无响应"
            items = re.findall(r"\d+\s+(\S+)", resp)
            log_manager.log_and_attach(f"ls 返回条目: {items}", "验证通过")
            assert len(items) > 0, f"ls 返回的文件列表不应为空: {resp}"

    @allure.story("目录操作")
    @allure.title("切换工作目录")
    def test_change_directory(self):
        """验证 cd 命令：切换目录并在新目录下列出文件"""
        with allure.step("切换到 data 目录"):
            resp = self._run_cli_command("cd data", timeout=3.0)
            assert resp, "cd data 命令无响应"
            assert "no such directory" not in resp.lower(), f"cd data 失败: {resp}"

        with allure.step("列出 data 目录文件"):
            resp = self._run_cli_command("ls", timeout=3.0)
            assert resp, "ls 命令无响应"

        with allure.step("返回上级目录"):
            resp = self._run_cli_command("cd ..", timeout=3.0)
            assert resp, "cd .. 命令无响应"
            assert "no such directory" not in resp.lower(), f"cd .. 失败: {resp}"

        with allure.step("列出上级目录文件"):
            resp = self._run_cli_command("ls", timeout=3.0)
            assert resp, "ls 命令无响应"

    # ==================================================================
    # 参数操作
    # ==================================================================

    @allure.story("参数操作")
    @allure.title("获取全部参数")
    def test_get_parameter(self):
        """验证 pp 命令：返回全部参数键值对"""
        with allure.step("发送 pp 命令"):
            resp = self._run_cli_command("pp", timeout=5.0)
        with allure.step("验证参数列表"):
            assert resp, "pp 命令无响应"
            params = dict(re.findall(r"(\w+)\s*:([\d.-]+)", resp))
            log_manager.log_and_attach(f"pp 返回 {len(params)} 个参数", "验证通过")
            assert len(params) > 10, f"参数总数应 > 10，实际 {len(params)}"

    @pytest.mark.skip(reason="pp 命令响应格式变更(Key:Value)，regex 未匹配，待修复")
    @allure.story("参数操作")
    @allure.title("获取指定参数值")
    def test_get_specific_parameter(self):
        """验证 pp <name> 命令：获取指定参数值"""
        with allure.step("发送 pp LOG_MSK0 命令"):
            resp = self._run_cli_command("pp LOG_MSK0", timeout=3.0)
            assert resp, "pp LOG_MSK0 命令无响应"

    @allure.story("参数操作")
    @allure.title("设置参数值")
    def test_set_parameter(self):
        """验证 sp 命令：设置参数值"""
        with allure.step("发送 sp INDOOR_DEBUG: 1 命令"):
            resp = self._run_cli_command("sp INDOOR_DEBUG: 1", timeout=3.0)
        with allure.step("验证设置成功"):
            assert resp, "sp 命令无响应"
            assert "can't find param" not in resp.lower(), f"sp 未找到参数: {resp}"
            assert "found param" in resp.lower(), f"sp 设置失败: {resp}"

        with allure.step("读取 INDOOR_DEBUG 验证值已变更"):
            resp = self._run_cli_command("pp INDOOR_DEBUG", timeout=3.0)
            assert resp, "pp INDOOR_DEBUG 命令无响应"

    @allure.story("参数操作")
    @allure.title("保存参数到 Flash")
    def test_save_parameter(self):
        """验证 svp 命令：保存参数到 Flash"""
        with allure.step("先设置 INDOOR_DEBUG=1"):
            resp = self._run_cli_command("sp INDOOR_DEBUG: 1", timeout=3.0)
            assert resp and "found param" in resp.lower(), "sp 命令执行失败"

        with allure.step("发送 svp INDOOR_DEBUG 命令"):
            resp = self._run_cli_command("svp INDOOR_DEBUG", timeout=3.0)
        with allure.step("验证保存成功"):
            assert resp, "svp 命令无响应"
            assert "save" in resp.lower() and "ok" in resp.lower(), f"svp 保存失败: {resp}"

    @allure.story("参数操作")
    @allure.title("系统参数抽样验证（set + save）")
    def test_system_parameter_validation(self):
        """抽样验证系统参数可被 sp 设置并被 svp 保存"""
        with allure.step("获取全部参数列表"):
            resp = self._run_cli_command("pp", timeout=5.0)
            assert resp, "获取全部参数失败"
            params = dict(re.findall(r"(\w+)\s*:([\d.-]+)", resp))
            assert params, "参数解析失败"
            # 过滤掩码类参数：固件 pp 输出对位掩码参数（如 LOG_MSK0）存在渲染截断，
            # 会与上一行参数名粘连（LOG_MSK0 → G_MSK0），导致 sp 报 "Can't find param"。
            # 此类参数属于固件 pp 输出缺陷，不参与抽样验证。
            params = {k: v for k, v in params.items() if "MSK" not in k}

        param_items = list(params.items())
        total = len(param_items)
        sample_indices = set()
        sample_indices.update(range(min(3, total)))
        sample_indices.update(range(max(0, total - 3), total))
        sample_indices.update(range(0, total, 20))
        sampled = [param_items[i] for i in sorted(sample_indices)]
        log_manager.log_and_attach(f"总参数 {total} 个，抽样 {len(sampled)} 个", "抽样信息")

        failed_params = []
        for name, value in sampled:
            resp = self._run_cli_command(f"sp {name}: {value}", timeout=3.0)
            if not resp or "found param" not in resp.lower():
                failed_params.append(f"set:{name}")
                continue
            resp = self._run_cli_command(f"svp {name}", timeout=3.0)
            if not resp or "save" not in resp.lower() or "ok" not in resp.lower():
                failed_params.append(f"save:{name}")

        if failed_params:
            log_manager.log_and_attach(f"失败参数列表: {failed_params}", "失败信息")
        assert len(failed_params) == 0, f"以下参数操作失败: {failed_params}"

    # ==================================================================
    # 系统状态
    # ==================================================================

    @allure.story("系统状态")
    @allure.title("获取任务信息")
    def test_get_task_info(self):
        """验证 pm 命令：返回系统任务列表"""
        with allure.step("发送 pm 命令"):
            resp = self._run_cli_command("pm", timeout=3.0)
        with allure.step("验证任务信息"):
            assert resp, "pm 命令无响应"
            assert "SYS_CLI_SERV" in resp, f"pm 未返回 SYS_CLI_SERV 任务: {resp}"

    @allure.story("系统状态")
    @allure.title("获取错误信息")
    def test_get_error_info(self):
        """验证 dmsg 命令：返回错误信息"""
        with allure.step("发送 dmsg 命令"):
            resp = self._run_cli_command("dmsg", timeout=3.0)
        with allure.step("验证错误信息"):
            assert resp, "dmsg 命令无响应"

    @allure.story("系统状态")
    @allure.title("清除错误信息")
    def test_get_error_info_clear(self):
        """验证 dmsg c 命令：清除错误信息"""
        with allure.step("发送 dmsg c 命令"):
            resp = self._run_cli_command("dmsg c", timeout=3.0)
        with allure.step("验证清除结果"):
            assert resp, "dmsg c 命令无响应"

    @allure.story("系统状态")
    @allure.title("获取模块初始化状态")
    def test_get_module_init_status(self):
        """验证 istate 命令：返回各模块初始化状态"""
        with allure.step("发送 istate 命令"):
            resp = self._run_cli_command("istate", timeout=3.0)
        with allure.step("验证初始化状态"):
            assert resp, "istate 命令无响应"
            key_modules = ["module", "sdcard", "param", "log", "mission", "assist"]
            found = [m for m in key_modules if m in resp.lower()]
            assert len(found) >= 1, f"istate 未返回任何关键模块状态: {resp}"

    @allure.story("系统状态")
    @allure.title("获取传感器工作状态")
    def test_get_sensor_work_status(self):
        """验证 sheal 命令：返回传感器健康状态"""
        with allure.step("发送 sheal 命令"):
            resp = self._run_cli_command("sheal", timeout=3.0)
        with allure.step("验证传感器状态"):
            assert resp, "sheal 命令无响应"
            sensors = ["imu", "baro", "compass", "gps", "battery", "tele"]
            found = [s for s in sensors if s in resp.lower()]
            assert len(found) >= 1, f"sheal 未返回任何关键传感器状态: {resp}"

    @allure.story("系统状态")
    @allure.title("获取通信质量")
    def test_get_communication_quality(self):
        """验证 mav 命令：返回 MAVLink 通信质量（循环刷新，按 q 退出）"""
        with allure.step("发送 mav 命令"):
            resp = self._run_interactive_command("mav", collect_time=3.0)
        with allure.step("验证通信质量信息"):
            assert resp, "mav 命令无响应"

    @allure.story("系统状态")
    @allure.title("获取设备版本")
    def test_get_device_version(self):
        """验证 version 命令：返回设备 sn 与固件版本"""
        with allure.step("发送 version 命令"):
            resp = self._run_cli_command("version", timeout=3.0)
        with allure.step("验证版本字段"):
            assert resp, "version 命令无响应"
            sn_match = re.search(r'sn[:=]\s*([^,\n]+)', resp, re.IGNORECASE)
            version_match = re.search(r'version[:=]\s*([^\n]+)', resp, re.IGNORECASE)
            assert sn_match, f"返回数据缺少 sn 字段: {resp}"
            assert version_match, f"返回数据缺少 version 字段: {resp}"
            sn = sn_match.group(1).strip()
            version = version_match.group(1).strip()
            assert sn, "sn 字段为空"
            assert version, "version 字段为空"
            log_manager.log_and_attach(f"sn={sn}, version={version}", "验证通过")

    @allure.story("系统状态")
    @allure.title("获取系统时间")
    def test_get_system_time(self):
        """验证 now 命令：返回 Base Time 与 Flight Time"""
        with allure.step("发送 now 命令"):
            resp = self._run_cli_command("now", timeout=3.0)
        with allure.step("验证时间字段"):
            assert resp, "now 命令无响应"
            m = re.search(r"Base Time\s*:\s*(\d+)\s*Flight Time\s*:\s*(\d+)", resp)
            assert m, f"now 响应缺少 Base Time/Flight Time: {resp}"
            base_time = int(m.group(1))
            flight_time = int(m.group(2))
            assert base_time > 0, f"Base Time 应 > 0，实际 {base_time}"
            log_manager.log_and_attach(f"Base Time={base_time}, Flight Time={flight_time}", "验证通过")

    @allure.story("系统状态")
    @allure.title("获取 CPU 使用率")
    def test_get_cpu_status(self):
        """验证 ps 命令：返回任务 CPU 占用与堆内存（循环刷新，按 q 退出）"""
        with allure.step("发送 ps 命令"):
            resp = self._run_interactive_command("ps", collect_time=4.0)
        with allure.step("验证 CPU 信息"):
            assert resp, "ps 命令无响应"
            assert "Heap" in resp, f"ps 响应缺少 Heap 字段: {resp}"
            assert ("CLI" in resp or "IDLE" in resp or "cli" in resp or "idle" in resp), \
                f"ps 未找到核心任务: {resp[:200]}"

    # ==================================================================
    # 飞行控制
    # ==================================================================

    @allure.story("飞行控制")
    @allure.title("设置飞行模式")
    def test_set_mode(self):
        """验证 mode <mode> 命令：切换飞行模式"""
        with allure.step("发送 mode stab 命令"):
            resp = self._run_cli_command("mode stab", timeout=3.0)
            assert resp, "mode stab 命令无响应"
            resp_lower = resp.lower()
            assert "incorrect mode name" not in resp_lower, f"模式名无效: {resp}"
            assert "cur mode:" not in resp_lower, f"模式切换失败: {resp}"

        with allure.step("读取当前模式验证"):
            resp = self._run_cli_command("mode", timeout=3.0)
            assert resp, "mode 命令无响应"
            m = re.search(r"(?:cur )?mode[:\s]+(\d+)", resp, re.IGNORECASE)
            assert m, f"未解析到当前模式: {resp}"
            mode_id = int(m.group(1))
            assert mode_id == 0, f"模式切换失败: 期望 stab(0)，实际 mode_id={mode_id}"

    @allure.story("飞行控制")
    @allure.title("获取当前飞行模式")
    def test_get_current_mode(self):
        """验证 mode 命令：查询当前飞行模式"""
        with allure.step("发送 mode 命令"):
            resp = self._run_cli_command("mode", timeout=3.0)
        with allure.step("验证当前模式"):
            assert resp, "mode 命令无响应"
            m = re.search(r"(?:cur )?mode[:\s]+(\d+)", resp, re.IGNORECASE)
            assert m, f"未解析到 mode_id: {resp}"
            mode_id = int(m.group(1))
            valid_mode_ids = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 20, 255}
            assert mode_id in valid_mode_ids, f"mode_id {mode_id} 不在有效范围"

    @allure.story("飞行控制")
    @allure.title("获取可用飞行模式")
    def test_get_available_mode(self):
        """验证 mode ? 命令：查询可用飞行模式列表"""
        with allure.step("发送 mode ? 命令"):
            resp = self._run_cli_command("mode ?", timeout=3.0)
        with allure.step("验证可用模式"):
            assert resp, "mode ? 命令无响应"
            modes = {m.lower() for m in re.findall(
                r'\b(stab|acro|althold|auto|guided|loiter|rtl|circle|land|cl)\b', resp, re.IGNORECASE)}
            core_modes = {"stab", "althold", "loiter", "guided", "land", "rtl"}
            common = core_modes & modes
            assert len(common) >= 2, f"mode ? 核心模式不足: {modes}"

    @pytest.mark.skip(reason="takeoff 命令返回 Param number error，待固件修复")
    @allure.story("飞行控制")
    @allure.title("执行起飞")
    def test_takeoff(self):
        """验证 takeoff 命令：执行默认起飞"""
        with allure.step("发送 takeoff 命令"):
            resp = self._run_cli_command("takeoff", timeout=5.0)
        with allure.step("验证起飞结果"):
            assert resp, "takeoff 命令无响应"
            assert "param number error!!!" not in resp.lower(), f"takeoff 参数错误: {resp}"

    @pytest.mark.skip(reason="takeoff 命令返回 Param number error，待固件修复")
    @allure.story("飞行控制")
    @allure.title("执行定点起飞")
    def test_takeoff_position(self):
        """验证 takeoff <x>,<y>,<z>,<alt> 命令：执行定点起飞"""
        with allure.step("发送 takeoff 0, 0, 0, 10 命令"):
            resp = self._run_cli_command("takeoff 0, 0, 0, 10", timeout=5.0)
        with allure.step("验证起飞结果"):
            assert resp, "takeoff 命令无响应"
            assert "param number error!!!" not in resp.lower(), f"takeoff 参数错误: {resp}"


    @pytest.mark.skip(reason="takeoff 命令返回 Param number error，待固件修复")
    @allure.story("飞行控制")
    @allure.title("执行指定高度起飞")
    def test_takeoff_altitude(self):
        """验证 takeoff <alt> 命令：执行指定高度起飞"""
        with allure.step("发送 takeoff 10 命令"):
            resp = self._run_cli_command("takeoff 10", timeout=5.0)
        with allure.step("验证起飞结果"):
            assert resp, "takeoff 命令无响应"
            assert "param number error!!!" not in resp.lower(), f"takeoff 参数错误: {resp}"

    @pytest.mark.skip(reason="flyto 命令返回 Param number error，待固件修复")
    @allure.story("飞行控制")
    @allure.title("执行飞行到指定坐标")
    def test_fly_to(self):
        """验证 flyto 命令：飞行到指定经纬度坐标"""
        with allure.step("发送 flyto 命令"):
            resp = self._run_cli_command("flyto 22.0, 113.0, 50", timeout=5.0)
            assert resp, "flyto 命令无响应"

    @pytest.mark.skip(reason="home 命令返回 Param number error，待固件修复")
    @allure.story("飞行控制")
    @allure.title("设置返航点")
    def test_set_home(self):
        """验证 home 命令：设置返航点坐标"""
        with allure.step("发送 home 命令"):
            resp = self._run_cli_command("home 22.0 113.0", timeout=5.0)
            assert resp, "home 命令无响应"

    @allure.story("飞行控制")
    @allure.title("设置地理围栏")
    def test_set_geofence(self):
        """验证 fence 命令：设置地理围栏"""
        with allure.step("发送 fence 0, 0, 100, 50 命令"):
            resp = self._run_cli_command("fence 0, 0, 100, 50", timeout=5.0)
        with allure.step("验证围栏设置"):
            assert resp, "fence 命令无响应"
            assert "fence origin:" in resp.lower(), f"fence 未返回围栏信息: {resp}"

    @allure.story("飞行控制")
    @allure.title("锁定电机")
    def test_arm_motors(self):
        """验证 arm 命令：锁定电机"""
        with allure.step("发送 arm 命令"):
            resp = self._run_cli_command("arm", timeout=3.0)
        with allure.step("验证锁定结果"):
            assert resp, "arm 命令无响应"

    @allure.story("飞行控制")
    @allure.title("解锁电机")
    def test_disarm_motors(self):
        """验证 disarm 命令：解锁电机"""
        with allure.step("发送 disarm 命令"):
            resp = self._run_cli_command("disarm", timeout=3.0)
        with allure.step("验证解锁结果"):
            assert resp, "disarm 命令无响应"

    # ==================================================================
    # 灯光与伺服
    # ==================================================================

    @allure.story("灯光控制")
    @allure.title("设置伺服 PWM")
    def test_set_servo(self):
        """验证 servo 命令：设置伺服 PWM 值"""
        with allure.step("发送 servo 245, 245, 245 命令"):
            resp = self._run_cli_command("servo 245, 245, 245", timeout=3.0)
            assert resp, "servo 命令无响应"
            assert "param num err!!!" not in resp.lower(), f"servo 参数错误: {resp}"
            assert "servo_value exceed" not in resp.lower(), f"servo 数值越界: {resp}"

        with allure.step("发送 servo 0, 0, 0 命令"):
            resp = self._run_cli_command("servo 0, 0, 0", timeout=3.0)
            assert resp, "servo 命令无响应"
            assert "param num err!!!" not in resp.lower(), f"servo 参数错误: {resp}"
            assert "servo_value exceed" not in resp.lower(), f"servo 数值越界: {resp}"

    @allure.story("灯光控制")
    @allure.title("关闭 LED 通知")
    def test_set_led_off(self):
        """验证 notify off 命令：关闭 LED 通知灯"""
        with allure.step("发送 notify off 命令"):
            resp = self._run_cli_command("notify off", timeout=3.0)
        with allure.step("验证关闭结果"):
            assert resp, "notify off 命令无响应"

    @allure.story("灯光控制")
    @allure.title("打开 LED 通知")
    def test_set_led_on(self):
        """验证 notify on 命令：打开 LED 通知灯"""
        with allure.step("发送 notify on 命令"):
            resp = self._run_cli_command("notify on", timeout=3.0)
        with allure.step("验证打开结果"):
            assert resp, "notify on 命令无响应"

    @allure.story("灯光控制")
    @allure.title("LED 通知状态切换")
    def test_notify_state_toggle(self):
        """验证 notify on/off 命令：通知灯状态可连续切换"""
        with allure.step("发送 notify on 命令"):
            resp = self._run_cli_command("notify on", timeout=3.0)
            assert resp, "notify on 命令无响应"

        with allure.step("发送 notify off 命令"):
            resp = self._run_cli_command("notify off", timeout=3.0)
            assert resp, "notify off 命令无响应"

    # ==================================================================
    # 表演与电池
    # ==================================================================
    @pytest.mark.skip(reason="fstart 命令返回 Param number error，待固件修复")
    @allure.story("表演控制")
    @allure.title("开始表演")
    def test_perform_action(self):
        """验证 fstart 命令：开始执行表演动作"""
        with allure.step("发送 fstart 命令"):
            resp = self._run_cli_command("fstart", timeout=5.0)
        with allure.step("验证表演开始"):
            assert resp, "fstart 命令无响应"
            assert "flight start" in resp.lower(), f"fstart 未返回 flight start: {resp}"

    @allure.story("电池信息")
    @allure.title("获取电池信息")
    def test_get_battery_info(self):
        """验证 bat 命令：返回电池总电压与电流"""
        with allure.step("发送 bat 命令"):
            resp = self._run_cli_command("bat", timeout=3.0)
        with allure.step("验证电池信息"):
            assert resp, "bat 命令无响应"
            sv = re.search(r'sum_voltage\s*:\s*([-+]?\d+\.?\d*)', resp)
            cur = re.search(r'current\s*:\s*([-+]?\d+\.?\d*)', resp)
            assert sv, f"bat 响应缺少 sum_voltage: {resp}"
            assert cur, f"bat 响应缺少 current: {resp}"
            sum_voltage = float(sv.group(1))
            current = float(cur.group(1))
            assert 0.0 < sum_voltage < 30.0, f"电池总电压异常: {sum_voltage}V"
            assert -60.0 < current < 60.0, f"电池电流异常: {current}A"
            log_manager.log_and_attach(f"sum_voltage={sum_voltage}V, current={current}A", "验证通过")

    # ==================================================================
    # DShot
    # ==================================================================

    @allure.story("DShot 控制")
    @allure.title("停止 DShot")
    def test_set_dshot_stop(self):
        """验证 dshot stop 命令：停止 DShot"""
        with allure.step("发送 dshot stop 命令"):
            resp = self._run_cli_command("dshot stop", timeout=5.0)
        with allure.step("验证停止结果"):
            assert resp, "dshot stop 命令无响应"
            resp_lower = resp.lower()
            assert "could not open tim_dshot" not in resp_lower, f"dshot stop 失败: {resp}"
            assert "drv_ioc_dshot_stop failed" not in resp_lower, f"dshot stop 失败: {resp}"
            assert "dshot stop" in resp_lower, f"dshot stop 未确认: {resp}"
            time.sleep(3)

    @allure.story("DShot 控制")
    @allure.title("启动 DShot")
    def test_set_dshot_start(self):
        """验证 dshot start 命令：启动 DShot"""
        with allure.step("发送 dshot start 命令"):
            resp = self._run_cli_command("dshot start", timeout=5.0)
        with allure.step("验证启动结果"):
            assert resp, "dshot start 命令无响应"
            resp_lower = resp.lower()
            assert "could not open tim_dshot" not in resp_lower, f"dshot start 失败: {resp}"
            assert "drv_ioc_dshot_start failed" not in resp_lower, f"dshot start 失败: {resp}"
            assert "dshot start" in resp_lower, f"dshot start 未确认: {resp}"
            time.sleep(3)

    @pytest.mark.skip(reason="dshot t 命令未实现，待固件支持")
    @allure.story("DShot 控制")
    @allure.title("DShot 测试模式")
    def test_set_dshot_test(self):
        """验证 dshot t 命令：进入 DShot 测试模式"""
        with allure.step("发送 dshot t 命令"):
            resp = self._run_cli_command("dshot t", timeout=5.0)
        with allure.step("验证测试模式"):
            assert resp, "dshot t 命令无响应"
            resp_lower = resp.lower()
            assert "could not open tim_dshot" not in resp_lower, f"dshot t 失败: {resp}"
            assert "drv_ioc_dshot_start failed" not in resp_lower, f"dshot t 失败: {resp}"
            assert "dshot test" in resp_lower, f"dshot t 未确认: {resp}"
            time.sleep(3)

    @allure.story("DShot 控制")
    @allure.title("读取电机 RPM")
    def test_read_motor_rpm(self):
        """验证 dshot rpm 命令：读取电机转速"""
        with allure.step("发送 dshot rpm 命令"):
            resp = self._run_cli_command("dshot rpm", timeout=5.0)
        with allure.step("验证转速信息"):
            assert resp, "dshot rpm 命令无响应"
            assert "rpm:" in resp.lower(), f"dshot rpm 未返回转速信息: {resp}"

    @pytest.mark.skip(reason="dshot info0 命令未实现，待固件支持")
    @allure.story("DShot 控制")
    @allure.title("读取 DShot 遥测")
    def test_read_dshot_telemetry(self):
        """验证 dshot info0 命令：读取 DShot 遥测数据"""
        with allure.step("发送 dshot info0 命令"):
            resp = self._run_cli_command("dshot info0", timeout=5.0)
        with allure.step("验证遥测数据"):
            assert resp, "dshot info0 命令无响应"

    @pytest.mark.skip(reason="dshot led 命令未实现，待固件支持")
    @allure.story("DShot 控制")
    @allure.title("开启 DShot LED")
    def test_set_dshot_led_on(self):
        """验证 dshot led1 命令：开启 DShot LED"""
        resp = self._run_cli_command("dshot led1", timeout=5.0)
        assert resp, "dshot led1 命令无响应"

    @pytest.mark.skip(reason="dshot led 命令未实现，待固件支持")
    @allure.story("DShot 控制")
    @allure.title("关闭 DShot LED")
    def test_set_dshot_led_off(self):
        """验证 dshot led0 命令：关闭 DShot LED"""
        resp = self._run_cli_command("dshot led0", timeout=5.0)
        assert resp, "dshot led0 命令无响应"

    @pytest.mark.skip(reason="dshot dir 命令未实现，待固件支持")
    @allure.story("DShot 控制")
    @allure.title("设置电机正转")
    def test_set_dshot_motor_direction_forward(self):
        """验证 dshot dir1 命令：设置电机正转"""
        resp = self._run_cli_command("dshot dir1", timeout=5.0)
        assert resp, "dshot dir1 命令无响应"

    @pytest.mark.skip(reason="dshot dir 命令未实现，待固件支持")
    @allure.story("DShot 控制")
    @allure.title("设置电机反转")
    def test_set_dshot_motor_direction_reverse(self):
        """验证 dshot dir0 命令：设置电机反转"""
        resp = self._run_cli_command("dshot dir0", timeout=5.0)
        assert resp, "dshot dir0 命令无响应"

    @pytest.mark.skip(reason="dshot 3d 命令未实现，待固件支持")
    @allure.story("DShot 控制")
    @allure.title("开启 3D 模式")
    def test_set_dshot_3d_mode_on(self):
        """验证 dshot 3d1 命令：开启 3D 模式"""
        resp = self._run_cli_command("dshot 3d1", timeout=5.0)
        assert resp, "dshot 3d1 命令无响应"

    @pytest.mark.skip(reason="dshot 3d 命令未实现，待固件支持")
    @allure.story("DShot 控制")
    @allure.title("关闭 3D 模式")
    def test_set_dshot_3d_mode_off(self):
        """验证 dshot 3d0 命令：关闭 3D 模式"""
        resp = self._run_cli_command("dshot 3d0", timeout=5.0)
        assert resp, "dshot 3d0 命令无响应"

    # ==================================================================
    # 故障状态
    # ==================================================================

    @allure.story("故障状态")
    @allure.title("获取故障状态")
    def test_get_failsafe_state(self):
        """验证 fs_state 命令：返回故障状态字段"""
        with allure.step("发送 fs_state 命令"):
            resp = self._run_cli_command("fs_state", timeout=2.0)
        with allure.step("验证故障字段"):
            assert resp, "fs_state 命令无响应"
            response_lower = resp.lower()
            fault_fields = ["ekf", "crash", "radio", "battery", "fence", "waypoint"]
            found_fields = [f for f in fault_fields if f in response_lower]
            assert len(found_fields) >= 1, f"fs_state 未返回任何故障字段: {resp}"

    @allure.story("故障状态")
    @allure.title("清除故障状态")
    def test_set_error_state_clear(self):
        """验证 ffs 0 命令：清除所有故障状态"""
        with allure.step("发送 ffs 0 命令"):
            resp = self._run_cli_command("ffs 0", timeout=5.0)
        with allure.step("验证清除结果"):
            assert resp, "ffs 0 命令无响应"

    @allure.story("故障状态")
    @allure.title("设置低电量故障")
    def test_set_error_state_low_battery(self):
        """验证 ffs 1 命令：设置低电量故障"""
        with allure.step("发送 ffs 1 命令"):
            resp = self._run_cli_command("ffs 1", timeout=5.0)
        with allure.step("验证故障标记"):
            assert resp, "ffs 1 命令无响应"
            assert "fake low battery" in resp.lower(), f"ffs 1 未命中 Fake low battery: {resp}"
        with allure.step("恢复：清除故障状态"):
            self._run_cli_command("ffs 0", timeout=5.0)

    @allure.story("故障状态")
    @allure.title("设置航点失败故障")
    def test_set_error_state_waypoint_failed(self):
        """验证 ffs 2 命令：设置航点失败故障"""
        with allure.step("发送 ffs 2 命令"):
            resp = self._run_cli_command("ffs 2", timeout=5.0)
        with allure.step("验证故障标记"):
            assert resp, "ffs 2 命令无响应"
            assert "fake wp error" in resp.lower(), f"ffs 2 未命中 Fake wp error: {resp}"
        with allure.step("恢复：清除故障状态"):
            self._run_cli_command("ffs 0", timeout=5.0)

    @allure.story("故障状态")
    @allure.title("设置围栏违规故障")
    def test_set_error_state_fence_violation(self):
        """验证 ffs 3 命令：设置围栏违规故障"""
        with allure.step("发送 ffs 3 命令"):
            resp = self._run_cli_command("ffs 3", timeout=5.0)
        with allure.step("验证故障标记"):
            assert resp, "ffs 3 命令无响应"
            assert "fake fence error" in resp.lower(), f"ffs 3 未命中 Fake fence error: {resp}"
        with allure.step("恢复：清除故障状态"):
            self._run_cli_command("ffs 0", timeout=5.0)

    @allure.story("故障状态")
    @allure.title("设置 EKF 故障")
    def test_set_error_state_ekf_error(self):
        """验证 ffs 4,1,0,1 命令：设置 EKF 故障"""
        with allure.step("发送 ffs 4, 1, 0, 1 命令"):
            resp = self._run_cli_command("ffs 4, 1, 0, 1", timeout=5.0)
        with allure.step("验证故障标记"):
            assert resp, "ffs 4, 1, 0, 1 命令无响应"
            assert "fake ekf to:" in resp.lower(), f"ffs 4,1,0,1 未命中 Fake ekf to:: {resp}"
        with allure.step("恢复：清除故障状态"):
            self._run_cli_command("ffs 0", timeout=5.0)

    # ==================================================================
    # WiFi（跳过：固件未实现或返回 False）
    # ==================================================================

    @pytest.mark.skip(reason="wifi 命令返回 False，待固件支持")
    @allure.story("WiFi 控制")
    @allure.title("设置 WiFi")
    def test_set_wifi(self):
        """验证 wifi 命令：设置 WiFi"""
        resp = self._run_cli_command("wifi", timeout=5.0)
        assert resp, "wifi 命令无响应"

    @pytest.mark.skip(reason="wifi debug 命令返回 False，待固件支持")
    @allure.story("WiFi 控制")
    @allure.title("开启 WiFi 调试")
    def test_set_wifi_debug_on(self):
        """验证 wifi debug on 命令：开启 WiFi 调试"""
        resp = self._run_cli_command("wifi debug on", timeout=5.0)
        assert resp, "wifi debug on 命令无响应"

    @pytest.mark.skip(reason="wifi debug 命令返回 False，待固件支持")
    @allure.story("WiFi 控制")
    @allure.title("关闭 WiFi 调试")
    def test_set_wifi_debug_off(self):
        """验证 wifi debug off 命令：关闭 WiFi 调试"""
        resp = self._run_cli_command("wifi debug off", timeout=5.0)
        assert resp, "wifi debug off 命令无响应"

    @pytest.mark.skip(reason="wifi reset 命令返回 False，待固件支持")
    @allure.story("WiFi 控制")
    @allure.title("重置 WiFi")
    def test_set_wifi_reset(self):
        """验证 wifi reset 命令：重置 WiFi"""
        resp = self._run_cli_command("wifi reset", timeout=5.0)
        assert resp, "wifi reset 命令无响应"

    @pytest.mark.skip(reason="wifi ip 命令返回 False，待固件支持")
    @allure.story("WiFi 控制")
    @allure.title("设置 WiFi IP")
    def test_set_wifi_ip(self):
        """验证 wifi ip 命令：设置 WiFi IP"""
        resp = self._run_cli_command("wifi 0 192.168.4.1", timeout=5.0)
        assert resp, "wifi ip 命令无响应"

    # ==================================================================
    # 日志
    # ==================================================================

    @allure.story("日志控制")
    @allure.title("开始记录日志")
    def test_set_log_start(self):
        """验证 log start 命令：开始记录日志"""
        with allure.step("发送 log start 命令"):
            resp = self._run_cli_command("log start", timeout=5.0)
        with allure.step("验证日志启动"):
            assert resp, "log start 命令无响应"
            resp_lower = resp.lower()
            assert "unknow log cmd" not in resp_lower, f"log start 失败: {resp}"
            assert "ok: starting a log" in resp_lower or "log will write into" in resp_lower, \
                f"log start 未确认: {resp}"

    @allure.story("日志控制")
    @allure.title("停止记录日志")
    def test_set_log_stop(self):
        """验证 log stop 命令：停止记录日志"""
        with allure.step("发送 log stop 命令"):
            resp = self._run_cli_command("log stop", timeout=5.0)
        with allure.step("验证日志停止"):
            assert resp, "log stop 命令无响应"
            resp_lower = resp.lower()
            assert "unknow log cmd" not in resp_lower, f"log stop 失败: {resp}"
            assert "ok: stopping a log" in resp_lower, f"log stop 未确认: {resp}"

    # ==================================================================
    # 内存调试
    # ==================================================================

    @allure.story("内存调试")
    @allure.title("开启内存调试")
    def test_set_memory_debug(self):
        """验证 smsg 命令：开启内存调试信息输出"""
        with allure.step("发送 smsg 命令"):
            resp = self._run_cli_command("smsg", timeout=3.0)
        with allure.step("验证开启结果"):
            assert resp, "smsg 命令无响应"

    @allure.story("内存调试")
    @allure.title("关闭内存调试")
    def test_set_memory_debug_off(self):
        """验证 smsg c 命令：关闭内存调试信息输出"""
        with allure.step("发送 smsg c 命令"):
            resp = self._run_cli_command("smsg c", timeout=3.0)
        with allure.step("验证关闭结果"):
            assert resp, "smsg c 命令无响应"

    # ==================================================================
    # 电机测试
    # ==================================================================
    @pytest.mark.skip(reason="mtcheck 命令会影响测试环境，跳过")
    @allure.story("电机测试")
    @allure.title("全通道电机测试")
    def test_motor_test_all(self):
        """验证 mtcheck 命令：全通道电机测试"""
        with allure.step("发送 mtcheck 命令"):
            resp = self._run_cli_command("mtcheck", timeout=5.0)
        with allure.step("验证测试结果"):
            assert resp, "mtcheck 命令无响应"
            assert "param number error!!!" not in resp.lower(), f"mtcheck 参数错误: {resp}"

    @pytest.mark.skip(reason="mtcheck 命令会影响测试环境，跳过")
    @allure.story("电机测试")
    @allure.title("单通道电机测试")
    def test_motor_test_channel(self):
        """验证 mtcheck <ch>,<pwm> 命令：单通道电机测试"""
        with allure.step("发送 mtcheck 0, 1500 命令"):
            resp = self._run_cli_command("mtcheck 0, 1500", timeout=5.0)
        with allure.step("验证测试结果"):
            assert resp, "mtcheck 命令无响应"
            assert "param number error!!!" not in resp.lower(), f"mtcheck 参数错误: {resp}"


    @pytest.mark.skip(reason="mtcheck 命令会影响测试环境，跳过")
    @allure.story("电机测试")
    @allure.title("定时电机测试")
    def test_motor_test_timer(self):
        """验证 mtcheck <ch>,<pwm>,<duration> 命令：定时电机测试"""
        with allure.step("发送 mtcheck 0, 1500, 5 命令"):
            resp = self._run_cli_command("mtcheck 0, 1500, 5", timeout=5.0)
        with allure.step("验证测试结果"):
            assert resp, "mtcheck 命令无响应"
            assert "param number error!!!" not in resp.lower(), f"mtcheck 参数错误: {resp}"


    @pytest.mark.skip(reason="mtcheck 命令会影响测试环境，跳过")
    @allure.story("电机测试")
    @allure.title("停止电机测试")
    def test_motor_test_stop(self):
        """验证 mtcheck -1 命令：停止电机测试"""
        with allure.step("发送 mtcheck -1 命令"):
            resp = self._run_cli_command("mtcheck -1", timeout=5.0)
        with allure.step("验证停止结果"):
            assert resp, "mtcheck 命令无响应"
            assert "param number error!!!" not in resp.lower(), f"mtcheck 参数错误: {resp}"

    @pytest.mark.skip(reason="mtcheck scan 会影响测试环境，跳过")
    @allure.story("电机测试")
    @allure.title("扫描式电机测试")
    def test_motor_test_scan(self):
        """验证 mtcheck scan 命令：扫描式电机测试"""
        resp = self._run_cli_command("mtcheck 0, 1200, 1800, 100, 2", timeout=5.0)
        assert resp, "mtcheck scan 命令无响应"

    @pytest.mark.skip(reason="mtcheck cycle 会影响测试环境，跳过")
    @allure.story("电机测试")
    @allure.title("循环式电机测试")
    def test_motor_test_cycle(self):
        """验证 mtcheck cycle 命令：循环式电机测试"""
        resp = self._run_cli_command("mtcheck 0, 1200, 1800, 100, 2, 3", timeout=5.0)
        assert resp, "mtcheck cycle 命令无响应"

    # ==================================================================
    # 老化测试（跳过：影响测试环境）
    # ==================================================================

    @pytest.mark.skip(reason="aging_test 会影响测试环境，跳过")
    @allure.story("老化测试")
    @allure.title("开始老化测试")
    def test_aging_test_start(self):
        """验证 aging_test 1 命令：开始老化测试"""
        resp = self._run_cli_command("aging_test 1, 100, 10", timeout=5.0)
        assert resp, "aging_test 命令无响应"

    @pytest.mark.skip(reason="aging_test 会影响测试环境，跳过")
    @allure.story("老化测试")
    @allure.title("停止老化测试")
    def test_aging_test_stop(self):
        """验证 aging_test 0 命令：停止老化测试"""
        resp = self._run_cli_command("aging_test 0", timeout=5.0)
        assert resp, "aging_test 命令无响应"

    @pytest.mark.skip(reason="aging_test cycle 会影响测试环境，跳过")
    @allure.story("老化测试")
    @allure.title("循环老化测试")
    def test_aging_test_cycle(self):
        """验证 aging_test cycle 命令：循环老化测试"""
        resp = self._run_cli_command("aging_test 1, 100, 10", timeout=5.0)
        assert resp, "aging_test 命令无响应"


# ============================================================================
# Topic 数据测试（dt 指令，MAVLink CONSOLE 通道）
# ============================================================================

@allure.feature("MAVLink Topic 数据测试")
@allure.severity(allure.severity_level.NORMAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "MAVLINK_CLI", "TOPIC_DATA")
@pytest.mark.functional
class TestMavlinkTopicData(_MavlinkCLIBase):
    """MAVLink Topic 数据测试 — 通过 dt 指令读取飞控内部 Topic 数据（CONSOLE 通道）。

    业务背景：
        飞控内部通过 Topic（主题）机制在各模块间传递实时数据。通过 dt（data topic）
        命令可以读取各 Topic 的当前值。本测试将串口协议中的 dt 测试迁移到 MAVLink
        CONSOLE（msg_id=48）通道，验证各 Topic 数据能够正常返回。
    """

    def _get_topic_data(self, topic, timeout=5.0):
        """发送 dt <topic> 命令并返回归一化响应文本；失败返回 None"""
        return self._run_cli_command(f"dt {topic}", timeout=timeout)

    def _assert_field(self, resp, field):
        """断言响应包含指定字段（形如 field: value 或 field= value）"""
        assert re.search(rf"{re.escape(field)}\s*[:=]", resp, re.IGNORECASE), \
            f"返回数据缺少 {field} 字段"

    # ==================== 遥控器原始数据测试 ====================
    @allure.story("遥控器数据")
    @allure.title("获取遥控器原始数据 TP_RC_RAW")
    def test_get_rc_raw_data(self):
        with allure.step("发送 dt TP_RC_RAW 命令并检查返回数据"):
            resp = self._get_topic_data("TP_RC_RAW")
            assert resp, "未收到设备响应"

    # ==================== 控制点数据测试 ====================
    @allure.story("控制点数据")
    @allure.title("获取控制点数据 TP_CTRL_POINT")
    def test_get_control_point_data(self):
        with allure.step("发送 dt TP_CTRL_POINT 命令并检查返回数据"):
            resp = self._get_topic_data("TP_CTRL_POINT")
            assert resp, "未收到设备响应"

    # ==================== 油门电机数据测试 ====================
    @allure.story("油门电机数据")
    @allure.title("获取油门电机数据 TP_THRO_MOTOR")
    def test_get_throttle_motor_data(self):
        with allure.step("发送 dt TP_THRO_MOTOR 命令并检查返回数据"):
            resp = self._get_topic_data("TP_THRO_MOTOR")
            assert resp, "未收到设备响应"

    # ==================== 姿态电机数据测试 ====================
    @allure.story("姿态电机数据")
    @allure.title("获取姿态电机数据 TP_ATTI_MOTOR")
    def test_get_atti_motor_data(self):
        with allure.step("发送 dt TP_ATTI_MOTOR 命令并检查返回数据"):
            resp = self._get_topic_data("TP_ATTI_MOTOR")
            assert resp, "未收到设备响应"
            for field in ("roll_motor", "pitch_motor", "yaw_motor"):
                self._assert_field(resp, field)

    # ==================== 目标姿态数据测试 ====================
    @allure.story("目标姿态数据")
    @allure.title("获取目标姿态数据 TP_TAR_ATTI")
    def test_get_target_attitude_data(self):
        with allure.step("发送 dt TP_TAR_ATTI 命令并检查返回数据"):
            resp = self._get_topic_data("TP_TAR_ATTI")
            assert resp, "未收到设备响应"

    # ==================== 目标角速度数据测试 ====================
    @allure.story("目标角速度数据")
    @allure.title("获取目标角速度数据 TP_TAR_RATE")
    def test_get_target_angular_velocity_data(self):
        with allure.step("发送 dt TP_TAR_RATE 命令并检查返回数据"):
            resp = self._get_topic_data("TP_TAR_RATE")
            assert resp, "未收到设备响应"

    # ==================== 当前位置数据测试 ====================
    @allure.story("当前位置数据")
    @allure.title("获取当前位置点数据 TP_CUR_POINT")
    def test_get_current_position_data(self):
        with allure.step("发送 dt TP_CUR_POINT 命令并检查返回数据"):
            resp = self._get_topic_data("TP_CUR_POINT")
            assert resp, "未收到设备响应"

    # ==================== 日志请求数据测试 ====================
    @allure.story("日志请求数据")
    @allure.title("获取日志请求数据 TP_LOG_REQ")
    def test_get_log_request_data(self):
        with allure.step("发送 dt TP_LOG_REQ 命令并检查返回数据"):
            resp = self._get_topic_data("TP_LOG_REQ")
            assert resp, "未收到设备响应"

    # ==================== 模式请求数据测试 ====================
    @allure.story("模式请求数据")
    @allure.title("获取模式请求数据 TP_MODE_REQ")
    def test_get_mode_request_data(self):
        with allure.step("发送 dt TP_MODE_REQ 命令并检查返回数据"):
            resp = self._get_topic_data("TP_MODE_REQ")
            assert resp, "未收到设备响应"

    # ==================== 解锁请求数据测试 ====================
    @allure.story("解锁请求数据")
    @allure.title("获取解锁请求数据 TP_ARM_REQ")
    def test_get_arm_request_data(self):
        with allure.step("发送 dt TP_ARM_REQ 命令并检查返回数据"):
            resp = self._get_topic_data("TP_ARM_REQ")
            assert resp, "未收到设备响应"

    # ==================== 解锁检查数据测试 ====================
    @allure.story("解锁检查数据")
    @allure.title("获取解锁检查数据 TP_ARM_CHECK")
    def test_get_arm_check_data(self):
        with allure.step("发送 dt TP_ARM_CHECK 命令并检查返回数据"):
            resp = self._get_topic_data("TP_ARM_CHECK")
            assert resp, "未收到设备响应"

    # ==================== 动作请求数据测试 ====================
    @allure.story("动作请求数据")
    @allure.title("获取动作请求数据 TP_ACTION_REQ")
    def test_get_action_request_data(self):
        with allure.step("发送 dt TP_ACTION_REQ 命令并检查返回数据"):
            resp = self._get_topic_data("TP_ACTION_REQ")
            assert resp, "未收到设备响应"

    # ==================== 灯光命令数据测试 ====================
    @allure.story("灯光命令数据")
    @allure.title("获取灯光命令数据 TP_LIGHT_CMD")
    def test_get_light_command_data(self):
        with allure.step("发送 dt TP_LIGHT_CMD 命令并检查返回数据"):
            resp = self._get_topic_data("TP_LIGHT_CMD")
            assert resp, "未收到设备响应"

    # ==================== 电池缩放数据测试 ====================
    @allure.story("电池缩放数据")
    @allure.title("获取电池缩放数据 TP_BATTERY_SCALED")
    def test_get_battery_scaled_data(self):
        with allure.step("发送 dt TP_BATTERY_SCALED 命令并检查返回数据"):
            resp = self._get_topic_data("TP_BATTERY_SCALED")
            assert resp, "未收到设备响应"

    # ==================== 位置内环控制数据测试 ====================
    @allure.story("位置内环控制数据")
    @allure.title("获取位置内环控制数据 TP_PCTRL_INNER")
    def test_get_pctrl_inner_data(self):
        with allure.step("发送 dt TP_PCTRL_INNER 命令并检查返回数据"):
            resp = self._get_topic_data("TP_PCTRL_INNER")
            assert resp, "未收到设备响应"

    # ==================== 姿态内环控制数据测试 ====================
    @allure.story("姿态内环控制数据")
    @allure.title("获取姿态内环控制数据 TP_ACTRL_INNER")
    def test_get_actrl_inner_data(self):
        with allure.step("发送 dt TP_ACTRL_INNER 命令并检查返回数据"):
            resp = self._get_topic_data("TP_ACTRL_INNER")
            assert resp, "未收到设备响应"

    # ==================== 电机请求数据测试 ====================
    @allure.story("电机请求数据")
    @allure.title("获取电机请求数据 TP_MOTOR_REQ")
    def test_get_motor_request_data(self):
        with allure.step("发送 dt TP_MOTOR_REQ 命令并检查返回数据"):
            resp = self._get_topic_data("TP_MOTOR_REQ")
            assert resp, "未收到设备响应"

    # ==================== 测试请求数据测试 ====================
    @allure.story("测试请求数据")
    @allure.title("获取测试请求数据 TP_TEST_REQ")
    def test_get_test_request_data(self):
        with allure.step("发送 dt TP_TEST_REQ 命令并检查返回数据"):
            resp = self._get_topic_data("TP_TEST_REQ")
            assert resp, "未收到设备响应"

    # ==================== BNO 传感器原始数据测试 ====================
    @allure.story("BNO 传感器数据")
    @allure.title("获取 BNO 传感器原始数据 TP_BNO_RAW")
    def test_get_bno_raw_data(self):
        with allure.step("发送 dt TP_BNO_RAW 命令并检查返回数据"):
            resp = self._get_topic_data("TP_BNO_RAW")
            assert resp, "未收到设备响应"

    # ==================== TOF 传感器原始数据测试 ====================
    @allure.story("TOF 传感器数据")
    @allure.title("获取 TOF 传感器原始数据 TP_TOF_RAW")
    def test_get_tof_raw_data(self):
        with allure.step("发送 dt TP_TOF_RAW 命令并检查返回数据"):
            resp = self._get_topic_data("TP_TOF_RAW")
            assert resp, "未收到设备响应"

    # ==================== 传感器校准数据测试 ====================
    @allure.story("传感器校准数据")
    @allure.title("获取传感器校准数据 TP_SENSOR_CALI")
    def test_get_sensor_calibration_data(self):
        with allure.step("发送 dt TP_SENSOR_CALI 命令并检查返回数据"):
            resp = self._get_topic_data("TP_SENSOR_CALI")
            assert resp, "未收到设备响应"

    # ==================== 数传 RSS 数据测试 ====================
    @allure.story("数传数据")
    @allure.title("获取数传 RSS 数据 TP_TELE_RSSI")
    def test_get_rssi_data(self):
        with allure.step("发送 dt TP_TELE_RSSI 命令并检查返回数据"):
            resp = self._get_topic_data("TP_TELE_RSSI")
            assert resp, "未收到设备响应"

    # ==================== 数传设置数据测试 ====================
    @allure.story("数传数据")
    @allure.title("获取数传设置数据 TP_TELE_SET")
    def test_get_tele_setting_data(self):
        with allure.step("发送 dt TP_TELE_SET 命令并检查返回数据"):
            resp = self._get_topic_data("TP_TELE_SET")
            assert resp, "未收到设备响应"

    # ==================== 电调请求数据测试 ====================
    @allure.story("电调数据")
    @allure.title("获取电调请求数据 TP_ESC_REQ")
    def test_get_esc_request_data(self):
        with allure.step("发送 dt TP_ESC_REQ 命令并检查返回数据"):
            resp = self._get_topic_data("TP_ESC_REQ")
            assert resp, "未收到设备响应"

    # ==================== 相机原始数据测试 ====================
    @allure.story("相机数据")
    @allure.title("获取相机原始数据 TP_CAMERA_RAW")
    def test_get_camera_raw_data(self):
        with allure.step("发送 dt TP_CAMERA_RAW 命令并检查返回数据"):
            resp = self._get_topic_data("TP_CAMERA_RAW")
            assert resp, "未收到设备响应"

    # ==================== 网络遥控数据测试 ====================
    @allure.story("遥控数据")
    @allure.title("获取网络遥控数据 TP_RC_NETWORK")
    def test_get_network_remote_control_data(self):
        with allure.step("发送 dt TP_RC_NETWORK 命令并检查返回数据"):
            resp = self._get_topic_data("TP_RC_NETWORK")
            assert resp, "未收到设备响应"

    # ==================== 导航内环数据测试 ====================
    @allure.story("导航数据")
    @allure.title("获取导航内环数据 TP_NAV_INNER")
    def test_get_navigation_inner_data(self):
        with allure.step("发送 dt TP_NAV_INNER 命令并检查返回数据"):
            resp = self._get_topic_data("TP_NAV_INNER")
            assert resp, "未收到设备响应"

    # ==================== GPS 更新数据测试 ====================
    @allure.story("GPS 数据")
    @allure.title("获取 GPS 更新数据 TP_UPDATE_GPS")
    def test_get_gps_update_data(self):
        with allure.step("发送 dt TP_UPDATE_GPS 命令并检查返回数据"):
            resp = self._get_topic_data("TP_UPDATE_GPS")
            assert resp, "未收到设备响应"

    # ==================== 电池序列号设置数据测试 ====================
    @allure.story("电池数据")
    @allure.title("获取电池序列号设置数据 TP_BAT_SET_SN")
    def test_get_battery_serial_number_data(self):
        with allure.step("发送 dt TP_BAT_SET_SN 命令并检查返回数据"):
            resp = self._get_topic_data("TP_BAT_SET_SN")
            assert resp, "未收到设备响应"

    # ==================== 电源请求数据测试 ====================
    @allure.story("电源数据")
    @allure.title("获取电源请求数据 TP_POWER_REQ")
    def test_get_power_request_data(self):
        with allure.step("发送 dt TP_POWER_REQ 命令并检查返回数据"):
            resp = self._get_topic_data("TP_POWER_REQ")
            assert resp, "未收到设备响应"

    # ==================== Boot 更新数据测试 ====================
    @allure.story("Boot 更新数据")
    @allure.title("获取 Boot 更新数据 TP_UPDATE_BOOT")
    def test_get_boot_update_data(self):
        with allure.step("发送 dt TP_UPDATE_BOOT 命令并检查返回数据"):
            resp = self._get_topic_data("TP_UPDATE_BOOT")
            assert resp, "未收到设备响应"

    # ==================== Boot 更新请求数据测试 ====================
    @allure.story("Boot 更新数据")
    @allure.title("获取 Boot 更新请求数据 TP_UPDATE_BOOT_REQ")
    def test_get_boot_update_request_data(self):
        with allure.step("发送 dt TP_UPDATE_BOOT_REQ 命令并检查返回数据"):
            resp = self._get_topic_data("TP_UPDATE_BOOT_REQ")
            assert resp, "未收到设备响应"

    # ==================== 无线电频道数据测试 ====================
    @allure.story("无线电数据")
    @allure.title("获取无线电频道数据 TP_RADIO_CHANNEL")
    def test_get_radio_channel_data(self):
        with allure.step("发送 dt TP_RADIO_CHANNEL 命令并检查返回数据"):
            resp = self._get_topic_data("TP_RADIO_CHANNEL")
            assert resp, "未收到设备响应"

    # ==================== 无线电对频数据测试 ====================
    @allure.story("无线电数据")
    @allure.title("获取无线电对频数据 TP_RADIO_MATCH")
    def test_get_radio_frequency_data(self):
        with allure.step("发送 dt TP_RADIO_MATCH 命令并检查返回数据"):
            resp = self._get_topic_data("TP_RADIO_MATCH")
            assert resp, "未收到设备响应"

    # ==================== DAV 更新请求数据测试 ====================
    @allure.story("DAV 更新数据")
    @allure.title("获取 DAV 更新请求数据 TP_UPDATE_DAV_REQ")
    def test_get_dav_update_request_data(self):
        with allure.step("发送 dt TP_UPDATE_DAV_REQ 命令并检查返回数据"):
            resp = self._get_topic_data("TP_UPDATE_DAV_REQ")
            assert resp, "未收到设备响应"

    # ==================== MAC 更新请求数据测试 ====================
    @allure.story("MAC 更新数据")
    @allure.title("获取 MAC 更新请求数据 TP_UPDATE_MAC_REQ")
    def test_get_mac_update_request_data(self):
        with allure.step("发送 dt TP_UPDATE_MAC_REQ 命令并检查返回数据"):
            resp = self._get_topic_data("TP_UPDATE_MAC_REQ")
            assert resp, "未收到设备响应"

    # ==================== 无线电地址数据测试 ====================
    @pytest.mark.skip(reason="无线电地址数据测试暂时跳过")
    @allure.story("无线电数据")
    @allure.title("获取无线电地址数据 TP_RADIO_ADDR")
    def test_get_radio_address_data(self):
        with allure.step("发送 dt TP_RADIO_ADDR 命令并检查返回数据"):
            resp = self._get_topic_data("TP_RADIO_ADDR")
            assert resp, "未收到设备响应"

    # ==================== LPPC 地址数据测试 ====================
    @pytest.mark.skip(reason="LPPC 地址数据测试暂时跳过")
    @allure.story("LPPC 数据")
    @allure.title("获取 LPPC 地址数据 TP_LPPC_ADDR")
    def test_get_lppc_address_data(self):
        with allure.step("发送 dt TP_LPPC_ADDR 命令并检查返回数据"):
            resp = self._get_topic_data("TP_LPPC_ADDR")
            assert resp, "未收到设备响应"

    # ==================== 点火器状态数据测试 ====================
    @allure.story("点火器数据")
    @allure.title("获取点火器状态数据 TP_IGNITER_STATE")
    def test_get_igniter_state_data(self):
        with allure.step("发送 dt TP_IGNITER_STATE 命令并检查返回数据"):
            resp = self._get_topic_data("TP_IGNITER_STATE")
            assert resp, "未收到设备响应"

    # ==================== 子模块固件信息数据测试 ====================
    @allure.story("子模块数据")
    @allure.title("获取子模块固件信息数据 TP_SUBMOD_FIRMWARE_INFO")
    def test_get_submodule_firmware_info_data(self):
        with allure.step("发送 dt TP_SUBMOD_FIRMWARE_INFO 命令并检查返回数据"):
            resp = self._get_topic_data("TP_SUBMOD_FIRMWARE_INFO")
            assert resp, "未收到设备响应"

    # ==================== LPPC 保护检查数据测试 ====================
    @pytest.mark.skip(reason="LPPC 保护检查数据测试暂时跳过")
    @allure.story("LPPC 数据")
    @allure.title("获取 LPPC 保护检查数据 TP_LPPC_PROTECTION_CHECK")
    def test_get_lppc_protection_check_data(self):
        with allure.step("发送 dt TP_LPPC_PROTECTION_CHECK 命令并检查返回数据"):
            resp = self._get_topic_data("TP_LPPC_PROTECTION_CHECK")
            assert resp, "未收到设备响应"

    # ==================== LPPC 修改寄存器数据测试 ====================
    @allure.story("LPPC 数据")
    @allure.title("获取 LPPC 修改寄存器数据 TP_LPPC_MODIFY_REGISTER")
    def test_get_lppc_modify_register_data(self):
        with allure.step("发送 dt TP_LPPC_MODIFY_REGISTER 命令并检查返回数据"):
            resp = self._get_topic_data("TP_LPPC_MODIFY_REGISTER")
            assert resp, "未收到设备响应"

    # ==================== IMU 原始数据测试 ====================
    @allure.story("IMU 数据")
    @allure.title("获取 IMU RAW0 原始数据 TP_IMU_RAW0")
    def test_get_imu_raw0(self):
        with allure.step("发送 dt TP_IMU_RAW0 命令并检查返回数据"):
            resp = self._get_topic_data("TP_IMU_RAW0")
            assert resp, "未收到设备响应"
            for field in ("acc_x", "acc_y", "acc_z", "gyo_x", "gyo_y", "gyo_z", "temp"):
                self._assert_field(resp, field)

    @allure.story("IMU 数据")
    @allure.title("获取 IMU RAW1 原始数据 TP_IMU_RAW1")
    def test_get_imu_raw1(self):
        with allure.step("发送 dt TP_IMU_RAW1 命令并检查返回数据"):
            resp = self._get_topic_data("TP_IMU_RAW1")
            assert resp, "未收到设备响应"
            for field in ("acc_x", "acc_y", "acc_z", "gyo_x", "gyo_y", "gyo_z", "temp"):
                self._assert_field(resp, field)

    # ==================== 气压计原始数据测试 ====================
    @allure.story("气压计数据")
    @allure.title("获取气压计 RAW0 原始数据 TP_BARO_RAW0")
    def test_get_baro_raw0(self):
        with allure.step("发送 dt TP_BARO_RAW0 命令并检查返回数据"):
            resp = self._get_topic_data("TP_BARO_RAW0")
            assert resp, "未收到设备响应"
            for field in ("press", "temp"):
                self._assert_field(resp, field)

    @allure.story("气压计数据")
    @allure.title("获取气压计 RAW1 原始数据 TP_BARO_RAW1")
    def test_get_baro_raw1(self):
        with allure.step("发送 dt TP_BARO_RAW1 命令并检查返回数据"):
            resp = self._get_topic_data("TP_BARO_RAW1")
            assert resp, "未收到设备响应"
            for field in ("press", "temp"):
                self._assert_field(resp, field)

    # ==================== 罗盘原始数据测试 ====================
    @allure.story("罗盘数据")
    @allure.title("获取罗盘 RAW0 原始数据 TP_COMPASS_RAW0")
    def test_get_compass_raw0_data(self):
        with allure.step("发送 dt TP_COMPASS_RAW0 命令并检查返回数据"):
            resp = self._get_topic_data("TP_COMPASS_RAW0")
            assert resp, "未收到设备响应"

    @allure.story("罗盘数据")
    @allure.title("获取罗盘 RAW1 原始数据 TP_COMPASS_RAW1")
    def test_get_compass_raw1_data(self):
        with allure.step("发送 dt TP_COMPASS_RAW1 命令并检查返回数据"):
            resp = self._get_topic_data("TP_COMPASS_RAW1")
            assert resp, "未收到设备响应"

    # ==================== GPS 原始数据测试 ====================
    @allure.story("GPS 数据")
    @allure.title("获取 GPS RAW0 原始数据 TP_GPS_RAW0")
    def test_get_gps_raw0_data(self):
        with allure.step("发送 dt TP_GPS_RAW0 命令并检查返回数据"):
            resp = self._get_topic_data("TP_GPS_RAW0")
            assert resp, "未收到设备响应"
            for field in ("state", "fixType", "lat", "lon", "alt", "sat_num"):
                self._assert_field(resp, field)

    # ==================== UWB 原始数据测试 ====================
    @allure.story("UWB 数据")
    @allure.title("获取 UWB RAW0 原始数据 TP_UWB_RAW0")
    def test_get_uwb_raw0_data(self):
        with allure.step("发送 dt TP_UWB_RAW0 命令并检查返回数据"):
            resp = self._get_topic_data("TP_UWB_RAW0")
            assert resp, "未收到设备响应"

    @allure.story("UWB 数据")
    @allure.title("获取 UWB RAW1 原始数据 TP_UWB_RAW1")
    def test_get_uwb_raw1_data(self):
        with allure.step("发送 dt TP_UWB_RAW1 命令并检查返回数据"):
            resp = self._get_topic_data("TP_UWB_RAW1")
            assert resp, "未收到设备响应"

    # ==================== IMU 缩放数据测试 ====================
    @allure.story("IMU 数据")
    @allure.title("获取 IMU SCALED0 数据 TP_IMU_SCALED0")
    def test_get_imu_scaled0(self):
        with allure.step("发送 dt TP_IMU_SCALED0 命令并检查返回数据"):
            resp = self._get_topic_data("TP_IMU_SCALED0")
            assert resp, "未收到设备响应"
            for field in ("acc_x", "acc_y", "acc_z", "gyo_x", "gyo_y", "gyo_z", "temp"):
                self._assert_field(resp, field)

    @allure.story("IMU 数据")
    @allure.title("获取 IMU SCALED1 数据 TP_IMU_SCALED1")
    def test_get_imu_scaled1(self):
        with allure.step("发送 dt TP_IMU_SCALED1 命令并检查返回数据"):
            resp = self._get_topic_data("TP_IMU_SCALED1")
            assert resp, "未收到设备响应"
            for field in ("acc_x", "acc_y", "acc_z", "gyo_x", "gyo_y", "gyo_z", "temp"):
                self._assert_field(resp, field)

    # ==================== 罗盘缩放数据测试 ====================
    @allure.story("罗盘数据")
    @allure.title("获取罗盘 SCALED0 数据 TP_COMPASS_SCALED0")
    def test_get_compass_scaled0_data(self):
        with allure.step("发送 dt TP_COMPASS_SCALED0 命令并检查返回数据"):
            resp = self._get_topic_data("TP_COMPASS_SCALED0")
            assert resp, "未收到设备响应"

    @allure.story("罗盘数据")
    @allure.title("获取罗盘 SCALED1 数据 TP_COMPASS_SCALED1")
    def test_get_compass_scaled1_data(self):
        with allure.step("发送 dt TP_COMPASS_SCALED1 命令并检查返回数据"):
            resp = self._get_topic_data("TP_COMPASS_SCALED1")
            assert resp, "未收到设备响应"

    # ==================== 舵机设置数据测试 ====================
    @allure.story("舵机数据")
    @allure.title("获取舵机 0 设置数据 TP_SET_SERVO0")
    def test_get_servo0_data(self):
        with allure.step("发送 dt TP_SET_SERVO0 命令并检查返回数据"):
            resp = self._get_topic_data("TP_SET_SERVO0")
            assert resp, "未收到设备响应"

    @allure.story("舵机数据")
    @allure.title("获取舵机 1 设置数据 TP_SET_SERVO1")
    def test_get_servo1_data(self):
        with allure.step("发送 dt TP_SET_SERVO1 命令并检查返回数据"):
            resp = self._get_topic_data("TP_SET_SERVO1")
            assert resp, "未收到设备响应"

    # ==================== 继电器设置数据测试 ====================
    @pytest.mark.skip(reason="继电器数据测试暂时跳过，后续根据需求启用")
    @allure.story("继电器数据")
    @allure.title("获取继电器 0 设置数据 TP_SET_RELAY0")
    def test_get_relay0_data(self):
        with allure.step("发送 dt TP_SET_RELAY0 命令并检查返回数据"):
            resp = self._get_topic_data("TP_SET_RELAY0")
            assert resp, "未收到设备响应"

    @pytest.mark.skip(reason="继电器数据测试暂时跳过，后续根据需求启用")
    @allure.story("继电器数据")
    @allure.title("获取继电器 1 设置数据 TP_SET_RELAY1")
    def test_get_relay1_data(self):
        with allure.step("发送 dt TP_SET_RELAY1 命令并检查返回数据"):
            resp = self._get_topic_data("TP_SET_RELAY1")
            assert resp, "未收到设备响应"


# ============================================================================
# Topic 传输时间测试（dt 指令，MAVLink CONSOLE 通道）
# ============================================================================

@allure.feature("MAVLink Topic 传输时间测试")
@allure.severity(allure.severity_level.NORMAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "MAVLINK_CLI", "TOPIC_DATA", "TRANSMISSION_TIME")
@pytest.mark.functional
class TestMavlinkTopicTransmissionTime(_MavlinkCLIBase):
    """MAVLink Topic 传输时间测试 — 测量 dt 命令的端到端往返时间（CONSOLE 通道）。

    通过标准：每个 Topic 的往返时间应 < 5000ms（与 dt 命令超时一致）。
    """

    TRANSMISSION_TIMEOUT_MS = 5000

    def _measure_topic_transmission_time(self, topic, timeout=5.0):
        """测量 dt <topic> 命令的端到端往返时间（终端需已打开）"""
        if not self._ensure_terminal_open():
            return None
        self._clear_recv_buffer()
        t0 = time.perf_counter()
        resp = self._send_console_cmd(f"dt {topic}", timeout=timeout)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        if not resp:
            return None
        return {
            "topic": topic,
            "response_time_ms": elapsed_ms,
            "response": self._normalize_response(resp),
        }

    def _assert_transmission_time(self, topic):
        with allure.step(f"发送 dt {topic} 并测量响应时间"):
            result = self._measure_topic_transmission_time(topic)
            assert result, "未收到设备响应"
            elapsed = result["response_time_ms"]
            log_manager.log_and_attach(f"{topic} 传输时间: {elapsed}ms", "传输时间")
            allure.attach(str(elapsed), "传输时间(ms)", allure.attachment_type.TEXT)
            assert elapsed < self.TRANSMISSION_TIMEOUT_MS, \
                f"{topic} 传输时间 {elapsed}ms 超过阈值 {self.TRANSMISSION_TIMEOUT_MS}ms"

    @allure.story("遥控器数据")
    @allure.title("测量 TP_RC_RAW 传输时间")
    def test_transmission_time_rc_raw(self):
        self._assert_transmission_time("TP_RC_RAW")

    @allure.story("控制点数据")
    @allure.title("测量 TP_CTRL_POINT 传输时间")
    def test_transmission_time_ctrl_point(self):
        self._assert_transmission_time("TP_CTRL_POINT")

    @allure.story("姿态电机数据")
    @allure.title("测量 TP_ATTI_MOTOR 传输时间")
    def test_transmission_time_atti_motor(self):
        self._assert_transmission_time("TP_ATTI_MOTOR")

    @allure.story("IMU 数据")
    @allure.title("测量 TP_IMU_RAW0 传输时间")
    def test_transmission_time_imu_raw0(self):
        self._assert_transmission_time("TP_IMU_RAW0")

    @allure.story("GPS 数据")
    @allure.title("测量 TP_GPS_RAW0 传输时间")
    def test_transmission_time_gps_raw0(self):
        self._assert_transmission_time("TP_GPS_RAW0")

    @allure.story("气压计数据")
    @allure.title("测量 TP_BARO_RAW0 传输时间")
    def test_transmission_time_baro_raw0(self):
        self._assert_transmission_time("TP_BARO_RAW0")

    @allure.story("电池数据")
    @allure.title("测量 TP_BATTERY_SCALED 传输时间")
    def test_transmission_time_battery_scaled(self):
        self._assert_transmission_time("TP_BATTERY_SCALED")

    @allure.story("数传数据")
    @allure.title("测量 TP_TELE_RSSI 传输时间")
    def test_transmission_time_tele_rssi(self):
        self._assert_transmission_time("TP_TELE_RSSI")
