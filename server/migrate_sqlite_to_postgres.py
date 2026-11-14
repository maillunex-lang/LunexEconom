"""One-time SQLite -> PostgreSQL copy. Run only while the old game service is stopped."""
import os
import sqlite3
import postgres_db

ACCOUNTS = os.environ.get("LUNEX_AUTH_DB", "/home/gamedev/projects/LunexEconom-runtime/accounts.sqlite3")
WORLD = os.environ.get("LUNEX_WORLD_DB", "/home/gamedev/projects/LunexEconom-server/world.sqlite3")
TABLES = {
 "accounts": {
  "users":("id","username","email","salt","password_hash","created_at"),
  "sessions":("token_hash","user_id","expires_at")
 },
 "world": {
  "buildings":("id","owner","kind","x","y","created"),
  "cells":("x","y","object_id"),
  "chunks":("cx","cy","version"),
  "events":("seq","cx","cy","version","kind","payload"),
  "commands":("owner","request_id","response")
 }
}

def migrate():
    postgres_db.init()
    with postgres_db.connect() as pg:
        # Abort on any preexisting destination data; never silently overwrite accounts.
        for tables in TABLES.values():
            for name in tables:
                if pg.execute("SELECT 1 FROM "+name+" LIMIT 1").fetchone():
                    raise RuntimeError("Destination table is not empty: "+name)
        for source, path in (("accounts",ACCOUNTS),("world",WORLD)):
            with sqlite3.connect(path) as sqlite:
                for name,cols in TABLES[source].items():
                    rows=sqlite.execute("SELECT "+",".join(cols)+" FROM "+name).fetchall()
                    if rows:
                        sql="INSERT INTO "+name+"("+",".join(cols)+") VALUES("+",".join(["%s"]*len(cols))+")"
                        with pg.cursor() as cursor:cursor.executemany(sql,rows)
                    print(name, len(rows))
        for name,col in (("users","id"),("events","seq")):
            pg.execute("SELECT setval(pg_get_serial_sequence(%s,%s), COALESCE((SELECT MAX("+col+") FROM "+name+"),1), EXISTS(SELECT 1 FROM "+name+"))",(name,col))
        pg.commit()
        print("MIGRATION_COMPLETE")

if __name__=="__main__":
    migrate()
