"""飞机参数字典（UavParamDict）—— 对齐 dgcs4 Server/Param/UavParamDict.cs

CSV 来源：C:\\Program Files\\DGCS\\4.0\\Components\\ParamList\\{机型名}_ParamList.csv
格式（ParamService.cs:379-417）：参数名,类型,参数值[,模块分组]

类型语义：
  0 — MustBe（参数必须等于该值）
  1 — MustNotBe（参数必须不等于该值）
  2 — 不校验（仅登记）
"""

import struct
from copy import deepcopy


# ------------------------------------------------------------------
# C# CRC32 查找表（Common/CRC/CRC32.cs:7-41）
# 注意：此表与标准 zlib.crc32 不同！必须使用此表才能与地面站 hash 一致。
# ------------------------------------------------------------------
_CS_CRC32_TABLE = [
    0x00000000, 0xF26B8303, 0xE13B70F7, 0x1350F3F4, 0xC79A971F, 0x35F1141C, 0x26A1E7E8, 0xD4CA64EB,
    0x8AD958CF, 0x78B2DBCC, 0x6BE22838, 0x9989AB3B, 0x4D43CFD0, 0xBF284CD3, 0xAC78BF27, 0x5E133C24,
    0x105EC76F, 0xE235446C, 0xF165B798, 0x030E349B, 0xD7C45070, 0x25AFD373, 0x36FF2087, 0xC494A384,
    0x9A879FA0, 0x68EC1CA3, 0x7BBCEF57, 0x89D76C54, 0x5D1D08BF, 0xAF768BBC, 0xBC267848, 0x4E4DFB4B,
    0x20BD8EDE, 0xD2D60DDD, 0xC186FE29, 0x33ED7D2A, 0xE72719C1, 0x154C9AC2, 0x061C6936, 0xF477EA35,
    0xAA64D611, 0x580F5512, 0x4B5FA6E6, 0xB93425E5, 0x6DFE410E, 0x9F95C20D, 0x8CC531F9, 0x7EAEB2FA,
    0x30E349B1, 0xC288CAB2, 0xD1D83946, 0x23B3BA45, 0xF779DEAE, 0x05125DAD, 0x1642AE59, 0xE4292D5A,
    0xBA3A117E, 0x4851927D, 0x5B016189, 0xA96AE28A, 0x7DA08661, 0x8FCB0562, 0x9C9BF696, 0x6EF07595,
    0x417B1DBC, 0xB3109EBF, 0xA0406D4B, 0x522BEE48, 0x86E18AA3, 0x748A09A0, 0x67DAFA54, 0x95B17957,
    0xCBA24573, 0x39C9C670, 0x2A993584, 0xD8F2B687, 0x0C38D26C, 0xFE53516F, 0xED03A29B, 0x1F682198,
    0x5125DAD3, 0xA34E59D0, 0xB01EAA24, 0x42752927, 0x96BF4DCC, 0x64D4CECF, 0x77843D3B, 0x85EFBE38,
    0xDBFC821C, 0x2997011F, 0x3AC7F2EB, 0xC8AC71E8, 0x1C661503, 0xEE0D9600, 0xFD5D65F4, 0x0F36E6F7,
    0x61C69362, 0x93AD1061, 0x80FDE395, 0x72966096, 0xA65C047D, 0x5437877E, 0x4767748A, 0xB50CF789,
    0xEB1FCBAD, 0x197448AE, 0x0A24BB5A, 0xF84F3859, 0x2C855CB2, 0xDEEEDFB1, 0xCDBE2C45, 0x3FD5AF46,
    0x7198540D, 0x83F3D70E, 0x90A324FA, 0x62C8A7F9, 0xB602C312, 0x44694011, 0x5739B3E5, 0xA55230E6,
    0xFB410CC2, 0x092A8FC1, 0x1A7A7C35, 0xE811FF36, 0x3CDB9BDD, 0xCEB018DE, 0xDDE0EB2A, 0x2F8B6829,
    0x82F63B78, 0x709DB87B, 0x63CD4B8F, 0x91A6C88C, 0x456CAC67, 0xB7072F64, 0xA457DC90, 0x563C5F93,
    0x082F63B7, 0xFA44E0B4, 0xE9141340, 0x1B7F9043, 0xCFB5F4A8, 0x3DDE77AB, 0x2E8E845F, 0xDCE5075C,
    0x92A8FC17, 0x60C37F14, 0x73938CE0, 0x81F80FE3, 0x55326B08, 0xA759E80B, 0xB4091BFF, 0x466298FC,
    0x1871A4D8, 0xEA1A27DB, 0xF94AD42F, 0x0B21572C, 0xDFEB33C7, 0x2D80B0C4, 0x3ED04330, 0xCCBBC033,
    0xA24BB5A6, 0x502036A5, 0x4370C551, 0xB11B4652, 0x65D122B9, 0x97BAA1BA, 0x84EA524E, 0x7681D14D,
    0x2892ED69, 0xDAF96E6A, 0xC9A99D9E, 0x3BC21E9D, 0xEF087A76, 0x1D63F975, 0x0E330A81, 0xFC588982,
    0xB21572C9, 0x407EF1CA, 0x532E023E, 0xA145813D, 0x758FE5D6, 0x87E466D5, 0x94B49521, 0x66DF1622,
    0x38CC2A06, 0xCAA7A905, 0xD9F75AF1, 0x2B9CD9F2, 0xFF56BD19, 0x0D3D3E1A, 0x1E6DCDEE, 0xEC064EED,
    0xC38D26C4, 0x31E6A5C7, 0x22B65633, 0xD0DDD530, 0x0417B1DB, 0xF67C32D8, 0xE52CC12C, 0x1747422F,
    0x49547E0B, 0xBB3FFD08, 0xA86F0EFC, 0x5A048DFF, 0x8ECEE914, 0x7CA56A17, 0x6FF599E3, 0x9D9E1AE0,
    0xD3D3E1AB, 0x21B862A8, 0x32E8915C, 0xC083125F, 0x144976B4, 0xE622F5B7, 0xF5720643, 0x07198540,
    0x590AB964, 0xAB613A67, 0xB831C993, 0x4A5A4A90, 0x9E902E7B, 0x6CFBAD78, 0x7FAB5E8C, 0x8DC0DD8F,
    0xE330A81A, 0x115B2B19, 0x020BD8ED, 0xF0605BEE, 0x24AA3F05, 0xD6C1BC06, 0xC5914FF2, 0x37FACCF1,
    0x69E9F0D5, 0x9B8273D6, 0x88D28022, 0x7AB90321, 0xAE7367CA, 0x5C18E4C9, 0x4F48173D, 0xBD23943E,
    0xF36E6F75, 0x0105EC76, 0x12551F82, 0xE03E9C81, 0x34F4F86A, 0xC69F7B69, 0xD5CF889D, 0x27A40B9E,
    0x79B737BA, 0x8BDCB4B9, 0x988C474D, 0x6AE7C44E, 0xBE2DA0A5, 0x4C4623A6, 0x5F16D052, 0xAD7D5351,
]


