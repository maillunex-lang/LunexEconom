"""Compare legacy per-city price fetch vs batched fetch on disposable SQLite."""
import json
import os
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import game_server
import regions
import economy


def run():
    with tempfile.TemporaryDirectory(prefix="regions-bench-") as tmp:
        original = game_server.DB
        game_server.DB = str(Path(tmp) / "world.sqlite3")
        try:
            with game_server.connect() as db:
                active = regions.region_ids()
                month = 12
                for region in active:
                    for product in economy.MARKET:
                        db.execute(
                            "INSERT INTO market_prices_region(region,product,month_index,price,supply,demand,imports,exports) VALUES(?,?,?,?,?,?,?,?)",
                            (region, product, month, 100, 10, 20, 0, 0))
                db.commit()
                def legacy():
                    prices = {}
                    for region in active:
                        prices[region] = {}
                        for row in db.execute("SELECT product,price,supply,demand,imports,exports FROM market_prices_region WHERE region=? AND month_index=?", (region,month)):
                            product,price,supply,demand,imports,exports = row
                            prices[region][product] = {"price":int(price),"supply":int(supply),"demand":int(demand),"imports":int(imports),"exports":int(exports)}
                    return prices
                def batched():
                    prices = {}
                    for region,product,price,supply,demand,imports,exports in db.execute("SELECT region,product,price,supply,demand,imports,exports FROM market_prices_region WHERE month_index=?", (month,)):
                        prices.setdefault(region,{})[product] = {"price":int(price),"supply":int(supply),"demand":int(demand),"imports":int(imports),"exports":int(exports)}
                    return prices
                assert legacy() == batched()
                def measure(fn):
                    times=[]
                    for _ in range(120):
                        t=time.perf_counter_ns()
                        fn()
                        times.append((time.perf_counter_ns()-t)/1e6)
                    return round(statistics.median(times),4)
                old_ms=measure(legacy)
                new_ms=measure(batched)
                return {"scope":"price-fetch portion of regions.overview, not full endpoint",
                        "regions":len(active),"products":len(economy.MARKET),
                        "legacy_queries":len(active),"batched_queries":1,
                        "legacy_median_ms":old_ms,"batched_median_ms":new_ms,
                        "speedup":round(old_ms/new_ms,2) if new_ms else None}
        finally:
            game_server.DB = original


if __name__ == "__main__":
    print(json.dumps(run(),indent=2))