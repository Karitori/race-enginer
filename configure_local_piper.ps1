param(
    [Parameter(Mandatory = $true)]
    [string]$ModelPath,
    [string]$PiperExe = "piper",
    [string]$OutFile = ".env.piper.local"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ModelPath)) {
    throw "Model not found: $ModelPath"
}

$resolvedModel = (Resolve-Path $ModelPath).Path
$jsonPath = "$resolvedModel.json"

if (-not (Test-Path $jsonPath)) {
    Write-Warning "Model config not found beside model: $jsonPath"
    Write-Warning "Piper may still run, but many models expect the .onnx.json file."
}

$resolvedPiper = $null
try {
    $resolvedPiper = (Get-Command $PiperExe -ErrorAction Stop).Source
} catch {
    Write-Warning "Could not resolve piper executable '$PiperExe' from PATH."
    Write-Warning "If installed in venv, use: uv run python main.py"
}

$lines = @(
    "VOICE_ENABLE_TTS=true",
    "VOICE_TTS_BACKEND=piper",
    "VOICE_PIPER_EXE=$PiperExe",
    "VOICE_PIPER_MODEL_PATH=$resolvedModel",
    "VOICE_PIPER_EXTRA_ARGS=--length_scale 0.95 --noise_scale 0.667 --noise_w 0.8"
)

$lines | Set-Content -Path $OutFile -Encoding UTF8

Write-Host ""
Write-Host "Local Piper configuration generated:"
Write-Host "  $OutFile"
Write-Host ""
if ($resolvedPiper) {
    Write-Host "Resolved piper executable:"
    Write-Host "  $resolvedPiper"
}
Write-Host "Resolved model:"
Write-Host "  $resolvedModel"
Write-Host ""
Write-Host "Copy lines from $OutFile into your .env, then restart the app."
