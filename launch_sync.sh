#!/bin/bash
# ============================================
# CWtoSDP Sync Manager Launcher - Linux
# ============================================

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "============================================"
echo " CWtoSDP Sync Manager"
echo "============================================"
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    echo "Please install Python 3.8+:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-tk"
    echo "  Fedora: sudo dnf install python3 python3-tkinter"
    echo "  Arch: sudo pacman -S python tk"
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

# Check for virtual environment
if [ -f "venv/bin/activate" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
fi

# Check if tkinter is available
python3 -c "import tkinter" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "ERROR: tkinter is not installed."
    echo "Install it with:"
    echo "  Ubuntu/Debian: sudo apt install python3-tk"
    echo "  Fedora: sudo dnf install python3-tkinter"
    echo "  Arch: sudo pacman -S tk"
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

# Launch the Sync Manager GUI
echo "Launching Sync Manager..."
echo ""
python3 -m src.main --sync

# Keep terminal open if there was an error
if [ $? -ne 0 ]; then
    echo ""
    read -p "An error occurred. Press Enter to close..."
fi

