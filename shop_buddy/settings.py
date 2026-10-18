"""Runtime configuration loaded from .env without exposing secrets."""
from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


load_dotenv(override=True)


@dataclass(frozen=True)
class Settings:
    database_path: Path
    openai_api_key: str | None
    openai_base_url: str | None
    openai_model: str
    gemini_api_key: str | None
    gemini_model: str
    workflow_mode: str

    @property
    def configured_provider(self) -> str:
        if self.openai_api_key:
            return "openai"
        if self.gemini_api_key:
            return "gemini"
        return "local"


def get_settings() -> Settings:
    raw_path = os.getenv("SHOP_BUDDY_DB_PATH", "data/shop_buddy.db")
    active_provider = os.getenv("SHOP_BUDDY_ACTIVE_AI_PROVIDER", "").strip().lower()
    openai_key = os.getenv("OPENAI_API_KEY") or None
    gemini_key = os.getenv("GEMINI_API_KEY") or None
    if active_provider == "openai":
        gemini_key = None
    elif active_provider == "gemini":
        openai_key = None
    elif active_provider in {"none", "local"}:
        openai_key = None
        gemini_key = None
    return Settings(
        database_path=Path(raw_path).resolve(),
        openai_api_key=openai_key,
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        gemini_api_key=gemini_key,
        # Gemini 2.0 Flash was shut down on 2026-06-01. Keep a current,
        # configurable default so adding only GEMINI_API_KEY is sufficient.
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        workflow_mode=(os.getenv("SHOP_BUDDY_WORKFLOW_OVERRIDE") or os.getenv("WORKFLOW_MODE", "langgraph")).lower(),
    )

