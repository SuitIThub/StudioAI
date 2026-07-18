# Stage-3 smoke (offline batch + FTS). Usage:
#   .\scripts\smoke_stage3.ps1                  # generate + batch --no-merge + FTS
#   .\scripts\smoke_stage3.ps1 -SkipBatch       # FTS only (index already filled)
#   .\scripts\smoke_stage3.ps1 -Merge           # re-batch with Qwen (slow; can timeout)
param(
    [int]$Generate = 120,
    [switch]$Merge,
    [switch]$SkipBatch
)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = "$Root\core;$Root\adapters\worker"
$py = Join-Path $Root ".venv\Scripts\python.exe"
if ($SkipBatch) { $Generate = 0 }
$argsList = @("scripts\smoke_stage3.py", "--generate", "$Generate")
if (-not $Merge) { $argsList += "--no-merge" }
if ($SkipBatch) { $argsList += "--skip-batch" }
& $py @argsList
exit $LASTEXITCODE
