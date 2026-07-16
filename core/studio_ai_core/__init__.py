"""StudioAI Core – single source of truth (Stage 2: LLM chat)."""

from __future__ import annotations

from pathlib import Path

CONTRACT_VERSION = "0.2.0"
PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[1]
