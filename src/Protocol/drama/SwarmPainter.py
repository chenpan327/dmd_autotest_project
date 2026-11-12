import time
import allure
from airtest.core.api import *

current_path = os.path.dirname(os.path.abspath(__file__))
root_path = os.path.split(current_path)[0]
auto_setup(__file__, devices=["Windows:///"])
from utils.web_cloud import load_config
from src.Physical.SwarmPainter.SwarmPainterBase import SwarmPainterBase

templatePath = os.path.join(root_path, "Protocol", "image")


class SwarmPainter(SwarmPainterBase):
    def __init__(self):
        super().__init__()
        conf = load_config().get("SwarmPainter_Ui", {})
        self.user = conf.get("user_name")
        self.pwd = conf.get("login_passwd")

        self.device = device()

    @property
    def login_window(self):
        return Template(templatePath + r"\tp_login_window.png", record_pos=(0.0, 0.005),
                        resolution=self.resolution)

    @property
    def account_widget(self):
        return Template(templatePath + r"\tp_account_widget.png", record_pos=(0.004, -0.023),
                        resolution=self.resolution)

    @property
    def pass_word_widget(self):
        return Template(templatePath + r"\tp_pass_word_widget.png", record_pos=(0.004, 0.003),
                        resolution=self.resolution)

    @property
    def login_button(self):
        return Template(templatePath + r"\tp_login_button.png", record_pos=(0.027, 0.054),
                        resolution=self.resolution)

    def welcome_page(self, **kwargs):
        return Template(templatePath + r"\tp_welcome_page.png", record_pos=(-0.001, -0.061),
                        resolution=self.resolution, **kwargs)

    @property
    def project_search_widget(self):
        return Template(templatePath + r"\tp_project_search.png", record_pos=(0.109, -0.057),
                        resolution=self.resolution)

    @property
    def project_edit_button(self):
        return Template(templatePath + r"\tp_project_edit_button.png", record_pos=(0.141, -0.022),
                        resolution=self.resolution)

    @property
    def delete_button(self):
        return Template(templatePath + r"\tp_delete_button.png", record_pos=(0.174, -0.006),
                        resolution=self.resolution, target_pos=2)

    @property
    def create_project(self):
        return Template(templatePath + r"\tp_create_project_button.png", record_pos=(-0.078, -0.056),
                        resolution=self.resolution)

    @property
    def project_name_widget(self):
        return Template(templatePath + r"\tp_project_name.png", record_pos=(0.0, -0.029),
                        resolution=self.resolution)

    @property
    def confirm_created_project(self):
        return Template(templatePath + r"\tp_confirm_created_project.png", record_pos=(0.059, 0.056),
                        resolution=self.resolution)

    def task_bar(self, **kwargs):
        return Template(templatePath + r"\tp_task_bar.png", record_pos=(-0.449, 0.108),
                        resolution=self.resolution, **kwargs)

    def outline_and_material_button(self, **kwargs):
        return Template(templatePath + r"\tp_material_button.png", record_pos=(-0.402, -0.242),
                        resolution=self.resolution, **kwargs)

    @property
    def import_material(self):
        return Template(templatePath + r"\tp_import_material.png", record_pos=(-0.45, -0.225),
                        resolution=self.resolution)

    @property
    def jsdm_file_path(self):
        return Template(templatePath + r"\tp_jsdm_file_path.png", record_pos=(-0.263, 0.011),
                        resolution=self.resolution)

    @property
    def open_jsdm_path(self):
        return Template(templatePath + r"\tp_open_path_button.png", record_pos=(-0.069, 0.028),
                        resolution=self.resolution)

    @property
    def task_folder(self):
        return Template(templatePath + r"\tp_task_folder_button.png", record_pos=(-0.433, -0.194),
                        resolution=self.resolution)

    @property
    def take_off_material(self):
        return Template(templatePath + r"\tp_take_off_material.png", record_pos=(-0.464, 0.054),
                        resolution=self.resolution)

    @property
    def landing_material(self, **kwargs):
        return Template(templatePath + r"\tp_landing_material.png", record_pos=(-0.465, -0.17),
                        resolution=self.resolution)

    @property
    def jsdm_type(self):
        return Template(templatePath + r"\tp_jsdm_type.png", record_pos=(0.414, -0.168), target_pos=5,
                        resolution=self.resolution)

    def jsdm_type_value(self, **kwargs):
        """ 起飞：target_pos=5 ，降落：target_pos=8 """
        return Template(templatePath + r"\tp_jsdm_type_value.png", record_pos=(0.446, -0.141),
                        resolution=self.resolution, **kwargs)

    @property
    def batch_generate_storyboards(self, **kwargs):
        return Template(templatePath + r"\tp_batch_generate_storyboards.png", record_pos=(-0.39, -0.156),
                        resolution=self.resolution, **kwargs)

    @property
    def progress_bar(self, **kwargs):
        return Template(templatePath + r"\tp_progress_bar.png", record_pos=(0.003, -0.002),
                        resolution=self.resolution, **kwargs)

    @property
    def error_tips(self, **kwargs):
        return Template(templatePath + r"\tp_error_tips.png", record_pos=(0.002, -0.026),
                        resolution=self.resolution, **kwargs)

    @property
    def landing_storyboards_1(self, **kwargs):
        return Template(templatePath + r"\tp_landing_storyboards_1.png", record_pos=(-0.433, 0.053),
                        resolution=self.resolution, **kwargs)

    @property
    def take_off_storyboards_1(self, **kwargs):
        return Template(templatePath + r"\tp_take_off_storyboards_1.png", record_pos=(-0.433, -0.173),
                        resolution=self.resolution, **kwargs)

    @property
    def storyboards_1(self, **kwargs):
        return Template(templatePath + r"\tp_storyboards_1.png", record_pos=(-0.433, -0.135),
                        resolution=self.resolution, **kwargs)

    @property
    def storyboards_2(self):
        return Template(templatePath + r"\tp_storyboards_2.png", record_pos=(-0.433, -0.097),
                        resolution=self.resolution)

    @property
    def storyboards_3(self):
        return Template(templatePath + r"\tp_storyboards_3.png", record_pos=(-0.433, -0.06),
                        resolution=self.resolution)

    @property
    def storyboards_4(self):
        return Template(templatePath + r"\tp_storyboards_4.png", record_pos=(-0.433, -0.022),
                        resolution=self.resolution)

    @property
    def storyboards_5(self):
        return Template(templatePath + r"\tp_storyboards_5.png", record_pos=(-0.434, 0.016),
                        resolution=self.resolution)

    @property
    def position_200(self):
        return Template(templatePath + r"\tp_position_200.png", record_pos=(-0.328, 0.146), target_pos=8,
                        resolution=self.resolution)

    @property
    def position_800(self, ):
        Template(r"tpl1778655756708.png", record_pos=(-0.199, 0.144), resolution=(1920, 1080))
        return Template(templatePath + r"\tp_position_800.png", record_pos=(-0.199, 0.144), target_pos=8,
                        resolution=self.resolution)

    @property
    def position_1200(self):
        return Template(templatePath + r"\tp_position_1200.png", record_pos=(-0.113, 0.143), target_pos=8,
                        resolution=self.resolution)

    @property
    def position_1600(self, ):
        return Template(templatePath + r"\tp_position_1600.png", record_pos=(-0.027, 0.143), target_pos=8,
                        resolution=self.resolution)

    @property
    def position_2000(self, ):
        return Template(templatePath + r"\tp_position_2000.png", record_pos=(0.058, 0.142), target_pos=8,
                        resolution=self.resolution)

    @property
    def position_2400(self, ):
        return Template(templatePath + r"\tp_position_2400.png", record_pos=(0.145, 0.142), target_pos=8,
                        resolution=self.resolution)

    @property
    def position_2800(self, ):
        """ 位置轴2800"""
        return Template(templatePath + r"\tp_position_2800.png", record_pos=(0.231, 0.142), target_pos=8,
                        resolution=self.resolution)

    @property
    def position_3400(self, ):
        """ 位置轴3400"""
        return Template(templatePath + r"\tp_position_3400.png", record_pos=(0.381, 0.134), target_pos=8,
                        resolution=self.resolution)

    @property
    def calculate_button(self):
        """解算按钮"""
        return Template(templatePath + r"\tp_calculate_button.png", record_pos=(-0.464, 0.144),
                        resolution=self.resolution)

    @property
    def export_drama_button(self):
        """导出剧本"""
        return Template(templatePath + r"\tp_export_drama_item.png", record_pos=(0.411, 0.169), target_pos=8,
                        resolution=self.resolution)

    @property
    def file_save_button(self):
        """文件保存按钮"""
        return Template(templatePath + r"\tp_file_save_button.png", record_pos=(-0.069, 0.028),
                        resolution=self.resolution)

    Template(r"tpl1778661307131.png", record_pos=(-0.069, -0.055), resolution=(1920, 1080))

    @property
    def check_tips(self):
        """确认提示"""
        return Template(templatePath + r"\tp_check_tips.png", record_pos=(-0.069, -0.055),
                        resolution=self.resolution)

    @property
    def check_confirm(self):
        """确认提示"""
        return Template(templatePath + r"\tp_check_confirm.png", record_pos=(-0.007, -0.008), target_pos=4,
                        resolution=self.resolution)
