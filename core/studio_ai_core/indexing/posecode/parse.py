"""Parse pose_compact text into bone → euler degrees."""

from __future__ import annotations

import re
from dataclasses import dataclass


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


def format_pose_compact_from_regions(pose_data: dict) -> str:
    """Flatten Bridge pose JSON regions to compact text (same as MCP formatter)."""
    regions = pose_data.get("regions") or {}
    lines: list[str] = []
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
