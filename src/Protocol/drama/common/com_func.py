# here saves python common functions
import hashlib
import json
import subprocess
import ctypes
import ctypes.wintypes
import math
import random
from datetime import datetime
import time
import base64
import os

try:
    from . import com_class
except ImportError:
    import com_class

from importlib import reload
reload(com_class)

# 创建DmdClip对象
try:
    from ..drone_show.DmdClip_pb2 import DmdClip, DroneInfo, DroneFrameData, DronePoseInfo, DmdVector3, DmdChannel, EDroneType
except ImportError as e:
    print(f"导入protobuf模块失败: {e}")
    from DmdClip_pb2 import DmdClip, DroneInfo, DroneFrameData, DronePoseInfo, DmdVector3, DmdChannel, EDroneType  # maya


try:
    # maya
    from google.protobuf import json_format
except:
    # blender
    pass

import logging
try:
    from utils.logger import logger
except ImportError:
    logger = logging.getLogger(__name__)

class Hardware:
    def __init__(self):
        self.disk_sn = ""
        self.baseboard_sn = ""
        self.cpu_sn = ""
        self.bios_sn = ""
        self.cs_uuid = ""

    def get_disk_sn(self):
        try:
            result = subprocess.check_output('wmic diskdrive get serialnumber', shell=True).decode()
            result = result.split('\n')[1].strip()
        except:
            result = '77777777'

        self.disk_sn = result

    def get_baseboard_sn(self):
        try:
            result = subprocess.check_output('wmic baseboard get serialnumber', shell=True).decode()
            result = result.split('\n')[1].strip()
        except:
            result = 'Default string'
        self.baseboard_sn = result

    def get_cpu_sn(self):
        try:
            result = subprocess.check_output('wmic cpu get processorid', shell=True).decode()
            result = result.split('\n')[1].strip()
        except:
            result = 'FFFFFFFFFFFFFFFF'

        self.cpu_sn = result

    def get_bios_sn(self):
        try:
            result = subprocess.check_output('wmic bios get serialnumber', shell=True).decode()
            result = result.split('\n')[1].strip()
        except:
            result = 'Default string'
        self.bios_sn = result

    def get_cs_uuid(self):
        try:
            result = subprocess.check_output('wmic csproduct get UUID', shell=True).decode()
            result = result.split('\n')[1].strip()
        except:
            result = 'AAAAAAAA-CCCC-0000-7777-CCCCCCCCCCCC'
        self.cs_uuid = result

    def encrypt(self, data):
        md5 = hashlib.md5()
        md5.update(data.encode('utf-8'))
        return md5.hexdigest()

    def get_machine_sn(self):
        self.get_disk_sn()
        self.get_baseboard_sn()
        self.get_cpu_sn()
        self.get_bios_sn()
        self.get_cs_uuid()

        sn_string = self.disk_sn + "_" + self.baseboard_sn + "_" + self.cpu_sn + "_" + self.bios_sn + "_" + self.cs_uuid

        return self.encrypt(sn_string)


