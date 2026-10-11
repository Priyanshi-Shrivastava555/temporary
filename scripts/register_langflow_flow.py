"""Create or update the saved Shop Buddy flow in a running LangFlow server."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests


LANGFLOW_URL = os.getenv("LANGFLOW_URL", "http://127.0.0.1:7860").rstrip("/")
FLOW_FILE = Path(__file__).resolve().parents[1] / "langflow" / "shop_buddy.flow.json"


def authenticated_session() -> requests.Session:
    session = requests.Session()
    last_error: Exception | None = None
    for _attempt in range(60):
        try:
            response = session.get(f"{LANGFLOW_URL}/api/v1/auto_login", timeout=10)
            response.raise_for_status()
            session.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
            return session
        except (requests.RequestException, KeyError) as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"LangFlow did not become API-ready: {last_error}")


def main() -> int:
    flow = json.loads(FLOW_FILE.read_text(encoding="utf-8"))
    session = authenticated_session()
    response = session.get(f"{LANGFLOW_URL}/api/v1/flows/", timeout=30)
    response.raise_for_status()
    existing = next(
        (
            item
            for item in response.json()
            if item.get("id") == flow.get("id")
            or item.get("endpoint_name") == flow.get("endpoint_name")
            or item.get("name") == flow.get("name")
        ),
        None,
    )

    if existing:
        flow["id"] = existing["id"]
        saved = session.put(f"{LANGFLOW_URL}/api/v1/flows/{existing['id']}", json=flow, timeout=120)
        action = "updated"
    else:
        saved = session.post(f"{LANGFLOW_URL}/api/v1/flows/", json=flow, timeout=120)
        action = "created"
    saved.raise_for_status()
    payload = saved.json()
    print(f"LangFlow flow {action}: {payload.get('name', flow['name'])} ({payload.get('id', flow.get('id'))})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, requests.RequestException, RuntimeError) as exc:
        print(f"Could not register Shop Buddy in LangFlow: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

