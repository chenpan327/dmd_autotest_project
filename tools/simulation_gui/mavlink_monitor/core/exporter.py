"""LogExporter — log persister for MAVLink messages.

Writes MessageRecord objects to a human-readable log file (matching the
existing project style), and supports bulk CSV/JSON export.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import TextIO

from .model import FieldDetail, MessageRecord


def hex_to_ascii(hex_bytes: bytes) -> str:
    """Convert bytes to a readable ASCII representation.

    0x00 -> \\0
    printable (0x20-0x7E) -> the character itself
    everything else -> '.'
    """
    result: list[str] = []
    for b in hex_bytes:
        if b == 0:
            result.append("\\0")
        elif 0x20 <= b <= 0x7E:
            result.append(chr(b))
        else:
            result.append(".")
    return "".join(result)


def _format_timestamp(ts: float) -> str:
    """Format a UNIX timestamp to [YYYY-MM-DD HH:MM:SS.ffffff]."""
    return datetime.fromtimestamp(ts).strftime("[%Y-%m-%d %H:%M:%S.%f]")


def _format_iso_timestamp(ts: float) -> str:
    """Format a UNIX timestamp to ISO 8601 with microseconds."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _format_crc(record: MessageRecord) -> str:
    """Format CRC status line.

    OK:    "OK (0xXXXX)"
    FAIL:  "FAIL (calc=0xAAAA, frame=0xBBBB)"
    """
    if record.crc_ok:
        return f"OK (0x{record.crc_expected:04X})"
    return f"FAIL (calc=0x{record.crc_expected:04X}, frame=0x{record.crc_actual:04X})"


def _format_field(fd: FieldDetail) -> str:
    """Format a single field detail line.

    Non-array:    name = value_display
    Array:        name = <hex bytes> (ASCII: 'readable')
    """
    if fd.is_array:
        # For arrays, value_raw should be bytes and raw_hex the spaced-hex version.
        if isinstance(fd.value_raw, bytes):
            ascii_str = hex_to_ascii(fd.value_raw)
            return f"    {fd.name} = {fd.raw_hex} (ASCII: '{ascii_str}')"
        else:
            # Fallback: raw_hex only
            return f"    {fd.name} = {fd.raw_hex}"
    else:
        return f"    {fd.name} = {fd.value_display}"


def _format_payload_hex(record: MessageRecord) -> str:
    """Format raw payload hex when fields are not yet parsed."""
    payload = record.payload_hex
    if payload:
        return f"    (raw payload) {payload}"
    return "    (raw payload) <empty>"


def _format_format_display(record: MessageRecord) -> str:
    """Format the 'Format:' line."""
    if record.format_type == "ip_prefixed" and record.relay_ip:
        return f"Format: ip_prefixed (Relay: {record.relay_ip})"
    return f"Format: {record.format_type}"


# ═══════════════════════════════════════════════════════════════════════════
# LogExporter
# ═══════════════════════════════════════════════════════════════════════════

