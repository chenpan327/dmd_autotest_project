# coding: utf-8
"""
CAN / CAN FD 协议封装（协议层）

对 TSMasterController（物理层）的薄封装，提供语义化的 CAN 收发 / 信号监控 /
RBS 剩余总线仿真 / 性能统计方法，供脚本层直接调用。

Usage::

    bus = CanProtocol(bin64_path="C:/Program Files (x86)/TOSUN/TSMaster/bin64")
    bus.connect()
    bus.send_frame(0x123, [1, 2, 3, 4, 5, 6, 7, 8])
    cid = bus.register_signal(0x64, "EngSpeed")
    value, ts_us = bus.read_signal(cid)
    bus.disconnect()
"""
from utils.logger import logger

from src.Physical.TSMaster.tsmaster_controller import TSMasterController


class CanProtocol:
    """CAN / CAN FD 总线协议封装（同步 API，提供上下文管理器）。"""

    def __init__(self, controller=None, bin64_path=None):
        """
        Args:
            controller (TSMasterController, optional): 已构造的控制器，None 时新建
            bin64_path (str, optional): TSMaster bin64 目录
        """
        self.controller = controller or TSMasterController(bin64_path=bin64_path)

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------

    def connect(self, app_name="TSMaster"):
        return self.controller.connect(app_name)

    def disconnect(self):
        self.controller.disconnect()

    @property
    def is_connected(self):
        return self.controller.is_connected

    # ------------------------------------------------------------------
    # 通道配置
    # ------------------------------------------------------------------

    def set_channel_count(self, count):
        return self.controller.set_can_channel_count(count)

    def configure_baudrate(self, chn, kbps, listen_only=False,
                           install_term_resistor_120ohm=False):
        return self.controller.configure_can_baudrate(
            chn, kbps, listen_only, install_term_resistor_120ohm
        )

    def configure_canfd_baudrate(self, chn, arb_kbps, data_kbps, **kwargs):
        return self.controller.configure_canfd_baudrate(chn, arb_kbps, data_kbps, **kwargs)

    def set_mapping(self, chn_index, hw_name, hw_type, hw_sub_type,
                    hw_index, hw_channel_index, enabled=True, app_name="TSMaster"):
        return self.controller.set_mapping(
            chn_index, hw_name, hw_type, hw_sub_type,
            hw_index, hw_channel_index, enabled, app_name,
        )

    # ------------------------------------------------------------------
    # 帧发送
    # ------------------------------------------------------------------

    def send_frame(self, frame_id, data, chn=0, is_ext=False, is_fd=False):
        """发送一帧 CAN / CAN FD（data 为字节列表）。"""
        can = self.controller.make_can_frame(frame_id, data, chn, is_ext, is_fd)
        ok = self.controller.transmit_can(can)
        logger.info(f"[CanProtocol] 发送帧 0x{int(frame_id):X} data={list(data)} -> {'OK' if ok else 'FAIL'}")
        return ok

    def send_frame_sync(self, frame_id, data, timeout_ms=1000, chn=0,
                        is_ext=False, is_fd=False):
        """同步发送一帧 CAN / CAN FD。"""
        can = self.controller.make_can_frame(frame_id, data, chn, is_ext, is_fd)
        return self.controller.transmit_can_sync(can, timeout_ms)

    def send_periodic(self, frame_id, data, period_ms, chn=0, is_ext=False, is_fd=False):
        """周期发送一帧 CAN / CAN FD。"""
        can = self.controller.make_can_frame(frame_id, data, chn, is_ext, is_fd)
        ok = self.controller.add_cyclic_message(can, period_ms)
        logger.info(f"[CanProtocol] 周期发送 0x{int(frame_id):X} @ {period_ms}ms -> {'OK' if ok else 'FAIL'}")
        return ok

    def stop_periodic(self):
        """停止所有周期帧。"""
        return self.controller.del_cyclic_messages()

    # ------------------------------------------------------------------
    # 信号监控
    # ------------------------------------------------------------------

    def register_signal(self, msg_id, signal_name, chn=0):
        """按报文 ID 注册 CAN 信号，返回 client_id。"""
        return self.controller.register_can_signal(chn, msg_id, signal_name)

    def read_signal(self, client_id, chn=0):
        """读取已注册 CAN 信号的最新物理值，返回 (value, timestamp_us)。"""
        return self.controller.get_can_signal_value(chn, client_id)

    # ------------------------------------------------------------------
    # RBS 剩余总线仿真
    # ------------------------------------------------------------------

    def rbs_start(self):
        return self.controller.rbs_start()

    def rbs_stop(self):
        return self.controller.rbs_stop()

    def rbs_configure(self, auto_start=True, auto_send_on_modification=True,
                      activate_node_simulation=True, init_value_options=0):
        return self.controller.rbs_configure(
            auto_start, auto_send_on_modification,
            activate_node_simulation, init_value_options,
        )

    def rbs_activate_message(self, chn, network, node, message, enable=True):
        return self.controller.rbs_activate_message(chn, network, node, message, enable)

    def rbs_set_signal(self, address, value):
        return self.controller.rbs_set_signal_by_address(address, value)

    def rbs_get_signal(self, address):
        return self.controller.rbs_get_signal_by_address(address)

    # ------------------------------------------------------------------
    # 性能统计
    # ------------------------------------------------------------------

    def enable_bus_statistics(self, enable=True):
        return self.controller.enable_bus_statistics(enable)

    def get_fps(self, frame_id, chn=0):
        """获取指定 ID 的每秒帧数（FPS），需先 enable_bus_statistics。"""
        return self.controller.get_fps(chn, frame_id)

    def get_bus_load(self, chn=0):
        """获取 CAN 总线负载（%）。"""
        return self.controller.get_bus_load(chn)

    # ------------------------------------------------------------------
    # 上下文管理器
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    def __del__(self):
        try:
            self.disconnect()
        except Exception:
            pass
