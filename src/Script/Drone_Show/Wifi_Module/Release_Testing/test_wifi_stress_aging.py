# coding: utf-8
"""
WiFi 模块测试 - 压力与老化测试

业务背景:
    长时间运行稳定性是 WiFi 模块在无人机编队表演中的关键质量属性。压测通过高
    频率的重复操作(SSID 切换、FTP 文件传输、Ping 测试、系统状态监控)模拟极端
    使用场景,暴露潜在的内存泄漏、连接资源耗尽、SD 卡写入异常、网络栈不稳定
    等问题。压测脚本默认执行 30 次循环,可根据需要调整 LOOP_COUNT 参数。

测试对象:
    - WiFi 模块长时间运行稳定性
    - WiFi 模块 SSID 切换的重连能力(循环切换 test_ssid 和 test_ssid_alt)
    - FTP 文件传输的长时间稳定性(循环上传随机 1KB 文件)
    - 网络连通性的长时间稳定性(循环 Ping 网关)
    - 系统资源占用的长时间稳定性(循环检查任务列表、WiFi 状态、SD 卡容量)

副作用管理:
    所有压测都通过 autouse fixture 在结束后还原 SSID(切回 test_ssid)。
    即使压测中途失败也会执行 teardown,避免污染后续测试。
"""
import os
import time
import pytest
import allure

from utils.logger import log_manager


