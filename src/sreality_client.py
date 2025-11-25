from typing import Any, Dict, Optional, List, Iterable
from urllib.parse import urlencode
from pathlib import Path
import json
import httpx
import time
import re
import unicodedata

from src.headers import build_browser_like_headers

BASE_SEARCH = "https://www.sreality.cz/api/v1/estates/search"


def _add(params: Dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, (list, tuple, set)):
        seq = [str(v) for v in value if v is not None]
        if seq:
            params[key] = ",".join(seq)
        return
    params[key] = value


def build_query(
        *,
        category_main_cb: Optional[int] = None,
        category_type_cb: Optional[Iterable[int]] = None,
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
        usable_area_from: Optional[int] = None,
        usable_area_to: Optional[int] = None,
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
    _add(params, "usable_area_from", usable_area_from)
    _add(params, "usable_area_to", usable_area_to)
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


def fetch_page(url: str) -> Dict[str, Any]:
    headers = build_browser_like_headers()
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


def fetch_all_pages(base_url: str, max_pages: int = 10000) -> list[dict]:
    all_items: list[dict] = []
    offset = 0
    limit = 60
    page = 0
    total = None

    print(f"[START] Full sync z {base_url}")

    base_url = re.sub(r"(&limit=\d+)", "", base_url)
    base_url = re.sub(r"(&offset=\d+)", "", base_url)

    while page < max_pages:
        if total is not None and len(all_items) >= total:
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
            break

        all_items.extend(items)
        offset += limit
        page += 1
        time.sleep(0.3)

    return all_items


def extract_pagination(data: Dict[str, Any]) -> Dict[str, Any]:
    return data.get("pagination", {}) if isinstance(data, dict) else {}


def extract_items(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    results = data.get("results", [])
    if not results and "_embedded" in data:
        results = data["_embedded"].get("estates", [])
    return results


def to_card(item: dict[str, Any]) -> dict[str, Any]:
    """
    Převádí JSON položku z API na interní 'card' objekt.
    """
    # --- Lokalita pro zobrazení ---
    loc = item.get("locality") or {}
    if isinstance(loc, dict):
        city = loc.get("city") or ""
        region = loc.get("region") or ""
        loc_txt = " | ".join([x for x in (city, region) if x])
    else:
        loc_txt = str(loc)

    advert_name = item.get("advert_name") or ""
    clean_name = advert_name.replace("\xa0", " ").replace("\u202f", " ")
    match = re.search(r"(\d+)", clean_name)
    area = int(match.group(1)) if match else None

    price_raw = item.get("price_summary_czk") or item.get("price_czk") or item.get("price")
    if isinstance(price_raw, dict):
        price = price_raw.get("value")
    else:
        price = price_raw

    type_map = {1: "prodej", 2: "pronajem", 3: "drazby", 4: "podily"}
    main_map = {1: "byt", 2: "dum", 3: "pozemek", 4: "komercni", 5: "ostatni"}
    sub_map = {
        2: "1+kk",
        3: "1+1",
        4: "2+kk",
        5: "2+1",
        6: "3+kk",
        7: "3+1",
        8: "4+kk",
        9: "4+1",
        10: "5+kk",
        11: "5+1",
        12: "6-a-vice",
        16: "atypicky",
        18: "komercni",
        19: "bydleni",
        20: "pole",
        21: "les",
        22: "louka",
        23: "zahrada",
        24: "ostatni-pozemky",
        25: "kancelare",
        26: "sklady",
        27: "vyroba",
        28: "obchodni-prostory",
        29: "ubytovani",
        30: "restaurace",
        31: "zemedelsky",
        32: "ostatni-komercni",
        33: "chata",
        34: "garaz",
        35: "pamatka-jine",
        36: "ostatni-ostatni",
        37: "rodinny",
        38: "cinzovni-dum",
        39: "vila",
        40: "na-klic",
        43: "chalupa",
        44: "zemedelska-usedlost",
        46: "rybnik",
        47: "pokoj",
        48: "sady-vinice",
        49: "virtualni-kancelar",
        50: "vinny-sklep",
        51: "pudni-prostor",
        52: "garazove-stani",
        53: "mobilheim",
        54: "vicegeneracni-dum",
        56: "ordinace",
        57: "apartmany",
    }

    def _val(cb):
        """Bezpečně vrátí číselnou hodnotu z dictu (i jako string)."""
        if isinstance(cb, dict):
            val = cb.get("value")
            # pokud je číslo, vrať ho
            if isinstance(val, int):
                return val
            # pokud je string s číslem, převeď
            if isinstance(val, str) and val.isdigit():
                return int(val)
            return None
        # pokud je string s číslem
        if isinstance(cb, str) and cb.isdigit():
            return int(cb)
        return cb

    def _slugify(s: str) -> str:
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        s = s.lower()
        s = re.sub(r"[^a-z0-9]+", "-", s)
        return s.strip("-")

    # --- Kategorie ---
    ct = type_map.get(_val(item.get("category_type_cb")), "detail")
    cm = main_map.get(_val(item.get("category_main_cb")), "nemovitost")
    sub_val = _val(item.get("category_sub_cb"))
    cs = sub_map.get(sub_val, "")

    # --- Oprava množných tvarů podkategorií (Sreality používá singulár) ---
    singular_fixes = {
        "louky": "louka",
        "lesy": "les",
        "zahrady": "zahrada",
        "rybniky": "rybnik",
    }
    if cs in singular_fixes:
        cs = singular_fixes[cs]

    # --- Lokalita slug (API ji někdy vrací množně, např. 'zahrady') ---
    seo = item.get("seo") or {}
    locality_slug = seo.get("locality") if isinstance(seo, dict) else ""
    if not locality_slug and isinstance(loc, dict):
        parts = [loc.get(k) for k in ("municipality", "city", "quarter", "ward") if loc.get(k)]
        locality_slug = "-".join(_slugify(x) for x in parts if x)
    elif isinstance(loc, str) and not locality_slug:
        locality_slug = _slugify(loc)

    # --- Složení finální URL ---
    hid = item.get("hash_id")
    parts = [p for p in (ct, cm, cs) if p]
    cat_path = "/".join(parts)
    if locality_slug:
        url = f"https://www.sreality.cz/detail/{cat_path}/{locality_slug}/{hid}"
    else:
        url = f"https://www.sreality.cz/detail/{cat_path}/{hid}"

    return {
        "id": item.get("hash_id"),
        "title": item.get("advert_name") or "(bez názvu)",
        "locality": loc_txt,
        "area": area,
        "price": price,
        "url": url,
    }


def save_json(data: Dict[str, Any], path: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(p.resolve())
