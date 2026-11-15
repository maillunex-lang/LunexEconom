"""One idempotent, opt-in monthly dispatch for human/NPC company automation.

Legacy production clears at owner level. Never double-spend stock or cash:
financial sub-account allocation is the only action supported until each
enterprise has its own cash and inventory settlement in a subsequent release.
"""
import json
import uuid

import holding

MANAGERS=('purchasing','production','sales','logistics','staff','finance')


def _q(sql,ph):
    return sql.replace('%s',ph)


def validate(config):
    if not isinstance(config,dict) or any(key not in MANAGERS for key in config):
        raise ValueError('invalid_managers')
    for name,value in config.items():
        if not isinstance(value,dict) or type(value.get('enabled',False)) is not bool:
            raise ValueError('invalid_manager')
        if name=='finance':
            allowed={'enabled','target_sub_id','max_transfer','cash_reserve'}
            if any(key not in allowed for key in value):raise ValueError('invalid_manager_finance')
            if any(type(value.get(k,0)) is not int or not 0 <= value.get(k,0) <= 10**12 for k in ('max_transfer','cash_reserve')):
                raise ValueError('invalid_finance_limits')
            if 'target_sub_id' in value and (not isinstance(value['target_sub_id'],str) or len(value['target_sub_id'])>64):
                raise ValueError('invalid_target_sub_id')
    return config


def monthly(db,ph,month,now):
    """Execute once per company/month, entirely in the settlement transaction.

    Disabled managers produce no entries. The other five managers preserve
    their approved config but cannot mutate the legacy owner-wide clearing.
    """
    holding.ensure(db,ph)
    owners=db.execute('SELECT DISTINCT owner FROM enterprise_settings ORDER BY owner').fetchall()
    applied=0
    for (owner,) in owners:
        inserted=db.execute(_q('INSERT INTO auto_months(owner,month_index) VALUES(%s,%s) ON CONFLICT(owner,month_index) DO NOTHING',ph),(owner,month))
        if inserted.rowcount==0:continue
        entries=db.execute(_q('SELECT object_id,managers FROM enterprise_settings WHERE owner=%s ORDER BY object_id',ph),(owner,)).fetchall()
        for oid,raw in entries:
            config=validate(json.loads(raw or '{}'))
            applied+=sum(1 for rule in config.values() if rule.get('enabled'))
            rule=config.get('finance') or {}
            if not rule.get('enabled'):continue
            dest=rule.get('target_sub_id');limit=rule.get('max_transfer',0);reserve=rule.get('cash_reserve',0)
            if not dest or not limit:continue
            src=holding.root_account(owner)
            available=db.execute(_q('SELECT balance FROM wallets WHERE account=%s',ph),(src,)).fetchone()
            amount=min(limit,max(0,int(available[0]) - reserve)) if available else 0
            if amount<=0:continue
            # Stable UUID makes retries idempotent even if a caller is replayed.
            rid=str(uuid.uuid5(uuid.NAMESPACE_URL,f'finance:{owner}:{oid}:{month}'))
            code,_=holding.transfer(db,ph,owner,src,holding.subsidiary_account(dest),amount,rid,now)
            if code not in (200,201,403):
                # A stale or deleted sub-account must never stop the month.
                # No transfer is made if the transaction was rejected.
                continue
    return applied