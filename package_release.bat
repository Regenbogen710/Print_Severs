@echo off
setlocal
cd /d "%~dp0"

set "PAUSE_AFTER=1"
for %%A in (%*) do (
    if /I "%%~A"=="-NoPause" set "PAUSE_AFTER=0"
)

set "SCRIPT=%~dp0scripts\package_release.ps1"
if not exist "%SCRIPT%" (
    echo [ERROR] %SCRIPT% not found.
    if "%PAUSE_AFTER%"=="1" pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
if errorlevel 1 (
    echo.
    echo [ERROR] Package failed.
    if "%PAUSE_AFTER%"=="1" pause
    exit /b 1
)

echo.
echo [INFO] Package completed.
if "%PAUSE_AFTER%"=="1" pause
