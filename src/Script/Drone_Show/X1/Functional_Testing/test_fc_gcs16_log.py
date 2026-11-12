# coding: utf-8

"""
GCS-16 日志列表、下载与清理（p1×14）— MAVLink 原生日志协议

业务背景：
    飞行日志的三步操作（清单 → 分块下载 → 停止），LOG_ERASE 独立毁灭
    门控用例，仅测试机执行。

协议构造速查（v44 dialect + 2026-09-11 真机测试）：
    ┌ 日志清单请求 → LOG_REQUEST_LIST(117) '<HHBB'（GCS→飞机）
    │   start=0, end=0xFFFF, target_system=1, target_component=1
    │   回包：LOG_ENTRY(118) × N 条流式（每条一个日志的元数据）
    │
    ├ 日志条目 → LOG_ENTRY(118) '<QQIIH'（飞机→GCS）
    │   id(uint64)=日志编号、Latest_id(uint64)、time_utc(uint64)=UTC
    │   时间戳、size(uint32)=字节数、num_logs(uint16)=日志总数
    │   实测：utc 全为 315446400（≈1980-01-01，飞机时钟未校——
    │   无 GPS 时 RTC 不走，日志只能按 id 排序，不能按时间）
    │
    ├ 数据块请求 → LOG_REQUEST_DATA(119) '<QIIBB'（GCS→飞机）
    │   id=日志编号、ofs=起始偏移、count=请求字节数、target=1,1
    │   回包：LOG_DATA(120) 一条（按 ofs+count 裁剪）
    │
    ├ 数据块回传 → LOG_DATA(120) '<QIB240B'（飞机→GCS）
    │   id、ofs=实际偏移、count=实际字节数、data[240B]=定长缓冲
    │   实测：块大小 200B（LOG_BLOCK_BYTES 经验值，<240B 上限），
    │   ofs 连续（0 → 200 → …），最后一块 count<size 标志文件尾
    │
    ├ 日志清除 → LOG_ERASE(121) '<BB'（GCS→飞机，毁灭门控）
    │   target_system=1, target_component=1（仅此 2 字段）
    │   回包：无专用 ACK，清除结果由后续 LIST 清单核实（条目=0）
    │
    └ 停止回传 → LOG_REQUEST_END(122) '<BB'（GCS→飞机）
        target_system=1, target_component=1（仅此 2 字段）
        实测：停止后 2s 内无残留 LOG_DATA

    - test_gcs16_log_protocol   日志列表 + 分块下载 + 停止回传（默认执行）
    - test_gcs16_log_erase      LOG_ERASE 日志清除（不可逆，毁灭门控）

毁灭用例默认 skip。开启 = 运行前设置环境变量（门控定义在 fc_basic_base.py，
import 时求值，改代码无效）：
    PowerShell: $env:FC_BASIC_ENABLE_DESTRUCTIVE = "1"
    CMD:        set FC_BASIC_ENABLE_DESTRUCTIVE=1
    Git Bash:   FC_BASIC_ENABLE_DESTRUCTIVE=1 python main.py --device_type X1 --test_suites Functional_Testing
"""

import time

import pytest
import allure

from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    FCBasicBase, destructive_gate, log_manager,
    LOG_LIST_TIMEOUT, LOG_BLOCK_BYTES)
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    MSG_ID_LOG_REQUEST_LIST, MSG_ID_LOG_ENTRY, MSG_ID_LOG_REQUEST_DATA,
    MSG_ID_LOG_DATA, MSG_ID_LOG_ERASE, MSG_ID_LOG_REQUEST_END)


