from dotenv import load_dotenv

load_dotenv()

from pathlib import Path
from typing import List, Optional, Dict
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx
import json
import traceback
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone
import sqlite3
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
import os
from datetime import datetime

from src.sreality_client import (
    build_query,
    fetch_page,
    fetch_all_pages,
    extract_items,
    extract_pagination,
    to_card,
    save_json
)
from src.routines_storage import (
    list_routines,
    get_routine,
    create_routine,
    update_routine_name,
    delete_routine,
    routine_db_path,
    update_routine_last_run
)
from src.storage import (
    upsert_items,
    get_known_ids,
    create_db_if_needed,
    ensure_new_ads_table,
    mark_new_ads
)

from src.users_storage import (
    init_users_db,
    ensure_admin,
    get_user_by_username,
    verify_user_password,
    create_user,
    list_users,
    delete_user,
    reset_password
)

from src.email_utils import send_email
from src.email_builder import build_new_ads_email

# === Načtení .env souboru ===
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# === Načtení .env souboru ===
ROOT = Path(__file__).resolve().parent
env_path = ROOT / ".env"

if not env_path.exists():
    raise RuntimeError(f"❌ Soubor .env nebyl nalezen v {env_path}")

load_dotenv(env_path)


def require_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise RuntimeError(f"❌ Chybí proměnná prostředí: {var_name}")
    return value


SECRET_KEY = require_env("SECRET_KEY")
ADMIN_USERNAME = require_env("ADMIN_USERNAME")
ADMIN_PASSWORD = require_env("ADMIN_PASSWORD")
ENVIRONMENT = os.getenv("ENV", "production")


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


