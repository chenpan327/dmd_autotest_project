# coding: utf-8

import pytest
import allure
from utils.logger import logger

# 1. 定义层级和元数据 (装饰器)
@allure.feature("Topic 数据测试")
@allure.story("DT 指令数据获取测试")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("Topic 数据获取功能测试")
@allure.description("""
测试步骤:
1. 通过 dt 指令获取各类 Topic 数据
2. 验证返回数据的有效性和完整性
3. 检查数据字段是否符合预期

测试范围:
- 遥控器数据
- 控制点数据
- 油门电机数据
- 姿态电机数据
- 目标姿态数据
- 目标角速度数据
- 当前位置数据
- 日志请求数据
- 模式请求数据
- 解锁请求数据
- 解锁检查数据
- 动作请求数据
- 灯光命令数据
- 电池缩放数据
- 位置内环控制数据
- 姿态内环控制数据
- 电机请求数据
- 测试请求数据
- BNO 传感器原始数据
- TOF 传感器原始数据
- 传感器校准数据
- 数传 RSS 数据
- 数传设置数据
- 电调请求数据
- 相机原始数据
- 网络遥控数据
- 导航内环数据
- GPS 更新数据
- 电池序列号设置数据
- 电源请求数据
- Boot 更新数据
- Boot 更新请求数据
- 无线电频道数据
- 无线电对频数据
- DAV 更新请求数据
- MAC 更新请求数据
- 无线电地址数据
- LPPC 地址数据
- 点火器状态数据
- 子模块固件信息数据
- LPPC 保护检查数据
- LPPC 修改寄存器数据
- IMU 原始数据
- 气压计原始数据
- 罗盘原始数据
- GPS 原始数据
- UWB 原始数据
- IMU 缩放数据
- 罗盘缩放数据
- 舵机设置数据
- 继电器设置数据
""")
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "TOPIC_DATA", "DT_COMMAND")


