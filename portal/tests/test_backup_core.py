import json
import os
import sqlite3
import tempfile
import time
import unittest

from portal import db
from portal.backup import core


def make(path):
    conn = db.connect(path, webhook=True, reports=True)
    conn.execute("INSERT INTO users(username,pw_hash,created) VALUES('owner','HASH',1)")
    for slug in ("alpha", "beta"):
        conn.execute("INSERT INTO projects(slug,name,repo,description,plan_json,plan_updated,created) VALUES(?,?,?,?,?,?,?)",
                     (slug, slug.title(), "o/" + slug, "d", json.dumps({"packages": []}), 1.0, 1.0))
        conn.execute("INSERT INTO task_state(project_slug,pkg_id,status) VALUES(?,?,?)", (slug, "A1", "accepted"))
        conn.execute("INSERT INTO ideas(project_slug,text,created) VALUES(?,?,?)", (slug, "идея " + slug, 1.0))
        conn.execute("INSERT INTO events(project_slug,pkg_id,ts,kind,source) VALUES(?,?,?,?,?)", (slug, "A1", 1.0, "k", "s"))
    return conn


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "p.sqlite")
        self.conn = make(self.path)
        self.bdir = os.path.join(self.d, "bak")

    def test_create_and_verify(self):
        p = core.create_backup(self.path, self.bdir)
        v = core.verify_backup(p)
        self.assertTrue(v["ok"])
        self.assertEqual((v["projects"], v["users"]), (2, 1))

    def test_backup_file_private(self):
        p = core.create_backup(self.path, self.bdir)
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)

    def test_same_second_names_unique(self):
        a = core.create_backup(self.path, self.bdir, now=1000)
        b = core.create_backup(self.path, self.bdir, now=1000)
        self.assertNotEqual(a, b)

    def test_prune_keeps_limit(self):
        for i in range(5):
            core.create_backup(self.path, self.bdir, keep=3, now=1000 + i)
        self.assertEqual(len(core.list_backups(self.bdir)), 3)

    def test_list_newest_first_and_ignores_foreign_files(self):
        core.create_backup(self.path, self.bdir, now=1000)
        core.create_backup(self.path, self.bdir, now=2000)
        open(os.path.join(self.bdir, "notes.txt"), "w").write("x")
        names = [i["name"] for i in core.list_backups(self.bdir)]
        self.assertEqual(len(names), 2)
        self.assertTrue(names[0] > names[1])

    def test_latest(self):
        self.assertIsNone(core.latest_backup(self.bdir))
        core.create_backup(self.path, self.bdir, now=1000)
        p = core.create_backup(self.path, self.bdir, now=2000)
        self.assertEqual(core.latest_backup(self.bdir), p)

    def test_restore_to_new_file_and_data_matches(self):
        p = core.create_backup(self.path, self.bdir)
        self.conn.execute("DELETE FROM projects WHERE slug='alpha'")
        target = os.path.join(self.d, "restored.sqlite")
        core.restore_backup(p, target)
        c = sqlite3.connect(target)
        self.assertEqual(c.execute("SELECT count(*) FROM projects").fetchone()[0], 2)
        c.close()

    def test_restore_refuses_existing_target(self):
        p = core.create_backup(self.path, self.bdir)
        with self.assertRaises(core.BackupError):
            core.restore_backup(p, self.path)

    def test_restore_refuses_corrupt_backup(self):
        bad = os.path.join(self.d, "bad.sqlite")
        open(bad, "wb").write(b"not a database" * 100)
        self.assertFalse(core.verify_backup(bad)["ok"])
        with self.assertRaises(core.BackupError):
            core.restore_backup(bad, os.path.join(self.d, "x.sqlite"))

    def test_verify_does_not_modify_backup(self):
        p = core.create_backup(self.path, self.bdir)
        before = open(p, "rb").read()
        core.verify_backup(p)
        self.assertEqual(open(p, "rb").read(), before)


class ExportImportTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.conn = make(os.path.join(self.d, "a.sqlite"))

    def test_export_has_only_project_data(self):
        data = core.export_project(self.conn, "alpha")
        text = json.dumps(data)
        self.assertNotIn("HASH", text)
        self.assertNotIn("beta", text.replace("Beta", ""))
        self.assertEqual(data["project"]["slug"], "alpha")
        self.assertEqual(len(data["tables"]["ideas"]), 1)

    def test_export_unknown_project(self):
        with self.assertRaises(core.BackupError):
            core.export_project(self.conn, "nope")

    def test_import_into_other_portal_preserves_data(self):
        data = json.loads(json.dumps(core.export_project(self.conn, "alpha")))
        other = db.connect(os.path.join(self.d, "b.sqlite"), webhook=True, reports=True)
        core.import_project(other, data)
        self.assertEqual(other.execute("SELECT text FROM ideas WHERE project_slug='alpha'").fetchone()[0], "идея alpha")
        self.assertEqual(other.execute("SELECT status FROM task_state WHERE project_slug='alpha'").fetchone()[0], "accepted")
        self.assertEqual(other.execute("SELECT count(*) FROM users").fetchone()[0], 0)

    def test_import_with_new_slug_does_not_mix_projects(self):
        data = core.export_project(self.conn, "alpha")
        core.import_project(self.conn, data, new_slug="alpha-copy")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM ideas WHERE project_slug='alpha'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM ideas WHERE project_slug='alpha-copy'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM ideas WHERE project_slug='beta'").fetchone()[0], 1)

    def test_import_refuses_existing_slug(self):
        data = core.export_project(self.conn, "alpha")
        with self.assertRaises(core.BackupError):
            core.import_project(self.conn, data)

    def test_import_rejects_bad_format(self):
        for bad in ({}, {"format": "x"}, [], "s", {"format": core.FORMAT, "project": {"slug": "../x", "name": "n"}, "tables": {}},
                    {"format": core.FORMAT, "project": {"slug": "ok", "name": ""}, "tables": {}},
                    {"format": core.FORMAT, "project": {"slug": "ok", "name": "n"}, "tables": {"users": []}}):
            with self.assertRaises(core.BackupError):
                core.import_project(self.conn, bad)

    def test_import_ignores_foreign_project_slug_in_rows(self):
        data = core.export_project(self.conn, "alpha")
        for r in data["tables"]["ideas"]:
            r["project_slug"] = "beta"
        core.import_project(self.conn, data, new_slug="gamma")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM ideas WHERE project_slug='beta'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM ideas WHERE project_slug='gamma'").fetchone()[0], 1)

    def test_import_is_atomic(self):
        data = core.export_project(self.conn, "alpha")
        data["tables"]["task_state"].append({"pkg_id": None, "status": None})
        with self.assertRaises(Exception):
            core.import_project(self.conn, data, new_slug="broken")
        self.assertIsNone(self.conn.execute("SELECT 1 FROM projects WHERE slug='broken'").fetchone())

    def test_import_row_limit(self):
        data = core.export_project(self.conn, "alpha")
        data["tables"]["ideas"] = [{"text": "x", "created": 1}] * (core.MAX_IMPORT_ROWS + 1)
        with self.assertRaises(core.BackupError):
            core.import_project(self.conn, data, new_slug="big")


class DeleteTests(unittest.TestCase):
    def setUp(self):
        self.conn = make(os.path.join(tempfile.mkdtemp(), "a.sqlite"))

    def test_requires_matching_confirmation(self):
        for bad in ("", "Alpha", "beta", None):
            with self.assertRaises(core.BackupError):
                core.delete_project(self.conn, "alpha", bad)
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM projects WHERE slug='alpha'").fetchone())

    def test_deletes_only_that_project(self):
        removed = core.delete_project(self.conn, "alpha", "alpha")
        self.assertEqual(removed["ideas"], 1)
        self.assertIsNone(self.conn.execute("SELECT 1 FROM projects WHERE slug='alpha'").fetchone())
        self.assertEqual(self.conn.execute("SELECT count(*) FROM ideas WHERE project_slug='beta'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM users").fetchone()[0], 1)

    def test_unknown_project(self):
        with self.assertRaises(core.BackupError):
            core.delete_project(self.conn, "nope", "nope")


class GraphTests(unittest.TestCase):
    PLAN = {"packages": [
        {"id": "A1", "depends_on": [], "lane": "A", "step": 1},
        {"id": "A2", "depends_on": ["A1"], "lane": "A", "step": 2},
        {"id": "A3", "depends_on": ["A2"], "lane": "A", "step": 3},
        {"id": "B1", "depends_on": [], "lane": "B", "step": 1},
        {"id": "B2", "depends_on": ["B1", "A1"], "lane": "B", "step": 2}]}

    def test_nodes_edges_and_critical_path(self):
        g = core.graph(self.PLAN)
        self.assertEqual(len(g["nodes"]), 5)
        self.assertIn({"from": "A1", "to": "B2"}, g["edges"])
        self.assertEqual(g["critical_path"], ["A1", "A2", "A3"])

    def test_accepted_packages_leave_critical_path(self):
        g = core.graph(self.PLAN, {"A1": "accepted", "A2": "accepted"})
        self.assertEqual(g["critical_path"], ["B1", "B2"])  # A3 одна, цепочка B1→B2 длиннее

    def test_cycle_detected(self):
        plan = {"packages": [{"id": "X", "depends_on": ["Y"]}, {"id": "Y", "depends_on": ["X"]}]}
        with self.assertRaises(core.BackupError):
            core.graph(plan)

    def test_unknown_dependency_ignored(self):
        g = core.graph({"packages": [{"id": "X", "depends_on": ["ghost"]}]})
        self.assertEqual(g["edges"], [])
        self.assertEqual(g["critical_path"], ["X"])

    def test_empty_plan(self):
        self.assertEqual(core.graph({})["critical_path"], [])

    def test_real_portal_plan(self):
        plan = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "docs", "portal", "work_plan.json"), encoding="utf-8"))
        g = core.graph(plan)
        self.assertTrue(g["critical_path"])


if __name__ == "__main__":
    unittest.main()
