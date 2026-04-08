import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Optional

DB_PATH = Path(__file__).resolve().parent / "bot.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                points INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS module_progress (
                user_id INTEGER NOT NULL,
                module_key TEXT NOT NULL,
                viewed INTEGER DEFAULT 0,
                quiz_score INTEGER DEFAULT 0,
                quiz_total INTEGER DEFAULT 0,
                quiz_passed INTEGER DEFAULT 0,
                reflection TEXT,
                completed_at TIMESTAMP,
                PRIMARY KEY (user_id, module_key),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_state (
                user_id INTEGER PRIMARY KEY,
                state TEXT,
                payload TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def ensure_user(user_id: int, first_name: str = "", last_name: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, first_name, last_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                updated_at=CURRENT_TIMESTAMP
            """,
            (user_id, first_name, last_name),
        )


def add_points(user_id: int, points: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET points = COALESCE(points, 0) + ?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
            (points, user_id),
        )


def ensure_module_row(user_id: int, module_key: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO module_progress (user_id, module_key)
            VALUES (?, ?)
            """,
            (user_id, module_key),
        )


def mark_viewed(user_id: int, module_key: str) -> bool:
    ensure_module_row(user_id, module_key)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT viewed FROM module_progress WHERE user_id=? AND module_key=?",
            (user_id, module_key),
        ).fetchone()
        if row and row["viewed"]:
            return False
        conn.execute(
            "UPDATE module_progress SET viewed=1 WHERE user_id=? AND module_key=?",
            (user_id, module_key),
        )
        return True


def save_quiz_result(user_id: int, module_key: str, score: int, total: int) -> bool:
    ensure_module_row(user_id, module_key)
    passed = 1 if score >= max(1, total - 1) else 0
    with get_conn() as conn:
        row = conn.execute(
            "SELECT quiz_passed FROM module_progress WHERE user_id=? AND module_key=?",
            (user_id, module_key),
        ).fetchone()
        first_pass = bool(passed and row and not row["quiz_passed"])
        conn.execute(
            """
            UPDATE module_progress
            SET quiz_score=?, quiz_total=?, quiz_passed=?,
                completed_at=CASE
                    WHEN ?=1 AND reflection IS NOT NULL AND TRIM(reflection)<>'' THEN CURRENT_TIMESTAMP
                    ELSE completed_at
                END
            WHERE user_id=? AND module_key=?
            """,
            (score, total, passed, passed, user_id, module_key),
        )
        return first_pass


def save_reflection(user_id: int, module_key: str, reflection: str) -> bool:
    ensure_module_row(user_id, module_key)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT reflection, quiz_passed FROM module_progress WHERE user_id=? AND module_key=?",
            (user_id, module_key),
        ).fetchone()
        is_first = not row or not (row["reflection"] and row["reflection"].strip())
        conn.execute(
            """
            UPDATE module_progress
            SET reflection=?,
                completed_at=CASE
                    WHEN quiz_passed=1 THEN CURRENT_TIMESTAMP
                    ELSE completed_at
                END
            WHERE user_id=? AND module_key=?
            """,
            (reflection, user_id, module_key),
        )
        return is_first


def get_state(user_id: int) -> Optional[Dict[str, str]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT state, payload FROM user_state WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return {"state": row["state"], "payload": row["payload"]}


def set_state(user_id: int, state: str, payload: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_state (user_id, state, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                state=excluded.state,
                payload=excluded.payload,
                updated_at=CURRENT_TIMESTAMP
            """,
            (user_id, state, payload),
        )


def clear_state(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM user_state WHERE user_id=?", (user_id,))


def get_progress(user_id: int):
    with get_conn() as conn:
        user = conn.execute(
            "SELECT user_id, first_name, last_name, points FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        modules = conn.execute(
            "SELECT * FROM module_progress WHERE user_id=? ORDER BY module_key",
            (user_id,),
        ).fetchall()
    return user, modules
