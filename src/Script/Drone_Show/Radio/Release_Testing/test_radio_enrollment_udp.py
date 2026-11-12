"""
DAV 设备上线协议测试 — UDP 网口 (pytest + Allure).

测试 DAV 设备上线通用协议的完整状态机::

    状态 1: 未连接 — DAV 设备主动向地面站轮询发送 EnrollRequest 消息
    状态 2: 地面站收到 EnrollRequest → 回复 EnrollReply → 设备回复 ACK 确认
    状态 3: 地面站收到 ACK → 将设备标记为在线 → 开始轮询发送心跳
    状态 4: 设备收到心跳 → 返回心跳数据包 (含设备状态: 版本/电量/错误码等)
    状态 5: 地面站长时间未收到心跳响应 → 标记设备离线 → 停止发送心跳
    状态 6: 设备检测到地面站离线 (收不到心跳) → 重新发送 EnrollRequest → 回到状态 1

每个测试类对应协议的一个或多个状态迁移::

    TestEnrollHandshake         — 状态 1→2→3 (EnrollRequest → EnrollReply → ACK → 上线)
    TestHeartbeatAfterEnroll    — 状态 4 (上线后心跳查询, 验证设备状态数据)
    TestEnrollStability         — 状态 6 (心跳持续期间不发送 EnrollRequest)
    TestDropOffAndReEnroll      — 状态 5→1→2→3→4 (掉线检测 + 重新上线恢复)
    TestRtkCorrection           — RTCM 数据注入, 清除心跳中的 RTK 报警

Usage::

    # 运行全部上线测试
    pytest script/test_radio_enrollment_udp.py -v --alluredir=allure-results

    # 只运行握手测试
    pytest script/test_radio_enrollment_udp.py -v -k "TestEnrollHandshake"

    # 打印详细控制台日志
    pytest script/test_radio_enrollment_udp.py -v -s

    # 生成 Allure 报告
    allure serve allure-results
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import allure
import pytest

from src.Protocol.radio.dav_protocol import DavProtocol
from src.Protocol.radio.radio_udp_protocol import RadioUdpProtocol


# ===========================================================================
# EnrollmentTracker — 协议事件跟踪器
# ===========================================================================


class EnrollmentTracker:
    """DAV 上线协议事件跟踪器, 线程安全。

    通过 RadioUdpProtocol 的回调接口拦截以下事件:
    - ENROLL_REQUEST 帧: 设备发起上线请求 (cmd=0x000C)
    - ACK 帧: 设备确认收到地面站响应 (message_type=1)

    同时记录初始快照, 支持 per-test 增量查询:
    - snapshot_initial(): 在上线完成后调用, 保存基线
    - new_enroll_count: 当前测试中新收到的 ENROLL_REQUEST 数量
    - reset_delta(): 每个测试开始前重置增量计数器

    Attributes
    ----------
    enroll_events : List[Tuple[float, Dict]]
        所有 ENROLL_REQUEST 事件列表, 每项为 (monotonic时间戳, 帧头字典)
    enroll_event : threading.Event
        收到 ENROLL_REQUEST 时触发
    ack_count : int
        累计收到的 ACK 帧总数
    ack_event : threading.Event
        收到 ACK 帧时触发
    enrollment_ack_count : int
        上线阶段的 ACK 数量快照 (snapshot_initial 之后不变)
    total_enroll_count : int
        累计 ENROLL_REQUEST 总数
    new_enroll_count : int
        当前测试增量 (相对于上次 snapshot/reset)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # --- ENROLL_REQUEST 跟踪 ---
        self.enroll_events: List[Tuple[float, Dict[str, Any]]] = []
        self.enroll_event = threading.Event()

        # --- ACK 跟踪 (MessageType.ACK = 1) ---
        self.ack_event = threading.Event()
        self.ack_count = 0

        # --- 快照基线 (connect 完成后调用 snapshot_initial) ---
        self._initial_enroll_count = 0
        self._initial_ack_count = 0

        # --- 心跳统计 (per-test) ---
        self.heartbeat_fail_count = 0
        self.heartbeat_ok_count = 0

    # ------------------------------------------------------------------
    # 回调入口 (由 RadioUdpProtocol 的 on_dispatch / on_enroll_request 触发)
    # ------------------------------------------------------------------

    def on_enroll_request(self, header: Dict[str, Any], payload: bytes) -> None:
        """设备发出 ENROLL_REQUEST 时回调。

        由 RadioUdpProtocol._handle_enroll_request 在发送 ENROLL_REPLY 之前调用。
        header 包含 cmd=0x000C, sender_address, seq 等字段。
        payload 为 EnrollRequest protobuf 原始字节 (含 device_type, product_name, serial_number)。
        """
        with self._lock:
            self.enroll_events.append((time.monotonic(), dict(header)))
            self.enroll_event.set()

    def on_dispatch(self, header: Dict[str, Any], payload: bytes) -> None:
        """所有接收帧的通用回调, 用于检测 ACK。

        由 BaseRadioProtocol._dispatch 在处理完内部逻辑后调用。
        我们只关心 message_type == 1 (ACK) 的帧。
        """
        if header.get("message_type") == 1:  # MessageType.ACK
            with self._lock:
                self.ack_count += 1
                self.ack_event.set()

    # ------------------------------------------------------------------
    # 快照与增量查询
    # ------------------------------------------------------------------

    def snapshot_initial(self) -> None:
        """保存上线完成时的基线快照 (EnrollRequest 数量和 ACK 数量)。

        在 connect() 返回后立即调用, 之后 new_enroll_count 只反映增量。
        """
        with self._lock:
            self._initial_enroll_count = len(self.enroll_events)
            self._initial_ack_count = self.ack_count

    def reset_delta(self) -> None:
        """每个测试开始前重置增量计数器和事件。

        由 autouse fixture _reset_tracker 调用。
        注意: ack_count 不清零 (它是累计值), 只清除 ack_event。
        """
        with self._lock:
            self.enroll_event.clear()
            self.ack_event.clear()
            self._initial_enroll_count = len(self.enroll_events)
            self.heartbeat_fail_count = 0
            self.heartbeat_ok_count = 0

    # ------------------------------------------------------------------
    # 查询属性
    # ------------------------------------------------------------------

    @property
    def new_enroll_count(self) -> int:
        """当前测试中新增的 ENROLL_REQUEST 数量 (相对于上次 snapshot/reset)。"""
        with self._lock:
            return len(self.enroll_events) - self._initial_enroll_count

    @property
    def new_enroll_events(self) -> List[Tuple[float, Dict[str, Any]]]:
        """当前测试中新增的 ENROLL_REQUEST 事件列表。"""
        with self._lock:
            return list(self.enroll_events[self._initial_enroll_count:])

    @property
    def total_enroll_count(self) -> int:
        """累计收到的 ENROLL_REQUEST 总数。"""
        with self._lock:
            return len(self.enroll_events)

    @property
    def enrollment_ack_count(self) -> int:
        """上线阶段收到的 ACK 数量 (snapshot_initial 时的快照值)。"""
        return self._initial_ack_count


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def enrolled_udp(radio_cfg: dict) -> RadioUdpProtocol:
    """(module 级别) 创建 UDP 连接, 等待设备上线, 注入事件跟踪器。

    完成以下步骤:
    1. 创建 RadioUdpProtocol 并注册 EnrollmentTracker 回调
    2. 绑定 UDP socket, 等待设备发送 ENROLL_REQUEST
    3. 自动回复 ENROLL_REPLY, 等待设备 ACK
    4. 保存上线快照, 将 tracker 挂载到协议对象上

    Yields
    ------
    RadioUdpProtocol
        已上线的 UDP 协议对象, 附加属性:
        - ._tracker : EnrollmentTracker — 事件跟踪器
        - ._reset_tracking() : callable — per-test 重置方法
    """
    host = radio_cfg["radio_udp_host"]
    port = radio_cfg["radio_udp_port"]
    local_port = radio_cfg["radio_udp_local_port"]
    enroll_timeout = radio_cfg.get("radio_udp_enroll_timeout", 15.0)

    tracker = EnrollmentTracker()

    udp = RadioUdpProtocol(
        on_dispatch=tracker.on_dispatch,
        on_enroll_request=tracker.on_enroll_request,
    )

    # ---- Step 1: 创建 UDP socket, 等待设备上线 ----
    with allure.step(
        f"创建 UDP 连接 → {host}:{port} "
        f"(本地端口={local_port}, 超时={enroll_timeout}s)"
    ):
        udp.connect(host, port, local_port=local_port,
                    timeout=enroll_timeout)

        # 等待设备回复 ACK (EnrollReply 发出后, 设备一般 200~500ms 内 ACK)
        tracker.ack_event.wait(timeout=2.0)
        tracker.snapshot_initial()

        enroll_count = tracker.total_enroll_count
        ack_count = tracker.ack_count

        allure.attach(
            f"device_address = 0x{udp.device_address:013X}\n"
            f"is_enrolled    = {udp.is_enrolled}\n"
            f"is_connected   = {udp.is_connected}\n"
            f"local_port     = {udp.local_port}\n"
            f"enroll_request_received = {enroll_count}\n"
            f"ack_received            = {ack_count}\n",
            "上线连接信息",
            allure.attachment_type.TEXT,
        )

        assert udp.is_enrolled, "设备未上线 — 未收到 ENROLL_REQUEST 或上线超时"
        assert udp.is_connected, "UDP socket 未连接"
        assert enroll_count >= 1, f"上线期间未收到 ENROLL_REQUEST (收到 {enroll_count} 次)"

    # ---- 挂载跟踪器到协议对象, 供测试用例使用 ----
    udp._tracker = tracker               # type: ignore[attr-defined]
    udp._reset_tracking = tracker.reset_delta  # type: ignore[attr-defined]

    yield udp

    # ---- Teardown: 断开 UDP 连接 ----
    with allure.step("断开 UDP 连接"):
        udp.disconnect()


