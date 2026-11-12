@echo off
chcp 65001 >nul
echo ============================================
echo   DGCS 地面站压力测试工具 - 打包为 EXE
echo ============================================
echo.

REM 检查 PyInstaller
where pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] 安装 PyInstaller...
    pip install pyinstaller
)

echo [INFO] 安装依赖...
pip install -r requirements.txt

echo.
echo [INFO] 清理旧构建...
if exist build_temp rmdir /s /q build_temp
if exist DGCS_StressTest.exe del /q DGCS_StressTest.exe

echo [INFO] 开始打包...

pyinstaller --onefile --windowed ^
    --name DGCS_StressTest ^
    --distpath . ^
    --workpath ./build_temp ^
    --specpath ./build_temp ^
    --collect-all scapy ^
    --collect-all scapy.arch ^
    --collect-all scapy.layers ^
    --collect-all scapy.modules ^
    --collect-all scapy.asn1 ^
    --hidden-import scapy ^
    --hidden-import scapy.arch.windows ^
    --hidden-import scapy.layers.l2 ^
    --hidden-import scapy.layers.inet ^
    --hidden-import scapy.sendrecv ^
    --hidden-import scapy.interfaces ^
    --exclude-module matplotlib ^
    --exclude-module numpy ^
    --exclude-module IPython ^
    --exclude-module pytest ^
    --exclude-module jedi ^
    --exclude-module nbformat ^
    --exclude-module zmq ^
    --exclude-module pygments ^
    --exclude-module PIL ^
    --exclude-module cryptography ^
    --exclude-module cffi ^
    --exclude-module lark ^
    --exclude-module rich ^
    --exclude-module prompt_toolkit ^
    --exclude-module parso ^
    --exclude-module jsonschema ^
    --exclude-module traitlets ^
    --exclude-module charset_normalizer ^
    --exclude-module certifi ^
    --exclude-module urllib3 ^
    --exclude-module requests ^
    --exclude-module psutil ^
    --exclude-module jinja2 ^
    --exclude-module sqlalchemy ^
    --exclude-module greenlet ^
    dgcs_stress_test.py

echo.
echo [INFO] 清理构建临时文件...
if exist build_temp rmdir /s /q build_temp

echo.
echo ============================================
echo   打包完成!
echo   输出: DGCS_StressTest.exe
echo ============================================
echo.
echo 提示: 如需 IP/MAC 伪造功能，请确保目标机器已安装 Npcap
echo      下载地址: https://npcap.com/#download
pause
