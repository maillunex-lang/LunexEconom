"""EX-04: four-stage, financially accounted construction projects.
A project reserves world cells at ordering time, but only becomes an operating
building on commissioning. All operations run in the world-locked transaction.
Existing /build is unchanged when CONSTRUCTION_PROJECTS_ENABLED=0.
"""
import json
import math
import os
import time
import uuid

import city_catalog
import clock
import contractors
import economy
import geo
import goods_catalog
import land
import production
import regional_prices
import zoning

STAGES = tuple(name for name, _ in city_catalog.STAGES)
WEIGHTS = tuple(share for _, share in city_catalog.STAGES)
CUMULATIVE = tuple(sum(WEIGHTS[:i+1]) for i in range(len(WEIGHTS)))
CANCEL_PENALTY_PERMILLE = 50
REPAIR_COST_PERMILLE = 600
WEAR_FLOOR = 0

def enabled():
    return os.environ.get("CONSTRUCTION_PROJECTS_ENABLED", "0").lower() in ("1", "true", "yes")

def _q(sql, ph):
    return sql.replace("%s", ph)

def ensure(db, ph):
    db.execute("""CREATE TABLE IF NOT EXISTS construction_projects (
       id TEXT PRIMARY KEY, owner TEXT NOT NULL, object_key TEXT NOT NULL,
       city_id TEXT NOT NULL, x INTEGER NOT NULL, y INTEGER NOT NULL,
       w INTEGER NOT NULL, h INTEGER NOT NULL, created_month BIGINT NOT NULL,
       last_month BIGINT NOT NULL, build_months INTEGER NOT NULL,
       total_cost BIGINT NOT NULL, stage_index INTEGER NOT NULL DEFAULT 0,
       status TEXT NOT NULL DEFAULT 'building',
       material_mode TEXT NOT NULL DEFAULT 'mixed',
       wear_permille INTEGER NOT NULL DEFAULT 0,
       condition_permille INTEGER NOT NULL DEFAULT 1000,
       completion_month BIGINT, delay_reason TEXT, delayed_months INTEGER NOT NULL DEFAULT 0)""")
    db.execute("""CREATE TABLE IF NOT EXISTS project_materials (
       project_id TEXT NOT NULL REFERENCES construction_projects(id),
       product TEXT NOT NULL, required BIGINT NOT NULL CHECK(required>=0),
       used BIGINT NOT NULL DEFAULT 0 CHECK(used>=0),
       PRIMARY KEY(project_id,product))""")
    db.execute("""CREATE TABLE IF NOT EXISTS construction_market_purchases (
       month_index BIGINT NOT NULL, product TEXT NOT NULL,
       qty BIGINT NOT NULL CHECK(qty>=0),
       PRIMARY KEY(month_index,product))""")
    db.execute("""CREATE TABLE IF NOT EXISTS construction_housing_supply (
       project_id TEXT PRIMARY KEY REFERENCES construction_projects(id),
       owner TEXT NOT NULL, city_id TEXT NOT NULL, capacity INTEGER NOT NULL,
       commissioned_month BIGINT NOT NULL, integrated INTEGER NOT NULL DEFAULT 0)""")
    db.execute("""CREATE TABLE IF NOT EXISTS construction_repairs (
       id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES construction_projects(id),
       month_index BIGINT NOT NULL, amount BIGINT NOT NULL,
       before_permille INTEGER NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS construction_projects_owner ON construction_projects(owner,status)")
    contractors.ensure(db, ph)

def _spec(object_key, city_id):
    city_item=city_catalog.get(object_key)
    if city_item:
        return {"object_key":object_key, "category":city_item["category"],
                "w":city_item["w"],"h":city_item["h"],
                "months":city_item["build_months"],"cost":city_catalog.cost_in(object_key,city_id),
                "wear":city_item["wear_permille_per_month"],
                "materials":dict(city_item["materials"]),
                "capacity":city_item["capacity"]}
    if goods_catalog.has_recipe(object_key):
        recipe=goods_catalog.recipe(object_key)
        # Explicit construction bill of materials for industrial buildings.
        # Production recipe.inputs MUST NOT be mistaken for construction materials.
        materials={"cement":recipe.width*recipe.height*2,
                   "steel":recipe.width*recipe.height,
                   "brick":recipe.width*recipe.height*2}
        return {"object_key":object_key, "category":"industry",
                "w":recipe.width,"h":recipe.height,
                "months":city_catalog.build_months(recipe.width*recipe.height),
                "cost":int(round(recipe.build_cost*regional_prices.indices(city_id)["construction"])),
                "wear":4,"materials":materials,"capacity":0}
    # Existing warehouse and retail do not have a recipe in goods_catalog.
    if object_key in ("warehouse","shop"):
        import building_dimensions
        w,h=building_dimensions.footprint(object_key)
        return {"object_key":object_key,"category":"industry" if object_key=="warehouse" else "commercial",
                "w":w,"h":h,"months":city_catalog.build_months(w*h),
                "cost":int(round(economy.BUILD_COST[object_key]*regional_prices.indices(city_id)["construction"])),
                "wear":4,"materials":{"cement":w*h*2,"steel":w*h,"brick":w*h*2},"capacity":0}
    return None

def _location(x,y):
    city=geo.city_for_cell(x,y)
    return city["id"] if city else min(geo.cities(),key=lambda c:(c["x"]-x)**2+(c["y"]-y)**2)["id"]

def _footprint(x,y,w,h):
    return [(xx,yy) for xx in range(x,x+w) for yy in range(y,y+h)]

def _stage_name(index):
    return STAGES[index] if index<len(STAGES) else "complete"

def _project_row(row):
    keys=("id","owner","object_key","city_id","x","y","w","h","created_month",
          "last_month","build_months","total_cost","stage_index","status",
          "material_mode","wear_permille","condition_permille","completion_month",
          "delay_reason","delayed_months")
    result=dict(zip(keys,row))
    result["stage"]=_stage_name(result["stage_index"])
    return result

def get(db, ph, pid):
    row=db.execute(_q("SELECT * FROM construction_projects WHERE id=%s",ph),(pid,)).fetchone()
    return _project_row(row) if row else None

def list_projects(db, ph, owner):
    rows=db.execute(_q("""SELECT * FROM construction_projects WHERE owner=%s
         ORDER BY created_month DESC,id DESC LIMIT 100""",ph),(owner,)).fetchall()
    result=[]
    for row in rows:
        p=_project_row(row)
        p["materials"]=[{"product":m[0],"required":m[1],"used":m[2]} for m in
                         db.execute(_q("SELECT product,required,used FROM project_materials WHERE project_id=%s ORDER BY product",ph),
                                    (p["id"],)).fetchall()]
        result.append(p)
    return 200,{"enabled":enabled(),"projects":result}

def _emit(db,ph,p,kind,stage,now):
    """Update the same chunk/event system used by legacy construction_stages."""
    coords=_footprint(p["x"],p["y"],p["w"],p["h"])
    grouped={}
    for x,y in coords:
        grouped.setdefault((x//12,y//12),[]).append([x,y])
    for (cx,cy),cells in sorted(grouped.items()):
        db.execute(_q("""INSERT INTO chunks(cx,cy,version) VALUES(%s,%s,1)
           ON CONFLICT(cx,cy) DO UPDATE SET version=chunks.version+1""",ph),(cx,cy))
        version=db.execute(_q("SELECT version FROM chunks WHERE cx=%s AND cy=%s",ph),(cx,cy)).fetchone()[0]
        visual_stage = "complete" if stage in ("complete","cancelled") else ("foundation" if stage=="foundation" else "frame")
        data={"object_id":p["id"],"owner":p["owner"],
              "building_kind":p["object_key"],"construction_stage":visual_stage,
              "project_stage":stage, "cells":cells}
        db.execute(_q("INSERT INTO events(cx,cy,version,kind,payload) VALUES(%s,%s,%s,%s,%s)",ph),
                   (cx,cy,version,kind,json.dumps(data,ensure_ascii=False)))

def _prepare_road(db, ph, footprint):
    """Require existing road access; never silently add free roads."""
    import roads
    x0,x1,y0,y1=roads.search_box(footprint)
    dynamic={(x,y) for x,y in db.execute(_q(
       "SELECT x,y FROM roads WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s",ph),
       (x0,x1,y0,y1)).fetchall()}
    occupied={(x,y) for x,y in db.execute(_q(
       "SELECT x,y FROM cells WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s",ph),
       (x0,x1,y0,y1)).fetchall()}
    reason,path=roads.plan_access(footprint,dynamic,occupied,10000)
    if reason: return reason
    missing=[c for c in path if c not in dynamic and not roads.is_base_road(*c)]
    return "road_required" if missing else None

def create(db,ph,owner,payload,now,*,tender_price=None,tender_months=None):
    rid,replay=land._command(db,ph,owner,payload)
    if replay: return replay
    x,y=payload.get("x"),payload.get("y")
    key=payload.get("object_id",payload.get("kind"))
    if not land._valid_point(x) or not land._valid_point(y) or type(key) is not str:
        return 400,{"error":"invalid_project"}
    if not land.enabled():
        return 409,{"error":"land_feature_required"}
    city_id=_location(x,y)
    if payload.get("city_id",city_id)!=city_id:
        return 409,{"error":"city_mismatch","city_id":city_id}
    spec=_spec(key,city_id)
    if not spec: return 400,{"error":"unknown_object"}
    footprint=_footprint(x,y,spec["w"],spec["h"])
    if any(not land._valid_point(a) or not land._valid_point(b) for a,b in footprint):
        return 400,{"error":"outside_world"}
    if (spec["category"] in ("education","health","administration","green","transport","amenity")) and owner!=economy.CITY:
        return 403,{"error":"municipal_only"}
    if (spec["category"]=="housing") and owner==economy.CITY:
        # City housing can be commissioned through tenders; no arbitrary free orders.
        pass
    for xx,yy in footprint:
        parcel=land.get_parcel(db,ph,*land.parcel_for_cell(xx,yy))
        zone=parcel["zone"]
        if spec["category"] in ("housing","education","health","administration","green","transport","amenity","commercial"):
            allowed=("center","suburb")
        else:
            allowed=zoning.ALLOWED.get(key,("industrial","open"))
        if zone not in allowed:
            return 409,{"error":"wrong_zone","zone":zone,"allowed":list(allowed)}
    import deposits
    deposit_decision=deposits.gate(db,ph,key,footprint)
    if deposit_decision and deposit_decision.get("error"):
        return 409,deposit_decision
    land.migrate_existing(db,ph)
    permitted=land.allowed_to_build(db,ph,owner,footprint,now)
    if permitted:return 409,permitted
    if any(db.execute(_q("SELECT 1 FROM cells WHERE x=%s AND y=%s",ph),(xx,yy)).fetchone() for xx,yy in footprint):
        return 409,{"error":"occupied"}
    reason=_prepare_road(db,ph,footprint)
    if reason:return 409,{"error":reason}
    mode=payload.get("material_mode","mixed")
    if mode not in ("inventory","market","mixed"): return 400,{"error":"invalid_material_mode"}
    contractor_id=payload.get("contractor_id")
    if contractor_id is not None and (type(contractor_id) is not str or not contractors.available(db,ph,contractor_id)):
        return 409,{"error":"contractor_unavailable"}
    cost=tender_price if tender_price is not None else spec["cost"]
    build_months=tender_months if tender_months is not None else spec["months"]
    if type(cost) is not int or not 0<cost<=spec["cost"] or type(build_months) is not int or not 1<=build_months<=24:
        return 400,{"error":"invalid_project_cost"}
    balance=land._wallet(db,ph,owner,now)
    if balance<cost:return 402,{"error":"insufficient_funds","cost":cost,"balance":balance}
    clk=clock.state(db,ph,now)
    pid=uuid.uuid4().hex
    escrow="system:project:"+pid
    economy.post(db,ph,"construction_reserve","Бюджет стройки "+pid,
                 [(economy.player_account(owner),-cost),(escrow,cost)],now)
    db.execute(_q("""INSERT INTO buildings(id,owner,kind,x,y,created)
                  VALUES(%s,%s,%s,%s,%s,%s)""",ph),(pid,owner,key,x,y,now))
    # A project does not register in the old 2-stage visual timer.
    # Its 4-stage authoritative state is exposed by construction_stages.stages_for_chunk.
    db.execute(_q("""INSERT INTO construction_projects
       (id,owner,object_key,city_id,x,y,w,h,created_month,last_month,build_months,
        total_cost,material_mode,wear_permille)
       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",ph),
       (pid,owner,key,city_id,x,y,spec["w"],spec["h"],clk["month_index"],
        clk["month_index"]-1,build_months,cost,mode,spec["wear"]))
    for product,required in sorted(spec["materials"].items()):
        if not goods_catalog.has_good(product):raise ValueError("uncatalogued construction good: "+product)
        db.execute(_q("INSERT INTO project_materials(project_id,product,required) VALUES(%s,%s,%s)",ph),
                   (pid,product,int(required)))
    for xx,yy in footprint:
        db.execute(_q("INSERT INTO cells(x,y,object_id) VALUES(%s,%s,%s)",ph),(xx,yy,pid))
    if deposit_decision and deposit_decision.get("deposit_id"):
        deposits.link(db,ph,pid,deposit_decision["deposit_id"],deposit_decision["resource"])
    if contractor_id and not contractors.assign(db,ph,pid,contractor_id,cost,clk["month_index"]+build_months):
        raise RuntimeError("contractor_capacity_changed")
    p=get(db,ph,pid)
    _emit(db,ph,p,"building_created","foundation",now)
    result={"ok":True,"project_id":pid,"cost":cost,"stage":"foundation",
            "months":build_months,"city_id":city_id,
            "materials":spec["materials"],"contractor_id":contractor_id}
    land._remember(db,ph,owner,rid,result)
    return 201,result

