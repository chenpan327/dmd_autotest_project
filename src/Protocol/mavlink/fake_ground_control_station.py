import socket

from .parse_mavlink import MAVLink_message
from utils.logger import logger


gcs_ip = "172.16.200.1"
drone_ip = "172.17.3.176"


class GroundControlStation:
    def __init__(self, local_ip=gcs_ip, local_port=14550,
                 drone_ip=drone_ip, drone_port=14551,
                 recv_timeout=1.0):
        self.local_ip = local_ip
        self.local_port = local_port
        self.drone_ip = drone_ip
        self.drone_port = drone_port
        self.recv_timeout = recv_timeout

        self.sock = None
        self.udp_connected = False
        self.discovered_drones = set()

        self._udp_setup()

    # ------------------------------------------------------------------
    # UDP 通讯
    # ------------------------------------------------------------------
    def _udp_setup(self):
        """创建并绑定 UDP 套接字"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.local_ip, self.local_port))
        self.sock.settimeout(self.recv_timeout)
        self.udp_connected = True
        logger.info(f"UDP 套接字已绑定到 {self.local_ip}:{self.local_port}")
        logger.info(f"目标无人机: {self.drone_ip}:{self.drone_port}")

    def close(self):
        """关闭 UDP 通讯"""
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.udp_connected = False
        logger.info("GroundControlStation UDP 通讯已关闭。")

    # ------------------------------------------------------------------
    # 无人机发现
    # ------------------------------------------------------------------
    def discover_drones(self, timeout=5.0):
        """自动发现广播心血的无人机IP

        Args:
            timeout: 发现超时时间（秒）

        Returns:
            discovered_drones 集合
        """
        logger.info(f"开始发现无人机，超时 {timeout}s...")
        self.sock.settimeout(0.5)
        start = __import__('time').time()

        while __import__('time').time() - start < timeout:
            try:
                data, addr = self.sock.recvfrom(4096)
                if data and len(data) > 6:
                    msg = MAVLink_message(hex_data=data.hex())
                    if msg.msg_id == 0:
                        drone_addr = (addr[0], self.drone_port)
                        self.discovered_drones.add(addr[0])
                        logger.info(f"发现无人机: {addr[0]}:{addr[1]}")
            except socket.timeout:
                continue
            except Exception:
                continue

        self.sock.settimeout(self.recv_timeout)
        logger.info(f"发现完成，已发现 {len(self.discovered_drones)} 架无人机: {self.discovered_drones}")
        return self.discovered_drones

    def is_drone_discovered(self, ip=None):
        """检查无人机是否已发现

        Args:
            ip: 无人机 IP，省略则使用默认 drone_ip

        Returns:
            bool
        """
        if ip is None:
            ip = self.drone_ip
        return ip in self.discovered_drones

    # ------------------------------------------------------------------
    # MAVLink 收发
    # ------------------------------------------------------------------
    def _get_best_target(self) -> tuple:
        """获取最佳目标地址：优先使用已发现的无人机 IP，否则用配置默认值"""
        if self.discovered_drones:
            # 取第一个发现的无人机，端口使用 drone_port
            ip = next(iter(self.discovered_drones))
            return (ip, self.drone_port)
        return (self.drone_ip, self.drone_port)

    def send(self, message: MAVLink_message, addr=None) -> bool:
        """向无人机发送一条 MAVLink 消息

        Args:
            message: 待发送的 MAVLink_message 实例
            addr: 目标 (ip, port)，省略则自动选择最佳目标

        Returns:
            发送成功返回 True，否则 False
        """
        if not self.udp_connected or self.sock is None:
            logger.warning("UDP 未连接，无法发送数据。")
            return False

        if addr is None:
            addr = self._get_best_target()

        # 检查目标 IP 是否在已发现无人机列表中
        if addr[0] not in self.discovered_drones:
            logger.warning(f"目标无人机 {addr[0]} 未被发现，可能无法接收消息")

        try:
            data = message.pack()
            self.sock.sendto(data, addr)
            return True
        except Exception as e:
            logger.error(f"发送数据失败: {e}")
            return False

    def wait_for_message(self, msg_ids, timeout=5.0):
        """等待指定 msg_id 的消息，使用短 socket timeout 高频轮询

        Args:
            msg_ids: 期望接收的 msg_id 列表，如 [0] 或 [5, 8]
            timeout: 总等待超时（秒）

        Returns:
            (MAVLink_message, addr) 元组；超时返回 (None, None)
        """
        import time as _time

        old_timeout = self.recv_timeout
        self.sock.settimeout(0.1)
        start = _time.time()

        try:
            while _time.time() - start < timeout:
                msg, addr = self.receive()
                if msg is not None:
                    if msg.msg_id in msg_ids:
                        return msg, addr
                _time.sleep(0.01)
            return None, None
        finally:
            self.recv_timeout = old_timeout
            self.sock.settimeout(old_timeout)

    def receive(self, bufsize: int = 4096):
        """接收并解析一条 MAVLink 消息

        Returns:
            (MAVLink_message, addr) 元组；超时返回 (None, None)
        """
        if not self.udp_connected or self.sock is None:
            return None, None

        try:
            data, addr = self.sock.recvfrom(bufsize)
        except socket.timeout:
            return None, None
        except ConnectionResetError:
            # Windows UDP: sendto 后对方端口不可达，ICMP 映射为 10054
            return None, None
        except Exception as e:
            logger.error(f"接收数据失败: {e}")
            return None, None

        try:
            message = MAVLink_message(hex_data=data.hex())
            logger.info(f"接收到来自 {addr} 的消息: {message}")
            # 任何有效的 MAVLink 消息都证明该 IP 存在无人机
            self.discovered_drones.add(addr[0])
            return message, addr
        except Exception as e:
            logger.error(f"解析 MAVLink 消息失败: {e}")
            return None, None


if __name__ == "__main__":
    gcs = GroundControlStation()

    try:
        # 先发现无人机
        gcs.discover_drones(timeout=5.0)

        while True:
            msg, addr = gcs.receive()
            if msg is None:
                continue
            logger.info(f"接收到来自 {addr} 的消息: {msg}")
    except KeyboardInterrupt:
        logger.info("正在停止 GroundControlStation...")
        gcs.close()
        logger.info("GroundControlStation 已完全停止。")