class WMIHardware:
    """使用WMI库获取硬件信息的类，比subprocess调用wmic更可靠"""
    
    def __init__(self):
        self.disk_sn = ""
        self.baseboard_sn = ""
        self.cpu_sn = ""
        self.bios_sn = ""
        self.cs_uuid = ""
        self.mac_address = ""
        self.computer_name = ""
        self.username = ""
        
        # 初始化WMI连接（延迟导入wmi模块）
        try:
            import wmi
            self.wmi_conn = wmi.WMI()
        except ImportError:
            print("WMI库未安装，请运行: pip install wmi pywin32")
            self.wmi_conn = None
        except Exception as e:
            print(f"WMI初始化失败: {e}")
            self.wmi_conn = None

    def get_disk_sn(self):
        """使用WMI获取硬盘序列号"""
        if not self.wmi_conn:
            self.disk_sn = f"{self.get_computer_name()}_disk"
            return
            
        try:
            # 获取第一个物理硬盘的序列号
            for disk in self.wmi_conn.Win32_DiskDrive():
                if disk.SerialNumber:
                    serial = disk.SerialNumber.strip()
                    if serial and serial != "":
                        self.disk_sn = serial
                        return
            # 如果没有获取到序列号，使用MediaType
            for disk in self.wmi_conn.Win32_DiskDrive():
                if disk.MediaType:
                    self.disk_sn = f"DISK_{disk.MediaType}_{disk.Index}"
                    return
        except Exception as e:
            print(f"WMI获取硬盘序列号失败: {e}")
        
        # 备用方案：使用逻辑磁盘信息
        try:
            for disk in self.wmi_conn.Win32_LogicalDisk():
                if disk.VolumeSerialNumber:
                    self.disk_sn = f"VOL_{disk.VolumeSerialNumber}"
                    return
        except:
            pass
        
        # 最终备用
        self.disk_sn = f"{self.get_computer_name()}_disk"

    def get_baseboard_sn(self):
        """使用WMI获取主板序列号"""
        if not self.wmi_conn:
            self.baseboard_sn = "WMI_NOT_AVAILABLE"
            return
            
        try:
            for board in self.wmi_conn.Win32_BaseBoard():
                if board.SerialNumber:
                    serial = board.SerialNumber.strip()
                    if serial and serial not in ["", "Default string", "None"]:
                        self.baseboard_sn = serial
                        return
                # 备用：使用产品名称
                if board.Product:
                    product = board.Product.strip()
                    if product and product != "":
                        self.baseboard_sn = f"BOARD_{product}"
                        return
        except Exception as e:
            print(f"WMI获取主板序列号失败: {e}")
        
        # 备用方案：使用计算机系统信息
        try:
            for cs in self.wmi_conn.Win32_ComputerSystem():
                if cs.Model:
                    self.baseboard_sn = f"MODEL_{cs.Model}"
                    return
        except:
            pass
        
        self.baseboard_sn = "BASEBOARD_UNKNOWN"

    def get_cpu_sn(self):
        """使用WMI获取CPU序列号"""
        if not self.wmi_conn:
            self.cpu_sn = "CPU_UNKNOWN"
            return
            
        try:
            for cpu in self.wmi_conn.Win32_Processor():
                if cpu.ProcessorId:
                    processor_id = cpu.ProcessorId.strip()
                    if processor_id and processor_id != "":
                        self.cpu_sn = processor_id
                        return
                # 备用：使用CPU名称
                if cpu.Name:
                    cpu_name = cpu.Name.strip()
                    if cpu_name:
                        self.cpu_sn = f"CPU_{cpu_name.replace(' ', '_')}"
                        return
        except Exception as e:
            print(f"WMI获取CPU序列号失败: {e}")
        
        self.cpu_sn = "CPU_UNKNOWN"

    def get_bios_sn(self):
        """使用WMI获取BIOS序列号"""
        if not self.wmi_conn:
            self.bios_sn = "BIOS_UNKNOWN"
            return
            
        try:
            for bios in self.wmi_conn.Win32_BIOS():
                if bios.SerialNumber:
                    serial = bios.SerialNumber.strip()
                    if serial and serial not in ["", "Default string", "None"]:
                        self.bios_sn = serial
                        return
                # 备用：使用BIOS版本
                if bios.Version:
                    version = bios.Version.strip()
                    if version:
                        self.bios_sn = f"BIOS_{version}"
                        return
        except Exception as e:
            print(f"WMI获取BIOS序列号失败: {e}")
        
        self.bios_sn = "BIOS_UNKNOWN"

    def get_cs_uuid(self):
        """使用WMI获取计算机系统UUID"""
        if not self.wmi_conn:
            self.cs_uuid = "UUID_UNKNOWN"
            return
            
        try:
            for cs in self.wmi_conn.Win32_ComputerSystemProduct():
                if cs.UUID:
                    uuid_val = cs.UUID.strip()
                    if uuid_val and uuid_val not in ["", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"]:
                        self.cs_uuid = uuid_val
                        return
        except Exception as e:
            print(f"WMI获取系统UUID失败: {e}")
        
        # 备用方案：使用MAC地址生成
        try:
            import uuid
            node = uuid.getnode()
            self.cs_uuid = str(uuid.UUID(int=node))
            return
        except:
            pass
        
        self.cs_uuid = "UUID_UNKNOWN"

    def get_mac_address(self):
        """使用WMI获取MAC地址"""
        if not self.wmi_conn:
            try:
                import uuid
                mac = uuid.getnode()
                self.mac_address = ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))
                return
            except:
                self.mac_address = "MAC_UNKNOWN"
                return
                
        try:
            # 获取第一个物理网络适配器的MAC地址
            for nic in self.wmi_conn.Win32_NetworkAdapter():
                if nic.MACAddress and nic.PhysicalAdapter:
                    self.mac_address = nic.MACAddress
                    return
            # 如果没有物理适配器标记，获取任何有MAC地址的适配器
            for nic in self.wmi_conn.Win32_NetworkAdapter():
                if nic.MACAddress:
                    self.mac_address = nic.MACAddress
                    return
        except Exception as e:
            print(f"WMI获取MAC地址失败: {e}")
        
        # 备用方案
        try:
            import uuid
            mac = uuid.getnode()
            self.mac_address = ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))
        except:
            self.mac_address = "MAC_UNKNOWN"

    def get_computer_name(self):
        """使用WMI获取计算机名"""
        if not self.wmi_conn:
            try:
                import socket
                self.computer_name = socket.gethostname()
                return
            except:
                self.computer_name = "COMPUTER_UNKNOWN"
                return
                
        try:
            for cs in self.wmi_conn.Win32_ComputerSystem():
                if cs.Name:
                    self.computer_name = cs.Name
                    return
        except Exception as e:
            print(f"WMI获取计算机名失败: {e}")
        
        # 备用方案
        try:
            import socket
            self.computer_name = socket.gethostname()
        except:
            self.computer_name = "COMPUTER_UNKNOWN"

    def get_username(self):
        """获取当前用户名"""
        try:
            self.username = os.getenv('USERNAME') or os.getenv('USER') or "unknown_user"
        except:
            self.username = "unknown_user"

    def encrypt(self, data):
        """MD5加密"""
        md5 = hashlib.md5()
        md5.update(data.encode('utf-8'))
        return md5.hexdigest()

    def get_machine_sn(self):
        """获取机器唯一标识码"""
        self.get_disk_sn()
        self.get_baseboard_sn()
        self.get_cpu_sn()
        self.get_bios_sn()
        self.get_cs_uuid()
        self.get_mac_address()
        self.get_computer_name()
        self.get_username()

        # 组合所有可用的标识信息
        sn_string = "_".join([
            self.disk_sn,
            self.baseboard_sn,
            self.cpu_sn,
            self.bios_sn,
            self.cs_uuid
        ])

        return self.encrypt(sn_string)
    
    def get_hardware_info_dict(self):
        """返回所有硬件信息的字典"""
        return {
            "disk_sn": self.disk_sn,
            "baseboard_sn": self.baseboard_sn,
            "cpu_sn": self.cpu_sn,
            "bios_sn": self.bios_sn,
            "cs_uuid": self.cs_uuid,
            "mac_address": self.mac_address,
            "computer_name": self.computer_name,
            "username": self.username
        }


