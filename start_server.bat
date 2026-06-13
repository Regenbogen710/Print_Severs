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
    if not exist "config.example.ini" (
        echo [ERROR] config.example.ini not found.
        exit /b 1
    )
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
    %PYTHON% -m venv .venv
    if errorlevel 1 goto fail
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto fail

echo [INFO] Installing dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto fail

if not exist "config.ini" (
    if not exist ".env" (
        echo [INFO] Creating config.ini from config.example.ini...
        copy "config.example.ini" "config.ini" >nul
        if errorlevel 1 goto fail
    )
)

if exist ".env" (
    echo [INFO] Found legacy .env. config.ini takes priority when it exists.
)

if exist "config.ini" (
    findstr /C:"admin_password = change-this-password" "config.ini" >nul 2>nul
    if not errorlevel 1 (
        echo [WARN] Please edit config.ini and change admin_password before public use.
    )
) else (
    findstr /C:"PRINT_SERVER_ADMIN_PASSWORD=change-this-password" ".env" >nul 2>nul
    if not errorlevel 1 (
        echo [WARN] Please edit .env and change PRINT_SERVER_ADMIN_PASSWORD before public use.
    )
)

echo.
echo [INFO] Starting PrintSevers...
echo [INFO] Open http://127.0.0.1:8000 after the server is ready.
echo [INFO] Keep this window open. Press Ctrl+C or close this window to stop all service processes.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_foreground.ps1" -PythonExe "%CD%\.venv\Scripts\python.exe"
goto end

:find_python
where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON=py -3"
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON=python"
    exit /b 0
)

echo [ERROR] Python was not found. Please install Python 3.11 or newer.
exit /b 1

:fail
echo.
echo [ERROR] Startup failed. Please check the message above.
pause
exit /b 1

:end
echo.
echo [INFO] PrintSevers stopped.
pause
