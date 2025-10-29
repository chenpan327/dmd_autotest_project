import inspect
import os.path
from datetime import datetime

from selenium import webdriver
from selenium.common import NoSuchElementException, TimeoutException
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import time
import configparser
from selenium.webdriver.chrome.options import Options

current_path = os.path.dirname(os.path.abspath(__file__))
root_path = os.path.dirname(current_path)

curr_date = datetime.today().strftime('%Y%m%d')
import logging

logger = logging.getLogger(__name__)
from utils.webFuntion import get_captcha, get_data

cloud_info = get_data(root_path + r'/WebBase/web_info.yaml')


class UIBase:
    def __init__(self, test_user, test_password, debug=True):
        self.username = test_user
        self.password = test_password
        self.debug = debug
        self.sub_menu = {"username": "(//input[@class='el-input__inner'])[%s]",
                         "password": "(//input[@class='el-input__inner'])[%s]",
                         "captcha": "(//input[@placeholder='输入验证码']/.)[%s]",
                         "login": "(//span[text()='登录']/..)[%s]",
                         "工作台": "(//span[text()='工作台'])",
                         "设备中心": "(//span[text()='设备中心'])[%s]",
                         "无人机管理": "(//span[text()='无人机管理'])[%s]",
                         "故障记录": "(//span[text()='故障记录'])[%s]",
                         "维修记录": "(//span[text()='维修记录'])[%s]",
                         "电池管理": "(//span[text()='电池管理'])[%s]",
                         "表演记录": "(//span[text()='表演记录'])[%s]",
                         "飞行记录": "(//span[text()='飞行记录'])[%s]",
                         "辅助设备": "(//span[text()='辅助设备'])[%s]",
                         "txtWidget": "(//input[@class='el-input__inner' and @type='text'])[%s]",
                         "addButton": "(//span[text()='新增']/..)[%s]",
                         "confirm": "(//span[text()='确定']/parent::button[@class='el-button el-button--primary'])[%s]",
                         "searchButton": "(//span[text()='查询']/..)[%s]",
                         "operateCell": "(//div[@class='operate-cell']/a)[%s]",
                         "selectorWidget": "(//div[@class='el-select__selected-item el-select__placeholder is-transparent'])[%s]",
                         }

        chrome_options = Options()
        if not debug:
            chrome_options.add_argument("--headless")  # 启用无头模式
            chrome_options.add_argument("--disable-gpu")  # 解决某些系统兼容性问题
            chrome_options.add_argument("--window-size=2560x1440")  # 设置窗口大小
            chrome_options.add_argument("--no-sandbox")  # 解决某些环境问题
            chrome_options.add_argument("--disable-dev-shm-usage")
        self.driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=chrome_options)
        self.url = cloud_info['base_url']
        self.wait = WebDriverWait(self.driver, 30)

    def open_page(self):
        # 打开登录页面
        self.driver.get(self.url)
        self.driver.implicitly_wait(10)
        time.sleep(1)

    def _click(self, key, index=1):
        try:

            xpath = self.sub_menu[key] % index
            self.driver.implicitly_wait(10)
            # print(xpath)
            self.wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
            self.driver.find_element(By.XPATH, xpath).click()
            time.sleep(0.7)
        except (NoSuchElementException, TimeoutException) as e:
            logger.error(f"未发现{key}按钮")
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
            logger.error(f"未发现{xpath}按钮")
            raise Exception(f'-->{key}<-- not found')

    def _double_click(self, key):
        try:
            xpath = self.sub_menu[key]

            self.wait.until(EC.element_to_be_clickable((By.CLASS_NAME, xpath)))
            element = self.driver.find_element(By.CLASS_NAME, xpath)
            action = ActionChains(self.driver)
            action.double_click(element).perform()
            time.sleep(1)
        except (NoSuchElementException, TimeoutException) as e:
            logger.error(f"未发现{key}按钮")
            raise Exception(f'-->{key}<-- not found')

    def _get_value(self, key):
        try:
            xpath = self.sub_menu[key]
            # print(xpath)
            self.wait.until(EC.visibility_of_element_located((By.CLASS_NAME, xpath)))
            ele_value = self.driver.find_element(By.CLASS_NAME, xpath).text
            time.sleep(1)
            return ele_value
        except (NoSuchElementException, TimeoutException) as e:
            logger.error(f"未发现{key}按钮")
            raise Exception(f'-->{key}<-- not found')

    def _import_file(self, file_path):
        try:
            upload_input = self.driver.find_element(By.CSS_SELECTOR, 'input.el-upload__input')
            upload_input.send_keys(file_path)
        except NoSuchElementException as e:
            logger.error(f"未发现{e.__repr__}按钮")
            raise Exception(f'-->file upload failed <--')

    def login(self):
        try:
            self.open_page()
            time.sleep(1)

            self.driver.maximize_window()
            self._input("username", self.username)
            self._input("password", self.password, index=2)
            captcha = get_captcha()
            print("==========", captcha)
            self._input("captcha", captcha)
            self._click("login")
            time.sleep(1)
            logger.info(f"{self.username}登录成功")
        except Exception as e:
            logger.error("登录异常", e.__repr__())

    def close(self):
        self.driver.close()

    def refresh(self):
        self.driver.refresh()
        time.sleep(1)

    def _scrolltoView(self, key):
        element = self.driver.find_element(By.XPATH, self.sub_menu[key])
        self.driver.execute_script("""
            arguments[0].scrollIntoView({behavior: "smooth", block: "center"});
        """, element)

    # 保存截图
    def save_screenshot(self, output_path):
        self.driver.implicitly_wait(10)
        time.sleep(2)
        self.driver.save_screenshot(output_path)


if __name__ == '__main__':
    test = UIBase("alan", "dmd@2025")
    a = get_captcha()
    test.login()

    print(root_path)
    print(cloud_info)
