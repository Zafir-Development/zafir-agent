"""A viewer that reconnects while the owner's server→client request waits gets that request again.

The canonical side of the sidecar's ``open_requests`` replay (``tui_gateway/server_requests.py``):
a reconnecting viewer re-renders the waiting card, and answering it there unblocks the turn
instead of leaving it parked until ``CARD_TIMEOUT_S``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.waiting import async_wait_until, wait_until


class _Transport:
    def __init__(self):
        self.frames = []

    def write(self, frame):
        self.frames.append(frame)
        return True

    def close(self):
        pass


async def _desktop(tmp_path, monkeypatch):
    from gateway.config import GatewayConfig
    from gateway.session import SessionStore
    from gateway.session_authority import initialize_session_authority
    from gateway.session_controls import AuthorityConnection
    from tui_gateway import server

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(server, "_hermes_home", str(home))
    monkeypatch.setattr(server, "_db", None)
    (home / ".env").write_text("OPENROUTER_API_KEY=sk-or-test\n", encoding="utf-8")
    (home / "config.yaml").write_text("model:\n  provider: openrouter\n  default: anthropic/claude-sonnet-4\n",
                                      encoding="utf-8")

    store = SessionStore(home / "sessions", GatewayConfig())
    runner = SimpleNamespace(_session_db=store._db, session_store=store, _draining=False, adapters={},
                             _handle_message=lambda event: None, _evict_cached_agent=lambda route: None,
                             _cached_agent_for=lambda route: None, _peek_session_state=lambda key: None)
    runner._adapter_for_source = lambda source: runner.adapters.get(source.platform)
    authority = await initialize_session_authority(runner, profile_id=str(home), instance_id="owner")
    transport = _Transport()
    identity = {"user_id": "uid:1", "provider": "local", "profile_id": str(home), "instance_id": "owner",
                "native_bootstrap": True}
    connection = AuthorityConnection(authority, transport, identity)
    from gateway.session_local_migration import bind_native_transport
    bind_native_transport(authority, connection.actor, identity)
    return SimpleNamespace(authority=authority, connection=connection, transport=transport, db=store._db)


async def _request(desktop, rid, method, params):
    from tui_gateway.ws import _dispatch_request
    reply = await _dispatch_request(desktop.connection, {"jsonrpc": "2.0", "id": rid, "method": method,
                                                         "params": params}, method, desktop.transport)
    if reply is None:
        def written():
            return next((f for f in desktop.transport.frames if isinstance(f, dict) and f.get("id") == rid), None)
        await async_wait_until(written, timeout=20)
        reply = written()
    return reply


async def _reload(desktop):
    """The renderer reloads: its socket closes and a new one connects and resumes."""
    from gateway.session_controls import AuthorityConnection
    from gateway.session_local_migration import bind_native_transport
    await desktop.connection.close()
    identity = {"user_id": "uid:1", "provider": "local", "profile_id": desktop.authority.profile_id,
                "instance_id": "owner", "native_bootstrap": True}
    desktop.transport = _Transport()
    desktop.connection = AuthorityConnection(desktop.authority, desktop.transport, identity)
    bind_native_transport(desktop.authority, desktop.connection.actor, identity)


@pytest.mark.asyncio
async def test_a_resumed_viewer_gets_the_waiting_card_and_its_answer_unblocks_the_turn(tmp_path, monkeypatch):
    from gateway.session_server_requests import ask_viewer_result, waiting
    desktop = await _desktop(tmp_path, monkeypatch)
    try:
        created = await _request(desktop, 1, "session.create",
                                 {"request_id": "card", "source": "tui", "cwd": str(tmp_path), "toolsets": []})
        assert "result" in created, created
        stored = created["result"]["session_id"]
        assert "result" in await _request(desktop, 2, "session.resume", {"session_id": stored})
        live = desktop.authority.sessions[stored]
        params = {"questions": [{"qid": "q0", "question": "Name?"}]}
        answer = asyncio.get_running_loop().run_in_executor(None, lambda: ask_viewer_result(
            live.event_stream, stored, "clarify", params, timeout=20))
        await async_wait_until(lambda: waiting(live.event_stream, stored, "clarify"), timeout=5)

        await _reload(desktop)
        resumed = await _request(desktop, 3, "session.resume", {"session_id": stored})

        assert "result" in resumed, resumed
        [entry] = resumed["result"]["open_requests"]
        assert entry["method"] == "clarify" and entry["params"] == {"session_id": stored, **params}
        reply = await desktop.connection.dispatch({"jsonrpc": "2.0", "id": entry["id"],
                                                   "result": {"answers": {"q0": "Sid"}}})
        assert reply is None
        assert await asyncio.wait_for(answer, 10) == {"answers": {"q0": "Sid"}}
        assert not waiting(live.event_stream, stored, "clarify")
    finally:
        await desktop.connection.close()


def test_an_open_request_is_replayed_only_on_its_own_sessions_stream():
    """Replay is per session: another session's reconnecting viewer never sees this request."""
    import threading
    from gateway.session_events import SessionEvents
    from gateway.session_server_requests import ask_viewer_result, open_requests, waiting, withdraw

    ours, other = SessionEvents(), SessionEvents()
    ours.fanout.attach(_Transport())
    ask = threading.Thread(target=lambda: ask_viewer_result(
        ours, "s1", "clarify", {"questions": [{"qid": "q0", "question": "?"}]}, timeout=10))
    ask.start()
    try:
        wait_until(lambda: waiting(ours, "s1", "clarify"), timeout=5)
        assert [entry["method"] for entry in open_requests(ours, "s1")] == ["clarify"]
        assert open_requests(other, "s1") == []
    finally:
        withdraw(ours, "s1", "clarify")
        ask.join(5)
