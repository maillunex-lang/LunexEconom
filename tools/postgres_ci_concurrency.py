"""Exchange concurrency smoke, ONLY on explicitly named disposable lunex_ci."""
import concurrent.futures
import json
import os
import sys
import threading
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import postgres_db
import postgres_world


def run():
    if os.getenv("LUNEX_PG_DB") != "lunex_ci" or os.getenv("LUNEX_PG_PORT") != "15499":
        raise RuntimeError("Refusing non-CI PostgreSQL database or port")
    if os.getenv("LUNEX_PG_HOST") not in ("127.0.0.1", "localhost"):
        raise RuntimeError("Refusing non-loopback PostgreSQL")
    postgres_db.init()
    with postgres_db.connect() as db:
        db.execute("DELETE FROM soc_fills")
        db.execute("DELETE FROM soc_orders")
        db.execute("DELETE FROM inventory WHERE owner LIKE 'chatgpt8_%'")
        db.execute("INSERT INTO inventory(owner,product,qty) VALUES('chatgpt8_seller','honey',10)")
        db.commit()
    barrier = threading.Barrier(2)

    def sell(index):
        barrier.wait()
        return postgres_world.soc_post(
            "chatgpt8_seller", "/soc/exchange/order",
            {"side":"sell","product":"honey","qty":10,"price":200,
             "request_id":str(uuid.uuid4())},
            "127.0.0.1")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(sell, i) for i in range(2)]
        results = [f.result(timeout=30) for f in futures]
    with postgres_db.connect() as db:
        stock = db.execute("SELECT COALESCE(SUM(qty),0) FROM inventory WHERE owner='chatgpt8_seller' AND product='honey'").fetchone()[0]
        reserved = db.execute("SELECT COALESCE(SUM(qty_left),0) FROM soc_orders WHERE owner='chatgpt8_seller' AND side='sell' AND product='honey' AND status='open'").fetchone()[0]
        ledger_bad = db.execute("SELECT COUNT(*) FROM (SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0) bad").fetchone()[0]
    # Two independent buyers race for a single reserved 10-unit sell order.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        def buy(i):
            return postgres_world.soc_post(
                f"chatgpt8_buyer_{i}", "/soc/exchange/order",
                {"side":"buy","product":"honey","qty":7,"price":200,
                 "request_id":str(uuid.uuid4())}, "127.0.0.1")
        buyer_results = list(pool.map(buy, range(2)))
    with postgres_db.connect() as db:
        stock_after = db.execute("SELECT COALESCE(SUM(qty),0) FROM inventory WHERE product='honey' AND owner LIKE 'chatgpt8_%'").fetchone()[0]
        reserved_after = db.execute("SELECT COALESCE(SUM(qty_left),0) FROM soc_orders WHERE product='honey' AND side='sell' AND status='open' AND owner='chatgpt8_seller'").fetchone()[0]
        filled = db.execute("SELECT COALESCE(SUM(qty),0) FROM soc_fills WHERE product='honey'").fetchone()[0]
        ledger_bad_after = db.execute("SELECT COUNT(*) FROM (SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0) bad").fetchone()[0]
    trade = {"buyer_codes":sorted(r[0] for r in buyer_results), "stock_after":int(stock_after),
             "reserved_after":int(reserved_after),"filled":int(filled),
             "ledger_bad_after":int(ledger_bad_after)}
    assert trade["buyer_codes"] == [201,201] and trade["filled"] == 10, trade
    assert trade["stock_after"] + trade["reserved_after"] == 10, trade
    assert trade["ledger_bad_after"] == 0, trade
    result = {"trade":trade,"codes": sorted(x[0] for x in results), "stock": int(stock),
              "reserved": int(reserved), "ledger_bad": int(ledger_bad)}
    assert {k:v for k,v in result.items() if k != "trade"} == {"codes":[201,409],"stock":0,"reserved":10,"ledger_bad":0}, result
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))