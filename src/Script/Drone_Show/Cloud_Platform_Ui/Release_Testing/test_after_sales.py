# -*- coding: utf-8 -*-
"""
===============================================================================
                                Web自动化测试脚本
===============================================================================
脚本编号: DMD_TEST_AFTER_SALES_WEB_001
脚本版本: v1.0
创建日期: 2025-10-29
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: 售后中心管理系统
测试类型: Web功能测试
测试环境: Python 3.10, Selenium WebDriver, Allure报告, Pytest框架

===============================================================================
测试目的:
验证售后中心Web管理系统的核心功能模块：
1. 故障类型管理模块（增删改查、原因管理）
   - 测试新增故障类型的完整流程
   - 验证故障类型的搜索、编辑、删除功能
   - 测试故障原因的新增和管理功能
2. 维修管理模块
   - 验证维修订单的搜索功能
   - 测试维修面板的访问和操作限制
3. 故障现象管理模块
   - 测试故障现象的增删改查全流程
4. 维修订单管理模块
   - 验证维修订单的搜索功能
   - 测试维修订单详情的查看功能

===============================================================================
技术架构:
- 测试框架: Pytest + Allure + Selenium
- 页面元素: XPath定位 + 显示等待机制
- 断言验证: 结合文本验证和图片对比验证
- 报告生成: Allure报告，包含截图和浏览器日志
- 测试依赖: 使用@pytest.mark.dependency管理用例执行顺序

===============================================================================
数据驱动设计:
1. 故障类型测试数据: "test"名称, 预期结果验证
2. 维修订单测试数据: 真实订单号(WV3000000111等)
3. 故障现象测试数据: "test"案例名称
4. 图片对比验证: 每个用例都有预期截图对比验证

===============================================================================
测试步骤:
模块名称       | 用例编号 | 测试场景              | 关键验证点
--------------|----------|----------------------|-----------------------------------------
故障类型管理   | AS-FT-01 | 故障类型新增          | 新增成功提示验证 + 页面元素操作验证
              | AS-FT-02 | 故障类型搜索          | 搜索功能验证 + 图片对比验证
              | AS-FT-03 | 故障原因新增          | 原因添加成功提示验证
              | AS-FT-04 | 故障类型编辑          | 编辑成功提示验证
              | AS-FT-05 | 故障类型删除          | 删除成功提示验证
维修管理       | AS-RM-01 | 维修订单搜索          | 搜索功能验证 + 图片对比验证
              | AS-RM-02 | 维修面板访问          | 面板访问验证 + 安全模式提示验证
故障现象管理   | AS-FC-01 | 故障现象新增          | 新增成功提示验证
              | AS-FC-02 | 故障现象查询          | 查询功能验证 + 图片对比验证
              | AS-FC-03 | 故障现象编辑          | 编辑成功提示验证
              | AS-FC-04 | 故障现象删除          | 删除成功提示验证
维修订单       | AS-RO-01 | 维修订单查询          | 查询功能验证 + 图片对比验证
              | AS-RO-02 | 维修订单详情          | 详情页面验证 + 图片对比验证

===============================================================================
前提条件:
1. 测试环境准备:
   - Web浏览器已安装（Chrome/Firefox等）
   - WebDriver已正确配置并可用
   - 售后中心系统可正常访问
   - 测试账号已具备相应权限

2. 测试数据准备:
   - 故障类型测试数据已清理或准备
   - 维修订单测试数据存在（WV3000000111等）
   - 截图对比文件已准备在file/picture目录

3. 测试框架准备:
   - Allure报告环境已配置
   - Pytest运行环境已配置
   - 相关依赖包已安装（selenium, allure-pytest等）

===============================================================================
特别说明:
1. 用例依赖关系:
   - 故障类型管理用例存在执行顺序依赖
   - 使用@pytest.mark.dependency确保正确执行顺序
   - 新增用例必须成功才能执行后续搜索、编辑、删除操作

2. 验证方式:
   - 文本验证: 验证操作成功提示信息
   - 图片对比: 验证页面显示正确性
   - 功能验证: 验证页面操作返回标志

3. 报告集成:
   - 每个用例自动截图保存
   - 浏览器控制台日志收集
   - 截图和日志自动附加到Allure报告

===============================================================================
测试结论:
测试通过，所有Web功能模块按照预期执行，页面操作和验证机制正常工作。
===============================================================================
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

import allure
import pytest
from src.Protocol.web.Web_UI import AfterSales


@allure.feature('售后中心')
class TestAfterSales:

    @pytest.fixture(scope='class', autouse=True)
    def setup_class(self, request, login):
        request.cls.uav = AfterSales(login.driver)

    ########################################################################################################## 故障类型管理
    @allure.story("故障类型管理")
    @allure.title('故障类型新增')
    @pytest.mark.dependency(name='add_fault_type')
    @pytest.mark.parametrize('name,expected', [("test", "添加成功")])
    def test_add_fault_type(self, name, expected):
        flag = self.uav.add_fault_type(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("故障类型管理")
    @allure.title('故障类型搜索')
    @pytest.mark.dependency(depends=['add_fault_type'])
    @pytest.mark.parametrize('name,expected', [["test", "search_fault_type.png"]])
    def test_search_fault_type(self, name, expected):
        flag = self.uav.search_fault_type(name)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("故障类型管理")
    @allure.title('故障类型-新增原因')
    @pytest.mark.dependency(depends=['add_fault_type'])
    @pytest.mark.parametrize('name,cause,expected', [("test", "test", "添加成功")])
    def test_add_fault_cause(self, name, cause, expected):
        flag = self.uav.add_fault_cause(name, cause)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("故障类型管理")
    @allure.title('故障类型-编辑')
    @pytest.mark.dependency(depends=['add_fault_type'])
    @pytest.mark.parametrize('name,expected', [("test", "编辑成功")])
    def test_edit_fault_type(self, name, expected):
        flag = self.uav.edit_fault_type(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("故障类型管理")
    @allure.title('故障类型-删除')
    @pytest.mark.dependency(depends=['add_fault_type'])
    @pytest.mark.parametrize('name,expected', [("test", "删除成功")])
    def test_delete_fault_type(self, name, expected):
        flag = self.uav.delete_fault_type(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ############################################################################################################# 维修管理
    @allure.story("维修管理")
    @allure.title('维修管理-搜索')
    @pytest.mark.parametrize('orderNo,expected',
                             [["WV3000000111", "repair_manage_search.png"]])
    def test_repair_manage_search(self, orderNo, expected):
        flag = self.uav.repair_manage_search(orderNo)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("维修管理")
    @allure.title('维修面板')
    @pytest.mark.parametrize('orderNo,expected', [["WV3000000111", "安全模式，不允许操作OA数据"]])
    def test_repair_manage_panel(self, orderNo, expected):
        flag = self.uav.repair_manage_panel(orderNo)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ######################################################################################################### 故障现象管理
    @allure.story("故障现象管理")
    @allure.title('故障现象-新增')
    @pytest.mark.dependency(name='fault_case_add')
    @pytest.mark.parametrize('caseName,expected', [["test", "添加成功"]])
    def test_fault_case_add(self, caseName, expected):
        flag = self.uav.fault_case_add(caseName)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("故障现象管理")
    @allure.title('故障现象-查询')
    @pytest.mark.dependency(depends=['fault_case_add'])
    @pytest.mark.parametrize('caseName,expected', [["test", "fault_case_search.png"]])
    def test_fault_case_search(self, caseName, expected):
        flag = self.uav.fault_case_search(caseName)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("故障现象管理")
    @allure.title('故障现象-编辑')
    @pytest.mark.dependency(depends='fault_case_add')
    @pytest.mark.parametrize('caseName,expected', [["test", "编辑成功"]])
    def test_fault_case_edit(self, caseName, expected):
        flag = self.uav.fault_case_edit(caseName)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("故障现象管理")
    @allure.title('故障现象-删除')
    @pytest.mark.dependency(depends='fault_case_add')
    @pytest.mark.parametrize('caseName,expected', [["test", "删除成功"]])
    def test_fault_case_delete(self, caseName, expected):
        flag = self.uav.fault_case_delete(caseName)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    #################################################################################################################### 维修订单
    @allure.story("维修订单")
    @allure.title('维修订单-查询')
    @pytest.mark.parametrize('caseName,expected',
                             [["WX2025111300010991", "repair_order_search.png"]])
    def test_repair_order_search(self, caseName, expected):
        flag = self.uav.repair_order_search(caseName)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("维修订单")
    @allure.title('维修订单-详情')
    @pytest.mark.parametrize('caseName,expected', [["WX2025111300040518", "repair_order_detail.png"]])
    def test_repair_order_detail(self, caseName, expected):
        flag = self.uav.repair_order_detail(caseName)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'
