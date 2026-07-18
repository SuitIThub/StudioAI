# StudioAI ↔ PoseBrowser (Stage 5a)

Hybrid: **PoseBrowser** exposes thin Host/Search hooks; **StudioAi.Plugin** talks HTTP to Core.

## Layout

| Piece | Location |
|-------|----------|
| AiContracts (DTOs + interfaces) | `adapters/aicontracts/StudioAi.Contracts/` |
| Thin BepInEx plugin | `adapters/plugin/StudioAi.Plugin/` |
| PoseBrowser hooks | `HS2-Sandbox/src/PoseBrowser/` (`PoseBrowserExternalApi`, `PoseBrowserHostService`, `PoseBrowserWindow.AiSearch`) |

## Build

```powershell
cd H:\Dateien\Dokumente\Repos\StudioAI\adapters
dotnet build StudioAi.Adapters.sln -c Release
```

Deploy DLLs to Honey Select:

```powershell
$dst = "D:\Honey Select\BepInEx\plugins\StudioAI"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item "plugin\StudioAi.Plugin\bin\Release\StudioAi.Plugin.dll" $dst -Force
Copy-Item "aicontracts\StudioAi.Contracts\bin\Release\StudioAi.Contracts.dll" $dst -Force
# Newtonsoft.Json if not already present in BepInEx/core or plugins:
# Copy-Item "$env:USERPROFILE\.nuget\packages\newtonsoft.json\13.0.3\lib\net45\Newtonsoft.Json.dll" $dst -Force
```

Rebuild **PoseBrowser** from HS2-Sandbox (contains AI filter + headless apply fallback):

```powershell
cd H:\Dateien\Dokumente\Repos\HS2-Sandbox
dotnet build targets\HS2\PoseBrowser\HS2Sandbox.PoseBrowser.csproj -c Release
# deploy HS2Sandbox.PoseBrowser.dll as you usually do
```

## Config (BepInEx)

`BepInEx/config/com.suitji.studio_ai.cfg`:

- `Core.BaseUrl` = `http://127.0.0.1:7860`
- Hotkey `SearchClipboard` default **F8** — searches Core with clipboard text and filters the Pose Browser grid

## Codegen note

DTOs in `StudioAi.Contracts` match `contracts/openapi.yaml` (`SearchRequest` / hits / health `contract_version`).  
Full NSwag pipeline can replace hand DTOs later; keep `ContractVersions.Expected` in sync with Core `CONTRACT_VERSION`.

## 5a acceptance

1. Core online, contract `0.4.0`
2. PoseBrowser open (window alive) so grid can filter
3. F8 with a known query in clipboard → grid intersects AI paths
4. Headless apply: `PoseBrowserExternalApi.TryApplyPoseByPath` works when HostService registered (window Start)
