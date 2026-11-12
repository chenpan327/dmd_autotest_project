#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# from drama_editor_util.debug import debug_print
# from . import maya_com_func as maya_func
try:
    from . import com_math,com_func, com_web
except:
    import com_math, com_func, com_web

import base64
import copy
from collections import defaultdict
import numpy as np
import ctypes
import os
import codecs
import json
from struct import unpack, pack
import math
import time
import subprocess
import platform
import requests
import os
import sys

# 把当前文件所在路径加入sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import i18n.i18n as i18n
    from importlib import reload
    reload(i18n)
    _ = i18n.Translation()
except:
    _ = lambda x: x

from datetime import datetime
import logging
try:
    from utils.logger import logger
except ImportError:
    logger = logging.getLogger(__name__)


def _get_dll_class():
    try:
        from ..DLL import DLL
    except ImportError:
        from DLL import DLL
    return DLL


class DroneParam:
    def __init__(self):
        self.drone_type = "unknown"
        self.value = 0
        self.safe_dis = 0
        self.horizon_max_speed = 0
        self.vertical_up_max_speed = 0
        self.vertical_down_max_speed = 0
        self.max_speed = 0
        self.horizon_max_acc = 0
        self.vertical_max_acc = 0
        self.takeoff_land_safe_dis = 0
        self.eng_name = ''

    def object_to_dict(self):
        dictionary = {}
        dictionary.update(self.__dict__)
        return dictionary

    def dict_to_object(self, dictionary):
        # convert dict to object
        # debug_print("dt: ")
        self.drone_type = dictionary["name"]
        self.value = int(dictionary["value"])
        for param in dictionary["droneParams"]:
            if param["name"] == "safeDis":
                self.safe_dis = float(param["value"])
            if param["name"] == "horizonMaxSpeed":
                self.horizon_max_speed = float(param["value"])
            if param["name"] == "verticalUpMaxSpeed":
                self.vertical_up_max_speed = float(param["value"])
            if param["name"] == "verticalDownMaxSpeed":
                self.vertical_down_max_speed = float(param["value"])
            if param["name"] == "maxSpeed":
                self.max_speed = float(param["value"])
            if param["name"] == "horizonMaxAcc":
                self.horizon_max_acc = float(param["value"])
            if param["name"] == "verticalMaxAcc":
                self.vertical_max_acc = float(param["value"])
            if param["name"] == "takeoffLandSafeDis":
                self.takeoff_land_safe_dis = float(param["value"])
            if param["name"] == "engName":
                self.eng_name = str(param["value"])
                # debug_print(self.eng_name)


class DroneTypeManager:
    def __init__(self, drone_types):
        self.drone_type_list = drone_types
        self.drone_0_x_value_list = [5]
        self.drone_1_x_value_list = [5, 6, 111]

        # there is some drone use 1.x and 2.x
        self.drone_2_x_value_list = [10, 11, 12, 2, 4, 6, 9, 13, 14, 15, 19, 33, 20, 35, 111, 99]
        self.drone_3_x_value_list = [21, 22, 24, 25]
        self.drone_X_x_value_list = [81]

        self.drone_box_ground_placement = [21, 22, 24, 25, 31, 41, 81]
        self.drone_big_lantern_value_list = [3]

        # payload

        self.drone_have_yaw_attr = [28, 41, 42, 81] # 航向角 Y2 L3 X1
        self.drone_have_gimbal = [81] # 云台
        self.drone_have_lazer = [81]
        self.drone_have_fireworks_port_payload = [
            5, 6, 23,# 灯笼
            10, 12, 18, 20, 28, 81,# 烟花
            31, 32, 41 ,42, 81, # 高亮
            41, 42, # 爆闪
        ]
        self.drone_have_lantern = [5, 6, 23]
        self.drone_have_fireworks = [10, 12, 18, 20, 28, 81]
        self.drone_have_high_light = [31, 41, 42, 81]  # 高亮 V4 L3 X1 have_dazzle_drone_type
        self.drone_have_dazzle = [41, 42]  # 爆闪 L3

        self.drone_fireworks_have_angle = [81]

        self.fireworks_angle_table = {
            81: [
                # [-40, 0], [-40, 0],     # UpXp
                # [0, 40], [0, 40],       # UpXn
                # [-90, 90], [-90, 90],   # DownYp
                # [-90, 90], [-90, 90]    # DownYn
                [40, 65, 90], [40, 65, 90],
                [0, 30, 60, 90, 120, 150, 180], [0, 30, 60, 90, 120, 150, 180],
                [40, 65, 90], [40, 65, 90],
                [0, 30, 60, 90, 120, 150, 180], [0, 30, 60, 90, 120, 150, 180],
            ]
        }

        # high power mode
        self.regular_power = 0.55
        self.high_light_power = 0.8
        self.dazzle_power = 1

        self.max_total_high_light_second = -1  # s

        self.max_continuous_high_light_second = 2  # s
        self.high_light_interval_times = 5  #

        self.max_continuous_dazzle_second = 1.5 # s
        self.dazzle_interval_times = 8

    def find(self, drone_type_value):
        for drone_type in self.drone_type_list:
            if drone_type.value == drone_type_value:
                return drone_type
        return False

    def exist(self, drone_type_value):
        drone_type_value_list = []
        for drone_type in self.drone_type_list:
            drone_type_value_list.append(drone_type.value)
        if drone_type_value in drone_type_value_list:
            return True
        else:
            return False

    def exist_0_x(self):
        for value in self.drone_0_x_value_list:
            if self.exist(value):
                return True
        return False

    def exist_1_x(self):
        for value in self.drone_1_x_value_list:
            if self.exist(value):
                return True
        return False

    def exist_2_x(self):
        for value in self.drone_2_x_value_list:
            if self.exist(value):
                return True
        return False

    def exist_3_x(self):
        for value in self.drone_3_x_value_list:
            if self.exist(value):
                return True
        return False

    def exist_yaw_type(self):
        for value in self.drone_have_yaw_attr:
            if self.exist(value):
                return True
        return False

    def exist_high_light_type(self):
        for value in self.drone_have_high_light:
            if self.exist(value):
                return True
        return False

    def exist_dazzle_type(self):
        for value in self.drone_have_dazzle:
            if self.exist(value):
                return True
        return False

    def exist_lazer_type(self):
        for value in self.drone_have_lazer:
            if self.exist(value):
                return True
        return False

    def exist_gimbal_type(self):
        for value in self.drone_have_gimbal:
            if self.exist(value):
                return True
        return False

    def exist_big_lantern(self):
        for value in self.drone_big_lantern_value_list:
            if self.exist(value):
                return True
        return False


# need reconstruct
class light_operate_history:
    def __init__(self, start, end):
        self.start_time = start
        self.end_time = end
        self.source_func = ''
        self.ui_control = {}
        self.sphere_obj = []
        self.support_obj = []

    def record(self):
        pass
        '''
        global Dmd_UAVC_history_info
        item_name = str(self.start_time) + '_' + str(self.end_time) + '_' + self.source_func
        if Dmd_UAVC_history_info.has_key(item_name.decode('gb2312')):
            name = item_name + '_new'
            while Dmd_UAVC_history_info.has_key(name.decode('gb2312')):
                name += '_new'
            Dmd_UAVC_history_info[name] = (self.ui_control, self.sphere_obj, self.support_obj)
        else:
            Dmd_UAVC_history_info[item_name] = (self.ui_control, self.sphere_obj, self.support_obj)

        Dmd_UAVC_history_infosave2file()
        Dmd_UAVC_history_refresh()
        '''


class GLOBAL_STATUS:
    SUCCESS = 200
    NOTOKEN_ONLINE = 201
    UNKNOWN = 202
    CURL_ERR = 203
    JSON_ERR = 204
    AUTH_ERR = 403
    GET_TOKEN_ERR = 206
    GET_DETAIL_ERR = 207
    FAILED = 400
    INVALID_TOKEN = 401
    PARAM_ERR = 404
    MISS_TOKEN = 405
    HAS_LOGINED = 520
    ERROR_PERMISSION = 500


class PROJECT_PLANT:
    YZ = 0
    XZ = 1
    XY = 2


class ReturnType:
    Return = 1
    Land = 0


class HighPowerTimes:
    PowerType = 0
    s_time = 0
    e_time = 0


class HighPowerPort:
    DAZZLE = 2
    HIGH_LIGHT = 1
    CLOSE = 0



# class TakeoffTable:
#     def __init__(self):
#         self.table = {}
#
#     def set_frame(self, name, frame):
#         self.table[name] = frame
#
#     def get_frame(self, name):
#         if name in self.table:
#             return self.table[name]
#         return None

class UAV_opt_param:
    def __init__(self):
        self.pos = [0.0, 0.0, 0.0]
        self.frame = 0
        self.scale = 1.0
        self.acc_scale = 1.0


class UAV_opt:
    def __init__(self):
        self.name = ""
        self.data = {}


class UAVC_opt:
    def __init__(self):
        self.cluster = {}

    def get_max_scale(self, frame):
        max_scale = -1
        for obj in self.cluster:
            opt_obj = self.cluster[obj]
            # debug_print(opt_obj)
            max_scale = max(max_scale, opt_obj.data[frame].scale)
        return max_scale

    def get_max_acc_scale(self, frame):
        max_scale = 0
        for obj in self.cluster:
            opt_obj = self.cluster[obj]
            # debug_print(opt_obj)
            if frame in opt_obj.data:
                max_scale = min(max_scale, opt_obj.data[frame].acc_scale)
        return max_scale

    def get_all_pos(self, frame):
        poss = {}
        for obj in self.cluster:
            poss[obj.name] = obj.data[frame].pos



