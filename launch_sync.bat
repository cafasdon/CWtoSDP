@echo off
REM ============================================
REM CWtoSDP Sync Manager Launcher - Windows
REM ============================================

title CWtoSDP Sync Manager

REM Get the directory where this script is located
cd /d "%~dp0"

echo ============================================
echo  CWtoSDP Sync Manager
echo ============================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

REM Check for virtual environment
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
)

REM Check if requirements are installed
python -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Required packages not installed.
    echo Run: pip install -r requirements.txt
    pause
    exit /b 1
)

REM Launch the Sync Manager GUI
echo Launching Sync Manager...
echo.
python -m src.main --sync

REM Keep window open if there was an error
if errorlevel 1 (
    echo.
    echo An error occurred. Press any key to close.
    pause >nul
)

