## PostgreSQL migration — 2026-11-14

**Current active database: PostgreSQL 16, isolated Docker container `lunexeconom-postgres`.**
- Internal-only port `127.0.0.1:15439`; Docker named volume `lunexeconom_pgdata`. No public PostgreSQL port.
- Both `lunexeconom-game.service` and legacy `lunexeconom-foundation.service` run with `LUNEX_DB_ENGINE=postgres` and a project-specific Python virtual environment with psycopg.
- Database `lunexeconom`, user `lunexeconom`. Password is stored only in `/home/gamedev/projects/LunexEconom-server/secrets/postgres-password`, not in GitHub.
- PostgreSQL schema: users, sessions, buildings, cells, chunks, events, commands.
- Migration script `server/migrate_sqlite_to_postgres.py` copied all existing rows. At migration time all seven source tables contained zero records. SQLite files remain intact as rollback archives.
- Automated PostgreSQL backup: `lunexeconom-backup.timer` daily runs root-owned `/usr/local/sbin/lunexeconom-backup-pg.py`, retaining 14 custom-format pg_dump archives under `/home/gamedev/backups/lunexeconom/postgres/`. Restore procedure must be tested before production launch.
- Tests: 3 PostgreSQL integration tests passed (including disposable account registration/login/logout). Separate temporary PostgreSQL database verified atomic building, idempotency, collision detection, events and chunk snapshots; test DB dropped afterwards. HTTPS /health and service readiness checked.
- **Known limitations:** this migration is storage-only. Server still lacks full terrain/road/cost validation, game economy, hardened auth, high-load benchmarks and Android end-to-end testing.

### Rollback notes
1. Stop only LunexEconom game and foundation services.
2. Restore pre-migration systemd service files from `/home/gamedev/backups/lunexeconom/server/`.
3. Restore SQLite Python files from pre-migration Git commit if needed and use untouched SQLite files/backups.
4. Recheck HTTPS endpoints and restart only LunexEconom services.
5. Never automatically roll back after new PostgreSQL writes without a separate data reconciliation plan.

---

# LunexEconom dedicated server on VPS (alpha)

## Production topology
- Public HTTPS: `https://rikagro.ru/lunexeconom/api/` (existing nginx, no new public port).
- Dedicated loopback service: `lunexeconom-game.service`, `127.0.0.1:18767`, memory limit 192 MB.
- Existing `lunexeconom-foundation.service` at `127.0.0.1:18761` is retained and untouched.
- Server code: `server/game_server.py`, `server/auth.py`.
- Runtime: `/home/gamedev/projects/LunexEconom-server/`.
- Previous SQLite user accounts (retained for rollback): `/home/gamedev/projects/LunexEconom-runtime/accounts.sqlite3` (shared with legacy auth endpoint).
- Previous SQLite world DB (retained for rollback): /home/gamedev/projects/LunexEconom-server/world.sqlite3`.
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
