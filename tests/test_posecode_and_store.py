"""Tests for rule-based posecode and FTS store."""

from __future__ import annotations

from pathlib import Path

from studio_ai_core.indexing.posecode import derive_posecode
from studio_ai_core.indexing.posecode.derive import norm_deg
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
    assert "legs_crossed" in r.tags
    assert r.details.get("unusual_rotation") is False
    assert "leaning_side" not in r.tags


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
