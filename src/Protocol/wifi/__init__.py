# coding: utf-8
"""
WiFi 模块协议层(wifi 子目录)

分层定位:
    物理层:Serial_Protocol_Lite.py(串口)、fake_ground_control_station.py(UDP)
    协议层:wifi.py — WiFi 专有命令封装、MAVLink 消息构造、iperf 客户端、升级流程
    脚本层:src/Script/Drone_Show/Wifi_Module/Release_Testing/ 下的 pytest 用例

所有 WiFi 协议层逻辑集中在单一文件 wifi.py 中,按以下分节组织:
    1. 常量             - MAVLink 命令 ID、msg_id、ACK 枚举、超时、固件路径、阈值
    2. 数据类           - IperfResult / UpgradeResult / ConnectionSample / StabilityReport / AutoSwitchReport
    3. MAVLink 命令封装 - send_standby / send_euler_network / send_update_companion / wait_for_command_ack
    4. iperf 客户端     - find_iperf_binary / run_tcp_uplink / run_udp_uplink
    5. 固件升级         - upgrade_gps / upgrade_companion / trigger_battery_upgrade
    6. 自动重连监控     - sample_connection / monitor_connection_stability / monitor_ssid_auto_switch

使用示例:
    from src.Protocol.wifi.wifi import (
        send_standby, send_euler_network, send_update_companion,
        find_iperf_binary, run_tcp_uplink, run_udp_uplink,
        upgrade_gps, upgrade_companion, trigger_battery_upgrade,
        monitor_ssid_auto_switch, monitor_connection_stability,
        MAV_CMD_STANDBY, MSG_ID_COMMAND_LONG, DEFAULT_ACK_TIMEOUT,
    )
"""
