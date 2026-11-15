"""The gateway HTTP listener has no page to serve and no token to leak.

Local clients authenticate with single-use tickets minted on the owner-only control socket
(SO_PEERCRED). The old dashboard app served ``GET /`` (which injected
``window.__HERMES_SESSION_TOKEN__``), every ``/api/*`` route and the SPA fallback on the same
loopback origin, so any other OS user on the host could read the bearer token and use every route.
After the dashboard removal the listener answers HTTP with a plain 404 and accepts no query
credential: there is no session token, no SPA and no REST surface left to expose.
"""

import types

import httpx
import pytest


@pytest.mark.asyncio
async def test_gateway_listener_has_no_http_surface_and_no_token(tmp_path, monkeypatch):
    from gateway.run_api import start_gateway_api, stop_gateway_api

    runner = types.SimpleNamespace(session_runtime_descriptor={"state": "ready"}, _draining=False,
                                   session_authority=None)
    handle = await start_gateway_api(runner)
    try:
        async with httpx.AsyncClient(base_url=handle.api_origin, trust_env=False) as client:
            for path in ("/", "/index.html", "/api/status", "/api/config/raw", "/api/ws-ticket"):
                response = await client.get(path)
                assert response.status_code == 404, (path, response.text)
                assert "__HERMES_SESSION_TOKEN__" not in response.text
            response = await client.get("/", headers={"Authorization": "Bearer anything"})
            assert response.status_code == 404
    finally:
        await stop_gateway_api(handle)
