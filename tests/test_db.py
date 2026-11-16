from pathlib import Path

import db


def test_history_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", str(tmp_path / "bot.sqlite3"))
    db.init_db()
    conn = db.open_db()
    user = db.get_or_create_user(conn, 42)
    db.add_message(conn, 42, user["thread_id"], "user", "hi")
    db.add_message(conn, 42, user["thread_id"], "assistant", "hello")
    history = db.load_history(conn, 42, user["thread_id"])
    assert [item["role"] for item in history] == ["user", "assistant"]
    user = db.new_thread(conn, 42)
    assert db.load_history(conn, 42, user["thread_id"]) == []
    conn.close()
