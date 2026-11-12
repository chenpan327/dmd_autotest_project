import argparse
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from utils.common import load_config
from utils.logger import log_manager
from utils.airtest_report import copy_dir, rmdir

# 12 小时超时（秒）
TIMEOUT_SECONDS = 43200
# 队列轮询间隔（秒）
_POLL_INTERVAL = 0.2


# ============================================================================
# Allure environment.properties 写入 / 重排
# ============================================================================

def _write_allure_environment(device_type, test_suites, mavlink_version, device_config, include_mavlink=True):
    """在 allure-results 中写入 environment.properties，报告 Overview 页展示环境信息"""
    allure_results = Path("allure-results")
    allure_results.mkdir(parents=True, exist_ok=True)

    env = []
    # 最重要的信息放前面
    env.append(f"Device={device_type}")
    env.append(f"TestSuite={test_suites}")
    if include_mavlink:
        env.append(f"MAVLink=v{mavlink_version}")

    # 设备配置
    if device_config:
        ip = device_config.get("ip") or device_config.get("acore_ip") or ""
        if ip:
            env.append(f"DroneIP={ip}")
        port = device_config.get("port", "")
        if port:
            env.append(f"UDPPort={port}")
        serial_port = device_config.get("serial_port", "")
        if serial_port:
            env.append(f"SerialPort={serial_port}")
        serial_baud = device_config.get("serial_baudrate", "")
        if serial_baud:
            env.append(f"SerialBaudrate={serial_baud}")

    # Jenkins 环境信息
    for jenkins_key, display_name in [
        ("BUILD_NUMBER", "BuildNumber"),
        ("BUILD_URL", "BuildURL"),
        ("GIT_BRANCH", "GitBranch"),
        ("GIT_COMMIT", "GitCommit"),
        ("JOB_NAME", "JobName"),
        ("NODE_NAME", "NodeName"),
    ]:
        val = os.environ.get(jenkins_key, "")
        if val:
            env.append(f"{display_name}={val}")

    # 次要信息放最后
    env.append(f"Python={platform.python_version()}")
    env.append(f"OS={platform.platform()}")
    env.append(f"ExecTime={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    env_path = allure_results / "environment.properties"
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(env) + "\n")
    log_manager.logger.info(f"已将环境信息写入 {env_path}")


def _reorder_allure_environment():
    """将 Firmware/SN 移至 Device 下方，确保重要信息优先展示"""
    env_path = Path("allure-results") / "environment.properties"
    if not env_path.exists():
        return

    with open(env_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    priority = {"Device": 0, "Firmware": 1, "SN": 2}

    ordered = sorted(lines, key=lambda line: priority.get(line.split("=", 1)[0], 99))

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ordered) + "\n")
    log_manager.logger.info("已重新排序 environment.properties")


# ============================================================================
# CLI 参数解析
# ============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description="Run pytest with Allure results")
    parser.add_argument("--device_type", type=str, help="Device type", required=True)
    parser.add_argument("--test_suites", type=str, help="Test Suites to run", required=True)
    parser.add_argument("--mavlink_version", type=str, help="MAVLink protocol version (e.g., 32, 37, 39, 41)", default=None)
    return parser.parse_args()


# ============================================================================
# pytest 子进程实时输出
# ============================================================================

def _enqueue_output(stream, queue):
    """后台线程：逐行读取子进程 stdout 并放入队列"""
    try:
        for line in iter(stream.readline, ''):
            queue.put(line)
    finally:
        stream.close()
        queue.put(None)  # 结束信号


def run_pytest_with_live_output(cmd) -> int:
    """
    执行 pytest 并实时输出。

    使用后台线程读取 stdout 避免 readline() 阻塞导致超时检测失效。
    :param cmd: 命令列表
    :return: pytest 的返回码，若发生异常或超时返回 -1
    """
    log_manager.logger.info("开始执行 pytest，实时输出用例执行过程...")
    log_manager.logger.debug(f"执行命令: {' '.join(cmd)}")
    start_time = time.time()

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        queue = Queue()
        reader_thread = threading.Thread(
            target=_enqueue_output, args=(process.stdout, queue), daemon=True
        )
        reader_thread.start()

        return_code = None
        while True:
            if time.time() - start_time > TIMEOUT_SECONDS:
                process.kill()
                process.wait()
                log_manager.logger.error(f"pytest 执行超时（超过 {TIMEOUT_SECONDS} 秒）")
                return -1

            try:
                line = queue.get(timeout=_POLL_INTERVAL)
                if line is None:
                    break
                print(line, end="", flush=True)
            except Empty:
                pass

            if return_code is None:
                return_code = process.poll()

        reader_thread.join(timeout=5)
        if return_code is None:
            return_code = process.wait()
        log_manager.logger.info(f"pytest 执行完成，返回码：{return_code}")
        return return_code

    except FileNotFoundError:
        log_manager.logger.error(f"命令未找到，请检查环境或命令拼写: {cmd[0]}")
        return -1
    except Exception as e:
        log_manager.logger.error(f"执行过程中发生未知错误: {e}")
        traceback.print_exc()
        return -1


