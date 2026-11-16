import unittest

from portal.review import conflicts, engine, knowledge, library, returns

ZONE = ["portal/app.py", "portal/tests/**", "portal/qa/server/*.md"]
SHARED = ["tools/work_plan.py", "docs/work_plan.json"]


class ZoneTests(unittest.TestCase):
    def test_glob_matching(self):
        self.assertTrue(engine.in_zone("portal/app.py", ZONE))
        self.assertTrue(engine.in_zone("portal/tests/sub/test_x.py", ZONE))
        self.assertTrue(engine.in_zone("portal/qa/server/A1.md", ZONE))
        self.assertFalse(engine.in_zone("portal/qa/server/deep/A1.md", ZONE))
        self.assertFalse(engine.in_zone("portal/static/index.html", ZONE))
        self.assertFalse(engine.in_zone("portal/app.pyc", ZONE))

    def test_dots_and_specials_are_literal(self):
        self.assertFalse(engine.in_zone("portalXapp.py", ["portal/app.py"]))
        self.assertFalse(engine.in_zone("portal/appXpy", ["portal/app.py"]))

    def test_zone_green_red_shared(self):
        self.assertEqual(engine.check_zone(["portal/app.py"], ZONE, SHARED)["status"], "green")
        r = engine.check_zone(["portal/app.py", "portal/static/x.js"], ZONE, SHARED)
        self.assertEqual(r["status"], "red")
        self.assertIn("portal/static/x.js", r["details"])
        s = engine.check_zone(["tools/work_plan.py"], ["tools/**"], SHARED)
        self.assertEqual(s["status"], "red")
        self.assertIn("общие", s["title"])


class SecretTests(unittest.TestCase):
    def test_detects_real_looking_secrets_only_in_added_lines(self):
        tok = "ghp_" + "a1B2c3D4" * 5
        diff = "--- a/x\n+++ b/x\n-old = '%s'\n+new = '%s'\n" % (tok, tok)
        found = engine.find_secrets(diff)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["type"], "github_token")
        self.assertEqual(found[0]["line"], 4)

    def test_value_is_never_returned(self):
        tok = "github_pat_" + "Z9" * 25
        out = engine.check_secrets("+TOKEN='%s'\n" % tok)
        self.assertEqual(out["status"], "red")
        self.assertNotIn(tok, str(out))

    def test_other_patterns(self):
        for line in ("+key = AKIA" + "ABCDEFGHIJKLMNOP", "+x='sk-" + "a" * 30 + "'", "+t = 123456789:" + "A" * 35,
                     "+-----BEGIN PRIVATE KEY-----", "+password = 'Sup3rSecretValue99'"):
            self.assertTrue(engine.find_secrets(line), line)

    def test_safe_and_removed_values_ignored(self):
        self.assertEqual(engine.find_secrets("+PW = 'correct-horse-battery'"), [])
        self.assertEqual(engine.find_secrets("+password = 'example-password-value'"), [])
        self.assertEqual(engine.find_secrets("-password = 'Sup3rSecretValue99'"), [])
        self.assertEqual(engine.find_secrets("+token = os.environ['TOKEN']"), [])
        self.assertEqual(engine.find_secrets(""), [])
        self.assertEqual(engine.find_secrets(None), [])
        self.assertEqual(engine.check_secrets("+ok")["status"], "green")


class OtherChecks(unittest.TestCase):
    def test_size_levels_and_binary_ignored(self):
        self.assertEqual(engine.check_size([{"path": "a.py", "added": 10, "deleted": 0}])["status"], "green")
        self.assertEqual(engine.check_size([{"path": "a.py", "added": 3500, "deleted": 0}])["status"], "yellow")
        self.assertEqual(engine.check_size([{"path": "a.py", "added": 13000, "deleted": 0}])["status"], "red")
        self.assertEqual(engine.check_size([{"path": "shot.png", "added": 99999, "deleted": 0}])["status"], "green")

    def test_ci(self):
        self.assertEqual(engine.check_ci("success")["status"], "green")
        self.assertEqual(engine.check_ci("failure")["status"], "red")
        self.assertEqual(engine.check_ci(None)["status"], "yellow")
        self.assertEqual(engine.check_ci("pending")["status"], "yellow")

    def test_checklist(self):
        self.assertEqual(engine.check_checklist([])["status"], "yellow")
        r = engine.check_checklist([{"text": "a", "done": True}, {"text": "b", "done": False}])
        self.assertEqual((r["status"], r["details"]), ("yellow", ["b"]))
        self.assertEqual(engine.check_checklist([{"text": "a", "done": True}])["status"], "green")

    def test_report(self):
        self.assertEqual(engine.check_report("  ")["status"], "yellow")
        self.assertEqual(engine.check_report(None)["status"], "yellow")
        self.assertEqual(engine.check_report("готово")["status"], "green")

    def test_tests_added(self):
        self.assertEqual(engine.check_tests_added(["portal/app.py"])["status"], "yellow")
        self.assertEqual(engine.check_tests_added(["portal/app.py", "portal/tests/test_a.py"])["status"], "green")
        self.assertEqual(engine.check_tests_added(["docs/x.md"])["status"], "green")


