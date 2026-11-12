# -*- coding: utf-8 -*-
"""
===============================================================================
                                Web自动化测试脚本
===============================================================================
脚本编号: DMD_TEST_SERVICE_CENTER_WEB_001
脚本版本: v1.0
创建日期: 2025-10-29
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: 服务项目中心管理系统
测试类型: Web功能测试
测试环境: Python 3.10, Selenium WebDriver, Allure报告, Pytest框架

===============================================================================
测试目的:
验证【服务项目中心】Web 管理系统中【飞行项目管理】模块的核心功能，
确保飞行项目的查询、编辑、详情查看以及自用订单相关业务流程正常，
页面交互正确，提示信息准确。

主要验证内容包括：
1. 飞行项目基础功能
   - 飞行项目搜索功能
   - 飞行项目编辑功能
   - 飞行项目详情页面展示
2. 飞行项目自用订单管理
   - 创建自用订单
   - 编辑自用订单
   - 取消自用订单
3. 页面提示信息与 UI 展示正确性

===============================================================================
技术架构:
- 测试框架: Pytest + Allure + Selenium
- 自动化模式: Page Object Model（POM）
- 页面元素定位: XPath
- 同步机制: 显式等待（WebDriverWait + ExpectedConditions）
- 用例依赖: pytest.mark.dependency
- 日志采集: 浏览器 Console 日志

===============================================================================
数据驱动设计:
1. 飞行项目测试数据:
   - 项目名称: auto_ test_project
2. 页面提示信息:
   - 创建成功
   - 编辑成功
   - 取消成功
3. 图片对比验证:
   - search_project.png
   - detail_project.png
4. 截图路径:
   - file/picture/

===============================================================================
测试步骤:
模块名称         | 用例编号 | 测试场景               | 关键验证点
----------------|----------|------------------------|-----------------------------------------
飞行项目管理     | TEST-01  | 飞行项目搜索           | 搜索结果展示 + 图片对比验证
                 | TEST-02  | 飞行项目编辑           | 编辑成功提示验证
                 | TEST-03  | 飞行项目详情           | 详情页面截图比对验证
                 | TEST-04  | 创建自用订单           | 创建成功提示验证
                 | TEST-05  | 编辑自用订单           | 编辑成功提示验证
                 | TEST-06  | 取消自用订单           | 取消成功提示验证

===============================================================================
前提条件:
1. 测试环境准备:
   - Web 浏览器（Chrome / Edge）已安装
   - WebDriver 已正确配置
   - 服务项目中心系统可正常访问
   - 测试账号具备飞行项目管理相关权限

2. 测试数据准备:
   - 飞行项目数据已存在（auto_test_project）
   - 图片比对基准文件已存放在 src/Protocol/image 目录
   - 截图保存路径 file/picture 可正常写入

3. 测试框架准备:
   - pytest、selenium、allure-pytest 已安装
   - Allure 报告环境配置完成

===============================================================================
特别说明:
1. 用例依赖关系:
   - 自用订单编辑、取消依赖于自用订单创建成功
   - 使用 pytest.mark.dependency 控制执行顺序

2. 验证方式:
   - 功能验证: 方法返回值 flag
   - 文本验证: 页面 Toast 提示信息
   - UI 验证: 页面截图与基准图片对比

3. 报告集成:
   - 每个用例执行完成后自动截图
   - 自动采集浏览器 Console 日志
   - 截图与日志统一附加至 Allure 测试报告

===============================================================================
测试结论:
服务项目中心飞行项目管理相关功能运行正常，
自用订单业务流程完整，页面展示与提示信息符合预期，
满足 Web 自动化测试验证要求。
===============================================================================
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
import allure
import pytest
from src.Protocol.web.Web_UI import ServiceCenter


@allure.feature('服务项目中心')
class TestServiceCenter:

    @pytest.fixture(scope='class', autouse=True)
    def setup_class(self, request, login):
        request.cls.uav = ServiceCenter(login.driver)

    ##########################################################################################################飞行项目管理
    @allure.story("飞行项目管理")
    @allure.title('飞行项目-搜索')
    @pytest.mark.parametrize('project_name,expected',
                             [("auto_ test_project", "search_project.png")])
    def test_search_project(self, project_name, expected):
        flag = self.uav.search_project(project_name)

        assert flag
        assert self.uav._checkPictures(expected), "screenshot unmatch !!!"

    @allure.story("飞行项目管理")
    @allure.title('飞行项目-编辑')
    @pytest.mark.parametrize('project_name,expected', [("auto_ test_project", "编辑成功")])
    def test_edit_project(self, project_name, expected):
        flag = self.uav.edit_project(project_name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("飞行项目管理")
    @allure.title('飞行项目-详情')
    @pytest.mark.parametrize('project_name,expected',
                             [("auto_ test_project", "detail_project.png")])
    def test_detail_project(self, project_name, expected):
        flag = self.uav.detail_project(project_name)

        assert flag
        assert self.uav._checkPictures(expected), "screenshot unmatch !!!"

    @allure.story("飞行项目管理")
    @allure.title('飞行项目-新增自用订单')
    @pytest.mark.dependency(name='self_order')
    @pytest.mark.parametrize('project_name,expected',
                             [("auto_ test_project", "创建成功")])
    def test_self_order(self, project_name, expected):
        flag = self.uav.add_self_order(project_name)
        text = self.uav.get_toast_text()
        assert flag
        assert expected in text

    @allure.story("飞行项目管理")
    @allure.title('飞行项目-编辑自用订单')
    @pytest.mark.dependency(depends=['self_order'])
    @pytest.mark.parametrize('project_name,expected',
                             [("auto_ test_project", "编辑成功")])
    def test_edit_self_order(self, project_name, expected):
        flag = self.uav.edit_self_order(project_name)
        text = self.uav.get_toast_text()

        assert flag, "编辑自用订单失败"
        assert expected in text

    @allure.story("飞行项目管理")
    @allure.title('飞行项目-取消自用订单')
    @pytest.mark.dependency(depends=['self_order'])
    @pytest.mark.parametrize('project_name,expected',
                             [("auto_ test_project", "取消成功")])
    def test_cancel_self_order(self, project_name, expected):
        flag = self.uav.cancel_self_order(project_name)
        text = self.uav.get_toast_text()

        assert flag, '取消自用订单失败'
        assert expected in text

    ##########################################################################################################表演二维码
    @allure.story("表演二维码管理")
    @allure.title('表演二维码-新增二维码')
    @pytest.mark.dependency(name='add_QRCode')
    @pytest.mark.parametrize(
        'audio_file, expected', [("test_audio.mp3", "添加成功")])
    def test_add_QRCode(self, audio_file, expected):
        flag = self.uav.add_QRCode(audio_file)
        text = self.uav.get_toast_text()

        assert flag, "新增二维码失败"
        assert expected in text

    @allure.story("表演二维码管理")
    @allure.title('表演二维码-查询二维码')
    @pytest.mark.dependency(depends=["add_QRCode"])
    @pytest.mark.parametrize('expected', ["search_QRCode.png"])
    def test_search_QRCode(self, expected):
        flag = self.uav.search_QRCode()

        assert flag, "查询二维码失败"
        assert self.uav._checkPictures(expected), "screenshot unmatch !!!"
