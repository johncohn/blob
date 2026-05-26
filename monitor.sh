#!/bin/bash
cd "$(dirname "$0")"
source benmidi_v7/venv/bin/activate
python3 blob_monitor.py --in-name "Network blob" --out-name "feather,m4,samd,widi,cme,iac"
