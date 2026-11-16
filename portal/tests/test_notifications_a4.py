"""A4: offline fake transport and deterministic clock tests."""
import json
import tempfile
import unittest
from pathlib import Path
from portal import auth, db, notify
from portal.app import create_app
from portal.tests.test_portal import call

class Fake:
    def __init__(self):
        self.calls=[]
        self.fail=False
        self.updates=[]
    def __call__(self,url,headers,payload=None,timeout=10):
        self.calls.append((url,headers,payload,timeout))
        if self.fail:
            raise ValueError("offline")
        if "/getUpdates" in url:
            return {"ok":True,"result":self.updates}
        if "/updates?" in url:
            return {"updates":self.updates}
        if "/sendMessage" in url:
            return {"ok":True}
        return {"message":{"body":{"text":"ok"}}}

class A4(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.path=str(self.root/"portal.sqlite")
        c=db.connect(self.path);auth.set_password(c,"owner","password-for-testing");c.close()
        self.files={}
        for ch in notify.CHANNELS:
            p=self.root/(ch+".token");p.write_text("dummy-"+ch);p.chmod(0o600);self.files[ch]=str(p)
        self.fake=Fake()
        self.now=[1000000.]
        self.app=create_app(self.path,base="/createportal",notifications_enabled=True,notify_token_files=self.files,notify_client=self.fake,notify_clock=lambda:self.now[0])
        r=call(self.app,"POST","/api/login",{"username":"owner","password":"password-for-testing"})
        self.cookie=r["headers"]["Set-Cookie"].split(";")[0];self.csrf=r["json"]["csrf"]
        self.conn=db.connect(self.path,notifications=True)
    def tearDown(self):
        self.conn.close();self.app.close();self.tmp.cleanup()
    def req(self,method,path,body=None,cookie=None,csrf=None):
        return call(self.app,method,"/api/notifications/"+path,body,cookie=self.cookie if cookie is None else cookie,csrf=self.csrf if csrf is None else csrf)
    def link(self,ch="max"):
        code=notify.create_code(self.conn,ch,self.now[0])
        self.assertTrue(notify.bind(self.conn,ch,code,"123456",self.now[0]))
    def test_01_default_disabled(self):
        self.assertFalse(self.req("GET","settings")["json"]["channels"]["max"]["enabled"])
    def test_02_default_unlinked(self):
        self.assertFalse(self.req("GET","settings")["json"]["channels"]["telegram"]["linked"])
    def test_03_code(self):
        self.assertEqual(len(self.req("POST","code",{"channel":"max"})["json"]["code"]),8)
    def test_04_code_not_plain_db(self):
        code=self.req("POST","code",{"channel":"max"})["json"]["code"]
        self.assertNotIn(code,str(self.conn.execute("SELECT * FROM notify_channels").fetchall()))
    def test_05_code_expires(self):
        code=notify.create_code(self.conn,"max",self.now[0])
        self.assertFalse(notify.bind(self.conn,"max",code,"123",self.now[0]+600))
    def test_06_code_before_expiry(self):
        code=notify.create_code(self.conn,"max",self.now[0])
        self.assertTrue(notify.bind(self.conn,"max",code,"123",self.now[0]+599))
    def test_07_wrong_code(self):
        notify.create_code(self.conn,"max",self.now[0])
        self.assertFalse(notify.bind(self.conn,"max","00000000","123",self.now[0]))
    def test_08_code_single_use(self):
        code=notify.create_code(self.conn,"max",self.now[0])
        self.assertTrue(notify.bind(self.conn,"max",code,"123",self.now[0]))
        self.assertFalse(notify.bind(self.conn,"max",code,"999",self.now[0]))
    def test_09_code_rotates(self):
        old=notify.create_code(self.conn,"max",self.now[0])
        new=notify.create_code(self.conn,"max",self.now[0])
        if old != new:self.assertFalse(notify.bind(self.conn,"max",old,"123",self.now[0]))
    def test_10_invalid_chat(self):
        code=notify.create_code(self.conn,"max",self.now[0])
        self.assertFalse(notify.bind(self.conn,"max",code,"evil",self.now[0]))
    def test_11_enable_requires_link(self):
        self.assertEqual(self.req("POST","settings",{"channel":"max","enabled":True,"events":{}})["status"],409)
    def test_12_enable_linked(self):
        self.link();self.assertEqual(self.req("POST","settings",{"channel":"max","enabled":True,"events":{}})["status"],200)
    def test_13_disable_independent(self):
        self.link("max");self.link("telegram")
        self.req("POST","settings",{"channel":"max","enabled":False,"events":{}})
        self.assertTrue(self.req("GET","settings")["json"]["channels"]["telegram"]["enabled"])
    def test_14_preference(self):
        self.link();self.req("POST","settings",{"channel":"max","enabled":True,"events":{"ci.failed":False}})
        self.assertFalse(self.req("GET","settings")["json"]["channels"]["max"]["events"]["ci.failed"])
    def test_15_bad_preference(self):
        self.assertEqual(self.req("POST","settings",{"channel":"max","enabled":False,"events":{"bad":True}})["status"],400)
    def test_16_bad_channel(self):
        self.assertEqual(self.req("POST","code",{"channel":"smtp"})["status"],400)
    def test_17_no_session(self):
        self.assertEqual(self.req("GET","settings",cookie="")["status"],401)
    def test_18_csrf(self):
        self.assertEqual(self.req("POST","code",{"channel":"max"},csrf="wrong")["status"],403)
    def test_19_unlink(self):
        self.link();self.req("POST","unlink",{"channel":"max"})
        self.assertFalse(self.req("GET","settings")["json"]["channels"]["max"]["linked"])
    def test_20_max_transport(self):
        notify.send("max","secret","123","hello",self.fake)
        self.assertIn("chat_id=123",self.fake.calls[-1][0])
        self.assertEqual(self.fake.calls[-1][1]["Authorization"],"secret")
    def test_21_max_no_token_in_url(self):
        notify.send("max","secret","123","hello",self.fake)
        self.assertNotIn("secret",self.fake.calls[-1][0])
    def test_22_telegram_transport(self):
        notify.send("telegram","secret","123","hello",self.fake)
        self.assertEqual(self.fake.calls[-1][2]["chat_id"],"123")
    def test_23_token_file(self):
        self.assertEqual(notify.token_from_file("max",self.files),"dummy-max")
    def test_24_token_permission(self):
        Path(self.files["max"]).chmod(0o644)
        with self.assertRaises(ValueError):notify.token_from_file("max",self.files)
    def test_25_token_not_in_settings(self):
        self.link();self.assertNotIn("dummy-max",str(self.req("GET","settings")["json"]))
    def test_26_queue_disabled(self):
        self.assertEqual(notify.enqueue(self.conn,"ci.failed","a","message",self.now[0]),0)
    def test_27_queue_linked(self):
        self.link();self.assertEqual(notify.enqueue(self.conn,"ci.failed","a","message",self.now[0]),1)
    def test_28_quiet_hour(self):
        self.link();notify.enqueue(self.conn,"ci.failed","a","message",self.now[0])
        self.assertEqual(notify.enqueue(self.conn,"ci.failed","a","message",self.now[0]+3599),0)
    def test_29_quiet_expired(self):
        self.link();notify.enqueue(self.conn,"ci.failed","a","message",self.now[0])
        self.assertEqual(notify.enqueue(self.conn,"ci.failed","a","message",self.now[0]+3600),1)
    def test_30_separate_events(self):
        self.link();notify.enqueue(self.conn,"ci.failed","a","message",self.now[0])
        self.assertEqual(notify.enqueue(self.conn,"task.submitted","a","message",self.now[0]),1)
    def test_31_separate_keys(self):
        self.link();notify.enqueue(self.conn,"ci.failed","a","message",self.now[0])
        self.assertEqual(notify.enqueue(self.conn,"ci.failed","b","message",self.now[0]),1)
    def test_32_delivery(self):
        self.link();notify.enqueue(self.conn,"ci.failed","a","message",self.now[0])
        self.assertEqual(notify.deliver_due(self.conn,self.files,self.fake,self.now[0]),1)
        self.assertEqual(self.conn.execute("SELECT status FROM notify_jobs").fetchone()[0],"delivered")
    def test_33_retry_delay(self):
        self.link();notify.enqueue(self.conn,"ci.failed","a","message",self.now[0]);self.fake.fail=True
        notify.deliver_due(self.conn,self.files,self.fake,self.now[0])
        self.assertEqual(notify.deliver_due(self.conn,self.files,self.fake,self.now[0]+299),0)
    def test_34_retry_three(self):
        self.link();notify.enqueue(self.conn,"ci.failed","a","message",self.now[0]);self.fake.fail=True
        for i in range(4):notify.deliver_due(self.conn,self.files,self.fake,self.now[0]+300*i)
        row=self.conn.execute("SELECT attempts,status FROM notify_jobs").fetchone()
        self.assertEqual(tuple(row),(4,"failed"))
    def test_35_no_token_in_log(self):
        self.link();notify.enqueue(self.conn,"ci.failed","a","message",self.now[0]);notify.deliver_due(self.conn,self.files,self.fake,self.now[0])
        self.assertNotIn("dummy-max",str([tuple(r) for r in self.conn.execute("SELECT * FROM notify_log")]))
    def test_36_poll_telegram(self):
        code=notify.create_code(self.conn,"telegram",self.now[0])
        self.fake.updates=[{"update_id":1,"message":{"chat":{"id":42},"text":code}}]
        self.assertTrue(self.req("POST","poll",{"channel":"telegram"})["json"]["linked"])
    def test_37_poll_max(self):
        code=notify.create_code(self.conn,"max",self.now[0])
        self.fake.updates=[{"update_id":"a","message":{"recipient":{"chat_id":42},"body":{"text":code}}}]
        self.assertTrue(self.req("POST","poll",{"channel":"max"})["json"]["linked"])
    def test_38_poll_replay(self):
        code=notify.create_code(self.conn,"telegram",self.now[0])
        self.fake.updates=[{"update_id":1,"message":{"chat":{"id":42},"text":code}}]
        self.req("POST","poll",{"channel":"telegram"})
        self.assertFalse(self.req("POST","poll",{"channel":"telegram"})["json"]["linked"])
    def test_39_test_not_linked(self):
        self.assertEqual(self.req("POST","test",{"channel":"max"})["status"],409)
    def test_40_test_linked(self):
        self.link();self.assertEqual(self.req("POST","test",{"channel":"max"})["status"],200)
    def test_41_test_failure(self):
        self.link();self.fake.fail=True
        self.assertEqual(self.req("POST","test",{"channel":"max"})["status"],502)
    def test_42_process_empty(self):
        self.assertEqual(self.req("POST","process",{})["status"],200)
    def test_43_process_csrf(self):
        self.assertEqual(self.req("POST","process",{},csrf="bad")["status"],403)
    def test_44_disabled_preference_no_queue(self):
        self.link();self.req("POST","settings",{"channel":"max","enabled":True,"events":{"ci.failed":False}})
        self.assertEqual(notify.enqueue(self.conn,"ci.failed","a","message",self.now[0]),0)
    def test_45_invalid_message(self):
        with self.assertRaises(ValueError):notify.send("max","secret","123","",self.fake)
    def test_46_invalid_key(self):
        self.link();self.assertEqual(notify.enqueue(self.conn,"ci.failed","", "message",self.now[0]),0)
    def test_47_log_route(self):
        self.assertEqual(self.req("GET","log")["status"],200)
    def test_48_not_found(self):
        self.assertEqual(self.req("GET","nope")["status"],404)
    def test_49_max_invalid_response(self):
        with self.assertRaises(ValueError):notify.send("max","secret","123","hello",lambda *a,**kw:None)
    def test_50_telegram_api_failure(self):
        with self.assertRaises(ValueError):notify.send("telegram","secret","123","hello",lambda *a,**kw:{"ok":False})
if __name__=="__main__":unittest.main()
