from typing import List, Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from src.core.auth import get_current_user_id
from src.core.templates import render
from src.core.utils import _to_int, _to_float, _clean_str
from src.services.search_service import search_multiple_keywords
from src.sreality_client import to_card
from src.storage import upsert_items, get_known_ids

router = APIRouter()


# =========================================
#           PŮVODNÍ AD-HOC RUTINA
# =========================================

@router.post("/routine/run", response_class=HTMLResponse)
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
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)

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
    new_items = [
        x for x in items
        if x.get("hash_id") and x["hash_id"] not in known_ids
    ]

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
