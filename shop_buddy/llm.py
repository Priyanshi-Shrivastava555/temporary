"""Optional response writer: OpenAI first, then Gemini, then local copy."""
from __future__ import annotations

import json
from typing import Any

from .settings import Settings


class LLMResponseWriter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def write(self, user_message: str, facts: dict[str, Any]) -> tuple[str | None, str]:
        """Return (message, provider). A failure safely falls back to local text."""
        prompt = (
            "You are Shop Buddy, a helpful UrbanNest Furnishings shopping concierge. "
            "Write a concise, warm response grounded strictly in these completed shopping results. "
            "Never invent stock, prices, or actions. Use 2-5 sentences and no markdown table.\n\n"
            f"Customer request: {user_message}\nCompleted results: {json.dumps(facts, default=str)}"
        )
        # Providers are attempted in priority order. In particular, a configured
        # but unavailable OpenAI gateway must not prevent Gemini from taking over.
        if self.settings.openai_api_key:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=self.settings.openai_api_key, base_url=self.settings.openai_base_url)
                response = client.chat.completions.create(
                    model=self.settings.openai_model,
                    messages=[{"role": "system", "content": "Be accurate and concise."}, {"role": "user", "content": prompt}],
                    temperature=0.35,
                    max_tokens=220,
                )
                text = response.choices[0].message.content
                if text:
                    return text.strip(), "openai"
            except Exception:
                pass
        if self.settings.gemini_api_key:
            try:
                from google import genai
                client = genai.Client(api_key=self.settings.gemini_api_key)
                response = client.models.generate_content(model=self.settings.gemini_model, contents=prompt)
                if response.text:
                    return response.text.strip(), "gemini"
            except Exception:
                pass
        return None, "local"