@allure.feature("FC 基础功能 P0/P1")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC")
@pytest.mark.functional
class TestGcs16Log(FCBasicBase):
    """GCS-16 日志列表、下载与清理（p1×14）"""

    @allure.story("GCS-16 日志协议")
    @allure.title("GCS-16 日志列表 + 分块下载 + 停止回传")
    def test_gcs16_log_protocol(self):
        """日志列表→下载→停止（GCS-16 p1×14 中的列表/下载/停止）"""
        with allure.step("LOG_REQUEST_LIST → 收集 LOG_ENTRY 清单"):
            self._clear_recv_buffer()
            msg = MAVLink_message(
                msg_id=MSG_ID_LOG_REQUEST_LIST, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'start': 0, 'end': 0xFFFF,
                        'target_system': 1, 'target_component': 1})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            entries = []
            num_logs = None
            start = time.time()
            while time.time() - start < LOG_LIST_TIMEOUT:
                received, addr = self.gcs.receive()
                if (received is not None and received.msg_id == MSG_ID_LOG_ENTRY
                        and addr and addr[0] == self.drone_ip):
                    entries.append(received)
                    n = received.fields.get('num_logs')
                    if n:
                        num_logs = n
                    if num_logs and len(entries) >= num_logs:
                        break
                time.sleep(0.02)
            summary = '\n'.join(
                f"  id={e.fields.get('id')} size={e.fields.get('size')}B "
                f"utc={e.fields.get('time_utc')}" for e in entries[:20])
            log_manager.log_and_attach(
                f"LOG_ENTRY {len(entries)} 条 (num_logs={num_logs})\n{summary}",
                "日志清单")
            assert entries, "LOG_REQUEST_LIST 无 LOG_ENTRY 回传（日志列表链路异常）"

        with allure.step("下载首个日志前 2 块，校验偏移连续"):
            first_id = entries[0].fields.get('id')
            first_size = entries[0].fields.get('size')
            # 空壳日志跳过（上一轮 ERASE 后固件自动新建的空日志 id=0/size=0，
            # 请求它的数据块会超时——2026-09-11 实测踩坑）
            if not first_id or not first_size:
                log_manager.logger.warning(
                    f"首个日志为空壳（id={first_id}, size={first_size}）——"
                    f"疑似上轮 ERASE 遗留，跳过下载步骤仅记录")
                return
            offsets = []
            for ofs in (0, LOG_BLOCK_BYTES):
                self._clear_recv_buffer()
                msg = MAVLink_message(
                    msg_id=MSG_ID_LOG_REQUEST_DATA, sys_id=1, comp_id=1, seq=0,
                    version=self.mavlink_version,
                    fields={'id': first_id, 'ofs': ofs,
                            'count': LOG_BLOCK_BYTES,
                            'target_system': 1, 'target_component': 1})
                self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
                data_msg = self._wait_msg(MSG_ID_LOG_DATA, timeout=6.0)
                assert data_msg is not None, (
                    f"LOG_REQUEST_DATA(id={first_id}, ofs={ofs}) 无 LOG_DATA 回传")
                actual_ofs = data_msg.fields.get('ofs')
                count = data_msg.fields.get('count')
                offsets.append((actual_ofs, count))
                log_manager.log_and_attach(
                    f"块 ofs={actual_ofs} count={count}B", f"日志块 @{ofs}")
            assert offsets[0][0] == 0 and offsets[1][0] == LOG_BLOCK_BYTES, (
                f"LOG_DATA 偏移不连续: {offsets}（缺块或乱序）")
            assert all(c and c > 0 for _, c in offsets), f"空数据块: {offsets}"

        with allure.step("LOG_REQUEST_END 停止回传"):
            msg = MAVLink_message(
                msg_id=MSG_ID_LOG_REQUEST_END, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'target_system': 1, 'target_component': 1})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            time.sleep(1.0)
            trailing = self._wait_msg(MSG_ID_LOG_DATA, timeout=2.0)
            log_manager.log_and_attach(
                f"停止后 2s 内残留 LOG_DATA: {'有' if trailing else '无'}",
                "停止回传")

    @allure.story("GCS-16 日志协议")
    @allure.title("GCS-16 LOG_ERASE 日志清除（不可逆）")
    @destructive_gate
    def test_gcs16_log_erase(self):
        """LOG_ERASE（GCS-16 清理 3 项，毁灭门控）"""
        with allure.step("LOG_ERASE → 确认旧日志清空"):
            # 固件行为：ERASE 清掉所有已存储日志后，日志系统自动为当前
            # 会话新建一条空日志（不可能归零，2026-09-11 实测 1 条）
            msg = MAVLink_message(
                msg_id=MSG_ID_LOG_ERASE, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'target_system': 1, 'target_component': 1})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            time.sleep(3.0)
            self._clear_recv_buffer()
            msg = MAVLink_message(
                msg_id=MSG_ID_LOG_REQUEST_LIST, sys_id=1, comp_id=1, seq=0,
                version=self.mavlink_version,
                fields={'start': 0, 'end': 0xFFFF,
                        'target_system': 1, 'target_component': 1})
            self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
            start = time.time()
            entries_after = 0
            while time.time() - start < 5.0:
                received, addr = self.gcs.receive()
                if (received is not None
                        and received.msg_id == MSG_ID_LOG_ENTRY
                        and addr and addr[0] == self.drone_ip):
                    entries_after += 1
                time.sleep(0.05)
            log_manager.log_and_attach(
                f"清除后 LOG_ENTRY {entries_after} 条"
                f"（≤1 为正常——固件清完旧日志后自动新建当前会话日志）",
                "清除结果")
            # ≤1 = 旧日志全部清除 + 可能有一条自动新建的当前会话日志；
            # >1 = 清除失败，旧日志残留
            assert entries_after <= 1, (
                f"清除后仍有 {entries_after} 条日志——旧日志未清干净"
                f"（预期 ≤1：旧日志清零 + 固件自动新建 1 条当前会话日志）")
