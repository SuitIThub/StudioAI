"""Unit tests that do not need llama-server or GGUF files."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from studio_ai_worker.backends.llamacpp import LlamaCppBackend
from studio_ai_worker.manager import ModelManager, ModelManagerError


@pytest.fixture()
def registry_file(tmp_path: Path) -> Path:
    data = {
        "models": [
            {
                "id": "a",
                "name": "A",
                "roles": ["structured_json"],
                "backend": "llamacpp",
                "path": str(tmp_path / "missing-a.gguf"),
                "vram_mb": 1000,
                "context_length": 2048,
            },
            {
                "id": "b",
                "name": "B",
                "roles": ["agent_chat"],
                "backend": "llamacpp",
                "path": str(tmp_path / "missing-b.gguf"),
                "vram_mb": 1000,
                "context_length": 2048,
            },
        ]
    }
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


def test_max_loaded_blocks_second_load(registry_file: Path, tmp_path: Path):
    backend = LlamaCppBackend(bin_path="llama-server-not-used")

    class _FakeServer:
        model_id = "a"

    backend._servers["a"] = _FakeServer()  # type: ignore[assignment]

    mm = ModelManager(
        registry_path=registry_file,
        max_loaded=1,
        backend=backend,
        grammars_dir=tmp_path,
    )

    with pytest.raises(ModelManagerError) as exc:
        mm.load("b")
    assert exc.value.status_code == 409


def test_list_models(registry_file: Path, tmp_path: Path):
    backend = LlamaCppBackend()
    mm = ModelManager(
        registry_path=registry_file,
        max_loaded=1,
        backend=backend,
        grammars_dir=tmp_path,
    )
    models = mm.list_models()
    assert {m["id"] for m in models} == {"a", "b"}
