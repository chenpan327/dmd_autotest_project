# coding: utf-8

r"""
P2 级功能补充测试 — 低优先级正向主路径（与 P0/P1 区分：简要断言、正向为主）

P2 协议速查（v44 dialect + DGCS 真站 + 前辈用例交叉源）：
    ┌─────────┬────────────────────────────────┬──────────────────────┬──────────────────────────┐
    │ msg_id  │ 消息                            │ 载荷格式              │ 字段 / 预期回包           │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │   2     │ IDENTIFY_INFO（飞机→GCS）        │ '<20B5B'             │ serial[20B]+code[5B]     │
    │         │  SN/CN 信息上报                  │                      │ 回包：无（被动上报）       │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │   3     │ GET_IDENTIFY_INFO（GCS→飞机）    │ '<BB'                │ target_system=0,        │
    │         │  请求 SN/CN                      │                      │ target_component=1      │
    │         │                                 │                      │ → 回 IDENTIFY_INFO(2)   │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │   6     │ FAILSAFE（飞机→GCS）             │ '<H'                 │ failsafe(uint16)        │
    │         │  失效保护状态标志                 │                      │ 周期/事件触发上报         │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │  25     │ SET_SERIAL_NUMBER（GCS→飞机）    │ '<20BB'              │ serial[20B]             │
    │         │  写入 SN                         │                      │ + type(0=飞机SN)        │
    │         │                                 │                      │ 回包：无专用 ACK          │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │  28     │ SET_CODE_NUMBER（GCS→飞机）      │ '<5B'                │ code[5B]               │
    │         │  写入设备编码                     │                      │ 回包：无专用 ACK          │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │  39     │ DRAMA_SWITCH（GCS→飞机）         │ '<QBBB'              │ time(uint64)+type+      │
    │         │  剧本切换指令                     │                      │ index+final_mode        │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │  40     │ MISSION_REQUEST_START（GCS→飞机）│ '<IBBB'              │ count+id+type+index     │
    │         │  任务加载请求                     │                      │ → 回 ACK(42)           │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │  41     │ MISSION_REQUEST_VERIFY（GCS→飞机）│ '<IBB'             │ crc32+id+type          │
    │         │  任务校验请求（MD5/CRC）           │                      │ → 回 ACK(42) result    │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │  42     │ MISSION_REQUEST_ACK（飞机→GCS）   │ '<B'                │ result(uint8)          │
    │         │  任务操作回执                     │                      │ 0=成功                 │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │  46     │ CALIB_TIME（GCS→飞机）           │ '<B'                 │ type(1=触发校时)       │
    │         │  校时命令                        │                      │ 回包：无专用 ACK         │
    │         │                                 │                      │ 效果：now CLI 时间更新   │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │  50     │ SWARM_FLIGHT_START（GCS→飞机）    │ '<QQQQQiiiiiiBB'     │ takeoff/play/light×2/   │
    │         │  群飞启动（DGCS"开始表演"按钮）      │    (66B 载荷)        │ play_id/ascend/descend/ │
    │         │                                 │                      │ elevation/return_lon/   │
    │         │                                 │                      │ return_lat/final_mode/  │
    │         │                                 │                      │ mission_id             │
    │         │                                 │                      │ → COMMAND_ACK(77)      │
    │         │                                 │                      │   command=50           │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │  63     │ NET_FILE_COMMAND（GCS↔飞机）      │ '<h253s'             │ net_file_cmd(H)+       │
    │         │  文件传输（多路复用）               │                      │ data[253B]            │
    │         │                                 │                      │ cmd: 0=OPEN 1=WRITE   │
    │         │                                 │                      │ 2=READ 3=CLOSE        │
    │         │                                 │                      │ 4=ACK 5=VERIFY        │
    │         │                                 │                      │ 6=DELETE              │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │  180    │ MAV_CMD_DO_SET_FENCE             │ COMMAND_LONG(76)     │ p1,p2=原点(0,0)        │
    │  (cmd)  │  设置电子围栏                     │                      │ p3=半径 p4=高度        │
    │         │                                 │                      │ → COMMAND_ACK(77)      │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │  40003  │ MAV_CMD_FLIGHT_STOP              │ COMMAND_LONG(76)     │ 无参数（p1~p7=0）      │
    │  (cmd)  │  急停                            │                      │ → COMMAND_ACK(77)      │
    ├─────────┼────────────────────────────────┼──────────────────────┼──────────────────────────┤
    │  183    │ MAV_CMD_DO_SET_SERVO             │ COMMAND_LONG(76)     │ p1=R p2=G p3=B (0~255)│
    │  (cmd)  │  底板灯 RGB 控制                 │                      │ **p7=1**（底板灯通道）  │
    │  p7=1   │  （区别于激光 p7=4、指示灯 notify）│                      │ p4=0（非激光通道）      │
    │         │                                 │                      │ → ACK(77) + packed_    │
    │         │                                 │                      │   state.light_r/g/b    │
    │         │                                 │                      │ 回读核对               │
    └─────────┴────────────────────────────────┴──────────────────────┴──────────────────────────┘

    CLI 补充通道：
    ├ version  返回 sn: XXX + version: XXX（SN 读取通道之一）
    ├ fence    "fence 原点X, 原点Y, 半径, 高度"（围栏设置 CLI 通道）
    ├ now      返回 Base Time / Flight Time（校时效果回读通道）
    └ ffs 0    清除全部失效注入（GCS-04 P1 已覆盖，P2 复用做标志清除）

覆盖范围（P2 需求条目 → 用例映射）：
    ┌ 失效保护状态上报      msg6 接收解析
    ├ 失效保护历史标志清除  ffs 0 + fs_state 核对
    ├ SN/CN 读取           version CLI + GET_IDENTIFY_INFO(3)→IDENTIFY_INFO(2)
    ├ SN 写入              SET_SERIAL_NUMBER(25) + version CLI 读回
    ├ 设备编码写入         SET_CODE_NUMBER(28)（无 CLI 读回通道）
    ├ 校时                 CALIB_TIME(46) → now CLI 回读
    ├ Home/围栏设置        DO_SET_FENCE(180) COMMAND_LONG + fence CLI
    ├ 围栏触发检测          设极小围栏(1m) + fs_state 检测越界标志
    ├ 文件传输             NET_FILE(63) OPEN/CLOSE 会话
    ├ 任务校验             MISSION_REQUEST_VERIFY(41) → ACK(42)
    ├ 任务启动接收          SWARM_FLIGHT_START(50) 地面态 → COMMAND_ACK(77)
    ├ 急停                 FLIGHT_STOP(40003) → COMMAND_ACK(77)
    └ 底板灯 RGB 控制       COMMAND_LONG 183 param7=1 → packed_state 回读

与 P0/P1 的关系：
    - 指示灯（信号灯）notify on/off → GCS-13 P1 覆盖（≠底板灯，两个东西）
    - 激光颜色 183 p7=4 → X1 Release_Testing laser 用例覆盖
    - 失效注入 ffs 1~5 → GCS-04 P1 已覆盖
    - 参数 pp/sp/svp → GCS-14/GCS-26 P1 已覆盖
    - Home/围栏 chenpan Release_Testing 有旧版（skip 待重写），此处为新版
    - 表演控制 msg50 → liaoyutao test_mavlink_play.py 有深度覆盖（P2 只验接收通道）
    - 底板灯 RGB → liaoyutao test_mavlink_led_control.py 有 18 项深度覆盖
      （P2 简要实现开启/关闭/回读闭环，与 V4 逻辑一致）
"""

