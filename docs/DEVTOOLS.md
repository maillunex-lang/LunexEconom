# Developer world editor (ChatGPT9, implementation in progress)

> **Not ready for production deployment.** The temporary isolated PostgreSQL integration suite passed on Lunex, and a signed Android debug APK was exported. No physical Android device run or production-safe concurrent editing verification has been completed.

## Operator-only roles

On the server, with the appropriate isolated account database selected:

```bash
python server/accounts_admin.py grant-dev USERNAME
python server/accounts_admin.py revoke-dev USERNAME
python server/accounts_admin.py list-dev
```

Never expose these commands through HTTP. Registration and profile updates do not grant developer privileges. Developer access is checked against the current server-side role and bans for every edit. The authenticated user's own profile includes `dev`.

## Implemented API

`POST /dev/terrain` (Bearer session token; developer only):

```json
{"request_id":"c2c3ad2b-180e-4517-839c-c47e48dbd7cb","kind":"water","cells":[[1,2],[1,3]]}
```

Returns `{"request_id":"...","changed":2}`. Valid kinds: `grass`, `tree`, `water`, `clear`. Up to 25 distinct integer cells per request, coordinates within ±1000. Requests are idempotent by UUID; conflicting reuses return 409. At most 30 developer actions per minute. Non-developers receive `403 {"error":"forbidden"}`.

`GET /terrain/chunk?cx=0&cy=0` (authenticated) returns `{"cx":0,"cy":0,"edits":[{"x":1,"y":2,"kind":"water","manual":true}]}`.

Actions are written to `dev_actions` with inverse snapshots and to `adm_audit`. Undo checks current cell state and rejects conflicting subsequent road/terrain actions; full multi-operator concurrency validation remains pending. Terrain changes increment chunk versions and trigger client chunk reloads. The procedural server road planner does not yet consume manual terrain overrides consistently, so do not deploy the editor.

## Building tools (experimental)

- `POST /dev/create`: developer-only creation of city-owned **park, school, hospital**. Body: `{"request_id":"<uuid>","kind":"park","x":11,"y":12}`. Validates zones, cells, roads and water. No ledger postings. Player-owned businesses are intentionally forbidden.
- `POST /dev/move`: body `{"request_id":"<uuid>","object_id":"<id>","x":11,"y":12}`. Moves existing geometry, retaining owner and operating records; deposit-bound buildings cannot be moved.
- `POST /dev/demolish`: body `{"request_id":"<uuid>","object_id":"<id>"}`. Removes **inactive** building geometry without sale proceeds; refuses buildings registered for production or linked to deposits; saves an inverse snapshot.
- `POST /dev/undo`: reverses the latest eligible developer operation, including city creation, move and demolition, when destination cells are still available.

All routes verify the developer role against the **authentication database**, serialize world mutations using the economy world lock, apply a 30-action/minute limit, require UUID idempotency and write an audit record.

## Outstanding safety work

- Integrate manual terrain overrides into server-side road access and water checks without per-cell SQL.
- Road removal and road-add undo now run a cardinal graph connectivity check over all base and dynamic roads. The check rejects splits of any surviving connected component and loss of every road entrance to an existing building. Dead-end trimming and removal with an alternate route remain allowed. Building relocation checks zoning and requires a destination adjacent to a road. The destination road must belong to a component connected to at least one city base road; isolated roads are rejected. Large-world performance benchmarking remains pending.
- Validate all economic dependencies of demolition and restoration, especially contracts, loans and deposits.
- The three PostgreSQL integration tests passed on 2026-11-15 against a disposable, memory-limited PostgreSQL 16 container with the isolated `lunex_ci` database. The container was removed after the tests; production PostgreSQL was never used. GitHub Actions results must be checked independently.
- A signed 55 MB Android debug APK was exported and verified with `apksigner` and `aapt` on the VPS. The editor UI smoke passes 846×388, 1280×720 and 2340×1080 landscape resolutions after fixing a zero-height/off-screen editor panel. The existing Forest Glass layout and unauthenticated touch-flow smoke tests were updated to match the current UI tree. Actual Android installation and interaction on a physical device are still required.
- Owner-controlled manual-cell exclusion in `citygen` is still pending and is outside this branch's allowed files.

