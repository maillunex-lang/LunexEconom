"""Enterprise HTTP endpoints; the platform owns transactions and authorization."""
from __future__ import annotations

import re
from psycopg.types.json import Jsonb
from server.platform.api import authenticate
from server.ledger.api import account, transfer
from server.world import core as world
from . import core

REQUEST = re.compile(r'^[A-Za-z0-9_.:-]{1,100}$')

def _id(ctx):
    try:
        return core.integer(int(ctx['path_params']['id']),1)
    except (KeyError,TypeError,ValueError):
        return None

def _mine(ctx):
    actor=authenticate(ctx)
    if not actor:
        return None,None,(401,{'error':'unauthorized'})
    eid=_id(ctx)
    row=ctx['conn'].execute("""SELECT id,owner_id,building_id,name,stage,running,staffing_bp,
      load_bp,recipe_id,storage_capacity,wear,build_cost,px,py,x,y
      FROM enterprises WHERE id=%s AND sold_at IS NULL""",(eid,)).fetchone() if eid else None
    if row is None or row[1]!=actor['id']:
        return actor,None,(404,{'error':'not_found'})
    return actor,row,None

def _detail(ctx,r):
    return {'id':r[0],'building_id':r[2],'name':r[3],
            'stage':core.STAGES[r[4]],'stage_index':r[4],
            'running':r[5],'staffing_bp':r[6],'load_bp':r[7],
            'recipe_id':r[8],'storage_capacity':r[9],
            'wear':r[10],'build_cost':r[11],
            'parcel':{'px':r[12],'py':r[13]},
            'position':{'x':r[14],'y':r[15]},
            'inventory':core.stock(ctx['conn'],r[0]),
            **core.payment_status(ctx['conn'],r[0],r[4],r[11]),
            'balance':'draft'}

def create(body,ctx):
    actor=authenticate(ctx)
    if not actor:
        return 401,{'error':'unauthorized'}
    if not isinstance(body,dict):
        return 400,{'error':'invalid_body'}
    request=body.get('request_id')
    building=body.get('building_id')
    if not isinstance(request,str) or not REQUEST.fullmatch(request):
        return 400,{'error':'invalid_request_id'}
    if not isinstance(building,str):
        return 400,{'error':'invalid_building'}
    try:
        px=core.integer(body.get('px'),-world.MAX_REQUEST_COORD,world.MAX_REQUEST_COORD)
        py=core.integer(body.get('py'),-world.MAX_REQUEST_COORD,world.MAX_REQUEST_COORD)
        x=core.integer(body.get('x',px*6),-world.MAX_REQUEST_COORD,world.MAX_REQUEST_COORD)
        y=core.integer(body.get('y',py*6),-world.MAX_REQUEST_COORD,world.MAX_REQUEST_COORD)
    except ValueError:
        return 400,{'error':'invalid_coordinates'}
    return core.place(ctx['conn'],actor,request,building,px,py,x,y)

def plan(body,ctx):
    actor=authenticate(ctx)
    if not actor:
        return 401,{'error':'unauthorized'}
    def arg(key):
        values=ctx.get('query',{}).get(key)
        return values[0] if isinstance(values,list) and len(values)==1 else None
    building=arg('building_id')
    if not isinstance(building,str):
        return 400,{'error':'invalid_building'}
    try:
        px=core.integer(int(arg('px')),-world.MAX_REQUEST_COORD,world.MAX_REQUEST_COORD)
        py=core.integer(int(arg('py')),-world.MAX_REQUEST_COORD,world.MAX_REQUEST_COORD)
        x=core.integer(int(arg('x') if arg('x') is not None else px*6),-world.MAX_REQUEST_COORD,world.MAX_REQUEST_COORD)
        y=core.integer(int(arg('y') if arg('y') is not None else py*6),-world.MAX_REQUEST_COORD,world.MAX_REQUEST_COORD)
    except (TypeError,ValueError):
        return 400,{'error':'invalid_coordinates'}
    return core.plan(ctx['conn'],actor,building,px,py,x,y)

def list_own(body,ctx):
    actor=authenticate(ctx)
    if not actor:
        return 401,{'error':'unauthorized'}
    rows=ctx['conn'].execute(
        'SELECT id,stage,build_cost FROM enterprises '
        'WHERE owner_id=%s AND sold_at IS NULL ORDER BY id',
        (actor['id'],)).fetchall()
    # Preserve the original enterprise ID list for existing Android clients.
    details=[{'id':eid,'stage_index':stage,
              **core.payment_status(ctx['conn'],eid,stage,cost)}
             for eid,stage,cost in rows]
    return 200,{'enterprises':[row[0] for row in rows], 'items':details}

def one(body,ctx):
    _,row,error=_mine(ctx)
    return error if error else (200,_detail(ctx,row))