def confirm_three_choice_box(title, text):
    MB_YESNOCANCEL = 0x00000003  # Yes/No/Cancel message box
    ID_YES = 6     # Constant for "Yes" button
    ID_NO = 7      # Constant for "No" button
    ID_CANCEL = 2  # Constant for "Cancel" button

    # Call Windows API to display the MessageBox
    result = ctypes.windll.user32.MessageBoxW(0, text, title, MB_YESNOCANCEL)

    # Return 0, 1, 2 for Yes, No, Cancel
    if result == ID_YES:
        return 0
    elif result == ID_NO:
        return 1
    elif result == ID_CANCEL:
        return 2


def confirm_message_box(title, text):
    MB_YES_NO = 0x00000004
    ID_YES = 6
    ID_NO = 7

    result = ctypes.windll.user32.MessageBoxW(0, text, title, MB_YES_NO)

    return result == ID_YES

def notice_message_box(title, text):
    ctypes.windll.user32.MessageBoxW(0, text, title, 0x30)


def trans_drama3_color(r, g, b, w=50):
    r = max(0, r)
    r = min(255, r)
    g = max(0, g)
    g = min(255, g)
    b = max(0, b)
    b = min(255, b)

    result = bytes()
    result += int(0).to_bytes(1, byteorder="big")
    result += r.to_bytes(1, byteorder="big")
    result += g.to_bytes(1, byteorder="big")
    result += b.to_bytes(1, byteorder="big")
    result += w.to_bytes(1, byteorder="big")
    result += int(0).to_bytes(1, byteorder="big")
    result += int(0).to_bytes(1, byteorder="big")
    result += int(0).to_bytes(1, byteorder="big")
    result += int(0).to_bytes(1, byteorder="big")
    return result


def write_log(path, do_what, count, frames, custom, *args):
    # args = {"attr_name": value}
    write_something = dict()
    write_something["do_what"] = do_what
    write_something["count"] = count
    write_something["frames"] = frames
    write_something["custom"] = custom
    for arg in args:
        write_something.update(arg)

    with open(path, "a") as f:
        f.write(json.dumps(write_something) + "\n")


def get_windows_documents_path(pathID=5):
    buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(None, pathID, None, 0, buf)
    return buf.value

