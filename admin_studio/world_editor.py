"""Draft-only world editor. No direct access to live economy or game database."""
import json
import re
import sqlite3
import time

BUILDINGS = {
    "school": (3, 2), "hospital": (3, 3), "park": (2, 2),
    "farm": (2, 2), "mine": (2, 3), "factory": (3, 2),
    "warehouse": (3, 3),
}
MUNICIPAL = {"school", "hospital", "park"}
MAX_COORD = 10000
DEFAULTS = {"population": 200, "profit_tax": 13, "property_tax": 2.2,
            "month_seconds": 86400, "growth_per_month": 0.002}

class WorldDrafts:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS draft_cities(
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, settings TEXT NOT NULL,
                    updated INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS draft_buildings(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    city_id TEXT NOT NULL REFERENCES draft_cities(id),
                    kind TEXT NOT NULL, owner TEXT NOT NULL, x INTEGER NOT NULL, y INTEGER NOT NULL,
                    UNIQUE(city_id,x,y,kind));
                CREATE INDEX IF NOT EXISTS draft_buildings_city ON draft_buildings(city_id);
            """)

    def cities(self):
        with self.store.connect() as db:
            return [{"id": row["id"], "title": row["title"],
                     "settings": json.loads(row["settings"])}
                    for row in db.execute("SELECT * FROM draft_cities ORDER BY id")]

    def city(self, city_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM draft_cities WHERE id=?", (city_id,)).fetchone()
            if row is None:
                raise ValueError("city_not_found")
            return {"id": row["id"], "title": row["title"],
                    "settings": json.loads(row["settings"]),
                    "buildings": [dict(x) for x in db.execute(
                        "SELECT id,kind,owner,x,y FROM draft_buildings WHERE city_id=? ORDER BY id",
                        (city_id,))]}

    def save_city(self, city_id, title, settings):
        if not isinstance(city_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,39}", city_id):
            raise ValueError("invalid_city_id")
        if not isinstance(title, str) or not 1 <= len(title) <= 80:
            raise ValueError("invalid_city_title")
        if not isinstance(settings, dict) or set(settings) != set(DEFAULTS):
            raise ValueError("invalid_settings")
        for key in DEFAULTS:
            value = settings[key]
            if type(value) not in (int, float) or not (value == value):
                raise ValueError("invalid_" + key)
        if type(settings["population"]) is not int or not 0 <= settings["population"] <= 10000000:
            raise ValueError("invalid_population")
        if not 5 <= settings["profit_tax"] <= 25 or not 0 <= settings["property_tax"] <= 2.2:
            raise ValueError("invalid_taxes")
        if type(settings["month_seconds"]) is not int or not 60 <= settings["month_seconds"] <= 2592000:
            raise ValueError("invalid_month_seconds")
        if not -0.05 <= settings["growth_per_month"] <= 0.05:
            raise ValueError("invalid_growth")
        with self.store.connect() as db:
            db.execute("INSERT INTO draft_cities(id,title,settings,updated) VALUES(?,?,?,?) "
                       "ON CONFLICT(id) DO UPDATE SET title=excluded.title,settings=excluded.settings,updated=excluded.updated",
                       (city_id, title, json.dumps(settings), int(time.time())))
            db.execute("INSERT INTO audit(at,action,subject,details) VALUES(?,?,?,?)",
                       (int(time.time()), "draft_city_save", city_id, "settings"))

    def place(self, city_id, kind, x, y):
        if kind not in MUNICIPAL or type(x) is not int or type(y) is not int:
            raise ValueError("only_municipal_buildings_allowed")
        w, h = BUILDINGS[kind]
        if min(x, y) < -MAX_COORD or max(x + w - 1, y + h - 1) > MAX_COORD:
            raise ValueError("outside_world")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM draft_cities WHERE id=?", (city_id,)).fetchone() is None:
                raise ValueError("city_not_found")
            for row in db.execute("SELECT kind,x,y FROM draft_buildings WHERE city_id=?", (city_id,)):
                rw, rh = BUILDINGS[row["kind"]]
                if x < row["x"] + rw and x + w > row["x"] and y < row["y"] + rh and y + h > row["y"]:
                    raise ValueError("occupied")
            cur = db.execute("INSERT INTO draft_buildings(city_id,kind,owner,x,y) VALUES(?,?,?,?,?)",
                             (city_id, kind, "city", x, y))
            db.execute("INSERT INTO audit(at,action,subject,details) VALUES(?,?,?,?)",
                       (int(time.time()), "draft_place", city_id, json.dumps({"kind":kind,"x":x,"y":y})))
            return {"id": cur.lastrowid, "kind": kind, "owner": "city", "x": x, "y": y}

    def remove(self, city_id, building_id):
        if type(building_id) is not int or building_id <= 0:
            raise ValueError("invalid_building_id")
        with self.store.connect() as db:
            cur = db.execute("DELETE FROM draft_buildings WHERE id=? AND city_id=?", (building_id, city_id))
            if cur.rowcount != 1:
                raise ValueError("building_not_found")
            db.execute("INSERT INTO audit(at,action,subject,details) VALUES(?,?,?,?)",
                       (int(time.time()), "draft_remove", city_id, str(building_id)))

    def forecast(self, city_id, months):
        if type(months) is not int or not 1 <= months <= 120:
            raise ValueError("invalid_months")
        city = self.city(city_id)
        settings = city["settings"]
        # Clearly labeled simplified demographic preview, not authoritative economy simulation.
        population = settings["population"]
        rate = settings["growth_per_month"]
        trend = []
        for month in range(1, months + 1):
            population = max(0, round(population * (1 + rate)))
            trend.append({"month": month, "population": population})
        return {"mode": "illustrative_draft_only", "city_id": city_id,
                "months": months, "trend": trend, "final_population": population,
                "note": "Прогноз только по росту населения; налоги и денежная экономика не моделируются"}

    def export(self, city_id):
        city = self.city(city_id)
        return {"schema": 1, "mode": "review_only", "city": city,
                "note": "Not an executable command. Must be reviewed and applied through a future authenticated game-server API."}