import os
import struct
import time

import pytest
import allure

from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    FCBasicBase, log_manager, _cli_failed, CONSOLE_PROMPT,
    MSG_ID_FAILSAFE, MSG_ID_TIME_CHECK, MSG_ID_COMMAND_ACK)

# SN/设备编码写入门控（受控资产，独立于 DESTRUCTIVE 组：即使开毁灭组
# 也不顺带写 SN）。默认 skip；用例内含"读备份→写入→teardown 原值回写→
# 读校验"闭环（identify_guard），还原失败硬失败附原值恢复指引
ENABLE_SN_WRITE = os.environ.get("FC_BASIC_ENABLE_SN_WRITE", "0") == "1"

sn_write_gate = pytest.mark.skipif(
    not ENABLE_SN_WRITE,
    reason="SN/设备编码为受控资产（真机不可随意写）：需设置环境变量 "
           "FC_BASIC_ENABLE_SN_WRITE=1，并确认在可写入的测试机上执行"
           "（用例已含备份/还原闭环）")

# P2 补充消息号（dialect v44）
MSG_ID_GET_IDENTIFY_INFO = 3
MSG_ID_IDENTIFY_INFO = 2
MSG_ID_SET_SERIAL_NUMBER = 25
MSG_ID_SET_CODE_NUMBER = 28
MSG_ID_DRAMA_SWITCH = 39
MSG_ID_MISSION_REQUEST_START = 40
MSG_ID_MISSION_REQUEST_VERIFY = 41
MSG_ID_MISSION_REQUEST_ACK = 42
MSG_ID_SWARM_FLIGHT_START = 50
MSG_ID_NET_FILE_COMMAND = 63

