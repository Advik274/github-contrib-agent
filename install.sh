#!/usr/bin/env bash
set -e

echo ""
echo " =========================================="
echo "  GitHub Contribution Agent — Setup (Linux/Mac)"
echo " =========================================="
echo ""

# Check Python 3.11+
if ! command -v python3 &>/dev/null; then
    echo " [ERROR] python3 not found. Install Python 3.11+ first."
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo " [OK] Python $PY_VER found"

# Virtual env
if [ ! -d ".venv" ]; then
    echo " [..] Creating virtual environment..."
    python3 -m venv .venv
    echo " [OK] Virtual environment created"
else
    echo " [OK] Virtual environment already exists"
fi

source .venv/bin/activate
echo " [..] Installing dependencies..."
pip install -r requirements.txt --quiet --upgrade
echo " [OK] Dependencies installed"

mkdir -p config logs data

echo ""
echo " =========================================="
echo "  Done! Run:  python main.py"
echo " =========================================="
echo ""
