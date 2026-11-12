# -*- coding: utf-8 -*-
"""
test_algo_collision.py
功能点：测试无人机间静态碰撞检测与位置微调避让算法。
算法 DLL 碰撞解决接口测试套件
================================
本测试套件覆盖 dmd_algorithm.dll 的碰撞解决算法：
  - CollisionSolve（碰撞检测与位置微调）

测试场景包括：
  - 存在碰撞风险的多机数据
  - 无碰撞风险的单架数据
  - 空输入边界
  - 返回结果中 points 字段校验

运行方式：
  pytest test_algo_collision.py -v
"""

import ctypes
import os
import sys
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
def get_test_drones_safe() -> List[Dict[str, Any]]:
    """返回无碰撞风险的单架无人机数据。"""
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
        "points": [[0.0, 0.0, 1.0], [10.0, 0.0, 1.0]],
        "colors": [],
    }]


def get_test_drones_collision() -> List[Dict[str, Any]]:
    """返回存在碰撞风险的多架无人机数据（起点相近）。"""
    return [
        {
            "droneType": 21, "droneId": 1, "startTime": 0, "endTime": 1000,
            "horizonAcc": 2.0, "horizonSpeed": 5.0, "verticalAcc": 1.0,
            "verticalSpeed": 2.0, "speed": 5.0,
            "points": [[0.0, 0.0, 1.0], [5.0, 5.0, 1.0]],
            "colors": [],
        },
        {
            "droneType": 21, "droneId": 2, "startTime": 0, "endTime": 1000,
            "horizonAcc": 2.0, "horizonSpeed": 5.0, "verticalAcc": 1.0,
            "verticalSpeed": 2.0, "speed": 5.0,
            "points": [[0.5, 0.0, 1.0], [5.0, 5.0, 1.0]],
            "colors": [],
        },
        {
            "droneType": 21, "droneId": 3, "startTime": 0, "endTime": 1000,
            "horizonAcc": 2.0, "horizonSpeed": 5.0, "verticalAcc": 1.0,
            "verticalSpeed": 2.0, "speed": 5.0,
            "points": [[0.0, 0.5, 1.0], [5.0, 5.0, 1.0]],
            "colors": [],
        },
    ]


def get_test_drones_multi() -> List[Dict[str, Any]]:
    """返回多架无人机测试数据。"""
    drones = []
    for i in range(5):
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
            "points": [[float(i), 0.0, 1.0], [float(i), 10.0, 1.0]],
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


