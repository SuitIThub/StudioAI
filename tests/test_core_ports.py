"""Core listen / discover ports 7200–7299."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from studio_ai_core.core_ports import (
    CORE_PORT_MAX,
    CORE_PORT_MIN,
    discover_core_base_url,
    is_core_health_payload,
    parse_core_hint,
    pick_listen_port,
    port_scan_order,
)


def test_port_scan_order_default():
    ports = port_scan_order(None)
    assert ports[0] == CORE_PORT_MIN
    assert ports[-1] == CORE_PORT_MAX
    assert len(ports) == 100


def test_port_scan_order_wraps():
    ports = port_scan_order(7205)
    assert ports[0] == 7205
    assert ports[-1] == 7204


def test_parse_core_hint_auto():
    assert parse_core_hint("auto") == ("127.0.0.1", None)
    host, port = parse_core_hint("http://127.0.0.1:7210")
    assert host == "127.0.0.1"
    assert port == 7210


def test_is_core_health_payload():
    assert is_core_health_payload({"status": "ok", "contract_version": "0.4.0"})
    assert not is_core_health_payload({"ok": True, "data": {"studio": "neov2"}})
    assert not is_core_health_payload({})


def test_discover_finds_port():
    def fake_probe(base_url: str, *, timeout_s: float = 0.35):
        if base_url.endswith(":7212"):
            return {"status": "ok", "contract_version": "0.4.0"}
        return None

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_connect(address, timeout=None):
        host, port = address
        if port != 7212:
            raise OSError("closed")
        return _Conn()

    with patch("studio_ai_core.core_ports.probe_core_health", side_effect=fake_probe), patch(
        "socket.create_connection", side_effect=fake_connect
    ):
        assert discover_core_base_url(host="127.0.0.1", preferred_port=7200) == (
            "http://127.0.0.1:7212"
        )


def test_discover_raises():
    def fake_connect(address, timeout=None):
        raise OSError("closed")

    with patch("studio_ai_core.core_ports.probe_core_health", return_value=None), patch(
        "socket.create_connection", side_effect=fake_connect
    ):
        with pytest.raises(RuntimeError):
            discover_core_base_url(host="127.0.0.1")


def test_pick_listen_port_skips_busy():
    def fake_bind(host: str, port: int) -> bool:
        return port >= 7202

    with patch("studio_ai_core.core_ports.can_bind", side_effect=fake_bind):
        assert pick_listen_port("127.0.0.1", 7200) == 7202
