"""HTTP client for StudioPoseBridge (thin I/O – no business logic)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from studio_ai_core.indexing.cameras import CameraPolicy, bridge_angle_for_view
from studio_ai_core.indexing.posecode import format_pose_compact_from_regions

logger = logging.getLogger(__name__)

BRIDGE_PORT_MIN = 7100
BRIDGE_PORT_MAX = 7199
# Discovery model: server binds one free port and keeps it; client walks the range
# once until health matches, then locks that URL for the process (no re-scan).
BRIDGE_DISCOVER_CONNECT_S = 0.15
BRIDGE_DISCOVER_READ_S = 2.5
BRIDGE_DISCOVER_TIMEOUT_S = BRIDGE_DISCOVER_READ_S


class BridgeError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class BridgeOfflineError(BridgeError):
    def __init__(self, message: str = "Studio bridge is offline") -> None:
        super().__init__(message, status_code=503)
        self.code = "bridge_offline"


def _parse_bridge_hint(base_url: str) -> tuple[str, int | None]:
    """Return (host, preferred_port_or_None) from a configured URL."""
    raw = (base_url or "").strip().rstrip("/")
    if not raw or raw.lower() in ("auto", "discover"):
        return "127.0.0.1", None
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    return host, port


def _port_scan_order(preferred: int | None) -> list[int]:
    """Walk 7100..7199; if preferred is in range, start there and wrap."""
    span = BRIDGE_PORT_MAX - BRIDGE_PORT_MIN + 1
    if preferred is not None and BRIDGE_PORT_MIN <= preferred <= BRIDGE_PORT_MAX:
        start = preferred
    else:
        start = BRIDGE_PORT_MIN
    return [
        BRIDGE_PORT_MIN + ((start - BRIDGE_PORT_MIN + i) % span) for i in range(span)
    ]


def is_bridge_health_payload(data: Any) -> bool:
    """True when GET /v1/health looks like StudioPoseBridge."""
    if not isinstance(data, dict):
        return False
    if data.get("ok") is False:
        return False
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(payload, dict):
        return False
    if payload.get("studio") == "neov2":
        return True
    return isinstance(payload.get("version"), str) and bool(payload.get("version"))


def _discover_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=BRIDGE_DISCOVER_CONNECT_S,
        read=BRIDGE_DISCOVER_READ_S,
        write=BRIDGE_DISCOVER_READ_S,
        pool=BRIDGE_DISCOVER_READ_S,
    )


async def _tcp_port_open(host: str, port: int, timeout_s: float = BRIDGE_DISCOVER_CONNECT_S) -> bool:
    """True if something accepts TCP on host:port (closed ports fail fast, no HTTP abort)."""
    try:
        conn = asyncio.open_connection(host, port)
        _reader, writer = await asyncio.wait_for(conn, timeout=timeout_s)
    except (OSError, asyncio.TimeoutError):
        return False
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass
    return True


async def probe_bridge_health(
    base_url: str,
    *,
    timeout_s: float | httpx.Timeout = BRIDGE_DISCOVER_TIMEOUT_S,
) -> dict[str, Any] | None:
    url = f"{base_url.rstrip('/')}/v1/health"
    timeout = timeout_s if isinstance(timeout_s, httpx.Timeout) else httpx.Timeout(timeout_s)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
    except httpx.HTTPError:
        return None
    if resp.status_code >= 400:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    if not is_bridge_health_payload(data):
        return None
    return data


async def discover_bridge_base_url(
    *,
    host: str = "127.0.0.1",
    preferred_port: int | None = None,
    timeout_s: float | httpx.Timeout | None = None,
) -> str:
    """
    One-shot discovery: walk 7100–7199 until StudioPoseBridge health matches, then stop.
    Caller must cache the result for the process lifetime.
    """
    timeout = timeout_s if timeout_s is not None else _discover_timeout()
    probed = 0
    for port in _port_scan_order(preferred_port):
        if not await _tcp_port_open(host, port):
            continue
        probed += 1
        base = f"http://{host}:{port}"
        data = await probe_bridge_health(base, timeout_s=timeout)
        if data is not None:
            logger.info(
                "Bridge locked at %s (after %s open-port probe(s); no further scan)",
                base,
                probed,
            )
            return base
    raise BridgeOfflineError(
        f"No StudioPoseBridge on {host}:{BRIDGE_PORT_MIN}-{BRIDGE_PORT_MAX}"
    )


class BridgeClient:
    """Talks to StudioPoseBridge; discovers once, then keeps that base URL."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:7100",
        *,
        token: str = "",
        timeout_s: float = 60.0,
        discover: bool = True,
        discover_timeout_s: float = BRIDGE_DISCOVER_TIMEOUT_S,
    ) -> None:
        self._hint_url = (base_url or "http://127.0.0.1:7100").rstrip("/")
        self._host, self._preferred_port = _parse_bridge_hint(self._hint_url)
        self.base_url = self._hint_url
        self.token = token
        self.timeout_s = timeout_s
        self.discover = discover
        self.discover_timeout_s = discover_timeout_s
        self._resolved = not discover
        self._resolve_lock = asyncio.Lock()

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.token:
            h["X-Pose-Token"] = self.token
        return h

    async def ensure_resolved(self) -> str:
        """Resolve bridge base URL once; subsequent calls reuse the locked URL."""
        if self._resolved:
            return self.base_url
        async with self._resolve_lock:
            if self._resolved:
                return self.base_url
            self.base_url = await discover_bridge_base_url(
                host=self._host,
                preferred_port=self._preferred_port,
                timeout_s=_discover_timeout(),
            )
            self._resolved = True
            return self.base_url

    @property
    def is_locked(self) -> bool:
        return self._resolved

    def invalidate(self) -> None:
        """Forget locked URL (explicit only — not used on normal health checks)."""
        self._resolved = not self.discover
        if self.discover:
            self.base_url = self._hint_url

    async def health(self) -> dict[str, Any] | None:
        """Probe the locked URL only (discover once if not yet locked)."""
        try:
            await self.ensure_resolved()
            return await probe_bridge_health(
                self.base_url,
                timeout_s=httpx.Timeout(connect=1.0, read=3.0, write=3.0, pool=3.0),
            )
        except BridgeOfflineError:
            return None

    async def list_characters(self) -> list[dict[str, Any]]:
        data = await self._json("GET", "/v1/characters")
        # Bridge wraps in {ok, data:{characters:[]}} or similar
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        chars = (payload or {}).get("characters") or data.get("characters") or []
        return chars if isinstance(chars, list) else []

    async def get_pose(
        self,
        character_id: int,
        *,
        regions: str | None = None,
        bones: str | None = None,
        space: str = "local",
    ) -> dict[str, Any]:
        params: list[str] = []
        if regions:
            params.append(f"regions={regions}")
        if bones:
            params.append(f"bones={bones}")
        if space:
            params.append(f"space={space}")
        q = ("?" + "&".join(params)) if params else ""
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
        await self.ensure_resolved()
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
        regions: str = "torso,hips,left_arm,right_arm,left_leg,right_leg",
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
            "pose_root": pose.get("root"),
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
        await self.ensure_resolved()
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
