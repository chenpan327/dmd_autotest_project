#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import datetime
import os

import pytest
import allure
from datetime import datetime, timedelta

from src.Protocol.web.Web_API import WEBCloud
from src.Protocol.dgcs.Dgcs_Ui import DGCS, root_path

from utils.logger import log_manager

@allure.feature("OTA升级验证")
@allure.story("")
class TestDroneOTA:

    @allure.title("OTA升级验证-真实飞机")
    @allure.description("")
    def test_drone_ota(self):
        ground_station = DGCS()
        web_cloud = WEBCloud()

        # 暂定无人机ID
        uav_id = "1"

        with allure.step("地面站和云平台-初始化"):
            web_cloud.get_token(dynamic_args={"username": ground_station.user, "password": ground_station.pwd})
            ground_station.start_app()
            
        with allure.step("地面站-登录"):
            user_name = "CI"
            user_password = "dmdfighting!"
            expected_message = "授权有效期只有：3天, 请联系管理员授权"

            date_str = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
            web_cloud.edit_gdc_user(dynamic_args={"username": "CI", "expired": f"{date_str} 00:00:00"})

            result = ground_station.login(user_name, user_password)

            allure.attach.file(
                root_path + "/file/picture/login.png",
                name="执行结果",
                attachment_type=allure.attachment_type.PNG
            )
            assert result == expected_message

        with allure.step("地面站-获取用户信息"):
            resp = web_cloud.gdbc_search()
            station_id = resp['result']['records'][0]['id']

            resp = web_cloud.gdbc_user_list(dynamic_args={"stationId": station_id, "username": ground_station.user})
            user_info = resp['result']['records'][0]

            result = ground_station.user_info()

            assert result['uav_type'] == user_info['droneTypeTxt'].split(',')

        with allure.step("地面站-设置网卡"):
            network_name = '以太网-地面站'
            ground_station.set_netCard(network_name)
            assert result

        with allure.step("地面站-获取无人机信息确认无人机上线"):
            uav_serch_result = ground_station.uav_search(uav_id)
            assert uav_serch_result, "无人机搜索失败或无人机未上线"

        with allure.step("地面站-查看无人机当前版本信息"):
            drone_info = ground_station.uav_info(uav_id)
            assert drone_info, "获取无人机信息失败"
            log_manager.logger.info(f"无人机 {uav_id} 当前版本信息: {drone_info}")

        with allure.step("执行OTA升级流程"):
            ground_station.update_firmware(uav_id)

        with allure.step("地面站-查看无人机当前版本信息"):
            drone_info = ground_station.uav_info(uav_id)
            assert drone_info, "获取无人机信息失败"
            log_manager.logger.info(f"无人机 {uav_id} 当前版本信息: {drone_info}")

        with allure.step("地面站-退出"):
            ground_station.exit()

        