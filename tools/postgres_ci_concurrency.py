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
        db.execute("DELETE FROM inventory WHERE owner='chatgpt8_seller'")
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
    result = {"codes": sorted(x[0] for x in results), "stock": int(stock),
              "reserved": int(reserved), "ledger_bad": int(ledger_bad)}
    assert result == {"codes":[201,409],"stock":0,"reserved":10,"ledger_bad":0}, result
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))