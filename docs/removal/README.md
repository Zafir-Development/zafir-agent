# Trimming Hermes to its core: CLI + TUI + gateway

**Status:** planning. Nothing in this branch has been deleted yet.
**Branch:** `trim-core-surfaces`, based on `master` (`b309d5015f`). Baseline measurements were taken at
`8d7061f1a7`, the last code commit; `b309d5015f` adds only `history/` docs.
**Purpose:** remove every product surface we do not intend to ship and keep only the agent core,
the classic CLI, the TUI, and the messaging gateway (Telegram first).

This directory is the source of truth for the scope and the order of work. It is not part of the
published documentation site.

## Decisions (recorded 2026-11-08)

| # | Decision | Status |
|---|---|---|
| D1 | Remove the Electron desktop app (`apps/desktop`) | accepted |
| D2 | Remove the Webapp (the browser-hosted renderer built from `apps/desktop`) | accepted — not extracted into a separate package |
| D3 | Remove the dashboard (`web/`, `hermes dashboard`) and the standalone `hermes serve` backend | accepted |
| D4 | Remove Bot Mode: the Bots UI, `bot_relay`, and the headless Bot Desktop screen | accepted; `computer_use` handling is an open sub-decision (see D7) |
| D5 | Remove the GUI bootstrap installer (`apps/bootstrap-installer`, "Hermes-Setup") | accepted |
| D6 | Keep: agent core, classic CLI, TUI (`ui-tui` + `tui_gateway`), gateway platforms (Telegram primary), cron, tools, Python plugins, PM | accepted |
| D7 | `computer_use` today imports `tools.bot_desktop` on every call; either refactor it to the host display or remove that tool too | **open** |
| D8 | Non-Telegram gateway adapters stay untouched in this project | accepted for now (optional later trim) |
| D9 | No compatibility or migration work: the product has no users yet, so frozen updater names, old-install shims, and desktop-update handoffs are deleted outright | accepted |

## Documents

| Document | Contents |
|---|---|
| [01-inventory-and-impact.md](01-inventory-and-impact.md) | What each surface is, measured inventory, what is deleted vs refactored, functional impact, risks |
| [02-removal-plan.md](02-removal-plan.md) | Step-by-step, PR-sized removal sequence with verification gates and done criteria |
| [03-optimization.md](03-optimization.md) | Baseline vs expected end state, what actually gets faster/smaller, what does not |

## Target end state

```
CLI (classic REPL, `hermes chat`)  ─┐
TUI (`hermes --tui`, ui-tui)        ├── agent core ── gateway (Telegram, cron, sessions)
gateway local session API (/api/ws) ┘
```

Surfaces that no longer exist: desktop app, Webapp, dashboard, Bot Mode, GUI installer,
packaged installs (DMG/MSIX/AppImage/Store), desktop plugin SDK, desktop update channels.
