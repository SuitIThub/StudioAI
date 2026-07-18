"""Stage 4 – visual scene feedback (JoyCaption on Studio render)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from studio_ai_core.bridge import BridgeClient, BridgeError
from studio_ai_core.chat_service import ChatService
from studio_ai_core.indexing.joycaption import JoyCaptionClient, JoyCaptionUnavailable
from studio_ai_core.vision_gate import VisionGate

logger = logging.getLogger(__name__)

# camera_source → Bridge screenshot angle
CAMERA_ANGLES = {
    "studio_active": "current",  # Camera.main / active Studio viewport
    "front_full": "front",
    "front": "front",
    "three_quarter": "three_quarter",
}

DEFAULT_FEEDBACK_PRESET = "scene_feedback"
POLISH_SYSTEM = (
    "You help a 3D studio creator. Given a visual description of the current render, "
    "reply with 1-3 short practical tips (framing, composition, clarity, mood). "
    "Do not invent objects that are not in the description. No roleplay."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WatchConfig:
    character_id: int
    caption_preset: str = DEFAULT_FEEDBACK_PRESET
    camera_source: str = "studio_active"
    instruction: str | None = None
    polish_with_chat: bool = False
    size: int = 768
    debounce_s: float = 12.0


@dataclass
class SceneFeedbackService:
    bridge: BridgeClient
    joycaption: JoyCaptionClient
    vision_gate: VisionGate
    chat: ChatService | None
    capture_dir: Path
    joycaption_quant: str = "8bit"
    default_preset: str = DEFAULT_FEEDBACK_PRESET
    default_debounce_s: float = 12.0
    default_polish: bool = False

    latest: dict[str, Any] | None = field(default=None, init=False)
    _watch: WatchConfig | None = field(default=None, init=False)
    _watch_task: asyncio.Task[None] | None = field(default=None, init=False)
    _analyze_count: int = field(default=0, init=False)

    def _ensure_joycaption(self) -> None:
        if not self.joycaption.loaded:
            quant = self.joycaption_quant if self.joycaption_quant in ("bf16", "8bit", "nf4") else None
            self.joycaption.load(quant=quant)  # type: ignore[arg-type]

    def _angle_for(self, camera_source: str) -> str:
        key = (camera_source or "studio_active").strip().lower()
        if key not in CAMERA_ANGLES:
            raise ValueError(
                f"Unknown camera_source {camera_source!r}; "
                f"expected one of {sorted(CAMERA_ANGLES)}"
            )
        return CAMERA_ANGLES[key]

    async def capture_render(
        self,
        *,
        character_id: int,
        camera_source: str = "studio_active",
        size: int = 768,
        framing: str = "full_body",
    ) -> Path:
        """Screenshot from Bridge (studio_active = Camera.main). Real PNG only."""
        angle = self._angle_for(camera_source)
        out_dir = Path(self.capture_dir) / "feedback"
        out_dir.mkdir(parents=True, exist_ok=True)
        png = await self.bridge.screenshot_bytes(
            character_id,
            angle=angle,
            size=size,
            framing=framing,
        )
        dest = out_dir / f"scene_{character_id}_{int(datetime.now().timestamp())}.png"
        dest.write_bytes(png)
        return dest.resolve()

    async def analyze(
        self,
        *,
        character_id: int,
        caption_preset: str | None = None,
        camera_source: str = "studio_active",
        instruction: str | None = None,
        polish_with_chat: bool | None = None,
        size: int = 768,
        image_path: Path | str | None = None,
    ) -> dict[str, Any]:
        """
        OnDemand / Manual: capture (unless image_path given) → JoyCaption → optional polish.

        Never fabricates a caption from pose metadata.
        """
        if self.vision_gate.indexing:
            return {
                "ok": False,
                "paused": True,
                "reason": "indexing_in_progress",
                "message": "Scene feedback paused while an index job holds JoyCaption.",
                "vision": self.vision_gate.status(),
            }

        preset = caption_preset or self.default_preset
        do_polish = self.default_polish if polish_with_chat is None else polish_with_chat

        if image_path is not None:
            path = Path(image_path)
            if not path.is_file():
                raise FileNotFoundError(str(path))
            camera_used = "offline_file"
        else:
            path = await self.capture_render(
                character_id=character_id,
                camera_source=camera_source,
                size=size,
            )
            camera_used = camera_source

        async with self.vision_gate.hold("feedback"):
            self._ensure_joycaption()
            caption = await asyncio.to_thread(
                self.joycaption.caption_path,
                path,
                caption_type=preset,
                instruction=instruction,
            )

        polish: str | None = None
        polish_error: str | None = None
        if do_polish:
            if self.chat is None:
                polish_error = "chat_service_unavailable"
            else:
                try:
                    polish = await self._polish(caption)
                except Exception as exc:
                    polish_error = str(exc)
                    logger.warning("scene feedback polish failed: %s", exc)

        self._analyze_count += 1
        result = {
            "ok": True,
            "mode": "ondemand",
            "character_id": character_id,
            "camera_source": camera_used,
            "caption_preset": preset,
            "instruction": instruction,
            "image_path": str(path),
            "caption": caption,
            "polish": polish,
            "polish_error": polish_error,
            "created_at": _utc_now(),
            "vision": self.vision_gate.status(),
        }
        self.latest = result
        return result

    async def _polish(self, caption: str) -> str:
        assert self.chat is not None
        result = await self.chat.chat(
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Scene description:\n{caption}\n\n"
                        "Write 1-3 short tips for the creator."
                    ),
                }
            ],
            persona="stheno",
            max_tokens=256,
            temperature=0.4,
            stream=False,
        )
        # Non-stream chat returns dict with message
        if isinstance(result, dict):
            msg = result.get("message") or result.get("assistant") or {}
            if isinstance(msg, dict):
                return str(msg.get("content") or "").strip()
            choices = result.get("choices")
            if isinstance(choices, list) and choices:
                return str((choices[0].get("message") or {}).get("content") or "").strip()
        return str(result).strip()

    def status(self) -> dict[str, Any]:
        watch = None
        if self._watch is not None:
            watch = {
                "running": self._watch_task is not None and not self._watch_task.done(),
                "character_id": self._watch.character_id,
                "debounce_s": self._watch.debounce_s,
                "caption_preset": self._watch.caption_preset,
                "camera_source": self._watch.camera_source,
                "instruction": self._watch.instruction,
                "polish_with_chat": self._watch.polish_with_chat,
            }
        return {
            "watch": watch,
            "latest": self.latest,
            "analyze_count": self._analyze_count,
            "vision": self.vision_gate.status(),
            "default_preset": self.default_preset,
            "default_debounce_s": self.default_debounce_s,
        }

    async def watch_start(
        self,
        *,
        character_id: int,
        caption_preset: str | None = None,
        camera_source: str = "studio_active",
        instruction: str | None = None,
        polish_with_chat: bool | None = None,
        size: int = 768,
        debounce_s: float | None = None,
    ) -> dict[str, Any]:
        await self.watch_stop()
        cfg = WatchConfig(
            character_id=character_id,
            caption_preset=caption_preset or self.default_preset,
            camera_source=camera_source,
            instruction=instruction,
            polish_with_chat=(
                self.default_polish if polish_with_chat is None else polish_with_chat
            ),
            size=size,
            debounce_s=float(debounce_s if debounce_s is not None else self.default_debounce_s),
        )
        if cfg.debounce_s < 5.0:
            cfg.debounce_s = 5.0
        self._watch = cfg
        self._watch_task = asyncio.create_task(self._watch_loop(), name="scene-feedback-watch")
        return {"ok": True, "watch": self.status()["watch"]}

    async def watch_stop(self) -> dict[str, Any]:
        task = self._watch_task
        self._watch_task = None
        self._watch = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return {"ok": True, "watch": None}

    async def _watch_loop(self) -> None:
        assert self._watch is not None
        cfg = self._watch
        logger.info(
            "Scene-feedback Watch started (char=%s, debounce=%.1fs)",
            cfg.character_id,
            cfg.debounce_s,
        )
        try:
            while self._watch is cfg:
                await asyncio.sleep(cfg.debounce_s)
                if self._watch is not cfg:
                    break
                if self.vision_gate.indexing:
                    logger.debug("Watch tick skipped – indexing in progress")
                    continue
                try:
                    result = await self.analyze(
                        character_id=cfg.character_id,
                        caption_preset=cfg.caption_preset,
                        camera_source=cfg.camera_source,
                        instruction=cfg.instruction,
                        polish_with_chat=cfg.polish_with_chat,
                        size=cfg.size,
                    )
                    if result.get("paused"):
                        continue
                    result["mode"] = "watch"
                    self.latest = result
                except asyncio.CancelledError:
                    raise
                except (BridgeError, JoyCaptionUnavailable, Exception) as exc:
                    logger.warning("Watch analyze failed: %s", exc)
                    self.latest = {
                        "ok": False,
                        "mode": "watch",
                        "error": str(exc),
                        "created_at": _utc_now(),
                    }
        except asyncio.CancelledError:
            logger.info("Scene-feedback Watch stopped")
            raise
