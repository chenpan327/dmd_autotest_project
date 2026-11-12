# -*- coding: utf-8 -*-
import json
import os
import sys
from datetime import datetime, timedelta

from utils.logger import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
import allure
from jsonpath_ng.ext import parse
from src.Protocol.web.Web_API import WEBCloud, root_path
from src.Script.Drone_Show.Cloud_Platform_Api.Unit_Module_Testing.conftest import data_driver


@allure.feature('接口单元测试')
class TestApiUnit:
    def setup_class(cls):
        logger.info("=============初始化测试类对象=======================")
        cls.runner = WEBCloud()
        cls.runner.get_token()
        cls._cache = {}

    # =========================
    # 飞行项目与设备
    # =========================
    @allure.story("云平台")
    @allure.title('获取token接口')
    @data_driver("test_get_token")
    def test_get_token(self, args, jsonpath_args, expected):
        self.runner.get_token(dynamic_args=args, assertions=expected)

    @allure.story("云平台")
    @allure.title('查询设备')
    @data_driver("test_search_device")
    def test_search_device(self, args, jsonpath_args, expected):
        self.runner.search_device(dynamic_args=args, assertions=expected)

    @allure.story("云平台")
    @allure.title('新建飞行项目')
    @data_driver("test_add_project")
    def test_add_project(self, args, jsonpath_args, expected):
        current = datetime.today()
        curr_date = current.strftime('%Y-%m-%d')
        args.update({"projectName": f"test{curr_date}", "expectedStartDate": curr_date, "expectedEndDate": curr_date})
        self.runner.add_project(dynamic_args=args, jsonpath_args=jsonpath_args, assertions=expected)

    @allure.story("云平台")
    @allure.title('计算租借设备价格')
    @data_driver("test_calculate_price")
    def test_calculate_price(self, args, jsonpath_args, expected):
        current = datetime.today()
        curr_date = current.strftime('%Y-%m-%d')

        future_date = current + timedelta(days=4)
        future_date = future_date.strftime('%Y-%m-%d')
        args.update({"rentTime": curr_date, "rentTimeEnd": future_date})

        self.runner.calculate_price(dynamic_args=args, jsonpath_args=jsonpath_args, assertions=expected)

    @allure.story("云平台")
    @allure.title('飞行项目看板')
    @data_driver("test_flight_project_dashboard")
    def test_flight_project_dashboard(self, args, jsonpath_args, expected):
        self.runner.flight_project_dashboard(dynamic_args=args, assertions=expected)

    @allure.story("云平台")
    @allure.title('项目设备调出')
    @data_driver("test_equipment_out_item")
    def test_equipment_out_item(self, args, jsonpath_args, expected):
        self.runner.equipment_out_item(dynamic_args=args, assertions=expected)


    # =========================
    # 地面站
    # =========================

    @allure.story("地面站")
    @allure.title('新增地面站')
    @data_driver("test_add_dgcs")
    def test_add_dgcs(self, args, jsonpath_args, expected):
        resp = self.runner.add_dgcs(dynamic_args=args, assertions=expected)

    @allure.story("地面站")
    @allure.title('地面站列表查询')
    @data_driver("test_dgcs_search")
    def test_dgcs_search(self, args, jsonpath_args, expected):
        resp = self.runner.dgcs_search(dynamic_args=args, assertions=expected)
        # 提取 id 和 name 存到缓存字典
        records = resp.get("result", {}).get("records", [])
        self._cache.update({r["name"]: r["id"] for r in records})

    @allure.story("地面站")
    @allure.title('添加用户')
    @data_driver("test_dgcs_add_user")
    def test_dgcs_add_user(self, args, jsonpath_args, expected):
        stationId = self._cache['test']
        current = datetime.today()

        future_date = current + timedelta(days=3)
        future_date = future_date.strftime('%Y-%m-%d')

        args.update({"stationId": stationId, "expired": f"{future_date} 00:00:00"})

        self.runner.dgcs_add_user(dynamic_args=args, assertions=expected)

    @allure.story("地面站")
    @allure.title('地面站授权用户查询')
    @data_driver("test_dgcs_user_list")
    def test_dgcs_user_list(self, args, jsonpath_args, expected):
        stationId = self._cache['test']
        args.update({"stationId": stationId})

        resp = self.runner.dgcs_user_list(dynamic_args=args, assertions=expected)
        records = resp.get("result", {}).get("records", [])
        self._cache.update({r["username"]: r["id"] for r in records})

    @allure.story("地面站")
    @allure.title('地面站授权功能查询')
    @data_driver("test_dgcs_func_list")
    def test_dgcs_func_list(self, args, jsonpath_args, expected):
        stationId = self._cache['4.0']
        args.update({"stationId": stationId})

        self.runner.dgcs_func_list(dynamic_args=args, assertions=expected)

    @allure.story("地面站")
    @allure.title('用户激活')
    @data_driver("test_activation_records")
    def test_activation_records(self, args, jsonpath_args, expected):
        self.runner.activation_records(dynamic_args=args, assertions=expected)

    @allure.story("地面站")
    @allure.title('用户信息')
    @data_driver("test_user_details")
    def test_user_details(self, args, jsonpath_args, expected):
        self.runner.user_details(dynamic_args=args, assertions=expected)

    @allure.story("地面站")
    @allure.title('删除授权用户')
    @data_driver("test_dgcs_del_user")
    def test_dgcs_del_user(self, args, jsonpath_args, expected):
        id = self._cache.get("alan")
        args.update({"id": id})
        self.runner.dgcs_del_user(dynamic_args=args, assertions=expected)

    @allure.story("地面站")
    @allure.title('飞行项目列表')
    @data_driver("test_project_list")
    def test_project_list(self, args, jsonpath_args, expected):
        self.runner.project_list(dynamic_args=args, assertions=expected)

    @allure.story("地面站")
    @allure.title('地面站-删除')
    @data_driver("test_delete_dgcs")
    def test_delete_dgcs(self, args, jsonpath_args, expected):
        stationId = self._cache['test']
        args.update({"id": stationId})
        self.runner.delete_dgcs(dynamic_args=args, assertions=expected)


    # =========================
    # 设备送修
    # =========================
    @allure.story("云平台")
    @allure.title('设备送修')
    @data_driver("test_send_repair")
    def test_send_repair(self, args, jsonpath_args, expected):
        resp = self.runner.send_repair(dynamic_args=args, jsonpath_args=jsonpath_args, assertions=expected)
        msg = resp.get("message")
        if msg == "操作成功":
            id = parse("$.result.id").find(resp)[0].value
            self._cache["order_id"] = id

    @allure.story("云平台")
    @allure.title('取消维修订单')
    @data_driver("test_cancel_order")
    def test_cancel_order(self, args, jsonpath_args, expected):
        id = self._cache.get("order_id")
        args.update({"id": id})

        self.runner.cancel_order(dynamic_args=args, assertions=expected)

    # =========================
    # 无人机设备
    # =========================
    @allure.story("无人机")
    @allure.title('设备状态统计')
    @data_driver("test_device_count_status")
    def test_device_count_status(self, args, jsonpath_args, expected):
        self.runner.device_count_status(dynamic_args=args, assertions=expected)

    @allure.story("无人机")
    @allure.title('设备使用率统计')
    @data_driver("test_device_usage_rate")
    def test_device_usage_rate(self, args, jsonpath_args, expected):
        self.runner.device_usage_rate(dynamic_args=args, assertions=expected)

    @allure.story("无人机")
    @allure.title('设备类型统计')
    @data_driver("test_device_count_type")
    def test_device_count_type(self, args, jsonpath_args, expected):
        self.runner.device_count_type(dynamic_args=args, assertions=expected)

