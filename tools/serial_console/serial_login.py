# -*- coding: utf-8 -*-
"""串口自动登录: 打开 Acore 调试串口, 用给定凭据登录并执行命令

用法: python tools/serial_console/serial_login.py COM8 921600 root root "ip -4 addr show; uname -a"
    若控制台已是登录后的 shell, 直接执行命令。
"""
import sys
import time

import serial


def read_until(ser, markers, timeout):
    """读到任一 marker 或超时, 返回累积文本"""
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = ser.read(512)
        if data:
            buf += data
            text = buf.decode("utf-8", errors="replace").lower()
            if any(m.lower() in text for m in markers):
                break
    return buf.decode("utf-8", errors="replace")


def main():
    port, baud, user, pwd = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    command = sys.argv[5] if len(sys.argv) > 5 else "uname -a; ip -4 addr show"
    ser = serial.Serial(port, baud, timeout=0.5)
    log = []

    ser.write(b"\r\n")
    time.sleep(1)
    ser.reset_input_buffer()
    ser.write(b"\r\n")
    log.append(read_until(ser, ["login:", "#", "$"], 4))

    if "login:" in log[-1].lower():
        ser.write((user + "\n").encode())
        log.append(read_until(ser, ["assword:"], 5))
        ser.write((pwd + "\n").encode())
        log.append(read_until(ser, ["#", "$", "incorrect", "failed"], 6))
    ser.reset_input_buffer()

    ser.write((command + "\n").encode())
    time.sleep(2)
    out = read_until(ser, [], 5)
    log.append(out)
    ser.close()

    print("=" * 60)
    print("".join(log))
    print("=" * 60)


if __name__ == "__main__":
    main()
