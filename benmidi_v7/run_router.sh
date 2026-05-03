#!/bin/bash
cd "$(dirname "$0")"

# Create venv and install dependencies on first run
if [ ! -d "venv" ]; then
    echo "First run: creating virtual environment..."
    python3 -m venv venv
    echo "Installing python-rtmidi..."
    venv/bin/pip install python-rtmidi
    echo "Ready."
    echo ""
fi

venv/bin/python midi_led_router.py
