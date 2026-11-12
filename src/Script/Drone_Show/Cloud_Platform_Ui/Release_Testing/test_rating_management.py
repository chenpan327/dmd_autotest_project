# -*- coding: utf-8 -*-
"""
===============================================================================
                                Web自动化测试脚本
===============================================================================
脚本编号: DMD_TESTRATING_MANAGEMENT
脚本版本: v1.0
创建日期: 2026-07-31
开发人员: 陈新江
版权所属：深圳大漠大智控技术有限公司
适用产品: 生产中心管理系统
测试类型: Web功能测试
测试环境: Python 3.10, Selenium WebDriver, Allure报告, Pytest框架

===============================================================================
测试目的:
验证生产中心 Web 管理系统的核心业务功能，确保库存、销售出库、
设备类型及编码规则等模块功能稳定、数据准确、流程正确。
主要包括：
1. 评级管理
   - 等级新增，查询，删除，失效

2. 人员管理
   - 新增飞手等级成员，编辑，删除

===============================================================================
技术架构:
- 测试框架: Pytest + Allure + Selenium
- 自动化模式: Page Object Model（POM）
- 页面元素定位: XPath / 页面文本校验
- 同步机制: 显式等待（WebDriverWait + ExpectedConditions）
- 用例依赖: pytest.mark.dependency

===============================================================================
数据驱动设计:
5. 图片对比验证:
   - search_rating_user.png
   - search_rating_user.png

===============================================================================
测试步骤:
模块名称       | 用例编号 | 测试场景              | 关键验证点
--------------|----------|----------------------|-----------------------------------------
等级管理         | TEST-01  | 新增飞手等级          | 新增成功提示验证
               | TEST-02  | 等级查询              | 页面截图校验
               | TEST-03  | 编辑等级              | 编辑成功提示验证
               | TEST-04  | 等级失效              | 编辑成功提示验证
               | TEST-05  | 等级删除              | 删除成功提示验证
人员管理        | TEST-06  | 人员管理新增           | 新增成功提示验证
               | TEST-07  | 人员管理搜索           | 页面截图校验
               | TEST-08  | 人员管理编辑           | 编辑成功提示验证
               | TEST-09  | 人员管理删除           | 删除成功提示验证


===============================================================================
前提条件:
1. 测试环境准备:
   - Web 浏览器（Chrome / Edge）已正确安装
   - WebDriver 配置完成并可正常驱动浏览器
   - 生产中心系统服务运行正常
   - 测试账号具备生产中心相关操作权限

2. 测试数据准备:
   - 无

3. 测试框架准备:
   - pytest、selenium、allure-pytest 等依赖已安装
   - Allure 报告环境已正确配置

===============================================================================
特别说明:
1. 用例依赖关系:
   - 库存管理部分用例存在执行顺序依赖
   - 使用 pytest.mark.dependency 保证业务流程完整
   - 导入成功后才能执行删除、入库、出库等操作

2. 验证方式:
   - 文本验证: Toast 提示内容校验
   - 页面验证: page_source 关键字校验
   - UI 验证: 页面截图与基准图片对比

3. 报告集成:
   - 每个用例执行后自动截图
   - 自动获取浏览器 Console 日志
   - 截图与日志统一附加至 Allure 报告

===============================================================================
测试结论:
评级管理各核心功能模块均可按照预期流程正常执行，
页面交互、数据处理及提示信息准确可靠，满足业务测试要求。
===============================================================================
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
import allure
import pytest
from src.Protocol.web.Web_UI import RatingManagement


@allure.feature('评级管理')
class TestRatingManagement:

    @pytest.fixture(scope='class', autouse=True)
    def setup_class(self, request, login):
        request.cls.uav = RatingManagement(login.driver)

    ############################################################################################################ 库存管理
    @allure.story("等级管理")
    @allure.title('等级管理-新增')
    @pytest.mark.parametrize('name,expected',
                             [("test", "添加成功")])
    @pytest.mark.dependency(name='add_rating_level')
    def test_add_rating_level(self, name, expected):
        flag = self.uav.add_rating_level(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("等级管理")
    @allure.title('等级管理-搜索')
    @pytest.mark.parametrize('name,expected',
                             [("test", "search_rating_level.png")])
    @pytest.mark.dependency(depends=['add_rating_level'])
    def test_search_rating_level(self, name, expected):
        flag = self.uav.search_rating_level(name)

        assert flag
        assert self.uav._checkPictures(expected), "screenshot unmatch !!!"

    @allure.story("等级管理")
    @allure.title('等级管理-编辑')
    @pytest.mark.parametrize('name,expected',
                             [("test", "编辑成功")])
    @pytest.mark.dependency(depends=['add_rating_level'])
    def test_edit_rating_level(self, name, expected):
        flag = self.uav.edit_rating_level(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("人员管理")
    @allure.title('人员管理-新增')
    @pytest.mark.parametrize('name,expected',
                             [("CI", "添加成功")])
    @pytest.mark.dependency(depends=['add_rating_level'],name='add_rating_user')
    def test_add_rating_user(self, name, expected):
        flag = self.uav.add_rating_user(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("人员管理")
    @allure.title('人员管理-搜索')
    @pytest.mark.parametrize('name,expected',
                             [("CI", "search_rating_user.png")])
    @pytest.mark.dependency(depends=['add_rating_user'])
    def test_search_rating_user(self, name, expected):
        flag = self.uav.search_rating_user(name)

        assert flag
        assert self.uav._checkPictures(expected), "screenshot unmatch !!!"

    @allure.story("人员管理")
    @allure.title('人员管理-编辑')
    @pytest.mark.parametrize('name,expected',
                             [("CI", "编辑成功")])
    @pytest.mark.dependency(depends=['add_rating_user'])
    def test_edit_rating_user(self, name, expected):
        flag = self.uav.edit_rating_user(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("人员管理")
    @allure.title('人员管理-删除')
    @pytest.mark.parametrize('name,expected',
                             [("CI", "删除成功")])
    @pytest.mark.dependency(depends=['add_rating_user'],name='delete_rating_user')
    def test_delete_rating_user(self, name, expected):
        flag = self.uav.delete_rating_user(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("等级管理")
    @allure.title('等级管理-失效')
    @pytest.mark.parametrize('name,expected',
                             [("test", "编辑成功")])
    @pytest.mark.dependency(depends=['delete_rating_user'])
    def test_failure_rating_level(self, name, expected):
        flag = self.uav.failure_rating_level(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("等级管理")
    @allure.title('等级管理-删除')
    @pytest.mark.parametrize('name,expected',
                             [("test", "删除成功")])
    @pytest.mark.dependency(depends=['delete_rating_user'])
    def test_delete_rating_level(self, name, expected):
        flag = self.uav.delete_rating_level(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text
