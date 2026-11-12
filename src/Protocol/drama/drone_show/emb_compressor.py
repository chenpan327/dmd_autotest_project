#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
嵌入式压缩算法 Python 封装模块

本模块通过 ctypes 调用 embedded_compress_algorithm.dll 提供的压缩/解压接口，
支持 fastlz、lzss、points、channels 四种算法，提供缓冲区级和文件级两类操作。
"""
__author__ = "jin tao"

import os
from ctypes import *

# ==================== DLL 加载 ====================

# 获取当前脚本所在的目录，用于定位 DLL 文件
script_dir = os.path.dirname(os.path.abspath(__file__))
dll_path = os.path.join(script_dir, "embedded_compress_algorithm.dll")
if not os.path.exists(dll_path):
    raise FileNotFoundError(f"DLL 文件未找到，请确认路径：{dll_path}")

# 加载 DLL：先尝试 CDLL（C 调用约定），失败再尝试 WinDLL（stdcall 调用约定）
try:
    # __cdecl（C 语言默认，尤其用于可变参数或 C 兼容场景）
    dll = CDLL(dll_path)
except OSError as e:
    errmsg = f"CDLL无法加载 DLL，错误：\n{e}."
    try:
        # 使用 WinDLL 对于 __stdcall 约定
        dll = WinDLL(dll_path)
    except OSError as e:
        errmsg += f"WinDLL无法加载 DLL，错误：\n{e}."
        raise OSError(errmsg)

# ==================== 函数签名定义 ====================

# 定义 DLL 中所有可用的函数签名（参数类型和返回类型），修复：统一使用 c_size_t
# 包含 4 种算法（fastlz、lzss、points、channels）× 2 种模式（compress、decompress）× 2 种级别（file、buffer）
functions = [
    ("fastlz_compress_file", [c_char_p, c_char_p], c_int),
    ("fastlz_decompress_file", [c_char_p, c_char_p], c_int),
    ("fastlz_compress_buffer", [POINTER(c_ubyte), c_size_t, POINTER(c_ubyte), POINTER(c_size_t)], c_int),
    ("fastlz_decompress_buffer", [POINTER(c_ubyte), c_size_t, POINTER(c_ubyte), POINTER(c_size_t)], c_int),
    ("lzss_compress_file", [c_char_p, c_char_p], c_int),
    ("lzss_decompress_file", [c_char_p, c_char_p], c_int),
    ("lzss_compress_buffer", [POINTER(c_ubyte), c_size_t, POINTER(c_ubyte), POINTER(c_size_t)], c_int),
    ("lzss_decompress_buffer", [POINTER(c_ubyte), c_size_t, POINTER(c_ubyte), POINTER(c_size_t)], c_int),
    ("points_compress_file", [c_char_p, c_char_p], c_int),
    ("points_decompress_file", [c_char_p, c_char_p], c_int),
    ("points_compress_buffer", [POINTER(c_ubyte), c_size_t, POINTER(c_ubyte), POINTER(c_size_t)], c_int),
    ("points_decompress_buffer", [POINTER(c_ubyte), c_size_t, POINTER(c_ubyte), POINTER(c_size_t)], c_int),
    ("channels_compress_file", [c_char_p, c_char_p], c_int),
    ("channels_decompress_file", [c_char_p, c_char_p], c_int),
    ("channels_compress_buffer", [POINTER(c_ubyte), c_size_t, POINTER(c_ubyte), POINTER(c_size_t)], c_int),
    ("channels_decompress_buffer", [POINTER(c_ubyte), c_size_t, POINTER(c_ubyte), POINTER(c_size_t)], c_int),
]

# 提取所有算法名称（通过函数名的前缀部分），使用 dict 去重后再转 list
algorithm_names_set = {}
for func_name, argtypes, restype in functions:
    getattr(dll, func_name).argtypes = argtypes
    getattr(dll, func_name).restype = restype
    algorithm_names_set[(str(func_name).split('_', 1)[0])] = 0

algorithm_names = list(algorithm_names_set.keys())


# ==================== 公共接口 ====================

def get_algorithm_types():
    """
    获取当前 DLL 支持的所有算法名称列表。

    Returns:
        list[str]: 支持的算法名称列表，如 ['fastlz', 'lzss', 'points', 'channels']。
    """
    return algorithm_names


def compress(data: bytes, algorithm: str = algorithm_names[0]) -> bytes:
    """
    对字节数据进行压缩。

    Args:
        data: 待压缩的原始字节数据。
        algorithm: 使用的压缩算法名称，必须是 get_algorithm_types() 返回的算法之一。
                   默认为第一个可用算法。

    Returns:
        bytes: 压缩后的字节数据；若失败则返回空字节串 b"".
    """
    # 检查算法是否受支持
    if algorithm not in algorithm_names:
        print(f"{algorithm} not in {algorithm_names}")
        return b""
    try:
        in_len = len(data)
        # 分配输出缓冲区，大小为输入的 1.2 倍（经验值，覆盖大多数压缩场景）
        out_len = c_size_t(int(in_len * 1.2))  # 修复：使用 c_size_t
        in_buffer = (c_ubyte * in_len)(*data)  # 创建输入缓冲区
        out_buffer = (c_ubyte * out_len.value)()  # 分配输出缓冲区（注意：这里使用 .value 获取整数值）

        # 调用 DLL 中对应的 buffer 级压缩函数（修复：参数类型统一为 c_size_t）
        ret = getattr(dll, f"{algorithm}_compress_buffer")(
            in_buffer,  # 输入缓冲区
            c_size_t(in_len),  # 输入长度
            out_buffer,  # 输出缓冲区
            byref(out_len)  # 输出长度指针（函数内部会写入实际压缩后长度）
        )

        if ret != 0:
            raise RuntimeError(f"Buffer compression failed, return={ret}")
        # 截取实际长度的压缩结果并转为 bytes
        compressed_data = bytes(out_buffer[:out_len.value])
        return compressed_data

    except Exception as e:
        print(f"Error occurred: {str(e)}")
        return b""


def decompress(compressed_bytes: bytes, algorithm: str = algorithm_names[0]) -> bytes:
    """
    对字节数据进行解压缩。

    Args:
        compressed_bytes: 待解压的压缩字节数据。
        algorithm: 使用的解压算法名称，必须与压缩时使用的算法一致。

    Returns:
        bytes: 解压后的原始字节数据；若失败则返回空字节串 b"".
    """
    # 检查算法是否受支持
    if algorithm not in algorithm_names:
        print(f"{algorithm} not in {algorithm_names}")
        return b""
    try:
        in_len = len(compressed_bytes)
        # 分配输出缓冲区，大小为输入的 30 倍（经验值，确保足够容纳解压后数据）
        out_len = c_size_t(in_len * 30)  # 修复：使用 c_size_t
        in_buffer = (c_ubyte * in_len)(*compressed_bytes)
        out_buffer = (c_ubyte * out_len.value)()  # 分配输出缓冲区

        # 调用 DLL 中对应的 buffer 级解压函数（修复：参数类型统一为 c_size_t）
        ret = getattr(dll, f"{algorithm}_decompress_buffer")(
            in_buffer,  # 输入缓冲区
            c_size_t(in_len),  # 输入长度
            out_buffer,  # 输出缓冲区
            byref(out_len)  # 输出长度指针（函数内部会写入实际解压后长度）
        )

        if ret != 0:
            raise RuntimeError(f"Buffer decompression failed, return={ret}")
        # 截取实际长度的解压结果并转为 bytes
        decompressed_data = bytes(out_buffer[:out_len.value])
        return decompressed_data

    except Exception as e:
        print(f"Error occurred: {str(e)}")
        return b""


def compress_file(input_file: str, output_file: str, algorithm: str = algorithm_names[0]) -> int:
    """
    对文件进行压缩。

    Args:
        input_file: 待压缩的输入文件路径。
        output_file: 压缩后的输出文件路径。
        algorithm: 使用的压缩算法名称。

    Returns:
        int: 0 表示成功，-1 或其他非零值表示失败。
    """
    # 检查算法是否受支持
    if algorithm not in algorithm_names:
        print(f"{algorithm} not in {algorithm_names}")
        return -1
    try:
        # 转换文件路径为 bytes，以便传递给 C 函数（char*）
        input_bytes = input_file.encode('utf-8')
        output_bytes = output_file.encode('utf-8')

        ret = getattr(dll, f"{algorithm}_compress_file")(input_bytes, output_bytes)
        if ret != 0:
            raise RuntimeError(f"File compression failed, return={ret}")
        return ret
    except Exception as e:
        print(f"Error occurred: {str(e)}")
        return -1
    pass


def decompress_file(input_file: str, output_file: str, algorithm: str = algorithm_names[0]) -> int:
    """
    对文件进行解压缩。

    Args:
        input_file: 待解压的输入文件路径。
        output_file: 解压后的输出文件路径。
        algorithm: 使用的解压算法名称，必须与压缩时使用的算法一致。

    Returns:
        int: 0 表示成功，-1 或其他非零值表示失败。
    """
    # 检查算法是否受支持
    if algorithm not in algorithm_names:
        print(f"{algorithm} not in {algorithm_names}")
        return -1
    try:
        # 转换文件路径为 bytes，以便传递给 C 函数（char*）
        input_bytes = input_file.encode('utf-8')
        output_bytes = output_file.encode('utf-8')

        ret = getattr(dll, f"{algorithm}_decompress_file")(input_bytes, output_bytes)
        if ret != 0:
            raise RuntimeError(f"File decompression failed, return={ret}")
        return ret
    except Exception as e:
        print(f"Error occurred: {str(e)}")
        return -1
    pass


# ==================== 命令行入口 ====================

if __name__ == "__main__":
    import argparse, sys, time

    # 获取支持的算法列表
    algorithms = get_algorithm_types()

    # 创建主解析器
    parser = argparse.ArgumentParser(
        description="嵌入式文件压缩/解压工具",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # 添加子命令：compress / decompress / test
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ---------- 压缩子命令 ----------
    compress_parser = subparsers.add_parser(
        "compress",
        help="压缩文件",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    compress_parser.add_argument(
        "input_file",
        type=str,
        help="输入文件路径"
    )
    compress_parser.add_argument(
        "output_file",
        type=str,
        help="输出文件路径"
    )
    compress_parser.add_argument(
        "--algo",
        choices=algorithms,
        default=algorithms[0],
        help=f"压缩算法（可选：{', '.join(algorithms)}）",
        metavar="algorithm"
    )

    # ---------- 解压子命令 ----------
    decompress_parser = subparsers.add_parser(
        "decompress",
        help="解压缩文件",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    decompress_parser.add_argument(
        "input_file",
        type=str,
        help="输入文件路径"
    )
    decompress_parser.add_argument(
        "output_file",
        type=str,
        help="输出文件路径"
    )
    decompress_parser.add_argument(
        "--algo",
        choices=algorithms,
        default=algorithms[0],
        help=f"解压算法（必须与压缩时算法一致，可选：{', '.join(algorithms)}）",
        metavar="algorithm"
    )

    # ---------- 测试子命令 ----------
    decompress_parser = subparsers.add_parser(
        "test",
        help="测试文件",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    decompress_parser.add_argument(
        "input_file",
        type=str,
        help="输入文件路径"
    )
    decompress_parser.add_argument(
        "output_file",
        type=str,
        help="输出文件路径"
    )
    decompress_parser.add_argument(
        "--algo",
        choices=algorithms,
        default=algorithms[0],
        help=f"压缩/解压算法（可选：{', '.join(algorithms)}）",
        metavar="algorithm"
    )

    # 解析参数
    args = parser.parse_args()

    # ---------- 执行压缩操作 ----------
    if args.command == "compress":
        if not os.path.isfile(args.input_file):
            print(f"错误：输入文件不存在 '{args.input_file}'", file=sys.stderr)
            sys.exit(1)

        result = compress_file(
            input_file=args.input_file,
            output_file=args.output_file,
            algorithm=args.algo
        )
        sys.exit(result)

    # ---------- 执行解压操作 ----------
    elif args.command == "decompress":
        if not os.path.isfile(args.input_file):
            print(f"错误：输入文件不存在 '{args.input_file}'", file=sys.stderr)
            sys.exit(1)

        result = decompress_file(
            input_file=args.input_file,
            output_file=args.output_file,
            algorithm=args.algo
        )
        sys.exit(result)

    # ---------- 执行测试操作（先压缩再解压，最后对比校验） ----------
    elif args.command == "test":
        if not os.path.isfile(args.input_file):
            print(f"错误：输入文件不存在 '{args.input_file}'", file=sys.stderr)
            sys.exit(1)

        # 获取输入文件大小
        original_size = os.path.getsize(args.input_file)
        print(f"原始文件大小: {original_size} 字节")

        # 压缩文件
        compressed_file = args.output_file + ".compressed"
        print(f"正在压缩文件到 {compressed_file}...")

        # 记录压缩开始时间
        start_time = time.time()
        compress_result = compress_file(
            input_file=args.input_file,
            output_file=compressed_file,
            algorithm=args.algo
        )
        # 记录压缩结束时间
        end_time = time.time()
        compress_time = end_time - start_time
        print(f"压缩耗时: {compress_time:.4f} 秒")

        if compress_result != 0:
            print(f"压缩失败，返回码: {compress_result}", file=sys.stderr)
            sys.exit(1)

        # 获取压缩后文件大小并计算压缩率
        compressed_size = os.path.getsize(compressed_file)
        compression_ratio = compressed_size / original_size
        print(f"压缩后文件大小: {compressed_size} 字节")
        print(f"压缩率: {compression_ratio:.2%}")

        # 解压缩文件
        decompressed_file = args.output_file + ".decompressed"
        print(f"正在解压缩文件到 {decompressed_file}...")

        # 记录解压缩开始时间
        start_time = time.time()
        decompress_result = decompress_file(
            input_file=compressed_file,
            output_file=decompressed_file,
            algorithm=args.algo
        )
        # 记录解压缩结束时间
        end_time = time.time()
        decompress_time = end_time - start_time
        print(f"解压缩耗时: {decompress_time:.4f} 秒")

        if decompress_result != 0:
            print(f"解压失败，返回码: {decompress_result}", file=sys.stderr)
            sys.exit(1)

        # 比较原始文件和解压后文件的内容一致性
        print("比较原始文件和解压后文件...")
        with open(args.input_file, "rb") as f1, open(decompressed_file, "rb") as f2:
            original_data = f1.read()
            decompressed_data = f2.read()

        if original_data == decompressed_data:
            print("校验结果: 通过 (原始文件与解压后文件内容一致)")
        else:
            print("校验结果: 失败 (原始文件与解压后文件内容不一致)", file=sys.stderr)
            sys.exit(1)

        total_time = compress_time + decompress_time
        print(f"测试完成: 使用 {args.algo} 算法成功压缩和解压文件")
        print(f"总耗时: {total_time:.4f} 秒 (压缩: {compress_time:.4f} 秒, 解压: {decompress_time:.4f} 秒)")

    pass
