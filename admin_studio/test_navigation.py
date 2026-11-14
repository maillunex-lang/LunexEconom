"""Static checks for Android-friendly World Studio navigation."""
import unittest
from pathlib import Path

ROOT = Path(__file__).parent / "static"

class NavigationTests(unittest.TestCase):
    def test_sections_and_navigation_match(self):
        html = (ROOT / "index.html").read_text()
        for name in ("overview", "players", "cities", "world", "assets", "patch", "audit"):
            self.assertIn('data-view="' + name + '"', html)
            self.assertIn('data-panel="' + name + '"', html)
        self.assertIn('src="navigation.js"', html)

    def test_accessibility_and_no_token_persistence(self):
        js = (ROOT / "navigation.js").read_text()
        css = (ROOT / "style.css").read_text()
        self.assertIn('aria-pressed', js)
        self.assertIn('hashchange', js)
        self.assertNotIn('localStorage', js)
        self.assertNotIn('sessionStorage', js)
        self.assertIn('safe-area-inset-bottom', css)
        self.assertIn('[hidden]{display:none!important}', css)
