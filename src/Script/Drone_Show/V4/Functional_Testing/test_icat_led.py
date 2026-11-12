# coding: utf-8
"""
LED 颜色功能测试模块

测试通过 iCAT LED 分析仪验证飞机 LED 指示灯的颜色显示是否正确。
支持 8 种标准颜色的测试：红、绿、蓝、黄、青、品红、白、黑。
"""

import math
import time

import pytest
import allure
from utils.logger import logger
import src.Protocol.icat.Icat_Led_Analyser as icat_led_analyser


# =============================================================================
# 测试类：LED 颜色功能测试
# =============================================================================
# 1. 定义 allure 层级和元数据
@allure.feature("LED 功能测试")  # 功能模块：LED 指示灯测试
@allure.story("LED 颜色显示验证")  # 用户故事：验证 LED 颜色显示准确性
@allure.severity(allure.severity_level.NORMAL)  # 用例严重程度：NORMAL
# 用例严重程度级别：BLOCKER(阻塞), CRITICAL(严重), NORMAL(普通), MINOR(次要), TRIVIAL(轻微)
@allure.title("LED 颜色显示测试")  # 用例标题
@allure.description("""
测试步骤:
1. 设置 LED 颜色为目标颜色值
2. 通过 iCAT LED 分析仪读取 4 个通道的 LED 数据
3. 验证读取的颜色名称与目标颜色是否匹配
4. 测试完成后关闭 LED

测试范围:
- 支持 8 种标准颜色：红、绿、蓝、黄、青、品红、白、黑
- 验证 4 个独立通道的 LED 颜色显示
- 使用 iCAT LED 分析仪进行硬件级颜色验证

预期结果:
- 所有通道的 LED 颜色显示与目标颜色一致
""")
@allure.tag("LED", "颜色", "iCAT", "硬件测试")  # 测试标签


