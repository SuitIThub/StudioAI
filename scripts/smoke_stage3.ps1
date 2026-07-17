# Stage-3 smoke (offline batch + FTS). Usage:
#   .\scripts\smoke_stage3.ps1
#   .\scripts\smoke_stage3.ps1 -Merge   # needs Heimserver worker + Qwen
param(
    [int]$Generate = 120,
    [switch]$Merge
)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = "$Root\core;$Root\adapters\worker"
$py = Join-Path $Root ".venv\Scripts\python.exe"
$argsList = @("scripts\smoke_stage3.py", "--generate", "$Generate")
if (-not $Merge) { $argsList += "--no-merge" }
& $py @argsList
exit $LASTEXITCODE
