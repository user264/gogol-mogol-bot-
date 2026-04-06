from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _fix_db_url(url: str) -> str:
    """Ensure async driver prefix for PostgreSQL URLs."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@dataclass(frozen=True)
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    database_url: str = _fix_db_url(os.getenv("DATABASE_URL", ""))
    poster_token: str = os.getenv("POSTER_TOKEN", "")
    tz: str = os.getenv("TZ", "Asia/Almaty")


config = Config()
