# Снимок 2026-11-08 — удаление GUI-установщика и desktop-стадий установщика

- **Дата:** 2026-11-08
- **Репозиторий:** `Zafir-Development/zafir-agent` (Hermes Agent)
- **Тип диаграммы:** `architecture` (Archify, `quality_profile: showcase`)
- **Язык:** русский; UI вьюера — английский (см. «Известные упрощения»)
- **База `main`:** `b309d5015fc156815f1ae8074db5688f7dee1c24`
- **Ревизия ветки `trim-core-surfaces` (кодовый коммит):** `1463d81269f576b6c349c516c47d9965fdc4fdf8`
  (`refactor(install): remove GUI bootstrap installer and desktop installer stages`)
- **Предыдущий снимок:** `../2026-11-08-architecture/` — не изменялся (append-only).

## Что изменилось

Этап 1 плана `docs/removal/02-removal-plan.md`: удалён GUI-установщик Hermes-Setup и всё
в установщиках, что существовало только для desktop-приложения. Архитектура рантайма
(CLI → gateway → ядро агента → LLM-провайдеры и `state.db`) не менялась.

- `apps/bootstrap-installer/**` удалён целиком (Tauri/Rust + React GUI-установщик).
- `.github/workflows/bootstrap-installer-build.yml` (сборка/подпись/нотаризация Hermes-Setup)
  и `.github/workflows/rust-tests.yml` (cargo-тесты Tauri-crate) удалены.
  `.github/workflows/bootstrap-installer.yml` переименован в `install-script.yml`
  (`Install script protocol`); из него убраны `-ProtocolVersion`-шаги — workflow
  проверяет протокол source-установки, а не GUI-приложение.
- `scripts/install.sh`: убраны флаг `--include-desktop`/`-IncludeDesktop`, константа
  `INCLUDE_DESKTOP`, pseudo-стадия `desktop`, `stage_desktop`, `desktop_product_present()`
  и desktop-строка/аргумент в `stage_products`. Манифест — ровно 9 source-стадий:
  `prerequisites repository venv python-deps config products setup gateway complete`;
  `protocol_version` (1) и stage-кадры не менялись.
- `scripts/install.ps1`: убраны `-IncludeDesktop`, `-ProtocolVersion`, `$ProductTitle`
  desktop-arm, `Test-DesktopProductPresent`, `Stage-Desktop` + dispatch,
  `Confirm-DesktopArtifact`, `New-DesktopShortcuts` и desktop-комментарии.
  `Invoke-InstalledHermes` больше не подгружает из диска
  `scripts/desktop-update/runtime.ps1` через `[IO.File]::ReadAllText`/`ScriptBlock::Create`,
  а запускает `.hermes\bin\hermes.exe` (fallback `.hermes\bin\hermes.cmd`) напрямую с
  `$CommandArgs`, сохраняя контракт `Invoke-Native`/exit-code и классификации
  `setup_failed`/`gateway_failed`. Это и упрощает запуск под политикой Restricted:
  лаунчер — exe/cmd, а не .ps1-файл, который политика запрещает загружать.
- CI-классификатор: удалены путь `apps/bootstrap-installer/` и весь Rust/Tauri-lane
  (`rust` output, `_RUST_PATHS`, `_RUST_FILENAMES`, `_is_rust`, `rust-tests` job и его
  `needs`); `bootstrap`-lane остаётся и срабатывает на `scripts/install.sh`,
  `scripts/install.ps1`, `scripts/gen-bootstrap-pins.py`, `setup-hermes.sh` и
  `.github/workflows/install-script.yml`. Обновлены `detect-changes/action.yml`,
  `ci.yaml`, `scripts/ci/classify_changes.py`, `.github/workflows/README.md` и
  path-assertion тесты (`tests/ci/`).
- Desktop-стадии/флаги установщика убраны из installer-E2E: `installer-script+desktop`
  и `desktop-installer@latest` удалены из `scripts/sandbox/generate-e2e-matrix.mjs`,
  `tests/install/installer-script-e2e.sh`, `tests/install/e2e-assets/installer-common.sh`,
  `tests/install/windows-e2e.ps1`, `install-e2e-run.yml`, `install-e2e-windows-run.yml`,
  `install-e2e-macos-run.yml`; шаги `-ProtocolVersion` в install-script workflow удалены.
  Signed-bundle (`packaged-app` → `open-app-update`) и source `hermes-desktop-app-update`
  ноги оставлены: они не запускают GUI-установщик и обслуживаются последующими этапами
  (см. «Известные упрощения»).
