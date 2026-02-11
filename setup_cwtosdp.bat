@echo off
REM ============================================================================
REM  CWtoSDP - One-Click Installer for Windows
REM ============================================================================
REM
REM  HOW TO USE:
REM    1. Download this file
REM    2. Double-click it
REM    3. That's it!
REM
REM ============================================================================

title CWtoSDP Installer
mode con: cols=80 lines=40
setlocal enabledelayedexpansion

REM Get the script's own directory
set "SCRIPT_DIR=%~dp0"

echo.
echo  =======================================================
echo  CWtoSDP - One-Click Installer
echo  ConnectWise to ServiceDesk Plus Integration
echo  =======================================================
echo.

REM ============================================================================
REM  STEP 1: Determine install location
REM ============================================================================

set "INSTALL_DIR=%USERPROFILE%\CWtoSDP"

REM Check if we're already running from inside an installed copy
if exist "%SCRIPT_DIR%src\main.py" (
    set "INSTALL_DIR=%SCRIPT_DIR%"
    echo  [INFO] Running from existing installation at: %SCRIPT_DIR%
    echo         Will update in place.
    echo.
)

echo  Install location: %INSTALL_DIR%
echo.

REM ============================================================================
REM  STEP 2: Check / Install Python
REM ============================================================================

echo  -------------------------------------------------------
echo  Step 1 of 4: Checking Python...
echo  -------------------------------------------------------
echo.

REM Try python first, then python3, then py
set "PYTHON_CMD="

python --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    goto :python_found
)

python3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python3"
    goto :python_found
)

py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    goto :python_found
)

REM Python not found -- try to install it
echo  [!] Python is not installed.
echo.
echo  Attempting to install Python automatically...
echo.

REM Try winget first
winget --version >nul 2>&1
if not errorlevel 1 (
    echo  [....] Installing Python via Windows Package Manager...
    echo         This may take a minute or two...
    echo.
    winget install Python.Python.3.13 --accept-package-agreements --accept-source-agreements --scope user >nul 2>&1
    if not errorlevel 1 (
        echo  [OK] Python installed successfully!
        echo.
        echo  =======================================================
        echo  Python was just installed.
        echo  Please close this window and run the installer again.
        echo  =======================================================
        echo.
        pause
        exit /b 0
    ) else (
        echo  [!] Winget install failed. Trying alternative method...
        echo.
    )
)

REM Winget not available or failed -- try direct download
echo  [....] Finding latest Python version from python.org...
set "PY_INSTALLER=%TEMP%\python_installer.exe"

REM Dynamically resolve the latest Python Windows installer URL
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
    "try { " ^
    "  $page = Invoke-WebRequest -Uri 'https://www.python.org/downloads/' -UseBasicParsing; " ^
    "  $link = ($page.Links | Where-Object { $_.href -match 'python-3\.\d+\.\d+-amd64\.exe$' } | Select-Object -First 1).href; " ^
    "  if (-not $link) { " ^
    "    $verMatch = [regex]::Match($page.Content, 'Download Python (3\.\d+\.\d+)'); " ^
    "    if ($verMatch.Success) { " ^
    "      $v = $verMatch.Groups[1].Value; " ^
    "      $link = \"https://www.python.org/ftp/python/$v/python-$v-amd64.exe\" " ^
    "    } else { throw 'Could not determine latest Python version' } " ^
    "  }; " ^
    "  Write-Host \"  Downloading: $link\"; " ^
    "  Invoke-WebRequest -Uri $link -OutFile '%PY_INSTALLER%' " ^
    "} catch { " ^
    "  Write-Host \"  [ERROR] $($_.Exception.Message)\" -ForegroundColor Red; " ^
    "  exit 1 " ^
    "}"

if exist "%PY_INSTALLER%" (
    echo  [OK] Downloaded Python installer.
    echo.
    echo  [....] Installing Python (this may take a minute)...
    echo         Installing for current user only, no admin needed.
    echo.
    "%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1
    if not errorlevel 1 (
        echo  [OK] Python installed successfully!
        del "%PY_INSTALLER%" 2>nul
        echo.
        echo  =======================================================
        echo  Python was just installed.
        echo  Please close this window and run the installer again.
        echo  =======================================================
        echo.
        pause
        exit /b 0
    ) else (
        echo  [ERROR] Python installation failed.
        del "%PY_INSTALLER%" 2>nul
    )
) else (
    echo  [ERROR] Could not download Python installer.
)

echo.
echo  =======================================================
echo  Could not install Python automatically.
echo  Please install Python manually from python.org
echo  =======================================================
echo.
start https://www.python.org/downloads/
pause
exit /b 1

:python_found
for /f "tokens=*" %%i in ('%PYTHON_CMD% --version 2^>^&1') do set PYVER=%%i
echo  [OK] %PYVER% found
echo.

REM Verify version is 3.8+
%PYTHON_CMD% -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" 2>nul
if errorlevel 1 (
    echo  [ERROR] Python 3.8 or higher is required.
    echo         You have %PYVER%
    echo         Please update Python from https://python.org/downloads
    echo.
    pause
    exit /b 1
)

