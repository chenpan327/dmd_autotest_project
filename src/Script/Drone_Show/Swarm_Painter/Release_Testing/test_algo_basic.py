# -*- coding: utf-8 -*-
"""
test_algo_basic.py
功能点：测试 DLL 连通性自检、基础算力、用户授权、无人机参数配置与字典-结构体转换。
算法 DLL 基础接口测试套件
==============================
本测试套件覆盖 dmd_algorithm.dll 的基础连通性与配置接口：
  - HelloWorld（连通性自检）
  - AddTwo（基础算力验证）
  - SetUserDronesInfo（无人机参数配置）
  - SetAuthorized（授权管理）
  - GetHardwareSN（硬件序列号获取）
  - use_dict_generate_dramainfo（结构体转换）

运行方式：
  pytest test_algo_basic.py -v
"""

import os
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List

import pytest
import allure
import ctypes

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
    from src.Protocol.drama.common import com_c_class as c_class
except ImportError as _import_err:
    log_manager.logger.warning(f"相对导入失败，尝试直接导入 Protocol 模块: {_import_err}")
    _protocol_dir = Path(__file__).parents[2]
    sys.path.append(str(_protocol_dir))
    import DLL as dll_module
    import com_c_class as c_class

# ===================== 测试常量 =====================
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


# ===================== Pytest Fixtures =====================
@pytest.fixture(scope="module")
def dll():
    """模块级 fixture：初始化 DLL 实例并完成授权。"""
    instance = dll_module.DLL(str(DLL_PATH))
    instance.set_user_drones_info(DRONE_INFO_STR)
    instance.set_user_authorize(True)
    yield instance
    instance.close()


# ===================== 测试类 =====================
@allure.feature("算法DLL基础接口测试")
class TestDllConnectivity:
    """验证 DLL 加载成功后的基础连通性与算力接口。"""

    @allure.title("HelloWorld连通性测试")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_hello_world(self, dll):
        """HelloWorld 不应抛出异常，证明 DLL 可正常调用。"""
        with allure.step("调用 HelloWorld 接口"):
            log_manager.logger.info(f"[指针信息] dll实例地址: {hex(id(dll))}")
            try:
                dll.hello()
                log_manager.logger.info("test_hello_world 通过，DLL 连通性正常")
                allure.attach(
                    f"DLL 实例地址: {hex(id(dll))}",
                    name="DLL实例信息",
                    attachment_type=allure.attachment_type.TEXT
                )
            except Exception as e:
                log_manager.logger.error(f"test_hello_world 失败: {e}")
                pytest.fail(f"HelloWorld 调用异常: {e}")

    @allure.title("AddTwo正数运算测试")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_add_two(self, dll):
        """AddTwo 应正确返回两数之和。"""
        with allure.step("调用 AddTwo(3, 5)"):
            a, b = 3, 5
            log_manager.logger.info(f"[输入参数] a={a}, b={b}")
            log_manager.logger.info(f"[指针信息] dll实例地址: {hex(id(dll))}")
            
            result = dll.add_two(a, b)
            log_manager.logger.info(f"[返回值] result={result}")
            
            expected = 8
            log_manager.logger.info(f"[断言检查] 期望={expected}, 实际={result}")
            assert result == expected, f"期望 {expected}，实际 {result}"
            
            allure.attach(
                f"DLL实例地址: {hex(id(dll))}\n运算结果: {result}",
                name="测试详情",
                attachment_type=allure.attachment_type.TEXT
            )
            log_manager.logger.info("test_add_two 通过，基础算力正常")

    @allure.title("AddTwo负数运算测试")
    @allure.severity(allure.severity_level.NORMAL)
    def test_add_two_negative(self, dll):
        """AddTwo 应支持负数运算。"""
        with allure.step("调用 AddTwo(-10, 5)"):
            a, b = -10, 5
            log_manager.logger.info(f"[输入参数] a={a}, b={b}")
            log_manager.logger.info(f"[指针信息] dll实例地址: {hex(id(dll))}")
            
            result = dll.add_two(a, b)
            log_manager.logger.info(f"[返回值] result={result}")
            
            expected = -5
            log_manager.logger.info(f"[断言检查] 期望={expected}, 实际={result}")
            assert result == expected, f"期望 {expected}，实际 {result}"
            
            allure.attach(
                f"DLL实例地址: {hex(id(dll))}\n运算结果: {result}",
                name="测试详情",
                attachment_type=allure.attachment_type.TEXT
            )

    @allure.title("AddTwo零值运算测试")
    @allure.severity(allure.severity_level.NORMAL)
    def test_add_two_zero(self, dll):
        """AddTwo 应支持零值运算。"""
        with allure.step("调用 AddTwo(0, 0)"):
            a, b = 0, 0
            log_manager.logger.info(f"[输入参数] a={a}, b={b}")
            log_manager.logger.info(f"[指针信息] dll实例地址: {hex(id(dll))}")
            
            result = dll.add_two(a, b)
            log_manager.logger.info(f"[返回值] result={result}")
            
            expected = 0
            log_manager.logger.info(f"[断言检查] 期望={expected}, 实际={result}")
            assert result == expected
            
            allure.attach(
                f"DLL实例地址: {hex(id(dll))}\n运算结果: {result}",
                name="测试详情",
                attachment_type=allure.attachment_type.TEXT
            )


