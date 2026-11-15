"""Platform accounts, sessions, roles, health and runtime flags."""
from pathlib import Path
from . import api, admin


def migrations():
    base=Path(__file__).resolve().parents[1] / 'migrations'
    return [base / '202611150900_platform_accounts.sql',base / '202611151000_platform_v201.sql',base / '202611160010_admin_a1.sql']


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
    registry.flag('support_compensation_limit', 100000, 0, 1000000000)
    registry.route('POST','/admin/login',admin.login)
    registry.route('POST','/admin/logout',admin.logout)
    registry.route('POST','/admin/password',admin.password)
    registry.route('GET','/admin/overview',admin.overview)
    registry.route('GET','/admin/flags',admin.flags)
    registry.route('GET','/admin/settings',admin.get_settings)
    registry.route('POST','/admin/settings',admin.update_settings)
    registry.route('GET','/admin/revisions',admin.revisions)
    registry.route('POST','/admin/revisions/rollback',admin.undo)
    registry.route('GET','/admin/audit',admin.audit)
    registry.route('GET','/admin/players',admin.players)
    registry.route('GET','/admin/players/{id}',admin.player_detail)
    registry.route('POST','/admin/players/{id}/block',admin.block_player)
    registry.route('POST','/admin/players/{id}/unblock',admin.unblock_player)
    registry.route('POST','/admin/players/{id}/compensate',admin.compensate)
    registry.route('POST','/admin/sessions/revoke',admin.revoke_sessions)
    registry.route('POST','/admin/roles',admin.roles)
    registry.route('POST','/admin/accounts/block',admin.block)
