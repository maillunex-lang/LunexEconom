"""Developer-only free assets, closure and undo on an isolated SQLite world."""
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

import game_server
import devtools
import geo
import city_catalog
import zoning
import roads

NOW=1800000000

class EditorEx14Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=game_server.DB
        game_server.DB=os.path.join(self.tmp.name,'world.sqlite3')
        self.role=patch('devtools.require_developer',return_value=True)
        self.role.start()
        with game_server.connect() as db:devtools.ensure(db,'?')
    def tearDown(self):
        self.role.stop()
        game_server.DB=self.old
        self.tmp.cleanup()
    def lot(self,kind='farm',width=2,height=2):
        from terrain_rules import preload,is_water
        with game_server.connect() as db:
            for city in geo.cities():
                cx,cy=city['x'],city['y']
                for dx in range(-35,36):
                    for dy in range(-35,36):
                        x,y=cx+dx,cy+dy
                        cells=[(x+i,y+j) for i in range(width) for j in range(height)]
                        if any(roads.is_base_road(a,b) or roads.is_water(a,b) for a,b in cells):continue
                        if zoning.check(db,'?',kind,cells):continue
                        if any(db.execute('SELECT 1 FROM cells WHERE x=? AND y=?',(a,b)).fetchone() for a,b in cells):continue
                        if any(db.execute('SELECT 1 FROM roads WHERE x=? AND y=?',(a,b)).fetchone() for a,b in cells):continue
                        from terrain_rules import preload
                        box=roads.search_box(cells)
                        edits=preload(db,'?',box)
                        err,path=roads.plan_access(cells,set(),set(),1000,edits)
                        if err:continue
                        return x,y
        self.fail('no free suitable lot')
    def test_player_enterprise_create_undo_balances_unchanged(self):
        x,y=self.lot()
        with game_server.connect() as db:
            before=db.execute('SELECT COALESCE(SUM(amount),0) FROM ledger_entries').fetchone()[0]
            p={'request_id':str(uuid.uuid4()),'kind':'farm','owner':'alice','x':x,'y':y,'developer_override':True}
            status,result=devtools.building_create(db,'?','dev',p,'local')
            self.assertEqual(status,200,result)
            self.assertEqual(db.execute('SELECT owner FROM building_ops WHERE object_id=?',(result['object_id'],)).fetchone(),('alice',))
            self.assertEqual(devtools.building_create(db,'?','dev',p,'local')[1].get('replayed'),True)
            self.assertEqual(db.execute('SELECT COALESCE(SUM(amount),0) FROM ledger_entries').fetchone()[0],before)
            status,undone=devtools.undo(db,'?','dev',{'request_id':str(uuid.uuid4())},'local')
            self.assertEqual(status,200,undone)
            self.assertIsNone(db.execute('SELECT id FROM buildings WHERE id=?',(result['object_id'],)).fetchone())

    def test_housing_owner_and_safe_demolition(self):
        x,y=self.lot('house',1,1)
        with game_server.connect() as db:
            p={'request_id':str(uuid.uuid4()),'kind':'house_wood','owner':'alice','x':x,'y':y,'developer_override':True}
            status,result=devtools.building_create(db,'?','dev',p,'local')
            self.assertEqual(status,200,result)
            oid=result['object_id']
            self.assertIsNone(db.execute('SELECT 1 FROM building_ops WHERE object_id=?',(oid,)).fetchone())
            d={'request_id':str(uuid.uuid4()),'object_id':oid,'developer_override':True}
            status,done=devtools.building_demolish(db,'?','dev',d,'local')
            self.assertEqual(status,200,done)
            status,undone=devtools.undo(db,'?','dev',{'request_id':str(uuid.uuid4())},'local')
            self.assertEqual(status,200,undone)
            self.assertEqual(db.execute('SELECT owner FROM buildings WHERE id=?',(oid,)).fetchone(),('alice',))

if __name__=='__main__':unittest.main()