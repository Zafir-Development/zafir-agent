# 02 — Sequential removal plan

Every step is one PR-sized change that leaves the tree green. Steps are ordered so that no step
depends on code deleted by a later one. Do not batch steps: each has its own verification gate.

**Global rules**

- No compatibility shims and no migration paths (D9). Delete `tests/compat/old_updater_surface.json`
  and the `old_updater_main.py`/`old_updater_deps.py` shims when the desktop names go.
- Delete a generated artifact together with its generator and its pinning test.
- Run `python scripts/check` on every step; run the targeted tests named in the step.
- Record the metric snapshot from [03-optimization.md](03-optimization.md#measurement) before
  Step 1 and after Step 12.
- Keep this directory (`docs/removal/`) in the branch; it is not published.
- **Every step ends with a `history/` entry** (see [history/README.md](../../history/README.md)):
  a new append-only snapshot `history/YYYY-MM-DD-<slug>/` (copy the previous snapshot, update
  `diagram.json`/`diagram.html` only where the runtime architecture actually changed, fill
  `NOTES.md` with the branch revision, verified facts with paths/lines, spec/artifact sha256 and
  known simplifications) plus a new top row in `history/CHANGELOG.md`. Commit it separately as
  `docs(history): snapshot <slug>` in the same branch. A step with no runtime-architecture change
  (e.g. Step 1) still gets a snapshot whose `NOTES.md` states why the diagram is unchanged.
- Archify is required for history artifacts: `~/.agents/skills/archify/bin/archify.mjs`
  (validate/deliver/visual-check with `--quality showcase`) - the acceptance bar is in
  `history/README.md` (9/9 checks, 0 errors, 0 warnings; `visual-check` pass on 1440x900,
  1600x1000, 1920x1080, 2048x1320).

Suggested PR sequence (13 steps, ~25–40 developer-days):

| Step | PR title | Depends on | Risk |
|---|---|---|---|
| 0 | Baseline + guardrails | — | none |
| 1 | Remove GUI installer and installer desktop stages | 0 | low |
| 2 | Remove desktop packaging, release channels, and desktop CI | 1 | medium |
| 3 | Remove `apps/desktop` and the Webapp | 2 | medium |
| 4 | Remove dashboard/`serve` surface, keep gateway session listener | 3 | **high** |
| 5 | Remove desktop CLI, config, update/uninstall branches | 3 | **high** |
| 6 | Remove desktop tools/toolsets and session-surface branches | 5 | medium |
| 7 | Remove Bot Mode (relay, Bot Desktop, viewer) | 6 | medium |
| 8 | Remove desktop plugin SDK/halves and catalog shelf | 7 | medium |
| 9 | Remove docs/website/i18n/skills for removed surfaces | 8 | low |
| 10 | Remove tests and update CI gates | 9 | medium |
| 11 | Prune dependencies, build graph, and startup lists | 10 | medium |
| 12 | Final verification, metrics, repo docs | 11 | low |

---

## Step 0 — Baseline and guardrails

**Goal:** record the starting point and keep the branch honest.

- Confirm `python scripts/check` and the core test lane are green before touching anything.
- Snapshot the metrics (commands in `03-optimization.md`).
- Add this plan (already in `docs/removal/`).
- Decide D7 (`computer_use` fate) and whether non-Telegram gateway adapters stay (D8). D7 changes
  Step 7; do not merge Step 7 before it is decided.

**Done:** baseline numbers committed in the PR description.

---

## Step 1 — GUI installer and installer desktop stages

**Goal:** remove `Hermes-Setup` and every installer behaviour that exists only to build/launch the
Electron app. Source installs keep working.

Delete:

- `apps/bootstrap-installer/**`
- `.github/workflows/bootstrap-installer-build.yml`, `rust-tests.yml`
- desktop-only tests: `tests/scripts/test_install_ps1_desktop_stage.py`,
  `tests/scripts/test_install_desktop_product_present.py`, `tests-js/bootstrap-installer-*`,
  `tests-js/install-known-failures*`
- `.github/workflows/rust-tests.yml` job references in `ci.yaml`; `justfile` and `lefthook.yml`
  desktop/bootstrap-installer lint jobs.

Edit:

- `scripts/install.sh`: remove `--include-desktop`, the `desktop` pseudo-stage and dispatch, the
  `desktop_product_present` probe, `products_record` desktop row, desktop arg in `stage_products`,
  `--include-desktop` help and constant. Keep `stage_names` (9 stages).
- `scripts/install.ps1`: remove `-IncludeDesktop`, `-ProtocolVersion`, `ProductTitle` desktop arm,
  `Test-DesktopProductPresent`, `Stage-Desktop` + dispatch, `Confirm-DesktopArtifact`,
  `New-DesktopShortcuts`; replace the `scripts/desktop-update/runtime.ps1` call in
  `Invoke-InstalledHermes` with a direct `.hermes/bin/hermes.exe setup/gateway` invocation.
- `scripts/install.cmd`: unchanged (source install).
- `.github/workflows/bootstrap-installer.yml`: drops the stage-protocol/GUI lanes; keep or rename it
  as source-installer protocol CI if the stage protocol is retained, otherwise remove it.
- `scripts/ci/classify_changes.py`, `scripts/ci/required_results.py`,
  `.github/actions/detect-changes/action.yml`, `.github/workflows/README.md` for removed paths.

Verify: `bash scripts/install.sh --manifest` lists the 9 source stages and no `desktop`;
`tests/scripts/install/`; `python scripts/check`.

**History:** add `history/<YYYY-MM-DD>-removal-step-1-installer/` (slug example:
`2026-11-08-removal-step-1-installer`): copy the current snapshot, keep the diagram unchanged
(the installer is not part of the runtime diagram) and state that in `NOTES.md`; add the
`history/CHANGELOG.md` row; commit as `docs(history): snapshot <slug>` after the code commit.

**Done:** a fresh source install on Linux/macOS/Windows (smoke) needs no desktop code path; the
history snapshot is committed in the same branch and `history/CHANGELOG.md` has the new row.

---

## Step 2 — Desktop packaging, release channels, desktop CI

**Goal:** stop producing and publishing desktop artifacts. Keep source release/tag machinery.

Delete:

- `scripts/build-bundle.sh`, `scripts/build-bundle.ps1`
- `scripts/bundles/desktop.py`, `desktop_inputs.py`, `desktop_prepare.py`,
  `dmgbuild_diagnostics.py`, `msix_names.py`, `set_dmg_volume_icon.sh`
- `scripts/build/desktop.mjs`, `desktop-reuse.mjs`, `electron-runtime.mjs`, `webapp.mjs`
- `scripts/msix-shared.mjs`, `stage-msixbundle.mjs`, `bundle-store-msixbundle.mjs`
- `scripts/desktop-update/**`, `scripts/desktop-update.ps1`
- `scripts/release.py` desktop dispatch/signature, desktop lanes in `scripts/releases/`,
  `scripts/bundles/release_artifacts.py`/`channel_artifacts.py` desktop targets,
  `scripts/releases/stamping.py` Tauri/Cargo stamping, `scripts/render-builds-table.py`
- `.github/workflows/desktop-bundled-release.yml`, `desktop-bundle-smoke.yml`,
  `e2e-desktop*.yml`, `windows-desktop-attach-e2e.yml`, `windows-bundle-sdk.yml`,
  `.github/actions/desktop-build-cache/**`, `scripts/ci/desktop_build_cache.py`,
  `scripts/ci/desktop_commands.py`
- `tests/ci/test_desktop_*`, `tests/scripts/desktop_update/**`,
  `tests/scripts/test_desktop_*`, `tests-js` desktop/packaging tests.

Edit (keep source distribution):

- `stable-release.yml`, `stable-release-publication.yml`, `canary-release.yml`: remove desktop
  bundle/Store/feed jobs; keep tag creation, source artifacts, and the release notes the source
  channel consumes. If the project will install from `main` only, switch `install.sh`'
  `CHANNEL` default and remove the release workflows consciously — do not leave a dangling default.
- `scripts/releases/` entrypoint/sequencer/lanes: source lanes only.
- `scripts/generate_icons.py`: remove desktop/bootstrap-installer outputs; retarget the icon guard
  (`repo-guards.yml`) in this step or Step 10 at the latest.
- `scripts/ci/classify_changes.py`, `required_results.py`, `.github/actions/detect-changes`.

Verify: `python scripts/check`; workflow YAML lint; `tests/ci/`; a dry-run of the source release
job graph.

**Done:** no workflow builds or publishes a desktop artifact; source tags/releases still work.

---

## Step 3 — `apps/desktop` and the Webapp

**Goal:** delete the Electron app, the renderer, the Webapp, and their build inputs.

Delete:

- `apps/desktop/**`
- `hermes_cli/webapp.py`, `webapp_launcher.py`, `webapp_access.py`, `webapp_sign_in.py`,
  `webapp_page_policy.py`, `webapp_previews.py`, `webapp_relay_target.py`,
  `subcommands/webapp.py`
- `gateway/webapp_listener.py`, `hermes_cli/web_session_sockets.py`,
  `hermes_cli/browser_credential.py`, `web_routers/webapp.py`, `webapp_access.py`,
  `webapp_relay_proxy.py`, `web_server_static_assets.py`
- `hermes_cli/desktop_plugin_*.py`, `hermes_cli/plugin_validate_desktop.py`,
  `web_routers/desktop_plugins.py`
- `apps/desktop` from `pnpm-workspace.yaml`/`package.json` (`install:desktop`),
  `pnpm-lock.yaml` (regenerate), `.envrc`, `lefthook.yml`, `justfile`, `.gitignore`,
  `.dockerignore`, `eslint`/`vitest` overrides
- `apps/shared` desktop-only modules listed in `01-inventory-and-impact.md` §3.1 (and their exports)
- `web_routers/ui_preferences.py`, `hermes_cli/ui_preferences.py`, `web_routers/gateway_connections*`,
  `hermes_cli/gateway_connections*`, `web_host_terminal*` (Webapp/dashboard doors)
- `apps/desktop` references in `ui-tui/scripts/visual/run.mjs` — either add Electron as a
  `ui-tui` devDependency or delete the visual harness (prefer deleting; it exists only to shoot
  Electron screenshots)
- Docker `webapp_build` stage; Nix `desktop.nix`, `webapp.nix`, `#desktop`/`#webapp` outputs,
  home-manager `programs.hermes-agent.desktop.*`, desktop checks
- `tests-js` files importing desktop code (~17), `tests/hermes_cli/test_webapp_*`,
  `tests/gateway/test_webapp_*`, `tests/e2e/.../desktop*`

Edit:

- `scripts/build/freshness.mjs`, `frontend-common.mjs`, `node-deps.mjs`, `inputs.py`,
  `scripts/build/agent.py`: drop desktop/webapp products and workspaces
- `hermes_cli/source_build.py`: products become TUI-only (web goes in Step 4)
- `hermes_cli/venv_sync.py:614-635`: no desktop detection
- `hermes_cli/main.py`: drop `build_webapp_parser`/`cmd_webapp`
- `pyproject.toml` `ruff` per-file-ignore paths under `apps/desktop`
- `scripts/install.sh`/`install.ps1`: no desktop product presence (already done in Step 1)

Verify: `pnpm install --frozen-lockfile` at root; `pnpm -r check` for remaining workspaces;
`pnpm --dir ui-tui run build`; `python scripts/check`; a Docker build of the image (no webapp stage).

**Done:** no reference to `apps/desktop` outside `docs/removal/` (`grep -rn apps/desktop`), and the
remaining JS workspaces install/build with the regenerated lockfile.

---

## Step 4 — Dashboard and `serve`, keep the gateway session listener

**Goal:** remove the browser dashboard and the standalone `serve` command while keeping the local
HTTP/WS listener the gateway uses for CLI/TUI sessions.

First: **audit the seam** (`gateway/run_api.py`, `hermes_cli/web_server*`). Identify which routes the
local CLI/TUI/gateway paths actually use (`/api/ws`, health/readiness, ticket/auth, session reads).
Keep those; drop the rest. This audit is the deliverable of the first PR in the step.

Delete:

- `web/**` (dashboard SPA) and its build (`scripts/build/web.mjs`, `web_dist` references,
  `main_web_build.py`, `pyproject` package-data `web_dist`, Docker dashboard expectations)
- `hermes_cli/web_routers/**` except routes the audit proves are needed by the session listener
- `hermes_cli/dashboard_auth/**`, `web_server_dashboard.py`, `web_server_surface.py` surface
  policies for `dashboard`/`webapp`, `web_server_boundary.py` desktop exemptions,
  `web_server_idle_exit.py`/`owner_exit`/`skew_exit` (desktop-pool retirement fences),
  `dashboard_procs.py`, `dashboard_register.py`, `main_dashboard.py`
- PTY and file surfaces: `pty_bridge.py`, `pty_session.py`, `win_pty_bridge.py` (after checking the
  terminal tool), `web_server_files.py`, `web_server_file_tickets.py`, `web_server_file_response.py`,
  `web_upload_limit.py`, `staged_uploads.py`, `web_asset_mime_types.py`, `web_deps.py`, `web_git.py`,
  `web_models.py`, `web_read_coalescing.py`, `web_whatsapp_session.py`, `web_server_remote_media.py`
- `subcommands/dashboard.py`, `hermes dashboard`/`serve`/`web` CLI entries, `--tui` shim,
  `--ssh-session-token-file`
- `web_routers/display.py` (Bot Screen viewer; also Step 7)
- Nix `web.nix`, `#web` output and dashboard service options; Docker dashboard/webapp stages
- `tests/hermes_cli/test_web_*`, `test_dashboard_*`, `test_web_server*`, `test_serve_*` (keep the
  ones that pin the retained listener), `tests/dashboard/`, `tests/website/test_catalog_rules_mirror`
  adjustments as needed

Edit:

- `hermes_cli/web_server.py` (and `web_server_app.py`, `web_server_lifecycle.py`,
  `web_server_gateway.py`, `web_server_sessions.py`, `web_server_profiles.py`,
  `web_server_chat.py`, etc.): slim to the session API; remove dashboard mounts, SPA fallback,
  browser auth, uploads, plugin dashboards (see Step 8)
- `hermes_cli/main.py`: remove dashboard/serve/web wiring, `_dashboard_sanitize_desktop_env`,
  fastapi/uvicorn availability check for `web`
- `gateway/run_api.py`: remove `warm_gateway_dashboard`/`GatewayDashboardMount` and dashboard
  imports; keep the listener and the native session WS
- `gateway/session_*` and `tui_gateway/*`: remove dashboard-only transports/readiness paths
- `web/` references in `web/AGENTS.md`, root `AGENTS.md` routing table, `tests/AGENTS.md`

Verify: start `hermes gateway` and attach `hermes --tui` and `hermes chat` against it; run
`tests/gateway/` and `tests/tui_gateway/` subsets; `python scripts/check`; `hermes --help` has no
dashboard/serve/web.

**Done:** no dashboard SPA, no browser auth, no standalone server; CLI/TUI/gateway session flows
pass. Target: one local listener, a small route set, no 690-route app.

---

## Step 5 — Desktop CLI, config, update/uninstall branches

**Goal:** remove `hermes desktop|gui`, the Electron build/launch/sign code, and every update,
uninstall, doctor, telemetry, and config branch that exists for the Electron app.

Delete:

- `hermes_cli/main_desktop.py`, `main_desktop_apparmor.py`, `main_desktop_tcc.py`,
  `desktop_build_lock.py`, `desktop_build_reuse.py`, `desktop_console.py`,
  `desktop_release_holders.py`, `desktop_update_verify.py`, `gui_uninstall.py`,
  `bundled_app.py`, `windows_appinstaller_update.py`, `windows_store_update.py`,
  `macos_tcc_anchor.py`, `subcommands/gui.py`, `plugin_validate_desktop.py`
- desktop tests under `tests/hermes_cli/`, `tests/scripts/`, `tests/tools/` (desktop tool tests
  move with Step 6)
- `tests/compat/old_updater_surface.json` and the desktop names in `old_updater_main.py` /
  `old_updater_deps.py` / `scripts/audit-old-updater-imports.py` baseline (D9: no users)

Edit:

- `hermes_cli/main.py`: parser wiring, `_SUBCOMMANDS`, uninstall branches, gui.log mode, desktop
  MCP discovery branch, `is_desktop_owned_backend` uses
- `hermes_cli/linux_desktop_entry.py` → extract `_needs_interpreter` to `relaunch.py` (or a small
  helper) and delete the rest
- `hermes_cli/update_cmd.py`, `update_cmd_windows.py`, `update_cmd_zip.py`, `update_finish.py`,
  `update_completion.py`, `source_completion.py`, `source_build.py`, `update_handoff.py`,
  `venv_sync.py`: remove `had_desktop_app_before_update`, desktop rebuild/handoff, ZIP
  `apps/desktop` preservation, desktop-controlled gateway lifecycle, packaged/unpacked branches
- `hermes_cli/uninstall.py`: remove GUI/data-removal branches, keep CLI uninstall
- `hermes_cli/config_defaults.py`: remove the `desktop` section and `onboarding.run` desktop wiring
- `hermes_cli/process_identity.py`, `anon_challenge.py`, `security_audit_startup.py`,
  `observability/shared_metrics_desktop.py`, `shared_metrics_contract.py` (desktop block),
  `shared_metrics_setup.py`, `shared_metrics_consent.py`
- `hermes_cli/doctor_platform.py` (TCC checks), `steward.py` desktop messages,
  `_launchers.py` bundled/sealed branches, `_startup_fast.py` desktop predicates,
  `data_cleanup.py`, `version_info.py` product identity
- `hermes_cli/commands.py`: remove `desktop`/`desktop_subcommands` fields and the 32 annotations;
  delete `scripts/dump_desktop_slash_registry.py` and the committed registry JSON + test

Verify: `hermes --help`, `hermes update --help`, `hermes uninstall --help`; `tests/hermes_cli/`,
`tests/scripts/test_*update*`, `tests/ci/`; `python scripts/check`.

**Done:** `grep -rn "desktop" hermes_cli/*.py` returns only historical session vocabulary
explicitly marked read-only.

---

## Step 6 — Desktop tools/toolsets and session-surface branches

**Goal:** stop offering renderer-backed tools and delete the desktop session branches while keeping
TUI behavior.

Delete:

- `tools/desktop_ui.py`, `preview_tool.py`, `open_preview_tool.py`, `close_preview_tool.py`,
  `read_preview_tool.py`, `annotate_preview_tool.py`, `drive_preview_tool.py`,
  `read_terminal_tool.py`, `close_terminal_tool.py`, `read_window_tool.py`, `focus_pane_tool.py`,
  `react_to_message_tool.py`, `tour_tool.py`, `tip_tool.py`, `set_theme_tool.py`,
  `setup_beat_tool.py`, `browser_vault_preview.py` (verify the vault preview is Webapp-only)
- `gateway/local_desktop_ui.py`
- toolsets `desktop_ui`, `catalog`, `onboarding`; `CLIENT_SURFACE_TOOLSETS` → `{"project"}`
- `tui_gateway/methods_onboarding.py` desktop first-run cards (keep CLI onboarding if it stays),
  `tui_gateway` desktop bridges (`server_requests.py`, `session_notifications._wire_desktop_sinks`)
- desktop branches: `gateway/session_policy.py` (`LOCAL_DESKTOP_CHAT`, `gui` surface),
  `gateway/session_local.py`, `gateway/hosted_room_peer.py` `HERMES_DESKTOP` gate,
  `agent/prompt_builder.py` desktop platform block, `agent/onboarding_text.py` desktop copy

Edit: `tools/registry.py` / `model_tools.py` discovery, `toolsets.py`, `tool_search`,
`mcp_tool_agent`, `agent/agent_runtime_helpers.py`, `tui_gateway/agent_factory.py` platform
resolution, `commands.py` catalog surface.

Verify: tool discovery (`discover_builtin_tools`), `hermes tools list`, TUI toolset behavior,
`tests/tools/` (minus deleted desktop tool tests), `tests/tui_gateway/`; `python scripts/check`.

**Done:** no renderer-backed tool is registered; TUI/CLI tool lists are unchanged except the
removed desktop-only entries.

---

## Step 7 — Bot Mode

**Goal:** remove the Bots UI backend, the relay, and the headless Bot Desktop screen. Prerequisite:
D7 decided.

If `computer_use` stays (recommended only with a real display backend):

- **First** refactor `tools/computer_use/tool.py` and `cua_backend.py` to drop
  `tools.bot_desktop` imports: lease check becomes a no-op, `desktop_env` uses the host env,
  sandbox placement logic is removed. Land this refactor in a separate PR and verify
  `tests/tools/test_computer_use*`.

Delete:

- `tools/bot_desktop/**` (13 files), `tools/bot_relay.py`,
  `tui_gateway/methods_bot_relay.py`
- `hermes_cli/subcommands/computer_use_screen.py`, `web_routers/display.py`
  (already gone with Step 4 if removed there)
- `hermes_cli/subcommands/peer.py` and `gateway/platforms/api_server*` **only if** bot-to-bot DMs
  are also out (D8); otherwise keep `api_server` as a gateway platform and remove only the peer
  pieces that reference Bot Mode
- `evals/botmode-*`, `evals/desktop-*` bot fixtures; `docker/sandbox-desktop*` if nothing else uses
  them; `toolsets.py` `bot_room` if hosted rooms are Bot Mode only
- config `bot_mode`, `bot_desktop` sections; `locales` bot-mode strings

Verify: `tests/tools/test_computer_use*`, gateway bot-room tests, `python scripts/check`.

**Done:** no Bot Mode UI/relay/screen code remains; `computer_use` works on a real display or is
removed by decision.

---

## Step 8 — Desktop plugin SDK/halves and catalog shelf

**Goal:** remove the UI-plugin contract that only the desktop/Webapp could load.

Delete:

- `desktop/plugin.js` from `_LOADABLE_ENTRYPOINTS` and `check_desktop_surface` call sites
- `plugins.manage install_desktop/remove_desktop` RPCs and `has_desktop_half`
- `.desktop.yaml` locale packs and `locales/_keys.desktop.json`
- plugin dashboards that exist only for the web dashboard (`plugins/kanban/dashboard/`,
  `plugins/hermes-achievements/dashboard/`) after confirming their Python APIs are not used by the
  agent side
- `plugin-catalog` rule 8 and the docs mirror; reclassify the 240 `category: desktop` entries
  (suggested: `ui` → `general`, or hide the shelf) via `scripts/validate_plugin_catalog.py` + catalog
  data PR

Edit: `hermes_cli/plugin_validate.py`, `plugins_cmd_inspect.py`, `plugins_cmd_catalog.py`,
`plugins_context.py`, `plugins_manifest.py`, `plugin_catalog.py`, `hermes_cli/data/plugin_api.json`
(docs), `plugin-catalog/README.md`, `website` catalog pages, `tests/hermes_cli/test_plugin_validate.py`,
`tests/website/test_catalog_rules_mirror.py`, `tests/website/test_extract_plugins.py`.

Verify: plugin validation tests, catalog validation, plugin install/update smoke.

**Done:** only Python plugins remain; catalog has no desktop shelf/rule.

---

## Step 9 — Docs, website, i18n, skills

**Goal:** the docs site builds and claims only what exists.

- Delete the pages listed in `01-inventory-and-impact.md` §3.5; delete their `sidebars.ts` entries.
- Edit installation/updating/quickstart/platform-support/nix-setup/windows-native/configuration/
  reference/developer-guide pages: remove desktop, Webapp, dashboard, Bot Mode, installer claims and
  links. `switching-to-source.md` is mostly about migrating a desktop install — delete or rewrite.
- Website app: remove navbar/footer download links, PluginCatalog desktop install links/shelf,
  review user stories.
- zh-Hans: delete/rewrite the 31 affected pages; there are no translated desktop/dashboard pages to
  delete.
- Skills: delete `optional-skills/software-development/inspecting-hermes-desktop-dom/`, desktop
  plugin references in `skills/autonomous-ai-agents/hermes-agent/`; regenerate skill docs.
- Regenerate the plugin/skill catalogs; do not hand-edit generated pages.

Verify: `python website/scripts/check_doc_links.py`; `pnpm --dir website build` (or the repo's
`docs-site-checks` lane); `generate-skill-docs.py` produces no diff; `python scripts/check`.

**Done:** docs site builds in both locales with no desktop/dashboard/bot references outside
historical changelog-like pages.

---

## Step 10 — Tests and CI gates

**Goal:** delete dead tests, fix the path-assertion gates, and keep required checks consistent.

- Delete the test files matched in `01-inventory-and-impact.md` §3.6 (~361 by name / 85k lines) and
  prune content-matched ones to edits.
- Re-home or delete cross-language parity fixtures that read desktop sources
  (`tests/e2e/core/parity/_boot_contract.py`, `tests/gateway/fixtures/execution_frames_capture.py`,
  `tests/gateway/test_local_display_key.py`).
- Update `scripts/ci/classify_changes.py`, `scripts/ci/required_results.py`,
  `.github/actions/detect-changes/action.yml`, `ci.yaml` job graph/`all-checks-pass`,
  `.github/workflows/README.md`, `js-tests.yml`, `nix.yml`, `repo-guards.yml` (icons),
  `install-e2e*` desktop legs, `docker.yml` (webapp/dashboard stages).
- Update `tests/ci/` path-assertion tests in the same PR; keep `windows-install-update-e2e.yml`
  (source install/update) and the source installer E2E lane.
- Update root/area `AGENTS.md` routing tables and `tests/AGENTS.md` references.

Verify: `scripts/run_tests.sh` for the touched suites; `python scripts/check`; a CI dry-run/graph
validation if available.

**Done:** no test or workflow references a deleted path; the required-check aggregate is satisfiable.

---

## Step 11 — Dependencies, build graph, startup lists

**Goal:** realize the install/build/startup savings.

- `pyproject.toml`: after the dashboard/Webapp/PTY removal, re-check every web-stack dependency and
  drop what is now unused (`fastapi`, `uvicorn`, `httptools`, `watchfiles`, `python-multipart`,
  `ptyprocess`/`pywinpty` if the terminal tool no longer needs them, `pywin32`/`winrt-*` if only
  desktop update checks used them). **Do not guess:** grep the remaining tree and keep what the
  gateway listener, TUI, and `api_server` platform import.
- Re-run `hermes pm lock` and commit `uv.lock`.
- `pnpm-workspace.yaml` / `pnpm-lock.yaml`: remove desktop/bootstrap importers (Step 3), then prune
  `allowBuilds`/`overrides`/`minimumReleaseAgeExclude` entries that existed for Electron.
- `scripts/build/{node-deps,freshness,frontend-common}.mjs`, `scripts/build/inputs.py`,
  `scripts/build/agent.py`, `hermes_cli/source_build.py`, `hermes_cli/source_completion.py`:
  only TUI (+ launchers) products.
- `pyproject.toml` `update-startup-files` and package data: remove deleted modules, `web_dist`.
- `hermes_cli/main.py` startup imports: remove deleted modules and confirm cold-start budget.

Verify: `hermes pm lock`; `python scripts/check`; fresh source install + `hermes update` smoke;
`hermes --tui` cold start timing before/after.

**Done:** dependency tree, lockfiles, and startup lists match the trimmed tree.

---

## Step 12 — Final verification and repo docs

**Goal:** prove the end state and publish the numbers.

Acceptance run:

1. Clean clone install: `bash scripts/install.sh` (macOS/Linux) and `install.ps1` (Windows), then
   `hermes --help`, `hermes chat -q "hi"`, `hermes --tui`, `hermes gateway` with a Telegram token.
2. `hermes update` from a previous commit on the branch (source update path).
3. `python scripts/check`; the touch suites; `pnpm -r check` for remaining workspaces.
4. `grep -rn "apps/desktop\|bootstrap-installer\|web_routers\|HERMES_DESKTOP"` — only historical
   session vocabulary and this plan.
5. Record final metrics and update `03-optimization.md`, root `README.md`, `AGENTS.md` routing
   tables, `CONTRIBUTING.md` PR-area list.

**Done:** end-state metrics filled in; the branch is the new baseline.
