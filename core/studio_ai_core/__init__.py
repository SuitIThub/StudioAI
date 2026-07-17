"""StudioAI Core – single source of truth (Stage 3: chat + indexing)."""

from __future__ import annotations

from pathlib import Path

CONTRACT_VERSION = "0.3.0"
PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[1]
