"""HQ snapshot contract, size, ownership and Enterprise settings."""
import json
import os
import tempfile
import unittest

import game_server
import holding
import hq_api
import routes_hq

NOW=1800000000

class HQTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.previous=game_server.DB
        game_server.DB=os.path.join(self.tmp.name,'world.sqlite3')
    def tearDown(self):
        game_server.DB=self.previous
        self.tmp.cleanup()

    def test_snapshot_matches_sample_contract(self):
        with game_server.connect() as db:
            status,data=routes_hq.get(db,'?','alice','/hq',{})
            self.assertEqual(status,200)
            self.assertEqual(data['version'],1)
            with open(os.path.join(os.path.dirname(__file__),'hq_sample.json'),encoding='utf8') as sample:
                expected=json.load(sample)
            for key, reference in expected.items():
                self.assertIn(key,data)
                self.assertEqual(type(data[key]),type(reference),key)
            self.assertLessEqual(len(json.dumps(data,ensure_ascii=False).encode()),65536)
            self.assertEqual(data['enterprises'],[])
            self.assertEqual(routes_hq.get(db,'?',None,'/hq',{})[0],401)

    def test_enterprise_settings_owned_and_readable(self):
        with game_server.connect() as db:
            db.execute("INSERT INTO buildings VALUES('b1','alice','farm',1,2,0)")
            status,data=routes_hq.post(db,'?','alice','/enterprise/settings',
                {'id':'b1','name':'Ферма','buy_limit':500,'price':50,'price_rule':'manual',
                 'auto_managers':{'finance':{'enabled':True}}},NOW)
            self.assertEqual(status,200,data)
            self.assertEqual(routes_hq.post(db,'?','bob','/enterprise/settings',{'id':'b1','name':'hack'},NOW)[0],403)
            status,detail=routes_hq.get(db,'?','alice','/enterprise',{'id':['b1']})
            self.assertEqual(status,200)
            self.assertEqual(detail['name'],'Ферма')
            self.assertEqual(detail['buy_limit'],500)
            self.assertEqual(detail['accounting_scope'],'company')
            self.assertEqual(routes_hq.get(db,'?','bob','/enterprise',{'id':['b1']})[0],403)

if __name__=='__main__':unittest.main()