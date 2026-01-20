@echo off
REM ============================================
REM CWtoSDP Installer - Windows
REM ============================================

title CWtoSDP Installer

REM Get the directory where this script is located
cd /d "%~dp0"

echo.
echo ============================================
echo  CWtoSDP Installer for Windows
echo ============================================
echo.

REM Check if Python is available
echo [1/5] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Python is not installed or not in PATH
    echo.
    echo Please install Python 3.8+ from https://python.org
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo        Found Python %PYVER%

REM Check Python version is 3.8+
python -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Python 3.8 or higher is required.
    echo        You have Python %PYVER%
    echo.
    pause
    exit /b 1
)

REM Create virtual environment
echo.
echo [2/5] Creating virtual environment...
if exist "venv" (
    echo        Virtual environment already exists, skipping...
) else (
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
    echo        Created venv/
)

REM Activate virtual environment
echo.
echo [3/5] Activating virtual environment...
call venv\Scripts\activate.bat
echo        Activated

REM Install dependencies
echo.
echo [4/5] Installing dependencies...
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

REM Check for credentials
echo.
echo [5/5] Checking configuration...
if exist "credentials.env" (
    echo        credentials.env found
) else (
    echo.
    echo WARNING: credentials.env not found!
    echo.
    echo Please create credentials.env with the following format:
    echo.
    echo   CLIENT_ID=your_connectwise_client_id
    echo   CLIENT_SECRET=your_connectwise_client_secret
    echo   ZOHO_CLIENT_ID=your_zoho_client_id
    echo   ZOHO_CLIENT_SECRET=your_zoho_client_secret
    echo   ZOHO_REFRESH_TOKEN=your_zoho_refresh_token
    echo.
)

REM Create data directory
if not exist "data" mkdir data
if not exist "logs" mkdir logs

echo.
echo ============================================
echo  Installation Complete!
echo ============================================
echo.
echo To launch the Sync Manager:
echo   - Double-click: launch_sync.bat
echo   - Or run: python -m src.main --sync
echo.
echo ============================================
echo.
pause

