"""Tests for thinking/answer split."""

from __future__ import annotations

from studio_ai_core.text_normalize import split_thinking, strip_thinking_text


def test_split_think_block():
    raw = "<think>plan first</think>\n\nHello there."
    reasoning, answer = split_thinking(raw)
    assert "plan first" in reasoning
    assert answer == "Hello there."
    assert strip_thinking_text(raw) == "Hello there."


def test_split_close_only():
    raw = "long internal monologue\n</think>\n\nFinal line."
    reasoning, answer = split_thinking(raw)
    assert "monologue" in reasoning
    assert answer == "Final line."


def test_no_think_passthrough():
    raw = "Just a normal reply."
    reasoning, answer = split_thinking(raw)
    assert reasoning == ""
    assert answer == "Just a normal reply."
