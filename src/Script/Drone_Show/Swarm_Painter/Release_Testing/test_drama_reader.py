#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DramaReader 测试脚本 - 测试 JSON 中所有元素是否存在"""
import pytest
import json
import os
import allure
from utils.logger import log_manager
from src.Protocol.drama.drone_show.drama_reader import DramaReader
from src.Script.Drone_Show.Swarm_Painter.Release_Testing.conftest import drone_index_list, load_drama_data, data_file_path

example_drone_type = "V4"

@allure.feature("DramaReader")
@allure.story("数据验证")
class TestTmpFileDataValidation:
    """验证解析后的实际数据"""
    # ==================== drama3 顶层字段测试 ====================

    @allure.title("验证dramaId字段非空")
    @allure.description("验证drama3.dramaId字段值不为空")
    def test_drama_id(self, drama3):
        with allure.step("检查dramaId字段"):
            log_manager.logger.info(f"验证 drama3.dramaId: {drama3.get('dramaId')}")
            assert drama3["dramaId"] != "", "字段 drama3.dramaId 为空字符串"

    @allure.title("验证droneCount字段非空")
    @allure.description("验证drama3.droneCount字段值不为空")
    def test_drone_count(self, drama3):
        with allure.step("检查droneCount字段"):
            log_manager.logger.info(f"验证 drama3.droneCount: {drama3.get('droneCount')}")
            assert drama3["droneCount"] != 0, "字段 drama3.droneCount 为空"

    @allure.title("验证sceneName字段非空")
    @allure.description("验证drama3.sceneName字段值不为空")
    def test_scene_name(self, drama3):
        with allure.step("检查sceneName字段"):
            log_manager.logger.info(f"验证 drama3.sceneName: {drama3.get('sceneName')}")
            # assert drama3["sceneName"] != "", "字段 drama3.sceneName 为空"

    @allure.title("验证description字段非空")
    @allure.description("验证drama3.description字段值不为空")
    def test_description(self, drama3):
        with allure.step("检查description字段"):
            log_manager.logger.info(f"验证 drama3.description: {drama3.get('description')}")
            # assert drama3["description"] != "", "字段 drama3.description 为空"

    @allure.title("验证payloadFps字段非空")
    @allure.description("验证drama3.payloadFps字段值不为空")
    def test_payload_fps(self, drama3):
        with allure.step("检查payloadFps字段"):
            log_manager.logger.info(f"验证 drama3.payloadFps: {drama3.get('payloadFps')}")
            assert drama3["payloadFps"] != 0, "字段 drama3.payloadFps 为空"

    @allure.title("验证pointFps字段非空")
    @allure.description("验证drama3.pointFps字段值不为空")
    def test_point_fps(self, drama3):
        with allure.step("检查pointFps字段"):
            log_manager.logger.info(f"验证 drama3.pointFps: {drama3.get('pointFps')}")
            assert drama3["pointFps"] != 0, "字段 drama3.pointFps 为空"

    @allure.title("验证dramaVersion字段非空")
    @allure.description("验证drama3.dramaVersion字段值不为空")
    def test_drama_version(self, drama3):
        with allure.step("检查dramaVersion字段"):
            log_manager.logger.info(f"验证 drama3.dramaVersion: {drama3.get('dramaVersion')}")
            assert drama3["dramaVersion"] != 0, "字段 drama3.dramaVersion 为空"

    @allure.title("验证drones数组非空")
    @allure.description("验证drama3.drones数组包含元素")
    def test_drones(self, drama3):
        with allure.step("检查drones数组"):
            log_manager.logger.info(f"验证 drama3.drones: 共 {len(drama3.get('drones', []))} 个无人机")
            assert len(drama3["drones"]) != 0, "字段 drama3.drones 为空"

    @allure.title("验证map对象非空")
    @allure.description("验证drama3.map对象包含字段")
    def test_map(self, drama3):
        with allure.step("检查map对象"):
            log_manager.logger.info(f"验证 drama3.map: {drama3.get('map')}")
            assert drama3["map"] != {}, "字段 drama3.map 为空"

        # ==================== map 子字段测试 ====================
        map_data = drama3["map"]
        with allure.step("检查map.rotate字段"):
            log_manager.logger.info(f"验证 drama3.map.rotate: {map_data.get('rotate')}")
            # assert map_data["rotate"] != "", "字段 drama3.map.rotate 为空"

        with allure.step("检查map.name字段"):
            log_manager.logger.info(f"验证 drama3.map.name: {map_data.get('name')}")
            # assert map_data["name"] != "", "字段 drama3.map.name 为空"

        with allure.step("检查map.widthScale字段"):
            log_manager.logger.info(f"验证 drama3.map.widthScale: {map_data.get('widthScale')}")
            # assert map_data["widthScale"] != "", "字段 drama3.map.widthScale 为空"

        with allure.step("检查map.heightScale字段"):
            log_manager.logger.info(f"验证 drama3.map.heightScale: {map_data.get('heightScale')}")
            # assert map_data["heightScale"] != "", "字段 drama3.map.heightScale 为空"

        with allure.step("检查map.radius字段"):
            log_manager.logger.info(f"验证 drama3.map.radius: {map_data.get('radius')}")
            # assert map_data["radius"] != "", "字段 drama3.map.radius 为空"

        with allure.step("检查map.x字段"):
            log_manager.logger.info(f"验证 drama3.map.x: {map_data.get('x')}")
            # assert map_data["x"] != "", "字段 drama3.map.x 为空"

        with allure.step("检查map.y字段"):
            log_manager.logger.info(f"验证 drama3.map.y: {map_data.get('y')}")
            # assert map_data["y"] != "", "字段 drama3.map.y 为空"

        with allure.step("检查map.z字段"):
            log_manager.logger.info(f"验证 drama3.map.z: {map_data.get('z')}")
            # assert map_data["z"] != "", "字段 drama3.map.z 为空"

        with allure.step("检查map.lon字段"):
            log_manager.logger.info(f"验证 drama3.map.lon: {map_data.get('lon')}")
            # assert map_data["lon"] != "", "字段 drama3.map.lon 为空"

        with allure.step("检查map.lat字段"):
            log_manager.logger.info(f"验证 drama3.map.lat: {map_data.get('lat')}")
            # assert map_data["lat"] != "", "字段 drama3.map.lat 为空"

    @allure.title("验证segmInfos数组非空")
    @allure.description("验证drama3.segmInfos数组包含元素")
    def test_segm_infos(self, drama3):
        with allure.step("检查segmInfos数组"):
            log_manager.logger.info(f"验证 drama3.segmInfos: 共 {len(drama3.get('segmInfos', []))} 个段信息")
            # assert len(drama3["segmInfos"]) != 0, "字段 drama3.segmInfos 为空"

        # ==================== segmInfos 子字段测试 ====================
        segm_infos = drama3["segmInfos"]
        for i, segm in enumerate(segm_infos):
            with allure.step("检查segmInfos[].startFrame字段"):
                log_manager.logger.info(f"验证 drama3.segmInfos[{i}].startFrame: {segm.get('startFrame')}")
                assert segm["startFrame"] != "", f"字段 drama3.segmInfos[{i}].startFrame 为空"

            with allure.step("检查segmInfos[].endFrame字段"):
                log_manager.logger.info(f"验证 drama3.segmInfos[{i}].endFrame: {segm.get('endFrame')}")
                assert segm["endFrame"] != "", f"字段 drama3.segmInfos[{i}].endFrame 为空"

            with allure.step("检查segmInfos[].type字段"):
                log_manager.logger.info(f"验证 drama3.segmInfos[{i}].type: {segm.get('type')}")
                assert segm["type"] != "", f"字段 drama3.segmInfos[{i}].type 为空"

            with allure.step("检查segmInfos[].description字段"):
                log_manager.logger.info(f"验证 drama3.segmInfos[{i}].description: {segm.get('description')}")
                assert segm["description"] != "", f"字段 drama3.segmInfos[{i}].description 为空"    

    @allure.title("验证authorName字段非空")
    @allure.description("验证drama3.authorName字段值不为空")
    def test_author_name(self, drama3):
        with allure.step("检查authorName字段"):
            log_manager.logger.info(f"验证 drama3.authorName: {drama3.get('authorName')}")
            assert drama3["authorName"] != "", "字段 drama3.authorName 为空"

    # ==================== drones 数组元素字段测试 ====================

    @allure.title("验证drones[].id字段非空")
    @allure.description("验证每个drone的id字段值不为空")
    def test_drones_id(self, drama3):
        with allure.step("检查drones[].id字段"):
            drones = drama3["drones"]
            for i, drone in enumerate(drones):
                log_manager.logger.info(f"验证 drones[{i}].id: {drone.get('id')}")
                assert drone["id"] != 0, f"字段 drones[{i}].id 为空"

    @allure.title("验证drones[].droneType字段非空")
    @allure.description("验证每个drone的droneType字段值不为空")
    def test_drones_drone_type(self, drama3):
        with allure.step("检查drones[].droneType字段"):
            drones = drama3["drones"]
            for i, drone in enumerate(drones):
                log_manager.logger.info(f"验证 drones[{i}].droneType: {drone.get('droneType')}")
                assert drone["droneType"] != 0, f"字段 drones[{i}].droneType 为空"

    @allure.title("验证drones[].returnType字段非空")
    @allure.description("验证每个drone的returnType字段值不为空")
    def test_drones_return_type(self, drama3):
        with allure.step("检查drones[].returnType字段"):
            drones = drama3["drones"]
            for i, drone in enumerate(drones):
                log_manager.logger.info(f"验证 drones[{i}].returnType: {drone.get('returnType')}")
                # assert drone["returnType"] != 0, f"字段 drones[{i}].returnType 为空"

    @allure.title("验证drones[].playTime字段非空")
    @allure.description("验证每个drone的playTime字段值不为空")
    def test_drones_play_time(self, drama3):
        with allure.step("检查drones[].playTime字段"):
            drones = drama3["drones"]
            for i, drone in enumerate(drones):
                log_manager.logger.info(f"验证 drones[{i}].playTime: {drone.get('playTime')}")
                # assert drone["playTime"] != 0, f"字段 drones[{i}].playTime 为空"

    @allure.title("验证drones[].positionKeyFrames数组非空及字段有效性")
    @allure.description("验证每个drone的positionKeyFrames数组包含元素，且frame递增，坐标字段不为空")
    def test_drones_position_key_frames(self, drama3):
        drones = drama3["drones"]
        
        with allure.step("检查drones[].positionKeyFrames数组"):
            for i, drone in enumerate(drones):
                position_kfs = drone.get("positionKeyFrames", [])
                
                # 1. 检查数组非空
                log_manager.logger.info(f"验证 drones[{i}].positionKeyFrames: 共 {len(position_kfs)} 个关键帧")
                assert len(position_kfs) != 0, f"字段 drones[{i}].positionKeyFrames 为空"

                # 2. 遍历关键帧
                with allure.step(f"验证 drone[{i}] 的 position 关键帧数据"):
                    for j, kf in enumerate(position_kfs):
                        # --- 验证 Frame 递增 ---
                        log_manager.logger.info(f"验证 drones[{i}].positionKeyFrames[{j}].frame: {kf.get('frame')}")

                        if j == 0:
                            last_frame = -1  # 允许首帧为 0
                        else:
                            last_frame = position_kfs[j-1].get("frame", 0)

                        assert kf["frame"] > last_frame, (
                            f"帧序错误: drones[{i}].positionKeyFrames[{j}].frame "
                            f"当前帧序 ({kf['frame']}) 必须大于上一帧的帧序 ({last_frame})"
                        )

                        # 将 x, y, z 的验证合并在一个逻辑块中，避免重复创建 allure step
                        log_manager.logger.info(f"验证 drones[{i}].positionKeyFrames[{j}] 坐标: x={kf.get('x')}, y={kf.get('y')}, z={kf.get('z')}")
                        
                        assert kf.get("x") is not None, f"字段 drones[{i}].positionKeyFrames[{j}].x 不能为空"
                        assert kf.get("y") is not None, f"字段 drones[{i}].positionKeyFrames[{j}].y 不能为空"
                        assert kf.get("z") is not None, f"字段 drones[{i}].positionKeyFrames[{j}].z 不能为空"

    @allure.title("验证drones[].lightKeyFrames数组非空及字段有效性")
    @allure.description("验证每个drone的lightKeyFrames数组包含元素，且frame递增，lights字段不为空")
    def test_drones_light_key_frames(self, drama3):
        drones = drama3["drones"]

        with allure.step("检查drones[].lightKeyFrames数组"):
            for i, drone in enumerate(drones):
                light_kfs = drone.get("lightKeyFrames", [])

                # 1. 检查数组非空
                log_manager.logger.info(f"验证 drones[{i}].lightKeyFrames: 共 {len(light_kfs)} 个关键帧")
                assert len(light_kfs) != 0, f"字段 drones[{i}].lightKeyFrames 为空"

                # 2. 遍历关键帧
                with allure.step(f"验证 drone[{i}] 的 light 关键帧数据"):
                    for j, kf in enumerate(light_kfs):
                        # --- 验证 Frame 递增 ---
                        log_manager.logger.info(f"验证 drones[{i}].lightKeyFrames[{j}].frame: {kf.get('frame')}")

                        if j == 0:
                            last_frame = -1  # 允许首帧为 0
                        else:
                            last_frame = light_kfs[j-1].get("frame", 0)

                        assert kf["frame"] > last_frame, (
                            f"帧序错误: drones[{i}].lightKeyFrames[{j}].frame "
                            f"当前帧序 ({kf['frame']}) 必须大于上一帧的帧序 ({last_frame})"
                        )

                        # 验证 lights 及其子字段
                        lights = kf.get("lights", {})
                        log_manager.logger.info(f"验证 drones[{i}].lightKeyFrames[{j}] lights: r={lights.get('r')}, g={lights.get('g')}, b={lights.get('b')}")
                        assert kf.get("lights") is not None, f"字段 drones[{i}].lightKeyFrames[{j}].lights 不能为空"
                        assert lights.get("r") is not None, f"字段 drones[{i}].lightKeyFrames[{j}].lights.r 不能为空"
                        assert lights.get("g") is not None, f"字段 drones[{i}].lightKeyFrames[{j}].lights.g 不能为空"
                        assert lights.get("b") is not None, f"字段 drones[{i}].lightKeyFrames[{j}].lights.b 不能为空"

    @allure.title("验证drones[].novaKeyFrames数组非空及字段有效性")
    @allure.description("验证每个drone的novaKeyFrames数组包含元素，且frame递增，novas字段不为空")
    def test_drones_nova_key_frames(self, drama3):
        drones = drama3["drones"]

        with allure.step("检查drones[].novaKeyFrames数组"):
            for i, drone in enumerate(drones):
                nova_kfs = drone.get("novaKeyFrames", [])

                # 1. 检查数组非空
                log_manager.logger.info(f"验证 drones[{i}].novaKeyFrames: 共 {len(nova_kfs)} 个关键帧")
                # assert len(nova_kfs) != 0, f"字段 drones[{i}].novaKeyFrames 为空"

                # 2. 遍历关键帧
                with allure.step(f"验证 drone[{i}] 的 nova 关键帧数据"):
                    for j, kf in enumerate(nova_kfs):
                        # --- 验证 Frame 递增 ---
                        log_manager.logger.info(f"验证 drones[{i}].novaKeyFrames[{j}].frame: {kf.get('frame')}")

                        if j == 0:
                            last_frame = -1  # 允许首帧为 0
                        else:
                            last_frame = nova_kfs[j-1].get("frame", 0)

                        assert kf["frame"] > last_frame, (
                            f"帧序错误: drones[{i}].novaKeyFrames[{j}].frame "
                            f"当前帧序 ({kf['frame']}) 必须大于上一帧的帧序 ({last_frame})"
                        )

                        # 验证 novas 及其子字段
                        novas = kf.get("novas", {})
                        log_manager.logger.info(f"验证 drones[{i}].novaKeyFrames[{j}] novas: power={novas.get('power')}")
                        assert kf.get("novas") is not None, f"字段 drones[{i}].novaKeyFrames[{j}].novas 不能为空"
                        assert novas.get("power") is not None, f"字段 drones[{i}].novaKeyFrames[{j}].novas.power 不能为空"

    @allure.title("验证drones[].fireworksKeyFrames数组及字段有效性")
    @allure.description("验证每个drone的fireworksKeyFrames数组，如果存在则frame递增，fireworks字段不为空")
    def test_drones_fireworks_key_frames(self, drama3):
        drones = drama3["drones"]

        with allure.step("检查drones[].fireworksKeyFrames数组"):
            for i, drone in enumerate(drones):
                fireworks_kfs = drone.get("fireworksKeyFrames", [])

                # 数组可以为空，只验证存在的数据
                log_manager.logger.info(f"验证 drones[{i}].fireworksKeyFrames: 共 {len(fireworks_kfs)} 个关键帧")

                # 遍历关键帧
                with allure.step(f"验证 drone[{i}] 的 fireworks 关键帧数据"):
                    for j, kf in enumerate(fireworks_kfs):
                        # --- 验证 Frame 递增 ---
                        log_manager.logger.info(f"验证 drones[{i}].fireworksKeyFrames[{j}].frame: {kf.get('frame')}")

                        if j == 0:
                            last_frame = -1  # 允许首帧为 0
                        else:
                            last_frame = fireworks_kfs[j-1].get("frame", 0)

                        assert kf["frame"] > last_frame, (
                            f"帧序错误: drones[{i}].fireworksKeyFrames[{j}].frame "
                            f"当前帧序 ({kf['frame']}) 必须大于上一帧的帧序 ({last_frame})"
                        )

                        # 验证 fireworks 及其子字段
                        fireworks = kf.get("fireworks", {})
                        log_manager.logger.info(f"验证 drones[{i}].fireworksKeyFrames[{j}] fireworks: firedPort={fireworks.get('firedPort')}, fireworkAngles={len(fireworks.get('fireworkAngles', []))} 个角度")
                        assert kf.get("fireworks") is not None, f"字段 drones[{i}].fireworksKeyFrames[{j}].fireworks 不能为空"
                        assert fireworks.get("firedPort") is not None, f"字段 drones[{i}].fireworksKeyFrames[{j}].fireworks.firedPort 不能为空"
                        assert fireworks.get("fireworkAngles") is not None, f"字段 drones[{i}].fireworksKeyFrames[{j}].fireworks.fireworkAngles 不能为空"

    @allure.title("验证drones[].lanternKeyFrames数组及字段有效性")
    @allure.description("验证每个drone的lanternKeyFrames数组，如果存在则frame递增，lanterns字段不为空")
    def test_drones_lantern_key_frames(self, drama3):
        drones = drama3["drones"]

        with allure.step("检查drones[].lanternKeyFrames数组"):
            for i, drone in enumerate(drones):
                lantern_kfs = drone.get("lanternKeyFrames", [])

                # 数组可以为空，只验证存在的数据
                log_manager.logger.info(f"验证 drones[{i}].lanternKeyFrames: 共 {len(lantern_kfs)} 个关键帧")

                # 2. 遍历关键帧
                with allure.step(f"验证 drone[{i}] 的 lantern 关键帧数据"):
                    for j, kf in enumerate(lantern_kfs):
                        # --- 验证 Frame 递增 ---
                        log_manager.logger.info(f"验证 drones[{i}].lanternKeyFrames[{j}].frame: {kf.get('frame')}")

                        if j == 0:
                            last_frame = -1  # 允许首帧为 0
                        else:
                            last_frame = lantern_kfs[j-1].get("frame", 0)

                        assert kf["frame"] > last_frame, (
                            f"帧序错误: drones[{i}].lanternKeyFrames[{j}].frame "
                            f"当前帧序 ({kf['frame']}) 必须大于上一帧的帧序 ({last_frame})"
                        )

                        # 验证 lanterns 及其子字段
                        lanterns = kf.get("lanterns", {})
                        log_manager.logger.info(f"验证 drones[{i}].lanternKeyFrames[{j}] lanterns: isOn={lanterns.get('isOn')}")
                        assert kf.get("lanterns") is not None, f"字段 drones[{i}].lanternKeyFrames[{j}].lanterns 不能为空"
                        assert lanterns.get("isOn") is not None, f"字段 drones[{i}].lanternKeyFrames[{j}].lanterns.isOn 不能为空"

    @allure.title("验证drones[].gimbalKeyFrames数组及字段有效性")
    @allure.description("验证每个drone的gimbalKeyFrames数组，如果存在则frame递增，gimbals字段不为空")
    def test_drones_gimbal_key_frames(self, drama3):
        drones = drama3["drones"]

        with allure.step("检查drones[].gimbalKeyFrames数组"):
            for i, drone in enumerate(drones):
                gimbal_kfs = drone.get("gimbalKeyFrames", [])

                # 数组可以为空，只验证存在的数据
                log_manager.logger.info(f"验证 drones[{i}].gimbalKeyFrames: 共 {len(gimbal_kfs)} 个关键帧")

                # 2. 遍历关键帧
                with allure.step(f"验证 drone[{i}] 的 gimbal 关键帧数据"):
                    for j, kf in enumerate(gimbal_kfs):
                        # --- 验证 Frame 递增 ---
                        log_manager.logger.info(f"验证 drones[{i}].gimbalKeyFrames[{j}].frame: {kf.get('frame')}")

                        if j == 0:
                            last_frame = -1  # 允许首帧为 0
                        else:
                            last_frame = gimbal_kfs[j-1].get("frame", 0)

                        assert kf["frame"] > last_frame, (
                            f"帧序错误: drones[{i}].gimbalKeyFrames[{j}].frame "
                            f"当前帧序 ({kf['frame']}) 必须大于上一帧的帧序 ({last_frame})"
                        )

                        # 验证 gimbals 及其子字段
                        gimbals = kf.get("gimbals", {})
                        log_manager.logger.info(f"验证 drones[{i}].gimbalKeyFrames[{j}] gimbals: pitch={gimbals.get('pitch')}, roll={gimbals.get('roll')}, yaw={gimbals.get('yaw')}")
                        assert kf.get("gimbals") is not None, f"字段 drones[{i}].gimbalKeyFrames[{j}].gimbals 不能为空"
                        assert gimbals.get("pitch") is not None, f"字段 drones[{i}].gimbalKeyFrames[{j}].gimbals.pitch 不能为空"
                        assert gimbals.get("roll") is not None, f"字段 drones[{i}].gimbalKeyFrames[{j}].gimbals.roll 不能为空"
                        assert gimbals.get("yaw") is not None, f"字段 drones[{i}].gimbalKeyFrames[{j}].gimbals.yaw 不能为空"

    @allure.title("验证drones[].lazerKeyFrames数组及字段有效性")
    @allure.description("验证每个drone的lazerKeyFrames数组，如果存在则frame递增，lazers字段不为空")
    def test_drones_lazer_key_frames(self, drama3):
        drones = drama3["drones"]

        with allure.step("检查drones[].lazerKeyFrames数组"):
            for i, drone in enumerate(drones):
                lazer_kfs = drone.get("lazerKeyFrames", [])

                # 数组可以为空，只验证存在的数据
                log_manager.logger.info(f"验证 drones[{i}].lazerKeyFrames: 共 {len(lazer_kfs)} 个关键帧")

                # 2. 遍历关键帧
                with allure.step(f"验证 drone[{i}] 的 lazer 关键帧数据"):
                    for j, kf in enumerate(lazer_kfs):
                        # --- 验证 Frame 递增 ---
                        log_manager.logger.info(f"验证 drones[{i}].lazerKeyFrames[{j}].frame: {kf.get('frame')}")

                        if j == 0:
                            last_frame = -1  # 允许首帧为 0
                        else:
                            last_frame = lazer_kfs[j-1].get("frame", 0)

                        assert kf["frame"] > last_frame, (
                            f"帧序错误: drones[{i}].lazerKeyFrames[{j}].frame "
                            f"当前帧序 ({kf['frame']}) 必须大于上一帧的帧序 ({last_frame})"
                        )

                        # 验证 lazers 及其子字段
                        lazers = kf.get("lazers", {})
                        log_manager.logger.info(f"验证 drones[{i}].lazerKeyFrames[{j}] lazers: r={lazers.get('r')}, g={lazers.get('g')}, b={lazers.get('b')}")
                        assert kf.get("lazers") is not None, f"字段 drones[{i}].lazerKeyFrames[{j}].lazers 不能为空"
                        assert lazers.get("r") is not None, f"字段 drones[{i}].lazerKeyFrames[{j}].lazers.r 不能为空"
                        assert lazers.get("g") is not None, f"字段 drones[{i}].lazerKeyFrames[{j}].lazers.g 不能为空"
                        assert lazers.get("b") is not None, f"字段 drones[{i}].lazerKeyFrames[{j}].lazers.b 不能为空"

    @allure.title("验证drones[].poseKeyFrames数组及字段有效性")
    @allure.description("验证每个drone的poseKeyFrames数组，如果存在则frame递增，pitch/roll/yaw字段不为空")
    def test_drones_pose_key_frames(self, drama3):
        drones = drama3["drones"]

        with allure.step("检查drones[].poseKeyFrames数组"):
            for i, drone in enumerate(drones):
                pose_kfs = drone.get("poseKeyFrames", [])

                # 数组可以为空，只验证存在的数据
                log_manager.logger.info(f"验证 drones[{i}].poseKeyFrames: 共 {len(pose_kfs)} 个关键帧")

                # 2. 遍历关键帧
                with allure.step(f"验证 drone[{i}] 的 pose 关键帧数据"):
                    for j, kf in enumerate(pose_kfs):
                        # --- 验证 Frame 递增 ---
                        log_manager.logger.info(f"验证 drones[{i}].poseKeyFrames[{j}].frame: {kf.get('frame')}")

                        if j == 0:
                            last_frame = -1  # 允许首帧为 0
                        else:
                            last_frame = pose_kfs[j-1].get("frame", 0)

                        assert kf["frame"] > last_frame, (
                            f"帧序错误: drones[{i}].poseKeyFrames[{j}].frame "
                            f"当前帧序 ({kf['frame']}) 必须大于上一帧的帧序 ({last_frame})"
                        )

                        # 验证 pitch/roll/yaw 字段
                        log_manager.logger.info(f"验证 drones[{i}].poseKeyFrames[{j}] pitch={kf.get('pitch')}, roll={kf.get('roll')}, yaw={kf.get('yaw')}")
                        assert kf.get("pitch") is not None, f"字段 drones[{i}].poseKeyFrames[{j}].pitch 不能为空"
                        assert kf.get("roll") is not None, f"字段 drones[{i}].poseKeyFrames[{j}].roll 不能为空"
                        assert kf.get("yaw") is not None, f"字段 drones[{i}].poseKeyFrames[{j}].yaw 不能为空"

    @allure.title("验证drones[].totalPointFrameCount字段非空")
    @allure.description("验证每个drone的totalPointFrameCount字段值不为空")
    def test_drones_total_point_frame_count(self, drama3):
        with allure.step("检查drones[].totalPointFrameCount字段"):
            drones = drama3["drones"]
            for i, drone in enumerate(drones):
                log_manager.logger.info(f"验证 drones[{i}].totalPointFrameCount: {drone.get('totalPointFrameCount')}")
                assert drone["totalPointFrameCount"] != 0, f"字段 drones[{i}].totalPointFrameCount 为空"

    @allure.title("验证drones[].totalPayloadFrameCount字段非空")
    @allure.description("验证每个drone的totalPayloadFrameCount字段值不为空")
    def test_drones_total_payload_frame_count(self, drama3):
        with allure.step("检查drones[].totalPayloadFrameCount字段"):
            drones = drama3["drones"]
            for i, drone in enumerate(drones):
                log_manager.logger.info(f"验证 drones[{i}].totalPayloadFrameCount: {drone.get('totalPayloadFrameCount')}")
                assert drone["totalPayloadFrameCount"] != 0, f"字段 drones[{i}].totalPayloadFrameCount 为空"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
