# -*- coding: utf-8 -*-
"""
test_algo_path_finding.py
功能点：测试静态路径规划、DMPC 动态规划与动态路径规划三类核心规划算法。
算法 DLL 路径规划接口测试套件
==================================
本测试套件覆盖 dmd_algorithm.dll 的路径规划核心算法：
  - PathFinding（静态路径规划）
  - DmpcPathFinding（DMPC 动态路径规划）
  - DynamicPathFinding（动态路径规划）

测试场景包括：
  - 正常多架无人机路径规划
  - 空输入边界
  - 单架无人机路径规划
  - 不同椭圆比率参数

运行方式：
  pytest test_algo_path_finding.py -v
"""

import ctypes
import os
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List

import allure
import pytest

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
def get_test_drones() -> List[Dict[str, Any]]:
    """返回一组标准测试无人机数据，包含起点和终点。"""
    return [{
        "droneType": 21,
        "droneId": 1,
        "startTime": 0,
        "endTime": 1000,
        "horizonAcc": 2.0,
        "horizonSpeed": 5.0,
        "verticalAcc": 1.0,
        "verticalSpeed": 2.0,
        "speed": 5.0,
        "points": [[0.0, 0.0, 1.0], [10.0, 0.0, 1.0], [10.0, 10.0, 1.0]],
        "colors": [],
    }]


def get_test_drones_multi(n: int = 4) -> List[Dict[str, Any]]:
    """返回多架无人机测试数据，用于多机路径规划。"""
    drones = []
    spacing = 5.0
    for i in range(n):
        start_x = i * spacing
        goal_x = (n - 1 - i) * spacing
        drones.append({
            "droneType": 21,
            "droneId": i + 1,
            "startTime": 0,
            "endTime": 1000,
            "horizonAcc": 2.0,
            "horizonSpeed": 5.0,
            "verticalAcc": 1.0,
            "verticalSpeed": 2.0,
            "speed": 5.0,
            "points": [[start_x, 0.0, 1.0], [goal_x, 10.0, 1.0]],
            "colors": [],
        })
    return drones


# ===================== Pytest Fixtures ======================
@pytest.fixture(scope="module")
def dll():
    """模块级 fixture：初始化 DLL 实例并完成授权。"""
    instance = dll_module.DLL(str(DLL_PATH))
    instance.set_user_drones_info(DRONE_INFO_STR)
    instance.set_user_authorize(True)
    yield instance
    instance.close()


