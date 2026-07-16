"""Chat + structured orchestration in Core."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from studio_ai_core.personas import PERSONAS, get_persona
from studio_ai_core.routing import (
    RoutingError,
    resolve_chat_target,
    resolve_structured_target,
)
from studio_ai_core.text_normalize import split_thinking
from studio_ai_core.worker_client import WorkerApiError, WorkerClient, WorkerOfflineError

logger = logging.getLogger(__name__)

_CLOSE_HINT = "/" + "think"
_OPEN_HINT = "<" + "think"
_OPEN_HINT_ALT = "<redacted_thinking"


def _normalize_assistant_message(
    message: dict[str, Any] | None, *, reasoning: str | None = None
) -> dict[str, Any]:
    msg = dict(message or {"role": "assistant", "content": ""})
    content = msg.get("content") or ""
    existing_reasoning = reasoning or msg.get("reasoning_content") or ""
    leaked_reasoning, answer = split_thinking(content)
    if leaked_reasoning:
        if existing_reasoning:
            existing_reasoning = (existing_reasoning.rstrip() + "\n\n" + leaked_reasoning).strip()
        else:
            existing_reasoning = leaked_reasoning
        msg["content"] = answer
    if existing_reasoning:
        msg["reasoning_content"] = existing_reasoning
    return msg


class ChatService:
    def __init__(
        self,
        worker: WorkerClient,
        *,
        default_persona: str = "stheno",
        grammars_dir: Path,
    ) -> None:
        self.worker = worker
        self.default_persona = default_persona
        self.grammars_dir = grammars_dir

    def list_personas(self) -> list[dict[str, str | int]]:
        return [
            {
                "id": p.id,
                "name": p.name,
                "model_id": p.model_id,
                "description": p.description,
                "default_max_tokens": p.default_max_tokens,
            }
            for p in PERSONAS
        ]

    def resolve_max_tokens(self, persona_id: str | None, max_tokens: int | None) -> int:
        if max_tokens is not None and max_tokens > 0:
            return max_tokens
        if persona_id:
            try:
                return get_persona(persona_id).default_max_tokens
            except KeyError:
                pass
        return get_persona(self.default_persona).default_max_tokens

    def build_messages(
        self,
        messages: list[dict[str, str]],
        *,
        persona_id: str | None,
        inject_system: bool = True,
    ) -> list[dict[str, str]]:
        out = [{"role": m["role"], "content": m["content"]} for m in messages]
        if not inject_system or not persona_id:
            return out
        has_system = any(m["role"] == "system" for m in out)
        if has_system:
            return out
        persona = get_persona(persona_id)
        return [{"role": "system", "content": persona.system_prompt}, *out]

    async def chat(
        self,
        *,
        messages: list[dict[str, str]],
        persona: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> dict[str, Any] | AsyncIterator[str]:
        model_id, resolved_persona = resolve_chat_target(
            persona_id=persona,
            model_id=model,
            default_persona=self.default_persona,
        )
        persona_id = resolved_persona.id if resolved_persona else persona
        if persona_id is None and model is None:
            persona_id = self.default_persona

        built = self.build_messages(messages, persona_id=persona_id)
        await self.worker.ensure_model(model_id)
        tokens = self.resolve_max_tokens(persona_id, max_tokens)

        if stream:
            return self._stream_chat(
                model_id=model_id,
                persona_id=persona_id,
                messages=built,
                max_tokens=tokens,
                temperature=temperature,
            )

        result = await self.worker.chat(
            model=model_id,
            messages=built,
            max_tokens=tokens,
            temperature=temperature,
        )
        message = _normalize_assistant_message(
            result.get("message"),
            reasoning=result.get("reasoning_content"),
        )
        return {
            "ok": True,
            "role": "agent_chat",
            "persona": persona_id,
            "model": result.get("model", model_id),
            "message": message,
            "finish_reason": result.get("finish_reason"),
        }

    async def _stream_chat(
        self,
        *,
        model_id: str,
        persona_id: str | None,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[str]:
        meta = {
            "type": "meta",
            "role": "agent_chat",
            "persona": persona_id,
            "model": model_id,
            "thinking": True,
        }
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"

        content_buf = ""
        emitted_answer_len = 0
        tag_mode = False

        async for line in self.worker.chat_stream(
            model=model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            if not line:
                continue
            raw = line[5:].strip() if line.startswith("data:") else line.strip()
            if raw == "[DONE]":
                if tag_mode:
                    _reasoning, answer = split_thinking(content_buf)
                    if len(answer) > emitted_answer_len:
                        piece = answer[emitted_answer_len:]
                        chunk = {"choices": [{"delta": {"content": piece}, "index": 0}]}
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                continue

            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                yield f"data: {raw}\n\n"
                continue

            if obj.get("type") in ("meta", "error"):
                yield f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
                continue

            choices = obj.get("choices") or []
            if not choices:
                yield f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
                continue

            delta = dict(choices[0].get("delta") or {})
            reason_piece = delta.get("reasoning_content") or delta.get("reasoning") or ""
            content_piece = delta.get("content") or ""

            out_delta: dict[str, Any] = {}
            if reason_piece:
                out_delta["reasoning_content"] = reason_piece

            if content_piece:
                content_buf += content_piece
                lower = content_buf.lower()
                if (not tag_mode) and (
                    _OPEN_HINT in lower or _OPEN_HINT_ALT in lower or _CLOSE_HINT in lower
                ):
                    tag_mode = True

                if tag_mode:
                    if _CLOSE_HINT in lower or "</redacted_thinking" in lower:
                        reasoning, answer = split_thinking(content_buf)
                        if (
                            reasoning
                            and emitted_answer_len == 0
                            and "reasoning_content" not in out_delta
                        ):
                            out_delta["reasoning_content"] = reasoning
                        if len(answer) > emitted_answer_len:
                            out_delta["content"] = answer[emitted_answer_len:]
                            emitted_answer_len = len(answer)
                    # else: still inside leaked think block — wait
                else:
                    out_delta["content"] = content_piece
                    emitted_answer_len = len(content_buf)

            if out_delta:
                chunk: dict[str, Any] = {
                    "choices": [
                        {
                            "delta": out_delta,
                            "index": 0,
                            "finish_reason": choices[0].get("finish_reason"),
                        }
                    ]
                }
                for key in ("id", "model", "object", "created"):
                    if key in obj:
                        chunk[key] = obj[key]
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        if tag_mode:
            _reasoning, answer = split_thinking(content_buf)
            if len(answer) > emitted_answer_len:
                piece = answer[emitted_answer_len:]
                chunk = {"choices": [{"delta": {"content": piece}, "index": 0}]}
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    async def structured(
        self,
        *,
        prompt: str | None = None,
        messages: list[dict[str, str]] | None = None,
        model: str | None = None,
        max_tokens: int = 256,
        temperature: float = 0.1,
        grammar_file: str = "smoke_json.gbnf",
        grammar: str | None = None,
    ) -> dict[str, Any]:
        profile = resolve_structured_target(model)
        await self.worker.ensure_model(profile.id)

        grammar_text = grammar
        grammar_ref = None if grammar else grammar_file

        if messages:
            result = await self.worker.chat(
                model=profile.id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                grammar=grammar_text,
                grammar_file=grammar_ref,
            )
            content = (result.get("message") or {}).get("content", "")
            finish = result.get("finish_reason")
        else:
            if not prompt:
                raise RoutingError("structured requires 'prompt' or 'messages'")
            result = await self.worker.completion(
                model=profile.id,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                grammar=grammar_text,
                grammar_file=grammar_ref,
            )
            content = result.get("text") or ""
            finish = result.get("finish_reason")

        parsed = None
        parse_error = None
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)

        return {
            "ok": parse_error is None,
            "role": "structured_json",
            "model": profile.id,
            "grammar_file": grammar_ref,
            "raw": content,
            "json": parsed,
            "parse_error": parse_error,
            "finish_reason": finish,
        }


__all__ = [
    "ChatService",
    "RoutingError",
    "WorkerApiError",
    "WorkerOfflineError",
]
