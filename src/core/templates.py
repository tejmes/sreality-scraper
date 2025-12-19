from fastapi import Request
from fastapi.templating import Jinja2Templates

from src.core.config import ROOT

templates = Jinja2Templates(directory=str(ROOT / "templates"))


def render(request: Request, template: str, context: dict = None):
    ctx = context or {}
    ctx["request"] = request
    ctx["is_admin"] = bool(request.session.get("is_admin"))
    ctx["username"] = request.session.get("username")
    return templates.TemplateResponse(template, ctx)
