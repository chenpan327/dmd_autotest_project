# coding: utf-8

"""
GCS-14 参数读取与设置（p1×12）— MAVLink 原生参数协议

业务背景：
    参数的 MAVLink 原生协议通道（区别于 GCS-26 的 CLI pp/sp/svp 路径）：
    单参读 → 改值 → 恢复 → 全量列表完整性。被测参数固定 INDOOR_DEBUG
    （调试开关，改值无飞行影响），原值以 MAVLink READ 回读为准，
    CLI `pp <名>` 单参查询作交叉对照。

协议构造速查（2026-09-11 真机验证，语义对齐 C# receive.cs）：
    ┌ 指定参数读取 → PARAM_REQUEST_READ(20) '<HBB128s'
    │   param_count=1 ⚠️ 名字槽个数（非索引！0=空请求，固件回无效帧）
    │   target_system=1, target_component=1, param_id=名字放 16B 槽 0 补零
    │   回包：PARAM_VALUE(22) 一条，带名带值（count=1/total=1）
    ├ 参数设置 → PARAM_SET(23) '<8fHBB128s'
    │   param_value=[值,0×7]（8 值槽）、param_count=1、target_system=0、
    │   target_component=1、param_id=名字放 16B 槽 0
    │   回包：PARAM_VALUE(22) 带名 echo 实际生效值——SET 确认=22 回传，
    │   不走 24
    └ 参数列表读取 → PARAM_REQUEST_LIST(21) '<BB'
        target_system=1, target_component=1（仅此 2 字段）
        回包：PARAM_VALUE(22) × ~64 帧流式（8 参数/帧）+
        PARAM_LIST_ACK(24, result=0) 在流吐完后回

真机实测口径（2026-09-10/11 debug_param_protocol.py 原始帧实锤）：
    - PARAM_VALUE(22) 分包布局 '<8f8HHH128s8B'：param_value[8f]/
      param_index[8H]/param_type[8B]/param_id[128s]=8×16B 名字区，
      count=本帧有效槽数、total=参数总数（509）
    - READ 回包在 count=1 语义下带名带值；count=0 空请求会得到无效帧
      （无名 + 残留值）——曾误判为"固件缺陷"，根因是构造错误；参照
      实现：fake_airplane._handle_param_request_read（对齐 C#
      HandleGetParam）
    - 完整性计数 = Σ 每帧 count，不能数帧数（~64 帧 ≠ 509 参数）
    - 流尾残帧只填 count 个槽，其余槽为未清零残留内存——解析须按
      count 截断，否则乱码名混入清单
    - parse_mavlink 对 8f 数组字段吞异常（fields 为空）→ struct 手解

注意：
    ⚠️ 取参别用无参 `pp` 全量 dump——回显 8s 吐不完会截断（注册表顺序
    VEL_CHECK_TEMP 开头，INDOOR_DEBUG 后段被截，2026-09-11 实测兜底
    误触发）；单参查询 `pp <名>` 秒回无截断。

用例：
    - test_gcs14_param_protocol   单读 → 改值 → 恢复 → 列表完整性
"""

import re
import socket
import struct
import time

import pytest
import allure

from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    FCBasicBase, log_manager, _cli_failed, _make_param_set, PARAM_LIST_TIMEOUT)
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    MSG_ID_PARAM_REQUEST_READ, MSG_ID_PARAM_REQUEST_LIST, MSG_ID_PARAM_VALUE,
    MSG_ID_PARAM_LIST_ACK)

# PARAM_VALUE(22) 载荷布局（v44 dialect）：8f + 8H + H + H + 128s + 8B
# —— 8f 数组字段 parse_mavlink 解析缺陷，struct 手解（2026-09-10 实锤）
PARAM_VALUE_FMT = '<8f8HHH128s8B'

