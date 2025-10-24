import subprocess
import sys
import time
from pathlib import Path


def run_pytest(generate_report: bool = True) -> None:
    """
    运行 pytest 测试（完全依赖 pytest.ini 配置），并可选生成 Allure 报告
    适配编码处理和异常捕获
    """
    # 基础命令：仅调用 pytest，所有配置读取 pytest.ini
    cmd = ["pytest"]

    # 执行 pytest 命令（指定编码为 utf-8，避免输出解码错误）
    print("\n" + "=" * 60)
    print(f"▶️  开始执行测试（{time.strftime('%Y-%m-%d %H:%M:%S')}）")
    print(f"📋  执行命令: {' '.join(cmd)}")
    print("=" * 60 + "\n")

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",  # 强制使用 utf-8 解码输出
            errors="ignore"    # 忽略无法解码的字符
        )
    except Exception as e:
        print("\n" + "*" * 60)
        print("❌  === 执行测试时发生异常 ===")
        print(f"💬  错误信息: {str(e)}")
        print("*" * 60 + "\n")
        sys.exit(1)

    # 输出测试结果
    print("\n" + "-" * 60)
    print("📝  === 测试输出 ===")
    print("-" * 60)
    print(result.stdout)

    # 检查是否有错误
    if result.returncode != 0:
        print("\n" + "*" * 60)
        print("❌  === 测试执行失败 ===")
        print("-" * 60)
        print(result.stderr)
        print("*" * 60 + "\n")
        sys.exit(result.returncode)
    else:
        print("\n" + "=" * 60)
        print(f"✅  测试执行成功（{time.strftime('%Y-%m-%d %H:%M:%S')}）")
        print("=" * 60 + "\n")

    # 生成 Allure 报告（若启用）
    if generate_report:
        generate_allure_report()


def generate_allure_report() -> None:
    """使用本地 allure 工具生成 HTML 报告，适配路径和系统"""
    # 项目根目录（main.py 所在目录）
    project_root = Path(__file__).parent.resolve()
    # Allure 结果数据目录（与 pytest.ini 中 --alluredir 配置保持一致）
    allure_results = project_root / "allure-results"
    # 报告输出目录
    allure_report = project_root / "allure-report"
    # 本地 allure 工具路径（根目录下的 allure-2.35.1）
    allure_cmd = project_root / "allure-2.35.1" / "bin" / "allure"

    # 根据系统调整命令（Windows 需加 .bat 后缀）
    if sys.platform.startswith("win32"):
        allure_cmd = allure_cmd.with_suffix(".bat")

    # 打印报告生成流程
    print("\n" + "=" * 60)
    print(f"📊  开始生成 Allure 报告（{time.strftime('%Y-%m-%d %H:%M:%S')}）")
    print("=" * 60 + "\n")

    # 检查 Allure 结果目录是否存在
    if not allure_results.exists():
        print(f"⚠️  警告：未找到 Allure 结果目录 {allure_results}，跳过报告生成")
        return

    # 检查 Allure 工具是否存在
    if not allure_cmd.exists():
        print("\n" + "*" * 60)
        print("❌  错误：未找到 Allure 工具")
        print(f"📂  期望路径：{allure_cmd}")
        print("💡  请确认 allure-2.35.1 文件夹已放在项目根目录")
        print("*" * 60 + "\n")
        return

    # 生成 HTML 报告的命令（清除旧报告）
    cmd = [
        str(allure_cmd),  # 转换为字符串路径
        "generate",
        str(allure_results),
        "-o",
        str(allure_report),
        "--clean"
    ]

    print(f"📋  执行命令: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
    except Exception as e:
        print("\n" + "*" * 60)
        print("❌  生成报告时发生异常")
        print(f"💬  错误信息: {str(e)}")
        print("*" * 60 + "\n")
        return

    if result.returncode == 0:
        print("\n" + "=" * 60)
        print(f"✅  Allure 报告生成成功（{time.strftime('%Y-%m-%d %H:%M:%S')}）")
        print(f"📂  报告路径：{allure_report.resolve()}")
        print("💡  可通过以下命令查看报告：")
        print(f"   {str(allure_cmd)} serve {str(allure_results)}")
        print("=" * 60 + "\n")
    else:
        print("\n" + "*" * 60)
        print("❌  生成 Allure 报告失败")
        print("-" * 60)
        print(result.stderr)
        print("*" * 60 + "\n")


if __name__ == "__main__":
    # 程序启动提示
    print("=" * 70)
    print(f"🚀  自动化测试程序启动（{time.strftime('%Y-%m-%d %H:%M:%S')}）")
    print(f"📂  项目根目录：{Path(__file__).parent.resolve()}")
    print("=" * 70)
    # 直接运行测试，所有配置由 pytest.ini 控制
    run_pytest(generate_report=True)