@pytest.mark.functional
class TestTopicData:
    """
    Topic 数据测试 测试 - 飞控内部 Topic 数据读取验证（dt 命令）

    业务背景：
        飞控内部通过 Topic（主题）机制在各模块间传递实时数据。通过串口 dt（data topic）
        命令可以读取各 Topic 的当前值，用于调试和验证飞控内部数据流的正确性。
        覆盖的 Topic 包括遥控器输入、控制点、电机输出、姿态控制、位置导航、日志/模式/
        解锁请求、灯光命令、电池状态、传感器原始数据（BNO/TOF/IMU/气压计/罗盘/GPS）、
        数传状态、电调请求、相机数据、导航更新、电源管理、Boot 更新、无线电配置、
        DAV/MAC 固件更新、LPPC 配置、点火器状态、UWB 定位、舵机/继电器设置等。
        这些 Topic 数据的正确性是飞控各子系统正常工作的基础。

    测试对象：
        - 串口 Topic 数据读取接口（dt TP_* 命令，共 56 个 Topic）
        - 遥控器数据：TP_RC_RAW（遥控器原始数据）, TP_RC_NETWORK（网络遥控数据）
        - 控制点数据：TP_CTRL_POINT（控制点）, TP_CUR_POINT（当前点）
        - 电机数据：TP_THRO_MOTOR（油门电机）, TP_ATTI_MOTOR（姿态电机）, TP_MOTOR_REQ（电机请求）
        - 姿态数据：TP_TAR_ATTI（目标姿态）, TP_TAR_RATE（目标角速度）, TP_ACTRL_INNER（姿态内环）
        - 位置数据：TP_PCTRL_INNER（位置内环）, TP_NAV_INNER（导航内环）
        - 日志/模式/解锁/动作请求：TP_LOG_REQ, TP_MODE_REQ, TP_ARM_REQ, TP_ARM_CHECK, TP_ACTION_REQ, TP_TEST_REQ
        - 灯光命令：TP_LIGHT_CMD
        - 电池数据：TP_BATTERY_SCALED（电池缩放）, TP_BAT_SET_SN（电池序列号设置）
        - 传感器数据：TP_BNO_RAW（BNO原始）, TP_TOF_RAW（TOF原始）, TP_SENSOR_CALI（传感器校准）,
          TP_IMU_RAW0/1（IMU原始，验证 acc_x/y/z, gyr_x/y/z, temp 字段）,
          TP_IMU_SCALED（IMU缩放）, TP_BARO_RAW0/1（气压计原始，验证 press/temp 字段）,
          TP_COMPASS_RAW0/1（罗盘原始）, TP_COMPASS_SCALED（罗盘缩放）,
          TP_GPS_RAW0（GPS原始，验证 state/fixType/lat/lon/alt/sat_num 字段）
        - 数传数据：TP_TELE_RSSI（数传RSSI）, TP_TELE_SET（数传设置）
        - 电调数据：TP_ESC_REQ
        - 相机数据：TP_CAMERA_RAW
        - 导航数据：TP_UPDATE_GPS
        - 电源/Boot数据：TP_POWER_REQ, TP_UPDATE_BOOT, TP_UPDATE_BOOT_REQ
        - 无线电数据：TP_RADIO_CHANNEL（频道）, TP_RADIO_MATCH（对频）, TP_RADIO_ADDR（地址）
        - DAV/MAC更新：TP_UPDATE_DAV_REQ, TP_UPDATE_MAC_REQ
        - 点火器数据：TP_IGNITER_STATE
        - 子模块固件：TP_SUBMOD_FIRMWARE_INFO
        - LPPC数据：TP_LPPC_ADDR, TP_LPPC_PROTECTION_CHECK, TP_LPPC_MODIFY_REGISTER
        - UWB数据：TP_UWB_RAW0, TP_UWB_RAW1
        - 舵机/继电器设置：TP_SERVO_SET, TP_RELAY_SET

    测试项：
        1. TP_RC_RAW — 获取遥控器原始数据
        2. TP_RC_NETWORK — 获取网络遥控数据
        3. TP_CTRL_POINT — 获取控制点数据
        4. TP_CUR_POINT — 获取当前控制点数据
        5. TP_THRO_MOTOR — 获取油门电机数据
        6. TP_ATTI_MOTOR — 获取姿态电机数据（验证 roll_motor/pitch_motor/yaw_motor 字段）
        7. TP_TAR_ATTI — 获取目标姿态数据
        8. TP_TAR_RATE — 获取目标角速度数据
        9. TP_LOG_REQ — 获取日志请求数据
        10. TP_MODE_REQ — 获取模式请求数据
        11. TP_ARM_REQ — 获取解锁请求数据
        12. TP_ARM_CHECK — 获取解锁检查数据
        13. TP_ACTION_REQ — 获取动作请求数据
        14. TP_LIGHT_CMD — 获取灯光命令数据
        15. TP_BATTERY_SCALED — 获取电池缩放数据
        16. TP_PCTRL_INNER — 获取位置内环控制数据
        17. TP_ACTRL_INNER — 获取姿态内环控制数据
        18. TP_MOTOR_REQ — 获取电机请求数据
        19. TP_TEST_REQ — 获取测试请求数据
        20. TP_BNO_RAW — 获取 BNO 传感器原始数据
        21. TP_TOF_RAW — 获取 TOF 传感器原始数据
        22. TP_SENSOR_CALI — 获取传感器校准数据
        23. TP_TELE_RSSI — 获取数传 RSSI 数据
        24. TP_TELE_SET — 获取数传设置数据
        25. TP_ESC_REQ — 获取电调请求数据
        26. TP_CAMERA_RAW — 获取相机原始数据
        27. TP_NAV_INNER — 获取导航内环数据
        28. TP_UPDATE_GPS — 获取 GPS 更新数据
        29. TP_BAT_SET_SN — 获取电池序列号设置数据
        30. TP_POWER_REQ — 获取电源请求数据
        31. TP_UPDATE_BOOT — 获取 Boot 更新数据
        32. TP_UPDATE_BOOT_REQ — 获取 Boot 更新请求数据
        33. TP_RADIO_CHANNEL — 获取无线电频道数据
        34. TP_RADIO_MATCH — 获取无线电对频数据
        35. TP_UPDATE_DAV_REQ — 获取 DAV 更新请求数据
        36. TP_UPDATE_MAC_REQ — 获取 MAC 更新请求数据
        37. TP_RADIO_ADDR — 获取无线电地址数据
        38. TP_LPPC_ADDR — 获取 LPPC 地址数据
        39. TP_IGNITER_STATE — 获取点火器状态数据
        40. TP_SUBMOD_FIRMWARE_INFO — 获取子模块固件信息数据
        41. TP_LPPC_PROTECTION_CHECK — 获取 LPPC 保护检查数据
        42. TP_LPPC_MODIFY_REGISTER — 获取 LPPC 修改寄存器数据
        43. TP_IMU_RAW0 — 获取 IMU RAW0 原始数据（验证 acc_x/y/z, gyr_x/y/z, temp 字段）
        44. TP_IMU_RAW1 — 获取 IMU RAW1 原始数据（验证 acc_x/y/z, gyr_x/y/z, temp 字段）
        45. TP_BARO_RAW0 — 获取气压计 RAW0 原始数据（验证 press/temp 字段）
        46. TP_BARO_RAW1 — 获取气压计 RAW1 原始数据（验证 press/temp 字段）
        47. TP_COMPASS_RAW0 — 获取罗盘 RAW0 原始数据
        48. TP_COMPASS_RAW1 — 获取罗盘 RAW1 原始数据
        49. TP_GPS_RAW0 — 获取 GPS RAW0 原始数据（验证 state/fixType/lat/lon/alt/sat_num 字段）
        50. TP_UWB_RAW0 — 获取 UWB RAW0 原始数据
        51. TP_UWB_RAW1 — 获取 UWB RAW1 原始数据
        52. TP_IMU_SCALED — 获取 IMU 缩放数据
        53. TP_COMPASS_SCALED — 获取罗盘缩放数据
        54. TP_SERVO_SET — 获取舵机设置数据
        55. TP_RELAY_SET — 获取继电器设置数据
        56. TP_BNO_RAW — 获取 BNO 传感器原始数据（重复项）
    """

    @pytest.fixture(autouse=True)
    def setup_before_test(self, serial_protocol_handler):
        """前置操作 + 后置操作"""
        logger.info("前置操作：初始化协议处理器")
        self.serial = serial_protocol_handler
        yield
        logger.info("后置操作：清理测试资源")

    # ==================== 遥控器原始数据测试 ====================
    @allure.story("遥控器数据")
    @allure.title("获取遥控器原始数据 TP_RC_RAW")
    def test_get_rc_raw_data(self):
        with allure.step("发送 dt TP_RC_RAW 命令并检查返回数据"):
            logger.info("发送 dt TP_RC_RAW 命令")
            result = self.serial.get_rc_raw_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 控制点数据测试 ====================
    @allure.story("控制点数据")
    @allure.title("获取控制点数据 TP_CTRL_POINT")
    def test_get_control_point_data(self):
        with allure.step("发送 dt TP_CTRL_POINT 命令并检查返回数据"):
            logger.info("发送 dt TP_CTRL_POINT 命令")
            result = self.serial.get_control_point_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 油门电机数据测试 ====================
    @allure.story("油门电机数据")
    @allure.title("获取油门电机数据 TP_THRO_MOTOR")
    def test_get_throttle_motor_data(self):
        with allure.step("发送 dt TP_THRO_MOTOR 命令并检查返回数据"):
            logger.info("发送 dt TP_THRO_MOTOR 命令")
            result = self.serial.get_throttle_motor_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 姿态电机数据测试 ====================
    @allure.story("姿态电机数据")
    @allure.title("获取姿态电机数据 TP_ATTI_MOTOR")
    def test_get_atti_motor_data(self):
        with allure.step("发送 dt TP_ATTI_MOTOR 命令并检查返回数据"):
            logger.info("发送 dt TP_ATTI_MOTOR 命令")
            result = self.serial.get_atti_motor()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"
            # 验证关键字段存在
            assert "roll_motor" in result, "返回数据缺少 roll_motor 字段"
            assert "pitch_motor" in result, "返回数据缺少 pitch_motor 字段"
            assert "yaw_motor" in result, "返回数据缺少 yaw_motor 字段"

    # ==================== 目标姿态数据测试 ====================
    @allure.story("目标姿态数据")
    @allure.title("获取目标姿态数据 TP_TAR_ATTI")
    def test_get_target_attitude_data(self):
        with allure.step("发送 dt TP_TAR_ATTI 命令并检查返回数据"):
            logger.info("发送 dt TP_TAR_ATTI 命令")
            result = self.serial.get_target_attitude_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 目标角速度数据测试 ====================
    @allure.story("目标角速度数据")
    @allure.title("获取目标角速度数据 TP_TAR_RATE")
    def test_get_target_angular_velocity_data(self):
        with allure.step("发送 dt TP_TAR_RATE 命令并检查返回数据"):
            logger.info("发送 dt TP_TAR_RATE 命令")
            result = self.serial.get_target_angular_velocity_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 当前位置数据测试 ====================
    @allure.story("当前位置数据")
    @allure.title("获取当前位置点数据 TP_CUR_POINT")
    def test_get_current_position_data(self):
        with allure.step("发送 dt TP_CUR_POINT 命令并检查返回数据"):
            logger.info("发送 dt TP_CUR_POINT 命令")
            result = self.serial.get_current_position_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 日志请求数据测试 ====================
    @allure.story("日志请求数据")
    @allure.title("获取日志请求数据 TP_LOG_REQ")
    def test_get_log_request_data(self):
        with allure.step("发送 dt TP_LOG_REQ 命令并检查返回数据"):
            logger.info("发送 dt TP_LOG_REQ 命令")
            result = self.serial.get_log_request_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 模式请求数据测试 ====================
    @allure.story("模式请求数据")
    @allure.title("获取模式请求数据 TP_MODE_REQ")
    def test_get_mode_request_data(self):
        with allure.step("发送 dt TP_MODE_REQ 命令并检查返回数据"):
            logger.info("发送 dt TP_MODE_REQ 命令")
            result = self.serial.get_mode_request_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 解锁请求数据测试 ====================
    @allure.story("解锁请求数据")
    @allure.title("获取解锁请求数据 TP_ARM_REQ")
    def test_get_arm_request_data(self):
        with allure.step("发送 dt TP_ARM_REQ 命令并检查返回数据"):
            logger.info("发送 dt TP_ARM_REQ 命令")
            result = self.serial.get_arm_request_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 解锁检查数据测试 ====================
    @allure.story("解锁检查数据")
    @allure.title("获取解锁检查数据 TP_ARM_CHECK")
    def test_get_arm_check_data(self):
        with allure.step("发送 dt TP_ARM_CHECK 命令并检查返回数据"):
            logger.info("发送 dt TP_ARM_CHECK 命令")
            result = self.serial.get_arm_check_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 动作请求数据测试 ====================
    @allure.story("动作请求数据")
    @allure.title("获取动作请求数据 TP_ACTION_REQ")
    def test_get_action_request_data(self):
        with allure.step("发送 dt TP_ACTION_REQ 命令并检查返回数据"):
            logger.info("发送 dt TP_ACTION_REQ 命令")
            result = self.serial.get_action_request_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 灯光命令数据测试 ====================
    @allure.story("灯光命令数据")
    @allure.title("获取灯光命令数据 TP_LIGHT_CMD")
    def test_get_light_command_data(self):
        with allure.step("发送 dt TP_LIGHT_CMD 命令并检查返回数据"):
            logger.info("发送 dt TP_LIGHT_CMD 命令")
            result = self.serial.get_light_command_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 电池缩放数据测试 ====================
    @allure.story("电池缩放数据")
    @allure.title("获取电池缩放数据 TP_BATTERY_SCALED")
    def test_get_battery_scaled_data(self):
        with allure.step("发送 dt TP_BATTERY_SCALED 命令并检查返回数据"):
            logger.info("发送 dt TP_BATTERY_SCALED 命令")
            result = self.serial.get_battery_scaled_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 位置内环控制数据测试 ====================
    @allure.story("位置内环控制数据")
    @allure.title("获取位置内环控制数据 TP_PCTRL_INNER")
    def test_get_pctrl_inner_data(self):
        with allure.step("发送 dt TP_PCTRL_INNER 命令并检查返回数据"):
            logger.info("发送 dt TP_PCTRL_INNER 命令")
            result = self.serial.get_pctrl_inner_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 姿态内环控制数据测试 ====================
    @allure.story("姿态内环控制数据")
    @allure.title("获取姿态内环控制数据 TP_ACTRL_INNER")
    def test_get_actrl_inner_data(self):
        with allure.step("发送 dt TP_ACTRL_INNER 命令并检查返回数据"):
            logger.info("发送 dt TP_ACTRL_INNER 命令")
            result = self.serial.get_actrl_inner_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 电机请求数据测试 ====================
    @allure.story("电机请求数据")
    @allure.title("获取电机请求数据 TP_MOTOR_REQ")
    def test_get_motor_request_data(self):
        with allure.step("发送 dt TP_MOTOR_REQ 命令并检查返回数据"):
            logger.info("发送 dt TP_MOTOR_REQ 命令")
            result = self.serial.get_motor_request_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 测试请求数据测试 ====================
    @allure.story("测试请求数据")
    @allure.title("获取测试请求数据 TP_TEST_REQ")
    def test_get_test_request_data(self):
        with allure.step("发送 dt TP_TEST_REQ 命令并检查返回数据"):
            logger.info("发送 dt TP_TEST_REQ 命令")
            result = self.serial.get_test_request_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== BNO 传感器原始数据测试 ====================
    @allure.story("BNO 传感器数据")
    @allure.title("获取 BNO 传感器原始数据 TP_BNO_RAW")
    def test_get_bno_raw_data(self):
        with allure.step("发送 dt TP_BNO_RAW 命令并检查返回数据"):
            logger.info("发送 dt TP_BNO_RAW 命令")
            result = self.serial.get_bno_raw_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== TOF 传感器原始数据测试 ====================
    @allure.story("TOF 传感器数据")
    @allure.title("获取 TOF 传感器原始数据 TP_TOF_RAW")
    def test_get_tof_raw_data(self):
        with allure.step("发送 dt TP_TOF_RAW 命令并检查返回数据"):
            logger.info("发送 dt TP_TOF_RAW 命令")
            result = self.serial.get_tof_raw_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 传感器校准数据测试 ====================
    @allure.story("传感器校准数据")
    @allure.title("获取传感器校准数据 TP_SENSOR_CALI")
    def test_get_sensor_calibration_data(self):
        with allure.step("发送 dt TP_SENSOR_CALI 命令并检查返回数据"):
            logger.info("发送 dt TP_SENSOR_CALI 命令")
            result = self.serial.get_sensor_calibration_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 数传 RSS 数据测试 ====================
    @allure.story("数传数据")
    @allure.title("获取数传 RSS 数据 TP_TELE_RSSI")
    def test_get_rssi_data(self):
        with allure.step("发送 dt TP_TELE_RSSI 命令并检查返回数据"):
            logger.info("发送 dt TP_TELE_RSSI 命令")
            result = self.serial.get_rssi_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 数传设置数据测试 ====================
    @allure.story("数传数据")
    @allure.title("获取数传设置数据 TP_TELE_SET")
    def test_get_tele_setting_data(self):
        with allure.step("发送 dt TP_TELE_SET 命令并检查返回数据"):
            logger.info("发送 dt TP_TELE_SET 命令")
            result = self.serial.get_tele_setting_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 电调请求数据测试 ====================
    @allure.story("电调数据")
    @allure.title("获取电调请求数据 TP_ESC_REQ")
    def test_get_esc_request_data(self):
        with allure.step("发送 dt TP_ESC_REQ 命令并检查返回数据"):
            logger.info("发送 dt TP_ESC_REQ 命令")
            result = self.serial.get_esc_request_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 相机原始数据测试 ====================
    @allure.story("相机数据")
    @allure.title("获取相机原始数据 TP_CAMERA_RAW")
    def test_get_camera_raw_data(self):
        with allure.step("发送 dt TP_CAMERA_RAW 命令并检查返回数据"):
            logger.info("发送 dt TP_CAMERA_RAW 命令")
            result = self.serial.get_camera_raw_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 网络遥控数据测试 ====================
    @allure.story("遥控数据")
    @allure.title("获取网络遥控数据 TP_RC_NETWORK")
    def test_get_network_remote_control_data(self):
        with allure.step("发送 dt TP_RC_NETWORK 命令并检查返回数据"):
            logger.info("发送 dt TP_RC_NETWORK 命令")
            result = self.serial.get_network_remote_control_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 导航内环数据测试 ====================
    @allure.story("导航数据")
    @allure.title("获取导航内环数据 TP_NAV_INNER")
    def test_get_navigation_inner_data(self):
        with allure.step("发送 dt TP_NAV_INNER 命令并检查返回数据"):
            logger.info("发送 dt TP_NAV_INNER 命令")
            result = self.serial.get_navigation_inner_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== GPS 更新数据测试 ====================
    @allure.story("GPS 数据")
    @allure.title("获取 GPS 更新数据 TP_UPDATE_GPS")
    def test_get_gps_update_data(self):
        with allure.step("发送 dt TP_UPDATE_GPS 命令并检查返回数据"):
            logger.info("发送 dt TP_UPDATE_GPS 命令")
            result = self.serial.get_gps_update_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 电池序列号设置数据测试 ====================
    @allure.story("电池数据")
    @allure.title("获取电池序列号设置数据 TP_BAT_SET_SN")
    def test_get_battery_serial_number_data(self):
        with allure.step("发送 dt TP_BAT_SET_SN 命令并检查返回数据"):
            logger.info("发送 dt TP_BAT_SET_SN 命令")
            result = self.serial.get_battery_serial_number_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 电源请求数据测试 ====================
    @allure.story("电源数据")
    @allure.title("获取电源请求数据 TP_POWER_REQ")
    def test_get_power_request_data(self):
        with allure.step("发送 dt TP_POWER_REQ 命令并检查返回数据"):
            logger.info("发送 dt TP_POWER_REQ 命令")
            result = self.serial.get_power_request_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== Boot 更新数据测试 ====================
    @allure.story("Boot 更新数据")
    @allure.title("获取 Boot 更新数据 TP_UPDATE_BOOT")
    def test_get_boot_update_data(self):
        with allure.step("发送 dt TP_UPDATE_BOOT 命令并检查返回数据"):
            logger.info("发送 dt TP_UPDATE_BOOT 命令")
            result = self.serial.get_boot_update_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== Boot 更新请求数据测试 ====================
    @allure.story("Boot 更新数据")
    @allure.title("获取 Boot 更新请求数据 TP_UPDATE_BOOT_REQ")
    def test_get_boot_update_request_data(self):
        with allure.step("发送 dt TP_UPDATE_BOOT_REQ 命令并检查返回数据"):
            logger.info("发送 dt TP_UPDATE_BOOT_REQ 命令")
            result = self.serial.get_boot_update_request_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 无线电频道数据测试 ====================
    @allure.story("无线电数据")
    @allure.title("获取无线电频道数据 TP_RADIO_CHANNEL")
    def test_get_radio_channel_data(self):
        with allure.step("发送 dt TP_RADIO_CHANNEL 命令并检查返回数据"):
            logger.info("发送 dt TP_RADIO_CHANNEL 命令")
            result = self.serial.get_radio_channel_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 无线电对频数据测试 ====================
    @allure.story("无线电数据")
    @allure.title("获取无线电对频数据 TP_RADIO_MATCH")
    def test_get_radio_frequency_data(self):
        with allure.step("发送 dt TP_RADIO_MATCH 命令并检查返回数据"):
            logger.info("发送 dt TP_RADIO_MATCH 命令")
            result = self.serial.get_radio_frequency_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== DAV 更新请求数据测试 ====================
    @allure.story("DAV 更新数据")
    @allure.title("获取 DAV 更新请求数据 TP_UPDATE_DAV_REQ")
    def test_get_dav_update_request_data(self):
        with allure.step("发送 dt TP_UPDATE_DAV_REQ 命令并检查返回数据"):
            logger.info("发送 dt TP_UPDATE_DAV_REQ 命令")
            result = self.serial.get_dav_update_request_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== MAC 更新请求数据测试 ====================
    @allure.story("MAC 更新数据")
    @allure.title("获取 MAC 更新请求数据 TP_UPDATE_MAC_REQ")
    def test_get_mac_update_request_data(self):
        with allure.step("发送 dt TP_UPDATE_MAC_REQ 命令并检查返回数据"):
            logger.info("发送 dt TP_UPDATE_MAC_REQ 命令")
            result = self.serial.get_mac_update_request_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 无线电地址数据测试 ====================
    @pytest.mark.skip(reason="无线电地址数据测试暂时跳过")
    @allure.story("无线电数据")
    @allure.title("获取无线电地址数据 TP_RADIO_ADDR")
    def test_get_radio_address_data(self):
        with allure.step("发送 dt TP_RADIO_ADDR 命令并检查返回数据"):
            logger.info("发送 dt TP_RADIO_ADDR 命令")
            result = self.serial.get_radio_address_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== LPPC 地址数据测试 ====================
    @pytest.mark.skip(reason="LPPC 地址数据测试暂时跳过")
    @allure.story("LPPC 数据")
    @allure.title("获取 LPPC 地址数据 TP_LPPC_ADDR")
    def test_get_lppc_address_data(self):
        with allure.step("发送 dt TP_LPPC_ADDR 命令并检查返回数据"):
            logger.info("发送 dt TP_LPPC_ADDR 命令")
            result = self.serial.get_lppc_address_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 点火器状态数据测试 ====================
    @allure.story("点火器数据")
    @allure.title("获取点火器状态数据 TP_IGNITER_STATE")
    def test_get_igniter_state_data(self):
        with allure.step("发送 dt TP_IGNITER_STATE 命令并检查返回数据"):
            logger.info("发送 dt TP_IGNITER_STATE 命令")
            result = self.serial.get_igniter_state_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 子模块固件信息数据测试 ====================
    @allure.story("子模块数据")
    @allure.title("获取子模块固件信息数据 TP_SUBMOD_FIRMWARE_INFO")
    def test_get_submodule_firmware_info_data(self):
        with allure.step("发送 dt TP_SUBMOD_FIRMWARE_INFO 命令并检查返回数据"):
            logger.info("发送 dt TP_SUBMOD_FIRMWARE_INFO 命令")
            result = self.serial.get_submodule_firmware_info_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== LPPC 保护检查数据测试 ====================
    @pytest.mark.skip(reason="LPPC 保护检查数据测试暂时跳过")
    @allure.story("LPPC 数据")
    @allure.title("获取 LPPC 保护检查数据 TP_LPPC_PROTECTION_CHECK")
    def test_get_lppc_protection_check_data(self):
        with allure.step("发送 dt TP_LPPC_PROTECTION_CHECK 命令并检查返回数据"):
            logger.info("发送 dt TP_LPPC_PROTECTION_CHECK 命令")
            result = self.serial.get_lppc_protection_check_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== LPPC 修改寄存器数据测试 ====================
    @allure.story("LPPC 数据")
    @allure.title("获取 LPPC 修改寄存器数据 TP_LPPC_MODIFY_REGISTER")
    def test_get_lppc_modify_register_data(self):
        with allure.step("发送 dt TP_LPPC_MODIFY_REGISTER 命令并检查返回数据"):
            logger.info("发送 dt TP_LPPC_MODIFY_REGISTER 命令")
            result = self.serial.get_lppc_modify_register_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== IMU 原始数据测试 ====================
    @allure.story("IMU 数据")
    @allure.title("获取 IMU RAW0 原始数据 TP_IMU_RAW0")
    def test_get_imu_raw0(self):
        with allure.step("发送 dt TP_IMU_RAW0 命令并检查返回数据"):
            logger.info("发送 dt TP_IMU_RAW0 命令")
            result = self.serial.get_imu_raw0()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"
            # 验证关键字段存在
            assert "acc_x" in result, "返回数据缺少 acc_x 字段"
            assert "acc_y" in result, "返回数据缺少 acc_y 字段"
            assert "acc_z" in result, "返回数据缺少 acc_z 字段"
            assert "gyr_x" in result, "返回数据缺少 gyr_x 字段"
            assert "gyr_y" in result, "返回数据缺少 gyr_y 字段"
            assert "gyr_z" in result, "返回数据缺少 gyr_z 字段"
            assert "temp" in result, "返回数据缺少 temp 字段"

    # ==================== IMU RAW1 原始数据测试 ====================
    @allure.story("IMU 数据")
    @allure.title("获取 IMU RAW1 原始数据 TP_IMU_RAW1")
    def test_get_imu_raw1(self):
        with allure.step("发送 dt TP_IMU_RAW1 命令并检查返回数据"):
            logger.info("发送 dt TP_IMU_RAW1 命令")
            result = self.serial.get_imu_raw1()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"
            # 验证关键字段存在
            assert "acc_x" in result, "返回数据缺少 acc_x 字段"
            assert "acc_y" in result, "返回数据缺少 acc_y 字段"
            assert "acc_z" in result, "返回数据缺少 acc_z 字段"
            assert "gyr_x" in result, "返回数据缺少 gyr_x 字段"
            assert "gyr_y" in result, "返回数据缺少 gyr_y 字段"
            assert "gyr_z" in result, "返回数据缺少 gyr_z 字段"
            assert "temp" in result, "返回数据缺少 temp 字段"

    # ==================== 气压计原始数据测试 ====================
    @allure.story("气压计数据")
    @allure.title("获取气压计 RAW0 原始数据 TP_BARO_RAW0")
    def test_get_baro_raw0(self):
        with allure.step("发送 dt TP_BARO_RAW0 命令并检查返回数据"):
            logger.info("发送 dt TP_BARO_RAW0 命令")
            result = self.serial.get_baro_raw0()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"
            # 验证关键字段存在
            assert "press" in result, "返回数据缺少 press 字段"
            assert "temp" in result, "返回数据缺少 temp 字段"

    # ==================== 气压计 RAW1 原始数据测试 ====================
    @allure.story("气压计数据")
    @allure.title("获取气压计 RAW1 原始数据 TP_BARO_RAW1")
    def test_get_baro_raw1(self):
        with allure.step("发送 dt TP_BARO_RAW1 命令并检查返回数据"):
            logger.info("发送 dt TP_BARO_RAW1 命令")
            result = self.serial.get_baro_raw1()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"
            # 验证关键字段存在
            assert "press" in result, "返回数据缺少 press 字段"
            assert "temp" in result, "返回数据缺少 temp 字段"

    # ==================== 罗盘原始数据测试 ====================
    @allure.story("罗盘数据")
    @allure.title("获取罗盘 RAW0 原始数据 TP_COMPASS_RAW0")
    def test_get_compass_raw0_data(self):
        with allure.step("发送 dt TP_COMPASS_RAW0 命令并检查返回数据"):
            logger.info("发送 dt TP_COMPASS_RAW0 命令")
            result = self.serial.get_compass_raw0_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 罗盘 RAW1 原始数据测试 ====================
    @allure.story("罗盘数据")
    @allure.title("获取罗盘 RAW1 原始数据 TP_COMPASS_RAW1")
    def test_get_compass_raw1_data(self):
        with allure.step("发送 dt TP_COMPASS_RAW1 命令并检查返回数据"):
            logger.info("发送 dt TP_COMPASS_RAW1 命令")
            result = self.serial.get_compass_raw1_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== GPS 原始数据测试 ====================
    @allure.story("GPS 数据")
    @allure.title("获取 GPS RAW0 原始数据 TP_GPS_RAW0")
    def test_get_gps_raw0_data(self):
        with allure.step("发送 dt TP_GPS_RAW0 命令并检查返回数据"):
            logger.info("发送 dt TP_GPS_RAW0 命令")
            result = self.serial.get_gps_raw0_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"
            # 验证关键字段存在
            assert "state" in result, "返回数据缺少 state 字段"
            assert "fixType" in result, "返回数据缺少 fixType 字段"
            assert "lat" in result, "返回数据缺少 lat 字段"
            assert "lon" in result, "返回数据缺少 lon 字段"
            assert "alt" in result, "返回数据缺少 alt 字段"
            assert "sat_num" in result, "返回数据缺少 sat_num 字段"

    # ==================== UWB 原始数据测试 ====================
    @allure.story("UWB 数据")
    @allure.title("获取 UWB RAW0 原始数据 TP_UWB_RAW0")
    def test_get_uwb_raw0_data(self):
        with allure.step("发送 dt TP_UWB_RAW0 命令并检查返回数据"):
            logger.info("发送 dt TP_UWB_RAW0 命令")
            result = self.serial.get_uwb_raw0_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== UWB RAW1 原始数据测试 ====================
    @allure.story("UWB 数据")
    @allure.title("获取 UWB RAW1 原始数据 TP_UWB_RAW1")
    def test_get_uwb_raw1_data(self):
        with allure.step("发送 dt TP_UWB_RAW1 命令并检查返回数据"):
            logger.info("发送 dt TP_UWB_RAW1 命令")
            result = self.serial.get_uwb_raw1_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== IMU 缩放数据测试 ====================
    @allure.story("IMU 数据")
    @allure.title("获取 IMU SCALED0 数据 TP_IMU_SCALED0")
    def test_get_imu_scaled0(self):
        with allure.step("发送 dt TP_IMU_SCALED0 命令并检查返回数据"):
            logger.info("发送 dt TP_IMU_SCALED0 命令")
            result = self.serial.get_imu_scaled0()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"
            # 验证关键字段存在
            assert "acc_x" in result, "返回数据缺少 acc_x 字段"
            assert "acc_y" in result, "返回数据缺少 acc_y 字段"
            assert "acc_z" in result, "返回数据缺少 acc_z 字段"
            assert "gyr_x" in result, "返回数据缺少 gyr_x 字段"
            assert "gyr_y" in result, "返回数据缺少 gyr_y 字段"
            assert "gyr_z" in result, "返回数据缺少 gyr_z 字段"
            assert "temp" in result, "返回数据缺少 temp 字段"

    # ==================== IMU SCALED1 数据测试 ====================
    @allure.story("IMU 数据")
    @allure.title("获取 IMU SCALED1 数据 TP_IMU_SCALED1")
    def test_get_imu_scaled1(self):
        with allure.step("发送 dt TP_IMU_SCALED1 命令并检查返回数据"):
            logger.info("发送 dt TP_IMU_SCALED1 命令")
            result = self.serial.get_imu_scaled1()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"
            # 验证关键字段存在
            assert "acc_x" in result, "返回数据缺少 acc_x 字段"
            assert "acc_y" in result, "返回数据缺少 acc_y 字段"
            assert "acc_z" in result, "返回数据缺少 acc_z 字段"
            assert "gyr_x" in result, "返回数据缺少 gyr_x 字段"
            assert "gyr_y" in result, "返回数据缺少 gyr_y 字段"
            assert "gyr_z" in result, "返回数据缺少 gyr_z 字段"
            assert "temp" in result, "返回数据缺少 temp 字段"

    # ==================== 罗盘缩放数据测试 ====================
    @allure.story("罗盘数据")
    @allure.title("获取罗盘 SCALED0 数据 TP_COMPASS_SCALED0")
    def test_get_compass_scaled0_data(self):
        with allure.step("发送 dt TP_COMPASS_SCALED0 命令并检查返回数据"):
            logger.info("发送 dt TP_COMPASS_SCALED0 命令")
            result = self.serial.get_compass_scaled0_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 罗盘 SCALED1 数据测试 ====================
    @allure.story("罗盘数据")
    @allure.title("获取罗盘 SCALED1 数据 TP_COMPASS_SCALED1")
    def test_get_compass_scaled1_data(self):
        with allure.step("发送 dt TP_COMPASS_SCALED1 命令并检查返回数据"):
            logger.info("发送 dt TP_COMPASS_SCALED1 命令")
            result = self.serial.get_compass_scaled1_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 舵机设置数据测试 ====================
    @allure.story("舵机数据")
    @allure.title("获取舵机 0 设置数据 TP_SET_SERVO0")
    def test_get_servo0_data(self):
        with allure.step("发送 dt TP_SET_SERVO0 命令并检查返回数据"):
            logger.info("发送 dt TP_SET_SERVO0 命令")
            result = self.serial.get_servo0_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 舵机 1 设置数据测试 ====================
    @allure.story("舵机数据")
    @allure.title("获取舵机 1 设置数据 TP_SET_SERVO1")
    def test_get_servo1_data(self):
        with allure.step("发送 dt TP_SET_SERVO1 命令并检查返回数据"):
            logger.info("发送 dt TP_SET_SERVO1 命令")
            result = self.serial.get_servo1_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 继电器设置数据测试 ====================
    @pytest.mark.skip(reason="继电器数据测试暂时跳过，后续根据需求启用")
    @allure.story("继电器数据")
    @allure.title("获取继电器 0 设置数据 TP_SET_RELAY0")
    def test_get_relay0_data(self):
        with allure.step("发送 dt TP_SET_RELAY0 命令并检查返回数据"):
            logger.info("发送 dt TP_SET_RELAY0 命令")
            result = self.serial.get_relay0_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"

    # ==================== 继电器 1 设置数据测试 ====================
    @pytest.mark.skip(reason="继电器数据测试暂时跳过，后续根据需求启用")
    @allure.story("继电器数据")
    @allure.title("获取继电器 1 设置数据 TP_SET_RELAY1")
    def test_get_relay1_data(self):
        with allure.step("发送 dt TP_SET_RELAY1 命令并检查返回数据"):
            logger.info("发送 dt TP_SET_RELAY1 命令")
            result = self.serial.get_relay1_data()
            logger.info(f"返回结果：{result}")
            assert result, "未收到设备响应"


