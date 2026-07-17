@echo off
REM ===========================================================================
REM  ONE-TIME SETUP  (needs internet — run once, then never again)
REM  Downloads ~700 MB of models. This can take a while on a slow connection.
REM ===========================================================================
setlocal
cd /d "%~dp0"

echo.
echo === Creating Python virtual environment ===
py -3 -m venv venv
if errorlevel 1 (
    echo.
    echo ERROR: Could not create the venv. Is Python 3 installed and on PATH?
    echo Download it from https://www.python.org/downloads/ (tick "Add to PATH").
    pause
    exit /b 1
)

echo.
echo === Installing runtime dependencies ===
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo === Installing conversion tools (temporary — removed at the end) ===
REM torch must come from the CPU-only index; transformers from normal PyPI.
REM They are installed separately so the CPU index isn't applied to transformers.
venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto :fail
venv\Scripts\pip install transformers
if errorlevel 1 goto :fail

echo.
echo === Downloading + building models (the long part) ===
venv\Scripts\python -m subtitles.download_models
if errorlevel 1 goto :fail

echo.
echo === Removing the temporary conversion tools to save disk space ===
venv\Scripts\pip uninstall -y torch transformers

echo.
echo ===========================================================================
echo  DONE. Setup finished successfully.
echo  From now on just double-click run.bat to start the subtitles.
echo ===========================================================================
pause
exit /b 0

:fail
echo.
echo ---------------------------------------------------------------------------
echo  SETUP FAILED. Scroll up to see the first red/error line.
echo  Common causes: no internet, or Python not installed.
echo ---------------------------------------------------------------------------
pause
exit /b 1
