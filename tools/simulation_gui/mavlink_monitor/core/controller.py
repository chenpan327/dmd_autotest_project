"""MonitorController — 核心引擎 ↔ GUI 桥接层

统一管理 parser / model / engine / filter / exporter 的生命周期。
GUI 只通过此类与核心交互。
"""

from __future__ import annotations
import time
from typing import Callable

from .model import MonitorModel, MessageRecord, FieldDetail
from .parser import MavlinkParser
from .engine import MonitorEngine
from .filter import MessageFilter, FilterRule, FilterResult
from .exporter import LogExporter


class MonitorController:
    """核心引擎 ↔ GUI 桥接控制器。

    用法:
        ctrl = MonitorController()
        ctrl.load_config(config_path, enums_path)
        ctrl.set_interface("以太网")
        ctrl.start()
        ...
        records = ctrl.get_new_records()
        ctrl.stop()
    """

    def __init__(self):
        self.parser = MavlinkParser()
        self.model = MonitorModel(capacity=4096000)
        self.engine = MonitorEngine(self.parser, self.model)
        self.filter = MessageFilter()
        self.exporter = LogExporter()

        self._config_loaded = False
        self._enums_loaded = False
        self._last_seq: int = 0          # GUI 已消费到的 seq
        self._start_time: float = 0.0   # 引擎启动时间
        self._last_highlights: dict[int, tuple] = {}  # 上次过滤的高亮映射
        self.filter_enabled: bool = True  # 过滤开关（GUI 控制）

    # ═══════════════════════════════════════════════════════════
    # 配置
    # ═══════════════════════════════════════════════════════════
    def load_config(self, config_path: str, version: str = "default") -> bool:
        """加载 MAVLink 消息配置 JSON。"""
        try:
            self.parser.load_config(config_path, version)
            self._config_loaded = True
            return True
        except Exception as e:
            print(f"[Controller] 加载 config 失败: {e}")
            return False

    def get_available_msgids(self) -> dict[int, str]:
        """返回已加载配置中所有消息的 {msg_id: message_name} 映射。"""
        return self.parser.get_available_msgids()

    def load_enums(self, enums_path: str, version: str = "default") -> bool:
        """加载 MAVLink 枚举 JSON。"""
        try:
            self.parser.load_enums(enums_path, version)
            self._enums_loaded = True
            return True
        except Exception as e:
            print(f"[Controller] 加载 enums 失败: {e}")
            return False

    def load_command_183_config(self, config_path: str) -> bool:
        """加载 command=183 业务功能映射配置。"""
        try:
            self.parser.load_command_183_config(config_path)
            return True
        except Exception as e:
            print(f"[Controller] 加载 command_183 配置失败: {e}")
            return False

    @property
    def is_config_ready(self) -> bool:
        return self._config_loaded

    # ═══════════════════════════════════════════════════════════
    # 网卡配置 & 启停
    # ═══════════════════════════════════════════════════════════
    def set_interface(self, name: str) -> None:
        """配置要嗅探的网卡接口名称。"""
        self.engine.set_interface(name)

    @property
    def active_interface(self) -> str:
        """当前活跃的网卡名称。"""
        return self.engine.active_interface_name

    # ═══════════════════════════════════════════════════════════
    # UDP 监听配置 & 启停
    # ═══════════════════════════════════════════════════════════
    def set_udp_listener(self, host: str = "0.0.0.0", port: int = 14550) -> None:
        """配置 UDP 监听器 host 和 port。"""
        self.engine.set_udp_listener(host, port)

    @property
    def udp_host(self) -> str:
        return self.engine.udp_host

    @property
    def udp_port(self) -> int:
        return self.engine.udp_port

    def start_udp(self) -> None:
        """启动 UDP socket 监听器。"""
        self.engine.start_udp()

    def stop_udp(self) -> None:
        """停止 UDP socket 监听器。"""
        self.engine.stop_udp()

    @property
    def is_udp_running(self) -> bool:
        return self.engine.is_udp_running

    def start(self) -> None:
        """启动网卡嗅探。"""
        self._start_time = time.time()
        self.engine.start()

    def stop(self) -> None:
        """停止网卡嗅探。"""
        self.engine.stop()

    @property
    def is_running(self) -> bool:
        return self.engine.is_running

    @property
    def is_paused(self) -> bool:
        return self.engine.is_paused

    def pause(self) -> None:
        self.engine.pause()

    def resume(self) -> None:
        self.engine.resume()

    # ═══════════════════════════════════════════════════════════
    # GUI 轮询接口
    # ═══════════════════════════════════════════════════════════
    def get_new_records(self) -> list[MessageRecord]:
        """获取上次消费以来的新记录并应用过滤。"""
        records = self.model.get_since(self._last_seq)
        if records:
            self._last_seq = records[-1].seq

        if self._has_active_filter():
            result = self.filter.apply(records)
            self._last_highlights = result.highlights
            return result.visible
        self._last_highlights = {}
        return records

    def get_last_filter_highlights(self) -> dict[int, tuple]:
        """返回最近一次过滤操作的高亮映射 (seq -> color)。"""
        return self._last_highlights

    def get_visible_records(self, max_count: int = 500) -> list[MessageRecord]:
        """获取当前可见记录（最近 max_count 条 + 过滤）。"""
        all_records = self.model.get_latest(max_count)
        if self._has_active_filter():
            result = self.filter.apply(all_records)
            return result.visible
        return all_records

    def _has_active_filter(self) -> bool:
        return self.filter_enabled and len(self.filter._rules) > 0

    # ═══════════════════════════════════════════════════════════
    # Lazy parse
    # ═══════════════════════════════════════════════════════════
    def parse_fields(self, record: MessageRecord) -> list[FieldDetail]:
        """对一条记录执行 lazy parse，返回字段详情。"""
        if record.fields_parsed:
            return record.fields

        # ── 电台 DAV 消息 → protobuf wire-format 解析 ──
        if record.source_type == "radio":
            fields = self._parse_radio_fields(record)
        else:
            fields = self.parser.parse_fields(record)

        # ── command=183 业务功能匹配 ──
        if record.msg_id == 76 and self.parser._cmd183_functions:
            # 检查 command 字段是否为 183
            for f in fields:
                if f.name == "command" and isinstance(f.value_raw, (int, float)):
                    if int(f.value_raw) == 183:
                        hint = self.parser.match_command_183_business(fields)
                        if hint:
                            # 将 hint 设置到 param7 字段上
                            for pf in fields:
                                if pf.name == "param7":
                                    pf.business_hint = hint
                                    break
                    break

        record.fields = fields
        record.fields_parsed = True
        return fields

    def _parse_radio_fields(self, record: MessageRecord) -> list[FieldDetail]:
        """解析电台 DAV 消息字段。

        按消息 msg_type 区分两种解析方式：
        - Ack 帧（dav_report 非 None，msg_type=1）：直接解析 report（不走 protobuf）
        - Msg 帧（msg_type=0）：protobuf wire 解析（GET_FIRMWARE_VERSION 等）
        """
        radio_node = self.engine._radio_node
        if radio_node is None or radio_node.parser is None:
            return []

        parser = radio_node.parser
        try:
            if record.dav_report is not None:
                return parser.parse_ack_report(record.dav_report)
            return parser.parse_protobuf_fields(record.msg_id, record.payload_bytes)
        except Exception as e:
            print(f"[Controller] 电台字段解析失败: {e}")
            return []

    # ═══════════════════════════════════════════════════════════
    # 过滤
    # ═══════════════════════════════════════════════════════════
    def set_filter_rules(self, rules: list[FilterRule]) -> None:
        self.filter.clear()
        for rule in rules:
            self.filter.add_rule(rule)

    def clear_filter(self) -> None:
        self.filter.clear()

    # ═══════════════════════════════════════════════════════════
    # 统计
    # ═══════════════════════════════════════════════════════════
    def get_stats(self) -> dict:
        """返回当前统计数据。

        优化：time.time() 只调用一次，减少系统调用开销。
        """
        now = time.time()
        rate = 0.0
        if self._start_time > 0:
            elapsed = now - self._start_time
            if elapsed > 0:
                rate = self.model.total / elapsed

        used, cap = self.model.buffer_usage
        uptime_sec = int(now - self._start_time) if self._start_time > 0 else 0
        h, m, s = uptime_sec // 3600, (uptime_sec % 3600) // 60, uptime_sec % 60

        return {
            "total":        self.model.total,
            "rate":         rate,
            "errors":       self.model.errors,
            "crc_fail":     self.model.crc_failures,
            "buffer_used":  used,
            "buffer_max":   cap,
            "uptime":       f"{h:02d}:{m:02d}:{s:02d}",
            "nic_packets":  self.engine.nic_packet_count,
            "nic_mavlink":  self.engine.nic_mavlink_count,
            "nic_errors":   self.engine.nic_error_count,
            "interface":    self.engine.active_interface_name,
            "udp_packets":  self.engine.udp_packet_count,
            "udp_mavlink":  self.engine.udp_mavlink_count,
            "udp_errors":   self.engine.udp_error_count,
            "udp_host":     self.engine.udp_host,
            "udp_port":     self.engine.udp_port,
            "udp_running":  self.engine.is_udp_running,
            "radio_packets": self.engine.radio_packet_count,
            "radio_mavlink": self.engine.radio_count,
            "radio_errors":  self.engine.radio_error_count,
            "radio_host":    self.engine.radio_host,
            "radio_port":    self.engine.radio_port,
            "radio_running": self.engine.is_radio_running,
            "gcs_app_port":    self.engine.gcs_app_port,
            "gcs_app_packets": self.engine.gcs_app_packet_count,
            "gcs_app_records": self.engine.gcs_app_record_count,
            "gcs_app_errors":  self.engine.gcs_app_error_count,
            "gcs_app_running": self.engine.is_gcs_app_running,
        }

    # ═══════════════════════════════════════════════════════════
    # 电台 DAV 监听控制
    # ═══════════════════════════════════════════════════════════
    def set_radio_listener(self, host: str = "0.0.0.0", port: int = 14555) -> None:
        """配置电台 DAV 监听器 host 和 port。"""
        self.engine.set_radio_listener(host, port)

    def load_radio_config(self, config_path: str) -> bool:
        """加载电台消息配置 JSON。"""
        return self.engine.load_radio_config(config_path)

    def start_radio(self) -> None:
        """启动电台 DAV UDP 监听器。"""
        self.engine.start_radio()

    def stop_radio(self) -> None:
        """停止电台 DAV UDP 监听器。"""
        self.engine.stop_radio()

    # ═══════════════════════════════════════════════════════════
    # 地面站应用 TCP 监控控制（GCS ↔ 云平台 TCP/TLS）
    # ═══════════════════════════════════════════════════════════
    def set_gcs_app_port(self, port: int = 443) -> None:
        """配置地面站应用监控对端端口（云端 HTTPS，默认 443）。"""
        self.engine.set_gcs_app_listener(port)

    def start_gcs_app(self) -> None:
        """启动地面站应用 TCP 监控（需先选择网卡）。"""
        self.engine.start_gcs_app()

    def stop_gcs_app(self) -> None:
        """停止地面站应用 TCP 监控。"""
        self.engine.stop_gcs_app()

    def inject_radio_packet(self, data: bytes, src_ip: str, src_port: int,
                            dst_ip: str, dst_port: int) -> bool:
        """将假电台的 DAV 帧直接注入监控（走 radio parser，绕过端口监听）。

        由 FullUdpMonitorPanel.inject_raw_message 在检测到 DAV 帧（0xA5 同步字）时调用，
        与网卡/端口监听路径解耦，直接解析并写入 MonitorModel。

        Returns:
            True 表示成功解析并写入；False 表示解析器未配置或帧校验失败。
        """
        node = self.engine._radio_node
        if node is None or node.parser is None:
            return False
        if not node.parser.is_configured:
            return False
        record = node.parser.to_message_record(
            data, src_ip, src_port, dst_ip, dst_port,
            node_id=f"fake_radio_{dst_ip}",
        )
        if record is None:
            return False
        self.model.append(record, is_crc_fail=(not record.crc_ok))
        return True

    @property
    def is_radio_running(self) -> bool:
        return self.engine.is_radio_running

    @property
    def radio_host(self) -> str:
        return self.engine.radio_host

    @property
    def radio_port(self) -> int:
        return self.engine.radio_port

    @property
    def nest_enabled(self) -> bool:
        """机巢(ip_prefixed)格式解析是否启用。"""
        return self.engine.nest_enabled

    @nest_enabled.setter
    def nest_enabled(self, value: bool) -> None:
        self.engine.nest_enabled = value

    # ═══════════════════════════════════════════════════════════
    # 日志
    # ═══════════════════════════════════════════════════════════
    def start_logging(self, prefix: str = "test_log") -> str:
        return self.exporter.start_logging(prefix)

    def stop_logging(self) -> None:
        self.exporter.stop_logging()

    def log_record(self, record: MessageRecord) -> None:
        self.exporter.write_record(record)

    # ═══════════════════════════════════════════════════════════
    # 重置
    # ═══════════════════════════════════════════════════════════
    def reset_stats(self) -> None:
        self.model.reset_stats()
        self._start_time = time.time()

    def clear_buffer(self) -> None:
        self.model.clear()
        self._last_seq = 0
