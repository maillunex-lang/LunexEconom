"""Low-overhead authenticated player presence with five-minute online window."""
import time

WINDOW = 300
WRITE_INTERVAL = 30

def ensure(db, ph):
    db.execute("""CREATE TABLE IF NOT EXISTS presence(
        player TEXT PRIMARY KEY, last_seen BIGINT NOT NULL,
        version TEXT NOT NULL, city TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS presence_samples(
        bucket BIGINT PRIMARY KEY, concurrent INTEGER NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS presence_seen ON presence(last_seen)")

def touch(db, ph, player, version="", city="", now=None):
    now = int(time.time()) if now is None else int(now)
    if not isinstance(player, str) or not player or len(player) > 40:
        return False
    version = str(version)[:32]
    city = str(city)[:64]
    sql = """INSERT INTO presence(player,last_seen,version,city) VALUES(%s,%s,%s,%s)
      ON CONFLICT(player) DO UPDATE SET last_seen=excluded.last_seen,
      version=excluded.version,city=excluded.city
      WHERE presence.last_seen<=excluded.last_seen-%s""".replace("%s", ph)
    result = db.execute(sql, (player, now, version, city, WRITE_INTERVAL))
    return result.rowcount > 0

def summary(db, ph, now=None):
    now = int(time.time()) if now is None else int(now)
    cutoff = now - WINDOW
    count = db.execute("SELECT COUNT(*) FROM presence WHERE last_seen>%s".replace("%s", ph), (cutoff,)).fetchone()[0]
    versions = [{"version": ver, "players": int(n)} for ver, n in
                db.execute("SELECT version,COUNT(*) FROM presence WHERE last_seen>%s GROUP BY version ORDER BY COUNT(*) DESC".replace("%s", ph), (cutoff,)).fetchall()]
    cities = [{"city": city or "не указан", "players": int(n)} for city, n in
              db.execute("SELECT city,COUNT(*) FROM presence WHERE last_seen>%s GROUP BY city ORDER BY COUNT(*) DESC".replace("%s", ph), (cutoff,)).fetchall()]
    peak_row = db.execute("SELECT COALESCE(MAX(concurrent),0) FROM presence_samples WHERE bucket>%s".replace("%s", ph), (now - 86400,)).fetchone()
    return {"online": int(count), "peak_24h": max(int(count), int(peak_row[0])), "versions": versions, "cities": cities}

def sample(db, ph, now=None):
    now = int(time.time()) if now is None else int(now)
    bucket = now // 300 * 300
    online = int(db.execute("SELECT COUNT(*) FROM presence WHERE last_seen>%s".replace("%s", ph), (now-WINDOW,)).fetchone()[0])
    db.execute("""INSERT INTO presence_samples(bucket,concurrent) VALUES(%s,%s)
      ON CONFLICT(bucket) DO UPDATE SET concurrent=CASE
      WHEN presence_samples.concurrent<excluded.concurrent THEN excluded.concurrent
      ELSE presence_samples.concurrent END""".replace("%s", ph), (bucket, online))
    # Bounded retention: delete at most once per hour, using the same bucket.
    if bucket % 3600 == 0:
        db.execute("DELETE FROM presence_samples WHERE bucket<%s".replace("%s", ph), (now-8*86400,))
    return online

def history(db, ph, now=None):
    now = int(time.time()) if now is None else int(now)
    rows = db.execute("SELECT bucket,concurrent FROM presence_samples WHERE bucket>%s ORDER BY bucket".replace("%s", ph),
                      (now-86400,)).fetchall()
    return [{"at": int(t), "online": int(n)} for t, n in rows]

def players(db, ph, now=None):
    now = int(time.time()) if now is None else int(now)
    rows = db.execute("SELECT player,last_seen,version,city FROM presence WHERE last_seen>%s ORDER BY last_seen DESC LIMIT 250".replace("%s", ph),
                      (now-WINDOW,)).fetchall()
    return [{"username": p, "last_seen": int(t), "version": v, "city": c}
            for p,t,v,c in rows]
