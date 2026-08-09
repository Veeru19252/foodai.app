"""
FoodAI - Configuration
======================
Reads MySQL connection settings from a local `.env` file (gitignored) or the
process environment. Real credentials belong in `.env`, never in git.

Settings (with defaults):
    MYSQL_HOST      127.0.0.1
    MYSQL_PORT      3306
    MYSQL_USER      root
    MYSQL_PASSWORD  (empty)
    MYSQL_DATABASE  foodai
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"


def _load_dotenv() -> None:
    """Minimal .env loader (KEY=VALUE lines; no extra dependencies)."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "foodai")


def mysql_config() -> dict:
    """Return the keyword args for pymysql.connect()."""
    return {
        "host": MYSQL_HOST,
        "port": MYSQL_PORT,
        "user": MYSQL_USER,
        "password": MYSQL_PASSWORD,
        "database": MYSQL_DATABASE,
        "charset": "utf8mb4",
    }
