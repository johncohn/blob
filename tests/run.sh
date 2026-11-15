#!/bin/bash
# Host-side checks (no hardware needed). Run from anywhere: tests/run.sh
set -e
cd "$(dirname "$0")"
c++ -std=c++17 -I firmware/mock -include firmware/mock/Arduino.h firmware/test.cpp -o /tmp/blob_fwtest && /tmp/blob_fwtest
PY=../benmidi_v7/venv/bin/python; [ -x "$PY" ] || PY=python3
"$PY" test_monitor.py
arduino-cli compile -b adafruit:samd:adafruit_feather_m4_can ../benmidi_v7 2>&1 | grep -E "^Sketch uses|error" 
