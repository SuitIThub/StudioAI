"""Worker configuration."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

# adapters/worker/studio_ai_worker/config.py -> parents[3] = StudioAI repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPO_ROOT / "deploy" / "config.home-server.yaml"

logger = logging.getLogger(__name__)


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
    llamacpp_ctx_size: int = 32768
    llamacpp_n_gpu_layers: int = 99
    health_timeout_s: float = 2.0
    load_timeout_s: float = 180.0
    config_path: Path | None = None


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def resolve_llamacpp_bin(bin_value: str) -> str:
    """Return absolute path if possible; keep bare name only when found on PATH."""
    p = Path(bin_value)
    if p.is_file():
        return str(p.resolve())
    found = shutil.which(bin_value)
    if found:
        return found
    return bin_value


def settings_from_config(config_path: Path | None = None) -> WorkerSettings:
    env_path = os.environ.get("STUDIO_AI_CONFIG")
    if config_path is not None:
        path = Path(config_path)
        explicit = True
    elif env_path:
        path = Path(env_path)
        explicit = True
    else:
        path = DEFAULT_CONFIG_PATH
        explicit = False

    if not path.is_file():
        msg = (
            f"Worker config not found: {path}. "
            "Use an existing file, e.g. deploy/config.home-server.yaml "
            "(extension must be .yaml, not -yaml)."
        )
        if explicit:
            raise FileNotFoundError(msg)
        logger.warning("%s Falling back to built-in defaults.", msg)

    raw = load_yaml_file(path)
    worker = raw.get("worker") or {}
    mm = raw.get("model_manager") or {}
    llamacpp = raw.get("llamacpp") or {}

    bin_raw = str(llamacpp.get("bin", "llama-server"))
    merged: dict[str, Any] = {
        "host": worker.get("host", "0.0.0.0"),
        "port": worker.get("port", 7850),
        "token": worker.get("token", ""),
        "max_loaded": mm.get("max_loaded_models", 1),
        "preferred_backend": mm.get("preferred_backend", "llamacpp"),
        "registry_path": Path(mm.get("registry_path", REPO_ROOT / "deploy" / "registry.yaml")),
        "grammars_dir": Path(mm.get("grammars_dir", REPO_ROOT / "deploy" / "grammars")),
        "llamacpp_bin": resolve_llamacpp_bin(bin_raw),
        "llamacpp_host": llamacpp.get("host", "127.0.0.1"),
        "llamacpp_base_port": llamacpp.get("base_port", 8080),
        "llamacpp_ctx_size": llamacpp.get("ctx_size", 32768),
        "llamacpp_n_gpu_layers": llamacpp.get("n_gpu_layers", 99),
        "config_path": path if path.is_file() else None,
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
