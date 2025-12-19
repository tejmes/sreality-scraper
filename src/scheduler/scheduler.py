from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone

scheduler = BackgroundScheduler(timezone=timezone("Europe/Prague"))
scheduler.start()

print("[SCHED] Scheduler spuštěn (globální inicializace).")
