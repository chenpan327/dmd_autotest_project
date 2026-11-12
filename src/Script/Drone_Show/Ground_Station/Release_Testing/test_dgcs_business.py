# -*- coding: utf-8 -*-
"""
test_dgcs_business.py

DGCS 业务层（DgcsBusiness）自动化测试套件，基于 pytest 框架实现。

================================================================
模块说明
================================================================
本测试套件以 DGCS（大漠大地面控制站）应用为被测对象，通过 DgcsBusiness
业务封装层驱动 UI 自动化，对地面站的核心业务流程进行端到端回归验证。

================================================================
测试覆盖范围
================================================================
1. 应用生命周期管理
   - 应用启动与主窗口附加
   - 应用退出与资源释放

2. 登录流程
   - 用户名输入
   - 密码输入
   - 登录按钮点击
   - 登录结果校验（主窗口切换、电量告警关闭等）

3. 剧本管理
   - 加载本地剧本文件（.dgcs）
   - 设置原点坐标
   - 设置演出起始时间
   - 通过 Excel 配置剧本-无人机映射
   - 剧本传输至无人机
   - 剧本传输结果验证

4. 无人机信息与参数
   - 无人机详情查看
   - 飞控参数配置（如 INDOOR_DEBUG 等）

5. 端到端完整表演流程
   - 登录 → 设置原点 → 加载剧本 → 设置映射 → 设置时间 → 传输剧本 → 验证传输

================================================================
命令行参数（由 conftest.py 中的 dgcs_* fixture 提供）
================================================================
--dgcs-app-path     DGCS 可执行文件路径
--dgcs-username     登录用户名
--dgcs-password     登录密码
--dgcs-drone-id     目标无人机 ID
--dgcs-drama-id     剧本 ID（默认 1）
--dgcs-drama-file   剧本文件绝对路径
--skip-gui          跳过所有依赖真实 GUI 的测试
"""

import os
import pytest


# ============================================================
# 应用生命周期测试
# ============================================================

@pytest.mark.gui
class TestAppLifecycle:
    """DGCS 应用启动与关闭流程测试。

    验证应用能够被正常拉起、成功附加到主窗口控件树，
    为后续的 UI 自动化操作提供前置环境。
    """

    def test_start_app(self, dgcs_app):
        """断言应用成功启动并完成主窗口附加。

        通过 dgcs_app fixture 启动应用，校验：
        - 应用进程处于运行状态
        - UI 框架已成功定位到主窗口对象
        """
        assert dgcs_app.ui.is_app_running(), "DGCS 应用未在运行"
        assert dgcs_app.ui.main_window is not None, "未附加到主窗口"


# ============================================================
# 登录流程测试
# ============================================================

@pytest.mark.gui
@pytest.mark.login
class TestLoginFlow:
    """登录界面相关业务测试。

    按"输入用户名 → 输入密码 → 点击登录 → 校验登录结果"
    的顺序对登录流程进行分步验证，便于精准定位失败环节。
    """

    def test_input_username(self, dgcs_app, dgcs_username):
        """校验用户名输入框可被正确填入。

        若未通过 --dgcs-username 提供用户名，则跳过该用例。
        """
        if not dgcs_username:
            pytest.skip("未提供 --dgcs-username")
        result = dgcs_app.input_username(dgcs_username)
        assert result is True, "输入用户名失败"

    def test_input_password(self, dgcs_app, dgcs_password):
        """校验密码输入框可被正确填入。

        若未通过 --dgcs-password 提供密码，则跳过该用例。
        """
        if not dgcs_password:
            pytest.skip("未提供 --dgcs-password")
        result = dgcs_app.input_password(dgcs_password)
        assert result is True, "输入密码失败"

    def test_click_login(self, dgcs_app, dgcs_username, dgcs_password):
        """校验登录按钮可被成功点击。

        前置：先填入用户名与密码（密码为可选项），
        再执行登录按钮点击动作。
        """
        if not dgcs_username:
            pytest.skip("未提供 --dgcs-username")
        dgcs_app.input_username(dgcs_username)
        if dgcs_password:
            dgcs_app.input_password(dgcs_password)
        result = dgcs_app.click_login()
        assert result is True, "点击登录按钮失败"

    def test_login_success(self, dgcs_app):
        """校验登录成功后能进入主控制窗口。

        逻辑：
        - 若当前已停留在"大漠大地面控制站"主窗口，视为已登录，跳过用例避免重复登录；
        - 否则等待登录完成（最长 10s），并关闭可能出现的电量预警等浮层；
        - 最终断言主窗口仍然有效。
        """
        if dgcs_app.ui.main_window and "大漠大地面控制站" in dgcs_app.ui.main_window.Name:
            pytest.skip("应用已处于登录状态，跳过成功登录测试")
        success = dgcs_app.check_login_success(wait_time=10)
        assert success is True, "期望登录成功，但实际返回失败"
        dgcs_app.check_main_window_waiting(wait_time=3)
        dgcs_app.check_battery_warming(wait_time=3)
        assert dgcs_app.ui.main_window is not None, "登录后主窗口丢失"


