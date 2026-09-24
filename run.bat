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

REM The GPU server's address changes every time a new pod is created, so it
REM lives in a one-line text file the operator can edit without touching any
REM code. Read it into the environment for this process only; config.py picks
REM it up from there. No file, or an empty one, means the values in config.py
REM are used as they are.
if exist "pod_url.txt" (
    for /f "usebackq delims=" %%u in ("pod_url.txt") do set "WHISPER_SERVER_URL=%%u"
)

REM This script is the LAPTOP-ONLY path: no GPU, no internet, no cost, and no
REM token. config.py defaults to using the GPU because that is the normal way
REM to run; START.bat is that. Saying so here means run.bat cannot fail asking
REM for a secret that only START.bat creates.
set "KHUTBAH_LOCAL_ONLY=1"

venv\Scripts\python app.py
if errorlevel 1 pause
