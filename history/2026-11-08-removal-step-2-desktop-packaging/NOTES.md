# Снимок 2026-11-08 — удаление desktop-упаковки, каналов релиза и desktop-CI

- **Дата:** 2026-11-08
- **Репозиторий:** `Zafir-Development/zafir-agent` (Hermes Agent)
- **Тип диаграммы:** `architecture` (Archify, `quality_profile: showcase`)
- **Язык:** русский; UI вьюера — английский (см. «Известные упрощения»)
- **База `main`:** `b309d5015fc156815f1ae8074db5688f7dee1c24`
- **Ревизия ветки `trim-core-surfaces` (кодовый коммит):** `2e879d4446dd49a3fc4d247792d7914d3da98674`
  (`trim-core-surfaces@2e879d4446`, `refactor(release): remove desktop packaging, release channels, and desktop CI`;
  241 файл, +1242/−42 605)
- **Предыдущий снимок:** `../2026-11-08-removal-step-1-installer/` — не изменялся (append-only).

## Что изменилось

Этап 2 плана `docs/removal/02-removal-plan.md` (§ Step 2, строки 104–142): прекращено производство
и публикация desktop-артефактов — удалены desktop-упаковка и сборка бандлов, каналы релиза
desktop-артефактов, desktop-CI и desktop-update. Source-релизы (теги, source-артефакты, заметки)
сохранены. Архитектура рантайма (CLI → gateway → ядро агента → LLM-провайдеры и `state.db`)
не менялась.

- **Desktop-CI удалён.** Удалены `.github/workflows/desktop-bundled-release.yml` (−2 489 строк),
  `desktop-bundle-smoke.yml`, `e2e-desktop.yml`, `e2e-desktop-core.yml`, `e2e-desktop-update.yml`,
  `windows-desktop-attach-e2e.yml`, `windows-bundle-sdk.yml`, `.github/actions/desktop-build-cache/**`
  и python-драйверы `scripts/ci/desktop_build_cache.py`, `scripts/ci/desktop_commands.py`.
  В `.github/` не осталось workflow, собирающего/подписывающего/публикующего DMG/MSIX/AppImage/Store.
- **Source-релизы.** `stable-release.yml` (215 строк) — 11 job'ов от `admit` до `complete`; desktop-
  job'ов (`candidates`/`transitions`/`publish-bundles`/`bootstrap-version`/`packaged`) нет, секреты —
  только DockerHub. `canary-release.yml` — только `tag` + `prune` source-канарейки;
  `stable-release-publication.yml` — один `reconcile`-job, вызывающий sequencer. Отсутствие desktop/R2
  machinery пиннится тестом `tests/ci/test_stable_release_graph.py`.
- **Lanes.** `scripts/releases/lanes.py`: 7 source-lane'ов (`docker`, `ci`, `nix`, `docker-tests`,
  `pm-bundle`, `windows-live`, `install-e2e`), `LANES_REVISION = 3`; claim (`entrypoint.py`) пишет
  `lanesRevision`, поэтому claim'ы старого desktop-пайплайна отвергаются, а не переводятся.
- **Desktop-модули релиза удалены:** `channels.py`, `channel_build.py`, `channel_publish.py`,
  `channel_releases.py`, `channel_disposable.py`, `store.py`, `handoff.py`, `desktop_targets.py`,
  `job_groups.py`, `stamping.py`, `commit_build.py`, `bundle_env.py`, `dispatch_log.py` и
  `scripts/render-builds-table.py`. Tauri/Cargo stamping заменён nix-only
  `scripts/releases/nix_stamp.py`; `stable.py`/`sequencer.py`/`versioning.py` стали source-only
  (квитанция всегда `candidateManifestSha256: null`).
- **Упаковка и сборка удалены:** `scripts/build-bundle.sh/.ps1`, `scripts/build/{desktop,desktop-reuse,
  electron-runtime,webapp}.mjs`, `scripts/msix-shared.mjs`, `scripts/stage-msixbundle.mjs`,
  `scripts/bundle-store-msixbundle.mjs`, `scripts/desktop-update/**` + `scripts/desktop-update.ps1`,
  desktop-модули `scripts/bundles/` (`desktop.py`, `desktop_inputs.py`, `desktop_prepare.py`,
  `dmgbuild_diagnostics.py`, `msix_names.py`, `set_dmg_volume_icon.sh`, `release_artifacts.py`,
  `channel_artifacts.py`), `evals/update_streaming/**`. Общий toolchain переименован
  `desktop_toolchain.py` → `scripts/bundles/toolchain.py`; `write_install_stamp.py` и
  `native_build.py` больше не импортируют удалённые модули.
