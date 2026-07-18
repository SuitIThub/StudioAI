# Start StudioAI Worker (Windows). Prefer scripts/start-worker.sh on the Linux home server.
#
# Usage:
#   .\scripts\start-worker.ps1
#   .\scripts\start-worker.ps1 -SkipPull -SkipInstall

param(
    [switch]$SkipPull,
    [switch]$SkipInstall,
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

if (-not $SkipPull) {
    Write-Step "git pull"
    if (Test-Path (Join-Path $Root ".git")) {
        git pull --ff-only
        if ($LASTEXITCODE -ne 0) {
            Write-Host "git pull --ff-only failed (local changes?). Continuing with current tree." -ForegroundColor Yellow
        }
    } else {
        Write-Host "Not a git checkout — skip pull." -ForegroundColor Yellow
    }
}

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Step "create .venv"
    py -3 -m venv .venv
    if (-not (Test-Path $py)) { python -m venv .venv }
    if (-not (Test-Path $py)) { throw "Could not create .venv" }
}

if (-not $SkipInstall) {
    Write-Step "pip install -e ."
    & $py -m pip install -q --upgrade pip
    & $py -m pip install -e .
}

$configPath = if ($Config) { $Config } else { Join-Path $Root "deploy\config.home-server.yaml" }
if (-not (Test-Path $configPath)) {
    throw "Worker config not found: $configPath"
}

$env:STUDIO_AI_CONFIG = (Resolve-Path $configPath).Path
$env:PYTHONPATH = "$Root\core;$Root\adapters\worker"

Write-Step "start Worker"
Write-Host "Config: $env:STUDIO_AI_CONFIG"
Write-Host "Stop:   Ctrl+C"
Write-Host ""

$cmd = Join-Path $Root ".venv\Scripts\studio-ai-worker.exe"
if (Test-Path $cmd) {
    & $cmd
} else {
    & $py -m studio_ai_worker
}
exit $LASTEXITCODE
