import sqlite3
from typing import Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from src.core.auth import get_current_user_id, _ensure_can_access_routine
from src.core.templates import render
from src.services.search_service import search_multiple_keywords
from src.persistence.routines_storage import (
    get_routine,
    routine_db_path,
    update_routine_last_run,
)
from src.persistence.storage import (
    create_db_if_needed,
    get_known_ids,
    upsert_items,
    ensure_new_ads_table,
    mark_new_ads,
)
from src.infrastructure.sreality_client import to_card

router = APIRouter()


@router.post("/routines/{routine_id}/run", response_class=HTMLResponse)
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

    all_items, _ = search_multiple_keywords(
        base_filters=f,
        description_search=f.get("description_search"),
        fetch_all=True,
    )

    known_ids = set(get_known_ids(dbp))
    new_items = [
        x for x in all_items
        if x.get("hash_id") and x["hash_id"] not in known_ids
    ]

    mark_new_ads(new_items, dbp)
    upsert_items(all_items, dbp)

    update_routine_last_run(routine_id)

    show_only_new = bool(only_new)
    displayed_items = new_items if show_only_new else all_items
    cards = [to_card(r) for r in displayed_items]

    return render(
        request,
        "results.html",
        {
            "items": displayed_items,
            "cards": cards,
            "pagination": {
                "total": len(displayed_items),
                "limit": 0,
                "offset": 0,
                "has_prev": False,
                "has_next": False,
            },
            "filters": {
                "routine_id": routine_id,
                "only_new": show_only_new,
            },
        },
    )


@router.get("/routines/{routine_id}/results", response_class=HTMLResponse)
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

    cards = [
        to_card({
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
        })
        for r in rows
    ]

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
            "back_link": f"/routines/{routine_id}",
        },
    )


@router.get("/routines/{routine_id}/new", response_class=HTMLResponse)
def routines_new(request: Request, routine_id: str):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)

    routine = get_routine(routine_id)
    deny = _ensure_can_access_routine(request, routine)
    if deny:
        return deny

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
            "pagination": {
                "total": len(rows),
                "limit": 0,
                "offset": 0,
                "has_prev": False,
                "has_next": False,
            },
            "filters": {
                "routine_id": routine_id,
                "only_new": True,
            },
        },
    )


@router.post("/routines/{routine_id}/mark_all_seen")
def mark_all_seen(request: Request, routine_id: str):
    db_path = routine_db_path(routine_id)
    ensure_new_ads_table(db_path)

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("UPDATE new_estates SET seen = 1;")
    con.commit()
    con.close()

    return RedirectResponse(f"/routines/{routine_id}/new", status_code=303)


@router.post("/routines/{routine_id}/ad/{hash_id}/mark_seen")
def mark_seen(request: Request, routine_id: str, hash_id: int):
    db_path = routine_db_path(routine_id)
    ensure_new_ads_table(db_path)

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        "UPDATE new_estates SET seen = 1 WHERE hash_id = ?",
        (hash_id,),
    )
    con.commit()
    con.close()

    return RedirectResponse(f"/routines/{routine_id}/new", status_code=303)


@router.get("/routines/{routine_id}/ad/{hash_id}", response_class=HTMLResponse)
def ad_detail(request: Request, routine_id: str, hash_id: int):
    db_path = routine_db_path(routine_id)
    if not db_path.exists():
        return HTMLResponse("Databáze rutiny neexistuje.", status_code=404)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute("SELECT * FROM estates WHERE hash_id = ?", (hash_id,))
    row = cur.fetchone()
    if not row:
        con.close()
        return HTMLResponse("Inzerát nenalezen.", status_code=404)

    estate = dict(row)

    cur.execute(
        "SELECT ts, price_czk FROM price_history WHERE hash_id = ? ORDER BY ts ASC",
        (hash_id,),
    )
    history = [{"ts": r[0], "price_czk": r[1]} for r in cur.fetchall()]
    con.close()

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
    if ("/run" in ref) or not ref:
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
