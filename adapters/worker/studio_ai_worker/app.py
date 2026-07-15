"""FastAPI application for the StudioAI Worker."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from studio_ai_worker import CONTRACT_VERSION
from studio_ai_worker.backends.llamacpp import LlamaCppBackend
from studio_ai_worker.config import WorkerSettings, settings_from_config
from studio_ai_worker.manager import ModelManager, ModelManagerError

logger = logging.getLogger(__name__)

settings: WorkerSettings
manager: ModelManager


def get_manager() -> ModelManager:
    return manager


def verify_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.token:
        return
    expected = f"Bearer {settings.token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")


class SwapRequest(BaseModel):
    unload_id: str
    load_id: str


class CompletionRequest(BaseModel):
    model: str | None = None
    prompt: str
    max_tokens: int = 256
    temperature: float = 0.2
    grammar: str | None = None
    grammar_file: str | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    max_tokens: int = 512
    temperature: float = 0.7
    grammar: str | None = None
    grammar_file: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global settings, manager
    settings = settings_from_config()
    backend = LlamaCppBackend(
        bin_path=settings.llamacpp_bin,
        host=settings.llamacpp_host,
        base_port=settings.llamacpp_base_port,
        ctx_size=settings.llamacpp_ctx_size,
        n_gpu_layers=settings.llamacpp_n_gpu_layers,
        load_timeout_s=settings.load_timeout_s,
    )
    manager = ModelManager(
        registry_path=settings.registry_path,
        max_loaded=settings.max_loaded,
        backend=backend,
        grammars_dir=settings.grammars_dir,
    )
    logger.info(
        "Worker started (contract=%s, max_loaded=%s, registry=%s)",
        CONTRACT_VERSION,
        settings.max_loaded,
        settings.registry_path,
    )
    yield
    manager.shutdown()
    logger.info("Worker stopped")


app = FastAPI(title="StudioAI Worker", version=CONTRACT_VERSION, lifespan=lifespan)


def _mm_http(exc: ModelManagerError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@app.get("/health")
def health(_: None = Depends(verify_token)) -> dict[str, Any]:
    return {
        "status": "ok",
        "contract_version": CONTRACT_VERSION,
        "backend": settings.preferred_backend,
        "loaded_models": manager.backend.loaded_ids,
        "detail": None,
    }


@app.get("/models")
def list_models(_: None = Depends(verify_token)) -> dict[str, Any]:
    return {"models": manager.list_models(), "max_loaded": manager.max_loaded}


@app.post("/models/{model_id}/load")
def load_model(model_id: str, _: None = Depends(verify_token)) -> dict[str, Any]:
    try:
        return manager.load(model_id)
    except ModelManagerError as exc:
        raise _mm_http(exc) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("load failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/models/{model_id}/unload")
def unload_model(model_id: str, _: None = Depends(verify_token)) -> dict[str, Any]:
    try:
        return manager.unload(model_id)
    except ModelManagerError as exc:
        raise _mm_http(exc) from exc


@app.post("/models/swap")
def swap_models(body: SwapRequest, _: None = Depends(verify_token)) -> dict[str, Any]:
    try:
        return manager.swap(body.unload_id, body.load_id)
    except ModelManagerError as exc:
        raise _mm_http(exc) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("swap failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/completions")
async def completions(body: CompletionRequest, _: None = Depends(verify_token)) -> dict[str, Any]:
    try:
        model_id = manager.resolve_default_model(body.model)
        if not manager.backend.is_loaded(model_id):
            manager.load(model_id)
        grammar = manager.read_grammar(body.grammar, body.grammar_file)
        return await manager.backend.completion(
            model_id,
            prompt=body.prompt,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            grammar=grammar,
        )
    except ModelManagerError as exc:
        raise _mm_http(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("completion failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest, _: None = Depends(verify_token)
) -> dict[str, Any]:
    try:
        model_id = manager.resolve_default_model(body.model)
        if not manager.backend.is_loaded(model_id):
            manager.load(model_id)
        grammar = manager.read_grammar(body.grammar, body.grammar_file)
        return await manager.backend.chat(
            model_id,
            messages=[m.model_dump() for m in body.messages],
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            grammar=grammar,
        )
    except ModelManagerError as exc:
        raise _mm_http(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("chat failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
