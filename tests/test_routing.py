"""Unit tests for Stage-2 role routing and personas (no worker required)."""

from __future__ import annotations

import pytest

from studio_ai_core.personas import get_persona
from studio_ai_core.routing import (
    RoutingError,
    resolve_chat_target,
    resolve_structured_target,
)
from studio_ai_core.chat_service import ChatService
from studio_ai_core.worker_client import WorkerClient
from pathlib import Path


def test_personas_exist():
    assert get_persona("stheno").model_id == "stheno-8b"
    assert get_persona("satyr").model_id == "satyr"


def test_resolve_chat_default_persona():
    model_id, persona = resolve_chat_target(default_persona="stheno")
    assert model_id == "stheno-8b"
    assert persona is not None
    assert persona.id == "stheno"


def test_resolve_chat_satyr():
    model_id, persona = resolve_chat_target(persona_id="satyr")
    assert model_id == "satyr"
    assert persona is not None


def test_resolve_chat_rejects_qwen():
    with pytest.raises(RoutingError):
        resolve_chat_target(model_id="qwen-technical")


def test_resolve_structured_default():
    profile = resolve_structured_target()
    assert profile.id == "qwen-technical"
    assert profile.grammar is True


def test_resolve_structured_rejects_chat_model():
    with pytest.raises(RoutingError):
        resolve_structured_target("stheno-8b")


def test_build_messages_injects_system(tmp_path: Path):
    svc = ChatService(WorkerClient("http://127.0.0.1:9"), grammars_dir=tmp_path)
    msgs = svc.build_messages(
        [{"role": "user", "content": "hi"}],
        persona_id="stheno",
    )
    assert msgs[0]["role"] == "system"
    assert "Stheno" in msgs[0]["content"]
    assert msgs[1]["content"] == "hi"


def test_build_messages_keeps_existing_system(tmp_path: Path):
    svc = ChatService(WorkerClient("http://127.0.0.1:9"), grammars_dir=tmp_path)
    msgs = svc.build_messages(
        [
            {"role": "system", "content": "custom"},
            {"role": "user", "content": "hi"},
        ],
        persona_id="stheno",
    )
    assert msgs[0]["content"] == "custom"
    assert len(msgs) == 2
