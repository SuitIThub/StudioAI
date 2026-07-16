"""StudioAI Core FastAPI – Stage 2 chat + role routing."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from studio_ai_core import CONTRACT_VERSION
from studio_ai_core.chat_service import ChatService
from studio_ai_core.config import CoreSettings, settings_from_config
from studio_ai_core.profiles import DEFAULT_PROFILES
from studio_ai_core.routing import RoutingError
from studio_ai_core.worker_client import WorkerApiError, WorkerClient, WorkerOfflineError

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

settings: CoreSettings
worker: WorkerClient
chat_service: ChatService


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    persona: str | None = None
    model: str | None = None
    max_tokens: int = 2048
    temperature: float = 0.7
    stream: bool = True


class StructuredRequest(BaseModel):
    prompt: str | None = None
    messages: list[ChatMessage] | None = None
    model: str | None = None
    max_tokens: int = 256
    temperature: float = 0.1
    grammar_file: str = "smoke_json.gbnf"
    grammar: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global settings, worker, chat_service
    settings = settings_from_config()
    worker = WorkerClient(
        settings.worker_url,
        token=settings.worker_token,
        timeout_s=settings.worker_timeout_s,
        health_timeout_s=settings.health_timeout_s,
    )
    chat_service = ChatService(
        worker,
        default_persona=settings.default_persona,
        grammars_dir=settings.grammars_dir,
    )
    logger.info(
        "Core started (contract=%s, config=%s, worker=%s, port=%s)",
        CONTRACT_VERSION,
        settings.config_path,
        settings.worker_url,
        settings.port,
    )
    yield
    logger.info("Core stopped")


app = FastAPI(title="StudioAI Core", version=CONTRACT_VERSION, lifespan=lifespan)


def _offline_http(exc: WorkerOfflineError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "worker_offline",
            "message": str(exc),
            "hint": "Start the Heimserver worker (studio-ai-worker) and check worker_remote.url.",
        },
    )


def _worker_http(exc: WorkerApiError) -> HTTPException:
    # Map capacity / not found through; otherwise 502
    status = exc.status_code if exc.status_code in (400, 404, 409) else 502
    return HTTPException(status_code=status, detail={"code": "worker_error", "message": str(exc)})


@app.get("/health")
async def health() -> dict[str, Any]:
    wh = await worker.health()
    worker_ok = wh is not None
    return {
        "status": "ok" if worker_ok else "degraded",
        "contract_version": CONTRACT_VERSION,
        "node_id": settings.node_id,
        "worker": {
            "url": settings.worker_url,
            "online": worker_ok,
            "health": wh,
        },
        "detail": None if worker_ok else "Heimserver worker offline – chat/structured unavailable",
    }


@app.get("/v1/personas")
def list_personas() -> dict[str, Any]:
    return {
        "personas": chat_service.list_personas(),
        "default_persona": settings.default_persona,
    }


@app.get("/v1/profiles")
def list_profiles() -> dict[str, Any]:
    return {
        "profiles": [
            {
                "id": p.id,
                "roles": list(p.roles),
                "grammar": p.grammar,
                "capabilities": list(p.capabilities),
            }
            for p in DEFAULT_PROFILES
        ]
    }


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    try:
        data = await worker.list_models()
        return {"ok": True, "worker_online": True, **data}
    except WorkerOfflineError as exc:
        raise _offline_http(exc) from exc
    except WorkerApiError as exc:
        raise _worker_http(exc) from exc


@app.post("/v1/chat")
async def chat(body: ChatRequest):
    try:
        messages = [m.model_dump() for m in body.messages]
        result = await chat_service.chat(
            messages=messages,
            persona=body.persona,
            model=body.model,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            stream=body.stream,
        )
        if body.stream:
            assert isinstance(result, AsyncIterator)

            async def event_gen():
                try:
                    async for chunk in result:
                        yield chunk
                except WorkerOfflineError as exc:
                    import json

                    err = {"type": "error", "code": "worker_offline", "message": str(exc)}
                    yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
                except WorkerApiError as exc:
                    import json

                    err = {"type": "error", "code": "worker_error", "message": str(exc)}
                    yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

            return StreamingResponse(event_gen(), media_type="text/event-stream")
        return result
    except RoutingError as exc:
        raise HTTPException(status_code=400, detail={"code": "routing_error", "message": str(exc)}) from exc
    except WorkerOfflineError as exc:
        raise _offline_http(exc) from exc
    except WorkerApiError as exc:
        raise _worker_http(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=400, detail={"code": "bad_request", "message": str(exc)}) from exc


@app.post("/v1/structured")
async def structured(body: StructuredRequest) -> dict[str, Any]:
    try:
        messages = [m.model_dump() for m in body.messages] if body.messages else None
        return await chat_service.structured(
            prompt=body.prompt,
            messages=messages,
            model=body.model,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            grammar_file=body.grammar_file,
            grammar=body.grammar,
        )
    except RoutingError as exc:
        raise HTTPException(status_code=400, detail={"code": "routing_error", "message": str(exc)}) from exc
    except WorkerOfflineError as exc:
        raise _offline_http(exc) from exc
    except WorkerApiError as exc:
        raise _worker_http(exc) from exc


@app.get("/")
def index() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="Chat UI not found")
    return FileResponse(index_path)


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
