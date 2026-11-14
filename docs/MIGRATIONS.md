# PostgreSQL migrations (BE-004)

Versioned PostgreSQL migrations live in `server/migrations/NNN_name.sql`.
`001_baseline.sql` is an exact snapshot of the tables in `postgres_db.SCHEMA` at the start of Round 3. Do not edit an applied migration. A changed SHA-256 checksum is rejected.

## Safe operator workflow

1. Take a tested backup, then rehearse restore with `ops/postgres_restore_drill.py` **into a disposable database**. Review the drill script's arguments before running. Never point the drill at a production database.
2. Set PostgreSQL connection via `LUNEX_PG_HOST`, `LUNEX_PG_PORT`, `LUNEX_PG_DB`, `LUNEX_PG_USER` and `LUNEX_PG_PASSWORD` or `LUNEX_PG_PASSWORD_FILE`. Do not commit values, print them or paste them into logs.
3. Run `python server/migrate.py status` to inspect pending versions and whether a legacy schema is detected.
4. On a verified restored copy, run `python server/migrate.py up` twice. The second invocation should show `applied_now: []`. Run server tests against that same test database.
5. Only after separate owner approval, a backup and a rollback/restore drill, authorize changes in production. There is no destructive down migration.

New migrations: add the next consecutive `NNN_description.sql`, SQL that is transactional and idempotent from the previous version, and a comment explaining reversibility. Add tests against both a fresh schema and a legacy baseline. **Never rewrite 001**. Existing tables created by other branches are preserved, not dropped or inspected for cleanup.

Migration execution is **disabled by default** during server startup. It is enabled only with `LUNEX_AUTO_MIGRATE=1` for the PostgreSQL engine. The existing `postgres_db.init()` CREATE IF NOT EXISTS behavior is unchanged. The runner acquires a transaction-scoped advisory lock and stores version, name, timestamp and checksum in `schema_migrations`. A partial legacy schema is rejected instead of guessing or altering data. A complete legacy table set is marked version 001 without recreation.

## Новые таблицы после baseline (правило, раунд 3)
`001_baseline.sql` — **фиксированный снимок** схемы на 14.11.2026 и не следует за `postgres_db.SCHEMA`. Каждая новая таблица, добавленная в `postgres_db.SCHEMA`, обязана получить
собственную пронумерованную миграцию (`002_…`, `003_…`, идемпотентную `CREATE TABLE IF NOT EXISTS …`): `migrate.load_migrations()` падает, если какая-то таблица схемы не описана миграцией.
Пример: `002_eco_owner_spend.sql`. Таблицы социального модуля (`soc_*`) создаёт `social.ensure()` при старте и в `postgres_db.SCHEMA` не входят — для них миграция не требуется,
пока их не перенесут в схему.