def _crc32(crc: int, data: bytes) -> int:
    """对齐 C# CRC32.CRC(uint crc, byte[] buf), Common/CRC/CRC32.cs:43-46"""
    for b in data:
        crc = _CS_CRC32_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc


# ------------------------------------------------------------------
# 机型名 → CSV 文件名（不含目录前缀）
# ------------------------------------------------------------------
MODEL_TO_CSV = {
    "X1":  "X1_ParamList.csv",
    "Y2":  "Y2_ParamList.csv",
    "L3":  "L3_ParamList.csv",
    "L31": "L31_ParamList.csv",
    "V4":  "Newton40_ParamList.csv",
    "V32": "Newton32_ParamList.csv",
    "V41": "Newton41_ParamList.csv",
    "L5":  "L5_ParamList.csv",
}

# 序列号前缀 → 机型名（由 AIRPLANE_MODEL_SERIALS 反向推导）
_SERIAL_PREFIX_TO_MODEL = {
    "WX10": "X1",
    "YY20": "Y2",
    "WL30": "L3",
    "WL31": "L31",
    "WV40": "V4",
    "WV32": "V32",
    "WV41": "V41",
    "WL50": "L5",
}


def serial_to_model(serial: str) -> str:
    """从序列号前缀反查机型名，查不到返回 'X1' 作为兜底。"""
    for prefix, model in _SERIAL_PREFIX_TO_MODEL.items():
        if serial.startswith(prefix):
            return model
    return "X1"


