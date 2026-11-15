"""ADR-001: 30 days per month, month rollover 09:00 Asia/Yekaterinburg."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Yekaterinburg')
MONTH_SECONDS = 86400
DAY_SECONDS = 2880
START_YEAR = 2027


def align_epoch(now):
    local = now.astimezone(ZONE)
    anchor = local.replace(hour=9, minute=0, second=0, microsecond=0)
    if local < anchor:
        anchor -= timedelta(days=1)
    return anchor.astimezone(timezone.utc)


def next_epoch(now):
    return align_epoch(now) + timedelta(days=1)


def indices(epoch, now):
    elapsed = max(0, int((now - epoch).total_seconds()))
    return elapsed // DAY_SECONDS, elapsed // MONTH_SECONDS


def apply_ticks(conn, registry, epoch, now):
    day, month = indices(epoch, now)
    if now < epoch:
        return
    for kind, latest in (('daily', day), ('monthly', month)):
        # Running while holding the transaction ensures receipt and side effects commit together.
        with conn.transaction():
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (2026111501 if kind == 'daily' else 2026111502,))
            latest_done = conn.execute('SELECT COALESCE(MAX(tick_index), -1) FROM tick_receipts WHERE kind=%s', (kind,)).fetchone()[0]
            for index in range(latest_done + 1, latest + 1):
                for _, fn in registry.tick_handlers[kind]:
                    fn(conn, index)
                conn.execute('INSERT INTO tick_receipts(kind,tick_index) VALUES(%s,%s)', (kind, index))
