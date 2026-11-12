# -*- coding: utf-8 -*-
"""
test_algo_takeoff_land.py
功能点：测试起降分配与带转弯点的起降分配两类起飞/降落路径生成算法。
算法 DLL 起降分配接口测试套件
==================================
本测试套件覆盖 dmd_algorithm.dll 的起降分配算法：
  - DispLand（起降分配）
  - DispLandTurnPoints（带转弯点的起降分配）

测试场景包括：
  - 正常起降分配
  - 带转弯点的起降分配
  - 起飞/降落模式切换
  - 不同 home_height 参数

运行方式：
  pytest test_algo_takeoff_land.py -v
"""

import os
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List

import pytest
import allure

from utils.logger import log_manager


# ===================== 路径解析 =====================
def _resolve_dll_path() -> Path:
    """根据当前脚本位置向上回溯，解析 DLL 所在目录。"""
    current_file = Path(__file__).resolve()
    base_dir = current_file.parents[4]
    return base_dir / "Physical" / "App"


DLL_PATH = _resolve_dll_path()
log_manager.logger.info(f"当前脚本: {Path(__file__).resolve()}")
log_manager.logger.info(f"DLL 路径: {DLL_PATH}")

if not DLL_PATH.exists():
    raise FileNotFoundError(f"DLL 目录不存在: {DLL_PATH}")
if not (DLL_PATH / "dmd_algorithm.dll").exists():
    raise FileNotFoundError(f"dmd_algorithm.dll 未找到，请将 DLL 放入: {DLL_PATH}")

# ===================== 模块导入 =====================
try:
    from src.Protocol.drama import DLL as dll_module
except ImportError as _import_err:
    log_manager.logger.warning(f"相对导入失败，尝试直接导入 Protocol 模块: {_import_err}")
    _protocol_dir = Path(__file__).parents[2]
    sys.path.append(str(_protocol_dir))
    import DLL as dll_module

DRONE_INFO_STR = """[
    {
        "name": "V3",
        "value": 21,
        "droneParams": [
            {"name": "horizonMaxSpeed", "value": "8", "state": "0"},
            {"name": "verticalUpMaxSpeed", "value": "5", "state": "0"},
            {"name": "safeDis", "value": "1.9", "state": "0"}
        ]
    }
]"""

# ===================== 测试数据工厂 ======================
def get_takeoff_drones() -> List[Dict[str, Any]]:
    """返回起飞场景无人机数据（起点地面，终点空中）。"""
    return [
        {
            "droneType": 21, "droneId": 1, "startTime": 0, "endTime": 1000,
            "horizonAcc": 2.0, "horizonSpeed": 5.0, "verticalAcc": 1.0,
            "verticalSpeed": 2.0, "speed": 5.0,
            "points": [[0.0, 0.0, 5.0], [10.0, 0.0, 30.0]],
            "colors": [[0, 0, 0]],
        },
        {
            "droneType": 21, "droneId": 2, "startTime": 0, "endTime": 1000,
            "horizonAcc": 2.0, "horizonSpeed": 5.0, "verticalAcc": 1.0,
            "verticalSpeed": 2.0, "speed": 5.0,
            "points": [[5.0, 0.0, 5.0], [15.0, 0.0, 30.0]],
            "colors": [[0, 0, 0]],
        },
    ]


def get_land_drones() -> List[Dict[str, Any]]:
    """返回降落场景无人机数据（起点空中，终点地面）。"""
    return [
        {
            "droneType": 21, "droneId": 1, "startTime": 0, "endTime": 1000,
            "horizonAcc": 2.0, "horizonSpeed": 5.0, "verticalAcc": 1.0,
            "verticalSpeed": 2.0, "speed": 5.0,
            "points": [[10.0, 0.0, 30.0], [0.0, 0.0, 5.0]],
            "colors": [[0, 0, 0]],
        },
        {
            "droneType": 21, "droneId": 2, "startTime": 0, "endTime": 1000,
            "horizonAcc": 2.0, "horizonSpeed": 5.0, "verticalAcc": 1.0,
            "verticalSpeed": 2.0, "speed": 5.0,
            "points": [[15.0, 0.0, 30.0], [5.0, 0.0, 5.0]],
            "colors": [[0, 0, 0]],
        },
    ]


