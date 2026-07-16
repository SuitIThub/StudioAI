"""HTTP client to the Heimserver Worker (thin adapter)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class WorkerOfflineError(Exception):
    """Raised when the Heimserver worker cannot be reached."""

    def __init__(self, message: str = "Heimserver worker is offline or unreachable") -> None:
        super().__init__(message)
        self.code = "worker_offline"


class WorkerApiError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class WorkerClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        timeout_s: float = 120.0,
        health_timeout_s: float = 3.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s
        self.health_timeout_s = health_timeout_s

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    async def health(self) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=self.health_timeout_s) as client:
                resp = await client.get(f"{self.base_url}/health", headers=self._headers())
                if resp.status_code >= 400:
                    return None
                return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Worker health failed: %s", exc)
            return None

    async def list_models(self) -> dict[str, Any]:
        return await self._request("GET", "/models")

    async def load(self, model_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/models/{model_id}/load")

    async def unload(self, model_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/models/{model_id}/unload")

    async def swap(self, unload_id: str, load_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/models/swap", json_body={"unload_id": unload_id, "load_id": load_id}
        )

    async def ensure_model(self, model_id: str) -> None:
        """Load model_id, swapping out whatever is currently loaded if needed."""
        data = await self.list_models()
        models = data.get("models") or []
        loaded = [m["id"] for m in models if m.get("loaded")]
        if model_id in loaded:
            return
        max_loaded = int(data.get("max_loaded") or 1)
        if loaded and len(loaded) >= max_loaded:
            await self.swap(loaded[0], model_id)
        else:
            await self.load(model_id)

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        grammar: str | None = None,
        grammar_file: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if grammar:
            body["grammar"] = grammar
        if grammar_file:
            body["grammar_file"] = grammar_file
        return await self._request("POST", "/v1/chat/completions", json_body=body)

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        grammar: str | None = None,
        grammar_file: str | None = None,
    ) -> AsyncIterator[str]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if grammar:
            body["grammar"] = grammar
        if grammar_file:
            body["grammar_file"] = grammar_file

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/chat/completions",
                    headers=self._headers(),
                    json=body,
                ) as resp:
                    if resp.status_code >= 400:
                        text = (await resp.aread()).decode("utf-8", errors="replace")
                        raise WorkerApiError(
                            f"Worker chat stream error {resp.status_code}: {text}",
                            status_code=resp.status_code,
                        )
                    async for line in resp.aiter_lines():
                        yield line
        except httpx.HTTPError as exc:
            raise WorkerOfflineError(
                f"Heimserver worker is offline or unreachable ({self.base_url}): {exc}"
            ) from exc

    async def completion(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.2,
        grammar: str | None = None,
        grammar_file: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if grammar:
            body["grammar"] = grammar
        if grammar_file:
            body["grammar_file"] = grammar_file
        return await self._request("POST", "/v1/completions", json_body=body)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.request(
                    method, url, headers=self._headers(), json=json_body
                )
        except httpx.HTTPError as exc:
            raise WorkerOfflineError(
                f"Heimserver worker is offline or unreachable ({self.base_url}): {exc}"
            ) from exc

        if resp.status_code >= 400:
            detail = resp.text
            try:
                payload = resp.json()
                detail = payload.get("detail", detail)
            except Exception:
                pass
            raise WorkerApiError(
                f"Worker error {resp.status_code}: {detail}", status_code=resp.status_code
            )

        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}
