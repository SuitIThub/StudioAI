# StudioAI – Stage 2: LLM Chat

Zentrales Monorepo. **Stufe 2** baut auf Stufe 1 auf: Core orchestriert Chat mit Personas (Stheno/Satyr), Role-Routing und Streaming. Der Heimserver-Worker bleibt thin.

| Komponente | Host | Port | Rolle |
|------------|------|------|--------|
| **Core** | Haupt-PC (Windows ok) | `7860` | Chat-API, Web-UI, CLI, Routing |
| **Worker** | Heimserver (Ubuntu) | `7850` | Model load/swap + llama.cpp |

**Noch nicht:** Studio-Bridge, JoyCaption, PoseBrowser, Indexierung.

## Was ist neu in Stufe 2

| Pfad | Rolle |
|------|--------|
| `core/studio_ai_core/` | Chat-Service, Personas, Routing, FastAPI + Web-UI |
| `POST /v1/chat` | Mehrturn-Chat (SSE-Streaming), Persona Stheno/Satyr |
| `POST /v1/structured` | Role `structured_json` → Qwen + GBNF |
| `studio-ai-chat` | Interaktive CLI gegen Core |
| Worker `stream: true` | Thin Pass-through SSE von llama.cpp |

## Voraussetzungen

- Stufe 1 auf dem Heimserver lauffähig (Worker + GGUF-Pfade + llama-server)
- Python 3.10+ auf dem **Haupt-PC** (Core) und Heimserver (Worker)
- LAN-Erreichbarkeit Haupt-PC → Heimserver:7850

## Setup

### Heimserver (Worker – unverändert Stufe 1)

```bash
cd /path/to/StudioAI
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
# registry.yaml + config.home-server.yaml anpassen
export STUDIO_AI_CONFIG="$PWD/deploy/config.home-server.yaml"
studio-ai-worker
```

### Haupt-PC (Core)

```powershell
cd H:\Dateien\Dokumente\Repos\StudioAI
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

# deploy/config.main-pc.yaml → worker_remote.url = Heimserver-LAN-IP
$env:STUDIO_AI_CORE_CONFIG = "$PWD\deploy\config.main-pc.yaml"
studio-ai-core
```

- Web-UI: `http://127.0.0.1:7860/` (oder LAN-IP des Haupt-PCs)
- API-Docs: `http://127.0.0.1:7860/docs`
- CLI: `studio-ai-chat --base http://127.0.0.1:7860`

Firewall Haupt-PC (falls LAN-Chat von anderem Gerät): Port **7860**.

## Role-Routing

| Anfrage | Route |
|---------|--------|
| `/v1/chat` + persona `stheno` / `satyr` | `agent_chat` → Stheno / Satyr |
| `/v1/structured` | `structured_json` → Qwen + GBNF |
| Chat mit `model=qwen-technical` | **400** (Routing-Fehler) |

Bei `max_loaded=1` swapped der Core automatisch das geladene Modell.

## Offline-Verhalten

Wenn der Worker down ist:

- `GET /health` → `status=degraded`, `worker.online=false`
- `POST /v1/chat` / `/v1/structured` → **503** mit `code: worker_offline`

## Abnahme-Checkliste (Stufe 2) — PAUSE Test

- [ ] Worker + Core laufen; Core `GET /health` zeigt `worker.online=true`
- [ ] Web-UI oder CLI: Mehrturn-Chat mit Stheno
- [ ] Persona-Wechsel auf Satyr (Modell-Swap, Chat funktioniert)
- [ ] Structured-Probe: `.\scripts\smoke_stage2.ps1 -Structured` → valides JSON
- [ ] Worker stoppen → Chat zeigt klaren Offline-Fehler (503 / UI-Hinweis)
- [ ] Von anderem LAN-Gerät Core-UI öffnen (optional)

Smoke:

```powershell
.\scripts\smoke_stage2.ps1 -Chat -Persona stheno
.\scripts\smoke_stage2.ps1 -Structured
```

```bash
./scripts/smoke_stage2.sh --chat --persona stheno
./scripts/smoke_stage2.sh --structured
```

## Nächste Stufe

Nach Test + Freigabe: **Stufe 3 – Capture + Describe** (Bridge, JoyCaption, Posecode, FTS).
