"""RSA-SHA256 signed client configuration: data-only, never a code patch."""
import base64
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import admin_api
import runtime_config
import live_config_api

class ConfigSignatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = sqlite3.connect(":memory:")
        admin_api.ensure(self.db, "?")
        runtime_config.ensure(self.db, "?")
        live_config_api.ensure(self.db, "?")
        self.db.execute("CREATE TABLE world_clock(id INTEGER PRIMARY KEY,epoch BIGINT,month_seconds BIGINT,base_index BIGINT)")
        self.db.execute("INSERT INTO world_clock VALUES(1,1000,60,0)")
        self.key = Path(self.tmp.name, "key.pem")
        self.public = Path(self.tmp.name, "public.pem")
        subprocess.run(["openssl","genrsa","-out",str(self.key),"2048"],check=True,capture_output=True)
        subprocess.run(["openssl","rsa","-in",str(self.key),"-pubout","-out",str(self.public)],check=True,capture_output=True)
        self.patcher = mock.patch.dict(os.environ,{live_config_api.PUBLIC_KEY_ENV:str(self.public)})
        self.patcher.start()
    def tearDown(self):
        self.patcher.stop()
        self.db.close()
        self.tmp.cleanup()
    def signature(self, raw):
        path=Path(self.tmp.name,"data")
        path.write_bytes(raw)
        return subprocess.run(["openssl","dgst","-sha256","-sign",str(self.key),str(path)],
                              check=True,capture_output=True).stdout
    def test_sign_publish_tamper_and_stage(self):
        data=live_config_api.prepare_candidate(self.db)
        raw=base64.b64decode(data["payload_b64"])
        sig=self.signature(raw)
        self.assertTrue(live_config_api.verify(str(self.public),raw,sig))
        self.assertFalse(live_config_api.verify(str(self.public),raw+b"x",sig))
        self.assertEqual(live_config_api.public(self.db,"?")[0],503)
        payload={"confirm":True,"revision":data["revision"],"signature":base64.b64encode(sig).decode()}
        self.assertEqual(live_config_api.publish(self.db,"?","admin","-",1000,payload)["signed"],True)
        status, published=live_config_api.public(self.db,"?")
        self.assertEqual(status,200)
        self.assertEqual(base64.b64decode(published["payload_b64"]),raw)
        self.assertEqual(live_config_api.publish(self.db,"?","admin","-",1000,payload)["already_signed"],True)
        runtime_config.client_update(self.db,"?",{"texts":{"hq_title":"Новый штаб"}},"admin","-",1001,confirmed=True)
        self.assertEqual(live_config_api.public(self.db,"?")[1]["revision"],0)
        with self.assertRaisesRegex(ValueError,"revision_conflict"):
            live_config_api.publish(self.db,"?","admin","-",1002,payload)
    def test_wrong_key_fails_closed(self):
        raw=live_config_api.canonical(live_config_api.candidate(self.db))
        with mock.patch.dict(os.environ,{live_config_api.PUBLIC_KEY_ENV:str(Path(self.tmp.name,"unknown"))}):
            self.assertFalse(live_config_api.verify(str(Path(self.tmp.name,"unknown")),raw,self.signature(raw)))
            with self.assertRaisesRegex(ValueError,"invalid_signature"):
                live_config_api.publish(self.db,"?","admin","-",1000,
                   {"confirm":True,"revision":0,"signature":base64.b64encode(self.signature(raw)).decode()})
    def test_no_secret_leaks(self):
        result=live_config_api.prepare_candidate(self.db)
        self.assertNotIn("private",repr(result))
        self.assertNotIn("password",repr(result))
if __name__=="__main__":unittest.main()
