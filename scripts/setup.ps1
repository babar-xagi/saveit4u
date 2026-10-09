param([string]$ExtensionId, [switch]$InstallFFmpeg)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectDirectory
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create a virtual environment. Install Python 3.11+ first.' }
    }
    & '.\.venv\Scripts\python.exe' -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip setup failed.' }
    & '.\.venv\Scripts\python.exe' -m pip install --upgrade -e .
    if ($LASTEXITCODE -ne 0) { throw 'Companion dependencies could not be installed.' }
    if ($InstallFFmpeg) {
        & '.\.venv\Scripts\python.exe' scripts/install_ffmpeg.py
        if ($LASTEXITCODE -ne 0) { throw 'Portable FFmpeg installation failed.' }
    }
    foreach ($dependency in @('ffmpeg', 'ffprobe')) {
        if (-not (Get-Command $dependency -ErrorAction SilentlyContinue) -and -not (Test-Path -LiteralPath ".tools\ffmpeg\bin\$dependency.exe")) {
            Write-Warning "$dependency is missing from PATH. Install FFmpeg and reopen your browser."
        }
    }
    if (-not (Get-Command deno -ErrorAction SilentlyContinue) -and -not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Warning 'Install Node 22+ or Deno 2.3+ and reopen your browser.'
    }
    if ($ExtensionId) {
        & '.\.venv\Scripts\python.exe' scripts/register_host.py --extension-id $ExtensionId
        if ($LASTEXITCODE -ne 0) { throw 'Native host registration failed.' }
    }
    Write-Host 'Companion installed. Load extension/ in Chrome or Edge and follow the Setup tab.'
} finally { Pop-Location }
