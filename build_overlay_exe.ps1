param(
    [switch]$OneFile,
    [string]$Name = "race-engineer-overlay",
    [string]$Entry = "overlay_main.py",
    [string]$IconPath = "assets\\desktop_app_icon.ico",
    [string]$VersionFile = "assets\\overlay_version_info.txt"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Entry)) {
    throw "Entry script not found: $Entry"
}
if (-not (Test-Path $VersionFile)) {
    throw "Version file not found: $VersionFile"
}

$pyinstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", $Name,
    "--version-file", $VersionFile
)

if (Test-Path $IconPath) {
    $pyinstallerArgs += @("--icon", $IconPath)
    $pyinstallerArgs += @("--add-data", "$IconPath;assets")
} else {
    Write-Warning "Icon file not found ($IconPath). Building without a custom icon."
}

$pyinstallerArgs += @("--add-data", ".env.example;.")
$pyinstallerArgs += @("--add-data", "docs\overlay_app.md;docs")

if ($OneFile) {
    $pyinstallerArgs += "--onefile"
}

$pyinstallerArgs += $Entry

Write-Host "Building overlay executable..."
Write-Host ("uv run pyinstaller " + ($pyinstallerArgs -join " "))

& uv run pyinstaller @pyinstallerArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($OneFile) {
    $outPath = Join-Path "dist" "$Name.exe"
} else {
    $outPath = Join-Path "dist" "$Name\$Name.exe"
}

Write-Host ""
Write-Host "Build complete:"
Write-Host $outPath
