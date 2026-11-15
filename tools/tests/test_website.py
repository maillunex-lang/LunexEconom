"""Regression checks for the director-owned roadmap and static website."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from tools.check_website import ROOT, apk_url_allowed, check_roadmap, main, public_base_url, valid_url, validate_latest


class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "web/roadmap.json").read_text(encoding="utf-8"))
        self.base = public_base_url((ROOT / "web/config.js").read_text(encoding="utf-8"))
        self.latest = json.loads((ROOT / "web/tests/fixtures/latest.example.json").read_text(encoding="utf-8"))

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

    def test_good_latest_example(self):
        validate_latest(self.latest, self.base)
        self.assertEqual(self.latest["channel"], "alpha")
        self.assertEqual(self.latest["apk_url"], "https://rikagro.ru/lunexeconom/v2/download/lunex-0.1.0.apk")
        with_extra = copy.deepcopy(self.latest)
        with_extra["debug"] = True
        with_extra["previous"]["signature"] = "ignored"
        validate_latest(with_extra, self.base)
        upper = copy.deepcopy(self.latest)
        upper["sha256"] = upper["sha256"].upper()
        validate_latest(upper, self.base)
        no_previous = copy.deepcopy(self.latest)
        no_previous["previous"] = None
        validate_latest(no_previous, self.base)

    def test_bad_latest_examples(self):
        cases = []
        short = copy.deepcopy(self.latest)
        short["sha256"] = "ab" * 31
        cases.append(short)
        garbage = copy.deepcopy(self.latest)
        garbage["sha256"] = "z" * 64
        cases.append(garbage)
        zero = copy.deepcopy(self.latest)
        zero["size"] = 0
        cases.append(zero)
        fractional = copy.deepcopy(self.latest)
        fractional["size"] = 1.5
        cases.append(fractional)
        boolean = copy.deepcopy(self.latest)
        boolean["size"] = True
        cases.append(boolean)
        text_size = copy.deepcopy(self.latest)
        text_size["size"] = "74631872"
        cases.append(text_size)
        foreign = copy.deepcopy(self.latest)
        foreign["apk_url"] = "https://evil.example/lunex.apk"
        cases.append(foreign)
        outside = copy.deepcopy(self.latest)
        outside["apk_url"] = "https://rikagro.ru/other/lunex.apk"
        cases.append(outside)
        query = copy.deepcopy(self.latest)
        query["apk_url"] = self.latest["apk_url"] + "?dl=1"
        cases.append(query)
        insecure = copy.deepcopy(self.latest)
        insecure["apk_url"] = "http://rikagro.ru/lunexeconom/v2/download/lunex.apk"
        cases.append(insecure)
        debug = copy.deepcopy(self.latest)
        debug["channel"] = "debug"
        cases.append(debug)
        beta = copy.deepcopy(self.latest)
        beta["channel"] = "Alpha"
        cases.append(beta)
        empty_prev = copy.deepcopy(self.latest)
        empty_prev["previous"] = {}
        cases.append(empty_prev)
        missing_prev = copy.deepcopy(self.latest)
        del missing_prev["previous"]
        cases.append(missing_prev)
        schema = copy.deepcopy(self.latest)
        schema["schema"] = 2
        cases.append(schema)
        string_schema = copy.deepcopy(self.latest)
        string_schema["schema"] = "1"
        cases.append(string_schema)
        blank_notes = copy.deepcopy(self.latest)
        blank_notes["notes"] = "   "
        cases.append(blank_notes)
        english = copy.deepcopy(self.latest)
        english["notes"] = "Fixed the map"
        cases.append(english)
        prefixed = copy.deepcopy(self.latest)
        prefixed["version_name"] = "v0.1.0"
        cases.append(prefixed)
        local_time = copy.deepcopy(self.latest)
        local_time["released"] = "2026-11-15T18:00:00+00:00"
        cases.append(local_time)
        nested = copy.deepcopy(self.latest)
        nested["previous"]["sha256"] = "nope"
        cases.append(nested)
        code = copy.deepcopy(self.latest)
        code["version_code"] = 0
        cases.append(code)
        for bad in cases:
            with self.subTest(bad=bad.get("channel"), sha=str(bad.get("sha256"))[:12], size=bad.get("size"), schema=bad.get("schema")):
                with self.assertRaises(ValueError):
                    validate_latest(bad, self.base)

    def test_apk_url_host_is_base_host(self):
        self.assertTrue(apk_url_allowed(self.latest["apk_url"], self.base))
        self.assertFalse(apk_url_allowed("https://user:pw@rikagro.ru/lunexeconom/v2/download/a.apk", self.base))
        self.assertFalse(apk_url_allowed("https://rikagro.ru/lunexeconom/%2e%2e/a.apk", self.base))

    def test_actual_website(self):
        main()

    def test_reject_bad_html_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "web"
            directory.mkdir()
            for name in ("index.html", "styles.css", "site.js", "config.js", "roadmap.json"):
                (directory / name).write_bytes((ROOT / "web" / name).read_bytes())
            (directory / "tests" / "fixtures").mkdir(parents=True)
            (directory / "tests" / "fixtures" / "latest.example.json").write_bytes((ROOT / "web/tests/fixtures/latest.example.json").read_bytes())
            bad = (directory / "index.html").read_text().replace("./styles.css", "/styles.css")
            (directory / "index.html").write_text(bad)
            with self.assertRaises(AssertionError): main(Path(tmp))


if __name__ == "__main__": unittest.main()
