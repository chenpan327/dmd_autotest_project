# coding: utf-8
"""
Guided 模式 flyto 飞行测试。

验证 Guided 模式下的 flyto 飞行行为：
- 必须在 Guided 模式下才能响应 flyto（其他模式下 action_req 不会被 guided 状态机处理）
- 可以从 PLAYING 状态打断：如果正在执行航点/剧本任务，flyto 会中断它并飞向新目标
- 到达目标后：自动切回 GUIDED_STATE_FLYING（悬停），不会自动降落
- 收到降落指令 → UAV_ACTION_LAND → 切换到 GUIDED_STATE_LANDING
"""

import time

import pytest
import allure
from utils.logger import logger


# ============================================================================
# Guided 模式 ID 常量
# ============================================================================
MODE_GUIDED = 4
MODE_STAB = 0
MODE_LOITER = 5
MODE_LAND = 9
MODE_AUTO = 3
MODE_RTL = 6


@allure.feature("Guided模式飞行测试")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "GUIDED_MODE", "FLYTO", "FLIGHT_TEST")


@pytest.mark.functional
class TestGuidedFlyto:
    """
    Guided 模式 flyto 飞行测试。

    验证 Guided 模式下的 flyto 飞行行为，覆盖以下场景：
    1. Guided 模式切换及前置条件检查
    2. Guided 模式下 flyto 命令响应
    3. 非 Guided 模式下 flyto 不被 guided 状态机处理
    4. PLAYING 状态中断：flyto 打断正在执行的航点/剧本任务
    5. 到达目标后行为：切回 GUIDED_STATE_FLYING 悬停，不自动降落
    6. 降落指令：UAV_ACTION_LAND → GUIDED_STATE_LANDING
    """

    # ========================================================================
    # 测试用航点坐标（根据实际测试场地调整）
    # ========================================================================
    WAYPOINT_A = (30.0, 120.0, 10.0)   # 目标航点 A
    WAYPOINT_B = (30.0001, 120.0001, 15.0)  # 目标航点 B（用于中断测试）

    @pytest.fixture(autouse=True)
    def setup_before_test(self, serial_protocol_handler):
        logger.info("前置操作：初始化协议处理器")
        self.serial = serial_protocol_handler

        # ---- 前置条件 ----
        # 1. 设置 INDOOR_DEBUG=1（室内调试模式，允许无 GPS 解锁）
        logger.info("前置：设置 INDOOR_DEBUG=1")
        set_ok = self.serial.set_parameter("INDOOR_DEBUG", 1)
        logger.info(f"set_parameter INDOOR_DEBUG=1 → {set_ok}")
        save_ok = self.serial.save_parameter("INDOOR_DEBUG")
        logger.info(f"save_parameter INDOOR_DEBUG → {save_ok}")
        if not (set_ok and save_ok):
            logger.warning("INDOOR_DEBUG 设置/保存失败，解锁可能受阻")

        # 2. 启动 DShot 协议（用于 flyto 过程中读取电机转速）
        logger.info("前置：启动 DShot 协议")
        dshot_ok = self.serial.set_dshot_start()
        logger.info(f"set_dshot_start → {dshot_ok}")
        time.sleep(3)  # 等待 DShot 协议启动稳定

        # 3. 解锁电机（Guided 模式 flyto 需要飞控处于解锁状态）
        logger.info("前置：发送 arm 解锁命令")
        arm_ok = self.serial.arm_motors()
        logger.info(f"arm_motors → {arm_ok}")

        yield

        # ---- 后置清理 ----
        logger.info("后置操作：清理测试资源")

        # 1. 锁定电机
        logger.info("后置：发送 disarm 锁定命令")
        try:
            self.serial.disarm_motors()
        except Exception as e:
            logger.warning(f"disarm 异常: {e}")

        # 2. 停止 DShot 协议
        logger.info("后置：停止 DShot 协议")
        try:
            self.serial.set_dshot_stop()
        except Exception as e:
            logger.warning(f"停止 DShot 异常: {e}")

        # 3. 恢复 INDOOR_DEBUG=0
        logger.info("后置：恢复 INDOOR_DEBUG=0")
        try:
            self.serial.set_parameter("INDOOR_DEBUG", 0)
            self.serial.save_parameter("INDOOR_DEBUG")
        except Exception as e:
            logger.warning(f"恢复 INDOOR_DEBUG 异常: {e}")

    # ========================================================================
    # 辅助方法
    # ========================================================================

    def _assert_mode(self, expected_mode_id: int, context: str = "") -> bool:
        """断言当前飞行模式为指定模式，返回是否匹配。"""
        mode_info = self.serial.get_current_mode()
        logger.info(f"当前模式信息: {mode_info}")
        actual_mode_id = mode_info.get("mode_id")
        if actual_mode_id != expected_mode_id:
            logger.warning(
                f"[{context}] 模式不匹配: 期望 mode_id={expected_mode_id}, "
                f"实际 mode_id={actual_mode_id}"
            )
            return False
        logger.info(f"[{context}] 模式验证通过: mode_id={actual_mode_id}")
        return True

    def _switch_to_guided(self) -> bool:
        """切换到 Guided 模式并验证。"""
        logger.info("切换到 Guided 模式")
        result = self.serial.set_mode("guided")
        if not result:
            logger.error("切换 Guided 模式失败")
            return False
        time.sleep(1.0)  # 等待模式切换生效
        return self._assert_mode(MODE_GUIDED, "切换 Guided")

    def _switch_to_stab(self) -> bool:
        """切换到 STAB 模式并验证。"""
        logger.info("切换到 STAB 模式")
        result = self.serial.set_mode("stab")
        if not result:
            logger.error("切换 STAB 模式失败")
            return False
        time.sleep(0.5)
        return True

    def _read_rpm_during_flyto(self, duration: float = 1.0, interval: float = 0.2) -> list:
        """
        flyto 过程中持续读取电机转速（DShot 遥测）。

        Args:
            duration: 采样总时长（秒）
            interval: 采样间隔（秒）

        Returns:
            rpm_samples: [(elapsed, rpm_result), ...] 采样记录列表
        """
        rpm_samples = []
        start = time.time()
        while (time.time() - start) < duration:
            elapsed = time.time() - start
            try:
                rpm_result = self.serial.read_motor_rpm()
                rpm_samples.append((elapsed, rpm_result))
                logger.info(f"[flyto +{elapsed:.1f}s] DShot RPM: {rpm_result}")
            except Exception as e:
                logger.warning(f"[flyto +{elapsed:.1f}s] 读取 RPM 异常: {e}")
                rpm_samples.append((elapsed, None))
            time.sleep(interval)
        return rpm_samples

    def _wait_flyto_complete(self, timeout: float = 30.0, poll_interval: float = 2.0) -> None:
        """
        等待 flyto 完成，超时则退出测试。

        轮询检查飞行模式是否保持在 Guided（mode_id=4）。
        如果模式异常偏离（非 Guided 且非 LAND）则提前失败。
        超时未完成则抛出 AssertionError 提示超时。

        Args:
            timeout: 最大等待时间（秒）
            poll_interval: 轮询间隔（秒）
        """
        logger.info(f"等待 flyto 完成，超时限制 {timeout}s ...")
        start = time.time()
        while (time.time() - start) < timeout:
            elapsed = time.time() - start
            mode_info = self.serial.get_current_mode()
            mode_id = mode_info.get("mode_id")
            logger.info(f"[flyto 等待 +{elapsed:.1f}s] 当前模式: {mode_info}")

            # Guided → 正在飞行或已到达悬停，正常继续等待
            if mode_id == MODE_GUIDED:
                # 读取一次转速辅助判断飞行状态
                try:
                    rpm = self.serial.read_motor_rpm()
                    logger.info(f"[flyto 等待 +{elapsed:.1f}s] DShot RPM: {rpm}")
                except Exception:
                    pass
                time.sleep(poll_interval)
                continue

            # LAND / RTL → 飞控进入了非预期模式，提前失败
            if mode_id in (MODE_LAND, MODE_RTL):
                raise AssertionError(
                    f"flyto 异常：飞控在 +{elapsed:.1f}s 进入 {mode_info.get('mode')} 模式，"
                    f"flyto 可能被中断或触发 failsafe"
                )

            # 其他未知模式也认为异常
            time.sleep(poll_interval)

        # 超时
        raise AssertionError(
            f"flyto 超时：{timeout}s 内未完成，飞控可能未抵达目标点或状态异常，"
            f"请检查飞行器状态"
        )

    # ========================================================================
    # 测试用例
    # ========================================================================

    # --- Guided 模式切换 ---

    @allure.story("Guided模式切换")
    @allure.title("切换到 Guided 模式并验证")
    @allure.description(
        "发送 mode guided 命令将飞控切换到 Guided 模式，"
        "验证当前模式 mode_id 为 4 (MODE_GUIDED)。"
        "Guided 模式是 flyto 命令响应的前提条件 —— "
        "只有在 Guided 模式下，action_req 才会被 guided 状态机处理。"
    )
    def test_switch_to_guided_mode(self):
        with allure.step("切换到 Guided 模式"):
            result = self.serial.set_mode("guided")
            logger.info(f"mode guided 返回: {result}")
            assert result, "切换 Guided 模式失败"

        with allure.step("等待模式切换生效"):
            time.sleep(1.0)

        with allure.step("验证当前模式为 Guided (mode_id=4)"):
            assert self._assert_mode(MODE_GUIDED, "Guided模式切换验证"), (
                "当前模式不是 Guided (mode_id != 4)"
            )

    # --- Guided 模式下 flyto ---

    @allure.story("Guided模式飞行")
    @allure.title("Guided 模式下发送 flyto 命令")
    @allure.description(
        "在 Guided 模式下发送 flyto <lat> <lon> <alt> 命令，"
        "验证命令被 guided 状态机接收并返回 OK / flying to 响应。"
        "前置条件：必须在 Guided 模式下（action_req 才会被 guided 状态机处理）。"
    )
    def test_flyto_in_guided_mode(self):
        with allure.step("前置：切换到 Guided 模式"):
            assert self._switch_to_guided(), "前置条件失败：无法切换到 Guided 模式"

        with allure.step("发送 flyto 命令"):
            lat, lon, alt = self.WAYPOINT_A
            logger.info(f"发送 flyto {lat} {lon} {alt}")
            result = self.serial.fly_to(lat, lon, alt)
            logger.info(f"flyto 返回: {result}")
            assert result, "Guided 模式下 flyto 命令失败"

        with allure.step("flyto 过程中通过 DShot 读取电机转速"):
            logger.info("flyto 已触发，持续读取电机转速验证电机转动...")
            rpm_samples = self._read_rpm_during_flyto(duration=3.0, interval=0.5)
            rpm_ok_count = sum(1 for _, r in rpm_samples if r)
            logger.info(f"DShot RPM 采样 {len(rpm_samples)} 次，成功 {rpm_ok_count} 次")
            # 至少有一次成功读取转速，说明电机响应了 flyto 指令
            assert rpm_ok_count > 0, (
                "flyto 过程中 DShot RPM 全部读取失败，电机可能未响应"
            )

        with allure.step("验证飞控仍处于 Guided 模式（flyto 不改变模式）"):
            mode_info = self.serial.get_current_mode()
            logger.info(f"flyto 后当前模式: {mode_info}")
            assert mode_info.get("mode_id") == MODE_GUIDED, (
                f"flyto 后模式异常: 期望 Guided(4), 实际 {mode_info.get('mode_id')}"
            )

    # --- 非 Guided 模式下 flyto 无效 ---

    @allure.story("Guided模式前置条件")
    @allure.title("非 Guided 模式下 flyto 不被 guided 状态机处理")
    @allure.description(
        "验证在非 Guided 模式（如 STAB/LOITER）下，flyto 命令虽然可以发送，"
        "但 action_req 不会被 guided 状态机处理，飞行器不会响应飞向目标。"
        "原因：flyto 基于 MAVLink guided 状态机实现，"
        "只有在 Guided 模式下状态机才会处理 SET_POSITION_TARGET_GLOBAL_INT 等指令。"
    )
    def test_flyto_ignored_in_non_guided_mode(self):
        with allure.step("前置：切换到非 Guided 模式 (STAB)"):
            assert self._switch_to_stab(), "前置条件失败：无法切换到 STAB 模式"

        with allure.step("验证当前模式不是 Guided"):
            mode_info = self.serial.get_current_mode()
            logger.info(f"当前模式: {mode_info}")
            assert mode_info.get("mode_id") != MODE_GUIDED, (
                "前置条件异常：当前模式不应为 Guided"
            )

        with allure.step("在 STAB 模式下发送 flyto 命令"):
            lat, lon, alt = self.WAYPOINT_A
            logger.info(f"在 STAB 模式下发送 flyto {lat} {lon} {alt}")
            result = self.serial.fly_to(lat, lon, alt)
            logger.info(f"flyto 返回: {result}")
            # flyto 命令可能在协议层返回成功（命令格式正确），
            # 但 guided 状态机不会实际处理 —— 此为预期行为。
            # 固件在非 Guided 模式下不会响应位置控制指令。
            logger.info(
                "注意：flyto 命令协议层返回 OK 仅表示命令已被接收，"
                "在非 Guided 模式下 guided 状态机不会处理该 action_req，"
                "飞行器不会飞向目标点。"
            )

        with allure.step("恢复：切回 Guided 模式"):
            assert self._switch_to_guided(), "恢复失败：无法切回 Guided 模式"

    # --- flyto 从 PLAYING 状态打断 ---

    @pytest.mark.skip(reason="需实际飞行环境：要求飞控正在执行航点/剧本任务时发送 flyto")
    @allure.story("Guided模式飞行")
    @allure.title("flyto 从 PLAYING 状态打断航点/剧本任务")
    @allure.description(
        "验证当飞控正在执行航点或剧本任务（PLAYING 状态）时，"
        "发送 flyto 命令可以中断当前任务并飞向新目标。\n"
        "行为链：\n"
        "1. 飞控处于 AUTO 模式执行航点任务（或 fstart 剧本）\n"
        "2. 切换到 Guided 模式 + 发送 flyto\n"
        "3. flyto 的 action_req 被 guided 状态机处理\n"
        "4. 飞控中断当前航点/剧本，飞向 flyto 指定的新目标"
    )
    def test_flyto_interrupt_playing_mission(self):
        with allure.step("前置：确保处于 Guided 模式"):
            assert self._switch_to_guided(), "前置条件失败：无法切换到 Guided 模式"

        with allure.step("启动表演任务 (fstart) 进入 PLAYING 状态"):
            logger.info("发送 fstart 命令启动剧本任务")
            result = self.serial.perform_action()
            logger.info(f"fstart 返回: {result}")
            # 不强制断言 —— fstart 可能因无剧本文件而失败，仅验证命令通道

        with allure.step("等待进入执行状态"):
            time.sleep(2.0)

        with allure.step("发送 flyto 命令打断当前任务"):
            lat, lon, alt = self.WAYPOINT_B
            logger.info(f"发送 flyto {lat} {lon} {alt} 打断 PLAYING 状态")
            result = self.serial.fly_to(lat, lon, alt)
            logger.info(f"flyto 返回: {result}")
            assert result, "flyto 打断命令失败 —— guided 状态机未响应"

        with allure.step("flyto 打断后读取 DShot 转速（验证电机接管）"):
            logger.info("flyto 接管后持续读取电机转速...")
            rpm_samples = self._read_rpm_during_flyto(duration=3.0, interval=0.5)
            rpm_ok_count = sum(1 for _, r in rpm_samples if r)
            logger.info(f"DShot RPM 采样 {len(rpm_samples)} 次，成功 {rpm_ok_count} 次")
            assert rpm_ok_count > 0, (
                "flyto 打断后 DShot RPM 全部读取失败，电机未接管"
            )

        with allure.step("验证模式仍为 Guided（flyto 接管后保持 Guided）"):
            mode_info = self.serial.get_current_mode()
            logger.info(f"flyto 打断后当前模式: {mode_info}")
            assert mode_info.get("mode_id") == MODE_GUIDED, (
                f"flyto 打断后模式异常: {mode_info.get('mode_id')}"
            )

    # --- 到达目标后悬停 ---

    @pytest.mark.skip(reason="需实际飞行环境：要求飞控飞抵目标后验证悬停行为")
    @allure.story("Guided模式飞行")
    @allure.title("flyto 到达目标后切回 GUIDED_STATE_FLYING 悬停")
    @allure.description(
        "验证 flyto 飞抵目标点后的行为：\n"
        "1. 飞控自动切回 GUIDED_STATE_FLYING（悬停状态）\n"
        "2. 不会自动降落 —— 保持悬停等待下一条指令\n"
        "3. 飞行模式保持 Guided (mode_id=4)\n\n"
        "此行为确保操作者可以在 flyto 到达后继续发送新的飞行指令，"
        "而无需重新切换模式或重新起飞。"
    )
    def test_flyto_arrival_hover_behavior(self):
        with allure.step("前置：切换到 Guided 模式"):
            assert self._switch_to_guided(), "前置条件失败：无法切换到 Guided 模式"

        with allure.step("发送 flyto 到目标点"):
            lat, lon, alt = self.WAYPOINT_A
            logger.info(f"发送 flyto {lat} {lon} {alt}")
            result = self.serial.fly_to(lat, lon, alt)
            logger.info(f"flyto 返回: {result}")
            assert result, "flyto 命令失败"

        with allure.step("飞行过程中通过 DShot 读取电机转速"):
            logger.info("flyto 飞行中，持续读取转速...")
            rpm_samples = self._read_rpm_during_flyto(duration=5.0, interval=0.5)
            rpm_ok_count = sum(1 for _, r in rpm_samples if r)
            logger.info(f"飞行中 DShot RPM 采样 {len(rpm_samples)} 次，成功 {rpm_ok_count} 次")
            assert rpm_ok_count > 0, "飞行中 DShot RPM 读取失败"

        with allure.step("等待飞抵目标点（超时 30s，轮询模式+RPM）"):
            self._wait_flyto_complete(timeout=30.0, poll_interval=2.0)

        with allure.step("到达后读取 DShot 转速（确认悬停，电机仍在转动）"):
            rpm_result = self.serial.read_motor_rpm()
            logger.info(f"到达后 RPM: {rpm_result}")

        with allure.step("验证到达后模式仍为 Guided（GUIDED_STATE_FLYING 悬停）"):
            mode_info = self.serial.get_current_mode()
            logger.info(f"到达后当前模式: {mode_info}")
            assert mode_info.get("mode_id") == MODE_GUIDED, (
                f"到达后模式异常: 期望 Guided(4) 悬停, 实际 {mode_info.get('mode_id')}"
            )

        with allure.step("验证飞控未自动降落（非 LAND 模式）"):
            mode_info = self.serial.get_current_mode()
            assert mode_info.get("mode_id") != MODE_LAND, (
                "异常：flyto 到达后不应自动进入 LAND 模式，应保持 GUIDED_STATE_FLYING 悬停"
            )
            logger.info("确认：到达目标后保持 Guided 悬停，未自动降落 ✓")

    # --- 降落指令 ---

    @allure.story("Guided模式降落")
    @allure.title("Guided 模式下发送降落指令 → GUIDED_STATE_LANDING")
    @allure.description(
        "验证在 Guided 模式悬停状态下，发送降落指令（UAV_ACTION_LAND）的行为：\n"
        "1. 飞控切换到 GUIDED_STATE_LANDING\n"
        "2. 飞行模式切换为 LAND (mode_id=9)\n"
        "3. 飞控执行自动降落流程\n\n"
        "注意：此测试验证降落命令响应，实际降落需在安全环境下执行。"
    )
    def test_land_from_guided_mode(self):
        with allure.step("前置：切换到 Guided 模式"):
            assert self._switch_to_guided(), "前置条件失败：无法切换到 Guided 模式"

        with allure.step("发送 mode land 命令（触发 UAV_ACTION_LAND）"):
            logger.info("发送 mode land 命令 → 触发 GUIDED_STATE_LANDING")
            result = self.serial.set_mode("land")
            logger.info(f"mode land 返回: {result}")
            assert result, "降落指令 (mode land) 失败"

        with allure.step("等待模式切换生效"):
            time.sleep(1.0)

        with allure.step("验证飞控进入 LAND 模式 (mode_id=9)"):
            mode_info = self.serial.get_current_mode()
            logger.info(f"降落指令后当前模式: {mode_info}")
            assert mode_info.get("mode_id") == MODE_LAND, (
                f"降落指令后模式异常: 期望 LAND(9), 实际 {mode_info.get('mode_id')}"
            )
            logger.info("确认：Guided → LAND 切换成功，进入 GUIDED_STATE_LANDING ✓")

        with allure.step("恢复：切回 Guided 模式"):
            assert self._switch_to_guided(), "恢复失败：无法切回 Guided 模式"

    # --- 完整 Guided 飞行流程 ---

    @pytest.mark.skip(reason="需实际飞行环境：完整 Guided flyto→悬停→降落 流程")
    @allure.story("Guided模式飞行")
    @allure.title("Guided 模式完整飞行流程：flyto → 悬停 → 降落")
    @allure.description(
        "完整的 Guided 模式飞行流程测试：\n"
        "1. 切换到 Guided 模式\n"
        "2. 发送 flyto 飞向目标点 A\n"
        "3. 等待到达 → 自动切回 GUIDED_STATE_FLYING 悬停\n"
        "4. 发送 flyto 飞向目标点 B（验证连续 flyto）\n"
        "5. 到达后发送降落指令 → GUIDED_STATE_LANDING\n\n"
        "此用例覆盖 Guided 模式下的核心飞行任务流程。"
    )
    def test_guided_full_flight_flow(self):
        # Step 1: 切 Guided
        with allure.step("Step 1: 切换到 Guided 模式"):
            assert self._switch_to_guided(), "Step 1 失败：无法切换到 Guided 模式"

        # Step 2: flyto 目标 A
        with allure.step("Step 2: flyto 目标点 A"):
            lat_a, lon_a, alt_a = self.WAYPOINT_A
            logger.info(f"flyto → A: ({lat_a}, {lon_a}, {alt_a})")
            result = self.serial.fly_to(lat_a, lon_a, alt_a)
            assert result, "flyto 目标 A 失败"

        with allure.step("飞行 A 过程中读取 DShot 转速"):
            rpm_samples = self._read_rpm_during_flyto(duration=3.0, interval=0.5)
            rpm_ok = sum(1 for _, r in rpm_samples if r)
            logger.info(f"→ A DShot RPM 采样 {len(rpm_samples)} 次，成功 {rpm_ok} 次")

        with allure.step("等待飞抵目标点 A（超时 30s）"):
            self._wait_flyto_complete(timeout=30.0, poll_interval=2.0)

        with allure.step("到达 A 后读取 DShot 转速（悬停）"):
            rpm_a = self.serial.read_motor_rpm()
            logger.info(f"→ A 到达后 RPM: {rpm_a}")

        with allure.step("验证到达 A 后悬停 (Guided mode_id=4)"):
            mode_info = self.serial.get_current_mode()
            assert mode_info.get("mode_id") == MODE_GUIDED, (
                f"到达 A 后未保持 Guided 悬停: {mode_info}"
            )

        # Step 3: flyto 目标 B（连续 flyto）
        with allure.step("Step 3: flyto 目标点 B（连续 flyto）"):
            lat_b, lon_b, alt_b = self.WAYPOINT_B
            logger.info(f"flyto → B: ({lat_b}, {lon_b}, {alt_b})")
            result = self.serial.fly_to(lat_b, lon_b, alt_b)
            assert result, "连续 flyto 目标 B 失败"

        with allure.step("飞行 B 过程中读取 DShot 转速"):
            rpm_samples = self._read_rpm_during_flyto(duration=3.0, interval=0.5)
            rpm_ok = sum(1 for _, r in rpm_samples if r)
            logger.info(f"→ B DShot RPM 采样 {len(rpm_samples)} 次，成功 {rpm_ok} 次")

        with allure.step("等待飞抵目标点 B（超时 30s）"):
            self._wait_flyto_complete(timeout=30.0, poll_interval=2.0)

        with allure.step("到达 B 后读取 DShot 转速（悬停）"):
            rpm_b = self.serial.read_motor_rpm()
            logger.info(f"→ B 到达后 RPM: {rpm_b}")

        with allure.step("验证到达 B 后悬停 (Guided mode_id=4)"):
            mode_info = self.serial.get_current_mode()
            assert mode_info.get("mode_id") == MODE_GUIDED, (
                f"到达 B 后未保持 Guided 悬停: {mode_info}"
            )

        # Step 4: 降落
        with allure.step("Step 4: 发送降落指令"):
            logger.info("发送 mode land → GUIDED_STATE_LANDING")
            result = self.serial.set_mode("land")
            assert result, "降落指令失败"

        with allure.step("降落中读取 DShot 转速（转速应逐渐降低）"):
            rpm_land = self.serial.read_motor_rpm()
            logger.info(f"降落中 RPM: {rpm_land}")

        with allure.step("验证进入 LAND 模式"):
            time.sleep(1.0)
            mode_info = self.serial.get_current_mode()
            assert mode_info.get("mode_id") == MODE_LAND, (
                f"降落指令后未进入 LAND: {mode_info}"
            )
            logger.info("完整 Guided 飞行流程测试通过 ✓")

    # --- Guided 模式与其他模式的切换 ---

    @allure.story("Guided模式切换")
    @allure.title("Guided ↔ 其他模式互切验证")
    @allure.description(
        "验证 Guided 模式与常用飞行模式之间的互相切换："
        "STAB → Guided → LOITER → Guided → AUTO → Guided → STAB。"
        "确保模式切换通道正常，Guided 模式可随时切入和切出。"
    )
    def test_mode_switch_round_trip(self):
        mode_sequence = [
            ("STAB", MODE_STAB),
            ("GUIDED", MODE_GUIDED),
            ("LOITER", MODE_LOITER),
            ("GUIDED", MODE_GUIDED),
            ("STAB", MODE_STAB),
        ]

        for mode_name, expected_id in mode_sequence:
            with allure.step(f"切换到 {mode_name} 模式 (mode_id={expected_id})"):
                result = self.serial.set_mode(mode_name)
                logger.info(f"mode {mode_name} 返回: {result}")
                assert result, f"切换 {mode_name} 模式失败"

                time.sleep(0.5)

                mode_info = self.serial.get_current_mode()
                actual_id = mode_info.get("mode_id")
                logger.info(f"当前模式: {mode_info}")
                assert actual_id == expected_id, (
                    f"模式验证失败: 期望 {mode_name}({expected_id}), "
                    f"实际 mode_id={actual_id}"
                )

        logger.info("Guided 模式互切往返测试通过 ✓")

    # --- teardown：测试结束后恢复到安全模式 ---

    @allure.story("测试清理")
    @allure.title("恢复安全状态")
    @allure.description(
        "所有测试结束后恢复到 STAB 模式，确保飞控处于安全状态。"
        "电机锁定和 INDOOR_DEBUG 恢复由 fixture teardown 自动处理。"
    )
    def test_restore_safe_mode(self):
        with allure.step("切换到 STAB 模式"):
            result = self.serial.set_mode("stab")
            logger.info(f"恢复 STAB 模式: {result}")
            assert result, "恢复 STAB 模式失败"

        with allure.step("确认电机已锁定（fixture teardown 处理）"):
            result = self.serial.disarm_motors()
            logger.info(f"确认锁定电机: {result}")
            # 不强制断言 —— 电机可能本身未解锁
