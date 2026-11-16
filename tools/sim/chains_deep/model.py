"""Standalone 24-month production model; money and units are always integers.

A single plant; upstream suppliers are external finite input streams. Financial
flows distinguish cash outlay and inventory carrying value. Historical events
are deterministic, with no random seed or implicit wall-clock time.
"""
from __future__ import annotations
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'data' / 'deep_chains_proposed'
BP = 10000


def checked(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('expected bounded integer')
    return value


def quality_weighted(inputs, quality, minimum=None):
    """Existing weighted_inputs_or_base (floor rounding), with quality gate."""
    minimum = minimum or {}
    for product, q in minimum.items():
        if checked(quality[product], 1) < checked(q, 1):
            return None
    for key in inputs:
        if not 1 <= checked(quality[key]) <= 100:
            raise ValueError('invalid quality')
    weight = sum(inputs.values())
    return sum(inputs[k] * quality[k] for k in inputs) // weight if weight else 50


def allocate_cost(total, outputs, allocation):
    """Exact integer cost split; remainder goes to lexicographically first ID."""
    checked(total)
    if set(outputs) != set(allocation) or sum(allocation.values()) != BP:
        raise ValueError('output allocation must cover every output and sum to BP')
    for x in outputs.values():checked(x, 1)
    for x in allocation.values():checked(x)
    result = {k: total * allocation[k] // BP for k in sorted(outputs)}
    result[sorted(result)[0]] += total - sum(result.values())
    return result


def load_scenarios():
    return json.loads((DATA / 'scenarios.json').read_text(encoding='utf-8'))


def run_one(scenario, months=24):
    checked(months, 1)
    inventory = {k: checked(q) for k, q in scenario['initial_stock'].items()}
    lots = []  # [product, remaining quantity, capitalized RUB], FIFO; unchanged on recipe switch
    cash = scenario['starting_cash_rub']
    initial_cash = cash
    journal = {'input_cash': 0, 'sales_cash': 0, 'operating_cash': 0, 'disposal_cash': 0}
    cumulative_cost = {'production': 0, 'sold': 0, 'disposed': 0}
    state = {'active_recipe': scenario['initial_recipe'], 'last_switch_day': -999999}
    lost_batches = 0
    history = []
    recipes = {r['id']: r for r in scenario['recipes']}
    for month in range(1, months + 1):
        days = 30  # model month is synthetic; switch rule still enforced per game day
        switches = {int(s['month']):s for s in scenario.get('switches',[])}
        produced = sold = shortage = missed = disposal = month_cost = sales = upkeep = 0
        month_load_bp = 0
        for d in range(days):
            day = (month-1)*30+d
            if d == 0 and month in switches:
                request = switches[month]
                if day-state['last_switch_day'] < 1:
                    raise ValueError('switch cooldown')
                if request['recipe'] not in recipes:
                    raise ValueError('recipe not allowed in building')
                state['active_recipe'] = request['recipe']
                state['last_switch_day'] = day
                # WIP is a separate, not-yet-booked batch, never input stock.
                # For the baseline, switching occurs between completed daily ticks.
                lost_batches += 0
            recipe = recipes[state['active_recipe']]
            for product, qty in scenario['daily_supplies'].items():
                if product in scenario.get('limited_supplies',{}):
                    qty = qty * scenario['limited_supplies'][product] // BP
                # Suppliers deliver only within the receiving inventory ceiling.
                # Excess order is not paid for, never quietly vaporized.
                remaining = max(0, scenario['storage_capacity'] - sum(inventory.values()) - sum(lot[1] for lot in lots))
                qty = min(checked(qty), remaining)
                inventory[product] = inventory.get(product,0) + qty
                paid = qty * scenario['input_prices_rub'].get(product,0)
                cash -= paid; journal['input_cash'] += paid
            # Current plant produces exactly one batch per day; delivery gate is strict.
            possible = min((inventory.get(k,0)//v for k,v in recipe['inputs'].items()), default=1)
            available = max(0, scenario['storage_capacity']-sum(inventory.values())-sum(lot[1] for lot in lots))
            consumed = sum(recipe['inputs'].values())
            made = sum(recipe['outputs'].values())
            if available + consumed < made:
                possible = 0  # all co-products must fit; no implicit destruction
            if possible > 0:
                if quality_weighted(recipe['inputs'],scenario['input_quality'],recipe.get('minimum_input_quality')) is None:
                    possible = 0
            if possible:
                input_value = sum(v*scenario['input_prices_rub'].get(k,0) for k,v in recipe['inputs'].items())
                production_cost = input_value + scenario['wages_per_batch_rub']
                split = allocate_cost(production_cost,recipe['outputs'],recipe['output_cost_allocation_bp'])
                for key,units in recipe['inputs'].items():
                    inventory[key] -= units
                for key,units in sorted(recipe['outputs'].items()):
                    lots.append([key,units,split[key]])
                produced += sum(recipe['outputs'].values())
                month_cost += production_cost
                cumulative_cost['production'] += production_cost
                cash -= scenario['wages_per_batch_rub']
                journal['operating_cash'] += scenario['wages_per_batch_rub']
                month_load_bp += BP
            else:
                missed += 1
                if any(inventory.get(k,0)<v for k,v in recipe['inputs'].items() if k in ('glass_bottle','milk_carton','tin_can','cardboard_box','paper_label')):
                    shortage += 1
            # Sales are fulfilled by FIFO lots at product-specific sale prices.
            demands = scenario['daily_demand']
            for key,limit in sorted(demands.items()):
                demand=limit
                for lot in lots:
                    if lot[0]!=key or demand<=0 or lot[1]<=0:continue
                    qty=min(lot[1],demand)
                    # cost basis remainder stays with remaining lot, last sale takes final RUB
                    value=lot[2]*qty//lot[1] if qty<lot[1] else lot[2]
                    lot[1]-=qty;lot[2]-=value
                    cumulative_cost['sold']+=value
                    demand-=qty;sold+=qty
                    sales += qty*scenario['sale_prices_rub'][key]
            lots=[lot for lot in lots if lot[1]>0]
            # explicit disposal is opt-in and expenses both carrying value + service
            for lot in list(lots):
                if lot[0] in scenario.get('dispose_products',[]):
                    disposal+=lot[1]
                    cumulative_cost['disposed']+=lot[2]
                    cash-=lot[1]*scenario['disposal_fee_rub']
                    journal['disposal_cash']+=lot[1]*scenario['disposal_fee_rub']
                    lots.remove(lot)
        cash+=sales;journal['sales_cash']+=sales
        upkeep=scenario['fixed_upkeep_month_rub'] + scenario['variable_upkeep_month_rub']*month_load_bp//(30*BP)
        cash-=upkeep;journal['operating_cash']+=upkeep
        stock_value=sum(lot[2] for lot in lots)
        # Unspent purchased inputs are carried at acquisition cost (no phantom production profit).
        raw_value=sum(inventory.get(k,0)*scenario['input_prices_rub'].get(k,0) for k in inventory)
        # Mark-to-cost P&L: cash change plus remaining inventory carrying value.
        economic_profit = cash - initial_cash + stock_value + raw_value - sum(q*scenario['input_prices_rub'].get(k,0) for k,q in scenario['initial_stock'].items())
        history.append({'month':month,'active_recipe':state['active_recipe'],'produced_units':produced,'sold_units':sold,'idle_days':missed,'packaging_shortage_days':shortage,'load_bp':month_load_bp//30,'revenue_rub':sales,'upkeep_rub':upkeep,'cost_of_production_rub':month_cost,'disposal_units':disposal,'cash_rub':cash,'finished_stock_units':sum(lot[1] for lot in lots),'raw_stock_units':sum(inventory.values()),'finished_stock_value_rub':stock_value,'economic_profit_to_date_rub':economic_profit})
    total={
        'produced_units':sum(x['produced_units'] for x in history),
        'sold_units':sum(x['sold_units'] for x in history),
        'avg_load_bp':sum(x['load_bp'] for x in history)//months,
        'packaging_shortage_days':sum(x['packaging_shortage_days'] for x in history),
        'idle_days':sum(x['idle_days'] for x in history),
        'disposal_units':sum(x['disposal_units'] for x in history),
        'finished_stock_units':history[-1]['finished_stock_units'],
        'raw_stock_units':history[-1]['raw_stock_units'],
        'cash_rub':cash,
        'profit_rub':history[-1]['economic_profit_to_date_rub'],
        'output_cost_produced_rub':cumulative_cost['production'],
        'output_cost_sold_rub':cumulative_cost['sold'],
        'output_cost_disposed_rub':cumulative_cost['disposed'],
        'output_cost_remaining_rub':sum(lot[2] for lot in lots),
        'journal_sales_rub':journal['sales_cash'],
        'journal_inputs_rub':journal['input_cash'],
        'journal_operating_rub':journal['operating_cash'],
        'journal_disposal_rub':journal['disposal_cash'],
        'switch_lost_batches':lost_batches,
        'inventory_conserved':cumulative_cost['production']==cumulative_cost['sold']+cumulative_cost['disposed']+sum(lot[2] for lot in lots),
        'cash_conserved':cash==initial_cash+journal['sales_cash']-journal['input_cash']-journal['operating_cash']-journal['disposal_cash'],
    }
    return {'totals':total,'history':history}


def run(months=24):
    return {'months':months,'scenarios':{s['id']:run_one(s,months) for s in load_scenarios()}}


def rebuild_golden():
    dest=DATA/'golden_24_months.json'
    dest.write_text(json.dumps(run(),ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return dest


if __name__ == '__main__':
    print(rebuild_golden())
