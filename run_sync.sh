#!/bin/bash
# ============================================================================
# CWtoSDP Automated Sync Launcher for Linux
# ============================================================================
# This script runs the automated synchronization from ConnectWise to SDP.
# 
# Usage:
#   ./run_sync.sh              - Run with prompts (interactive)
#   ./run_sync.sh --dry-run    - Preview mode (no changes)
#   ./run_sync.sh --yes        - Auto-confirm (no prompts)
#
# Make executable: chmod +x run_sync.sh
# ============================================================================

cd "$(dirname "$0")"

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Install dependencies if missing
python3 -c "import requests; import dotenv" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt || { echo "[ERROR] Failed to install dependencies"; exit 1; }
fi

# Run the sync script with auto-confirm (--yes) by default
python3 run_sync.py --yes "$@"

# Exit with the Python script's exit code
exit $?

