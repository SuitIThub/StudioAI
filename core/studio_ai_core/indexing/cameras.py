"""Camera view policy for indexing captures."""

from __future__ import annotations

from dataclasses import dataclass

from studio_ai_core.indexing.posecode.derive import PosecodeResult, needs_one_quarter


@dataclass(frozen=True)
class CameraPolicy:
    always: tuple[str, ...] = ("front", "three_quarter")
    optional: tuple[str, ...] = ("one_quarter",)
    one_quarter_mode: str = "auto"  # auto | always | off
    # StudioPoseBridge supports numeric angles; map one_quarter → degrees until preset exists
    one_quarter_angle: str = "45"


def resolve_views(policy: CameraPolicy, posecode: PosecodeResult | None = None) -> list[str]:
    views = list(policy.always)
    mode = (policy.one_quarter_mode or "auto").lower()
    if mode == "always":
        views.append("one_quarter")
    elif mode == "off":
        pass
    elif mode == "auto" and posecode is not None and needs_one_quarter(posecode):
        views.append("one_quarter")
    # dedupe
    seen: set[str] = set()
    out: list[str] = []
    for v in views:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def bridge_angle_for_view(view: str, policy: CameraPolicy) -> str:
    """Map logical view name to Bridge screenshot angle param."""
    if view in ("front", "front_full"):
        return "front"
    if view == "three_quarter":
        return "three_quarter"
    if view == "one_quarter":
        return policy.one_quarter_angle
    return view
