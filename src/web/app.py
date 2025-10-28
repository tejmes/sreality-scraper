from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx

from fastapi.responses import HTMLResponse
import sqlite3
from datetime import datetime

from src.sreality_client import (
    build_query,
    fetch_page,
    fetch_all_pages,
    extract_items,
    extract_pagination,
    to_card,
    save_json,
)
from src.routines_storage import (
    list_routines,
    get_routine,
    create_routine,
    update_routine_name,
    delete_routine,
    routine_db_path,
)
from src.storage import (
    upsert_items,
    get_known_ids,
    create_db_if_needed,
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


def _split_keywords(description_search: Optional[str]) -> list[str]:
    if not description_search:
        return []
    return [w.strip() for w in description_search.replace(";", ",").split(",") if w.strip()]


def search_multiple_keywords(
        *,
        base_filters: dict,
        description_search: Optional[str],
        fetch_all: bool = False,
) -> tuple[list[dict], dict]:
    """
    Provede jedno nebo více dotazů na API podle klíčových slov a sjednotí výsledky bez duplikátů.
    Vrací (unikátní_výsledky, pagination_info)
    """
    keywords = _split_keywords(description_search)
    all_results = []
    last_limit = base_filters.get("limit", 60)
    total_from_api = 0

    # více dotazů = chytré vyhledávání
    multi_search = len(keywords) > 1

    for kw in (keywords or [None]):
        url = build_query(description_search=_clean_str(kw), **base_filters)
        if fetch_all:
            data = fetch_all_pages(url)
            items = data
            pag = {"total": len(items), "limit": base_filters.get("limit", 60)}
        else:
            data = fetch_page(url)
            items = extract_items(data)
            pag = extract_pagination(data)

        last_limit = pag.get("limit", last_limit)
        total_from_api = max(total_from_api, pag.get("total", 0))
        all_results.extend(items)

    # sjednocení výsledků (bez duplicit podle hash_id)
    seen = set()
    unique = []
    for r in all_results:
        hid = r.get("hash_id")
        if hid and hid not in seen:
            unique.append(r)
            seen.add(hid)

    # --- rozhodnutí, co zobrazit jako total ---
    if multi_search:
        # při chytrém vyhledávání chceme reálný počet všech unikátních výsledků
        total_final = len(unique)
    else:
        # při běžném vyhledávání použij hodnotu z API (aby stránkování fungovalo)
        total_final = total_from_api or len(unique)

    return unique, {"total": total_final, "limit": last_limit}


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
    # převody
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

    items, pagination = search_multiple_keywords(
        base_filters=base_filters,
        description_search=description_search,
        fetch_all=False,
    )

    total = pagination.get("total", len(items))
    cards = [to_card(x) for x in items]
    save_json({"results": items}, "snapshots/last_search.json")

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
#           RUTINY – UI + CRUD
# =========================================
@app.get("/routine", response_class=HTMLResponse)
def routine_index(request: Request):
    # formulář pro vytvoření nové rutiny
    return templates.TemplateResponse("routine.html", {"request": request})


@app.post("/routines/create")
def routines_create(
        request: Request,
        routine_name: str = Form(...),
        routine_description: Optional[str] = Form(None),

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
):
    filters = {
        "category_main_cb": _to_int(category_main_cb),
        "category_type_cb": _to_int(category_type_cb),
        "category_sub_cb": [_to_int(s) for s in (category_sub_cb or []) if _to_int(s) is not None],
        "locality_country_id": _to_int(locality_country_id) or 112,
        "locality_region_id": _to_int(locality_region_id),
        "locality_district_id": _to_int(locality_district_id),
        "locality_search_name": _clean_str(locality_search_name),
        "locality_entity_type": _clean_str(locality_entity_type),
        "locality_entity_id": _to_int(locality_entity_id),
        "locality_radius": _to_float(locality_radius),
        "description_search": _clean_str(description_search),
        "estate_area_from": _to_int(estate_area_from),
        "estate_area_to": _to_int(estate_area_to),
        "price_from": _to_int(price_from) if price_mode != "per_m2" else None,
        "price_to": _to_int(price_to) if price_mode != "per_m2" else None,
        "price_m2_from": _to_int(price_from) if price_mode == "per_m2" else None,
        "price_m2_to": _to_int(price_to) if price_mode == "per_m2" else None,
        "advert_age_to": _to_int(advert_age_to),
        "price_mode": price_mode,
        "limit": 60,
        "offset": 0,
    }

    routine = create_routine(name=routine_name, description=routine_description, filters=filters)
    create_db_if_needed(routine_db_path(routine["id"]))

    return RedirectResponse(url=f"/routines/{routine['id']}", status_code=303)


@app.get("/routines", response_class=HTMLResponse)
def routines_list(request: Request):
    routines = list_routines()
    return templates.TemplateResponse("routines.html", {"request": request, "routines": routines})


@app.get("/routines/{routine_id}", response_class=HTMLResponse)
def routines_detail(request: Request, routine_id: str):
    routine = get_routine(routine_id)
    if not routine:
        return HTMLResponse("Rutina nenalezena.", status_code=404)
    return templates.TemplateResponse("routine_detail.html", {"request": request, "routine": routine})


@app.post("/routines/{routine_id}/update_name")
def routines_update_name(routine_id: str, new_name: str = Form(...)):
    ok = update_routine_name(routine_id, new_name)
    if not ok:
        return HTMLResponse("Rutina nenalezena.", status_code=404)
    return RedirectResponse(url=f"/routines/{routine_id}", status_code=303)


@app.post("/routines/{routine_id}/update_description")
def routines_update_description(routine_id: str, new_description: str = Form(...)):
    from src.routines_storage import update_routine_description
    ok = update_routine_description(routine_id, new_description)
    if not ok:
        return HTMLResponse("Rutina nenalezena.", status_code=404)
    return RedirectResponse(url=f"/routines/{routine_id}", status_code=303)


@app.post("/routines/{routine_id}/delete")
def routines_delete(routine_id: str):
    ok = delete_routine(routine_id)
    if not ok:
        return HTMLResponse("Rutina nenalezena.", status_code=404)
    return RedirectResponse(url="/routines", status_code=303)


@app.post("/routines/{routine_id}/run", response_class=HTMLResponse)
def routines_run(
        request: Request,
        routine_id: str,
        only_new: Optional[str] = Form(None),
):
    routine = get_routine(routine_id)
    if not routine:
        return HTMLResponse("Rutina nenalezena.", status_code=404)

    f = routine["filters"]
    dbp = routine_db_path(routine_id)
    create_db_if_needed(dbp)

    # --- FULL SYNC pokaždé při spuštění ---
    print(f"[SYNC] Spouštím full sync pro rutinu {routine_id}")
    base_filters_full = dict(
        category_main_cb=f.get("category_main_cb"),
        category_type_cb=f.get("category_type_cb"),
        category_sub_cb=f.get("category_sub_cb"),
        locality_country_id=f.get("locality_country_id") or 112,
        locality_region_id=f.get("locality_region_id"),
        locality_district_id=f.get("locality_district_id"),
        locality_search_name=f.get("locality_search_name"),
        locality_entity_type=f.get("locality_entity_type"),
        locality_entity_id=f.get("locality_entity_id"),
        locality_radius=f.get("locality_radius"),
        estate_area_from=f.get("estate_area_from"),
        estate_area_to=f.get("estate_area_to"),
        price_from=f.get("price_from"),
        price_to=f.get("price_to"),
        price_m2_from=f.get("price_m2_from"),
        price_m2_to=f.get("price_m2_to"),
        advert_age_to=f.get("advert_age_to"),
        limit=60,
        offset=0,
    )

    all_items, _ = search_multiple_keywords(
        base_filters=base_filters_full,
        description_search=f.get("description_search"),
        fetch_all=True,
    )
    upsert_items(all_items, dbp)
    print(f"[SYNC] Uloženo {len(all_items)} inzerátů do {dbp.name}")

    # --- ZOBRAZ VŠECHNY VÝSLEDKY NAJEDNOU ---
    cards = []
    for r in all_items:
        cards.append(to_card(r))

    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "items": all_items,
            "cards": cards,
            "pagination": {
                "total": len(all_items),
                "limit": 0,
                "offset": 0,
                "has_prev": False,
                "has_next": False,
                "prev_offset": 0,
                "next_offset": 0,
            },
            "filters": {
                **{k: f.get(k) for k in f.keys()},
                "routine_id": routine_id,
                "only_new": bool(only_new),
            },
        },
    )


