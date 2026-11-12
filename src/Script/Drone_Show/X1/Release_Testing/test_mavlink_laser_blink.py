# coding: utf-8

"""
X1 激光反复点亮调试测试 — Debug 模式下绿/蓝激光各反复点亮 3 次（视觉联调用）

业务背景：
    X1 机型挂载激光云台负载，视觉联调阶段需要激光反复点亮，供外部相机
    拍照识别激光光斑圆心。本测试通过 MAVLink CONSOLE 消息（msg_id=48）
    打开固件 CLI 终端，进入云台调试模式后，绿/蓝激光各反复点亮 3 次
    （点亮 → 保持 → 关闭），每次点亮保持期间由 USB 相机（ff-camera，
    utils/laser_camera.py）取图做视觉断言：点亮须检出预期颜色光斑并
    记录圆心，熄灭后须无光斑；相机不可用时视觉断言自动跳过。

测试流程：
    [前置] 打开终端 — 初始化 GroundControlStation，等一跳心跳确认链路，
           SR0_CONSOLE 复位后置 20 打开 CLI→CONSOLE 路由（回显 Save/Set OK）；
           固件版本/SN 写入 allure 环境信息；打开相机（可选外设，失败仅告警）
     1. gimbal 1 进入调试模式（CLI）
     2. 绿色激光反复 3 次：点亮（指令断言 + 取图断言检出光斑）→ 保持 →
        关闭（指令断言 + 取图断言光斑消失）→ 熄灭 0.5s
     3. 蓝色激光反复 3 次：同上
     4. gimbal 2 → gimbal 0 恢复默认（Init）模式
        （模式单向切换：Debug 不能直接切 Init，须经 LD Protection 中转）
    [后置] 清理 — 关相机、关激光、恢复 Init 模式、SR0_CONSOLE=0 关路由、
           关闭地面站 UDP 套接字

协议整理（依据 l5_test 需求文档 + 真机实测 172.19.210.29）：
    ┌──────────────────┬──────────────────────────────────────────────┐
    │ 动作              │ 指令格式                                     │
    ├──────────────────┼──────────────────────────────────────────────┤
    │ 终端路由开关 ★    │ PARAM_SET (msg_id=23): SR0_CONSOLE=20 开/0 关│
    │ (2026-09-04 抓包  │ 格式 '<8fHBB128s', crc_extra=75；            │
    │  逆向确认)        │ 置 20 后 CLI 才桥接到 CONSOLE(48)，回        │
    │                  │ "Save/Set 'SR0_CONSOLE' OK"。缺这步无回显！  │
    ├──────────────────┼──────────────────────────────────────────────┤
    │ 云台模式 (CLI)    │ CONSOLE (msg_id=48): `gimbal <mode>`         │
    │ (X1-REQ-GMBL-0001)│ 0=Init 1=Debug 2=LD Protection               │
    │   实测: gimbal 1 ✓│ 无效参数回 "unknow gimbal cmd"               │
    ├──────────────────┼──────────────────────────────────────────────┤
    │ 激光开关          │ COMMAND_LONG command=183                     │
    │ (X1-REQ-LASER-0006│ (MAV_CMD_DO_SET_SERVO)                       │
    │  关闭=RGB 全 0)   │ param7=4(颜色控制) param4=channel（真机确认）│
    │                  │ param1/2/3 = r/g/b (0~255)                   │
    │                  │ OFF=(0,0,0) 绿=(0,5,0) 蓝=(0,0,5)            │
    └──────────────────┴──────────────────────────────────────────────┘

    注意事项：
    - ★ 终端握手是前置条件：固件默认不桥接 CLI 到 CONSOLE(48)，必须先
      PARAM_SET(23) SR0_CONSOLE=20。2026-09-04 之前测试跳过此步导致所有
      CLI 命令无回显，曾长期被误判为"CLI 挂死"（UDP 助手抓包逆向确认）
    - 激光功率限幅：标准为 10% 功率档（255×10% 取整 = 25，X1-REQ-LASER-0008
      单机控制限幅 / X1-REQ-GMBL-0005 上锁限幅）。当前取 25（换 ff-Camera
      后待校准定稿）；限幅是安全起见，避免强光伤眼
    - X1 激光负载只有绿/蓝两色、无红光（报文 param1=r 恒 0）
    - 云台模式单向切换：Init → Debug → LD Protection → Init，Debug 不能
      直接切回 Init，必须先切 LD Protection 中转
    - 负载长时间闲置（数小时级）后 CLI 可能真无响应（对云台负载单独
      重新上电可恢复）；打开终端的判据即 Set/Save OK 回显，未收到报
      打开失败
    - 固件对未知子命令仍回 ACK（如 "unknow gimbal cmd"），断言须同时检查
      NAK / unknow 失败标记，不能只看 ACK

分层：
    收发与云台/激光业务方法及协议常量见 X1/conftest.py 的 _GimbalLaserBase；
    前置/后置 fixture（终端握手 + 相机开关）留在本文件；相机视觉校验为
    本文件模块级辅助函数 _verify_spot_on/_verify_spot_off（与测试类分离，
    后续出现第二个视觉用例时再上移共享位置）。功率限幅按相机检测需求
    覆盖为 5、相机 index 为类属性；其余用例参数（反复次数/保持时长/
    颜色取值）均在用例现场，脚本扩充时各用例自持参数。
"""

