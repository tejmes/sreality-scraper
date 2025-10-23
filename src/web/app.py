from __future__ import annotations

from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx

from src.sreality_client import (
    build_query,
    fetch_all_pages,
    to_card,
    save_json,
)


# --- Pomocné převody ---
def _to_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(s.strip())
    except ValueError:
        return None


def _to_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return float(s.strip())
    except ValueError:
        return None


def _clean_str(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v if v else None


def search_multiple_keywords(
        *,
        base_filters: dict,
        description_search: Optional[str],
        use_price_m2: bool,
        fetch_all: bool = False
) -> list[dict]:
    """
    Provede jedno nebo více dotazů na API podle klíčových slov oddělených čárkou/tečkou/čárkou
    a sjednotí výsledky bez duplikátů.
    - base_filters = ostatní parametry (kromě description_search)
    - fetch_all = False → fetch_page (jedna stránka)
                 True  → fetch_all_pages (všechny stránky)
    """
    from src.sreality_client import build_query, fetch_page, fetch_all_pages, extract_items, extract_pagination

    # rozdělit klíčová slova
    keywords = []
    if description_search:
        keywords = [w.strip() for w in description_search.replace(";", ",").split(",") if w.strip()]

    print(f"[SEARCH_MULTI] Klíčová slova: {keywords or ['(žádné)']}")
    all_results = []

    # --- každý dotaz zvlášť ---
    for i, kw in enumerate(keywords or [None]):
        url = build_query(
            description_search=_clean_str(kw),
            **base_filters
        )
        print(f"[SEARCH_MULTI] Dotaz {i + 1}/{len(keywords or [None])}: {url}")

        if fetch_all:
            data = fetch_all_pages(url)
            items = data
        else:
            data = fetch_page(url)
            items = extract_items(data)
            pagination = extract_pagination(data)
            print(f"[SEARCH_MULTI] {len(items)} položek (total={pagination.get('total')})")

        all_results.extend(items)

    # --- sloučení (UNION) ---
    seen = set()
    unique = []
    for r in all_results:
        hid = r.get("hash_id")
        if hid and hid not in seen:
            unique.append(r)
            seen.add(hid)

    print(f"[SEARCH_MULTI] Po sjednocení: {len(unique)} unikátních inzerátů")
    return unique


# --- FastAPI a šablony ---
ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = ROOT / "templates"

app = FastAPI(title="Sreality Scraper – hledání a rutina")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# =========================================
#           STRÁNKA 1 – HLEDÁNÍ
# =========================================
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/autocomplete")
def autocomplete(q: str):
    if not q or len(q.strip()) < 2:
        return JSONResponse([])

    url = (
            "https://www.sreality.cz/api/v1/localities/suggest"
            "?phrase=" + q.strip() +
            "&category=region_cz,district_cz,municipality_cz,quarter_cz,ward_cz,street_cz,area_cz"
            "&locality_country_id=112"
            "&lang=cs"
            "&limit=10"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.sreality.cz/",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        with httpx.Client(headers=headers, timeout=10.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        suggestions = []
        for item in results:
            user = item.get("userData", {})
            name = user.get("suggestFirstRow")
            second = user.get("suggestSecondRow")
            if name:
                suggestions.append({
                    "name": name,
                    "second_row": second,
                    "entity_type": user.get("entityType"),
                    "entity_id": user.get("id"),
                })
        return JSONResponse(suggestions)
    except Exception as e:
        print(f"[autocomplete] error: {e}")
        return JSONResponse([])


@app.post("/search", response_class=HTMLResponse)
def search(
        request: Request,
        category_main_cb: str = Form(...),
        category_type_cb: Optional[str] = Form(None),
        category_sub_cb: Optional[List[str]] = Form(None),

        locality_country_id: Optional[str] = Form(None),
        locality_region_id: Optional[str] = Form(None),
        locality_district_id: Optional[str] = Form(None),

        locality_search_name: Optional[str] = Form(None),
        locality_entity_type: Optional[str] = Form(None),
        locality_entity_id: Optional[str] = Form(None),
        locality_radius: Optional[str] = Form(None),

        description_search: Optional[str] = Form(None),
        estate_area_from: Optional[str] = Form(None),
        estate_area_to: Optional[str] = Form(None),
        price_from: Optional[str] = Form(None),
        price_to: Optional[str] = Form(None),
        price_mode: str = Form("total"),
        advert_age_to: Optional[str] = Form(None),

        limit: str = Form("60"),
        offset: str = Form("0"),
):
    # --- převody ---
    cm = _to_int(category_main_cb)
    ct = _to_int(category_type_cb)
    subs = [_to_int(s) for s in category_sub_cb or [] if _to_int(s) is not None]

    country = _to_int(locality_country_id) or 112
    reg = _to_int(locality_region_id)
    dist = _to_int(locality_district_id)
    radius = _to_float(locality_radius)
    ea_from = _to_int(estate_area_from)
    ea_to = _to_int(estate_area_to)
    p_from = _to_int(price_from)
    p_to = _to_int(price_to)
    adv_age = _to_int(advert_age_to)
    lim = _to_int(limit) or 60
    off = _to_int(offset) or 0

    use_price_m2 = (price_mode == "per_m2")

    # --- URL dotazu ---
    base_filters = dict(
        category_main_cb=cm,
        category_type_cb=ct,
        category_sub_cb=subs,
        locality_country_id=country,
        locality_region_id=reg,
        locality_district_id=dist,
        locality_search_name=_clean_str(locality_search_name),
        locality_entity_type=_clean_str(locality_entity_type),
        locality_entity_id=_to_int(locality_entity_id),
        locality_radius=radius,
        estate_area_from=ea_from,
        estate_area_to=ea_to,
        price_from=None if use_price_m2 else p_from,
        price_to=None if use_price_m2 else p_to,
        price_m2_from=p_from if use_price_m2 else None,
        price_m2_to=p_to if use_price_m2 else None,
        advert_age_to=adv_age,
        limit=lim,
        offset=off,
    )

    items = search_multiple_keywords(
        base_filters=base_filters,
        description_search=description_search,
        use_price_m2=use_price_m2,
        fetch_all=False,  # jen aktuální stránka (rychlé vyhledávání)
    )

    total = len(items)

    print(f"[SEARCH] Staženo {len(items)} záznamů (celkem {total})")

    cards = [to_card(x) for x in items]
    out_path = save_json({"results": items}, "snapshots/last_search.json")

    # --- stránkování ---
    has_prev = off > 0
    has_next = off + lim < total

    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "items": items,
            "cards": cards,
            "pagination": {
                "total": total,
                "limit": lim,
                "offset": off,
                "has_prev": has_prev,
                "has_next": has_next,
                "prev_offset": max(0, off - lim),
                "next_offset": off + lim,
            },
            "filters": {
                "category_main_cb": cm,
                "category_type_cb": ct,
                "category_sub_cb": subs,
                "locality_country_id": country,
                "locality_region_id": reg,
                "locality_district_id": dist,
                "locality_search_name": locality_search_name,
                "locality_entity_type": locality_entity_type,
                "locality_entity_id": locality_entity_id,
                "locality_radius": radius,
                "description_search": description_search,
                "estate_area_from": ea_from,
                "estate_area_to": ea_to,
                "price_from": p_from,
                "price_to": p_to,
                "price_mode": price_mode,
                "advert_age_to": adv_age,
                "limit": lim,
            },
        },
    )


