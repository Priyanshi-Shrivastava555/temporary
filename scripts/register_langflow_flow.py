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


def _response_detail(response: requests.Response) -> str:
    try:
        content = json.dumps(response.json(), default=str)
    except ValueError:
        content = response.text
    return " ".join(content.split())[:2000] or "<empty response body>"


def _require_success(response: requests.Response, operation: str) -> requests.Response:
    if not response.ok:
        raise RuntimeError(
            f"{operation} failed with HTTP {response.status_code} for {response.request.method} "
            f"{response.url}. Response: {_response_detail(response)}"
        )
    return response


def _flow_signature(flow: dict) -> tuple[str | None, str | None, frozenset[tuple], frozenset[tuple]]:
    """Return the executable graph signature, ignoring only visual metadata.

    Comparing just node IDs and edge endpoints allowed an older saved flow to
    survive after prompts, custom-component code, model settings, or tool
    wiring changed.  LangFlow would then execute that stale payload and report
    an opaque HTTP 500.  Include the component templates and full handles so a
    launcher restart always reconciles the saved flow with the repository.
    """
    data = flow.get("data") or {}
    nodes = frozenset(
        (
            node.get("id"),
            (node.get("data") or {}).get("type"),
            json.dumps(((node.get("data") or {}).get("node") or {}).get("template") or {}, sort_keys=True),
            json.dumps(((node.get("data") or {}).get("node") or {}).get("outputs") or [], sort_keys=True),
        )
        for node in data.get("nodes", [])
    )
    edges = frozenset(
        (
            edge.get("source"),
            edge.get("target"),
            edge.get("sourceHandle"),
            edge.get("targetHandle"),
        )
        for edge in data.get("edges", [])
    )
    return flow.get("name"), flow.get("endpoint_name"), nodes, edges


def _update_flow(session: requests.Session, flow_id: str, flow: dict) -> requests.Response:
    """Support LangFlow releases that expose PATCH, PUT, or both."""
    url = f"{LANGFLOW_URL}/api/v1/flows/{flow_id}"
    rejected: list[str] = []
    for method in ("patch", "put"):
        response = session.request(method, url, json=flow, timeout=120)
        if response.status_code in {404, 405, 422}:
            rejected.append(f"{method.upper()}={response.status_code}")
            continue
        _require_success(response, "LangFlow flow update")
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
            _require_success(response, "LangFlow auto-login")
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
    _require_success(response, "LangFlow flow lookup")
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
    _require_success(saved, f"LangFlow flow {action}")
    payload = saved.json()
    print(f"LangFlow flow {action}: {payload.get('name', flow['name'])} ({payload.get('id', flow.get('id'))})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, requests.RequestException, RuntimeError) as exc:
        print(f"Could not register Shop Buddy in LangFlow: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

