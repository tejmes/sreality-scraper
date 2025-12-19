from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

env_path = ROOT / ".env"

if not env_path.exists():
    raise RuntimeError(f"❌ Soubor .env nebyl nalezen v {env_path}")

load_dotenv(env_path)


def require_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise RuntimeError(f"❌ Chybí proměnná prostředí: {var_name}")
    return value


SECRET_KEY = require_env("SECRET_KEY")
ADMIN_USERNAME = require_env("ADMIN_USERNAME")
ADMIN_PASSWORD = require_env("ADMIN_PASSWORD")
ENVIRONMENT = os.getenv("ENV", "production")
