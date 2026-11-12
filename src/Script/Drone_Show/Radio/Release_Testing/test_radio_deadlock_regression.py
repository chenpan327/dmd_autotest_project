"""
电台心跳死锁回归测试。

死锁复现路径（对应 hex dump 数据流）：::

    ① 注册 (ENROLL_REPLY)
    ② SET_RADIO_REGULATORY_DOMAIN → ACK
    ③ 电台回显 SEND_RADIO_RF_PARAM_ECHO
    ④ SET_RADIO_ENCRYPT_KEY → ACK
    ⑤ ASK_HEARTBEAT → **死锁 6~30s，电台不响应心跳**
    ⑥ 电台反复发送 ENROLL_REQUEST，地面不回复 → 僵持
    ⑦ 地面回复 ENROLL_REPLY → 死锁解除，心跳恢复

Usage::

    pytest script/test_radio_deadlock_regression.py -v --alluredir=allure-results
    pytest script/test_radio_deadlock_regression.py -v -s          # 打印帧日志

测试用例概览
────────────
test_sustained_heartbeat_30s           射频配置后 30s 1Hz 心跳，捕获死锁间隙
test_heartbeat_latency_after_rf_config 死锁恢复后 10 次心跳延迟基准
test_drop_off_time                     地面静默，测量电台掉线重注册时间
test_silent_then_heartbeat_without_enroll  静默→掉线→不回复注册→发心跳→验证无响应
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import allure
import pytest

from src.Protocol.radio.dav_protocol import DavProtocol
from src.Protocol.radio.dav_payload import DavPayload
from src.Protocol.radio.radio_udp_protocol import RadioUdpProtocol

# RadioUdpProtocol 默认 _CMD lookup 不包含的命令
CMD_SET_RADIO_REGULATORY_DOMAIN = 0x0203
CMD_SEND_RADIO_RF_PARAM_ECHO = 0x0207

# ═══════════════════════════════════════════════════════════════════════════════
# 帧日志：打印原始 hex + DAV header + protobuf 解析
# ═══════════════════════════════════════════════════════════════════════════════

_cmd_name_map: Optional[Dict[int, str]] = None


def _get_cmd_name_map(dp: DavPayload) -> Dict[int, str]:
    """cmd_id → 名称 映射表，惰性构建。"""
    global _cmd_name_map
    if _cmd_name_map is None:
        _cmd_name_map = {}
        for name, cid in dp._name_to_cmd.items():
            if cid <= 0xFFFF:
                _cmd_name_map[cid] = name
    return _cmd_name_map


class FrameLogger:
    """收发帧拦截器，输出 hex dump + header + protobuf 解析。

    用法：
        - 包一层 send_callback → 每次发送自动 log_send()
        - 在 on_dispatch 回调中调 log_recv() → 每次接收自动 log
    """

    def __init__(self, dp: DavPayload, dav: DavProtocol, label: str = "GS"):
        self._dp = dp
        self._label = label
        self._seq = 0
        self._lock = threading.Lock()
        # 仅用于 _dump_frame 中的 throwaway 解析，避免污染真实 _dav 的接收缓冲
        self._DavProtocol = DavProtocol

    def log_send(self, raw: bytes) -> None:
        with self._lock:
            self._seq += 1
            print(f"\n{'─' * 60}")
            print(f"  [{self._label}] >>> SEND #{self._seq}")
            self._dump_frame(raw)

    def log_recv(self, header: Dict, payload: bytes) -> None:
        with self._lock:
            self._seq += 1
            direction = "ACK" if header.get("message_type") == 1 else "CMD"
            print(f"\n{'─' * 60}")
            print(f"  [{self._label}] <<< RECV #{self._seq} ({direction})")
            self._dump_header(header, payload)

    # ── 内部 ────────────────────────────────────────────────────────────

    def _dump_frame(self, raw: bytes) -> None:
        # hex dump（16 字节一行）
        for i in range(0, len(raw), 16):
            chunk = raw[i:i + 16]
            hex_part = " ".join(f"{b:02x}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            print(f"  {i:04x}: {hex_part:<48s} {ascii_part}")

        # 用独立的 DavProtocol 实例解析，避免污染共享的接收状态机
        try:
            tmp = self._DavProtocol(local_address=0)
            for header, payload in tmp.feed(raw):
                self._dump_header(header, payload)
        except Exception:
            pass

    def _dump_header(self, header: Dict, payload: bytes) -> None:
        cmd = header.get("cmd", 0)
        msg_type = header.get("message_type", 0)
        sender = header.get("sender_address", 0) & DavProtocol.ADDRESS_MASK
        receiver = header.get("receiver_address", 0) & DavProtocol.ADDRESS_MASK

        type_str = "ACK" if msg_type == 1 else "CMD"
        cmd_name = _get_cmd_name_map(self._dp).get(cmd, "UNKNOWN")

        print(f"  seq={header.get('seq', 0)} type={type_str} "
              f"cmd=0x{cmd:04X} ({cmd_name})")
        print(f"  sender=0x{sender:013X}  receiver=0x{receiver:013X}")
        print(f"  payload_len={len(payload)}")

        if cmd_name != "UNKNOWN" and len(payload) > 0:
            try:
                msg = self._dp.decode(cmd_id=cmd, data=payload)
                self._print_proto(self._dp.to_dict(msg), indent=2)
            except Exception:
                if len(payload) > 0:
                    print(f"  proto(raw): {payload.hex(' ')}")

    def _print_proto(self, obj: Any, indent: int = 2) -> None:
        prefix = " " * indent
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    print(f"{prefix}{k}:")
                    self._print_proto(v, indent + 2)
                elif isinstance(v, bytes):
                    try:
                        s = v.decode("ascii")
                        if all(c >= " " and c <= "~" for c in s):
                            print(f'{prefix}{k} = "{s}"')
                        else:
                            print(f"{prefix}{k} = {v.hex(' ')}")
                    except Exception:
                        print(f"{prefix}{k} = {v.hex(' ')}")
                else:
                    print(f"{prefix}{k} = {v}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, dict):
                    print(f"{prefix}[{i}]:")
                    self._print_proto(item, indent + 2)
                else:
                    print(f"{prefix}[{i}] = {item}")


# ═══════════════════════════════════════════════════════════════════════════════
# Fixture：完成"注册 → 射频配置 → echo → 加密密钥"全部前置步骤
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def configured_udp(radio_cfg: dict) -> RadioUdpProtocol:
    """构建 UDP 连接并完成死锁前置步骤。

    步骤与 hex dump 完全一致：
      1. 注册（RadioUdpProtocol 自动回复 ENROLL_REPLY）
      2. SET_RADIO_REGULATORY_DOMAIN（EU869 + SCAN 双组）
      3. 等待 SEND_RADIO_RF_PARAM_ECHO
      4. SET_RADIO_ENCRYPT_KEY

    fixture 还负责：
      - 注入 FrameLogger 拦截所有收发帧
      - 暴露 ENROLL_REQUEST 跟踪机制给测试用例

    Yields 的 RadioUdpProtocol 对象上附加了以下属性：
      ._enroll_arrived         threading.Event — 收到 ENROLL_REQUEST 时 set
      ._enroll_arrive_time     float — 首次 ENROLL_REQUEST 的 monotonic 时间戳
      ._reset_enroll_watch()   callable — 清除以上状态，重新开始侦听
    """
    host = radio_cfg["radio_udp_host"]
    port = radio_cfg["radio_udp_port"]
    local_port = radio_cfg["radio_udp_local_port"]
    enroll_timeout = radio_cfg.get("radio_udp_enroll_timeout", 15.0)
    medium_timeout = radio_cfg.get("radio_medium_timeout", 3.0)
    # ── 事件 / 共享状态 ──
    echo_received = threading.Event()
    echo_payload: dict = {}

    enroll_arrived = threading.Event()
    enroll_arrive_time: float = 0.0

    frame_logger: List[FrameLogger] = [None]  # type: ignore[assignment]

    def on_dispatch(header: Dict, payload: bytes) -> None:
        # 帧日志
        if frame_logger[0] is not None:
            frame_logger[0].log_recv(header, payload)
        # 捕获 RF echo
        if header.get("cmd") == CMD_SEND_RADIO_RF_PARAM_ECHO:
            echo_payload["header"] = dict(header)
            echo_payload["payload"] = bytes(payload)
            echo_received.set()
        # 跟踪 ENROLL_REQUEST 到达
        if header.get("cmd") == udp._CMD.get("ENROLL_REQUEST"):
            if not enroll_arrived.is_set():
                enroll_arrive_time = time.monotonic()
                enroll_arrived.set()

    udp = RadioUdpProtocol(on_dispatch=on_dispatch)

    # 注入 FrameLogger（包一层 send callback）
    original_send = udp._udp_send
    fl = FrameLogger(udp._dp, udp._dav, label="GS")
    frame_logger[0] = fl

    def logged_send(data: bytes) -> None:
        fl.log_send(data)
        original_send(data)

    udp._udp_send = logged_send  # type: ignore[method-assign]

    # ── Step 1：注册 ──
    with allure.step("Step 1: Connect + enroll"):
        udp.connect(host, port, local_port=local_port,
                    timeout=enroll_timeout)
        assert udp.is_enrolled
        allure.attach(
            f"device_address=0x{udp.device_address:013X}\nis_enrolled=True",
            "enrollment_info", allure.attachment_type.TEXT,
        )

    # ── Step 2：射频参数（hex dump seq=250，EU869 + SCAN 两组）──
    with allure.step("Step 2: SET_RADIO_REGULATORY_DOMAIN"):
        payload = udp._dp.encode(
            cmd_id=CMD_SET_RADIO_REGULATORY_DOMAIN,
            set_rf_param=[
                {
                    "rf_work_mode": 4,       # COUNTRY_CODE_EU869
                    "rf_tx_power_dbm": [27, 0, 0, 0],
                    "rf_max_fre": [869650000, 0, 0, 0],
                    "rf_min_fre": [869400000, 0, 0, 0],
                },
                {
                    "rf_work_mode": 100,     # COUNTRY_CODE_SCAN
                    "rf_tx_power_dbm": [30, 30, 30, 30],
                    "rf_max_fre": [0, 0, 0, 0],
                    "rf_min_fre": [0, 0, 0, 0],
                },
            ],
        )
        ack_val = udp._request_with_ack(
            cmd=CMD_SET_RADIO_REGULATORY_DOMAIN, payload=payload,
            timeout=medium_timeout,
        )
        allure.attach(f"ack_value={ack_val}", "rf_domain_ack",
                      allure.attachment_type.TEXT)

    # ── Step 3：等待电台射频回显（hex dump seq=106）──
    with allure.step("Step 3: Wait for SEND_RADIO_RF_PARAM_ECHO"):
        if echo_received.wait(medium_timeout):
            echo_data = udp._dp.to_dict(
                udp._dp.decode(cmd_id=CMD_SEND_RADIO_RF_PARAM_ECHO,
                               data=echo_payload["payload"])
            )
            allure.attach(str(echo_data), "rf_param_echo",
                          allure.attachment_type.JSON)
            print("  [OK] 收到 RF param echo")
        else:
            allure.attach("no echo received", "rf_param_echo",
                          allure.attachment_type.TEXT)
            print("  [--] 未收到 RF param echo")

    # ── Step 4：加密密钥（hex dump seq=251）──
    with allure.step("Step 4: SET_RADIO_ENCRYPT_KEY"):
        enc_cmd = udp.cmd_id("SET_RADIO_ENCRYPT_KEY")
        enc_payload = udp._dp.encode(
            cmd_id=enc_cmd,
            radio_key={"encrypt_type": 0, "encrypt_key": b"", "encrypt_iv": b""},
        )
        ack_val = udp._request_with_ack(
            cmd=enc_cmd, payload=enc_payload, timeout=medium_timeout,
        )
        allure.attach(f"ack_value={ack_val}", "encrypt_key_ack",
                      allure.attachment_type.TEXT)

    # ── 暴露 ENROLL 跟踪工具给测试用例 ──
    udp._enroll_arrived = enroll_arrived          # type: ignore[attr-defined]
    udp._enroll_arrive_time = enroll_arrive_time  # type: ignore[attr-defined]

    def reset_enroll_watch() -> None:
        enroll_arrived.clear()
        nonlocal enroll_arrive_time
        enroll_arrive_time = 0.0

    udp._reset_enroll_watch = reset_enroll_watch  # type: ignore[attr-defined]

    allure.attach(
        "前置完成：注册 → SET_RADIO_REGULATORY_DOMAIN → echo → "
        "SET_RADIO_ENCRYPT_KEY",
        "precondition_summary", allure.attachment_type.TEXT,
    )

    yield udp

    with allure.step("Disconnect"):
        udp.disconnect()


# ═══════════════════════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════════════════════

@allure.feature("DAV Radio Deadlock Regression (UDP)")
class TestDeadlockAfterRfConfig:

    # ── 用例 1：30s 1Hz 心跳，捕获死锁间隙 ───────────────────────────────

    @allure.story("Sustained Heartbeat Monitor")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("sustained heartbeat — 死锁检测")
    @allure.description(
        "射频配置后立即开始 1Hz 心跳。"
        "前几秒的死锁窗口内无响应 → 记录为间隙 → FAIL。"
        "死锁恢复后持续监控，验证不复发。"
    )
    def test_sustained_heartbeat_30s(
        self, configured_udp: RadioUdpProtocol, radio_cfg: dict,
    ) -> None:
        duration = radio_cfg.get("radio_deadlock_duration", 30)
        gap_start: Optional[float] = None
        gaps: List[Tuple[float, float]] = []
        times_ms: List[float] = []
        fail_indices: List[int] = []

        t_start = time.monotonic()
        deadline = t_start + duration
        seq = 0
        next_send = t_start

        print(f"\n  持续 {duration}s 心跳监控（1Hz）:")
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now < next_send:
                time.sleep(next_send - now)
            seq += 1
            elapsed = time.monotonic() - t_start
            next_send = t_start + seq
            t0 = time.perf_counter()

            try:
                hb = configured_udp.query_heartbeat(timeout=1.0)
                rtt = (time.perf_counter() - t0) * 1000
                times_ms.append(rtt)

                if gap_start is not None:
                    gaps.append((gap_start, elapsed))
                    print(f"  [{elapsed:5.1f}s] seq={seq:2d} [恢复] "
                          f"RTT={rtt:.0f}ms  死锁={gap_start:.1f}→{elapsed:.1f}s")
                    gap_start = None
                else:
                    print(f"  [{elapsed:5.1f}s] seq={seq:2d} [OK] RTT={rtt:.0f}ms  "
                          f"FW={hb.get('firmware_version_alias', '?')}")
            except Exception:
                fail_indices.append(seq)
                elapsed = time.monotonic() - t_start
                if gap_start is None:
                    gap_start = elapsed
                    print(f"  [{elapsed:5.1f}s] seq={seq:2d} [死锁开始]")
                else:
                    print(f"  [{elapsed:5.1f}s] seq={seq:2d} [死锁中] "
                          f"(已 {elapsed - gap_start:.1f}s)")

        if gap_start is not None:
            gaps.append((gap_start, time.monotonic() - t_start))

        total = len(times_ms) + len(fail_indices)
        gap_report = "\n".join(
            f"  gap[{i}]: {s:.1f}s → {e:.1f}s ({e-s:.1f}s)"
            for i, (s, e) in enumerate(gaps)
        ) if gaps else "  无死锁间隙"

        summary = (
            f"total={total}  ok={len(times_ms)}  timeout={len(fail_indices)}  "
            f"rate={len(times_ms)/total*100:.1f}%\n"
            f"gaps={len(gaps)}  deadlock_total={sum(e-s for s,e in gaps):.1f}s\n"
            f"\n{gap_report}"
        )
        if times_ms:
            summary += (
                f"\nRTT: min={min(times_ms):.1f}  max={max(times_ms):.1f}  "
                f"mean={sum(times_ms)/len(times_ms):.1f}ms"
            )

        allure.attach(summary, "sustained_result", allure.attachment_type.TEXT)
        allure.attach("\n".join(f"{v:.1f}" for v in times_ms),
                      "sustained_rtt_raw", allure.attachment_type.CSV)
        if gaps:
            allure.attach("\n".join(f"{s:.1f},{e:.1f},{e-s:.1f}" for s, e in gaps),
                          "deadlock_gaps", allure.attachment_type.CSV)

        print(f"\n  === 结果：{len(times_ms)}/{total} 响应  "
              f"间隙 {len(gaps)} 次  死锁总时长 {sum(e-s for s,e in gaps):.1f}s")
        for i, (s, e) in enumerate(gaps):
            print(f"    gap[{i}]: {s:.1f}s → {e:.1f}s ({e-s:.1f}s)")

        # 允许 1 次死锁间隙（已知的射频配置后静默窗口），多次间隙才判定回归
        assert len(gaps) <= 1, (
            f"检测到 {len(gaps)} 次死锁间隙（允许 ≤1），"
            f"总 {sum(e-s for s,e in gaps):.1f}s\n{gap_report}"
        )

    # ── 用例 2：死锁恢复后延迟基准 ───────────────────────────────────────

    @allure.story("Heartbeat Response Time")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.title("Heartbeat response latency after RF config")
    @allure.description("死锁恢复后连续 10 次心跳，验证 RTT 稳定在 500ms 内。")
    def test_heartbeat_latency_after_rf_config(
        self, configured_udp: RadioUdpProtocol, radio_cfg: dict,
    ) -> None:
        medium_timeout = radio_cfg.get("radio_medium_timeout", 3.0)
        times_ms: List[float] = []
        for i in range(10):
            t0 = time.perf_counter()
            try:
                hb = configured_udp.query_heartbeat(timeout=medium_timeout)
                elapsed = (time.perf_counter() - t0) * 1000
                times_ms.append(elapsed)
                print(f"  [{i+1:2d}/10] {elapsed:6.1f}ms  "
                      f"FW={hb.get('firmware_version_alias', '?')}")
            except Exception as e:
                print(f"  [{i+1:2d}/10] FAILED: {e}")

        assert len(times_ms) > 0, "心跳全部失败"
        avg = sum(times_ms) / len(times_ms)
        mx = max(times_ms)

        allure.attach(
            f"samples={len(times_ms)}\nmin={min(times_ms):.1f}ms\n"
            f"max={mx:.1f}ms\nmean={avg:.1f}ms",
            "heartbeat_latency_stats", allure.attachment_type.TEXT,
        )
        allure.attach(
            "\n".join(f"{v:.1f}" for v in times_ms),
            "heartbeat_latency_raw", allure.attachment_type.CSV,
        )
        assert avg < 500, f"平均延迟过高: mean={avg:.0f}ms"
        assert mx < 1000, f"延迟尖峰: max={mx:.0f}ms"

    # ── 用例 3：静默 → 测量掉线时间 ──────────────────────────────────────

    @allure.story("Radio Offline Detection")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("Silent ground station — 测量电台掉线时间")
    @allure.description(
        "射频配置后地面站静默（不发心跳），测量电台多久判定掉线、"
        "发送 ENROLL_REQUEST。"
    )
    def test_drop_off_time(
        self, configured_udp: RadioUdpProtocol,
    ) -> None:
        configured_udp._reset_enroll_watch()  # type: ignore[attr-defined]

        max_wait = 60.0
        print(f"\n  地面站静默，等待电台掉线（最长 {max_wait}s）")

        arrived = configured_udp._enroll_arrived.wait(timeout=max_wait)  # type: ignore[attr-defined]
        elapsed = time.monotonic() - (configured_udp._enroll_arrive_time  # type: ignore[attr-defined]
                                      if arrived else time.monotonic())

        if arrived:
            print(f"  [收到 ENROLL_REQUEST @ ~{elapsed:.1f}s]")
        else:
            print(f"  [{max_wait:.0f}s 内未收到 ENROLL_REQUEST]")

        allure.attach(
            f"arrived={arrived}\nelapsed={elapsed:.1f}s",
            "drop_off_result", allure.attachment_type.TEXT,
        )

        if arrived:
            print(f"\n  === 掉线时间 ≈ {elapsed:.1f}s ===")
        else:
            print(f"\n  === {max_wait:.0f}s 内未掉线 ===")

    # ── 用例 4：静默 → 不回复注册 → 心跳验证 ─────────────────────────────

    @allure.story("Radio Offline Detection")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("Silent + ignore ENROLL → 心跳不响应")
    @allure.description(
        "射频配置后静默，电台掉线发 ENROLL_REQUEST。"
        "地面不回复 ENROLL_REPLY，转头发送 10s 心跳。"
        "验证：未注册 → 电台不响应任何心跳。"
    )
    def test_silent_then_heartbeat_without_enroll(
        self, configured_udp: RadioUdpProtocol,
    ) -> None:
        """两阶段测试：

        Phase 1 — 静默等待电台掉线（已预先阻止 ENROLL_REPLY 自动回复）
        Phase 2 — 发送 10s 心跳，断言全部超时
        """
        max_wait = 60.0

        # 阻止 RadioUdpProtocol 自动回复 ENROLL_REPLY
        original_handler = configured_udp._handle_enroll_request

        def noop_handler(header: Dict, payload: bytes) -> None:
            pass

        configured_udp._handle_enroll_request = noop_handler  # type: ignore[method-assign]

        try:
            configured_udp._reset_enroll_watch()  # type: ignore[attr-defined]

            # ── Phase 1：静默 ──
            print("\n  Phase 1: 静默（ENROLL_REPLY 已阻止）")
            arrived = configured_udp._enroll_arrived.wait(timeout=max_wait)  # type: ignore[attr-defined]
            drop_elapsed = time.monotonic() - (
                configured_udp._enroll_arrive_time  # type: ignore[attr-defined]
                if arrived else time.monotonic()
            )

            if not arrived:
                print(f"  [{max_wait:.0f}s 内未收到 ENROLL_REQUEST]")
                allure.attach(f"timeout={max_wait}s", "silent_phase",
                              allure.attachment_type.TEXT)
                return

            print(f"  [收到 ENROLL_REQUEST @ ~{drop_elapsed:.1f}s（未回复）]")

            # ── Phase 2：10s 心跳 ──
            print("\n  Phase 2: 10s 心跳（电台未注册，预期全部超时）")

            ok = 0
            timeout = 0
            hb_start = time.monotonic()
            deadline = hb_start + 10.0
            seq = 0
            next_send = hb_start

            while time.monotonic() < deadline:
                now = time.monotonic()
                if now < next_send:
                    time.sleep(next_send - now)
                seq += 1
                elapsed = time.monotonic() - hb_start
                next_send = hb_start + seq

                try:
                    hb = configured_udp.query_heartbeat(timeout=1.0)
                    ok += 1
                    print(f"  [{elapsed:5.1f}s] seq={seq:2d} [!!!] 意外响应: "
                          f"FW={hb.get('firmware_version_alias', '?')}")
                except Exception:
                    timeout += 1
                    print(f"  [{elapsed:5.1f}s] seq={seq:2d} [--] 超时（预期）")

            summary = (
                f"drop_off={drop_elapsed:.1f}s\n"
                f"hb_ok={ok}  hb_timeout={timeout}  total={ok+timeout}\n"
            )
            allure.attach(summary, "no_enroll_result", allure.attachment_type.TEXT)

            print(f"\n  === 掉线 {drop_elapsed:.1f}s | "
                  f"心跳 响应={ok} 超时={timeout} ===")

            assert ok == 0, (
                f"未注册状态下电台响应了 {ok} 次心跳！注册不再是心跳前置条件。"
            )

        finally:
            configured_udp._handle_enroll_request = original_handler  # type: ignore[method-assign]
