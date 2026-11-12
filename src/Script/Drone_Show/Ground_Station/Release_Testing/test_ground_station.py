# -*- coding: utf-8 -*-
"""
===============================================================================
                                Web自动化测试脚本
===============================================================================
脚本编号: DMD_TEST_GROUND_CONTROL
脚本版本: v1.0
创建日期: 2026-04-07
开发人员: 陈新江
版权所属：深圳大漠大智控技术有限公司
适用产品: 地控中心管理系统
测试类型: 地面站UI测试
测试环境: Python 3.10, uiautomation, Allure报告, Pytest框架

===============================================================================
测试目的:
验证地面站软件与无人机表演相关业务流程
1. 地面站用户登录
   - 未授权用户登录（alan1）
   - 用户账号密码错误（ci）
   - 地面站授权到期提醒（ci）

===============================================================================
技术架构:
- 测试框架: Pytest + uiautomation + allure
- 测试环境: 地面站V4（uat）
===============================================================================
数据驱动设计:
1. 地面站登录：账号授权验证，到期提醒
2. 无人机详情: 检查飞机发送到地面站报文，并做异常检查
3. 飞行表演: 模拟飞行添加飞机表演剧本，剧本传输等
4. 网卡设置: 选择地面站网卡信息
5. 固件更新: 选择无人机指定固件版本进行更新

===============================================================================
测试步骤:
模块名称           | 用例编号 | 测试场景                | 关键验证点
------------------|----------|------------------------|-----------------------------------------
地面站登录          | GC-GS-01 | 地面站登录              | 不同账号登录的异常提示
                  | GC-GS-02 | 设置网卡               | 选择设备本地网卡
                  | GC-GS-03 | 模拟飞行               | 添加飞机加载剧本执行表演
                  | GC-GS-04 | 亮灯                  | 选择无人机进行亮灯操作
                  | GC-GS-05 | 无人机详情             | 无人机详细信息上报


===============================================================================
前提条件:
1. 测试环境准备:
   - 本地以安装地面站V4最新版本
   - 测试账号已经在当前测试设备上激活
   - uat环境正常

2. 测试数据准备:
   - 测试账号CI在当前环境可用
   - 当前测试设备地面站有连接无人机设备
   - 测试设备需保持未锁屏状态

3. 测试框架准备:
   - Pytest运行环境正常
   - Allure报告环境配置完成
   - uiautomation、allure-pytest等依赖已安装

===============================================================================
特别说明:
1. 用例依赖关系:
   - 多数模块用例存在前置依赖
   - 使用@pytest.mark.dependency确保执行顺序正确
   - 登录成功，设备连接状态是多数用例的前提

2. 验证方式:
   - 控件验证: 执行弹窗出现
   - 无人机验证: 获取无人机报文
   - 功能验证: 页面操作返回标志位

3. 报告集成:
   - 用例执行自动截图
   - 截图自动附加到Allure报告
   - 支持问题回溯与结果分析

===============================================================================
测试结论:
测试通过，地面站界面操作正常，无人机与地面站信息交互正确
===============================================================================
"""
import json
import os
import sys
import time

import inspect

from utils.logger import logger
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
import allure
import pytest
from src.Protocol.web.Web_API import WEBCloud
from src.Protocol.dgcs.Dgcs_Ui import DGCS, root_path
from utils.web_cloud import load_test_data


def data_driver(json_file):
    def decorator(func):
        func_name = func.__name__
        key = func_name.replace("test_", "")

        data = load_test_data(json_file, key)

        arg_names = list(data[0].keys())

        arg_values = []
        for item in data:
            arg_values.append(
                pytest.param(
                    *[item.get(k) for k in arg_names],
                    id=item.get("title", None)
                )
            )

        # 👉 关键：不要破坏函数引用链
        func = pytest.mark.parametrize(arg_names, arg_values)(func)
        return func

    return decorator


