# One-time setup for reel-watcher on Windows.
# Run from the repo folder:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Optional: -ModelSize small|large  (default: picked from your RAM)
param([string]$ModelSize = "")

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Ensure-Tool($cmd, $wingetId, $name) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        Write-Host "[ok] $name found" -ForegroundColor Green
        return
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is not available. Install '$name' manually, then run this script again."
    }
    Write-Host "[..] installing $name with winget" -ForegroundColor Yellow
    winget install --id $wingetId -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "$name was installed but '$cmd' is not on PATH yet. Close and reopen PowerShell, then run this script again."
    }
}

Ensure-Tool "uv" "astral-sh.uv" "uv"
Ensure-Tool "ffmpeg" "Gyan.FFmpeg" "FFmpeg"
Ensure-Tool "ollama" "Ollama.Ollama" "Ollama"

Write-Host "[..] installing Python packages (uv sync)" -ForegroundColor Yellow
uv sync
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

Write-Host "[..] running tests" -ForegroundColor Yellow
uv run pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "[!!] some tests failed; see output above" -ForegroundColor Red }

# Make sure the Ollama server is up (the desktop app normally starts it).
try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 | Out-Null
} catch {
    Write-Host "[..] starting Ollama" -ForegroundColor Yellow
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

if (-not $ModelSize) {
    $ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    $ModelSize = if ($ramGB -lt 32) { "small" } else { "large" }
    Write-Host "[ok] $ramGB GB RAM -> model size '$ModelSize'" -ForegroundColor Green
}
$model = if ($ModelSize -eq "large") { "qwen3-vl:30b" } else { "qwen2.5vl:7b" }
if ($env:REEL_WATCHER_VLM) { $model = $env:REEL_WATCHER_VLM }

Write-Host "[..] downloading vision model $model (one time, several GB)" -ForegroundColor Yellow
ollama pull $model
if ($LASTEXITCODE -ne 0) { throw "ollama pull $model failed" }

Write-Host ""
Write-Host "Setup done. Close and reopen PowerShell, cd back into this folder, then try:" -ForegroundColor Green
Write-Host "  uv run reel-watcher study --local C:\path\to\clip.mp4 --out-root .\out"
