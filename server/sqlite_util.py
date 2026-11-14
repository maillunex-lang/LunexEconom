"""SQLite helper: connections that are really closed when used as context managers.

`with sqlite3.connect(...) as db:` only commits or rolls back, it never closes the connection, so every request leaked one
connection until the garbage collector ran (hundreds of "ResourceWarning: unclosed database" in test logs and file
descriptors held on a busy server). psycopg's context manager closes; this makes SQLite behave the same way.
"""
import sqlite3


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)    # commit, or roll back on an exception
        finally:
            self.close()


def open_db(path, timeout=10):
    return sqlite3.connect(path, timeout=timeout, factory=ClosingConnection)
