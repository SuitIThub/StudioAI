"""StudioAI indexing / search CLI (Stage 3)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

from studio_ai_core.bridge import BridgeClient
from studio_ai_core.config import camera_policy_from_settings, settings_from_config
from studio_ai_core.core_ports import resolve_core_base_url
from studio_ai_core.indexing.pipeline import IndexingService
from studio_ai_core.indexing.posecode import derive_posecode
from studio_ai_core.indexing.store import PoseIndexStore
from studio_ai_core.worker_client import WorkerClient


_core_base_cached: str | None = None


def _core_base() -> str:
    global _core_base_cached
    if _core_base_cached:
        return _core_base_cached
    hint = os.environ.get("STUDIO_AI_CORE_URL")
    if not hint:
        settings = settings_from_config()
        hint = f"http://127.0.0.1:{settings.port}"
    try:
        _core_base_cached = resolve_core_base_url(hint)
    except RuntimeError:
        _core_base_cached = hint.rstrip("/")
    return _core_base_cached


def _core_online(timeout: float = 2.0) -> bool:
    try:
        base = _core_base()
        with httpx.Client(timeout=timeout) as client:
            r = client.get(f"{base}/health")
            return r.status_code < 500
    except (httpx.HTTPError, RuntimeError):
        return False


def _service(skip_merge: bool = False) -> IndexingService:
    settings = settings_from_config()
    store = PoseIndexStore(settings.index_db_path)
    worker = WorkerClient(
        settings.worker_url,
        token=settings.worker_token,
        timeout_s=settings.worker_timeout_s,
        health_timeout_s=settings.health_timeout_s,
    )
    bridge = BridgeClient(settings.bridge_url, token=settings.bridge_token)
    return IndexingService(
        store=store,
        worker=worker,
        bridge=bridge,
        camera_policy=camera_policy_from_settings(settings),
        capture_dir=settings.capture_dir,
        grammars_dir=settings.grammars_dir,
        skip_merge=skip_merge,
        caption_preset=settings.caption_preset,
        joycaption_quant=settings.joycaption_quant,
    )


def cmd_search(args: argparse.Namespace) -> int:
    settings = settings_from_config()
    store = PoseIndexStore(settings.index_db_path)
    hits = store.search(args.query, limit=args.limit)
    print(f"query={args.query!r}  hits={len(hits)}  db={settings.index_db_path}")
    for i, h in enumerate(hits, 1):
        print(f"{i:2}. {h.pose_id}  score={h.score:.3f}")
        print(f"    {h.description[:160]}")
        print(f"    tags={h.tags}")
    return 0


def cmd_posecode(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    result = derive_posecode(text)
    print(json.dumps({"text": result.text, "tags": result.tags, "details": result.details}, indent=2))
    return 0


def cmd_index_folder(args: argparse.Namespace) -> int:
    svc = _service(skip_merge=args.no_merge)

    async def run():
        return await svc.index_offline_folder(
            Path(args.folder),
            use_joycaption=args.joycaption,
            use_merge=not args.no_merge,
        )

    out = asyncio.run(run())
    print(json.dumps({k: out[k] for k in out if k != "stored"}, indent=2, ensure_ascii=False))
    print("stored pose_id:", out["pose_id"])
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    svc = _service(skip_merge=args.no_merge)

    async def run():
        return await svc.batch_index_dir(
            Path(args.root),
            use_joycaption=args.joycaption,
            use_merge=not args.no_merge,
            limit=args.limit,
        )

    out = asyncio.run(run())
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("ok") else 1


def cmd_capture(args: argparse.Namespace) -> int:
    # Prefer Core when running – keeps Bridge client centralized
    if not getattr(args, "local", False) and _core_online():
        body: dict = {
            "character_id": args.character,
            "pose_path": args.pose_path,
            "size": args.size,
        }
        if args.views:
            body["views"] = args.views.split(",")
        with httpx.Client(base_url=_core_base(), timeout=180.0) as client:
            resp = client.post("/v1/capture", json=body)
            print(resp.text)
            resp.raise_for_status()
        return 0

    svc = _service()

    async def run():
        return await svc.capture(
            character_id=args.character,
            pose_path=args.pose_path,
            views=args.views.split(",") if args.views else None,
            size=args.size,
        )

    out = asyncio.run(run())
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_describe_index(args: argparse.Namespace) -> int:
    """Capture (optional) + describe + merge + store.

    Prefer Core HTTP so JoyCaption stays warm across runs (much faster after first load).
    Use --local to force in-process pipeline (cold-loads the VLM each time).
    """
    if not getattr(args, "local", False) and _core_online():
        body: dict = {
            "use_joycaption": not args.no_joycaption,
            "use_merge": not args.no_merge,
            "size": args.size,
        }
        if args.folder:
            body["folder"] = args.folder
        else:
            body["character_id"] = args.character
            body["pose_path"] = args.pose_path
        print(f"(via Core {_core_base()} – JoyCaption stays loaded after first call)", file=sys.stderr)
        with httpx.Client(base_url=_core_base(), timeout=600.0) as client:
            resp = client.post("/v1/describe", json=body)
            print(resp.text)
            if resp.status_code >= 400:
                print(resp.text, file=sys.stderr)
                return 1
        return 0

    print("(local mode – JoyCaption loads into this process each run)", file=sys.stderr)
    svc = _service(skip_merge=args.no_merge)

    async def run():
        if args.folder:
            return await svc.index_offline_folder(
                Path(args.folder),
                use_joycaption=not args.no_joycaption,
                use_merge=not args.no_merge,
            )
        cap = await svc.capture(
            character_id=args.character,
            pose_path=args.pose_path,
            size=args.size,
        )
        return await svc.index_from_capture(
            cap,
            use_joycaption=not args.no_joycaption,
            use_merge=not args.no_merge,
        )

    out = asyncio.run(run())
    print(json.dumps({k: out[k] for k in out if k != "stored"}, indent=2, ensure_ascii=False))
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    """OnDemand scene feedback via Core (JoyCaption stays warm)."""
    if not _core_online():
        print("Core offline – start studio-ai-core first.", file=sys.stderr)
        return 1
    body: dict = {
        "character_id": args.character,
        "camera_source": args.camera,
        "size": args.size,
        "polish_with_chat": args.polish,
    }
    if args.preset:
        body["caption_preset"] = args.preset
    if args.instruction:
        body["instruction"] = args.instruction
    if args.image:
        body["image_path"] = args.image
    print(f"(via Core {_core_base()})", file=sys.stderr)
    with httpx.Client(base_url=_core_base(), timeout=600.0) as client:
        if args.watch:
            resp = client.post(
                "/v1/scene-feedback/watch/start",
                json={
                    "character_id": args.character,
                    "camera_source": args.camera,
                    "caption_preset": args.preset,
                    "instruction": args.instruction,
                    "polish_with_chat": args.polish,
                    "size": args.size,
                    "debounce_s": args.debounce,
                },
            )
        else:
            resp = client.post("/v1/scene-feedback/analyze", json=body)
        print(resp.text)
        if resp.status_code >= 400:
            return 1
    return 0


def cmd_feedback_stop(args: argparse.Namespace) -> int:
    if not _core_online():
        print("Core offline.", file=sys.stderr)
        return 1
    with httpx.Client(base_url=_core_base(), timeout=30.0) as client:
        resp = client.post("/v1/scene-feedback/watch/stop")
        print(resp.text)
        return 0 if resp.status_code < 400 else 1


def cmd_feedback_status(args: argparse.Namespace) -> int:
    if not _core_online():
        print("Core offline.", file=sys.stderr)
        return 1
    with httpx.Client(base_url=_core_base(), timeout=30.0) as client:
        resp = client.get("/v1/scene-feedback/status")
        print(resp.text)
        return 0 if resp.status_code < 400 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="studio-ai", description="StudioAI Core CLI (Stage 4)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="FTS search over indexed poses")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("posecode", help="Derive rule-based posecode from pose_compact text")
    p.add_argument("--file", "-f", help="pose_compact.txt path (default: stdin)")
    p.set_defaults(func=cmd_posecode)

    p = sub.add_parser("index-folder", help="Index one offline capture folder")
    p.add_argument("folder")
    p.add_argument("--joycaption", action="store_true")
    p.add_argument("--no-merge", action="store_true")
    p.set_defaults(func=cmd_index_folder)

    p = sub.add_parser("batch", help="Batch-index offline folders under a root")
    p.add_argument("root")
    p.add_argument("--joycaption", action="store_true")
    p.add_argument("--no-merge", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("capture", help="Capture views via StudioPoseBridge (live Studio)")
    p.add_argument("--character", type=int, required=True)
    p.add_argument("--pose-path", default=None)
    p.add_argument("--views", default=None, help="comma list, e.g. front,three_quarter")
    p.add_argument("--size", type=int, default=512)
    p.add_argument("--local", action="store_true", help="Bypass Core; run in this process")
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("describe", help="Capture/offline -> JoyCaption -> merge -> store")
    p.add_argument("--folder", help="Offline folder with pose_compact.txt")
    p.add_argument("--character", type=int, default=None)
    p.add_argument("--pose-path", default=None)
    p.add_argument("--size", type=int, default=512)
    p.add_argument("--no-joycaption", action="store_true")
    p.add_argument("--no-merge", action="store_true")
    p.add_argument(
        "--local",
        action="store_true",
        help="Bypass Core (cold-loads JoyCaption every run – slow)",
    )
    p.set_defaults(func=cmd_describe_index)

    p = sub.add_parser("feedback", help="Scene feedback OnDemand (or --watch)")
    p.add_argument("--character", type=int, default=0)
    p.add_argument(
        "--camera",
        default="studio_active",
        help="studio_active (Camera.main) | front_full | three_quarter",
    )
    p.add_argument("--preset", default=None, help="scene_feedback | scene_critique | …")
    p.add_argument("--instruction", default=None, help="extra text appended to JoyCaption prompt")
    p.add_argument("--polish", action="store_true", help="optional Stheno tips after caption")
    p.add_argument("--size", type=int, default=768)
    p.add_argument("--image", default=None, help="offline PNG path (skip Bridge capture)")
    p.add_argument("--watch", action="store_true", help="start debounced Watch loop")
    p.add_argument("--debounce", type=float, default=None, help="Watch interval seconds")
    p.set_defaults(func=cmd_feedback)

    p = sub.add_parser("feedback-stop", help="Stop scene-feedback Watch")
    p.set_defaults(func=cmd_feedback_stop)

    p = sub.add_parser("feedback-status", help="Scene-feedback status + latest")
    p.set_defaults(func=cmd_feedback_status)

    args = parser.parse_args(argv)
    if args.cmd == "describe" and not args.folder and args.character is None:
        parser.error("describe requires --folder or --character")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
