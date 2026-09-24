@echo off
REM ===========================================================================
REM  IS THE GPU READY?  (run this a few minutes BEFORE the khutbah)
REM  Says in plain English whether the subtitles will run on the GPU or have
REM  quietly fallen back to this laptop. Safe to run any time; changes nothing.
REM ===========================================================================
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo.
    echo Setup has not been run yet. Please run install.bat first.
    echo.
    pause
    exit /b 1
)

REM The pod URL changes every time a new pod is created, so it lives in a
REM one-line text file rather than in config.py. Set it for this process only.
if exist "pod_url.txt" (
    for /f "usebackq delims=" %%u in ("pod_url.txt") do set "WHISPER_SERVER_URL=%%u"
)

venv\Scripts\python -m subtitles.preflight
echo.
pause