@allure.epic("WiFi 模块测试")
@allure.feature("老化压测")
@allure.story("长时间运行稳定性")
class TestWifiStressAging:
    """WiFi 老化压测类"""

    # ==================== 压测参数 ====================
    LOOP_COUNT = 30          # 循环次数
    PING_INTERVAL = 2        # Ping 间隔(秒)
    SSID_SWITCH_INTERVAL = 5 # SSID 切换间隔(秒)
    SSID_RECONNECT_DELAY = 5 # SSID 重连等待(秒)

    @pytest.fixture(autouse=True)
    def _restore_ssid(self, serial_session, test_params):
        """压测前后还原 SSID,避免污染后续测试

        autouse=True,所有测试用例都会自动应用。
        压测常会切换 SSID 导致遗留状态,teardown 阶段必须还原。
        """
        original_ssid = test_params["test_ssid"]
        log_manager.logger.info(f"[Stress-Preserve] 测试前 SSID={original_ssid}")
        yield
        try:
            log_manager.logger.info(f"[Stress-Preserve] 还原 SSID: {original_ssid}")
            serial_session.change_ssid(original_ssid)
            time.sleep(self.SSID_RECONNECT_DELAY)
            log_manager.logger.info("[Stress-Preserve] 还原完成")
        except Exception as e:
            log_manager.logger.error(f"[Stress-Preserve] 还原失败: {e}")

    # ==================== 压测用例 ====================


    @allure.title("循环 Ping 测试")
    @allure.description(
        f"循环 {LOOP_COUNT} 次 Ping 网关(间隔 {PING_INTERVAL}s),"
        "验证网络稳定性。允许个别失败但总失败率不超过 10%。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "压测", "Ping", "循环")
    def test_loop_ping(self, serial_session, test_params):
        """循环执行 Ping 测试,验证网络稳定性"""
        gateway = test_params["test_gateway"]
        fail_count = 0
        fail_threshold = max(1, self.LOOP_COUNT // 10)  # 允许 10% 失败

        with allure.step(f"循环 Ping {self.LOOP_COUNT} 次,间隔 {self.PING_INTERVAL}s"):
            for i in range(self.LOOP_COUNT):
                result = serial_session.ping(gateway)
                if result is None or result.get("loss_percent", 100) > 0:
                    fail_count += 1
                    log_manager.logger.warning(
                        f"[{i+1}/{self.LOOP_COUNT}] Ping 失败 (累计失败: {fail_count})"
                    )
                else:
                    avg = result.get("avg_ms", "N/A")
                    log_manager.logger.info(
                        f"[{i+1}/{self.LOOP_COUNT}] Ping 成功, 延迟: {avg}ms"
                    )
                time.sleep(self.PING_INTERVAL)

        with allure.step("验证结果"):
            log_manager.logger.info(
                f"Ping 测试完成: 总次数 {self.LOOP_COUNT}, 失败 {fail_count} 次"
            )
            allure.attach(
                f"【压测结果】\n"
                f"  总次数: {self.LOOP_COUNT}\n"
                f"  失败次数: {fail_count}\n"
                f"  失败率: {fail_count / self.LOOP_COUNT * 100:.1f}%\n"
                f"  阈值: {fail_threshold} 次({fail_threshold / self.LOOP_COUNT * 100:.0f}%)",
                name="Ping 压测结果",
                attachment_type=allure.attachment_type.TEXT
            )
            assert fail_count <= fail_threshold, (
                f"Ping 失败 {fail_count} 次超过阈值 {fail_threshold} 次"
            )


    @allure.title("循环 SSID 切换测试")
    @allure.description(
        f"循环 {LOOP_COUNT} 次在 test_ssid 和 test_ssid_alt 之间切换"
        f"(间隔 {SSID_SWITCH_INTERVAL}s),验证每次切换后 WiFi 连接正常"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "压测", "SSID 切换", "循环")
    def test_loop_ssid_switch(self, serial_session, test_params):
        """循环切换 SSID,验证重连能力"""
        ssids = [test_params["test_ssid"], test_params["test_ssid_alt"]]
        fail_count = 0
        fail_threshold = max(1, self.LOOP_COUNT // 10)  # 允许 10% 失败

        with allure.step(f"循环切换 SSID {self.LOOP_COUNT} 次"):
            for i in range(self.LOOP_COUNT):
                ssid = ssids[i % len(ssids)]
                success = serial_session.change_ssid(ssid)
                time.sleep(self.SSID_SWITCH_INTERVAL)

                status = serial_session.check_wifi_connection()
                if success and status and status.get("is_linked"):
                    log_manager.logger.info(
                        f"[{i+1}/{self.LOOP_COUNT}] SSID 切换成功: {ssid}, "
                        f"RSSI: {status.get('rssi')}"
                    )
                else:
                    fail_count += 1
                    log_manager.logger.warning(
                        f"[{i+1}/{self.LOOP_COUNT}] SSID 切换后未连接: {ssid}"
                    )

        with allure.step("验证结果"):
            log_manager.logger.info(
                f"SSID 切换测试完成: 总次数 {self.LOOP_COUNT}, 失败 {fail_count} 次"
            )
            allure.attach(
                f"【压测结果】\n"
                f"  总次数: {self.LOOP_COUNT}\n"
                f"  失败次数: {fail_count}\n"
                f"  失败率: {fail_count / self.LOOP_COUNT * 100:.1f}%",
                name="SSID 切换压测结果",
                attachment_type=allure.attachment_type.TEXT
            )
            assert fail_count <= fail_threshold, (
                f"SSID 切换失败 {fail_count} 次超过阈值 {fail_threshold} 次"
            )

        # SSID 还原由 fixture teardown 完成


    @allure.title("循环文件传输测试")
    @allure.description(
        f"循环 {LOOP_COUNT} 次上传 1KB 随机文件到 FTP,验证上传成功率 100%。"
        "teardown 兜底删除所有成功上传的远端文件, 避免在设备 /cmpn/dmd_companion/ 残留。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "压测", "FTP", "循环")
    def test_loop_file_transfer(self, serial_session, ftp_session):
        """循环上传文件,验证 FTP 稳定性 (teardown 清理远端残留)"""
        fail_count = 0
        uploaded_remotes = []  # 收集成功上传的远端路径, finally 统一清理

        try:
            with allure.step(f"循环上传文件 {self.LOOP_COUNT} 次"):
                for i in range(self.LOOP_COUNT):
                    # 首次上传前确保 FTP 已连接
                    if i == 0:
                        ftp_session.reconnect()

                    # 创建测试文件(Windows 兼容路径)
                    if os.name == "nt":
                        local_path = os.path.join(
                            os.environ.get("TEMP", "."), f"stress_test_{i}.bin"
                        )
                    else:
                        local_path = f"/tmp/stress_test_{i}.bin"

                    with open(local_path, "wb") as f:
                        f.write(os.urandom(1024))  # 1KB

                    remote_path = f"/cmpn/dmd_companion/stress_test_{i}.bin"
                    success = ftp_session.upload_file(local_path, remote_path)

                    if success:
                        uploaded_remotes.append(remote_path)
                        log_manager.logger.info(
                            f"[{i+1}/{self.LOOP_COUNT}] 文件上传成功: {remote_path}"
                        )
                    else:
                        fail_count += 1
                        log_manager.logger.warning(
                            f"[{i+1}/{self.LOOP_COUNT}] 文件上传失败: {remote_path}"
                        )

                    # 清理本地文件 (远端 finally 统一清理)
                    if os.path.exists(local_path):
                        os.remove(local_path)

                    time.sleep(2)

            with allure.step("验证结果"):
                log_manager.logger.info(
                    f"文件传输测试完成: 总次数 {self.LOOP_COUNT}, 失败 {fail_count} 次"
                )
                allure.attach(
                    f"【压测结果】\n"
                    f"  总次数: {self.LOOP_COUNT}\n"
                    f"  失败次数: {fail_count}\n"
                    f"  成功率: {(self.LOOP_COUNT - fail_count) / self.LOOP_COUNT * 100:.1f}%",
                    name="文件传输压测结果",
                    attachment_type=allure.attachment_type.TEXT
                )
                # 文件传输要求 100% 成功(每次上传都是独立操作,失败即异常)
                assert fail_count == 0, (
                    f"文件传输存在 {fail_count} 次失败(期望 0)"
                )
        finally:
            # 兜底清理所有成功上传的远端文件, 不论断言是否失败都执行
            if uploaded_remotes:
                log_manager.logger.info(
                    f"[Cleanup] 删除 {len(uploaded_remotes)} 个远端 stress_test_*.bin"
                )
                try:
                    ftp_session.reconnect()
                except Exception:
                    pass
                for r in uploaded_remotes:
                    try:
                        ftp_session.delete_file(r)
                    except Exception as e:
                        log_manager.logger.warning(f"[Cleanup] 删除 {r} 失败: {e}")


    @allure.title("系统状态循环监控")
    @allure.description(
        f"循环 {LOOP_COUNT} 次获取系统任务、WiFi 状态、SD 卡容量(间隔 5s),"
        "验证所有查询成功。SD 卡未挂载时跳过 SD 字段检查。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "压测", "系统状态", "循环")
    def test_loop_system_status(self, serial_session):
        """循环检查系统任务状态,验证资源占用"""
        fail_count = 0
        sd_skip = False  # 一次性检测 SD 是否可用

        with allure.step(f"循环检查系统状态 {self.LOOP_COUNT} 次"):
            for i in range(self.LOOP_COUNT):
                tasks = serial_session.get_os_tasks()
                wifi_info = serial_session.get_wifi_info()

                # tasks 和 wifi_info 是核心字段,必须可用
                if tasks is None or wifi_info is None:
                    fail_count += 1
                    log_manager.logger.warning(
                        f"[{i+1}/{self.LOOP_COUNT}] 获取核心状态失败"
                        f"(tasks={'OK' if tasks else 'None'}, "
                        f"wifi_info={'OK' if wifi_info else 'None'})"
                    )
                else:
                    # SD 卡可选(首次失败后不再尝试,避免日志噪声)
                    sd_info = None
                    if not sd_skip:
                        sd_info = serial_session.get_sd_card_info()
                        if sd_info is None:
                            sd_skip = True
                            log_manager.logger.info(
                                f"[{i+1}/{self.LOOP_COUNT}] SD 卡未挂载,后续跳过 SD 字段"
                            )

                    log_manager.logger.info(
                        f"[{i+1}/{self.LOOP_COUNT}] 任务数: {len(tasks)}, "
                        f"WiFi: {wifi_info.get('connect_status')}, "
                        f"SD 剩余: {sd_info.get('total_free_mb') if sd_info else 'N/A'}MB"
                    )

                time.sleep(5)

        with allure.step("验证结果"):
            log_manager.logger.info(
                f"系统状态监控完成: 总次数 {self.LOOP_COUNT}, 失败 {fail_count} 次"
            )
            allure.attach(
                f"【压测结果】\n"
                f"  总次数: {self.LOOP_COUNT}\n"
                f"  失败次数: {fail_count}\n"
                f"  SD 卡: {'跳过(未挂载)' if sd_skip else '正常监控'}",
                name="系统状态压测结果",
                attachment_type=allure.attachment_type.TEXT
            )
            assert fail_count == 0, (
                f"系统状态查询存在 {fail_count} 次失败"
            )