# 被测参数（固定）：INDOOR_DEBUG 调试开关，改值无飞行影响——前辈
# test_mavlink_cli.py 的 sp/svp 用例同款选参先例（2026-09-10 dump 确认
# 存在，=1）。原值以 MAVLink READ 回读为准，改值后必恢复。
GCS14_PARAM_NAME = 'INDOOR_DEBUG'


def _parse_param_slots(msg):
    """手解 PARAM_VALUE → [(name, value), ...]（按 count 个有效槽，分包 8/帧）

    名字区 param_id[128] 按 16B 分槽，与 value[8f] 一一对应。
    ⚠️ 只解析前 count 个槽：流尾残帧（如 509=63×8+5）只填了 count 个，
    其余槽是固件未清零的残留内存（乱码名 + 1e7 级残留值，2026-09-11
    实测混入清单）。count=0（READ/SET 回包前的无效帧）无有效槽。
    """
    payload = msg.payload or b''
    size = struct.calcsize(PARAM_VALUE_FMT)
    if len(payload) < size:
        return []
    vals = struct.unpack(PARAM_VALUE_FMT, payload[:size])
    raw = vals[18]
    slots = []
    for i in range(min(vals[16], 8)):
        name = raw[i * 16:(i + 1) * 16].split(b'\x00')[0].decode(
            'ascii', errors='replace')
        if name:
            slots.append((name, vals[i]))
    return slots


def _parsed_frame_text(msg):
    """格式化解析后的 PARAM_VALUE 报文：MAVLink 头字段 + struct 手解字段

    载荷解析失败（长度不足的异常帧）时退回原始 hex 便于排障。
    """
    head = (f"start={getattr(msg, 'start', '?')} "
            f"length={getattr(msg, 'length', '?')} "
            f"seq={getattr(msg, 'seq', '?')} "
            f"sys_id={getattr(msg, 'sys_id', '?')} "
            f"comp_id={getattr(msg, 'comp_id', '?')} "
            f"msg_id={getattr(msg, 'msg_id', '?')}")
    p = _parse_param_value(msg)
    if p is None:
        payload = msg.payload or b''
        return f"{head}\n（载荷解析失败，原始 hex:\n{payload.hex(' ')}）"
    lines = [head,
             f"count={p['count']}（本帧有效槽） total={p['total']}（参数总数）"]
    slots = _parse_param_slots(msg)
    for i, (name, value) in enumerate(slots):
        lines.append(f"  槽{i}: {name} = {value:g}")
    if not slots:
        lines.append("  （无有效槽——疑似 count=0 无效帧）")
    return '\n'.join(lines)


def _parse_param_value(msg):
    """手解 PARAM_VALUE(22) → dict；异常帧返回 None

    parse_mavlink 对 8f 浮点数组字段吞异常导致 fields 为空，按
    liaoyutao test_mavlink_cli._parse_param_value 同款 struct 绕法手解。
    """
    payload = msg.payload or b''
    size = struct.calcsize(PARAM_VALUE_FMT)
    if len(payload) < size:
        return None
    vals = struct.unpack(PARAM_VALUE_FMT, payload[:size])
    return {
        'name': vals[18].split(b'\x00')[0].decode('ascii', errors='replace'),
        'value': vals[0],          # param_value[0]（分包帧=本帧首参数）
        'count': vals[16],         # 本帧有效参数槽数（分包 8/帧）
        'total': vals[17],         # 参数总数
        'index': vals[8],
    }


