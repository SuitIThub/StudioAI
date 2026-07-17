# StudioAI – Stage 3: Capture + Describe + FTS Index

**Stufe 3** indexiert Posen suchtauglich: Bridge-Capture → regelbasiertes Posecode → JoyCaption → Qwen+GBNF-Merge → SQLite/FTS.

| Komponente | Host | Port |
|------------|------|------|
| Core | Haupt-PC | 7860 |
| Worker | Heimserver | 7850 |
| StudioPoseBridge | Haupt-PC (Studio) | 7842 |

**Nicht in Stufe 3:** Scene-Feedback-Watch, PoseBrowser-AI-UI.

## Neu in Stufe 3

| Pfad / Befehl | Rolle |
|---------------|--------|
| `core/.../indexing/posecode` | Regeln: `pose_compact` → tags/text |
| `core/.../indexing/joycaption` | JoyCaption-Client (`pip install -e ".[vision]"`) |
| `core/.../indexing/merge` + `deploy/grammars/index_entry.gbnf` | Qwen-Merge |
| `core/.../indexing/store` | SQLite + FTS5 |
| `core/.../bridge` | HTTP-Client zu StudioPoseBridge |
| `studio-ai search/posecode/capture/describe/batch` | CLI |
| `POST /v1/capture`, `/v1/describe`, `/v1/search`, … | Core-API |

## Setup (Haupt-PC)

```powershell
cd H:\Dateien\Dokumente\Repos\StudioAI
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
# Für Live-Captions:
# pip install -e ".[vision]"

# config.main-pc.yaml: worker_remote.url, bridge.token
$env:STUDIO_AI_CORE_CONFIG = "$PWD\deploy\config.main-pc.yaml"
studio-ai-core
```

Heimserver: Worker wie Stufe 1/2 (`studio-ai-worker`).

## Offline-Batch + FTS (ohne Studio)

```powershell
python scripts/generate_batch_fixtures.py --count 120
studio-ai batch testdata\batch_poses --no-merge
studio-ai search "kneeling from behind"
python scripts/smoke_stage3.py --no-merge
```

Mit Qwen-Merge (Worker online, Qwen geladen/swap ok):

```powershell
studio-ai batch testdata\batch_poses
```

## Live Capture (Studio + Bridge)

1. StudioNeoV2 + StudioPoseBridge, Charakter in Szene, Pose applied  
2. Token in `deploy/config.main-pc.yaml` → `bridge.token`  
3. Core neu starten  

```powershell
studio-ai capture --character 0
studio-ai describe --character 0          # braucht [vision] + Worker für Merge
studio-ai describe --folder data\captures\<id> --no-joycaption   # nur Posecode+Merge/Fallback
```

Siehe `adapters/bridge/README.md`.

## Abnahme-Checkliste — PAUSE Test

- [ ] Posecode-Regeln: bekannte Compact-Fixtures → erwartete Tags  
- [ ] Capture Front/3Q (Bridge): `pose_compact` nicht leer, PNGs da  
- [ ] Describe (JoyCaption) für Front + Three-Quarter  
- [ ] Einzel-Merge → valides `index_entry` JSON (oder Fallback dokumentiert)  
- [ ] Batch ≥100 indexiert  
- [ ] FTS: ≥10 vorbereitete Queries treffen erwartete Posen (`smoke_stage3.py`)

## Nächste Stufe

Nach Freigabe: **Stufe 4 – Scene-Feedback**.
