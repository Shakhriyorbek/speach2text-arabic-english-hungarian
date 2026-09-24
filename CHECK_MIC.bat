@echo off
REM ===========================================================================
REM  IS THE MICROPHONE WORKING?
REM
REM  Run this when the subtitle screen stays blank. It lists the inputs this
REM  computer can see, then watches the one in config.py and shows a live level
REM  bar while you speak.
REM
REM  The subtitle app can only ever say "no speech", which looks the same for a
REM  muted mic, a wrong device number, a dead cable, and a condenser microphone
REM  with no phantom power. This tells them apart.
REM ===========================================================================
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo.
    echo Setup has not been run yet. Please run install.bat first.
    echo.
    pause
    exit /b 1
)

venv\Scripts\python -m subtitles.miccheck %*
echo.
pause
