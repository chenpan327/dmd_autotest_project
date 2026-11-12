# -*- coding: utf-8 -*-
"""
test_algo_ai_conversion.py
功能点：测试 Mesh 文件路径、Mesh 字节流、线条数据三种输入到无人机点位的 AI 转换。
算法 DLL AI 转换接口测试套件
==============================
本测试套件覆盖 dmd_algorithm.dll 的 AI/图形转换算法：
  - MeshPath2Point（从 Mesh 文件路径生成点位）
  - MeshBytes2Point（从 Mesh 字节数据生成点位）
  - Line2Point（从线条数据生成点位）

测试场景包括：
  - 正常路径/字节/线条转换
  - 空输入边界
  - 不同参数组合
  - 返回结果格式校验

运行方式：
  pytest test_algo_ai_conversion.py -v
"""

import ctypes
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

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

# ===================== 真实文件路径 ======================
# 使用项目根目录（脚本向上5级）定位 drama_files
PROJECT_ROOT = Path(__file__).parents[5]
OBJ_FILES_DIR = PROJECT_ROOT / "file" / "drama_files"

log_manager.logger.info(f"[AI Conversion Test] PROJECT_ROOT: {PROJECT_ROOT}")
log_manager.logger.info(f"[AI Conversion Test] OBJ_FILES_DIR: {OBJ_FILES_DIR}")
log_manager.logger.info(f"[AI Conversion Test] OBJ_FILES_DIR exists: {OBJ_FILES_DIR.exists()}")

if OBJ_FILES_DIR.exists():
    obj_files_list = list(OBJ_FILES_DIR.glob("*.obj"))
    log_manager.logger.info(f"[AI Conversion Test] 找到 {len(obj_files_list)} 个 .obj 文件:")
    for f in obj_files_list:
        log_manager.logger.info(f"  - {f.name} ({f.stat().st_size} bytes)")
else:
    log_manager.logger.warning(f"[AI Conversion Test] OBJ_FILES_DIR 不存在: {OBJ_FILES_DIR}")


def get_obj_files() -> List[Path]:
    """返回可用的 .obj 文件列表。"""
    if not OBJ_FILES_DIR.exists():
        log_manager.logger.warning(f"[get_obj_files] 目录不存在: {OBJ_FILES_DIR}")
        return []
    obj_files = list(OBJ_FILES_DIR.glob("*.obj"))
    log_manager.logger.info(f"[get_obj_files] 返回 {len(obj_files)} 个文件")
    return obj_files


# ===================== 测试数据工厂 ======================
def get_test_drones_for_ai(n: int = 10) -> List[Dict[str, Any]]:
    """返回用于 AI 转换的无人机占位数据。

    这些无人机仅作为点位输出的容器，points 会被 C 层覆盖。
    """
    drones = []
    for i in range(n):
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
            "points": [[0.0, 0.0, 0.0]],
            "colors": [],
        })
    return drones


def get_dummy_mesh_bytes() -> bytes:
    """返回模拟的 Mesh 字节数据（非真实格式，仅用于边界测试）。"""
    return b"\x00\x01\x02\x03" * 64


def get_dummy_line_bytes() -> bytes:
    """返回模拟的线条字节数据（非真实格式，仅用于边界测试）。"""
    return b"\x00\x01\x02\x03" * 32


# ===================== Pytest Fixtures ======================
@pytest.fixture(scope="module")
def dll():
    """模块级 fixture：初始化 DLL 实例并完成授权。"""
    instance = dll_module.DLL(str(DLL_PATH))
    instance.set_user_drones_info(DRONE_INFO_STR)
    instance.set_user_authorize(True)
    yield instance
    instance.close()


