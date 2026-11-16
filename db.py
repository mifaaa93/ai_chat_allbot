"""SQLite storage for users, threads and messages."""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from config import CVC_MODEL, DATABASE_PATH, HISTORY_LIMIT, ROOT

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    model TEXT NOT NULL,
    reasoning TEXT NOT NULL DEFAULT 'off',
    style TEXT NOT NULL DEFAULT 'normal',
    image_quality TEXT NOT NULL DEFAULT 'low',
    thread_id TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(user_id, thread_id, id);
"""


def db_path() -> Path:
    path = Path(DATABASE_PATH)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with closing(open_db()) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def _new_thread() -> str:
    return uuid.uuid4().hex


def get_or_create_user(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        return row
    now = time.time()
    conn.execute(
        "INSERT INTO users (user_id, model, reasoning, style, image_quality, thread_id, created_at) "
        "VALUES (?, ?, 'off', 'normal', 'low', ?, ?)",
        (user_id, CVC_MODEL, _new_thread(), now),
    )
    conn.commit()
    return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def update_user(conn: sqlite3.Connection, user_id: int, **fields) -> sqlite3.Row:
    get_or_create_user(conn, user_id)
    allowed = {"model", "reasoning", "style", "image_quality", "thread_id"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if updates:
        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [user_id]
        conn.execute(f"UPDATE users SET {assignments} WHERE user_id = ?", values)
        conn.commit()
    return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def new_thread(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    return update_user(conn, user_id, thread_id=_new_thread())


def add_message(conn: sqlite3.Connection, user_id: int, thread_id: str, role: str, content: str) -> None:
    conn.execute(
        "INSERT INTO messages (user_id, thread_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, thread_id, role, content, time.time()),
    )
    conn.commit()


def load_history(conn: sqlite3.Connection, user_id: int, thread_id: str, limit: int = HISTORY_LIMIT) -> list[dict]:
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE user_id = ? AND thread_id = ? "
        "ORDER BY id DESC LIMIT ?",
        (user_id, thread_id, limit),
    ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]
