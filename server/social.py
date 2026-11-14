"""Alliances, joint projects, messages, moderation, achievements and alliance ranking.

Shared by SQLite and PostgreSQL. Every function runs inside the caller's transaction.
Money moves only through ``economy.post`` (entries sum to 0). The alliance treasury
account is ``alliance:<id>``; pledged project money sits on ``project:<id>``; the
company that owns joint buildings is the pseudo-owner ``alliance:<id>`` (wallet
``player:alliance:<id>``) so the existing monthly step, taxes and ``building_ops``
apply unchanged. See docs/ALLIANCES.md.
"""
import json
import re
import threading
import time
import unicodedata
import uuid

import economy
import production
import soc_build


MAX_MEMBERS = 8
NAME_MIN, NAME_MAX = 3, 24
CREATE_FEE = 50_000
MIN_TRANSFER = 1_000
MAX_TRANSFER = 100_000_000
MAX_PROJECTS = 3
MAX_OPEN_INVITES = 20
MSG_MAX = 300
MSG_KEEP = 50
MSG_PER_MINUTE = 12
ACTION_PER_MINUTE = 40
REPORT_PER_HOUR = 5
IP_PER_MINUTE = 120
REPORT_MIN, REPORT_MAX = 3, 200
USER_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_]{3,24}$")
_ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u00ad"), None)

ACHIEVEMENTS = (
    ("first_building", "Первое здание", "Построить или владеть зданием"),
    ("first_profit", "Первая прибыль", "Месяц с положительной прибылью"),
    ("steady_quarter", "Квартал без долгов", "Три месяца подряд без просрочки и долгов"),
    ("first_contract", "Первый контракт", "Заключить контракт на поставку"),
    ("alliance_member", "В альянсе", "Состоять в альянсе"),
    ("election_win", "Победа на выборах", "Стать мэром"),
    ("exchange_deal", "Сделка на бирже", "Исполненная заявка"),
)

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS soc_alliances(id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, leader TEXT NOT NULL, status TEXT NOT NULL, created_month BIGINT NOT NULL, created BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS soc_members(alliance_id TEXT NOT NULL, owner TEXT NOT NULL, role TEXT NOT NULL, joined_month BIGINT NOT NULL, joined BIGINT NOT NULL, PRIMARY KEY(alliance_id, owner))",
    "CREATE TABLE IF NOT EXISTS soc_membership(owner TEXT PRIMARY KEY, alliance_id TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS soc_invites(id TEXT PRIMARY KEY, alliance_id TEXT NOT NULL, from_owner TEXT NOT NULL, to_owner TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, created BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS soc_projects(id TEXT PRIMARY KEY, alliance_id TEXT NOT NULL, kind TEXT NOT NULL, x INTEGER NOT NULL, y INTEGER NOT NULL, cost BIGINT NOT NULL, pledged BIGINT NOT NULL, status TEXT NOT NULL, object_id TEXT NOT NULL, created_month BIGINT NOT NULL, started_month BIGINT NOT NULL, created BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS soc_pledges(project_id TEXT NOT NULL, owner TEXT NOT NULL, amount BIGINT NOT NULL, PRIMARY KEY(project_id, owner))",
    "CREATE TABLE IF NOT EXISTS soc_shares(project_id TEXT NOT NULL, owner TEXT NOT NULL, amount BIGINT NOT NULL, PRIMARY KEY(project_id, owner))",
    "CREATE TABLE IF NOT EXISTS soc_payouts(alliance_id TEXT NOT NULL, month_index BIGINT NOT NULL, profit BIGINT NOT NULL, paid BIGINT NOT NULL, PRIMARY KEY(alliance_id, month_index))",
    "CREATE TABLE IF NOT EXISTS soc_messages(id BIGINT PRIMARY KEY, channel TEXT NOT NULL, sender TEXT NOT NULL, body TEXT NOT NULL, created BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS soc_inbox(owner TEXT NOT NULL, message_id BIGINT NOT NULL, PRIMARY KEY(owner, message_id))",
    "CREATE TABLE IF NOT EXISTS soc_blocks(owner TEXT NOT NULL, blocked TEXT NOT NULL, created BIGINT NOT NULL, PRIMARY KEY(owner, blocked))",
    "CREATE TABLE IF NOT EXISTS soc_reports(id TEXT PRIMARY KEY, reporter TEXT NOT NULL, target TEXT NOT NULL, reason TEXT NOT NULL, created BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS soc_audit(id TEXT PRIMARY KEY, alliance_id TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, amount BIGINT NOT NULL, detail TEXT NOT NULL, month_index BIGINT NOT NULL, created BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS soc_achievements(owner TEXT NOT NULL, code TEXT NOT NULL, earned_month BIGINT NOT NULL, earned BIGINT NOT NULL, PRIMARY KEY(owner, code))",
    "CREATE TABLE IF NOT EXISTS soc_orders(id TEXT PRIMARY KEY, owner TEXT NOT NULL, product TEXT NOT NULL, side TEXT NOT NULL, qty BIGINT NOT NULL, qty_left BIGINT NOT NULL, price BIGINT NOT NULL, status TEXT NOT NULL, created BIGINT NOT NULL, seq BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS soc_fills(id TEXT PRIMARY KEY, buy_id TEXT NOT NULL, sell_id TEXT NOT NULL, buyer TEXT NOT NULL, seller TEXT NOT NULL, product TEXT NOT NULL, qty BIGINT NOT NULL, price BIGINT NOT NULL, fee BIGINT NOT NULL, created BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS soc_seq(name TEXT PRIMARY KEY, value BIGINT NOT NULL)",
)

_buckets = {}
_limit_lock = threading.Lock()


def ensure(db, ph):
    for statement in SCHEMA:
        db.execute(statement.replace("%s", ph) if False else statement)


def reset_limits():
    with _limit_lock:
        _buckets.clear()


def allow(key, limit, window, now=None):
    """In-process fixed window. The window resets when the clock crosses its edge."""
    now = int(time.time() if now is None else now)
    slot = now // int(window)
    with _limit_lock:
        prev = _buckets.get(key)
        if prev is None or prev[0] != slot:
            _buckets[key] = [slot, 1]
            count = 1
        else:
            prev[1] += 1
            count = prev[1]
        if len(_buckets) > 4000:
            for stale in [k for k, v in _buckets.items() if v[0] != slot][:1000]:
                _buckets.pop(stale, None)
        return count <= int(limit)


def guarded(owner, client, kind):
    now = time.time()
    if client and not allow("ip:" + client, IP_PER_MINUTE, 60, now):
        return False
    if kind == "message":
        return allow("msg:" + owner, MSG_PER_MINUTE, 60, now)
    if kind == "report":
        return allow("rep:" + owner, REPORT_PER_HOUR, 3600, now)
    return allow("act:" + owner, ACTION_PER_MINUTE, 60, now)


def normalize_name(raw):
    """Alliance display name. NFKC, no zero-width, casefold key is separate."""
    if type(raw) is not str:
        return None
    text = unicodedata.normalize("NFKC", raw).translate(_ZW).strip()
    text = " ".join(text.split())
    if not NAME_MIN <= len(text) <= NAME_MAX:
        return None
    if any(unicodedata.category(ch).startswith("C") for ch in text):
        return None
    if not any(ch.isalpha() for ch in text):
        return None
    if not all(ch.isalpha() or ch.isdigit() or ch in " -" for ch in text):
        return None
    return text


