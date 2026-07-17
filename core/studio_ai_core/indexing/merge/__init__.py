"""Merge posecode + captions into index JSON via Qwen+GBNF."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from studio_ai_core import REPO_ROOT
from studio_ai_core.worker_client import WorkerClient

logger = logging.getLogger(__name__)

DEFAULT_GRAMMAR_PATH = REPO_ROOT / "deploy" / "grammars" / "index_entry.gbnf"

MERGE_SYSTEM = (
    "You merge pose index signals into one JSON object. "
    "Posecode is authoritative for body posture/stance. "
    "Captions are authoritative for clothing, appearance, style, and atmosphere. "
    "When captions conflict with posecode on posture (e.g. standing vs sitting), "
    "keep the posecode posture and rewrite description accordingly. "
    "Output must match the grammar exactly - no markdown."
)


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
    return (
        f"{MERGE_SYSTEM}\n\n"
        f"Posecode text: {posecode_text}\n"
        f"Posecode tags: [{tags}]\n"
        f"Captions:\n{cap_lines or '- (none)'}\n\n"
        "Produce JSON with keys description (string), tags (string array), synonyms (string array).\n"
        "Include posture tags from posecode. Add searchable synonyms for the description.\n"
    )


def fallback_index_entry(
    *,
    posecode_tags: list[str],
    captions: dict[str, str],
) -> dict[str, Any]:
    front = captions.get("front") or captions.get("front_full") or next(iter(captions.values()), "")
    keywords = _keyword_union(front, *captions.values())
    tags = list(dict.fromkeys([*posecode_tags, *keywords]))
    return {
        "description": front or ("pose: " + ", ".join(posecode_tags)),
        "tags": tags,
        "synonyms": keywords[:12],
    }


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
            return {
                "ok": True,
                "source": "qwen_gbnf",
                "attempt": attempt + 1,
                "entry": {
                    "description": parsed["description"],
                    "tags": [str(t) for t in parsed["tags"]],
                    "synonyms": [str(s) for s in parsed["synonyms"]],
                },
                "raw": last_raw,
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
    }
