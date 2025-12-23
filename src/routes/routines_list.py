from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.core.auth import (
    is_admin,
    get_current_user_id,
    ensure_can_access_routine,
)
from src.core.templates import render
from src.persistence.routines_storage import (
    list_routines,
    get_routine,
)
from src.persistence.users_storage import list_users

router = APIRouter()


@router.get("/routine", response_class=HTMLResponse)
def routine_index(request: Request):
    if not get_current_user_id(request):
        return RedirectResponse("/login", status_code=303)
    return render(request, "routine.html")


@router.get("/routines", response_class=HTMLResponse)
def routines_list(request: Request):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)

    if is_admin(request):
        routines = list_routines()
        users = {u["id"]: u["username"] for u in list_users()}
        for r in routines:
            r["author_name"] = users.get(r.get("user_id"), "?")
    else:
        routines = list_routines(user_id=uid)

    return render(request, "routines.html", {"routines": routines})


@router.get("/routines/{routine_id}", response_class=HTMLResponse)
def routines_detail(request: Request, routine_id: str):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)

    routine = get_routine(routine_id)
    deny = ensure_can_access_routine(request, routine)
    if deny:
        return deny

    return render(request, "routine_detail.html", {"routine": routine})
