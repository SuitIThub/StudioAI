"""Tests for rule-based posecode and FTS store."""

from __future__ import annotations

from pathlib import Path

from studio_ai_core.indexing.posecode import derive_posecode
from studio_ai_core.indexing.posecode.derive import norm_deg
from studio_ai_core.indexing.posecode.parse import format_pose_compact_from_regions
from studio_ai_core.indexing.store import PoseIndexStore


# Kneeling: strong knee bend, thighs relatively upright (|thigh_x| < 55)
KNEELING = """
cf_J_LegLow01_L: 85,0,0
cf_J_LegLow01_R: 82,0,0
cf_J_LegUp00_L: 40,0,0
cf_J_LegUp00_R: 35,0,0
cf_J_Spine01: 10,0,0
cf_J_Hips: 0,5,0
"""

STANDING = """
cf_J_LegLow01_L: 5,0,0
cf_J_LegLow01_R: 4,0,0
cf_J_LegUp00_L: 3,0,0
cf_J_LegUp00_R: 2,0,0
cf_J_Spine01: 0,0,0
cf_J_Hips: 0,0,0
"""

ROTATED = """
cf_J_LegLow01_L: 8,0,0
cf_J_LegLow01_R: 7,0,0
cf_J_LegUp00_L: 5,0,0
cf_J_LegUp00_R: 4,0,0
cf_J_Hips: 0,45,0
"""

# Real capture: chair sit, crossed legs (HS2 0..360 eulers)
SITTING_CROSSED = """
cf_J_Spine01: 8.7,0.2,351.9
cf_J_Spine02: 6.8,1.2,359.6
cf_J_Spine03: 0,0,0
cf_J_Shoulder_L: 4.9,11,9
cf_J_ArmUp00_L: 0.2,17.8,73.3
cf_J_ArmLow01_L: 356.6,69.8,357
cf_J_Shoulder_R: 4.4,1.1,2.9
cf_J_ArmUp00_R: 353.2,339.7,309.3
cf_J_ArmLow01_R: 0,282.8,340.5
cf_J_LegUp00_L: 287.8,302.7,66.3
cf_J_LegLow01_L: 69,0,0
cf_J_LegUp00_R: 291,330.8,10.4
cf_J_LegLow01_R: 71.2,0,0
"""

# Real capture: all-fours / crouch (weight on hands)
ALL_FOURS = """
cf_J_Spine01: 5.9,0,0
cf_J_Spine02: 349.6,0,0
cf_J_Spine03: 0,0,0
cf_J_Shoulder_L: 0,350,0
cf_J_ArmUp00_L: 297.4,320.9,110.1
cf_J_ArmLow01_L: 0,87.6,0
cf_J_Shoulder_R: 0,10,0
cf_J_ArmUp00_R: 297.1,8.9,265.2
cf_J_ArmLow01_R: 346.3,261.5,358.9
cf_J_LegUp00_L: 284,336.1,5.9
cf_J_LegLow01_L: 62.7,0,0
cf_J_LegUp00_R: 309,199.6,208.6
cf_J_LegLow01_R: 54.6,188.6,185.2
"""


def test_norm_deg_wraps_hs2():
    assert abs(norm_deg(291.0) - (-69.0)) < 0.01
    assert abs(norm_deg(351.9) - (-8.1)) < 0.01


def test_kneeling_tags():
    r = derive_posecode(KNEELING)
    assert "kneeling" in r.tags
    assert "sitting" not in r.tags
    assert "standing" not in r.tags


def test_standing_tags():
    r = derive_posecode(STANDING)
    assert "standing" in r.tags


def test_sitting_crossed_not_kneeling():
    r = derive_posecode(SITTING_CROSSED)
    assert "sitting" in r.tags
    assert "kneeling" not in r.tags
    assert "all_fours" not in r.tags
    assert "legs_crossed" in r.tags
    assert r.details.get("unusual_rotation") is False
    assert "leaning_side" not in r.tags


def test_all_fours_not_sitting():
    r = derive_posecode(ALL_FOURS)
    assert "all_fours" in r.tags
    assert "crouching" in r.tags
    assert "sitting" not in r.tags
    assert "legs_crossed" not in r.tags
    assert "arms_forward" in r.tags


# Same leg bend as sitting, but character guide pitched forward (no arm reach needed)
ALL_FOURS_VIA_ROOT = """
char_guide: 80,0,0
cf_J_LegUp00_L: 287.8,0,0
cf_J_LegLow01_L: 69,0,0
cf_J_LegUp00_R: 291,0,0
cf_J_LegLow01_R: 71.2,0,0
cf_J_ArmUp00_L: 5,0,0
cf_J_ArmUp00_R: 5,0,0
cf_J_Spine01: 5,0,0
"""

# Real capture: tip is in FK hips while Studio guide is identity
ALL_FOURS_VIA_HIPS = """
char_guide: 0,0,0
char_root: 0,0,0
cf_J_Hips: 84.6,332.2,150.9
cf_J_LegUp00_L: 284,336.1,5.9
cf_J_LegLow01_L: 62.7,0,0
cf_J_LegUp00_R: 309,199.6,208.6
cf_J_LegLow01_R: 54.6,188.6,185.2
cf_J_ArmUp00_L: 5,0,0
cf_J_ArmUp00_R: 5,0,0
cf_J_Spine01: 5.9,0,0
"""


def test_all_fours_from_root_pitch():
    r = derive_posecode(ALL_FOURS_VIA_ROOT)
    assert "all_fours" in r.tags
    assert "sitting" not in r.tags
    assert r.details.get("root_pitched_forward") is True


def test_all_fours_from_hips_pitch():
    r = derive_posecode(ALL_FOURS_VIA_HIPS)
    assert "all_fours" in r.tags
    assert "sitting" not in r.tags
    assert r.details.get("hips_pitched_forward") is True
    assert r.details.get("root_pitched_forward") is False