class DroneLightCube:
    def __init__(self, drone_row_column_height, bar_long_width, drone_light_time_list):
        self.drone_row_column_height = drone_row_column_height
        self.bar_long_width = bar_long_width
        self.drone_light_time_list = drone_light_time_list


class EasyLightModel:
    def __init__(self, name):
        self.name = name
        self.light_index = 0
        self.curve = ''

    def set_index(self, n):
        self.light_index = n

    def set_curve(self, func):
        self.curve = func


class CheckDroneBase:
    def __init__(self):
        self.id = 0
        self.nick_name = ""

        self.per_frame_pos = [0, 0, 0]

        self.cur_pos = [0, 0, 0]
        self.cur_speed = 0.0
        self.cur_horizon_speed = 0.0
        self.cur_horizon_speed_x = 0.0
        self.cur_horizon_speed_y = 0.0
        self.cur_vertical_speed = 0.0

        self.last_pos = [0, 0, 0]
        self.last_speed = 0.0
        self.last_horizon_speed = 0.0
        self.last_horizon_speed_x = 0.0
        self.last_horizon_speed_y = 0.0
        self.last_vertical_speed = 0.0

        self.horizon_acc = 0.0
        self.vertical_acc = 0.0

        self.takeoff_height = 10.0
        self.takeoff_end_frame = 0.0
        self.land_height = 10.0
        self.land_start_frame = float("inf")

        self.drone_value = 0
        self.param = DroneParam()

    def update_speed(self):
        self.last_speed = copy.deepcopy(self.cur_speed)
        self.last_horizon_speed = copy.deepcopy(self.cur_horizon_speed)
        self.last_horizon_speed_x = copy.deepcopy(self.cur_horizon_speed_x)
        self.last_horizon_speed_y = copy.deepcopy(self.cur_horizon_speed_y)
        self.last_vertical_speed = copy.deepcopy(self.cur_vertical_speed)

    def update_pos(self):
        self.last_pos = copy.deepcopy(self.cur_pos)
        self.cur_pos = copy.deepcopy(self.per_frame_pos)

    def calculate_speed(self, interval):
        move_dis = com_math.euclidean_distance(self.cur_pos, self.last_pos)
        move_horizon_dis = ((self.cur_pos[0] - self.last_pos[0]) ** 2 +
                            (self.cur_pos[1] - self.last_pos[1]) ** 2) ** 0.5
        move_vertical_dis = self.cur_pos[2] - self.last_pos[2]

        self.cur_speed = move_dis / interval
        self.cur_horizon_speed = move_horizon_dis / interval
        self.cur_horizon_speed_x = (self.cur_pos[0] - self.last_pos[0]) / interval
        self.cur_horizon_speed_y = (self.cur_pos[1] - self.last_pos[1]) / interval
        self.cur_vertical_speed = move_vertical_dis / interval

        # calculate acc
        self.horizon_acc = abs(self.cur_horizon_speed - self.last_horizon_speed) / interval
        self.horizon_acc = max(self.horizon_acc, abs(self.cur_horizon_speed_x - self.last_horizon_speed_x) / interval)
        self.horizon_acc = max(self.horizon_acc, abs(self.cur_horizon_speed_y - self.last_horizon_speed_y) / interval)

        self.vertical_acc = abs(self.cur_vertical_speed - self.last_vertical_speed) / interval


class SafetyChecker:
    def __init__(self, result_path="", check_redundancy=1.07):
        self.cur_frame = 0

        self.check_redundancy = check_redundancy

        self.drone_base_list = list()    # CheckDroneBase

        self.check_result = list()

        # coll
        self.min_collision = float("inf")
        self.min_collision_rate = 0

        # speed
        # value
        self.max_speed = 0
        self.max_horizon_speed = 0
        self.max_vertical_up_speed = 0
        self.max_vertical_down_speed = 0

        self.max_acc = 0
        self.max_horizon_acc = 0
        self.max_vertical_acc = 0

        # rate
        self.max_speed_rate = 0
        self.max_horizon_speed_rate = 0
        self.max_vertical_up_speed_rate = 0
        self.max_vertical_down_speed_rate = 0

        self.max_acc_rate = 0
        self.max_horizon_acc_rate = 0
        self.max_vertical_acc_rate = 0

        self.result_path = result_path
        if self.result_path:
            if not os.path.exists(self.result_path):
                os.makedirs(os.path.dirname(self.result_path), exist_ok=True)
            with open(self.result_path, 'w') as f:
                f.write("frames,id1,id2,error,error value\n")

    def set_frame(self, fr):
        self.cur_frame = fr

    def check_collision(self, obj1, obj2, is_takeoff_land=False):
        if is_takeoff_land:
            safe_dis = min(obj1.param.takeoff_land_safe_dis, obj2.param.takeoff_land_safe_dis)
        else:
            safe_dis = min(obj1.param.safe_dis, obj2.param.safe_dis)

        if (
                obj1.per_frame_pos[0] - obj2.per_frame_pos[0]) >= safe_dis or (
                obj1.per_frame_pos[1] - obj2.per_frame_pos[1]) >= safe_dis or (
                obj1.per_frame_pos[2] - obj2.per_frame_pos[2]) >= safe_dis:
            return
        cur_dis = com_math.euclidean_distance(obj1.per_frame_pos, obj2.per_frame_pos)
        if cur_dis < safe_dis:
            self.check_result.append([str(self.cur_frame), str(obj1.id), str(obj2.id), "碰撞", str(round(cur_dis, 3))])

        self.min_collision = min(cur_dis, self.min_collision)

    def check_speed(self, obj):
        # speed
        if obj.cur_speed > obj.param.max_speed:
            self.check_result.append([str(self.cur_frame), str(obj.id), "", "超合速度", str(round(obj.cur_speed, 3))])

        if obj.cur_horizon_speed > obj.param.horizon_max_speed:
            self.check_result.append([str(self.cur_frame), str(obj.id), "", "超水平速度", str(round(obj.cur_horizon_speed, 3))])

        if obj.cur_vertical_speed > obj.param.vertical_up_max_speed:
            self.check_result.append([str(self.cur_frame), str(obj.id), "", "超上升速度", str(round(obj.cur_vertical_speed, 3))])

        if obj.cur_vertical_speed < obj.param.vertical_down_max_speed:
            self.check_result.append([str(self.cur_frame), str(obj.id), "", "超下降速度", str(round(obj.cur_vertical_speed, 3))])

        # acceleration
        if obj.horizon_acc > obj.param.horizon_max_acc:
            self.check_result.append([str(self.cur_frame), str(obj.id), "", "超水平加速度", str(round(obj.horizon_acc, 3))])

        if obj.vertical_acc > obj.param.vertical_max_acc:
            self.check_result.append([str(self.cur_frame), str(obj.id), "", "超垂直加速度", str(round(obj.vertical_acc, 3))])

        self.max_speed = max(obj.cur_speed, self.max_speed)
        self.max_horizon_speed = max(obj.cur_horizon_speed, self.max_horizon_speed)
        self.max_vertical_up_speed = max(obj.cur_vertical_speed, self.max_vertical_up_speed)
        self.max_vertical_down_speed = min(obj.cur_vertical_speed, self.max_vertical_down_speed)
        self.max_horizon_acc = max(obj.horizon_acc, self.max_horizon_acc)
        self.max_vertical_acc = max(obj.vertical_acc, self.max_vertical_acc)

    def check_speed_write_in_file(self, obj):
        result = ""
        self.max_speed = max(obj.cur_speed, self.max_speed)
        self.max_horizon_speed = max(obj.cur_horizon_speed, self.max_horizon_speed)
        self.max_vertical_up_speed = max(obj.cur_vertical_speed, self.max_vertical_up_speed)
        self.max_vertical_down_speed = min(obj.cur_vertical_speed, self.max_vertical_down_speed)
        self.max_horizon_acc = max(obj.horizon_acc, self.max_horizon_acc)
        self.max_vertical_acc = max(obj.vertical_acc, self.max_vertical_acc)

        cur_max_speed_rate = obj.cur_speed / obj.param.max_speed
        cur_max_horizon_speed_rate = obj.cur_horizon_speed / obj.param.horizon_max_speed
        cur_max_vertical_up_speed_rate = obj.cur_vertical_speed / obj.param.vertical_up_max_speed
        cur_max_vertical_down_speed_rate = obj.cur_vertical_speed / obj.param.vertical_down_max_speed
        cur_max_horizon_acc_rate = obj.horizon_acc / obj.param.horizon_max_acc
        cur_max_vertical_acc_rate = obj.vertical_acc / obj.param.vertical_max_acc

        self.max_speed_rate = max(cur_max_speed_rate, self.max_speed_rate)
        self.max_horizon_speed_rate = max(cur_max_horizon_speed_rate, self.max_horizon_speed_rate)
        self.max_vertical_up_speed_rate = max(cur_max_vertical_up_speed_rate, self.max_vertical_up_speed_rate)
        self.max_vertical_down_speed_rate = min(cur_max_vertical_down_speed_rate, self.max_vertical_down_speed_rate)
        self.max_horizon_acc_rate = max(cur_max_horizon_acc_rate, self.max_horizon_acc_rate)
        self.max_vertical_acc_rate = max(cur_max_vertical_acc_rate, self.max_vertical_acc_rate)

        # speed
        if cur_max_speed_rate > self.check_redundancy:
            result += f"{self.cur_frame},{obj.nick_name},,{_(u'超合速度')},{round(obj.cur_speed, 3)}\n"

        if cur_max_horizon_speed_rate > self.check_redundancy:
            result += f"{self.cur_frame},{obj.nick_name},,{_(u'超水平速度')},{round(obj.cur_horizon_speed, 3)}\n"

        if cur_max_vertical_down_speed_rate > self.check_redundancy:
            result += f"{self.cur_frame},{obj.nick_name},,{_(u'超下降速度')},{round(obj.cur_vertical_speed, 3)}\n"

        # acceleration
        if cur_max_horizon_acc_rate > self.check_redundancy:
            result += f"{self.cur_frame},{obj.nick_name},,{_(u'超水平加速度')},{round(obj.horizon_acc, 3)}\n"
        if cur_max_vertical_acc_rate > self.check_redundancy:
            result += f"{self.cur_frame},{obj.nick_name},,{_(u'超垂直加速度')},{round(obj.vertical_acc, 3)}\n"

        return result

    def check_collision_write_in_file(self, objs, sd):
        s_q = sd ** 2
        grid = defaultdict(list)

        result = ""

        for v_name, obj in objs.items():
            i = int(np.floor(obj.cur_pos[0] / sd))
            j = int(np.floor(obj.cur_pos[1] / sd))
            k = int(np.floor(obj.cur_pos[2] / sd))
            grid[(i, j, k)].append(obj)

        for v_name, obj in objs.items():
            i = int(np.floor(obj.cur_pos[0] / sd))
            j = int(np.floor(obj.cur_pos[1] / sd))
            k = int(np.floor(obj.cur_pos[2] / sd))
            for di in range(-1, 2):
                for dj in range(-1, 2):
                    for dk in range(-1, 2):
                        neighbor_grid = (i + di, j + dj, k + dk)
                        if neighbor_grid not in grid:
                            continue

                        for neighbor_obj in grid[neighbor_grid]:
                            if neighbor_obj.id <= obj.id:
                                continue

                            dx = obj.cur_pos[0] - neighbor_obj.cur_pos[0]
                            dy = obj.cur_pos[1] - neighbor_obj.cur_pos[1]
                            dz = obj.cur_pos[2] - neighbor_obj.cur_pos[2]
                            dis = dx ** 2 + dy ** 2 + dz ** 2
                            if dis < s_q:
                                dis = dis ** 0.5
                                dis = max(0.01, dis)
                                cur_min_collision_rate = sd / dis
                                if cur_min_collision_rate > self.check_redundancy:
                                    result += f"{self.cur_frame},{obj.nick_name},{neighbor_obj.nick_name},{_(u'碰撞')},{round(dis, 3)}\n"
                                self.min_collision = min(dis, self.min_collision)
                                self.min_collision_rate = max(cur_min_collision_rate, self.min_collision_rate)

        return result
                        

