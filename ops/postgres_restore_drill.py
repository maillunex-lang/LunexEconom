#!/usr/bin/env python3
"""Offline PostgreSQL backup restore drill, restricted to disposable databases.

Never uses the project's production connection defaults. Requires an explicit
test DSN and a separate disposable database name with a safety prefix.
"""
import argparse
import os
import re
import subprocess
import sys
from urllib.parse import urlsplit

SAFE_DB = re.compile(r"^lunex_restore_test_[a-z0-9_]{1,40}$")


def run_drill(backup, admin_dsn, target, *, runner=subprocess.run):
    if not SAFE_DB.fullmatch(target):
        raise ValueError("target must begin with lunex_restore_test_")
    parsed = urlsplit(admin_dsn)
    if parsed.scheme != "postgresql" or parsed.hostname not in ("localhost", "127.0.0.1", "::1") or parsed.port is None or parsed.port == 15439 or parsed.path != "/lunex_restore_admin":
        raise ValueError("explicit isolated loopback test cluster DSN required (not production port)")
    if not os.path.isfile(backup) or os.path.getsize(backup) == 0:
        raise ValueError("backup missing or empty")
    # The operator-provided admin DSN must point at a disposable test cluster.
    # This script does not create or drop databases: provisioning is separate.
    env = os.environ.copy()
    env["PGCONNECT_TIMEOUT"] = "5"
    check = runner(["psql", admin_dsn, "-X", "-v", "ON_ERROR_STOP=1",
                    "-Atc", "SELECT current_database(), inet_server_port()"],
                   env=env, capture_output=True, text=True, check=True, timeout=15)
    if check.stdout.strip() != "lunex_restore_admin|" + str(parsed.port):
        raise ValueError("admin DSN must connect to lunex_restore_admin database")
    # Restore only to the explicit disposable target, never via embedded backup ownership.
    runner(["pg_restore", "--exit-on-error", "--no-owner", "--no-acl",
            "--dbname=" + admin_dsn.rsplit("/", 1)[0] + "/" + target, backup],
           env=env, check=True, timeout=180)
    result = runner(["psql", admin_dsn.rsplit("/", 1)[0] + "/" + target,
                     "-X", "-v", "ON_ERROR_STOP=1", "-Atc",
                     "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"],
                    env=env, capture_output=True, text=True, check=True, timeout=15)
    count = int(result.stdout.strip())
    if count < 1:
        raise ValueError("restore produced no public tables")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--admin-dsn", required=True,
                        help="isolated test cluster DSN pointing to lunex_restore_admin")
    parser.add_argument("--target", required=True,
                        help="pre-created empty DB named lunex_restore_test_*")
    args = parser.parse_args()
    count = run_drill(args.backup, args.admin_dsn, args.target)
    print("Restore verified in disposable DB: %d public tables" % count)


if __name__ == "__main__":
    main()
