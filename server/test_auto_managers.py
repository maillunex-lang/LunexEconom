import sqlite3
import unittest

import holding
import auto_managers

class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        holding.ensure(self.db,'?')

    def tearDown(self):self.db.close()

    def test_idempotent_and_no_unapproved_cash_or_stock(self):
        self.db.execute("INSERT INTO enterprise_settings(object_id,owner,managers) VALUES('b','alice','{\"finance\":{\"enabled\":true}}')")
        self.assertEqual(auto_managers.monthly(self.db,'?',7,123),1)
        self.assertEqual(auto_managers.monthly(self.db,'?',7,124),0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM auto_months').fetchone()[0],1)

    def test_finance_monthly_posts_once_and_preserves_consolidated_profit(self):
        import economy
        for ddl in economy.SCHEMA:
            self.db.execute(ddl)
        holding.create(self.db,'?','npc:operator','Company',0)
        sub=holding.add_subsidiary(self.db,'?','npc:operator','Production',sub_id='sub1')
        self.db.execute("INSERT INTO wallets(account,balance) VALUES('player:npc:operator',500)")
        config='{"finance":{"enabled":true,"target_sub_id":"sub1","max_transfer":150,"cash_reserve":200}}'
        self.db.execute('INSERT INTO enterprise_settings(object_id,owner,managers) VALUES(?,?,?)',('b1','npc:operator',config))
        self.assertEqual(auto_managers.monthly(self.db,'?',7,123),1)
        self.assertEqual(auto_managers.monthly(self.db,'?',7,124),0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM holding_transfers').fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT balance FROM wallets WHERE account='player:npc:operator'").fetchone()[0],350)
        self.assertEqual(self.db.execute("SELECT balance FROM wallets WHERE account='holding:sub:sub1'").fetchone()[0],150)
        self.assertEqual(holding.consolidated(self.db,'?','npc:operator')['cash'],500)
        self.assertEqual(self.db.execute('SELECT SUM(amount) FROM ledger_entries').fetchone()[0],0)

    def test_reject_invalid_config(self):
        with self.assertRaises(ValueError):auto_managers.validate({'finance':{'enabled':'yes'}})

if __name__=='__main__':unittest.main()