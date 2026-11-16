"""Platform accounts, sessions, roles, health and runtime flags."""
from pathlib import Path
from . import api, admin, admin_economy, admin_world, admin_server, admin_catalog, admin_content, admin_releases, admin_audit


def migrations():
    base=Path(__file__).resolve().parents[1] / 'migrations'
    return [base / '202611150900_platform_accounts.sql',base / '202611151000_platform_v201.sql',base / '202611160010_admin_a1.sql',base / '202611160200_admin_a2.sql',base / '202611160201_admin_a2_production.sql',base / '202611160300_platform_refresh_family.sql',base / '202611161100_admin_a3.sql',base / '202611161200_admin_password_change.sql']


def register(registry):
    admin_audit.install_serializer()
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

    # A2 diagnostics, sharing the A1 authentication and role rules.
    registry.route('GET','/admin/economy',admin_economy.economy)
    registry.route('GET','/admin/economy/history',admin_economy.history)
    registry.route('GET','/admin/cities',admin_world.cities)
    # Registry's {id} matcher is numeric; city identifiers are stable text slugs.
    from server.world.core import CITIES
    for city_id in CITIES:
        def city_growth(body, ctx, city_id=city_id):
            return admin_world.growth(body, dict(ctx, path_params={'id':city_id}))
        registry.route('POST',f'/admin/cities/{city_id}/growth',city_growth)
    registry.route('GET','/admin/world/events',admin_world.events)
    registry.route('GET','/admin/parcels',admin_world.parcels)
    registry.route('GET','/admin/server',admin_server.server)
    registry.route('GET','/admin/ticks',admin_server.ticks)
    registry.route('GET','/admin/errors',admin_server.errors)
    registry.route('GET','/admin/alerts',admin_server.alerts)
    # A3 catalog, announcements, release metadata and audit downloads.
    registry.route('GET','/admin/catalog',admin_catalog.catalog)
    registry.route('POST','/admin/catalog/preview',admin_catalog.preview)
    registry.route('POST','/admin/catalog/apply',admin_catalog.apply)
    registry.route('POST','/admin/catalog/rollback',admin_catalog.rollback)
    registry.route('GET','/admin/catalog/revisions',admin_catalog.revisions)
    registry.route('GET','/admin/announcements',admin_content.list_admin)
    registry.route('POST','/admin/announcements',admin_content.create)
    registry.route('POST','/admin/announcements/{id}/deactivate',admin_content.deactivate)
    registry.route('GET','/announcements',admin_content.public)
    registry.route('GET','/admin/releases',admin_releases.releases)
    registry.route('GET','/admin/audit/export',admin_audit.export)
    registry.tick('daily','admin_production',admin_economy.capture_production,order=41)
    registry.tick('daily','admin_daily_stats',admin_economy.snapshot,order=1000)
    registry.tick('daily','admin_error_sync',admin_server.record_tick_errors,order=1001)
