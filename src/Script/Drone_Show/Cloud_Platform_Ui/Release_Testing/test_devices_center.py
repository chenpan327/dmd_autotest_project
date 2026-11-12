# -*- coding: utf-8 -*-
"""
===============================================================================
                                Web自动化测试脚本
===============================================================================
脚本编号: DMD_TEST_DEVICE_CENTER_WEB_001
脚本版本: v1.0
创建日期: 2025-10-29
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: 设备中心管理系统
测试类型: Web功能测试
测试环境: Python 3.10, Selenium WebDriver, Allure报告, Pytest框架

===============================================================================
测试目的:
验证【设备中心】Web 管理系统核心业务模块的功能完整性与页面稳定性，
确保设备、故障、维修、电池、飞行、表演及辅助设备等模块的关键流程
在真实浏览器环境下能够正常执行并正确反馈结果。

重点验证内容包括：
1. 无人机管理模块
   - 设备搜索、新增、删除
   - 设备 Excel 文件导入
2. 故障记录模块
   - 新增故障记录
   - 故障送修操作
   - 故障记录 Excel 导入
3. 维修记录模块
   - 维修记录搜索功能
4. 电池管理模块
   - 电池记录搜索
   - 记录分析
   - 电池信息编辑与详情查看
5. 表演记录模块
   - 表演记录搜索与详情查看
6. 飞行记录模块
   - 飞行记录搜索与详情查看
7. 辅助设备模块
   - 新增、查询、编辑、删除辅助设备

===============================================================================
技术架构:
- 测试框架: Pytest + Allure + Selenium WebDriver
- 自动化模式: Page Object Model（POM）
- 页面元素定位: XPath
- 同步机制: 显式等待（WebDriverWait + ExpectedConditions）
- 用例依赖管理: pytest.mark.dependency
- 日志采集: 浏览器 Console 日志（driver.get_log）

===============================================================================
数据驱动设计:
1. 设备类测试数据:
   - 无人机 SN（WV43210X0000 / WV43210X1111 等）
   - 电池 SN（BL3SN58B0000 / V3S240801-2805）
   - 飞行设备 SN（WV4015140099）
2. 文件导入数据:
   - 设备管理清单.xls
   - 故障记录.xls
3. UI 校验数据:
   - 页面截图比对（search_SN.png / detail_battery.png 等）
4. 提示信息校验:
   - 添加成功 / 删除成功 / 操作成功 / 文件导入成功

===============================================================================
测试步骤:
模块名称       | 用例编号 | 测试场景               | 关键验证点
--------------|----------|------------------------|-----------------------------------------
无人机管理     | TEST-01  | 设备搜索               | 搜索结果展示 + 页面截图比对
               | TEST-02  | 新增设备               | 添加成功提示验证
               | TEST-03  | 删除设备               | 删除成功提示验证
               | TEST-04  | 导入设备               | 文件导入成功提示验证
故障记录       | TEST-05  | 新增故障记录           | 添加成功提示验证
               | TEST-06  | 故障记录送修           | 操作成功提示验证
               | TEST-07  | 导入故障记录           | 文件导入成功提示验证
维修记录       | TEST-08  | 搜索维修记录           | 页面截图比对验证
电池管理       | TEST-09  | 搜索电池记录           | 页面截图比对验证
               | TEST-10  | 记录分析               | 分析页面截图验证
               | TEST-11  | 编辑电池信息           | 编辑页面截图验证
               | TEST-12  | 查看电池详情           | 详情页面截图验证
表演记录       | TEST-13  | 表演记录搜索           | 页面截图比对验证
               | TEST-14  | 表演记录详情           | 详情页面截图验证
飞行记录       | TEST-15  | 飞行记录搜索           | 页面截图比对验证
               | TEST-16  | 飞行记录详情           | 详情页面截图验证
辅助设备       | TEST-17  | 新增辅助设备           | 添加成功提示验证
               | TEST-18  | 查询辅助设备           | 页面截图比对验证
               | TEST-19  | 编辑辅助设备           | 编辑成功提示验证
               | TEST-20  | 删除辅助设备           | 删除成功提示验证

===============================================================================
前提条件:
1. 测试环境准备:
   - Web 浏览器（Chrome / Edge）已安装
   - WebDriver 已正确配置并可用
   - 设备中心系统可正常访问
   - 测试账号具备设备中心全部操作权限

2. 测试数据准备:
   - 测试用设备、电池、订单数据已存在或可创建
   - Excel 导入文件已放置在 file/excel 目录
   - 图片比对基准文件已准备在 src/Protocol/image 目录

3. 测试框架准备:
   - pytest、selenium、allure-pytest 等依赖已安装
   - Allure 报告环境已配置完成

===============================================================================
特别说明:
1. 用例依赖关系:
   - 设备新增 → 删除 → 导入 存在前后依赖
   - 故障记录、维修、电池、辅助设备等模块
     通过 pytest.mark.dependency 控制执行顺序

2. 验证方式:
   - 功能验证: 方法返回标志位 flag
   - 文本验证: 页面 Toast 提示信息
   - UI 验证: 页面截图与基准图片比对

3. 报告集成:
   - 每个测试用例执行完成后自动截图
   - 自动采集浏览器 Console 日志
   - 截图与日志统一附加至 Allure 测试报告

===============================================================================
测试结论:
设备中心各功能模块运行稳定，
业务流程执行正确，页面展示与提示信息符合预期，
满足 Web 自动化测试验证要求。
===============================================================================
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
import allure
import pytest
from src.Protocol.web.Web_UI import DevicesCenter


@allure.feature('设备中心')
@pytest.mark.usefixtures("login")
class TestDevicesCenter:

    @pytest.fixture(scope='class', autouse=True)
    def setup_class(self, request, login):
        request.cls.uav = DevicesCenter(login.driver)
        yield
        request.cls.uav.delete_device("WV43210X0000")

    ############################################################################################################无人机管理
    @allure.story("无人机管理")
    @allure.title('无人机管理-搜索')
    @pytest.mark.parametrize('sn,expected', [("WV43210X1111", "search_SN.png")])
    def test_search_SN(self, sn, expected):
        flag = self.uav.search_SN(sn)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("无人机管理")
    @allure.title('无人机管理-新增')
    @pytest.mark.parametrize('sn,expected', [("WV43210X0000", "添加成功")])
    @pytest.mark.dependency(name='add_device')
    def test_add_device(self, sn, expected):
        flag = self.uav.add_device(sn)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("无人机管理")
    @allure.title('无人机管理-删除')
    @pytest.mark.parametrize('sn,expected', [("WV43210X0000", "删除成功")])
    @pytest.mark.dependency(name='delete_device',depends=['add_device'])
    def test_delete_device(self, sn, expected):
        flag = self.uav.delete_device(sn)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("无人机管理")
    @allure.title('无人机管理-导入')
    @pytest.mark.parametrize('file_path,expected', [("设备管理清单.xls", "文件导入成功")])
    @pytest.mark.dependency(name='import_device', depends=['delete_device'])
    def test_import_device(self, file_path, expected):
        flag = self.uav.import_device(file_path)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ############################################################################################################# 故障记录
    @allure.story("故障记录")
    @allure.title('故障记录-新增')
    @pytest.mark.parametrize('sn,expected', [("WV43210X0000", "添加成功")])
    @pytest.mark.dependency(name='add_fault_record', depends=['import_device'])
    def test_add_fault_record(self, sn, expected):
        flag = self.uav.add_fault_record(sn)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("故障记录")
    @allure.title('故障记录-导入')
    @pytest.mark.parametrize('file_path,expected', [(f"故障记录.xls", "文件导入成功")])
    @pytest.mark.dependency(depends=['import_device'])
    def test_import_records(self, file_path, expected):
        flag = self.uav.import_records(file_path)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("故障记录")
    @allure.title('故障记录-送修')
    @pytest.mark.parametrize('sn,expected', [("WV43210X0000", "操作成功")])
    @pytest.mark.dependency(depends=['add_fault_record'])
    def test_send_repair(self, sn, expected):
        flag = self.uav.send_repair(sn)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ################################################################################################################### 维修记录
    @allure.story("维修记录")
    @allure.title('维修记录-搜索')
    @pytest.mark.parametrize('sn,expected',
                             [["WV3000000019", "search_repare_record.png"]])
    def test_search_repare_record(self, sn, expected):
        flag = self.uav.search_repare_record(sn)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    ############################################################################################################# 电池管理
    @allure.story("电池管理")
    @allure.title('电池管理-搜索')
    @pytest.mark.parametrize('sn,expected', [("BL3SN58B0000", "search_battery.png")])
    @pytest.mark.dependency(name='search_battery')
    def test_search_battery(self, sn, expected):
        flag = self.uav.search_battery(sn)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("电池管理")
    @allure.title('电池管理-记录分析')
    @pytest.mark.parametrize('sn,no,expected',
                             [("V3S240801-2805", "18021336-8b38-45fc-8286-dbc78dfa532e",
                               "record_analysis.png")])
    @pytest.mark.dependency(depends=['search_battery'])
    def test_record_analysis(self, sn, no, expected):
        flag = self.uav.record_analysis(sn, no)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("电池管理")
    @allure.title('电池管理-编辑')
    @pytest.mark.parametrize('sn,expected', [("V3S240801-2805", "edit_battery.png")])
    @pytest.mark.dependency(depends=['search_battery'])
    def test_edit_battery(self, sn, expected):
        flag = self.uav.edit_battery(sn)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("电池管理")
    @allure.title('电池管理-详情')
    @pytest.mark.parametrize('sn,expected', [("V3S240801-2805", "detail_battery.png")])
    @pytest.mark.dependency(depends=['search_battery'])
    def test_detail_battery(self, sn, expected):
        flag = self.uav.detail_battery(sn)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    ############################################################################################################# 表演记录
    @allure.story("表演记录")
    @allure.title('表演记录-搜索')
    @pytest.mark.parametrize('No,expected', [
        ("83e0c8c2-2705-49f1-ae64-7bf2fc27d37f", "search_records.png")])
    @pytest.mark.dependency(name='search_records')
    def test_search_records(self, No, expected):
        flag = self.uav.search_records(No)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("表演记录")
    @allure.title('表演记录-详情')
    @pytest.mark.dependency(depends=['search_records'])
    @pytest.mark.parametrize('No,expected', [
        ("83e0c8c2-2705-49f1-ae64-7bf2fc27d37f", "detail_record.png")])
    def test_detail_record(self, No, expected):
        flag = self.uav.detail_record(No)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    ############################################################################################################# 飞行记录
    @allure.story("飞行记录")
    @allure.title('飞行记录-搜索')
    @pytest.mark.dependency(name='search_device')
    @pytest.mark.parametrize('SN,expected',
                             [("WV4015140099", "search_device.png")])
    def test_search_device(self, SN, expected):
        flag = self.uav.search_device(SN)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("飞行记录")
    @allure.title('飞行记录-详情')
    @pytest.mark.dependency(depends=['search_device'])
    @pytest.mark.parametrize('SN,expected',
                             [("WV4015140099", "detail_flight.png")])
    def test_detail_flight(self, SN, expected):
        flag = self.uav.detail_flight(SN)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    ############################################################################################################# 辅助设备
    @allure.story("辅助设备")
    @allure.title('辅助设备-新增')
    @pytest.mark.dependency(name='assist_equipment_add')
    @pytest.mark.parametrize('SN,expected', [["CL34S56P9999", "添加成功"]])
    def test_assist_equipment_add(self, SN, expected):
        flag = self.uav.assist_equipment_add(SN)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("辅助设备")
    @allure.title('辅助设备-查询')
    @pytest.mark.dependency(depends=['assist_equipment_add'])
    @pytest.mark.parametrize('SN,expected',
                             [("CL34S56P9999", "assist_equipment_search.png")])
    def test_assist_equipment_search(self, SN, expected):
        flag = self.uav.assist_equipment_search(SN)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("辅助设备")
    @allure.title('辅助设备-编辑')
    @pytest.mark.dependency(depends=['assist_equipment_add'])
    @pytest.mark.parametrize('SN,expected', [["CL34S56P9999", "编辑成功"]])
    def test_assist_equipment_edit(self, SN, expected):
        flag = self.uav.assist_equipment_edit(SN)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("辅助设备")
    @allure.title('辅助设备-删除')
    @pytest.mark.dependency(depends=['assist_equipment_add'])
    @pytest.mark.parametrize('SN,expected', [["CL34S56P9999", "删除成功"]])
    def test_assist_equipment_delete(self, SN, expected):
        flag = self.uav.assist_equipment_delete(SN)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text
