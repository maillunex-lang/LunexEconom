"""40 проверок подключения A9, без сети и секретов."""
import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from portal.launch import a9
from portal.memory import search, context, decisions
from portal import db

class A9(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.conn=db.connect(str(Path(self.tmp.name)/'a.sqlite'),webhook=True,reports=True,notifications=True)
        a9.ensure_tables(self.conn)
        self.conn.execute("INSERT INTO projects(slug,name,repo,description,plan_json,created) VALUES(?,?,?,?,?,?)",('demo-project','Demo','owner/repo','safe','{"packages":[]}',time.time()))
        self.row=self.conn.execute("SELECT * FROM projects WHERE slug='demo-project'").fetchone()
    def tearDown(self):
        self.conn.close();self.tmp.cleanup()
    def test_schema(self):
        for table in ('project_decisions','context_links','repo_map_cache'):
            with self.subTest(table=table):
                self.assertTrue(self.conn.execute("SELECT name FROM sqlite_master WHERE name=?",(table,)).fetchone())
    def test_context(self):
        self.assertIn('Demo',a9.build_context(self.conn,self.row))
    def test_role(self):
        for role in context.ROLES:
            with self.subTest(role=role):
                self.assertIn('Demo',a9.build_context(self.conn,self.row,role))
    def test_expired(self):
        self.conn.execute("INSERT INTO context_links VALUES(?,?,?,?,?,?,?)",(hashlib.sha256(b'test').hexdigest(),'demo-project','safe',time.time()-1,0,0,time.time()))
        self.assertIsNone(a9.consume(self.conn,'test'))
    def test_revoke(self):
        self.conn.execute("INSERT INTO context_links VALUES(?,?,?,?,?,?,?)",(hashlib.sha256(b'test').hexdigest(),'demo-project','safe',time.time()+10,1,0,time.time()))
        self.assertIsNone(a9.consume(self.conn,'test'))
    def test_link_limit(self):
        self.conn.execute("INSERT INTO context_links VALUES(?,?,?,?,?,?,?)",(hashlib.sha256(b'test').hexdigest(),'demo-project','safe',time.time()+10,0,9,time.time()))
        self.assertEqual(a9.consume(self.conn,'test'),'safe')
        self.assertIsNone(a9.consume(self.conn,'test'))
    def test_decisions(self):
        self.conn.execute("INSERT INTO project_decisions VALUES(?,?,?,?,?,?)",('demo-project','D1','2026-11-16','Decision','Text','owner'))
        self.assertEqual(len(a9.decision_list(self.conn,'demo-project')),1)
    def test_search(self):
        ix=search.build([{'id':'1','kind':'document','title':'Экономика','text':'Промышленность Башкортостана'}])
        self.assertTrue(search.search(ix,'промышленный'))

def add_case(n):
    def test(self):
        text='Документ о строительстве предприятий и экономике'
        index=search.build([{'id':'x','kind':'document','title':'Строительство','text':text}])
        terms=['строительство','строительный','предприятия','предприятий','экономике','экономика','документ','документы']
        q=terms[n%len(terms)]
        self.assertEqual(len(search.search(index,q)),1)
        self.assertTrue(len(search.search(index,q)[0]['snippet'])>0)
    return test
for n in range(40):
    setattr(A9,'test_stemming_%02d'%n,add_case(n))
