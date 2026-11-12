from pywinauto import Application
from pywinauto.application import ProcessNotFoundError

class AppBase:
    def __init__(self, app_path=None, window_title=None):
        """
        初始化基础类。启动应用或连接到已存在的应用窗口。
        :param app_path: 应用路径，用于启动应用。
        :param window_title: 应用窗口标题，用于连接到已运行的应用窗口。
        """
        self.app = None
        self.window = None

        if app_path:
            self.start_application(app_path)
        elif window_title:
            self.connect_to_window(window_title)
        else:
            raise ValueError("You must provide either an app path or a window title.")

    def start_application(self, app_path):
        """
        启动应用程序并连接到它的主窗口。
        :param app_path: 应用程序的路径
        """
        try:
            self.app = Application().start(app_path)
            # 等待应用启动并获取主窗口
            self.window = self.app.window()
        except Exception as e:
            print(f"Error starting application: {e}")

    def connect_to_window(self, window_title):
        """
        根据窗口标题连接到已运行的应用。
        :param window_title: 应用的窗口标题
        """
        try:
            self.window = Application().connect(title=window_title).window()
        except ProcessNotFoundError:
            print(f"Window with title '{window_title}' not found.")
        except Exception as e:
            print(f"Error connecting to window: {e}")

    def close_window(self):
        """
        关闭当前连接的应用窗口
        """
        try:
            self.window.close()
        except Exception as e:
            print(f"Error closing window: {e}")

    def wait_for_window(self, timeout=10):
        """
        等待窗口出现
        :param timeout: 等待窗口出现的时间（秒）
        """
        try:
            self.window.wait('visible', timeout=timeout)
        except Exception as e:
            print(f"Error waiting for window: {e}")