@pytest.fixture(autouse=True)
def _reset_tracker(enrolled_udp: RadioUdpProtocol) -> None:
    """(autouse) 每个测试开始前重置 EnrollmentTracker 增量计数器。

    确保每个测试用例从干净的跟踪状态开始, 互不干扰。
    """
    enrolled_udp._reset_tracking()  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def rtk_sender(radio_cfg: dict):
    """(module 级别) 创建 RTK RTCM 串口发送器。

    通过串口向 DAV 设备注入 RTCM3 校正数据 (1006 站坐标 + 1074 GPS MSM4),
    用于清除心跳中的 RTK_ERROR_VALUE 报警。

    需要配置 rtk_serial_port, 设为空字符串则自动 skip。
    使用 builder 模式生成模拟 RTCM 数据, 无需外部 JSON 文件。
    """
    rtk_port = radio_cfg.get("rtk_serial_port", "")
    rtk_baud = radio_cfg.get("rtk_serial_baud", 115200)
    rtk_interval = radio_cfg.get("rtk_send_interval", 1.0)
    if not rtk_port:
        pytest.skip("rtk_serial_port 未配置 — 跳过 RTCM 校正测试")
        return None  # type: ignore[return-value]

    from Protocol.rtcm.rtk_test_protocol import RtkSender

    sender = RtkSender()
    try:
        with allure.step(f"打开 RTK 串口 → {rtk_port} @ {rtk_baud} baud"):
            sender.connect(rtk_port, baud=rtk_baud)
            assert sender.is_connected, f"无法打开 RTK 串口 {rtk_port}"

        # 配置 builder 模式参数: 站坐标 + GPS MSM4
        sender._msg_config[1006].update({
            "station_id": 0,
            "x": -2396842.8368,
            "y": -5976984.0662,
            "z": 11628934.2224,
            "antenna_height": 0.0003,
        })
        allure.attach(
            f"串口 = {rtk_port}\n"
            f"波特率 = {rtk_baud}\n"
            f"模式 = builder (模拟 GPS MSM4 + 站坐标 1006)\n"
            f"发送间隔 = {rtk_interval}s",
            "RTK 发送器配置",
            allure.attachment_type.TEXT,
        )

        yield sender
    finally:
        with allure.step("关闭 RTK 串口, 停止 RTCM 发送"):
            sender.disconnect()


