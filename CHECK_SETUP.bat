@echo off
REM ===========================================================================
REM  IS THE GPU ACCOUNT SET UP?  (run once after install, or after changing
REM  anything in config.py)
REM
REM  Checks the RunPod key, the storage volume and the settings. Rents nothing
REM  and costs nothing. Also tells you if a GPU is running that you forgot.
REM ===========================================================================
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo.
    echo Setup has not been run yet. Please run install.bat first.
    echo.
    pause
    exit /b 1
)

venv\Scripts\python -m subtitles.pod
echo.
pause
