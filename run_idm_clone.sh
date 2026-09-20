#!/bin/bash
# Launcher untuk IDM Clone -- otomatis deteksi lokasi folder ini sendiri,
# jadi shortcut tetap jalan walau project dipindah ke folder lain.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
python3 gui_main.py