def remove_duplicate_sublists(lst):
    seen = set()
    result = []

    for sublist in lst:
        # 将子列表转换为元组，以便进行集合操作
        tuple_sublist = tuple(sorted(sublist))

        # 如果元组表示的子列表不在集合中，则将其添加到结果列表中
        if tuple_sublist not in seen:
            seen.add(tuple_sublist)
            result.append(sublist)

    return result


def remove_duplicate_sublists2(lst):
    # 使用集合存储已经出现过的子列表（元组形式）
    seen = set()

    # 存储结果的列表
    result = []

    for sublist in lst:
        # 将子列表转换为元组
        tuple_sublist = tuple(sublist)

        # 如果元组形式的子列表不在集合中，则将其添加到结果列表和集合中
        if tuple_sublist not in seen:
            seen.add(tuple_sublist)
            result.append(sublist)

    return result


def generate_random_sequence(a, b, x, y, continue_rate=0.4, gap_rate=0.6):
    result = []
    current_run = 0  # 当前连续数字计数
    current_gap = 0  # 当前间断计数

    time_list = range(a, b+1)
    effective_idx = [0 for i in range(b-a+1)]
    for idx in range(random.randint(1, x+y), b-a+1):
        if not result:
            # 初始化，直接加入第一个数字
            result.append(time_list[idx])
            effective_idx[idx] = 1
            current_run = 1
            continue

        if current_gap > y:
            result.append(time_list[idx])
            effective_idx[idx] = 1
            current_run = 1
            current_gap = 0
            continue

        if time_list[idx] == result[-1] + 1:
            # 连续数字
            if current_run < x and random.random() < continue_rate:  # 持续概率 越高越容易持续
                result.append(time_list[idx])
                effective_idx[idx] = 1
                current_run += 1
                current_gap = 0  # 重置间断计数
            else:
                continue  # 忽略超过连续限制的数字
        else:
            # 间断数字
            gap = time_list[idx] - result[-1] - 1
            if gap >= y or random.random() > gap_rate:  # 间断概率 越高越容易间断
                result.append(time_list[idx])
                effective_idx[idx] = 1
                current_gap = gap
                current_run = 1  # 重置连续计数
            else:
                continue  # 忽略超过间断限制的数字

    return effective_idx, result

def calculate_date_countdown(login_json_expired):
    # input: login_json_expired, ret_json["expired"]
    try:
        parsed_date = datetime.strptime(login_json_expired, "%Y-%m-%d %H:%M:%S")
    except Exception as e:
        return 100
    year, month, day = parsed_date.year, parsed_date.month, parsed_date.day

    current_time_struct = time.localtime()
    current_year, current_month, current_day = current_time_struct.tm_year, current_time_struct.tm_mon, current_time_struct.tm_mday

    current_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    target_date = parsed_date.replace(hour=0, minute=0, second=0, microsecond=0)
    delta = target_date - current_date
    days_diff = delta.days

    return days_diff

def judge_expired_time_and_notice(login_json_expired, notice_text):
    days_diff = calculate_date_countdown(login_json_expired)
    if days_diff <= 15 and days_diff % 2 == 1:
        notice_message_box("  ", notice_text)
    return days_diff

def read_json(json_path):
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
    except UnicodeDecodeError:
        with open(json_path, 'r', encoding='gbk') as f:  # 尝试使用'gbk'编码打开
            json_data = json.load(f)
    return json_data

def read_json_with_coding(json_path, coding):
    try:
        with open(json_path, 'r', encoding=coding) as f:
            json_data = json.load(f)
    except UnicodeDecodeError:
        notice_message_box("提示", f"文件编码错误: {json_path}, coding: {coding}")
        return None
    return json_data

def encode_to_base64(input_string):
    try:
        input_bytes = input_string.encode('utf-8')
        base64_bytes = base64.b64encode(input_bytes)
        base64_string = base64_bytes.decode('utf-8')
        return base64_string
    except Exception as e:
        print(f"Error encoding to Base64: {e}")
        return False

def decode_from_base64(base64_string):
    try:
        base64_bytes = base64_string.encode('utf-8')
        input_bytes = base64.b64decode(base64_bytes)
        original_string = input_bytes.decode('utf-8')
        return original_string
    except Exception as e:
        print(f"Error decoding from Base64: {e}")
        return False

def check_md5(file_path, md5):
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)

        return hash_md5.hexdigest() == md5
    except Exception as e:
        print(f"Error checking MD5: {e}")
        return False
    
def open_in_explorer(file_path):
    if os.path.exists(file_path):
        os.startfile(file_path)
    else:
        notice_message_box("提示", f"文件不存在: {file_path}")