def name_key(text):
    cleaned = unicodedata.normalize("NFKC", text).translate(_ZW)
    return " ".join(cleaned.split()).casefold()


def _q(sql, ph):
    return sql.replace("%s", ph)


def _human(owner):
    return type(owner) is str and bool(owner) and owner not in economy.RESERVED_OWNERS and ":" not in owner and USER_RE.fullmatch(owner) is not None


def _one(db, ph, sql, params=()):
    return db.execute(_q(sql, ph), params).fetchone()


def _all(db, ph, sql, params=()):
    return db.execute(_q(sql, ph), params).fetchall()


def next_id(db, ph, name):
    db.execute(_q("INSERT INTO soc_seq(name,value) VALUES(%s,0) ON CONFLICT(name) DO NOTHING", ph), (name,))
    db.execute(_q("UPDATE soc_seq SET value=value+1 WHERE name=%s", ph), (name,))
    return int(_one(db, ph, "SELECT value FROM soc_seq WHERE name=%s", (name,))[0])


def treasury_account(alliance_id):
    return "alliance:" + alliance_id


def project_account(project_id):
    return "project:" + project_id


def alliance_owner(alliance_id):
    """Pseudo-owner of joint buildings. Wallet is player:alliance:<id>, not the treasury."""
    return "alliance:" + alliance_id


def _ensure_account(db, ph, account):
    db.execute(_q("INSERT INTO wallets(account,balance) VALUES(%s,0) ON CONFLICT(account) DO NOTHING", ph), (account,))


def account_balance(db, ph, account):
    row = _one(db, ph, "SELECT balance FROM wallets WHERE account=%s", (account,))
    return int(row[0]) if row else 0


def _move(db, ph, src, dst, amount, kind, memo, now):
    if type(amount) is not int or amount <= 0:
        return False
    if account_balance(db, ph, src) < amount:
        return False
    _ensure_account(db, ph, dst)
    economy.post(db, ph, kind, memo, [(src, -int(amount)), (dst, int(amount))], now)
    return True


def _must_move(db, ph, src, dst, amount, kind, memo, now):
    if amount == 0:
        return
    if not _move(db, ph, src, dst, amount, kind, memo, now):
        raise RuntimeError("ledger move failed: %s -> %s %s" % (src, dst, amount))


def _membership(db, ph, owner):
    row = _one(db, ph, "SELECT alliance_id FROM soc_membership WHERE owner=%s", (owner,))
    return row[0] if row else None


def _role(db, ph, alliance_id, owner):
    row = _one(db, ph, "SELECT role FROM soc_members WHERE alliance_id=%s AND owner=%s", (alliance_id, owner))
    return row[0] if row else None


def _alliance(db, ph, alliance_id):
    return _one(db, ph, "SELECT id,name,leader,status FROM soc_alliances WHERE id=%s", (alliance_id,))


def _member_count(db, ph, alliance_id):
    return int(_one(db, ph, "SELECT COUNT(*) FROM soc_members WHERE alliance_id=%s", (alliance_id,))[0])


def _members(db, ph, alliance_id):
    return _all(db, ph, "SELECT owner,role FROM soc_members WHERE alliance_id=%s ORDER BY CASE role WHEN 'leader' THEN 0 ELSE 1 END, joined, owner", (alliance_id,))


def _blocked(db, ph, owner, other):
    """True when ``owner`` has blocked ``other`` (owner does not want contact from other)."""
    return _one(db, ph, "SELECT 1 FROM soc_blocks WHERE owner=%s AND blocked=%s", (owner, other)) is not None


def _audit(db, ph, alliance_id, actor, action, amount, detail, month, now):
    db.execute(_q("INSERT INTO soc_audit(id,alliance_id,actor,action,amount,detail,month_index,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", ph),
               (uuid.uuid4().hex, alliance_id, actor, action, int(amount), detail[:200], int(month), int(now)))


def _notify(db, ph, owner, body, now):
    mid = next_id(db, ph, "message")
    channel = "system:" + owner
    db.execute(_q("INSERT INTO soc_messages(id,channel,sender,body,created) VALUES(%s,%s,'system',%s,%s)", ph),
               (mid, channel, body[:MSG_MAX], int(now)))
    db.execute(_q("INSERT INTO soc_inbox(owner,message_id) VALUES(%s,%s)", ph), (owner, mid))
    return mid


def _notify_members(db, ph, alliance_id, body, now):
    for owner, _role_name in _members(db, ph, alliance_id):
        _notify(db, ph, owner, body, now)


def _public_alliance(row, members):
    ident, name, leader, status = row
    return {"id": ident, "name": name, "leader": leader, "status": status, "members": members}


def _money(amount):
    return type(amount) is int and MIN_TRANSFER <= amount <= MAX_TRANSFER


# ---- alliances ---------------------------------------------------------------