# ===================== 用户配置与授权测试 =====================
@pytest.mark.algo
@pytest.mark.basic
class TestUserConfig:
    """验证用户无人机信息设置与授权管理接口。"""

    def test_set_user_drones_info(self, dll):
        """SetUserDronesInfo 应成功解析并保存无人机参数。"""
        with allure.step("设置无人机信息"):
            log_manager.logger.info(f"[输入参数] drone_info_str 长度={len(DRONE_INFO_STR)}")
            log_manager.logger.info(f"[指针信息] dll实例地址: {hex(id(dll))}")
            try:
                result = dll.set_user_drones_info(DRONE_INFO_STR)
                log_manager.logger.info(f"[返回值] result={result}")
                
                log_manager.logger.info(f"[断言检查] 期望=True, 实际={result}")
                assert result is True, "设置无人机信息失败"
                log_manager.logger.info("test_set_user_drones_info 通过")
            except Exception as e:
                log_manager.logger.error(f"test_set_user_drones_info 失败: {e}")
                pytest.fail(f"SetUserDronesInfo 异常: {e}")

    def test_set_user_drones_info_invalid_json(self, dll):
        """传入合法 JSON 但不是数组时应返回 False 而不崩溃（避免触发 DLL 弹窗）。"""
        with allure.step("传入无效JSON格式"):
            invalid_json = '{"not": "a list"}'
            log_manager.logger.info(f"[输入参数] invalid_json={invalid_json}")
            log_manager.logger.info(f"[指针信息] dll实例地址: {hex(id(dll))}")
            
            result = dll.set_user_drones_info(invalid_json)
            log_manager.logger.info(f"[返回值] result={result}")
            
            log_manager.logger.info(f"[断言检查] 期望=False, 实际={result}")
            assert result is False

    def test_set_user_authorize(self, dll):
        """授权接口应正常执行不抛异常。"""
        with allure.step("设置用户授权"):
            log_manager.logger.info(f"[输入参数] authorize=True")
            log_manager.logger.info(f"[指针信息] dll实例地址: {hex(id(dll))}")
            try:
                dll.set_user_authorize(True)
                log_manager.logger.info("[返回值] 授权设置成功")
                log_manager.logger.info("test_set_user_authorize 通过")
            except Exception as e:
                log_manager.logger.error(f"test_set_user_authorize 失败: {e}")
                pytest.fail(f"SetAuthorized 异常: {e}")


