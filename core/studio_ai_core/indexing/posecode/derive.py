"""Rule-based posecode: pose_compact → tags + text (no LLM)."""

from __future__ import annotations

from dataclasses import dataclass

from studio_ai_core.indexing.posecode.parse import BoneEuler, parse_pose_compact


@dataclass(frozen=True)
class PosecodeResult:
    text: str
    tags: list[str]
    raw: str
    details: dict[str, float | str | bool]


def _find(bones: dict[str, BoneEuler], *names: str) -> BoneEuler | None:
    lower = {k.lower(): v for k, v in bones.items()}
    for name in names:
        hit = lower.get(name.lower())
        if hit is not None:
            return hit
    return None


def norm_deg(v: float) -> float:
    """Map HS2 euler (often 0..360) into signed [-180, 180]."""
    x = (v + 180.0) % 360.0 - 180.0
    return x


def bend_mag(*axes: float) -> float:
    """Largest absolute bend on any provided axis (after normalize)."""
    return max((abs(norm_deg(a)) for a in axes), default=0.0)


def derive_posecode(pose_compact: str) -> PosecodeResult:
    """
    Deterministic posture tags from local bone eulers.

    HS2 local FK often reports angles in 0..360 — always normalize before thresholds.
    Sitting (chair) and kneeling both bend the knee; thigh flexion separates them.
    """
    bones = parse_pose_compact(pose_compact)
    tags: list[str] = []
    details: dict[str, float | str | bool] = {"bone_count": float(len(bones))}

    if not bones:
        return PosecodeResult(
            text="empty pose",
            tags=["empty"],
            raw=pose_compact or "",
            details=details,
        )

    left_shin = _find(bones, "cf_J_LegLow01_L", "cf_j_leglow01_l")
    right_shin = _find(bones, "cf_J_LegLow01_R", "cf_j_leglow01_r")
    left_thigh = _find(bones, "cf_J_LegUp00_L", "cf_j_legup00_l")
    right_thigh = _find(bones, "cf_J_LegUp00_R", "cf_j_legup00_r")
    spine = _find(bones, "cf_J_Spine01", "cf_j_spine01", "cf_J_Spine02")
    hips = _find(bones, "cf_J_Hips", "cf_j_hips", "cf_J_Kosi01")
    left_arm = _find(bones, "cf_J_ArmLow01_L", "cf_j_armlow01_l")
    right_arm = _find(bones, "cf_J_ArmLow01_R", "cf_j_armlow01_r")
    left_up = _find(bones, "cf_J_ArmUp00_L", "cf_j_armup00_l")
    right_up = _find(bones, "cf_J_ArmUp00_R", "cf_j_armup00_r")

    shin_mags = [bend_mag(b.x) for b in (left_shin, right_shin) if b is not None]
    thigh_mags = [bend_mag(b.x) for b in (left_thigh, right_thigh) if b is not None]
    max_shin = max(shin_mags, default=0.0)
    max_thigh = max(thigh_mags, default=0.0)
    details["max_shin_x"] = max_shin
    details["max_thigh_x"] = max_thigh

    # Sitting: thighs flexed toward horizontal + knees bent (chair / floor sit).
    # Kneeling: strong knee bend with thighs more upright (less thigh flexion).
    if max_thigh >= 55 and max_shin >= 40:
        tags.append("sitting")
    elif max_shin >= 70:
        tags.append("kneeling")
    elif max_shin >= 35 or max_thigh >= 55:
        tags.append("squatting")
    else:
        tags.append("standing")

    # Crossed legs: asymmetric thigh twist between sides
    if left_thigh is not None and right_thigh is not None:
        dy = abs(norm_deg(left_thigh.y) - norm_deg(right_thigh.y))
        dz = abs(norm_deg(left_thigh.z) - norm_deg(right_thigh.z))
        details["thigh_y_asym"] = dy
        details["thigh_z_asym"] = dz
        if dy >= 30 or dz >= 30:
            tags.append("legs_crossed")

    # Lean / bend from spine (normalized)
    if spine is not None:
        sx, sy, sz = norm_deg(spine.x), norm_deg(spine.y), norm_deg(spine.z)
        details["spine_x"] = sx
        details["spine_y"] = sy
        details["spine_z"] = sz
        if sx >= 25:
            tags.append("bent_forward")
        elif sx <= -20:
            tags.append("arched_back")
        if abs(sz) >= 20:
            tags.append("leaning_side")

    # Hip / body yaw – unusual rotation → optional one_quarter capture
    yaw = 0.0
    if hips is not None:
        yaw = norm_deg(hips.y)
        details["hips_y"] = yaw
    elif spine is not None:
        yaw = norm_deg(spine.y)
        details["spine_y"] = yaw
    unusual_rotation = abs(yaw) >= 35
    details["unusual_rotation"] = unusual_rotation
    if unusual_rotation:
        tags.append("rotated")
        if yaw > 0:
            tags.append("turned_left")
        else:
            tags.append("turned_right")

    # Arms: elbow bend can live on X, Y, or Z depending on FK setup
    for side, low, up in (
        ("left", left_arm, left_up),
        ("right", right_arm, right_up),
    ):
        if low is not None and bend_mag(low.x, low.y, low.z) >= 50:
            tags.append(f"{side}_arm_bent")
        if up is not None and norm_deg(up.x) <= -40:
            tags.append(f"{side}_arm_raised")

    seen: set[str] = set()
    uniq: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            uniq.append(t)

    text = "pose with " + ", ".join(uniq) if uniq else "neutral pose"
    return PosecodeResult(text=text, tags=uniq, raw=pose_compact, details=details)


def needs_one_quarter(result: PosecodeResult) -> bool:
    return bool(result.details.get("unusual_rotation"))
