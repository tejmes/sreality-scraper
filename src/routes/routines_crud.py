from typing import Optional, List

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from datetime import datetime

from src.core.auth import get_current_user_id, ensure_can_access_routine
from src.core.utils import to_int, to_float, clean_str
from src.persistence.routines_storage import (
    create_routine,
    get_routine,
    delete_routine,
    update_routine_name,
    routine_db_path,
)
from src.persistence.storage import create_db_if_needed
from src.scheduler.scheduler import scheduler
from src.scheduler.jobs import run_routine_job

router = APIRouter()


@router.post("/routines/create")
def routines_create(
        request: Request,
        routine_name: str = Form(...),
        routine_description: Optional[str] = Form(None),

        schedule_type: str = Form("manual"),
        schedule_times: Optional[str] = Form(None),
        schedule_days: Optional[str] = Form(None),

        emails: Optional[str] = Form(None),

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
):
    filters = {
        "category_main_cb": to_int(category_main_cb),
        "category_type_cb": [int(x) for x in (category_type_cb or [])],
        "category_sub_cb": [to_int(s) for s in (category_sub_cb or []) if to_int(s) is not None],
        "room_count_cb": [to_int(r) for r in (room_count_cb or []) if to_int(r) is not None],
        "locality_country_id": to_int(locality_country_id) or 112,
        "locality_region_id": to_int(locality_region_id),
        "locality_district_id": to_int(locality_district_id),
        "locality_search_name": clean_str(locality_search_name),
        "locality_entity_type": clean_str(locality_entity_type),
        "locality_entity_id": to_int(locality_entity_id),
        "locality_radius": to_float(locality_radius),
        "description_search": clean_str(description_search),
        "usable_area_from": to_int(usable_area_from),
        "usable_area_to": to_int(usable_area_to),
        "estate_area_from": to_int(estate_area_from),
        "estate_area_to": to_int(estate_area_to),
        "price_from": to_int(price_from) if price_mode != "per_m2" else None,
        "price_to": to_int(price_to) if price_mode != "per_m2" else None,
        "price_m2_from": to_int(price_from) if price_mode == "per_m2" else None,
        "price_m2_to": to_int(price_to) if price_mode == "per_m2" else None,
        "advert_age_to": to_int(advert_age_to),
        "price_mode": price_mode,
        "limit": 60,
        "offset": 0,
    }

    times = [t.strip() for t in (schedule_times or "").split(",") if t.strip()]
    schedule = {"type": "daily", "times": times} if times else None

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

    if schedule:
        try:
            for t in schedule["times"]:
                hour, minute = map(int, t.split(":"))
                scheduler.add_job(
                    run_routine_job,
                    "cron",
                    hour=hour,
                    minute=minute,
                    args=[routine],
                    name=routine["id"],
                )
        except Exception as e:
            print(f"[SCHED] Chyba při přidávání nové rutiny: {e}")

    return RedirectResponse(f"/routines/{routine['id']}", status_code=303)


@router.post("/routines/{routine_id}/update_name")
def routines_update_name(routine_id: str, new_name: str = Form(...)):
    if not update_routine_name(routine_id, new_name):
        return HTMLResponse("Rutina nenalezena.", status_code=404)
    return RedirectResponse(f"/routines/{routine_id}", status_code=303)


@router.post("/routines/{routine_id}/update_description")
def routines_update_description(routine_id: str, new_description: str = Form(...)):
    from src.persistence.routines_storage import update_routine_description
    if not update_routine_description(routine_id, new_description):
        return HTMLResponse("Rutina nenalezena.", status_code=404)
    return RedirectResponse(f"/routines/{routine_id}", status_code=303)


@router.post("/routines/{routine_id}/update_emails")
def routines_update_emails(routine_id: str, emails: str = Form("")):
    from src.persistence.routines_storage import load_index, save_index

    doc = load_index()
    for r in doc["routines"]:
        if r["id"] == routine_id:
            r["emails"] = [e.strip() for e in emails.split(",") if e.strip()]
            break

    save_index(doc)
    return RedirectResponse(f"/routines/{routine_id}", status_code=303)


