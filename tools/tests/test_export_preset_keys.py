"""The pinned manifest public key must be packaged into the APK (non-resource files need include_filter)."""
import re
import unittest
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ExportPresetKeys(unittest.TestCase):
    def test_update_public_key_is_packaged(self):
        cfg = (ROOT / "client" / "export_presets.cfg").read_text(encoding="utf-8")
        filters = re.findall(r'^include_filter="([^"]*)"', cfg, flags=re.M)
        self.assertTrue(filters, "export preset has no include_filter")
        patterns = [p.strip() for p in filters[0].split(",") if p.strip()]
        for key in ("config/update_public.pem", "security/config_public.pem"):
            self.assertTrue((ROOT / "client" / key).is_file(), key)
            self.assertTrue(any(fnmatch(key, p) for p in patterns), f"{key} is not exported: {patterns}")

    def test_models_are_packaged(self):
        cfg = (ROOT / "client" / "export_presets.cfg").read_text(encoding="utf-8")
        patterns = [p.strip() for p in re.findall(r'^include_filter="([^"]*)"', cfg, flags=re.M)[0].split(",")]
        for path in (ROOT / "client" / "models").rglob("*"):
            if path.suffix in (".glb", ".json"):
                rel = path.relative_to(ROOT / "client").as_posix()
                self.assertTrue(any(fnmatch(rel, p) for p in patterns), rel)


if __name__ == "__main__":
    unittest.main()
