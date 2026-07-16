#!/usr/bin/env bash
# Stage-2 smoke (Core on main PC). Usage:
#   ./scripts/smoke_stage2.sh --chat --persona stheno
#   ./scripts/smoke_stage2.sh --structured
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source .venv/bin/activate
python scripts/smoke_stage2.py "$@"