@allure.description("")
@allure.feature("地面站UI测试")
class TestDGCS:
    @classmethod
    def setup_class(cls):
        logger.info("=============初始化测试类对象=======================")
        cls.runner = DGCS()
        cls.web = WEBCloud()
        cls.web.get_token(dynamic_args={"username": cls.runner.user, "password": cls.runner.pwd})
        cls.runner.start_app()

    @classmethod
    def teardown_class(cls):
        cls.runner.exit()

    @allure.title("地面站-登录")
    @pytest.mark.dependency(name='login')
    @allure.severity(allure.severity_level.CRITICAL)
    @data_driver(
        BASE_DIR + r'\Release_Testing\test_data.json')
    def test_login(self, usr, pwd, expected):
        if usr == 'CI':
            # 获取地面站id
            with allure.step(f"获取云平台地面站id"):
                resp = self.web.dgcs_search()
                station_id = resp['result']['records'][0]['id']

            # 获取地面站用户id
            with allure.step(f"获取地面站授权用户id"):
                resp = self.web.dgcs_user_list(dynamic_args={"stationId": station_id, "username": self.runner.user})
                self.runner.user_info = resp['result']['records'][0]
                # 修改授权用户到期时间
                id = self.runner.user_info['id']

            with allure.step(f"修改用户授权到期时间"):
                date_str = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
                self.web.edit_dgcs_user(dynamic_args={"username": "CI", "id": id, "expired": f"{date_str} 00:00:00"})

        with allure.step(f"用户{usr}登录地面站"):
            result = self.runner.login(usr, pwd)

            allure.attach.file(
                root_path + "/file/picture/login.png",
                name="执行结果",
                attachment_type=allure.attachment_type.PNG
            )
            assert result == expected

    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title('用户信息')
    @pytest.mark.dependency(depends=['login'])
    def test_user_info(self):
        with allure.step("检查地面站用户信息"):
            result = self.runner.profile()
            assert result['uav_type'] == self.runner.user_info['droneTypeTxt'].split(',')

    @pytest.mark.parametrize('name', ['以太网 2'])
    @pytest.mark.dependency(depends=['login'])
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title('设置网卡')
    def test_set_netcard(self, name):
        with allure.step("设置网卡"):
            result = self.runner.set_netcard(name)
            assert result

    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.dependency(depends=['login'], name='uav_show')
    @allure.title('无人机-模拟飞行')
    def test_uav_show(self):
        with allure.step("添加模拟飞机"):
            result = self.runner.add_simulated_uav('Newton40')
            assert result

        with allure.step("加载剧本"):
            self.runner.load_player(r"\file\drama_files\L3高亮+爆闪200架.drm")

        with allure.step("判断附近是否有临近飞行项目"):
            flag = False
            resp = self.web.adjacent_project_list()
            project_list = resp['data']['projectList']
            if len(project_list) > 0:
                flag = True

        with allure.step("设置原点"):
            result = self.runner.set_origin(flag)
            assert result

        with allure.step("差分转发"):
            result = self.runner.set_rtk()

        with allure.step("设置剧本映射"):
            self.runner.mapping_set()

        with allure.step("设置表演时间"):
            self.runner.set_show_time()

        with allure.step("预览剧本"):
            self.runner.review_player()

        with allure.step("传输剧本"):
            self.runner.transfer_player()
        with allure.step("开始表演"):
            self.runner.start_show()

    @pytest.mark.dependency(depends=['uav_show'])
    @pytest.mark.parametrize('uav_id,color', [('1', 'FF0050')])
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title('无人机-亮灯')
    def test_uav_light(self, uav_id, color):
        with allure.step("地面站点击亮灯"):
            result = self.runner.uav_light(uav_id, color)
            assert result

        allure.attach.file(
            root_path + "/file/picture/main.png",
            name="执行结果",
            attachment_type=allure.attachment_type.PNG
        )

    @pytest.mark.parametrize('uav_id', ['1'])
    @pytest.mark.dependency(depends=['uav_show'])
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title('无人机-详情')
    def test_uav_info(self, uav_id):
        with allure.step("无人机详情"):
            result = self.runner.uav_info(uav_id)
            assert result

        allure.attach.file(
            root_path + "/file/picture/UavListView.png",
            name="执行结果",
            attachment_type=allure.attachment_type.PNG
        )

    @pytest.mark.parametrize('uav_id', ['1'])
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.dependency(depends=['uav_show'])
    @allure.title('更新固件')
    def test_update_firmware(self, uav_id):
        with allure.step("更新固件"):
            result = self.runner.update_firmware(uav_id)
            assert result
