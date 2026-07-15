# StudioAI – Stage 1: Model Infrastructure

Zentrales Monorepo für den Studio-AI-Stack. **Stufe 1** liefert nur die nötigste Infrastruktur: Modelle registrieren, laden/entladen/swappen und per llama.cpp Inference ausführen.

**Heimserver-Zielplattform: Ubuntu** (Worker läuft dort). Der Windows-Haupt-PC kommt ab späteren Stufen dazu.

## Was ist drin

| Pfad | Rolle |
|------|--------|
| `adapters/worker/` | Thin Worker (FastAPI) + Model-Manager + llama.cpp-Backend |
| `core/studio_ai_core/` | Profile-Definitionen (SoT für Rollen) |
| `deploy/` | Config, `registry.yaml` (Platzhalter-Pfade), GBNF |
| `contracts/openapi.yaml` | API-SoT für spätere C#-Codegen (Entscheidung B) |

**Noch nicht (kommt in späteren Stufen):** Studio-Bridge, JoyCaption, Chat-UI, PoseBrowser.

## Voraussetzungen (Heimserver / Ubuntu)

- Ubuntu mit NVIDIA-Treiber (GTX 2060 Super)
- Python 3.10+ (`python3`, `python3-venv`)
- Selbst kompiliertes **llama.cpp** mit `llama-server` im `PATH` oder absolutem Pfad in der Config
- GGUF-Dateien für Qwen / Stheno / Satyr (Pfade in `deploy/registry.yaml`)

## Setup (Ubuntu)

```bash
cd /path/to/StudioAI
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Pfade anpassen:
#   deploy/registry.yaml              → echte .gguf-Pfade (Linux-Absolutpfade)
#   deploy/config.home-server.yaml    → llamacpp.bin z.B. /home/you/llama.cpp/build/bin/llama-server
```

## Start (Ubuntu)

```bash
cd /path/to/StudioAI
source .venv/bin/activate
export STUDIO_AI_CONFIG="$PWD/deploy/config.home-server.yaml"
studio-ai-worker
```

API: `http://<heimserver-lan-ip>:7850`  
Docs: `http://<heimserver-lan-ip>:7850/docs`

Firewall (falls nötig):

```bash
sudo ufw allow 7850/tcp
```

## API (Kurz)

```
GET  /health
GET  /models
POST /models/{id}/load
POST /models/{id}/unload
POST /models/swap                 { "unload_id": "...", "load_id": "..." }
POST /v1/completions              { prompt, model?, grammar_file? }
POST /v1/chat/completions         { messages, model?, ... }
```

`max_loaded_models: 1` (Default) – zweites Load ohne Unload → **409**. Nutze `/models/swap`.

Optional Auth: `worker.token` in Config → Header `Authorization: Bearer <token>`.

## Abnahme-Checkliste (Stufe 1) — PAUSE Test

- [ ] Worker startet; `GET /health` → `status=ok`, `contract_version=0.1.0`
- [ ] `GET /models` listet `qwen-technical`, `stheno-8b`, `satyr`
- [ ] Pfade in `registry.yaml` gesetzt (keine `CHANGE_ME` mehr, Linux-Pfade)
- [ ] `POST /models/qwen-technical/load` erfolgreich
- [ ] GBNF-Smoke:
  ```bash
  chmod +x scripts/smoke_stage1.sh
  ./scripts/smoke_stage1.sh --gbnf --model qwen-technical
  ```
  Antwort ist valides JSON laut `deploy/grammars/smoke_json.gbnf`
- [ ] Swap qwen → stheno; Chat-Smoke:
  ```bash
  ./scripts/smoke_stage1.sh --chat --model stheno-8b
  ```
- [ ] Satyr ebenfalls load/unload bzw. swap
- [ ] Zweites Load bei vollem Slot ohne Unload → 409 (kein Doppel-VRAM)

## Model-Rollen (Core-Profiles)

| ID | Rollen |
|----|--------|
| `qwen-technical` | `index_merge`, `structured_json` (+ GBNF) |
| `stheno-8b` | `agent_chat`, `scene_feedback_polish` |
| `satyr` | `agent_chat` |

Posecode bleibt später **regelbasiert** im Core – keine Modell-Rolle `posecode_interpret`.

## Nächste Stufe

Nach deinem persönlichen Test und Freigabe: **Stufe 2 – LLM-Chat-Einbindung** (Streaming-Chat-UI am Core).