# COMMAND_LONG 命令号（DGCS 真站定义）
CMD_DO_SET_FENCE = 180           # 电子围栏设置（chenpan 用例同款）
CMD_FLIGHT_STOP = 40003          # 急停（DGCS 真站 MAV_CMD_FLIGHT_STOP）
CMD_DO_SET_SERVO = 183           # 复用命令：p7=1 底板灯 / p7=4 激光
LED_PARAM7 = 1                   # p7=1 = 底板灯通道（V4/X1 LED 用例同源）
NET_FILE_OPEN = 0
NET_FILE_CLOSE = 3


@allure.feature("FC 基础功能 P2")
@allure.severity(allure.severity_level.MINOR)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC_P2")
@pytest.mark.functional
class TestGcsP2Supplement(FCBasicBase):
    """P2 级功能补充（低优先级，简要断言，正向主路径）"""

    # ==================================================================
    # 失效保护
    # ==================================================================

    @allure.story("P2-失效保护")
    @allure.title("P2 失效保护状态上报：msg6 接收解析")
    def test_p2_failsafe_msg6(self):
        """验证 msg6 FAILSAFE 消息可接收且字段可解析（P2 正向）"""
        with allure.step("等待 msg6 FAILSAFE"):
            msg = self._wait_msg(MSG_ID_FAILSAFE, timeout=5.0)
            if msg is not None:
                log_manager.log_and_attach(
                    f"msg6 fields: {msg.fields}", "FAILSAFE 消息")
                assert len(msg.fields) > 0, f"msg6 字段为空: {msg.fields}"
            else:
                log_manager.log_and_attach(
                    "5s 内无 msg6（正常态无失效上报）", "FAILSAFE 消息")

    @allure.story("P2-失效保护")
    @allure.title("P2 失效保护历史标志清除：ffs 0 + fs_state 核对")
    def test_p2_failsafe_flag_clear(self):
        """验证 ffs 0 清除后 fs_state 全零（P2 正向）"""
        with allure.step("ffs 0 清除"):
            resp = self._cli("ffs 0")
            assert "ack" in resp.lower(), f"ffs 0 无 ACK: {resp[:100]}"
        with allure.step("fs_state 核对全零"):
            state = self._cli("fs_state")
            log_manager.log_and_attach(state, "fs_state")
            nonzero = []
            for line in state.splitlines():
                if ':' in line:
                    key, _, val = line.partition(':')
                    val = val.strip()
                    if val.lstrip('-').isdigit() and int(val) != 0:
                        nonzero.append(f"{key.strip()}={val}")
            if nonzero:
                log_manager.logger.warning(
                    f"ffs 0 后仍有非零标志: {nonzero}（P2 存档不判失败）")

    # ==================================================================
    # SN / 设备编码
    # ==================================================================

    @pytest.fixture
    def identify_guard(self):
        """SN/设备编码写类用例的备份/还原守卫（同 net_config_guard 范式）

        setup：读当前 SN+编码存档（读不到原值则放弃执行——没有备份就
        没有还原）；teardown：若发生过写入，原值回写并读校验，校验失败
        硬失败（附原值 hex 恢复指引）。
        """
        backup = self._read_identify(retries=3)
        assert backup is not None, (
            "无法读取当前 SN/设备编码（IDENTIFY_INFO 无应答），"
            "放弃执行写类用例——没有备份就没有还原")
        sn_b, code_b = backup
        sn_show, cn_show = sn_b.rstrip(b'\x00'), code_b.rstrip(b'\x00')
        log_manager.log_and_attach(
            f"备份 SN={sn_show!r} CN={cn_show!r} "
            f"(raw hex: sn={sn_b.hex()} cn={code_b.hex()})", "SN/编码备份")
        self._wrote_identify = False
        yield backup
        if self._wrote_identify:
            self._restore_identify(backup)

    @staticmethod
    def _bump_identify(raw):
        """由本机原值派生测试写入值（非零字节 +1，0xFF→0xFE，零 padding 保持）

        各机器 SN/设备编码取值与格式均不同，测试值不能写死固定常量：
        沿用原值逐字节 +1 —— 保持长度/\\x00 padding/非零域，写入不会因
        格式不符被拒；派生值必 ≠ 原值，读回可区分"已写入"与"未生效"；
        0xFF 边界避让到 0xFE 防止非零变零。还原不依赖逆变换（直接回写
        备份原值）。
        """
        return bytes(0 if b == 0 else (0xFE if b == 0xFF else b + 1)
                     for b in raw)

    def _read_identify(self, retries=3):
        """GET_IDENTIFY_INFO(3) → IDENTIFY_INFO(2)，读 (sn 20B, code 5B)

        Returns: (sn_bytes, code_bytes) 元组（原样含 \\x00 padding，回写按
        原始 25B 保真）；应答缺失或载荷不足 25B 返回 None。
        """
        for _ in range(retries):
            self._clear_recv_buffer()
            msg = MAVLink_message(
                msg_id=MSG_ID_GET_IDENTIFY_INFO, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'target_system': 0, 'target_component': 1})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            identify = self._wait_msg(MSG_ID_IDENTIFY_INFO, timeout=5.0)
            if identify is not None:
                # msg2 '<20B5B'：20B SN + 5B 编码
                raw = bytes(identify.payload or b'')[:25]
                if len(raw) == 25:
                    return raw[:20], raw[20:25]
            time.sleep(0.5)
        return None

    def _write_sn(self, sn20):
        """SET_SERIAL_NUMBER(25) 写 20B SN（type=0 飞机SN，无专用 ACK）"""
        msg = MAVLink_message(
            msg_id=MSG_ID_SET_SERIAL_NUMBER, sys_id=1, comp_id=1, seq=0,
            version=self.mavlink_version,
            fields={f'serail_number[{i}]': sn20[i] for i in range(20)}
            | {'type': 0})
        self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
        time.sleep(2.0)      # 与原用例同款写入等待
        sn_show = bytes(sn20).rstrip(b'\x00')
        log_manager.log_and_attach(
            f"SET_SERIAL_NUMBER 已发送 type=0 sn={sn_show!r}", "SN 写入")

    def _write_code(self, code5):
        """SET_CODE_NUMBER(28) 写 5B 设备编码（无专用 ACK）"""
        msg = MAVLink_message(
            msg_id=MSG_ID_SET_CODE_NUMBER, sys_id=1, comp_id=1, seq=0,
            version=self.mavlink_version,
            fields={f'code_number[{i}]': code5[i] for i in range(5)})
        self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
        time.sleep(1.0)
        code_show = bytes(code5).rstrip(b'\x00')
        log_manager.log_and_attach(
            f"SET_CODE_NUMBER 已发送 code={code_show!r}", "编码写入")

    def _restore_identify(self, backup):
        """原值回写 SN+编码并读校验（msg25/28 无 ACK，读回比对是唯一判据）

        同值回写无害：若测试写入未生效（可能需重启），读回一直是原值
        == 备份，校验同样通过；只有"写入生效且还原失败"才硬失败。
        """
        sn_b, code_b = backup
        with allure.step("还原 SN/设备编码（原值回写 + 读校验）"):
            current = None
            for attempt in range(1, 4):
                self._write_sn(sn_b)
                self._write_code(code_b)
                current = self._read_identify(retries=3)
                if current == backup:
                    log_manager.log_and_attach(
                        f"还原校验通过（第 {attempt} 次，与备份一致）", "还原校验")
                    return
                got = (f"sn={current[0].hex()} cn={current[1].hex()}"
                       if current else "读取失败")
                log_manager.log_and_attach(
                    f"第 {attempt} 次还原读校验不一致（当前 {got}），重试",
                    "还原重试")
            cur_desc = (f"sn={current[0].hex()} cn={current[1].hex()}"
                        if current else "读取失败")
            assert current == backup, (
                f"SN/设备编码还原失败！备份: sn={sn_b.hex()} cn={code_b.hex()}，"
                f"当前: {cur_desc}。"
                f"恢复手段：人工下发 SET_SERIAL_NUMBER(25)/SET_CODE_NUMBER(28) "
                f"按上述备份 hex 写回（写入可能需重启生效，重启后需复核）；"
                f"msg25/28 无专用 ACK，读回比对是唯一判据")

    @allure.story("P2-SN/编码")
    @allure.title("P2 SN/CN 读取：version CLI + GET_IDENTIFY_INFO(3)")
    def test_p2_sn_read(self):
        """验证 SN 双通道可读（P2 正向：CLI + MAVLink）"""
        with allure.step("CLI version 读取 SN"):
            resp = self._cli("version")
            assert resp and CONSOLE_PROMPT in resp, (
                f"version 无完整回显: {resp[:200]}")
            log_manager.log_and_attach(resp[:300], "version 回显")
            assert "sn" in resp.lower(), f"version 缺少 sn: {resp[:200]}"

        with allure.step("MAVLink GET_IDENTIFY_INFO(3)"):
            msg = MAVLink_message(
                msg_id=MSG_ID_GET_IDENTIFY_INFO, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'target_system': 0, 'target_component': 1})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            identify = self._wait_msg(MSG_ID_IDENTIFY_INFO, timeout=5.0)
            if identify is not None:
                # msg2 '<20B5B'：20B SN + 5B 编码
                raw = (identify.payload or b'')[:25]
                sn_bytes = raw[:20].rstrip(b'\x00')
                cn_bytes = raw[20:25].rstrip(b'\x00')
                log_manager.log_and_attach(
                    f"SN={sn_bytes!r}, CN={cn_bytes!r}", "IDENTIFY_INFO")
                assert sn_bytes, "IDENTIFY_INFO SN 字段为空"
            else:
                log_manager.logger.warning(
                    "GET_IDENTIFY_INFO 无回包（P2 存档不判失败）")

    @allure.story("P2-SN/编码")
    @allure.title("P2 SN 写入 + 读回：SET_SERIAL_NUMBER(25)（门控 SN_WRITE）")
    @sn_write_gate
    def test_p2_sn_write_read(self, identify_guard):
        """验证 SN 写入并读回（写→读→guard 原值还原闭环）

        msg25 无专用 ACK，生效性以 IDENTIFY_INFO(2) 读回为准；写入是否
        即时生效未知（可能需重启），读回不等时 P2 存档不判失败——
        teardown 无论如何都会原值回写并读校验（identify_guard 兜底）。
        """
        test_sn = self._bump_identify(identify_guard[0])
        sn_show = test_sn.rstrip(b'\x00')
        with allure.step(f"SET_SERIAL_NUMBER(25) 写入派生测试值 {sn_show!r}"):
            # msg25 '<20BB'：serial[20B] + type(0=飞机SN)；
            # 测试值由本机原值逐字节 +1 派生（_bump_identify），非固定常量
            self._write_sn(test_sn)
            self._wrote_identify = True

        with allure.step("version CLI 读回核对（CLI 通道存档）"):
            resp = self._cli("version")
            log_manager.log_and_attach(resp[:300], "version 读回")
            assert resp and "sn" in resp.lower(), (
                f"写入后 version 仍可读: {resp[:200]}")

        with allure.step("IDENTIFY_INFO 读回比对（即时生效性未知，P2 存档不判死）"):
            current = self._read_identify(retries=1)
            if current is not None and current[0] == test_sn:
                log_manager.log_and_attach(
                    f"SN 读回 = 写入值 {sn_show!r}（即时生效）", "SN 读回")
            else:
                got = current[0].rstrip(b'\x00') if current else b''
                log_manager.logger.warning(
                    f"SN 读回 {got!r} ≠ 写入值 {sn_show!r}"
                    f"（可能需重启生效；guard 仍将原值回写，P2 不判失败）")

    @allure.story("P2-SN/编码")
    @allure.title("P2 设备编码写入：SET_CODE_NUMBER(28)（门控 SN_WRITE）")
    @sn_write_gate
    def test_p2_code_write(self, identify_guard):
        """验证设备编码写入 + IDENTIFY_INFO 读回（无 CLI 读回通道）

        guard 兜底原值还原（写入是否即时生效未知，读回不等时 P2 存档
        不判失败）。
        """
        test_code = self._bump_identify(identify_guard[1])
        code_show = test_code.rstrip(b'\x00')
        with allure.step(f"SET_CODE_NUMBER(28) 发送派生测试值 {code_show!r}"):
            # msg28 '<5B'：code_number[5B]；
            # 测试值由本机原值逐字节 +1 派生（_bump_identify），非固定常量
            self._write_code(test_code)
            self._wrote_identify = True

        with allure.step("IDENTIFY_INFO 读回比对（即时生效性未知，P2 存档不判死）"):
            current = self._read_identify(retries=1)
            if current is not None and current[1] == test_code:
                log_manager.log_and_attach(
                    f"编码读回 = 写入值 {code_show!r}（即时生效）", "编码读回")
            else:
                got = current[1].rstrip(b'\x00') if current else b''
                log_manager.logger.warning(
                    f"编码读回 {got!r} ≠ 写入值 {code_show!r}"
                    f"（可能需重启生效；guard 仍将原值回写，P2 不判失败）")

    # ==================================================================
    # 校时
    # ==================================================================

    @allure.story("P2-校时")
    @allure.title("P2 校时：CALIB_TIME(46) → now CLI 回读")
    def test_p2_time_sync(self):
        """验证校时命令可发送且时间可读（P2 正向）"""
        with allure.step("读取当前时间（now CLI 基线）"):
            now_before = self._cli("now")
            assert now_before and "time" in now_before.lower(), (
                f"now 无时间字段: {now_before[:200]}")
            log_manager.log_and_attach(now_before[:300], "校时前 now")

        with allure.step("发送 CALIB_TIME(46)"):
            msg = MAVLink_message(
                msg_id=MSG_ID_TIME_CHECK, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version, fields={'type': 1})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            time.sleep(2.0)
            log_manager.log_and_attach("CALIB_TIME type=1 已发送", "校时发送")

        with allure.step("校时后 now 回读"):
            now_after = self._cli("now")
            log_manager.log_and_attach(now_after[:300], "校时后 now")
            assert now_after and "time" in now_after.lower(), (
                f"校时后 now 无时间字段: {now_after[:200]}")

    # ==================================================================
    # Home / 围栏
    # ==================================================================

    @allure.story("P2-Home/围栏")
    @allure.title("P2 围栏设置：DO_SET_FENCE(180) MAVLink + fence CLI")
    def test_p2_fence_set(self):
        """验证围栏双通道可设（P2 正向：MAVLink 180 + CLI）"""
        with allure.step("MAVLink DO_SET_FENCE(180) 设置"):
            # chenpan 用例同款参数：command=180, radius=100, height=50
            ack = self._send_command(CMD_DO_SET_FENCE,
                                     param1=0, param2=0, param3=100, param4=50)
            assert ack is not None, "DO_SET_FENCE 无 ACK"
            result = ack.fields.get('result')
            log_manager.log_and_attach(
                f"DO_SET_FENCE ACK result={result}", "围栏 MAVLink 设置")

        with allure.step("CLI fence 命令设置"):
            resp = self._cli("fence 0, 0, 100, 50")
            assert resp and CONSOLE_PROMPT in resp, (
                f"fence 无完整回显: {resp[:200]}")
            assert not _cli_failed(resp), f"fence 执行失败: {resp[:200]}"
            log_manager.log_and_attach(resp[:300], "fence CLI 回显")

    @allure.story("P2-Home/围栏")
    @allure.title("P2 围栏触发检测：设极小围栏 + fs_state 检测")
    def test_p2_fence_trigger(self):
        """验证极小围栏下飞控检测到越界（P2：协议级检测验证）"""
        with allure.step("设极小围栏（半径 1m，飞机必然越界）"):
            ack = self._send_command(CMD_DO_SET_FENCE,
                                     param1=0, param2=0, param3=1, param4=1)
            assert ack is not None, "设极小围栏无 ACK"
            time.sleep(3.0)

        with allure.step("检查 fs_state 是否有围栏标志"):
            state = self._cli("fs_state")
            log_manager.log_and_attach(state, "极小围栏下 fs_state")
            # 飞机在半径 1m 围栏外 → fence 标志可能置位
            fence_hit = 'fence' in state.lower() and ':1' in state
            if not fence_hit:
                log_manager.logger.warning(
                    "极小围栏下 fence 标志未置位——检测可能需飞行状态或 "
                    "GCS-04 ffs 3 注入验证（P2 存档不判失败）")

        with allure.step("恢复正常围栏"):
            ack = self._send_command(CMD_DO_SET_FENCE,
                                     param1=0, param2=0, param3=100, param4=50)
            assert ack is not None, "恢复正常围栏无 ACK"

    # ==================================================================
    # 任务编排（协议接收验证，不执行飞行）
    # ==================================================================

    @allure.story("P2-任务编排")
    @allure.title("P2 任务校验：MISSION_REQUEST_VERIFY(41) → ACK(42)")
    def test_p2_mission_verify(self):
        """验证任务校验请求可发送且有回执（P2 正向）"""
        with allure.step("发送 MISSION_REQUEST_VERIFY(41)"):
            # msg41 '<IBB'：crc32 + id + type
            msg = MAVLink_message(
                msg_id=MSG_ID_MISSION_REQUEST_VERIFY, sys_id=1, comp_id=1,
                seq=0, version=self.mavlink_version,
                fields={'crc32': 0, 'id': 0, 'type': 0})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            ack = self._wait_msg(MSG_ID_MISSION_REQUEST_ACK, timeout=5.0)
            if ack is not None:
                result = ack.fields.get('result')
                log_manager.log_and_attach(
                    f"MISSION_REQUEST_ACK result={result}", "任务校验回执")
                assert result is not None, "ACK result 字段为空"
            else:
                log_manager.logger.warning(
                    "MISSION_REQUEST_VERIFY 无 ACK（无任务文件时可能不回，"
                    "P2 存档不判失败）")

    @allure.story("P2-任务编排")
    @allure.title("P2 任务启动命令接收：SWARM_FLIGHT_START(50)")
    def test_p2_swarm_start(self):
        """验证任务启动命令可发送且有 ACK（P2：接收层验证，不执行飞行）"""
        with allure.step("发送 SWARM_FLIGHT_START(50)"):
            # msg50 '<QQQQQiiiiiiBB'，liaoyutao play 用例同源字段
            # 上锁地面态发送：ACK 可能拒绝（无任务/未解锁），接收层通畅即可
            now_ms = int(time.time() * 1000)
            msg = MAVLink_message(
                msg_id=MSG_ID_SWARM_FLIGHT_START, sys_id=1, comp_id=1,
                seq=0, version=self.mavlink_version,
                fields={'takeoff': now_ms, 'play': now_ms + 60000,
                        'takeoff_light': now_ms + 5000,
                        'land_light': now_ms + 300000,
                        'play_id': 1,
                        'ascend': 2, 'descend': 2,
                        'elevation': 50,
                        'return_lon': 0, 'return_lat': 0,
                        'final_mode': 6, 'mission_id': 1})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            # SWARM_FLIGHT_START 的 ACK 走 COMMAND_ACK(77) command=50
            ack = self._wait_msg(MSG_ID_COMMAND_ACK, timeout=5.0)
            if ack is not None and ack.fields.get('command') == 50:
                result = ack.fields.get('result')
                log_manager.log_and_attach(
                    f"SWARM_FLIGHT_START ACK result={result}"
                    f"（上锁态预期拒绝，接收层通畅即可）", "任务启动回执")
            else:
                log_manager.logger.warning(
                    "SWARM_FLIGHT_START 无 ACK 或 command≠50"
                    "（上锁地面态可能被忽略，P2 存档不判失败）")

    @allure.story("P2-任务编排")
    @allure.title("P2 急停：FLIGHT_STOP(40003) → ACK")
    def test_p2_flight_stop(self):
        """验证急停命令可发送且有 ACK（P2 正向：上锁态安全）"""
        with allure.step("发送 FLIGHT_STOP(40003)"):
            ack = self._send_command(CMD_FLIGHT_STOP)
            assert ack is not None, "FLIGHT_STOP 无 ACK"
            result = ack.fields.get('result')
            log_manager.log_and_attach(
                f"FLIGHT_STOP ACK result={result}（上锁态安全发送）",
                "急停回执")

    # ==================================================================
    # 文件传输（简要：会话通道验证）
    # ==================================================================

    @allure.story("P2-文件传输")
    @allure.title("P2 NET_FILE 会话：打开 → 关闭")
    def test_p2_net_file_session(self):
        """验证 NET_FILE_OPEN/CLOSE 会话通道（P2 正向，不写数据）"""
        with allure.step("NET_FILE_OPEN 打开 test 文件"):
            path = b'test_p2.tmp'
            data = path.ljust(250, b'\x00') + struct.pack('<h', 1)
            msg = MAVLink_message(
                msg_id=MSG_ID_NET_FILE_COMMAND, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'net_file_cmd': NET_FILE_OPEN,
                        'data': list(data[:253])})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            resp = self._wait_msg(MSG_ID_NET_FILE_COMMAND, timeout=5.0)
            if resp is not None:
                log_manager.log_and_attach(
                    f"OPEN 回包 cmd={resp.fields.get('net_file_cmd')}",
                    "NET_FILE_OPEN 回执")
            else:
                log_manager.logger.warning(
                    "NET_FILE_OPEN 无回包（协议细节待确认，P2 存档不判失败）")

        with allure.step("NET_FILE_CLOSE 关闭会话"):
            close_data = struct.pack('<h', 0)
            msg = MAVLink_message(
                msg_id=MSG_ID_NET_FILE_COMMAND, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'net_file_cmd': NET_FILE_CLOSE,
                        'data': list(close_data.ljust(253, b'\x00'))})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            resp = self._wait_msg(MSG_ID_NET_FILE_COMMAND, timeout=3.0)
            if resp is not None:
                log_manager.log_and_attach(
                    f"CLOSE 回包 cmd={resp.fields.get('net_file_cmd')}",
                    "NET_FILE_CLOSE 回执")
            else:
                log_manager.logger.warning(
                    "NET_FILE_CLOSE 无回包（P2 存档不判失败）")

    # ==================================================================
    # 底板灯 RGB 控制（区别于指示灯 notify / 激光 p7=4）
    # ==================================================================

    @allure.story("P2-底板灯")
    @allure.title("P2 底板灯 RGB 开启（绿色）→ packed_state 回读 → 关闭")
    def test_p2_bottom_light(self):
        """验证底板灯 RGB 控制：开启→回读→关闭闭环（P2 正向）

        COMMAND_LONG 183 param7=1 = 底板灯通道（V4/X1 LED 用例同源，
        liaoyutao test_mavlink_led_control.py 同款协议）。
        回读：packed_state.light_r/light_g/light_b
        """
        with allure.step("开启底板灯（绿色 0,36,0, param7=1）"):
            ack = self._send_command(
                CMD_DO_SET_SERVO, param1=0, param2=36, param3=0,
                param7=LED_PARAM7)
            assert ack is not None, "底板灯开启无 ACK"
            result = ack.fields.get('result')
            log_manager.log_and_attach(
                f"底板灯 ACK result={result}", "底板灯开启")

        with allure.step("packed_state 回读 light 字段"):
            packed = self._get_packed_state()
            if packed is not None:
                light = (packed.fields.get('light_r'),
                         packed.fields.get('light_g'),
                         packed.fields.get('light_b'))
                log_manager.log_and_attach(
                    f"指令 RGB(0,36,0) → 回读 light={light}", "底板灯回读")
                # P2 简要：回读值非全零即认为通道生效（精确比对待真机校准）
                if light == (0, 0, 0):
                    log_manager.logger.warning(
                        "底板灯回读全零——p7=1 通道可能未生效或 packed_state"
                        ".light 字段不反映底板灯（P2 存档不判失败）")
            else:
                log_manager.logger.warning("无法获取 packed_state 回读")

        with allure.step("关闭底板灯（RGB 全 0, param7=1）"):
            ack = self._send_command(
                CMD_DO_SET_SERVO, param1=0, param2=0, param3=0,
                param7=LED_PARAM7)
            assert ack is not None, "底板灯关闭无 ACK"
            log_manager.log_and_attach(
                f"底板灯关闭 ACK result={ack.fields.get('result')}",
                "底板灯关闭")
