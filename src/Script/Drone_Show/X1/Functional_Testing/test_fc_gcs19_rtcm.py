# coding: utf-8

"""
GCS-19 RTCM 差分注入（p1×3）— 坏数据健壮性（32/128/240 分档）+ GPS 状态一致性

业务背景：
    按 32/128/240 字节分档发送 DIFFERENTIAL_LOCATION_PACKET（随机坏数据，
    无真实差分源时的健壮性子集）：飞机不崩、心跳/状态流不断，且 GPS
    相关字段（fix_type/satellites/rtk_quality）不被垃圾数据污染。
    真实差分注入与定位质量爬升待有源时补充。

    ⚠️ RTCM(228~230) 是单向注入协议，固件不回 ACK 不回显——报文级
    收发一致性不可行；一致性校验落在**状态级**（注入前后 GPS 字段对比：
    垃圾数据不应引起 fix_type 异常翻转或卫星数骤降）。

    - test_gcs19_rtcm_robust   随机坏数据注入 + 链路存活 + GPS 状态一致性
"""

import os
import time

import pytest
import allure

from src.Protocol.mavlink.parse_mavlink import MAVLink_message
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    FCBasicBase, log_manager)
from src.Script.Drone_Show.X1.Functional_Testing.fc_basic_base import (
    MSG_ID_HEARTBEAT, MSG_ID_RTCM_32, MSG_ID_RTCM_128, MSG_ID_RTCM_240)

# GPS 一致性对比的字段（注入前后不应变坏）
_GPS_FIELDS = ('fix_type', 'satellites_visible', 'rtk_quality', 'eph')


@allure.feature("FC 基础功能 P0/P1")
@allure.severity(allure.severity_level.CRITICAL)
@allure.tag("DMD_TEST_AIRPLANE", "DMD_AIRPLANE", "FC_BASIC")
@pytest.mark.functional
class TestGcs19Rtcm(FCBasicBase):
    """GCS-19 RTCM 差分注入（p1×3）"""

    @allure.story("GCS-19 RTCM 注入")
    @allure.title("GCS-19 RTCM 坏数据健壮性 + GPS 状态一致性（32/128/240 分档）")
    def test_gcs19_rtcm_robust(self):
        """RTCM 坏数据注入健壮性 + GPS 不被污染（GCS-19 p1×3 的注入链路）"""
        with allure.step("注入前 GPS 基线"):
            base = self._get_packed_state()
            assert base is not None, "无法获取 packed_state 基线"
            base_gps = {k: base.fields.get(k) for k in _GPS_FIELDS}
            log_manager.log_and_attach(
                '\n'.join(f"{k} = {v}" for k, v in base_gps.items()),
                "GPS 基线")

        for msg_id, size, name in [(MSG_ID_RTCM_32, 32, "PACKET_32"),
                                   (MSG_ID_RTCM_128, 128, "PACKET_128"),
                                   (MSG_ID_RTCM_240, 240, "PACKET_240")]:
            with allure.step(f"注入 3 帧{name}（随机坏数据）"):
                for seq in range(3):
                    payload = list(os.urandom(size))
                    msg = MAVLink_message(
                        msg_id=msg_id, sys_id=1, comp_id=1, seq=0,
                        version=self.mavlink_version,
                        fields={'seq': seq, 'pack_num': 3, 'subseq': 0,
                                'length': size, 'data': payload})
                    self.gcs.send(msg, addr=(self.drone_ip, self.drone_port))
                    time.sleep(0.1)
                log_manager.log_and_attach(
                    f"{name} 已发 3 帧 × {size}B 随机数据", f"RTCM {name}")

        with allure.step("注入后链路存活 + GPS 状态一致性"):
            hb = self.gcs.wait_for_message([MSG_ID_HEARTBEAT], timeout=8.0)
            assert hb is not None, "RTCM 坏数据后心跳丢失——注入导致业务/飞控异常"
            packed = self._get_packed_state()
            assert packed is not None, "RTCM 坏数据后 packed_state 不回传"

            after_gps = {k: packed.fields.get(k) for k in _GPS_FIELDS}
            log_manager.log_and_attach(
                '\n'.join(f"{k}: {base_gps[k]} → {after_gps[k]}"
                          + ("  ← 变化" if base_gps[k] != after_gps[k] else "")
                          for k in _GPS_FIELDS),
                "GPS 前后对比")

            # fix_type 不应升格（垃圾数据不会提升定位质量）
            # 台架上基线通常 0（无定位），升格到 >3 意味着被误解析
            assert (after_gps['fix_type'] or 0) <= max(base_gps['fix_type'] or 0, 3), (
                f"fix_type 从 {base_gps['fix_type']} 异常升到 "
                f"{after_gps['fix_type']}——垃圾 RTCM 疑似被误解析（问题单素材）")
            # 卫星数不应骤降（垃圾不会影响接收）
            base_sat = base_gps['satellites_visible'] or 0
            after_sat = after_gps['satellites_visible'] or 0
            assert after_sat >= base_sat - 2, (
                f"卫星数从 {base_sat} 骤降到 {after_sat}——疑似被垃圾数据干扰")
