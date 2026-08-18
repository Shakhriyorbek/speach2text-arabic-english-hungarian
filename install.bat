@echo off
REM ===========================================================================
REM  ONE-TIME SETUP  (needs internet — run once, then never again)
REM  Downloads several GB of models. This can take a while on a slow connection.
REM    ~700 MB  Whisper + the English->Hungarian model
REM    ~2.4 GB  NLLB, only when config.py has TRANSLATION_PATH = "direct"
REM             (the default — it translates Arabic straight to Hungarian)
REM  Set TRANSLATION_PATH = "pivot" before running to skip the large download.
REM ===========================================================================
setlocal
cd /d "%~dp0"

echo.
echo === Looking for a supported Python (3.10 - 3.13) ===
REM Pick the newest SUPPORTED version explicitly rather than "py -3", which
REM would silently grab Python 3.14+. webrtcvad-wheels (the voice-activity
REM detector) publishes no wheel for 3.14 yet, and building it from source
REM needs the MSVC build tools — so "py -3" fails confusingly on a new laptop.
set "PYEXE="
if not defined PYEXE (py -3.13 --version >nul 2>&1 && set "PYEXE=py -3.13")
if not defined PYEXE (py -3.12 --version >nul 2>&1 && set "PYEXE=py -3.12")
if not defined PYEXE (py -3.11 --version >nul 2>&1 && set "PYEXE=py -3.11")
if not defined PYEXE (py -3.10 --version >nul 2>&1 && set "PYEXE=py -3.10")

if not defined PYEXE (
    echo.
    echo ERROR: No supported Python found. This project needs Python 3.10-3.13.
    echo.
    echo   Python 3.14 or newer does NOT work yet: the webrtcvad-wheels package
    echo   ^(the voice-activity detector^) has no wheel for it.
    echo.
    echo   Install Python 3.13 from https://www.python.org/downloads/
    echo   and tick "Add Python to PATH" during setup, then run this again.
    pause
    exit /b 1
)
echo Using %PYEXE%

echo.
echo === Creating Python virtual environment ===
%PYEXE% -m venv venv
if errorlevel 1 (
    echo.
    echo ERROR: Could not create the venv with %PYEXE%.
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
