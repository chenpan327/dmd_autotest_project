# coding: utf-8
"""
灯语 notify_flash 命令全覆盖测试。

覆盖指示灯枚举 0-87，分为两段：
- 0-73  → 指示灯（Indicator LEDs）：基础状态、初始化、未解锁/已解锁、错误/异常、
           校准与测试、充电、ICT 工厂测试
- 74-87 → 表演灯（Performance LEDs）：Failsafe 状态、TDOA 校准、投放、ICT 测试

互斥规则：指示灯 (0-73) 和表演灯 (74-87) 互斥 —— 设置其中任意一个，另一个自动
恢复为正常模式（NOTIFY_STATE_NONE / LT_NONE）。

设置后每 100ms 固件会强制覆盖当前灯语状态，测试验证命令可正常发送
并收到有效响应。测试完成后发送 notify_flash 88 恢复正常状态。
"""

import time

import pytest
import allure
from utils.logger import logger


# ============================================================================
# 灯语枚举数据表
# ============================================================================

# --- 基础状态 ---
LED_STATE_NONE = (0, "NOTIFY_STATE_NONE", "灭", "无状态/默认")

# --- 初始化阶段 (1-14)：白底 + 故障模块色 ---
LED_INIT_STATES = [
    (1,  "NOTIFY_STATE_INIT_START",   "白常亮",              "初始化开始"),
    (2,  "INIT_SDCARD_FAILED",        "白→红→灭 循环",       "SD卡故障"),
    (3,  "INIT_GPS_FAILED",           "白→绿→灭 循环",       "GPS故障"),
    (4,  "INIT_TEL_FAILED",           "白→绿→红→灭 循环",    "数传故障"),
    (5,  "INIT_BNO_FAILED",           "白→绿→蓝→灭 循环",    "BNO(IMU)故障"),
    (6,  "INIT_LPPC_FAILED",          "白→绿→蓝→灭 循环",    "LPPC故障 (同BNO)"),
    (7,  "INIT_ESC_FAILED",           "白→蓝→灭 循环",       "电调故障"),
    (8,  "INIT_IMU_FAILED",           "白→黄→红→灭 循环",    "IMU故障"),
    (9,  "INIT_COMPASS_FAILED",       "白→黄→绿→灭 循环",    "罗盘故障"),
    (10, "INIT_BARO_FAILED",          "白→黄→蓝→灭 循环",    "气压计故障"),
    (11, "INIT_TOF_FAILED",           "白→黄→白→灭 循环",    "TOF故障"),
    (12, "INIT_UWB_FAILED",           "白→黄→青→灭 循环",    "UWB故障"),
    (13, "INIT_CAMERA_FAILED",        "白→黄→紫→灭 循环",    "相机故障"),
    (14, "INIT_MODULE_FAILED",        "白→青→灭 循环",       "模块总故障"),
]

# --- 未解锁状态 (15-29)：慢闪=正常 / 常亮+黄=GCS断连 / 快闪=无网络/升级 ---
LED_DISARMED_STATES = [
    (15, "DISARMED_NORM",               "蓝慢闪",              "未解锁/无定位"),
    (16, "DISARMED_3DFIX",              "绿慢闪",              "未解锁/3D定位"),
    (17, "DISARMED_RTK_FLOAT",          "青慢闪",              "未解锁/RTK浮点"),
    (18, "DISARMED_RTK_FIX",            "紫慢闪",              "未解锁/RTK固定"),
    (19, "DISARMED_NORM_GCS_FAIL",      "蓝→黄→灭 常亮循环",   "GCS断连/未解锁"),
    (20, "DISARMED_3DFIX_GCS_FAIL",     "绿→黄→灭 常亮循环",   "GCS断连/3D定位"),
    (21, "DISARMED_RTK_FLOAT_GCS_FAIL", "青→黄→灭 常亮循环",   "GCS断连/RTK浮点"),
    (22, "DISARMED_RTK_FIX_GCS_FAIL",   "紫→黄→灭 常亮循环",   "GCS断连/RTK固定"),
    (23, "DISARMED_NORM_NET_FAIL",      "蓝快闪",              "无网络/未解锁"),
    (24, "DISARMED_3DFIX_NET_FAIL",     "绿快闪",              "无网络/3D定位"),
    (25, "DISARMED_RTK_FLOAT_NET_FAIL", "青快闪",              "无网络/RTK浮点"),
    (26, "DISARMED_RTK_FIX_NET_FAIL",   "紫快闪",              "无网络/RTK固定"),
    (27, "GPS_WAITING",                 "蓝快闪",              "GPS等待模式"),
    (28, "GPS_UPDATING",                "绿快闪",              "GPS固件升级中"),
    (29, "SUBMOD_UPDATING",             "青快闪",              "子模块固件升级中"),
]

