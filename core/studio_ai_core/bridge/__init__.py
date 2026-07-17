"""HTTP client for StudioPoseBridge (thin I/O – no business logic)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from studio_ai_core.indexing.cameras import CameraPolicy, bridge_angle_for_view
from studio_ai_core.indexing.posecode import format_pose_compact_from_regions

logger = logging.getLogger(__name__)


class BridgeError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class BridgeOfflineError(BridgeError):
    def __init__(self, message: str = "Studio bridge is offline") -> None:
        super().__init__(message, status_code=503)
        self.code = "bridge_offline"


class BridgeClient:
    """Talks to StudioPoseBridge (default http://127.0.0.1:7842)."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:7842",
        *,
        token: str = "",
        timeout_s: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.token:
            h["X-Pose-Token"] = self.token
        return h

    async def health(self) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/v1/health")
                if resp.status_code >= 400:
                    return None
                return resp.json()
        except httpx.HTTPError:
            return None

    async def list_characters(self) -> list[dict[str, Any]]:
        data = await self._json("GET", "/v1/characters")
        # Bridge wraps in {ok, data:{characters:[]}} or similar
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        chars = (payload or {}).get("characters") or data.get("characters") or []
        return chars if isinstance(chars, list) else []

    async def get_pose(self, character_id: int, *, regions: str | None = None) -> dict[str, Any]:
        q = f"?regions={regions}" if regions else ""
        data = await self._json("GET", f"/v1/characters/{character_id}/pose{q}")
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        return payload or data

    async def screenshot_bytes(
        self,
        character_id: int,
        *,
        angle: str = "front",
        size: int = 512,
        framing: str = "full_body",
        fmt: str = "png",
    ) -> bytes:
        params = {
            "angle": angle,
            "size": str(size),
            "framing": framing,
            "format": fmt,
        }
        url = f"{self.base_url}/v1/characters/{character_id}/screenshot"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.get(url, headers=self._headers(), params=params)
        except httpx.HTTPError as exc:
            raise BridgeOfflineError(f"Bridge unreachable ({self.base_url}): {exc}") from exc
        if resp.status_code >= 400:
            raise BridgeError(
                f"Screenshot failed {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
            )
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype:
            # Some bridge versions wrap base64 in JSON
            data = resp.json()
            payload = data.get("data") or data
            b64 = payload.get("png_base64") or payload.get("image_base64")
            if b64:
                import base64

                return base64.b64decode(b64)
            raise BridgeError("Screenshot JSON response missing image bytes")
        return resp.content

    async def apply_and_capture(
        self,
        *,
        character_id: int,
        views: list[str],
        policy: CameraPolicy,
        out_dir: Path,
        pose_path: str | None = None,
        size: int = 512,
        framing: str = "full_body",
        regions: str = "torso,left_arm,right_arm,left_leg,right_leg",
    ) -> dict[str, Any]:
        """
        Prefer composite Bridge endpoint if present; else capture-only using current pose.
        pose_path apply requires Bridge extension (see adapters/bridge/README.md).
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Try composite endpoint first
        if pose_path:
            try:
                body = {
                    "pose_path": pose_path,
                    "character_id": character_id,
                    "views": views,
                    "size": size,
                    "framing": framing,
                }
                data = await self._json("POST", "/v1/indexing/apply-and-capture", json_body=body)
                return data.get("data") or data
            except BridgeError as exc:
                if exc.status_code not in (404, 405):
                    logger.warning("apply-and-capture unavailable (%s); capture-only fallback", exc)

        pose = await self.get_pose(character_id, regions=regions)
        pose_compact = format_pose_compact_from_regions(pose)
        captures: dict[str, str] = {}
        for view in views:
            angle = bridge_angle_for_view(view, policy)
            png = await self.screenshot_bytes(
                character_id, angle=angle, size=size, framing=framing
            )
            dest = out_dir / f"{view}.png"
            dest.write_bytes(png)
            captures[view] = str(dest.resolve())

        return {
            "character_id": character_id,
            "pose_path": pose_path,
            "pose_compact": pose_compact,
            "captures": captures,
            "applied": False,
            "mode": "capture_only",
        }

    async def _json(
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
            raise BridgeOfflineError(f"Bridge unreachable ({self.base_url}): {exc}") from exc
        if resp.status_code >= 400:
            raise BridgeError(
                f"Bridge error {resp.status_code}: {resp.text[:800]}",
                status_code=resp.status_code,
            )
        if not resp.content:
            return {}
        return resp.json()
