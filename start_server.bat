@echo off
setlocal
cd /d "%~dp0"

if /I "%~1"=="--check" (
    if not exist "requirements.txt" (
        echo [ERROR] requirements.txt not found.
        exit /b 1
    )
    if not exist "app\main.py" (
        echo [ERROR] app\main.py not found.
        exit /b 1
    )
    if not exist "scripts\start_foreground.ps1" (
        echo [ERROR] scripts\start_foreground.ps1 not found.
        exit /b 1
    )
    if not exist "config.ini" (
        echo [ERROR] config.ini not found.
        exit /b 1
    )
    call :find_python
    if errorlevel 1 exit /b 1
    echo [OK] start_server.bat is ready in %CD%
    exit /b 0
)

echo.
echo =====================================
echo   PrintSevers one-click start
echo =====================================
echo Project: %CD%
echo.

call :find_python
if errorlevel 1 goto fail

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creating virtual environment...
    call %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto fail
)

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment was not created correctly.
    goto fail
)

echo [INFO] Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail

if not exist "config.ini" (
    echo [ERROR] config.ini not found. Please restore config.ini before starting.
    goto fail
)

findstr /C:"admin_password = change-this-password" "config.ini" >nul 2>nul
if not errorlevel 1 (
    echo [WARN] Please edit config.ini and change admin_password before public use.
)

echo.
echo [INFO] Starting PrintSevers...
echo [INFO] Open http://127.0.0.1:8000 after the server is ready.
echo [INFO] Keep this window open. Press Ctrl+C or close this window to stop all service processes.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_foreground.ps1" -PythonExe "%CD%\.venv\Scripts\python.exe"
goto end

:find_python
call :try_python py -3
if not errorlevel 1 (
    echo [INFO] Using Python: %PYTHON_CMD%
    exit /b 0
)

call :try_python python
if not errorlevel 1 (
    echo [INFO] Using Python: %PYTHON_CMD%
    exit /b 0
)

echo [ERROR] Python 3.11 or newer was not found. Please install Python and retry.
exit /b 1

:try_python
if "%~2"=="" (
    "%~1" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
) else (
    "%~1" %~2 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
)
if errorlevel 1 exit /b 1
if "%~2"=="" (
    set "PYTHON_CMD=%~1"
) else (
    set "PYTHON_CMD=%~1 %~2"
)
exit /b 0

:fail
echo.
echo [ERROR] Startup failed. Please check the message above.
pause
exit /b 1

:end
echo.
echo [INFO] PrintSevers stopped.
pause