class SmoothTools:
    def __init__(self):
        self.fix_acc = 0.0
        self.fix_velocity = 0.0
        self.fix_time = 0.0
        self.fix_acc_acc = 0.0
        self.scale = 500
        self.T = []
        self.dt = 0.0
        self.spatium = []
        self.dis = 0.0

    def get_spatium(self, time):
        if time > self.fix_time:
            time = self.fix_time
        if time < 0:
            time = 0.0

        index = int(self.scale * (time / self.fix_time)) - 1
        if index < 0:
            index = 0
        return self.spatium[index] * self.dis

    def get_spatium_2d(self, time, x, y):
        if time > self.fix_time:
            time = self.fix_time
        if time < 0:
            time = 0.0

        index = int(self.scale * (time / self.fix_time)) - 1
        if index < 0:
            index = 0

        d = x ** 2 + y ** 2
        d = d ** 0.5
        dis = self.spatium[index] * self.dis
        x_d = x / d * dis
        y_d = y / d * dis

        return [x_d, y_d]

    def get_spatium_3d(self, time, x, y, z):
        if time > self.fix_time:
            time = self.fix_time
        if time < 0:
            time = 0.0

        index = int(self.scale * (time / self.fix_time)) - 1
        if index < 0:
            index = 0
        # print("get index ", index, time)

        d = x ** 2 + y ** 2 + z ** 2
        d = d ** 0.5
        dis = self.spatium[index] * self.dis
        x_d = x / d * dis
        y_d = y / d * dis
        z_d = z / d * dis

        return [x_d, y_d, z_d]

    def set_scale(self, scale):
        self.scale = scale

    def get_fix_time(self):
        return self.fix_time

    def get_fix_velocity(self):
        return self.fix_velocity

    def get_fix_acc(self):
        return self.fix_acc

    def get_fix_acc_acc(self):
        return self.fix_acc_acc

    def smooth(self, estimated_time, speed_max, acc_max, dis):
        # print(u"预估时间", estimated_time)
        # print(u"speed", speed_max)
        # print(u"acc", acc_max)
        # print(u"距离", dis)

        self.get_smooth_param(estimated_time, speed_max / dis, acc_max / dis)

        ThetaStart = 0.0
        self.dis = ThetaEnd = dis
        t = []
        s = []
        Theta = []
        dt = 1.0 / self.scale * self.fix_time
        for i in range(self.scale):
            t.append(i * 1.0 / self.scale * self.fix_time)
            s.append(0.0)
            Theta.append(0.0)

        # print(self.scale)
        for i in range(self.scale):
            # print(i)
            # print(t, V, A, J, T, Tf)
            s[i] = self.get_scaling_curve(t[i], self.fix_velocity, self.fix_acc, self.fix_acc_acc, self.T,
                                          self.fix_time)
            # print(i, s[i])
            Theta[i] = ThetaStart + s[i] * (ThetaEnd - ThetaStart)
            # if i > 1:
            #     sd[i - 1] = (s[i] - s[i - 1]) / dt
            #
            # if i > 2:
            #     sdd[i - 2] = (sd[i - 1] - sd[i - 2]) / dt

        self.dt = dt
        self.spatium = s

    def get_smooth_param(self, estimated_time, speed_max, acc_max):
        # input param
        Tf = estimated_time
        v = speed_max
        a = acc_max
        # print("input param ", estimated_time, speed_max, acc_max)

        i = 0
        exitg1 = False

        T = []
        for i in range(7):
            T.append(0.0)

        i = 0
        while ((not exitg1) and (i < 1000)):
            J = a * a * v / ((Tf * v * a - v * v) - a)
            T[0] = a / J
            T[1] = v / a - a / J

            T[2] = T[0]
            T[3] = (Tf - 2.0 * a / J) - 2.0 * v / a
            T[4] = T[2]
            T[5] = T[1]
            T[6] = T[0]
            if (T[1] < -1.0E-6):
                a = (v * J) ** 0.5
                i += 1
            elif (T[3] < -1.0E-6):
                v = Tf * a / 2.0 - a * a / J
                i += 1
            elif (J < -1.0E-6):
                Tf = (v * v + a) / (v * a) + 0.1
                i += 1
            else:
                exitg1 = True

        self.fix_acc = a
        self.fix_velocity = v
        self.fix_time = Tf
        self.T = T
        self.fix_acc_acc = J

        # print(u"A 加速度 ", self.fix_acc)
        # print(u"V 速度 ", self.fix_velocity)
        # print(u"Tf 总耗时 ", self.fix_time)
        # print(u"J 加加速度 ", self.fix_acc_acc)

    def get_scaling_curve(self, t, V, A, J, T, Tf):
        # print(t, V, A, J, T, Tf)
        s = 0.0
        dt = 0.0
        if t >= 0.0 and t <= T[0]:
            s = 1 / 6.0 * J * (t ** 3)
        elif t > T[0] and t <= (T[0] + T[1]):
            dt = t - T[0]
            s = (0.5 * A * (dt * dt) + A * A / (2.0 * J) * dt) + (A ** 3.0) / (6.0 * (J * J))
        elif t > (T[0] + T[1]) and t <= (T[0] + T[1] + T[2]):
            dt = t - T[0] - T[1]
            s = ((((-1 / 6.0 * J * (dt ** 3) + 0.5 * A * (dt * dt)) + (A * T[1] + A * A / (2.0 * J)) * dt) + 0.5 * A * (
                    T[1] * T[1])) + A * A / (2.0 * J) * T[1]) + (A ** 3) / (6.0 * (J * J))
        elif t > (T[0] + T[1] + T[2]) and t <= (T[0] + T[1] + T[2] + T[3]):
            dt = t - T[0] - T[1] - T[2]
            s = V * dt - 1 / 6.0 * J * (T[2] ** 3) + 0.5 * A * (T[2] * T[2]) + (
                    A * T[1] + A * A / (2.0 * J)) * T[2] + 0.5 * A * (T[1] * T[1]) + A * A / (2.0 * J) * T[1] + (
                        A ** 3) / (6.0 * (J * J))
        elif t > (T[0] + T[1] + T[2] + T[3]) and t <= (T[0] + T[1] + T[2] + T[3] + T[4]):
            dt = Tf - t - T[0] - T[1]
            s = 1.0 - (((((-1 / 6.0 * J * (dt ** 3) + 0.5 * A * (dt * dt)) + (
                    A * T[1] + A * A / (2.0 * J)) * dt) + 0.5 * A * (T[1] * T[1])) + A * A / (2.0 * J) * T[1]) + (
                               A ** 3.0) / (6.0 * (J * J)))
        elif t > (T[0] + T[1] + T[2] + T[3] + T[4]) and t <= (T[0] + T[1] + T[2] + T[3] + T[4] + T[5]):
            dt = Tf - t - T[0]
            s = 1.0 - ((0.5 * A * (dt * dt) + A * A / (2.0 * J) * dt) + (A ** 3.0) / (6.0 * (J * J)))
        elif t > (T[0] + T[1] + T[2] + T[3] + T[4] + T[5]) and t <= (
                T[0] + T[1] + T[2] + T[3] + T[4] + T[5] + T[6] + 100000.0):
            s = 1.0 - 1 / 6.0 * J * ((Tf - t) ** 3)
        else:
            s = 0.0

        return s


