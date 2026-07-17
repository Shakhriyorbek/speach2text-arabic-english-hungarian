@echo off
REM ===========================================================================
REM  START THE SUBTITLES  (double-click this every Friday)
REM  No internet needed. In the window: F1 = Part 1 (Arabic), F2 = Part 2.
REM ===========================================================================
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo.
    echo Setup has not been run yet. Please run install.bat first.
    echo.
    pause
    exit /b 1
)

venv\Scripts\python app.py
if errorlevel 1 pause
