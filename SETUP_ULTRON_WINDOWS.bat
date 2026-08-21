@echo off
setlocal
chcp 65001 >nul
title Ultron Personal V1 Setup
cd /d "%~dp0"

echo ==============================================
echo   ULTRON PERSONAL V1 - WINDOWS SETUP
echo ==============================================
echo.

set "PYTHON_CMD="
where py >nul 2>&1 && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD where python >nul 2>&1 && set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
    echo Python is missing. Trying the official Windows package manager...
    where winget >nul 2>&1 || (
        echo Winget is unavailable. Install Python 3.10 or newer from python.org, then run this setup again.
        pause
        exit /b 1
    )
    winget install --id Python.Python.3.12 --exact --accept-package-agreements --accept-source-agreements
    echo Python installation was requested. Close this window, then double-click setup again.
    pause
    exit /b 0
)

where git >nul 2>&1 || (
    echo Git is missing. Installing Git for Windows...
    where winget >nul 2>&1 || (
        echo Winget is unavailable. Install Git for Windows, then run setup again.
        pause
        exit /b 1
    )
    winget install --id Git.Git --exact --accept-package-agreements --accept-source-agreements
    echo Git installation was requested. Close this window, then double-click setup again.
    pause
    exit /b 0
)

echo Opening the Ultron setup window...
%PYTHON_CMD% -m backend.app.installer
if errorlevel 1 (
    echo.
    echo Setup window could not start. Read the message above.
    pause
    exit /b 1
)
endlocal