class Drone:
    def __init__(self, id=0):
        self.id = id
        self.param = DroneParam()
        self.start_pos = [0.0, 0.0, 0.0]
        self.end_pos = [0.0, 0.0, 0.0]
        self.pos = [0.0, 0.0, 0.0]
        self.speed = 0
        self.horizon_speed = 0
        self.vertical_speed = 0
        self.horizon_speed_x = 0
        self.horizon_speed_y = 0
        self.takeoff = False
        self.takeoff_time = 0.0  # second
        self.takeoff_end_frame = 0  # frame
        self.takeoff_end = False
        self.takeoff_speed = 0.0
        self.takeoff_invterval = 0  # ms
        self.land = False
        self.land_time = 0.0  # second
        self.land_start = False
        self.land_start_frame = 0  # frame
        self.land_speed = 0.0
        self.land_invterval = 0  # ms
        self.dis_xy = 0.0
        self.dis_z = 0.0
        self.wp_time = 0.0  # second
        self.wp_dis = 0.0
        self.arrived = False
        self.up_time = 0.0
        self.takeoff_height = 0.0
        self.land_height = 0.0
        self.down_time = 0.0
        self.return_type = 0
        self.name = "dmd" + str(self.id)
        self.uv = []
        self.closet_point = []


class DramaEditorUser:
    def __init__(self):
        # user json init it
        self.name = ""
        self.description = ""
        self.expired = ""
        self.maxActivate = 5
        self.areas = []
        self.dramaEditorVersion = ""
        self.dramaEditorFuncs = []
        self.droneTypes = []
        self.status = 1
        self.active_status = 0
        self.active_time = ""
        self.password = ""
        self.remember = False
        self.bl_auto_login = False

    def init(self, temp):
        self.status = temp["status"]
        self.name = temp["name"]
        self.id = temp["id"]
        self.description = temp["description"]
        self.expired = temp["expired"]
        self.maxActivate = temp["maxActivate"]
        self.areas = temp["areas"]
        self.dramaEditorVersion = temp["dramaEditorVersion"]
        self.dramaEditorFuncs = temp["dramaEditorFuncs"]
        self.droneTypes = temp["droneTypes"]
        self.login = ""
        self.auto_login = ""
        self.logout = ""

        self.expired = self.expired.split("T")[0]

    def init_active(self, temp):
        self.active_status = temp["status"]
        self.maxActivate = temp["maxActivate"]
        self.active_time = temp["created"]

    def set_login(self, func):
        self.login = func

    def set_auto_login(self, func):
        self.auto_login = func

    def set_logout(self, func):
        self.logout = func


class SettingParam(object):
    def __init__(self, frame_time, version):
        self.ui_name = ""

        self.ui_start_time = ""
        self.ui_end_time = ""
        self.ui_takeoff_start = ""
        self.ui_takeoff_end = ""
        self.ui_land_start = ""
        self.ui_land_end = ""
        self.ui_takeoff_height = ""
        self.ui_land_height = ""

        self.ui_takeoff_safe_radius = ""
        self.ui_takeoff_collision = ""
        self.ui_pos_fps = ""
        self.ui_light_fps = ""
        self.ui_scene_fps = ""
        self.ui_drone_type = ""

        self.drone_param_list = []
        self.cur_drone_type = DroneParam()

        self.setting = None
        self.indoor_led_num = 4
        self.frame_time = frame_time
        self.fps = 1.0 / self.frame_time
        self.version = version


class Param:
    def __init__(self, param_name, value):
        self.param_name = param_name
        self.param_value = value
        self.exist = False

    def storage(self):
        pass


class PermanentParam(Param):
    def __init__(self, param_name, value, storage_file_path):
        Param.__init__(self, param_name, value)
        self.storage_file_path = storage_file_path
        cfg_json = {}
        if os.path.exists(self.storage_file_path):
            cfg_file = codecs.open(self.storage_file_path, 'r', 'utf-8')
            try:
                cfg_json = json.load(cfg_file)
            except:
                print("Configure file load fail.")
            cfg_file.close()
            # if cfg_json.has_key(self.param_name):
            if self.param_name in cfg_json:
                self.param_value = cfg_json[self.param_name]
                self.exist = True

    def storage(self):
        cfg_json = {}

        # read back
        if os.path.exists(self.storage_file_path):
            with codecs.open(self.storage_file_path, 'r', 'utf-8') as cfg_file:
                try:
                    cfg_json = json.load(cfg_file)
                except:
                    print("Configure file load fail.")
                finally:
                    cfg_file.close()

        backup_cfg = cfg_json.copy()
        # add new param
        cfg_json[self.param_name] = self.param_value

        # write params
        with codecs.open(self.storage_file_path, 'w', 'utf-8') as cfg_file:
            try:
                cfg_file.write(json.dumps(cfg_json, sort_keys=True, indent=4))
                print("Write parameter success: {}".format(self.param_name))
                return True
            except Exception as e:
                print("Write parameter fail: ", str(e))
                cfg_file.write(json.dumps(backup_cfg, sort_keys=True, indent=4))
                # cmds.confirmDialog(title=_(u'保存参数'), icon='critical', message=_(u"保存参数失败"))
                ctypes.windll.user32.MessageBoxW(0, (u"保存参数失败"), (u'保存参数'), 0x30)
                return False

    def set_value(self, value):
        self.param_value = value
        if self.storage():
            self.exist = True

    def get_value(self):
        return self.param_value

    def exist(self):
        return self.exist

class PermanentParam_CRYPT(Param):
    dll = None
    def __init__(self, param_name, value, storage_file_path, dll=None):
        Param.__init__(self, param_name, value)
        self.storage_file_path = storage_file_path
        # if PermanentParam_CRYPT.dll is None and dll_path is not None:
        #     PermanentParam_CRYPT.dll = _get_dll_class()(dll_path)
        if dll:
            PermanentParam_CRYPT.dll = dll

        if os.path.exists(self.storage_file_path):
            try:
                cfg_file = codecs.open(self.storage_file_path, 'r', 'utf-8')
                cfg_json = json.load(cfg_file)
                encrypt_result = PermanentParam_CRYPT.dll.encrypt_file(self.storage_file_path)
                cfg_file.close()
            except Exception as e:
                cfg_json_str = PermanentParam_CRYPT.dll.decrypt_file(self.storage_file_path)
                cfg_json = json.loads(cfg_json_str)
            # if cfg_json.has_key(self.param_name):
            if self.param_name in cfg_json:
                self.param_value = cfg_json[self.param_name]
                self.exist = True
            else:
                self.storage()
                self.exist = True
        else:
            self.storage()
            self.exist = True

    def storage(self):
        cfg_json = {}

        # read back
        if os.path.exists(self.storage_file_path):
            try:
                cfg_json_str = PermanentParam_CRYPT.dll.decrypt_file(self.storage_file_path)
                cfg_json = json.loads(cfg_json_str)
            except Exception as e:
                logger.warning("Configure file load fail: %s", e)

        backup_cfg = cfg_json.copy()
        # add new param
        cfg_json[self.param_name] = self.param_value

        status = False

        # write params
        with codecs.open(self.storage_file_path, 'w', 'utf-8') as cfg_file:
            try:
                cfg_file.write(json.dumps(cfg_json, sort_keys=True, indent=4))
                logger.info("Write parameter success: %s", self.param_name)
                status = True
            except Exception as e:
                logger.warning("Write parameter fail: %s", e)
                cfg_file.write(json.dumps(backup_cfg, sort_keys=True, indent=4))
                # cmds.confirmDialog(title=_(u'保存参数'), icon='critical', message=_(u"保存参数失败"))
                ctypes.windll.user32.MessageBoxW(0, "保存参数失败", '保存参数', 0x30)
                status = False

        PermanentParam_CRYPT.dll.encrypt_file(self.storage_file_path)
        return status


    def set_value(self, value):
        self.param_value = value
        if self.storage():
            self.exist = True

    def get_value(self):
        return self.param_value

    def exist(self):
        return self.exist



