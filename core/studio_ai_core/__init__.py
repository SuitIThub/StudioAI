"""StudioAI Core – single source of truth (Stage 4: chat + indexing + scene feedback)."""

from __future__ import annotations

from pathlib import Path

CONTRACT_VERSION = "0.4.0"
PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[1]
