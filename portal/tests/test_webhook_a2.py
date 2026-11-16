"""Signed webhook and CI-gated auto-accept contract tests."""
import hashlib
import hmac
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portal import auth, bootstrap, db
from portal.app import create_app
from portal.tests.test_portal import PW, call

BASE = '/createportal'
SHA = 'a' * 40
BAD_SHA = 'b' * 40


class A2(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'portal.sqlite')
        self.secret = Path(self.temp.name) / 'secret'
        self.secret.write_bytes(b'test-only-secret-value')
        c = db.connect(self.path)
        auth.set_password(c, 'owner', PW)
        c.close()
        self.plan = bootstrap.STARTER_PLAN
        self.app = create_app(self.path, base=BASE, webhook_enabled=True, webhook_secret_file=self.secret,
                              fetch=lambda url, token: json.dumps(self.plan))
        r = call(self.app, 'POST', BASE + '/api/login', {'username': 'owner', 'password': PW})
        self.cookie = r['headers']['Set-Cookie'].split(';')[0]
        self.csrf = r['json']['csrf']
        r = self.api('POST', '/api/projects', {'slug': 'demo-project', 'name': 'Demo', 'repo': 'owner/repo'})
        self.assertEqual(r['status'], 201)
        self.api('POST', '/api/projects/demo-project/plan', {'plan': self.plan})
        self.counter = 0

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def api(self, method, path, data=None, cookie=None, csrf=None):
        return call(self.app, method, BASE + path, data, self.cookie if cookie is None else cookie,
                    self.csrf if csrf is None else csrf)

    def hook(self, kind, payload, signed=True, delivery=None, signature=None, app=None, size=None):
        self.counter += 1
        raw = json.dumps(payload).encode()
        signature = signature if signature is not None else ('sha256=' + hmac.new(self.secret.read_bytes(), raw, hashlib.sha256).hexdigest() if signed else '')
        result = {}
        def start(status, headers):
            result['status'] = int(status.split()[0])
        env = {'REQUEST_METHOD': 'POST', 'PATH_INFO': BASE + '/hook/github', 'CONTENT_LENGTH': str(len(raw) if size is None else size),
               'wsgi.input': io.BytesIO(raw), 'HTTP_X_HUB_SIGNATURE_256': signature,
               'HTTP_X_GITHUB_DELIVERY': delivery or f'delivery-{self.counter:08d}', 'HTTP_X_GITHUB_EVENT': kind}
        result['body'] = b''.join((app or self.app)(env, start))
        return result

    def repo(self):
        return {'full_name': 'owner/repo'}

    def pr(self, merged=True, branch='v2/A1-security', title='Task A1', sha=SHA, base='main', number=12, action=None):
        return {'repository': self.repo(), 'number': number, 'action': action or ('closed' if merged else 'opened'),
                'pull_request': {'title': title, 'merged': merged, 'merge_commit_sha': sha,
                                 'head': {'ref': branch, 'sha': BAD_SHA, 'repo': self.repo()},
                                 'base': {'ref': base, 'repo': self.repo()}}}

    def ci(self, state='success', sha=SHA, kind='workflow_run', name='unit', status=None):
        return {'repository': self.repo(), kind: {'head_sha': sha, 'name': name, 'status': status or 'completed',
                                                   'conclusion': state, 'app': {'slug': name}}}

    def task(self):
        return self.api('GET', '/api/projects/demo-project')['json']['state'].get('A1', {})

    def events(self):
        return self.api('GET', '/api/projects/demo-project/events')['json']['events']

    def test_unsigned(self):
        self.assertEqual(self.hook('pull_request', self.pr(), signed=False)['status'], 401)
        self.assertEqual(self.task(), {})

    def test_bad_signature(self):
        self.assertEqual(self.hook('pull_request', self.pr(), signature='sha256='+'0'*64)['status'], 401)
        self.assertEqual(self.task(), {})

    def test_missing_secret(self):
        self.secret.unlink()
        self.assertEqual(self.hook('pull_request', self.pr(), signature='sha256='+'0'*64)['status'], 401)

    def test_repeated_delivery(self):
        p = self.pr()
        self.assertIn(b'processed', self.hook('pull_request', p, delivery='delivery-000001')['body'])
        self.assertIn(b'duplicate', self.hook('pull_request', p, delivery='delivery-000001')['body'])
        self.assertEqual(len(self.events()), 2)  # PR merged + waiting CI

    def test_unknown_repo(self):
        p = self.pr()
        p['repository']['full_name'] = 'other/repo'
        self.assertEqual(self.hook('pull_request', p)['status'], 200)
        self.assertEqual(self.task(), {})

    def test_missing_repo(self):
        self.assertEqual(self.hook('push', {})['status'], 400)

    def test_invalid_delivery(self):
        self.assertEqual(self.hook('push', {'repository': self.repo()}, delivery='bad')['status'], 400)

    def test_oversize(self):
        self.assertEqual(self.hook('push', {'repository': self.repo()}, size=1_000_001)['status'], 413)

    def test_push_main_updates_plan(self):
        self.assertEqual(self.hook('push', {'repository': self.repo(), 'ref': 'refs/heads/main'})['status'], 200)
        self.assertIn('plan.synced', [e['kind'] for e in self.events()])

    def test_push_other_branch_ignored(self):
        self.hook('push', {'repository': self.repo(), 'ref': 'refs/heads/dev'})
        self.assertEqual(self.events(), [])

    def test_push_invalid_preserves_old_plan(self):
        self.plan = {'bad': True}
        self.hook('push', {'repository': self.repo(), 'ref': 'refs/heads/main'})
        self.assertIn('plan.sync_failed', [e['kind'] for e in self.events()])
        self.assertTrue(self.api('GET', '/api/projects/demo-project')['json']['packages'])

    def test_pr_link_branch(self):
        self.hook('pull_request', self.pr(merged=False))
        self.assertEqual(self.task()['pr']['number'], 12)

    def test_pr_link_title(self):
        self.hook('pull_request', self.pr(branch='feature/other', title='Implements A1 for portal'))
        self.assertEqual(self.task()['pr']['number'], 12)

    def test_pr_unmatched(self):
        self.hook('pull_request', self.pr(branch='feature/unknown', title='Unrelated'))
        self.assertEqual(self.task(), {})

    def test_pr_merged_sets_sha_only_without_ci(self):
        self.hook('pull_request', self.pr())
        self.assertEqual(self.task()['sha'], SHA)
        self.assertEqual(self.task()['merged'], 1)
        self.assertNotEqual(self.task()['status'], 'accepted')

    def test_pr_wrong_base_no_merged_marker(self):
        self.hook('pull_request', self.pr(base='develop'))
        self.assertEqual(self.task()['merged'], 0)

    def test_ci_without_pr(self):
        self.hook('workflow_run', self.ci())
        self.assertEqual(self.task(), {})

    def test_ci_visible(self):
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci())
        self.assertEqual(self.task()['ci']['state'], 'success')

    def test_settings_default(self):
        r = self.api('GET', '/api/projects/demo-project/settings')
        self.assertEqual(r['json']['auto_accept'], True)
        self.assertEqual(r['json']['auto_accept_require_checklist'], False)

    def test_settings_update(self):
        r = self.api('POST', '/api/projects/demo-project/settings', {'auto_accept': False})
        self.assertEqual(r['json']['auto_accept'], False)

    def test_settings_csrf(self):
        self.assertEqual(self.api('POST', '/api/projects/demo-project/settings', {'auto_accept': False}, csrf='bad')['status'], 403)

    def test_settings_session(self):
        self.assertEqual(self.api('GET', '/api/projects/demo-project/settings', cookie='')['status'], 401)

    def test_settings_reject_string_bool(self):
        self.assertEqual(self.api('POST', '/api/projects/demo-project/settings', {'auto_accept': 'false'})['status'], 400)

    def test_events_session(self):
        self.assertEqual(self.api('GET', '/api/projects/demo-project/events', cookie='')['status'], 401)

    def test_feature_off(self):
        other = create_app(self.path, base=BASE)
        try:
            self.assertEqual(self.hook('pull_request', self.pr(), app=other)['status'], 404)
        finally:
            other.close()

    # Auto-accept: 12+ independent regression cases.
    def test_auto_green_after_merge(self):
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci())
        self.assertEqual(self.task()['status'], 'accepted')

    def test_auto_green_before_merge(self):
        self.hook('workflow_run', self.ci())
        self.hook('pull_request', self.pr())
        self.assertEqual(self.task()['status'], 'accepted')

    def test_auto_red(self):
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci('failure'))
        self.assertNotEqual(self.task()['status'], 'accepted')
        self.assertIn('ci.failed', [x['kind'] for x in self.events()])

    def test_auto_pending(self):
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci(status='in_progress'))
        self.assertNotEqual(self.task()['status'], 'accepted')

    def test_auto_disabled(self):
        self.api('POST', '/api/projects/demo-project/settings', {'auto_accept': False})
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci())
        self.assertEqual(self.task()['merged'], 1)
        self.assertNotEqual(self.task()['status'], 'accepted')

    def test_auto_repeat_delivery(self):
        self.hook('pull_request', self.pr())
        p = self.ci()
        self.hook('workflow_run', p, delivery='delivery-repeat-1')
        self.hook('workflow_run', p, delivery='delivery-repeat-1')
        self.assertEqual(sum(x['kind'] == 'task.auto_accept' for x in self.events()), 1)

    def test_auto_different_project(self):
        self.hook('pull_request', self.pr(branch='v2/B2-other', title='B2'))
        self.hook('workflow_run', self.ci())
        self.assertEqual(self.task(), {})

    def test_auto_manual_accepted_preserved(self):
        self.api('POST', '/api/projects/demo-project/status', {'id': 'A1', 'status': 'accepted', 'note': 'manual'})
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci())
        self.assertEqual(self.task()['note'], 'manual')
        self.assertEqual(sum(x['kind'] == 'task.auto_accept' for x in self.events()), 0)

    def test_auto_wrong_base(self):
        self.hook('pull_request', self.pr(base='develop'))
        self.hook('workflow_run', self.ci())
        self.assertNotEqual(self.task()['status'], 'accepted')

    def test_auto_wrong_sha(self):
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci(sha=BAD_SHA))
        self.assertNotEqual(self.task()['status'], 'accepted')

    def test_auto_no_ci(self):
        self.hook('pull_request', self.pr())
        self.assertNotEqual(self.task()['status'], 'accepted')

    def test_auto_two_checks_one_red(self):
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci())
        self.hook('check_suite', self.ci('failure', kind='check_suite'))
        # Once accepted, later CI failures cannot silently unaccept: CI ordering matters.
        self.assertEqual(self.task()['status'], 'accepted')

    def test_auto_required_check_missing(self):
        self.api('POST', '/api/projects/demo-project/settings', {'required_checks': ['unit', 'integration']})
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci())
        self.assertNotEqual(self.task()['status'], 'accepted')

    def test_auto_required_check_present(self):
        self.api('POST', '/api/projects/demo-project/settings', {'required_checks': ['unit']})
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci())
        self.assertEqual(self.task()['status'], 'accepted')

    def test_auto_checklist_gate(self):
        self.api('POST', '/api/projects/demo-project/settings', {'auto_accept_require_checklist': True})
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci())
        self.assertNotEqual(self.task()['status'], 'accepted')

    def test_auto_planned_note(self):
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci())
        self.assertIn('без отметки выдачи', self.task()['note'])

    def test_auto_issued(self):
        self.api('POST', '/api/projects/demo-project/status', {'id': 'A1', 'status': 'issued'})
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci())
        self.assertEqual(self.task()['status'], 'accepted')

    def test_auto_submitted(self):
        self.api('POST', '/api/projects/demo-project/status', {'id': 'A1', 'status': 'submitted'})
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci())
        self.assertEqual(self.task()['status'], 'accepted')

    def test_auto_red_and_green_observed_before_merge(self):
        self.hook('workflow_run', self.ci('success'))
        self.hook('check_suite', self.ci('failure', kind='check_suite'))
        self.hook('pull_request', self.pr())
        self.assertNotEqual(self.task()['status'], 'accepted')

    def test_auto_pending_and_green_observed_before_merge(self):
        self.hook('workflow_run', self.ci('success'))
        self.hook('check_suite', self.ci(status='queued', kind='check_suite'))
        self.hook('pull_request', self.pr())
        self.assertNotEqual(self.task()['status'], 'accepted')

    def test_auto_red_then_green_recovery(self):
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci('failure'))
        self.assertNotEqual(self.task()['status'], 'accepted')
        self.hook('workflow_run', self.ci('success'))
        self.assertEqual(self.task()['status'], 'accepted')

    def test_auto_no_duplicate_accept_new_delivery(self):
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci())
        self.hook('workflow_run', self.ci())
        self.assertEqual(sum(e['kind'] == 'task.auto_accept' for e in self.events()), 1)

    def test_auto_audit(self):
        self.hook('pull_request', self.pr())
        self.hook('workflow_run', self.ci())
        audit = self.api('GET', '/api/audit')['json']['entries']
        self.assertIn('task.auto_accept', [x['action'] for x in audit])


if __name__ == '__main__':
    unittest.main()
