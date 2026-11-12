import json
import os

import requests
from jsonschema import validate, ValidationError
from utils.logger import log_manager
import openpyxl
from utils.web_cloud import load_config
from urllib.parse import urlencode
from jsonpath_ng.ext import parse

current_path = os.path.dirname(os.path.abspath(__file__))
root_path = os.path.split(os.path.split(os.path.dirname(current_path))[0])[0]
root_path = root_path.replace('\\', '\\\\')

# 延迟加载配置，避免模块导入时失败
cloud_info = None


def get_cloud_info():
    global cloud_info
    if cloud_info is None:
        cloud_info = load_config().get("Cloud_Platform_Api", {})
        if cloud_info is None:
            log_manager.logger.error("未找到 Cloud_Platform_Api 配置")
            raise ValueError("未找到 Cloud_Platform_Api 配置")
    return cloud_info


class APIBase:

    def __init__(self):
        self.session = requests.Session()
        self.cloud_info = get_cloud_info()
        self.domain = self.cloud_info['domain']
        self.username = self.cloud_info.get('test_user', 'alan')
        self.password = self.cloud_info.get('test_pwd', 'dmd@2025')
        self.file_path = root_path + '\\file\\excel\\api_test_data.xlsx'
        self.test_data = {}

    # =========================
    # 读取 Excel
    # =========================
    def read_excel(self, sheet_name):

        wb = openpyxl.load_workbook(self.file_path)
        sheet = wb[sheet_name]

        headers = [cell.value for cell in sheet[1]]

        execute_index = headers.index("execute")

        for row in sheet.iter_rows(min_row=2):

            if row[execute_index].value == 1:
                continue

            row_data = {}

            for header, cell in zip(headers, row):

                value = cell.value

                if header in ["data", "response_json_schema"] and value:
                    try:
                        value = json.loads(value)
                    except Exception:
                        log_manager.logger.warning(f"{header} 不是合法JSON: {value}")

                row_data[header] = value

            title = row_data["title"]
            self.test_data[title] = row_data

    # =========================
    # 获取 case 数据
    # =========================
    def _get_params(self, title):

        if title not in self.test_data:
            raise ValueError(f"Excel中未找到case: {title}")
        return self.test_data[title]

    # =========================
    # 统一请求入口
    # =========================
    def request(self, method, uri, headers=None, js_schema=None, files=None, **kwargs):
        url = self.domain + uri
        headers = headers or {}

        log_manager.logger.info(f"< request url > {url}")
        log_manager.logger.info(f"< request headers >\n{json.dumps(headers, indent=2, ensure_ascii=False)}")
        log_manager.logger.info(f"< request params >\n{json.dumps(kwargs, indent=2, ensure_ascii=False)}")

        opened_files = {}
        upload_files = None

        # ===========================
        # 处理上传文件
        # ===========================
        if files:
            upload_files = {}

            for field_name, file_info in files.items():
                abs_path = file_info
                f = open(abs_path, "rb")

                opened_files[field_name] = f
                upload_files[field_name] = f

            kwargs["files"] = upload_files

        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                **kwargs
            )
        finally:
            for f in opened_files.values():
                try:
                    f.close()
                except Exception:
                    pass
        return self._handle_response(response, js_schema)

    # =========================
    # 自动处理请求参数
    # =========================
    def build_request(self, data_set, dynamic_args=None, jsonpath_args=None):
        method = data_set["method"].lower()
        uri = data_set["uri"]

        headers = data_set.get("requests_header")

        if headers:
            headers = json.loads(headers)

        request_data = (data_set.get("data") or {}).copy()

        if dynamic_args:
            request_data.update(dynamic_args)

        if jsonpath_args:
            for item in jsonpath_args:
                path, value = item[0], item[1]
                jp = parse(path)
                if jp.find(request_data):
                    jp.update(request_data, value)
                else:
                    log_manager.logger.warning(
                        f"JSONPath 未匹配: {path}，跳过修改"
                    )

        params_key = data_set["params_key"]

        if headers and "x-www-form-urlencoded" in str(headers):
            request_data = urlencode(request_data)

        params = {}
        if request_data:
            params[params_key] = request_data

        # params = {params_key: request_data}

        return {
            "method": method,
            "uri": uri,
            "headers": headers,
            "js_schema": data_set.get("response_json_schema"),
            **params
        }

    def _handle_response(self, response, js_schema=None):
        """
        统一处理 response
        """

        log_manager.logger.info(f"< response status > {response.status_code}")

        # 1. 判断状态码
        if response.status_code != 200:
            log_manager.logger.error(response.text)
            raise AssertionError(
                f"接口请求失败: status_code={response.status_code}"
            )

        # 2. 转json
        try:
            res_json = response.json()
        except Exception:
            log_manager.logger.error(response.text)
            raise AssertionError("返回内容不是合法JSON")

        log_manager.logger.info(f"< response data >\n{json.dumps(res_json, indent=2, ensure_ascii=False)}")

        # 3. schema校验
        if js_schema:
            try:
                validate(instance=res_json, schema=js_schema)
            except ValidationError as e:
                log_manager.logger.error(f"JSON Schema 校验失败: {e.message}")
                raise AssertionError(f"JSON Schema 校验失败: {e.message}")

        # 4. 返回json
        return res_json

    def assert_response(self, response, assertions):

        """
        assertions:
        [
            ("$.code", "eq", 0),
            ("$.data.total", "gt", 0),
            ("$.msg", "contains", "success")
        ]
        """
        log_manager.logger.info(f"< assertions info > {assertions}")

        for item in assertions:
            json_path = item[0]
            op = item[1]
            expect = item[2] if len(item) > 2 else None

            matches = parse(json_path).find(response)

            # 多值匹配: [*] 等 path 匹配到多个结果时收集为列表
            if len(matches) > 1:
                actual = [m.value for m in matches]
            else:
                actual = matches[0].value if matches else None

            # =====================
            # eq
            # =====================
            if op == "eq":
                assert actual == expect, \
                    f"{json_path}: {actual} != {expect}"

            # =====================
            # neq
            # =====================
            elif op == "neq":
                assert actual != expect, \
                    f"{json_path}: {actual} == {expect}"

            # =====================
            # contains
            # =====================
            elif op == "contains":
                assert expect in actual, \
                    f"{expect} not in {actual}"

            # =====================
            # gt
            # =====================
            elif op == "gt":
                assert actual > expect, \
                    f"{actual} <= {expect}"
            # =====================
            # lt
            # =====================
            elif op == "lt":
                assert actual < expect, \
                    f"{actual} >= {expect}"

            # =====================
            # len_eq
            # =====================
            elif op == "len_eq":
                assert hasattr(actual, "__len__"), \
                    f"{json_path} has no len()"

                assert len(actual) == expect, \
                    f"{json_path} length {len(actual)} != {expect}"

            # =====================
            # len_gt
            # =====================
            elif op == "len_gt":
                assert hasattr(actual, "__len__"), \
                    f"{json_path} has no len()"

                assert len(actual) > expect, \
                    f"{json_path} length {len(actual)} < {expect}"

            # =====================
            # is_none
            # =====================
            elif op == "is_none":
                assert actual is None, \
                    f"{json_path} is not None"

            # =====================
            # not_none
            # =====================
            elif op == "not_none":
                assert actual is not None, \
                    f"{json_path} is None"
