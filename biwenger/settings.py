from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    email: str
    password: str
    token: str
    league_id: str
    user_id: str
    app_version: str
    competition: str
    telegram_bot_token: str
    telegram_chat_id: str
    dry_run: bool
    budget_safety_margin: int
    daily_briefing_hour: int
    xai_api_key: str
    xai_model: str
    data_dir: Path

    @property
    def has_password_login(self) -> bool:
        return bool(self.email and self.password)

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def load_settings() -> Settings:
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    return Settings(
        email=_env("BIWENGER_EMAIL"),
        password=_env("BIWENGER_PASSWORD"),
        token=_env("BIWENGER_TOKEN"),
        league_id=_env("BIWENGER_LEAGUE_ID"),
        user_id=_env("BIWENGER_USER_ID"),
        app_version=_env("BIWENGER_APP_VERSION", "631"),
        competition=_env("BIWENGER_COMPETITION", "la-liga"),
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
        dry_run=_env_bool("DRY_RUN", True),
        budget_safety_margin=_env_int("BUDGET_SAFETY_MARGIN", 1_000_000),
        daily_briefing_hour=_env_int("DAILY_BRIEFING_HOUR", 10),
        xai_api_key=_env("XAI_API_KEY"),
        xai_model=_env("XAI_MODEL", "grok-4.5"),
        data_dir=data_dir,
    )


settings = load_settings()


def set_telegram_chat_id(chat_id: str) -> None:
    """Guarda el chat_id en memoria y en el .env."""
    global settings
    object.__setattr__(settings, "telegram_chat_id", str(chat_id))
    path = ROOT / ".env"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if "TELEGRAM_CHAT_ID=" in text:
        lines = []
        for line in text.splitlines():
            if line.startswith("TELEGRAM_CHAT_ID="):
                lines.append(f"TELEGRAM_CHAT_ID={chat_id}")
            else:
                lines.append(line)
        text = "\n".join(lines) + "\n"
    else:
        text = text.rstrip() + f"\nTELEGRAM_CHAT_ID={chat_id}\n"
    path.write_text(text, encoding="utf-8")
