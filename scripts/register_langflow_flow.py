"""Create or update the saved Shop Buddy flow in a running LangFlow server."""
from __future__ import annotations

import json
import os
import sys
import time
import copy
from pathlib import Path

import requests


LANGFLOW_URL = os.getenv("LANGFLOW_URL", "http://127.0.0.1:7860").rstrip("/")
FLOW_FILE = Path(__file__).resolve().parents[1] / "langflow" / "shop_buddy.flow.json"
LEGACY_FLOW_NAMES = {"Shop Buddy", "Shop_Buddy"}
MODEL_COMPONENT_TYPE = "ext:shop_buddy:ShopBuddyModelComponent@extra"
RUNTIME_MODEL_FIELDS = frozenset(
    {"openai_api_key", "openai_base_url", "openai_model", "gemini_api_key", "gemini_model"}
)


def _catalog_component(catalog: dict, component_type: str) -> dict | None:
    """Find a component definition across old and new LangFlow categories."""
    for components in catalog.values():
        if isinstance(components, dict) and isinstance(components.get(component_type), dict):
            return components[component_type]
    return None


def _replace_target_handle_field(edge: dict, old: str, new: str, field_type: str) -> None:
    target = (edge.get("data") or {}).get("targetHandle") or {}
    if target.get("fieldName") != old:
        return
    target["fieldName"] = new
    target["type"] = field_type
    target["inputTypes"] = ["LanguageModel"]
    raw_target = edge.get("targetHandle")
    if isinstance(raw_target, str):
        raw_target = raw_target.replace(f"œfieldNameœ: œ{old}œ", f"œfieldNameœ: œ{new}œ")
        raw_target = raw_target.replace("œtypeœ: œotherœ", f"œtypeœ: œ{field_type}œ")
        raw_target = raw_target.replace("œtypeœ: œmodelœ", f"œtypeœ: œ{field_type}œ")
        edge["targetHandle"] = raw_target


def adapt_flow_for_catalog(flow: dict, catalog: dict) -> dict:
    """Rebase built-in nodes when the VDI predates the standalone lfx SDK.

    LangFlow exports embed the source code for built-in components. A flow
    exported by 1.12 therefore imports ``lfx`` and cannot even be parsed by a
    1.4 evaluator. Keep the project export current, but replace Chat/Agent
    definitions with the running server's native schemas before registration.
    Custom Shop Buddy components carry their own dual-version SDK adapter.
    """
    agent_component = _catalog_component(catalog, "Agent")
    if not agent_component:
        return flow
    agent_template = agent_component.get("template") or {}
    if "model" in agent_template or "agent_llm" not in agent_template:
        return flow

    adapted = copy.deepcopy(flow)
    node_types = {"ChatInput", "ChatOutput", "Agent"}
    for node in (adapted.get("data") or {}).get("nodes", []):
        data = node.get("data") or {}
        component_type = data.get("type")
        if component_type not in node_types:
            continue
        native = _catalog_component(catalog, component_type)
        if not native:
            raise RuntimeError(f"LangFlow component catalog is missing {component_type}.")
        previous = data.get("node") or {}
        previous_template = previous.get("template") or {}
        replacement = copy.deepcopy(native)
        replacement["display_name"] = previous.get("display_name") or data.get("display_name")
        for field, definition in (replacement.get("template") or {}).items():
            if field == "code":
                continue
            old_definition = previous_template.get(field)
            if isinstance(definition, dict) and isinstance(old_definition, dict) and "value" in old_definition:
                definition["value"] = copy.deepcopy(old_definition["value"])
        if component_type == "Agent":
            model_field = replacement["template"]["agent_llm"]
            model_field["value"] = "Custom"
            model_field["input_types"] = ["LanguageModel"]
            # LangFlow 1.4's Agent refuses to run without at least one tool.
            # The orchestrator is intentionally routing-only, so give it the
            # built-in read-only date tool without adding a graph node/edge or
            # changing the five evaluator-required shopping tools.
            if node.get("id") == "Agent-orchestrator" and "add_current_date_tool" in replacement["template"]:
                replacement["template"]["add_current_date_tool"]["value"] = True
            data["_connectionMode"] = True
        data["node"] = replacement

    agent_ids = {
        node.get("id")
        for node in adapted["data"].get("nodes", [])
        if (node.get("data") or {}).get("type") == "Agent"
    }
    for edge in adapted["data"].get("edges", []):
        if edge.get("target") in agent_ids:
            _replace_target_handle_field(edge, "model", "agent_llm", "str")
    return adapted


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