def is_admin(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


def _ensure_can_access_routine(request: Request, routine: dict):
    """
    Admin může vše, běžný uživatel jen své rutiny.
    Vrací RedirectResponse nebo HTMLResponse, pokud nemá přístup.
    """
    if not routine:
        return HTMLResponse("Rutina nenalezena.", status_code=404)
    if is_admin(request):
        return None
    if routine.get("user_id") != get_current_user_id(request):
        return HTMLResponse("Přístup odepřen.", status_code=403)
    return None


def get_current_user(request: Request) -> Optional[str]:
    return request.session.get("username")


def get_current_user_id(request: Request) -> Optional[int]:
    return request.session.get("user_id")


def require_admin(request: Request):
    """Redirects to /login if not logged in as admin."""
    if not request.session.get("is_admin"):
        return RedirectResponse("/login", status_code=303)


def search_multiple_keywords(
        *,
        base_filters: dict,
        description_search: Optional[str] = None,
        fetch_all: bool = False,
) -> tuple[list[dict], dict]:
    """
    Spustí jedno nebo více vyhledávání na Sreality.cz podle klíčových slov
    a sjednotí výsledky bez duplicit. Používá stejné filtry pro ruční i plánované rutiny.
    """

    # Pokud description_search není explicitně předáno, vezmi ho z filtrů rutiny
    if description_search is None and "description_search" in base_filters:
        description_search = base_filters["description_search"]

    # Odstraň klíče, které API nezná nebo které jsou interní
    INVALID_KEYS = {
        "description_search",  # zpracovává se zvlášť
        "price_mode",  # jen interní přepínač
        "limit", "offset",  # API má vlastní stránkování
        "user_id",  # rutina metadata
        "id", "name", "created_at", "last_run", "schedule"  # další meta-informace
    }
    base_filters = {k: v for k, v in base_filters.items() if k not in INVALID_KEYS}

    # Rozdělení popisu na víc klíčových slov
    keywords = _split_keywords(description_search)
    all_results = []
    last_limit = base_filters.get("limit", 60)
    total_from_api = 0
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

    # Odstranění duplicit podle hash_id
    seen = set()
    unique = []
    for r in all_results:
        hid = r.get("hash_id")
        if hid and hid not in seen:
            unique.append(r)
            seen.add(hid)

    total_final = len(unique) if multi_search else total_from_api or len(unique)
    return unique, {"total": total_final, "limit": last_limit}


# --- FastAPI a šablony ---
app = FastAPI(title="Sreality Scraper – hledání a rutina")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


def render(request: Request, template: str, context: dict = None):
    ctx = context or {}
    ctx["request"] = request
    ctx["is_admin"] = bool(request.session.get("is_admin"))
    ctx["username"] = request.session.get("username")
    return templates.TemplateResponse(template, ctx)


def require_login(request: Request):
    """Dependency that redirects to /login if user is not logged in."""
    if not request.session.get("user_id"):
        raise RedirectResponse("/login", status_code=303)


# =========================================
#           STRÁNKA 1 – HLEDÁNÍ
# =========================================
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)
    # Po přihlášení přesměruj rovnou na stránku vyhledávání
    return RedirectResponse("/search", status_code=303)


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    if not get_current_user_id(request):
        return RedirectResponse("/login", status_code=303)
    return render(request, "index.html")


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
        category_type_cb: Optional[List[str]] = Form(None),
        category_sub_cb: Optional[List[str]] = Form(None),
        room_count_cb: Optional[List[str]] = Form(None),

        locality_country_id: Optional[str] = Form(None),
        locality_region_id: Optional[str] = Form(None),
        locality_district_id: Optional[str] = Form(None),

        locality_search_name: Optional[str] = Form(None),
        locality_entity_type: Optional[str] = Form(None),
        locality_entity_id: Optional[str] = Form(None),
        locality_radius: Optional[str] = Form(None),

        description_search: Optional[str] = Form(None),

        usable_area_from: Optional[str] = Form(None),
        usable_area_to: Optional[str] = Form(None),

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

    # multi-výběr typů nabídky (prodej, pronajem, drazby...)
    if category_type_cb:
        ct = [int(x) for x in category_type_cb]
    else:
        ct = []

    subs = [_to_int(s) for s in category_sub_cb or [] if _to_int(s) is not None]
    rooms = [_to_int(r) for r in (room_count_cb or []) if _to_int(r) is not None]

    country = _to_int(locality_country_id) or 112
    reg = _to_int(locality_region_id)
    dist = _to_int(locality_district_id)
    radius = _to_float(locality_radius)
    ua_from = _to_int(usable_area_from)
    ua_to = _to_int(usable_area_to)
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
        room_count_cb=rooms,
        locality_country_id=country,
        locality_region_id=reg,
        locality_district_id=dist,
        locality_search_name=_clean_str(locality_search_name),
        locality_entity_type=_clean_str(locality_entity_type),
        locality_entity_id=_to_int(locality_entity_id),
        locality_radius=radius,
        usable_area_from=ua_from,
        usable_area_to=ua_to,
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

    return render(
        request,
        "results.html",
        {
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
    if not get_current_user_id(request):
        return RedirectResponse("/login", status_code=303)
    return render(request, "routine.html")


@app.post("/routines/create")
def routines_create(
        request: Request,
        routine_name: str = Form(...),
        routine_description: Optional[str] = Form(None),

        schedule_type: str = Form("manual"),
        schedule_times: Optional[str] = Form(None),
        schedule_days: Optional[str] = Form(None),

        emails: Optional[str] = Form(None),

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
        usable_area_from: Optional[str] = Form(None),
        usable_area_to: Optional[str] = Form(None),
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
        "usable_area_from": _to_int(usable_area_from),
        "usable_area_to": _to_int(usable_area_to),
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

    # --- nový jednoduchý systém plánování ---
    times = [t.strip() for t in (schedule_times or "").split(",") if t.strip()]

    if times:
        schedule = {"type": "daily", "times": times}
    else:
        schedule = None

    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)

    routine = create_routine(
        name=routine_name,
        description=routine_description,
        filters=filters,
        user_id=uid,
        schedule=schedule,
        emails=[e.strip() for e in (emails or "").split(",") if e.strip()],
    )

    create_db_if_needed(routine_db_path(routine["id"]))

    # --- okamžité naplánování nové rutiny bez restartu ---
    if schedule:
        try:
            sched = schedule
            typ = sched.get("type")
            times = sched.get("times", [])
            days = sched.get("days", [])
            for t in times:
                hour, minute = map(int, t.split(":"))
                if typ == "daily":
                    scheduler.add_job(run_routine_job, "cron",
                                      hour=hour, minute=minute,
                                      args=[routine], name=routine["id"])
                elif typ == "weekly" and days:
                    for d in days:
                        scheduler.add_job(run_routine_job, "cron",
                                          day_of_week=d, hour=hour, minute=minute,
                                          args=[routine], name=routine["id"])
            print(f"[SCHED] Přidána nová rutina (bez restartu): {routine['name']} → {sched}")
        except Exception as e:
            print(f"[SCHED] Chyba při přidávání nové rutiny: {e}")
    return RedirectResponse(url=f"/routines/{routine['id']}", status_code=303)


@app.get("/routines", response_class=HTMLResponse)
def routines_list(request: Request):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)

    if is_admin(request):
        routines = list_routines()
        # Načteme mapu {user_id: username}
        users = {u["id"]: u["username"] for u in list_users()}
        # Doplníme autora
        for r in routines:
            r["author_name"] = users.get(r.get("user_id"), "?")
    else:
        routines = list_routines(user_id=uid)

    return render(request, "routines.html", {"routines": routines})


@app.get("/routines/{routine_id}", response_class=HTMLResponse)
def routines_detail(request: Request, routine_id: str):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)
    routine = get_routine(routine_id)
    deny = _ensure_can_access_routine(request, routine)
    if deny: return deny
    return render(request, "routine_detail.html", {"routine": routine})


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