def settings(body,ctx):
    _,row,error=_mine(ctx)
    if error:return error
    if not isinstance(body,dict) or set(body)-{'name','recipe_id','min_stock','running','staffing_bp'}:
        return 400,{'error':'invalid_settings'}
    name=body.get('name',row[3])
    recipe=body.get('recipe_id',row[8])
    running=body.get('running',row[5])
    staffing=body.get('staffing_bp',row[6])
    minimum=body.get('min_stock')
    if not isinstance(name,str) or not 1<=len(name.strip())<=80:
        return 400,{'error':'invalid_name'}
    if type(running) is not bool:
        return 400,{'error':'invalid_running'}
    try:core.integer(staffing,0,10000)
    except ValueError:return 400,{'error':'invalid_staffing'}
    if recipe is not None and not any(r['id']==recipe and r['building']==row[2] for r in core.catalog().data['recipes']):
        return 400,{'error':'invalid_recipe'}
    if minimum is not None:
        if not isinstance(minimum,dict):
            return 400,{'error':'invalid_min_stock'}
        try:
            if any(p not in core.catalog().index['products'] or core.integer(v,0,row[9]) is None for p,v in minimum.items()):
                return 400,{'error':'invalid_min_stock'}
        except ValueError:return 400,{'error':'invalid_min_stock'}
        ctx['conn'].execute('UPDATE enterprises SET name=%s,recipe_id=%s,running=%s,staffing_bp=%s,min_stock=%s WHERE id=%s',
                            (name.strip(),recipe,running,staffing,Jsonb(minimum),row[0]))
    else:
        ctx['conn'].execute('UPDATE enterprises SET name=%s,recipe_id=%s,running=%s,staffing_bp=%s WHERE id=%s',
                            (name.strip(),recipe,running,staffing,row[0]))
    return 200,{'id':row[0],'ok':True}

def sell(body,ctx):
    actor,row,error=_mine(ctx)
    if error:
        # Replayed sale requests must remain idempotent after the asset is retired.
        req=body.get('request_id') if isinstance(body,dict) else None
        if actor and isinstance(req,str) and REQUEST.fullmatch(req):
            previous=ctx['conn'].execute('SELECT enterprise_id,owner_id,price,transfer_id FROM enterprise_sale_requests WHERE request_id=%s',(req,)).fetchone()
            if previous and previous[1]==actor['id'] and previous[0]==_id(ctx):
                return 200,{'id':previous[0],'price':previous[2],'transfer_id':previous[3],'idempotent':True}
        return error
    req=body.get('request_id') if isinstance(body,dict) else None
    if not isinstance(req,str) or not REQUEST.fullmatch(req):
        return 400,{'error':'invalid_request_id'}
    conn=ctx['conn']
    locked=conn.execute('SELECT stage,build_cost,sold_at FROM enterprises '
                        'WHERE id=%s FOR UPDATE',(row[0],)).fetchone()
    if locked is None or locked[2] is not None:
        previous=conn.execute('SELECT enterprise_id,owner_id,price,transfer_id '
                              'FROM enterprise_sale_requests WHERE request_id=%s',
                              (req,)).fetchone()
        if previous and previous[:2]==(row[0],actor['id']):
            return 200,{'id':row[0],'price':previous[2],
                        'transfer_id':previous[3],'idempotent':True}
        return 404,{'error':'not_found'}
    if any(v['quantity']>0 for v in core.stock(conn,row[0]).values()):
        return 409,{'error':'inventory_not_empty'}
    previous=conn.execute('SELECT enterprise_id,owner_id,price,transfer_id FROM enterprise_sale_requests WHERE request_id=%s',(req,)).fetchone()
    if previous:
        if previous[:2]!=(row[0],actor['id']):
            return 409,{'error':'request_id_conflict'}
        return 200,{'id':row[0],'price':previous[2],'transfer_id':previous[3],'idempotent':True}
    # balance: draft. Construction resale refunds half of the ALREADY paid
    # installments. Operational buildings preserve 50% of full build_cost.
    paid=conn.execute('SELECT COALESCE(sum(amount),0),count(*) '
                      'FROM enterprise_stage_payments WHERE enterprise_id=%s',
                      (row[0],)).fetchone()
    total_paid=int(paid[0]) if paid[1] else (locked[1] if locked[0]==4 else 0)
    price=total_paid//2
    if price<=0:
        return 409,{'error':'no_paid_construction'}
    player=account(conn,'player:'+actor['username'].lower(),'player',actor['id'])
    treasury=account(conn,'system:treasury')
    transfer_id=transfer(conn,'enterprise:sell:'+req,treasury,player,price)
    world.clear_occupied(conn,'enterprise:'+str(row[0]))
    conn.execute('DELETE FROM enterprise_build_waits WHERE enterprise_id=%s',(row[0],))
    conn.execute('UPDATE enterprises SET sold_at=now(),running=false WHERE id=%s',(row[0],))
    conn.execute('INSERT INTO enterprise_sale_requests(request_id,enterprise_id,owner_id,price,transfer_id) VALUES(%s,%s,%s,%s,%s)',
                 (req,row[0],actor['id'],price,transfer_id))
    return 200,{'id':row[0],'price':price,'transfer_id':transfer_id,'idempotent':False}

