from types import SimpleNamespace

from shop_buddy.llm import LLMResponseWriter
from shop_buddy.settings import Settings


def test_gemini_is_tried_when_openai_is_unavailable(tmp_path, monkeypatch):
    class BrokenOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
            )

    class FakeGeminiClient:
        def __init__(self, **_kwargs):
            self.models = SimpleNamespace(
                generate_content=lambda **_kwargs: SimpleNamespace(text="Gemini fallback response")
            )

    import openai
    from google import genai

    monkeypatch.setattr(openai, "OpenAI", BrokenOpenAI)
    monkeypatch.setattr(genai, "Client", FakeGeminiClient)
    settings = Settings(
        database_path=tmp_path / "fallback.db",
        openai_api_key="configured-but-unavailable",
        openai_base_url="https://example.invalid/v1",
        openai_model="gpt-4o-mini",
        gemini_api_key="configured-gemini",
        gemini_model="gemini-3.5-flash",
        workflow_mode="langgraph",
    )

    message, provider = LLMResponseWriter(settings).write("show chairs", {"results": []})

    assert message == "Gemini fallback response"
    assert provider == "gemini"

