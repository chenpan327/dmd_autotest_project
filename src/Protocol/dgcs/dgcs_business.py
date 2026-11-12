# -*- coding: utf-8 -*-
"""
dgcs_business.py

业务层模块：负责组合 UI 原子操作，完成完整的 DGCS 业务流程。

本模块通过 self.ui 访问 dgcs_ui.DgcsUI 提供的 UI 层能力，自身不包含直接操作控件的方法，
而是将原子操作编排为端到端的业务动作，例如：
- 登录 / 关闭应用
- 加载剧本、设置原点、设置时间
- 传输剧本、验证剧本、设置映射
- 查看无人机详情、参数配置

典型用法：
    from dgcs_business import DgcsBusiness
    dgcs = DgcsBusiness()
    dgcs.start_app()
    dgcs.login(username, password)
    dgcs.load_drama("show.dgcs")
"""

import time
import os
import tempfile
import re

import xlwt

from src.Physical.Dgcs.dgcs_ui import DgcsUI, APP_PATH
from utils.text_color import check_text_color_red

class DgcsBusiness:
    """
    业务层：负责组合 UI 原子操作，完成完整的业务流程。
    通过 self.ui 访问 UI 层能力，自身不包含直接操作控件的方法。
    """

    def __init__(self, ui=None, app_path=APP_PATH):
        self.ui = ui or DgcsUI(app_path)

    def start_app(self):
        return self.ui.start_app()

    def close_app(self):
        name = self.ui.main_window.Name if self.ui.main_window else ""
        if name and "DGCS" in name:
            close_button = self.ui.get_login_close_button()
            close_button.Click()
        elif name and "大漠大地面控制站" in name:
            close_button = self.ui.get_control_close_button()
            close_button.Click()
            time.sleep(1)
            close_button = self.ui.get_close_mainwindow_confirm_button()
            close_button.Click()


        if self.check_main_window_close_warming():
            print(f"成功关闭 {self.ui.app_path}")
        elif self.ui.process_id:
            self.ui.terminate_process()
            print(f"成功关闭 {self.ui.app_path}")
        else:
            print(f"无法关闭 {self.ui.app_path}")

    def dump_controls(self, save_path="controls.json"):
        return self.ui.dump_controls(save_path)

    def input_username(self, username):
        try:
            username_edit = self.ui.get_login_username_edit()
            self.ui.clear_edit(username_edit)
            username_edit.SendKeys(username)
            print(f"已输入用户名: {username}")
            return True
        except Exception as e:
            print(f"输入用户名失败: {e}")
            return False

    def input_password(self, password):
        try:
            password_edit = self.ui.get_login_password_edit()
            self.ui.clear_edit(password_edit)
            password_edit.SendKeys(password)
            print(f"已输入密码: {password}")
            return True
        except Exception as e:
            print(f"输入密码失败: {e}")
            return False
        
    # 登录界面 - 检查登录界面
    def check_login_window(self, status=True, wait_time=2):
        interval = 0.2
        appear_start = time.time()
        # 缓存窗口定位器，避免每次循环都重新查找主窗口 + 查找更新窗口
        window = self.ui.get_login_submit_button()
        while time.time() - appear_start < wait_time:
            if window.Exists() == status:
                time.sleep(interval)
            else:
                return False
        return True
    
    def click_login(self):
        try:
            submit_button = self.ui.get_login_submit_button()
            submit_button.Click()
            print("已点击登录按钮")
            return True
        except Exception as e:
            print(f"点击登录按钮失败: {e}")
            return False

    def check_login_success(self, wait_time=2):
        interval = 0.2
        # 等待5s 登录中弹窗消失
        time.sleep(5)
        for _ in range(int(wait_time / interval)):
            try:
                login_window = self.ui.get_login_window()
                warming_window = login_window.WindowControl(Name='警告')
                warming_message_text = warming_window.TextControl(AutomationId='MessageTextBlock')
                if warming_message_text:
                    print("检测到登录失败警告弹窗")
                    warming_confirm_button = warming_window.ButtonControl(AutomationId='ConfirmButton')
                    warming_confirm_button.Click()
                    print("已关闭警告弹窗")
                    return False
            except:
                pass
            time.sleep(interval)

        self.ui._refresh_main_window()
        if self.ui.main_window is not None:
            self.ui.process_id = self.ui.find_existing_process()
        print("登录成功")
        return True

    def login_with_history(self, username, password=None):
        pass

    def get_main_window(self):
        return self.ui.get_control_window()

    # 登录界面 - 检查主界面
    def check_main_window(self, status=True, wait_time=2):
        interval = 0.2
        appear_start = time.time()
        # 缓存窗口定位器，避免每次循环都重新查找主窗口 + 查找更新窗口
        window = self.ui.get_control_window()
        while time.time() - appear_start < wait_time:
            if window.Exists() == status:
                time.sleep(interval)
            else:
                return False
        return True
    
    def check_main_window_close_warming(self, wait_time=1):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                control_window = self.ui.get_control_window()
                warming_window = control_window.WindowControl(Name='询问')
                warming_message_text = warming_window.TextControl(AutomationId='MessageTextBlock')
                if warming_message_text:
                    print("检测到退出询问弹窗")
                    warming_confirm_button = warming_window.ButtonControl(AutomationId='ConfirmButton')
                    warming_confirm_button.Click()
                    print("已关闭退出询问弹窗")
                    return False
            except:
                pass
            time.sleep(interval)
        return True

    def check_main_window_waiting(self, wait_time=3):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                control_window = self.ui.get_control_window()
                waiting_window = control_window.WindowControl(Name='LoadingWindow')
                waiting_message_text = waiting_window.TextControl(AutomationId='Utils_Loading_StatusTextBlock')
                if waiting_message_text:
                    print("检测到等待弹窗")
                else:
                    return True
            except:
                return True
            time.sleep(interval)
        return False

    def check_battery_warming(self, wait_time=3):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                control_window = self.ui.get_control_window()
                warming_window = control_window.WindowControl(Name='警告')
                warming_message_text = warming_window.TextControl(AutomationId='TitleTextBlock')
                if "设置电池序列号" in warming_message_text or "Set Battery Serial" in warming_message_text:
                    print("检测到电池警告弹窗")
                    warming_confirm_button = warming_window.ButtonControl(AutomationId='ConfirmButton')
                    warming_confirm_button.Click()
                    print("已关闭电池警告弹窗")
                    return False
            except:
                pass
            time.sleep(interval)
        return True

    def get_adjacent_project_warning_texts(self):
        warning_window = self.ui.get_adjacent_project_warning_window()
        texts = []

        def _collect_texts(control):
            try:
                if control.ControlTypeName == 'TextControl' and control.Name:
                    texts.append(control.Name)
                for child in control.GetChildren():
                    _collect_texts(child)
            except Exception:
                pass

        _collect_texts(warning_window)
        return texts

    def click_adjacent_project_warning_confirm(self):
        try:
            warning_window = self.ui.get_adjacent_project_warning_window()
            confirm_button = warning_window.ButtonControl(Name='确定')
            confirm_button.Click()
            print("已点击确定按钮关闭弹窗")
            return True
        except Exception as e:
            print(f"点击确定按钮失败: {e}")
            return False

    def check_and_close_adjacent_project_warning(self, wait_time=3):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                warning_window = self.ui.get_adjacent_project_warning_window()
                if warning_window:
                    print("检测到邻近表演项目弹窗")
                    texts = self.get_adjacent_project_warning_texts()
                    self.click_adjacent_project_warning_confirm()
                    return texts
            except:
                pass
            time.sleep(interval)
        return None

    def load_drama(self, filename, wait_time=5):
        try:
            dramaload_cfg_button = self.ui.get_drama_cfg_dramaload_button()
            dramaload_cfg_button.Click()
            print("已点击剧本加载按钮")
            time.sleep(0.5)

            drama_button = self.ui.get_dramaload_drama_button()
            drama_button.Click()
            print("已点击剧本按钮")
            time.sleep(0.5)

            load_button = self.ui.get_dramaload_load_button()
            load_button.Click()
            print("已点击加载按钮")
            time.sleep(0.5)

            interval = 0.2
            dialog_window = None
            for _ in range(int(wait_time / interval)):
                try:
                    dialog_window = self.ui.get_dramaload_dialog_window()
                    if dialog_window:
                        print("检测到剧本文件选择弹窗")
                        break
                except:
                    pass
                time.sleep(interval)

            if not dialog_window:
                print("未检测到剧本文件选择弹窗")
                return False

            filename_edit = self.ui.get_dramaload_dialog_filename_edit()
            self.ui.input_to_edit(filename_edit, filename)
            print(f"已输入文件名: {filename}")
            time.sleep(0.2)

            open_button = self.ui.get_dramaload_dialog_open_button()
            open_button.Click()
            print("已点击打开按钮")
            time.sleep(0.5)

            time.sleep(2)
            time.sleep(1)
            info_edit = self.ui.get_dramaload_info_edit()
            loaded_info = self.ui.get_control_value(info_edit)
            loaded_info = loaded_info.strip() if loaded_info else ""
            print(f"读取到剧本信息: {loaded_info!r}")

            if os.path.basename(filename).strip() in loaded_info:
                print(f"剧本校验成功: {filename}")
                result = True
            else:
                print(f"剧本校验失败。期望: {os.path.basename(filename)}, 实际: {loaded_info}")
                result = False

            dramaload_cfg_button = self.ui.get_drama_cfg_dramaload_button()
            dramaload_cfg_button.Click()
            print("已关闭剧本加载面板")
            time.sleep(0.5)

            return result

        except Exception as e:
            print(f"加载剧本失败: {e}")
            return False

    def set_origin(self, drone_id):
        try:
            origin_button = self.ui.get_drama_cfg_origin_button()
            origin_button.Click()
            print("已点击原点设置按钮")
            time.sleep(0.5)

            longitude_edit = self.ui.get_origin_set_longitude_edit()
            latitude_edit = self.ui.get_origin_set_latitude_edit()

            self.ui.input_to_edit(longitude_edit, '0')
            print("已将经度设为0")
            time.sleep(0.1)

            self.ui.input_to_edit(latitude_edit, '0')
            print("已将纬度设为0")
            time.sleep(0.1)

            set_button = self.ui.get_origin_set_set_button()
            set_button.Click()
            print("已点击设置按钮（归零）")
            time.sleep(0.5)

            refresh_button = self.ui.get_origin_set_refresh_button()
            refresh_button.Click()
            print("已点击刷新按钮")
            time.sleep(0.5)

            uavid_edit = self.ui.get_origin_set_uavid_edit()
            uavid_edit.Click()
            print("已点击飞机Id输入框")
            time.sleep(0.2)

            self.ui.clear_edit(uavid_edit)
            uavid_edit.SendKeys(drone_id)
            print(f"已输入飞机Id: {drone_id}")
            time.sleep(0.1)

            set_button = self.ui.get_origin_set_set_button()
            set_button.Click()
            print("已点击设置按钮")
            time.sleep(0.5)

            longitude_edit = self.ui.get_origin_set_longitude_edit()
            latitude_edit = self.ui.get_origin_set_latitude_edit()

            longitude_value = self.ui.get_control_value(longitude_edit)
            latitude_value = self.ui.get_control_value(latitude_edit)
            print(f"设置后经度: {longitude_value}, 纬度: {latitude_value}")

            try:
                lon_is_zero = float(longitude_value) == 0.0
            except (ValueError, TypeError):
                lon_is_zero = longitude_value == '0' or longitude_value == '' or longitude_value is None

            try:
                lat_is_zero = float(latitude_value) == 0.0
            except (ValueError, TypeError):
                lat_is_zero = latitude_value == '0' or latitude_value == '' or latitude_value is None

            if lon_is_zero and lat_is_zero:
                print("原点设置可能未成功，经纬度仍为0")
                return False
            else:
                print("原点设置成功")

            origin_button = self.ui.get_drama_cfg_origin_button()
            origin_button.Click()
            print("已关闭原点设置面板")
            return True
        except Exception as e:
            print(f"设置原点失败: {e}")
            return False

    def set_time(self):
        try:
            timeset_button = self.ui.get_drama_cfg_timeset_button()
            timeset_button.Click()
            print("已点击时间设置按钮")
            time.sleep(0.5)

            auto_generate_button = self.ui.get_time_set_auto_generate_button()
            auto_generate_button.Click()
            print("已点击自动生成按钮")
            time.sleep(0.5)

            set_time_button = self.ui.get_time_set_set_time_button()
            set_time_button.Click()
            print("已点击设置时间按钮")
            time.sleep(0.5)

            timeset_button = self.ui.get_drama_cfg_timeset_button()
            timeset_button.Click()
            print("已关闭时间设置面板")
            return True
        except Exception as e:
            print(f"设置时间失败: {e}")
            return False

    def open_uav_view_meau_list(self):
        try:
            uav_view_meau_list_button = self.ui.get_uav_view_menu_list_button()
            uav_view_meau_list_button.Click()
            print("已点击列表视图")
            return True
        except Exception as e:
            print(f"点击列表视图失败: {e}")
            return False

    def show_drone_message(self, drone_id):
        drone_button = self.ui.get_uav_view_menu_drone_button(drone_id)
        if drone_button:
            drone_button.Click()
            print(f"找到目标飞机 ID: {drone_id}")
            return True
        else:
            print("未找到目标飞机")
            return False

    def check_drone_detail_info(self, drone_id):
        detail_info = {}

        uav_detail_info = self.ui.get_uav_view_menu_drone_detail_info()

        item = {
            "drone_id": "Drone_DisplayId_TextBox",
            "ip_address": "Network_IpAddress_TextBox",
            "mac_address": "Network_MacAddress_TextBox",
            "serial_number": "Network_UniqueSerial_TextBox",
            "group_id": "Network_GroupId_TextBox",
            "rc_id": "Network_Rcid_TextBox",
            "fail_safe_ekf_unhealthy": "FlightStatus_Ekf_Label",
            "fail_safe_crash_detected": "FlightStatus_Crash_Label",
            "fail_safe_radio_lost": "FlightStatus_Radio_Label",
            "fail_safe_battery_failsafe": "FlightStatus_Battery_Label",
            "fail_safe_fence_1_breach": "FlightStatus_FirstFence_Label",
            "fail_safe_fence_2_breach": "FlightStatus_SecondFence_Label",
            "fail_safe_waypoint_fail": "FlightStatus_Waypoint_Label",
            "fail_safe_drama_fail": "FlightStatus_DramaFail_Label",
            "fail_safe_parachute_active": "FlightStatus_Parachute_Label",
            "fail_safe_too_far": "FlightStatus_TooFar_Label",
            "fail_safe_static_distance_fail": "FlightStatus_StaticDistance_Label",
            "fail_safe_vibration_high": "FlightStatus_Vibration_Label",
            "fail_safe_imu_unhealthy": "FlightStatus_Imu_Label",
            "fail_safe_baro_unhealthy": "FlightStatus_Baro_Label",
            "fail_safe_compass_unhealthy": "FlightStatus_Compass_Label",
            "fail_safe_gps_unhealthy": "FlightStatus_Gps_Label",
            "fail_safe_battery_health_bad": "FlightStatus_BatteryHealth_Label",
            "fail_safe_acc_calibrating": "FlightStatus_AccCalibration_Label",
            "fail_safe_compass_calibrating": "FlightStatus_CompassCalibration_Label",
            "fail_safe_light_calibrating": "FlightStatus_LightCalibration_Label",
            "fail_safe_magnetic_disturb": "FlightStatus_MagneticDisturb_Label",
            "fail_safe_scram_active": "FlightStatus_Scram_Label",
            "fail_safe_esc_unhealthy": "FlightStatus_Esc_Label",
            "fail_safe_parachute_health_bad": "FlightStatus_ParachuteHealth_Label",
            "fail_safe_tele_unhealthy": "FlightStatus_Tele_Label",
            "fail_safe_bms_unhealthy": "FlightStatus_Bms_Label",
            "fail_safe_module_unhealthy": "FlightStatus_Module_Label",
            "fail_safe_rid_unhealthy": "FlightStatus_Rid_Label",
            "fail_safe_gimbal_unhealthy": "FlightStatus_Gimbal_Label",
            "longitude": "FlightStatus_Longitude_TextBox",
            "latitude": "FlightStatus_Latitude_TextBox",
            "altitude_asl": "FlightStatus_Asl_TextBox",
            "roll_angle": "FlightStatus_Roll_TextBox",
            "pitch_angle": "FlightStatus_Pitch_TextBox",
            "yaw_angle": "FlightStatus_Yaw_TextBox",
            "battery_cycle_count": "Battery_UsedTimes_Label",
            "voltage_diff": "Battery_VoltageDiff_Label",
            "voltage_history_diff": "Battery_VoltageHistoryDiff_Label",
            "current_capacity": "Battery_CurrentCapacity_Label",
            "total_capacity": "Battery_TotalCapacity_Label",
            "remaining_flight_time": "Battery_RemainFlyTime_Label",
            "temp_imu": "Battery_ImuTemperature_Label",
            "temp_baro": "Battery_BaroTemperature_Label",
            "temp_battery": "Battery_BatteryTemperature_Label",
            "voltage_cell_1": "Battery_Cell1Voltage_Label",
            "voltage_cell_2": "Battery_Cell2Voltage_Label",
            "voltage_cell_3": "Battery_Cell3Voltage_Label",
            "voltage_cell_4": "Battery_Cell4Voltage_Label",
            "voltage_rid": "Battery_RidVoltage_Label",
            "battery_serial_number": "Battery_SerialNumber_TextBox",
            "version_mavlink": "Firmware_Mavlink_TextBox",
            "version_fc": "Firmware_Fc_TextBox",
            "version_com": "Firmware_Com_TextBox",
            "version_battery": "Firmware_Battery_TextBox",
            "version_gps": "Firmware_Gps_TextBox",
            "version_tele": "Firmware_Tele_TextBox",
            "version_bms": "Firmware_Bms_TextBox",
            "version_rid": "Firmware_Rid_TextBox",
            "version_gimbal": "Firmware_Gimbal_TextBox",
            "message_status": "Message_Status_TextBox"
        }

        for key, automation_id in item.items():
            automation_id = "DroneDetailPanel_" + automation_id
            ui_element = uav_detail_info.Control(searchDepth=1, AutomationId=automation_id)
            legacy_accessible = ui_element.GetLegacyIAccessiblePattern()
            if legacy_accessible:
                detail_info[key] = legacy_accessible.Value
            else:
                detail_info[key] = None

        if "drone_id" in detail_info and detail_info["drone_id"] == drone_id:
            print(f"成功校验无人机 ID：{detail_info['drone_id']}")
        elif "drone_id" in detail_info:
            print(f"无人机 ID 不匹配。期望: {drone_id}, 实际: {detail_info['drone_id']}")

        return detail_info

    def check_param_config_warming(self, wait_time=1):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                control_window = self.ui.get_control_window()
                warming_window = control_window.WindowControl(Name='警告')
                if warming_window:
                    print("检测到警告弹窗")
                    warming_confirm_button = warming_window.ButtonControl(AutomationId='ConfirmButton')
                    warming_confirm_button.Click()
                    print("已关闭警告弹窗")
                    return False
            except:
                pass
            time.sleep(interval)
        return True

    def set_drone_param_config(self, drone_id, param_config_name, param_value=None):
        self.open_uav_view_meau_list()
        self.show_drone_message(drone_id)
        detail_info = self.check_drone_detail_info(drone_id)
        self.open_uav_view_meau_list()

        drone_param_config_button = self.ui.get_drone_param_config_button()
        if drone_param_config_button:
            drone_param_config_button.Click()

            param_config_edit = self.ui.get_drone_param_config_name_edit()
            self.ui.input_to_edit(param_config_edit, param_config_name)
            time.sleep(0.1)

            param_config_read_button = self.ui.get_drone_param_config_read_button()
            param_config_read_button.Click()
            time.sleep(0.1)
            param_config_read_button.Click()
            time.sleep(0.1)

            if param_value is not None:
                param_config_value_edit = self.ui.get_drone_param_config_value_edit()
                self.ui.input_to_edit(param_config_value_edit, str(param_value))
                print(f"已输入参数值: {param_value}")
                time.sleep(0.1)

            param_config_set_button = self.ui.get_drone_param_config_set_button()
            param_config_set_button.Click()
            print("已点击设置按钮")
            time.sleep(0.1)

            self.check_set_drone_param_config_successful()

            drone_param_config_button.Click()

        self.open_uav_view_meau_list()
        self.show_drone_message(drone_id)
        detail_info = self.check_drone_detail_info("")
        self.open_uav_view_meau_list()

    def check_set_drone_param_config_successful(self, wait_time=2):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                control_window = self.ui.get_control_window()
                drone_param_config_successful = control_window.WindowControl(Name='提示')
                if drone_param_config_successful:
                    print("检测到提示弹窗")
                    wsuccessful_confirm_button = drone_param_config_successful.ButtonControl(AutomationId='ConfirmButton')
                    wsuccessful_confirm_button.Click()
                    print("已关闭提示弹窗")
                    return False
            except:
                pass
            time.sleep(interval)
        return True

    def check_and_close_dramasend_success(self, wait_time=2):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                success_window = self.ui.get_dramasend_success_window()
                if success_window:
                    success_text = self.ui.get_dramasend_success_text()
                    if success_text and success_text.Name == '成功':
                        print("检测到传输剧本成功弹窗")
                        confirm_button = self.ui.get_dramasend_success_confirm_button()
                        confirm_button.Click()
                        print("已关闭传输剧本成功弹窗")
                        return True
            except:
                pass
            time.sleep(interval)
        return False

    def transmit_drama(self, drone_id, wait_time=10):
        try:
            drama_send_button = self.ui.get_drama_cfg_drama_send_button()
            drama_send_button.Click()
            print("已点击传输剧本面板按钮")
            time.sleep(0.5)

            transmit_button = self.ui.get_dramatransmit_transmit_button()
            transmit_button.Click()
            print("已点击传输剧本按钮")
            time.sleep(0.5)

            interval = 0.2
            transmit_task_window = None
            for _ in range(int(wait_time / interval)):
                try:
                    transmit_task_window = self.ui.get_transmit_task_window()
                    if transmit_task_window:
                        print("检测到传输剧本弹窗")
                        break
                except:
                    pass
                time.sleep(interval)

            if not transmit_task_window:
                print("未检测到传输剧本弹窗")
                return False

            all_transmit_button = transmit_task_window.ButtonControl(AutomationId='TransmitTask_AllTransmit_Button')
            all_transmit_button.Click()
            print("已点击全部传输按钮")
            time.sleep(0.5)

            success_closed = self.check_and_close_dramasend_success(wait_time=wait_time)
            if not success_closed:
                print("未检测到传输成功弹窗")
                return False
            print("传输剧本完成")

            row = self.ui.get_transmit_task_data_grid_row_by_drone_id(drone_id)
            if not row:
                print(f"未找到飞机 ID: {drone_id}")
                return False
            row.Click()
            print(f"已点击飞机 ID: {drone_id} 所在行")
            time.sleep(0.5)

            verify_button = self.ui.get_transmit_task_verify_button()
            verify_button.Click()
            print("已点击验证按钮")
            time.sleep(0.5)

            verify_success_closed = self.check_and_close_dramasend_success(wait_time=wait_time)
            if not verify_success_closed:
                print("未检测到验证成功弹窗")
                return False
            print(f"飞机 {drone_id} 验证完成")

            close_button = self.ui.get_transmit_task_close_button()
            close_button.Click()
            print("已关闭传输剧本弹窗")
            time.sleep(0.5)

            drama_send_button = self.ui.get_drama_cfg_drama_send_button()
            drama_send_button.Click()
            print("已关闭传输剧本面板")
            time.sleep(0.5)

            return True

        except Exception as e:
            print(f"传输剧本失败: {e}")
            return False

    def verify_drama_by_drone_id(self, drone_id, wait_time=10):
        try:
            interval = 0.2
            transmit_task_window = None
            for _ in range(int(wait_time / interval)):
                try:
                    transmit_task_window = self.ui.get_transmit_task_window()
                    if transmit_task_window:
                        print("检测到传输剧本弹窗")
                        break
                except:
                    pass
                time.sleep(interval)

            if not transmit_task_window:
                print("未检测到传输剧本弹窗")
                return False

            row = self.ui.get_transmit_task_data_grid_row_by_drone_id(drone_id)
            if not row:
                print(f"未找到飞机 ID: {drone_id}")
                return False
            row.Click()
            print(f"已点击飞机 ID: {drone_id} 所在行")
            time.sleep(0.5)

            verify_button = self.ui.get_transmit_task_verify_button()
            verify_button.Click()
            print("已点击验证按钮")
            time.sleep(0.5)

            success_closed = self.check_and_close_dramasend_success(wait_time=wait_time)
            if success_closed:
                print(f"飞机 {drone_id} 验证完成")
                return True
            else:
                print("未检测到验证成功弹窗")
                return False

        except Exception as e:
            print(f"验证剧本失败: {e}")
            return False

    def create_drama_uav_mapping_excel(self, drama_id, uav_ids, keep_file=False):
        if isinstance(uav_ids, str):
            uav_ids = [uav_ids]

        wb = xlwt.Workbook()
        ws = wb.add_sheet("Sheet1")

        def _to_num(val):
            try:
                return int(val)
            except (ValueError, TypeError):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return val

        for i, uav_id in enumerate(uav_ids):
            ws.write(i, 0, _to_num(drama_id))
            ws.write(i, 1, _to_num(uav_id))

        fd, tmp_path = tempfile.mkstemp(suffix=".xls", dir=tempfile.gettempdir())
        os.close(fd)
        wb.save(tmp_path)
        print(f"已生成临时Excel文件: {tmp_path}")

        if keep_file:
            return tmp_path
        else:
            try:
                os.remove(tmp_path)
                print(f"已删除临时Excel文件: {tmp_path}")
            except Exception as e:
                print(f"删除临时文件失败: {e}")
            return None

    def set_mapping_by_excel(self, drama_id, drone_id, wait_time=5):
        tmp_path = None
        try:
            tmp_path = self.create_drama_uav_mapping_excel(drama_id, drone_id, keep_file=True)
            if not tmp_path:
                print("生成临时Excel文件失败")
                return False

            mapset_button = self.ui.get_drama_cfg_mapset_button()
            mapset_button.Click()
            print("已点击设置映射按钮")
            time.sleep(0.5)

            load_xls_button = self.ui.get_mapping_set_load_xls_button()
            load_xls_button.Click()
            print("已点击加载xls按钮")
            time.sleep(0.5)

            interval = 0.2
            dialog_window = None
            for _ in range(int(wait_time / interval)):
                try:
                    dialog_window = self.ui.get_mapping_set_dialog_window()
                    if dialog_window:
                        print("检测到文件选择弹窗")
                        break
                except:
                    pass
                time.sleep(interval)

            if not dialog_window:
                print("未检测到文件选择弹窗")
                return False

            filename_edit = self.ui.get_mapping_set_dialog_filename_edit()
            self.ui.input_to_edit(filename_edit, tmp_path)
            print(f"已输入文件路径: {tmp_path}")
            time.sleep(0.2)

            open_button = self.ui.get_mapping_set_dialog_open_button()
            open_button.Click()
            print("已点击打开按钮")
            time.sleep(2)

            set_button = self.ui.get_mapping_set_set_button()
            set_button.Click()
            print("已点击设置按钮")
            time.sleep(0.5)

            print("通过Excel设置映射完成")
            return True

        except Exception as e:
            print(f"通过Excel设置映射失败: {e}")
            return False
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                    print(f"已删除临时Excel文件: {tmp_path}")
                except Exception as e:
                    print(f"删除临时文件失败: {e}")

            self.ui.switch_to_main_window()

    # 通用加载状态
    def check_loading_status(self, wait_time=30):
        interval = 0.2
        end_confirm_seconds = 2
        # 等待加载状态图片出现
        time.sleep(0.1)
        image = self.ui.get_loading_status_image()

        if not image.Exists(maxSearchSeconds=0.1):
            # 加载图片未出现，持续 2s 确认仍未出现
            absent_start = time.time()
            while time.time() - absent_start < end_confirm_seconds:
                if image.Exists(maxSearchSeconds=0.1):
                    # 期间出现 → 转入"等消失"流程
                    return self.check_loading_status(wait_time)
                time.sleep(interval)
            return True

        # 加载图片已出现，等到消失（最多 wait_time）
        appear_start = time.time()
        while time.time() - appear_start < wait_time:
            if not image.Exists(maxSearchSeconds=0.1):
                # 消失 → 持续 2s 确认加载界面结束
                gone_start = time.time()
                while time.time() - gone_start < end_confirm_seconds:
                    if image.Exists(maxSearchSeconds=0.1):
                        # 期间又出现，重置确认起点
                        gone_start = time.time()
                    time.sleep(interval)
                return True
            time.sleep(interval)

        print(f"加载界面存在超过{wait_time}s")
        return False
    
    # 通用 - 检查升级是否成功
    def check_update_status(self, current_versions, target_versions):
        result = True
        for current_version, target_version in  zip(current_versions, target_versions):
            if current_version != target_version:
                result = False
        return result
    
    # 帮助按钮相关
    def click_commonmenu_help_button(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                commonmenu_help_button = self.ui.get_commonmenu_help_button()
                commonmenu_help_button.Click()
                return True
            except Exception as e:
                print(f"点击帮助按钮失败: {e}")
            time.sleep(interval)
        return False
    
    # 帮助-检查测试更新按钮相关
    def click_commonmenu_help_check_betaversion_button(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                button = self.ui.get_commonmenu_help_check_betaversion_button()
                button.Click()
                if self.check_loading_status():
                # 检查30s内是否加载完成
                    return True
                else:
                    return False
            except Exception as e:
                print(f"点击检查测试更新失败: {e}")
            time.sleep(interval)
        return False
    
    # 帮助-检查更新按钮相关
    def click_commonmenu_help_check_officialversion_button(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                button = self.ui.get_commonmenu_help_check_officialversion_button()
                button.Click()
                if self.check_loading_status():
                # 检查30s内是否加载完成
                    return True
                else:
                    return False
            except Exception as e:
                print(f"点击检查测试更新失败: {e}")
            time.sleep(interval)
        return False
    
    # 帮助-检查更新窗口- 检查窗口状态
    def check_official_updates_window(self, wait_time=5):
        interval = 0.2
        # 缓存窗口定位器，避免每次循环都重新查找主窗口 + 查找更新窗口
        window = self.ui.get_check_official_updates_window()
        for _ in range(int(wait_time / interval)):
            if window.Exists():
                time.sleep(interval)
            else:
                return False
        return True

    # 帮助-检查测试更新窗口- 检查窗口状态
    def check_beta_updates_window(self, wait_time=5):
        interval = 0.2
        # 缓存窗口定位器，避免每次循环都重新查找主窗口 + 查找更新窗口
        window = self.ui.get_check_beta_updates_window()
        for _ in range(int(wait_time / interval)):
            if window.Exists():
                time.sleep(interval)
            else:
                return False
        return True
    
    # 帮助-检查更新窗口-飞机类型选取
    def click_official_updates_window_types_dataitem(self, uav_type, wait_time=1):
        interval = 0.2
        uav_dict_item, uav_dict = self.ui.get_check_official_updates_window_uav_group_types_data_items(uav_type=uav_type)
        for _ in range(int(wait_time / interval)):
            try:
                if uav_dict_item is None:
                    return False
                else:
                    # 翻页至目标飞机类型所在的页数
                    self.ui.send_pgdn_keybd(uav_dict_item.get('item_page'))
                    uav_dict_item.get('data_item').Click()
                    return True, uav_dict_item, uav_dict
            except Exception as e:
                print(f"点击飞机类型失败: {e}")
            time.sleep(interval)
        return False, None, None

    # 帮助-检查测试更新窗口-飞机类型选取
    def click_beta_updates_window_types_dataitem(self, uav_type, wait_time=1):
        interval = 0.2
        uav_dict_item, uav_dict = self.ui.get_check_beta_updates_window_uav_group_types_data_items(uav_type=uav_type)
        for _ in range(int(wait_time / interval)):
            try:
                if uav_dict_item is None:
                    return False
                else:
                    # 翻页至目标飞机类型所在的页数
                    self.ui.send_pgdn_keybd(uav_dict_item.get('item_page'))
                    uav_dict_item.get('data_item').Click()
                    return True, uav_dict_item, uav_dict
            except Exception as e:
                print(f"点击飞机类型失败: {e}")
            time.sleep(interval)
        return False, None, None
    
    # 帮助-检查更新窗口-飞控版本选取
    def click_official_updates_window_infos_dataitem(self, fc_version='latest', wait_time=1):
        interval = 0.2
        infos_dict_item, infos_dict = self.ui.get_check_official_updates_window_uav_group_infos_data_items(fc_update_version=fc_version)
        for _ in range(int(wait_time / interval)):
            try:
                if fc_version=='latest':
                    list(infos_dict.values())[0].get('data_item').Click()
                    return True
                elif infos_dict_item is None:
                    return False
                else:
                    # 翻页至目标飞机类型所在的页数
                    self.ui.send_pgdn_keybd(infos_dict_item.get('item_page'))
                    infos_dict_item.get('data_item').Click()
                    return True, infos_dict_item, infos_dict
            except Exception as e:
                print(f"点击飞控版本失败: {e}")
            time.sleep(interval)
        return False, None, None

    # 帮助-检查测试更新窗口-飞控版本选取
    def click_beta_updates_window_infos_dataitem(self, fc_version='latest', wait_time=1):
        interval = 0.2
        infos_dict_item, infos_dict = self.ui.get_check_beta_updates_window_uav_group_infos_data_items(fc_update_version=fc_version)
        for _ in range(int(wait_time / interval)):
            try:
                if fc_version=='latest':
                    list(infos_dict.values())[0].get('data_item').Click()
                    return True
                elif infos_dict_item is None:
                    return False
                else:
                    # 翻页至目标飞机类型所在的页数
                    self.ui.send_pgdn_keybd(infos_dict_item.get('item_page'))
                    infos_dict_item.get('data_item').Click()
                    return True, infos_dict_item, infos_dict
            except Exception as e:
                print(f"点击飞控版本失败: {e}")
            time.sleep(interval)
        return False, None, None
    
    # 帮助-检查更新窗口-下载使用按钮
    def click_official_updates_window_update_button(self, wait_time=60):
        update_button = self.ui.get_check_official_updates_window_uav_group_update_button()
        try:
            update_button.Click()
            if self.check_loading_status(wait_time=wait_time):
            # 检查60s内是否下载完成
                return True
            else:
                return False
        except:
            return False

    # 帮助-检查测试更新窗口-下载使用按钮
    def click_beta_updates_window_update_button(self, wait_time=60):
        update_button = self.ui.get_check_beta_updates_window_uav_group_update_button()
        try:
            update_button.Click()
            if self.check_loading_status(wait_time=wait_time):
            # 检查60s内是否下载完成
                return True
            else:
                return False
        except:
            return False

    # 帮助-检查更新窗口-全部更新按钮
    def click_official_updates_window_updateall_button(self):
        updateall_button = self.ui.get_check_official_updates_window_uav_group_updateall_button()
        try:
            updateall_button.Click()
        except:
            return False

        total_timeout = 180
        idle_threshold = 10
        interval = 0.2

        # 记录脚本开始时间戳；空闲计时起点
        start_time = time.time()
        idle_start = start_time

        loading_image = self.ui.get_loading_status_image()
        while True:
            now = time.time()
            if loading_image.Exists(maxSearchSeconds=0.1):
                # 检测到加载图片，重置空闲计时起点
                idle_start = now
            else:
                # 持续空闲时长 = 当前时间 - 空闲计时起点
                idle_elapsed = now - idle_start
                if idle_elapsed >= idle_threshold:
                    return True

            if now - start_time >= total_timeout:
                return False

            time.sleep(interval)

    # 帮助-检查测试更新窗口-全部更新按钮
    def click_beta_updates_window_updateall_button(self):
        updateall_button = self.ui.get_check_beta_updates_window_uav_group_updateall_button()
        try:
            updateall_button.Click()
        except:
            return False

        total_timeout = 180
        idle_threshold = 10
        interval = 0.2

        # 记录脚本开始时间戳；空闲计时起点
        start_time = time.time()
        idle_start = start_time

        loading_image = self.ui.get_loading_status_image()
        while True:
            now = time.time()
            if loading_image.Exists(maxSearchSeconds=0.1):
                # 检测到加载图片，重置空闲计时起点
                idle_start = now
            else:
                # 持续空闲时长 = 当前时间 - 空闲计时起点
                idle_elapsed = now - idle_start
                if idle_elapsed >= idle_threshold:
                    return True

            if now - start_time >= total_timeout:
                return False

            time.sleep(interval)

    # 帮助-检查更新窗口-关闭窗口按钮
    def click_official_updates_window_close_button(self):
        try:
            close_button = self.ui.get_check_official_updates_window_close_button()
            close_button.Click()
            if self.check_loading_status(wait_time=30):
            # 检查30s内是否加载界面消失
                if not self.check_official_updates_window():
                # 检查5s内是否窗口关闭
                    return True
                else:
                    return False
            else:
                return False
        except:
            return False

    # 帮助-检查测试更新窗口-关闭窗口按钮
    def click_beta_updates_window_close_button(self):
        try:
            close_button = self.ui.get_check_beta_updates_window_close_button()
            close_button.Click()
            if self.check_loading_status(wait_time=30):
            # 检查30s内是否加载界面消失
                if not self.check_beta_updates_window():
                # 检查5s内是否窗口关闭
                    return True
                else:
                    return False
            else:
                return False
        except:
            return False
        
    # 帮助-检查更新窗口-升级功能完整流程
    def click_official_updates_window_update_flow(self, uav_type, fc_version='latest'):
        interval = 0.2

        def _close_if_window_appears(timeout=15):
            """轮询 timeout 秒，若 official_updates_window 出现则执行关闭"""
            for _ in range(int(timeout / interval)):
                try:
                    if self.ui.get_check_official_updates_window().Exists():
                        self.click_official_updates_window_close_button()
                        return True
                except Exception:
                    pass
                time.sleep(interval)
            return False

        try:
            # Step1 按下帮助按钮
            if not self.click_commonmenu_help_button():
                return 'STEP1_FAILED: Failed to click Help button'

            # Step2 按下检查更新窗口按钮
            if not self.click_commonmenu_help_check_officialversion_button():
                _close_if_window_appears(timeout=15)
                return 'STEP2_FAILED: Failed to open Check Official Updates window'

            # Step3~5：异常时关闭 official_updates_window 后再返回
            try:
                result, current_types_dataitem, _ = self.click_official_updates_window_types_dataitem(uav_type=uav_type)
                if not result:
                    self.click_official_updates_window_close_button()
                    return 'STEP3_FAILED: Failed to select UAV type'
                result, current_infos_dataitem, _ = self.click_official_updates_window_infos_dataitem(fc_version=fc_version)
                if not result:
                    self.click_official_updates_window_close_button()
                    return 'STEP4_FAILED: Failed to select FC version'
                if not self.click_official_updates_window_update_button():
                    self.click_official_updates_window_close_button()
                    return 'STEP5_FAILED: Failed to click Update button'

                # Step5.5 升级后校验：types_dataitem.uav_version == infos_dataitem.fc_id
                try:
                    if not current_types_dataitem or not current_infos_dataitem:
                        self.click_official_updates_window_close_button()
                        return 'STEP5.5_FAILED: Failed to refetch data after upgrade'
                    new_uav_version = current_types_dataitem.get('uav_version')
                    new_fc_id = current_infos_dataitem.get('fc_id')
                    if new_uav_version != new_fc_id:
                        self.click_official_updates_window_close_button()
                        return f'STEP5.5_FAILED: Version mismatch after upgrade: uav_version={new_uav_version}, fc_id={new_fc_id}'
                except Exception as e:
                    self.click_official_updates_window_close_button()
                    return f'STEP5.5_EXCEPTION: {e}'
            except:
                pass

            # Step6 关闭 official_updates_window
            if not self.click_official_updates_window_close_button():
                return 'STEP6_FAILED: Failed to close official updates window'
            return 'SUCCESS'
        except:
            pass

    # 帮助-检查测试更新窗口-升级功能完整流程
    def click_beta_updates_window_update_flow(self, uav_type, fc_version='latest'):
        interval = 0.2

        def _close_if_window_appears(timeout=15):
            """轮询 timeout 秒，若 beta_updates_window 出现则执行关闭"""
            for _ in range(int(timeout / interval)):
                try:
                    if self.ui.get_check_beta_updates_window().Exists():
                        self.click_beta_updates_window_close_button()
                        return True
                except Exception:
                    pass
                time.sleep(interval)
            return False

        try:
            # Step1 按下帮助按钮
            if not self.click_commonmenu_help_button():
                return 'STEP1_FAILED: Failed to click Help button'

            # Step2 按下检查测试更新窗口按钮
            if not self.click_commonmenu_help_check_betaversion_button():
                _close_if_window_appears(timeout=15)
                return 'STEP2_FAILED: Failed to open Check Beta Updates window'

            # Step3~5：异常时关闭 beta_updates_window 后再返回
            try:
                result, current_types_dataitem, _ = self.click_beta_updates_window_types_dataitem(uav_type=uav_type)
                if not result:
                    self.click_beta_updates_window_close_button()
                    return 'STEP3_FAILED: Failed to select UAV type'
                result, current_infos_dataitem, _ = self.click_beta_updates_window_infos_dataitem(fc_version=fc_version)
                if not result:
                    self.click_beta_updates_window_close_button()
                    return 'STEP4_FAILED: Failed to select FC version'
                if not self.click_beta_updates_window_update_button():
                    self.click_beta_updates_window_close_button()
                    return 'STEP5_FAILED: Failed to click Update button'

                # Step5.5 升级后校验：types_dataitem.uav_version == infos_dataitem.fc_id
                try:
                    if not current_types_dataitem or not current_infos_dataitem:
                        self.click_beta_updates_window_close_button()
                        return 'STEP5.5_FAILED: Failed to refetch data after upgrade'
                    new_uav_version = current_types_dataitem.get('uav_version')
                    new_fc_id = current_infos_dataitem.get('fc_id')
                    if new_uav_version != new_fc_id:
                        self.click_beta_updates_window_close_button()
                        return f'STEP5.5_FAILED: Version mismatch after upgrade: uav_version={new_uav_version}, fc_id={new_fc_id}'
                except Exception as e:
                    self.click_beta_updates_window_close_button()
                    return f'STEP5.5_EXCEPTION: {e}'
            except:
                pass

            # Step6 关闭 beta_updates_window
            if not self.click_beta_updates_window_close_button():
                return 'STEP6_FAILED: Failed to close beta updates window'
            return 'SUCCESS'
        except:
            pass

    # 设置菜单相关
    def click_commonmenu_settings_button(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                netcard_set_window = self.ui.get_commonmenu_settings_button()
                netcard_set_window.Click()
                # print("已点击设置菜单")
                return True
            except Exception as e:
                print(f"点击设置菜单失败: {e}")
            time.sleep(interval)
        return False
    
    # 设置菜单相关 - 网卡设置菜单选项
    def click_commonmenu_settings_netcard_menuitem(self, wait_time=5):
        interval = 0.2
        appear_start = time.time()
        while time.time() - appear_start < wait_time:
            try:
                menuitem = self.ui.get_commonmenu_settings_netcard_menuitem()
                menuitem.Click()
                # print("已点击设置菜单-设置网卡")
                return True
            except Exception as e:
                print(f"点击设置菜单-设置网卡失败: {e}")
            time.sleep(interval)
        return False

    # 设置菜单相关 - 更新固件菜单选项
    def click_commonmenu_settings_updatefirmware_menuitem(self, wait_time=5):
        interval = 0.2
        appear_start = time.time()
        while time.time() - appear_start < wait_time:
            try:
                menuitem = self.ui.get_commonmenu_settings_updatefirmware_menuitem()
                menuitem.Click()
                return True
            except Exception as e:
                print(f"点击设置菜单-更新固件失败: {e}")
            time.sleep(interval)
        return False

    # 设置菜单相关 - 更新电池菜单选项
    def click_commonmenu_settings_updatebattery_menuitem(self, wait_time=5):
        interval = 0.2
        appear_start = time.time()
        while time.time() - appear_start < wait_time:
            try:
                menuitem = self.ui.get_commonmenu_settings_updatebattery_menuitem()
                menuitem.Click()
                return True
            except Exception as e:
                print(f"点击设置菜单-更新电池失败: {e}")
            time.sleep(interval)
        return False

    # 设置菜单相关 - 更新GPS菜单选项
    def click_commonmenu_settings_updategps_menuitem(self, wait_time=5):
        interval = 0.2
        appear_start = time.time()
        while time.time() - appear_start < wait_time:
            try:
                menuitem = self.ui.get_commonmenu_settings_updategps_menuitem()
                menuitem.Click()
                return True
            except Exception as e:
                print(f"点击设置菜单-更新GPS失败: {e}")
            time.sleep(interval)
        return False

    # 设置菜单相关 - 更新接收机菜单选项
    def click_commonmenu_settings_updatereceiver_menuitem(self, wait_time=5):
        interval = 0.2
        appear_start = time.time()
        while time.time() - appear_start < wait_time:
            try:
                menuitem = self.ui.get_commonmenu_settings_updatereceiver_menuitem()
                menuitem.Click()
                return True
            except Exception as e:
                print(f"点击设置菜单-更新接收机失败: {e}")
            time.sleep(interval)
        return False

    # 设置菜单相关 - 更新BMS菜单选项
    def click_commonmenu_settings_updatebms_menuitem(self, wait_time=5):
        interval = 0.2
        appear_start = time.time()
        while time.time() - appear_start < wait_time:
            try:
                menuitem = self.ui.get_commonmenu_settings_updatebms_menuitem()
                menuitem.Click()
                return True
            except Exception as e:
                print(f"点击设置菜单-更新BMS失败: {e}")
            time.sleep(interval)
        return False

    # 设置菜单相关 - 更新RID菜单选项
    def click_commonmenu_settings_updaterid_menuitem(self, wait_time=5):
        interval = 0.2
        appear_start = time.time()
        while time.time() - appear_start < wait_time:
            try:
                menuitem = self.ui.get_commonmenu_settings_updaterid_menuitem()
                menuitem.Click()
                return True
            except Exception as e:
                print(f"点击设置菜单-更新RID失败: {e}")
            time.sleep(interval)
        return False

    # 设置菜单相关 - 更新电台菜单选项
    def click_commonmenu_settings_updatestation_menuitem(self, wait_time=5):
        interval = 0.2
        appear_start = time.time()
        while time.time() - appear_start < wait_time:
            try:
                menuitem = self.ui.get_commonmenu_settings_updatestation_menuitem()
                menuitem.Click()
                return True
            except Exception as e:
                print(f"点击设置菜单-更新电台失败: {e}")
            time.sleep(interval)
        return False

    # 设置菜单相关 - 升级Boot菜单选项
    def click_commonmenu_settings_updateboot_menuitem(self, wait_time=5):
        interval = 0.2
        appear_start = time.time()
        while time.time() - appear_start < wait_time:
            try:
                menuitem = self.ui.get_commonmenu_settings_updateboot_menuitem()
                menuitem.Click()
                return True
            except Exception as e:
                print(f"点击设置菜单-升级Boot失败: {e}")
            time.sleep(interval)
        return False

    # 设置菜单相关 - USB更新固件菜单选项
    def click_commonmenu_settings_updateusb_menuitem(self, wait_time=5):
        interval = 0.2
        appear_start = time.time()
        while time.time() - appear_start < wait_time:
            try:
                menuitem = self.ui.get_commonmenu_settings_updateusb_menuitem()
                menuitem.Click()
                return True
            except Exception as e:
                print(f"点击设置菜单-USB更新固件失败: {e}")
            time.sleep(interval)
        return False

    # 更新固件窗口 - 关闭窗口按钮
    def click_updatefirmware_window_close_button(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                button = self.ui.get_updatefirmware_window_close_button()
                button.Click()
                return True
            except Exception as e:
                print(f"点击固件窗口[关闭]按钮失败: {e}")
            time.sleep(interval)
        return False

    # 更新固件窗口 - 最小化窗口按钮
    def click_updatefirmware_window_minimize_button(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                button = self.ui.get_updatefirmware_window_minimize_button()
                button.Click()
                return True
            except Exception as e:
                print(f"点击固件窗口[最小化]按钮失败: {e}")
            time.sleep(interval)
        return False    
    
    # 更新固件窗口 - 忽略离线选项
    def click_updatefirmware_window_ignoreoffline_checkbox(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                checkbox = self.ui.get_updatefirmware_window_ignoreoffline_checkbox()
                checkbox.Click()
                return True
            except Exception as e:
                print(f"点击固件窗口[忽略离线]勾选项失败: {e}")
            time.sleep(interval)
        return False   
    
    # 更新固件窗口 - 全部更新按钮
    def click_updatefirmware_window_allupdate_button(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                button = self.ui.get_updatefirmware_window_allupdate_button()
                button.Click()
                return True
            except Exception as e:
                print(f"点击固件窗口[全部更新]按钮失败: {e}")
            time.sleep(interval)
        return False  
    
    # 更新固件窗口 - 部分更新按钮
    def click_updatefirmware_window_partupdate_button(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                button = self.ui.get_updatefirmware_window_partupdate_button()
                button.Click()
                return True
            except Exception as e:
                print(f"点击固件窗口[部分更新]按钮失败: {e}")
            time.sleep(interval)
        return False  
    
    # 更新固件窗口 - 重试按钮
    def click_updatefirmware_window_retry_button(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                button = self.ui.get_updatefirmware_window_retry_button()
                button.Click()
                return True
            except Exception as e:
                print(f"点击固件窗口[重试]按钮失败: {e}")
            time.sleep(interval)
        return False  

    # 更新固件窗口 - 中止按钮
    def click_updatefirmware_window_cancel_button(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                button = self.ui.get_updatefirmware_window_cancel_button()
                button.Click()
                return True
            except Exception as e:
                print(f"点击固件窗口[中止]按钮失败: {e}")
            time.sleep(interval)
        return False  

    # 更新固件窗口 - 选取飞机
    def click_updatefirmware_window_data_grid_items(self,uav_id ,wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                select_item, _ = self.ui.get_updatefirmware_window_data_grid_items(uav_id=uav_id)
                select_item.get('data_item').Click()
                return True, select_item
            except Exception as e:
                print(f"点击固件窗口[选取飞机]失败: {e}")
            time.sleep(interval)
        return False, None 

    # 更新固件窗口 - 检查固件传输状态
    # 阶段1：progress_stage='File' 且 progress_percent='1' 开始 → progress_percent='100' 结束（阶段1→2 超时 3min）
    # 阶段2：progress_stage='Restart' 且 progress_message='成功'（阶段2→3 超时 1min）
    # 阶段3：progress_stage='Completely' 且 connect_state='DISCONNECTED'（阶段3→4 超时 6min）
    # 阶段4：connect_state='WORKING'（阶段4→5 超时 1min）
    # 阶段5：connect_state='FC_WORKING'（到达后认为传输完成，开始比对版本）
    # 升级后再读 current_version 与 new_version，相等则视为成功，返回 True
    # 字符串比较忽略大小写；未显式定义超时时间的阶段间过渡按 1min 处理
    def check_updatefirmware_window_update_status(self, uav_id, uav_item,
                                                    wait_time=1, default_timeout=60,
                                                    stage12_timeout=180, stage34_timeout=600):
        """
        监测固件升级全流程状态。

        Parameters
        ----------
        uav_id : str
            飞机标识（用于日志）。
        uav_item : dict
            单架飞机的状态字典，结构与 ``get_updatefirmware_window_data_grid_items``
            返回的 ``items_dict[uav_id]`` 一致：
              - ``current_version`` / ``connect_state`` / ``progress_stage`` /
                ``progress_percent`` / ``progress_message`` 均为
                ``{'value': Name, 'item': TextControl}``，本方法读取
                ``field['item'].Name`` 获取最新值。
              - ``new_version`` 为纯字符串。
        wait_time : float
            每次轮询间隔秒数，默认 1s。
        default_timeout : float
            未显式定义超时时间的阶段间过渡默认 60s。
        stage12_timeout : float
            阶段1→2（File 开始到 100%）超时秒数，默认 180s。
        stage34_timeout : float
            阶段3→4（DISCONNECTED 到 WORKING）超时秒数，默认 600s。

        Returns
        -------
        str
            升级成功时返回耗时字符串，格式 ``"XminYs"``（如 ``"3min25s"``）；
            失败时返回描述字符串，指明失败阶段及原因。
        """
        interval = 0.5

        def _eq(a, b):
            """忽略大小写比较。"""
            return str(a or "").strip().lower() == str(b or "").strip().lower()

        def _read_field(name):
            """读取 uav_item 中字段的当前 Name。

            若字段是 ``{'value', 'item'}`` 结构，返回 ``item.Name``；
            若为纯值字段（如 ``new_version``），直接返回该值；
            缺失或异常时返回空串。
            """
            field = uav_item.get(name)
            if field is None:
                return ""
            if isinstance(field, dict) and 'item' in field and field['item'] is not None:
                try:
                    return field['item'].Name or ""
                except Exception:
                    pass
            if isinstance(field, dict) and 'value' in field:
                return field['value'] or ""
            return field or ""

        def _read_row():
            """从 uav_item 重新读取一行所有列的最新 Name。"""
            return {
                'connect_state': _read_field('connect_state'),
                'current_version': _read_field('current_version'),
                'new_version': _read_field('new_version'),
                'progress_stage': _read_field('progress_stage'),
                'progress_percent': _read_field('progress_percent'),
                'progress_message': _read_field('progress_message'),
            }

        def _wait_for(predicate, timeout, label):
            """轮询直到 predicate(row_dict) 为 True 或超时。返回 (row, ok)。"""
            start = time.time()
            while time.time() - start < timeout:
                try:
                    row = _read_row()
                except Exception as e:
                    print(f"[{uav_id}] 读取固件行失败: {e}")
                    time.sleep(interval)
                    continue
                if predicate(row):
                    return row, True
                time.sleep(interval)
            print(f"[{uav_id}] {label} 超时（>{timeout:.0f}s）")
            return None, False

        # 升级前：读取初始 current_version / new_version
        try:
            before = _read_row()
            before_current = before['current_version']
            before_new = before['new_version']
        except Exception as e:
            print(f"[{uav_id}] 读取升级前版本失败: {e}")
            return f"读取升级前版本失败: {e}"
        print(f"[{uav_id}] 升级前 current_version={before_current!r}, new_version={before_new!r}")

        # 阶段1：等待 progress_stage='File' 且 progress_percent='1' 启动
        row, ok = _wait_for(
            lambda r: _eq(r['progress_stage'], 'File') and _eq(r['progress_percent'], '1'),
            default_timeout, "阶段1启动",
        )
        if not ok:
            return "阶段1启动超时（等待 progress_stage='File' 且 progress_percent='1'）"
        upgrade_start = time.time()

        # 阶段1结束：progress_percent='100'，阶段1→2 超时 stage12_timeout
        row, ok = _wait_for(
            lambda r: _eq(r['progress_percent'], '100'),
            stage12_timeout, "阶段1（File 100%）",
        )
        if not ok:
            return f"阶段1结束超时（等待 progress_percent='100'，已等待{stage12_timeout}s）"

        # 阶段2：progress_stage='Restart' 且 progress_message='成功'，阶段2→3 超时 default_timeout
        row, ok = _wait_for(
            lambda r: _eq(r['progress_stage'], 'Restart') and _eq(r['progress_message'], '成功'),
            default_timeout, "阶段2（Restart 成功）",
        )
        if not ok:
            return "阶段2超时（等待 progress_stage='Restart' 且 progress_message='成功'）"

        # 阶段3：progress_stage='Completely' 且 connect_state='DISCONNECTED'
        row, ok = _wait_for(
            lambda r: _eq(r['progress_stage'], 'Completely') and _eq(r['connect_state'], 'DISCONNECTED'),
            default_timeout, "阶段3（Completely + DISCONNECTED）",
        )
        if not ok:
            return "阶段3超时（等待 progress_stage='Completely' 且 connect_state='DISCONNECTED'）"

        # 阶段4：connect_state='WORKING'，阶段3→4 超时 stage34_timeout
        row, ok = _wait_for(
            lambda r: _eq(r['connect_state'], 'WORKING'),
            stage34_timeout, "阶段4（WORKING）",
        )
        if not ok:
            return f"阶段4超时（等待 connect_state='WORKING'，已等待{stage34_timeout}s）"

        # 阶段5：connect_state='FC_WORKING'，阶段4→5 超时 default_timeout
        row, ok = _wait_for(
            lambda r: _eq(r['connect_state'], 'FC_WORKING'),
            default_timeout, "阶段5（FC_WORKING）",
        )
        if not ok:
            return "阶段5超时（等待 connect_state='FC_WORKING'）"
        upgrade_elapsed = int(time.time() - upgrade_start)
        upgrade_duration = f"{upgrade_elapsed // 60}min{upgrade_elapsed % 60}s"

        # 升级后：再读一次 current_version / new_version，比较两者是否相等
        try:
            after = _read_row()
            after_current = after['current_version']
            after_new = after['new_version']
        except Exception as e:
            print(f"[{uav_id}] 读取升级后版本失败: {e}")
            return f"读取升级后版本失败: {e}"
        print(f"[{uav_id}] 升级后 current_version={after_current!r}, new_version={after_new!r}")

        if _eq(after_current, after_new):
            print(f"[{uav_id}] 升级成功（current_version == new_version），耗时 {upgrade_duration}")
            return upgrade_duration

        print(f"[{uav_id}] 升级失败：current_version({after_current!r}) != new_version({after_new!r})")
        return f"版本校验失败：current_version({after_current!r}) != new_version({after_new!r})"

    # 网卡设置相关
    def click_netcard_set_window(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                netcard_set_window = self.ui.get_netcard_set_window()
                netcard_set_window.Click()
                # print("已点击网卡窗口")
                return True
            except Exception as e:
                print(f"已点击网卡窗口: {e}")
            time.sleep(interval)
        return False

    def check_netcard_set_window(self):
        return self.ui.get_netcard_set_window().Exists()
            
    def click_netcard_set_combobox(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                netcard_set_combobox = self.ui.get_netcard_set_combobox()
                netcard_set_combobox.Click()
                # print("已点击网卡列表")
                return True
            except Exception as e:
                print(f"已点击网卡列表: {e}")
            time.sleep(interval)
        return False
        
    def select_netcard_set_listitem(self, name, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                set_netcard_set_listitem = self.ui.get_netcard_set_listitem(name=name)
                set_netcard_set_listitem.Click()
                # print(f"已点击选取网卡{name}")
                return True
            except Exception as e:
                print(f"已点击选取网卡: {e}")
            time.sleep(interval)
        return False
        
    def click_netcard_set_button(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                set_netcard_set_listitem = self.ui.get_netcard_set_button()
                set_netcard_set_listitem.Click()
                # print(f"已点击设置网卡")
                return True
            except Exception as e:
                print(f"已点击设置网卡: {e}")
            time.sleep(interval)
        return False

    # 其他菜单相关
    def get_othermenu_windspeed_info_text(self, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                windspeed_info = self.ui.get_othermenu_windspeed_info_text().Name
                # 文字颜色
                if check_text_color_red(self.ui.get_othermenu_windspeed_info_text())['exists_red']:
                    color = 'Red'
                else:
                    color = 'White'
                # 风向 (direction) - 匹配 '-xxx°' 或 'xxx°' (支持有符号方向)
                direction_match = re.search(r'(-?\d+)\s*°', windspeed_info)
                direction = int(direction_match.group(1)) if direction_match else None
                # 风速 (speed) - 匹配 'x.xm/s'
                speed_match = re.search(r'(\d+\.?\d+)\s*m/s', windspeed_info)
                speed = float(speed_match.group(1)) if speed_match else None
                # print(f"[TEST] 当前风速信息:风向{direction}°  风速{speed}m/s 字体颜色{color}")
                return direction, speed, color
            except Exception as e:
                print(f"[TEST] 当前风速信息: {e}")
            time.sleep(interval)
        return None, None, None
    
    def click_othermenu_language_switch_button(self, language, wait_time=5):
        interval = 0.2
        for _ in range(int(wait_time / interval)):
            try:
                othermenu_language_switch_button = self.ui.get_othermenu_language_switch_button()
                othermenu_language_switch_button.Click()
                if language == "English":
                    othermenu_english_menuitem = self.ui.get_othermenu_english_menuitem()
                elif language == "Chinese":
                    othermenu_english_menuitem = self.ui.get_othermenu_chinese_menuitem()
                else:
                    othermenu_english_menuitem = self.ui.get_othermenu_english_menuitem()
                othermenu_english_menuitem.Click()
                return True
            except Exception as e:
                print(f"未执行点击切换语言按钮: {e}")
            time.sleep(interval)
        return False
    
    # 风速告警相关
    def check_windspeed_warning_window(self):
        # 检查风速告警窗口是否存在
        return self.ui.get_windspeed_warning_iknow_button().Exists()
    
    def get_windspeed_warning_info(self, wait_time=5):
        # 获取风速告警文本信息
        interval = 1
        if self.check_windspeed_warning_window():
            try:
                windspeed_warning_text = self.ui.get_windspeed_warning_text().Name
                if '1 级告警风速' in windspeed_warning_text or '1 windspeed risk threshold' in windspeed_warning_text:
                    windspeed_warning_level = 1
                elif '2 级告警风速' in windspeed_warning_text or '2 windspeed risk threshold' in windspeed_warning_text:
                    windspeed_warning_level = 2
                elif '3 级告警风速' in windspeed_warning_text or '3 windspeed risk threshold' in windspeed_warning_text:
                    windspeed_warning_level = 3
                else:
                    return False, windspeed_warning_text
                
                return windspeed_warning_level, windspeed_warning_text
            except Exception as e:
                return False, None
        else:
            return False, None
    
    def click_windspeed_warning_iknow_window(self, wait_time=5):
        # 按下我知道了按钮
        interval = 1
        for _ in range(int(wait_time / interval)):
            try:
                netcard_set_window = self.ui.get_windspeed_warning_iknow_button()
                netcard_set_window.Click()
                print("[TEST] 已点击风速告警窗口-我知道了按钮")
                return True
            except Exception as e:
                print(f"[TEST] 未执行点击风速告警窗口-我知道了按钮: {e}")
            time.sleep(interval)
        return False
    
    def click_windspeed_warning_close_window(self, wait_time=5):
        # 按下关闭按钮
        interval = 1
        for _ in range(int(wait_time / interval)):
            try:
                netcard_set_window = self.ui.get_windspeed_warning_close_button()
                netcard_set_window.Click()
                print("[TEST] 已点击风速告警窗口-关闭按钮")
                return True
            except Exception as e:
                print(f"[TEST] 未执行点击风速告警窗口-关闭按钮: {e}")
            time.sleep(interval)
        return False
    