"""Operator-only developer grants. Never expose these functions as HTTP routes.

Grants live in a separate table so existing SQLite and PostgreSQL user schemas
remain untouched. A grant is effective only for an existing, unbanned account.
"""
import argparse
import time
import auth

def ensure(db):
    db.execute("CREATE TABLE IF NOT EXISTS dev_roles (username TEXT PRIMARY KEY, granted_at BIGINT NOT NULL)")

def set_developer(username, enabled, db=None):
    owned = db is None
    db = db or auth._db()
    try:
        ensure(db)
        ph = auth._ph()
        row = db.execute("SELECT username FROM users WHERE username=" + ph, (username,)).fetchone()
        if row is None:
            raise ValueError("account_not_found")
        if enabled:
            db.execute("INSERT INTO dev_roles(username,granted_at) VALUES(" + ph + "," + ph + ") ON CONFLICT(username) DO UPDATE SET granted_at=excluded.granted_at", (row[0], int(time.time())))
        else:
            db.execute("DELETE FROM dev_roles WHERE username=" + ph, (row[0],))
        db.commit()
    finally:
        if owned:
            db.close()

def is_developer(username, db=None):
    owned = db is None
    db = db or auth._db()
    try:
        ensure(db)
        if auth._active_ban(db, username) is not None:
            return False
        row = db.execute("SELECT 1 FROM dev_roles d JOIN users u ON u.username=d.username WHERE d.username=" + auth._ph(), (username,)).fetchone()
        return row is not None
    finally:
        if owned:
            db.close()

def list_developers(db=None):
    owned = db is None
    db = db or auth._db()
    try:
        ensure(db)
        return [row[0] for row in db.execute("SELECT d.username FROM dev_roles d JOIN users u ON u.username=d.username ORDER BY d.username").fetchall()]
    finally:
        if owned:
            db.close()

def main(argv=None):
    parser = argparse.ArgumentParser(description="Local operator-only developer role management")
    parser.add_argument("command", choices=("grant-dev", "revoke-dev", "list-dev"))
    parser.add_argument("username", nargs="?")
    args = parser.parse_args(argv)
    if args.command == "list-dev":
        for username in list_developers():
            print(username)
        return
    if not args.username:
        parser.error("username required")
    set_developer(args.username, args.command == "grant-dev")
    print("role updated")

if __name__ == "__main__":
    main()
