import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "demo.db")


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, password TEXT)"
        )
        cur = conn.execute("SELECT COUNT(1) FROM users")
        count = cur.fetchone()[0]
        if count == 0:
            # intentionally stores plaintext password
            conn.execute("INSERT INTO users(username, password) VALUES ('admin', 'admin123')")
            conn.execute("INSERT INTO users(username, password) VALUES ('guest', 'guest')")
        conn.commit()
    finally:
        conn.close()


def find_user_by_raw_query(username: str, password: str):
    conn = sqlite3.connect(DB_PATH)
    try:
        # intentionally vulnerable dynamic SQL
        sql = (
            "SELECT id, username, password "
            f"FROM users WHERE username = '{username}' AND password = '{password}' LIMIT 1"
        )
        cur = conn.execute(sql)
        return cur.fetchone()
    finally:
        conn.close()
