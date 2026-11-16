# Снимок 2026-11-15 — удаление desktop-инструментов и desktop-сессий

- **Дата:** 2026-11-15
- **Репозиторий:** `Zafir-Development/zafir-agent` (Hermes Agent)
- **Тип диаграммы:** `architecture` (Archify, `quality_profile: showcase`)
- **Язык:** русский; UI вьюера — английский (см. «Известные упрощения»)
- **База `main`:** `b309d5015fc156815f1ae8074db5688f7dee1c24`
- **База ветки этапа (`removal-step-6-tools-sessions`):** `45bcfd5b3e` — merge PR #7
  (`removal-step-5-desktop-cli`); дерево включает этапы 1–5 со всеми review-исправлениями
- **HEAD code-коммитов этапа:** `d04aefaaf2`
- **Документ-план этапа:** `docs/removal/step-6-removal-plan.md` (и § Step 6 в
  `docs/removal/02-removal-plan.md`)
- **Предыдущий снимок:** `../2026-11-11-removal-step-5-desktop-cli/` — не изменялся
  (append-only).

## Что изменилось

Этап 6 плана `docs/removal`: удалены инструменты, которым нужен удалённый renderer, и
активные desktop-сессии, при сохранении CLI, TUI, ACP, messaging gateway, Projects,
browser/vault, connectors, approvals/clarify/sudo/secret, профилей, cron, Python plugins и
source install/update. Рантайм остался тем же, что после этапа 5: CLI + TUI + messaging
gateway с единственным loopback-listener'ом `/api/ws` (одноразовый тикет из control socket).

Удалено:

- **13 renderer-инструментов и 18 их модулей** (включая `tour_presets.py`, удалённый вместе со своим последним контрактным потребителем): 11 инструментов toolset'а `desktop_ui`
  (`read_terminal`, `close_terminal`, `desktop_preview`, `drive_preview`, `annotate_preview`,
  `read_window_below`, `focus_pane`, `react_to_message`, `gui_tour`, `show_tip`, `set_theme`),
  `setup_beat` (toolset `onboarding`) и `manage_catalog` (toolset `catalog`); модули
  `tools/desktop_ui.py`, шесть preview-модулей, `read_terminal/close_terminal/read_window/
  focus_pane/react_to_message`, `tour_tool/tour_presets/tip_tool/set_theme_tool/setup_beat_tool`,
  `tools/connectors/catalog_tool.py`. Toolsets `desktop_ui`, `catalog`, `onboarding` удалены;
  `CLIENT_SURFACE_TOOLSETS = frozenset({"project"})`; `project`/`desktop_project` оставлены для
  TUI Projects (переименование — не этап 6).
- **Agent-plumbing:** inline executors, legacy-алиасы (`tour`/`tip`, `open_preview`/
  `close_preview`/`read_preview`), динамические schema-rewriter'ы для удалённых инструментов,
  7 callback-параметров конструктора `AIAgent`/`init_agent`, lifecycle/parallel/post-hook
  allowlists, `tools.tool_search.defer` entries, renderer process sinks
  (`process_registry.on_output/on_close`, `request_close_terminal`).
- **Desktop-бриджи:** `gateway/local_desktop_ui.py` (живой общий фрагмент — connector card
  `connection.request`/`connection.update` и restore на завершении turn — перенесён в
  `gateway/local_viewer_events.py`), `tui_gateway/theme_bridge.py`, preview/terminal/window/
  tour/theme/setup callback'и и их probe-лестницы, renderer-tab события, 8 desktop-only
  server-request kinds (`preview.read`, `preview.act`, `terminal.read`, `window.read`, `tour`,
  `theme.apply`, `theme.pick`, `setup_beat`). Общий транспорт (request/response, cancel, replay,
  locked clarify answers, pinned transport ownership, foreign-responder refusal, capability)
  сохранён.
- **Preview-vault:** `tools/browser_vault_preview.py` и RPC `vault.preview.fill`; общий page
  resolver вернулся к pre-preview выбору (CDP-supervisor или plugin page backend). Устаревший
  явный `target="preview"` отклоняется до любого обращения к странице/секрету; origin/nonce,
  redaction, secure evaluation и остальные 7 `vault.*` RPC сохранены.
