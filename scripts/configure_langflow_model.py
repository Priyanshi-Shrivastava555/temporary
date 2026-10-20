"""Configure the live Shop_Buddy model from a local .env without exporting secrets.

This is used only when Phase 1 reuses the VDI-provided LangFlow service. That
service does not inherit this repository's environment, so the saved custom
model needs its OpenAI proxy configuration set through LangFlow's local API.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.register_langflow_flow import _require_success, _update_flow, authenticated_session


MODEL_COMPONENT_TYPE = "ext:shop_buddy:ShopBuddyModelComponent@extra"
FLOW_NAME = "Shop_Buddy"
FLOW_ENDPOINT = "shop-buddy"
OPENAI_VARIABLE_NAME = "SHOP_BUDDY_OPENAI_API_KEY"


def apply_openai_configuration(flow: dict, *, api_key: str, base_url: str, model: str) -> dict:
    """Return a copy of ``flow`` with its Shop Buddy model configured."""
    configured = copy.deepcopy(flow)
    for node in (configured.get("data") or {}).get("nodes") or []:
        data = node.get("data") or {}
        if data.get("type") != MODEL_COMPONENT_TYPE:
            continue
        template = (data.get("node") or {}).get("template") or {}
        for field, value in {
            "openai_api_key": api_key,
            "openai_base_url": base_url,
            "openai_model": model,
        }.items():
            if field not in template:
                raise RuntimeError(f"The live model is missing its {field} field.")
            template[field]["value"] = value
        return configured
    raise RuntimeError("Could not find the Shop Buddy model in the live flow.")


def flow_records(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get("items", payload)
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def upsert_credential_variable(
    session,
    *,
    name: str,
    value: str,
    default_field: str,
) -> str:
    """Store a credential using LangFlow 1.4's encrypted variable API."""
    response = session.get("http://127.0.0.1:7860/api/v1/variables/", timeout=30)
    _require_success(response, "LangFlow variable lookup")
    variables = flow_records(response.json())
    existing = next((item for item in variables if item.get("name") == name), None)
    payload = {
        "name": name,
        "value": value,
        "default_fields": [default_field],
        "type": "Credential",
    }
    if existing and existing.get("id"):
        payload["id"] = existing["id"]
        response = session.patch(
            f"http://127.0.0.1:7860/api/v1/variables/{existing['id']}",
            json=payload,
            timeout=30,
        )
        operation = "LangFlow credential update"
    else:
        response = session.post(
            "http://127.0.0.1:7860/api/v1/variables/",
            json=payload,
            timeout=30,
        )
        operation = "LangFlow credential creation"
    _require_success(response, operation)
    return name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()

    environment = {name: str(value or "").strip() for name, value in dotenv_values(args.env_file).items()}
    api_key = environment.get("OPENAI_API_KEY", "")
    base_url = environment.get("OPENAI_BASE_URL", "").rstrip("/")
    model = environment.get("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key or not base_url or not model:
        raise RuntimeError("OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL must be set to configure reused LangFlow.")

    session = authenticated_session()
    response = session.get("http://127.0.0.1:7860/api/v1/flows/", timeout=30)
    _require_success(response, "LangFlow flow lookup")
    flow = next(
        (
            item
            for item in flow_records(response.json())
            if item.get("name") == FLOW_NAME and item.get("endpoint_name") == FLOW_ENDPOINT
        ),
        None,
    )
    if not flow or not flow.get("id"):
        raise RuntimeError("Expected exactly one saved Shop_Buddy flow with endpoint shop-buddy.")

    response = session.get(f"http://127.0.0.1:7860/api/v1/flows/{flow['id']}", timeout=30)
    _require_success(response, "LangFlow flow read")
    full_flow = response.json()
    model_node = next(
        (
            node
            for node in (full_flow.get("data") or {}).get("nodes") or []
            if (node.get("data") or {}).get("type") == MODEL_COMPONENT_TYPE
        ),
        None,
    )
    if model_node is None:
        raise RuntimeError("Could not find the Shop Buddy model in the live flow.")
    key_field = model_node["data"]["node"]["template"].get("openai_api_key") or {}
    api_key_value = api_key
    if key_field.get("load_from_db") is True:
        api_key_value = upsert_credential_variable(
            session,
            name=OPENAI_VARIABLE_NAME,
            value=api_key,
            default_field="openai_api_key",
        )
    configured = apply_openai_configuration(
        full_flow,
        api_key=api_key_value,
        base_url=base_url,
        model=model,
    )
    _update_flow(session, str(flow["id"]), configured)
    print("Configured the live Shop_Buddy model from .env without exporting credentials.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Could not configure the live Shop_Buddy model: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
