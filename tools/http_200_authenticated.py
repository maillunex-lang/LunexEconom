"""200 authenticated simulated players on a disposable loopback SQLite world."""
import concurrent.futures
import contextlib
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid


def get(url, token=None):
    request = urllib.request.Request(url, headers={"Authorization":"Bearer "+token} if token else {})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.load(error)


def run():
    server = Path(__file__).resolve().parents[1] / "server"
    with tempfile.TemporaryDirectory(prefix="lunex-auth-200-") as temp:
        auth_path = Path(temp) / "accounts.sqlite3"
        with sqlite3.connect(auth_path) as db:
            db.executescript("""
                CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,email TEXT UNIQUE NOT NULL,salt BLOB NOT NULL,password_hash BLOB NOT NULL,created_at INTEGER NOT NULL);
                CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,expires_at INTEGER NOT NULL);
            """)
            tokens = []
            for i in range(200):
                token = f"isolated-chatgpt8-session-{i:04d}"
                tokens.append(token)
                db.execute("INSERT INTO users(id,username,email,salt,password_hash,created_at) VALUES(?,?,?,?,?,?)",
                           (i+1, f"testplayer{i:04d}", f"player{i:04d}@example.invalid", b"salt", b"hash", int(time.time())))
                db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
                           (hashlib.sha256(token.encode()).hexdigest(), i+1, int(time.time())+3600))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0))
            port = sock.getsockname()[1]
        env = dict(os.environ, LUNEX_WORLD_DB=str(Path(temp)/"world.sqlite3"),
                   LUNEX_AUTH_DB=str(auth_path), LUNEX_PORT=str(port), LUNEX_DB_ENGINE="sqlite")
        with open(Path(temp)/"server.log","w") as log:
            process = subprocess.Popen([sys.executable,"-u",str(server/"game_server.py")],
                                       cwd=str(server),env=env,stdout=log,stderr=log)
            try:
                base = f"http://127.0.0.1:{port}"
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError(Path(temp,"server.log").read_text()[-2000:])
                    try:
                        if get(base+"/health")[0]==200: break
                    except urllib.error.URLError:
                        time.sleep(.1)
                else: raise TimeoutError("isolated HTTP startup")
                def one(i):
                    start=time.perf_counter()
                    status, payload=get(base+"/wallet",tokens[i])
                    return status, payload.get("error"), (time.perf_counter()-start)*1000
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
                    results=list(pool.map(one,range(200)))
                codes={}
                for status,_,_ in results: codes[str(status)]=codes.get(str(status),0)+1
                # Each authenticated player submits one authoritative build transaction.
                def build(i):
                    payload = json.dumps({"kind":"farm", "x":2, "y":6+4*i,
                                          "request_id":str(uuid.uuid4())}).encode()
                    req = urllib.request.Request(base+"/build", data=payload, method="POST",
                        headers={"Authorization":"Bearer "+tokens[i], "Content-Type":"application/json"})
                    try:
                        with urllib.request.urlopen(req, timeout=30) as response:
                            return response.status, json.load(response)
                    except urllib.error.HTTPError as error:
                        with error:
                            return error.code, json.load(error)
                with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                    builds=list(pool.map(build,range(200)))
                build_codes={}
                build_errors={}
                for status,payload in builds:
                    build_codes[str(status)]=build_codes.get(str(status),0)+1
                    if status!=201:
                        key=payload.get("error","unknown")
                        build_errors[key]=build_errors.get(key,0)+1
                with sqlite3.connect(Path(temp)/"world.sqlite3") as db:
                    bad=db.execute("SELECT COUNT(*) FROM (SELECT tx_id FROM ledger_entries GROUP BY tx_id HAVING SUM(amount)<>0)").fetchone()[0]
                    wallet_total=db.execute("SELECT COALESCE(SUM(balance),0) FROM wallets").fetchone()[0]
                output={"players":200,"parallel_workers":20,"statuses":codes,
                        "p95_ms":round(sorted(x[2] for x in results)[190],2),
                        "build_statuses":build_codes,
                        "build_errors":build_errors,
                        "unbalanced_ledger_transactions":bad,"wallet_sum":wallet_total}
                assert codes=={"200":200} and bad==0 and wallet_total==0,output
                assert sum(build_codes.values())==200 and build_codes.get("201",0)>0 and all(int(k)<500 for k in build_codes),output
                assert set(build_errors).issubset({"no_road_access", "occupied", "insufficient_funds", "blocked", "not_buildable", "out_of_bounds", "road_overlap"}),output
                return output
            finally:
                process.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired): process.wait(timeout=5)
                if process.poll() is None: process.kill();process.wait()


if __name__=="__main__":
    print(json.dumps(run(),indent=2))