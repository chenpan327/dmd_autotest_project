@echo off
:: 关闭命令回显，解决中文乱码
chcp 65001 > nul
setlocal enabledelayedexpansion

REM ============================================================================
REM MAINTENANCE NOTES (keep this block ASCII-only, see note 4):
REM   1. Save this file as UTF-8 without BOM. chcp 65001 makes the Chinese
REM      messages display correctly.
REM   2. Escape special chars in echo lines: pipe, angle brackets, ampersand,
REM      caret. A bare pipe in an echo line is treated as a command pipe and
REM      caused Jenkins build failures before ("not recognized").
REM   3. PROJECT_ROOT can be overridden from outside. Jenkins node uses the
REM      D: checkout, local checkouts may use C:. Default is the D: path.
REM   4. REM/comment lines must stay ASCII-only: mixed multi-byte text in
REM      comments gets mis-parsed by cmd under codepage 65001 and random
REM      fragments execute as commands (also caused "not recognized").
REM ============================================================================

echo.
echo     ******     ***   ***    ******
echo     **  **     **** ****    **  **
echo     **  **     ** *** **    **  **
echo     **  **     **  *  **    **  **
echo     ******     **     **    ******
echo     ======     ==     ==    ======
echo.
echo     +----------------------------------------------+
echo     ^|  +--------------------------------------+  ^|
echo     ^|  ^|  +------------------------------+  ^|  ^|
echo     ^|  ^|  ^|                              ^|  ^|  ^|
echo     ^|  ^|  ^|      测  试  开  发  部      ^|  ^|  ^|
echo     ^|  ^|  ^|                              ^|  ^|  ^|
echo     ^|  ^|  +------------------------------+  ^|  ^|
echo     ^|  +--------------------------------------+  ^|
echo     +----------------------------------------------+
echo.
echo               自动化测试构建脚本
echo.
echo ========================================================================
echo.

echo DIR CHECK: 检查并创建 Allure 目录结构...
REM Set path variables. PROJECT_ROOT can be overridden via environment.
if not defined PROJECT_ROOT set "PROJECT_ROOT=D:\workspace\code\dmd_autotest_project"
set "ALLURE_RESULTS=!PROJECT_ROOT!\allure-results"
set "ALLURE_REPORT=!PROJECT_ROOT!\allure-report"
set "ALLURE_HISTORY=!PROJECT_ROOT!\allure-history"

:: 目录检查与创建
if not exist "!ALLURE_RESULTS!" (
    mkdir "!ALLURE_RESULTS!"
    echo   - INFO: 已创建结果目录：!ALLURE_RESULTS!
) else (
    echo   - INFO: 结果目录已存在：!ALLURE_RESULTS!
)

if not exist "!ALLURE_REPORT!" (
    mkdir "!ALLURE_REPORT!"
    echo   - INFO: 已创建报告目录：!ALLURE_REPORT!
) else (
    echo   - INFO: 报告目录已存在：!ALLURE_REPORT!
)

if not exist "!ALLURE_HISTORY!" (
    mkdir "!ALLURE_HISTORY!"
    echo   - INFO: 已创建历史目录：!ALLURE_HISTORY!
) else (
    echo   - INFO: 历史目录已存在：!ALLURE_HISTORY!
)

:: 清空旧的结果文件，避免累积影响报告
if exist "!ALLURE_RESULTS!" (
    echo   - INFO: 清空旧的结果文件...
    del /q "!ALLURE_RESULTS!\*" 2>nul
)

:: 参数合法性检查（含占位符与 BSP_APP/BoardType 分发）
echo.
echo PARAM CHECK: 参数合法性检查
echo ------------------------------------------------------------------------
echo.

set "param_error=0"

if "%DeviceType%"=="" (
    echo   - ERROR: 错误：设备类型不能为空！
    set "param_error=1"
) else if "%DeviceType%"=="---请选择待测对象---" (
    echo   - ERROR: 错误：请从下拉列表中选择有效的设备类型！
    set "param_error=1"
)

:: 当选择 BSP_APP 时，需要额外检查 BoardType
if "%DeviceType%"=="BSP_APP" (
    if "%BoardType%"=="" (
        echo   - ERROR: 错误：选择了 BSP_APP 但未选择具体板子！
        set "param_error=1"
    ) else if "%BoardType%"=="-" (
        echo   - ERROR: 错误：请从 BoardType 下拉中选择有效的 BSP 板子！
        set "param_error=1"
    ) else if "%BoardType%"=="---请选择具体BSP板子---" (
        echo   - ERROR: 错误：请从 BoardType 下拉中选择有效的 BSP 板子！
        set "param_error=1"
    )
)

