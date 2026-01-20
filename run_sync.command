#!/bin/bash
# ============================================================================
# CWtoSDP Automated Sync Launcher for macOS
# ============================================================================
# This script runs the automated synchronization from ConnectWise to SDP.
# 
# Usage:
#   ./run_sync.command              - Run with prompts (interactive)
#   ./run_sync.command --dry-run    - Preview mode (no changes)
#   ./run_sync.command --yes        - Auto-confirm (no prompts)
#
# Make executable: chmod +x run_sync.command
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

# Keep terminal open for review
echo ""
echo "Press any key to close..."
read -n 1