@allure.feature("FC 基础功能 P0/P1")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC")
@pytest.mark.functional
class TestGcs14Param(FCBasicBase):
    """GCS-14 参数读取与设置（p1×12）"""

    # ==================================================================
    # 公共辅助
    # ==================================================================

    def _wait_named_param_value(self, name, timeout=6.0):
        """等待 param_id 匹配的 PARAM_VALUE，返回参数值；脏帧丢弃重等

        READ/SET 回包在 count=1 语义下均带名，本方法两处通用
        （READ 单参读 + SET 改值/恢复回读）。LIST 后台流式帧会串进
        等待窗口，名字不匹配的帧一律丢弃留痕；命中帧附原始报文。
        """
        start = time.time()
        dropped = 0
        while time.time() - start < timeout:
            msg = self._wait_msg(MSG_ID_PARAM_VALUE, timeout=1.0)
            if msg is None:
                continue
            p = _parse_param_value(msg)
            if p and p['name'] == name:
                if dropped:
                    log_manager.logger.info(
                        f"丢弃串流脏帧 × {dropped}（期望 {name!r}）")
                log_manager.log_and_attach(
                    _parsed_frame_text(msg), f"PARAM_VALUE 解析帧（{name}）")
                return p['value']
            dropped += 1
            log_manager.log_and_attach(
                _parsed_frame_text(msg), f"PARAM_VALUE 脏帧 #{dropped}（期望 {name}）")
        return None

    # ==================================================================
    # 参数三协议
    # ==================================================================

    @allure.story("GCS-14 参数协议")
    @allure.title("GCS-14 参数列表/单读/设置 MAVLink 原生协议")
    def test_gcs14_param_protocol(self):
        """参数四环节：CLI 交叉校验 → 单参读 → 改值 0/恢复 → 列表完整性（GCS-14 p1×12）"""
        with allure.step(f"CLI 单参校验被测参数 {GCS14_PARAM_NAME}"):
            # 单参查询秒回无截断（无参 pp 全量 dump 8s 吐不完会截断，
            # 2026-09-11 实测导致兜底误触发）
            pp_out = self._cli(f"pp {GCS14_PARAM_NAME}", timeout=8.0)
            assert not _cli_failed(pp_out), (
                f"pp {GCS14_PARAM_NAME} 查询失败: {pp_out[:200]}")
            m = re.search(rf'{GCS14_PARAM_NAME}\s*[:=]\s*(-?[\d.]+)', pp_out)
            assert m, f"pp 单参查询未见 {GCS14_PARAM_NAME}: {pp_out[:200]}"
            cli_value = float(m.group(1))
            param_name = GCS14_PARAM_NAME
            log_manager.log_and_attach(
                f"CLI 视角: {GCS14_PARAM_NAME} = {cli_value}\n"
                f"pp 回显:\n{pp_out[:200]}", "参数选择")

        with allure.step("PARAM_REQUEST_READ(20) 单参读（count=1 名字槽语义）"):
            # param_count=名字槽个数（对齐 C# receive.cs HandleGetParam）：
            # 单参读 = 1 + 名字放 param_id 槽 0；count=0 是空请求，固件
            # 回无效帧（2026-09-11 实测，曾误判为固件缺陷）
            msg = MAVLink_message(
                msg_id=MSG_ID_PARAM_REQUEST_READ, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'param_count': 1, 'target_system': 1,
                        'target_component': 1,
                        'param_id': param_name.encode()})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            read_value = self._wait_named_param_value(param_name)
            assert read_value is not None, (
                f"PARAM_REQUEST_READ({param_name}) 未收到参数名匹配的 "
                f"PARAM_VALUE（count=1 语义下回包应带名）")
            log_manager.log_and_attach(
                f"READ 回包: {param_name} = {read_value}", "单参读")
            if abs(read_value - cli_value) > 1e-6:
                log_manager.logger.warning(
                    f"READ 回包值 {read_value} 与 CLI pp 值 {cli_value} "
                    f"不同（MAVLink 与 CLI 口径差异，存档不判失败）")

        with allure.step("PARAM_SET(23) 改值 0 → 回读核对"):
            # 真改值验证：写与当前不同的值（当前非 0 则写 0，反之写 1）
            target = 0.0 if abs(read_value) > 1e-6 else 1.0
            set_msg = _make_param_set(param_name, target,
                                      version=self.mavlink_version)
            self.gcs.send(set_msg, addr=(self.drone_ip, self.drone_port))
            readback = self._wait_named_param_value(param_name)
            assert readback is not None, (
                f"PARAM_SET 后未收到 {param_name} 的参数名匹配回读"
                f"（SET 回包应带名——实测口径）")
            log_manager.log_and_attach(
                f"SET {param_name}={target} → 回读 {readback}", "改值回读")
            assert abs(readback - target) < 1e-4, (
                f"改值未生效: 设 {target} 读 {readback}"
                f"（飞控可能做了范围钳制，记录口径）")

        with allure.step("恢复：PARAM_SET(23) 写回原值 → 回读核对"):
            set_msg = _make_param_set(param_name, read_value,
                                      version=self.mavlink_version)
            self.gcs.send(set_msg, addr=(self.drone_ip, self.drone_port))
            readback2 = self._wait_named_param_value(param_name)
            assert readback2 is not None, (
                f"恢复写入后未收到 {param_name} 的参数名匹配回读")
            log_manager.log_and_attach(
                f"恢复 SET {param_name}={read_value} → 回读 {readback2}",
                "恢复回读")
            assert abs(readback2 - read_value) < 1e-4, (
                f"恢复失败: 设 {read_value} 读 {readback2}——参数遗留改值态，"
                f"需人工恢复")

        with allure.step("PARAM_REQUEST_LIST(21) → 分包流式回传完整性"):
            # 完整性计数 = Σ 每帧 count（分包 8 参数/帧），不是帧数。
            # ⚠️ ACK(24) 在流尾才回——必须在同一循环里收，若先单独等 24
            # 会把已开跑的流式帧当不匹配消息吃掉（实测丢 ~120 参数）
            self._clear_recv_buffer()
            msg = MAVLink_message(
                msg_id=MSG_ID_PARAM_REQUEST_LIST, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'target_system': 1, 'target_component': 1})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            params_recv = frames = 0
            param_total = None
            ack = None
            param_table = {}          # name → value（全量清单，去重）
            start = last_rx = time.time()
            self.gcs.sock.settimeout(0.1)
            try:
                while time.time() - start < PARAM_LIST_TIMEOUT:
                    try:
                        received, addr = self.gcs.receive()
                    except socket.timeout:
                        # ACK(24) 在流尾回——收到且静默 1.5s 即认为吐完
                        if ack is not None and time.time() - last_rx > 1.5:
                            break
                        continue
                    if (received is None or not addr
                            or addr[0] != self.drone_ip):
                        continue
                    last_rx = time.time()
                    if received.msg_id == MSG_ID_PARAM_LIST_ACK:
                        ack = received
                    elif received.msg_id == MSG_ID_PARAM_VALUE:
                        frames += 1
                        p = _parse_param_value(received)
                        if p:
                            params_recv += p['count'] or 1
                            if p['total']:
                                param_total = p['total']
                        else:
                            params_recv += 1
                        for name, value in _parse_param_slots(received):
                            param_table.setdefault(name, value)
            finally:
                self.gcs.sock.settimeout(self.gcs.recv_timeout)
            duration = time.time() - start
            log_manager.log_and_attach(
                f"列表 ACK(24)="
                f"{'result=' + str(ack.fields.get('result')) if ack else '无'}，"
                f"分包 {frames} 帧 / Σcount={params_recv} 参数，"
                f"param_total={param_total}，用时 {duration:.0f}s",
                "参数列表回传")
            # 全量清单逐项打印 + 附件（存档：参数表快照，可 diff 固件版本间差异）
            if param_table:
                log_manager.log_and_attach(
                    f"参数全量清单（{len(param_table)} 项）：\n" + '\n'.join(
                        f"{name:36} {value:>16.6g}"
                        for name, value in sorted(param_table.items())),
                    "参数全量清单")
            assert params_recv >= 1, "PARAM_REQUEST_LIST 无任何 PARAM_VALUE 回传"
            if param_total:
                assert params_recv >= param_total * 0.9, (
                    f"参数列表回传不完整: Σcount={params_recv}/总量 {param_total}"
                    f"（<90%；分包 ~64 帧 × ~5 帧/s ≈ 13s——不足请核查链路丢帧）")
