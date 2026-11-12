import ctypes


class Point_S(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("z", ctypes.c_float)
    ]


class Color_S(ctypes.Structure):
    _fields_ = [
        ("r", ctypes.c_int),
        ("g", ctypes.c_int),
        ("b", ctypes.c_int)
    ]

class Point_P(ctypes.Structure):
    _fields_ = [
        ("frame", ctypes.c_int),
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("z", ctypes.c_float)
    ]


class Pose_P(ctypes.Structure):
    _fields_ = [
        ("frame", ctypes.c_int),
        ("pitch", ctypes.c_float),
        ("roll", ctypes.c_float),
        ("yaw", ctypes.c_float)
    ]


class Color_P(ctypes.Structure):
    _fields_ = [
        ("frame", ctypes.c_int),
        ("r", ctypes.c_int),
        ("g", ctypes.c_int),
        ("b", ctypes.c_int)
    ]


class Nova_P(ctypes.Structure):
    _fields_ = [
        ("frame", ctypes.c_int),
        ("power", ctypes.c_short)
    ]


class Fireworks_Angle_P(ctypes.Structure):
    _fields_ = [
        ("channel", ctypes.c_int),
        ("angle", ctypes.c_int)
    ]


class Fireworks_P(ctypes.Structure):
    _fields_ = [
        ("frame", ctypes.c_int),
        ("firedPort", ctypes.c_int),
        ("fireworksAngles", ctypes.POINTER(Fireworks_Angle_P)),
        ("fireworksAnglesSize", ctypes.c_int)
    ]


class Lantern_P(ctypes.Structure):
    _fields_ = [
        ("frame", ctypes.c_int),
        ("isOn", ctypes.c_bool)
    ]


class Gimbal_P(ctypes.Structure):
    _fields_ = [
        ("frame", ctypes.c_int),
        ("pitch", ctypes.c_float),
        ("roll", ctypes.c_float),
        ("yaw", ctypes.c_float)
    ]


class Lazer_P(ctypes.Structure):
    _fields_ = [
        ("frame", ctypes.c_int),
        ("r", ctypes.c_int),
        ("g", ctypes.c_int),
        ("b", ctypes.c_int)
    ]


class PointsArr(ctypes.Structure):
    _fields_ = [
        ("points", ctypes.POINTER(Point_S)),
        ("size", ctypes.c_int)
    ]


class ChannelsArr(ctypes.Structure):
    _fields_ = [
        ("points", ctypes.POINTER(Color_S)),
        ("size", ctypes.c_int)
    ]


class DroneInfo(ctypes.Structure):
    _fields_ = [
        ("droneType", ctypes.c_int),
        ("droneId", ctypes.c_int),
        ("startTime", ctypes.c_int),
        ("endTime", ctypes.c_int),

        ("returnType", ctypes.c_int),

        ("offsetZ", ctypes.c_float),

        # for check
        ("horizonAcc", ctypes.c_float),
        ("horizonSpeed", ctypes.c_float),
        ("horizonSpeedX", ctypes.c_float),
        ("horizonSpeedY", ctypes.c_float),
        ("speed", ctypes.c_float),
        ("verticalAcc", ctypes.c_float),
        ("verticalSpeed", ctypes.c_float),

        ("points", ctypes.POINTER(Point_S)),
        ("pointsSize", ctypes.c_int),
        ("colors", ctypes.POINTER(Color_S)),
        ("colorsSize", ctypes.c_int),

        ("fireworksCnt", ctypes.c_int),
        ("fireworksAngle", ctypes.POINTER(ctypes.c_int))
    ]

