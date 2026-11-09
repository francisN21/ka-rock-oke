@echo off
REM MicBridge on its own. Extra options: --lan  --no-browser  --no-autostart
cd /d "%~dp0"
call ..\.venv\Scripts\activate.bat
python -m micbridge %*
