import json
import tempfile
import unittest
from pathlib import Path

import stamp_build

PRESET = '[preset.0.options]\n\nversion/code=13\nversion/name="0.2.8.1-main-menu-test"\npackage/unique_name="ru.lunex.bashkiriahoneyoil"\n'


class StampBuildTests(unittest.TestCase):
    def make_root(self, preset=PRESET):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "client").mkdir()
        (root / "client" / "export_presets.cfg").write_text(preset, encoding="utf-8")
        return root

    def test_stamps_preset_and_build_info(self):
        root = self.make_root()
        self.assertEqual(stamp_build.stamp(root, 160, "0.3.160"), (160, "0.3.160"))
        text = (root / "client" / "export_presets.cfg").read_text(encoding="utf-8")
        self.assertIn("version/code=160", text)
        self.assertIn('version/name="0.3.160"', text)
        self.assertIn('package/unique_name="ru.lunex.bashkiriahoneyoil"', text)       # untouched
        info = json.loads((root / "client" / "build_info.json").read_text(encoding="utf-8"))
        self.assertEqual(info, {"version_code": 160, "version_name": "0.3.160"})

    def test_cli_derives_name_from_count(self):
        root = self.make_root()
        self.assertEqual(stamp_build.main(["--count", "200", "--root", str(root)]), 0)
        self.assertIn("version/code=200", (root / "client" / "export_presets.cfg").read_text(encoding="utf-8"))

    def test_rejects_bad_values(self):
        root = self.make_root()
        for code, name in ((0, "0.3.0"), (stamp_build.MAX_CODE + 1, "0.3.1"), (5, 'x"; rm'), (5, "")):
            with self.assertRaises(ValueError):
                stamp_build.stamp(root, code, name)

    def test_requires_exactly_one_version_line(self):
        for preset in ("[preset.0.options]\n", PRESET + "version/code=1\n"):
            root = self.make_root(preset)
            with self.assertRaises(ValueError):
                stamp_build.stamp(root, 10, "0.3.10")

    def test_repository_preset_is_stampable(self):
        repo = Path(__file__).resolve().parent.parent
        text = (repo / "client" / "export_presets.cfg").read_text(encoding="utf-8")
        self.assertEqual(text.count("\nversion/code="), 1)
        self.assertEqual(text.count("\nversion/name="), 1)
        info = json.loads((repo / "client" / "build_info.json").read_text(encoding="utf-8"))
        self.assertIn("version_code", info)


if __name__ == "__main__":
    unittest.main()
