"""StudioAI Core FastAPI – Stage 4 chat + indexing + scene feedback."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from studio_ai_core import CONTRACT_VERSION
from studio_ai_core.bridge import BridgeClient, BridgeError, BridgeOfflineError
from studio_ai_core.chat_service import ChatService
from studio_ai_core.config import camera_policy_from_settings, settings_from_config
from studio_ai_core.indexing import INDEX_VERSION
from studio_ai_core.indexing.joycaption import JoyCaptionClient, JoyCaptionUnavailable
from studio_ai_core.indexing.pipeline import IndexingService
from studio_ai_core.indexing.store import PoseIndexStore
from studio_ai_core.profiles import DEFAULT_PROFILES
from studio_ai_core.routing import RoutingError
from studio_ai_core.scene_feedback import SceneFeedbackService
from studio_ai_core.vision_gate import VisionGate
from studio_ai_core.worker_client import WorkerApiError, WorkerClient, WorkerOfflineError

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

settings = None
worker: WorkerClient
chat_service: ChatService
store: PoseIndexStore
indexing: IndexingService
bridge: BridgeClient
vision_gate: VisionGate
scene_feedback: SceneFeedbackService
joycaption: JoyCaptionClient


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    persona: str | None = None
    model: str | None = None
    max_tokens: int | None = None
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


class PosecodeRequest(BaseModel):
    pose_compact: str


class CaptureRequest(BaseModel):
    character_id: int
    pose_path: str | None = None
    views: list[str] | None = None
    size: int = 512


class DescribeRequest(BaseModel):
    folder: str | None = None
    character_id: int | None = None
    pose_path: str | None = None
    size: int = 512
    use_joycaption: bool = True
    use_merge: bool = True


class IndexFolderRequest(BaseModel):
    folder: str
    use_joycaption: bool = False
    use_merge: bool = True


class BatchIndexRequest(BaseModel):
    root: str
    use_joycaption: bool = False
    use_merge: bool = True
    limit: int | None = None


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=20, ge=1, le=100)


class SceneFeedbackAnalyzeRequest(BaseModel):
    character_id: int = 0
    caption_preset: str | None = None
    camera_source: str = "studio_active"
    instruction: str | None = None
    polish_with_chat: bool | None = None
    size: int = 768
    image_path: str | None = None


class SceneFeedbackWatchRequest(BaseModel):
    character_id: int = 0
    caption_preset: str | None = None
    camera_source: str = "studio_active"
    instruction: str | None = None
    polish_with_chat: bool | None = None
    size: int = 768
    debounce_s: float | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global settings, worker, chat_service, store, indexing, bridge
    global vision_gate, scene_feedback, joycaption
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
    store = PoseIndexStore(settings.index_db_path)
    bridge = BridgeClient(settings.bridge_url, token=settings.bridge_token)
    vision_gate = VisionGate()
    joycaption = JoyCaptionClient()
    indexing = IndexingService(
        store=store,
        worker=worker,
        bridge=bridge,
        joycaption=joycaption,
        camera_policy=camera_policy_from_settings(settings),
        capture_dir=settings.capture_dir,
        grammars_dir=settings.grammars_dir,
        caption_preset=settings.caption_preset,
        joycaption_quant=settings.joycaption_quant,
        vision_gate=vision_gate,
    )
    scene_feedback = SceneFeedbackService(
        bridge=bridge,
        joycaption=joycaption,
        vision_gate=vision_gate,
        chat=chat_service,
        capture_dir=settings.capture_dir,
        joycaption_quant=settings.joycaption_quant,
        default_preset=settings.feedback_preset,
        default_debounce_s=settings.feedback_debounce_s,
        default_polish=settings.feedback_polish,
    )
    logger.info(
        "Core started (contract=%s, index=%s, worker=%s, bridge=%s)",
        CONTRACT_VERSION,
        INDEX_VERSION,
        settings.worker_url,
        settings.bridge_url,
    )
    yield
    await scene_feedback.watch_stop()
    store.close()
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
    status = exc.status_code if exc.status_code in (400, 404, 409) else 502
    return HTTPException(status_code=status, detail={"code": "worker_error", "message": str(exc)})


def _bridge_http(exc: BridgeError) -> HTTPException:
    code = getattr(exc, "code", "bridge_error")
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": code, "message": str(exc)},
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    wh = await worker.health()
    worker_ok = wh is not None
    bh = await bridge.health()
    bridge_ok = bh is not None
    status = "ok" if worker_ok else "degraded"
    return {
        "status": status,
        "contract_version": CONTRACT_VERSION,
        "index_version": INDEX_VERSION,
        "node_id": settings.node_id,
        "worker": {"url": settings.worker_url, "online": worker_ok, "health": wh},
        "bridge": {"url": settings.bridge_url, "online": bridge_ok, "health": bh},
        "index": {"db": str(settings.index_db_path), "count": store.count()},
        "vision": vision_gate.status(),
        "scene_feedback": {
            "watch_running": bool(
                scene_feedback._watch_task and not scene_feedback._watch_task.done()
            ),
            "analyze_count": scene_feedback._analyze_count,
        },
        "detail": None if worker_ok else "Heimserver worker offline – chat/merge unavailable",
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


@app.post("/v1/posecode")
def posecode(body: PosecodeRequest) -> dict[str, Any]:
    return indexing.derive_posecode_only(body.pose_compact)


@app.post("/v1/capture")
async def capture(body: CaptureRequest) -> dict[str, Any]:
    try:
        return await indexing.capture(
            character_id=body.character_id,
            pose_path=body.pose_path,
            views=body.views,
            size=body.size,
        )
    except BridgeOfflineError as exc:
        raise _bridge_http(exc) from exc
    except BridgeError as exc:
        raise _bridge_http(exc) from exc


@app.post("/v1/describe")
async def describe(body: DescribeRequest) -> dict[str, Any]:
    try:
        if body.folder:
            return await indexing.index_offline_folder(
                Path(body.folder),
                use_joycaption=body.use_joycaption,
                use_merge=body.use_merge,
            )
        if body.character_id is None:
            raise HTTPException(
                status_code=400,
                detail={"code": "bad_request", "message": "folder or character_id required"},
            )
        cap = await indexing.capture(
            character_id=body.character_id,
            pose_path=body.pose_path,
            size=body.size,
        )
        return await indexing.index_from_capture(
            cap,
            use_joycaption=body.use_joycaption,
            use_merge=body.use_merge,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": str(exc)}) from exc
    except JoyCaptionUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "joycaption_unavailable", "message": str(exc)},
        ) from exc
    except BridgeOfflineError as exc:
        raise _bridge_http(exc) from exc
    except BridgeError as exc:
        raise _bridge_http(exc) from exc


@app.post("/v1/index/folder")
async def index_folder(body: IndexFolderRequest) -> dict[str, Any]:
    try:
        return await indexing.index_offline_folder(
            Path(body.folder),
            use_joycaption=body.use_joycaption,
            use_merge=body.use_merge,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": str(exc)}) from exc


@app.post("/v1/index/batch")
async def index_batch(body: BatchIndexRequest) -> dict[str, Any]:
    return await indexing.batch_index_dir(
        Path(body.root),
        use_joycaption=body.use_joycaption,
        use_merge=body.use_merge,
        limit=body.limit,
    )


@app.post("/v1/search")
def search(body: SearchRequest) -> dict[str, Any]:
    hits = store.search(body.query, limit=body.limit)
    return {
        "query": body.query,
        "count": len(hits),
        "hits": [
            {
                "pose_id": h.pose_id,
                "path": h.path,
                "description": h.description,
                "tags": h.tags,
                "score": h.score,
                "snippet": h.snippet,
            }
            for h in hits
        ],
    }


@app.get("/v1/poses/{pose_id}")
def get_pose(pose_id: str) -> dict[str, Any]:
    row = store.get(pose_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": pose_id})
    return row


@app.post("/v1/scene-feedback/analyze")
async def scene_feedback_analyze(body: SceneFeedbackAnalyzeRequest) -> dict[str, Any]:
    try:
        return await scene_feedback.analyze(
            character_id=body.character_id,
            caption_preset=body.caption_preset,
            camera_source=body.camera_source,
            instruction=body.instruction,
            polish_with_chat=body.polish_with_chat,
            size=body.size,
            image_path=body.image_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "bad_request", "message": str(exc)}) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": str(exc)}) from exc
    except JoyCaptionUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "joycaption_unavailable", "message": str(exc)},
        ) from exc
    except BridgeOfflineError as exc:
        raise _bridge_http(exc) from exc
    except BridgeError as exc:
        raise _bridge_http(exc) from exc


@app.post("/v1/scene-feedback/watch/start")
async def scene_feedback_watch_start(body: SceneFeedbackWatchRequest) -> dict[str, Any]:
    try:
        return await scene_feedback.watch_start(
            character_id=body.character_id,
            caption_preset=body.caption_preset,
            camera_source=body.camera_source,
            instruction=body.instruction,
            polish_with_chat=body.polish_with_chat,
            size=body.size,
            debounce_s=body.debounce_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "bad_request", "message": str(exc)}) from exc


@app.post("/v1/scene-feedback/watch/stop")
async def scene_feedback_watch_stop() -> dict[str, Any]:
    return await scene_feedback.watch_stop()


@app.get("/v1/scene-feedback/status")
def scene_feedback_status() -> dict[str, Any]:
    return scene_feedback.status()


@app.get("/v1/scene-feedback/latest")
def scene_feedback_latest() -> dict[str, Any]:
    if scene_feedback.latest is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "no feedback result yet"},
        )
    return scene_feedback.latest


@app.get("/")
def index() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="Chat UI not found")
    return FileResponse(index_path)


@app.get("/feedback")
def feedback_page() -> FileResponse:
    path = STATIC_DIR / "feedback.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Feedback UI not found")
    return FileResponse(path)


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
