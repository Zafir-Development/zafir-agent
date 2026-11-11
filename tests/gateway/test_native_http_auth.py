"""Native listener auth: exactly one ticket subprotocol from a loopback peer, nothing else.

The listener used to fall back to the dashboard app for browser credentials (cookies,
``?token=`` session tokens, browser ``?ticket=`` tickets, ``X-Hermes-Gateway-Ticket`` header
grants). After the dashboard removal there is exactly one credential shape it accepts: the
canonical gateway protocol plus one one-time ticket subprotocol. Everything else is refused at
the handshake (4403 → HTTP 403) before any ticket is redeemed.
"""

import asyncio

import pytest
import pytest_asyncio

PROTOCOL = "hermes-gateway-v1"
TICKET_PREFIX = "hermes-gateway-ticket."


async def _handshake(origin: str, protocols: list[str]) -> int:
    port = int(origin.rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write((
        "GET /api/ws HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Protocol: {', '.join(protocols)}\r\n\r\n"
    ).encode())
    await writer.drain()
    status = int((await asyncio.wait_for(reader.readline(), 10)).split()[1])
    writer.close()
    return status


@pytest_asyncio.fixture
async def listener(tmp_path):
    import types

    from gateway.run_api import start_gateway_api, stop_gateway_api
    from gateway.runtime_bootstrap import TicketStore

    home = str(tmp_path)
    tickets = TicketStore("owner", [home])
    authority = types.SimpleNamespace(profile_id=home, instance_id="owner",
                                      db=types.SimpleNamespace(db_path=home + "/state.db"))
    runner = types.SimpleNamespace(
        session_runtime_descriptor={"state": "ready"}, _draining=False,
        session_ticket_store=tickets, session_authority=authority)
    handle = await start_gateway_api(runner)
    try:
        yield handle, tickets, home
    finally:
        await stop_gateway_api(handle)


@pytest.mark.asyncio
@pytest.mark.parametrize("protocols", [
    [TICKET_PREFIX + "not-a-real-ticket"],
    [PROTOCOL],
    [PROTOCOL, TICKET_PREFIX],
    [PROTOCOL, TICKET_PREFIX + "a", TICKET_PREFIX + "b"],
    ["some-other-protocol", TICKET_PREFIX + "a"],
])
async def test_only_the_canonical_ticket_subprotocol_is_accepted(listener, protocols):
    handle, _tickets, _home = listener
    assert await _handshake(handle.api_origin, protocols) == 403


@pytest.mark.asyncio
async def test_a_missing_subprotocol_is_refused_by_the_transport(listener):
    """No Sec-WebSocket-Protocol header at all: the upgrade is refused before any ticket is seen."""
    handle, _tickets, _home = listener
    port = int(handle.api_origin.rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        b"GET /api/ws HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
        b"Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        b"Sec-WebSocket-Version: 13\r\n\r\n"
    )
    await writer.drain()
    assert int((await asyncio.wait_for(reader.readline(), 10)).split()[1]) == 403
    writer.close()


@pytest.mark.asyncio
async def test_a_valid_native_ticket_reaches_the_session_dispatch(listener, monkeypatch):
    import json

    from websockets.asyncio.client import connect

    handle, tickets, home = listener
    seen = []

    async def handle_ws(ws, **kwargs):
        await ws.accept(subprotocol=PROTOCOL)
        seen.append(kwargs["auth_identity"])
        await ws.close()

    monkeypatch.setattr("tui_gateway.ws.handle_ws", handle_ws)
    ticket = tickets.mint(profile_id=home, subject="human", purpose="interactive")
    url = handle.api_origin.replace("http:", "ws:") + "/api/ws"
    async with connect(url, subprotocols=[PROTOCOL, TICKET_PREFIX + ticket]) as ws:
        assert ws.subprotocol == PROTOCOL
    assert seen and seen[0]["provider"] == "local"
    assert seen[0]["profile_id"] == home
    assert seen[0]["native_bootstrap"] is True