- **GUI first-run onboarding:** 11 модулей (`agent/onboarding_{flow,text,facts,record,
  first_tasks,session}.py`, `agent/turn_scripted_prelude.py`, `gateway/session_onboarding.py`,
  `tui_gateway/methods_onboarding.py`, `hermes_cli/onboarding_{run,due}.py`), их RPC/секции
  контрактов, toolset fold-in, scripted opening/per-turn notes, observe/delete/reset hooks,
  `onboarding.run` в конфиге и GUI-run инвалидация/free-tier boot wiring. Сохранены CLI/setup,
  first-touch hints (`onboarding.profile_build`/`onboarding.seen`), welcome/free-tier авторизация,
  setup record и исторические model-config/`ONBOARDING_DONE` данные (без миграции).
- **Активные desktop-сессии:** `gui` убран из `SURFACES` (новый `session.create` с `gui`
  отклоняется существующей validation path; исторические строки/транскрипты читаемы, а
  adopted/resumed turn выполняется на выжившей локальной поверхности `tui`);
  `LOCAL_DESKTOP_CHAT`, `local_desktop_turn`, `desktop_local` (producer/capability/transport/
  create-mark), client-declared local-host флаг; `serving_local_host` теперь выводится из
  native-ticket identity. `tui_gateway/agent_factory.py` по умолчанию `tui` без
  `HERMES_DESKTOP*`; desktop platform/HUD copy и обещания GUI-инструментов удалены из prompt'ов;
  hosted-room catalog больше не поправляет `persistent_process` по `HERMES_DESKTOP`.
- **Wire/контракты:** удалены `preview.restart`, HUD-поверхность, `display.in_app_tips/tours`,
  мёртвые desktop events, `onboarding.*`, `vault.preview.fill`, `desktop_local` capability,
  `gui` в canonical create enum; перегенерированы `apps/shared/src/gateway-contract.generated.ts`
  и `gateway-contract.openrpc.json`. `commands.catalog`, `argument_mode`, `review_subcommands`,
  Projects/`desktop_project` и connector RPC сохранены.
- **Тесты/ссылки:** удалены тесты исключительно удалённых поверхностей (renderer tools,
  preview-vault, GUI onboarding), смешанные сужены до выживших контрактов, добавлены
  поведенческие проверки discovery/dispatch, session authority, vault guard и TUI Projects;
  обновлены prompt-surface fixtures (матрица `desktop.claude` → `tui.claude`) и TS channel
  тесты; вычищены evals/AGENTS/developer docs/CI-baselines, регенерированы lint-baselines.

Оставлено без изменения поведения:

- agent core, классический CLI, TUI/Projects, ACP, messaging gateway и все его адаптеры,
  browser/vault (CDP + plugin page backend), connectors, approvals/clarify/sudo/secret,
  профили и изоляция, cron/фоновые процессы, Python plugins, PM и source install/update.
- Историческая wire-лексика как данные: `source="desktop"/"gui"`-строки, legacy-списки
  источников, `desktop_protocol`/`desktop_contract` поля TUI, observability RETIRED
  tool/toolset-имена и v3/v4 enum'ы (D9: старые строки валидны).
- Bot Mode / `tools/bot_desktop/**` / `bot_relay` / `computer_use` / bot-room — этап 7;
  Python plugin system, `dashboard_auth` и desktop plugin contract — этап 8.

## Почему схема рантайма не изменилась

Компонент Desktop удалён из диаграммы ещё на этапе 3, а этап 4 переписал runtime-схему
(CLI + TUI + gateway, один loopback-listener `/api/ws`). Этап 6 удаляет каталог
renderer-инструментов, desktop-бриджи, GUI onboarding и desktop-сессии, но не добавляет и не
убирает ни одного изображённого компонента, процесса или сетевой связи: узлы CLI/TUI/gateway/
agent/tools/state/провайдеры и их связи остаются теми же. Узел «Инструменты» по-прежнему
означает реестр инструментов; его агрегатная подпись («70+ tools · 28 toolsets») —
иллюстративная, как и в предыдущих снимках, и по правилу `history/README.md` не менялась,
потому что изображённые компоненты/связи не менялись. Измеренные факты этапа: реестр
`registry` 68 → 55 имён (−13), `TOOLSETS` 57 → 54 (−3), toolset-набор сессии 18/20 → 18 на
всех поверхностях. Поэтому `diagram.json` и `diagram.html` скопированы из
`../2026-11-11-removal-step-5-desktop-cli/` без изменений; контрольные суммы совпадают с
предыдущим снимком:

- `sha256(diagram.json)` = `d3e0f87c1975ae80d28767cdc3f69005014efcd54034912c1690d52e481c46ec`
- `sha256(diagram.html)` = `0c3c8078d1ba639be799c23c685d97dd65c0da670590f19559277146ba14e9e9`

Файл `diagram.json` не содержит ни одного вхождения `desktop` (`grep -ci desktop` = 0);
узлы и связи по-прежнему соответствуют коду.

## Факты, проверенные по коду (ветка `removal-step-6-tools-sessions`)

### Renderer tools/toolsets

- `toolsets.py:67` — `CLIENT_SURFACE_TOOLSETS = frozenset({"project"})`; `toolsets.py:70` —
  `TOOLSETS` (54 ключа), среди них нет `desktop_ui`/`catalog`/`onboarding`.
- `toolsets.py:129` — `"project": _ts("Projects — create/switch named workspaces (client
  sessions: TUI)", ["desktop_project"])`.
- `tools/connectors/tool.py` — регистрация `manage_connections` сохранена, `manage_catalog`
  удалён; generic helper'ы (`tools/connectors/catalog.py`, `run.py`) сохранены для
  `connection.respond`/reissue пути.
- `tools/project_tools.py` — `desktop_project` сохранён (TUI Projects), обновлены docstring/
  schema-описания.
- `tools/process_registry.py` — нет `on_output/on_close` и `request_close_terminal`; output
  log/watch/heartbeat/kill пути не менялись.
- Discovery (одинаковое временное окружение, PM env): `registry` raw names 68 → 55; ни одного
  из 13 удалённых имён нет в registry/`get_tool_definitions()`/inline table/legacy alias/
  dynamic rewriter/deferred-tool-search; `hermes-cli`/`hermes-telegram`/`hermes-gateway`/
  `hermes-acp`/`coding`/`project`/`browser`/`connections`/`debugging`/`safe` резолвятся.
  Модельно-видимый список остаётся 20 (deferred assembly) — выигрыша в payload нет, см.
  `docs/removal/03-optimization.md`.

### Bridges / TUI transport

- `gateway/local_viewer_events.py:42` — `_install_connection_hook()`, `:38-39` — маршруты
  `connection.update` по session-key+profile c fallthrough в sidecar-hook; `:28` — в
  `_TURN_ATTRS` входит `connection_callback`; `:69` — `wire()`, `:91` — установка hook'а.
  `gateway/local_desktop_ui.py` удалён.
- `tui_gateway/server.py` — нет регистрации `methods_onboarding`; `tui_gateway/methods_onboarding.py`
  удалён.
- `tui_gateway/contracts/server_requests.py` — зарегистрированы только approval, clarify,
  display.install.sudo, secret, sudo, vault.code, vault.save_login, vault.unlock_prompt;
  desktop kinds отсутствуют. `tui_gateway/server_requests.py` сохраняет
  cancellation/replay/locked answer/pinned ownership/foreign-responder refusal.
- `tui_gateway/session_notifications.py`, `tui_gateway/agent_callbacks.py` — renderer-tab sinks
  и desktop callback'и удалены; process management, completion/watch/heartbeat, interrupt/
  cleanup и notification poller сохранены; TUI `reaction_callback` сохранён.

### Vault

- `tools/browser_vault_preview.py` удалён; `tools/browser_vault_tool.py:65` — `_page_backend`
  использует `agent.browser_page_registry.backend_for_task` (CDP/plugin page), как до preview;
  `:682` `_handle_vault`, `:691` — `invalid_target` guard для любого `target != "browser"` до
  разрешения страницы/секрета.
- `tui_gateway/methods_vault.py:42,60,78,102,124,135,168` — сохранены 7 scoped RPC
  (`vault.list/sources/source.set/unlock/lock/add/remove`), `vault.preview.fill` отсутствует;
  `_LONG_HANDLERS = {"vault.list"}`. Origin/nonce/redaction/profile isolation не менялись.

### Onboarding

- `agent/onboarding.py:113,140,170,196,202` — first-touch API сохранён
  (`profile_build_mode`, `first_contact_turn_note`, `profile_build_directive`, `is_seen`,
  `mark_seen`); desktop import/re-export удалён.