def create_alliance(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    name = normalize_name(payload.get("name"))
    if name is None:
        return 400, {"error": "invalid_name"}
    key = name_key(name)
    if _membership(db, ph, owner):
        return 409, {"error": "already_in_alliance"}
    if _one(db, ph, "SELECT 1 FROM soc_alliances WHERE name_key=%s", (key,)):
        return 409, {"error": "name_taken"}
    economy.ensure_wallet(db, ph, owner, now)
    if (economy.balance(db, ph, owner) or 0) < CREATE_FEE:
        return 402, {"error": "insufficient_funds", "cost": CREATE_FEE, "balance": economy.balance(db, ph, owner) or 0}
    aid = uuid.uuid4().hex
    db.execute(_q("INSERT INTO soc_alliances(id,name,name_key,leader,status,created_month,created) VALUES(%s,%s,%s,%s,'active',%s,%s)", ph),
               (aid, name, key, owner, int(month), int(now)))
    db.execute(_q("INSERT INTO soc_membership(owner,alliance_id) VALUES(%s,%s)", ph), (owner, aid))
    db.execute(_q("INSERT INTO soc_members(alliance_id,owner,role,joined_month,joined) VALUES(%s,%s,'leader',%s,%s)", ph),
               (aid, owner, int(month), int(now)))
    if not _move(db, ph, economy.player_account(owner), treasury_account(aid), CREATE_FEE, "alliance_create", "Взнос при создании альянса", now):
        raise RuntimeError("create fee was not charged")
    _audit(db, ph, aid, owner, "create", CREATE_FEE, name, month, now)
    _notify(db, ph, owner, "Создан альянс «%s»" % name, now)
    return 201, {"ok": True, "alliance": _public_alliance((aid, name, owner, "active"), 1),
                 "balance": economy.balance(db, ph, owner), "treasury": CREATE_FEE}


def _active(db, ph, alliance_id):
    row = _alliance(db, ph, alliance_id)
    if row is None or row[3] != "active":
        return None
    return row


def apply_alliance(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    aid = payload.get("alliance_id")
    if type(aid) is not str or not 8 <= len(aid) <= 64:
        return 400, {"error": "invalid_alliance"}
    row = _active(db, ph, aid)
    if row is None:
        return 404, {"error": "not_found"}
    if _membership(db, ph, owner):
        return 409, {"error": "already_in_alliance"}
    if _member_count(db, ph, aid) >= MAX_MEMBERS:
        return 409, {"error": "alliance_full"}
    if _blocked(db, ph, row[2], owner):
        return 403, {"error": "blocked"}
    if _one(db, ph, "SELECT 1 FROM soc_invites WHERE alliance_id=%s AND to_owner=%s AND kind='apply' AND status='open'", (aid, owner)):
        return 409, {"error": "invite_exists"}
    if int(_one(db, ph, "SELECT COUNT(*) FROM soc_invites WHERE alliance_id=%s AND status='open'", (aid,))[0]) >= MAX_OPEN_INVITES:
        return 409, {"error": "too_many_invites"}
    iid = uuid.uuid4().hex
    db.execute(_q("INSERT INTO soc_invites(id,alliance_id,from_owner,to_owner,kind,status,created) VALUES(%s,%s,%s,%s,'apply','open',%s)", ph),
               (iid, aid, owner, owner, int(now)))
    _notify(db, ph, row[2], "Заявка в «%s» от %s" % (row[1], owner), now)
    return 201, {"ok": True, "invite_id": iid, "alliance_id": aid, "status": "open", "month": month}


def invite_member(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    target = payload.get("name")
    if type(target) is not str or USER_RE.fullmatch(target) is None or target == owner:
        return 400, {"error": "invalid_name"}
    aid = _membership(db, ph, owner)
    if not aid or _role(db, ph, aid, owner) != "leader":
        return 403, {"error": "not_leader"}
    row = _active(db, ph, aid)
    if _member_count(db, ph, aid) >= MAX_MEMBERS:
        return 409, {"error": "alliance_full"}
    if _membership(db, ph, target):
        return 409, {"error": "already_in_alliance"}
    if _blocked(db, ph, target, owner):
        return 403, {"error": "blocked"}
    if _one(db, ph, "SELECT 1 FROM soc_invites WHERE alliance_id=%s AND to_owner=%s AND kind='invite' AND status='open'", (aid, target)):
        return 409, {"error": "invite_exists"}
    if int(_one(db, ph, "SELECT COUNT(*) FROM soc_invites WHERE alliance_id=%s AND status='open'", (aid,))[0]) >= MAX_OPEN_INVITES:
        return 409, {"error": "too_many_invites"}
    iid = uuid.uuid4().hex
    db.execute(_q("INSERT INTO soc_invites(id,alliance_id,from_owner,to_owner,kind,status,created) VALUES(%s,%s,%s,%s,'invite','open',%s)", ph),
               (iid, aid, owner, target, int(now)))
    _notify(db, ph, target, "Вас приглашают в альянс «%s»" % row[1], now)
    return 201, {"ok": True, "invite_id": iid, "name": target, "month": month}


def _join(db, ph, joiner, aid, month, now):
    if _membership(db, ph, joiner):
        return 409, {"error": "already_in_alliance"}
    if _member_count(db, ph, aid) >= MAX_MEMBERS:
        return 409, {"error": "alliance_full"}
    row = _active(db, ph, aid)
    if row is None:
        return 409, {"error": "invalid_state"}
    db.execute(_q("INSERT INTO soc_membership(owner,alliance_id) VALUES(%s,%s)", ph), (joiner, aid))
    db.execute(_q("INSERT INTO soc_members(alliance_id,owner,role,joined_month,joined) VALUES(%s,%s,'member',%s,%s)", ph),
               (aid, joiner, int(month), int(now)))
    _audit(db, ph, aid, joiner, "join", 0, joiner, month, now)
    _notify(db, ph, joiner, "Вас приняли в альянс «%s»" % row[1], now)
    _notify(db, ph, row[2], "%s вступил в «%s»" % (joiner, row[1]), now)
    return 201, {"ok": True, "alliance_id": aid, "name": joiner, "members": _member_count(db, ph, aid)}


def accept_invite(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    iid = payload.get("invite_id")
    if type(iid) is not str or not 8 <= len(iid) <= 64:
        return 400, {"error": "invalid_invite"}
    row = _one(db, ph, "SELECT alliance_id,from_owner,to_owner,kind,status FROM soc_invites WHERE id=%s", (iid,))
    if row is None:
        return 404, {"error": "not_found"}
    aid, _src, target, kind, status = row
    if status != "open":
        return 409, {"error": "invalid_state"}
    if kind == "invite":
        if owner != target:
            return 403, {"error": "not_recipient"}
        joiner = owner
    elif kind == "apply":
        if _role(db, ph, aid, owner) != "leader":
            return 403, {"error": "not_leader"}
        joiner = target
        if _blocked(db, ph, joiner, owner):
            return 403, {"error": "blocked"}
    else:
        return 400, {"error": "invalid_invite"}
    status_code, body = _join(db, ph, joiner, aid, month, now)
    if status_code != 201:
        return status_code, body
    db.execute(_q("UPDATE soc_invites SET status='accepted' WHERE id=%s", ph), (iid,))
    body["invite_id"] = iid
    return 201, body


def decline_invite(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    iid = payload.get("invite_id")
    if type(iid) is not str or not 8 <= len(iid) <= 64:
        return 400, {"error": "invalid_invite"}
    row = _one(db, ph, "SELECT alliance_id,to_owner,kind,status FROM soc_invites WHERE id=%s", (iid,))
    if row is None:
        return 404, {"error": "not_found"}
    aid, target, kind, status = row
    if status != "open":
        return 409, {"error": "invalid_state"}
    if kind == "invite" and owner != target:
        return 403, {"error": "not_recipient"}
    if kind == "apply" and owner != target and _role(db, ph, aid, owner) != "leader":
        return 403, {"error": "not_recipient"}
    db.execute(_q("UPDATE soc_invites SET status='declined' WHERE id=%s", ph), (iid,))
    return 201, {"ok": True, "invite_id": iid, "status": "declined", "month": month}


def _clear_member(db, ph, aid, owner):
    db.execute(_q("DELETE FROM soc_members WHERE alliance_id=%s AND owner=%s", ph), (aid, owner))
    db.execute(_q("DELETE FROM soc_membership WHERE owner=%s AND alliance_id=%s", ph), (owner, aid))


def leave_alliance(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    aid = _membership(db, ph, owner)
    if not aid:
        return 409, {"error": "not_member"}
    if _role(db, ph, aid, owner) == "leader":
        if _member_count(db, ph, aid) > 1:
            return 409, {"error": "leader_must_transfer"}
        return dissolve_alliance(db, ph, owner, payload, month, now)
    _clear_member(db, ph, aid, owner)
    _audit(db, ph, aid, owner, "leave", 0, owner, month, now)
    return 201, {"ok": True, "alliance_id": aid, "status": "left"}


def kick_member(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    target = payload.get("name")
    if type(target) is not str or USER_RE.fullmatch(target) is None:
        return 400, {"error": "invalid_name"}
    aid = _membership(db, ph, owner)
    if not aid or _role(db, ph, aid, owner) != "leader":
        return 403, {"error": "not_leader"}
    if target == owner:
        return 400, {"error": "invalid_name"}
    if _role(db, ph, aid, target) is None:
        return 404, {"error": "not_found"}
    _clear_member(db, ph, aid, target)
    _audit(db, ph, aid, owner, "kick", 0, target, month, now)
    _notify(db, ph, target, "Вас исключили из альянса", now)
    return 201, {"ok": True, "name": target, "alliance_id": aid}


def transfer_leadership(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    target = payload.get("name")
    if type(target) is not str or USER_RE.fullmatch(target) is None or target == owner:
        return 400, {"error": "invalid_name"}
    aid = _membership(db, ph, owner)
    if not aid or _role(db, ph, aid, owner) != "leader":
        return 403, {"error": "not_leader"}
    if _role(db, ph, aid, target) is None:
        return 404, {"error": "not_found"}
    db.execute(_q("UPDATE soc_members SET role='member' WHERE alliance_id=%s AND owner=%s", ph), (aid, owner))
    db.execute(_q("UPDATE soc_members SET role='leader' WHERE alliance_id=%s AND owner=%s", ph), (aid, target))
    db.execute(_q("UPDATE soc_alliances SET leader=%s WHERE id=%s", ph), (target, aid))
    _audit(db, ph, aid, owner, "transfer", 0, target, month, now)
    _notify(db, ph, target, "Вам передали руководство альянсом", now)
    return 201, {"ok": True, "leader": target, "alliance_id": aid}


def contribute(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    amount = payload.get("amount")
    if not _money(amount):
        return 400, {"error": "invalid_amount"}
    aid = _membership(db, ph, owner)
    if not aid:
        return 403, {"error": "not_member"}
    economy.ensure_wallet(db, ph, owner, now)
    if not _move(db, ph, economy.player_account(owner), treasury_account(aid), amount, "alliance_contribute", "Взнос в казну альянса", now):
        return 402, {"error": "insufficient_funds", "cost": amount, "balance": economy.balance(db, ph, owner) or 0}
    _audit(db, ph, aid, owner, "contribute", amount, owner, month, now)
    leader = _one(db, ph, "SELECT leader,name FROM soc_alliances WHERE id=%s", (aid,))
    if leader and leader[0] != owner:
        _notify(db, ph, leader[0], "Взнос %d ₽ от %s" % (amount, owner), now)
    return 201, {"ok": True, "amount": amount, "treasury": account_balance(db, ph, treasury_account(aid)),
                 "balance": economy.balance(db, ph, owner)}


def withdraw(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    amount = payload.get("amount")
    if not _money(amount):
        return 400, {"error": "invalid_amount"}
    aid = _membership(db, ph, owner)
    if not aid or _role(db, ph, aid, owner) != "leader":
        return 403, {"error": "not_leader"}
    treasury = treasury_account(aid)
    if account_balance(db, ph, treasury) < amount:
        return 402, {"error": "insufficient_funds", "cost": amount, "balance": account_balance(db, ph, treasury)}
    economy.ensure_wallet(db, ph, owner, now)
    if not _move(db, ph, treasury, economy.player_account(owner), amount, "alliance_withdraw", "Вывод из казны альянса", now):
        return 402, {"error": "insufficient_funds", "cost": amount, "balance": account_balance(db, ph, treasury)}
    _audit(db, ph, aid, owner, "withdraw", amount, owner, month, now)
    return 201, {"ok": True, "amount": amount, "treasury": account_balance(db, ph, treasury),
                 "balance": economy.balance(db, ph, owner)}


def _refund_pledges(db, ph, project_id, now):
    account = project_account(project_id)
    rows = _all(db, ph, "SELECT owner,amount FROM soc_pledges WHERE project_id=%s ORDER BY owner", (project_id,))
    for owner, amount in rows:
        amount = int(amount)
        if amount:
            _must_move(db, ph, account, economy.player_account(owner), amount, "project_refund", "Возврат вклада в проект", now)
    db.execute(_q("DELETE FROM soc_pledges WHERE project_id=%s", ph), (project_id,))


def _split_treasury(db, ph, aid, now):
    """Equal split. The remainder of the division goes to the leader."""
    members = [owner for owner, _role_name in _members(db, ph, aid)]
    leader = _one(db, ph, "SELECT leader FROM soc_alliances WHERE id=%s", (aid,))[0]
    treasury = treasury_account(aid)
    total = account_balance(db, ph, treasury)
    if total <= 0 or not members:
        return []
    base, rem = divmod(total, len(members))
    cuts = []
    entries = [(treasury, -total)]
    for owner in members:
        cut = base + (rem if owner == leader else 0)
        if cut:
            entries.append((economy.player_account(owner), cut))
            cuts.append({"name": owner, "amount": cut})
    economy.post(db, ph, "alliance_dissolve", "Раздел казны альянса", entries, now)
    return cuts


def dissolve_alliance(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    aid = _membership(db, ph, owner)
    if not aid or _role(db, ph, aid, owner) != "leader":
        return 403, {"error": "not_leader"}
    for pid, status in _all(db, ph, "SELECT id,status FROM soc_projects WHERE alliance_id=%s AND status='funding'", (aid,)):
        _refund_pledges(db, ph, pid, now)
        db.execute(_q("UPDATE soc_projects SET status='cancelled', pledged=0 WHERE id=%s", ph), (pid,))
    company = alliance_owner(aid)
    for object_id, in _all(db, ph, "SELECT id FROM buildings WHERE owner=%s", (company,)):
        production.sell_building(db, ph, company, object_id, now)
    cash = economy.balance(db, ph, company) or 0
    if cash:
        _must_move(db, ph, economy.player_account(company), treasury_account(aid), cash, "alliance_sweep", "Остаток компании альянса в казну", now)
    db.execute(_q("UPDATE soc_projects SET status='closed' WHERE alliance_id=%s AND status='active'", ph), (aid,))
    cuts = _split_treasury(db, ph, aid, now)
    names = [m for m, _r in _members(db, ph, aid)]
    for member in names:
        _clear_member(db, ph, aid, member)
        _notify(db, ph, member, "Альянс распущен, казна разделена", now)
    db.execute(_q("UPDATE soc_invites SET status='cancelled' WHERE alliance_id=%s AND status='open'", ph), (aid,))
    db.execute(_q("UPDATE soc_alliances SET status='dissolved' WHERE id=%s", ph), (aid,))
    _audit(db, ph, aid, owner, "dissolve", 0, "dissolved", month, now)
    return 201, {"ok": True, "alliance_id": aid, "status": "dissolved", "split": cuts,
                 "balance": economy.balance(db, ph, owner)}


# ---- projects ----------------------------------------------------------------

def _project_public(row, pledges):
    ident, aid, kind, x, y, cost, pledged, status, object_id, created_month, started_month = row
    return {"id": ident, "alliance_id": aid, "kind": kind, "x": int(x), "y": int(y), "cost": int(cost),
            "pledged": int(pledged), "remaining": max(0, int(cost) - int(pledged)), "status": status,
            "object_id": object_id, "created_month": int(created_month), "started_month": int(started_month),
            "pledges": [{"name": o, "amount": int(a)} for o, a in pledges]}


def open_project(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    aid = _membership(db, ph, owner)
    if not aid or _role(db, ph, aid, owner) != "leader":
        return 403, {"error": "not_leader"}
    kind, x, y = payload.get("kind"), payload.get("x"), payload.get("y")
    if kind not in soc_build.KINDS:
        return 400, {"error": "invalid_build"}
    open_n = int(_one(db, ph, "SELECT COUNT(*) FROM soc_projects WHERE alliance_id=%s AND status IN ('funding','active')", (aid,))[0])
    if open_n >= MAX_PROJECTS:
        return 409, {"error": "too_many_projects"}
    error, planned = soc_build.plan(db, ph, kind, x, y)
    if error:
        return 409, {"error": error}
    pid = uuid.uuid4().hex
    db.execute(_q("INSERT INTO soc_projects(id,alliance_id,kind,x,y,cost,pledged,status,object_id,created_month,started_month,created) "
                  "VALUES(%s,%s,%s,%s,%s,%s,0,'funding','',%s,-1,%s)", ph),
               (pid, aid, kind, int(x), int(y), int(planned["cost"]), int(month), int(now)))
    _audit(db, ph, aid, owner, "project", int(planned["cost"]), "%s %s,%s" % (kind, x, y), month, now)
    return 201, {"ok": True, "project": _project_public((pid, aid, kind, x, y, planned["cost"], 0, "funding", "", month, -1), []),
                 "road_cells": len(planned["new_roads"])}


def _cuts(total, parts):
    """Split ``total`` by weights. Each cut is <= its weight. Sum of cuts == min(total, sum weights)."""
    weights = [(k, int(w)) for k, w in parts if int(w) > 0]
    base = sum(w for _, w in weights)
    if total <= 0 or base <= 0:
        return []
    total = min(int(total), base)
    cuts = {k: total * w // base for k, w in weights}
    rem = total - sum(cuts.values())
    for k, w in weights:
        if rem <= 0:
            break
        add = min(w - cuts[k], rem)
        cuts[k] += add
        rem -= add
    return [(k, cuts[k]) for k, _w in weights if cuts[k]]


def _maybe_start(db, ph, project_id, month, now, clk):
    row = _one(db, ph, "SELECT alliance_id,kind,x,y,cost,pledged,status FROM soc_projects WHERE id=%s", (project_id,))
    aid, kind, x, y, cost, pledged, status = row
    if status != "funding":
        return {"started": False}
    error, planned = soc_build.plan(db, ph, kind, int(x), int(y))
    if error:
        return {"started": False, "error": error}
    required = int(planned["cost"])
    pledged = int(pledged)
    if pledged < required:
        db.execute(_q("UPDATE soc_projects SET cost=%s WHERE id=%s", ph), (required, project_id))
        return {"started": False, "cost": required}
    if pledged > required:
        parts = _all(db, ph, "SELECT owner,amount FROM soc_pledges WHERE project_id=%s ORDER BY owner", (project_id,))
        for who, cut in _cuts(pledged - required, parts):
            _must_move(db, ph, project_account(project_id), economy.player_account(who), cut, "project_refund", "Лишний вклад возвращён", now)
            db.execute(_q("UPDATE soc_pledges SET amount=amount-%s WHERE project_id=%s AND owner=%s", ph), (cut, project_id, who))
        pledged = required
        db.execute(_q("UPDATE soc_projects SET pledged=%s, cost=%s WHERE id=%s", ph), (pledged, required, project_id))
    company = alliance_owner(aid)
    wallet = economy.player_account(company)
    _ensure_account(db, ph, wallet)   # existing row => charge_build will not grant start capital
    if not _move(db, ph, project_account(project_id), wallet, required, "project_fund", "Финансирование стройки альянса", now):
        return {"started": False, "error": "insufficient_funds"}
    status_code, body = soc_build.place(db, ph, company, kind, int(x), int(y), planned, now, clk)
    if status_code != 201:
        _must_move(db, ph, wallet, project_account(project_id), required, "project_refund", "Стройка не началась", now)
        return {"started": False, "error": body.get("error", "invalid_build")}
    for who, amount in _all(db, ph, "SELECT owner,amount FROM soc_pledges WHERE project_id=%s AND amount>0", (project_id,)):
        db.execute(_q("INSERT INTO soc_shares(project_id,owner,amount) VALUES(%s,%s,%s)", ph), (project_id, who, int(amount)))
    db.execute(_q("UPDATE soc_projects SET status='active', object_id=%s, started_month=%s, cost=%s, pledged=%s WHERE id=%s", ph),
               (body["object_id"], int(month), required, required, project_id))
    _notify_members(db, ph, aid, "Проект %s запущен" % kind, now)
    return {"started": True, "object_id": body["object_id"], "cost": body["cost"], "owner": company}


def pledge_project(db, ph, owner, payload, month, now, clk=None):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    pid = payload.get("project_id")
    amount = payload.get("amount")
    if type(pid) is not str or not 8 <= len(pid) <= 64:
        return 400, {"error": "invalid_project"}
    if type(amount) is not int or amount < 1 or amount > MAX_TRANSFER:
        return 400, {"error": "invalid_amount"}
    row = _one(db, ph, "SELECT alliance_id,cost,pledged,status FROM soc_projects WHERE id=%s", (pid,))
    if row is None:
        return 404, {"error": "not_found"}
    aid, cost, pledged, status = row
    if _role(db, ph, aid, owner) is None:
        return 403, {"error": "not_member"}
    if status != "funding":
        return 409, {"error": "invalid_state"}
    room = int(cost) - int(pledged)
    if amount > room:
        return 400, {"error": "above_remaining", "remaining": room}
    economy.ensure_wallet(db, ph, owner, now)
    if not _move(db, ph, economy.player_account(owner), project_account(pid), amount, "project_pledge", "Вклад в проект альянса", now):
        return 402, {"error": "insufficient_funds", "cost": amount, "balance": economy.balance(db, ph, owner) or 0}
    db.execute(_q("INSERT INTO soc_pledges(project_id,owner,amount) VALUES(%s,%s,%s) ON CONFLICT(project_id,owner) DO UPDATE SET amount=soc_pledges.amount+%s", ph),
               (pid, owner, amount, amount))
    db.execute(_q("UPDATE soc_projects SET pledged=pledged+%s WHERE id=%s", ph), (amount, pid))
    _audit(db, ph, aid, owner, "pledge", amount, pid[:8], month, now)
    leader = _one(db, ph, "SELECT leader FROM soc_alliances WHERE id=%s", (aid,))
    if leader and leader[0] != owner:
        _notify(db, ph, leader[0], "Вклад в проект %d ₽ от %s" % (amount, owner), now)
    started = _maybe_start(db, ph, pid, month, now, clk) if int(pledged) + amount >= int(cost) else {"started": False}
    fresh = _one(db, ph, "SELECT id,alliance_id,kind,x,y,cost,pledged,status,object_id,created_month,started_month FROM soc_projects WHERE id=%s", (pid,))
    pledges = _all(db, ph, "SELECT owner,amount FROM soc_pledges WHERE project_id=%s ORDER BY owner", (pid,))
    return 201, {"ok": True, "project": _project_public(fresh, pledges), "started": started,
                 "balance": economy.balance(db, ph, owner)}


def cancel_project(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    pid = payload.get("project_id")
    if type(pid) is not str or not 8 <= len(pid) <= 64:
        return 400, {"error": "invalid_project"}
    row = _one(db, ph, "SELECT alliance_id,status FROM soc_projects WHERE id=%s", (pid,))
    if row is None:
        return 404, {"error": "not_found"}
    aid, status = row
    if _role(db, ph, aid, owner) != "leader":
        return 403, {"error": "not_leader"}
    if status != "funding":
        return 409, {"error": "invalid_state"}
    _refund_pledges(db, ph, pid, now)
    db.execute(_q("UPDATE soc_projects SET status='cancelled', pledged=0 WHERE id=%s", ph), (pid,))
    _audit(db, ph, aid, owner, "project_cancel", 0, pid[:8], month, now)
    return 201, {"ok": True, "project_id": pid, "status": "cancelled", "balance": economy.balance(db, ph, owner)}


# ---- monthly shares ----------------------------------------------------------

def _share_pool(db, ph, aid):
    rows = _all(db, ph, "SELECT s.owner,s.amount FROM soc_shares s JOIN soc_projects p ON p.id=s.project_id "
                        "WHERE p.alliance_id=%s AND p.status='active'", (aid,))
    pool = {}
    for owner, amount in rows:
        pool[owner] = pool.get(owner, 0) + int(amount)
    return sorted(pool.items())


def distribute_pending(db, ph, clk, now):
    """Pay completed months of alliance companies. Idempotent per alliance and month."""
    aids = [r[0] for r in _all(db, ph, "SELECT DISTINCT alliance_id FROM soc_projects WHERE status='active'")]
    for aid in aids:
        company = alliance_owner(aid)
        alive = _one(db, ph, "SELECT 1 FROM buildings WHERE owner=%s", (company,))
        if alive is None:
            cash = economy.balance(db, ph, company) or 0
            if cash:
                _must_move(db, ph, economy.player_account(company), treasury_account(aid), cash, "alliance_sweep", "Здания альянса закрыты", now)
            db.execute(_q("UPDATE soc_projects SET status='lost' WHERE alliance_id=%s AND status='active'", ph), (aid,))
            continue
        reports = _all(db, ph, "SELECT month_index,profit FROM company_reports WHERE owner=%s ORDER BY month_index", (company,))
        for month_index, profit in reports:
            month_index = int(month_index)
            if _one(db, ph, "SELECT 1 FROM soc_payouts WHERE alliance_id=%s AND month_index=%s", (aid, month_index)):
                continue
            started = _one(db, ph, "SELECT MIN(started_month) FROM soc_projects WHERE alliance_id=%s AND status='active' AND started_month>=0", (aid,))
            if started and started[0] is not None and month_index < int(started[0]):
                db.execute(_q("INSERT INTO soc_payouts(alliance_id,month_index,profit,paid) VALUES(%s,%s,%s,0)", ph),
                           (aid, month_index, int(profit)))
                continue
            tax_row = _one(db, ph, "SELECT paid FROM company_taxes WHERE owner=%s AND month_index=%s", (company, month_index))
            tax_paid = int(tax_row[0]) if tax_row else 0
            want = max(0, int(profit) - tax_paid)
            have = max(0, economy.balance(db, ph, company) or 0)
            distributable = min(want, have)
            paid = 0
            if distributable > 0:
                pool = _share_pool(db, ph, aid)
                total_w = sum(amount for _o, amount in pool)
                entries = [(economy.player_account(company), -distributable)]
                treasury_add = 0
                used = 0
                if total_w <= 0:
                    treasury_add = distributable
                else:
                    for member, weight in pool:
                        cut = distributable * weight // total_w
                        used += cut
                        if cut <= 0:
                            continue
                        if _role(db, ph, aid, member):
                            entries.append((economy.player_account(member), cut))
                        else:
                            treasury_add += cut
                    treasury_add += distributable - used
                if treasury_add:
                    entries.append((treasury_account(aid), treasury_add))
                # merge duplicate accounts (leader who is also a shareholder is already one row)
                merged = {}
                for account, amount in entries:
                    merged[account] = merged.get(account, 0) + amount
                merged = [(a, n) for a, n in merged.items() if n]
                if sum(n for _a, n in merged) != 0 or len({a for a, _n in merged}) != len(merged):
                    raise RuntimeError("alliance dividend is not balanced")
                economy.post(db, ph, "alliance_dividend", "Доли проекта альянса за месяц %d" % month_index, merged, now)
                paid = distributable
            db.execute(_q("INSERT INTO soc_payouts(alliance_id,month_index,profit,paid) VALUES(%s,%s,%s,%s)", ph),
                       (aid, month_index, int(profit), paid))


# ---- messages, blocks, reports ----------------------------------------------

def _clean_text(raw, limit):
    if type(raw) is not str:
        return None
    text = raw.replace("\x00", "").strip()
    if not text or len(text) > limit or "<" in text or ">" in text:
        return None
    return text


def _trim_channel(db, ph, channel):
    rows = _all(db, ph, "SELECT id FROM soc_messages WHERE channel=%s ORDER BY id DESC", (channel,))
    extra = [r[0] for r in rows[MSG_KEEP:]]
    for mid in extra:
        db.execute(_q("DELETE FROM soc_inbox WHERE message_id=%s", ph), (mid,))
        db.execute(_q("DELETE FROM soc_messages WHERE id=%s", ph), (mid,))


def send_message(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    body = _clean_text(payload.get("body"), MSG_MAX)
    if body is None:
        return 400, {"error": "invalid_text"}
    target, alliance = payload.get("to"), payload.get("alliance")
    if type(target) is str and type(alliance) is str:
        return 400, {"error": "invalid_request"}
    if type(target) is str:
        if USER_RE.fullmatch(target) is None or target == owner:
            return 400, {"error": "invalid_name"}
        if _blocked(db, ph, target, owner):
            return 403, {"error": "blocked"}
        channel = "dm:" + "|".join(sorted((owner, target)))
        recipients = (owner, target)
    elif type(alliance) is str and 8 <= len(alliance) <= 64:
        if _role(db, ph, alliance, owner) is None:
            return 403, {"error": "not_member"}
        channel = "alliance:" + alliance
        recipients = tuple(m for m, _r in _members(db, ph, alliance))
    else:
        return 400, {"error": "invalid_request"}
    mid = next_id(db, ph, "message")
    db.execute(_q("INSERT INTO soc_messages(id,channel,sender,body,created) VALUES(%s,%s,%s,%s,%s)", ph),
               (mid, channel, owner, body, int(now)))
    for recipient in recipients:
        db.execute(_q("INSERT INTO soc_inbox(owner,message_id) VALUES(%s,%s)", ph), (recipient, mid))
    _trim_channel(db, ph, channel)
    return 201, {"ok": True, "id": mid, "channel": channel, "month": month}


def read_inbox(db, ph, owner, args):
    raw = args.get("after", "0")
    if type(raw) is not str or not raw.isascii() or not raw.isdigit() or len(raw) > 18:
        return 400, {"error": "invalid_cursor"}
    after = int(raw)
    rows = _all(db, ph, "SELECT m.id,m.sender,m.body,m.created,m.channel FROM soc_messages m "
                        "JOIN soc_inbox i ON i.message_id=m.id WHERE i.owner=%s AND m.id>%s ORDER BY m.id LIMIT 50",
                (owner, after))
    messages = []
    for mid, sender, body, created, channel in rows:
        messages.append({"id": int(mid), "name": "Система" if sender == "system" else sender,
                         "body": body, "created": int(created), "channel": channel})
    return 200, {"ok": True, "messages": messages}


def block_player(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    target = payload.get("name")
    if type(target) is not str or USER_RE.fullmatch(target) is None or target == owner:
        return 400, {"error": "invalid_name"}
    db.execute(_q("INSERT INTO soc_blocks(owner,blocked,created) VALUES(%s,%s,%s) ON CONFLICT(owner,blocked) DO NOTHING", ph),
               (owner, target, int(now)))
    return 201, {"ok": True, "blocked": target, "month": month}


def unblock_player(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    target = payload.get("name")
    if type(target) is not str or USER_RE.fullmatch(target) is None:
        return 400, {"error": "invalid_name"}
    db.execute(_q("DELETE FROM soc_blocks WHERE owner=%s AND blocked=%s", ph), (owner, target))
    return 201, {"ok": True, "name": target, "month": month}


def file_report(db, ph, owner, payload, month, now):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    target = payload.get("name")
    reason = _clean_text(payload.get("reason"), REPORT_MAX)
    if type(target) is not str or USER_RE.fullmatch(target) is None or target == owner:
        return 400, {"error": "invalid_name"}
    if reason is None or len(reason) < REPORT_MIN:
        return 400, {"error": "invalid_text"}
    rid = uuid.uuid4().hex
    db.execute(_q("INSERT INTO soc_reports(id,reporter,target,reason,created) VALUES(%s,%s,%s,%s,%s)", ph),
               (rid, owner, target, reason, int(now)))
    return 201, {"ok": True, "id": rid, "month": month}


# ---- reads -------------------------------------------------------------------

def _projects_of(db, ph, aid):
    rows = _all(db, ph, "SELECT id,alliance_id,kind,x,y,cost,pledged,status,object_id,created_month,started_month "
                        "FROM soc_projects WHERE alliance_id=%s ORDER BY created", (aid,))
    out = []
    for row in rows:
        pledges = _all(db, ph, "SELECT owner,amount FROM soc_pledges WHERE project_id=%s ORDER BY owner", (row[0],))
        if not pledges:
            pledges = _all(db, ph, "SELECT owner,amount FROM soc_shares WHERE project_id=%s ORDER BY owner", (row[0],))
        out.append(_project_public(row, pledges))
    return out


def view_alliance(db, ph, owner, args):
    aid = _membership(db, ph, owner)
    mine = [{"id": i, "alliance_id": a, "kind": k, "name": src} for i, a, src, k in _all(
        db, ph, "SELECT id,alliance_id,from_owner,kind FROM soc_invites WHERE to_owner=%s AND status='open' AND kind='invite'", (owner,))]
    body = {"ok": True, "alliance": None, "role": None, "invites": mine,
            "limits": {"members": MAX_MEMBERS, "create_fee": CREATE_FEE, "min_transfer": MIN_TRANSFER}}
    if not aid:
        return 200, body
    row = _alliance(db, ph, aid)
    roster = [{"name": m, "role": r} for m, r in _members(db, ph, aid)]
    info = _public_alliance(row, len(roster))
    info["treasury"] = account_balance(db, ph, treasury_account(aid))
    info["roster"] = roster
    info["projects"] = _projects_of(db, ph, aid)
    info["audit"] = [{"name": a, "action": action, "amount": int(amount), "detail": detail, "month": int(m), "created": int(c)}
                     for a, action, amount, detail, m, c in _all(
                         db, ph, "SELECT actor,action,amount,detail,month_index,created FROM soc_audit WHERE alliance_id=%s ORDER BY created DESC LIMIT 15",
                         (aid,))]
    incoming = []
    if _role(db, ph, aid, owner) == "leader":
        incoming = [{"id": i, "name": who, "kind": kind} for i, who, kind in _all(
            db, ph, "SELECT id,to_owner,kind FROM soc_invites WHERE alliance_id=%s AND status='open' ORDER BY created", (aid,))]
    body.update({"alliance": info, "role": _role(db, ph, aid, owner), "applications": incoming})
    return 200, body


def list_alliances(db, ph, owner, args):
    raw = args.get("q", "")
    if type(raw) is not str or len(raw) > NAME_MAX:
        return 400, {"error": "invalid_name"}
    key = name_key(normalize_name(raw) or "") if raw.strip() else ""
    # A query that is not a valid full name can still be a fragment of letters.
    if raw.strip() and not key:
        fragment = " ".join(unicodedata.normalize("NFKC", raw).translate(_ZW).split()).casefold()
        if not fragment or any(not (ch.isalpha() or ch.isdigit() or ch in " -") for ch in fragment):
            return 400, {"error": "invalid_name"}
        key = fragment
    if key:
        like = "%" + key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = _all(db, ph, "SELECT id,name,leader FROM soc_alliances WHERE status='active' AND name_key LIKE %s ESCAPE '\\' ORDER BY name_key LIMIT 20", (like,))
    else:
        rows = _all(db, ph, "SELECT id,name,leader FROM soc_alliances WHERE status='active' ORDER BY created DESC LIMIT 20")
    items = []
    for ident, name, leader in rows:
        items.append({"id": ident, "name": name, "leader": leader, "members": _member_count(db, ph, ident)})
    return 200, {"ok": True, "alliances": items, "viewer": owner}


def achievements_view(db, ph, owner, args):
    if not _human(owner):
        return 403, {"error": "npc_forbidden"}
    month = int(args.get("month") or 0)
    now = int(args.get("now") or 0)
    _evaluate(db, ph, owner, month, now)
    owned = {code: int(when) for code, when in _all(db, ph, "SELECT code,earned_month FROM soc_achievements WHERE owner=%s", (owner,))}
    items = [{"code": code, "title": title, "hint": hint, "earned": code in owned, "month": owned.get(code)}
             for code, title, hint in ACHIEVEMENTS]
    return 200, {"ok": True, "name": owner, "achievements": items}


def _grant(db, ph, owner, code, month, now):
    cur = db.execute(_q("INSERT INTO soc_achievements(owner,code,earned_month,earned) VALUES(%s,%s,%s,%s) ON CONFLICT(owner,code) DO NOTHING", ph),
                     (owner, code, int(month), int(now)))
    if cur.rowcount == 1:
        title = dict((c, t) for c, t, _h in ACHIEVEMENTS).get(code, code)
        _notify(db, ph, owner, "Достижение: %s" % title, now)


def _evaluate(db, ph, owner, month, now):
    if _one(db, ph, "SELECT 1 FROM buildings WHERE owner=%s", (owner,)) or _one(
            db, ph, "SELECT 1 FROM company_reports WHERE owner=%s AND buildings>0", (owner,)):
        _grant(db, ph, owner, "first_building", month, now)
    if _one(db, ph, "SELECT 1 FROM company_reports WHERE owner=%s AND profit>0", (owner,)):
        _grant(db, ph, owner, "first_profit", month, now)
    reports = [int(m) for m, in _all(db, ph, "SELECT month_index FROM company_reports WHERE owner=%s ORDER BY month_index DESC LIMIT 3", (owner,))]
    status = _one(db, ph, "SELECT missed,wages_owed,input_owed,maint_owed FROM company_status WHERE owner=%s", (owner,))
    tax = _one(db, ph, "SELECT tax_owed FROM company_tax_state WHERE owner=%s", (owner,))
    arrears = 0
    missed = 0
    if status:
        missed = int(status[0])
        arrears = int(status[1]) + int(status[2]) + int(status[3])
    if tax:
        arrears += int(tax[0])
    if len(reports) == 3 and reports[0] == reports[1] + 1 and reports[1] == reports[2] + 1 and missed == 0 and arrears == 0:
        _grant(db, ph, owner, "steady_quarter", month, now)
    if _one(db, ph, "SELECT 1 FROM trade_contracts WHERE supplier=%s OR buyer=%s", (owner, owner)):
        _grant(db, ph, owner, "first_contract", month, now)
    if _membership(db, ph, owner):
        _grant(db, ph, owner, "alliance_member", month, now)
    if _one(db, ph, "SELECT 1 FROM election_results WHERE winner=%s", (owner,)) or _one(
            db, ph, "SELECT 1 FROM city_state WHERE mayor=%s", (owner,)) or _one(
            db, ph, "SELECT 1 FROM mayor_terms WHERE mayor=%s", (owner,)):
        _grant(db, ph, owner, "election_win", month, now)
    if _one(db, ph, "SELECT 1 FROM soc_fills WHERE buyer=%s OR seller=%s", (owner, owner)):
        _grant(db, ph, owner, "exchange_deal", month, now)


def alliance_ranking(db, ph, owner, args):
    mode = args.get("by", "capital")
    if mode not in ("capital", "activity", "members"):
        return 400, {"error": "invalid_sort"}
    month = int(args.get("month") or 0)
    rows = []
    for ident, name, leader in _all(db, ph, "SELECT id,name,leader FROM soc_alliances WHERE status='active'"):
        members = _member_count(db, ph, ident)
        treasury = account_balance(db, ph, treasury_account(ident))
        buildings = 0
        for kind, in _all(db, ph, "SELECT kind FROM buildings WHERE owner=%s", (alliance_owner(ident),)):
            buildings += int(economy.BUILD_COST.get(kind, 0))
        activity = int(_one(db, ph, "SELECT COALESCE(SUM(amount),0) FROM soc_audit WHERE alliance_id=%s AND action IN ('create','contribute','pledge') AND month_index>=%s",
                            (ident, month - 12))[0])
        rows.append({"id": ident, "name": name, "leader": leader, "members": members,
                     "treasury": treasury, "buildings": buildings, "capital": treasury + buildings, "activity": activity})
    rows.sort(key=lambda item: (-item[mode], item["name"].casefold(), item["id"]))
    top = []
    mine = None
    for index, item in enumerate(rows, start=1):
        item = dict(item)
        item["rank"] = index
        if index <= 20:
            top.append(item)
        if _membership(db, ph, owner) == item["id"]:
            mine = {"rank": index, "name": item["name"], "capital": item["capital"]}
    return 200, {"ok": True, "by": mode, "top": top, "me": mine, "total": len(rows)}


import charts
import exchange

POST = {
    "/soc/alliance/create": create_alliance,
    "/soc/alliance/apply": apply_alliance,
    "/soc/alliance/invite": invite_member,
    "/soc/alliance/accept": accept_invite,
    "/soc/alliance/decline": decline_invite,
    "/soc/alliance/leave": leave_alliance,
    "/soc/alliance/kick": kick_member,
    "/soc/alliance/transfer": transfer_leadership,
    "/soc/alliance/contribute": contribute,
    "/soc/alliance/withdraw": withdraw,
    "/soc/alliance/dissolve": dissolve_alliance,
    "/soc/project": open_project,
    "/soc/project/pledge": pledge_project,
    "/soc/project/cancel": cancel_project,
    "/soc/message": send_message,
    "/soc/block": block_player,
    "/soc/unblock": unblock_player,
    "/soc/report": file_report,
    "/soc/exchange/order": exchange.place_order,
    "/soc/exchange/cancel": exchange.cancel_order,
}

GET = {
    "/soc/alliance": view_alliance,
    "/soc/alliances": list_alliances,
    "/soc/inbox": read_inbox,
    "/soc/achievements": achievements_view,
    "/soc/alliance-ranking": alliance_ranking,
    "/soc/exchange/book": exchange.view_book,
    "/soc/exchange/mine": exchange.my_orders,
    "/soc/charts/prices": charts.price_history,
    "/soc/charts/economy": charts.economy_history,
}

# Paths that must not advance the world or write except their own read-only query.
READ_ONLY = {"/soc/alliances", "/soc/inbox", "/soc/alliance-ranking", "/soc/exchange/book", "/soc/exchange/mine",
             "/soc/charts/prices", "/soc/charts/economy"}

# Pledge needs the clock object, not just the month index.
NEEDS_CLOCK = {"/soc/project/pledge"}


def perform_post(db, ph, owner, path, payload, client, now, clk):
    """Replay, rate limit, call, store. Caller has already advanced the month and holds the world lock."""
    fn = POST.get(path)
    if fn is None:
        return 404, {"error": "not_found"}
    request_id = payload.get("request_id") if isinstance(payload, dict) else None
    try:
        uuid.UUID(request_id)
    except (ValueError, TypeError, AttributeError):
        return 400, {"error": "invalid_request_id"}
    prev = db.execute(_q("SELECT response FROM commands WHERE owner=%s AND request_id=%s", ph), (owner, request_id)).fetchone()
    if prev:
        return 200, json.loads(prev[0])
    kind = "message" if path == "/soc/message" else "report" if path == "/soc/report" else "action"
    if not guarded(owner, client or "", kind):
        return 429, {"error": "rate_limited"}
    month = int(clk["month_index"])
    if path in NEEDS_CLOCK:
        status, result = fn(db, ph, owner, payload, month, now, clk)
    else:
        status, result = fn(db, ph, owner, payload, month, now)
    if status == 201:
        db.execute(_q("INSERT INTO commands(owner,request_id,response) VALUES(%s,%s,%s)", ph),
                   (owner, request_id, json.dumps(result, ensure_ascii=False)))
    return status, result


def perform_get(db, ph, owner, path, args, clk=None):
    fn = GET.get(path)
    if fn is None:
        return 404, {"error": "not_found"}
    if clk is not None:
        args = dict(args)
        args["month"] = str(clk["month_index"])
        args["now"] = str(clk.get("server_time") or 0)
    return fn(db, ph, owner, args)
