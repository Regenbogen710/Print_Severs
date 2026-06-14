param(
    [switch]$CheckOnly,
    [switch]$NoPause,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$LogPath = Join-Path $LogDir ("deploy-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$LatestLogPath = Join-Path $LogDir "deploy-latest.log"

function Write-DeployLog {
    param(
        [string]$Message,
        [ValidateSet("INFO", "OK", "WARN", "ERROR")]
        [string]$Level = "INFO"
    )

    $line = "[{0}] {1}" -f $Level, $Message
    Write-Host $line
    Add-Content -LiteralPath $LogPath -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $line) -Encoding UTF8
}

function Find-PythonCommand {
    $commands = @(
        @{ Command = "py"; Arguments = @("-3") },
        @{ Command = "python"; Arguments = @() }
    )

    foreach ($item in $commands) {
        $found = Get-Command $item.Command -ErrorAction SilentlyContinue
        if ($null -ne $found) {
            return $item
        }
    }

    throw "Python was not found. Please install Python 3.11 or newer."
}

function Invoke-Python {
    param(
        [hashtable]$PythonCommand,
        [string[]]$Arguments
    )

    & $PythonCommand.Command @($PythonCommand.Arguments + $Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw ("Python command failed: {0}" -f ($Arguments -join " "))
    }
}

function Test-ExecutablePath {
    param([string]$PathText)

    if ([string]::IsNullOrWhiteSpace($PathText)) {
        return $false
    }

    $expanded = [Environment]::ExpandEnvironmentVariables($PathText).Trim('"')
    return Test-Path -LiteralPath $expanded -PathType Leaf
}

function Add-Candidate {
    param(
        [System.Collections.Generic.List[string]]$Candidates,
        [string]$PathText
    )

    if ([string]::IsNullOrWhiteSpace($PathText)) {
        return
    }

    if (-not $Candidates.Contains($PathText)) {
        [void]$Candidates.Add($PathText)
    }
}

function Join-OptionalPath {
    param(
        [string]$Base,
        [string]$Child
    )

    if ([string]::IsNullOrWhiteSpace($Base)) {
        return $null
    }
    return Join-Path $Base $Child
}

function Add-CommandCandidate {
    param(
        [System.Collections.Generic.List[string]]$Candidates,
        [string[]]$Names
    )

    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $command -and (Test-ExecutablePath $command.Source)) {
            Add-Candidate $Candidates $command.Source
        }
    }
}

function Add-RegistryAppPathCandidate {
    param(
        [System.Collections.Generic.List[string]]$Candidates,
        [string]$ExecutableName
    )

    $keys = @(
        "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$ExecutableName",
        "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\$ExecutableName",
        "Registry::HKEY_CURRENT_USER\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$ExecutableName"
    )

    foreach ($key in $keys) {
        if (-not (Test-Path -LiteralPath $key)) {
            continue
        }
        $value = (Get-Item -LiteralPath $key).GetValue("")
        if ($value) {
            Add-Candidate $Candidates ([string]$value)
        }
    }
}

function Resolve-FirstExecutable {
    param(
        [string]$Label,
        [string[]]$CandidatePaths,
        [string[]]$CommandNames,
        [string[]]$RegistryNames
    )

    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($path in $CandidatePaths) {
        Add-Candidate $candidates $path
    }
    Add-CommandCandidate $candidates $CommandNames
    foreach ($name in $RegistryNames) {
        Add-RegistryAppPathCandidate $candidates $name
    }

    foreach ($candidate in $candidates) {
        if (Test-ExecutablePath $candidate) {
            $resolved = (Resolve-Path -LiteralPath ([Environment]::ExpandEnvironmentVariables($candidate).Trim('"'))).Path
            Write-DeployLog ("{0} found: {1}" -f $Label, $resolved) "OK"
            return $resolved
        }
    }

    Write-DeployLog ("{0} was not found. Existing config value will be kept." -f $Label) "WARN"
    return $null
}

function Find-SumatraPdf {
    $candidatePaths = @(
        (Join-OptionalPath $env:ProgramFiles "SumatraPDF\SumatraPDF.exe"),
        (Join-OptionalPath ${env:ProgramFiles(x86)} "SumatraPDF\SumatraPDF.exe"),
        (Join-OptionalPath $env:LOCALAPPDATA "SumatraPDF\SumatraPDF.exe"),
        (Join-OptionalPath $env:USERPROFILE "scoop\apps\sumatrapdf\current\SumatraPDF.exe"),
        "C:\ProgramData\chocolatey\bin\SumatraPDF.exe",
        (Join-Path $Root "tools\SumatraPDF.exe")
    )
    Resolve-FirstExecutable "SumatraPDF" $candidatePaths @("SumatraPDF.exe", "sumatrapdf.exe") @("SumatraPDF.exe")
}

