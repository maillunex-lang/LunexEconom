"""SEC1 local-only stdlib HTTP workload. Never targets production by default."""
import argparse
import json
import math
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from ipaddress import ip_address
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4


def is_local(url):
    parsed=urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        return False
    if parsed.hostname=='localhost':return True
    try:return ip_address(parsed.hostname).is_loopback
    except ValueError:return False


def request(base, method, path, payload=None, token=None, timeout=12, simulated_ip=None):
    started=time.perf_counter()
    data=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode() if payload is not None else None
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    if simulated_ip:headers['X-Real-IP']=simulated_ip
    try:
        with urlopen(Request(base+path,data=data,headers=headers,method=method),timeout=timeout) as reply:
            code=reply.status;content=reply.read(1024*256)
    except HTTPError as exc:
        code=exc.code;content=exc.read(1024*256)
    except Exception:
        return (0,(time.perf_counter()-started)*1000,{},'network_error')
    try:
        decoded=json.loads(content) if content else {}
    except (ValueError,UnicodeDecodeError):
        return (code,(time.perf_counter()-started)*1000,{},'invalid_json')
    return (code,(time.perf_counter()-started)*1000,decoded,None)


def percentile(values,p):
    if not values:return None
    s=sorted(values);position=(len(s)-1)*p/100
    a=math.floor(position);b=math.ceil(position)
    return round(s[a]*(b-position)+s[b]*(position-a),2) if a!=b else round(s[a],2)


def scenario(base,i,seed,simulate_ips=False):
    simulated_ip=f"10.176.{i//250+1}.{i%250+1}" if simulate_ips else None
    unique=uuid4().hex[:12]
    name='l'+unique
    email=name+'@example.test'
    password='SEC1_ExamplePassword_12345!'
    results=[]
    def call(stage,method,path,body=None,token=None):
        code,ms,payload,error=request(base,method,path,body,token,simulated_ip=simulated_ip)
        results.append({'stage':stage,'status':code,'latency_ms':round(ms,2),'error':error})
        return code,payload
    code,_=call('register','POST','/auth/register',{'username':name,'email':email,'password':password})
    if code!=201:return results
    code,auth=call('login','POST','/auth/login',{'username':name,'password':password})
    if code!=200:return results
    token=auth.get('access_token')
    call('map','GET','/world/chunk?cx=0&cy=0',token=token)
    # Distinct deterministic parcels; buying may be rejected by legitimate game rules.
    px,py=40+i,40+i
    code,_=call('land','POST','/land/buy',{'px':px,'py':py,'request_id':'load-land:'+unique},token)
    if code==201:
        call('build','POST','/enterprises',{'px':px,'py':py,'x':px*6+2,'y':py*6+2,'building_id':'field','request_id':'load-build:'+unique},token)
    call('enterprises','GET','/enterprises',token=token)
    return results


def run(args):
    if not is_local(args.dry_url) and not args.i_know_this_is_not_production:
        raise SystemExit('REFUSED: remote target requires --i-know-this-is-not-production')
    hostname=urlparse(args.dry_url).hostname or ''
    if hostname.lower() in ('rikagro.ru','www.rikagro.ru') or hostname.lower().endswith('.rikagro.ru'):
        raise SystemExit('REFUSED: production domain is forbidden')
    if args.simulate_ips and not is_local(args.dry_url):
        raise SystemExit('REFUSED: simulated IPs only supported on a loopback test server')
    started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        records=[record for group in pool.map(lambda i:scenario(args.dry_url.rstrip('/'),i,args.seed,args.simulate_ips),range(args.players)) for record in group]
    elapsed=time.perf_counter()-started
    durations=[r['latency_ms'] for r in records]
    summary={'url':args.dry_url,'players':args.players,'concurrency':args.concurrency,'simulated_ips':args.simulate_ips,
      'total_requests':len(records),'elapsed_seconds':round(elapsed,2),
      'requests_per_second':round(len(records)/max(elapsed,0.001),2),
      'latency_ms':{'p50':percentile(durations,50),'p95':percentile(durations,95),'p99':percentile(durations,99)},
      'codes':dict(sorted(Counter(str(r['status']) for r in records).items())),
      'stages':{stage:dict(sorted(Counter(str(r['status']) for r in records if r['stage']==stage).items()))
        for stage in sorted(set(r['stage'] for r in records))},
      'network_errors':sum(bool(r['error']) for r in records)}
    if args.report:
        with open(args.report,'w',encoding='utf-8') as output:json.dump(summary,output,ensure_ascii=False,indent=2)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary


def main():
    ap=argparse.ArgumentParser(description='SEC1 local-only game API load test')
    ap.add_argument('--dry-url',default='http://127.0.0.1:18777')
    ap.add_argument('--players',type=int,default=100)
    ap.add_argument('--concurrency',type=int,default=10)
    ap.add_argument('--seed',type=int,default=20261116)
    ap.add_argument('--simulate-ips',action='store_true',help='Only local test server with LUNEX_TRUST_PROXY_REAL_IP=1')
    ap.add_argument('--report',default='')
    ap.add_argument('--i-know-this-is-not-production',action='store_true')
    args=ap.parse_args()
    if not 1<=args.players<=10000 or not 1<=args.concurrency<=100:
        ap.error('players must be 1..10000 and concurrency 1..100')
    run(args)

if __name__=='__main__':main()
