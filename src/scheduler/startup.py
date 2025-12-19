import json

from src.scheduler.scheduler import scheduler
from src.scheduler.jobs import run_routine_job
from src.routines_storage import list_routines


def schedule_existing_routines():
    routines = list_routines()
    print(f"[STARTUP] Načítám {len(routines)} rutin pro naplánování.")

    for r in routines:
        sched = r.get("schedule")
        if not sched:
            continue
        try:
            if isinstance(sched, str) and "@" in sched:
                typ, t = sched.split("@")
                sched = {"type": typ, "times": [t]}
            if isinstance(sched, str):
                sched = json.loads(sched)

            typ = sched.get("type")
            times = sched.get("times", [])
            days = sched.get("days", [])

            for t in times:
                hour, minute = map(int, t.split(":"))
                if typ == "daily":
                    scheduler.add_job(
                        run_routine_job,
                        "cron",
                        hour=hour,
                        minute=minute,
                        args=[r],
                        name=r["id"],
                    )
                elif typ == "weekly" and days:
                    for d in days:
                        scheduler.add_job(
                            run_routine_job,
                            "cron",
                            day_of_week=d,
                            hour=hour,
                            minute=minute,
                            args=[r],
                            name=r["id"],
                        )

            print(f"[SCHED] Přidána rutina: {r['name']} → {sched}")
        except Exception as e:
            print(f"[SCHED] Chyba při přidávání rutiny {r['name']}: {e}")

    print(f"[SCHED] Scheduler spuštěn, jobs: {len(scheduler.get_jobs())}")

    print("[SCHED] Aktivní naplánované joby:")
    for j in scheduler.get_jobs():
        print(f"   • {j.name} → {j.next_run_time}")
