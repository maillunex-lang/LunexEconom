"""Single JSON data source and schema checks."""
from pathlib import Path
import json
from jsonschema import validate

ROOT = Path(__file__).resolve().parents[1] / 'data'
SCHEMA = ROOT / 'schema.json'

def load(name):
    if name not in ('products', 'recipes', 'buildings'):
        raise ValueError('Unknown catalog')
    data = json.loads((ROOT / (name + '.json')).read_text())
    validate(data, json.loads(SCHEMA.read_text()))
    return data

def migrations(): return []

def register(registry):
    def catalog(body, ctx):
        return 200, {name: load(name) for name in ('products', 'recipes', 'buildings')}
    registry.route('GET', '/catalog', catalog)
