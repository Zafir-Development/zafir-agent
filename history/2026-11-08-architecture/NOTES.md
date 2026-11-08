# Снимок 2026-11-08 — архитектура Hermes Agent

- **Дата:** 2026-11-08
- **Ревизия `main`:** `8d7061f1a74980a7549356a4e5e57b603475ddf0`
- **Репозиторий:** `Zafir-Development/zafir-agent` (Hermes Agent)
- **Тип диаграммы:** `architecture` (Archify, `quality_profile: showcase`)
- **Язык:** русский; UI вьюера — английский (см. «Известные упрощения»)

## Что на схеме

- **Интерфейсы:** CLI-клиент (`hermes`, `hermes chat`), TUI на Ink (`hermes --tui`),
  Desktop (Electron + React), веб-дашборд (`FastAPI` SPA, `/chat`), IDE и внешние API
  (ACP / HTTP API).
- **Gateway-процесс (один владелец на хост):** JSON-RPC и сессии (очередь допуска,
  стрим событий), адаптеры платформ (Telegram, Discord, Slack, ~20 платформ),
  Cron и фоновые задачи.
- **Ядро агента:** `AIAgent`, turn loop, сжатие контекста, стабильный prompt cache;
  вызовы инструментов (70+ tools, ~28 toolsets: терминал, браузер, web, MCP,
  субагенты).
- **Внешнее:** LLM-провайдеры (Nous Portal, OpenRouter, OpenAI и др.) по HTTPS;
  `state.db` (SQLite + FTS5) в `HERMES_HOME` профиля.
- **Карточки:** путь одного сообщения, состав gateway-процесса, состояние и расширения.

## Проверка фактов

| Узел / связь | Проверенный факт | Источник |
|---|---|---|
| CLI → `attach · /api/ws` | CLI больше не запускает агента в своём процессе: находит/стартует gateway профиля и подключается по локальному WebSocket | `website/docs/user-guide/cli.md:176` |
| TUI (Ink) → JSON-RPC | TUI подключается к общему gateway профиля по `/api/ws`, протокол `hermes-gateway-v1`, одноразовый ticket | `website/docs/user-guide/tui.md:298`; `tui_gateway/AGENTS.md:9-21` |
| Desktop → `gateway ensure` | приложение выполняет `hermes gateway ensure`, подключается по `/api/ws` с одноразовыми тикетами | `website/docs/user-guide/desktop.md:634`; `apps/desktop/src/AGENTS.md:6-20` |
| Web-дашборд → `TUI по /api/pty` | дашборд встраивает настоящий `hermes --tui` через PTY (xterm.js), а не переписывает чат на React | `web/AGENTS.md:9-28`; `hermes_cli/web_routers/chat_ws.py:475` |
| IDE / внешние API → `ACP / HTTP` | ACP-адаптер и HTTP API подключаются к тому же session authority | `website/docs/developer-guide/gateway-internals.md:133-142`; `acp_adapter/` |
| Gateway — один владелец на хост | один gateway-процесс обслуживает все профили хоста (кроме `gateway.standalone: true`); под мультиплексом — по одному session authority на обслуживаемый home | `website/docs/user-guide/desktop.md:634`; `website/docs/user-guide/multi-profile-gateways.md:263,294`; `website/docs/developer-guide/gateway-internals.md:133-142` |
| JSON-RPC и сессии | durable-очередь допуска, состояние pending-входов, стрим событий в `/api/ws`; контракт объявлен в Python и генерируется для TypeScript | `website/docs/developer-guide/gateway-internals.md:69-95`; `tui_gateway/AGENTS.md:28-45` |
| Ядро агента | `AIAgent` — фасад; цикл хода в `agent/conversation_loop.py` и `agent/turn_*.py`; prompt cache неизменен, сжатие — единственное исключение | `agent/AGENTS.md:7-19` |
| Инструменты | реестр инструментов, 70+ tools и ~28 toolsets; терминал/браузер/web/MCP/субагенты | `website/docs/developer-guide/architecture.md:218-222`; `tools/AGENTS.md` |
| Адаптеры платформ | адаптеры в `gateway/platforms/` поверх `base.py`, 25+ платформ (встроенные и плагины) | `gateway/AGENTS.md:6-13`; `website/docs/developer-guide/architecture.md:230-233` |
| Cron | cron ticking — часть долгоживущего gateway-процесса | `website/docs/developer-guide/architecture.md:232`; `gateway/run.py:1654` (`_cron_tick_profile_homes`) |
| LLM-провайдеры | общий runtime-резолвер провайдеров/моделей для CLI, gateway, cron, ACP и auxiliary-вызовов | `agent/AGENTS.md:94-107`; `website/docs/developer-guide/architecture.md:212-216` |
| `state.db` | SQLite + FTS5: сессии, транскрипты, поиск, lineage | `website/docs/developer-guide/architecture.md:41-48,224-228`; `website/docs/developer-guide/session-storage.md` |