- `scripts/generate_icons.py`: удалены bootstrap-installer outputs (doc-карта,
  `CHECK_SIZES`, `TARGETS`), desktop-иконки не тронуты (этап 2/3). Обновлён
  `scripts/generate-icons.mjs`. `justfile`/`lefthook.yml`: удалены
  `lint-bootstrap-installer` и job с `root: apps/bootstrap-installer/`.
- Тесты, пинившие удалённое: `tests/scripts/test_install_ps1_desktop_stage.py`,
  `tests/scripts/install/test_install_desktop_product_present.py`,
  `tests-js/bootstrap-installer-stage-timer.test.ts` удалены. `install-known-failures`
  оставлен — он покрывает source-ноги. `test_install_ps1_execution_policy.py` переписан
  под новый контракт (прямой запуск лаунчера под Restricted policy).

**Почему диаграмма без изменений.** GUI-установщик и стадии `install.sh`/`install.ps1` — это
инструмент доставки, а не рантайм-архитектура: на `diagram.json` их нет ни узлом, ни связью.
Менять схему было бы нечем; поэтому `diagram.json` скопирован из предыдущего снимка как есть,
`diagram.html` пересобран тем же Archify (побайтово совпадает с прошлым артефактом), а снимок
фиксирует факт отсутствия архитектурных изменений и удалённые поверхности.

## Проверка фактов

