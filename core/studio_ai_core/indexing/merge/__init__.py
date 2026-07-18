"""Merge posecode + captions into index JSON via Qwen+GBNF."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

from studio_ai_core import REPO_ROOT
from studio_ai_core.worker_client import WorkerClient

logger = logging.getLogger(__name__)

DEFAULT_GRAMMAR_PATH = REPO_ROOT / "deploy" / "grammars" / "index_entry.gbnf"

MERGE_SYSTEM = (
    "You build a searchable pose-index entry from equal evidence sources: "
    "posecode tags and each view caption. "
    "None is authoritative alone — any may be wrong. "
    "When two or more sources agree on a stance, use that stance. "
    "When sources clearly conflict with no majority, omit the contested claim. "
    "Ignore clothing, hair, face, jewelry, breast size, skin, and render quality. "
    "Ignore captions that claim 'hanging' or 'upside down' unless every source agrees. "
    "Output must match the grammar exactly - no markdown."
)

_STANCE_TAGS = frozenset(
    {
        "standing",
        "sitting",
        "kneeling",
        "squatting",
        "all_fours",
        "lying",
        "prone",
        "supine",
    }
)

_STANCE_COMPAT = frozenset({"crouching", "bent_forward", "arched_back", "leaning_side"})

# Alias → canonical before exclusivity checks (synonyms are not conflicts)
_TAG_ALIASES: dict[str, str] = {
    "arms_extended": "arms_forward",
    "arms_over_chest": "arms_crossed",
    "on_stomach": "prone",
    "stomach": "prone",
    "on_back": "supine",
}

# Mutually exclusive tag sets: if ≥2 *distinct* members appear after aliasing, drop all.
_EXCLUSIVE_GROUPS: tuple[frozenset[str], ...] = (
    _STANCE_TAGS,
    frozenset({"arms_forward", "arms_crossed", "arms_raised", "arms_behind"}),
    frozenset({"facing_forward", "facing_away", "from_behind", "profile"}),
    frozenset({"prone", "supine"}),  # both are lying variants; omit if both claimed
)

_NOISE_TAGS = frozenset(
    {
        "symmetrical_legs",
        "close_feet",
        "slightly_elevated_upper_body",
        "feet_pointed_downward",
        "feet_pointing_upward",
        "feet_downward",
        "legs_positioned_symmetrically",
        "posecode",
        "posecode_tags",
        "posecode_text",
        "bent",
        "downward",
        "weight-bearing_stance",
        "weight_bearing_stance",
        "bent_knees",
        "knees_bent",
        "bent_arms",
        "bent_elbows",
        "arms_bent",
        "elbows_pointing_outward",
        "legs_slightly_apart",
        "stomach",
    }
)

_SYNONYM_STOP = frozenset(
    {
        "posecode",
        "posecode_tags",
        "posecode_text",
        "bent",
        "downward",
        "pose",
        "position",
        "stance",
        "stomach",
    }
)


def _normalize_tag(tag: str) -> str:
    t = tag.strip().lower().replace(" ", "_")
    return _TAG_ALIASES.get(t, t)


def load_index_grammar(grammars_dir: Path | None = None) -> str:
    """Grammar lives in Core (SoT) and is sent inline to the Worker."""
    path = (grammars_dir / "index_entry.gbnf") if grammars_dir else DEFAULT_GRAMMAR_PATH
    if not path.is_file():
        path = DEFAULT_GRAMMAR_PATH
    if not path.is_file():
        raise FileNotFoundError(f"index_entry.gbnf not found at {path}")
    return path.read_text(encoding="utf-8")


def build_merge_prompt(
    *,
    posecode_text: str,
    posecode_tags: list[str],
    captions: dict[str, str],
) -> str:
    cap_lines = "\n".join(f"- {view}: {text}" for view, text in captions.items() if text)
    tags = ", ".join(posecode_tags)
    majority = majority_stance(posecode_tags, captions)
    majority_line = (
        f"Majority stance (2+ independent votes): {majority}\n"
        if majority
        else "Majority stance: none (omit stance if contested)\n"
    )
    return (
        f"{MERGE_SYSTEM}\n\n"
        f"Posecode text: {posecode_text}\n"
        f"Posecode tags: [{tags}]\n"
        f"Captions (pose-focused):\n{cap_lines or '- (none)'}\n"
        f"{majority_line}\n"
        "Produce JSON:\n"
        "- description: ONE short sentence on body pose. Include majority stance AND "
        "notable limb/torso cues from posecode tags (never stance alone like 'standing').\n"
        "- tags: at most 8 pose keywords; include majority stance when present; "
        "never include both sides of a conflict.\n"
        "- synonyms: at most 6 short pose search aliases (no meta words like posecode).\n"
    )


def stance_from_caption(text: str) -> str | None:
    """Extract a primary stance vote from caption text. Returns None if unreliable."""
    t = (text or "").lower()
    if not t:
        return None
    # Common VLM hallucations on odd camera angles — do not count as votes
    if "upside down" in t or "hanging" in t:
        return None
    if "all-fours" in t or "all fours" in t or "hands and knees" in t or "hands-and-knees" in t:
        return "all_fours"
    if "kneeling" in t or "on her knees" in t or "on his knees" in t or "on knees" in t:
        return "kneeling"
    if "lying" in t or "on back" in t or "on her back" in t or "on his back" in t:
        return "lying"
    if "supine" in t:
        return "lying"
    if "prone" in t or "on stomach" in t or "face down" in t:
        return "lying"
    if "sitting" in t or "seated" in t:
        return "sitting"
    if "squatting" in t:
        return "squatting"
    if "standing" in t or "upright" in t:
        return "standing"
    if "crouching" in t or "crouch" in t:
        return "all_fours"
    return None


def stance_from_posecode(tags: list[str]) -> str | None:
    for t in tags:
        tl = t.lower().replace(" ", "_")
        if tl in ("supine", "prone"):
            return "lying"
        if tl in _STANCE_TAGS:
            return tl
    return None


def majority_stance(
    posecode_tags: list[str],
    captions: dict[str, str],
) -> str | None:
    """
    Equal-weight votes: one from posecode, one per caption view.
    Keep stance only when ≥2 votes agree and there is no tie. No single source wins alone.
    """
    votes: list[str] = []
    pc = stance_from_posecode(posecode_tags)
    if pc:
        votes.append(pc)
    for text in captions.values():
        s = stance_from_caption(text or "")
        if s:
            votes.append(s)
    if not votes:
        return None
    counts = Counter(votes)
    best, n = counts.most_common(1)[0]
    if n < 2:
        return None
    if sum(1 for c in counts.values() if c == n) > 1:
        return None  # tie — omit rather than pick a winner
    return best


def sanitize_merge_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Drop contradictory / noisy tags without preferring any input source."""
    tags_in = [_normalize_tag(str(t)) for t in (entry.get("tags") or [])]
    tags_in = [t for t in tags_in if t and t not in _NOISE_TAGS]

    drop: set[str] = set()
    for group in _EXCLUSIVE_GROUPS:
        present = [t for t in tags_in if t in group]
        if group is _EXCLUSIVE_GROUPS[0]:
            present = [t for t in present if t not in _STANCE_COMPAT]
        if len(set(present)) >= 2:
            drop.update(present)

    cleaned: list[str] = []
    seen: set[str] = set()
    for t in tags_in:
        if t in drop or t in seen:
            continue
        seen.add(t)
        cleaned.append(t)
        if len(cleaned) >= 8:
            break

    synonyms = [_normalize_tag(str(s)) for s in (entry.get("synonyms") or [])]
    syn_out: list[str] = []
    syn_seen: set[str] = set()
    for s in synonyms:
        if not s or s in syn_seen or s in drop or s in _NOISE_TAGS or s in _SYNONYM_STOP:
            continue
        if "posecode" in s:
            continue
        if any(s == d or s.startswith(d + "_") for d in drop):
            continue
        syn_seen.add(s)
        syn_out.append(s)
        if len(syn_out) >= 6:
            break

    desc = str(entry.get("description") or "").strip()
    return {
        "description": desc,
        "tags": cleaned,
        "synonyms": syn_out,
    }


