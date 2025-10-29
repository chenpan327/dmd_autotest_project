import time
from datetime import datetime

from web.UI_base import UIBase
from selenium.webdriver.support.ui import WebDriverWait
from web.UI_base import logger
from selenium.webdriver.common.by import By


class DevicesCenter(UIBase):
    def __init__(self, test_user, test_password, debug=True):
        super().__init__(test_user, test_password, debug=debug)
        sub_menu = {
            "SN": "//input[@placeholder='请输入序列号']",
            "group": "(//input[@class='el-select__input'])[%s]",
            "dmd": "(//span[text()='深圳大漠大智控技术有限公司']/..)[%s]",
            "warehouse": "(//input[@class='el-select__input'])[%s]",
            "productPart": "(//span[text()='生产部'])[%s]",
            "SNSearch": "//span[text()='查询']",
            "add": "(//button[@class='el-button el-button--primary'])[2]",
            "deviceNo": "//input[@placeholder='请输入无人机序列号']",
            "deviceType": "//span[text()='请选择设备类型']",
            "V4": "//span[text()='V4无人机']",
            "number": "(//input[@placeholder='请输入编号'])[2]",
            "confirm": "//span[text()='确定']/parent::button[@class='el-button el-button--primary']",
            "delete": "//span[text()='删除']",
            "submit": "//span[text()='确定']/..",
            ################################################################ 故障记录 #############################################################################################
            "item1": "/html/body/div[2]/div[6]/div/div/div[1]/ul/li",
            "item2": "/html/body/div[2]/div[13]/div/div/div[1]/ul/li",
            "faultDESC": "//span[text()='请选择故障描述']/../preceding-sibling::div/input",
            "fixAddress": "(//span[text()='请选择维修点'])[2]/../..",
            "faultStatu": "//span[text()='请选择设备状态']/../..",
            "OACheck": "/html/body/div[2]/div[14]/div/div/div[1]/ul/li[1]",
            "check": "//span[@class='el-checkbox__inner']",
            "sendRepair": "//span[text()='送修']",
            ################################################################ 电池管理 #############################################################################################
            "batterySN": "(//input[@class='el-input__inner'])[1]",
            "analysis": "//span[text()='记录分析']",
            "recordNo": "//input[@placeholder='请输入记录编号']",
            "search": "(//span[text()='查询'])[2]",
            "edit": "//span[text()='编辑']",
            "detail": "//span[text()='详情']",
            "more": "(//div[@class='el-dropdown'])[3]",
            "detail1": "(//li[@label='详情'])[1]",
            "txtWidgets": "(//input[@class='el-input__inner'])[%s]",
            "L3": "(//span[text()='L3适配器']/..)[%s]",
        }
        self.sub_menu.update(sub_menu)

    ############################################################################################################# 无人机管理
    def search_SN(self, SN):
        """
        无人机管理-搜索
        """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("无人机管理")
            self._input("SN", SN)
            self._click("group", index=1)
            self._click("dmd", index=1)
            self._click("warehouse", index=2)
            self._click("productPart", index=1)
            self._click("SNSearch")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def add_device(self, SN):
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("无人机管理")
            self._click("add")
            self._input("deviceNo", SN)
            self._click("deviceType")
            self._click("V4")
            self._click("group", index=6)
            self._click("dmd", index=2)
            self._click("warehouse", index=7)
            self._click("productPart", index=2)
            self._input("number", "001")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
        return False

    def import_file(self, file_path):
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("无人机管理")
            self._import_file(file_path)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def delete_device(self, SN):

        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("无人机管理")
            self._input("SN", SN)
            self._click("SNSearch")
            time.sleep(2)
            self._click("delete")
            self._click("submit")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
        return False

    ############################################################################################################# 故障记录
    def add_fault_record(self, SN):
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("故障记录")
            self._click("add")
            self._input("warehouse", SN, index=3)
            time.sleep(1)
            self._click("item1")
            self._input("faultDESC", "test")
            time.sleep(1)
            self._click("item2")
            self._click("fixAddress")
            time.sleep(1)
            self._click("dmd", index=4)  # (//span[text()='深圳大漠大智控技术有限公司'])[3]
            self._click("faultStatu")
            time.sleep(1)
            self._click("OACheck")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def send_repair(self, SN):

        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("故障记录")
            self._input("SN", SN)
            self._click("SNSearch")
            self._click("check")
            self._click("sendRepair")
            self._click("confirm")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def import_record(self, file_path):

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

        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("维修记录")
            self._input("SN", SN)
            self._click("SNSearch")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ############################################################################################################# 电池管理
    def search_battery(self, SN):
        """
        电池管理-记录搜索
        """

        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("电池管理")
            self._input("batterySN", SN)
            self._click("SNSearch")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def record_analysis(self, SN, recordNo):
        """
        电池管理-记录分析
        """
        try:
            self.search_battery(SN)
            self._click("analysis")
            self._input("recordNo", recordNo)
            self._click("search")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def edit_battery(self, SN):
        """
        电池管理-编辑
        """

        try:
            # self.refresh()
            self.search_battery(SN)
            self._click("edit")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def detail_battery(self, SN):
        """
        电池管理-详情
        """
        try:
            # self.refresh()
            self.search_battery(SN)
            self._click("detail")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ############################################################################################################# 表演记录
    def search_records(self, recordNo):
        """
        表演记录-查询
        """

        try:
            # self.refresh()
            self._click("工作台")
            self._click("设备中心")
            self._click("表演记录")
            self._input("batterySN", recordNo)
            self._click("SNSearch")
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def detail_record(self, recordNo):
        """
        表演记录-详情
        """

        try:
            # self.refresh()
            self.search_records(recordNo)
            self._click("more")
            self._click("detail1")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ############################################################################################################# 飞行记录
    def search_device(self, SN):
        """
        飞行记录记录-搜索
        """
        try:

            self._click("工作台")
            self._click("设备中心")
            self._click("飞行记录")
            self._input("batterySN", SN)
            self._click("SNSearch")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def detail_flight(self, SN):
        """
        飞行记录记录-详情
        """
        try:
            self.search_device(SN)
            self._click("detail")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    ########################################################################################################## 辅助设备管理
    def assist_equipment_search(self, SN):
        """
       辅助设备-搜索
       """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("辅助设备")
            self._input("batterySN", SN)
            self._click("SNSearch")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def assist_equipment_add(self, SN):
        """
       辅助设备-新增
       """
        try:
            self._click("工作台")
            self._click("设备中心")
            self._click("辅助设备")
            self._click("add")
            self._input("txtWidgets", SN, index=3)
            self._click("warehouse", index=5)
            self._click("L3", index=2)
            self._click("warehouse", index=7)
            self._click("dmd", index=2)
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def assist_equipment_edit(self, SN):
        """
       辅助设备-编辑
       """
        try:
            self.assist_equipment_search(SN)
            self._click("edit")
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False

    def assist_equipment_delete(self, SN):
        """
       辅助设备-删除
       """
        try:
            self.assist_equipment_search(SN)
            self._click("delete")
            self._click("confirm")
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"{e.__repr__()}")
            return False


if __name__ == '__main__':
    ob = DevicesCenter("alan", "dmd@2025")
    ob.login()

    ob.assist_equipment_add("CL34S56P0001")
    time.sleep(3)
