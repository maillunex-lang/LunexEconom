"""Isolated end-to-end oil deposit build checks via authenticated HTTP."""
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


def call(base, token, payload):
    request = urllib.request.Request(
        base + "/build", data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.load(error)


def run():
    server = Path(__file__).resolve().parents[1] / "server"
    with tempfile.TemporaryDirectory(prefix="lunex-http-deposit-") as temp:
        world = Path(temp) / "world.sqlite3"
        auth = Path(temp) / "accounts.sqlite3"
        token = "isolated-oil-well-auth"
        with sqlite3.connect(auth) as db:
            db.executescript("""
                CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,email TEXT UNIQUE NOT NULL,salt BLOB NOT NULL,password_hash BLOB NOT NULL,created_at INTEGER NOT NULL);
                CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,expires_at INTEGER NOT NULL);
            """)
            db.execute("INSERT INTO users VALUES(1,'alice','alice@example.invalid',?,?,?)", (b"salt", b"hash", int(time.time())))
            db.execute("INSERT INTO sessions VALUES(?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), 1, int(time.time()) + 3600))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, LUNEX_WORLD_DB=str(world), LUNEX_AUTH_DB=str(auth),
                   LUNEX_PORT=str(port), LUNEX_DB_ENGINE="sqlite")
        with open(Path(temp) / "server.log", "w") as log:
            proc = subprocess.Popen([sys.executable, "-u", str(server / "game_server.py")],
                                    cwd=str(server), env=env, stdout=log, stderr=log)
            try:
                base = f"http://127.0.0.1:{port}"
                for _ in range(100):
                    if proc.poll() is not None:
                        raise RuntimeError(Path(temp, "server.log").read_text()[-2500:])
                    try:
                        with urllib.request.urlopen(base + "/health", timeout=2) as resp:
                            if resp.status == 200:
                                break
                    except urllib.error.URLError:
                        time.sleep(.1)
                else:
                    raise TimeoutError("test server did not start")
                sys.path.insert(0, str(server))
                import deposits
                with sqlite3.connect(world) as db:
                    origins = db.execute("SELECT x,y,id FROM deposits WHERE resource='oil' ORDER BY id").fetchall()
                assert len(origins) >= 2, origins
                x, y, _ = origins[0]
                # No-deposit coordinate is guaranteed to be far from any deposit.
                def build_at(px, py):
                    return call(base, token, {"kind":"oil_well", "x":px, "y":py, "request_id":str(uuid.uuid4())})
                no_deposit = None
                for candidate_y in range(6, 350, 4):
                    candidate = build_at(2, candidate_y)
                    if candidate[1].get("error") == "no_deposit":
                        no_deposit = candidate
                        break
                assert no_deposit is not None, "no road-accessible off-deposit site found"
                built = build_at(x, y)
                # Another oil well at the same deposit but on a free cell should be deposit_busy.
                # If the original footprint occupies the entire deposit, attach a different
                # building to a second deposit, matching the server's established unit fixture.
                x2, y2, dep_id2 = origins[1]
                with sqlite3.connect(world) as db:
                    db.execute("INSERT INTO buildings(id,owner,kind,x,y,created) VALUES(?,?,?,?,?,?)",
                               ("qa-busy-fixture", "fixture", "farm", 8990, 8990, int(time.time())))
                    db.execute("INSERT INTO building_deposits(object_id,deposit_id,resource) VALUES(?,?,?)",
                               ("qa-busy-fixture", dep_id2, "oil"))
                    db.commit()
                busy = build_at(x2, y2)
                result = {"no_deposit": [no_deposit[0], no_deposit[1].get("error")],
                          "valid_well": built[0],
                          "deposit_busy": [busy[0], busy[1].get("error")]}
                assert result == {"no_deposit":[409,"no_deposit"],"valid_well":201,
                                  "deposit_busy":[409,"deposit_busy"]}, result
                return result
            finally:
                proc.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=5)
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))