def parse_dmdclip_proto_to_json(file_path):
    dmdclip_component = None
    try:
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return None
            
        # 读取二进制文件
        with open(file_path, 'rb') as f:
            binary_data = f.read()
            
        if not binary_data:
            return None
            
        # 尝试解析为DramaDTO消息
        try:
            dmdclip_component = parse_dmdclip_proto_direct(file_path)

            # with open(file_path + ".txt", "w") as f:
            #     f.write(json.dumps(dmdclip_component))
            #     notice_message_box("", f"已写入: {file_path}.txt")

            return dmdclip_component
            
        except Exception as e:
            print(f"解析DramaDTO失败: {e}")
        return None
        
    except Exception as e:
        return None
    return dmdclip_component
    
def dump_json_to_protobuf(json_path):
    """将JSON文件转换为protobuf格式
    Args:
        json_path: JSON文件路径
    Returns:
        protobuf文件路径,转换失败返回None
    """
    if not os.path.exists(json_path) or not json_path.endswith(".jsdm"):
        print(f"文件不存在或格式错误: {json_path}")
        return None
        
    try:
        # 读取JSON文件
        with open(json_path, 'r', encoding='gbk') as f:
            json_data = json.load(f)
            
        # 生成protobuf文件路径
        protobuf_path = json_path.replace(".jsdm", ".bin")
        
        # 转换为protobuf格式
        drama_dto = DmdClip()
        json_format.Parse(json.dumps(json_data), drama_dto)
        
        # 写入protobuf文件
        with open(protobuf_path, 'wb') as f:
            f.write(drama_dto.SerializeToString())
            
        print(f"成功转换为protobuf: {protobuf_path}")
        return protobuf_path
        
    except Exception as e:
        print(f"转换protobuf失败: {e}")
        return None

DRONE_TYPE_MAP = {
    "Y1": 18,
    "V3": 21,
    "V4": 31,
    "UNKOWN": 0
}

def jsdm_to_dmdclip(jsdm_path):
    """
    将jsdm格式转换为dmdclip格式
    Args:
        jsdm_path: jsdm文件路径
    Returns:
        str: 生成的dmdclip文件路径，失败返回None
    """
    if not os.path.exists(jsdm_path) or not jsdm_path.endswith(".jsdm"):
        logger.warning("文件不存在或格式错误: %s", jsdm_path)
        return None

    try:
        # 读取JSON文件
        last_exception = ""
        encodings_to_try = ['utf-8', 'utf-8-sig', 'gbk']
        for encoding in encodings_to_try:
            try:
                with open(jsdm_path, 'r', encoding=encoding) as f:
                    jsdm_data = json.load(f)
                    last_exception = ""
                    break
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                last_exception = e

        if last_exception:
            logger.warning(last_exception)
            return None
            
        # 验证数据结构
        if not isinstance(jsdm_data, dict):
            logger.warning("jsdm文件格式错误：根节点不是字典")
            return None
            
            
        drone_type_infos = jsdm_data.get("droneTypes", [])
        if not drone_type_infos:
            logger.warning("jsdm文件格式错误：droneTypes列表为空")
            return None
        
        dmdclip = DmdClip()
        
        # 设置基本信息
        dmdclip.Name = jsdm_data.get("name", "SP任务")
        logger.info("处理任务: %s", dmdclip.Name)
        
        # 处理无人机信息
        drone_no = 0
        for drone_type_info in drone_type_infos:
            drone_no += 1
            drone_info = DroneInfo()
            drone_info.No = int(drone_type_info.get("no", drone_no))
            drone_type = drone_type_info.get("type", "0")
            
            drone_info.Type = drone_type  # EDroneType枚举值
            dmdclip.DroneInfos.append(drone_info)

        color_infos = jsdm_data.get("channelFrames", [])
        pos_infos = jsdm_data.get("pointFrames", [])
        color_frames = len(color_infos)
        pos_frames = len(pos_infos)

        color_interval_frame = 1
        pos_interval_frame = 5
        if color_frames > 1:
            time_0 = color_infos[0]["time"]
            time_1 = color_infos[1]["time"]
            color_interval_frame = (time_1 - time_0) / 100
        if pos_frames > 1:
            time_0 = pos_infos[0]["time"]
            time_1 = pos_infos[1]["time"]
            pos_interval_frame = (time_1 - time_0) / 100

        need_frame = int(max(color_frames, pos_interval_frame*(pos_frames-1) + 1))
        for i in range(need_frame):
            frame_data = DroneFrameData()
            frame_data.Time = i * 100
            for drone_info in dmdclip.DroneInfos:
                frame_data.DroneDataInfos.append(DronePoseInfo(No=drone_info.No))
            dmdclip.ClipDatas.append(frame_data)

        for t in range(len(color_infos)):
            index = int(color_infos[t]['time'] / 100)
            for drone in range(len(color_infos[t]['channels'])):
                frame_data = dmdclip.ClipDatas[index]
                frame_data.DroneDataInfos[drone].Channel.C1 = int(color_infos[t]['channels'][drone]['c1'])
                frame_data.DroneDataInfos[drone].Channel.C2 = int(color_infos[t]['channels'][drone]['c2'])
                frame_data.DroneDataInfos[drone].Channel.C3 = int(color_infos[t]['channels'][drone]['c3'])
        
        for t in range(len(pos_infos)):
            index = int(pos_infos[t]['time'] / 100)
            for drone in range(len(pos_infos[t]['points'])):
                frame_data = dmdclip.ClipDatas[index]
                frame_data.DroneDataInfos[drone].Position.X = float(pos_infos[t]['points'][drone]['x'])
                frame_data.DroneDataInfos[drone].Position.Y = float(pos_infos[t]['points'][drone]['y'])
                frame_data.DroneDataInfos[drone].Position.Z = float(pos_infos[t]['points'][drone]['z'])
        
        # 生成输出文件路径
        output_path = jsdm_path.replace(".jsdm", "_" + str(generate_timestamp()) + ".bin")
        
        # 写入二进制文件
        with open(output_path, 'wb') as f:
            f.write(dmdclip.SerializeToString())
        return output_path
        
    except json.JSONDecodeError as e:
        logger.warning("JSON解析失败: %s", e)
        return None
    except Exception as e:
        logger.warning("转换失败: %s", e)
        import traceback
        traceback.print_exc()
        return None

