# -*- coding: utf-8 -*-

import time

import allure
from numpy.core.multiarray import result_type

from utils.logger import log_manager
import uiautomation as auto
from src.Physical.Dgcs.Dgcs_Base import DgCSUi, root_path


class DGCS(DgCSUi):
    def __init__(self):
        super().__init__()
        self.user_info = {}

    """
    ===============================================================================
    业务流程
    ===============================================================================
    """

    def login(self, usr, pwd):
        """
        功能:地面站登录方法，根据用户名与密码判断用户是否授权，以及是否授权到期，并返回提示信息
        参数：
            usr(sting):用户账号
            pwd(string):账号密码
        返回：
        string:登录提示窗口的文本信息
        """
        login_window = self._get_login_window()

        self.input_text('Login_Username_ComboBox', usr, control_instance=login_window)
        self.input_text('PART_PasswordBox', pwd, control_instance=login_window)
        self.click("Login_Submit_Button", control_instance=login_window, wait_loading=True)

        try:
            re = self._handle_warning()
            assert re[0], '未发现警告窗口'
            return re[1]
        except AssertionError as e:
            # self._get_main_window()
            log_manager.logger.info(f"{usr} login successful")
            return True

    def exit(self):
        """
        功能:地面站关闭方法，执行完所有步骤后关闭地面站
        参数：None
        返回：None
        """

        try:
            self.click('MainWindow_TitleBar_Close_Button', ratioX=0.3, ratioY=0.5)
            self.click("ConfirmButton")
            return True

        except Exception as e:
            log_manager.logger.error(f"Exit failed: {e}")
            return False

    def uav_light(self, uav_id, color):
        """
        功能:选中飞机进行亮灯操作，三秒后关闭灯光
        参数：
            uav_id(sting):飞机id
            color(string):灯光颜色的十六进制码，eg:白：FFFFFF 黑：000000 红：FF0050  绿:A5FF00 蓝:0066FF
        返回：
            boolean:操作成功后返回True，如果所选的飞机id不存在则返回False
        """
        result = self.uav_search(uav_id)
        if result:
            # 打开点灯菜单
            self.click("ControlMenu_Lighting_ToggleButton")

            # 点击颜色表
            self.click(f'ColorPickButton_{color}', wait_loading=True)
            time.sleep(3)
            self.click("ColorPickButton_000000", wait_loading=True)

            self.click("ControlMenu_Lighting_ToggleButton")
            self.input_text('UavListView_SearchCondition_TextBox', "{Delete}")
            self.click('UavViewMenu_ListView_ToggleButton')
            return True
        else:
            log_manager.logger.error(f"{uav_id} not found")
            return False

    def uav_search(self, uav_id):
        """
        功能:根据飞机搜索过滤，并点击选中飞机
        参数：
            uav_id(sting):飞机id
        返回：
            boolean:所选飞机存在则返回True，不存在则返回False
        """
        self.click('UavViewMenu_ListView_ToggleButton')
        self.input_text('UavListView_SearchCondition_TextBox', str(uav_id))
        self.click("UavListView_Search_Button")

        # 2.判断查找的id是否存在，存在则选中对应飞机
        data_grid = self.get_node('UavListView_Uav_DataGrid')
        if len(list(data_grid['child'].keys())) == 1:
            log_manager.logger.info(f'id {uav_id} not found')
            return False
        self.click("SelectBtnsGroup_UnselectAll_Button")
        self.click(f'{uav_id}')

        return True

    def uav_info(self, uav_id):
        """
        功能:搜索飞机查看飞机的详细信息
        参数：
            uav_id(sting):飞机id
        返回：
            dict:将飞机的所有参数打包成dict返回，如果飞机id不存在则返回{}
        """
        result = self.uav_search(uav_id)
        if result:
            self.save_screenshot(self.main_tree, 'UavListView')

            # 3.点击指定id飞机获取详细信息
            detail = self.get_node('detailInfo')
            prefix_key = 'DroneDetailPanel_%s'
            item = {"id": "Drone_DisplayId_TextBox", "ip": "Network_IpAddress_TextBox",
                    "mac": "Network_MacAddress_TextBox",
                    "sn": "Network_UniqueSerial_TextBox", "ssid": "Network_GroupId_TextBox",
                    "rcId": "Network_Rcid_TextBox",
                    "lon": "FlightStatus_Longitude_TextBox", "lat": "FlightStatus_Latitude_TextBox",
                    "asl": "FlightStatus_Asl_TextBox",
                    "roll": "FlightStatus_Roll_TextBox", "pitch": "FlightStatus_Pitch_TextBox",
                    "yaw": "FlightStatus_Yaw_TextBox",
                    "battery_used_times": "Battery_UsedTimes_Label",
                    "voltage_battery_diff": "Battery_VoltageDiff_Label",
                    "voltage_battery_history_diff": "Battery_VoltageHistoryDiff_Label",
                    "temp_imu": "Battery_ImuTemperature_Label", "temp_baro": "Battery_BaroTemperature_Label",
                    "temp_batt": "Battery_BatteryTemperature_Label",
                    "voltage_battery_cell1": "Battery_Cell1Voltage_Label",
                    "voltage_battery_cell2": "Battery_Cell2Voltage_Label",
                    "voltage_battery_cell3": "Battery_Cell3Voltage_Label",
                    "voltage_battery_cell4": "Battery_Cell4Voltage_Label",
                    "battery_serial_number": "Battery_SerialNumber_TextBox",
                    "mav": "Firmware_Mavlink_TextBox", "fc": "Firmware_Fc_TextBox", "com": "Firmware_Com_TextBox",
                    "bat": "Firmware_Battery_TextBox", "gps": "Firmware_Gps_TextBox", "rcvr": "Firmware_Tele_TextBox",
                    "bms": "Firmware_Bms_TextBox", "rid": "Firmware_Rid_TextBox", "message": "Message_Status_TextBox"
                    }
            result = {}
            for x in item:
                text_control = detail['child'][prefix_key % item[x]]['instance']
                value = text_control.Name if text_control.Name != '' else text_control.GetLegacyIAccessiblePattern().Value
                result[x] = value

            # 4.清空关闭

            self.input_text('UavListView_SearchCondition_TextBox', '{Delete}')
            self.click('UavViewMenu_ListView_ToggleButton')
            log_manager.logger.info(str(result))
            return result
        else:
            log_manager.logger.error(f"{uav_id} not found")
            return {}

    def add_simulated_uav(self, uav_type):
        """
        功能:根据飞机类型添加200架模拟飞机
        参数：
            uav_type(sting):飞机类型，eg:Newton40
        返回：
            boolean:如果传入飞机类型不存在则返回False，成功添加后返回False
        """
        self.click('CommonMenu_Toolbox_Button')
        self.click("CommonMenu_Toolbox_Debug_MenuItem")
        self.click("DebugWindow_Simulator_CheckBox", wait_loading=True)
        debug_win = self._get_debug_window()

        self.click("comboxUavType", control_instance=debug_win)
        debug_win = self._get_debug_window()
        scroll = self.get_node('comboxUavType', control_instance=debug_win, )
        rect = scroll['instance'].BoundingRectangle
        auto.MoveTo(int((rect.left + rect.right) / 2), rect.bottom + 50)
        for i in range(3):
            try:
                self.click(uav_type, control_instance=debug_win)
                break
            except:
                auto.WheelDown(3)
                debug_win = self._get_debug_window(active=False)
        else:
            self.click("comboxUavType", control_instance=debug_win)
            self.click('CloseWindow', control_instance=debug_win)
            log_manager.logger.error(f"uav type {uav_type} not found")
            return False

        debug_win = self._get_debug_window()
        self.click("btnAddUav", control_instance=debug_win)
        self._get_debug_window()
        self.click("MinimizeButton", control_instance=debug_win)

        allure.attach.file(
            root_path + "/file/picture/debug_tool.png",
            name="执行结果",
            attachment_type=allure.attachment_type.PNG)

        log_manager.logger.info("add simulated uav successful")
        return True

    def load_player(self, drama_path):
        """
        功能:加载剧本文件
        参数：
            drama_path(sting):剧本文件的名称
        返回：
            boolean:剧本文件加载成功后返回True
        """
        self.click("DramaCfgMenu_DramaLoad_ToggleButton")
        self.click("DramaLoad_Load_Button")
        self.click("1148")

        self.input_text('1148', root_path + drama_path)
        self.click('1')

        log_manager.logger.info(rf"player name【{root_path}{drama_path}")
        allure.attach.file(
            root_path + "/file/picture/main.png",
            name="执行结果",
            attachment_type=allure.attachment_type.PNG)

        self.click("DramaCfgMenu_DramaLoad_ToggleButton")
        log_manager.logger.info(f"{drama_path} loaded successfully")
        return True

    def set_rtk(self):
        """
        功能:差分设置，选择差分账号为qxwz
        参数：None
        返回：
            boolean:差分设置成功返回True，失败则返回False
        """

        self.click("DramaCfgMenu_Rtk_ToggleButton")
        self.click("RTKSet_RtkForwardPort_ComboBox")

        self.click("qxwz", active=False)
        self.click("RTKSet_RtkForwardOpen_Button")
        time.sleep(3)
        warnings = self.get_node('警告')

        allure.attach.file(
            root_path + "/file/picture/main.png",
            name="执行结果",
            attachment_type=allure.attachment_type.PNG)

        if warnings:
            msg_ctrl = self.get_node('MessageTextBlock')
            msg = msg_ctrl['instance'].Name
            self.click("ConfirmButton")
            self.click("DramaCfgMenu_Rtk_ToggleButton")
            log_manager.logger.error(f"Rtk set error：{msg}")
            return False
        else:
            self.click("DramaCfgMenu_Rtk_ToggleButton")
            return True

    def set_origin(self, flag=False):
        """
        功能:设置原点，在导入剧本后，选择飞机id为1的飞机设置原点，如果当前坐标附近周围4公里存在其他的表演项目则会弹出提醒，如果当前坐标位置区域为禁飞区则设置原点失败
        参数：
            flag(boolean):周边是否有其他表演项目的提示标志
        返回：
            boolean:如果当前位置在禁飞区则返回False，否则返回True
        """

        self.click("DramaCfgMenu_Origin_ToggleButton")
        self.input_text('OriginSet_UavId_ComboBox', '1')

        allure.attach.file(
            root_path + "/file/picture/main.png",
            name="执行结果",
            attachment_type=allure.attachment_type.PNG)

        warnings = self.get_node('警告')
        if flag:
            self.click("确定")
        if warnings:
            msg_ctrl = self.get_node('MessageTextBlock')
            msg = msg_ctrl['instance'].Name
            log_manager.logger.error(f"Origin set error：{msg}")
            self.click("ConfirmButton")
            self.click("DramaCfgMenu_Origin_ToggleButton")
            return False
        self.click("DramaCfgMenu_Origin_ToggleButton")
        log_manager.logger.info("set origin successful")
        return True

    def mapping_set(self):
        """
        功能:剧本映射，采取一键映射策略
        参数：None
        返回：None
        """
        self.click('DramaCfgMenu_MapSet_ToggleButton')
        self.click('MappingSet_AllAutoMap_Button')

        allure.attach.file(
            root_path + "/file/picture/main.png",
            name="执行结果",
            attachment_type=allure.attachment_type.PNG)
        self.click('MappingSet_Set_Button')
        log_manager.logger.info("mapping set successful")

    def set_show_time(self):
        """
        功能:设置表演时间，这里采取自动生成的策略
        参数：None
        返回：None
        """
        self.click("DramaCfgMenu_TimeSet_ToggleButton")
        self.click("RelativeTime_AutoGenerate_Button")
        self.click("RelativeTime_SetTime_Button")

        allure.attach.file(
            root_path + "/file/picture/main.png",
            name="执行结果",
            attachment_type=allure.attachment_type.PNG)
        self.click("DramaCfgMenu_TimeSet_ToggleButton")
        log_manager.logger.info("show time set successful")

    def review_player(self):
        """
        功能:剧本预览，该方法没有预览过程，采取直接勾选【已预览】策略
        参数：None
        返回：None
        """
        self.click("DramaCfgMenu_Preview_ToggleButton")
        self._get_main_window()
        self.click("Preview_EnablePreview_CheckBox")
        self.click("DramaCfgMenu_Preview_ToggleButton")

    def transfer_player(self):
        """
        功能:传输剧本，全部传输
        参数：None
        返回：
        boolean：设置等待时间为10秒，传输成功则返回True，失败则返回False
        """
        self.click("DramaCfgMenu_DramaSend_ToggleButton")
        self.click("DramaTransmit_Transmit_Button")
        self.click("TransmitTask_AllTransmit_Button")

        success = self.get_node('提示')
        if success:
            result = True
        else:
            fail = self.get_node('警告')
            result = False

        msg_ctrl = self.get_node('MessageTextBlock')
        msg = msg_ctrl['instance'].Name
        self._get_main_window()
        self.click("ConfirmButton")

        allure.attach.file(
            root_path + "/file/picture/main.png",
            name="执行结果",
            attachment_type=allure.attachment_type.PNG)

        self.click("CloseWindow")
        self.click("DramaTransmit_Transmitted_CheckBox")
        self.click("DramaCfgMenu_DramaSend_ToggleButton")
        log_manager.logger.info(f"transmission {msg}")
        return result

    def start_show(self):
        """
        功能:检查并开始表演，如果差分未设置则会弹出两次提醒
        参数：None
        返回：None
        """
        self.click("PlayMenu_PerformDrama_ToggleButton")
        self.click("PlayPanel_Check_Button")
        # self._get_main_window()
        self.click("ConfirmButton")
        # self._get_main_window()
        self.click("ConfirmButton")
        self.click("PlayPanel_StartPerforming_ToggleButton")
        # self._get_main_window()
        self.click("ConfirmButton")
        # self._get_main_window()
        self.click("ConfirmButton")

        while True:
            time.sleep(10)
            self._get_main_window()
            ctrl = self.get_node('ConfirmButton')
            if ctrl:
                allure.attach.file(
                    root_path + "/file/picture/main.png",
                    name="执行结果",
                    attachment_type=allure.attachment_type.PNG)
                break
        msg_ctrl = self.get_node('MessageTextBlock')
        msg = msg_ctrl['instance'].Name
        log_manager.logger.info(f"提示信息：{msg}")
        self.click("ConfirmButton")

    def update_firmware(self, uva_id):
        """
        功能:根据传入的飞机id更新固件
        参数：
            uav_id：飞机id
        返回：
            boolean：等待3分钟更新成功则返回True，失败则返回False
        """

        self.click("CommonMenu_Settings_Button")
        self.click("CommonMenu_Settings_UpdateFirmware_MenuItem")

        grid = self.get_node('FCFirmware_Firmware_DataGrid')
        self.click(f"Column_Uav_DisplayId_{uva_id}", control_instance=grid['child'])

        self.click("FCFirmware_PartUpdate_Button")

        success = self.get_node('提示', timeout=30)
        if success:
            result = True
        else:
            fail = self.get_node('警告', timeout=30)
            result = False
        allure.attach.file(
            root_path + "/file/picture/main.png",
            name="执行结果",
            attachment_type=allure.attachment_type.PNG)

        msg_ctrl = self.get_node('MessageTextBlock')
        msg = msg_ctrl['instance'].Name
        log_manager.logger.info(f"提示信息：{msg}")
        self.click("ConfirmButton")
        self.click('CloseWindow')
        return result

    def profile(self):
        """
        功能:用户信息检查，到期时间，飞机数量，飞机类型等信息
        参数：None
        返回：
            dict:将信息打包成字典格式
        """
        # 首次进入地面站主页，检查是否有电池序列号提醒
        tips = self.get_node('ConfirmButton')
        if tips:
            msg_ctrl = self.get_node('MessageTextBlock')
            msg = msg_ctrl['instance'].Name
            log_manager.logger.info(f"提示信息：{msg}")
            self.click("ConfirmButton")

        info = {}
        self.click('OtherMenu_UserInfo_Button')
        self._get_main_window()
        user_info = self.get_node('用户信息')
        info['user_name'] = self.get_node('UserInfo_Username_TextBox', control_instance=user_info['child'])[
            'instance'].GetLegacyIAccessiblePattern().Value

        info['expire_date'] = self.get_node('UserInfo_ExpiredDate_TextBox', control_instance=user_info['child'])[
            'instance'].GetLegacyIAccessiblePattern().Value

        uav_type = self.get_node('UserInfo_UavType_TextBox', control_instance=user_info['child'])[
            'instance'].GetLegacyIAccessiblePattern().Value
        info['uav_type'] = uav_type.splitlines()

        allure.attach.file(
            root_path + "/file/picture/main.png",
            name="执行结果",
            attachment_type=allure.attachment_type.PNG
        )
        self.click("CloseWindow")
        log_manager.logger.info(f"{str(info)}")
        return info

    def set_netcard(self, name):
        """
        功能:根据传入的name设置我网卡
        参数：
            name(string):网卡名称
        返回：
            boolean：网卡名称存在则设置成功，不存在则设置失败
        """

        self.click("CommonMenu_Settings_Button")
        self.click("设置网卡")
        self.click("Settings_NetCard_SelectComboBox")

        allure.attach.file(
            root_path + "/file/picture/main.png",
            name="执行结果",
            attachment_type=allure.attachment_type.PNG)

        try:
            self.click(name, active=False)
            self.click("Settings_NetCard_SetButton", wait_loading=True, timeout=30)
            tips = self.get_node('ConfirmButton')
            if tips:
                msg_ctrl = self.get_node('MessageTextBlock')
                msg = msg_ctrl['instance'].Name
                log_manager.logger.info(f"提示信息：{msg}")
                self.click("ConfirmButton")
        except:
            self.click("Settings_NetCard_SelectComboBox")
            self.click("CloseWindow")
            log_manager.logger.error(f"set netcard failed,{name} not found")
            return False
        log_manager.logger.info(f"{name} set successful")
        return True

    def parameter_set(self, uav_id, param_name, value):
        """
        功能:设置单个飞机的某个参数值
        参数：
            uav_id(string):飞机id
            param_name(string):参数名称
            value(string):参数值
        返回：
            boolean：参数设置成功则返回True，失败则返回False
        """
        uav = self.uav_search(uav_id)
        if uav:
            self.click("ControlMenu_ParamConfig_ToggleButton")
            self.click("PART_EditableTextBox")
            self.input_text('PART_EditableTextBox', param_name)
            self.click("ParamConfig_Read_Button")
            self.click("ParamConfig_Read_Button")
            self.input_text("ParamConfig_ParamValue_NumericBox", str(value))
            self.click("ParamConfig_Set_Button")

            success = self.get_node('提示', timeout=30)
            if success:
                result = True
            else:
                fail = self.get_node('警告', timeout=30)
                result = False

            allure.attach.file(
                root_path + "/file/picture/main.png",
                name="执行结果",
                attachment_type=allure.attachment_type.PNG)

            msg_ctrl = self.get_node('MessageTextBlock')
            msg = msg_ctrl['instance'].Name
            log_manager.logger.info(f"提示信息：{msg}")

            self.click("ConfirmButton")
            self.click("ControlMenu_ParamConfig_ToggleButton")
            self.input_text('UavListView_SearchCondition_TextBox', '{Delete}')
            self.click('UavViewMenu_ListView_ToggleButton')
            return result
        else:
            return False

    ####################################################### 其他菜单 ###############################
    def standby(self, uav_id):
        search_result = self.uav_search(uav_id)

        if search_result:
            self.click("ControlMenu_Other_ToggleButton")
            self._get_main_window()
            self.click("ControlMenu_Other_ToggleButton")
            time.sleep(5)
            self._get_main_window()
            warings = self.get_node("警告")
            if warings:
                msg_ctrl = self.get_node('MessageTextBlock')
                msg = msg_ctrl['instance'].Name
                log_manager.logger(f"{uav_id} 待机失败,message：{msg}")
                return False
            else:
                return True
        else:
            return False
