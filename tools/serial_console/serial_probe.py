# -*- coding: utf-8 -*-
"""串口探针: 打开 COM 口, 发送回车, 抓 3 秒输出判断板子控制台状态"""
import sys
import time

import serial
from serial.tools import list_ports


def probe(port: str, baud: int = 115200) -> None:
    print(f"[可用串口] {[p.device for p in list_ports.comports()]}")
    try:
        ser = serial.Serial(port, baud, timeout=0.3)
    except serial.SerialException as e:
        print(f"[失败] 打开 {port}@{baud} 失败: {e}")
        print("提示: 若提示拒绝访问, 请先关闭占用该串口的终端(如 PuTTY/串口助手)")
        sys.exit(1)

    print(f"[连接] {port} @ {baud} 8N1, 发送回车并抓取 3 秒输出 ...")
    ser.write(b"\r\n")
    time.sleep(0.5)
    ser.write(b"\r\n")

    deadline = time.time() + 3
    chunks = []
    while time.time() < deadline:
        data = ser.read(256)
        if data:
            chunks.append(data)
    ser.close()

    text = b"".join(chunks).decode("utf-8", errors="replace")
    print("-" * 50)
    print(text if text.strip() else "(无输出 — 板子可能没上电/波特率不对/非调试串口)")
    print("-" * 50)
    low = text.lower()
    if "login" in low:
        print(">>> 状态: 登录提示符 — 输入用户名密码即可登录")
    elif text.strip():
        print(">>> 状态: 已有输出(可能是 shell 提示符或启动日志), 请把上面内容发我看")


if __name__ == "__main__":
    port = sys.argv[1] if len(sys.argv) > 1 else "COM7"
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
    probe(port, baud)
