# -*- coding: utf-8 -*-
"""
test_algo_matching.py
功能点：测试基于几何距离的最佳匹配与基于拍卖算法的最佳匹配两种分配策略。
算法 DLL 最佳匹配接口测试套件
================================
本测试套件覆盖 dmd_algorithm.dll 的匹配算法：
  - BestMatch（基于几何距离的最佳匹配）
  - BestMatchAuction（基于拍卖算法的最佳匹配）

测试场景包括：
  - 多架无人机常规匹配
  - 拍卖模式匹配
  - 空输入边界
  - 返回字典的键值类型校验

运行方式：
  pytest test_algo_matching.py -v
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
def get_test_drones_two() -> List[Dict[str, Any]]:
    """返回两架无人机测试数据，用于匹配。"""
    return [
        {
            "droneType": 21, "droneId": 1, "startTime": 0, "endTime": 1000,
            "horizonAcc": 2.0, "horizonSpeed": 5.0, "verticalAcc": 1.0,
            "verticalSpeed": 2.0, "speed": 5.0,
            "points": [[0.0, 0.0, 1.0], [10.0, 10.0, 1.0]],
            "colors": [],
        },
        {
            "droneType": 21, "droneId": 2, "startTime": 0, "endTime": 1000,
            "horizonAcc": 2.0, "horizonSpeed": 5.0, "verticalAcc": 1.0,
            "verticalSpeed": 2.0, "speed": 5.0,
            "points": [[10.0, 0.0, 1.0], [0.0, 10.0, 1.0]],
            "colors": [],
        },
    ]


def get_test_drones_multi(n: int = 6) -> List[Dict[str, Any]]:
    """返回多架无人机测试数据，用于大规模匹配。"""
    drones = []
    spacing = 3.0
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


# ===================== BestMatch 测试 =====================
@pytest.mark.algo
@pytest.mark.matching
@allure.feature("匹配算法测试")
@allure.story("基于几何距离的最佳匹配 (BestMatch)")
class TestBestMatch:
    """常规最佳匹配（BestMatch）接口测试。"""

    @allure.title("两架无人机最佳匹配测试")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description("验证两架无人机进行几何距离最佳匹配时，返回字典的键值均映射到输入的 droneId 集合，且匹配数量为 2。")
    @allure.tag("BestMatch", "两机匹配", "几何距离")
    def test_best_match_two_drones(self, dll):
        """两架无人机匹配应返回字典，键值应映射到输入的 droneId 集合。"""
        drones = get_test_drones_two()
        input_ids = {d["droneId"] for d in drones}

        # Step 1: DLL 调用
        with allure.step("【DLL调用】执行两架无人机最佳匹配"):
            log_manager.logger.info(f"[输入] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[输入] droneIds: {input_ids}")
            log_manager.logger.info(f"[输入] auction: False")
            log_manager.logger.info(f"[指针] dll地址: {hex(id(dll))}")

            result = dll.best_match(drones)

            log_manager.logger.info(f"[输出] 匹配结果类型: {type(result)}")
            log_manager.logger.info(f"[输出] 匹配结果长度: {len(result)}")
            log_manager.logger.info(f"[输出] 结果 keys: {set(result.keys())}")
            log_manager.logger.info(f"[输出] 结果 values: {set(result.values())}")
            log_manager.logger.info(f"[输出] 完整匹配字典: {result}")

        # Step 2: 断言验证
        with allure.step("【断言验证】校验匹配结果的键值均在输入 droneId 集合中"):
            log_manager.logger.info(f"[对比] keys ⊆ input_ids: {set(result.keys()) <= input_ids}")
            log_manager.logger.info(f"[对比] values ⊆ input_ids: {set(result.values()) <= input_ids}")

            assert isinstance(result, dict)
            assert len(result) == 2, f"期望 2 条匹配，实际 {len(result)}"
            assert set(result.keys()) <= input_ids, f"匹配 key 必须在输入 droneId 集合中: {result}"
            assert set(result.values()) <= input_ids, f"匹配 value 必须在输入 droneId 集合中: {result}"

        # Step 3: 附件报告
        allure.attach(
            f"输入无人机数: {len(drones)}\n输入 droneIds: {input_ids}\n拍卖模式: False\n预期: 返回字典，键值均在输入 droneId 集合中，匹配数量为 2",
            name="【测试数据】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"匹配结果: {result}\n结果 keys: {set(result.keys())}\n结果 values: {set(result.values())}\n结果数量: {len(result)}",
            name="【测试结果】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            "【测试结论】: 通过 — 两架无人机最佳匹配成功，返回字典的键值均映射到输入的 droneId 集合。",
            name="【测试结论】",
            attachment_type=allure.attachment_type.TEXT
        )
        log_manager.logger.info("test_best_match_two_drones 通过")

    @allure.title("多架无人机最佳匹配测试")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description("验证多架（6架）无人机进行几何距离最佳匹配时，返回有效字典且匹配数量等于输入无人机数量。")
    @allure.tag("BestMatch", "多机匹配", "几何距离", "规模测试")
    def test_best_match_multi_drones(self, dll):
        """多架无人机匹配应返回有效字典。"""
        drones = get_test_drones_multi(n=6)
        input_ids = {d["droneId"] for d in drones}

        # Step 1: DLL 调用
        with allure.step("【DLL调用】执行多架无人机最佳匹配"):
            log_manager.logger.info(f"[输入] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[输入] droneIds: {input_ids}")
            log_manager.logger.info(f"[输入] auction: False")
            log_manager.logger.info(f"[指针] dll地址: {hex(id(dll))}")

            result = dll.best_match(drones)

            log_manager.logger.info(f"[输出] 匹配结果类型: {type(result)}")
            log_manager.logger.info(f"[输出] 匹配结果长度: {len(result)}")
            log_manager.logger.info(f"[输出] 结果 keys: {set(result.keys())}")
            log_manager.logger.info(f"[输出] 结果 values: {set(result.values())}")
            log_manager.logger.info(f"[输出] 完整匹配字典: {result}")

        # Step 2: 断言验证
        with allure.step("【断言验证】校验返回类型为字典且匹配数量等于输入数量"):
            assert isinstance(result, dict)
            assert len(result) == 6, f"期望 6 条匹配，实际 {len(result)}"

        # Step 3: 附件报告
        allure.attach(
            f"输入无人机数: {len(drones)}\n输入 droneIds: {input_ids}\n拍卖模式: False\n预期: 返回字典，匹配数量为 6",
            name="【测试数据】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"匹配结果: {result}\n结果 keys: {set(result.keys())}\n结果 values: {set(result.values())}\n结果数量: {len(result)}",
            name="【测试结果】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            "【测试结论】: 通过 — 多架无人机最佳匹配成功，返回有效字典且匹配数量等于输入数量。",
            name="【测试结论】",
            attachment_type=allure.attachment_type.TEXT
        )
        log_manager.logger.info("test_best_match_multi_drones 通过")

    @allure.title("空输入最佳匹配测试")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description("验证空列表输入最佳匹配接口时，应返回空字典。")
    @allure.tag("BestMatch", "边界测试", "空输入")
    def test_best_match_empty(self, dll):
        """空列表输入应返回空字典。"""
        # Step 1: DLL 调用
        with allure.step("【DLL调用】执行空输入最佳匹配"):
            log_manager.logger.info("[输入] 无人机数量: 0")
            log_manager.logger.info("[输入] auction: False")
            log_manager.logger.info(f"[指针] dll地址: {hex(id(dll))}")

            result = dll.best_match([])

            log_manager.logger.info(f"[输出] 匹配结果类型: {type(result)}")
            log_manager.logger.info(f"[输出] 匹配结果长度: {len(result)}")
            log_manager.logger.info(f"[输出] 完整匹配字典: {result}")

        # Step 2: 断言验证
        with allure.step("【断言验证】校验空输入返回空字典"):
            assert result == {}

        # Step 3: 附件报告
        allure.attach(
            "输入无人机数: 0\n拍卖模式: False\n预期: 返回空字典 {}",
            name="【测试数据】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"匹配结果: {result}\n结果类型: {type(result)}\n结果数量: {len(result)}",
            name="【测试结果】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            "【测试结论】: 通过 — 空输入最佳匹配返回空字典。",
            name="【测试结论】",
            attachment_type=allure.attachment_type.TEXT
        )
        log_manager.logger.info("test_best_match_empty 通过")

    @allure.title("匹配结果大小一致性测试")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description("验证最佳匹配返回的字典大小与输入无人机数量一致。")
    @allure.tag("BestMatch", "一致性测试", "大小校验")
    def test_best_match_result_size(self, dll):
        """匹配结果字典大小应与输入无人机数量一致。"""
        drones = get_test_drones_two()
        input_ids = {d["droneId"] for d in drones}

        # Step 1: DLL 调用
        with allure.step("【DLL调用】执行匹配结果大小一致性检查"):
            log_manager.logger.info(f"[输入] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[输入] droneIds: {input_ids}")
            log_manager.logger.info(f"[输入] auction: False")
            log_manager.logger.info(f"[指针] dll地址: {hex(id(dll))}")

            result = dll.best_match(drones)

            log_manager.logger.info(f"[输出] 匹配结果类型: {type(result)}")
            log_manager.logger.info(f"[输出] 匹配结果长度: {len(result)}")
            log_manager.logger.info(f"[输出] 结果 keys: {set(result.keys())}")
            log_manager.logger.info(f"[输出] 结果 values: {set(result.values())}")
            log_manager.logger.info(f"[输出] 完整匹配字典: {result}")

        # Step 2: 断言验证
        with allure.step("【断言验证】校验匹配结果字典大小与输入数量一致"):
            assert isinstance(result, dict)
            assert len(result) == len(drones), f"期望 {len(drones)} 条匹配，实际 {len(result)}"

        # Step 3: 附件报告
        allure.attach(
            f"输入无人机数: {len(drones)}\n输入 droneIds: {input_ids}\n拍卖模式: False\n预期: 返回字典大小等于输入无人机数量 {len(drones)}",
            name="【测试数据】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"匹配结果: {result}\n输入数量: {len(drones)}\n输出数量: {len(result)}",
            name="【测试结果】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"【测试结论】: 通过 — 匹配结果字典大小 {len(result)} 与输入无人机数量 {len(drones)} 一致。",
            name="【测试结论】",
            attachment_type=allure.attachment_type.TEXT
        )
        log_manager.logger.info("test_best_match_result_size 通过")


# ===================== BestMatchAuction 测试 =====================
@pytest.mark.algo
@pytest.mark.matching
@allure.feature("匹配算法测试")
@allure.story("基于拍卖算法的最佳匹配 (BestMatchAuction)")
class TestBestMatchAuction:
    """拍卖算法最佳匹配（BestMatchAuction）接口测试。"""

    @allure.title("两架无人机拍卖匹配测试")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description("验证两架无人机进行拍卖算法匹配时，返回字典的键值均映射到输入的 droneId 集合，且匹配数量为 2。")
    @allure.tag("BestMatchAuction", "两机匹配", "拍卖算法")
    def test_best_match_auction_two_drones(self, dll):
        """拍卖模式匹配应返回有效字典，键值应映射到输入的 droneId 集合。"""
        drones = get_test_drones_two()
        input_ids = {d["droneId"] for d in drones}

        # Step 1: DLL 调用
        with allure.step("【DLL调用】执行两架无人机拍卖匹配"):
            log_manager.logger.info(f"[输入] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[输入] droneIds: {input_ids}")
            log_manager.logger.info(f"[输入] auction: True")
            log_manager.logger.info(f"[指针] dll地址: {hex(id(dll))}")

            result = dll.best_match(drones, auction=True)

            log_manager.logger.info(f"[输出] 匹配结果类型: {type(result)}")
            log_manager.logger.info(f"[输出] 匹配结果长度: {len(result)}")
            log_manager.logger.info(f"[输出] 结果 keys: {set(result.keys())}")
            log_manager.logger.info(f"[输出] 结果 values: {set(result.values())}")
            log_manager.logger.info(f"[输出] 完整匹配字典: {result}")

        # Step 2: 断言验证
        with allure.step("【断言验证】校验拍卖匹配结果的键值均在输入 droneId 集合中"):
            log_manager.logger.info(f"[对比] keys ⊆ input_ids: {set(result.keys()) <= input_ids}")
            log_manager.logger.info(f"[对比] values ⊆ input_ids: {set(result.values()) <= input_ids}")

            assert isinstance(result, dict)
            assert len(result) == 2, f"期望 2 条拍卖匹配，实际 {len(result)}"
            assert set(result.keys()) <= input_ids, f"拍卖匹配 key 必须在输入 droneId 集合中: {result}"
            assert set(result.values()) <= input_ids, f"拍卖匹配 value 必须在输入 droneId 集合中: {result}"

        # Step 3: 附件报告
        allure.attach(
            f"输入无人机数: {len(drones)}\n输入 droneIds: {input_ids}\n拍卖模式: True\n预期: 返回字典，键值均在输入 droneId 集合中，匹配数量为 2",
            name="【测试数据】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"拍卖匹配结果: {result}\n结果 keys: {set(result.keys())}\n结果 values: {set(result.values())}\n结果数量: {len(result)}",
            name="【测试结果】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            "【测试结论】: 通过 — 两架无人机拍卖匹配成功，返回字典的键值均映射到输入的 droneId 集合。",
            name="【测试结论】",
            attachment_type=allure.attachment_type.TEXT
        )
        log_manager.logger.info("test_best_match_auction_two_drones 通过")

    @allure.title("多架无人机拍卖匹配测试")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description("验证多架（6架）无人机进行拍卖算法匹配时，返回有效字典且匹配数量等于输入无人机数量。")
    @allure.tag("BestMatchAuction", "多机匹配", "拍卖算法", "规模测试")
    def test_best_match_auction_multi(self, dll):
        """多架无人机拍卖匹配应返回有效字典。"""
        drones = get_test_drones_multi(n=6)
        input_ids = {d["droneId"] for d in drones}

        # Step 1: DLL 调用
        with allure.step("【DLL调用】执行多架无人机拍卖匹配"):
            log_manager.logger.info(f"[输入] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[输入] droneIds: {input_ids}")
            log_manager.logger.info(f"[输入] auction: True")
            log_manager.logger.info(f"[指针] dll地址: {hex(id(dll))}")

            result = dll.best_match(drones, auction=True)

            log_manager.logger.info(f"[输出] 匹配结果类型: {type(result)}")
            log_manager.logger.info(f"[输出] 匹配结果长度: {len(result)}")
            log_manager.logger.info(f"[输出] 结果 keys: {set(result.keys())}")
            log_manager.logger.info(f"[输出] 结果 values: {set(result.values())}")
            log_manager.logger.info(f"[输出] 完整匹配字典: {result}")

        # Step 2: 断言验证
        with allure.step("【断言验证】校验返回类型为字典且匹配数量等于输入数量"):
            assert isinstance(result, dict)
            assert len(result) == 6, f"期望 6 条拍卖匹配，实际 {len(result)}"

        # Step 3: 附件报告
        allure.attach(
            f"输入无人机数: {len(drones)}\n输入 droneIds: {input_ids}\n拍卖模式: True\n预期: 返回字典，匹配数量为 6",
            name="【测试数据】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"拍卖匹配结果: {result}\n结果 keys: {set(result.keys())}\n结果 values: {set(result.values())}\n结果数量: {len(result)}",
            name="【测试结果】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            "【测试结论】: 通过 — 多架无人机拍卖匹配成功，返回有效字典且匹配数量等于输入数量。",
            name="【测试结论】",
            attachment_type=allure.attachment_type.TEXT
        )
        log_manager.logger.info("test_best_match_auction_multi 通过")

    @allure.title("空输入拍卖匹配测试")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description("验证空列表输入拍卖算法匹配接口时，应返回空字典。")
    @allure.tag("BestMatchAuction", "边界测试", "空输入")
    def test_best_match_auction_empty(self, dll):
        """空列表拍卖匹配应返回空字典。"""
        # Step 1: DLL 调用
        with allure.step("【DLL调用】执行空输入拍卖匹配"):
            log_manager.logger.info("[输入] 无人机数量: 0")
            log_manager.logger.info("[输入] auction: True")
            log_manager.logger.info(f"[指针] dll地址: {hex(id(dll))}")

            result = dll.best_match([], auction=True)

            log_manager.logger.info(f"[输出] 匹配结果类型: {type(result)}")
            log_manager.logger.info(f"[输出] 匹配结果长度: {len(result)}")
            log_manager.logger.info(f"[输出] 完整匹配字典: {result}")

        # Step 2: 断言验证
        with allure.step("【断言验证】校验空输入拍卖匹配返回空字典"):
            assert result == {}

        # Step 3: 附件报告
        allure.attach(
            "输入无人机数: 0\n拍卖模式: True\n预期: 返回空字典 {}",
            name="【测试数据】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"拍卖匹配结果: {result}\n结果类型: {type(result)}\n结果数量: {len(result)}",
            name="【测试结果】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            "【测试结论】: 通过 — 空输入拍卖匹配返回空字典。",
            name="【测试结论】",
            attachment_type=allure.attachment_type.TEXT
        )
        log_manager.logger.info("test_best_match_auction_empty 通过")

    @allure.title("常规匹配与拍卖匹配一致性测试")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description("验证同一组数据下，常规匹配与拍卖匹配返回的结果数量一致，均等于输入无人机数量。")
    @allure.tag("BestMatch", "BestMatchAuction", "一致性对比", "算法对比")
    def test_best_match_consistency(self, dll):
        """同一组数据，常规匹配与拍卖匹配应返回相同数量的结果。"""
        drones = get_test_drones_two()
        input_ids = {d["droneId"] for d in drones}

        # Step 1: DLL 调用 - 常规匹配
        with allure.step("【DLL调用】执行常规匹配 (auction=False)"):
            log_manager.logger.info(f"[输入] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[输入] droneIds: {input_ids}")
            log_manager.logger.info(f"[输入] auction: False")
            log_manager.logger.info(f"[指针] dll地址: {hex(id(dll))}")

            result_normal = dll.best_match(drones, auction=False)

            log_manager.logger.info(f"[输出-常规] 匹配结果类型: {type(result_normal)}")
            log_manager.logger.info(f"[输出-常规] 匹配结果长度: {len(result_normal)}")
            log_manager.logger.info(f"[输出-常规] 结果 keys: {set(result_normal.keys())}")
            log_manager.logger.info(f"[输出-常规] 结果 values: {set(result_normal.values())}")
            log_manager.logger.info(f"[输出-常规] 完整匹配字典: {result_normal}")

        # Step 2: DLL 调用 - 拍卖匹配
        with allure.step("【DLL调用】执行拍卖匹配 (auction=True)"):
            log_manager.logger.info(f"[输入] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[输入] auction: True")

            result_auction = dll.best_match(drones, auction=True)

            log_manager.logger.info(f"[输出-拍卖] 匹配结果类型: {type(result_auction)}")
            log_manager.logger.info(f"[输出-拍卖] 匹配结果长度: {len(result_auction)}")
            log_manager.logger.info(f"[输出-拍卖] 结果 keys: {set(result_auction.keys())}")
            log_manager.logger.info(f"[输出-拍卖] 结果 values: {set(result_auction.values())}")
            log_manager.logger.info(f"[输出-拍卖] 完整匹配字典: {result_auction}")

        # Step 3: 断言验证
        with allure.step("【断言验证】校验常规匹配与拍卖匹配数量一致且等于输入数量"):
            log_manager.logger.info(f"[对比] 常规匹配数量: {len(result_normal)}, 拍卖匹配数量: {len(result_auction)}, 期望数量: {len(drones)}")

            assert isinstance(result_normal, dict)
            assert isinstance(result_auction, dict)
            assert len(result_normal) == len(drones), f"常规匹配数量异常: {len(result_normal)}"
            assert len(result_auction) == len(drones), f"拍卖匹配数量异常: {len(result_auction)}"

        # Step 4: 附件报告
        allure.attach(
            f"输入无人机数: {len(drones)}\n输入 droneIds: {input_ids}\n预期: 常规匹配与拍卖匹配返回数量一致，均等于 {len(drones)}",
            name="【测试数据】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"常规匹配: {result_normal}\n常规匹配数量: {len(result_normal)}\n拍卖匹配: {result_auction}\n拍卖匹配数量: {len(result_auction)}",
            name="【测试结果】",
            attachment_type=allure.attachment_type.TEXT
        )
        allure.attach(
            f"【测试结论】: 通过 — 常规匹配数量 {len(result_normal)} 与拍卖匹配数量 {len(result_auction)} 一致，均等于输入无人机数量 {len(drones)}。",
            name="【测试结论】",
            attachment_type=allure.attachment_type.TEXT
        )
        log_manager.logger.info(
            f"test_best_match_consistency 通过，常规: {len(result_normal)}, "
            f"拍卖: {len(result_auction)}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