@app.post("/routines/{routine_id}/update_emails")
def routines_update_emails(request: Request, routine_id: str, emails: str = Form("")):
    from src.routines_storage import _load_index, _save_index

    doc = _load_index()
    for r in doc["routines"]:
        if r["id"] == routine_id:
            r["emails"] = [e.strip() for e in emails.split(",") if e.strip()]
            break

    _save_index(doc)
    return RedirectResponse(url=f"/routines/{routine_id}", status_code=303)


@app.post("/routines/{routine_id}/delete")
def routines_delete(request: Request, routine_id: str):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)

    routine = get_routine(routine_id)
    deny = _ensure_can_access_routine(request, routine)
    if deny:
        return deny

    ok = delete_routine(routine_id)
    if not ok:
        return HTMLResponse("Rutina nenalezena.", status_code=404)

    # --- odstranit naplánovaný job ze scheduleru ---
    for job in scheduler.get_jobs():
        if job.name == routine_id:
            scheduler.remove_job(job.id)
            print(f"[SCHED] Job rutiny {routine_id} odebrán ze scheduleru.")

    return RedirectResponse(url="/routines", status_code=303)


@app.post("/routines/{routine_id}/run", response_class=HTMLResponse)
def routines_run(
        request: Request,
        routine_id: str,
        only_new: Optional[str] = Form(None),
):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)

    routine = get_routine(routine_id)
    deny = _ensure_can_access_routine(request, routine)
    if deny:
        return deny

    f = routine["filters"]
    dbp = routine_db_path(routine_id)
    create_db_if_needed(dbp)

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
        usable_area_from=f.get("usable_area_from"),
        usable_area_to=f.get("usable_area_to"),
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

    # 🟢 Stáhni aktuální inzeráty
    all_items, _ = search_multiple_keywords(
        base_filters=base_filters_full,
        description_search=f.get("description_search"),
        fetch_all=True,
    )

    # 🟢 Získej známé ID inzerátů z databáze konkrétní rutiny
    known_ids = set(get_known_ids(dbp))

    # 🟢 Vyfiltruj jen nové inzeráty
    new_items = [x for x in all_items if x.get("hash_id") and x["hash_id"] not in known_ids]

    mark_new_ads(new_items, dbp)

    # 🟢 Ulož vše (aby se ceny aktualizovaly)
    upsert_items(all_items, dbp)
    print(f"[SYNC] Uloženo {len(all_items)} inzerátů do {dbp.name}")

    update_routine_last_run(routine_id)

    # 🟢 Podle volby zobraz jen nové nebo všechny
    show_only_new = bool(only_new)
    displayed_items = new_items if show_only_new else all_items

    cards = [to_card(r) for r in displayed_items]

    return RedirectResponse(f"/routines/{routine_id}/results", status_code=303)


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

    ref = request.headers.get("referer", "")

    # Pokud referer vede na POST run → vrať na GET výsledky rutiny
    if ("/run" in ref) or (ref == ""):
        ref = f"/routines/{routine_id}/results"

    return render(
        request,
        "ad_detail.html",
        {
            "routine_id": routine_id,
            "estate": estate,
            "history": history,
            "sreality_url": sreality_url,
            "back_to_results_url": ref,
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
        usable_area_from: Optional[str] = Form(None),
        usable_area_to: Optional[str] = Form(None),
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
    ua_from = _to_int(usable_area_from)
    ua_to = _to_int(usable_area_to)
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
        usable_area_from=ua_from,
        usable_area_to=ua_to,
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

    return render(
        request,
        "results.html",
        {
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
                "usable_area_from": ua_from,
                "usable_area_to": ua_to,
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


# =========================================
#           ADMIN LOGIN & DASHBOARD
# =========================================

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if is_admin(request):
        return RedirectResponse("/admin", status_code=303)
    return render(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = verify_user_password(username, password)
    if not user:
        return render(request, "login.html", {"error": "Invalid credentials"})

    # uložit do session
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["is_admin"] = bool(user["is_admin"])

    # redirect podle role
    if user["is_admin"]:
        return RedirectResponse("/admin", status_code=303)
    else:
        return RedirectResponse("/search", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/user/reset_password", response_class=HTMLResponse)
def user_reset_password_form(request: Request):
    """Zobrazí formulář pro změnu hesla přihlášeného uživatele."""
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)

    return render(request, "user_reset_password.html", {"error": None})


@app.post("/user/reset_password", response_class=HTMLResponse)
def user_reset_password_submit(
        request: Request,
        old_password: str = Form(...),
        new_password: str = Form(...),
        confirm_password: str = Form(...),
):
    """Změna hesla pro aktuálně přihlášeného uživatele."""
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)

    user = get_user_by_username(get_current_user(request))
    if not user:
        return HTMLResponse("Uživatel nenalezen.", status_code=404)

    # 1️⃣ Ověření starého hesla
    if not verify_user_password(user["username"], old_password):
        return render(request, "user_reset_password.html", {"error": "Původní heslo je nesprávné."})

    # 2️⃣ Ověření nového hesla
    if new_password != confirm_password:
        return render(request, "user_reset_password.html", {"error": "Nová hesla se neshodují."})

    # 3️⃣ Změna v DB
    reset_password(uid, new_password)
    return render(request, "user_reset_password.html", {"error": "✅ Heslo bylo úspěšně změněno."})


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)
    return render(request, "admin.html", {"username": get_current_user(request)})


# =========================================
#           ADMIN – SPRÁVA UŽIVATELŮ
# =========================================

@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)
    users = list_users()
    return render(request, "admin_users.html", {"users": users})


@app.post("/admin/users/create")
def admin_create_user(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        admin_flag: Optional[str] = Form(None, alias="is_admin"),  # ← alias opraví jméno z HTML
):
    try:
        print("[DEBUG] Session:", request.session)
        if not is_admin(request):
            print("[DEBUG] Not admin → redirect")
            return RedirectResponse("/login", status_code=303)

        print(f"[DEBUG] Creating user: username={username}, admin_flag={admin_flag}")
        result = create_user(username, password, bool(admin_flag))
        print(f"[DEBUG] Result of create_user: {result}")
        return RedirectResponse("/admin/users", status_code=303)

    except Exception as e:
        print("[ERROR] Exception while creating user:")
        traceback.print_exc()
        return HTMLResponse(f"<h1>Internal Server Error</h1><pre>{e}</pre>", status_code=500)


@app.post("/admin/users/{user_id}/delete")
def admin_delete_user(request: Request, user_id: int):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)
    delete_user(user_id)
    return RedirectResponse("/admin/users", status_code=303)


@app.post("/admin/users/{user_id}/reset")
def admin_reset_password(request: Request, user_id: int):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)
    reset_password(user_id, "1234")
    return RedirectResponse("/admin/users", status_code=303)


