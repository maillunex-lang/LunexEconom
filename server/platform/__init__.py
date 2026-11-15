"""Platform accounts, sessions, roles, health and runtime flags."""
from pathlib import Path
from . import api, admin


def migrations():
    return [Path(__file__).resolve().parents[1] / 'migrations' / '202611150900_platform_accounts.sql', Path(__file__).resolve().parents[1] / 'migrations' / '202611151000_platform_v201.sql']


def register(registry):
    registry.route('GET', '/health', api.health)
    registry.route('POST', '/auth/register', api.register)
    registry.route('POST', '/auth/login', api.login)
    registry.route('GET', '/auth/me', api.me)
    registry.route('GET', '/me', api.me)
    registry.route('POST', '/auth/refresh', api.refresh)
    registry.route('POST', '/auth/logout', api.logout)
    registry.route('GET', '/config', api.config)
    registry.flag('registration_enabled', True)
    registry.route('GET','/admin/overview',admin.overview)
    registry.route('GET','/admin/flags',admin.flags)
    registry.route('GET','/admin/settings',admin.get_settings)
    registry.route('POST','/admin/settings',admin.update_settings)
    registry.route('GET','/admin/revisions',admin.revisions)
    registry.route('POST','/admin/revisions/rollback',admin.undo)
    registry.route('GET','/admin/audit',admin.audit)
    registry.route('POST','/admin/accounts/block',admin.block)