@app.get("/routines/{routine_id}/ad/{hash_id}", response_class=HTMLResponse)
def ad_detail(request: Request, routine_id: str, hash_id: int):
    db_path = routine_db_path(routine_id)
    if not db_path.exists():
        return HTMLResponse("Databáze rutiny neexistuje.", status_code=404)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("""
        SELECT * FROM estates WHERE hash_id = ?
    """, (hash_id,))
    row = cur.fetchone()
    if not row:
        con.close()
        return HTMLResponse("Inzerát nenalezen.", status_code=404)

    estate = dict(row)

    # načteme historii cen
    cur.execute("""
        SELECT ts, price_czk FROM price_history WHERE hash_id = ? ORDER BY ts ASC
    """, (hash_id,))
    history = [{"ts": r[0], "price_czk": r[1]} for r in cur.fetchall()]
    con.close()

    # Použijeme to_card na rekonstrukci kanonické URL
    from src.sreality_client import to_card
    sreality_url = to_card({
        "hash_id": estate["hash_id"],
        "advert_name": estate["advert_name"],
        "category_main_cb": {"value": estate["category_main"]},
        "category_type_cb": {"value": estate["category_type"]},
        "category_sub_cb": {"value": estate["category_sub"]},
        "locality": {
            "city": estate.get("city"),
            "district": estate.get("district"),
            "region": estate.get("region_name"),
        },
        "seo": {"locality": estate.get("city") or ""},
    })["url"]

    return templates.TemplateResponse(
        "ad_detail.html",
        {
            "request": request,
            "routine_id": routine_id,
            "estate": estate,
            "history": history,
            "sreality_url": sreality_url,
        },
    )


# =========================================
#           PŮVODNÍ AD-HOC RUTINA
# =========================================
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
        only_new: Optional[str] = Form(None),
):
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
        description_search=_clean_str(description_search),
        estate_area_from=ea_from,
        estate_area_to=ea_to,
        price_from=None if use_price_m2 else p_from,
        price_to=None if use_price_m2 else p_to,
        price_m2_from=p_from if use_price_m2 else None,
        price_m2_to=p_to if use_price_m2 else None,
        advert_age_to=adv_age,
    )

    items, _ = search_multiple_keywords(
        base_filters=base_filters,
        description_search=description_search,
        fetch_all=True,
    )

    # ad-hoc používá globální DB (historické chování)
    known_ids = set(get_known_ids())
    new_items = [x for x in items if x.get("hash_id") and x["hash_id"] not in known_ids]
    upsert_items(items)

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
