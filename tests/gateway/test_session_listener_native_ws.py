"""The gateway's session listener serves local sessions with no web application behind it.

The listener used to lazy-import the dashboard app (``hermes_cli.web_server``, hundreds of routes)
on the first request or warm it after READY. After Step 4 there is no dashboard to import: binding
``/api/ws`` must not pull FastAPI or any web-server module into the process, and every other
request is a 404 (HTTP) or a refused upgrade.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_PROBE = textwrap.dedent("""
    import asyncio, json, sys, types
    import httpx
    from websockets.asyncio.client import connect

    async def main():
        from gateway.run_api import start_gateway_api, stop_gateway_api
        from gateway.runtime_bootstrap import TicketStore
        import tui_gateway.ws

        async def fake_handle_ws(ws, **kwargs):
            await ws.accept(subprotocol="hermes-gateway-v1")
            await ws.send_json({"native": True})
            await ws.close()
        tui_gateway.ws.handle_ws = fake_handle_ws

        home = sys.argv[1]
        tickets = TicketStore("owner", [home])
        authority = types.SimpleNamespace(profile_id=home, instance_id="owner",
                                          db=types.SimpleNamespace(db_path=home + "/state.db"))
        runner = types.SimpleNamespace(_draining=False, session_runtime_descriptor={"state": "ready"},
                                       session_authority=authority, session_ticket_store=tickets)
        out = {}
        handle = await start_gateway_api(runner)
        try:
            out["after_bind"] = sorted(m for m in ("hermes_cli.web_server", "fastapi", "uvicorn")
                                       if m in sys.modules)
            url = handle.api_origin.replace("http:", "ws:") + "/api/ws"
            ticket = tickets.mint(profile_id=home, subject="human", purpose="interactive")
            protocols = ["hermes-gateway-v1", "hermes-gateway-ticket." + ticket]
            async with connect(url, subprotocols=protocols) as ws:
                out["native"] = json.loads(await ws.recv())
            # DNS-rebinding guard: a raw upgrade with a foreign Host is refused at the handshake.
            port = int(handle.api_origin.rsplit(":", 1)[1])
            ticket = tickets.mint(profile_id=home, subject="human", purpose="interactive")
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write((
                "GET /api/ws HTTP/1.1\\r\\nHost: attacker.invalid\\r\\nUpgrade: websocket\\r\\n"
                "Connection: Upgrade\\r\\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\\r\\n"
                "Sec-WebSocket-Version: 13\\r\\nSec-WebSocket-Protocol: hermes-gateway-v1, "
                "hermes-gateway-ticket." + ticket + "\\r\\n\\r\\n"
            ).encode())
            await writer.drain()
            out["rebind"] = int((await asyncio.wait_for(reader.readline(), 10)).split()[1])
            writer.close()
            async with httpx.AsyncClient(base_url=handle.api_origin, trust_env=False) as client:
                out["status"] = (await client.get("/api/status")).status_code
                out["root"] = (await client.get("/")).status_code
            out["after_http"] = sorted(m for m in ("hermes_cli.web_server", "fastapi")
                                       if m in sys.modules)
        finally:
            await stop_gateway_api(handle)
        print("RESULT " + json.dumps(out), file=sys.stderr, flush=True)

    asyncio.run(main())
""")


def test_session_listener_serves_native_ws_without_any_dashboard_module(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "TZ", "HERMES_RUNTIME_DIR", "TMPDIR"}}
    env.update(HOME=str(tmp_path), HERMES_HOME=str(home), PYTHONPATH=str(REPO))
    proc = subprocess.run([sys.executable, "-c", _PROBE, str(home)], cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=120, check=False)
    lines = [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.startswith("RESULT ")]
    assert proc.returncode == 0 and lines, proc.stderr[-3000:]
    out = json.loads(lines[-1][len("RESULT "):])
    assert out["after_bind"] == ["uvicorn"], f"listener start imported {out['after_bind']}"
    assert out["native"] == {"native": True}
    assert out["rebind"] == 403
    assert out["status"] == 404 and out["root"] == 404
    assert out["after_http"] == []
