import time
import pyautogui
from pywinauto.application import Application
from pywinauto.keyboard import send_keys
from utils.logger import logger

class AppBase:
    """底层操作类：封装对窗口和控件的操作"""

    def __init__(self, app_path: str, window_title_re: str, process_name: str):
        self.app_path = app_path
        self.window_title_re = window_title_re
        self.process_name = process_name
        self.app: Application | None = None
        self.main_window = None

    def start_app(self):
        """启动 APP 并获取主窗口"""
        try:
            self.app = Application(backend="uia").start(self.app_path)
            time.sleep(2)
            self.main_window = self.app.window(title_re=self.window_title_re)
            self.main_window.set_focus()
            logger.info(f"启动 APP 成功: {self.app_path}")
        except Exception as e:
            logger.error(f"启动 APP 失败: {e}")
            raise

    def focus_main_window(self):
        """激活主窗口"""
        try:
            self.main_window.set_focus()
            time.sleep(1)
            logger.info("主窗口聚焦成功")
        except Exception as e:
            logger.error(f"focus_main_window失败: {e}")
            raise

    def input_username(self, username: str):
        try:
            username_field = self.main_window.child_window(auto_id="cboxUserName", control_type="ComboBox")
            username_field.set_focus()
            send_keys(username)
            pyautogui.press("tab")
            pyautogui.hotkey("ctrl", "a")
            pyautogui.press("delete")
            time.sleep(0.5)
            logger.info(f"输入用户名成功: {username}")
        except Exception as e:
            logger.error(f"input_username失败: {e}")
            raise

    def input_password(self, password: str):
        try:
            send_keys(password)
            time.sleep(0.5)
            logger.info("输入密码成功")
        except Exception as e:
            logger.error(f"input_password失败: {e}")
            raise

    def click_login(self):
        try:
            login_btn = self.main_window.child_window(title="登录", auto_id="btnLogin", control_type="Button")
            login_btn.click()
            time.sleep(2)
            logger.info("点击登录按钮成功")
        except Exception as e:
            logger.error(f"click_login失败: {e}")
            raise

    def click_flight_control(self):
        try:
            btn = self.main_window.child_window(auto_id="tbtnFlightControl", control_type="Pane")
            btn.click_input()
            time.sleep(0.1)
            btn.click_input()
            logger.info("点击飞行控制成功")
        except Exception as e:
            logger.error(f"click_flight_control失败: {e}")
            raise

    def kill_app(self):
        """关闭进程"""
        import psutil
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'] == self.process_name:
                proc.kill()
                logger.info(f"已关闭进程: {self.process_name}")