| Узел / утверждение | Проверенный факт | Источник |
|---|---|---|
| `scripts/install.sh` — 9 стадий, без `desktop` | `stage_names()` печатает `prerequisites repository venv python-deps config products setup gateway complete`; `run_stage` не содержит ветки `desktop` | [scripts/install.sh](../../scripts/install.sh#L490-L492), [run_stage](../../scripts/install.sh#L1161-L1191) |
| `scripts/install.sh` — протокол не менялся | `emit_manifest` печатает `{"protocol_version":1,"stages":[...]}` | [scripts/install.sh](../../scripts/install.sh#L510) |
| `scripts/install.sh` — нет desktop-флага/пробы | в файле нет `INCLUDE_DESKTOP`/`desktop_product_present`; `stage_products` зовёт completion без `--desktop` | [scripts/install.sh](../../scripts/install.sh#L1073-L1088) |
| `scripts/install.ps1` — прямой запуск лаунчера | `Invoke-InstalledHermes` ищет `.hermes\bin\hermes.exe`, затем `.cmd`, и вызывает `Invoke-Native { & $launcher @CommandArgs }`; `scripts/desktop-update/runtime.ps1` не загружается | [scripts/install.ps1](../../scripts/install.ps1#L1443-L1465) |
| `scripts/install.ps1` — манифест/стадии | `$Stages` — те же 9 стадий, `protocol_version = 1` | [scripts/install.ps1](../../scripts/install.ps1#L875-L887), [manifest](../../scripts/install.ps1#L1522) |
| GUI-установщик удалён | каталога `apps/bootstrap-installer/` больше нет; Tauri-crate и frontend удалены | `git show --stat 1463d81269` |
| install-script CI-lane | `ci.yaml` job `install-script` → `install-script.yml`; workflow name «Install script protocol»; `-ProtocolVersion`-шагов нет | [ci.yaml](../../.github/workflows/ci.yaml#L219-L228), [install-script.yml](../../.github/workflows/install-script.yml#L1-L16) |
| `rust`-lane удалён | в `classify_changes.py`/`detect-changes`/`ci.yaml` нет `rust`-вывода/путей/job'ов; `bootstrap`-lane сохранён | [classify_changes.py](../../scripts/ci/classify_changes.py#L156-L163), [detect-changes](../../.github/actions/detect-changes/action.yml#L48-L65) |
| Desktop-стадии installer-E2E | `installer-script+desktop`/`desktop-installer` отсутствуют в матрице и драйверах; source-ноги остались | `grep -RIn 'installer-script+desktop' scripts tests/install .github/workflows` (пусто вне KNOWN_FAILURES/README) |
| Bootstrap-installer outputs в иконках | `generate_icons.py --check`: `[ok] all 89 targets generate and pass structural checks`; bootstrap-installer путей нет | `scripts/generate_icons.py`, `.venv/bin/python scripts/generate_icons.py --check` |
| Архитектура не менялась | предыдущий снимок не редактировался; `diagram.json`/`diagram.html` совпадают по sha256 с `2026-11-08-architecture/` | `shasum -a 256 history/2026-11-08-architecture/* history/2026-11-08-removal-step-1-installer/*` |

## Приёмка

- `validate`: **9/9** проверок, `showcase`, ошибок **0**, предупреждений **0**.
- `deliver`: спецификация `sha256:1e9bf039283f5ff9361fd53d5c7789f84925fb8508b65a555fb326acd031a0f6`
  (8 436 байт); артефакт `sha256:ce692b81bef4c7d97030984583be71578daa9b81a22593307b32997f806a58fd`
  (824 178 байт). Это те же байты, что в снимке `2026-11-08-architecture`, — диаграмма
  действительно не менялась.
- `visual-check`: `pass`, 4/4 вьюпорта — 1440×900, 1600×1000, 1920×1080, 2048×1320;
  `scrollWidth`/`scrollHeight` в пределах вьюпорта (`overflowX`/`overflowY` = false).
- `screenshot-light-2048x1320.png`:
  `sha256:d33f5d2bc122399a63593cbb2bf000cc18eb1ac54bb6d54c17f7da832d05a518`.
- Archify: локальный CLI `~/.agents/skills/archify/bin/archify.mjs` (Node 26.8.1).
  На этой машине Chrome поднимается только с `ARCHIFY_CHROME_NO_SANDBOX=1` (sandbox Chrome
  не стартует под хост-обвязкой) — это окружение, а не диаграмма.

## Воспроизведение

```bash
S=history/2026-11-08-removal-step-1-installer
node ~/.agents/skills/archify/bin/archify.mjs validate architecture \
  "$S/diagram.json" --quality showcase --json
node ~/.agents/skills/archify/bin/archify.mjs deliver architecture \
  "$S/diagram.json" "$S/diagram.html" --quality showcase --json
# на обычной машине без --no-sandbox; здесь Chrome запускается только так:
ARCHIFY_CHROME_NO_SANDBOX=1 node ~/.agents/skills/archify/bin/archify.mjs visual-check \
  "$S/diagram.html" --json
shasum -a 256 "$S/diagram.json" "$S/diagram.html" "$S/screenshot-light-2048x1320.png"
```

## Известные упрощения

- Схема не изменилась намеренно: установщик в неё не входит. Это не пропуск проверки —
  `NOTES.md` фиксирует удалённые поверхности и их факты-источники.
- В дереве осознанно оставлены ссылки на удалённый GUI-установщик, принадлежащие следующим
  этапам плана: `scripts/releases/stamping.py` и `tests/scripts/test_version_stamping.py`
  (Tauri/Cargo stamping — этап 2), `.github/workflows/stable-release.yml` (`bootstrap-version`
  lane и packaged-приёмка — этап 2), `hermes_cli/update_lock.py` (update-ветки — этап 5),
  `tests/install/macos-desktop-e2e.sh`/`drive-dmg-install.sh` и desktop-маршруты
  `windows-e2e.ps1` (desktop E2E — этап 2/3), `tests/install/README.md` и
  `tests/install/e2e-assets/known-failures.json` (документация/тесты — этап 9/10).
  `pnpm-lock.yaml` сохраняет importer `apps/bootstrap-installer` до перегенерации lock-файла
  на этапе 2/3 (тяжёлый `pnpm install` в этом этапе запрещён).
- Windows-тесты установщика (`platforms("windows")`) на этой macOS-машине не запускались;
  PowerShell-парсинг `install.ps1` — тоже (нет `pwsh`). Изменения проверены статически и
  Linux-тестами; Windows-прогон остаётся за CI (`tests-os`, `install-script.yml`).
- `tests/ci/test_prompt_surface.py`, `test_update_ci_routing.py`,
  `test_update_transitive_routing.py`, `test_plugin_validate_action.py` на этой машине
  падают по окружению: первый подменяет `sys.platform` на linux и импортирует linux
  sysconfigdata (Linux-only тест), остальные реплеят CI-шаги под bash 3.2 (нет `mapfile`)
  или упираются в сетевой таймаут; к изменениям этапа отношения не имеют.
- `meta.locale` не задан: Archify поддерживает только `en` и `zh-CN`, поэтому фиксированный
  UI вьюера и `<html lang>` остаются английскими; содержимое схемы — на русском.
