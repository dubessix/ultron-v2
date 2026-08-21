@echo off
setlocal
chcp 65001 >nul
title Ultron Personal V1
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ultron is not installed yet. Opening setup...
    call "SETUP_ULTRON_WINDOWS.bat"
    exit /b %errorlevel%
)

if not exist "data\logs" mkdir "data\logs"
set "ULTRON_HOME=%~dp0"
set "ULTRON_LAUNCH_LOG=%~dp0data\logs\launcher-ui.log"
cls

".venv\Scripts\python.exe" -m backend.app.cli start
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo ULTRON START FAILED
    echo Review the error above or open Ultron Doctor.
    echo Log: %ULTRON_LAUNCH_LOG%
    pause
)
exit /b %EXIT_CODE%