def description_from_posecode(posecode_tags: list[str]) -> str:
    """Build a searchable one-liner from rule-based tags (floor without JoyCaption)."""
    tags = [_normalize_tag(str(t)) for t in (posecode_tags or []) if t]
    tags = list(dict.fromkeys(t for t in tags if t and t not in _NOISE_TAGS))
    if not tags:
        return "unspecified pose"

    stance = next((t for t in tags if t in _STANCE_TAGS), None)
    extras = [t for t in tags if t not in _STANCE_TAGS]

    def _phrase(tag: str) -> str:
        return tag.replace("_", " ")

    if stance:
        lead = _phrase(stance)
        lead = lead[:1].upper() + lead[1:]
        if extras:
            return f"{lead} with " + ", ".join(_phrase(t) for t in extras[:6])
        return f"{lead} pose"

    return "Pose with " + ", ".join(_phrase(t) for t in extras[:6])


def _description_is_thin(desc: str, *, min_words: int = 3) -> bool:
    """True when description is empty, stance-only, or too short for search."""
    d = (desc or "").strip()
    if not d:
        return True
    words = [w for w in re.split(r"\W+", d.lower()) if w and w not in {"pose", "a", "an", "the"}]
    if len(words) < min_words:
        return True
    compact = d.lower().replace("-", "_").replace(" ", "_").strip(".,;")
    if compact in _STANCE_TAGS:
        return True
    if compact.endswith("_pose") and compact[: -len("_pose")] in _STANCE_TAGS:
        return True
    if len(words) <= 2 and any(w in _STANCE_TAGS for w in words):
        return True
    return False


