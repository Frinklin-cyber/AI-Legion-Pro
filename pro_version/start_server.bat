@echo off
chcp 65001 >nul
title AI Legion HQ - Server Console
cd /d "%~dp0ai_army"
echo ============================================
echo    AI Legion HQ - Starting...
echo    Started: %date% %time%
echo ============================================
echo [%date% %time%] server-start >> run_stdout.log
python main.py
echo.
echo ============================================
echo    Server stopped. Window closes in 10s...
echo ============================================
timeout /t 10
