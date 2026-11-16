"""Служебные команды на сервере: python -m portal.manage set-password <логин> (пароль вводится скрытно, не передаётся аргументом)."""
import getpass
import os
import sys

from . import auth, db

DB = os.environ.get("PORTAL_DB", "/var/lib/createportal/portal.sqlite")


def main(argv):
    if len(argv) >= 3 and argv[1] == "set-password":
        pw = getpass.getpass("Пароль (не короче 14 символов): ")
        if pw != getpass.getpass("Повторите: "):
            print("не совпали")
            return 1
        conn = db.connect(DB)
        auth.set_password(conn, argv[2], pw)
        print("пароль задан, все сессии сброшены")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
