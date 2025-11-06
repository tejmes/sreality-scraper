from pathlib import Path
from typing import Dict, Any, Optional, List
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "routines"
DATA_DIR.mkdir(parents=True, exist_ok=True)

INDEX_PATH = DATA_DIR / "index.json"


def _now_iso() -> str:
    now = datetime.now(ZoneInfo("Europe/Prague"))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _load_index() -> Dict[str, Any]:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {"routines": []}


def _save_index(doc: Dict[str, Any]) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def list_routines(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Vrátí seznam rutin. Pokud je zadán user_id, vrátí jen rutiny daného uživatele.
    """
    routines = _load_index().get("routines", [])
    if user_id is None:
        return routines
    return [r for r in routines if r.get("user_id") == user_id]


def get_routine(routine_id: str) -> Optional[Dict[str, Any]]:
    for r in list_routines():
        if r["id"] == routine_id:
            return r
    return None


def update_routine_last_run(routine_id: str) -> None:
    doc = _load_index()
    for r in doc.get("routines", []):
        if r["id"] == routine_id:
            r["last_run"] = _now_iso()
            break
    _save_index(doc)


def create_routine(
        *,
        name: str,
        filters: Dict[str, Any],
        description: Optional[str] = None,
        user_id: Optional[int],
        schedule: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Vytvoří novou rutinu. Každá rutina je vlastněna konkrétním uživatelem (user_id).
    """
    rid = uuid.uuid4().hex[:12]
    doc = _load_index()
    routine = {
        "id": rid,
        "name": name.strip() or "Bez názvu",
        "description": description.strip() if description else "",
        "filters": filters,
        "created_at": _now_iso(),
        "schedule": schedule,
        "last_run": None,
        "emails": [],
        "active": True,
        "user_id": user_id,
    }
    doc["routines"].append(routine)
    _save_index(doc)

    (DATA_DIR / rid).mkdir(parents=True, exist_ok=True)
    return routine


def update_routine_name(routine_id: str, new_name: str) -> bool:
    doc = _load_index()
    changed = False
    for r in doc.get("routines", []):
        if r["id"] == routine_id:
            r["name"] = new_name.strip()
            changed = True
            break
    if changed:
        _save_index(doc)
    return changed


def update_routine_description(routine_id: str, new_description: str) -> bool:
    doc = _load_index()
    changed = False
    for r in doc.get("routines", []):
        if r["id"] == routine_id:
            r["description"] = new_description.strip()
            changed = True
            break
    if changed:
        _save_index(doc)
    return changed


def delete_routine(routine_id: str) -> bool:
    doc = _load_index()
    before = len(doc.get("routines", []))
    doc["routines"] = [r for r in doc.get("routines", []) if r["id"] != routine_id]
    after = len(doc.get("routines", []))
    if before == after:
        return False
    _save_index(doc)

    # smazat i data adresář
    rdir = DATA_DIR / routine_id
    if rdir.exists():
        # bezpečné smazání celé složky
        for p in sorted(rdir.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        rdir.rmdir()
    return True


def routine_db_path(routine_id: str) -> Path:
    # Každá rutina má vlastní DB ve svém adresáři
    return (DATA_DIR / routine_id / "estates.sqlite3").resolve()
