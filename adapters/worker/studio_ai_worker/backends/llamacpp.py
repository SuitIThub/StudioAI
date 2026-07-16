"""llama.cpp server backend – start/stop process and call OpenAI-compatible API."""

from __future__ import annotations

import logging
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class RunningServer:
    model_id: str
    model_path: Path
    port: int
    process: subprocess.Popen[str]
    base_url: str = field(init=False)

    def __post_init__(self) -> None:
        self.base_url = f"http://127.0.0.1:{self.port}"


class LlamaCppBackend:
    def __init__(
        self,
        *,
        bin_path: str = "llama-server",
        host: str = "127.0.0.1",
        base_port: int = 8080,
        ctx_size: int = 4096,
        n_gpu_layers: int = 99,
        load_timeout_s: float = 180.0,
    ) -> None:
        self.bin_path = bin_path
        self.host = host
        self.base_port = base_port
        self.ctx_size = ctx_size
        self.n_gpu_layers = n_gpu_layers
        self.load_timeout_s = load_timeout_s
        self._servers: dict[str, RunningServer] = {}
        self._next_port = base_port

    @property
    def loaded_ids(self) -> list[str]:
        return list(self._servers.keys())

    def is_loaded(self, model_id: str) -> bool:
        return model_id in self._servers

    def get_server(self, model_id: str) -> RunningServer | None:
        return self._servers.get(model_id)

    def _pick_port(self) -> int:
        port = self._next_port
        while self._port_in_use(port):
            port += 1
        self._next_port = port + 1
        return port

    @staticmethod
    def _port_in_use(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    def load(
        self,
        model_id: str,
        model_path: Path,
        ctx_size: int | None = None,
        *,
        extra_args: list[str] | None = None,
        enable_thinking: bool | None = None,
    ) -> RunningServer:
        if model_id in self._servers:
            return self._servers[model_id]

        if not model_path.is_file():
            raise FileNotFoundError(
                f"GGUF not found for '{model_id}': {model_path}. "
                "Set the correct path in deploy/registry.yaml."
            )

        port = self._pick_port()
        ctx = ctx_size or self.ctx_size
        cmd = [
            self.bin_path,
            "-m",
            str(model_path),
            "--host",
            self.host,
            "--port",
            str(port),
            "-c",
            str(ctx),
            "-ngl",
            str(self.n_gpu_layers),
            "--jinja",
        ]
        # Only disable thinking when explicitly requested in registry.
        if enable_thinking is False:
            cmd.extend(["--reasoning-budget", "0"])
        if extra_args:
            cmd.extend(extra_args)
        logger.info("Starting llama-server: %s", " ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"llama-server binary not found: '{self.bin_path}'. "
                "Install llama.cpp and set llamacpp.bin in config."
            ) from exc

        server = RunningServer(model_id=model_id, model_path=model_path, port=port, process=proc)
        try:
            self._wait_ready(server)
        except Exception:
            self._terminate(proc)
            raise

        self._servers[model_id] = server
        return server

    def unload(self, model_id: str) -> None:
        server = self._servers.pop(model_id, None)
        if server is None:
            return
        self._terminate(server.process)

    def unload_all(self) -> None:
        for model_id in list(self._servers):
            self.unload(model_id)

    def _wait_ready(self, server: RunningServer) -> None:
        deadline = time.time() + self.load_timeout_s
        url = f"{server.base_url}/health"
        last_err = ""
        while time.time() < deadline:
            if server.process.poll() is not None:
                out = ""
                if server.process.stdout:
                    out = server.process.stdout.read() or ""
                raise RuntimeError(
                    f"llama-server exited early (code {server.process.returncode}). Output:\n{out[-2000:]}"
                )
            try:
                with httpx.Client(timeout=2.0) as client:
                    # Prefer /v1/models; fall back to /health
                    for probe in (f"{server.base_url}/v1/models", url):
                        try:
                            resp = client.get(probe)
                            if resp.status_code < 500:
                                logger.info("llama-server ready for %s on port %s", server.model_id, server.port)
                                return
                        except httpx.HTTPError as exc:
                            last_err = str(exc)
            except httpx.HTTPError as exc:
                last_err = str(exc)
            time.sleep(0.5)
        raise TimeoutError(
            f"Timed out waiting for llama-server ({server.model_id}) on port {server.port}: {last_err}"
        )

    @staticmethod
    def _terminate(proc: subprocess.Popen[str]) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    async def completion(
        self,
        model_id: str,
        *,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.2,
        grammar: str | None = None,
    ) -> dict[str, Any]:
        server = self._require(model_id)
        payload: dict[str, Any] = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if grammar:
            payload["grammar"] = grammar

        async with httpx.AsyncClient(timeout=120.0) as client:
            # llama.cpp OpenAI-compatible completions
            resp = await client.post(
                f"{server.base_url}/v1/completions",
                json={
                    "model": model_id,
                    "prompt": prompt,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    **({"grammar": grammar} if grammar else {}),
                },
            )
            if resp.status_code >= 400:
                # Fallback to native /completion endpoint
                resp = await client.post(f"{server.base_url}/completion", json=payload)
            resp.raise_for_status()
            data = resp.json()

        text = ""
        finish = None
        if "choices" in data and data["choices"]:
            choice = data["choices"][0]
            text = choice.get("text") or (choice.get("message") or {}).get("content") or ""
            finish = choice.get("finish_reason")
        else:
            text = data.get("content") or data.get("text") or ""
            finish = data.get("stop_type")
        return {"model": model_id, "text": text, "finish_reason": finish}

    async def chat(
        self,
        model_id: str,
        *,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        grammar: str | None = None,
        chat_template_kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        server = self._require(model_id)
        body: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if grammar:
            body["grammar"] = grammar
        if chat_template_kwargs:
            body["chat_template_kwargs"] = chat_template_kwargs

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{server.base_url}/v1/chat/completions", json=body)
            resp.raise_for_status()
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {"role": "assistant", "content": choice.get("text") or ""}
        return {
            "model": model_id,
            "message": {"role": message.get("role", "assistant"), "content": message.get("content", "")},
            "finish_reason": choice.get("finish_reason"),
            "reasoning_content": message.get("reasoning_content"),
        }

    async def chat_stream(
        self,
        model_id: str,
        *,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        grammar: str | None = None,
        chat_template_kwargs: dict[str, Any] | None = None,
    ):
        """Yield raw SSE lines from llama.cpp (data: ... / [DONE])."""
        server = self._require(model_id)
        body: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if grammar:
            body["grammar"] = grammar
        if chat_template_kwargs:
            body["chat_template_kwargs"] = chat_template_kwargs

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{server.base_url}/v1/chat/completions", json=body
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line is not None:
                        yield line

    def _require(self, model_id: str) -> RunningServer:
        server = self._servers.get(model_id)
        if server is None:
            raise KeyError(f"Model '{model_id}' is not loaded. Call POST /models/{model_id}/load first.")
        return server