class GetOffsetByLog:
    def __init__(self, path):
        self.window_size = 10
        self.last_location = [0, 0, 0]
        self.all_point = 0
        self.loc_origin = [0, 0, 0]
        self.LOCATION_SCALING_FACTOR = 0.011131884502145034
        self.DEG_TO_RAD = 0.017453292519943295769236907684886
        self.path = path


    def get_pos(self):
        with open(self.path, "rb") as f:
            bin_data = f.read()
        read_buffer = list(bin_data)

        all_byte_data = self.getFileBytes(read_buffer)
        all_data = self.set_data(all_byte_data)
        return self.save_data(all_data)


    def get_String(self, arrayList: list, index=0, length=1) -> str:
        """
        The intercept list converts bytes to an ASCII string
        :param arrayList:Read the list of bytes obtained from the bin file
        :param index:Initial subscript
        :param length:The length of the cut
        :return:The converted string
        """
        resStr = ''
        for j in range(index, length):
            if arrayList[j:j + 1][0] != 0:
                resStr += str(chr(arrayList[j:j + 1][0]))
        return resStr

    def getFileBytes(self, readList: list) -> dict:
        """
        Parse the Bin file for a collection of bytes
        :param readList: Read the list of bytes obtained from the bin file
        :return: allData: dict[str,list[list]]
        """
        headers = {}
        messages = {}
        lineNum = 0
        i = 0
        while i < len(readList):
            if i > 1 and readList[i - 2] == 163 and readList[i - 1] == 149 and readList[i] == 128:
                header = {
                    "type": '',
                    "length": '',
                    "name": '',
                    "format": '',
                    "fields": '',
                }
                index = i + 1
                if True:
                    length = 1
                    bytes = readList[index:index + length]
                    header["type"] = int(bytes[0])
                    index = index + length
                if True:
                    length = 1
                    bytes = readList[index:index + length]
                    header["length"] = int(bytes[0])
                    index = index + length
                if True:
                    length = 4
                    name = self.get_String(readList, index, index + length)
                    header["name"] = name
                    index = index + length
                if True:
                    length = 16
                    format = self.get_String(readList, index, index + length)
                    header["format"] = format
                    index = index + length
                if True:
                    length = 64
                    fields = self.get_String(readList, index, index + length)
                    header["fields"] = fields
                headers[int(header["type"])] = header
                messages[header["name"]] = []
                lineNum = lineNum + 1
                i += 86
            if i > 1 and readList[i - 2] == 163 and readList[i - 1] == 149 and readList[i] != 128:
                index = i + 0
                if True:
                    length = 1
                    bytes = readList[index:index + length]
                    header = headers.get(bytes[0])
                    index = index + length
                if header is not None:
                    format = header["format"]
                    name = header["name"]
                    i += header["length"] - 1
                    datas = [lineNum, '0001-01-01 00:00:00.000', name]
                    lineNum = lineNum + 1

                    for s in range(len(format)):
                        data = 0.0
                        f = format[s]
                        if f == 'f':
                            length = 4
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(4)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<f', pack('4B', *bytes))[0]
                            index = index + length
                        elif f == 'q':
                            length = 8
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(8)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<q', pack('8B', *bytes))[0]
                            index = index + length
                        elif f == 'Q':
                            length = 8
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(8)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<Q', pack('8B', *bytes))[0]
                            index = index + length
                        elif f == 'i':
                            length = 4
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(4)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<i', pack('4B', *bytes))[0]
                            index = index + length
                        elif f == 'I':
                            length = 4
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(4)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<I', pack('4B', *bytes))[0]
                            index = index + length
                        elif f == 'b':
                            length = 1
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(1)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<b', pack('1B', *bytes))[0]
                            index = index + length
                        elif f == 'B':
                            length = 1
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(1)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<B', pack('1B', *bytes))[0]
                            index = index + length
                        elif f == 'M':
                            length = 1
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(1)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<B', pack('1B', *bytes))[0]
                            index = index + length
                        elif f == 'L':
                            length = 4
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(4)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<I', pack('4B', *bytes))[0]
                            index = index + length
                        elif f == 'h':
                            length = 2
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(2)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<h', pack('2B', *bytes))[0]
                            index = index + length
                        elif f == 'H':
                            length = 2
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(2)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<H', pack('2B', *bytes))[0]
                            index = index + length
                        elif f == 'n':
                            length = 4
                            data = self.get_String(readList, index, index + length)
                            index = index + length
                        elif f == 'N':
                            length = 16
                            data = self.get_String(readList, index, index + length)
                            index = index + length
                        elif f == 'Z':
                            length = 64
                            data = self.get_String(readList, index, index + length)
                            index = index + length
                        elif f == 'c':
                            length = 2
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(2)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<H', pack('2B', *bytes))[0]
                            index = index + length
                        elif f == 'C':
                            length = 2
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(2)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<H', pack('2B', *bytes))[0]
                            index = index + length
                        elif f == 'e':
                            length = 4
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(4)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<i', pack('4B', *bytes))[0]
                            index = index + length
                        elif f == 'E':
                            length = 4
                            bytes = readList[index:index + length] if index < len(readList) else com_math.zeros(4)
                            if len(bytes) < length:
                                bytes.extend(com_math.zeros(length - len(bytes)))
                            data = unpack('<I', pack('4B', *bytes))[0]
                            index = index + length
                        datas.append(data)
                    messages[header["name"]].append(datas)
            i += 1
        return messages

    def set_data(self, uavDataDict: dict) -> dict:
        UAV_Evt_dict = {}
        for keyName in uavDataDict.keys():
            if UAV_Evt_dict.get(keyName) is None:
                UAV_Evt_dict[keyName] = []
            # get uav imu data
            if str(keyName) == 'GPS0':
                gps_append = UAV_Evt_dict["GPS0"].append
                for gpsData in uavDataDict["GPS0"]:
                    if gpsData[3] != 6 or pow(pow(gpsData[15], 2) + pow(gpsData[16], 2), 0.5) > 0.08:
                        continue
                    else:
                        gps_append(
                            [gpsData[0], gpsData[12], gpsData[13], gpsData[14], gpsData[15], gpsData[16], gpsData[17]])
            if str(keyName) == 'IMU0' and len(uavDataDict["IMU0"]) != 0:
                start = 0
                end = 0
                imu_append = UAV_Evt_dict["IMU0"].append
                for imuData in uavDataDict["IMU0"]:
                    if math.sqrt(imuData[6] ** 2 + imuData[7] ** 2) < 0.025:
                        if start == 0:
                            start = imuData[0]
                        else:
                            end = imuData[0]
                    else:
                        if start != 0 and end != 0:
                            imu_append([start, end])
                        start = 0
                        end = 0
        return UAV_Evt_dict

    def window_filter(self, window_list: list):
        location = []
        lat = 0
        lon = 0
        alt = 0
        for data in window_list:
            location.append(pow(pow(data[1] % 10, 2) + pow(data[2] % 100, 2) + pow(data[3] % 1000, 2), 0.5))
            lat += data[1]
            lon += data[2]
            alt += data[3]
        now_location = [lat / self.window_size, lon / self.window_size, alt / self.window_size]
        if com_math.python_std(location) < 5 and pow(
                (now_location[0] - self.last_location[0]) ** 2 + (now_location[1] - self.last_location[1]) ** 2 + (
                        now_location[2] - self.last_location[2]) ** 2, 0.5) > 30:
            return True
        else:
            return False

    def delete_repeat(self, res_list):
        result = []
        delete_point = []
        for i in range(0, len(res_list) - 1):
            if i in delete_point:
                continue
            for j in range(i + 1, len(res_list)):
                if pow((res_list[i][0] / 10 - res_list[j][0] / 10) ** 2 + (res_list[i][1] - res_list[j][1]) ** 2, 0.5) < 20:
                    if math.sqrt(res_list[i][3] ** 2 + res_list[i][4] ** 2 + res_list[i][5] ** 2) < math.sqrt(
                            res_list[j][3] ** 2 + res_list[j][4] ** 2 + res_list[j][5] ** 2):
                        delete_point.append(j)
                    else:
                        delete_point.append(i)
        for i in range(0, len(res_list)):
            if i in delete_point:
                continue
            result.append([res_list[i][0], res_list[i][1], res_list[i][2]])
        return result

    def save_data(self, dataDict: dict):
        window_list = [0] * self.window_size
        count = 0
        index = 0
        res_point = []
        for data in dataDict["GPS0"]:
            if len(dataDict["IMU0"]) != 0:
                while index < len(dataDict["IMU0"]):
                    if dataDict["IMU0"][index][0] < data[0] < dataDict["IMU0"][index][1]:
                        window_list[count % self.window_size] = data
                        count += 1
                        break
                    elif index < len(dataDict["IMU0"]) - 1 and dataDict["IMU0"][index][1] < data[0] < \
                            dataDict["IMU0"][index + 1][0]:
                        break
                    index += 1
            else:
                window_list[count % self.window_size] = data
                count += 1
            if count > self.window_size and self.window_filter(window_list):
                lat = 0  # 维度
                lon = 0  # 经度
                alt = 0
                vx = 0
                vy = 0
                vz = 0
                for window_data in window_list:
                    lat += window_data[1]
                    lon += window_data[2]
                    alt += window_data[3]
                    vx += window_data[4]
                    vy += window_data[5]
                    vz += window_data[6]
                self.last_location = [lat / self.window_size, lon / self.window_size, alt / self.window_size]
                res_point.append(
                    [lon / self.window_size, lat / self.window_size, alt / self.window_size, vx / self.window_size, vy / self.window_size,
                     vz / self.window_size])
                self.all_point += 1
        result = self.delete_repeat(res_point)
        result_loc = self.location_diff(result)
        result_loc[0] = [0, 0, 0]

        return result_loc

    def location_diff(self, src_loc: list):
        self.loc_origin = src_loc[0]
        result_loc = [self.loc_origin]
        for i in range(1, len(src_loc)):
            result_loc.append([(src_loc[i][0] - self.loc_origin[0]) * self.LOCATION_SCALING_FACTOR * self.longitude_scale(self.loc_origin),
                               (src_loc[i][1] - self.loc_origin[1]) * self.LOCATION_SCALING_FACTOR, -(src_loc[i][2] - self.loc_origin[2]) * 1e-3])
        return result_loc

    def longitude_scale(self, src_loc):
        scale = math.cos(src_loc[1] * 1.0e-7 * self.DEG_TO_RAD)
        return com_math.constrain_float(scale, 0.01, 1.0)


