#!/usr/bin/env bash
# Start StudioAI Core (Linux / WSL on the main PC).
#
# Usage:
#   ./scripts/start-core.sh
#   ./scripts/start-core.sh --skip-pull
#   ./scripts/start-core.sh --skip-install

set -euo pipefail

SKIP_PULL=0
SKIP_INSTALL=0
CONFIG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-pull) SKIP_PULL=1; shift ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --config) CONFIG="${2:-}"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--skip-pull] [--skip-install] [--config PATH]"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

step() { printf '\n==> %s\n' "$*"; }

if [[ "$SKIP_PULL" -eq 0 ]]; then
  step "git pull"
  if [[ -d .git ]]; then
    if ! git pull --ff-only; then
      echo "git pull --ff-only failed (local changes?). Continuing with current tree." >&2
    fi
  else
    echo "Not a git checkout — skip pull."
  fi
fi

PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  step "create .venv"
  python3 -m venv .venv
  PY="$ROOT/.venv/bin/python"
fi

if [[ "$SKIP_INSTALL" -eq 0 ]]; then
  step "pip install -e \".[vision]\""
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -e ".[vision]" || {
    echo "pip install failed. On CUDA hosts also run scripts/setup_vision.ps1 (Windows) or install torch+cu manually." >&2
    exit 1
  }
fi

CONFIG_PATH="${CONFIG:-$ROOT/deploy/config.main-pc.yaml}"
if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Core config not found: $CONFIG_PATH" >&2
  exit 1
fi

export STUDIO_AI_CORE_CONFIG="$(cd "$(dirname "$CONFIG_PATH")" && pwd)/$(basename "$CONFIG_PATH")"
export PYTHONPATH="$ROOT/core:$ROOT/adapters/worker${PYTHONPATH:+:$PYTHONPATH}"

step "start Core"
echo "Config: $STUDIO_AI_CORE_CONFIG"
echo "Ports:  7200-7299 (auto)"
echo "Stop:   Ctrl+C"
echo

if [[ -x "$ROOT/.venv/bin/studio-ai-core" ]]; then
  exec "$ROOT/.venv/bin/studio-ai-core"
else
  exec "$PY" -m studio_ai_core
fi
