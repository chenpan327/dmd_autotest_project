# -*- coding: utf-8 -*-
import json
import os
import sys
from datetime import datetime, timedelta

from utils.logger import log_manager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
import allure
from jsonpath_ng.ext import parse
from src.Script.Drone_Show.Cloud_Platform_Api.Release_Testing.conftest import build_parametrize
from src.Protocol.web.Web_API import WEBCloud


@allure.feature('WEB接口测试')
class TestWEBCloud:

    def setup_class(cls):
        log_manager.logger.info("=============初始化测试类对象=======================")
        cls.runner = WEBCloud()

        cls.runner.get_token(dynamic_args={"username": cls.runner.username, "password": cls.runner.password})
        cls._cache = {}

    @allure.description("""
        测试步骤:
        1. 地面站飞机入库
        2. 获取待绑定设备列表id
        3. 绑定设备
        4. 编辑设备（修改设备状态）
        5. 检查设备
        6. 新建飞行项目
        7. 查询飞行项目
        8. 新增自用订单
        9. 搜索自用订单
        10. 自用订单出库
        11. 检查设备
        12. 查询出入库记录
        13. 自用订单入库
        14. 检查设备
        15. 编辑设备（修改设备状态）
        16. 出借方上架资源
        17. 价格查询
        18. 借用方下单
        19. 查询租借订单
        20. 获取租借订单详细信息
        21. 确认租借订单
        22. 借出方出库
        23. 借入方入库
        24. 借入方出库
        25. 借出方入库
        26. 检查飞行项目看板
        27. 检查项目设备调出
        28. 删除设备

        测试环境:
            - uat：https://cloud-uat.dmduav.com/

        预期结果:
        - 所有接口请求通过，接口返回满足校验
        """)
    @allure.story("飞行项目-自用订单")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_fly_project(self):
        with allure.step("地面站飞机入库"):
            args, expected = build_parametrize("gdbc_device_inbound")
            self.runner.gdbc_device_inbound(dynamic_args=args, assertions=expected)

        with allure.step("获取待绑定设备列表id"):
            args, expected = build_parametrize("bind_list")
            args.update({"createBy": self.runner.username})

            response = self.runner.bind_list(dynamic_args=args, assertions=expected)
            device_id = parse("$.result.records[0].id").find(response)[0].value

        with allure.step("绑定设备"):
            args, expected = build_parametrize("bind_device")
            self.runner.bind_device(dynamic_args=args, assertions=expected)

        with allure.step("编辑设备（修改设备状态）"):
            args, expected = build_parametrize("edit_device")
            args.update({"id": device_id})
            self.runner.edit_device(dynamic_args=args, assertions=expected)

        with allure.step("检查设备"):
            args, expected = build_parametrize("search_device")
            self.runner.search_device(dynamic_args=args, assertions=expected)

        with allure.step("新建飞行项目"):
            current = datetime.today()
            curr_date = current.strftime('%Y-%m-%d')
            project_name = f"test{curr_date}"

            args, expected = build_parametrize("add_project")
            args.update({"expectedStartDate": curr_date, "expectedEndDate": curr_date, "projectName": project_name})

            self.runner.add_project(dynamic_args=args, assertions=expected)
            self._cache['project_name'] = project_name

        with allure.step("查询飞行项目"):
            args, expected = build_parametrize("search_project")
            args.update({"projectName": project_name})

            response = self.runner.search_project(dynamic_args=args, assertions=expected)
            project_id = parse("$.result.records[0].id").find(response)[0].value

            self._cache['project_id'] = project_id

        with allure.step("新增自用订单"):
            args, expected = build_parametrize("add_self_order")
            args.update(
                {"projectId": project_id, "projectName": project_name, "rentTime": curr_date, "rentTimeEnd": curr_date})
            self.runner.add_self_order(dynamic_args=args, assertions=expected)

        with allure.step("搜索自用订单"):
            args, expected = build_parametrize("search_self_order")
            args.update({"projectId": project_id})

            response = self.runner.search_self_order(dynamic_args=args, assertions=expected)
            order_id = parse("$.result.records[0].id").find(response)[0].value
            order_no = parse("$.result.records[0].orderNo").find(response)[0].value

        with allure.step("自用订单出库"):
            args, expected = build_parametrize("self_order_outbound")
            args.update({"ids": [order_id]})

            self.runner.self_order_outbound(dynamic_args=args, assertions=expected)

        with allure.step("检查设备"):
            args, expected = build_parametrize("search_device", index=2)
            self.runner.search_device(dynamic_args=args, assertions=expected)

        with allure.step("查询出入库记录"):
            args, expected = build_parametrize("in_out_record")
            expected.append(["$.result.records[0].relOrderNo", "eq", order_no])
            for i in range(2):
                args.update({"stockOrderType": i})
                self.runner.in_out_record(dynamic_args=args, assertions=expected)

        with allure.step("自用订单入库"):
            args, expected = build_parametrize("self_order_inbound")
            args.update({"ids": [order_id], "returnTime": curr_date})

            self.runner.self_order_inbound(dynamic_args=args, assertions=expected)

        with allure.step("检查设备"):
            args, expected = build_parametrize("search_device")
            self.runner.search_device(dynamic_args=args, assertions=expected)

        with allure.step("编辑设备（修改设备状态）"):
            args, expected = build_parametrize("edit_device", index=2)
            args.update({"id": device_id})
            self.runner.edit_device(dynamic_args=args, assertions=expected)

        with allure.step("出借方上架资源"):
            kh2 = WEBCloud()
            args, expected = build_parametrize("get_token")
            kh2.get_token(dynamic_args=args, assertions=expected)

            args, expected = build_parametrize("search_rent_source")
            response = kh2.search_rent_source(dynamic_args=args, assertions=expected)

            if response['result']['total'] < 1:
                args, expected = build_parametrize("add_rent_source")
                kh2.add_rent_source(dynamic_args=args, assertions=expected)

        with allure.step("价格查询"):
            current = datetime.today()
            curr_date = current.strftime('%Y-%m-%d')

            future_date = current + timedelta(days=4)
            future_date = future_date.strftime('%Y-%m-%d')

            args, jsonpath_args, expected = build_parametrize("add_rent_order")
            args.update({"rentTime": curr_date, "rentTimeEnd": future_date})

            resp = self.runner.calculate_price(dynamic_args=args, jsonpath_args=jsonpath_args, assertions=expected)
            amount = parse("$.result.amount").find(resp)[0].value

        with allure.step("借用方下单"):
            args, jsonpath_args, expected = build_parametrize("add_rent_order")
            args.update({"projectId": project_id, "projectName": project_name, "rentTime": curr_date,
                         "rentTimeEnd": future_date})
            jsonpath_args.append(["$.uavEquipmentRentList[0].totalPrices", amount])

            self.runner.add_rent_order(dynamic_args=args, assertions=expected)

        with allure.step("查询租借订单"):
            args, expected = build_parametrize("search_rent_order")
            args.update({"projectId": project_id})

            response = self.runner.search_rent_order(dynamic_args=args, assertions=expected)
            rent_order_id = parse("$.result.records[0].id").find(response)[0].value

        with allure.step("获取租借订单详细信息"):
            args, expected = build_parametrize("detail_rent_order")
            args.update({"id": rent_order_id})

            resp = self.runner.detail_rent_order(dynamic_args=args, assertions=expected)
            order_detail = resp.get("result")

        with allure.step("确认租借订单"):
            args, expected = build_parametrize("confirm_rent_order")
            order_detail.update(args)
            kh2.confirm_rent_order(dynamic_args=order_detail, assertions=expected)

        with allure.step("借出方出库"):
            args, expected = build_parametrize("rent_out_outbound")
            args.update({"ids": [rent_order_id]})

            kh2.rent_out_outbound(dynamic_args=args, assertions=expected)

        with allure.step("借入方入库"):
            args, expected = build_parametrize("rent_in_inbound")
            args.update({"ids": [rent_order_id]})

            self.runner.rent_in_inbound(dynamic_args=args, assertions=expected)

        with allure.step("借入方出库"):
            args, expected = build_parametrize("rent_in_outbound")
            args.update({"ids": [rent_order_id]})

            self.runner.rent_in_outbound(dynamic_args=args, assertions=expected)

        with allure.step("借出方入库"):
            args, expected = build_parametrize("rent_out_inbound")
            args.update({"ids": [rent_order_id], "returnTime": curr_date})

            self.runner.rent_out_inbound(dynamic_args=args, assertions=expected)

        with allure.step("检查飞行项目看板"):
            args, expected = build_parametrize("flight_project_dashboard")
            args.update({"projectId": project_id})

            self.runner.flight_project_dashboard(dynamic_args=args, assertions=expected)

        with allure.step("检查飞行项目设备调出"):
            args, expected = build_parametrize("equipment_out_item")
            args.update({"projectId": project_id})

            self.runner.equipment_out_item(dynamic_args=args, assertions=expected)

        with allure.step("项目完结"):
            args, expected = build_parametrize("edit_project")
            args.update({"id": project_id})

            self.runner.edit_project(dynamic_args=args, assertions=expected)

    @allure.description("""
            测试步骤:
            1. 获取被盘点参仓库代码
            2. 检查设备信息
            3. 设备转移到被盘点仓库
            4. 新建盘点任务
            5. 手持获取盘点数据列表
            6. 开始盘点
            7. 提交盘点数据信息
            8. 完成盘点
            9. 检查盘点清单
            10. 获取库存调整信息
            11. 创建库存调整单
            12. 删除测试设备

            测试环境:
                - uat：https://cloud-uat.dmduav.com/

            预期结果:
            - 所有接口请求通过，接口返回满足校验
            """)
    @allure.story("库存管理-库存盘点")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_inventory_task(self):
        with allure.step("查询仓库代码"):
            current = datetime.today()
            curr_date = current.strftime('%Y-%m-%d')
            warehouse_name = self._cache['project_name']

            args, expected = build_parametrize("warehouse_list")
            args.update({"name": warehouse_name})
            resp = self.runner.warehouse_list(dynamic_args=args, assertions=expected)
            code = resp.get("result").get("records")[0]['code']

            self._cache['warehouse_id'] = code

        with allure.step("检查设备"):
            args, expected = build_parametrize("search_device", index=3)
            resp = self.runner.search_device(dynamic_args=args, assertions=expected)
            device_id = resp.get("result").get("records")[0]['id']
            self._cache["device_id"] = device_id

        with allure.step("编辑设备（修改设备组织）"):
            args, expected = build_parametrize("edit_device", index=3)
            args.update({"id": device_id, "warehouseId": code})
            self.runner.edit_device(dynamic_args=args, assertions=expected)

        with allure.step("新建盘点任务"):
            args, expected = build_parametrize("inventory_task_add")
            args.update({"warehouseId": code, "expectedStartTime": f"{curr_date} 00:00:00",
                         "expectedEndTime": f"{curr_date} 00:00:00"})
            self.runner.inventory_task_add(dynamic_args=args, assertions=expected)

        with allure.step("查询盘点任务列表"):
            args, expected = build_parametrize("inventory_task_list")
            resp = self.runner.inventory_task_list(dynamic_args=args, assertions=expected)
            task_id = resp.get("result").get("records")[0]["id"]

        with allure.step("开始盘点"):
            args, expected = build_parametrize("start_inventory_task")
            args.update({"id": task_id})
            self.runner.start_inventory_task(dynamic_args=args, assertions=expected)

        with allure.step("提交数据"):
            args, expected = build_parametrize("commit_devices_data")
            args.update({"id": task_id})
            self.runner.commit_devices_data(dynamic_args=args, assertions=expected)

        with allure.step("完成盘点"):
            args, expected = build_parametrize("finish_inventory_task")
            args.update({"id": task_id})
            self.runner.finish_inventory_task(dynamic_args=args, assertions=expected)

        with allure.step("盘点清单"):
            args, expected = build_parametrize("query_record_list")
            args.update({"taskId": task_id})
            self.runner.query_record_list(dynamic_args=args, assertions=expected)

            args, expected = build_parametrize("query_record_list", index=2)
            args.update({"taskId": task_id})
            self.runner.query_record_list(dynamic_args=args, assertions=expected)

        with allure.step("获取库存调整单"):
            args, expected = build_parametrize("get_inventory_adjustment")
            args.update({"id": task_id})

            self.runner.get_inventory_adjustment(dynamic_args=args, assertions=expected)

        with allure.step("创建库存调整单"):
            args, expected = build_parametrize("create_inventory_adjustment")
            args.update({"id": task_id})

            self.runner.create_inventory_adjustment(dynamic_args=args, assertions=expected)

    @allure.description("""
                测试步骤:
                1. 获取评级类型
                2. 获取评级等级icon
                3. 新增评级等级
                4. 查询等级名称id
                5. 添加等级用户
                6. 添加等级费用配置
                7. 查询用户评级id
                8. 加入租借
                9. 查询飞手资源列表
                10. 计算飞手服务价格
                11. 创建租借订单
                12. 查询飞手租借订单
                13. 确认飞手订单
                14. 完成订单
                15. 结款完成
                16. 清理数据

                测试环境:
                    - uat：https://cloud-uat.dmduav.com/

                预期结果:
                - 所有接口请求通过，接口返回满足校验
                """)
    @allure.story("交易中心-飞手服务")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_flyer_server(self):

        with allure.step("获取评级类型"):
            args, expected = build_parametrize("rating_type_list")

            resp = self.runner.rating_type_list(assertions=expected)

            type_list = {}
            for i in resp['result']:
                type_list[i['name']] = i['id']

        with allure.step("获取评级等级icon"):
            args, expected = build_parametrize("rating_icon_list")
            flight_engineer = type_list.get("飞行工程师")
            args.update({"ratingTypeId": flight_engineer})

            resp = self.runner.rating_icon_list(dynamic_args=args, assertions=expected)

            icon_url = {}
            for i in resp['result']:
                icon_url[i['name']] = i['url']

        with allure.step("新增评级等级"):
            args, expected = build_parametrize("add_rating_level")
            icon = icon_url.get("中级")
            args.update({"ratingTypeId": flight_engineer, "icon": icon})

            self.runner.add_rating_level(dynamic_args=args, assertions=expected)

        with allure.step("查询等级名称id"):
            args, expected = build_parametrize("rating_level_list")

            resp = self.runner.rating_level_list(dynamic_args=args, assertions=expected)
            id = resp.get("result").get("records")[0]['id']

        with allure.step("添加等级用户"):
            current = datetime.today()
            curr_date = current.strftime('%Y-%m-%d')
            future_date = current + timedelta(days=4)
            future_date = future_date.strftime('%Y-%m-%d')

            args, expected = build_parametrize("add_rating_user")
            args.update({"startDate": f"{curr_date} 00:00:00",
                         "endDate": f"{future_date} 00:00:00",
                         "ratingTypeId": flight_engineer,
                         "ratingLevelId": id
                         })

            resp = self.runner.add_rating_user(dynamic_args=args, assertions=expected)

        with allure.step("添加等级费用配置"):
            args, expected = build_parametrize("add_flyer_cost")
            args.update({"ratingLevelId": id})

            resp = self.runner.add_flyer_cost(dynamic_args=args, assertions=expected)

        with allure.step("查询用户评级id"):
            args, expected = build_parametrize("rating_user_list")
            resp = self.runner.rating_user_list(dynamic_args=args, assertions=expected)

            rating_id = resp['result']['records'][0]['id']

        with allure.step("加入租借"):
            args, expected = build_parametrize("change_rent_flag")
            args.update({"ratingId": rating_id})

            self.runner.change_rent_flag(dynamic_args=args, assertions=expected)

        with allure.step("查询飞手资源列表"):
            args, expected = build_parametrize("user_resource_list")
            resp = self.runner.user_resource_list(dynamic_args=args, assertions=expected)

            source_id = resp['result']['records'][0]['id']

        with allure.step("计算飞手服务价格"):
            args, expected = build_parametrize("calculate_flyer_cost")
            args.update({"startDay": curr_date, "endDay": future_date, "resourceId": source_id})

            self.runner.calculate_flyer_cost(dynamic_args=args, assertions=expected)

        with allure.step("创建租借订单"):
            kh2 = WEBCloud()
            args, expected = build_parametrize("get_token")
            kh2.get_token(dynamic_args=args, assertions=expected)

            args, expected = build_parametrize("create_flyer_order")
            args.update({"startDay": curr_date, "endDay": future_date, "userResourceId": source_id})

            kh2.create_flyer_order(dynamic_args=args, assertions=expected)

        with allure.step("查询飞手租借订单"):
            args, expected = build_parametrize("flyer_order_list")
            resp = self.runner.flyer_order_list(dynamic_args=args, assertions=expected)
            order_id = resp.get("result").get("records")[0]['id']

        with allure.step("确认飞手订单"):
            args, expected = build_parametrize("confirm_flyer_order")
            args.update({"id": order_id, "userResourceId": source_id})

            self.runner.confirm_flyer_order(dynamic_args=args, assertions=expected)

        with allure.step("完成订单"):
            args, expected = build_parametrize("update_flyer_order")
            args.update({"id": order_id})

            self.runner.update_flyer_order(dynamic_args=args, assertions=expected)

        with allure.step("结款完成"):
            args, expected = build_parametrize("update_flyer_order", index=2)
            args.update({"id": order_id})

            self.runner.update_flyer_order(dynamic_args=args, assertions=expected)

        with allure.step("清理数据"):
            resp = self.runner.flyr_cost_list()
            results = resp.get("result")
            cost_id = None
            for i in results:
                if i['ratingLevelName'] == '测试飞手等级':
                    cost_id = i['id']

            self.runner.delete_flyer_cost(dynamic_args={"id": cost_id})
            self.runner.delete_rating_user(dynamic_args={"id": rating_id})
            self.runner.delete_rating_level(dynamic_args={"id": id})

    @allure.description("""
                    测试步骤:
                    1. 手持设备新增送修
                    2. 确认维修订单关联oa
                    3. 维修点入库
                    4. 维修点出库
                    5. 客户入库
                    6. 删除设备

                    测试环境:
                        - uat：https://cloud-uat.dmduav.com/

                    预期结果:
                    - 所有接口请求通过，接口返回满足校验
                    """)
    @allure.story("售后中心-设备送修")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_devices_repair(self):
        with allure.step("手持设备送修"):
            log_manager.logger.info("\r【手持设备送修】=========>")

            args, jsonpath_args, expected = build_parametrize("send_repair")
            args.update({"projectId": self._cache["project_id"], "projectName": self._cache["project_name"]})
            jsonpath_args.append(["$.breakdownRecords[0].warehouseId", self._cache['warehouse_id']])

            resp = self.runner.send_repair(dynamic_args=args, jsonpath_args=jsonpath_args, assertions=expected)
            order_id = resp.get("result").get("id")

        with allure.step("确认维修订单"):
            log_manager.logger.info("\r【确认维修订单】=========>")

            args, expected = build_parametrize("update_repair_site")
            args.update({"orderId": order_id})
            self.runner.update_repair_site(dynamic_args=args, assertions=expected)

        with allure.step("维修点入库"):
            log_manager.logger.info("\r【维修点入库】=========>")

            args, expected = build_parametrize("update_repair_status")
            args.update({"orderId": order_id})
            resp = self.runner.update_repair_status(dynamic_args=args, assertions=expected)

        with allure.step("维修点出库"):
            log_manager.logger.info("\r【维修点出库】=========>")

            args, expected = build_parametrize("update_repair_status", index=2)
            args.update({"orderId": order_id})
            resp = self.runner.update_repair_status(dynamic_args=args, assertions=expected)

        with allure.step("客户入库"):
            log_manager.logger.info("\r【维修点出库】=========>")

            args, expected = build_parametrize("update_repair_status", index=3)
            args.update({"orderId": order_id})
            resp = self.runner.update_repair_status(dynamic_args=args, assertions=expected)

        with allure.step("删除设备"):
            args, expected = build_parametrize("delete_device")
            args.update({"id": self._cache["device_id"]})

            self.runner.delete_device(dynamic_args=args, assertions=expected)

    @allure.description("""
                        测试步骤:
                        1. 地面站入库设备
                        2. 获取绑定设备id
                        3. 绑定设备
                        4. 新增设备调度单
                        5. 获取设备调度单列表
                        6. 调度单设备出库
                        7. 设备归还
                        8. 删除设备

                        测试环境:
                            - uat：https://cloud-uat.dmduav.com/

                        预期结果:
                        - 所有接口请求通过，接口返回满足校验
                        """)
    @allure.story("素材中心-素材管理")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_drama_material(self):
        with  allure.step("上传json文件"):
            args, expected = build_parametrize("upload_darma_jsdm")

            resp = self.runner.upload_darma_jsdm(files=args, assertions=expected)

            extra = parse("$.result.extra").find(resp)[0].value
            types = parse("$.result.jsdmDetail.types[0]").find(resp)[0].value
            file_id = parse("$.result.file.fileId").find(resp)[0].value

        with  allure.step("添加素材"):
            args, expected = build_parametrize("add_drama_material")
            args.update({
                "url": extra['url'],
                "keywords": extra['keywords'],
                "imageUrl": extra['imageUrl'],
                "downloadUrl": extra['url'],
                "fileId": file_id,
            })
            self.runner.add_drama_material(dynamic_args=args, assertions=expected)

        with  allure.step("查询素材"):
            args, expected = build_parametrize("list_drama_material")
            args.update({"keywords": extra['keywords']})

            resp = self.runner.list_drama_material(dynamic_args=args, assertions=expected)
            material_id = resp.get("result").get("records")[0]['id']

        with  allure.step("素材下架"):
            args, expected = build_parametrize("change_material_status")
            args.update({"id": material_id})

            self.runner.change_material_status(dynamic_args=args, assertions=expected)

        with  allure.step("素材删除"):
            args, expected = build_parametrize("delete_drama_material")
            args.update({"id": material_id})

            self.runner.delete_drama_material(dynamic_args=args, assertions=expected)

    @allure.story("生产中心-设备调度")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_devices_dispatch(self):
        with allure.step("地面站飞机入库"):
            args, expected = build_parametrize("gdbc_device_inbound")
            self.runner.gdbc_device_inbound(dynamic_args=args, assertions=expected)

        with allure.step("获取待绑定设备列表id"):
            args, expected = build_parametrize("bind_list")
            args.update({"createBy": self.runner.username})

            response = self.runner.bind_list(dynamic_args=args, assertions=expected)
            device_id = parse("$.result.records[0].id").find(response)[0].value

        with allure.step("绑定设备"):
            args, expected = build_parametrize("bind_device")
            self.runner.bind_device(dynamic_args=args, assertions=expected)

        with allure.step("新增设备调度单"):
            current = datetime.today()
            curr_date = current.strftime('%Y-%m-%d')

            args, expected = build_parametrize("add_dispatch_order")
            args.update({"expectedDispatchDate": curr_date, })
            self.runner.add_dispatch_order(dynamic_args=args, assertions=expected)

        with allure.step("获取设备调度单列表"):
            args, expected = build_parametrize("list_dispatch_order")
            args.update({"expectedDispatchDate": curr_date, })
            resp = self.runner.list_dispatch_order(dynamic_args=args, assertions=expected)
            order_id = resp.get("result").get("records")[0]['id']

        with allure.step("调度单设备出库"):
            args, expected = build_parametrize("outbound_dispatch_devices")
            args.update({"ids": [order_id]})
            resp = self.runner.outbound_dispatch_devices(dynamic_args=args, assertions=expected)

        with allure.step("设备归还"):
            args, expected = build_parametrize("return_dispatch_devices")
            resp = self.runner.return_dispatch_devices(dynamic_args=args, assertions=expected)

        with allure.step("删除设备"):
            args, expected = build_parametrize("delete_device")
            args.update({"id": device_id})

            self.runner.delete_device(dynamic_args=args, assertions=expected)