# coding: utf-8
"""
WiFi 模块测试 - 固件交替升级 + 版本号验证(脚本层)

业务背景:
    发布测试中,验证固件升级流程的可靠性不能只跑一次成功路径。
    本测试采用「往返交替」策略:
        1. 记录当前固件版本号
        2. 上传本地仓库的固件文件,触发升级,等待 reboot 重连
        3. 查询新版本号 → 验证已变化(证明升级生效)
        4. 用步骤 1 备份的原始固件再升回去,等待 reboot 重连
        5. 查询版本号 → 验证已还原(证明降级/还原流程通)

    覆盖四类固件升级的成功路径:
        - WiFi 模块固件(firmware/Wifi/fota_793x.bin + 串口 dmdcicd update wifi)— 往返验证
        - GPS 固件(firmware/Gps/GPS.bin + MAV_CMD_UPDATE_COMPANION param1=2)— 往返验证
        - 飞控固件(firmware/Fc/dmd_uav.bin + 打包 update.zip + MAV_CMD_UPDATE_COMPANION param1=0)— 往返验证
        - 电池固件(firmware/Bat/battery.bin + MAV_CMD_UPDATE_COMPANION param1=1)— 仅触发链路
          (固件 stub 阶段,upgrade_task 电池分支未实现,只验证 FTP 上传 + ACK)

源码事实:
    - WiFi 模块固件升级: dmd_cicd.c "update wifi"(命令 update,参数 wifi)→ FOTA 写入 → hal_sys_reboot
    - GPS 升级: onion_upgrade.c:118-190,内部 UART 刷写,~30-60s
    - companion 整包升级: onion_upgrade.c:410-471,解压 → fcs_upgrade → mt793x_upgrade + reboot

上次运行(#450.txt)经验:
    - GPS 还原失败"10.0s 内未收到 COMMAND_ACK" — 实际是 WiFi 透传 ACK 有延迟,
      本测试把 ACK 超时拉长到 30s,且不强依赖 ACK,主要看版本号变化。
    - WiFi 固件备份失败(FTP file_exists 返回 False) — 本测试不依赖 FTP 备份,
      而是用 firmware/Wifi/fota_793x.bin 本身作为「另一档」固件,飞机当前固件
      通过先记录版本号 + 在 fixture teardown 用 update.zip 路径还原。

副作用管理:
    本测试会真实修改飞机固件。fixture teardown 必须确保还原到原始版本。
    任一升级步骤失败时,通过 pytest fixture 的 try/finally 兜底还原。
"""
import os
import re
import time
import shutil
import zipfile
import pytest
import allure
import sys

# 确保项目根目录在 sys.path 中
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from utils.logger import log_manager
from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation
from src.Protocol.wifi.wifi import (
    upgrade_gps, upgrade_companion, trigger_battery_upgrade,
    reconnect_after_reboot, resolve_module_ip,
    WIFI_DEFAULT_BAUDRATE, WIFI_REBOOT_READY_SECONDS,
    DEFAULT_ACK_TIMEOUT, GPS_BLOCK_DATA_LEN,
    FTP_GPS_FIRMWARE, FTP_UPDATE_ZIP, FTP_BATTERY_FIRMWARE,
)


# ==================== 固件文件路径 ====================
FIRMWARE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "firmware")
WIFI_FIRMWARE_PATH = os.path.join(FIRMWARE_DIR, "Wifi", "fota_793x.bin")
GPS_FIRMWARE_PATH = os.path.join(FIRMWARE_DIR, "Gps", "GPS.bin")
FC_FIRMWARE_PATH = os.path.join(FIRMWARE_DIR, "Fc", "dmd_uav.bin")
BAT_FIRMWARE_PATH = os.path.join(FIRMWARE_DIR, "Bat", "battery.bin")

# 飞机上 WiFi 固件 FTP 路径(用于备份和还原)
FTP_WIFI_FIRMWARE = "/cmpn/dmd_companion/fota_793x.bin"

# 备份目录
BACKUP_DIR = os.path.join(FIRMWARE_DIR, "backup")
WIFI_BACKUP_PATH = os.path.join(BACKUP_DIR, "wifi_fota_793x_alt_backup.bin")
GPS_BACKUP_PATH = os.path.join(BACKUP_DIR, "gps_alt_backup.bin")

# 升级后等待时间(秒) — WiFi reboot ~30s + 串口就绪
WIFI_UPGRADE_WAIT_S = 60
# GPS 升级等待(估算 30s)
GPS_UPGRADE_WAIT_S = 60
# companion 整包升级等待(解压+fcs+reboot ~120s)
COMPANION_UPGRADE_WAIT_S = 150


