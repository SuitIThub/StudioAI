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
        "- description: ONE short sentence on body pose (use majority stance if present).\n"
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


def apply_majority_stance(
    entry: dict[str, Any],
    *,
    posecode_tags: list[str],
    captions: dict[str, str],
) -> dict[str, Any]:
    """Replace contested stance tags with majority vote when available."""
    cleaned = sanitize_merge_entry(entry)
    majority = majority_stance(posecode_tags, captions)
    tags = [t for t in cleaned["tags"] if t not in _STANCE_TAGS]
    if majority:
        tags.insert(0, majority)
        # Keep crouching alongside all_fours if already present / posecode had it
        if majority == "all_fours" and (
            "crouching" in cleaned["tags"] or "crouching" in posecode_tags
        ):
            if "crouching" not in tags:
                tags.insert(1, "crouching")
    cleaned["tags"] = tags[:8]

    synonyms = list(cleaned["synonyms"])
    if majority and f"{majority}_pose" not in synonyms:
        synonyms = [f"{majority}_pose", *synonyms][:6]
    cleaned["synonyms"] = synonyms

    desc = cleaned["description"]
    if majority and desc:
        # If description still leads with a conflicting stance word, lightly rewrite
        other = _STANCE_TAGS - {majority, "supine", "prone"}
        lead = desc.split(",", 1)[0].lower()
        if any(o.replace("_", " ") in lead or o in lead for o in other):
            rest = desc.split(",", 1)[1].strip() if "," in desc else ""
            cleaned["description"] = (
                f"{majority.replace('_', ' ')}, {rest}" if rest else majority.replace("_", " ")
            )
    elif majority and not desc:
        cleaned["description"] = majority.replace("_", " ")
    return cleaned


def fallback_index_entry(
    *,
    posecode_tags: list[str],
    captions: dict[str, str],
) -> dict[str, Any]:
    """Conservative union + majority stance."""
    majority = majority_stance(posecode_tags, captions)
    base_tags = [t for t in posecode_tags if t not in _STANCE_TAGS]
    if majority:
        base_tags = [majority, *base_tags]
    elif stance_from_posecode(posecode_tags):
        # No majority: omit stance entirely (equal-weight rule)
        pass
    texts = [t for t in captions.values() if t]
    shared = _shared_keywords(texts) if len(texts) >= 2 else []
    description = (
        f"{majority.replace('_', ' ')} pose"
        if majority
        else ("pose with " + ", ".join(base_tags[:4]) if base_tags else "pose")
    )
    tags = list(dict.fromkeys([*base_tags, *shared]))[:8]
    return apply_majority_stance(
        {"description": description, "tags": tags, "synonyms": shared[:6]},
        posecode_tags=posecode_tags,
        captions=captions,
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

    entry = fallback_index_entry(posecode_tags=posecode_tags, captions=captions)
    return {
        "ok": False,
        "source": "fallback",
        "attempt": 2,
        "entry": entry,
        "raw": last_raw,
        "error": last_err,
        "majority_stance": majority_stance(posecode_tags, captions),
    }