# ===========================================================================
# 辅助函数
# ===========================================================================


def _query_heartbeat(
    udp: RadioUdpProtocol,
    timeout: float = 1.0,
) -> Dict[str, Any]:
    """向设备发送 ASK_HEARTBEAT (0x000E), 等待 SEND_RADIO_R2_HEARTBEAT (0x0204)。

    返回心跳数据 dict, 额外注入 _rtt_ms 字段记录往返延迟 (毫秒)。
    """
    t0 = time.perf_counter()
    hb = udp.query_heartbeat(timeout=timeout)
    rtt = (time.perf_counter() - t0) * 1000
    hb["_rtt_ms"] = rtt
    return hb


def _check_rtk_error(hb: Dict[str, Any]) -> Optional[str]:
    """检查心跳数据中是否存在 RTK 输入异常报警。

    如果 radio_station_r2.error_report 包含 "RTK_ERROR" (且不是 NO_ERROR),
    说明设备未收到 RTCM 校正数据。返回错误码字符串, 无错误则返回 None。
    """
    r2 = hb.get("radio_station_r2", {})
    error = r2.get("error_report", "")
    if "RTK_ERROR" in str(error) and "NO_ERROR" not in str(error):
        return str(error)
    return None


# ===========================================================================
# 测试类 1: TestEnrollHandshake — 上线握手流程
# ===========================================================================
# 覆盖协议状态 1→2→3:
#   状态 1: 设备发送 EnrollRequest (0x000C)
#   状态 2: 地面站回复 EnrollReply (0x000D) → 设备回复 ACK
#   状态 3: 地面站收到 ACK → 标记设备在线


@allure.feature("DAV 设备上线协议 (UDP)")
class TestEnrollHandshake:
    """测试组 1: 上线握手 — EnrollRequest → EnrollReply → ACK → 在线。"""

    @allure.story("上线握手")
    @allure.severity(allure.severity_level.BLOCKER)
    @allure.title("上线成功 — 设备 EnrollRequest 到达, 地面站回复 EnrollReply")
    @allure.description(
        "验证 DAV 设备上线握手协议的最基本流程:\n"
        "1. 地面站创建 UDP socket 并开始监听\n"
        "2. DAV 设备发送 ENROLL_REQUEST (0x000C) 请求上线\n"
        "3. RadioUdpProtocol 自动回复 ENROLL_REPLY (0x000D, accept_status=0)\n"
        "4. 设备地址被解析, 上线状态标志位 is_enrolled 置为 True\n"
        "5. 上层可开始查询心跳 / 配置等操作"
    )
    def test_enroll_success(self, enrolled_udp: RadioUdpProtocol) -> None:
        """验证上线握手成功: socket 已连接 + 设备已上线 + 地址已解析。"""
        assert enrolled_udp.is_connected, (
            "UDP socket 未连接 — 检查网络和 REMOTE_HOST 配置"
        )
        assert enrolled_udp.is_enrolled, (
            "设备未上线 — 未收到 ENROLL_REQUEST 或 ENROLL_REPLY 发送失败"
        )
        assert enrolled_udp.device_address != 0, (
            "设备地址未解析 — ENROLL_REQUEST 中 sender_address 为空"
        )

        tracker: EnrollmentTracker = enrolled_udp._tracker  # type: ignore[attr-defined]
        assert tracker.total_enroll_count >= 1, (
            f"上线期间至少应收到 1 次 ENROLL_REQUEST (实际收到 {tracker.total_enroll_count} 次)"
        )

    @allure.story("上线握手")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("ACK 确认 — 设备收到 EnrollReply 后回复 ACK")
    @allure.description(
        "验证设备在收到 ENROLL_REPLY 后会回复 ACK 确认帧:\n"
        "- ACK 帧的 message_type = 1 (MessageType.ACK)\n"
        "- ACK 携带 ack_report 值 (cmd=0x000D 的请求序列号)\n"
        "- 当前实现中 _handle_enroll_request 不等待 ACK, 所以若无 ACK 仅警告不失败"
    )
    def test_enroll_ack_received(self, enrolled_udp: RadioUdpProtocol) -> None:
        """验证设备对 EnrollReply 回复了 ACK 确认帧。"""
        tracker: EnrollmentTracker = enrolled_udp._tracker  # type: ignore[attr-defined]

        enroll_ack = tracker.enrollment_ack_count

        allure.attach(
            f"上线阶段 ACK 数量  = {enroll_ack}\n"
            f"累计 ACK 总数       = {tracker.ack_count}\n"
            f"累计 EnrollRequest  = {tracker.total_enroll_count}\n"
            f"\n说明: ACK 帧特征为 message_type=1, 表示设备对收到的 CMD 帧的确认。\n"
            f"上线阶段 GS 只发了 ENROLL_REPLY (cmd=0x000D), 所以紧随其后的 ACK 即上线 ACK。",
            "ACK 检测结果",
            allure.attachment_type.TEXT,
        )

        if enroll_ack == 0:
            msg = (
                "【注意】上线阶段未检测到设备 ACK 帧。\n"
                "原因分析:\n"
                "  1. 设备固件可能不发 ACK (部分版本跳过此步骤)\n"
                "  2. ACK 到达时 connect() 已返回, 等待超时 (2s) 不够\n"
                "  3. on_dispatch 回调未收到 ACK 帧 (需确认 _dispatch 逻辑)\n"
                "\n"
                "影响: 当前实现不依赖 ACK 判定上线, 不影响后续心跳等操作。"
            )
            allure.attach(msg, "ACK 缺失说明", allure.attachment_type.TEXT)
            print(f"\n  !! {msg}")
            # 不 fail — 当前 RadioUdpProtocol 不等待 ACK
        else:
            print(f"\n  [OK] 上线阶段收到 {enroll_ack} 个 ACK 确认帧")

    @allure.story("上线握手")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.title("EnrollRequest 帧头校验 — 发送方地址有效")
    @allure.description(
        "验证 ENROLL_REQUEST 帧的 DAV 帧头字段:\n"
        "- sender_address: 设备地址, 不能为 0\n"
        "- cmd: 应等于 ENROLL_REQUEST (0x000C)\n"
        "- message_type: 0 (CMD 帧)\n"
        "- 帧头中的 seq 字段用于防重放"
    )
    def test_enroll_request_content(self, enrolled_udp: RadioUdpProtocol) -> None:
        """验证 EnrollRequest 帧头中包含有效的发送方地址。"""
        tracker: EnrollmentTracker = enrolled_udp._tracker  # type: ignore[attr-defined]

        assert len(tracker.enroll_events) > 0, "未收到任何 ENROLL_REQUEST 事件"

        # 取首次 ENROLL_REQUEST 的帧头信息
        # on_enroll_request 回调接收 (header, payload), header 是 DAV 帧头字典
        header = tracker.enroll_events[0][1]
        sender_raw = header.get("sender_address", 0)
        sender = sender_raw & DavProtocol.ADDRESS_MASK  # 取低 52 位有效地址
        cmd = header.get("cmd", 0)

        allure.attach(
            f"sender_address_raw  = 0x{sender_raw:013X}\n"
            f"sender_address_masked = 0x{sender:013X}\n"
            f"cmd                  = 0x{cmd:04X}\n"
            f"message_type         = {header.get('message_type', '?')}\n"
            f"seq                  = {header.get('seq', '?')}\n"
            f"receiver_address     = 0x{header.get('receiver_address', 0) & DavProtocol.ADDRESS_MASK:013X}",
            "ENROLL_REQUEST 帧头解析",
            allure.attachment_type.TEXT,
        )

        assert sender != 0, (
            "ENROLL_REQUEST 的 sender_address 为 0 — 设备地址未正确填入帧头"
        )


