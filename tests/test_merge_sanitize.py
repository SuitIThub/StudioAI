"""Tests for merge sanitize (equal-weight conflict handling)."""

from __future__ import annotations

from studio_ai_core.indexing.merge import (
    apply_majority_stance,
    fallback_index_entry,
    majority_stance,
    sanitize_merge_entry,
)


def test_sanitize_drops_conflicting_arm_tags():
    entry = sanitize_merge_entry(
        {
            "description": "crouching with mixed arm cues",
            "tags": [
                "crouching",
                "all_fours",
                "arms_forward",
                "arms_crossed",
                "legs_bent",
                "symmetrical_legs",
                "close_feet",
            ],
            "synonyms": ["arms_forward_pose", "arms_crossed_pose", "crouching_pose"],
        }
    )
    assert "all_fours" in entry["tags"]
    assert "crouching" in entry["tags"]
    assert "arms_forward" not in entry["tags"]
    assert "arms_crossed" not in entry["tags"]
    assert "symmetrical_legs" not in entry["tags"]
    assert "arms_crossed_pose" not in entry["synonyms"]
    assert len(entry["tags"]) <= 8


def test_sanitize_keeps_arms_crossed_aliases():
    """arms_crossed + arms_over_chest are synonyms, not a conflict."""
    entry = sanitize_merge_entry(
        {
            "description": "Standing with arms crossed over chest",
            "tags": ["standing", "arms_crossed", "arms_over_chest", "arms_bent"],
            "synonyms": ["arms_crossed_over_chest", "standing_pose", "stomach_posecode"],
        }
    )
    assert "standing" in entry["tags"]
    assert "arms_crossed" in entry["tags"]
    assert "arms_over_chest" not in entry["tags"]
    assert "arms_bent" not in entry["tags"]
    assert "stomach_posecode" not in entry["synonyms"]


def test_sanitize_drops_conflicting_stances():
    entry = sanitize_merge_entry(
        {
            "description": "unclear stance",
            "tags": ["sitting", "all_fours", "legs_bent"],
            "synonyms": [],
        }
    )
    assert "sitting" not in entry["tags"]
    assert "all_fours" not in entry["tags"]
    assert "legs_bent" in entry["tags"]


def test_majority_all_fours_ignores_hanging_caption():
    tags = ["all_fours", "crouching", "arms_forward"]
    captions = {
        "front": "Hanging upside down with legs bent at the knees",
        "three_quarter": "All-fours stance with legs bent and arms extended forward",
    }
    assert majority_stance(tags, captions) == "all_fours"
    entry = apply_majority_stance(
        {
            "description": "Crouching with bent knees",
            "tags": ["crouching", "bent_knees", "arms_forward"],
            "synonyms": [],
        },
        posecode_tags=tags,
        captions=captions,
    )
    assert entry["tags"][0] == "all_fours"


def test_majority_lying_over_wrong_posecode_standing():
    # Two lying captions beat one standing (front) + wrong standing posecode → tie 2-2 → omit
    assert (
        majority_stance(
            ["standing", "rotated"],
            {
                "front": "Standing weight-bearing stance",
                "three_quarter": "Lying on back with legs extended",
                "one_quarter": "Lying on back, legs extended straight",
            },
        )
        is None
    )
    # With corrected posecode (lying), majority is clear
    assert (
        majority_stance(
            ["lying", "hips_pitched"],
            {
                "front": "Standing weight-bearing stance",
                "three_quarter": "Lying on back with legs extended",
                "one_quarter": "Lying on back, legs extended straight",
            },
        )
        == "lying"
    )


def test_majority_kneeling_from_captions():
    assert (
        majority_stance(
            ["standing", "legs_crossed"],
            {
                "front": "Kneeling pose with legs bent at the knees",
                "three_quarter": "Kneeling pose with weight-bearing stance",
            },
        )
        == "kneeling"
    )


def test_fallback_uses_majority_not_single_source():
    entry = fallback_index_entry(
        posecode_tags=["all_fours", "crouching"],
        captions={
            "front": "Hanging upside down with arms near the head",
            "three_quarter": "All-fours stance with arms extended forward",
        },
    )
    assert "all_fours" in entry["tags"]
    assert entry["tags"][0] == "all_fours"


def test_posecode_only_fallback_is_not_stance_only():
    entry = fallback_index_entry(
        posecode_tags=["standing", "left_arm_bent", "right_arm_raised"],
        captions={},
    )
    assert "standing" in entry["tags"]
    assert "left_arm_bent" in entry["tags"]
    desc = entry["description"].lower()
    assert "standing" in desc
    assert "arm" in desc
    assert desc != "standing"
    assert desc != "standing pose"


def test_enrich_replaces_bare_standing():
    from studio_ai_core.indexing.merge import enrich_thin_description

    entry = enrich_thin_description(
        {"description": "standing", "tags": ["standing"], "synonyms": []},
        posecode_tags=["standing", "left_arm_bent", "arms_crossed"],
    )
    assert "arm" in entry["description"].lower()
    assert entry["description"].lower() != "standing"
