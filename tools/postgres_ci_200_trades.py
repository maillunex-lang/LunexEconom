"""200 distinct actors submit exchange orders against disposable PostgreSQL lunex_ci."""
import concurrent.futures
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import postgres_db
import postgres_world


def run():
    if (os.getenv("LUNEX_PG_DB"), os.getenv("LUNEX_PG_PORT"), os.getenv("LUNEX_PG_HOST")) != (
            "lunex_ci", "15499", "127.0.0.1"):
        raise RuntimeError("Refusing non-isolated PostgreSQL")
    postgres_db.init()
    with postgres_db.connect() as db:
        db.execute("DELETE FROM soc_fills")
        db.execute("DELETE FROM soc_orders")
        db.execute("DELETE FROM inventory WHERE owner LIKE 'chatgpt8_%'")
        for i in range(100):
            db.execute("INSERT INTO inventory(owner,product,qty) VALUES(%s,'honey',1)",
                       (f"chatgpt8_stress_seller_{i:03d}",))
        db.commit()
    def submit(i, side):
        owner = f"chatgpt8_stress_{side}er_{i:03d}"
        start = time.perf_counter()
        result = postgres_world.soc_post(owner, "/soc/exchange/order", {
            "side":side, "product":"honey", "qty":1, "price":200,
            "request_id":str(uuid.uuid4())}, "192.0.2." + str(i + 1))
        return result[0], round((time.perf_counter()-start)*1000,2)
    # Bounded concurrency; never uses production DB.
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        sells=list(pool.map(lambda i:submit(i,"sell"),range(100)))
        buys=list(pool.map(lambda i:submit(i,"buy"),range(100)))
    with postgres_db.connect() as db:
        matched=db.execute("SELECT COALESCE(SUM(qty),0) FROM soc_fills WHERE product='honey'").fetchone()[0]
        stock=db.execute("SELECT COALESCE(SUM(qty),0) FROM inventory WHERE owner LIKE 'chatgpt8_stress_%' AND product='honey'").fetchone()[0]
        reserved=db.execute("SELECT COALESCE(SUM(qty_left),0) FROM soc_orders WHERE side='sell' AND status='open' AND product='honey'").fetchone()[0]
        bad=db.execute("SELECT COUNT(*) FROM (SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0) t").fetchone()[0]
    codes={}
    for status,_ in sells+buys:codes[str(status)]=codes.get(str(status),0)+1
    result={"actors":200,"max_workers":12,"client_ip_model":"distinct RFC5737 TEST-NET-1 IP per actor","status_codes":codes,
            "matched_qty":int(matched),"inventory_qty":int(stock),
            "open_sell_qty":int(reserved),"unbalanced_ledger":int(bad),
            "p95_ms":sorted(t for _,t in sells+buys)[190]}
    assert codes=={"201":200} and matched==100 and stock==100 and reserved==0 and bad==0,result
    return result

if __name__=="__main__":
    print(json.dumps(run(),indent=2))