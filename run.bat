@echo off
cd /d "%~dp0"
REM pythonw = same Python, but with no visible console window,
REM so this behaves like a real desktop app.
start "" pythonw main.py
