"""PostgreSQL integration: consent, reversible deletion and ledger integrity."""
import os
import unittest
from uuid import uuid4
from server import db
from server.game_server import create_app
from server.tests.test_platform_v201 import request
from server.platform.consent import CONFIRM_PHRASE,finalize_pending
from server.ledger.api import reconcile

DSN=os.getenv('LUNEX_TEST_DATABASE_URL')

@unittest.skipUnless(DSN,'Requires isolated PostgreSQL test database')
class ConsentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=create_app(DSN)
    @classmethod
    def tearDownClass(cls): cls.app.close()

    def new_user(self,consent=True):
        name='c'+uuid4().hex[:15]
        data={'username':name,'email':name+'@example.test','password':'LongPassword123!'}
        if consent is not None: data['consent_personal_data']=consent
        result=request(type(self).app,'POST','/auth/register',data,ip='10.225.'+str(int(name[1:3],16))+'.1')
        return data,result

    def create(self):
        data,(status,profile)=self.new_user()
        self.assertEqual(status,201,profile)
        return data,profile

    def auth(self,data):
        code,response=request(type(self).app,'POST','/auth/login',{'username':data['username'],'password':data['password']},ip='10.225.0.4')
        self.assertEqual(code,200,response)
        return response

    def test_01_register_missing(self): self.assertEqual(self.new_user(None)[1][1]['error'],'consent_required')
    def test_02_register_false(self): self.assertEqual(self.new_user(False)[1][0],400)
    def test_03_register_null(self):
        data,_=self.new_user(None);data['consent_personal_data']=None
        self.assertEqual(request(type(self).app,'POST','/auth/register',data)[0],400)
    def test_04_register_string(self):
        data,_=self.new_user(None);data['consent_personal_data']='true'
        self.assertEqual(request(type(self).app,'POST','/auth/register',data)[0],400)
    def test_05_register_integer(self):
        data,_=self.new_user(None);data['consent_personal_data']=1
        self.assertEqual(request(type(self).app,'POST','/auth/register',data)[0],400)
    def test_06_register_true(self): self.create()
    def test_07_register_evidence(self):
        _,profile=self.create()
        with db.connect(DSN) as conn:
            rows=conn.execute('SELECT version FROM account_consents WHERE account_id=%s',(profile['id'],)).fetchall()
        self.assertEqual(rows,[('2026-11-16',)])
    def test_08_registration_timestamp(self):
        _,profile=self.create()
        with db.connect(DSN) as conn:
            self.assertIsNotNone(conn.execute('SELECT consent_at FROM accounts WHERE id=%s',(profile['id'],)).fetchone()[0])
    def test_09_login_current(self):
        data,_=self.create();self.assertIsNone(self.auth(data)['consent_required_version'])
    def test_10_login_old(self):
        data,profile=self.create()
        with db.connect(DSN) as conn:
            conn.execute('UPDATE accounts SET consent_version=NULL WHERE id=%s',(profile['id'],));conn.commit()
        self.assertEqual(self.auth(data)['consent_required_version'],'2026-11-16')
    def test_11_consent_unauthenticated(self):
        self.assertEqual(request(type(self).app,'POST','/auth/consent',{'consent_personal_data':True})[0],401)
    def test_12_consent_false(self):
        data,_=self.create();token=self.auth(data)['access_token']
        self.assertEqual(request(type(self).app,'POST','/auth/consent',{'consent_personal_data':False},token=token)[0],400)
    def test_13_consent_true(self):
        data,_=self.create();token=self.auth(data)['access_token']
        self.assertEqual(request(type(self).app,'POST','/auth/consent',{'consent_personal_data':True},token=token)[0],200)
    def test_14_consent_idempotent(self):
        data,profile=self.create();token=self.auth(data)['access_token']
        for _ in range(2): self.assertEqual(request(type(self).app,'POST','/auth/consent',{'consent_personal_data':True},token=token)[0],200)
        with db.connect(DSN) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM account_consents WHERE account_id=%s',(profile['id'],)).fetchone()[0],1)
    def test_15_consent_me(self):
        data,_=self.create();t=self.auth(data)['access_token']
        self.assertIsNone(request(type(self).app,'GET','/auth/me',token=t)[1]['consent_required_version'])
    def test_16_delete_unauthenticated(self):
        self.assertEqual(request(type(self).app,'POST','/account/delete',{'password':'x','confirmation_phrase':CONFIRM_PHRASE})[0],401)
    def test_17_delete_missing_phrase(self):
        data,_=self.create();t=self.auth(data)['access_token']
        self.assertEqual(request(type(self).app,'POST','/account/delete',{'password':data['password']},token=t)[0],400)
    def test_18_delete_wrong_phrase(self):
        data,_=self.create();t=self.auth(data)['access_token']
        self.assertEqual(request(type(self).app,'POST','/account/delete',{'password':data['password'],'confirmation_phrase':'DELETE'},token=t)[0],400)
    def test_19_delete_wrong_password(self):
        data,_=self.create();t=self.auth(data)['access_token']
        self.assertEqual(request(type(self).app,'POST','/account/delete',{'password':'incorrect','confirmation_phrase':CONFIRM_PHRASE},token=t)[0],401)
    def test_20_delete_success(self):
        data,profile=self.create();t=self.auth(data)['access_token']
        code,payload=request(type(self).app,'POST','/account/delete',{'password':data['password'],'confirmation_phrase':CONFIRM_PHRASE},token=t)
        self.assertEqual(code,200,payload);self.assertTrue(payload['cancel_on_login'])
    def test_21_delete_revokes(self):
        data,_=self.create();t=self.auth(data)['access_token']
        request(type(self).app,'POST','/account/delete',{'password':data['password'],'confirmation_phrase':CONFIRM_PHRASE},token=t)
        self.assertEqual(request(type(self).app,'GET','/auth/me',token=t)[0],401)
    def test_22_cancel_on_login(self):
        data,profile=self.create();t=self.auth(data)['access_token']
        request(type(self).app,'POST','/account/delete',{'password':data['password'],'confirmation_phrase':CONFIRM_PHRASE},token=t)
        self.auth(data)
        with db.connect(DSN) as conn:
            self.assertIsNone(conn.execute('SELECT delete_requested_at FROM accounts WHERE id=%s',(profile['id'],)).fetchone()[0])
    def test_23_finalization(self):
        data,profile=self.create()
        with db.connect(DSN) as conn:
            conn.execute("UPDATE accounts SET delete_requested_at=now()-interval '8 days' WHERE id=%s",(profile['id'],));finalize_pending(conn);conn.commit()
            row=conn.execute('SELECT username,email,deleted_at FROM accounts WHERE id=%s',(profile['id'],)).fetchone()
        self.assertEqual(row[0],'deleted_'+str(profile['id']));self.assertIsNone(row[1]);self.assertIsNotNone(row[2])
    def test_24_ledger_preserved(self):
        data,profile=self.create()
        with db.connect(DSN) as conn:
            before=conn.execute('SELECT count(*) FROM ledger_entries').fetchone()[0]
            conn.execute("UPDATE accounts SET delete_requested_at=now()-interval '8 days' WHERE id=%s",(profile['id'],));finalize_pending(conn)
            after=conn.execute('SELECT count(*) FROM ledger_entries').fetchone()[0]
            self.assertEqual(before,after);self.assertTrue(reconcile(conn)['ok']);conn.commit()
    def test_25_cannot_login_deleted(self):
        data,profile=self.create()
        with db.connect(DSN) as conn:
            conn.execute("UPDATE accounts SET delete_requested_at=now()-interval '8 days' WHERE id=%s",(profile['id'],));finalize_pending(conn);conn.commit()
        self.assertEqual(request(type(self).app,'POST','/auth/login',{'username':data['username'],'password':data['password']})[0],401)
    def test_26_password_absent_from_response(self):
        data,_=self.create();t=self.auth(data)['access_token']
        self.assertNotIn(data['password'],str(request(type(self).app,'POST','/account/delete',{'password':data['password'],'confirmation_phrase':CONFIRM_PHRASE},token=t)))
    def test_27_delete_idempotent(self):
        data,profile=self.create();t=self.auth(data)['access_token']
        request(type(self).app,'POST','/account/delete',{'password':data['password'],'confirmation_phrase':CONFIRM_PHRASE},token=t)
        with db.connect(DSN) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM audit WHERE target_account_id=%s AND action='account.delete_requested'",(profile['id'],)).fetchone()[0],1)

if __name__=='__main__': unittest.main()
