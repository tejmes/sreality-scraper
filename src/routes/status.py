from fastapi import APIRouter
from fastapi.responses import JSONResponse
from datetime import datetime

from src.core.config import ENVIRONMENT
from src.scheduler.scheduler import scheduler

router = APIRouter()


@router.get("/health")
def health():
    return {
        "status": "ok",
        "time": datetime.utcnow().isoformat(),
        "env": ENVIRONMENT,
    }


@router.get("/debug/scheduler")
def scheduler_status():
    return JSONResponse([
        {
            "id": j.id,
            "name": j.name,
            "next_run_time": str(j.next_run_time),
        }
        for j in scheduler.get_jobs()
    ])
