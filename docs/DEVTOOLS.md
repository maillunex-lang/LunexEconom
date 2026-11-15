# Developer world editor (ChatGPT9, implementation in progress)

> **Not ready for deployment.** Building operations are partially implemented; Android device integration and isolated PostgreSQL CI have not been confirmed green.

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
- Road removal and road-add undo now run a cardinal graph connectivity check over all base and dynamic roads. The check rejects splits of any surviving connected component and loss of every road entrance to an existing building. Dead-end trimming and removal with an alternate route remain allowed. Building relocation checks zoning and requires a destination adjacent to a road. It does not yet require that road to connect to a particular city's road component.
- Validate all economic dependencies of demolition and restoration, especially contracts, loans and deposits.
- Test PostgreSQL with isolated `lunex_ci` only; never use production DB.
- Run Android landscape/safe-area, touch and editor UI integration tests on an actual device.
- Owner-controlled manual-cell exclusion in `citygen` is still pending and is outside this branch's allowed files.

## Road editing and undo (experimental)

`POST /dev/roads` with `{ "request_id": "<uuid>", "operation": "add", "cells": [[11,12]] }` adds dynamic roads. `operation: "remove"` deletes them. Developer role is validated against the **authentication database**, not the separate world database. Each operation is capped at 25 cells and produces chunk version events. Existing buildings, base roads and water are protected. `POST /dev/undo` with `{ "request_id": "<uuid>" }` reverts the latest eligible terrain or road action. Do not deploy until concurrent editing safety is verified.

## Validation record

Isolated development workspace, 2026-11-15: `python -m unittest discover -p 'test_*.py' -q` returned **559 tests, OK (56 skipped)** with SQLite engine before this documentation update. Godot 4.7.2 headless editor load exited with code 0. The PostgreSQL `lunex_ci` workflow has been committed but has **not been confirmed green**. No production database was accessed.