- **Иконки.** `scripts/generate_icons.py` генерирует 12 не-desktop целей (masters + website +
  `web/public`); step `repo-guards.yml` вызывает `"$HERMES_PYTHON" -m scripts.generate_icons` и
  `--check`; `scripts/generate-icons.mjs` — обёртка. Из `js-tests.yml` убран electron-runtime step.
- **E2E.** В `install-e2e*` остались только source-ноги (`installer-script`, `hermes-update`,
  `hermes-desktop-app-update`); bundled/packaged-ноги и их inputs удалены, `bundledMatrix`/
  `packaged-app`/`open-app-update` убраны из `scripts/sandbox/generate-e2e-matrix.mjs`. Удалены
  packaged-драйверы `tests/install/` и весь `tests/scripts/desktop_update/**`.
- **Классификатор и гейты.** Из `classify_changes.py`, `.github/actions/detect-changes/action.yml`,
  `required_results.py`, `tests-os.yml` убраны lanes `e2e_desktop_core`/`e2e_desktop_update`/
  `desktop_updater`/`python_prod`; `_E2E_LANES` — только `e2e` и `e2e_upgrade`.
- `scripts/install.sh`/`install.ps1` не менялись: source-установка (9 стадий, `protocol_version` 1)
  не затронута.

**Почему диаграмма без изменений.** Desktop-упаковка, каналы релиза и desktop-CI — это инструменты
доставки, а не рантайм-архитектура: в `diagram.json` нет ни узла, ни подписи, ни связи про
сборку/подпись/публикацию артефактов, release-каналы или CI. Search по спеке
(`grep -oiE 'dmg|msix|bundle|release|channel|artifact|store|updater|workflow|packag' diagram.json`)
не даёт совпадений, поэтому менять схему нечем: `diagram.json` скопирован из предыдущего снимка как
есть, `diagram.html` пересобран тем же Archify (побайтово совпадает с прошлым артефактом), а снимок
фиксирует факт отсутствия архитектурных изменений и удалённые поверхности доставки.

## Проверка фактов

