import os

import requests
import yaml

current_path = os.path.dirname(os.path.abspath(__file__))
root_path = os.path.dirname(current_path)


def get_captcha():
    key = '1629428467008'
    url = f'https://cloud-gateway-uat.dmduav.com/sys/randomImage/{key}'  # https://cloud-gateway-uat.dmduav.com
    response = requests.get(url)
    captcha = None
    if response.status_code == 200:
        captcha = response.json().get('message')
        return captcha
    else:
        return 0


def get_data(file_path):
    with open(file_path) as f:
        data = yaml.safe_load(f)
        re = data.get("web")

    return re


# print("captcha:",captcha)
if __name__ == '__main__':
    a = get_captcha()
    print(a)
    # cls = get_data(r"C:\Users\dmd\Desktop\pythonProject\dmd_autotest_project\src\Physical\WebBase\web_info.yaml")
    # print(cls)