import time

import pytest
import allure

from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
from src.Script.Drone_Show.X1.conftest import (
    GIMBAL_MODE_DEBUG, LASER_BROADCAST_CHANNEL, _GimbalLaserBase)
from utils.laser_camera import LaserSpotCamera, MIN_SPOT_AREA_PX, encode_jpg
from utils.logger import log_manager


# ============================================================================
# 相机视觉校验辅助（与测试类分离；camera 为 None 时自动跳过）
# ============================================================================

def _verify_spot_on(camera, color_key, label, round_idx):
    """点亮取图断言检出预期颜色光斑，标注画面（JPG）与质心/面积进报告

    Args:
        camera: LaserSpotCamera 实例（None 时跳过并记录）
        color_key: 检测模块颜色键（"green"/"blue"）
        label: 报告用中文颜色名（如 "绿"）
        round_idx: 当前轮次（报告命名用）
    """
    if camera is None:
        log_manager.log_and_attach("相机不可用，跳过圆心识别",
                                   f"圆心识别 {label} #{round_idx}")
        return
    time.sleep(0.3)     # 点亮后静置：光斑稳定 + 相机曝光适应
    frame = camera.capture()
    result = camera.detect_spot(frame, color_key)

    allure.attach(encode_jpg(camera.annotate(frame, result)),
                  name=f"点亮画面 {label} #{round_idx}",
                  attachment_type=allure.attachment_type.JPG)
    detail = (f"质心=({result.centroid[0]:.1f}, {result.centroid[1]:.1f})"
              if result.centroid else "未检出")
    log_manager.log_and_attach(
        f"{label}激光光斑: found={result.found}, {detail}, "
        f"面积={result.area_px:.0f}px², 命中像素={result.pixel_count}",
        f"圆心识别 {label} #{round_idx}")
    assert result.found, (
        f"{label}激光点亮后未检出光斑（最大轮廓面积 {result.area_px:.0f}px² < "
        f"{MIN_SPOT_AREA_PX}px²，命中像素 {result.pixel_count}）。"
        f"请检查相机是否对准墙面光斑，或用 debug_camera_laser.py 校准阈值")


def _verify_spot_off(camera, label, round_idx):
    """熄灭取图断言画面中无光斑（camera 为 None 时跳过）

    绿/蓝两色都检（X1 仅此两色激光），任一检出即判失败（余辉/残留或误检）。
    """
    if camera is None:
        return
    time.sleep(0.2)     # 熄灭后静置
    frame = camera.capture()
    results = {key: camera.detect_spot(frame, key) for key in ("green", "blue")}
    found = [key for key, r in results.items() if r.found]

    allure.attach(encode_jpg(frame),
                  name=f"熄灭画面 {label} #{round_idx}",
                  attachment_type=allure.attachment_type.JPG)
    log_manager.log_and_attach(
        "熄灭后光斑检测: " + ", ".join(
            f"{key}(found={r.found}, 面积={r.area_px:.0f}px²)"
            for key, r in results.items()),
        f"熄灭验证 {label} #{round_idx}")
    assert not found, f"激光已关闭但仍检出光斑: {found}（余辉/残留或误检）"


# ============================================================================
# 测试类
# ============================================================================

