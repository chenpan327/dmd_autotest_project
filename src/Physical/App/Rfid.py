import sys
import time
import uiautomator2 as u2


class RFID:
    def __init__(self, device=None):
        self.d = u2.connect(device)

    def unlock_screen(self):
        # 上滑解锁设备
        if not self.d.info['screenOn']:
            self.d.screen_on()
            self.d.swipe_ext("up", scale=0.9)
            time.sleep(3)

    def start_app(self, package_name):
        # 启动app，如果已启动先关闭
        self.d.app_clear(package_name)
        self.d.app_start(package_name, stop=True)

    def stop_app(self, package_name):
        # 关闭app
        self.d.app_stop(package_name)

    def click(self, xpath):
        # 跟据xpath信息点击对应元素
        self.d.xpath(xpath).click(timeout=10)
        time.sleep(0.7)

    def input(self, xpath, content):
        # 在指定元素中输入内容
        self.d.xpath(xpath).click(timeout=10)
        self.d.send_keys(content, clear=True)
        time.sleep(0.7)


    def user_login(self, usr, pwd):
        # 用户登录
        self.input('//*[@resource-id="com.example.uhf_rfid.tes:id/username_input"]', usr)
        self.input('//*[@resource-id="com.example.uhf_rfid.tes:id/password_input"]', pwd)
        self.click("//*[@text='登录']")

