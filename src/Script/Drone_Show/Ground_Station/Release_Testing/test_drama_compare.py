#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os

import pytest
import allure

from src.Protocol.drama.drone_show.drama_reader import DramaReader
from src.Protocol.drama.drone_show.dat_reader import DatReader
from src.Protocol.drama.drone_show.drm_compare import DrmCompare, ERROR_CODE
from utils.logger import log_manager

@allure.feature("剧本信息验证")
@allure.story("验证解析后的实际数据")
class TestDramaCompare:
     
    @allure.title("比较单一无人机输入和输出的剧本数据-drama3和dat")
    @allure.description("")
    def test_one_drone_data(self, drama3_file_path, dat_file_path):
        saved_drama_path =None
        saved_dat_path = None
        png_list = []

        with allure.step("剧本存在性验证"):
            assert drama3_file_path, "drama3 文件路径未配置"
            assert dat_file_path, "dat 文件路径未配置"
            assert os.path.exists(drama3_file_path), f"drama3 文件不存在：{drama3_file_path}"
            assert os.path.exists(dat_file_path), f"dat 文件不存在：{dat_file_path}"
        
        with allure.step("传入单个无人机的剧本数据"):
            drama_reader = DramaReader()
            drama_data = drama_reader.read(drama3_file_path)
            saved_drama_path = drama_reader.save_one_drone_data(drone_num=1, interpolate=True)

        with allure.step("输出单个无人机数据"):
            dat_reader = DatReader()
            header, config, trailer, result_crc0, result_crc1, result_crc2 = dat_reader.process_file(dat_file_path)
            dat_reader.print_split_result(header, config, trailer, result_crc0, result_crc1, result_crc2)
            saved_dat_path = dat_reader.save_one_drone_data(config, trailer['frames'], dat_file_path, interpolate=True)
            
        with allure.step("比较保存的 drama3 数据和 dat 数据"):
            assert saved_drama_path and os.path.exists(saved_drama_path), f"保存的 drama3 数据文件不存在：{saved_drama_path}"
            assert saved_dat_path and os.path.exists(saved_dat_path), f"保存的 dat 数据文件不存在：{saved_dat_path}"
            drm_compare = DrmCompare(saved_drama_path, saved_dat_path)
            error_code = drm_compare.compare_one_drone_data()
            log_manager.logger.info(f"比较结果：{ERROR_CODE[error_code]} (错误代码 {error_code})")
            if error_code == 0:
                png_list = drm_compare.plot_differences()

        with allure.step("附图"):
            for png_path in png_list:
                if os.path.exists(png_path):
                    allure.attach.file(png_path, name=os.path.basename(png_path), attachment_type=allure.attachment_type.PNG)
                else:
                    log_manager.logger.warning(f"警告：图像文件不存在，无法附加：{png_path}")

    @allure.title("比较不同帧率的剧本数据-drama3")
    @allure.description("")
    def test_compare_drama_fps(self):
        drama_data_L10P2 = None
        drama_data_L10P10 = None
        drama_data_L30P2 = None
        drama_data_L30P10 = None

        with allure.step("剧本存在性验证"):
            fps_L10P2_file_path = "file/drama_files/0422-L10P2.drm"
            fps_L10P10_file_path = "file/drama_files/0422-L10P10.drm"
            fps_L30P2_file_path = "file/drama_files/0422-L30P2.drm"
            fps_L30P10_file_path = "file/drama_files/0422-L30P10.drm"
            assert os.path.exists(fps_L10P2_file_path), f"drama3 文件不存在：{fps_L10P2_file_path}"
            assert os.path.exists(fps_L10P10_file_path), f"drama3 文件不存在：{fps_L10P10_file_path}"
            assert os.path.exists(fps_L30P2_file_path), f"drama3 文件不存在：{fps_L30P2_file_path}"
            assert os.path.exists(fps_L30P10_file_path), f"drama3 文件不存在：{fps_L30P10_file_path}"

        with allure.step("加载不同帧率的剧本数据"):
            drama_reader_L10P2 = DramaReader()
            drama_data_L10P2 = drama_reader_L10P2.read(fps_L10P2_file_path)["drama3"]
            drama_reader_L10P10 = DramaReader()
            drama_data_L10P10 = drama_reader_L10P10.read(fps_L10P10_file_path)["drama3"]
            drama_reader_L30P2 = DramaReader()
            drama_data_L30P2 = drama_reader_L30P2.read(fps_L30P2_file_path)["drama3"]
            drama_reader_L30P10 = DramaReader()
            drama_data_L30P10 = drama_reader_L30P10.read(fps_L30P10_file_path)["drama3"]
            assert drama_data_L10P2 is not None, "无法加载 L10P2 的剧本数据"
            assert drama_data_L10P10 is not None, "无法加载 L10P10 的剧本数据"
            assert drama_data_L30P2 is not None, "无法加载 L30P2 的剧本数据"
            assert drama_data_L30P10 is not None, "无法加载 L30P10 的剧本数据"

        with allure.step("比较 L10P2 和 L10P10 的剧本数据 - ID差异验证"):
            log_manager.logger.info(f"L10P2剧本 ID: {drama_data_L10P2.get('dramaId')}")    
            log_manager.logger.info(f"L10P10剧本 ID: {drama_data_L10P10.get('dramaId')}")
            assert drama_data_L10P2.get('dramaId') != drama_data_L10P10.get('dramaId'), "L10P2 和 L10P10 的剧本 ID 不匹配" 

        with allure.step("比较 L30P2 和 L30P10 的剧本数据 - ID差异验证"):
            log_manager.logger.info(f"L30P2剧本 ID: {drama_data_L30P2.get('dramaId')}")    
            log_manager.logger.info(f"L30P10剧本 ID: {drama_data_L30P10.get('dramaId')}")
            assert drama_data_L30P2.get('dramaId') != drama_data_L30P10.get('dramaId'), "L30P2 和 L30P10 的剧本 ID 不匹配"

        with allure.step("比较 L10P2 和 L10P10 的剧本数据 - 位置帧率差异验证"):
            log_manager.logger.info(f"L10P2剧本 位置帧率: {drama_data_L10P2.get('pointFps')}")    
            log_manager.logger.info(f"L10P10剧本 位置帧率: {drama_data_L10P10.get('pointFps')}")
            assert drama_data_L10P2.get('pointFps') == 2, "L10P2 的剧本 位置帧率 应为 2"
            assert drama_data_L10P10.get('pointFps') == 10, "L10P10 的剧本 位置帧率 应为 10"

        with allure.step("比较 L30P2 和 L30P10 的剧本数据 - 位置帧率差异验证"):
            log_manager.logger.info(f"L30P2剧本 位置帧率: {drama_data_L30P2.get('pointFps')}")    
            log_manager.logger.info(f"L30P10剧本 位置帧率: {drama_data_L30P10.get('pointFps')}")
            assert drama_data_L30P2.get('pointFps') == 2, "L30P2 的剧本 位置帧率 应为 2"
            assert drama_data_L30P10.get('pointFps') == 10, "L30P10 的剧本 位置帧率 应为 10"

        with allure.step("比较 L10P2 和 L30P2 的剧本数据 - 灯光帧率差异验证"):
            log_manager.logger.info(f"L10P2剧本 灯光帧率: {drama_data_L10P2.get('payloadFps')}")    
            log_manager.logger.info(f"L30P2剧本 灯光帧率: {drama_data_L30P2.get('payloadFps')}")
            assert drama_data_L10P2.get('payloadFps') == 10, "L10P2 的剧本 灯光帧率 应为 10"
            assert drama_data_L30P2.get('payloadFps') == 30, "L30P2 的剧本 灯光帧率 应为 30"

        with allure.step("比较 L10P10 和 L30P10 的剧本数据 - 灯光帧率差异验证"):
            log_manager.logger.info(f"L10P10剧本 灯光帧率: {drama_data_L10P10.get('payloadFps')}")    
            log_manager.logger.info(f"L30P10剧本 灯光帧率: {drama_data_L30P10.get('payloadFps')}")
            assert drama_data_L10P10.get('payloadFps') == 10, "L10P10 的剧本 灯光帧率 应为 10"
            assert drama_data_L30P10.get('payloadFps') == 30, "L30P10 的剧本 灯光帧率 应为 30"

        with allure.step("抽样单一飞机剧本数据--位置帧数和灯光帧数验证"):
            drone_index = 1
            drone_L10P2 = drama_data_L10P2.get("drones", [])[drone_index]
            drone_L10P10 = drama_data_L10P10.get("drones", [])[drone_index]
            drone_L30P2 = drama_data_L30P2.get("drones", [])[drone_index]
            drone_L30P10 = drama_data_L30P10.get("drones", [])[drone_index]

            log_manager.logger.info(f"抽样验证无人机 {drone_index} 的剧本数据")
            log_manager.logger.info(f"L10P2剧本 位置帧数: {drone_L10P2.get('totalPointFrameCount')}, 灯光帧数: {drone_L10P2.get('totalPayloadFrameCount')}")
            log_manager.logger.info(f"L10P10剧本 位置帧数: {drone_L10P10.get('totalPointFrameCount')}, 灯光帧数: {drone_L10P10.get('totalPayloadFrameCount')}")
            log_manager.logger.info(f"L30P2剧本 位置帧数: {drone_L30P2.get('totalPointFrameCount')}, 灯光帧数: {drone_L30P2.get('totalPayloadFrameCount')}")
            log_manager.logger.info(f"L30P10剧本 位置帧数: {drone_L30P10.get('totalPointFrameCount')}, 灯光帧数: {drone_L30P10.get('totalPayloadFrameCount')}")  

            assert (drone_L10P2.get('totalPointFrameCount') - 1) /  (drone_L10P2.get('totalPayloadFrameCount') - 1) == 0.2, "L10P2 和 L10P10 的位置帧数比例不正确"
            assert (drone_L10P10.get('totalPointFrameCount') - 1) /  (drone_L10P10.get('totalPayloadFrameCount') - 1) == 1, "L10P10 的位置帧数比例不正确"
            assert (drone_L30P2.get('totalPointFrameCount') - 1) /  (drone_L30P2.get('totalPayloadFrameCount') - 1) <= 0.07, "L30P2 和 L30P10 的位置帧数比例不正确"
            assert (drone_L30P10.get('totalPointFrameCount') - 1) /  (drone_L30P10.get('totalPayloadFrameCount') - 1) <= 0.34, "L30P10 的位置帧数比例不正确"

    @allure.title("比较不同帧率的剧本数据-dat")
    @allure.description("")
    def test_compare_dat_fps(self):
        dat_data_L10P2 = None
        dat_data_L10P10 = None
        dat_data_L30P2 = None
        dat_data_L30P10 = None

        with allure.step("dat 文件存在性验证"):
            fps_L10P2_file_path = "file/dat_files/L10P2.txt"
            fps_L10P10_file_path = "file/dat_files/L10P10.txt"
            fps_L30P2_file_path = "file/dat_files/L30P2.txt"
            fps_L30P10_file_path = "file/dat_files/L30P10.txt"
            assert os.path.exists(fps_L10P2_file_path), f"dat 文件不存在：{fps_L10P2_file_path}"
            assert os.path.exists(fps_L10P10_file_path), f"dat 文件不存在：{fps_L10P10_file_path}"
            assert os.path.exists(fps_L30P2_file_path), f"dat 文件不存在：{fps_L30P2_file_path}"
            assert os.path.exists(fps_L30P10_file_path), f"dat 文件不存在：{fps_L30P10_file_path}"

        with allure.step("加载不同帧率的 dat 数据"):
            saved_dat_paths = []
            
            dat_reader = DatReader()
            for file_path in [fps_L10P2_file_path, fps_L10P10_file_path, fps_L30P2_file_path, fps_L30P10_file_path]:
                log_manager.logger.info(f"正在加载 dat 文件：{file_path}")
                header, config, trailer, result_crc0, result_crc1, result_crc2 = dat_reader.process_file(file_path)
                dat_reader.print_split_result(header, config, trailer, result_crc0, result_crc1, result_crc2)
                saved_dat_path = dat_reader.save_one_drone_data(config, trailer['frames'], file_path, interpolate=True)
                assert saved_dat_path and os.path.exists(saved_dat_path), f"保存的 dat 数据文件不存在：{saved_dat_path}"
                log_manager.logger.info(f"成功加载并保存 dat 文件：{file_path}，保存路径：{saved_dat_path}")
                saved_dat_paths.append(saved_dat_path)


            dat_data_L10P2 = dat_reader.read_json_file(saved_dat_paths[0])
            dat_data_L10P10 = dat_reader.read_json_file(saved_dat_paths[1])
            dat_data_L30P2 = dat_reader.read_json_file(saved_dat_paths[2])
            dat_data_L30P10 = dat_reader.read_json_file(saved_dat_paths[3])
            assert dat_data_L10P2 is not None, "无法加载 L10P2 的 dat 数据"
            assert dat_data_L10P10 is not None, "无法加载 L10P10 的 dat 数据"
            assert dat_data_L30P2 is not None, "无法加载 L30P2 的 dat 数据"
            assert dat_data_L30P10 is not None, "无法加载 L30P10 的 dat 数据"

        with allure.step("比较 dat 数据 - 位置帧数和灯光帧数验证"):
            for dat_data, label in zip([dat_data_L10P2, dat_data_L10P10, dat_data_L30P2, dat_data_L30P10], ["L10P2", "L10P10", "L30P2", "L30P10"]):
                log_manager.logger.info(f"{label} dat 数据 位置帧数: {dat_data.get('pointFps')}, 灯光帧数: {dat_data.get('payloadFps')}")  
                assert dat_data.get('pointFps') in [2, 10], f"{label} 的 dat 数据 位置帧数 应为 2 或 10"
                assert dat_data.get('payloadFps') in [10, 30], f"{label} 的 dat 数据 灯光帧数 应为 10 或 30"

    @pytest.mark.parametrize("drone_1_drama_json, drone_1_dat_json", [
        ("file/drama_files/0422-L10P2_drone_1.json", "file/dat_files/L10P2.json"),
        ("file/drama_files/0422-L10P10_drone_1.json", "file/dat_files/L10P10.json"),
        ("file/drama_files/0422-L30P2_drone_1.json", "file/dat_files/L30P2.json"),
        ("file/drama_files/0422-L30P10_drone_1.json", "file/dat_files/L30P10.json")
    ])
    @allure.title("比较单一无人机输入和输出的剧本数据-drama3和dat-数据差异验证")
    @allure.description("")
    def test_compare_differences(self, drone_1_drama_json, drone_1_dat_json):

        with allure.step("加载单一无人机的 drama3 和 dat 数据"):
            assert os.path.exists(drone_1_drama_json), f"drama3 数据文件不存在：{drone_1_drama_json}"
            assert os.path.exists(drone_1_dat_json), f"dat 数据文件不存在：{drone_1_dat_json}"

            drm_compare = DrmCompare(drone_1_drama_json, drone_1_dat_json)
            error_code = drm_compare.compare_one_drone_data()
            log_manager.logger.info(f"比较结果：{ERROR_CODE[error_code]} (错误代码 {error_code})")
            if error_code == 0:
                png_list = drm_compare.plot_differences()

        with allure.step("附图"):
            for png_path in png_list:
                if os.path.exists(png_path):
                    allure.attach.file(png_path, name=os.path.basename(png_path), attachment_type=allure.attachment_type.PNG)
                else:
                    log_manager.logger.warning(f"警告：图像文件不存在，无法附加：{png_path}")


if __name__ == "__main__":
    pytest.main(["-v", "-s", "test_drama_compare.py"])  