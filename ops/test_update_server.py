import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ops import update_server as updater

class TestUpdater(unittest.TestCase):
    def test_nested_modules_and_exclude_tests(self):
        paths = ['server/__init__.py','server/game_server.py','server/auth.py','server/registry.py','server/platform/api.py','server/data/products.json','server/migrations/202611150900_platform_accounts.sql','server/requirements.txt','server/tests/test_auth.py','server/clock/test_clock.py']
        names=updater.files_from_tree({'tree':[{'path':p,'type':'blob'} for p in paths]})
        self.assertIn('platform/api.py',names)
        self.assertIn('data/products.json',names)
        self.assertNotIn('tests/test_auth.py',names)
        self.assertNotIn('clock/test_clock.py',names)
        self.assertEqual(updater.WORKFLOW,'server-check.yml')

    def test_no_deploy_without_green_ci(self):
        with tempfile.TemporaryDirectory() as t,patch.object(updater,'STATE',Path(t)),patch.object(updater,'api',side_effect=[{'sha':'a'*40},{'workflow_runs':[]}]),patch.object(updater,'deploy') as deploy:
            self.assertEqual(updater.main(),0)
            deploy.assert_not_called()

    def test_rollback_restores_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            target=root/'target'
            (target/'platform').mkdir(parents=True)
            (target/'game_server.py').write_text('old')
            (target/'platform'/'api.py').write_text('old nested')
            with patch.object(updater,'STATE',root/'state'),patch.object(updater,'SERVER_DIR',target),patch.object(updater,'stage_tree') as stage,patch.object(updater,'restart',side_effect=RuntimeError('restart failed')):
                def populate(sha,names,folder):
                    (folder/'platform').mkdir()
                    (folder/'platform'/'api.py').write_text('new nested')
                    (folder/'game_server.py').write_text('new')
                stage.side_effect=populate
                with self.assertRaises(RuntimeError): updater.deploy('a'*40,['platform/api.py','game_server.py'])
                self.assertEqual((target/'platform'/'api.py').read_text(),'old nested')
                self.assertEqual((target/'game_server.py').read_text(),'old')

if __name__=='__main__': unittest.main()
