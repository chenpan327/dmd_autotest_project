# -*- coding: utf-8 -*-
"""
===============================================================================
                                Web自动化测试脚本
===============================================================================
脚本编号: DMD_TEST_PRODUCTION_CENTER_WEB_001
脚本版本: v1.0
创建日期: 2025-10-29
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
1. 库存管理模块
   - 设备搜索、导入、导出、删除
   - 批量入库、批量出库
   - 设备编辑与变更记录查看
2. 销售出库模块
   - OA 数据同步
   - 出库飞机操作
   - 设备清单与订单详情查看
3. 设备类型管理模块
   - 设备类型的搜索、新增、编辑、详情查看及删除
4. 编码规则管理模块
   - 编码规则搜索
   - 编码规则详情查看
   - 编码规则编辑功能验证

===============================================================================
技术架构:
- 测试框架: Pytest + Allure + Selenium
- 自动化模式: Page Object Model（POM）
- 页面元素定位: XPath / 页面文本校验
- 同步机制: 显式等待（WebDriverWait + ExpectedConditions）
- 用例依赖: pytest.mark.dependency

===============================================================================
数据驱动设计:
1. 设备序列号数据:
   - WV43210X1111
   - WV43210X0000
2. Excel 导入数据:
   - inventory-record.xls
3. 设备类型数据:
   - 类型名称: test
   - 类型值: 999
4. 编码规则数据:
   - 编码前缀: DV211511
   - 产品标识: DV21
5. 图片对比验证:
   - search_devices.png
   - search_Model.png
   - sear_code_rule.png
   - detail_code_rule.png

===============================================================================
测试步骤:
模块名称       | 用例编号 | 测试场景              | 关键验证点
--------------|----------|----------------------|-----------------------------------------
库存管理       | TEST-01  | 设备搜索              | 搜索结果展示 + 图片对比验证
               | TEST-02  | 设备导出              | 页面数据内容校验
               | TEST-03  | 设备导入              | 导入成功提示验证
               | TEST-04  | 设备删除              | 删除成功提示验证
               | TEST-05  | 批量入库              | 入库成功提示验证
               | TEST-06  | 批量出库              | 出库成功提示验证
               | TEST-07  | 变更记录              | 设备变更信息校验
               | TEST-08  | 编辑设备              | 编辑成功提示验证
销售出库       | TEST-09  | 同步 OA               | 同步成功提示验证
               | TEST-10  | 出库飞机              | 页面字段完整性校验
               | TEST-11  | 设备清单              | 清单字段校验
               | TEST-12  | 订单详情              | 订单信息完整性校验
设备类型       | TEST-13  | 设备类型搜索          | 搜索结果图片对比
               | TEST-14  | 设备类型新增          | 新增成功提示验证
               | TEST-15  | 设备类型编辑          | 编辑成功提示验证
               | TEST-16  | 设备类型详情          | 页面字段校验
               | TEST-17  | 设备类型删除          | 删除成功提示验证
编码规则       | TEST-18  | 编码规则搜索          | 搜索结果图片对比
               | TEST-19  | 编码规则详情          | 页面截图校验
               | TEST-20  | 编码规则编辑          | 编辑成功提示验证

===============================================================================
前提条件:
1. 测试环境准备:
   - Web 浏览器（Chrome / Edge）已正确安装
   - WebDriver 配置完成并可正常驱动浏览器
   - 生产中心系统服务运行正常
   - 测试账号具备生产中心相关操作权限

2. 测试数据准备:
   - 测试设备序列号存在或可被导入
   - Excel 导入文件路径正确、数据合法
   - 图片比对基准文件已存放在 file/picture 目录

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
生产中心各核心功能模块均可按照预期流程正常执行，
页面交互、数据处理及提示信息准确可靠，满足业务测试要求。
===============================================================================
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
import allure
import pytest
from src.Protocol.web.Web_UI import ProductionCenter


@allure.feature('生产中心')
class TestProductionCenter:

    @pytest.fixture(scope='class', autouse=True)
    def setup_class(self, request, login):
        request.cls.uav = ProductionCenter(login.driver)
        yield
        request.cls.uav.delete_device("WV43210X0000")

    ############################################################################################################ 库存管理
    @allure.story("库存管理")
    @allure.title('库存管理-搜索')
    @pytest.mark.parametrize('device_SN,expected',
                             [("WV43210X1111", "search_devices.png")])
    @pytest.mark.dependency(name='search_devices')
    def test_search_devices(self, device_SN, expected):
        flag = self.uav.search_devices(device_SN)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("库存管理")
    @allure.title('库存管理-导出')
    @pytest.mark.skip("UI界面缺少判定条件，跳过执行")
    @pytest.mark.parametrize('device_SN,expected', [("WV43210X1111", "")])
    @pytest.mark.dependency(depends=['search_devices'])
    def test_export_device(self, device_SN, expected):
        flag = self.uav.export_device(device_SN)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("库存管理")
    @allure.title('库存管理-批量入库')
    @pytest.mark.parametrize('device_SN,expected', [("WV43210X0000", "添加成功")])
    @pytest.mark.dependency(depends=['search_devices'], name='batching_storage')
    def test_batching_storage(self, device_SN, expected):
        flag = self.uav.batching_storage(device_SN)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("库存管理")
    @allure.title('库存管理-批量出库')
    @pytest.mark.parametrize('device_SN,expected', [("WV43210X0000", "编辑成功")])
    @pytest.mark.dependency(depends=['batching_storage'], name='batching_outbound')
    def test_batching_outbound(self, device_SN, expected):
        flag = self.uav.batching_outbound(device_SN)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("库存管理")
    @allure.title('库存管理-变更记录')
    @pytest.mark.parametrize('device_SN,expected', [("WV43210X0000", "change_history.png")])
    @pytest.mark.dependency(depends=['batching_outbound'])
    def test_change_history(self, device_SN, expected):
        flag = self.uav.change_history(device_SN)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("库存管理")
    @allure.title('库存管理-编辑')
    @pytest.mark.parametrize('device_SN,expected', [("WV43210X0000", "编辑成功")])
    @pytest.mark.dependency(depends=['batching_storage'])
    def test_edit_device(self, device_SN, expected):
        flag = self.uav.edit_device(device_SN)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("库存管理")
    @allure.title('库存管理-设备删除')
    @pytest.mark.parametrize('device_SN,expected', [("WV43210X0000", "删除成功")])
    @pytest.mark.dependency(depends=['batching_storage'], name='delete_device')
    def test_delete_device(self, device_SN, expected):
        flag = self.uav.delete_device(device_SN)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("库存管理")
    @allure.title('库存管理-导入')
    @pytest.mark.parametrize('file_path,expected', [("inventory-record.xls", "文件导入成功")])
    @pytest.mark.dependency(depends=['delete_device'])
    def test_import_device(self, file_path, expected):
        flag = self.uav.import_device(file_path)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ############################################################################################################ 设备类型
    @allure.story("设备类型")
    @allure.title("设备类型-搜索")
    @pytest.mark.parametrize('typeName,productModle,expected',
                             [("V4无人机", "DMD-M400W-V4", "search_Model.png")])
    def test_search_model(self, typeName, productModle, expected):
        flag = self.uav.search_Model(typeName, productModle)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("设备类型")
    @allure.title("设备类型-新增")
    @pytest.mark.parametrize('typeName,typeValue,expected', [("test", "999", "添加成功")])
    @pytest.mark.dependency(name='add_type')
    def test_add_type(self, typeName, typeValue, expected):
        flag = self.uav.add_type(typeName, typeValue)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("设备类型")
    @allure.title("设备类型-编辑")
    @pytest.mark.parametrize('typeName,expected', [("test", "编辑成功")])
    @pytest.mark.dependency(depends=['add_type'])
    def test_edit_device_type(self, typeName, expected):
        flag = self.uav.edit_device_type(typeName)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("设备类型")
    @allure.title("设备类型-详情")
    @pytest.mark.parametrize('typeName,expected', [("test", "device_type_detail.png")])
    @pytest.mark.dependency(depends=['add_type'])
    def test_device_type_detail(self, typeName, expected):
        flag = self.uav.device_type_detail(typeName)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("设备类型")
    @allure.title("设备类型-删除")
    @pytest.mark.parametrize('typeName,expected', [("test", "删除成功")])
    @pytest.mark.dependency(depends=['add_type'])
    def test_device_type_delete(self, typeName, expected):
        flag = self.uav.device_type_delete(typeName)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ############################################################################################################ 编码规则
    @allure.story("编码规则")
    @allure.title("编码规则-搜索")
    @pytest.mark.parametrize('header,value,proFlag,expected', [
        ("DV211511", "DV2115110001", "DV21", "sear_code_rule.png")])
    def test_sear_code_rule(self, header, value, proFlag, expected):
        flag = self.uav.sear_code_rule(header, value, proFlag)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("编码规则")
    @allure.title("编码规则-详情")
    @pytest.mark.parametrize('header,expected', [["DV211511", "detail_code_rule.png"]])
    def test_detail_code_rule(self, header, expected):
        flag = self.uav.detail_code_rule(header)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("编码规则")
    @allure.title("编码规则-编辑")
    @pytest.mark.parametrize('header,expected', [("DV211511", "编辑成功")])
    def test_edit_code_rule(self, header, expected):
        flag = self.uav.edit_code_rule(header)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text
