# coding: utf-8
"""
WiFi 模块测试 - SD 卡与网络性能

业务背景:
    WiFi 模块内置 SD 卡用于存储飞行日志、表演数据等信息,其读写性能和剩余容量
    直接影响数据存储的可靠性。同时,网络延迟是评估 WiFi 通信质量的重要指标。
    本测试通过串口命令检查 SD 卡容量、执行 SD 卡读写性能测试(dmdfact sdTest),
    并对网关执行 Ping 延迟测试,为性能基线建立和容量规划提供数据。

中间件事实(来自 mt793x dmd_factory.c + fatfs_utils.c):
    - dmdfact sdCap → fatfs_print_free():输出 fre_clust/csize/ssize/total_free(单位 MB)
    - dmdfact sdTest → fatfs_write_test("0:/test.txt"):
        * 写入固定 4096000 字节(1000 × 4096B)
        * 输出行 "write file success, fsize:%lld, time:%d, speed:%lld KB/s"
        * 字段 file_size=4096000, time_ms=实际耗时, speed_kbps=计算速度
    - WIFITEST 模式无 SD 卡服务,dmdfact sdTest/sdCap 返回失败

副作用管理:
    无副作用 — sdTest 写的是固定路径 0:/test.txt,固件每次会覆盖。
"""
import pytest
import allure

from utils.logger import log_manager


@allure.epic("WiFi 模块测试")
@allure.feature("性能测试")
@allure.story("SD 卡与网络性能")
class TestSdAndNetworkPerformance:
    """SD 卡与网络性能测试类"""

    # SD 卡性能阈值(来自 fatfs_utils.c:固定写 4096000B,speed=4096000/time_ms*1000 KB/s)
    EXPECTED_SD_FILE_SIZE = 4096000  # fatfs_utils.c:673 写入 1000 × 4096B
    MIN_SD_SPEED_KBPS = 300          # 性能告警阈值(预期约 400 KB/s)
    MIN_SD_FREE_MB = 100             # 最小剩余空间阈值


    @allure.title("SD 卡容量检查")
    @allure.description("dmdfact sdCap 调用 fatfs_print_free,返回 total_free_mb 字段")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "性能", "SD 卡", "容量")
    def test_sd_card_capacity(self, serial_session):
        """测试检查 SD 卡剩余容量"""
        with allure.step("发送 dmdfact sdCap 命令"):
            result = serial_session.get_sd_card_info()

        with allure.step("验证 SD 卡容量"):
            if result is None:
                pytest.skip("SD 卡未挂载或未插入 — 跳过(WIFITEST 模式无 SD 服务)")

            assert isinstance(result, dict), f"期望 dict,实际 {type(result).__name__}"
            log_manager.logger.info(f"SD 卡容量信息: {result}")

            free_mb = result.get("total_free_mb")
            assert free_mb is not None, "total_free_mb 字段为空"
            assert isinstance(free_mb, (int, float)), \
                f"total_free_mb 应为数值,实际 {type(free_mb).__name__}"
            assert free_mb > self.MIN_SD_FREE_MB, \
                f"SD 卡剩余空间不足: {free_mb}MB (阈值 {self.MIN_SD_FREE_MB}MB)"

            allure.attach(
                f"【测试结果】\n  剩余空间: {free_mb} MB",
                name="SD 卡容量",
                attachment_type=allure.attachment_type.TEXT
            )


    @allure.title("SD 卡读写性能测试")
    @allure.description(
        "dmdfact sdTest 调用 fatfs_write_test,固定写入 4096000 字节(1000×4096B),"
        "输出 fsize/time/speed。源码依据:fatfs_utils.c:673,701,705"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "性能", "SD 卡", "读写速度")
    def test_sd_card_rw_performance(self, serial_session):
        """测试 SD 卡读写速度"""
        with allure.step("发送 dmdfact sdTest 命令"):
            result = serial_session.sd_card_test()

        with allure.step("验证读写性能"):
            if result is None:
                pytest.skip("SD 卡未挂载或未插入 — 跳过 sdTest")

            assert isinstance(result, dict), f"期望 dict,实际 {type(result).__name__}"
            assert result.get("test_passed") is True, \
                f"SD 卡读写测试未通过: {result}"
            log_manager.logger.info(f"SD 卡性能: {result}")

            file_size = result.get("file_size")
            time_ms = result.get("time_ms")
            speed_kbps = result.get("speed_kbps")

            # 固件写固定 4096000 字节,file_size 应等于该值(fatfs_utils.c:673)
            if file_size is not None:
                assert file_size == self.EXPECTED_SD_FILE_SIZE, \
                    f"file_size 应为固定值 {self.EXPECTED_SD_FILE_SIZE},实际 {file_size}"

            # time_ms 必须为正数
            if time_ms is not None:
                assert time_ms > 0, f"time_ms 应为正数,实际 {time_ms}"

            # speed_kbps 校验:理论值 = 4096000 / time_ms * 1000 ≈ 4000000/time_ms KB/s
            if speed_kbps is not None:
                assert speed_kbps > 0, f"speed_kbps 应为正,实际 {speed_kbps}"
                if speed_kbps < self.MIN_SD_SPEED_KBPS:
                    log_manager.logger.warning(
                        f"SD 卡写入速度偏低: {speed_kbps} KB/s"
                        f"(阈值 {self.MIN_SD_SPEED_KBPS} KB/s,预期约 400 KB/s)"
                    )

            allure.attach(
                f"【测试结果】\n"
                f"  文件大小: {file_size} 字节\n"
                f"  写入耗时: {time_ms} ms\n"
                f"  写入速度: {speed_kbps} KB/s",
                name="SD 卡性能",
                attachment_type=allure.attachment_type.TEXT
            )


    @allure.title("Ping 网关延迟测试")
    @allure.description("对网关执行 Ping 测试,验证零丢包并记录平均延迟(阈值 50ms)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("WiFi", "性能", "Ping", "延迟")
    def test_ping_gateway_latency(self, serial_session, test_params):
        """测试 Ping 网关延迟"""
        gateway = test_params["test_gateway"]

        with allure.step(f"执行 ping {gateway}"):
            result = serial_session.ping(gateway)

        with allure.step("验证 Ping 结果"):
            assert result is not None, "Ping 命令执行失败(无响应或解析失败)"
            assert isinstance(result, dict), f"期望 dict,实际 {type(result).__name__}"

            sent = result.get("sent")
            received = result.get("received")
            loss_percent = result.get("loss_percent", 100)
            avg_ms = result.get("avg_ms")

            assert sent is not None and sent > 0, f"sent 字段无效: {sent}"
            assert received is not None and received >= 0, f"received 字段无效: {received}"
            assert received <= sent, f"received({received}) > sent({sent})"
            assert loss_percent == 0, f"Ping 存在丢包: {loss_percent}% (received={received}/{sent})"

            allure.attach(
                f"【测试结果】\n"
                f"  目标: {gateway}\n"
                f"  发送/接收/丢失: {sent}/{received}/{sent - received}\n"
                f"  丢包率: {loss_percent}%\n"
                f"  延迟: min={result.get('min_ms')}ms, "
                f"max={result.get('max_ms')}ms, avg={avg_ms}ms",
                name="Ping 延迟",
                attachment_type=allure.attachment_type.TEXT
            )

            # 延迟告警(不断言,只记录)— 局域网内通常 < 10ms
            if avg_ms is not None and avg_ms > 50:
                log_manager.logger.warning(
                    f"Ping 平均延迟偏高: {avg_ms}ms(局域网预期 < 50ms)"
                )
