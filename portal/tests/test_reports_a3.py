"""A3: isolated report/review/metrics API integration tests."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path

from portal import auth, bootstrap, db
from portal.app import create_app
from portal.tests.test_portal import call

BASE = '/createportal/api'


class ReportsA3(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'a3.sqlite')
        conn = db.connect(self.path)
        auth.set_password(conn, 'owner', 'fixture-password-long')
        conn.close()
        self.app = create_app(self.path, base='/createportal', reports_enabled=True)
        result = call(self.app, 'POST', '/api/login', {'username':'owner','password':'fixture-password-long'})
        self.cookie = result['headers']['Set-Cookie'].split(';')[0]
        self.csrf = result['json']['csrf']
        self.request('POST', BASE + '/projects', {'slug':'alpha-proj','name':'Alpha'})
        self.request('POST', BASE + '/projects', {'slug':'beta-proj','name':'Beta'})
        plan = copy.deepcopy(bootstrap.STARTER_PLAN)
        for slug in ('alpha-proj','beta-proj'):
            self.request('POST', BASE + '/projects/' + slug + '/plan', {'plan':plan})
        self.prefix = BASE + '/projects/alpha-proj'
        self.report = self.prefix + '/tasks/A1/report'
        self.review = self.prefix + '/tasks/A1/review'
        self.status = self.prefix + '/status'

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, *, cookie=None, csrf=None):
        return call(self.app, method, path, body, cookie=self.cookie if cookie is None else cookie,
                    csrf=self.csrf if csrf is None else csrf)

    def ready(self):
        self.request('POST', self.status, {'id':'A1','status':'issued'})
        self.request('POST', self.status, {'id':'A1','status':'submitted'})

    def checklist(self, checked=True, ci='success'):
        return {'items':[{'text':x,'checked':checked} for x in ['Проверка','CI']], 'ci_state':ci}

    def test_01_report_write(self):
        self.assertEqual(self.request('POST',self.report,{'text':'Сделано'})['status'],200)
    def test_02_report_read(self):
        self.request('POST',self.report,{'text':'Сделано'})
        self.assertEqual(self.request('GET',self.report)['json']['report']['body'],'Сделано')
    def test_03_report_empty(self):
        self.assertIsNone(self.request('GET',self.report)['json']['report'])
    def test_04_report_update(self):
        self.request('POST',self.report,{'text':'Первая'})
        self.request('POST',self.report,{'text':'Вторая'})
        self.assertEqual(self.request('GET',self.report)['json']['report']['body'],'Вторая')
    def test_05_report_isolation(self):
        self.request('POST',self.report,{'text':'Только Alpha'})
        self.assertIsNone(self.request('GET',BASE+'/projects/beta-proj/tasks/A1/report')['json']['report'])
    def test_06_report_url(self):
        self.assertEqual(self.request('POST',self.report,{'pr_url':'https://github.com/o/r/pull/2'})['status'],200)
    def test_07_report_bad_url(self):
        self.assertEqual(self.request('POST',self.report,{'pr_url':'https://evil.example/pull/2'})['status'],400)
    def test_08_report_too_long(self):
        self.assertEqual(self.request('POST',self.report,{'text':'x'*20001})['status'],400)
    def test_09_report_invalid_type(self):
        self.assertEqual(self.request('POST',self.report,{'text':5})['status'],400)
    def test_10_report_unknown_task(self):
        self.assertEqual(self.request('GET',self.prefix+'/tasks/Z99/report')['status'],404)
    def test_11_report_no_session(self):
        self.assertEqual(self.request('GET',self.report,cookie='')['status'],401)
    def test_12_report_csrf(self):
        self.assertEqual(self.request('POST',self.report,{'text':'x'},csrf='bad')['status'],403)
    def test_13_review_default(self):
        self.assertEqual(len(self.request('GET',self.review)['json']['review']['items']),5)
    def test_14_review_write(self):
        self.assertEqual(self.request('POST',self.review,self.checklist())['status'],200)
    def test_15_review_read(self):
        self.request('POST',self.review,self.checklist())
        self.assertTrue(self.request('GET',self.review)['json']['review']['items'][0]['checked'])
    def test_16_review_isolation(self):
        self.request('POST',self.review,self.checklist())
        self.assertFalse(self.request('GET',BASE+'/projects/beta-proj/tasks/A1/review')['json']['review']['items'][0]['checked'])
    def test_17_review_invalid_items(self):
        self.assertEqual(self.request('POST',self.review,{'items':[]})['status'],400)
    def test_18_review_invalid_ci(self):
        self.assertEqual(self.request('POST',self.review,{'ci_state':'greenish'})['status'],400)
    def test_19_accept_no_checklist(self):
        self.ready()
        self.assertEqual(self.request('POST',self.status,{'id':'A1','status':'accepted'})['status'],409)
    def test_20_accept_incomplete(self):
        self.ready();self.request('POST',self.review,self.checklist(False))
        self.assertEqual(self.request('POST',self.status,{'id':'A1','status':'accepted'})['json']['error'],'checklist_incomplete')
    def test_21_accept_red_ci(self):
        self.ready();self.request('POST',self.review,self.checklist(True,'red'))
        self.assertEqual(self.request('POST',self.status,{'id':'A1','status':'accepted'})['json']['error'],'ci_red')
    def test_22_accept_green(self):
        self.ready();self.request('POST',self.review,self.checklist())
        self.assertEqual(self.request('POST',self.status,{'id':'A1','status':'accepted'})['status'],200)
    def test_23_accept_manual(self):
        self.ready()
        self.assertEqual(self.request('POST',self.status,{'id':'A1','status':'accepted','manual':True})['status'],200)
        self.assertTrue(any(x['action']=='task.manual_accept' for x in db.recent_audit(db.connect(self.path, reports=True))))
    def test_24_accept_bad_manual(self):
        self.ready()
        self.assertEqual(self.request('POST',self.status,{'id':'A1','status':'accepted','manual':'true'})['status'],400)
    def test_25_return_remarks_required(self):
        self.ready()
        self.assertEqual(self.request('POST',self.review,{'return':True,'remarks':' '})['status'],400)
    def test_26_return_issued(self):
        self.ready();self.request('POST',self.review,{'return':True,'remarks':'Исправить тесты'})
        self.assertEqual(self.request('GET',self.prefix)['json']['state']['A1']['status'],'issued')
    def test_27_return_count(self):
        self.ready();self.request('POST',self.review,{'return':True,'remarks':'Первый'})
        self.request('POST',self.status,{'id':'A1','status':'submitted'})
        self.request('POST',self.review,{'return':True,'remarks':'Второй'})
        self.assertEqual(self.request('GET',self.review)['json']['review']['revision_count'],2)
    def test_28_return_not_submitted(self):
        self.assertEqual(self.request('POST',self.review,{'return':True,'remarks':'Исправить'})['status'],409)
    def test_29_events(self):
        self.request('POST',self.report,{'text':'Текст'})
        self.assertTrue(any(x['kind']=='task.report' for x in self.request('GET',self.prefix+'/events')['json']['events']))
    def test_30_events_isolation(self):
        self.request('POST',self.report,{'text':'Текст'})
        self.assertEqual(self.request('GET',BASE+'/projects/beta-proj/events')['json']['events'],[])
    def test_31_metrics_empty(self):
        self.assertEqual(self.request('GET',BASE+'/metrics')['json']['metrics']['accepted_week'],0)
    def test_32_metrics_accepted(self):
        self.ready();self.request('POST',self.status,{'id':'A1','status':'accepted','manual':True})
        self.assertEqual(self.request('GET',BASE+'/metrics')['json']['metrics']['accepted_week'],1)
    def test_33_metrics_awaiting(self):
        self.ready()
        self.assertEqual(self.request('GET',self.prefix+'/metrics')['json']['metrics']['awaiting_owner'],1)
    def test_34_metrics_red(self):
        self.request('POST',self.review,self.checklist(True,'red'))
        self.assertEqual(self.request('GET',BASE+'/metrics')['json']['metrics']['red_ci'],1)
    def test_35_metrics_durations(self):
        self.ready();self.request('POST',self.status,{'id':'A1','status':'accepted','manual':True})
        c = db.connect(self.path, reports=True)
        now = time.time()
        c.execute('UPDATE task_state SET issued_at=?,submitted_at=?,accepted_at=? WHERE project_slug=? AND pkg_id=?', (now-120,now-60,now,'alpha-proj','A1'))
        c.close()
        m = self.request('GET',self.prefix+'/metrics')['json']['metrics']
        self.assertAlmostEqual(m['avg_issue_to_submit_seconds'],60)
        self.assertAlmostEqual(m['avg_submit_to_accept_seconds'],60)
    def test_36_metrics_return_rate(self):
        self.ready();self.request('POST',self.review,{'return':True,'remarks':'Повторить'})
        self.assertEqual(self.request('GET',self.prefix+'/metrics')['json']['metrics']['return_rate'],1)
    def test_37_metrics_isolation(self):
        self.ready()
        self.assertEqual(self.request('GET',BASE+'/projects/beta-proj/metrics')['json']['metrics']['awaiting_owner'],0)
    def test_38_review_no_session(self):
        self.assertEqual(self.request('GET',self.review,cookie='')['status'],401)
    def test_39_review_csrf(self):
        self.assertEqual(self.request('POST',self.review,self.checklist(),csrf='bad')['status'],403)
    def test_40_metrics_no_session(self):
        self.assertEqual(self.request('GET','/api/metrics',cookie='')['status'],401)
    def test_41_review_bad_remarks(self):
        self.assertEqual(self.request('POST',self.review,{'remarks':'x'*3001})['status'],400)
    def test_42_review_bad_checkbox(self):
        self.assertEqual(self.request('POST',self.review,{'items':[{'text':'CI','checked':1}]})['status'],400)
    def test_43_review_unknown_task(self):
        self.assertEqual(self.request('GET',self.prefix+'/tasks/Z99/review')['status'],404)
    def test_44_metrics_unknown_project(self):
        self.assertEqual(self.request('GET',BASE+'/projects/ghost-proj/metrics')['status'],404)
    def test_45_report_extra_field(self):
        self.assertEqual(self.request('POST',self.report,{'text':'x','secret':'x'})['status'],400)
    def test_46_review_extra_field(self):
        self.assertEqual(self.request('POST',self.review,{'ci_state':'success','secret':'x'})['status'],400)


if __name__ == '__main__':
    unittest.main()
