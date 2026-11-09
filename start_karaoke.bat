@echo off
REM Starts MicBridge (mic mixer, http://localhost:5556) and PiKaraoke (TV + phones, port 5555).
REM Phones: open http://<this PC's address>:5555/app/
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (echo Run setup_windows.bat first. & pause & exit /b 1)
call .venv\Scripts\activate.bat
start "MicBridge" /min cmd /c "cd /d "%~dp0micbridge" && python -m micbridge"
start "PiKaraoke" pikaraoke
