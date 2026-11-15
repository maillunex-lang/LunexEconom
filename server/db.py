"""PostgreSQL-only database connector and sequential SHA-256 migrations."""
import hashlib
import os
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).resolve().parent / 'migrations'


def connect(dsn=None):
    url = dsn or os.environ.get('LUNEX_DATABASE_URL')
    if not url or not url.startswith(('postgresql://', 'postgres://')):
        raise RuntimeError('LUNEX_DATABASE_URL must be a PostgreSQL connection URL')
    return psycopg.connect(url, autocommit=False)


def migrate(conn, modules):
    with conn.transaction():
        conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())')
        conn.execute('SELECT pg_advisory_xact_lock(2026111500)')
        paths = sorted({Path(p) for mod in modules for p in mod.migrations()})
        for path in paths:
            if not path.name[:12].isdigit() or not path.name.endswith('.sql'):
                raise ValueError(f'Invalid migration filename: {path.name}')
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            row = conn.execute('SELECT sha256 FROM schema_migrations WHERE name = %s', (path.name,)).fetchone()
            if row:
                if row[0] != checksum:
                    raise RuntimeError('Migration checksum mismatch: ' + path.name)
                continue
            conn.execute(path.read_text(encoding='utf-8'))
            conn.execute('INSERT INTO schema_migrations(name,sha256) VALUES (%s,%s)', (path.name, checksum))
