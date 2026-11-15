"""Check 20 city descriptors and deterministic terrain vectors without a database."""
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.world.cities import load_cities
from server.world import core
from server.world.generator import noise, terrain, zone, radius_at_level


def validate():
    doc=load_cities()
    if len(doc['cities'])!=20:
        raise ValueError('world must have exactly 20 cities')
    expected=Path(__file__).resolve().parents[1]/'server/tests/vectors/world_seed_v1.json'
    vector=json.loads(expected.read_text(encoding='utf-8'))
    if vector['seed']!=core.SEED:
        raise ValueError('seed mismatch')
    for test in vector['cells']:
        x,y=test['x'],test['y']
        if terrain(vector['seed'],x,y)!=test['terrain'] or noise(vector['seed'],x,y)!=test['noise']:
            raise ValueError(f'world terrain vector mismatch at ({x},{y})')
    for test in vector['zones']:
        if zone(test['x'],test['y'],0,0,12,test['level'])!=test['zone']:
            raise ValueError('world zoning vector mismatch')
    if [radius_at_level(12,n) for n in range(1,7)]!=vector['radii']:
        raise ValueError('world growth radius vector mismatch')
    print(f'World OK: {len(doc["cities"])} cities, {len(vector["cells"])} terrain vectors, '
          f'{len(vector["zones"])} zoning vectors; balance=draft')


if __name__=='__main__':
    try:
        validate()
    except Exception as exc:
        raise SystemExit(f'ERROR: {exc}')
