# coding: utf-8

"""
X1 激光云台测试 — ① 激光校准（单独用例校验校准命令）
                ② 手动复刻校准过程：云台调试模式 + X/Y 轴角度扫描 + 绿/蓝激光点亮
                ③ 极限角步进轮转：绿激光常亮 + 4 个 (x,y) 极限角按 -60~60° 步进轮转

业务背景：
    X1 机型挂载激光云台负载（laser payload），表演前需要对激光模组进行标定，
    并通过云台调试模式验证 X/Y 两轴的角度可达性与激光输出。本测试通过
    MAVLink CONSOLE 消息（msg_id=48）打开固件 CLI 终端，先发送激光标定命令，
    再进入云台调试模式，对 X 轴、Y 轴分别做 -60°~+60° 步进 10° 的定点扫描
    （含两端共 13 个点），最后逐个点亮绿色/蓝色激光各 1 秒，恢复云台默认
    模式并关闭终端。

测试流程（与测试步骤一一对应；终端开关由 fixture 前置/后置管理，不占步骤编号）：
用例一（激光校准 — 单独用例校验校准命令本身）：
    [前置] 打开终端 — 初始化 GroundControlStation，SR0_CONSOLE=20 打开
           CLI→CONSOLE 路由（关键握手），以 "Set OK" 回显确认通道打通
     1. 发送激光校准命令 — command=40040 (param1=7, param2=1)，
        ACK result=0 后等待整定 60s
    [后置] 清理 — fixture 统一兜底（关激光、恢复 Init、关路由、关地面站）

用例二（手动复刻校准过程并点亮激光 — 按文件内顺序在用例一之后执行）：
    [前置] 打开终端 — 同上
     1. gimbal 1 进入调试模式（CLI）
     2. 云台归零 — Lock 模式角度 (0°, 0°)
     3. X 轴扫描 — -60°~+60° 步进 10°，共 13 个点（Y 保持 0°）
     4. Y 轴扫描 — -60°~+60° 步进 10°，共 13 个点（X 保持 0°）
     5. 云台归零 → 等待 2s
     6. 绿色激光 ON → 持续 1s → OFF → 熄灭 0.5s
     7. 蓝色激光 ON → 持续 1s → OFF
     8. gimbal 2 → gimbal 0 恢复默认（Init）模式
        （模式单向切换：Debug 不能直接切 Init，须经 LD Protection 中转）
    [后置] 清理 — 关激光、恢复 Init 模式、SR0_CONSOLE=0 关路由、
           关闭地面站 UDP 套接字

用例三（极限角步进轮转；终端开关同样由 fixture 管理，不占步骤编号）：
    [前置] 打开终端 — 同上
     1. gimbal 1 进入调试模式（CLI）
     2. 点亮绿色激光 — 亮度 2（RGB=(0,2,0)），全程常亮至步骤 4
     3. 按步进值轮转 4 个极限角（每组 (x, y)）：
        每轮先归零 (0,0)，再逐步走到 (60,-60) → (-60,60) → (60,60) → (-60,-60)；
        步进值 1/5/10/20/30/60/120°，每种重复 1 轮
        （每轮移动次数 = 420/步进：归零→第 1 角 60° 行程 + 3 段 120° 行程；
          全程约 592 次移动，其中步进 1° 一轮 420 次；
          步进 1° 每步间隔 0.1s、其余 0.5s，全程约 4 分钟）
     4. 关闭激光
     5. 云台归零 — Lock(0°, 0°) → 等待 2s（Init 模式不自动回中，须显式归零）
     6. gimbal 2 → gimbal 0 恢复默认（Init）模式
    [后置] 清理 — 同上

协议整理（依据 l5_test 需求文档 + 真机实测 172.19.210.29）：
    ┌────────────────────────────┬─────────────────────────────────────────────┐
    │ 动作                        │ 指令格式                                    │
    ├────────────────────────────┼─────────────────────────────────────────────┤
    │ 终端路由开关 ★              │ PARAM_SET (msg_id=23): SR0_CONSOLE=20 开/0 关│
    │ (2026-09-04 抓包逆向确认)   │ 置 20 后 CLI 才桥接到 CONSOLE(48)，回        │
    │                            │ "Set 'SR0_CONSOLE' OK"。缺这步 CLI 无回显！ │
    ├────────────────────────────┼─────────────────────────────────────────────┤
    │ 激光校准                    │ COMMAND_LONG command=40040                  │
    │ (X1-REQ-LASER-0005)        │ param1=7(激光), param2=1(执行校准)           │
    │   实测: ACK result=0 ✓      │                                             │
    ├────────────────────────────┼─────────────────────────────────────────────┤
    │ 云台模式 (CLI)              │ CONSOLE (msg_id=48): `gimbal <mode>`        │
    │ (X1-REQ-GMBL-0001)         │ 0=Init 1=Debug 2=LD Protection              │
    │   实测: gimbal 1 ✓          │ 无效参数回 "unknow gimbal cmd"              │
    ├────────────────────────────┼─────────────────────────────────────────────┤
    │ 云台角度控制 (Lock)          │ COMMAND_LONG command=183                    │
    │ (X1-REQ-GMBL-0003)         │ (MAV_CMD_DO_SET_SERVO)                      │
    │ (X1-REQ-LASER-0007 角度形式) │ param1=X轴 param2=Y轴角度 [-180,180]        │
    │                            │ param4=通道(1~4) param7=11(LOCK)            │
    ├────────────────────────────┼─────────────────────────────────────────────┤
    │ 激光开关                    │ COMMAND_LONG command=183                    │
    │ (X1-REQ-LASER-0006 关闭     │ param7=4 param4=channel（真机确认）          │
    │  =RGB 全 0)                 │ param1/2/3 = r/g/b (0~255)                  │
    │                            │ OFF=(0,0,0) 绿=(0,3,0) 蓝=(0,0,3)           │
    ├────────────────────────────┼─────────────────────────────────────────────┤
    │ 激光槽位查询                 │ COMMAND_LONG command=183                    │
    │ (X1-REQ-LASER-0003)        │ param1=1 param7=9 → LASER_CHANNEL_STATE     │
    │                            │ (msg_id=60)，确认激光实际安装通道            │
    └────────────────────────────┴─────────────────────────────────────────────┘

    注意事项：
    - ★ 终端握手是前置条件：固件默认不桥接 CLI 到 CONSOLE(48)，必须先
      PARAM_SET(23) SR0_CONSOLE=20。2026-09-04 之前测试跳过此步导致所有
      CLI 命令无回显，曾长期被误判为"CLI 挂死"（UDP 助手抓包逆向确认）
    - 激光功率限幅：标准为 10% 功率档（255×10% 取整 = 25，X1-REQ-LASER-0008
      单机控制限幅 / X1-REQ-GMBL-0005 上锁限幅）。实测调试取 3 即可，
      限制功率是安全起见，避免强光伤眼
    - X1 激光负载只有绿/蓝两色、无红光（报文 param1=r 恒 0）；
      云台另有向量形式控制（param7=10，见 command_183_functions.json）
    - 云台模式单向切换：Init → Debug → LD Protection → Init，Debug 不能
      直接切回 Init，必须先切 LD Protection 中转
    - 云台机械限位 ±50°：Lock 角度指令可给到 ±180°，但 >±50° 时云台实际
      饱和于 50° 限位（GMBL-0003 AC-008）；扫描至 ±60° 属超限点，
      按 13 点扫描属预期行为
    - Init 模式不自动回中（2026-09-14 真机实测：恢复 Init 后云台停在
      最后角度）——流程结束前须显式发 Lock(0°, 0°) 归零
    - 固件对未知子命令仍回 ACK（如 "unknow gimbal cmd"），断言须同时检查
      NAK / unknow 失败标记，不能只看 ACK

分层：
    收发与云台/激光业务方法（_gimbal_mode / _gimbal_restore_init /
    _gimbal_lock_angle / _gimbal_vector / _laser_color）及协议常量见
    X1/conftest.py 的 _GimbalLaserBase；前置/后置 fixture 留在本文件
    （不同用例的清理策略可能有差别）。本文件负责标定扫描的流程编排。
"""