@app.post("/routines/{routine_id}/update_schedule")
def routines_update_schedule(
        routine_id: str,
        schedule_times: Optional[str] = Form(None),
):
    from src.routines_storage import _load_index, _save_index, get_routine
    doc = _load_index()
    routine = None
    for r in doc["routines"]:
        if r["id"] == routine_id:
            routine = r
            # nový jednoduchý systém – každé HH:MM je "daily"
            times = [t.strip() for t in schedule_times.split(",") if t.strip()] if schedule_times else []
            if times:
                r["schedule"] = {"type": "daily", "times": times}
            else:
                r["schedule"] = None
            break
    _save_index(doc)

    # === aktualizace APScheduleru ===
    if routine:
        # smazat staré joby stejné rutiny
        for job in scheduler.get_jobs():
            if job.name == routine_id:
                scheduler.remove_job(job.id)

        sched = routine.get("schedule")
        if sched:
            try:
                if isinstance(sched, str) and "@" in sched:
                    typ, t = sched.split("@")
                    sched = {"type": typ, "times": [t]}
                if isinstance(sched, str):
                    sched = json.loads(sched)

                typ = sched.get("type")
                times = sched.get("times", [])
                days = sched.get("days", [])
                for t in times:
                    hour, minute = map(int, t.split(":"))
                    if typ == "daily":
                        scheduler.add_job(
                            run_routine_job, "cron",
                            hour=hour, minute=minute, args=[routine],
                            name=routine_id
                        )
                    elif typ == "weekly" and days:
                        for d in days:
                            scheduler.add_job(
                                run_routine_job, "cron",
                                day_of_week=d, hour=hour, minute=minute, args=[routine],
                                name=routine_id
                            )
                print(f"[SCHED] Aktualizována rutina '{routine['name']}' – {sched}")
            except Exception as e:
                print(f"[SCHED] Chyba při registraci nové rutiny {routine['name']}: {e}")

    return RedirectResponse(url=f"/routines/{routine_id}", status_code=303)


