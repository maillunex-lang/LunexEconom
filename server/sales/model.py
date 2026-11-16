"""V2-SALES deterministic, integer-only scoring and max-min clearance.

Formulas intentionally match tools.sim.sales.model; no simulation code imported.
"""
from __future__ import annotations

from server.enterprises.core import integer, MAX


def price_valid(price, reference, min_bp, max_bp, step=1):
    integer(price, 1); integer(reference, 1); integer(min_bp, 1, 10000)
    integer(max_bp, min_bp, 100000); integer(step, 1)
    return (reference * min_bp // 10000 <= price <=
            reference * max_bp // 10000 and price % step == 0)


def supplier_score(price, quality, reliability, distance, cfg,
                   *, port_delivered=None, min_quality=None):
    for item in (price, reliability, distance):
        integer(item)
    integer(quality, 0, 100); integer(reliability, 0, 1000)
    if price == 0:
        raise ValueError('zero external price')
    effective = integer(price + distance * cfg['freight_rub_per_distance_unit'])
    port = (cfg['port_price_rub'] + distance * cfg['freight_rub_per_distance_unit']
            if port_delivered is None else port_delivered)
    threshold = max(cfg['min_acceptable_quality'], min_quality or 0)
    if ((port is not None and effective > port) or quality < threshold):
        return None
    price_score = min(1000, cfg['reference_price_rub'] * 1000 // effective)
    q_score = quality * 10
    d_score = 1000 * (10 + distance) // (10 + 2 * distance)
    value = (price_score * cfg['price_score_weight_bp'] +
             q_score * cfg['quality_score_weight_bp'] +
             reliability * cfg['reliability_score_weight_bp'] +
             d_score * cfg['distance_score_weight_bp']) // 10000
    return value if value >= cfg['score_cutoff'] else None


def allocate_fair(available, requests, cap=None):
    integer(available)
    targets = {str(key): integer(value) for key, value in requests.items()}
    allocations = {key: 0 for key in targets}
    remaining = available
    while remaining:
        active = [key for key in sorted(targets) if allocations[key] < targets[key]]
        if not active:
            break
        step = max(1, remaining // len(active))
        progressed = 0
        for key in active:
            take = min(step, remaining, targets[key] - allocations[key])
            allocations[key] += take
            remaining -= take
            progressed += take
        if not progressed:
            break
    if cap is not None:
        integer(cap)
        if any(value > cap for value in allocations.values()):
            raise ValueError('cap not applied to requests')
    return allocations


def cap_requests_by_owner(available, requests, owners, cap_bp=4000):
    """Apply aggregate holding caps, fairly distributing that cap to its plants."""
    integer(available); integer(cap_bp, 0, 10000)
    cap = available * cap_bp // 10000
    grouped = {}
    for key, demand in requests.items():
        owner = owners[key]
        grouped.setdefault(owner, {})[str(key)] = integer(demand)
    limited = {}
    for own, demands in sorted(grouped.items(), key=lambda item: str(item[0])):
        limited.update(allocate_fair(min(cap, sum(demands.values())), demands))
    return limited