class Rectangle:
    def __init__(self):
        self.lon_lat_list = list()
        self.coor_list = list()
        self.LOCATION_SCALING_FACTOR = 0.011131884502145034
        self.DEG_TO_RAD = 0.017453292519943295769236907684886
        self.center = []

    def input_lon_lat(self, points):
        for point in points:
            new_point = dict()
            new_point["lon"] = point[0]
            new_point["lat"] = point[1]
            new_point["hgt"] = point[2]
            self.lon_lat_list.append(new_point)
        if not self.center:
            self.center = (self.lon_lat_list[0]["lon"], self.lon_lat_list[0]["lat"])
        self.trans_lon_lat_to_coor()


    def input_xyz(self, *args):
        for arg in args:
            new_point = dict()
            new_point["x"] = arg[0]
            new_point["y"] = arg[1]
            new_point["z"] = arg[2]
            self.coor_list.append(new_point)

    def set_center_lon_lat(self, lon, lat):
        self.center = [0, 0, 0]
        self.center[0] = lon
        self.center[1] = lat

    def constrain_float(self, amt, low, high):
        if math.isnan(amt):
            return (low + high) * 0.5
        return low if amt < low else high if amt > high else amt

    def longitude_scale(self):
        scale = math.cos(self.center[1] * 1.0e-7 * self.DEG_TO_RAD)
        return self.constrain_float(scale, 0.01, 1.0)

    def trans_lon_lat_to_coor(self):
        # 0 left top
        # 1 left bottom
        # 2 right bottom
        # 3 right top
        for i in range(0, len(self.lon_lat_list)):
            new_point = dict()
            new_point["x"] = (self.lon_lat_list[i]["lon"] - self.center[0]) * self.LOCATION_SCALING_FACTOR * self.longitude_scale()
            new_point["y"] = (self.lon_lat_list[i]["lat"] - self.center[1]) * self.LOCATION_SCALING_FACTOR
            new_point["z"] = (-(self.lon_lat_list[i]["hgt"] - self.center[2]) * 1e-3)
            self.coor_list.append(new_point)
        x_offset = self.coor_list[0]["x"] - self.coor_list[1]["x"]
        y_offset = self.coor_list[0]["y"] - self.coor_list[1]["y"]
        z_offset = self.coor_list[0]["z"] - self.coor_list[1]["z"]

        new_point = dict()
        new_point["x"] = self.coor_list[2]["x"] + x_offset
        new_point["y"] = self.coor_list[2]["y"] + y_offset
        new_point["z"] = self.coor_list[2]["z"] + z_offset
        self.coor_list.append(new_point)


class HTTP:
    def __init__(self):
        self.http_prefix = "https://"
        self.server = ""
        self.port = ""

    def set_OFFLINE(self):
        self.http_prefix = "http://"
        self.server = "127.0.0.1"
        self.port = ":8081"

    def set_ONLINE_TEST(self):
        self.http_prefix = "https://"
        self.server = "api.dmduav.com"
        self.port = ":4397"

    def set_ONLINE(self):
        self.http_prefix = "https://"
        self.server = "cloud.dmduav.com"
        self.port = ":8080"

    def set_LOCAL(self):
        self.http_prefix = "https://"
        self.server = "192.168.6.28"
        self.port = ":8080"

    # def set_TEST(self):
    #     self.http_prefix = "https://"
    #     self.server = "cmdl.dmduav.com"
    #     self.port = ":38080"

    def set_WEB(self): # 预发布
        self.http_prefix = "https://"
        self.server = "cloud-gateway.dmduav.com"
        self.port = ""

    def set_TEST(self): # 内部测试
        self.http_prefix = "https://"
        self.server = "cloud-gateway-uat.dmduav.com"
        self.port = ""




# class DramaEditorIdentify:
#     def __init__(self):
#         self.http = HTTP()
#         self.http.set_ONLINE()
#
#         self.token = ""
#         self.token_head = ""
#         self.token_type = ""
#         self.refresh_token = ""
#         self.expires_in = ""
#
#     def get_login_token(self, username, password):
#         url = f"{self.http.http_prefix}{self.http.server}{self.http.port}/oauth/token"
#
#         payload = {
#             'username': (None, username),
#             'password': (None, password),
#         }
#
#         headers = {
#
#         }
#
#         try:
#             response = requests.post(url, headers=headers, files=payload, timeout=(10, 30), verify=True)
#             content = response.json()
#             if response.status_code == 200:
#                 content["ret_code"] = content["code"]
#                 if content['data']:
#                     self.token = content['data'].get('token', '')
#                     self.token_type = content['data'].get('tokenHead', '')
#                     self.refresh_token = content['data'].get('refreshToken', '')
#                     self.expires_in = content['data'].get("expiresIn", 0)
#             return content
#         except requests.exceptions.RequestException as e:
#             return {"code": 203}
#
#
#     def get_user_details(self, machine_number, drama_editor_type):
#         url = f"{self.http.http_prefix}{self.http.server}{self.http.port}/api/v1/de/userDetails"
#         payload = {
#             'machineNumber': (None, machine_number),
#             'dramaEditorType': (None, drama_editor_type),
#         }
#
#         headers = {
#             'Authorization': f"{self.token_type} {self.token}"
#         }
#
#         try:
#             response = requests.get(url, headers=headers, files=payload, timeout=(10, 30), verify=True)
#             content = response.json()
#             return content
#         except requests.exceptions.RequestException as e:
#             return {"code": -1}
        



class Task_Log:
    def __init__(self,path):
        self.pid = os.getpid()
        self.task_sta_time = time.time()
        self.task_end_time = None
        self.task_sta_memory = self.get_memory_info()
        self.task_end_memory = None
        self.debug_path = path

        self.task_name = 'taskName'
        self.task_quantity = 'quantity'
        self.task_frameCount = 'frameCount'
        self.task_timeTaken = 'timeTaken'
        self.task_memoryUsage = 'memoryUsage'
        self.task_scene_name = 'scene'
        self.task_time = 'time'
        self.soft_info = {
            'software': "default",
            'version': "20250101",
        }

    def set_soft_info(self, si):
        self.soft_info = si

    def write_json(self, json_path, json_dict):
        with open(json_path, "w", encoding='utf-8') as f:
            json.dump(json_dict, f, ensure_ascii=False, indent=4)


    def read_json(self, json_path):
        try:
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)
            except UnicodeDecodeError:
                with open(json_path, 'r', encoding='gbk') as f:
                    json_data = json.load(f)
        except:
            self.env_init(self.soft_info)
        return json_data


    def get_memory_info(self):
        try:
            result = subprocess.run(['tasklist'], text=True, stdout=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW, errors='ignore')
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        current_pid = int(parts[1])  
                        if current_pid == self.pid:
                            memory_str = parts[-2].replace(',', '') 
                            memory_kb = int(memory_str) 
                            memory_gb = memory_kb / (1024 ** 2) 
                            return round(memory_gb,3)
                    except ValueError:
                        continue  
        except Exception as e:
            print(f"error: {e}")
        return None


    def get_task_end_time(self):
        self.task_end_time = time.time()
        return round(self.task_end_time - self.task_sta_time,2)


    def get_task_end_memory(self):
        self.task_end_memory = self.get_memory_info()
        memory = round(self.task_end_memory - self.task_sta_memory,3)
        if memory < 0:
            memory = 0
        return memory


    def get_cpu_info(self):
        try:
            if platform.system() == "Windows":
                cpu_info = os.popen("wmic cpu get name").read().strip().split("\n")[-1]
            else:
                cpu_info = "Unknown"
        except:
            cpu_info = "Unknown"
        return cpu_info


    def get_memory_size(self):
        try:
            if platform.system() == "Windows":
                mem_bytes = int(os.popen("wmic computersystem get totalphysicalmemory").read().strip().split("\n")[-1].strip())
            else:
                mem_bytes = 0
            mem_gb = round(mem_bytes / (1024 ** 3),1)
        except:
            mem_bytes = 0
        return str(mem_gb)


    def get_time(self):
        now = datetime.now()
        return now.strftime("%Y-%m-%d %H:%M:%S")


    def env_init(self,soft_info):
        try:
            debug_info = {
                "env_info":{
                    'software': soft_info['software'],
                    'version': soft_info['version'],
                    'cpu': self.get_cpu_info(),
                    'memory': self.get_memory_size(),
                    'time': self.get_time(),
                },
                'task_list':[],
            }
            self.write_json(self.debug_path,debug_info)
        except:
            pass


    def write_task_info(self, task_name, quantity, frame, scene, *args):
        try:
            debug_info = self.read_json(self.debug_path)
            task_list = debug_info.get('task_list', [])
            task_entry = None

            for entry in task_list:
                if entry.get(self.task_name) == task_name:
                    task_entry = entry
                    break

            if not task_entry:
                new_task = {
                    self.task_name: task_name,
                    self.task_quantity: [quantity],
                    self.task_frameCount: [frame],
                    self.task_timeTaken: [self.get_task_end_time()],
                    self.task_memoryUsage: [self.get_task_end_memory()],
                    self.task_scene_name: [scene],
                    self.task_time: [self.get_time()],
                }

                if len(args) > 0:
                    for arg_idx in range(min(4, len(args))):
                        new_task[f"attr{arg_idx+1}"] = [str(args[arg_idx])]

                # for arg in args:
                #     for key, value in arg.items():
                #         if key in new_task:
                #             if isinstance(value, list):
                #                 new_task[key].extend(value)
                #             else:
                #                 new_task[key].append(value)
                #         else:
                #             new_task[key] = [value] if not isinstance(value, list) else value

                task_list.append(new_task)
            else:
                task_entry[self.task_quantity].append(quantity)
                task_entry[self.task_frameCount].append(frame)
                task_entry[self.task_timeTaken].append(self.get_task_end_time())
                task_entry[self.task_memoryUsage].append(self.get_task_end_memory())
                task_entry[self.task_scene_name].append(scene)
                task_entry[self.task_time].append(self.get_time())

                if len(args) > 0:
                    for arg_idx in range(min(4, len(args))):
                        if f"attr{arg_idx+1}" in task_entry:
                            task_entry[f"attr{arg_idx+1}"].append(str(args[arg_idx]))

                # for arg in args:
                #     for key, value in arg.items():
                #         if key in task_entry:
                #             if isinstance(value, list):
                #                 task_entry[key].extend(value)
                #             else:
                #                 task_entry[key].append(value)
                #         else:
                #             task_entry[key] = [value] if not isinstance(value, list) else value

            debug_info['task_list'] = task_list
            self.write_json(self.debug_path, debug_info)
        except:
            print("...")


    def up_log(self, username, password, drama_editor_type, data, dll):
        if data['task_list']:
            web = com_web.DramaEditorIdentify()
            ret_json = web.get_login_token(username, password)
            url = f"{web.http.http_prefix}{web.http.server}{web.http.port}/api/v1/de/logInfo"
            headers = {
                'Authorization': f"{web.token_type} {web.token}"
            }

            if ret_json['code'] == 200:
                user_json = web.get_user_details(dll.get_hardware_sn(), drama_editor_type)
                if user_json['code'] == 200:
                    user_param = {"user_info": {
                        "username": user_json['data']['name'],
                        "dramaEditorVersion": user_json['data']['dramaEditorVersion'],
                        "expired": user_json['data']['expired'],
                        "maxActivate": user_json['data']['maxActivate'],
                        "description": user_json['data']['description'],

                    }}
                    data.update(user_param)
                    try:
                        response = requests.post(url, headers=headers, json=data, timeout=(10, 30), verify=True)
                        return response.json()
                    except requests.exceptions.RequestException as e:
                        return {"code": -1}
            return {"code": -1}
        else:
            return {"code": -2}


