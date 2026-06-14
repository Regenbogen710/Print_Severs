param(
    [string]$OutputDir = "dist",
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$VersionLine = Select-String -LiteralPath "pyproject.toml" -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
if ($null -eq $VersionLine) {
    throw "Cannot read project version from pyproject.toml"
}

$Version = $VersionLine.Matches[0].Groups[1].Value
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$PackageName = "PrintSevers-$Version-windows-$Stamp"
$StageRoot = Join-Path ([System.IO.Path]::GetTempPath()) $PackageName
$StageProject = Join-Path $StageRoot "PrintSevers"

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}
$OutputRoot = Resolve-Path $OutputDir
$OutputPath = Join-Path $OutputRoot "$PackageName.zip"

if (Test-Path $StageRoot) {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $StageProject | Out-Null

$Items = @(
    ".gitattributes",
    ".gitignore",
    "config.ini",
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "deploy.bat",
    "start_server.bat",
    "package_release.bat",
    "app",
    "scripts",
    "tests"
)

foreach ($Item in $Items) {
    if (-not (Test-Path -LiteralPath $Item)) {
        continue
    }
    Copy-Item -LiteralPath $Item -Destination $StageProject -Recurse -Force
}

$ExcludedNames = @(
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "data",
    "dist",
    ".git"
)

foreach ($Name in $ExcludedNames) {
    Get-ChildItem -LiteralPath $StageProject -Recurse -Force -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq $Name } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
}

Get-ChildItem -LiteralPath $StageProject -Recurse -Force -File -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -eq ".env" -or
        $_.Extension -in @(".pyc", ".pyo") -or
        $_.Name -like "*.sqlite3" -or
        $_.Name -like "*.sqlite3-shm" -or
        $_.Name -like "*.sqlite3-wal" -or
        $_.Name -like "*.log"
    } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

$ManifestPath = Join-Path $StageProject "PACKAGE_MANIFEST.txt"
$Manifest = @(
    "PrintSevers package",
    "Version: $Version",
    "BuiltAt: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "",
    "Deploy: double-click deploy.bat",
    "Start: double-click start_server.bat",
    "Configure: edit config.ini before first start",
    "Excluded: .git, data, dist, virtualenvs, caches, logs"
)
$Manifest | Set-Content -LiteralPath $ManifestPath -Encoding UTF8

if (Test-Path -LiteralPath $OutputPath) {
    Remove-Item -LiteralPath $OutputPath -Force
}

Compress-Archive -LiteralPath $StageProject -DestinationPath $OutputPath -CompressionLevel Optimal
Remove-Item -LiteralPath $StageRoot -Recurse -Force

$File = Get-Item -LiteralPath $OutputPath
Write-Host "[OK] Package created: $($File.FullName)"
Write-Host "[OK] Size: $([Math]::Round($File.Length / 1MB, 2)) MB"

if (-not $NoPause) {
    Write-Host "Press any key to exit..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
