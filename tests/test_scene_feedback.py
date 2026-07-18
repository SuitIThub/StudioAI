"""Unit tests for Stage-4 vision gate + feedback helpers (no GPU)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from studio_ai_core.scene_feedback import CAMERA_ANGLES, SceneFeedbackService
from studio_ai_core.vision_gate import VisionGate


def test_camera_source_maps_to_current():
    assert CAMERA_ANGLES["studio_active"] == "current"
    assert CAMERA_ANGLES["front_full"] == "front"


def test_vision_gate_indexing_flag():
    async def _run():
        gate = VisionGate()
        assert gate.indexing is False
        gate.begin_index()
        assert gate.indexing is True
        async with gate.hold("index"):
            assert gate.owner == "index"
            assert gate.locked is True
        gate.end_index()
        assert gate.indexing is False
        assert gate.owner is None

    asyncio.run(_run())


def test_analyze_pauses_when_indexing(tmp_path: Path):
    async def _run():
        gate = VisionGate()
        gate.begin_index()

        class DummyBridge:
            pass

        class DummyJoy:
            loaded = True

            def load(self, quant=None):
                return "ok"

        svc = SceneFeedbackService(
            bridge=DummyBridge(),  # type: ignore[arg-type]
            joycaption=DummyJoy(),  # type: ignore[arg-type]
            vision_gate=gate,
            chat=None,
            capture_dir=tmp_path,
        )
        out = await svc.analyze(character_id=0)
        assert out.get("paused") is True
        assert out.get("reason") == "indexing_in_progress"
        gate.end_index()

    asyncio.run(_run())


def test_instruction_appended_in_caption_path(monkeypatch, tmp_path: Path):
    from PIL import Image

    from studio_ai_core.indexing.joycaption.client import JoyCaptionClient

    img = tmp_path / "x.png"
    Image.new("RGB", (32, 32), color=(20, 40, 60)).save(img)

    client = JoyCaptionClient()
    captured: dict = {}

    def fake_caption_image(image, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(client, "caption_image", fake_caption_image)
    text = client.caption_path(
        img,
        caption_type="scene_feedback",
        instruction="Focus on framing",
    )
    assert text == "ok"
    assert "Additional instruction: Focus on framing" in (captured.get("prompt") or "")