# ===================== Pytest Fixtures ======================
@pytest.fixture(scope="module")
def dll():
    """模块级 fixture：初始化 DLL 实例并完成授权。"""
    instance = dll_module.DLL(str(DLL_PATH))
    instance.set_user_drones_info(DRONE_INFO_STR)
    instance.set_user_authorize(True)
    yield instance
    instance.close()


# ===================== DispLand 测试 =====================
@pytest.mark.algo
@pytest.mark.takeoffland
@allure.feature("起降分配算法测试")
@allure.story("DispLand - 起降分配")
class TestDispLand:
    """起降分配（DispLand）接口测试。

    测试目标：验证 disp_takeoff_land 接口的行为。
    已知问题：当前 DLL 中 disp_takeoff_land 为空实现，测试验证其发出 UserWarning。
    """

    @allure.title("起降分配空实现警告测试")
    @allure.description(
        "验证 disp_takeoff_land 当前为空实现，应发出 UserWarning 并返回 None。\n"
        "此测试确认 DLL 未实现的接口有合理的降级行为。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("DispLand", "空实现", "警告")
    def test_disp_takeoff_land_warns(self, dll):
        """DispLand 封装方法当前为空实现，应发出 UserWarning。"""
        
        allure.attach(
            f"【测试数据】\n"
            f"  接口: disp_takeoff_land\n"
            f"  预期结果: 发出 UserWarning，返回 None",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("调用 disp_takeoff_land 并验证警告"):
            with pytest.warns(UserWarning, match="not implemented yet"):
                result = dll.disp_takeoff_land()

        allure.attach(
            f"【测试结果】\n"
            f"  返回值: {result}\n"
            f"  警告: UserWarning (not implemented yet)\n"
            f"  预期: UserWarning + None",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("验证返回值为 None"):
            assert result is None

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ DispLand 空实现正确处理，发出了预期的 UserWarning。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )


# ===================== DispLandTurnPoints 测试 =====================
@pytest.mark.algo
@pytest.mark.takeoffland
@allure.feature("带转弯点的起降分配算法测试")
@allure.story("DispLandTurnPoints - 带转弯点的起降分配")
class TestDispLandTurnPoints:
    """带转弯点的起降分配（DispLandTurnPoints）接口测试。

    测试目标：验证带转弯点的起飞/降落分配逻辑。
    """

    @allure.title("起飞场景带转弯点分配测试")
    @allure.description("验证起飞场景下，带转弯点的起降分配能否正确执行并返回 bool。")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("DispLandTurnPoints", "起飞", "转弯点")
    def test_disp_land_turn_points_takeoff(self, dll):
        """起飞场景带转弯点分配应返回 bool。"""
        
        # ===== 测试数据 =====
        drones = get_takeoff_drones()
        turn_points = [[5.0, 5.0, 15.0]]
        is_takeoff = True
        home_height = -0.1

        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  转弯点数: {len(turn_points)}\n"
            f"  转弯点: {turn_points}\n"
            f"  is_takeoff: {is_takeoff}\n"
            f"  home_height: {home_height}\n"
            f"  预期结果: 返回 bool 类型",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行 DispLandTurnPoints DLL 调用"):
            result = dll.disp_land_turn_points(
                drones, is_takeoff=is_takeoff, home_height=home_height, turn_points=turn_points
            )

        allure.attach(
            f"【测试结果】\n"
            f"  返回值: {result}\n"
            f"  返回类型: {type(result).__name__}\n"
            f"  预期: bool",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("验证返回类型"):
            assert isinstance(result, bool), f"返回类型应为 bool，实际 {type(result)}"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ 起飞场景带转弯点分配成功。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("降落场景带转弯点分配测试")
    @allure.description("验证降落场景下，带转弯点的起降分配能否正确执行并返回 bool。")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("DispLandTurnPoints", "降落", "转弯点")
    def test_disp_land_turn_points_land(self, dll):
        """降落场景带转弯点分配应返回 bool。"""
        
        # ===== 测试数据 =====
        drones = get_land_drones()
        turn_points = [[7.0, 5.0, 15.0]]
        is_takeoff = False
        home_height = -0.1

        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  转弯点数: {len(turn_points)}\n"
            f"  转弯点: {turn_points}\n"
            f"  is_takeoff: {is_takeoff}\n"
            f"  home_height: {home_height}\n"
            f"  预期结果: 返回 bool 类型",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行 DispLandTurnPoints DLL 调用"):
            result = dll.disp_land_turn_points(
                drones, is_takeoff=is_takeoff, home_height=home_height, turn_points=turn_points
            )

        allure.attach(
            f"【测试结果】\n"
            f"  返回值: {result}\n"
            f"  返回类型: {type(result).__name__}\n"
            f"  预期: bool",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("验证返回类型"):
            assert isinstance(result, bool), f"返回类型应为 bool，实际 {type(result)}"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ 降落场景带转弯点分配成功。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("多个转弯点不崩溃测试")
    @allure.severity(allure.severity_level.NORMAL)
    def test_disp_land_turn_points_multiple_turns(self, dll):
        """多个转弯点不应导致崩溃。"""
        with allure.step("准备多个转弯点数据并调用 disp_land_turn_points"):
            drones = get_takeoff_drones()
            turn_points = [[5.0, 0.0, 15.0], [10.0, 5.0, 20.0]]
            is_takeoff = True
            home_height = -0.1

            log_manager.logger.info(f"[输入参数] drones数量: {len(drones)}, turn_points: {turn_points}, is_takeoff: {is_takeoff}, home_height: {home_height}")
            log_manager.logger.info(f"[指针信息] dll 实例地址: {hex(id(dll))}")

            result = dll.disp_land_turn_points(
                drones, is_takeoff=is_takeoff, home_height=home_height, turn_points=turn_points
            )

            log_manager.logger.info(f"[返回值] result: {result}, type: {type(result)}")
            log_manager.logger.info(f"[断言检查] 返回值类型: {type(result)}, 预期: bool")
            assert isinstance(result, bool), f"返回类型应为 bool，实际 {type(result)}"

            allure.attach(
                f"测试结果: {result}\n输入无人机数: {len(drones)}\n转弯点数: {len(turn_points)}",
                name="测试详情",
                attachment_type=allure.attachment_type.TEXT
            )
            log_manager.logger.info("test_disp_land_turn_points_multiple_turns 通过")

    @allure.title("空转弯点列表不崩溃测试")
    @allure.severity(allure.severity_level.NORMAL)
    def test_disp_land_turn_points_empty(self, dll):
        """空转弯点列表不应导致崩溃。"""
        with allure.step("准备空转弯点数据并调用 disp_land_turn_points"):
            drones = get_takeoff_drones()
            turn_points = []
            is_takeoff = True
            home_height = -0.1

            log_manager.logger.info(f"[输入参数] drones数量: {len(drones)}, turn_points: {turn_points}, is_takeoff: {is_takeoff}, home_height: {home_height}")
            log_manager.logger.info(f"[指针信息] dll 实例地址: {hex(id(dll))}")

            result = dll.disp_land_turn_points(
                drones, is_takeoff=is_takeoff, home_height=home_height, turn_points=turn_points
            )

            log_manager.logger.info(f"[返回值] result: {result}, type: {type(result)}")
            log_manager.logger.info(f"[断言检查] 返回值类型: {type(result)}, 预期: bool")
            assert isinstance(result, bool), f"返回类型应为 bool，实际 {type(result)}"

            allure.attach(
                f"测试结果: {result}\n输入无人机数: {len(drones)}\n转弯点数: {len(turn_points)}",
                name="测试详情",
                attachment_type=allure.attachment_type.TEXT
            )
            log_manager.logger.info("test_disp_land_turn_points_empty 通过")

    @allure.title("不同home_height参数不崩溃测试")
    @allure.severity(allure.severity_level.NORMAL)
    def test_disp_land_turn_points_home_height(self, dll):
        """不同 home_height 参数不应导致崩溃。"""
        with allure.step("遍历不同home_height值并调用 disp_land_turn_points"):
            drones = get_takeoff_drones()
            turn_points = [[5.0, 5.0, 15.0]]
            is_takeoff = True
            height_values = [-0.1, 1.0, 2.0]

            log_manager.logger.info(f"[输入参数] drones数量: {len(drones)}, turn_points: {turn_points}, is_takeoff: {is_takeoff}, home_height列表: {height_values}")
            log_manager.logger.info(f"[指针信息] dll 实例地址: {hex(id(dll))}")

            results = {}
            for hgt in height_values:
                result = dll.disp_land_turn_points(
                    drones, is_takeoff=is_takeoff, home_height=hgt, turn_points=turn_points
                )
                results[hgt] = result
                log_manager.logger.info(f"[返回值] home_height={hgt}, result: {result}, type: {type(result)}")
                log_manager.logger.info(f"[断言检查] home_height={hgt} 返回值类型: {type(result)}, 预期: bool")
                assert isinstance(result, bool), f"home_height={hgt} 时返回类型异常"

            allure.attach(
                f"测试结果: {results}\n输入无人机数: {len(drones)}\n转弯点数: {len(turn_points)}",
                name="测试详情",
                attachment_type=allure.attachment_type.TEXT
            )
            log_manager.logger.info("test_disp_land_turn_points_home_height 通过")

    @allure.title("home_height接近goal高度不崩溃测试")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_disp_land_turn_points_invalid_height(self, dll):
        """home_height 接近 goal 高度时不应崩溃。"""
        with allure.step("准备接近goal高度的参数并调用 disp_land_turn_points"):
            drones = [
                {
                    "droneType": 21, "droneId": 1, "startTime": 0, "endTime": 1000,
                    "horizonAcc": 2.0, "horizonSpeed": 5.0, "verticalAcc": 1.0,
                    "verticalSpeed": 2.0, "speed": 5.0,
                    "points": [[0.0, 0.0, 15.0], [10.0, 0.0, 12.0]],
                    "colors": [[0, 0, 0]],
                }
            ]
            is_takeoff = True
            home_height = 10.0
            turn_points = []

            log_manager.logger.info(f"[输入参数] drones数量: {len(drones)}, points: {drones[0]['points']}, is_takeoff: {is_takeoff}, home_height: {home_height}, turn_points: {turn_points}")
            log_manager.logger.info(f"[指针信息] dll 实例地址: {hex(id(dll))}")

            try:
                result = dll.disp_land_turn_points(
                    drones, is_takeoff=is_takeoff, home_height=home_height, turn_points=turn_points
                )

                log_manager.logger.info(f"[返回值] result: {result}, type: {type(result)}")
                log_manager.logger.info(f"[断言检查] 返回值类型: {type(result)}, 预期: bool")
                assert isinstance(result, bool), f"返回类型应为 bool，实际 {type(result)}"

                allure.attach(
                    f"测试结果: {result}\n输入无人机数: {len(drones)}\nhome_height: {home_height}\ngoal高度: 12.0",
                    name="测试详情",
                    attachment_type=allure.attachment_type.TEXT
                )
                log_manager.logger.info(f"test_disp_land_turn_points_invalid_height 通过，结果: {result}")
            except Exception as e:
                pytest.fail(f"无效高度参数不应导致崩溃: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