| Узел / утверждение | Проверенный факт | Источник |
|---|---|---|
| Desktop-CI workflow'ы удалены | семи файлов нет в дереве: `desktop-bundled-release.yml`, `desktop-bundle-smoke.yml`, `e2e-desktop.yml`, `e2e-desktop-core.yml`, `e2e-desktop-update.yml`, `windows-desktop-attach-e2e.yml`, `windows-bundle-sdk.yml`; нет `.github/actions/desktop-build-cache/`; удаление видно в коммите (−2 489, −257, −256, −114, −131, −111, −47 строк) | `git show --stat 2e879d4446`; `ls .github/workflows/`, `ls .github/actions/` |
| Ни один workflow не собирает desktop-артефакт | в `.github/` нет совпадений с `dmg msix appimage notariz electron-builder desktop-bundle bundled-release`, кроме `blob-size-allowlist.txt` (allowlist для `apps/desktop/packaging/dmg-volume.icns`, этап 3) | `grep -rniE 'dmg|msix|appimage|notariz|electron-builder|desktop-bundle|bundled-release' .github/`; [blob-size-allowlist.txt](../../.github/blob-size-allowlist.txt#L10-L12) |
| `stable-release.yml` — только source | 11 job'ов: `admit` (23), `ci` (59), `docker` (73), `nix` (90), `pm-bundle` (100), `windows-live` (108), `install-e2e` (116), `acceptance` (131), `publish-docker` (148), `publication` (162), `complete` (179); гейт приёмки `stable gate admit ci docker nix pm-bundle windows-live install-e2e`; секреты только `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` | [stable-release.yml](../../.github/workflows/stable-release.yml#L23-L180), [gate](../../.github/workflows/stable-release.yml#L143), [secrets](../../.github/workflows/stable-release.yml#L209-L210) |
| Запреты desktop/R2 machinery пиннятся тестом | тест перебирает 4 release-workflow'а и требует отсутствия токенов `CLOUDFLARE_R2`, `MS_STORE`, `publish-bundles`, `candidates-`, `transitions-`, `windows-packaged`, `macos-packaged`, `bootstrap-version`, `render-builds-table`, `desktop-bundled-release.yml` и др.; второй тест запрещает ссылки workflow на удалённые модули | [test_stable_release_graph.py](../../tests/ci/test_stable_release_graph.py#L120-L131), [DELETED_RELEASE_MODULES](../../tests/ci/test_stable_release_graph.py#L278-L291) |
| Канарейка и публикация — source-only | `canary-release.yml`: job'ы `tag` (28) → `release.py --canary --publish` (47) и `prune` (49) → `--prune-canaries` (64); в шапке — «A source-only canary is the annotated tag plus its published GitHub prerelease — nothing is built». `stable-release-publication.yml`: один job `reconcile` (29) → `python -m scripts.releases.sequencer` (59) | [canary-release.yml](../../.github/workflows/canary-release.yml#L6-L12), [tag](../../.github/workflows/canary-release.yml#L28-L47), [prune](../../.github/workflows/canary-release.yml#L49-L64), [stable-release-publication.yml](../../.github/workflows/stable-release-publication.yml#L29-L59) |
| Lanes — 7 source-lane'ов, `LANES_REVISION = 3` | `LANES` — ровно `docker, ci, nix, docker-tests, pm-bundle, windows-live, install-e2e`; claim пишет `lanes` и `lanesRevision`, `claim_lanes` отвергает чужую ревизию | [lanes.py](../../scripts/releases/lanes.py#L26-L33), [revision](../../scripts/releases/lanes.py#L95-L97), [claim_lanes](../../scripts/releases/lanes.py#L100-L106), [entrypoint.py](../../scripts/releases/entrypoint.py#L291-L292) |
| Lane dry-run | независимый прогон `scripts/releases/lanes.py` на Python 3: `jobs_to_run(DEFAULT)` = `{ci, docker, install-e2e, nix, pm-bundle, publish-docker, windows-live}`; `select(without={'docker'})` отключает `docker` и `publish-docker` | прогон импорта модуля (stdlib-only), `scripts/releases/lanes.py` |
| Desktop-модули релиза удалены | 13 модулей и `scripts/render-builds-table.py` отсутствуют в дереве (удаление в коммите, −3 000+ строк); `scripts/releases/` теперь: `authors`, `darwin`, `distance`, `docker`, `draft_warning`, `entrypoint`, `lanes`, `nix_stamp`, `pick_tags`, `progress`, `r2*`, `semver`, `sequencer`, `stable`, `upload_summary`, `versioning` | `git show --stat 2e879d4446`; `ls scripts/releases/` |
| Nix-stamping вместо Tauri/Cargo | новый nix-only `nix_stamp.py` переписывает `version` в `nix/hermes-agent.nix`; job `flake-check` в `nix.yml` запускает его на изолированном release-source; тест требует `nix_stamp.py --version` | [nix_stamp.py](../../scripts/releases/nix_stamp.py#L1-L7), [nix.yml](../../.github/workflows/nix.yml#L175-L182), [test](../../tests/ci/test_stable_release_graph.py#L295-L300) |
| Упаковка и сборка удалены | отсутствуют `scripts/build-bundle.sh`, `build-bundle.ps1`, `build/{desktop,desktop-reuse,electron-runtime,webapp}.mjs`, `msix-shared.mjs`, `stage-msixbundle.mjs`, `bundle-store-msixbundle.mjs`, `desktop-update/`, `desktop-update.ps1`, `bundles/{desktop,desktop_inputs,desktop_prepare,dmgbuild_diagnostics,msix_names,set_dmg_volume_icon.sh,release_artifacts,channel_artifacts}`, `evals/update_streaming/`; общий toolchain — `scripts/bundles/toolchain.py`, `bundles/` = `bytecode native native_build native_prepared payload stage toolchain` | `git show --stat 2e879d4446`; `ls scripts/bundles/`, `ls scripts/`, `ls evals/` |
| Нет импортов удалённых модулей | `native_build.py` импортирует `scripts.bundles.toolchain`; в `write_install_stamp.py` нет `desktop_prepare`/`commit_build`/`channel_request`; grep по `scripts/`, `hermes_cli/`, `tests/` не находит импортов удалённых release-модулей | [native_build.py](../../scripts/bundles/native_build.py#L30-L31), [native_build.py](../../scripts/bundles/native_build.py#L71-L72), `grep -rn …` |
| Иконки: 12 не-desktop целей | `TARGETS` — 12 записей (masters, website, `web/public/favicon.ico`), в docstring «Outputs (12 files)»; `--check` печатает `[ok] all 12 targets generate and pass structural checks`; step repo-guards запускает `"$HERMES_PYTHON" -m scripts.generate_icons` + `--check` и падает на diff | [generate_icons.py](../../scripts/generate_icons.py#L46), [TARGETS](../../scripts/generate_icons.py#L114), [check](../../scripts/generate_icons.py#L425), [repo-guards.yml](../../.github/workflows/repo-guards.yml#L807-L816) |
| js-tests без Electron | в `js-tests.yml` нет шага electron-runtime и нет desktop/bundle-упоминаний (файл урезан на 41 строку) | `grep -ni 'electron\|desktop\|bundle' .github/workflows/js-tests.yml` (пусто); `git show --stat 2e879d4446` |
| install-e2e — только source-ноги | job'ы `install-e2e.yml`: `pick-releases` (107), `generate-matrix` (171), `linux` (208), `windows` (229), `macos` (246), `leg-player` (272), `source-gate` (298), `report` (340); раннер `install-e2e-run.yml` — один job `e2e` (88); в матрице `InstallMethod = 'installer-script'`, `UpdateMethod += hermes-update, hermes-desktop-app-update`, `bundledMatrix`/`packaged-app`/`open-app-update` удалены | [install-e2e.yml](../../.github/workflows/install-e2e.yml#L107-L340), [install-e2e-run.yml](../../.github/workflows/install-e2e-run.yml#L88), [generate-e2e-matrix.mjs](../../scripts/sandbox/generate-e2e-matrix.mjs#L38-L45), [ROUTE_OSES](../../scripts/sandbox/generate-e2e-matrix.mjs#L211-L217) |
| Packaged-драйверы и тесты удалены | в `tests/install/` остались только source-инструменты (`installer-script-e2e.sh`, `windows-e2e.ps1`, `e2e-assets/`); `macos-desktop-e2e.sh`, `macos-bundled-e2e.sh`, `macos-bundle-smoke.sh`, `windows-bundled-e2e.ps1`, `windows-bundle-smoke.ps1`, `e2e-assets/drive-dmg-install.sh` отсутствуют; каталога `tests/scripts/desktop_update/` нет | `ls tests/install/`; `git show --stat 2e879d4446` |
| Классификатор и гейты без desktop | `_E2E_LANES` — только `e2e` и `e2e_upgrade`; из `detect-changes/action.yml` убраны outputs `python_prod`/`e2e_desktop_core`/`e2e_desktop_update`/`desktop_updater`; в `required_results.py` удалены `DEFERRED_JOBS`/`EXCLUDED_JOBS` и lane'ы `desktop_updater`/`e2e_desktop_update`; из `tests-os.yml` убран input и `--ignore-glob` для desktop-update тестов | [classify_changes.py](../../scripts/ci/classify_changes.py#L364-L366), [detect-changes](../../.github/actions/detect-changes/action.yml#L15-L53), [required_results.py](../../scripts/ci/required_results.py#L31-L36), `git show --stat 2e879d4446` |
| `scripts/install.sh` не менялся | `git diff b52bfece95 -- scripts/install.sh scripts/install.ps1` пуст; `stage_names` печатает те же 9 стадий, `protocol_version = 1` | `git diff`; [install.sh](../../scripts/install.sh#L490-L491), [manifest](../../scripts/install.sh#L510) |
| `python scripts/check` — зелёный | прогон этапа: «15 checks, ok», health 0 blocking/0 advisory; `_CHECKS` = 12 guards + 1 diff-guard + `ruff` + `health` = 15 | [scripts/check](../../scripts/check#L104-L121); прогон этапа |
| Targeted-наборы тестов | прогон этапа: `tests/ci` + `tests/scripts` + `tests/installation` — 148 файлов, 1 593 passed, 132 skipped, 23 падения только по окружению (bash 3.2 `mapfile`, linux-sysconfigdata, сеть, cross-worktree venv); `tests/scripts/test_release_entrypoint.py` отдельно — 64 passed | прогон этапа |
| YAML и граф релизов | прогон этапа: все 52 YAML-файла в `.github/` парсятся, `needs:`/`uses:`/`workflow_run` разрешаются (35 workflow-yml + README); в дереве ровно 35 `.github/workflows/*.yml` | прогон этапа; `ls .github/workflows/*.yml \| wc -l` |
| Архитектура не менялась | `diagram.json`, `diagram.html` и screenshot этапа побайтово совпадают с предыдущими снимками (sha256 ниже) | `shasum -a 256 history/2026-11-08-removal-step-1-installer/* history/2026-11-08-removal-step-2-desktop-packaging/*` |

## Приёмка

- `validate`: **9/9** проверок, `showcase`, ошибок **0**, предупреждений **0**
  (`compositionStatus: pass`).
- `deliver`: спецификация `sha256:1e9bf039283f5ff9361fd53d5c7789f84925fb8508b65a555fb326acd031a0f6`
  (8 436 байт); артефакт `sha256:ce692b81bef4c7d97030984583be71578daa9b81a22593307b32997f806a58fd`
  (824 178 байт). Это те же байты, что в снимках `2026-11-08-architecture` и
  `2026-11-08-removal-step-1-installer`, — диаграмма не менялась.
- `visual-check`: `pass`, 4/4 вьюпорта — 1440×900, 1600×1000, 1920×1080, 2048×1320;
  `scrollWidth`/`scrollHeight` в пределах вьюпорта (`overflowX`/`overflowY` = false);
  `containment`/`readability`/`captures`/`viewerChrome` — `pass`; скриншоты light/dark.
- Перцептивная проверка: **пройдена** по скриншотам light 2048×1320 и dark 1440×900 —
  нет обрезанных подписей, наложений узлов и карточек, читаемый порядок.
- `screenshot-light-2048x1320.png`:
  `sha256:d33f5d2bc122399a63593cbb2bf000cc18eb1ac54bb6d54c17f7da832d05a518` (побайтово равен
  скриншоту предыдущих снимков).
- Archify: локальный CLI `~/.agents/skills/archify/bin/archify.mjs` **2.17.0-dev.1**, Node 26.8.1.
  На этой машине Chrome поднимается только с `ARCHIFY_CHROME_NO_SANDBOX=1` (без него
  `visual-check` падает на `Target.getTargets: timed out after 15000ms`) — это окружение,
  а не диаграмма.
- Sidecar-файлы `visual-check` (`diagram.visual-check.*`) после проверки удалены: в снимке только
  `diagram.json`, `diagram.html`, `screenshot-light-2048x1320.png`, `NOTES.md`.

## Воспроизведение

```bash
S=history/2026-11-08-removal-step-2-desktop-packaging
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

- Схема не изменилась намеренно: упаковка, release-каналы и CI в неё не входят. Это не пропуск
  проверки — `NOTES.md` фиксирует удалённые поверхности доставки и их факты-источники.
- Диаграмма показывает рантайм-топологию на момент этапа и намеренно не отражает шаги 3+ плана:
  узел `Desktop` (Electron + React) и путь desktop-update остаются на схеме, пока само приложение
  не удалено (этап 3); `Web-дашборд` уходит на этапе 4.
- R2-транспорт (`scripts/releases/r2.py`, `r2_scope.py`, `r2_multipart.py`, `darwin.py`) осознанно
  оставлен: его импортируют не-desktop `scripts/ci/archive_inputs.py` (подпись/скачивание
  toolchain-архивов) и `scripts/ci/setup_toolchain.py`; workflow на эти модули больше не ссылаются,
  и тест `test_no_workflow_references_a_deleted_release_module` это пиннит.
- Claim'ы старого desktop-пайплайна не переводятся: `lanes.py`/`sequencer.py` распознают
  desktop-era метаданные (`skipBundles`, `skipTests`, `includeMacosIntel`, `includeTermux`) и
  пропускают их; совместимости с прежними каналами нет (D9).
- `pm/lock.json` (dmgbuild-пины, строки 98–106) и `pnpm-lock.yaml` (importer `apps/desktop` и
  Electron-записи) остаются до этапов 3/11 — перегенерация lock-файлов в этом этапе не делалась.
- `apps/desktop/**` (включая тесты, ссылающиеся на удалённые root-скрипты), `tests/hermes_cli`,
  `tests/e2e/core`, `hermes_cli/update*`/`desktop*`, `tests/install/e2e-assets/desktop-smoke*` и
  `BUNDLED_UPDATES.md` — следующие этапы (3/5/10); docs/website — этап 9.
- PowerShell-часть (`tests/install/windows-e2e.ps1`, `scripts/windows_e2e_harness.ps1`) на этой
  macOS-машине не исполнялась (нет `pwsh`); изменения проверены статически, прогон — в CI
  (`install-e2e*`, `tests-os`).
- 23 падения в targeted-прогоне — окружение этой машины (bash 3.2 `mapfile` в
  `test_update_ci_routing`/`test_update_transitive_routing`, linux-sysconfigdata в
  `test_prompt_surface`, сеть в `test_plugin_validate_action`, cross-worktree venv в
  `test_termux_update_refusal`); к изменениям этапа отношения не имеют.
- `meta.locale` не задан: Archify поддерживает только `en` и `zh-CN`, поэтому фиксированный
  UI вьюера и `<html lang>` остаются английскими; содержимое схемы — на русском.
