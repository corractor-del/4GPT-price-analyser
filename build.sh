#!/usr/bin/env bash
set -euo pipefail
# Build one-file GUI exe/app using PyInstaller
# Requires: pip install -r requirements.txt && pip install pyinstaller
pyinstaller build.spec
echo "Done. See ./dist/AvitoPriceAnalyzer or ./dist/AvitoPriceAnalyzer.exe"
