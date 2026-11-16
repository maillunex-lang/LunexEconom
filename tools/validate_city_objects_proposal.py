"""V2-CITY-DESIGN: deterministic proposal generator and checker (read-only server imports)."""
from __future__ import annotations
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tools/sim/data/city_objects_proposed"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import importlib.util
_gen_spec = importlib.util.spec_from_file_location("world_generator_readonly", ROOT / "server/world/generator.py")
_world_gen = importlib.util.module_from_spec(_gen_spec)
_gen_spec.loader.exec_module(_world_gen)
noise, terrain, zone, radius_at_level, CHUNK_CELLS = (_world_gen.noise, _world_gen.terrain, _world_gen.zone, _world_gen.radius_at_level, _world_gen.CHUNK_CELLS)

def _pairs(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise ValueError("duplicate key: " + k)
        obj[k] = v
    return obj

def _bad_number(s):
    raise ValueError("float or non-integer constant: " + s)

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                      parse_float=_bad_number, parse_constant=_bad_number)

def load_proposal(folder=DATA):
    return {name: read_json(Path(folder) / (name + ".json"))
            for name in ("catalog", "rules", "districts_ufa", "examples")}

def trunk_edges(cities):
    """Mirror core.trunk_edges MST tie-breaker without DB modules."""
    by = {c["id"]: c for c in cities}
    remaining, selected, edges = set(by) - {"ufa"}, {"ufa"}, []
    while remaining:
        d, a, b = min((abs(by[a]["x"] - by[b]["x"]) + abs(by[a]["y"] - by[b]["y"]), a, b)
                      for a in selected for b in remaining)
        edges.append((a, b, d))
        selected.add(b)
        remaining.remove(b)
    return edges

def virtual_road(city, level, x, y, city_map, edges):
    """Reproduce trunks + retained rings + spokes in server.world.core.virtual_road."""
    for a, b, _ in edges:
        ca, cb = city_map[a], city_map[b]
        if (y == ca["y"] and min(ca["x"], cb["x"]) <= x <= max(ca["x"], cb["x"])
            or x == cb["x"] and min(ca["y"], cb["y"]) <= y <= max(ca["y"], cb["y"])):
            return True
    for c in city_map.values():
        active_level = level if c["id"] == city["id"] else 1
        dx, dy = x - c["x"], y - c["y"]
        distance = max(abs(dx), abs(dy))
        if distance > radius_at_level(c["base_radius"], active_level):
            continue
        if dx == 0 or dy == 0 or any(distance == radius_at_level(c["base_radius"], n)
                                    for n in range(1, active_level + 1)):
            return True
    return False

def ufa_district(x, y, city, mapping):
    dx, dy = x - city["x"], y - city["y"]
    distance = max(abs(dx), abs(dy))
    typ = zone(x, y, city["x"], city["y"], city["base_radius"], 6)
    if distance <= 2:
        result = "belaya_naberezhnaya"
    elif typ == "industrial":
        result = "neftyanoy_holm"
    elif dy >= 7 and abs(dy) >= abs(dx):
        result = "yuzhnaya_okraina"
    elif dx > 0 and abs(dx) >= abs(dy):
        result = "centralny_rynok"
    elif dx < 0 and abs(dx) >= abs(dy):
        result = "vokzalny_krug"
    else:
        result = "medovy_kvartal"
    assert result in {item["id"] for item in mapping["districts"]}
    return result

def footprint(obj):
    return {(obj["x"] + i, obj["y"] + j)
            for i in range(obj["width"]) for j in range(obj["height"])}

