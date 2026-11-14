# LunexEconom dedicated server on VPS (alpha)

## Production topology
- Public HTTPS: `https://rikagro.ru/lunexeconom/api/` (existing nginx, no new public port).
- Dedicated loopback service: `lunexeconom-game.service`, `127.0.0.1:18767`, memory limit 192 MB.
- Existing `lunexeconom-foundation.service` at `127.0.0.1:18761` is retained and untouched.
- Server code: `server/game_server.py`, `server/auth.py`.
- Runtime: `/home/gamedev/projects/LunexEconom-server/`.
- User accounts: `/home/gamedev/projects/LunexEconom-runtime/accounts.sqlite3` (shared with legacy auth endpoint).
- World DB: `/home/gamedev/projects/LunexEconom-server/world.sqlite3`.
- Nightly backup timer: `lunexeconom-backup.timer`, keeps latest 14 backups per database in `/home/gamedev/backups/lunexeconom/server/`.

## API
- `GET /health`, `GET /world`
- `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `POST /auth/logout`
- `GET /events?after=N`, `GET /chunk?cx=X&cy=Y` (require Bearer token)
- `POST /build` (requires Bearer token), JSON `{"kind":"farm","x":10,"y":10,"request_id":"<UUID>"}`.
- Building types and footprints: farm 2×2, mine 2×3, factory 3×2.
- Atomic collision check and commit, per-chunk versions, durable event log, idempotent requests per account.

## Tests / known limitations
- Headless Godot startup verified; Python isolated tests passed for atomic build, collision, idempotency, events and chunk snapshots.
- HTTPS health returned 200 and unauthenticated events/build returned 401.
- **Not production-complete:** SQLite alpha persistence, no server-side road/path, terrain, land ownership or costs validation, no economy simulation, no password recovery/email verification, no multi-device load testing. Client world build requests are not yet wired to `POST /build`; only sync uses authenticated endpoints.
- Future work: PostgreSQL migration, durable per-account rate limits, session rotation, server-side construction rules, user-specific companies and finances, deployment/rollback automation, load and security tests.

## Safety
- All code changes on GitHub `main` only.
- VPS service binds to loopback, no additional publicly listening port.
- Existing nginx and other projects preserved; backup of nginx config is stored outside `sites-enabled`.
- No new branch created.
