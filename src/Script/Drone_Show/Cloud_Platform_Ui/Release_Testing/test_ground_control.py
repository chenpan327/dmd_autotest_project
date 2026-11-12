# -*- coding: utf-8 -*-
"""
===============================================================================
                                Web自动化测试脚本
===============================================================================
脚本编号: DMD_TEST_GROUND_CONTROL_WEB_001
脚本版本: v1.0
创建日期: 2025-10-29
开发人员: 陈盼
版权所属：深圳大漠大智控技术有限公司
适用产品: 地控中心管理系统
测试类型: Web功能测试
测试环境: Python 3.10, Selenium WebDriver, Allure报告, Pytest框架

===============================================================================
测试目的:
验证地控中心Web管理系统的核心功能模块：
1. 地面站管理模块
   - 测试地面站的搜索功能
   - 验证地面站新增流程
   - 测试地面站授权用户功能
   - 验证地面站激活记录查看功能
   - 测试地面站版本文件上传功能
   - 验证地面站删除功能
2. 剧本编辑器管理模块
   - 测试剧本编辑器新增功能
   - 验证剧本编辑器查询功能
   - 测试剧本编辑器授权用户功能
   - 验证剧本编辑器版本文件上传功能
   - 测试剧本编辑器删除功能
3. 无人机组件管理模块
   - 验证无人机组件搜索功能
   - 测试无人机组件颜色表展示
   - 验证无人机组件新增功能
   - 测试无人机组件文件上传功能
   - 验证无人机组件删除功能
4. 无人机类型管理模块
   - 测试无人机类型搜索功能
   - 验证无人机类型新增功能
   - 测试无人机类型删除功能
5. 差分账号管理模块
   - 验证差分账号搜索功能
   - 测试差分账号新增功能
   - 验证差分账号编辑功能
   - 测试差分账号删除功能
6. 电台类型管理模块
   - 验证电台类型查询功能
   - 测试电台类型新增功能
   - 验证电台类型编辑功能
   - 测试电台类型删除功能
7. 组合版本管理模块
   - 测试组合版本新增功能
   - 验证组合版本编辑功能
   - 测试组合版本删除功能
8. 产品版本管理模块
   - 验证产品版本新增功能
   - 测试产品版本查询功能
   - 验证产品版本授权用户功能
   - 测试产品版本文件新增功能
   - 验证产品版本编辑与删除功能
9. 飞控参数管理模块
   - 测试飞控参数新增功能
   - 验证飞控参数搜索功能
   - 测试飞控参数编辑与删除功能
10. 飞行区域管理模块
    - 验证飞行区域新增功能
    - 测试飞行区域搜索功能
    - 验证飞行区域授权功能
    - 测试飞行区域编辑与删除功能
11. 飞行区域GIS模块
    - 验证GIS飞行区域新增功能

===============================================================================
技术架构:
- 测试框架: Pytest + Allure + Selenium
- 页面模型: Page Object Model（GroundControl）
- 页面元素: XPath定位 + 显式等待机制
- 断言方式: 文本断言 + 页面截图对比验证
- 依赖管理: 使用@pytest.mark.dependency管理用例执行顺序

===============================================================================
数据驱动设计:
1. 地面站测试数据: 名称、授权用户、版本文件路径
2. 剧本编辑器测试数据: 编辑器名称、版本文件
3. 无人机组件测试数据: 组件名称、颜色表、版本文件
4. 无人机类型测试数据: 类型名称、类型值
5. 差分账号测试数据: 账号信息
6. 产品版本与组合版本测试数据: 版本名称、文件路径
7. 飞控参数与飞行区域测试数据: 参数名称、区域名称、状态值
8. 图片对比验证: 关键功能点均配置基准截图

===============================================================================
测试步骤:
模块名称           | 用例编号 | 测试场景                | 关键验证点
------------------|----------|------------------------|-----------------------------------------
地面站管理         | GC-GS-01 | 地面站搜索              | 搜索结果验证 + 页面内容校验
                  | GC-GS-02 | 地面站新增              | 新增成功提示验证
                  | GC-GS-03 | 地面站授权用户          | 授权成功提示验证
                  | GC-GS-04 | 地面站激活记录          | 页面截图对比验证
                  | GC-GS-05 | 地面站版本文件上传      | 上传成功提示验证
                  | GC-GS-06 | 地面站删除              | 删除成功提示验证
剧本编辑器管理     | GC-PE-01 | 剧本编辑器新增          | 新增成功提示验证
                  | GC-PE-02 | 剧本编辑器查询          | 页面截图对比验证
                  | GC-PE-03 | 剧本编辑器授权用户      | 授权成功提示验证
                  | GC-PE-04 | 剧本编辑器版本文件      | 上传成功提示验证
                  | GC-PE-05 | 剧本编辑器删除          | 删除成功提示验证
无人机组件管理     | GC-UC-01 | 无人机组件搜索          | 页面截图对比验证
                  | GC-UC-02 | 无人机组件颜色表        | 页面展示验证
                  | GC-UC-03 | 无人机组件新增          | 新增成功提示验证
                  | GC-UC-04 | 无人机组件文件上传      | 上传成功提示验证
                  | GC-UC-05 | 无人机组件删除          | 删除成功提示验证
飞行区域管理       | GC-FA-01 | 飞行区域新增            | 新增成功提示验证
                  | GC-FA-02 | 飞行区域搜索            | 页面截图对比验证
                  | GC-FA-03 | 飞行区域授权            | 操作成功提示验证
                  | GC-FA-04 | 飞行区域编辑            | 编辑成功提示验证
                  | GC-FA-05 | 飞行区域删除            | 删除成功提示验证

===============================================================================
前提条件:
1. 测试环境准备:
   - Web浏览器已正确安装并可用
   - WebDriver环境配置完成
   - 地控中心系统可正常访问
   - 测试账号具备管理员权限

2. 测试数据准备:
   - 各模块基础数据已存在或可新增
   - 文件上传所需安装包、Excel文件已准备
   - 图片对比基准文件已放置在file/picture目录

3. 测试框架准备:
   - Pytest运行环境正常
   - Allure报告环境配置完成
   - selenium、allure-pytest等依赖已安装

===============================================================================
特别说明:
1. 用例依赖关系:
   - 多数模块用例存在前置依赖
   - 使用@pytest.mark.dependency确保执行顺序正确
   - 新增成功是后续查询、编辑、删除的前提

2. 验证方式:
   - 文本验证: Toast提示信息校验
   - 图片对比: 页面关键区域截图比对
   - 功能验证: 页面操作返回标志位

3. 报告集成:
   - 用例执行自动截图
   - 截图自动附加到Allure报告
   - 支持问题回溯与结果分析

===============================================================================
测试结论:
测试通过，地控中心Web各功能模块运行正常，页面操作与业务逻辑符合预期。
===============================================================================
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
import allure
import pytest
from src.Protocol.web.Web_UI import GroundControl


@allure.feature('地控中心')
class TestGroundControl:

    @pytest.fixture(scope='class', autouse=True)
    def setup_class(self, request, login):
        request.cls.uav = GroundControl(login.driver)


    ########################################################################################################### 地面站管理
    @allure.story("地面站管理")
    @allure.title('地面站管理-搜索')
    @pytest.mark.dependency(name='search_ground_station')
    @pytest.mark.parametrize('name,expected', [["3.0", "search_ground_station.png"]])
    def test_search_ground_station(self, name, expected):
        flag = self.uav.search_ground_station(name)

        assert flag
        assert self.uav._checkPictures(expected), 'screenshot unmatch !!!'

    @allure.story("地面站管理")
    @allure.title('地面站管理-新增')
    @pytest.mark.parametrize('name,expected', [("test", "添加成功")])
    @pytest.mark.dependency(name='add_ground_station')
    def test_add_ground_station(self, name, expected):
        flag = self.uav.add_ground_station(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("地面站管理")
    @allure.title('地面站-授权用户')
    @pytest.mark.parametrize('name,expected', [("test", "添加成功")])
    @pytest.mark.dependency(depends=['add_ground_station'])
    def test_authorized_user(self, name, expected):
        flag = self.uav.authorized_user(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("地面站管理")
    @allure.title('地面站-激活记录')
    @pytest.mark.parametrize('name,expected', [("test", "activation_record.png")])
    @pytest.mark.dependency(depends=['add_ground_station'])
    def test_activation_record(self, name, expected):
        flag = self.uav.activation_record(name)

        assert flag
        assert self.uav._checkPictures(expected)

    @allure.story("地面站管理")
    @allure.title('地面站-版本文件')
    @pytest.mark.parametrize('name,file_path,expected',
                             [("test", "Xshell-8.0.0084p.exe", "添加成功")])
    @pytest.mark.dependency(depends=['add_ground_station'])
    def test_edition_file(self, name, file_path, expected):
        flag = self.uav.edition_file(name, file_path)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("地面站管理")
    @allure.title('地面站-删除')
    @pytest.mark.parametrize('name,expected', [('test', '删除成功')])
    @pytest.mark.dependency(depends=['add_ground_station'])
    def test_delete_ground_station(self, name, expected):
        flag = self.uav.delete_ground_station(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ######################################################################################################## 剧本编辑器管理
    @allure.story("剧本编辑器管理")
    @allure.title('剧本编辑器-新增')
    @pytest.mark.parametrize('name,expected', [('test', '添加成功')])
    @pytest.mark.dependency(name='add_player_editor')
    def test_add_player_editor(self, name, expected):
        flag = self.uav.add_player_editor(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("剧本编辑器管理")
    @allure.title('剧本编辑器-查询')
    @pytest.mark.parametrize('name,expected', [('test', "search_player_editor.png")])
    @pytest.mark.dependency(depends=['add_player_editor'])
    def test_search_player_editor(self, name, expected):
        flag = self.uav.search_player_editor(name)

        assert flag
        assert self.uav._checkPictures(expected)

    @allure.story("剧本编辑器管理")
    @allure.title('剧本编辑器-授权用户')
    @pytest.mark.parametrize('name,expected', [('test', '添加成功')])
    @pytest.mark.dependency(depends=['add_player_editor'])
    def test_author_user(self, name, expected):
        flag = self.uav.author_user(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("剧本编辑器管理")
    @allure.title('剧本编辑器-版本文件')
    @pytest.mark.parametrize('name,file_path,expected',
                             [('test',"Xshell-8.0.0084p.exe", '添加成功')])
    @pytest.mark.dependency(depends=['add_player_editor'])
    def test_version_file(self, name, file_path, expected):
        flag = self.uav.version_file(name, file_path)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("剧本编辑器管理")
    @allure.title('剧本编辑器-删除')
    @pytest.mark.parametrize('name,expected', [('test', '删除成功')])
    @pytest.mark.dependency(depends=['add_player_editor'])
    def test_delete_player_editor(self, name, expected):
        flag = self.uav.delete_player_editor(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ######################################################################################################## 无人机组件管理
    @allure.story("无人机组件管理")
    @allure.title('无人机组件-搜索')
    @pytest.mark.parametrize('name,expected', [
        ('Newton23', "UAVComponents_search.png")])
    @pytest.mark.dependency(name='UAVComponents_search')
    def test_UAVComponents_search(self, name, expected):
        flag = self.uav.UAVComponents_search(name)

        assert flag
        assert self.uav._checkPictures(expected)

    @allure.story("无人机组件管理")
    @allure.title('无人机-组件颜色表')
    @pytest.mark.parametrize('name,expected',
                             [('Newton23', "components_colors.png")])
    @pytest.mark.dependency(depends=['UAVComponents_search'])
    def test_components_colors(self, name, expected):
        flag = self.uav.components_colors(name)

        assert flag
        assert self.uav._checkPictures(expected)

    @allure.story("无人机组件管理")
    @allure.title('无人机组件-新增')
    @pytest.mark.parametrize('name,expected', [('test', '添加成功')])
    @pytest.mark.dependency(name='components_add')
    def test_components_add(self, name, expected):
        flag = self.uav.components_add(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("无人机组件管理")
    @allure.title('无人机组件-文件上传')
    @pytest.mark.parametrize('name,file_path,expected',
                             [('test',  "Xshell-8.0.0084p.exe", '添加成功')])
    @pytest.mark.dependency(depends=['components_add'])
    def test_components_version(self, name, file_path, expected):
        flag = self.uav.components_version(name, file_path)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("无人机组件管理")
    @allure.title('无人机组件-删除')
    @pytest.mark.parametrize('name,expected', [('test', '删除成功')])
    @pytest.mark.dependency(depends=['components_add'])
    def test_components_delete(self, name, expected):
        flag = self.uav.components_delete(name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ######################################################################################################## 无人机类型管理
    @allure.story("无人机类型管理")
    @allure.title('无人机类型-搜索')
    @pytest.mark.parametrize('name,typeValue,expected',
                             [('V4', '31', "uavType_search.png")])
    @pytest.mark.dependency(name='uavType_search')
    def test_uavType_search(self, name, typeValue, expected):
        flag = self.uav.uavType_search(name, typeValue)

        assert flag
        assert self.uav._checkPictures(expected)

    @allure.story("无人机类型管理")
    @allure.title('无人机类型-新增')
    @pytest.mark.parametrize('name,typeValue,expected', [['V4', '31', '添加成功']])
    @pytest.mark.dependency(name='uavType_add')
    def test_uavType_add(self, name, typeValue, expected):
        flag = self.uav.uavType_add(name, typeValue)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("无人机类型管理")
    @allure.title('无人机类型-删除')
    @pytest.mark.parametrize('name,typeValue,expected', [['test', '999', '删除成功']])
    @pytest.mark.dependency(depends=['uavType_add'])
    def test_uavType_delete(self, name, typeValue, expected):
        flag = self.uav.uavType_delete(name, typeValue)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ######################################################################################################### 差分账号管理
    @allure.story("差分账号管理")
    @allure.title('差分账号-搜索')
    @pytest.mark.parametrize('account,expected',
                             [('qxycwf003', "differenceAcct_search.png")])
    def test_differenceAcct_search(self, account, expected):
        flag = self.uav.differenceAcct_search(account)

        assert flag
        assert self.uav._checkPictures(expected)

    @allure.story("差分账号管理")
    @allure.title('差分账号-新增')
    @pytest.mark.parametrize('account,expected', [['test', '添加成功']])
    @pytest.mark.dependency(name='differenceAcct_add')
    def test_differenceAcct_add(self, account, expected):
        flag = self.uav.differenceAcct_add(account)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("差分账号管理")
    @allure.title('差分账号-编辑')
    @pytest.mark.parametrize('account,expected', [['test', '编辑成功']])
    @pytest.mark.dependency(depends=['differenceAcct_add'])
    def test_differenceAcct_edit(self, account, expected):
        flag = self.uav.differenceAcct_edit(account)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("差分账号管理")
    @allure.title('差分账号-删除')
    @pytest.mark.parametrize('account,expected', [['test', '删除成功']])
    @pytest.mark.dependency(depends=['differenceAcct_add'])
    def test_differenceAcct_delete(self, account, expected):
        flag = self.uav.differenceAcct_delete(account)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ######################################################################################################### 电台类型管理
    @allure.story("电台类型管理")
    @allure.title('电台类型-查询')
    @pytest.mark.parametrize('radioType,expected', [['电台E', "radio_search.png"]])
    def test_radio_search(self, radioType, expected):
        flag = self.uav.radio_search(radioType)

        assert flag
        assert self.uav._checkPictures(expected)

    @allure.story("电台类型管理")
    @allure.title('电台类型-新增')
    @pytest.mark.parametrize('radioType,expected', [['test', '添加成功']])
    @pytest.mark.dependency(name='radio_add')
    def test_radio_add(self, radioType, expected):
        flag = self.uav.radio_add(radioType)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("电台类型管理")
    @allure.title('电台类型-编辑')
    @pytest.mark.parametrize('radioType,expected', [['test', '编辑成功']])
    @pytest.mark.dependency(depends=['radio_add'])
    def test_radio_edit(self, radioType, expected):
        flag = self.uav.radio_edit(radioType)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("电台类型管理")
    @allure.title('电台类型-删除')
    @pytest.mark.parametrize('radioType,expected', [['test', '删除成功']])
    @pytest.mark.dependency(depends=['radio_add'])
    def test_radio_delete(self, radioType, expected):
        flag = self.uav.radio_delete(radioType)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ######################################################################################################### 组合版本管理
    @allure.story("组合版本管理")
    @allure.title('组合版本-新增')
    @pytest.mark.parametrize('expected', ['添加成功'])
    @pytest.mark.dependency(name='version_group_add')
    def test_version_group_add(self, expected):
        flag = self.uav.version_group_add()
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("组合版本管理")
    @allure.title('组合版本-编辑')
    @pytest.mark.parametrize('expected', ['编辑成功'])
    @pytest.mark.dependency(depends=['version_group_add'])
    def test_version_group_edit(self, expected):
        flag = self.uav.version_group_edit()
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("组合版本管理")
    @allure.title('组合版本-删除')
    @pytest.mark.parametrize('expected', ['删除成功'])
    @pytest.mark.dependency(depends=['version_group_add'])
    def test_version_group_delete(self, expected):
        flag = self.uav.version_group_delete()
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ######################################################################################################### 产品版本管理
    @allure.story("产品版本管理")
    @allure.title('产品版本-新增')
    @pytest.mark.parametrize('production_name,expected', [['test', '添加成功']])
    @pytest.mark.dependency(name='production_version_add')
    def test_production_version_add(self, production_name, expected):
        flag = self.uav.production_version_add(production_name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("产品版本管理")
    @allure.title('产品版本-查询')
    @pytest.mark.parametrize('production_name,expected',
                             [('test', "production_version_search.png")])
    @pytest.mark.dependency(depends=['production_version_add'])
    def test_production_version_search(self, production_name, expected):
        flag = self.uav.production_version_search(production_name)

        assert flag
        assert self.uav._checkPictures(expected)

    @allure.story("产品版本管理")
    @allure.title('产品版本-授权用户')
    @pytest.mark.parametrize('production_name,expected', [['test', '添加成功']])
    @pytest.mark.dependency(depends=['production_version_add'])
    def test_production_version_user(self, production_name, expected):
        flag = self.uav.production_version_user(production_name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("产品版本管理")
    @allure.title('产品版本-新增版本文件')
    @pytest.mark.parametrize('production_name,file_path,expected',
                             [['test', "Xshell-8.0.0084p.exe", '添加成功']])
    @pytest.mark.dependency(depends=['production_version_add'])
    def test_production_version_addfile(self, production_name, file_path, expected):
        flag = self.uav.production_version_addfile(production_name, file_path)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("产品版本管理")
    @allure.title('产品版本-编辑')
    @pytest.mark.parametrize('production_name,expected', [['test', '编辑成功']])
    @pytest.mark.dependency(depends=['production_version_add'])
    def test_production_version_edit(self, production_name, expected):
        flag = self.uav.production_version_edit(production_name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("产品版本管理")
    @allure.title('产品版本-删除')
    @pytest.mark.parametrize('production_name,expected', [['test', '删除成功']])
    @pytest.mark.dependency(depends=['production_version_add'])
    def test_production_version_delete(self, production_name, expected):
        flag = self.uav.production_version_delete(production_name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ######################################################################################################### 飞控参数管理
    @allure.story("飞控参数管理")
    @allure.title('飞控参数-新增')
    @pytest.mark.parametrize('param_name,expected', [['test', '添加成功']])
    @pytest.mark.dependency(name='flight_parameters_add')
    def test_flight_parameters_add(self, param_name, expected):
        flag = self.uav.flight_parameters_add(param_name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("飞控参数管理")
    @allure.title('飞控参数-搜索')
    @pytest.mark.parametrize('param_name,expected',
                             [['test', "flight_parameters_search.png"]])
    @pytest.mark.dependency(depends=['flight_parameters_add'])
    def test_flight_parameters_search(self, param_name, expected):
        flag = self.uav.flight_parameters_search(param_name)

        assert flag
        assert self.uav._checkPictures(expected)

    @allure.story("飞控参数管理")
    @allure.title('飞控参数-编辑')
    @pytest.mark.parametrize('param_name,expected', [['test', '编辑成功']])
    @pytest.mark.dependency(depends=['flight_parameters_add'])
    def test_flight_parameters_edit(self, param_name, expected):
        flag = self.uav.flight_parameters_edit(param_name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("飞控参数管理")
    @allure.title('飞控参数-删除')
    @pytest.mark.parametrize('param_name,expected', [['test', '删除成功']])
    @pytest.mark.dependency(depends=['flight_parameters_add'])
    def test_flight_parameters_delete(self, param_name, expected):
        flag = self.uav.flight_parameters_delete(param_name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ######################################################################################################### 飞行区域管理
    @allure.story("飞行区域管理")
    @allure.title('飞行区域-新增')
    @pytest.mark.parametrize('area_name,expected', [['test1009', '添加成功']])
    @pytest.mark.dependency(name='flight_area_add')
    def test_flight_area_add(self, area_name, expected):
        flag = self.uav.flight_area_add(area_name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("飞行区域管理")
    @allure.title('飞行区域-搜索')
    @pytest.mark.parametrize('area_name,status,expected',
                             [('test1009', 'enable', "flight_area_search.png")])
    @pytest.mark.dependency(depends=['flight_area_add'])
    def test_flight_area_search(self, area_name, status, expected):
        flag = self.uav.flight_area_search(area_name, status)

        assert flag
        assert self.uav._checkPictures(expected)

    @allure.story("飞行区域管理")
    @allure.title('飞行区域-授权')
    @pytest.mark.parametrize('area_name,expected', [['test1009', '操作成功']])
    @pytest.mark.dependency(depends=['flight_area_add'])
    def test_flight_area_authorize(self, area_name, expected):
        flag = self.uav.flight_area_authorize(area_name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("飞行区域管理")
    @allure.title('飞行区域-编辑')
    @pytest.mark.parametrize('area_name,expected', [['test1009', '编辑成功']])
    @pytest.mark.dependency(depends=['flight_area_add'])
    def test_flight_area_edit(self, area_name, expected):
        flag = self.uav.flight_area_edit(area_name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    @allure.story("飞行区域管理")
    @allure.title('飞行区域-删除')
    @pytest.mark.parametrize('area_name,expected', [['test1009', '删除成功']])
    @pytest.mark.dependency(depends=['flight_area_add'])
    def test_flight_area_delete(self, area_name, expected):
        flag = self.uav.flight_area_delete(area_name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text

    ######################################################################################################### 飞行区域GIS
    @allure.story("飞行区域GIS")
    @allure.title('飞行区域-新增')
    @pytest.mark.parametrize('area_name,expected', [['test1009', '添加成功']])
    def test_area_GIS_add(self, area_name, expected):
        flag = self.uav.area_GIS_add(area_name)
        text = self.uav.get_toast_text()

        assert flag
        assert expected in text
