"""Regression checks for the director-owned roadmap and static website."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from tools.check_website import ROOT, check_roadmap, main, valid_url


class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "web/roadmap.json").read_text(encoding="utf-8"))

    def test_good_roadmap(self):
        check_roadmap(self.data)

    def test_invalid_status(self):
        bad = copy.deepcopy(self.data)
        bad["phases"][0]["items"][0]["status"] = "finished"
        with self.assertRaises(ValueError): check_roadmap(bad)

    def test_invalid_progress(self):
        for value in (-1, 101, 12.5, True):
            with self.subTest(value=value):
                bad = copy.deepcopy(self.data)
                bad["phases"][0]["progress"] = value
                with self.assertRaises(ValueError): check_roadmap(bad)

    def test_empty_title(self):
        bad = copy.deepcopy(self.data)
        bad["milestones"][0]["title"] = "  "
        with self.assertRaises(ValueError): check_roadmap(bad)

    def test_url_policy(self):
        for url in ("/download/app.apk", "//evil.example/app.apk", "https://evil.example/app.apk", "../app.apk", "./%2e%2e/app.apk"):
            with self.subTest(url=url): self.assertFalse(valid_url(url))
        self.assertTrue(valid_url("./roadmap.json"))

    def test_actual_website(self):
        main()

    def test_reject_bad_html_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "web"
            directory.mkdir()
            for name in ("index.html", "styles.css", "site.js", "config.js", "roadmap.json"):
                (directory / name).write_bytes((ROOT / "web" / name).read_bytes())
            bad = (directory / "index.html").read_text().replace("./styles.css", "/styles.css")
            (directory / "index.html").write_text(bad)
            with self.assertRaises(AssertionError): main(Path(tmp))


if __name__ == "__main__": unittest.main()
