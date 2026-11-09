# Журнал изменений схемы Hermes Agent

Новые записи добавляются сверху. Формат: дата · снимок · ревизия `master` · суть этапа.

| Дата | Снимок | Ревизия `master` | Что изменилось |
|---|---|---|---|
| 2026-11-08 | [2026-11-08-removal-step-2-desktop-packaging](./2026-11-08-removal-step-2-desktop-packaging/NOTES.md) | База `main` — `b309d5015f`; ветка `trim-core-surfaces@2e879d4446` (см. NOTES) | Удалены desktop-упаковка (DMG/MSIX/AppImage/Store), каналы релиза desktop-артефактов, desktop-CI и `desktop-update`; source-релизы сохранены. Архитектура рантайма не менялась, диаграмма скопирована без изменений. |
| 2026-11-08 | [2026-11-08-removal-step-1-installer](./2026-11-08-removal-step-1-installer/NOTES.md) | База `main` — `b309d5015f`; ветка `trim-core-surfaces@1463d81269` (см. NOTES) | Удалён GUI-установщик Hermes-Setup (`apps/bootstrap-installer`), desktop-стадии и флаги `install.sh`/`install.ps1`, `-ProtocolVersion`, Rust/rust-tests lane и desktop-стадии installer-E2E; архитектура рантайма не менялась, диаграмма скопирована без изменений. |
| 2026-11-08 | [2026-11-08-architecture](./2026-11-08-architecture/NOTES.md) | `8d7061f1a74980a7549356a4e5e57b603475ddf0` | Первый снимок схемы работы: интерфейсы (CLI, TUI, Desktop, веб-дашборд, IDE/API), gateway-процесс с очередью допуска и адаптерами платформ, ядро агента, инструменты, `state.db`, LLM-провайдеры. При перепроверке исправлена формулировка владельца gateway (один на хост, а не на профиль) и добавлен узел Cron/фоновых задач. |
