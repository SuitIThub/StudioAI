"""Worker configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

# adapters/worker/studio_ai_worker/config.py -> parents[3] = StudioAI repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPO_ROOT / "deploy" / "config.home-server.yaml"


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STUDIO_AI_", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 7850
    token: str = ""
    max_loaded: int = 1
    preferred_backend: str = "llamacpp"
    registry_path: Path = REPO_ROOT / "deploy" / "registry.yaml"
    grammars_dir: Path = REPO_ROOT / "deploy" / "grammars"
    llamacpp_bin: str = "llama-server"
    llamacpp_host: str = "127.0.0.1"
    llamacpp_base_port: int = 8080
    llamacpp_ctx_size: int = 4096
    llamacpp_n_gpu_layers: int = 99
    health_timeout_s: float = 2.0
    load_timeout_s: float = 180.0


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def settings_from_config(config_path: Path | None = None) -> WorkerSettings:
    path = config_path or Path(
        __import__("os").environ.get("STUDIO_AI_CONFIG", str(DEFAULT_CONFIG_PATH))
    )
    raw = load_yaml_file(path)
    worker = raw.get("worker") or {}
    mm = raw.get("model_manager") or {}
    llamacpp = raw.get("llamacpp") or {}

    merged: dict[str, Any] = {
        "host": worker.get("host", "0.0.0.0"),
        "port": worker.get("port", 7850),
        "token": worker.get("token", ""),
        "max_loaded": mm.get("max_loaded_models", 1),
        "preferred_backend": mm.get("preferred_backend", "llamacpp"),
        "registry_path": Path(mm.get("registry_path", REPO_ROOT / "deploy" / "registry.yaml")),
        "grammars_dir": Path(mm.get("grammars_dir", REPO_ROOT / "deploy" / "grammars")),
        "llamacpp_bin": llamacpp.get("bin", "llama-server"),
        "llamacpp_host": llamacpp.get("host", "127.0.0.1"),
        "llamacpp_base_port": llamacpp.get("base_port", 8080),
        "llamacpp_ctx_size": llamacpp.get("ctx_size", 4096),
        "llamacpp_n_gpu_layers": llamacpp.get("n_gpu_layers", 99),
    }
    # Resolve relative paths against config file directory / repo root
    base = path.parent if path.is_file() else REPO_ROOT
    for key in ("registry_path", "grammars_dir"):
        p = Path(merged[key])
        if not p.is_absolute():
            merged[key] = (base / p).resolve()
        else:
            merged[key] = p

    return WorkerSettings(**merged)