REM ============================================================================
REM  STEP 3: Download CWtoSDP from GitHub
REM ============================================================================

echo  -------------------------------------------------------
echo  Step 2 of 4: Downloading CWtoSDP...
echo  -------------------------------------------------------
echo.

if exist "%INSTALL_DIR%\src\main.py" (
    echo  [OK] CWtoSDP is already downloaded at:
    echo       %INSTALL_DIR%
    echo       Skipping download.
    echo.
    goto :setup_app
)

echo  [....] Downloading latest version from GitHub...
echo.

set "ZIP_FILE=%TEMP%\cwtosdp_latest.zip"
set "EXTRACT_DIR=%TEMP%\cwtosdp_extract"

REM Download the ZIP
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
    "try { " ^
    "  Invoke-WebRequest -Uri 'https://github.com/cafasdon/CWtoSDP/archive/refs/heads/main.zip' -OutFile '%ZIP_FILE%' -UseBasicParsing; " ^
    "  Write-Host 'Download complete.' " ^
    "} catch { " ^
    "  Write-Host 'ERROR: Download failed.' -ForegroundColor Red; " ^
    "  Write-Host $_.Exception.Message; " ^
    "  exit 1 " ^
    "}"

if not exist "%ZIP_FILE%" (
    echo.
    echo  [ERROR] Failed to download CWtoSDP.
    echo         Please check your internet connection and try again.
    echo.
    pause
    exit /b 1
)

echo  [OK] Downloaded.
echo.

REM Extract
echo  [....] Extracting files...

REM Clean up any previous extraction
if exist "%EXTRACT_DIR%" rmdir /s /q "%EXTRACT_DIR%" 2>nul
if not exist "%EXTRACT_DIR%" mkdir "%EXTRACT_DIR%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Expand-Archive -Path '%ZIP_FILE%' -DestinationPath '%EXTRACT_DIR%' -Force"

if errorlevel 1 (
    echo  [ERROR] Failed to extract files.
    del "%ZIP_FILE%" 2>nul
    pause
    exit /b 1
)

REM Move from CWtoSDP-main subfolder to install location
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

REM The ZIP extracts to CWtoSDP-main/ - copy contents to install dir
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Get-ChildItem '%EXTRACT_DIR%\CWtoSDP-main\*' | Copy-Item -Destination '%INSTALL_DIR%' -Recurse -Force"

REM Clean up
del "%ZIP_FILE%" 2>nul
rmdir /s /q "%EXTRACT_DIR%" 2>nul

if exist "%INSTALL_DIR%\src\main.py" (
    echo  [OK] Extracted to %INSTALL_DIR%
    echo.
) else (
    echo  [ERROR] Extraction failed - src\main.py not found.
    echo         Please try again or download manually from GitHub.
    echo.
    pause
    exit /b 1
)

:setup_app

REM ============================================================================
REM  STEP 4: Set up the application (venv + dependencies)
REM ============================================================================

echo  -------------------------------------------------------
echo  Step 3 of 4: Setting up the application...
echo  -------------------------------------------------------
echo.

pushd "%INSTALL_DIR%"

REM Create virtual environment
if not exist "venv\Scripts\activate.bat" (
    echo  [....] Creating virtual environment...
    %PYTHON_CMD% -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create virtual environment.
        popd
        pause
        exit /b 1
    )
    echo  [OK] Virtual environment created.
) else (
    echo  [OK] Virtual environment already exists.
)
echo.

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install / update dependencies
echo  [....] Installing dependencies...
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  [ERROR] Failed to install dependencies.
    popd
    pause
    exit /b 1
)
echo  [OK] Dependencies installed.
echo.

REM Create data/logs directories
if not exist "data" mkdir data
if not exist "logs" mkdir logs

REM ============================================================================
REM  STEP 5: Create Desktop shortcut
REM ============================================================================

echo  -------------------------------------------------------
echo  Step 4 of 4: Creating Desktop shortcut...
echo  -------------------------------------------------------
echo.

set "SHORTCUT=%USERPROFILE%\Desktop\CWtoSDP.bat"

if not exist "%SHORTCUT%" (
    (
        echo @echo off
        echo title CWtoSDP - Sync Manager
        echo cd /d "%INSTALL_DIR%"
        echo call start.bat
    ) > "%SHORTCUT%"
    echo  [OK] Desktop shortcut created: CWtoSDP.bat
) else (
    echo  [OK] Desktop shortcut already exists.
)
echo.

REM ============================================================================
REM  DONE! Launch the application
REM ============================================================================

echo.
echo  =======================================================
echo  Installation Complete!
echo  Installed to: %INSTALL_DIR%
echo  =======================================================
echo.
echo  Launching CWtoSDP now...
echo.

REM Clear pycache for a fresh start
if exist "src\__pycache__" rmdir /s /q "src\__pycache__" 2>nul

REM Launch the GUI
python -m src.main --sync

REM Keep window open if there was an error
if errorlevel 1 (
    echo.
    echo  [ERROR] Something went wrong. See the messages above.
    echo.
    pause
)

popd
endlocal
