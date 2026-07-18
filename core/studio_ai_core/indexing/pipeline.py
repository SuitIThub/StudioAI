"""Indexing pipeline: capture → posecode → describe → merge → store."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from studio_ai_core.bridge import BridgeClient, BridgeError
from studio_ai_core.indexing import INDEX_VERSION
from studio_ai_core.indexing.cameras import CameraPolicy, resolve_views
from studio_ai_core.indexing.joycaption import INDEX_CAPTION_TYPE, JoyCaptionClient, JoyCaptionUnavailable
from studio_ai_core.indexing.merge import fallback_index_entry, merge_index_entry
from studio_ai_core.indexing.posecode import derive_posecode
from studio_ai_core.indexing.store import PoseIndexStore
from studio_ai_core.vision_gate import VisionGate
from studio_ai_core.worker_client import WorkerClient, WorkerOfflineError

logger = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"[^a-zA-Z0-9._\-]+")


def pose_id_from_path(path: str | Path | None) -> str:
    if not path:
        return str(uuid.uuid4())
    p = Path(path)
    stem = p.stem if p.suffix else p.name
    cleaned = _SAFE_ID.sub("_", stem).strip("_")
    return cleaned or str(uuid.uuid4())


class IndexingService:
    def __init__(
        self,
        *,
        store: PoseIndexStore,
        worker: WorkerClient,
        bridge: BridgeClient | None = None,
        joycaption: JoyCaptionClient | None = None,
        camera_policy: CameraPolicy | None = None,
        capture_dir: Path,
        grammars_dir: Path | None = None,
        skip_merge: bool = False,
        caption_preset: str = INDEX_CAPTION_TYPE,
        joycaption_quant: str = "8bit",
        vision_gate: VisionGate | None = None,
    ) -> None:
        self.store = store
        self.worker = worker
        self.bridge = bridge
        self.joycaption = joycaption or JoyCaptionClient()
        self.camera_policy = camera_policy or CameraPolicy()
        self.capture_dir = Path(capture_dir)
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.grammars_dir = Path(grammars_dir) if grammars_dir else None
        self.skip_merge = skip_merge
        self.caption_preset = caption_preset
        self.joycaption_quant = joycaption_quant
        self.vision_gate = vision_gate or VisionGate()

    def _ensure_joycaption(self) -> None:
        if not self.joycaption.loaded:
            quant = self.joycaption_quant if self.joycaption_quant in ("bf16", "8bit", "nf4") else None
            self.joycaption.load(quant=quant)  # type: ignore[arg-type]

    def derive_posecode_only(self, pose_compact: str) -> dict[str, Any]:
        result = derive_posecode(pose_compact)
        return {
            "posecode_text": result.text,
            "posecode_tags": result.tags,
            "details": result.details,
            "needs_one_quarter": bool(result.details.get("unusual_rotation")),
        }

    async def capture(
        self,
        *,
        character_id: int,
        pose_path: str | None = None,
        views: list[str] | None = None,
        size: int = 512,
    ) -> dict[str, Any]:
        if self.bridge is None:
            raise BridgeError("Bridge not configured", status_code=503)

        # First pass without one_quarter; refine after posecode if auto
        initial_views = views or list(self.camera_policy.always)
        out = self.capture_dir / (pose_id_from_path(pose_path) if pose_path else f"char{character_id}")
        result = await self.bridge.apply_and_capture(
            character_id=character_id,
            views=initial_views,
            policy=self.camera_policy,
            out_dir=out,
            pose_path=pose_path,
            size=size,
        )
        compact = result.get("pose_compact") or ""
        pc = derive_posecode(compact)
        final_views = views or resolve_views(self.camera_policy, pc)
        missing = [v for v in final_views if v not in (result.get("captures") or {})]
        if missing:
            extra = await self.bridge.apply_and_capture(
                character_id=character_id,
                views=missing,
                policy=self.camera_policy,
                out_dir=out,
                pose_path=None,
                size=size,
            )
            captures = dict(result.get("captures") or {})
            captures.update(extra.get("captures") or {})
            result["captures"] = captures
            if extra.get("pose_compact"):
                result["pose_compact"] = extra["pose_compact"]
                compact = extra["pose_compact"]
                pc = derive_posecode(compact)

        result["posecode"] = {
            "text": pc.text,
            "tags": pc.tags,
            "details": pc.details,
        }
        result["views"] = list((result.get("captures") or {}).keys())
        return result

    async def describe_images(
        self,
        captures: dict[str, str],
        *,
        caption_type: str | None = None,
        load_model: bool = True,
    ) -> dict[str, str]:
        """Caption capture paths under the shared VisionGate (blocks Watch)."""

        def _run() -> dict[str, str]:
            if load_model:
                logger.info("JoyCaption ensure/load quant=%s", self.joycaption_quant)
                self._ensure_joycaption()
            preset = caption_type or self.caption_preset
            out: dict[str, str] = {}
            for view, path in captures.items():
                logger.info("JoyCaption caption view=%s path=%s preset=%s", view, path, preset)
                out[view] = self.joycaption.caption_path(path, caption_type=preset)
                logger.info("JoyCaption caption done view=%s chars=%s", view, len(out[view]))
            return out

        async with self.vision_gate.hold("index"):
            return await asyncio.to_thread(_run)

    async def index_offline_folder(
        self,
        folder: Path,
        *,
        pose_id: str | None = None,
        use_joycaption: bool = False,
        use_merge: bool = True,
    ) -> dict[str, Any]:
        """
        Index a folder with:
          pose_compact.txt (required)
          front.png / three_quarter.png / one_quarter.png (optional)
          captions.json (optional precomputed captions)
        """
        folder = Path(folder)
        compact_path = folder / "pose_compact.txt"
        if not compact_path.is_file():
            raise FileNotFoundError(f"Missing pose_compact.txt in {folder}")
        compact = compact_path.read_text(encoding="utf-8")
        pc = derive_posecode(compact)

        captions: dict[str, str] = {}
        cap_file = folder / "captions.json"
        if cap_file.is_file():
            captions = json.loads(cap_file.read_text(encoding="utf-8"))

        captures: dict[str, str] = {}
        for view in ("front", "three_quarter", "one_quarter", "front_full"):
            png = folder / f"{view}.png"
            if png.is_file():
                captures[view] = str(png.resolve())

        if use_joycaption and captures:
            missing = {v: p for v, p in captures.items() if v not in captions}
            if missing:
                self.vision_gate.begin_index()
                try:
                    captions.update(await self.describe_images(missing))
                finally:
                    self.vision_gate.end_index()

        return await self._finalize_index(
            pose_id=pose_id or pose_id_from_path(folder),
            path=str(folder.resolve()),
            compact=compact,
            pc_text=pc.text,
            pc_tags=pc.tags,
            captures=captures,
            captions=captions,
            use_merge=use_merge,
        )

    async def index_from_capture(
        self,
        capture_result: dict[str, Any],
        *,
        pose_id: str | None = None,
        use_joycaption: bool = True,
        use_merge: bool = True,
        captions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        compact = capture_result.get("pose_compact") or ""
        pc = derive_posecode(compact)
        captures = {k: str(v) for k, v in (capture_result.get("captures") or {}).items()}
        caps = dict(captions or {})
        if use_joycaption:
            missing = {v: p for v, p in captures.items() if v not in caps}
            if not captures:
                logger.warning(
                    "index_from_capture: use_joycaption=True but no capture images — "
                    "JoyCaption skipped (posecode-only)"
                )
            elif not missing:
                logger.info("index_from_capture: captions already present for %s", list(caps.keys()))
            else:
                logger.info(
                    "index_from_capture: JoyCaption describing views=%s",
                    list(missing.keys()),
                )
                self.vision_gate.begin_index()
                try:
                    caps.update(await self.describe_images(missing))
                finally:
                    self.vision_gate.end_index()
                logger.info(
                    "index_from_capture: JoyCaption done views=%s lens=%s",
                    list(caps.keys()),
                    {k: len(v) for k, v in caps.items()},
                )
        return await self._finalize_index(
            pose_id=pose_id
            or pose_id_from_path(capture_result.get("pose_path"))
            or f"char{capture_result.get('character_id', 'x')}",
            path=capture_result.get("pose_path"),
            compact=compact,
            pc_text=pc.text,
            pc_tags=pc.tags,
            captures=captures,
            captions=caps,
            use_merge=use_merge,
        )

    async def _finalize_index(
        self,
        *,
        pose_id: str,
        path: str | None,
        compact: str,
        pc_text: str,
        pc_tags: list[str],
        captures: dict[str, str],
        captions: dict[str, str],
        use_merge: bool,
    ) -> dict[str, Any]:
        merge_meta: dict[str, Any]
        if use_merge and not self.skip_merge:
            try:
                merge_meta = await merge_index_entry(
                    self.worker,
                    posecode_text=pc_text,
                    posecode_tags=pc_tags,
                    captions=captions,
                    grammars_dir=self.grammars_dir,
                )
            except WorkerOfflineError:
                entry = fallback_index_entry(
                    posecode_tags=pc_tags, captions=captions, posecode_text=pc_text
                )
                merge_meta = {
                    "ok": False,
                    "source": "fallback_offline",
                    "entry": entry,
                    "error": "worker_offline",
                }
        else:
            entry = fallback_index_entry(
                posecode_tags=pc_tags, captions=captions, posecode_text=pc_text
            )
            merge_meta = {"ok": True, "source": "fallback_skip_merge", "entry": entry}

        entry = merge_meta["entry"]
        self.store.upsert(
            pose_id=pose_id,
            path=path,
            description=entry["description"],
            tags=entry["tags"],
            synonyms=entry.get("synonyms") or [],
            posecode_raw=compact,
            posecode_text=pc_text,
            posecode_tags=pc_tags,
            captures=captures,
            captions=captions,
            index_version=INDEX_VERSION,
        )
        return {
            "pose_id": pose_id,
            "index_version": INDEX_VERSION,
            "posecode_text": pc_text,
            "posecode_tags": pc_tags,
            "captions": captions,
            "merge": merge_meta,
            "stored": self.store.get(pose_id),
        }

    async def batch_index_dir(
        self,
        root: Path,
        *,
        use_joycaption: bool = False,
        use_merge: bool = True,
        limit: int | None = None,
    ) -> dict[str, Any]:
        root = Path(root)
        folders = sorted([p for p in root.iterdir() if p.is_dir() and (p / "pose_compact.txt").is_file()])
        if limit is not None:
            folders = folders[:limit]
        results = []
        errors = []
        if use_joycaption:
            self.vision_gate.begin_index()
        try:
            for folder in folders:
                try:
                    results.append(
                        await self.index_offline_folder(
                            folder, use_joycaption=use_joycaption, use_merge=use_merge
                        )
                    )
                except Exception as exc:
                    logger.exception("batch failed for %s", folder)
                    errors.append({"folder": str(folder), "error": str(exc)})
        finally:
            if use_joycaption:
                self.vision_gate.end_index()
        return {
            "ok": len(errors) == 0,
            "indexed": len(results),
            "errors": errors,
            "total_in_store": self.store.count(),
        }

    async def index_paths(
        self,
        paths: list[str],
        *,
        character_id: int = 0,
        use_joycaption: bool = True,
        use_merge: bool = True,
        size: int = 512,
        allow_stub: bool = False,
    ) -> dict[str, Any]:
        """Index explicit pose file/folder paths (PoseBrowser selection).

        Preferred path for library ``.png`` / pose files:
          Bridge capture (pose should already be applied by Plugin or Bridge) →
          JoyCaption → merge → SQLite.

        Folders with ``pose_compact.txt`` still use offline folder indexing.
        ``allow_stub=True`` keeps the old filename-only fallback (not for production tests).
        """
        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        for raw in paths:
            try:
                p = Path(raw)
                folder = p if p.is_dir() else p.parent
                compact = folder / "pose_compact.txt"
                if compact.is_file() and (p.is_dir() or not p.suffix):
                    logger.info("index_paths offline folder %s", folder)
                    out = await self.index_offline_folder(
                        folder, use_joycaption=use_joycaption, use_merge=use_merge
                    )
                    results.append(
                        {
                            "pose_id": out.get("pose_id"),
                            "path": str(folder),
                            "source": "offline_folder",
                            "index_version": out.get("index_version"),
                        }
                    )
                    continue

                if not p.exists() and not Path(raw).exists():
                    raise FileNotFoundError(f"path not found: {raw}")

                file_path = p if p.is_file() or p.suffix else p
                abs_path = str(file_path.resolve()) if file_path.exists() else str(Path(raw))
                pose_id = pose_id_from_path(abs_path) or file_path.stem

                # Live library files need JoyCaption (same as Phase-3 /v1/describe).
                # Without it, merge falls back to thin posecode text ("standing").
                live_jc = use_joycaption
                if not live_jc and not allow_stub:
                    logger.warning(
                        "index_paths: use_joycaption=false ignored for live capture "
                        "(set allow_stub=true to skip JoyCaption)"
                    )
                    live_jc = True

                logger.info(
                    "index_paths LIVE capture+describe pose_id=%s path=%s char=%s joycaption=%s",
                    pose_id,
                    abs_path,
                    character_id,
                    live_jc,
                )
                try:
                    cap = await self.capture(
                        character_id=character_id,
                        pose_path=abs_path,
                        size=size,
                    )
                    logger.info(
                        "index_paths capture ok pose_id=%s mode=%s views=%s applied=%s",
                        pose_id,
                        cap.get("mode"),
                        list((cap.get("captures") or {}).keys()),
                        cap.get("applied"),
                    )
                    # Ensure store path is the library file, not capture dir
                    cap["pose_path"] = abs_path
                    out = await self.index_from_capture(
                        cap,
                        pose_id=pose_id,
                        use_joycaption=live_jc,
                        use_merge=use_merge,
                    )
                    cap_keys = (
                        list((out.get("captions") or {}).keys())
                        if isinstance(out.get("captions"), dict)
                        else []
                    )
                    logger.info(
                        "index_paths describe done pose_id=%s caption_views=%s merge=%s",
                        pose_id,
                        cap_keys,
                        (out.get("merge") or {}).get("source")
                        if isinstance(out.get("merge"), dict)
                        else None,
                    )
                    results.append(
                        {
                            "pose_id": out.get("pose_id") or pose_id,
                            "path": abs_path,
                            "source": "live_capture",
                            "index_version": out.get("index_version"),
                            "captions": list((out.get("captions") or {}).keys())
                            if isinstance(out.get("captions"), dict)
                            else [],
                            "description": (out.get("stored") or {}).get("description")
                            if isinstance(out.get("stored"), dict)
                            else out.get("merge", {}).get("entry", {}).get("description")
                            if isinstance(out.get("merge"), dict)
                            else None,
                        }
                    )
                except (BridgeError, JoyCaptionUnavailable, WorkerOfflineError) as exc:
                    if allow_stub:
                        logger.warning(
                            "index_paths live failed (%s); stub fallback for %s",
                            exc,
                            abs_path,
                        )
                        desc = (file_path.stem or pose_id).replace("_", " ").replace("-", " ").strip()
                        tags = [t for t in (file_path.stem or pose_id).replace("-", "_").split("_") if t]
                        self.store.upsert(
                            pose_id=pose_id,
                            path=abs_path,
                            description=desc or pose_id,
                            tags=tags,
                            synonyms=[],
                            posecode_raw=None,
                            posecode_text=None,
                            posecode_tags=[],
                            captures={},
                            captions={},
                            index_version=INDEX_VERSION,
                        )
                        results.append(
                            {
                                "pose_id": pose_id,
                                "path": abs_path,
                                "source": "path_stub_fallback",
                                "index_version": INDEX_VERSION,
                                "error": str(exc),
                            }
                        )
                    else:
                        raise
            except Exception as exc:
                logger.exception("index_paths failed for %s", raw)
                errors.append({"path": str(raw), "error": str(exc)})

        items = [
            {
                "pose_id": r.get("pose_id"),
                "path": r.get("path"),
                "source": r.get("source") or "unknown",
                "description": r.get("description"),
            }
            for r in results
        ]
        out = {
            "ok": len(errors) == 0,
            "indexed": len(results),
            "errors": errors,
            "items": items,
            "total_in_store": self.store.count(),
        }
        logger.info(
            "index_paths done: indexed=%s errors=%s store=%s sample=%s",
            out["indexed"],
            len(errors),
            out["total_in_store"],
            items[:5],
        )
        return out
