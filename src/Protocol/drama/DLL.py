import os
import ctypes
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from utils.logger import log_manager

# ======================== 【Windows 短路径转换】=========================
# 用于将包含中文的路径转换为 8.3 短路径格式，避免 DLL 内部 ANSI 函数无法处理中文
def _to_short_path(path: str) -> str:
    """将路径转换为 Windows 8.3 短路径（不含中文）。
    
    Args:
        path: 原始路径字符串。
        
    Returns:
        短路径字符串。如果转换失败，返回原始路径。
    """
    try:
        import ctypes
        buffer = ctypes.create_unicode_buffer(260)
        ctypes.windll.kernel32.GetShortPathNameW(path, buffer, 260)
        short_path = buffer.value
        if short_path and os.path.exists(short_path):
            return short_path
        return path
    except Exception:
        return path
# ==========================================================================

try:
    from .common import com_c_class as c_class
    from .common import com_func
except ImportError:
    import com_c_class as c_class
    import com_func


# ======================== 【全局禁用 Windows 弹窗】=========================
# 系统级禁止任何弹窗、错误框、消息框（真正从根源关闭）
ctypes.windll.kernel32.SetErrorMode(0x0002 | 0x0001 | 0x0004 | 0x8000)
# ==========================================================================

PYTHON_VERSION = sys.version_info
StringCallback = ctypes.WINFUNCTYPE(None, ctypes.c_char_p)

# 授权密钥常量
AUTHORIZE_KEY = b"UbK7HmSVxYuVMUVfzNVw"
DLL_NAME = "dmd_algorithm.dll"

TRANSFORMER_SOLVER_ERROR_CODE = {
    -1: "Unknown error",
    1: "Precheck: goals number not match with starts number",
    2: "Precheck: starts collision",
    3: "Precheck: goals collision",
    4: "Precheck: all uav already at goal",
    5: "Precheck: starts type not match with goals type",
    6: "Precheck: find not support type",
    7: "Precheck: obstacles find not support type",
    8: "Precheck: obstacle path lengths are inconsistent",
    9: "Pre_Process: failed to select preprocess",
    10: "Find_Path: failed to select solver",
    11: "RVO: run failed",
    12: "RVO: memory not enough",
    13: "CAPT: arrival failed",
    14: "CAPT: check path failed",
    15: "CAPT: symbol error",
    16: "Expand_Drama: expand drama failed",
    17: "Merge Path: startSets and goalSets don't match",
    18: "DMPC: QP solver failed",
    19: "DMPC: pathfinding failed",
    20: "DMPC: Solve path collision",
    21: "Post_Process: failed to select postprocess",
    22: "Post_Process: path_optimization failed",
}


