"""Bridge port discovery (7100–7199)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from studio_ai_core.bridge import (
    BridgeClient,
    BridgeOfflineError,
    _port_scan_order,
    discover_bridge_base_url,
    is_bridge_health_payload,
    probe_bridge_health,
)


def test_port_scan_order_default():
    ports = _port_scan_order(None)
    assert ports[0] == 7100
    assert ports[-1] == 7199
    assert len(ports) == 100


def test_port_scan_order_wraps_from_preferred():
    ports = _port_scan_order(7105)
    assert ports[0] == 7105
    assert ports[1] == 7106
    assert ports[-1] == 7104


def test_is_bridge_health_payload():
    assert is_bridge_health_payload(
        {"ok": True, "data": {"version": "0.1.0", "studio": "neov2", "scene_loaded": False}}
    )
    assert not is_bridge_health_payload({"ok": False, "error": "nope"})
    assert not is_bridge_health_payload({"status": "ok"})
    assert not is_bridge_health_payload(None)


def test_discover_finds_matching_port():
    async def fake_probe(base_url: str, *, timeout_s: float = 0.35):
        if base_url.endswith(":7112"):
            return {"ok": True, "data": {"version": "0.1.0", "studio": "neov2"}}
        return None

    async def fake_tcp(host: str, port: int, timeout_s: float = 0.15):
        return port == 7112

    async def _run():
        with patch("studio_ai_core.bridge.probe_bridge_health", side_effect=fake_probe), patch(
            "studio_ai_core.bridge._tcp_port_open", side_effect=fake_tcp
        ):
            return await discover_bridge_base_url(host="127.0.0.1", preferred_port=7100)

    assert asyncio.run(_run()) == "http://127.0.0.1:7112"


def test_discover_raises_when_none():
    async def _run():
        with patch("studio_ai_core.bridge.probe_bridge_health", new=AsyncMock(return_value=None)), patch(
            "studio_ai_core.bridge._tcp_port_open", new=AsyncMock(return_value=False)
        ):
            await discover_bridge_base_url(host="127.0.0.1")

    with pytest.raises(BridgeOfflineError):
        asyncio.run(_run())


def test_client_resolves_once_then_caches():
    calls: list[str] = []

    async def fake_discover(*, host: str, preferred_port, timeout_s: float):
        calls.append(host)
        return "http://127.0.0.1:7133"

    async def _run():
        client = BridgeClient("http://127.0.0.1:7100", discover=True)
        with patch("studio_ai_core.bridge.discover_bridge_base_url", side_effect=fake_discover):
            assert await client.ensure_resolved() == "http://127.0.0.1:7133"
            assert await client.ensure_resolved() == "http://127.0.0.1:7133"
        return client.base_url

    assert asyncio.run(_run()) == "http://127.0.0.1:7133"
    assert calls == ["127.0.0.1"]


def test_client_fixed_url_skips_discover():
    async def _run():
        client = BridgeClient("http://127.0.0.1:7842", discover=False)
        return await client.ensure_resolved()

    assert asyncio.run(_run()) == "http://127.0.0.1:7842"


def test_probe_rejects_non_bridge_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hello": "world"})

    transport = httpx.MockTransport(handler)

    class PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    async def _run():
        with patch("httpx.AsyncClient", PatchedClient):
            return await probe_bridge_health("http://127.0.0.1:7100")

    assert asyncio.run(_run()) is None


def test_probe_accepts_bridge_health():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {"version": "0.1.0", "studio": "neov2", "scene_loaded": True},
            },
        )

    transport = httpx.MockTransport(handler)

    class PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    async def _run():
        with patch("httpx.AsyncClient", PatchedClient):
            return await probe_bridge_health("http://127.0.0.1:7100")

    data = asyncio.run(_run())
    assert data is not None
    assert data["data"]["studio"] == "neov2"