def test_format_pose_compact_includes_root():
    compact = format_pose_compact_from_regions(
        {
            "root": {
                "guide_rot_euler": [75.0, 10.0, 0.0],
                "world_rot_euler": [70.0, 5.0, 0.0],
            },
            "regions": {
                "hips": [{"bone": "cf_J_Hips", "rot_euler": [0, 12, 0]}],
            },
        }
    )
    assert "char_guide: 75.0,10.0,0.0" in compact
    assert "char_root: 70.0,5.0,0.0" in compact
    assert "cf_J_Hips: 0,12,0" in compact


# Real capture: supine / on back (hips tipped ~90°, legs nearly straight)
LYING_SUPINE = """
char_guide: 0,0,0
char_root: 0,0,0
cf_J_Spine01: 344.5,0.3,357.4
cf_J_Spine02: 16.2,0.3,0.1
cf_J_Hips: 272,199,162.2
cf_J_ArmUp00_L: 8.9,52.7,69.1
cf_J_ArmLow01_L: 1.5,67.4,355.6
cf_J_ArmUp00_R: 16.7,314.5,287.6
cf_J_ArmLow01_R: 0,259.5,7.4
cf_J_LegUp00_L: 3.8,14.6,5.1
cf_J_LegLow01_L: 8.3,0,0
cf_J_LegUp00_R: 0.1,347.7,3.6
cf_J_LegLow01_R: 18.4,0,0
"""

# Real capture: kneeling / seiza (modest shin-X, large shin Y/Z fold)
KNEELING_SEIZA = """
char_guide: 0,0,0
char_root: 0,0,0
cf_J_Spine01: 24.4,0.3,2
cf_J_Spine02: 13.8,350.6,358.6
cf_J_Hips: 4.3,0,0
cf_J_ArmUp00_L: 313.8,11.2,69.9
cf_J_ArmLow01_L: 0,146.4,4.3
cf_J_ArmUp00_R: 321.6,343.3,290
cf_J_ArmLow01_R: 358.3,306.9,348.9
cf_J_LegUp00_L: 332.5,32.5,341.7
cf_J_LegLow01_L: 28.7,179.3,174.1
cf_J_LegUp00_R: 327.3,331.6,6.7
cf_J_LegLow01_R: 27.5,179,187.4
"""


def test_lying_supine_not_standing():
    r = derive_posecode(LYING_SUPINE)
    assert "lying" in r.tags
    assert "standing" not in r.tags
    assert "rotated" not in r.tags
    assert r.details.get("unusual_rotation") is False


def test_kneeling_seiza_folded_shins():
    r = derive_posecode(KNEELING_SEIZA)
    assert "kneeling" in r.tags
    assert "standing" not in r.tags
    assert "legs_crossed" not in r.tags


STANDING_ARMS_CROSSED = """
char_guide: 0,0,0
char_root: 0,0,0
cf_J_Spine01: 5.8,0,357.9
cf_J_Spine02: 343.5,0,0
cf_J_Hips: 0,0,0
cf_J_ArmUp00_L: 357.7,76,54.5
cf_J_ArmLow01_L: 1.5,99.4,22.1
cf_J_ArmUp00_R: 6.7,276.9,299.9
cf_J_ArmLow01_R: 357.5,255.2,14.7
cf_J_LegUp00_L: 341.3,349,349.5
cf_J_LegLow01_L: 17.5,0,0
cf_J_LegUp00_R: 348.9,0,359.1
cf_J_LegLow01_R: 14,0,0
"""


def test_standing_arms_crossed():
    r = derive_posecode(STANDING_ARMS_CROSSED)
    assert "standing" in r.tags
    assert "arms_crossed" in r.tags
    assert "all_fours" not in r.tags


def test_unusual_rotation_one_quarter_flag():
    r = derive_posecode(ROTATED)
    assert r.details.get("unusual_rotation") is True
    assert "rotated" in r.tags


def test_fts_search(tmp_path: Path):
    store = PoseIndexStore(tmp_path / "idx.sqlite")
    store.upsert(
        pose_id="pose_kneel_01",
        path="/tmp/a",
        description="woman kneeling from behind on a wooden floor",
        tags=["kneeling", "from_behind"],
        synonyms=["on knees", "rear view"],
        posecode_raw=KNEELING,
        posecode_text="pose with kneeling",
        posecode_tags=["kneeling"],
        captions={"front": "kneeling from behind"},
    )
    store.upsert(
        pose_id="pose_stand_01",
        path="/tmp/b",
        description="woman standing facing the camera in a red dress",
        tags=["standing", "front"],
        synonyms=["upright"],
        posecode_raw=STANDING,
        posecode_text="pose with standing",
        posecode_tags=["standing"],
        captions={"front": "standing facing camera"},
    )
    hits = store.search("kneeling from behind")
    assert hits
    assert hits[0].pose_id == "pose_kneel_01"
    hits2 = store.search("red dress")
    assert any(h.pose_id == "pose_stand_01" for h in hits2)
    store.close()


def test_fts_matches_caption_not_just_description(tmp_path: Path):
    store = PoseIndexStore(tmp_path / "idx.sqlite")
    store.upsert(
        pose_id="kneeling_behind_000",
        path=None,
        description="kneeling pose",
        tags=["kneeling", "behind"],
        synonyms=[],
        posecode_raw=KNEELING,
        posecode_text="pose with kneeling",
        posecode_tags=["kneeling"],
        captions={"front": "woman kneeling from behind, arched back"},
    )
    hits = store.search("kneeling from behind")
    assert hits
    assert hits[0].pose_id == "kneeling_behind_000"
    store.close()