def enrich_thin_description(
    entry: dict[str, Any],
    *,
    posecode_tags: list[str],
    posecode_text: str = "",
) -> dict[str, Any]:
    """Replace stance-only / empty descriptions with a posecode-derived sentence."""
    cleaned = dict(entry)
    desc = str(cleaned.get("description") or "").strip()
    if not _description_is_thin(desc):
        return cleaned

    tag_src = list(
        dict.fromkeys([*(cleaned.get("tags") or []), *(posecode_tags or [])])
    )
    rich = description_from_posecode(tag_src)
    if _description_is_thin(rich) and (posecode_text or "").strip():
        raw = posecode_text.strip()
        if raw.lower().startswith("pose with "):
            parts = [p.strip().replace("_", " ") for p in raw[10:].split(",") if p.strip()]
            if parts:
                first = parts[0]
                if first.replace(" ", "_") in _STANCE_TAGS and len(parts) > 1:
                    rich = first[:1].upper() + first[1:] + " with " + ", ".join(parts[1:])
                else:
                    rich = "Pose with " + ", ".join(parts)
            else:
                rich = raw
        else:
            rich = raw
    cleaned["description"] = rich
    return cleaned


def apply_majority_stance(
    entry: dict[str, Any],
    *,
    posecode_tags: list[str],
    captions: dict[str, str],
    posecode_text: str = "",
) -> dict[str, Any]:
    """Replace contested stance tags with majority vote when available."""
    cleaned = sanitize_merge_entry(entry)
    majority = majority_stance(posecode_tags, captions)
    tags = [t for t in cleaned["tags"] if t not in _STANCE_TAGS]
    if majority:
        tags.insert(0, majority)
        if majority == "all_fours" and (
            "crouching" in cleaned["tags"] or "crouching" in posecode_tags
        ):
            if "crouching" not in tags:
                tags.insert(1, "crouching")
        for t in posecode_tags:
            nt = _normalize_tag(t)
            if nt not in _STANCE_TAGS and nt not in tags:
                tags.append(nt)
    elif not any(captions.values()):
        # No captions: trust posecode stance (only evidence available)
        pc = stance_from_posecode(posecode_tags)
        if pc and pc not in tags:
            tags.insert(0, pc)
        for t in posecode_tags:
            nt = _normalize_tag(t)
            if nt not in _STANCE_TAGS and nt not in tags:
                tags.append(nt)
    cleaned["tags"] = tags[:8]

    synonyms = list(cleaned["synonyms"])
    if majority and f"{majority}_pose" not in synonyms:
        synonyms = [f"{majority}_pose", *synonyms][:6]
    cleaned["synonyms"] = synonyms

    desc = cleaned["description"]
    if majority and desc and not _description_is_thin(desc):
        other = _STANCE_TAGS - {majority, "supine", "prone"}
        lead = desc.split(",", 1)[0].lower()
        if any(o.replace("_", " ") in lead or o in lead for o in other):
            rest = desc.split(",", 1)[1].strip() if "," in desc else ""
            if rest:
                cleaned["description"] = (
                    f"{majority.replace('_', ' ').capitalize()}, {rest}"
                )
            else:
                cleaned["description"] = description_from_posecode(cleaned["tags"])
    else:
        # Empty / thin / no majority: never store bare "standing"
        tag_src = cleaned["tags"] if cleaned["tags"] else posecode_tags
        cleaned["description"] = description_from_posecode(tag_src)

    return enrich_thin_description(
        cleaned, posecode_tags=posecode_tags, posecode_text=posecode_text
    )


