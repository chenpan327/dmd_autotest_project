# -*- coding: utf-8 -*-
"""串口监听: 打开 COM 口持续抓取输出 N 秒, 存档到 log/serial_capture_*.log"""
import sys
import time
from datetime import datetime
from pathlib import Path

import serial


def listen(port: str, baud: int, seconds: int) -> None:
    # 本脚本位于 tools/serial_console/ 下, 向上三级即项目根目录
    out = (
        Path(__file__).resolve().parent.parent.parent
        / "logs"
        / f"serial_capture_{datetime.now():%Y%m%d_%H%M%S}.log"
    )
    out.parent.mkdir(parents=True, exist_ok=True)

    ser = serial.Serial(port, baud, timeout=0.3)
    print(f"[监听中] {port} @ {baud}，持续 {seconds}s，输出存档: {out}", flush=True)
    ser.write(b"\r\n")

    deadline = time.time() + seconds
    n = 0
    with open(out, "wb") as f:
        while time.time() < deadline:
            data = ser.read(4096)
            if data:
                f.write(data)
                f.flush()
                n += len(data)
    ser.close()
    print(f"[完成] 共收到 {n} 字节, 存档: {out}", flush=True)
    if n == 0:
        print("[结论] 全程无输出 — 检查供电/串口线是否接板子调试 UART/TX-RX 是否接反", flush=True)


if __name__ == "__main__":
    listen(
        sys.argv[1] if len(sys.argv) > 1 else "COM7",
        int(sys.argv[2]) if len(sys.argv) > 2 else 115200,
        int(sys.argv[3]) if len(sys.argv) > 3 else 90,
    )
