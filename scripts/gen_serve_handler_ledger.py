#!/usr/bin/env -S bash -c 'exec "$BASH" "$(dirname "$0")/run-in-hermes-env" python3 "$0" "$@"'
"""Regenerate tests/hermes_cli/serve_handler_ledger.json from the code.

One row per handler ``hermes serve`` exposes: every HTTP/WebSocket route of the shared FastAPI app
(``hermes_cli.web_server.app``, imported the way ``serve`` imports it, ``HERMES_SERVE_HEADLESS=1``)
and every JSON-RPC method a ``/api/ws`` client can call (the legacy ``tui_gateway.server._methods``
table plus the verbs the session authority serves). ``gateway.ping``, the ``/api/ws`` heartbeat, is
answered by the transport before dispatch and has no row. Dashboard-plugin API routes depend on which
plugins are installed and enabled, so they are one row: the ``/api/plugins/{name}/{path}`` mount. Plugin
JSON-RPC methods are one row too: the declared ``plugin.{plugin_id}.{name}`` namespace.

Columns are derived from code, never judged:

* RPC ``current_path`` uses the tables ``/api/ws`` dispatch reads (``tui_gateway/ws.py``): served by
  the authority (``AuthorityConnection.handlers`` + group verbs + ``profiles.list``), else legacy
  fallback or refused per ``tui_gateway/ws_legacy_fallback.py::legacy_fallback_allowed``. A connector
  verb the authority serves only for a session-owned call (``gateway/session_connections.py``) falls
  back for an account-owned one. Without an authority (standalone ``serve``/``dashboard``) every
  legacy method runs in-process on ``server.dispatch``.
* HTTP ``current_path`` is the endpoint plus any ``route_on`` surface gate
  (``hermes_cli/web_server_surface.py``). Whether an endpoint reaches the authority is not derived.
* ``decision`` is ``authority`` for a verb the authority serves; everything else is ``undecided``
  until a reviewed entry lands in ``DECISIONS`` below. ``ref`` names the open #145171 decision a
  row waits on.

``--check`` writes nothing and exits 1 on drift (``tests/hermes_cli/test_serve_handler_ledger.py``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "hermes_cli" / "serve_handler_ledger.json"
DECISION_VALUES = ("authority", "keep-host-wide", "delete", "undecided")
# Step 4 removed the browser dashboard and the standalone ``hermes serve`` app. Every HTTP route
# and every non-native WebSocket route below existed only for that app: the dashboard SPA, its
# browser auth/tickets, file manager + uploads, PTY terminal, plugin dashboards, display viewer,
# webapp relay and the Desktop control plane. The native session WebSocket is answered by
# ``gateway/run_api.py`` before the app, not by an app route, so its app fallback goes too.
# The same goes for ``POST /api/profiles``: profile creation is an RPC (``profiles.create``) over
# ``/api/ws``, not an HTTP route. RPC rows keep their mechanical decision (they all stay).
_DELETE_ROWS = frozenset({
    'DELETE /api/credentials/pool/{provider}/{index}',
    'DELETE /api/cron/jobs/{job_id}',
    'DELETE /api/dashboard/agent-plugins/{name:path}',
    'DELETE /api/env',
    'DELETE /api/files',
    'DELETE /api/learning/node',
    'DELETE /api/local-models/models/{model_id}',
    'DELETE /api/mcp/oauth/flows/{flow_id}',
    'DELETE /api/mcp/servers/{name}',
    'DELETE /api/messaging/relay/{platform}/accounts/{platform_user_id}',
    'DELETE /api/messaging/telegram/onboarding/{pairing_id}',
    'DELETE /api/messaging/whatsapp/onboarding/{pairing_id}',
    'DELETE /api/ops/hooks',
    'DELETE /api/profiles/{name}',
    'DELETE /api/providers/custom-endpoints/{endpoint_id}',
    'DELETE /api/providers/oauth/sessions/{session_id}',
    'DELETE /api/providers/oauth/{provider_id}',
    'DELETE /api/sessions/empty',
    'DELETE /api/sessions/{session_id}',
    'DELETE /api/webhooks/{name}',
    'DELETE GET HEAD OPTIONS PATCH POST PUT /api/plugins/{name}/{path:path}',
    'GET /api/actions/{name}/status',
    'GET /api/analytics/models',
    'GET /api/analytics/usage',
    'GET /api/audio/elevenlabs/voices',
    'GET /api/audio/voice-config',
    'GET /api/audio/voice-live/status',
    'GET /api/auth/me',
    'GET /api/auth/providers',
    'GET /api/chat/workspaces',
    'GET /api/config',
    'GET /api/config/defaults',
    'GET /api/config/raw',
    'GET /api/config/schema',
    'GET /api/credentials/pool',
    'GET /api/cron/blueprints',
    'GET /api/cron/delivery-targets',
    'GET /api/cron/jobs',
    'GET /api/cron/jobs/{job_id}',
    'GET /api/cron/jobs/{job_id}/runs',
    'GET /api/curator',
    'GET /api/dashboard/font',
    'GET /api/dashboard/plugins',
    'GET /api/dashboard/plugins/auto-update',
    'GET /api/dashboard/plugins/catalog',
    'GET /api/dashboard/plugins/hub',
    'GET /api/dashboard/plugins/rescan',
    'GET /api/dashboard/themes',
    'GET /api/delegation/routing',
    'GET /api/egress/status',
    'GET /api/env',
    'GET /api/files',
    'GET /api/files/download',
    'GET /api/files/read',
    'GET /api/files/stream',
    'GET /api/fs/default-cwd',
    'GET /api/fs/download',
    'GET /api/fs/git-root',
    'GET /api/fs/list',
    'GET /api/fs/read-data-url',
    'GET /api/fs/read-text',
    'GET /api/gateway/migrate/plan',
    'GET /api/git/base-branches',
    'GET /api/git/branches',
    'GET /api/git/file-diff',
    'GET /api/git/gh-auth',
    'GET /api/git/review/commit-context',
    'GET /api/git/review/diff',
    'GET /api/git/review/list',
    'GET /api/git/review/rev-parse',
    'GET /api/git/review/ship-info',
    'GET /api/git/status',
    'GET /api/git/worktrees',
    'GET /api/health',
    'GET /api/health/idle',
    'GET /api/hermes/update/check',
    'GET /api/hermes/update/receipt',
    'GET /api/host/identity',
    'GET /api/learning/graph',
    'GET /api/learning/node',
    'GET /api/local-models/catalog',
    'GET /api/local-models/hardware',
    'GET /api/local-models/jobs',
    'GET /api/local-models/jobs/{job_id}',
    'GET /api/local-models/search',
    'GET /api/local-models/search/files',
    'GET /api/local-models/status',
    'GET /api/logs',
    'GET /api/mcp/catalog',
    'GET /api/mcp/oauth/callback/{server_name:path}',
    'GET /api/mcp/oauth/flows/{flow_id}',
    'GET /api/mcp/servers',
    'GET /api/media',
    'GET /api/media/proxy',
    'GET /api/memory',
    'GET /api/memory/providers/{name}/config',
    'GET /api/memory/providers/{provider}/oauth/status',
    'GET /api/messaging/platforms',
    'GET /api/messaging/relay',
    'GET /api/messaging/relay/link/{code}',
    'GET /api/messaging/telegram/onboarding/{pairing_id}',
    'GET /api/messaging/whatsapp/onboarding/{pairing_id}',
    'GET /api/model/auxiliary',
    'GET /api/model/info',
    'GET /api/model/moa',
    'GET /api/model/options',
    'GET /api/model/recommended-default',
    'GET /api/ops/backup/download',
    'GET /api/ops/checkpoints',
    'GET /api/ops/hooks',
    'GET /api/pairing',
    'GET /api/portal',
    'GET /api/profiles',
    'GET /api/profiles/active',
    'GET /api/profiles/projects/tree',
    'GET /api/profiles/sessions',
    'GET /api/profiles/sessions/sidebar',
    'GET /api/profiles/{name}/desktop-overlay',
    'GET /api/profiles/{name}/setup-command',
    'GET /api/profiles/{name}/soul',
    'GET /api/providers/custom-endpoints',
    'GET /api/providers/oauth',
    'GET /api/providers/oauth/nous/handoff',
    'GET /api/providers/oauth/{provider_id}/poll/{session_id}',
    'GET /api/sessions',
    'GET /api/sessions/empty/count',
    'GET /api/sessions/search',
    'GET /api/sessions/stats',
    'GET /api/sessions/{session_id}',
    'GET /api/sessions/{session_id}/export',
    'GET /api/sessions/{session_id}/latest-descendant',
    'GET /api/sessions/{session_id}/messages',
    'GET /api/sessions/{session_id}/messages/around',
    'GET /api/sessions/{session_id}/mutation-snapshot',
    'GET /api/sessions/{session_id}/timeline',
    'GET /api/shared-metrics/consent',
    'GET /api/skills',
    'GET /api/skills/content',
    'GET /api/skills/hub/official',
    'GET /api/skills/hub/preview',
    'GET /api/skills/hub/scan',
    'GET /api/skills/hub/search',
    'GET /api/skills/hub/sources',
    'GET /api/ssh/ownership',
    'GET /api/status',
    'GET /api/system/stats',
    'GET /api/tools/computer-use/status',
    'GET /api/tools/terminal/backends',
    'GET /api/tools/toolsets',
    'GET /api/tools/toolsets/{name}/config',
    'GET /api/tools/toolsets/{name}/models',
    'GET /api/webhooks',
    'GET /auth/callback',
    'GET /auth/login',
    'GET /auth/native/authorize',
    'GET /dashboard-plugins/@{profile}/{plugin_name}/{file_path:path}',
    'GET /dashboard-plugins/{plugin_name}/{file_path:path}',
    'GET /login',
    'GET /{full_path:path}',
    'GET HEAD /docs',
    'GET HEAD /docs/oauth2-redirect',
    'GET HEAD /openapi.json',
    'GET HEAD /redoc',
    'HEAD /api/files/stream',
    'HEAD /api/fs/download',
    'PATCH /api/profiles/{name}',
    'PATCH /api/sessions/{session_id}',
    'POST /api/audio/speak',
    'POST /api/audio/stt-lease',
    'POST /api/audio/transcribe',
    'POST /api/audio/tts-lease',
    'POST /api/audio/voice-live/session',
    'POST /api/auth/ws-ticket',
    'POST /api/chat/file-upload',
    'POST /api/chat/image-upload',
    'POST /api/credentials/pool',
    'POST /api/cron/blueprints/instantiate',
    'POST /api/cron/fire',
    'POST /api/cron/jobs',
    'POST /api/cron/jobs/{job_id}/cancel',
    'POST /api/cron/jobs/{job_id}/pause',
    'POST /api/cron/jobs/{job_id}/resume',
    'POST /api/cron/jobs/{job_id}/trigger',
    'POST /api/curator/run',
    'POST /api/dashboard/agent-plugins/activate',
    'POST /api/dashboard/agent-plugins/install',
    'POST /api/dashboard/agent-plugins/update-all',
    'POST /api/dashboard/agent-plugins/{name:path}/disable',
    'POST /api/dashboard/agent-plugins/{name:path}/enable',
    'POST /api/dashboard/agent-plugins/{name:path}/update',
    'POST /api/dashboard/plugins/{name:path}/visibility',
    'POST /api/env/reveal',
    'POST /api/files/mkdir',
    'POST /api/files/ticket',
    'POST /api/files/upload',
    'POST /api/files/upload-stream',
    'POST /api/fs/write-text',
    'POST /api/gateway/drain',
    'POST /api/gateway/migrate',
    'POST /api/gateway/restart',
    'POST /api/gateway/start',
    'POST /api/gateway/stop',
    'POST /api/git/branch/switch',
    'POST /api/git/review/commit',
    'POST /api/git/review/create-pr',
    'POST /api/git/review/pr-list',
    'POST /api/git/review/push',
    'POST /api/git/review/revert',
    'POST /api/git/review/stage',
    'POST /api/git/review/unstage',
    'POST /api/git/worktree/add',
    'POST /api/git/worktree/remove',
    'POST /api/health/retirement',
    'POST /api/hermes/update',
    'POST /api/local-models/activate',
    'POST /api/local-models/download',
    'POST /api/local-models/download-browsed',
    'POST /api/local-models/download/pause',
    'POST /api/local-models/download/resume',
    'POST /api/local-models/eject',
    'POST /api/local-models/quickstart',
    'POST /api/local-models/runtime/install',
    'POST /api/local-models/server',
    'POST /api/local-models/sideload',
    'POST /api/mcp/catalog/install',
    'POST /api/mcp/servers',
    'POST /api/mcp/servers/{name}/auth',
    'POST /api/mcp/servers/{name}/test',
    'POST /api/memory/providers/{name}/setup',
    'POST /api/memory/providers/{provider}/oauth/start',
    'POST /api/memory/reset',
    'POST /api/messaging/platforms/{platform_id}/test',
    'POST /api/messaging/relay/{platform}/link',
    'POST /api/messaging/telegram/onboarding/start',
    'POST /api/messaging/telegram/onboarding/{pairing_id}/apply',
    'POST /api/messaging/whatsapp/onboarding/start',
    'POST /api/messaging/whatsapp/onboarding/{pairing_id}/apply',
    'POST /api/model/set',
    'POST /api/ops/backup',
    'POST /api/ops/checkpoints/prune',
    'POST /api/ops/config-migrate',
    'POST /api/ops/debug-share',
    'POST /api/ops/doctor',
    'POST /api/ops/dump',
    'POST /api/ops/hooks',
    'POST /api/ops/import',
    'POST /api/ops/import-upload',
    'POST /api/ops/prompt-size',
    'POST /api/ops/security-audit',
    'POST /api/pairing/approve',
    'POST /api/pairing/clear-pending',
    'POST /api/pairing/revoke',
    'POST /api/profiles',
    'POST /api/profiles/active',
    'POST /api/profiles/import',
    'POST /api/profiles/sessions/pull-requests',
    'POST /api/profiles/{name}/describe-auto',
    'POST /api/profiles/{name}/export',
    'POST /api/profiles/{name}/open-terminal',
    'POST /api/providers/custom-endpoints',
    'POST /api/providers/custom-endpoints/validate',
    'POST /api/providers/custom-endpoints/{endpoint_id}/activate',
    'POST /api/providers/oauth/{provider_id}/start',
    'POST /api/providers/oauth/{provider_id}/submit',
    'POST /api/providers/validate',
    'POST /api/sessions/bulk-delete',
    'POST /api/sessions/import',
    'POST /api/sessions/owner-backfill',
    'POST /api/sessions/prune',
    'POST /api/skills',
    'POST /api/skills/hub/install',
    'POST /api/skills/hub/uninstall',
    'POST /api/skills/hub/update',
    'POST /api/tools/computer-use/permissions/grant',
    'POST /api/tools/toolsets/{name}/post-setup',
    'POST /api/webhooks',
    'POST /api/webhooks/enable',
    'POST /auth/logout',
    'POST /auth/native/refresh',
    'POST /auth/native/token',
    'POST /auth/password-login',
    'PUT /api/config',
    'PUT /api/config/raw',
    'PUT /api/cron/jobs/{job_id}',
    'PUT /api/curator/paused',
    'PUT /api/dashboard/font',
    'PUT /api/dashboard/plugin-providers',
    'PUT /api/dashboard/plugins/auto-update',
    'PUT /api/dashboard/theme',
    'PUT /api/delegation/backend',
    'PUT /api/delegation/backends/model_map',
    'PUT /api/delegation/backends/profile_routes',
    'PUT /api/env',
    'PUT /api/learning/node',
    'PUT /api/mcp/servers',
    'PUT /api/mcp/servers/{name}/enabled',
    'PUT /api/memory/provider',
    'PUT /api/memory/providers/{name}/config',
    'PUT /api/messaging/platforms/{platform_id}',
    'PUT /api/model/moa',
    'PUT /api/profiles/{name}/description',
    'PUT /api/profiles/{name}/model',
    'PUT /api/profiles/{name}/soul',
    'PUT /api/shared-metrics/consent',
    'PUT /api/skills/content',
    'PUT /api/skills/lock',
    'PUT /api/skills/toggle',
    'PUT /api/tools/terminal/backend',
    'PUT /api/tools/toolsets/{name}',
    'PUT /api/tools/toolsets/{name}/env',
    'PUT /api/tools/toolsets/{name}/model',
    'PUT /api/tools/toolsets/{name}/provider',
    'PUT /api/webhooks/{name}/enabled',
    'WS /api/audio/speak-stream',
    'WS /api/audio/transcribe-stream',
    'WS /api/console',
    'WS /api/display/ws',
    'WS /api/events',
    'WS /api/pty',
    'WS /api/pub',
    'WS /api/ws',
})
# Reviewed owner decisions, keyed by row ``handler``: ``(decision, ref)``. A row not listed here
# keeps its mechanical default.
DECISIONS: dict[str, tuple[str, str]] = {
    handler: ("delete", "") for handler in _DELETE_ROWS
}

_PLUGIN_MODULE_PREFIX = "hermes_dashboard_plugin_"


def _surface_gates(route) -> list[str]:
    """``route_on(field)`` dependencies: the route 404s on surfaces whose policy leaves *field* off."""
    from hermes_cli.web_server_surface import route_on

    gate_code = route_on("_").__code__
    gates = []
    for dep in getattr(getattr(route, "dependant", None), "dependencies", ()):
        call = getattr(dep, "call", None)
        if call is not None and getattr(call, "__code__", None) is gate_code:
            cells = dict(zip(call.__code__.co_freevars, (c.cell_contents for c in call.__closure__)))
            gates.append(str(cells["field"]))
    return sorted(gates)


def _collect() -> dict:
    """Raw facts from a fresh import (run in a child process: see :func:`_facts`)."""
    sys.path.insert(0, str(ROOT))
    from unittest.mock import MagicMock

    from fastapi.routing import APIRoute, APIWebSocketRoute
    from starlette.routing import Mount

    from gateway.runtime_bootstrap import _PURPOSE_CAPABILITIES
    from gateway.session_connections import METHODS as CONNECTION_METHODS
    from gateway.session_controls import AuthorityConnection
    from gateway.session_group_controls import GROUP_METHODS
    from hermes_cli.web_server import app
    from tui_gateway import server
    from tui_gateway.contracts.registry import CANONICAL_NAMESPACES
    from tui_gateway.ws_legacy_fallback import legacy_fallback_allowed

    interactive = SimpleNamespace(capabilities=_PURPOSE_CAPABILITIES["interactive"])

    routes = []
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None) or getattr(route, "app", None)
        module = getattr(endpoint, "__module__", "") or ""
        if module.startswith(_PLUGIN_MODULE_PREFIX):
            continue
        name = getattr(endpoint, "__qualname__", None) or type(endpoint).__qualname__
        if isinstance(route, APIWebSocketRoute):
            kind, methods = "websocket", ["WS"]
        elif isinstance(route, Mount):
            kind, methods = "mount", ["*"]
        else:
            kind, methods = "http", sorted(getattr(route, "methods", None) or ["*"])
        routes.append({"path": route.path, "kind": kind, "methods": methods, "source": f"{module}:{name}",
                       "gates": _surface_gates(route) if isinstance(route, (APIRoute, APIWebSocketRoute)) else []})
    return {
        "routes": routes,
        "legacy": sorted(server._methods),
        "served": sorted(set(AuthorityConnection.handlers(MagicMock())) | set(GROUP_METHODS) | {"profiles.list"}),
        # Dynamic method families (``plugin.<plugin_id>.<name>``): one row per declared pattern.
        "namespaces": sorted(CANONICAL_NAMESPACES),
        # The authority serves these only for a session-owned call; an account-owned one gets -32601.
        "account_owned_fallback": sorted(CONNECTION_METHODS),
        # Legacy methods ws.py keeps on the authority's -32601, by the predicate it calls.
        "refused": sorted(method for method in server._methods if not legacy_fallback_allowed(interactive, method)),
    }


def _facts() -> dict:
    """:func:`_collect` in a child interpreter with ``serve``'s import environment and a throwaway
    HERMES_HOME, so the route set never depends on the caller's process state or real profile."""
    with tempfile.TemporaryDirectory(prefix="serve-ledger-") as scratch:
        # The facts go to a file: importing tui_gateway.server takes over stdout for its JSON-RPC.
        home, out = Path(scratch) / "home", Path(scratch) / "facts.json"
        home.mkdir()
        env = {**os.environ, "HERMES_HOME": str(home), "HERMES_SERVE_HEADLESS": "1"}
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--collect", str(out)], cwd=ROOT,
                              env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
                              timeout=300)
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(f"handler collection failed:\n{proc.stderr[-4000:]}")
        return json.loads(out.read_text(encoding="utf-8-sig"))