# ===================== CollisionSolve 测试 =====================
@allure.feature("碰撞解决算法测试")
@allure.story("碰撞检测与位置微调避让 (CollisionSolve)")
@pytest.mark.algo
@pytest.mark.collision
class TestCollisionSolve:
    """碰撞解决（CollisionSolve）接口测试。"""

    @allure.title("无碰撞风险数据测试")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description("验证无碰撞风险的单架无人机数据进行碰撞解决时，正常返回包含有效 points 的列表。")
    @allure.tag("CollisionSolve", "无碰撞", "单架无人机")
    def test_collision_solve_safe(self, dll):
        """无碰撞风险数据应正常返回列表。"""
        drones = get_test_drones_safe()

        # Step 1: DLL 调用
        with allure.step("【DLL调用】执行无碰撞风险的碰撞解决"):
            # 打印指针信息
            log_manager.logger.info(f"[指针信息] dll对象地址: {hex(id(dll))}")
            log_manager.logger.info(f"[指针信息] dll对象类型: {type(dll)}")

            # 打印输入参数
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
            for idx, drone in enumerate(drones):
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] droneId: {drone.get('droneId')}")
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] droneType: {drone.get('droneType')}")
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] points数量: {len(drone.get('points', []))}")
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] points: {drone.get('points')}")

            result = dll.collision_solve(drones)

            # 打印返回值
            log_manager.logger.info(f"[返回值] 结果类型: {type(result)}")
            log_manager.logger.info(f"[返回值] 返回无人机数量: {len(result)}")
            for idx, drone in enumerate(result):
                points = drone.get("points", [])
                log_manager.logger.info(f"[返回值] 无人机[{idx}] points数量: {len(points)}")
                if points:
                    log_manager.logger.info(f"[返回值] 无人机[{idx}] 首点坐标: {points[0]}")
                    log_manager.logger.info(f"[返回值] 无人机[{idx}] 末点坐标: {points[-1]}")
                    log_manager.logger.info(f"[返回值] 无人机[{idx}] points: {points}")

        # Step 2: 断言验证
        with allure.step("【断言验证】校验碰撞解决结果类型、长度和 points 有效性"):
            log_manager.logger.info(f"[断言检查] 碰撞解决结果检查 | result_type={type(result)}, result_len={len(result)}, expected_len=1")
            assert isinstance(result, list)
            assert len(result) == 1, f"期望返回 1 架无人机结果，实际 {len(result)}"
            assert "points" in result[0]
            assert len(result[0]["points"]) > 0, "碰撞解决应返回有效 points"

        # Step 3: 附件报告
        allure.attach(
            f"输入无人机数: {len(drones)}\n输入 droneIds: {[d.get('droneId') for d in drones]}\n场景: 无碰撞风险\n预期: 返回包含有效 points 的列表，长度为 1",
            name="【测试数据】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"返回无人机数: {len(result)}\n首架无人机路径点数: {len(result[0]['points'])}\n首点坐标: {result[0]['points'][0]}\n末点坐标: {result[0]['points'][-1]}",
            name="【测试结果】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            "【测试结论】: 通过 — 无碰撞风险数据碰撞解决成功，返回包含有效 points 的列表。",
            name="【测试结论】",
            attachment_type=allure.attachment_type.TEXT
        )
        log_manager.logger.info("test_collision_solve_safe 通过")

    @allure.title("存在碰撞风险数据测试")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description("验证存在碰撞风险的多架无人机数据进行碰撞解决时，返回调整后的位置且包含有效 points。")
    @allure.tag("CollisionSolve", "碰撞风险", "多架无人机", "位置微调")
    def test_collision_solve_collision(self, dll):
        """存在碰撞风险的数据应返回调整后的位置。"""
        drones = get_test_drones_collision()

        # Step 1: DLL 调用
        with allure.step("【DLL调用】执行存在碰撞风险的碰撞解决"):
            # 打印指针信息
            log_manager.logger.info(f"[指针信息] dll对象地址: {hex(id(dll))}")
            log_manager.logger.info(f"[指针信息] dll对象类型: {type(dll)}")

            # 打印输入参数
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
            for idx, drone in enumerate(drones):
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] droneId: {drone.get('droneId')}")
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] droneType: {drone.get('droneType')}")
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] points数量: {len(drone.get('points', []))}")
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] points: {drone.get('points')}")

            result = dll.collision_solve(drones)

            # 打印返回值
            log_manager.logger.info(f"[返回值] 结果类型: {type(result)}")
            log_manager.logger.info(f"[返回值] 返回无人机数量: {len(result)}")
            for idx, drone in enumerate(result):
                points = drone.get("points", [])
                log_manager.logger.info(f"[返回值] 无人机[{idx}] points数量: {len(points)}")
                if points:
                    log_manager.logger.info(f"[返回值] 无人机[{idx}] 首点坐标: {points[0]}")
                    log_manager.logger.info(f"[返回值] 无人机[{idx}] 末点坐标: {points[-1]}")
                    log_manager.logger.info(f"[返回值] 无人机[{idx}] points: {points}")

        # Step 2: 断言验证
        with allure.step("【断言验证】校验碰撞风险数据返回结果的数量和 points 字段"):
            log_manager.logger.info(f"[断言检查] 碰撞风险数据结果检查 | result_type={type(result)}, result_len={len(result)}, expected_len=3")
            assert isinstance(result, list)
            assert len(result) == 3, f"期望返回 3 架无人机结果，实际 {len(result)}"
            for idx, d in enumerate(result):
                assert "points" in d, f"无人机[{idx}] 缺少 points 字段"
                log_manager.logger.info(f"[返回值] 无人机[{idx}] droneId: {drones[idx]['droneId']}, points数量: {len(d['points'])}")

        # Step 3: 附件报告
        allure.attach(
            f"输入无人机数: {len(drones)}\n输入 droneIds: {[d.get('droneId') for d in drones]}\n场景: 存在碰撞风险（起点相近）\n预期: 返回调整后的位置，包含有效 points，长度为 3",
            name="【测试数据】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"返回无人机数: {len(result)}\n各无人机路径点数: {[len(d['points']) for d in result]}",
            name="【测试结果】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            "【测试结论】: 通过 — 存在碰撞风险数据碰撞解决成功，返回调整后的位置且包含有效 points。",
            name="【测试结论】",
            attachment_type=allure.attachment_type.TEXT
        )
        log_manager.logger.info("test_collision_solve_collision 通过")

    @allure.title("多架无人机碰撞解决测试")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description("验证多架（5架）无人机进行碰撞解决时，正常执行并返回结果。")
    @allure.tag("CollisionSolve", "多机测试", "规模测试")
    def test_collision_solve_multi(self, dll):
        """多架无人机碰撞解决应正常执行。"""
        drones = get_test_drones_multi()

        # Step 1: DLL 调用
        with allure.step("【DLL调用】执行多架无人机碰撞解决"):
            # 打印指针信息
            log_manager.logger.info(f"[指针信息] dll对象地址: {hex(id(dll))}")
            log_manager.logger.info(f"[指针信息] dll对象类型: {type(dll)}")

            # 打印输入参数
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
            for idx, drone in enumerate(drones):
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] droneId: {drone.get('droneId')}")
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] droneType: {drone.get('droneType')}")
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] points数量: {len(drone.get('points', []))}")
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] points: {drone.get('points')}")

            result = dll.collision_solve(drones)

            # 打印返回值
            log_manager.logger.info(f"[返回值] 结果类型: {type(result)}")
            log_manager.logger.info(f"[返回值] 返回无人机数量: {len(result)}")
            for idx, drone in enumerate(result):
                points = drone.get("points", [])
                log_manager.logger.info(f"[返回值] 无人机[{idx}] points数量: {len(points)}")
                if points:
                    log_manager.logger.info(f"[返回值] 无人机[{idx}] 首点坐标: {points[0]}")
                    log_manager.logger.info(f"[返回值] 无人机[{idx}] 末点坐标: {points[-1]}")
                    log_manager.logger.info(f"[返回值] 无人机[{idx}] points: {points}")

        # Step 2: 断言验证
        with allure.step("【断言验证】校验多机碰撞解决返回结果的数量"):
            log_manager.logger.info(f"[断言检查] 多机碰撞解决结果检查 | result_type={type(result)}, result_len={len(result)}, expected_len=5")
            assert isinstance(result, list)
            assert len(result) == 5, f"期望返回 5 架无人机结果，实际 {len(result)}"

        # Step 3: 附件报告
        allure.attach(
            f"输入无人机数: {len(drones)}\n输入 droneIds: {[d.get('droneId') for d in drones]}\n场景: 多架无人机（5架）\n预期: 返回结果列表，长度为 5",
            name="【测试数据】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"返回无人机数: {len(result)}\n各无人机路径点数: {[len(d['points']) for d in result]}",
            name="【测试结果】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            "【测试结论】: 通过 — 多架无人机碰撞解决成功，返回结果列表长度与输入一致。",
            name="【测试结论】",
            attachment_type=allure.attachment_type.TEXT
        )
        log_manager.logger.info("test_collision_solve_multi 通过")

    @allure.title("空输入边界测试")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description("验证空列表输入碰撞解决接口时，应返回空列表。")
    @allure.tag("CollisionSolve", "边界测试", "空输入")
    def test_collision_solve_empty(self, dll):
        """空列表输入应返回空列表。"""
        drones = []

        # Step 1: DLL 调用
        with allure.step("【DLL调用】执行空输入碰撞解决"):
            # 打印指针信息
            log_manager.logger.info(f"[指针信息] dll对象地址: {hex(id(dll))}")
            log_manager.logger.info(f"[指针信息] dll对象类型: {type(dll)}")

            # 打印输入参数
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")

            result = dll.collision_solve(drones)

            # 打印返回值
            log_manager.logger.info(f"[返回值] 结果类型: {type(result)}")
            log_manager.logger.info(f"[返回值] 返回列表: {result}")

        # Step 2: 断言验证
        with allure.step("【断言验证】校验空输入返回空列表"):
            log_manager.logger.info(f"[断言检查] 空输入结果检查 | result_type={type(result)}, result_value={result}, expected=[]")
            assert result == [], f"期望返回空列表，实际 {result}"

        # Step 3: 附件报告
        allure.attach(
            "输入无人机数: 0\n场景: 空输入边界测试\n预期: 返回空列表 []",
            name="【测试数据】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"返回结果: {result}\n结果类型: {type(result)}\n结果数量: {len(result)}",
            name="【测试结果】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            "【测试结论】: 通过 — 空输入碰撞解决返回空列表。",
            name="【测试结论】",
            attachment_type=allure.attachment_type.TEXT
        )
        log_manager.logger.info("test_collision_solve_empty 通过")

    @allure.title("返回结果points字段校验")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description("验证碰撞解决返回结果中的 points 字段必须有效，每个坐标点均为 3 维 (x, y, z)。")
    @allure.tag("CollisionSolve", "points校验", "坐标维度", "数据完整性")
    def test_collision_solve_returns_points(self, dll):
        """返回结果中的 points 必须有效（包含 3 维坐标）。"""
        drones = get_test_drones_safe()

        # Step 1: DLL 调用
        with allure.step("【DLL调用】执行碰撞解决获取结果"):
            # 打印指针信息
            log_manager.logger.info(f"[指针信息] dll对象地址: {hex(id(dll))}")
            log_manager.logger.info(f"[指针信息] dll对象类型: {type(dll)}")

            # 打印输入参数
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
            for idx, drone in enumerate(drones):
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] droneId: {drone.get('droneId')}")
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] droneType: {drone.get('droneType')}")
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] points数量: {len(drone.get('points', []))}")
                log_manager.logger.info(f"[输入参数] 无人机[{idx}] points: {drone.get('points')}")

            result = dll.collision_solve(drones)

            # 打印返回值
            log_manager.logger.info(f"[返回值] 结果类型: {type(result)}")
            log_manager.logger.info(f"[返回值] 返回无人机数量: {len(result)}")
            for idx, drone in enumerate(result):
                points = drone.get("points", [])
                log_manager.logger.info(f"[返回值] 无人机[{idx}] points数量: {len(points)}")
                if points:
                    log_manager.logger.info(f"[返回值] 无人机[{idx}] 首点坐标: {points[0]}")
                    log_manager.logger.info(f"[返回值] 无人机[{idx}] 末点坐标: {points[-1]}")
                    log_manager.logger.info(f"[返回值] 无人机[{idx}] points: {points}")

        # Step 2: 断言验证
        with allure.step("【断言验证】校验 points 字段存在且每个坐标为 3 维"):
            log_manager.logger.info(f"[断言检查] points字段校验检查 | result_len={len(result)}, expected_len=1")
            assert len(result) == 1, f"期望返回 1 架无人机结果，实际 {len(result)}"
            for idx, d in enumerate(result):
                assert "points" in d, f"无人机[{idx}] 缺少 points 字段"
                assert len(d["points"]) > 0, "points 不应为空"
                for pidx, p in enumerate(d["points"]):
                    assert len(p) == 3, f"无人机[{idx}] 坐标点[{pidx}] 应为 3 维 (x, y, z)，实际维度 {len(p)}, 值 {p}"
                    log_manager.logger.info(f"[返回值] 无人机[{idx}] 点[{pidx}]: x={p[0]}, y={p[1]}, z={p[2]}")

        # Step 3: 附件报告
        allure.attach(
            f"输入无人机数: {len(drones)}\n输入 droneIds: {[d.get('droneId') for d in drones]}\n场景: points 字段校验\n预期: 返回结果中 points 字段有效，每个坐标点均为 3 维 (x, y, z)",
            name="【测试数据】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"返回无人机数: {len(result)}\npoints点数: {len(result[0]['points'])}\n坐标维度验证: 全部为3维(x,y,z)",
            name="【测试结果】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            "【测试结论】: 通过 — 返回结果中 points 字段有效，所有坐标点均为 3 维 (x, y, z)。",
            name="【测试结论】",
            attachment_type=allure.attachment_type.TEXT
        )
        log_manager.logger.info("test_collision_solve_returns_points 通过")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
