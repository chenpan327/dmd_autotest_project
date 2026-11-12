#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MAVLink 网络文件传输工具

功能说明：
    通过 MAVLink 协议实现与远端设备的文件传输，支持以下操作：
    - push: 推送本地文件到远端设备
    - pull: 从远端设备拉取文件到本地
    - verify: 校验远端文件的完整性（MD5）
    - delete: 删除远端设备上的文件

工作流程：
    1. 打开文件会话（NET_FILE_OPEN）
    2. 传输文件数据（NET_FILE_WRITE/READ）
    3. 关闭文件会话（NET_FILE_CLOSE）
    4. 每个操作都需要等待远端的 ACK 确认，支持超时重试

作者：jin tao
创建时间：2025-10-15 15:33:42
"""


import sys
import os, re, types, io
import hashlib
import struct
import time

from src.Protocol.mavlink.parse_mavlink import MAVLink_message

# ============================================================================
# MAVLink NET_FILE_COMMAND 消息 ID 常量
# ============================================================================
MAVLINK_MSG_ID_NET_FILE_COMMAND = 63

# ============================================================================
# 网络文件操作命令常量定义
# 对应 MAVLink NET_FILE_COMMAND 消息中的 cmd 字段
# ============================================================================
NET_FILE_OPEN   = 0  # 打开文件
NET_FILE_WRITE  = 1  # 写入文件数据
NET_FILE_READ   = 2  # 读取文件数据
NET_FILE_CLOSE  = 3  # 关闭文件
NET_FILE_ACK    = 4  # 操作确认响应
NET_FILE_VERIFY = 5  # 校验文件（MD5）
NET_FILE_DELETE = 6  # 删除文件

# ============================================================================
# 网络文件操作模式常量定义
# ============================================================================
NET_FILE_OP_MODE_NONE   = 0  # 无操作模式
NET_FILE_OP_MODE_READ   = 1  # 读取模式（从远端读取文件）
NET_FILE_OP_MODE_WRITE  = 2  # 写入模式（向远端写入文件）

#####################################################################################
# 抽象接口层：统一串口和UDP的MAVLink通讯接口
#####################################################################################

import time as time_module


class MAVLinkLink:
    """MAVLink 通讯接口统一类

    统一串口模式和UDP模式的接口，使得文件操作函数可以通用。
    """

    # MAVLink 消息头信息（子类可覆盖）
    SYS_ID = 0
    COMP_ID = 0
    SEQ = 0

    def recv_match(self, blocking=False, timeout=0.5):
        """接收并返回一条 MAVLink 消息

        Args:
            blocking: 是否阻塞等待
            timeout: 阻塞超时时间（秒）

        Returns:
            MAVLink_message 或 None（超时返回 None）
        """
        raise NotImplementedError

    def send(self, message):
        """发送 MAVLink 消息

        Args:
            message: MAVLink_message 实例或 bytes

        Returns:
            发送成功返回 True，否则 False
        """
        raise NotImplementedError

    def net_file_command_send(self, cmd, data):
        """构造并发送 NET_FILE_COMMAND 消息

        Args:
            cmd: 命令码（NET_FILE_OPEN, NET_FILE_WRITE 等）
            data: 命令数据（字节串）

        Returns:
            发送的 MAVLink_message 对象
        """
        # NET_FILE_COMMAND 格式: <h253s (2字节命令码 + 253字节数据)
        # data 可能小于 253 字节，需要填充
        padded_data = data[:253].ljust(253, b'\x00') if data else b'\x00' * 253
        payload = struct.pack('<h253s', cmd, padded_data)

        msg = MAVLink_message(
            msg_id=MAVLINK_MSG_ID_NET_FILE_COMMAND,
            payload=payload,
            sys_id=self.SYS_ID,
            comp_id=self.COMP_ID,
            seq=self.SEQ
        )
        self.SEQ = (self.SEQ + 1) & 0xFF  # 序列号递增
        self.send(msg)
        return msg

    def close(self):
        """关闭连接（子类可重写）"""
        pass


class SerialMAVLinkLink(MAVLinkLink):
    """串口模式的 MAVLink 通讯接口适配器

    注意：串口模式暂未实现，使用前需自行适配底层串口通讯。
    """

    def __init__(self, port, baudrate=115200, sys_id=0, comp_id=0):
        import serial
        self._serial = serial.Serial(port, baudrate=baudrate, timeout=0.1)
        self.SYS_ID = sys_id
        self.COMP_ID = comp_id
        self._buf = b''

    def recv_match(self, blocking=False, timeout=0.5):
        start = time_module.time()
        while True:
            # 尝试从缓冲区解析完整的 MAVLink 消息
            while len(self._buf) >= 8:
                if self._buf[0] != 0xFE:  # MAVLink start byte
                    self._buf = self._buf[1:]
                    continue
                length = self._buf[1]
                if len(self._buf) < 6 + length + 2:
                    break
                msg_data = self._buf[:6 + length + 2]
                self._buf = self._buf[6 + length + 2:]
                try:
                    msg = MAVLink_message(hex_data=msg_data.hex())
                    return msg
                except Exception:
                    continue

            if not blocking:
                return None
            if time_module.time() - start >= timeout:
                return None

            # 从串口读取更多数据
            try:
                more = self._serial.read(256)
                if more:
                    self._buf += more
                else:
                    time_module.sleep(0.01)
            except Exception:
                time_module.sleep(0.01)

    def send(self, message):
        try:
            if isinstance(message, MAVLink_message):
                data = message.pack()
            else:
                data = message
            self._serial.write(data)
            return True
        except Exception as e:
            print(f"[SerialMAVLinkLink] send error: {e}")
            return False

    def close(self):
        if self._serial:
            self._serial.close()
            self._serial = None


class GCSSimMAVLinkLink(MAVLinkLink):
    """UDP模式（GroundControlStation）的 MAVLink 通讯接口适配器"""

    def __init__(self, gcs):
        self._gcs = gcs

    def recv_match(self, blocking=False, timeout=0.5):
        start = time_module.time()
        while True:
            msg, addr = self._gcs.receive()
            if msg is None:
                if not blocking:
                    return None
                if time_module.time() - start >= timeout:
                    return None
                time_module.sleep(0.01)
            else:
                return msg

    def send(self, message):
        return self._gcs.send(message)

    def close(self):
        self._gcs.close()


#####################################################################################
# 工具函数：用于 MAVLink 消息的调试和格式化输出
#####################################################################################

def buf2hexstr(buf):
    """
    将字节缓冲区转换为十六进制字符串
    
    参数:
        buf: 字节缓冲区 (bytes/bytearray)
    
    返回:
        str: 以空格分隔的十六进制字符串，例如 "01 02 0A FF"
    """
    return ' '.join(f"{byte:02X}" for byte in buf)  # 每个字节格式化为两位大写十六进制


def msg_buf_str(msg):
    """
    获取 MAVLink 消息的完整缓冲区十六进制字符串
    
    参数:
        msg: MAVLink 消息对象
    
    返回:
        str: 消息缓冲区的十六进制表示
    """
    return buf2hexstr(msg.pack())


def msg_header_str(msg):
    """
    获取 MAVLink 消息头的详细信息字符串
    
    参数:
        msg: MAVLink 消息对象
    
    返回:
        str: 包含消息类型、长度、序列号、源系统、源组件、消息ID的字符串
    """
    return f"msg_id({msg.msg_id}) header(len:{msg.length}, seq:{msg.seq}, sys:{msg.sys_id}, comp:{msg.comp_id})"


def print_msg_detail(msg, type=0) -> None:
    """
    打印 MAVLink 消息的详细信息（用于调试）
    
    参数:
        msg: MAVLink 消息对象
        type: 输出格式类型
              0 - 默认格式（直接打印消息对象）
              1 - 完整缓冲区十六进制格式
              2 - 消息头详细信息格式
    """
    if type == 0:
        print(msg)  # 默认格式
    elif type == 1:
        print('MG Le sq Sc Dt ID')  # 打印字段名提示
        print(msg_buf_str(msg))  # 完整缓冲区十六进制
    elif type == 2:
        print(msg_header_str(msg))  # 消息头详细信息

def net_file_write_file(m_in, m_out, filefrom, fileto) -> bool:
    """
    将本地文件推送到远端设备（写入操作）
    
    工作流程:
        Step 1: 打开远端文件（NET_FILE_OPEN）
        Step 2: 分块写入文件数据（NET_FILE_WRITE）
        Step 3: 关闭远端文件（NET_FILE_CLOSE）
    
    参数:
        m_in: MAVLink 输入连接对象（用于接收 ACK）
        m_out: MAVLink 输出连接对象（用于发送命令）
        filefrom: 本地源文件路径
        fileto: 远端目标文件路径
    
    返回:
        bool: 传输成功返回 True，失败返回 False
    
    重试机制:
        - 每个操作最多重试 3 次
        - 每次等待 ACK 的超时时间为 3 秒
        - 接收消息的阻塞超时为 0.5 秒
    """
    step = 1  # 当前步骤：1-打开, 2-写入, 3-关闭
    file_op_mode = NET_FILE_OP_MODE_WRITE  # 操作模式：写入
    file_op_fid = 0  # 文件操作句柄（由远端返回）
    file_wr_pos = 0  # 当前写入位置
    file_ack_result = False  # ACK 结果标志

    # 检查本地文件是否存在
    if os.path.exists(filefrom) == False:
        print(f"file ({filefrom}) not exist")
        return False
    
    # 读取本地文件到内存
    with open(filefrom, 'rb') as f:
        file_data = f.read()
        f.close()
    print(f"source file size: {len(file_data)}")

    # 构造打开文件的命令数据包
    # 格式: <hI64s - 操作模式(2字节) + 文件长度(4字节) + 文件名(64字节)
    open_st = struct.pack('<hI64s', file_op_mode, len(file_data), fileto.encode('utf-8'))

    # ========================================================================
    # Step 1: 打开远端文件
    # ========================================================================
    itry = 0  # 重试计数器
    while step == 1:
        # 发送打开文件命令
        # m_out.net_file_command_send 会自动调用 pack() 方法打包数据
        m_out.net_file_command_send(NET_FILE_OPEN, open_st)
        file_ack_result = False
        start_time = time.time()
        timeout = 3.0  # 超时时间：3秒
        
        # 等待 ACK 响应
        while start_time + timeout > time.time():
            msg = m_in.recv_match(blocking=True, timeout=0.5)
            if msg:
                print_msg_detail(msg, 0)
                # 检查是否为 NET_FILE_COMMAND 消息且命令为 ACK
                if msg.msg_id == MAVLINK_MSG_ID_NET_FILE_COMMAND and msg.fields.get('net_file_cmd') == NET_FILE_ACK:
                    # 解析 ACK 数据
                    # 格式: <hiIh64s - 命令(2) + 返回值(4) + 文件长度(4) + 操作模式(2) + 文件名(64)
                    open_fmt = "<hiIh64s"
                    required_len = struct.calcsize(open_fmt)
                    if required_len <= len(msg.payload) - 2:
                        ack_cmd, open_return, f_length, op_mode, sz_name = struct.unpack(open_fmt, msg.payload[2:2+required_len])
                        # 验证响应：命令匹配、返回值有效、模式匹配
                        if ack_cmd == NET_FILE_OPEN and open_return >= 0 and op_mode == file_op_mode:
                            file_op_fid = open_return  # 保存文件句柄
                            file_ack_result = True
                            itry = 0  # 重置重试计数
                            step += 1  # 进入下一步
                            break
        # 检查是否超时重试
        if not file_ack_result:
            itry += 1
            if itry >= 3:
                print(f"The retry count for the open has exceeded the limit ({itry}).")
                break
    # 如果打开失败，直接返回
    if step != 2:
        return False

    # ========================================================================
    # Step 2: 分块写入文件数据
    # ========================================================================
    itry = 0  # 重试计数器
    while file_wr_pos < len(file_data) and step == 2:
        # 计算本次发送的数据长度（最大 240 字节）
        send_len = min(len(file_data) - file_wr_pos, 240)
        
        # 构造写入数据包
        # 格式: <HiI{send_len}s - 数据长度(2) + 文件句柄(4) + 写入位置(4) + 数据
        write_st = struct.pack(f'<HiI{send_len}s', send_len, file_op_fid, file_wr_pos,
                               file_data[file_wr_pos:file_wr_pos + send_len])
        
        # 发送写入命令
        m_out.net_file_command_send(NET_FILE_WRITE, write_st)
        file_ack_result = False
        start_time = time.time()
        timeout = 3.0
        
        # 等待 ACK 响应
        while start_time + timeout > time.time():
            msg = m_in.recv_match(blocking=True, timeout=0.5)
            if msg:
                print_msg_detail(msg, 0)
                if msg.msg_id == MAVLINK_MSG_ID_NET_FILE_COMMAND and msg.fields.get('net_file_cmd') == NET_FILE_ACK:
                    # 解析 ACK 数据
                    # 格式: <hiiI - 命令(2) + 实际写入长度(4) + 文件句柄(4) + 位置(4)
                    write_fmt = "<hiiI"
                    required_len = struct.calcsize(write_fmt)
                    if required_len <= len(msg.payload) - 2:
                        ack_cmd, write_return, op_fid, f_pos = struct.unpack(write_fmt, msg.payload[2:2+required_len])
                        # 验证响应：命令匹配、长度有效、句柄匹配
                        if ack_cmd == NET_FILE_WRITE and write_return >= 0 and op_fid == file_op_fid:
                            file_wr_pos += write_return  # 更新写入位置
                            file_ack_result = True
                            itry = 0  # 重置重试计数
                            break
        # 检查是否超时重试
        if not file_ack_result:
            itry += 1
            if itry >= 3:
                print(f"The retry count for the write (pos={file_wr_pos}) has exceeded the limit ({itry}).")
                break
    # 检查是否全部写入完成
    if file_wr_pos >= len(file_data):
        step += 1  # 进入下一步

    if step != 3:
        return False

    # ========================================================================
    # Step 3: 关闭远端文件
    # ========================================================================
    itry = 0
    # 构造关闭文件命令
    # 格式: <Hi - 保留字段(2) + 文件句柄(4)
    close_st = struct.pack(f'<Hi', 0, file_op_fid)
    while step == 3:
        m_out.net_file_command_send(NET_FILE_CLOSE, close_st)
        file_ack_result = False
        start_time = time.time()
        timeout = 3.0
        
        # 等待 ACK 响应
        while start_time + timeout > time.time():
            msg = m_in.recv_match(blocking=True, timeout=0.5)
            if msg:
                print_msg_detail(msg, 0)
                if msg.msg_id == MAVLINK_MSG_ID_NET_FILE_COMMAND and msg.fields.get('net_file_cmd') == NET_FILE_ACK:
                    # 解析 ACK 数据
                    # 格式: <hii - 命令(2) + 返回值(4) + 文件句柄(4)
                    close_fmt = "<hii"
                    required_len = struct.calcsize(close_fmt)
                    if required_len <= len(msg.payload) - 2:
                        ack_cmd, close_return, op_fid = struct.unpack(close_fmt, msg.payload[2:2+required_len])
                        # 验证响应：命令匹配、返回值有效、句柄匹配
                        if ack_cmd == NET_FILE_CLOSE and close_return >= 0 and op_fid == file_op_fid:
                            file_ack_result = True
                            itry = 0
                            step += 1
                            break
        # 检查是否超时重试
        if not file_ack_result:
            itry += 1
            if itry >= 3:
                print(f"The retry count for the close has exceeded the limit ({itry}).")
                break
    
    # 返回传输结果
    if step > 3:
        print(f"transfer {len(file_data)} Bytes success.")
        return True
    return False

def net_file_read_file(m_in, m_out, fileto, filefrom) -> bool:
    """
    从远端设备拉取文件到本地（读取操作）
    
    工作流程:
        Step 1: 打开远端文件（NET_FILE_OPEN），获取文件大小和句柄
        Step 2: 分块读取文件数据（NET_FILE_READ）
        Step 3: 关闭远端文件（NET_FILE_CLOSE）
    
    参数:
        m_in: MAVLink 输入连接对象（用于接收文件数据）
        m_out: MAVLink 输出连接对象（用于发送读取命令）
        fileto: 本地目标文件路径
        filefrom: 远端源文件路径
    
    返回:
        bool: 传输成功返回 True，失败返回 False
    
    重试机制:
        - 每个操作最多重试 3 次
        - 每次等待 ACK 的超时时间为 3 秒
        - 接收消息的阻塞超时为 0.5 秒
    """
    step = 1  # 当前步骤：1-打开, 2-读取, 3-关闭
    file_op_mode = NET_FILE_OP_MODE_READ  # 操作模式：读取
    file_op_fid = 0  # 文件操作句柄（由远端返回）
    file_rd_pos = 0  # 当前读取位置
    file_ack_result = False  # ACK 结果标志
    file_length = 0  # 文件总长度

    # 打开本地文件用于写入
    with open(fileto, 'wb') as f:
        # ========================================================================
        # Step 1: 打开远端文件
        # ========================================================================
        itry = 0  # 重试计数器
        # 构造打开文件的命令数据包
        # 格式: <hI64s - 操作模式(2字节) + 保留字段(4字节) + 文件名(64字节)
        open_st = struct.pack('<hI64s', file_op_mode, 0, filefrom.encode('utf-8'))
        while step == 1:
            m_out.net_file_command_send(NET_FILE_OPEN, open_st)
            file_ack_result = False
            start_time = time.time()
            timeout = 3.0  # 超时时间：3秒
            
            # 等待 ACK 响应
            while start_time + timeout > time.time():
                msg = m_in.recv_match(blocking=True, timeout=0.5)
                if msg:
                    print_msg_detail(msg, 0)
                    if msg.msg_id == MAVLINK_MSG_ID_NET_FILE_COMMAND and msg.fields.get('net_file_cmd') == NET_FILE_ACK:
                        # 解析 ACK 数据
                        # 格式: <hiIh64s - 命令(2) + 文件句柄(4) + 文件长度(4) + 操作模式(2) + 文件名(64)
                        open_fmt = "<hiIh64s"
                        required_len = struct.calcsize(open_fmt)
                        if required_len <= len(msg.payload) - 2:
                            ack_cmd, open_return, f_length, op_mode, sz_name = struct.unpack(open_fmt, msg.payload[2:2+required_len])
                            # 验证响应：命令匹配、句柄有效、模式匹配
                            if ack_cmd == NET_FILE_OPEN and open_return >= 0 and op_mode == file_op_mode:
                                file_op_fid = open_return  # 保存文件句柄
                                file_length = f_length  # 保存文件总长度
                                file_ack_result = True
                                itry = 0
                                step += 1  # 进入下一步
                                break
            # 检查是否超时重试
            if not file_ack_result:
                itry += 1
                if itry >= 3:
                    print(f"The retry count for the open has exceeded the limit ({itry}).")
                    break
        # 如果打开失败，直接返回
        if step != 2:
            return False

        # ========================================================================
        # Step 2: 分块读取文件数据
        # ========================================================================
        itry = 0  # 重试计数器
        while step == 2:
            # 构造读取命令
            # 格式: <hiI - 请求长度(2) + 文件句柄(4) + 读取位置(4)
            # 注：此处请求长度为 224 字节
            read_st = struct.pack(f'<hiI', 224, file_op_fid, file_rd_pos)
            m_out.net_file_command_send(NET_FILE_READ, read_st)
            file_ack_result = False
            start_time = time.time()
            timeout = 3.0
            
            # 等待 ACK 响应（包含文件数据）
            while start_time + timeout > time.time():
                msg = m_in.recv_match(blocking=True, timeout=0.5)
                if msg:
                    print_msg_detail(msg, 2)  # 打印消息头详细信息
                    if msg.msg_id == MAVLINK_MSG_ID_NET_FILE_COMMAND and msg.fields.get('net_file_cmd') == NET_FILE_ACK:
                        # 解析 ACK 数据（包含变长数据字段）
                        # 固定部分格式: <hiiI - 命令(2) + 实际读取长度(4) + 文件句柄(4) + 读取位置(4)
                        read_fmt = "<hiiI"
                        required_len = struct.calcsize(read_fmt)
                        if len(msg.payload) - 2 >= required_len:
                            data_bytes = msg.payload[2:]
                            # 动态添加数据字段的格式
                            read_fmt += f"{len(data_bytes[required_len:])}s"
                            ack_cmd, read_return, op_fid, f_pos, rdata = struct.unpack(read_fmt, data_bytes)
                            rdata = rdata[:read_return]  # 截取实际数据（去掉 padding）
                            # 验证响应：命令匹配、长度匹配、句柄匹配
                            if ack_cmd == NET_FILE_READ and read_return == len(rdata) and op_fid == file_op_fid:
                                f.seek(f_pos)  # 定位到文件偏移
                                f.write(rdata)  # 写入文件数据
                                file_rd_pos = f_pos + read_return  # 更新读取位置
                                file_ack_result = True
                                itry = 0
                                # 检查是否读取完成
                                if file_rd_pos == file_length:
                                    step += 1  # 进入下一步
                                break
            # 检查是否超时重试
            if not file_ack_result:
                itry += 1
                if itry >= 3:
                    print(f"The retry count for the read (pos={file_rd_pos}) has exceeded the limit ({itry}).")
                    break

        # 如果读取未完成，直接返回
        if step != 3:
            return False

        # ========================================================================
        # Step 3: 关闭远端文件
        # ========================================================================
        itry = 0
        # 构造关闭文件命令
        close_st = struct.pack(f'<Hi', 0, file_op_fid)
        while step == 3:
            m_out.net_file_command_send(NET_FILE_CLOSE, close_st)
            file_ack_result = False
            start_time = time.time()
            timeout = 3.0
            
            # 等待 ACK 响应
            while start_time + timeout > time.time():
                msg = m_in.recv_match(blocking=True, timeout=0.5)
                if msg:
                    print_msg_detail(msg, 0)
                    if msg.msg_id == MAVLINK_MSG_ID_NET_FILE_COMMAND and msg.fields.get('net_file_cmd') == NET_FILE_ACK:
                        # 解析 ACK 数据
                        close_fmt = "<hii"
                        required_len = struct.calcsize(close_fmt)
                        if required_len <= len(msg.payload) - 2:
                            ack_cmd, close_return, op_fid = struct.unpack(close_fmt, msg.payload[2:2+required_len])
                            # 验证响应：命令匹配、返回值有效、句柄匹配
                            if ack_cmd == NET_FILE_CLOSE and close_return >= 0 and op_fid == file_op_fid:
                                file_ack_result = True
                                itry = 0
                                step += 1
                                break
            # 检查是否超时重试
            if not file_ack_result:
                itry += 1
                if itry >= 3:
                    print(f"The retry count for the close has exceeded the limit ({itry}).")
                    break
        # 返回传输结果
        if step > 3:
            # 获取文件总大小并打印成功消息
            print(f"transfer {f.seek(0, io.SEEK_END)} Bytes success.")
            return True

    return False

def net_file_verify_file(m_in, m_out, file_local, file_remote, md5hex_str) -> bool:
    """
    校验远端文件的完整性（通过 MD5 比对）
    
    工作流程:
        1. 计算本地文件的 MD5 或使用提供的 MD5 字符串
        2. 发送校验命令到远端（NET_FILE_VERIFY）
        3. 接收远端返回的 MD5 值并进行比对
    
    参数:
        m_in: MAVLink 输入连接对象（用于接收 ACK）
        m_out: MAVLink 输出连接对象（用于发送校验命令）
        file_local: 本地文件路径（用于计算 MD5）
        file_remote: 远端文件路径
        md5hex_str: MD5 的十六进制字符串（如果提供，则优先使用）
    
    返回:
        bool: 校验成功返回 True，失败返回 False
    
    校验结果:
        - verify_return == 0: 校验成功（MD5 匹配）
        - verify_return > 0:  校验失败（MD5 不匹配）
        - verify_return < 0:  校验错误（文件不存在或其他错误）
    
    重试机制:
        - 最多重试 3 次
        - 每次等待 ACK 的超时时间为 3 秒
        - 接收消息的阻塞超时为 2.5 秒
    """
    # 准备 MD5 数据
    if md5hex_str:
        # 如果提供了 MD5 十六进制字符串，直接转换为字节
        md5hex_data = bytes.fromhex(md5hex_str.replace(" ", ""))
    elif file_local:
        # 否则计算本地文件的 MD5
        if not os.path.exists(file_local):
            print(f"file ({file_local}) not exist.")
            return False

        f = open(file_local, 'rb')
        file_size = f.seek(0, io.SEEK_END)  # 获取文件大小
        f.seek(0)  # 重置文件指针
        md5_hash = hashlib.md5()
        md5_hash.update(f.read())  # 计算 MD5
        f.close()
        md5hex_data = md5_hash.digest()  # 获取二进制 MD5 值
        print(f"local file ({file_local}) \nmd5: {md5_hash.hexdigest()}")
    else:
        # 没有本地文件也没有提供 MD5，使用空字节
        md5hex_data = b''

    # ========================================================================
    # 发送校验命令并等待响应
    # ========================================================================
    itry = 0  # 重试计数器
    while True:
        # 构造校验命令数据包
        # 格式: <16s64s - MD5值(16字节) + 文件名(64字节)
        verify_st = struct.pack(f'<16s64s', md5hex_data, file_remote.encode('utf-8'))
        m_out.net_file_command_send(NET_FILE_VERIFY, verify_st)
        file_ack_result = False
        start_time = time.time()
        timeout = 3.0  # 超时时间：3秒
        
        # 等待 ACK 响应
        while start_time + timeout > time.time():
            msg = m_in.recv_match(blocking=True, timeout=2.5)
            if msg:
                print_msg_detail(msg, 0)
                if msg.msg_id == MAVLINK_MSG_ID_NET_FILE_COMMAND and msg.fields.get('net_file_cmd') == NET_FILE_ACK:
                    # 解析 ACK 数据
                    # 格式: <hi16s64s - 命令(2) + 校验结果(4) + 远端MD5(16) + 文件名(64)
                    verify_fmt = "<hi16s64s"
                    required_len = struct.calcsize(verify_fmt)
                    if required_len <= len(msg.payload) - 2:
                        ack_cmd, verify_return, fmd5, fname = struct.unpack(verify_fmt, msg.payload[2:2+required_len])
                        # 验证响应：命令匹配、文件名匹配
                        if ack_cmd == NET_FILE_VERIFY and fname.startswith(file_remote.encode('utf-8')+b'\0'):
                            file_ack_result = True
                            itry = 0
                            # 根据校验结果返回不同状态
                            if verify_return >= 0 :
                                if verify_return == 0 :
                                    # MD5 匹配，校验成功
                                    print(f"verify success: {verify_return}")
                                    return True
                                else:
                                    # MD5 不匹配，校验失败
                                    print(f"verify fail: {verify_return}")
                                    print(f"{file_remote} MD5: {fmd5.hex()}")
                                    return False
                            else:
                                # 校验错误（文件不存在等）
                                print(f"verify error: {verify_return}")
                                return False
                            break
        # 检查是否超时重试
        if not file_ack_result:
            itry += 1
            if itry >= 3:
                print(f"The retry count for the verify has exceeded the limit ({itry}).")
                break

    return False

def net_file_delete_file(m_in, m_out, file_remote) -> bool:
    """
    删除远端设备上的文件
    
    工作流程:
        1. 发送删除命令到远端（NET_FILE_DELETE）
        2. 等待远端返回删除结果
    
    参数:
        m_in: MAVLink 输入连接对象（用于接收 ACK）
        m_out: MAVLink 输出连接对象（用于发送删除命令）
        file_remote: 远端文件路径
    
    返回:
        bool: 删除成功返回 True，失败返回 False
    
    删除结果:
        - delete_return >= 0: 删除成功
        - delete_return < 0:  删除失败（文件不存在、权限错误等）
    
    重试机制:
        - 最多重试 3 次
        - 每次等待 ACK 的超时时间为 3 秒
        - 接收消息的阻塞超时为 0.5 秒
    """
    itry = 0  # 重试计数器
    while True:
        # 构造删除命令数据包
        # 格式: <64s - 文件名(64字节)
        delete_st = struct.pack(f'<64s', file_remote.encode('utf-8'))
        m_out.net_file_command_send(NET_FILE_DELETE, delete_st)
        file_ack_result = False
        start_time = time.time()
        timeout = 3.0  # 超时时间：3秒
        
        # 等待 ACK 响应
        while start_time + timeout > time.time():
            msg = m_in.recv_match(blocking=True, timeout=0.5)
            if msg:
                print_msg_detail(msg, 0)
                if msg.msg_id == MAVLINK_MSG_ID_NET_FILE_COMMAND and msg.fields.get('net_file_cmd') == NET_FILE_ACK:
                    # 解析 ACK 数据
                    # 格式: <hi64s - 命令(2) + 删除结果(4) + 文件名(64)
                    delete_fmt = "<hi64s"
                    required_len = struct.calcsize(delete_fmt)
                    if required_len <= len(msg.payload) - 2:
                        ack_cmd, delete_return, fname = struct.unpack(delete_fmt, msg.payload[2:2+required_len])
                        # 验证响应：命令匹配、文件名匹配
                        if ack_cmd == NET_FILE_DELETE and fname.startswith(file_remote.encode('utf-8')+b'\0'):
                            file_ack_result = True
                            itry = 0
                            # 根据删除结果返回不同状态
                            if delete_return >= 0 :
                                # 删除成功
                                print(f"delete success: {delete_return}")
                                return True
                            else:
                                # 删除失败
                                print(f"delete error: {delete_return}")
                                return False
                            break
        # 检查是否超时重试
        if not file_ack_result:
            itry += 1
            if itry >= 3:
                print(f"The retry count for the delete has exceeded the limit ({itry}).")
                break
    
    return False

def main_entry(args):
    """
    主入口函数：处理命令行参数并执行相应的文件操作

    工作流程:
        1. 建立 MAVLink 连接（支持串口和 UDP）
        2. 根据命令类型执行相应的文件操作
        3. 关闭连接

    参数:
        args: argparse 解析后的命令行参数对象

    支持的命令:
        - push: 推送本地文件到远端 (push <local> <remote>)
        - pull: 从远端拉取文件到本地 (pull <remote> <local>)
        - verify: 校验远端文件 (verify <remote> [--local <file> | --md5 <hash>])
        - delete: 删除远端文件 (delete <remote>)
    """
    device = str(args.device)

    if device.startswith('udp:'):
        # UDP 连接模式：通过 GroundControlStation 实现
        from src.Protocol.mavlink.fake_ground_control_station import GroundControlStation

        a = device.split(':')
        if len(a) != 3:
            print(f"udp device format error: {device}")
            return

        gcs = GroundControlStation(drone_ip=a[1])
        m_link = GCSSimMAVLinkLink(gcs)
        m_link.SYS_ID = args.sysid
        m_link.COMP_ID = args.compid
    else:
        # 串口连接模式
        m_link = SerialMAVLinkLink(
            port=device,
            baudrate=args.baudrate,
            sys_id=args.sysid,
            comp_id=args.compid
        )

    try:
        if args.command == "push":
            if net_file_write_file(m_link, m_link, args.local, args.remote):
                print(f"push ({args.local}) to ({args.remote}) success.")
        elif args.command == "pull":
            if net_file_read_file(m_link, m_link, args.local, args.remote):
                print(f"pull ({args.local}) from ({args.remote}) success.")
        elif args.command == "verify":
            net_file_verify_file(m_link, m_link, args.local, args.remote, args.md5)
        elif args.command == "delete":
            net_file_delete_file(m_link, m_link, args.remote)
    except KeyboardInterrupt:
        print("Keyboard Interrupt ...")
    finally:
        m_link.close()
##------------------------------------------------------------
# 命令行参数解析和程序入口
##------------------------------------------------------------

if __name__ == '__main__':
    import argparse
    
    # 创建主解析器
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=False, title="可用子命令", help="命令说明")

    # 全局参数（所有命令都可以使用）
    parser.add_argument("-baudrate", required=False, help="串口波特率（默认 115200）", type=int, default=115200)
    parser.add_argument("-device",   required=False, help="设备路径（默认 COM6，支持 udp:ip:port 格式）", type=str, default="COM6")
    parser.add_argument("-sysid",    required=False, help='MAVLink 源系统 ID（默认 0）', type=int, default=0)
    parser.add_argument("-compid",   required=False, help='MAVLink 源组件 ID（默认 0）', type=int, default=0)
    
    # 子命令：push（推送文件到远端）
    # 用法: python mav_net_file.py push <本地文件> <远程文件>
    parser_push = subparsers.add_parser("push", help="推送文件至远端")
    parser_push.add_argument("local", help="本地文件名")
    parser_push.add_argument("remote", help="远程文件名")
    
    # 子命令：pull（从远端拉取文件）
    # 用法: python mav_net_file.py pull <远程文件> <本地文件>
    parser_pull = subparsers.add_parser("pull", help="从远端拉取文件")
    parser_pull.add_argument("remote", help="远程文件名")
    parser_pull.add_argument("local", help="本地文件名")
    
    # 子命令：verify（校验远端文件完整性）
    # 用法: python mav_net_file.py verify <远程文件> [--local <本地文件> | --md5 <MD5字符串>]
    parser_verify = subparsers.add_parser("verify", help="校验远端文件")
    parser_verify.add_argument("remote", help='远程文件名', type=str)
    # 互斥参数：只能提供 local 或 md5 其中之一
    exclusive_group = parser_verify.add_mutually_exclusive_group()
    exclusive_group.add_argument("--local", required=False, help='本地文件名（用于计算 MD5）', type=str, default="")
    exclusive_group.add_argument("--md5", required=False, help='MD5码的Hex字符串', type=str, default="")
    
    # 子命令：delete（删除远端文件）
    # 用法: python mav_net_file.py delete <远程文件>
    parser_delete = subparsers.add_parser("delete", help="删除远端文件")
    parser_delete.add_argument("remote", help='远程文件名', type=str)

    # 解析命令行参数
    args = parser.parse_args()

    try:
        main_entry(args)
    except KeyboardInterrupt:
        print("Keyboard Interrupt ...")
    except Exception as e:
        print(e)