# --- 已解锁状态 (30-33)：颜色与 DISARMED 一致但改为常亮 ---
LED_ARMED_STATES = [
    (30, "ARMED_NORM",       "蓝常亮", "已解锁/无精确定位"),
    (31, "ARMED_3DFIX",      "绿常亮", "已解锁/3D定位"),
    (32, "ARMED_RTK_FLOAT",  "青常亮", "已解锁/RTK浮点"),
    (33, "ARMED_RTK_FIX",    "紫常亮", "已解锁/RTK固定"),
]

# --- 错误状态 (34-36) ---
LED_ERROR_STATES = [
    (34, "ERROR",       "红常亮",          "通用错误"),
    (35, "ERROR_HARD",  "红→黄→灭 循环",    "硬件错误 (传感器/伴机)"),
    (36, "ERROR_SOFT",  "红→蓝→灭 循环",    "软件错误 (EKF/围栏/时间同步)"),
]

# --- 异常状态 (37-38) ---
LED_EXCEPTION_STATES = [
    (37, "EXCEPTION_LOWPOWER",  "黄→绿→灭 循环", "低电量警告"),
    (38, "EXCEPTION_DISTURB",   "黄→蓝→灭 循环", "磁干扰警告"),
]

# --- 校准与测试 (39-57) ---
LED_CALIBRATION_STATES = [
    # 加速度计校准
    (39, "CAL_ACC_ROTATE1",    "红→绿 循环",        "加速度计翻转方向1"),
    (40, "CAL_ACC_ROTATE2",    "红→蓝 循环",        "加速度计翻转方向2"),
    (41, "CAL_ACC_HOLD",       "黄常亮",             "加速度计保持静止"),
    # 罗盘校准
    (42, "CAL_CMP_ALIGN",      "黄快闪",             "罗盘对准方向"),
    (43, "CAL_CMP_ROTATE",     "红→绿→蓝 循环",      "罗盘旋转校准"),
    (44, "CAL_CMP_SUCCESS",    "黄常亮",             "罗盘校准成功"),
    (45, "CAL_CMP_FAIL",       "红常亮",             "罗盘校准失败"),
    (46, "CAL_CMP_INIT_FAIL",  "黄→红 循环",         "校准初始化失败"),
    (47, "CAL_IMU",            "白快闪",             "IMU校准中"),
    # 相机标定
    (48, "CAL_CAM_DETECT_TAG", "蓝→白→黄 循环",      "检测标定标签"),
    (49, "CAL_CAM_GET_TAG",    "绿→紫 循环",         "获取标定标签"),
    (50, "CAL_CAM_SUCCESS",    "黄常亮",             "相机标定成功"),
    (51, "CAL_CAM_FAIL",       "红常亮",             "相机标定失败"),
    # 电调校准
    (52, "CAL_ESC",            "红→绿→蓝 循环",      "电调校准中"),
    (53, "CAL_ESC_SUCCESS",    "黄常亮",             "电调校准成功"),
    (54, "CAL_ESC_FAIL",       "蓝→绿→红→灭 循环",   "电调校准失败"),
    # 温漂测试
    (55, "TEST_TEMP_DOING",    "白常亮",             "温漂测试中"),
    (56, "TEST_TEMP_SUCCESS",  "绿常亮",             "温漂测试通过"),
    (57, "TEST_TEMP_FAIL",     "红常亮",             "温漂测试失败"),
]

# --- 警告 (58) ---
LED_WARNING_STATES = [
    (58, "WARN_CAMERA_UNHEALTHY", "黄→红→灭 循环", "相机不健康"),
]

# --- 充电状态 (59-62) ---
LED_CHARGING_STATES = [
    (59, "CHARGING_ABNORMAL", "蓝常亮",  "充电异常"),
    (60, "CHARGING_NORMAL",   "白常亮",  "充电中"),
    (61, "CHARGING_FULL",     "绿常亮",  "充电已满"),
    (62, "HIGH_TEMP",         "红快闪",  "电池高温(>=60C)"),
]

# --- ICT 工厂测试 (63-73) ---
LED_ICT_STATES = [
    (63, "ICT_ERROR",            "红常亮",  "ICT通用错误"),
    (64, "ICT_ONLY_CMP1_ERROR",  "黄常亮",  "仅罗盘1错误"),
    (65, "ICT_ONLY_CMP0_ERROR",  "黄快闪",  "仅罗盘0错误"),
    (66, "ICT_BQ40Z50_ERROR",    "红快闪",  "BQ40Z50电量计错误"),
    (67, "ICT_DISCHARGE_ERROR",  "黄快闪",  "放电测试错误"),
    (68, "ICT_IGNITER_ERROR",    "黄常亮",  "点火器错误"),
    (69, "ICT_RADIO_ERROR",      "红快闪",  "电台错误"),
    (70, "ICT_RTCM_ERROR",       "红慢闪",  "RTCM错误"),
    (71, "ICT_MB_RUNNING",       "绿慢闪",  "主板运行中"),
    (72, "ICT_CORRECT",          "绿常亮",  "ICT测试通过"),
    (73, "ICT_WAIT_DOWN",        "蓝常亮",  "等待下电"),
]

