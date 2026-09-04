@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo  ZEROagent 企业知识大脑 - 一键启动 (Windows)
echo ============================================
echo.

REM ---- 1. 检查 Python ----
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.11+（安装时勾选 Add to PATH）:
    echo         https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python 已就绪

REM ---- 2. 安装依赖 ----
echo.
echo [1/4] 安装 Python 依赖...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试
    pause
    exit /b 1
)

REM ---- 3. 检查 Ollama 服务 ----
echo.
echo [2/4] 检查本地 Ollama 服务 (localhost:11434)...
where ollama >nul 2>&1
if errorlevel 1 (
    echo [提示] 未检测到 Ollama，请先安装: https://ollama.com/download
    echo        安装完成后打开 Ollama（任务栏图标），再重新运行本脚本。
    pause
    exit /b 1
)
curl -s --max-time 3 http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [提示] Ollama 已安装但服务未运行，正在启动...
    start "" ollama app
    timeout /t 5 /nobreak >nul
)
curl -s --max-time 3 http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [错误] Ollama 服务仍未就绪，请手动打开 Ollama 后重试。
    pause
    exit /b 1
)
echo [OK] Ollama 服务已就绪

REM ---- 4. 拉取本地模型（数据不出域，模型存放在本机）----
echo.
echo [3/4] 检查并拉取本地模型（首次约 5GB，视网速可能需要几分钟）...
ollama list | findstr /C:"nomic-embed-text" >nul || ollama pull nomic-embed-text
ollama list | findstr /C:"qwen2.5:7b" >nul || ollama pull qwen2.5:7b

REM ---- 5. 检查 8000 端口 ----
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if not errorlevel 1 (
    echo.
    echo [提示] 端口 8000 已被占用。若为旧版 ZEROagent 服务，请先关闭它再运行本脚本。
)

REM ---- 6. 启动服务 ----
echo.
echo [4/4] 启动服务，浏览器将自动打开: http://localhost:8000
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8000"
python main.py

pause