if "%TestSuites%"=="" (
    echo   - ERROR: 错误：测试套件不能为空！
    set "param_error=1"
) else if "%TestSuites%"=="---请下拉勾选测试套件---" (
    echo   - ERROR: 错误：请从下拉列表中选择有效的测试套件！
    set "param_error=1"
) else if "%TestSuites%"=="---请先选择具体BSP板子---" (
    echo   - ERROR: 错误：请先选择具体的 BSP 板子！
    set "param_error=1"
)

if !param_error! equ 1 (
    echo.
    echo   - WARN: 参数检查失败，请检查构建参数配置！
    echo.
    exit /b 1
) else (
    echo   - OK: 所有必填参数检查通过
)

:: 根据 DeviceType 决定实际设备名（用于传递给 main.py）
set "ACTUAL_DEVICE=%DeviceType%"
if "%DeviceType%"=="BSP_APP" (
    set "ACTUAL_DEVICE=%BoardType%"
)

:: 输出参数配置
echo.
echo PARAM CONFIG: 测试参数配置
echo ------------------------------------------------------------------------
echo   设备类型（原始）：    %DeviceType%
if "%DeviceType%"=="BSP_APP" (
    echo   实际设备（传递）：    !ACTUAL_DEVICE!
)
echo   测试套件：    %TestSuites%
echo ------------------------------------------------------------------------
echo   项目根目录：  !PROJECT_ROOT!
echo   结果目录：    !ALLURE_RESULTS!
echo   报告目录：    !ALLURE_REPORT!
echo   历史目录：    !ALLURE_HISTORY!
echo ------------------------------------------------------------------------
echo.

:: Python 环境检查与自动配置
set "PYTHON_EXE=!PROJECT_ROOT!\.venv\Scripts\python.exe"
echo PYTHON CHECK: 检查 Python 运行环境
echo ------------------------------------------------------------------------
echo   Python 解释器路径：!PYTHON_EXE!

if not exist "!PYTHON_EXE!" (
    echo.
    echo   - WARN: 虚拟环境不存在，开始自动创建...
    echo.
    echo   [1/2] 创建虚拟环境 .venv ...
    python -m venv "!PROJECT_ROOT!\.venv"
    if errorlevel 1 (
        echo   - ERROR: 虚拟环境创建失败，请检查系统 Python 是否安装
        exit /b 1
    )
    echo   - OK: 虚拟环境创建成功
    echo.
    echo   [2/2] 安装依赖包（requirements.txt）...
    "!PYTHON_EXE!" -m pip install -r "!PROJECT_ROOT!\requirements.txt" --quiet
    if errorlevel 1 (
        echo   - ERROR: 依赖包安装失败，请检查网络连接及 requirements.txt
        exit /b 1
    )
    echo   - OK: 依赖包安装完成
    echo.
    echo   - INFO: Python 运行环境已自动配置完成
) else (
    echo   - OK: Python 解释器路径验证通过
)

:: 执行测试脚本（切换到项目根目录，避免相对路径问题）
echo.
echo TEST RUN: 开始执行测试脚本
echo ------------------------------------------------------------------------
cd /d "!PROJECT_ROOT!"
echo   执行命令：!PYTHON_EXE! main.py --device_type "!ACTUAL_DEVICE!" --test_suites "%TestSuites%"
echo ------------------------------------------------------------------------
echo.

"!PYTHON_EXE!" main.py --device_type "!ACTUAL_DEVICE!" --test_suites "%TestSuites%"
set "TEST_RESULT=%errorlevel%"

:: 输出执行结果
echo.
echo TEST RESULT: 测试执行结果
echo ------------------------------------------------------------------------
if %TEST_RESULT% equ 0 (
    echo   - SUCCESS: 测试执行成功
    echo             所有测试用例执行完成！
) else (
    echo   - FAILED: 测试执行失败
    echo             错误码：%TEST_RESULT%
    echo.
    exit /b %TEST_RESULT%
)

echo.
echo ========================================================================
echo                      构建流程执行完成
echo ========================================================================
echo.
