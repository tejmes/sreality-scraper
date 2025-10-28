from __future__ import annotations
from typing import Any, Dict, Optional, List, Iterable
from urllib.parse import urlencode
from pathlib import Path
import json
import httpx
import time

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


def fetch_page(url: str) -> Dict[str, Any]:
    headers = build_browser_like_headers()
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


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


def to_card(item: Dict[str, Any]) -> Dict[str, Any]:
    loc = item.get("locality", {})
    if isinstance(loc, dict):
        city = loc.get("city") or ""
        region = loc.get("region") or ""
        loc_txt = " | ".join([x for x in (city, region) if x])
    else:
        loc_txt = str(loc)

    area = item.get("estate_area") or item.get("land_area") or item.get("usable_area")
    price = item.get("price_summary_czk")

    # 1) Preferovat kanonickou URL z API
    url = None
    links = item.get("_links", {})
    if isinstance(links, dict):
        self_link = (links.get("self") or {}).get("href")
        if self_link:
            url = "https://www.sreality.cz" + self_link

    # 2) Fallback – robustní složení SEO URL (včetně locality slugu)
    if not url:
        # Pomocné mapy
        type_map = {1: "prodej", 2: "pronajem", 3: "drazby", 4: "podily"}
        main_map = {1: "byt", 2: "dum", 3: "pozemek", 4: "komercni", 5: "ostatni"}
        sub_map = {
            18: "komercni", 19: "bydleni", 20: "pole", 21: "lesy", 22: "louky",
            23: "zahrady", 24: "ostatni", 33: "chata", 35: "pamatka-jine",
            37: "rodinny", 39: "vila", 40: "na-klic", 43: "chalupa",
            44: "zemedelska-usedlost", 46: "rybniky", 48: "sady-vinice", 54: "vicegeneracni-dum"
        }

        def _slugify(s: str) -> str:
            import unicodedata, re
            s = unicodedata.normalize("NFKD", s)
            s = "".join(ch for ch in s if not unicodedata.combining(ch))
            s = s.lower()
            s = re.sub(r"[^a-z0-9]+", "-", s)
            s = re.sub(r"-{2,}", "-", s).strip("-")
            return s

        # Kategorie části
        ct_val = (item.get("category_type_cb") or {}).get("value")
        cm_val = (item.get("category_main_cb") or {}).get("value")
        cs_val = (item.get("category_sub_cb") or {}).get("value")
        ct = type_map.get(ct_val, "detail")
        cm = main_map.get(cm_val, "nemovitost")
        cs = sub_map.get(cs_val, "")

        # Locality slug: preferuj SEO.locality, jinak slož z locality dictu
        locality_slug = ""
        seo = item.get("seo") or {}
        if isinstance(seo, dict):
            locality_slug = seo.get("locality") or ""

        if not locality_slug:
            # pokus složit ze známých polí locality
            if isinstance(loc, dict):
                parts_guess = []
                # Město / městská část
                for key in ("city", "municipality", "quarter", "ward"):
                    val = loc.get(key)
                    if val:
                        parts_guess.append(str(val))
                # Ulice – v různých datech může být 'street' nebo 'street_name'
                for key in ("street", "street_name"):
                    val = loc.get(key)
                    if val:
                        parts_guess.append(str(val))
                if parts_guess:
                    locality_slug = "-".join(_slugify(p) for p in parts_guess if p)
            # poslední zoufalý pokus: někdy je locality text celé v jednom řetězci
            if not locality_slug and isinstance(loc, str):
                locality_slug = _slugify(loc)

        # Když se nepodaří nic zjistit, raději ponecháme „/detail/<id>“ než rozbitý slug,
        # ale pokud aspoň něco máme, složíme plnou SEO URL.
        hid = item.get("hash_id")
        if locality_slug:
            parts = [p for p in (ct, cm, cs) if p]
            cat_path = "/".join(parts)
            url = f"https://www.sreality.cz/detail/{cat_path}/{locality_slug}/{hid}"
        else:
            url = f"https://www.sreality.cz/detail/{hid}"

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
