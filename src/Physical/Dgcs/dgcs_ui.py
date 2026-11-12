# -*- coding: utf-8 -*-
"""
dgcs_ui.py

UI 层模块：负责 DGCS 应用的驱动和所有 UI 控件的查找与基础操作。

本模块不包含业务流程逻辑，只提供与界面交互的原子能力，包括：
- 启动 / 查找 / 关闭 DGCS 进程
- 获取登录窗口、主控制窗口及各功能面板
- 对 Edit、Button、DataGrid 等控件的封装操作
- 通用辅助方法（清空输入框、获取控件值、切换窗口等）

典型用法：
    from dgcs_ui import DgcsUI
    ui = DgcsUI()
    ui.start_app()
    ui.dump_controls("controls.json")
"""

import json
import time
import os
import tempfile

import psutil
import uiautomation as auto
import subprocess
import ctypes
import xlwt

APP_PATH = "C:\\Program Files\\DGCS\\4.0\\DGCS.exe"


class DgcsUI:
    """
    UI 层：负责应用驱动和所有 UI 控件的查找与基础操作。
    不包含业务流程逻辑，只提供与界面交互的原子能力。
    """

    def __init__(self, app_path=APP_PATH):
        auto.SetGlobalSearchTimeout(10)
        self.app_path = app_path
        self.process_id = None
        self.main_window = None

    def start_app(self):
        existing_pid = self.find_existing_process()
        if existing_pid:
            print(f"DGCS 已经在运行，进程ID: {existing_pid}")
            self.process_id = existing_pid
            self._refresh_main_window()
            return True
        else:
            print("DGCS 未在运行，正在启动...")
            try:
                subprocess.Popen(APP_PATH)
                print(f"正在启动 DGCS 应用: {self.app_path}")
                for i in range(30):
                    if self.is_app_running():
                        self._refresh_main_window()
                        if self.main_window is not None:
                            self.process_id = self.find_existing_process()
                            return True
                    time.sleep(0.5)
                print("启动超时，请检查应用状态。")
                return False
            except Exception as e:
                import traceback
                print(f"启动 DGCS 应用失败: {e}")
                traceback.print_exc()
                return False

    def _refresh_main_window(self):
        root = auto.GetRootControl()
        for window in root.GetChildren():
            name = window.Name
            if name and ("DGCS " in name or "大漠大地面控制站" in name or "Dmd Ground Control Station" in name):
                self.main_window = window
                # 如果窗口状态为最小化，则点击任务栏窗口按钮，确认窗口被打开
                if window.GetWindowPattern().WindowVisualState == 2:
                    self.get_main_window_button().Click()
                # print(f"已附加到窗口: {name}")
                break
        else:
            self.main_window = None

    def find_existing_process(self):
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] and proc.info['name'].lower() == 'dgcs.exe':
                    return proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return None

    def is_app_running(self):
        return self.find_existing_process() is not None

    def terminate_process(self):
        if self.process_id:
            try:
                proc = psutil.Process(self.process_id)
                proc.terminate()
                proc.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
            except Exception as e:
                print(f"终止进程时出错: {e}")
            self.process_id = None

    def dump_controls(self, save_path="controls.json"):
        if self.main_window is None:
            print("未找到窗口，无法遍历控件")
            return {}

        def _traverse(control):
            try:
                name = control.Name
                controlTypeName = control.ControlTypeName
                automation_id = control.AutomationId
                className = control.ClassName
            except Exception:
                return None

            info = {
                "controlType": controlTypeName,
                "name": name,
                "automation_id": automation_id,
                "className": className,
                "children": []
            }

            try:
                children = control.GetChildren()
                for child in children:
                    child_info = _traverse(child)
                    if child_info:
                        info["children"].append(child_info)
            except Exception:
                pass

            return info

        controls_tree = _traverse(self.main_window)
        if controls_tree is None:
            return {}

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(controls_tree, f, ensure_ascii=False, indent=2)

        def _count_controls(node):
            if not node:
                return 0
            count = 1
            for child in node.get("children", []):
                count += _count_controls(child)
            return count

        total_count = _count_controls(controls_tree)
        print(f"共遍历 {total_count} 个控件，结果已保存到: {save_path}")
        return controls_tree

    # ---------- 窗口获取 ----------
    def get_login_window(self):
        if self.main_window is not None and "DGCS" in self.main_window.Name:
            return self.main_window
        return auto.WindowControl(Name='DGCS 4.0.9609.38000')

    def get_control_window(self):
        if self.main_window is not None and ("Dmd Ground Control Station" in self.main_window.Name or "大漠大地面控制站" in self.main_window.Name):
            return self.main_window
        else:
            self._refresh_main_window()
            if self.main_window is not None and ("Dmd Ground Control Station" in self.main_window.Name or "大漠大地面控制站" in self.main_window.Name):
                return self.main_window
            
    # ---------- 登录相关控件 ----------
    def get_login_close_button(self):
        return self.get_login_window().ButtonControl(AutomationId='CloseWindow')

    def get_login_username_edit(self):
        login_window = self.get_login_window()
        username_combobox = login_window.ComboBoxControl(AutomationId='Login_Username_ComboBox')
        return username_combobox.EditControl(AutomationId='PART_EditableTextBox')

    def get_login_password_edit(self):
        return self.get_login_window().EditControl(AutomationId='PART_PasswordBox')

    def get_login_submit_button(self):
        return self.get_login_window().ButtonControl(AutomationId='Login_Submit_Button')

    # ---------- 主控制窗口控件 ---------- 关闭应用按钮 ----------
    def get_control_close_button(self):
        return self.get_control_window().ButtonControl(AutomationId='MainWindow_TitleBar_Close_Button')
    
    # ---------- 主控制窗口控件 ---------- 关闭应用按钮 ---------- 询问窗口 ----------
    def get_close_mainwindow_confirm_window(self):
        root = auto.GetRootControl()
        return root.WindowControl(Name='询问')
    
    # ---------- 主控制窗口控件 ---------- 关闭应用按钮 ---------- 询问窗口 ---------- 关闭应用确定按钮 ----------
    def get_close_mainwindow_confirm_button(self):
        return self.get_close_mainwindow_confirm_window().ButtonControl(AutomationId='ConfirmButton')
    
    # ---------- 主控制窗口控件 ---------- 关闭应用按钮 ---------- 询问窗口 ---------- 关闭应用取消按钮 ----------
    def get_close_mainwindow_cancel_button(self):
        return self.get_close_mainwindow_confirm_window().ButtonControl(AutomationId='CancelButton')

    # ---------- 主控制窗口控件 ---------- 关闭应用按钮 ---------- 询问窗口 ---------- 关闭应用关闭按钮 ----------
    def get_close_mainwindow__close_button(self):
        return self.get_close_mainwindow_confirm_window().ButtonControl(LocalizedControlType='按钮')
    
    # ---------- 邻近项目警告弹窗 ----------
    def get_adjacent_project_warning_window(self):
        return self.get_control_window().WindowControl(Name='检测到邻近表演项目 - 请注意避让')

    # ---------- 原点设置面板 ----------
    def get_origin_set_panel(self):
        return self.get_control_window().CustomControl(className='OriginSet')

    def get_origin_set_uavid_edit(self):
        origin_set = self.get_origin_set_panel()
        uavid_combobox = origin_set.ComboBoxControl(AutomationId='OriginSet_UavId_ComboBox')
        return uavid_combobox.EditControl(AutomationId='PART_EditableTextBox')

    def get_origin_set_refresh_button(self):
        return self.get_origin_set_panel().ButtonControl(AutomationId='OriginSet_Refresh_Button')

    def get_origin_set_longitude_edit(self):
        return self.get_origin_set_panel().EditControl(AutomationId='OriginSet_Longitude_NumericBox')

    def get_origin_set_latitude_edit(self):
        return self.get_origin_set_panel().EditControl(AutomationId='OriginSet_Latitude_NumericBox')

    def get_origin_set_set_button(self):
        return self.get_origin_set_panel().ButtonControl(AutomationId='OriginSet_Set_Button')

    def get_origin_set_apply_button(self):
        return self.get_origin_set_panel().ButtonControl(AutomationId='OriginSet_Apply_Button')

    # ---------- 时间设置面板 ----------
    def get_time_set_panel(self):
        return self.get_control_window().CustomControl(className='TimeSet')

    def get_time_set_auto_generate_button(self):
        return self.get_time_set_panel().ButtonControl(AutomationId='RelativeTime_AutoGenerate_Button')

    def get_time_set_set_time_button(self):
        return self.get_time_set_panel().ButtonControl(AutomationId='RelativeTime_SetTime_Button')

    # ---------- 剧本配置菜单 ----------
    def get_drama_cfg_origin_button(self):
        return self.get_control_window().ButtonControl(AutomationId='DramaCfgMenu_Origin_ToggleButton')

    def get_drama_cfg_dramaload_button(self):
        return self.get_control_window().ButtonControl(AutomationId='DramaCfgMenu_DramaLoad_ToggleButton')

    def get_drama_cfg_mapset_button(self):
        return self.get_control_window().ButtonControl(AutomationId='DramaCfgMenu_MapSet_ToggleButton')

    def get_drama_cfg_timeset_button(self):
        return self.get_control_window().ButtonControl(AutomationId='DramaCfgMenu_TimeSet_ToggleButton')

    def get_drama_cfg_drama_send_button(self):
        return self.get_control_window().ButtonControl(AutomationId='DramaCfgMenu_DramaSend_ToggleButton')

    # ---------- 传输剧本面板 ----------
    def get_dramatransmit_panel(self):
        control_window = self.get_control_window()
        dramatransmit_window = control_window.WindowControl(className='Window')
        return dramatransmit_window.CustomControl(className='DramaTransmit')

    def get_dramatransmit_transmit_button(self):
        return self.get_dramatransmit_panel().ButtonControl(AutomationId='DramaTransmit_Transmit_Button')

    # ---------- 剧本加载面板 ----------
    def get_dramaload_panel(self):
        control_window = self.get_control_window()
        dramaload_window = control_window.WindowControl(className='Window')
        return dramaload_window.CustomControl(className='DramaLoad')

    def get_dramaload_land_button(self):
        return self.get_dramaload_panel().ButtonControl(AutomationId='DramaLoad_Land_ToggleButton')

    def get_dramaload_drama_button(self):
        return self.get_dramaload_panel().ButtonControl(AutomationId='DramaLoad_Drama_ToggleButton')

    def get_dramaload_takeoff_button(self):
        return self.get_dramaload_panel().ButtonControl(AutomationId='DramaLoad_Takeoff_ToggleButton')

    def get_dramaload_music_button(self):
        return self.get_dramaload_panel().ButtonControl(AutomationId='DramaLoad_Music_ToggleButton')

    def get_dramaload_load_button(self):
        return self.get_dramaload_panel().ButtonControl(AutomationId='DramaLoad_Load_Button')

    def get_dramaload_delete_button(self):
        return self.get_dramaload_panel().ButtonControl(AutomationId='DramaLoad_Delete_Button')

    def get_dramaload_info_edit(self):
        return self.get_dramaload_panel().EditControl(AutomationId='DramaLoad_Info_TextBox')

    def get_dramaload_dialog_window(self):
        control_window = self.get_control_window()
        child_window = control_window.WindowControl(className='Window')
        return child_window.WindowControl(Name='剧本', ClassName='#32770')

    def get_dramaload_dialog_filename_edit(self):
        return self.get_dramaload_dialog_window().EditControl(AutomationId='1148')

    def get_dramaload_dialog_open_button(self):
        return self.get_dramaload_dialog_window().ButtonControl(AutomationId='1')

    # ---------- 无人机视图 ----------
    def get_uav_view_menu_list_button(self):
        return self.get_control_window().ButtonControl(AutomationId='UavViewMenu_ListView_ToggleButton')

    def get_uav_view_menu_drone_button(self, drone_id):
        control_window = self.get_control_window()
        uav_view_menu_list_window = control_window.WindowControl(className='Window')
        uav_view_menu_list_control = uav_view_menu_list_window.CustomControl(className='UavListView')
        uav_view_menu_list_data_grid = uav_view_menu_list_control.DataGridControl(AutomationId='UavListView_Uav_DataGrid')
        try:
            return uav_view_menu_list_data_grid.DataItemControl(name=drone_id)
        except:
            return None

    def get_uav_view_menu_drone_detail_info(self):
        control_window = self.get_control_window()
        uav_view_menu_list_window = control_window.WindowControl(className='Window')
        uav_view_menu_list_control = uav_view_menu_list_window.CustomControl(className='UavListView')
        return uav_view_menu_list_control.CustomControl(AutomationId='detailInfo')

    # ---------- 参数配置 ----------
    def get_drone_param_config_button(self):
        return self.get_control_window().ButtonControl(AutomationId='ControlMenu_ParamConfig_ToggleButton')

    def get_drone_param_config_panel(self):
        return self.get_control_window().CustomControl(className='ParamConfig')

    def get_drone_param_config_name_edit(self):
        param_config = self.get_drone_param_config_panel()
        return param_config.ComboBoxControl(AutomationId='ParamConfig_ParamName_ComboBox').EditControl(AutomationId='PART_EditableTextBox')

    def get_drone_param_config_list_item(self, name):
        param_config = self.get_drone_param_config_panel()
        try:
            return param_config.ComboBoxControl(AutomationId='ParamConfig_ParamName_ComboBox').ListItemControl(name=name)
        except:
            return None

    def get_drone_param_config_pop_name(self, name):
        return self.get_control_window().CustomControl(className='Popup').PaneControl(className='ScrollViewer').ListItemControl(name=name)

    def get_drone_param_config_read_button(self):
        return self.get_drone_param_config_panel().ButtonControl(AutomationId='ParamConfig_Read_Button')

    def get_drone_param_config_set_button(self):
        return self.get_drone_param_config_panel().ButtonControl(AutomationId='ParamConfig_Set_Button')

    def get_drone_param_config_select_failed_uav_button(self):
        return self.get_drone_param_config_panel().ButtonControl(AutomationId='ParamConfig_SelectFailedUav_Button')

    def get_drone_param_config_set_all_button(self):
        return self.get_drone_param_config_panel().ButtonControl(AutomationId='ParamConfig_SetAll_Button')

    def get_drone_param_config_read_all_button(self):
        return self.get_drone_param_config_panel().ButtonControl(AutomationId='ParamConfig_ReadAll_Button')

    def get_drone_param_config_value_edit(self):
        return self.get_drone_param_config_panel().EditControl(AutomationId='ParamConfig_ParamValue_NumericBox')

    # ---------- 传输剧本成功弹窗 ----------
    def get_dramasend_success_window(self):
        return self.get_control_window().WindowControl(Name='提示')

    def get_dramasend_success_text(self):
        return self.get_dramasend_success_window().TextControl(AutomationId='MessageTextBlock')

    def get_dramasend_success_confirm_button(self):
        return self.get_dramasend_success_window().ButtonControl(AutomationId='ConfirmButton')

    # ---------- 传输任务弹窗 ----------
    def get_transmit_task_window(self):
        return self.get_control_window().WindowControl(Name='传输剧本->1')

    def get_transmit_task_select_failed_button(self):
        return self.get_transmit_task_window().ButtonControl(AutomationId='TransmitTask_SelectFailed_Button')

    def get_transmit_task_mark_failed_button(self):
        return self.get_transmit_task_window().ButtonControl(AutomationId='TransmitTask_MarkFailed_Button')

    def get_transmit_task_all_transmit_button(self):
        return self.get_transmit_task_window().ButtonControl(AutomationId='TransmitTask_AllTransmit_Button')

    def get_transmit_task_retry_button(self):
        return self.get_transmit_task_window().ButtonControl(AutomationId='TransmitTask_Retry_Button')

    def get_transmit_task_part_transmit_button(self):
        return self.get_transmit_task_window().ButtonControl(AutomationId='TransmitTask_PartTransmit_Button')

    def get_transmit_task_verify_button(self):
        return self.get_transmit_task_window().ButtonControl(AutomationId='TransmitTask_Verify_Button')

    def get_transmit_task_abort_button(self):
        return self.get_transmit_task_window().ButtonControl(AutomationId='TransmitTask_Abort_Button')

    def get_transmit_task_close_button(self):
        return self.get_transmit_task_window().ButtonControl(AutomationId='CloseWindow')

    def get_transmit_task_data_grid(self):
        return self.get_transmit_task_window().DataGridControl(AutomationId='TransmitTask_Transmit_DataGrid')

    def get_transmit_task_data_grid_row_by_drone_id(self, drone_id):
        data_grid = self.get_transmit_task_data_grid()
        for row in data_grid.GetChildren():
            if row.ControlTypeName == 'DataItemControl':
                for cell in row.GetChildren():
                    if cell.ControlTypeName == 'CustomControl' and cell.ClassName == 'DataGridCell':
                        if cell.Name == str(drone_id):
                            return row
        return None

    # ---------- 设置映射 ----------
    def get_mapping_set_window(self):
        return self.get_control_window().WindowControl(Name='设置映射')

    def get_mapping_set_load_xls_button(self):
        return self.get_mapping_set_window().ButtonControl(AutomationId='MappingSet_LoadXls_Button')

    def get_mapping_set_remove_button(self):
        return self.get_mapping_set_window().ButtonControl(AutomationId='MappingSet_Remove_Button')

    def get_mapping_set_all_auto_map_button(self):
        return self.get_mapping_set_window().ButtonControl(AutomationId='MappingSet_AllAutoMap_Button')

    def get_mapping_set_append_map_button(self):
        return self.get_mapping_set_window().ButtonControl(AutomationId='MappingSet_AppendMap_Button')

    def get_mapping_set_set_button(self):
        return self.get_mapping_set_window().ButtonControl(AutomationId='MappingSet_Set_Button')

    def get_mapping_set_alternate_uav_button(self):
        return self.get_mapping_set_window().ButtonControl(AutomationId='MappingSet_AlternateUav_Button')

    def get_mapping_set_replace_uav_button(self):
        return self.get_mapping_set_window().ButtonControl(AutomationId='MappingSet_ReplaceUav_Button')

    def get_mapping_set_dialog_window(self):
        control_window = self.get_control_window()
        child_window = control_window.WindowControl(ClassName='Window')
        return child_window.WindowControl(ClassName='#32770')

    def get_mapping_set_dialog_filename_edit(self):
        return self.get_mapping_set_dialog_window().EditControl(AutomationId='1148')

    def get_mapping_set_dialog_open_button(self):
        return self.get_mapping_set_dialog_window().ButtonControl(AutomationId='1')
    
    # ---------- 加载界面 ----------
    def get_loading_status_image(self):
        return self.get_control_window().ImageControl(AutomationId='Utils_Loading_StatusImage')
    
    # ---------- 帮助按钮 ----------
    def get_commonmenu_help_button(self):
        return self.get_control_window().ButtonControl(AutomationId='CommonMenu_Help_Button')
    
    # ---------- 帮助按钮 ---------- 检查更新菜单选项----------
    def get_commonmenu_help_check_officialversion_button(self):
        return self.get_control_window().MenuItemControl(AutomationId='CommonMenu_Help_CheckOfficialVersion_MenuItem')
    
    # ---------- 帮助按钮 ---------- 检查测试菜单选项----------
    def get_commonmenu_help_check_betaversion_button(self):
        return self.get_control_window().MenuItemControl(AutomationId='CommonMenu_Help_CheckBetaVersion_MenuItem')
    
    # ---------- 帮助按钮 ---------- 关于菜单选项----------
    def get_commonmenu_help_about_button(self):
        return self.get_control_window().MenuItemControl(AutomationId='CommonMenu_Help_About_MenuItem')
    
    # ---------- 检查正式版更新窗口 ----------
    def get_check_official_updates_window(self):
        main_window = self.get_control_window()
        if "大漠大地面控制站" in main_window.Name:
            return main_window.WindowControl(Name='检查更新')
        else:
            return main_window.WindowControl(Name='Check Official Updates')

    # ---------- 检查正式版更新窗口 ---------- 关闭按钮----------
    def get_check_official_updates_window_close_button(self):
        return self.get_check_official_updates_window().ButtonControl(AutomationId='CloseWindow')

    # ---------- 检查正式版更新窗口 ---------- 最小化按钮----------
    def get_check_official_updates_window_minimize_button(self):
        return self.get_check_official_updates_window().ButtonControl(AutomationId='MinimizeButton')

    # ---------- 检查正式版更新窗口 ---------- DGCS组----------
    def get_check_official_updates_window_dgcs_group(self):
        return self.get_check_official_updates_window().GroupControl(Name='DGCS')

    # ---------- 检查正式版更新窗口 ---------- DGCS组---------- 更新DGCS按钮----------
    def get_check_official_updates_window_dgcs_group_update_button(self):
        return self.get_check_official_updates_window_dgcs_group().ButtonControl(AutomationId='UpdateDgcs_Update_Button')

    # ---------- 检查正式版更新窗口 ---------- DGCS组---------- 新版本文本----------
    def get_check_official_updates_window_dgcs_group_latestversion_text(self):
        return self.get_check_official_updates_window_dgcs_group().TextControl(AutomationId='UpdateDgcs_LatestVersion_TextBlock')

    # ---------- 检查正式版更新窗口 ---------- DGCS组---------- 当前版本文本----------
    def get_check_official_updates_window_dgcs_group_currentversion_text(self):
        return self.get_check_official_updates_window_dgcs_group().TextControl(AutomationId='UpdateDgcs_CurrentVersion_TextBlock')

    # ---------- 检查正式版更新窗口 ---------- 飞机组件组
    def get_check_official_updates_window_uav_group(self):
        main_window = self.get_control_window()
        if "大漠大地面控制站" in main_window.Name:
            return self.get_check_official_updates_window().GroupControl(Name='飞机组件')
        else:
            return self.get_check_official_updates_window().GroupControl(Name='UAV Components')

    # ---------- 检查正式版更新窗口 ---------- 飞机组件组---------- 单个飞控更新按钮----------
    def get_check_official_updates_window_uav_group_update_button(self):
        return self.get_check_official_updates_window_uav_group().ButtonControl(AutomationId='UpdateDgcs_DownloadToUse_Button')

    # ---------- 检查正式版更新窗口 ---------- 飞机组件组---------- 全部飞控更新按钮----------
    def get_check_official_updates_window_uav_group_updateall_button(self):
        return self.get_check_official_updates_window_uav_group().ButtonControl(AutomationId='UpdateDgcs_UpdateAll_Button')

    # ---------- 检查正式版更新窗口 ---------- 飞机组件组---------- 待升级飞机数据网格----------
    def get_check_official_updates_window_uav_group_types_data(self):
        return self.get_check_official_updates_window_uav_group().DataGridControl(AutomationId='UpdateDgcs_ComponentTypes_DataGrid')

    # ---------- 检查正式版更新窗口 ---------- 飞机组件组---------- 待升级飞机数据网格---------- 飞机类型----------
    # 获取待升级飞机数据网格中的所有飞机类型项，包括飞机类型、版本号、更新状态
    # 返回字典结构: {飞机类型名称: {'data_item': DataGridRow对象, 'uav_version': 版本号, 'uav_update_status': 是否选中}}
    def get_check_official_updates_window_uav_group_types_data_items(self, uav_type, max_pages=100):
        uav_dict = {}

        # 获取待升级飞机数据网格控件
        data = self.get_check_official_updates_window_uav_group_types_data()
        # 初始化页数
        item_page = 1
        # 初始化翻页选中Row_Count
        count_limit = 19
        # 防止翻页失败或数据无限增长时陷入死循环
        page_count = 0
        while page_count < max_pages:
            page_count += 1
            # 获取当前页所有 DataGridRow
            data_children = data.GetChildren()
            page_has_new_item = False
            new_item_count = 0
            for data_grid_row in data_children:
                # 筛选出DataGridRow类型的行（每行代表一个飞机类型）
                if data_grid_row.ClassName == 'DataGridRow':
                    data_grid_row_children = data_grid_row.GetChildren()
                    # 防止索引越界：子控件数必须能覆盖到下标 3
                    assert len(data_grid_row_children) > 3, f"飞机类型行子控件数量不足: {len(data_grid_row_children)}"
                    uav_type_name = data_grid_row_children[1].Name
                    # 检查是否已存在（避免重复添加）
                    if uav_type_name not in uav_dict:
                        page_has_new_item = True
                        new_item_count += 1
                        uav_dict_item = {
                            uav_type_name: {
                                'data_item': data_grid_row,
                                'uav_version': data_grid_row_children[2].Name,
                                'uav_update_status': (data_grid_row_children[3].CheckBoxControl(ClassName='CheckBox').GetLegacyIAccessiblePattern().State == 0x10),
                                'item_page': item_page
                            }
                        }
                        uav_dict.update(uav_dict_item)

                    # 当达到第19个时，翻到下一页
                    if new_item_count >= count_limit:
                        # 收集完当前页后，点击最后一个控件触发翻页
                        data_grid_row.Click()
                        time.sleep(0.1)
                        self.send_pgdn_keybd()
                        time.sleep(0.2)
                        item_page += 1
                        new_item_count = 0
                        # 因为会有一个Row在列表显示区域外，把循环次数改为18
                        count_limit = 18
                        break

            # 本页无新增控件，退出循环
            if not page_has_new_item:
                if not uav_dict:
                    # 没有可升级飞机类型，不点击任何行
                    break
                if len(uav_dict) <= 19:
                    list(uav_dict.values())[0].get('data_item').Click()
                else:
                    self.send_pgup_keybd(times=item_page)
                break

        return uav_dict.get(uav_type), uav_dict

    # ---------- 检查正式版更新窗口 ---------- 飞机组件组---------- 选中飞机数据网格----------
    def get_check_official_updates_window_uav_group_infos_data(self):
        return self.get_check_official_updates_window_uav_group().DataGridControl(AutomationId='UpdateDgcs_ComponentInfos_DataGrid')

    # ---------- 检查正式版更新窗口 ---------- 飞机组件组---------- 选中飞机数据网格---------- 飞控版本----------
    def get_check_official_updates_window_uav_group_infos_data_items(self, fc_update_version, max_pages=100):
        infos_dict = {}

        # 获取待升级飞机数据网格控件
        data = self.get_check_official_updates_window_uav_group_infos_data()
        # 初始化页数
        item_page = 1
        # 初始化翻页选中Row_Count
        count_limit = 19
        # 防止翻页失败或数据无限增长时陷入死循环
        page_count = 0
        while page_count < max_pages:
            page_count += 1
            # 获取当前页所有 DataGridRow
            data_children = data.GetChildren()
            page_has_new_item = False
            new_item_count = 0
            for data_grid_row in data_children:
                if data_grid_row.ClassName == 'DataGridRow':
                    data_grid_row_children = data_grid_row.GetChildren()
                    # 防止索引越界：子控件数必须能覆盖到下标 10
                    assert len(data_grid_row_children) > 10, f"飞机信息行子控件数量不足: {len(data_grid_row_children)}"
                    fc_version = data_grid_row_children[2].Name
                    # 检查是否已存在（避免重复添加）
                    if fc_version not in infos_dict:
                        page_has_new_item = True
                        new_item_count += 1
                        infos_dict_item = {
                            fc_version: {
                                'data_item': data_grid_row,
                                'fc_id': data_grid_row_children[1].Name,
                                'component_version': data_grid_row_children[3].Name,
                                'battery_version': data_grid_row_children[4].TextControl(ClassName='TextBlock').Name,
                                'gps_version': data_grid_row_children[5].Name,
                                'rs_version': data_grid_row_children[6].Name,
                                'receiver_version': data_grid_row_children[7].TextControl(ClassName='TextBlock').Name,
                                'bms_version': data_grid_row_children[8].TextControl(ClassName='TextBlock').Name,
                                'rid_version': data_grid_row_children[9].TextControl(ClassName='TextBlock').Name,
                                'remark': data_grid_row_children[10].TextControl(ClassName='TextBlock').Name,
                                'item_page': item_page
                            }
                        }
                        infos_dict.update(infos_dict_item)

                    # 当达到第19个时，翻到下一页
                    if new_item_count >= count_limit:
                        # 收集完当前页后，点击最后一个控件触发翻页
                        data_grid_row.Click()
                        time.sleep(0.1)
                        self.send_pgdn_keybd()
                        time.sleep(0.2)
                        item_page += 1
                        new_item_count = 0
                        # 因为会有一个Row在列表显示区域外，把循环次数改为18
                        count_limit = 18
                        break

            # 本页无新增控件，退出循环
            if not page_has_new_item:
                if not infos_dict:
                    # 没有可升级飞机，不点击任何行
                    break
                if len(infos_dict) <= 19:
                    list(infos_dict.values())[0].get('data_item').Click()
                else:
                    self.send_pgup_keybd(times=item_page)
                break

        return infos_dict.get(fc_update_version), infos_dict

    # ---------- 检查测试更新窗口 ----------
    def get_check_beta_updates_window(self):
        main_window = self.get_control_window()
        if "大漠大地面控制站" in main_window.Name:
            return main_window.WindowControl(Name='检查测试更新')
        else:
            return main_window.WindowControl(Name='Check Beta Updates')
    
    # ---------- 检查测试更新窗口 ---------- 关闭按钮----------
    def get_check_beta_updates_window_close_button(self):
        return self.get_check_beta_updates_window().ButtonControl(AutomationId='CloseWindow')
    
    # ---------- 检查测试更新窗口 ---------- 最小化按钮----------
    def get_check_beta_updates_window_minimize_button(self):
        return self.get_check_beta_updates_window().ButtonControl(AutomationId='MinimizeButton')
    
    # ---------- 检查测试更新窗口 ---------- DGCS组----------
    def get_check_beta_updates_window_dgcs_group(self):
        return self.get_check_beta_updates_window().GroupControl(Name='DGCS')
    
    # ---------- 检查测试更新窗口 ---------- DGCS组---------- 更新DGCS按钮---------- 
    def get_check_beta_updates_window_dgcs_group_update_button(self):
        return self.get_check_beta_updates_window_dgcs_group().ButtonControl(AutomationId='UpdateDgcs_Update_Button')
    
    # ---------- 检查测试更新窗口 ---------- DGCS组---------- 新版本文本---------- 
    def get_check_beta_updates_window_dgcs_group_latestversion_text(self):
        return self.get_check_beta_updates_window_dgcs_group().TextControl(AutomationId='UpdateDgcs_LatestVersion_TextBlock')
    
    # ---------- 检查测试更新窗口 ---------- DGCS组---------- 当前版本文本---------- 
    def get_check_beta_updates_window_dgcs_group_currentversion_text(self):
        return self.get_check_beta_updates_window_dgcs_group().TextControl(AutomationId='UpdateDgcs_CurrentVersion_TextBlock')
    
    # ---------- 检查测试更新窗口 ---------- 飞机组件组
    def get_check_beta_updates_window_uav_group(self):
        main_window = self.get_control_window()
        if "大漠大地面控制站" in main_window.Name:
            return self.get_check_beta_updates_window().GroupControl(Name='飞机组件')
        else:
            return self.get_check_beta_updates_window().GroupControl(Name='UAV Components')
    
    # ---------- 检查测试更新窗口 ---------- 飞机组件组---------- 单个飞控更新按钮---------- 
    def get_check_beta_updates_window_uav_group_update_button(self):
        return self.get_check_beta_updates_window_uav_group().ButtonControl(AutomationId='UpdateDgcs_DownloadToUse_Button')

    # ---------- 检查测试更新窗口 ---------- 飞机组件组---------- 全部飞控更新按钮---------- 
    def get_check_beta_updates_window_uav_group_updateall_button(self):
        return self.get_check_beta_updates_window_uav_group().ButtonControl(AutomationId='UpdateDgcs_UpdateAll_Button')
    
    # ---------- 检查测试更新窗口 ---------- 飞机组件组---------- 待升级飞机数据网格----------
    def get_check_beta_updates_window_uav_group_types_data(self):
        return self.get_check_beta_updates_window_uav_group().DataGridControl(AutomationId='UpdateDgcs_ComponentTypes_DataGrid')
    
    # ---------- 检查测试更新窗口 ---------- 飞机组件组---------- 待升级飞机数据网格---------- 飞机类型----------
    # 获取待升级飞机数据网格中的所有飞机类型项，包括飞机类型、版本号、更新状态
    # 返回字典结构: {飞机类型名称: {'data_item': DataGridRow对象, 'uav_version': 版本号, 'uav_update_status': 是否选中}}
    def get_check_beta_updates_window_uav_group_types_data_items(self, uav_type, max_pages=100):
        uav_dict = {}

        # 获取待升级飞机数据网格控件
        data = self.get_check_beta_updates_window_uav_group_types_data()
        # 初始化页数
        item_page = 1
        # 初始化翻页选中Row_Count
        count_limit = 19
        # 防止翻页失败或数据无限增长时陷入死循环
        page_count = 0
        while page_count < max_pages:
            page_count += 1
            # 获取当前页所有 DataGridRow
            data_children = data.GetChildren()
            page_has_new_item = False
            new_item_count = 0
            for data_grid_row in data_children:
                # 筛选出DataGridRow类型的行（每行代表一个飞机类型）
                if data_grid_row.ClassName == 'DataGridRow':
                    data_grid_row_children = data_grid_row.GetChildren()
                    # 防止索引越界：子控件数必须能覆盖到下标 3
                    assert len(data_grid_row_children) > 3, f"飞机类型行子控件数量不足: {len(data_grid_row_children)}"
                    uav_type_name = data_grid_row_children[1].Name
                    # 检查是否已存在（避免重复添加）
                    if uav_type_name not in uav_dict:
                        page_has_new_item = True
                        new_item_count += 1
                        uav_dict_item = {
                            uav_type_name: {
                                'data_item': data_grid_row,
                                'uav_version': data_grid_row_children[2].Name,
                                'uav_update_status': (data_grid_row_children[3].CheckBoxControl(ClassName='CheckBox').GetLegacyIAccessiblePattern().State == 0x10),
                                'item_page': item_page
                            }
                        }
                        uav_dict.update(uav_dict_item)

                    # 当达到第19个时，翻到下一页
                    if new_item_count >= count_limit:
                        # 收集完当前页后，点击最后一个控件触发翻页
                        data_grid_row.Click()
                        time.sleep(0.1)
                        self.send_pgdn_keybd()
                        time.sleep(0.2)
                        item_page += 1
                        new_item_count = 0
                        # 因为会有一个Row在列表显示区域外，把循环次数改为18
                        count_limit = 18
                        break

            # 本页无新增控件，退出循环
            if not page_has_new_item:
                if not uav_dict:
                    # 没有可升级飞机类型，不点击任何行
                    break
                if len(uav_dict) <= 19:
                    list(uav_dict.values())[0].get('data_item').Click()
                else:
                    self.send_pgup_keybd(times=item_page)
                break

        return uav_dict.get(uav_type), uav_dict

    # ---------- 检查测试更新窗口 ---------- 飞机组件组---------- 选中飞机数据网格----------
    def get_check_beta_updates_window_uav_group_infos_data(self):
        return self.get_check_beta_updates_window_uav_group().DataGridControl(AutomationId='UpdateDgcs_ComponentInfos_DataGrid')

    # ---------- 检查测试更新窗口 ---------- 飞机组件组---------- 选中飞机数据网格---------- 飞控版本----------
    def get_check_beta_updates_window_uav_group_infos_data_items(self, fc_update_version, max_pages=100):
        infos_dict = {}

        # 获取待升级飞机数据网格控件
        data = self.get_check_beta_updates_window_uav_group_infos_data()
        # 初始化页数
        item_page = 1
        # 初始化翻页选中Row_Count
        count_limit = 19
        # 防止翻页失败或数据无限增长时陷入死循环
        page_count = 0
        while page_count < max_pages:
            page_count += 1
            # 获取当前页所有 DataGridRow
            data_children = data.GetChildren()
            page_has_new_item = False
            new_item_count = 0
            for data_grid_row in data_children:
                if data_grid_row.ClassName == 'DataGridRow':
                    data_grid_row_children = data_grid_row.GetChildren()
                    # 防止索引越界：子控件数必须能覆盖到下标 10
                    assert len(data_grid_row_children) > 10, f"飞机信息行子控件数量不足: {len(data_grid_row_children)}"
                    fc_version = data_grid_row_children[2].Name
                    # 检查是否已存在（避免重复添加）
                    if fc_version not in infos_dict:
                        page_has_new_item = True
                        new_item_count += 1
                        infos_dict_item = {
                            fc_version: {
                                'data_item': data_grid_row,
                                'fc_id': data_grid_row_children[1].Name,
                                'component_version': data_grid_row_children[3].Name,
                                'battery_version': data_grid_row_children[4].TextControl(ClassName='TextBlock').Name,
                                'gps_version': data_grid_row_children[5].Name,
                                'rs_version': data_grid_row_children[6].Name,
                                'receiver_version': data_grid_row_children[7].TextControl(ClassName='TextBlock').Name,
                                'bms_version': data_grid_row_children[8].TextControl(ClassName='TextBlock').Name,
                                'rid_version': data_grid_row_children[9].TextControl(ClassName='TextBlock').Name,
                                'remark': data_grid_row_children[10].TextControl(ClassName='TextBlock').Name,
                                'item_page': item_page
                            }
                        }
                        infos_dict.update(infos_dict_item)

                    # 当达到第19个时，翻到下一页
                    if new_item_count >= count_limit:
                        # 收集完当前页后，点击最后一个控件触发翻页
                        data_grid_row.Click()
                        time.sleep(0.1)
                        self.send_pgdn_keybd()
                        time.sleep(0.2)
                        item_page += 1
                        new_item_count = 0
                        # 因为会有一个Row在列表显示区域外，把循环次数改为18
                        count_limit = 18
                        break

            # 本页无新增控件，退出循环
            if not page_has_new_item:
                if not infos_dict:
                    # 没有可升级飞机，不点击任何行
                    break
                if len(infos_dict) <= 19:
                    list(infos_dict.values())[0].get('data_item').Click()
                else:
                    self.send_pgup_keybd(times=item_page)
                break

        return infos_dict.get(fc_update_version), infos_dict
    
        # ---------- 设置按钮 ----------
    def get_commonmenu_settings_button(self):
        return self.get_control_window().CustomControl(ClassName='CommonMenu').ButtonControl(AutomationId='CommonMenu_Settings_Button')
    
    # ---------- 设置按钮 ---------- 网卡设置菜单选项----------
    def get_commonmenu_settings_netcard_menuitem(self):
        return self.get_control_window().MenuControl(ClassName='ContextMenu').MenuItemControl(AutomationId='CommonMenu_Settings_NetCard_MenuItem')
    
    # ---------- 设置按钮 ---------- 更新固件菜单选项----------
    def get_commonmenu_settings_updatefirmware_menuitem(self):
        return self.get_control_window().MenuControl(ClassName='ContextMenu').MenuItemControl(AutomationId='CommonMenu_Settings_UpdateFirmware_MenuItem')

    # ---------- 设置按钮 ---------- 更新电池菜单选项----------
    def get_commonmenu_settings_updatebattery_menuitem(self):
        return self.get_control_window().MenuControl(ClassName='ContextMenu').MenuItemControl(AutomationId='CommonMenu_Settings_UpdateBattery_MenuItem')

    # ---------- 设置按钮 ---------- 更新GPS菜单选项----------
    def get_commonmenu_settings_updategps_menuitem(self):
        return self.get_control_window().MenuControl(ClassName='ContextMenu').MenuItemControl(AutomationId='CommonMenu_Settings_UpdateGps_MenuItem')

    # ---------- 设置按钮 ---------- 更新接收机菜单选项----------
    def get_commonmenu_settings_updatereceiver_menuitem(self):
        return self.get_control_window().MenuControl(ClassName='ContextMenu').MenuItemControl(AutomationId='CommonMenu_Settings_UpdateReceiver_MenuItem')

    # ---------- 设置按钮 ---------- 更新BMS菜单选项----------
    def get_commonmenu_settings_updatebms_menuitem(self):
        return self.get_control_window().MenuControl(ClassName='ContextMenu').MenuItemControl(AutomationId='CommonMenu_Settings_UpdateBms_MenuItem')

    # ---------- 设置按钮 ---------- 更新RID菜单选项----------
    def get_commonmenu_settings_updaterid_menuitem(self):
        return self.get_control_window().MenuControl(ClassName='ContextMenu').MenuItemControl(AutomationId='CommonMenu_Settings_UpdateRid_MenuItem')

    # ---------- 设置按钮 ---------- 更新电台菜单选项----------
    def get_commonmenu_settings_updatestation_menuitem(self):
        return self.get_control_window().MenuControl(ClassName='ContextMenu').MenuItemControl(AutomationId='CommonMenu_Settings_UpdateStation_MenuItem')

    # ---------- 设置按钮 ---------- 升级Boot菜单选项----------
    def get_commonmenu_settings_updateboot_menuitem(self):
        return self.get_control_window().MenuControl(ClassName='ContextMenu').MenuItemControl(AutomationId='CommonMenu_Settings_BootUpdate_MenuItem')

    # ---------- 设置按钮 ---------- USB更新固件菜单选项----------
    def get_commonmenu_settings_updateusb_menuitem(self):
        return self.get_control_window().MenuControl(ClassName='ContextMenu').MenuItemControl(AutomationId='CommonMenu_Settings_UsbUpdate_MenuItem')

    # ---------- 设置按钮 ---------- 网卡设置菜单选项---------- 设置网卡窗口 ----------
    def get_netcard_set_window(self):
        return self.get_control_window().WindowControl(Name='设置网卡')
    
    # ---------- 设置按钮 ---------- 网卡设置菜单选项---------- 网口选择下拉框 ----------
    def get_netcard_set_combobox(self):
        return self.get_netcard_set_window().ComboBoxControl(AutomationId='Settings_NetCard_SelectComboBox')

    # ---------- 设置按钮 ---------- 网卡设置菜单选项---------- 网口选择下拉框选项 ----------  
    def get_netcard_set_listitem(self, name):
        return self.get_netcard_set_combobox().ListItemControl(Name=name)

    # ---------- 设置按钮 ---------- 网卡设置菜单选项---------- 网口设置按钮 ----------      
    def get_netcard_set_button(self):
        return self.get_netcard_set_window().ButtonControl(Name='设置')

    # ---------- 更新xx成功弹窗 ----------
    def get_update_info_window(self):
        return auto.ButtonControl(AutomationId='ConfirmButton').GetAncestorControl()

    # ---------- 更新xx成功弹窗 ---------- 确认按钮----------
    def get_update_info_confirm_button(self):
        return self.get_update_info_window().ButtonControl(AutomationId='ConfirmButton')

    # ---------- 更新固件窗口 ----------
    def get_updatefirmware_window(self):
        main_window = self.get_control_window()
        if "大漠大地面控制站" in main_window.Name:
            return main_window.WindowControl(Name='更新固件')
        else:
            return main_window.WindowControl(Name='Update Firmware')

    # ---------- 更新固件窗口 ---------- 关闭按钮----------
    def get_updatefirmware_window_close_button(self):
        return self.get_updatefirmware_window().ButtonControl(AutomationId='CloseWindow')

    # ---------- 更新固件窗口 ---------- 最小化按钮----------
    def get_updatefirmware_window_minimize_button(self):
        return self.get_updatefirmware_window().ButtonControl(AutomationId='MinimizeButton')

    # ---------- 更新固件窗口 ---------- 固件数据网格----------
    def get_updatefirmware_window_data_grid(self):
        return self.get_updatefirmware_window().DataGridControl(AutomationId='FCFirmware_Firmware_DataGrid')

    # ---------- 更新固件窗口 ---------- 固件数据网格---------- 飞机Id----------
    # 获取固件数据网格中的所有飞机项，包括飞机Id、连接状态、类型、当前版本、新版本、阶段、进度、信息
    # 返回字典结构: {飞机Id: {'data_item': DataGridRow对象, 'user_type': ..., 'connect_state': ..., 'uav_type': ..., 'current_version': ..., 'new_version': ..., 'progress_stage': ..., 'progress_percent': ..., 'progress_message': ..., 'item_page': ...}}
    def get_updatefirmware_window_data_grid_items(self, uav_id, max_pages=100):
        items_dict = {}

        # 获取固件数据网格控件
        data = self.get_updatefirmware_window_data_grid()
        # 初始化页数
        item_page = 1
        # 初始化翻页选中Row_Count
        count_limit = 19
        # 防止翻页失败或数据无限增长时陷入死循环
        page_count = 0
        while page_count < max_pages:
            page_count += 1
            # 获取当前页所有 DataGridRow
            data_children = data.GetChildren()
            page_has_new_item = False
            new_item_count = 0
            for data_grid_row in data_children:
                if data_grid_row.ClassName == 'DataGridRow':
                    data_grid_row_children = data_grid_row.GetChildren()
                    # 防止索引越界：子控件数必须能覆盖到下标 9
                    assert len(data_grid_row_children) > 9, f"固件行子控件数量不足: {len(data_grid_row_children)}"
                    uav_type = data_grid_row_children[4].TextControl(ClassName='TextBlock').Name
                    uav_display_id = data_grid_row_children[2].TextControl(ClassName='TextBlock').Name
                    # 检查是否已存在（避免重复添加）
                    if uav_type not in items_dict:
                        page_has_new_item = True
                        new_item_count += 1
                        items_dict_item = {
                            f"{uav_type}_{uav_display_id}": {
                                'data_item': data_grid_row,
                                'user_type': data_grid_row_children[1].TextControl(ClassName='TextBlock').Name,
                                'connect_state': {'value': data_grid_row_children[3].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[3].TextControl(ClassName='TextBlock')},
                                'current_version': {'value': data_grid_row_children[5].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[5].TextControl(ClassName='TextBlock')},
                                'new_version': data_grid_row_children[6].TextControl(ClassName='TextBlock').Name,
                                'progress_stage': {'value': data_grid_row_children[7].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[7].TextControl(ClassName='TextBlock')},
                                'progress_percent': {'value': data_grid_row_children[8].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[8].TextControl(ClassName='TextBlock')},
                                'progress_message': {'value': data_grid_row_children[9].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[9].TextControl(ClassName='TextBlock')},
                                'item_page': item_page
                            }
                        }
                        items_dict.update(items_dict_item)

                    # 当达到第19个时，翻到下一页
                    if new_item_count >= count_limit:
                        # 收集完当前页后，点击最后一个控件触发翻页
                        data_grid_row.Click()
                        time.sleep(0.1)
                        self.send_pgdn_keybd()
                        time.sleep(0.2)
                        item_page += 1
                        new_item_count = 0
                        # 因为会有一个Row在列表显示区域外，把循环次数改为18
                        count_limit = 18
                        break

            # 本页无新增控件，退出循环
            if not page_has_new_item:
                if not items_dict:
                    # 没有可升级飞机，不点击任何行
                    break
                if len(items_dict) <= 19:
                    list(items_dict.values())[0].get('data_item').Click()
                else:
                    self.send_pgup_keybd(times=item_page)
                break

        return items_dict.get(uav_id), items_dict

    # ---------- 更新固件窗口 ---------- 已完成文本----------
    def get_updatefirmware_window_completed_text(self):
        return self.get_updatefirmware_window().TextControl(AutomationId='FCFirmware_Completed_TextBlock')

    # ---------- 更新固件窗口 ---------- 进度文本----------
    def get_updatefirmware_window_progress_text(self):
        return self.get_updatefirmware_window().TextControl(AutomationId='FCFirmware_Progress_TextBlock')

    # ---------- 更新固件窗口 ---------- 忽略离线复选框----------
    def get_updatefirmware_window_ignoreoffline_checkbox(self):
        return self.get_updatefirmware_window().CheckBoxControl(AutomationId='FCFirmware_IgnoreOffline_CheckBox')

    # ---------- 更新固件窗口 ---------- 全部更新按钮----------
    def get_updatefirmware_window_allupdate_button(self):
        return self.get_updatefirmware_window().ButtonControl(AutomationId='FCFirmware_AllUpdate_Button')

    # ---------- 更新固件窗口 ---------- 重试按钮----------
    def get_updatefirmware_window_retry_button(self):
        return self.get_updatefirmware_window().ButtonControl(AutomationId='FCFirmware_Retry_Button')

    # ---------- 更新固件窗口 ---------- 部分更新按钮----------
    def get_updatefirmware_window_partupdate_button(self):
        return self.get_updatefirmware_window().ButtonControl(AutomationId='FCFirmware_PartUpdate_Button')

    # ---------- 更新固件窗口 ---------- 中止按钮----------
    def get_updatefirmware_window_cancel_button(self):
        return self.get_updatefirmware_window().ButtonControl(AutomationId='FCFirmware_Cancel_Button')

    # ---------- 更新GPS窗口 ----------
    def get_updategps_window(self):
        main_window = self.get_control_window()
        if "大漠大地面控制站" in main_window.Name:
            return main_window.WindowControl(Name='更新GPS')
        else:
            return main_window.WindowControl(Name='Update GPS')

    # ---------- 更新GPS窗口 ---------- 关闭按钮----------
    def get_updategps_window_close_button(self):
        return self.get_updategps_window().ButtonControl(AutomationId='CloseWindow')

    # ---------- 更新GPS窗口 ---------- 最小化按钮----------
    def get_updategps_window_minimize_button(self):
        return self.get_updategps_window().ButtonControl(AutomationId='MinimizeButton')

    # ---------- 更新GPS窗口 ---------- 固件数据网格----------
    def get_updategps_window_data_grid(self):
        return self.get_updategps_window().DataGridControl(AutomationId='FCFirmware_Firmware_DataGrid')

    # ---------- 更新GPS窗口 ---------- 固件数据网格---------- 飞机项----------
    # 获取固件数据网格中的所有飞机项，包括飞机Id、连接状态、类型、当前版本、新版本、阶段、进度、信息
    # 返回字典结构: {飞机类型_飞机Id: {'data_item': DataGridRow对象, 'user_type': ..., 'connect_state': ..., 'uav_type': ..., 'current_version': ..., 'new_version': ..., 'progress_stage': ..., 'progress_percent': ..., 'progress_message': ..., 'item_page': ...}}
    def get_updategps_window_data_grid_items(self, uav_id, max_pages=100):
        items_dict = {}

        # 获取固件数据网格控件
        data = self.get_updategps_window_data_grid()
        # 初始化页数
        item_page = 1
        # 初始化翻页选中Row_Count
        count_limit = 19
        # 防止翻页失败或数据无限增长时陷入死循环
        page_count = 0
        while page_count < max_pages:
            page_count += 1
            # 获取当前页所有 DataGridRow
            data_children = data.GetChildren()
            page_has_new_item = False
            new_item_count = 0
            for data_grid_row in data_children:
                if data_grid_row.ClassName == 'DataGridRow':
                    data_grid_row_children = data_grid_row.GetChildren()
                    # 防止索引越界：子控件数必须能覆盖到下标 9
                    assert len(data_grid_row_children) > 9, f"固件行子控件数量不足: {len(data_grid_row_children)}"
                    uav_type = data_grid_row_children[4].TextControl(ClassName='TextBlock').Name
                    uav_display_id = data_grid_row_children[2].TextControl(ClassName='TextBlock').Name
                    # 检查是否已存在（避免重复添加）
                    if uav_type not in items_dict:
                        page_has_new_item = True
                        new_item_count += 1
                        items_dict_item = {
                            f"{uav_type}_{uav_display_id}": {
                                'data_item': data_grid_row,
                                'user_type': data_grid_row_children[1].TextControl(ClassName='TextBlock').Name,
                                'connect_state': {'value': data_grid_row_children[3].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[3].TextControl(ClassName='TextBlock')},
                                'current_version': {'value': data_grid_row_children[5].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[5].TextControl(ClassName='TextBlock')},
                                'new_version': data_grid_row_children[6].TextControl(ClassName='TextBlock').Name,
                                'progress_stage': {'value': data_grid_row_children[7].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[7].TextControl(ClassName='TextBlock')},
                                'progress_percent': {'value': data_grid_row_children[8].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[8].TextControl(ClassName='TextBlock')},
                                'progress_message': {'value': data_grid_row_children[9].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[9].TextControl(ClassName='TextBlock')},
                                'item_page': item_page
                            }
                        }
                        items_dict.update(items_dict_item)

                    # 当达到第19个时，翻到下一页
                    if new_item_count >= count_limit:
                        # 收集完当前页后，点击最后一个控件触发翻页
                        data_grid_row.Click()
                        time.sleep(0.1)
                        self.send_pgdn_keybd()
                        time.sleep(0.2)
                        item_page += 1
                        new_item_count = 0
                        # 因为会有一个Row在列表显示区域外，把循环次数改为18
                        count_limit = 18
                        break

            # 本页无新增控件，退出循环
            if not page_has_new_item:
                if not items_dict:
                    # 没有可升级飞机，不点击任何行
                    break
                if len(items_dict) <= 19:
                    list(items_dict.values())[0].get('data_item').Click()
                else:
                    self.send_pgup_keybd(times=item_page)
                break

        return items_dict.get(uav_id), items_dict

    # ---------- 更新GPS窗口 ---------- 已完成文本----------
    def get_updategps_window_completed_text(self):
        return self.get_updategps_window().TextControl(AutomationId='FCFirmware_Completed_TextBlock')

    # ---------- 更新GPS窗口 ---------- 进度文本----------
    def get_updategps_window_progress_text(self):
        return self.get_updategps_window().TextControl(AutomationId='FCFirmware_Progress_TextBlock')

    # ---------- 更新GPS窗口 ---------- 忽略离线复选框----------
    def get_updategps_window_ignoreoffline_checkbox(self):
        return self.get_updategps_window().CheckBoxControl(AutomationId='FCFirmware_IgnoreOffline_CheckBox')

    # ---------- 更新GPS窗口 ---------- 全部更新按钮----------
    def get_updategps_window_allupdate_button(self):
        return self.get_updategps_window().ButtonControl(AutomationId='FCFirmware_AllUpdate_Button')

    # ---------- 更新GPS窗口 ---------- 重试按钮----------
    def get_updategps_window_retry_button(self):
        return self.get_updategps_window().ButtonControl(AutomationId='FCFirmware_Retry_Button')

    # ---------- 更新GPS窗口 ---------- 部分更新按钮----------
    def get_updategps_window_partupdate_button(self):
        return self.get_updategps_window().ButtonControl(AutomationId='FCFirmware_PartUpdate_Button')

    # ---------- 更新GPS窗口 ---------- 中止按钮----------
    def get_updategps_window_cancel_button(self):
        return self.get_updategps_window().ButtonControl(AutomationId='FCFirmware_Cancel_Button')

    # ---------- 更新BMS窗口 ----------
    def get_updatebms_window(self):
        main_window = self.get_control_window()
        if "大漠大地面控制站" in main_window.Name:
            return main_window.WindowControl(Name='更新BMS')
        else:
            return main_window.WindowControl(Name='Update BMS')

    # ---------- 更新BMS窗口 ---------- 关闭按钮----------
    def get_updatebms_window_close_button(self):
        return self.get_updatebms_window().ButtonControl(AutomationId='CloseWindow')

    # ---------- 更新BMS窗口 ---------- 最小化按钮----------
    def get_updatebms_window_minimize_button(self):
        return self.get_updatebms_window().ButtonControl(AutomationId='MinimizeButton')

    # ---------- 更新BMS窗口 ---------- 固件数据网格----------
    def get_updatebms_window_data_grid(self):
        return self.get_updatebms_window().DataGridControl(AutomationId='FCFirmware_Firmware_DataGrid')

    # ---------- 更新BMS窗口 ---------- 固件数据网格---------- 飞机项----------
    # 获取固件数据网格中的所有飞机项，包括飞机Id、连接状态、类型、当前版本、新版本、阶段、进度、信息
    # 返回字典结构: {飞机类型_飞机Id: {'data_item': DataGridRow对象, 'user_type': ..., 'connect_state': ..., 'uav_type': ..., 'current_version': ..., 'new_version': ..., 'progress_stage': ..., 'progress_percent': ..., 'progress_message': ..., 'item_page': ...}}
    def get_updatebms_window_data_grid_items(self, uav_id, max_pages=100):
        items_dict = {}

        # 获取固件数据网格控件
        data = self.get_updatebms_window_data_grid()
        # 初始化页数
        item_page = 1
        # 初始化翻页选中Row_Count
        count_limit = 19
        # 防止翻页失败或数据无限增长时陷入死循环
        page_count = 0
        while page_count < max_pages:
            page_count += 1
            # 获取当前页所有 DataGridRow
            data_children = data.GetChildren()
            page_has_new_item = False
            new_item_count = 0
            for data_grid_row in data_children:
                if data_grid_row.ClassName == 'DataGridRow':
                    data_grid_row_children = data_grid_row.GetChildren()
                    # 防止索引越界：子控件数必须能覆盖到下标 9
                    assert len(data_grid_row_children) > 9, f"固件行子控件数量不足: {len(data_grid_row_children)}"
                    uav_type = data_grid_row_children[4].TextControl(ClassName='TextBlock').Name
                    uav_display_id = data_grid_row_children[2].TextControl(ClassName='TextBlock').Name
                    # 检查是否已存在（避免重复添加）
                    if uav_type not in items_dict:
                        page_has_new_item = True
                        new_item_count += 1
                        items_dict_item = {
                            f"{uav_type}_{uav_display_id}": {
                                'data_item': data_grid_row,
                                'user_type': data_grid_row_children[1].TextControl(ClassName='TextBlock').Name,
                                'connect_state': {'value': data_grid_row_children[3].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[3].TextControl(ClassName='TextBlock')},
                                'current_version': {'value': data_grid_row_children[5].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[5].TextControl(ClassName='TextBlock')},
                                'new_version': data_grid_row_children[6].TextControl(ClassName='TextBlock').Name,
                                'progress_stage': {'value': data_grid_row_children[7].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[7].TextControl(ClassName='TextBlock')},
                                'progress_percent': {'value': data_grid_row_children[8].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[8].TextControl(ClassName='TextBlock')},
                                'progress_message': {'value': data_grid_row_children[9].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[9].TextControl(ClassName='TextBlock')},
                                'item_page': item_page
                            }
                        }
                        items_dict.update(items_dict_item)

                    # 当达到第19个时，翻到下一页
                    if new_item_count >= count_limit:
                        # 收集完当前页后，点击最后一个控件触发翻页
                        data_grid_row.Click()
                        time.sleep(0.1)
                        self.send_pgdn_keybd()
                        time.sleep(0.2)
                        item_page += 1
                        new_item_count = 0
                        # 因为会有一个Row在列表显示区域外，把循环次数改为18
                        count_limit = 18
                        break

            # 本页无新增控件，退出循环
            if not page_has_new_item:
                if not items_dict:
                    # 没有可升级飞机，不点击任何行
                    break
                if len(items_dict) <= 19:
                    list(items_dict.values())[0].get('data_item').Click()
                else:
                    self.send_pgup_keybd(times=item_page)
                break

        return items_dict.get(uav_id), items_dict

    # ---------- 更新BMS窗口 ---------- 已完成文本----------
    def get_updatebms_window_completed_text(self):
        return self.get_updatebms_window().TextControl(AutomationId='FCFirmware_Completed_TextBlock')

    # ---------- 更新BMS窗口 ---------- 进度文本----------
    def get_updatebms_window_progress_text(self):
        return self.get_updatebms_window().TextControl(AutomationId='FCFirmware_Progress_TextBlock')

    # ---------- 更新BMS窗口 ---------- 忽略离线复选框----------
    def get_updatebms_window_ignoreoffline_checkbox(self):
        return self.get_updatebms_window().CheckBoxControl(AutomationId='FCFirmware_IgnoreOffline_CheckBox')

    # ---------- 更新BMS窗口 ---------- 全部更新按钮----------
    def get_updatebms_window_allupdate_button(self):
        return self.get_updatebms_window().ButtonControl(AutomationId='FCFirmware_AllUpdate_Button')

    # ---------- 更新BMS窗口 ---------- 重试按钮----------
    def get_updatebms_window_retry_button(self):
        return self.get_updatebms_window().ButtonControl(AutomationId='FCFirmware_Retry_Button')

    # ---------- 更新BMS窗口 ---------- 部分更新按钮----------
    def get_updatebms_window_partupdate_button(self):
        return self.get_updatebms_window().ButtonControl(AutomationId='FCFirmware_PartUpdate_Button')

    # ---------- 更新BMS窗口 ---------- 中止按钮----------
    def get_updatebms_window_cancel_button(self):
        return self.get_updatebms_window().ButtonControl(AutomationId='FCFirmware_Cancel_Button')

    # ---------- 更新接收机窗口 ----------
    def get_updatereceiver_window(self):
        main_window = self.get_control_window()
        if "大漠大地面控制站" in main_window.Name:
            return main_window.WindowControl(Name='更新接收机')
        else:
            return main_window.WindowControl(Name='Update Receiver')

    # ---------- 更新接收机窗口 ---------- 关闭按钮----------
    def get_updatereceiver_window_close_button(self):
        return self.get_updatereceiver_window().ButtonControl(AutomationId='CloseWindow')

    # ---------- 更新接收机窗口 ---------- 最小化按钮----------
    def get_updatereceiver_window_minimize_button(self):
        return self.get_updatereceiver_window().ButtonControl(AutomationId='MinimizeButton')

    # ---------- 更新接收机窗口 ---------- 固件数据网格----------
    def get_updatereceiver_window_data_grid(self):
        return self.get_updatereceiver_window().DataGridControl(AutomationId='FCFirmware_Firmware_DataGrid')

    # ---------- 更新接收机窗口 ---------- 固件数据网格---------- 飞机项----------
    # 获取固件数据网格中的所有飞机项，包括飞机Id、连接状态、类型、当前版本、新版本、阶段、进度、信息
    # 返回字典结构: {飞机类型_飞机Id: {'data_item': DataGridRow对象, 'user_type': ..., 'connect_state': ..., 'uav_type': ..., 'current_version': ..., 'new_version': ..., 'progress_stage': ..., 'progress_percent': ..., 'progress_message': ..., 'item_page': ...}}
    def get_updatereceiver_window_data_grid_items(self, uav_id, max_pages=100):
        items_dict = {}

        # 获取固件数据网格控件
        data = self.get_updatereceiver_window_data_grid()
        # 初始化页数
        item_page = 1
        # 初始化翻页选中Row_Count
        count_limit = 19
        # 防止翻页失败或数据无限增长时陷入死循环
        page_count = 0
        while page_count < max_pages:
            page_count += 1
            # 获取当前页所有 DataGridRow
            data_children = data.GetChildren()
            page_has_new_item = False
            new_item_count = 0
            for data_grid_row in data_children:
                if data_grid_row.ClassName == 'DataGridRow':
                    data_grid_row_children = data_grid_row.GetChildren()
                    # 防止索引越界：子控件数必须能覆盖到下标 9
                    assert len(data_grid_row_children) > 9, f"固件行子控件数量不足: {len(data_grid_row_children)}"
                    uav_type = data_grid_row_children[4].TextControl(ClassName='TextBlock').Name
                    uav_display_id = data_grid_row_children[2].TextControl(ClassName='TextBlock').Name
                    # 检查是否已存在（避免重复添加）
                    if uav_type not in items_dict:
                        page_has_new_item = True
                        new_item_count += 1
                        items_dict_item = {
                            f"{uav_type}_{uav_display_id}": {
                                'data_item': data_grid_row,
                                'user_type': data_grid_row_children[1].TextControl(ClassName='TextBlock').Name,
                                'connect_state': {'value': data_grid_row_children[3].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[3].TextControl(ClassName='TextBlock')},
                                'current_version': {'value': data_grid_row_children[5].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[5].TextControl(ClassName='TextBlock')},
                                'new_version': data_grid_row_children[6].TextControl(ClassName='TextBlock').Name,
                                'progress_stage': {'value': data_grid_row_children[7].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[7].TextControl(ClassName='TextBlock')},
                                'progress_percent': {'value': data_grid_row_children[8].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[8].TextControl(ClassName='TextBlock')},
                                'progress_message': {'value': data_grid_row_children[9].TextControl(ClassName='TextBlock').Name,
                                                     'item': data_grid_row_children[9].TextControl(ClassName='TextBlock')},
                                'item_page': item_page
                            }
                        }
                        items_dict.update(items_dict_item)

                    # 当达到第19个时，翻到下一页
                    if new_item_count >= count_limit:
                        # 收集完当前页后，点击最后一个控件触发翻页
                        data_grid_row.Click()
                        time.sleep(0.1)
                        self.send_pgdn_keybd()
                        time.sleep(0.2)
                        item_page += 1
                        new_item_count = 0
                        # 因为会有一个Row在列表显示区域外，把循环次数改为18
                        count_limit = 18
                        break

            # 本页无新增控件，退出循环
            if not page_has_new_item:
                if not items_dict:
                    # 没有可升级飞机，不点击任何行
                    break
                if len(items_dict) <= 19:
                    list(items_dict.values())[0].get('data_item').Click()
                else:
                    self.send_pgup_keybd(times=item_page)
                break

        return items_dict.get(uav_id), items_dict

    # ---------- 更新接收机窗口 ---------- 已完成文本----------
    def get_updatereceiver_window_completed_text(self):
        return self.get_updatereceiver_window().TextControl(AutomationId='FCFirmware_Completed_TextBlock')

    # ---------- 更新接收机窗口 ---------- 进度文本----------
    def get_updatereceiver_window_progress_text(self):
        return self.get_updatereceiver_window().TextControl(AutomationId='FCFirmware_Progress_TextBlock')

    # ---------- 更新接收机窗口 ---------- 忽略离线复选框----------
    def get_updatereceiver_window_ignoreoffline_checkbox(self):
        return self.get_updatereceiver_window().CheckBoxControl(AutomationId='FCFirmware_IgnoreOffline_CheckBox')

    # ---------- 更新接收机窗口 ---------- 全部更新按钮----------
    def get_updatereceiver_window_allupdate_button(self):
        return self.get_updatereceiver_window().ButtonControl(AutomationId='FCFirmware_AllUpdate_Button')

    # ---------- 更新接收机窗口 ---------- 重试按钮----------
    def get_updatereceiver_window_retry_button(self):
        return self.get_updatereceiver_window().ButtonControl(AutomationId='FCFirmware_Retry_Button')

    # ---------- 更新接收机窗口 ---------- 部分更新按钮----------
    def get_updatereceiver_window_partupdate_button(self):
        return self.get_updatereceiver_window().ButtonControl(AutomationId='FCFirmware_PartUpdate_Button')

    # ---------- 更新接收机窗口 ---------- 中止按钮----------
    def get_updatereceiver_window_cancel_button(self):
        return self.get_updatereceiver_window().ButtonControl(AutomationId='FCFirmware_Cancel_Button')

    # ---------- 其他菜单 ----------
    def get_othermenu_control(self):
        self._refresh_main_window()
        return self.get_control_window().CustomControl(ClassName='OtherMenu')
    
    # ---------- 其他菜单 ---------- 中英文切换----------
    def get_othermenu_language_switch_button(self):
       return self.get_control_window().ButtonControl(AutomationId='OtherMenu_SwitchLanguage_Button')
    
    # ---------- 其他菜单 ---------- 中英文切换---------- 切换英文 ----------
    def get_othermenu_english_menuitem(self):
       return self.get_control_window().MenuItemControl(AutomationId='OtherMenu_English_MenuItem')

    # ---------- 其他菜单 ---------- 中英文切换---------- 切换中文 ----------
    def get_othermenu_chinese_menuitem(self):
       return self.get_control_window().MenuItemControl(AutomationId='OtherMenu_Chinese_MenuItem')

    # ---------- 其他菜单 ---------- 风速显示模块 ----------
    def get_othermenu_windspeed_info_control(self):
        return self.get_othermenu_control().CustomControl(AutomationId='OtherMenu_WindSpeedInfo_WindSpeedInfo')
    
    # ---------- 其他菜单 ---------- 风速显示模块 ---------- 风速显示文本 ----------
    def get_othermenu_windspeed_info_text(self):
        return self.get_othermenu_windspeed_info_control().TextControl(AutomationId='WindSpeedInfo_Speed_TextBlock')
    
    # ---------- 风速告警窗口 ----------
    def get_windspeed_warning_window(self):
        return self.find_child_by_localizedcontroltype(self.get_control_window(),'窗格')
    
    # ---------- 风速告警窗口 ---------- 风速告警图标 ----------
    def get_windspeed_warning_icon(self):
        return self.get_windspeed_warning_window().ImageControl(AutomationId='IconImage')

    # ---------- 风速告警窗口 ---------- 风速告警文本 ----------
    def get_windspeed_warning_text(self):
        panecontrol = self.find_child_by_localizedcontroltype(self.get_control_window(),'窗格')
        textcontrol = self.find_child_by_name(panecontrol, 'm/s')
        return textcontrol
    
    # ---------- 风速告警窗口 ---------- 我知道了按钮 ----------
    def get_windspeed_warning_iknow_button(self):
        return self.get_windspeed_warning_window().ButtonControl(AutomationId='PART_ConfirmButton')
    
    # ---------- 风速告警窗口 ---------- 告警消息关闭按钮 ----------
    def get_windspeed_warning_close_button(self):
        return self.get_windspeed_warning_window().ButtonControl(AutomationId='PART_CloseButton')
    
    # ---------- 任务栏 ---------- DGCS应用 ----------
    def get_main_window_button(self):
        root = auto.GetRootControl()
        return self.find_child_by_automationid(root, '}\\DGCS\\')
    
    # ---------- 通用 UI 辅助方法 ----------
    def clear_edit(self, edit_control):
        edit_control.Click()
        time.sleep(0.2)
        auto.SendKeys('{Ctrl}a')
        time.sleep(0.1)
        auto.SendKeys('{Delete}')
        time.sleep(0.1)

    def input_to_edit(self, edit_control, text):
        self.clear_edit(edit_control)
        edit_control.SendKeys(text)

    def get_control_value(self, control):
        legacy_accessible = control.GetLegacyIAccessiblePattern()
        if legacy_accessible:
            return legacy_accessible.Value
        return control.Name

    def switch_to_main_window(self):
        if self.main_window:
            try:
                self.main_window.SwitchToThisWindow()
                time.sleep(0.3)
            except Exception as e:
                print(f"切回主窗口失败: {e}")
    
    def send_pgdn_keybd(self, times=1):
        user32 = ctypes.windll.user32
        """通过 keybd_event 发送 PageDown。
        times=0 时不发送任何按键（用于"已在目标页"场景）"""
        if times <= 0:
            return
        VK_NEXT = 0x22      # PageDown 虚拟键码
        KEYEVENTF_KEYUP = 0x0002
        for _ in range(times):
            user32.keybd_event(VK_NEXT, 0, 0, 0)                # 按下
            time.sleep(0.05)
            user32.keybd_event(VK_NEXT, 0, KEYEVENTF_KEYUP, 0)  # 抬起
            time.sleep(0.05)
    
    def send_pgup_keybd(self, times=1):
        user32 = ctypes.windll.user32
        """通过 keybd_event 发送 PageUp。
        times=0 时不发送任何按键"""
        if times <= 0:
            return
        VK_PRIOR = 0x21     # PageUp 虚拟键码
        KEYEVENTF_KEYUP = 0x0002
        for _ in range(times):
            user32.keybd_event(VK_PRIOR, 0, 0, 0)               # 按下
            time.sleep(0.05)
            user32.keybd_event(VK_PRIOR, 0, KEYEVENTF_KEYUP, 0)  # 抬起
            time.sleep(0.05)

    # ---------- 移动鼠标到控件上 ----------
    def move_mouse_to_control(self, control, position='center'):
        """将鼠标移动到指定控件的指定位置。

        Args:
            control: 目标 UI 控件
            position: 目标位置，支持 'center'（控件中心）、'topleft'（左上角）、
                      'topright'（右上角）、'bottomleft'（左下角）、'bottomright'（右下角），
                      或传入 (x_ratio, y_ratio) 元组（取值 0~1，相对控件宽高的比例偏移）

        Returns:
            成功返回 (x, y) 屏幕坐标，失败返回 None
        """
        if control is None:
            print("move_mouse_to_control: 控件为空")
            return None
        try:
            rect = control.BoundingRectangle
            x, y, width, height = rect.left, rect.top, rect.width(), rect.height()
        except Exception as e:
            print(f"move_mouse_to_control: 获取控件位置失败: {e}")
            return None

        if width <= 0 or height <= 0:
            print("move_mouse_to_control: 控件宽高为 0，跳过移动")
            return None

        # 根据 position 计算目标点
        if position == 'center':
            tx, ty = x + width // 2, y + height // 2
        elif position == 'topleft':
            tx, ty = x + 2, y + 2
        elif position == 'topright':
            tx, ty = x + width - 2, y + 2
        elif position == 'bottomleft':
            tx, ty = x + 2, y + height - 2
        elif position == 'bottomright':
            tx, ty = x + width - 2, y + height - 2
        elif isinstance(position, tuple) and len(position) == 2:
            xr, yr = position
            tx, ty = x + int(width * xr), y + int(height * yr)
        else:
            tx, ty = x + width // 2, y + height // 2

        # 优先使用 uiautomation 自带的移动方法
        try:
            control.MoveCursorTo(tx, ty)
        except Exception:
            # 兜底：使用 Windows API 直接设置光标位置
            try:
                ctypes.windll.user32.SetCursorPos(tx, ty)
            except Exception as e:
                print(f"move_mouse_to_control: 移动鼠标失败: {e}")
                return None
        time.sleep(0.1)
        return tx, ty

    # ---------- ComboBox 与 ListBoxItem 点击 ----------
    def click_combobox(self, combobox):
        combobox.Click()
        time.sleep(0.3)

    def click_listbox_item(self, list_item):
        list_item.Click()
        time.sleep(0.2)

    def select_list_item_by_name(self, combobox_or_list, item_name):
        combobox_or_list.Click()
        time.sleep(0.3)
        list_item = combobox_or_list.ListItemControl(name=item_name)
        if list_item:
            list_item.Click()
            time.sleep(0.2)
            return True
        return False

    # ---------- 通用 UI 通过AutomationId查询控件 ----------
    def find_child_by_automationid(self, parent_control, automationid_contains, recursive=True):

        """
        遍历当前控件下所有子控件，查找 AutomationId 存在特定字符串的子控件并返回。

        Args:
            parent_control: 起始控件（根节点）
            automationid_contains: 要匹配的 AutomationId 字符串（子串匹配，不区分大小写）
            recursive: 是否递归遍历所有层级，默认 True

        Returns:
            找到的第一个匹配控件，未找到返回 None
        """
        if not parent_control:
            return None

        try:
            children = parent_control.GetChildren()
        except Exception:
            return None

        for child in children:
            try:
                child_automationid = child.AutomationId or ""
                if automationid_contains in child_automationid:
                    return child
            except Exception:
                pass

            if recursive:
                result = self.find_child_by_automationid(child, automationid_contains, recursive=True)
                if result is not None:
                    return result

        return None
    
    # ---------- 通用 UI 通过Name查询控件 ----------
    def find_child_by_name(self, parent_control, name_contains, recursive=False):

        """
        遍历当前控件下所有子控件，查找 Name 存在特定字符串的子控件并返回。

        Args:
            parent_control: 起始控件（根节点）
            name_contains: 要匹配的 Name 字符串（子串匹配，不区分大小写）
            recursive: 是否递归遍历所有层级，默认 True

        Returns:
            找到的第一个匹配控件，未找到返回 None
        """
        if not parent_control:
            return None

        try:
            children = parent_control.GetChildren()
        except Exception:
            return None

        for child in children:
            try:
                child_name = child.Name or ""
                if name_contains in child_name:
                    return child
            except Exception:
                pass

            if recursive:
                result = self.find_child_by_name(child, name_contains, recursive=True)
                if result is not None:
                    return result

        return None

    # ---------- 通用 UI 通过LocalizedControlType查询控件 ----------
    def find_child_by_localizedcontroltype(self, parent_control, localizedcontroltype_contains, recursive=False):

        """
        遍历当前控件下所有子控件，查找 Name 存在特定字符串的子控件并返回。

        Args:
            parent_control: 起始控件（根节点）
            name_contains: 要匹配的 Name 字符串（子串匹配，不区分大小写）
            recursive: 是否递归遍历所有层级，默认 True

        Returns:
            找到的第一个匹配控件，未找到返回 None
        """
        if not parent_control:
            return None

        try:
            children = parent_control.GetChildren()
        except Exception:
            return None

        for child in children:
            try:
                localizedcontroltype = child.LocalizedControlType or ""
                if localizedcontroltype_contains in localizedcontroltype:
                    return child
            except Exception:
                pass

            if recursive:
                result = self.find_child_by_localizedcontroltype(child, localizedcontroltype_contains, recursive=True)
                if result is not None:
                    return result

        return None
