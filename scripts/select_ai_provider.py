"""Validate AI credentials and print the provider the launchers should use.

Only the final provider name is written to stdout so shell launchers can safely
capture it. Diagnostics go to stderr and never include credentials.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.parse import quote, urlparse

import requests


TIMEOUT_SECONDS = 25
PLACEHOLDERS = {
    "changeme",
    "change-me",
    "dummy",
    "example",
    "none",
    "null",
    "replace-me",
    "test",
    "your-api-key",
    "your-key-here",
}


def _key(name: str) -> str:
    value = os.getenv(name, "").strip()
    normalized = value.lower().strip("<>{}[]()'\"")
    if not value or normalized in PLACEHOLDERS or normalized.startswith(("your_", "your-", "replace_")):
        return ""
    return value


def _error_text(response: requests.Response) -> str:
    try:
        payload: Any = response.json()
        if isinstance(payload, dict):
            error = payload.get("error", payload.get("detail", payload))
            if isinstance(error, dict):
                message = error.get("message") or error.get("detail") or json.dumps(error, default=str)
            else:
                message = str(error)
        else:
            message = str(payload)
    except ValueError:
        message = response.text
    return " ".join(message.split())[:500] or "no response details"


def _probe_openai() -> tuple[bool, str]:
    api_key = _key("OPENAI_API_KEY")
    if not api_key:
        return False, "OPENAI_API_KEY is empty or a placeholder"
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "temperature": 0,
                "max_tokens": 2,
            },
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return False, f"network failure ({type(exc).__name__})"
    if response.ok:
        return True, f"model {model} accepted a chat request"
    if response.status_code in {401, 403}:
        host = urlparse(base_url).netloc or base_url
        if host.lower() == "api.openai.com":
            return False, f"HTTP {response.status_code}: OPENAI_API_KEY was rejected by OpenAI"
        return False, (
            f"HTTP {response.status_code}: OPENAI_API_KEY was rejected by configured proxy {host}; "
            "use a token issued for that proxy, or use https://api.openai.com/v1 with an OpenAI-issued key"
        )
    return False, f"HTTP {response.status_code}: {_error_text(response)}"


def _probe_gemini() -> tuple[bool, str]:
    api_key = _key("GEMINI_API_KEY")
    if not api_key:
        return False, "GEMINI_API_KEY is empty or a placeholder"
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model, safe='')}:generateContent"
    )
    try:
        response = requests.post(
            endpoint,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": "Reply with OK."}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 2},
            },
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return False, f"network failure ({type(exc).__name__})"
    if response.ok:
        return True, f"model {model} accepted a generate-content request"
    return False, f"HTTP {response.status_code}: {_error_text(response)}"


def select_provider() -> str:
    preference = os.getenv("SHOP_BUDDY_AI_PROVIDER", "auto").strip().lower() or "auto"
    if preference not in {"auto", "openai", "gemini"}:
        print(
            "WARNING: SHOP_BUDDY_AI_PROVIDER must be auto, openai, or gemini; using auto.",
            file=sys.stderr,
        )
        preference = "auto"

    candidates = [preference] if preference != "auto" else ["openai", "gemini"]
    probes = {"openai": _probe_openai, "gemini": _probe_gemini}
    for provider in candidates:
        valid, detail = probes[provider]()
        if valid:
            print(f"AI provider ready: {provider} ({detail}).", file=sys.stderr)
            return provider
        print(f"AI provider unavailable: {provider} ({detail}).", file=sys.stderr)

    if preference != "auto":
        print(
            f"WARNING: forced provider {preference} is unavailable; AI framework execution will be skipped.",
            file=sys.stderr,
        )
    else:
        print(
            "WARNING: no configured AI provider passed validation; deterministic API operations remain available.",
            file=sys.stderr,
        )
    return "none"


def main() -> int:
    print(select_provider())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
