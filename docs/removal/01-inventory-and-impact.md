# 01 — Inventory and impact

Baseline: `8d7061f1a7`, the last code commit before deletion work (the branch is based on
`b309d5015f`, whose only addition is `history/` docs). `git ls-files` and `wc -l`
counts; no `node_modules` in the checkout.

## 1. What the removed surfaces actually are

| Surface | Where it lives | Notes |
|---|---|---|
| Electron desktop app | `apps/desktop/electron/` (main process), `apps/desktop/src/` (renderer), `e2e/`, packaging configs | 4,877 files, 1,048,410 lines, 58 MB. `src/` is also the Webapp renderer |
| Webapp | `apps/desktop/scripts/build-webapp.mjs` → `apps/desktop/dist-webapp`; `hermes_cli/webapp*.py`; `gateway/webapp_listener.py`; Docker `webapp_build` stage; Nix `webapp.nix` | "Desktop workspace in a browser". Cannot survive a plain `apps/desktop` deletion: it is built from the same renderer |
| Dashboard | `web/` SPA (262 files / 66,258 lines), `hermes_cli/web_server*.py`, `hermes_cli/web_routers/` (37 files, 298 REST routes), `hermes_cli/dashboard_auth/` (18 files), `main_dashboard.py`, `dashboard_procs.py`, `subcommands/dashboard.py` | `hermes dashboard` and `hermes serve` run the same FastAPI app |
| Bot Mode | `bot_relay` (`tools/bot_relay.py`, `tui_gateway/methods_bot_relay.py`), Bots UI (inside the desktop renderer), Bot Desktop (`tools/bot_desktop/`, 13 files), viewer (`subcommands/computer_use_screen.py`, `web_routers/display.py`) | Bot = profile; profiles/cron themselves stay |
| GUI installer | `apps/bootstrap-installer/` (Tauri, 51 files / 11,699 lines), installer stage protocol, `-IncludeDesktop` stages | Drives `scripts/install.ps1`/`install.sh` |

`apps/shared` (`@hermes/shared`) is **shared with `web/` and `ui-tui/`** — the package stays; only
seven desktop-only modules are removed.

## 2. Baseline measurements

| Area | Files | Lines |
|---|---|---:|
| Tracked repository | 23,084 | 4,915,885 |
| Checkout size (no `.git`) | — | 286 MB |
| `apps/desktop` | 4,877 | 1,048,410 (58 MB) |
| `apps/bootstrap-installer` | 51 | 11,699 |
| `apps/shared` (stays) | 77 | 70,330 |
| `web/` dashboard SPA | 262 | 66,258 |
| `ui-tui/` (stays) | 663 | 125,368 |
| `tui_gateway/` (stays) | 127 | 50,644 |
| Python, all | 10,948 | 2,681,295 |
| Python, `tests/` | 7,795 | 1,611,845 |
| Python, non-test | 3,153 | 1,069,450 |
| Docs site | 791 | 338,538 |
| Tests, all files | 7,931 | 1,643,822 |
| CI workflows | 44 | 11,804 |

Removal-scope Python modules (measured groups):

| Group | Files | Lines |
|---|---:|---:|
| web / dashboard / webapp / gateway-connections / UI-prefs / host-terminal (`hermes_cli`) | 117 | 44,553 |
| gateway webapp listener, `local_desktop_ui`, shared-metrics-desktop, dashboard/webapp subcommands | 8 | 4,103 |
| desktop CLI cluster (`main_desktop*`, `desktop_*`, `gui_uninstall`, `linux_desktop_entry`, `bundled_app`, Windows updaters, `subcommands/gui`) | 18 | 5,668 |
| desktop tools (preview/terminal/window/theme/tour bridge) | 17 | 1,570 |
| bot-mode Python (`tools/bot_desktop/`, `bot_relay`, `methods_bot_relay`, screen subcommand) | 15 | 3,789 |
| desktop plugin halves (`desktop_plugin_*.py`, `plugin_validate_desktop.py`) | 3 | 699 |
| **Total removable Python** | **~180** | **~60,400** |

