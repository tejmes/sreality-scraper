from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional, List
import json
import uuid
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "routines"
DATA_DIR.mkdir(parents=True, exist_ok=True)

INDEX_PATH = DATA_DIR / "index.json"


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _load_index() -> Dict[str, Any]:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {"routines": []}


def _save_index(doc: Dict[str, Any]) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def list_routines() -> List[Dict[str, Any]]:
    return _load_index().get("routines", [])


def get_routine(routine_id: str) -> Optional[Dict[str, Any]]:
    for r in list_routines():
        if r["id"] == routine_id:
            return r
    return None


def create_routine(*, name: str, filters: Dict[str, Any], description: Optional[str] = None) -> Dict[str, Any]:
    rid = uuid.uuid4().hex[:12]
    doc = _load_index()
    routine = {
        "id": rid,
        "name": name.strip() or "Bez názvu",
        "description": description.strip() if description else "",
        "filters": filters,
        "created_at": _now_iso(),
        "schedule": None,
        "emails": [],
        "active": True,
    }
    doc["routines"].append(routine)
    _save_index(doc)

    rdir = DATA_DIR / rid
    rdir.mkdir(parents=True, exist_ok=True)

    return routine


def update_routine_name(routine_id: str, new_name: str) -> bool:
    doc = _load_index()
    changed = False
    for r in doc.get("routines", []):
        if r["id"] == routine_id:
            r["name"] = new_name.strip() or r["name"]
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