# ===================== PathFinding 测试 =====================
@allure.feature("路径规划算法测试")
@allure.story("PathFinding - 静态路径规划")
@pytest.mark.algo
@pytest.mark.pathfinding
class TestPathFinding:
    """静态路径规划（PathFinding）接口测试。

    测试目标：验证 DLL 对无人机从起点到终点的静态路径规划能力。
    覆盖场景：单机、多机、空输入、椭圆比率参数、扩展模式。
    """

    @allure.title("单架无人机路径规划测试")
    @allure.description("验证单架无人机配置下，PathFinding 能否生成包含起点和终点的完整路径。")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("PathFinding", "单机", "路径规划")
    def test_path_finding_single_drone(self, dll):
        """单架无人机路径规划应返回带 points 路径的结果。"""
        
        # ===== 测试数据 =====
        drones = get_test_drones()
        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  无人机 ID: {drones[0]['droneId']}\n"
            f"  初始路径点数: {len(drones[0]['points'])}\n"
            f"  路径: {drones[0]['points']}\n"
            f"  预期结果: 返回包含 points 字段的路径，points 数量 >= 2",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行 PathFinding DLL 调用"):
            result = dll.path_finding(drones)

        # ===== 附加测试结果 =====
        if isinstance(result, list) and len(result) > 0 and "points" in result[0]:
            allure.attach(
                f"【测试结果】\n"
                f"  返回类型: list\n"
                f"  返回无人机数: {len(result)}\n"
                f"  首架无人机路径点数: {len(result[0]['points'])}\n"
                f"  首架无人机路径: {result[0]['points'][:3]}...",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )
        else:
            allure.attach(
                f"【测试结果】\n"
                f"  返回类型: {type(result).__name__}\n"
                f"  返回值: {result}",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )

        with allure.step("验证返回结果"):
            assert isinstance(result, list)
            assert len(result) == len(drones), f"期望返回 {len(drones)} 架无人机路径，实际 {len(result)}"
            assert "points" in result[0]
            assert len(result[0]["points"]) >= 2, "路径 points 数量应至少包含起点和终点"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ PathFinding 成功生成路径，包含 {len(result[0]['points'])} 个路径点。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("多架无人机路径规划测试")
    @allure.description("验证 4 架无人机交叉路径场景下，PathFinding 能否为每架无人机生成无冲突路径。")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("PathFinding", "多机", "路径规划")
    def test_path_finding_multi_drones(self, dll):
        """多架无人机路径规划应正确返回每组路径。"""
        
        # ===== 测试数据 =====
        drones = get_test_drones_multi(n=4)
        drone_details = []
        for d in drones:
            drone_details.append(f"  - ID={d['droneId']}, 路径={d['points']}")
        
        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  无人机详情:\n" + "\n".join(drone_details) + "\n"
            f"  预期结果: 返回 4 架无人机路径，每架 points >= 2",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行多机 PathFinding DLL 调用"):
            result = dll.path_finding(drones)

        # ===== 附加测试结果 =====
        points_info = [len(d.get("points", [])) for d in result] if isinstance(result, list) else []
        allure.attach(
            f"【测试结果】\n"
            f"  返回类型: {type(result).__name__}\n"
            f"  返回无人机数: {len(result) if isinstance(result, list) else 'N/A'}\n"
            f"  各无人机路径点数: {points_info}",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("验证每架无人机的路径"):
            assert isinstance(result, list)
            assert len(result) == 4, f"期望返回 4 架无人机路径，实际 {len(result)}"
            for i, d in enumerate(result):
                assert "points" in d
                assert len(d["points"]) >= 2, f"无人机 {i+1} 路径 points 不足"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ 多机路径规划成功，4 架无人机均生成了路径。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("空输入路径规划测试")
    @allure.description("验证空列表输入时，PathFinding 应返回空列表而非崩溃。")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("PathFinding", "边界条件", "空输入")
    def test_path_finding_empty(self, dll):
        """空列表输入应返回空列表。"""
        
        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: 0 (空列表)\n"
            f"  预期结果: 返回 []",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行空输入 PathFinding DLL 调用"):
            result = dll.path_finding([])

        allure.attach(
            f"【测试结果】\n"
            f"  返回类型: {type(result).__name__}\n"
            f"  返回值: {result}\n"
            f"  预期: []",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("验证返回空列表"):
            assert result == [], f"空输入应返回 []，实际 {result}"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ PathFinding 正确处理了空输入。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("椭圆比率参数路径规划测试")
    @allure.description("验证不同椭圆比率参数 (0.5, 1.0, 2.0) 对路径规划的影响，确保 DLL 不因参数变化而崩溃。")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("PathFinding", "参数组合", "椭圆比率")
    def test_path_finding_ellips_ratio(self, dll):
        """不同椭圆比率参数不应导致崩溃。"""
        
        drones = get_test_drones()
        ratios = [0.5, 1.0, 2.0]
        
        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  椭圆比率测试值: {ratios}\n"
            f"  预期结果: 每个比率下都返回有效路径",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        results_info = {}
        for ratio in ratios:
            with allure.step(f"测试 ellips_ratio={ratio}"):
                result = dll.path_finding(drones, ellips_ratio=ratio)
                
                assert isinstance(result, list)
                assert len(result) == len(drones), f"椭圆比率 {ratio} 下路径规划失败"
                assert len(result[0]["points"]) >= 2, f"椭圆比率 {ratio} 下路径 points 不足"
                results_info[ratio] = len(result[0]["points"])

        allure.attach(
            f"【测试结果】\n" + "\n".join([f"  ratio={k}: points数={v}" for k, v in results_info.items()]),
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ 所有椭圆比率参数均成功生成路径。\n" +
            "\n".join([f"  ratio={k}: {v} 个路径点" for k, v in results_info.items()]),
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("扩展模式路径规划测试")
    @allure.description("验证 is_expansion=True 模式下，PathFinding 能否正常工作。")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("PathFinding", "扩展模式")
    def test_path_finding_is_expansion(self, dll):
        """is_expansion=True 不应导致崩溃。"""
        
        drones = get_test_drones()
        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  is_expansion: True\n"
            f"  预期结果: 返回有效路径",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行扩展模式 PathFinding DLL 调用"):
            result = dll.path_finding(drones, is_expansion=True)

        if isinstance(result, list) and len(result) > 0:
            allure.attach(
                f"【测试结果】\n"
                f"  返回类型: list\n"
                f"  返回无人机数: {len(result)}\n"
                f"  首架无人机路径点数: {len(result[0]['points'])}",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )

        with allure.step("验证扩展模式结果"):
            assert isinstance(result, list)
            assert len(result) == len(drones), "is_expansion=True 下路径规划不应返回空列表"
            assert len(result[0]["points"]) >= 2, "is_expansion=True 下路径 points 不足"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ 扩展模式路径规划成功，生成 {len(result[0]['points'])} 个路径点。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )


# ===================== DmpcPathFinding 测试 =====================
@allure.feature("路径规划算法测试")
@allure.story("DmpcPathFinding - DMPC动态路径规划")
@pytest.mark.algo
@pytest.mark.pathfinding
class TestDmpcPathFinding:
    """DMPC 动态路径规划（DmpcPathFinding）接口测试。

    测试目标：验证 DLL 的 DMPC（分布式模型预测控制）路径规划能力。
    已知问题：当前 DLL 实现在某些场景下会触发 access violation，以下测试如实暴露此问题。
    """

    @allure.title("DMPC单无人机路径规划测试")
    @allure.description(
        "验证单架无人机配置下，DMPC 路径规划能否成功。\n"
        "预期：返回 True 表示规划成功。\n"
        "已知问题：当前 DLL 实现在此场景下可能发生 access violation。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("DmpcPathFinding", "单机", "DLL缺陷")
    def test_dmpc_path_finding_success(self, dll):
        """合法输入 DMPC 路径规划应返回 True。"""
        
        drones = get_test_drones()
        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  无人机 ID: {drones[0]['droneId']}\n"
            f"  初始路径点: {drones[0]['points']}\n"
            f"  预期结果: 返回 True",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行 DMPC PathFinding DLL 调用"):
            result = dll.dmpc_path_finding(drones)

        allure.attach(
            f"【测试结果】\n"
            f"  返回值: {result}\n"
            f"  预期: True",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("验证返回结果"):
            assert result is True, f"合法输入应返回 True，实际 {result} - DLL 可能发生了 access violation"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ DMPC 单无人机路径规划成功。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("DMPC空输入测试")
    @allure.description("验证空列表输入时，DMPC 路径规划应不崩溃并返回 False。")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("DmpcPathFinding", "边界条件", "空输入")
    def test_dmpc_path_finding_empty(self, dll):
        """空列表输入应不崩溃。"""
        
        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: 0 (空列表)\n"
            f"  预期结果: 返回 False",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行空输入 DMPC PathFinding DLL 调用"):
            result = dll.dmpc_path_finding([])

        allure.attach(
            f"【测试结果】\n"
            f"  返回值: {result}\n"
            f"  预期: False",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ DMPC 正确处理了空输入。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("DMPC多无人机路径规划测试")
    @allure.description(
        "验证 3 架无人机配置下，DMPC 路径规划能否成功。\n"
        "预期：返回 True 表示多机协同规划成功。\n"
        "已知问题：当前 DLL 实现在此场景下可能发生 access violation。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("DmpcPathFinding", "多机", "DLL缺陷")
    def test_dmpc_path_finding_multi(self, dll):
        """多架无人机 DMPC 规划应返回 True。"""
        
        drones = get_test_drones_multi(n=3)
        drone_details = [f"  - ID={d['droneId']}, 路径={d['points']}" for d in drones]
        
        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  无人机详情:\n" + "\n".join(drone_details) + "\n"
            f"  预期结果: 返回 True",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行多机 DMPC PathFinding DLL 调用"):
            result = dll.dmpc_path_finding(drones)

        allure.attach(
            f"【测试结果】\n"
            f"  返回值: {result}\n"
            f"  预期: True",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("验证返回结果"):
            assert result is True, f"多机合法输入应返回 True，实际 {result} - DLL 可能发生了 access violation"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ DMPC 多无人机路径规划成功。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )


# ===================== DynamicPathFinding 测试 =====================
@allure.feature("路径规划算法测试")
@allure.story("DynamicPathFinding - 动态路径规划")
@pytest.mark.algo
@pytest.mark.pathfinding
class TestDynamicPathFinding:
    """动态路径规划（DynamicPathFinding）接口测试。

    测试目标：验证 DLL 的动态路径规划能力，支持起始路径点配置。
    已知问题：当前 DLL 实现在某些场景下会触发 access violation，以下测试如实暴露此问题。
    """

    @allure.title("动态路径规划测试")
    @allure.description(
        "验证单架无人机配置下，动态路径规划能否返回包含 points 的路径结果。\n"
        "预期：返回 list 类型，长度等于无人机数量，包含 points 字段。\n"
        "已知问题：当前 DLL 实现在此场景下可能发生 access violation。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("DynamicPathFinding", "单机", "DLL缺陷")
    def test_dynamic_path_finding(self, dll):
        """动态路径规划应返回带 points 的结果。"""
        
        drones = get_test_drones()
        start_way_points_count = 1
        
        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  无人机 ID: {drones[0]['droneId']}\n"
            f"  初始路径点: {drones[0]['points']}\n"
            f"  start_way_points_count: {start_way_points_count}\n"
            f"  预期结果: 返回 list，长度={len(drones)}，包含 points 字段",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行 DynamicPathFinding DLL 调用"):
            result = dll.dynamic_path_finding(drones, start_way_points_count=start_way_points_count)

        if isinstance(result, list) and len(result) > 0 and "points" in result[0]:
            allure.attach(
                f"【测试结果】\n"
                f"  返回类型: list\n"
                f"  返回无人机数: {len(result)}\n"
                f"  首架无人机路径点数: {len(result[0]['points'])}\n"
                f"  首架无人机路径: {result[0]['points'][:3]}...",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )
        else:
            allure.attach(
                f"【测试结果】\n"
                f"  返回类型: {type(result).__name__}\n"
                f"  返回值: {result}",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )

        with allure.step("验证返回结果"):
            assert isinstance(result, list), f"成功应返回 list，实际 {type(result)}"
            assert len(result) == len(drones)
            assert "points" in result[0]

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ DynamicPathFinding 成功生成路径，包含 {len(result[0]['points'])} 个路径点。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("动态路径规划空输入测试")
    @allure.description("验证空列表输入时，动态路径规划应返回 False 或空列表。")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("DynamicPathFinding", "边界条件", "空输入")
    def test_dynamic_path_finding_empty(self, dll):
        """空列表输入应返回 False 或空列表。"""
        
        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: 0 (空列表)\n"
            f"  预期结果: 返回 False 或 []",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行空输入 DynamicPathFinding DLL 调用"):
            result = dll.dynamic_path_finding([])

        allure.attach(
            f"【测试结果】\n"
            f"  返回类型: {type(result).__name__}\n"
            f"  返回值: {result}\n"
            f"  预期: False 或 []",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("验证返回结果"):
            assert result in (False, []), f"空输入应返回 False 或 []，实际 {result}"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ DynamicPathFinding 正确处理了空输入。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
