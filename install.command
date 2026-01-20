#!/bin/bash
# ============================================
# CWtoSDP Installer - macOS
# ============================================

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo ""
echo "============================================"
echo " CWtoSDP Installer for macOS"
echo "============================================"
echo ""

# Check if Python 3 is available
echo "[1/6] Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo ""
    echo "ERROR: Python 3 is not installed"
    echo ""
    echo "Install Python 3.8+ using one of these methods:"
    echo "  - Download from https://python.org"
    echo "  - Using Homebrew: brew install python"
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

PYVER=$(python3 --version 2>&1 | cut -d' ' -f2)
echo "       Found Python $PYVER"

# Check Python version is 3.8+
python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null
if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Python 3.8 or higher is required."
    echo "       You have Python $PYVER"
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

# Check for tkinter
echo ""
echo "[2/6] Checking tkinter..."
python3 -c "import tkinter" 2>/dev/null
if [ $? -ne 0 ]; then
    echo ""
    echo "WARNING: tkinter is not installed."
    echo "Install it with: brew install python-tk"
    echo ""
fi

# Create virtual environment
echo ""
echo "[3/6] Creating virtual environment..."
if [ -d "venv" ]; then
    echo "       Virtual environment already exists, skipping..."
else
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create virtual environment"
        read -p "Press Enter to close..."
        exit 1
    fi
    echo "       Created venv/"
fi

# Activate virtual environment
echo ""
echo "[4/6] Activating virtual environment..."
source venv/bin/activate
echo "       Activated"

# Install dependencies
echo ""
echo "[5/6] Installing dependencies..."
python -m pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Failed to install dependencies"
    read -p "Press Enter to close..."
    exit 1
fi

# Make launcher scripts executable
echo ""
echo "[6/6] Setting up launchers..."
chmod +x launch_sync.command launch_sync.sh 2>/dev/null
echo "       Made launch scripts executable"

# Check for credentials
echo ""
if [ -f "credentials.env" ]; then
    echo "       credentials.env found"
else
    echo "WARNING: credentials.env not found!"
    echo ""
    echo "Please create credentials.env with the following format:"
    echo ""
    echo "  CLIENT_ID=your_connectwise_client_id"
    echo "  CLIENT_SECRET=your_connectwise_client_secret"
    echo "  ZOHO_CLIENT_ID=your_zoho_client_id"
    echo "  ZOHO_CLIENT_SECRET=your_zoho_client_secret"
    echo "  ZOHO_REFRESH_TOKEN=your_zoho_refresh_token"
    echo ""
fi

# Create directories
mkdir -p data logs

echo ""
echo "============================================"
echo " Installation Complete!"
echo "============================================"
echo ""
echo "To launch the Sync Manager:"
echo "  - Double-click: launch_sync.command"
echo "  - Or run: python3 -m src.main --sync"
echo ""
echo "============================================"
echo ""
read -p "Press Enter to close..."

