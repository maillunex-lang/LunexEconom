"""Stable, actionable HQ alerts derived from existing economic and world data."""
import economy


def collect(owner, enterprise_rows, status, loan_balance, contracts, clock_month, stock, capacity, market=None):
    out = []
    def add(level, code, text, obj=None):
        value = {'level': level, 'code': code, 'text': text, 'object_id': obj['id'] if obj else None,
                 'x': obj['x'] if obj else None, 'y': obj['y'] if obj else None}
        out.append(value)
        if obj is not None:
            obj['alerts'].append(code)
    for key, code, label in (('wages_owed','wage_arrears','Просрочка зарплаты'),
                             ('tax_owed','tax_arrears','Просрочка налогов'),
                             ('input_owed','input_arrears','Долг за сырьё'),
                             ('maint_owed','maintenance_arrears','Просрочка содержания')):
        if int(status.get(key, 0)) > 0:
            add('critical' if key in ('wages_owed','tax_owed') else 'warning', code, label)
    if loan_balance and int(status.get('missed', 0)):
        add('warning', 'loan_interest', 'Кредитные проценты требуют внимания')
    if int(status.get('missed', 0)) >= max(1, int(status.get('bankrupt_after', 3)) - 1):
        add('critical', 'bankruptcy_risk', 'Угроза банкротства')
    if capacity and sum(max(0,int(q)) for q in stock.values()) >= capacity:
        add('warning', 'warehouse_full', 'Склад заполнен')
    for obj in enterprise_rows:
        if obj['construction_stage'] == 'complete' and obj.get('recently_completed'):
            add('info', 'construction_complete', 'Строительство завершено', obj)
        spec = obj.get('recipe') or {}
        if obj['status'] == 'working':
            for good, required in spec.get('inputs', {}).items():
                if int(stock.get(good, 0)) < int(required):
                    add('warning', 'no_input:' + good, 'Не хватает сырья: ' + good, obj)
    for contract in contracts:
        if int(contract['end_month']) <= clock_month + 1:
            add('info', 'contract_expiring', 'Договор скоро истекает')
    return out[:40]