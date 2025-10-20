import os
import subprocess
import sys
from pathlib import Path


def run_pytest(generate_report: bool = True) -> None:
    """
    运行 pytest 测试（完全依赖 pytest.ini 配置），并可选生成 Allure 报告

    参数:
        generate_report: 是否生成 Allure HTML 报告，默认 True
    """
    # 基础命令：仅调用 pytest，所有配置读取 pytest.ini
    cmd = ["pytest"]

    # 执行 pytest 命令
    print(f"开始执行测试（依赖 pytest.ini 配置）... 命令: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # 输出测试结果
    print("\n=== 测试输出 ===")
    print(result.stdout)

    # 检查是否有错误
    if result.returncode != 0:
        print("\n=== 测试错误 ===")
        print(result.stderr)
        sys.exit(result.returncode)

    # 生成 Allure 报告（若启用）
    if generate_report:
        generate_allure_report()


def generate_allure_report() -> None:
    """使用本地 allure 工具生成 HTML 报告"""
    # Allure 结果数据目录（与 pytest.ini 中 --alluredir 配置保持一致）
    allure_results = Path("./allure-results")
    # 报告输出目录
    allure_report = Path("./allure-report")
    # 本地 allure 工具路径（与 pytest.ini 同级的 allure-2.35.1）
    allure_cmd = "./allure-2.35.1/bin/allure"

    # 检查 Allure 结果目录是否存在
    if not allure_results.exists():
        print(f"警告：未找到 Allure 结果目录 {allure_results}，跳过报告生成")
        return

    # 根据系统调整命令（Windows 需加 .bat 后缀）
    if sys.platform.startswith("win32"):
        allure_cmd += ".bat"

    # 生成 HTML 报告的命令（清除旧报告）
    cmd = [
        allure_cmd,
        "generate",
        str(allure_results),
        "-o",
        str(allure_report),
        "--clean"
    ]

    print(f"\n开始生成 Allure 报告... 命令: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode == 0:
        print(f"Allure 报告生成成功！路径：{allure_report.resolve()}")
        print(f"可通过命令查看：{allure_cmd} serve {allure_results}")
    else:
        print(f"生成 Allure 报告失败：{result.stderr}")


if __name__ == "__main__":
    # 直接运行测试，所有配置由 pytest.ini 控制
    run_pytest(generate_report=True)