def fallback_index_entry(
    *,
    posecode_tags: list[str],
    captions: dict[str, str],
    posecode_text: str = "",
) -> dict[str, Any]:
    """Conservative union + majority stance; rich posecode description as floor."""
    majority = majority_stance(posecode_tags, captions)
    has_captions = any(bool(t) for t in (captions or {}).values())
    if majority:
        stance = majority
    elif not has_captions:
        # Posecode-only: trust the rule-based stance (no competing votes)
        stance = stance_from_posecode(posecode_tags)
    else:
        stance = None

    base_tags = [
        t for t in posecode_tags if _normalize_tag(t) not in _STANCE_TAGS
    ]
    if stance:
        tags = list(dict.fromkeys([stance, *base_tags]))
    else:
        tags = list(dict.fromkeys(base_tags))

    texts = [t for t in captions.values() if t]
    shared = _shared_keywords(texts) if len(texts) >= 2 else []
    tags = list(dict.fromkeys([*tags, *shared]))[:8]
    description = description_from_posecode(tags if tags else posecode_tags)

    return apply_majority_stance(
        {
            "description": description,
            "tags": tags,
            "synonyms": ([f"{stance}_pose"] if stance else []) + shared[:6],
        },
        posecode_tags=posecode_tags,
        captions=captions,
        posecode_text=posecode_text,
    )


_WORD = re.compile(r"[a-zA-Z][a-zA-Z\-]{2,}")


def _keyword_union(*texts: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    stop = {
        "the",
        "and",
        "with",
        "from",
        "this",
        "that",
        "image",
        "shows",
        "woman",
        "man",
        "her",
        "his",
        "she",
        "are",
        "has",
        "pose",
        "position",
        "facing",
        "slightly",
    }
    for text in texts:
        for w in _WORD.findall(text or ""):
            lw = w.lower()
            if lw in stop or lw in seen:
                continue
            seen.add(lw)
            out.append(lw)
            if len(out) >= 24:
                return out
    return out


def _shared_keywords(texts: list[str]) -> list[str]:
    """Keywords that appear in at least two captions (weak consensus)."""
    if len(texts) < 2:
        return []
    stop = {
        "the",
        "and",
        "with",
        "from",
        "this",
        "that",
        "image",
        "shows",
        "woman",
        "man",
        "her",
        "his",
        "she",
        "are",
        "has",
        "pose",
        "position",
        "facing",
        "slightly",
    }
    counts: dict[str, int] = {}
    for text in texts:
        seen_doc: set[str] = set()
        for w in _WORD.findall(text or ""):
            lw = w.lower()
            if lw in stop or lw in seen_doc:
                continue
            seen_doc.add(lw)
            counts[lw] = counts.get(lw, 0) + 1
    return [w for w, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if n >= 2][
        :8
    ]


async def merge_index_entry(
    worker: WorkerClient,
    *,
    posecode_text: str,
    posecode_tags: list[str],
    captions: dict[str, str],
    model_id: str = "qwen-technical",
    grammar: str | None = None,
    grammars_dir: Path | None = None,
    max_tokens: int = 512,
    temperature: float = 0.1,
) -> dict[str, Any]:
    """Call Qwen+GBNF; retry once; then fallback tag-union.

    Grammar text is loaded from Core and sent inline — Worker does not need the file.
    """
    prompt = build_merge_prompt(
        posecode_text=posecode_text,
        posecode_tags=posecode_tags,
        captions=captions,
    )
    grammar_text = grammar or load_index_grammar(grammars_dir)
    await worker.ensure_model(model_id)

    last_raw = ""
    last_err = None
    for attempt in range(2):
        try:
            result = await worker.completion(
                model=model_id,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                grammar=grammar_text,
            )
            last_raw = result.get("text") or ""
            parsed = json.loads(last_raw)
            if not isinstance(parsed.get("tags"), list):
                raise ValueError("tags must be array")
            if not isinstance(parsed.get("synonyms"), list):
                raise ValueError("synonyms must be array")
            if not isinstance(parsed.get("description"), str):
                raise ValueError("description must be string")
            entry = apply_majority_stance(
                {
                    "description": parsed["description"],
                    "tags": [str(t) for t in parsed["tags"]],
                    "synonyms": [str(s) for s in parsed["synonyms"]],
                },
                posecode_tags=posecode_tags,
                captions=captions,
                posecode_text=posecode_text,
            )
            entry = enrich_thin_description(
                entry, posecode_tags=posecode_tags, posecode_text=posecode_text
            )
            return {
                "ok": True,
                "source": "qwen_gbnf",
                "attempt": attempt + 1,
                "entry": entry,
                "raw": last_raw,
                "majority_stance": majority_stance(posecode_tags, captions),
            }
        except Exception as exc:
            last_err = str(exc)
            logger.warning("merge attempt %s failed: %s", attempt + 1, exc)

    entry = fallback_index_entry(
        posecode_tags=posecode_tags,
        captions=captions,
        posecode_text=posecode_text,
    )
    return {
        "ok": False,
        "source": "fallback",
        "attempt": 2,
        "entry": entry,
        "raw": last_raw,
        "error": last_err,
        "majority_stance": majority_stance(posecode_tags, captions),
    }
