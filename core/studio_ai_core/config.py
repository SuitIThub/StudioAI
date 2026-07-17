"""Core configuration (main PC primary node)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from studio_ai_core import REPO_ROOT
from studio_ai_core.indexing.cameras import CameraPolicy

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

    # Stage 3
    bridge_url: str = "http://127.0.0.1:7842"
    bridge_token: str = ""
    index_db_path: Path = REPO_ROOT / "data" / "pose_index.sqlite"
    capture_dir: Path = REPO_ROOT / "data" / "captures"
    joycaption_quant: str = "8bit"
    one_quarter_mode: str = "auto"
    one_quarter_angle: str = "45"


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def _resolve_path(value: str | Path, base: Path) -> Path:
    p = Path(value)
    if not p.is_absolute():
        p = (base / p).resolve()
    return p


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
    bridge = raw.get("bridge") or {}
    indexing = raw.get("indexing") or {}
    cameras = indexing.get("cameras") or {}

    base = path.parent if path.is_file() else REPO_ROOT

    grammars = _resolve_path(
        core.get("grammars_dir", REPO_ROOT / "deploy" / "grammars"), base
    )
    db_path = _resolve_path(
        indexing.get("db_path", REPO_ROOT / "data" / "pose_index.sqlite"), base
    )
    capture_dir = _resolve_path(
        indexing.get("capture_dir", REPO_ROOT / "data" / "captures"), base
    )

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
        bridge_url=str(bridge.get("url", "http://127.0.0.1:7842")).rstrip("/"),
        bridge_token=str(bridge.get("token", "") or ""),
        index_db_path=db_path,
        capture_dir=capture_dir,
        joycaption_quant=str(indexing.get("joycaption_quant", "8bit")),
        one_quarter_mode=str(cameras.get("one_quarter_mode", "auto")),
        one_quarter_angle=str(cameras.get("one_quarter_angle", "45")),
    )


def camera_policy_from_settings(settings: CoreSettings) -> CameraPolicy:
    return CameraPolicy(
        one_quarter_mode=settings.one_quarter_mode,
        one_quarter_angle=settings.one_quarter_angle,
    )
