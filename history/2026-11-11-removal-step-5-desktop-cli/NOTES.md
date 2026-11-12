# Снимок 2026-11-11 — удаление desktop CLI, config и update/uninstall-веток

- **Дата:** 2026-11-11
- **Репозиторий:** `Zafir-Development/zafir-agent` (Hermes Agent)
- **Тип диаграммы:** `architecture` (Archify, `quality_profile: showcase`)
- **Язык:** русский; UI вьюера — английский (см. «Известные упрощения»)
- **База `main`:** `b309d5015fc156815f1ae8074db5688f7dee1c24`
- **База ветки `removal-step-5-desktop-cli` (родитель этапа):** `62bee6d5df` — merge PR #6
  (`removal-step-4-dashboard`); дерево совпадает с tip этапа 4 `17956759f0`
- **HEAD на момент снятия снимка (code-коммиты этапа):** `142bddafb3`
  (`test(removal): retarget tests ...`; коммит снимка идёт отдельно сверху)
- **Документ-план этапа:** `docs/removal/02-removal-plan.md` § Step 5
- **Предыдущий снимок:** `../2026-11-10-removal-step-4-dashboard-serve/` — не изменялся
  (append-only).

## Что изменилось

Этап 5 плана `docs/removal`: удалены команда `hermes desktop` (и алиас `hermes gui`), весь код
сборки/запуска/подписи Electron-приложения, а также все config/update/uninstall/doctor/telemetry-
ветки, существовавшие только ради установленного desktop-приложения. Рантайм Hermes остался тем
же, что и после этапа 4: CLI + TUI + messaging gateway с единственным loopback-listener'ом
`/api/ws` (одноразовый тикет из control socket).

Удалено:

- 15 desktop CLI/сборочных модулей: `hermes_cli/main_desktop*.py`, `desktop_build_lock.py`,
  `desktop_build_reuse.py`, `desktop_console.py`, `desktop_release_holders.py`,
  `desktop_update_verify.py`, `gui_uninstall.py`, `bundled_app.py`,
  `windows_appinstaller_update.py`, `windows_store_update.py`, `macos_tcc_anchor.py`,
  `linux_desktop_entry.py`, `subcommands/gui.py`, плюс `windows_ssh_runtime.py` (Windows-рантайм
  Desktop SSH-бэкенда) и 27 их тестов.
- старый updater-compat слой (D9, «полная ревизия», отложенная этапом 4):
  `hermes_cli/_old_updater.py`, `old_updater_deps.py`, `_update_takeover.py`, `update_finish.py`,
  `update_handoff.py`, `managed_uv.py`, `npm_engine.py`, `psutil_android.py`, `_scan_venv_blockers.py`,
  их shim-функции в `update_cmd*.py`/`update_completion.py`/`update_zip`-ветках и
  `hermes_bootstrap.py`'s legacy `--post-swap` path; `tests/compat/**`,
  `scripts/audit-old-updater-imports.py`, `scripts/ci/check_lazy_deps_imports.py`,
  `evals/update_pipeline/post_swap_handoff_ab.sh`.
- `hermes_cli/dashboard_procs.py` и slim `hermes_cli/main_dashboard.py` (держались frozen
  old-updater surface). Их живые helper'ы вынесены в нейтральные модули
  `hermes_cli/process_inventory.py` (поиск процесса/дома по pid) и
  `hermes_cli/service_restart_helpers.py` (команды restart для legacy-сервисов), а
  `_finalize_update_output`/`_install_hangup_protection` — в `hermes_cli/update_output.py`.
- desktop-секция `DEFAULT_CONFIG` (16 листьев); нужные TUI значения переехали в нейтральные
  `projects.repo_scan_{enabled,roots,exclude_paths}` и
  `sessions.auto_continue.{enabled,freshness_minutes,max_attempts}`.
- shared-metrics desktop/v5-ветки: `observability/shared_metrics_desktop.py`, шесть
  `hermes.desktop.*` метрик и `shared_metrics.update_run` из контракта и схем v3/v4,
  соответствующие JSON-RPC handler'ы, desktop-строки в `shared_metrics_contract`/
  `shared_metrics_setup`/`shared_metrics_disabled`.
- desktop-поля `CommandDef.desktop`/`desktop_subcommands` и 32 аннотации, `command_desktop_meta()`,
  `desktop_surface_registry()`; `argument_mode` сохранён (его использует TUI), review-скоуп
  переименован в `review_subcommands`.
