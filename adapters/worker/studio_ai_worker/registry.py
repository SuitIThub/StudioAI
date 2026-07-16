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
    # Qwen3-Thinking etc.: False disables thinking via llama-server flags + request kwargs
    enable_thinking: bool | None = None
    # Cap thinking tokens when enable_thinking is true (llama.cpp --reasoning-budget)
    reasoning_budget: int | None = None
    extra_args: list[str] | None = None

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
        extra = entry.get("extra_args") or []
        if not isinstance(extra, list):
            extra = []
        thinking = entry.get("enable_thinking")
        if thinking is not None:
            thinking = bool(thinking)
        budget = entry.get("reasoning_budget")
        if budget is not None:
            budget = int(budget)
        out[model_id] = ModelSpec(
            id=model_id,
            name=str(entry.get("name") or model_id),
            roles=[str(r) for r in (entry.get("roles") or [])],
            backend=str(entry.get("backend") or "llamacpp"),
            path=entry.get("path"),
            vram_mb=int(entry.get("vram_mb") or 0),
            context_length=int(entry.get("context_length") or 32768),
            chat_template=entry.get("chat_template"),
            notes=entry.get("notes"),
            enable_thinking=thinking,
            reasoning_budget=budget,
            extra_args=[str(a) for a in extra] or None,
        )
    return out


def dump_registry_example() -> dict[str, Any]:
    return {"models": []}
