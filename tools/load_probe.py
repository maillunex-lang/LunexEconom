"""Bounded synthetic 200-player probe on a disposable SQLite world only.

Never starts a public service, touches production PostgreSQL, or runs citygen --wipe.
Actions use the same core handlers as the game server. Authentication, mobile
rendering, network latency, and real-world concurrency are NOT measured.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import random
import statistics
import sys
import tempfile
import time
import uuid
from unittest import mock

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

import citygen
import economy
import game_server
import geo
import production
import regions
import social

NOW = 1_800_000_000


def timed(fn, samples):
    start = time.perf_counter()
    value = fn()
    samples.append((time.perf_counter() - start) * 1000)
    return value


def stats(samples):
    if not samples:
        return {"count": 0}
    sorted_samples = sorted(samples)
    return {"count": len(samples), "p50_ms": round(statistics.median(samples), 2),
            "p95_ms": round(sorted_samples[min(len(sorted_samples)-1, int(.95*len(sorted_samples)))], 2),
            "max_ms": round(max(samples), 2)}


def run(players=200, seed=20261115):
    if players != 200:
        raise ValueError("This reproducible probe requires exactly 200 virtual players")
    rng = random.Random(seed)
    results = {"players": players, "seed": seed, "environment": "tempfile SQLite, local direct calls",
               "operation_timings": {}, "successful_builds": 0, "rejected_builds": {},
               "success_sell_orders": 0, "success_buy_orders": 0, "matched_trades": 0,
               "citygen": {}, "month_step_ms": [], "errors": []}
    samples = {k: [] for k in ("wallet", "build", "order", "chunk", "economy_regions", "monthly_step")}
    with tempfile.TemporaryDirectory(prefix="lunex-gpt5-load-") as tmp:
        filename = os.path.join(tmp, "probe.sqlite3")
        with mock.patch.object(game_server, "DB", filename), mock.patch.object(game_server.time, "time", return_value=NOW):
            with game_server.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                start = time.perf_counter()
                planted = []
                for city in geo.cities():
                    summary = citygen.seed_city(db, "?", city["id"], NOW)
                    planted.append(summary)
                db.commit()
                results["citygen"] = {"cities": len(planted),
                                      "houses": sum(v["placed"] for v in planted),
                                      "road_cells": sum(v["road_cells"] for v in planted),
                                      "elapsed_ms": round((time.perf_counter()-start)*1000, 2)}
            print("PROBE citygen seeded in disposable DB:", results["citygen"], flush=True)
            owners = [f"probe_{i:03d}" for i in range(players)]
            # For reporting a real build acceptance ratio, every player submits
            # at least one authoritative build command. Rejections are not retried
            # until accepted, as retries would distort the latency distribution.
            cities = geo.cities()
            for i, owner in enumerate(owners):
                timed(lambda o=owner: game_server.wallet(o), samples["wallet"])
                c = cities[i % len(cities)]
                x = int(c["x"] + (i//20%10)*5 - 19)
                y = int(c["y"] - 15 + (i//20%10)*4)
                kind = ["farm", "mine", "warehouse", "shop"][i%4]
                status, data = timed(
                    lambda o=owner,k=kind,xx=x,yy=y: game_server.build(o, {
                        "kind": k, "x": xx, "y": yy, "request_id": str(uuid.uuid4())}),
                    samples["build"])
                if status in (200, 201):
                    results["successful_builds"] += 1
                else:
                    key = data.get("error", "http_" + str(status))
                    results["rejected_builds"][key] = results["rejected_builds"].get(key, 0)+1
                if i % 40 == 39:
                    print("PROBE building", i+1, "/", players, flush=True)
            # Test-only stock allocation. This is a load fixture, not an economic
            # transaction and is omitted from invariant checks until after matching.
            with game_server.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                for owner in owners[:100]:
                    exchange_stmt = "INSERT INTO inventory(owner,product,qty) VALUES(?,?,?) ON CONFLICT(owner,product) DO UPDATE SET qty=excluded.qty"
                    db.execute(exchange_stmt, (owner, "honey", 20))
                db.commit()
            # Give each synthetic participant a unique simulated source IP.
            # This preserves the game's 120 actions/IP/min guardrail while
            # measuring 200 distinct clients rather than one abusive proxy.
            social.reset_limits()
            for i, owner in enumerate(owners):
                seller = i < 100
                payload = {"side": "sell" if seller else "buy", "product": "honey",
                           "qty": 2, "price": 150, "request_id": str(uuid.uuid4())}
                status, data = timed(lambda o=owner,p=payload: game_server.soc_post(
                    o, "/soc/exchange/order", p,
                    "198.51.100." + str((i % 200) + 1)), samples["order"])
                if status == 201:
                    if seller:
                        results["success_sell_orders"] += 1
                    else:
                        results["success_buy_orders"] += 1
                        results["matched_trades"] += len(data.get("fills", []))
                else:
                    key = "order_" + data.get("error", str(status))
                    results["rejected_builds"][key] = results["rejected_builds"].get(key,0)+1
            for i in range(players):
                c = cities[i % len(cities)]
                cx,cy = int(c["x"])//12,int(c["y"])//12
                timed(lambda x=cx,y=cy: game_server.chunk(x,y), samples["chunk"])
                def overview():
                    with game_server.connect() as db:
                        view = regions.overview(db, "?")
                        if len(view["cities"]) != 20:
                            raise AssertionError("Expected 20 active cities")
                        return view
                timed(overview, samples["economy_regions"])
            # The clock has not run a completed month at this point. Initialize
            # a world_state cursor, then process the following month with true
            # production.step_month, not an imitation or synthetic sleep.
            with game_server.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO world_state(id,processed_through) VALUES(1,-1) "
                           "ON CONFLICT(id) DO UPDATE SET processed_through=excluded.processed_through")
                db.commit()
            for month in (0, 1):
                def settle():
                    with game_server.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        # Source code uses the current clock only to pick which
                        # complete month to settle; previous world state -1.
                        clk = {"month_index": month+1, "server_time": NOW + (month+1)*86400}
                        result = production.advance(db, "?", clk, NOW + (month+1)*86400)
                        db.commit()
                        return result
                count = timed(settle, samples["monthly_step"])
                if count != 1:
                    raise RuntimeError("expected single month settled: "+str(count))
                results["month_step_ms"].append(round(samples["monthly_step"][-1],2))
                print("PROBE month",month,results["month_step_ms"][-1],"ms",flush=True)
            with game_server.connect() as db:
                ledger_bad = db.execute(
                    "SELECT COUNT(*) FROM (SELECT tx_id FROM ledger_entries "
                    "GROUP BY tx_id HAVING SUM(amount) <> 0)").fetchone()[0]
                results["ledger_bad_transactions"] = int(ledger_bad)
                results["wallet_total"] = int(db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0])
                results["active_cities"] = len(regions.active_regions(db,"?"))
                results["road_count"] = int(db.execute("SELECT COUNT(*) FROM roads").fetchone()[0])
                results["building_count"] = int(db.execute("SELECT COUNT(*) FROM buildings").fetchone()[0])
                results["order_count"] = int(db.execute("SELECT COUNT(*) FROM soc_orders").fetchone()[0])
    results["operation_timings"] = {k: stats(values) for k,values in samples.items()}
    return results


if __name__ == "__main__":
    args=argparse.ArgumentParser()
    args.add_argument("--players",type=int,default=200)
    args.add_argument("--output",default="")
    parsed=args.parse_args()
    report=run(parsed.players)
    output=json.dumps(report,ensure_ascii=False,indent=2)
    print("PROBE_RESULTS_START")
    print(output)
    if parsed.output:
        Path(parsed.output).write_text(output)
    if report["ledger_bad_transactions"] or report["wallet_total"] != 0:
        raise SystemExit("ledger invariants failed")