- desktop-ветки update/source: `had_desktop_app_before_update`, `_desktop_owns_gateway_lifecycle`,
  `_rebuild_desktop_after_update`, `_looks_like_desktop_control_plane`, ZIP-сохранение
  `apps/desktop`, TCC-anchor в post-update, `desktop=`/`desktop_build_ok=` параметры
  `_prepare_updated_checkout`/`_print_update_summary`, `desktop` в completion request.
- `hermes gui.log`/`desktop.log`: GUI-режим логирования, сбор логов в `debug`/`logs`,
  `hermes logs gui|desktop|handoff`.
- Windows/macOS product identity: `STEWARD_DESKTOP`, desktop uninstall/update сообщения,
  `version_info.distribution == "desktop-app"`, desktop-app ветка баннера,
  `HERMES_DESKTOP_CHILD_PID`-исключение в security-audit.
- `is_desktop_owned_backend`; desktop-предикаты `process_identity` переименованы в нейтральные
  `serving_local_host` / `serves_local_host_now` / `local_host_client`, `anon_auth.on_local_host_backend`,
  `welcome_trial.claim_welcome_trial`; `REAPABLE_PURPOSES` сокращён до `{"gateway", "mcp-helper"}`.
- serve/desktop-serve attach-роли `gateway/host_rendezvous.py` (`ROLE_SERVE`, `ROLE_DESKTOP_SERVE`,
  `probe_owner`, `/api/host/identity`) — осталась одна роль `ROLE_GATEWAY`; `plugins_activation`'s
  `notify_serve_backend`/`_serve_backend_record` удалены. Windows-запись credential-файлов с
  owner+SYSTEM DACL вынесена из `windows_ssh_runtime` в нейтральный `hermes_cli/private_file.py`.
- `hermes_cli/uninstall.py`: `run_gui_uninstall`, `--gui`, `--gui-summary`, `--desktop-userdata`,
  macOS Electron/TCC-уборки и dashboard launchd sweep; обычный CLI uninstall и `--data` сохранены.

Оставлено без изменения поведения:

- CLI chat, TUI, gateway и его messaging-адаптеры, cron, tools, plugins, source install/update,
  обычный `hermes uninstall`.
- `argument_mode` в registry, review-скоуп `/skills` для TUI, `plugins.dashboard_auth` core и
  bundled-провайдеры (решение по ним — этап 8, см. «Известные упрощения»).
- Историческая wire-лексика, которую могут нести уже записанные строки/квитанции (`source="desktop"`,
  `initiator/kind: desktop`, retired enum-значения shared-metrics, `UPDATE_MECHANISMS`
  стампов) — удалены только producers, не readers.

## Почему схема рантайма не изменилась

Компонент Desktop удалён из диаграммы ещё на этапе 3, а этап 4 удалил dashboard/`serve` и
переписал runtime-схему (CLI + TUI + gateway, один loopback-listener `/api/ws`). Этап 5 удаляет
build/CLI/config/update-ветки desktop-приложения, но не добавляет и не убирает ни одного
runtime-компонента, процесса или сетевой связи: `hermes desktop|gui` больше не команда, однако
процессная топология та же. Поэтому `diagram.json` и `diagram.html` скопированы из
`../2026-11-10-removal-step-4-dashboard-serve/` без изменений; контрольные суммы совпадают с
предыдущим снимком:

- `sha256(diagram.json)` = `d3e0f87c1975ae80d28767cdc3f69005014efcd54034912c1690d52e481c46ec`
- `sha256(diagram.html)` = `0c3c8078d1ba639be799c23c685d97dd65c0da670590f19559277146ba14e9e9`

Файл `diagram.json` не содержит ни одного вхождения `desktop` (проверено `grep -ci desktop` = 0);
узлы CLI/TUI/gateway/agent/tools/state/провайдеры по-прежнему соответствуют коду.

## Факты, проверенные по коду (ветка `removal-step-5-desktop-cli`)

### CLI: desktop-команд больше нет

- `hermes_cli/main.py` — нет импортов `subcommands.gui`/`main_desktop`/`main_dashboard`;
  `_SUBCOMMANDS`/`_BUILTIN_SUBCOMMANDS` не содержат `desktop`/`gui`;
  `cmd_uninstall` (`hermes_cli/main.py:2016`) оставляет только `--data`-ветку и обычный uninstall.
- `hermes_cli/subcommands/uninstall.py` — `--full | --data`, `--yes`, `--dry-run`; флагов
  `--gui`/`--gui-summary`/`--desktop-userdata` нет.