Other measured surfaces:

- Tests touched by this removal: 642 files / 176,713 lines (361 files / 85,443 lines match by name;
  the rest reference removed modules and need edits, not necessarily deletion).
- Scripts in scope: 68 files / 22,051 lines (not all deleted — release/build installers are trimmed).
- CI: 20 workflows / 6,403 lines touch installers, desktop, or release; 10 dedicated desktop/GUI
  workflows account for 3,942 lines.
- `pnpm-lock.yaml`: 12,890 lines; importers for `apps/desktop` (84 prod + 39 dev deps, 371 lines)
  and `apps/bootstrap-installer` (83 lines) are 454 of the 789 importer lines.
- Config: `desktop` 14 keys, `dashboard` 16 keys, `bot_mode` 2, `bot_desktop` 5, `onboarding` 3,
  `webapp` 1 — about 41 keys; 249 files mention `HERMES_DESKTOP`, 153 `HERMES_DASHBOARD`,
  25 `HERMES_SERVE`.
- Toolsets: 42 → 39 (remove `desktop_ui`, `catalog`, `onboarding`; keep `project` — TUI folds it
  in at `tui_gateway/agent_factory.py`); ~13 tool names and ~17 tool modules go.
- Slash-command registry: 32 `desktop=` annotations and the generated slash registry dump.
- API surface: `web_server` mounts about 690 routes (see `gateway/run_api.py` docstring);
  `web_routers/` alone has 298 routes. Target after the trim: the local session listener only.

## 3. Deletion inventory by layer

### 3.1 Application trees

- `apps/desktop/**` — whole tree (Electron main, renderer, e2e, assets, packaging, docs, configs).
- `apps/bootstrap-installer/**` — whole tree.
- `web/**` — whole dashboard SPA.
- Nix: `nix/desktop.nix`, `nix/webapp.nix`, `nix/web.nix`, desktop/home-manager options in
  `nix/homeManagerModules.nix`, desktop checks in `nix/checks.nix`, desktop test helpers.
- Docker: `webapp_build` stage and `apps/desktop/dist-webapp` copy in `Dockerfile`; dashboard/webapp
  expectations in `.dockerignore`.
- `apps/shared`: only `backend-scope.ts`, `data-url-read-max.ts`, `external-url.ts`, `file-url.ts`,
  `hermes-cloud.ts`, `skill-scaffold.ts`, `translucency.ts` (drop the exports too). Keep the rest.

### 3.2 Python core

- Delete: `hermes_cli/main_desktop.py`, `main_desktop_apparmor.py`, `main_desktop_tcc.py`,
  `desktop_build_lock.py`, `desktop_build_reuse.py`, `desktop_console.py`,
  `desktop_release_holders.py`, `desktop_update_verify.py`, `gui_uninstall.py`,
  `linux_desktop_entry.py` (extract `_needs_interpreter` first), `bundled_app.py`,
  `windows_appinstaller_update.py`, `windows_store_update.py`, `macos_tcc_anchor.py`,
  `plugin_validate_desktop.py`, `desktop_plugin_halves.py`, `desktop_plugin_install.py`,
  `subcommands/gui.py`, `subcommands/webapp.py`, `subcommands/dashboard.py`,
  `subcommands/computer_use_screen.py`.
- Delete Webapp: `hermes_cli/webapp*.py`, `gateway/webapp_listener.py`, `web_routers/webapp*`,
  `web_session_sockets.py`, `browser_credential.py`, `web_server_static_assets.py`.
- Delete dashboard plumbing: `web/*` Python (see §2 groups), `web_routers/**`, `dashboard_auth/**`,
  `main_dashboard.py`, `dashboard_procs.py`, `dashboard_register.py`, `main_web_build.py`,
  `web_host_terminal*`, `ui_preferences.py`, `gateway_connections*`, `pty_bridge`/`pty_session`,
  `staged_uploads`, `memory_oauth` (after checking its non-dashboard consumers).
- Delete bot mode: `tools/bot_desktop/**` (13 files), `tools/bot_relay.py`,
  `tui_gateway/methods_bot_relay.py`, `web_routers/display.py`.
