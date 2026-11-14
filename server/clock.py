"""Server game calendar. 1 real day = 1 game month by default (86400 s per month).

The month length is configurable (LUNEX_MONTH_SECONDS) so test servers can run
fast. Changing it never makes the calendar jump: the clock is rebased so that
the current month index stays continuous. Shared by SQLite and PostgreSQL.
"""
import os

DEFAULT_MONTH_SECONDS = 86400
MIN_MONTH_SECONDS = 60
DAYS_PER_MONTH = 30
START_YEAR = 2027

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS world_clock(id INTEGER PRIMARY KEY, epoch BIGINT NOT NULL, month_seconds BIGINT NOT NULL, base_index BIGINT NOT NULL)",
)


def configured_month_seconds():
    try:
        value = int(os.environ.get("LUNEX_MONTH_SECONDS", DEFAULT_MONTH_SECONDS))
    except ValueError:
        return DEFAULT_MONTH_SECONDS
    return max(value, MIN_MONTH_SECONDS)


def month_index(params, now):
    epoch, month_seconds, base_index = params
    return base_index + max(0, now - epoch) // month_seconds


def describe(params, now):
    """Calendar state for `now`. month_index 0 is January of START_YEAR."""
    epoch, month_seconds, _ = params
    index = month_index(params, now)
    elapsed = max(0, now - epoch) % month_seconds
    return {
        "month_index": index,
        "year": START_YEAR + index // 12,
        "month": index % 12 + 1,
        "day": min(DAYS_PER_MONTH, elapsed * DAYS_PER_MONTH // month_seconds + 1),
        "month_seconds": month_seconds,
        "seconds_to_next_month": month_seconds - elapsed,
        "epoch": epoch,
        "base_index": params[2],
        "server_time": now,
    }


def load(db, ph, now, month_seconds=None):
    """Read (creating or rebasing if needed) the clock parameters. Call inside a transaction."""
    month_seconds = month_seconds or configured_month_seconds()
    row = db.execute("SELECT epoch,month_seconds,base_index FROM world_clock WHERE id=1").fetchone()
    if row is None:
        db.execute("INSERT INTO world_clock(id,epoch,month_seconds,base_index) VALUES(1,%s,%s,0)".replace("%s", ph), (now, month_seconds))
        return (now, month_seconds, 0)
    params = (int(row[0]), int(row[1]), int(row[2]))
    if params[1] != month_seconds:
        index = month_index(params, now)
        db.execute("UPDATE world_clock SET epoch=%s,month_seconds=%s,base_index=%s WHERE id=1".replace("%s", ph), (now, month_seconds, index))
        params = (now, month_seconds, index)
    return params


def state(db, ph, now):
    return describe(load(db, ph, now), now)