def _market_quote(db,ph,product,month):
    """Quote the current simulated commodity market, not an unlimited imaginary supplier."""
    row=db.execute(_q("""SELECT price,supply FROM market_prices
       WHERE product=%s AND month_index<=%s ORDER BY month_index DESC LIMIT 1""",ph),
       (product,month)).fetchone()
    return (int(row[0]),max(0,int(row[1]))) if row else None

def _materials_stage(db,ph,p,idx,month,now):
    """Atomic preflight first, then consume inventory and buy only actual market supply.
    Returns False without changing quantities/wallets when anything is missing."""
    need=[]
    for product,required,used in db.execute(_q("""SELECT product,required,used FROM project_materials
                                 WHERE project_id=%s ORDER BY product""",ph),(p["id"],)).fetchall():
        target=(required*CUMULATIVE[idx]+999)//1000
        delta=max(0,target-used)
        if not delta:continue
        have=db.execute(_q("SELECT qty FROM inventory WHERE owner=%s AND product=%s",ph),
                        (p["owner"],product)).fetchone()
        stock=max(0,int(have[0])) if have else 0
        own=min(delta,stock) if p["material_mode"] in ("inventory","mixed") else 0
        purchase=delta-own
        market_price=0
        if purchase:
            if p["material_mode"]=="inventory":return False,"materials_missing"
            quote=_market_quote(db,ph,product,month)
            if not quote:return False,"market_quote_unavailable"
            market_price,supply=quote
            bought=db.execute(_q("""SELECT qty FROM construction_market_purchases
                      WHERE month_index=%s AND product=%s""",ph),(month,product)).fetchone()
            if supply-(bought[0] if bought else 0)<purchase:
                return False,"market_supply_shortage"
        need.append((product,delta,own,purchase,market_price))
    bill=sum(purchase*unit for _,_,_,purchase,unit in need)
    escrow="system:project:"+p["id"]
    escrow_balance=db.execute(_q("SELECT balance FROM wallets WHERE account=%s",ph),(escrow,)).fetchone()
    available=max(0,int(escrow_balance[0])) if escrow_balance else 0
    if bill>available:return False,"construction_budget_exhausted"
    for product,delta,own,purchase,unit in need:
        if own:
            db.execute(_q("UPDATE inventory SET qty=qty-%s WHERE owner=%s AND product=%s AND qty>=%s",ph),
                       (own,p["owner"],product,own))
        if purchase:
            db.execute(_q("""INSERT INTO construction_market_purchases(month_index,product,qty)
                     VALUES(%s,%s,%s) ON CONFLICT(month_index,product)
                     DO UPDATE SET qty=construction_market_purchases.qty+excluded.qty""",ph),
                       (month,product,purchase))
            economy.post(db,ph,"construction_material","Материалы "+product+" для "+p["id"],
                         [(escrow,-purchase*unit),(economy.MARKET_ACCOUNT,purchase*unit)],now)
        db.execute(_q("UPDATE project_materials SET used=used+%s WHERE project_id=%s AND product=%s",ph),
                   (delta,p["id"],product))
    return True,""