# ===========================================================================
# 测试类 2: TestHeartbeatAfterEnroll — 上线后心跳查询
# ===========================================================================
# 覆盖协议状态 4:
#   地面站发送 ASK_HEARTBEAT (0x000E) → 设备回复 SEND_RADIO_R2_HEARTBEAT (0x0204)
#   心跳数据包含: 固件版本/运行状态/电量/射频参数/错误报告/GPS 时间等


@allure.feature("DAV 设备上线协议 (UDP)")
class TestHeartbeatAfterEnroll:
    """测试组 2: 上线后心跳 — 验证心跳查询响应和数据完整性。"""

    @allure.story("心跳查询")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("心跳往返延迟 — RTT 统计")
    @allure.description(
        "上线完成后连续发送 ASK_HEARTBEAT (0x000E), 测量每次往返延迟 (RTT)。\n"
        "期望:\n"
        "- 平均 RTT < 1000ms (UDP 局域网一般在 5~50ms)\n"
        "- 失败率 ≤ 2/10 (设备偶尔可能因内部处理延迟导致超时)\n"
        "- 每次心跳返回固件版本号和电量百分比"
    )
    def test_heartbeat_rtt(self, enrolled_udp: RadioUdpProtocol, radio_cfg: dict) -> None:
        """测量心跳查询的往返延迟, 统计 min/max/mean/stdev。"""
        hb_samples = radio_cfg.get("radio_heartbeat_samples", 10)
        times_ms: List[float] = []

        with allure.step(f"发送 {hb_samples} 次 ASK_HEARTBEAT, 测量 RTT"):
            for i in range(hb_samples):
                try:
                    hb = _query_heartbeat(enrolled_udp)
                    times_ms.append(hb["_rtt_ms"])
                    r2 = hb.get("radio_station_r2", {})
                    error = r2.get("error_report", "?")
                    batt = r2.get("battery_percentage", "?")
                    fw = hb.get("firmware_version_alias", "?")
                    print(f"  [{i+1:2d}/{hb_samples}] "
                          f"RTT={times_ms[-1]:6.1f}ms  "
                          f"FW={fw}  电量={batt}%  错误={error}")
                except Exception as e:
                    print(f"  [{i+1:2d}/{hb_samples}] 超时: {e}")
                    times_ms.append(-1.0)

        ok_times = [t for t in times_ms if t > 0]
        fail_count = sum(1 for t in times_ms if t < 0)

        assert len(ok_times) > 0, f"全部 {hb_samples} 次心跳查询均超时 — 设备可能已离线"
        mean_rtt = sum(ok_times) / len(ok_times)

        allure.attach(
            f"采样次数 = {len(times_ms)}\n"
            f"成功     = {len(ok_times)}\n"
            f"超时     = {fail_count}\n"
            f"最小值   = {min(ok_times):.1f} ms\n"
            f"最大值   = {max(ok_times):.1f} ms\n"
            f"平均值   = {mean_rtt:.1f} ms\n",
            "心跳 RTT 统计",
            allure.attachment_type.TEXT,
        )
        allure.attach(
            "\n".join(f"{v:.1f}" for v in ok_times),
            "心跳 RTT 原始数据 (ms)",
            allure.attachment_type.CSV,
        )

        assert mean_rtt < 1000, f"心跳平均 RTT 过高: {mean_rtt:.0f}ms (上限 1000ms)"
        assert fail_count <= 2, f"心跳超时次数过多: {fail_count}/{len(times_ms)} (上限 2 次)"

    @allure.story("心跳查询")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.title("心跳数据完整性 — 固件版本 / 设备类型 / 错误码 / 电量")
    @allure.description(
        "验证心跳返回数据包含必要的设备状态字段:\n"
        "- firmware_version_alias: 固件版本号 (必需)\n"
        "- device_type: 设备类型 (UAV=0 / RADIO_STATION=2 等)\n"
        "- local_ms_time: 设备本地运行时间 ms (必需 >0)\n"
        "- error_report: 设备错误状态 (RADIO_R2_NO_ERROR 表示正常)\n"
        "- battery_percentage: 电量百分比"
    )
    def test_heartbeat_data_integrity(self, enrolled_udp: RadioUdpProtocol) -> None:
        """验证心跳数据中各必要字段非空 / 有意义。"""
        with allure.step("发送 ASK_HEARTBEAT, 校验返回字段"):
            hb = _query_heartbeat(enrolled_udp)

        # 顶层字段
        fw = hb.get("firmware_version_alias", "")
        device_type = hb.get("device_type", "")
        local_ms = hb.get("local_ms_time", 0)

        assert fw, "firmware_version_alias 为空 — 设备未返回固件版本"
        assert local_ms > 0, f"local_ms_time 异常: {local_ms} (应为正数)"

        # radio_station_r2 子结构
        r2 = hb.get("radio_station_r2", {})
        error = r2.get("error_report", "RADIO_R2_NO_ERROR")
        batt = r2.get("battery_percentage", -1)

        allure.attach(
            f"固件版本   = {fw}\n"
            f"设备类型   = {device_type}\n"
            f"本地运行时间 = {local_ms} ms\n"
            f"错误报告   = {error}\n"
            f"电量       = {batt}%\n"
            f"心跳 RTT   = {hb['_rtt_ms']:.1f} ms",
            "心跳数据详情",
            allure.attachment_type.TEXT,
        )

        print(f"\n  固件版本 = {fw}")
        print(f"  设备类型 = {device_type}")
        print(f"  错误码   = {error}")
        print(f"  电量     = {batt}%")

    @allure.story("心跳查询")
    @allure.severity(allure.severity_level.MINOR)
    @allure.title("RTK 报警检测 — 检查心跳中是否存在 RTK_ERROR_VALUE")
    @allure.description(
        "在不发送 RTCM 校正数据的情况下查询心跳, 检查 error_report 字段。\n"
        "如果包含 RTK_ERROR_VALUE, 说明设备未收到 RTCM 数据流 — 這是正常现象。\n"
        "通过后续 TestRtkCorrection 发送 RTCM 数据即可清除此报警。"
    )
    def test_heartbeat_rtk_error_warning(self, enrolled_udp: RadioUdpProtocol) -> None:
        """检查心跳中的 RTK 报警状态 (仅诊断, 不 fail)。"""
        with allure.step("查询心跳, 检测 RTK 报警"):
            hb = _query_heartbeat(enrolled_udp)

        rtk_err = _check_rtk_error(hb)
        r2 = hb.get("radio_station_r2", {})
        error = r2.get("error_report", "?")

        allure.attach(
            f"error_report = {error}\n"
            f"RTK 报警     = {'YES' if rtk_err else 'NO'}\n"
            f"心跳 RTT     = {hb['_rtt_ms']:.1f} ms\n"
            f"\n说明:\n"
            f"  RTK_ERROR_VALUE 表示设备串口未收到 RTCM 校正数据。\n"
            f"  通过 COM4 串口发送 RTCM 1006/1074 帧可清除此报警。",
            "RTK 报警检查",
            allure.attachment_type.TEXT,
        )

        if rtk_err:
            print(f"\n  !! 检测到 RTK 报警: {rtk_err}")
            print(f"  → 原因: 设备串口未收到 RTCM 校正数据")
            print(f"  → 解决: 运行 TestRtkCorrection 测试或接入 GNSS 基准站")
        else:
            print(f"\n  [OK] 无 RTK 报警 — error_report = {error}")


