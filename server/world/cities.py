"""Immutable city descriptors, verified before database startup."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError, SchemaError

DATA = Path(__file__).resolve().parents[1] / 'data' / 'cities.json'
EXPECTED = (
    'ufa','sterlitamak','salavat','neftekamsk','oktyabrsky','beloretsk',
    'sibay','meleuz','kumertau','tuymazy','ishimbay','birsk','belebey',
    'dyurtyuli','baymak','uchaly','davlekanovo','blagoveshchensk','agidel','yanaul',
)
INDEX = {'construction','land','housing','salary','traffic'}
POS = {'type':'integer','minimum':1}
IDENT = {'type':'string','pattern':'^[a-z][a-z0-9_]*$'}
SCHEMA = {
    'type':'object','required':['seed','cities'],'additionalProperties':False,
    'properties':{
        'seed':{'type':'integer','minimum':0},
        'cities':{'type':'array','minItems':20,'maxItems':20,'items':{
            'type':'object','additionalProperties':False,
            'required':['id','name','latitude_e6','longitude_e6','x','y',
                        'population_estimate','specialization','base_radius','indices_bp','balance'],
            'properties':{
                'id':IDENT,'name':{'type':'string','minLength':1},
                'latitude_e6':{'type':'integer','minimum':50000000,'maximum':60000000},
                'longitude_e6':{'type':'integer','minimum':50000000,'maximum':62000000},
                'x':{'type':'integer'},'y':{'type':'integer'},
                'population_estimate':POS,'specialization':IDENT,
                'base_radius':POS,'balance':{'const':'draft'},
                'indices_bp':{'type':'object','required':sorted(INDEX),
                              'additionalProperties':False,
                              'properties':{key:{'type':'integer','minimum':1,'maximum':100000} for key in INDEX}}
            }
        }}
    }
}


def load_cities(path=DATA):
    def no_duplicate_keys(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f'duplicate city JSON key: {key}')
            obj[key] = value
        return obj
    try:
        doc=json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=no_duplicate_keys,
                       parse_constant=lambda v: (_ for _ in ()).throw(ValueError(f'Invalid numeric value {v}')))
        Draft202012Validator(SCHEMA).validate(doc)
        cities=doc['cities']
        ids=[city['id'] for city in cities]
        if set(ids) != set(EXPECTED) or len(ids) != len(set(ids)):
            raise ValueError('City IDs must match the exact 20 GDD-02 cities without duplicates')
        if len({(c['x'], c['y']) for c in cities}) != len(cities):
            raise ValueError('Duplicate world grid city centers')
        if doc['seed'] == 0:
            raise ValueError('World seed cannot be zero')
        if (cities[0]['id'],cities[0]['x'],cities[0]['y']) != ('ufa',0,0):
            raise ValueError('Ufa must be at the world origin')
        if any(value != 10000 for value in cities[0]['indices_bp'].values()):
            raise ValueError('Ufa reference indices must equal 10000')
        return doc
    except (OSError,ValueError,TypeError,ValidationError,SchemaError) as e:
        raise ValueError(f'Invalid server/data/cities.json: {e}') from e
