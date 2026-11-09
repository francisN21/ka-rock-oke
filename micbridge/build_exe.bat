@echo off
REM Builds dist\MicBridge.exe (single file). Run ..\setup_windows.bat first.
cd /d "%~dp0"
call ..\.venv\Scripts\activate.bat
pip install pyinstaller
pyinstaller --noconfirm --onefile --name MicBridge ^
  --add-data "micbridge\static;micbridge\static" ^
  --collect-all sounddevice ^
  --hidden-import scipy.signal ^
  micbridge_launcher.py
echo Built dist\MicBridge.exe
pause
