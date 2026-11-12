# -*- coding: utf-8 -*-
"""
===============================================================================
                                Web 自动化测试脚本
===============================================================================
脚本编号：DMD_TEST_DEVICE_CENTER_WEB_001
脚本版本：v1.0
创建日期：2025-10-29
开发人员：陈新江
版权所属：深圳大漠大智控技术有限公司
适用产品：设备中心管理系统
测试类型：Web 功能测试
测试环境：Python 3.10, Selenium WebDriver, Allure 报告，Pytest 框架

===============================================================================
测试目的:
验证设备中心 Web 管理系统的核心功能模块：
1. 无人机管理模块（增删查、批量导入）
2. 故障记录模块
3. 维修记录模块
4. 电池管理模块
5. 表演记录模块
6. 飞行记录模块
7. 辅助设备管理模块

===============================================================================
技术架构:
- 测试框架：Pytest + Allure + Selenium
- 页面元素：XPath 定位 + 显示等待机制
- 断言验证：结合文本验证和图片对比验证
- 报告生成：Allure 报告，包含截图和浏览器日志
- 测试依赖：使用@pytest.mark.dependency 管理用例执行顺序

===============================================================================
"""

import math
import time
from datetime import datetime

from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from utils.logger import logger
from src.Physical.WebBase.UIBase import UIBase, curr_date, root_path


# ======================================================================================================================
# 售后中心
# ======================================================================================================================
class AfterSales(UIBase):
    def __init__(self, driver):
        super().__init__(driver)
        sub_menu = {
            "txtArea": "(//textarea[@class='el-textarea__inner'])[%s]",
            "numberBox": "(//input[@class='el-input__inner' and @type='number'])[%s]",
            "selectorWidget1": "(//input[@class='el-select__input']/..)[%s]",
            "V4Item": "(//span[text()='V4无人机']/parent::li)[%s]",
            "operateCell1": "(//div[@class='operate-cell']/div/div/a)[%s]",
        }
        self.sub_menu.update(sub_menu)

    ########################################################################################################## 故障类型管理
    def search_fault_type(self, name):
        """
        故障类型管理 - 查询
        """
        try:
            self._click("工作台")
            self._click("售后中心")
            self._click("故障类型管理")
            self._input("txtWidget", name)
            self._click("selectorWidget")
            self._click("V4Item")
            self._click("searchButton")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def add_fault_type(self, name):
        """
        故障类型管理 - 新增
        """
        try:
            self._click("工作台")
            self._click("售后中心")
            self._click("故障类型管理")
            self._click("addButton")
            self._input("txtWidget", name, index=2)
            self._input("txtWidget", "test", index=3)
            self._click("selectorWidget1", index=2)
            self._click("V4Item", index=2)
            self._input("numberBox", "1", index=2)
            self._input("numberBox", "1", index=3)
            self._input("numberBox", "10", index=4)
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def add_fault_cause(self, name, cause):
        """
        故障类型管理 - 添加原因
        """
        try:
            self.search_fault_type(name)
            self._click("operateCell1")
            self._input("txtWidget", cause, index=3)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def edit_fault_type(self, name):
        """
        故障类型管理 - 编辑
        """
        try:
            self.search_fault_type(name)
            self._click("operateCell1", index=2)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def delete_fault_type(self, name):
        """
        故障类型管理 - 删除
        """
        try:
            self.search_fault_type(name)
            self._click("operateCell1", index=3)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ############################################################################################################# 维修管理
    def repair_manage_search(self, orderNo):
        """
        维修管理 - 查询
        """
        try:
            self._click("工作台")
            self._click("售后中心")
            self._click("维修管理")
            self._input("txtWidget", orderNo)
            self._click("searchButton")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def repair_manage_panel(self, orderNo):
        """
        维修管理 - 维修面板
        """
        try:
            self.repair_manage_search(orderNo)
            self._click("operateCell")
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ######################################################################################################### 故障现象管理
    def fault_case_search(self, caseName):
        """
        故障现象管理 - 查询
        """
        try:
            self._click("工作台")
            self._click("售后中心")
            self._click("故障现象管理")
            self._input("txtWidget", caseName, index=1)
            self._click("searchButton", index=1)
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def fault_case_add(self, caseName):
        """
        故障现象管理 - 新增
        """
        try:
            self._click("工作台")
            self._click("售后中心")
            self._click("故障现象管理")
            self._click("addButton")
            self._input("txtWidget", "99", index=2)
            self._input("txtArea", caseName)
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def fault_case_edit(self, caseName):
        """
        故障现象管理 - 编辑
        """
        try:
            self.fault_case_search(caseName)
            self._click("operateCell")
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def fault_case_delete(self, caseName):
        """
        故障现象管理 - 删除
        """
        try:
            self.fault_case_search(caseName)
            self._click("operateCell", index=2)
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ############################################################################################################# 维修订单
    def repair_order_search(self, orderNo):
        """
        维修订单 - 查询
        """
        try:
            self._click("工作台")
            self._click("售后中心")
            self._click("维修订单")
            self._input("txtWidget", orderNo)
            self._click("searchButton")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def repair_order_detail(self, orderNo):
        """
        维修订单 - 详情
        """
        try:
            self.repair_order_search(orderNo)
            self._click("operateCell1", index=3)
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False