# =========================================
#           STRÁNKA 2 – RUTINA
# =========================================
@app.get("/routine", response_class=HTMLResponse)
def routine_index(request: Request):
    return templates.TemplateResponse("routine.html", {"request": request})


@app.post("/routine/run", response_class=HTMLResponse)
def routine_run(
        request: Request,
        category_main_cb: str = Form(...),
        category_type_cb: Optional[str] = Form(None),
        category_sub_cb: Optional[List[str]] = Form(None),
        locality_country_id: Optional[str] = Form(None),
        locality_region_id: Optional[str] = Form(None),
        locality_district_id: Optional[str] = Form(None),
        locality_search_name: Optional[str] = Form(None),
        locality_entity_type: Optional[str] = Form(None),
        locality_entity_id: Optional[str] = Form(None),
        locality_radius: Optional[str] = Form(None),
        description_search: Optional[str] = Form(None),
        estate_area_from: Optional[str] = Form(None),
        estate_area_to: Optional[str] = Form(None),
        price_from: Optional[str] = Form(None),
        price_to: Optional[str] = Form(None),
        price_mode: str = Form("total"),
        advert_age_to: Optional[str] = Form(None),
        only_new: Optional[str] = Form(None),  # <── přidaný parametr
):
    # --- převody ---
    cm = _to_int(category_main_cb)
    ct = _to_int(category_type_cb)
    subs = [_to_int(s) for s in category_sub_cb or [] if _to_int(s) is not None]
    country = _to_int(locality_country_id) or 112
    reg = _to_int(locality_region_id)
    dist = _to_int(locality_district_id)
    radius = _to_float(locality_radius)
    ea_from = _to_int(estate_area_from)
    ea_to = _to_int(estate_area_to)
    p_from = _to_int(price_from)
    p_to = _to_int(price_to)
    adv_age = _to_int(advert_age_to)
    use_price_m2 = (price_mode == "per_m2")

    # --- vytvoření URL dotazu ---
    url = build_query(
        category_main_cb=cm,
        category_type_cb=ct,
        category_sub_cb=subs,
        locality_country_id=country,
        locality_region_id=reg,
        locality_district_id=dist,
        locality_search_name=_clean_str(locality_search_name),
        locality_entity_type=_clean_str(locality_entity_type),
        locality_entity_id=_to_int(locality_entity_id),
        locality_radius=radius,
        description_search=_clean_str(description_search),
        estate_area_from=ea_from,
        estate_area_to=ea_to,
        price_from=None if use_price_m2 else p_from,
        price_to=None if use_price_m2 else p_to,
        price_m2_from=p_from if use_price_m2 else None,
        price_m2_to=p_to if use_price_m2 else None,
        advert_age_to=adv_age,
    )

    base_filters = dict(
        category_main_cb=cm,
        category_type_cb=ct,
        category_sub_cb=subs,
        locality_country_id=country,
        locality_region_id=reg,
        locality_district_id=dist,
        locality_search_name=_clean_str(locality_search_name),
        locality_entity_type=_clean_str(locality_entity_type),
        locality_entity_id=_to_int(locality_entity_id),
        locality_radius=radius,
        estate_area_from=ea_from,
        estate_area_to=ea_to,
        price_from=None if use_price_m2 else p_from,
        price_to=None if use_price_m2 else p_to,
        price_m2_from=p_from if use_price_m2 else None,
        price_m2_to=p_to if use_price_m2 else None,
        advert_age_to=adv_age,
    )

    items = search_multiple_keywords(
        base_filters=base_filters,
        description_search=description_search,
        use_price_m2=use_price_m2,
        fetch_all=True,  # rutina – stáhne všechny stránky
    )

    from src.storage import upsert_items, get_known_ids
    known_ids = set(get_known_ids())
    new_items = [x for x in items if x.get("hash_id") and x["hash_id"] not in known_ids]

    # vždy uložíme všechny (aby se databáze aktualizovala)
    upsert_items(items)
    print(f"[ROUTINE] Uloženo {len(items)} inzerátů (z toho {len(new_items)} nových)")

    # --- rozhodni, co se zobrazí ---
    show_only_new = bool(only_new)
    displayed_items = new_items if show_only_new else items

    cards = [to_card(x) for x in displayed_items]
    total = len(displayed_items)

    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "items": displayed_items,
            "cards": cards,
            "pagination": {
                "total": total,
                "limit": 0,
                "offset": 0,
                "has_prev": False,
                "has_next": False,
                "prev_offset": 0,
                "next_offset": 0,
            },
            "filters": {
                "category_main_cb": cm,
                "category_type_cb": ct,
                "category_sub_cb": subs,
                "locality_country_id": country,
                "locality_region_id": reg,
                "locality_district_id": dist,
                "locality_search_name": locality_search_name,
                "locality_entity_type": locality_entity_type,
                "locality_entity_id": locality_entity_id,
                "locality_radius": radius,
                "description_search": description_search,
                "estate_area_from": ea_from,
                "estate_area_to": ea_to,
                "price_from": p_from,
                "price_to": p_to,
                "price_mode": price_mode,
                "advert_age_to": adv_age,
                "only_new": show_only_new,
            },
        },
    )
