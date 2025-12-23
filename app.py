from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from src.core.config import (
    SECRET_KEY,
    ADMIN_USERNAME,
    ADMIN_PASSWORD,
    ROOT,
)
from src.routes.status import router as status_router
from src.routes.adhoc import router as adhoc_router
from src.routes.admin import router as admin_router
from src.routes.auth import router as auth_router
from src.routes.autocomplete import router as autocomplete_router
from src.routes.routines_crud import router as routines_crud_router
from src.routes.routines_list import router as routines_list_router
from src.routes.routines_run import router as routines_run_router
from src.routes.search import router as search_router
from src.scheduler.startup import schedule_existing_routines
from src.persistence.users_storage import (
    init_users_db,
    ensure_admin,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_users_db()
    ensure_admin(ADMIN_USERNAME, ADMIN_PASSWORD)
    schedule_existing_routines()

    yield


app = FastAPI(title="Sreality Scraper", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

app.include_router(status_router)
app.include_router(adhoc_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(autocomplete_router)
app.include_router(routines_crud_router)
app.include_router(routines_list_router)
app.include_router(routines_run_router)
app.include_router(search_router)
