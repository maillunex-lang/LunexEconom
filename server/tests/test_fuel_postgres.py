"""V2-FUEL1 PostgreSQL regression coverage (separate rolled-back fixtures)."""
from unittest.mock import patch
from server.ledger.api import reconcile
from server.supply import core, api
from server.game_server import build_registry
from server.tests.test_supply_postgres import SupplyPostgresTests, FLAGS


class FuelPostgresTests(SupplyPostgresTests):
    # Reuse the proven rolled-back PostgreSQL fixtures.
    def setUp(self):
        super().setUp()
        self.flags = {**FLAGS, 'logistics_fuel_required': True,
                      'logistics_fuel_autobuy': True}

    def _trade(self, money=1000000, source_city='ufa', dest_city='sterlitamak',
               source_stock=100, buyer_fuel=0, autobuy=True):
        owner = self.owner(money)
        seller = self.enterprise(owner, 'field', city=source_city,
                                 stock=[('grain', source_stock, 50)])
        buyer = self.enterprise(owner, 'mill', city=dest_city,
                                stock=[('fuel', buyer_fuel, 50)] if buyer_fuel else [])
        self.link(buyer, 'grain', seller)
        flags = {**self.flags, 'logistics_fuel_autobuy': autobuy}
        row = next(r for r in core._enterprises(self.conn) if r[0] == buyer)
        return owner, seller, buyer, row, flags

    def test_quote_integer_examples_and_flags(self):
        with patch.object(core.world, 'routes', return_value={'distance_meters': 85000}):
            self.assertEqual(core.fuel_quote('ufa','sterlitamak',100,self.flags), (85, 5950))
            self.assertEqual(core.fuel_quote('ufa','sterlitamak',1,self.flags), (1, 70))
            self.assertEqual(core.fuel_quote('ufa','ufa',100,self.flags), (0, 0))
            self.assertEqual(core.fuel_quote('ufa','sterlitamak',0,self.flags), (0, 0))
            self.assertEqual(core.fuel_quote('ufa','sterlitamak',100,{**self.flags,
                'logistics_fuel_required':False}), (0, 0))
            self.assertEqual(core.fuel_quote('ufa','sterlitamak',100,{**self.flags,
                'logistics_fuel_autobuy':False}), (85, 0))
        reg = build_registry()
        self.assertIs(reg.flags['logistics_fuel_required'], False)
        self.assertIs(reg.flags['logistics_fuel_autobuy'], True)

    def test_autobuy_ledger_idempotency_and_reconcile(self):
        owner, seller, buyer, row, flags = self._trade()
        liters, cost = core.fuel_quote('ufa','sterlitamak',100,flags)
        first = self.balance(owner)
        core.links_day(self.conn, self.day, flags)
        transfers = self.conn.execute("""SELECT request_id FROM ledger_transfers
            WHERE request_id LIKE %s ORDER BY request_id""",
            (f'supply:{buyer}:grain:{self.day}:%',)).fetchall()
        self.assertEqual(len([t for t in transfers if t[0].endswith(':fuel')]),1)
        self.assertEqual(self.qty(seller,'grain'), 0)
        self.assertEqual(self.balance(owner), first - cost - core._travel(
            'ufa','sterlitamak',100,1)[1])
        self.assertEqual(self.qty(buyer, 'fuel'), 0)
        core.links_day(self.conn, self.day, flags)
        self.assertEqual(self.conn.execute("""SELECT count(*) FROM ledger_transfers
            WHERE request_id LIKE %s""",(f'supply:{buyer}:grain:{self.day}:%',)).fetchone()[0],len(transfers))
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_fuel_unaffordable_is_atomic_and_reported(self):
        owner, seller, buyer, row, flags = self._trade(money=100000)
        freight = core._travel('ufa','sterlitamak',100,1)[1]
        fuel_cost = core.fuel_quote('ufa','sterlitamak',100,flags)[1]
        # Set the wallet to cover freight but not freight + fuel.
        desired = freight + fuel_cost - 1
        from server.ledger.api import transfer
        transfer(self.conn,'fuel:fixture:reduce:'+str(buyer), owner['wallet'],
                 self.treasury, 100000-desired)
        money = self.balance(owner)
        self.assertEqual(core._buy(self.conn,self.day,row,'grain',100,'enterprise',
                                   seller,0,0,flags,1),0)
        self.assertEqual(self.balance(owner),money)
        self.assertEqual(self.qty(seller,'grain'),100)
        self.assertEqual(self.conn.execute("""SELECT count(*) FROM shipments
            WHERE buyer_enterprise_id=%s""",(buyer,)).fetchone()[0],0)
        self.assertEqual(self.conn.execute("""SELECT reason FROM supply_fuel_failures
            WHERE enterprise_id=%s AND day_index=%s""",(buyer,self.day)).fetchone()[0],
                         'fuel_unaffordable')
        with patch('server.supply.api.authenticate', return_value=owner):
            context={'conn':self.conn,'path_params':{'id':str(buyer)},
                     'settings':flags}
            code,response=api.get({},context)
            self.assertEqual(code,200)
            self.assertEqual(response['fuel_failures'][0]['reason'],'fuel_unaffordable')
            self.assertEqual(response['links'][0]['fuel_cost'],fuel_cost)
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_manual_fuel_missing_and_inventory_consumption(self):
        owner, seller, buyer, row, flags = self._trade(buyer_fuel=0,autobuy=False)
        self.assertEqual(core._buy(self.conn,self.day,row,'grain',100,'enterprise',
                                   seller,0,0,flags,1),0)
        self.assertEqual(self.qty(seller,'grain'),100)
        self.assertEqual(self.conn.execute("""SELECT reason FROM supply_fuel_failures
            WHERE enterprise_id=%s AND day_index=%s""",(buyer,self.day)).fetchone()[0],
                         'fuel_missing')
        liters,_=core.fuel_quote('ufa','sterlitamak',100,flags)
        from server.enterprises import core as enterprise
        enterprise.adjust(self.conn,buyer,'fuel',liters,50)
        self.assertEqual(core._buy(self.conn,self.day,row,'grain',100,'enterprise',
                                   seller,0,0,flags,1),100)
        self.assertEqual(self.qty(buyer,'fuel'),0)
        self.assertFalse(any(r[0].endswith(':fuel') for r in self.conn.execute("""
            SELECT request_id FROM ledger_transfers WHERE request_id LIKE %s""",
            (f'supply:{buyer}:grain:{self.day}:%',)).fetchall()))
        self.assertTrue(reconcile(self.conn)['ok'])

    def test_disabled_and_intracity_no_fuel_journals(self):
        for source,dest,flag in [('ufa','sterlitamak',False),('ufa','ufa',True)]:
            owner,seller,buyer,row,flags=self._trade(source_city=source,dest_city=dest)
            flags['logistics_fuel_required']=flag
            before=self.balance(owner)
            self.assertEqual(core._buy(self.conn,self.day,row,'grain',100,
                'enterprise',seller,0,0,flags,buyer),100)
            self.assertEqual(self.balance(owner),before-core._travel(source,dest,100,1)[1])
            self.assertFalse(any(r[0].endswith(':fuel') for r in self.conn.execute("""
                SELECT request_id FROM ledger_transfers WHERE request_id LIKE %s""",
                (f'supply:{buyer}:grain:{self.day}:%',)).fetchall()))
        self.assertTrue(reconcile(self.conn)['ok'])
