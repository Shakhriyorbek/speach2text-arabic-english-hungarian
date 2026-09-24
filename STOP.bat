@echo off
REM ===========================================================================
REM  GIVE THE GPU BACK  --  only needed if something went wrong.
REM
REM  START.bat already releases the GPU when you close the subtitle window, and
REM  the rented machine stops itself after a few hours no matter what. This is
REM  for the in-between case: the laptop was shut, or the program was killed,
REM  and you want the billing to stop NOW rather than in a few hours.
REM
REM  Safe to run at any time. If nothing is rented, it says so and does nothing.
REM ===========================================================================
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo.
    echo Setup has not been run yet. Please run install.bat first.
    echo.
    pause
    exit /b 1
)

venv\Scripts\python -m subtitles.stop_pod
echo.
pause
