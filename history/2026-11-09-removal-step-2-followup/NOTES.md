# Снимок 2026-11-09 — доводка этапа 2: Docker/Nix графы, desktop-CI и source-canary

- **Дата:** 2026-11-09
- **Репозиторий:** `Zafir-Development/zafir-agent` (Hermes Agent), PR #4
- **Тип диаграммы:** `architecture` (Archify, `quality_profile: showcase`)
- **Язык:** русский; UI вьюера — английский (см. «Известные упрощения»)
- **База `main`:** `b309d5015fc156815f1ae8074db5688f7dee1c24`
- **Предыдущий снимок этапа 2:** `../2026-11-08-removal-step-2-desktop-packaging/` — не изменялся
  (append-only); его диаграмма скопирована в этот снимок без изменений.
- **Ревизия ветки (кодовые коммиты):**
  `a3d31668d99e14726183725a8a8818919265f7d0..a81424e5cb` — четыре коммита поверх HEAD PR #4:
  `70833fa665` (docker), `d0848a819a` (nix), `bd6a13f934` (ci/e2e), `a81424e5cb` (canary);
  68 файлов, +481/−4 881.

## Что изменилось

Этот снимок фиксирует доводку этапа 2 (`docs/removal/02-removal-plan.md`) по замечаниям к PR #4:
этап 2 удалил desktop-упаковку, но оставил в дереве потребителей удалённых сборщиков. Замечание 1
(удалённая Stage-Complete) исправляется отдельным PR и сюда не входит; этот снимок фиксирует только
оставшиеся четыре контракта. Архитектура рантайма (CLI → gateway → ядро агента → LLM-провайдеры и
`state.db`) не менялась. TUI, dashboard, Docker/Nix-пакеты, source install/update и source-релизы
сохранены; desktop-приложение (`apps/desktop`) остаётся до этапа 3.

- **Docker build graph.** Удалены `webapp_build`-стадия, её `COPY --from=webapp_build
  .../dist-webapp` и `COPY scripts/build/electron-runtime.mjs` (файл удалён этапом 2). `.dockerignore`
  больше не втягивает `apps/desktop` в контекст сборки. Сохранены стадии `icons`, `frontend_build`
  (TUI + dashboard), `python_deps`, `runtime` и их продукты. Мёртвый `tests/docker/test_webapp_bundle.py`
  удалён; вместо него — статический контракт build-графа `tests/docker/test_dockerfile_build_context.py`
  (каждый COPY-источник существует; каждый `COPY --from=` называет более раннюю стадию), который
  работает без Docker-демона и падает на прежнем HEAD.
- **Nix build graph.** Удалены `nix/desktop.nix`, `nix/webapp.nix` и `nix/tests/desktop-backend.py`.
  Из `nix/hermes-agent.nix` убраны `hermesWebapp`/`hermesDesktop`, `electron`, `frontends.webapp` и
  devenv `finalAttrs` (существовал только для desktop-обёртки); из `nix/packages.nix` — outputs
  `webapp`/`desktop`. Из `nix/checks.nix` убраны проверки `home-manager-desktop`,
  `home-manager-desktop-standalone` и `desktop-backend`, а `frontend-icons` перенацелен на иконку
  dashboard; из `nix/homeManagerModules.nix`/`nix/moduleCommon.nix` — опции и launcher-wiring
  `programs.hermes-agent.desktop.*`. `nix/icons.nix` больше не требует удалённый DMG-арт,
  `nix/lib.nix` собирает только `.#tui .#web`; `#tui`, `#web`, агент и source-модули сохранены.
  Это минимально необходимая часть Nix-cleanup из этапа 3 — сам `apps/desktop` не удалялся.