- `hermes_cli/uninstall.py:969` — module-entrypoint `--mode {lite,full,data}` (было +`gui`);
  `hermes_cli/uninstall.py:457` — `remove_app_leftovers` (только XDG cache/data, macOS
  Electron-каталоги и dashboard launchd sweep удалены).
- Проверка: `python -m hermes_cli.main --help`, `... update --help`, `... uninstall --help` не
  содержат desktop/gui; `hermes desktop --help` и `hermes gui --help` → «not a `hermes` command»
  с exit 2.

### Slash-реестр и TUI

- `hermes_cli/commands.py:65` — `argument_mode` сохранён; `:71` — `review_subcommands`;
  поля `desktop`/`desktop_subcommands` удалены. `command_catalog_meta()` отдаёт только
  `argument_mode`; `tui_gateway/command_discovery.py` и `tui_gateway/methods_tools.py` читают
  review-скоуп из `review_subcommands`.
- `tui_gateway/contracts/tools_commands.py` — `CommandCatalogMeta` больше не несёт
  `desktop`/`desktop_subcommands`; сгенерированные `apps/shared/src/gateway-contract.*`
  пересозданы `scripts/gen_gateway_contracts.py` (`--check` чист).
- `python scripts/gen_gateway_command_parity.py --check` чист;
  `website/docs/developer-guide/gateway-command-parity.md` пересоздан генератором.

### Process identity / host rendezvous

- `hermes_cli/process_identity.py:390,399,403` — `serving_local_host`/`serves_local_host_now`/
  `local_host_client`; `_BACKEND_OWNER_PURPOSES` (`:44-46`) = gateway; `_REAP_MIN_AGE_SECONDS`
  (`:567`) инлайнен; `_desktop_spawner_identity` (HERMES_PARENT_PID) удалён.
- `gateway/host_rendezvous.py:57-58` — `ROLE_GATEWAY` и `_ROLES = (ROLE_GATEWAY,)`; `probe_owner`
  и `HOST_IDENTITY_PATH` удалены.
- `hermes_cli/private_file.py:114` — `write_private_text` (POSIX 0600 / Windows owner+SYSTEM DACL),
  единственный потребитель — `gateway/host_rendezvous.py` при публикации host-token;
  `hermes_cli/windows_ssh_runtime.py` удалён, pywin32-комментарий в `pyproject.toml` переуказан.

### Update/source

- `hermes_bootstrap.py` — legacy `--post-swap` invocation и импорт `update_handoff` удалены.
- Новые нейтральные модули: `hermes_cli/process_inventory.py`,
  `hermes_cli/service_restart_helpers.py`, `hermes_cli/update_output.py`;
  `_finalize_update_output`/`_install_hangup_protection` импортируются в `hermes_cli/main.py:715`
  из `update_output`.
- `hermes_cli/main.py:1920` — от frozen-surface остались только ленивые имена `update_cmd`
  (eager-импорт стоил бы старта); блоки `old_updater_deps`/`dashboard_procs`,
  `_write_update_incomplete_marker` и `_detect_venv_python_processes` удалены.
- `scripts/ci/classify_changes.py` — секции `_UPDATE_PIPELINE`/`_UPDATE_DEPENDENCIES` больше не
  называют удалённые desktop/frozen модули, добавлены `update_output.py`,
  `process_inventory.py`, `service_restart_helpers.py`.
- `pyproject.toml` `[tool.hermes] update-startup-files` больше не содержит
  `hermes_cli/update_handoff.py`; `scripts/install_root_lint_baseline.json` — записи для
  `_old_updater.py`, `linux_desktop_entry.py`, `macos_tcc_anchor.py`, `main_dashboard.py`,
  `update_handoff.py` удалены.
- `_source_completion_request()` (`hermes_cli/update_cmd.py`) больше не принимает/не передаёт
  `desktop`; `_prepare_updated_checkout`/`_print_update_summary` — без desktop-параметров.
- `hermes_cli/source_build.py` собирает только TUI + launchers; ZIP-перенос больше не
  сохраняет `apps/desktop` (`_ZIP_PRESERVED_NESTED` = scripts/ui-tui).

### Config и телеметрия

- `hermes_cli/config_defaults.py:2299,2310` — новые нейтральные ключи
  `sessions.auto_continue` и `projects.repo_scan_*`; desktop-секции нет. Потребители —
  `tui_gateway/session_auto_continue.py` и `tui_gateway/methods_projects.py` (TUI-поведение
  сохранено). Новые 6 ключей добавлены в `scripts/ci/docs_drift_baseline.json` (docs — этап 9).
