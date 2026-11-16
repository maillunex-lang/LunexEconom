"""A3 player announcements: immutable creation, time window and city visibility."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from server.catalog import canonical
from . import admin, api
from .admin_catalog import _request
from .admin_server import guard

_WRITE = {"owner", "admin"}


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 45:
        raise ValueError("invalid_datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid_datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError("timezone_required")
    return parsed.astimezone(timezone.utc)


def _clean(value, minimum, maximum):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError("invalid_text_length")
    if any(c in value for c in ("<", ">", "\x00")):
        raise ValueError("html_not_allowed")
    return value.strip()


def create(body, ctx):
    actor, err = guard(ctx, _WRITE)
    if err:
        return err
    try:
        req = _request(body)
        title, text = _clean(body.get("title"), 1, 80), _clean(body.get("body"), 1, 500)
        level = body.get("level")
        if level not in ("info", "warn"):
            raise ValueError("invalid_level")
        city = body.get("city_id")
        if city is not None and (not isinstance(city, str) or len(city)>80 or
          not ctx["conn"].execute("SELECT 1 FROM world_cities WHERE id=%s", (city,)).fetchone()):
            raise ValueError("invalid_city")
        begins, ends = _timestamp(body.get("starts_at")), _timestamp(body.get("ends_at"))
        if ends <= begins or (ends - begins).days > 366:
            raise ValueError("invalid_window")
        signature = hashlib.sha256(canonical(
            {"title": title, "body": text, "level": level, "city": city,
             "starts_at": begins.isoformat(), "ends_at": ends.isoformat()})).hexdigest()
        conn = ctx["conn"]
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("announcement:"+req,))
        old = conn.execute("SELECT id,request_hash FROM announcements WHERE request_id=%s", (req,)).fetchone()
        if old:
            return (200, {"ok": True, "id": old[0], "idempotent": True}) if old[1]==signature else (409, {"error":"request_id_conflict"})
        ident = conn.execute("""INSERT INTO announcements
           (request_id,request_hash,title,body,level,city_id,starts_at,ends_at,created_by)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
           (req, signature, title, text, level, city, begins, ends, actor["username"])).fetchone()[0]
        admin._audit(ctx, actor, "announcement.create", {"request_id":req},
            old=None, new={"id":ident,"title":title,"body":text,"level":level,"city_id":city,
                           "starts_at":begins.isoformat(),"ends_at":ends.isoformat(),"active":True})
        return 201, {"ok":True,"id":ident}
    except (TypeError, ValueError) as exc:
        return 400, {"error":str(exc),"message":"Проверьте текст, город и даты объявления."}


def list_admin(body, ctx):
    actor, err = guard(ctx)
    if err:
        return err
    rows = ctx["conn"].execute("""SELECT id,title,body,level,city_id,starts_at,ends_at,
         created_by,created_at,active FROM announcements ORDER BY id DESC LIMIT 200""").fetchall()
    return 200, {"items":[{"id":r[0],"title":r[1],"body":r[2],"level":r[3],
        "city_id":r[4],"starts_at":r[5].isoformat(),"ends_at":r[6].isoformat(),
        "created_by":r[7],"created_at":r[8].isoformat(),"active":r[9]} for r in rows]}


def deactivate(body, ctx):
    actor, err = guard(ctx, _WRITE)
    if err:
        return err
    try:
        req = _request(body)
        ident = int(ctx["path_params"]["id"])
        conn = ctx["conn"]
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("announcement-deactivate:"+req,))
        signature=hashlib.sha256(canonical({"id":ident})).hexdigest()
        old=conn.execute("SELECT announcement_id,request_hash FROM announcement_deactivations WHERE request_id=%s",(req,)).fetchone()
        if old:
            return (200,{"ok":True,"id":ident,"idempotent":True}) if old==(ident,signature) else (409,{"error":"request_id_conflict"})
        row=conn.execute("SELECT active,title FROM announcements WHERE id=%s FOR UPDATE",(ident,)).fetchone()
        if row is None:
            return 404,{"error":"not_found"}
        conn.execute("INSERT INTO announcement_deactivations(request_id,announcement_id,request_hash) VALUES(%s,%s,%s)",
                     (req,ident,signature))
        if row[0]:
            conn.execute("UPDATE announcements SET active=false WHERE id=%s",(ident,))
            admin._audit(ctx,actor,"announcement.deactivate",{"request_id":req},old={"id":ident,"active":True},
                         new={"id":ident,"active":False})
        return 200,{"ok":True,"id":ident,"active":False}
    except (ValueError, TypeError) as exc:
        return 400,{"error":str(exc)}


def public(body, ctx):
    player=api.authenticate(ctx,track=False)
    if player is None:
        return 401,{"error":"unauthorized"}
    ctx["conn"].execute("SELECT set_config('statement_timeout','5000',true)")
    # A player can have more than one city. Ownership of parcels/enterprises is authoritative.
    rows=ctx["conn"].execute("""SELECT id,title,body,level,city_id,starts_at,ends_at
         FROM announcements a
         WHERE a.active=true AND a.starts_at<=now() AND a.ends_at>now()
         AND (a.city_id IS NULL OR
              EXISTS (SELECT 1 FROM world_parcels p WHERE p.owner_kind='player'
                      AND p.owner_ref=%s AND p.city_id=a.city_id)
              OR EXISTS (SELECT 1 FROM enterprises e WHERE e.owner_id=%s
                         AND e.city_id=a.city_id AND e.sold_at IS NULL))
         ORDER BY a.starts_at DESC,a.id DESC LIMIT 100""",
         (str(player["id"]),player["id"])).fetchall()
    return 200,{"items":[{"id":r[0],"title":r[1],"body":r[2],"level":r[3],
         "city_id":r[4],"starts_at":r[5].isoformat(),"ends_at":r[6].isoformat()}
         for r in rows]}
