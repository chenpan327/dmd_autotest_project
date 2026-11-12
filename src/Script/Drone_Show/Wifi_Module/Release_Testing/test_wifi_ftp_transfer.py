# coding: utf-8
"""
WiFi 模块测试 - FTP 文件传输链路(脚本层)

业务背景:
    FTP 是所有固件升级(companion / GPS / 电池)的文件传输通道。
    本测试项独立验证 FTP 链路可用性 + 串口文件完整性校验接口,作为后续固件升级
    测试的前置保障。固件升级本身的成功/失败路径由 test_wifi_firmware_alternating_upgrade.py
    和 test_wifi_upgrade_failure.py 分别覆盖。

测试项:
    1. FTP 文件上传 + 存在性校验(1KB 随机文件 → /cmpn/dmd_companion/)
    2. 串口 check_ftp_file 接口可调用且返回有效

中间件事实:
    - FTP 服务由 mt793x 中间件 lwip ftp server 提供,根目录 /cmpn/dmd_companion/
    - check_ftp_file 是 dmdcicd 串口命令,通过 FATFS 读文件并返回状态

残留清理:
    test_upload.bin 是 fixture 共享文件 (test_ftp_file_upload 上传, test_file_integrity_check 消费),
    两个用例跑完才能删。用 class-scoped autouse fixture 在 setup/teardown 各删一次远端文件,
    保证不论用例是否失败, 都不会在设备上残留。
"""
import os
import pytest
import allure


REMOTE_TEST_FILE = "/cmpn/dmd_companion/test_upload.bin"


@allure.epic("WiFi 模块测试")
@allure.feature("FTP 文件传输")
@allure.story("链路可用性")
class TestWifiFtpTransfer:
    """FTP 文件上传与完整性校验测试类"""


    @pytest.fixture(autouse=True, scope="class")
    def _cleanup_remote_test_file(self, ftp_session):
        """class 级 autouse fixture:setup + teardown 各删一次 REMOTE_TEST_FILE

        Why: test_upload.bin 被两个用例共享, 单用例清理会破坏另一个用例的前置。
        scope="class" 保证整组用例跑完才删, 且 setup 也清一遍以防止上次失败遗留。
        """
        ftp_session.reconnect()
        ftp_session.delete_file(REMOTE_TEST_FILE)
        yield
        try:
            ftp_session.reconnect()
            ftp_session.delete_file(REMOTE_TEST_FILE)
        except Exception as e:
            allure.attach(
                f"清理 {REMOTE_TEST_FILE} 失败: {e}", name="清理告警",
                attachment_type=allure.attachment_type.TEXT,
            )


    @allure.title("FTP 文件上传测试")
    @allure.description(
        "通过 FTP 上传 1KB 随机文件到 WiFi 模块 /cmpn/dmd_companion/,验证文件存在。"
        "FTP 链路是所有固件升级(companion/GPS/电池)的前置条件。"
        "远端文件 test_upload.bin 由 class fixture 在用例组结束统一清理。"
    )
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.tag("FTP", "文件上传", "链路测试")
    def test_ftp_file_upload(self, serial_session, ftp_session):
        """测试通过 FTP 上传文件到 WiFi 模块"""
        with allure.step("连接 FTP 服务器"):
            connected = ftp_session.connect()
            assert connected, "FTP 连接失败"

        with allure.step("准备 1KB 随机测试文件"):
            test_file = os.path.join(os.path.dirname(__file__), "test_upload.bin")
            with open(test_file, "wb") as f:
                f.write(os.urandom(1024))

        with allure.step(f"上传测试文件到 {REMOTE_TEST_FILE}"):
            success = ftp_session.upload_file(test_file, REMOTE_TEST_FILE)
            assert success, "文件上传失败"

        with allure.step("验证文件存在性"):
            exists = ftp_session.file_exists(REMOTE_TEST_FILE)
            assert exists, "上传的文件不存在"

        # 清理本地测试文件 (远端由 class fixture 统一清理)
        if os.path.exists(test_file):
            os.remove(test_file)


    @allure.title("文件完整性校验(串口 check_ftp_file)")
    @allure.description(
        f"通过串口命令检查远程文件 {REMOTE_TEST_FILE} 的完整性,"
        "验证 check_ftp_file 接口可调用且返回非 None。"
        "前置依赖:test_ftp_file_upload 已上传该文件。"
    )
    @allure.severity(allure.severity_level.NORMAL)
    @allure.tag("FTP", "完整性校验", "串口命令")
    def test_file_integrity_check(self, serial_session):
        """测试通过串口命令检查文件完整性"""
        with allure.step(f"检查远程文件 {REMOTE_TEST_FILE}"):
            result = serial_session.check_ftp_file(REMOTE_TEST_FILE)

        with allure.step("验证检查结果"):
            assert result is not None, "文件完整性检查失败(接口未响应或解析失败)"