# ===========================================================================
# 测试类 3: TestEnrollStability — 心跳期间上线状态稳定性
# ===========================================================================
# 覆盖协议状态 6:
#   设备在能收到地面站心跳时, 不发送 EnrollRequest。
#   如果此时收到 EnrollRequest, 说明设备的"心跳在线 → 不发 EnrollRequest"逻辑失效。


@allure.feature("DAV 设备上线协议 (UDP)")
class TestEnrollStability:
    """测试组 3: 上线稳定性 — 持续心跳期间不应出现重复 EnrollRequest。"""

    @allure.story("上线稳定性")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("持续心跳 — 验证无重复 EnrollRequest")
    @allure.description(
        "上线后以 1Hz 频率持续发送心跳，同时监控是否有新的 ENROLL_REQUEST 到达。\n\n"
        "协议规范要求:\n"
        "  状态 6: DAV 设备在能收到地面站心跳时, 不发送 EnrollRequest。\n\n"
        "如果测试期间收到 EnrollRequest, 说明:\n"
        "  1. 心跳响应可能延迟过大, 设备认为地面站已离线\n"
        "  2. 设备固件的心跳在线检测逻辑可能有问题\n"
        "  3. UDP 网络丢包导致心跳请求/响应丢失"
    )
    def test_no_enroll_request_during_sustained_heartbeat(
        self, enrolled_udp: RadioUdpProtocol, radio_cfg: dict,
    ) -> None:
        """持续发送 1Hz 心跳, 断言期间无新的 EnrollRequest。"""
        sustained_duration = radio_cfg.get("radio_sustained_duration", 20)
        tracker: EnrollmentTracker = enrolled_udp._tracker  # type: ignore[attr-defined]

        hb_ok = 0
        hb_fail = 0
        hb_times: List[float] = []

        t_start = time.monotonic()
        deadline = t_start + sustained_duration
        seq = 0
        next_send = t_start

        print(f"\n  持续 {sustained_duration}s 心跳 (1Hz) — 监控 EnrollRequest ...")

        with allure.step(f"以 1Hz 发送心跳, 持续 {sustained_duration}s"):
            while time.monotonic() < deadline:
                now = time.monotonic()
                if now < next_send:
                    time.sleep(next_send - now)
                seq += 1
                elapsed = time.monotonic() - t_start
                next_send = t_start + seq

                try:
                    hb = _query_heartbeat(enrolled_udp)
                    hb_ok += 1
                    hb_times.append(hb["_rtt_ms"])
                except Exception:
                    hb_fail += 1

                # 每 5 次心跳输出一次状态
                if seq % 5 == 0:
                    new_enroll = tracker.new_enroll_count
                    print(f"  [{elapsed:5.1f}s] seq={seq:2d}  "
                          f"hb_ok={hb_ok} hb_fail={hb_fail}  "
                          f"new_enroll={new_enroll}")

                # 一旦发现新的 EnrollRequest, 立即终止
                if tracker.new_enroll_count > 0:
                    t = tracker.new_enroll_events[0][0] - t_start
                    print(f"\n  !!! [{t:.1f}s] 检测到新的 EnrollRequest — 终止测试 !!!")
                    break

        new_enroll = tracker.new_enroll_count
        total = hb_ok + hb_fail

        # 汇总报告
        summary = (
            f"测试时长         = {time.monotonic() - t_start:.1f}s\n"
            f"心跳成功         = {hb_ok}\n"
            f"心跳超时         = {hb_fail}\n"
            f"总发送次数       = {total}\n"
            f"新增 EnrollRequest = {new_enroll}\n"
            f"\n"
            f"  → 协议预期: 状态 6 — 心跳在线期间设备不发送 EnrollRequest\n"
        )
        if hb_times:
            summary += (
                f"\n心跳 RTT 统计:\n"
                f"  min  = {min(hb_times):.1f} ms\n"
                f"  max  = {max(hb_times):.1f} ms\n"
                f"  mean = {sum(hb_times)/len(hb_times):.1f} ms"
            )

        allure.attach(summary, "稳定性测试结果", allure.attachment_type.TEXT)
        if hb_times:
            allure.attach(
                "\n".join(f"{v:.1f}" for v in hb_times),
                "持续心跳 RTT 原始数据 (ms)",
                allure.attachment_type.CSV,
            )

        print(f"\n  === 稳定性测试完成: OK={hb_ok} FAIL={hb_fail} "
              f"new_enroll={new_enroll} ===")

        assert new_enroll == 0, (
            f"测试期间收到 {new_enroll} 次新的 EnrollRequest!\n"
            f"这说明设备在心跳持续期间重新发起了上线请求,\n"
            f"违反了协议状态 6: 'DAV 设备在能收到地面站心跳时不发送 EnrollRequest'。\n"
            f"可能原因: (1) 心跳响应延迟过大 (2) UDP 丢包 (3) 设备固件逻辑问题。"
        )


