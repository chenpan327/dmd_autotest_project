import math
import os
import struct
import sys
import json

from . import emb_compressor

from utils.logger import logger

# 修复 Windows 控制台 UTF-8 输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


class DatReader:
    # 定义 CRC32 查找表 (直接复制自你提供的 C 代码)
    CRC32_TABLE = [
        0x00000000, 0xF26B8303, 0xE13B70F7, 0x1350F3F4, 0xC79A971F, 0x35F1141C,
        0x26A1E7E8, 0xD4CA64EB, 0x8AD958CF, 0x78B2DBCC, 0x6BE22838, 0x9989AB3B,
        0x4D43CFD0, 0xBF284CD3, 0xAC78BF27, 0x5E133C24, 0x105EC76F, 0xE235446C,
        0xF165B798, 0x030E349B, 0xD7C45070, 0x25AFD373, 0x36FF2087, 0xC494A384,
        0x9A879FA0, 0x68EC1CA3, 0x7BBCEF57, 0x89D76C54, 0x5D1D08BF, 0xAF768BBC,
        0xBC267848, 0x4E4DFB4B, 0x20BD8EDE, 0xD2D60DDD, 0xC186FE29, 0x33ED7D2A,
        0xE72719C1, 0x154C9AC2, 0x061C6936, 0xF477EA35, 0xAA64D611, 0x580F5512,
        0x4B5FA6E6, 0xB93425E5, 0x6DFE410E, 0x9F95C20D, 0x8CC531F9, 0x7EAEB2FA,
        0x30E349B1, 0xC288CAB2, 0xD1D83946, 0x23B3BA45, 0xF779DEAE, 0x05125DAD,
        0x1642AE59, 0xE4292D5A, 0xBA3A117E, 0x4851927D, 0x5B016189, 0xA96AE28A,
        0x7DA08661, 0x8FCB0562, 0x9C9BF696, 0x6EF07595, 0x417B1DBC, 0xB3109EBF,
        0xA0406D4B, 0x522BEE48, 0x86E18AA3, 0x748A09A0, 0x67DAFA54, 0x95B17957,
        0xCBA24573, 0x39C9C670, 0x2A993584, 0xD8F2B687, 0x0C38D26C, 0xFE53516F,
        0xED03A29B, 0x1F682198, 0x5125DAD3, 0xA34E59D0, 0xB01EAA24, 0x42752927,
        0x96BF4DCC, 0x64D4CECF, 0x77843D3B, 0x85EFBE38, 0xDBFC821C, 0x2997011F,
        0x3AC7F2EB, 0xC8AC71E8, 0x1C661503, 0xEE0D9600, 0xFD5D65F4, 0x0F36E6F7,
        0x61C69362, 0x93AD1061, 0x80FDE395, 0x72966096, 0xA65C047D, 0x5437877E,
        0x4767748A, 0xB50CF789, 0xEB1FCBAD, 0x197448AE, 0x0A24BB5A, 0xF84F3859,
        0x2C855CB2, 0xDEEEDFB1, 0xCDBE2C45, 0x3FD5AF46, 0x7198540D, 0x83F3D70E,
        0x90A324FA, 0x62C8A7F9, 0xB602C312, 0x44694011, 0x5739B3E5, 0xA55230E6,
        0xFB410CC2, 0x092A8FC1, 0x1A7A7C35, 0xE811FF36, 0x3CDB9BDD, 0xCEB018DE,
        0xDDE0EB2A, 0x2F8B6829, 0x82F63B78, 0x709DB87B, 0x63CD4B8F, 0x91A6C88C,
        0x456CAC67, 0xB7072F64, 0xA457DC90, 0x563C5F93, 0x082F63B7, 0xFA44E0B4,
        0xE9141340, 0x1B7F9043, 0xCFB5F4A8, 0x3DDE77AB, 0x2E8E845F, 0xDCE5075C,
        0x92A8FC17, 0x60C37F14, 0x73938CE0, 0x81F80FE3, 0x55326B08, 0xA759E80B,
        0xB4091BFF, 0x466298FC, 0x1871A4D8, 0xEA1A27DB, 0xF94AD42F, 0x0B21572C,
        0xDFEB33C7, 0x2D80B0C4, 0x3ED04330, 0xCCBBC033, 0xA24BB5A6, 0x502036A5,
        0x4370C551, 0xB11B4652, 0x65D122B9, 0x97BAA1BA, 0x84EA524E, 0x7681D14D,
        0x2892ED69, 0xDAF96E6A, 0xC9A99D9E, 0x3BC21E9D, 0xEF087A76, 0x1D63F975,
        0x0E330A81, 0xFC588982, 0xB21572C9, 0x407EF1CA, 0x532E023E, 0xA145813D,
        0x758FE5D6, 0x87E466D5, 0x94B49521, 0x66DF1622, 0x38CC2A06, 0xCAA7A905,
        0xD9F75AF1, 0x2B9CD9F2, 0xFF56BD19, 0x0D3D3E1A, 0x1E6DCDEE, 0xEC064EED,
        0xC38D26C4, 0x31E6A5C7, 0x22B65633, 0xD0DDD530, 0x0417B1DB, 0xF67C32D8,
        0xE52CC12C, 0x1747422F, 0x49547E0B, 0xBB3FFD08, 0xA86F0EFC, 0x5A048DFF,
        0x8ECEE914, 0x7CA56A17, 0x6FF599E3, 0x9D9E1AE0, 0xD3D3E1AB, 0x21B862A8,
        0x32E8915C, 0xC083125F, 0x144976B4, 0xE622F5B7, 0xF5720643, 0x07198540,
        0x590AB964, 0xAB613A67, 0xB831C993, 0x4A5A4A90, 0x9E902E7B, 0x6CFBAD78,
        0x7FAB5E8C, 0x8DC0DD8F, 0xE330A81A, 0x115B2B19, 0x020BD8ED, 0xF0605BEE,
        0x24AA3F05, 0xD6C1BC06, 0xC5914FF2, 0x37FACCF1, 0x69E9F0D5, 0x9B8273D6,
        0x88D28022, 0x7AB90321, 0xAE7367CA, 0x5C18E4C9, 0x4F48173D, 0xBD23943E,
        0xF36E6F75, 0x0105EC76, 0x12551F82, 0xE03E9C81, 0x34F4F86A, 0xC69F7B69,
        0xD5CF889D, 0x27A40B9E, 0x79B737BA, 0x8BDCB4B9, 0x988C474D, 0x6AE7C44E,
        0xBE2DA0A5, 0x4C4623A6, 0x5F16D052, 0xAD7D5351
    ]

    def __init__(self):
        self.origin_lon = 114.0224279
        self.origin_lat = 22.6868406
        
        pass

    def calculate_crc32(self, data):
        """
        计算 CRC32，初始值为 0，且不进行最终异或。
        这通常用于某些特定的嵌入式或自定义协议中。
        """
        crc = 0x00000000
        for byte in data:
            index = (crc ^ byte) & 0xFF
            crc = (crc >> 8) ^ self.CRC32_TABLE[index]
        return crc

    def decode_varint(self, data, pos):
        result = 0
        shift = 0
        while True:
            byte = data[pos]
            result |= (byte & 0x7F) << shift
            pos += 1
            if not (byte & 0x80):
                break
            shift += 7
        return result, pos

    def split_data(self, data):
        """
        分割二进制数据：
        - 帧头 20 字节：crc0(4) + id(4) + index(9) + 预留(3)
        - 配置部分：crc1(4) + len(1) + len 对应的变长数据
        - 后续内容：crc2(4) + 剩余全部内容帧
        """
        offset = 0

        # 帧头 20 字节
        header = {
            'crc0': data[offset:offset + 4],
            'id': data[offset + 4:offset + 8],
            'index_play': data[offset + 8:offset + 12],
            'index_land': data[offset + 12:offset + 16],
            'frame_sync': data[offset + 16:offset + 17],
            'reserved': data[offset + 17:offset + 20],
        }
        result_crc0 = self.calculate_crc32(data[4:20])
        offset += 20

        # 配置部分
        crc1 = data[offset:offset + 4]
        offset += 4
        length = data[offset]
        offset += 1
        var_data = data[offset:offset + length]
        offset += length

        pos = 0
        fields = {}
        while pos < len(var_data):
            tag_val, new_pos = self.decode_varint(var_data, pos)
            field_number = tag_val >> 3
            wire_type = tag_val & 0x07
            pos = new_pos

            if wire_type == 0:  # Varint
                value, pos = self.decode_varint(var_data, pos)
                fields[field_number] = value
            else:
                logger.error(f"Unsupported wire type: {wire_type}")

        # 映射到变量名
        pointFps = fields.get(1)
        payloadFps = fields.get(2)
        totalPointFrameCount = fields.get(3)
        totalPayloadFrameCount = fields.get(4)

        config = {
            'crc1': crc1,
            'len': length,
            'pointFps': pointFps,
            'payloadFps': payloadFps,
            'totalPointFrameCount': totalPointFrameCount,
            'totalPayloadFrameCount': totalPayloadFrameCount
        }

        result_crc1 = self.calculate_crc32(data[24:25 + length])

        # 后续内容
        compress = data[offset:]
        decompressed = emb_compressor.decompress(compress, 'fastlz')

        crc2 = decompressed[0:4]
        content = decompressed[4:]

        result_crc2 = self.calculate_crc32(content)

        # 解析变长帧
        frame_sync_val = (header['frame_sync'][0] >> 4) & 0x0F if header['frame_sync'] else 0
        frames = self.parse_frames(content, frame_sync_val)

        trailer = {
            'crc2': crc2,
            "frames": frames
        }

        return header, config, trailer, result_crc0, result_crc1, result_crc2

    def parse_frames(self, decompressed_data, frame_sync):
        """
        解析变长帧数据。

        每帧格式：
        - type: 1 byte
            bit0: 位置标志 (有则 +12 bytes: x4 + y4 + z4，大端有符号整型)
            bit1: 灯光标志 (有则 +3 bytes: r1 + g1 + b1)
            bit2: 其他标志
            bit4-7: 帧同步标志
        """
        frames = []
        i = 0
        total_len = len(decompressed_data)

        while i < total_len:
            if i + 1 > total_len:
                break

            t = decompressed_data[i]
            temp_frame_sync = (t >> 4) & 0x0F
            has_pos = bool(t & 0x01)
            has_light = bool(t & 0x02)
            has_other = bool(t & 0x04)

            frame_len = 1

            if temp_frame_sync == frame_sync:
                if has_pos:
                    frame_len += 12
                if has_light:
                    frame_len += 3

                if i + frame_len > total_len:
                    frames.append({'unknown': None})
                    logger.info("发现未知帧（帧长度超出剩余数据），将其标记为未知帧并继续解析下一帧")
                    i += frame_len
                    continue

                frame_data = decompressed_data[i + 1:i + frame_len]
                position = None
                light = None

                if has_pos:
                    pos_bytes = frame_data[:12]
                    lon = struct.unpack('<i', pos_bytes[0:4])[0]
                    lat = struct.unpack('<i', pos_bytes[4:8])[0]
                    alt = struct.unpack('<i', pos_bytes[8:12])[0]
                    position = {'lon': lon, 'lat': lat, 'alt': alt}
                    frame_data = frame_data[12:]

                if has_light:
                    light = {'r': frame_data[0], 'g': frame_data[1], 'b': frame_data[2]}

                frames.append({
                    'position': position,
                    'light': light,
                })
            else:
                frames.append({'unknown': None})

            i += frame_len

        return frames

    def print_split_result(self, header, config, trailer, result_crc0, result_crc1, result_crc2):
        """打印分割结果"""

        crc0_ok = result_crc0 == int.from_bytes(header['crc0'], 'little')
        crc1_ok = result_crc1 == int.from_bytes(config['crc1'], 'little')
        crc2_ok = result_crc2 == int.from_bytes(trailer['crc2'], 'little')

        logger.info(f"  [帧头 20 字节]")
        logger.info(f"    crc0:     {header['crc0'].hex()}")
        logger.info(f"    CRC校验:  {'通过' if crc0_ok else '失败'} (计算值: {result_crc0:08X})")
        logger.info(f"    id:       {header['id'].hex()} -> {struct.unpack('<I', header['id'])[0]}")
        logger.info(f"    index_play:    {header['index_play'].hex()}")
        logger.info(f"    index_land:    {header['index_land'].hex()}")
        logger.info(f"    frame_sync:    {header['frame_sync'].hex()}")
        logger.info(f"    reserved: {header['reserved'].hex()}")

        logger.info(f"  [配置部分]")
        logger.info(f"    crc1:     {config['crc1'].hex()}")
        logger.info(f"    CRC校验:  {'通过' if crc1_ok else '失败'} (计算值: {result_crc1:08X})")
        logger.info(f"    len:      {config['len']}")
        logger.info(f"    pointFps: {config['pointFps']}")
        logger.info(f"    payloadFps: {config['payloadFps']}")
        logger.info(f"    totalPointFrameCount: {config['totalPointFrameCount']}")
        logger.info(f"    totalPayloadFrameCount: {config['totalPayloadFrameCount']}")

        logger.info(f"  [后续内容]")
        logger.info(f"    crc2:         {trailer['crc2'].hex()}")
        logger.info(f"    CRC校验:      {'通过' if crc2_ok else '失败'} (计算值: {result_crc2:08X})")

        # 统计帧类型
        empty_count = 0
        pos_count = 0
        light_count = 0
        unknown_count = 0

        for frame in trailer['frames']:
            if 'unknown' in frame:
                unknown_count += 1
            else:
                has_pos = frame['position'] is not None
                has_light = frame['light'] is not None
                if has_pos:
                    pos_count += 1
                if has_light:
                    light_count += 1
                if not has_pos and not has_light:
                    empty_count += 1

        logger.info(f"  [帧统计]")
        logger.info(f"    统计总帧数:   {len(trailer['frames'])}")
        logger.info(f"    空帧:     {empty_count}")
        logger.info(f"    位置帧:   {pos_count}")
        logger.info(f"    灯光帧:   {light_count}")
        logger.info(f"    未知帧:   {unknown_count}")

    def save_one_drone_data(self, config, frames, drama_json, interpolate=False):
        new_frame_list = {}

        new_frame_list["pointFps"] = config["pointFps"]
        new_frame_list["payloadFps"] = config["payloadFps"]
        new_frame_list["totalPointFrameCount"] = config["totalPointFrameCount"]
        new_frame_list["totalPayloadFrameCount"] = config["totalPayloadFrameCount"]

        frames_index = 0
        for frame in frames:
            new_frame_list[frames_index] = []

            if frame['position'] is not None:
                
                new_frame_list[frames_index].append(frame['position'])

            if frame['light'] is not None:
                new_frame_list[frames_index].append(frame['light'])

            frames_index += 1

        if interpolate:
            self.print_frame_type_counts(new_frame_list)
            new_frame_list = self.interpolate_light_positions(new_frame_list)
            self.print_frame_type_counts(new_frame_list)
            self.raw_to_xyz(new_frame_list)

        dot_index = drama_json.rfind('.')
        new_frame_list_name = f"{drama_json[:dot_index]}.json"
        with open(new_frame_list_name, "w", encoding="utf-8") as f:
            json.dump(new_frame_list, f, indent=4, ensure_ascii=False)
            logger.info(f"已成功保存 {new_frame_list_name} 文件")

        return new_frame_list_name

    def read_binary_file(self, file_path):
        """读取二进制文件并返回其内容"""
        with open(file_path, 'rb') as f:
            data = f.read()
        return data

    def process_file(self, file_path):
        """
        处理单个 .dat 文件的完整流程。

        Args:
            file_path: .dat 文件路径

        Returns:
            (header, config, trailer, result_crc0, result_crc1, result_crc2) 元组
        """
        if not os.path.exists(file_path):
            logger.error(f"文件不存在: {file_path}")
            return None

        data = self.read_binary_file(file_path)
        header, config, trailer, result_crc0, result_crc1, result_crc2 = self.split_data(data)

        return header, config, trailer, result_crc0, result_crc1, result_crc2
    
    def interpolate_light_positions(self, new_frame_list):
        logger.info("处理缺失的位置或灯光数据：使用线性插值（位置）和前向填充（灯光）")
        
        frame_len = max(new_frame_list['totalPointFrameCount'], new_frame_list['totalPayloadFrameCount'])
        
        last_pos_frame = None
        last_light_frame = None
        
        # --- 第一步：预扫描，标记哪些帧拥有有效的位置数据 ---
        # 创建一个布尔列表，valid_pos_frames[i] 为 True 表示第 i 帧有位置数据
        valid_pos_frames = [False] * frame_len

        last_lat = 0
        last_lon = 0
        last_alt = 0
        full_new_frame_list = {}
        full_new_frame_list["pointFps"] = new_frame_list["pointFps"]
        full_new_frame_list["payloadFps"] = new_frame_list["payloadFps"]
        full_new_frame_list["totalPointFrameCount"] = new_frame_list["totalPointFrameCount"]
        full_new_frame_list["totalPayloadFrameCount"] = new_frame_list["totalPayloadFrameCount"]
        
        for frame_id in range(frame_len):
            if frame_id not in new_frame_list:
                new_frame_list[frame_id] = []
            if frame_id not in full_new_frame_list:
                full_new_frame_list[frame_id] = []
                
            for data in new_frame_list[frame_id]:
                if "lat" in data and "lon" in data and "alt" in data:
                    valid_pos_frames[frame_id] = True
                    last_lat += data["lat"]
                    last_lon += data["lon"]
                    last_alt += data["alt"]
                    full_new_frame_list[frame_id].append({
                        "lat": last_lat,
                        "lon": last_lon,
                        "alt": last_alt
                    })
                
                if "r" in data and "g" in data and "b" in data:
                    full_new_frame_list[frame_id].append({
                        "r": data["r"],
                        "g": data["g"],
                        "b": data["b"]
                    })

        # 辅助函数：线性插值计算
        def lerp_val(start_val, end_val, ratio):
            return start_val + (end_val - start_val) * ratio
            # return start_val + end_val * ratio

        # --- 第二步：主循环，进行插值和填充 ---
        for frame_id in range(frame_len):
            frame_has_light = False
            frame_has_position = False
            
            # 确保帧列表存在
            if frame_id not in full_new_frame_list:
                full_new_frame_list[frame_id] = []
            
            # 1. 更新当前帧状态和“最后一帧”缓存
            for data in full_new_frame_list[frame_id]:
                if "lat" in data and "lon" in data and "alt" in data:
                    last_pos_frame = data
                    frame_has_position = True
                if "r" in data and "g" in data and "b" in data:
                    last_light_frame = data 
                    frame_has_light = True
            
            # 2. 灯光数据处理（保持原有的前向填充逻辑）
            if not frame_has_light:
                full_new_frame_list[frame_id].append(last_light_frame)
                
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
                    for d in full_new_frame_list[start_idx]:
                        if "lat" in d and "lon" in d and "alt" in d:
                            start_data = d
                            break
                    
                    for d in full_new_frame_list[end_idx]:
                        if "lat" in d and "lon" in d and "alt" in d:
                            end_data = d
                            break
                    
                    if start_data and end_data:
                        # 计算插值比例 (0.0 到 1.0)
                        # 例如：start=0, end=10, current=5 -> ratio = 0.5
                        ratio = (frame_id - start_idx) / (end_idx - start_idx)
                        
                        interpolated_pos = {
                            "lat": lerp_val(start_data["lat"], end_data["lat"], ratio),
                            "lon": lerp_val(start_data["lon"], end_data["lon"], ratio),
                            "alt": lerp_val(start_data["alt"], end_data["alt"], ratio)
                        }
                        # 如果有其他相关字段（如时间戳等），也可以在这里处理，或者直接保留
                        full_new_frame_list[frame_id].append(interpolated_pos)
                    else:
                        # 理论上不会发生，因为valid_pos_frames已经确认存在
                        pass
                else:
                    # 如果无法进行线性插值（例如在开头或结尾缺失），回退到前向填充
                    if last_pos_frame:
                        full_new_frame_list[frame_id].append(last_pos_frame)

        return full_new_frame_list
    
    def print_frame_type_counts(self, new_frame_list):
        """打印帧统计总览（单行，避免大量日志）。"""
        empty_count = 0
        pos_count = 0
        light_count = 0
        unknown_count = 0

        for frame_id in new_frame_list.keys():
            if frame_id in ("pointFps", "payloadFps", "totalPayloadFrameCount", "totalPointFrameCount"):
                continue

            if not new_frame_list[frame_id]:
                empty_count += 1
            else:
                for data in new_frame_list[frame_id]:
                    if "lat" in data and "lon" in data and "alt" in data:
                        pos_count += 1
                    elif "r" in data and "g" in data and "b" in data:
                        light_count += 1
                    else:
                        unknown_count += 1

        logger.info(
            f"[帧统计] 点位帧率={new_frame_list['pointFps']} 灯光帧率={new_frame_list['payloadFps']} | "
            f"位置帧总数={new_frame_list['totalPointFrameCount']} 灯光帧总数={new_frame_list['totalPayloadFrameCount']} | "
            f"实际位置帧={pos_count} 灯光帧={light_count} 未知帧={unknown_count}"
        )

    def raw_to_xyz(self, new_frame_list, scale_factor=1e7):
        LAT_TO_M = 111319.5
        
        for frame_id in new_frame_list.keys():
            if frame_id in ("pointFps", "payloadFps", "totalPayloadFrameCount", "totalPointFrameCount"):
                continue

            frame_data = new_frame_list[frame_id]
            for item in frame_data:
                if "lat" in item and "lon" in item and "alt" in item:
                    lat = item["lat"] / scale_factor
                    lon = item["lon"] / scale_factor
                    alt = item["alt"] / 1e3  # 假设原始高度单位是毫米，转换为米

                    x = (lon - self.origin_lon) * LAT_TO_M * math.cos(math.radians(lat))
                    y = (lat - self.origin_lat) * LAT_TO_M 
                    z = alt

                    item["x"] = x
                    item["y"] = y
                    item["z"] = z

        return new_frame_list
    
    def read_json_file(self, file_path):
        """读取 JSON 文件并返回其内容"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data


if __name__ == '__main__':
    files = [
        # 'dat/drama_mission_1_drama_1.dat',
        "dat/L10P2.txt",
        "dat/L10P10.txt",
        "dat/L30P2.txt",
        "dat/L30P10.txt"
    ]

    reader = DatReader()
    for file_path in files:
        header, config, trailer, result_crc0, result_crc1, result_crc2 = reader.process_file(file_path)

        reader.print_split_result(header, config, trailer, result_crc0, result_crc1, result_crc2)

        reader.save_one_drone_data(config, trailer['frames'], file_path, interpolate=True)
