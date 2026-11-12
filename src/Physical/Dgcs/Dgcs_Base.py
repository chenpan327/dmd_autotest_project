import json
import time

import psutil
import uiautomation as auto
from uiautomation import *
import subprocess
from utils.logger import log_manager
from pathlib import Path
from utils.web_cloud import load_config

current_path = os.path.dirname(os.path.abspath(__file__))
root_path = os.path.split(os.path.split(os.path.dirname(current_path))[0])[0]
conf_info = load_config().get("Ground_Station", {})


# auto.Logger.SetLogFile(root_path + "/logs/test_log.log")


class DgCSUi:
    def __init__(self):
        auto.SetGlobalSearchTimeout(10)

        self._cache = {}
        self.app_path = conf_info['app_path']
        self.user = conf_info['user_name']
        self.pwd = conf_info['login_passwd']
        self.main_tree = None

    # ================== 进程管理 ==================
    @staticmethod
    def _kill_process_by_name(process_name):
        for proc in psutil.process_iter(attrs=['pid', 'name']):
            if proc.info['name'] == process_name:
                try:
                    psutil.Process(proc.info['pid']).terminate()
                except Exception as e:
                    log_manager.logger.warning(f"Kill process failed: {process_name}, {e}")

    def start_app(self):
        for p in ("DGCS.exe", "umap.exe"):
            self._kill_process_by_name(p)

        try:
            subprocess.Popen(
                [self.app_path],
                cwd=os.path.dirname(self.app_path)  # ⭐关键：指定工作目录
            )

        except Exception as e:
            log_manager.logger.error(f"Start app failed: {e.__repr__()}")
            raise

    # ================== 控件树构建 ==================
    @staticmethod
    def _get_control_key(control):
        """统一生成控件key"""
        return next(
            (x for x in (
                control.AutomationId,
                control.HelpText,
                control.Name,
                control.ClassName
            ) if x),
            "Unknown"
        )

    def _build_tree(self, control):
        """递归构建控件树"""
        result = {}

        try:
            children = control.GetChildren()
        except Exception as e:
            log_manager.logger.error(e.__repr__())
            return result

        for child in children:
            key = self._get_control_key(child)

            # ⚠️ 避免重复 key 覆盖
            if key in result:
                key = f"{key}_{id(child)}"

            result[key] = {
                "instance": child,
                "child": self._build_tree(child)
            }

        return result

    def _find_node(self, data, target_key):
        """
        查找唯一 key，返回完整节点
        """
        if not isinstance(data, dict):
            return None

        # 当前层命中
        if target_key in data:
            return data[target_key]

        # 递归 child
        for v in data.values():
            if isinstance(v, dict) and 'child' in v:
                res = self._find_node(v['child'], target_key)
                if res:
                    return res
        return None

    def get_node(self, key, control_instance=None, timeout=10, interval=0.5, active=True):
        """
        获取有效控件

        逻辑：
        1. 优先从缓存获取（只查一次）
        2. 指定子树 -> 直接查找，不循环
        3. 主窗口 -> retry + refresh
        """

        # ==========================================
        # 1. 优先从缓存获取（只查一次）
        # ==========================================
        cache_ctrl = self._cache.get(key)

        if cache_ctrl:
            try:
                if cache_ctrl["instance"].Exists(0.2):

                    rect = cache_ctrl["instance"].BoundingRectangle
                    if not (rect.left == 0 and rect.top == 0 and rect.right == 0 and rect.bottom == 0):
                        return cache_ctrl
                else:
                    # 缓存失效
                    self._cache.pop(key, None)
            except Exception:
                # COM对象失效
                self._cache.pop(key, None)

        # ==========================================
        # 2. 指定子树（不循环）
        # ==========================================
        if control_instance is not None:
            try:
                ctrl = self._find_node(control_instance, key)
                if not ctrl:
                    raise Exception(f"{key} not found from sub tree")

                if not ctrl['instance'].Exists(0.2):
                    raise Exception(f"{key} invalid")
                return ctrl
            except Exception as e:
                log_manager.logger.info(f"find {key} retry... ")
                raise Exception(f"{key} get node failed: {e}")

        # ==========================================
        # 3. 主窗口模式（循环查找）
        # ==========================================
        start = time.time()
        while time.time() - start < timeout:
            try:
                # 当前树查找
                ctrl = self._find_node(self.main_tree, key)
                if ctrl and ctrl['instance'].Exists(0.2):

                    rect = ctrl['instance'].BoundingRectangle
                    if (rect.left == 0 and rect.top == 0 and rect.right == 0 and rect.bottom == 0):
                        raise Exception(f"{key} invalid")

                    # 更新缓存（最新覆盖旧缓存）
                    if key not in ("ConfirmButton"):
                        self._cache[key] = ctrl
                    return ctrl

                # 查找失败 -> 刷新主窗口树
                self._get_main_window(active=active)
            except Exception as e:
                log_manager.logger.warning(f"get node retry: {e}")
                try:
                    self._get_main_window(active=active)
                except Exception:
                    pass
            time.sleep(interval)
        log_manager.logger.warning(f"{key} not found")
        return None

    def input_text(self, key, text, control_instance=None, timeout=10, active=True):

        ctrl = self.get_node(
            key=key,
            control_instance=control_instance,
            timeout=timeout,
            active=active
        )

        try:
            # 激活输入框
            ctrl['instance'].Click()
            # 清空文本
            auto.SendKeys("{Ctrl}a{Delete}")
            # 输入内容
            auto.SendKeys(text)

            log_manager.logger.info(f">>>> input [{key}] = {text}")
        except Exception as e:
            raise AssertionError(f"{key} input failed: {e}")

    def click(self, key, control_instance=None, wait_loading=False, timeout=10, active=True, **kwargs):
        ctrl = self.get_node(
            key,
            control_instance=control_instance,
            timeout=timeout,
            active=active
        )
        ctrl['instance'].Click(**kwargs)
        log_manager.logger.info(f">>>> {key} clicked")
        if wait_loading:
            self.wait_loading_finished()

    def save_screenshot(self, control_instance, key):
        self.get_node(key, control_instance=control_instance)['instance'].CaptureToImage(
            root_path + f"/file/picture/{key}.png")

    def _handle_warning(self):
        """处理登录后的警告弹窗"""

        login_window = self._get_login_window()
        warning_ctrl = login_window.get("警告", None)

        if not warning_ctrl:
            return False, None
        msg_ctrl = self.get_node('MessageTextBlock', control_instance=login_window)
        msg = msg_ctrl['instance'].Name

        self.click("ConfirmButton", control_instance=login_window, wait_loading=True)
        log_manager.logger.info(f"{msg}")
        return True, msg

    def _get_main_window(self, active=True):
        win = auto.WindowControl(Name="大漠大地面控制站")
        if not win.Exists(maxSearchSeconds=30):
            log_manager.logger.error('未发现主窗口')
            raise AssertionError('未发现主窗口')
        else:
            if active:
                win.SetActive()

            win.CaptureToImage(root_path + f"/file/picture/main.png")
            self.main_tree = self._build_tree(win)

    def _get_login_window(self):
        win = auto.WindowControl(searchDepth=10, RegexName='DGCS.*')
        if not win.Exists(maxSearchSeconds=30):
            log_manager.logger.error('未发现登录窗口')
            raise AssertionError('未发现登录窗口')
        else:
            win.SetActive()
            win.CaptureToImage(root_path + f"/file/picture/login.png")
            return self._build_tree(win)

    def _get_debug_window(self, active=True):
        win = auto.WindowControl(searchDepth=10, RegexName='模拟器工具.*')

        if not win.Exists(maxSearchSeconds=20):
            log_manager.logger.error('未发现模拟器工具窗口')
            raise AssertionError('未发现模拟器窗口')
        else:
            if active:
                win.SetActive()
            win.CaptureToImage(root_path + f"/file/picture/debug_tool.png")
            return self._build_tree(win)

    def wait_loading_finished(self, interval=0.5):
        """
        等待 loading 消失
        """

        start = time.time()
        while time.time() - start < 180:

            try:
                loading = auto.TextControl(
                    AutomationId="Utils_Loading_StatusTextBlock"
                )

                # 不存在
                if not loading.Exists(0.5):
                    return True

                # 存在但不可见
                if loading.IsOffscreen:
                    return True

            except Exception:
                # 控件失效也认为 loading 结束
                return True

            time.sleep(interval)

        raise TimeoutError("loading wait timeout")
