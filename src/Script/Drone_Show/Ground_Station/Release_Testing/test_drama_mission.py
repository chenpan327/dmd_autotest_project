#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
剧本执行验证测试模块

该模块用于验证大漠大地面控制站（DGCS）将剧本下发到真实无人机后，
无人机实际执行的轨迹数据（dat 文件）与原始剧本数据（drama3 文件）的一致性。

测试主流程：
    1. 登录地面站
    2. 配置无人机（设置室内调试模式、设置原点）
    3. 加载并传输剧本
    4. 解析 drama3 和 dat 文件
    5. 比较两份数据并输出差异图像
"""
import datetime
import os

import pytest
import allure
from datetime import datetime, timedelta

from src.Protocol.drama.drone_show.drama_reader import DramaReader
from src.Protocol.drama.drone_show.dat_reader import DatReader
from src.Protocol.drama.drone_show.drm_compare import DrmCompare, ERROR_CODE
from utils.logger import log_manager

@allure.feature("剧本执行验证")
@allure.story("")
class TestDramaMission:
    """剧本执行验证测试类，用于验证剧本传输与执行的正确性。"""

    @allure.title("剧本执行验证-真实飞机")
    @allure.description("")
    def test_drama_mission(
        self,
        dgcs_app,
        dgcs_username,
        dgcs_password,
        dgcs_drone_id,
        dgcs_drama_id,
        dgcs_drama_file,
        drama3_file_path,
        dat_file_path,
    ):
        """
        剧本执行验证主测试用例。

        参数说明：
            dgcs_app:          DGCS 应用对象（由 conftest fixture 注入）
            dgcs_username:     登录用户名
            dgcs_password:     登录密码
            dgcs_drone_id:     目标无人机 ID
            dgcs_drama_id:     剧本 ID
            dgcs_drama_file:   待加载的剧本文件路径
            drama3_file_path:  drama3 源文件路径（原始剧本数据）
            dat_file_path:     dat 文件路径（无人机执行后的轨迹数据）
        """
        # 用于存储中间生成的单机数据文件路径以及差异图像列表
        saved_drama_path = None  # 单机剧本数据保存路径
        saved_dat_path = None    # 单机 dat 数据保存路径
        png_list = []            # 差异对比图像路径列表

        # ====== 步骤 1：环境初始化 ======
        # 确认 DGCS 应用进程已启动并成功附加到主窗口，否则后续 UI 操作无法进行
        with allure.step("地面站和云平台-初始化"):
            assert dgcs_app.ui.is_app_running(), "DGCS 应用未在运行"
            assert dgcs_app.ui.main_window is not None, "未附加到主窗口"

        # ====== 步骤 2：登录地面站 ======
        # 若主窗口标题已包含「大漠大地面控制站」，说明已处于登录后状态，跳过登录流程；
        # 否则依次完成用户名、密码输入与登录点击，并校验登录后主窗口仍然存在
        with allure.step("地面站-登录"):
            if dgcs_app.ui.main_window and "大漠大地面控制站" in dgcs_app.ui.main_window.Name:
                pass
            else:
                assert dgcs_username, "未提供 --dgcs-username"
                assert dgcs_app.input_username(dgcs_username), "输入用户名失败"
                if dgcs_password:
                    assert dgcs_app.input_password(dgcs_password), "输入密码失败"
                assert dgcs_app.click_login(), "点击登录按钮失败"
                assert dgcs_app.check_login_success(wait_time=10), "登录失败"
                # 处理登录后可能出现的等待弹窗以及电池预警弹窗，避免阻塞后续步骤
                dgcs_app.check_main_window_waiting(wait_time=3)
                dgcs_app.check_battery_warming(wait_time=3)
                assert dgcs_app.ui.main_window is not None, "登录后主窗口丢失"

        # ====== 步骤 3：确认目标无人机参数 ======
        # 仅校验测试输入的无人机 ID 已通过命令行参数提供
        with allure.step("地面站-获取无人机信息确认无人机上线"):
            assert dgcs_drone_id, "未提供 --dgcs-drone-id"

        # ====== 步骤 4：将无人机切换为室内调试模式 ======
        # 室内调试模式（INDOOR_DEBUG=1）用于模拟飞行，确保测试可在地面安全环境下运行
        with allure.step("地面站-设置无人机为室内调试模式"):
            try:
                dgcs_app.set_drone_param_config(
                    drone_id=dgcs_drone_id,
                    param_config_name="INDOOR_DEBUG",
                    param_value="1",
                )
            except Exception as exc:
                pytest.fail(f"参数配置执行异常: {exc}")

        # ====== 步骤 5：设置无人机原点 ======
        # 设置过程中可能弹出「相邻项目」提示，需主动关闭以保证操作完成
        with allure.step("地面站-设置原点"):
            result = dgcs_app.set_origin(drone_id=dgcs_drone_id)
            dgcs_app.check_and_close_adjacent_project_warning(wait_time=3)
            assert result is True, f"无人机 {dgcs_drone_id} 原点设置失败"

        # ====== 步骤 6：加载剧本文件 ======
        # 校验剧本文件路径有效且加载成功，加载等待 5 秒以避免大型剧本未完成解析
        with allure.step("地面站-加载剧本"):
            assert dgcs_drama_file, "未提供 --dgcs-drama-file"
            assert os.path.exists(dgcs_drama_file), f"剧本文件不存在: {dgcs_drama_file}"
            assert dgcs_app.load_drama(filename=dgcs_drama_file, wait_time=5), \
                f"剧本加载失败: {dgcs_drama_file}"

        # ====== 步骤 7：设置剧本与无人机的映射关系 ======
        # 使用 Excel 映射方式将剧本中的逻辑机号自动映射到真实无人机
        with allure.step("地面站-设置剧本自动映射"):
            result = dgcs_app.set_mapping_by_excel(
                drama_id=dgcs_drama_id,
                drone_id=dgcs_drone_id,
                wait_time=5,
            )
            assert result is True, "通过 Excel 设置映射失败"

        # ====== 步骤 8：设置剧本播放时间 ======
        with allure.step("地面站-设置播放时间"):
            result = dgcs_app.set_time()
            assert result is True, "时间设置失败"

        # ====== 步骤 9：将剧本传输到无人机 ======
        # 传输过程较耗时，最长等待 15 秒；返回值为 None 表示传输失败
        with allure.step("地面站-传输剧本"):
            result = dgcs_app.transmit_drama(drone_id=dgcs_drone_id, wait_time=15)
            assert result is not None, f"无人机 {dgcs_drone_id} 剧本传输失败"

        # ====== 步骤 10：验证比对所需的源文件存在 ======
        # drama3 为原始剧本数据，dat 为无人机执行后产生的轨迹数据，两者均需存在才能比对
        with allure.step("剧本存在性验证"):
            assert drama3_file_path, "drama3 文件路径未配置"
            assert dat_file_path, "dat 文件路径未配置"
            assert os.path.exists(drama3_file_path), f"drama3 文件不存在：{drama3_file_path}"
            assert os.path.exists(dat_file_path), f"dat 文件不存在：{dat_file_path}"

        # ====== 步骤 11：解析 drama3 文件并导出单机数据 ======
        # interpolate=True 表示对时间序列做插值处理，保证与 dat 数据采样率对齐
        with allure.step("传入单个无人机的剧本数据"):
            drama_reader = DramaReader()
            drama_data = drama_reader.read(drama3_file_path)
            saved_drama_path = drama_reader.save_one_drone_data(drone_num=1, interpolate=True)

        # ====== 步骤 12：解析 dat 文件并导出单机数据 ======
        # process_file 返回文件头、配置、尾部以及三组 CRC 校验结果
        # trailer['frames'] 为实际飞行轨迹帧序列
        with allure.step("输出单个无人机数据"):
            dat_reader = DatReader()
            header, config, trailer, result_crc0, result_crc1, result_crc2 = dat_reader.process_file(dat_file_path)
            dat_reader.print_split_result(header, config, trailer, result_crc0, result_crc1, result_crc2)
            saved_dat_path = dat_reader.save_one_drone_data(config, trailer['frames'], dat_file_path, interpolate=True)

        # ====== 步骤 13：比对 drama3 与 dat 数据 ======
        # error_code == 0 时数据一致，此时生成差异折线图便于在报告中查看；非 0 表示数据存在差异
        with allure.step("比较保存的 drama3 数据和 dat 数据"):
            assert saved_drama_path and os.path.exists(saved_drama_path), f"保存的 drama3 数据文件不存在：{saved_drama_path}"
            assert saved_dat_path and os.path.exists(saved_dat_path), f"保存的 dat 数据文件不存在：{saved_dat_path}"
            drm_compare = DrmCompare(saved_drama_path, saved_dat_path)
            error_code = drm_compare.compare_one_drone_data()
            print(f"比较结果：{ERROR_CODE[error_code]} (错误代码 {error_code})")
            if error_code == 0:
                png_list = drm_compare.plot_differences()

        # ====== 步骤 14：将差异图像作为附件添加到 Allure 报告 ======
        with allure.step("附图"):
            for png_path in png_list:
                if os.path.exists(png_path):
                    allure.attach.file(png_path, name=os.path.basename(png_path), attachment_type=allure.attachment_type.PNG)
                else:
                    print(f"警告：图像文件不存在，无法附加：{png_path}")

        # ====== 步骤 15：地面站退出（占位，后续可补充清理动作）======
        with allure.step("地面站-退出"):
            pass
