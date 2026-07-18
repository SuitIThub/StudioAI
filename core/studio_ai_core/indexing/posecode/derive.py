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
    return (v + 180.0) % 360.0 - 180.0


def bend_mag(*axes: float) -> float:
    """Largest absolute bend on any provided axis (after normalize)."""
    return max((abs(norm_deg(a)) for a in axes), default=0.0)


def derive_posecode(pose_compact: str) -> PosecodeResult:
    """
    Deterministic posture tags from local bone eulers.

    HS2 local FK often reports angles in 0..360 — always normalize before thresholds.
    Lying often keeps nearly straight legs with hips pitched ~90°.
    Kneeling / seiza often shows modest shin-X but large shin Y/Z (legs folded under).
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
    spine01 = _find(bones, "cf_J_Spine01", "cf_j_spine01")
    spine02 = _find(bones, "cf_J_Spine02", "cf_j_spine02")
    spine = spine01 or spine02
    hips = _find(bones, "cf_J_Hips", "cf_j_hips", "cf_J_Kosi01")
    left_arm = _find(bones, "cf_J_ArmLow01_L", "cf_j_armlow01_l")
    right_arm = _find(bones, "cf_J_ArmLow01_R", "cf_j_armlow01_r")
    left_up = _find(bones, "cf_J_ArmUp00_L", "cf_j_armup00_l")
    right_up = _find(bones, "cf_J_ArmUp00_R", "cf_j_armup00_r")
    char_guide = _find(bones, "char_guide")
    char_root = _find(bones, "char_root")

    shin_mags = [bend_mag(b.x) for b in (left_shin, right_shin) if b is not None]
    thigh_mags = [bend_mag(b.x) for b in (left_thigh, right_thigh) if b is not None]
    shin_fold_mags = [
        bend_mag(b.y, b.z) for b in (left_shin, right_shin) if b is not None
    ]
    max_shin = max(shin_mags, default=0.0)
    max_thigh = max(thigh_mags, default=0.0)
    max_shin_fold = max(shin_fold_mags, default=0.0)
    details["max_shin_x"] = max_shin
    details["max_thigh_x"] = max_thigh
    details["max_shin_fold"] = max_shin_fold

    root_pitch = 0.0
    if char_guide is not None and any(
        abs(norm_deg(v)) >= 1.0 for v in (char_guide.x, char_guide.y, char_guide.z)
    ):
        root_pitch = norm_deg(char_guide.x)
    elif char_root is not None and any(
        abs(norm_deg(v)) >= 1.0 for v in (char_root.x, char_root.y, char_root.z)
    ):
        root_pitch = norm_deg(char_root.x)
    details["root_pitch"] = root_pitch
    root_pitched_forward = abs(root_pitch) >= 45.0
    details["root_pitched_forward"] = root_pitched_forward

    hips_pitch = abs(norm_deg(hips.x)) if hips is not None else 0.0
    details["hips_pitch"] = hips_pitch
    hips_pitched_forward = hips_pitch >= 55.0
    details["hips_pitched_forward"] = hips_pitched_forward

    left_up_x = abs(norm_deg(left_up.x)) if left_up else 0.0
    right_up_x = abs(norm_deg(right_up.x)) if right_up else 0.0
    both_arms_reaching = left_up_x >= 50 and right_up_x >= 50
    details["left_armup_x"] = left_up_x
    details["right_armup_x"] = right_up_x
    details["both_arms_reaching"] = both_arms_reaching

    spine_x = 0.0
    if spine01 is not None:
        spine_x = norm_deg(spine01.x)
    if spine02 is not None:
        s2 = norm_deg(spine02.x)
        if abs(s2) > abs(spine_x):
            spine_x = s2
    details["spine_x"] = spine_x

    tip_mag = max(abs(root_pitch) if root_pitched_forward else 0.0, hips_pitch)
    legs_straightish = max_thigh < 45 and max_shin < 40
    tipped = both_arms_reaching or root_pitched_forward or hips_pitched_forward
    # Kneeling / seiza: shins folded under (large local Y/Z) even when shin-X is modest
    kneel_folded = max_shin_fold >= 90 and max_thigh >= 15 and max_shin < 70

    # 1) Lying: body tipped ~90° with mostly straight legs (supine/prone FK looks "standing")
    if tip_mag >= 70 and legs_straightish:
        tags.append("lying")
        if hips_pitch >= 70:
            tags.append("hips_pitched")
    # 2) All-fours / crawl
    elif max_thigh >= 45 and max_shin >= 40 and tipped:
        tags.append("all_fours")
        tags.append("crouching")
        if root_pitched_forward:
            tags.append("root_pitched")
        if hips_pitched_forward and not root_pitched_forward:
            tags.append("hips_pitched")
    # 3) Sitting (chair-like: flexed thighs + bent knees, not folded-under shins)
    elif max_thigh >= 55 and max_shin >= 40 and not kneel_folded:
        tags.append("sitting")
    # 4) Kneeling
    elif max_shin >= 70 or kneel_folded:
        tags.append("kneeling")
    elif max_shin >= 35 or max_thigh >= 55:
        tags.append("squatting")
    else:
        tags.append("standing")

    floor_pose = any(t in tags for t in ("lying", "all_fours", "prone", "supine"))

    # Crossed legs: only upright / sitting
    if not floor_pose and "kneeling" not in tags and left_thigh is not None and right_thigh is not None:
        dy = abs(norm_deg(left_thigh.y) - norm_deg(right_thigh.y))
        dz = abs(norm_deg(left_thigh.z) - norm_deg(right_thigh.z))
        details["thigh_y_asym"] = dy
        details["thigh_z_asym"] = dz
        if dy >= 30 or dz >= 30:
            tags.append("legs_crossed")

    if spine is not None:
        sy = norm_deg(spine.y)
        sz = norm_deg(spine.z)
        details["spine_y"] = sy
        details["spine_z"] = sz
        if spine_x >= 20 or ("all_fours" in tags and spine_x >= 5):
            tags.append("bent_forward")
        elif spine_x <= -18 and "lying" not in tags:
            tags.append("arched_back")
        if abs(sz) >= 20:
            tags.append("leaning_side")

    yaw = 0.0
    if hips is not None:
        yaw = norm_deg(hips.y)
        details["hips_y"] = yaw
    elif spine is not None:
        yaw = norm_deg(spine.y)
    # Hips yaw on lying/all-fours is body orientation on the floor, not a standing turn
    unusual_rotation = (not floor_pose) and abs(yaw) >= 35
    details["unusual_rotation"] = unusual_rotation
    if unusual_rotation:
        tags.append("rotated")
        tags.append("turned_left" if yaw > 0 else "turned_right")

    for side, low, up in (
        ("left", left_arm, left_up),
        ("right", right_arm, right_up),
    ):
        if low is not None and bend_mag(low.x, low.y, low.z) >= 50:
            tags.append(f"{side}_arm_bent")
        if up is None:
            continue
        ux = norm_deg(up.x)
        if "all_fours" in tags and abs(ux) >= 50:
            tags.append(f"{side}_arm_forward")
        elif ux <= -40:
            tags.append(f"{side}_arm_raised")

    if "all_fours" in tags:
        tags.append("arms_forward")
    elif (
        "lying" not in tags
        and left_arm is not None
        and right_arm is not None
        and bend_mag(left_arm.x, left_arm.y, left_arm.z) >= 50
        and bend_mag(right_arm.x, right_arm.y, right_arm.z) >= 50
        and left_up_x < 40
        and right_up_x < 40
        and "left_arm_raised" not in tags
        and "right_arm_raised" not in tags
    ):
        # Both elbows bent, upper arms not reaching/raised → crossed / folded on chest
        tags.append("arms_crossed")

    seen: set[str] = set()
    uniq: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            uniq.append(t)

    text = "pose with " + ", ".join(uniq) if uniq else "neutral pose"
    return PosecodeResult(text=text, tags=uniq, raw=pose_compact, details=details)


def needs_one_quarter(result: PosecodeResult) -> bool:
    if result.details.get("unusual_rotation"):
        return True
    # Extra angle helps when front view of lying looks like standing to VLMs
    return "lying" in result.tags
