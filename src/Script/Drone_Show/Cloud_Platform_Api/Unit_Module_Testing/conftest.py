import time

import pytest
from utils.logger import log_manager
import yaml
import os, sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)


def load_case_data(method_name):
    with open(BASE_DIR + r"\Unit_Module_Testing\test_data.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get(method_name, [])


def build_parametrize(method_name):
    cases = load_case_data(method_name)
    params = []
    ids = []
    for case in cases:
        params.append(
            (
                case.get("args", {}),
                case.get("jsonpath_args", []),
                case.get("expected", [])
            )
        )
        ids.append(case.get("name", "unknown"))
    return params, ids


def data_driver(method_name):
    params, ids = build_parametrize(method_name)
    return pytest.mark.parametrize(
        "args,jsonpath_args,expected",
        params,
        ids=ids
    )


@pytest.fixture(autouse=True)
def test_setup_teardown(request: pytest.FixtureRequest):
    log_manager.logger.info(f">>> \n测试开始：{request.node.name}")
    yield
    log_manager.logger.info(f">>> 测试结束：{request.node.name}")
    log_manager.attach_log_to_allure()
    time.sleep(0.5)
