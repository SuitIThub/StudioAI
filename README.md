# StudioAI – Stage 4: Scene Feedback (+ Stage 3 Index)

**Stufe 4** bewertet das **gerenderte Studio-Bild** (aktive Kamera) mit JoyCaption.
Posecode/Metadaten werden dafür **nicht** als Caption-Ersatz benutzt.

| Komponente | Host | Port |
|------------|------|------|
| Core | Haupt-PC | 7860 |
| Worker | Heimserver | 7850 |
| StudioPoseBridge | Haupt-PC (Studio) | 7842 |

**Contract:** `0.4.0`

## Neu in Stufe 4

| Pfad / Befehl | Rolle |
|---------------|--------|
| `core/.../scene_feedback/` | OnDemand + Watch + optional Stheno-Polish |
| `core/.../vision_gate.py` | JoyCaption exklusiv: Index vs Feedback |
| `POST /v1/scene-feedback/analyze` | Einmal-Analyse |
| `POST /v1/scene-feedback/watch/start\|stop` | Debounced Watch |
| `GET /v1/scene-feedback/status\|latest` | Status / letztes Ergebnis |
| `studio-ai feedback …` | CLI |
| `http://127.0.0.1:7860/feedback` | Web-Panel |
| Bridge `angle=current` | `camera_source=studio_active` |

Presets: `scene_feedback`, `scene_critique`, `Versaut (NSFW)`.

## Setup (kurz)

```powershell
cd H:\Dateien\Dokumente\Repos\StudioAI
.\.venv\Scripts\Activate.ps1
$env:STUDIO_AI_CORE_CONFIG = "$PWD\deploy\config.main-pc.yaml"
# Vision einmalig (falls noch nicht):
.\scripts\setup_vision.ps1
studio-ai-core
```

Heimserver: `studio-ai-worker` wie bisher. Studio + StudioPoseBridge laufen lassen.

Config: `deploy/config.main-pc.yaml` → Abschnitt `scene_feedback`.

## Abnahme-Checkliste — PAUSE Test

Siehe detaillierten Testplan unten (kleinteilige Befehle).

- [ ] OnDemand = Caption eines echten Bridge-PNGs (`studio_active` → `angle=current`)
- [ ] `instruction` landet im JoyCaption-Prompt
- [ ] Watch debounced (≥5 s, Default 12)
- [ ] Watch pausiert während Index (`vision.indexing`)
- [ ] Kein Metadata-/Posecode-Fake als Caption
- [ ] Optional: Polish mit Stheno (Worker online)

## Nächste Stufe

Nach Freigabe: **Stufe 5a – Contracts + Host + Search-Hook**.
