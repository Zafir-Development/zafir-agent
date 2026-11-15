# Снимок 2026-11-09 — доводка этапа 2 по замечаниям приёмки: Termux SHA, D9, stable-публикация

- **Дата:** 2026-11-09
- **Репозиторий:** `Zafir-Development/zafir-agent` (Hermes Agent), PR #4
- **Тип диаграммы:** `architecture` (Archify, `quality_profile: showcase`)
- **Язык:** русский; UI вьюера — английский (см. «Известные упрощения»)
- **База `main`:** `b309d5015fc156815f1ae8074db5688f7dee1c24`
- **Предыдущий снимок:** `../2026-11-09-removal-step-2-followup/` — не изменялся (append-only);
  его `diagram.json`/`diagram.html`/screenshot скопированы в этот снимок без изменений.
- **Ревизия ветки (кодовые коммиты):** `4319b99f94..036dd82d81` — три коммита поверх
  `docs(history): snapshot 2026-11-09-removal-step-2-followup`:
  `d60a7d1b2d` (Termux SHA), `3b0d404034` (D9/sequencer), `036dd82d81` (stable-публикация);
  8 файлов, +103/−72.

## Что изменилось

Этот снимок фиксирует три замечания приёмки этапа 2. Пункты 1 и 2 — обязательные условия
приёмки; пункт 3 — унаследованный (есть и в базе) дефект stable-публикации, который мешал
подтвердить работоспособность сохранённой автоматической release-цепочки. Архитектура рантайма
(CLI → gateway → ядро агента → LLM-провайдеры и `state.db`) не менялась: затронуты только
инструменты сборки/релиза. TUI, gateway, агент, Docker/Nix и source install/update сохранены.

- **Termux: идентичность commit-сборки по SHA без release-тега.** Этап 2 удалил из
  `write_install_stamp.py` обработку `HERMES_BUILD_COMMIT`, но сохранил
  `scripts/termux/build.py --commit <SHA>`. Commit-режим `build_deb.sh` выставляет
  `HERMES_DESKTOP_VARIANT=runtime` и пустой `HERMES_PAYLOAD_TAG`, поэтому запись stamp'а
  упиралась в guard «не-bootstrap payload требует тег» и `.deb`-сборка обрывалась после
  подготовки окружения. Добавлено ровно одно tagless-исключение: `payload == "runtime"` и явно
  переданный `--commit` (полный 40-символьный lowercase-hex, не env/git-догадка, не all-zero
  fallback) при отсутствии тега. Stamp сохраняет `tag: null`, идентичность — SHA; все прочие
  не-bootstrap payload по-прежнему требуют `HERMES_PAYLOAD_TAG`. Commit-режим теперь помечает
  stamp `--source commit-build` (это читают `hermes_cli/update_contract.is_commit_build`, banner
  и update-refusal), мёртвая env-обвязка `HERMES_BUILD_COMMIT` удалена — compat-shim не
  возвращается (D9).
- **D9: desktop-era claim-совместимость удалена.** Ветка этапа 2 добавила
  `is_desktop_era_claim()`/`_DESKTOP_CLAIM_KEYS` и skip-ветку в `sequencer.discover()`, чтобы
  теги, нарезанные удалённым desktop-пайплайном, не валили source-only проход; `source_only_attempts`
  исключал их из учёта outstanding-attempts. `docs/removal` D9 прямо запрещает compatibility
  shims и migration paths, а строгий `validate_claim` уже отвергает такие claim'ы — skip скрывал
  реальную несогласованность. Предикат, skip-ветка и отдельный учёт удалены; `discover()`
  валидирует каждый claim и поднимает `<tag> metadata is invalid`; guard outstanding-attempts
  снова считается по всем refs. Тест на пропуск удалён; строгий отказ остаётся под
  `test_stable_release.py::test_a_claim_from_the_desktop_pipeline_is_refused`.
- **Stable-публикация: reconciler после успешного запуска.** Финальная job `Stable Release`
  вызывает sequencer, пока workflow ещё `in_progress`; `classify_runs()` видит `running`, план
  публикации пуст. `stable-release-publication.yml` реагировал на завершение только неуспешных
  запусков, поэтому успешный draft оставался неопубликованным до ручного dispatch. Гейт
  `workflow_run` больше не исключает `conclusion == success`: reconciler запускается после любого
  завершённого dispatch-запуска этого репозитория. Для уже опубликованного релиза он идемпотентен
  (receipt-тег и публичный release дают `published`, план пуст); failed-запуск по-прежнему
  перезапускает упавшие job'ы.

