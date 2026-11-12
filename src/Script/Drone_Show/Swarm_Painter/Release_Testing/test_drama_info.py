#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pytest
import allure
from utils.logger import log_manager
from src.Script.Drone_Show.Swarm_Painter.Release_Testing.conftest import drone_index_list, load_drama_data, data_file_path

example_drone_type = "V4"

AUTOPILOT_TYPE_MAP = {
    81: "X1",
    41: "L3",
    21: "V3",
    43: "L1",
    31: "V4"
}

@allure.feature("剧本信息验证")
@allure.story("验证解析后的实际数据")
class TestDramaInfo:
    """验证解析后的实际数据"""
    @pytest.mark.parametrize("drama3_file_name", [data_file_path])
    @allure.title("drama3 文件名验证")
    @allure.description("")
    def test_drama_filename(self, drama3_file_name):
        """验证 drama3 文件名是否正确加载"""
        drama_data = load_drama_data()
        if drama_data is None:
            pytest.skip("无法加载 drama3 数据，跳过文件名验证") 
        assert drama3_file_name != "", "drama3 文件名未正确加载"
        with allure.step(f"drama3 文件名: {drama3_file_name}"):
            pass

    # ==================== drama3 基础信息解读 ====================
    @allure.title("drama3 基础信息解读")
    @allure.description("")
    def test_drama_info(self, drama3):
        with allure.step(f"dramaId: {drama3.get('dramaId')}"):
            pass
        with allure.step(f"droneCount: {drama3.get('droneCount')}"):
            pass
        with allure.step(f"sceneName: {drama3.get('sceneName')}"):
            pass
        with allure.step(f"description: {drama3.get('description')}"):
            pass
        with allure.step(f"payloadFps: {drama3.get('payloadFps')}"):
            pass
        with allure.step(f"pointFps: {drama3.get('pointFps')}"):
            pass
        with allure.step(f"dramaVersion: {drama3.get('dramaVersion')}"):
            pass
        with allure.step(f"authorName: {drama3.get('authorName')}"):
            pass
        with allure.step(f"drones: 共 {len(drama3.get('drones', []))} 个无人机"):
            pass
        
    @pytest.mark.parametrize("drone_index", drone_index_list)
    @allure.title("drama3 无人机剧本信息总结")
    @allure.description("")
    def test_drama_info_summary(self, drone_index):
        drone = load_drama_data().get("drama3", {}).get("drones", [])[drone_index]

        with allure.step(f"drones[{drone_index}] 的基本信息"):
            log_manager.logger.info(f"id: {drone.get('id')}")
            log_manager.logger.info(f"droneType: {drone.get('droneType')}")
            log_manager.logger.info(f"当前机型为: {AUTOPILOT_TYPE_MAP.get(drone.get('droneType'), '未知机型')}")
            log_manager.logger.info(f"returnType: {drone.get('returnType')}")
            log_manager.logger.info(f"playTime: {drone.get('playTime')}")
            log_manager.logger.info(f"totalPointFrameCount: {drone.get('totalPointFrameCount')}")
            log_manager.logger.info(f"totalPayloadFrameCount: {drone.get('totalPayloadFrameCount')}")

        # === 总结剧本信息 ===
        with allure.step(f"无人机 {drone.get('id')} 的剧本信息总结"):
            # === 解析 positionKeyFrames 中的飞行高度信息 ===
            position_kfs = drone.get("positionKeyFrames", [])
            log_manager.logger.info(f"positionKeyFrames: 共 {len(position_kfs)} 个关键帧")
            if len(position_kfs) > 0:
                max_hight = max((kf.get("z", 0) for kf in position_kfs), default=0)
                log_manager.logger.info(f"最大飞行高度: {max_hight} 米")
                min_hight = min((kf.get("z", 0) for kf in position_kfs), default=0)
                log_manager.logger.info(f"最小飞行高度: {min_hight} 米")

                first_frame_hight = position_kfs[0].get("z", 0) if position_kfs else 0
                log_manager.logger.info(f"首帧飞行高度: {first_frame_hight} 米")
                last_frame_hight = position_kfs[-1].get("z", 0) if position_kfs else 0
                log_manager.logger.info(f"末帧飞行高度: {last_frame_hight} 米")
            else:
                log_manager.logger.info("positionKeyFrames 为空，无飞行高度数据")

            # === 解析 lightKeyFrames 中的灯光信息 ===
            light_kfs = drone.get("lightKeyFrames", [])
            log_manager.logger.info(f"lightKeyFrames: 共 {len(light_kfs)} 个关键帧")
            if len(light_kfs) > 0:
                first_frame_light = light_kfs[0].get("lights", {}) if light_kfs else {}
                log_manager.logger.info(f"首帧灯光状态: r={first_frame_light.get('r')}, g={first_frame_light.get('g')}, b={first_frame_light.get('b')}")
                last_frame_light = light_kfs[-1].get("lights", {}) if light_kfs else {}
                log_manager.logger.info(f"末帧灯光状态: r={last_frame_light.get('r')}, g={last_frame_light.get('g')}, b={last_frame_light.get('b')}")
            else:
                log_manager.logger.info("lightKeyFrames 为空，无灯光数据")

            # === 解析 novaKeyFrames 中的 nova 信息 ===
            nova_kfs = drone.get("novaKeyFrames", [])
            log_manager.logger.info(f"novaKeyFrames: 共 {len(nova_kfs)} 个关键帧")
            if len(nova_kfs) > 0:
                first_frame_nova = nova_kfs[0].get("novas", {}) if nova_kfs else {}
                log_manager.logger.info(f"首帧 nova 状态: power={first_frame_nova.get('power')}")
                last_frame_nova = nova_kfs[-1].get("novas", {}) if nova_kfs else {}
                log_manager.logger.info(f"末帧 nova 状态: power={last_frame_nova.get('power')}")
                max_nova_power = max((kf.get("novas", {}).get("power", 0) for kf in nova_kfs), default=0)
                log_manager.logger.info(f"最大 nova power: {max_nova_power}")
                min_nova_power = min((kf.get("novas", {}).get("power", 0) for kf in nova_kfs), default=0)
                log_manager.logger.info(f"最小 nova power: {min_nova_power}")
            else:
                log_manager.logger.info("novaKeyFrames 为空，无 nova 数据")

            # === 解析 fireworksKeyFrames 中的烟花信息 ===
            fireworks_kfs = drone.get("fireworksKeyFrames", [])
            log_manager.logger.info(f"fireworksKeyFrames: 共 {len(fireworks_kfs)} 个关键帧")
            if len(fireworks_kfs) > 0:
                first_frame_fw = fireworks_kfs[0].get("fireworks", {}) if fireworks_kfs else {}
                log_manager.logger.info(f"首帧烟花状态: firedPort={first_frame_fw.get('firedPort')}")
                for j, kf in enumerate(first_frame_fw.get("fireworkAngles", [])):
                    log_manager.logger.info(f"首帧烟花角度 通道{j}: {kf.get('channel')}, 角度: {kf.get('angle')}")
                last_frame_fw = fireworks_kfs[-1].get("fireworks", {}) if fireworks_kfs else {}
                log_manager.logger.info(f"末帧烟花状态: firedPort={last_frame_fw.get('firedPort')}")
                for j, kf in enumerate(last_frame_fw.get("fireworkAngles", [])):
                    log_manager.logger.info(f"末帧烟花角度 通道{j}: {kf.get('channel')}, 角度: {kf.get('angle')}")
            else:
                log_manager.logger.info("fireworksKeyFrames 为空，无烟花数据")

            # === 解析 lanternKeyFrames 中的灯笼信息 ===
            lantern_kfs = drone.get("lanternKeyFrames", [])
            log_manager.logger.info(f"lanternKeyFrames: 共 {len(lantern_kfs)} 个关键帧")
            if len(lantern_kfs) > 0:
                first_frame_lantern = lantern_kfs[0].get("lanterns", {}) if lantern_kfs else {}
                log_manager.logger.info(f"首帧灯笼状态: isOn={first_frame_lantern.get('isOn')}")
                last_frame_lantern = lantern_kfs[-1].get("lanterns", {}) if lantern_kfs else {}
                log_manager.logger.info(f"末帧灯笼状态: isOn={last_frame_lantern.get('isOn')}")
            else:
                log_manager.logger.info("lanternKeyFrames 为空，无灯笼数据")

            # === 解析 gimbalKeyFrames 中的云台信息 ===
            gimbal_kfs = drone.get("gimbalKeyFrames", [])
            log_manager.logger.info(f"gimbalKeyFrames: 共 {len(gimbal_kfs)} 个关键帧")
            if len(gimbal_kfs) > 0:
                first_frame_gimbal = gimbal_kfs[0].get("gimbals", {}) if gimbal_kfs else {}
                log_manager.logger.info(f"首帧云台状态: pitch={first_frame_gimbal.get('pitch')}, roll={first_frame_gimbal.get('roll')}, yaw={first_frame_gimbal.get('yaw')}")
                last_frame_gimbal = gimbal_kfs[-1].get("gimbals", {}) if gimbal_kfs else {}
                log_manager.logger.info(f"末帧云台状态: pitch={last_frame_gimbal.get('pitch')}, roll={last_frame_gimbal.get('roll')}, yaw={last_frame_gimbal.get('yaw')}")
            else:
                log_manager.logger.info("gimbalKeyFrames 为空，无云台数据")


            # === 解析 lazerKeyFrames 中的激光信息 ===
            lazer_kfs = drone.get("lazerKeyFrames", [])
            log_manager.logger.info(f"lazerKeyFrames: 共 {len(lazer_kfs)} 个关键帧")
            if len(lazer_kfs) > 0:
                first_frame_lazer = lazer_kfs[0].get("lazers", {}) if lazer_kfs else {}
                log_manager.logger.info(f"首帧激光状态: r={first_frame_lazer.get('r')}, g={first_frame_lazer.get('g')}, b={first_frame_lazer.get('b')}")
                last_frame_lazer = lazer_kfs[-1].get("lazers", {}) if lazer_kfs else {}
                log_manager.logger.info(f"末帧激光状态: r={last_frame_lazer.get('r')}, g={last_frame_lazer.get('g')}, b={last_frame_lazer.get('b')}")
            else:
                log_manager.logger.info("lazerKeyFrames 为空，无激光数据")

            # === 解析 poseKeyFrames 中的姿态信息 ===
            pose_kfs = drone.get("poseKeyFrames", [])
            log_manager.logger.info(f"poseKeyFrames: 共 {len(pose_kfs)} 个关键帧")
            if len(pose_kfs) > 0:
                first_frame_pose = pose_kfs[0]
                log_manager.logger.info(f"首帧姿态状态: pitch={first_frame_pose.get('pitch')}, roll={first_frame_pose.get('roll')}, yaw={first_frame_pose.get('yaw')}")
                last_frame_pose = pose_kfs[-1]
                log_manager.logger.info(f"末帧姿态状态: pitch={last_frame_pose.get('pitch')}, roll={last_frame_pose.get('roll')}, yaw={last_frame_pose.get('yaw')}")
            else:
                log_manager.logger.info("poseKeyFrames 为空，无姿态数据")

            
if __name__ == "__main__":
    pytest.main([__file__, "-v"])