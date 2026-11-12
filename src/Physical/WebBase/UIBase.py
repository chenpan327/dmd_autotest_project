import inspect
# import os
import sys
from datetime import datetime
from utils.logger import log_manager
from utils.web_cloud import get_captcha, load_config
from selenium.common import NoSuchElementException, TimeoutException
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from airtest.core.api import *
from pathlib import Path
import threading
import time
from io import BytesIO

import imageio
from PIL import Image
from selenium.webdriver.common.by import By

from airtest.core.cv import Template
from airtest.aircv import imread

current_path = os.path.dirname(os.path.abspath(__file__))
root_path = os.path.split(os.path.split(os.path.dirname(current_path))[0])[0]
curr_date = datetime.today().strftime('%Y%m%d')

# 延迟加载配置，避免模块导入时失败
cloud_info = None


def get_cloud_info():
    global cloud_info
    if cloud_info is None:
        cloud_info = load_config().get("Cloud_Platform_Ui", {})
        if cloud_info is None:
            log_manager.logger.error("未找到 Cloud_Platform_Ui 配置")
            raise ValueError("未找到 Cloud_Platform_Ui 配置")
    return cloud_info


auto_setup(__file__, devices=["Windows:///"])


class UIBase:
    _instances = {}

    def __new__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[cls] = instance
        return cls._instances[cls]

    def __init__(self, driver):
        self.driver = driver
        self.node_name = None
        self.sub_menu = {"username": "(//input[@class='el-input__inner'])[%s]",
                         "password": "(//input[@class='el-input__inner'])[%s]",
                         "captcha": "(//input[@placeholder='输入验证码']/.)[%s]",
                         "login": "(//span[text()='登录']/..)[%s]",
                         "工作台": "(//span[text()='工作台'])[%s]",
                         "服务项目中心": "(//span[text()='服务项目中心'])[%s]",
                         "飞行项目管理": "(//span[text()='飞行项目管理'])[%s]",
                         "表演二维码管理": "(//span[text()='表演二维码管理'])[%s]",
                         "设备中心": "(//span[text()='设备中心'])[%s]",
                         "无人机管理": "(//span[text()='无人机管理'])[%s]",
                         "故障记录": "(//span[text()='故障记录'])[%s]",
                         "维修记录": "(//span[text()='维修记录'])[%s]",
                         "电池管理": "(//span[text()='电池管理'])[%s]",
                         "表演记录": "(//span[text()='表演记录'])[%s]",
                         "飞行记录": "(//span[text()='飞行记录'])[%s]",
                         "辅助设备": "(//span[text()='辅助设备'])[%s]",
                         "地控中心": "(//span[text()='地控中心'])[%s]",
                         "地面站管理": "(//span[text()='地面站管理'])[%s]",
                         "剧本编辑器管理": "(//span[text()='剧本编辑器管理'])[%s]",
                         "无人机组件管理": "(//span[text()='无人机组件管理'])[%s]",
                         "无人机类型管理": "(//span[text()='无人机类型管理'])[%s]",
                         "差分账号管理": "(//span[text()='差分账号管理'])[%s]",
                         "电台类型管理": "(//span[text()='电台类型管理'])[%s]",
                         "组合版本管理": "(//span[text()='组合版本管理'])[%s]",
                         "产品版本管理": "(//span[text()='产品版本管理'])[%s]",
                         "飞控参数管理": "(//span[text()='飞控参数管理'])[%s]",
                         "飞行区域管理": "(//span[text()='飞行区域管理'])[%s]",
                         "飞行区域GIS": "(//span[text()='飞行区域GIS'])[%s]",
                         "生产中心": "(//span[text()='生产中心'])[%s]",
                         "库存管理": "(//span[text()='库存管理'])[%s]",
                         "销售出库": "(//span[text()='销售出库'])[%s]",
                         "设备类型": "(//span[text()='设备类型'])[%s]",
                         "编码规则": "(//span[text()='编码规则'])[%s]",
                         "售后中心": "(//span[text()='售后中心'])[%s]",
                         "故障类型管理": "(//span[text()='故障类型管理'])[%s]",
                         "维修管理": "(//span[text()='维修管理'])[%s]",
                         "故障现象管理": "(//span[text()='故障现象管理'])[%s]",
                         "维修订单": "(//span[text()='维修订单'])[%s]",
                         "评级管理": "(//span[text()='评级管理'])[%s]",
                         "等级管理":"(//span[text()='等级管理'])[%s]",
                         "人员管理": "(//span[text()='人员管理'])[%s]",
                         "close": "(//button[@class='promotion-close'])[%s]",
                         "txtWidget": "(//input[@class='el-input__inner' and @type='text'])[%s]",
                         "addButton": "(//span[text()='新增']/..)[%s]",
                         "confirm": "(//span[text()='确定']/parent::button[@class='el-button el-button--primary'])[%s]",
                         "searchButton": "(//span[text()='查询']/..)[%s]",
                         "operateCell": "(//div[@class='operate-cell']/a)[%s]",
                         "selectorWidget": "(//div[@class='el-select__selected-item el-select__placeholder is-transparent'])[%s]",
                         }
        self.cloud_info = get_cloud_info()
        self.url = self.cloud_info['base_url']
        self.username = self.cloud_info['test_user']
        self.password = self.cloud_info['test_pwd']
        self.wait = WebDriverWait(self.driver, 30)

    # def __call__(self):
    #     return self

    # ==============================
    # 基础封装方法
    # ==============================

    def _click(self, key, index=1):
        try:
            xpath = self.sub_menu[key] % index
            self.driver.implicitly_wait(10)
            self.wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
            self.driver.find_element(By.XPATH, xpath).click()
            time.sleep(0.7)
        except (NoSuchElementException, TimeoutException) as e:
            log_manager.logger.error(f"未发现{key}按钮")
            raise Exception(f'-->{key}<-- not found')

    def _input(self, key, words, index=1):
        try:
            xpath = self.sub_menu[key] % index
            self.driver.implicitly_wait(10)
            self.wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
            input_box = self.driver.find_element(By.XPATH, xpath)
            input_box.clear()
            input_box.send_keys(words)
            time.sleep(1)
        except (NoSuchElementException, TimeoutException) as e:
            log_manager.logger.error(f"未发现{xpath}按钮")
            raise Exception(f'-->{key}<-- not found')

    def _double_click(self, key, index=1):
        try:
            xpath = self.sub_menu[key] % index

            self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
            element = self.driver.find_element(By.XPATH, xpath)
            action = ActionChains(self.driver)
            action.double_click(element).perform()
            time.sleep(1)
        except (NoSuchElementException, TimeoutException) as e:
            log_manager.logger.error(f"未发现{key}按钮")
            raise Exception(f'-->{key}<-- not found')

    def _get_value(self, key, index=1):
        try:
            xpath = self.sub_menu[key] % index
            # print(xpath)
            self.wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
            ele_value = self.driver.find_element(By.XPATH, xpath).text
            time.sleep(1)
            return ele_value
        except (NoSuchElementException, TimeoutException) as e:
            log_manager.logger.error(f"未发现{key}按钮")
            raise Exception(f'-->{key}<-- not found')

    def _import_file(self, file):
        try:
            file_path = root_path + f"/file/excel/{file}"
            upload_input = self.driver.find_element(By.CSS_SELECTOR, 'input.el-upload__input')
            upload_input.send_keys(file_path)
        except NoSuchElementException as e:
            log_manager.logger.error(f"未发现{e.__repr__}按钮")
            raise Exception(f'-->file upload failed <--')

    def _scrolltoView(self, key, index=1):
        xpath = self.sub_menu[key] % index
        element = self.driver.find_element(By.XPATH, xpath)
        self.driver.execute_script("""
            arguments[0].scrollIntoView({behavior: "smooth", block: "center"});
        """, element)

    # ==============================
    # 页面操作
    # ==============================
    def open_page(self):
        # 打开登录页面
        self.driver.get(self.url)
        self.driver.implicitly_wait(10)
        time.sleep(1)

    def login(self):
        try:
            self.open_page()
            time.sleep(1)
            self._input("username", self.username)
            self._input("password", self.password, index=2)
            captcha = get_captcha()
            self._input("captcha", captcha)
            self._click("login")
            time.sleep(2)
            try:
                self.driver.find_element(By.XPATH, self.sub_menu['close'] % 1).click()
            except Exception as e:
                pass
            log_manager.logger.info(f"{self.username}登录成功")
            return self
        except Exception as e:
            log_manager.logger.error("登录异常", e.__repr__())

    def close(self):
        self.driver.close()

    def refresh(self):
        self.driver.refresh()
        time.sleep(1)

    def _checkPictures(self, template_path, threshold=0.95):
        """
        Match screenshots with templates and save screenshot file
        """
        try:
            time.sleep(1)

            # Template path
            template_path = Path(root_path) / "src" / "Protocol" / "image" / template_path

            # 设置 threshold=0 以获取真实 confidence
            tpl = Template(str(template_path), threshold=0)

            # screenshot name
            self.node_name = f"{self.__class__.__name__.lower()}-{sys._getframe(1).f_code.co_name}"

            screenshot_path = Path(root_path) / "file" / "picture" / f"{self.node_name.lower()}.png"

            # take screenshot
            self.driver.get_screenshot_as_file(str(screenshot_path))

            screen = imread(str(screenshot_path))

            # template match
            result = tpl._cv_match(screen)

            # 获取真实 confidence
            confidence = result["confidence"] if result else 0

            log_manager.logger.info(
                f"\n模板: {template_path}"
                f"\n截图: {screenshot_path}"
                f"\nthreshold: {threshold}"
                f"\nconfidence: {confidence}"
            )

            # 判断是否匹配成功
            if confidence >= threshold:
                log_manager.logger.info(f"{self.node_name}图片匹配成功")
                return True
            else:
                log_manager.logger.error(f"{self.node_name}图片匹配失败")
                return False

        except Exception as e:
            log_manager.logger.exception(f"图片匹配异常---> {template_path}")
            raise

    def get_toast_text(self, index=1):
        """
        get toast text and save screenshot
        """
        self.node_name = f"{self.__class__.__name__.lower()}-{sys._getframe(1).f_code.co_name}"
        toast = None
        try:
            TOAST = (By.XPATH, f"(//p[@class='el-message__content'])[{index}]")
            toast = self.wait.until(EC.visibility_of_element_located(TOAST))
            log_manager.logger.info(str(self.node_name) + "=========>" + f":{toast.text}")
        except Exception as e:
            log_manager.logger.error(e.__repr__)

        screenshot_path = Path(root_path) / "file" / "picture" / f"{self.node_name.lower()}.png"
        self.driver.get_screenshot_as_file(screenshot_path)

        return toast.text


class GifRecorder:

    def __init__(self,
                 driver,
                 output="record.gif",
                 fps=3):

        self.driver = driver
        self.output = output
        self.fps = fps

        self.frames = []

        self.running = False

        self.thread = None

    # =========================
    # 开始录制
    # =========================
    def start(self):

        if self.running:
            return

        self.running = True
        self.frames.clear()
        self.thread = threading.Thread(
            target=self._record,
            daemon=True
        )

        self.thread.start()

    # =========================
    # 录制线程
    # =========================
    def _record(self):
        interval = 1 / self.fps
        while self.running:
            try:
                png = self.driver.get_screenshot_as_png()
                img = Image.open(
                    BytesIO(png)
                )
                self.frames.append(img)
            except Exception as e:
                print(e)
            time.sleep(interval)

    # =========================
    # 停止录制
    # =========================
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()

        if self.frames:
            imageio.mimsave(
                self.output,
                self.frames,
                duration=1
            )
            print(f"gif saved: {self.output}")