@router.post("/routines/{routine_id}/update")
def routines_update(
        request: Request,
        routine_id: str,
        routine_name: str = Form(...),
        routine_description: str = Form(""),
        schedule_times: str = Form(""),
        emails: str = Form(""),

        category_main_cb: str = Form(...),
        category_type_cb: List[str] = Form([]),
        category_sub_cb: List[str] = Form([]),
        room_count_cb: List[str] = Form([]),

        locality_country_id: str = Form(None),
        locality_region_id: str = Form(None),
        locality_district_id: Optional[str] = Form(None),
        locality_search_name: str = Form(None),
        locality_entity_type: str = Form(None),
        locality_entity_id: str = Form(None),
        locality_radius: str = Form(None),

        description_search: Optional[str] = Form(None),

        usable_area_from: str = Form(None),
        usable_area_to: str = Form(None),
        estate_area_from: str = Form(None),
        estate_area_to: str = Form(None),

        price_from: str = Form(None),
        price_to: str = Form(None),
        price_mode: str = Form("total"),
        advert_age_to: str = Form(None),
):
    from src.persistence.routines_storage import load_index, save_index

    doc = load_index()
    routine = next((r for r in doc["routines"] if r["id"] == routine_id), None)
    if not routine:
        return RedirectResponse("/routines", status_code=302)

    old_times = routine.get("schedule", {}).get("times", []) or []

    routine["name"] = routine_name
    routine["description"] = routine_description

    times = [t.strip() for t in schedule_times.split(",") if t.strip()]
    routine["schedule"] = {"type": "daily", "times": times} if times else None
    routine["emails"] = [e.strip() for e in emails.split(",") if e.strip()]

    entity_id = int(locality_entity_id) if locality_entity_id else None
    entity_type = locality_entity_type.strip() if locality_entity_type else None
    region_id = int(locality_region_id) if locality_region_id else None

    if entity_id:
        region_id = None

    routine["filters"] = {
        "category_main_cb": int(category_main_cb),
        "category_type_cb": [int(x) for x in category_type_cb],
        "category_sub_cb": [int(x) for x in category_sub_cb],
        "room_count_cb": [int(x) for x in room_count_cb],
        "locality_country_id": int(locality_country_id) if locality_country_id else None,
        "locality_region_id": region_id,
        "locality_district_id": int(locality_district_id) if locality_district_id else None,
        "locality_search_name": locality_search_name,
        "locality_entity_type": entity_type,
        "locality_entity_id": entity_id,
        "locality_radius": float(locality_radius) if locality_radius else None,
        "description_search": clean_str(description_search),
        "usable_area_from": int(usable_area_from) if usable_area_from else None,
        "usable_area_to": int(usable_area_to) if usable_area_to else None,
        "estate_area_from": int(estate_area_from) if estate_area_from else None,
        "estate_area_to": int(estate_area_to) if estate_area_to else None,
        "price_mode": price_mode,
        "price_from": int(price_from) if price_from else None,
        "price_to": int(price_to) if price_to else None,
        "advert_age_to": int(advert_age_to) if advert_age_to else None,
    }

    save_index(doc)

    added_times = set(times) - set(old_times)

    for job in scheduler.get_jobs():
        if job.id.startswith(f"{routine_id}_cron_"):
            scheduler.remove_job(job.id)

    now = datetime.now()

    for t in added_times:
        hour, minute = map(int, t.split(":"))

        run_at = now.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )

        if run_at > now:
            scheduler.add_job(
                run_routine_job,
                trigger="date",
                run_date=run_at,
                args=[routine],
                id=f"{routine_id}_once_{t}",
                replace_existing=True,
            )

    for t in times:
        hour, minute = map(int, t.split(":"))
        scheduler.add_job(
            run_routine_job,
            trigger="cron",
            hour=hour,
            minute=minute,
            args=[routine],
            id=f"{routine_id}_cron_{t}",
            replace_existing=True,
        )

    return RedirectResponse(f"/routines/{routine_id}", status_code=303)


@router.post("/routines/{routine_id}/delete")
def routines_delete(request: Request, routine_id: str):
    routine = get_routine(routine_id)
    deny = ensure_can_access_routine(request, routine)
    if deny:
        return deny

    if not delete_routine(routine_id):
        return HTMLResponse("Rutina nenalezena.", status_code=404)

    for job in scheduler.get_jobs():
        if job.name == routine_id:
            scheduler.remove_job(job.id)

    return RedirectResponse("/routines", status_code=303)
