# Developer world editor (ChatGPT9, implementation in progress)

> **Not ready for deployment.** This document describes only the routes implemented and tested so far. Building operations are NOT implemented; road/terrain tools and basic undo exist, but require integration validation.

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

Actions are written to `dev_actions` with an inverse snapshot and to `adm_audit`. **Undo supports terrain and dynamic roads, but does not yet protect against concurrent edits by other operators.** Terrain edits are stored server-side, but the normal server terrain planner, chunk events and Godot rendering have not yet been connected. Do not advertise them as synchronized world edits.

## Outstanding safety work

- Integrate terrain overrides into `roads.is_water` and server terrain checks without per-cell SQL.
- Integrate event/version updates, client terrain cache and rebuild of 3D chunk meshes.
- Implement developer-only building, demolition and moving tools, including all economic invariants. Road add/remove exists through `POST /dev/roads` and Godot editor, but requires further conflict testing.
- Complete the Godot editor for buildings, strengthen undo history and run the PostgreSQL CI workflow. SQLite regression and Godot headless project load passed locally.
- Have the owner apply the manual-cell exclusion patch to `citygen`; never edit citygen in this branch.

No production database migrations, role grants or deployment have been performed.

## Road editing and undo (experimental)

`POST /dev/roads` with `{ "request_id": "<uuid>", "operation": "add", "cells": [[11,12]] }` adds dynamic roads. `operation: "remove"` deletes them. Developer role is validated against the **authentication database**, not the separate world database. Each operation is capped at 25 cells and produces chunk version events. Existing buildings, base roads and water are protected. `POST /dev/undo` with `{ "request_id": "<uuid>" }` reverts the latest eligible terrain or road action. Do not deploy until concurrent editing safety is verified.

## Validation record

Isolated development workspace, 2026-11-15: `python -m unittest discover -p 'test_*.py' -q` returned **553 tests, OK (56 skipped)** with SQLite engine. Godot 4.7.2 headless editor load exited with code 0. The PostgreSQL `lunex_ci` workflow has been committed but has **not been confirmed green**. No production database was accessed.