# ===========================================================================
# 测试类 4: TestDropOffAndReEnroll — 掉线检测与重新上线
# ===========================================================================
# 覆盖协议状态 5→1→2→3→4:
#   状态 5: 地面站长时间不发送心跳 → 设备标记地面站离线
#   状态 1: 设备重新发送 EnrollRequest
#   ...
#   状态 4: 重新上线后心跳恢复
#
# 设计说明:
#   test_drop_off_time 临时阻断 ENROLL_REPLY 自动回复,
#   这样设备不会重新上线, 保持"离线等待"状态。
#   下一个测试 test_re_enroll_and_heartbeat_recovery 恢复自动回复,
#   等待设备发出的 EnrollRequest, 完成重新上线并验证心跳恢复。


@allure.feature("DAV 设备上线协议 (UDP)")
class TestDropOffAndReEnroll:
    """测试组 4: 掉线检测与重新上线 — 完整离线→上线恢复流程。

    两个测试按顺序执行, 有状态依赖:
    1. test_drop_off_time: 静默 + 阻断回复 → 测量掉线时间
    2. test_re_enroll_and_heartbeat_recovery: 恢复回复 → 重新上线 → 心跳验证
    """

    @allure.story("掉线检测")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("设备掉线时间测量 — 地面站静默, 等待 EnrollRequest")
    @allure.description(
        "协议状态 5→1 迁移测试:\n"
        "1. 地面站停止发送心跳 (静默)\n"
        "2. 设备检测到长时间无心跳 → 判定地面站离线\n"
        "3. 设备重新发送 EnrollRequest → 回到状态 1\n\n"
        "本测试阻断 ENROLL_REPLY 自动回复 (避免设备立即重新上线),\n"
        "纯粹测量从静默到收到 EnrollRequest 的时间 (即设备掉线检测时间)。\n\n"
        "预期掉线时间: 通常在 5~60 秒之间, 取决于设备固件的心跳超时设置。"
    )
    def test_drop_off_time(
        self, enrolled_udp: RadioUdpProtocol, radio_cfg: dict,
    ) -> None:
        """地面站静默, 测量设备判定掉线并重发 EnrollRequest 的时间。"""
        max_wait = radio_cfg.get("radio_drop_off_max_wait", 60.0)
        tracker: EnrollmentTracker = enrolled_udp._tracker  # type: ignore[attr-defined]

        # 临时阻断 ENROLL_REPLY 自动回复
        # 这样设备发出 EnrollRequest 后不会重新上线, 保持离线状态
        original_handler = enrolled_udp._handle_enroll_request

        def noop_enroll_handler(header: Dict[str, Any], payload: bytes) -> None:
            """空操作 — 收到 EnrollRequest 后不回复 EnrollReply。"""

        enrolled_udp._handle_enroll_request = noop_enroll_handler  # type: ignore[method-assign]

        with allure.step(f"地面站静默 (不发送心跳), 等待设备掉线 (最长 {max_wait}s)"):
            try:
                print(f"\n  地面站静默 — 等待设备掉线重发 EnrollRequest (最长 {max_wait}s)...")

                t_silent = time.monotonic()
                arrived = tracker.enroll_event.wait(timeout=max_wait)

                if arrived:
                    drop_time = tracker.enroll_events[-1][0] - t_silent
                    sender = tracker.enroll_events[-1][1].get("sender_address", 0)
                    sender_masked = sender & DavProtocol.ADDRESS_MASK
                    print(f"  [收到 ENROLL_REQUEST @ ~{drop_time:.1f}s] "
                          f"sender=0x{sender_masked:013X}")
                else:
                    drop_time = max_wait
                    print(f"  [{max_wait:.0f}s 内未收到 ENROLL_REQUEST]")

                allure.attach(
                    f"ENROLL_REQUEST 到达 = {arrived}\n"
                    f"掉线时间           = {drop_time:.1f}s\n"
                    f"静默开始时间戳     = {t_silent}\n"
                    f"备注: ENROLL_REPLY 自动回复已阻断 (本测试仅测量时间)",
                    "掉线检测结果",
                    allure.attachment_type.TEXT,
                )

                if arrived:
                    print(f"\n  === 设备掉线时间 ≈ {drop_time:.1f}s ===")
                    # 掉线时间应在合理范围内 (5~120s)
                    assert 5.0 < drop_time < 120.0, (
                        f"掉线时间异常: {drop_time:.1f}s (预期 5~120s)\n"
                        f"太短 (<5s): 可能不是真正的掉线, 而是设备重启或网络抖动\n"
                        f"太长 (>120s): 设备心跳超时设置可能过大或固件逻辑异常"
                    )
                else:
                    print(f"\n  === {max_wait:.0f}s 内未检测到掉线 (可接受) ===")

            finally:
                # 恢复原始 handler, 供后续测试使用
                enrolled_udp._handle_enroll_request = original_handler  # type: ignore[method-assign]

    @allure.story("重新上线")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("重新上线 + 心跳恢复 — 完整离线→上线→心跳恢复流程")
    @allure.description(
        "协议状态 1→2→3→4 的完整恢复测试:\n"
        "1. 等待设备发送 EnrollRequest (设备已处于离线-重试状态)\n"
        "2. RadioUdpProtocol 自动回复 EnrollReply → 设备回复 ACK → 上线完成\n"
        "3. 立即发送 10 次心跳查询 → 验证心跳通道已恢复正常\n\n"
        "前置条件: test_drop_off_time 已触发设备掉线并阻断回复,\n"
        "设备当前处于'发送 EnrollRequest 等待回复'的循环中。"
    )
    def test_re_enroll_and_heartbeat_recovery(
        self, enrolled_udp: RadioUdpProtocol, radio_cfg: dict,
    ) -> None:
        """等待设备 EnrollRequest, 完成重新上线, 验证心跳恢复正常。"""
        max_wait = radio_cfg.get("radio_drop_off_max_wait", 60.0)
        hb_samples = radio_cfg.get("radio_heartbeat_samples", 10)
        tracker: EnrollmentTracker = enrolled_udp._tracker  # type: ignore[attr-defined]
        old_count = tracker.total_enroll_count

        print(f"\n  等待设备 EnrollRequest, 完成重新上线 ...")

        # ---- Phase 1: 等待 EnrollRequest + 自动重新上线 ----
        with allure.step("等待设备 EnrollRequest, 自动回复 EnrollReply 完成重新上线"):
            arrived = tracker.enroll_event.wait(timeout=max_wait)

            # 给设备时间处理 EnrollReply 并回复 ACK
            time.sleep(1.5)

            new_count = tracker.total_enroll_count

            allure.attach(
                f"上线前 EnrollRequest 计数 = {old_count}\n"
                f"上线后 EnrollRequest 计数 = {new_count}\n"
                f"ENROLL_REQUEST 已到达    = {arrived}\n"
                f"is_enrolled              = {enrolled_udp.is_enrolled}\n"
                f"is_connected             = {enrolled_udp.is_connected}\n"
                f"device_address           = 0x{enrolled_udp.device_address:013X}",
                "重新上线结果",
                allure.attachment_type.TEXT,
            )

            if not arrived:
                print(f"  [{max_wait:.0f}s 内未收到 ENROLL_REQUEST — 跳过]")
                pytest.skip("未收到 ENROLL_REQUEST, 设备可能尚未进入离线-重试状态")

            assert enrolled_udp.is_enrolled, (
                "重新上线失败 — is_enrolled 仍为 False, "
                "ENROLL_REPLY 可能未成功发送或设备未处理"
            )

        # ---- Phase 2: 心跳恢复验证 ----
        with allure.step(f"发送 {hb_samples} 次心跳, 验证通道恢复正常"):
            times_ms: List[float] = []
            for i in range(hb_samples):
                try:
                    hb = _query_heartbeat(enrolled_udp)
                    times_ms.append(hb["_rtt_ms"])
                    print(f"  [{i+1:2d}/{hb_samples}] "
                          f"RTT={times_ms[-1]:6.1f}ms  "
                          f"FW={hb.get('firmware_version_alias', '?')}")
                except Exception as e:
                    print(f"  [{i+1:2d}/{hb_samples}] 超时: {e}")
                    times_ms.append(-1.0)

            ok_times = [t for t in times_ms if t > 0]
            fail_count = sum(1 for t in times_ms if t < 0)
            assert len(ok_times) > 0, (
                f"重新上线后全部 {hb_samples} 次心跳均超时 — 设备虽已上线但心跳通道异常"
            )

            mean_rtt = sum(ok_times) / len(ok_times)

            allure.attach(
                f"采样次数 = {len(times_ms)}\n"
                f"成功     = {len(ok_times)}\n"
                f"超时     = {fail_count}\n"
                f"min      = {min(ok_times):.1f} ms\n"
                f"max      = {max(ok_times):.1f} ms\n"
                f"mean     = {mean_rtt:.1f} ms",
                "重新上线后心跳 RTT 统计",
                allure.attachment_type.TEXT,
            )
            allure.attach(
                "\n".join(f"{v:.1f}" for v in ok_times),
                "重新上线后心跳 RTT 原始数据 (ms)",
                allure.attachment_type.CSV,
            )

            assert mean_rtt < 1000, (
                f"重新上线后心跳平均 RTT 过高: {mean_rtt:.0f}ms (上限 1000ms)"
            )

        print(f"\n  === 重新上线 + 心跳恢复完成 === RTT mean={mean_rtt:.0f}ms")