- Delete desktop tools: `tools/desktop_ui.py` and the 16 preview/terminal/window/theme/tour tools.
- Edit (not delete): `hermes_cli/main.py`, `commands.py`, `config_defaults.py`, `source_build.py`,
  `source_completion.py`, `update*`, `uninstall.py`, `venv_sync.py`, `doctor_platform.py`,
  `process_identity.py`, `anon_challenge.py`, `steward.py`, `_launchers.py`, `_startup_fast.py`,
  `relaunch.py`, `data_cleanup.py`, `toolsets.py`, `tools/registry` registration sites,
  `agent/prompt_builder.py`, `agent/onboarding_text.py`, `tui_gateway/*`, `gateway/session_*`,
  `gateway/run_api.py`, `web_server*` core (slim to the session listener).

### 3.3 Tools / toolsets / plugins / locales

- Toolset `desktop_ui` (11 tools), `catalog` (`manage_catalog`), `onboarding` (`setup_beat`);
  `CLIENT_SURFACE_TOOLSETS` reduced to `project`; GUI tools no longer registered.
- Desktop plugin halves: `desktop/plugin.js` loadable entrypoint, `plugin_validate` rule 8,
  `plugins.manage install_desktop/remove_desktop` RPCs, `has_desktop_half`, `.desktop.yaml` locale
  packs, `locales/_keys.desktop.json`, `@hermes/plugin-sdk` docs.
- Plugin dashboards that exist only for the web dashboard: `plugins/kanban/dashboard/`,
  `plugins/hermes-achievements/dashboard/` (decide whether the Python plugin APIs themselves stay).
- Plugin catalog: 240 entries on the default `category: desktop` shelf — relabel/hide; catalog
  admission rule 8 and its docs mirror are removed together.

### 3.4 Installers, build, release, CI

- Installers: `--include-desktop`/`-IncludeDesktop`, `desktop` pseudo-stage,
  `desktop_product_present`/`Test-DesktopProductPresent`, `Confirm-DesktopArtifact`,
  `New-DesktopShortcuts`, `-ProtocolVersion`; replace `scripts/desktop-update/runtime.ps1` use in
  `install.ps1`; keep all source-install stages and the `complete` marker.
- Build: `scripts/build/desktop*.mjs`, `electron-runtime.mjs`, `webapp.mjs`; `build-bundle.sh/.ps1`;
  desktop branches in `node-deps.mjs`, `freshness.mjs`, `frontend-common.mjs`, `inputs.py`,
  `agent.py`; `scripts/bundles/desktop*.py`, `dmgbuild_diagnostics.py`, `msix_names.py`,
  `set_dmg_volume_icon.sh`; `msix-shared.mjs`, `stage-msixbundle.mjs`,
  `bundle-store-msixbundle.mjs`.
- Release: `scripts/desktop-update/**`, `scripts/desktop-update.ps1`, `scripts/release.py`
  desktop dispatch, desktop lanes in `scripts/releases/*`, `stamping.py` Cargo/Tauri stamping,
  `render-builds-table.py`, `dump_desktop_slash_registry.py`, desktop targets in
  `generate_icons.py`, `scripts/ci/desktop_*`, `.github/actions/desktop-build-cache`.
  **Keep the source-release/tag pipeline** — the source installer's stable channel resolves tags
  and GitHub releases.
- CI: delete `desktop-bundled-release.yml`, `desktop-bundle-smoke.yml`, `e2e-desktop.yml`,
  `e2e-desktop-core.yml`, `e2e-desktop-update.yml`, `windows-desktop-attach-e2e.yml`,
  `windows-bundle-sdk.yml`, `bootstrap-installer-build.yml`, `rust-tests.yml`; trim desktop legs of
  `install-e2e*`; re-scope `stable-release*`, `canary-release`, `ci.yaml`, `js-tests.yml`,
  `repo-guards.yml` icon check, `.github/actions/detect-changes`, `scripts/ci/classify_changes.py`,
  `scripts/ci/required_results.py`, `.github/workflows/README.md`.
