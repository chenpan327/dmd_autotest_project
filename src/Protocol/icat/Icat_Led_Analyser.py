#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iCAT LED 分析仪串口通讯协议库
支持 iCATFT04/iCATFT08/iCATFT16 系列 LED 测试仪

根据手册：iCAT+LED 测试仪用戶手冊 5.0.pdf
支持接口：USB/RS232/I2C
"""

import math

import serial
import time
import re
from typing import Tuple, List, Optional, Dict
from dataclasses import dataclass
from enum import Enum
from PIL import ImageColor, Image, ImageDraw, ImageFont


class GainLevel(Enum):
    """增益倍数枚举"""
    GAIN_1X = 1
    GAIN_4X = 2
    GAIN_16X = 3
    GAIN_60X = 4


class IntegrateTime(Enum):
    """传感器积分时间枚举"""
    TIME_25MS = 1
    TIME_50MS = 2
    TIME_100MS = 3
    TIME_200MS = 4
    TIME_500MS = 5


class DefaultSetting(Enum):
    """默认设置"""
    STANDARD = "01"  # 标准光源：16X, 100ms
    STRONG = "02"    # 强光：1X, 25ms
    WEAK = "03"      # 弱光：60X, 200ms


@dataclass
class RGBValue:
    """RGB 颜色值"""
    r: int
    g: int
    b: int
    
    def __str__(self):
        return f"RGB({self.r}, {self.g}, {self.b})"


@dataclass
class HSIValue:
    """HSI (色相，饱和度，亮度) 值"""
    hue: int          # 0-360
    saturation: int   # 0-100
    intensity: int    # 0-100 (HSI) 或 0-99999 (HSI2)
    
    def __str__(self):
        return f"HSI(H:{self.hue}, S:{self.saturation}, I:{self.intensity})"


@dataclass
class XYValue:
    """CIE1931 xy 色度值"""
    x: float
    y: float
    
    def __str__(self):
        return f"xy({self.x:.3f}, {self.y:.3f})"


@dataclass
class ChannelAllData:
    """通道完整数据 (Get CH##.All 返回)"""
    rgb: RGBValue
    hue: int
    saturation: int
    intensity: int
    x: float
    y: float
    wavelength: int
    
    @property
    def color_name(self) -> str:
        """获取颜色名称"""
        
        # 根据 RGB 分析当前颜色
        # try:
        #     # 使用 PIL 库获取颜色名称
        #     hex_color = '#{:02X}{:02X}{:02X}'.format(self.rgb.r, self.rgb.g, self.rgb.b)
        #     color_name = ImageColor.getcolor(hex_color, "RGB")
        #     return color_name
        # except Exception:
        #     return "无法识别"
        
        # 根据 HSI 分析当前颜色
        try:
            if self.saturation < 20:
                if self.intensity < 20:
                    return "black"
                else:
                    if 0 <= self.hue < 60 or 300 <= self.hue < 360:
                        return "warm white"
                    elif 180 <= self.hue < 270:
                        return "cool white"
                    else:
                        return "white"
            elif self.hue < 15 or self.hue >= 345:
                return "red"
            elif 15 <= self.hue < 45:
                return "orange yellow red"
            elif 45 <= self.hue < 75:
                return "yellow"
            elif 75 <= self.hue < 105:
                return "yellow green"
            elif 105 <= self.hue < 135:
                return "green"
            elif 135 <= self.hue < 165:
                return "cyan green"
            elif 165 <= self.hue < 195:
                return "cyan"
            elif 195 <= self.hue < 225:
                return "sky cyan blue"
            elif 225 <= self.hue < 255:
                return "blue"
            elif 255 <= self.hue < 315:
                return "magenta blue violet"
            elif 315 <= self.hue < 345:
                return "violet"
            else:
                return "unknown color"   
        except Exception:
            return "unknown color" 
        
    @property
    def calculate_HSI(self) -> HSIValue:
        """根据 RGB 计算 HSI 值"""
        r, g, b = self.rgb.r / 255.0, self.rgb.g / 255.0, self.rgb.b / 255.0
        intensity = (r + g + b) / 3.0
        
        min_rgb = min(r, g, b)
        saturation = 1 - (min_rgb / intensity) if intensity > 0 else 0
        
        # 色相计算
        if saturation == 0:
            hue = 0
        else:
            num = 0.5 * ((r - g) + (r - b))
            den = ((r - g) ** 2 + (r - b) * (g - b)) ** 0.5
            theta = math.acos(num / den) if den != 0 else 0
            hue = math.degrees(theta)
            if b > g:
                hue = 360 - hue
        
        return HSIValue(
            hue=int(hue),
            saturation=int(saturation * 100),
            intensity=int(intensity * 100)
        )
    
    def caculate_delta_e(self, target_rgb: RGBValue) -> float:
        """计算当前 RGB 与目标 RGB 的颜色差异 Delta E"""
        dr = target_rgb.r - self.rgb.r
        dg = target_rgb.g - self.rgb.g
        db = target_rgb.b - self.rgb.b
        delta_e = (dr * dr + dg * dg + db * db) ** 0.5
        return delta_e
    
    def caculate_delta_hsi(self, target_hsi: HSIValue) -> Tuple[int, int, int]:
        """计算当前 HSI 与目标 HSI 的差异"""
        delta_hue = abs(self.hue - target_hsi.hue)
        delta_saturation = abs(self.saturation - target_hsi.saturation)
        delta_intensity = abs(self.intensity - target_hsi.intensity)
        return delta_hue, delta_saturation, delta_intensity


class ICATError(Exception):
    """iCAT 设备异常"""
    pass


class ICATLedAnalyser:
    """
    iCAT LED 分析仪串口通讯类
    
    支持型号：iCATFT04 (4 通道), iCATFT08 (8 通道), iCATFT16 (16 通道)
    通讯接口：USB 转串口/RS232/I2C
    """
    
    # 命令前缀和格式
    CMD_PREFIX = ""  # 命令无前缀
    RESP_OK = "%OK"
    RESP_ERROR = "%Error"
    
    def __init__(self, port: str, baudrate: int = 19200, 
                 timeout: float = 1.0, write_timeout: float = 1.0):
        """
        初始化 iCAT LED 分析仪
        
        Args:
            port: 串口端口名，如 'COM3' (Windows) 或 '/dev/ttyUSB0' (Linux)
            baudrate: 波特率，默认 19200
            timeout: 读取超时时间 (秒)
            write_timeout: 写入超时时间 (秒)
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.serial = None
        self._connected = False
        self._i2c_address = 0x02  # 默认 I2C 地址
    
    def connect(self) -> bool:
        """
        连接串口设备
        
        Returns:
            bool: 连接成功返回 True
            
        Raises:
            ICATError: 连接失败时抛出
        """
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                write_timeout=self.write_timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            # 等待设备就绪
            time.sleep(0.5)
            self._connected = True
            # 清空缓冲区
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            return True
        except serial.SerialException as e:
            raise ICATError(f"无法连接串口 {self.port}: {e}")
    
    def disconnect(self):
        """断开串口连接"""
        if self.serial and self.serial.is_open:
            self.serial.close()
        self._connected = False
    
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._connected and self.serial and self.serial.is_open
    
    def _send_command(self, command: str) -> str:
        """
        发送命令并接收响应
        
        Args:
            command: 要发送的命令字符串
            
        Returns:
            str: 设备响应
            
        Raises:
            ICATError: 通讯失败时抛出
        """
        if not self.is_connected():
            raise ICATError("设备未连接，请先调用 connect()")
        
        try:
            # 发送命令 (以换行符结尾)
            cmd_bytes = (command + "\r").encode('ascii')
            self.serial.write(cmd_bytes)
            self.serial.flush()
            
            # 读取响应
            time.sleep(0.05)  # 给设备响应时间
            response = self.serial.readline().decode('ascii').strip()
            
            return response
        except serial.SerialException as e:
            raise ICATError(f"串口通讯错误：{e}")
        except UnicodeDecodeError as e:
            raise ICATError(f"响应解码错误：{e}")
    
    def _check_response(self, response: str, expected_prefix: str = "%") -> bool:
        """检查响应是否有效"""
        # print(response)
        if response == self.RESP_ERROR:
            raise ICATError("设备返回错误")
        if not response.startswith(expected_prefix):
            raise ICATError(f"响应格式错误：{response}")
        return True
    
    def _parse_channel(self, channel: int) -> str:
        """格式化通道号 (00-15)"""
        if not 0 <= channel <= 15:
            raise ValueError("通道号必须在 0-15 之间")
        return f"{channel:02d}"
    
    # ==================== 2.1 设置参数命令 ====================
    
    def set_i2c_address(self, address: int) -> bool:
        """
        设置设备的 I2C 地址
        
        Args:
            address: I2C 地址 (0x00-0xFF)
            
        Returns:
            bool: 设置成功返回 True
        """
        cmd = f"Set I2C Address=0x{address:02X}"
        response = self._send_command(cmd)
        self._check_response(response)
        return response == self.RESP_OK
    
    def set_channel_xoffset(self, channel: int, offset: float) -> bool:
        """
        设置通道 X 值偏移量
        
        Args:
            channel: 通道号 (0-15)
            offset: 偏移量 (-0.127 到 +0.127)
        """
        if not -0.127 <= offset <= 0.127:
            raise ValueError("偏移量必须在 -0.127 到 +0.127 之间")
        
        sign = "+" if offset >= 0 else "-"
        cmd = f"Set CH{self._parse_channel(channel)}.xoffset={sign}{abs(offset):.3f}"
        response = self._send_command(cmd)
        self._check_response(response)
        return response == self.RESP_OK
    
    def set_channel_yoffset(self, channel: int, offset: float) -> bool:
        """设置通道 Y 值偏移量"""
        if not -0.127 <= offset <= 0.127:
            raise ValueError("偏移量必须在 -0.127 到 +0.127 之间")
        
        sign = "+" if offset >= 0 else "-"
        cmd = f"Set CH{self._parse_channel(channel)}.yoffset={sign}{abs(offset):.3f}"
        response = self._send_command(cmd)
        self._check_response(response)
        return response == self.RESP_OK
    
    def set_channel_wloffset(self, channel: int, offset: int) -> bool:
        """
        设置通道波长偏移量
        
        Args:
            channel: 通道号 (0-15)
            offset: 偏移量 (-127 到 +127)
        """
        if not -127 <= offset <= 127:
            raise ValueError("偏移量必须在 -127 到 +127 之间")
        
        sign = "+" if offset >= 0 else "-"
        cmd = f"Set CH{self._parse_channel(channel)}.wloffset={sign}{abs(offset):03d}"
        response = self._send_command(cmd)
        self._check_response(response)
        return response == self.RESP_OK
    
    def set_channel_intoffset(self, channel: int, offset: int) -> bool:
        """
        设置通道强度偏移量
        
        Args:
            channel: 通道号 (0-15)
            offset: 偏移量 (-32767 到 +32767)
        """
        if not -32767 <= offset <= 32767:
            raise ValueError("偏移量必须在 -32767 到 +32767 之间")
        
        sign = "+" if offset >= 0 else "-"
        cmd = f"Set CH{self._parse_channel(channel)}.intoffset={sign}{abs(offset):05d}"
        response = self._send_command(cmd)
        self._check_response(response)
        return response == self.RESP_OK
    
    def set_channel_gain(self, channel: int, gain_level: int) -> bool:
        """
        设置通道增益倍数
        
        Args:
            channel: 通道号 (0-15)
            gain_level: 增益级别 (1=1X, 2=4X, 3=16X, 4=60X)
        """
        if gain_level not in [1, 2, 3, 4]:
            raise ValueError("增益级别必须是 1, 2, 3 或 4")
        
        cmd = f"Set CH{self._parse_channel(channel)}.Gain={gain_level}"
        response = self._send_command(cmd)
        self._check_response(response)
        return response == self.RESP_OK
    
    def set_channel_intetime(self, channel: int, time_level: int) -> bool:
        """
        设置通道传感器积分时间
        
        Args:
            channel: 通道号 (0-15)
            time_level: 时间级别 (1=25ms, 2=50ms, 3=100ms, 4=200ms, 5=500ms)
        """
        if time_level not in [1, 2, 3, 4, 5]:
            raise ValueError("时间级别必须是 1-5")
        
        cmd = f"Set CH{self._parse_channel(channel)}.Intetime={time_level}"
        response = self._send_command(cmd)
        self._check_response(response)
        return response == self.RESP_OK
    
    def set_default(self, setting: DefaultSetting) -> bool:
        """
        设置设备默认参数
        
        Args:
            setting: 默认设置类型
        """
        cmd = f"SetDefault {setting.value}"
        response = self._send_command(cmd)
        self._check_response(response)
        return response == self.RESP_OK
    
    # ==================== 2.2 读取设置参数命令 ====================
    
    def get_i2c_address(self) -> int:
        """获取设备 I2C 地址"""
        response = self._send_command("Get I2C Address")
        self._check_response(response)
        # 解析 %0xAA 格式
        match = re.match(r'%0x([0-9A-Fa-f]+)', response)
        if match:
            return int(match.group(1), 16)
        raise ICATError(f"无法解析 I2C 地址：{response}")
    
    def get_channel_xoffset(self, channel: int) -> float:
        """获取通道 X 偏移量"""
        cmd = f"Get CH{self._parse_channel(channel)}.xoffset"
        response = self._send_command(cmd)
        self._check_response(response)
        return float(response[1:])  # 去掉%前缀
    
    def get_channel_yoffset(self, channel: int) -> float:
        """获取通道 Y 偏移量"""
        cmd = f"Get CH{self._parse_channel(channel)}.yoffset"
        response = self._send_command(cmd)
        self._check_response(response)
        return float(response[1:])
    
    def get_channel_wloffset(self, channel: int) -> int:
        """获取通道波长偏移量"""
        cmd = f"Get CH{self._parse_channel(channel)}.wloffset"
        response = self._send_command(cmd)
        self._check_response(response)
        return int(response[1:])
    
    def get_channel_intoffset(self, channel: int) -> int:
        """获取通道强度偏移量"""
        cmd = f"Get CH{self._parse_channel(channel)}.intoffset"
        response = self._send_command(cmd)
        self._check_response(response)
        return int(response[1:])
    
    def get_channel_gain(self, channel: int) -> int:
        """获取通道增益级别"""
        cmd = f"Get CH{self._parse_channel(channel)}.GAIN"
        response = self._send_command(cmd)
        self._check_response(response)
        return int(response[1:])
    
    def get_channel_intetime(self, channel: int) -> int:
        """获取通道积分时间级别"""
        cmd = f"Get CH{self._parse_channel(channel)}.intetime"
        response = self._send_command(cmd)
        self._check_response(response)
        return int(response[1:])
    
    def get_channel_setting(self, channel: int) -> Dict:
        """
        获取通道完整设置参数
        
        Returns:
            Dict: 包含增益、积分时间、各偏移量的字典
        """
        cmd = f"Get CH{self._parse_channel(channel)}.Setting"
        response = self._send_command(cmd)
        self._check_response(response)
        
        print(response)
        # 解析：%AA;TTT;+(-)0.XXX;+(-)0.YYY;+(-)WWW;+(-)IIIII
        parts = response[1:].split(';')  # 去掉%前缀
        
        return parts
    
    def get_model(self) -> str:
        """获取设备型号"""
        response = self._send_command("Get Model")
        self._check_response(response)
        return response[1:]  # 去掉%前缀
    
    def get_sn(self) -> str:
        """获取设备序列号"""
        response = self._send_command("Get SN")
        self._check_response(response)
        return response[1:]
    
    def get_fw_ver(self) -> str:
        """获取固件版本"""
        response = self._send_command("Get FW.VER")
        self._check_response(response)
        return response[1:]
    
    def get_hw_ver(self) -> str:
        """获取硬件版本"""
        response = self._send_command("Get HW.VER")
        self._check_response(response)
        return response[1:]
    
    # ==================== 2.3 功能性命令 ====================
    
    def get_channel_rgb(self, channel: int) -> RGBValue:
        """
        获取通道 RGB 值
        
        Returns:
            RGBValue: RGB 颜色值
        """
        cmd = f"Get CH{self._parse_channel(channel)}.RGB"
        response = self._send_command(cmd)
        self._check_response(response)
        
        # 解析 %RRR,GGG,BBB
        match = re.match(r'%(\d+),(\d+),(\d+)', response)
        if match:
            return RGBValue(
                r=int(match.group(1)),
                g=int(match.group(2)),
                b=int(match.group(3))
            )
        raise ICATError(f"无法解析 RGB 值：{response}")
    
    def get_channel_hsi(self, channel: int) -> HSIValue:
        """
        获取通道 HSI 值 (亮度范围 0-100)
        """
        cmd = f"Get CH{self._parse_channel(channel)}.HSI"
        response = self._send_command(cmd)
        self._check_response(response)
        
        # 解析 %HHH,SSS,III
        match = re.match(r'%(\d+),(\d+),(\d+)', response)
        if match:
            return HSIValue(
                hue=int(match.group(1)),
                saturation=int(match.group(2)),
                intensity=int(match.group(3))
            )
        raise ICATError(f"无法解析 HSI 值：{response}")
    
    def get_channel_hsi2(self, channel: int) -> HSIValue:
        """
        获取通道 HSI 值 (亮度范围 0-99999，推荐使用)
        """
        cmd = f"Get CH{self._parse_channel(channel)}.HSI2"
        response = self._send_command(cmd)
        self._check_response(response)
        
        # 解析 %HHH,SSS,IIIII
        match = re.match(r'%(\d+),(\d+),(\d+)', response)
        if match:
            return HSIValue(
                hue=int(match.group(1)),
                saturation=int(match.group(2)),
                intensity=int(match.group(3))
            )
        raise ICATError(f"无法解析 HSI2 值：{response}")
    
    def get_channel_wavelength(self, channel: int) -> int:
        """获取通道波长 (nm)"""
        cmd = f"Get CH{self._parse_channel(channel)}.Wavelength"
        response = self._send_command(cmd)
        self._check_response(response)
        return int(response[1:])
    
    def get_channel_int(self, channel: int) -> int:
        """获取通道强度 (0-99999)"""
        cmd = f"Get CH{self._parse_channel(channel)}.Int"
        response = self._send_command(cmd)
        self._check_response(response)
        return int(response[1:])
    
    def get_channel_xy(self, channel: int) -> XYValue:
        """获取通道 CIE1931 xy 色度值"""
        cmd = f"Get CH{self._parse_channel(channel)}.xy"
        response = self._send_command(cmd)
        self._check_response(response)
        
        # 解析 %0.xxx,0.yyy
        match = re.match(r'%([\d.]+),([\d.]+)', response)
        if match:
            return XYValue(
                x=float(match.group(1)),
                y=float(match.group(2))
            )
        raise ICATError(f"无法解析 xy 值：{response}")
    
    def get_channel_rgbi(self, channel: int) -> Tuple[RGBValue, int]:
        """获取通道 RGB 和强度值"""
        cmd = f"Get CH{self._parse_channel(channel)}.RGBI"
        response = self._send_command(cmd)
        self._check_response(response)
        
        # 解析 %RRR,GGG,BBB,IIIII
        match = re.match(r'%(\d+),(\d+),(\d+),(\d+)', response)
        if match:
            rgb = RGBValue(
                r=int(match.group(1)),
                g=int(match.group(2)),
                b=int(match.group(3))
            )
            intensity = int(match.group(4))
            return rgb, intensity
        raise ICATError(f"无法解析 RGBI 值：{response}")
    
    def get_channel_cct(self, channel: int) -> int:
        """获取通道 CCT (相关色温) 值"""
        cmd = f"Get CH{self._parse_channel(channel)}.CCT"
        response = self._send_command(cmd)
        self._check_response(response)
        # 解析 %CCCCCk 格式
        match = re.match(r'%(\d+)k', response, re.IGNORECASE)
        if match:
            return int(match.group(1))
        raise ICATError(f"无法解析 CCT 值：{response}")
    
    def get_channel_xyi(self, channel: int) -> Tuple[XYValue, int]:
        """获取通道 xy 色度和强度值"""
        cmd = f"Get CH{self._parse_channel(channel)}.xyI"
        response = self._send_command(cmd)
        self._check_response(response)
        
        # 解析 %0.xxx,0.yyy,IIIII
        match = re.match(r'%([\d.]+),([\d.]+),(\d+)', response)
        if match:
            xy = XYValue(
                x=float(match.group(1)),
                y=float(match.group(2))
            )
            intensity = int(match.group(3))
            return xy, intensity
        raise ICATError(f"无法解析 xyI 值：{response}")
    
    def get_channel_all(self, channel: int) -> ChannelAllData:
        """
        获取通道完整数据 (RGB, HSI, xy, 波长，颜色)
        
        Returns:
            ChannelAllData: 完整数据对象
        """
        cmd = f"Get CH{self._parse_channel(channel)}.All"
        response = self._send_command(cmd)
        self._check_response(response)
        
        # 解析 % RRR,GGG,BBB,HHH,SSS,IIIIII,0.XX,0.YY,WWW,CC
        pattern = r'%\s*(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),([\d.]+),([\d.]+),(\d+)'
        match = re.match(pattern, response)
        if match:
            return ChannelAllData(
                rgb=RGBValue(
                    r=int(match.group(1)),
                    g=int(match.group(2)),
                    b=int(match.group(3))
                ),
                hue=int(match.group(4)),
                saturation=int(match.group(5)),
                intensity=int(match.group(6)),
                x=float(match.group(7)),
                y=float(match.group(8)),
                wavelength=int(match.group(9))
            )
        raise ICATError(f"无法解析 All 数据：{response}")
    
    # ==================== 2.4 整体读取命令 ====================
    
    def get_rgb_all(self) -> List[RGBValue]:
        """获取所有通道的 RGB 值"""
        response = self._send_command("Get RGB.All")
        self._check_response(response)
        
        # 解析 %RRR,GGG,BBB;RRR,GGG,BBB;...
        values = []
        data = response[1:]  # 去掉%前缀
        for group in data.split(';'):
            if group.strip():
                parts = group.split(',')
                if len(parts) == 3:
                    values.append(RGBValue(
                        r=int(parts[0]),
                        g=int(parts[1]),
                        b=int(parts[2])
                    ))
        return values
    
    def get_hsi_ax(self, ax: str) -> List[HSIValue]:
        """
        获取部分通道的 HSI 值
        
        Args:
            ax: "A0" (0-7 通道) 或 "A1" (8-15 通道)
        """
        if ax not in ["A0", "A1"]:
            raise ValueError("AX 参数必须是 A0 或 A1")
        
        cmd = f"Get HSI.{ax}"
        response = self._send_command(cmd)
        self._check_response(response)
        
        # 解析 %HHH,SSS,IIIII;HHH,SSS,IIIII;...
        values = []
        data = response[1:]
        for group in data.split(';'):
            if group.strip():
                parts = group.split(',')
                if len(parts) == 3:
                    values.append(HSIValue(
                        hue=int(parts[0]),
                        saturation=int(parts[1]),
                        intensity=int(parts[2])
                    ))
        return values
    
    def get_wl_all(self) -> List[int]:
        """获取所有通道的波长值"""
        response = self._send_command("Get WL.All")
        self._check_response(response)
        
        # 解析 %WWW,WWW,WWW,...
        values = []
        data = response[1:]
        for val in data.split(','):
            if val.strip():
                values.append(int(val))
        return values
    
    def get_xyi_ax(self, ax: str) -> List[Tuple[XYValue, int]]:
        """获取部分通道的 xy 和强度值"""
        if ax not in ["A0", "A1"]:
            raise ValueError("AX 参数必须是 A0 或 A1")
        
        cmd = f"Get XYI.{ax}"
        response = self._send_command(cmd)
        self._check_response(response)
        
        # 解析 %0.xxx,0.yyy,IIIII;0.xxx,0.yyy,IIIII;...
        values = []
        data = response[1:]
        for group in data.split(';'):
            if group.strip():
                parts = group.split(',')
                if len(parts) == 3:
                    xy = XYValue(x=float(parts[0]), y=float(parts[1]))
                    intensity = int(parts[2])
                    values.append((xy, intensity))
        return values
    
    def get_int_all(self) -> List[int]:
        """获取所有通道的强度值"""
        response = self._send_command("Get Int.All")
        self._check_response(response)
        
        # 解析 %IIIII;IIIII;...
        values = []
        data = response[1:]
        for val in data.split(';'):
            if val.strip():
                values.append(int(val))
        return values
    
    # ==================== 2.5 闪烁 LED 读取命令 ====================
    
    def get_channel_pwm(self, channel: int) -> Dict:
        """
        获取闪烁 LED 的 RGB 及 HSI 值
        
        Returns:
            Dict: 包含 RGB、HSI 和是否闪烁的信息
        """
        cmd = f"Get CH{self._parse_channel(channel)}.PWM"
        response = self._send_command(cmd)
        self._check_response(response)
        
        # 解析 %RRR,GGG,BBB;HHH,SSS,IIIII;Y/N
        pattern = r'%(\d+),(\d+),(\d+);(\d+),(\d+),(\d+);([YN])'
        match = re.match(pattern, response)
        if match:
            return {
                'rgb': RGBValue(
                    r=int(match.group(1)),
                    g=int(match.group(2)),
                    b=int(match.group(3))
                ),
                'hsi': HSIValue(
                    hue=int(match.group(4)),
                    saturation=int(match.group(5)),
                    intensity=int(match.group(6))
                ),
                'is_pwm': match.group(7) == 'Y'
            }
        raise ICATError(f"无法解析 PWM 数据：{response}")
    
    # 
    def icat_all_channel_setting(self) -> List[Dict]:
        """
        获取所有通道的完整设置参数
        
        Returns:
            List[Dict]: 每个通道的设置参数字典列表
        """
        settings = []
        for ch in range(4):
            self.set_channel_gain(ch, 1)
            self.set_channel_intetime(ch, 1)
            self.set_channel_xoffset(ch, 0)
            self.set_channel_yoffset(ch, 0)
            self.set_channel_wloffset(ch, 0)
            self.set_channel_intoffset(ch, 0)

            setting = self.get_channel_setting(ch)
            settings.append(setting)
        return settings
    
    # ==================== 上下文管理器支持 ====================
    
    def __enter__(self):
        """上下文管理器入口"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.disconnect()
        return False
    

if __name__ == "__main__":
    # 测试代码
    analyser = ICATLedAnalyser('COM4', baudrate=19200)
    try:
        analyser.connect()
        print("连接成功")
        model = analyser.get_model()
        print(f"设备型号: {model}")
        sn = analyser.get_sn()
        print(f"序列号: {sn}")
        fw_ver = analyser.get_fw_ver()
        print(f"固件版本: {fw_ver}")
        
        settings = analyser.icat_all_channel_setting()
        print("通道设置参数:")
        for idx, setting in enumerate(settings):
            print(f"通道 {idx}: {setting}")
        
    except ICATError as e:
        print(f"错误: {e}")
    finally:
        analyser.disconnect()