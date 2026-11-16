"""Unit tests for UI proposal validator."""
import unittest
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.validate_ui_proposal import relative_luminance, contrast_ratio, check_tokens

class TestUIProposal(unittest.TestCase):
    def test_luminance(self):
        self.assertAlmostEqual(relative_luminance("FFFFFF"), 1.0, places=2)
        self.assertAlmostEqual(relative_luminance("000000"), 0.0, places=2)

    def test_contrast_dark_text(self):
        # High contrast expected
        ratio = contrast_ratio("EEF5E8", "0A201B")
        self.assertGreaterEqual(ratio, 4.5)

    def test_tokens_structure(self):
        tokens_path = Path(__file__).resolve().parent.parent.parent / "client" / "theme" / "tokens_proposed.json"
        if not tokens_path.exists():
            self.skipTest("tokens not present in test context")
        with open(tokens_path) as f:
            data = json.load(f)
        errs = check_tokens(data)
        self.assertEqual(errs, [], f"Token errors: {errs}")

if __name__ == "__main__":
    unittest.main()