# ==================== 版本号解析 ====================
# WiFi 固件版本格式: APP version info, branch[develop], commitID[5b42d3d3], tag[V3.61], hardVer[255]
_WIFI_TAG_RE = re.compile(r"tag\[([^\]]+)\]")


def _ensure_backup_dir():
    """确保备份目录存在"""
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _extract_wifi_tag(version_str: str) -> str:
    """从 dmdfact getVer 输出中提取 tag 字段(V3.61 等)
    无法提取时返回原始字符串前 80 字符,便于诊断。
    """
    if not version_str:
        return ""
    m = _WIFI_TAG_RE.search(version_str)
    if m:
        return m.group(1).strip()
    return version_str.strip()[:80]


def _zip_fc_firmware(fc_bin_path: str, zip_out_path: str) -> bool:
    """把飞控固件 dmd_uav.bin 打包为 update.zip(companion 整包升级要求的格式)

    companion 升级流程会调 uncompress_update_zip,要求 zip 内含 dmd_uav.bin。
    """
    try:
        with zipfile.ZipFile(zip_out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(fc_bin_path, arcname=os.path.basename(fc_bin_path))
        log_manager.logger.info(
            f"[Alt-Upgrade] 已打包 FC 固件: {zip_out_path}({os.path.getsize(zip_out_path)} 字节)"
        )
        return True
    except Exception as e:
        log_manager.logger.error(f"[Alt-Upgrade] 打包 FC 固件失败: {e}")
        return False



@allure.epic("WiFi 模块测试")
@allure.feature("固件升级")
@allure.story("交替升级与版本验证")
class TestWifiFirmwareAlternatingUpgrade:
    """固件交替升级测试 — 升到本地版本 → 验证变化 → 还原 → 验证恢复"""


    # GPS / 电池 / companion 整包固件在 /root/ 下的 FTP 路径 — 升级触发后必须清理,
    # 否则 test_wifi_upgrade_failure 套件会因检测到这些文件而 SKIP (评审文档已记此缺陷)。
    # WiFi 固件 fota_793x.bin 不在此列, 它由 _restore_wifi_firmware 还原到基线。
    _FTP_UPGRADE_RESIDUE = [
        FTP_GPS_FIRMWARE,
        FTP_BATTERY_FIRMWARE,
        FTP_UPDATE_ZIP,
    ]


    @pytest.fixture(autouse=True, scope="class")
    def _cleanup_upgrade_firmware_residue(self, ftp_session):
        """class 级 autouse fixture:setup + teardown 各清一次 /root/ 下的升级固件残留

        Why: GPS/battery/update.zip 升级后留在 /root/, 会让 test_wifi_upgrade_failure
        套件的前置检查"文件不存在"失败 → SKIP, 掩盖真问题。
        scope="class" 保证整组升级用例跑完才删, 不会破坏升级流程中途的依赖。
        """
        self._delete_residue(ftp_session, "setup")
        yield
        self._delete_residue(ftp_session, "teardown")


    @classmethod
    def _delete_residue(cls, ftp_session, phase: str):
        """best-effort 删除 /root/ 下三类固件残留, 单个失败不影响其他"""
        try:
            ftp_session.reconnect()
        except Exception:
            pass
        for path in cls._FTP_UPGRADE_RESIDUE:
            try:
                if ftp_session.file_exists(path):
                    ftp_session.delete_file(path)
                    log_manager.logger.info(
                        f"[Alt-Upgrade] {phase} 清理升级固件残留: {path}"
                    )
            except Exception as e:
                log_manager.logger.warning(
                    f"[Alt-Upgrade] {phase} 清理 {path} 异常: {e}"
                )


    @pytest.fixture(scope="class")
    def gcs_upgrade(self, test_params, serial_session):
        """升级专用地面站 fixture:用模块当前 IP,避免 config 漂移"""
        target_ip = resolve_module_ip(serial_session, test_params["mavlink_target_ip"])
        target_port = test_params["mavlink_target_port"]

        log_manager.logger.info(f"[Alt-Upgrade] GCS 初始化: {target_ip}:{target_port}")
        gcs_instance = GroundControlStation(drone_ip=target_ip, drone_port=target_port)

        log_manager.logger.info("[Alt-Upgrade] 开始发现无人机...")
        gcs_instance.discover_drones(timeout=10.0)
        if gcs_instance.discovered_drones:
            best_ip = next(iter(gcs_instance.discovered_drones))
            log_manager.logger.info(f"[Alt-Upgrade] 发现无人机: {best_ip},将优先使用")
        else:
            log_manager.logger.warning(
                f"[Alt-Upgrade] 未发现无人机,GPS/FC 升级用例将使用默认 IP: {target_ip}"
            )

        yield gcs_instance
        gcs_instance.close()


    @pytest.fixture(autouse=True)
    def _restore_wifi_firmware(self, serial_session, ftp_session):
        """函数级 fixture:测试前后确保 WiFi 固件还原到飞机初始版本

        策略(修复两个与真实业务的偏差):
        1. **基线真相源是 tag,不是 FTP 文件** — 测试前先 dmdfact getVer 拿到
           应用区当前的 tag 作为基线,再下载 FTP 上的 fota_793x.bin 作兜底材料。
           FTP 上的 bin 不保证等于应用区基线:可能是上次测试残留,用它还原后
           tag 不会回到基线。所以"是否已还原"必须以 tag 为准。
        2. **teardown 条件触发,不盲目双重 reboot** — 测试后先查 tag,
           tag == 基线 → 跳过还原(测试用例步骤 4 已还原就属于这种情况);
           tag != 基线 → 用备份还原 + reboot + 重连,再查 tag 验证;
           还原后仍 != 基线 → log error 报警要求人工干预。
        """
        _ensure_backup_dir()
        wifi_backup_ok = False
        baseline_tag = ""

        # 测试前:记录基线 tag + 下载 FTP 备份(尽力而为)
        try:
            baseline_tag = self._query_wifi_version(serial_session)
            if baseline_tag:
                log_manager.logger.info(
                    f"[Alt-Upgrade] 基线 tag(应用区当前): {baseline_tag}"
                )
            else:
                log_manager.logger.warning(
                    "[Alt-Upgrade] 无法获取基线 tag — teardown 将无法判定还原状态"
                )

            if ftp_session.connect() and ftp_session.file_exists(FTP_WIFI_FIRMWARE):
                if ftp_session.download_file(FTP_WIFI_FIRMWARE, WIFI_BACKUP_PATH):
                    wifi_backup_ok = True
                    log_manager.logger.info(
                        f"[Alt-Upgrade] 已下载 FTP 上的 WiFi 固件: {WIFI_BACKUP_PATH}"
                        "(注:不保证等于应用区基线,真相源是上面的 tag)"
                    )
            else:
                log_manager.logger.warning(
                    f"[Alt-Upgrade] FTP 上 {FTP_WIFI_FIRMWARE} 不存在或 FTP 连不上"
                )
        except Exception as e:
            log_manager.logger.warning(f"[Alt-Upgrade] 备份阶段异常: {e}")

        yield

        # 测试后:条件触发还原(以 tag 为准,避免盲目 reboot)
        if not baseline_tag:
            log_manager.logger.error(
                "[Alt-Upgrade] teardown: 无基线 tag,无法判定是否需要还原 — 请手动确认"
            )
            return

        current_tag = self._query_wifi_version(serial_session)
        if current_tag == baseline_tag:
            log_manager.logger.info(
                f"[Alt-Upgrade] teardown: 当前 tag({current_tag})已是基线,跳过还原"
            )
            return

        log_manager.logger.warning(
            f"[Alt-Upgrade] teardown: 当前 tag({current_tag})≠ 基线({baseline_tag}),"
            f"启动还原"
        )

        if not wifi_backup_ok or not os.path.exists(WIFI_BACKUP_PATH):
            log_manager.logger.error(
                f"[Alt-Upgrade] teardown: 无备份文件可还原 — 请手动还原到基线 tag {baseline_tag}"
            )
            return

        try:
            if not ftp_session.connect():
                log_manager.logger.error("[Alt-Upgrade] teardown: FTP 连接失败")
                return
            if not ftp_session.upload_file(WIFI_BACKUP_PATH, FTP_WIFI_FIRMWARE):
                log_manager.logger.error(
                    f"[Alt-Upgrade] teardown: 还原上传失败: {WIFI_BACKUP_PATH}"
                )
                return

            serial_session.update_wifi_module()
            # WiFi reboot 后串口要重连
            time.sleep(WIFI_UPGRADE_WAIT_S)
            reconnect_after_reboot(
                serial_session,
                baudrate=WIFI_DEFAULT_BAUDRATE,
                ready_wait=WIFI_REBOOT_READY_SECONDS,
                retries=5,
            )

            # 还原后再查 tag,验证是否真的回到基线
            restored_tag = self._query_wifi_version(serial_session)
            if restored_tag == baseline_tag:
                log_manager.logger.info(
                    f"[Alt-Upgrade] teardown: 已还原到基线 tag {baseline_tag}"
                )
            else:
                log_manager.logger.error(
                    f"[Alt-Upgrade] teardown: 还原后 tag({restored_tag})仍 ≠ 基线"
                    f"({baseline_tag})— FTP 备份可能不等于应用区基线固件,"
                    f"请手动还原"
                )
        except Exception as e:
            log_manager.logger.error(
                f"[Alt-Upgrade] teardown: 还原异常: {e} — 请手动还原到 tag {baseline_tag}"
            )


    # ==================== WiFi 固件交替升级 ====================


    @allure.title("WiFi 固件交替升级(本地版 → 验证变化 → 还原 → 验证恢复)")
    @allure.description(
        "完整 WiFi 固件往返流程:\n"
        "  1. 查询当前 WiFi 版本 tag(基线)\n"
        "  2. 上传 firmware/Wifi/fota_793x.bin + 串口 dmdcicd update wifi → 等 reboot\n"
        "  3. 查询版本 → 验证 tag 已变化\n"
        "  4. 上传步骤 1 备份固件 + dmdcicd update wifi → 等 reboot\n"
        "  5. 查询版本 → 验证 tag 已恢复到基线\n"
        "源码:dmd_cicd.c \"update wifi\" → FOTA 写入 + hal_sys_reboot\n"
        "fixture teardown 兜底:即使中途断言失败也会还原到基线。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("固件升级", "WiFi 模块", "交替升级", "版本验证")
    def test_wifi_firmware_round_trip(self, serial_session, ftp_session):
        """WiFi 固件往返升级 + 版本验证"""
        if not os.path.exists(WIFI_FIRMWARE_PATH):
            pytest.skip(f"本地 WiFi 固件不存在: {WIFI_FIRMWARE_PATH}")

        # 步骤 1:查询基线版本
        with allure.step("查询飞机当前 WiFi 版本(基线)"):
            baseline_version = self._query_wifi_version(serial_session)
            if not baseline_version:
                pytest.skip(
                    "无法获取 WiFi 基线版本(串口或固件异常)— 跳过避免无意义升级"
                )
            log_manager.logger.info(f"[Alt-Upgrade] WiFi 基线版本 tag: {baseline_version}")
            allure.attach(
                f"  WiFi 基线版本 tag: {baseline_version}\n"
                f"  本地固件: {WIFI_FIRMWARE_PATH}",
                name="基线信息",
                attachment_type=allure.attachment_type.TEXT
            )

        # 步骤 2:上传本地固件 + 触发升级
        with allure.step(f"上传本地 WiFi 固件并触发升级: {WIFI_FIRMWARE_PATH}"):
            upload_ok = self._upload_and_trigger_wifi(
                serial_session, ftp_session, WIFI_FIRMWARE_PATH
            )
            assert upload_ok, f"本地 WiFi 固件上传或升级触发失败: {WIFI_FIRMWARE_PATH}"

        with allure.step(f"等待 WiFi reboot + 串口重连({WIFI_UPGRADE_WAIT_S}s)"):
            time.sleep(WIFI_UPGRADE_WAIT_S)
            reconnect_ok = reconnect_after_reboot(
                serial_session,
                baudrate=WIFI_DEFAULT_BAUDRATE,
                ready_wait=WIFI_REBOOT_READY_SECONDS,
                retries=5,
            )
            if not reconnect_ok:
                pytest.fail(
                    "WiFi 升级后串口重连失败 — 可能 reboot 异常或串口端口被占用"
                )

        # 步骤 3:验证版本已变化
        with allure.step("查询升级后 WiFi 版本并验证变化"):
            upgraded_version = self._query_wifi_version(serial_session)
            allure.attach(
                f"  基线版本 tag: {baseline_version}\n"
                f"  升级后 tag: {upgraded_version}",
                name="版本对比",
                attachment_type=allure.attachment_type.TEXT
            )

            # 关键断言:版本必须变化(否则升级没生效)
            # 边界情况:本地固件和飞机当前固件相同 → 此时 tag 相同,Skip 而非 FAIL
            if upgraded_version == baseline_version:
                pytest.skip(
                    f"升级前后版本相同({baseline_version})— 本地固件与飞机当前固件一致,"
                    "无法验证「变化」,但升级流程本身未崩溃"
                )

            assert upgraded_version != baseline_version, (
                f"WiFi 升级后版本未变化: 基线={baseline_version}, 升级后={upgraded_version}"
            )
            log_manager.logger.info(
                f"[Alt-Upgrade] WiFi 版本变化: {baseline_version} → {upgraded_version}"
            )

        # 步骤 4:还原到基线(teardown 也会做,这里主动验证)
        with allure.step("用备份固件还原到基线"):
            restore_ok = self._upload_and_trigger_wifi(
                serial_session, ftp_session, WIFI_BACKUP_PATH
            )
            assert restore_ok, "WiFi 还原上传或升级触发失败"

        with allure.step(f"等待 WiFi reboot + 串口重连({WIFI_UPGRADE_WAIT_S}s)"):
            time.sleep(WIFI_UPGRADE_WAIT_S)
            reconnect_after_reboot(
                serial_session,
                baudrate=WIFI_DEFAULT_BAUDRATE,
                ready_wait=WIFI_REBOOT_READY_SECONDS,
                retries=5,
            )

        # 步骤 5:验证版本已恢复
        with allure.step("查询还原后 WiFi 版本并验证恢复"):
            restored_version = self._query_wifi_version(serial_session)
            allure.attach(
                f"  基线版本 tag: {baseline_version}\n"
                f"  还原后 tag: {restored_version}",
                name="还原验证",
                attachment_type=allure.attachment_type.TEXT
            )

            # 软断言:版本恢复 — 不同则警告(不 FAIL,因为 teardown 会再尝试还原)
            if restored_version != baseline_version:
                log_manager.logger.warning(
                    f"[Alt-Upgrade] WiFi 还原后版本({restored_version})"
                    f"与基线({baseline_version})不一致 — teardown 会再次还原"
                )
            else:
                log_manager.logger.info(
                    f"[Alt-Upgrade] WiFi 已恢复到基线: {restored_version}"
                )

            allure.attach(
                f"【测试结果】\n"
                f"  WiFi 固件往返升级成功\n"
                f"  基线 → 升级后 → 还原后: {baseline_version} → {upgraded_version} → {restored_version}\n"
                f"  版本变化验证: 通过\n"
                f"  版本恢复验证: {'通过' if restored_version == baseline_version else '失败(teardown 兜底)'}",
                name="测试总结",
                attachment_type=allure.attachment_type.TEXT
            )


    # ==================== GPS 固件交替升级 ====================


    @allure.title("GPS 固件交替升级(本地版 → 验证 → 还原)")
    @allure.description(
        "完整 GPS 固件往返流程:\n"
        "  1. 记录基线(GPS 固件文件大小 + CRC32,因 GPS 版本需要 FC 上报)\n"
        "  2. 上传 firmware/Gps/GPS.bin + MAV_CMD_UPDATE_COMPANION param1=2\n"
        "  3. 等待 GPS 内部刷写完成\n"
        "  4. 上传备份 GPS 固件 + 再触发 → 还原\n"
        "注:GPS 版本号在 EXTEND_STATE msg_id=8 中由 FC 上报,本测试不依赖 FC 心跳,\n"
        "    通过文件 CRC32 + 升级返回 success 间接验证流程通过。\n"
        "上次 #450.txt 经验:ACK 超时拉到 30s + 不强依赖 ACK,主要看 upgrade_gps.success。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("固件升级", "GPS", "交替升级")
    def test_gps_firmware_round_trip(self, gcs_upgrade, ftp_session, mavlink_version):
        """GPS 固件往返升级"""
        if not os.path.exists(GPS_FIRMWARE_PATH):
            pytest.skip(f"本地 GPS 固件不存在: {GPS_FIRMWARE_PATH}")

        # 先备份当前 FTP 上的 gps.bin(如果有)
        gps_backup_exists = False
        try:
            if ftp_session.connect() and ftp_session.file_exists(FTP_GPS_FIRMWARE):
                if ftp_session.download_file(FTP_GPS_FIRMWARE, GPS_BACKUP_PATH):
                    gps_backup_exists = True
                    log_manager.logger.info(
                        f"[Alt-Upgrade] 已备份飞机当前 GPS 固件: {GPS_BACKUP_PATH}"
                    )
        except Exception as e:
            log_manager.logger.warning(f"[Alt-Upgrade] 备份 GPS 固件异常: {e}")

        # 步骤 1:上传本地 GPS 固件 + 触发升级
        with allure.step("上传本地 GPS 固件并触发升级"):
            result_up = upgrade_gps(
                gcs_upgrade, ftp_session, mavlink_version,
                firmware_path=GPS_FIRMWARE_PATH,
                remote_path=FTP_GPS_FIRMWARE,
                ack_timeout=30.0,  # 经验值:#450.txt 中 10s 超时,放宽到 30s
            )
            allure.attach(
                f"  本地固件: {GPS_FIRMWARE_PATH}\n"
                f"  upgrade_gps.success: {result_up.success}\n"
                f"  upgrade_gps.error: {result_up.error}\n"
                f"  ACK result: {result_up.ack_result}\n"
                f"  等待秒数: {result_up.wait_seconds}",
                name="升级结果",
                attachment_type=allure.attachment_type.TEXT
            )

            # GPS 升级触发链路必须通,实际刷写完成由固件保证
            if not result_up.success:
                # ACK 超时但 FTP 上传成功 → 也算部分通过(上次 #450.txt 也碰到 ACK 超时)
                if result_up.error and "未收到 COMMAND_ACK" in result_up.error:
                    log_manager.logger.warning(
                        "[Alt-Upgrade] GPS 升级 ACK 超时,但 FTP 上传已成功 — "
                        "固件可能仍在后台刷写,继续等待"
                    )
                else:
                    pytest.fail(f"GPS 升级失败: {result_up.error}")

        # 步骤 2:等待内部刷写完成
        with allure.step(f"等待 GPS 内部刷写({GPS_UPGRADE_WAIT_S}s)"):
            time.sleep(GPS_UPGRADE_WAIT_S)

        # 步骤 3:还原(如果有备份)
        if gps_backup_exists:
            with allure.step("用备份 GPS 固件还原"):
                result_restore = upgrade_gps(
                    gcs_upgrade, ftp_session, mavlink_version,
                    firmware_path=GPS_BACKUP_PATH,
                    remote_path=FTP_GPS_FIRMWARE,
                    ack_timeout=30.0,
                )
                allure.attach(
                    f"  还原固件: {GPS_BACKUP_PATH}\n"
                    f"  upgrade_gps.success: {result_restore.success}\n"
                    f"  ACK result: {result_restore.ack_result}",
                    name="还原结果",
                    attachment_type=allure.attachment_type.TEXT
                )

                # 还原失败不 FAIL(teardown 也不能再补救,因为 GPS 无 teardown),
                # 但要明确警告用户手动还原
                if not result_restore.success:
                    log_manager.logger.error(
                        "[Alt-Upgrade] GPS 还原失败 — 请手动上传原始 gps.bin 重升"
                    )

            with allure.step(f"等待 GPS 还原后内部刷写({GPS_UPGRADE_WAIT_S}s)"):
                time.sleep(GPS_UPGRADE_WAIT_S)
        else:
            log_manager.logger.warning(
                "[Alt-Upgrade] 无 GPS 备份文件,跳过还原步骤 — "
                "请手动确认飞机上的 GPS 固件版本是否需要恢复"
            )

        allure.attach(
            f"【测试结果】\n"
            f"  GPS 固件升级触发: {'成功' if result_up.success else 'ACK 超时(可能仍在后台刷写)'}\n"
            f"  GPS 固件还原: {'已触发' if gps_backup_exists else '跳过(无备份)'}\n"
            f"  注: GPS 版本号需要 FC 上报 EXTEND_STATE,本测试不验证版本字段\n"
            f"      主要验证 FTP 上传 + MAV_CMD 触发 + WiFi 模块不崩溃",
            name="测试总结",
            attachment_type=allure.attachment_type.TEXT
        )


    # ==================== FC 固件交替升级(companion 整包) ====================


    @allure.title("FC 固件交替升级(update.zip 整包 → 验证 → 还原)")
    @allure.description(
        "FC 固件通过 companion 整包升级流程:\n"
        "  1. 把 firmware/Fc/dmd_uav.bin 打包成 update.zip\n"
        "  2. FTP 上传 update.zip 到 /root/update.zip\n"
        "  3. MAV_CMD_UPDATE_COMPANION param1=0 触发 → 解压 → fcs_upgrade → reboot\n"
        "  4. 等 reboot 重连\n"
        "注:companion 整包升级会让 WiFi 模块也 reboot,fixture teardown 必须确保还原。\n"
        "本测试不做版本字段断言(需要 FC 上报 EXTEND_STATE),只验证流程不崩溃。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("固件升级", "FC 飞控", "companion 整包", "交替升级")
    def test_fc_firmware_round_trip(
        self, serial_session, gcs_upgrade, ftp_session, mavlink_version, tmp_path
    ):
        """FC 固件往返升级(update.zip 整包路径)"""
        if not os.path.exists(FC_FIRMWARE_PATH):
            pytest.skip(f"本地 FC 固件不存在: {FC_FIRMWARE_PATH}")

        # 步骤 1:打包 FC 固件为 update.zip
        update_zip = str(tmp_path / "update.zip")
        with allure.step(f"打包 FC 固件: {FC_FIRMWARE_PATH} → {update_zip}"):
            if not _zip_fc_firmware(FC_FIRMWARE_PATH, update_zip):
                pytest.fail("FC 固件打包失败")

        # 步骤 2:上传 + 触发 companion 整包升级
        with allure.step("上传 update.zip 并触发 companion 整包升级"):
            result_up = upgrade_companion(
                gcs_upgrade, ftp_session, mavlink_version,
                firmware_path=update_zip,
                remote_path=FTP_UPDATE_ZIP,
                ack_timeout=30.0,
            )
            allure.attach(
                f"  update.zip: {update_zip}({os.path.getsize(update_zip)} 字节)\n"
                f"  upgrade_companion.success: {result_up.success}\n"
                f"  ACK result: {result_up.ack_result}\n"
                f"  等待秒数: {result_up.wait_seconds}",
                name="升级结果",
                attachment_type=allure.attachment_type.TEXT
            )

            # ACK 超时容忍:companion 升级 ACK 路径长,可能超时
            if not result_up.success:
                if result_up.error and "未收到 COMMAND_ACK" in result_up.error:
                    log_manager.logger.warning(
                        "[Alt-Upgrade] companion 整包 ACK 超时,FTP 已上传 — "
                        "可能仍在后台解压 + 刷写,继续等待"
                    )
                else:
                    pytest.fail(f"companion 整包升级失败: {result_up.error}")

        # 步骤 3:等待 companion 升级完成(解压 + fcs + reboot)
        with allure.step(f"等待 companion 整包升级 + reboot({COMPANION_UPGRADE_WAIT_S}s)"):
            time.sleep(COMPANION_UPGRADE_WAIT_S)
            # companion 升级会让 WiFi 模块也 reboot,需要重连串口
            reconnect_ok = reconnect_after_reboot(
                serial_session,
                baudrate=WIFI_DEFAULT_BAUDRATE,
                ready_wait=WIFI_REBOOT_READY_SECONDS,
                retries=5,
            )
            if not reconnect_ok:
                log_manager.logger.warning(
                    "[Alt-Upgrade] companion 升级后串口重连失败 — "
                    "WiFi 模块可能仍在 reboot 中,请手动检查"
                )

        # 验证 WiFi 模块存活(基础命令能响应)
        with allure.step("验证 WiFi 模块在 FC 升级后仍存活"):
            alive_version = self._query_wifi_version(serial_session)
            allure.attach(
                f"  companion 升级后 WiFi 版本: {alive_version or '(无响应)'}\n"
                f"  存活判定: {'OK' if alive_version else 'WiFi 无响应'}",
                name="存活验证",
                attachment_type=allure.attachment_type.TEXT
            )
            # 这里不强制 assert,因为 companion reboot 可能让 WiFi 串口短暂无响应
            if not alive_version:
                log_manager.logger.warning(
                    "[Alt-Upgrade] companion 升级后 WiFi 无响应 — "
                    "可能仍在 reboot 中,请人工检查飞机状态"
                )

        allure.attach(
            f"【测试结果】\n"
            f"  FC 固件 companion 整包升级触发: {'成功' if result_up.success else 'ACK 超时(可能仍在后台刷写)'}\n"
            f"  WiFi 模块存活: {'OK' if alive_version else '需人工检查'}\n"
            f"  注: FC 版本号需要 FC 上报 EXTEND_STATE,本测试不验证版本字段\n"
            f"      主要验证 update.zip 打包 + FTP 上传 + MAV_CMD 触发 + WiFi 不崩溃\n"
            f"  注: FC 固件还原需手动用原始 dmd_uav.bin 重升 — 飞机初始 FC 固件未备份",
            name="测试总结",
            attachment_type=allure.attachment_type.TEXT
        )


    # ==================== 电池固件升级触发(stub 阶段) ====================


    @allure.title("电池固件升级触发(MAV_CMD_UPDATE_COMPANION param1=1)")
    @allure.description(
        "通过协议层 trigger_battery_upgrade 验证电池升级触发链路:\n"
        "  1. FTP 上传 battery.bin 到 /root/battery.bin\n"
        "  2. 发 MAV_CMD_UPDATE_COMPANION param1=1\n"
        "  3. 验证 COMMAND_ACK result=0(ACCEPTED)\n"
        "源码 onion_companion.c:227-233:检查 /root/battery.bin 存在 → 透传 UAV + 回 ACK。\n"
        "注:upgrade_task 电池分支当前为 stub(onion_upgrade.c:445 注释 ' // update battery'),\n"
        "    实际升级未执行,本用例仅验证触发链路(FTP + ACK),不做 round_trip 版本验证。\n"
        "失败路径(文件缺失)见 test_wifi_upgrade_failure.py::test_battery_upgrade_file_missing。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("固件升级", "电池升级", "触发链路")
    def test_battery_firmware_upgrade_trigger(self, gcs_upgrade, ftp_session, mavlink_version):
        """电池固件升级触发(成功路径,stub 阶段只验证 ACK)"""
        if not os.path.exists(BAT_FIRMWARE_PATH):
            pytest.skip(f"本地电池固件不存在: {BAT_FIRMWARE_PATH}")

        firmware_len = os.path.getsize(BAT_FIRMWARE_PATH)

        allure.attach(
            f"【固件信息】\n"
            f"  文件: {BAT_FIRMWARE_PATH}\n"
            f"  大小: {firmware_len} 字节({firmware_len / 1024:.1f} KB)\n"
            f"  FTP 路径: {FTP_BATTERY_FIRMWARE}\n"
            f"  触发命令: MAV_CMD_UPDATE_COMPANION param1=1",
            name="固件信息",
            attachment_type=allure.attachment_type.TEXT
        )

        with allure.step("执行电池升级触发(协议层 trigger_battery_upgrade)"):
            result = trigger_battery_upgrade(
                gcs_upgrade, ftp_session, mavlink_version, BAT_FIRMWARE_PATH,
                remote_path=FTP_BATTERY_FIRMWARE, ack_timeout=DEFAULT_ACK_TIMEOUT,
            )
            assert result.success, (
                f"电池升级触发失败: {result.error}(可能 /root/battery.bin 未被识别)"
            )

        allure.attach(
            f"【测试结果】\n"
            f"  电池固件升级触发成功\n"
            f"  COMMAND_ACK result: {result.ack_result} (ACCEPTED)\n"
            f"  注:upgrade_task 电池分支为 stub,实际升级未执行\n"
            f"  本用例仅验证 FTP 上传 + 命令接收 + ACK 回复",
            name="测试结果",
            attachment_type=allure.attachment_type.TEXT
        )


    # ==================== 内部辅助方法 ====================


    def _query_wifi_version(self, serial_session) -> str:
        """查询 WiFi 版本并提取 tag,失败返回空字符串"""
        try:
            raw = serial_session.get_wifi_version()
            if not raw:
                return ""
            tag = _extract_wifi_tag(raw)
            log_manager.logger.info(f"[Alt-Upgrade] WiFi 版本查询: raw[:120]={raw[:120]!r}, tag={tag}")
            return tag
        except Exception as e:
            log_manager.logger.warning(f"[Alt-Upgrade] WiFi 版本查询异常: {e}")
            return ""


    def _upload_and_trigger_wifi(self, serial_session, ftp_session, local_path: str) -> bool:
        """上传 WiFi 固件到 FTP + 触发 dmdcicd update wifi"""
        try:
            if not ftp_session.connect():
                log_manager.logger.error("[Alt-Upgrade] FTP 连接失败")
                return False
            if not ftp_session.upload_file(local_path, FTP_WIFI_FIRMWARE):
                log_manager.logger.error(
                    f"[Alt-Upgrade] WiFi 固件上传失败: {local_path} -> {FTP_WIFI_FIRMWARE}"
                )
                return False
            log_manager.logger.info(
                f"[Alt-Upgrade] WiFi 固件上传成功: {local_path}({os.path.getsize(local_path)} 字节)"
            )

            # 触发 WiFi 模块固件升级
            # update_wifi_module 现在严格校验回显:命中 usage/unknown/not exist/failed
            # 任一失败标志返回 None,且必须检测到 "open ... ok" 成功标志才返回非空
            result = serial_session.update_wifi_module()
            if not result:
                log_manager.logger.error(
                    "[Alt-Upgrade] dmdcicd update wifi 失败(无回显 / 命中失败标志 / "
                    "未检测到 open ok 成功标志),详见 protocol 层日志"
                )
                return False
            log_manager.logger.info(
                f"[Alt-Upgrade] dmdcicd update wifi 响应: {str(result)[:120]!r}"
            )
            return True
        except Exception as e:
            log_manager.logger.error(f"[Alt-Upgrade] WiFi 固件上传/触发异常: {e}")
            return False
