from __future__ import annotations
from typing import Any, Dict, Optional, List, Iterable
from urllib.parse import urlencode
from pathlib import Path
import json
import httpx
import time

from src.headers import build_browser_like_headers

BASE_SEARCH = "https://www.sreality.cz/api/v1/estates/search"


# --- Pomocná funkce pro přidání parametru do URL ---
def _add(params: Dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, (list, tuple, set)):
        seq = [str(v) for v in value if v is not None]
        if seq:
            params[key] = ",".join(seq)
        return
    params[key] = value


# --- Sestavení dotazu na API ---
def build_query(
        *,
        category_main_cb: Optional[int] = None,
        category_type_cb: Optional[int] = None,
        category_sub_cb: Optional[Iterable[int]] = None,
        room_count_cb: Optional[Iterable[int]] = None,
        locality_country_id: Optional[int] = None,
        locality_region_id: Optional[int] = None,
        locality_district_id: Optional[int] = None,
        locality_search_name: Optional[str] = None,
        locality_entity_type: Optional[str] = None,
        locality_entity_id: Optional[int] = None,
        locality_radius: Optional[float] = None,
        description_search: Optional[str] = None,
        estate_area_from: Optional[int] = None,
        estate_area_to: Optional[int] = None,
        price_from: Optional[int] = None,
        price_to: Optional[int] = None,
        price_m2_from: Optional[int] = None,
        price_m2_to: Optional[int] = None,
        advert_age_to: Optional[int] = None,
        limit: int = 60,
        offset: int = 0,
        lang: str = "cs",
) -> str:
    params: Dict[str, Any] = {}
    _add(params, "category_main_cb", category_main_cb)
    _add(params, "category_type_cb", category_type_cb)
    _add(params, "category_sub_cb", list(category_sub_cb) if category_sub_cb else None)
    _add(params, "room_count_cb", list(room_count_cb) if room_count_cb else None)
    _add(params, "locality_search_name", locality_search_name)
    _add(params, "locality_entity_type", locality_entity_type)
    _add(params, "locality_entity_id", locality_entity_id)
    _add(params, "locality_country_id", locality_country_id)
    if locality_region_id is not None and ("locality_entity_id" not in params):
        _add(params, "locality_region_id", locality_region_id)
    if locality_district_id is not None and ("locality_entity_id" not in params):
        _add(params, "locality_district_id", locality_district_id)
    if locality_radius is not None:
        _add(params, "locality_radius", float(locality_radius))
    _add(params, "description_search", description_search)
    _add(params, "estate_area_from", estate_area_from)
    _add(params, "estate_area_to", estate_area_to)
    _add(params, "price_from", price_from)
    _add(params, "price_to", price_to)
    _add(params, "price_m2_from", price_m2_from)
    _add(params, "price_m2_to", price_m2_to)
    _add(params, "advert_age_to", advert_age_to)
    params["limit"] = int(limit)
    params["offset"] = int(offset)
    params["lang"] = lang
    return f"{BASE_SEARCH}?{urlencode(params, doseq=True)}"


# --- Stahování všech stránek ---
def fetch_all_pages(base_url: str, max_pages: int = 1000) -> list[dict]:
    all_items: list[dict] = []
    offset = 0
    limit = 60
    page = 0
    total = None

    print(f"[START] Full sync z {base_url}")

    import re
    base_url = re.sub(r"(&limit=\d+)", "", base_url)
    base_url = re.sub(r"(&offset=\d+)", "", base_url)

    while page < max_pages:
        if total is not None and len(all_items) >= total:
            print(f"[STOP] dosažen konec ({len(all_items)}/{total}) → končím")
            break

        url = f"{base_url}&limit={limit}&offset={offset}"

        try:
            data = fetch_page(url)
        except Exception as e:
            print(f"[WARN] chyba při stahování stránky {page + 1}: {e}")
            break

        pag = extract_pagination(data)
        total = pag.get("total") or total or 0

        items = extract_items(data)
        if not items:
            print(f"[DEBUG] prázdná stránka {page + 1}, končím.")
            break

        all_items.extend(items)
        print(f"[PAGE] {page + 1} → přidáno {len(items)} (celkem {len(all_items)}/{total})")

        offset += limit
        page += 1
        time.sleep(0.3)

    if total and len(all_items) > total:
        print(f"[FIX] ořezávám {len(all_items)} → {total} podle total z API")
        all_items = all_items[:total]

    print(f"[DONE] Načteno {len(all_items)} výsledků z {page} stránek (celkem {total}).")
    print(f"[RETURN DEBUG] Vrací se {len(all_items)} inzerátů zpět do app.py")
    return all_items


# --- Jedna stránka ---
def fetch_page(url: str) -> Dict[str, Any]:
    headers = build_browser_like_headers()
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


# --- Pomocné extrakce ---
def extract_pagination(data: Dict[str, Any]) -> Dict[str, Any]:
    return data.get("pagination", {}) if isinstance(data, dict) else {}


def extract_items(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        print("[extract_items] data není dict")
        return []
    results = data.get("results", [])
    if not results and "_embedded" in data:
        results = data["_embedded"].get("estates", [])
    return results


# --- Převod pro UI ---
def to_card(item: Dict[str, Any]) -> Dict[str, Any]:
    loc = item.get("locality", {})
    if isinstance(loc, dict):
        city = loc.get("city") or ""
        region = loc.get("region") or ""
        loc_txt = " | ".join([x for x in (city, region) if x])
    else:
        loc_txt = str(loc)

    area = item.get("estate_area") or item.get("land_area") or item.get("usable_area")

    # Použijeme vždy cenu z price_summary_czk
    price = item.get("price_summary_czk")

    return {
        "id": item.get("hash_id"),
        "title": item.get("advert_name") or "(bez názvu)",
        "locality": loc_txt,
        "area": area,
        "price": price,
        "url": f"https://www.sreality.cz/detail/{item.get('hash_id')}",
    }


def save_json(data: Dict[str, Any], path: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(p.resolve())