class PartialDrama:
    def __init__(self, file_path, opt_color=True, opt_pos=True, opt_fireworks=True, scene_fps=10):
        self.path = file_path
        self.frame_types_table = {
            'takeoff': 0,
            'picture': 1,
            'transition': 2,
            'land': 3
        }
        self.frame_types_list = {
            'takeoff': [],
            'picture': [],
            'transition': [],
            'land': []
        }
        self.drone_count = 0
        self.frame_count = 0 #
        self.name = ""
        self.description = ""
        self.pos_freq = 0 #
        self.color_freq = 0 #
        self.drone_points_colors = list()
        self.drama_type = ""
        self.is_old = False
        self.group_info = dict()
        self.opt_color = opt_color
        self.opt_pos = opt_pos
        self.opt_fireworks = opt_fireworks
        self.drone_caches = list()
        self.drone_type_list = list()
        self.drone_no_idx_map = dict()

        self.set_scene_fps = 10

        self.parse()

    def parse(self, file_path=None):
        if file_path:
            parse_path = file_path
        else:
            parse_path = self.path

        if not os.path.exists(parse_path):
            return

        if parse_path.endswith(".jsdm"):
            drama_json_info = com_func.read_json(parse_path)
            self.drama_type = "jsdm"

            self.is_old = not drama_json_info.get("isNewFlag", False)

            self.pos_freq = 5 if len(drama_json_info["pointFrames"]) < 2 else \
                (drama_json_info["pointFrames"][1]["time"] - drama_json_info["pointFrames"][1]["time"]) / 100  # time - time / 100
            self.color_freq = 1 if len(drama_json_info["channelFrames"]) < 2 else \
                (drama_json_info["channelFrames"][1]["time"] - drama_json_info["channelFrames"][1]["time"]) / 100
            try:
                self.name = drama_json_info["name"]
            except:
                self.name = drama_json_info["sceneName"]
            self.description = drama_json_info["description"]
            self.frame_count = drama_json_info["frameCount"]
            self.drone_count = drama_json_info["planeCount"]
            try:
                self.group_info = drama_json_info["groupInfo"]
            except:
                logger.warning("scene have no group information")
            self.drone_points_colors = list(DronePosColor() for k in range(self.drone_count))
            self.drone_caches = list(DroneCache() for k in range(self.drone_count))

            drone_no_idx_map = dict()
            for drone_idx in range(len(drama_json_info["droneTypes"])):
                self.drone_type_list.append((int(drama_json_info["droneTypes"][drone_idx].get("no")), drama_json_info["droneTypes"][drone_idx].get("type")))
                self.drone_no_idx_map[int(drama_json_info["droneTypes"][drone_idx].get("no"))] = drone_idx

                if drama_json_info["droneTypes"][drone_idx].get("cache"):
                    self.drone_caches[drone_idx].cache = drama_json_info["droneTypes"][drone_idx]["cache"]
                else:
                    self.drone_caches[drone_idx].cache = ""


            if self.opt_pos:
                for point_frame in drama_json_info["pointFrames"]:
                    for point_idx in range(len(point_frame["points"])):
                        # drone_idx = point_frame["points"][point_idx]['no'] - 1
                        drone_idx = self.drone_no_idx_map[point_frame["points"][point_idx]['no']]
                        self.drone_points_colors[drone_idx].add_point(point_frame["time"]/100,
                                                                      point_frame["points"][point_idx]["x"],
                                                                      point_frame["points"][point_idx]["y"],
                                                                      point_frame["points"][point_idx]["z"])
                    cur_frame_type = point_frame.get('frameType', None)
                    for frame_type in ['takeoff', 'picture', 'transition', 'land']:
                        if cur_frame_type == self.frame_types_table[frame_type]:
                            self.frame_types_list[frame_type].append(point_frame['time']/100)
                            break

            if self.opt_color:
                for color_frame in drama_json_info["channelFrames"]:
                    for color_idx in range(len(color_frame["channels"])):
                        # drone_idx = color_frame["channels"][color_idx]['no'] - 1
                        drone_idx = self.drone_no_idx_map[color_frame["channels"][color_idx]['no']]
                        self.drone_points_colors[drone_idx].add_color(color_frame["time"]/100,
                                                                      color_frame["channels"][color_idx]["c1"],
                                                                      color_frame['channels'][color_idx]["c2"],
                                                                      color_frame["channels"][color_idx]["c3"])

        elif parse_path.endswith(".jsdmraw"):
            drama_json_info = com_func.read_json(parse_path)
            self.drama_type = "jsdmraw"
            self.name = drama_json_info["sceneName"]
            self.description = drama_json_info["description"]
            self.drone_count = drama_json_info["droneCount"]
            try:
                self.group_info = drama_json_info["groupInfo"]
            except:
                logger.warning("scene have no group information")
            self.drone_points_colors = list(DronePosColor() for k in range(self.drone_count))
            self.drone_caches = list(DroneCache() for k in range(self.drone_count))

            if not drama_json_info.get("isNewFlag"):
                self.is_old = True
            self.is_old = not drama_json_info.get("isNewFlag", False)

            if len(drama_json_info["drones"][0]["points"]) > 0 and drama_json_info["drones"][0]["points"][0]["no"] >= 0:
                offset = drama_json_info["drones"][0]["points"][0]["no"]
            elif len(drama_json_info["drones"][0]["channels"]) > 0 and drama_json_info["drones"][0]["channels"][0]["no"] >= 0:
                offset = drama_json_info["drones"][0]["channels"][0]["no"]
            else:
                print("no drama info in: " + parse_path)
                return None

            for drone in drama_json_info["drones"]:
                for point in drone["points"]:
                    if point["no"] > 0:
                        offset = min(offset, point["no"])
                for color in drone["channels"]:
                    if color["no"] > 0:
                        offset = min(offset, color["no"])

            for drone_idx in range(len(drama_json_info["drones"])):
                if drama_json_info["drones"][drone_idx].get("cache"):
                    self.drone_caches[drone_idx].cache = drama_json_info["drones"][drone_idx]["cache"]
                else:
                    self.drone_caches[drone_idx].cache = ""

                self.drone_type_list.append((drama_json_info["drones"][drone_idx].get("id"), drama_json_info["drones"][drone_idx].get('droneType')))

                if self.opt_pos:
                    for point in drama_json_info["drones"][drone_idx]["points"]:
                        self.drone_points_colors[drone_idx].add_point((point["no"]-offset)/100, point["x"], point["y"], point["z"])
                if self.opt_color:
                    for color in drama_json_info["drones"][drone_idx]["channels"]:
                        self.drone_points_colors[drone_idx].add_color((color["no"]-offset) / 100, color["c1"], color["c2"], color["c3"])

        elif parse_path.endswith(".bin"):
            result_dict = com_func.parse_dmdclip_proto_to_json(parse_path)
            if result_dict:
                drone_infos = result_dict.get("DroneInfos", [])
                clip_datas = result_dict.get("ClipDatas", [])

                if len(drone_infos) == 0 or len(clip_datas) == 0:
                    return
                self.drama_type = "jsdm"
                self.drone_count = len(drone_infos)
                self.frame_count = len(clip_datas) #
                self.name = result_dict.get("name", "SP任务")
                self.description = ""
                self.pos_freq = 5 #
                self.color_freq = 1 #
                self.is_old = True
                self.group_info = dict()
                self.drone_caches = list(DroneCache() for k in range(self.drone_count))

                self.drone_points_colors = list(DronePosColor() for k in range(self.drone_count))

                for frame in clip_datas:
                    cur_time = frame.get("Time", 0)
                    drone_data_infos = frame.get("DroneDataInfos", [])
                    logger.debug(drone_data_infos)
                    for drone_index in range(len(drone_data_infos)):
                        pos_data = drone_data_infos[drone_index].get("Position", {})
                        color_data = drone_data_infos[drone_index].get("Channel", {})
                        logger.debug(pos_data)
                        logger.debug(color_data)
                        if pos_data:
                            self.drone_points_colors[drone_index].add_point(cur_time/100, pos_data['X'], pos_data['Y'], pos_data['Z'])
                        if color_data:
                            self.drone_points_colors[drone_index].add_color(cur_time/100, color_data['C1'], color_data['C2'], color_data['C3'])

                for drone_info in drone_infos:
                    self.drone_type_list.append((drone_info['NO'], drone_info['Type']))

        elif parse_path.endswith(".vviz"):
            # sky brush
            # drama_json_info = com_func.read_json(parse_path)
            with open(parse_path, 'r') as f:
                drama_json_info = json.load(f)
            if not drama_json_info:
                return

            self.drama_type = "vviz"
            self.name = drama_json_info.get("performanceName", os.path.splitext(os.path.basename(parse_path))[0])
            self.description = ""
            self.group_info = dict()
            self.is_old = True

            performances = drama_json_info.get("performances", [])
            self.drone_count = len(performances)
            self.drone_points_colors = list(DronePosColor() for k in range(self.drone_count))
            self.drone_caches = list(DroneCache() for k in range(self.drone_count))

            default_pos_fps = float(drama_json_info.get("defaultPositionRate", 2.0) or 2.0)
            default_color_fps = float(drama_json_info.get("defaultColorRate", 10.0) or 10.0)

            default_pos_dt = 1.0 / default_pos_fps
            default_color_frames = 1.0 / default_color_fps

            if default_color_fps > 0:
                self.set_scene_fps = int(default_color_fps)

            
            if default_pos_fps > 2:
                if not com_func.confirm_message_box("warning", f"position fps is {default_pos_fps}, which is greater than 2, maybe loss some info, continue?"):
                    return

            # PartialDrama uses Maya 10FPS frame units internally, so 1 second == 10 frames.
            self.pos_freq = self.set_scene_fps / default_pos_fps
            self.color_freq = self.set_scene_fps / default_color_fps

            max_frame = 0.0

            airframe_type_table = {
                "Verge_X1": 41,
            }

            for drone_idx, performance in enumerate(performances):
                agent_description = performance.get("agentDescription", {})
                payload_descriptions = performance.get("payloadDescription", [])

                drone_no = int(performance.get("id", drone_idx)) + 1
                drone_type = airframe_type_table.get(agent_description.get("airframe"), agent_description.get("airframe", 0))
                self.drone_type_list.append((drone_no, drone_type))

                home_x = float(agent_description.get("homeX", 0.0))
                home_y = float(agent_description.get("homeY", 0.0))
                home_z = float(agent_description.get("homeZ", 0.0))

                if self.opt_pos:
                    current_frame = 0.0
                    self.drone_points_colors[drone_idx].add_point(current_frame, home_x, home_z, home_y)
                    
                    for traversal in agent_description.get("agentTraversal", []):
                        current_frame += self.pos_freq
                        home_x += float(traversal.get("dx", 0.0))
                        home_z += float(traversal.get("dz", 0.0))
                        home_y += float(traversal.get("dy", 0.0))
                        self.drone_points_colors[drone_idx].add_point(current_frame, home_x, home_z, home_y)
                    max_frame = max(max_frame, current_frame)

                if self.opt_color:
                    payload_actions = []
                    for payload_description in payload_descriptions:
                        payload_actions = payload_description.get("payloadActions", [])
                        if payload_actions:
                            break

                    current_frame = 0.0
                    for payload_action in payload_actions:
                        self.drone_points_colors[drone_idx].add_color(
                            current_frame,
                            int(payload_action.get("r", 0)),
                            int(payload_action.get("g", 0)),
                            int(payload_action.get("b", 0))
                        )
                        current_frame += self.color_freq
                    max_frame = max(max_frame, current_frame)

            self.frame_count = int(math.ceil(max_frame))


