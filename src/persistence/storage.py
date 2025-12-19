import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from datetime import datetime
from zoneinfo import ZoneInfo
import re


def _now_iso() -> str:
    now = datetime.now(ZoneInfo("Europe/Prague"))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _pick(d: Dict[str, Any], *keys: str, default=None):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def _extract_flat_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    advert_name = item.get("advert_name")

    loc = item.get("locality")

    clean_name = advert_name.replace("\xa0", " ").replace("\u202f", " ")
    match = re.search(r"(\d+)", clean_name)
    area = int(match.group(1)) if match else None

    price_raw = _pick(item, "price_summary_czk", "price_czk", "price", default=None)
    price_czk = price_raw.get("value") if isinstance(price_raw, dict) else price_raw

    return {
        "hash_id": item.get("hash_id"),
        "advert_name": advert_name,
        "category_main": (item.get("category_main_cb") or {}).get("value"),
        "category_sub": (item.get("category_sub_cb") or {}).get("value"),
        "category_type": (item.get("category_type_cb") or {}).get("value"),
        "city": loc.get("city"),
        "district": loc.get("district"),
        "region_id": loc.get("region_id"),
        "region_name": loc.get("region"),
        "gps_lat": loc.get("gps_lat"),
        "gps_lon": loc.get("gps_lon"),
        "area_m2": area,
        "price_czk": price_czk,
        "price_czk_m2": item.get("price_czk_m2"),
    }


def create_db_if_needed(db_path: Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS estates (
        hash_id            INTEGER PRIMARY KEY,
        advert_name        TEXT,
        category_main      INTEGER,
        category_sub       INTEGER,
        category_type      INTEGER,
        city               TEXT,
        district           TEXT,
        region_id          INTEGER,
        region_name        TEXT,
        gps_lat            REAL,
        gps_lon            REAL,
        area_m2            REAL,
        price_czk          REAL,
        price_czk_m2       REAL,
        first_seen         TEXT,
        last_seen          TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS price_history (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        hash_id   INTEGER NOT NULL,
        ts        TEXT NOT NULL,
        price_czk REAL,
        FOREIGN KEY(hash_id) REFERENCES estates(hash_id)
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_estates_region ON estates(region_id);")
    con.commit()
    con.close()


def upsert_items(items: Iterable[Dict[str, Any]], db_path: Path) -> None:
    create_db_if_needed(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    now = _now_iso()

    for raw in items:
        rec = _extract_flat_fields(raw)
        hid = rec["hash_id"]
        if hid is None:
            continue

        cur.execute("SELECT price_czk, first_seen FROM estates WHERE hash_id = ?", (hid,))
        row = cur.fetchone()
        previous_price: Optional[float] = row["price_czk"] if row else None
        first_seen_prev: Optional[str] = row["first_seen"] if row else None

        cur.execute("""
        INSERT INTO estates (
            hash_id, advert_name, category_main, category_sub, category_type,
            city, district, region_id, region_name, gps_lat, gps_lon,
            area_m2, price_czk, price_czk_m2,
            first_seen, last_seen
        ) VALUES (
            :hash_id, :advert_name, :category_main, :category_sub, :category_type,
            :city, :district, :region_id, :region_name, :gps_lat, :gps_lon,
            :area_m2, :price_czk, :price_czk_m2,
            :first_seen, :last_seen
        )
        ON CONFLICT(hash_id) DO UPDATE SET
            advert_name=excluded.advert_name,
            category_main=excluded.category_main,
            category_sub=excluded.category_sub,
            category_type=excluded.category_type,
            city=excluded.city,
            district=excluded.district,
            region_id=excluded.region_id,
            region_name=excluded.region_name,
            gps_lat=excluded.gps_lat,
            gps_lon=excluded.gps_lon,
            area_m2=excluded.area_m2,
            price_czk=excluded.price_czk,
            price_czk_m2=excluded.price_czk_m2,
            last_seen=excluded.last_seen;
        """, {
            **rec,
            "first_seen": first_seen_prev or now,
            "last_seen": now,
        })

        if rec["price_czk"] is not None and rec["price_czk"] != previous_price:
            cur.execute(
                "INSERT INTO price_history (hash_id, ts, price_czk) VALUES (?, ?, ?)",
                (hid, now, rec["price_czk"])
            )

    con.commit()
    con.close()


def get_known_ids(db_path: Path) -> list[int]:
    create_db_if_needed(db_path)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT hash_id FROM estates;")
    ids = [row[0] for row in cur.fetchall()]
    con.close()
    return ids


def ensure_new_ads_table(db_path: Path):
    """Zajistí existenci tabulky pro nové inzeráty."""
    db_path = Path(db_path)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS new_estates (
        hash_id INTEGER PRIMARY KEY,
        first_detected TEXT NOT NULL,
        seen INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(hash_id) REFERENCES estates(hash_id)
    );
    """)
    con.commit()
    con.close()


def mark_new_ads(new_items: list[dict], db_path: Path):
    """Uloží nové inzeráty do new_estates."""
    ensure_new_ads_table(db_path)
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    now = _now_iso()

    for item in new_items:
        hid = item.get("hash_id")
        if not hid:
            continue
        cur.execute(
            "INSERT OR IGNORE INTO new_estates (hash_id, first_detected, seen) VALUES (?, ?, 0)",
            (hid, now),
        )
    con.commit()
    con.close()
