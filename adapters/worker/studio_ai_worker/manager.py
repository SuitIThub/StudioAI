"""Model lifecycle: load / unload / swap with max_loaded limit."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from studio_ai_worker.backends.llamacpp import LlamaCppBackend
from studio_ai_worker.registry import ModelSpec, load_registry

logger = logging.getLogger(__name__)


class ModelManagerError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class ModelManager:
    def __init__(
        self,
        *,
        registry_path: Path,
        max_loaded: int = 1,
        backend: LlamaCppBackend,
        grammars_dir: Path,
    ) -> None:
        self.registry_path = registry_path
        self.max_loaded = max(1, max_loaded)
        self.backend = backend
        self.grammars_dir = grammars_dir
        self._specs = load_registry(registry_path)

    def reload_registry(self) -> None:
        self._specs = load_registry(self.registry_path)

    def list_models(self) -> list[dict[str, Any]]:
        items = []
        for spec in self._specs.values():
            items.append(
                {
                    "id": spec.id,
                    "name": spec.name,
                    "roles": spec.roles,
                    "backend": spec.backend,
                    "loaded": self.backend.is_loaded(spec.id),
                    "vram_mb": spec.vram_mb,
                    "path": spec.path,
                    "notes": spec.notes,
                }
            )
        return items

    def get_spec(self, model_id: str) -> ModelSpec:
        if model_id not in self._specs:
            raise ModelManagerError(f"Unknown model id: {model_id}", status_code=404)
        return self._specs[model_id]

    def resolve_default_model(self, preferred: str | None = None) -> str:
        if preferred:
            self.get_spec(preferred)
            return preferred
        loaded = self.backend.loaded_ids
        if loaded:
            return loaded[0]
        if self._specs:
            return next(iter(self._specs))
        raise ModelManagerError("No models registered", status_code=404)

    def load(self, model_id: str) -> dict[str, Any]:
        spec = self.get_spec(model_id)
        if self.backend.is_loaded(model_id):
            return {
                "ok": True,
                "message": f"Model '{model_id}' already loaded",
                "loaded_models": self.backend.loaded_ids,
            }

        if len(self.backend.loaded_ids) >= self.max_loaded:
            raise ModelManagerError(
                f"max_loaded={self.max_loaded} reached (loaded: {self.backend.loaded_ids}). "
                "Unload a model or use POST /models/swap.",
                status_code=409,
            )

        if not spec.path:
            raise ModelManagerError(
                f"Model '{model_id}' has no path configured in registry.yaml (placeholder).",
                status_code=400,
            )

        path = Path(spec.path)
        self.backend.load(model_id, path, ctx_size=spec.context_length)
        return {
            "ok": True,
            "message": f"Loaded '{model_id}'",
            "loaded_models": self.backend.loaded_ids,
        }

    def unload(self, model_id: str) -> dict[str, Any]:
        self.get_spec(model_id)
        if not self.backend.is_loaded(model_id):
            return {
                "ok": True,
                "message": f"Model '{model_id}' was not loaded",
                "loaded_models": self.backend.loaded_ids,
            }
        self.backend.unload(model_id)
        return {
            "ok": True,
            "message": f"Unloaded '{model_id}'",
            "loaded_models": self.backend.loaded_ids,
        }

    def swap(self, unload_id: str, load_id: str) -> dict[str, Any]:
        self.get_spec(unload_id)
        self.get_spec(load_id)
        if unload_id == load_id:
            return self.load(load_id)

        # Unload first to free VRAM (max_loaded typically 1 on 6GB)
        if self.backend.is_loaded(unload_id):
            self.backend.unload(unload_id)
        elif len(self.backend.loaded_ids) >= self.max_loaded:
            # Capacity full with a different model – unload oldest/first
            victim = self.backend.loaded_ids[0]
            logger.info("swap: unloading '%s' to free slot for '%s'", victim, load_id)
            self.backend.unload(victim)

        return self.load(load_id)

    def read_grammar(self, grammar: str | None = None, grammar_file: str | None = None) -> str | None:
        if grammar:
            return grammar
        if not grammar_file:
            return None
        path = Path(grammar_file)
        if not path.is_absolute():
            path = self.grammars_dir / path
        if not path.is_file():
            raise ModelManagerError(f"Grammar file not found: {path}", status_code=400)
        return path.read_text(encoding="utf-8")

    def shutdown(self) -> None:
        self.backend.unload_all()
