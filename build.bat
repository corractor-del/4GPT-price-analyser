@echo off
REM Build Windows one-file EXE (no console)
REM Requires: pip install -r requirements.txt && pip install pyinstaller
pyinstaller build.spec
echo.
echo Done. See .\dist\AvitoPriceAnalyzer\ or .\dist\AvitoPriceAnalyzer.exe
pause