# ===================== MeshPath2Point 测试 =====================
@pytest.mark.algo
@pytest.mark.ai
@allure.feature("AI转换接口测试")
@allure.story("MeshPath2Point - 文件路径转点位")
class TestMeshPath2Point:
    """Mesh 文件路径转点位（MeshPath2Point）接口测试。

    测试目标：验证 DLL 从 OBJ 网格文件生成无人机点位的能力。
    覆盖场景：正常文件、不存在文件、空输入、真实大文件。
    """

    @allure.title("不存在的Mesh文件路径测试")
    @allure.description("验证传入不存在的文件路径时，DLL 应返回失败而非崩溃。用于确认 DLL 的错误处理机制是否健全。")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("MeshPath2Point", "异常路径", "容错")
    def test_mesh_path_to_point_nonexistent(self, dll):
        """不存在的 Mesh 文件路径应返回 (False, status)。"""
        
        # ===== 测试数据 =====
        drones = get_test_drones_for_ai(n=5)
        mesh_path = r"C:\nonexistent\mesh.obj"
        target_count = 5

        log_manager.logger.info(f"[输入参数] mesh_path: {mesh_path}")
        log_manager.logger.info(f"[输入参数] target_count: {target_count}")
        log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")

        # ===== 附加测试数据 =====
        allure.attach(
            f"【测试数据】\n"
            f"  无人机数量: {len(drones)}\n"
            f"  无人机类型: V3 (type=21)\n"
            f"  mesh_path: {mesh_path}\n"
            f"  target_count: {target_count}\n"
            f"  预期结果: success=False, status!=0",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行 DLL 调用"):
            success, status = dll.mesh_path_to_point(
                drones, mesh_path=mesh_path, target_count=target_count
            )

        log_manager.logger.info(f"[断言检查] success={success}, status={status}")

        # ===== 附加测试结果 =====
        allure.attach(
            f"【测试结果】\n"
            f"  success: {success}\n"
            f"  status: {status}\n"
            f"  预期: success=False, status!=0",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("验证断言"):
            assert success is False, f"不存在的 Mesh 文件应返回失败，实际 success={success}"
            assert status != 0, f"不存在的 Mesh 文件应返回非零状态码，实际 status={status}"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ DLL 正确处理了不存在的文件路径，返回失败状态码 {status}。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )

        log_manager.logger.info(f"test_mesh_path_to_point_nonexistent 通过，success={success}, status={status}")

    @allure.title("空无人机列表路径转换测试")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_mesh_path_to_point_empty_drones(self, dll):
        """空无人机列表应返回失败（success=False）。"""
        with allure.step("执行空无人机列表的路径转换测试"):
            mesh_path = r"C:\nonexistent\mesh.obj"
            target_count = 0

            log_manager.logger.info(f"[输入参数] mesh_path: {mesh_path}")
            log_manager.logger.info(f"[输入参数] target_count: {target_count}")
            log_manager.logger.info(f"[输入参数] 无人机数量: 0")
            log_manager.logger.info(f"[指针信息] dll地址: {hex(id(dll))}")

            success, status = dll.mesh_path_to_point(
                [], mesh_path=mesh_path, target_count=target_count
            )

            log_manager.logger.info(f"[断言检查] success={success}, status={status}")
            log_manager.logger.info(f"  预期: success=False, status!=0")

            assert success is False, f"空无人机列表应返回失败，实际 success={success}"
            assert status != 0, f"空无人机列表应返回非0状态码，实际 status={status}"

            allure.attach(
                f"success: {success}\nstatus: {status}\n输入无人机数: 0\ntarget_count: {target_count}",
                name="转换结果",
                attachment_type=allure.attachment_type.TEXT
            )

            log_manager.logger.info("test_mesh_path_to_point_empty_drones 通过")

    @allure.title("返回值类型校验测试")
    @allure.severity(allure.severity_level.NORMAL)
    def test_mesh_path_to_point_return_types(self, dll):
        """不存在路径应返回失败的二元组。"""
        with allure.step("执行返回值类型校验测试"):
            drones = get_test_drones_for_ai(n=3)
            mesh_path = r"C:\test\mesh.obj"
            target_count = 3

            log_manager.logger.info(f"[输入参数] mesh_path: {mesh_path}")
            log_manager.logger.info(f"[输入参数] target_count: {target_count}")
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[指针信息] dll地址: {hex(id(dll))}")

            result = dll.mesh_path_to_point(
                drones, mesh_path=mesh_path, target_count=target_count
            )

            log_manager.logger.info(f"[断言检查] result类型={type(result).__name__}, 长度={len(result)}")
            log_manager.logger.info(f"  success={result[0]}, status={result[1]}")
            log_manager.logger.info(f"  预期: success=False, status!=0")

            assert len(result) == 2, f"返回应为二元组，实际长度 {len(result)}"
            assert result[0] is False, f"不存在的路径应返回失败，实际 success={result[0]}"
            assert result[1] != 0, f"应返回非零状态码，实际 status={result[1]}"

            allure.attach(
                f"success: {result[0]}\nstatus: {result[1]}\n输入无人机数: {len(drones)}\ntarget_count: {target_count}",
                name="转换结果",
                attachment_type=allure.attachment_type.TEXT
            )

            log_manager.logger.info("test_mesh_path_to_point_return_types 通过")

    @allure.title("真实OBJ文件小批量转换测试")
    @allure.description("验证所有真实 .obj 文件在 10 架无人机配置下能否成功转换。此测试覆盖 DLL 的完整文件加载、网格处理和点位生成流程。")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("MeshPath2Point", "真实文件", "批量")
    def test_mesh_path_to_point_real_files_small(self, dll):
        """所有真实 .obj 文件在 10 架无人机下应成功转换。"""
        obj_files = get_obj_files()
        if not obj_files:
            pytest.skip("未找到 .obj 文件")

        # ===== 附加测试数据概览 =====
        file_info_list = []
        for f in obj_files:
            file_info_list.append(f"  - {f.name} ({f.stat().st_size / 1024:.1f} KB)")
        
        allure.attach(
            f"【测试数据】\n"
            f"  文件总数: {len(obj_files)}\n"
            f"  文件列表:\n" + "\n".join(file_info_list) + "\n"
            f"  无人机数量: 10\n"
            f"  target_count: 10\n"
            f"  预期结果: 全部文件 success=True, status=0",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        # ===== 逐个文件测试 =====
        for obj_file in obj_files:
            with allure.step(f"处理文件: {obj_file.name}"):
                drones = get_test_drones_for_ai(n=10)
                mesh_path = str(obj_file)
                target_count = 10

                log_manager.logger.info(f"[DLL调用] {obj_file.name}")
                
                success, status = dll.mesh_path_to_point(
                    drones, mesh_path=mesh_path, target_count=target_count
                )

                log_manager.logger.info(f"[断言检查] 文件 {obj_file.name}: success={success}, status={status}")

                # ===== 附加单个文件测试结果 =====
                total_points = sum(len(d.get("points", [])) for d in drones)
                allure.attach(
                    f"【测试结果 - {obj_file.name}】\n"
                    f"  文件大小: {obj_file.stat().st_size / 1024:.1f} KB\n"
                    f"  success: {success}\n"
                    f"  status: {status}\n"
                    f"  生成点位总数: {total_points}\n"
                    f"  预期: success=True, status=0",
                    name=f"测试结果 - {obj_file.name}",
                    attachment_type=allure.attachment_type.TEXT
                )

                with allure.step(f"验证 {obj_file.name} 转换结果"):
                    assert success is True, f"{obj_file.name} 转换失败，status={status}"

                allure.attach(
                    f"【测试结论 - {obj_file.name}】\n"
                    f"  ✅ 文件 {obj_file.name} 成功转换，生成了 {total_points} 个点位。",
                    name=f"测试结论 - {obj_file.name}",
                    attachment_type=allure.attachment_type.TEXT
                )

    @allure.title("兔子350架无人机转换测试")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_mesh_path_to_point_rabbit_350(self, dll):
        """tuzi_350.obj 应支持 350 架无人机转换。"""
        obj_file = OBJ_FILES_DIR / "tuzi_350.obj"
        if not obj_file.exists():
            pytest.skip("未找到 tuzi_350.obj")

        with allure.step("执行 tuzi_350.obj 的转换测试"):
            drones = get_test_drones_for_ai(n=350)
            mesh_path = str(obj_file)
            target_count = 350

            log_manager.logger.info(f"[输入参数] mesh_path: {mesh_path}")
            log_manager.logger.info(f"[输入参数] target_count: {target_count}")
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[指针信息] dll地址: {hex(id(dll))}")

            success, status = dll.mesh_path_to_point(
                drones, mesh_path=mesh_path, target_count=target_count
            )

            log_manager.logger.info(f"[断言检查] success={success}, status={status}")
            log_manager.logger.info(f"  预期: success=True, status=0")

            assert success is True, f"兔子350架转换失败，status={status}"
            assert status == 0, f"兔子350架返回非零状态码 {status}"
            for i, d in enumerate(drones):
                assert len(d["points"]) > 0, f"无人机 {i} 未生成 points"

            allure.attach(
                f"success: {success}\nstatus: {status}\n输入无人机数: {len(drones)}\ntarget_count: {target_count}",
                name="转换结果",
                attachment_type=allure.attachment_type.TEXT
            )

            log_manager.logger.info("兔子350架.obj 350架转换通过")

    @allure.title("紫荆花500架无人机转换测试")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_mesh_path_to_point_flower_500(self, dll):
        """zijinghua_500.obj 实际含 500 个顶点，应支持 500 架无人机转换。"""
        obj_file = OBJ_FILES_DIR / "zijinghua_500.obj"
        if not obj_file.exists():
            pytest.skip("未找到 zijinghua_500.obj")

        with allure.step("执行 zijinghua_500.obj 的转换测试"):
            drones = get_test_drones_for_ai(n=500)
            mesh_path = str(obj_file)
            target_count = 500

            log_manager.logger.info(f"[输入参数] mesh_path: {mesh_path}")
            log_manager.logger.info(f"[输入参数] target_count: {target_count}")
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[指针信息] dll地址: {hex(id(dll))}")

            success, status = dll.mesh_path_to_point(
                drones, mesh_path=mesh_path, target_count=target_count
            )

            log_manager.logger.info(f"[断言检查] success={success}, status={status}")
            log_manager.logger.info(f"  预期: success=True, status=0")

            assert success is True, f"紫荆花500架转换失败，status={status}"
            assert status == 0, f"紫荆花500架返回非零状态码 {status}"
            for i, d in enumerate(drones):
                assert len(d["points"]) > 0, f"无人机 {i} 未生成 points"

            allure.attach(
                f"success: {success}\nstatus: {status}\n输入无人机数: {len(drones)}\ntarget_count: {target_count}",
                name="转换结果",
                attachment_type=allure.attachment_type.TEXT
            )

            log_manager.logger.info("紫荆花500架.obj 500架转换通过")


# ===================== MeshBytes2Point 测试 =====================
@pytest.mark.algo
@pytest.mark.ai
@allure.feature("AI转换接口测试")
class TestMeshBytes2Point:
    """Mesh 字节流转点位（MeshBytes2Point）接口测试。"""

    @allure.title("模拟字节数据转换测试")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_mesh_bytes_to_point_dummy_data(self, dll):
        """模拟字节数据调用不应崩溃，返回类型正确。"""
        with allure.step("执行模拟字节数据的转换测试"):
            drones = get_test_drones_for_ai(n=5)
            data = get_dummy_mesh_bytes()
            mesh_format = 0
            target_count = 5

            log_manager.logger.info(f"[输入参数] data长度: {len(data)}")
            log_manager.logger.info(f"[输入参数] mesh_format: {mesh_format}")
            log_manager.logger.info(f"[输入参数] target_count: {target_count}")
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[指针信息] dll地址: {hex(id(dll))}")

            success, status = dll.mesh_bytes_to_point(
                drones, data=data, mesh_format=mesh_format, target_count=target_count
            )

            log_manager.logger.info(f"[断言检查] success={success}, status={status}")
            log_manager.logger.info(f"  预期: success=False, status!=0")

            assert success is False, f"非法 Mesh 字节数据应返回失败，实际 success={success}"
            assert status != 0, f"非法数据应返回非零状态码，实际 status={status}"

            allure.attach(
                f"success: {success}\nstatus: {status}\n输入无人机数: {len(drones)}\ndata长度: {len(data)}\nmesh_format: {mesh_format}\ntarget_count: {target_count}",
                name="转换结果",
                attachment_type=allure.attachment_type.TEXT
            )

            log_manager.logger.info(f"test_mesh_bytes_to_point_dummy_data 通过，success={success}, status={status}")

    @allure.title("空字节数据转换测试")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_mesh_bytes_to_point_empty_data(self, dll):
        """空字节数据应返回失败（success=False）。"""
        with allure.step("执行空字节数据的转换测试"):
            drones = get_test_drones_for_ai(n=3)
            data = b""
            mesh_format = 0
            target_count = 3

            log_manager.logger.info(f"[输入参数] data长度: {len(data)}")
            log_manager.logger.info(f"[输入参数] mesh_format: {mesh_format}")
            log_manager.logger.info(f"[输入参数] target_count: {target_count}")
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[指针信息] dll地址: {hex(id(dll))}")

            success, status = dll.mesh_bytes_to_point(
                drones, data=data, mesh_format=mesh_format, target_count=target_count
            )

            log_manager.logger.info(f"[断言检查] success={success}, status={status}")
            log_manager.logger.info(f"  预期: success=False, status!=0")

            assert success is False, f"空字节数据应返回失败，实际 success={success}"
            assert status != 0, f"空字节数据应返回非0状态码，实际 status={status}"

            allure.attach(
                f"success: {success}\nstatus: {status}\n输入无人机数: {len(drones)}\ndata长度: {len(data)}\nmesh_format: {mesh_format}\ntarget_count: {target_count}",
                name="转换结果",
                attachment_type=allure.attachment_type.TEXT
            )

            log_manager.logger.info("test_mesh_bytes_to_point_empty_data 通过")

    @allure.title("空无人机列表字节流转换测试")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_mesh_bytes_to_point_empty_drones(self, dll):
        """空无人机列表应返回失败（success=False）。"""
        with allure.step("执行空无人机列表的字节流转换测试"):
            data = get_dummy_mesh_bytes()
            mesh_format = 0
            target_count = 0

            log_manager.logger.info(f"[输入参数] data长度: {len(data)}")
            log_manager.logger.info(f"[输入参数] mesh_format: {mesh_format}")
            log_manager.logger.info(f"[输入参数] target_count: {target_count}")
            log_manager.logger.info(f"[输入参数] 无人机数量: 0")
            log_manager.logger.info(f"[指针信息] dll地址: {hex(id(dll))}")

            success, status = dll.mesh_bytes_to_point(
                [], data=data, mesh_format=mesh_format, target_count=target_count
            )

            log_manager.logger.info(f"[断言检查] success={success}, status={status}")
            log_manager.logger.info(f"  预期: success=False, status!=0")

            assert success is False, f"空无人机列表应返回失败，实际 success={success}"
            assert status != 0, f"空无人机列表应返回非0状态码，实际 status={status}"

            allure.attach(
                f"success: {success}\nstatus: {status}\n输入无人机数: 0\ndata长度: {len(data)}\nmesh_format: {mesh_format}\ntarget_count: {target_count}",
                name="转换结果",
                attachment_type=allure.attachment_type.TEXT
            )

            log_manager.logger.info("test_mesh_bytes_to_point_empty_drones 通过")

    @allure.title("字节流返回值类型校验测试")
    @allure.severity(allure.severity_level.NORMAL)
    def test_mesh_bytes_to_point_return_types(self, dll):
        """非法字节数据应返回失败的二元组。"""
        with allure.step("执行字节流返回值类型校验测试"):
            drones = get_test_drones_for_ai(n=3)
            data = get_dummy_mesh_bytes()
            mesh_format = 0
            target_count = 3

            log_manager.logger.info(f"[输入参数] data长度: {len(data)}")
            log_manager.logger.info(f"[输入参数] mesh_format: {mesh_format}")
            log_manager.logger.info(f"[输入参数] target_count: {target_count}")
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[指针信息] dll地址: {hex(id(dll))}")

            result = dll.mesh_bytes_to_point(
                drones, data=data, mesh_format=mesh_format, target_count=target_count
            )

            log_manager.logger.info(f"[断言检查] result类型={type(result).__name__}, 长度={len(result)}")
            log_manager.logger.info(f"  success={result[0]}, status={result[1]}")
            log_manager.logger.info(f"  预期: success=False, status!=0")

            assert len(result) == 2, f"返回应为二元组，实际长度 {len(result)}"
            assert result[0] is False, f"非法数据应返回失败，实际 success={result[0]}"
            assert result[1] != 0, f"应返回非零状态码，实际 status={result[1]}"

            allure.attach(
                f"success: {result[0]}\nstatus: {result[1]}\n输入无人机数: {len(drones)}\ndata长度: {len(data)}\nmesh_format: {mesh_format}\ntarget_count: {target_count}",
                name="转换结果",
                attachment_type=allure.attachment_type.TEXT
            )

            log_manager.logger.info("test_mesh_bytes_to_point_return_types 通过")


# ===================== Line2Point 测试 =====================
@pytest.mark.algo
@pytest.mark.ai
@allure.feature("AI转换接口测试")
class TestLine2Point:
    """线条数据转点位（Line2Point）接口测试。"""

    @allure.title("模拟线条数据转换测试")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_line_to_point_dummy_data(self, dll):
        """模拟线条数据调用不应崩溃，返回类型正确。"""
        with allure.step("执行模拟线条数据的转换测试"):
            drones = get_test_drones_for_ai(n=5)
            input_type = 0
            mode = 0
            data = get_dummy_line_bytes()
            target_dot_count = 5

            log_manager.logger.info(f"[输入参数] input_type: {input_type}")
            log_manager.logger.info(f"[输入参数] mode: {mode}")
            log_manager.logger.info(f"[输入参数] data长度: {len(data)}")
            log_manager.logger.info(f"[输入参数] target_dot_count: {target_dot_count}")
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[指针信息] dll地址: {hex(id(dll))}")

            success, status = dll.line_to_point(
                drones, input_type=input_type, mode=mode, data=data, target_dot_count=target_dot_count
            )

            log_manager.logger.info(f"[断言检查] success={success}, status={status}")
            log_manager.logger.info(f"  预期: success=False, status!=0")

            assert success is False, f"非法线条数据应返回失败，实际 success={success}"
            assert status != 0, f"非法数据应返回非零状态码，实际 status={status}"

            allure.attach(
                f"success: {success}\nstatus: {status}\n输入无人机数: {len(drones)}\ninput_type: {input_type}\nmode: {mode}\ndata长度: {len(data)}\ntarget_dot_count: {target_dot_count}",
                name="转换结果",
                attachment_type=allure.attachment_type.TEXT
            )

            log_manager.logger.info(f"test_line_to_point_dummy_data 通过，success={success}, status={status}")

    @allure.title("空线条数据转换测试")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_line_to_point_empty_data(self, dll):
        """空线条数据应返回失败（success=False）。"""
        with allure.step("执行空线条数据的转换测试"):
            drones = get_test_drones_for_ai(n=3)
            input_type = 0
            mode = 0
            data = b""
            target_dot_count = 3

            log_manager.logger.info(f"[输入参数] input_type: {input_type}")
            log_manager.logger.info(f"[输入参数] mode: {mode}")
            log_manager.logger.info(f"[输入参数] data长度: {len(data)}")
            log_manager.logger.info(f"[输入参数] target_dot_count: {target_dot_count}")
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[指针信息] dll地址: {hex(id(dll))}")

            success, status = dll.line_to_point(
                drones, input_type=input_type, mode=mode, data=data, target_dot_count=target_dot_count
            )

            log_manager.logger.info(f"[断言检查] success={success}, status={status}")
            log_manager.logger.info(f"  预期: success=False, status!=0")

            assert success is False, f"空线条数据应返回失败，实际 success={success}"
            assert status != 0, f"空线条数据应返回非0状态码，实际 status={status}"

            allure.attach(
                f"success: {success}\nstatus: {status}\n输入无人机数: {len(drones)}\ninput_type: {input_type}\nmode: {mode}\ndata长度: {len(data)}\ntarget_dot_count: {target_dot_count}",
                name="转换结果",
                attachment_type=allure.attachment_type.TEXT
            )

            log_manager.logger.info("test_line_to_point_empty_data 通过")

    @allure.title("空无人机列表线条转换测试")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_line_to_point_empty_drones(self, dll):
        """空无人机列表应返回失败（success=False）。"""
        with allure.step("执行空无人机列表的线条转换测试"):
            input_type = 0
            mode = 0
            data = get_dummy_line_bytes()
            target_dot_count = 0

            log_manager.logger.info(f"[输入参数] input_type: {input_type}")
            log_manager.logger.info(f"[输入参数] mode: {mode}")
            log_manager.logger.info(f"[输入参数] data长度: {len(data)}")
            log_manager.logger.info(f"[输入参数] target_dot_count: {target_dot_count}")
            log_manager.logger.info(f"[输入参数] 无人机数量: 0")
            log_manager.logger.info(f"[指针信息] dll地址: {hex(id(dll))}")

            success, status = dll.line_to_point(
                [], input_type=input_type, mode=mode, data=data, target_dot_count=target_dot_count
            )

            log_manager.logger.info(f"[断言检查] success={success}, status={status}")
            log_manager.logger.info(f"  预期: success=False, status!=0")

            assert success is False, f"空无人机列表应返回失败，实际 success={success}"
            assert status != 0, f"空无人机列表应返回非0状态码，实际 status={status}"

            allure.attach(
                f"success: {success}\nstatus: {status}\n输入无人机数: 0\ninput_type: {input_type}\nmode: {mode}\ndata长度: {len(data)}\ntarget_dot_count: {target_dot_count}",
                name="转换结果",
                attachment_type=allure.attachment_type.TEXT
            )

            log_manager.logger.info("test_line_to_point_empty_drones 通过")

    @allure.title("不同mode参数线条转换测试")
    @allure.severity(allure.severity_level.NORMAL)
    def test_line_to_point_different_modes(self, dll):
        """不同 mode 参数下非法数据均应返回失败。"""
        drones = get_test_drones_for_ai(n=3)
        input_type = 0
        data = get_dummy_line_bytes()
        target_dot_count = 3

        for mode in [0, 1]:
            with allure.step(f"执行 mode={mode} 的线条转换测试"):
                log_manager.logger.info(f"[输入参数] input_type: {input_type}")
                log_manager.logger.info(f"[输入参数] mode: {mode}")
                log_manager.logger.info(f"[输入参数] data长度: {len(data)}")
                log_manager.logger.info(f"[输入参数] target_dot_count: {target_dot_count}")
                log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
                log_manager.logger.info(f"[指针信息] dll地址: {hex(id(dll))}")

                success, status = dll.line_to_point(
                    drones, input_type=input_type, mode=mode, data=data, target_dot_count=target_dot_count
                )

                log_manager.logger.info(f"[断言检查] mode={mode}: success={success}, status={status}")
                log_manager.logger.info(f"  预期: success=False, status!=0")

                assert success is False, f"mode={mode} 时非法数据应返回失败，实际 success={success}"
                assert status != 0, f"mode={mode} 时应返回非0状态码，实际 status={status}"

                allure.attach(
                    f"success: {success}\nstatus: {status}\n输入无人机数: {len(drones)}\ninput_type: {input_type}\nmode: {mode}\ndata长度: {len(data)}\ntarget_dot_count: {target_dot_count}",
                    name="转换结果",
                    attachment_type=allure.attachment_type.TEXT
                )

        log_manager.logger.info("test_line_to_point_different_modes 通过")

    @allure.title("线条返回值类型校验测试")
    @allure.severity(allure.severity_level.NORMAL)
    def test_line_to_point_return_types(self, dll):
        """非法线条数据应返回失败的二元组。"""
        with allure.step("执行线条返回值类型校验测试"):
            drones = get_test_drones_for_ai(n=3)
            input_type = 0
            mode = 0
            data = get_dummy_line_bytes()
            target_dot_count = 3

            log_manager.logger.info(f"[输入参数] input_type: {input_type}")
            log_manager.logger.info(f"[输入参数] mode: {mode}")
            log_manager.logger.info(f"[输入参数] data长度: {len(data)}")
            log_manager.logger.info(f"[输入参数] target_dot_count: {target_dot_count}")
            log_manager.logger.info(f"[输入参数] 无人机数量: {len(drones)}")
            log_manager.logger.info(f"[指针信息] dll地址: {hex(id(dll))}")

            result = dll.line_to_point(
                drones, input_type=input_type, mode=mode, data=data, target_dot_count=target_dot_count
            )

            log_manager.logger.info(f"[断言检查] result类型={type(result).__name__}, 长度={len(result)}")
            log_manager.logger.info(f"  success={result[0]}, status={result[1]}")
            log_manager.logger.info(f"  预期: success=False, status!=0")

            assert len(result) == 2, f"返回应为二元组，实际长度 {len(result)}"
            assert result[0] is False, f"非法数据应返回失败，实际 success={result[0]}"
            assert result[1] != 0, f"应返回非零状态码，实际 status={result[1]}"

            allure.attach(
                f"success: {result[0]}\nstatus: {result[1]}\n输入无人机数: {len(drones)}\ninput_type: {input_type}\nmode: {mode}\ndata长度: {len(data)}\ntarget_dot_count: {target_dot_count}",
                name="转换结果",
                attachment_type=allure.attachment_type.TEXT
            )

            log_manager.logger.info("test_line_to_point_return_types 通过")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
