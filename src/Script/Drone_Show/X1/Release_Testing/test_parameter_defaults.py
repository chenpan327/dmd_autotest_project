# coding: utf-8

"""
关键飞控参数默认值批量验证（串口协议）

业务背景：
    飞控固件出厂时内置一组经过标定的默认参数值，这些参数直接影响飞行稳定性、
    控制精度和安全性。参数值在固件升级、配置迁移或异常写入后可能被意外修改，
    因此需要在每次发布前验证关键参数的当前值是否符合预期。

    本测试通过串口 CLI 的 pp 命令逐个读取参数值，与两套基准值交叉比对：
    - DEFAULT_VALUES: 固件出厂默认值，匹配则 WARNING（参数未被配置）
    - TEST_VALUES:   测试期望值，匹配则 PASS（参数已按测试要求配置）

    不匹配任一基准值时 FAIL，确保参数值既非"未配置"也非"未知变更"。

测试对象：
    - 加速度控制参数: ACC_XY_D, ACC_XY_MAX, ACC_XY_P
    - 角速率控制参数: P_RATE_D, P_RATE_I, P_RATE_P, R_RATE_D, R_RATE_I, R_RATE_P
    - 位置/速度控制参数: POS_XY_KP, VEL_DW_MAX, VEL_UP_MAX, VEL_XY_KP, VEL_XY_MAX, PLT_VELXY_MAX
    - 降落检测参数: LD_ADJ_PEG, LD_ADJ_RHGT, LD_ADJ_SPD, LD_ADJ_TIM, LD_ADJ_VEG, LD_ADJ_VER_CK
    - 控制缩放参数: LD_PCTRL_SCA, LD_VCTRL_SCA, LD_ACTRL_SCA
    - 降落速度参数: LD_MTD_SPD, LD_VTD_SPD
    - 航向控制参数: TCD_HATT_EN

协议格式参考：
    driver/tools/CLI_COMMANDS_REFERENCE.md
"""

import pytest
import allure
from utils.logger import logger


# ============================================================================
# 基准参数值
# ============================================================================

# 固件出厂默认值（匹配 → WARNING：参数未被配置，仍为出厂状态）
DEFAULT_VALUES = {
    # 加速度控制
    "ACC_XY_D":       0.02,
    "ACC_XY_MAX":     10.0,
    "ACC_XY_P":       0.6,
    # Pitch 角速率控制
    "P_RATE_D":       0.005,
    "P_RATE_I":       0.15,
    "P_RATE_P":       0.21,
    # Roll 角速率控制
    "R_RATE_D":       0.005,
    "R_RATE_I":       0.15,
    "R_RATE_P":       0.23,
    # 位置/速度控制
    "POS_XY_KP":      0.9,
    "VEL_DW_MAX":     5.0,
    "VEL_UP_MAX":     6.0,
    "VEL_XY_KP":      1.7,
    "VEL_XY_MAX":     10.0,
    "PLT_VELXY_MAX":  8.0,
    # 降落检测
    "LD_ADJ_PEG":     0.05,
    "LD_ADJ_RHGT":    0.15,
    "LD_ADJ_SPD":     0.15,
    "LD_ADJ_TIM":     4.0,
    "LD_ADJ_VEG":     0.2,
    "LD_ADJ_VER_CK":  0.22,
    # 控制缩放
    "LD_PCTRL_SCA":   1.4,
    "LD_VCTRL_SCA":   1.058,
    "LD_ACTRL_SCA":   1.2,
    # 降落速度
    "LD_MTD_SPD":     1.2,
    "LD_VTD_SPD":     4.5,
    # 航向控制
    "TCD_HATT_EN":    0.0,
}

# 测试期望值（匹配 → PASS：参数已按测试要求配置）
TEST_VALUES = {
    # 加速度控制
    "ACC_XY_D":       0.01,
    "ACC_XY_MAX":     7.0,
    "ACC_XY_P":       0.5,
    # Pitch 角速率控制
    "P_RATE_D":       0.0025,
    "P_RATE_I":       0.2,
    "P_RATE_P":       0.26,
    # Roll 角速率控制
    "R_RATE_D":       0.0025,
    "R_RATE_I":       0.2,
    "R_RATE_P":       0.26,
    # 位置/速度控制
    "POS_XY_KP":      0.6,
    "VEL_DW_MAX":     3.0,
    "VEL_UP_MAX":     5.0,
    "VEL_XY_KP":      1.4,
    "VEL_XY_MAX":     6.0,
    "PLT_VELXY_MAX":  5.5,
    # 降落检测
    "LD_ADJ_PEG":     1.0,
    "LD_ADJ_RHGT":    0.0,
    "LD_ADJ_SPD":     0.4,
    "LD_ADJ_TIM":     3.0,
    "LD_ADJ_VEG":     1.0,
    "LD_ADJ_VER_CK":  1.0,
    # 控制缩放
    "LD_PCTRL_SCA":   1.0,
    "LD_VCTRL_SCA":   1.0,
    "LD_ACTRL_SCA":   1.0,
    # 降落速度
    "LD_MTD_SPD":     0.8,
    "LD_VTD_SPD":     2.0,
    # 航向控制
    "TCD_HATT_EN":    1.0,
}

# 浮点比较相对容差
FLOAT_REL_TOLERANCE = 1e-4

