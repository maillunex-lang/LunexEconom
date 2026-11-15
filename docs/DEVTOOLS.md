# Developer world editor (ChatGPT9, implementation in progress)

> **Not ready for deployment.** This document describes only the routes implemented and tested so far. Building, road, 3D UI and undo operations are NOT implemented.

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

Actions are written to `dev_actions` with an inverse snapshot and to `adm_audit`. **Undo is not yet implemented.** Terrain edits are stored server-side, but the normal server terrain planner, chunk events and Godot rendering have not yet been connected. Do not advertise them as synchronized world edits.

## Outstanding safety work

- Integrate terrain overrides into `roads.is_water` and server terrain checks without per-cell SQL.
- Integrate event/version updates, client terrain cache and rebuild of 3D chunk meshes.
- Implement developer-only building, demolition, moving and road tools, including all economic invariants.
- Implement the Godot editor, undo and full PostgreSQL/Godot CI.
- Have the owner apply the manual-cell exclusion patch to `citygen`; never edit citygen in this branch.

No production database migrations, role grants or deployment have been performed.
