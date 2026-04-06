from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    database_url: str = os.getenv("DATABASE_URL", "")
    poster_token: str = os.getenv("POSTER_TOKEN", "")
    tz: str = os.getenv("TZ", "Asia/Almaty")


config = Config()
