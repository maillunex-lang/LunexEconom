"""Isolated EX-03/EX-04 construction_boom and land_speculation stress scenarios.

No production DB is accessed. Unlike balance_sim's existing strategies, this
module explicitly activates the optional mechanics inside a disposable SQLite
and checks money preservation at every simulated month.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import sys
import tempfile
import uuid
from unittest import mock

SERVER=os.path.join(os.path.dirname(__file__),"..","server")
if SERVER not in sys.path:sys.path.insert(0,SERVER)

import clock
import construction_projects as projects
import economy
import game_server
import goods_catalog
import land
import tenders

T0=1_800_000_000
MONTH_SECONDS=86400
SCENARIOS=("construction_boom","land_speculation")

def run_scenario(name,months=24,seed=20261115):
    if name not in SCENARIOS:raise ValueError("unknown EX-03/EX-04 scenario")
    if not 1<=months<=120:raise ValueError("months outside 1..120")
    # Numbered UUIDs make the order of projects deterministic under shortages.
    ids=itertools.count()
    def new_uuid():
        return uuid.uuid5(uuid.NAMESPACE_URL,f"ex0304:{seed}:{next(ids)}")
    results=[]
    with tempfile.TemporaryDirectory(prefix="lunex-ex0304-sim-") as tmp:
        old_db=game_server.DB
        now=[T0]
        try:
            with mock.patch.dict(os.environ,{"LAND_ENABLED":"1",
                    "CONSTRUCTION_PROJECTS_ENABLED":"1","LUNEX_MONTH_SECONDS":str(MONTH_SECONDS)}),\
                 mock.patch.object(uuid,"uuid4",side_effect=new_uuid),\
                 mock.patch.object(game_server.time,"time",side_effect=lambda: now[0]):
                game_server.DB=os.path.join(tmp,"world.sqlite3")
                with game_server.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    clock.state(db,"?",now[0])
                    for owner in ("developer","npc:developer"):
                        economy.ensure_wallet(db,"?",owner,now[0])
                        economy.post(db,"?","scenario_funds","Учебный капитал",
                                     [(economy.player_account(owner),20_000_000),
                                      (economy.TREASURY,-20_000_000)],now[0])
                    if name=="construction_boom":
                        status,body=land.buy(db,"?","developer",
                              {"px":0,"py":0,"request_id":str(new_uuid())},now[0])
                        assert status==201,(status,body)
                        for x,y in ((1,1),(1,2),(2,1)):
                            status,body=projects.create(db,"?","developer",
                                 {"object_id":"house_wood","x":x,"y":y,
                                  "request_id":str(new_uuid())},now[0])
                            assert status==201,(x,y,status,body)
                    else:
                        # The player and the NPC landholder face the same assessed
                        # prices and monthly vacant-plot tax.
                        for owner,px,py in (("developer",0,0),("npc:developer",1,0)):
                            status,body=land.buy(db,"?",owner,
                                 {"px":px,"py":py,"request_id":str(new_uuid())},now[0])
                            assert status==201,(owner,status,body)
                for month in range(months):
                    now[0]=T0+month*MONTH_SECONDS
                    with game_server.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        # A limited commodity market: the project uses the same
                        # goods_catalog and market_prices tables as the live world.
                        for good in goods_catalog.GOODS:
                            db.execute("""INSERT INTO market_prices
                              (product,month_index,price,supply,demand)
                              VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING""",
                              (good.id,month,good.reference_price,10_000,100))
                        ls=land.monthly(db,"?",month,now[0])
                        cp=projects.monthly(db,"?",month,now[0])
                        ts=tenders.monthly(db,"?",month,now[0])
                        bad=db.execute("""SELECT COUNT(*) FROM
                              (SELECT tx_id FROM ledger_entries GROUP BY tx_id
                               HAVING SUM(amount)<>0)""").fetchone()[0]
                        balances=db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
                        negative=db.execute("""SELECT COUNT(*) FROM wallets
                                 WHERE account LIKE 'player:%' AND balance<0""").fetchone()[0]
                        negative_stock=db.execute("SELECT COUNT(*) FROM inventory WHERE qty<0").fetchone()[0]
                        completed=db.execute("SELECT COUNT(*) FROM construction_projects WHERE status='complete'").fetchone()[0]
                        vacant=db.execute("SELECT COUNT(*) FROM land_parcels WHERE owner IN ('developer','npc:developer')").fetchone()[0]
                        results.append({"month":month,"wallet_sum":balances,"unbalanced_tx":bad,
                            "negative_players":negative,"negative_stock":negative_stock,
                            "commissioned":completed,"owned_parcels":vacant,
                            "rent":ls["rent"],"land_tax":ls["tax"],
                            "projects_completed":cp["completed"],
                            "tenders_awarded":ts["awarded"]})
                        assert bad==0 and balances==0 and negative==0 and negative_stock==0, results[-1]
        finally:
            game_server.DB=old_db
    digest=hashlib.sha256(json.dumps(results,sort_keys=True,
                                   separators=(",",":")).encode()).hexdigest()
    flags=[]
    if name=="construction_boom" and results[-1]["commissioned"]<3:
        flags.append("construction_not_commissioned")
    if name=="land_speculation" and results[-1]["land_tax"]<=0:
        flags.append("vacant_land_tax_missing")
    return {"scenario":name,"seed":seed,"months":months,
            "digest":digest,"invariants":[],"flags":flags,
            "last":results[-1],"rows":results}

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("scenario",choices=SCENARIOS)
    parser.add_argument("--months",type=int,default=24)
    parser.add_argument("--seed",type=int,default=20261115)
    args=parser.parse_args()
    result=run_scenario(args.scenario,args.months,args.seed)
    print(json.dumps({k:v for k,v in result.items() if k!="rows"},
                     ensure_ascii=False,indent=2))