def _escrow_balance(db,ph,pid):
    row=db.execute(_q("SELECT balance FROM wallets WHERE account=%s",ph),("system:project:"+pid,)).fetchone()
    return int(row[0]) if row else 0

def _settle_phase(db,ph,p,idx,now):
    already=p["total_cost"]-_escrow_balance(db,ph,p["id"])
    targeted=p["total_cost"]*CUMULATIVE[idx]//1000
    payment=max(0,min(_escrow_balance(db,ph,p["id"]),targeted-already))
    return contractors.pay_milestone(db,ph,p["id"],payment,now)

def _commission(db,ph,p,month,now):
    # Only now does production see the facility. Housing and public facilities
    # remain non-productive unless the existing catalog supplies a production spec.
    if p["object_key"] in economy.PRODUCTION or goods_catalog.has_recipe(p["object_key"]):
        clk=clock.state(db,ph,now)
        clk["month_index"]=month
        clk["seconds_to_next_month"]=clk["month_seconds"]
        production.register_building(db,ph,p["owner"],p["id"],p["object_key"],clk)
    item=city_catalog.get(p["object_key"])
    if item and item["category"]=="housing":
        db.execute(_q("""INSERT INTO construction_housing_supply
           (project_id,owner,city_id,capacity,commissioned_month)
           VALUES(%s,%s,%s,%s,%s) ON CONFLICT(project_id) DO NOTHING""",ph),
           (p["id"],p["owner"],p["city_id"],item["capacity"],month))
        _emit(db,ph,p,"housing_commissioned","complete",now)
    penalty=contractors.finish(db,ph,p["id"],month,now)
    return penalty

