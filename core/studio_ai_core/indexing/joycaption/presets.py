"""JoyCaption presets for indexing (adapted from JoyCaptionTest)."""

from __future__ import annotations

DEFAULT_SYSTEM_PROMPT = "You are a helpful image captioner."

# Indexing default: concrete, searchable description
INDEX_CAPTION_TYPE = "Sachlich"

CAPTION_PROMPTS: dict[str, str] = {
    "Beschreibend (formal)": "Write a detailed description for this image.",
    "Beschreibend (locker)": "Write a descriptive caption for this image in a casual tone.",
    "Sachlich": (
        "Write a straightforward caption for this image. Begin with the main subject and medium. "
        "Mention pivotal elements—people, objects, scenery—using confident, definite language. "
        "Focus on concrete details like color, shape, texture, and spatial relationships. "
        "Show how elements interact. Omit mood and speculative wording. If text is present, quote it exactly. "
        "Note any watermarks, signatures, or compression artifacts. Never mention what's absent, resolution, "
        "or unobservable details. Vary your sentence structure and keep the description concise, "
        "without starting with “This image is…” or similar phrasing."
    ),
    "Versaut (NSFW)": (
        "Write a filthy, pornographic caption for this image—the kind of dirty talk someone "
        "would use in a horny group chat or sexting, not a neutral description. "
        "Use raw vulgar slang, profanity, and explicit sex talk."
    ),
}


def prompt_for(caption_type: str | None = None) -> str:
    key = caption_type or INDEX_CAPTION_TYPE
    return CAPTION_PROMPTS.get(key, CAPTION_PROMPTS[INDEX_CAPTION_TYPE])