class DronePosColor:
    def __init__(self):
        self.points = list()
        self.point_frames = list()

        self.colors = list()
        self.color_frames = list()

    def add_point(self, frame, *args):
        if len(args) == 1 and len(args[0]) == 3:
            self.points.append(tuple(args))
        elif len(args) == 3:
            self.points.append((args[0], args[1], args[2]))
        else:
            return
        self.point_frames.append(frame)

    def add_color(self, frame, *args):
        if len(args) == 1 and len(args[0]) == 3:
            self.colors.append(tuple(args))
        elif len(args) == 3:
            self.colors.append((args[0], args[1], args[2]))
        else:
            return
        self.color_frames.append(frame)

class DroneCache:
    def __init__(self):
        self.id = 0
        self.type = ""
        self.cache = ""

class KDTree:
    def __init__(self, points):
        indexed_points = [(point, idx) for idx, point in enumerate(points)]
        self.root = self.build_tree(indexed_points, depth=0)

    def build_tree(self, indexed_points, depth):
        # Base case: If the list of points is empty, return None
        if not indexed_points:
            return None

        # Number of dimensions (for 3D space, k = 3)
        k = len(indexed_points[0][0])  # Points are stored as (point, idx)
        axis = depth % k  # Select axis cyclically (x, y, z)

        # Sort points by the current axis and choose the median
        indexed_points.sort(key=lambda point_idx: point_idx[0][axis])
        median_idx = len(indexed_points) // 2
        median_point, tmp_idx = indexed_points[median_idx]  # Extract the point and its index

        # Recursively build the left and right subtrees
        left = self.build_tree(indexed_points[:median_idx], depth + 1)
        right = self.build_tree(indexed_points[median_idx + 1:], depth + 1)

        # Return the node containing the median point and the two subtrees
        return {
            'point': median_point,  # The actual point (x, y, z)
            'idx': tmp_idx,  # The index of this point in the original list
            'left': left,
            'right': right
        }

    def find_nearest(self, target, k=1):
        # Initialize the nearest point and distance
        self.best_point_idx = None
        self.best_dist = float('inf')

        # Start the recursive search for the nearest point
        self._find_nearest(self.root, target, depth=0)

        return self.best_point_idx, self.best_dist

    def _find_nearest(self, node, target, depth):
        if node is None:
            return

        # Current node point and its distance to the target point
        point = node['point']
        dist = self._euclidean_distance(point, target)

        # If the current point is closer to the target, update the best point and distance
        if dist < self.best_dist:
            self.best_point_idx = node['idx']
            self.best_dist = dist

        # Determine the current axis (x, y, z)
        k = len(target)
        axis = depth % k

        # Recursively search the relevant subtree
        if target[axis] < point[axis]:
            self._find_nearest(node['left'], target, depth + 1)
            # Check if we need to search the other subtree
            if abs(target[axis] - point[axis]) < self.best_dist:
                self._find_nearest(node['right'], target, depth + 1)
        else:
            self._find_nearest(node['right'], target, depth + 1)
            # Check if we need to search the other subtree
            if abs(target[axis] - point[axis]) < self.best_dist:
                self._find_nearest(node['left'], target, depth + 1)

    def find_points_in_radius(self, center, radius):
        # List to store points inside the radius
        self.points_within_radius = []
        self._find_points_in_radius(self.root, center, radius, depth=0)
        return self.points_within_radius

    def _find_points_in_radius(self, node, center, radius, depth):
        if node is None:
            return

        # Get the point at the current node and compute the distance to the center
        point = node['point']
        dist = self._euclidean_distance(point, center)

        # If the point is within the radius, add it to the result list
        if dist <= radius:
            self.points_within_radius.append(node['idx'])

        # Determine the splitting dimension (cycle through x, y, z)
        k = len(center)
        axis = depth % k

        # Determine if we need to search both subtrees (left and right)
        if center[axis] - radius <= point[axis]:
            self._find_points_in_radius(node['left'], center, radius, depth + 1)
        if center[axis] + radius >= point[axis]:
            self._find_points_in_radius(node['right'], center, radius, depth + 1)

    def _euclidean_distance(self, point1, point2):
        # Calculate Euclidean distance between two points
        return math.sqrt(sum((point1[i] - point2[i]) ** 2 for i in range(len(point1))))


class SpVersionData:
    def __init__(self):
        self.OnlyId = 0 #主键 
        self.Id = ""
        self.name = ""
        self.IsUsing = True
        self.IsVersionShow = True
        self.eVType = ""
        self.description = ""
        self.RelationId = ""
        self.versionNo = 0
        self.versionName = ""
        self.path = ""
        self.md5 = ""
        self.localUrl = ""
        self.cloudUrl = ""

    def get_version_data(self, version_json_str):
        try:
            version_json = json.loads(version_json_str)
            self.OnlyId = version_json['OnlyId']
            self.Id = version_json['Id']
            self.name = version_json['name']
            self.IsUsing = version_json['IsUsing']
            self.IsVersionShow = version_json['IsVersionShow']
            self.eVType = version_json['eVType']
            self.description = version_json['description']
            self.RelationId = version_json['RelationId']
            self.versionNo = version_json['versionNo']
            self.versionName = version_json['versionName']
            self.path = version_json['path']
            self.md5 = version_json['md5']
            self.localUrl = version_json['localUrl']
            self.cloudUrl = version_json['cloudUrl']
        except:
            return None

class UserCacheInfo:
    def __init__(self, cur_user_name):
        self.user_cache_list = [cur_user_name]

    def add_user(self, cache_string):
        userlist = self.decrypt_user_cache(cache_string)
        for i in userlist:
            if i not in self.user_cache_list:
                self.user_cache_list.append(i)

    def use_cache_add(self, cache_string):
        users = self.decrypt_user_cache(cache_string)
        if users:
            self.user_cache_list.extend(users)
        self.user_cache_list_deduplication()

    def user_cache_list_deduplication(self):
        self.user_cache_list = list(set(self.user_cache_list))

    def generate_b64(self):
        try:
            return com_func.encode_to_base64(json.dumps(self.user_cache_list))
        except Exception as e:
            return False

    def decrypt_user_cache(self, b64_str):
        decrypted_str = com_func.decode_from_base64(b64_str)
        if not decrypted_str:
            return False

        try:
            return json.loads(decrypted_str)
        except Exception as e:
            return False