function Find-LibreOffice {
    $candidatePaths = @(
        (Join-OptionalPath $env:ProgramFiles "LibreOffice\program\soffice.exe"),
        (Join-OptionalPath ${env:ProgramFiles(x86)} "LibreOffice\program\soffice.exe"),
        (Join-OptionalPath $env:USERPROFILE "scoop\apps\libreoffice\current\program\soffice.exe"),
        "C:\ProgramData\chocolatey\bin\soffice.exe"
    )
    Resolve-FirstExecutable "LibreOffice" $candidatePaths @("soffice.exe") @("soffice.exe", "libreoffice.exe")
}

function Set-IniValue {
    param(
        [string]$Path,
        [string]$Section,
        [string]$Key,
        [string]$Value
    )

    $encoding = [System.Text.UTF8Encoding]::new($false)
    $lines = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $Path) {
        foreach ($line in [System.IO.File]::ReadAllLines($Path, $encoding)) {
            [void]$lines.Add($line)
        }
    }

    $sectionPattern = "^\s*\[{0}\]\s*$" -f [regex]::Escape($Section)
    $nextSectionPattern = "^\s*\[.+\]\s*$"
    $keyPattern = "^\s*{0}\s*=" -f [regex]::Escape($Key)
    $sectionIndex = -1

    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match $sectionPattern) {
            $sectionIndex = $i
            break
        }
    }

    if ($sectionIndex -lt 0) {
        if ($lines.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($lines[$lines.Count - 1])) {
            [void]$lines.Add("")
        }
        [void]$lines.Add("[$Section]")
        [void]$lines.Add("$Key = $Value")
        [System.IO.File]::WriteAllLines($Path, $lines, $encoding)
        return
    }

    $sectionEnd = $lines.Count
    for ($i = $sectionIndex + 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match $nextSectionPattern) {
            $sectionEnd = $i
            break
        }
    }

    for ($i = $sectionIndex + 1; $i -lt $sectionEnd; $i++) {
        if ($lines[$i] -match $keyPattern) {
            $lines[$i] = "$Key = $Value"
            [System.IO.File]::WriteAllLines($Path, $lines, $encoding)
            return
        }
    }

    $lines.Insert($sectionEnd, "$Key = $Value")
    [System.IO.File]::WriteAllLines($Path, $lines, $encoding)
}

try {
    Write-DeployLog "Starting PrintSevers deployment: $Root"

    foreach ($required in @("requirements.txt", "config.ini", "app\main.py")) {
        if (-not (Test-Path -LiteralPath $required)) {
            throw "Required file missing: $required"
        }
    }

    if ($CheckOnly) {
        Write-DeployLog "Check passed. Dependencies were not installed and config.ini was not changed." "OK"
        exit 0
    }

    if (-not $SkipInstall) {
        $python = Find-PythonCommand
        if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
            Write-DeployLog "Creating virtual environment .venv..."
            Invoke-Python $python @("-m", "venv", ".venv")
        } else {
            Write-DeployLog "Virtual environment .venv already exists. Skipping creation."
        }

        Write-DeployLog "Installing dependencies..."
        & ".venv\Scripts\python.exe" -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) {
            throw "Dependency installation failed"
        }
    } else {
        Write-DeployLog "Dependency installation skipped by argument."
    }

    $sumatraPath = Find-SumatraPdf
    if ($sumatraPath) {
        Set-IniValue "config.ini" "printer" "sumatra_pdf_path" $sumatraPath
        Write-DeployLog "Updated config.ini: sumatra_pdf_path" "OK"
    }

    $libreOfficePath = Find-LibreOffice
    if ($libreOfficePath) {
        Set-IniValue "config.ini" "printer" "libreoffice_path" $libreOfficePath
        Write-DeployLog "Updated config.ini: libreoffice_path" "OK"
    }

    Write-DeployLog "Deployment completed. Log: $LogPath" "OK"
    Write-DeployLog "Next step: run start_server.bat to start the service."
    Copy-Item -LiteralPath $LogPath -Destination $LatestLogPath -Force
} catch {
    Write-DeployLog $_.Exception.Message "ERROR"
    Copy-Item -LiteralPath $LogPath -Destination $LatestLogPath -Force -ErrorAction SilentlyContinue
    exit 1
} finally {
    if (-not $NoPause) {
        Write-Host "Press any key to exit..."
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    }
}