def monthly(db,ph,month,now):
    if not enabled(): return {"advanced":0,"delayed":0,"completed":0,"wear":0}
    rows=db.execute("""SELECT * FROM construction_projects WHERE status IN ('building','delayed','complete')
                   ORDER BY id""").fetchall()
    advanced=delayed=completed=wear_count=0
    for row in rows:
        p=_project_row(row)
        if p["status"]=="complete":
            if p["completion_month"] is not None and month>p["completion_month"] and month>p["last_month"]:
                elapsed=month-max(p["completion_month"],p["last_month"])
                condition=max(WEAR_FLOOR,p["condition_permille"]-elapsed*p["wear_permille"])
                db.execute(_q("UPDATE construction_projects SET condition_permille=%s,last_month=%s WHERE id=%s",ph),
                           (condition,month,p["id"]))
                wear_count+=1
            continue
        if p["last_month"]>=month:continue
        idx=p["stage_index"]
        stalled=False
        # At most four transitions even after a long offline period.
        while idx<len(STAGES):
            threshold=(p["build_months"]*CUMULATIVE[idx]+999)//1000
            if month-p["created_month"]<threshold:break
            ok,reason=_materials_stage(db,ph,p,idx,month,now)
            if not ok:
                db.execute(_q("""UPDATE construction_projects SET status='delayed',
                     delay_reason=%s,delayed_months=delayed_months+1,
                     last_month=%s WHERE id=%s""",ph),(reason,month,p["id"]))
                delayed+=1
                stalled=True
                break
            _settle_phase(db,ph,p,idx,now)
            idx+=1
            db.execute(_q("""UPDATE construction_projects SET stage_index=%s,status=%s,
                delay_reason=NULL WHERE id=%s""",ph),
                (idx,"complete" if idx==len(STAGES) else "building",p["id"]))
            _emit(db,ph,p,"building_created",_stage_name(idx),now)
            advanced+=1
            if idx==len(STAGES):
                # Spend the remaining reserved budget on contractor labour / work.
                remainder=_escrow_balance(db,ph,p["id"])
                if remainder:
                    contractors.pay_milestone(db,ph,p["id"],remainder,now)
                _commission(db,ph,p,month,now)
                db.execute(_q("UPDATE construction_projects SET completion_month=%s WHERE id=%s",ph),
                           (month,p["id"]))
                completed+=1
        if not stalled:
            db.execute(_q("UPDATE construction_projects SET last_month=%s WHERE id=%s",ph),(month,p["id"]))
    return {"advanced":advanced,"delayed":delayed,"completed":completed,"wear":wear_count}

