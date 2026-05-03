#!/bin/bash
cd "$(dirname "$0")"

if [ ! -d "venv" ] || ! venv/bin/python -c "import rtmidi; import mido" 2>/dev/null; then
    echo "Setting up virtual environment..."
    rm -rf venv
    python3 -m venv venv
    echo "Installing dependencies..."
    venv/bin/pip install -r requirements.txt --index-url https://pypi.org/simple
    if [ $? -ne 0 ]; then
        echo ""
        echo "ERROR: Install failed. Check your internet connection and try again."
        rm -rf venv
        exit 1
    fi
    echo "Ready."
    echo ""
fi

venv/bin/python midi_session.py "$@"
