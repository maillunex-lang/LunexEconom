"""Versioned PostgreSQL migrations with a non-destructive legacy baseline.

Only PostgreSQL is supported. The existing postgres_db.SCHEMA stays intact.
Run via: python server/migrate.py status | up
"""
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import postgres_db

DIRECTORY = Path(__file__).with_name("migrations")
FILE_PATTERN = re.compile(r"^(\d{3})_([a-z][a-z0-9_]*)\.sql$")
TABLE_PATTERN = re.compile(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([a-z_][a-z_0-9]*)", re.I)
BASELINE_TABLES = frozenset(TABLE_PATTERN.findall(postgres_db.SCHEMA))


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


def load_migrations():
    files = sorted(DIRECTORY.glob("*.sql"))
    migrations = []
    for path in files:
        match = FILE_PATTERN.fullmatch(path.name)
        if not match:
            raise RuntimeError("Invalid migration filename: " + path.name)
        sql = path.read_text(encoding="utf-8")
        migrations.append(Migration(int(match[1]), match[2], sql, hashlib.sha256(sql.encode("utf-8")).hexdigest()))
    if not migrations or [m.version for m in migrations] != list(range(1, len(migrations) + 1)):
        raise RuntimeError("Migration versions must start at 001 and be consecutive")
    if frozenset(TABLE_PATTERN.findall(migrations[0].sql)) != BASELINE_TABLES:
        raise RuntimeError("Baseline tables differ from postgres_db.SCHEMA")
    return migrations


def _ensure_registry(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            checksum TEXT NOT NULL
        )
    """)


def _applied(db):
    return {row[0]: (row[1], row[2]) for row in
            db.execute("SELECT version,name,checksum FROM schema_migrations ORDER BY version").fetchall()}


def _verify(migrations, applied):
    available = {migration.version: migration for migration in migrations}
    for version, (name, checksum) in applied.items():
        if version not in available:
            raise RuntimeError("Unknown previously applied migration version: %03d" % version)
        current = available[version]
        if (current.name, current.checksum) != (name, checksum):
            raise RuntimeError("Checksum/name mismatch for applied migration %03d" % version)
    if sorted(applied) != list(range(1, len(applied) + 1)):
        raise RuntimeError("Migration history has gaps")


def _existing_baseline_tables(db):
    names = db.execute("""
        SELECT tablename FROM pg_catalog.pg_tables
        WHERE schemaname = current_schema()
    """).fetchall()
    return BASELINE_TABLES.intersection(row[0] for row in names)


def status(db=None):
    if db is None:
        with postgres_db.connect() as connection:
            return status(connection)
    migrations = load_migrations()
    exists = db.execute("SELECT to_regclass('schema_migrations')").fetchone()[0]
    applied = _applied(db) if exists else {}
    _verify(migrations, applied)
    existing = _existing_baseline_tables(db)
    return {
        "applied": sorted(applied),
        "pending": [m.version for m in migrations if m.version not in applied],
        "legacy_baseline": bool(existing == BASELINE_TABLES and 1 not in applied),
        "partial_baseline": bool(existing and existing != BASELINE_TABLES),
    }


def up(db=None):
    if db is None:
        with postgres_db.connect() as connection:
            return up(connection)
    db.execute("SELECT pg_advisory_xact_lock(20261114, 77)")
    migrations = load_migrations()
    _ensure_registry(db)
    applied = _applied(db)
    _verify(migrations, applied)
    completed = []
    for migration in migrations:
        if migration.version in applied:
            continue
        if migration.version == 1:
            existing = _existing_baseline_tables(db)
            if existing and existing != BASELINE_TABLES:
                raise RuntimeError("Partial legacy schema: refusing to apply baseline")
            if not existing:
                db.execute(migration.sql)
        else:
            db.execute(migration.sql)
        db.execute(
            "INSERT INTO schema_migrations(version,name,checksum) VALUES(%s,%s,%s)",
            (migration.version, migration.name, migration.checksum),
        )
        completed.append(migration.version)
    return {"applied_now": completed, "status": status(db)}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args not in (["status"], ["up"]):
        print("Usage: python server/migrate.py status|up", file=sys.stderr)
        return 2
    try:
        result = status() if args[0] == "status" else up()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as error:
        # Never echo connection strings or environment variables to CLI logs.
        print("Migration failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
