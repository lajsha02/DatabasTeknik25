# Modules/AuthDB.py (vår pickle-baserade lagring)
import os, hashlib, secrets, time, pickle
from typing import List, Tuple, Optional

DB_PATH = "data/game.pickle"

def _ensure_dir():
    os.makedirs("data", exist_ok=True)

def _default_db():
    """ Vår "databas" som en Python-dict:
    - users:     lista av användare
    - scores:    lista av resultat
    - counters:  enkla räknare för användarid)"""
    return {"users": [], "scores": [], "counters": {"users": 0, "scores": 0}}

def _load_db():
    _ensure_dir()
    if not os.path.exists(DB_PATH):
        return _default_db()
    with open(DB_PATH, "rb") as f:
        db = pickle.load(f)
    # Säkerställ att alla nycklar finns (om vi ändrar struktur senare)
    if "users" not in db: db["users"] = []
    if "scores" not in db: db["scores"] = []
    if "counters" not in db: db["counters"] = {"users": 0, "scores": 0}
    # Alla användare ska alltid ha en progress-lista (vilka länder som är klara)
    for u in db["users"]:
        if "progress" not in u:
            u["progress"] = []
    return db

def _save_db(db):
    """ Sparar hela databasen (dict) till fil """
    with open(DB_PATH, "wb") as f:
        pickle.dump(db, f)

#  Publika API:t för användarhantering, resultat och progress
def init_db():
    """Initierar filen om den saknas, så resten av koden kan anta rätt struktur."""
    db = _load_db()
    _save_db(db)

def _hash_password(password: str, salt: bytes) -> bytes:
    """ Returnerar en hash av lösenordet med angivet salt """
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)

def create_user(username: str, password: str):
    """ Skapa användare: unikt namn, spara salt + hash + tom progress"""
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
        "progress": []  # här lagrar vi vilka länder spelaren låst upp
    }
    db["users"].append(user_rec)
    _save_db(db)
    return True, {"user_id": user_rec["id"]}

def verify_user(username: str, password: str):
    # autentiserar genom att hasha inmatningen med lagrat salt och jämför med hash
    db = _load_db()
    for u in db["users"]:
        if u["username"] == username.strip():
            if _hash_password(password, u["pw_salt"]) == u["pw_hash"]:
                return True, {"user_id": u["id"]}
            else:
                return False, "Fel lösenord."
    return False, "Hittar inte användaren."

def record_score(user_id: int, level: int, time_sec: int):
    """ Spara ett resultat. används för leaderboard-logik."""
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
    """Returnerar [(username, bästa_tid)] för vald level, sorterat snabbast först."""
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

#Progress/land-logik
def add_country_progress(user_id: int, country_id: str) -> bool:
    """Markera att användaren klarat ett land (används för upplåsning i UI)"""
    db = _load_db()
    for u in db["users"]:
        if u["id"] == int(user_id):
            if country_id not in u["progress"]:
                u["progress"].append(country_id)
            _save_db(db)
            return True
    return False

def remove_country_progress(user_id: int, country_id: str) -> bool:
    # Smidig för återställning/testfall när vi vill låsa om ett land.
    db = _load_db()
    for u in db["users"]:
        if u["id"] == int(user_id):
            if country_id in u["progress"]:
                u["progress"].remove(country_id)
            _save_db(db)
            return True
    return False

def get_progress(user_id: int) -> List[str]:
    """Hämtas av game.py för att rita rätt (öppna/låsta) land-knappar"""
    db = _load_db()
    for u in db["users"]:
        if u["id"] == int(user_id):
            return list(u.get("progress", []))
    return []

def has_access(user_id: int, country_id: str) -> bool:
    """True om landet finns i spelarens progress (annars visas lås-ikon i UI:t)"""
    db = _load_db()
    for u in db["users"]:
        if u["id"] == int(user_id):
            return country_id in u.get("progress", [])
    return False

# hjälpfunktion för att kunna slå upp id från användarnamn utan att röra loginflödet.
def user_id_by_username(username: str) -> Optional[int]:
    db = _load_db()
    for u in db["users"]:
        if u["username"] == username.strip():
            return u["id"]
    return None