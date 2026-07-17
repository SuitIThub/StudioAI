"""StudioAI indexing / search CLI (Stage 3)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from studio_ai_core.bridge import BridgeClient
from studio_ai_core.config import camera_policy_from_settings, settings_from_config
from studio_ai_core.indexing.pipeline import IndexingService
from studio_ai_core.indexing.posecode import derive_posecode
from studio_ai_core.indexing.store import PoseIndexStore
from studio_ai_core.worker_client import WorkerClient


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
    """Capture (optional) + describe + merge + store."""
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="studio-ai", description="StudioAI Core CLI (Stage 3)")
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
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("describe", help="Capture/offline -> JoyCaption -> merge -> store")
    p.add_argument("--folder", help="Offline folder with pose_compact.txt")
    p.add_argument("--character", type=int, default=None)
    p.add_argument("--pose-path", default=None)
    p.add_argument("--size", type=int, default=512)
    p.add_argument("--no-joycaption", action="store_true")
    p.add_argument("--no-merge", action="store_true")
    p.set_defaults(func=cmd_describe_index)

    args = parser.parse_args(argv)
    if args.cmd == "describe" and not args.folder and args.character is None:
        parser.error("describe requires --folder or --character")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
