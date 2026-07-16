"""Core configuration (main PC primary node)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from studio_ai_core import REPO_ROOT

DEFAULT_CONFIG_PATH = REPO_ROOT / "deploy" / "config.main-pc.yaml"
logger = logging.getLogger(__name__)


class CoreSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STUDIO_AI_CORE_", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 7860
    node_id: str = "main-pc"
    worker_url: str = "http://127.0.0.1:7850"
    worker_token: str = ""
    worker_timeout_s: float = 120.0
    health_timeout_s: float = 3.0
    default_persona: str = "stheno"
    grammars_dir: Path = REPO_ROOT / "deploy" / "grammars"
    config_path: Path | None = None


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def settings_from_config(config_path: Path | None = None) -> CoreSettings:
    env_path = os.environ.get("STUDIO_AI_CORE_CONFIG")
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
            f"Core config not found: {path}. "
            "Use deploy/config.main-pc.yaml (extension .yaml, not -yaml)."
        )
        if explicit:
            raise FileNotFoundError(msg)
        logger.warning("%s Falling back to built-in defaults (worker → 127.0.0.1).", msg)

    raw = load_yaml_file(path)
    node = raw.get("node") or {}
    worker = raw.get("worker_remote") or {}
    core = raw.get("core") or {}

    grammars = Path(core.get("grammars_dir", REPO_ROOT / "deploy" / "grammars"))
    if not grammars.is_absolute():
        base = path.parent if path.is_file() else REPO_ROOT
        grammars = (base / grammars).resolve()

    return CoreSettings(
        host=core.get("host", "0.0.0.0"),
        port=int(core.get("port", 7860)),
        node_id=node.get("id", "main-pc"),
        worker_url=str(worker.get("url", "http://127.0.0.1:7850")).rstrip("/"),
        worker_token=str(worker.get("token", "") or ""),
        worker_timeout_s=float(core.get("worker_timeout_s", 120.0)),
        health_timeout_s=float(core.get("health_timeout_s", 3.0)),
        default_persona=str(core.get("default_persona", "stheno")),
        grammars_dir=grammars,
        config_path=path if path.is_file() else None,
    )