def _flow_signature(flow: dict) -> tuple[str | None, str | None, str | None, frozenset[tuple], frozenset[tuple]]:
    """Return the executable graph signature, ignoring only visual metadata.

    Comparing just node IDs and edge endpoints allowed an older saved flow to
    survive after prompts, custom-component code, model settings, or tool
    wiring changed.  LangFlow would then execute that stale payload and report
    an opaque HTTP 500.  Include the component templates and full handles so a
    launcher restart always reconciles the saved flow with the repository.
    """
    data = flow.get("data") or {}

    def template_signature(node: dict) -> str:
        node_data = node.get("data") or {}
        template = copy.deepcopy((node_data.get("node") or {}).get("template") or {})
        # A reused VDI service stores the model key and proxy settings in the
        # live flow. They are deployment-local runtime configuration, not
        # exportable graph structure, so do not replace a working flow just
        # because those values are intentionally absent from the repository.
        if node_data.get("type") == MODEL_COMPONENT_TYPE:
            for field in RUNTIME_MODEL_FIELDS:
                if isinstance(template.get(field), dict):
                    template[field]["value"] = "<runtime-configuration>"
        return json.dumps(template, sort_keys=True)

    nodes = frozenset(
        (
            node.get("id"),
            (node.get("data") or {}).get("type"),
            template_signature(node),
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
    return flow.get("name"), flow.get("endpoint_name"), flow.get("description"), nodes, edges


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


def _matching_flows(flows: list[dict], desired: dict) -> list[dict]:
    """Find canonical and legacy copies that can collide at run time."""
    return [
        item
        for item in flows
        if (
            item.get("id") == desired.get("id")
            and not str(item.get("name", "")).startswith("Shop_Buddy_legacy_")
        )
        or item.get("endpoint_name") == desired.get("endpoint_name")
        or item.get("name") in LEGACY_FLOW_NAMES
    ]


def _choose_canonical(matches: list[dict], desired: dict) -> dict | None:
    """Prefer the evaluator-named flow, then the exported UUID, then endpoint."""
    return next((item for item in matches if item.get("name") == desired.get("name")), None) or next(
        (item for item in matches if item.get("id") == desired.get("id")), None
    ) or next((item for item in matches if item.get("endpoint_name") == desired.get("endpoint_name")), None)


def _archive_duplicate(session: requests.Session, duplicate: dict) -> None:
    flow_id = str(duplicate["id"])
    archived_name = f"Shop_Buddy_legacy_{flow_id[:8]}"
    response = session.patch(
        f"{LANGFLOW_URL}/api/v1/flows/{flow_id}",
        json={"name": archived_name, "endpoint_name": None},
        timeout=60,
    )
    _require_success(response, f"Archive duplicate LangFlow flow {flow_id}")
    print(f"Archived duplicate LangFlow flow: {archived_name} ({flow_id})")


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
    catalog_response = session.get(f"{LANGFLOW_URL}/api/v1/all", timeout=120)
    _require_success(catalog_response, "LangFlow component catalog lookup")
    flow = adapt_flow_for_catalog(flow, catalog_response.json())
    response = session.get(f"{LANGFLOW_URL}/api/v1/flows/", timeout=30)
    _require_success(response, "LangFlow flow lookup")
    matches = _matching_flows(response.json(), flow)
    existing = _choose_canonical(matches, flow)
    for duplicate in matches:
        if existing is None or duplicate.get("id") != existing.get("id"):
            _archive_duplicate(session, duplicate)

    if existing and _flow_signature(existing) == _flow_signature(flow):
        flow["id"] = existing["id"]
        saved = None
        action = "already current"
    else:
        # Do not patch an incompatible executable graph in place. LangFlow can
        # retain a compiled endpoint for the pre-update payload until restart,
        # which made /run/shop-buddy execute an older graph even though GET
        # /flows showed the new name and node count. Preserve the old graph as
        # a non-endpoint legacy flow, then create a fresh canonical flow.
        if existing is not None:
            _archive_duplicate(session, existing)
        create_payload = dict(flow)
        create_payload.pop("id", None)
        saved = session.post(f"{LANGFLOW_URL}/api/v1/flows/", json=create_payload, timeout=120)
        action = "created"
    if saved is not None:
        _require_success(saved, f"LangFlow flow {action}")

    verify_response = session.get(f"{LANGFLOW_URL}/api/v1/flows/", timeout=30)
    _require_success(verify_response, "LangFlow post-registration verification")
    verified_flows = verify_response.json()
    canonical = [item for item in verified_flows if item.get("name") == flow["name"]]
    endpoints = [item for item in verified_flows if item.get("endpoint_name") == flow["endpoint_name"]]
    if len(canonical) != 1 or len(endpoints) != 1 or canonical[0].get("id") != endpoints[0].get("id"):
        raise RuntimeError(
            f"Expected exactly one {flow['name']} flow owning endpoint {flow['endpoint_name']}; "
            f"found names={[item.get('id') for item in canonical]}, "
            f"endpoints={[item.get('id') for item in endpoints]}."
        )
    if _flow_signature(canonical[0]) != _flow_signature(flow):
        raise RuntimeError("LangFlow accepted the registration request but did not persist the executable graph payload.")
    print(f"LangFlow flow {action}: {flow['name']} ({canonical[0]['id']})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, requests.RequestException, RuntimeError) as exc:
        print(f"Could not register Shop Buddy in LangFlow: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

