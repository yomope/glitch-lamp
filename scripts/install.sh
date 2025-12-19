#!/bin/bash
set -e

echo "Installing dependencies..."

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Python3 could not be found. Please install it."
    exit 1
fi

echo "Creating virtual environment..."
python3 -3.10 -m venv venv

echo "Activating virtual environment..."
source venv/bin/activate

echo "Upgrading pip..."
pip install --upgrade pip

echo "Installing required packages..."
pip install -r requirements.txt

echo "Checking for FFmpeg..."
if ! command -v ffmpeg &> /dev/null; then
    echo "WARNING: FFmpeg is not installed or not in PATH."
    echo "Some plugins like 'datamosh' and 'recompress' require FFmpeg."
    echo "Please install FFmpeg (e.g., sudo apt install ffmpeg)."
else
    echo "FFmpeg is found."
fi

echo "Installation complete."
