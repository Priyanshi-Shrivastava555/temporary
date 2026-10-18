"""Regenerate the Shop Buddy flow from the installed LangFlow component schemas.

Run this only while ``start-langflow.cmd`` is serving localhost:7860.  Building
from LangFlow's own schemas keeps the export compatible with the pinned version
instead of hand-writing partial React Flow nodes.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import argparse
from pathlib import Path

import requests


def _local_model_component() -> dict:
    """Build the model schema locally when the running server predates it."""
    from lfx.custom.utils import create_component_template

    source = Path(__file__).resolve().parents[1] / "langflow" / "components" / "shop_buddy" / "model.py"
    module_name = "shop_buddy_model_component"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    component, _ = create_component_template(
        component_extractor=module.ShopBuddyModelComponent(),
        module_name="shop_buddy",
    )
    return component


LANGFLOW_URL = "http://127.0.0.1:7860"
FLOW_ID = "a9d23675-97bd-4c72-8a32-9d8815fab311"
FLOW_NAME = "Shop_Buddy"
FLOW_DESCRIPTION = (
    "UrbanNest agentic shopping flow with orchestration, search, cart management, "
    "and five FastAPI tools. Registration schema v2."
)
SIMPLE_AGENT_ID = "f05ffa00-25ed-4be6-9922-6d7bfa0c83ed"
SEPARATOR = "œ"


def _authenticated_session() -> requests.Session:
    session = requests.Session()
    response = session.get(f"{LANGFLOW_URL}/api/v1/auto_login", timeout=30)
    response.raise_for_status()
    session.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return session


def _configure_node(node: dict, node_id: str, x: int, y: int, display_name: str) -> dict:
    node = copy.deepcopy(node)
    node["id"] = node_id
    node["position"] = {"x": x, "y": y}
    node["positionAbsolute"] = {"x": x, "y": y}
    node["selected"] = False
    node["dragging"] = False
    node["data"]["id"] = node_id
    node["data"]["display_name"] = display_name
    node["data"]["node"]["display_name"] = display_name
    return node


def _source_handle(data_type: str, node_id: str, name: str, output_types: list[str]) -> str:
    types = ", ".join(f"{SEPARATOR}{item}{SEPARATOR}" for item in output_types)
    return (
        f"{{{SEPARATOR}dataType{SEPARATOR}: {SEPARATOR}{data_type}{SEPARATOR}, "
        f"{SEPARATOR}id{SEPARATOR}: {SEPARATOR}{node_id}{SEPARATOR}, "
        f"{SEPARATOR}name{SEPARATOR}: {SEPARATOR}{name}{SEPARATOR}, "
        f"{SEPARATOR}output_types{SEPARATOR}: [{types}]}}"
    )


def _target_handle(field_name: str, node_id: str, input_types: list[str], field_type: str) -> str:
    types = ", ".join(f"{SEPARATOR}{item}{SEPARATOR}" for item in input_types)
    return (
        f"{{{SEPARATOR}fieldName{SEPARATOR}: {SEPARATOR}{field_name}{SEPARATOR}, "
        f"{SEPARATOR}id{SEPARATOR}: {SEPARATOR}{node_id}{SEPARATOR}, "
        f"{SEPARATOR}inputTypes{SEPARATOR}: [{types}], "
        f"{SEPARATOR}type{SEPARATOR}: {SEPARATOR}{field_type}{SEPARATOR}}}"
    )


def _edge(
    source: str,
    target: str,
    source_type: str,
    output_name: str,
    output_types: list[str],
    target_field: str,
    input_types: list[str],
    field_type: str,
) -> dict:
    source_data = {
        "dataType": source_type,
        "id": source,
        "name": output_name,
        "output_types": output_types,
    }
    target_data = {
        "fieldName": target_field,
        "id": target,
        "inputTypes": input_types,
        "type": field_type,
    }
    source_handle = _source_handle(source_type, source, output_name, output_types)
    target_handle = _target_handle(target_field, target, input_types, field_type)
    compact_source = source_handle.replace(" ", "")
    compact_target = target_handle.replace(" ", "")
    return {
        "id": f"reactflow__edge-{source}{compact_source}-{target}{compact_target}",
        "source": source,
        "target": target,
        "sourceHandle": source_handle,
        "targetHandle": target_handle,
        "data": {"sourceHandle": source_data, "targetHandle": target_data},
        "animated": False,
        "className": "",
        "selected": False,
    }


def _extension_node(wrapper: dict, component: dict, cache_key: str, node_id: str, x: int, y: int) -> dict:
    node = _configure_node(wrapper, node_id, x, y, component["display_name"])
    node["data"]["type"] = cache_key
    node["data"]["node"] = copy.deepcopy(component)
    node["data"]["node"]["tool_mode"] = True
    node["data"]["node"]["outputs"] = [
        {
            "allows_loop": False,
            "cache": True,
            "display_name": "Toolset",
            "group_outputs": False,
            "hidden": None,
            "loop_types": None,
            "method": "to_toolkit",
            "name": "component_as_tool",
            "options": None,
            "required_inputs": None,
            "selected": "Tool",
            "tool_mode": True,
            "types": ["Tool"],
            "value": "__UNDEFINED__",
        }
    ]
    node["data"]["node"]["template"]["api_url"]["value"] = "http://127.0.0.1:8000"
    node["data"]["id"] = node_id
    return node


def _component_node(
    wrapper: dict,
    component: dict,
    cache_key: str,
    node_id: str,
    x: int,
    y: int,
    display_name: str,
) -> dict:
    node = _configure_node(wrapper, node_id, x, y, display_name)
    node["data"]["type"] = cache_key
    node["data"]["node"] = copy.deepcopy(component)
    node["data"]["node"]["display_name"] = display_name
    node["data"]["id"] = node_id
    return node


def synchronize_local_model(flow: dict) -> dict:
    """Refresh evaluator identity and embedded model without a running server."""
    flow["name"] = FLOW_NAME
    flow["description"] = FLOW_DESCRIPTION
    component = _local_model_component()
    node = next(
        item
        for item in flow["data"]["nodes"]
        if (item.get("data") or {}).get("type") == "ext:shop_buddy:ShopBuddyModelComponent@extra"
    )
    node["data"]["node"] = copy.deepcopy(component)
    node["data"]["node"]["display_name"] = "Shop Buddy AI Model"
    for agent in (
        item for item in flow["data"]["nodes"] if (item.get("data") or {}).get("type") == "Agent"
    ):
        # This is the flag LangFlow itself sets when an external LanguageModel
        # is connected to a ModelInput. It keeps the saved canvas and runtime
        # interpretation aligned across supported LangFlow installations.
        agent["data"]["_connectionMode"] = True
    return flow


def build_flow() -> dict:
    session = _authenticated_session()
    examples_response = session.get(f"{LANGFLOW_URL}/api/v1/flows/basic_examples/", timeout=120)
    examples_response.raise_for_status()
    examples = examples_response.json()
    simple_agent = next(flow for flow in examples if flow["id"] == SIMPLE_AGENT_ID)

    all_response = session.get(f"{LANGFLOW_URL}/api/v1/all", timeout=120)
    all_response.raise_for_status()
    all_components = all_response.json()

    wrapper = next(node for node in simple_agent["data"]["nodes"] if node["data"]["type"] == "URLComponent")

    chat_input = _component_node(
        wrapper, all_components["input_output"]["ChatInput"], "ChatInput",
        "ChatInput-shopbuddy", 0, 260, "Chat Input",
    )
    orchestrator = _component_node(
        wrapper, all_components["models_and_agents"]["Agent"], "Agent",
        "Agent-orchestrator", 420, 260, "Orchestration Agent",
    )
    search_agent = _component_node(
        wrapper, all_components["models_and_agents"]["Agent"], "Agent",
        "Agent-search", 850, 120, "Product Search Agent",
    )
    cart_agent = _component_node(
        wrapper, all_components["models_and_agents"]["Agent"], "Agent",
        "Agent-cart", 1280, 260, "Cart Management Agent",
    )
    chat_output = _component_node(
        wrapper, all_components["input_output"]["ChatOutput"], "ChatOutput",
        "ChatOutput-shopbuddy", 1710, 260, "Chat Output",
    )
    model_cache_key = "ext:shop_buddy:ShopBuddyModelComponent@extra"
    # Always embed the checked-in source. A running LangFlow process may still
    # have an older component cached even though this repository has been
    # updated, which would otherwise recreate the same stale-flow 500.
    model_component = _local_model_component()
    model_node = _component_node(
        wrapper, model_component, model_cache_key,
        "ShopBuddyModel-shopbuddy", 430, -250, "Shop Buddy AI Model",
    )

    prompts = {
        "Agent-orchestrator": (
            "Classify the request as search, add, update, delete, view, or combined. Preserve every product, "
            "quantity, budget, and session detail for the downstream agents. Do not claim that a backend action "
            "succeeded; only the specialized agents and tools may do that."
        ),
        "Agent-search": (
            "You are UrbanNest's product-search specialist. Use Search Products whenever discovery or product "
            "resolution is needed. Respect requirements and budget. Return only products supplied by the tool, "
            "including stable product IDs for downstream cart work."
        ),
        "Agent-cart": (
            "You are UrbanNest's cart specialist and final responder. Use the connected cart tools for every add, "
            "update, delete, or view operation. Use upstream product IDs when available. Never invent a successful "
            "operation; summarize only structured tool results. For search-only requests, return the upstream "
            "recommendations without mutating the cart."
        ),
    }
    for node in (orchestrator, search_agent, cart_agent):
        node["data"]["_connectionMode"] = True
        node["data"]["node"]["template"]["system_prompt"]["value"] = prompts[node["id"]]
        node["data"]["node"]["template"]["add_current_date_tool"]["value"] = False
        node["data"]["node"]["template"]["add_calculator_tool"]["value"] = False

    tool_specs = [
        ("ext:shop_buddy:SearchProductsComponent@extra", "SearchProducts-tool", 850, -230, "Agent-search"),
        ("ext:shop_buddy:AddProductToCartComponent@extra", "AddProductToCart-tool", 1080, 620, "Agent-cart"),
        ("ext:shop_buddy:UpdateCartItemComponent@extra", "UpdateCartItem-tool", 1330, 620, "Agent-cart"),
        ("ext:shop_buddy:DeleteCartItemComponent@extra", "DeleteCartItem-tool", 1580, 620, "Agent-cart"),
        ("ext:shop_buddy:GetCartItemsComponent@extra", "GetCartItems-tool", 1830, 620, "Agent-cart"),
    ]
    tool_nodes = [
        _extension_node(wrapper, all_components["shop_buddy"][cache_key], cache_key, node_id, x, y)
        for cache_key, node_id, x, y, _target in tool_specs
    ]

    edges = [
        _edge("ChatInput-shopbuddy", "Agent-orchestrator", "ChatInput", "message", ["Message"], "input_value", ["Message"], "str"),
        _edge("Agent-orchestrator", "Agent-search", "Agent", "response", ["Message"], "input_value", ["Message"], "str"),
        _edge("Agent-search", "Agent-cart", "Agent", "response", ["Message"], "input_value", ["Message"], "str"),
        _edge("Agent-cart", "ChatOutput-shopbuddy", "Agent", "response", ["Message"], "input_value", ["Data", "JSON", "DataFrame", "Table", "Message"], "other"),
    ]
    for target in ("Agent-orchestrator", "Agent-search", "Agent-cart"):
        edges.append(
            _edge(
                "ShopBuddyModel-shopbuddy", target, model_cache_key, "model", ["LanguageModel"],
                "model", ["LanguageModel"], "model",
            )
        )
    for cache_key, node_id, _x, _y, target in tool_specs:
        edges.append(_edge(node_id, target, cache_key, "component_as_tool", ["Tool"], "tools", ["Tool"], "other"))

    return {
        "id": FLOW_ID,
        "name": FLOW_NAME,
        "description": FLOW_DESCRIPTION,
        "endpoint_name": "shop-buddy",
        "is_component": False,
        "data": {
            "nodes": [chat_input, model_node, orchestrator, search_agent, cart_agent, chat_output, *tool_nodes],
            "edges": edges,
            "viewport": {"x": 80, "y": 180, "zoom": 0.65},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sync-local-model",
        action="store_true",
        help="Refresh the embedded Shop Buddy model source without contacting LangFlow.",
    )
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "langflow" / "shop_buddy.flow.json"
    if args.sync_local_model:
        flow = synchronize_local_model(json.loads(output.read_text(encoding="utf-8")))
        output.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Synchronized the local model in {output}.")
        return 0
    try:
        flow = build_flow()
    except (requests.RequestException, KeyError, StopIteration) as exc:
        print(f"Could not build LangFlow export: {exc!r}", file=sys.stderr)
        return 1
    output.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {output} ({len(flow['data']['nodes'])} nodes, {len(flow['data']['edges'])} edges).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
