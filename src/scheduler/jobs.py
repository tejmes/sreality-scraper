import os

from src.services.search_service import search_multiple_keywords
from src.persistence.storage import (
    upsert_items,
    get_known_ids,
    create_db_if_needed,
    mark_new_ads,
)
from src.persistence.routines_storage import routine_db_path, update_routine_last_run
from src.infrastructure.email_utils import send_email
from src.services.email_builder import build_new_ads_email


def run_routine_job(routine):
    print("[CRON] PID:", os.getpid())
    print(f"[CRON] Spouštím rutinu: {routine['name']}")

    f = routine["filters"]
    dbp = routine_db_path(routine["id"])
    create_db_if_needed(dbp)

    all_items, _ = search_multiple_keywords(
        base_filters=f,
        fetch_all=True,
    )

    known_ids = set(get_known_ids(dbp))
    upsert_items(all_items, dbp)

    new_items = [
        x for x in all_items
        if x.get("hash_id") and x["hash_id"] not in known_ids
    ]
    mark_new_ads(new_items, dbp)

    emails = routine.get("emails") or []

    if new_items and emails:
        body = build_new_ads_email(routine, new_items)

        send_email(
            to=emails,
            subject=f"Nové inzeráty – {routine['name']}",
            text=body
        )

        print(f"[EMAIL] Odeslán email ({len(new_items)} nových inzerátů) → {emails}")

    update_routine_last_run(routine["id"])
    print(
        f"[CRON] Hotovo: {routine['name']} – "
        f"{len(all_items)} inzerátů, nových {len(new_items)}"
    )
