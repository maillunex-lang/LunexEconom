## Автообновление сервера (CI-gate + откат)

Скрипт `ops/update_server.py` + `lunexeconom-server-update.timer` (каждые ~5 минут):
1. берёт SHA последнего коммита `main`; если он уже развёрнут или ранее падал — ничего не делает;
2. требует успешный GitHub Actions `Server checks` (`.github/workflows/server-check.yml`: компиляция + `test_roads`, `test_app`, `test_auth`) именно для этого SHA; если серверные файлы в коммите не менялись (workflow не запускался) — просто отмечает коммит текущим;
3. скачивает `server/*.py` (без тестов) строго по SHA, проверяет синтаксис без выполнения кода;
4. сохраняет бэкап текущих файлов (`/var/lib/lunexeconom-server-update/backups/`, 10 последних);
5. обновляет файлы, перезапускает `lunexeconom-game.service`, ждёт `GET /health` = 200 и `ok:true`;
6. при любой ошибке возвращает старые файлы, перезапускает службу и запоминает плохой SHA (`failed-sha`), чтобы не зацикливаться.

Установка на VPS (один раз, root):
```bash
cd /home/gamedev/projects/LunexEconom && git pull origin main      # либо скачайте файлы из ops/
install -m 755 ops/update_server.py /opt/lunexeconom-deploy/update_server.py
install -m 644 ops/lunexeconom-server-update.service ops/lunexeconom-server-update.timer /etc/systemd/system/
mkdir -p /var/lib/lunexeconom-server-update
systemctl daemon-reload
systemctl enable --now lunexeconom-server-update.timer
systemctl start lunexeconom-server-update.service      # первый запуск вручную
journalctl -u lunexeconom-server-update.service -n 30 --no-pager
```
Настройка через переменные окружения (`Environment=` в unit): `LUNEX_SERVER_DIR`, `LUNEX_SERVICES` (список через пробел), `LUNEX_HEALTH_URL`, `LUNEX_SERVER_USER`. Сам `update_server.py` обновляется вручную (копированием из `ops/`). Отключить: `systemctl disable --now lunexeconom-server-update.timer`.

Ограничения: обновляется только Python-код; миграции схемы выполняются через `CREATE TABLE IF NOT EXISTS` при старте; деструктивные миграции требуют ручного шага. Проверено локально сухим прогоном на реальном GitHub (временные папки, без перезапуска) и юнит-тестами отката; на самом VPS ещё не запускалось.

---

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