class DLL:
    """dmd_algorithm.dll 的 Python 封装类。

    负责 DLL 加载、函数签名注册、Python 字典与 C 结构体的转换，
    以及各类无人机编队算法接口的调用。
    """

    def __init__(self, python_dll_libs_path: str) -> None:
        """
        Args:
            python_dll_libs_path: DLL 依赖库所在的目录路径。

        Raises:
            FileNotFoundError: 当 dmd_algorithm.dll 不存在时抛出。
            OSError: 当 DLL 加载失败时抛出。
        """
        # DLL 加载前再次强制禁用 Windows 错误弹窗（模块级 SetErrorMode 可能在某些场景下失效）
        ctypes.windll.kernel32.SetErrorMode(0x0002 | 0x0001 | 0x0004 | 0x8000)

        self._libs_path = Path(python_dll_libs_path)
        dll_path = self._libs_path / DLL_NAME

        if not dll_path.exists():
            raise FileNotFoundError(f"DLL not found: {dll_path}")

        # Python 3.8+ 使用 add_dll_directory 替代全局 PATH 修改
        self._dll_cookie = None
        if PYTHON_VERSION >= (3, 8):
            self._dll_cookie = os.add_dll_directory(str(self._libs_path))

        if PYTHON_VERSION >= (3, 11):
            self.dll = ctypes.CDLL(str(dll_path), winmode=0)
        else:
            self.dll = ctypes.CDLL(str(dll_path))

        # 静默授权，禁用弹窗
        self.set_user_authorize(au=True)
        self.register_functions()

        self.empty_map = {
            "rotate": 0.0, "name": "none", "widthScale": 0.0, "heightScale": 0.0,
            "x": 0.0, "y": 0.0, "z": 0.0, "lon": 0.0, "lat": 0.0
        }

    def __del__(self) -> None:
        """析构时清理 add_dll_directory 的 cookie。"""
        self.close()

    def close(self) -> None:
        """释放 DLL 相关资源（如 add_dll_directory 的 cookie）。"""
        if self._dll_cookie is not None:
            self._dll_cookie.close()
            self._dll_cookie = None

    def get_dll(self) -> ctypes.CDLL:
        """返回底层的 ctypes CDLL 实例。"""
        return self.dll

    # DLL 函数签名配置：{函数名: (restype, argtypes)}
    FUNCTION_SIGNATURES = {
        "HelloWorld": (None, None),
        "SetUserDronesInfo": (ctypes.c_bool, [ctypes.c_char_p]),
        "SetAuthorized": (None, [ctypes.c_bool, ctypes.c_char_p]),
        "SafetyCheck": (ctypes.c_bool, [
            ctypes.POINTER(c_class.DramaInfo), ctypes.c_wchar_p,
            ctypes.POINTER(c_class.CheckResultPy), ctypes.c_bool, ctypes.c_float
        ]),
        "FireworkSafetyCheck": (ctypes.c_bool, [
            ctypes.POINTER(c_class.DramaInfo), ctypes.c_wchar_p
        ]),
        "DensitySafetyCheck": (ctypes.c_bool, [
            ctypes.POINTER(c_class.DramaInfo), ctypes.c_double,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_int)), ctypes.POINTER(ctypes.c_int)
        ]),
        "PathFinding": (ctypes.c_int, [
            ctypes.POINTER(c_class.DramaInfo), ctypes.c_float, ctypes.c_bool,
            ctypes.c_void_p, ctypes.c_wchar_p,
        ]),
        "DynamicPathFinding": (ctypes.c_bool, [
            ctypes.POINTER(c_class.DramaInfo), ctypes.c_int
        ]),
        "DmpcPathFinding": (ctypes.c_int, [
            ctypes.POINTER(c_class.DramaInfo),
            ctypes.POINTER(c_class.DramaInfo),
            ctypes.c_void_p, ctypes.c_wchar_p,
        ]),
        "DispLand": (ctypes.c_int, [
            ctypes.POINTER(c_class.DramaInfo), ctypes.c_bool, ctypes.c_float
        ]),
        "DispLandTurnPoints": (ctypes.c_int, [
            ctypes.POINTER(c_class.DramaInfo), ctypes.c_bool, ctypes.c_float,
            ctypes.c_int, ctypes.POINTER(c_class.Point_S)
        ]),
        "FreeWayPointsArr": (None, [ctypes.POINTER(c_class.PointsArr)]),
        "ExportDrama": (ctypes.c_bool, [
            ctypes.POINTER(c_class.DramaInfo), ctypes.c_wchar_p,
            ctypes.c_char_p, ctypes.POINTER(c_class.CheckResultPy)
        ]),
        "ExportDrama3": (ctypes.c_bool, [
            ctypes.POINTER(c_class.Drama3Info), ctypes.c_wchar_p,
            ctypes.c_char_p, ctypes.POINTER(c_class.CheckResultPy)
        ]),
        "De": (ctypes.c_bool, [ctypes.c_char_p]),
        "EncryptFileSelf": (ctypes.c_bool, [ctypes.c_char_p]),
        "ParseFileComponent": (ctypes.c_char_p, [ctypes.c_char_p]),
        "BestMatch": (None, [
            ctypes.POINTER(c_class.DramaInfo),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
            ctypes.POINTER(ctypes.c_int)
        ]),
        "BestMatchAuction": (None, [
            ctypes.POINTER(c_class.DramaInfo),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
            ctypes.POINTER(ctypes.c_int), ctypes.c_int
        ]),
        "CollisionSolve": (ctypes.c_bool, [ctypes.POINTER(c_class.DramaInfo)]),
        "GetHardwareSN": (ctypes.c_bool, [ctypes.c_char_p]),
        "AddTwo": (ctypes.c_int, [ctypes.c_int, ctypes.c_int]),
        "FreeMatchResult": (None, [
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
        ]),
        "MeshPath2Point": (ctypes.c_bool, [
            ctypes.POINTER(c_class.DramaInfo), ctypes.c_char_p,
            ctypes.c_int, ctypes.POINTER(ctypes.c_int)
        ]),
        "MeshBytes2Point": (ctypes.c_bool, [
            ctypes.POINTER(c_class.DramaInfo),
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
            ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)
        ]),
        "Line2Point": (ctypes.c_bool, [
            ctypes.POINTER(c_class.DramaInfo), ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
            ctypes.c_int, ctypes.POINTER(ctypes.c_int)
        ]),
    }

    def register_functions(self) -> None:
        """数据驱动注册 DLL 导出函数的参数类型和返回类型。"""
        for func_name, (restype, argtypes) in self.FUNCTION_SIGNATURES.items():
            func = getattr(self.dll, func_name, None)
            if func is None:
                log_manager.logger.warning(f"[DLL] 函数 {func_name} 未在 DLL 中找到")
                continue
            func.argtypes = argtypes
            func.restype = restype

    def free(self, pointer) -> None:
        """释放 DLL 分配的 PointsArr 内存。"""
        self.dll.FreeWayPointsArr(pointer)

    def hello(self) -> None:
        """调用 HelloWorld 测试函数。"""
        self.dll.HelloWorld()

    def set_user_drones_info(self, drone_info_str: str) -> bool:
        """设置用户无人机信息。

        Args:
            drone_info_str: JSON 或特定格式的无人机信息字符串。

        Returns:
            是否设置成功。
        """
        try:
            return self.dll.SetUserDronesInfo(drone_info_str.encode("utf-8"))
        except Exception as e:
            log_manager.logger.error(f"SetUserDronesInfo failed: {e}")
            return False

    def set_user_authorize(self, au: bool = True) -> None:
        """静默授权，禁止弹窗。

        Args:
            au: 是否授权，默认为 True。
        """
        try:
            auth_bool = ctypes.c_bool(au)
            self.dll.SetAuthorized(auth_bool, AUTHORIZE_KEY)
        except Exception as e:
            log_manager.logger.warning(f"SetAuthorized failed: {e}")

    def safety_check(
        self,
        *,
        drone_info_list: Optional[List[Dict[str, Any]]] = None,
        csv_path: str = "",
        start: int = 0,
        end: int = 1000,
        interval: int = 100,
        pos_fps: int = 2,
        color_fps: int = 10,
        simplify: bool = False,
        ellips_ratio: float = 1.0,
    ) -> Optional[c_class.CheckResultPy]:
        """执行安全检查。

        所有参数均通过关键字传入，避免位置参数混乱。

        Returns:
            成功：CheckResultPy 实例（包含 min_dis、min_dis_value 等字段）。
            失败：None（DLL 返回 False 或抛出异常时）。
        """
        drone_info_list = drone_info_list or []
        if not drone_info_list:
            log_manager.logger.warning("SafetyCheck received empty drone_info_list")
            return None

        try:
            drama_info = self.use_dict_generate_dramainfo(
                drone_info_list,
                start=start,
                end=end,
                interval=interval,
                pos_fps=pos_fps,
                color_fps=color_fps,
            )
            log_manager.logger.debug(f"[safety_check] drama_info.size={drama_info.size}, drama_info 地址={hex(id(drama_info))}")
            
            check_result = c_class.CheckResultPy(min_dis=0, min_dis_value=float("inf"))
            log_manager.logger.debug(f"[safety_check] csv_path={csv_path}")
            log_manager.logger.debug(f"[safety_check] 调用 SafetyCheck DLL...")
            
            success = self.dll.SafetyCheck(
                ctypes.byref(drama_info),
                csv_path,
                ctypes.byref(check_result),
                simplify,
                ellips_ratio,
            )
            log_manager.logger.debug(f"[safety_check] SafetyCheck 返回 success={success}")
            
            if not success:
                log_manager.logger.warning("SafetyCheck DLL returned False")
                return None
            return check_result
        except Exception as e:
            log_manager.logger.error(f"SafetyCheck failed: {e}")
            return None

    def dense_safety_check(self, drone_info_list: List[Dict[str, Any]], check_range: float = 2.18) -> List[int]:
        """密集安全检查。

        Args:
            drone_info_list: 无人机信息字典列表。
            check_range: 检查范围。

        Returns:
            成功：密度分布列表。
            失败：空列表。
        """
        try:
            drama_info = self.use_dict_generate_dramainfo(drone_info_list)
            distributes = ctypes.POINTER(ctypes.c_int)()
            count = ctypes.c_int()
            success = self.dll.DenseSafetyCheck(
                ctypes.byref(drama_info), check_range,
                ctypes.byref(distributes), ctypes.byref(count),
            )
            if not success:
                log_manager.logger.warning("DenseSafetyCheck DLL returned False")
                return []
            result = [distributes[i] for i in range(count.value)]
            return result
        except Exception as e:
            log_manager.logger.error(f"DenseSafetyCheck failed: {e}")
            return []

    def fireworks_safety_check(
        self,
        drone_info_list: List[Dict[str, Any]],
        result_path: str = "",
    ) -> bool:
        """烟花安全检查。

        Args:
            drone_info_list: 无人机信息字典列表。
            result_path: 结果 CSV 文件路径。

        Returns:
            是否检查成功。
        """
        try:
            drama_info = self.use_dict_generate_dramainfo(drone_info_list)
            return self.dll.FireworkSafetyCheck(
                ctypes.byref(drama_info), result_path,
            )
        except Exception as e:
            log_manager.logger.error(f"FireworkSafetyCheck failed: {e}")
            return False

    def path_finding(self, drone_info_list: List[Dict[str, Any]], ellips_ratio: float = 1.0, is_expansion: bool = False) -> Union[List[Dict[str, Any]], bool]:
        """执行路径规划。

        Args:
            drone_info_list: 无人机信息字典列表。
            ellips_ratio: 椭圆比率。
            is_expansion: 是否扩展。

        Returns:
            成功：更新后的 drone_info_list（包含 points 路径，空输入返回 []）。
            失败：False（算法返回非0错误码或抛出异常时）。
        """
        try:
            drama_info = self.use_dict_generate_dramainfo(drone_info_list)
            code = self.dll.PathFinding(
                ctypes.byref(drama_info), ellips_ratio, is_expansion, None, ""
            )
            if code != 0:
                log_manager.logger.warning(f"PathFinding returned error code: {code}")
                return False
            for i, d in enumerate(drone_info_list):
                drone = drama_info.drones[i]
                d["points"] = [[p.x, p.y, p.z] for p in drone.points[:drone.pointsSize]]
            return drone_info_list
        except Exception as e:
            log_manager.logger.error(f"PathFinding failed: {e}")
            return False

    def dynamic_path_finding(
        self,
        drone_info_list: List[Dict[str, Any]],
        start_way_points_count: int = 1,
    ) -> Union[List[Dict[str, Any]], bool]:
        """动态路径规划。

        Args:
            drone_info_list: 无人机信息字典列表。
            start_way_points_count: 起始路径点数量。

        Returns:
            成功：更新后的 drone_info_list（包含 points 路径）。
            失败：False。
        """
        if not drone_info_list:
            log_manager.logger.warning("DynamicPathFinding received empty drone_info_list")
            return False

        try:
            drama_info = self.use_dict_generate_dramainfo(drone_info_list)
            success = self.dll.DynamicPathFinding(
                ctypes.byref(drama_info), start_way_points_count,
            )
            if not success:
                log_manager.logger.warning("DynamicPathFinding DLL returned False")
                return False
            for i, d in enumerate(drone_info_list):
                drone = drama_info.drones[i]
                d["points"] = [[p.x, p.y, p.z] for p in drone.points[:drone.pointsSize]]
            return drone_info_list
        except Exception as e:
            log_manager.logger.error(f"DynamicPathFinding failed: {e}")
            return False

    def dmpc_path_finding(self, drone_info_list: List[Dict[str, Any]]) -> bool:
        """DMPC 路径规划。

        Returns:
            True：DLL 返回 0（成功）。
            False：DLL 返回非 0 错误码或抛出异常。
        """
        if not drone_info_list:
            log_manager.logger.warning("DmpcPathFinding received empty drone_info_list")
            return False

        try:
            p = self.use_dict_generate_dramainfo(drone_info_list)
            # 注意：o 不能为空，否则 DLL 内部会 access violation
            o = self.use_dict_generate_dramainfo(drone_info_list)
            code = self.dll.DmpcPathFinding(p, o, None, None)
            if code != 0:
                log_manager.logger.warning(f"DmpcPathFinding returned error code: {code}")
                return False
            return True
        except Exception as e:
            log_manager.logger.error(f"DmpcPathFinding failed: {e}")
            return False

    def disp_takeoff_land(
        self,
        drone_info_list: List[Dict[str, Any]],
        is_takeoff: bool,
        home_height: float,
    ) -> bool:
        """起降分配。

        Args:
            drone_info_list: 无人机信息字典列表。
            is_takeoff: 是否为起飞。
            home_height: 起降高度。

        Returns:
            True：路径成功生成（pointsSize 被修改且 DLL 返回 0）。
            False：前置检查失败、算法失败或抛出异常。
        """
        try:
            drama_info = self.use_dict_generate_dramainfo(drone_info_list)
            original_sizes = [drama_info.drones[i].pointsSize for i in range(drama_info.size)]
            code = self.dll.DispLand(
                ctypes.byref(drama_info), is_takeoff, home_height,
            )
            if code != 0:
                log_manager.logger.warning(f"DispLand returned non-zero code: {code}")
                return False
            if drama_info.size == 0:
                return True
            new_sizes = [drama_info.drones[i].pointsSize for i in range(drama_info.size)]
            if original_sizes == new_sizes:
                log_manager.logger.warning(
                    "DispLand returned 0 but pointsSize unchanged (前置检查失败)"
                )
                return False
            return True
        except Exception as e:
            log_manager.logger.error(f"DispLand failed: {e}")
            return False

    def disp_land_turn_points(
        self,
        drone_info_list: List[Dict[str, Any]],
        is_takeoff: bool,
        home_height: float,
        turn_points: List[List[float]],
    ) -> bool:
        """执行带转弯点的起降分配。

        说明：C++ 中 `return false`（前置检查失败）和 `return 0`（成功）都被 ctypes
        转为 int 0，无法通过返回值直接区分。本方法通过检查无人机 pointsSize 是否被
        修改来判断真实成功。

        Args:
            drone_info_list: 无人机信息字典列表。
            is_takeoff: 是否为起飞。
            home_height: 起降高度。
            turn_points: 转弯点坐标列表 [[x, y, z], ...]。

        Returns:
            True：路径成功生成（pointsSize 被修改且 DLL 返回 0）。
            False：前置检查失败、算法失败或抛出异常。
        """
        try:
            drama_info = self.use_dict_generate_dramainfo(drone_info_list)
            original_sizes = [drama_info.drones[i].pointsSize for i in range(drama_info.size)]

            turn_arr = (c_class.Point_S * len(turn_points))(
                *[c_class.Point_S(x, y, z) for x, y, z in turn_points]
            )
            code = self.dll.DispLandTurnPoints(
                ctypes.byref(drama_info), is_takeoff, home_height,
                len(turn_points), turn_arr,
            )

            if code != 0:
                log_manager.logger.warning(f"DispLandTurnPoints returned non-zero code: {code}")
                return False

            if drama_info.size == 0:
                return True

            new_sizes = [drama_info.drones[i].pointsSize for i in range(drama_info.size)]
            if original_sizes == new_sizes:
                log_manager.logger.warning(
                    "DispLandTurnPoints returned 0 but pointsSize unchanged (前置检查失败)"
                )
                return False
            return True
        except Exception as e:
            log_manager.logger.error(f"DispLandTurnPoints failed: {e}")
            return False

    def export_drama(
        self,
        drone_info_list: List[Dict[str, Any]],
        result_path: str,
        output_path: str,
    ) -> bool:
        """导出 drama。

        Args:
            drone_info_list: 无人机信息字典列表。
            result_path: 结果路径（wchar_t）。
            output_path: 输出文件路径（utf-8）。

        Returns:
            是否导出成功。
        """
        try:
            drama_info = self.use_dict_generate_dramainfo(drone_info_list)
            check_result = c_class.CheckResultPy(min_dis=0, min_dis_value=float("inf"))
            # 转换为短路径以支持中文文件名
            short_output_path = _to_short_path(output_path)
            return self.dll.ExportDrama(
                ctypes.byref(drama_info), result_path,
                short_output_path.encode("utf-8"), ctypes.byref(check_result),
            )
        except Exception as e:
            log_manager.logger.error(f"ExportDrama failed: {e}")
            return False

    def export_drama3(
        self,
        drama3_info: Any,
        result_path: str,
        output_path: str,
    ) -> bool:
        """导出 drama3。

        Args:
            drama3_info: Drama3Info 结构体实例（由 use_dict_generate_drama3info 生成）。
            result_path: 结果路径（wchar_t）。
            output_path: 输出文件路径（utf-8）。

        Returns:
            是否导出成功。
        """
        try:
            if drama3_info is None:
                log_manager.logger.warning("export_drama3 received None drama3_info")
                return False
            check_result = c_class.CheckResultPy(min_dis=0, min_dis_value=float("inf"))
            # 转换为短路径以支持中文文件名
            short_output_path = _to_short_path(output_path)
            return self.dll.ExportDrama3(
                ctypes.byref(drama3_info), result_path,
                short_output_path.encode("utf-8"), ctypes.byref(check_result),
            )
        except Exception as e:
            log_manager.logger.error(f"ExportDrama3 failed: {e}")
            return False

    def de(self, file_path: str) -> bool:
        """Drama 解密。

        Args:
            file_path: 待解密文件路径（utf-8）。

        Returns:
            是否解密成功。
        """
        try:
            return self.dll.De(file_path.encode("utf-8"))
        except Exception as e:
            log_manager.logger.error(f"De failed: {e}")
            return False

    def best_match(self, drones_info_list: List[Dict[str, Any]], auction: bool = False) -> Union[Dict[int, int], bool]:
        """执行最佳匹配。

        Args:
            drones_info_list: 无人机信息列表。
            auction: 是否使用拍卖算法。

        Returns:
            成功：匹配字典 {drone_id: target_id}（空输入返回空字典 {}）。
            失败：False（DLL 调用抛出异常时）。
        """
        k = ctypes.POINTER(ctypes.c_int)()
        v = ctypes.POINTER(ctypes.c_int)()
        cnt = ctypes.c_int()
        info = self.use_dict_generate_dramainfo(drones_info_list)

        try:
            if auction:
                self.dll.BestMatchAuction(
                    ctypes.byref(info), ctypes.byref(k), ctypes.byref(v), ctypes.byref(cnt), 6
                )
            else:
                self.dll.BestMatch(
                    ctypes.byref(info), ctypes.byref(k), ctypes.byref(v), ctypes.byref(cnt)
                )

            result: Dict[int, int] = {}
            count = cnt.value
            for i in range(count):
                result[k[i]] = v[i]
            return result
        except Exception as e:
            log_manager.logger.error(f"BestMatch failed: {e}")
            return False
        finally:
            if k and v:
                try:
                    self.dll.FreeMatchResult(k, v)
                except Exception as e:
                    log_manager.logger.warning(f"Failed to free BestMatch memory: {e}")

    def encrypt_file(self, file_path: str) -> bool:
        """加密文件。

        Args:
            file_path: 待加密文件路径。

        Returns:
            是否加密成功。
        """
        try:
            return self.dll.EncryptFileSelf(file_path.encode("utf-8"))
        except Exception as e:
            log_manager.logger.logger.error(f"EncryptFileSelf failed: {e}")
            return False

    def decrypt_file(self, file_path: str) -> str:
        """解密文件内容。

        Args:
            file_path: 加密文件路径。

        Returns:
            解密后的内容字符串。失败返回空字符串。
        """
        try:
            ptr = self.dll.ParseFileComponent(file_path.encode("utf-8"))
            if not ptr:
                return ""
            result = ptr.decode("utf-8", errors="replace") if isinstance(ptr, bytes) else str(ptr)
            return result
        except Exception as e:
            log_manager.logger.error(f"ParseFileComponent failed: {e}")
            return ""

    def collision_solve(self, drone_info_list: List[Dict[str, Any]]) -> Union[List[Dict[str, Any]], bool]:
        """执行碰撞解决。

        Returns:
            成功：更新后的 drone_info_list（包含 points 路径，空输入返回 []）。
            失败：False（DLL 调用抛出异常时）。
        """
        try:
            info = self.use_dict_generate_dramainfo(drone_info_list)
            self.dll.CollisionSolve(ctypes.byref(info))
            for i, d in enumerate(drone_info_list):
                drone = info.drones[i]
                d["points"] = [[p.x, p.y, p.z] for p in drone.points[:drone.pointsSize]]
            return drone_info_list
        except Exception as e:
            log_manager.logger.error(f"CollisionSolve failed: {e}")
            return False

    def get_hardware_sn(self) -> str:
        """获取硬件序列号。

        Returns:
            硬件序列号字符串。失败返回空字符串。
        """
        try:
            buf = ctypes.create_string_buffer(256)
            success = self.dll.GetHardwareSN(buf)
            if not success:
                return ""
            return buf.value.decode("utf-8", errors="ignore")
        except Exception as e:
            log_manager.logger.error(f"GetHardwareSN failed: {e}")
            return ""

    def add_two(self, a: int, b: int) -> int:
        """调用 AddTwo 测试函数。

        Args:
            a: 第一个整数。
            b: 第二个整数。

        Returns:
            a + b 的结果。
        """
        return self.dll.AddTwo(a, b)

    def use_dict_generate_dramainfo(
        self,
        drones_info_list: Any,
        map_info: Optional[Dict[str, Any]] = None,
        interval: int = 500,
        start: int = 0,
        end: int = 0,
        color_fps: int = 10,
        pos_fps: int = 2,
        cache: str = "",
        drama_version: int = 2,
    ) -> c_class.DramaInfo:
        """将 Python 字典列表转换为 C 结构体 DramaInfo。

        注意：此函数会保持内部数组的引用（通过 _keepalive 属性），
        以防止 ctypes 对象在函数返回后被垃圾回收导致 C 层悬空指针。

        Args:
            drones_info_list: 无人机信息字典列表。
            map_info: 地图信息字典。
            interval: 时间间隔。
            start: 开始时间。
            end: 结束时间。
            color_fps: 颜色帧率。
            pos_fps: 位置帧率。
            cache: 缓存路径。
            drama_version: Drama 版本号。

        Returns:
            组装好的 DramaInfo 结构体实例。
        """
        if not isinstance(drones_info_list, list):
            drones_info_list = []

        # keepalive 用于防止内部数组被 GC，避免 C 层悬空指针
        keepalive: List[Any] = []
        arr = (c_class.DroneInfo * len(drones_info_list))()
        keepalive.append(arr)

        for i, d in enumerate(drones_info_list):
            pts = d.get("points", [[0, 0, 1]])
            points = (c_class.Point_S * len(pts))(
                *[c_class.Point_S(x, y, z) for x, y, z in pts]
            )
            keepalive.append(points)

            cols = d.get("colors", [[0, 0, 0]])
            colors = (c_class.Color_S * len(cols))(
                *[c_class.Color_S(r, g, b) for r, g, b in cols]
            )
            keepalive.append(colors)

            fw_angles = d.get("fireworksAngle", [])
            fw_cnt = len(fw_angles)
            fw_arr = (ctypes.c_int * fw_cnt)(*fw_angles) if fw_cnt else None
            if fw_arr is not None:
                keepalive.append(fw_arr)

            arr[i] = c_class.DroneInfo(
                droneType=d.get("droneType", 1),
                droneId=d.get("droneId", 1),
                startTime=int(d.get("startTime", 0)),
                endTime=int(d.get("endTime", 10000)),
                returnType=d.get("returnType", 1),
                horizonAcc=d.get("horizonAcc", 2.0),
                horizonSpeed=d.get("horizonSpeed", 5.0),
                horizonSpeedX=d.get("horizonSpeedX", 0.0),
                horizonSpeedY=d.get("horizonSpeedY", 0.0),
                speed=d.get("speed", 5.0),
                verticalAcc=d.get("verticalAcc", 1.0),
                verticalSpeed=d.get("verticalSpeed", 2.0),
                points=points,
                pointsSize=len(pts),
                colors=colors,
                colorsSize=len(cols),
                fireworksCnt=fw_cnt,
                fireworksAngle=fw_arr,
            )

        m = map_info or self.empty_map
        c_map = c_class.DmdMap(
            rotate=m["rotate"],
            name=ctypes.c_char_p(b"none"),
            widthScale=m["widthScale"],
            heightScale=m["heightScale"],
            x=m["x"],
            y=m["y"],
            z=m["z"],
            lon=m["lon"],
            lat=m["lat"],
        )

        result = c_class.DramaInfo(
            drones=arr,
            size=len(drones_info_list),
            dramaVersion=drama_version,
            map=c_map,
            interval=int(interval),
            colorFps=int(color_fps),
            pointFps=int(pos_fps),
            startTime=int(start),
            endTime=int(end),
            totalCount=262144,
            logPath=ctypes.c_char_p(b""),
            userCache=ctypes.c_char_p(b""),
        )
        # 关键：保持所有内部数组的引用，防止 GC 回收后 C 层指针悬空
        result._keepalive = keepalive
        return result

    def use_dict_generate_drama3info(self, *args: Any, **kwargs: Any) -> Any:
        """生成 Drama3Info（当前为空实现）。"""
        warnings.warn("use_dict_generate_drama3info is not implemented yet", stacklevel=2)
        return None

    @staticmethod
    def get_drone3_list_elem_dict() -> Dict[str, Any]:
        """获取 Drone3 列表元素模板字典。"""
        return {}

    def encrypt_drama_file(self, *args: Any, **kwargs: Any) -> bool:
        """加密 drama 文件（当前为空实现）。"""
        warnings.warn("encrypt_drama_file is not implemented yet", stacklevel=2)
        return False

    def mesh_path_to_point(
        self,
        drone_info_list: List[Dict[str, Any]],
        mesh_path: str,
        target_count: int,
    ) -> Tuple[bool, int]:
        """从 Mesh 文件路径生成点位。

        Args:
            drone_info_list: 无人机信息字典列表。
            mesh_path: Mesh 文件路径。
            target_count: 目标点位数量。

        Returns:
            (是否成功, shellcvt_status 状态码)。
        """
        try:
            drama_info = self.use_dict_generate_dramainfo(drone_info_list)
            status = ctypes.c_int()
            # 转换为短路径以支持中文文件名
            short_mesh_path = _to_short_path(mesh_path)
            if short_mesh_path != mesh_path:
                log_manager.logger.debug(f"[mesh_path_to_point] 路径转换: {mesh_path} -> {short_mesh_path}")
            result = self.dll.MeshPath2Point(
                ctypes.byref(drama_info),
                short_mesh_path.encode("utf-8"),
                target_count,
                ctypes.byref(status),
            )
            if result:
                for i, d in enumerate(drone_info_list):
                    if i < drama_info.size:
                        drone = drama_info.drones[i]
                        d["points"] = [[drone.points[0].x, drone.points[0].y, drone.points[0].z]]
            return result, status.value
        except Exception as e:
            log_manager.logger.error(f"MeshPath2Point failed: {e}")
            return False, -1

    def mesh_bytes_to_point(
        self,
        drone_info_list: List[Dict[str, Any]],
        data: bytes,
        mesh_format: int,
        target_count: int,
    ) -> Tuple[bool, int]:
        """从 Mesh 字节数据生成点位。

        Args:
            drone_info_list: 无人机信息字典列表。
            data: Mesh 字节数据。
            mesh_format: Mesh 格式。
            target_count: 目标点位数量。

        Returns:
            (是否成功, shellcvt_status 状态码)。
        """
        try:
            drama_info = self.use_dict_generate_dramainfo(drone_info_list)
            status = ctypes.c_int()
            data_arr = (ctypes.c_uint8 * len(data))(*data)
            result = self.dll.MeshBytes2Point(
                ctypes.byref(drama_info),
                data_arr,
                len(data),
                mesh_format,
                target_count,
                ctypes.byref(status),
            )
            if result:
                for i, d in enumerate(drone_info_list):
                    if i < drama_info.size:
                        drone = drama_info.drones[i]
                        d["points"] = [[drone.points[0].x, drone.points[0].y, drone.points[0].z]]
            return result, status.value
        except Exception as e:
            log_manager.logger.error(f"MeshBytes2Point failed: {e}")
            return False, -1

    def line_to_point(
        self,
        drone_info_list: List[Dict[str, Any]],
        input_type: int,
        mode: int,
        data: bytes,
        target_dot_count: int,
    ) -> Tuple[bool, int]:
        """从线条数据生成点位。

        Args:
            drone_info_list: 无人机信息字典列表。
            input_type: 输入类型。
            mode: 模式。
            data: 线条字节数据。
            target_dot_count: 目标点位数量。

        Returns:
            (是否成功, l2d_status 状态码)。
        """
        try:
            drama_info = self.use_dict_generate_dramainfo(drone_info_list)
            status = ctypes.c_int()
            data_arr = (ctypes.c_uint8 * len(data))(*data)
            result = self.dll.Line2Point(
                ctypes.byref(drama_info),
                input_type,
                mode,
                data_arr,
                len(data),
                target_dot_count,
                ctypes.byref(status),
            )
            if result:
                for i, d in enumerate(drone_info_list):
                    if i < drama_info.size:
                        drone = drama_info.drones[i]
                        d["points"] = [[drone.points[0].x, drone.points[0].y, drone.points[0].z]]
            return result, status.value
        except Exception as e:
            log_manager.logger.error(f"Line2Point failed: {e}")
            return False, -1
