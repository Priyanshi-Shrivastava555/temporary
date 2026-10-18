"""Ensure the evaluator has a valid LangFlow API key persisted in .env."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import stat
import tempfile

import requests


LANGFLOW_URL = os.getenv("LANGFLOW_URL", "http://127.0.0.1:7860").rstrip("/")
KEY_PATTERN = re.compile(r"^\s*LANGFLOW_API_KEY\s*=")


def response_detail(response: requests.Response) -> str:
    try:
        detail = response.json()
    except ValueError:
        detail = response.text
    return " ".join(str(detail).split())[:1000] or "<empty response body>"


def key_is_valid(api_key: str) -> bool:
    if not api_key:
        return False
    try:
        response = requests.get(
            f"{LANGFLOW_URL}/api/v1/flows/",
            headers={"x-api-key": api_key, "Accept": "application/json"},
            timeout=30,
            allow_redirects=False,
        )
    except requests.RequestException:
        return False
    return response.ok and "json" in response.headers.get("content-type", "").lower()


def create_api_key() -> str:
    session = requests.Session()
    login = session.get(f"{LANGFLOW_URL}/api/v1/auto_login", timeout=30)
    if not login.ok:
        raise RuntimeError(
            f"LangFlow auto-login failed with HTTP {login.status_code}: {response_detail(login)}"
        )
    try:
        access_token = login.json()["access_token"]
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f"LangFlow auto-login returned an invalid response: {response_detail(login)}") from exc
    session.headers["Authorization"] = f"Bearer {access_token}"
    created = session.post(
        f"{LANGFLOW_URL}/api/v1/api_key/",
        json={"name": "Shop Buddy Evaluator"},
        timeout=30,
    )
    if not created.ok:
        raise RuntimeError(
            f"LangFlow API-key creation failed with HTTP {created.status_code}: {response_detail(created)}"
        )
    try:
        api_key = str(created.json()["api_key"]).strip()
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f"LangFlow API-key creation returned an invalid response: {response_detail(created)}") from exc
    if not api_key:
        raise RuntimeError("LangFlow created an empty API key.")
    return api_key


def persist_env_key(env_file: Path, api_key: str) -> None:
    try:
        original = env_file.read_text(encoding="utf-8")
        original_mode = stat.S_IMODE(env_file.stat().st_mode)
    except FileNotFoundError:
        original = ""
        original_mode = 0o600

    replacement = f"LANGFLOW_API_KEY={shlex.quote(api_key)}"
    lines: list[str] = []
    replaced = False
    for line in original.splitlines():
        if KEY_PATTERN.match(line):
            if not replaced:
                lines.append(replacement)
                replaced = True
            continue
        lines.append(line)
    if not replaced:
        if lines and lines[-1]:
            lines.append("")
        lines.append(replacement)

    env_file.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{env_file.name}.", dir=env_file.parent, text=True)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        os.chmod(temporary, original_mode)
        os.replace(temporary, env_file)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()

    api_key = os.getenv("LANGFLOW_API_KEY", "").strip()
    if key_is_valid(api_key):
        persist_env_key(args.env_file, api_key)
        print("LangFlow evaluator API key is valid and persisted in .env.")
        return 0

    api_key = create_api_key()
    if not key_is_valid(api_key):
        raise RuntimeError("LangFlow created an API key, but the server rejected it during verification.")
    persist_env_key(args.env_file, api_key)
    print("LangFlow evaluator API key was created, verified, and persisted in .env.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, requests.RequestException) as exc:
        print(f"Could not configure LANGFLOW_API_KEY: {exc}", file=os.sys.stderr)
        raise SystemExit(1) from exc
