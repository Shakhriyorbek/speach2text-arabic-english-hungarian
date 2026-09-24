@echo off
REM ===========================================================================
REM  GET THE LATEST VERSION
REM
REM  Downloads the current code and copies it over this folder. Your settings,
REM  your models and your Python environment are NOT touched:
REM
REM    venv\             not in the download, so it cannot be replaced
REM    models\           the same - your 3 GB stays put
REM    config_local.py   your microphone number and anything else you set
REM
REM  Only config.py and the program files are replaced, which is the point.
REM  Needs internet. Takes under a minute. Safe to run any time.
REM ===========================================================================
setlocal
cd /d "%~dp0"

set "REPO=Shakhriyorbek/speach2text-arabic-english-hungarian"
set "ZIP=%TEMP%\khutbah-update.zip"
set "OUT=%TEMP%\khutbah-update"

echo.
echo === Downloading the latest version ===
if exist "%ZIP%" del /q "%ZIP%"
if exist "%OUT%" rmdir /s /q "%OUT%"
curl -fsSL -o "%ZIP%" "https://github.com/%REPO%/archive/refs/heads/main.zip"
if errorlevel 1 (
    echo.
    echo Could not download it. Is this computer online?
    echo.
    pause
    exit /b 1
)

echo === Unpacking ===
powershell -NoProfile -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%OUT%' -Force"
if errorlevel 1 goto :fail

REM The archive contains one top-level folder; copy what is INSIDE it, so we
REM do not end up with the project nested one level deeper every time.
echo === Copying the files in ===
robocopy "%OUT%\speach2text-arabic-english-hungarian-main" "%CD%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :fail

del /q "%ZIP%" >nul 2>&1
rmdir /s /q "%OUT%" >nul 2>&1

echo.
echo ===========================================================================
echo  UPDATED.
echo.
echo  Your microphone setting, models and Python environment were left alone.
echo  If a pod is running, close the subtitle window and start it again so the
echo  GPU picks up the new server too.
echo ===========================================================================
echo.
pause
exit /b 0

:fail
echo.
echo Update FAILED. Nothing was changed. You can still download the ZIP by
echo hand from https://github.com/%REPO%
echo.
pause
exit /b 1
