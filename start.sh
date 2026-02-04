#!/bin/bash
# ============================================
# CWtoSDP - One-Click Launcher (Linux)
# ============================================
# This script:
#   1. Creates venv if it doesn't exist
#   2. Activates the virtual environment
#   3. Installs dependencies if needed
#   4. Launches the Sync Manager GUI
# ============================================

# Get the directory where this script is located
cd "$(dirname "$0")"

echo ""
echo "  ╔═══════════════════════════════════════════╗"
echo "  ║         CWtoSDP - Sync Manager            ║"
echo "  ╚═══════════════════════════════════════════╝"
echo ""

# ============================================
# Step 1: Check Python
# ============================================
if ! command -v python3 &> /dev/null; then
    echo "  [ERROR] Python 3 is not installed"
    echo ""
    echo "  Install with:"
    echo "    Ubuntu/Debian: sudo apt install python3 python3-venv python3-tk"
    echo "    Fedora:        sudo dnf install python3 python3-tkinter"
    echo "    Arch:          sudo pacman -S python python-tk"
    echo ""
    read -p "  Press Enter to exit..."
    exit 1
fi

PYVER=$(python3 --version 2>&1 | cut -d' ' -f2)
echo "  [OK] Python $PYVER found"

# Check Python version is 3.8+
if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
    echo "  [ERROR] Python 3.8 or higher is required"
    read -p "  Press Enter to exit..."
    exit 1
fi

# Check for tkinter
if ! python3 -c "import tkinter" 2>/dev/null; then
    echo "  [ERROR] tkinter is not installed"
    echo ""
    echo "  Install with:"
    echo "    Ubuntu/Debian: sudo apt install python3-tk"
    echo "    Fedora:        sudo dnf install python3-tkinter"
    echo "    Arch:          sudo pacman -S tk"
    echo ""
    read -p "  Press Enter to exit..."
    exit 1
fi

# ============================================
# Step 2: Create venv if needed
# ============================================
if [ ! -f "venv/bin/activate" ]; then
    echo "  [....] Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "  [ERROR] Failed to create virtual environment"
        echo "  Try: sudo apt install python3-venv"
        read -p "  Press Enter to exit..."
        exit 1
    fi
    echo "  [OK] Virtual environment created"
else
    echo "  [OK] Virtual environment exists"
fi

# ============================================
# Step 3: Activate venv
# ============================================
source venv/bin/activate

# ============================================
# Step 4: Install dependencies if needed
# ============================================
if ! python3 -c "import requests; import dotenv; import pandas" 2>/dev/null; then
    echo "  [....] Installing dependencies..."
    pip install --upgrade pip > /dev/null 2>&1
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "  [ERROR] Failed to install dependencies"
        read -p "  Press Enter to exit..."
        exit 1
    fi
    echo "  [OK] Dependencies installed"
else
    echo "  [OK] Dependencies already installed"
fi

# ============================================
# Step 5: Create directories
# ============================================
mkdir -p data logs

# ============================================
# Step 6: Check credentials
# ============================================
if [ ! -f "credentials.env" ]; then
    echo ""
    echo "  [!] credentials.env not found"
    echo "      You can configure credentials in Settings (gear icon)"
    echo ""
fi

# ============================================
# Step 7: Launch GUI
# ============================================
echo ""
echo "  Launching Sync Manager..."
echo ""
python3 -m src.main --sync

# Keep window open if there was an error
if [ $? -ne 0 ]; then
    echo ""
    echo "  [ERROR] An error occurred. See above for details."
    read -p "  Press Enter to exit..."
fi

