# coding: utf-8
"""一次性将所有参数设为 TEST_VALUES（绕过 send_command，直接串口读写）。"""
import sys
import os
import time
# 本脚本位于 tools/x1_params/ 下, 向上两级即项目根目录 (保证 src.* 可导入)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _PROJECT_ROOT)

from src.Physical.Serial.SerialPortController import SerialPortController
from src.Script.Drone_Show.X1.Release_Testing.test_parameter_defaults import TEST_VALUES

PORT = "COM7"
BAUDRATE = 115200

print(f"连接串口: {PORT} @ {BAUDRATE}")

spc = SerialPortController(port=PORT, baudrate=BAUDRATE, timeout=0.5)
if not spc.connect():
    print("串口连接失败")
    sys.exit(1)

print("已连接，等待设备就绪...")
time.sleep(1)
spc.clear_buffer()

# 发一个换行确认设备在提示符
spc.send_data("\r\n")
time.sleep(0.5)
spc.clear_buffer()

failed = []
total = len(TEST_VALUES)

for i, (name, value) in enumerate(TEST_VALUES.items(), 1):
    cmd = f"sp {name}:{value}\r\n"
    spc.clear_buffer()
    spc.send_data(cmd)

    # 读取响应直到收到提示符或超时
    response = b""
    start = time.time()
    while (time.time() - start) < 2.0:
        data = spc.read_data(timeout=0.2)
        if data:
            response += data
            decoded = response.decode('utf-8', errors='ignore')
            if "~dmd_uav~@" in decoded:
                break

    decoded = response.decode('utf-8', errors='ignore')
    ok = "ACK" in decoded and "Found param" in decoded.lower()
    status = "OK" if ok else "FAIL"
    if not ok:
        failed.append(name)

    print(f"  [{i:2d}/{total}] {name} = {value} ... {status}")
    if not ok:
        print(f"        响应: {decoded.strip()[:120]}")

print(f"\n完成: {total - len(failed)}/{total} 成功, {len(failed)} 失败")
if failed:
    print(f"失败参数: {failed}")

spc.disconnect()
print("已断开")