def demolish(body,ctx):
    """Retire a building without charging unfinished stages (D-14: 200‰ draft)."""
    actor,row,error=_mine(ctx)
    req=body.get('request_id') if isinstance(body,dict) else None
    if not isinstance(req,str) or not REQUEST.fullmatch(req):
        return 400,{'error':'invalid_request_id'}
    conn=ctx['conn']
    if error:
        if actor:
            previous=conn.execute("""SELECT enterprise_id,owner_id,refund,transfer_id
              FROM enterprise_demolition_requests WHERE request_id=%s""",(req,)).fetchone()
            if previous and previous[:2]==(_id(ctx),actor['id']):
                return 200,{'id':previous[0],'refund':previous[2],
                            'transfer_id':previous[3],'idempotent':True}
        return error
    locked=conn.execute('SELECT stage,build_cost,sold_at FROM enterprises '
                        'WHERE id=%s FOR UPDATE',(row[0],)).fetchone()
    if locked is None or locked[2] is not None:
        return 404,{'error':'not_found'}
    previous=conn.execute("""SELECT enterprise_id,owner_id,refund,transfer_id
      FROM enterprise_demolition_requests WHERE request_id=%s""",(req,)).fetchone()
    if previous:
        if previous[:2]!=(row[0],actor['id']):
            return 409,{'error':'request_id_conflict'}
        return 200,{'id':row[0],'refund':previous[2],
                    'transfer_id':previous[3],'idempotent':True}
    if any(v['quantity']>0 for v in core.stock(conn,row[0]).values()):
        return 409,{'error':'inventory_not_empty'}
    paid=conn.execute('SELECT COALESCE(sum(amount),0),count(*) '
                      'FROM enterprise_stage_payments WHERE enterprise_id=%s',
                      (row[0],)).fetchone()
    amount=int(paid[0]) if paid[1] else (locked[1] if locked[0]==4 else 0)
    refund=amount*200//1000  # 20% of paid material value, balance: draft.
    receipt=None
    if refund:
        player=account(conn,'player:'+actor['username'].lower(),'player',actor['id'])
        receipt=transfer(conn,'enterprise:demolish:'+req,
                         account(conn,'system:treasury'),player,refund)
    world.clear_occupied(conn,'enterprise:'+str(row[0]))
    conn.execute('DELETE FROM enterprise_build_waits WHERE enterprise_id=%s',(row[0],))
    conn.execute('UPDATE enterprises SET sold_at=now(),running=false WHERE id=%s',(row[0],))
    conn.execute("""INSERT INTO enterprise_demolition_requests
      (request_id,enterprise_id,owner_id,refund,transfer_id)
      VALUES(%s,%s,%s,%s,%s)""",(req,row[0],actor['id'],refund,receipt))
    return 200,{'id':row[0],'refund':refund,'transfer_id':receipt,
                'idempotent':False}


def report(body,ctx):
    _,row,error=_mine(ctx)
    if error:return error
    rows=ctx['conn'].execute("""SELECT month_index,revenue,expenses,average_load_bp,inventory,wear
      FROM enterprise_month_reports WHERE enterprise_id=%s ORDER BY month_index DESC LIMIT 24""",(row[0],)).fetchall()
    return 200,{'id':row[0],'reports':[{'month_index':m,'revenue':rev,'expenses':exp,
      'profit':rev-exp,'average_load_bp':load,'inventory':inv,'wear':wear}
      for m,rev,exp,load,inv,wear in rows]}

def admin_stock(body,ctx):
    if not ctx.get('admin_verified') or not ctx['settings'].get('enterprise_admin_stock_draft',False):
        return 403,{'error':'forbidden'}
    eid=_id(ctx)
    if eid is None:
        return 404,{'error':'not_found'}
    row=ctx['conn'].execute('SELECT storage_capacity FROM enterprises WHERE id=%s AND sold_at IS NULL FOR UPDATE',(eid,)).fetchone()
    if row is None:return 404,{'error':'not_found'}
    try:
        product=body['product_id']
        qty=core.integer(body['quantity'],1,1000000)
        quality=core.integer(body.get('quality',50),1,100)
        if core.stock_total(ctx['conn'],eid)+qty>row[0]:
            return 409,{'error':'warehouse_full'}
        core.adjust(ctx['conn'],eid,product,qty,quality)
        ctx['conn'].execute('INSERT INTO audit(actor,action,payload) VALUES(%s,%s,%s)',
          ('admin','enterprise.inventory',Jsonb({'enterprise_id':eid,'product_id':product,'quantity':qty})))
    except (ValueError,KeyError,TypeError):
        return 400,{'error':'invalid_inventory'}
    return 200,{'id':eid,'inventory':core.stock(ctx['conn'],eid)}
