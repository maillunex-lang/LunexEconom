"""Bounded, sanitized admin audit downloads, with a tiny WSGI serializer adapter.

The game's legacy WSGI entrypoint always JSON-serializes handler payloads.
Installation decorates that one serializer only for a typed Download response;
ordinary game/admin responses delegate unchanged. No game_server source edit.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, timedelta
from http import HTTPStatus

from . import admin
from .admin_server import guard

_FIELDS=("id","actor","role","action","target_account_id","ip","created_at")
_EMAIL=re.compile(r"(?i)[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")
_SECRET=re.compile(r"(?i)password|passwd|token|secret|api[_-]?key|bearer|authorization|hash|email")


class Download:
    def __init__(self, raw, kind):
        self.raw=raw
        self.content_type=("text/csv; charset=utf-8" if kind=="csv"
                           else "application/json; charset=utf-8")
        self.filename="lunex-audit." + kind


def install_serializer():
    from server import game_server
    old=game_server._send
    if getattr(old,"_a3_download",False):
        return

    def send(start_response,status,payload):
        if not isinstance(payload,Download):
            return old(start_response,status,payload)
        raw=payload.raw
        start_response(f"{status} {HTTPStatus(status).phrase}",[
            ("Content-Type",payload.content_type),
            ("Content-Disposition",f'attachment; filename="{payload.filename}"'),
            ("Content-Length",str(len(raw))),
            ("Cache-Control","no-store"),
            ("X-Content-Type-Options","nosniff"),
        ])
        return [raw]
    send._a3_download=True
    game_server._send=send


def _date(value):
    if value is None:
        return None
    if not isinstance(value,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",value):
        raise ValueError("invalid_date")
    return date.fromisoformat(value)


def _safe(value):
    if value is None:
        return ""
    text=str(value)
    text=_EMAIL.sub("[скрыто]",text)
    text=_SECRET.sub("[скрыто]",text)
    return text[:200]


def _csv_safe(value):
    value=_safe(value)
    if value and value.lstrip(" \t\r\n").startswith(("=","+","-","@")):
        return "'" + value
    return value


def export(body,ctx):
    actor,err=guard(ctx,{"owner","admin"})
    if err:
        return err
    try:
        fmt=admin._query(ctx,"format","csv")
        if fmt not in ("csv","json"):
            raise ValueError("invalid_format")
        start=_date(admin._query(ctx,"from"))
        end=_date(admin._query(ctx,"to"))
        if start is not None and end is not None and end<start:
            raise ValueError("invalid_date_range")
        action=admin._query(ctx,"action")
        by=admin._query(ctx,"actor")
        if (action is not None and (not 1<=len(action)<=100 or "\x00" in action)
            or by is not None and (not 1<=len(by)<=100 or "\x00" in by)):
            raise ValueError("invalid_filter")
    except (TypeError,ValueError) as exc:
        return 400,{"error":str(exc),"message":"Проверьте фильтры экспорта."}
    clauses=[]
    args=[]
    if start is not None:
        clauses.append("created_at >= %s")
        args.append(start)
    if end is not None:
        clauses.append("created_at < %s")
        args.append(end+timedelta(days=1))
    if action is not None:
        clauses.append("action=%s")
        args.append(action)
    if by is not None:
        clauses.append("actor=%s")
        args.append(by)
    where=" WHERE "+" AND ".join(clauses) if clauses else ""
    rows=ctx["conn"].execute("""SELECT id,actor,actor_role,action,target_account_id,ip,created_at
            FROM audit""" + where + " ORDER BY id DESC LIMIT %s", (*args,10000)).fetchall()
    clean=[{"id":int(r[0]),"actor":_safe(r[1]),"role":_safe(r[2]),
            "action":_safe(r[3]),"target_account_id":r[4],
            "ip":_safe(r[5]),"created_at":r[6].isoformat()} for r in rows]
    if fmt=="json":
        raw=json.dumps({"count":len(clean),"items":clean},ensure_ascii=False,separators=(",",":")).encode()
    else:
        output=io.StringIO(newline="")
        writer=csv.writer(output,lineterminator="\r\n")
        writer.writerow(_FIELDS)
        for item in clean:
            writer.writerow([_csv_safe(item[k]) for k in _FIELDS])
        raw=("\ufeff"+output.getvalue()).encode("utf-8")
    return 200,Download(raw,fmt)