# 所有受测参数名（从两套基准值取并集，确保一致）
ALL_PARAM_NAMES = sorted(set(DEFAULT_VALUES) | set(TEST_VALUES))


# ============================================================================
# 辅助函数
# ============================================================================

def _matches(value: float, reference: float) -> bool:
    """判断 value 是否在 reference 的相对容差范围内匹配。"""
    return value == pytest.approx(reference, rel=FLOAT_REL_TOLERANCE)


# ============================================================================
# 测试类
# ============================================================================

@allure.feature("串口协议参数默认值验证")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "SERIAL_PROTOCOL", "PARAM_DEFAULT")
@pytest.mark.functional
class TestParamDefaults:
    """
    关键飞控参数默认值批量验证。

    通过串口 CLI 的 pp <name> 逐个读取 27 个关键飞控参数，与两套基准值交叉比对：
    - DEFAULT_VALUES（固件出厂默认值）：匹配 → WARNING（参数仍为出厂状态，未被配置）
    - TEST_VALUES（测试期望值）：匹配 → PASS（参数已按测试要求配置）
    - 均不匹配 → FAIL（参数值异常）

    浮点比较使用 pytest.approx（相对容差 1e-4）。
    """

    @pytest.fixture(autouse=True)
    def setup_before_test(self, serial_protocol_handler):
        logger.info("前置操作：初始化协议处理器")
        self.serial = serial_protocol_handler
        yield
        logger.info("后置操作：清理测试资源")

    @allure.story("参数默认值")
    @allure.title("关键飞控参数默认值批量验证")
    @allure.description("""
    通过串口 CLI 的 pp <name> 逐个读取 27 个关键飞控参数，与两套基准值交叉比对：

    判定规则：
    - 匹配 TEST_VALUES（测试期望值）→ PASS
    - 匹配 DEFAULT_VALUES（出厂默认值）→ WARNING（参数仍为出厂状态）
    - 均不匹配 → FAIL（参数值异常）

    验证范围：
    - 加速度控制 (3): ACC_XY_D, ACC_XY_MAX, ACC_XY_P
    - 角速率控制 (6): P_RATE_D/I/P, R_RATE_D/I/P
    - 位置/速度控制 (6): POS_XY_KP, VEL_DW_MAX, VEL_UP_MAX, VEL_XY_KP, VEL_XY_MAX, PLT_VELXY_MAX
    - 降落检测 (6): LD_ADJ_PEG, LD_ADJ_RHGT, LD_ADJ_SPD, LD_ADJ_TIM, LD_ADJ_VEG, LD_ADJ_VER_CK
    - 控制缩放 (3): LD_PCTRL_SCA, LD_VCTRL_SCA, LD_ACTRL_SCA
    - 降落速度 (2): LD_MTD_SPD, LD_VTD_SPD
    - 航向控制 (1): TCD_HATT_EN

    浮点比较使用 pytest.approx（相对容差 1e-4）。
    """)
    def test_parameter_default_values(self):
        failed_params = []       # 不匹配任一基准值
        warning_params = []      # 匹配出厂默认值（未被配置）
        passed_params = []       # 匹配测试期望值

        for param_name in ALL_PARAM_NAMES:
            with allure.step(f"读取参数 {param_name}"):
                logger.info(f"发送 pp {param_name} 命令")
                result = self.serial.get_parameter(param_name)
                assert result is not None, f"pp {param_name} 命令执行失败（无响应）"
                assert param_name in result, f"pp {param_name} 响应中未找到参数 {param_name}"

                value_str = result[param_name]
                try:
                    actual_value = float(value_str)
                except (ValueError, TypeError):
                    failed_params.append(f"{param_name}: 无法解析响应值 ({value_str})")
                    logger.error(f"{param_name} 解析失败，响应: {result}")
                    continue

                default_val = DEFAULT_VALUES.get(param_name)
                test_val = TEST_VALUES.get(param_name)

                matched_test = test_val is not None and _matches(actual_value, test_val)
                matched_default = default_val is not None and _matches(actual_value, default_val)

                if matched_test:
                    passed_params.append(param_name)
                    logger.info(f"{param_name}: {actual_value} 匹配测试期望值 {test_val} → PASS")
                elif matched_default:
                    warning_params.append(
                        f"{param_name}: 当前={actual_value}（出厂默认={default_val}）")
                    logger.warning(
                        f"{param_name}: {actual_value} 匹配出厂默认值 {default_val} → WARNING（未被配置）")
                else:
                    failed_params.append(
                        f"{param_name}: 当前={actual_value}, 默认={default_val}, 期望测试={test_val}")
                    logger.error(
                        f"{param_name}: {actual_value} 不匹配任一基准值 → FAIL")

        # --- 汇总 ---
        total = len(ALL_PARAM_NAMES)
        logger.info(f"参数验证完成: 通过={len(passed_params)}/{total}, "
                    f"警告(默认值)={len(warning_params)}/{total}, "
                    f"失败={len(failed_params)}/{total}")

        if warning_params:
            logger.warning(f"以下 {len(warning_params)} 个参数仍为出厂默认值: {warning_params}")

        if failed_params:
            logger.error(f"以下 {len(failed_params)} 个参数值与预期不符: {failed_params}")

        assert len(failed_params) == 0, \
            f"以下 {len(failed_params)} 个参数值与预期不符: {failed_params}"