# --- 表演灯 (74-87)：仅在 ekf_light_enable==1 时启用 ---
LED_PERFORMANCE_STATES = [
    (74, "LT_NONE",               "灭 (LOF)",           "无事件",                   "默认/正常"),
    (75, "LT_PREARM_WARN",        "红快闪 (LQF)",       "预解锁警告",               "motor_prearm_warn=1"),
    (76, "LT_FS_HIG_ARM",         "红→绿 常亮 (LON)",   "高严重failsafe+已解锁+无导航", "fs_high触发+ARMED+!nav_valid"),
    (77, "LT_FS_HIG_DISARM",      "红→灭 常亮 (LON)",   "高严重failsafe+已加锁",    "fs_high触发+DISARMED"),
    (78, "LT_FS_MID",             "红→黄 常亮 (LON)",   "中严重failsafe+已加锁",    "fs_mid触发+DISARMED"),
    (79, "LT_FS_LOW",             "黄→灭 常亮 (LON)",   "低严重failsafe+已加锁",    "fs_low触发+DISARMED"),
    (80, "LT_FS_HIG_SAFING",      "红→白 常亮 (LON)",   "Safing中(无导航)",         "fs_high+ARMED+STAB+摇杆>=40%+!nav_valid"),
    (81, "LT_FS_HIG_SAFING_REC",  "绿→白 常亮 (LON)",   "Safing中(有导航)",         "fs_high+ARMED+STAB+摇杆>=40%+nav_valid"),
    (82, "LT_FS_HIG_REC",         "绿慢闪 (LSF)",       "高严重恢复",               "fs_high+ARMED+nav_valid (非RTL)"),
    (83, "LT_FS_HIG_REC_RTL",     "绿快闪 (LQF)",       "高严重恢复(RTL)",          "fs_high+ARMED+nav_valid+RTL模式"),
    (84, "LT_CAL_TDOA_FAIL",      "红慢闪 (LSF)",       "TDOA校准失败",             "tdoa_calibrate_state=FAIL"),
    (85, "LT_CAL_TDOA_SUCCESS",   "绿慢闪 (LSF)",       "TDOA校准成功",             "tdoa_calibrate_state=SUCCESS"),
    (86, "LT_DROP",               "灭 (LON)",           "投放/降落",                "failsafe_drop=1"),
    (87, "LT_ICT_MB_PL_TESTING",  "红→绿→蓝 常亮 (LON)","ICT主板负载测试",          "ICT测试"),
]


def _build_indicator_leds() -> list[tuple[int, str, str, str, str]]:
    """组装全部指示灯数据 (0-73)，返回 (id, enum_name, light_pattern, meaning, category)。"""
    return (
        [(*LED_STATE_NONE, "基础状态")] +
        [(i, n, p, m, "初始化阶段") for i, n, p, m in LED_INIT_STATES] +
        [(i, n, p, m, "未解锁状态") for i, n, p, m in LED_DISARMED_STATES] +
        [(i, n, p, m, "已解锁状态") for i, n, p, m in LED_ARMED_STATES] +
        [(i, n, p, m, "错误状态")   for i, n, p, m in LED_ERROR_STATES] +
        [(i, n, p, m, "异常状态")   for i, n, p, m in LED_EXCEPTION_STATES] +
        [(i, n, p, m, "校准与测试") for i, n, p, m in LED_CALIBRATION_STATES] +
        [(i, n, p, m, "警告")       for i, n, p, m in LED_WARNING_STATES] +
        [(i, n, p, m, "充电状态")   for i, n, p, m in LED_CHARGING_STATES] +
        [(i, n, p, m, "ICT工厂测试") for i, n, p, m in LED_ICT_STATES]
    )


def _build_performance_leds() -> list[tuple[int, str, str, str, str]]:
    """组装表演灯数据 (74-87)，返回 (id, enum_name, light_pattern, meaning, trigger_condition)。"""
    return [(i, n, p, m, t) for i, n, p, m, t in LED_PERFORMANCE_STATES]


# 预构建查找表，key 为枚举 id
INDICATOR_LED_MAP: dict[int, tuple[int, str, str, str, str]] = {
    item[0]: item for item in _build_indicator_leds()
}
PERFORMANCE_LED_MAP: dict[int, tuple[int, str, str, str, str]] = {
    item[0]: item for item in _build_performance_leds()
}

