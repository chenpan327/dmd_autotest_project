import time

import pytest
from utils.logger import log_manager
import yaml
import os, sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)


def load_case_data(method_name):
    with open(BASE_DIR + r"\Release_Testing\test_data.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get(method_name, [])


def build_parametrize(method_name, index=1):
    cases = load_case_data(method_name)
    if isinstance(cases, list):
        for case in cases:
            if case.get("index") == index:
                args = case.get("args", {})
                expected = case.get("expected", [])
                jsonpath_args = case.get("jsonpath_args", [])
                if jsonpath_args:
                    return args, jsonpath_args, expected
                return args, expected
        raise ValueError(f"未找到 {method_name} 中 index={index} 的用例")


@pytest.fixture(autouse=True)
def test_setup_teardown(request: pytest.FixtureRequest):
    log_manager.logger.info(f">>> \n测试开始：{request.node.name}")
    yield
    log_manager.logger.info(f">>> 测试结束：{request.node.name}")
    log_manager.attach_log_to_allure()
    time.sleep(0.5)
