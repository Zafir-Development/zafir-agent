# Снимок 2026-11-09 — удаление Electron-приложения apps/desktop и Webapp

- **Дата:** 2026-11-09
- **Репозиторий:** `Zafir-Development/zafir-agent` (Hermes Agent)
- **Тип диаграммы:** `architecture` (Archify, `quality_profile: showcase`)
- **Язык:** русский; UI вьюера — английский (см. «Известные упрощения»)
- **База `main`:** `b309d5015fc156815f1ae8074db5688f7dee1c24`
- **База ветки `trim-core-surfaces` (родитель этапа):** `5ab178a43b515fd995278956f33541695718242e`
  (merge PR #4, этап 2)
- **Ревизия ветки `trim-core-surfaces` (кодовый коммит этапа):** `b6b99c1a1554f990e20b71db07df8cfcf52f403d`
  (`refactor(removal): delete the Electron app and the Webapp`)
- **Предыдущий снимок:** `../2026-11-09-removal-step-2-review-fixes/` — не изменялся (append-only).

## Что изменилось

Этап 3 плана `docs/removal/02-removal-plan.md`: удалены Electron-приложение `apps/desktop`,
Webapp и их build inputs; `source_build` переведён на TUI + web (web уходит на этапе 4).

**Схема рантайма изменилась.** В диаграмме:

- удалён компонент `desktop` («Desktop · Electron + React»);
- удалена связь `desktop-attach` (`desktop → rpc`, «gateway ensure»);
- из `meta.views[surfaces].focus` убран `desktop` (осталось `cli, tui, dashboard, rpc`);
- освободившийся вертикальный шаг фронтенд-колонки закрыт: `dashboard` поднят `370 → 280`,
  `ide` — `460 → 370`; `labelAt` связей `dashboard-attach`/`ide-attach` сдвинуты соответственно
  (`268,390 → 268,300`, `268,480 → 268,390`).

Webapp отдельным узлом в диаграмме не рисовался (он собирался из `apps/desktop`), поэтому
удаление Webapp схему не меняет. Узел «Web-дашборд» сохранён: дашборд удаляется на этапе 4.

## Факты, проверенные по коду (база `5ab178a43b`)

### Приложение и Webapp

- `apps/desktop/**` — 4877 tracked-файлов на базе; удалён целиком (Electron main/renderer,
  e2e, assets, packaging, docs, конфиги, скрипты сборки Webapp).
- Удалены 36 Python-модулей:
  - Webapp: `hermes_cli/webapp{,_access,_launcher,_page_policy,_previews,_relay_target,_sign_in}.py`,
    `hermes_cli/web_routers/webapp{,_access,_relay_proxy}.py`, `hermes_cli/subcommands/webapp.py`,
    `gateway/webapp_listener.py`;
  - двери dashboard/Webapp: `hermes_cli/ui_preferences.py`,
    `hermes_cli/web_routers/ui_preferences.py`, `hermes_cli/gateway_connections{,_normalize,_oauth,_probe,_reach,_ssh,_ssh_programs,_ssh_remote,_ssh_transport,_watch}.py`
    (10), `hermes_cli/web_routers/gateway_connections{,_reach}.py`,
    `hermes_cli/web_host_terminal{,_sessions,_ssh}.py` (3);
  - desktop plugin halves: `hermes_cli/desktop_plugin_halves.py`, `desktop_plugin_install.py`,
    `plugin_validate_desktop.py`, `hermes_cli/web_routers/desktop_plugins.py`;
  - связанная web-инфраструктура: `hermes_cli/browser_credential.py`, `web_session_sockets.py`,
    `web_server_static_assets.py` (две функции перенесены в `web_server_dashboard.py`).
- Каскад импортов вычищен в 49 файлах `hermes_cli/`, `gateway/`, `tui_gateway/`; проверка
  `import hermes_cli.main, hermes_cli.web_server, hermes_cli.web_server_app,
  hermes_cli.dashboard_auth.middleware, hermes_cli.dashboard_auth.routes, hermes_cli.plugin_validate,
  gateway.run_api, tui_gateway.methods_tools, tui_gateway.methods_display` — зелёная.

### Build graph и CLI

- `hermes_cli/source_build.py:111-113` — `prepare_launch_dependencies` ставит только
  `("ui-tui", "web")`; desktop-детект через `main_desktop` удалён.
- `hermes_cli/source_build.py:133-137` — `source_frontends` = `ui-tui` + `web` (web — этап 4);
  `build_source_webapp` и сборка `apps/desktop/scripts/build-webapp.mjs` удалены.
  `build_update_products(..., desktop=...)` сохраняет kwarg до этапа 5 (его ещё передают
  `update_finish.py`/`source_completion.py`).
- `hermes_cli/venv_sync.py:607` — детект `apps/desktop` и `--desktop` в `source_completion` убраны.
- `hermes_cli/main.py` — `build_webapp_parser`/`cmd_webapp`/регистрация и `"webapp"` в
  `_SUBCOMMANDS` удалены.
- `scripts/build/freshness.mjs`: продукты `{tui, web}`; удалены `webapp`-inputs и весь
  desktop-механизм install-stamp (`stampClock`, `stampIdentity`, `stampContentHash`, `readStamp`,
  `.hermes-stale`); `buildInputs(source, product, prepared?)`, `recordProduct({source, product, out, inputs})`.
- `scripts/build/frontend-common.mjs`: `developerOutputs = ['ui-tui/dist', 'hermes_cli/web_dist']`,
  удалены `nativeTargetOutput` и ветки `apps/desktop/build/products`.
- `scripts/build/inputs.py`, `scripts/build/agent.py` — frontend `webapp` удалён; web сохранён.
- `scripts/ci/classify_changes.py` — удалены desktop-пины и webapp-маршруты update-пути;
  installer/source lanes не тронуты. `gen_gateway_command_parity.py` потерял Desktop-колонку,
  сгенерированный `website/docs/developer-guide/gateway-command-parity.md` перегенерирован.
- `hermes_cli/config_defaults.py:983` `webapp:`-блок оставлен: `webapp.public_url` ещё читается
  dashboard/web-server кодом (этап 4).
- `Dockerfile:317` (`frontend_build`) собирает `scripts/build/tui.mjs` (`:341`) и web; стадии
  `webapp_build`/`electron-runtime` нет (этап 2). `nix/` не содержит desktop/webapp outputs
  и checks (этап 2); остаточные комментарии вычищены.

### JS-воркспейсы, тесты, CI

- `apps/shared`: удалены desktop-only модули `backend-scope.ts`, `data-url-read-max.ts`,
  `external-url.ts`, `file-url.ts`, `hermes-cloud.ts`, `skill-scaffold.ts`, `translucency.ts`
  (+ их exports и 3 теста); остальное сохранено.
- `ui-tui/scripts/visual/**` (4 файла) и script `visual` удалены — харнесс снимал
  Electron-скриншоты.
- `pnpm-lock.yaml` перегенерирован pinned pnpm 12.15.0: удалены импортёры `apps/desktop` и
  (stale) `apps/bootstrap-installer`, 474 пакета; 0 добавленных `name@version`, без перепина
  (этап 11). `pnpm install --frozen-lockfile` — зелёный.
- `package.json` (`install:desktop`), `.envrc`, `lefthook.yml`, `justfile`, `.gitignore`,
  `.dockerignore`, `pnpm-workspace.yaml`, `web/vitest.config.ts` — desktop-записи убраны.
- Удалено 39 файлов `evals/desktop*`; botmode-evals оставлены этапу 7 (переформулированы только
  мёртвые ссылки на renderer).
- Тесты: 76 файлов удалено (`tests/hermes_cli/test_webapp_*`, `tests/gateway/test_webapp_*`,
  webapp-fixtures, `test_gateway_connections*`, `test_web_host_terminal*`, `test_ui_preferences`,
  `test_desktop_plugin_*`, `test_browser_credential`, `tests/e2e/**/desktop*` и др.);
  адаптированы source_build/web-build/tui-npm/dashboard-auth/display/plugin-validate тесты и
  комментарии; `tests-js` — 7 файлов удалено/адаптировано.
- `pyproject.toml`/`ruff.toml`/`ruff.pre-commit.toml`: per-file-ignore
  `apps/desktop/electron/fixtures/**` удалён.
- AGENTS.md: из корневого routing table убрана строка `apps/desktop`, из «What Hermes Is» —
  Electron desktop; `web/AGENTS.md`, `tui_gateway/AGENTS.md`, `tests/AGENTS.md` — мёртвые ссылки
  переформулированы.

### Остатки (владельцы — следующие этапы)

- `website/docs/**`: 12 файлов ещё упоминают `apps/desktop` — этап 9 (docs-свип):
  `developer-guide/{cli-internals,codebase-ownership,desktop-plugin-sdk,macos-bundle-updates,shared-bundle-builds,worktree-ui-dev}.md`,
  `getting-started/updating.md`, `reference/{cli-commands,package-management}.md`,
  `user-guide/{desktop,git-worktrees}.md`,
  `user-guide/skills/optional/software-development/software-development-inspecting-hermes-desktop-dom.md`.
- `optional-skills/software-development/inspecting-hermes-desktop-dom/SKILL.md` — этап 9.
- `tests/fixtures/legacy_desktop/`, `tests/hermes_cli/test_desktop_*`, `test_gui_command.py`,
  `test_linux_desktop_entry.py`, `test_bundled_desktop_launch.py`, `test_update_*` — этапы 5/10
  (эти тесты пинят ещё не удалённую desktop-функциональность).
- `tests/tools/test_bot_mode_canonical_chat_resolution.py` — этап 7.
- `hermes_cli/{main_desktop*,gui,linux_desktop_entry,desktop_build_lock,desktop_release_holders,update_*,steward,shared_metrics_contract,commands}.py`
  — этапы 5/6; desktop tools/toolsets — этап 6; Bot Mode — этап 7; desktop plugin SDK
  (RPC/locales/catalog shelf) — этап 8; перепин зависимостей — этап 11.

## Диаграмма и приёмка Archify

- Исходник: `diagram.json` — копия предыдущего снимка с правками выше.
- `validate architecture ... --quality showcase --json` → **9/9 проверок, 0 errors, 0 warnings**.
- `deliver architecture ... --quality showcase --json` → ok, spec **sha256
  `d6886f8821b0f1f71358ad1e3a912ea790a43d4f149cf2b37da080e856ce55b0`** (7999 bytes),
  artifact **sha256 `6453043f3f9fb76e41d173f4fc2c93aa462b114153ac0a3472ff74b9c3690edf`**
  (822040 bytes).
- `visual-check diagram.html --json` (с `ARCHIFY_CHROME_NO_SANDBOX=1`) → `status: pass`,
  containment pass на 1440×900, 1600×1000, 1920×1080, 2048×1320 (нет overflow X/Y, readability ok;
  сняты light+dark капчуры). `visualReview: pending` — перцептивную оценку не заявляю.
- Скриншот для быстрого просмотра: `screenshot-light-2048x1320.png`.

## Известные упрощения

- Диаграмма сохраняет узел «Web-дашборд» и связи `dashboard-attach`/`ide-attach`: дашборд
  (`web/`, `hermes dashboard`/`serve`) удаляется на этапе 4.
- Webapp-двери удалены, но dashboard-сервер оставлен импортируемым: убраны только
  webapp-специфичные проверки (socket-named ticket refusal, browser-credential generation
  tracking, webapp sign-in binding, saved-gateway sign-in). Остаточные мёртвые seam'ы
  (`listener_public_url`, `webapp` policy entry, `_webapp_caller_signed_out`) — этап 4.
- Проверки, которые нельзя было выполнить на этой машине: `docker build` (нет демона —
  static-only: `tests/docker/test_dockerfile_build_context.py`), `nix flake check` (nix нет),
  PowerShell-синтаксис `windows-e2e.ps1` (pwsh нет). Полные прогоны
  `tests/hermes_cli`/`tests/gateway` не укладываются в 300-секундный per-file cap под нагрузкой
  хоста; гонялись целевые файлы, а environment-only падения (macOS bash 3.2 `mapfile`,
  `_sysconfigdata__linux_darwin`, realpath `/private/var`) зафиксированы отдельно.
- UI вьюера Archify английский (`meta.locale` не задан для русского) — как в предыдущих снимках.
