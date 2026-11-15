"""Platform accounts, sessions, roles, health and runtime flags."""
from pathlib import Path
from . import api


def migrations():
    return [Path(__file__).resolve().parents[1] / 'migrations' / '202611150900_platform_accounts.sql']


def register(registry):
    registry.route('GET', '/health', api.health)
    registry.route('POST', '/auth/register', api.register)
    registry.route('POST', '/auth/login', api.login)
    registry.route('GET', '/auth/me', api.me)
    registry.route('GET', '/config', api.config)
    registry.flag('registration_enabled', True)
