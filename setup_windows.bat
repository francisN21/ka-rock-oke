@echo off
REM Ka-Rock-oke one-time setup for Windows.
REM Uses Python 3.13: newer versions may lack ready-made builds of the audio and
REM math libraries, which then need a C++ compiler to install.
cd /d "%~dp0"

py -3.13 --version >nul 2>nul
if errorlevel 1 (
  echo Installing Python 3.13 alongside your current Python...
  winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements
  py -3.13 --version >nul 2>nul || (echo Python 3.13 didn't install. Install it from python.org, then run this again. & pause & exit /b 1)
)

where ffmpeg >nul 2>nul || (
  echo Installing ffmpeg...
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
)

if not exist .venv (
  echo Creating the Ka-Rock-oke environment...
  py -3.13 -m venv .venv || (echo Couldn't create the environment. & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
echo Installing PiKaraoke (this fork)...
pip install -e . || (echo PiKaraoke install failed. & pause & exit /b 1)
echo Installing MicBridge...
pip install -r micbridge\requirements.txt || (echo MicBridge install failed. & pause & exit /b 1)

echo.
echo Setup finished. Run start_karaoke.bat
echo Note: if ffmpeg was just installed, close this window and open a new one first.
pause
