import tempfile
import unittest
from pathlib import Path

from tools import doc_check as dc


class DocCheckTests(unittest.TestCase):
    def make(self, text):
        d = Path(tempfile.mkdtemp())
        f = d / "x.md"
        f.write_text(text, encoding="utf-8")
        return f

    def run_on(self, text, blob="/api/login PORTAL_DB"):
        f = self.make(text)
        dc.ROOT_ORIG = dc.ROOT
        try:
            dc.ROOT = f.parent
            return dc.check_file(f, blob)
        finally:
            dc.ROOT = dc.ROOT_ORIG

    def test_missing_path_is_found_and_existing_is_not(self):
        r = self.run_on("См. `docs/nope.md` и `x.md`.")
        self.assertEqual([(k, t) for _, _, k, t in r], [("path", "docs/nope.md")])

    def test_route_and_env(self):
        r = self.run_on("`GET /api/login` `/api/ghost/thing` `PORTAL_DB` `PORTAL_GHOST_VAR`")
        got = {(k, t) for _, _, k, t in r}
        self.assertIn(("route", "/api/ghost/thing"), got)
        self.assertIn(("env", "PORTAL_GHOST_VAR"), got)
        self.assertNotIn(("route", "/api/login"), got)
        self.assertNotIn(("env", "PORTAL_DB"), got)

    def test_future_lines_domains_and_placeholders_skipped(self):
        r = self.run_on("[v2] `docs/future.md`\n`rikagro.ru/createportal/`\n`docs/<id>.md`\nПланируется `a/b.md`\nСкелет: `c/d.md`")
        self.assertEqual(r, [])

    def test_path_param_segments_ignored_in_routes(self):
        r = self.run_on("`/api/projects/{slug}/login`", blob="/api/projects /login")
        self.assertEqual(r, [])

    def test_repo_docs_are_fresh(self):
        """Документы портала не должны ссылаться на несуществующие файлы, маршруты и переменные."""
        blob = dc.source_blob()
        found = []
        for f in dc.collect(None):
            found += dc.check_file(f, blob)
        self.assertEqual(found, [], found)


if __name__ == "__main__":
    unittest.main()