- `hermes_cli/config_defaults.py:2313` — секция `onboarding` содержит только `seen`/
  `profile_build`; `onboarding.run` удалён.
- Fresh CLI+TUI import probe: в `sys.modules` нет `onboarding_flow/session/facts/record/text/
  first_tasks`, `methods_onboarding`, `session_onboarding`, `onboarding_run`, `onboarding_due`,
  `turn_scripted_prelude`.
- `hermes_cli/free_tier_bootstrap.py` — сохранены setup record, reconcile/broadcast,
  settle_interrupted_claim, gateway-boot path; удалены desktop-boot hook, resettle и
  onboarding_due инвалидация. `hermes_cli/install_state.py` — `ONBOARDING_DONE` остаётся
  historical-read.

### Sessions / wire

- `gateway/session_policy.py:81` — `SURFACES = {'cli','tui','acp','tool','oneshot'}`;
  `:96` — `_LEGACY_CREATED_SURFACES = {'gui': 'desktop', 'desktop': 'desktop'}` (historical
  read), `:117-123` — picker-алиасы; `:690-691` — явный отказ `desktop_ui`.
- `tui_gateway/agent_factory.py:29-32` — `_resolve_session_platform()` → `"tui"` без
  `HERMES_DESKTOP*`; `:323-327` — `_client_surface_toolsets()` = `CLIENT_SURFACE_TOOLSETS`.
- `hermes_state_local_migration.py:64-71` — `legacy_creation_source`: stored label остаётся
  данными, adopted/resumed turn идёт как `tui` (без shim/миграции).
- `tui_gateway/contracts/canonical_sessions.py:34` — create `source: Literal['cli','tui','acp',
  'tool','oneshot']` (без `gui`).
- `gateway/session_hosted_rpc.py:99` — seed `build_policy({'source': 'tui'}, ...)` затем
  `replace(..., source='bot_room', platform='bot_room')`.
- `tui_gateway/methods_connectors.py:298,306` — `_connector_page_vars()` для sessionless
  connector RPC связывает `source="tui"` (последний live desktop-source producer удалён);
  desktop-only `return_to_args` producer удалён из `tools/connectors/gateway/{client,bridge}.py`
  и `tools/connectors/managed.py` (wire оставляет optional `returnTo`).
- `gateway/run_turn.py` — сохранён полный owning-profile runtime scope; `gateway/hosted_room_peer.py`
  — signed catalog/execution policy/target profile/peer path без desktop-env поправки.
- Регенерация: `scripts/gen_gateway_contracts.py --check` = 0, `scripts/gen_gateway_command_parity.py
  --check` = 0; `tui_gateway.server` — 249 handlers == 249 declared methods, 8 server requests,
  68 events; `preview.restart`/`onboarding.*`/`vault.preview.fill` отсутствуют и в контракте,
  и в handler-таблицах.

### Тесты / ссылки

- Удалены все тесты исключительно удалённых поверхностей; смешанные сужены. Новые/расширенные
  поведенческие проверки: отсутствие 13 имён в discovery/tool search/inline/MCP при
  резолвящихся выживших toolsets; TUI Projects/`desktop_project` и disabled selection без
  desktop env; clarify/approval/cancel/reconnect и connector request/update/response;
  vault target=`preview` без операций в браузере; `/api/ws` ticket attach/profile-grant
  isolation/чтение старой истории/отказ новым `gui` source; fresh CLI/TUI без импорта GUI-run.
- Prompt-surface fixtures перегенерированы: матрица `desktop.claude` заменена на `tui.claude`,
  удалены `react_to_message.json`/`tool_search.desktop.claude.json`, `manage_connections.json`
  и `surfaces.json` обновлены; генератор сделан host-переносимым (sysconfig freeze до OS-pin,
  psutil pre-import, scrub обоих написаний `/var` и `/private/var`), поэтому рендер на macOS
  совпадает с Linux-раннером.
- evals: удалён removed-surface harness `evals/core_tool_deferral/**`, его host sandbox вынесен
  в нейтральный `evals/host_sandbox.py` (без shim); обновлены AGENTS.md/tui_gateway AGENTS,
  developer/reference docs, `optional-skills/productivity/live-dashboard`, lint-baselines.

## Приёмка Archify