class LogExporter:
    """Log persister for MAVLink messages.

    Writes human-readable log files matching the existing project style,
    and can bulk-export records to CSV / JSON files.

    优化：write_record() 不每条 flush，而是按时间间隔（默认 1 秒）
    或缓冲区积累（默认 64KB）触发刷新，大幅降低高频日志场景的磁盘 I/O。
    """

    # 缓冲刷新策略
    _FLUSH_INTERVAL = 1.0     # 秒
    _FLUSH_BUF_SIZE = 65536   # 字节（64 KB）

    def __init__(self, log_dir: str = "./logs"):
        self._log_dir = log_dir
        self._file: TextIO | None = None
        self._started: bool = False
        self._last_flush: float = 0.0
        self._buf_written: int = 0

    # ── Log session ──────────────────────────────────────────────────────

    def start_logging(self, prefix: str = "test_log") -> str:
        """Start a new log session.

        Creates the log directory (if needed), opens a new file named
        ``{prefix}_YYYYMMDD_HHMMSS.log``, and returns its absolute path.
        """
        os.makedirs(self._log_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.log"
        filepath = os.path.join(self._log_dir, filename)

        self._file = open(filepath, "w", encoding="utf-8")
        self._started = True
        self._last_flush = time.time()
        self._buf_written = 0
        return os.path.abspath(filepath)

    def stop_logging(self) -> None:
        """Close the current log file（确保刷新所有缓冲数据）。"""
        if self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None
        self._started = False
        self._buf_written = 0

    # ── Write single record ──────────────────────────────────────────────

    def write_record(self, record: MessageRecord) -> None:
        """Write a single MessageRecord to the log file.

        Format matches the existing project style (see module docstring for
        examples).  If no logging session is active the call is silently
        ignored.
        """
        if self._file is None or not self._started:
            return

        lines: list[str] = []

        # Header line: timestamp + direction
        lines.append(f"{_format_timestamp(record.timestamp_abs)} MAVLINK {record.direction}")
        lines.append(f"  Src:  {record.src_ip}:{record.src_port}")
        lines.append(f"  Dst:  {record.dst_ip}:{record.dst_port}")
        lines.append(f"  Msg:  {record.msg_name} (id={record.msg_id})")
        lines.append(f"  CRC:  {_format_crc(record)}")
        lines.append(f"  {_format_format_display(record)}")
        lines.append(f"  Source: {record.source_type} ({record.node_id})")
        lines.append("  Fields:")

        # Fields or raw payload
        if record.fields_parsed and record.fields:
            for fd in record.fields:
                lines.append(_format_field(fd))
        else:
            lines.append(_format_payload_hex(record))

        lines.append("")  # blank separator line

        chunk = "\n".join(lines)
        self._file.write(chunk)
        self._buf_written += len(chunk)

        # 按时间间隔或缓冲区大小触发 flush，而非每条记录都 flush
        now = time.time()
        if (now - self._last_flush >= self._FLUSH_INTERVAL
                or self._buf_written >= self._FLUSH_BUF_SIZE):
            self._file.flush()
            self._last_flush = now
            self._buf_written = 0

    # ── Export helpers ───────────────────────────────────────────────────

    def export_csv(self, records: list[MessageRecord], filepath: str) -> None:
        """Export a list of records to a CSV file.

        Columns: Seq, Time(Abs), Time(Rel), Dir, Src IP, Src Port,
        Dst IP, Dst Port, Msg Name, Msg ID, Sys, Comp, Len, CRC,
        Format, Relay IP
        """
        header = (
            "Seq,Time(Abs),Time(Rel),Dir,Src IP,Src Port,Dst IP,Dst Port,"
            "Msg Name,Msg ID,Sys,Comp,Len,CRC,Format,Relay IP,Node ID,Source"
        )

        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(header + "\n")
            for r in records:
                crc = "OK" if r.crc_ok else "FAIL"
                relay = r.relay_ip if r.format_type == "ip_prefixed" else ""
                row = (
                    f"{r.seq},"
                    f"{_format_iso_timestamp(r.timestamp_abs)},"
                    f"{r.timestamp_rel:+.6f},"
                    f"{r.direction},"
                    f"{r.src_ip},{r.src_port},"
                    f"{r.dst_ip},{r.dst_port},"
                    f"{r.msg_name},"
                    f"0x{r.msg_id:02X},"
                    f"{r.sys_id},{r.comp_id},{r.payload_len},"
                    f"{crc},"
                    f"{r.format_type},"
                    f"{relay},"
                    f"{r.node_id},"
                    f"{r.source_type}"
                )
                f.write(row + "\n")

    def export_json(self, records: list[MessageRecord], filepath: str) -> None:
        """Export a list of records to a JSON file.

        Each record is serialized as a flat dict with ISO-8601 timestamp.
        """
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

        data: list[dict] = []
        for r in records:
            crc = "OK" if r.crc_ok else "FAIL"
            relay = r.relay_ip if r.format_type == "ip_prefixed" else ""
            data.append({
                "seq": r.seq,
                "timestamp_abs": _format_iso_timestamp(r.timestamp_abs),
                "timestamp_rel": round(r.timestamp_rel, 6),
                "direction": r.direction,
                "src_ip": r.src_ip,
                "src_port": r.src_port,
                "dst_ip": r.dst_ip,
                "dst_port": r.dst_port,
                "msg_name": r.msg_name,
                "msg_id": f"0x{r.msg_id:02X}",
                "sys_id": r.sys_id,
                "comp_id": r.comp_id,
                "payload_len": r.payload_len,
                "crc": crc,
                "format_type": r.format_type,
                "relay_ip": relay,
                "node_id": r.node_id,
                "source_type": r.source_type,
                "fields_parsed": r.fields_parsed,
                "fields": [
                    {
                        "name": fd.name,
                        "value_raw": (
                            fd.raw_hex if isinstance(fd.value_raw, bytes)
                            else fd.value_raw
                        ),
                        "value_display": fd.value_display,
                        "raw_hex": fd.raw_hex,
                        "type_name": fd.type_name,
                        "is_array": fd.is_array,
                    }
                    for fd in r.fields
                ],
            })

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
