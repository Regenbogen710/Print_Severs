param(
    [string]$PythonExe = ".venv\Scripts\python.exe",
    [switch]$Check
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

if ($Check) {
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        Write-Host "[WARN] Python executable does not exist yet: $PythonExe"
    }
    if (-not (Test-Path -LiteralPath "app\run_server.py")) {
        throw "app\run_server.py not found"
    }
    Write-Host "[OK] foreground launcher is ready in $Root"
    exit 0
}

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogFile = Join-Path $LogDir "start-server-$Stamp.log"
$LatestLog = Join-Path $LogDir "start-server-latest.log"

if (Test-Path -LiteralPath $LatestLog) {
    Remove-Item -LiteralPath $LatestLog -Force
}
New-Item -ItemType File -Path $LatestLog -Force | Out-Null

$env:PYTHONUNBUFFERED = "1"
$env:PRINT_SERVER_PARENT_PID = "$PID"

function Write-LogLine {
    param([string]$Line)

    $Line | Tee-Object -FilePath $LogFile -Append | Out-Host
    Add-Content -LiteralPath $LatestLog -Value $Line -Encoding UTF8
}

Write-LogLine "[INFO] PrintSevers foreground launcher started"
Write-LogLine "[INFO] Working directory: $Root"
Write-LogLine "[INFO] Log file: $LogFile"
Write-LogLine "[INFO] Latest log: $LatestLog"
Write-LogLine "[INFO] Closing this terminal or pressing Ctrl+C stops the service"
Write-LogLine ""

try {
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $PythonExe -u -m app.run_server 2>&1 |
            ForEach-Object {
                $line = $_.ToString()
                Write-LogLine $line
            }
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }

    $ExitCode = $LASTEXITCODE
    if ($null -eq $ExitCode) {
        $ExitCode = 0
    }
    Write-LogLine ""
    Write-LogLine "[INFO] Python server exited with code $ExitCode"
}
finally {
    Write-LogLine ""
    Write-LogLine "[INFO] PrintSevers foreground launcher stopped"
}

exit $ExitCode
