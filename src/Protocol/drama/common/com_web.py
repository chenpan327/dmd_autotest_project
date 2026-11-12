import os
import zipfile
import requests
import sys
import functools
from email.utils import parsedate_to_datetime

try:
    from . import com_class
except:
    import com_class

ISONLINEENV = True

class DramaEditorIdentify:
    def __init__(self):
        self.http = com_class.HTTP()
        global ISONLINEENV
        if ISONLINEENV:
            self.http.set_ONLINE()
        else:
            self.http.set_TEST()

        self.token = ""
        self.token_head = ""
        self.token_type = ""
        self.refresh_token = ""
        self.expires_in = ""

    def get_login_token(self, username, password):
        url = f"{self.http.http_prefix}{self.http.server}{self.http.port}/oauth/token"
        payload = {
            'username': (None, username),
            'password': (None, password),
        }

        headers = {
        }

        try:
            response = requests.post(url, headers=headers, files=payload, timeout=(10, 3), verify=True)
            content = response.json()
            if response.status_code == 200:
                content["ret_code"] = content["code"]
                if content['data']:
                    self.token = content['data'].get('token', '')
                    self.token_type = content['data'].get('tokenHead', '')
                    self.refresh_token = content['data'].get('refreshToken', '')
                    self.expires_in = content['data'].get("expiresIn", 0)
            return content
        except requests.exceptions.RequestException as e:
            return {"code": 203}

    def get_user_details(self, machine_number, drama_editor_type, user_version):
        url = f"{self.http.http_prefix}{self.http.server}{self.http.port}/api/v1/de/userDetails"
        payload = {
            'machineNumber': (None, machine_number),
            'dramaEditorType': (None, drama_editor_type),
            'version': (None, user_version)
        }

        headers = {
            'Authorization': f"{self.token_type} {self.token}"
        }

        try:
            response = requests.get(url, headers=headers, files=payload, timeout=(10, 3), verify=True)
            content = response.json()
            return content
        except requests.exceptions.RequestException as e:
            return {"code": -1}

    def post_active(self, machine_number, drama_editor_type):
        url = f"{self.http.http_prefix}{self.http.server}{self.http.port}/api/v1/de/activationRecords"
        payload = {
            'machineNumber': (None, machine_number),
            'dramaEditorType': (None, drama_editor_type),
        }

        headers = {
            'Authorization': f"{self.token_type} {self.token}"
        }

        try:
            response = requests.post(url, headers=headers, files=payload, timeout=(10, 3), verify=True)
            content = response.json()
            return content
        except requests.exceptions.RequestException as e:
            return {"code": -1}

    def get_drones_param(self, drone_types):
        value_str = ",".join(list(map(str, drone_types)))
        url = f"{self.http.http_prefix}{self.http.server}{self.http.port}/api/v1/drone/typeDetails"
        payload = {
            "typeValues": (None, value_str)
        }

        headers = {
            'Authorization': f"{self.token_type} {self.token}"
        }

        try:
            response = requests.get(url, headers=headers, files=payload, timeout=(10, 3), verify=True)
            content = response.json()
            return content
        except requests.exceptions.RequestException as e:
            return {"code": -1}

    def get_latest_version(self, drama_editor_version):
        url = f"{self.http.http_prefix}{self.http.server}{self.http.port}/api/v1/de/version"
        payload = {
            "dramaEditorType": (None, drama_editor_version)
        }
        headers = {
            'Authorization': f"{self.token_type} {self.token}"
        }
        try:
            response = requests.get(url, headers=headers, files=payload, timeout=(10, 3), verify=True)
            content = response.json()
            self.version = content["data"]["version"]
            return content
        except requests.exceptions.RequestException as e:
            return {"code": -1}

    def get_update(self, version, path, operations):
        url = f"{self.http.http_prefix}{self.http.server}{self.http.port}/api/v1/de/files"
        
        data = {
            'version': version
        }
        headers = {
            'Authorization': f"{self.token_type} {self.token}"
        }

        url_file = requests.get(url, headers=headers, params=data, stream=True, timeout=(10, 15))
        file_size = round((int(url_file.headers.get('content-length', 0)) / 1024) / 1024, 1)

        if os.path.isfile(path):
            os.remove(path)

        downloaded = 0
        for data in url_file.iter_content(chunk_size=1024000):
            downloaded += 0.975
            key = f'下载文件:{round(downloaded,1)}mb/{file_size}mb'
            operations[key] = functools.partial(self.download_file, path, data)

        # Print a summary of the operations
        print("Operations summary:")
        for key in operations:
            print(f"Operation: {key}")

        return operations
    
    def get_update_maya(self, version, path):
        url = f"{self.http.http_prefix}{self.http.server}{self.http.port}/api/v1/de/files"
        
        headers = {
            'Authorization': f"{self.token_type} {self.token}"
        }
        
        data = {
            'version': version
        }
        
        try:
            response = requests.get(url, headers=headers, params=data, stream=True)
            response.raise_for_status()  # Raise an exception for HTTP errors
            
            # Process the response as needed
            # For example, you can write the response content to a file
            with open(path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024000):
                    if chunk:
                        f.write(chunk)
            
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")
            return False
        
    def download_file(self, path, data):
        with open(path, 'ab') as f:
            f.write(data)
            
    def unzip(self, dow_path, path):
        path = os.path.join(path, "update")
        with zipfile.ZipFile(dow_path, 'r') as zip_ref:
            zip_ref.extractall(path)

    def get_network_time(self):
        try:
            response = requests.head('https://www.baidu.com', timeout=5)
            date_str = response.headers['Date']
            dt = parsedate_to_datetime(date_str)
            return dt.date()
        except Exception as e:
            return None


    def get_user_unfinished_tasks(self):
        try:

            url = f"{self.http.http_prefix}{self.http.server}{self.http.port}/dmd-platform/platform/dramaTask/getUndoTaskList"
            print(url)
            headers = {
                'Authorization': f"{self.token_type} {self.token}"
            }

            response = requests.get(url, headers=headers)
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")
            return False