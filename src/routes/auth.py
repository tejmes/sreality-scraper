from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from src.core.auth import is_admin, get_current_user, get_current_user_id
from src.core.templates import render
from src.persistence.users_storage import (
    verify_user_password,
    get_user_by_username,
    reset_password,
)

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if is_admin(request):
        return RedirectResponse("/admin", status_code=303)
    return render(request, "login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
def login_submit(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
):
    user = verify_user_password(username, password)
    if not user:
        return render(request, "login.html", {"error": "Invalid credentials"})

    # uložit do session
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["is_admin"] = bool(user["is_admin"])
    request.session["team_id"] = user.get("team_id")

    if user["is_admin"]:
        return RedirectResponse("/admin", status_code=303)
    else:
        return RedirectResponse("/search", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@router.get("/user/reset_password", response_class=HTMLResponse)
def user_reset_password_form(request: Request):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)

    return render(request, "user_reset_password.html", {"error": None})


@router.post("/user/reset_password", response_class=HTMLResponse)
def user_reset_password_submit(
        request: Request,
        old_password: str = Form(...),
        new_password: str = Form(...),
        confirm_password: str = Form(...),
):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login", status_code=303)

    user = get_user_by_username(get_current_user(request))
    if not user:
        return HTMLResponse("Uživatel nenalezen.", status_code=404)

    if not verify_user_password(user["username"], old_password):
        return render(
            request,
            "user_reset_password.html",
            {"error": "Původní heslo je nesprávné."},
        )

    if new_password != confirm_password:
        return render(
            request,
            "user_reset_password.html",
            {"error": "Nová hesla se neshodují."},
        )

    reset_password(uid, new_password)
    return render(
        request,
        "user_reset_password.html",
        {"error": "Heslo bylo úspěšně změněno."},
    )
