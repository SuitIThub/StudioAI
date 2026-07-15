"""Registered model catalog (YAML)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ModelSpec:
    id: str
    name: str
    roles: list[str]
    backend: str
    path: str | None
    vram_mb: int
    context_length: int
    chat_template: str | None = None
    notes: str | None = None

    @property
    def resolved_path(self) -> Path | None:
        if not self.path:
            return None
        return Path(self.path)


def load_registry(path: Path) -> dict[str, ModelSpec]:
    if not path.is_file():
        raise FileNotFoundError(f"Model registry not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    models_raw = raw.get("models") or []
    out: dict[str, ModelSpec] = {}
    for entry in models_raw:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry["id"])
        out[model_id] = ModelSpec(
            id=model_id,
            name=str(entry.get("name") or model_id),
            roles=[str(r) for r in (entry.get("roles") or [])],
            backend=str(entry.get("backend") or "llamacpp"),
            path=entry.get("path"),
            vram_mb=int(entry.get("vram_mb") or 0),
            context_length=int(entry.get("context_length") or 4096),
            chat_template=entry.get("chat_template"),
            notes=entry.get("notes"),
        )
    return out


def dump_registry_example() -> dict[str, Any]:
    return {"models": []}
