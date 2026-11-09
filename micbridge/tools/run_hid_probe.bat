@echo off
REM Read-only probe of the mic receiver's HID interfaces. Sends nothing to the device.
REM Everything printed here is also saved to tools\probe_log.txt so Claude can read it.
cd /d "%~dp0\.."
set LOG=%~dp0probe_log.txt
echo Probe started %date% %time% > "%LOG%"
if exist ..\.venv\Scripts\activate.bat (call ..\.venv\Scripts\activate.bat)
where python >> "%LOG%" 2>&1
python --version >> "%LOG%" 2>&1
if errorlevel 1 (
  echo Python was not found. Install Python 3.10+ from python.org and tick "Add python.exe to PATH". >> "%LOG%"
  type "%LOG%"
  pause
  exit /b 1
)
echo.
echo Listening for 15 seconds - press the buttons on the mics and receiver now.
python tools\hid_probe.py --listen 15 >> "%LOG%" 2>&1
echo Exit code %errorlevel% >> "%LOG%"
type "%LOG%"
echo.
echo Done. Tell Claude it finished.
pause