# ===================== 硬件信息测试 =====================
@pytest.mark.algo
@pytest.mark.basic
@allure.feature("硬件信息接口测试")
@allure.story("硬件序列号")
class TestHardwareInfo:
    """硬件序列号相关接口测试。

    测试目标：验证硬件信息相关接口的行为。
    已知问题：GetHardwareSN 当前为空实现。
    """

    @allure.title("硬件序列号空实现警告测试")
    @allure.description(
        "验证 get_hardware_sn 当前为空实现，应发出 UserWarning 并返回空字符串。\n"
        "此测试确认 DLL 未实现的接口有合理的降级行为。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("HardwareInfo", "空实现", "警告")
    def test_get_hardware_sn_warns(self, dll):
        """GetHardwareSN 当前为空实现，应发出 UserWarning。"""
        
        allure.attach(
            f"【测试数据】\n"
            f"  接口: get_hardware_sn\n"
            f"  预期结果: 发出 UserWarning，返回空字符串 ''",
            name="测试数据",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("调用 get_hardware_sn 并验证警告"):
            with pytest.warns(UserWarning, match="not implemented yet"):
                result = dll.get_hardware_sn()

        allure.attach(
            f"【测试结果】\n"
            f"  返回值: '{result}'\n"
            f"  警告: UserWarning (not implemented yet)\n"
            f"  预期: UserWarning + ''",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("验证返回值为空字符串"):
            assert result == "", f"空实现应返回空字符串，实际 '{result}'"

        allure.attach(
            f"【测试结论】\n"
            f"  ✅ GetHardwareSN 空实现正确处理，发出了预期的 UserWarning。",
            name="测试结论",
            attachment_type=allure.attachment_type.TEXT
        )


# ===================== 结构体转换测试 =====================
@pytest.mark.algo
@pytest.mark.basic
class TestStructConversion:
    """验证 Python 字典到 C 结构体的转换逻辑。"""

    def test_dramainfo_keepalive(self, dll):
        """转换后的 DramaInfo 必须带有 _keepalive 引用保护。"""
        with allure.step("测试 DramaInfo keepalive"):
            drones = [{
                "droneType": 21,
                "droneId": 1,
                "points": [[0, 0, 1], [10, 0, 1], [10, 10, 1]],
                "colors": [[255, 0, 0]],
            }]
            log_manager.logger.info(f"[输入参数] drones={drones}")
            log_manager.logger.info(f"[指针信息] dll实例地址: {hex(id(dll))}")
            
            drama = dll.use_dict_generate_dramainfo(drones)
            log_manager.logger.info(f"[返回值] drama.size={drama.size}")
            
            log_manager.logger.info(f"[断言检查] 期望 hasattr(_keepalive)=True, 实际={hasattr(drama, '_keepalive')}")
            assert hasattr(drama, "_keepalive")
            log_manager.logger.info(f"[断言检查] 期望 len(_keepalive)>0, 实际={len(drama._keepalive)}")
            assert len(drama._keepalive) > 0
            log_manager.logger.info(f"[断言检查] 期望 size=1, 实际={drama.size}")
            assert drama.size == 1
            log_manager.logger.info(f"[断言检查] 期望 droneId=1, 实际={drama.drones[0].droneId}")
            assert drama.drones[0].droneId == 1
            log_manager.logger.info(f"[断言检查] 期望 pointsSize=3, 实际={drama.drones[0].pointsSize}")
            assert drama.drones[0].pointsSize == 3
            log_manager.logger.info(f"[断言检查] 期望 colorsSize=1, 实际={drama.drones[0].colorsSize}")
            assert drama.drones[0].colorsSize == 1
            log_manager.logger.info("test_dramainfo_keepalive 通过")

    def test_dramainfo_defaults(self, dll):
        """空字典应使用默认值填充。"""
        with allure.step("测试 DramaInfo 默认值"):
            minimal = [{}]
            log_manager.logger.info(f"[输入参数] minimal={minimal}")
            log_manager.logger.info(f"[指针信息] dll实例地址: {hex(id(dll))}")
            
            drama = dll.use_dict_generate_dramainfo(minimal)
            log_manager.logger.info(f"[返回值] drama.size={drama.size}")
            
            log_manager.logger.info(f"[断言检查] 期望 size=1, 实际={drama.size}")
            assert drama.size == 1
            log_manager.logger.info(f"[断言检查] 期望 droneType=1, 实际={drama.drones[0].droneType}")
            assert drama.drones[0].droneType == 1
            log_manager.logger.info(f"[断言检查] 期望 speed=5.0, 实际={drama.drones[0].speed}")
            assert drama.drones[0].speed == 5.0
            log_manager.logger.info(f"[断言检查] 期望 horizonAcc=2.0, 实际={drama.drones[0].horizonAcc}")
            assert drama.drones[0].horizonAcc == 2.0
            log_manager.logger.info(f"[断言检查] 期望 pointsSize=1, 实际={drama.drones[0].pointsSize}")
            assert drama.drones[0].pointsSize == 1
            log_manager.logger.info("test_dramainfo_defaults 通过")

    def test_dramainfo_fireworks(self, dll):
        """fireworksAngle 列表应正确转换为 ctypes 数组。"""
        with allure.step("测试 fireworksAngle 转换"):
            drones = [{
                "droneType": 21,
                "droneId": 1,
                "points": [[0, 0, 1]],
                "fireworksAngle": [0, 45, 90],
            }]
            log_manager.logger.info(f"[输入参数] drones={drones}")
            log_manager.logger.info(f"[指针信息] dll实例地址: {hex(id(dll))}")
            
            drama = dll.use_dict_generate_dramainfo(drones)
            log_manager.logger.info(f"[返回值] fireworksCnt={drama.drones[0].fireworksCnt}")
            
            log_manager.logger.info(f"[断言检查] 期望 fireworksCnt=3, 实际={drama.drones[0].fireworksCnt}")
            assert drama.drones[0].fireworksCnt == 3
            log_manager.logger.info("test_dramainfo_fireworks 通过")

    def test_dramainfo_empty_list(self, dll):
        """传入空列表应生成 size=0 的 DramaInfo。"""
        with allure.step("测试空列表输入"):
            log_manager.logger.info(f"[输入参数] drones=[]")
            log_manager.logger.info(f"[指针信息] dll实例地址: {hex(id(dll))}")
            
            drama = dll.use_dict_generate_dramainfo([])
            log_manager.logger.info(f"[返回值] drama.size={drama.size}")
            
            log_manager.logger.info(f"[断言检查] 期望 size=0, 实际={drama.size}")
            assert drama.size == 0

    def test_dramainfo_non_list_input(self, dll):
        """传入非 list 类型时应自动转为空列表。"""
        with allure.step("测试非列表输入"):
            log_manager.logger.info(f"[输入参数] drones='invalid'")
            log_manager.logger.info(f"[指针信息] dll实例地址: {hex(id(dll))}")
            
            drama = dll.use_dict_generate_dramainfo("invalid")
            log_manager.logger.info(f"[返回值] drama.size={drama.size}")
            
            log_manager.logger.info(f"[断言检查] 期望 size=0, 实际={drama.size}")
            assert drama.size == 0

    def test_drama3info_warns(self, dll):
        """use_dict_generate_drama3info 当前为空实现，应发出 UserWarning。"""
        with allure.step("测试 drama3info 未实现警告"):
            log_manager.logger.info(f"[指针信息] dll实例地址: {hex(id(dll))}")
            with pytest.warns(UserWarning, match="not implemented yet"):
                result = dll.use_dict_generate_drama3info()
            log_manager.logger.info(f"[返回值] result={result}")
            
            log_manager.logger.info(f"[断言检查] 期望 result=None, 实际={result}")
            assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
