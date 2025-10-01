# Modules/AuthDB.py (pickle-based storage + per-user progress)
import os, hashlib, secrets, time, pickle
from typing import List, Tuple, Optional

# Behåll samma namn men byt till pickle-fil
DB_PATH = "data/game.pickle"

# ---------- Intern hjälp ----------
def _ensure_dir():
    os.makedirs("data", exist_ok=True)

def _default_db():
    return {"users": [], "scores": [], "counters": {"users": 0, "scores": 0}}

def _load_db():
    _ensure_dir()
    if not os.path.exists(DB_PATH):
        return _default_db()
    with open(DB_PATH, "rb") as f:
        db = pickle.load(f)
    # Framåtkompatibilitet
    if "users" not in db: db["users"] = []
    if "scores" not in db: db["scores"] = []
    if "counters" not in db: db["counters"] = {"users": 0, "scores": 0}
    # Säkerställ progress på alla users
    for u in db["users"]:
        if "progress" not in u:
            u["progress"] = []
    return db

def _save_db(db):
    with open(DB_PATH, "wb") as f:
        pickle.dump(db, f)

# Bibehållen signatur – gör inget i pickle-läget
def _connect():
    return None

# ---------- Publika API:t (oförändrade funktionsnamn) ----------
def init_db():
    """Se till att pickle-filen finns och har rätt struktur."""
    db = _load_db()
    _save_db(db)

def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)

def create_user(username: str, password: str):
    username = username.strip()
    if len(username) < 3 or len(password) < 3:
        return False, "Användarnamn och lösenord måste vara minst 3 tecken."
    db = _load_db()
    for u in db["users"]:
        if u["username"] == username:
            return False, "Användarnamnet är upptaget."
    salt = secrets.token_bytes(16)
    pw_hash = _hash_password(password, salt)
    db["counters"]["users"] += 1
    user_rec = {
        "id": db["counters"]["users"],
        "username": username,
        "pw_salt": salt,
        "pw_hash": pw_hash,
        "created_at": int(time.time()),
        "progress": []  # <- NYTT: lista av klarade länder
    }
    db["users"].append(user_rec)
    _save_db(db)
    return True, {"user_id": user_rec["id"]}

def verify_user(username: str, password: str):
    db = _load_db()
    for u in db["users"]:
        if u["username"] == username.strip():
            if _hash_password(password, u["pw_salt"]) == u["pw_hash"]:
                return True, {"user_id": u["id"]}
            else:
                return False, "Fel lösenord."
    return False, "Hittar inte användaren."

def record_score(user_id: int, level: int, time_sec: int):
    db = _load_db()
    db["counters"]["scores"] += 1
    score_rec = {
        "id": db["counters"]["scores"],
        "user_id": int(user_id),
        "level": int(level),
        "time_sec": int(time_sec),
        "created_at": int(time.time())
    }
    db["scores"].append(score_rec)
    _save_db(db)

def top_times(level: int, limit: int = 10) -> List[Tuple[str, int]]:
    """[(username, best_time_sec), ...] sorterat på kortast tid."""
    db = _load_db()
    id2name = {u["id"]: u["username"] for u in db["users"]}
    best_per_user = {}
    for s in db["scores"]:
        if s["level"] != int(level):
            continue
        uid = s["user_id"]
        best = best_per_user.get(uid)
        if best is None or s["time_sec"] < best:
            best_per_user[uid] = s["time_sec"]
    rows = [(id2name.get(uid, f"User {uid}"), best) for uid, best in best_per_user.items()]
    rows.sort(key=lambda x: x[1])
    return rows[:limit]

# ---------- NYTT: Progress/land-logik ----------
def add_country_progress(user_id: int, country_id: str) -> bool:
    """Markera att användaren har klarat ett land (låser upp knappen)."""
    db = _load_db()
    for u in db["users"]:
        if u["id"] == int(user_id):
            if country_id not in u["progress"]:
                u["progress"].append(country_id)
            _save_db(db)
            return True
    return False

def remove_country_progress(user_id: int, country_id: str) -> bool:
    db = _load_db()
    for u in db["users"]:
        if u["id"] == int(user_id):
            if country_id in u["progress"]:
                u["progress"].remove(country_id)
            _save_db(db)
            return True
    return False

def get_progress(user_id: int) -> List[str]:
    db = _load_db()
    for u in db["users"]:
        if u["id"] == int(user_id):
            return list(u.get("progress", []))
    return []

def has_access(user_id: int, country_id: str) -> bool:
    """True om landet är klarat/olåst, annars röd/disabled i UI:t."""
    db = _load_db()
    for u in db["users"]:
        if u["id"] == int(user_id):
            return country_id in u.get("progress", [])
    return False

# Hjälp: hämta user_id från användarnamn (så vi slipper ändra i login.py)
def user_id_by_username(username: str) -> Optional[int]:
    db = _load_db()
    for u in db["users"]:
        if u["username"] == username.strip():
            return u["id"]
    return None