- `validate architecture diagram.json --quality showcase --json` — `ok: true`, 9/9 проверок,
  `composition.status = pass`, 0 errors, 0 warnings.
- `deliver architecture diagram.json diagram.html --quality showcase --json` — `ok: true`;
  specification SHA-256 `d3e0f87c1975ae80d28767cdc3f69005014efcd54034912c1690d52e481c46ec`
  (7 697 bytes), artifact SHA-256 `0c3c8078d1ba639be799c23c685d97dd65c0da670590f19559277146ba14e9e9`
  (820 075 bytes).
- `visual-check diagram.html --json` — `status: pass` на 1440×900, 1600×1000, 1920×1080,
  2048×1320 (containment/readability/legend/dock без пересечений; browser evidence
  `automated-browser`). Перцептивная проверка человеком не проводилась (`visualReview: pending`);
  артефакт побайтно совпадает с принятым снимком этапа 5.

## Проверки (результаты)

Все команды — из актуального worktree этапа, PM test interpreter; `HERMES_HOME` тесты
изолируют сами (conftest), пользовательский `~/.hermes` не изменялся.

| Проверка | Результат |
|---|---|
| `python scripts/check` (HEAD `d04aefaaf2`) | **PASS**: `14 checks, ok` — footguns, shebangs, no-tmp, detached-spawns, install-root, config-writers, config-readers, os-marker-fakes, agents-md, case-collisions, profile-archives, blob-size, ruff, health. Health: 730 файлов vs `b309d5015f` — 0 blocking, 0 advisory; остаётся только reviewed allow-comment `tui_gateway/ws.py:67 BLE001` |
| `python scripts/gen_gateway_contracts.py --check` | exit 0 (clean) |
| `python scripts/gen_gateway_command_parity.py --check` | exit 0 (clean) |
| `scripts/run_tests.sh tests/tools/ tests/agent/ tests/tui_gateway/ tests/gateway/ -q -j 4 --file-retries 0` | 4111 файлов, **39 845 passed**, 1 failed, 1 collection error, 781 skipped (94.7 min). Оба «красных» — pre-existing классы: `tests/tools/test_local_interrupt_cleanup.py` (load-sensitive timing; на этом же дереве в изоляции 4 passed) и `tests/agent/test_vault_key_storage.py` (collection error: нет optional `keyring`; падал и на базе) |
| `pnpm --dir ui-tui run typecheck` | clean |
| `pnpm --dir ui-tui test` | 1 954 passed / 1 failed / 28 skipped; единственный fail — pre-existing timing-класс `hermes-ink/.../execFileNoThrow.test.ts` (hermes-ink не менялся); с реальным (не symlink) TMPDIR дополнительные 3 macOS-класса проходят |
| `node .github/scripts/run-workspace-checks.mjs --concurrency 1` | apps/shared PASS, hermes-ink PASS; ui-tui и tests-js падают только на pre-existing macOS/env-классах (не связаны с этапом 6) |
| Целевые прогоны этапа | `tests/tools/ + tests/tui_gateway/` = 13 995 passed / 0 failed; retarget-батчи gateway/agent = green; `tests/ci/test_prompt_surface.py` 2 passed; `tests/tui_gateway/contracts/test_generated.py` 2 passed |
| Archify validate / deliver / visual-check | см. «Приёмка Archify» |
| Исходный baseline: тот же 4-suite на `45bcfd5b3e` (pristine worktree) | **12 красных файлов** (EXIT 1): 2 collection error (`test_vault_key_storage.py` — нет optional `keyring`; `test_fal_sdk.py` — нет `fal_client`) и 10 файлов: `test_compaction_prompt_rebuild`, `test_shell_hooks_tree_kill`, `test_estop_interactive_turns`, `test_readiness`, `test_session_client_env`, `test_bot_desktop_resources`, `test_delegate`, `test_terminal_pipeline_status`, `test_transcription_tools`, `test_tui_gateway_server`. Все 12 — pre-existing env/macOS/load-классы; на финальном дереве из них остаются только `test_vault_key_storage` (optional extra) и load-sensitive `test_local_interrupt_cleanup` (в изоляции зелёный), остальные закрыты host-robustness-правками тестов (см. ниже). |

