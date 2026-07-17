"""Generate offline batch fixtures for Stage-3 FTS acceptance (no Studio required)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# (pose_id, stance tags via shin/thigh eulers, caption theme, search queries that should hit)
TEMPLATES = [
    ("kneeling_behind", "kneeling", 80, 50, 0, "woman kneeling from behind, arched back", ["kneeling from behind", "kneeling"]),
    ("standing_front", "standing", 5, 5, 0, "woman standing facing camera, casual dress", ["standing facing", "casual dress"]),
    ("squatting_side", "squatting", 40, 60, 40, "woman squatting in profile, hands on knees", ["squatting", "hands on knees"]),
    ("bent_forward", "bent", 20, 30, 0, "woman bent forward at the waist, long hair", ["bent forward", "long hair"]),
    ("arm_raised", "standing", 8, 8, 0, "woman standing with left arm raised overhead", ["arm raised", "overhead"]),
    ("sitting_floor", "kneeling", 90, 70, 10, "woman sitting on the floor with legs folded", ["sitting on the floor", "legs folded"]),
    ("all_fours", "kneeling", 85, 55, -20, "woman on all fours facing away from camera", ["all fours", "facing away"]),
    ("leaning_wall", "standing", 10, 15, 30, "woman leaning against a wall, looking aside", ["leaning against", "looking aside"]),
    ("lying_side", "lying", 15, 80, 5, "woman lying on her side on a bed", ["lying on her side", "on a bed"]),
    ("from_behind_stand", "standing", 12, 10, 50, "woman standing seen from behind, looking over shoulder", ["from behind", "over shoulder"]),
    ("yoga_stretch", "standing", 25, 35, 0, "woman in a yoga stretch with arms extended", ["yoga stretch", "arms extended"]),
    ("crouch_ready", "squatting", 45, 65, 15, "woman crouching ready pose in sportswear", ["crouching", "sportswear"]),
]


def _pose_compact(shin_x: float, thigh_x: float, hips_y: float, arm_raise: bool = False) -> str:
    lines = [
        f"cf_J_LegLow01_L: {shin_x},0,0",
        f"cf_J_LegLow01_R: {shin_x * 0.95},0,0",
        f"cf_J_LegUp00_L: {thigh_x},0,0",
        f"cf_J_LegUp00_R: {thigh_x * 0.9},0,0",
        f"cf_J_Spine01: {15 if shin_x > 60 else 5},0,0",
        f"cf_J_Hips: 0,{hips_y},0",
        "cf_J_ArmLow01_L: 10,0,0",
        "cf_J_ArmLow01_R: 12,0,0",
        f"cf_J_ArmUp00_L: {-50 if arm_raise else 0},0,0",
        "cf_J_ArmUp00_R: 0,0,0",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "testdata" / "batch_poses"),
    )
    parser.add_argument("--count", type=int, default=120)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    queries: list[dict] = []
    for i in range(args.count):
        base_id, _stance, shin, thigh, yaw, caption, qlist = TEMPLATES[i % len(TEMPLATES)]
        pose_id = f"{base_id}_{i:03d}"
        folder = out / pose_id
        folder.mkdir(exist_ok=True)
        arm_raise = "arm_raised" in base_id
        compact = _pose_compact(shin, thigh, yaw + (i % 7), arm_raise=arm_raise)
        (folder / "pose_compact.txt").write_text(compact, encoding="utf-8")
        # Unique searchable caption per pose
        full_caption = f"{caption}. variant {i}. pose id {pose_id}."
        captions = {
            "front": full_caption,
            "three_quarter": f"three-quarter view: {caption}",
        }
        (folder / "captions.json").write_text(
            json.dumps(captions, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        # Expected queries (first of each template + a few globals)
        if i < len(TEMPLATES):
            for q in qlist:
                queries.append({"query": q, "expect_contains": pose_id.split("_")[0], "pose_id": pose_id})

    # Extra fixed queries for acceptance (≥10)
    extra = [
        {"query": "kneeling from behind", "expect_contains": "kneeling"},
        {"query": "standing facing", "expect_contains": "standing"},
        {"query": "squatting", "expect_contains": "squatting"},
        {"query": "bent forward", "expect_contains": "bent"},
        {"query": "arm raised", "expect_contains": "arm"},
        {"query": "sitting on the floor", "expect_contains": "sitting"},
        {"query": "all fours", "expect_contains": "all"},
        {"query": "leaning against", "expect_contains": "leaning"},
        {"query": "lying on her side", "expect_contains": "lying"},
        {"query": "from behind", "expect_contains": "behind"},
        {"query": "yoga stretch", "expect_contains": "yoga"},
        {"query": "crouching sportswear", "expect_contains": "crouch"},
    ]
    queries.extend(extra)

    meta = {"count": args.count, "queries": queries}
    (out / "fts_queries.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Wrote {args.count} pose folders -> {out}")
    print(f"FTS query file -> {out / 'fts_queries.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