class Drone3Info(ctypes.Structure):
    _fields_ = [
        ("droneType", ctypes.c_int),
        ("droneId", ctypes.c_int),
        ("startTime", ctypes.c_int),
        ("endTime", ctypes.c_int),
        ("returnType", ctypes.c_int),
        ("offsetZ", ctypes.c_float),
        ("horizonAcc", ctypes.c_float),
        ("horizonSpeed", ctypes.c_float),
        ("horizonSpeedX", ctypes.c_float),
        ("horizonSpeedY", ctypes.c_float),
        ("speed", ctypes.c_float),
        ("verticalAcc", ctypes.c_float),
        ("verticalSpeed", ctypes.c_float),

        # position
        ("points", ctypes.POINTER(Point_P)),
        ("pointsSize", ctypes.c_int),
        # pose
        ("poses", ctypes.POINTER(Pose_P)),
        ("posesSize", ctypes.c_int),

        # paylods
        ("colors", ctypes.POINTER(Color_P)),
        ("colorsSize", ctypes.c_int),
        ("novas", ctypes.POINTER(Nova_P)),
        ("novasSize", ctypes.c_int),
        ("fireworks", ctypes.POINTER(Fireworks_P)),
        ("fireworksSize", ctypes.c_int),
        ("lanterns", ctypes.POINTER(Lantern_P)),
        ("lanternsSize", ctypes.c_int),
        ("gimbals", ctypes.POINTER(Gimbal_P)),
        ("gimbalsSize", ctypes.c_int),
        ("lazers", ctypes.POINTER(Lazer_P)),
        ("lazersSize", ctypes.c_int),
    ]

class DmdMap(ctypes.Structure):
    _fields_ = [
        ("rotate", ctypes.c_double),
        ("name", ctypes.c_char_p),
        ("widthScale", ctypes.c_double),
        ("heightScale", ctypes.c_double),
        ("radius", ctypes.c_double),
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("z", ctypes.c_double),
        ("lon", ctypes.c_double),
        ("lat", ctypes.c_double),
    ]

class SegmInfo(ctypes.Structure):
    _fields_ = [
        ("startFrame", ctypes.c_int),
        ("endFrame", ctypes.c_int),
        ("type", ctypes.c_int),
        ("description", ctypes.c_char_p),
    ]


class DramaInfo(ctypes.Structure):
    _fields_ = [
        ("drones", ctypes.POINTER(DroneInfo)),
        ("size", ctypes.c_int),
        ("dramaVersion", ctypes.c_int),
        ("map", DmdMap),
        ("interval", ctypes.c_int),  # ms
        ("colorFps", ctypes.c_int),
        ("pointFps", ctypes.c_int),
        ("startTime", ctypes.c_int),
        ("endTime", ctypes.c_int),
        ("totalCount", ctypes.c_int),
        ("logPath", ctypes.c_char_p),
        ("userCache", ctypes.c_char_p)
    ]

class Drama3Info(ctypes.Structure):
    _fields_ = [
        ("drones", ctypes.POINTER(Drone3Info)),
        ("size", ctypes.c_int),
        ("interval", ctypes.c_int),
        ("payloadFps", ctypes.c_int),
        ("pointFps", ctypes.c_int),
        ("startTime", ctypes.c_int),
        ("endTime", ctypes.c_int),
        ("map", DmdMap),
        ("segments", ctypes.POINTER(SegmInfo)),
        ("segmentsSize", ctypes.c_int),
        ("authorName", ctypes.c_char_p),
        ("ellipsoidCheckRatio", ctypes.c_float)
    ]


class CheckResultPy(ctypes.Structure):
    _fields_ = [
        ("min_dis", ctypes.c_double),
        ("speed", ctypes.c_double),
        ("up_speed", ctypes.c_double),
        ("down_speed", ctypes.c_double),
        ("horizon_speed", ctypes.c_double),
        ("horizon_acc", ctypes.c_double),
        ("vertical_acc", ctypes.c_double),

        ("min_dis_value", ctypes.c_double),
        ("speed_value", ctypes.c_double),
        ("up_speed_value", ctypes.c_double),
        ("down_speed_value", ctypes.c_double),
        ("horizon_speed_value", ctypes.c_double),
        ("horizon_acc_value", ctypes.c_double),
        ("vertical_acc_value", ctypes.c_double),
    ]