"""Double entry and consolidation against an isolated in-memory world."""
import sqlite3
import unittest
import uuid

import economy
import holding

class HoldingTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        for schema in economy.SCHEMA:
            self.db.execute(schema)
        holding.ensure(self.db,'?')
        holding.create(self.db,'?','alice','Агрохолдинг',0)
        self.db.execute("INSERT INTO wallets VALUES('player:alice',1000)")
        self.sub=holding.add_subsidiary(self.db,'?','alice','Фермерское предприятие',sub_id='sub1')

    def tearDown(self):self.db.close()

    def test_internal_transfer_eliminated_and_balanced(self):
        before=holding.consolidated(self.db,'?','alice')
        request=str(uuid.uuid4())
        status,data=holding.transfer(self.db,'?','alice','player:alice',holding.subsidiary_account(self.sub),400,request,1)
        self.assertEqual(status,201,data)
        self.assertEqual(holding.transfer(self.db,'?','alice','player:alice',holding.subsidiary_account(self.sub),400,request,2)[0],200)
        after=holding.consolidated(self.db,'?','alice')
        self.assertEqual(after['cash'],before['cash'])
        self.assertEqual(after['profit_month'],before['profit_month'])
        self.assertEqual(self.db.execute('SELECT SUM(amount) FROM ledger_entries').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM holding_transfers').fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT balance FROM wallets WHERE account='player:alice'").fetchone()[0],600)
        self.assertEqual(self.db.execute("SELECT balance FROM wallets WHERE account='holding:sub:sub1'").fetchone()[0],400)

    def test_no_cross_holding_transfer_or_overdraft(self):
        self.assertEqual(holding.transfer(self.db,'?','alice','player:alice','player:bob',1,str(uuid.uuid4()),1)[0],403)
        self.assertEqual(holding.transfer(self.db,'?','alice','player:alice','holding:sub:sub1',2000,str(uuid.uuid4()),1)[0],402)
        self.assertEqual(self.db.execute('SELECT count(*) FROM ledger_tx').fetchone()[0],0)

    def test_external_profit_is_not_multiplied_by_subsidiaries(self):
        self.db.execute("INSERT INTO company_reports VALUES('alice',3,250,100,40,110,1)")
        self.assertEqual(holding.consolidated(self.db,'?','alice')['profit_month'],110)
        holding.add_subsidiary(self.db,'?','alice','Торговое предприятие',sub_id='sub2')
        self.assertEqual(holding.consolidated(self.db,'?','alice')['profit_month'],110)

if __name__=='__main__':unittest.main()