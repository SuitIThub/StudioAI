# Stage 1 acceptance helpers (run on Heimserver after install)
# Usage:
#   .\scripts\smoke_stage1.ps1
#   .\scripts\smoke_stage1.ps1 -Gbnf -Model qwen-technical
#   .\scripts\smoke_stage1.ps1 -Chat -Model stheno-8b

param(
    [string]$Base = "http://127.0.0.1:7850",
    [string]$Token = "",
    [string]$Model = "qwen-technical",
    [switch]$Gbnf,
    [switch]$Chat
)

$pyArgs = @("scripts/smoke_stage1.py", "--base", $Base, "--model", $Model)
if ($Token) { $pyArgs += @("--token", $Token) }
if ($Gbnf) { $pyArgs += "--gbnf" }
if ($Chat) { $pyArgs += "--chat" }

python @pyArgs