# ============================================================================
# 设备特判钩子(Swarm_Painter_Ui 等)
# ============================================================================

def _swarm_painter_ui_pre_run(project_root: Path) -> None:
    """Swarm_Painter_Ui:测试启动前清理 temp/report/allure-results/allure-report"""
    case_dir = project_root / "src" / "Script" / "Drone_Show" / "SwarmPainter_Ui" / "Release_Testing"
    for d in (
        case_dir / "temp",
        case_dir / "report",
        project_root / "allure-results",
        project_root / "allure-report",
    ):
        rmdir(str(d))


def _swarm_painter_ui_post_allure(project_root: Path, allure_report: Path) -> None:
    """Swarm_Painter_Ui:allure 报告生成后把 temp 目录拷进报告目录"""
    case_dir = project_root / "src" / "Script" / "Drone_Show" / "SwarmPainter_Ui" / "Release_Testing"
    copy_dir(str(case_dir / "temp"), str(allure_report))


# 设备 → 钩子字典。main 函数靠这个分发特判逻辑,新增设备只需在此登记。
_DEVICE_HOOKS = {
    "Swarm_Painter_Ui": {
        "pre_run": _swarm_painter_ui_pre_run,
        "post_allure": _swarm_painter_ui_post_allure,
    },
}


# ============================================================================
# 测试脚本路径解析 / pytest 命令组装
# ============================================================================

def _resolve_script_dir(project_root: Path, device_type: str, test_suites: str, device_config: dict) -> Path:
    """解析测试脚本目录(优先 config.json 的 script_dir,否则自动搜索 Drone_Show / Drone_Applications)"""
    script_dir_override = device_config.get("script_dir")
    if script_dir_override:
        p = Path(script_dir_override)
        return p if p.is_absolute() else project_root / script_dir_override

    script_base = project_root / "src" / "Script"
    candidates = [
        script_base / "Drone_Show" / device_type,
        script_base / "Drone_Applications" / device_type,
    ]
    for c in candidates:
        if c.exists():
            return c / test_suites

    log_manager.logger.error(
        "测试脚本目录不存在,已搜索以下路径:\n"
        + "\n".join(f"  - {c / test_suites}" for c in candidates)
    )
    sys.exit(1)


def _build_pytest_command(
    device_type: str,
    test_suites: str,
    mavlink_version: str,
    script_dir: Path,
    script_paths: list,
    include_mavlink: bool = True,
) -> list:
    """组装 pytest 命令行(含 -v -s --tb=long + --device_type/--test_suites 参数 + 脚本路径)

    include_mavlink=False 时不追加 --mavlink_version (仅 Drone_Show 下的机型测试需要,
    Drone_Applications/BSP 底软等场景不涉及 MAVLink)。
    """
    cmd = [
        sys.executable, "-m", "pytest", "-v", "-s", "--tb=long",
        f"--device_type={device_type}",
        f"--test_suites={test_suites}",
    ]
    if include_mavlink:
        cmd.append(f"--mavlink_version={mavlink_version}")
    for rel in script_paths:
        full = script_dir / rel
        if not full.exists():
            log_manager.logger.error(f"测试脚本不存在: {full}")
            sys.exit(1)
        cmd.append(str(full))
    return cmd


# ============================================================================
# Allure 报告生成（已弃用，交由 Jenkins 插件处理）
# ============================================================================

# 此函数不再被调用，保留定义仅作历史参考
# def _generate_allure_report(project_root: Path) -> None:
#     ... (内容已省略，实际运行时不会执行)


# ============================================================================
# 主流程编排
# ============================================================================

