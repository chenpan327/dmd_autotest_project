# -*- coding: utf-8 -*-
"""
test_algo_safety_check.py
功能点：测试常规安全检查、烟花特效安全检查与密集编队安全检查三类检测能力。
算法 DLL 安全检查接口测试套件
==================================
本测试套件覆盖 dmd_algorithm.dll 的安全检查算法：
  - SafetyCheck（常规安全检查，含最小间距、碰撞检测）
  - FireworkSafetyCheck（烟花特效安全检查）
  - DenseSafetyCheck（密集编队安全检查）

测试场景包括：
  - 正常数据安全检查
  - CSV 结果导出
  - 空输入边界
  - 不存在的 CSV 路径容错

运行方式：
  pytest test_algo_safety_check.py -v
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
    """返回一组标准测试无人机数据。"""
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


def get_test_drones_multi() -> List[Dict[str, Any]]:
    """返回多架无人机测试数据，用于碰撞检测。"""
    return [
        {
            "droneType": 21, "droneId": 1, "startTime": 0, "endTime": 1000,
            "horizonAcc": 2.0, "horizonSpeed": 5.0, "verticalAcc": 1.0,
            "verticalSpeed": 2.0, "speed": 5.0,
            "points": [[0.0, 0.0, 1.0], [5.0, 0.0, 1.0]],
            "colors": [],
        },
        {
            "droneType": 21, "droneId": 2, "startTime": 0, "endTime": 1000,
            "horizonAcc": 2.0, "horizonSpeed": 5.0, "verticalAcc": 1.0,
            "verticalSpeed": 2.0, "speed": 5.0,
            "points": [[5.0, 0.0, 1.0], [0.0, 0.0, 1.0]],
            "colors": [],
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


# ===================== SafetyCheck 测试 =====================
@allure.feature("安全检查算法测试")
@allure.story("SafetyCheck - 常规安全检查")
@pytest.mark.algo
@pytest.mark.safety
class TestSafetyCheck:
    """常规安全检查（SafetyCheck）接口测试。

    测试目标：验证 DLL 对无人机编队的碰撞/安全距离检查能力。
    注意：当前 DLL 实现在某些场景下会触发 access violation，以下测试如实暴露此问题。
    """

    @allure.title("单架无人机安全检查测试")
    @allure.description(
        "验证单架无人机配置下，SafetyCheck 能否正常返回检查结果。\n"
        "预期：返回包含 min_dis 和 min_dis_value 的 CheckResultPy 对象。\n"
        "已知问题：当前 DLL 实现在此场景下可能发生 access violation。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("SafetyCheck", "单机", "DLL缺陷")
    def test_safety_check_single_drone(self, dll, tmp_path):
        """单架无人机安全检查应返回 CheckResultPy 实例。"""
        
        # ===== 测试数据 =====
        drones = get_test_drones()
        csv_file = tmp_path / "safety.csv"

        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  无人机类型: {drones[0]['droneType']}\n"
            f"  无人机 ID: {drones[0]['droneId']}\n"
            f"  路径点数: {len(drones[0]['points'])}\n"
            f"  CSV 路径: {csv_file}\n"
            f"  参数: start=0, end=1000, interval=500, simplify=False\n"
            f"  预期结果: 返回 CheckResultPy 对象 (min_dis, min_dis_value)",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行 SafetyCheck DLL 调用"):
            log_manager.logger.info(f"[DLL调用] SafetyCheck, drones={len(drones)}")
            
            res = dll.safety_check(
                drone_info_list=drones,
                csv_path=str(csv_file),
                start=0, end=1000, interval=500,
            )

        log_manager.logger.info(f"[返回值] result={res}, type={type(res).__name__ if res else 'None'}")

        # ===== 附加 DLL 返回结果 =====
        if res is not None:
            allure.attach(
                f"【测试结果】\n"
                f"  返回类型: {type(res).__name__}\n"
                f"  min_dis: {res.min_dis}\n"
                f"  min_dis_value: {res.min_dis_value}\n"
                f"  预期: CheckResultPy 对象",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )
        else:
            allure.attach(
                f"【测试结果】\n"
                f"  返回: None\n"
                f"  ⚠️ DLL 可能发生了 access violation 或内部错误",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )

        with allure.step("验证返回结果"):
            assert res is not None, "SafetyCheck 返回 None - DLL 可能发生了 access violation"
            assert hasattr(res, "min_dis"), "CheckResultPy 缺少 min_dis 属性"
            assert hasattr(res, "min_dis_value"), "CheckResultPy 缺少 min_dis_value 属性"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ SafetyCheck 成功返回检查结果。\n"
            f"  最小安全距离: {res.min_dis}\n"
            f"  最小距离值: {res.min_dis_value:.4f}m",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("多架无人机安全检查测试")
    @allure.description(
        "验证多架无人机配置下，SafetyCheck 能否正常返回检查结果。\n"
        "预期：返回包含 min_dis 和 min_dis_value 的 CheckResultPy 对象。\n"
        "已知问题：当前 DLL 实现在此场景下可能发生 access violation。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("SafetyCheck", "多机", "DLL缺陷")
    def test_safety_check_multi_drones(self, dll, tmp_path):
        """多架无人机安全检查应返回有效结果。"""
        
        # ===== 测试数据 =====
        drones = get_test_drones_multi()
        csv_file = tmp_path / "safety_multi.csv"
        drone_details = [f"  - ID={d['droneId']}, 路径点={len(d['points'])}" for d in drones]

        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  无人机详情:\n" + "\n".join(drone_details) + "\n"
            f"  CSV 路径: {csv_file}\n"
            f"  参数: start=0, end=1000, interval=500\n"
            f"  预期结果: 返回 CheckResultPy 对象",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行多机 SafetyCheck DLL 调用"):
            res = dll.safety_check(
                drone_info_list=drones,
                csv_path=str(csv_file),
                start=0, end=1000, interval=500,
            )

        # ===== 附加测试结果 =====
        if res is not None:
            allure.attach(
                f"【测试结果】\n"
                f"  返回类型: {type(res).__name__}\n"
                f"  min_dis: {res.min_dis}\n"
                f"  min_dis_value: {res.min_dis_value}",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )
        else:
            allure.attach(
                f"【测试结果】\n"
                f"  返回: None\n"
                f"  ⚠️ DLL 可能发生了 access violation",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )

        with allure.step("验证返回结果"):
            assert res is not None, "SafetyCheck 返回 None - DLL 可能发生了 access violation"
            assert hasattr(res, "min_dis"), "CheckResultPy 缺少 min_dis 属性"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ 多机 SafetyCheck 成功返回检查结果。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("空输入安全检查测试")
    @allure.description("验证空列表输入时，SafetyCheck 应不崩溃并返回 None。")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("SafetyCheck", "边界条件", "空输入")
    def test_safety_check_empty(self, dll, tmp_path):
        """空列表输入不应导致崩溃。"""
        
        csv_file = tmp_path / "safety_empty.csv"
        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: 0 (空列表)\n"
            f"  CSV 路径: {csv_file}\n"
            f"  预期结果: 返回 None",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行空输入 SafetyCheck DLL 调用"):
            res = dll.safety_check(
                drone_info_list=[],
                csv_path=str(csv_file),
                start=0, end=1000, interval=500,
            )

        allure.attach(
            f"【测试结果】\n"
            f"  返回: {res}\n"
            f"  预期: None",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("验证返回 None"):
            assert res is None, f"空输入应返回 None，实际 {res}"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ SafetyCheck 正确处理了空输入。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("不存在CSV路径容错测试")
    @allure.description("验证传入不存在的 CSV 路径时，SafetyCheck 应不崩溃。")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("SafetyCheck", "容错", "无效路径")
    def test_safety_check_nonexistent_csv(self, dll):
        """传入不存在的 CSV 路径不应导致崩溃。"""
        
        drones = get_test_drones()
        bad_path = r"C:\nonexistent\path\test.csv"

        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  CSV 路径: {bad_path} (不存在)\n"
            f"  预期结果: 返回 None 或 CheckResultPy",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行无效 CSV 路径 SafetyCheck DLL 调用"):
            res = dll.safety_check(
                drone_info_list=drones,
                csv_path=bad_path,
                start=0, end=1000, interval=500,
            )

        if res is not None:
            allure.attach(
                f"【测试结果】\n"
                f"  返回类型: {type(res).__name__}\n"
                f"  min_dis: {res.min_dis}\n"
                f"  min_dis_value: {res.min_dis_value}",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )
        else:
            allure.attach(
                f"【测试结果】\n"
                f"  返回: None",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )

        with allure.step("验证不崩溃"):
            # 此测试主要验证不崩溃，返回值可以是 None 或 CheckResultPy
            if res is not None:
                assert hasattr(res, "min_dis"), "CheckResultPy 缺少 min_dis 属性"
                assert hasattr(res, "min_dis_value"), "CheckResultPy 缺少 min_dis_value 属性"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ SafetyCheck 正确处理了不存在的 CSV 路径，未崩溃。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("Simplify参数安全检查测试")
    @allure.description(
        "验证 simplify=True 参数时，SafetyCheck 应不崩溃。\n"
        "已知问题：当前 DLL 实现在此场景下可能发生 access violation。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("SafetyCheck", "参数组合", "simplify", "DLL缺陷")
    def test_safety_check_simplify(self, dll, tmp_path):
        """simplify=True 参数不应导致崩溃。"""
        
        drones = get_test_drones()
        csv_file = tmp_path / "safety_simp.csv"

        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  CSV 路径: {csv_file}\n"
            f"  参数: start=0, end=1000, interval=500, simplify=True\n"
            f"  预期结果: 返回 CheckResultPy 对象",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行 simplify=True SafetyCheck DLL 调用"):
            res = dll.safety_check(
                drone_info_list=drones,
                csv_path=str(csv_file),
                start=0, end=1000, interval=500,
                simplify=True,
            )

        if res is not None:
            allure.attach(
                f"【测试结果】\n"
                f"  返回类型: {type(res).__name__}\n"
                f"  min_dis: {res.min_dis}\n"
                f"  min_dis_value: {res.min_dis_value}",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )
        else:
            allure.attach(
                f"【测试结果】\n"
                f"  返回: None\n"
                f"  ⚠️ DLL 可能发生了 access violation",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )

        with allure.step("验证返回结果"):
            assert res is not None, "SafetyCheck 返回 None - DLL 可能发生了 access violation"
            assert hasattr(res, "min_dis"), "CheckResultPy 缺少 min_dis 属性"
            assert hasattr(res, "min_dis_value"), "CheckResultPy 缺少 min_dis_value 属性"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ simplify=True SafetyCheck 成功返回检查结果。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )


# ===================== FireworkSafetyCheck 测试 =====================
@allure.feature("安全检查算法测试")
@allure.story("FireworkSafetyCheck - 烟花安全检查")
@pytest.mark.algo
@pytest.mark.safety
class TestFireworkSafetyCheck:
    """烟花安全检查（FireworkSafetyCheck）接口测试。

    测试目标：验证 DLL 对无人机烟花数据的安全检查能力。
    """

    @allure.title("无烟花数据安全检查测试")
    @allure.description("验证无烟花数据的无人机应返回 False。")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("FireworkSafetyCheck", "无烟花")
    def test_fireworks_safety_check_no_fireworks(self, dll, tmp_path):
        """无烟花数据的无人机应返回 False。"""
        
        drones = get_test_drones()
        csv_file = tmp_path / "firework.csv"

        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  无人机类型: {drones[0]['droneType']}\n"
            f"  无人机 ID: {drones[0]['droneId']}\n"
            f"  烟花数据: 无（colors 为空）\n"
            f"  CSV 路径: {csv_file}\n"
            f"  预期结果: 返回 False",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行烟花安全检查 DLL 调用"):
            result = dll.fireworks_safety_check(drones, str(csv_file))

        allure.attach(
            f"【测试结果】\n"
            f"  返回值: {result}\n"
            f"  返回类型: {type(result).__name__}\n"
            f"  预期: False",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("验证返回 False"):
            assert result is False, f"无烟花数据应返回 False，实际 {result}"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ 烟花安全检查正确返回 False（无人机无烟花数据）。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )


# ===================== DenseSafetyCheck 测试 =====================
@allure.feature("安全检查算法测试")
@allure.story("DenseSafetyCheck - 密集安全检查")
@pytest.mark.algo
@pytest.mark.safety
class TestDenseSafetyCheck:
    """密集安全检查（DenseSafetyCheck）接口测试。

    测试目标：验证 DLL 对无人机编队的密集安全检查能力。
    """

    @allure.title("多架无人机密集安全检查测试")
    @allure.description("验证多架无人机配置下，密集安全检查能否返回有效的分布列表。")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("DenseSafetyCheck", "多机")
    def test_dense_safety_check_multi(self, dll):
        """多架无人机密集检查应返回分布列表。"""
        
        drones = get_test_drones_multi()
        check_range = 2.18
        drone_details = [f"  - ID={d['droneId']}, 路径点={d['points']}" for d in drones]

        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  无人机详情:\n" + "\n".join(drone_details) + "\n"
            f"  check_range: {check_range}\n"
            f"  预期结果: 返回非空分布列表，元素为 int",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行密集安全检查 DLL 调用"):
            result = dll.dense_safety_check(drones, check_range=check_range)

        if result:
            allure.attach(
                f"【测试结果】\n"
                f"  返回类型: {type(result).__name__}\n"
                f"  分布元素数量: {len(result)}\n"
                f"  分布元素类型: {[type(x).__name__ for x in result]}\n"
                f"  分布值: {result}",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )
        else:
            allure.attach(
                f"【测试结果】\n"
                f"  返回: {result}\n"
                f"  预期: 非空列表",
                name="测试结果",
                attachment_type=allure.attachment_type.TEXT
            )

        with allure.step("验证返回结果"):
            assert len(result) > 0, f"多机密集检查应返回非空分布，实际 {result}"
            assert all(isinstance(x, int) for x in result), f"分布元素应为 int"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ 密集安全检查成功，返回 {len(result)} 个分布值。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.title("空输入密集安全检查测试")
    @allure.description("验证空列表输入时，密集安全检查应返回空列表。")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("DenseSafetyCheck", "边界条件", "空输入")
    def test_dense_safety_check_empty(self, dll):
        """空列表应返回空列表。"""
        
        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: 0 (空列表)\n"
            f"  预期结果: 返回 []",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行空输入密集安全检查 DLL 调用"):
            result = dll.dense_safety_check([])

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
            f"  ✅ 密集安全检查正确处理了空输入。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
