# Stage-2 smoke (Core on Windows main PC). Usage:
#   .\scripts\smoke_stage2.ps1 -Chat -Persona stheno
#   .\scripts\smoke_stage2.ps1 -Structured
param(
    [string]$Base = "http://127.0.0.1:7860",
    [string]$Persona = "stheno",
    [switch]$Chat,
    [switch]$Structured,
    [switch]$OfflineCheck
)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$argsList = @("scripts\smoke_stage2.py", "--base", $Base, "--persona", $Persona)
if ($Chat) { $argsList += "--chat" }
if ($Structured) { $argsList += "--structured" }
if ($OfflineCheck) { $argsList += "--offline-check" }
& $py @argsList
exit $LASTEXITCODE
