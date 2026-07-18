"""StudioAI Core listen port (7200–7299) + client discovery helpers."""

from __future__ import annotations

import logging
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

CORE_PORT_MIN = 7200
CORE_PORT_MAX = 7299
CORE_DISCOVER_TIMEOUT_S = 0.35


def port_scan_order(preferred: int | None) -> list[int]:
    """Walk CORE_PORT_MIN..MAX; if preferred is in range, start there and wrap."""
    span = CORE_PORT_MAX - CORE_PORT_MIN + 1
    if preferred is not None and CORE_PORT_MIN <= preferred <= CORE_PORT_MAX:
        start = preferred
    else:
        start = CORE_PORT_MIN
    return [
        CORE_PORT_MIN + ((start - CORE_PORT_MIN + i) % span) for i in range(span)
    ]


def parse_core_hint(base_url: str) -> tuple[str, int | None]:
    raw = (base_url or "").strip().rstrip("/")
    if not raw or raw.lower() in ("auto", "discover"):
        return "127.0.0.1", None
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    return parsed.hostname or "127.0.0.1", parsed.port


def can_bind(host: str, port: int) -> bool:
    """True if we can bind TCP on host:port (ephemeral check)."""
    family = socket.AF_INET
    bind_host = host
    if host in ("0.0.0.0", "::", ""):
        bind_host = "0.0.0.0"
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((bind_host, port))
            return True
    except OSError:
        return False


def pick_listen_port(host: str, preferred: int) -> int:
    """First free port in 7200–7299 (preferred start, wrap)."""
    for port in port_scan_order(preferred):
        if can_bind(host, port):
            if port != preferred:
                logger.warning(
                    "Core port %s busy – binding %s instead (range %s–%s)",
                    preferred,
                    port,
                    CORE_PORT_MIN,
                    CORE_PORT_MAX,
                )
            return port
    raise RuntimeError(
        f"Could not bind any Core HTTP port in {CORE_PORT_MIN}..{CORE_PORT_MAX} "
        f"(preferred={preferred}, host={host})"
    )


def is_core_health_payload(data: Any) -> bool:
    """True when GET /health looks like StudioAI Core."""
    if not isinstance(data, dict):
        return False
    ver = data.get("contract_version")
    return isinstance(ver, str) and bool(ver)


def probe_core_health(
    base_url: str,
    *,
    timeout_s: float = CORE_DISCOVER_TIMEOUT_S,
) -> dict[str, Any] | None:
    for path in ("/health/live", "/health"):
        url = f"{base_url.rstrip('/')}{path}"
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.get(url)
        except httpx.HTTPError:
            continue
        if resp.status_code >= 400:
            continue
        try:
            data = resp.json()
        except ValueError:
            continue
        if is_core_health_payload(data):
            return data
    return None


def discover_core_base_url(
    *,
    host: str = "127.0.0.1",
    preferred_port: int | None = None,
    timeout_s: float = CORE_DISCOVER_TIMEOUT_S,
) -> str:
    """One-shot: walk 7200–7299 until Core /health matches, then stop (caller caches)."""
    import socket

    probed = 0
    for port in port_scan_order(preferred_port):
        try:
            with socket.create_connection((host, port), timeout=min(0.15, timeout_s)):
                pass
        except OSError:
            continue
        probed += 1
        base = f"http://{host}:{port}"
        data = probe_core_health(base, timeout_s=timeout_s)
        if data is not None:
            logger.info(
                "Core locked at %s (after %s open-port probe(s); no further scan)",
                base,
                probed,
            )
            return base
    raise RuntimeError(
        f"No StudioAI Core on {host}:{CORE_PORT_MIN}-{CORE_PORT_MAX}"
    )


def resolve_core_base_url(hint: str | None = None) -> str:
    """Resolve Core URL from hint / env-style URL (discovers port if needed)."""
    host, preferred = parse_core_hint(hint or "http://127.0.0.1:7200")
    # Fast path: preferred port already answers
    if preferred is not None:
        base = f"http://{host}:{preferred}"
        if probe_core_health(base, timeout_s=max(1.0, CORE_DISCOVER_TIMEOUT_S)) is not None:
            return base
    return discover_core_base_url(host=host, preferred_port=preferred)
