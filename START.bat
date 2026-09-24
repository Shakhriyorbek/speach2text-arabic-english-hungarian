@echo off
REM ===========================================================================
REM  KHUTBAH SUBTITLES  --  start everything.
REM
REM  This is the only thing that needs double-clicking on a Friday. It rents a
REM  GPU, waits for it, shows the subtitles, and gives the GPU back when the
REM  window is closed. Nothing has to be typed or copied.
REM
REM  If the GPU cannot be rented it offers to carry on using this laptop on its
REM  own -- the subtitles still work, just less accurately. Never debug in front
REM  of the congregation: take that option and look at it afterwards.
REM ===========================================================================
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo.
    echo Setup has not been run yet. Please run install.bat first.
    echo.
    pause
    exit /b 1
)

venv\Scripts\python -m subtitles.launcher
if errorlevel 1 pause