def cancel(db,ph,owner,payload,now):
    rid,replay=land._command(db,ph,owner,payload)
    if replay:return replay
    pid=payload.get("project_id")
    if type(pid) is not str:return 400,{"error":"invalid_project"}
    p=get(db,ph,pid)
    if not p:return 404,{"error":"not_found"}
    if p["owner"]!=owner:return 403,{"error":"not_owner"}
    if p["status"] in ("complete","cancelled"):return 409,{"error":"cannot_cancel"}
    remaining=_escrow_balance(db,ph,pid)
    penalty=remaining*CANCEL_PENALTY_PERMILLE//1000
    refund=remaining-penalty
    escrow="system:project:"+pid
    if refund:
        economy.post(db,ph,"construction_cancel","Возврат бюджета "+pid,
                     [(escrow,-refund),(economy.player_account(owner),refund)],now)
    if penalty:
        economy.post(db,ph,"construction_cancel_fee","Неустойка "+pid,
                     [(escrow,-penalty),(economy.CONSTRUCTION,penalty)],now)
    _emit(db,ph,p,"building_removed","cancelled",now)
    db.execute(_q("DELETE FROM cells WHERE object_id=%s",ph),(pid,))
    db.execute(_q("DELETE FROM buildings WHERE id=%s",ph),(pid,))
    db.execute(_q("UPDATE construction_projects SET status='cancelled',delay_reason=NULL WHERE id=%s",ph),(pid,))
    contractors.cancel(db,ph,pid)
    result={"ok":True,"project_id":pid,"refund":refund,"cancellation_fee":penalty}
    land._remember(db,ph,owner,rid,result)
    return 200,result

