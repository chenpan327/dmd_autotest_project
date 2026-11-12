# coding: utf-8
"""
简化版串口协议层代码
- 去除冗余功能，保留核心串口通信逻辑
- 简化代码结构，减少不必要的 log 打印
- 删除所有重试修饰器
"""
import re
import time
from typing import Union, Dict, Optional, Any, List

from utils.logger import logger
from src.Physical.Serial.SerialPortController import SerialPortController


class ProtocolHandler(SerialPortController):
    """简化版协议处理类 - 继承 SerialPortController，封装核心协议相关的发送和接收逻辑"""

    # 基础常量
    DEFAULT_TIMEOUT = 10
    ACK_MARKER = "ACK"
    PROMPT_MARKER = "~dmd_uav~@:"

    def __init__(self, port=None, baudrate=115200, timeout=0.5):
        """初始化协议处理器"""
        super().__init__(port=port, baudrate=baudrate, timeout=timeout,
                         enable_count=False, enable_queue=False)

    def send_command(self, cmd: str, add_newline: bool = True,
                     wait_response: bool = True, timeout: float = None,
                     check_ack: bool = True) -> Optional[str]:
        """
        发送串口命令并获取响应

        Args:
            cmd: 命令字符串
            add_newline: 是否添加换行符
            wait_response: 是否等待响应
            timeout: 超时时间（秒）
            check_ack: 是否检查 ACK 应答，默认开启

        Returns:
            响应字符串，失败返回 None
        """
        if timeout is None:
            timeout = self.DEFAULT_TIMEOUT

        if not self.is_connected:
            return None

        try:
            # 清空缓冲区 - 多次清理确保无残留数据
            self.clear_buffer()
            time.sleep(0.05)
            self.clear_buffer()

            # 同步设备提示符：发送换行唤醒设备，等待提示符出现
            # 处理设备可能处于交互模式或持续发送数据的状态
            self._sync_prompt(timeout=1.0)

            # sync_prompt 发送的 q 可能触发 NAK 响应，消纳残留数据
            self.clear_buffer()
            self._drain_buffer(timeout=0.5)
            self.clear_buffer()

            # 构建命令
            send_cmd = cmd.rstrip('\r\n')
            if add_newline:
                send_cmd += "\r\n"

            # 发送命令
            success = self.send_data(send_cmd)
            if not success:
                return None

            if not wait_response:
                return None

            logger.info(f"[ProtocolHandler] 发送命令: {send_cmd.strip()}，等待响应...")
            # 读取响应
            full_response = ""
            start_time = time.time()
            last_data_time = start_time

            while (time.time() - start_time) < timeout:
                data = self.read_data(timeout=0.1)
                if data:
                    try:
                        decoded = data.decode('utf-8', errors='ignore')
                        full_response += decoded
                        last_data_time = time.time()
                    except Exception:
                        pass

                # 检查响应是否完整
                if full_response and self._is_response_complete(full_response):
                    break

                # 空闲超时判断（固件处理 IP/SSID 等命令可能需要 1-2 秒）
                idle_time = time.time() - last_data_time
                if idle_time > 2.0:
                    break

            logger.info(f"[ProtocolHandler] 接收响应: {full_response.strip()}")

            if not full_response:
                return None

            # 归一化换行符：将 \r\n 和单独的 \r 统一为 \n
            full_response = full_response.replace('\r\n', '\n').replace('\r', '\n')

            # 检查 ACK 应答
            if check_ack and not self._has_ack(full_response):
                logger.warning(f"[ProtocolHandler] 命令 {cmd.strip()} 未收到 ACK 应答")
                return None

            return full_response.strip()

        except Exception as e:
            logger.error(f"[ProtocolHandler] 发送命令 {cmd.strip()} 异常: {e}")
            return None

    def _sync_prompt(self, timeout: float = 1.0) -> None:
        """
        同步设备提示符：确保设备退出交互模式并处于命令就绪状态

        被动优先策略：
        1. 先读取看是否有数据流入（设备在交互模式持续发送数据）
        2. 若有数据流入，说明在交互模式，发送 q 退出
        3. 若无数据流入，说明在提示符就绪，发送换行验证

        Args:
            timeout: 每阶段最大等待时间（秒）
        """
        def _has_prompt(text: str) -> bool:
            if self.PROMPT_MARKER in text:
                return True
            # WiFi 模块 shell 提示符
            if re.search(r'(?:^|\n)\$ ?\r?\n', text, re.MULTILINE):
                return True
            return False

        try:
            # 阶段1：被动检测 — 不发送任何东西，先看有没有数据流入
            has_data = False
            has_prompt = False
            start_time = time.time()

            while (time.time() - start_time) < 0.3:
                data = self.read_data(timeout=0.1)
                if data:
                    has_data = True
                    try:
                        decoded = data.decode('utf-8', errors='ignore')
                        if _has_prompt(decoded):
                            has_prompt = True
                    except Exception:
                        pass

            # 阶段2：有数据但没提示符 → 设备在交互模式，发送 q 退出
            if has_data and not has_prompt:
                self.send_data("q\r\n")
                start_time = time.time()
                while (time.time() - start_time) < timeout:
                    data = self.read_data(timeout=0.1)
                    if data:
                        try:
                            decoded = data.decode('utf-8', errors='ignore')
                            if _has_prompt(decoded):
                                break
                        except Exception:
                            pass
                return

            # 阶段3：无数据流入 → 发送换行唤醒，验证提示符存在
            self.send_data("\r\n")
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                data = self.read_data(timeout=0.1)
                if data:
                    try:
                        decoded = data.decode('utf-8', errors='ignore')
                        if _has_prompt(decoded):
                            break
                    except Exception:
                        pass

        except Exception:
            pass

    def _exec_cmd(self, cmd: str, timeout: float = None, parser=None) -> Any:
        """
        通用命令执行器，统一 try/except/日志 模式

        Args:
            cmd: 命令字符串
            timeout: 超时时间（秒）
            parser: 响应解析函数，接收原始响应字符串，返回解析结果

        Returns:
            解析结果（如果有 parser）或 bool（命令是否成功），失败返回 None
        """
        try:
            raw_response = self.send_command(cmd, timeout=timeout or self.DEFAULT_TIMEOUT)
            if raw_response is None:
                logger.warning(f"[ProtocolHandler] 命令 {cmd} 无响应")
                return None
            response_str = self._parse_response_to_string(raw_response)
            if parser:
                return parser(response_str)
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 命令 {cmd} 执行失败: {e}")
            return None

    def _is_response_complete(self, response: str) -> bool:
        """
        判断响应是否完整（提示符出现在响应末尾表示命令执行完毕）

        注意：不能用简单的 `in` 检测，因为残留数据（sync_prompt 的 q/NAK）
        可能在真正的命令响应之前就包含提示符。只有提示符在末尾时
        才说明命令响应已完整送达。

        Args:
            response: 响应字符串

        Returns:
            响应是否完整
        """
        stripped = response.rstrip()
        # V4/V3 固件提示符
        if stripped.endswith(self.PROMPT_MARKER):
            return True
        # WiFi 模块 shell 提示符
        if stripped.endswith('$') or stripped.endswith('$ '):
            return True
        return False

    def _drain_buffer(self, timeout: float = 0.3) -> None:
        """
        消纳串口缓冲区中的残留数据（sync_prompt 后的 q/NAK 等）

        持续读取直到超时，不因短暂空闲而提前退出。

        Args:
            timeout: 最大读取时间（秒）
        """
        try:
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                self.read_data(timeout=0.05)
        except Exception:
            pass

    def _has_ack(self, response: str) -> bool:
        """
        检查响应是否包含 ACK 应答标记

        固件在收到命令后会统一回复 ACK 应答，
        用于确认命令已被正确接收和执行。

        WiFi 模块使用 Linux shell 提示符 $ 表示命令执行完成，
        不发送独立的 ACK 行。

        MTK 固件 minicli 串口输出含 \\x00 字节，
        会出现在 $ 提示符之前，干扰正则匹配。

        Args:
            response: 响应字符串

        Returns:
            包含 ACK 或 shell 提示符返回 True
        """
        if not response:
            return False
        # MTK 固件输出含 null 字节，先清理再匹配
        clean = response.replace('\x00', '')
        # V4/V3 固件：ACK 在命令回显后、响应数据前独占一行
        if re.search(r'(?:^|\n)ACK\r?\n', clean, re.MULTILINE):
            return True
        # WiFi 模块：shell 提示符 $ 独占一行（带换行）
        if re.search(r'(?:^|\n)\$ ?\r?\n', clean, re.MULTILINE):
            return True
        # $ 在响应末尾（_is_response_complete 可能提前截断 trailing 换行）
        stripped = clean.rstrip()
        if stripped.endswith('$') or stripped.endswith('$ '):
            return True
        return False

    def _parse_response_to_string(self, response: Union[bytes, str]) -> str:
        """将响应转换为字符串，去除固件发送的 null 字节、\\r 等控制字符"""
        if not response:
            return ""

        try:
            if isinstance(response, bytes):
                text = response.decode('utf-8', errors='ignore')
            else:
                text = str(response)
            # 固件串口响应常含 \x00 等控制字符，会破坏正则匹配
            text = text.replace('\x00', '')
            # 归一化换行符：\r\n 和单独的 \r 统一为 \n
            text = text.replace('\r\n', '\n').replace('\r', '\n')
            return text.strip()
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return ""

    # ==================== 查看当前目录下的文件和文件夹 ====================
    def list_directory(self) -> List[str]:
        """
        查看当前目录下的文件和文件夹

        Returns:
            文件和文件夹列表
        """
        try:
            raw_response = self.send_command("ls", timeout=2)
            if not raw_response:
                return []

            response_str = self._parse_response_to_string(raw_response)
            # 提取文件和文件夹列表
            # 响应格式：SIZE\tNAME\n0\tdata/\n0\tdev/\n...
            # 匹配数字后跟空白字符（空格或制表符）再跟文件/目录名的格式
            pattern = r"\d+\s+(\S+)"
            
            items = []
            matches = re.findall(pattern, response_str)
            if matches:
                for match in matches:
                    items.append(match.strip())
            
            logger.info(f"[ProtocolHandler] 当前目录下的文件和文件夹: {items}")
            return items

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return []
    
    # ==================== 跳转到某个文件夹下 ====================
    def change_directory(self, directory: str) -> bool:
        """
        跳转到某个文件夹下

        Args:
            directory: 目标文件夹名称

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"cd {directory}", timeout=2)
            if not response:
                return False

            response_lower = response.lower()
            error_keywords = "no such directory"

            if error_keywords in response_lower:
                return False

            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 参数名称及其对应的值 ====================
    def get_parameter(self, param_name: str) -> Optional[Dict[str, str]]:
        """
        获取参数名称及其对应的值

        Args:
            param_name: 参数名称

        Returns:
            参数字典 {参数名：参数值}，失败返回 None
        """
        try:
            if not param_name:
                # 获取所有参数
                raw_response = self.send_command("pp", timeout=3)
                if not raw_response:
                    return None
                response_str = self._parse_response_to_string(raw_response)
                # 解析所有参数：兼容 "NAME  :VALUE" 和 "NAME:VALUE" 两种格式
                pattern = r"(\w+)\s*:([\d.-]+)"
                result = {}
                matches = re.findall(pattern, response_str)
                for match in matches:
                    result[match[0]] = match[1]
                return result if result else None

            raw_response = self.send_command(f"pp {param_name}", timeout=2)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)

            # 兼容 "NAME:VALUE" 和 "NAME  :VALUE" 两种格式
            pattern = r"(\w+)\s*:([\d.-]+)"
            match = re.search(pattern, response_str)
            if match:
                name = match.group(1)
                value = match.group(2)
                return {name: value}
            return None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None
    
    # ==================== 模块运行任务信息 ====================
    def get_task_info(self) -> Optional[str]:
        """
        获取模块运行任务信息

        Returns:
            任务信息字符串，失败返回 None
        """
        try:
            raw_response = self.send_command("pm", timeout=2)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)
            
            return response_str
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None
        
    # ==================== 获取错误信息 ====================
    def get_error_info(self) -> Optional[str]:
        """
        获取错误信息

        Returns:
            错误信息字符串，失败返回 None
        """
        try:
            raw_response = self.send_command("dmsg", timeout=2)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)
            
            return response_str
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None
        
    def get_error_info_clear(self) -> Optional[str]:
        """
        获取错误信息并清除

        Returns:
            错误信息字符串，失败返回 None
        """
        try:
            raw_response = self.send_command("dmsg c", timeout=2)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)
            
            return response_str
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 获取飞控系统各模块初始化状态 ====================
    def get_module_init_status(self) -> Optional[Dict[str, str]]:
        """
        获取飞控系统各模块初始化状态

        Returns:
            包含各模块初始化状态的字典，失败返回 None
        """
        try:
            raw_response = self.send_command("istate", timeout=2)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)

            # 响应格式：module:1 sdcard:1 param:1 ...
            pattern = r"(\w+):(\d+)"
            matches = re.findall(pattern, response_str)
            if matches:
                return {match[0]: match[1] for match in matches}
            return None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 获取各个传感器的工作状态 ====================
    def get_sensor_work_status(self) -> Optional[Dict[str, str]]:
        """
        获取各个传感器的工作状态

        Returns:
            包含各传感器工作状态的字典，失败返回 None
        """
        try:
            raw_response = self.send_command("sheal", timeout=2)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)
            # 响应格式：module:1 sdcard:1 param:1 ...
            pattern = r"(\w+):(\d+)"
            matches = re.findall(pattern, response_str)
            if matches:
                return {match[0]: match[1] for match in matches}
            return None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 获取通信质量 ====================
    def get_communication_quality(self) -> Optional[str]:
        """
        获取通信质量

        Returns:
            通信质量信息字符串，失败返回 None
        """
        try:
            raw_response = self.send_command("mav", timeout=2)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)

            # 结束指令（q 退出交互模式无 ACK，跳过 ACK 检查）
            self.send_command("q", timeout=2, check_ack=False)
            return response_str
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 获取设备版本信息 ====================
    def get_device_version(self) -> Optional[Dict[str, Any]]:
        """
        获取设备版本信息

        Returns:
            包含 SN 和版本号的字典，失败返回 None
        """
        result = {"sn": None, "version": None, "full_info": ""}

        try:
            raw_response = self.send_command("version", timeout=2)
            if not raw_response:
                return result

            response_str = self._parse_response_to_string(raw_response)
            clean_response = re.sub(r'\[\d+:\d+:\d+\.\d+\]\w+←◆', '', response_str).strip()
            result["full_info"] = clean_response

            sn_match = re.search(r'sn[:=]\s*([^,]+)', clean_response, re.IGNORECASE)
            version_match = re.search(r'version[:=]\s*([^\n]+)', clean_response, re.IGNORECASE)

            if sn_match:
                result["sn"] = sn_match.group(1).strip()
            if version_match:
                result["version"] = version_match.group(1).strip()

            return result
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None
    
    # ==================== 系统时间和飞行时长 ====================
    def get_system_time(self) -> Dict[str, Any]:
        """
        获取系统时间

        Returns:
            包含系统时间的字典
        """
        result = {"Base Time": None, "Flight Time": None}

        try:
            response = self.send_command("now", timeout=2)
            result["response"] = response

            pattern = r"Base Time\s*:\s*(\d+)\s*Flight Time\s*:\s*(\d+)"
            match = re.search(pattern, response)
            if match:
                result["Base Time"] = int(match.group(1))
                result["Flight Time"] = int(match.group(2))

        except Exception:
            pass

        return result
    
    # ==================== 无人机的模式 ====================
    def set_mode(self, mode: str) -> bool:
        """
        设置飞行模式

        严格按固件源码回显校验(sys_cli_serv.cpp:1586-1607 cmd_func_mode):
            成功:
                - 固件静默返回,无正向打印。仅发布 UORB TP_MODE_REQ 后立即返回。
            失败:
                - "ERROR: incorrect mode name" + "Available modes are:"  仅当传 "?" 时打印
                - "cur mode: %d"  当 mode 名不匹配任何分支时,固件会 fall-through
                  到查询分支并打印当前模式。所以响应里出现 "cur mode:" 等同于模式名无效。

        Args:
            mode: 模式字符串 (stab, althold, loiter, guided, auto, land, rtl)

        Returns:
            成功返回 True
        """
        valid_modes = {
            "stab": "stab", "althold": "althold", "loiter": "loiter",
            "guided": "guided", "land": "land", "rtl": "rtl", "auto": "auto",
        }

        try:
            mode_clean = mode.strip().lower()
            if mode_clean not in valid_modes:
                return False

            mode_cmd = valid_modes[mode_clean]
            response = self.send_command(f"mode {mode_cmd}", timeout=2)
            if not response:
                return False
            response_lower = response.lower()
            # 命中失败标志 — 模式名无效或请求了帮助
            if "incorrect mode name" in response_lower:
                return False
            if "cur mode:" in response_lower:
                return False
            # 成功路径:固件静默,响应只剩 CLI 提示符等噪声。无失败标志即成功。
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
    
    def get_current_mode(self) -> Dict[str, Any]:
        """
        获取当前飞行模式

        Returns:
            包含当前模式信息的字典
        """
        result = {"mode": None, "mode_id": None}

        MODE_STAB    = 0
        MODE_ACRO    = 1
        MODE_ALTHOLD = 2
        MODE_AUTO    = 3
        MODE_GUIDED  = 4
        MODE_LOITER  = 5
        MODE_RTL     = 6
        UMODE_CIRCLE  = 7
        MODE_UNKNOW  = 8
        MODE_LAND    = 9
        MODE_CL      = 20
        MODE_NULL    = 255

        try:
            raw_response = self.send_command("mode", timeout=2)

            if not raw_response:
                return result

            response_str = self._parse_response_to_string(raw_response)

            # 响应格式可能是：cur mode: 5 或 mode:5 或 MODE:5
            pattern = r"(?:cur )?mode[:\s]+(\d+)"
            match = re.search(pattern, response_str, re.IGNORECASE)
            if match:
                mode_id = int(match.group(1))
                result["mode_id"] = mode_id

                mode_map = {
                    MODE_STAB: "stab",
                    MODE_ACRO: "acro",
                    MODE_ALTHOLD: "althold",
                    MODE_AUTO: "auto",
                    MODE_GUIDED: "guided",
                    MODE_LOITER: "loiter",
                    MODE_RTL: "rtl",
                    UMODE_CIRCLE: "circle",
                    MODE_UNKNOW: "unknown",
                    MODE_LAND: "land",
                    MODE_CL: "cl",
                    MODE_NULL: "null"
                }
                result["mode"] = mode_map.get(mode_id, f"unknown_mode_{mode_id}")

        except Exception:
            pass

        return result
    
    def get_available_mode(self) -> Dict[str, Any]:
        """
        获取可用飞行模式

        Returns:
            包含当前模式信息的字典
        """
        result = {"modes": []}

        try:
            raw_response = self.send_command("mode ?", timeout=2)
            if not raw_response:
                return result

            response_str = self._parse_response_to_string(raw_response)

            # 响应格式可能是多行模式列表，用空格或换行分隔
            # 提取所有单词作为模式
            modes = re.findall(r'\b(stab|acro|althold|auto|guided|loiter|rtl|circle|land|cl)\b', response_str, re.IGNORECASE)
            if modes:
                result["modes"] = [m.lower() for m in modes]

        except Exception:
            pass

        return result

    # ==================== 起飞命令 ====================
    def takeoff(self) -> bool:
        """
        起飞命令

        严格按固件源码回显校验(sys_cli_serv.cpp:1609-1657 cmd_func_takeoff):
            成功:
                - 固件静默返回,仅发布 UORB TP_ACTION_REQ。
            失败:
                - "ERROR: Param number error!!!"  仅在带参数且个数非 1 或 4 时打印
                  (无参调用不会触发,但保留校验防御 future regression)

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command("takeoff", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            if "param number error!!!" in response_lower:
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def takeoff_position(self, x: float, y: float, z: float, altitude: float = 10.0) -> bool:
        """
        在指定位置起飞

        严格按固件源码回显校验(sys_cli_serv.cpp:1609-1657 cmd_func_takeoff):
            成功:
                - 固件静默返回,仅发布 UORB TP_ACTION_REQ。
            失败:
                - "ERROR: Param number error!!!"  参数个数非 4 时打印

        Args:
            x: X 坐标
            y: Y 坐标
            z: Z 坐标
            altitude: 起飞高度（米）

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"takeoff {x}, {y}, {z}, {altitude}", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            if "param number error!!!" in response_lower:
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def takeoff_altitude(self, altitude: float = 10.0) -> bool:
        """
        指定高度起飞

        严格按固件源码回显校验(sys_cli_serv.cpp:1609-1657 cmd_func_takeoff):
            成功:
                - 固件静默返回,仅发布 UORB TP_ACTION_REQ。
            失败:
                - "ERROR: Param number error!!!"  参数个数非 1 时打印

        Args:
            altitude: 起飞高度（米）

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"takeoff {altitude}", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            if "param number error!!!" in response_lower:
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
    
    # ==================== 舵机命令 ====================
    def set_servo(self, channel1: int, channel2: int, channel3: int) -> bool:
        """
        设置舵机 PWM 值

        严格按固件源码回显校验(sys_cli_serv.cpp:243-286 cmd_func_servo):
            失败:
                - "Param num err!!!"            sys_cli_serv.cpp:267(注意是 "num" + 3 个感叹号)
                - "servo_value exceed, valid:0~255"  sys_cli_serv.cpp:274 值超范围
            成功:
                - 固件静默返回,无正向打印。仅能确认无失败标志 + 非空响应。

        Args:
            channel1: 舵机通道1（0-255）
            channel2: 舵机通道2（0-255）
            channel3: 舵机通道3（0-255）
        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"servo {channel1}, {channel2}, {channel3}", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            if "param num err!!!" in response_lower:
                return False
            if "servo_value exceed, valid:0~255" in response_lower:
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 表演命令 ====================
    def perform_action(self) -> bool:
        """
        执行表演动作(fstart)

        严格按固件源码回显校验(sys_cli_serv.cpp:235-241 cmd_func_fstart):
            成功:
                - "flight start"  sys_cli_serv.cpp:240 task_info 无条件打印
            失败:
                - 无失败分支(固件不验证 publish 结果)。

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"fstart", timeout=5)
            if not response:
                return False
            return "flight start" in response.lower()
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 指示灯命令 ====================
    def set_led_on(self) -> bool:
        """
        设置指示灯开启(notify on)

        固件源码回显说明(sys_cli_serv.cpp:226-233 cmd_func_notify):
            固件在 on/off/无效参数 三种情况下都完全静默,
            只写 GLB_VAR::notify_state,不向 CLI 输出任何字符。
            所以响应里没有任何成功/失败标志可供匹配,本方法只能验证命令已发出
            并收到非空响应(至少包含 CLI 回显)。

        Returns:
            命令发送并收到响应返回 True;通信异常返回 False
        """
        try:
            response = self.send_command(f"notify on", timeout=5)
            return bool(response)
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def set_led_off(self) -> bool:
        """
        设置指示灯关闭(notify off)

        固件源码回显说明(sys_cli_serv.cpp:226-233 cmd_func_notify):
            固件在 on/off/无效参数 三种情况下都完全静默,
            只写 GLB_VAR::notify_state,不向 CLI 输出任何字符。
            所以响应里没有任何成功/失败标志可供匹配,本方法只能验证命令已发出
            并收到非空响应(至少包含 CLI 回显)。

        Returns:
            命令发送并收到响应返回 True;通信异常返回 False
        """
        try:
            response = self.send_command(f"notify off", timeout=5)
            return bool(response)
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def notify_flash(self, param: int) -> bool:
        """
        发送 notify_flash 命令控制指示灯

        指示灯枚举 0-87，分段：
        - 0-73  → 指示灯（Indicator LEDs）
        - 74-87 → 表演灯（Performance LEDs）
        - 88    → 恢复正常状态（解除强制覆盖）

        互斥规则：指示灯和表演灯互斥，设置一方另一方自动恢复为正常模式。
        注意：设置后每 100ms 会被固件强制覆盖，需手动 notify_flash 88 恢复正常。

        Args:
            param: 灯语参数（0-88）

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"notify_flash {param}", timeout=5)
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 飞行命令 ====================
    def fly_to(self, latitude: float, longitude: float, altitude: float) -> bool:
        """
        飞行到指定位置

        Args:
            latitude: 纬度
            longitude: 经度
            altitude: 高度（米）

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"flyto {latitude},{longitude},{altitude}", timeout=5)
            
            if "Param number error!!!" in response:
                return False
            
            if response:
                response_lower = response.lower()
                return "ok" in response_lower or "flying to" in response_lower
            return False
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 设置返航点命令 ====================
    def set_home(self, latitude: float, longitude: float) -> bool:
        """
        设置返航点

        Args:
            latitude: 纬度
            longitude: 经度

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"home {latitude} {longitude}", timeout=5)

            if "Param number error!!!" in response:
                return False

            logger.info(f"[ProtocolHandler] 设置返航点响应: {response}")
            match = re.search(r'\((.*?)\)', response)
            if match:
                coordinates = [float(coord.strip()) for coord in match.group(1).split(',')]
                return coordinates[0] == latitude and coordinates[1] == longitude
            return False
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
    
    # ==================== 设置电子围栏命令 ====================
    def set_geofence(self, x: float, y: float, radius: float, height: float) -> bool:
        """
        设置电子围栏

        严格按固件源码回显校验(sys_cli_serv.cpp:174-224 cmd_func_setfence):
            成功:
                - "Fence origin:"  sys_cli_serv.cpp:208/222
                  格式 "Fence origin:(%f, %f), radius:%f, height:%f\n"
            失败:
                - "Param number error!!!"  sys_cli_serv.cpp:179/194
                  (注意是 "number" 不是 "num",3 个感叹号;固件原文就这么写)

        Args:
            x: 中心点 x 坐标
            y: 中心点 y 坐标
            radius: 半径（米）
            height: 高度（米）

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"fence {x}, {y}, {radius}, {height}", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            logger.info(f"[WiFi-Protocol] set_geofence 响应: {response_lower[:200]}")
            # 失败优先 — 参数个数错误(固件原文)
            if "param number error!!!" in response_lower:
                return False
            # 成功标志 — Fence origin:(...) 字符串
            return "fence origin:" in response_lower
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 解锁命令 ====================
    def arm_motors(self) -> bool:
        """
        解锁电机(arm)

        固件源码回显说明(sys_cli_serv.cpp:1696-1702 cmd_func_arm):
            固件仅发布 UORB TP_ARM_REQ,不向 CLI 输出任何字符
            (无论解锁成功或被飞控拒绝都静默)。
            所以响应里没有任何成功/失败标志可供匹配,本方法只能验证命令已发出
            并收到非空响应(至少包含 CLI 回显)。

        Returns:
            命令发送并收到响应返回 True;通信异常返回 False
        """
        try:
            response = self.send_command("arm", timeout=3)
            return bool(response)
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 上锁命令 ====================
    def disarm_motors(self) -> bool:
        """
        锁定电机(disarm)

        固件源码回显说明(sys_cli_serv.cpp:1704-1710 cmd_func_disarm):
            固件仅发布 UORB TP_ARM_REQ,不向 CLI 输出任何字符
            (无论上锁成功或被飞控拒绝都静默)。
            所以响应里没有任何成功/失败标志可供匹配,本方法只能验证命令已发出
            并收到非空响应(至少包含 CLI 回显)。

        Returns:
            命令发送并收到响应返回 True;通信异常返回 False
        """
        try:
            response = self.send_command("disarm", timeout=3)
            return bool(response)
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 设置内存调试信息 ====================
    def set_memory_debug(self) -> bool:
        """
        打印 syslog 缓冲区(smsg)

        固件源码回显说明(sys_cli_serv.cpp:1267-1298 cmd_func_smsg):
            无参数调用时,固件用 printd 循环输出整个 syslog 缓冲区内容。
            缓冲区空时输出空字符序列,非空时输出实际日志。
            无显式成功/失败标志,本方法只能验证命令已发出并收到响应。

        Returns:
            命令发送并收到响应返回 True;通信异常返回 False
        """
        try:
            response = self.send_command("smsg", timeout=3)
            return bool(response)
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def set_memory_debug_off(self) -> bool:
        """
        清空 syslog 缓冲区(smsg c)

        固件源码回显说明(sys_cli_serv.cpp:1274-1277 cmd_func_smsg):
            para == "c" 时,固件 memset 清零 syslog 缓冲区后立即 return,
            不向 CLI 输出任何字符。无显式成功/失败标志,
            本方法只能验证命令已发出并收到响应。

        Returns:
            命令发送并收到响应返回 True;通信异常返回 False
        """
        try:
            response = self.send_command("smsg c", timeout=3)
            return bool(response)
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 获取 WiFi 信息 ====================
    def get_wifi_info(self) -> Optional[Dict[str, Any]]:
        """
        获取 WiFi 连接信息

        Returns:
            包含 WiFi 信息的字典，包括 MAC、SSID、BSSID、频段、信道、IP 等，失败返回 None
        """
        result = {
            "mac": None,
            "test_mode": None,
            "connect_status": None,
            "ssid": None,
            "bssid": None,
            "bss_index": None,
            "band": None,
            "channel": None,
            "bandwidth": None,
            "wlan_idx": None,
            "sta_idx": None,
            "ip_mode": None,
            "ip": None,
            "netmask": None,
            "gateway": None,
            "full_info": ""
        }

        try:
            raw_response = self.send_command("wifi info", timeout=3)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)
            result["full_info"] = response_str

            patterns = {
                "mac": r"mac:\s*([0-9a-fA-F:]{17})",
                "test_mode": r"Test Mode:\s*(\d+)",
                "connect_status": r"Connect Status:\s*(\w+)",
                "ssid": r"Ssid:\s*(\S+)",
                "bssid": r"BssId:\s*([0-9a-fA-F:]{17})",
                "bss_index": r"BssIndex:\s*(\d+)",
                "band": r"Band:\s*(\S+(?:\s*\([^)]+\))?)",
                "channel": r"CH:\s*(\d+)",
                "bandwidth": r"BW:\s*(\d+)",
                "wlan_idx": r"wlanIdx:\s*(\d+)",
                "sta_idx": r"staIdx:\s*(\d+)",
                "ip_mode": r"mode:\s*(\w+)",
                "ip": r"ip:\s*([\d.]+)",
                "netmask": r"netmask:\s*([\d.]+)",
                "gateway": r"gateway:\s*([\d.]+)"
            }

            for field, pattern in patterns.items():
                match = re.search(pattern, response_str)
                if match:
                    value = match.group(1)
                    if field in ["channel", "bss_index", "wlan_idx", "sta_idx", "bandwidth", "test_mode"]:
                        result[field] = int(value)
                    else:
                        result[field] = value

            return result if any(v is not None for k, v in result.items() if k != "full_info") else None

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 获取 IP 配置信息 ====================
    def get_ip_info(self) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        """
        获取所有网络接口的 IP 配置信息

        Returns:
            包含各接口 IP 信息的字典，格式为 {接口名: {mode, ip, netmask, gateway}}，失败返回 None
        """
        result = {}

        try:
            raw_response = self.send_command("ip", timeout=5)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)
            logger.info(f"[WiFi-Protocol] ip 响应: {response_str[:500]}")

            # 按接口分割响应：interface: xxx
            interface_pattern = r"interface:\s*(\w+)"
            interfaces = re.findall(interface_pattern, response_str)

            for iface in interfaces:
                # 提取该接口对应的内容块（兼容 \0 前缀和各种空白符）
                iface_block_pattern = rf"interface:\s*{re.escape(iface)}\s*mode:\s*(\w+).*?ip\s+([\d.]+).*?netmask\s+([\d.]+).*?gateway\s+([\d.]+)"
                match = re.search(iface_block_pattern, response_str, re.DOTALL)
                if match:
                    result[iface] = {
                        "mode": match.group(1),
                        "ip": match.group(2),
                        "netmask": match.group(3),
                        "gateway": match.group(4)
                    }

            return result if result else None

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 检查 WiFi 连接状态 ====================
    def check_wifi_connection(self) -> Optional[Dict[str, Any]]:
        """
        检查 WiFi 连接状态，获取信号强度和连接状态

        Returns:
            包含 rssi、quality 和 is_linked 的字典，失败返回 None
        """
        result = {
            "rssi": None,
            "quality": None,
            "is_linked": False
        }

        try:
            raw_response = self.send_command("dmdcicd checkWifi", timeout=5)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)
            logger.info(f"[WiFi-Protocol] checkWifi 响应: {response_str[:500]}")

            # 提取 RSSI 和 quality
            rssi_pattern = r"geted rssi\s*:\s*([-+]?\d+),\s*quality\s*:\s*(\d+)"
            rssi_match = re.search(rssi_pattern, response_str)
            if rssi_match:
                result["rssi"] = int(rssi_match.group(1))
                result["quality"] = int(rssi_match.group(2))

            # 检查连接状态（宽松匹配）
            response_lower = response_str.lower()
            if "linked" in response_lower and "wifi" in response_lower:
                result["is_linked"] = True
            elif "disconnect" in response_lower or "not linked" in response_lower:
                result["is_linked"] = False

            return result

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 获取系统任务信息 ====================
    def get_os_tasks(self) -> Optional[List[Dict[str, Any]]]:
        """
        获取系统所有任务的信息（任务名、状态、优先级、栈水位线、任务号）

        Returns:
            任务信息列表，每个元素包含 task_name、status、priority、stack_watermark、task_number，失败返回 None
        """
        result = []

        try:
            raw_response = self.send_command("os task", timeout=3)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)

            # 匹配任务行格式：任务名(空格)状态(空格)优先级(空格)栈水位线(空格)任务号
            # 例如：cli                	X	8	1836	2
            task_pattern = r"(\w[\w\s]*?\w)\s+([XRBST])\s+(\d+)\s+(\d+)\s+(\d+)"
            matches = re.findall(task_pattern, response_str)

            for match in matches:
                task_name = match[0].strip()
                # 过滤掉表头和无关行
                if task_name in ["parameter", "meaning", "pcTaskName", "cStatus", "uxCurrentPriority", "usStackHighWaterMark", "xTaskNumber"]:
                    continue
                if not task_name or len(task_name) < 2:
                    continue

                result.append({
                    "task_name": task_name,
                    "status": match[1],
                    "priority": int(match[2]),
                    "stack_watermark": int(match[3]),
                    "task_number": int(match[4])
                })

            return result if result else None

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== Ping 测试 ====================
    def ping(self, target_ip: str, count: int = 3) -> Optional[Dict[str, Any]]:
        """
        对指定 IP 执行 ping 测试

        Args:
            target_ip: 目标 IP 地址
            count: ping 次数（可选，实际由固件控制）

        Returns:
            包含 ping 结果的字典，包括 sent、received、lost、loss_percent、min_ms、max_ms、avg_ms，失败返回 None
        """
        result = {
            "target_ip": target_ip,
            "sent": None,
            "received": None,
            "lost": None,
            "loss_percent": None,
            "min_ms": None,
            "max_ms": None,
            "avg_ms": None
        }

        try:
            # 发送 ping 命令
            raw_response = self.send_command(f"ping  {target_ip}", timeout=20)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)
            logger.info(f"[WiFi-Protocol] ping 响应(第1段): {response_str[:500]}")

            # ping 输出是异步的，需要等待一段时间让结果缓冲
            # 实际 ping 结果在 ping_thread 日志行中，如:
            # [ping][I][ping_thread][419][ping]: 172.16.201.1, Packets: Sent = 3, Received =0, Lost = 3 (100% loss)
            import time
            time.sleep(8)

            # 再收集一次响应，捕获异步的 ping 输出
            raw_response2 = self.send_command("", timeout=5)
            if raw_response2:
                response_str2 = self._parse_response_to_string(raw_response2)
                logger.info(f"[WiFi-Protocol] ping 响应(第2段): {response_str2[:500]}")
                response_str = response_str + response_str2

            # 提取统计行：Packets: Sent = 3, Received =3, Lost = 0 (0% loss)
            stats_pattern = r"Packets:\s*Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+),\s*Lost\s*=\s*(\d+)\s*\((\d+)%\s*loss\)"
            stats_match = re.search(stats_pattern, response_str)
            if stats_match:
                result["sent"] = int(stats_match.group(1))
                result["received"] = int(stats_match.group(2))
                result["lost"] = int(stats_match.group(3))
                result["loss_percent"] = int(stats_match.group(4))

            # 提取延迟统计：min = 1, max =2, avg = 1
            delay_pattern = r"min\s*=\s*(\d+),\s*max\s*=\s*(\d+),\s*avg\s*=\s*(\d+)"
            delay_match = re.search(delay_pattern, response_str)
            if delay_match:
                result["min_ms"] = int(delay_match.group(1))
                result["max_ms"] = int(delay_match.group(2))
                result["avg_ms"] = int(delay_match.group(3))

            # 如果统计行未找到，尝试从单个 ping: recv 行解析
            if result["sent"] is None:
                recv_pattern = r"ping:\s*recv\s*seq\([^)]+\)\s*" + re.escape(target_ip) + r"\s*,\s*(\d+)\s*ms"
                recv_matches = re.findall(recv_pattern, response_str)
                if recv_matches:
                    result["received"] = len(recv_matches)
                    result["sent"] = result["received"]  # 假设收到=发送（WiFi 直连响应）
                    result["lost"] = 0
                    result["loss_percent"] = 0
                    times = [int(t) for t in recv_matches]
                    result["min_ms"] = min(times) if times else None
                    result["max_ms"] = max(times) if times else None
                    result["avg_ms"] = sum(times) // len(times) if times else None

            return result if result["sent"] is not None else None

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 获取 MAC 地址 ====================
    def get_mac_address(self, interface: str = "sta") -> Optional[str]:
        """
        获取指定接口的 MAC 地址

        Args:
            interface: 接口类型，"sta"（STA 模式）或 "ap"（AP 模式）

        Returns:
            MAC 地址字符串（如 "64:32:07:91:1e:70"），失败返回 None
        """
        try:
            raw_response = self.send_command(f"dmdcicd getMac       {interface}", timeout=3)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)

            # 提取格式：geted [sta] macAddr[64:32:07:91:1e:70]
            pattern = rf"geted\s+\[{interface}\]\s*macAddr\[([0-9a-fA-F:]+)\]"
            match = re.search(pattern, response_str)
            if match:
                return match.group(1)

            return None

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 设置 STA 休眠模式 ====================
    def set_sta_ps_mode(self, mode: int) -> bool:
        """
        设置 STA 休眠模式（Power Save Mode）

        Args:
            mode: 休眠模式值，0 表示不休眠，其他值表示开启休眠

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"config write STA PSMode {mode}", timeout=5)
            if not response:
                return False

            response_lower = response.lower()
            logger.info(f"[WiFi-Protocol] set_sta_ps_mode 响应: {response_lower[:200]}")
            return "write data item ok" in response_lower or "ok" in response_lower

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 修改 IP 配置 ====================
    def change_ip_config(self, ip: str, mask: Optional[str] = None, gateway: Optional[str] = None) -> Optional[Dict[str, str]]:
        """
        修改 STA 接口的 IP 地址（可选同时修改子网掩码和网关）

        Args:
            ip: 新的 IP 地址（如 "172.16.0.100"）
            mask: 子网掩码（可选，如 "255.240.0.0"）
            gateway: 网关地址（可选，如 "172.16.202.1"）

        Returns:
            包含 changed_ip、serial、code 的字典，失败返回 None
        """
        result = {
            "changed_ip": None,
            "serial": None,
            "code": None
        }

        try:
            # 构建命令：仅传 IP，或同时传 mask 和 gateway
            if mask and gateway:
                cmd = f"dmdcicd chgIp        {ip}  {mask}  {gateway}"
            else:
                cmd = f"dmdcicd chgIp        {ip}"

            # IP 配置变更可能需要较长时间生效，设置较长超时
            raw_response = self.send_command(cmd, timeout=15)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)

            # 提取变更确认：changed ipAddr[172.16.0.100] 或 ipAddr[172.16.0.100]
            ip_match = re.search(r"changed\s+ipAddr\[([0-9.]+)\]", response_str)
            if not ip_match:
                ip_match = re.search(r"ipAddr\[([0-9.]+)\]", response_str)
            if ip_match:
                result["changed_ip"] = ip_match.group(1)

            # 提取后续的 uav2gcs 信息（如果存在）：serial: <WL30P59Y1600>, code: <450>
            serial_match = re.search(r"serial:\s*<([^>]+)>", response_str)
            code_match = re.search(r"code:\s*<([^>]+)>", response_str)
            if serial_match:
                result["serial"] = serial_match.group(1)
            if code_match:
                result["code"] = code_match.group(1)

            return result if result["changed_ip"] is not None else None

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 获取 SD 卡容量信息 ====================
    def get_sd_card_info(self) -> Optional[Dict[str, Any]]:
        """
        获取 SD 卡剩余容量信息

        Returns:
            包含 free_clust、cluster_size、sector_size、total_free_mb 的字典，失败返回 None
        """
        result = {
            "free_clusters": None,
            "cluster_size": None,
            "sector_size": None,
            "total_free_mb": None
        }

        try:
            raw_response = self.send_command("dmdfact sdCap", timeout=5)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)

            # 提取格式：fre_clust[61376], csize[16], ssize[512], total_free[479 MB]
            fre_clust_match = re.search(r"fre_clust\[(\d+)\]", response_str)
            csize_match = re.search(r"csize\[(\d+)\]", response_str)
            ssize_match = re.search(r"ssize\[(\d+)\]", response_str)
            total_free_match = re.search(r"total_free\[(\d+)\s*MB\]", response_str)

            if fre_clust_match:
                result["free_clusters"] = int(fre_clust_match.group(1))
            if csize_match:
                result["cluster_size"] = int(csize_match.group(1))
            if ssize_match:
                result["sector_size"] = int(ssize_match.group(1))
            if total_free_match:
                result["total_free_mb"] = int(total_free_match.group(1))

            return result if any(v is not None for v in result.values()) else None

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== SD 卡读写性能测试 ====================
    def sd_card_test(self) -> Optional[Dict[str, Any]]:
        """
        执行 SD 卡读写性能测试（创建 test.txt 并写入数据）

        注意：固件收到 dmdfact sdTest 后会立即回显命令本身，实际测试结果
        需要约 5-6 秒才返回（fatfs_write_test + fatfs_simple_test），
        因此不能使用标准 send_command 的 2 秒空闲超时。

        Returns:
            包含 file_size、time_ms、speed_kbps 的字典，失败返回 None
        """
        result = {
            "file_size": None,
            "time_ms": None,
            "speed_kbps": None,
            "test_passed": False
        }

        try:
            if not self.is_connected:
                return None

            # 清空缓冲区
            self.clear_buffer()
            time.sleep(0.05)
            self.clear_buffer()

            # 发送命令
            self.send_data("dmdfact sdTest\r\n")
            logger.info("[ProtocolHandler] 已发送 dmdfact sdTest，等待测试结果...")

            # 持续读取响应，直到收到 fatfs_simple_test success 或超时
            # 固件行为：立即回显命令 → 5~6 秒后输出测试结果
            full_response = ""
            start_time = time.time()
            last_data_time = start_time
            timeout = 30.0

            while (time.time() - start_time) < timeout:
                data = self.read_data(timeout=0.1)
                if data:
                    decoded = data.decode('utf-8', errors='ignore')
                    full_response += decoded
                    last_data_time = time.time()

                # 收到测试完成标记即可提前退出
                if "fatfs_simple_test success" in full_response.lower():
                    break

                # 收到数据后，空闲 8 秒（回显后固件执行 SD 测试需约 6 秒）
                if full_response and (time.time() - last_data_time) > 8.0:
                    break

            logger.info(f"[ProtocolHandler] SD 测试响应: {full_response.strip()}")

            response_str = self._parse_response_to_string(full_response)

            # 提取格式：fsize:4096000, time:5882, speed:680 KB/s
            fsize_match = re.search(r"fsize:(\d+)", response_str)
            time_match = re.search(r"time:(\d+)", response_str)
            speed_match = re.search(r"speed:(\d+)\s*KB/s", response_str)

            if fsize_match:
                result["file_size"] = int(fsize_match.group(1))
            if time_match:
                result["time_ms"] = int(time_match.group(1))
            if speed_match:
                result["speed_kbps"] = int(speed_match.group(1))

            # 判断测试是否成功（固件输出 fatfs_simple_test success 或 write file success）
            result["test_passed"] = (
                "fatfs_simple_test success" in response_str.lower() or
                "write file success" in response_str.lower()
            )
            if not result["test_passed"]:
                logger.warning(f"[WiFi-Protocol] SD 卡测试未通过，响应: {response_str[:200]}")
                return None

            return result

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 复位/重启 ====================
    def reboot(self) -> bool:
        """
        重启设备

        Returns:
            成功返回 True
        """
        try:
            # 重启可能导致设备在 ACK 回复前断开，跳过 ACK 检查
            response = self.send_command("reboot", timeout=3, check_ack=False)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 获取 WiFi 固件版本 ====================
    def get_wifi_version(self) -> Optional[str]:
        """
        获取 WiFi 固件版本信息

        Returns:
            版本号字符串，失败返回 None
        """
        try:
            raw_response = self.send_command("dmdfact getVer", timeout=3)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)
            return response_str.strip() if response_str.strip() else None

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 获取 CPU 占用率 ====================
    def get_os_cpu(self, duration_ms: int = 2000) -> Optional[Dict[str, Any]]:
        """
        获取 CPU 占用率信息

        Args:
            duration_ms: 采样窗口(毫秒)。中间件命令格式为 `os cpu <duration_ms>`,
                         不带参数会回 usage 提示(`os cpu <duration_ms>`)而非数据。

        Returns:
            包含 CPU 信息的字典，失败返回 None
        """
        result = {
            "cpu_usage": None,
            "full_info": ""
        }

        try:
            # 采样耗时略大于 duration_ms,确保中间件能完成采样并返回
            timeout_sec = max(5.0, (duration_ms + 1000) / 1000.0)
            raw_response = self.send_command(f"os cpu {duration_ms}", timeout=timeout_sec)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)
            result["full_info"] = response_str

            return result

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 切换 SSID ====================
    def change_ssid(self, ssid: str) -> bool:
        """
        切换 WiFi 连接的 SSID

        Args:
            ssid: 新的 SSID 名称

        Returns:
            成功返回 True

        中间件响应判定(dmd_cicd.c chgSsid 分支):
            命令处理后,固件会打印 `[main][I][set_wifi_ssid][107]get wifi temperature
            while chgSsid [xx]` 日志作为已处理标记。直接通过 "ok"/"changed"/"success"
            关键字判定会全部误判为失败(中间件不回这些词)。
        """
        try:
            response = self.send_command(f"dmdcicd chgSsid      {ssid}", timeout=8)
            if not response:
                return False

            response_lower = response.lower()
            logger.info(f"[WiFi-Protocol] change_ssid({ssid}) 响应: {response_lower[:200]}")
            # 优先匹配中间件处理标记(set_wifi_ssid 日志行)
            if "set_wifi_ssid" in response_lower:
                return True
            # 兼容老固件:回 ok / changed / success 也算成功
            return "ok" in response_lower or "changed" in response_lower or "success" in response_lower

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 切换 AP/STA 模式 ====================
    def change_op_mode(self, mode: str) -> bool:
        """
        切换 WiFi 工作模式（AP 或 STA）

        Args:
            mode: "ap" 或 "sta"

        Returns:
            成功返回 True
        """
        mode_lower = mode.strip().lower()
        if mode_lower not in ["ap", "sta"]:
            return False

        try:
            response = self.send_command(f"dmdcicd chgOpMode    {mode_lower}", timeout=8)
            if not response:
                return False

            response_lower = response.lower()
            logger.info(f"[WiFi-Protocol] change_op_mode({mode_lower}) 响应: {response_lower[:200]}")
            return "ok" in response_lower or "changed" in response_lower or "success" in response_lower

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 检查 FTP 文件完整性 ====================
    def check_ftp_file(self, remote_path: str) -> Optional[Dict[str, Any]]:
        """
        检查 FTP 服务器上文件的完整性

        Args:
            remote_path: 远程文件路径（如 "/cmpn/dmd_companion/fota_793x.bin"）

        Returns:
            包含文件完整性检查结果的字典，失败返回 None
        """
        result = {
            "file_path": remote_path,
            "exists": False,
            "size": None,
            "md5": None,
            "full_info": ""
        }

        try:
            raw_response = self.send_command(f"dmdcicd checkFtp        {remote_path}", timeout=10)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)
            result["full_info"] = response_str

            # 判断文件是否存在
            if "not found" not in response_str.lower() and "error" not in response_str.lower():
                result["exists"] = True

            # 尝试提取文件大小
            size_match = re.search(r"size[:\s]+(\d+)", response_str, re.IGNORECASE)
            if size_match:
                result["size"] = int(size_match.group(1))

            # 尝试提取 MD5
            md5_match = re.search(r"md5[:\s]+([0-9a-fA-F]{32})", response_str, re.IGNORECASE)
            if md5_match:
                result["md5"] = md5_match.group(1)

            return result

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== WiFi 模块升级 ====================
    def update_wifi_module(self) -> Optional[str]:
        """
        执行 WiFi 模块固件升级

        校验策略(根据当前固件行为调整):
            失败 (任一命中即判失败):
                - "usage:"     参数错误(dmd_cicd.c:74/82)
                - "unknown"    命令名错误(CLI dispatcher)
                - "not exist"  升级文件不存在(onion_upgrade.c:460)
                - "failed"     任何 failed 字样(f_open/check head/check crc 等)
            成功:有非空回显且未命中失败标志即视为通过。

        注:#468 实测固件对 "dmdcicd update wifi" 的回显只有命令本身的 echo,
        没有 upgrade_utils.c:171 的 "open ... ok" 标志位打印出来(可能因为
        xQueueSend 后异步任务在 timeout=120s 内未把进度日志刷到 CLI 通道,
        或固件版本差异关闭了该打印)。FTPS 上传 + dmdcicd 接收命令的链路是
        通的(#468 上传 2.69MB fota_793x.bin 3.0s 成功),所以这里以"未命中
        失败标志"作为通过依据;真正的升级结果由后续 test_wifi_firmware_round_trip
        步骤 3/5 的版本号 tag 变化来验证。

        #455 历史背景:之前只看"有响应就通过"会让 "unknown command" 也通过,
        所以失败标志检测仍然保留 — 它能拦掉绝大多数固件侧的命令路径错误。

        Returns:
            升级回显文本,失败返回 None
        """
        try:
            # 固件 dmd_cicd.c:252-256 命令是 "update",参数才是 "wifi"(分两个 token)
            # 写成 "dmdcicd updateWifi" 会被解析成顶层命令 "updateWifi" → unknown command
            raw_response = self.send_command("dmdcicd update wifi", timeout=120)
            if not raw_response:
                logger.error("[update_wifi_module] 无回显,命令未被执行")
                return None

            response_str = self._parse_response_to_string(raw_response)

            # 失败标志检测 — 任一命中立即判失败
            failure_markers = ("usage:", "unknown", "not exist", "failed")
            for marker in failure_markers:
                if marker in response_str:
                    logger.error(
                        f"[update_wifi_module] 检测到失败标志 '{marker}',"
                        f"回显: {response_str}"
                    )
                    return None

            logger.info(f"[update_wifi_module] 升级命令已接收(未命中失败标志): {response_str}")
            return response_str

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 获取 IP 地址 ====================
    def get_ip_address(self) -> Optional[str]:
        """
        获取当前 WiFi IP 地址

        Returns:
            IP 地址字符串，失败返回 None
        """
        try:
            raw_response = self.send_command("dmdcicd getIp", timeout=3)
            if not raw_response:
                return None

            response_str = self._parse_response_to_string(raw_response)

            # 提取 IP 地址格式
            ip_match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", response_str)
            if ip_match:
                return ip_match.group(1)

            return None

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 获取电池信息 ====================
    def get_battery_info(self) -> Dict[str, Any]:
        """
        获取电池信息

        Returns:
            包含电池电压、电流、温度等信息的字典
        """
        result = {
            "sum_voltage": None, "current": None, "temp": None,
            "soh": None, "lest_time": None, "cycle_count": None,
            "cell1_vol": None, "cell2_vol": None, "cell3_vol": None,
            "cell4_vol": None, "max_diff": None, "operation status": None,
            "unuse close count": None, "lifetime": None, "charging_status": None,
            "full_capacity": None, "vct": None
        }

        try:
            raw_response = self.send_command("bat", timeout=2)
            if not raw_response:
                return result

            response_str = self._parse_response_to_string(raw_response)

            patterns = {
                "sum_voltage": r'sum_voltage\s*:\s*([-+]?\d+\.?\d*)',
                "current": r'current\s*:\s*([-+]?\d+\.?\d*)',
                "temp": r'temp\s*:\s*([-+]?\d+\.?\d*)',
                "soh": r'soh\s*:\s*(\d+)',
                "lest_time": r'lest time\s*:\s*(\d+)',
                "cycle_count": r'cycle count\s*:\s*(\d+)',
                "cell1_vol": r'cell1_vol\s*:\s*([-+]?\d+\.?\d*)',
                "cell2_vol": r'cell2_vol\s*:\s*([-+]?\d+\.?\d*)',
                "cell3_vol": r'cell3_vol\s*:\s*([-+]?\d+\.?\d*)',
                "cell4_vol": r'cell4_vol\s*:\s*([-+]?\d+\.?\d*)',   
                "max_diff": r'max_diff\s*:\s*([-+]?\d+\.?\d*)',
                "operation status": r'operation status\s*:\s*(\w+)',
                "unuse close count": r'unuse close count\s*:\s*(\d+)',
                "lifetime": r'lifetime\s*:\s*(\d+)',
                "charging_status": r'charging status\s*:\s*(\w+)',
                "full_capacity": r'full capacity\s*:\s*(\d+)',
                "vct": r'vct\s*:\s*(\d+)'
            }

            for field, pattern in patterns.items():
                match = re.search(pattern, response_str)
                if match:
                    try:
                        value = match.group(1)
                        result[field] = float(value) if '.' in value else int(value)
                    except ValueError:
                        pass

        except Exception:
            pass

        return result

    # ==================== dshot 协议 ====================
    def set_dshot_telemetry(self, enable: bool) -> bool:
        """
        设置 dshot telemetry 遥测开关(dshot tel 0/1)

        严格按固件源码回显校验(sys_cli_serv.cpp:2712-2721 cmd_func_dshot):
            失败:
                - "ERROR: unknow dshot cmd"     sys_cli_serv.cpp:2716 参数非 0/1
                - "ERROR: send cmd failed"      sys_cli_serv.cpp:2721 DRV_IOC_DSHOT_TELEMETRY ioctl 失败
                - "ERROR: Could not open TIM_DSHOT"  sys_cli_serv.cpp:2708 设备打开失败
            成功:
                - 固件静默返回,无正向打印。

        Args:
            enable: True 开启,False 关闭

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dshot tel {'1' if enable else '0'}", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            if "unknow dshot cmd" in response_lower:
                return False
            if "send cmd failed" in response_lower:
                return False
            if "could not open tim_dshot" in response_lower:
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def set_dshot_start(self) -> bool:
        """
        启动 dshot(dshot start)

        严格按固件源码回显校验(sys_cli_serv.cpp:2722-2728 cmd_func_dshot):
            成功:
                - "dshot start"  sys_cli_serv.cpp:2723(无条件先打印再 ioctl)
            失败:
                - "ERROR: DRV_IOC_DSHOT_START failed"  sys_cli_serv.cpp:2727 ioctl 返回非 OK
                - "ERROR: Could not open TIM_DSHOT"    sys_cli_serv.cpp:2708

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dshot start", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            if "could not open tim_dshot" in response_lower:
                return False
            if "drv_ioc_dshot_start failed" in response_lower:
                return False
            return "dshot start" in response_lower
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def set_dshot_stop(self) -> bool:
        """
        停止 dshot(dshot stop)

        严格按固件源码回显校验(sys_cli_serv.cpp:2729-2735 cmd_func_dshot):
            成功:
                - "dshot stop"  sys_cli_serv.cpp:2730
            失败:
                - "ERROR: DRV_IOC_DSHOT_STOP failed"  sys_cli_serv.cpp:2734
                - "ERROR: Could not open TIM_DSHOT"   sys_cli_serv.cpp:2708

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dshot stop", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            if "could not open tim_dshot" in response_lower:
                return False
            if "drv_ioc_dshot_stop failed" in response_lower:
                return False
            return "dshot stop" in response_lower
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def set_dshot_test(self) -> bool:
        """
        测试 dshot(dshot t)

        严格按固件源码回显校验(sys_cli_serv.cpp:2736-2745 cmd_func_dshot):
            成功:
                - "dshot test"  sys_cli_serv.cpp:2737
            失败:
                - "ERROR: DRV_IOC_DSHOT_TEST failed"  sys_cli_serv.cpp:2744
                - "ERROR: Could not open TIM_DSHOT"   sys_cli_serv.cpp:2708

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dshot t", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            if "could not open tim_dshot" in response_lower:
                return False
            if "drv_ioc_dshot_test failed" in response_lower:
                return False
            return "dshot test" in response_lower
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def read_motor_rpm(self) -> bool:
        """
        读取电机转速(dshot rpm)

        严格按固件源码回显校验(sys_cli_serv.cpp:2746-2771 cmd_func_dshot):
            成功:
                - "rpm:%d,%d,%d,%d"  sys_cli_serv.cpp:2770 DRV_IOC_DSHOT_RPM ioctl 成功时打印
            失败:
                - ioctl 失败时固件静默返回(无失败标志)。本方法通过缺失 "rpm:" 前缀识别。
                - "ERROR: Could not open TIM_DSHOT"  sys_cli_serv.cpp:2708

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dshot rpm", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            if "could not open tim_dshot" in response_lower:
                return False
            return "rpm:" in response_lower
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def read_dshot_telemetry(self, channel: int) -> bool:
        """
        请求 dshot ESC 遥测(dshot info<N>)

        固件源码回显说明(sys_cli_serv.cpp:2772-2777 cmd_func_dshot):
            固件仅发布 UORB TP_ESC_REQ,不向 CLI 输出任何字符。
            响应通过其他通道异步返回。本方法只能验证命令已发出并收到响应。

        Args:
            channel: ESC 通道号

        Returns:
            命令发送并收到响应返回 True;通信异常返回 False
        """
        try:
            response = self.send_command(f"dshot info{channel}", timeout=5)
            return bool(response)
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def set_dshot_led(self, enable: bool) -> bool:
        """
        设置 dshot LED 开关(dshot led0/led1)

        严格按固件源码回显校验(sys_cli_serv.cpp:2778-2787 cmd_func_dshot):
            失败:
                - "ERROR: unknow dshot cmd"   sys_cli_serv.cpp:2782 参数非 0/1
                - "ERROR: send cmd failed"    sys_cli_serv.cpp:2787 DRV_IOC_DSHOT_LED ioctl 失败
                - "ERROR: Could not open TIM_DSHOT"  sys_cli_serv.cpp:2708
            成功:
                - 固件静默返回。

        Args:
            enable: True 开启,False 关闭

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dshot led{'1' if enable else '0'}", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            if "unknow dshot cmd" in response_lower:
                return False
            if "send cmd failed" in response_lower:
                return False
            if "could not open tim_dshot" in response_lower:
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def set_dshot_motor_direction(self, enable: bool) -> bool:
        """
        设置 dshot 电机方向(dshot dir0/dir1)

        严格按固件源码回显校验(sys_cli_serv.cpp:2788-2797 cmd_func_dshot):
            失败:
                - "ERROR: unknow dshot cmd"   sys_cli_serv.cpp:2792 参数非 0/1
                - "ERROR: send cmd failed"    sys_cli_serv.cpp:2797 DRV_IOC_DSHOT_DIRECTION ioctl 失败
                - "ERROR: Could not open TIM_DSHOT"  sys_cli_serv.cpp:2708
            成功:
                - 固件静默返回。

        Args:
            enable: True 正转,False 反转

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dshot dir{'1' if enable else '0'}", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            if "unknow dshot cmd" in response_lower:
                return False
            if "send cmd failed" in response_lower:
                return False
            if "could not open tim_dshot" in response_lower:
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def set_dshot_3d_mode(self, enable: bool) -> bool:
        """
        设置 dshot 3D 模式(dshot 3d0/3d1)

        严格按固件源码回显校验(sys_cli_serv.cpp:2798-2807 cmd_func_dshot):
            失败:
                - "ERROR: unknow dshot cmd"   sys_cli_serv.cpp:2802 参数非 0/1
                - "ERROR: send cmd failed"    sys_cli_serv.cpp:2807 DRV_IOC_DSHOT_3D_MODE ioctl 失败
                - "ERROR: Could not open TIM_DSHOT"  sys_cli_serv.cpp:2708
            成功:
                - 固件静默返回。

        Args:
            enable: True 开启,False 关闭

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dshot 3d{'1' if enable else '0'}", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            if "unknow dshot cmd" in response_lower:
                return False
            if "send cmd failed" in response_lower:
                return False
            if "could not open tim_dshot" in response_lower:
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 设置异常状态 ====================
    def set_error_state(self, state: str) -> bool:
        """
        设置异常状态(注入故障用于 failsafe 测试)

        严格按固件源码回显校验(sys_cli_serv.cpp:1937-2010 cmd_func_fake_fail):
            clear_error     → ffs 0          固件静默解锁所有 state,无回显
            low_battery     → ffs 1          打印 "Fake low battery"
            waypoint_failed → ffs 2          打印 "Fake wp error"
            fence_violation → ffs 3          打印 "Fake fence error"
            ekf_error       → ffs 4,1,0,1    打印 "Fake EKF to:(1, 0, 1)"
            crash_fall      → ffs 5          打印 "Fake crash (fall)"
            （ffs 5 为 2026-09-09 真机终端实测发现，固件源码区间外，按实测回显补录）

        除 clear_error 外,其余 5 个 state 必须命中对应的 "Fake ..." 字符串才算通过。
        clear_error 固件设计上无回显,只能确认命令被 dispatcher 接受。

        Args:
            state: clear_error / low_battery / waypoint_failed /
                   fence_violation / ekf_error / crash_fall

        Returns:
            成功返回 True
        """

        # 清除故障 0
        CLEAR_ERROR = 0
        # 低电量报警 1
        LOW_BATTERY_ALARM = 1
        # 航点失败 2
        WAYPOINT_FAILED = 2
        # 超出电子围栏 3
        FENCE_VIOLATION = 3
        # EKF异常 4
        EKF_ERROR = 4
        # 坠机(跌落) 5 —— 2026-09-09 真机终端实测发现
        CRASH_FALL = 5
        horizontal_error = 1
        vertical_error = 0
        attitude_error = 1

        if state not in ["clear_error", "low_battery", "waypoint_failed", "fence_violation", "ekf_error", "crash_fall"]:
            raise ValueError("Invalid error state")

        # state_cmd + 该 state 对应的固件成功回显关键字(None 表示固件无回显)
        state_map = {
            "clear_error":     (str(CLEAR_ERROR), None),
            "low_battery":     (str(LOW_BATTERY_ALARM), "fake low battery"),
            "waypoint_failed": (str(WAYPOINT_FAILED), "fake wp error"),
            "fence_violation": (str(FENCE_VIOLATION), "fake fence error"),
            "ekf_error":       (f"{EKF_ERROR}, {horizontal_error}, {vertical_error}, {attitude_error}",
                                "fake ekf to:"),
            "crash_fall":      (str(CRASH_FALL), "fake crash"),
        }
        state_cmd, success_marker = state_map[state]

        try:
            response = self.send_command(f"ffs {state_cmd}", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            logger.info(f"[WiFi-Protocol] set_error_state({state}) 响应: {response_lower[:200]}")
            # clear_error 固件静默无回显 — 只能确认命令被接受
            if success_marker is None:
                return True
            # 其余 state 必须命中固件实际打印的 "Fake ..." 字符串
            return success_marker in response_lower
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 获取 CPU 状态 ====================
    def get_cpu_status(self) -> Dict[str, Any]:
        """
        获取 CPU 状态

        Returns:
            包含 CPU 使用率等信息的字典
        """
        result = {
            "tasks": [],
            "heap": None,
            "dma_heap": None,
            "dma1_heap": None
        }

        ps_executed = False
        try:
            raw_response = self.send_command("ps", timeout=5)
            if not raw_response:
                return result

            ps_executed = True
            response_str = self._parse_response_to_string(raw_response)

            # 解析任务列表 pattern
            task_pattern = r'^ID\s+State\s+Prio\s+Mark\s+CPU\(%\)\s+Name\s*\n' \
                          r'((?:^\d+\s+[A-Z]\s+\d+\s+\d+\s+[\d.]+\s+\S.*\n)*)' \
                          r'^Heap\s*:\s*Total\s+(\d+)\s*,\s*Used\s+(\d+)\s*,\s*Remain\s+(\d+)\s*\n' \
                          r'^DmaHeap\s*:\s*Total\s+(\d+)\s*,\s*Used\s+(\d+)\s*,\s*Remain\s+(\d+)\s*\n' \
                          r'^Dma1Heap\s*:\s*Total\s+(\d+)\s*,\s*Used\s+(\d+)\s*,\s*Remain\s+(\d+)'

            match = re.search(task_pattern, response_str, re.MULTILINE)
            if match:
                tasks_text = match.group(1).strip()

                # 解析每行任务
                task_line_pattern = r'^(\d+)\s+([A-Z])\s+(\d+)\s+(\d+)\s+([\d.]+)\s+(.+)$'
                task_matches = re.findall(task_line_pattern, tasks_text, re.MULTILINE)

                for task in task_matches:
                    result["tasks"].append({
                        "id": int(task[0]),
                        "state": task[1],
                        "prio": int(task[2]),
                        "mark": int(task[3]),
                        "cpu": float(task[4]),
                        "name": task[5].strip()
                    })

                # 解析内存信息
                result["heap"] = {
                    "total": int(match.group(2)),
                    "used": int(match.group(3)),
                    "remain": int(match.group(4))
                }
                result["dma_heap"] = {
                    "total": int(match.group(5)),
                    "used": int(match.group(6)),
                    "remain": int(match.group(7))
                }
                result["dma1_heap"] = {
                    "total": int(match.group(8)),
                    "used": int(match.group(9)),
                    "remain": int(match.group(10))
                }

        except Exception:
            pass
        finally:
            # 确保 ps 命令的交互界面被退出（q 退出交互模式无 ACK）
            if ps_executed:
                try:
                    self.send_command("q", timeout=2, check_ack=False)
                    time.sleep(0.3)  # 等待终端退出交互界面
                except Exception:
                    pass

        return result

    # ==================== WiFi 相关命令 ====================
    def set_wifi(self) -> bool:
        """
        设置 WiFi

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"wifi", timeout=5)

            if "module error" in response.lower():
                return False
            
            if response:
                pattern = r"Current wifi id=(\d+), mask_id=(\d+), ssid=([^\n]+)"
                match = re.search(pattern, response)
                if match:
                    wifi_id = int(match.group(1))
                    mask_id = int(match.group(2))
                    ssid = match.group(3).strip()
                    response_dict = {
                        "wifi_id": wifi_id,
                        "mask_id": mask_id,
                        "ssid": ssid
                    }
                return response_dict
            return False
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    def set_wifi_debug_on(self) -> bool:
        """
        开启 WiFi 调试模式

        固件事实(sys_cli_serv.cpp:820-838):
            cmd_func_wifi 的 "debug on" 分支整个被注释掉,飞控匹配到命令后
            直接 close(fd) + return,不调任何 ioctl,不打印任何回显。
            所以本命令既无成功关键字也无失败关键字。

        本方法只能确认命令被 dispatcher 接受(响应非空 + 无 ERROR 字样),
        无法做正向成功校验 — 这是固件的限制,不是接口宽松。
        之前的 "module error" 检查在固件源码里根本不存在,已删除。

        Returns:
            命令被 dispatcher 接受返回 True
        """
        try:
            response = self.send_command("wifi debug on", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            logger.info(f"[WiFi-Protocol] set_wifi_debug_on 响应: {response_lower[:200]}")
            # 固件无成功/失败标志位 — 只能拒绝明显的 ERROR 字样兜底
            return "error" not in response_lower
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def set_wifi_debug_off(self) -> bool:
        """
        关闭 WiFi 调试模式

        固件事实(sys_cli_serv.cpp:839-857):
            同 set_wifi_debug_on,"debug off" 分支也被整体注释掉,
            飞控匹配到命令后不做任何操作,不打印任何回显。

        Returns:
            命令被 dispatcher 接受返回 True
        """
        try:
            response = self.send_command("wifi debug off", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            logger.info(f"[WiFi-Protocol] set_wifi_debug_off 响应: {response_lower[:200]}")
            return "error" not in response_lower
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
    
    def set_wifi_reset(self) -> bool:
        """
        重置 WiFi 芯片

        按固件源码回显校验(sys_cli_serv.cpp:858-863):
            失败:
                - "Failed to reset DRV_IOC_HFLPD130"  sys_cli_serv.cpp:861
            成功:
                - 固件静默返回,无正向打印。
                  这是固件事实,不能编造成功关键字 — 仅能确认无失败标志且
                  响应非空(即命令被 dispatcher 接受)。

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command("wifi reset", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            logger.info(f"[WiFi-Protocol] set_wifi_reset 响应: {response_lower[:200]}")
            # 失败标志 — DRV_IOC_HFLPD130_RESET ioctl 返回非 OK 时打印
            if "failed to reset drv_ioc_hflpd130" in response_lower:
                return False
            # 固件成功路径无正向回显,只能确认命令被接受(无失败标志 + 非空响应)
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    def set_wifi_ip(self, id: int, ssid: str) -> bool:
        """
        设置 WiFi IP 地址

        严格按固件源码回显校验(sys_cli_serv.cpp:864-925):
            成功:
                - "set wifi ip and ssid ok"  sys_cli_serv.cpp:924
            失败 (任一命中即失败):
                - "network id should be an integer between 1-999"  sys_cli_serv.cpp:874/883/888
                - "ssid character number should be betwwen 1-8"    sys_cli_serv.cpp:898
                  (固件原文拼写就是 betwwen,不要改成 between)
                - "Failed to set DRV_IOC_HFLPD130_SET_IP"         sys_cli_serv.cpp:908
                - "Failed to set DRV_IOC_HFLPD130_SET_SSID"       sys_cli_serv.cpp:914

        Args:
            id: WiFi 网络 ID(1-999)
            ssid: WiFi SSID(1-8 字符)

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"wifi {id} {ssid}", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            logger.info(f"[WiFi-Protocol] set_wifi_ip({id}, {ssid}) 响应: {response_lower[:200]}")
            # 失败标志
            failure_markers = (
                "network id should be an integer between 1-999",
                "ssid character number should be betwwen 1-8",  # 固件原文拼写
                "failed to set drv_ioc_hflpd130_set_ip",
                "failed to set drv_ioc_hflpd130_set_ssid",
            )
            for marker in failure_markers:
                if marker in response_lower:
                    return False
            # 成功标志
            return "set wifi ip and ssid ok" in response_lower
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 日志相关命令 ====================
    def set_log_start(self) -> bool:
        """
        开始日志记录

        严格按固件源码回显校验(sys_cli_serv.cpp:1565-1583, log.cpp:408):
            成功 (任一出现即通过):
                - "OK: starting a log"   sys_cli_serv.cpp:1567 立即回显
                - "log will write into"  log.cpp:408 日志任务异步启动后回显
            失败:
                - "unknow log cmd"       sys_cli_serv.cpp:1581(固件原文就这么拼,
                  没有拼写错误,不要改成 unknown)

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command("log start", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            logger.info(f"[WiFi-Protocol] set_log_start 响应: {response_lower[:200]}")
            # 失败优先 — 命中 unknow log cmd 立即判失败(固件原文拼写)
            if "unknow log cmd" in response_lower:
                return False
            # 成功标志 — 必须命中 OK: starting a log 或异步的 log will write into
            return "ok: starting a log" in response_lower or "log will write into" in response_lower
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def set_log_stop(self) -> bool:
        """
        停止日志记录

        严格按固件源码回显校验(sys_cli_serv.cpp:1565-1583):
            成功:
                - "OK: stopping a log"   sys_cli_serv.cpp:1574 立即回显
            失败:
                - "unknow log cmd"       sys_cli_serv.cpp:1581(固件原文拼写)

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command("log stop", timeout=5)
            if not response:
                return False
            response_lower = response.lower()
            logger.info(f"[WiFi-Protocol] set_log_stop 响应: {response_lower[:200]}")
            if "unknow log cmd" in response_lower:
                return False
            return "ok: stopping a log" in response_lower
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 参数方法 ====================
    def set_parameter(self, param_name: str, value: Any) -> bool:
        """
        修改参数内存值(配合 svp 持久化到 SD 卡)

        严格按固件源码回显校验(sys_cli_serv.cpp:1470-1548 cmd_func_sp):
            成功:
                - "Found param"  sys_cli_serv.cpp:1489 找到参数时打印
            失败:
                - "Can't find param"  sys_cli_serv.cpp:1484 找不到参数时打印

        Args:
            param_name: 参数名
            value: 参数值

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"sp {param_name}: {value}", timeout=2)
            if not response:
                return False
            response_lower = response.lower()
            logger.info(f"[WiFi-Protocol] set_parameter({param_name}) 响应: {response_lower[:200]}")
            if "can't find param" in response_lower:
                return False
            return "found param" in response_lower
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def save_parameter(self, param_name: str) -> bool:
        """
        保存参数到 SD 卡

        严格按固件源码回显校验(sys_cli_serv.cpp:1550-1563 cmd_func_svp):
            成功:
                - "Save" + "OK"  sys_cli_serv.cpp:1559 格式 "OK: Save '%s' OK"
            失败:
                - "can't find param"  sys_cli_serv.cpp:1556 参数不存在
                - "Save" + "Failed"   sys_cli_serv.cpp:1561 "ERROR: Save '%s' Failed"

        Args:
            param_name: 参数名

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"svp {param_name}", timeout=2)
            if not response:
                return False
            response_lower = response.lower()
            logger.info(f"[WiFi-Protocol] save_parameter({param_name}) 响应: {response_lower[:200]}")
            if "can't find param" in response_lower:
                return False
            if "save" in response_lower and "failed" in response_lower:
                return False
            # 成功格式 "OK: Save '<name>' OK" — 同时含 save 和 ok
            return "save" in response_lower and "ok" in response_lower
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
    
    # ==================== 电机测试 ====================
    def motor_test_channel(self, channel: int, pwm_value: int) -> bool:
        """
        电机测试(单通道)

        严格按固件源码回显校验(sys_cli_serv.cpp:2196-2281 cmd_func_mt_check):
            成功:
                - 固件静默返回,仅发布 UORB TP_TEST_REQ。
            失败:
                - "ERROR: Param number error!!!"  参数个数非 2/3 时打印

        Args:
            channel: 电机通道 0~3
            pwm_value: PWM 值 1040~1950
        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"mtcheck {channel}, {pwm_value}", timeout=5)
            if not response:
                return False
            if "param number error!!!" in response.lower():
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def motor_test_timer(self, channel: int, pwm_value: int, duration: int) -> bool:
        """
        电机测试定时

        严格按固件源码回显校验(sys_cli_serv.cpp:2196-2281 cmd_func_mt_check):
            成功:
                - 固件静默返回,仅发布 UORB TP_TEST_REQ。
            失败:
                - "ERROR: Param number error!!!"  参数个数非 2/3 时打印

        Args:
            channel: 电机通道 0~3
            pwm_value: PWM 值 1040~1950
            duration: 测试持续时间（秒）
        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"mtcheck {channel}, {pwm_value}, {duration}", timeout=5)
            time.sleep(duration)  # 等待测试持续时间
            if not response:
                return False
            if "param number error!!!" in response.lower():
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def motor_test_all(self) -> bool:
        """
        电机测试所有通道(无参数)

        严格按固件源码回显校验(sys_cli_serv.cpp:2196-2281 cmd_func_mt_check):
            成功:
                - 固件静默返回(para=="" 时默认 start=1, param1=0)。
            失败:
                - 无参数调用不会触发 "Param number error!!!",
                  但保留校验防御 future regression。

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"mtcheck", timeout=5)
            if not response:
                return False
            if "param number error!!!" in response.lower():
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def motor_test_stop(self) -> bool:
        """
        停止电机测试(mtcheck -1)

        严格按固件源码回显校验(sys_cli_serv.cpp:2269-2270 cmd_func_mt_check):
            成功:
                - 固件静默返回,params[0]==-1 时 start=0。
            失败:
                - 无匹配的失败分支。

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"mtcheck -1", timeout=5)
            if not response:
                return False
            if "param number error!!!" in response.lower():
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def motor_test_scan(self, channel: int, pwm_start: int, pwm_end: int, step: int, duration: int) -> bool:
        """
        电机测试扫描

        严格按固件源码回显校验(sys_cli_serv.cpp:2196-2281 cmd_func_mt_check):
            成功:
                - 固件静默返回,仅发布 UORB TP_TEST_REQ。
            失败:
                - "ERROR: Param number error!!!"  参数个数非 5 或 thro 值超 1960 时打印

        Args:
            channel: 电机通道 0~3
            pwm_start: 起始 PWM 值 1040~1950
            pwm_end: 结束 PWM 值 1040~1950
            step: PWM 步长
            duration: 每个 PWM 值的测试持续时间（秒）

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"mtcheck {channel}, {pwm_start}, {pwm_end}, {step}, {duration}", timeout=5)
            time.sleep(duration * ((pwm_end - pwm_start) // step))  # 等待测试持续时间
            if not response:
                return False
            if "param number error!!!" in response.lower():
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def motor_test_cycle(self, motor0_pwm: int, motor1_pwm: int, motor2_pwm: int, motor3_pwm: int, work_time: int, rest_time: int, duration: int) -> bool:
        """
        电机测试循环

        严格按固件源码回显校验(sys_cli_serv.cpp:2255-2268 cmd_func_mt_check):
            成功:
                - 固件静默返回,仅发布 UORB TP_TEST_REQ。
            失败:
                - "ERROR: Param number error!!!"  参数个数非 7 或 thro 值超 1960 时打印

        Args:
            motor0_pwm: 电机0 PWM 值 1040~1950
            motor1_pwm: 电机1 PWM 值 1040~1950
            motor2_pwm: 电机2 PWM 值 1040~1950
            motor3_pwm: 电机3 PWM 值 1040~1950
            work_time: 工作时间（秒）
            rest_time: 休息时间（秒）
            duration: 测试持续时间（秒）

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"mtcheck {motor0_pwm}, {motor1_pwm}, {motor2_pwm}, {motor3_pwm}, {work_time}, {rest_time}, {duration}", timeout=5, check_ack=False)
            time.sleep(duration)  # 等待测试持续时间
            if not response:
                return False
            if "param number error!!!" in response.lower():
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 老化测试 ====================
    def aging_test_start(self, end_time: int, interval_time: int) -> bool:
        """
        老化测试启动

        严格按固件源码回显校验(sys_cli_serv.cpp:2831-2910 cmd_func_aging_test):
            成功:
                - 固件静默返回,仅发布 UORB TP_TEST_REQ。
            失败:
                - "ERROR: Param number error!!!"  参数个数非 3 或 params[0] 非 1 时打印

        Args:
            end_time: 测试结束时间（秒）
            interval_time: 测试间隔时间（秒）
        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"aging_test 1, {end_time}, {interval_time}", timeout=end_time+5)
            time.sleep(end_time)  # 等待测试持续时间
            if not response:
                return False
            if "param number error!!!" in response.lower():
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def aging_test_stop(self) -> bool:
        """
        停止老化测试

        严格按固件源码回显校验(sys_cli_serv.cpp:2858-2866 cmd_func_aging_test):
            成功:
                - 固件静默返回,params[0]==0 时 start=0。
            失败:
                - "ERROR: Param number error!!!"  参数个数非 1 时打印

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"aging_test 0", timeout=5)
            if not response:
                return False
            if "param number error!!!" in response.lower():
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def aging_test_cycle(self, end_time: int, throttle_duration: int, work_time: int, rest_time: int,throttle_low: int, throttle_mid: int,throttle_high: int, throttle_top: int,duration: int) -> bool:
        """
        老化测试循环

        严格按固件源码回显校验(sys_cli_serv.cpp:2879-2901 cmd_func_aging_test):
            成功:
                - 固件静默返回,仅发布 UORB TP_TEST_REQ。
            失败:
                - "ERROR: Param number error!!!"  参数个数非 10、params[0] 非 1
                  或油门百分比 > 100 时打印

        Args:
            end_time: 测试结束时间（秒）
            throttle_duration: 油门持续时间（秒）
            work_time: 工作时间（秒）
            rest_time: 休息时间（秒）
            throttle_low: 低油门值
            throttle_mid: 中油门值
            throttle_high: 高油门值
            throttle_top: 顶油门值
            duration: 测试持续时间（秒）
        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"aging_test 1, {end_time}, {throttle_duration}, {work_time}, {rest_time}, {throttle_low}, {throttle_mid}, {throttle_high}, {throttle_top}, {duration}", timeout=end_time+5, check_ack=False)
            time.sleep(end_time)  # 等待测试持续时间
            if not response:
                return False
            if "param number error!!!" in response.lower():
                return False
            return True
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== Shell 回显开关(原方法名保留,内部控制 shell_echo_config) ====================
    def radio_test_mode(self, enable: bool) -> bool:
        """
        切换 CLI shell 回显开关(shell_echo_config on/off)

        注: 方法名 "radio_test_mode" 与实际行为不符 — 实际控制的是 shell_echo_config
            (CLI 回显开关), 不是电台测试模式。电台测试模式由 radio_test_setting_*
            系列方法控制。保留方法名以维持 API 兼容性。

        严格按固件源码回显校验(sys_cli_serv.cpp:3161-3185 cmd_func_config_echo):
            成功:
                - 固件静默返回,仅写 echo_config 标志位。
            失败:
                - 无失败分支(参数非 "on"/"off"/"?" 时静默忽略)。

        Args:
            enable: True 开启回显,False 关闭回显

        Returns:
            命令发送并收到响应返回 True;通信异常返回 False
        """
        try:
            response = self.send_command(f"shell_echo_config {'on' if enable else 'off'}", timeout=5)
            return bool(response)
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def radio_test_check(self) -> Optional[str]:
        """
        查询 CLI shell 回显开关状态(shell_echo_config ?)

        注: 方法名 "radio_test_check" 与实际行为不符 — 实际查询的是 shell_echo_config
            (CLI 回显开关)。原实现发的是不存在的 `shell_echo_check ?` 命令(固件中
            无此 handler,会被 CLI 当作未知命令丢弃),已修正为 `shell_echo_config ?`。

        严格按固件源码回显校验(sys_cli_serv.cpp:3163-3172 cmd_func_config_echo):
            查询时固件必输出以下二者之一:
                - "shell_echo_config on"    echo_config 为 true 时
                - "shell_echo_config off"   echo_config 为 false 时

        Returns:
            "on" / "off" 表示当前状态;通信异常或回显不匹配返回 None
        """
        try:
            response = self.send_command(f"shell_echo_config ?", timeout=5)
            if not response:
                return None
            response_lower = response.lower()
            if "shell_echo_config on" in response_lower:
                return "on"
            if "shell_echo_config off" in response_lower:
                return "off"
            return None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return None

    # ==================== 电台测试模式(radio_test_config) ====================
    def radio_test_setting_check(self) -> bool:
        """
        查询电台工厂测试模式状态(radio_test_config ?)

        固件源码回显说明(sys_cli_serv.cpp:3206-3225 cmd_func_radio_test_mode_config):
            查询时固件通过 DAV 协议向电台子模块发 askFactoryMode 命令,
            响应通过其他通道异步返回,CLI 不输出任何字符。
            本方法只能验证命令已发出并收到响应。

        Returns:
            命令发送并收到响应返回 True;通信异常返回 False
        """
        try:
            response = self.send_command(f"radio_test_config ?", timeout=5)
            return bool(response)
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def radio_test_setting_start(self) -> bool:
        """
        进入电台工厂测试模式(radio_test_config 1)

        固件源码回显说明(sys_cli_serv.cpp:3218-3223 cmd_func_radio_test_mode_config):
            固件通过 DAV 协议向电台子模块发 setFactoryMode 命令,
            CLI 不输出任何字符。本方法只能验证命令已发出并收到响应。

        Returns:
            命令发送并收到响应返回 True;通信异常返回 False
        """
        try:
            response = self.send_command(f"radio_test_config 1", timeout=5)
            return bool(response)
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    def radio_test_setting_stop(self) -> bool:
        """
        退出电台工厂测试模式(radio_test_config 0)

        固件源码回显说明(sys_cli_serv.cpp:3218-3223 cmd_func_radio_test_mode_config):
            固件通过 DAV 协议向电台子模块发 setFactoryMode 命令,
            CLI 不输出任何字符。本方法只能验证命令已发出并收到响应。

        Returns:
            命令发送并收到响应返回 True;通信异常返回 False
        """
        try:
            response = self.send_command(f"radio_test_config 0", timeout=5)
            return bool(response)
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 接收机850M射频运行状态 ====================
    def radio_test_850M_mode_check(self) -> bool:
        """
        检查接收机850M射频运行状态

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"radio_850m_mode ?", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False



    # ==================== 获取遥控器原始数据 ====================
    def get_rc_raw_data(self) -> Dict[str, Any]:
        """
        获取遥控器原始数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_RC_RAW", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
    
    # ==================== 获取控制点数据 ====================
    def get_control_point_data(self) -> Dict[str, Any]:
        """
        获取控制点数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_CTRL_POINT", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 获取油门电机数据 ====================
    def get_throttle_motor_data(self) -> Dict[str, Any]:
        """
        获取油门电机数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_THRO_MOTOR", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== 获取姿态电机数据 ====================
    def get_atti_motor(self) -> Dict[str, Optional[float]]:
        """
        获取姿态电机数据

        Returns:
            包含 roll、pitch、yaw 电机值的字典
        """
        result = {"roll_motor": None, "pitch_motor": None, "yaw_motor": None}

        try:
            raw_response = self.send_command("dt TP_ATTI_MOTOR", timeout=5.0)
            if not raw_response:
                return False

            response_str = self._parse_response_to_string(raw_response)

            patterns = {
                "roll_motor": r'roll_motor\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "pitch_motor": r'pitch_motor\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "yaw_motor": r'yaw_motor\s*[:=]\s*([-+]?\d*\.\d+|\d+)'
            }

            for field, pattern in patterns.items():
                match = re.search(pattern, response_str, re.IGNORECASE | re.MULTILINE)
                if match:
                    try:
                        result[field] = float(match.group(1))
                    except ValueError:
                        pass

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

        return result
    
    # ==================== 获取目标姿态数据 ====================
    def get_target_attitude_data(self) -> Dict[str, Optional[float]]:
        """
        获取目标姿态数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_TAR_ATTI", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
    
    # ==================== 获取目标角速度数据 ====================
    def get_target_angular_velocity_data(self) -> Dict[str, Optional[float]]:
        """
        获取目标角速度数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_TAR_RATE", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取当前位置点数据 ====================
    def get_current_position_data(self) -> Dict[str, Optional[float]]:
        """
        获取当前位置点数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_CUR_POINT", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取日志请求数据 ====================
    def get_log_request_data(self) -> Dict[str, Any]:
        """
        获取日志请求数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_LOG_REQ", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取模式请求数据 ====================
    def get_mode_request_data(self) -> Dict[str, Any]:
        """
        获取模式请求数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_MODE_REQ", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取解锁请求数据 ====================
    def get_arm_request_data(self) -> Dict[str, Any]:
        """
        获取解锁请求数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_ARM_REQ", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取解锁检查数据 ====================
    def get_arm_check_data(self) -> Dict[str, Any]:
        """
        获取解锁检查数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_ARM_CHECK", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取动作请求数据 ====================
    def get_action_request_data(self) -> Dict[str, Any]:
        """
        获取动作请求数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_ACTION_REQ", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取灯光命令数据 ====================
    def get_light_command_data(self) -> Dict[str, Any]:
        """
        获取灯光命令数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_LIGHT_CMD", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
    
    # ==================== 获取电池缩放数据数据 ====================
    def get_battery_scaled_data(self) -> Dict[str, Any]:
        """
        获取电池缩放数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_BATTERY_SCALED", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取位置内环控制数据 ====================
    def get_pctrl_inner_data(self) -> Dict[str, Any]:
        """
        获取位置内环控制数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_PCTRL_INNER", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取姿态内环控制控制数据 ====================
    def get_actrl_inner_data(self) -> Dict[str, Any]:
        """
        获取姿态内环控制数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_ACTRL_INNER", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取电机请求数据 ====================
    def get_motor_request_data(self) -> Dict[str, Any]:
        """
        获取电机请求数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_MOTOR_REQ", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取测试请求数据 ====================
    def get_test_request_data(self) -> Dict[str, Any]:
        """
        获取测试请求数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_TEST_REQ", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取BNO传感器原始数据 ====================
    def get_bno_raw_data(self) -> Dict[str, Any]:
        """
        获取BNO传感器原始数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_BNO_RAW", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取TOF传感器原始数据 ====================
    def get_tof_raw_data(self) -> Dict[str, Any]:
        """
        获取TOF传感器原始数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_TOF_RAW", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取传感器校准数据 ====================
    def get_sensor_calibration_data(self) -> Dict[str, Any]:
        """
        获取传感器校准数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_SENSOR_CALI", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取数传RSS数据 ====================
    def get_rssi_data(self) -> Dict[str, Any]:
        """
        获取数传RSS数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_TELE_RSSI", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
    
    # ==================== 获取数传设置数据 ====================
    def get_tele_setting_data(self) -> Dict[str, Any]:
        """
        获取数传设置数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_TELE_SET", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取电调请求数据 ====================
    def get_esc_request_data(self) -> Dict[str, Any]:
        """
        获取电调请求数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_ESC_REQ", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取相机原始数据 ====================
    def get_camera_raw_data(self) -> Dict[str, Any]:
        """
        获取相机原始数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_CAMERA_RAW", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取网络遥控数据 ====================
    def get_network_remote_control_data(self) -> Dict[str, Any]:
        """
        获取网络遥控数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_RC_NETWORK", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取导航内环数据 ====================
    def get_navigation_inner_data(self) -> Dict[str, Any]:
        """
        获取导航内环数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_NAV_INNER", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取GPS更新数据 ====================
    def get_gps_update_data(self) -> Dict[str, Any]:
        """
        获取GPS更新数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_UPDATE_GPS", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取电池序列号设置数据 ====================
    def get_battery_serial_number_data(self) -> Dict[str, Any]:
        """
        获取电池序列号设置数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_BAT_SET_SN", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取电源请求数据 ====================
    def get_power_request_data(self) -> Dict[str, Any]:
        """
        获取电源请求数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_POWER_REQ", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取Boot更新数据 ====================
    def get_boot_update_data(self) -> Dict[str, Any]:
        """
        获取Boot更新数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_UPDATE_BOOT", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取Boot更新请求数据 ====================
    def get_boot_update_request_data(self) -> Dict[str, Any]:
        """
        获取Boot更新请求数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_UPDATE_BOOT_REQ", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取无线电频道数据 ====================
    def get_radio_channel_data(self) -> Dict[str, Any]:
        """
        获取无线电频道数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_RADIO_CHANNEL", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取无线电对频数据 ====================
    def get_radio_frequency_data(self) -> Dict[str, Any]:
        """
        获取无线电对频数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_RADIO_MATCH", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取DAV更新请求数据 ====================
    def get_dav_update_request_data(self) -> Dict[str, Any]:
        """
        获取DAV更新请求数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_UPDATE_DAV_REQ", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取MAC更新请求数据 ====================
    def get_mac_update_request_data(self) -> Dict[str, Any]:
        """
        获取MAC更新请求数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_UPDATE_MAC_REQ", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取无线电地址数据 ====================
    def get_radio_address_data(self) -> Dict[str, Any]:
        """
        获取无线电地址数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_RADIO_ADDR", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取LPPC地址数据 ====================
    def get_lppc_address_data(self) -> Dict[str, Any]:
        """
        获取LPPC地址数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_LPPC_ADDR", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取点火器状态数据 ====================
    def get_igniter_state_data(self) -> Dict[str, Any]:
        """
        获取点火器状态数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_IGNITER_STATE", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取子模块固件信息数据 ====================
    def get_submodule_firmware_info_data(self) -> Dict[str, Any]:
        """
        获取子模块固件信息数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_SUBMOD_FIRMWARE_INFO", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取LPPC保护检查数据 ====================
    def get_lppc_protection_check_data(self) -> Dict[str, Any]:
        """
        获取LPPC 保护检查数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_LPPC_PROTECTION_CHECK", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取LPPC修改寄存器数据 ====================
    def get_lppc_modify_register_data(self) -> Dict[str, Any]:
        """
        获取LPPC 修改寄存器数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_LPPC_MODIFY_REGISTER", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取IMU原始数据 ====================
    def get_imu_raw0(self) -> Dict[str, Optional[float]]:
        """
        获取 IMU RAW0 数据

        Returns:
            包含加速度计、陀螺仪和温度数据的字典
        """
        result = {
            "acc_x": None, "acc_y": None, "acc_z": None,
            "gyr_x": None, "gyr_y": None, "gyr_z": None,
            "temp": None, "time_stamp_us": None
        }

        try:
            raw_response = self.send_command("dt TP_IMU_RAW0", timeout=5.0)
            if not raw_response:
                return False

            patterns = {
                "acc_x": r"acc_x\s*:\s*([-+]?\d+\.?\d*)",
                "acc_y": r"acc_y\s*:\s*([-+]?\d+\.?\d*)",
                "acc_z": r"acc_z\s*:\s*([-+]?\d+\.?\d*)",
                "gyo_x": r"gyo_x\s*:\s*([-+]?\d+\.?\d*)",
                "gyo_y": r"gyo_y\s*:\s*([-+]?\d+\.?\d*)",
                "gyo_z": r"gyo_z\s*:\s*([-+]?\d+\.?\d*)",
                "temp": r"temp\s*:\s*([-+]?\d+\.?\d*)",
                "time_stamp_us": r"time_stamp_us\s*:\s*(\d+)"
            }

            for field, pattern in patterns.items():
                match = re.search(pattern, raw_response, re.IGNORECASE | re.MULTILINE)
                if match:
                    try:
                        value_str = match.group(1).strip()
                        result[field] = int(value_str) if field == "time_stamp_us" else float(value_str)
                    except ValueError:
                        pass
              
            # 字段名映射：gyo_x -> gyr_x
            result["gyr_x"] = result.pop("gyo_x", None)
            result["gyr_y"] = result.pop("gyo_y", None)
            result["gyr_z"] = result.pop("gyo_z", None)

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

        return result

    def get_imu_raw1(self) -> Dict[str, Optional[float]]:
        """
        获取 IMU RAW1 数据

        Returns:
            包含加速度计、陀螺仪和温度数据的字典
        """
        result = {
            "acc_x": None, "acc_y": None, "acc_z": None,
            "gyr_x": None, "gyr_y": None, "gyr_z": None,
            "temp": None
        }

        try:
            raw_response = self.send_command("dt TP_IMU_RAW1", timeout=5)
            if not raw_response:
                return False

            patterns = {
                'acc_x': r'acc_x\s*:\s*([-\d\.]+)',
                'acc_y': r'acc_y\s*:\s*([-\d\.]+)',
                'acc_z': r'acc_z\s*:\s*([-\d\.]+)',
                'gyo_x': r'gyo_x\s*:\s*([-\d\.]+)',
                'gyo_y': r'gyo_y\s*:\s*([-\d\.]+)',
                'gyo_z': r'gyo_z\s*:\s*([-\d\.]+)',
                'temp': r'temp\s*:\s*([-\d\.]+)'
            }

            for field, pattern in patterns.items():
                match = re.search(pattern, raw_response, re.IGNORECASE)
                if match:
                    try:
                        result[field] = float(match.group(1))
                    except ValueError:
                        pass

            # 字段名映射
            if "gyo_x" in result:
                result["gyr_x"] = result.pop("gyo_x", None)
                result["gyr_y"] = result.pop("gyo_y", None)
                result["gyr_z"] = result.pop("gyo_z", None)

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

        return result
    
    # ==================== 获取气压计数据原始数据 ====================
    def get_baro_raw0(self) -> Dict[str, Optional[float]]:
        """
        获取气压计0数据

        Returns:
            包含气压和温度的字典
        """
        result = {"press": None, "temp": None}

        try:
            raw_response = self.send_command("dt TP_BARO_RAW0", timeout=2)
            if not raw_response:
                return False

            response_str = self._parse_response_to_string(raw_response)

            press_match = re.search(r'press\s*:\s*([-+]?\d+\.?\d*)', response_str, re.IGNORECASE)
            temp_match = re.search(r'temp\s*:\s*([-+]?\d+\.?\d*)', response_str, re.IGNORECASE)

            if press_match:
                try:
                    result["press"] = float(press_match.group(1))
                except ValueError:
                    pass
            if temp_match:
                try:
                    result["temp"] = float(temp_match.group(1))
                except ValueError:
                    pass

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

        return result
    
    def get_baro_raw1(self) -> Dict[str, Optional[float]]:
        """
        获取气压计1数据

        Returns:
            包含气压和温度的字典
        """
        result = {"press": None, "temp": None}

        try:
            raw_response = self.send_command("dt TP_BARO_RAW1", timeout=2)
            if not raw_response:
                return False

            response_str = self._parse_response_to_string(raw_response)

            press_match = re.search(r'press\s*:\s*([-+]?\d+\.?\d*)', response_str, re.IGNORECASE)
            temp_match = re.search(r'temp\s*:\s*([-+]?\d+\.?\d*)', response_str, re.IGNORECASE)

            if press_match:
                try:
                    result["press"] = float(press_match.group(1))
                except ValueError:
                    pass
            if temp_match:
                try:
                    result["temp"] = float(temp_match.group(1))
                except ValueError:
                    pass

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

        return result
    
    # ==================== 获取罗盘原始数据 ====================
    def get_compass_raw0_data(self) -> Dict[str, Any]:
        """
        获取罗盘0原始数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_COMPASS_RAW0", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    def get_compass_raw1_data(self) -> Dict[str, Any]:
        """
        获取罗盘1原始数据

        Returns:
            包含罗盘1原始数据字典
        """
        try:
            response = self.send_command(f"dt TP_COMPASS_RAW1", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取GPS原始数据 ====================
    def get_gps_raw0_data(self) -> Dict[str, Any]:
        """
        获取 GPS 原始数据

        Returns:
            包含 GPS 数据的字典
        """
        result = {
            "state": 0,
            "fixType": 0,
            "utc_time": 0,
            "fix_percent": 0,
            "year": 0,
            "month": 0,
            "day": 0,
            "hour": 0, 
            "min": 0, 
            "sec": 0,
            "hdop": 0, 
            "vel_accuracy": 0.0, 
            "horz_accuracy": 0.0, 
            "vert_accuracy": 0.0,
            "sat_num": 0, 
            "lon": 0, 
            "lat": 0,
            "alt": 0,  
            "ellip_hgt": 0,
            "vel_x": 0.0000000,  
            "vel_y": 0.0000000,  
            "vel_z": 0.0000000, 
            "vert_vel_exist": 0,
            "vel_accuracy_exist": 0,
            "horz_accuracy_exist": 0,
            "vert_accuracy_exist": 0,
            "svUsed_num_beidou": 0,
            "svUsed_num_gps": 0,
            "svUsed_num_glo": 0,
            "itf_flag": 0,
            "jamind": 0,
            "agccnt": 0,
            "nosieperms": 0,
            "cr_count": 0,
            "pr_count": 0,
            "do_count": 0,
            "good_quality": 0,
            "good_cno": 0,
            "very_good_cno": 0,
            "bad_cno": 0,
            "numSVs": 0,
            "pvt_time_ms": 0
        }

        try:
            raw_response = self.send_command("dt TP_GPS_RAW0", timeout=2)
            if not raw_response:
                return False

            response_str = self._parse_response_to_string(raw_response)

            patterns = {
                "state": r'state\s*[:=]\s*(\d+)',
                "fixType": r'fixType\s*[:=]\s*(\d+)',
                "utc_time": r'utc_time\s*[:=]\s*(\d+)',
                "fix_percent": r'fix_percent\s*[:=]\s*(\d+)',
                "year": r'year\s*[:=]\s*(\d+)',
                "month": r'month\s*[:=]\s*(\d+)',
                "day": r'day\s*[:=]\s*(\d+)',
                "hour": r'hour\s*[:=]\s*(\d+)',
                "min": r'min\s*[:=]\s*(\d+)',
                "sec": r'sec\s*[:=]\s*(\d+)',
                "hdop": r'hdop\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "vel_accuracy": r'vel_accuracy\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "horz_accuracy": r'horz_accuracy\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "vert_accuracy": r'vert_accuracy\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "sat_num": r'sat_num\s*[:=]\s*(\d+)',
                "lon": r'lon\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "lat": r'lat\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "alt": r'alt\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "ellip_hgt": r'ellip_hgt\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "vel_x": r'vel_x\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "vel_y": r'vel_y\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "vel_z": r'vel_z\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "vert_vel_exist": r'vert_vel_exist\s*[:=    ]\s*(\d+)',
                "vel_accuracy_exist": r'vel_accuracy_exist\s*[:=]\s*(\d+)',
                "horz_accuracy_exist": r'horz_accuracy_exist\s*[:=]\s*(\d+)',
                "vert_accuracy_exist": r'vert_accuracy_exist\s*[:=]\s*(\d+)',
                "svUsed_num_beidou": r'svUsed_num_beidou\s*[:=]\s*(\d+)',
                "svUsed_num_gps": r'svUsed_num_gps\s*[:=]\s*(\d+)',
                "svUsed_num_glo": r'svUsed_num_glo\s*[:=]\s*(\d+)',
                "itf_flag": r'itf_flag\s*[:=]\s*(\d+)',
                "jamind": r'jamind\s*[:=]\s*(\d+)',
                "agccnt": r'agccnt\s*[:=]\s*(\d+)',
                "nosieperms": r'nosieperms\s*[:=]\s*(\d+)',
                "cr_count": r'cr_count\s*[:=]\s*(\d+)',
                "pr_count": r'pr_count\s*[:=]\s*(\d+)',
                "do_count": r'do_count\s*[:=]\s*(\d+)',
                "good_quality": r'good_quality\s*[:=]\s*(\d+)',
                "good_cno": r'good_cno\s*[:=]\s*(\d+)',
                "very_good_cno": r'very_good_cno\s*[:=]\s*(\d+)',
                "bad_cno": r'bad_cno\s*[:=]\s*(\d+)',
                "numSVs": r'numSVs\s*[:=]\s*(\d+)',
                "pvt_time_ms": r'pvt_time_ms\s*[:=]\s*(\d+)'          
            }

            for field, pattern in patterns.items():
                match = re.search(pattern, response_str, re.IGNORECASE)
                if match:
                    try:
                        value = match.group(1)
                        result[field] = float(value) if '.' in value else int(value)
                    except ValueError:
                        pass

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

        return result
    
    # ==================== 获取UWB原始数据 ====================
    def get_uwb_raw0_data(self) -> Dict[str, Any]:
        """
        获取UWB 0原始数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_UWB_RAW0", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    def get_uwb_raw1_data(self) -> Dict[str, Any]:
        """
        获取UWB 1原始数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_UWB_RAW1", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取IMU缩放数据 ====================
    def get_imu_scaled0(self) -> Dict[str, Optional[float]]:
        """
        获取 IMU SCALED0 数据

        Returns:
            包含加速度计、陀螺仪、磁力计和温度数据的字典
        """
        result = {
            "acc_x": None, "acc_y": None, "acc_z": None,
            "gyr_x": None, "gyr_y": None, "gyr_z": None,
            "temp": None, "noise": None, "seq": None
        }

        try:
            raw_response = self.send_command("dt TP_IMU_SCALED0", timeout=5.0)
            if not raw_response:
                return False

            response_str = self._parse_response_to_string(raw_response)

            patterns = {
                "acc_x": r'acc_x\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "acc_y": r'acc_y\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "acc_z": r'acc_z\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "gyo_x": r'gyo_x\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "gyo_y": r'gyo_y\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "gyo_z": r'gyo_z\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "temp": r'temp\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "noise": r'noise\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "seq": r'seq\s*[:=]\s*(\d+)'
            }

            for field, pattern in patterns.items():
                match = re.search(pattern, response_str, re.IGNORECASE)
                if match:
                    try:
                        result[field] = float(match.group(1))
                    except ValueError:
                        pass
            
            # 字段名映射：gyo_x -> gyr_x
            result["gyr_x"] = result.pop("gyo_x", None)
            result["gyr_y"] = result.pop("gyo_y", None)
            result["gyr_z"] = result.pop("gyo_z", None)

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

        return result

    def get_imu_scaled1(self) -> Dict[str, Optional[float]]:
        """
        获取 IMU SCALED1 数据

        Returns:
            包含加速度计、陀螺仪和温度数据的字典
        """
        result = {
            "acc_x": None, "acc_y": None, "acc_z": None,
            "gyr_x": None, "gyr_y": None, "gyr_z": None,
            "temp": None, "noise": None, "seq": None
        }

        try:
            raw_response = self.send_command("dt TP_IMU_SCALED1", timeout=5.0)
            if not raw_response:
                return False

            response_str = self._parse_response_to_string(raw_response)

            patterns = {
                "acc_x": r'acc_x\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "acc_y": r'acc_y\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "acc_z": r'acc_z\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "gyo_x": r'gyo_x\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "gyo_y": r'gyo_y\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "gyo_z": r'gyo_z\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "temp": r'temp\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "noise": r'noise\s*[:=]\s*([-+]?\d*\.\d+|\d+)',
                "seq": r'seq\s*[:=]\s*(\d+)'
            }

            for field, pattern in patterns.items():
                match = re.search(pattern, response_str, re.IGNORECASE)
                if match:
                    try:
                        result[field] = float(match.group(1))
                    except ValueError:
                        pass

            # 字段名映射
            if "gyo_x" in result:
                result["gyr_x"] = result.pop("gyo_x", None)
                result["gyr_y"] = result.pop("gyo_y", None)
                result["gyr_z"] = result.pop("gyo_z", None)

        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

        return result
    
    # ==================== 获取罗盘缩放数据 ====================
    def get_compass_scaled0_data(self) -> Dict[str, Any]:
        """
        获取罗盘0缩放数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_COMPASS_SCALED0", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    def get_compass_scaled1_data(self) -> Dict[str, Any]:
        """
        获取罗盘1缩放数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_COMPASS_SCALED1", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取舵机设置数据 ====================
    def get_servo0_data(self) -> Dict[str, Any]:
        """
        获取舵机0设置数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_SET_SERVO0", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    def get_servo1_data(self) -> Dict[str, Any]:
        """
        获取舵机1设置数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_SET_SERVO1", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    # ==================== 获取继电器设置数据 ====================
    def get_relay0_data(self) -> Dict[str, Any]:
        """
        获取继电器0设置数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_SET_RELAY0", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False
        
    def get_relay1_data(self) -> Dict[str, Any]:
        """
        获取继电器1设置数据

        Returns:
            成功返回 True
        """
        try:
            response = self.send_command(f"dt TP_SET_RELAY1", timeout=5)
            return response is not None
        except Exception as e:
            logger.error(f"[ProtocolHandler] 执行异常: {e}")
            return False

    # ==================== Topic 传输时间测量 ====================
    def measure_topic_transmission_time(self, topic_name: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """
        测量 dt 命令的 topic 传输时间（端到端往返时间）

        Args:
            topic_name: topic 名称，如 "TP_IMU_RAW0"
            timeout: 超时时间（秒）

        Returns:
            {"topic": topic_name, "response_time_ms": float, "response": str} 或 None（失败时）
        """
        try:
            t_start = time.perf_counter()
            response = self.send_command(f"dt {topic_name}", timeout=timeout)
            t_end = time.perf_counter()

            if not response:
                return None

            return {
                "topic": topic_name,
                "response_time_ms": round((t_end - t_start) * 1000, 2),
                "response": response
            }
        except Exception as e:
            logger.error(f"[ProtocolHandler] 测量 {topic_name} 传输时间异常: {e}")
            return None