- **Desktop-CI и desktop install/update E2E.** `js-tests` через
  `.github/scripts/run-workspace-checks.mjs` больше не выбирает packaging/update-юниты desktop:
  `apps/desktop/package.json` оставляет только `check:lint` и `check:test:ui`, скрипты
  build/pack/dist/payload/update:repro/test-desktop/electron-builder удалены. В
  `scripts/sandbox/generate-e2e-matrix.mjs` `UpdateMethod` — только `installer-script` и
  `hermes-update`: удалены `hermes-desktop-app-update`, аннотация тегов и pre-desktop-пропуски,
  обновлены три run-workflow, `install-e2e.yml`, README и классификатор. Удалены app-update-ветки
  обоих драйверов, desktop-chat/launch-capture фикстуры, их tests-js и Python-тесты, desktop-правила
  known-failures. Source-маршруты `installer-script`/`hermes-update` и обязательные release-гейты
  (`source-gate`, required-results lanes, launcher self-lock) сохранены.
- **Source-canary.** `scripts/release.py --canary` публикует канарейку как GitHub prerelease, но
  `hermes_cli/source_releases.py` продолжал разрешать канал `canary` через R2 (`_resolve_channel`).
  Теперь `canary` идёт через существующий GitHub-resolver: самый новый опубликованный non-draft
  prerelease с каноническим тегом `vX.Y.Z+canary.<UTC>` текущего репозитория, с проверкой точного
  commit SHA из GitHub и совпадения тега на `origin`. Ветка R2-указателя для canary удалена
  (у stable указатель остался), класс `_BuildMetadata` удалён. Добавлен поведенческий тест:
  при запрете любых R2-чтений и при наличии draft/неподходящего тега выше квитанции source-updater
  проверяет и применяет опубликованный GitHub-canary.
- **Прочее.** `tests-js/generate-icons.test.mjs` проверяет сохранённые non-desktop выходы иконок
  (`assets/icon-master.svg`, `web/public/favicon.ico`) вместо удалённой desktop-иконки; исправлен
  преждевременный неиспользуемый импорт в `tests-js/product-builders.test.mjs`; удалён мёртвый
  `scripts/launch_capture_probe.sh`; в `.github/actionlint.yaml` объявлен существующий runner-label
  `windows-latest-32-core` (снимает преждевременное замечание actionlint).

**Почему диаграмма без изменений.** Docker/Nix build-графы, CI, known-failures и способ разрешения
source-canary — это инструменты доставки, а не рантайм-архитектура. В `diagram.json` нет ни узла,
ни подписи, ни связи про сборку, CI, релиз-каналы или Nix/Docker: поиск
(`grep -oiE 'dmg|msix|bundle|release|channel|artifact|store|updater|workflow|packag|docker|nix|canary'
diagram.json`) не даёт совпадений. Поэтому `diagram.json` скопирован из предыдущего снимка как есть,
`diagram.html` пересобран тем же Archify (побайтово совпадает с прошлым артефактом), а снимок
фиксирует факт отсутствия архитектурных изменений и исправленные контракты доставки.

## Проверка фактов