def fund(db,ph,owner,payload,now):
    rid,replay=land._command(db,ph,owner,payload)
    if replay:return replay
    pid,amount=payload.get("project_id"),payload.get("amount")
    p=get(db,ph,pid) if type(pid) is str else None
    if not p:return 404,{"error":"not_found"}
    if p["owner"]!=owner:return 403,{"error":"not_owner"}
    if p["status"] not in ("building","delayed") or type(amount) is not int or not 1<=amount<=10**9:
        return 400,{"error":"invalid_funding"}
    if not land._transfer(db,ph,owner,"system:project:"+pid,amount,
                          "construction_topup","Пополнение бюджета стройки "+pid,now):
        return 402,{"error":"insufficient_funds"}
    result={"ok":True,"project_id":pid,"added":amount}
    land._remember(db,ph,owner,rid,result)
    return 201,result

def repair(db,ph,owner,payload,now):
    rid,replay=land._command(db,ph,owner,payload)
    if replay:return replay
    pid=payload.get("project_id")
    p=get(db,ph,pid) if type(pid) is str else None
    if not p:return 404,{"error":"not_found"}
    if p["owner"]!=owner:return 403,{"error":"not_owner"}
    if p["status"]!="complete":return 409,{"error":"not_commissioned"}
    deficit=1000-p["condition_permille"]
    if deficit<=0:return 409,{"error":"no_repairs_needed"}
    price=max(1,p["total_cost"]*deficit*REPAIR_COST_PERMILLE//1000000)
    if not land._transfer(db,ph,owner,economy.CONSTRUCTION,price,"construction_repair",
                          "Ремонт здания "+pid,now):
        return 402,{"error":"insufficient_funds","cost":price}
    db.execute(_q("UPDATE construction_projects SET condition_permille=1000 WHERE id=%s",ph),(pid,))
    repair_id=uuid.uuid4().hex
    db.execute(_q("""INSERT INTO construction_repairs
         (id,project_id,month_index,amount,before_permille) VALUES(%s,%s,%s,%s,%s)""",ph),
         (repair_id,pid,clock.state(db,ph,now)["month_index"],price,p["condition_permille"]))
    result={"ok":True,"project_id":pid,"cost":price,"condition_permille":1000}
    land._remember(db,ph,owner,rid,result)
    return 201,result
