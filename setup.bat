@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
python bootstrap_demo.py
echo.
echo Cai dat hoan tat. Chay run.bat de mo ung dung.
pause

