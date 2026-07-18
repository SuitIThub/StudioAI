# Start StudioAI Core on the main PC (JoyCaption + Bridge + FTS).
#
# Usage (from anywhere):
#   .\scripts\start-core.ps1
#   .\scripts\start-core.ps1 -SkipPull
#   .\scripts\start-core.ps1 -SkipInstall
#
# Does: optional git pull → ensure venv → pip install -e ".[vision]" → studio-ai-core

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
    if (-not (Test-Path $py)) {
        python -m venv .venv
    }
    if (-not (Test-Path $py)) {
        throw "Could not create .venv — install Python 3.10+ first."
    }
}

if (-not $SkipInstall) {
    Write-Step "pip install -e `".[vision]`" (editable Core + JoyCaption deps)"
    & $py -m pip install -q --upgrade pip
    & $py -m pip install -e ".[vision]"
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed. For CUDA torch on RTX 50xx run: .\scripts\setup_vision.ps1"
    }
}

$configPath = if ($Config) { $Config } else { Join-Path $Root "deploy\config.main-pc.yaml" }
if (-not (Test-Path $configPath)) {
    throw "Core config not found: $configPath"
}

$env:STUDIO_AI_CORE_CONFIG = (Resolve-Path $configPath).Path
$env:PYTHONPATH = "$Root\core;$Root\adapters\worker"

Write-Step "start Core"
Write-Host "Config: $env:STUDIO_AI_CORE_CONFIG"
Write-Host "Ports:  7200-7299 (auto) · expects Worker + Bridge"
Write-Host "Stop:   Ctrl+C"
Write-Host ""

$coreCmd = Join-Path $Root ".venv\Scripts\studio-ai-core.exe"
if (Test-Path $coreCmd) {
    & $coreCmd
} else {
    & $py -m studio_ai_core
}
exit $LASTEXITCODE