# ------------------------------------------------------------------
# UavParamDict
# ------------------------------------------------------------------
class UavParamDict:
    """飞机参数字典，对齐 C# UavParamDict（UavParamDict.cs:9-206）。

    每架假飞机持有独立 Clone 副本，写参不影响其他飞机。
    """

    __slots__ = (
        "ParamTypes", "ParamsMustBe", "ParamsMustNotBe",
        "MustBeTypes", "dynamicParams", "ParamHash", "_model",
    )

    def __init__(self, model: str):
        self._model = model
        # key: 参数名, value: 校验类型 byte（0=MustBe, 1=MustNotBe, 2=不校验）
        self.ParamTypes: dict[str, int] = {}
        # key: 参数名, value: 期望值
        self.ParamsMustBe: dict[str, float] = {}
        # key: 参数名, value: 禁止值
        self.ParamsMustNotBe: dict[str, float] = {}
        # key: 模块分组 sbyte, value: MustBe 参数名列表
        self.MustBeTypes: dict[int, list[str]] = {}
        # 动态参数（TASK_MSK0~3），决定哪些模块分组参与 hash
        self.dynamicParams: dict[str, float] = {
            "TASK_MSK0": 16777215,
            "TASK_MSK1": 16777215,
            "TASK_MSK2": 16777215,
            "TASK_MSK3": 16777215,
        }
        self.ParamHash: int = 0

    # ------------------------------------------------------------------
    # Clone
    # ------------------------------------------------------------------
    def clone(self) -> "UavParamDict":
        """浅拷贝所有字典，创建一份独立副本（对齐 C# Clone）。"""
        c = UavParamDict(self._model)
        c.ParamTypes = dict(self.ParamTypes)
        c.ParamsMustBe = dict(self.ParamsMustBe)
        c.ParamsMustNotBe = dict(self.ParamsMustNotBe)
        c.MustBeTypes = {k: list(v) for k, v in self.MustBeTypes.items()}
        c.dynamicParams = dict(self.dynamicParams)
        c.ParamHash = self.ParamHash
        return c

    # ------------------------------------------------------------------
    # CSV 加载
    # ------------------------------------------------------------------
    def load_csv(self, csv_path: str) -> bool:
        """从指定 CSV 文件加载参数表。

        Returns:
            True 加载成功；False 文件不存在 / 无 MustBe 参数。
        """
        import os
        if not os.path.isfile(csv_path):
            return False

        with open(csv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue

            name = parts[0]
            try:
                chk_type = int(parts[1])      # 0=MustBe, 1=MustNotBe, 2=不校验
                value = float(parts[2])
            except ValueError:
                continue

            self.ParamTypes[name] = chk_type

            if chk_type == 0:
                self.ParamsMustBe[name] = value
                mod_group = int(parts[3]) if len(parts) > 3 else -1
                self.MustBeTypes.setdefault(mod_group, []).append(name)
            elif chk_type == 1:
                self.ParamsMustNotBe[name] = value
            # type == 2：仅登记，不存值

        if not self.ParamsMustBe:
            return False

        self.refresh_param_hash()
        return True

    # ------------------------------------------------------------------
    # 参数取值（对齐 C# GetParamValue，FakeUavParser.cs:214-227）
    # ------------------------------------------------------------------
    def get_param_value(self, name: str) -> float:
        """返回某个参数的上报值。

        MustBe    → 预期值本身
        MustNotBe → 禁止值 + 0.1（保证"不等于"）
        其他       → 0
        """
        if name in self.ParamsMustBe:
            return self.ParamsMustBe[name]
        if name in self.ParamsMustNotBe:
            return self.ParamsMustNotBe[name] + 0.1
        return 0.0

    # ------------------------------------------------------------------
    # 写参（对齐 C# HandleSetParam，FakeUavParser.receive.cs:458-484）
    # ------------------------------------------------------------------
    def set_param(self, name: str, value: float) -> bool:
        """写入一个参数值。

        只改写 ParamsMustBe / ParamsMustNotBe 中已有的 key；
        两者都不存在时忽略（但仍返回 True 表示无需报错）。
        """
        if name in self.ParamsMustBe:
            self.ParamsMustBe[name] = value
            return True
        if name in self.ParamsMustNotBe:
            self.ParamsMustNotBe[name] = value
            return True
        return False

    # ------------------------------------------------------------------
    # ParamHash（对齐 C# UavParamDict.cs:55-98）
    # ------------------------------------------------------------------
    def refresh_param_hash(self):
        """重新计算 ParamHash（写参后必须调用）。"""
        # 1) 先用 ParamsMustBe 中的实际值刷新 dynamicParams
        for key in self.dynamicParams:
            if key in self.ParamsMustBe:
                self.dynamicParams[key] = self.ParamsMustBe[key]

        # 2) 计算 hash
        self.ParamHash = self._calc_param_hash(self.dynamicParams)

    def _calc_param_hash(self, replace_dict: dict[str, float]) -> int:
        """基于 dynamicParams 选中的模块分组，累计 C# CRC32。"""
        sorted_names = self._ordinal_hash_params(replace_dict)
        h = 0
        for name in sorted_names:
            val = self.ParamsMustBe.get(name)
            if val is None:
                continue
            h = _crc32(h, struct.pack("<f", val))
        return h & 0xFFFFFFFF

    def _get_dynamic_types(self, pairs: dict[str, float]) -> set[int]:
        """展开 TASK_MSK0~3 的 24 位 bitmask → 模块分组号集合。"""
        types: set[int] = {-1}
        size = 24
        for key in ("TASK_MSK0", "TASK_MSK1", "TASK_MSK2", "TASK_MSK3"):
            val = pairs.get(key)
            if val is None:
                continue
            try:
                offset = size * int(key[-1])  # 0, 1, 2, 3
            except (ValueError, IndexError):
                continue
            bits = int(val) & 0xFFFFFF  # 低 24 位
            for i in range(size):
                if bits & (1 << i):
                    types.add(i + offset)
        return types

    def _ordinal_hash_params(self, pairs: dict[str, float]) -> list[str]:
        """按 dynamicParams 选中分组的参数名排序后返回。"""
        dyn_types = self._get_dynamic_types(pairs)
        names: list[str] = []
        for t in sorted(dyn_types):
            if t in self.MustBeTypes:
                names.extend(self.MustBeTypes[t])
        names.sort()
        return names