def generate(city, level, catalog, rules, seed, all_cities, districts,
             occupied=(), reserved=()):
    """Stable proposal, ordered by immutable ring/slot/attempt, no reflow."""
    # Dynamic ownership filters the canonical placement; no alternative candidate is promoted.
    if occupied or reserved:
        blocked = set(occupied) | set(reserved)
        canonical = generate(city,level,catalog,rules,seed,all_cities,districts)
        return [obj for obj in canonical if not footprint(obj) & blocked]
    available = [o for o in catalog["objects"] if o["id"] not in ("city_hall", "bridge", "embankment")]
    mapping = {c["id"]: c for c in all_cities}
    edges = trunk_edges(all_cities)
    result = []
    claimed = set(occupied) | set(reserved)
    chunks_count, chunks_cells = defaultdict(int), defaultdict(int)
    # Mandatory single city hall near city centre. Stable first object at every level.
    hall = next(o for o in catalog["objects"] if o["id"] == "city_hall")
    possible = []
    for dy in range(-6, 7):
        for dx in range(-6, 7):
            x, y = city["x"]+dx, city["y"]+dy
            obj = dict(id=city["id"] + ":1:hall:0", type_id=hall["id"],
                       city_id=city["id"], ring=1, x=x, y=y,
                       width=hall["width"], height=hall["height"],
                       district_id=ufa_district(x,y,city,districts) if city["id"]=="ufa"
                       else "city_center", model_id=hall["model_id"])
            cells=footprint(obj)
            if all(max(abs(px-city["x"]),abs(py-city["y"]))<=12
                   and terrain(seed,px,py)!="water"
                   and not virtual_road(city,1,px,py,mapping,edges)
                   and zone(px,py,city["x"],city["y"],12,1) in hall["zones"]
                   for px,py in cells):
                distance=max(abs(dx),abs(dy))
                possible.append((distance, noise(seed ^ rules["seed_salt"],x,y), x,y,obj,cells))
    if not possible:
        raise ValueError("city hall cannot be placed safely: "+city["id"])
    _, _, _, _, hall_obj, hall_cells = min(possible)
    result.append(hall_obj)
    claimed.update(hall_cells)
    for px,py in hall_cells:
        ck=(px//CHUNK_CELLS,py//CHUNK_CELLS)
        chunks_cells[ck]+=1
    for ck in {(px//CHUNK_CELLS,py//CHUNK_CELLS) for px,py in hall_cells}:
        chunks_count[ck]+=1
    counts_by_type=defaultdict(int)
    counts_by_type["city_hall"]=1
    for ring in range(1, level + 1):
        outer = radius_at_level(city["base_radius"], ring)
        inner = radius_at_level(city["base_radius"], ring - 1) if ring > 1 else -1
        choices = [o for o in available if o["min_level"] <= ring]
        total_weight = sum(o["weight"] for o in choices)
        for slot in range(rules["anchors_per_ring"]):
            for attempt in range(rules["attempts_per_anchor"]):
                key = noise(seed ^ rules["seed_salt"],
                            (city["x"] << 8) ^ ring * 65537 ^ slot,
                            (city["y"] << 8) ^ attempt * 193)
                span = 2 * outer + 1
                x = city["x"] - outer + key % span
                y = city["y"] - outer + (key >> 21) % span
                if not inner < max(abs(x-city["x"]), abs(y-city["y"])) <= outer:
                    continue
                if key % rules["selection_modulus"] >= rules["acceptance_threshold"]:
                    continue
                pick = (key >> 42) % total_weight
                chosen = None
                for item in choices:
                    if pick < item["weight"]:
                        chosen = item
                        break
                    pick -= item["weight"]
                assert chosen is not None
                obj = dict(id=f'{city["id"]}:{ring}:{slot}:{attempt}', type_id=chosen["id"],
                           city_id=city["id"], ring=ring, x=x, y=y,
                           width=chosen["width"], height=chosen["height"],
                           district_id=ufa_district(x,y,city,districts) if city["id"]=="ufa"
                           else ("city_center" if max(abs(x-city["x"]),abs(y-city["y"]))<=2 else "city_area"),
                           model_id=chosen["model_id"])
                cells = footprint(obj)
                if counts_by_type[chosen["id"]] >= rules["max_per_type"][chosen["id"]]:
                    continue
                if cells & claimed:
                    continue
                invalid = False
                for px, py in cells:
                    d = max(abs(px-city["x"]), abs(py-city["y"]))
                    if (not inner < d <= outer or terrain(seed, px, py) == "water"
                        or virtual_road(city, ring, px, py, mapping, edges)
                        or zone(px, py, city["x"], city["y"], city["base_radius"], ring)
                        not in chosen["zones"]):
                        invalid = True
                        break
                if invalid:
                    continue
                touched = defaultdict(int)
                for px, py in cells:
                    touched[(px//CHUNK_CELLS, py//CHUNK_CELLS)] += 1
                if (len(result) >= rules["max_objects_per_city"]
                    or any(chunks_count[ch]+1 > rules["max_objects_per_chunk"]
                           or chunks_cells[ch]+num > rules["max_generated_footprint_cells_per_chunk"]
                           for ch, num in touched.items())):
                    continue
                result.append(obj)
                counts_by_type[chosen["id"]]+=1
                claimed.update(cells)
                for ch, num in touched.items():
                    chunks_count[ch] += 1
                    chunks_cells[ch] += num
    return result

def objects_in_cell(objects, x, y):
    """Same deterministic object references for one global signed cell."""
    return [o for o in objects if (o["x"] <= x < o["x"] + o["width"]
            and o["y"] <= y < o["y"] + o["height"])]

def objects_in_chunk(objects, cx, cy):
    """References are shared across chunk edges, but the object model renders once."""
    lo_x, lo_y = cx * CHUNK_CELLS, cy * CHUNK_CELLS
    return [o for o in objects if (o["x"] < lo_x + CHUNK_CELLS
            and o["x"] + o["width"] > lo_x
            and o["y"] < lo_y + CHUNK_CELLS
            and o["y"] + o["height"] > lo_y)]

def digest(objects):
    return hashlib.sha256(json.dumps(objects,ensure_ascii=False,sort_keys=True,
                                     separators=(",",":")).encode("utf-8")).hexdigest()

def _numbers(value, label, errors):
    if isinstance(value, float):
        errors.append("float: "+label)
    elif isinstance(value, list):
        for i, obj in enumerate(value):
            _numbers(obj, f"{label}[{i}]", errors)
    elif isinstance(value, dict):
        for key, obj in value.items():
            _numbers(obj, f"{label}.{key}", errors)
    elif value is not None and type(value) not in (str, int, bool):
        errors.append("unexpected type: "+label)

def validate(data):
    errors = []
    _numbers(data, "proposal", errors)
    catalog, rules, mapping = data["catalog"], data["rules"], data["districts_ufa"]
    base = read_json(ROOT / "server/data/cities.json")
    m2 = read_json(ROOT / "tools/sim/data/districts_ufa.json")
    city_map = {c["id"]: c for c in base["cities"]}
    edges = trunk_edges(base["cities"])
    types = {}
    for item in catalog["objects"]:
        ident = item["id"]
        if ident in types: errors.append("duplicate object type: "+ident)
        types[ident] = item
        for field in ("width","height","weight","height_m","build_cost_rub","monthly_upkeep_rub"):
            if type(item.get(field)) is not int or item[field] <= 0:
                errors.append(ident+" invalid "+field)
        for field in ("min_level","radius_cells","traffic_points","land_effect_bp","comfort_points","demand_signal"):
            if type(item.get(field)) is not int or item[field] < 0:
                errors.append(ident+" invalid "+field)
        if not 1 <= item["min_level"] <= 6: errors.append(ident+" bad min_level")
        if not item["zones"] or not set(item["zones"]) <= {"center","residential","industrial","free"}:
            errors.append(ident+" bad zones")
        if item["service"] not in ("transport","education","health"):
            errors.append(ident+" unknown service")
        if not item.get("name_ru") or not item.get("model_id"): errors.append(ident+" missing visual id/name")
    if len(types)!=22 or len(catalog["objects"])!=22:
        errors.append("catalog must contain 22 unique types")
    if set(rules["max_per_type"])!=set(types) or rules["max_per_type"]["city_hall"]!=1:
        errors.append("type caps must cover all types and one city hall")
    if any(type(n) is not int or n<0 for n in rules["max_per_type"].values()):
        errors.append("type caps invalid")
    if set(rules["service_kinds"])!={"transport","education","health"}:
        errors.append("service mismatch project 14")
    if rules["city_level_radius"] != [radius_at_level(12,n) for n in range(1,7)]:
        errors.append("wrong radius progression")
    if not (1<=rules["anchors_per_ring"]<=1000 and 1<=rules["attempts_per_anchor"]<=50
            and rules["publish_lead_days"]>=1
            and rules["special_structures"]=="manual_only"):
        errors.append("invalid limits or special structures")
    if (type(rules.get("max_objects_per_city")) is not int or rules["max_objects_per_city"] < 1
        or type(rules.get("max_objects_per_chunk")) is not int or rules["max_objects_per_chunk"] < 1
        or type(rules.get("max_generated_footprint_cells_per_chunk")) is not int
        or rules["max_generated_footprint_cells_per_chunk"] < 1):
        errors.append("invalid hard limits")
    m2_map = {o["id"]:o for o in m2["districts"]}
    district_map = {o["id"]:o for o in mapping["districts"]}
    if len(district_map)!=6 or set(district_map)!=set(m2_map):
        errors.append("M2 districts mismatch")
    if sum(o["pop_permille"] for o in mapping["districts"])!=1000:
        errors.append("M2 population shares must be 1000")
    for key in district_map.keys() & m2_map.keys():
        for field in ("name","type","pop_permille","traffic","appeal_permille","layers_permille"):
            if district_map[key][field] != m2_map[key][field]:
                errors.append("M2 field changed: "+key+"."+field)
    if len(data["examples"]["cities"])!=3:
        errors.append("expected exactly three city examples")
    for example in data["examples"]["cities"]:
        city = city_map.get(example["city_id"])
        if city is None:
            errors.append("unknown city "+example["city_id"])
            continue
        for level in (1,2,3):
            expected = example["levels"].get(str(level))
            if expected is None:
                errors.append("missing level example")
                continue
            objects = generate(city,level,catalog,rules,base["seed"],base["cities"],mapping)
            if objects != generate(city,level,catalog,rules,base["seed"],base["cities"],mapping):
                errors.append("nondeterminism")
            if expected["objects"]!=objects or expected["sha256"]!=digest(objects):
                errors.append("example mismatch "+city["id"]+" L"+str(level))
            if sum(o["type_id"]=="city_hall" for o in objects)!=1:
                errors.append("city hall uniqueness/missing")
            if any(sum(o["type_id"]==tid for o in objects)>cap for tid,cap in rules["max_per_type"].items()):
                errors.append("per-type cap exceeded")
            if len(objects)>rules["max_objects_per_city"]:
                errors.append("city object cap")
            taken, instances, cell_counts = set(), defaultdict(int), defaultdict(int)
            for obj in objects:
                cells = footprint(obj)
                if cells & taken: errors.append("overlapping objects")
                taken.update(cells)
                chunks = set()
                for x,y in cells:
                    dist=max(abs(x-city["x"]),abs(y-city["y"]))
                    if dist>radius_at_level(city["base_radius"],level): errors.append("outside city")
                    if terrain(base["seed"],x,y)=="water": errors.append("water overlap")
                    if virtual_road(city,level,x,y,city_map,edges): errors.append("road overlap")
                    if zone(x,y,city["x"],city["y"],city["base_radius"],level) not in types[obj["type_id"]]["zones"]:
                        errors.append("wrong zone")
                    ch=(x//CHUNK_CELLS,y//CHUNK_CELLS)
                    chunks.add(ch)
                    cell_counts[ch]+=1
                for ch in chunks: instances[ch]+=1
            if any(n>rules["max_objects_per_chunk"] for n in instances.values()):
                errors.append("chunk instances cap")
            if any(n>rules["max_generated_footprint_cells_per_chunk"] for n in cell_counts.values()):
                errors.append("chunk footprint cap")
            if level>1:
                old=example["levels"][str(level-1)]["objects"]
                if objects[:len(old)]!=old: errors.append("growth moved historic objects")
    return errors

def main():
    try:
        errors=validate(load_proposal())
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as error:
        errors=[str(error)]
    if errors:
        for e in errors: print("FAIL:",e)
        return 1
    print("PASS: city objects, 22 types, Ufa M2 districts, 3 cities x 3 levels, integer-only and geometric safety")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
