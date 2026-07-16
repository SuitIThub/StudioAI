"""Role routing: chat → Stheno/Satyr; structured → Qwen + GBNF."""

from __future__ import annotations

from studio_ai_core.personas import Persona, get_persona
from studio_ai_core.profiles import ModelProfile, profile_for_role, profiles_by_id


class RoutingError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def resolve_chat_target(
    *,
    persona_id: str | None = None,
    model_id: str | None = None,
    default_persona: str = "stheno",
) -> tuple[str, Persona | None]:
    """Return (model_id, persona_or_none) for agent chat."""
    if model_id:
        profiles = profiles_by_id()
        if model_id not in profiles:
            raise RoutingError(f"Unknown model '{model_id}'")
        profile = profiles[model_id]
        if "agent_chat" not in profile.roles:
            raise RoutingError(
                f"Model '{model_id}' is not a chat model (roles={list(profile.roles)}). "
                "Use /v1/structured for Qwen+GBNF."
            )
        persona = None
        if persona_id:
            persona = get_persona(persona_id)
            if persona.model_id != model_id:
                raise RoutingError(
                    f"Persona '{persona_id}' maps to '{persona.model_id}', not '{model_id}'"
                )
        return model_id, persona

    pid = persona_id or default_persona
    try:
        persona = get_persona(pid)
    except KeyError as exc:
        raise RoutingError(str(exc)) from exc
    return persona.model_id, persona


def resolve_structured_target(model_id: str | None = None) -> ModelProfile:
    if model_id:
        profile = profiles_by_id().get(model_id)
        if profile is None:
            raise RoutingError(f"Unknown model '{model_id}'")
        if "structured_json" not in profile.roles and "index_merge" not in profile.roles:
            raise RoutingError(
                f"Model '{model_id}' is not a technical/structured model. "
                "Use a chat persona via /v1/chat."
            )
        return profile

    profile = profile_for_role("structured_json")
    if profile is None:
        raise RoutingError("No model profile for role 'structured_json'")
    return profile
