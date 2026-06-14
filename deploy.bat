@echo off
setlocal
cd /d "%~dp0"

if /I "%~1"=="--check" (
    if not exist "requirements.txt" (
        echo [ERROR] requirements.txt not found.
        exit /b 1
    )
    if not exist "config.ini" (
        echo [ERROR] config.ini not found.
        exit /b 1
    )
    if not exist "scripts\deploy.ps1" (
        echo [ERROR] scripts\deploy.ps1 not found.
        exit /b 1
    )
    echo [OK] deploy.bat is ready in %CD%
    exit /b 0
)

echo.
echo =====================================
echo   PrintSevers one-click deploy
echo =====================================
echo Project: %CD%
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\deploy.ps1" -NoPause
if errorlevel 1 goto fail

echo.
echo [INFO] Deployment completed.
pause
exit /b 0

:fail
echo.
echo [ERROR] Deployment failed. Please check the message above.
pause
exit /b 1
