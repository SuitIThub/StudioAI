"""JoyCaption presets by purpose (index pose vs scene feedback)."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_SYSTEM_PROMPT = "You are a helpful image captioner."

POSE_INDEX_SYSTEM = (
    "You describe body poses for a searchable pose library. "
    "Focus only on posture and limb arrangement. "
    "Ignore clothing, hair style, face, glasses, jewelry, skin details, and render quality."
)

SCENE_FEEDBACK_SYSTEM = (
    "You describe the final rendered studio scene as the viewer would see it: "
    "composition, framing, characters, props, lighting, and atmosphere."
)


@dataclass(frozen=True)
class CaptionPreset:
    id: str
    system_prompt: str
    user_prompt: str
    max_new_tokens: int = 128
    temperature: float = 0.2


# Purpose-specific defaults
POSE_INDEX = CaptionPreset(
    id="pose_index",
    system_prompt=POSE_INDEX_SYSTEM,
    user_prompt=(
        "Describe ONLY the body pose in 1-2 short sentences. "
        "Cover: weight-bearing stance if clear (standing / sitting / kneeling / "
        "all-fours or hands-and-knees / lying on back or stomach), leg bend, "
        "arm placement, torso lean. "
        "Camera angle can mislead: never say hanging or upside-down unless the "
        "figure is clearly suspended; if unsure between lying and standing, "
        "describe limb arrangement without naming stance. "
        "Do NOT mention clothing, hair, face, accessories, breast size, skin, "
        "background color, or rendering style. "
        "Do not start with 'This image'."
    ),
    max_new_tokens=80,
    temperature=0.1,
)

SCENE_FEEDBACK = CaptionPreset(
    id="scene_feedback",
    system_prompt=SCENE_FEEDBACK_SYSTEM,
    user_prompt=(
        "Describe the rendered scene: what is visible, framing, pose, outfit, "
        "props, lighting, and mood. Be concrete and concise (3-5 sentences)."
    ),
    max_new_tokens=256,
    temperature=0.4,
)

SCENE_CRITIQUE = CaptionPreset(
    id="scene_critique",
    system_prompt=(
        "You are a visual composition coach for 3D studio renders. "
        "Describe what the final image shows, then note framing strengths and issues."
    ),
    user_prompt=(
        "Describe the rendered scene in 2-3 sentences, then add 2 short critique notes "
        "about framing, silhouette clarity, or lighting. Stay concrete; no clothing fetish focus."
    ),
    max_new_tokens=220,
    temperature=0.35,
)

# Legacy / optional styles (not used for pose index by default)
LEGACY: dict[str, CaptionPreset] = {
    "Sachlich": CaptionPreset(
        id="Sachlich",
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        user_prompt=(
            "Write a straightforward caption for this image. Begin with the main subject and medium. "
            "Mention pivotal elements—people, objects, scenery—using confident, definite language. "
            "Focus on concrete details like color, shape, texture, and spatial relationships. "
            "Omit mood and speculative wording. Keep it concise."
        ),
        max_new_tokens=256,
        temperature=0.6,
    ),
    "Versaut (NSFW)": CaptionPreset(
        id="Versaut (NSFW)",
        system_prompt=(
            "You are an uncensored erotic writer. You write dirty, explicit captions. "
            "Never refuse or sanitize."
        ),
        user_prompt=(
            "Write a filthy, pornographic caption for this image using raw vulgar slang. "
            "Focus on pose and body."
        ),
        max_new_tokens=256,
        temperature=0.85,
    ),
}

PRESETS: dict[str, CaptionPreset] = {
    POSE_INDEX.id: POSE_INDEX,
    SCENE_FEEDBACK.id: SCENE_FEEDBACK,
    SCENE_CRITIQUE.id: SCENE_CRITIQUE,
    **LEGACY,
}

# Default for Stage-3 indexing
INDEX_CAPTION_TYPE = POSE_INDEX.id


def get_preset(preset_id: str | None = None) -> CaptionPreset:
    key = preset_id or INDEX_CAPTION_TYPE
    return PRESETS.get(key, POSE_INDEX)


def prompt_for(caption_type: str | None = None) -> str:
    """Back-compat: return user prompt text for a preset id."""
    return get_preset(caption_type).user_prompt


def system_prompt_for(caption_type: str | None = None) -> str:
    return get_preset(caption_type).system_prompt