class VerdictTests(unittest.TestCase):
    def good(self, **kw):
        args = dict(plan_pkg_zone=ZONE, shared_files=SHARED, files=["portal/app.py", "portal/tests/test_a.py"], diff_text="+x = 1",
                    stats=[{"path": "portal/app.py", "added": 20, "deleted": 2}], ci_state="success",
                    checklist=[{"text": "a", "done": True}], report="сделано")
        args.update(kw)
        return engine.review(**args)

    def test_all_green_allows_auto_merge(self):
        v = self.good()
        self.assertEqual(v["status"], "green")
        self.assertTrue(engine.auto_merge_allowed(v))

    def test_any_yellow_blocks_auto_merge(self):
        v = self.good(report="")
        self.assertEqual(v["status"], "yellow")
        self.assertFalse(engine.auto_merge_allowed(v))

    def test_red_wins_and_lists_reasons(self):
        v = self.good(files=["portal/static/x.js"], ci_state="failure")
        self.assertEqual(v["status"], "red")
        self.assertEqual(len(v["red"]), 2)
        self.assertFalse(engine.auto_merge_allowed(v))

    def test_secret_in_diff_blocks(self):
        v = self.good(diff_text="+t='ghp_" + "Q" * 36 + "'")
        self.assertEqual(v["status"], "red")
        self.assertFalse(engine.auto_merge_allowed(v))

    def test_empty_verdict_is_green_but_no_checks(self):
        self.assertEqual(engine.verdict([])["status"], "green")


class ConflictTests(unittest.TestCase):
    def test_overlap_detection(self):
        self.assertTrue(conflicts.zones_overlap(["portal/app.py"], ["portal/app.py"]))
        self.assertTrue(conflicts.zones_overlap(["portal/**"], ["portal/static/**"]))
        self.assertFalse(conflicts.zones_overlap(["portal/app.py", "portal/tests/**"], ["portal/static/**", "portal/ui_tests/**"]))
        self.assertTrue(conflicts.zones_overlap(["**"], ["portal/x"]))

    def test_warnings_red_for_same_files_yellow_for_zones(self):
        tasks = [{"id": "A", "zone": ["portal/**"], "files": ["portal/app.py"]},
                 {"id": "B", "zone": ["portal/static/**"], "files": ["portal/app.py"]},
                 {"id": "C", "zone": ["portal/static/**"], "files": []}]
        w = conflicts.warnings(tasks)
        pairs = {(x["a"], x["b"]): x["level"] for x in w}
        self.assertEqual(pairs[("A", "B")], "red")
        self.assertEqual(pairs[("A", "C")], "yellow")
        self.assertEqual(pairs[("B", "C")], "yellow")

    def test_no_warnings_for_disjoint(self):
        tasks = [{"id": "A", "zone": ["portal/app.py"], "files": ["portal/app.py"]}, {"id": "B", "zone": ["portal/static/**"], "files": []}]
        self.assertEqual(conflicts.warnings(tasks), [])
        self.assertEqual(conflicts.warnings([]), [])


class ReturnsTests(unittest.TestCase):
    def test_prompt_contains_reasons_pr_and_attempt(self):
        p = returns.rework_prompt("A6", "Мастер", ["no_tests", "ci_red"], "добавь проверку ссылки", "https://github.com/o/r/pull/1", 2)
        for s in ("A6", "Нет тестов", "CI красный", "добавь проверку ссылки", "pull/1", "Попытка доработки: 2"):
            self.assertIn(s, p)

    def test_unknown_reasons_ignored_and_empty_rejected(self):
        with self.assertRaises(ValueError):
            returns.rework_prompt("A", "t", ["nope"])
        self.assertIn("note", returns.rework_prompt("A", "t", ["nope"], "note"))

    def test_note_is_limited(self):
        p = returns.rework_prompt("A", "t", ["no_tests"], "x" * 5000)
        self.assertLess(len(p), 4000)

    def test_catalog_and_suggest_from_review(self):
        self.assertTrue(all(c["id"] and c["title"] and c["text"] for c in returns.catalog()))
        v = {"checks": [{"id": "zone", "status": "red"}, {"id": "ci", "status": "green"}, {"id": "report", "status": "yellow"}]}
        self.assertEqual(returns.reasons_from_review(v), ["out_of_zone", "no_report"])


