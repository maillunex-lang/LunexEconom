"""Default -> environment -> PostgreSQL runtime configuration."""
import json
import os


def read_settings(conn, defaults):
    result = dict(defaults)
    for key in defaults:
        env = os.getenv('LUNEX_FLAG_' + key.upper())
        if env is not None:
            result[key] = json.loads(env)
    for key, value in conn.execute('SELECT key,value FROM runtime_config'):
        if key in defaults and type(value) is type(defaults[key]):
            result[key] = value
    return result
