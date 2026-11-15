# Этап 6 — desktop tools/toolsets и session-surface ветки

**Статус:** план, 2026-11-15. Удаление на этом этапе ещё не выполнялось.
**Проект:** `trim-core-surfaces`; детализация [общего плана](02-removal-plan.md#step-6--desktop-toolstoolsets-and-session-surface-branches).
**Проверенная локальная база:** `removal-step-5-desktop-cli@0866ca73f6`;
код этапа 5 заканчивается на `142bddafb3`, сверху — history-снимок.
Локальные `main`/`master` (`b309d5015f`) и `trim-core-surfaces` (`12fc682475`)
отстают от этой базы. Статус удалённых веток и PR здесь не утверждается.
Перед реализацией взять актуальный результат этапа 5 со всеми исправлениями review;
не начинать удаление с исходного дерева `trim-core-surfaces`.

## Цель и границы

Убрать инструменты, которым нужен удалённый renderer, и активные desktop-сессии.
Сохранить CLI, TUI, ACP, messaging gateway, Projects, browser/vault, connectors,
разрешения, профили, cron и Python plugins. Результат — один PR этапа 6 с
последовательными code-коммитами и отдельным завершающим history-коммитом.

Решения D6, D8, D9 из [README](README.md) действуют: никаких migration/shim,
новых core tools, замен desktop-функций или удаления не-Telegram адаптеров.
D7 (`computer_use`) остаётся открытым и относится к этапу 7; этап 6 его не решает.

## Что учтено из этапов 0–5

| Этап | Уже сделано | Ограничение для этапа 6 |
|---|---|---|
| 0 | Зафиксированы inventory, порядок, D1–D9 и метрики | Исходные количества из `01`/`03` — baseline/оценки, а не размер оставшегося удаления |
| 1 | Удалены GUI installer и desktop-стадии; source-протокол и 9 стадий сохранены | Не менять installer/completion и не возвращать desktop-продукт |
| 2 и follow-up/review | Удалены packaging, desktop CI/update/release; сохранены source stable/canary, Docker/Nix/Termux | Не восстанавливать release-совместимость; не повторять уже выполненное удаление build-графа |
| 3 | Удалены `apps/desktop`, Webapp и desktop plugin halves; `apps/shared` и TUI сохранены | Не удалять весь shared-пакет; учитывать его generated contracts и тесты |
| 4 и исправления | Удалены dashboard/`serve`, REST/browser auth; остался loopback `/api/ws` с тикетом из control socket | Сохранять ticket/Host/origin/profile/grant/drain-проверки; readiness не требует HTTP health-route |
| 5 | Удалены desktop CLI/config/update/metrics/old-updater; извлечены общие helpers | Не планировать их повторно; сохранять `projects.repo_scan_*`, `sessions.auto_continue.*`, `argument_mode`, `review_subcommands` |

Фактическая история: [CHANGELOG](../../history/CHANGELOG.md),
[снимок этапа 5](../../history/2026-11-11-removal-step-5-desktop-cli/NOTES.md),
[аудит границы этапа 4](step-4-seam-audit.md). Его deliberate retentions про
`dashboard_procs`/`main_dashboard` и serve-attach уже закрыты этапом 5.
`dashboard_auth` plugin core/providers оставлены этапу 8; stamp/update-inventory
остатки, отмеченные в снимке 5, — этапу 10.

## Уточнения исходного плана по текущему коду

- Discovery сканирует `registry.register()` автоматически. Одного удаления строк из
  `toolsets.py` недостаточно: есть inline dispatch, aliases, callback-параметры,
  отложенный tool search и MCP execution scope.
- `manage_catalog` зарегистрирован в `tools/connectors/tool.py:172`, реализован в
  `tools/connectors/catalog_tool.py` и вызывается inline. Это дополнительная точка
  удаления, отсутствующая в первоначальном списке модулей.
- `desktop_project` из `tools/project_tools.py:164` остаётся: toolset `project`
  используется TUI. Переименование инструмента не входит в этап.
- `tui_gateway/server_requests.py` — общий транспорт clarify/approval/sudo/secret/vault.
  Удаляются только desktop request kinds и их обработчики, не весь файл.
- `gateway/local_desktop_ui.py:132,252` содержит также `connection_callback` и
  маршрутизацию `connection.update`; `ui-tui/src/app/createGatewayEventHandler.ts:1206`
  обрабатывает `connection.request`. Перед удалением модуля сохранить общий путь.
- `tools/browser_vault_tool.py:70,164,725` импортирует preview backend, в том числе
  из общего выбора страницы. Удаление только `browser_vault_preview.py` сломает
  обычный vault; CDP и plugin page backend необходимо сохранить.
- `agent/onboarding.py` совмещает CLI/gateway first-touch hints с импортом desktop
  run record. Нельзя удалять всё `onboarding*` по имени.
- `commands.catalog` — общий RPC и metadata builder; он не равен удаляемому
  toolset `catalog`. Метаданные desktop registry уже удалены на этапе 5.

## Порядок реализации

### 6.1. Зафиксировать рабочую базу и сохраняемые контракты

1. Проверить ancestry этапов 1–5 и чистоту выбранной рабочей копии. Прочитать
   root и area `AGENTS.md`: tools, agent, gateway, tui_gateway, hermes_cli, tests;
   plugins — если затронут общий connector installer.
2. Выполнить `python scripts/check` и целевые проверки ниже на базе; сохранить
   результаты и отдельно воспроизводимые исходные failures. Старые сообщения
   о сбоях Bash/macOS из этапа 4 не считать автоматически актуальными.
3. В одинаковом временном home/config получить discovery и разрешённые tool names
   для CLI/TUI/Telegram, Projects, browser/vault и connectors. Сравнивать множества
   сохранённых возможностей, не фиксированное число всех инструментов.
4. Для каждого удаляемого модуля найти импорты, inline handlers, constructors,
   RPC/contracts, TS consumers, fixtures, startup/package lists и CI paths.
   Составить перечень остаточных ссылок с владельцем этапа 7–11.

**Выход:** проверенная база, результаты проверок и точные границы общего кода;
никаких изменений пользовательского `HERMES_HOME`.

### 6.2. Удалить renderer tools и их регистрацию

Удалить `tools/desktop_ui.py` и модули:

- `preview_tool.py`, `open_preview_tool.py`, `close_preview_tool.py`,
  `read_preview_tool.py`, `drive_preview_tool.py`, `annotate_preview_tool.py`;
- `read_terminal_tool.py`, `close_terminal_tool.py`, `read_window_tool.py`,
  `focus_pane_tool.py`, `react_to_message_tool.py`;
- `tour_tool.py`, его исключительно desktop-потребляемые `tour_presets.py`,
  `tip_tool.py`, `set_theme_tool.py`, `setup_beat_tool.py`;
- `tools/connectors/catalog_tool.py`; регистрацию/импорт `manage_catalog` в
  `tools/connectors/tool.py`. Общие catalog installer helpers удалять только после
  проверки оставшихся вызовов из connectors/RPC — Python plugin/skill install остаётся.

Удалить toolsets `desktop_ui`, `catalog`, `onboarding`;
`CLIENT_SURFACE_TOOLSETS = frozenset({"project"})`. Оставить `project` и
`desktop_project`, исправить их описания под TUI.

Синхронно убрать соответствующие inline executors в `agent/inline_tool_executors.py`,
aliases в `model_tools.py`, списки в `agent/agent_runtime_helpers.py`,
UI lifecycle allowlists, constructor/callback plumbing в `run_agent.py`,
`agent/agent_init.py`, `agent/agent_init_params.py` и все найденные callers.
Пройти `tools/tool_search.py`, `tools/mcp_tool_agent.py`, execute-code/tool-call
маршруты: удалённый инструмент не должен возвращаться через deferred discovery.
Общий scope/denylist и правила prompt caching сохраняются.

**Выход:** все 13 renderer tool names (`desktop_ui` 11 + `setup_beat` +
`manage_catalog`) отсутствуют в registry/schema/inline dispatch; discovery работает.
Старые helpers/aliases `open_preview`, `close_preview`, `read_preview` тоже убраны.

### 6.3. Сузить desktop bridges, сохранить общий TUI transport

1. В `gateway/local_viewer_events.py` сохранить общие event/callback bindings,
   restore при завершении turn и connector request/update route. По возможности
   перенести небольшой живой фрагмент туда; отдельный sibling нужен только если
   иначе нарушаются size/complexity limits. Затем удалить `gateway/local_desktop_ui.py`.
2. В `tui_gateway/agent_callbacks.py`, `server.py`, `session_notifications.py`
   убрать preview/terminal-pane/window/tour/theme/setup callbacks и probe ladders,
   `theme_bridge.py`, desktop emitter wiring.
3. Для `_wire_desktop_sinks`, `process_registry.on_output/on_close` отделить
   renderer tabs от реальных фоновых процессов. Удалить события вкладок без TUI
   consumers; сохранить process management, completion/watch/heartbeat,
   interrupt/cleanup и notification poller. `reaction_callback` общей TUI-реакции
   не равен удаляемому инструменту `react_to_message`.
4. В `server_requests.py` и `gateway/session_server_requests.py` оставить общий
   request/response, cancellation, replay, locked clarify answers, transport ownership.
   Убрать исключительно desktop kinds: `preview.read`, `preview.act`,
   `terminal.read`, `window.read`, `tour`, `theme.apply`, `theme.pick`, `setup_beat`.
   Общий `server_requests` capability и механизмы отказа чужому responder сохраняются.
5. Проверить HUD/voice-live surface notes и их producers (`gateway/session_surface.py`,
   `tui_gateway/methods_voice.py`, `agent/prompt_builder.py`): убрать ветки удалённого
   клиента, сохранив используемые TUI voice/STT/TTS и общий capabilities RPC.

**Выход:** TUI по-прежнему отвечает на human-input requests, reconnect восстанавливает
ожидающий prompt, connector operations завершаются в своём профиле/сеансе.

### 6.4. Удалить preview-vault и desktop first-run onboarding

**Vault:** удалить `tools/browser_vault_preview.py`, `vault.preview.fill` из
`tui_gateway/methods_vault.py`, schema/inline auto-targeting и preview callback.
Общий page resolver использует plugin page backend или CDP, как до удаления preview.
Устаревший явный `target="preview"` должен отклоняться до обращения к странице;
нельзя молча заполнить секретом другой браузер. Сохранить origin/nonce checks,
redaction, secure evaluation и profile isolation. Общие `vault.*` RPC остаются.

**Onboarding:** удалить `tui_gateway/methods_onboarding.py`,
`gateway/session_onboarding.py`, desktop `agent/onboarding_{flow,text,facts,record,first_tasks,session}.py`
после удаления их callers. Снять `onboarding.*` desktop RPC, toolset fold-in,
scripted opening/per-turn notes, observe/delete/reset hooks из turn runner,
session lifecycle и methods_tools. Generic scripted-prelude механизм удалять
только при отсутствии других реальных callers.

`hermes_cli/onboarding_run.py` и `onboarding_due.py` обслуживают GUI-run:
проверить зависимости `free_tier_bootstrap`, затем удалить этот путь и его
invalidation/boot wiring. Из конфига убрать только desktop `onboarding.run` и
другие доказанно GUI-only настройки. Сохранить CLI/setup, welcome/free-tier
авторизацию и first-touch `onboarding.profile_build`/`onboarding.seen` с их
живыми consumers; в `agent/onboarding.py` удалить desktop import/re-export.
Не удалять записанные пользовательские чаты и не мигрировать БД ради этого этапа.

**Выход:** fresh TUI/CLI не открывает GUI onboarding, обычные onboarding hints и
vault работают без импорта удалённых модулей.

### 6.5. Убрать активные desktop session policies и обновить wire

- `gateway/session_policy.py`: удалить создание/запуск `gui → desktop`,
  `LOCAL_DESKTOP_CHAT`, desktop toolset exceptions и `local_desktop_turn`.
  В `gateway/run_turn.py` оставить полный owning-profile runtime scope.
- `gateway/session_local.py`, `session_controls.py`, `tui_gateway/ws.py`,
  `methods_voice.py` и contracts: убрать `desktop_local` producers, capability,
  transport state и аргументы. Сохранить `client_local`, native-ticket identity,
  owner-only права и актуальную семантику `serving_local_host` из этапа 5.
- `tui_gateway/agent_factory.py`: default platform — `tui`, без
  `HERMES_DESKTOP`/`HERMES_DESKTOP_TERMINAL`; сохранённый explicit source для
  разрешённых plugin/gateway callers не переписывать в TUI. Projects fold-in и
  enable/disable selection должны сохранить прежнее TUI-поведение.
- `agent/prompt_builder.py`/`system_prompt.py`: убрать desktop platform/HUD copy
  и обещания GUI tools. Не перестраивать prompt/toolset в середине беседы.
- `gateway/hosted_room_peer.py:272`: убрать desktop-env поправку к
  `persistent_process`; сохранить signed catalog, execution policy, target profile
  и работающий gateway/api_server/peer path. Bot Mode удаляется на этапе 7.
- Исторические `source="desktop"/"gui"` остаются читаемыми как данные;
  чтение transcript не должно запускать desktop agent или выдавать GUI capabilities.
  Новые desktop sources отклоняются существующим validation path. При необходимости
  чтение старого формата отделить от принятия нового launch request, без shim/миграции.
- Удалить мёртвые модели/registrations в `tui_gateway/contracts/` вместе с
  methods/events/server requests; пройти canonical и fallback catalog отдельно.
  Перегенерировать `apps/shared/src/gateway-contract.generated.ts` и
  `gateway-contract.openrpc.json`; поправить shared/TUI consumers и тестовые frames.
  `commands.catalog`, `argument_mode`, `review_subcommands`, Projects RPC остаются.

**Выход:** CLI/TUI/ACP/messaging sources сохраняют возможности и изоляцию;
desktop capability нельзя получить через env, create/resume или fallback RPC.

### 6.6. Закрыть тесты, ссылки, проверки и history

Удалить тесты исключительно удалённых tools, preview-vault и GUI onboarding.
Смешанные тесты `test_gui_surface_toolsets`, session platform/policy, reactions,
server requests, connectors и Projects сузить до сохранённых контрактов.
Обновить prompt-surface fixtures, RPC frames, TS channel tests, которые используют
`preview.read` как пример, на сохраняемый request с корректной wire-схемой.
Не оставлять сломанные импорты до общего тестового cleanup этапа 10.

В том же PR убрать пути удалённых модулей из startup/package lists,
CI classifiers и lint baselines, если они там есть; заново сгенерировать
затронутые артефакты. Исправить прямые ссылки и правила о переносимых символах
в `AGENTS.md`, developer docs и skills. Полное переписывание сайта/локалей — этап 9;
dependency/lockfile pruning — этап 11, если сам этап 6 их не меняет.

## Проверки при реализации

Все команды — из актуального worktree этапа 6, через PM test interpreter;
`HERMES_HOME` и `HERMES_RUNTIME_DIR` — отдельные временные каталоги.
Ниже перечислены будущие проверки, а не результаты текущего планирования.

```bash
python scripts/check
python scripts/gen_gateway_contracts.py --check
python scripts/gen_gateway_command_parity.py --check
scripts/run_tests.sh tests/tools/ tests/agent/ tests/tui_gateway/ tests/gateway/ -q -j 4 --file-retries 0
pnpm --dir ui-tui run typecheck
pnpm --dir ui-tui test
node .github/scripts/run-workspace-checks.mjs --concurrency 1
```

Для быстрой обратной связи до полного целевого прогона использовать существующие
`test_toolsets`, `test_project_tools`, `test_tool_search*`, `test_browser_vault*`,
`test_session_policy*`, `test_runtime_api`, `test_session_listener_native_ws`,
`test_human_input_hooks_tui`, `test_server_requests`, `test_local_viewer_*`,
`test_canonical_wire_contract*`, `test_multiplex_toolsets_profile_isolation` и
`test_connector_account_surface`. Реальные имена/пакеты брать из выбранной базы;
удалённые GUI-only тесты не включать. Затронутые CLI/config/CI тесты добавить по diff.

Достаточно расширить существующие поведенческие проверки; новые нужны там,
где остаётся непокрытая граница:

| Контракт | Что доказать |
|---|---|
| Discovery/dispatch | Удалённые tools отсутствуют и недоступны через tool search/inline/MCP; оставшиеся toolsets разрешаются |
| TUI и Projects | `project`/`desktop_project`, disabled selection, source resolution и callbacks работают без desktop env |
| Human input и connectors | Clarify/approval/cancel/reconnect и connection request/update/response не теряются, чужой session/profile не отвечает |
| Vault | CDP/plugin backend сохраняет secret/origin guard; preview target не вызывает операции ни в одном браузере |
| Session authority | `/api/ws` ticket attach, profile/grant isolation и чтение старой истории работают; новые gui sources отвергаются |
| Onboarding | Fresh CLI/TUI не импортирует GUI-run, обычные first-touch hints и setup сохраняются |

Регрессии в сохраняемом поведении воспроизводить на базе; удаление поверхности
проверять реальным discovery/dispatch/RPC, без source-reading/change-detector tests.

Ручной smoke: `hermes --help`, `hermes tools list`, gateway + CLI/TUI attach,
обычный tool call, Projects, clarify/approval с переподключением, background
process completion и connector status. Модельный endpoint/токен использовать
только при наличии настроенной тестовой среды; отдельно указать непроверенные
live Telegram/model/browser случаи.

В PR сохранить короткий остаточный аудит: поиск имён удалённых modules/tools,
`HERMES_DESKTOP`, `desktop_local`, `source='gui'` с классификацией каждого
совпадения (историческое чтение, этап 7/8/9/10/11, ошибка этапа 6).
Глобальное требование «слово desktop нигде не встречается» здесь неверно:
`desktop_project`, Bot Desktop и desktop plugin API ещё законны.

## Условие завершения и следующий этап

Этап завершён, когда renderer tools/RPC/producers удалены без dangling imports,
сохранённые CLI/TUI/gateway проверки проходят, контракты перегенерированы и
остатки имеют явного владельца. В PR записать реальные результаты и ограничения,
замерить удалённые files/lines и tool schemas; не обещать ускорения LLM-turn или
уменьшения CLI/TUI tool payload — это оговорено в [03](03-optimization.md).

После code-коммитов создать append-only
`history/YYYY-MM-DD-removal-step-6-tools-sessions/` из снимка этапа 5 и добавить
верхнюю строку `history/CHANGELOG.md`. Изменять diagram только при фактическом
изменении изображённых компонентов/связей; иначе копия + объяснение в NOTES.
В NOTES — точный code HEAD, факты с paths/lines, SHA-256, проверки и ограничения.
Обязательная Archify-приёмка по [history/README](../../history/README.md):
validate/deliver `--quality showcase`, 9/9, 0 errors/warnings, visual-check на
четырёх размерах. Отдельный коммит `docs(history): snapshot <slug>` в ветке этапа.
Во время составления этого плана снимок выполненного этапа не создаётся.

Далее — этап 7: решение D7 и Bot Mode. `tools/bot_desktop/**`, `bot_relay`,
`methods_bot_relay`, `computer_use`, bot-room/peer возможности не удаляются здесь.
Python plugin system, `dashboard_auth` providers и desktop plugin contract — этап 8.
