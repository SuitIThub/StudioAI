#!/usr/bin/env bash
# Stage 1 smoke on Ubuntu home server
# Usage:
#   ./scripts/smoke_stage1.sh
#   ./scripts/smoke_stage1.sh --gbnf --model qwen-technical
#   ./scripts/smoke_stage1.sh --chat --model stheno-8b

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

exec "$PYTHON" scripts/smoke_stage1.py "$@"