import time

import pytest
import allure

from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
from src.Script.Drone_Show.X1.conftest import (
    GIMBAL_CHANNEL, GIMBAL_MODE_DEBUG, LASER_BROADCAST_CHANNEL, _GimbalLaserBase)
from utils.logger import log_manager


# ============================================================================
# 测试类
# ============================================================================

@allure.feature("激光云台标定扫描")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "LASER_GIMBAL", "SCAN_TEST")
@pytest.mark.functional
class TestMavlinkLaserCalibrationScan(_GimbalLaserBase):
    """X1 激光云台测试 — ① 激光校准命令单独校验；② 手动复刻校准过程
    （调试模式 + X/Y 扫描）并点亮绿/蓝激光；③ 绿激光常亮 + 4 极限角
    步进轮转（1~120° 步进，约 592 次移动）"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, drone_ip, drone_port, mavlink_version):
        """测试前置/后置（终端握手；后置兜底：关激光、恢复 Init、关路由、关地面站）"""
        self.drone_ip = drone_ip
        self.drone_port = drone_port
        self.mavlink_version = mavlink_version

        try:
            with allure.step("打开终端（初始化地面站，打通 CONSOLE 通道）"):
                self.gcs = GroundControlStation(drone_ip=drone_ip, drone_port=drone_port)
                log_manager.log_and_attach(
                    f"地面站初始化完成，本地地址: {self.gcs.local_ip}:{self.gcs.local_port}",
                    "初始化信息")
                self._clear_recv_buffer()
                # 等一跳心跳（实测约 5s 一条，收到即返回）：登记 discovered
                # 集合消除 send() 的"未被发现"误告警，离线时留日志线索
                self._wait_drone_online()
                # 关键握手：SR0_CONSOLE 打开 CLI→CONSOLE 路由（恒定先复位
                # 再置 20，回显 Save/Set OK 必然出现，详见 _set_console_route）
                self._set_console_route(20.0)
                # 固件版本/SN 写入 allure 环境信息（对齐串口 fixture 归档口径）
                self._record_device_env()
        except Exception:
            # setup 失败时 pytest 不跑本 fixture 的 teardown，须自行关闭
            # 套接字，避免残留占住 14550 影响后续用例
            self.gcs.close()
            raise
        yield
        with allure.step("清理测试资源（关激光、恢复 Init 模式、关路由、关闭终端）"):
            try:
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)   # 兜底关激光（广播通道）
                # 兜底归零：Init 不自动回中，防止用例中途失败时云台停在
                # 失败角度（未进 Debug 时此命令为无害 no-op）
                self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL)
                self._gimbal_restore_init()
            except Exception as e:
                log_manager.logger.warning(f"兜底清理命令发送失败: {e}")
            finally:
                try:
                    self._set_console_route(0.0)   # SR0_CONSOLE=0 关路由
                except Exception as e:
                    log_manager.logger.warning(f"关闭 CONSOLE 路由失败: {e}")
                self.gcs.close()
                log_manager.log_and_attach("地面站已关闭", "清理信息")

    # ==================================================================
    # 用例一：激光校准（单独校验校准命令）
    # ==================================================================

    @allure.story("激光校准")
    @allure.title("X1 激光校准命令单独校验")
    def test_laser_calibration(self):
        """验证激光校准命令（X1-REQ-LASER-0005）：ACK result=0 后整定 60s"""
        with allure.step("发送激光校准命令 (command=40040, param1=7, param2=1)"):
            # X1-REQ-LASER-0005：param1=7(激光)、param2=1(执行校准)
            ack = self._send_command_long(40040, param1=7, param2=1, timeout=10.0)
        with allure.step("验证校准命令回执 result=0"):
            # _send_command_long 内部已断言过；此处显式重申判据，报告可见
            result = ack.fields.get('result', -1)
            assert result == 0, f"激光校准命令执行失败, ACK result={result}"
            log_manager.log_and_attach("ACK result=0，校准已启动", "验证通过")
        with allure.step("等待校准整定 60s"):
            log_manager.log_and_attach("标定已启动，等待 60s", "激光校准")
            time.sleep(60.0)

    # ==================================================================
    # 用例二：手动复刻校准过程并点亮激光
    # ==================================================================

    @allure.story("手动复刻校准扫描")
    @allure.title("X1 手动复刻校准过程：X/Y 轴扫描 + 绿/蓝激光点亮")
    def test_gimbal_scan_and_laser_light_flow(self):
        """手动复刻校准过程（调试模式 + X/Y 定点扫描）并点亮绿/蓝激光
        （步骤 1~8，终端开关由 fixture 管理；按文件内顺序在激光校准后执行）"""
        # ── 步骤 1：gimbal 1 进入调试模式 ─────────────────────────────
        with allure.step("1. gimbal 1 进入调试模式"):
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入调试模式: {resp[:200]}"

        # ── 步骤 2：云台归零 Lock(0°, 0°) ────────────────────────────
        with allure.step("2. 云台归零 Lock(0°, 0°)"):
            ack = self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL)
            assert ack.fields.get('result', -1) == 0, "云台归零指令被拒绝"

        # ── 步骤 3：X 轴扫描（Y 保持 0°）─────────────────────────────
        # 扫描点位 -60~+60 步进 10°，含两端共 13 点；云台机械限位 ±50°，
        # 超出部分实际饱和于 50°（GMBL-0003 AC-008），超限点属预期行为
        with allure.step(
                "3. X 轴扫描 -60°~+60° 步进 10° "
                "（13 个点, >±50° 饱和于机械限位）"):
            for angle in range(-60, 61, 10):
                with allure.step(f"X={angle}°, Y=0°"):
                    ack = self._gimbal_lock_angle(angle, 0, channel=GIMBAL_CHANNEL)
                    assert ack.fields.get('result', -1) == 0, \
                        f"X={angle}° 点位指令被拒绝"

        # ── 步骤 4：Y 轴扫描（X 保持 0°）─────────────────────────────
        # 同步骤 3 的点位与限位说明
        with allure.step(
                "4. Y 轴扫描 -60°~+60° 步进 10° "
                "（13 个点, >±50° 饱和于机械限位）"):
            for angle in range(-60, 61, 10):
                with allure.step(f"X=0°, Y={angle}°"):
                    ack = self._gimbal_lock_angle(0, angle, channel=GIMBAL_CHANNEL)
                    assert ack.fields.get('result', -1) == 0, \
                        f"Y={angle}° 点位指令被拒绝"

        # ── 步骤 5：云台归零 → 等待 2s ───────────────────────────────
        with allure.step("5. 云台归零 Lock(0°, 0°) → 等待 2s"):
            ack = self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=2.0)
            assert ack.fields.get('result', -1) == 0, "云台归零指令被拒绝"

        # ── 步骤 6：绿色激光 ON → 持续 1s → OFF ─────────────────────
        with allure.step("6. 绿色激光 ON → 持续 1s → OFF"):
            ack = self._laser_color(3, 0, channel=LASER_BROADCAST_CHANNEL)   # 绿色
            assert ack.fields.get('result', -1) == 0, "绿色激光点亮指令被拒绝"
            time.sleep(1.0)               # 持续点亮 1s
            ack = self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)   # 熄灭（g/b 全 0）
            assert ack.fields.get('result', -1) == 0, "绿色激光熄灭指令被拒绝"
            time.sleep(0.5)               # 熄灭间隔，再切蓝色激光

        # ── 步骤 7：蓝色激光 ON → 持续 1s → OFF ─────────────────────
        with allure.step("7. 蓝色激光 ON → 持续 1s → OFF"):
            ack = self._laser_color(0, 3, channel=LASER_BROADCAST_CHANNEL)   # 蓝色
            assert ack.fields.get('result', -1) == 0, "蓝色激光点亮指令被拒绝"
            time.sleep(1.0)               # 持续点亮 1s
            ack = self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)   # 熄灭（g/b 全 0）
            assert ack.fields.get('result', -1) == 0, "蓝色激光熄灭指令被拒绝"

        # ── 步骤 8：gimbal 2 → gimbal 0 恢复默认（Init）模式 ─────────
        with allure.step("8. gimbal 2 → gimbal 0 恢复默认（Init）模式"):
            self._gimbal_restore_init()

    # ==================================================================
    # 用例三：极限角步进轮转（绿激光常亮）
    # ==================================================================

    @allure.story("极限角步进轮转")
    @allure.title("X1 绿激光常亮 + 云台 4 极限角步进轮转测试")
    def test_gimbal_laser_corner_step_sweep_flow(self):
        """绿激光常亮 + 4 极限角步进轮转（步骤 1~5，终端开关由 fixture 管理）"""
        def sweep_path(start, end, step):
            """生成 start→end 的步进插值路径点列表（不含起点，含精确终点）

            x/y 同步插值：n = ceil(最大单轴行程 / step)，第 k 步坐标 =
            起点 + Δ*k/n，整数运算无累积误差；步进值不整除行程时（如 120°
            步进走 60° 行程）终点也能精确落位。
            """
            dx, dy = end[0] - start[0], end[1] - start[1]
            n = -(-max(abs(dx), abs(dy)) // step)     # ceil 除法
            return [(start[0] + dx * k // n, start[1] + dy * k // n)
                    for k in range(1, n + 1)]

        # 4 个极限角 (x, y)，按需求原文顺序轮转；每轮移动次数 = 420/步进
        # （归零→第 1 角 60° 行程 + 3 段对角 120° 行程）
        corners = ((60, -60), (-60, 60), (60, 60), (-60, -60))
        # 每轮路径：归零 (0,0) → 第 1 角，再按序过渡到第 2/3/4 角
        legs = [((0, 0), corners[0])] + list(zip(corners, corners[1:]))

        # ── 步骤 1：gimbal 1 进入调试模式 ────────────────────────────
        with allure.step("1. gimbal 1 进入调试模式"):
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入调试模式: {resp[:200]}"

        # ── 步骤 2：点亮绿色激光（全程常亮）─────────────────────────
        with allure.step("2. 点亮绿色激光（常亮至步骤 4）"):
            ack = self._laser_color(2, 0, channel=LASER_BROADCAST_CHANNEL)
            assert ack.fields.get('result', -1) == 0, "绿色激光点亮指令被拒绝"   # 亮度 2（需求"度=2"，限幅 3 以内）

        # ── 步骤 3：按步进值轮转 4 个极限角度 ────────────────────────
        with allure.step(
                f"3. 轮转 4 个极限角 {corners}，"
                f"步进 1/5/10/20/30/60/120° 各 1 轮"
                f"（步进 1° 间隔 0.1s、其余 0.5s，约 592 次移动 / 约 4 分钟）"):
            for step_value in (1, 5, 10, 20, 30, 60, 120):
                # 步进 1° 一轮 420 次移动，间隔单独缩短为 0.1s；其余 0.5s
                interval = 0.1 if step_value == 1 else 0.5
                moves = sum(len(sweep_path(a, b, step_value))
                            for a, b in legs)
                with allure.step(
                        f"步进 {step_value}°：归零 + 4 段过渡，共 {moves} 次移动"
                        f"（每步 {interval}s）"):
                    # 每轮起点归零是全行程跳转，整定固定用默认 1s
                    self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL)
                    for leg_idx, (start, end) in enumerate(legs, 1):
                        path = sweep_path(start, end, step_value)
                        with allure.step(
                                f"段{leg_idx}/{len(legs)}: {start} → {end} "
                                f"({len(path)} 步)"):
                            for x, y in path:
                                self._gimbal_lock_angle(
                                    x, y, channel=GIMBAL_CHANNEL,
                                    settle=interval, quiet=True)
                        log_manager.log_and_attach(
                            f"步进 {step_value}° 段{leg_idx}: {start} → {end} "
                            f"完成 {len(path)} 步", "轮转段摘要")

        # ── 步骤 4：关闭激光 ─────────────────────────────────────────
        with allure.step("4. 关闭激光"):
            ack = self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)
            assert ack.fields.get('result', -1) == 0, "激光熄灭指令被拒绝"

        # ── 步骤 5：云台归零 → 等待 2s ───────────────────────────────
        # Init 模式不自动回中，恢复默认模式前须显式归零（2026-09-14 实测）
        with allure.step("5. 云台归零 Lock(0°, 0°) → 等待 2s"):
            ack = self._gimbal_lock_angle(0, 0, channel=GIMBAL_CHANNEL, settle=2.0)
            assert ack.fields.get('result', -1) == 0, "云台归零指令被拒绝"

        # ── 步骤 6：gimbal 2 → gimbal 0 恢复默认（Init）模式 ─────────
        with allure.step("6. gimbal 2 → gimbal 0 恢复默认（Init）模式"):
            self._gimbal_restore_init()