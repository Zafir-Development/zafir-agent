# Снимок 2026-11-10 — удаление web-дашборда, `hermes dashboard` и `hermes serve`

- **Дата:** 2026-11-10
- **Репозиторий:** `Zafir-Development/zafir-agent` (Hermes Agent)
- **Тип диаграммы:** `architecture` (Archify, `quality_profile: showcase`)
- **Язык:** русский; UI вьюера — английский (см. «Известные упрощения»)
- **База `main`:** `b309d5015fc156815f1ae8074db5688f7dee1c24`
- **База ветки `removal-step-4-dashboard` (родитель этапа):** `08229474ac` (merge PR #5, этапы 0–3)
- **HEAD на момент снятия снимка:** `0cd916f478` (`docs(removal): audit the dashboard/serve seam`);
  правки этапа 4 лежат в рабочем дереве ветки, коммит этапа делает Lead
- **Документ-аудит этапа:** `docs/removal/step-4-seam-audit.md`
- **Предыдущий снимок:** `../2026-11-09-removal-step-3-desktop/` — не изменялся (append-only).

## Что изменилось

Этап 4 плана `docs/removal/02-removal-plan.md`: удалены браузерный дашборд (`web/` SPA),
команды `hermes dashboard` и `hermes serve` и весь dashboard/`serve` FastAPI-апп. Рантайм
Hermes теперь — CLI + TUI + messaging gateway. Остался единственный локальный HTTP/WS-listener,
и он отвечает ровно на один маршрут — нативный сессионный `/api/ws` с одноразовым тикетом,
через который `hermes chat`, `hermes --tui` и `hermes gateway attach` (а также ACP-адаптер)
подключаются к сессиям.

**Схема рантайма изменилась.** В диаграмме:

- удалён компонент `dashboard` («Web-дашборд · FastAPI SPA · /chat»);
- удалена связь `dashboard-attach` (`dashboard → rpc`, «TUI по /api/pty»);
- из `meta.views[surfaces].focus` убран `dashboard` (осталось `cli, tui, rpc`), а `note` теперь
  называет единственный маршрут `/api/ws` с тикетом;
- освободившийся вертикальный шаг фронтенд-колонки закрыт: `ide` поднят `370 → 280`, `labelAt`
  связи `ide-attach` сдвинут `268,390 → 268,300`;
- `ide` больше не обещает удалённый HTTP API: «IDE-клиенты (ACP) / acp_adapter · hermes acp»,
  связь `ide-attach` — «ACP через gateway» (ACP-адаптер ходит в gateway через
  `hermes_cli.gateway_client.connect_gateway`, то есть тот же `/api/ws`);
- у узла `rpc` подпись отражает оставшийся credential-путь: «нативный тикет · очередь допуска»
  (badge `/api/ws` сохранён);
- в карточке «Путь одного сообщения» первый пункт уточнён: `prompt.submit` идёт в gateway
  «по /api/ws с тикетом».

Узлы CLI/TUI, gateway-контур, cron, адаптеры платформ, ядро агента, инструменты, `state.db`,
LLM- и messaging-провайдеры не менялись: они по-прежнему соответствуют коду.

## Факты, проверенные по коду (ветка `removal-step-4-dashboard`)

### Один listener, один маршрут — `/api/ws`

- `gateway/run_api.py:1-11` — docstring модуля: listener отдаёт ровно один маршрут,
  `ticketed native session WebSocket at /api/ws`; HTTP отвечает 404, любой другой WS-путь
  закрывается; браузерного auth-слоя нет.
- `gateway/run_api.py:45-60` — `SessionListenerFallback`: не-`/api/ws` HTTP → `404
  {"error": "not_found"}`, не-`/api/ws` WebSocket → close `4404`.
- `gateway/run_api.py:202-233` — `GatewayRuntimeAPI._serve` перехватывает только
  `scope['path'] == '/api/ws'`; до допуска проверяются readiness/drain (не ready → `1013`,
  restart-wait admission для ответа на припаркованный prompt, см. `gateway/drain_control.py:42,61`).
- `gateway/run_api.py:86-95` — `_require_loopback`: listener отказывается стартовать на
  не-loopback адресе; `start_gateway_api` (`:97`) по умолчанию `127.0.0.1`, `port=0`
  (эфемерный порт). Вызов — `gateway/run_runtime.py:569`.
- `hermes_cli/web_server_lifecycle.py:40-42` — `build_listener_server` («uvicorn `Config` +
  `Server` … FastAPI-free»): HTTP-слой остался только как транспорт listener'а.
- Порты 9119/9120 рантайм больше не слушает: единственный bind — loopback с `port=0`.
  Остаточные упоминания — легаси-обвязка апдейтера и тексты, не listener'ы:
  `hermes_cli/_parser.py:135-137` (help-текст), `hermes_cli/config_defaults.py:983-984`
  (`webapp`/`dashboard` блоки конфига), `hermes_cli/main_dashboard.py:57` (порт для
  restart-команд старого сервиса), `hermes_cli/dashboard_procs.py` (поиск старых backend'ов).
  Уборка этих остатков — docs/config-этапы.

### Тикет и readiness/drain

- `hermes_cli/web_server_boundary.py:79-90` — `_gateway_ws_ticket_from_subprotocol`: тикет
  берётся ТОЛЬКО из `sec-websocket-protocol` (`hermes-gateway-v1` +
  `hermes-gateway-ticket.<ticket>`), `?token=`/cookie/query не читаются.
- `hermes_cli/web_server_boundary.py:93-130` — `ws_client_reason` (loopback peer gate) и
  `ws_host_origin_reason` (Host/DNS-rebinding) — границы остались.
- `gateway/run_api.py:242-260` — `4403`, если тикет не из subprotocol, peer не loopback, есть
  `Origin` или Host-проверка не прошла; затем redeem `session_ticket_store.redeem(...)` в
  `interactive`, при отказе — `worker-adoption`; неверный тикет → `4403`.
- `gateway/runtime_bootstrap.py:25-100` — `TicketStore`: TTL 30 с, `mint`/`redeem`, профиль и
  capabilities (`interactive`, `worker-adoption`, …).
- `gateway/control_socket.py:351,404` — тикет минтится на owner-only control socket (verb
  `session-ticket`, субъект peer'а); клиентская сторона —
  `hermes_cli/gateway_client.py:273-299` (`_session_ticket`), транспорт —
  `hermes_cli/gateway_client.py:39-45` (`gateway_ws_target` → `/api/ws` + оба subprotocols).
- `gateway/run_api.py:280-284` — после redeem сокет уходит в `tui_gateway.ws.handle_ws` с
  `auth_identity` из тикета: один и тот же JSON-RPC диспетчер для всех клиентов.

### Клиенты

- CLI/`hermes chat` и `hermes gateway attach`: `hermes_cli/gateway_client.py:319-390`
  (`connect_gateway`); `hermes_cli/subcommands/gateway.py:132-149` — `attach` печатает URL
  `/api/ws` + одноразовый тикет.
- TUI: `ui-tui/scripts/gateway_bootstrap.py:47-62` — attach-gateway, тикет из control socket,
  `gateway_ws_target`; `ui-tui/src/gatewayClient.ts:19` — `attachUrl: envUrl('HERMES_TUI_GATEWAY_URL')`.
- ACP: `acp_adapter/gateway_server.py:163` — `connection = connect_gateway()`, то есть ACP
  подключается тем же нативным маршрутом.

### Что удалено (по `git status` на момент снимка)

- `web/**` — 262 tracked-файла SPA (сборка, исходники, `web/AGENTS.md`); `scripts/build/web.mjs`;
  `nix/web.nix` (+ `nix/icons.nix`, `scripts/build/icon_environment.py`); dashboard-сервисы
  `docker/s6-rc.d/dashboard/*` и запись в `docker/s6-rc.d/user/contents.d/dashboard`;
  `evals/dashboard_auth/refresh_singleflight_live_e2e.py`.
- `hermes_cli`: 24 файла `web_server*.py` (кроме `web_server_boundary.py` и
  `web_server_lifecycle.py`), 29 файлов `web_routers/**`, 14 модулей `dashboard_auth/**`
  (login/cookies/routes/ws_tickets/middleware/native_flow/native_http/…); `pty_*.py`,
  `staged_uploads.py`, `web_models.py`, `web_deps.py`, `web_git.py`, `web_build_limits.py`,
  `web_asset_mime_types.py`, `web_read_coalescing.py`, `web_upload_limit.py`,
  `web_whatsapp_session.py`, `dashboard_register.py`, `plugin_host_http_auth.py`,
  `memory_oauth.py`; `hermes_cli/subcommands/dashboard.py` (в нём жили и `dashboard`, и `serve`).
- Build/CI: `hermes_cli/source_build.py:113,124,189-194` — только `ui-tui` (web-продукта нет);
  `scripts/build/freshness.mjs:25-35` — только `tui`-inputs; `pnpm-workspace.yaml` без `web`;
  `package.json` без `install:web`/`audit:web`; `Dockerfile` без dashboard-стадий и
  `HERMES_WEB_DIST`; `setup.py`, `justfile`, `lefthook.yml`, eslint/tsconfig/`.envrc`/`.dockerignore`
  без web-записей; `scripts/ci/classify_changes.py` и `.github/actions/detect-changes` без
  удалённых путей.
- `tests/**` — 262 файла (dashboard/serve-наборы и импортировавшие удалённые модули тесты;
  часть файлов адаптирована под нейтральные дома helper'ов). Итоговые счётчики зависят от
  коммита этапа — здесь зафиксировано состояние рабочего дерева.
- Сознательно оставлено (audit §6): `web_server_boundary.py`, `web_server_lifecycle.py`;
  тонкое `dashboard_auth/` ядро (`__init__`, `base`, `registry`, `listener_client`) для
  plugin-протокола; `dashboard_procs.py` и slim `main_dashboard.py` — легаси-очистка
  процесса/сервиса в апдейтере, не пользовательский дашборд.

### Поведенческое изменение: `HERMES_TUI_GATEWAY_URL`

Удалённая дверь больше не аутентифицируется. Listener принимает только тикет из
`sec-websocket-protocol`, а тикет минтит только owner-only control socket на loopback
(`web_server_boundary.py:79-90`, `gateway/run_api.py:242-248`,
`gateway/control_socket.py:351,404`). Явный URL из `HERMES_TUI_GATEWAY_URL` клиент по-прежнему
берёт как есть (`hermes_cli/gateway_client.py:334`; shared TUI-клиент считает его
non-canonical attach-URL: `apps/shared/src/node/gateway-client.ts:768-783`), но тикета в этом
пути нет — сокет получает `4403`, а `?token=`/browser-credential в URL не читается
(dashboard browser-auth route удалён). Не-loopback bind listener'а тоже запрещён
(`gateway/run_api.py:86-95`). Для локальных CLI/TUI/ACP остаётся штатный тикет-путь.

## Диаграмма и приёмка Archify

- Исходник: `diagram.json` — копия предыдущего снимка с правками выше.
- `validate architecture ... --quality showcase --json` → **9/9 проверок, 0 errors, 0 warnings**
  (`composition.status: pass`; metric'и: 0 proper crossings, 0 ambiguous corridors,
  min label-route clearance 16.6 px, min segment 16 px).
- `deliver architecture ... --quality showcase --json` → ok, spec **sha256
  `d3e0f87c1975ae80d28767cdc3f69005014efcd54034912c1690d52e481c46ec`** (7697 bytes),
  artifact **sha256 `0c3c8078d1ba639be799c23c685d97dd65c0da670590f19559277146ba14e9e9`**
  (820075 bytes).
- `visual-check diagram.html --json` (с `ARCHIFY_CHROME_NO_SANDBOX=1`) → `status: pass`,
  `containment: pass` на 1440×900, 1600×1000, 1920×1080, 2048×1320 (на каждом: нет overflow X/Y,
  `readabilityOk`, `viewerChromeOk`; сняты light+dark капчуры). Ни `validate`, ни `deliver`,
  ни `visual-check` не отклоняли кандидата — правок по диагностике не потребовалось.
  `visualReview: pending` — формальную перцептивную приёмку не заявляю; скриншоты light/dark
  (1440×900 и 2048×1320) просмотрены глазами: диаграмма читаема и сбалансирована.
- Скриншот для быстрого просмотра: `screenshot-light-2048x1320.png`.

## Известные упрощения

- Диаграмма не рисует readiness/drain-гейт отдельным узлом: он остаётся внутри gateway
  (`gateway/run_api.py:202-233`, `gateway/drain_control.py:42,61`) и отражён только подписью
  «нативный тикет · очередь допуска» + пунктом карточки про `/api/ws`.
- Серверный dashboard-путь удалён, но `hermes_cli/dashboard_auth/`-ядро и bundled
  `plugins/dashboard_auth/*` оставлены (протокол/registry нужны plugin-системе); их судьба —
  следующие этапы. После этапа 4 эти провайдеры не могут обслужить страницу.
- Остаточные упоминания dashboard/serve (`_parser.py` help-текст, `config_defaults.py`
  `webapp`/`dashboard`-блоки, legacy-модули апдейтера) относятся к docs/config-этапам;
  на схему рантайма не влияют.
- UI вьюера Archify английский (`meta.locale` не задан для русского) — как в предыдущих снимках.
- Снимок снят в рабочем дереве незавершённого этапа 4: счётчики удалённых файлов и номера
  строк зафиксированы по состоянию на 2026-11-10; Lead коммитит этап и снимок раздельно.