# ============================================================================
# 测试类
# ============================================================================


@allure.feature("灯语控制测试")
@allure.severity(allure.severity_level.NORMAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "LED_FLASH", "NOTIFY_FLASH")


@pytest.mark.functional
class TestLedFlash:
    """
    灯语 notify_flash 命令全覆盖测试。

    覆盖指示灯枚举 0-87，分为两段：
    - 0-73  → 指示灯（Indicator LEDs）：基础状态、初始化、未解锁/已解锁、错误/异常、
               校准与测试、充电、ICT 工厂测试
    - 74-87 → 表演灯（Performance LEDs）：Failsafe 状态、TDOA 校准、投放、ICT 测试

    互斥规则：指示灯 (0-73) 和表演灯 (74-87) 互斥，设置一方另一方自动恢复为正常模式。

    设置后每 100ms 固件会强制覆盖当前灯语状态，测试完成后
    发送 notify_flash 88 恢复正常。
    """

    @pytest.fixture(autouse=True)
    def setup_before_test(self, serial_protocol_handler):
        logger.info("前置操作：初始化协议处理器")
        self.serial = serial_protocol_handler
        yield
        logger.info("后置操作：清理测试资源")

    # ==================== 指示灯 0-73 ====================
    @allure.story("指示灯控制")
    @allure.title("指示灯全覆盖测试 (0-73)")
    @allure.description(
        "遍历 notify_flash 0 到 73，覆盖全部指示灯枚举："
        "基础状态、初始化阶段(1-14)、未解锁(15-29)、已解锁(30-33)、"
        "错误(34-36)、异常(37-38)、校准与测试(39-57)、警告(58)、"
        "充电(59-62)、ICT工厂测试(63-73)。"
    )
    def test_indicator_leds_0_to_73(self):
        indicator_leds = _build_indicator_leds()
        failed_ids = []

        for led_id, enum_name, light_pattern, meaning, category in indicator_leds:
            with allure.step(f"[{category}] {enum_name} (id={led_id}): {light_pattern} — {meaning}"):
                logger.info(
                    f"发送 notify_flash {led_id} → [{category}] {enum_name} | "
                    f"灯语: {light_pattern} | 含义: {meaning}"
                )
                result = self.serial.notify_flash(led_id)
                if not result:
                    logger.warning(f"notify_flash {led_id} ({enum_name}) 失败")
                    failed_ids.append((led_id, enum_name, category))
                # 等待 10s，给测试人员观察灯语变化的时间
                time.sleep(10)

        if failed_ids:
            logger.error(f"指示灯失败列表: {failed_ids}")
        assert len(failed_ids) == 0, (
            f"以下 {len(failed_ids)} 个指示灯 ID 操作失败: {failed_ids}"
        )

    # ==================== 表演灯 74-87 ====================
    @allure.story("表演灯控制")
    @allure.title("表演灯全覆盖测试 (74-87)")
    @allure.description(
        "遍历 notify_flash 74 到 87，覆盖全部表演灯枚举："
        "Failsafe 各级别(75-83)、TDOA 校准(84-85)、投放(86)、ICT测试(87)。"
        "注意：表演灯仅在 ekf_light_enable==1 时启用。"
    )
    def test_performance_leds_74_to_87(self):
        performance_leds = _build_performance_leds()
        failed_ids = []

        for led_id, enum_name, light_pattern, meaning, trigger in performance_leds:
            with allure.step(f"{enum_name} (id={led_id}): {light_pattern} — {meaning}"):
                logger.info(
                    f"发送 notify_flash {led_id} → {enum_name} | "
                    f"灯语: {light_pattern} | 含义: {meaning} | 触发: {trigger}"
                )
                result = self.serial.notify_flash(led_id)
                if not result:
                    logger.warning(f"notify_flash {led_id} ({enum_name}) 失败")
                    failed_ids.append((led_id, enum_name, trigger))
                # 等待 10s，给测试人员观察灯语变化的时间
                time.sleep(10)

        if failed_ids:
            logger.error(f"表演灯失败列表: {failed_ids}")
        assert len(failed_ids) == 0, (
            f"以下 {len(failed_ids)} 个表演灯 ID 操作失败: {failed_ids}"
        )

    # ==================== 恢复正常 ====================
    @allure.story("灯语控制")
    @allure.title("恢复正常状态 (notify_flash 88)")
    @allure.description("发送 notify_flash 88 恢复正常指示灯状态，解除 100ms 强制覆盖。")
    def test_restore_normal_flash_88(self):
        with allure.step("发送 notify_flash 88"):
            logger.info("发送 notify_flash 88 命令，恢复正常状态")
            result = self.serial.notify_flash(88)
            logger.info(f"notify_flash 88 返回结果：{result}")
            assert result, "notify_flash 88 恢复正常状态失败"
