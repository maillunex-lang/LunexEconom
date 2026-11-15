import io
import contextlib
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
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
            (root/'env').write_text('LUNEX_SHA='+'b'*40+'\n')
            with patch.object(updater,'STATE',root/'state'),patch.object(updater,'SERVER_DIR',target),patch.object(updater,'stage_tree') as stage,patch.object(updater,'restart',side_effect=RuntimeError('restart failed')),patch.object(updater,'ENV_FILE',root/'env'):
                def populate(sha,names,folder):
                    (folder/'platform').mkdir()
                    (folder/'platform'/'api.py').write_text('new nested')
                    (folder/'game_server.py').write_text('new')
                stage.side_effect=populate
                with self.assertRaises(RuntimeError): updater.deploy('a'*40,['platform/api.py','game_server.py'])
                self.assertEqual((target/'platform'/'api.py').read_text(),'old nested')
                self.assertEqual((target/'game_server.py').read_text(),'old')

    def test_atomic_sha_preserves_secrets_order_permissions(self):
        with tempfile.TemporaryDirectory() as t:
            env=Path(t)/'v2.env'
            env.write_bytes(b'# comment\nPASSWORD=FAKE_PRIVATE_SECRET\nLUNEX_SHA=' + b'a'*40 + b'\nFLAG=yes\n')
            env.chmod(0o640)
            with patch.object(updater,'ENV_FILE',env):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    old=updater.atomic_sha('b'*40)
            self.assertEqual(old,'a'*40)
            self.assertEqual(stat.S_IMODE(env.stat().st_mode),0o640)
            self.assertEqual(env.read_bytes(),b'# comment\nPASSWORD=FAKE_PRIVATE_SECRET\nLUNEX_SHA='+b'b'*40+b'\nFLAG=yes\n')
            self.assertNotIn('FAKE_PRIVATE_SECRET',output.getvalue())

    def test_deploy_success_sha_and_pip(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); target=root/'server'; target.mkdir()
            (target/'game_server.py').write_text('old')
            (target/'requirements.txt').write_text('old-package==1')
            env=root/'env'; env.write_text('PASSWORD=FAKE_PRIVATE_SECRET\nLUNEX_SHA='+'a'*40+'\n')
            def stage(sha,names,folder):
                (folder/'game_server.py').write_text('new')
                (folder/'requirements.txt').write_text('new-package==2')
            with patch.object(updater,'STATE',root/'state'),patch.object(updater,'SERVER_DIR',target),patch.object(updater,'ENV_FILE',env),patch.object(updater,'stage_tree',side_effect=stage),patch.object(updater,'restart') as restart,patch.object(updater,'run',return_value=Mock(returncode=0)) as run,patch.object(updater,'health_sha',return_value=True):
                updater.deploy('b'*40,['game_server.py','requirements.txt'])
                restart.assert_called_once()
                self.assertEqual(run.call_count,1)
                self.assertIn('pip',run.call_args.args[0])
            self.assertEqual((target/'game_server.py').read_text(),'new')
            self.assertIn('LUNEX_SHA='+'b'*40,env.read_text())

    def test_sha_mismatch_rolls_back_code_and_env(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); target=root/'server'; target.mkdir()
            (target/'game_server.py').write_text('old')
            env=root/'env'; env.write_text('PASSWORD=FAKE_PRIVATE_SECRET\nLUNEX_SHA='+'a'*40+'\n')
            def stage(sha,names,folder): (folder/'game_server.py').write_text('new')
            output=io.StringIO()
            with patch.object(updater,'STATE',root/'state'),patch.object(updater,'SERVER_DIR',target),patch.object(updater,'ENV_FILE',env),patch.object(updater,'stage_tree',side_effect=stage),patch.object(updater,'restart') as restart,patch.object(updater,'health_sha',side_effect=[False,True]),contextlib.redirect_stderr(output):
                with self.assertRaises(RuntimeError):
                    updater.deploy('b'*40,['game_server.py'])
                self.assertEqual(restart.call_count,2)
            self.assertEqual((target/'game_server.py').read_text(),'old')
            self.assertIn('LUNEX_SHA='+'a'*40,env.read_text())
            self.assertNotIn('FAKE_PRIVATE_SECRET',output.getvalue())

    def test_stale_state_refuses_deploy(self):
        with tempfile.TemporaryDirectory() as t:
            state=Path(t); (state/'deployed-sha').write_text('a'*40)
            with patch.object(updater,'STATE',state),patch.object(updater,'api',return_value={'sha':'b'*40}),patch.object(updater,'health_sha',return_value=False),patch.object(updater,'deploy') as deploy:
                with self.assertRaisesRegex(RuntimeError,'Stale'):
                    updater.main()
                deploy.assert_not_called()

    def test_pip_failure_rolls_back_without_restart(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); target=root/'server'; target.mkdir()
            (target/'game_server.py').write_text('old')
            (target/'requirements.txt').write_text('old')
            env=root/'env'; env.write_text('PASSWORD=FAKE_PRIVATE_SECRET\nLUNEX_SHA='+'a'*40+'\n')
            def stage(sha,names,folder):
                (folder/'game_server.py').write_text('new')
                (folder/'requirements.txt').write_text('new')
            with patch.object(updater,'STATE',root/'state'),patch.object(updater,'SERVER_DIR',target),patch.object(updater,'ENV_FILE',env),patch.object(updater,'stage_tree',side_effect=stage),patch.object(updater,'run',return_value=Mock(returncode=1,stderr='FAKE_PRIVATE_SECRET')),patch.object(updater,'restart') as restart:
                with self.assertRaisesRegex(RuntimeError,'dependency installation'):
                    updater.deploy('b'*40,['game_server.py','requirements.txt'])
                restart.assert_not_called()
            self.assertEqual((target/'game_server.py').read_text(),'old')
            self.assertIn('LUNEX_SHA='+'a'*40,env.read_text())

    def test_rollback_restores_code_even_when_env_restore_fails(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); target=root/'server'; target.mkdir()
            (target/'game_server.py').write_text('old')
            env=root/'env'; env.write_text('LUNEX_SHA='+'a'*40+'\\n')
            def stage(sha,names,folder):
                (folder/'game_server.py').write_text('new')
            original_atomic=updater.atomic_sha
            calls=[0]
            def failing_restore(sha):
                calls[0]+=1
                if calls[0]==2:
                    raise OSError('FAKE_PRIVATE_SECRET')
                return original_atomic(sha)
            with patch.object(updater,'STATE',root/'state'),patch.object(updater,'SERVER_DIR',target),patch.object(updater,'ENV_FILE',env),patch.object(updater,'stage_tree',side_effect=stage),patch.object(updater,'atomic_sha',side_effect=failing_restore),patch.object(updater,'restart',side_effect=[None,None]) as restart,patch.object(updater,'health_sha',side_effect=[False,True]),contextlib.redirect_stderr(io.StringIO()) as output:
                with self.assertRaisesRegex(RuntimeError,'rollback incomplete'):
                    updater.deploy('b'*40,['game_server.py'])
                self.assertEqual(restart.call_count,2)
            self.assertEqual((target/'game_server.py').read_text(),'old')
            self.assertNotIn('FAKE_PRIVATE_SECRET',output.getvalue())

if __name__=='__main__': unittest.main()
