"""Real TCP HTTP/WS coverage for the gateway-owned session listener.

The listener owns exactly one route — the native ticketed WebSocket at ``/api/ws`` — and never
takes signals or starts/stops runtime services. Everything else is a 404 (HTTP) or a closed
upgrade, which is the regression this file pins after the dashboard app was removed.
"""

import asyncio
import json
from pathlib import Path
import signal

import httpx
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

PROTOCOL = "hermes-gateway-v1"
TICKET_PREFIX = "hermes-gateway-ticket."


async def _raw_upgrade(origin: str, protocols, *, host_header: str) -> int:
    """Send a raw WebSocket handshake with a chosen Host header; return the HTTP status."""
    port = int(origin.rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        b"GET /api/ws HTTP/1.1\r\n"
        + f"Host: {host_header}\r\n".encode()
        + b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        + b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        + b"Sec-WebSocket-Version: 13\r\n"
        + f"Sec-WebSocket-Protocol: {', '.join(protocols)}\r\n\r\n".encode()
    )
    await writer.drain()
    status = int((await asyncio.wait_for(reader.readline(), 10)).split()[1])
    writer.close()
    return status


@pytest.mark.asyncio
async def test_owner_serves_only_the_native_session_ws(monkeypatch, tmp_path):
    from gateway.run import GatewayRunner
    from gateway.config import GatewayConfig
    from gateway.run_api import start_gateway_api, stop_gateway_api
    from gateway.runtime_bootstrap import TicketStore
    from gateway.session_authority import initialize_session_authority
    from hermes_state import SessionDB

    runner = GatewayRunner(GatewayConfig(sessions_dir=tmp_path / "gateway-sessions"))
    assert runner.adapters == {}
    # Boot publishes the runtime descriptor before the listener binds; the readiness gate reads it.
    runner.session_runtime_descriptor = {"state": "ready"}
    runner._draining = False
    # The ticket names the authority's profile HOME (its store's directory), as the control socket
    # does; the native dispatch checks the identity's profile against the bound authority.
    db = SessionDB(tmp_path / "state.db")
    home = str(tmp_path)
    await initialize_session_authority(
        runner, profile_id=home, instance_id="api-owner", db=db)
    tickets = TicketStore("api-owner", [home])
    runner.session_ticket_store = tickets
    before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

    handle = await start_gateway_api(runner)
    try:
        assert handle.api_origin.startswith("http://127.0.0.1:")
        assert before == {sig: signal.getsignal(sig) for sig in before}
        # No dashboard app: every HTTP path is a plain 404, token or not.
        async with httpx.AsyncClient(base_url=handle.api_origin, trust_env=False) as client:
            assert (await client.get("/api/status")).status_code == 404
            assert (await client.get("/")).status_code == 404
            assert (await client.post("/api/ws-ticket")).status_code == 404
            assert (await client.get("/api/config/raw",
                                     headers={"Authorization": "Bearer x"})).status_code == 404

        url = handle.api_origin.replace("http:", "ws:") + "/api/ws"
        # No credential at all: refused at the handshake (4403 → HTTP 403).
        with pytest.raises(InvalidStatus) as rejected:
            async with connect(url):
                pass
        assert rejected.value.response.status_code == 403
        # A browser Origin is refused even with an otherwise valid ticket.
        ticket = tickets.mint(profile_id=home, subject="human", purpose="interactive")
        with pytest.raises(InvalidStatus):
            async with connect(url, origin="http://attacker.invalid",
                               subprotocols=[PROTOCOL, TICKET_PREFIX + ticket]):
                pass
        # A foreign Host is refused before the ticket is redeemed (DNS-rebinding guard).
        ticket = tickets.mint(profile_id=home, subject="human", purpose="interactive")
        assert await _raw_upgrade(handle.api_origin, [PROTOCOL, TICKET_PREFIX + ticket],
                                  host_header="attacker.invalid") == 403
        # The native ticket path answers RPCs against the bound authority.
        ticket = tickets.mint(profile_id=home, subject="human", purpose="interactive")
        async with connect(url, subprotocols=[PROTOCOL, TICKET_PREFIX + ticket]) as ws:
            assert ws.subprotocol == PROTOCOL
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "session.list", "params": {}}))
            while True:
                reply = json.loads(await asyncio.wait_for(ws.recv(), 10))
                if reply.get("id") == 1:
                    break
            assert "result" in reply, reply
        with pytest.raises(RuntimeError, match="already"):
            await start_gateway_api(runner)
    finally:
        await stop_gateway_api(handle)
        if runner._session_db is not None:
            await runner._session_db.close()
    assert before == {sig: signal.getsignal(sig) for sig in before}
    with pytest.raises(httpx.ConnectError):
        async with httpx.AsyncClient() as client:
            await client.get(handle.api_origin + "/api/status")


@pytest.mark.asyncio
async def test_readiness_gate_refuses_sockets_before_ready(tmp_path):
    from gateway.run_api import start_gateway_api, stop_gateway_api
    from gateway.runtime_bootstrap import TicketStore

    class Runner:
        _draining = False
        session_runtime_descriptor = {"state": "starting"}
        session_authority = None

    runner = Runner()
    tickets = TicketStore("owner", [str(tmp_path)])
    runner.session_ticket_store = tickets
    handle = await start_gateway_api(runner)
    try:
        url = handle.api_origin.replace("http:", "ws:") + "/api/ws"
        ticket = tickets.mint(profile_id=str(tmp_path), subject="human", purpose="interactive")
        with pytest.raises(InvalidStatus):
            async with connect(url, subprotocols=[PROTOCOL, TICKET_PREFIX + ticket]):
                pass
    finally:
        await stop_gateway_api(handle)
