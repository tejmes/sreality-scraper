from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "estates.sqlite3"
DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def create_db_if_needed(db_path: Path | str = DEFAULT_DB_PATH) -> None:
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
        price_unit_value   INTEGER,
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


def _pick(d: Dict[str, Any], *keys: str, default=None):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def _extract_flat_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    loc = item.get("locality") or {}
    price_czk = _pick(item, "price_summary_czk", "price_czk", "price", default=None)
    price_unit_cb = item.get("price_unit_cb") or {}
    area = _pick(item, "estate_area", "living_area", "land_area", "usable_area", "area", default=None)

    return {
        "hash_id": item.get("hash_id"),
        "advert_name": _pick(item, "advert_name", "name", "title", default=None),
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
        "price_czk_m2": _pick(item, "price_summary_czk_m2", "price_czk_m2", default=None),
        "price_unit_value": price_unit_cb.get("value"),
    }


def upsert_items(items: Iterable[Dict[str, Any]], db_path: Path | str = DEFAULT_DB_PATH) -> None:
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
            area_m2, price_czk, price_czk_m2, price_unit_value,
            first_seen, last_seen
        ) VALUES (
            :hash_id, :advert_name, :category_main, :category_sub, :category_type,
            :city, :district, :region_id, :region_name, :gps_lat, :gps_lon,
            :area_m2, :price_czk, :price_czk_m2, :price_unit_value,
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
            price_unit_value=excluded.price_unit_value,
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


def get_known_ids(db_path: Path | str = DEFAULT_DB_PATH) -> list[int]:
    create_db_if_needed(db_path)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT hash_id FROM estates;")
    ids = [row[0] for row in cur.fetchall()]
    con.close()
    return ids
