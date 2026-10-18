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


def _flow_signature(flow: dict) -> tuple[frozenset[tuple], frozenset[tuple]]:
    """Return the stable graph shape, ignoring server-managed metadata."""
    data = flow.get("data") or {}
    nodes = frozenset(
        (node.get("id"), (node.get("data") or {}).get("type"))
        for node in data.get("nodes", [])
    )
    edges = frozenset(
        (edge.get("source"), edge.get("target"))
        for edge in data.get("edges", [])
    )
    return nodes, edges


def _update_flow(session: requests.Session, flow_id: str, flow: dict) -> requests.Response:
    """Support LangFlow releases that expose PATCH, PUT, or both."""
    url = f"{LANGFLOW_URL}/api/v1/flows/{flow_id}"
    rejected: list[str] = []
    for method in ("patch", "put"):
        response = session.request(method, url, json=flow, timeout=120)
        if response.status_code in {404, 405, 422}:
            rejected.append(f"{method.upper()}={response.status_code}")
            continue
        response.raise_for_status()
        return response
    raise RuntimeError(
        "This LangFlow server does not expose a compatible flow-update method "
        f"at {url} ({', '.join(rejected)})."
    )


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
        if _flow_signature(existing) == _flow_signature(flow):
            print(f"LangFlow flow already current: {flow['name']} ({existing['id']})")
            return 0
        saved = _update_flow(session, existing["id"], flow)
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

