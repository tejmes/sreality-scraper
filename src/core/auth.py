from typing import Optional
from fastapi import Request
from fastapi.responses import RedirectResponse, HTMLResponse

from src.persistence.users_storage import get_user_by_id


def is_admin(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


def get_current_user(request: Request) -> Optional[str]:
    return request.session.get("username")


def get_current_user_id(request: Request) -> Optional[int]:
    return request.session.get("user_id")


def require_admin(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse("/login", status_code=303)


def require_login(request: Request):
    if not request.session.get("user_id"):
        raise RedirectResponse("/login", status_code=303)


def ensure_can_access_routine(request: Request, routine: dict):
    if not routine:
        return HTMLResponse("Rutina nenalezena.", status_code=404)

    uid = request.session.get("user_id")
    if not uid:
        return RedirectResponse("/login", status_code=303)

    is_admin_flag = request.session.get("is_admin", False)
    my_team = request.session.get("team_id")

    owner_id = routine.get("user_id")
    owner = get_user_by_id(owner_id)

    if is_admin_flag:
        return None

    if owner_id == uid:
        return None

    if my_team and owner and owner.get("team_id") == my_team:
        return None

    return HTMLResponse("Přístup odepřen.", status_code=403)