class KnowledgeTests(unittest.TestCase):
    def test_add_dedupe_and_ids(self):
        l, a = knowledge.add([], "Postgres падает без postmaster.pid: удалить файл", now=1)
        self.assertEqual(a["id"], "L1")
        l2, b = knowledge.add(l, "postgres  падает без POSTMASTER.pid: удалить файл", now=2)
        self.assertIsNone(b)
        self.assertEqual(len(l2), 1)
        l3, c = knowledge.add(l2, "Не перенаправлять вывод render в файл", now=3)
        self.assertEqual(c["id"], "L2")

    def test_validation(self):
        with self.assertRaises(ValueError):
            knowledge.add([], "коротко")
        with self.assertRaises(ValueError):
            knowledge.add([], "x" * 500)
        with self.assertRaises(ValueError):
            knowledge.add([], "токен ghp_" + "a1B2c3D4" * 5 + " использовать")

    def test_limit_and_remove(self):
        l = []
        for i in range(70):
            l, _ = knowledge.add(l, "правило номер %d для проекта" % i, now=i)
        self.assertEqual(len(l), knowledge.MAX_LESSONS)
        self.assertEqual(len(knowledge.remove(l, l[0]["id"])), knowledge.MAX_LESSONS - 1)

    def test_render_prefers_tags_and_limits(self):
        l = []
        l, _ = knowledge.add(l, "старое правило про сервер и базу", tags=["server"], now=1)
        l, _ = knowledge.add(l, "новое правило про интерфейс и вёрстку", tags=["ui"], now=2)
        text = knowledge.render(l, tags=["server"])
        self.assertTrue(text.startswith("ЛОВУШКИ"))
        self.assertLess(text.index("старое"), text.index("новое"))
        self.assertEqual(knowledge.render([]), "")
        self.assertEqual(knowledge.render(l, max_chars=5), "")

    def test_suggest_from_returns(self):
        s = knowledge.suggest_from_returns(["no_tests", "ci_red", "no_tests"])
        self.assertEqual([x["reason"] for x in s], ["no_tests"])
        self.assertEqual(knowledge.suggest_from_returns(["no_tests"]), [])


class LibraryTests(unittest.TestCase):
    def test_only_first_pass_recorded(self):
        self.assertEqual(library.record([], "A1", "t", "g", "p", 1, "A"), [])
        lib = library.record([], "A1", "Безопасность портала", "смена пароля и аудит входа", "промпт", 0, "A")
        self.assertEqual(len(lib), 1)

    def test_similar_by_keywords_and_lane(self):
        lib = library.record([], "A1", "Безопасность портала", "смена пароля и аудит входа", "p", 0, "A")
        lib = library.record(lib, "B1", "Мобильная доска", "переключатель линий на телефоне", "p", 0, "B")
        got = library.similar(lib, "Аудит безопасности", "добавить журнал аудита входа", lane="A")
        self.assertEqual([x["id"] for x in got], ["A1"])
        self.assertEqual(library.similar(lib, "Аудит", "вход", lane="B"), [])
        self.assertEqual(library.similar([], "a", "b"), [])

    def test_replace_same_task_and_limit(self):
        lib = []
        for i in range(60):
            lib = library.record(lib, "T%d" % i, "задача %d" % i, "цель %d" % i, "p", 0, "A")
        self.assertEqual(len(lib), library.MAX_EXAMPLES)
        lib = library.record(lib, "T59", "новое", "новая цель", "p2", 0, "A")
        self.assertEqual(len([x for x in lib if x["id"] == "T59"]), 1)

    def test_render_examples(self):
        self.assertEqual(library.render_examples([]), "")
        lib = library.record([], "A1", "Безопасность", "аудит входа", "p", 0, "A")
        self.assertIn("ОБРАЗЕЦ", library.render_examples(lib))


if __name__ == "__main__":
    unittest.main()
