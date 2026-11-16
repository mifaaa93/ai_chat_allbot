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


def test_files_cleared_on_new_thread(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", str(tmp_path / "bot.sqlite3"))
    db.init_db()
    conn = db.open_db()
    user = db.get_or_create_user(conn, 7)
    db.add_file(
        conn, 7, user["thread_id"],
        tg_file_id="AgFILE",
        filename="notes.txt",
        kind="document",
        origin="bot",
        tg_message_id=10,
        source_text="hello",
    )
    assert db.list_files(conn, 7, user["thread_id"])[0]["filename"] == "notes.txt"
    old_thread = user["thread_id"]
    user = db.new_thread(conn, 7)
    assert db.list_files(conn, 7, old_thread) == []
    assert db.list_files(conn, 7, user["thread_id"]) == []
    conn.close()


def test_files_prune_keeps_latest(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", str(tmp_path / "bot.sqlite3"))
    monkeypatch.setattr(db, "MAX_STORED_FILES", 3)
    db.init_db()
    conn = db.open_db()
    user = db.get_or_create_user(conn, 8)
    for index in range(5):
        db.add_file(
            conn, 8, user["thread_id"],
            tg_file_id=f"id-{index}",
            filename=f"f{index}.txt",
            kind="document",
            origin="bot",
        )
    names = [row["filename"] for row in db.list_files(conn, 8, user["thread_id"])]
    assert names == ["f2.txt", "f3.txt", "f4.txt"]
    conn.close()
