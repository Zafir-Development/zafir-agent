# 03 — Optimization: before vs. after

Baseline `8d7061f1a7` (last code commit; `b309d5015f` adds only `history/` docs). "After" numbers are estimates derived from the inventory in
[01-inventory-and-impact.md](01-inventory-and-impact.md); fill in the measured column at Step 12.

## Summary

The optimization is about **product surface, distribution, and maintenance cost**, not about the
agent's per-turn speed. The agent loop, tool-call protocol, and gateway messaging path are
untouched, so model latency and token cost do not change for CLI/TUI sessions.

| Dimension | Before | After (estimate) | Δ |
|---|---:|---:|---:|
| Tracked files | 23,084 | ~17,100–17,500 | −24–26% |
| Tracked lines | 4,915,885 | ~3,570,000–3,680,000 | −25–27% |
| Checkout size (no `.git`) | 286 MB | ~228 MB | −20% |
| Application trees (desktop + installer + dashboard SPA) | 1,126,367 lines | 0 | −100% |
| Python, all | 10,948 files / 2,681,295 lines | ~10,770 files / ~2,520,000 lines | −6% |
| Python, non-test | 1,069,450 lines | ~1,009,000 lines | −6% |
| Tests (all files) | 7,931 / 1,643,822 lines | ~7,300 / ~1,470,000 lines | −8–11% |
| `pnpm-lock.yaml` | 12,890 lines, 8 workspace importers | ~9,300–9,800 lines, 5 importers (`.`, `apps/shared`, `tests-js`, `ui-tui`, `ui-tui/packages/hermes-ink`) | −25–28% lock, −57% importer lines |
| Workspace node deps for the removed apps | ≈84 prod + ≈39 dev (`apps/desktop`), 83 importer lines (installer) | 0 | gone |
| CI workflows | 44 / 11,804 lines | ~35 / ~8,000 lines | −20% workflows, −32% YAML |
| Config keys for removed surfaces | ~41 (`desktop` 14, `dashboard` 16, `bot_mode` 2, `bot_desktop` 5, `onboarding` 3, `webapp` 1) | 0 | gone |
| Toolsets | 42 | 39 | −3 |
| Renderer-backed tools | ~13 names / 17 modules | 0 | gone |
| HTTP routes (dashboard + webapp + session app) | ~690 | target <100 (session listener only) | ≈−85% |
| Locally bound listeners | dashboard 9119, webapp 9120, RFB screen socket, host-terminal sockets | local session API only | ≈−3 services |
| Docs pages | 10 pages / 7,684 lines deleted, ~90 edited, 31 zh-Hans | core + TUI + gateway docs only | — |
| Product surfaces | 4 (desktop, Webapp, dashboard, TUI/CLI) + bot mode | 2 (CLI, TUI) + gateway | fewer moving parts |

## What gets measurably better

1. **Install/fetch footprint.** 58 MB of the checkout disappears (`apps/desktop`), plus the
   Electron matcher/toolchain dependency graph: the desktop pnpm importer alone carries 84 prod and
   39 dev packages, and the lockfile's Electron/builder/Playwright surface is removed. Electron is
   never downloaded for dev, CI, or source installs. The Python side keeps FastAPI/uvicorn for the
   gateway session listener, so the Python wheel set shrinks only where the audit proves a package
   was dashboard-only (Step 11).
2. **Cold start.** The code documents that importing `hermes_cli.web_server` (the ~690-route app)
   costs about 0.6 s before the gateway's listener can bind (`gateway/run_api.py` docstring).
   Slimming the app to the session listener removes that import from the boot path; measure
   `hermes gateway` and `hermes --tui` cold start before/after and record it here.
3. **Attack surface.** Removed: browser login/OAuth pages and cookie/token auth, dashboard and
   Webapp listeners, file manager and upload endpoints, PTY terminal bridge, host-terminal SSH,
   RFB screen viewer, plugin dashboard HTTP APIs, desktop plugin JS loading, and the
   desktop/dashboard update handoff. Nothing listens on 9119/9120 after this change.
4. **CI and release cost.** 9 desktop/installer workflow files (~3,800 YAML lines) disappear or
   reduce to one source-installer lane, the 2,489-line `desktop-bundled-release.yml` release train
   is gone, and release moves to
   source-tag/source-artifact only: no signing, notarization, MSIX/Store, R2 feeds, or desktop E2E.
5. **Maintenance surface.** One frontend product (TUI) instead of four; one update mechanism
   (source update) instead of source + electron-updater + MSIX App Installer + Store; no desktop
   plugin SDK / half contract; no desktop-only toolsets in the registry; ~41 config keys and a
   quarter of the `HERMES_*` environment matrix removed (249 files mention `HERMES_DESKTOP`,
   153 `HERMES_DASHBOARD`).
6. **Docs.** Ten product pages (7,684 lines) and their navigation/sidebar/link upkeep disappear; the
   site no longer promises downloads, MSIX, Webapp, dashboard, or Bot Mode.

## What does NOT improve (be honest)

- **Agent behavior and cost.** `agent/` (152,886 lines), `gateway/` (132,926), and `tools/`
  (131,812) stay largely intact. The model still gets the same tools for CLI/TUI sessions:
  `desktop_ui`/`catalog`/`onboarding` were only folded in for desktop-sourced sessions, so their
  removal does not shrink the tool payload the model sees on CLI/TUI. Prompt caching is unaffected.
- **Messaging gateway.** Telegram/Discord/etc. adapters, sessions, cron, hosted rooms stay; the
  gateway's local HTTP/WS listener stays because CLI/TUI sessions attach through it.
- **Python dependency floor.** `fastapi`/`uvicorn`/`httptools`/`watchfiles`/`python-multipart` are
  declared as core dependencies today; whether they can be dropped depends on the Step 4 route
  audit and the `api_server` gateway platform. Do not claim their removal until verified.
- **Tests dominate the tree.** 7,931 test files / 1,643,822 lines are 33% of tracked files and 33%
  of tracked lines; this trim touches ~642 of them and deletes roughly half of those. The repo
  remains test-heavy.
- **Website** stays at ~330k lines (docs only shrink by the removed pages).
- **Repo history** does not shrink; only the working tree does.

## Measurement

Run before Step 1 and after Step 12; paste both into the PR.

```bash
# tracked size
git ls-files | wc -l
git ls-files | tr '\n' '\0' | xargs -0 wc -l | awk '$2 != "total" {s+=$1} END {print s}'
du -sh .          # worktree, excluding .git via du -sh --exclude=.git on GNU

# python split
git ls-files '*.py' | wc -l
git ls-files '*.py' | grep -v '^tests/' | tr '\n' '\0' | xargs -0 wc -l | awk '$2 != "total" {s+=$1} END {print s}'

# lockfile / workspace
awk '/^importers:/{f=1} f && /^  [^ ].*:$/{print}' pnpm-lock.yaml
grep -c 'electron' pnpm-lock.yaml

# surfaces
grep -rl 'HERMES_DESKTOP' --include='*.py' --include='*.ts' --include='*.mjs' . | wc -l
grep -rl 'apps/desktop' . | wc -l
ls .github/workflows | wc -l

# cold start (after install)
/usr/bin/time -p hermes gateway --help
/usr/bin/time -p hermes --tui --version   # or the repo's start timing harness
```

## Rough effort

13 steps, ~25–40 developer-days for one person familiar with the codebase; steps 1–3 and 8–9 are
parallelizable, steps 4–6 are sequential. The highest-risk item is Step 4 (splitting the dashboard
from the gateway session listener), not the file deletion itself.