def parse_dmdclip_proto_direct(file_path):
    """
    直接解析dmdclip protobuf文件，避免Base64编码问题
    
    Args:
        file_path: dmdclip文件路径
        
    Returns:
        dict: 解析后的数据字典
    """
    try:
        if not os.path.exists(file_path):
            return None
            
        with open(file_path, 'rb') as f:
            binary_data = f.read()
            
        if not binary_data:
            return None
            

        drama_dto = DmdClip()
        drama_dto.ParseFromString(binary_data)
        
        # 手动构建字典，避免Base64编码
        result = {
            "Name": drama_dto.Name,
            "DroneInfos": [],
            "ClipDatas": []
        }
        
        # 处理无人机信息
        for drone_info in drama_dto.DroneInfos:
            result["DroneInfos"].append({
                "NO": drone_info.No,
                "Type": drone_info.Type
            })
        
        # 处理帧数据
        for frame_data in drama_dto.ClipDatas:
            frame_dict = {
                "Time": frame_data.Time,
                "DroneDataInfos": []
            }
            
            for drone_data in frame_data.DroneDataInfos:
                drone_dict = {
                    "No": drone_data.No
                }
                
                # 处理位置数据
                if drone_data.HasField('Position'):
                    drone_dict["Position"] = {
                        "X": drone_data.Position.X,
                        "Y": drone_data.Position.Y,
                        "Z": drone_data.Position.Z
                    }
                
                # 处理颜色数据 - 直接转换为整数
                if drone_data.HasField('Channel'):
                    drone_dict["Channel"] = {
                        "C1": drone_data.Channel.C1,
                        "C2": drone_data.Channel.C2,
                        "C3": drone_data.Channel.C3
                    }
                
                frame_dict["DroneDataInfos"].append(drone_dict)
            
            result["ClipDatas"].append(frame_dict)
        
        return result
        
    except Exception as e:
        print(f"直接解析dmdclip失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def read_json(json_path):
    encodings_to_try = ['utf-8', 'utf-8-sig', 'gbk']
    last_exception = None

    for encoding in encodings_to_try:
        try:
            with open(json_path, 'r', encoding=encoding) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            last_exception = e

    if last_exception:
        # 如果所有编码都失败，则重新引发最后一个异常
        raise last_exception

def flat_dict_infos(dict_infos):
    if not dict_infos:
        return {}

    result = {}
    next_key = sorted(dict_infos.keys())[0]


    # 按原始键的顺序处理
    for key in sorted(dict_infos.keys()):
        value = dict_infos[key]

        if isinstance(value, list):
            if len(value) == 1:
                # 如果列表只有一个元素，直接使用原键
                if key not in result:
                    result[key] = [value[0]]
                else:
                    while next_key in result:
                        next_key += 1
                    result[next_key] = [value[0]]
                    next_key += 1
            else:
                # 如果列表有多个元素，第一个元素用原键，其余从原键+1开始分配
                for i, element in enumerate(value):
                    if i == 0:
                        # 如果原键已经被占用，重新分配
                        if key in result:
                            while next_key in result:
                                next_key += 1
                            result[next_key] = [element]
                            next_key += 1
                        else:
                            result[key] = [element]
                            next_key = key + 1  # 下一个键从原键+1开始
                    else:
                        # 找到下一个可用的键
                        while next_key in result:
                            next_key += 1
                        result[next_key] = [element]
                        next_key += 1
        else:
            # 非列表值直接使用原键
            result[key] = [value]
    return result

# dic = {1:[0], 2:[1], 3:[2], 8:[2,0,0], 9:[2,3]}
# print(flat_dict_infos(dic))


def parse_drm_temp_to_json(temp_path):
    json_data = {
        "authorName": "",
        "description": "",
        "dramaId": "",
        "dramaVersion": "",
        "droneCount": 0,
        "drones": [],
        "map": {},
        "payloadFps": 0,
        "pointFps": 0,
        "sceneName": "",
        "segmInfos": [],
    }
    try:
        if not os.path.exists(temp_path):
            print(f"文件不存在: {temp_path}")
            return None

        with open(temp_path, 'rb') as f:
            binary_data = f.read()

        if not binary_data:
            print(f"文件为空: {temp_path}")
            return None

        from protobuf.Drama3_pb2 import Drama3
        drama3 = Drama3()
        drama3.ParseFromString(binary_data)

        json_data["authorName"] = drama3.authorName
        json_data["description"] = drama3.description
        json_data["dramaId"] = drama3.dramaId
        json_data["dramaVersion"] = drama3.dramaVersion
        json_data["droneCount"] = drama3.droneCount
        
        for drone in drama3.drones:
            cur_drone_info = {
                "id": drone.id,
                "type": drone.droneType,
                "return_type": drone.returnType,
                "play_time": drone.playTime,
                "points": list(),
                "poses": list(),
                "colors": list(),
                "novas": list(),
                "fireworks": list(),
                "lanterns": list(),
                "gimbals": list(),
                "lazers": list(),
            }
            
            for point in drone.positionKeyFrames:
                cur_drone_info["points"].append({
                    "frame": point.frame,
                    "x": point.x,
                    "y": point.y,
                    "z": point.z
                })
            for color in drone.lightKeyFrame:
                cur_drone_info["colors"].append({
                    "frame": color.frame,
                    "r": color.lights.r,
                    "g": color.lights.g,
                    "b": color.lights.b
                })

            for nova in drone.novaKeyFrame:
                cur_drone_info["novas"].append({
                    "frame": nova.frame,
                    "power": nova.novas.power
                })

            for fireworks in drone.fireworksKeyFrame:
                cur_frame_firework_info = {
                    "frame": fireworks.frame,
                    "firedPort": fireworks.fireworks.firedPort,
                    "fireworksAngles": list()
                }

                for angle in fireworks.fireworks.fireworkAngles:
                    cur_frame_firework_info["fireworksAngles"].append({
                        "channel": angle.channel,
                        "angle": angle.angle
                    })

                cur_drone_info["fireworks"].append(cur_frame_firework_info)

            for lantern in drone.lanternKeyFrame:
                cur_drone_info["lanterns"].append({
                    "frame": lantern.frame,
                    "isOn": lantern.lanterns.isOn
                })

            for gimbal in drone.gimbalKeyFrame:
                cur_drone_info["gimbals"].append({
                    "frame": gimbal.frame,
                    "pitch": gimbal.gimbals.pitch,
                    "roll": gimbal.gimbals.roll,
                    "yaw": gimbal.gimbals.yaw
                })

            for lazer in drone.lazerKeyFrame:
                cur_drone_info["lazers"].append({
                    "frame": lazer.frame,
                    "r": lazer.lazers.r,
                    "g": lazer.lazers.g,
                    "b": lazer.lazers.b
                })
            for pose in drone.poseKeyFrames:
                cur_drone_info["poses"].append({
                    "frame": pose.frame,
                    "pitch": pose.pitch,
                    "roll": pose.roll,
                    "yaw": pose.yaw
                })

            json_data["drones"].append(cur_drone_info)

        json_data["map"] = drama3.map
        json_data["payloadFps"] = drama3.payloadFps
        json_data["pointFps"] = drama3.pointFps
        json_data["sceneName"] = drama3.sceneName
        json_data["segmInfos"] = drama3.segmInfos
        return json_data
    except Exception as e:
        print(f"解析drm失败: {e}")
        return None


def judge_high_power_times(high_power_time_table, 
                           max_hl_sustain_frames=20, high_light_interval_times=5,
                           max_dz_sustain_frames=15, dazzle_interval_times=8,
                           max_total_high_power_frames=-1,
                           prepare_high_power_frames=0):
    # high_light_port_time_table: [[frame, power_value], ...]
    error_msg = ""
    warning_msg = ""

    if not high_power_time_table:
        return "", "", 0

    # if high_light_port_time_table[0][1] != 2 or high_light_port_time_table[-1][1] != 2:
    #     error_msg += "\t[1 start end error]: high light command doesn't start or end with [0, 0, 0]\n"

    open_close_pairs = []  # HighPowerTimes

    high_light_open_stack = []
    is_open = False
    cur_type = com_class.HighPowerPort.HIGH_LIGHT

    for item in high_power_time_table:
        cur_frame = item[0]
        cur_power_value = item[1]

        if cur_power_value >= 1:
            if is_open:
                warning_msg += f"  [1 dazzle command blocked]: at frame {cur_frame}\n"
                continue
            cur_type = com_class.HighPowerPort.DAZZLE
            high_light_open_stack.append(cur_frame)
            is_open = True

        elif cur_power_value > 0.55:
            if is_open:
                warning_msg += f"[1 high light command blocked]: at frame {cur_frame}\n"
                continue
            cur_type = com_class.HighPowerPort.HIGH_LIGHT
            high_light_open_stack.append(cur_frame)
            is_open = True
        # elif cur_port == com_class.HighPowerPort.CLOSE:
        else:
            if is_open and high_light_open_stack:
                new_item = com_class.HighPowerTimes()
                new_item.PowerType=cur_type
                new_item.s_time=high_light_open_stack.pop()
                new_item.e_time=cur_frame
                open_close_pairs.append(new_item)
            is_open = False

    total_enable_frames = prepare_high_power_frames

    if is_open or high_light_open_stack:
        error_msg += f"  [2 high power not closed]: at frame {','.join(list(map(str, high_light_open_stack)))}\n"
        total_enable_frames += 9999999
        return error_msg, warning_msg, total_enable_frames

    for pair in open_close_pairs:
        if pair.PowerType == com_class.HighPowerPort.HIGH_LIGHT:
            max_sustain_frames = max_hl_sustain_frames
            interval_times = high_light_interval_times
        elif pair.PowerType == com_class.HighPowerPort.DAZZLE:
            max_sustain_frames = max_dz_sustain_frames
            interval_times = dazzle_interval_times
        else:
            continue
        if pair.e_time - pair.s_time > max_sustain_frames: # * 1.1:
            error_msg += f"  [3 over max sustain time {max_sustain_frames}]: at {pair.s_time} to {pair.e_time}\n"
            continue
        # if pair.e_time - pair.s_time > max_sustain_frames:
        #     warning_msg += f"  [3 over max sustain time {max_sustain_frames}]: at {pair.s_time} to {pair.e_time}\n"
        total_enable_frames += pair.e_time - pair.s_time

    for i in range(len(open_close_pairs) - 1):
        need_interval_frames = (open_close_pairs[i].e_time - open_close_pairs[i].s_time) * interval_times
        if open_close_pairs[i + 1].s_time - open_close_pairs[i].e_time < need_interval_frames: # * 1.1:
            warning_msg += f"  [4 over high light interval {need_interval_frames}]: at {open_close_pairs[i].e_time} to {open_close_pairs[i + 1].s_time}\n"
        # if open_close_pairs[i + 1].s_time - open_close_pairs[i].e_time < need_interval_frames:
        #     error_msg += f"  [4 over high light interval {need_interval_frames}]: at {open_close_pairs[i].e_time} to {open_close_pairs[i + 1].s_time}\n"
    
    if max_total_high_power_frames != -1 and total_enable_frames > max_total_high_power_frames:
        error_msg += f"  [5 over max total high power frames {max_total_high_power_frames}]: total enable frames={total_enable_frames} > {max_total_high_power_frames}\n"

    return error_msg, warning_msg, total_enable_frames

def generate_timestamp(unit="s"):
    if unit == "s":
        return int(time.time())
    elif unit == "ms":
        return int(time.time() * 1000)
    elif unit == "us":
        return int(time.time() * 1000000)
    elif unit == "ns":
        return int(time.time() * 1000000000)
    else:
        return time.time()

def format_timestamp(timestamp):
    timestamp = float(timestamp)
    if timestamp > 9999999999:
        timestamp /= 1000.0
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))