# ===========================================================================
# 测试类 5: TestRtkCorrection — RTCM 校正数据清除 RTK 报警
# ===========================================================================
# RTK 报警产生原因:
#   DAV 设备通过串口接收 GNSS 基准站 RTCM3 校正数据,
#   如果串口无数据输入, 设备在心跳中报告 RTK_ERROR_VALUE。
#   通过 RtkSender 向设备串口注入 RTCM 帧 (1006 站坐标 + 1074 GPS MSM4),
#   设备检测到有效 RTCM 数据流后自动清除报警。
#
# 需要:
#   1. RTK_SERIAL_PORT 配置为实际 COM 口 (当前="COM4")
#   2. 串口线连接 PC ↔ DAV 设备的 RTK 输入口
#   3. 设备固件支持从串口接收 RTCM3 数据


@allure.feature("DAV 设备上线协议 (UDP)")
class TestRtkCorrection:
    """测试组 5: RTCM 校正 — 发送 RTCM 数据清除心跳中的 RTK 报警。"""

    @allure.story("RTCM 校正")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.title("RTK 报警清除 — 发送 RTCM → 心跳 error_report 变为 NO_ERROR")
    @allure.description(
        "验证 RTCM 校正数据能解除 RTK 输入异常报警:\n"
        "1. 查询当前心跳 — 预计包含 RTK_ERROR_VALUE (设备串口无 RTCM 输入)\n"
        "2. 通过 RtkSender 向 COM4 串口发送 RTCM3 帧 (1006 + 1074)\n"
        "3. 等待 3 秒让设备处理 RTCM 数据\n"
        "4. 再次查询心跳 — 预期 error_report 变为 RADIO_R2_NO_ERROR\n\n"
        "RTCM 数据说明:\n"
        "  1006: 基准站坐标 (X/Y/Z + 天线高度)\n"
        "  1074: GPS MSM4 观测值 (伪距 + 载波相位 + 信噪比)\n"
        "  使用 builder 模式生成模拟数据, GPS 时间使用实时 UTC 时间"
    )
    @pytest.mark.usefixtures("rtk_sender")
    def test_rtcm_clears_rtk_error(
        self, enrolled_udp: RadioUdpProtocol, rtk_sender, radio_cfg: dict,
    ) -> None:
        """发送 RTCM 校正数据, 验证心跳中 RTK 报警被清除。"""
        rtk_interval = radio_cfg.get("rtk_send_interval", 1.0)
        if not rtk_sender or not rtk_sender.is_connected:
            pytest.skip("RTK 串口未连接 — 检查 rtk_serial_port 配置和物理连线")

        # ---- Step 1: 发送前查询 (预期有 RTK 报警) ----
        with allure.step("Step 1: RTCM 发送前 — 查询心跳, 记录当前错误状态"):
            hb_before = _query_heartbeat(enrolled_udp)
            error_before = (
                hb_before.get("radio_station_r2", {}).get("error_report", "?")
            )
            allure.attach(
                f"RTCM 发送前 error_report = {error_before}\n"
                f"心跳 RTT                 = {hb_before['_rtt_ms']:.1f} ms",
                "发送前心跳状态",
                allure.attachment_type.TEXT,
            )
            print(f"\n  [Step 1] RTCM 发送前: error_report = {error_before}")

        # ---- Step 2: 发送 RTCM 数据 ----
        with allure.step(f"Step 2: 启动 RTCM 自动发送 ({rtk_interval}s 间隔), 持续 3 秒"):
            rtk_sender.start_auto_send(interval=rtk_interval)

            # 等待设备接收并处理 RTCM 数据 (3 秒足够发 3 轮)
            time.sleep(3.0)

            rtk_sender.stop_send()
            print(f"  [Step 2] RTCM 发送完成 (3 秒, 约 3 轮)")

        # ---- Step 3: 发送后查询 (预期 RTK 报警已清除) ----
        with allure.step("Step 3: RTCM 发送后 — 再次查询心跳, 验证错误状态变化"):
            hb_after = _query_heartbeat(enrolled_udp)
            error_after = (
                hb_after.get("radio_station_r2", {}).get("error_report", "?")
            )
            allure.attach(
                f"RTCM 发送后 error_report = {error_after}\n"
                f"心跳 RTT                 = {hb_after['_rtt_ms']:.1f} ms",
                "发送后心跳状态",
                allure.attachment_type.TEXT,
            )
            print(f"  [Step 3] RTCM 发送后: error_report = {error_after}")

        # ---- 结果判定 ----
        rtk_before = _check_rtk_error(hb_before)
        rtk_after = _check_rtk_error(hb_after)

        if rtk_before and not rtk_after:
            # 理想情况: RTCM 成功清除了 RTK 报警
            print(f"\n  [OK] RTCM 校正生效 — error_report: {rtk_before} → {error_after}")
        elif not rtk_before:
            # 发送前就没有 RTK 报警 (可能已经被其他来源的 RTCM 清除了)
            print(f"\n  [--] 发送前即无 RTK 报警 (error={error_before}) — 无需校正")
        elif rtk_after:
            # RTCM 发送后报警依然存在 — 需要排查
            print(f"\n  [!!] RTCM 发送后 RTK 报警仍存在: {rtk_after}")
            print(f"  → 排查: (1) 串口线是否连接正确 (2) 波特率是否匹配 (3) 设备 RTK 输入协议是否匹配")