# ==================== Topic 传输时间测试 ====================
@allure.feature("Topic 传输时间测试")
@allure.story("Topic 数据响应时间测量")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("Topic 数据传输时间测量")
@allure.description("""
测试步骤:
1. 通过 dt 指令获取各类 Topic 数据
2. 测量每次命令的端到端往返时间（RTT）
3. 验证响应时间在合理阈值内

测试范围:
- 遥控器数据
- 控制点数据
- 姿态电机数据
- IMU 原始数据
- GPS 原始数据
- 气压计原始数据
- 电池缩放数据
- 数传 RSSI 数据
""")
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "TOPIC_DATA", "TRANSMISSION_TIME")


@pytest.mark.functional
class TestTopicTransmissionTime:
    """
    Topic 传输时间测试 - 测量 dt 命令的端到端往返响应时间

    业务背景：
        通过串口 dt 命令读取各 Topic 数据时，响应时间直接影响调试和验证效率。
        本测试测量各 Topic 命令的端到端往返时间（RTT），包括串口通信开销、
        设备处理时间等，确保数据传输在可接受的时间范围内。

    测试对象：
        - TP_RC_RAW（遥控器原始数据）
        - TP_CTRL_POINT（控制点数据）
        - TP_ATTI_MOTOR（姿态电机数据，含字段解析）
        - TP_IMU_RAW0（IMU 原始数据，含字段解析）
        - TP_GPS_RAW0（GPS 原始数据，含字段解析）
        - TP_BARO_RAW0（气压计原始数据，含字段解析）
        - TP_BATTERY_SCALED（电池缩放数据）
        - TP_TELE_RSSI（数传 RSSI 数据）

    通过标准：
        每个 Topic 的往返时间应 < 5000ms（与 dt 命令超时一致）
    """

    # 传输时间阈值（ms），与 send_command 的 dt 命令超时一致
    TRANSMISSION_TIMEOUT_MS = 5000

    @pytest.fixture(autouse=True)
    def setup_before_test(self, serial_protocol_handler):
        """前置操作 + 后置操作"""
        logger.info("前置操作：初始化协议处理器（传输时间测试）")
        self.serial = serial_protocol_handler
        yield
        logger.info("后置操作：清理测试资源（传输时间测试）")

    # ==================== 遥控器数据 ====================
    @allure.story("遥控器数据")
    @allure.title("测量 TP_RC_RAW 传输时间")
    def test_transmission_time_rc_raw(self):
        with allure.step("发送 dt TP_RC_RAW 并测量响应时间"):
            logger.info("测量 TP_RC_RAW 传输时间")
            result = self.serial.measure_topic_transmission_time("TP_RC_RAW")
            assert result, "未收到设备响应"
            elapsed = result["response_time_ms"]
            logger.info(f"TP_RC_RAW 传输时间: {elapsed}ms")
            allure.attach(str(elapsed), "传输时间(ms)", allure.attachment_type.TEXT)
            assert elapsed < self.TRANSMISSION_TIMEOUT_MS, \
                f"TP_RC_RAW 传输时间 {elapsed}ms 超过阈值 {self.TRANSMISSION_TIMEOUT_MS}ms"

    # ==================== 控制点数据 ====================
    @allure.story("控制点数据")
    @allure.title("测量 TP_CTRL_POINT 传输时间")
    def test_transmission_time_ctrl_point(self):
        with allure.step("发送 dt TP_CTRL_POINT 并测量响应时间"):
            logger.info("测量 TP_CTRL_POINT 传输时间")
            result = self.serial.measure_topic_transmission_time("TP_CTRL_POINT")
            assert result, "未收到设备响应"
            elapsed = result["response_time_ms"]
            logger.info(f"TP_CTRL_POINT 传输时间: {elapsed}ms")
            allure.attach(str(elapsed), "传输时间(ms)", allure.attachment_type.TEXT)
            assert elapsed < self.TRANSMISSION_TIMEOUT_MS, \
                f"TP_CTRL_POINT 传输时间 {elapsed}ms 超过阈值 {self.TRANSMISSION_TIMEOUT_MS}ms"

    # ==================== 姿态电机数据 ====================
    @allure.story("姿态电机数据")
    @allure.title("测量 TP_ATTI_MOTOR 传输时间")
    def test_transmission_time_atti_motor(self):
        with allure.step("发送 dt TP_ATTI_MOTOR 并测量响应时间"):
            logger.info("测量 TP_ATTI_MOTOR 传输时间")
            result = self.serial.measure_topic_transmission_time("TP_ATTI_MOTOR")
            assert result, "未收到设备响应"
            elapsed = result["response_time_ms"]
            logger.info(f"TP_ATTI_MOTOR 传输时间: {elapsed}ms")
            allure.attach(str(elapsed), "传输时间(ms)", allure.attachment_type.TEXT)
            assert elapsed < self.TRANSMISSION_TIMEOUT_MS, \
                f"TP_ATTI_MOTOR 传输时间 {elapsed}ms 超过阈值 {self.TRANSMISSION_TIMEOUT_MS}ms"

    # ==================== IMU 原始数据 ====================
    @allure.story("IMU 数据")
    @allure.title("测量 TP_IMU_RAW0 传输时间")
    def test_transmission_time_imu_raw0(self):
        with allure.step("发送 dt TP_IMU_RAW0 并测量响应时间"):
            logger.info("测量 TP_IMU_RAW0 传输时间")
            result = self.serial.measure_topic_transmission_time("TP_IMU_RAW0")
            assert result, "未收到设备响应"
            elapsed = result["response_time_ms"]
            logger.info(f"TP_IMU_RAW0 传输时间: {elapsed}ms")
            allure.attach(str(elapsed), "传输时间(ms)", allure.attachment_type.TEXT)
            assert elapsed < self.TRANSMISSION_TIMEOUT_MS, \
                f"TP_IMU_RAW0 传输时间 {elapsed}ms 超过阈值 {self.TRANSMISSION_TIMEOUT_MS}ms"

    # ==================== GPS 原始数据 ====================
    @allure.story("GPS 数据")
    @allure.title("测量 TP_GPS_RAW0 传输时间")
    def test_transmission_time_gps_raw0(self):
        with allure.step("发送 dt TP_GPS_RAW0 并测量响应时间"):
            logger.info("测量 TP_GPS_RAW0 传输时间")
            result = self.serial.measure_topic_transmission_time("TP_GPS_RAW0")
            assert result, "未收到设备响应"
            elapsed = result["response_time_ms"]
            logger.info(f"TP_GPS_RAW0 传输时间: {elapsed}ms")
            allure.attach(str(elapsed), "传输时间(ms)", allure.attachment_type.TEXT)
            assert elapsed < self.TRANSMISSION_TIMEOUT_MS, \
                f"TP_GPS_RAW0 传输时间 {elapsed}ms 超过阈值 {self.TRANSMISSION_TIMEOUT_MS}ms"

    # ==================== 气压计原始数据 ====================
    @allure.story("气压计数据")
    @allure.title("测量 TP_BARO_RAW0 传输时间")
    def test_transmission_time_baro_raw0(self):
        with allure.step("发送 dt TP_BARO_RAW0 并测量响应时间"):
            logger.info("测量 TP_BARO_RAW0 传输时间")
            result = self.serial.measure_topic_transmission_time("TP_BARO_RAW0")
            assert result, "未收到设备响应"
            elapsed = result["response_time_ms"]
            logger.info(f"TP_BARO_RAW0 传输时间: {elapsed}ms")
            allure.attach(str(elapsed), "传输时间(ms)", allure.attachment_type.TEXT)
            assert elapsed < self.TRANSMISSION_TIMEOUT_MS, \
                f"TP_BARO_RAW0 传输时间 {elapsed}ms 超过阈值 {self.TRANSMISSION_TIMEOUT_MS}ms"

    # ==================== 电池缩放数据 ====================
    @allure.story("电池数据")
    @allure.title("测量 TP_BATTERY_SCALED 传输时间")
    def test_transmission_time_battery_scaled(self):
        with allure.step("发送 dt TP_BATTERY_SCALED 并测量响应时间"):
            logger.info("测量 TP_BATTERY_SCALED 传输时间")
            result = self.serial.measure_topic_transmission_time("TP_BATTERY_SCALED")
            assert result, "未收到设备响应"
            elapsed = result["response_time_ms"]
            logger.info(f"TP_BATTERY_SCALED 传输时间: {elapsed}ms")
            allure.attach(str(elapsed), "传输时间(ms)", allure.attachment_type.TEXT)
            assert elapsed < self.TRANSMISSION_TIMEOUT_MS, \
                f"TP_BATTERY_SCALED 传输时间 {elapsed}ms 超过阈值 {self.TRANSMISSION_TIMEOUT_MS}ms"

    # ==================== 数传 RSSI 数据 ====================
    @allure.story("数传数据")
    @allure.title("测量 TP_TELE_RSSI 传输时间")
    def test_transmission_time_tele_rssi(self):
        with allure.step("发送 dt TP_TELE_RSSI 并测量响应时间"):
            logger.info("测量 TP_TELE_RSSI 传输时间")
            result = self.serial.measure_topic_transmission_time("TP_TELE_RSSI")
            assert result, "未收到设备响应"
            elapsed = result["response_time_ms"]
            logger.info(f"TP_TELE_RSSI 传输时间: {elapsed}ms")
            allure.attach(str(elapsed), "传输时间(ms)", allure.attachment_type.TEXT)
            assert elapsed < self.TRANSMISSION_TIMEOUT_MS, \
                f"TP_TELE_RSSI 传输时间 {elapsed}ms 超过阈值 {self.TRANSMISSION_TIMEOUT_MS}ms"
