@echo off
cd /d "%~dp0"
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --windowed --name DeltaXSmartLabelStudio --collect-all customtkinter run.py
echo.
echo Ban dong goi nam tai dist\DeltaXSmartLabelStudio
pause

