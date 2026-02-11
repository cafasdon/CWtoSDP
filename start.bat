@echo off
REM ============================================
REM CWtoSDP - One-Click Launcher (Windows)
REM ============================================
REM This script:
REM   1. Creates venv if it doesn't exist
REM   2. Activates the virtual environment
REM   3. Installs dependencies if needed
REM   4. Launches the Sync Manager GUI
REM ============================================

title CWtoSDP

REM Get the directory where this script is located
cd /d "%~dp0"

echo.
echo  ===========================================
echo  CWtoSDP - Sync Manager
echo  ===========================================
echo.

REM ============================================
REM Step 1: Check Python
REM ============================================
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python is not installed or not in PATH
    echo.
    echo  Please install Python 3.8+ from https://python.org
    echo  Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo  [OK] Python %PYVER% found

REM Check Python version is 3.8+
python -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" 2>nul
if errorlevel 1 (
    echo  [ERROR] Python 3.8 or higher is required.
    pause
    exit /b 1
)

REM ============================================
REM Step 2: Create venv if needed
REM ============================================
if not exist "venv\Scripts\activate.bat" (
    echo  [....] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo  [OK] Virtual environment created
) else (
    echo  [OK] Virtual environment exists
)

REM ============================================
REM Step 3: Activate venv
REM ============================================
call venv\Scripts\activate.bat

REM ============================================
REM Step 4: Install dependencies if needed
REM ============================================
python -c "import requests; import dotenv; import pandas" >nul 2>&1
if errorlevel 1 (
    echo  [....] Installing dependencies...
    python -m pip install --upgrade pip >nul 2>&1
    pip install -r requirements.txt
    if errorlevel 1 (
        echo  [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
    echo  [OK] Dependencies installed
) else (
    echo  [OK] Dependencies already installed
)

REM ============================================
REM Step 5: Create directories
REM ============================================
if not exist "data" mkdir data
if not exist "logs" mkdir logs

REM ============================================
REM Step 6: Check credentials
REM ============================================
if not exist "credentials.env" (
    echo.
    echo  [!] credentials.env not found
    echo      You can configure credentials in Settings (gear icon)
    echo.
)

REM ============================================
REM Step 7: Clear Python cache for fresh start
REM ============================================
echo  [....] Clearing Python cache...
if exist "src\__pycache__" rmdir /s /q "src\__pycache__" 2>nul
del /s /q "*.pyc" 2>nul >nul
echo  [OK] Python cache cleared

REM ============================================
REM Step 8: Launch GUI
REM ============================================
echo.
echo  Launching Sync Manager...
echo.
python -m src.main --sync

REM Keep window open if there was an error
if errorlevel 1 (
    echo.
    echo  [ERROR] An error occurred. See above for details.
    pause
)
