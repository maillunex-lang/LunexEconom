"""HQ/holding PostgreSQL 16 acceptance, only disposable lunex_ci."""
import os
import unittest
import uuid

CI=os.environ.get('LUNEX_DB_ENGINE')=='postgres' and os.environ.get('LUNEX_PG_DB')=='lunex_ci'

@unittest.skipUnless(CI,'requires isolated lunex_ci PostgreSQL database')
class PostgreSQLHQTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import postgres_db
        postgres_db.init()

    def test_contract_holding_journal_and_read_only_snapshot(self):
        import postgres_db,holding,hq_api
        with postgres_db.connect() as db:
            db.execute('SAVEPOINT hq_ci_test')
            try:
                owner='ci_hq_'+uuid.uuid4().hex[:12]
                db.execute('INSERT INTO wallets(account,balance) VALUES(%s,%s)',('player:'+owner,500))
                db.execute('INSERT INTO wallets(account,balance) VALUES(%s,%s)',('system:ci_balancer_'+uuid.uuid4().hex,-500))
                holding.create(db,'%s',owner,'CI Holding')
                sub=holding.add_subsidiary(db,'%s',owner,'CI Subsidiary',sub_id=uuid.uuid4().hex)
                before=holding.consolidated(db,'%s',owner)
                status,result=holding.transfer(db,'%s',owner,'player:'+owner,holding.subsidiary_account(sub),150,str(uuid.uuid4()),1800000000)
                self.assertEqual(status,201,result)
                after=holding.consolidated(db,'%s',owner)
                self.assertEqual(before['cash'],after['cash'])
                self.assertEqual(before['profit_month'],after['profit_month'])
                txid=result['tx_id']
                self.assertEqual(db.execute('SELECT SUM(amount) FROM ledger_entries WHERE tx_id=%s',(txid,)).fetchone()[0],0)
                code,body=hq_api.snapshot(db,'%s',owner,1800000000)
                self.assertEqual(code,200)
                self.assertEqual(body['money']['cash'],500)
                self.assertEqual(body['version'],1)
            finally:
                db.execute('ROLLBACK TO SAVEPOINT hq_ci_test')
                db.execute('RELEASE SAVEPOINT hq_ci_test')

if __name__=='__main__':unittest.main()