import time

from src.Protocol.drama.SwarmPainter import *
from src.Script.Drone_Show.SwarmPainter_Ui.Release_Testing import *


@allure.feature("SwarmPainter Ui测试")
class TestSwarmPainter:
    @classmethod
    def setup_class(cls):
        cls.runner = SwarmPainter()

    @allure.title("登录SwarmPainter")
    @allure.link("test_login.html", name="Airtest报告")
    @copy_result_html("test_login.html")
    def test_login(self):
        self.runner.wait(self.runner.login_window, timeout=30)
        self.runner.click(self.runner.account_widget)
        text(self.runner.user)

        self.runner.click(self.runner.pass_word_widget)
        text(self.runner.pwd)

        self.runner.click(self.runner.login_button)

        wel = self.runner.welcome_page(threshold=0.8)
        self.runner.wait(wel)
        assert_exists(wel, '登录失败')

    @allure.title("新建剧本")
    @allure.link("test_create_project.html", name="Airtest报告")
    @copy_result_html("test_create_project.html")
    def test_create_project(self):
        project_name = "auto_test_project"
        self.runner.click(self.runner.project_search_widget)
        text(project_name)
        keyevent("{ENTER}")

        if exists(self.runner.project_edit_button):
            self.runner.click(self.runner.project_edit_button)
            self.runner.click(self.runner.delete_button)

        self.runner.click(self.runner.create_project)
        self.runner.click(self.runner.project_name_widget)
        text(project_name)
        self.runner.click(self.runner.confirm_created_project)

        for _ in range(60):
            if exists(self.runner.progress_bar):
                time.sleep(0.5)
                continue
            else:
                break
        else:
            raise Exception(">>>> 新建剧本异常")

        task_bar = self.runner.task_bar(threshold=0.8)
        self.runner.wait(task_bar, timeout=30)
        assert_exists(task_bar, '打开项目失败')

    @allure.title("导入剧本")
    @allure.link("test_import_material.html", name="Airtest报告")
    @copy_result_html("test_import_material.html")
    def test_import_material(self):
        self.runner.click(self.runner.outline_and_material_button(target_pos=6))
        self.runner.click(self.runner.import_material)

        self.runner.click(self.runner.jsdm_file_path)
        text(os.path.join(root_path, "file", "JSDM"))
        self.runner.click(self.runner.open_jsdm_path)
        text('"qifei.jsdm" "1.jsdm" "2.jsdm" "3.jsdm" "4.jsdm" "5.jsdm" "jiangluo.jsdm" ')
        self.runner.click(self.runner.open_jsdm_path)

        for _ in range(60):
            if exists(self.runner.progress_bar):
                time.sleep(0.5)
                continue
            else:
                break
        else:
            raise Exception(">>>> 创建分镜异常")

        if exists(self.runner.error_tips):
            raise AssertionError("导入素材失败")

        if not exists(self.runner.take_off_material):
            self.runner.click(self.runner.task_folder)

        assert_exists(self.runner.take_off_material, '素材加载失败')

    @allure.title("创建分镜")
    @allure.link("test_build_storyboard.html", name="Airtest报告")
    @copy_result_html("test_build_storyboard.html")
    def test_build_storyboard(self):
        # 设置起飞素材jsdm_type为【起飞】
        self.runner.click(self.runner.take_off_material)
        self.runner.click(self.runner.jsdm_type)
        self.runner.click(self.runner.jsdm_type_value(target_pos=5))

        # 设置降落素材jsdm_type为【降落】
        self.runner.click(self.runner.landing_material)
        self.runner.click(self.runner.jsdm_type)
        self.runner.click(self.runner.jsdm_type_value(target_pos=8), use_cache=False)

        # 批量生成分镜
        self.runner.click(self.runner.task_folder, right_click=True)
        self.runner.click(self.runner.batch_generate_storyboards)

        # 进度条加载中
        for _ in range(60):
            if exists(self.runner.progress_bar):
                time.sleep(0.5)
                continue
            else:
                break
        else:
            raise Exception(">>>> 创建分镜异常")

        self.runner.click(self.runner.outline_and_material_button(target_pos=4), use_cache=False)

        if not exists(self.runner.storyboards_1):
            self.runner.click(self.runner.task_folder)
            self.runner.click(self.runner.task_folder)

    @allure.title("拖动分镜到位置轴并解算")
    @allure.link("test_storyboard_solving.html", name="Airtest报告")
    @copy_result_html("test_storyboard_solving.html")
    def test_storyboard_solving(self):
        self.runner.drag(self.runner.take_off_storyboards_1, self.runner.position_200, 1)
        self.runner.drag(self.runner.storyboards_1, self.runner.position_800, 1)
        self.runner.drag(self.runner.storyboards_2, self.runner.position_1200, 1)
        self.runner.drag(self.runner.storyboards_3, self.runner.position_1600, 1)
        self.runner.drag(self.runner.storyboards_4, self.runner.position_2000, 1)
        self.runner.drag(self.runner.storyboards_5, self.runner.position_2400, 1)
        self.runner.drag(self.runner.landing_storyboards_1, self.runner.position_2800, 1)

        self.runner.click(self.runner.calculate_button)

        for _ in range(60):
            if exists(self.runner.progress_bar):
                time.sleep(0.5)
                continue
            else:
                break
        else:
            raise Exception(">>>> 解算失败")

    @allure.title("导出drama文件")
    @allure.link("test_export_as_drama.html", name="Airtest报告")
    @copy_result_html("test_export_as_drama.html")
    def test_export_as_drama(self):
        self.runner.click(self.runner.position_3400, right_click=True)
        self.runner.click(self.runner.export_drama_button)
        self.runner.click(self.runner.file_save_button)

        if exists(self.runner.check_tips):
            self.runner.click(self.runner.check_confirm)

        for _ in range(60):
            if exists(self.runner.progress_bar):
                time.sleep(0.5)
                continue
            else:
                break
        else:
            raise Exception(">>>> 创建分镜异常")
