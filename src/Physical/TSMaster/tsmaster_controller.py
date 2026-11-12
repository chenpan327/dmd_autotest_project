# coding: utf-8
"""
TSMaster CAN/CAN FD 总线控制器（物理层）

对 TSMaster Python API（app / com / test 三个静态类）做薄封装，聚焦 CAN / CAN FD。
TSMaster 的全部 API 返回码约定为 0 = 成功，非 0 = 错误码（详见工程根目录
TSMaster_Python_API.md）。

功能特性:
    - 运行时加载（config.json 解析 bin64 路径，注册表 fallback）
    - 应用连接 / 断开
    - CAN 通道数、波特率、硬件映射配置
    - CAN / CAN FD 帧构造与发送（异步 / 同步 / 周期）
    - 信号服务器（sgnsrv）注册与取值
    - RBS 剩余总线仿真控制
    - 总线统计 / FPS 测量
    - 上下文管理器 (with 语句)

属性:
    ts (module): 加载后的 TSMaster 模块
    app / com / test: TSMaster 的静态 API 类引用
    is_connected (bool): 连接状态标志
"""
from utils.logger import logger

from src.Physical.TSMaster.tsmaster_loader import load_tsmaster


class TSMasterController:
    """
    TSMaster CAN/CAN FD 总线控制器

    连接流程:
        1. 构造 TSMasterController(bin64_path=...)
        2. set_can_channel_count / configure_can_baudrate / set_mapping 等配置
        3. connect()
        4. 收发帧 / 信号 / RBS / 统计
        5. disconnect()
    """

    def __init__(self, bin64_path=None):
        """
        初始化控制器，加载 TSMaster 运行时

        Args:
            bin64_path (str, optional): TSMaster bin64 目录，None 时回退注册表
        """
        self.ts = load_tsmaster(bin64_path)
        self.app = self.ts.app
        self.com = self.ts.com
        self.test = self.ts.test
        self.is_connected = False

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _check(self, code, operation=""):
        """检查 TSMaster API 返回码（0 = 成功），失败时记录错误描述。"""
        if code != 0:
            desc = ""
            try:
                desc = self.app.get_error_description(code)
            except Exception:
                pass
            logger.error(f"[TSMaster] {operation} 失败 (code={code}): {desc}")
            return False
        return True

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect(self, app_name="TSMaster"):
        """
        连接 TSMaster 应用

        Args:
            app_name (str): 应用名称，默认 "TSMaster"

        Returns:
            bool: 连接成功返回 True，失败返回 False
        """
        try:
            if app_name:
                self.app.set_current_application(app_name)
            code = self.app.connect()
            self.is_connected = bool(self.app.is_connected())
            return self._check(code, f"connect({app_name})")
        except Exception as e:
            logger.error(f"[TSMaster] 连接失败: {e}")
            self.is_connected = False
            return False

    def disconnect(self):
        """断开 TSMaster 应用连接"""
        try:
            self.app.disconnect()
        except Exception as e:
            logger.error(f"[TSMaster] 断开连接失败: {e}")
        finally:
            self.is_connected = False

    # ------------------------------------------------------------------
    # 通道配置
    # ------------------------------------------------------------------

    def set_can_channel_count(self, count):
        """设置 CAN 通道总数"""
        return self._check(self.app.set_can_channel_count(count),
                           f"set_can_channel_count({count})")

    def configure_can_baudrate(self, chn, kbps, listen_only=False,
                               install_term_resistor_120ohm=False):
        """配置 CAN 波特率"""
        return self._check(
            self.app.configure_can_baudrate(
                chn, float(kbps), bool(listen_only), bool(install_term_resistor_120ohm)
            ),
            f"configure_can_baudrate(chn={chn}, {kbps}kbps)",
        )

    def configure_canfd_baudrate(self, chn, arb_kbps, data_kbps,
                                 controller_type=0, controller_mode=0,
                                 install_term_resistor_120ohm=False):
        """配置 CAN FD 仲裁段 / 数据段波特率"""
        return self._check(
            self.app.configure_canfd_baudrate(
                chn, float(arb_kbps), float(data_kbps),
                int(controller_type), int(controller_mode),
                bool(install_term_resistor_120ohm),
            ),
            f"configure_canfd_baudrate(chn={chn}, {arb_kbps}/{data_kbps}kbps)",
        )

    # ------------------------------------------------------------------
    # 硬件映射
    # ------------------------------------------------------------------

    def set_mapping(self, chn_index, hw_name, hw_type, hw_sub_type,
                    hw_index, hw_channel_index, enabled=True, app_name="TSMaster"):
        """建立应用 CAN 通道 → 硬件通道映射（app_channel_type 固定为 CAN）"""
        app_can = int(getattr(self.ts, "APP_CAN", 0))
        return self._check(
            self.app.set_mapping(
                app_name, app_can, int(chn_index),
                hw_name, int(hw_type), int(hw_sub_type),
                int(hw_index), int(hw_channel_index), bool(enabled),
            ),
            f"set_mapping(chn={chn_index}, hw={hw_name})",
        )

    # ------------------------------------------------------------------
    # 帧构造与发送
    # ------------------------------------------------------------------

    def make_can_frame(self, frame_id, data, chn=0, is_ext=False, is_fd=False):
        """构造一个 RawCAN 帧对象（data 为字节列表）"""
        can = self.ts.RawCAN()
        if is_ext:
            can.init_w_ext_id(int(frame_id), len(data))
        else:
            can.init_w_std_id(int(frame_id), len(data))
        can.idx_chn = int(chn)
        can.data = list(data)
        if is_fd:
            can.is_edl = True
        return can

    def transmit_can(self, can):
        """异步发送一帧 CAN（can 为 RawCAN 对象）"""
        return self._check(self.com.transmit_can_async(can), "transmit_can_async")

    def transmit_can_sync(self, can, timeout_ms=1000):
        """同步发送一帧 CAN"""
        return self._check(
            self.com.transmit_can_sync(can, int(timeout_ms)),
            "transmit_can_sync",
        )

    def add_cyclic_message(self, can, period_ms):
        """将一帧加入周期发送引擎"""
        return self._check(
            self.com.add_cyclic_message_can(can, float(period_ms)),
            f"add_cyclic_message(id=0x{can.id:X}, {period_ms}ms)",
        )

    def del_cyclic_messages(self):
        """清除所有周期帧"""
        return self._check(self.com.del_cyclic_messages(), "del_cyclic_messages")

    # ------------------------------------------------------------------
    # 信号服务器（sgnsrv）
    # ------------------------------------------------------------------

    def register_can_signal(self, chn, msg_id, signal_name):
        """按报文 ID 注册 CAN 信号，返回 client_id（失败返回 -1）"""
        result = self.com.sgnsrv_register_can_signal_by_msg_identifier(
            int(chn), int(msg_id), signal_name
        )
        try:
            code, client_id = int(result[0]), int(result[1])
        except (TypeError, IndexError, ValueError):
            # 某些版本直接返回 client_id
            code, client_id = 0, int(result)
        if code != 0:
            logger.error(
                f"[TSMaster] register_can_signal(0x{int(msg_id):X}, {signal_name}) "
                f"失败 (code={code})"
            )
            return -1
        return client_id

    def get_can_signal_value(self, chn, client_id):
        """取 CAN 信号最新物理值，返回 (value, timestamp_us)"""
        result, value, timestamp_us = self.com.sgnsrv_get_can_signal_phy_value_latest(
            int(chn), int(client_id)
        )
        if result != 0:
            logger.error(
                f"[TSMaster] get_can_signal_value(client_id={client_id}) "
                f"失败 (code={result})"
            )
        return value, timestamp_us

    # ------------------------------------------------------------------
    # RBS 剩余总线仿真
    # ------------------------------------------------------------------

    def rbs_start(self):
        return self._check(self.com.can_rbs_start(), "can_rbs_start")

    def rbs_stop(self):
        return self._check(self.com.can_rbs_stop(), "can_rbs_stop")

    def rbs_enable(self, enable):
        return self._check(self.com.can_rbs_enable(bool(enable)), "can_rbs_enable")

    def rbs_configure(self, auto_start=True, auto_send_on_modification=True,
                      activate_node_simulation=True, init_value_options=0):
        return self._check(
            self.com.can_rbs_configure(
                bool(auto_start), bool(auto_send_on_modification),
                bool(activate_node_simulation), int(init_value_options),
            ),
            "can_rbs_configure",
        )

    def rbs_activate_message(self, chn, network, node, message, enable=True,
                             include_children=True):
        """按名激活 / 去激活 RBS 报文"""
        return self._check(
            self.com.can_rbs_activate_message_by_name(
                int(chn), bool(enable), network, node, message
            ),
            f"can_rbs_activate_message({message})",
        )

    def rbs_set_signal_by_address(self, address, value):
        """按符号地址写 RBS 信号物理值"""
        return self._check(
            self.com.can_rbs_set_signal_value_by_address(address, float(value)),
            f"can_rbs_set_signal({address})",
        )

    def rbs_get_signal_by_address(self, address):
        """按符号地址读 RBS 信号物理值，返回 (value,)"""
        result, value = self.com.can_rbs_get_signal_value_by_address(address)
        if result != 0:
            logger.error(f"[TSMaster] rbs_get_signal({address}) 失败 (code={result})")
        return value

    def rbs_batch_set_start(self):
        return self._check(self.com.can_rbs_batch_set_start(), "can_rbs_batch_set_start")

    def rbs_batch_set_end(self):
        return self._check(self.com.can_rbs_batch_set_end(), "can_rbs_batch_set_end")

    # ------------------------------------------------------------------
    # 总线统计 / 性能
    # ------------------------------------------------------------------

    def enable_bus_statistics(self, enable=True):
        return self._check(
            self.com.enable_bus_statistics(bool(enable)), "enable_bus_statistics"
        )

    def clear_bus_statistics(self):
        return self._check(self.com.clear_bus_statistics(), "clear_bus_statistics")

    def get_bus_statistics(self, chn, stat_idx=0, bus_type=None):
        """取总线统计值（stat_idx 默认 0 = 总线负载），返回 (value,)"""
        if bus_type is None:
            bus_type = int(getattr(self.ts, "APP_CAN", 0))
        result, value = self.com.get_bus_statistics(int(bus_type), int(chn), int(stat_idx))
        if result != 0:
            logger.error(f"[TSMaster] get_bus_statistics 失败 (code={result})")
        return value

    def get_bus_load(self, chn):
        """取 CAN 总线负载（%）"""
        load_idx = int(getattr(self.ts, "CAN_STAT_BUS_LOAD", 0))
        return self.get_bus_statistics(chn, stat_idx=load_idx)

    def get_fps(self, chn, identifier):
        """取指定 ID 的每秒帧数（FPS），需先 enable_bus_statistics"""
        result = self.com.get_fps_can(int(chn), int(identifier))
        try:
            code, fps = int(result[0]), int(result[1])
        except (TypeError, IndexError, ValueError):
            code, fps = 0, int(result)
        if code != 0:
            logger.error(
                f"[TSMaster] get_fps(0x{int(identifier):X}) 失败 (code={code})"
            )
        return fps

    # ------------------------------------------------------------------
    # 上下文管理器
    # ------------------------------------------------------------------

    def __enter__(self):
        if not self.is_connected and not self.connect():
            raise ConnectionError("无法连接 TSMaster 应用")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def __del__(self):
        try:
            if self.is_connected:
                self.disconnect()
        except Exception:
            pass
