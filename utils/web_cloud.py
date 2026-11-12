import json
import os
import requests
from utils.common import load_config
from utils.logger import logger


def get_captcha():
    conf_info = load_config().get("Cloud_Platform_Ui", {})
    key = conf_info['key']
    url = conf_info['api_url'] + f'/sys/randomImage/{key}'
    response = requests.get(url)
    captcha = None
    if response.status_code == 200:
        captcha = response.json().get('message')
        return captcha
    else:
        return 0


def load_test_data(file_name, key):
    base_path = os.path.dirname(os.path.dirname(__file__))
    file_path = os.path.join(base_path, file_name)

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data[key]
