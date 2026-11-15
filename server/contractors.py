"""EX-04 building contractors, including NPC firms and player firms.
All mutations are inside the same serialized world transaction as projects.
"""
import json
import uuid

import clock
import economy
import regional_prices

NPC_CONTRACTORS = (
    ("npc:builder:ufa", "Башстрой", 3, 900),
    ("npc:builder:region", "РегионСтрой", 2, 850),
    ("npc:builder:small", "Малый подряд", 1, 800),
)
LATE_PENALTY_PERMILLE = 10

def _q(statement, ph):
    return statement.replace("%s", ph)

def ensure(db, ph):
    db.execute("""CREATE TABLE IF NOT EXISTS contractors (
       id TEXT PRIMARY KEY, owner TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
       capacity INTEGER NOT NULL CHECK(capacity>=1 AND capacity<=20),
       quality_permille INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1)""")
    db.execute("""CREATE TABLE IF NOT EXISTS contractor_orders (
       project_id TEXT PRIMARY KEY, contractor_id TEXT NOT NULL REFERENCES contractors(id),
       agreed_price BIGINT NOT NULL, deadline_month BIGINT NOT NULL,
       late_penalty_permille INTEGER NOT NULL, paid BIGINT NOT NULL DEFAULT 0,
       status TEXT NOT NULL DEFAULT 'active')""")
    for cid, name, capacity, quality in NPC_CONTRACTORS:
        db.execute(_q("""INSERT INTO contractors(id,owner,name,capacity,quality_permille)
                 VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""", ph),
                   (cid, cid, name, capacity, quality))

def _row(row):
    return dict(zip(("id","owner","name","capacity","quality_permille","active","busy"),row))

def view(db, ph):
    rows = db.execute("""SELECT c.id,c.owner,c.name,c.capacity,c.quality_permille,c.active,
        (SELECT COUNT(*) FROM contractor_orders o
         WHERE o.contractor_id=c.id AND o.status='active') AS busy
        FROM contractors c ORDER BY c.id""").fetchall()
    return 200, {"contractors": [_row(r) for r in rows]}

def register(db, ph, owner, payload, now):
    import land
    rid, replay = land._command(db, ph, owner, payload)
    if replay: return replay
    name, capacity = payload.get("name"), payload.get("capacity", 1)
    if type(name) is not str or not 3<=len(name.strip())<=64 or type(capacity) is not int or not 1<=capacity<=20:
        return 400, {"error": "invalid_contractor"}
    old=db.execute(_q("SELECT id FROM contractors WHERE owner=%s",ph),(owner,)).fetchone()
    if old:
        return 409, {"error": "already_contractor", "contractor_id": old[0]}
    cid="player:"+uuid.uuid4().hex
    db.execute(_q("INSERT INTO contractors(id,owner,name,capacity,quality_permille) VALUES(%s,%s,%s,%s,900)",ph),
               (cid,owner,name.strip(),capacity))
    result={"ok": True,"contractor_id": cid,"capacity": capacity}
    land._remember(db,ph,owner,rid,result)
    return 201,result

def available(db, ph, cid):
    row=db.execute(_q("""SELECT c.id,c.owner,c.capacity,c.active,
         (SELECT COUNT(*) FROM contractor_orders o WHERE o.contractor_id=c.id AND o.status='active')
         FROM contractors c WHERE c.id=%s""",ph),(cid,)).fetchone()
    if not row or not row[3] or row[4]>=row[2]:
        return None
    return {"id":row[0],"owner":row[1],"capacity":row[2],"busy":row[4]}

def assign(db, ph, project_id, cid, cost, deadline_month):
    contractor = available(db,ph,cid)
    if not contractor:
        return False
    db.execute(_q("""INSERT INTO contractor_orders(project_id,contractor_id,agreed_price,deadline_month,late_penalty_permille)
                  VALUES(%s,%s,%s,%s,%s)""",ph),
               (project_id,cid,cost,deadline_month,LATE_PENALTY_PERMILLE))
    return True

def pay_milestone(db, ph, project_id, amount, now):
    if amount<=0: return 0
    row=db.execute(_q("""SELECT o.contractor_id,c.owner FROM contractor_orders o
       JOIN contractors c ON c.id=o.contractor_id WHERE o.project_id=%s AND o.status='active'""",ph),
                   (project_id,)).fetchone()
    recipient=economy.player_account(row[1]) if row else economy.CONSTRUCTION
    escrow="system:project:"+project_id
    economy.post(db,ph,"construction_milestone","Строительный этап "+project_id,
                 [(escrow,-amount),(recipient,amount)],now)
    if row:
        db.execute(_q("UPDATE contractor_orders SET paid=paid+%s WHERE project_id=%s",ph),(amount,project_id))
    return amount

def finish(db, ph, project_id, done_month, now):
    row=db.execute(_q("""SELECT o.deadline_month,o.agreed_price,o.late_penalty_permille,c.owner
       FROM contractor_orders o JOIN contractors c ON c.id=o.contractor_id
       WHERE o.project_id=%s AND o.status='active'""",ph),(project_id,)).fetchone()
    penalty=0
    if row and done_month>row[0]:
        # Penalties are capped by the contractor's actually available funds.
        due=(done_month-row[0])*row[1]*row[2]//1000
        available_cash=max(0,economy.balance(db,ph,row[3]) or 0)
        penalty=min(due,available_cash)
        if penalty:
            project=db.execute(_q("SELECT owner FROM construction_projects WHERE id=%s",ph),(project_id,)).fetchone()
            if project and project[0]!=row[3]:
                economy.post(db,ph,"contractor_penalty","Просрочка договора "+project_id,
                             [(economy.player_account(row[3]),-penalty),
                              (economy.player_account(project[0]),penalty)],now)
    db.execute(_q("UPDATE contractor_orders SET status='complete' WHERE project_id=%s",ph),(project_id,))
    return penalty

def cancel(db, ph, project_id):
    db.execute(_q("UPDATE contractor_orders SET status='cancelled' WHERE project_id=%s",ph),(project_id,))