# ======================================================================================================================
# 设备中心
# ======================================================================================================================
class DevicesCenter(UIBase):
    def __init__(self, driver):
        super().__init__(driver)
        sub_menu = {
            "selectorWidget1": "(//input[@class='el-select__input'])[%s]",
            "dmd": "(//span[text()='深圳大漠大智控技术有限公司']/parent::li)[%s]",
            "dmd1": "(//span[text()='深圳大漠大智控技术有限公司test-维修仓库']/parent::li)[%s]",
            "productPart": "(//span[text()='生产部']/parent::li)[%s]",
            "addButton1": "(//span[text()='新增设备']/..)[%s]",
            "V4": "(//span[text()='V4无人机'])[%s]",
            "txtWidget1": "(//input[@class='el-select__input'])[%s]",
            "item1": "(/html/body/div[4]/div[7]/div/div/div[1]/ul/li)[%s]",
            "item2": "(/html/body/div[4]/div[14]/div/div/div[1]/ul/li[1])[%s]",
            "OACheck": "(/html/body/div[4]/div[15]/div/div/div[1]/ul/li[1])[%s]",
            "check": "(//span[@class='el-checkbox__inner'])[%s]",
            "sendRepair": "(//span[text()='送修'])[%s]",
            "analysis": "(//span[text()='记录分析'])[%s]",
            "operateCell1": "(//div[@class='operate-cell']/div/div/a)[%s]",
            "L3": "(//span[text()='L3适配器']/parent::li)[%s]",
        }
        self.sub_menu.update(sub_menu)

    ############################################################################################################# 无人机管理
    def search_SN(self, SN):
        """
        无人机管理 - 查询
        """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("无人机管理")
            self._input("txtWidget", SN)
            self._click("selectorWidget1")
            self._click("dmd")
            self._click("selectorWidget1", index=2)
            self._click("productPart")
            self._click("searchButton")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def add_device(self, SN):
        """
        无人机管理 - 新增
        """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("无人机管理")
            self._click("addButton1")
            self._input("txtWidget", SN, index=7)
            self._click("selectorWidget", index=6)
            self._click("V4")
            self._click("selectorWidget1", index=8)
            self._click("dmd", index=2)
            self._click("selectorWidget1", index=9)
            self._click("productPart", index=2)
            self._input("txtWidget", "001", index=16)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
        return False

    def delete_device(self, SN):
        """
        无人机管理 - 删除
        """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("无人机管理")
            self._input("txtWidget", SN)
            self._click("searchButton")
            time.sleep(2)
            self._click("operateCell", index=2)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
        return False

    def import_device(self, file_path):
        """
        无人机管理 - 导入
        """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("无人机管理")
            self._import_file(file_path)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
        return False

    ############################################################################################################# 故障记录
    def add_fault_record(self, SN):
        """
        故障记录 - 新增
        """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("故障记录")
            self._click("addButton")
            self._input("txtWidget1", SN, index=4)  # 序列号
            time.sleep(1)
            self._click("item1")
            self._input("txtWidget1", "test", index=10)  # 故障描述
            time.sleep(1)
            self._click("item2")
            self._click("txtWidget1", index=12)  # 维修点
            time.sleep(1)
            self._click("dmd1", index=2)
            self._click("txtWidget1", 11)  # 故障处理状态
            time.sleep(1)
            self._click("OACheck")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def send_repair(self, SN):
        """
        故障记录 - 送修
        """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("故障记录")
            self._input("txtWidget", SN)
            self._click("searchButton")
            self._click("check", index=2)
            self._click("sendRepair")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def import_records(self, file_path):
        """
        故障记录 - 导入故障记录
        """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("故障记录")
            self._import_file(file_path)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ############################################################################################################# 维修记录
    def search_repare_record(self, SN):
        """
        维修记录 - 搜索
        """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("维修记录")
            self._input("txtWidget", SN)
            self._click("searchButton")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ############################################################################################################# 电池管理
    def search_battery(self, SN):
        """
        电池管理 - 记录搜索
        """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("电池管理")
            self._input("txtWidget", SN)
            self._click("searchButton")
            time.sleep(2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def record_analysis(self, SN, recordNo):
        """
        电池管理 - 记录分析
        """
        try:
            self.search_battery(SN)
            self._click("operateCell")
            self._input("txtWidget", recordNo, index=2)
            self._click("searchButton", index=2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}", exc_info=True)
            return False

    def edit_battery(self, SN):
        """
        电池管理 - 编辑
        """
        try:
            self.search_battery(SN)
            self._click("operateCell1")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def detail_battery(self, SN):
        """
        电池管理 - 详情
        """
        try:
            self.search_battery(SN)

            self._click("operateCell1", index=2)
            time.sleep(1)
            return True
        except Exception as e:
            return False

    ############################################################################################################# 表演记录
    def search_records(self, recordNo):
        """
        表演记录 - 查询
        """

        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("表演记录")
            self._input("txtWidget", recordNo)
            self._click("searchButton")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def detail_record(self, recordNo):
        """
        表演记录 - 详情
        """
        try:
            self.search_records(recordNo)
            self._click("operateCell")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ############################################################################################################# 飞行记录
    def search_device(self, SN):
        """
        飞行记录记录 - 搜索
        """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("飞行记录")
            self._input("txtWidget", SN)
            self._click("searchButton")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def detail_flight(self, SN):
        """
        飞行记录记录 - 详情
        """
        try:
            self.search_device(SN)
            self._click("operateCell")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ########################################################################################################## 辅助设备管理
    def assist_equipment_search(self, SN):
        """
       辅助设备 - 搜索
       """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("辅助设备")
            self._input("txtWidget", SN)
            self._click("searchButton")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def assist_equipment_add(self, SN):
        """
       辅助设备 - 新增
       """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("辅助设备")
            self._click("addButton")
            self._input("txtWidget", SN, index=3)
            self._click("selectorWidget1", index=5)
            self._click("L3", index=2)
            self._click("selectorWidget1", index=7)
            self._click("dmd", index=2)
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def assist_equipment_edit(self, SN):
        """
       辅助设备 - 编辑
       """
        try:
            self.assist_equipment_search(SN)
            self._click("operateCell1", index=2)
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def assist_equipment_delete(self, SN):
        """
       辅助设备 - 删除
       """
        try:
            self.assist_equipment_search(SN)
            self._click("operateCell1", index=3)
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False


# ======================================================================================================================
# 地控中心
# ======================================================================================================================
class GroundControl(UIBase):
    def __init__(self, driver):
        super().__init__(driver)
        sub_menu = {
            "numberBox": "(//input[@class='el-input__inner' and @type='number'])[%s]",
            "authUser": "(//span[text()='授权用户'])[%s]",
            "usrAccount": "(//span[text()='请输入用户账号']/..)[%s]",
            "user": "(//input[@placeholder='用户账号'])[%s]",
            "choseBox": "(//span[@class='el-checkbox__inner']/parent::span[@class='el-checkbox__input'])[%s]",
            "activationRecord": "((//div[@class='cell el-tooltip'])[15]//span)[%s]",
            "addFile": "(//span[text()='新增文件']/..)[%s]",
            "more": "(//div[@class='dropdown-container'])[%s]",
            "operateCell1": "(//div[@class='operate-cell']/div/div/a)[%s]",
            "delete": "(//li[@label='删除'])[%s]",
            "using": "(//span[@class='el-radio__inner'])[%s]",
            "productionItem": "(//span[text()='请选择']/..)[%s]",
            "proItme": "(//li[@class='el-select-dropdown__item'])[%s]",
            "groupParam": "(//div[text()='组合参数'])[%s]",
            "edit1": "(//li[@label='编辑'])[%s]",
            "selectorBar": "(//input[@class='el-select__input'])[%s]",
            "shape": "(//span[text()='圆']/parent::li)[%s]",
            "shape1": "(//span[text()='圆']/parent::button)[%s]",
            "able": "(//span[text()='已授权']/parent::li)[%s]",
            "enable": "(//span[text()='未授权']/parent::li)[%s]",
            "authorizeStatus": "(//div[@class='el-switch__action'])[%s]",
            "save": "(//span[text()='保存'])[%s]",
            "mapControl": "(//button[@title='地图镜头控件'])[%s]",
            "zoomIn": "(//button[@title='放大'])[%s]",
        }
        self.sub_menu.update(sub_menu)

    ########################################################################################################### 地面站管理
    def search_ground_station(self, name):
        """
        地面站管理 - 查询
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("地面站管理")
            self._input("txtWidget", name)
            self._click("searchButton")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def add_ground_station(self, name):
        """
        地面站管理 - 新增
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("地面站管理")
            self._click("addButton")
            self._input("txtWidget", name, index=2)
            self._input("txtWidget", 'test', index=3)
            self._input("numberBox", '99', index=1)
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def authorized_user(self, name):
        """
        地面站管理 - 授权用户
        """
        try:
            self.search_ground_station(name)
            self._click("operateCell", index=2)
            self._click("addButton", index=2)
            self._click("usrAccount")
            self._click("user")
            self._input("user", 'alan1')
            self._click("searchButton", index=3)
            self._click("choseBox", index=4)
            self._click("confirm", index=3)
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def activation_record(self, name):
        """
        地面站管理 - 激活记录
        """
        try:
            self.search_ground_station(name)
            self._click("operateCell", index=2)
            self._click("activationRecord")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def edition_file(self, name, file_path):
        """
        地面站管理 - 版本文件
        """
        try:
            self.search_ground_station(name)
            self._click("operateCell", index=3)
            self._click("addFile")
            self._import_file(file_path)
            self.wait.until(EC.visibility_of_element_located((By.XPATH, "//p[@class='el-message__content']")))
            time.sleep(1)
            self._input("txtWidget", "1.0", index=3)
            self._click("confirm", index=2)
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def delete_ground_station(self, name):
        """
        地面站管理 - 删除地面站
        """
        try:
            self.search_ground_station(name)
            self._click("more")
            self._click("delete")
            self._click("confirm", index=2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ########################################################################################################### 剧本编辑器
    def add_player_editor(self, name):
        """
        剧本编辑器管理 - 新增
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("剧本编辑器管理")
            self._click("addButton")
            self._input("txtWidget", 'test', index=2)
            self._input("txtWidget", 'test', index=3)
            self._input("numberBox", '99')
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def search_player_editor(self, name):
        """
        剧本编辑器管理 - 搜索
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("剧本编辑器管理")
            self._input("txtWidget", name)
            self._click("searchButton")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def author_user(self, name):
        """
        剧本编辑器管理 - 授权用户
        """
        try:
            self.search_player_editor(name)
            self._click("operateCell", index=2)
            self._click("addButton", index=2)
            self._click("usrAccount")
            self._click("user")
            self._input("user", 'alan1')
            self._click("searchButton", index=3)
            self._click("choseBox", index=4)
            self._click("confirm", index=4)
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def delete_player_editor(self, name):
        """
        剧本编辑器管理 - 删除
        """
        try:
            self.search_player_editor(name)
            self._click("more")
            self._click("delete")
            self._click("confirm", index=3)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def version_file(self, name, file_path):
        """
        剧本编辑器管理 - 版本文件
        """
        try:
            self.search_player_editor(name)
            self._click("operateCell", index=3)
            self._click("addFile")
            self._import_file(file_path)
            self.wait.until(EC.visibility_of_element_located((By.XPATH, "//p[@class='el-message__content']")))
            time.sleep(1)
            self._input("txtWidget", "1.0", index=3)
            self._click("confirm", index=2)
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ######################################################################################################## 无人机组件管理
    def UAVComponents_search(self, name):
        """
        无人机组件管理 - 查询
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("无人机组件管理")
            self._input("txtWidget", name)
            self._click("searchButton")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def components_colors(self, name):
        """
        无人机组件管理 - 组件颜色表
        """
        try:
            self.UAVComponents_search(name)
            self._click("operateCell", index=2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def components_add(self, name):
        """
        无人机组件管理 - 新增组件
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("无人机组件管理")
            self._click('addButton')
            self._input("txtWidget", name, index=2)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def components_version(self, name, file_path):
        """
        无人机组件管理 - 组件版本
        """
        try:
            self.UAVComponents_search(name)
            self._click("operateCell")
            self._click("addFile")
            self._import_file(file_path)
            self.wait.until(EC.visibility_of_element_located((By.XPATH, "//p[@class='el-message__content']")))
            time.sleep(3)
            self._input("txtWidget", "1.0", index=3)
            self._click("confirm", index=2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def components_delete(self, name):
        """
        无人机组件管理 - 删除组件
        """
        try:
            self.UAVComponents_search(name)
            self._click("more")
            time.sleep(1)
            self._click("delete")
            time.sleep(1)
            self._click("confirm", index=2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ######################################################################################################## 无人机类型管理
    def uavType_search(self, name, typeValue):
        """
        无人机类型管理 - 查询
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("无人机类型管理")
            self._input("txtWidget", name)
            self._input("txtWidget", typeValue, index=2)
            self._click("searchButton")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def uavType_add(self, name, typeValue):
        """
        无人机类型管理 - 复制新增
        """
        try:
            self.uavType_search(name, typeValue)
            self._click("operateCell1", index=2)
            self._input("txtWidget", "test", index=3)
            self._input("numberBox", "999")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def uavType_delete(self, name, typeValue):
        """
        无人机类型管理 - 删除
        """
        try:
            self.uavType_search(name, typeValue)
            self._click("operateCell1", index=4)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ######################################################################################################### 差分账号管理
    def differenceAcct_search(self, account):
        """
        差分账号管理 - 查询
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("差分账号管理")
            self._input("txtWidget", account)
            self._click("searchButton")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def differenceAcct_add(self, account):
        """
        差分账号管理 - 新增
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("差分账号管理")
            self._click("addButton")
            self._input("txtWidget", account, index=2)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def differenceAcct_edit(self, account):
        """
        差分账号管理 - 编辑
        """
        try:
            self.differenceAcct_search(account)
            self._click("operateCell1")
            self._click("using", index=2)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def differenceAcct_delete(self, account):
        """
        差分账号管理 - 删除
        """
        try:
            self.differenceAcct_search(account)
            self._click("operateCell1", index=3)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ######################################################################################################### 电台类型管理
    def radio_search(self, radioType):
        """
        电台类型管理 - 查询
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("电台类型管理")
            self._input("txtWidget", radioType)
            self._click("searchButton")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def radio_add(self, radioType):
        """
        电台类型管理 - 新增
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("电台类型管理")
            self._click("addButton")
            self._input("txtWidget", radioType, index=3)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def radio_edit(self, radioType):
        """
        电台类型管理 - 编辑
        """
        try:
            self.radio_search(radioType)
            self._click("operateCell1")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def radio_delete(self, radioType):
        """
        电台类型管理 - 删除
        """
        try:
            self.radio_search(radioType)
            self._click("operateCell1", index=3)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ######################################################################################################### 组合版本管理
    def version_group_add(self):
        """
        组合版本管理 - 新增
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("组合版本管理")
            self._click("addButton")
            self._input("txtWidget", 'test', index=3)
            self._input("txtWidget", '1', index=4)
            self._click("addButton", index=3)
            self._click("addButton", index=3)
            self._click("productionItem")
            self._click("proItme", index=6)
            self._click("productionItem")
            self._click("proItme", index=24)
            self._input("txtWidget", 'test', index=6)
            self._input("txtWidget", 'test', index=7)
            self._input("txtWidget", 'test', index=9)
            self._input("txtWidget", 'test', index=10)
            self._click("groupParam")
            self._click("addButton", index=4)
            self._input("txtWidget", '1', index=12)
            self._input("txtWidget", '1', index=13)
            self._input("txtWidget", '1', index=14)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def version_group_edit(self):
        """
        组合版本管理 - 编辑
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("组合版本管理")
            self._click("operateCell1")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def version_group_delete(self):
        """
        组合版本管理 - 删除
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("组合版本管理")
            self._click("operateCell1", index=3)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ######################################################################################################### 产品版本管理
    def production_version_search(self, production_name):
        """
        产品版本管理 - 查询
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("产品版本管理")
            self._input("txtWidget", production_name)
            self._click("searchButton")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def production_version_add(self, production_name):
        """
        产品版本管理 - 新增
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("产品版本管理")
            self._click("addButton")
            self._input("txtWidget", "test", index=3)
            self._input("txtWidget", "test", index=4)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def production_version_user(self, production_name):
        """
        产品版本管理 - 授权用户
        """
        try:
            self.production_version_search(production_name)
            self._click("operateCell", index=2)
            self._click("addButton", index=2)
            self._click("usrAccount")
            self._click("user")
            self._input("user", 'alan1')
            self._click("searchButton", index=3)
            self._click("choseBox", index=7)
            self._click("confirm", index=3)
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def production_version_addfile(self, production_name, file_path):
        """
        产品版本管理 - 上传文件
        """
        try:
            self.production_version_search(production_name)
            self._click("operateCell", index=3)
            self._click("addButton", index=2)
            self._import_file(file_path)
            self.wait.until(EC.visibility_of_element_located((By.XPATH, "//p[@class='el-message__content']")))
            time.sleep(3)
            self._input("txtWidget", "1.0", index=4)
            self._click("confirm", index=2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def production_version_edit(self, production_name):
        """
        产品版本管理 - 编辑
        """
        try:
            self.production_version_search(production_name)
            self._click("more")
            self._click("edit1")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def production_version_delete(self, production_name):
        """
        产品版本管理 - 删除
        """
        try:
            self.production_version_search(production_name)
            self._click("more")
            self._click("delete")
            self._click("confirm", index=2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ######################################################################################################### 飞控参数管理
    def flight_parameters_add(self, param_name):
        """
        飞控参数管理 - 新增
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("飞控参数管理")
            self._click("addButton", index=1)
            self._input("txtWidget", param_name, index=3)
            self._input("txtWidget", '1', index=4)
            self._input("txtWidget", '0', index=5)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def flight_parameters_search(self, param_name):
        """
        飞控参数管理 - 搜索
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._click("飞控参数管理")
            self._input("txtWidget", param_name)
            self._click("searchButton")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def flight_parameters_edit(self, param_name):
        """
        飞控参数管理 - 编辑
        """
        try:
            self.flight_parameters_search(param_name)
            self._click("operateCell1")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def flight_parameters_delete(self, param_name):
        """
        飞控参数管理 - 删除
        """
        try:
            self.flight_parameters_search(param_name)
            self._click("operateCell1", index=3)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ######################################################################################################### 飞行区域管理
    def flight_area_add(self, area_name):
        """
        飞行区域管理 - 新增
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._scrolltoView("飞行区域管理")
            time.sleep(1)
            self._click("飞行区域管理")
            self._click("addButton")
            self._input("txtWidget", area_name, index=2)
            self._input("txtWidget", 'test', index=3)
            self._input("numberBox", '114', index=2)
            self._input("numberBox", '22', index=3)
            self._input("numberBox", '200', index=4)
            self._click("selectorBar", index=5)
            self._click("shape", index=2)

            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def flight_area_search(self, area_name, enable):
        """
        飞行区域管理 - 搜索
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._scrolltoView("飞行区域管理")
            time.sleep(1)
            self._click("飞行区域管理")

            self._input("txtWidget", area_name)
            self._click("selectorBar")
            self._click(enable)
            self._click("selectorBar", index=2)
            self._click("shape")
            self._click("searchButton")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def flight_area_authorize(self, area_name):
        """
        飞行区域管理 - 授权
        """
        try:
            self.flight_area_search(area_name, "enable")

            self._click("operateCell")
            self._click("authorizeStatus", index=2)
            self._click("save", index=1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def flight_area_edit(self, area_name):
        """
        飞行区域管理 - 编辑
        """
        try:
            self.flight_area_search(area_name, "able")

            self._click("more")
            self._click("edit1")
            self._click("authorizeStatus", index=2)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def flight_area_delete(self, area_name):
        """
        飞行区域管理 - 删除
        """
        try:
            self.flight_area_search(area_name, "enable")

            self._click("more")
            self._click("delete")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ######################################################################################################### 飞行区域 GIS
    def area_GIS_add(self, area_name):
        """
        飞行区域 GIS-新增
        """
        try:
            self._click("工作台")
            self._click("地控中心")
            self._scrolltoView("飞行区域GIS")
            time.sleep(1)
            self._click("飞行区域GIS")
            self._click("mapControl")
            map = self.driver.find_element(By.XPATH, "//div[@aria-label='地图']")

            for i in range(3):
                time.sleep(1.5)
                self._click("zoomIn")

            self._click("shape1")
            act = ActionChains(self.driver)
            act.move_to_element_with_offset(map, 100, 100)
            time.sleep(1.5)
            act.click_and_hold()

            for i in range(3):
                angle = 2 * math.pi * i / 10
                x = 5 * math.cos(angle)
                y = 5 * math.sin(angle)
                act.move_by_offset(x, y)

            act.release().perform()
            self.wait.until(EC.presence_of_element_located((By.XPATH, "//div[@class='el-switch is-checked']")))
            self._input("txtWidget", area_name, index=3)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False


# ======================================================================================================================
# 生产中心
# ======================================================================================================================
class ProductionCenter(UIBase):
    def __init__(self, driver):
        super().__init__(driver)
        sub_menu = {
            "selectorWidget1": "(//input[@class='el-select__input'])[%s]",
            "expand": "(//*[text()='展开'])[%s]",
            "damoda": "(//span[text()='深圳大漠大智控技术有限公司']/parent::li)[%s]",
            "button": "(//button[@class='el-button el-button--primary'])[%s]",
            "txtArea": "(//textarea[@placeholder='请输入无人机序列号'])[%s]",
            "V4": "(//span[text()='V4无人机']/..)[%s]",
            "productPart": "(//span[text()='生产部']/parent::li[@role='option'])[%s]",
            "more": "(//div[@class='dropdown-container'])[%s]",
            "changeHistory": "(//span[text()='变更记录'])[%s]",
            "detail": "(//span[text()='详情'])[%s]",
            "editOrder": "(//span[text()='编辑'])[%s]",
            "cancelOrder": "(//span[text()='撤销']/parent::li)[%s]",
            "deleteOrder": "(//span[text()='删除']/parent::li)[%s]",
            "operateCell1": "(//div[@class='operate-cell']/div/div/a)[%s]",
            "uav": "(//span[text()='无人机']/parent::li)[%s]",
        }
        self.sub_menu.update(sub_menu)

    ############################################################################################################ 库存管理
    def search_devices(self, SN):
        """
        库存管理 - 查询
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("库存管理", index=2)
            time.sleep(1)
            self._click("expand")
            self._click("selectorWidget1")
            self._click("damoda")
            self._input("txtWidget", SN)
            self._click("searchButton")
            time.sleep(2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def batching_storage(self, SN):
        """
        库存管理 - 批量入库
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("库存管理", index=2)
            self._click("button", index=2)
            self._input("txtArea", SN)
            self._click("selectorWidget", index=4)
            self._click("V4", index=2)
            self._input("txtWidget", '001', index=7)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def batching_outbound(self, SN):
        """
        库存管理 - 批量出库
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("库存管理", index=2)
            self._click("button", index=3)
            self._input("txtArea", SN)
            self._input("txtWidget", '001', index=7)
            self._click("selectorWidget1", index=4)
            self._click("damoda", index=2)
            self._click("selectorWidget1", index=5)
            self._click("productPart")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def export_device(self, SN):
        """
        库存管理 - 导出
        """
        try:
            self.search_devices(SN)
            self._click("button", index=5)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def import_device(self, file_path):
        """
        库存管理 - 导入
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("库存管理", index=2)
            self._import_file(file_path)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def delete_device(self, SN):
        """
        库存管理 - 删除设备
        """
        try:
            self.search_devices(SN)
            self._click("operateCell", index=2)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def change_history(self, SN):
        """
        库存管理 - 变更记录
        """
        try:
            self.search_devices(SN)
            self._click("more")
            self._click("changeHistory")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def edit_device(self, SN):
        """
        库存管理 - 编辑
        """
        try:
            self.search_devices(SN)
            self._click("operateCell", index=1)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ############################################################################################################ 销售出库
    def syncOA(self):
        """
        销售出库-OA 同步
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("销售出库")
            self._click("button", index=2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def outbound_device(self):
        """
        销售出库 - 出库飞机
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("销售出库")
            self._click("operateCell")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def device_bill(self):
        """
        销售出库 - 设备清单
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("销售出库")
            self._click("operateCell", index=2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def order_detail(self):
        """
        销售出库 - 订单详情
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("销售出库")
            self._click("more")
            self._click("detail")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def order_edit(self):
        """
        销售出库 - 订单编辑
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("销售出库")
            self._click("more")
            self._click("editOrder")
            self._click("selectorWidget1", index=2)
            self._click("damoda", index=2)
            self._click("selectorWidget1", index=3)
            self._click("productPart")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def cancel_order(self):
        """
        销售出库 - 订单编辑
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("销售出库")
            self._click("more")
            self._click("cancelOrder")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def delete_order(self):
        """
        销售出库 - 订单编辑
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("销售出库")
            self._click("more")
            self._click("deleteOrder")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ############################################################################################################ 设备类型
    def search_Model(self, typeName, productModle):
        """
        设备类型 - 查询
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("设备类型")
            self._input("txtWidget", typeName)
            self._input("txtWidget", productModle, index=2)
            self._click("searchButton")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def add_type(self, typeName, typeValue):
        """
        设备类型 - 新增
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("设备类型")
            self._click("addButton")
            self._click("selectorWidget1")
            self._click("uav")
            self._input('txtWidget', typeName, index=4)
            self._input("txtWidget", typeValue, index=5)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def edit_device_type(self, typeName):
        """
        设备类型 - 编辑
        """
        try:
            self.search_Model(typeName, '')
            self._click("operateCell1")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def device_type_detail(self, typeName):
        """
        设备类型 - 详情
        """
        try:
            self.search_Model(typeName, '')
            self._click("operateCell1", index=2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def device_type_delete(self, typeName):
        """
        设备类型 - 删除
        """
        try:
            self.search_Model(typeName, '')
            self._click("operateCell1", index=3)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    #################################################################################################################### 编码规则
    def sear_code_rule(self, header, value, proFlag):
        """
        编码规则 - 搜索
        """
        try:
            self._click("工作台")
            self._click("生产中心")
            self._click("编码规则")
            self._input("txtWidget", header)
            self._input("txtWidget", value, index=2)
            self._input("txtWidget", proFlag, index=3)
            self._click("searchButton")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def detail_code_rule(self, Header):
        """
        编码规则 - 详情
        """
        try:
            self.sear_code_rule(Header, '', '')
            self._click("operateCell", index=2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def edit_code_rule(self, header):
        """
        编码规则 - 编辑
        """
        try:
            self.sear_code_rule(header, '', '')
            self._click("operateCell")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False


# ======================================================================================================================
# 服务中心
# ======================================================================================================================
class ServiceCenter(UIBase):
    def __init__(self, driver):
        super().__init__(driver)
        sub_menu = {
            "tab": "(//span[@class='custom-tabs-label'])[%s]",
            "order": "(//span[text()='下单']/..)[%s]",
            "date": "(//input[@class='el-range-input'])[%s]",
            "today": "(//td[@class='available today'])[%s]",
            "selectorWidget1": "(//input[@class='el-select__input'])[%s]",
            "warehouse": "(//span[text()='生产部']/parent::li)[%s]",
            "addQRCode": "(//span[text()='新增二维码']/..)[%s]",
            "projectName": "(//span[text()='auto_ test_project']/parent::li)[%s]",
            "currTime": "(//span[text()='此刻']/..)[%s]",
            "inProgress": "(//span[text()='进行中']/parent::li)[%s]",
            "audioTime": "(//span[@data-v-8a155593])[%s]"

        }
        self.sub_menu.update(sub_menu)

    ########################################################################################################## 飞行项目管理
    def search_project(self, project_name):
        """
        飞行项目管理 - 查询
        """
        try:
            self._click("工作台")
            self._click("服务项目中心")
            self._click("飞行项目管理")
            self._input("txtWidget", project_name)
            self._click("searchButton")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def edit_project(self, project_name):
        """
        飞行项目管理 - 编辑
        """
        try:
            self.search_project(project_name)
            self._click("operateCell", index=3)
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def detail_project(self, project_name):
        """
        飞行项目管理 - 详情
        """
        try:
            self.search_project(project_name)
            self._click("operateCell", index=4)
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def add_self_order(self, project_name):
        """
        飞行项目管理 - 新增自用订单
        """
        try:
            self.detail_project(project_name)
            self._click("tab", index=2)
            self._click("order")
            self._click("date")
            self._double_click("today")
            self._click("selectorWidget1", index=3)
            self._click("warehouse")
            self._click("selectorWidget1", index=4)
            self._click("warehouse", index=2)
            self._input("txtWidget", "test", index=2)
            self._input("txtWidget", "15111111111", index=3)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def edit_self_order(self, project_name):
        """
        飞行项目管理 - 编辑自用订单
        """
        try:
            self.detail_project(project_name)
            self._click("tab", index=2)
            self._click("operateCell", index=6)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def cancel_self_order(self, project_name):
        """
        飞行项目管理 - 取消自用订单
        """
        try:
            self.detail_project(project_name)
            self._click("tab", index=2)
            self._click("operateCell", index=5)
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ######################################################################################################## 表演二维码管理
    def add_QRCode(self, audio_file):
        """
        表演二维码管理 - 新增二维码
        """
        try:
            self._click("工作台")
            self._click("服务项目中心")
            self._click("表演二维码管理")
            self._click("addQRCode")
            self._input("txtWidget", f"test{curr_date}", index=2)
            self._click("selectorWidget1", index=2)
            self._click("projectName")
            self._click("txtWidget", index=3)
            self._click("currTime")
            self._import_file(audio_file)
            for _ in range(20):
                duration = self._get_value("audioTime")
                if duration is not None:
                    break
                else:
                    time.sleep(0.5)
                    continue
            else:
                return False
            self._click("confirm")
            time.sleep(2)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def search_QRCode(self):
        """
        表演二维码管理 - 搜索二维码
        """
        try:
            self._click("工作台")
            self._click("服务项目中心")
            self._click("表演二维码管理")
            self._input("txtWidget", f"test{curr_date}")
            self._click("selectorWidget1")
            self._click("inProgress")
            self._click("searchButton")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False
# ======================================================================================================================
# 评级管理
# ======================================================================================================================
class RatingManagement(UIBase):
    def __init__(self, driver):
        super().__init__(driver)
        sub_menu = {
            "selectorWidget1": "(//input[@class='el-select__input'])[%s]",
            "flyer": "(//li[@class='el-select-dropdown__item']/span[text()='飞行工程师'])[%s]",
            "icon": "(//label[@class='image-radio-item'])[%s]",
            "textarea": "(//textarea[@class='el-textarea__inner'])[%s]",
            "save": "(//span[text()='保存']/..)[%s]",
            "failure": "(//span[text()='失效'])[%s]",
            "delete": "(//span[text()='删除'])[%s]",
            "flyEnginner": "(//div[text()='飞行工程师'])[%s]",
            "users": "(//span[text()='请选择'])[%s]",
            "checkBox": "(//span[@class='el-checkbox__inner'])[%s]",
            "test": "(//span[text()='test']/..)[%s]",
            "time":"(//input[@class='el-range-input'])[%s]",
            "today":"(//td[@class='available today'])[%s]",
            "check":"(//span[text()='确定']/..)[%s]",
            "edit":"(//span[text()='编辑'])[%s]",

        }
        self.sub_menu.update(sub_menu)

    ######################################################################################################## 等级管理
    def add_rating_level(self, name):
        """
        等级管理 - 新增等级
        """
        try:
            self._click("工作台")
            self._scrolltoView("评级管理")
            time.sleep(1)
            self._click("评级管理")
            self._click("等级管理")
            self._click("addButton")
            self._input("txtWidget", name, index=2)
            self._click("selectorWidget1", index=2)
            self._click("flyer", index=2)
            self._click("icon", index=3)
            self._input("textarea", "test", index=1)
            self._click("save")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def search_rating_level(self, name):
        """
        等级管理 - 查询
        """
        try:
            self._click("工作台")
            self._scrolltoView("评级管理")
            time.sleep(1)
            self._click("评级管理")
            self._click("等级管理")
            self._input("txtWidget", name)
            self._click("searchButton")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def failure_rating_level(self, name):
        """
        等级管理 - 失效
        """
        try:
            self.search_rating_level(name)
            self._click("failure")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def edit_rating_level(self, name):
        """
        等级管理 - 编辑
        """
        try:
            self.search_rating_level(name)
            self._click("edit")
            self._click("save")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def delete_rating_level(self, name):
        """
        等级管理 - 删除
        """
        try:
            self.search_rating_level(name)
            self._click("delete")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ######################################################################################################## 人员管理
    def add_rating_user(self, name):
        """
        人员管理 - 新增
        """
        try:
            self._click("工作台")
            self._scrolltoView("评级管理")
            time.sleep(1)
            self._click("评级管理")
            self._click("人员管理")
            self._click("flyEnginner")
            self._click("addButton")
            self._click("users")
            self._click("txtWidget", index=6)
            self._input("txtWidget", name, index=6)
            self._click("searchButton", index=2)
            self._click("checkBox", index=12)
            self._click("confirm")
            self._click("selectorWidget1", index=3)
            self._click("test", index=2)
            self._click("time")
            self._double_click("today")
            self._click("check")
            self._click("save")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def search_rating_user(self, name):
        """
        人员管理 - 搜索
        """
        try:
            self._click("工作台")
            self._scrolltoView("评级管理")
            time.sleep(1)
            self._click("评级管理")
            self._click("人员管理")
            self._click("flyEnginner")
            self._input("txtWidget", name)
            self._click("searchButton")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def edit_rating_user(self, name):
        """
        人员管理 - 编辑
        """
        try:
            self.search_rating_user(name)
            self._click("edit")
            self._click("save")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def delete_rating_user(self, name):
        """
        人员管理 - 删除
        """
        try:
            self.search_rating_user(name)
            self._click("delete")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

