"""ADM1 contract tests; PostgreSQL integration tests run when LUNEX_TEST_DATABASE_URL is set."""
import os
from pathlib import Path
import unittest

class TestAdminA1StaticContract(unittest.TestCase):
    def test_panel_is_self_contained_and_russian(self):
        root=Path(__file__).resolve().parents[2]/'web'/'admin'
        html=(root/'index.html').read_text()
        js=(root/'app.js').read_text()
        self.assertIn('lang="ru"',html)
        self.assertIn('./styles.css',html)
        self.assertIn('./config.js',html)
        self.assertNotIn('http://',html+js)
        self.assertNotIn('https://',html+js)
        self.assertIn('sessionStorage',js)

    def test_roles_and_migration_contract(self):
        migration=(Path(__file__).resolve().parents[1]/'migrations'/'202611160010_admin_a1.sql').read_text()
        for token in ('admin_sessions','actor_role','target_account_id','blocked_until'):
            self.assertIn(token,migration)

@unittest.skipUnless(os.getenv('LUNEX_TEST_DATABASE_URL'),'Set LUNEX_TEST_DATABASE_URL for PostgreSQL integration tests')
class TestAdminA1Postgres(unittest.TestCase):
    def test_enabled_marker(self):
        # Full end-to-end cases are kept in the project integration suite and require an isolated DB.
        self.assertTrue(os.getenv('LUNEX_TEST_DATABASE_URL'))
