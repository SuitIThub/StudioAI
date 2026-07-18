# StudioAI – Stage 5a: PoseBrowser Host + AI Search Hook

**Stufe 5a** verdrahtet Core-Suche mit dem PoseBrowser-Grid (ohne Chat-UI).

| Komponente | Rolle |
|------------|--------|
| Core | FTS `/v1/search` (bereits Stufe 3), Contract `0.4.0` |
| `StudioAi.Contracts` | DTOs + Host-Interfaces |
| `StudioAi.Plugin` | HTTP→Core, Contract-Check, F8→Suche→Grid |
| PoseBrowser (HS2-Sandbox) | `SetAiSearchResults`, headless Apply-Fallback |

**Nicht in 5a:** Chat-Panel, Index-Bar, Agent-Tools-UI → **Stufe 5b**.

## Start (Core / Worker)

**Main-PC (Core + JoyCaption):**

```powershell
cd H:\Dateien\Dokumente\Repos\StudioAI
.\scripts\start-core.ps1
```

**Heimserver (Worker + llama.cpp):**

```bash
cd /path/to/StudioAI
./scripts/start-worker.sh
```

Both scripts: `git pull` → venv/pip → start. Skip steps with `-SkipPull` / `--skip-pull` or `-SkipInstall` / `--skip-install`.

## Deploy (kurz)

```powershell
cd H:\Dateien\Dokumente\Repos\StudioAI
.\scripts\deploy_studioai_plugin.ps1
```

PoseBrowser neu bauen/deployen (HS2-Sandbox):

```powershell
cd H:\Dateien\Dokumente\Repos\HS2-Sandbox
dotnet build targets\HS2\PoseBrowser\HS2Sandbox.PoseBrowser.csproj -c Release
# DLL wie gewohnt nach BepInEx\plugins kopieren
```

Details: `adapters/plugin/README.md`

## Abnahme-Checkliste — PAUSE Test

Siehe detaillierten Testplan (kleinteilig) am Ende der 5a-Lieferung / unten in der Chat-Antwort.

## Nächste Stufe

Nach Freigabe: **Stufe 5b – PoseBrowser UI + Agent-Tools**.
