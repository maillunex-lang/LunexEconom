"""100 simultaneous loopback HTTP requests per endpoint on real Waitress.

Requires LUNEX_TEST_DATABASE_URL, never touches production DSN.
"""
import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from statistics import median
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
from uuid import uuid4

from server import db
from server.platform.security import hash_password


def request(url,method='GET',payload=None,ip=None):
    data=json.dumps(payload).encode() if payload is not None else None
    started=time.monotonic()
    try:
        headers={'Content-Type':'application/json'}
        if ip: headers['X-Real-IP']=ip
        with urlopen(Request(url,data=data,method=method,headers=headers),timeout=35) as response:
            code=response.status
            raw=response.read(10000)
            json.loads(raw)
    except HTTPError as exc:
        code=exc.code
    except Exception as exc:
        return ('NETWORK:'+str(exc),time.monotonic()-started)
    return code,time.monotonic()-started


def batch(name,urls,expected):
    started=time.monotonic()
    with ThreadPoolExecutor(max_workers=100) as executor:
        results=list(executor.map(lambda entry:request(*entry),urls))
    codes={}
    for code,elapsed in results:
        codes[code]=codes.get(code,0)+1
    latencies=sorted(elapsed for _,elapsed in results)
    p95=latencies[int(0.95*(len(latencies)-1))]
    print(f'{name}: 100 concurrent, status={codes}, elapsed={time.monotonic()-started:.3f}s, p50={median(latencies):.3f}s, p95={p95:.3f}s, max={max(latencies):.3f}s',flush=True)
    if codes != {expected:len(urls)}:
        raise AssertionError(f'{name} HTTP failures: {codes}')


def main():
    dsn=os.getenv('LUNEX_TEST_DATABASE_URL')
    if not dsn or dsn!=os.getenv('LUNEX_DATABASE_URL'):
        raise SystemExit('Isolated test DSN required as BOTH LUNEX_TEST_DATABASE_URL and LUNEX_DATABASE_URL')
    password='TestLoadOnlyPassword_2026!'
    hashed=hash_password(password)
    tag=uuid4().hex[:9]
    users=[]
    with db.connect(dsn) as conn:
        for i in range(100):
            user='load'+tag+str(i)
            conn.execute('INSERT INTO accounts(username,email,password_hash,role) VALUES(%s,%s,%s,%s)',(user,user+'@example.com',hashed,'player'))
            users.append(user)
        conn.commit()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        port=sock.getsockname()[1]
    env=dict(os.environ,LUNEX_PORT=str(port),LUNEX_THREADS='8',LUNEX_POOL_MIN='2',LUNEX_POOL_MAX='10',LUNEX_TICK_INTERVAL='60',LUNEX_TRUST_PROXY_REAL_IP='1')
    process=subprocess.Popen([sys.executable,'-m','server.game_server'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    base=f'http://127.0.0.1:{port}'
    try:
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError('Waitress exited before serving')
            status,_=request(base+'/health')
            if status==200:break
            time.sleep(0.2)
        else:
            raise RuntimeError('Waitress did not start')
        batch('/health',[(base+'/health',) for _ in range(100)],200)
        batch('/auth/login',[(base+'/auth/login','POST',{'username':user,'password':password},'10.54.1.'+str(i+1)) for i,user in enumerate(users)],200)
    finally:
        process.terminate()
        try: process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill();process.wait()

if __name__=='__main__':main()
