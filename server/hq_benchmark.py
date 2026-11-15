"""Isolated SQLite 20-city/200-player HQ benchmark. No production connections."""
import json
import os
import statistics
import tempfile
import time

import game_server
import geo
import hq_api


def main():
    with tempfile.TemporaryDirectory() as folder:
        original=game_server.DB
        game_server.DB=os.path.join(folder,'bench.sqlite3')
        try:
            with game_server.connect() as db:
                centers=geo.cities()
                for i in range(200):
                    owner='bench%03d'%i
                    city=centers[i%20]
                    object_id='benchbuilding%03d'%i
                    db.execute('INSERT INTO buildings(id,owner,kind,x,y,created) VALUES(?,?,?,?,?,?)',
                               (object_id,owner,'farm',city['x']+20,city['y']+20,i))
                    db.execute('INSERT INTO building_ops VALUES(?,?,?,?,?)',(object_id,owner,'farm',0,0))
                    db.execute('INSERT INTO wallets(account,balance) VALUES(?,?)',('player:'+owner,1_000_000+i))
                    db.execute('INSERT INTO company_reports VALUES(?,?,?,?,?,?,?)',(owner,0,10000,3000,2000,5000,1))
                db.commit()
                timings=[];sizes=[]
                for i in range(200):
                    t0=time.perf_counter()
                    status,data=hq_api.snapshot(db,'?','bench%03d'%i,1800000000,cache=False)
                    timings.append((time.perf_counter()-t0)*1000)
                    sizes.append(len(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()))
                    assert status==200
                result={'cities':20,'players':200,'calls':200,'p50_ms':round(statistics.median(timings),3),
                        'p95_ms':round(sorted(timings)[189],3),'max_ms':round(max(timings),3),
                        'max_bytes':max(sizes),'avg_bytes':round(statistics.mean(sizes)),
                        'limit_bytes':hq_api.MAX_BYTES}
                print(json.dumps(result,ensure_ascii=False))
        finally:game_server.DB=original

if __name__=='__main__':main()