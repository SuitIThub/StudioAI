"""Model role profiles – mapping tasks to models (source of truth in Core)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelProfile:
    id: str
    roles: tuple[str, ...]
    grammar: bool = False
    capabilities: tuple[str, ...] = field(default_factory=tuple)


# Stage 1: technical (Qwen) for structured JSON; chat models for RP/dialog.
# posecode_interpret is intentionally NOT a model role – that stays rule-based in Core later.
DEFAULT_PROFILES: tuple[ModelProfile, ...] = (
    ModelProfile(
        id="qwen-technical",
        roles=("index_merge", "structured_json"),
        grammar=True,
        capabilities=("text",),
    ),
    ModelProfile(
        id="stheno-8b",
        roles=("agent_chat", "scene_feedback_polish"),
        grammar=False,
        capabilities=("text",),
    ),
    ModelProfile(
        id="satyr",
        roles=("agent_chat",),
        grammar=False,
        capabilities=("text",),
    ),
)


def profiles_by_id() -> dict[str, ModelProfile]:
    return {p.id: p for p in DEFAULT_PROFILES}


def profile_for_role(role: str) -> ModelProfile | None:
    for profile in DEFAULT_PROFILES:
        if role in profile.roles:
            return profile
    return None