Host-robustness-правки pre-existing тестов (не поведение продукта, раскрыты явно):
`test_compaction_prompt_rebuild` резолвит scratch-TMPDIR, `test_readiness` выводит overall-статус из
disk-пробы, `test_terminal_pipeline_status` закреплён за Linux (bash 3.2), `test_transcription_tools`
не выбирает macOS-принудительный CPU/int8, `test_bot_desktop_resources` закреплён за Linux (host-gate),
`test_fal_sdk` использует importorskip для optional extra, `test_delegate` сравнивает realpath,
`test_session_client_env` закреплён за `not macos` (launchd-ветка), `test_shell_hooks_tree_kill`/
`test_local_interrupt_cleanup` — load-sensitive process-timing (зелёные в изоляции/серийно).

Ручной smoke: `hermes --help` и `hermes tools list` под PM env — exit 0, desktop/gui-команд нет;
`tui_gateway.server` import — 249 handlers == 249 declared methods; fresh CLI/TUI import не
загружает GUI-run модули. Live Telegram/model/browser-сценарии не прогонялись (см. «Известные
упрощения»).

## Метрики

Замеры теми же командами, что в `docs/removal/03-optimization.md` § Measurement, на базовом
коммите `45bcfd5b3e` и на дереве после code-коммитов этапа 6 (HEAD `d04aefaaf2`, до
history-снимка и отдельного коммита CHANGELOG):

| Метрика | Было (base) | Стало | Δ |
|---|---:|---:|---:|
| tracked-файлы (`git ls-files`) | 17 036 | 16 954 | −82 |
| tracked-строки | 3 682 309 | 3 667 504 | −14 805 |
| Python-файлы | 10 233 | 10 154 | −79 |
| Python non-test строки | 1 002 714 | 995 857 | −6 857 |
| Python test строки | 1 496 530 | 1 490 898 | −5 632 |
| tracked-байты | 189 634 042 | 188 985 918 | −648 124 |

Диффа `45bcfd5b3e..d04aefaaf2`: 322 paths, +1 453/−16 259; 86 удалённых файлов (46 тестов,
40 не-тестов), 4 добавленных (план этапа, два новых test-файла, `tool_search.tui.claude.json`),
229 изменённых; `evals/core_tool_deferral/sandbox.py` перенесён в `evals/host_sandbox.py`
(rename, без shim). Удалено 13 tool schemas: registry raw names 68 → 55, `TOOLSETS` 57 → 54,
per-session toolset list 18 (cli/tui/gateway) / 20 (desktop) → 18 на всех поверхностях,
desktop raw tools 33 → 23; модельно-видимый список CLI/TUI 20 → 20 (deferred assembly), поэтому
выигрыш в payload не заявляется.

Снимок добавляет `diagram.json`, `diagram.html`, `screenshot-light-2048x1320.png`, `NOTES.md`
и верхнюю строку `history/CHANGELOG.md` (append-only; прошлые снимки не изменяются).

## Известные упрощения / ограничения

- Live Telegram/model/browser-сценарии не прогонялись (нет настроенного тестового
  endpoint/аккаунтов в этой среде); соответствующие тесты либо замоканы, либо пропущены.
- macOS-специфичные pre-existing классы (bash 3.2, `/var` vs `/private/var`, отсутствующий
  optional extra, заполненный диск) остаются и не относятся к этапу 6; они перечислены в
  разделе проверок вместе с исходными значениями.
- D9: пользователей нет, поэтому старые desktop-значения конфига/строк просто читаются как
  исторические данные, без миграции и shim; adopted desktop-история резюмируется на `tui`.
- Не заявляется ускорение LLM-turn или уменьшение CLI/TUI tool payload: `desktop_ui`/
  `catalog`/`onboarding` сворачивались только для desktop-сессий, а модельно-видимый список
  CLI/TUI остаётся 20 (deferred assembly); см. `docs/removal/03-optimization.md`.
- Границы следующих этапов: `tools/bot_desktop/**`, `bot_relay`, `methods_bot_relay`,
  `computer_use`, bot-room/peer — этап 7 (D7 открыт); Python plugin system, `dashboard_auth`
  providers и desktop plugin contract — этап 8; локали/полный сайт — этап 9;
  stamp/update-inventory/telemetry-словарь — этап 10; dependency/lockfile pruning — этап 11.
- UI вьюера Archify — английский (встроенный), как в предыдущих снимках.
