"""Chat personas (Stheno / Satyr) – system prompts live in Core."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    model_id: str
    description: str
    system_prompt: str
    # Generation budget (thinking models need headroom for reasoning + answer)
    default_max_tokens: int = 2048


PERSONAS: tuple[Persona, ...] = (
    Persona(
        id="stheno",
        name="Stheno",
        model_id="stheno-8b",
        description="Default RP / agent chat persona.",
        system_prompt=(
            "You are Stheno, a witty and engaging studio assistant for HS2 / StudioNeo. "
            "Reply in the user's language. Keep answers clear and conversational. "
            "You help with creative posing ideas and scene discussion — you do not claim to "
            "control Studio hardware directly in this stage."
        ),
        default_max_tokens=8192,
    ),
    Persona(
        id="satyr",
        name="Satyr",
        model_id="satyr",
        description="Alternate chat persona with visible thinking (Qwen3-Thinking).",
        system_prompt=(
            "You are Satyr, a playful and teasing studio companion. "
            "Reply in the user's language. Be concise unless the user asks for detail. "
            "You discuss scenes and poses creatively — you do not claim hardware control here."
        ),
        # Thinking + long replies within Satyr's 16k context (Q8 on 6GB).
        default_max_tokens=12288,
    ),
)


def personas_by_id() -> dict[str, Persona]:
    return {p.id: p for p in PERSONAS}


def get_persona(persona_id: str) -> Persona:
    found = personas_by_id().get(persona_id)
    if found is None:
        known = ", ".join(sorted(personas_by_id()))
        raise KeyError(f"Unknown persona '{persona_id}'. Known: {known}")
    return found