| Узел / утверждение | Проверенный факт | Источник |
|---|---|---|
| Dockerfile не ссылается на удалённые сборщики | на прежнем HEAD 7 совпадений `electron-runtime\|webapp_build\|build-webapp\|dist-webapp`; после — 0; стадии: `sqlite_build, runtime_base, python_deps, icons, frontend_build, runtime` | `git show a3d31668d9:Dockerfile \| grep -nE ...`; `grep -nE ... Dockerfile`; [Dockerfile](../../Dockerfile#L317-L343) |
| Docker build-граф проверяется без демона | `tests/docker/test_dockerfile_build_context.py`: 2 теста; на прежнем HEAD падает (`line 327: scripts/build/electron-runtime.mjs`), после — 2 passed; `tests/docker/conftest.py` пропускает только тесты, которым нужен `built_image` | `scripts/run_tests.sh tests/docker/test_dockerfile_build_context.py`; [test](../../tests/docker/test_dockerfile_build_context.py#L1-L133) |
| `.dockerignore` не тянет desktop в контекст | нет `!apps/desktop/**` и `dist-webapp`; сохранён `!apps/shared/**` (workspace-зависимость `web`) | [.dockerignore](../../.dockerignore#L80-L86) |
| Nix не ссылается на удалённые файлы/outputs | `grep -rnE "hermesDesktop\|hermesWebapp\|#desktop\|#webapp\|desktop\.nix\|webapp\.nix\|desktop-backend\|scripts/build/(desktop\|webapp)\.mjs" nix/ .github/workflows/nix.yml` — пусто; `nix/desktop.nix`, `nix/webapp.nix`, `nix/tests/desktop-backend.py` отсутствуют | `git show a3d31668d9:nix/hermes-agent.nix` (8 совпадений до правки); `grep -rniE 'desktop\|webapp' nix/` — только 2 комментария про ещё существующий `apps/desktop` |
| Nix сохраняет TUI/dashboard/агент | `nix/packages.nix` — `tui`, `web`, `agent`, `minimal`, `messaging`, `sandbox`, pm-пакеты; `agentInputs.frontends = { tui, web }`; `nix/lib.nix` собирает `.#tui .#web`; проверки TUI/web/agent/module остались | [packages.nix](../../nix/packages.nix#L93-L104), [hermes-agent.nix](../../nix/hermes-agent.nix#L223-L226), [checks.nix](../../nix/checks.nix#L215-L230) |
| Desktop-опции Nix удалены согласованно | нет `programs.hermes-agent.desktop.*`; удалены `desktopPackage`/`desktopEnvironment`/`desktopRun`/`desktopUsesService`; non-desktop backend/service-опции сохранены | [homeManagerModules.nix](../../nix/homeManagerModules.nix#L154-L240), [moduleCommon.nix](../../nix/moduleCommon.nix#L620-L650) |
| js-tests не выбирает packaging/update | HEAD: 9 юнитов, включая `apps/desktop :: check:test:desktop:all`/`check:test:desktop:platforms`; после: 7 юнитов, у `apps/desktop` только `check:lint`, `check:test:ui` | `node .github/scripts/run-workspace-checks.mjs --list` на обоих деревьях |
| install-E2E-матрица без desktop-маршрутов | HEAD: 6 ног на ОС, среди `update_method` — `hermes-desktop-app-update`, есть `tag_has_desktop`; после: 4 ноги на ОС, только `installer-script`/`hermes-update`, `tag_has_desktop` отсутствует | `node scripts/sandbox/generate-e2e-matrix.mjs --tags '[{"ref":"v2026.8.3","desktop":true}]'` (HEAD) / `--tags '["v2026.8.3"]'` (после) |
| Source-маршруты и гейты сохранены | `install-e2e.yml` сохраняет `source-gate` (падает на пустой матрице и провале любой source-ноги); `stable-release.yml` по-прежнему требует lane `install-e2e`; `required_results.py` не изменён; known-failures сохраняет правило launcher self-lock | [install-e2e.yml](../../.github/workflows/install-e2e.yml#L280-L320), `git diff a3d31668d9..a81424e5cb -- scripts/ci/required_results.py` (пусто) |
| Canary разрешается без R2 | новый тест `test_published_github_canary_reaches_the_source_updater_without_r2` падает на `a3d31668d9` (`AssertionError: canary must not read an R2 channel record or pointer` в `_resolve_source_target`) и проходит после: check → apply на точный commit GitHub-prerelease; draft и non-prerelease теги выше квитанции пропускаются | `scripts/run_tests.sh tests/hermes_cli/test_source_release_channels.py`; [source_releases.py](../../hermes_cli/source_releases.py#L143-L220) |
| Точный SHA и origin-тег по-прежнему проверяются | `_resolve_release` сверяет `sha` из `/commits/<tag>` с `ls-remote --tags origin refs/tags/<tag>^{}`; `_published` требует `draft is False` и `prerelease is (channel == "canary")`, `_valid_tag` — канонический `is_canary_tag` | [source_releases.py](../../hermes_cli/source_releases.py#L289-L380) |
| R2-указатель canary удалён | `_release_pointer()` читает только `releases/stable/release-candidates.json`; `_BuildMetadata`/`releases/canary/index.html` отсутствуют; stable по-прежнему может читать свой pointer | [source_releases.py](../../hermes_cli/source_releases.py#L326-L360) |
| Python-линт зелёный | `python scripts/check` на итоговом дереве: 15 checks, ok; health 0 blocking / 0 advisory (51 файл против `b309d5015f`) | прогон этапа |
| Workflow-lint зелёный | `actionlint -config-file .github/actionlint.yaml` на всех изменённых workflow — exit 0 | прогон этапа |
| Python-наборы | 58 файлов, 638 passed, 89 skipped; 18 падений только окружения этой macOS-машины: 17 в `tests/ci/test_update_*_routing.py` (bash 3.2 без `mapfile`), 1 в `tests/ci/test_prompt_surface.py` (linux-sysconfigdata у pinned Python); `tests/ci/test_plugin_validate_action.py` — flaky по таймауту git-реплея, прошёл на retry; целевые `tests/scripts/test_source_driver.py`, `test_agent_build.py`, `test_source_build_env.py`, `tests/scripts/install/`, `tests/docker/test_dockerfile_build_context.py`, canary-тесты — зелёные | `scripts/run_tests.sh tests/ci/ tests/scripts/test_source_build_env.py tests/scripts/test_source_driver.py tests/scripts/test_agent_build.py tests/scripts/install/ tests/hermes_cli/test_source_release_channels.py tests/hermes_cli/test_source_channel_integration.py tests/docker/test_dockerfile_build_context.py` |
| JS-наборы | `tests-js`: typecheck PASS, eslint PASS; целевые vitest 4 файла / 20 тестов PASS; полный vitest — 111/114 passed. 3 падения: 2 — преждевременная macOS-канонизация `/private/var` vs `/var` в `tests-js/product-builders.test.mjs` (воспроизведены на `a3d31668d9`), 1 — таймаут web-build под параллельной нагрузкой (тот же файл отдельно: 9 passed, те же 2 преждexisting падения) | `vitest run` в `tests-js`; воспроизведение на detached HEAD-worktree |
| Архитектура не менялась | `diagram.json`, `diagram.html` и screenshot побайтово совпадают с предыдущими снимками (sha256 ниже) | `shasum -a 256 history/2026-11-08-removal-step-2-desktop-packaging/* history/2026-11-09-removal-step-2-followup/*` |

## Приёмка

- `validate`: **9/9** проверок, `showcase`, ошибок **0**, предупреждений **0**
  (`compositionStatus: pass`).
- `deliver`: спецификация `sha256:1e9bf039283f5ff9361fd53d5c7789f84925fb8508b65a555fb326acd031a0f6`
  (8 436 байт); артефакт `sha256:ce692b81bef4c7d97030984583be71578daa9b81a22593307b32997f806a58fd`
  (824 178 байт) — побайтово совпадает с предыдущими снимками; контрольная пересборка дала
  `BYTE-IDENTICAL`.
- `visual-check`: `pass`, 4/4 вьюпорта — 1440×900, 1600×1000, 1920×1080, 2048×1320;
  `scrollWidth`/`scrollHeight` в пределах вьюпорта (`overflowX`/`overflowY` = false);
  `containment`/`readability`/`viewerChrome` — `pass`; `minimumProjectedNodeTextPx` ≥ 7.56 при
  требуемых 6. Скриншот `screenshot-light-2048x1320.png`:
  `sha256:d33f5d2bc122399a63593cbb2bf000cc18eb1ac54bb6d54c17f7da832d05a518` — побайтово равен
  скриншоту предыдущих снимков, поэтому перцептивная проверка (нет обрезанных подписей, наложений
  и нечитаемых зон) переносится с принятого снимка без изменений.
- Archify: локальный CLI `~/.agents/skills/archify/bin/archify.mjs`, Node 26.8.1; Chrome поднимается
  с `ARCHIFY_CHROME_NO_SANDBOX=1` (окружение этой машины, не диаграмма). Sidecar-файлы
  `diagram.visual-check.*` после проверки удалены: в снимке только `diagram.json`, `diagram.html`,
  `screenshot-light-2048x1320.png`, `NOTES.md`.

## Воспроизведение

```bash
S=history/2026-11-09-removal-step-2-followup
node ~/.agents/skills/archify/bin/archify.mjs validate architecture \
  "$S/diagram.json" --quality showcase --json
OUT="$(mktemp -d)/diagram.html"
node ~/.agents/skills/archify/bin/archify.mjs deliver architecture \
  "$S/diagram.json" "$OUT" --quality showcase --json
cmp "$OUT" "$S/diagram.html"
ARCHIFY_CHROME_NO_SANDBOX=1 node ~/.agents/skills/archify/bin/archify.mjs visual-check \
  "$S/diagram.html" --json
shasum -a 256 "$S/diagram.json" "$S/diagram.html" "$S/screenshot-light-2048x1320.png"
```

## Известные упрощения

- Схема не изменилась намеренно: build-графы, CI, known-failures и разрешение канала canary в неё
  не входят. Это не пропуск проверки — таблица выше фиксирует исправленные контракты и их источники.
- Узел `Desktop` (Electron + React) остаётся на схеме, пока `apps/desktop` не удалён (этап 3);
  `Web-дашборд` уходит на этапе 4. Снимок отражает рантайм этапа 2.
- Реальный `docker build` и `nix flake check`/`nix eval` на этой машине **не запускались**:
  Docker-демон не отвечает (`docker info` не подключается), `nix`/`/nix` отсутствуют. Docker-граф
  проверен статическим контрактом построения образа (COPY-источники и стадии, без демона), Nix —
  статическим аудитом ссылок/сбалансированности и `py_compile` тестового фикстура; реальная сборка
  подтверждается CI-полосами `docker.yml` и `nix.yml`.
- `apps/desktop/node_modules` в этом окружении не установлены, поэтому `check:lint`/`check:test:ui`
  приложения не исполнялись локально; снят только тот `tsc`-проход, которому нужен удалённый
  `scripts/msix-shared.mjs`. Реальную проверку даст `js-tests`.
- `pwsh` на машине нет: правки `tests/install/windows-e2e.ps1`, `scripts/windows_e2e_harness.ps1` и
  `tests/install/e2e-assets/journey-mock-windows.ps1` проверены структурно и через `bash -n`/AST-харнесс;
  исполнение — в CI (`install-e2e*`, `tests-os`).
- Документация, описывающая удалённые поверхности, остаётся на этап 9:
  `website/docs/getting-started/nix-setup.md` всё ещё упоминает `#desktop`/`#webapp` и
  `programs.hermes-agent.desktop.*`, `website/docs/developer-guide/stable-releases.md` — R2-канарейку и
  desktop-сборки; ссылки на удалённый `tests/install/BUNDLED_UPDATES.md` в website/docs и
  `apps/desktop/BUILDING.md`. Это осознанно не расширяется до этапа 9.
- `apps/desktop/scripts/build-webapp.mjs` и `hermes_cli/source_build.py`/`main_desktop.py` ещё
  ссылаются на удалённые сборщики; это этапы 3/5, не этап 2 (их вызовы не активны в CI). Лишние
  desktop-тесты внутри `apps/desktop` удалит этап 3 вместе с приложением.
- 18 падений Python и 3 падения JS — окружение этой macOS-машины (bash 3.2 `mapfile`,
  linux-sysconfigdata, macOS realpath `/private/var`, таймауты под нагрузкой); на `a3d31668d9`
  realpath-падения воспроизводятся, остальные перечислены в таблице. К изменениям этапа они
  отношения не имеют.
- `meta.locale` не задан: Archify поддерживает только `en` и `zh-CN`, поэтому UI вьюера и
  `<html lang>` остаются английскими; содержимое схемы — на русском.
