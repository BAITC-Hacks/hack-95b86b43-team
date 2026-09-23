"""Small SQLite store for local demo runs and approved orders."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "workspace.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            # sqlite's own context manager commits/rolls back, but does not
            # close the handle. Explicit closure matters on Windows and for
            # repeated API requests, not just during process shutdown.
            with connection:
                yield connection
        finally:
            connection.close()

    def get_setting(self, key):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def save(self, table, identity, value):
        assert table in {"runs", "orders"}
        with self.connect() as db:
            db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?)", (identity, json.dumps(value, ensure_ascii=False)))

    def get(self, table, identity):
        assert table in {"runs", "orders"}
        with self.connect() as db:
            row = db.execute(f"SELECT payload FROM {table} WHERE id=?", (identity,)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, table):
        assert table in {"runs", "orders"}
        with self.connect() as db:
            rows = db.execute(f"SELECT payload FROM {table} ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def replace_order(self, value, expected_version):
        # A second local server must not bypass optimistic version checks.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM orders WHERE id=?", (value["id"],)).fetchone()
            if not row or json.loads(row[0])["version"] != expected_version:
                return False
            db.execute("UPDATE orders SET payload=? WHERE id=?", (json.dumps(value, ensure_ascii=False), value["id"]))
        return True
