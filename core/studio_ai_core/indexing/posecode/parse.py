"""Parse pose_compact text into bone → euler degrees."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_LINE_EULER = re.compile(
    r"^(?P<bone>\S+)\s*:\s*(?P<x>-?\d+(?:\.\d+)?)\s*,\s*(?P<y>-?\d+(?:\.\d+)?)\s*,\s*(?P<z>-?\d+(?:\.\d+)?)\s*$"
)
_LINE_QUAT = re.compile(
    r"^(?P<bone>\S+)\s*:\s*quat\s+(?P<a>-?\d+(?:\.\d+)?)\s*,\s*(?P<b>-?\d+(?:\.\d+)?)\s*,\s*"
    r"(?P<c>-?\d+(?:\.\d+)?)\s*,\s*(?P<d>-?\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BoneEuler:
    bone: str
    x: float
    y: float
    z: float


def parse_pose_compact(text: str) -> dict[str, BoneEuler]:
    """Parse 'bone: x,y,z' lines. Quaternion lines are skipped (no reliable euler)."""
    out: dict[str, BoneEuler] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_EULER.match(line)
        if m:
            bone = m.group("bone")
            out[bone] = BoneEuler(
                bone=bone,
                x=float(m.group("x")),
                y=float(m.group("y")),
                z=float(m.group("z")),
            )
            continue
        if _LINE_QUAT.match(line):
            continue
    return out


def _euler_line(name: str, reuler: list[Any]) -> str | None:
    if not isinstance(reuler, list) or len(reuler) < 3:
        return None
    return f"{name}: {reuler[0]},{reuler[1]},{reuler[2]}"


def format_pose_compact_from_regions(pose_data: dict) -> str:
    """Flatten Bridge pose JSON (regions + optional root) to compact text."""
    lines: list[str] = []

    root = pose_data.get("root")
    if isinstance(root, dict):
        # Prefer guide (Studio object placement), fall back to ChaControl world
        for key, alias in (
            ("guide_rot_euler", "char_guide"),
            ("world_rot_euler", "char_root"),
        ):
            line = _euler_line(alias, root.get(key) or [])
            if line:
                lines.append(line)

    regions = pose_data.get("regions") or {}
    for _name, bones in regions.items():
        if not isinstance(bones, list):
            continue
        for b in bones:
            if not isinstance(b, dict):
                continue
            bone = b.get("bone", "?")
            reuler = b.get("rot_euler")
            rquat = b.get("rot_quat")
            if isinstance(reuler, list) and len(reuler) >= 3:
                lines.append(f"{bone}: {reuler[0]},{reuler[1]},{reuler[2]}")
            elif isinstance(rquat, list) and len(rquat) >= 4:
                lines.append(
                    f"{bone}: quat {rquat[0]},{rquat[1]},{rquat[2]},{rquat[3]}"
                )
    return "\n".join(lines)
