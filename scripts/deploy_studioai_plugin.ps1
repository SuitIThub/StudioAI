# Deploy StudioAI Stage-5a plugin into Honey Select BepInEx
param(
    [string]$GamePlugins = "D:\Honey Select\BepInEx\plugins\StudioAI"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Adapters = Join-Path $Root "adapters"

Push-Location $Adapters
dotnet build StudioAi.Adapters.sln -c Release
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Pop-Location

New-Item -ItemType Directory -Force -Path $GamePlugins | Out-Null
Copy-Item "$Adapters\plugin\StudioAi.Plugin\bin\Release\StudioAi.Plugin.dll" $GamePlugins -Force
Copy-Item "$Adapters\plugin\StudioAi.Plugin\bin\Release\StudioAi.Contracts.dll" $GamePlugins -Force
Copy-Item "$Adapters\plugin\StudioAi.Plugin\bin\Release\Newtonsoft.Json.dll" $GamePlugins -Force
Write-Host "Deployed to $GamePlugins"
Write-Host "Also rebuild+deploy HS2Sandbox.PoseBrowser from HS2-Sandbox (AI filter hooks)."
