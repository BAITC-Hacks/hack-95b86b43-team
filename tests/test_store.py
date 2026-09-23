import sqlite3

import pytest

from backend.app.core.store import Store


def test_operations_release_database_handles(tmp_path, monkeypatch):
    # Retain connection references so garbage collection cannot accidentally
    # make this pass. Every public operation must release its own handle.
    opened = []
    real_connect = sqlite3.connect

    def tracked_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    store = Store(tmp_path / "runtime")
    store.set_setting("dataset", {"id": "demo"})
    assert store.get_setting("dataset") == {"id": "demo"}
    store.save("orders", "order-1", {"id": "order-1", "version": 1})
    assert store.get("orders", "order-1")["version"] == 1
    assert len(store.all("orders")) == 1
    assert store.replace_order({"id": "order-1", "version": 2}, 1)
    assert not store.replace_order({"id": "order-1", "version": 3}, 1)
    assert store.get("orders", "order-1")["version"] == 2

    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")

    # Windows rejects moving/removing a SQLite file while leaked handles are
    # open. This is also a practical guard for clean test/demo restarts.
    renamed = store.path.with_name("closed-database.sqlite3")
    store.path.rename(renamed)
    renamed.unlink()


def test_failed_transaction_rolls_back_and_closes(tmp_path, monkeypatch):
    store = Store(tmp_path / "runtime")
    opened = []
    real_connect = sqlite3.connect

    def tracked_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    with pytest.raises(RuntimeError, match="interrupted"):
        with store.connect() as connection:
            connection.execute("INSERT INTO settings VALUES (?, ?)", ("unfinished", "{}"))
            raise RuntimeError("interrupted")

    assert store.get_setting("unfinished") is None
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
