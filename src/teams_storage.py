import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from zoneinfo import ZoneInfo
from filelock import FileLock

from src.users_storage import list_team_members, set_team

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "teams"
DATA_DIR.mkdir(parents=True, exist_ok=True)

INDEX_PATH = DATA_DIR / "index.json"


def _now_iso() -> str:
    now = datetime.now(ZoneInfo("Europe/Prague"))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _load_index() -> Dict[str, Any]:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {"teams": []}


def _save_index(doc: Dict[str, Any]) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(INDEX_PATH) + ".lock"):
        INDEX_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def list_teams() -> List[Dict[str, Any]]:
    return _load_index().get("teams", [])


def get_team(team_id: int) -> Optional[Dict[str, Any]]:
    for t in list_teams():
        if t["id"] == team_id:
            return t
    return None


def create_team(name: str) -> Dict[str, Any]:
    doc = _load_index()
    teams = doc.get("teams", [])
    new_id = 1
    if teams:
        new_id = max(t["id"] for t in teams) + 1

    team = {
        "id": new_id,
        "name": name.strip(),
        "created_at": _now_iso(),
    }
    teams.append(team)
    doc["teams"] = teams
    _save_index(doc)
    return team


def delete_team(team_id: int) -> bool:
    doc = _load_index()
    teams = doc.get("teams", [])
    before = len(teams)

    new_teams = [t for t in teams if t["id"] != team_id]
    if len(new_teams) == before:
        return False

    doc["teams"] = new_teams

    members = list_team_members(team_id)
    for u in members:
        set_team(u["id"], None)

    _save_index(doc)
    return True
