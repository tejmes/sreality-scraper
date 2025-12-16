import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from zoneinfo import ZoneInfo
from passlib.hash import bcrypt
import traceback

from src.routines_storage import list_routines, delete_routine

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
USERS_DB = DATA_DIR / "users.sqlite3"


def _connect(db_path: Path = USERS_DB) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def init_users_db(db_path: Path = USERS_DB) -> None:
    """Vytvoří tabulku users, pokud neexistuje."""
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        """
    )
    con.commit()

    # Přidání sloupce team_id (pokud ještě neexistuje)
    try:
        cur.execute("ALTER TABLE users ADD COLUMN team_id INTEGER")
        con.commit()
    except sqlite3.OperationalError:
        # sloupec už existuje
        pass

    con.close()


def create_user(username: str, password: str, is_admin: bool = False, db_path: Path = USERS_DB) -> Dict[str, Any]:
    """
    Vytvoří uživatele s bcrypt hashem.
    Vyhazuje sqlite3.IntegrityError při duplicitním username.
    """
    try:
        if not username or not password:
            raise ValueError("username and password are required")

        password_hash = bcrypt.hash(password)
        now = datetime.now(ZoneInfo("Europe/Prague")).strftime("%Y-%m-%d %H:%M:%S")

        con = _connect(db_path)
        cur = con.cursor()
        cur.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (username, password_hash, 1 if is_admin else 0, now),
        )
        con.commit()
        user_id = cur.lastrowid
        con.close()
        return {"id": user_id, "username": username, "is_admin": is_admin, "created_at": now}

    except Exception as e:
        print("[ERROR] create_user() failed:")
        traceback.print_exc()
        raise


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def get_user_by_username(username: str, db_path: Path = USERS_DB) -> Optional[Dict[str, Any]]:
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def verify_user_password(username: str, password: str, db_path: Path = USERS_DB) -> Optional[Dict[str, Any]]:
    """
    Vrací dict uživatele, pokud heslo sedí jinak None.
    """
    user = get_user_by_username(username, db_path)
    if not user:
        return None
    if bcrypt.verify(password, user["password_hash"]):
        return user
    return None


def ensure_admin(username: str = "admin", password: str = "admin", db_path: Path = USERS_DB) -> Dict[str, Any]:
    """
    Pokud admin neexistuje, vytvoří ho.
    Vrací existující nebo nově vytvořeného admina.
    """
    init_users_db(db_path)
    user = get_user_by_username(username, db_path)
    if user:
        return user
    return create_user(username=username, password=password, is_admin=True, db_path=db_path)


def list_users():
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT id, username, is_admin, created_at, team_id FROM users ORDER BY id ASC")
    users = [dict(row) for row in cur.fetchall()]
    con.close()
    return users


def delete_user(user_id: int):
    user_routines = list_routines(user_id=user_id)
    for r in user_routines:
        delete_routine(r["id"])

    con = _connect()
    cur = con.cursor()
    cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    con.commit()
    con.close()


def reset_password(user_id: int, new_password: str):
    con = _connect()
    cur = con.cursor()
    hashed = bcrypt.hash(new_password)
    cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hashed, user_id))
    con.commit()
    con.close()


def set_team(user_id: int, team_id: int | None):
    """Nastaví uživateli team_id (nebo None pro odebrání z týmu)."""
    con = _connect()
    cur = con.cursor()
    cur.execute("UPDATE users SET team_id = ? WHERE id = ?", (team_id, user_id))
    con.commit()
    con.close()


def list_team_members(team_id: int):
    """Vrátí seznam uživatelů v daném týmu."""
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE team_id = ?", (team_id,))
    rows = cur.fetchall()
    con.close()
    return [dict(r) for r in rows]