# =========================================
#           AUTOMATICKÉ SPUŠTĚNÍ RUTIN
# =========================================

scheduler = BackgroundScheduler(timezone=timezone("Europe/Prague"))
scheduler.start()
print("[SCHED] Scheduler spuštěn (globální inicializace).")


def run_routine_job(routine):
    import os
    print("[CRON] PID:", os.getpid())

    print(f"[CRON] Spouštím rutinu: {routine['name']}")
    f = routine["filters"]
    dbp = routine_db_path(routine["id"])
    create_db_if_needed(dbp)

    all_items, _ = search_multiple_keywords(
        base_filters=f,
        fetch_all=True,
    )

    # 🟢 Nejprve zjistíme známé ID
    known_ids = set(get_known_ids(dbp))

    # 🟢 Uložíme všechny inzeráty (včetně aktualizací)
    upsert_items(all_items, dbp)

    # 🟢 Zjistíme které jsou nové a uložíme do new_estates
    new_items = [x for x in all_items if x.get("hash_id") and x["hash_id"] not in known_ids]
    mark_new_ads(new_items, dbp)

    emails = routine.get("emails") or []

    if new_items and emails:
        body = build_new_ads_email(routine, new_items)

        send_email(
            to=emails,
            subject=f"Nové inzeráty – {routine['name']}",
            text=body
        )

        print(f"[EMAIL] Odeslán email ({len(new_items)} nových inzerátů) → {emails}")

    update_routine_last_run(routine["id"])
    print(f"[CRON] Hotovo: {routine['name']} – {len(all_items)} inzerátů, nových {len(new_items)}")


@app.on_event("startup")
def startup_all():
    # inicializace uživatelů
    init_users_db()
    ensure_admin(ADMIN_USERNAME, ADMIN_PASSWORD)

    # načtení rutin
    routines = list_routines()
    print(f"[STARTUP] Načítám {len(routines)} rutin pro naplánování.")
    for r in routines:
        sched = r.get("schedule")
        if not sched:
            continue
        try:
            if isinstance(sched, str) and "@" in sched:
                typ, t = sched.split("@")
                sched = {"type": typ, "times": [t]}
            if isinstance(sched, str):
                sched = json.loads(sched)

            typ = sched.get("type")
            times = sched.get("times", [])
            days = sched.get("days", [])
            for t in times:
                hour, minute = map(int, t.split(":"))
                if typ == "daily":
                    scheduler.add_job(run_routine_job, "cron", hour=hour, minute=minute, args=[r], name=r["id"])
                elif typ == "weekly" and days:
                    for d in days:
                        scheduler.add_job(
                            run_routine_job,
                            "cron",
                            day_of_week=d,
                            hour=hour,
                            minute=minute,
                            args=[r],
                            name=r["id"],
                        )
            print(f"[SCHED] Přidána rutina: {r['name']} → {sched}")
        except Exception as e:
            print(f"[SCHED] Chyba při přidávání rutiny {r['name']}: {e}")

    print(f"[SCHED] Scheduler spuštěn, jobs: {len(scheduler.get_jobs())}")

    print("[SCHED] Aktivní naplánované joby:")
    for j in scheduler.get_jobs():
        print(f"   • {j.name} → {j.next_run_time}")