def _rpc_row(method: str, facts: dict) -> dict:
    legacy, served = method in facts["legacy"], method in facts["served"]
    standalone = "; standalone: legacy server.dispatch" if legacy else "; standalone: unknown method"
    falls_back = legacy and method not in facts["refused"]
    if served and falls_back and method in facts["account_owned_fallback"]:
        return {"current_path": "authority (session-owned); account-owned: legacy fallback" + standalone,
                "decision": "undecided", "ref": "D3"}
    if served:
        return {"current_path": "authority" + standalone, "decision": "authority", "ref": ""}
    path = "legacy fallback" if falls_back else "authority refuses (-32601)"
    return {"current_path": path + standalone, "decision": "undecided", "ref": "D3"}


def _http_row(route: dict) -> dict:
    path = route["source"] + ("; surface: " + ", ".join(route["gates"]) if route["gates"] else "")
    return {"current_path": path, "decision": "undecided", "ref": ""}


def rows(facts: dict) -> list[dict]:
    out = [{"handler": f"{' '.join(route['methods'])} {route['path']}", "kind": route["kind"], **_http_row(route)}
           for route in facts["routes"]]
    out += [{"handler": method, "kind": "rpc", **_rpc_row(method, facts)}
            for method in sorted(set(facts["legacy"]) | set(facts["served"]))]
    out += [{"handler": name, "kind": "rpc", "current_path": "authority (after its own verbs); standalone: unknown method",
             "decision": "authority", "ref": ""} for name in facts.get("namespaces", ())]
    for row in out:
        if row["handler"] in DECISIONS:
            row["decision"], row["ref"] = DECISIONS[row["handler"]]
    return sorted(out, key=lambda row: (row["kind"] == "rpc", row["handler"]))


def render(facts: dict | None = None) -> str:
    table = rows(facts or _facts())
    counts: dict[str, dict[str, int]] = {}
    for row in table:
        bucket = counts.setdefault(row["kind"], {})
        bucket[row["decision"]] = bucket.get(row["decision"], 0) + 1
    head = json.dumps({"generated_by": "scripts/gen_serve_handler_ledger.py", "refs": "#145171 (EP-1)",
                       "decisions": list(DECISION_VALUES), "counts": counts}, indent=1, sort_keys=True)
    return (head[:-2] + ',\n "handlers": [\n' + ",\n".join("  " + json.dumps(row, sort_keys=True) for row in table)
            + "\n ]\n}\n")


def check(out: Path = OUT) -> int:
    committed = out.read_text(encoding="utf-8-sig") if out.exists() else ""
    if committed == render():
        return 0
    print(f"{out.relative_to(ROOT)} is stale; run scripts/gen_serve_handler_ledger.py", file=sys.stderr)
    return 1


def main(argv) -> int:
    if "--collect" in argv:
        Path(argv[argv.index("--collect") + 1]).write_text(json.dumps(_collect()), encoding="utf-8")
        return 0
    if "--check" in argv:
        return check()
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
