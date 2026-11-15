"""End-to-end loopback HTTP probe on a disposable SQLite database only."""
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def request(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.load(error)


def run():
    server = Path(__file__).resolve().parents[1] / "server"
    with tempfile.TemporaryDirectory(prefix="lunex-http-isolated-") as temp:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, LUNEX_WORLD_DB=str(Path(temp)/"world.sqlite3"),
                   LUNEX_PORT=str(port), LUNEX_DB_ENGINE="sqlite")
        with open(Path(temp)/"server.log", "w") as log:
            process = subprocess.Popen([sys.executable, "-u", str(server/"game_server.py")],
                                       cwd=str(server), env=env, stdout=log, stderr=log)
            try:
                base = "http://127.0.0.1:" + str(port)
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("isolated server terminated: " + Path(temp, "server.log").read_text()[-2000:])
                    try:
                        status, _ = request(base + "/health")
                        if status == 200:
                            break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(.1)
                else:
                    raise TimeoutError("isolated server startup timeout")
                results = {}
                for path in ("/health", "/catalog/goods", "/deposits?x0=0&y0=0&x1=8&y1=8"):
                    status, data = request(base + path)
                    results[path] = {"status": status, "payload_type": type(data).__name__}
                    if status != 200:
                        raise AssertionError(results[path])
                return results
            finally:
                process.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=5)
                if process.poll() is None:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))