@app.get("/debug/scheduler")
def debug_scheduler():
    jobs = scheduler.get_jobs()
    return JSONResponse([
        {"id": j.id, "name": j.name, "next_run_time": str(j.next_run_time)} for j in jobs
    ])


@app.post("/routines/{routine_id}/mark_all_seen")
def mark_all_seen(request: Request, routine_id: str):
    """Označí všechny nové inzeráty v dané rutině jako zhlédnuté."""
    db_path = routine_db_path(routine_id)
    ensure_new_ads_table(db_path)

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("UPDATE new_estates SET seen = 1;")
    con.commit()
    con.close()

    return RedirectResponse(url=f"/routines/{routine_id}/new", status_code=303)


@app.get("/routines/{routine_id}/new", response_class=HTMLResponse)
def routines_new(request: Request, routine_id: str):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)
    routine = get_routine(routine_id)
    deny = _ensure_can_access_routine(request, routine)
    if deny: return deny

    db_path = routine_db_path(routine_id)
    ensure_new_ads_table(db_path)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("""
        SELECT e.*
        FROM estates e
        JOIN new_estates n ON e.hash_id = n.hash_id
        WHERE n.seen = 0
        ORDER BY n.first_detected DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    con.close()

    cards = []
    for r in rows:
        card_input = {
            "hash_id": r["hash_id"],
            "advert_name": r["advert_name"],
            "locality": {
                "city": r.get("city"),
                "district": r.get("district"),
                "region": r.get("region_name"),
            },
            "category_main_cb": {"value": r.get("category_main")},
            "category_type_cb": {"value": r.get("category_type")},
            "category_sub_cb": {"value": r.get("category_sub")},

            # 🔥 DŮLEŽITÉ – tato položka opravuje cenu:
            "price_czk": r.get("price_czk"),

            "seo": {"locality": r.get("city") or ""},
        }
        cards.append(to_card(card_input))

    return render(
        request,
        "results.html",
        {
            "items": rows,
            "cards": cards,
            "pagination": {"total": len(rows), "limit": 0, "offset": 0, "has_prev": False, "has_next": False},
            "filters": {"routine_id": routine_id, "only_new": True},
        },
    )


@app.get("/routines/{routine_id}/results", response_class=HTMLResponse)
def routines_results_page(request: Request, routine_id: str):
    routine = get_routine(routine_id)
    if not routine:
        return HTMLResponse("Rutina nenalezena.", status_code=404)

    dbp = routine_db_path(routine_id)
    con = sqlite3.connect(dbp)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM estates")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()

    cards = [to_card({
        "hash_id": r["hash_id"],
        "advert_name": r["advert_name"],
        "locality": {
            "city": r.get("city"),
            "district": r.get("district"),
            "region": r.get("region_name"),
        },
        "category_main_cb": {"value": r.get("category_main")},
        "category_type_cb": {"value": r.get("category_type")},
        "category_sub_cb": {"value": r.get("category_sub")},
        "price_czk": r.get("price_czk"),
        "seo": {"locality": r.get("city") or ""},
    }) for r in rows]

    return render(
        request,
        "results.html",
        {
            "items": rows,
            "cards": cards,
            "pagination": {
                "total": len(rows),
                "limit": 0,
                "offset": 0,
                "has_prev": False,
                "has_next": False,
            },
            "filters": {"routine_id": routine_id},
            "back_link": f"/routines/{routine_id}"
        },
    )


@app.post("/routines/{routine_id}/ad/{hash_id}/mark_seen")
def mark_seen(request: Request, routine_id: str, hash_id: int):
    db_path = routine_db_path(routine_id)
    ensure_new_ads_table(db_path)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("UPDATE new_estates SET seen = 1 WHERE hash_id = ?", (hash_id,))
    con.commit()
    con.close()
    return RedirectResponse(url=f"/routines/{routine_id}/new", status_code=303)


@app.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password_custom(request: Request, user_id: int, new_password: str = Form(...)):
    """Admin ručně nastaví nové heslo uživateli přes JS prompt."""
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)

    reset_password(user_id, new_password)
    return RedirectResponse("/admin/users", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat(), "env": ENVIRONMENT}
