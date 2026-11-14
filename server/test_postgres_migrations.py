"""PostgreSQL migration tests use only lunex_ci and temporary schemas."""
import dataclasses
import os
import re
import unittest
import uuid
from unittest import mock

import postgres_db
import migrate


@unittest.skipUnless(
    os.environ.get("LUNEX_DB_ENGINE") == "postgres"
    and os.environ.get("LUNEX_PG_DB") == "lunex_ci",
    "requires isolated PostgreSQL database lunex_ci",
)
class PostgresMigrationTests(unittest.TestCase):
    def setUp(self):
        self.db = postgres_db.connect()
        if self.db.execute("SELECT current_database()").fetchone()[0] != "lunex_ci":
            self.db.close()
            self.skipTest("refusing to alter a non-test database")
        self.schema = "chatgpttwo_" + uuid.uuid4().hex[:16]
        self.db.execute("CREATE SCHEMA " + self.schema)
        self.db.execute("SET search_path TO " + self.schema)
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.execute("SET search_path TO public")
        self.db.execute("DROP SCHEMA IF EXISTS " + self.schema + " CASCADE")
        self.db.commit()
        self.db.close()

    def test_clean_baseline_matches_legacy_schema(self):
        result = migrate.up(self.db)
        migrations = migrate.load_migrations()
        self.assertEqual(result["applied_now"], [m.version for m in migrations])      # 001 baseline, then every later migration
        described = set()
        for migration in migrations:
            described |= set(migrate.TABLE_PATTERN.findall(migration.sql))
        names = {row[0] for row in self.db.execute(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname=%s", (self.schema,)
        ).fetchall()}
        self.assertEqual(names, described | {"schema_migrations"})
        self.assertEqual(described, migrate.SCHEMA_TABLES)               # the migrations describe exactly postgres_db.SCHEMA
        self.assertEqual(migrate.status(self.db)["pending"], [])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0], len(migrations))

    def test_legacy_baseline_does_not_rewrite_data(self):
        for statement in postgres_db.SCHEMA.split(";"):
            if statement.strip():
                self.db.execute(statement)
        self.db.execute(
            "INSERT INTO users(username,email,salt,password_hash,created_at) "
            "VALUES('baseline_account','baseline@example.test',%s,%s,123)",
            (b"salt", b"hash"),
        )
        self.db.commit()
        self.assertTrue(migrate.status(self.db)["legacy_baseline"])
        # 001 is only recorded (the legacy tables are kept untouched); later migrations are idempotent and run
        self.assertEqual(migrate.up(self.db)["applied_now"], [m.version for m in migrate.load_migrations()])
        self.assertEqual(self.db.execute("SELECT count(*) FROM users").fetchone()[0], 1)
        self.assertEqual(self.db.execute(
            "SELECT created_at FROM users WHERE username='baseline_account'"
        ).fetchone()[0], 123)

    def test_repeat_and_checksum_tampering(self):
        migrate.up(self.db)
        self.db.commit()
        self.assertEqual(migrate.up(self.db)["applied_now"], [])
        original = migrate.load_migrations()
        changed = dataclasses.replace(original[0], checksum="0" * 64)
        with mock.patch.object(migrate, "load_migrations", return_value=[changed]):
            with self.assertRaisesRegex(RuntimeError, "Checksum/name mismatch"):
                migrate.up(self.db)

    def test_postgres_email_quota(self):
        import ops_email
        now = 1_800_000_000
        self.assertTrue(ops_email.reserve(self.db, "%s", "ops@example.test", "ci", now, postgres=True))
        self.assertFalse(ops_email.reserve(self.db, "%s", "ops@example.test", "ci", now + 59, postgres=True))
        self.assertTrue(ops_email.reserve(self.db, "%s", "ops@example.test", "ci", now + 60, postgres=True))

    def test_partial_legacy_schema_refused(self):
        self.db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        self.db.commit()
        self.assertTrue(migrate.status(self.db)["partial_baseline"])
        with self.assertRaisesRegex(RuntimeError, "Partial legacy schema"):
            migrate.up(self.db)
        self.db.rollback()


if __name__ == "__main__":
    unittest.main()