- `hermes_cli/observability/shared_metrics_contract.py` — определения `hermes.desktop.*` и
  `shared_metrics.update_run` удалены; исторические *значения* enum'ов (`desktop`, `desktop_attach`,
  `serve_boot`, `dashboard`, `download`) оставлены с комментариями «removed client; old rows stay
  valid», чтобы не терять уже записанные строки.
- `hermes_cli/observability/schemas/hermes.shared_metrics.v3.schema.json` и
  `...v4.schema.json` — ни одного `hermes.desktop.*` (`grep -c` = 0); v3 сохранён как формат
  «pending»-пакетов.
- `tui_gateway/methods_shared_metrics.py` — удалены 5 desktop_*-handler'ов и `update_run`;
  `tui_gateway/contracts/config_free_tier_control.py` — `SharedMetricsSetParams.first_run` нет,
  `SharedMetricsStartupLatencyParams.surface` = `Literal["tui"]`; контракты перегенерированы.

### Прочее

- `hermes_logging.py:355` — `setup_logging(mode=...)` больше не знает `gui`/`gui.log`;
  `hermes_cli/logs.py` — потоки agent/errors/gateway/update/mcp-stderr.
- `hermes_cli/banner.py` — desktop-shell ветка удалена; commit-build артефакт печатает
  `… · commit-build · <sha>` из стампа без git-probe.
- `.github/blob-size-allowlist.txt` — добавлен путь этого снимка (`history/.../diagram.html`),
  как для предыдущих снимков.

## Приёмка Archify

- `validate architecture diagram.json --quality showcase --json` — `ok: true`, 9/9 проверок,
  `composition.status = pass`, 0 errors, 0 warnings.
- `deliver architecture diagram.json diagram.html --quality showcase --json` — `ok: true`.
- `visual-check diagram.html --json` — pass на 1440×900, 1600×1000, 1920×1080, 2048×1320
  (readabilityOk, legend/navigation dock без пересечений).

## Метрики (по §Measurement из `docs/removal/03-optimization.md`)

Замеры теми же командами, что в `docs/removal/03-optimization.md` § Measurement, на базовом
коммите `62bee6d5df` и на дереве после этапа 5 (до коммита снимка):

| Метрика | Было (base) | Стало | Δ |
|---|---:|---:|---:|
| tracked-файлы (`git ls-files \| wc -l`) | 17 131 | 17 036 | −95 |
| tracked-строки | 3 695 484 | 3 682 294 | −13 190 |
| Python-файлы | 10 328 | 10 233 | −95 |
| Python non-test строки | 1 014 337 | 1 002 714 | −11 623 |
| tracked-байты | 189 884 514 | 189 631 913 | −252 601 |

Диффа: 103 удалённых файла (66 тестов, 37 не-тестов), 8 добавленных (4 нейтральных модуля +
4 файла снимка), 271 изменённый. Тестовых файлов удалено 66; перенесены 4 теста
`_needs_interpreter_*` в `tests/hermes_cli/test_relaunch.py`.

## Известные упрощения

- D9: пользователей нет, поэтому старые значения desktop-конфига просто игнорируются, без
  миграции и shim'ов.
- Bundled `plugins/dashboard_auth/*` и его реестр (`hermes_cli/dashboard_auth/`, плагинный API
  `register_dashboard_auth_provider`) оставлены: их удаление пересекается с этапом 8 (plugin SDK),
  решение зафиксировано в PR этапа 5.
- `scripts/write_install_stamp.py` всё ещё умеет `HERMES_DESKTOP_VARIANT`/`distribution
  desktop-app` и хранит историческую stamp-лексику — это упаковочный cleanup, отложенный на
  этап 10 (не влияет на рантайм: readers валидируют только `docker`/`nix`).
- Update-inventory по-прежнему понимает legacy-типы runtime `serve`/`dashboard` (read-only остатки
  до-этапных установок); удаление — этап 10.
- Имена и ветки этапа 6/7/8 остаются как есть: `tools/desktop_ui.py`, preview/terminal/window/tour-
  инструменты, `CLIENT_SURFACE_TOOLSETS`, `gateway/session_policy.LOCAL_DESKTOP_CHAT`,
  `tui_gateway` desktop-бриджи, `tools/bot_desktop/**`, plugin kind «desktop», локали
  `*.desktop.yaml`. Их desktop-упоминания — ожидаемый долг следующих этапов, не этапа 5.
- UI вьюера Archify — английский (встроенный), как в предыдущих снимках.
