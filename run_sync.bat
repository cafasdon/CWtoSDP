@echo off
REM ============================================================================
REM CWtoSDP Automated Sync Launcher for Windows
REM ============================================================================
REM This script runs the automated synchronization from ConnectWise to SDP.
REM 
REM Usage:
REM   run_sync.bat              - Run with prompts (interactive)
REM   run_sync.bat --dry-run    - Preview mode (no changes)
REM   run_sync.bat --yes        - Auto-confirm (no prompts)
REM ============================================================================

cd /d "%~dp0"

REM Check for virtual environment
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM Run the sync script with any provided arguments
python run_sync.py %*

REM Keep window open if there was an error
if %ERRORLEVEL% neq 0 (
    echo.
    echo Sync completed with errors. Press any key to exit...
    pause > nul
)

