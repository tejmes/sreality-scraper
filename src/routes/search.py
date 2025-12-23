from typing import List, Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from src.core.auth import is_admin, get_current_user_id
from src.core.templates import render
from src.core.utils import to_int, to_float, clean_str
from src.services.search_service import search_multiple_keywords
from src.infrastructure.sreality_client import to_card, save_json

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/search", status_code=303)


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    if not get_current_user_id(request):
        return RedirectResponse("/login", status_code=303)
    return render(request, "index.html")


@router.post("/search", response_class=HTMLResponse)
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
    cm = to_int(category_main_cb)

    ct = [int(x) for x in category_type_cb] if category_type_cb else []
    subs = [to_int(s) for s in category_sub_cb or [] if to_int(s) is not None]
    rooms = [to_int(r) for r in room_count_cb or [] if to_int(r) is not None]

    country = to_int(locality_country_id) or 112
    reg = to_int(locality_region_id)
    dist = to_int(locality_district_id)
    radius = to_float(locality_radius)

    ua_from = to_int(usable_area_from)
    ua_to = to_int(usable_area_to)
    ea_from = to_int(estate_area_from)
    ea_to = to_int(estate_area_to)

    p_from = to_int(price_from)
    p_to = to_int(price_to)
    adv_age = to_int(advert_age_to)

    lim = to_int(limit) or 60
    off = to_int(offset) or 0

    use_price_m2 = (price_mode == "per_m2")

    base_filters = dict(
        category_main_cb=cm,
        category_type_cb=ct,
        category_sub_cb=subs,
        room_count_cb=rooms,
        locality_country_id=country,
        locality_region_id=reg,
        locality_district_id=dist,
        locality_search_name=clean_str(locality_search_name),
        locality_entity_type=clean_str(locality_entity_type),
        locality_entity_id=to_int(locality_entity_id),
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
