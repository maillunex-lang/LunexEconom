"""Isolated HTTP adapter for EX-03/EX-04; no duplicate auth or DB connection stack."""
import json
import os
import time
from urllib.parse import parse_qs, urlsplit

import construction_projects
import contractors
import land
import tenders

GET = frozenset(("/land", "/auctions", "/projects", "/tenders", "/contractors"))
POST = {
    "/land/buy": land.buy,
    "/land/lease": land.lease,
    "/land/rezone": land.rezone,
    "/land/rezone/decide": land.decide_rezone,
    "/land/fixed-price": land.set_fixed_price,
    "/land/buyback": land.buyback,
    "/land/buyback/consent": land.consent_buyback,
    "/auctions/create": land.start_auction,
    "/auctions/bid": land.bid,
    "/auctions/cancel": land.cancel_auction,
    "/projects": construction_projects.create,
    "/projects/cancel": construction_projects.cancel,
    "/projects/fund": construction_projects.fund,
    "/projects/repair": construction_projects.repair,
    "/contractors/register": contractors.register,
    "/tenders/create": tenders.create,
    "/tenders/bid": tenders.bid,
}
LAND_WRITES = frozenset(("/land/buy","/land/lease","/land/rezone","/land/rezone/decide",
                         "/land/fixed-price","/land/buyback","/land/buyback/consent","/auctions/create","/auctions/bid","/auctions/cancel"))
PROJECT_WRITES = frozenset(POST)-LAND_WRITES

def handle_http(handler, method):
    """Return False for another subsystem's path, True once this route responds."""
    import game_server
    url=urlsplit(handler.path)
    path=url.path
    if method=="GET":
        if path not in GET:return False
    elif method=="POST":
        if path not in POST:return False
    else:
        return False
    land_on=land.enabled()
    projects_on=construction_projects.enabled()
    if method=="GET" and path=="/land" and not land_on:
        handler._send(200,{"enabled":False,"parcel_size":land.PARCEL_SIZE,"parcels":[]})
        return True
    if path in LAND_WRITES and not land_on:
        handler._send(404,{"error":"feature_disabled","feature":"land"})
        return True
    if path in PROJECT_WRITES and not projects_on:
        handler._send(404,{"error":"feature_disabled","feature":"construction_projects"})
        return True
    owner=handler._identity()
    if not owner:
        handler._send(401,{"error":"unauthorized"})
        return True
    payload={}
    if method=="POST":
        try:
            size=int(handler.headers.get("Content-Length","0"))
            if not 2<=size<=4096: raise ValueError("body length")
            payload=json.loads(handler.rfile.read(size))
            if not isinstance(payload,dict):raise ValueError("body type")
        except (ValueError,UnicodeError,json.JSONDecodeError):
            handler._send(400,{"error":"invalid_body"})
            return True
    with game_server.LOCK, game_server.NPC_CONNECT() as db:
        ph=game_server.NPC_PH
        if ph=="%s":
            db.execute("SELECT pg_advisory_xact_lock(20261114)")
        else:
            db.execute("BEGIN IMMEDIATE")
        now=int(time.time())
        # Reconcile pre-existing buildings before ANY new land sale or reservation.
        if land_on:land.migrate_existing(db,ph)
        if method=="POST":
            status,data=POST[path](db,ph,owner,payload,now)
        elif path=="/land":
            try:
                qs=parse_qs(url.query)
                cx=int(qs["cx"][0]);cy=int(qs["cy"][0])
                if len(qs["cx"])!=1 or len(qs["cy"])!=1:raise ValueError("duplicates")
            except (KeyError,IndexError,TypeError,ValueError):
                status,data=400,{"error":"invalid_query"}
            else:
                status,data=land.view_chunk(db,ph,cx,cy)
        elif path=="/auctions":
            if land_on:land.close_due(db,ph,land._month(db,ph,now),now)
            status,data=land.auctions(db,ph)
        elif path=="/projects":
            status,data=construction_projects.list_projects(db,ph,owner)
        elif path=="/tenders":
            status,data=tenders.view(db,ph,owner)
        else:
            status,data=contractors.view(db,ph)
    handler._send(status,data)
    return True