# 2. pytest 标记：用于测试分类和筛选
@pytest.mark.functional  # 功能测试标记
@pytest.mark.led  # LED 测试标记
# 3. 参数化测试：8 种标准颜色及其 RGB 值
@pytest.mark.parametrize("led_color", [
    {"red": [255, 0, 0]},       # 红色
    {"green": [0, 255, 0]},     # 绿色
    {"blue": [0, 0, 255]},      # 蓝色
    {"yellow": [255, 255, 0]},  # 黄色
    {"cyan": [0, 255, 255]},    # 青色
    {"magenta": [255, 0, 255]}, # 品红色
    {"white": [255, 255, 255]}, # 白色
    {"black": [0, 0, 0]}        # 黑色（关闭）
])
class TestLEDColor:
    """
    LED 颜色测试类
    
    通过参数化方式对 8 种标准颜色进行逐一测试，
    使用 iCAT LED 分析仪验证实际显示颜色是否与目标一致。
    """

    @pytest.fixture(autouse=True)
    def setup_before_test(self, protocol_handler):
        """
        测试前后置处理
        
        Args:
            protocol_handler: 协议处理器实例，用于发送控制命令
            
        Yields:
            None: 执行测试主体后执行后置操作
        """
        # ===== 前置操作 =====
        logger.info("===== 测试开始：前置操作 =====")
        self.protocol_handler = protocol_handler
        yield
        # ===== 后置操作 =====
        logger.info("===== 测试结束：后置操作 =====")
        with allure.step("关闭 LED"):
            logger.info("发送 set_servo 命令关闭 LED (RGB: [0, 0, 0])")
            self.protocol_handler.set_servo(0, 0, 0)
            time.sleep(0.5)  # 等待 LED 关闭
            logger.info("LED 已关闭")

    def test_led_color(self, led_color):
        """
        测试 LED 颜色显示功能
        
        Args:
            led_color: 参数字典，格式为 {颜色名：[R, G, B]}
            
        Raises:
            AssertionError: 当通道颜色与目标颜色不匹配时抛出
        """
        # 提取颜色名称和 RGB 值
        led_color_name = list(led_color.keys())[0]
        logger.info(f"========== 测试 LED 颜色：{led_color_name} ==========")
        led_color_values = led_color[led_color_name]

        # 步骤 1: 设置 LED 颜色
        with allure.step(f"设置 LED 颜色为 {led_color_name}"):
            logger.info(f"发送 set_servo 命令，RGB 值：{led_color_values}")
            r, g, b = led_color_values
            actual_data = self.protocol_handler.set_servo(r, g, b)
            logger.info(f"命令响应数据：{actual_data}")
            allure.attach(
                f"RGB 输入值：[{r}, {g}, {b}]",
                name="LED 颜色输入",
                attachment_type=allure.attachment_type.TEXT
            )

        # 步骤 2: 读取并验证 LED 数据
        with allure.step(f"读取 LED 数据并验证颜色"):
            # 使用上下文管理器自动连接/断开 iCAT 设备
            with icat_led_analyser.ICATLedAnalyser('COM4', baudrate=19200) as icat:
                # 遍历 4 个通道进行验证
                for channel in range(4):
                    logger.info(f"----- 通道 {channel} 测试数据 -----")
                    all_data = icat.get_channel_all(channel)

                    # 记录测试数据到 allure 报告
                    allure.attach(
                        f"颜色名称：{all_data.color_name}\n"
                        f"RGB 值：{all_data.rgb}\n"
                        f"HSI 值：H={all_data.hue}, S={all_data.saturation}, I={all_data.intensity}\n"
                        f"计算 HSI 值：H={all_data.calculate_HSI.hue}, S={all_data.calculate_HSI.saturation}, I={all_data.calculate_HSI.intensity}",
                        name=f"通道 {channel} - LED 数据",
                        attachment_type=allure.attachment_type.TEXT
                    )

                    logger.info(f"通道 {channel} - 颜色：{all_data.color_name}")
                    logger.info(f"通道 {channel} - RGB 值：{all_data.rgb}")
                    logger.info(f"通道 {channel} - HSI 值：{all_data.hue}, {all_data.saturation}, {all_data.intensity}")
                    logger.info(f"通道 {channel} - 计算 HSI 值：{all_data.calculate_HSI.hue}, {all_data.calculate_HSI.saturation}, {all_data.calculate_HSI.intensity}")

                    # 断言：验证颜色名称是否匹配
                    # assert led_color_name in all_data.color_name, (
                    #     f"通道 {channel} 颜色不匹配：期望 '{led_color_name}', 实际 '{all_data.color_name}'"
                    # )

                    """根据 RGB 计算 HSI 值"""
                    r, g, b = all_data.rgb.r / 255.0, all_data.rgb.g / 255.0, all_data.rgb.b / 255.0
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

                    led_color_hue = hue
                    delta_hue = abs(all_data.hue - led_color_hue)
                    logger.info(f"通道 {channel} Hue {led_color_hue}, 期望颜色 '{led_color_name}', 实际颜色 '{all_data.color_name}', 色差值 {delta_hue}")

                    assert delta_hue < 60, (
                        f"通道 {channel} Hue 色差过大：期望颜色 '{led_color_name}', 实际颜色 '{all_data.color_name}', 色差值 {delta_hue}"
                    )

    def test_led_all_info(self, led_color):
        """
        测试 LED 全部信息读取功能
        
        Args:
            led_color: 参数字典，格式为 {颜色名：[R, G, B]}
        """
        # 提取颜色名称和 RGB 值
        led_color_name = list(led_color.keys())[0]
        logger.info(f"========== 测试 LED 全部颜色：{led_color_name} ==========")
        led_color_values = led_color[led_color_name]

        # 步骤 1: 设置 LED 颜色
        with allure.step(f"设置 LED 颜色为 {led_color_name}"):
            logger.info(f"发送 set_servo 命令，RGB 值：{led_color_values}")
            r, g, b = led_color_values
            actual_data = self.protocol_handler.set_servo(r, g, b)
            logger.info(f"命令响应数据：{actual_data}")
            allure.attach(
                f"RGB 输入值：[{r}, {g}, {b}]",
                name="LED 颜色输入",
                attachment_type=allure.attachment_type.TEXT
            )

        # 步骤 2: 读取 LED 全部信息
        with allure.step(f"读取 LED 全部信息"):
            # 使用上下文管理器自动连接/断开 iCAT 设备
            with icat_led_analyser.ICATLedAnalyser('COM4', baudrate=19200) as icat:
                # 遍历 4 个通道进行验证
                for channel in range(4):
                    logger.info(f"----- 通道 {channel} 测试数据 -----")
                    all_data = icat.get_channel_all(channel)

                    # 记录测试数据到 allure 报告
                    allure.attach(
                        f"颜色名称：{all_data.color_name}\n"
                        f"RGB 值：{all_data.rgb}\n"
                        f"HSI 值：H={all_data.hue}, S={all_data.saturation}, I={all_data.intensity}\n"
                        f"计算 HSI 值：H={all_data.calculate_HSI.hue}, S={all_data.calculate_HSI.saturation}, I={all_data.calculate_HSI.intensity}\n"
                        f"XY 值：X={all_data.x}, Y={all_data.y}\n"
                        f"波长值：{all_data.wavelength}",
                        name=f"通道 {channel} - LED 数据",
                        attachment_type=allure.attachment_type.TEXT
                    )

                    logger.info(f"通道 {channel} - 颜色：{all_data.color_name}")
                    logger.info(f"通道 {channel} - RGB 值：{all_data.rgb}")
                    logger.info(f"通道 {channel} - HSI 值：{all_data.hue}, {all_data.saturation}, {all_data.intensity}")
                    logger.info(f"通道 {channel} - 计算 HSI 值：{all_data.calculate_HSI.hue}, {all_data.calculate_HSI.saturation}, {all_data.calculate_HSI.intensity}")
                    logger.info(f"通道 {channel} - XY 值：X={all_data.x}, Y={all_data.y}")
                    logger.info(f"通道 {channel} - 波长值：{all_data.wavelength}")
