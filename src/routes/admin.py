from typing import Optional

import traceback
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from src.core.auth import is_admin, get_current_user, get_current_user_id
from src.core.templates import render
from src.users_storage import (
    create_user,
    list_users,
    delete_user,
    reset_password,
    set_team,
    list_team_members,
    get_user_by_id,
)
from src.teams_storage import (
    list_teams,
    get_team,
    create_team,
    delete_team,
)
from src.routines_storage import list_routines

router = APIRouter()


# ==========================
# ADMIN DASHBOARD
# ==========================

@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)
    return render(request, "admin.html", {"username": get_current_user(request)})


# ==========================
# ADMIN – UŽIVATELÉ
# ==========================

@router.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)
    users = list_users()
    return render(request, "admin_users.html", {"users": users})


@router.post("/admin/users/create")
def admin_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    admin_flag: Optional[str] = Form(None, alias="is_admin"),
):
    try:
        if not is_admin(request):
            return RedirectResponse("/login", status_code=303)

        create_user(username, password, bool(admin_flag))
        return RedirectResponse("/admin/users", status_code=303)

    except Exception as e:
        traceback.print_exc()
        return HTMLResponse(
            f"<h1>Internal Server Error</h1><pre>{e}</pre>",
            status_code=500,
        )


@router.post("/admin/users/{user_id}/delete")
def admin_delete_user(request: Request, user_id: int):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)
    delete_user(user_id)
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/reset")
def admin_reset_password(request: Request, user_id: int):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)
    reset_password(user_id, "1234")
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password_custom(
    request: Request,
    user_id: int,
    new_password: str = Form(...),
):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)
    reset_password(user_id, new_password)
    return RedirectResponse("/admin/users", status_code=303)


# ==========================
# ADMIN – TÝMY
# ==========================

@router.get("/admin/teams", response_class=HTMLResponse)
def admin_teams(request: Request):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)
    teams = list_teams()
    return render(request, "admin_teams.html", {
        "teams": teams,
        "username": get_current_user(request),
    })


@router.post("/admin/teams/create")
def admin_teams_create(request: Request, name: str = Form(...)):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)
    create_team(name)
    return RedirectResponse("/admin/teams", status_code=303)


@router.get("/admin/teams/{team_id}", response_class=HTMLResponse)
def admin_team_detail(request: Request, team_id: int):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)

    team = get_team(team_id)
    if not team:
        return HTMLResponse("Tým nenalezen.", status_code=404)

    users = list_users()
    members = [u for u in users if u.get("team_id") == team_id]
    available = [u for u in users if u.get("team_id") != team_id]

    return render(request, "admin_team_detail.html", {
        "team": team,
        "members": members,
        "available_users": available,
        "username": get_current_user(request),
    })


@router.post("/admin/teams/{team_id}/add_user")
def admin_team_add_user(
    request: Request,
    team_id: int,
    user_id: int = Form(...),
):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)

    team = get_team(team_id)
    if not team:
        return HTMLResponse("Tým nenalezen.", status_code=404)

    set_team(user_id, team_id)
    return RedirectResponse(f"/admin/teams/{team_id}", status_code=303)


@router.post("/admin/teams/{team_id}/remove_user")
def admin_team_remove_user(
    request: Request,
    team_id: int,
    user_id: int = Form(...),
):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)

    team = get_team(team_id)
    if not team:
        return HTMLResponse("Tým nenalezen.", status_code=404)

    set_team(user_id, None)
    return RedirectResponse(f"/admin/teams/{team_id}", status_code=303)


@router.post("/admin/teams/{team_id}/delete")
def admin_team_delete(request: Request, team_id: int):
    if not is_admin(request):
        return RedirectResponse("/login", status_code=303)

    delete_team(team_id)
    return RedirectResponse("/admin/teams", status_code=303)


# ==========================
# TEAM PAGE
# ==========================

@router.get("/team", response_class=HTMLResponse)
def team_page(request: Request):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)

    user = get_user_by_id(uid)
    if not user or user.get("team_id") is None:
        return HTMLResponse("Nejste členem žádného týmu.", status_code=403)

    team_id = user["team_id"]
    team = get_team(team_id)
    if not team:
        return HTMLResponse("Tým nenalezen.", status_code=404)

    members = list_team_members(team_id)
    member_ids = {m["id"] for m in members}

    all_routines = list_routines()
    team_routines = [r for r in all_routines if r.get("user_id") in member_ids]

    users_by_id = {m["id"]: m for m in members}
    routines_by_user = {}

    for r in team_routines:
        uid = r.get("user_id")
        routines_by_user.setdefault(uid, []).append(r)

    return render(request, "team.html", {
        "team": team,
        "members": members,
        "routines_by_user": routines_by_user,
        "users_by_id": users_by_id,
    })
