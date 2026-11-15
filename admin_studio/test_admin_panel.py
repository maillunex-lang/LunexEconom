"""Admin panel regression guards: routes gated and every tab connected."""
import unittest
from pathlib import Path

from game_client import GET_PATHS, POST_PATHS, GameAdminError, GameClient

ROOT = Path(__file__).parent / "static"

class AdminPanelTests(unittest.TestCase):
    def test_screens_have_navigation_targets(self):
        html=(ROOT/"index.html").read_text(encoding="utf-8")
        js=(ROOT/"navigation.js").read_text(encoding="utf-8")
        for name in ("dashboard","online","flags","parameters","revisions","maintenance"):
            self.assertIn('data-view="'+name+'"',html)
            self.assertIn('data-panel="'+name+'"',html)
            self.assertIn('"'+name+'"',js)
        self.assertIn('src="admin-panel.js"',html)
        self.assertIn('id="client-save"',html)
        self.assertIn('id="client-hqtitle"',html)
    def test_no_unsafe_html_and_no_saved_credentials(self):
        js=(ROOT/"admin-panel.js").read_text(encoding="utf-8")
        self.assertNotIn(".innerHTML",js)
        self.assertNotIn("localStorage",js)
        self.assertNotIn("sessionStorage",js)
        self.assertIn("expected_revision",js)
        self.assertIn("confirm",js)
    def test_game_admin_whitelist(self):
        for path in ("/admin/config","/admin/revisions","/admin/online",
                     "/admin/status","/admin/online/players","/admin/config/candidate"):
            self.assertIn(path,GET_PATHS)
        for path in ("/admin/config/set","/admin/config/rollback",
                     "/admin/config/client","/admin/config/sign"):
            self.assertIn(path,POST_PATHS)
        client=GameClient(token="z"*32)
        with self.assertRaises(GameAdminError):
            client.request("POST","/admin/config",payload={})
        with self.assertRaises(GameAdminError):
            client.request("POST","/admin/config/evil",payload={})

if __name__=="__main__":unittest.main()