## Что изменилось при перепроверке

1. **Владелец gateway.** Было «1 на профиль» — стало «один владелец на хост»:
   один процесс обслуживает все профили, кроме помеченных `gateway.standalone`,
   а под `gateway.multiplex_profiles` внутри него по одному session authority на
   каждый обслуживаемый home.
2. **Добавлен узел «Cron и фоновые задачи»** внутрь gateway-процесса и связь
   «по расписанию» → «JSON-RPC и сессии».
3. **Уточнён подзаголовок узла сессий**: «очередь допуска · стрим» (cron вынесен
   в отдельный узел).
4. **Guided view «Ход агента»** теперь включает cron в фокус.

## Приёмка

- `validate`: 9/9 проверок, `showcase`, ошибок 0, предупреждений 0.
- `deliver`: спецификация `sha256:1e9bf039283f5ff9361fd53d5c7789f84925fb8508b65a555fb326acd031a0f6`
  (8 436 байт); артефакт `sha256:ce692b81bef4c7d97030984583be71578daa9b81a22593307b32997f806a58fd`
  (824 178 байт).
- `visual-check`: `pass`, 4/4 вьюпорта — 1440×900, 1600×1000, 1920×1080, 2048×1320;
  `scrollWidth`/`scrollHeight` в пределах вьюпорта; скриншоты light/dark.
- Перцептивная проверка: **пройдена** по скриншотам (light 1440 и 2048, dark 1440) —
  нет обрезанных подписей, наложений узлов и карточек, читаемый порядок.
- Archify: `2.17.0-dev.1`.

## Воспроизведение

```bash
node ~/.agents/skills/archify/bin/archify.mjs validate architecture \
  history/2026-11-08-architecture/diagram.json --quality showcase --json
node ~/.agents/skills/archify/bin/archify.mjs deliver architecture \
  history/2026-11-08-architecture/diagram.json \
  history/2026-11-08-architecture/diagram.html --quality showcase --json
node ~/.agents/skills/archify/bin/archify.mjs visual-check \
  history/2026-11-08-architecture/diagram.html --json
```

## Известные упрощения

- Схема показывает топологию, а не деплой: удалённые/SSH/cloud-gateway, отдельный
  `gateway.standalone`-профиль, `api_server`-платформа и внутреннее устройство ACP
  не детализируются.
- Dashboard: чат — это настоящий TUI-ребёнок поверх PTY; в части режимов он
  подключается к in-process `tui_gateway` дашборда по loopback `/api/ws`, но сессии
  всё равно обслуживаются gateway/session authority. Связь «Web-дашборд →
  JSON-RPC и сессии» намеренно укрупнена.
- Один узел «LLM-провайдеры» вместо списка провайдеров; провайдеры-плагины не
  раскрываются.
- Плагины, скиллы, MCP-серверы и субагенты показаны карточками и подзаголовками,
  а не отдельными узлами (чтобы не перегружать схему).
- `meta.locale` не задан: Archify поддерживает только `en` и `zh-CN`, поэтому
  фиксированный UI вьюера и `<html lang>` остаются английскими; содержимое схемы —
  на русском.
