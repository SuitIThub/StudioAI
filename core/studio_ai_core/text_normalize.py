"""Normalize LLM chat output – split thinking vs visible answer."""

from __future__ import annotations

import re

# Qwen3 / llama.cpp may leak thinking into `content` with these markers.
_BLOCK_RE = re.compile(
    r"(?is)<\s*think\s*>(.*?)</\s*think\s*>|<\s*redacted_thinking\s*>(.*?)</\s*redacted_thinking\s*>"
)
_CLOSE_RE = re.compile(r"(?is)</\s*think\s*>|</\s*redacted_thinking\s*>")


def split_thinking(text: str) -> tuple[str, str]:
    """Return (reasoning, answer) extracted from a single content string."""
    if not text:
        return "", ""

    reasoning_parts: list[str] = []
    remainder = text
    pieces: list[str] = []
    last = 0
    for match in _BLOCK_RE.finditer(remainder):
        pieces.append(remainder[last : match.start()])
        block = match.group(1) if match.group(1) is not None else match.group(2)
        if block and block.strip():
            reasoning_parts.append(block.strip())
        last = match.end()
    pieces.append(remainder[last:])
    remainder = "".join(pieces)

    # Opener missing: text before the last closing tag is reasoning.
    closes = list(_CLOSE_RE.finditer(remainder))
    if closes:
        cut = closes[-1]
        head = remainder[: cut.start()].strip()
        if head:
            reasoning_parts.append(head)
        remainder = remainder[cut.end() :]

    answer = remainder.strip()
    reasoning = "\n\n".join(p for p in reasoning_parts if p)
    return reasoning, answer


def strip_thinking_text(text: str) -> str:
    """Keep only the visible assistant reply."""
    _, answer = split_thinking(text)
    return answer
