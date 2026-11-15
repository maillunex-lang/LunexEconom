import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("build_strings", ROOT / "tools/build_strings.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

class StringsTest(unittest.TestCase):
    def test_every_documented_key_is_built(self):
        found = builder.collect()
        built = json.loads((ROOT / "client/data/strings.json").read_text(encoding="utf-8"))
        self.assertEqual(found, built)
        self.assertGreaterEqual(len(found), 280)

    def test_placeholders_and_duplicate_guards(self):
        placeholders = re.compile(r"\{([a-z][a-z0-9_]*)\}")
        built = json.loads((ROOT / "client/data/strings.json").read_text(encoding="utf-8"))
        documented = builder.collect()
        self.assertEqual({k:set(placeholders.findall(v)) for k,v in built.items()},
                         {k:set(placeholders.findall(v)) for k,v in documented.items()})
        self.assertEqual({"version"},set(placeholders.findall(built["update.screen.available"])))

    def test_all_keys_from_all_three_sources(self):
        values = builder.collect()
        for source in builder.SOURCES:
            for row in (ROOT / source).read_text(encoding="utf-8").splitlines():
                if "|" in row:
                    key = row.split("|",1)[0].strip()
                    if builder.KEY.fullmatch(key):
                        self.assertIn(key,values)
