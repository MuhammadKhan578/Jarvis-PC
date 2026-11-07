@echo off
cd /d "%~dp0"
python jarvis_app.py
if errorlevel 1 pause