@allure.feature("激光反复点亮调试")
@allure.severity(allure.severity_level.NORMAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "LASER_BLINK", "VISION_DEBUG")
@pytest.mark.functional
class TestMavlinkLaserBlink(_GimbalLaserBase):
    """X1 激光反复点亮调试测试 — Debug 模式下绿/蓝激光各反复点亮 3 次"""

    # 覆盖基类护眼限幅 3：相机检测需要更高亮度；当前取标准 10% 功率档 25
    # （X1-REQ-LASER-0008），ff-Camera 实测口径待校准定稿
    LASER_POWER_LIMIT = 25

    # 按设备名打开 FF-Camera：DirectShow 索引顺序会随插拔/驱动漂移
    # （09-15 排查时 FF 在 index 1、09-17 漂到 index 0——硬编码 index
    # 不可靠）；相机为可选外设，打开失败时视觉断言整体跳过
    CAMERA_NAME = "FF-Camera"

    @pytest.fixture(autouse=True)
    def setup_teardown(self, drone_ip, drone_port, mavlink_version):
        """测试前置/后置（终端握手 + 相机；后置兜底：关激光、恢复 Init、
        关路由、关相机、关地面站）"""
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

        # 相机为可选外设：打开失败只告警并跳过视觉断言，不阻塞 MAVLink 主流程
        self.camera = None
        try:
            # ff-camera 1920x1080 实测可用（设不上会自动回退）；手动曝光 -9
            # （DirectShow 负值标度）——自动曝光会把背景洗白、光斑核心死白
            # 带星芒丢失颜色信息，实测 -9 时背景回落、光斑呈紧凑绿点可稳定
            # 检出（2026-09-04 debug_camera_laser.py 调参确认）
            self.camera = LaserSpotCamera(
                camera_name=self.CAMERA_NAME,
                width=1920, height=1080, exposure=-9).open()
            log_manager.log_and_attach(
                f"相机已打开 {self.CAMERA_NAME}"
                f"（index={self.camera.camera_index}）", "初始化信息")
        except Exception as e:
            log_manager.logger.warning(
                f"相机 {self.CAMERA_NAME} 打开失败，视觉断言跳过: {e}")
        yield
        with allure.step("清理测试资源（关激光、恢复 Init 模式、关路由、关相机与终端）"):
            try:
                self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)   # 兜底关激光
                self._gimbal_restore_init()
            except Exception as e:
                log_manager.logger.warning(f"兜底清理命令发送失败: {e}")
            finally:
                try:
                    self._set_console_route(0.0)   # SR0_CONSOLE=0 关路由
                except Exception as e:
                    log_manager.logger.warning(f"关闭 CONSOLE 路由失败: {e}")
                if self.camera is not None:
                    self.camera.close()
                    log_manager.log_and_attach("相机已关闭", "清理信息")
                self.gcs.close()
                log_manager.log_and_attach("地面站已关闭", "清理信息")

    # ==================================================================
    # 测试流程
    # ==================================================================

    @allure.story("反复点亮调试")
    @allure.title("X1 绿/蓝激光各反复点亮 3 次（视觉联调）")
    def test_laser_repeated_blink(self):
        """激光反复点亮调试全流程（步骤 1~4，终端开关由 fixture 管理）"""
        # 用例参数：反复次数 / 每次保持时长（预留外部拍照识别）
        repeat, hold = 3, 2.0

        # ── 步骤 1：gimbal 1 进入调试模式 ─────────────────────────────
        with allure.step("1. gimbal 1 进入调试模式"):
            resp = self._gimbal_mode(GIMBAL_MODE_DEBUG)
            assert 'set gimbal to debug mode' in resp.lower(), \
                f"未进入调试模式: {resp[:200]}"

        # ── 步骤 2：绿色激光反复 3 次 ─────────────────────────────────
        # (g, b) = (5, 0)：调试点亮值 5（相机检测下限，依据见 LASER_POWER_LIMIT）
        with allure.step(f"2. 绿色激光反复点亮 {repeat} 次（每次保持 "
                         f"{hold}s，预留拍照识别）"):
            for round_idx in range(1, repeat + 1):
                with allure.step(f"绿色激光 第 {round_idx}/{repeat} 次"):
                    ack = self._laser_color(5, 0, channel=LASER_BROADCAST_CHANNEL)
                    assert ack.fields.get('result', -1) == 0, \
                        f"绿色激光第 {round_idx} 次点亮指令被拒绝"
                    log_manager.log_and_attach(
                        f"绿色激光已点亮，保持 {hold}s", f"点亮 绿 #{round_idx}")
                    time.sleep(hold)
                    _verify_spot_on(self.camera, "green", "绿", round_idx)
                    ack = self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)
                    assert ack.fields.get('result', -1) == 0, \
                        f"绿色激光第 {round_idx} 次熄灭指令被拒绝"
                    log_manager.log_and_attach(
                        "绿色激光已关闭", f"关闭 绿 #{round_idx}")
                    _verify_spot_off(self.camera, "绿", round_idx)
                    time.sleep(0.5)   # 熄灭间隔，避免连续高频点亮

        # ── 步骤 3：蓝色激光反复 3 次 ─────────────────────────────────
        # 蓝色同亮度：(g, b) = (0, 5)
        with allure.step(f"3. 蓝色激光反复点亮 {repeat} 次（每次保持 "
                         f"{hold}s，预留拍照识别）"):
            for round_idx in range(1, repeat + 1):
                with allure.step(f"蓝色激光 第 {round_idx}/{repeat} 次"):
                    ack = self._laser_color(0, 5, channel=LASER_BROADCAST_CHANNEL)
                    assert ack.fields.get('result', -1) == 0, \
                        f"蓝色激光第 {round_idx} 次点亮指令被拒绝"
                    log_manager.log_and_attach(
                        f"蓝色激光已点亮，保持 {hold}s", f"点亮 蓝 #{round_idx}")
                    time.sleep(hold)
                    _verify_spot_on(self.camera, "blue", "蓝", round_idx)
                    ack = self._laser_color(0, 0, channel=LASER_BROADCAST_CHANNEL)
                    assert ack.fields.get('result', -1) == 0, \
                        f"蓝色激光第 {round_idx} 次熄灭指令被拒绝"
                    log_manager.log_and_attach(
                        "蓝色激光已关闭", f"关闭 蓝 #{round_idx}")
                    _verify_spot_off(self.camera, "蓝", round_idx)
                    time.sleep(0.5)   # 熄灭间隔，避免连续高频点亮

        # ── 步骤 4：gimbal 2 → gimbal 0 恢复默认（Init）模式 ─────────
        with allure.step("4. gimbal 2 → gimbal 0 恢复默认（Init）模式"):
            self._gimbal_restore_init()
