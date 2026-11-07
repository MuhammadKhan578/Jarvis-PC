@echo off
cd /d "%~dp0"
echo Installing Jarvis dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Install failed. Make sure Python 3.10+ is installed and on PATH.
    pause
    exit /b 1
)
echo.
echo Done. Double-click Jarvis.bat to start.
pause
