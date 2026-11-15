#!/usr/bin/env python3
"""Sign the current runtime client configuration offline using the same RSA key as LivePatch.

The private key never leaves this trusted operator process; the server and
World Studio only see a detached signature. Use through an SSH tunnel.
"""
import argparse
import base64
import json
import os
import sys
from pathlib import Path

from sign_release import call, sign_bytes

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--studio",required=True)
    parser.add_argument("--key",required=True)
    args=parser.parse_args()
    token=os.environ.get("LUNEX_ADMIN_TOKEN","")
    if len(token)<32:
        print("LUNEX_ADMIN_TOKEN is required",file=sys.stderr)
        return 2
    base=args.studio.rstrip("/")
    info=json.loads(call(base+"/api/game/config/candidate",token))
    raw=base64.b64decode(info["payload_b64"],validate=True)
    signature=base64.b64encode(sign_bytes(Path(args.key),raw)).decode()
    result=json.loads(call(base+"/api/game/config/sign",token,
        {"confirm":True,"revision":int(info["revision"]),"signature":signature}))
    print("Client configuration signed, revision",result.get("revision"))
    return 0

if __name__=="__main__":
    sys.exit(main())