## Road editing and undo (experimental)

`POST /dev/roads` with `{ "request_id": "<uuid>", "operation": "add", "cells": [[11,12]] }` adds dynamic roads. `operation: "remove"` deletes them. Developer role is validated against the **authentication database**, not the separate world database. Each operation is capped at 25 cells and produces chunk version events. Existing buildings, base roads and water are protected. `POST /dev/undo` with `{ "request_id": "<uuid>" }` reverts the latest eligible terrain or road action. Do not deploy until concurrent editing safety is verified.

## Validation record

On Lunex, 2026-11-15:
- **PostgreSQL 16:** 3/3 real integration tests passed against a temporary local `lunex_ci` container. Container explicitly removed by a shell exit trap.
- **SQLite:** full Python regression suite passed after the editor and UI smoke updates with 579 tests (58 skipped).
- **Godot 4.7.2:** headless developer-editor smoke, dynamic-panel layout smoke, catalogue smoke and unauthenticated touch flow all passed on the isolated `ChatGPT9` checkout. The tests are executable with `godot --headless --path client --script res://tests/<name>.gd`.
- **Android:** build `/home/gamedev/projects/LunexEconom-chatgpt9-android-debug.apk` is generated in a separate output path, signed with the local debug keystore and verified with the Android SDK. No Android device or emulator was connected during testing, so this is not an on-device certification.

Neither the production DB, active game service, running production Docker containers, nor `main` was modified.
## Дополнение ChatGPT11: EX-14, редактор рельефа и свободные объекты

`roads.plan_access(...,overrides)` теперь принимает загруженную карту ручных правок. `terrain_rules.preload(db, ph, bounding_box)` читает их одним ограниченным прямоугольным запросом и планировщик не делает SQL по клеткам. Серверы SQLite/PostgreSQL перед строительством читают переопределения, `citygen.seed_city` пропускает `terrain_edits.manual=1` (включая вручную очищенные лоты). Android `client/world.gd::cell_kind` уже отдаёт приоритет ручным правкам; `test_terrain_parity.py` проверяет серверные правила и отсутствие генерации поверх ручных клеток. Это локальный на запрос кэш, не межтранзакционная память, поэтому редакторы не видят устаревшие данные.

`POST /dev/create` с `developer_override:true`, `owner:<player_username>`, `kind`, `x`, `y`, UUID `request_id` позволяет разработчику подарить объект из `economy.BUILD_COST` или жилое здание из `city_catalog`. Создание без платы, записывает в `dev_actions` и аудит, дороги и события карты, предприятие регистрирует в `building_ops`; жильё создаётся без операционной записи. Стандартное создание городских социальных зданий осталось неизменным. Отмена `POST /dev/undo` безопасна только до экономического оборота/изменения связей; новые дороги удаляются, когда удаление не разрушает дорожную сеть. Тест `test_devtools_ex14.py` проверяет обе категории и отмену. **Назначение только для разработчика**, не для игроков.

`POST /dev/demolish` с `developer_override:true` может удалить активное предприятие, только когда нет продукции на общем складе, активных контрактов, товарных долгов, непогашенных налогов/кредитов и заявок биржи. Сохраняется обратимый снимок `building_ops`, специализации, геометрии, привязки месторождения, стадии стройки и настроек. Удаление не меняет денежные счета (нулевой баланс проводок), освобождает право на месторождение; `undo` восстанавливает эти записи при отсутствии конфликта. Для действующих предприятий с неисполненными обязательствами возвращается 409 с причиной: нельзя терять права кредиторов/поставщиков ради редактора. Обычный снос без явного флага не поменял поведения. Перенос здания сохраняет прежний принцип: требует уже существующий связный подъезд, без скрытого строительства дорог; полноценный перенос **с автоматической прокладкой и обратимым удалением новых дорог ещё не готов**.