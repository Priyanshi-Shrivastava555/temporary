"""LangFlow language-model component with OpenAI-to-Gemini fallback."""
from __future__ import annotations

import os

from langchain_core.language_models import BaseLanguageModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from lfx.custom import Component
from lfx.io import FloatInput, Output, SecretStrInput, StrInput
from pydantic import SecretStr


class ShopBuddyModelComponent(Component):
    """Use the provider that the launcher validated, with direct-run fallback."""

    display_name = "Shop Buddy AI Model"
    description = "Uses the startup-validated OpenAI or Gemini provider without storing keys in the flow export."
    name = "ShopBuddyModel"
    icon = "BrainCircuit"
    trace_type = "model"

    inputs = [
        SecretStrInput(
            name="openai_api_key",
            display_name="OpenAI API Key Override",
            required=False,
            advanced=True,
        ),
        StrInput(
            name="openai_base_url",
            display_name="OpenAI Base URL Override",
            required=False,
            advanced=True,
        ),
        StrInput(
            name="openai_model",
            display_name="OpenAI Model",
            value="gpt-4o-mini",
            advanced=True,
        ),
        SecretStrInput(
            name="gemini_api_key",
            display_name="Gemini API Key Override",
            required=False,
            advanced=True,
        ),
        StrInput(
            name="gemini_model",
            display_name="Gemini Model",
            value="gemini-3.5-flash",
            advanced=True,
        ),
        FloatInput(
            name="temperature",
            display_name="Temperature",
            value=0.2,
            advanced=True,
        ),
    ]
    outputs = [
        Output(
            name="model",
            display_name="Language Model",
            method="build_model",
            types=["LanguageModel"],
        )
    ]

    @staticmethod
    def _secret(value: object) -> str:
        if isinstance(value, SecretStr):
            return value.get_secret_value().strip()
        return str(value or "").strip()

    def build_model(self) -> BaseLanguageModel:
        active_provider = os.getenv("SHOP_BUDDY_ACTIVE_AI_PROVIDER", "").strip().lower()
        openai_key = self._secret(self.openai_api_key) or os.getenv("OPENAI_API_KEY", "").strip()
        if openai_key and active_provider not in {"gemini", "none", "local"}:
            return ChatOpenAI(
                api_key=SecretStr(openai_key),
                base_url=(self.openai_base_url or os.getenv("OPENAI_BASE_URL", "")).strip() or None,
                model=(self.openai_model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")).strip(),
                temperature=self.temperature,
            )

        gemini_key = self._secret(self.gemini_api_key) or os.getenv("GEMINI_API_KEY", "").strip()
        if gemini_key and active_provider not in {"openai", "none", "local"}:
            return ChatGoogleGenerativeAI(
                api_key=SecretStr(gemini_key),
                model=(self.gemini_model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")).strip(),
                temperature=self.temperature,
            )

        raise ValueError(
            "No validated AI provider is active. Set a valid OPENAI_API_KEY or GEMINI_API_KEY in .env, "
            "then restart with ./start.sh --phase1."
        )
