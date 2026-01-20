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

# Run the sync script with any provided arguments
python3 run_sync.py "$@"

# Exit with the Python script's exit code
exit $?

