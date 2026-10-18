from scripts import select_ai_provider
from shop_buddy.settings import get_settings


def test_selector_falls_back_to_gemini(monkeypatch):
    monkeypatch.setenv("SHOP_BUDDY_AI_PROVIDER", "auto")
    monkeypatch.setattr(select_ai_provider, "_probe_openai", lambda: (False, "HTTP 401"))
    monkeypatch.setattr(select_ai_provider, "_probe_gemini", lambda: (True, "ready"))

    assert select_ai_provider.select_provider() == "gemini"


def test_selector_returns_none_when_no_provider_works(monkeypatch):
    monkeypatch.setenv("SHOP_BUDDY_AI_PROVIDER", "auto")
    monkeypatch.setattr(select_ai_provider, "_probe_openai", lambda: (False, "missing"))
    monkeypatch.setattr(select_ai_provider, "_probe_gemini", lambda: (False, "missing"))

    assert select_ai_provider.select_provider() == "none"


def test_settings_use_only_startup_validated_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOP_BUDDY_DB_PATH", str(tmp_path / "provider.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "bad-openai")
    monkeypatch.setenv("GEMINI_API_KEY", "working-gemini")
    monkeypatch.setenv("SHOP_BUDDY_ACTIVE_AI_PROVIDER", "gemini")

    settings = get_settings()

    assert settings.openai_api_key is None
    assert settings.gemini_api_key == "working-gemini"
    assert settings.configured_provider == "gemini"
