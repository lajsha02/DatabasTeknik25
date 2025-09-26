# Modules/AuthDB.py
import sqlite3, os, hashlib, secrets, time

DB_PATH = "data/game.db"

def _connect():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = _connect()
    cur = conn.cursor()
    # Users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            pw_salt BLOB NOT NULL,
            pw_hash BLOB NOT NULL,
            created_at INTEGER NOT NULL
        );
    """)
    # Scores (för framtida leaderboard – kan användas direkt om ni vill)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scores(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            level INTEGER NOT NULL,
            time_sec INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()

def _hash_password(password: str, salt: bytes) -> bytes:
    # PBKDF2-HMAC (standardbibliotek, bra nog för skolkurs/projekt)
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)

def create_user(username: str, password: str):
    username = username.strip()
    if len(username) < 3 or len(password) < 3:
        return False, "Användarnamn och lösenord måste vara minst 3 tecken."
    conn = _connect()
    try:
        salt = secrets.token_bytes(16)
        pw_hash = _hash_password(password, salt)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users(username, pw_salt, pw_hash, created_at) VALUES(?,?,?,?)",
            (username, salt, pw_hash, int(time.time()))
        )
        conn.commit()
        return True, {"user_id": cur.lastrowid}
    except sqlite3.IntegrityError:
        return False, "Användarnamnet är upptaget."
    finally:
        conn.close()

def verify_user(username: str, password: str):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id, pw_salt, pw_hash FROM users WHERE username=?", (username.strip(),))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False, "Hittar inte användaren."
    uid, salt, stored_hash = row
    if _hash_password(password, salt) == stored_hash:
        return True, {"user_id": uid}
    return False, "Fel lösenord."

def record_score(user_id: int, level: int, time_sec: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO scores(user_id, level, time_sec, created_at) VALUES(?,?,?,?)",
        (user_id, level, time_sec, int(time.time()))
    )
    conn.commit()
    conn.close()

def top_times(level: int, limit: int = 10):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT u.username, MIN(s.time_sec) AS best
        FROM scores s JOIN users u ON u.id = s.user_id
        WHERE s.level = ?
        GROUP BY s.user_id
        ORDER BY best ASC
        LIMIT ?
    """, (level, limit))
    rows = cur.fetchall()
    conn.close()
    return rows

# Modules/AuthDB.py  (utdrag/komplettering)
def record_score(user_id: int, level: int, time_sec: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO scores(user_id, level, time_sec, created_at) VALUES(?,?,?,?)",
        (user_id, level, time_sec, int(time.time()))
    )
    conn.commit()
    conn.close()

def top_times(level: int, limit: int = 10):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT u.username, MIN(s.time_sec) AS best
        FROM scores s JOIN users u ON u.id = s.user_id
        WHERE s.level = ?
        GROUP BY s.user_id
        ORDER BY best ASC
        LIMIT ?
    """, (level, limit))
    rows = cur.fetchall()
    conn.close()
    return rows  # [("Nahom Yared", 102), ...]