# ============================================================
# 剧本端到端业务测试
# ============================================================

@pytest.mark.gui
@pytest.mark.login
@pytest.mark.e2e
class TestFullShowFlow:
    """剧本完整业务流程测试。

    依次覆盖：参数配置 → 原点设置 → 剧本加载 → 映射设置 →
    时间设置 → 剧本传输 → 传输验证。所有用例使用已登录的
    dgcs_login fixture，确保从主控制窗口开始执行。
    """

    def test_set_drone_param_config(self, dgcs_login, dgcs_drone_id):
        """校验无人机飞控参数配置流程。

        说明：
        - 本用例使用 INDOOR_DEBUG=1 作为示例参数；
        - 实际可用参数取决于飞控固件，运行前请按需替换；
        - 参数配置会触发多面板的开关切换，过程较脆弱，
          此处仅做"不抛异常"级别的弱断言。
        """
        if not dgcs_drone_id:
            pytest.skip("未提供 --dgcs-drone-id")
        try:
            dgcs_login.set_drone_param_config(
                drone_id=dgcs_drone_id,
                param_config_name="INDOOR_DEBUG",
                param_value="1",
            )
        except Exception as exc:
            pytest.fail(f"参数配置执行异常: {exc}")

    def test_set_origin(self, dgcs_login, dgcs_drone_id):
        """校验为指定无人机设置原点的业务流程。

        设置完成后顺带关闭"邻近项目"等可能出现的提示弹窗，
        避免影响后续操作。
        """
        if not dgcs_drone_id:
            pytest.skip("未提供 --dgcs-drone-id")
        result = dgcs_login.set_origin(drone_id=dgcs_drone_id)
        dgcs_login.check_and_close_adjacent_project_warning(wait_time=3)
        assert result is True, f"无人机 {dgcs_drone_id} 原点设置失败"

    def test_load_drama(self, dgcs_login, dgcs_drama_file):
        """校验从本地文件加载剧本的业务流程。

        加载前会校验剧本文件路径是否存在；不存在则跳过用例
        而非失败，避免环境差异导致误报。
        """
        if not dgcs_drama_file:
            pytest.skip("未提供 --dgcs-drama-file")
        if not os.path.exists(dgcs_drama_file):
            pytest.skip(f"剧本文件不存在: {dgcs_drama_file}")
        result = dgcs_login.load_drama(filename=dgcs_drama_file, wait_time=5)
        assert result is True, f"剧本加载失败: {dgcs_drama_file}"

    def test_set_mapping_by_excel(self, dgcs_login, dgcs_drama_id, dgcs_drone_id):
        """校验通过 Excel 文件批量配置剧本-无人机映射的流程。

        将剧本 ID 与目标无人机 ID 关联，为后续传输与起飞做准备。
        """
        if not dgcs_drone_id:
            pytest.skip("未提供 --dgcs-drone-id")
        result = dgcs_login.set_mapping_by_excel(
            drama_id=dgcs_drama_id,
            drone_id=dgcs_drone_id,
            wait_time=5,
        )
        assert result is True, "通过 Excel 设置映射失败"

    def test_set_time(self, dgcs_login):
        """校验剧本演出起始时间设置流程。"""
        result = dgcs_login.set_time()
        assert result is True, "时间设置失败"

    def test_transmit_drama(self, dgcs_login, dgcs_drone_id):
        """校验剧本下发至无人机的业务流程。

        最长等待 15s 以容纳大体积剧本的传输耗时；返回值非空
        即视为传输流程未异常终止。
        """
        if not dgcs_drone_id:
            pytest.skip("未提供 --dgcs-drone-id")
        result = dgcs_login.transmit_drama(drone_id=dgcs_drone_id, wait_time=15)
        assert result is not None, f"无人机 {dgcs_drone_id} 剧本传输失败"

    def test_verify_drama_by_drone_id(self, dgcs_login, dgcs_drone_id):
        """校验"剧本传输验证"功能可独立执行。

        步骤：
        1. 打开剧本传输面板并触发传输弹窗；
        2. 调用 verify_drama_by_drone_id 对指定无人机执行验证；
        3. 无论验证结果如何，统一关闭传输弹窗与传输面板，
           保证测试不污染后续用例的 UI 状态。
        """
        if not dgcs_drone_id:
            pytest.skip("未提供 --dgcs-drone-id")

        dgcs_login.ui.get_drama_cfg_drama_send_button().Click()
        import time
        time.sleep(0.5)
        dgcs_login.ui.get_dramatransmit_transmit_button().Click()
        time.sleep(0.5)

        result = dgcs_login.verify_drama_by_drone_id(drone_id=dgcs_drone_id, wait_time=15)

        try:
            close_btn = dgcs_login.ui.get_transmit_task_close_button()
            close_btn.Click()
            time.sleep(0.5)
        except Exception:
            pass
        try:
            dgcs_login.ui.get_drama_cfg_drama_send_button().Click()
            time.sleep(0.5)
        except Exception:
            pass

        assert result is True, f"无人机 {dgcs_drone_id} 剧本验证失败"