def run_pytest() -> None:
    try:
        args = parse_args()
        project_root = Path(__file__).parent.resolve()

        config_data = load_config()
        if not config_data:
            log_manager.logger.error("配置文件 config.json 不存在或为空")
            sys.exit(1)
        log_manager.logger.info("成功加载配置文件")

        device_type = args.device_type
        test_suites = args.test_suites
        device_config = config_data.get(device_type, {})

        # 校验配置里有脚本路径
        script_paths = (
            device_config.get("testsuites", {})
            .get(test_suites, {})
            .get("script", [])
        )
        log_manager.logger.info(f"从配置文件获取到 {len(script_paths)} 个脚本路径")
        if not script_paths:
            log_manager.logger.error("无有效可用的测试用例路径")
            log_manager.logger.error(f"   请检查 DeviceType: {device_type}")
            log_manager.logger.error(f"   请检查 TestSuites: {test_suites}")
            sys.exit(1)
        log_manager.logger.info(f"有效测试用例路径: {script_paths}")

        # 解析测试脚本目录
        script_dir = _resolve_script_dir(project_root, device_type, test_suites, device_config)
        if not script_dir.exists():
            log_manager.logger.error(f"测试脚本目录不存在: {script_dir}")
            sys.exit(1)
        log_manager.logger.info(f"测试脚本目录存在: {script_dir}")

        # 设备特判钩子(目前只有 Swarm_Painter_Ui,清理临时目录)
        hooks = _DEVICE_HOOKS.get(device_type, {})
        if hooks.get("pre_run"):
            hooks["pre_run"](project_root)

        # 解析 MAVLink 版本(命令行优先,其次 config.json)
        # 仅 Drone_Show 下的机型测试涉及 MAVLink; Drone_Applications/BSP 底软等场景不注入
        include_mavlink = "Drone_Show" in script_dir.parts
        mavlink_version = args.mavlink_version or config_data.get("mavlink_version", "41")
        if include_mavlink:
            os.environ["DMD_MAVLINK_VERSION"] = mavlink_version
            log_manager.logger.info(f"MAVLink 协议版本: {mavlink_version}")
        else:
            log_manager.logger.info("非 Drone_Show 场景, 不注入 MAVLink 版本参数")

        # 组装 pytest 命令
        cmd = _build_pytest_command(
            device_type, test_suites, mavlink_version, script_dir, script_paths,
            include_mavlink=include_mavlink,
        )
        log_manager.logger.info(f"最终执行命令: {' '.join(cmd)}")

        # 清空 allure-results 并写入 environment.properties(conftest 在 pytest 期间会追加 Firmware/SN)
        allure_results = project_root / "allure-results"
        if allure_results.exists():
            shutil.rmtree(allure_results)
        allure_results.mkdir(parents=True, exist_ok=True)
        _write_allure_environment(device_type, test_suites, mavlink_version, device_config,
                                  include_mavlink=include_mavlink)

        # 执行 pytest
        return_code = run_pytest_with_live_output(cmd)

        # conftest 期间可能追加 Firmware/SN,按 priority 重排
        _reorder_allure_environment()

        if return_code != 0:
            log_manager.logger.error(
                f"pytest 执行失败,返回码:{return_code} — 将继续执行后续操作"
            )
        else:
            log_manager.logger.info("所有用例执行完成!")

        # ========== 移除内部 Allure 报告生成，由 Jenkins 插件接管 ==========
        # 此处不再调用 _generate_allure_report()，报告将由 Jenkins 后置操作生成
        log_manager.logger.info("Allure 报告将由 Jenkins 插件生成，跳过内部生成步骤")

        # 后置钩子（Swarm_Painter_Ui 需要拷贝 temp 到 allure-report）
        # 注意：由于报告由插件生成，此处 allure_report 目录可能尚不存在或为空，
        # 因此该钩子可能无法正常工作。建议将此操作移至 Jenkins 后置步骤中实现。
        # 此处暂时保留但注释掉，如需使用请取消注释并确保插件生成完毕后再执行。
        # if hooks.get("post_allure"):
        #     allure_report = project_root / "allure-report"
        #     hooks["post_allure"](project_root, allure_report)

        print("=" * 60, flush=True)
        print("流程结束，等待 Jenkins 插件生成 Allure 报告\n", flush=True)

        # 按 pytest 返回码退出(失败时 Jenkins 标红)
        if return_code != 0:
            sys.exit(return_code if return_code is not None else -1)

    except Exception as e:
        log_manager.logger.error(f"未捕获的异常: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run_pytest()