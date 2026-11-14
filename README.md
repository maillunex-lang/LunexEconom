# Башкирия: Мёд и Нефть

Android-only, landscape, 2D-isometric economic MMO set in a procedurally generated Bashkortostan-inspired world.

**Status:** 0.1 Foundation in progress. This is not yet a playable game.

## Architecture
- Godot 4 Android client, landscape and touch-first.
- Authoritative server with modular economic subsystems.
- PostgreSQL ledger and persistent world planned; no production database deployed yet.
- One real day corresponds to one in-game month.

## Safety
Independent project. Do not modify existing BASHECO, NEXUS, other games or production services.

## Project control center
- [Полный паспорт проекта: 94 решения](docs/PROJECT_PASSPORT.md)
- [Дорожная карта 0.1–1.0 с чеклистом](docs/ROADMAP.md)
- [Журнал фактического прогресса](docs/PROGRESS.md)
- [Foundation: технические ограничения и тесты](docs/FOUNDATION.md)

**For developers and AI agents:** read passport → roadmap → progress before changing code; update progress only after real tests.

## Website and development dashboard

Public landing: https://rikagro.ru/lunexeconom/

Source: [web/](web/). Static, dependency-free HTML/CSS/JS. The roadmap is loaded from public `docs/ROADMAP.md` and commits from GitHub's public API; a built-in roadmap is used when the API is unavailable. APK download is **disabled** until a verified release is recorded in `web/release.json` with `status: published`, `version`, a real HTTPS APK `url`, and ideally `sha256`. Do not publish an unbuilt or unverified APK.

Deployment path: `/var/www/rikagro-game/lunexeconom/`, isolated from existing root landing and services. Updating GitHub files does **not** automatically deploy the website; deploy reviewed changes separately.