**Почему диаграмма без изменений.** Termux-упаковка, release-граф и workflow-публикация — это
доставка, а не рантайм-архитектура. В `diagram.json` нет ни узла, ни подписи, ни связи про сборку,
пакеты, CI, релиз-каналы или публикацию: поиск
`grep -oiE 'termux|deb|package|artifact|release|publish|channel|workflow|stamp|docker|nix|sequencer'
diagram.json` не даёт совпадений (единственное вхождение подстроки `arch` — слово «architecture» в
заголовке). Поэтому `diagram.json` скопирован из предыдущего снимка как есть,
`diagram.html` пересобран тем же Archify (побайтово совпадает), а снимок фиксирует факт отсутствия
архитектурных изменений и исправленные контракты доставки. Заодно снимок append-only исправляет
утверждение снимка `2026-11-08-removal-step-2-desktop-packaging`: desktop-era claim'ы больше **не
пропускаются**, а отвергаются (см. «Известные упрощения»).

## Проверка фактов

| Узел / утверждение | Проверенный факт | Источник |
|---|---|---|
| Termux commit-сборка штампуется без тега | на `HEAD` тот же вызов writer'а падает: `write_install_stamp: HERMES_DESKTOP_VARIANT=runtime requires HERMES_PAYLOAD_TAG=… (got None)`, rc=1, файл не создан; после правки — rc=0 и stamp `payload: runtime`, `tag: null`, `source: commit-build`, точный commit | `git show HEAD:scripts/write_install_stamp.py` во временном дереве; финальный вызов writer'а; [write_install_stamp.py](../../scripts/write_install_stamp.py#L226-L238) |
| Tagless-исключение узкое | `tagless_runtime` требует `payload == "runtime"` + `commit_admitted` + `commit != FALLBACK_COMMIT` + полный 40-hex + пустой тег; условие `payload != "bootstrap" and not tagless_runtime and not (tag …)` сохраняет требование тега для `bundled`/`light`/`store`/тегированного runtime | [write_install_stamp.py](../../scripts/write_install_stamp.py#L218-L241); параметризованные отказы в [test_write_install_stamp.py](../../tests/scripts/test_write_install_stamp.py#L126-L140) |
| Commit-пакет остаётся commit-build для updater'а | commit-режим выставляет `STAMP_SOURCE=commit-build`, tag/`--release-commit` — `bundle`; `--source "$STAMP_SOURCE"` в вызове stamp'а; `HERMES_BUILD_COMMIT` больше нигде не читается в этом пути | [build_deb.sh](../../scripts/termux/build_deb.sh#L39-L98), [build_deb.sh](../../scripts/termux/build_deb.sh#L196-L215), `grep -rn HERMES_BUILD_COMMIT scripts/` (только strip-list `scripts/bundles/toolchain.py` и тесты) |
| Тест воспроизводит именно вызов build_deb | subprocess writer'а с `HERMES_DESKTOP_VARIANT=runtime`, пустым `HERMES_PAYLOAD_TAG`, `--commit`, `--source commit-build`, `--distribution apt-termux --update-mechanism external`; проверены exit 0, поля stamp'а и чтение через `_stamp_version_info`; отказы: нет `--commit` (только ambient `GITHUB_SHA`), короткий, non-hex, all-zero | [test_write_install_stamp.py](../../tests/scripts/test_write_install_stamp.py#L99-L140) |
| D9: shim удалён полностью | `grep -rn "is_desktop_era_claim\|_DESKTOP_CLAIM_KEYS"` — пусто; `discover()` с прежним desktop-era claim'ом поднимает `ValueError: <tag> metadata is invalid`; тест `test_desktop_era_claims_are_skipped_not_fatal` удалён; строгий отказ по шести старым формам остаётся зелёным | [sequencer.py](../../scripts/releases/sequencer.py#L225-L283), [test_release_sequencer.py](../../tests/scripts/test_release_sequencer.py), [test_stable_release.py](../../tests/scripts/test_stable_release.py#L216-L238) |
| Outstanding-attempts снова по всем refs | `outstanding = outstanding_attempts(list(refs), lambda v: f"v{v}" in refs)` до чтения GitHub-объектов, без `source_only_*`; для невалидного мульти-ref исторического графа всё равно `ValueError` (порядок гардов изменён, поведение валидных source-only графов — нет) | [sequencer.py](../../scripts/releases/sequencer.py#L240-L248) |
| Публикация докручивается после success | гейт: `event_name != 'workflow_run'` ИЛИ (`workflow_run.event == 'workflow_dispatch'` И head repo == этот репозиторий) — `conclusion` больше не фильтруется; `push` и fork по-прежнему отклоняются; для уже опубликованного релиза sequencer идемпотентен | [stable-release-publication.yml](../../.github/workflows/stable-release-publication.yml#L11-L35), [test_stable_release_graph.py](../../tests/ci/test_stable_release_graph.py#L240-L252) |
| Тест публикации красный на старом workflow | новый тест против workflow с `conclusion != 'success'`: `1 failed, 31 passed`, падение ровно на `assert gate(... conclusion="success")` | копия теста в pristine-`HEAD` дереве, прогон верификатора |
| Python-линт зелёный | `python scripts/check --base HEAD`: 15 checks, ok; code health 6 файлов против `4319b99f94`: 0 blocking / 0 advisory | прогон этапа |
| Ruff/actionlint/shell чисто | ruff 0.15.22 (пин репозитория) по всем изменённым `.py` — `All checks passed!`; `actionlint .github/workflows/stable-release-publication.yml` — exit 0; `bash -n` и `shellcheck -x scripts/termux/build_deb.sh` — exit 0; `git diff --check` — exit 0 | прогон этапа |
| Целевые наборы зелёные | 7 файлов, **129 passed**: `test_write_install_stamp` (19), `test_termux_commit_identity` (1), `test_release_sequencer` (30), `test_stable_release` (22), `test_stable_release_graph` (32), `test_update_contract` (18), `test_commit_build_updates` (7); после финальной правки docstring повторно `test_write_install_stamp`+`test_stable_release_graph` — 51 passed | `scripts/run_tests.sh` с `HERMES_PYTHON` тестового окружения |
| Манифест установщика и E2E-матрица не задеты | `bash scripts/install.sh --manifest` — 9 source-стадий, desktop нет; `scripts/sandbox/generate-e2e-matrix.mjs` объявляет только `installer-script`/`hermes-update` | прогон этапа |

## Приёмка Archify

- `validate`: **9/9** проверок, `showcase`, `ok: true`, `compositionStatus: pass`; ошибок и
  предупреждений нет (`issues: []`).
- `deliver`: спецификация `sha256:1e9bf039283f5ff9361fd53d5c7789f84925fb8508b65a555fb326acd031a0f6`
  (8 436 байт); артефакт `sha256:ce692b81bef4c7d97030984583be71578daa9b81a22593307b32997f806a58fd`
  (824 178 байт); контрольная пересборка дала `BYTE-IDENTICAL`, побайтово совпадает с предыдущими
  снимками.
- `visual-check`: `pass`, 4/4 вьюпорта — 1440×900, 1600×1000, 1920×1080, 2048×1320;
  `scrollWidth`/`scrollHeight` в пределах вьюпорта (`overflowX`/`overflowY` = false);
  `containment`/`readability`/`viewerChrome` — `pass`; `minimumProjectedNodeTextPx` = 7.56–8.6 при
  требуемых 6. Скриншот `screenshot-light-2048x1320.png`:
  `sha256:d33f5d2bc122399a63593cbb2bf000cc18eb1ac54bb6d54c17f7da832d05a518` — побайтово равен
  скриншоту предыдущих снимков, поэтому перцептивная проверка переносится с принятого снимка.
- Sidecar-файлы `diagram.visual-check.*` после проверки удалены: в снимке только `diagram.json`,
  `diagram.html`, `screenshot-light-2048x1320.png`, `NOTES.md`.

## Воспроизведение

```bash
S=history/2026-11-09-removal-step-2-review-fixes
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

- Схема не изменилась намеренно: Termux-упаковка, release-граф и публикация в неё не входят. Это
  не пропуск проверки — таблица выше фиксирует исправленные контракты и их источники.
- Снимок append-only исправляет прежний `2026-11-08-removal-step-2-desktop-packaging/NOTES.md`:
  утверждение «desktop-era метаданные … пропускают» больше не соответствует коду — теперь они
  отвергаются (`metadata is invalid`).
- Реальная сборка `.deb` (`build_deb.sh`/`build.py --commit`) локально не запускалась: нужен
  Docker с arm64-образом `termux-docker` и подготовленный bionic-payload. Правка подтверждена
  точным воспроизведением argv/env-вызова stamp-писателя, статикой shell-скрипта и тестом.
- Тест writer'а дублирует argv `build_deb.sh` литералами (end-to-end через Docker недоступен);
  дрейф аргументов ловится ревью, а не этим тестом.
- `test_termux_update_refusal` падает на этой машине (2 из 5) не из-за диффа: `HERMES_PYTHON`
  указывает на venv внутри чужого checkout, поэтому `hermes update` вызывает
  `retarget_to_owning_install` и перезапускает `hermes_cli.main` с pytest-argv. Воспроизведено
  на pristine-`HEAD` дереве с тем же интерпретатором; это же окружение уже отмечено в снимке
  `2026-11-08-removal-step-2-desktop-packaging`.
- Полоса `tests/ci/` на этой macOS-машине: 19 падений окружения (17 — bash 3.2 без `mapfile`,
  1 — linux-sysconfigdata в `test_prompt_surface`, 1 — plugin-validator fixture); изменённый
  `test_stable_release_graph.py` зелёный. Полоса `tests/scripts/`: 2 падения
  `test_pick_release_tags` (тот же `mapfile`) и 2 — `test_termux_update_refusal` (см. выше);
  три файла упёрлись в дефолтный таймаут под параллельной нагрузкой, `test_release_entrypoint.py`
  отдельно зелёный за 90 с.
- Website-документация, описывающая desktop-каналы (`website/docs/developer-guide/stable-releases.md`),
  остаётся на этап 9 плана; этот снимок её не меняет.
- `meta.locale` не задан: Archify поддерживает только `en` и `zh-CN`, поэтому UI вьюера и
  `<html lang>` остаются английскими; содержимое схемы — на русском.
