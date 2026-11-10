# Step 4 seam audit — dashboard/`serve` vs. the gateway session listener

Branch `removal-step-4-dashboard`, base `08229474ac` (PR #5, stages 0–3 merged into
`trim-core-surfaces`). This document is the audit deliverable of Step 4 before any deletion: which
routes of the dashboard/`serve` FastAPI app stay, which go, and the evidence for each.

Method: `tests/hermes_cli/serve_handler_ledger.json` is the machine copy of the route/RPC inventory.
It is generated from the code by `scripts/gen_serve_handler_ledger.py` (it imports
`hermes_cli.web_server.app` the way `serve` imports it, and the `/api/ws` dispatch tables for RPC
rows) and pinned by `tests/hermes_cli/test_serve_handler_ledger.py`. Reviewed decisions live in the
generator's `DECISIONS` table; nothing below is judged by hand-written counts.

Reproduce:

```bash
./scripts/gen_serve_handler_ledger.py            # regenerate (writes the ledger)
python - <<'PY'                                   # counts
import json, collections
d = json.load(open("tests/hermes_cli/serve_handler_ledger.json"))
print(collections.Counter((h["kind"], h["decision"]) for h in d["handlers"]))
PY
```

## 1. Counts: before and after

| Reading | HTTP | WebSocket | RPC (over `/api/ws`) | Total |
|---|---:|---:|---:|---:|
| Committed ledger before this step (stale after Stage 3) | 344 | 10 | 291 | 645 |
| Regenerated at Step 4 start (`python scripts/gen_serve_handler_ledger.py`) | 313 | 8 | 291 | 612 |
| Step 4 decisions applied (this audit's ledger) | **0** | **1 native** (`/api/ws` answered by `gateway/run_api.py`, not an app route) | **290** | — |

The committed ledger was 2 formulas behind the tree (34 rows for modules Stage 3 deleted); the
regenerated "before" number is the honest baseline: **321 HTTP/WS routes**, of which **321 are
dashboard/`serve`-only** and **zero** have a non-dashboard consumer (evidence per group below). The
statement "about 690 routes" in the old `gateway/run_api.py` / `web_server_boundary.py` docstrings
was a stale 2x estimate; it is removed with the app.

RPC count moves 291 → 290 because `display.observe` mints a ticket only the deleted
`/api/display/ws` viewer could redeem (Bot Screen; Step 7 owns the rest of Bot Desktop). Every other
RPC method stays on `/api/ws` untouched.

## 2. The one kept route: `/api/ws`

| Item | Evidence |
|---|---|
| Served by | `gateway/run_api.py::GatewayRuntimeAPI._serve` — it intercepts `scope["path"] == "/api/ws"` before any app is reached (the app previously saw only browser/`?token=` upgrades). |
| Credential | one-time ticket in the `hermes-gateway-ticket.<ticket>` WebSocket subprotocol + `hermes-gateway-v1`; minted on the owner-only control socket (`hermes_cli/gateway_client.py::_session_ticket` → `gateway/runtime_bootstrap.py::TicketStore`). Not an HTTP route. |
| Only clients | CLI/TUI: `hermes_cli/gateway_client.py::gateway_ws_target` / `connect_gateway` (used by `hermes chat`, `hermes --tui`, `hermes gateway attach --json`, `hermes sessions adopt`). `grep -rn "api/ws" ui-tui/src` → `ui-tui/src/gatewayClient.ts:9,14,17-20`. No other HTTP/WS call from CLI or TUI. |
| Kept boundary | loopback peer gate, Host/DNS-rebinding check, ticket redeem + profile/authority binding, readiness/drain gating and the restart-wait admission (below). |
| Deleted app fallback | `hermes_cli/web_routers/chat_ws.py::gateway_ws` (browser cookies/tickets/`?token=`), `web_server_chat._ws_auth_reason`, `dashboard_auth.*`. Browser upgrades on `/api/ws` now close `4403`: no browser credential survives the dashboard. |

## 3. Route groups deleted (all 313 HTTP + 8 WebSocket rows)

`current_path` in the ledger names the definition; "only consumer" is what the code audit found
outside the dashboard SPA itself (grep of the CLI `hermes_cli/`, `tui_gateway/`, `ui-tui/`,
`gateway/` trees; the dashboard SPA and the Electron renderer were the consumers of everything
below and are gone with Stages 3–4).

| Ledger module (rows) | What it is | Only consumer found | Decision |
|---|---|---|---|
| `web_routers.ops` (28) | credential pool / setup ops REST | dashboard SPA, Desktop | delete |
| `web_routers.dashboard_ui` (21) | dashboard UI prefs, plugin UI, host terminal | dashboard SPA | delete |
| `web_routers.files` (21) + `uploads` (1) | file manager, uploads, file tickets | dashboard SPA, Desktop file attach | delete |
| `web_routers.git` (21) | git review panes | dashboard SPA | delete |
| `web_routers.status` (20) | `/api/health*`, `/api/status`, `/api/host/identity` | dashboard SPA + Desktop readiness poller; CLI/TUI readiness is control-socket `identify` (`hermes_cli/gateway_runtime_discovery.py`) | delete |
| `web_routers.profiles` (20) | profile REST incl. `POST /api/profiles`, `/api/profiles/sessions*` | dashboard SPA; TUI creates profiles through the `profiles.create` RPC over `/api/ws` | delete |
| `web_routers.local_models` (18) | local-model manager REST | dashboard SPA; the CLI setup flow used the module as a library (handler core extracted: see §5) | delete routes |
| `web_routers.sessions` (18) | session browser / transcript / mutation REST | dashboard SPA, Desktop session picker | delete |
| `web_routers.config_env` (15) | raw config / `.env` REST | dashboard SPA | delete |
| `web_routers.cron` (14) | cron REST | dashboard SPA | delete |
| `web_routers.skills` (14) | skills editor REST | dashboard SPA | delete |
| `web_routers.mcp` (12) | MCP manager REST | dashboard SPA | delete |
| `web_routers.tools` (12) | toolset config REST | dashboard SPA | delete |
| `web_routers.messaging` (11) + `messaging_relay` (4) | messaging/channel cards, relay | dashboard SPA | delete |
| `dashboard_auth.routes` (11) | browser login/logout/OAuth/session routes | browsers only | delete |
| `web_routers.audio` (10) | `/api/audio/*` TTS/STT WS + REST | dashboard SPA / Desktop voice | delete |
| `web_routers.chat_ws` (5) | `/api/console`, `/api/events`, `/api/pty`, `/api/pub`, `/api/ws` app fallback | browser/PTY only | delete |
| `web_routers.actions` (8) | desktop/dashboard action REST | dashboard SPA | delete |
| `web_routers.oauth` (7) | provider OAuth REST + poller | dashboard SPA | delete |
| `web_routers.models` (7) | model catalogue REST | dashboard SPA | delete |
| `web_routers.analytics` (4) | usage analytics | dashboard SPA | delete |
| `web_routers.delegation` (4) | delegation UI REST | dashboard SPA | delete |
| `web_routers.memory_providers` (3) | memory OAuth connect routes (`memory_oauth.py`) | dashboard SPA | delete |
| `web_routers.shared_metrics` (2) | dashboard telemetry | dashboard SPA | delete |
| `web_routers.display` (1) | `/api/display/ws` RFB viewer | Bot Screen only; `display.observe` RPC removed with it | delete |
| `web_routers.chat_workspaces` (1) | chat workspace REST | dashboard SPA | delete |
| `web_server_dashboard` (2) | plugin dashboard HTTP mounts | dashboard SPA | delete |
| `fastapi.applications` (4) | SPA static assets + fallback 404 | browser | delete |
| `dashboard_auth.routes` WS + `web_routers.audio` WS/misc (8 WS rows) | browser/PTY/audio/display sockets | browsers, PTY child, RFB viewer | delete |

Special rows the plan called out:

| Handler | Definition | Consumer outside the dashboard | Decision / evidence |
|---|---|---|---|
| `GET /api/health`, `/api/health/idle`, `/api/health/retirement` | `web_routers/status.py:119,162,172` | none — CLI/TUI readiness uses the control socket `identify` (`gateway_runtime_discovery.py`); `restart_wait_read`'s HTTP allowlist is deleted with these routes (`gateway/drain_control.py` keeps only the WS policies) | delete |
| `GET /api/status` | `web_routers/status.py:544` | Desktop/dashboard poller; `hermes gateway status` is control-socket based | delete |
| `GET /api/profiles/sessions`, `/api/profiles/sessions/sidebar` | `web_routers/profiles.py` | Desktop/dashboard profile switcher and restart-wait reads; TUI lists sessions with the `session.list` RPC | delete |
| `GET /api/host/identity` | `web_routers/status.py:133`; path constant `gateway/host_rendezvous.py:60` | the probe is the `hermes serve`/Desktop attach ladder (`gateway/host_rendezvous.py:407`); no CLI/TUI caller | delete route; see §6 for the retained host record |
| `POST /api/profiles` | `web_routers/profiles.py::create_profile_endpoint` | none (dashboard profiles page). Keep-host-wide decision removed from the ledger: profile creation is host-level work, and it stays available as the `profiles.create` RPC over `/api/ws` (`tui_gateway/methods_profiles.py:306`) | delete HTTP route |
| `profiles.create` (RPC) | `tui_gateway/methods_profiles.py:306` | TUI/plugin clients over `/api/ws` (contract: `tui_gateway/contracts/profiles_vault_complete_foreign_subagents.py:224`) | keep; ledger row returns to its mechanical `undecided`/D3 state (legacy fallback on the gateway dispatch table), the RPC surface is unchanged |
| `WS /api/display/ws` + `display.observe` | `web_routers/display.py`, `tui_gateway/methods_display.py` | Bot Screen viewer only | delete (rest of Bot Desktop is Step 7) |

## 4. Kept session-listener seam (not dashboard code)

| Piece | Location | Why it stays |
|---|---|---|
| Listener construct + bind | `gateway/run_api.py::start_gateway_api`, `hermes_cli/web_server_lifecycle.py::build_listener_server` (uvicorn only, FastAPI-free) | the only local listener after this step; loopback-only |
| Boundary checks | `hermes_cli/web_server_boundary.py` (`_gateway_ws_ticket_from_subprotocol`, `ws_client_reason`, `ws_host_origin_reason`) | Host/DNS-rebinding + loopback peer gates for the native socket |
| Ticket redeem | `gateway/run_api.py::_serve` → `runner.session_ticket_store.redeem` | native grants; minted on the owner-only control socket |
| Readiness/drain gate | descriptor state + `gateway/drain_control.py` (`restart_wait_open`, `ws_method_refused_while_draining`, `RESTART_WAIT_WS_METHODS`) | 503/1013 while not ready; restart-wait admission for a human answering a parked prompt |
| Session authority bind | `gateway/session_authorities.py::authority_for_profile_id` + `owner_scope` | the ticket names the served profile |

`warm_gateway_dashboard` and `GatewayDashboardMount` are deleted; `gateway/run_bootstrap.py` no
longer warms a dashboard after READY. `start_gateway_api` refuses a non-loopback bind: native
tickets are loopback grants and no browser auth exists to authenticate a remote peer.

## 5. Helpers extracted from the deleted modules (kept surfaces must not import them)

| Symbol | Was | New neutral home | Kept consumer |
|---|---|---|---|
| `config_write_scope` + profile/secret/config scopes, `CONFIG_MUTATION_LOCK` | `web_routers/_common.py`, `web_server_profiles.py`, `web_server.py` | `hermes_cli/profile_scope.py` | `tools/connectors/mcp.py` |
| `_write_profile_model` + model-assignment helpers | `web_routers/profiles.py`, `web_server_config.py` | `hermes_cli/profile_model_write.py` | `tui_gateway/methods_profiles.py` (profile create RPC) |
| `_open_session_db_at_path` (+ read-probe statements) | `web_server_sessions.py` | `hermes_cli/session_db_browse.py` | `tui_gateway/server.py` |
| `_fs_regular_file`, `_is_sensitive_path`, `_FS_DATA_URL_MAX_BYTES` | `web_routers/files.py`, `web_server.py` | `hermes_cli/host_files.py` | `tui_gateway/session_history.py` |
| `_resolve_profile_dir` | `web_server_profiles.py` | direct `hermes_cli.profiles` validation | `gateway/session_readiness.py` |
| local-model handler core (`local_models_*`, `QuickstartBody`, `_human_gb`) | `web_routers/local_models.py` | `hermes_cli/local_models_service.py` | `hermes_cli/model_setup_flows_local.py` (`hermes model` local setup) |
| bytecode fingerprint/sweep + dropped-dir prune | `main_web_build.py` | `hermes_cli/update_bytecode.py` | `hermes_cli/main.py`, `hermes_cli/update_cmd_maint.py` |
| `_systemd_restart_commands`, `_format_restart_commands`, launchd/process helpers | `main_dashboard.py` | retained slim `main_dashboard.py` (legacy service support, see §6) | `hermes_cli/update_serve_obligations.py`, `update_abort_recovery.py`, `update_inventory.py`, `gateway_supervised_restart.py`, `dashboard_procs.py` |

## 6. Deliberate retentions (reported, not silently kept)

1. **`hermes_cli/dashboard_procs.py` and a subset of `hermes_cli/main_dashboard.py`.** These files no
   longer implement a user-facing dashboard or `serve` command; they are the updater's legacy
   service/process cleanup (stop/restart a backend a previous release left running) and are pinned
   by the frozen old-updater surface (`tests/compat/old_updater_surface.json`:
   `hermes_cli.dashboard_procs::_scan_dashboard_processes`,
   `hermes_cli.dashboard_procs::_kill_stale_dashboard_processes`, `hermes_cli::main_dashboard`).
   Deleting them would brick a `hermes update` running from an older release (the frozen-surface
   policy is explicit: restore the name, a stub is fine; the full compat revision is Step 5). The
   `hermes dashboard` / `hermes serve` command implementations were deleted from `main.py` and
   `subcommands/dashboard.py`; the retained module only formats/executes restart commands and
   detects legacy backend processes.
2. **Thin `hermes_cli/dashboard_auth/` core** (`__init__.py`, `base.py`, `registry.py`,
   `listener_client.py`): `hermes_cli/plugins.py`, `plugins_context.py`, `gateway/owner_identity.py`
   and the bundled `plugins/dashboard_auth/*` providers import the provider protocol and the
   process-global registry at plugin discovery. Login pages, cookie/session middleware, OAuth
   routes, WS browser tickets and public-URL helpers are deleted. The fate of the bundled
   `plugins/dashboard_auth/*` providers themselves is a decision outside Step 4 — flagged for the
   report (they can no longer serve a page after this step).
3. **`gateway/host_rendezvous.py` serve-attach ladder.** The host record/lock also backs the single
   gateway role (`gateway/host_topology.py`), which stays; only the `/api/host/identity` HTTP route
   it probed is deleted. The serve/desktop-serve attach roles are now unreachable and belong to the
   later Step 5/7 cleanup.

## 7. Stop-condition proof (does the removal break CLI/TUI/gateway auth?)

- CLI/TUI attach: only `/api/ws` with a control-socket-minted ticket (single client path,
  `hermes_cli/gateway_client.py:39-45,318-382`); that path is kept and covered by
  `tests/gateway/test_runtime_api.py` + `tests/gateway/test_session_listener_*.py`.
- Ticket minting and the owner-only control socket are gateway code (`gateway/runtime_bootstrap.py`,
  `gateway/run_bootstrap.py:370`), untouched.
- Gateway messaging auth (`authz_mixin`, platform allowlists) and native identity
  (`gateway/session_identity.py`) are untouched except for inlining the two internal-ticket constants
  (`server-internal`), which only the removed browser ticket issuer used.
- Plugin load: the provider registry and protocol types stay (above); no bundled plugin import
  breaks. Verified by import smoke and `tests/plugins/dashboard_auth/*` while the tree is intact.
- Remaining reference sweep: `grep -rn "web_routers\|hermes_cli.web_server"` is limited to
  `docs/removal/`, `history/` and the residual files named in §6 (plus the frozen
  `_UPDATE_CRITICAL_FILES` historical list, which names `hermes_cli/web_server.py` for pre-declaration
  trees only). Website/skills/tests references belong to Steps 9–10.
