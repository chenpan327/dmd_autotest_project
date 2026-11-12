import json
import os
from .Drama3_pb2 import Drama3
# from Drama3_pb2_new import Drama3
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import zipfile
import io
from utils.logger import logger

secret_key = b"Dmd_Drama_Editor_Plugin_Aes_Key!"
secret_iv = b"IdontkonwanyIVs!"

def _safe_str(value):
    """将 protobuf bytes 字段安全解码为 str。

    protobuf 7.x 对 string 字段强制校验 UTF-8。Drama3_pb2.py 已将
    string 字段改为 bytes 类型（参见 mavlink_monitor 中的本地副本），
    因此读取时可能得到 bytes。本函数将其解码为 str，非 UTF-8 字节
    用 U+FFFD 替换。
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class DramaReader:
    """读取 DRM/TMP 文件并解析为 JSON 结构的类"""

    def __init__(self):
        self.data = {
            "drama3": {
                "dramaId": "",
                "droneCount": 0,
                "sceneName": "",
                "description": "",
                "payloadFps": 0,
                "pointFps": 0,
                "dramaVersion": "",
                "drones": [],
                "map": {
                    "rotate": 0.0,
                    "name": "",
                    "widthScale": 0.0,
                    "heightScale": 0.0,
                    "radius": 0.0,
                    "x": 0.0,
                    "y": 0.0,
                    "z": 0.0,
                    "lon": 0.0,
                    "lat": 0.0,
                },
                "segmInfos": [],
                "authorName": "",
            }
        }
        self.file_path = ""

    def read(self, file_path):
        """读取并解析 DRM/TMP 文件

        Args:
            file_path: 文件路径（.tmp 或已解密的 .drm）

        Returns:
            dict: 解析后的 JSON 数据

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件为空或解析失败
        """
        self.file_path = file_path

        output_path = self.decrypt_drm_to_tmp(file_path)
        logger.info(f"解密成功: {output_path}")
        
        if not os.path.exists(output_path):         
            logger.error(f"文件不存在: {output_path}")  
            raise FileNotFoundError(f"文件不存在: {output_path}")

        with open(output_path, "rb") as f:
            binary_data = f.read()

        if not binary_data:
            logger.error(f"文件为空: {output_path}")
            raise ValueError(f"文件为空: {output_path}")

        drama3 = Drama3()
        try:
            drama3.ParseFromString(binary_data)
        except Exception as e:
            logger.error(f"解析失败: {e}")
            raise ValueError(
                f"解析失败: {e}\n"
                f"提示: .drm 文件可能是加密/压缩格式，需要先转换为 .tmp 格式。"
                f"请使用 TMP 格式的文件进行解析。"
            )

        self._parse_drama3(drama3)
        return self.data

    def _parse_drama3(self, drama3):
        """解析 Drama3 对象"""
        root = self.data["drama3"]

        root["dramaId"] = _safe_str(drama3.dramaId)
        root["droneCount"] = drama3.droneCount
        root["sceneName"] = _safe_str(drama3.sceneName)
        root["description"] = _safe_str(drama3.description)
        root["payloadFps"] = drama3.payloadFps
        root["pointFps"] = drama3.pointFps
        root["dramaVersion"] = drama3.dramaVersion
        root["authorName"] = _safe_str(drama3.authorName)

        # 解析无人机列表
        for drone in drama3.drones:
            root["drones"].append(self._parse_drone(drone))

        # 解析地图信息
        self._parse_map_info(drama3.map)

        # 解析段信息
        for segm_info in drama3.segmInfos:
            root["segmInfos"].append({
                "startFrame": segm_info.startFrame,
                "endFrame": segm_info.endFrame,
                "type": segm_info.type,
                "description": _safe_str(segm_info.description),
            })

    def _parse_drone(self, drone):
        """解析单个无人机数据"""
        drone_data = {
            "id": drone.id,
            "droneType": drone.droneType,
            "returnType": drone.returnType,
            "playTime": drone.playTime,
            "positionKeyFrames": [],
            "lightKeyFrames": [],
            "novaKeyFrames": [],
            "fireworksKeyFrames": [],
            "lanternKeyFrames": [],
            "gimbalKeyFrames": [],
            "lazerKeyFrames": [],
            "poseKeyFrames": [],
            "totalPointFrameCount": drone.totalPointFrameCount,
            "totalPayloadFrameCount": drone.totalPayloadFrameCount,
        }

        # 解析位置关键帧
        logger.info(f"位置关键帧数量: {len(drone.positionKeyFrames)}")
        for point in drone.positionKeyFrames:
            drone_data["positionKeyFrames"].append({
                "frame": point.frame,
                "x": point.x,
                "y": point.y,
                "z": point.z,
            })

        # 解析灯光关键帧
        logger.info(f"灯光关键帧数量: {len(drone.lightKeyFrame)}")
        for light in drone.lightKeyFrame:
            drone_data["lightKeyFrames"].append({
                "frame": light.frame,
                "lights": {
                    "r": light.lights.r,
                    "g": light.lights.g,
                    "b": light.lights.b,
                },
            })

        # 解析Nova关键帧
        logger.info(f"Nova关键帧数量: {len(drone.novaKeyFrame)}")
        for nova in drone.novaKeyFrame:
            drone_data["novaKeyFrames"].append({
                "frame": nova.frame,
                "novas": {
                    "power": nova.novas.power,
                },
            })

        # 解析烟花关键帧
        logger.info(f"烟花关键帧数量: {len(drone.fireworksKeyFrame)}")
        for fireworks in drone.fireworksKeyFrame:
            firework_angles = []
            for angle in fireworks.fireworks.fireworkAngles:
                firework_angles.append({
                    "channel": angle.channel,
                    "angle": angle.angle,
                })

            drone_data["fireworksKeyFrames"].append({
                "frame": fireworks.frame,
                "fireworks": {
                    "firedPort": fireworks.fireworks.firedPort,
                    "fireworkAngles": firework_angles,
                },
            })

        # 解析灯笼关键帧
        logger.info(f"灯笼关键帧数量: {len(drone.lanternKeyFrame)}")
        for lantern in drone.lanternKeyFrame:
            drone_data["lanternKeyFrames"].append({
                "frame": lantern.frame,
                "lanterns": {
                    "isOn": lantern.lanterns.isOn,
                },
            })

        # 解析云台关键帧
        logger.info(f"云台关键帧数量: {len(drone.gimbalKeyFrame)}")
        for gimbal in drone.gimbalKeyFrame:
            drone_data["gimbalKeyFrames"].append({
                "frame": gimbal.frame,
                "gimbals": {
                    "pitch": gimbal.gimbals.pitch,
                    "roll": gimbal.gimbals.roll,
                    "yaw": gimbal.gimbals.yaw,
                },
            })

        # 解析激光关键帧
        logger.info(f"激光关键帧数量: {len(drone.lazerKeyFrame)}")
        for lazer in drone.lazerKeyFrame:
            drone_data["lazerKeyFrames"].append({
                "frame": lazer.frame,
                "lazers": {
                    "r": lazer.lazers.r,
                    "g": lazer.lazers.g,
                    "b": lazer.lazers.b,
                },
            })

        # 解析姿态关键帧
        logger.info(f"姿态关键帧数量: {len(drone.poseKeyFrames)}")
        for pose in drone.poseKeyFrames:
            drone_data["poseKeyFrames"].append({
                "frame": pose.frame,
                "pitch": pose.pitch,
                "roll": pose.roll,
                "yaw": pose.yaw,
            })

        return drone_data

    def _parse_map_info(self, map_info):
        """解析地图信息"""
        self.data["drama3"]["map"] = {
            "rotate": map_info.rotate,
            "name": _safe_str(map_info.name),
            "widthScale": map_info.widthScale,
            "heightScale": map_info.heightScale,
            "radius": map_info.radius,
            "x": map_info.x,
            "y": map_info.y,
            "z": map_info.z,
            "lon": map_info.lon,
            "lat": map_info.lat,
        }

    def save_to_json(self, output_path, indent=4):
        """保存为 JSON 文件

        Args:
            output_path: 输出文件路径
            indent: JSON 缩进空格数，默认 4
        """
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=indent, ensure_ascii=False)

    def to_json_string(self, indent=4):
        """转换为 JSON 字符串

        Args:
            indent: JSON 缩进空格数，默认 4

        Returns:
            str: JSON 字符串
        """
        return json.dumps(self.data, indent=indent, ensure_ascii=False)
    
    def aes_cbc_decrypt(self, ciphertext_bytes, key, iv) -> bytes:
        """
        使用 AES-CBC 模式解密二进制数据。
        返回解密后的原始字节数据。
        """
        # 创建 AES 解密器
        cipher = AES.new(key, AES.MODE_CBC, iv)

        # 解密
        decrypted_padded = cipher.decrypt(ciphertext_bytes)

        # 去除填充 (PKCS7)
        try:
            plaintext = unpad(decrypted_padded, AES.block_size)
        except ValueError:
            # 如果数据未正确填充，尝试去除末尾的零字节
            plaintext = decrypted_padded.rstrip(b'\x00')

        return plaintext

    def decrypt_drm_to_tmp(self, drm_file_path, output_tmp_path=None):
        """
        解密 .drm 文件并提取 .tmp 文件
        
        Args:
            drm_file_path: .drm 文件路径
            output_tmp_path: 输出的 .tmp 文件路径（可选，默认为同名 .tmp 文件）
        
        Returns:
            str: 输出的 .tmp 文件路径
        """
        if output_tmp_path is None:
            output_tmp_path = drm_file_path.rsplit('.', 1)[0] + '.tmp'
        
        # 读取加密数据
        with open(drm_file_path, 'rb') as f:
            encrypted_data = f.read()
        
        # AES 解密
        decrypted_data = self.aes_cbc_decrypt(encrypted_data, secret_key, secret_iv)
        
        # ZIP 解压
        zip_buffer = io.BytesIO(decrypted_data)
        with zipfile.ZipFile(zip_buffer) as zf:
            file_list = zf.namelist()
            if 'dramafile' not in file_list:
                raise ValueError(f"ZIP 文件中没有找到 'dramafile'，找到: {file_list}")
            
            tmp_data = zf.read('dramafile')
        
        # 保存 .tmp 文件
        with open(output_tmp_path, 'wb') as f:
            f.write(tmp_data)
        
        logger.info(f"已成功解密并保存为: {output_tmp_path}")
        return output_tmp_path
    
    def save_one_drone_data(self, drone_num=1, interpolate=False):

        drone = self.data["drama3"]["drones"][drone_num-1]
        pointFps = self.data["drama3"]['pointFps']
        payloadFps = self.data["drama3"]['payloadFps']
        totalPayloadFrameCount = drone["totalPayloadFrameCount"]
        totalPointFrameCount = drone["totalPointFrameCount"]
        # logger.info(drone['id'])

        new_frame_list = {}
        new_frame_list['pointFps'] = pointFps
        new_frame_list['payloadFps'] = payloadFps
        new_frame_list["totalPointFrameCount"] = totalPointFrameCount
        new_frame_list["totalPayloadFrameCount"] = totalPayloadFrameCount

        # 剧本帧数同步 
        if pointFps >= payloadFps:
            light_frame_interval = int(pointFps / payloadFps)
            pos_frame_interval = 1
        else:
            light_frame_interval = 1
            pos_frame_interval = int(payloadFps / pointFps)

        frame_id = 0
        for light in drone["lightKeyFrames"]:           
            if frame_id not in new_frame_list:
                new_frame_list[frame_id] = []
            
            new_frame_list[frame_id].append({
                # "type": 0,
                "r": light["lights"]["r"],
                "g": light["lights"]["g"],
                "b": light["lights"]["b"]
            })
            frame_id += light_frame_interval

        frame_id = 0
        for position in drone["positionKeyFrames"]:
            if frame_id not in new_frame_list:
                new_frame_list[frame_id] = []
            
            new_frame_list[frame_id].append({
                # "type": 1,
                "x": position["x"],
                "y": position["y"],
                "z": position["z"]
            })
            frame_id += pos_frame_interval

        self.print_frame_type_counts(new_frame_list)

        if interpolate:
            # 插帧：如果某帧缺少位置或灯光数据，则使用前一帧的数据进行填充
            new_frame_list = self.interpolate_light_positions(new_frame_list)
            self.print_frame_type_counts(new_frame_list)
        
        dot_index = self.file_path.rfind('.')
        new_frame_list_name = f"{self.file_path[:dot_index]}_drone_{drone_num}.json"
        with open(new_frame_list_name, "w", encoding="utf-8") as f:
            json.dump(new_frame_list, f, indent=4, ensure_ascii=False)
            logger.info(f"已成功保存 {new_frame_list_name} 文件")
        return new_frame_list_name

    def print_frame_type_counts(self, new_frame_list):
        # 统计帧类型
        empty_count = 0
        pos_count = 0
        light_count = 0
        unknown_count = 0

        logger.info(f"点位帧率: {new_frame_list['pointFps']} 帧/秒")
        logger.info(f"灯光帧率: {new_frame_list['payloadFps']} 帧/秒")
        logger.info(f"位置帧总数：{new_frame_list['totalPointFrameCount']} ")
        logger.info(f"灯光帧总数: {new_frame_list['totalPayloadFrameCount']}")

        for frame_id in new_frame_list.keys():
            if frame_id in ("pointFps", "payloadFps", "totalPayloadFrameCount", "totalPointFrameCount"):
                continue

            if not new_frame_list[frame_id]:
                empty_count += 1
            else:
                for data in new_frame_list[frame_id]:
                    if "x" in data and "y" in data and "z" in data:
                        pos_count += 1
                    elif "r" in data and "g" in data and "b" in data:
                        light_count += 1
                    else:
                        unknown_count += 1

        logger.info(f"  [帧统计]")
        # logger.info(f"    统计总帧数:   {empty_count + pos_count + light_count + unknown_count}")
        # logger.info(f"    空帧:     {empty_count}")
        logger.info(f"    位置帧:   {pos_count}")
        logger.info(f"    灯光帧:   {light_count}")
        logger.info(f"    未知帧:   {unknown_count}")

    def interpolate_light_positions(self, new_frame_list):
        logger.info("处理缺失的位置或灯光数据：使用线性插值（位置）和前向填充（灯光）")
        
        frame_len = max(new_frame_list['totalPointFrameCount'], new_frame_list['totalPayloadFrameCount'])
        
        last_pos_frame = None
        last_light_frame = None
        
        # --- 第一步：预扫描，标记哪些帧拥有有效的位置数据 ---
        # 创建一个布尔列表，valid_pos_frames[i] 为 True 表示第 i 帧有位置数据
        valid_pos_frames = [False] * frame_len
        
        for frame_id in range(frame_len):
            if frame_id not in new_frame_list:
                new_frame_list[frame_id] = []
                
            for data in new_frame_list[frame_id]:
                if "x" in data and "y" in data and "z" in data:
                    valid_pos_frames[frame_id] = True
                    break # 只要有一个数据有效，该帧即为有效

        # 辅助函数：线性插值计算
        def lerp_val(start_val, end_val, ratio):
            return start_val + (end_val - start_val) * ratio
            # return start_val + end_val * ratio

        # --- 第二步：主循环，进行插值和填充 ---
        for frame_id in range(frame_len):
            frame_has_light = False
            frame_has_position = False
            
            # 确保帧列表存在
            if frame_id not in new_frame_list:
                new_frame_list[frame_id] = []
            
            # 1. 更新当前帧状态和“最后一帧”缓存
            for data in new_frame_list[frame_id]:
                if "x" in data and "y" in data and "z" in data:
                    last_pos_frame = data
                    frame_has_position = True
                if "r" in data and "g" in data and "b" in data:
                    last_light_frame = data 
                    frame_has_light = True
            
            # 2. 灯光数据处理（保持原有的前向填充逻辑）
            if not frame_has_light:
                new_frame_list[frame_id].append(last_light_frame)
                
            # 3. 位置数据处理（使用线性插值）
            if not frame_has_position:
                # 寻找插值的起点和终点
                start_idx = None
                end_idx = None
                
                # 向前找最近的有效帧
                for i in range(frame_id - 1, -1, -1):
                    if valid_pos_frames[i]:
                        start_idx = i
                        break
                
                # 向后找最近的有效帧
                for i in range(frame_id + 1, frame_len):
                    if valid_pos_frames[i]:
                        end_idx = i
                        break
                
                # 如果找到了起点和终点，则进行线性插值
                if start_idx is not None and end_idx is not None:
                    # 获取起点和终点的数据
                    # 注意：这里假设每一帧只有一个位置数据对象，取列表第一个符合xyz的
                    start_data = None
                    end_data = None
                    
                    # 重新从原始列表获取具体的数据对象
                    for d in new_frame_list[start_idx]:
                        if "x" in d and "y" in d and "z" in d:
                            start_data = d
                            break
                    
                    for d in new_frame_list[end_idx]:
                        if "x" in d and "y" in d and "z" in d:
                            end_data = d
                            break
                    
                    if start_data and end_data:
                        # 计算插值比例 (0.0 到 1.0)
                        # 例如：start=0, end=10, current=5 -> ratio = 0.5
                        ratio = (frame_id - start_idx) / (end_idx - start_idx)
                        
                        interpolated_pos = {
                            "x": lerp_val(start_data["x"], end_data["x"], ratio),
                            "y": lerp_val(start_data["y"], end_data["y"], ratio),
                            "z": lerp_val(start_data["z"], end_data["z"], ratio)
                        }
                        # 如果有其他相关字段（如时间戳等），也可以在这里处理，或者直接保留
                        new_frame_list[frame_id].append(interpolated_pos)
                    else:
                        # 理论上不会发生，因为valid_pos_frames已经确认存在
                        pass
                else:
                    # 如果无法进行线性插值（例如在开头或结尾缺失），回退到前向填充
                    if last_pos_frame:
                        new_frame_list[frame_id].append(last_pos_frame)
            
        return new_frame_list
            
if __name__ == "__main__":
    files = [
        "drama_files/0422-L10P2.drm",
        "drama_files/0422-L10P10.drm",
        "drama_files/0422-L30P2.drm",
        "drama_files/0422-L30P10.drm"
        # "drama_files/420版本测试8.drm"
    ]
    
    # for file_path in files:
    #     try:
    #         reader = DramaReader()
    #         data = reader.read(file_path)
            
    #         # 生成输出文件路径
    #         output_path = file_path.replace(".drm", ".json")
    #         # logger.info(output_path)
    #         if output_path == file_path:
    #             output_path = file_path + ".json"
            
    #         # reader.save_to_json(output_path)
    #         reader.save_one_drone_data(drone_num=1, interpolate=True)

    #         # logger.info(f"解析成功: {output_path}")
    #     except Exception as e:
    #         logger.info(f"错误: {e}")

    # fig = plt.figure()
    # ax = fig.add_subplot(111, projection='3d')
    # for file_path in files:
    #     json_path = file_path.replace(".drm", "_drone_1.json")
    #     if not os.path.exists(json_path):
    #         logger.info(f"文件不存在: {json_path}")
    #         continue
        
    #     with open(json_path, 'r', encoding='utf-8') as f:
    #         frame_data = json.load(f)
        
    #     xs, ys, zs = [], [], []
    #     for frame_id in sorted(frame_data.keys()):
    #         if frame_id in ("pointFps", "payloadFps", "totalPointFrameCount", "totalPayloadFrameCount"):
    #             continue
            
    #         for data in frame_data[frame_id]:
    #             if "x" in data and "y" in data and "z" in data:
    #                 xs.append(data["x"])
    #                 ys.append(data["y"])
    #                 zs.append(data["z"])
        
    #     ax.scatter(xs, ys, zs, label=os.path.basename(file_path), s=20, alpha=0.3, depthshade=False)

    # ax.set_xlabel('X')
    # ax.set_ylabel('Y')
    # ax.set_zlabel('Z')
    # plt.title("123")
    # plt.show()