- Docs build: `sidebars.ts` entries are hard build errors; `check_doc_links.py` and
  `generate-skill-docs.py` are hard CI gates.

### 3.5 Docs, i18n, skills

- Delete pages: `user-guide/desktop.md`, `user-guide/multi-connection-desktop.md`,
  `user-guide/bot-mode.md`, `user-guide/features/bot-screen.md`,
  `developer-guide/desktop-plugin-sdk.md`, `developer-guide/macos-bundle-updates.md`,
  `guides/desktop-native-signin.md`, `user-guide/features/web-dashboard.md`,
  `developer-guide/worktree-ui-dev.md` (or retitle to TUI-only).
- Edit: installation, updating, quickstart, platform-support, nix-setup, windows-native,
  configuration, reference/*, developer-guide/* (~90 English files), plus 31 zh-Hans files.
- Skills: `optional-skills/software-development/inspecting-hermes-desktop-dom/`, desktop-plugin
  references in `skills/autonomous-ai-agents/hermes-agent/`, then regenerate skill docs.
- Website app: navbar/footer download links, `website/src/components/PluginCatalog/catalog.ts`
  desktop install deep links, plugin shelf config, `userStories.json` review.

### 3.6 Tests

- Delete: `tests/desktop/`, `tests/scripts/desktop_update/` (38), `tests/hermes_cli/test_desktop_*`
  / `test_gui_*` / `test_webapp_*` / `test_dashboard_*` / `test_web_server*` / `test_linux_desktop*`,
  `tests/tools/*desktop*`, `tests/ci/test_desktop_*`, `tests/install/*bundled*`,
  `tests-js/desktop-*`, `tests-js/electron-*`, `tests-js/macos-*`, `tests-js/notarize*`,
  `apps/desktop/e2e` (goes with the tree).
- Edit: session/toolset/prompt/update/uninstall tests that only mention a removed branch;
  parity fixtures that read desktop sources (`tests/e2e/core/parity/_boot_contract.py`,
  `tests/gateway/fixtures/execution_frames_capture.py`) must be re-homed or deleted.
- Probe result: 642 test files / 176,713 lines are name- or import-matched; roughly half should be
  deleted, the rest edited.

## 4. Seams that must be refactored, not deleted

1. **Gateway local session API.** `gateway/run_api.py` is the gateway's local HTTP/WS listener and
   serves the native session WebSocket (`/api/ws`) that local CLI/TUI sessions attach to. It is not
   dashboard code. Keep the listener, delete the dashboard app/mount, auth pages, uploads, files,
   PTY terminal, display/RFB and webapp surfaces, and slim `web_server*` to what `/api/ws` needs.
   This is the highest-risk seam in the project; audit it first in Step 4.
2. **`tui_gateway`** is shared by TUI, dashboard, and desktop: keep the TUI protocol; remove
   desktop/bot/webapp-only RPCs, capability branches, and product-named strings.
3. **`apps/shared`** stays (web/ and ui-tui depend on it); only the seven desktop-only modules go.
4. **`hermes update` completion.** `source_build.py` currently builds TUI + web + desktop and the
   installers share the same completion. Keep `complete`/`.hermes-bootstrap-complete`, keep TUI
   build, drop web and desktop products.
5. **Installers.** `scripts/install.sh`/`install.ps1` stay (source install), but `install.ps1`
   text-loads `scripts/desktop-update/runtime.ps1`; replace that with a direct `.hermes/bin/hermes`
   invocation before deleting the desktop-update directory.
6. **Source release channel.** The stable install channel resolves GitHub releases/tags. Desktop
   bundle jobs are removed, but tag/release cutting for source installs must remain (or the default
   channel must be changed deliberately).
7. **Plugin system.** Python plugin API and bundled Python plugins stay; the desktop half/SDK and
   its catalog rules go.
8. **`computer_use` ↔ Bot Desktop.** `tools/computer_use/tool.py` and `cua_backend.py` import
   `tools.bot_desktop` on every call (`ensure_started_for_tool`, lease checks, `desktop_env`).
   Deleting Bot Desktop requires refactoring the tool to the host display — decide D7 before Step 7.
9. **TUI visual harness.** `ui-tui/scripts/visual/run.mjs` borrows the Electron binary from
   `apps/desktop/package.json`; either add Electron as a `ui-tui` devDependency or drop the harness.
10. **Generated artifacts.** `apps/desktop/src/lib/desktop-slash-registry.json`,
    `execution-authority.frames.json`, `locales/_keys.desktop.json`, icon outputs, and generated
    catalog/skill docs must be removed together with their generators and pinning tests.

## 5. Functional impact

Removed user-visible capabilities:

- `hermes desktop` / `hermes gui` (build/launch/sign/sandbox flags), `hermes webapp`,
  `hermes dashboard`, `hermes serve` (standalone), `hermes uninstall --gui` family,
  `hermes computer-use screen`.
- Native desktop UI: panes/tabs, terminal, browser tabs, file browser, artifacts, git review,
  memory graph, quick entry, voice/HUD/wake-word, pets, settings, onboarding, multi-connection
  (local/remote/cloud/SSH), 9 locales.
- Bot Mode UI, Bot Screen viewer, bot relay, `hermes peer` bot-to-bot DMs (audit before removing).
- Desktop agent tools/toolsets (preview, drive preview, terminal tabs, window reads, focus, theme,
  tour, tips) — these never worked outside the desktop app anyway, so CLI/TUI capability does not
  regress, but the model-facing tool list shrinks.
- Packaged distribution and its update machinery: DMG/ZIP/AppImage, MSIX/MSIXBundle/Store,
  signing/notarization, electron-updater channels, App Installer, builds table/download pages,
  Hermes-Setup.
- Desktop plugin ecosystem: `@hermes/plugin-sdk`, `desktop/plugin.js`, desktop locale packs,
  desktop catalog shelf.
- Desktop-side telemetry/metrics surfaces, `HERMES_DESKTOP*` identity branches, `desktop`/`gui`
  session-source writers (historical rows remain readable — no migration).

Kept: agent loop, tools, cron, CLI, TUI, `tui_gateway`, gateway adapters (Telegram), sessions,
profiles, Python plugins, PM, source install/update, Docker/Nix/Termux packaging (trimmed).

## 6. Risks / traps

1. **`web_server` seam misjudged.** Deleting the dashboard wholesale would break the gateway's
   local session WS that CLI/TUI attach to. The route audit in Step 4 is mandatory; "about 690
   routes" must not become zero.
2. **`computer_use` import chain.** Deleting `tools/bot_desktop` without refactoring the tool breaks
   `computer_use` at call time (lazy imports, not import time).
3. **Tool registry.** Deleting tool modules without removing registration sites (`toolsets.py`,
   `model_tools.py` discovery, `agent/agent_runtime_helpers.py`) fails tool discovery wholesale.
4. **Top-level import surfaces.** `hermes_cli/main.py` imports `main_desktop` symbols at module
   level; `web_server` imports removed routers at module level. Remove the imports in the same PR.
5. **Repo-guards icon gate.** `repo-guards.yml` regenerates icons into `apps/desktop/**` and
   `apps/bootstrap-installer/**` and diffs them; retarget `generate_icons.py` in the same change.
6. **Docs gates.** Docusaurus sidebar IDs, `check_doc_links.py`, `generate-skill-docs.py`, and the
   catalog-rules mirror test fail on stale references.
7. **Lockfile / workspace policy tests.** Removing two pnpm projects requires a lockfile
   regeneration; `tests-js` policy tests assert workspace membership.
8. **Cross-language parity fixtures.** Python tests parse desktop TypeScript sources; re-home or
   delete them.
9. **Release channel.** Removing all tag/release jobs silently breaks `install.sh`'s stable default.
10. **Tests/CI drift.** Removing paths from classifiers (`classify_changes.py`,
    `required_results.py`) while jobs still reference them turns aggregate checks red; branch
    protection is external.
